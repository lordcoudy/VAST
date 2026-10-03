"""Real files/CPython children; explicit engine and GI fixtures, never Docker/GI acceptance."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import controller
import guest_consumer
import research_protocol as p
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
from publication_operational_container_custody_v1 import _state, _confirmed_absent, _successful_terminal

CID='a'*64
ENGINE_FIXTURE=r'''
import json,sys
from pathlib import Path
file=Path(sys.argv[1]);args=json.loads(sys.argv[2]);data=json.loads(file.read_text())
if args[:2]==['container','inspect']:
 identifier=args[-1]
 if data['not_found_remaining']:
  data['not_found_remaining']-=1;file.write_text(json.dumps(data));absent=True
 else:absent=data['removed']
 if absent:
  sys.stdout.write('\n');sys.stderr.write('Error response from daemon: No such container: '+identifier+'\n');sys.exit(1)
 print(json.dumps(data['state']))
elif args[:2]==['container','rm']:
 assert args==['container','rm',data['state']['Id']]
 data['removed']=True;file.write_text(json.dumps(data));print(data['state']['Id'])
elif args==['info','--format','{{json .ID}}']:
 print(json.dumps(data['daemon_id'],separators=(',',':')))
else:raise RuntimeError('unsupported explicit engine fixture command')
'''


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        c=self.c=controller.Controller.__new__(controller.Controller)
        c.cidfile=self.base/'original.cid';c.cid_fd=None;c.cid_identity=None;c.cid_pin=None
        c.cid_last_observation=None;c.cid_observation_count=0;c.container_id=None
        c.cid_ownership_observed=False;c.cleanup_deadline=None;c.in_cleanup=False
        c.deadline=time.monotonic()+20;c.phase_deadline=c.deadline;c.pins=[];c.errors=[]
        c.evidence=p.Evidence(self.base/'controller');c.name='explicit-engine-fixture'
        c.label='b'*64;c.reserved_at=time.time_ns()-3_000_000_000
        c.sequence=0;c.engine=p.Pin(Path(sys.executable));c.environment={'PATH':'/usr/bin:/bin'}
        c.abort=threading.Event();c.check_socket=lambda:c.engine.verify()
        c.projection='explicit-fixture-projection';c.absent=_confirmed_absent;c.state=_state
        c.successful_container_terminal=_successful_terminal;c.process=None
        now=datetime.now(timezone.utc)
        timestamp=lambda delta:(now+timedelta(seconds=delta)).isoformat().replace('+00:00','Z')
        state={'Id':CID,'Name':'/'+c.name,'Image':controller.IMAGE_ID,'Created':timestamp(-2),
            'Running':False,'OOMKilled':False,'ExitCode':0,'Pid':0,'StartedAt':timestamp(-1.5),
            'FinishedAt':timestamp(-1),'Operation':c.label}
        self.fixture_file=self.base/'engine-fixture.json'
        self.fixture_file.write_text(json.dumps({'state':state,'not_found_remaining':0,'removed':False,
            'daemon_id':controller.DAEMON_ID}))
        self.calls=[];self.cleanup_deadlines=[]
        def fixture_command(arguments,timeout=10):
            if c.in_cleanup:
                self.assertIsNotNone(c.process.returncode,'launcher must be reaped before publication observations')
                self.cleanup_deadlines.append(c.cleanup_deadline)
            self.calls.append(arguments)
            return controller.Controller.command(c,['-I','-B','-c',ENGINE_FIXTURE,
                str(self.fixture_file),json.dumps(arguments)],timeout=timeout)
        c.command=fixture_command

    def tearDown(self):
        c=self.c
        if c.process is not None and c.process.poll() is None:
            os.killpg(c.process.pid,signal.SIGKILL);c.process.wait(timeout=2)
        if c.cid_fd is not None:os.close(c.cid_fd)
        c.evidence.close()
        for pin in c.pins:pin.close()
        c.engine.close();self.temp.cleanup()

    def child(self,program):
        c=self.c
        c.process=subprocess.Popen([sys.executable,'-I','-B','-c',program,str(c.cidfile)],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        threads=[]
        for stream,name in ((c.process.stdout,'fixture.stdout'),(c.process.stderr,'fixture.stderr')):
            target=c.evidence.open(name,p.CHANNEL_MAX)
            thread=threading.Thread(target=c.drain,args=(stream,target,c.errors,time.monotonic()+20),daemon=True)
            thread.start();threads.append(thread)
        return threads

    def test_original_partial_file_publication_stays_pending_until_stable_complete(self):
        threads=self.child("import os,sys,time;f=open(sys.argv[1],'wb');f.flush();time.sleep(.05);f.write(b'a'*8);f.flush();time.sleep(.05);f.write(b'a'*56);f.flush();f.close()")
        pending=0
        until=time.monotonic()+3
        while time.monotonic()<until:
            result=self.c.observe_cid()
            if result is not None:break
            pending+=1;time.sleep(.01)
        self.c.process.wait(timeout=2)
        for thread in threads:thread.join(timeout=1)
        self.assertEqual(result,CID);self.assertGreater(pending,0)
        self.assertIsNotNone(self.c.cid_pin);self.assertEqual(len(self.c.pins),1)
        self.assertEqual(self.c.observe_cid(),CID);self.assertEqual(len(self.c.pins),1)
        rows=[json.loads(raw) for raw in (self.c.evidence.directory/'events.jsonl').read_bytes().splitlines()]
        observed=[row for row in rows if row['kind']=='original_cid_observation']
        self.assertTrue(any(row['after'] is not None and row['after'][4]<64 for row in observed));self.assertEqual(observed[-1]['partial_hex'],(b'a'*64).hex())

    def test_complete_cid_optional_newline_and_physical_hash(self):
        self.c.cidfile.write_bytes((CID+'\n').encode())
        self.assertEqual(self.c.observe_cid(),CID)
        self.assertEqual(self.c.cid_pin.descriptor['sha256'],hashlib.sha256((CID+'\n').encode()).hexdigest())

    def test_malformed_and_oversize_cid_retain_actual_failure_stat(self):
        for raw in (b'x',b'a'*64+b'x',b'a'*66):
            self.c.cidfile.write_bytes(raw)
            with self.assertRaises(p.ResearchError):self.c.observe_cid()
            rows=[json.loads(line) for line in (self.c.evidence.directory/'events.jsonl').read_bytes().splitlines()]
            self.assertIsNotNone(rows[-1]['failure']);self.assertEqual(rows[-1]['after'][4],len(raw))

    def test_original_inode_substitution_symlink_and_multiple_links_reject(self):
        self.c.cidfile.write_bytes(b'a'*8);self.assertIsNone(self.c.observe_cid())
        self.c.cidfile.unlink();self.c.cidfile.write_bytes(b'a'*64)
        with self.assertRaises(p.ResearchError):self.c.observe_cid()
        rows=[json.loads(line) for line in (self.c.evidence.directory/'events.jsonl').read_bytes().splitlines()]
        self.assertEqual(rows[-1]['named'],p.epoch(self.c.cidfile.lstat()))
        self.assertNotEqual(rows[-1]['named'][:2],rows[-1]['before'][:2])
        self.c.cidfile.unlink();self.c.cidfile.symlink_to(self.fixture_file)
        with self.assertRaises(p.ResearchError):self.c.observe_cid()
        self.c.cidfile.unlink();self.c.cidfile.write_bytes(b'a'*64)
        os.link(self.c.cidfile,self.base/'second-link')
        with self.assertRaises(p.ResearchError):self.c.observe_cid()

    def test_fast_natural_launcher_exit_binds_complete_cid_and_removes_before_both_absences(self):
        threads=self.child("import os,sys;open(sys.argv[1],'wb').write(b'a'*64);os.write(1,b'A'*4096);os.write(2,b'B'*4096)")
        self.c.process.wait(timeout=2)
        self.c.cleanup_original(threads)
        self.assertFalse(self.c.errors);self.assertTrue(self.c.absent_after_rm)
        self.assertEqual(self.c.process.returncode,0);self.assertIsNotNone(self.c.cid_pin)
        removal=self.calls.index(['container','rm',CID])
        self.assertEqual([row[-1] for row in self.calls[removal+1:]],[CID,self.c.name])
        self.assertEqual((self.c.evidence.directory/'fixture.stdout').read_bytes(),b'A'*4096)
        self.assertEqual((self.c.evidence.directory/'fixture.stderr').read_bytes(),b'B'*4096)
        self.assertEqual(len(set(self.cleanup_deadlines)),1);self.assertLess(self.c.cleanup_elapsed_s,15)

    def test_delayed_name_publication_is_not_earlier_removal_absence(self):
        data=json.loads(self.fixture_file.read_text());data['not_found_remaining']=1
        self.fixture_file.write_text(json.dumps(data))
        threads=self.child('pass');self.c.process.wait(timeout=2)
        self.c.cleanup_original(threads)
        self.assertTrue(self.c.absent_after_rm)
        self.assertTrue(any('completed CID' in error for error in self.c.errors))
        self.assertEqual(self.calls[0][-1],self.c.name);self.assertEqual(self.calls[1][-1],self.c.name)

    def test_bad_cid_keeps_failure_but_cleans_positive_exact_name_owner(self):
        threads=self.child("import sys;open(sys.argv[1],'wb').write(b'not-a-cid')")
        self.c.process.wait(timeout=2);self.c.cleanup_original(threads)
        self.assertTrue(self.c.absent_after_rm);self.assertTrue(self.c.errors)
        self.assertIn(['container','rm',CID],self.calls)

    def test_original_live_launcher_is_reaped_before_engine_fixture_observation(self):
        threads=self.child("import sys,time;open(sys.argv[1],'wb').write(b'a'*64);time.sleep(10)")
        time.sleep(.05);pid=self.c.process.pid
        self.c.cleanup_original(threads)
        self.assertNotEqual(self.c.process.returncode,0);self.assertFalse(Path(f'/proc/{pid}').exists())
        self.assertTrue(any('process-group termination' in error for error in self.c.errors))

    def test_cleanup_command_cannot_consume_final_deadline_reserve(self):
        self.c.in_cleanup=True;self.c.cleanup_deadline=time.monotonic()+1
        with self.assertRaises(p.ResearchError):controller.Controller.command(self.c,['-I','-B','-c','pass'])
        self.assertEqual(self.c.sequence,0)

    def test_unresolved_publication_keeps_unknown_and_never_claims_removal_absence(self):
        data=json.loads(self.fixture_file.read_text());data['not_found_remaining']=100
        self.fixture_file.write_text(json.dumps(data))
        threads=self.child('raise SystemExit(1)');self.c.process.wait(timeout=2)
        self.c.cleanup_original(threads)
        self.assertFalse(self.c.absent_after_rm);self.assertIsNone(self.c.final_state)
        self.assertTrue(any('unresolved' in error for error in self.c.errors),self.c.errors)
        self.assertFalse(any(row[:2]==['container','rm'] for row in self.calls))
        self.assertLess(self.c.cleanup_elapsed_s,15)

    def outer_finalization_crossing(self,body_failure):
        """Actual 15s boundary and files/children; synthetic guest-result seam, no decoder claim."""
        c=self.c
        c.destination=self.base;c.start=time.monotonic();c.deadline=c.start+600
        c.socket_fd=os.open(self.fixture_file,os.O_RDONLY);c.daemon=p.canonical(controller.DAEMON_ID)+b'\n'
        c.child=None;c.preflight=lambda:None;c.monitor_namespaces=lambda:[]
        def original_fixture_launch():
            threads=self.child("import sys;open(sys.argv[1],'wb').write(b'a'*64)")
            c.child=p.owner(c.process.pid);c.process.wait(timeout=2)
            c.cleanup_original(threads)
            guest=self.base/'guest/metadata';guest.mkdir(parents=True)
            (guest/'research-terminal.v1.json').write_bytes(p.canonical(p.seal({
                'result':{'explicit_synthetic_guest_result':True},'failure':None,'runs_completed':4,
                'elapsed_s':1,'accepted':False,'publication_ready':False}))+b'\n')
            if body_failure:raise p.ResearchError('original outer fixture body cause')
        c.launch=original_fixture_launch
        original_document=c.evidence.document
        def bounded_final_document(name,value,final=False):
            receipt=original_document(name,value,final)
            if name=='terminal.v1.json':
                # Deliberately make the real final append/close cross the unchanged cleanup clock.
                time.sleep(max(0,c.cleanup_deadline-time.monotonic())+0.02)
            return receipt
        c.evidence.document=bounded_final_document
        self.assertEqual(c.execute(),1)
        self.assertLess(time.monotonic(),c.deadline)
        terminal=p.verify_seal(p.strict_object((c.evidence.directory/'terminal.v1.json').read_bytes()))
        late=p.verify_seal(p.strict_object((c.evidence.directory/'receipt-time-limit-failure.v1.json').read_bytes()))
        self.assertEqual(late['cleanup_deadline_monotonic_s'],c.cleanup_deadline)
        self.assertGreater(late['observed_after_final_close_monotonic_s'],c.cleanup_deadline)
        self.assertEqual(Path(late['provisional_terminal']['path']).read_bytes(),
            (c.evidence.directory/'terminal.v1.json').read_bytes())
        if body_failure:self.assertEqual(terminal['failure'],'original outer fixture body cause')
        else:self.assertTrue(terminal['original_execution_completed'])
        self.assertFalse(c.evidence.streams)
        self.assertFalse(Path(f'/proc/{c.process.pid}').exists())

    def test_outer_successful_body_crosses_original_cleanup15_and_rejects_success(self):
        self.outer_finalization_crossing(False)

    def test_outer_failed_body_preserves_cause_when_original_cleanup15_is_crossed(self):
        self.outer_finalization_crossing(True)

    def guest(self):
        guest=guest_consumer.Guest.__new__(guest_consumer.Guest)
        guest.begun=time.monotonic();guest.overall_deadline=guest.begun+20;guest.failure_stage='fixture_preflight'
        guest.metadata=p.Evidence(self.base/'guest');guest.runs=[];guest.pins=[];guest.plan={}
        plan=self.base/'fixture-plan';plan.write_text('explicit fixture, not an authority')
        guest.plan_pin=p.Pin(plan);guest.pins.append(guest.plan_pin)
        typelib=self.base/'fixture-typelib';typelib.write_bytes(b'explicit GI metadata fixture')
        def pin(path,expected=None):
            actual=typelib if str(path).endswith('/Gst-1.0.typelib') else Path(path)
            held=p.Pin(actual);guest.pins.append(held);return held
        guest.pin=pin
        gi=types.SimpleNamespace(__file__=str(Path(__file__)),_gi=types.SimpleNamespace(__file__=str(Path(__file__))))
        return guest,gi

    def test_single_explicit_list_initializer_records_actual_fixture_callable_and_stages(self):
        guest,gi=self.guest();calls=[]
        def init(argv):
            """Explicit fake GI callable; None would raise, no installed GI is invoked."""
            if argv is None:raise TypeError('None not allowed in explicit fixture')
            calls.append(argv)
        Gst=types.SimpleNamespace(init=init,is_initialized=lambda:True)
        try:
            guest.initialize_gst(Gst,gi)
            self.assertEqual(calls,[[]])
            metadata=p.verify_seal(p.strict_object((guest.metadata.directory/'initialization-metadata.v1.json').read_bytes(),p.METADATA_MAX))
            self.assertEqual(metadata['intended_arguments'],[]);self.assertEqual(metadata['code_filename'],__file__)
            self.assertTrue(metadata['actual_loaded_override_sources'])
        finally:
            guest.metadata.close()
            for held in guest.pins:held.close()

    def test_original_initializer_failure_keeps_stage_type_and_bounded_trace_without_fallback(self):
        guest,gi=self.guest();calls=[]
        def init(argv):calls.append(argv);raise TypeError('original explicit initializer fixture failure')
        Gst=types.SimpleNamespace(init=init,is_initialized=lambda:False)
        guest.preflight=lambda:guest.initialize_gst(Gst,gi)
        self.assertEqual(guest.execute(),1);self.assertEqual(calls,[[]])
        terminal=p.verify_seal(p.strict_object((guest.metadata.directory/'research-terminal.v1.json').read_bytes()))
        self.assertEqual(terminal['failure_stage'],'gst_init_empty_list')
        self.assertEqual(terminal['failure_type'],'builtins.TypeError')
        raw=Path(terminal['failure_traceback']['path']).read_bytes()
        self.assertIn(b'original explicit initializer fixture failure',raw);self.assertLessEqual(len(raw),p.EVENT_MAX)
        self.assertEqual(terminal['runs_completed'],0);self.assertIsNone(terminal['result'])

    def test_initialization_doc_cap_fails_before_single_intended_call(self):
        guest,gi=self.guest();calls=[]
        def init(argv):calls.append(argv)
        init.__doc__='x'*4097
        Gst=types.SimpleNamespace(init=init,is_initialized=lambda:True)
        guest.preflight=lambda:guest.initialize_gst(Gst,gi)
        self.assertEqual(guest.execute(),1);self.assertEqual(calls,[])
        terminal=p.verify_seal(p.strict_object((guest.metadata.directory/'research-terminal.v1.json').read_bytes()))
        self.assertEqual(terminal['failure_stage'],'gst_initialization_metadata')


if __name__=='__main__':unittest.main(verbosity=2)
