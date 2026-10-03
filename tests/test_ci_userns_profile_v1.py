"""CI policy metadata and ordinary-process fixtures; no AppArmor/namespace load."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location('ci_profile', ROOT/'scripts/ci_userns_profile_v1.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def denial_fixture():
    """Retained5bc row shapes, explicitly synthetic current ownership/time values."""
    python = str(Path(sys.executable).resolve())
    info = os.stat(python)
    identity = {key: getattr(info, key) for key in
                ('st_dev','st_ino','st_mode','st_nlink','st_size','st_uid','st_gid')}
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    pid = os.getpid()
    mono, wall = time.monotonic_ns(), time.time_ns()
    capture = {'capture_completed':True,'returncode':1,'timed_out':False,
        'capture_exceeded':False,'failure':None,'eof':{'stdout':True,'stderr':True},
        'original_group_absent':True,'started_monotonic_ns':mono-1_000_000,
        'started_wall_time_ns':wall-1_000_000,'terminal_wall_time_ns':wall+3_000_000,
        'cleanup_deadline_ns':mono+10_000_000_000,
        'owner':{'pid':pid,'uid':os.getuid(),'gid':os.getgid(),'boot_id':boot,
                 'executable_realpath':python,'executable_stat':copy.deepcopy(identity)}}
    def row(event, syscall=None, offset=0, **fields):
        return {'event':event,'original_pid':pid,'pid':pid,'monotonic_ns':mono+offset,
                'wall_time_ns':wall+offset, **({'syscall':syscall} if syscall else {}), **fields}
    rows = [row('original_ready', executable=python,
                label={'path':'/proc/self/attr/current','value':'unconfined'}),
            row('syscall_started','unshare',offset=100_000,flags=268435456),
            row('syscall_completed','unshare',offset=100_000,flags=268435456,
                terminal_monotonic_ns=mono+200_000),
            row('syscall_started','open',offset=300_000,path='/proc/self/setgroups'),
            row('syscall_failed','open',offset=300_000,path='/proc/self/setgroups',errno=13,
                stock_tolerated_missing_setgroups=False,terminal_monotonic_ns=mono+400_000,
                terminal_wall_time_ns=wall+400_000),
            row('namespace_setup_failed',offset=500_000,errno=13)]
    millis = (wall+400_000)//1_000_000
    record = {'MESSAGE':f'audit: type=1400 audit({millis//1000}.{millis%1000:03d}:128): '
              f'apparmor="DENIED" operation="capable" class="cap" '
              f'profile="unprivileged_userns" pid={pid} comm="python3.12" '
              'capability=21 capname="sys_admin"', '_BOOT_ID':boot.replace('-',''),
              '_TRANSPORT':'kernel','__REALTIME_TIMESTAMP':str((wall+500_000)//1000),
              '__MONOTONIC_TIMESTAMP':str((mono+500_000)//1000)}
    return capture, rows, record, {'path':python,'stat':identity}, boot, mono-2_000_000, mono+1_000_000


class UsernsProfileTests(unittest.TestCase):
    def physical_metadata_fixture(self,module,directory):
        """Original-format metadata fixtures, never a real denial or policy grant."""
        capture,rows,record,identity,boot,job_start,_=coarse_denial_fixture()
        for key in ('started_wall_time_ns','terminal_wall_time_ns'):
            capture[key]-=20_000_000
        for key in ('started_monotonic_ns','terminal_monotonic_ns','cleanup_deadline_ns'):
            capture[key]-=20_000_000
        for row in rows:
            for key in ('wall_time_ns','terminal_wall_time_ns','monotonic_ns','terminal_monotonic_ns'):
                if key in row:row[key]-=20_000_000
            for key in ('audit_coarse_before','audit_coarse_after'):
                if key in row:
                    for clock in ('value_ns','started_monotonic_ns','terminal_monotonic_ns'):
                        row[key][clock]-=20_000_000
        for key in ('__REALTIME_TIMESTAMP','__MONOTONIC_TIMESTAMP'):
            record[key]=str(int(record[key])-20_000)
        audit=record['MESSAGE'].split('audit(')[1].split(':')[0]
        millis=int(audit.split('.')[0])*1000+int(audit.split('.')[1])-20
        record['MESSAGE']=record['MESSAGE'].replace(audit,f'{millis//1000}.{millis%1000:03d}')
        job_start-=20_000_000
        capture['owner'].update(ppid=os.getpid(),pgid=capture['owner']['pid'])
        python=identity['path'];capture['argv']=[python,'-I','-B',str(Path(module._diagnostic.__file__).resolve()),
            '--worker','--start-gate-fd','5']
        query=copy.deepcopy(capture);query['returncode']=0
        query['owner']['pid']+=1;query['owner']['pgid']=query['owner']['pid']
        query['started_wall_time_ns']=capture['terminal_wall_time_ns']+1_000_000
        query['terminal_wall_time_ns']=capture['terminal_wall_time_ns']+2_000_000
        command=['/usr/bin/journalctl','--dmesg','--since',
            '@'+str(capture['started_wall_time_ns']//1_000_000_000-1),'--until',
            '@'+str(capture['terminal_wall_time_ns']//1_000_000_000+1),'--no-pager','--output=json',
            '--lines=32','--case-sensitive=no','--grep=apparmor=.*DENIED.*(userns|unshare|capable)']
        query['argv']=[*module._diagnostic._gated_execv_argv(python,command),'--start-gate-fd','5']
        source=Path(directory)/'original-metadata-fixture';(source/'kernel-query').mkdir(parents=True)
        for rel,value in [('capture.json',capture),('kernel-query/capture.json',query),
                          ('kernel-denial.json',{'records':[{'original_journal_record':record}]})]:
            (source/rel).write_text(json.dumps(value)+'\n')
        (source/'stdout.raw').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (source/'kernel-query/stdout.raw').write_text(json.dumps(record)+'\n')
        return {'diagnostic_dir':source,'diagnostic':capture,'python':python,
                'output_dir':Path(directory)/'profile-fixture','job_start_ns':job_start,
                'absolute_deadline_ns':time.monotonic_ns()+60_000_000_000}

    def policy_command_fixture(self,module,mode='success'):
        state={'name':'vast-ci-userns-'+'a'*32,'present':False,'commands':[]}
        def capture(argv,path,deadline,**kwargs):
            command=argv[argv.index('/usr/bin/sudo'):]
            state['commands'].append(command);path=Path(path);path.mkdir()
            rc=0;completed=True
            if '/usr/bin/cat' in command:
                present=state['present'] or (mode=='collision' and len(state['commands'])==1)
                raw=((state['name']+' (unconfined)\n') if present else 'other (enforce)\n').encode()
            else:
                fdpath=command[-1];self.assertEqual(Path(fdpath).read_bytes(),
                    module.profile_bytes_v1(state['name'],str(Path(sys.executable).resolve())))
                if '--add' in command:
                    state['present']=mode!='load_nonzero'
                    rc=1 if mode in ('load_nonzero','load_nonzero_present') else 0
                    completed=mode!='load_capture_failure'
                elif '--remove' in command:
                    rc=1 if mode=='remove_nonzero' else 0
                    if rc==0:state['present']=False
                else:self.fail('unexpected policy command')
                raw=b''
            (path/'stdout.raw').write_bytes(raw);(path/'stderr.raw').write_bytes(b'')
            value={'returncode':rc,'capture_completed':completed,'timed_out':False,
                   'failure':None if completed else 'explicit original capture fixture failure',
                   'local_metadata_fixture_only':True}
            (path/'capture.json').write_text(json.dumps(value)+'\n')
            if '--add' in command and mode=='load_persistence_failure':
                raise OSError('original add terminal persistence fixture')
            return value
        return state,capture

    def test_held_lifecycle_uses_original_fixed_add_and_owned_remove_with_actual_file_bytes(self):
        module=helper();state,capture=self.policy_command_fixture(module)
        with tempfile.TemporaryDirectory() as directory:
            kwargs=self.physical_metadata_fixture(module,directory)
            before=set(Path('/proc/self/fd').iterdir())
            with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                 mock.patch.object(module._diagnostic,'capture_original_child',capture):
                with module.held_ci_userns_profile_v1(**kwargs) as active:
                    self.assertEqual(active['expected_profile'],state['name']+' (unconfined)')
                    self.assertTrue(active['report']['load_verified'])
                    self.assertLess(active['suite_deadline_ns'],kwargs['absolute_deadline_ns'])
            report=json.loads((kwargs['output_dir']/'profile-lifecycle.json').read_bytes())
            self.assertEqual(report['status'],'completed');self.assertTrue(report['unload_verified'])
            self.assertTrue(report['held_fds_released']);self.assertFalse(state['present'])
            self.assertEqual(sum('--add' in cmd for cmd in state['commands']),1)
            self.assertEqual(sum('--remove' in cmd for cmd in state['commands']),1)
            self.assertEqual(before,set(Path('/proc/self/fd').iterdir()))

    def test_collision_and_load_nonzero_never_execute_or_remove_a_foreign_profile(self):
        module=helper()
        for mode in ('collision','load_nonzero'):
            state,capture=self.policy_command_fixture(module,mode)
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                kwargs=self.physical_metadata_fixture(module,directory)
                with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                     mock.patch.object(module._diagnostic,'capture_original_child',capture):
                    with self.assertRaises(RuntimeError):
                        with module.held_ci_userns_profile_v1(**kwargs):self.fail('unverified policy yielded')
                self.assertFalse(any('--remove' in cmd for cmd in state['commands']))
                if mode=='collision':self.assertFalse(any('--add' in cmd for cmd in state['commands']))

    def test_failed_capture_with_original_zero_and_observed_owned_profile_still_cleans(self):
        module=helper();state,capture=self.policy_command_fixture(module,'load_capture_failure')
        with tempfile.TemporaryDirectory() as directory:
            kwargs=self.physical_metadata_fixture(module,directory)
            with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                 mock.patch.object(module._diagnostic,'capture_original_child',capture):
                with self.assertRaisesRegex(RuntimeError,'load/enforcement'):
                    with module.held_ci_userns_profile_v1(**kwargs):self.fail('failed capture yielded')
            report=json.loads((kwargs['output_dir']/'profile-lifecycle.json').read_bytes())
            self.assertEqual(report['status'],'failed');self.assertFalse(report['load_verified'])
            self.assertTrue(report['unload_verified']);self.assertFalse(state['present'])

    def test_nonzero_or_persistence_failure_with_proved_owned_effect_never_runs_suite_and_cleans(self):
        module=helper()
        for mode in ('load_nonzero_present','load_persistence_failure'):
            state,capture=self.policy_command_fixture(module,mode)
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                kwargs=self.physical_metadata_fixture(module,directory)
                with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                     mock.patch.object(module._diagnostic,'capture_original_child',capture):
                    with self.assertRaises((RuntimeError,OSError)):
                        with module.held_ci_userns_profile_v1(**kwargs):self.fail('failed add ran suite')
                report=json.loads((kwargs['output_dir']/'profile-lifecycle.json').read_bytes())
                self.assertEqual(report['status'],'failed');self.assertFalse(report['load_verified'])
                self.assertTrue(report['unload_verified']);self.assertFalse(state['present'])

    def test_original_body_error_survives_unload_and_receipt_failure_with_fds_retired(self):
        module=helper();state,capture=self.policy_command_fixture(module,'remove_nonzero')
        with tempfile.TemporaryDirectory() as directory:
            kwargs=self.physical_metadata_fixture(module,directory);before=set(Path('/proc/self/fd').iterdir())
            saved=module._save
            def save(path,*args):
                if path.name=='profile-lifecycle.json':raise OSError('original lifecycle persistence fixture')
                return saved(path,*args)
            with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                 mock.patch.object(module._diagnostic,'capture_original_child',capture),mock.patch.object(module,'_save',save):
                with self.assertRaisesRegex(ValueError,'primary full-suite failure') as caught:
                    with module.held_ci_userns_profile_v1(**kwargs):raise ValueError('primary full-suite failure')
            self.assertTrue(caught.exception.__notes__)
            self.assertEqual(before,set(Path('/proc/self/fd').iterdir()))

    def test_physically_foreign_kernel_query_command_cannot_activate_profile(self):
        module=helper();state,capture=self.policy_command_fixture(module)
        with tempfile.TemporaryDirectory() as directory:
            kwargs=self.physical_metadata_fixture(module,directory)
            path=kwargs['diagnostic_dir']/'kernel-query/capture.json';query=json.loads(path.read_bytes())
            query['argv'][query['argv'].index('/usr/bin/journalctl')]='/usr/bin/foreign'
            path.write_text(json.dumps(query))
            with mock.patch.object(module._diagnostic,'capture_original_child',capture):
                with self.assertRaisesRegex(RuntimeError,'kernel query argv'):
                    with module.held_ci_userns_profile_v1(**kwargs):self.fail('foreign query yielded')
            self.assertEqual(state['commands'],[])

    def test_receipt_last_cannot_escape_original_unload_cleanup_deadline(self):
        import types
        module=helper();state,capture=self.policy_command_fixture(module)
        with tempfile.TemporaryDirectory() as directory:
            kwargs=self.physical_metadata_fixture(module,directory)
            clock={'late':None};real_time=module.time
            module.time=types.SimpleNamespace(monotonic_ns=lambda:
                clock['late'] if clock['late'] is not None else real_time.monotonic_ns(),
                time_ns=real_time.time_ns)
            save=module._save
            def crossing_save(path,value,maximum):
                save(path,value,maximum)
                if path.name=='profile-lifecycle.json':
                    clock['late']=value['unload_phase']['cleanup_deadline_ns']+1
            with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),\
                 mock.patch.object(module._diagnostic,'capture_original_child',capture),\
                 mock.patch.object(module,'_save',crossing_save):
                with self.assertRaisesRegex(RuntimeError,'receipt-last crossed'):
                    with module.held_ci_userns_profile_v1(**kwargs) as active:
                        report=active['report']
            self.assertEqual(report['status'],'failed');self.assertTrue(report['late_finalization'])
            self.assertTrue(report['held_fds_released']);self.assertFalse(state['present'])
            self.assertTrue((kwargs['output_dir']/'late-profile.failure').is_file())

    def test_post_verify_budget_guard_never_dispatches_a_root_command_past_original_deadline(self):
        import subprocess
        import types
        for phase in ('slow_verify_inventory','preceding_inventory_parser','post_suite_verify'):
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as directory:
                module=helper();state,capture=self.policy_command_fixture(module)
                kwargs=self.physical_metadata_fixture(module,directory)
                clock={'late':None,'advanced':False};real_time=module.time
                module.time=types.SimpleNamespace(monotonic_ns=lambda:
                    clock['late'] if clock['late'] is not None else real_time.monotonic_ns(),
                    time_ns=real_time.time_ns)
                def consume_original_budget(deadline,remaining):
                    original=subprocess.run([sys.executable,'-I','-B','-c',
                        'import time;time.sleep(.005)'],capture_output=True,timeout=1)
                    self.assertEqual(original.returncode,0)
                    self.assertEqual((original.stdout,original.stderr),(b'',b''))
                    clock['late']=deadline-remaining+1;clock['advanced']=True
                verify=module.verify_held_v1
                def slow_verify(path,fd,identity,deadline_ns=None):
                    verify(path,fd,identity,deadline_ns)
                    if phase=='slow_verify_inventory' and Path(path).name=='owned.profile' and                        deadline_ns<kwargs['absolute_deadline_ns'] and not clock['advanced']:
                        consume_original_budget(deadline_ns,3_000_000_000)
                def preceding_inventory(argv,path,deadline,**options):
                    value=capture(argv,path,deadline,**options)
                    if phase=='preceding_inventory_parser' and len(state['commands'])==1:
                        # The first inventory uses the20s work deadline; the parser
                        # uses the original30s work+cleanup deadline.
                        consume_original_budget(deadline+10_000_000_000,21_000_000_000)
                    return value
                before=set(Path('/proc/self/fd').iterdir())
                with mock.patch.object(module.uuid,'uuid4',return_value=type('Uuid',(),{'hex':'a'*32})()),                     mock.patch.object(module._diagnostic,'capture_original_child',preceding_inventory),                     mock.patch.object(module,'verify_held_v1',slow_verify):
                    with self.assertRaisesRegex(RuntimeError,'self-timeout.*closing reserve'):
                        with module.held_ci_userns_profile_v1(**kwargs) as active:
                            self.assertEqual(phase,'post_suite_verify','insufficient load budget yielded suite')
                            consume_original_budget(kwargs['absolute_deadline_ns'],21_000_000_000)
                self.assertTrue(clock['advanced']);self.assertEqual(before,set(Path('/proc/self/fd').iterdir()))
                if phase=='slow_verify_inventory':self.assertEqual(state['commands'],[])
                elif phase=='preceding_inventory_parser':self.assertFalse(any('--add' in c for c in state['commands']))
                else:
                    self.assertEqual(sum('--add' in c for c in state['commands']),1)
                    self.assertFalse(any('--remove' in c for c in state['commands']))
                    self.assertTrue(state['present'],'unproved removal cannot be reported absent')
                report=json.loads((kwargs['output_dir']/'profile-lifecycle.json').read_bytes())
                self.assertEqual(report['status'],'failed');self.assertTrue(report['held_fds_released'])

    def test_privileged_minimum_budget_accepts_only_two_original_fixed_command_shapes(self):
        module=helper();fdpath=f'/proc/{os.getpid()}/fd/7'
        for action in ('--add','--remove'):
            self.assertEqual(module.fixed_root_timeout_budget_v1(module.parser_command_v1(action,fdpath)),21_000_000_000)
        inventory=['/usr/bin/sudo','-n','--','/usr/bin/timeout','--signal=TERM','--kill-after=1s','1s',
                   '/usr/bin/cat',module.KERNEL_PROFILES]
        self.assertEqual(module.fixed_root_timeout_budget_v1(inventory),3_000_000_000)
        for command in [inventory[:-1]+['/etc/shadow'],['/usr/bin/sudo','-n','--','arbitrary'],
                        module.parser_command_v1('--add',fdpath)[:-1]+['/tmp/profile']]:
            with self.assertRaisesRegex(RuntimeError,'unknown privileged command|parser source is not this original controller held FD'):
                module.fixed_root_timeout_budget_v1(command)

    def test_actual_gate_handoff_withholds_original_child_if_owner_acquisition_consumes_budget(self):
        import types
        module=helper();diagnostic=module._diagnostic;real_time=diagnostic.time
        start=real_time.monotonic_ns();deadline=start+30_000_000_000
        clock={'calls':0}
        def now():
            clock['calls']+=1
            return start if clock['calls']==1 else deadline-21_000_000_000+1
        diagnostic.time=types.SimpleNamespace(monotonic_ns=now,time_ns=real_time.time_ns,sleep=real_time.sleep)
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'payload-started'
            command=[sys.executable,'-I','-B','-c',
                'from pathlib import Path;Path('+repr(str(marker))+').write_text("started")']
            before=set(Path('/proc/self/fd').iterdir())
            result=diagnostic.capture_original_child(diagnostic._gated_execv_argv(sys.executable,command),
                Path(directory)/'capture',deadline,execution_s=20,cleanup_s=10,start_gate=True,
                raw_limit=8192,report_limit=8192,minimum_start_budget_ns=21_000_000_000)
            self.assertFalse(result['original_start_gate_released']);self.assertFalse(marker.exists())
            self.assertFalse(result['capture_completed']);self.assertIn('gate release',result['failure'])
            self.assertIsNotNone(result['owner']);self.assertTrue(result['original_group_absent'])
            self.assertEqual(result['eof'],{'stdout':True,'stderr':True})
            self.assertIsNotNone(result['returncode']);self.assertEqual(before,set(Path('/proc/self/fd').iterdir()))

    def test_original_shape_joins_only_exact_interpreter_pid_boot_operation_and_time(self):
        module = helper()
        args = denial_fixture()
        proof = module.join_original_userns_denial_v1(*args,expected_clock_contract_version=1)
        self.assertEqual(proof['pid'], os.getpid())
        self.assertEqual(proof['failed_operation'], 'open:/proc/self/setgroups')
        self.assertEqual(proof['denied_capability'], 'sys_admin')
        self.assertEqual(proof['denied_profile'], 'unprivileged_userns')

    def test_absent_foreign_ambiguous_or_generic_denial_is_not_a_profile_grant(self):
        module = helper()
        args = denial_fixture()
        variants = []
        for key,value in [('_BOOT_ID','f'*32),('_TRANSPORT','stdout'),
                          ('__REALTIME_TIMESTAMP','0'),('__MONOTONIC_TIMESTAMP','0')]:
            bad=copy.deepcopy(args);bad[2][key]=value;variants.append(bad)
        for old,new in [('pid='+str(os.getpid()),'pid='+str(os.getpid()+1)),
                        ('"DENIED"','"ALLOWED"'),('"sys_admin"','"net_admin"'),
                        ('"unprivileged_userns"','"foreign"')]:
            bad=copy.deepcopy(args);bad[2]['MESSAGE']=bad[2]['MESSAGE'].replace(old,new);variants.append(bad)
        bad=copy.deepcopy(args);bad[1].append(copy.deepcopy(bad[1][4]));variants.append(bad)
        bad=copy.deepcopy(args);bad[1][4]['errno']=2;variants.append(bad)
        bad=copy.deepcopy(args);bad[1][2]['flags']=0;variants.append(bad)
        bad=copy.deepcopy(args);bad[1][0]['label']['value']='foreign (enforce)';variants.append(bad)
        bad=copy.deepcopy(args);bad[0]['owner']['executable_stat']['st_ino']+=1;variants.append(bad)
        bad=copy.deepcopy(args);bad[0]['capture_completed']=False;variants.append(bad)
        bad=copy.deepcopy(args);bad[0]['returncode']=0;variants.append(bad)
        bad=list(copy.deepcopy(args));bad[6]=bad[0]['cleanup_deadline_ns']+1;variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad[2]):
                with self.assertRaises(RuntimeError): module.join_original_userns_denial_v1(*bad,expected_clock_contract_version=1)

    def test_profile_has_only_exact_attachment_and_userns_permission(self):
        module=helper()
        path='/opt/hostedtoolcache/Python/3.12.3/x64/bin/python3.12'
        raw=module.profile_bytes_v1('vast-ci-userns-'+'a'*32,path)
        self.assertEqual(raw,('abi <abi/4.0>,\nprofile vast-ci-userns-'+ 'a'*32 +
            ' '+path+' flags=(unconfined) {\n  userns,\n}\n').encode())
        for bad in ['/tmp/with space/python','/tmp/*/python','/tmp/../python',path+'\nother','relative']:
            with self.subTest(path=bad):
                with self.assertRaises(RuntimeError):module.profile_bytes_v1('vast-ci-userns-'+'a'*32,bad)
        with self.assertRaises(RuntimeError):module.profile_bytes_v1('unprivileged_userns',path)

    def test_only_add_remove_and_root_owned_timeout_are_valid_command_shapes(self):
        module=helper()
        fdpath=f'/proc/{os.getpid()}/fd/7'
        for action in ('--add','--remove'):
            argv=module.parser_command_v1(action,fdpath)
            self.assertEqual(argv[:7],['/usr/bin/sudo','-n','--','/usr/bin/timeout',
                '--signal=TERM','--kill-after=1s','19s'])
            self.assertEqual(argv[7:],['/usr/sbin/apparmor_parser',action,'--skip-cache','--jobs=0','--',fdpath])
            self.assertNotIn('--replace',argv)
        for action in ('--replace','--purge-cache','--add --replace'):
            with self.assertRaises(RuntimeError):module.parser_command_v1(action,fdpath)
        for path in ('/tmp/profile','/proc/other/fd/7','/proc/1/fd/7',fdpath+';bad'):
            with self.assertRaises(RuntimeError):module.parser_command_v1('--add',path)

    def test_kernel_inventory_requires_exact_named_unconfined_profile(self):
        module=helper();name='vast-ci-userns-'+'a'*32
        self.assertFalse(module.kernel_profile_present_v1(b'other (enforce)\n',name))
        self.assertTrue(module.kernel_profile_present_v1((name+' (unconfined)\n').encode(),name))
        for raw in [(name+' (enforce)\n').encode(),(name+' (unconfined)\n') .encode()*2,
                    b'partial-without-newline',b'\xff\n']:
            with self.assertRaises(RuntimeError):module.kernel_profile_present_v1(raw,name)

    def test_real_held_profile_detects_named_substitution_and_same_size_mutation(self):
        module=helper()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'owned.profile';path.write_bytes(b'original')
            fd,identity=module.hold_regular_v1(path,512,time.monotonic_ns()+5_000_000_000)
            try:
                module.verify_held_v1(path,fd,identity)
                path.write_bytes(b'changed!')
                with self.assertRaises(RuntimeError):module.verify_held_v1(path,fd,identity)
            finally:os.close(fd)
            path.write_bytes(b'original')
            fd,identity=module.hold_regular_v1(path,512,time.monotonic_ns()+5_000_000_000)
            try:
                path.unlink();path.write_bytes(b'original')
                with self.assertRaises(RuntimeError):module.verify_held_v1(path,fd,identity)
            finally:os.close(fd)

    def test_real_single_link_and_bounded_source_predicates_are_not_waived(self):
        module=helper()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source';path.write_bytes(b'ab')
            with self.assertRaises(RuntimeError):module.hold_regular_v1(path,1,10**30)
            os.link(path,Path(directory)/'second')
            with self.assertRaises(RuntimeError):module.hold_regular_v1(path,8,10**30)
            with self.assertRaises(RuntimeError):module.hold_regular_v1(Path(directory),8,10**30)

    def test_real_fresh_child_rejects_wrong_profile_before_discovery(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            code=('import importlib.util,os,sys;from pathlib import Path;'
                  's=importlib.util.spec_from_file_location("ci",sys.argv[1]);'
                  'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                  'fds=[os.open("/dev/null",os.O_RDWR) for _ in range(3)];'
                  'raise SystemExit(m.suite_child(Path(sys.argv[2]),*fds,'
                  'expected_profile="vast-ci-userns-'+ 'a'*32 +' (unconfined)"))')
            original=subprocess.run([sys.executable,'-I','-B','-c',code,
                str(ROOT/'scripts/run_ci_checks.py'),str(output)],capture_output=True,timeout=5)
            self.assertEqual(original.returncode,1)
            report=json.loads((output/'unittest-child.report.json').read_bytes())
            self.assertIn('AppArmor label',report['child_failure'])
            self.assertNotIn('discovered_ids',report)

    def test_capture_retains_permission_failure_and_original_eof_without_success(self):
        module=helper();helper_capture=module._diagnostic
        with tempfile.TemporaryDirectory() as directory:
            # Ordinary owned child self-terminates. No root process is signalled.
            command=[sys.executable,'-I','-B','-c','import time;time.sleep(.08)']
            with mock.patch.object(helper_capture.os,'killpg',side_effect=PermissionError(1,'explicit signal fixture')):
                result=helper_capture.capture_original_child(command,Path(directory)/'out',10**30,
                    execution_s=.02,cleanup_s=.4)
            self.assertFalse(result['capture_completed'])
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['returncode'],0)
            self.assertTrue(result['original_group_absent'])
            self.assertEqual(result['eof'],{'stdout':True,'stderr':True})
            self.assertTrue(result['signal_failures'])

    def test_real_root_timeout_shape_is_tested_without_sudo_or_policy(self):
        module=helper()
        command=['/usr/bin/timeout','--signal=TERM','--kill-after=.05s','.05s',
                 sys.executable,'-I','-B','-c','import time;time.sleep(5)']
        with tempfile.TemporaryDirectory() as directory:
            result=module._diagnostic.capture_original_child(
                module._diagnostic._gated_execv_argv(sys.executable,command),Path(directory)/'out',
                10**30,execution_s=1,cleanup_s=1,start_gate=True,raw_limit=8192)
            self.assertTrue(result['capture_completed'],result)
            self.assertEqual(result['returncode'],124)
            self.assertTrue(result['original_group_absent'])

    def test_phase_capture_smaller_limit_preserves_overflow_prefix_and_failure(self):
        module=helper()
        with tempfile.TemporaryDirectory() as directory:
            result=module._diagnostic.capture_original_child([sys.executable,'-I','-B','-c',
                'import os;os.write(1,b"x"*16384)'],Path(directory)/'out',10**30,
                execution_s=1,cleanup_s=1,raw_limit=8192)
            self.assertFalse(result['capture_completed']);self.assertTrue(result['capture_exceeded'])
            self.assertLessEqual(sum((Path(directory)/'out'/p).stat().st_size for p in
                                     ('stdout.raw','stderr.raw')),8192)
        with self.assertRaises(ValueError):
            module._diagnostic.capture_original_child([],Path('/unused'),10**30,raw_limit=16385)


def coarse_denial_fixture():
    """Synthetic v2 clocks with an8ms coarse lag; no real policy authority."""
    args=list(denial_fixture());capture,rows,record,_,boot,_,_=args
    start,failed=rows[1],rows[4]
    audit_ns=(start['wall_time_ns']//1_000_000-8)*1_000_000
    audit=record['MESSAGE'].split('audit(')[1].split(':')[0]
    record['MESSAGE']=record['MESSAGE'].replace(audit,
        f'{audit_ns//1_000_000_000}.{audit_ns//1_000_000%1000:03d}')
    rows[0]['namespace_clock_contract_version']=2
    def sample(phase,value,start_ns,end_ns):
        return {'available':True,'clock_id':5,'clock_name':'CLOCK_REALTIME_COARSE',
                'phase':phase,'value_ns':value,'original_pid':capture['owner']['pid'],
                'boot_id':boot,'started_monotonic_ns':start_ns,'terminal_monotonic_ns':end_ns}
    before=sample('before_unshare',audit_ns+123456,
                  start['monotonic_ns']-80000,start['monotonic_ns']-70000)
    start['audit_coarse_before']=before
    rows[2]['audit_coarse_before']=copy.deepcopy(before)
    failed['audit_coarse_after']=sample('after_failed_setgroups_open',audit_ns+456789,
                  failed['terminal_monotonic_ns']+50000,failed['terminal_monotonic_ns']+60000)
    capture['terminal_monotonic_ns']=failed['terminal_monotonic_ns']+400000
    return tuple(args)


class AuditClockTests(unittest.TestCase):
    def test_coarse_lag_beyond_original_fine_tolerance_joins_actual_clock_bins(self):
        module=helper();args=coarse_denial_fixture()
        proof=module.join_original_userns_denial_v1(*args)
        self.assertGreater(args[1][1]['wall_time_ns']-proof['audit_wall_time_ns'],2000000)
        self.assertEqual(proof['audit_clock_basis'],'CLOCK_REALTIME_COARSE')
        self.assertEqual(proof['audit_clock_bracket_ns'],[proof['audit_wall_time_ns']]*2)

    def test_equal_and_inclusive_boundary_bins_accept_but_adjacent_bins_fail(self):
        module=helper()
        for offset in (0,1000000,-1000000,2000000):
            args=list(coarse_denial_fixture());rows=args[1];record=args[2]
            first=rows[1]['audit_coarse_before']['value_ns']//1000000*1000000
            rows[4]['audit_coarse_after']['value_ns']=first+1999999
            audit=record['MESSAGE'].split('audit(')[1].split(':')[0];value=first+offset
            record['MESSAGE']=record['MESSAGE'].replace(audit,
                f'{value//1000000000}.{value//1000000%1000:03d}')
            with self.subTest(offset=offset):
                if offset in (0,1000000):module.join_original_userns_denial_v1(*args)
                else:
                    with self.assertRaises(RuntimeError):module.join_original_userns_denial_v1(*args)

    def test_missing_and_malformed_new_clock_evidence_cannot_downgrade(self):
        module=helper()
        def remove_all(args):
            args[1][0].pop('namespace_clock_contract_version')
            for row in args[1]:
                row.pop('audit_coarse_before',None);row.pop('audit_coarse_after',None)
        cases={'all_removed':remove_all,
            'missing_after':lambda a:a[1][4].pop('audit_coarse_after'),
            'unknown_version':lambda a:a[1][0].update(namespace_clock_contract_version=3),
            'boolean_version':lambda a:a[1][0].update(namespace_clock_contract_version=True),
            'unavailable':lambda a:a[1][4]['audit_coarse_after'].update(available=False),
            'wrong_clock':lambda a:a[1][4]['audit_coarse_after'].update(clock_id=0),
            'boolean_clock':lambda a:a[1][4]['audit_coarse_after'].update(clock_id=True),
            'wrong_name':lambda a:a[1][4]['audit_coarse_after'].update(clock_name='CLOCK_REALTIME'),
            'boolean_value':lambda a:a[1][4]['audit_coarse_after'].update(value_ns=True),
            'negative_value':lambda a:a[1][4]['audit_coarse_after'].update(value_ns=-1),
            'foreign_pid':lambda a:a[1][4]['audit_coarse_after'].update(original_pid=os.getpid()+1),
            'foreign_boot':lambda a:a[1][4]['audit_coarse_after'].update(boot_id='foreign'),
            'wrong_phase':lambda a:a[1][4]['audit_coarse_after'].update(phase='before_unshare'),
            'reversed_value':lambda a:a[1][4]['audit_coarse_after'].update(value_ns=a[1][1]['audit_coarse_before']['value_ns']-1),
            'late_before':lambda a:a[1][1]['audit_coarse_before'].update(terminal_monotonic_ns=a[1][1]['monotonic_ns']+1),
            'early_after':lambda a:a[1][4]['audit_coarse_after'].update(started_monotonic_ns=a[1][4]['terminal_monotonic_ns']-1),
            'reversed_sample':lambda a:a[1][4]['audit_coarse_after'].update(terminal_monotonic_ns=a[1][4]['audit_coarse_after']['started_monotonic_ns']-1),
            'out_of_capture':lambda a:a[0].update(terminal_monotonic_ns=a[1][4]['audit_coarse_after']['terminal_monotonic_ns']-1),
            'future_capture':lambda a:a[0].update(terminal_monotonic_ns=a[-1]+1)}
        for name,mutate in cases.items():
            args=list(coarse_denial_fixture());mutate(args)
            if 'audit_coarse_before' in args[1][1]:
                args[1][2]['audit_coarse_before']=copy.deepcopy(args[1][1]['audit_coarse_before'])
            with self.subTest(case=name),self.assertRaises(RuntimeError):
                module.join_original_userns_denial_v1(*args)

    def test_explicit_legacy_retains_original_strict_rejection_and_cannot_take_v2(self):
        module=helper();legacy=denial_fixture()
        proof=module.join_original_userns_denial_v1(*legacy,expected_clock_contract_version=1)
        self.assertEqual(proof['wall_clock_quantization_allowance_ns'],2000000)
        current=list(coarse_denial_fixture())
        with self.assertRaises(RuntimeError):
            module.join_original_userns_denial_v1(*current,expected_clock_contract_version=1)
        current[1][0].pop('namespace_clock_contract_version')
        for row in current[1]:row.pop('audit_coarse_before',None);row.pop('audit_coarse_after',None)
        with self.assertRaisesRegex(RuntimeError,'clock interval'):
            module.join_original_userns_denial_v1(*current,expected_clock_contract_version=1)
        with self.assertRaises(RuntimeError):module.join_original_userns_denial_v1(*legacy)

    def test_original_B_clock_operands_stay_rejected_in_explicit_legacy_context(self):
        module=helper();args=list(denial_fixture());capture,rows,record=args[:3]
        # Synthetic current ownership with the immutable original B relative clock operands.
        audit=record['MESSAGE'].split('audit(')[1].split(':')[0]
        stamp=(int(audit.split('.')[0])*1000+int(audit.split('.')[1]))*1000000
        capture.update(started_wall_time_ns=stamp-1000000,terminal_wall_time_ns=stamp+5000000)
        for row in rows[1:3]:row['wall_time_ns']=stamp+2187040
        for row in rows[3:5]:row['wall_time_ns']=stamp+2286847
        rows[4]['terminal_wall_time_ns']=stamp+2338743
        record['__REALTIME_TIMESTAMP']=str((stamp+2640000)//1000)
        self.assertEqual(rows[1]['wall_time_ns']-2000000-stamp,187040)
        with self.assertRaisesRegex(RuntimeError,'clock interval'):
            module.join_original_userns_denial_v1(*args,expected_clock_contract_version=1)

    def test_unknown_expected_clock_contract_is_never_inferred_from_record(self):
        module=helper()
        for version in (0,3,True,'2',None):
            with self.subTest(version=version),self.assertRaises(RuntimeError):
                module.join_original_userns_denial_v1(*coarse_denial_fixture(),
                    expected_clock_contract_version=version)

    def test_original_journal_and_owner_predicates_still_reject_v2(self):
        module=helper()
        for mutate in (lambda a:a[2].update(__REALTIME_TIMESTAMP=str((a[0]['terminal_wall_time_ns']+1_000_000)//1000)),
                       lambda a:a[2].update(__MONOTONIC_TIMESTAMP=str((a[1][4]['terminal_monotonic_ns']+3_000_000)//1000)),
                       lambda a:a[0]['owner'].update(boot_id='foreign')):
            args=list(coarse_denial_fixture());mutate(args)
            with self.assertRaises(RuntimeError):module.join_original_userns_denial_v1(*args)

    def test_live_missing_contract_fails_before_any_profile_command(self):
        module=helper();fixtures=UsernsProfileTests();state,capture=fixtures.policy_command_fixture(module)
        with tempfile.TemporaryDirectory() as directory:
            kwargs=fixtures.physical_metadata_fixture(module,directory)
            path=kwargs['diagnostic_dir']/'stdout.raw';rows=[json.loads(line) for line in path.read_text().splitlines()]
            for row in rows:
                row.pop('namespace_clock_contract_version',None)
                row.pop('audit_coarse_before',None);row.pop('audit_coarse_after',None)
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            # Make the stripped record pass legacy timing, so this tests the live version gate.
            query_raw=kwargs['diagnostic_dir']/'kernel-query/stdout.raw'
            record=json.loads(query_raw.read_bytes())
            old=record['MESSAGE'].split('audit(')[1].split(':')[0]
            fine=rows[4]['terminal_wall_time_ns']//1000000
            record['MESSAGE']=record['MESSAGE'].replace(old,f'{fine//1000}.{fine%1000:03d}')
            query_raw.write_text(json.dumps(record)+'\n')
            (kwargs['diagnostic_dir']/'kernel-denial.json').write_text(json.dumps(
                {'records':[{'original_journal_record':record}]})+'\n')
            original_capture=json.loads((kwargs['diagnostic_dir']/'capture.json').read_bytes())
            identity={'path':kwargs['python'],'stat':original_capture['owner']['executable_stat']}
            module.join_original_userns_denial_v1(original_capture,rows,record,identity,
                original_capture['owner']['boot_id'],kwargs['job_start_ns'],time.monotonic_ns(),
                expected_clock_contract_version=1)
            with mock.patch.object(module._diagnostic,'capture_original_child',capture):
                with self.assertRaises(RuntimeError):
                    with module.held_ci_userns_profile_v1(**kwargs):self.fail('missing contract yielded')
            self.assertEqual(state['commands'],[])


if __name__=='__main__': unittest.main()
