"""Original Popen hook regressions; these fixtures grant no container acceptance."""
from __future__ import annotations
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

MODULES = (
    "checkpoint_gstreamer_publication_runtime_v3",
    "checkpoint_openvino_gva_publication_runtime_v3",
    "checkpoint_deepstream_publication_runtime_v3",
    "checkpoint_savant_publication_runtime_v3",
)

@unittest.skipUnless(sys.platform == "linux", "requires Linux held-executable process invocation")
class OriginalProcessHookTests(unittest.TestCase):
    def _pin(self, runtime):
        path = Path(sys.executable).resolve()
        fd = os.open(path, os.O_RDONLY)
        info = os.fstat(fd)
        return runtime._Pin(role="container_engine", path=path, fd=fd,
            snapshot=runtime._snapshot(info), size=info.st_size, sha256="0" * 64, container_path=None)

    def test_original_terminal_hook_uses_actual_wait_status_and_original_bytes(self):
        for name in MODULES:
            with self.subTest(runtime=name):
                runtime = importlib.import_module(name)
                pin = self._pin(runtime)
                try:
                    token = object()
                    with mock.patch.object(runtime, "engine_process_started_v1", return_value=token) as started, mock.patch.object(runtime, "engine_process_terminal_v1") as terminal:
                        result = runtime._invoke_engine(pin, {"path": "/nonexistent-test.sock"},
                            ("-c", "import sys; print('original'); sys.stderr.write('error'); sys.exit(3)"), 5.0)
                    self.assertEqual(result.returncode, 3)
                    self.assertEqual(result.stdout, b"original\n")
                    self.assertEqual(result.stderr, b"error")
                    process = started.call_args.args[0]
                    self.assertIsInstance(process, runtime.subprocess.Popen)
                    self.assertEqual(process.returncode, 3)
                    self.assertEqual(terminal.call_count, 1)
                    self.assertEqual(terminal.call_args.args,
                        (token, process, b"original\n", b"error", False, False, False))
                finally:
                    os.close(pin.fd)

    def test_start_persistence_failure_reaps_original_child(self):
        for name in MODULES:
            with self.subTest(runtime=name):
                runtime = importlib.import_module(name)
                pin = self._pin(runtime)
                observed = []
                def fail_started(process, *args):
                    observed.append(process)
                    raise OSError("fixture original launch persistence failed")
                try:
                    with mock.patch.object(runtime, "engine_process_started_v1", side_effect=fail_started), mock.patch.object(runtime, "engine_process_terminal_v1") as terminal:
                        with self.assertRaisesRegex(OSError, "original launch persistence failed"):
                            runtime._invoke_engine(pin, {"path": "/nonexistent-test.sock"},
                                ("-c", "import time; time.sleep(30)"), 5.0)
                    self.assertEqual(len(observed), 1)
                    self.assertIsNotNone(observed[0].poll())
                    terminal.assert_not_called()
                finally:
                    os.close(pin.fd)

    def test_timeout_records_original_killed_status_before_existing_error(self):
        for name in MODULES:
            with self.subTest(runtime=name):
                runtime = importlib.import_module(name)
                pin = self._pin(runtime)
                try:
                    token = object()
                    with mock.patch.object(runtime, "engine_process_started_v1", return_value=token), mock.patch.object(runtime, "engine_process_terminal_v1") as terminal:
                        with self.assertRaises(runtime.NativePublicationTransientErrorV3):
                            runtime._invoke_engine(pin, {"path": "/nonexistent-test.sock"},
                                ("-c", "import time; time.sleep(30)"), .05)
                    self.assertEqual(terminal.call_count, 1)
                    self.assertEqual(terminal.call_args.args[1].returncode, -9)
                    self.assertEqual(terminal.call_args.args[4:], (True, False, False))
                finally:
                    os.close(pin.fd)

    def test_wait_failure_closes_original_pipes_and_preserves_body_cause(self):
        for name in MODULES:
            with self.subTest(runtime=name):
                runtime = importlib.import_module(name)
                pin = self._pin(runtime)
                observed = []
                def fail_started(process, *args):
                    observed.append(process)
                    actual_wait = process.wait
                    calls = 0
                    def failed_wait(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            actual_wait(*args, **kwargs)
                            raise runtime.subprocess.TimeoutExpired("fixture original wait", 10)
                        raise OSError("fixture second original wait failed")
                    process.wait = failed_wait
                    raise OSError("fixture original body failed")
                try:
                    with mock.patch.object(runtime, "engine_process_started_v1", side_effect=fail_started), mock.patch.object(runtime, "engine_process_terminal_v1") as terminal:
                        with self.assertRaisesRegex(OSError, "original body failed") as raised:
                            runtime._invoke_engine(pin, {"path": "/nonexistent-test.sock"},
                                ("-c", "import time; time.sleep(30)"), 5.0)
                    process = observed[0]
                    self.assertIsNotNone(process.returncode)
                    self.assertTrue(process.stdout.closed)
                    self.assertTrue(process.stderr.closed)
                    self.assertTrue(any("second original wait failed" in note for note in raised.exception.__notes__))
                    terminal.assert_not_called()
                finally:
                    os.close(pin.fd)

if __name__ == "__main__":
    unittest.main()
