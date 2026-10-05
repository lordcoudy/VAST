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
from unittest.mock import patch

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
        c.mode='research';c.root=self.base;c.review_root=self.base
        c.source_commit='c'*40;c.current_checkout_commit='d'*40
        c.plan_descriptor={'path':'explicit fixture plan','sha256':'e'*64,'size_bytes':1}
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
                'artifact_kind':'vast_decoder_research_guest_terminal_v1',
                'planning_commit':controller.PLANNING_COMMIT,'source_commit':c.source_commit,
                'current_checkout_commit':c.current_checkout_commit,'mode':'research','plan':c.plan_descriptor,
                'review_repository_root':str(c.review_root),'project_root':str(c.root),
                'operation_completed':True,'research_complete':True,'provisional_until_owner_final_close':True,
                'result':{'explicit_synthetic_guest_result':True},'failure':None,'runs_completed':4,
                'elapsed_s':1,'accepted':False,'publication_ready':False,'native_pair_count':0,
                'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False}))+b'\n')
            for number,(clip,setting) in enumerate(controller.FIXED_ORDER,1):
                (self.base/f'guest/run-{number:02d}-{clip}-{setting}').mkdir()
            (c.evidence.directory/'original.stdout').write_bytes(p.canonical({'successful':True,
                'receipt':p.physical_descriptor(guest/'research-terminal.v1.json'),
                'receipt_time_limit_failure':None,'close_failure':None,'metadata_close_error':None,
                'pin_close_error':None,'close_failure_capture_error':None})+b'\n')
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
        guest.metadata=p.Evidence(self.base/'guest');guest.runs=[];guest.pins=[];guest.mode='research'
        guest.plan={'planning_commit':controller.PLANNING_COMMIT,'source_commit':'c'*40,
            'current_checkout_commit':'d'*40,'mode':'research'}
        guest.phase_deadline=guest.overall_deadline
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


class ReviewedInputTests(unittest.TestCase):
    """Disposable native Git repositories; no historical repository or engine access."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.repo=self.base/'repo';self.repo.mkdir()
        self.git('init','-q')
        self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        self.planning={name:('reviewed '+name+'\n').encode() for name in
            ('proposal.md','design.md','tasks.md','specs/benchmark-launch-preparation/spec.md')}
        self.change=self.repo/'openspec/changes/fix-decoder-preflight'
        for name,raw in self.planning.items():
            path=self.change/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        self.git('add','.');self.git('commit','-qm','reviewed planning')
        self.P=self.git('rev-parse','HEAD').decode().strip()
        self.code=self.repo/'artifacts/benchmark_recovery_20260930/decoder-research-implementation-v6'
        self.code.mkdir(parents=True)
        for name in ('controller.py','guest_consumer.py','research_protocol.py'):
            (self.code/name).write_bytes(('explicit fixture '+name+'\n').encode())
        self.git('add','.');self.git('commit','-qm','reviewed source')
        self.S=self.git('rev-parse','HEAD').decode().strip()
        self.c=controller.Controller.__new__(controller.Controller)
        self.c.review_root=self.repo;self.c.source_commit=self.S;self.c.pins=[]
        self.c.phase_deadline=time.monotonic()+20;self.c.abort=threading.Event()
        self.c.environment={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'}
        self.c.evidence=p.Evidence(self.base/'controller');self.c.git_sequence=0

    def tearDown(self):
        self.c.evidence.close()
        for held in self.c.pins:held.close()
        self.temp.cleanup()

    def git(self,*args):
        return subprocess.run(['/usr/bin/git','-c','core.longpaths=true','-C',str(self.repo),*args],check=True,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5).stdout

    def prepare(self):
        with patch.object(controller,'PLANNING_COMMIT',self.P):
            return self.c.prepare_reviewed_inputs(self.code)

    def test_task_progress_and_archived_paths_use_exact_raw_reviewed_blobs(self):
        (self.change/'tasks.md').write_text('later checked task\n')
        archive=self.repo/'openspec/changes/archive/2026-10-04-fix-decoder-preflight'
        archive.parent.mkdir();self.change.rename(archive)
        self.git('add','-A');self.git('commit','-qm','progress and archive')
        rows=self.prepare()
        self.assertEqual(len(rows),4)
        self.assertEqual(self.c.current_checkout_commit,self.git('rev-parse','HEAD').decode().strip())
        for row,(name,raw) in zip(rows,self.planning.items()):
            self.assertEqual(Path(row['path']).read_bytes(),raw)
            self.assertEqual(row['planning_commit'],self.P)
            self.assertEqual(row['git_path'],'openspec/changes/fix-decoder-preflight/'+name)
            self.assertEqual(row['sha256'],hashlib.sha256(raw).hexdigest())

    def test_supported_native_git_worktree_is_accepted(self):
        worktree=self.base/'worktree';self.git('worktree','add','-q','--detach',str(worktree),self.S)
        self.c.review_root=worktree
        self.code=worktree/self.code.relative_to(self.repo)
        self.assertEqual(len(self.prepare()),4)

    def test_foreign_repository_and_unreviewed_source_drift_are_rejected(self):
        foreign=self.base/'foreign';foreign.mkdir()
        subprocess.run(['/usr/bin/git','-c','core.longpaths=true','-C',str(foreign),'init','-q'],check=True,timeout=5)
        self.c.review_root=foreign
        with self.assertRaises(p.ResearchError):self.prepare()
        self.c.review_root=self.repo;(self.code/'guest_consumer.py').write_bytes(b'changed physical runtime')
        with self.assertRaises(p.ResearchError):self.prepare()

    def test_missing_runtime_source_and_nonexact_source_parameter_are_rejected(self):
        self.c.source_commit=self.P
        with self.assertRaises(p.ResearchError):self.prepare()
        self.c.source_commit='HEAD'
        with self.assertRaises(p.ResearchError):self.prepare()

    def test_reviewed_planning_must_be_ancestor_of_exact_source(self):
        self.git('checkout','-q','--orphan','foreign-history')
        self.git('commit','-qm','same files with foreign history')
        self.c.source_commit=self.git('rev-parse','HEAD').decode().strip()
        with self.assertRaisesRegex(p.ResearchError,'Git command failed'):self.prepare()

    def test_oversized_reviewed_blob_is_rejected_before_raw_copy(self):
        (self.change/'proposal.md').write_bytes(b'x'*(p.CHANNEL_MAX+1))
        self.git('add','.');self.git('commit','-qm','oversized reviewed blob')
        self.P=self.git('rev-parse','HEAD').decode().strip();self.S=self.P;self.c.source_commit=self.S
        with self.assertRaises(p.ResearchError):self.prepare()
        self.assertFalse((self.c.evidence.directory/'reviewed-proposal.md').exists())

    def test_expired_shared_prelaunch_deadline_rejects_before_git_child(self):
        self.c.phase_deadline=time.monotonic()-1
        with self.assertRaises(p.ResearchError):self.prepare()
        self.assertEqual(self.c.git_sequence,0)

    def test_actual_git_stdout_stream_cap_rejects_and_reaps_owned_child(self):
        self.c.git_pin=self.c.pin('/usr/bin/git')
        with self.assertRaisesRegex(p.ResearchError,'byte cap'):
            self.c.git_command(['show',self.P+':'+controller.PLANNING_PATH+'proposal.md'],4)
        record=p.verify_seal(p.strict_object((self.c.evidence.directory/'git-01.v1.json').read_bytes(),p.METADATA_MAX))
        self.assertFalse(Path(f"/proc/{record['child']['pid']}").exists())
        self.assertFalse(any(name.startswith('git-') and name.endswith(('.stdout','.stderr'))
            for name in self.c.evidence.streams))

    def test_owned_auxiliary_is_killed_at_actual_remaining_shared_deadline(self):
        fixture=self.base/'sleeping-auxiliary'
        fixture.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(10)\n');fixture.chmod(0o700)
        self.c.git_pin=self.c.pin(fixture);self.c.phase_deadline=time.monotonic()+.15
        began=time.monotonic()
        with self.assertRaisesRegex(p.ResearchError,'deadline'):self.c.git_command([])
        record=p.verify_seal(p.strict_object((self.c.evidence.directory/'git-01.v1.json').read_bytes(),p.METADATA_MAX))
        self.assertEqual(record['returncode'],-signal.SIGKILL)
        self.assertFalse(Path(f"/proc/{record['child']['pid']}").exists())
        self.assertLess(time.monotonic()-began,1)

    def test_git_capture_close_failure_still_retires_other_original_stream(self):
        self.c.git_pin=self.c.pin('/usr/bin/git');target=None;faulted=False
        original_open=self.c.evidence.open;original_fsync=os.fsync
        def opened(name,maximum):
            nonlocal target
            result=original_open(name,maximum)
            if name=='git-01.stdout':target=self.c.evidence.streams[name]
            return result
        def fsync(fd):
            nonlocal faulted
            if fd==target and not faulted:
                faulted=True
                closed=os.dup(fd);os.close(closed);original_fsync(closed)  # Genuine EBADF on an owned, closed FD.
            return original_fsync(fd)
        self.c.evidence.open=opened
        with patch.object(controller.os,'fsync',fsync):
            with self.assertRaises(OSError):self.c.git_command(['rev-parse','HEAD'])
        self.assertFalse(any(name.startswith('git-') and name.endswith(('.stdout','.stderr'))
            for name in self.c.evidence.streams))

    def test_failed_initial_auxiliary_owner_observation_never_signals_unknown_group(self):
        fixture=self.base/'owner-failure-auxiliary'
        fixture.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(.05)\n');fixture.chmod(0o700)
        self.c.git_pin=self.c.pin(fixture);original_owner=controller.owner
        def observed(pid,**kwargs):
            if pid!=os.getpid():raise p.ResearchError('explicit initial owner observation unavailable')
            return original_owner(pid,**kwargs)
        with patch.object(controller,'owner',observed),patch.object(controller.os,'killpg',wraps=os.killpg) as kill:
            with self.assertRaisesRegex(p.ResearchError,'owner observation unavailable'):self.c.git_command([])
            self.assertEqual(kill.call_count,0)
        record=p.verify_seal(p.strict_object((self.c.evidence.directory/'git-01.v1.json').read_bytes(),p.METADATA_MAX))
        self.assertIsNone(record['child']);self.assertTrue(record['child_reaped'])

    def test_changed_auxiliary_owner_join_prevents_signal_and_preserves_cap_failure(self):
        fixture=self.base/'changed-owner-auxiliary'
        fixture.write_text('#!'+sys.executable+'\nimport time\nprint("too many original bytes",flush=True)\ntime.sleep(.05)\n')
        fixture.chmod(0o700);self.c.git_pin=self.c.pin(fixture);original_owner=controller.owner;calls=0
        def observed(pid,**kwargs):
            nonlocal calls
            actual=original_owner(pid,**kwargs)
            if pid!=os.getpid():
                calls+=1
                if calls==1:actual=dict(actual,starttime_ticks=actual['starttime_ticks']+1)
            return actual
        with patch.object(controller,'owner',observed),patch.object(controller.os,'killpg',wraps=os.killpg) as kill:
            with self.assertRaisesRegex(p.ResearchError,'byte cap'):self.c.git_command([],4)
            self.assertEqual(kill.call_count,0)
        record=p.verify_seal(p.strict_object((self.c.evidence.directory/'git-01.v1.json').read_bytes(),p.METADATA_MAX))
        self.assertTrue(record['child_reaped']);self.assertTrue(record['close_errors'])


class ControllerModeTests(unittest.TestCase):
    setUp=SetupTests.setUp
    tearDown=SetupTests.tearDown
    child=SetupTests.child

    def fixture(self,mode,receipt_mode=None,*,result=None,runs=0,companion=None):
        c=self.c;c.destination=self.base;c.mode=mode;c.start=time.monotonic();c.deadline=c.start+600
        c.phase_deadline=c.start+120;c.root=self.base;c.review_root=self.base
        c.source_commit='c'*40;c.current_checkout_commit='d'*40
        c.plan_descriptor={'path':'explicit fixture plan','sha256':'e'*64,'size_bytes':1}
        c.socket_fd=os.open(self.fixture_file,os.O_RDONLY);c.daemon=p.canonical(controller.DAEMON_ID)+b'\n'
        c.child=None;c.preflight=lambda:None
        guest=self.base/'guest/metadata';guest.mkdir(parents=True)
        receipt={'artifact_kind':('vast_decoder_research_metadata_preflight_terminal_v1' if mode=='metadata-only'
            else 'vast_decoder_research_guest_terminal_v1'),'planning_commit':controller.PLANNING_COMMIT,
            'source_commit':c.source_commit,'current_checkout_commit':c.current_checkout_commit,
            'review_repository_root':str(c.review_root),'project_root':str(c.root),
            'mode':receipt_mode or mode,'plan':c.plan_descriptor,'operation_completed':True,
            'metadata_preflight_completed':True,'research_complete':mode=='research',
            'result':result,'failure':None,'runs_completed':runs,'elapsed_s':1,
            'provisional_until_owner_final_close':True,'accepted':False,'publication_ready':False,
            'native_pair_count':0,'benchmark_arm_count':0,'qualification_count':0,'model_or_parity_evidence':False}
        name='metadata-preflight-terminal.v1.json' if mode=='metadata-only' else 'research-terminal.v1.json'
        raw=p.canonical(p.seal(receipt))+b'\n';(guest/name).write_bytes(raw)
        if companion:(guest/companion).write_bytes(b'explicit failure fixture')
        def launch():
            descriptor=p.physical_descriptor(guest/name)
            stdout=p.canonical({'successful':True,'receipt':descriptor,'receipt_time_limit_failure':None,
                'close_failure':None,'metadata_close_error':None,'pin_close_error':None,
                'close_failure_capture_error':None})+b'\n'
            (c.evidence.directory/'original.stdout').write_bytes(stdout)
            (c.evidence.directory/'original.stderr').write_bytes(b'')
            c.process=types.SimpleNamespace(returncode=0,poll=lambda:0);c.cleanup_deadline=time.monotonic()+15
            c.absent_after_rm=True;c.successful_original_state=True
        c.launch=launch
        return c

    def test_metadata_null_result_zero_runs_is_valid_after_original_close(self):
        self.assertEqual(self.fixture('metadata-only').execute(),0)

    def test_metadata_rejects_research_result_or_run_namespace(self):
        c=self.fixture('metadata-only',result={'synthetic':True},runs=4)
        self.assertEqual(c.execute(),1)

    def test_mode_mismatch_and_close_failure_never_promote(self):
        c=self.fixture('metadata-only',receipt_mode='research',companion='close-failure.v1.json')
        self.assertEqual(c.execute(),1)

    def test_metadata_mode_rejects_any_original_run_directory(self):
        c=self.fixture('metadata-only');(self.base/'guest/run-01-front_gate-default').mkdir()
        with self.assertRaises(p.ResearchError):c.monitor_namespaces()

    def test_metadata_fast_exit_still_checks_shared_body_deadline(self):
        c=self.fixture('metadata-only');c.start=time.monotonic()-121
        self.assertEqual(c.execute(),1)

    def test_missing_cli_mode_fails_before_engine_or_output_creation(self):
        output=self.base/'never-created'
        run=subprocess.run([sys.executable,'-I','-B',str(Path(controller.__file__)),
            '--project-root',str(self.base),'--output-dir',str(output),
            '--review-repository-root',str(self.base),'--source-commit','c'*40],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        self.assertEqual(run.returncode,2);self.assertIn(b'--mode',run.stderr)
        self.assertFalse(output.exists())

    def controller_close_fault(self,body_failure):
        c=self.fixture('metadata-only');held=c.pin(self.fixture_file)
        original_close=c.evidence.close;faulted=False
        def close():
            nonlocal faulted
            original_close()
            if (c.evidence.directory/'terminal.v1.json').exists() and not faulted:
                faulted=True
                os.close(-1)  # Real EBADF after provisional terminal's streams closed.
        c.evidence.close=close
        if body_failure:
            def primary():raise p.ResearchError('explicit original controller body failure')
            c.preflight=primary
        self.assertEqual(c.execute(),1)
        self.assertIsNone(held.fd)
        with self.assertRaises(OSError):os.fstat(c.socket_fd)
        terminal=p.verify_seal(p.strict_object((c.evidence.directory/'terminal.v1.json').read_bytes()))
        companion=p.verify_seal(p.strict_object((c.evidence.directory/'controller-close-failure.v1.json').read_bytes()))
        self.assertTrue(companion['close_errors'])
        if body_failure:
            self.assertEqual(terminal['failure'],'explicit original controller body failure')
            self.assertEqual(companion['original_failure'],terminal['failure'])
        else:self.assertTrue(terminal['original_execution_completed'])

    def test_controller_close_error_retires_remaining_pins_and_blocks_provisional_success(self):
        self.controller_close_fault(False)

    def test_controller_close_error_preserves_original_body_failure(self):
        self.controller_close_fault(True)


if __name__=='__main__':unittest.main(verbosity=2)
