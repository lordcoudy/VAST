from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/ci_external_test_observer_v1.py"
spec = importlib.util.spec_from_file_location("ci_observer_fixture", MODULE)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ExternalObserverTests(unittest.TestCase):
    def invoke(self, directory, body, *, interval=.02, cleanup=1, ready=1):
        program = ("import importlib.util,os,signal,sys,time,json\n"
                   "s=importlib.util.spec_from_file_location('observer',sys.argv[1]);"
                   "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
                   "trace_fd=int(sys.argv[2]);event_fd=int(sys.argv[3]);stop_fd=int(sys.argv[4])\n" + body)
        return observer.observe_test_child(
            lambda trace, event, stop: [sys.executable, "-I", "-B", "-c", program,
                                  str(MODULE), str(trace), str(event), str(stop)],
            output_dir=Path(directory) / "original",
            absolute_deadline_ns=time.monotonic_ns() + 5_000_000_000,
            interval_s=interval, cleanup_s=cleanup, ready_timeout_s=ready)

    def test_real_signal_dump_has_one_native_task_and_actual_response(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory, "with m.child_trace_handler(trace_fd,event_fd,stop_fd): time.sleep(.12)\n")
            self.assertTrue(result["successful"], result)
            rows = [json.loads(line) for line in (Path(directory) / "original/responses.original.jsonl").read_text().splitlines()]
            self.assertEqual(rows[0]["event"], "ready")
            self.assertEqual(rows[0]["native_task_count"], 1)
            self.assertGreaterEqual(result["requests_sent"], 2)
            self.assertGreaterEqual(result["responses_started"], 2)
            trace = (Path(directory) / "original/trace.original.log").read_text()
            self.assertIn("handler", trace)
            self.assertIn('File "<string>"', trace)
            self.assertEqual(result["owner"]["ppid"], os.getpid())
            self.assertTrue(all(result["pipe_eof"].values()))

    def test_long_native_call_records_delay_and_possible_coalescing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "import hashlib\nwith m.child_trace_handler(trace_fd,event_fd,stop_fd):\n"
                " hashlib.pbkdf2_hmac('sha256',b'x',b'y',1000000)\n time.sleep(.03)\n")
            self.assertTrue(result["successful"], result)
            self.assertGreater(result["requests_sent"], result["responses_started"])
            self.assertGreater(result["unmatched_or_coalesced_requests_possible"], 0)
            self.assertIn("no one-to-one", result["response_matching"])

    def test_existing_handler_is_rejected_without_ready_or_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "signal.signal(signal.SIGUSR1,lambda *a:None)\n"
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd): pass\n")
            self.assertFalse(result["successful"])
            self.assertFalse(result["ready"])
            self.assertNotEqual(result["returncode"], 0)

    def test_ready_missing_stops_only_original_child(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory, "time.sleep(4)\n", ready=.1)
            self.assertFalse(result["successful"])
            self.assertIn("READY", result["failure"])
            self.assertTrue(result["forced_sigterm"])
            self.assertLess(result["returncode"], 0)
            self.assertFalse(Path(f'/proc/{result["owner"]["pid"]}').exists())

    def test_original_nonzero_and_signal_are_not_success(self):
        for action in ("sys.exit(7)", "os.kill(os.getpid(),signal.SIGABRT)"):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                result = self.invoke(directory,
                    "with m.child_trace_handler(trace_fd,event_fd,stop_fd): " + action + "\n")
                self.assertFalse(result["successful"])
                self.assertNotEqual(result["returncode"], 0)
                if "SIGABRT" in action:
                    self.assertEqual(result["signal"], signal.SIGABRT)

    def test_trace_overflow_retains_exact_prefix_and_sticky_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd):\n"
                " for n in range(18): os.write(trace_fd,b'x'*65536)\n time.sleep(.1)\n")
            self.assertFalse(result["successful"])
            self.assertIn("1MiB", result["failure"])
            raw = (Path(directory) / "original/trace.original.log").read_bytes()
            self.assertEqual(len(raw), observer.TRACE_LIMIT)
            self.assertEqual(raw, b'x' * observer.TRACE_LIMIT)

    def test_control_truncated_and_oversized_prefixes_fail(self):
        for raw in ("b'{\"event\":'", "b'x'*5000"):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                result = self.invoke(directory, f"os.write(event_fd,{raw})\n")
                self.assertFalse(result["successful"])
                self.assertTrue((Path(directory) / "original/responses.original.jsonl").is_file())

    def test_nonblocking_child_control_failure_does_not_raise_into_test(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd) as state:\n"
                " os.close(event_fd)\n os.kill(os.getpid(),signal.SIGUSR1)\n"
                " assert state['failure'] is not None\n os.write(trace_fd,b'test-resumed')\n"
                "sys.exit(9)\n", interval=.5)
            self.assertNotEqual(result["returncode"], 0)
            self.assertFalse(result["successful"])
            self.assertEqual((Path(directory) / "original/trace.original.log").read_bytes(), b'test-resumed')

    def test_real_pipe_drain_deadline_is_failed_and_not_quiescence(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd):\n"
                " if os.fork()==0: time.sleep(.4);os._exit(0)\n", cleanup=.1, interval=.5)
            self.assertFalse(result["successful"])
            self.assertFalse(all(result["pipe_eof"].values()))
            self.assertIn("not established", result["descendant_quiescence"])
            time.sleep(.45)  # Explicit fixture descendant terminal, not observer proof.

    def test_capture_failure_and_cancellation_reap_original_and_retire_fds(self):
        for mode in ("write", "cancel"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                before = set(os.listdir('/proc/self/fd'))
                if mode == "write":
                    original = Path.open
                    class FailedWriter:
                        def __init__(self, wrapped): self.wrapped = wrapped
                        def write(self, raw):
                            if raw: raise OSError("fixture persistence denied")
                            return self.wrapped.write(raw)
                        def flush(self): return self.wrapped.flush()
                        def close(self): return self.wrapped.close()
                    def broken(path, *args, **kwargs):
                        stream = original(path, *args, **kwargs)
                        return FailedWriter(stream) if path.name == "trace.original.log" else stream
                    patch = mock.patch.object(Path, "open", broken)
                else:
                    patch = mock.patch.object(observer.selectors.EpollSelector, "select", side_effect=KeyboardInterrupt("fixture cancel"))
                with patch:
                    result = self.invoke(directory,
                        "with m.child_trace_handler(trace_fd,event_fd,stop_fd): time.sleep(4)\n")
                self.assertFalse(result["successful"])
                self.assertFalse(Path(f'/proc/{result["owner"]["pid"]}').exists())
                self.assertEqual(before, set(os.listdir('/proc/self/fd')))

    def test_sigaction_disposition_and_restart_snapshot_are_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke(directory,
                "import ctypes\nlibc=ctypes.CDLL(None);a=ctypes.create_string_buffer(512);b=ctypes.create_string_buffer(512)\n"
                "libc.sigaction(signal.SIGUSR1,None,ctypes.byref(a))\n"
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd): pass\n"
                "libc.sigaction(signal.SIGUSR1,None,ctypes.byref(b))\n"
                "assert (int.from_bytes(a.raw[136:140],'little') & 0x10000000)==(int.from_bytes(b.raw[136:140],'little') & 0x10000000)\nassert signal.getsignal(signal.SIGUSR1)==signal.SIG_DFL\n")
            self.assertTrue(result["successful"], result)

    def test_missing_stop_ack_and_live_pipe_eof_are_failed(self):
        for body in (
            "with m.child_trace_handler(trace_fd,event_fd,stop_fd): os.close(stop_fd)\n",
            "with m.child_trace_handler(trace_fd,event_fd,stop_fd):\n os.close(trace_fd)\n time.sleep(4)\n",
        ):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                result = self.invoke(directory, body)
                self.assertFalse(result["successful"])
                self.assertFalse(Path(f'/proc/{result["owner"]["pid"]}').exists())

    def test_receipt_close_crossing_original_cleanup_deadline_is_failed(self):
        original = Path.open
        class LateClose:
            def __init__(self, wrapped): self.wrapped = wrapped
            def write(self, raw): return self.wrapped.write(raw)
            def flush(self): return self.wrapped.flush()
            def close(self): time.sleep(.15);return self.wrapped.close()
        def delayed(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return LateClose(stream) if path.name == "terminal.v1.json" else stream
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(Path, "open", delayed):
            result = self.invoke(directory,
                "with m.child_trace_handler(trace_fd,event_fd,stop_fd): pass\n", cleanup=.1)
            self.assertFalse(result["successful"])
            self.assertIn("receipt-close", result["failure"])
            self.assertTrue((Path(directory)/"original/late-finalization.failure.json").is_file())

    def test_new_namespace_overflow_is_sticky_and_retires_original_fds(self):
        before = set(os.listdir('/proc/self/fd'))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(observer, "NAMESPACE_LIMIT", 128):
            with self.assertRaisesRegex(RuntimeError, "8MiB"):
                self.invoke(directory, "time.sleep(4)\n")
        self.assertEqual(before, set(os.listdir('/proc/self/fd')))

    def test_pidfd_open_failure_reaps_exact_live_original_child(self):
        before = set(os.listdir('/proc/self/fd'))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            observer.os, "pidfd_open", side_effect=OSError("fixture pidfd acquisition failed")
        ):
            result = self.invoke(directory, "time.sleep(4)\n")
            self.assertFalse(result["successful"])
            self.assertTrue(result["pidfd_acquisition_failed"])
            self.assertIn("pidfd acquisition failed", result["failure"])
            self.assertLess(result["returncode"], 0)
            self.assertTrue(result["forced_sigterm"])
            self.assertFalse(Path(f'/proc/{result["owner"]["pid"]}').exists())
            launch = json.loads((Path(directory)/"original/launch.v1.json").read_text())
            self.assertFalse(launch["pidfd_opened"])
            self.assertFalse(all(result["pipe_eof"].values()))
        self.assertEqual(before, set(os.listdir('/proc/self/fd')))


if __name__ == "__main__":
    unittest.main()
