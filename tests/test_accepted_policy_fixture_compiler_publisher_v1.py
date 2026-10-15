"""Portable publisher contract tests; all processes, files and signals are fake."""
import hashlib
import io
import json
import signal
import stat
import struct
import sys
import unittest
from types import SimpleNamespace

from tests.fixtures import accepted_policy_fixture_compiler_publisher_v1 as publisher


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf(body=b"fixture"):
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", header, 16, 2, 62, 1)
    return bytes(header) + body


def request(source=b"int main(void){return 0;}\n", header=None):
    if header is None:
        header = {"source_size": len(source), "source_sha256": digest(source)}
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii")
    return b"VASTCC1\n" + struct.pack("!I", len(raw)) + raw + source


class MemoryStream(io.BytesIO):
    def __init__(self, data=b"", *, chunk=None, read_error=False, write_limit=None,
                 flush_error=False, close_error=False):
        super().__init__(data)
        self.chunk = chunk
        self.read_error = read_error
        self.write_limit = write_limit
        self.flush_error = flush_error
        self.close_error = close_error
        self.saved = data

    def read(self, size=-1):
        if self.read_error:
            raise OSError("synthetic read failure")
        return super().read(min(size, self.chunk) if self.chunk else size)

    def write(self, data):
        if self.write_limit == 0:
            return 0
        return super().write(data[:self.write_limit] if self.write_limit else data)

    def fileno(self):
        return id(self)

    def flush(self):
        if self.flush_error:
            raise OSError("synthetic flush failure")

    def close(self):
        self.saved = self.getvalue()
        super().close()
        if self.close_error:
            raise OSError("synthetic close failure")


class World:
    def __init__(self, *, stdout=b"cc-out\n", stderr=b"cc-err\n", code=0):
        self.now = 0.0
        self.core = (1, 1)
        self.fsize = (16777216, 16777216)
        self.pid = 1
        self.calls = []
        self.opens = []
        self.kills = []
        self.handlers = {}
        self.diagnostics = MemoryStream()
        self.files = {sys.executable: elf(), "/usr/bin/cc": elf(), "/work/engine": elf()}
        self.handles = {}
        self.fail_source_write = False
        self.fail_source_close = False
        self.fail_sync = False
        self.read_stall = False
        self.write_stall = False
        self.wait_error = False
        self.descendant_live = False
        self.child = SimpleNamespace(pid=123, returncode=None,
            stdout=MemoryStream(stdout), stderr=MemoryStream(stderr))

        def poll():
            self.child.returncode = code
            return code
        self.child.poll = poll

    def open_file(self, path, mode):
        self.opens.append((path, mode))
        if mode == "xb":
            if path in self.files:
                raise FileExistsError(path)
            stream = MemoryStream(write_limit=0 if self.fail_source_write else None,
                                  close_error=self.fail_source_close)
            self.files[path] = stream
        else:
            value = self.files[path]
            stream = MemoryStream(value) if isinstance(value, bytes) else value
        self.handles[stream.fileno()] = stream
        return stream

    def file_stat(self, fd):
        stream = self.handles[fd]
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_size=len(stream.getvalue()),
            st_dev=1, st_ino=fd, st_mtime_ns=1, st_ctime_ns=1)

    def sync_file(self, fd):
        if self.fail_sync:
            raise OSError("synthetic fsync failure")

    def process_factory(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.child

    def wait_ready(self, readers, writers, errors, timeout):
        self.now += 0.001
        if self.read_stall and readers or self.write_stall and writers:
            self.now += timeout
            return [], [], []
        return readers, writers, []

    def wait_child(self):
        if self.wait_error:
            raise OSError("synthetic wait failure")
        if self.descendant_live:
            self.now += 1
            return 0, 0
        raise ChildProcessError

    def kwargs(self):
        return dict(stderr=self.diagnostics, clock=lambda: self.now, process_factory=self.process_factory,
            wait_ready=self.wait_ready, get_limit=lambda name: self.core if name == "CORE" else self.fsize,
            get_pid=lambda: self.pid, open_file=self.open_file, file_stat=self.file_stat,
            sync_file=self.sync_file, wait_child=self.wait_child,
            kill_group=lambda pid, sig: self.kills.append((pid, sig)),
            set_handler=lambda sig, fn: self.handlers.__setitem__(sig, fn),
            make_nonblocking=lambda stream: None)


class AcceptedPolicyFixtureCompilerPublisherTests(unittest.TestCase):
    def run_case(self, raw=None, world=None, output=None, chunk=None):
        world = World() if world is None else world
        input_stream = MemoryStream(request() if raw is None else raw, chunk=chunk)
        output = MemoryStream() if output is None else output
        code = publisher.run_publisher_v1(input_stream, output, **world.kwargs())
        return code, output.saved if output.closed else output.getvalue(), world

    def frame(self, data):
        self.assertTrue(data.startswith(b"VASTCE1\n"), "publisher must export its fixed framed outcome")
        self.assertGreaterEqual(len(data), 12)
        size = struct.unpack("!I", data[8:12])[0]
        self.assertLessEqual(12 + size, 65536)
        metadata = json.loads(data[12:12 + size])
        self.assertEqual(data[12:12 + size], json.dumps(metadata, sort_keys=True,
            separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"))
        offset = 12 + size
        parts = []
        for item in (metadata["compiler"]["stdout"], metadata["compiler"]["stderr"], metadata["elf"]):
            payload = data[offset:offset + item["size_bytes"]]
            self.assertEqual(len(payload), item["size_bytes"])
            self.assertEqual(digest(payload), item["sha256"])
            parts.append(payload)
            offset += len(payload)
        self.assertEqual(offset, len(data))
        self.assertLessEqual(offset, 18939904)
        return metadata, parts

    def test_success_exports_authenticated_elf_after_original_status_and_eof(self):
        code, raw, world = self.run_case()
        self.assertEqual(len(world.calls), 1, "valid fresh source must invoke the fixed compiler once")
        meta, parts = self.frame(raw)
        self.assertEqual(code, 0)
        self.assertEqual(meta["source"], {"size_bytes": 26, "sha256": digest(b"int main(void){return 0;}\n")})
        self.assertEqual(meta["artifact_kind"], "vast_fixture_compiler_export_v1")
        self.assertEqual(meta["schema_version"], 1)
        self.assertEqual(parts, [b"cc-out\n", b"cc-err\n", elf()])
        self.assertEqual(meta["compiler"]["returncode"], 0)
        self.assertTrue(meta["compiler"]["reaped"] and meta["descendants_reaped"])
        self.assertTrue(meta["elf"]["available"])
        self.assertEqual(meta["causes"], [])
        self.assertEqual(world.calls[0][0][0], ["/usr/bin/cc", "-O0", "-std=c11", "/work/engine.c", "-o", "/work/engine"])
        self.assertTrue(world.calls[0][1]["start_new_session"])
        self.assertEqual(world.calls[0][1]["cwd"], "/work")

    def test_short_reads_and_partial_output_writes_preserve_exact_wire(self):
        code, raw, _ = self.run_case(chunk=1, output=MemoryStream(write_limit=3))
        meta, parts = self.frame(raw)
        self.assertEqual(code, 0)
        self.assertEqual(parts[-1], elf())

    def test_nonzero_compiler_status_keeps_channels_without_usable_elf(self):
        code, raw, _ = self.run_case(world=World(code=7))
        meta, parts = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["returncode"], 7)
        self.assertEqual(meta["causes"][0], "compiler_exit_nonzero")
        self.assertEqual(parts[:2], [b"cc-out\n", b"cc-err\n"])
        self.assertFalse(meta["elf"]["available"])
        self.assertEqual(parts[-1], b"")

    def test_original_compiler_signal_is_not_publisher_exit_status(self):
        code, raw, _ = self.run_case(world=World(code=-9))
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["returncode"], -9)

    def test_overflow_preserves_exact_prefix_and_observed_discarded_counts(self):
        payload = b"o" * (1048576 + 19)
        code, raw, _ = self.run_case(world=World(stdout=payload))
        meta, parts = self.frame(raw)
        channel = meta["compiler"]["stdout"]
        self.assertEqual(code, 1)
        self.assertEqual(parts[0], payload[:1048576])
        self.assertEqual(channel["observed_bytes"], len(payload))
        self.assertEqual(channel["discarded_bytes"], 19)
        self.assertTrue(channel["eof"])
        self.assertIn("stdout_overflow", meta["causes"])
        self.assertFalse(meta["elf"]["available"])

    def test_bad_or_noncanonical_request_refuses_before_compiler(self):
        for header in (b'{}', b'{"source_size":true,"source_sha256":"a"}',
                       b'{"source_size":1,"source_size":1,"source_sha256":"a"}',
                       b'{ "source_sha256":"a", "source_size":1 }'):
            with self.subTest(header=header):
                code, raw, world = self.run_case(b"VASTCC1\n" + struct.pack("!I", len(header)) + header + b"a")
                meta, _ = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertFalse(world.calls)
                self.assertIn("request_invalid", meta["causes"])

    def test_declared_source_overflow_refuses_before_any_source_file(self):
        code, raw, world = self.run_case(request(b"", {"source_size": 8388609, "source_sha256": "a" * 64}))
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertNotIn(("/work/engine.c", "xb"), world.opens)
        self.assertIn("request_invalid", meta["causes"])

    def test_trailing_source_or_digest_drift_cannot_launch(self):
        for raw in (request() + b"extra", request(b"x", {"source_size": 1, "source_sha256": "0" * 64})):
            with self.subTest(raw=raw):
                code, data, world = self.run_case(raw)
                meta, _ = self.frame(data)
                self.assertEqual(code, 1)
                self.assertFalse(world.calls)
                self.assertIn("source_binding_invalid", meta["causes"])

    def test_truncated_source_retains_failure_without_invented_compiler_eof(self):
        code, raw, world = self.run_case(request()[:-1])
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertFalse(world.calls)
        self.assertFalse(meta["compiler"]["started"])
        self.assertFalse(meta["compiler"]["stdout"]["eof"])

    def test_wrong_core_fsize_or_pid_refuses_before_compiler(self):
        for key, value in (("core", (0, 0)), ("core", (1, 2)), ("core", (True, 1)),
                           ("fsize", (16777216, -1)), ("pid", 2)):
            with self.subTest(key=key, value=value):
                world = World()
                setattr(world, key, value)
                code, raw, world = self.run_case(world=world)
                meta, _ = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertFalse(world.calls)
                self.assertIn("runtime_preflight_failed", meta["causes"])

    def test_non_native_interpreter_or_compiler_elf_refuses(self):
        for path in (sys.executable, "/usr/bin/cc"):
            with self.subTest(path=path):
                world = World()
                world.files[path] = b"#!not-an-elf"
                code, raw, world = self.run_case(world=world)
                meta, _ = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertFalse(world.calls)
                self.assertIn("runtime_preflight_failed", meta["causes"])

    def test_source_write_or_fsync_failure_never_launches_compiler(self):
        for key in ("fail_source_write", "fail_sync"):
            with self.subTest(key=key):
                world = World()
                setattr(world, key, True)
                code, raw, world = self.run_case(world=world)
                meta, _ = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertFalse(world.calls)
                self.assertIn("source_io_error", meta["causes"])

    def test_failed_source_write_never_counts_unconfirmed_bytes(self):
        world = World()
        world.fail_source_write = True
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["source"], {"size_bytes": 0, "sha256": digest(b"")})
        self.assertIn("source_io_error", meta["causes"])

    def test_existing_source_is_not_overwritten_or_reused(self):
        world = World()
        world.files["/work/engine.c"] = b"old"
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertFalse(world.calls)
        self.assertEqual(world.files["/work/engine.c"], b"old")
        self.assertIn("source_io_error", meta["causes"])

    def test_bad_or_oversized_output_elf_is_unavailable(self):
        for payload in (b"not-elf", elf() + b"x" * 16777216):
            with self.subTest(size=len(payload)):
                world = World()
                world.files["/work/engine"] = payload
                code, raw, _ = self.run_case(world=world)
                meta, parts = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertFalse(meta["elf"]["available"])
                self.assertEqual(parts[-1], b"")
                self.assertIn("elf_invalid", meta["causes"])

    def test_source_close_failure_cannot_mask_original_write_failure(self):
        world = World()
        world.fail_source_write = world.fail_source_close = True
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["causes"][:2], ["source_io_error", "source_close_error"])
        self.assertFalse(world.calls)

    def test_runtime_observation_failure_precedes_distinct_close_failure(self):
        world = World()
        bad = MemoryStream(b"not-elf", close_error=True)
        world.files["/usr/bin/cc"] = bad
        code, raw, _ = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["causes"][:2], ["runtime_preflight_failed", "runtime_file_close_error"])

    def test_signal_refusal_is_exported_without_becoming_normal_success(self):
        world = World()
        original = world.wait_ready

        def interrupted(readers, writers, errors, timeout):
            if not world.calls and not writers:
                world.handlers[signal.SIGTERM](signal.SIGTERM, None)
            return original(readers, writers, errors, timeout)
        world.wait_ready = interrupted
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["causes"][0], "signal_term")
        self.assertFalse(world.calls)

    def test_late_write_failure_has_separate_fixed_publisher_diagnostic(self):
        code, raw, world = self.run_case(output=MemoryStream(write_limit=0))
        diagnostic = world.diagnostics.saved if world.diagnostics.closed else world.diagnostics.getvalue()
        self.assertEqual(code, 1)
        self.assertIn(b"publisher_export_write_error", diagnostic)
        self.assertLessEqual(len(diagnostic), 4096)

    def test_flush_then_close_failures_keep_distinct_order_without_exception_text(self):
        code, raw, world = self.run_case(output=MemoryStream(flush_error=True, close_error=True))
        diagnostic = world.diagnostics.saved if world.diagnostics.closed else world.diagnostics.getvalue()
        self.assertEqual(code, 1)
        self.assertIn(b"publisher_export_flush_error", diagnostic)
        self.assertIn(b"publisher_export_close_error", diagnostic)
        self.assertLess(diagnostic.index(b"publisher_export_flush_error"), diagnostic.index(b"publisher_export_close_error"))
        self.assertNotIn(b"synthetic", diagnostic)

    def test_complete_export_has_explicit_stdout_and_diagnostic_closure(self):
        output = MemoryStream()
        code, raw, world = self.run_case(output=output)
        self.assertEqual(code, 0)
        self.assertTrue(output.closed)
        self.assertTrue(world.diagnostics.closed)
        self.frame(raw)

    def test_stalled_request_consumes_one_deadline_without_launch_or_export(self):
        world = World()
        world.read_stall = True
        code, raw, world = self.run_case(world=world)
        self.assertEqual(code, 1)
        self.assertEqual(raw, b"")
        self.assertFalse(world.calls)
        self.assertGreaterEqual(world.now, 60)
        self.assertLess(world.now, 60.1)
        self.assertTrue(world.diagnostics.closed)

    def test_stalled_export_is_bounded_without_resetting_compile_deadline(self):
        world = World()
        world.write_stall = True
        code, raw, world = self.run_case(world=world)
        self.assertEqual(code, 1)
        self.assertEqual(raw, b"")
        self.assertEqual(len(world.calls), 1)
        self.assertGreaterEqual(world.now, 60)
        self.assertLess(world.now, 60.1)

    def test_live_compiler_is_signalled_once_per_group_phase_and_never_accepted(self):
        world = World(code=None)
        code, raw, world = self.run_case(world=world)
        self.assertEqual(code, 1)
        meta, _ = self.frame(raw)
        self.assertFalse(meta["compiler"]["reaped"])
        self.assertFalse(meta["elf"]["available"])
        self.assertEqual(world.kills, [(123, "TERM"), (123, "KILL")])
        self.assertTrue(world.child.stdout.closed and world.child.stderr.closed)
        self.assertIsNone(world.child.returncode)

    def test_direct_child_exit_cannot_stand_in_for_descendant_closure(self):
        world = World()
        world.descendant_live = True
        code, raw, world = self.run_case(world=world)
        self.assertEqual(code, 1)
        meta, _ = self.frame(raw)
        self.assertFalse(meta["descendants_reaped"])
        self.assertFalse(meta["elf"]["available"])
        self.assertEqual(world.child.returncode, 0)
        self.assertGreaterEqual(world.now, 55)
        self.assertLess(world.now, 60)
        self.assertIn((123, "KILL"), world.kills)

    def test_adopted_nonzero_status_is_distinct_from_original_compiler_status(self):
        world = World()
        pending = [(456, -15)]

        def wait_child():
            if pending:
                return pending.pop()
            raise ChildProcessError
        world.wait_child = wait_child
        code, raw, _ = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["returncode"], 0)
        self.assertTrue(meta["descendants_reaped"])
        self.assertIn("descendant_exit_nonzero", meta["causes"])
        self.assertFalse(meta["elf"]["available"])

    def test_capture_read_failure_keeps_prefix_with_unknown_discarded_remainder(self):
        world = World(stdout=b"prefix")
        original = world.child.stdout.read
        calls = []

        def read(size):
            if calls:
                raise OSError("secret exception text must not escape")
            calls.append(True)
            return original(size)
        world.child.stdout.read = read
        code, raw, _ = self.run_case(world=world)
        meta, parts = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(parts[0], b"prefix")
        self.assertEqual(meta["compiler"]["stdout"]["observed_bytes"], 6)
        self.assertIsNone(meta["compiler"]["stdout"]["discarded_bytes"])
        self.assertFalse(meta["compiler"]["stdout"]["eof"])
        self.assertTrue(meta["compiler"]["stderr"]["eof"])
        self.assertEqual(meta["causes"][0], "stdout_read_error")
        self.assertNotIn(b"secret exception", raw)

    def test_original_nonzero_status_precedes_both_distinct_pipe_close_failures(self):
        world = World(code=8)
        world.child.stdout.close_error = world.child.stderr.close_error = True
        code, raw, _ = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["returncode"], 8)
        self.assertEqual(meta["causes"][:3], ["compiler_exit_nonzero", "stdout_close_error", "stderr_close_error"])

    def test_signal_during_compiler_observation_refuses_even_if_compiler_returns_zero(self):
        world = World()
        original = world.process_factory

        def factory(*args, **kwargs):
            child = original(*args, **kwargs)
            world.handlers[signal.SIGTERM](signal.SIGTERM, None)
            return child
        world.process_factory = factory
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["returncode"], 0)
        self.assertEqual(meta["causes"][0], "signal_term")
        self.assertFalse(meta["elf"]["available"])
        self.assertEqual(world.kills, [(123, "TERM")])

    def test_wrong_machine_and_elf_class_are_refused(self):
        for offset, value in ((4, 1), (5, 2), (18, 3)):
            with self.subTest(offset=offset):
                world = World()
                payload = bytearray(elf())
                payload[offset] = value
                world.files["/work/engine"] = bytes(payload)
                code, raw, _ = self.run_case(world=world)
                meta, _ = self.frame(raw)
                self.assertEqual(code, 1)
                self.assertIn("elf_invalid", meta["causes"])

    def test_elf_stat_drift_refuses_retained_bytes(self):
        world = World()
        original = world.file_stat
        calls = []

        def file_stat(fd):
            result = original(fd)
            if world.opens[-1] == ("/work/engine", "rb"):
                calls.append(True)
                if len(calls) > 1:
                    result.st_mtime_ns += 1
            return result
        world.file_stat = file_stat
        code, raw, _ = self.run_case(world=world)
        meta, parts = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(parts[-1], b"")
        self.assertIn("elf_invalid", meta["causes"])

    def test_endless_overflow_is_stopped_in_time_to_export_original_prefix(self):
        world = World(code=None)
        original_ready = world.wait_ready
        terminated = []

        def read(size):
            return b"" if terminated else b"p" * size

        def kill_group(pid, kind):
            world.kills.append((pid, kind))
            terminated.append(True)
            world.child.returncode = -15 if kind == "TERM" else -9

        def wait_ready(readers, writers, errors, timeout):
            if readers:
                world.now += 0.1
            return original_ready(readers, writers, errors, timeout)
        world.child.stdout.read = read
        world.child.poll = lambda: world.child.returncode
        world.kill_group = kill_group
        world.wait_ready = wait_ready
        effects = world.kwargs()
        effects["kill_group"] = kill_group
        output = MemoryStream()
        code = publisher.run_publisher_v1(MemoryStream(request()), output, **effects)
        raw = output.saved if output.closed else output.getvalue()
        meta, parts = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(parts[0], b"p" * 1048576)
        self.assertEqual(meta["causes"][0], "stdout_overflow")
        self.assertEqual(meta["compiler"]["returncode"], -15)
        self.assertTrue(meta["compiler"]["stdout"]["eof"])
        self.assertEqual(world.kills, [(123, "TERM")])
        self.assertLess(world.now, 15)

    def test_read_crossing_cutoff_keeps_bytes_before_deadline_classification(self):
        world = World()
        original = world.child.stdout.read

        def read(size):
            data = original(size)
            if data:
                world.now = 56
            return data
        world.child.stdout.read = read
        code, raw, _ = self.run_case(world=world)
        meta, parts = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(parts[0], b"cc-out\n")
        self.assertEqual(meta["compiler"]["stdout"]["observed_bytes"], 7)

    def test_unstarted_channel_has_zero_observations_and_unknown_completion(self):
        code, raw, _ = self.run_case(b"invalid!")
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(meta["compiler"]["stdout"]["observed_bytes"], 0)
        self.assertFalse(meta["compiler"]["stdout"]["eof"])
        self.assertIsNone(meta["compiler"]["stdout"]["discarded_bytes"])

    def test_invalid_child_identity_never_signals_guessed_pid_and_closes_pipes(self):
        world = World()
        world.child.pid = 1
        code, raw, world = self.run_case(world=world)
        meta, _ = self.frame(raw)
        self.assertEqual(code, 1)
        self.assertEqual(world.kills, [])
        self.assertTrue(world.child.stdout.closed and world.child.stderr.closed)
        self.assertFalse(meta["compiler"]["reaped"])
        self.assertIn("compiler_identity_invalid", meta["causes"])


if __name__ == "__main__":
    unittest.main()
