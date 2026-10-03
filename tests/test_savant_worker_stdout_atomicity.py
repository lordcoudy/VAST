from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from checkpoint_savant_container_runtime_v3 import (
    SavantContainerRuntimeV3Error, validate_savant_native_stdio,
)

DEFAULT = b'max_fps_dur 8.33333e+06 min_fps_dur 2e+08\n'
CONFIGURED = b'max_fps_dur 1.66667e+06 min_fps_dur 1.66667e+06\n'


@unittest.skipUnless(sys.platform == 'linux', 'Native worker descriptors require Linux')
class SavantWorkerStdoutAtomicityTests(unittest.TestCase):
    def run_child(self, body):
        prefix = 'import os, sys\nsys.path.insert(0, ' + repr(str(ROOT / 'scripts')) + ')\n'
        prefix += 'import checkpoint_savant_sdk_runtime_v3 as worker\n'
        return subprocess.run([sys.executable, '-B', '-c', prefix + textwrap.dedent(body)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)

    def test_concurrent_worker_entrypoints_preserve_fragmented_native_notices(self):
        result = self.run_child('''
            import multiprocessing, tempfile
            from pathlib import Path
            context = multiprocessing.get_context('fork')
            barrier = context.Barrier(2, timeout=10)
            def child():
                def run(args):
                    for fragment in (b'max_fps_dur ', b'8.33333e+06 ', b'min_fps_dur ', b'2e+08\\n'):
                        os.write(1, fragment)
                        barrier.wait()
                    os.write(1, b'max_fps_dur 1.66667e+06 min_fps_dur 1.66667e+06\\n')
                worker.run_fd_worker = run
                with tempfile.TemporaryDirectory() as output:
                    code = worker.main(['run', '--codec', 'h264', '--topology-kind',
                        'independent_processes', '--stream-id', '0', '--branches',
                        'plate_number', '--arm-id', 'atomic-test', '--output-dir', output])
                raise SystemExit(code)
            children = [context.Process(target=child) for _ in range(2)]
            for child in children: child.start()
            for child in children:
                child.join(15)
                assert child.exitcode == 0, child.exitcode
        ''')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stderr, b'')
        self.assertEqual(result.stdout, (DEFAULT + CONFIGURED) * 2)
        with tempfile.TemporaryDirectory() as name:
            stdout, stderr = Path(name) / 'out', Path(name) / 'err'
            stdout.write_bytes(result.stdout)
            stderr.write_bytes(result.stderr)
            audit = validate_savant_native_stdio(stdout, stderr, expected_worker_count=2)
            self.assertEqual(audit['nvstreammux_default_timing_line_count'], 2)

    def test_native_c_buffer_is_flushed_before_restoring_stdout(self):
        result = self.run_child('''
            import ctypes
            libc = ctypes.CDLL(None)
            with worker._capture_worker_native_stdout():
                libc.printf(b'native buffered bytes')
            os.write(1, b' after capture')
        ''')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'native buffered bytes after capture')

    def test_failure_keeps_captured_bytes_and_restores_stdout(self):
        result = self.run_child('''
            try:
                with worker._capture_worker_native_stdout():
                    os.write(1, b'before failure')
                    raise RuntimeError('original failure')
            except RuntimeError as error:
                assert str(error) == 'original failure'
            os.write(1, b' after failure')
        ''')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'before failure after failure')

    def test_oversized_stdout_fails_instead_of_forwarding_truncated_success(self):
        result = self.run_child('''
            try:
                with worker._capture_worker_native_stdout():
                    os.write(1, b'x' * 4097)
            except worker.SavantSdkRuntimeV3Error as error:
                assert 'stdout exceeds atomic capture bound' in str(error)
            else:
                raise AssertionError('oversized stdout accepted')
            os.write(1, b'restored')
        ''')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'restored')

    def test_unexpected_bytes_are_preserved_for_strict_validator_rejection(self):
        result = self.run_child('''
            with worker._capture_worker_native_stdout():
                os.write(1, b'unknown native warning\\n')
        ''')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(result.stdout, b'unknown native warning\n')
        with tempfile.TemporaryDirectory() as name:
            stdout, stderr = Path(name) / 'out', Path(name) / 'err'
            stdout.write_bytes(DEFAULT + CONFIGURED + result.stdout)
            stderr.write_bytes(b'')
            with self.assertRaises(SavantContainerRuntimeV3Error):
                validate_savant_native_stdio(stdout, stderr, expected_worker_count=1)


if __name__ == '__main__':
    unittest.main()
