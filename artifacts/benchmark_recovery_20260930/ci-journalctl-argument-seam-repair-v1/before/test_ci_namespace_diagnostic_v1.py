"""Local instrumentation/ordinary-child fixtures; never actual namespace setup."""
import importlib.util
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class NamespaceDiagnosticTests(unittest.TestCase):
    @staticmethod
    def ordinary_child(code):
        import sys
        gate = ('import os,sys;position=sys.argv.index("--start-gate-fd");'
                'fd=int(sys.argv[position+1]);assert os.read(fd,1)==b"1";os.close(fd);')
        return [sys.executable, '-I', '-B', '-c', gate + code]

    def helper(self):
        spec = importlib.util.spec_from_file_location('ci_namespace', ROOT/'scripts/ci_namespace_diagnostic_v1.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_namespace_denial_candidate_retains_original_pid_capability_and_case(self):
        helper = self.helper()
        positive = (
            'apparmor="DENIED" operation="userns_create" pid=123 comm="python3.12"',
            'apparmor="DENIED" operation="capable" info="Userns policy restriction" capname="sys_admin" pid=123',
        )
        for message in positive:
            with self.subTest(message=message):
                self.assertTrue(helper._relevant_original_denial(message, 123))
        for message in (
            positive[0].replace('pid=123 ', 'pid=1234 '),
            positive[1].replace('capname="sys_admin"', 'capname="net_admin"'),
            positive[0].replace('"DENIED"', '"ALLOWED"'),
            'plain text userns pid=123',
            'apparmor="DENIED" operation="open" pid=123 name="unrelated"',
        ):
            with self.subTest(message=message):
                self.assertFalse(helper._relevant_original_denial(message, 123))

    def test_real_gated_exec_keeps_original_pid_and_truthful_initial_owner(self):
        helper = self.helper()
        import json, sys
        command = [sys.executable, '-I', '-B', '-c', 'import os,json;print(json.dumps({"pid":os.getpid()}))']
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'out'
            result = helper.capture_original_child(helper._gated_execv_argv(sys.executable, command),
                output, 10**30, execution_s=1, cleanup_s=1, start_gate=True)
            self.assertTrue(result['capture_completed'])
            self.assertEqual(result['returncode'], 0)
            self.assertEqual(json.loads((output/'stdout.raw').read_bytes())['pid'], result['owner']['pid'])
            self.assertEqual(result['owner']['executable_realpath'], str(Path(sys.executable).resolve(strict=True)))
            self.assertTrue(result['original_group_absent'])
            self.assertEqual(result['eof'], {'stdout': True, 'stderr': True})

    def test_kernel_query_explicitly_captures_capability_denials_without_claiming_cause(self):
        helper = self.helper()
        import json, time
        calls = []
        def capture(argv, output, deadline, **kwargs):
            output = Path(output); output.mkdir()
            calls.append((argv, kwargs))
            rows = [{'event': 'syscall_failed', 'syscall': 'open', 'path': '/proc/self/setgroups',
                     'errno': 13, 'original_pid': 123}] if len(calls) == 1 else [
                {'MESSAGE': 'apparmor="DENIED" operation="capable" capname="sys_admin" info="Userns policy restriction" pid=123'},
                {'MESSAGE': 'apparmor="DENIED" operation="capable" capname="net_admin" pid=123'},
                {'MESSAGE': 'apparmor="DENIED" operation="capable" capname="sys_admin" pid=1234'},
                {'MESSAGE': 'foreign text pid=123'},
            ]
            (output/'stdout.raw').write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
            return {'owner': {'pid': 123}, 'capture_completed': True, 'returncode': 1 if len(calls) == 1 else 0,
                    'failure': None, 'cleanup_deadline_ns': time.monotonic_ns() + 10_000_000_000,
                    'started_wall_time_ns': time.time_ns(), 'terminal_wall_time_ns': time.time_ns()}
        real_open = os.open
        def opened(path, *args, **kwargs):
            if path == '/dev/kmsg': raise PermissionError(13, 'explicit unavailable kernel fixture')
            return real_open(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(helper, 'capture_original_child', capture), mock.patch.object(os, 'open', opened):
                result = helper.observe_namespace_setup_v1(output_dir=Path(directory)/'out',
                    python='/fixture/canonical-python', absolute_deadline_ns=10**30)
        self.assertEqual(len(calls), 2)
        self.assertIn('--case-sensitive=no', calls[1][0])
        self.assertIn('capable', next(arg for arg in calls[1][0] if arg.startswith('--grep=')))
        self.assertEqual(calls[1][1], {'execution_s': 2, 'cleanup_s': 1, 'start_gate': True})
        self.assertEqual(calls[1][0][0], '/fixture/canonical-python')
        self.assertEqual(Path(calls[1][0][5]).name, 'journalctl')
        self.assertNotIn('sudo', ' '.join(calls[1][0]))
        self.assertEqual(len(result['policy_denial']['records']), 1)
        self.assertFalse(result['policy_denial']['policy_denial_proven'])
        self.assertFalse(result['namespace_succeeded'])
        query = result['policy_denial']['original_kernel_query']
        self.assertEqual(query['command_after_original_start_gate'], calls[1][0][5:])
        self.assertTrue(query['gate_owner_executable_is_initial_python'])
        self.assertFalse(query['post_exec_executable_observed'])

    def test_exact_first_unshare_failure_delegates_once_and_retains_original_errno(self):
        helper = self.helper()
        events = []
        calls = []
        def original(flags):
            calls.append(flags)
            raise PermissionError(13, 'explicit fixture denial')
        stock = types.SimpleNamespace(os=os, _linux_mount_v3=lambda *args: None)
        with mock.patch.object(os, 'unshare', original, create=True):
            with helper.instrument_namespace_calls(stock, events.append, original_pid=os.getpid()):
                with self.assertRaises(PermissionError):
                    stock.os.unshare(0x10000000)
        self.assertEqual(calls, [0x10000000])
        failure = [e for e in events if e['event'] == 'syscall_failed'][0]
        self.assertEqual((failure['syscall'], failure['flags'], failure['errno']), ('unshare', 0x10000000, 13))
        self.assertEqual(failure['original_pid'], os.getpid())
        self.assertIs(stock.os.unshare, os.unshare)

    def test_mapping_open_failure_identifies_actual_path_and_flags(self):
        helper = self.helper()
        events = []
        real_open = os.open
        def original(path, flags, *args, **kwargs):
            if path == '/proc/self/uid_map':
                raise PermissionError(13, 'explicit mapping fixture denial')
            return real_open(path, flags, *args, **kwargs)
        stock = types.SimpleNamespace(os=os, _linux_mount_v3=lambda *args: None)
        with mock.patch.object(os, 'open', original):
            with helper.instrument_namespace_calls(stock, events.append, original_pid=os.getpid()):
                with self.assertRaises(PermissionError):
                    stock.os.open('/proc/self/uid_map', os.O_WRONLY | os.O_NOFOLLOW)
        failure = [e for e in events if e['event'] == 'syscall_failed'][0]
        self.assertEqual(failure['syscall'], 'open')
        self.assertEqual(failure['path'], '/proc/self/uid_map')
        self.assertEqual(failure['flags'], os.O_WRONLY | os.O_NOFOLLOW)

    def test_original_mount_cause_and_flags_are_retained_without_policy_inference(self):
        helper = self.helper()
        events = []
        def mount(*args):
            try:
                raise PermissionError(13, 'explicit mount fixture denial')
            except PermissionError as cause:
                raise RuntimeError('stock wrapper') from cause
        stock = types.SimpleNamespace(os=os, _linux_mount_v3=mount)
        with helper.instrument_namespace_calls(stock, events.append, original_pid=os.getpid()):
            with self.assertRaises(RuntimeError):
                stock._linux_mount_v3(None, b'/', None, 16384)
        failure = [e for e in events if e['event'] == 'syscall_failed'][0]
        self.assertEqual((failure['syscall'], failure['errno'], failure['flags']), ('mount', 13, 16384))
        self.assertNotIn('apparmor_denial_proven', failure)
        self.assertIs(stock._linux_mount_v3, mount)

    def test_real_ordinary_child_nonzero_and_raw_eof_are_preserved(self):
        helper = self.helper()
        import sys
        with tempfile.TemporaryDirectory() as directory:
            result = helper.capture_original_child(
                self.ordinary_child("print('explicit nonnamespace fixture');sys.exit(7)"),
                Path(directory)/'out', 10**30, execution_s=1, cleanup_s=1, start_gate=True)
            self.assertEqual(result['returncode'], 7)
            self.assertFalse(result['timed_out'])
            self.assertEqual(result['eof'], {'stdout': True, 'stderr': True})
            self.assertTrue(result['original_group_absent'])
            self.assertIn(b'explicit nonnamespace fixture', (Path(directory)/'out/stdout.raw').read_bytes())

    def test_real_ordinary_child_timeout_reaps_original_and_never_reports_success(self):
        helper = self.helper()
        import sys
        with tempfile.TemporaryDirectory() as directory:
            result = helper.capture_original_child(
                [sys.executable, '-I', '-B', '-c', 'import time;time.sleep(10)'],
                Path(directory)/'out', 10**30, execution_s=.05, cleanup_s=1)
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['returncode'], -9)
            self.assertTrue(result['original_group_absent'])

    def test_real_ordinary_child_overflow_retains_bounded_prefix_and_fails(self):
        helper = self.helper()
        import sys
        with tempfile.TemporaryDirectory() as directory:
            result = helper.capture_original_child(
                self.ordinary_child("os.write(1,b'x'*70000)"),
                Path(directory)/'out', 10**30, execution_s=1, cleanup_s=1, start_gate=True)
            self.assertTrue(result['capture_exceeded'])
            self.assertLessEqual((Path(directory)/'out/stdout.raw').stat().st_size, 48*1024)
            self.assertFalse(result['capture_completed'])

    def test_original_pidfd_failure_contains_exact_child_and_leaves_no_parent_fds(self):
        helper = self.helper()
        import sys
        before = set(Path('/proc/self/fd').iterdir())
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(os, 'pidfd_open', side_effect=OSError(24,'explicit pidfd fixture fault')):
                result = helper.capture_original_child(
                    [sys.executable,'-I','-B','-c','import time;time.sleep(10)'],
                    Path(directory)/'out', 10**30, execution_s=1, cleanup_s=1)
            self.assertIn('original owner/pidfd unavailable', result['failure'])
            self.assertFalse(result['capture_completed'])
            self.assertEqual(result['returncode'], -9)
            self.assertTrue(result['original_group_absent'])
        self.assertEqual(set(Path('/proc/self/fd').iterdir()), before)

    def test_original_capture_flush_failure_closes_fd_and_preserves_failed_status(self):
        helper = self.helper()
        import sys
        real_open = Path.open
        retained = []
        class FailingFlush:
            def __init__(self, stream): self.stream=stream
            def write(self, raw): return self.stream.write(raw)
            def flush(self): raise OSError('explicit original flush fault')
            def fileno(self): return self.stream.fileno()
            def close(self): self.stream.close()
        def opened(path, *args, **kwargs):
            stream = real_open(path, *args, **kwargs)
            if path.name == 'stdout.raw':
                retained.append(stream)
                return FailingFlush(stream)
            return stream
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(Path, 'open', opened):
                result = helper.capture_original_child(
                    self.ordinary_child("print('explicit ordinary-child fixture')"),
                    Path(directory)/'out', 10**30, execution_s=1, cleanup_s=1, start_gate=True)
            self.assertFalse(result['capture_completed'])
            self.assertIn('explicit original flush fault', result['failure'])
            self.assertTrue(retained[0].closed)
            self.assertTrue(result['original_group_absent'])

    def test_original_cleanup_deadline_includes_capture_close(self):
        helper = self.helper()
        import sys,time
        real_fsync = os.fsync
        def delayed(fd):
            time.sleep(.06)
            real_fsync(fd)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(os, 'fsync', delayed):
                result = helper.capture_original_child(
                    self.ordinary_child('pass'),
                    Path(directory)/'out', 10**30, execution_s=1, cleanup_s=.05, start_gate=True)
            self.assertFalse(result['capture_completed'])
            self.assertIn('deadline',result['failure'])

    def test_original_child_exit_does_not_extend_descendant_pipe_cleanup_to_execution_budget(self):
        helper = self.helper()
        import sys
        child = "import subprocess,sys;subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(10)'])"
        with tempfile.TemporaryDirectory() as directory:
            result = helper.capture_original_child(self.ordinary_child(child),
                Path(directory)/'out',10**30,execution_s=2,cleanup_s=.2,start_gate=True)
            self.assertFalse(result['capture_completed'])
            self.assertLess(result['elapsed_s'],1)
            self.assertTrue(result['original_group_absent'])

    def test_kernel_query_is_read_only_once_and_rejects_foreign_pid_prefix(self):
        helper = self.helper()
        import json,time
        calls = []
        def capture(argv, output, deadline, **kwargs):
            output=Path(output);output.mkdir()
            calls.append(argv)
            if len(calls)==1:
                row={'event':'syscall_failed','syscall':'unshare','flags':268435456,'errno':13,
                     'original_pid':123,'stock_tolerated_missing_setgroups':False}
                (output/'stdout.raw').write_text(json.dumps(row)+'\n')
            else:
                (output/'stdout.raw').write_text('\n'.join(json.dumps({'MESSAGE':message}) for message in [
                    'apparmor="DENIED" operation="userns_create" pid=1234 comm="foreign"',
                    'apparmor="DENIED" operation="userns_create" pid=123 comm="python3.12"'])+'\n')
            return {'owner':{'pid':123},'capture_completed':True,'returncode':1 if len(calls)==1 else 0,
                    'failure':None,'cleanup_deadline_ns':time.monotonic_ns()+10_000_000_000,
                    'started_wall_time_ns':time.time_ns(),'terminal_wall_time_ns':time.time_ns()}
        real_open = os.open
        def opened(path,*a,**k):
            if path=='/dev/kmsg': raise PermissionError(13,'explicit inaccessible kernel fixture')
            return real_open(path,*a,**k)
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(helper,'capture_original_child',capture), mock.patch.object(os,'open',opened):
                result=helper.observe_namespace_setup_v1(output_dir=Path(directory)/'out',
                    python='/fixture/canonical-python',absolute_deadline_ns=10**30)
            self.assertEqual(len(calls),2)
            self.assertEqual(Path(calls[1][5]).name, 'journalctl')
            self.assertNotIn('sudo', ' '.join(calls[1]))
            self.assertIn('--kernel',calls[1])
            self.assertNotIn('apparmor_parser',' '.join(calls[1]))
            self.assertEqual(len(result['policy_denial']['records']),1)
            self.assertIn('pid=123 comm',result['policy_denial']['records'][0]['original_journal_record']['MESSAGE'])
            self.assertFalse(result['policy_denial']['policy_denial_proven'])
            self.assertFalse(result['namespace_succeeded'])

    def test_prepared_namespace_and_kernel_capture_share_the_reviewed_64kib_domain(self):
        helper = self.helper()
        import sys
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'out'
            # This ordinary child is larger than the per-capture allowance;
            # it never invokes namespace setup or a kernel reader.
            result = helper.capture_original_child(
                self.ordinary_child("os.write(1,b'x'*(24*1024))"),
                output, 10**30, execution_s=1, cleanup_s=1, start_gate=True)
            self.assertTrue(result['capture_exceeded'])
            self.assertFalse(result['capture_completed'])
            self.assertTrue(result['original_group_absent'])
            self.assertLessEqual(sum((output/name).stat().st_size for name in
                                     ('stdout.raw','stderr.raw')), 16*1024)
            self.assertLessEqual((output/'capture.json').stat().st_size, 12*1024-256)
        # Two captures, including reserved late-close leaves, and one final
        # relevant-denial leaf must all fit in the reviewed aggregate domain.
        aggregate = 2*(helper.RAW_LIMIT + helper.REPORT_LIMIT + 256) + helper.DENIAL_LIMIT
        self.assertLessEqual(aggregate, 64*1024)


if __name__ == '__main__':
    unittest.main()
