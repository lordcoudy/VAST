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
        c.mode='research'
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
        c.mode='research'
        c.destination=Path(self.temp.name)/'owner';(c.destination/'guest').mkdir(parents=True)
        c.evidence=self.evidence
        for index,name in ((1,'run-01-front_gate-default'),(2,'run-02-front_gate-zero')):
            folder=c.destination/'guest'/name;folder.mkdir()
            (folder/'run-started.v1.json').write_bytes(p.canonical(p.seal({
                'artifact_kind':'vast_decoder_research_run_started_v1','run':index,
                'guest_elapsed_at_start_s':index})))
        (c.destination/'guest/run-01-front_gate-default/terminal.v1.json').write_bytes(b'')
        with self.assertRaises(p.ResearchError):c.monitor_namespaces()
        (c.destination/'guest/run-01-front_gate-default/terminal.v1.json').write_bytes(p.canonical(p.seal({
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


class IndependentColdTests(unittest.TestCase):
    """Synthetic closed observations; real tiny files/Git, never Docker or GI."""
    @classmethod
    def setUpClass(cls):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'decoder-independent-v6/cold_reader.py'
        spec=importlib.util.spec_from_file_location('independent_decoder_cold_v6',path)
        cls.cold=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.cold)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name).resolve()
        self.fd_before=len(list(Path('/proc/self/fd').iterdir()))
        self.replays=[];self.patches=[]

    def tearDown(self):
        for replay in self.replays:replay.h.close()
        for active in reversed(self.patches):active.stop()
        self.assertEqual(len(list(Path('/proc/self/fd').iterdir())),self.fd_before)
        self.temp.cleanup()

    def patch_anchor(self,name,value):
        active=patch.object(self.cold,name,value);active.start();self.patches.append(active)

    def raw(self,path,data=b'synthetic'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        return {'path':str(path),'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}

    def document(self,path,kind,**fields):
        return self.raw(path,self.cold.canonical(p.seal(dict(artifact_kind=kind,accepted=False,publication_ready=False,**fields)))+b'\n')

    def decoded(self,path):
        import json
        return json.loads(path.read_bytes())

    def replace_document(self,path,**fields):
        value=self.decoded(path);value.pop('sha256');value.update(fields)
        return self.raw(path,self.cold.canonical(p.seal(value))+b'\n')

    @staticmethod
    def owner(pid,ppid=90):
        return {'pid':pid,'ppid':ppid,'starttime_ticks':100+pid,'uid':1000,'gid':1000,
            'boot_id':'11111111-2222-3333-4444-555555555555'}

    def external_owner(self,pid,ppid,group=None,session=None):
        return dict(self.owner(pid,ppid),process_group_id=pid if group is None else group,
            session_id=pid if session is None else session)

    def journal(self,path,rows):
        return self.raw(path,b''.join(self.cold.canonical(dict(event_seq=i,observed_monotonic_ns=100000+i,**row))+b'\n'
            for i,row in enumerate(rows,1)))

    @staticmethod
    def buffer_abi():
        return dict(implementation='cpython',version=[3,12,3],pointer_bytes=8,py_buffer_bytes=80,format_offset=40,request='PyBUF_SIMPLE',
            field_offsets={'buf':0,'obj':8,'len':16,'itemsize':24,'readonly':32,'ndim':36,'format':40,'shape':48,'strides':56,'suboffsets':64,'internal':72})

    def git(self,root,*args):
        import subprocess
        result=subprocess.run(['/usr/bin/git','--no-replace-objects','-c','core.longpaths=true','-C',str(root),*args],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,
            env=dict(os.environ,GIT_AUTHOR_NAME='Synthetic',GIT_AUTHOR_EMAIL='fixture@example.invalid',
                GIT_COMMITTER_NAME='Synthetic',GIT_COMMITTER_EMAIL='fixture@example.invalid'))
        self.assertEqual(result.returncode,0,result.stderr.decode());return result.stdout.strip().decode()

    def fixture(self,mode='metadata-only',flush=False,original_observer=None,fixture_root=None):
        base=self.base if fixture_root is None else Path(fixture_root)
        c=self.cold;self.project=base/'physical';self.repository=base/'review';self.repository.mkdir()
        # Synthetic host binding only; the real interpreter still undergoes file/FD custody.
        self.patch_anchor('HOST_INTERPRETER',str(Path(sys.executable).resolve(strict=True)))
        self.attempt=base/'attempt';(self.attempt/'controller').mkdir(parents=True);(self.attempt/'guest/metadata').mkdir(parents=True)
        self.external=base/'external';self.external.mkdir();self.helper=base/'capture.py';helper=self.raw(self.helper,b'# synthetic reviewed helper\n')
        self.git(self.repository,'init','-q')
        for name,rel in c.PLANNING_PATHS.items():self.raw(self.repository/'openspec/changes/fix-decoder-preflight'/rel,('P '+name+'\n').encode())
        self.git(self.repository,'add','openspec');self.git(self.repository,'commit','-qm','synthetic planning')
        self.P=self.git(self.repository,'rev-parse','HEAD')
        # Only the declared disposable fixture substitutes the reviewed amendment authority.
        if hasattr(c,'OBSERVER_PLANNING'):self.patch_anchor('OBSERVER_PLANNING',self.P)
        for name in ('controller.py','guest_consumer.py','research_protocol.py'):self.raw(self.repository/c.RUNTIME/name,('# synthetic source '+name+'\n').encode())
        self.raw(self.repository/c.OBSERVER,Path(c.__file__).read_bytes() if original_observer is None else original_observer)
        self.git(self.repository,'add','artifacts');self.git(self.repository,'commit','-qm','synthetic reviewed source')
        self.S=self.git(self.repository,'rev-parse','HEAD')
        self.binding=dict(mode=mode,planning_commit=self.P,source_commit=self.S,current_checkout_commit=self.S,
            review_repository_root=str(self.repository),project_root=str(self.project))
        self.code=[self.raw(self.repository/c.RUNTIME/name,('# synthetic source '+name+'\n').encode())
            for name in ('controller.py','guest_consumer.py','research_protocol.py')]
        planning=[]
        for name,rel in c.PLANNING_PATHS.items():
            data=(self.repository/'openspec/changes/fix-decoder-preflight'/rel).read_bytes()
            row=self.raw(self.attempt/'controller'/name,data)
            planning.append(dict(row,planning_commit=self.P,git_path='openspec/changes/fix-decoder-preflight/'+rel,
                git_blob_sha1=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()))
        source=self.raw(self.project/'scripts/stock.py',b'# historical synthetic source\n')
        custody=self.raw(self.project/'scripts/publication_operational_container_custody_v1.py',b'# synthetic custody\n')
        self.patch_anchor('CUSTODY',{k:custody[k] for k in ('size_bytes','sha256')})
        sources=[];media=[]
        for role in ('front_gate','underbody'):
            descriptor=self.raw(self.project/'data'/f'{role}.mp4',('synthetic-media-'+role).encode());media.append(dict(role=role,descriptor=descriptor))
            sources.append(dict(role=role,dataset_id='synthetic_dataset',stream_id=0,encoded_geometry={'width':2,'height':2},
                stock_source_parameters=dict(input_path='data/'+role+'.mp4',source_sha256=descriptor['sha256'],
                    source_container='mp4',source_codec='h264',source_duration_ns=40000000000)))
        source_binary=dict(path='/usr/local/bin/vast_checkpoint_source',size_bytes=1,sha256='1'*64)
        plugin=dict(path='/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0/libgstnvcodec.so',size_bytes=1,sha256='2'*64)
        prefix=self.project/'artifacts/benchmark_recovery_20260930/decoder-experiment-prerequisites'
        ledger=self.document(prefix/'prerequisite-recipe-ledger.v1.json','synthetic_historical_ledger',image_id=c.IMAGE,
            source_citations=[dict(descriptor=source)],stock_sources=sources,actual_package_files=dict(source_binary=source_binary,nvcodec_plugin=plugin))
        observed=self.raw(prefix/'original-media-physical-observation.v1.json',c.canonical(dict(media=media)))
        self.patch_anchor('LEDGER_SHA',ledger['sha256']);self.patch_anchor('MEDIA_OBSERVATION',{k:observed[k] for k in ('size_bytes','sha256')})
        git_descriptor=dict(path='/usr/bin/git',size_bytes=Path('/usr/bin/git').stat().st_size,sha256=hashlib.sha256(Path('/usr/bin/git').read_bytes()).hexdigest())
        self.plan=dict(self.binding,image_id=c.IMAGE,fixed_order=[list(x) for x in c.ORDER],guest_prelaunch_budget_s=100,
            sources=[dict(row,media=media[i]['descriptor'],actual_first_32_au_max_bytes=None) for i,row in enumerate(sources)],
            source_files=[source],source_binary=source_binary,nvcodec_plugin=plugin,code=self.code,planning_files=planning,
            custody_helper=custody,review_git=git_descriptor,historical_prerequisite=ledger)
        plan_descriptor=self.document(self.attempt/'controller/execution-plan.v1.json','vast_decoder_research_plan_v1',**self.plan)
        guest_plan=dict(plan_descriptor,path='/opt/vast/input/plan.json')
        guest=self.owner(120,1);self.guest_owner=guest;directory=self.attempt/'guest/metadata'
        gi=dict(path='/synthetic/gi.py',size_bytes=1,sha256='3'*64);extension=dict(gi,path='/synthetic/_gi.so');typelib=dict(gi,path='/synthetic/Gst.typelib')
        library=dict(gi,path='/synthetic/libgst.so');packages=[guest_plan,source_binary,plugin,gi,extension,typelib,library]
        packages.extend(dict(row,path='/opt/vast/code/'+Path(row['path']).name) for row in self.code)
        packages.extend(dict(row['descriptor'],path='/opt/vast/media/'+row['role']+'.mp4') for row in media)
        self.packages=packages
        mapped={'original_row':'1000-2000 r--p 00000000 00:01 9 /synthetic/libgst.so',
            'address_start':4096,'address_end':8192,'permissions':'r--p','offset':0,'mapped_identity':[os.makedev(0,1),9],
            'path':'/synthetic/libgst.so','resolved_path':'/synthetic/libgst.so'}
        facts=dict(process=guest,proc_path='/proc/120/maps',selectors=['libgst','libglib','libgobject','libgirepository','_gi.','libcuda','libnvcuvid','libnvidia'],snapshot_size_bytes=80,
            snapshot_sha256='a'*64,selected_original_rows=[mapped])
        before=self.document(directory/'mapped-inputs-01.v1.json','vast_decoder_research_original_mapped_inputs_v1',observation_complete=False,**facts)
        closed=self.document(directory/'mapped-inputs-01-closed.v1.json','vast_decoder_research_original_mapped_inputs_v1',
            observation_complete=True,owner_before=guest,owner_after=guest,selected_rows_before=[mapped],selected_rows_after=[mapped],
            snapshot_after_size_bytes=80,snapshot_after_sha256='a'*64,before_snapshot=dict(before,path='/opt/vast/output/metadata/'+Path(before['path']).name),
            pin_observations=[dict(descriptor=library,mapping_observation=dict(view='direct',visible_identity=mapped['mapped_identity'],selected_identity=mapped['mapped_identity'],probe=None))],**facts)
        collection=[dict(closed,path='/opt/vast/output/metadata/'+Path(closed['path']).name)]
        self.collections=collection
        self.document(directory/'prelaunch.v1.json','vast_decoder_research_guest_prelaunch_v1',plan=guest_plan,controller=guest,
            buffer_abi=self.buffer_abi(),
            gi_version='3.50.0',gst_version=[1,28,2,0],plugin_path=plugin['path'],packages=packages,
            media={row['role']:dict(row['descriptor'],path='/opt/vast/media/'+row['role']+'.mp4') for row in media},
            mapped_library_collections=collection,elapsed_s=1)
        self.document(directory/'initialization-metadata.v1.json','vast_decoder_research_initialization_metadata_v1',
            intended_arguments=[],callable_doc='synthetic init',actual_loaded_override_sources=[gi],gi_package=gi,gi_extension=extension,gst_typelib=typelib)
        self.journal(directory/'events.jsonl',[dict(kind='registry_process_started',controller=guest,child=self.owner(121,120)),
            dict(kind='registry_process_terminal',returncode=0,failures=[]),dict(kind='gst_initialization_before',intended_arguments=[]),
            dict(kind='gst_initialization_after',actual_initialized=True)])
        self.raw(directory/'registry.stdout',b'synthetic registry observation');self.raw(directory/'registry.stderr',b'')
        final=self.document(directory/'final-package-pins.v1.json','vast_decoder_research_final_package_pins_v1',
            pins=packages,all_before_after_verified=True,mapped_library_collections=collection)
        result=None
        if mode=='research':
            completed=[self.run_fixture(i,role,setting,flush) for i,(role,setting) in enumerate(c.ORDER,1)]
            pairs=[dict(clip=completed[a][0]['clip'],sequence=n+1,default_residence_ns=completed[a][0]['timings'][n]['residence_ns'],
                zero_residence_ns=completed[b][0]['timings'][n]['residence_ns'],zero_minus_default_ns=completed[b][0]['timings'][n]['residence_ns']-completed[a][0]['timings'][n]['residence_ns'],
                cohort=completed[a][0]['timings'][n]['cohort'],steady_state_pair=not(flush)) for a,b in ((0,1),(3,2)) for n in range(32)]
            paired=self.document(directory/'paired-timing.v1.json','vast_decoder_research_paired_timing_v1',observations=pairs)
            result=dict(research_correctness_preserved=True,runs=[row[1] for row in completed],final_package_pins=dict(final,path='/opt/vast/output/metadata/'+Path(final['path']).name),
                paired_timings=dict(paired,path='/opt/vast/output/metadata/'+Path(paired['path']).name),central_steady_state_sufficient_by_run=[not flush]*4)
        final=self.document(directory/'final-package-pins.v1.json','vast_decoder_research_final_package_pins_v1',
            pins=packages,all_before_after_verified=True,mapped_library_collections=self.collections)
        if result is not None:result['final_package_pins']=dict(final,path='/opt/vast/output/metadata/'+Path(final['path']).name)
        guest_leaf='metadata-preflight-terminal.v1.json' if mode=='metadata-only' else 'research-terminal.v1.json'
        guest_kind='vast_decoder_research_metadata_preflight_terminal_v1' if mode=='metadata-only' else 'vast_decoder_research_guest_terminal_v1'
        guest_terminal=self.document(directory/guest_leaf,guest_kind,**self.binding,plan=guest_plan,provisional_until_owner_final_close=True,
            operation_completed=True,metadata_preflight_completed=mode=='metadata-only',research_complete=mode=='research',runs_completed=0 if mode=='metadata-only' else 4,
            result=result,failure=None,failure_stage=None,failure_type=None,failure_traceback=None,failure_traceback_error=None,original_primary_failure=None,
            primary_failure_capture_error=None,elapsed_s=10)
        guest_descriptor=dict(guest_terminal,path='/opt/vast/output/metadata/'+guest_leaf)
        controller_owner=self.owner(100,90);docker_owner=self.owner(101,100)
        external_child=self.external_owner(100,90);outer=self.external_owner(90,89,80,80)
        name='vast-decoder-research-'+('0'*32);cid='b'*64;label=hashlib.sha256((self.P+self.S+mode+c.IMAGE+name).encode()).hexdigest()
        engine=dict(path='/usr/bin/docker',size_bytes=Path('/usr/bin/docker').stat().st_size,sha256=hashlib.sha256(Path('/usr/bin/docker').read_bytes()).hexdigest());self.patch_anchor('ENGINE_SHA',engine['sha256'])
        self.document(self.attempt/'controller/reservation.v1.json','vast_decoder_research_reservation_v1',**self.binding,
            controller=controller_owner,name=name,label=label,daemon_id=c.DAEMON,image_id=c.IMAGE,once_only=True,reserved_at_ns=1,engine=engine,plan=plan_descriptor)
        self.raw(self.attempt/'controller/original.cid',(cid+'\n').encode())
        argv=['/usr/bin/docker','run','--name',name,'--cidfile',str(self.attempt/'controller/original.cid'),'--label','vast.operational-custody='+label,
            '--gpus','all','--network','none','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=134217728,mode=1777','--env','HOME=/tmp','--env','XDG_CACHE_HOME=/tmp',
            '--env','NVIDIA_DRIVER_CAPABILITIES=compute,utility,video','--mount','type=bind,src='+str(self.repository/c.RUNTIME)+',dst=/opt/vast/code,readonly',
            '--mount','type=bind,src='+str(self.attempt/'controller/execution-plan.v1.json')+',dst=/opt/vast/input/plan.json,readonly','--mount','type=bind,src='+str(self.attempt/'guest')+',dst=/opt/vast/output']
        for row in self.plan['sources']:argv+=['--mount','type=bind,src='+row['media']['path']+',dst=/opt/vast/media/'+row['role']+'.mp4,readonly']
        argv+=['--entrypoint','/usr/bin/python3',c.IMAGE,'-I','-B','/opt/vast/code/guest_consumer.py','--plan','/opt/vast/input/plan.json','--output-dir','/opt/vast/output','--mode',mode]
        self.document(self.attempt/'controller/launch-intent.v1.json','vast_decoder_research_launch_intent_v1',argv=argv)
        self.document(self.attempt/'controller/process-start.v1.json','vast_decoder_research_process_start_v1',argv=argv,child=docker_owner,controller=controller_owner)
        self.raw(self.attempt/'controller/original.stdout',c.canonical(dict(successful=True,receipt=guest_descriptor,receipt_time_limit_failure=None,
            close_failure=None,metadata_close_error=None,pin_close_error=None,close_failure_capture_error=None))+b'\n');self.raw(self.attempt/'controller/original.stderr',b'')
        state=dict(Id=cid,Name='/'+name,Image=c.IMAGE,Operation=label,Running=False,Pid=0,ExitCode=0,OOMKilled=False,
            Created='2026-10-04T00:00:00.000000001Z',StartedAt='2026-10-04T00:00:00.000000002Z',FinishedAt='2026-10-04T00:00:00.000000003Z')
        projection=c.PROJECTION
        commands=[(['info','--format','{{json .ID}}'],0,c.canonical(c.DAEMON)+b'\n',b''),(['ps','--all','--no-trunc','--format','{{.ID}}'],0,b'',b''),
            (['image','inspect','--format','{{.Id}}',c.IMAGE],0,(c.IMAGE+'\n').encode(),b''),
            (['container','inspect','--format',projection,name],1,b'',f'Error: No such container: {name}\n'.encode()),
            (['container','inspect','--format',projection,cid],0,c.canonical(state)+b'\n',b''),(['container','rm',cid],0,(cid+'\n').encode(),b''),
            (['container','inspect','--format',projection,cid],1,b'',f'Error: No such container: {cid}\n'.encode()),
            (['container','inspect','--format',projection,name],1,b'',f'Error: No such container: {name}\n'.encode()),(['info','--format','{{json .ID}}'],0,c.canonical(c.DAEMON)+b'\n',b'')]
        for i,(args,rc,out,err) in enumerate(commands,1):
            self.document(self.attempt/'controller'/f'engine-{i:02d}.v1.json','vast_decoder_research_engine_observation_v1',argv=['/usr/bin/docker',*args],
                timed_out=False,errors=[],controller=controller_owner,child=self.owner(300+i,100),elapsed_s=.01,returncode=rc,observed_realtime_ns=2000000000000000000,
                stdout=self.raw(self.attempt/'controller'/f'engine-{i:02d}.stdout',out),stderr=self.raw(self.attempt/'controller'/f'engine-{i:02d}.stderr',err))
        self.journal(self.attempt/'controller/events.jsonl',[dict(kind='original_container_terminal_before_remove',state=state),
            dict(kind='original_launcher_terminal',forced_group_stop=False,returncode=0),dict(kind='original_cleanup_terminal',exact_remove_then_absence=True,errors=[])])
        leaves=[dict(path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted((self.attempt/'controller').iterdir())]
        manifest=self.document(self.attempt/'controller/closed-controller-leaves.v1.json','vast_decoder_research_closed_controller_leaves_v1',leaves=leaves)
        terminal=self.document(self.attempt/'controller/terminal.v1.json','vast_decoder_research_controller_terminal_v1',**self.binding,
            provisional_until_owner_final_close=True,operation_completed=True,original_execution_completed=True,failure=None,errors=[],original_cli_returncode=0,
            oom_killed=False,container_not_found_after_owned_remove=True,elapsed_s=30,cleanup_elapsed_after_close_s=1,independent_cold_recomputed=False,
            research_conclusion_authorized=False,research_complete=mode=='research',metadata_preflight_completed=mode=='metadata-only',runs_completed=0 if mode=='metadata-only' else 4,
            result=None if mode=='metadata-only' else 'original research body',controller=controller_owner,child=docker_owner,name=name,label=label,container_id=cid,
            final_observed_state=state,closed_controller_leaves=manifest,guest_terminal=guest_terminal)
        host_argv=[c.HOST_INTERPRETER,'-I','-B',str(self.repository/c.RUNTIME/'controller.py'),
            '--project-root',str(self.project),'--review-repository-root',str(self.repository),'--source-commit',self.S,'--mode',mode,'--output-dir',str(self.attempt)]
        sources_before=[]
        observer_path=self.repository/c.OBSERVER
        for row in [*self.code,dict(path=str(observer_path),size_bytes=observer_path.stat().st_size,sha256=hashlib.sha256(observer_path.read_bytes()).hexdigest())]:
            sources_before.append(dict(descriptor=row,epoch=c.epoch(Path(row['path']).stat())))
        interpreter=Path(c.HOST_INTERPRETER)
        interpreter_descriptor=dict(path=str(interpreter),size_bytes=interpreter.stat().st_size,sha256=hashlib.sha256(interpreter.read_bytes()).hexdigest())
        launch=self.document(self.external/'launch.v1.json','vast_decoder_research_external_original_controller_launch_v1',argv=host_argv,controller=outer,sources=sources_before,
            dispatch_source=dict(descriptor=helper,epoch=c.epoch(self.helper.stat())),interpreter=dict(descriptor=interpreter_descriptor,epoch=c.epoch(interpreter.stat())))
        self.document(self.external/'process-start.v1.json','vast_decoder_research_external_original_controller_started_v1',argv=host_argv,controller=outer,child=external_child)
        stdout=self.raw(self.external/'original.stdout',c.canonical(dict(successful=True,receipt=terminal,original_execution_completed=True,
            streams_closed=True,pins_closed=True,socket_closed=True,controller_close_errors=[],failure=None,close_failure=None,
            close_failure_capture_error=None,receipt_time_limit_failure=None,mode=mode,planning_commit=self.P,source_commit=self.S))+b'\n');stderr=self.raw(self.external/'original.stderr',b'')
        external_terminal=self.document(self.external/'terminal.v1.json','vast_decoder_research_external_original_controller_terminal_v1',**self.binding,
            external_capture_completed=True,original_controller_returncode=0,timed_out=False,capture_exceeded=[],failures=[],containment=None,
            all_source_epochs_rechecked=True,elapsed_s=40,started_at_ns=1,finished_at_ns=2,log_eof=dict(stdout=True,stderr=True),close_errors=[],all_streams_closed=True,
            provisional_until_owner_final_close=True,launch=launch,argv=host_argv,controller=outer,original_child=external_child,sources_before=sources_before,sources_after=sources_before,
            dispatch_source=dict(descriptor=helper,epoch=c.epoch(self.helper.stat())),dispatch_source_after=dict(descriptor=helper,epoch=c.epoch(self.helper.stat())),
            interpreter_after=dict(descriptor=interpreter_descriptor,epoch=c.epoch(interpreter.stat())),signals=[],container_cleanup_verified=None,container_oom_observed=None,
            stdout=stdout,stderr=stderr)
        self.tool=base/'original-tool.json'
        self.raw(self.tool,c.canonical(dict(tool_calls=[dict(tool_name='exec_command',arguments={'cmd':'synthetic capture'},result=dict(exit_code=0,
            original_token_count=300,output='w\0s\0l\0: synthetic warning\r\0\n\0'+c.canonical(dict(receipt=external_terminal,external_capture_completed=True,late_terminal=None,close_errors=[])).decode()+'\n'))])))
        replay=c.Replay(self.project,self.repository,self.attempt,mode,self.S,planning_commit=self.P);self.replays.append(replay)
        self.replay=replay;self.capture_sha=helper['sha256'];return replay

    def test_P2_real_six_core_and_eight_external_owner_records_join(self):
        replay=self.fixture();replay.plan=self.plan;replay.binding=replay.source_bindings(self.plan)
        external=replay.external(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        controller=replay.controller(external)
        self.assertEqual(set(controller['controller']),{'pid','ppid','starttime_ticks','uid','gid','boot_id'})
        self.assertEqual(set(external['original_child']),set(controller['controller'])|{'process_group_id','session_id'})
        self.assertEqual(external['controller']['process_group_id'],80)
        self.assertNotEqual(external['controller']['process_group_id'],external['controller']['pid'])

    def test_P2_real_guest_alias_and_physical_terminal_descriptor_join(self):
        replay=self.fixture();replay.plan=replay.doc(self.attempt/'controller/execution-plan.v1.json','vast_decoder_research_plan_v1')
        replay.binding=self.binding;controller=self.decoded(self.attempt/'controller/terminal.v1.json')
        completed,pairs=replay.guest(controller)
        self.assertEqual((completed,pairs),([],[]))
        alias=self.decoded(self.attempt/'controller/original.stdout')['receipt']
        self.assertEqual(replay.output(alias),Path(controller['guest_terminal']['path']))
        self.assertNotEqual(alias['path'],controller['guest_terminal']['path'])
        self.assertEqual({k:alias[k] for k in ('size_bytes','sha256')},
            {k:controller['guest_terminal'][k] for k in ('size_bytes','sha256')})
        self.assertEqual(replay.guest_terminal_join,dict(controller_physical=controller['guest_terminal'],
            guest_stdout_alias=alias,held_physical=controller['guest_terminal']))

    def reseal_external_owners(self,parent,child):
        launch=self.replace_document(self.external/'launch.v1.json',controller=parent)
        self.replace_document(self.external/'process-start.v1.json',controller=parent,child=child)
        terminal=self.replace_document(self.external/'terminal.v1.json',launch=launch,controller=parent,original_child=child)
        value=self.decoded(self.tool)
        value['tool_calls'][0]['result']['output']=self.cold.canonical(dict(receipt=terminal,
            external_capture_completed=True,late_terminal=None,close_errors=[])).decode()+'\n'
        self.raw(self.tool,self.cold.canonical(value))

    def cross_version_fixture(self,fixture_root=None,large_planning=False):
        replay=self.fixture(original_observer=b'# immutable distinct original S observer\n',fixture_root=fixture_root)
        replay.h.close();c=self.cold
        self.observer_repository=self.repository.parent/'observer'
        self.git(self.repository.parent,'clone','-q','--no-hardlinks',str(self.repository),str(self.observer_repository))
        for name,relative in c.PLANNING_PATHS.items():
            raw=('P2 '+name+'\n').encode()
            if large_planning and name=='reviewed-design.md':raw=b'x'*(c.DOC_MAX+1)
            self.raw(self.observer_repository/'openspec/changes/fix-decoder-preflight'/relative,raw)
        self.git(self.observer_repository,'add','openspec');self.git(self.observer_repository,'commit','-qm','synthetic approved P2')
        self.P2=self.git(self.observer_repository,'rev-parse','HEAD');self.patch_anchor('OBSERVER_PLANNING',self.P2)
        self.raw(self.observer_repository/c.OBSERVER,Path(c.__file__).read_bytes())
        self.git(self.observer_repository,'add','artifacts');self.git(self.observer_repository,'commit','-qm','synthetic corrected C')
        self.C=self.git(self.observer_repository,'rev-parse','HEAD')
        corrected=c.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P,
            observer_repository=self.observer_repository,observer_commit=self.C)
        self.replays.append(corrected);return corrected

    def test_P2_each_core_identity_and_exact_controller_schema_is_required(self):
        changes=[('pid',101),('ppid',91),('starttime_ticks',201),('uid',1001),('gid',1001),
            ('boot_id','22222222-2222-3333-4444-555555555555'),('uid',1000.0),('extra',1),('missing',None)]
        for key,new in changes:
            with self.subTest(field=key),tempfile.TemporaryDirectory(dir=self.base) as temp:
                replay=self.fixture(fixture_root=temp);replay.plan=self.plan;replay.binding=self.binding
                owner=self.owner(100,90)
                if key=='missing':owner.pop('boot_id')
                else:owner[key]=new
                self.replace_document(self.attempt/'controller/terminal.v1.json',controller=owner)
                with self.assertRaises(self.cold.Refusal):replay.controller(self.decoded(self.external/'terminal.v1.json'))
                replay.h.close()

    def test_P2_external_parent_child_shape_and_containment_are_required(self):
        changes=[('parent','process_group_id',0),('parent','session_id',True),('parent','extra',1),
            ('parent','missing',None),('child','process_group_id',99),('child','session_id',99),
            ('child','process_group_id',True),('child','session_id',0),('child','missing',None)]
        for role,key,new in changes:
            with self.subTest(role=role,field=key),tempfile.TemporaryDirectory(dir=self.base) as temp:
                replay=self.fixture(fixture_root=temp);replay.plan=self.plan;replay.binding=replay.source_bindings(self.plan)
                parent=self.external_owner(90,89,80,80);child=self.external_owner(100,90)
                owner=parent if role=='parent' else child
                if key=='missing':owner.pop('session_id')
                else:owner[key]=new
                self.reseal_external_owners(parent,child)
                with self.assertRaisesRegex(self.cold.Refusal,'external .*owner|session containment'):
                    replay.external(self.external/'terminal.v1.json',self.capture_sha,self.tool)
                replay.h.close()

    def test_P2_terminal_paths_size_hash_and_mode_are_not_interchangeable(self):
        cases=[('physical','path','/opt/vast/output/metadata/metadata-preflight-terminal.v1.json'),
            ('physical','path','foreign'),('physical','size_bytes',1),('physical','sha256','0'*64),
            ('guest','path','physical'),('guest','path','/opt/vast/output/metadata/research-terminal.v1.json'),
            ('guest','path','/opt/vast/output/metadata/../metadata/metadata-preflight-terminal.v1.json'),
            ('guest','path','/foreign/metadata/metadata-preflight-terminal.v1.json'),
            ('guest','size_bytes',1),('guest','sha256','0'*64)]
        for role,key,new in cases:
            with self.subTest(role=role,field=key,value=new),tempfile.TemporaryDirectory(dir=self.base) as temp:
                replay=self.fixture(fixture_root=temp)
                replay.plan=replay.doc(self.attempt/'controller/execution-plan.v1.json','vast_decoder_research_plan_v1');replay.binding=self.binding
                controller=self.decoded(self.attempt/'controller/terminal.v1.json')
                stdout=self.decoded(self.attempt/'controller/original.stdout')
                descriptor=controller['guest_terminal'] if role=='physical' else stdout['receipt']
                descriptor[key]=str(self.base/'foreign-terminal.json') if new=='foreign' else controller['guest_terminal']['path'] if new=='physical' else new
                if role=='guest':self.raw(self.attempt/'controller/original.stdout',self.cold.canonical(stdout)+b'\n')
                with self.assertRaises(self.cold.Refusal):replay.guest(controller)
                replay.h.close()

    def test_P2_distinct_git_C_executes_against_frozen_S_and_raw_P2_after_archive(self):
        replay=self.cross_version_fixture();old_plan=(self.attempt/'controller/execution-plan.v1.json').read_bytes()
        current=self.observer_repository/'openspec/changes/fix-decoder-preflight'
        self.raw(current/'tasks.md',b'legitimate task progress after P2\n')
        archive=self.observer_repository/'openspec/changes/archive/2026-10-04-fix-decoder-preflight';archive.parent.mkdir()
        self.git(self.observer_repository,'mv',str(current),str(archive));self.git(self.observer_repository,'add','openspec')
        self.git(self.observer_repository,'commit','-qm','synthetic task progress and archive')
        result=replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        binding=result['observer_binding']
        self.assertTrue(result['operation_completed']);self.assertEqual(result['source_commit'],self.S)
        self.assertEqual(replay.binding,self.binding);self.assertEqual(binding['source_commit'],self.C)
        self.assertEqual(binding['planning_commit'],self.P2);self.assertNotEqual(binding['current_checkout_commit'],self.C)
        self.assertEqual(len(binding['planning_files']),4);self.assertEqual(len([r for r in replay.git_commands
            if 'cat-file' in r['argv'] and any(a.startswith(self.P2+':') for a in r['argv'])]),4)
        self.assertNotEqual(binding['original_observer']['sha256'],binding['executed_observer']['sha256'])
        self.assertEqual(binding['executed_observer']['sha256'],hashlib.sha256(Path(self.cold.__file__).read_bytes()).hexdigest())
        self.assertEqual((self.attempt/'controller/execution-plan.v1.json').read_bytes(),old_plan)
        self.assertTrue(all(r['planning_commit']==self.P for r in self.plan['planning_files']))
        self.assertEqual((result['actual_original_au_count'],result['paired_timing_count']),(0,0))
        self.assertEqual(result['guest_terminal_join']['controller_physical'],
            self.decoded(self.attempt/'controller/terminal.v1.json')['guest_terminal'])
        self.assertEqual(result['guest_terminal_join']['guest_stdout_alias'],
            self.decoded(self.attempt/'controller/original.stdout')['receipt'])

    def test_P2_paired_observer_arguments_and_exact_C_ancestry_are_required(self):
        replay=self.cross_version_fixture();replay.h.close();c=self.cold
        for supplied in ({'observer_repository':self.observer_repository},{'observer_commit':self.C}):
            with self.subTest(supplied=supplied),self.assertRaisesRegex(c.Refusal,'paired observer'):
                c.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P,**supplied)
        for root,commit in [(self.observer_repository,self.P),(self.repository,self.C),
                (self.observer_repository/'..',self.C),(self.observer_repository,'not-a-commit')]:
            with self.subTest(root=root,commit=commit):
                changed=c.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P,
                    observer_repository=root,observer_commit=commit);self.replays.append(changed)
                with self.assertRaises(c.Refusal):changed.source_bindings(self.plan)
                changed.h.close()
        default=c.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P);self.replays.append(default)
        with self.assertRaises(c.Refusal):default.source_bindings(self.plan)

    def test_P2_current_C_and_original_S_files_keep_separate_physical_guards(self):
        for role in ('observer-C','original-S','C-epoch'):
            with self.subTest(role=role),tempfile.TemporaryDirectory(dir=self.base) as temp:
                replay=self.cross_version_fixture(fixture_root=temp)
                path=(self.repository if role=='original-S' else self.observer_repository)/self.cold.OBSERVER
                if role=='C-epoch':
                    replay.source_bindings(self.plan);path.write_bytes(path.read_bytes())
                    with self.assertRaisesRegex(self.cold.Refusal,'epoch|name'):replay.h.check(True)
                else:
                    path.write_bytes(path.read_bytes()+b'# unreviewed drift\n')
                    with self.assertRaisesRegex(self.cold.Refusal,'descriptor'):replay.source_bindings(self.plan)
                replay.h.close()

    def test_P2_raw_amendment_blob_bound_is_enforced(self):
        replay=self.cross_version_fixture(large_planning=True)
        with self.assertRaisesRegex(self.cold.Refusal,'Git stream cap'):replay.source_bindings(self.plan)
        failed=replay.git_commands[-1]
        self.assertIn(self.P2+':openspec/changes/fix-decoder-preflight/design.md',failed['argv'])
        self.assertLessEqual(failed['stdout_size'],self.cold.DOC_MAX)
        self.assertIsNotNone(failed['returncode']);self.assertEqual(failed['close_errors'],[])

    def run_fixture(self,index,role,setting,flush):
        c=self.cold;source=next(row for row in self.plan['sources'] if row['role']==role);guest=self.guest_owner
        directory=self.attempt/'guest'/f'run-{index:02d}-{role}-{setting}';directory.mkdir()
        worker=f'research-source-{role}-{index:02d}';run=f'research-decoder-{index:02d}';params=source['stock_source_parameters']
        argv=[self.plan['source_binary']['path'],'--source-path','/proc/self/fd/5','--dataset-id',source['dataset_id'],'--source-sha256',source['media']['sha256'],
            '--checkpoint-container','mp4','--checkpoint-codec','h264','--source-duration-ns',str(params['source_duration_ns']),'--playback-timestamp-scale','600',
            '--source-replay','continuous','--logical-stream-id','0']
        env={'VAST_CHECKPOINT_'+key:value for key,value in dict(WORKER_ID=worker,RUN_ID=run,DATASET_ID=source['dataset_id'],SOURCE_SHA256=source['media']['sha256'],
            STREAM_ID='0',SOURCE_CONTAINER='mp4',SOURCE_CODEC='h264',SOURCE_DURATION_NS=str(params['source_duration_ns']),PLAYBACK_TIMESTAMP_SCALE='600',SOURCE_REPLAY='continuous',
            ADMISSION_MODE='native_common_source_coordinator',ADMISSION_EVENT_FD='5',ADMISSION_ACK_FD='6',CONTROL_FD='7',STATUS_FD='8',ADMISSION_CONSUMER_FDS_JSON='{"research-decoder":9}').items()}
        env.update(GST_REGISTRY=f'/tmp/decoder-research-source-{index}.registry.bin',GST_REGISTRY_UPDATE='no')
        rows=[dict(kind='source_process_started',child=self.owner(200+index,120),controller=guest,source_binary=self.plan['source_binary'],media=source['media'],argv=argv,environment=env),
            dict(kind='clock_domains',guest_monotonic_ns=1000000,guest_realtime_ns=0,secondary_admission_to_output_omitted=True)]
        template=self.decoded(self.attempt/'guest/metadata/mapped-inputs-01-closed.v1.json')
        source_owner=self.owner(200+index,120);number=index+1;metadata=self.attempt/'guest/metadata'
        facts={key:template[key] for key in ('proc_path','selectors','snapshot_size_bytes','snapshot_sha256','selected_original_rows')}
        facts.update(process=source_owner,proc_path=f'/proc/{source_owner["pid"]}/maps',selectors=['libgst','libglib','libgobject'])
        before=self.document(metadata/f'mapped-inputs-{number:02d}.v1.json','vast_decoder_research_original_mapped_inputs_v1',observation_complete=False,**facts)
        mapped=self.document(metadata/f'mapped-inputs-{number:02d}-closed.v1.json','vast_decoder_research_original_mapped_inputs_v1',observation_complete=True,**facts,
            owner_before=source_owner,owner_after=source_owner,selected_rows_before=template['selected_rows_before'],selected_rows_after=template['selected_rows_after'],
            snapshot_after_size_bytes=80,snapshot_after_sha256='a'*64,pin_observations=template['pin_observations'],
            before_snapshot=dict(before,path='/opt/vast/output/metadata/'+Path(before['path']).name))
        mapped=dict(mapped,path='/opt/vast/output/metadata/'+Path(mapped['path']).name);self.collections.append(mapped)
        rows.append(dict(kind='source_status',status='READY',original_timestamp=2000))
        rows.append(dict(kind='actual_source_loaded_libraries',libraries=[item['descriptor'] for item in template['pin_observations']],mapped_inputs=mapped))
        start=b'1 START 2001000000 2000 33500 43500\n';stop=b'1 STOP 33500\n'
        rows.extend([dict(kind='start_intent',raw_ascii=start.decode()),dict(kind='source_status',status='STARTED',original_timestamp=2000),
            dict(kind='start_sent',raw_ascii=start.decode())])
        declarations=[];packets=[];transport=[];timings=[];rgb=[];pts=[]
        for n in range(1,33):
            payload=('AU-'+str(n)).encode();aupts=(n-1)*1666666;point=aupts*600;duration=999999600;pts.append(point)
            admission=f'{run}:0:admission:{n}';key=f"synthetic_dataset:0:{source['media']['sha256']}:0:{aupts}";sha=hashlib.sha256(payload).hexdigest()
            event=dict(protocol_version=1,source_process_id=worker,sequence=n,run_id=run,dataset_id=source['dataset_id'],stream_id=0,admission_id=admission,input_frame_key=key,
                source_sha256=source['media']['sha256'],source_cycle=0,access_unit_pts_ns=aupts,payload_sha256=sha,payload_size_bytes=len(payload),schedule_offset_ns=(n-1)*duration,
                admission_timestamp_ms=2000+(n-1)*1000,event_provenance='native_common_source_coordinator');declarations.append(event)
            packet_row=dict(sequence=n,source_cycle=0,access_unit_pts_ns=aupts,transport_pts_ns=point,access_unit_dts_ns=c.MISSING,duration_ns=duration,
                keyframe=True,payload_size_bytes=len(payload),payload_sha256=sha);packets.append(packet_row)
            text=[admission.encode(),key.encode(),sha.encode()];transport.append(c.HEADER.pack(b'VASTAU01',1,1,n,0,aupts,point,c.MISSING,duration,*map(len,text),len(payload))+b''.join(text)+payload)
            rows.extend([dict(kind='admission_declaration',original=event),dict(kind='ack_intent',raw_ascii=f'1 ACK {n}\n'),
                dict(kind='transport_validated',**packet_row),dict(kind='ack_sent',raw_ascii=f'1 ACK {n}\n')])
        rows.extend([dict(kind='stop_intent',raw_ascii=stop.decode()),dict(kind='stop_sent',raw_ascii=stop.decode()),
            dict(kind='pipeline_created',text=c.PIPELINE,setting=setting,property_default_readback=-1,property_readback=0 if setting=='zero' else -1,default_was_unset=setting=='default')])
        for status in ('ADMISSION_STOPPED','DRAINED'):rows.append(dict(kind='source_status',status=status,original_timestamp=2000))
        eos=1 if flush else 1000000000000
        for n,point in enumerate(pts,1):
            enter=1000000+n*10000;exit=enter+(100 if setting=='default' else 90)
            fields=dict(caps='video/x-raw,format=RGB',caps_features=[])
            rows.extend([dict(kind='decoder_sink',pts=point,**fields),dict(kind='decoder_src',pts=point,**fields)])
            # Explicit per-event clock values are retained by journal below.
            rows[-2]['observed_monotonic_ns']=enter;rows[-1]['observed_monotonic_ns']=exit
            output=dict(pts=point,output_ordinal=n,format='RGB',width=2,height=2,stride=6,offset=0,pixel_sha256=hashlib.sha256(('RGB'+str(n)).encode()).hexdigest(),
                hold_hash_ns=2,sample_hold_start_ns=1,sample_hold_end_ns=3,**fields);rgb.append(output);rows.append(dict(kind='rgb_output',**output))
            timings.append(dict(original_sequence=n,pts=point,decoder_sink_ns=enter,decoder_src_ns=exit,residence_ns=exit-enter,
                cohort='startup' if n<=8 else 'central' if n<=24 else 'tail',after_actual_decoder_sink_eos=flush))
            rows.append(dict(kind='appsrc_submission',sequence=n,pts=point,fifo_depth=0,blocking_ns=0,push_return_monotonic_ns=100000+len(rows)+1))
        rows.extend([dict(kind='decoder_sink_eos_observed',observed_monotonic_ns=eos),dict(kind='decoder_src_eos_observed'),
            dict(kind='pipeline_bus_eos'),dict(kind='appsrc_eos_requested'),dict(kind='source_transport_eof',observed_monotonic_ns=2000000)])
        self.raw(directory/'events.jsonl',b''.join(c.canonical(dict(event_seq=i,observed_monotonic_ns=100000+i)|row)+b'\n' for i,row in enumerate(rows,1)))
        for name,data in [('source-control.raw',start+stop),('source-status.raw',b''.join(f'1 {s} {worker} 2000\n'.encode() for s in ('READY','STARTED','ADMISSION_STOPPED','DRAINED'))),
            ('source-admission.raw',b''.join(c.canonical(e)+b'\n' for e in declarations)),('source-ack.raw',b''.join(f'1 ACK {n}\n'.encode() for n in range(1,33))),
            ('source-transport.raw',b''.join(transport)),('source.stdout',b''),('source.stderr',b'')]:self.raw(directory/name,data)
        self.document(directory/'run-started.v1.json','vast_decoder_research_run_started_v1',run=index,controller=guest,guest_elapsed_at_start_s=index*40)
        self.document(directory/'startup-completed.v1.json','vast_decoder_research_startup_v1',run=index,elapsed_s=1)
        self.document(directory/'source-transport-eof.v1.json','vast_decoder_research_source_transport_eof_v1',run=index,observed_monotonic_ns=2000000)
        self.document(directory/'decoder-drain-completed.v1.json','vast_decoder_research_decoder_drain_v1',run=index,elapsed_from_source_eof_s=1,actual_decoder_sink_eos_ns=eos,
            source_eof_monotonic_ns=2000000,completed_monotonic_ns=3000000)
        actual=dict(clip=role,setting=setting,outputs=rgb,timings=timings,packets=packets,input_pts_decode_order=pts,actual_decoder_sink_eos_ns=eos,
            central_steady_state_sufficient=not flush,actual_admissions=32,actual_packets=32,raw_bytes=len(b''.join(transport)),maximum_actual_au_payload_bytes=5,
            pipeline=c.PIPELINE,property_default_readback=-1,property_readback=0 if setting=='zero' else -1)
        observations=self.document(directory/'observations.v1.json','vast_decoder_research_observations_v1',**actual)
        leaves=[dict(path='/opt/vast/output/'+path.relative_to(self.attempt/'guest').as_posix(),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(directory.iterdir())]
        terminal=self.document(directory/'terminal.v1.json','vast_decoder_research_run_terminal_v1',run=index,clip=role,setting=setting,controller=guest,run_successful=True,
            source_returncode=0,errors=[],cleanup_errors=[],elapsed_s=35,closed_original_leaves=leaves,observations=dict(observations,path='/opt/vast/output/'+observations['path'].split('/guest/')[1]))
        return actual,dict(terminal=dict(terminal,path='/opt/vast/output/'+terminal['path'].split('/guest/')[1]),observations=dict(observations,path='/opt/vast/output/'+observations['path'].split('/guest/')[1]))

    def test_complete_metadata_positive_uses_real_git_and_holds_all_files(self):
        replay=self.fixture();result=replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        self.assertTrue(result['raw_join_complete']);self.assertTrue(result['metadata_preflight_completed'])
        self.assertFalse(result['research_complete']);self.assertEqual(result['actual_original_au_count'],0)
        self.assertFalse(result['accepted']);self.assertTrue(all(r['returncode']==0 and r['eof']==[True,True] for r in result['git_observations']))

    def test_complete_research_positive_reconstructs128_au64_pairs_and_legal_ack_interleaving(self):
        replay=self.fixture('research');result=replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        self.assertEqual(result['actual_original_au_count'],128);self.assertEqual(result['paired_timing_count'],64)
        self.assertEqual({r['zero_minus_default_ns'] for r in result['paired_timings']},{-10})
        self.assertEqual(result['central_steady_state_sufficient_by_run'],[True]*4);self.assertFalse(result['publication_ready'])

    def test_flush_only_outputs_remain_insufficient_without_changing_cohorts(self):
        replay=self.fixture('research',True);result=replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        self.assertEqual(result['central_steady_state_sufficient_by_run'],[False]*4)
        self.assertEqual(sum(r['cohort']=='central' for r in result['paired_timings']),32)
        self.assertTrue(all(not r['steady_state_pair'] for r in result['paired_timings']))

    def test_old_provisional_success_with_close_failure_companion_is_rejected(self):
        replay=self.fixture();self.raw(self.attempt/'guest/metadata/guest-close-failure.v1.json',b'{}')
        with self.assertRaisesRegex(self.cold.Refusal,'metadata/no failure'):replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)

    def test_external_provisional_success_needs_genuine_final_tool_rc(self):
        replay=self.fixture();value=self.decoded(self.tool);value['tool_calls'][0]['result']['exit_code']=1
        self.raw(self.tool,self.cold.canonical(value))
        with self.assertRaisesRegex(self.cold.Refusal,'external final tool rc'):replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)

    def test_source_and_reviewed_planning_raw_mutations_are_rejected_by_git(self):
        replay=self.fixture();self.raw(self.repository/self.cold.RUNTIME/'guest_consumer.py',b'# foreign same-path source\n')
        with self.assertRaisesRegex(self.cold.Refusal,'descriptor'):replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        replay.h.close()
        self.raw(self.repository/self.cold.RUNTIME/'guest_consumer.py',b'# synthetic source guest_consumer.py\n')
        copied=self.attempt/'controller/reviewed-design.md';self.raw(copied,b'foreign reviewed design\n')
        second=self.cold.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P);self.replays.append(second)
        with self.assertRaises(self.cold.Refusal):second.source_bindings(self.plan)

    def test_current_task_progress_does_not_replace_reviewed_p_blobs(self):
        replay=self.fixture();path=self.repository/'openspec/changes/fix-decoder-preflight/tasks.md';self.raw(path,b'current progress beyond reviewed P\n')
        self.git(self.repository,'add','openspec');self.git(self.repository,'commit','-qm','synthetic task progress')
        self.plan['current_checkout_commit']=self.git(self.repository,'rev-parse','HEAD')
        binding=replay.source_bindings(self.plan)
        self.assertEqual(binding['planning_commit'],self.P);self.assertNotEqual(binding['current_checkout_commit'],self.S)

    def test_raw_payload_corruption_has_independent_valid_prefix_only(self):
        replay=self.fixture('research');path=self.attempt/'guest/run-01-front_gate-default/source-transport.raw'
        raw=bytearray(path.read_bytes());raw[-1]^=1;self.raw(path,raw)
        with self.assertRaises(self.cold.Refusal):replay.execute(self.external/'terminal.v1.json',self.capture_sha,self.tool)
        prefix=replay.failed_prefixes()[0]
        self.assertEqual(prefix['hash_valid_packet_prefix'],31);self.assertFalse(prefix['promoted_cohort']);self.assertFalse(prefix['causal_join_complete'])

    def test_mapping_bridge_observer_owner_range_and_close_are_replayed(self):
        replay=self.fixture();path=self.attempt/'guest/metadata/mapped-inputs-01-closed.v1.json';value=self.decoded(path)
        observation=value['pin_observations'][0]['mapping_observation'];observation.update(view='readonly_backing_bridge',visible_identity=[1,10],probe=dict(
            abi=self.buffer_abi(),
            buffer_address=4096,buffer_length=1,owner=self.guest_owner,vma={k:v for k,v in value['selected_original_rows'][0].items() if k!='resolved_path'},
            maps_size_bytes=80,maps_sha256='a'*64,export_released=True,mapping_closed=True,selected_rows_during_without_probe=value['selected_original_rows']))
        packages={r['path']:r for r in self.packages}
        descriptor=self.replace_document(path,pin_observations=value['pin_observations'])
        collections=[dict(descriptor,path='/opt/vast/output/metadata/'+path.name)]
        replay.mappings(dict(mapped_library_collections=collections),dict(mapped_library_collections=collections),packages,self.guest_owner,[])
        replay.h.close();observation['probe']['mapping_closed']=False
        descriptor=self.replace_document(path,pin_observations=value['pin_observations']);collections=[dict(descriptor,path='/opt/vast/output/metadata/'+path.name)]
        second=self.cold.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P);self.replays.append(second)
        with self.assertRaisesRegex(self.cold.Refusal,'range/retirement'):second.mappings(dict(mapped_library_collections=collections),dict(mapped_library_collections=collections),packages,self.guest_owner,[])

    def test_real_leaf_replacement_links_and_close_fault_release_other_handles(self):
        directory=self.base/'held';directory.mkdir();a=directory/'a';b=directory/'b';self.raw(a);self.raw(b)
        held=self.cold.Held(directory,time.monotonic()+3)
        try:
            held.pin(a);held.pin(b);a.unlink();self.raw(a)
            with self.assertRaisesRegex(self.cold.Refusal,'epoch drift'):held.check(True)
        finally:held.close()
        a.unlink();os.link(b,a)
        held=self.cold.Held(directory,time.monotonic()+3)
        try:
            with self.assertRaisesRegex(self.cold.Refusal,'single-link'):held.pin(a)
        finally:held.close()
        a.unlink();self.raw(a);held=self.cold.Held(directory,time.monotonic()+3);held.pin(a);held.pin(b)
        fd=held.files[str(a)][0];real_close=os.close
        def fail_once(value):
            real_close(value)
            if value==fd:raise OSError(5,'synthetic close acknowledgement fault')
        with patch.object(self.cold.os,'close',side_effect=fail_once):held.close()
        self.assertTrue(held.close_errors);self.assertFalse(held.files);self.assertFalse(held.directories)

    def test_unknown_extra_output_and_foreign_mode_cannot_borrow_positive_body(self):
        replay=self.fixture();self.raw(self.attempt/'guest/extra.raw',b'unknown')
        with self.assertRaisesRegex(self.cold.Refusal,'guest namespace'):replay.namespace()
        (self.attempt/'guest/extra.raw').unlink();replay.h.close()
        second=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);self.replays.append(second)
        with self.assertRaisesRegex(self.cold.Refusal,'P/S/H/root/mode'):second.source_bindings(self.plan)

    def reseal_run_leaves(self,directory):
        terminal_path=directory/'terminal.v1.json';value=self.decoded(terminal_path)
        value.pop('sha256');value['observations']=dict(path='/opt/vast/output/'+(directory/'observations.v1.json').relative_to(self.attempt/'guest').as_posix(),
            size_bytes=(directory/'observations.v1.json').stat().st_size,sha256=hashlib.sha256((directory/'observations.v1.json').read_bytes()).hexdigest())
        value['closed_original_leaves']=[dict(path='/opt/vast/output/'+path.relative_to(self.attempt/'guest').as_posix(),size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in sorted(directory.iterdir()) if path!=terminal_path]
        self.raw(terminal_path,self.cold.canonical(p.seal(value))+b'\n')

    def test_resealed_raw_header_payload_ack_control_and_trailing_corruption_is_refused(self):
        replay=self.fixture('research');replay.plan=self.plan;directory=self.attempt/'guest/run-01-front_gate-default'
        source=self.plan['sources'][0];raw_files={name:(directory/name).read_bytes() for name in ('source-transport.raw','source-ack.raw','source-control.raw','source-admission.raw')}
        mutations=[('source-transport.raw',b'BADMAGIC'+raw_files['source-transport.raw'][8:]),
            ('source-transport.raw',raw_files['source-transport.raw']+b'trailing'),
            ('source-transport.raw',raw_files['source-transport.raw'][:-1]),
            ('source-ack.raw',raw_files['source-ack.raw'].replace(b'ACK 32',b'ACK 31')),
            ('source-control.raw',raw_files['source-control.raw'].replace(b'33500',b'33501')),
            ('source-admission.raw',raw_files['source-admission.raw'].replace(b'"sequence":32',b'"sequence":31'))]
        for name,data in mutations:
            with self.subTest(name=name,sha=hashlib.sha256(data).hexdigest()):
                self.raw(directory/name,data);self.reseal_run_leaves(directory)
                fresh=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);fresh.plan=self.plan;self.replays.append(fresh)
                with self.assertRaises(self.cold.Refusal):fresh.run(1,'front_gate','default',source,self.guest_owner)
                fresh.h.close();self.raw(directory/name,raw_files[name]);self.reseal_run_leaves(directory)

    def test_resealed_journal_pts_caps_digest_eos_order_and_cohort_corruption_is_refused(self):
        import json
        replay=self.fixture('research');directory=self.attempt/'guest/run-01-front_gate-default';source=self.plan['sources'][0]
        raw=(directory/'events.jsonl').read_bytes();original=[json.loads(line) for line in raw.splitlines()]
        for kind,field,value in [('decoder_sink','pts',999),('decoder_src','caps',None),('rgb_output','pixel_sha256','x'*64),
            ('rgb_output','output_ordinal',2),('admission_declaration','event_seq',9),('decoder_sink_eos_observed','kind','missing_sink_eos')]:
            with self.subTest(kind=kind,field=field):
                rows=json.loads(json.dumps(original));next(row for row in rows if row['kind']==kind)[field]=value
                self.raw(directory/'events.jsonl',b''.join(self.cold.canonical(row)+b'\n' for row in rows));self.reseal_run_leaves(directory)
                fresh=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);fresh.plan=self.plan;self.replays.append(fresh)
                with self.assertRaises(self.cold.Refusal):fresh.run(1,'front_gate','default',source,self.guest_owner)
                fresh.h.close()
        self.raw(directory/'events.jsonl',raw)
        observed=self.decoded(directory/'observations.v1.json');observed['timings'][8]['cohort']='startup'
        self.replace_document(directory/'observations.v1.json',timings=observed['timings']);self.reseal_run_leaves(directory)
        fresh=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);fresh.plan=self.plan;self.replays.append(fresh)
        with self.assertRaisesRegex(self.cold.Refusal,'recomputation'):fresh.run(1,'front_gate','default',source,self.guest_owner)

    def test_fd_namespace_byte_and_json_limits_refuse_without_unbounded_acquisition(self):
        directory=self.base/'bounded';directory.mkdir();self.raw(directory/'leaf',b'12345')
        held=self.cold.Held(directory,time.monotonic()+3)
        try:
            with self.assertRaisesRegex(self.cold.Refusal,'cap'):held.pin(directory/'leaf',maximum=4)
        finally:held.close()
        for n in range(129):self.raw(directory/f'leaf-{n}')
        held=self.cold.Held(directory,time.monotonic()+3)
        try:
            with self.assertRaisesRegex(self.cold.Refusal,'namespace leaf count'):held.members(directory)
        finally:held.close()
        with self.assertRaises(self.cold.Refusal):self.cold.strict_json(b'{"a":1,"a":2}')
        with self.assertRaises(self.cold.Refusal):self.cold.strict_json(b'{"a":NaN}')
        with self.assertRaisesRegex(self.cold.Refusal,'report2MiB'):self.cold.save_exclusive(self.base/'oversize.json',{'raw':'x'*(2*1048576)})

    def test_metadata_positive_cannot_authorize_foreign_owner_or_partial_maps(self):
        replay=self.fixture();path=self.attempt/'guest/metadata/mapped-inputs-01-closed.v1.json';original=self.decoded(path)
        cases=[dict(owner_after=self.owner(999)),dict(observation_complete=False),dict(selected_rows_after=[])]
        for fields in cases:
            with self.subTest(fields=fields):
                descriptor=self.replace_document(path,**fields);collection=[dict(descriptor,path='/opt/vast/output/metadata/'+path.name)]
                fresh=self.cold.Replay(self.project,self.repository,self.attempt,'metadata-only',self.S,self.P);self.replays.append(fresh)
                with self.assertRaises(self.cold.Refusal):fresh.mappings(dict(mapped_library_collections=collection),dict(mapped_library_collections=collection),
                    {row['path']:row for row in self.packages},self.guest_owner,[])
                fresh.h.close();self.raw(path,self.cold.canonical(original)+b'\n')

    def test_failed_main_retains_prefix_and_independent_close_status_without_promotion(self):
        import contextlib,io
        replay=self.fixture('research');path=self.attempt/'guest/run-01-front_gate-default/source-transport.raw'
        self.raw(path,path.read_bytes()[:-1]);self.patch_anchor('PLANNING',self.P)
        report=self.base/'failed-report.json'
        argv=['cold','--project-root',str(self.project),'--review-repository-root',str(self.repository),'--planning-commit',self.P,
            '--source-commit',self.S,'--mode','research','--attempt',str(self.attempt),'--external-terminal',str(self.external/'terminal.v1.json'),
            '--capture-source-sha256',self.capture_sha,'--capture-tool-record',str(self.tool),'--report',str(report)]
        # Fixing the expected planning anchor is an explicit synthetic fixture;
        # Git/source validators remain real and no production CLI grant is used.
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()):code=self.cold.main()
        self.assertEqual(code,1);value=self.decoded(report)
        self.assertFalse(value['raw_join_complete']);self.assertFalse(value['research_complete']);self.assertFalse(value['accepted'])
        self.assertTrue(value['all_held_fds_released']);self.assertEqual(value['close_errors'],[])
        self.assertEqual(value['valid_prefix_findings'][0]['hash_valid_packet_prefix'],31)

    def test_controller_positive_body_does_not_override_post_close_failure(self):
        replay=self.fixture();path=self.external/'original.stdout';value=self.decoded(path)
        value['pins_closed']=False;self.raw(path,self.cold.canonical(value)+b'\n')
        self.replace_document(self.external/'terminal.v1.json',stdout=dict(path=str(path),size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        # This directly audits the closed external records, independently of
        # the additional trusted tool boundary which is validated separately.
        replay.plan=self.plan;replay.binding=self.binding
        terminal_descriptor=dict(path=str(self.external/'terminal.v1.json'),size_bytes=(self.external/'terminal.v1.json').stat().st_size,
            sha256=hashlib.sha256((self.external/'terminal.v1.json').read_bytes()).hexdigest())
        record=self.decoded(self.tool);record['tool_calls'][0]['result']['output']=self.cold.canonical(dict(receipt=terminal_descriptor,
            external_capture_completed=True,late_terminal=None,close_errors=[])).decode()+'\n';self.raw(self.tool,self.cold.canonical(record))
        replay.source_bindings(self.plan)
        with self.assertRaisesRegex(self.cold.Refusal,'post-close controller'):replay.external(self.external/'terminal.v1.json',self.capture_sha,self.tool)

    def test_failed_main_invalidates_prefix_after_real_held_epoch_mutation(self):
        import contextlib,io
        self.fixture('research');path=self.attempt/'guest/run-01-front_gate-default/source-transport.raw'
        self.raw(path,path.read_bytes()[:-1]);self.patch_anchor('PLANNING',self.P)
        report=self.base/'mutated-prefix-report.json';observed=[];causes=[]
        original_prefix=self.cold.Replay.failed_prefixes;original_execute=self.cold.Replay.execute
        def execute(subject,*args):
            try:return original_execute(subject,*args)
            except ValueError as error:
                causes.append({'type':type(error).__name__,'message':str(error)[:4096]});raise
        def mutate_after_reads(subject):
            value=original_prefix(subject);observed.append(value)
            info=path.stat();os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+1))
            return value
        argv=['cold','--project-root',str(self.project),'--review-repository-root',str(self.repository),'--planning-commit',self.P,
            '--source-commit',self.S,'--mode','research','--attempt',str(self.attempt),'--external-terminal',str(self.external/'terminal.v1.json'),
            '--capture-source-sha256',self.capture_sha,'--capture-tool-record',str(self.tool),'--report',str(report)]
        with patch.object(sys,'argv',argv),patch.object(self.cold.Replay,'execute',execute), \
             patch.object(self.cold.Replay,'failed_prefixes',mutate_after_reads),contextlib.redirect_stdout(io.StringIO()):
            code=self.cold.main()
        self.assertEqual(code,1);self.assertEqual(observed[0][0]['hash_valid_packet_prefix'],31)
        value=self.decoded(report);self.assertEqual(value['first_failure'],causes[0])
        self.assertTrue(value['all_held_fds_released']);self.assertFalse(value['raw_join_complete'])
        self.assertTrue(value['valid_prefix_findings'])
        self.assertTrue(all('hash_valid_packet_prefix' not in row for row in value['valid_prefix_findings']))

    def test_source_start_requires_ready_loaded_observation_and_enabling_intent(self):
        import json
        self.fixture('research');directory=self.attempt/'guest/run-01-front_gate-default';source=self.plan['sources'][0]
        original=[json.loads(line) for line in (directory/'events.jsonl').read_bytes().splitlines()]
        for field,target in [('READY','start_intent'),('actual_source_loaded_libraries','READY'),
                             ('STARTED','start_intent'),('admission_declaration','start_intent')]:
            with self.subTest(moved=field,target=target):
                rows=json.loads(json.dumps(original))
                def selected(row,kind):return row.get('status')==kind or row['kind']==kind
                moved=rows.pop(next(i for i,row in enumerate(rows) if selected(row,field)))
                position=next(i for i,row in enumerate(rows) if selected(row,target))
                rows.insert(position+(1 if field=='READY' else 0),moved)
                for i,row in enumerate(rows,1):row['event_seq']=i
                self.raw(directory/'events.jsonl',b''.join(self.cold.canonical(row)+b'\n' for row in rows));self.reseal_run_leaves(directory)
                fresh=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);fresh.plan=self.plan;self.replays.append(fresh)
                with self.assertRaisesRegex(self.cold.Refusal,'source START enabling causality'):
                    fresh.run(1,'front_gate','default',source,self.guest_owner)
                fresh.h.close()

    def test_original_admission_types_u64_and_reserved_duration_are_rejected(self):
        import json
        replay=self.fixture('research');directory=self.attempt/'guest/run-01-front_gate-default';source=self.plan['sources'][0]
        admissions=[json.loads(line) for line in (directory/'source-admission.raw').read_bytes().splitlines()]
        for field,value in [('protocol_version',True),('sequence',True),('stream_id',False),('source_cycle',False),
                            ('access_unit_pts_ns',False),('payload_size_bytes',4.0),('schedule_offset_ns',False),
                            ('admission_timestamp_ms',2000.0),('schedule_offset_ns',1<<64)]:
            with self.subTest(field=field,value=value):
                changed=json.loads(json.dumps(admissions));changed[0][field]=value
                with self.assertRaisesRegex(self.cold.Refusal,'original admission types/u64'):
                    replay.packets(directory,changed,source,'research-decoder-01')
        raw=bytearray((directory/'source-transport.raw').read_bytes());offset=0
        for _ in range(32):
            header=list(self.cold.HEADER.unpack(raw[offset:offset+80]));last=offset
            offset+=80+header[9]+header[10]+header[11]+header[12]
        header[8]=self.cold.MISSING;raw[last:last+80]=self.cold.HEADER.pack(*header)
        # The final duration has no next declaration to expose its sentinel.
        replay.h.close();self.raw(directory/'source-transport.raw',raw)
        fresh=self.cold.Replay(self.project,self.repository,self.attempt,'research',self.S,self.P);self.replays.append(fresh)
        with self.assertRaisesRegex(self.cold.Refusal,'original text/PTS/cadence'):
            fresh.packets(directory,admissions,source,'research-decoder-01')


if __name__=='__main__':unittest.main(verbosity=2)
