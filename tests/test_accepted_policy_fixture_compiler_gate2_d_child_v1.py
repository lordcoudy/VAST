"""Controlled D-child schedules: no native process, ELF or resource mutation."""
import io
from pathlib import Path
import signal
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as recipe
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as stage
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_child_v1 as child


def proof(**changes):
    value = dict(pid=321, uid=1000, euid=1000, gid=1000, egid=1000,
                 pgid=321, sid=321, core=[1, 1], fsize=[1048576, 1048576])
    value.update(changes)
    return recipe.canonical_json_v1(value) + b"\n"


class Stream(io.BytesIO):
    def __init__(self, raw=b"", *, fail_write=False, fail_close=False):
        super().__init__(raw)
        self.saved, self.fail_write, self.fail_close = raw, fail_write, fail_close
    def fileno(self):
        return id(self)
    def write(self, raw):
        if self.fail_write:
            super().write(raw[:2])
            raise OSError("unreturned extent")
        return super().write(raw)
    def close(self):
        self.saved = self.getvalue()
        super().close()
        if self.fail_close:
            raise OSError("close failure")


class World:
    def __init__(self, *, mode="normal", raw_proof=None):
        self.now, self.mode = 0, mode
        self.proof = bytearray(proof() if raw_proof is None else raw_proof)
        self.stdin, self.stdout, self.stderr = Stream(), Stream(recipe.D_REPLY), Stream()
        if mode == 'stdin_close_fault':
            self.stdin.fail_close = True
        if mode == "overflow":
            self.stdout = Stream(b"x" * 5000)
        if mode == 'combined_overflow':
            self.stdout, self.stderr = Stream(b'x' * 3000), Stream(b'y' * 3000)
        self.pid, self.returncode = 321, None
        self.signals, self.calls, self.files, self.closed_fds = [], [], {}, []
        self.identity_value = dict(pid=321, start_ticks=12345, pgid=321, sid=321,
                                   uid=1000, euid=1000, gid=1000, egid=1000)
        self.identity_calls, self.waited = 0, False
        self.interrupted = False
    def popen(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        kwargs["preexec_fn"]()
        if self.mode == "late_spawn":
            self.now = 11_000_000_000
        if self.mode == 'bad_spawn_clock':
            self.now = -1
        return self
    def identity(self, pid):
        self.identity_calls += 1
        value = dict(self.identity_value)
        if self.mode == "identity_drift" and self.identity_calls > 1:
            value["start_ticks"] += 1
        return value
    def fd_read(self, fd, count):
        result = bytes(self.proof[:count])
        del self.proof[:count]
        return result
    def select(self, readers, writers, errors, timeout):
        self.now += max(1, int(timeout * 1_000_000_000))
        if self.mode == 'select_interrupt' and not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        ready = [fd for fd in readers if fd == 10 or self.stdin.closed or self.signals]
        return ready, writers, []
    def waitpid(self, pid, flags):
        if self.mode == 'wait_interrupt' and not self.interrupted:
            self.interrupted = True
            raise KeyboardInterrupt
        if self.waited:
            raise AssertionError("owned child reaped twice")
        status = None
        if self.mode in ('normal', 'stdin_close_fault') and self.stdin.closed:
            status = 0
        if self.mode == "core" and self.stdin.closed:
            status = signal.SIGSEGV | 0x80
        if self.mode not in ("unknown", "identity_drift") and self.signals:
            last = self.signals[-1][1]
            if last == signal.SIGKILL or self.mode not in ("kill", "early_kill"):
                status = int(last)
        if status is None:
            return 0, 0
        self.waited = True
        return pid, status
    def killpg(self, pid, number):
        self.signals.append((self.now, number))
        if self.mode == 'late_signal':
            self.now = 11_000_000_000
    def open_capture(self, path):
        if self.mode == 'late_prepare':
            self.now = 7_500_000_000
        if path.name in self.files:
            raise FileExistsError(path.name)
        stream = Stream(fail_write=self.mode == "write_fault" and path.name == "d.stdout.original",
                        fail_close=self.mode == "close_fault" and path.name == "d.stdout.original")
        self.files[path.name] = stream
        return stream
    def effects(self):
        return dict(clock=lambda: self.now, popen=self.popen, pipe=lambda: (10, 11),
                    fd_close=lambda fd: self.closed_fds.append(fd), fd_read=self.fd_read,
                    nonblocking=lambda fd: None, select=self.select, waitpid=self.waitpid,
                    identity=self.identity, killpg=self.killpg, open_capture=self.open_capture,
                    sync=lambda fd: None, preexec=lambda fd: None,
                    physical_directory=lambda path: True)


class ChildTests(unittest.TestCase):
    def run_world(self, world):
        return child.run_child_v1(executable_path=Path('/controlled/D/engine'),
            directory=Path('/controlled/D'), output_dir=Path('/controlled/outputs'),
            started_ns=0, absolute_deadline_ns=10_000_000_000, _effects=world.effects())

    def test_normal_child_has_proof_exit_eofs_and_persisted_originals_separately(self):
        world = World()
        result = self.run_world(world)
        self.assertEqual(result['causes'], [])
        self.assertEqual(result['proof'], proof().decode('ascii'))
        self.assertTrue(result['identity_verified'] and result['proof_eof'])
        self.assertEqual((result['wait_status'], result['returncode']), (0, 0))
        self.assertTrue(result['reaped'] and result['stdout_eof'] and result['stderr_eof'])
        self.assertEqual(result['stdout'], recipe.D_REPLY.decode('ascii'))
        self.assertEqual(result['stderr'], '')
        self.assertEqual(world.stdin.saved, recipe.D_COMMAND)
        self.assertTrue(result['stdin_closed'] and result['capture_persisted'] and result['capture_closed'])
        self.assertFalse(result['forced'] or result['unknown_closure'] or result['late'])
        self.assertTrue(result['controlled'])
        self.assertEqual(world.signals, [])
        argv, options = world.calls[0]
        self.assertEqual(argv, ['/controlled/D/engine'])
        self.assertTrue(options['start_new_session'] and options['close_fds'])
        self.assertEqual(options['env'], stage.child_environment_v1('/controlled/D'))
        self.assertEqual(options['pass_fds'], (11,))
        self.assertEqual(set(world.files), {'d.stdout.original', 'd.stderr.original', 'd.preexec.original'})
        self.assertIn(10, world.closed_fds)
        self.assertIn(11, world.closed_fds)

    def test_work_term_kill_and_final_share_the_original_absolute_budget(self):
        for mode in ('kill', 'unknown'):
            with self.subTest(mode=mode):
                world = World(mode=mode)
                result = self.run_world(world)
                self.assertEqual(world.signals, [(7_000_000_000, signal.SIGTERM), (8_000_000_000, signal.SIGKILL)])
                self.assertTrue(result['forced'])
                self.assertLessEqual(world.now, 10_000_000_000)
                if mode == 'unknown':
                    self.assertTrue(result['unknown_closure'])
                    self.assertFalse(result['reaped'])
                else:
                    self.assertTrue(result['reaped'])
                    self.assertEqual(result['returncode'], -signal.SIGKILL)

    def test_invalid_proof_starts_containment_immediately_without_waiting_seven_seconds(self):
        world = World(mode='early_kill', raw_proof=proof(core=[0, 0]))
        result = self.run_world(world)
        self.assertIn('d_preexec_proof', result['causes'])
        self.assertLess(world.signals[0][0], 1_000_000_000)
        self.assertEqual(world.signals[1][0] - world.signals[0][0], 1_000_000_000)
        self.assertEqual(world.stdin.saved, b'')
        self.assertTrue(result['forced'])

    def test_identity_drift_prevents_any_group_signal(self):
        world = World(mode='identity_drift')
        result = self.run_world(world)
        self.assertEqual(world.signals, [])
        self.assertIn('d_child_identity_drift', result['causes'])
        self.assertTrue(result['unknown_closure'])

    def test_output_overflow_retains_only_the_combined_four_kib_prefix(self):
        world = World(mode='overflow')
        result = self.run_world(world)
        self.assertIn('d_child_channel_cap', result['causes'])
        self.assertEqual(len(result['stdout'].encode('ascii')) + len(result['stderr'].encode('ascii')), 4096)
        self.assertEqual(world.files['d.stdout.original'].saved, b'x' * 4096)
        self.assertTrue(result['forced'])

    def test_preexec_proof_cap_refuses_with_retained_prefix(self):
        world = World(mode='proof_overflow', raw_proof=b'x' * 1025)
        result = self.run_world(world)
        self.assertIn('d_child_proof_cap', result['causes'])
        self.assertEqual(len(world.files['d.preexec.original'].saved), 1024)
        self.assertFalse(result['identity_verified'])

    def test_actual_wait_status_keeps_the_core_bit(self):
        world = World(mode='core')
        result = self.run_world(world)
        self.assertEqual(result['wait_status'], signal.SIGSEGV | 0x80)
        self.assertEqual(result['returncode'], -signal.SIGSEGV)
        self.assertTrue(result['core_dumped'])
        self.assertIn('d_child_status', result['causes'])

    def test_late_spawn_keeps_known_pid_and_unknown_closure_without_new_time(self):
        world = World(mode='late_spawn')
        result = self.run_world(world)
        self.assertEqual(result['pid'], 321)
        self.assertTrue(result['late'] and result['unknown_closure'])
        self.assertFalse(result['reaped'])
        self.assertEqual(world.signals, [])
        self.assertEqual(world.now, 11_000_000_000)

    def test_preparation_crossing_work_cutoff_refuses_before_spawn(self):
        world = World(mode='late_prepare')
        result = self.run_world(world)
        self.assertEqual(world.calls, [])
        self.assertIsNone(result['pid'])
        self.assertIn('d_child_spawn_window', result['causes'])

    def test_invalid_clock_after_spawn_stops_dependent_observations(self):
        world = World(mode='bad_spawn_clock')
        result = self.run_world(world)
        self.assertEqual(result['pid'], 321)
        self.assertTrue(result['late'] and result['unknown_closure'])
        self.assertEqual(world.identity_calls, 0)
        self.assertEqual(world.signals, [])

    def test_signal_crossing_absolute_cutoff_does_not_begin_another_observation(self):
        world = World(mode='late_signal')
        result = self.run_world(world)
        self.assertTrue(result['late'] and result['unknown_closure'])
        self.assertFalse(result['reaped'])
        self.assertEqual(result['signals'], ['TERM'])
        self.assertEqual(world.now, 11_000_000_000)

    def test_stdout_and_stderr_share_one_capture_cap(self):
        world = World(mode='combined_overflow')
        result = self.run_world(world)
        self.assertIn('d_child_channel_cap', result['causes'])
        self.assertEqual(world.files['d.stdout.original'].saved, b'x' * 3000)
        self.assertEqual(world.files['d.stderr.original'].saved, b'y' * 1096)

    def test_capture_write_and_close_failures_cannot_report_persistence_success(self):
        for mode in ('write_fault', 'close_fault'):
            with self.subTest(mode=mode):
                world = World(mode=mode)
                result = self.run_world(world)
                self.assertTrue(result['causes'])
                self.assertFalse(result['capture_persisted'] and result['capture_closed'])

    def test_stdin_close_exception_remains_unknown_without_recovered_close_claim(self):
        world = World(mode='stdin_close_fault')
        result = self.run_world(world)
        self.assertEqual(result['stdin_written_bytes'], len(recipe.D_COMMAND))
        self.assertFalse(result['stdin_closed'])
        self.assertTrue(result['unknown_closure'])
        self.assertIn('d_child_stdin_OSError', result['causes'])

    def test_interruption_keeps_owned_child_and_bounded_containment(self):
        for mode in ('wait_interrupt', 'select_interrupt'):
            with self.subTest(mode=mode):
                world = World(mode=mode)
                result = self.run_world(world)
                self.assertTrue(result['forced'] and result['reaped'])
                self.assertEqual(result['pid'], 321)
                self.assertEqual(result['signals'], ['TERM'])
                self.assertTrue(any('KeyboardInterrupt' in value for value in result['causes']))
                self.assertLess(world.now, 3_000_000_000)


class PreexecTests(unittest.TestCase):
    def test_limits_are_set_before_measured_proof_and_fd_closed_before_exec(self):
        events, limits = [], {}
        def set_limit(name, value):
            events.append(('set', name, value))
            limits[name] = value
        def get_limit(name):
            events.append(('get', name))
            return limits[name]
        written = []
        effects = dict(set_limit=set_limit, get_limit=get_limit, getpid=lambda: 321,
                       getuid=lambda: 1000, geteuid=lambda: 1000, getgid=lambda: 1000,
                       getegid=lambda: 1000, getpgid=lambda pid: 321, getsid=lambda pid: 321,
                       write=lambda fd, raw: written.append(raw) or len(raw),
                       close=lambda fd: events.append(('close', fd)))
        child._preexec_proof_v1(11, _effects=effects)
        self.assertEqual(events[:2], [('set', 'CORE', (1, 1)), ('set', 'FSIZE', (1048576, 1048576))])
        self.assertEqual(written, [proof()])
        self.assertEqual(events[-1], ('close', 11))


if __name__ == '__main__':
    unittest.main()
