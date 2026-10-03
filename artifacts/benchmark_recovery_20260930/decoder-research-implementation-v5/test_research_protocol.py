"""Synthetic protocol/pipe/bounds tests only. No GI, source ELF, Docker or decoder."""
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import research_protocol as p
import controller


def contract():
    return {'source_process_id':'research-source-front_gate-01','run_id':'research-decoder-01',
        'dataset_id':'kpp_iss_publication_v3_h264','stream_id':0,'source_sha256':'a'*64,
        'source_duration_ns':33120000000000,'window_start_ms':1000,'window_end_ms':32500}


def event(seq=1,payload=b'AU',size=None):
    c=contract(); aupts=(seq-1)*1666666
    return {'protocol_version':1,'source_process_id':c['source_process_id'],'sequence':seq,
        'run_id':c['run_id'],'dataset_id':c['dataset_id'],'stream_id':c['stream_id'],
        'admission_id':f"{c['run_id']}:0:admission:{seq}",
        'input_frame_key':f"{c['dataset_id']}:0:{c['source_sha256']}:0:{aupts}",
        'source_sha256':c['source_sha256'],'source_cycle':0,'access_unit_pts_ns':aupts,
        'payload_sha256':hashlib.sha256(payload).hexdigest(),
        'payload_size_bytes':len(payload) if size is None else size,
        'schedule_offset_ns':(seq-1)*p.CADENCE_MIN,'admission_timestamp_ms':1000+(seq-1)*1000,
        'event_provenance':'native_common_source_coordinator'}


def packet(e,payload=b'AU',duration=p.CADENCE_MIN,dts=p.MISSING,**overrides):
    text=[e[k].encode() for k in ('admission_id','input_frame_key','payload_sha256')]
    fields={'magic':b'VASTAU01','version':1,'flags':1,'seq':e['sequence'],'cycle':0,
        'aupts':e['access_unit_pts_ns'],'pts':e['access_unit_pts_ns']*600,'dts':dts,
        'duration':duration,'a':len(text[0]),'k':len(text[1]),'h':len(text[2]),'size':len(payload)}
    fields.update(overrides)
    return p.HEADER.pack(*fields.values())+b''.join(text)+payload


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.evidence=p.Evidence(Path(self.temp.name)/'evidence')
        self.raw=self.evidence.open('raw.bin',p.RAW_MAX)
        self.abort=threading.Event()
        self.deadline=time.monotonic()+3
        self.gate=p.AdmissionGate(contract())

    def tearDown(self):
        self.evidence.close();self.temp.cleanup()

    def receive(self,raw):
        r,w=os.pipe()
        os.write(w,raw);os.close(w)
        try:return self.gate.receive(r,self.deadline,self.abort,self.evidence,self.raw)
        finally:os.close(r)

    def test_current_binary_requires_its_enabling_ack_and_next_declaration_waits_previous(self):
        # Synthetic producer mirrors the proven source causal order; no stock source is executed.
        ack_r,ack_w=os.pipe(); binary_r,binary_w=os.pipe()
        enabled=threading.Event();completed=threading.Event();errors=[]
        def producer():
            try:
                self.assertEqual(os.read(ack_r,64),b'1 ACK 1\n')
                enabled.set()
                raw=packet(event())
                for chunk in (raw[:17],raw[17:80],raw[80:]):os.write(binary_w,chunk)
            except BaseException as exc:errors.append(exc)
            finally:os.close(ack_r);os.close(binary_w)
        source=threading.Thread(target=producer);source.start()
        self.gate.declare(event(),self.deadline,self.abort)
        self.assertFalse(enabled.is_set())
        os.write(ack_w,b'1 ACK 1\n');os.close(ack_w)
        received=self.gate.receive(binary_r,self.deadline,self.abort,self.evidence,self.raw)
        os.close(binary_r)
        def next_declaration():
            try:self.gate.declare(event(2),self.deadline,self.abort);completed.set()
            except BaseException as exc:errors.append(exc)
        pending=threading.Thread(target=next_declaration);pending.start()
        self.assertFalse(completed.wait(0.03))
        # This release is packet validation, with no appsrc/push/decoder call.
        self.gate.mark_validated(received)
        self.assertTrue(completed.wait(1))
        pending.join(1);source.join(1)
        self.assertFalse(errors);self.assertEqual(received['access_unit_dts_ns'],p.MISSING)
        self.assertEqual((self.evidence.directory/'raw.bin').read_bytes(),packet(event()))

    def test_header_oversize_and_declared_length_mismatch_before_payload_allocation(self):
        self.gate.declare(event(),self.deadline,self.abort)
        for raw in (packet(event(),size=p.PAYLOAD_MAX+1)[:80],packet(event(),a=8192)[:80]):
            previous=self.evidence.files[self.raw][0]
            sizes=[]
            original=p.read_exact
            def traced(fd,size,*args,**kwargs):
                sizes.append(size);return original(fd,size,*args,**kwargs)
            with patch.object(p,'read_exact',traced):
                with self.assertRaises(p.ResearchError):self.receive(raw)
            self.assertEqual(sizes,[80]);self.assertEqual(self.evidence.files[self.raw][0],previous+80)

    def test_digest_identity_flags_and_cadence_fail_closed(self):
        self.gate.declare(event(),self.deadline,self.abort)
        cases=[packet(event(),payload=b'XX'),packet(event(),flags=2),packet(event(),pts=1),
            packet(event(),duration=0),packet(event(),cycle=1)]
        for raw in cases:
            with self.assertRaises(p.ResearchError):self.receive(raw)
        self.assertEqual(self.gate.validated,{})

    def test_true_unsigned_dts_and_duration_are_retained(self):
        self.gate.declare(event(),self.deadline,self.abort)
        received=self.receive(packet(event(),dts=p.MISSING-1))
        self.assertEqual(received['access_unit_dts_ns'],p.MISSING-1)
        self.assertEqual(received['duration_ns'],p.CADENCE_MIN)
        self.assertEqual(received['payload'],b'AU')

    def test_raw_aggregate_rejected_before_second_ack(self):
        first=event(size=p.PAYLOAD_MAX)
        self.gate.declare(first,self.deadline,self.abort)
        self.gate.mark_validated({'sequence':1,'duration_ns':p.CADENCE_MIN})
        previous=self.gate.reserved_raw_bytes
        with self.assertRaisesRegex(p.ResearchError,'before ACK'):
            self.gate.declare(event(2,size=p.PAYLOAD_MAX),self.deadline,self.abort)
        self.assertEqual(len(self.gate.declared),1);self.assertEqual(self.gate.reserved_raw_bytes,previous)

    def test_exact32_no_extra_duplicate_foreign_or_late_admission(self):
        for seq in range(1,33):
            current=event(seq)
            self.gate.declare(current,self.deadline,self.abort)
            self.gate.mark_validated({'sequence':seq,'duration_ns':p.CADENCE_MIN})
        with self.assertRaises(p.ResearchError):self.gate.declare(event(33),self.deadline,self.abort)
        with self.assertRaises(p.ResearchError):self.gate.declare(event(1),self.deadline,self.abort)
        for current in (dict(event(1),stream_id=True),dict(event(1),source_process_id='foreign'),
                dict(event(1),admission_timestamp_ms=32500),dict(event(1),duration_ns=1)):
            with self.assertRaises(p.ResearchError):p.AdmissionGate(contract()).declare(current,self.deadline,self.abort)

    def test_wrong_second_schedule_rejected_using_received_duration(self):
        self.gate.declare(event(),self.deadline,self.abort)
        self.gate.mark_validated({'sequence':1,'duration_ns':p.CADENCE_MIN})
        with self.assertRaises(p.ResearchError):self.gate.declare(dict(event(2),schedule_offset_ns=1),self.deadline,self.abort)

    def test_clean_eof_truncation_and_invalid_json(self):
        self.assertIsNone(self.receive(b''))
        with self.assertRaises(p.ResearchError):self.receive(b'VAST')
        self.assertEqual((self.evidence.directory/'raw.bin').read_bytes(),b'VAST')
        for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'[]',b'x'*(p.EVENT_MAX+1)):
            with self.assertRaises(p.ResearchError):p.strict_object(raw)

    def test_truncated_text_payload_and_source_line_preserve_every_consumed_byte(self):
        self.gate.declare(event(),self.deadline,self.abort)
        for raw in (packet(event())[:85],packet(event())[:-1]):
            previous=(self.evidence.directory/'raw.bin').read_bytes()
            with self.assertRaises(p.ResearchError):self.receive(raw)
            self.assertEqual((self.evidence.directory/'raw.bin').read_bytes(),previous+raw)
        r,w=os.pipe();os.write(w,b'first\npartial');os.close(w);retained=[]
        try:
            reader=p.LineReader(r,self.deadline,self.abort,retained.append)
            self.assertEqual(reader.read(),b'first\n')
            with self.assertRaises(p.ResearchError):reader.read()
            self.assertEqual(b''.join(retained),b'first\npartial')
        finally:os.close(r)

    def test_active_rgb_excludes_padding_and_rejects_bad_layout_before_hash(self):
        raw=bytearray(b'xxxABCDEFzzGHIJKLzz')
        first=p.active_rgb_digest(raw,2,2,8,3)
        raw[9]=ord('Q');raw[17]=ord('Q')
        self.assertEqual(first,p.active_rgb_digest(raw,2,2,8,3))
        raw[3]=ord('Q')
        self.assertNotEqual(first,p.active_rgb_digest(raw,2,2,8,3))
        for layout in ((2,2,5,3),(2,3,8,3),(2,2,8,-1)):
            with self.assertRaises(p.ResearchError):p.active_rgb_digest(raw,*layout)

    def test_pair_complete_multiset_pixels_caps_order_and_tail_are_required(self):
        rows=[dict(pts=i,width=2,height=2,format='RGB',caps='RGB',caps_features=['memory:SystemMemory'],
            pixel_sha256=str(i)) for i in range(32)]
        self.assertTrue(p.compare_outputs(rows,[dict(x) for x in rows],list(range(32))))
        for changed in (rows[:-1],rows[:-1]+[dict(rows[0])],list(reversed(rows)),
                rows[:-1]+[dict(rows[-1],pixel_sha256='changed-tail')],
                rows[:-1]+[dict(rows[-1],caps_features=['foreign'])]):
            with self.assertRaises(p.ResearchError):p.compare_outputs(rows,changed,list(range(32)))

    def test_actual_sink_eos_keeps_fixed_central_cohort_and_marks_flush_insufficient(self):
        packets=[{'sequence':i+1,'transport_pts_ns':i} for i in range(32)]
        entries={i:100+i for i in range(32)};exits={i:200+i for i in range(32)}
        timings=p.decoder_timings(entries,exits,packets,[210])
        self.assertEqual([r['original_sequence'] for r in timings if r['cohort']=='central'],list(range(9,25)))
        central=[r for r in timings if r['cohort']=='central']
        self.assertTrue(any(r['after_actual_decoder_sink_eos'] for r in central))
        self.assertEqual(len(timings),32)
        with self.assertRaises(p.ResearchError):p.decoder_timings(entries,exits,packets,[])
        with self.assertRaises(p.ResearchError):p.decoder_timings(entries,exits,packets,[210,211])

    def test_decoder_clock_negative_and_missing_join_reject(self):
        packets=[{'sequence':i+1,'transport_pts_ns':i} for i in range(32)]
        entries={i:100+i for i in range(32)};exits={i:200+i for i in range(32)}
        with self.assertRaises(p.ResearchError):p.decoder_timings(entries,dict(exits)|{3:0},packets,[250])
        with self.assertRaises(p.ResearchError):p.decoder_timings(entries,{i:v for i,v in exits.items() if i!=31},packets,[250])

    def test_evidence_caps_reserve_failure_receipt_and_preserve_failed_prefix(self):
        tiny=self.evidence.open('tiny',2)
        self.evidence.append(tiny,b'AB')
        with self.assertRaises(p.ResearchError):self.evidence.append(tiny,b'C')
        self.assertEqual((self.evidence.directory/'tiny').read_bytes(),b'AB')
        with patch.object(p,'EVENT_COUNT',3):
            self.evidence.event('first');self.evidence.event('second')
            with self.assertRaises(p.ResearchError):self.evidence.event('third')
        descriptor=self.evidence.document('failure.json',{'failed':True,'accepted':False},final=True)
        self.assertTrue(descriptor['size_bytes']>0)
        with self.assertRaises(FileExistsError):p.Evidence(self.evidence.directory)

    def test_held_file_and_ancestor_epochs_reject_mutation_and_rename(self):
        parent=Path(self.temp.name)/'held';parent.mkdir();file=parent/'input';file.write_bytes(b'fixed')
        pin=p.Pin(file)
        try:
            pin.verify(rehash=True)
            file.write_bytes(b'changed')
            with self.assertRaises(p.ResearchError):pin.verify()
        finally:pin.close()
        file.write_bytes(b'fixed');pin=p.Pin(file)
        try:
            parent.rename(parent.with_name('moved'));parent.mkdir();file.write_bytes(b'fixed')
            with self.assertRaises(p.ResearchError):pin.verify()
        finally:pin.close()

    def test_post_receipt_crossing_is_immutable_failed_and_cannot_enable_next_run(self):
        bounded=p.Evidence(Path(self.temp.name)/'receipt-cap',2*p.EVENT_MAX+20)
        try:
            raw=bounded.open('prefix',21)
            bounded.append(raw,b'A'*20)
            with self.assertRaises(p.ResearchError):bounded.append(raw,b'B')
            receipt=bounded.document('terminal.v1.json',{'run_successful':True,'accepted':False},final=True)
            bounded.close()
            original=(bounded.directory/'terminal.v1.json').read_bytes()
            with patch.object(p.time,'monotonic',return_value=99):
                self.assertEqual(p.post_receipt_deadline(bounded,receipt,0,100,'run',100),(True,None))
            with patch.object(p.time,'monotonic',return_value=100.001):
                permitted,failure=p.post_receipt_deadline(bounded,receipt,0,120,'run',100)
            self.assertFalse(permitted)
            self.assertEqual((bounded.directory/'terminal.v1.json').read_bytes(),original)
            facts=p.verify_seal(p.strict_object(Path(failure['path']).read_bytes()))
            self.assertTrue(facts['failed']);self.assertFalse(facts['original_execution_completed'])
            self.assertEqual(facts['provisional_terminal'],receipt)
            self.assertGreater(facts['observed_after_final_close_monotonic_s'],facts['cleanup_deadline_monotonic_s'])
            self.assertFalse(bounded.streams)
        finally:bounded.close()

    def test_external_watchdog_does_not_complete_partial_or_unsealed_phase_file(self):
        c=controller.Controller.__new__(controller.Controller)
        path=Path(self.temp.name)/'phase.json'
        path.write_bytes(b'')
        self.assertIsNone(c.completed_document(path,'phase'))
        path.write_bytes(b'{"artifact_kind":"phase"}')
        self.assertIsNone(c.completed_document(path,'phase'))
        path.write_bytes(p.canonical(p.seal({'artifact_kind':'phase','elapsed_s':3})))
        self.assertEqual(c.completed_document(path,'phase')['elapsed_s'],3)
        with self.assertRaises(p.ResearchError):c.completed_document(path,'foreign')

    def test_external_previous_run_needs_sealed_terminal_before_next_start(self):
        c=controller.Controller.__new__(controller.Controller)
        c.destination=Path(self.temp.name)/'owner';(c.destination/'guest').mkdir(parents=True)
        c.evidence=self.evidence
        for index in (1,2):
            folder=c.destination/'guest'/f'run-{index:02d}';folder.mkdir()
            (folder/'run-started.v1.json').write_bytes(p.canonical(p.seal({
                'artifact_kind':'vast_decoder_research_run_started_v1','run':index,
                'guest_elapsed_at_start_s':index})))
        (c.destination/'guest/run-01/terminal.v1.json').write_bytes(b'')
        with self.assertRaises(p.ResearchError):c.monitor_namespaces()
        (c.destination/'guest/run-01/terminal.v1.json').write_bytes(p.canonical(p.seal({
            'artifact_kind':'vast_decoder_research_run_terminal_v1','run':1,'elapsed_s':35,'run_successful':True})))
        active=c.monitor_namespaces()
        self.assertEqual(active[0][1]['run'],2)

    def test_bounded_auxiliary_real_python_child_drains_both_pipes_to_eof(self):
        # Explicit synthetic observer fixture: actual Python ELF, no Docker socket/daemon ownership.
        c=controller.Controller.__new__(controller.Controller)
        c.engine=p.Pin(Path(sys.executable));c.evidence=self.evidence;c.abort=threading.Event()
        c.errors=[];c.sequence=0;c.reserved_at=time.time_ns();c.environment={'PATH':'/usr/bin:/bin'}
        c.check_socket=lambda:c.engine.verify()
        try:
            rc,out,err=c.command(['-I','-B','-c','import os;os.write(1,b"A"*65536);os.write(2,b"B"*65536)'],timeout=2)
            self.assertEqual(rc,0);self.assertEqual(out,b'A'*65536);self.assertEqual(err,b'B'*65536)
        finally:c.engine.close()

    def test_bounded_auxiliary_timeout_retains_original_failed_child(self):
        c=controller.Controller.__new__(controller.Controller)
        c.engine=p.Pin(Path(sys.executable));c.evidence=self.evidence;c.abort=threading.Event()
        c.errors=[];c.sequence=0;c.reserved_at=time.time_ns();c.environment={'PATH':'/usr/bin:/bin'}
        c.check_socket=lambda:c.engine.verify()
        try:
            with self.assertRaises(p.ResearchError):
                c.command(['-I','-B','-c','import os,time;os.write(1,b"original-prefix");time.sleep(2)'],timeout=0.1)
            facts=p.verify_seal(p.strict_object((self.evidence.directory/'engine-01.v1.json').read_bytes(),p.METADATA_MAX))
            self.assertTrue(facts['timed_out']);self.assertNotEqual(facts['returncode'],0)
            self.assertEqual((self.evidence.directory/'engine-01.stdout').read_bytes(),b'original-prefix')
        finally:c.engine.close()


if __name__=='__main__':unittest.main(verbosity=2)
