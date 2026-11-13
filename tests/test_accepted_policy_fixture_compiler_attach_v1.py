"""Controlled stdcopy streams and unit temp files only; no Docker socket/API."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


def frame(stream, payload):
    return bytes((stream, 0, 0, 0)) + struct.pack("!I", len(payload)) + payload


class Duplex:
    def __init__(self, data=b"", *, chunk=None):
        self.data = data
        self.offset = 0
        self.chunk = chunk
        self.sent = []
        self.shutdown = False
        self.facts = {"closed": False}
        self.requests = []

    def read(self, count):
        self.requests.append(count)
        amount = min(count, self.chunk or count)
        result = self.data[self.offset:self.offset + amount]
        self.offset += len(result)
        return result

    def sendall(self, data):
        self.sent.append(data)

    def shutdown_write(self):
        self.shutdown = True

    def close(self):
        self.facts["closed"] = True


class RepeatedDuplex(Duplex):
    """Finite synthetic wire, with no whole declared-payload allocation."""
    def __init__(self, pieces):
        super().__init__()
        self.pieces = list(pieces)
        self.index = 0
        self.part_offset = 0

    def read(self, count):
        self.requests.append(count)
        if self.index == len(self.pieces):
            return b""
        part = self.pieces[self.index]
        length = part if type(part) is int else len(part)
        amount = min(count, length - self.part_offset)
        result = b"x" * amount if type(part) is int else part[self.part_offset:self.part_offset + amount]
        self.offset += amount
        self.part_offset += amount
        if self.part_offset == length:
            self.index += 1
            self.part_offset = 0
        return result


class FaultFile:
    def __init__(self, file, fault):
        self.file, self.fault = file, fault

    def write(self, data):
        if self.fault == "write":
            self.file.write(data[:2])
            raise OSError("untrusted detail must never become a cause")
        if self.fault == "short":
            return self.file.write(data[:2])
        return self.file.write(data)

    def flush(self):
        if self.fault == "flush":
            raise OSError("untrusted")
        self.file.flush()

    def fileno(self):
        return self.file.fileno()

    def close(self):
        self.file.close()
        if self.fault == "close":
            raise OSError("untrusted")


class CompilerAttachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name).resolve()

    def attach(self, data=b"", *, chunk=None):
        duplex = Duplex(data, chunk=chunk)
        return compiler._CompilerAttachV1(duplex, self.output), duplex

    def test_interleaved_short_frames_expose_only_stdout(self):
        attach, duplex = self.attach(frame(1, b"abc") + frame(2, b"warning") + frame(1, b"xyz"), chunk=1)
        self.assertEqual(attach.read(2), b"ab")
        self.assertEqual(attach.read(6), b"cxyz")
        self.assertEqual(attach.read(1), b"")
        attach.close()
        self.assertEqual((self.output / "client.stderr.original").read_bytes(), b"warning")
        self.assertEqual((self.output / "attach.headers.original").read_bytes(), frame(1, b"abc")[:8] + frame(2, b"warning")[:8] + frame(1, b"xyz")[:8])
        self.assertTrue(duplex.facts["closed"])

    def test_invalid_header_refuses_with_facts(self):
        attach, _ = self.attach(frame(3, b"bad"))
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.read(1)
        self.assertIs(caught.exception.facts, attach.facts)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()

    def test_truncated_payload_returns_prefix_before_sticky_failure(self):
        attach, _ = self.attach(bytes((1, 0, 0, 0)) + struct.pack("!I", 5) + b"ab", chunk=1)
        self.assertEqual(attach.read(5), b"ab")
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()

    def test_boundary_eof_marks_both_channels_and_completion_requires_close(self):
        attach, _ = self.attach()
        self.assertEqual(attach.read(1), b"")
        self.assertTrue(attach.facts.get("stdout_eof"))
        self.assertTrue(attach.facts.get("stderr_eof"))
        self.assertFalse(attach.facts.get("complete"))
        attach.close()
        self.assertTrue(attach.facts.get("complete"))

    def test_empty_prefix_files_are_exclusive_persisted_and_hashed(self):
        attach, _ = self.attach()
        attach.read(1)
        attach.close()
        for name in ("attach.headers.original", "client.stderr.original"):
            path = self.output / name
            self.assertTrue(path.exists(), "close must preserve even a zero-byte original")
            self.assertEqual(path.read_bytes(), b"")

    def test_send_halfclose_and_close_delegate_without_api_dispatch(self):
        attach, duplex = self.attach()
        attach.sendall(b"request")
        attach.shutdown_write()
        self.assertEqual(attach.read(1), b"")
        attach.close()
        self.assertEqual(duplex.sent, [b"request"])
        self.assertTrue(duplex.shutdown and duplex.facts["closed"])

    def test_production_caps_are_literal(self):
        self.assertEqual((compiler._CompilerAttachV1.STDOUT_LIMIT,
            compiler._CompilerAttachV1.STDERR_LIMIT,
            compiler._CompilerAttachV1.HEADER_LIMIT), (18939904, 1048576, 65536))

    def test_single_frame_oversize_never_reads_payload(self):
        for stream, size in ((1, 18939905), (2, 1048577)):
            with self.subTest(stream=stream), tempfile.TemporaryDirectory() as tmp:
                duplex = Duplex(bytes((stream, 0, 0, 0)) + struct.pack("!I", size) + b"unobserved")
                attach = compiler._CompilerAttachV1(duplex, Path(tmp).resolve())
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    attach.read(1)
                self.assertEqual(caught.exception.causes, ["attach_frame_declaration_bound"])
                self.assertEqual(duplex.offset, 8)
                self.assertEqual(attach.facts["stdout" if stream == 1 else "stderr"]["observed_bytes"], 0)
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.close()
                self.assertEqual((Path(tmp) / "attach.headers.original").stat().st_size, 8)

    def test_aggregate_stdout_overflow_observes_exactly_one_excess(self):
        duplex = RepeatedDuplex([frame(1, b"")[:4] + struct.pack("!I", 18939904),
            18939904, frame(1, b"ab")[:8], b"ab", b"unobserved"])
        attach = compiler._CompilerAttachV1(duplex, self.output)
        used = 0
        while used < 18939904:
            used += len(attach.read(65536))
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.read(1)
        self.assertEqual(caught.exception.causes[0], "attach_stdout_overflow")
        self.assertEqual((used, duplex.offset), (18939904, 18939904 + 16 + 1))
        self.assertEqual(attach.facts["stdout"]["observed_bytes"], 18939905)
        self.assertIsNone(attach.facts["stdout"]["discarded_bytes"])
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()
        self.assertLessEqual(max(duplex.requests), 65536)

    def test_aggregate_stderr_overflow_preserves_only_prefix(self):
        duplex = RepeatedDuplex([frame(2, b"")[:4] + struct.pack("!I", 1048576),
            1048576, frame(2, b"ab")[:8], b"ab"])
        attach = compiler._CompilerAttachV1(duplex, self.output)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()
        path = self.output / "client.stderr.original"
        self.assertEqual(path.stat().st_size, 1048576)
        self.assertEqual(duplex.offset, 1048576 + 17)
        self.assertEqual(attach.facts["stderr"]["observed_bytes"], 1048577)
        self.assertFalse(attach.facts["stderr_eof"])

    def test_header_limit_and_zero_frames_are_finite(self):
        attach, duplex = self.attach(frame(1, b"") * 8192 + b"extra")
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.read(1)
        self.assertEqual(caught.exception.causes[0], "attach_headers_overflow")
        self.assertEqual(duplex.offset, 65537)
        self.assertEqual(attach.facts["headers_retained_bytes"], 65536)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()

    def test_exact_header_limit_then_boundary_eof_is_clean(self):
        attach, _ = self.attach(frame(2, b"") * 8192)
        self.assertEqual(attach.read(1), b"")
        attach.close()
        self.assertEqual(attach.facts["frames"], 8192)
        self.assertTrue(attach.facts["complete"])

    def test_partial_header_and_reserved_bytes_are_retained(self):
        for raw, cause in ((b"\1\0\0", "attach_header_truncated"),
                           (b"\1\1\0\0\0\0\0\0", "attach_header_invalid")):
            with self.subTest(cause=cause), tempfile.TemporaryDirectory() as tmp:
                attach = compiler._CompilerAttachV1(Duplex(raw, chunk=1), Path(tmp).resolve())
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    attach.read(1)
                self.assertEqual(caught.exception.causes[0], cause)
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.close()
                self.assertEqual((Path(tmp) / "attach.headers.original").read_bytes(), raw)

    def test_bad_read_counts_refuse_without_wire_read(self):
        for value in (True, 0, -1, 65537, 1.0):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                duplex = Duplex()
                attach = compiler._CompilerAttachV1(duplex, Path(tmp).resolve())
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.read(value)
                self.assertEqual(duplex.requests, [])
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.close()

    def test_prefix_identity_and_persistence_facts(self):
        attach, _ = self.attach(frame(2, b"evidence"))
        self.assertEqual(attach.read(1), b"")
        attach.close()
        record = attach.facts["files"]["client.stderr.original"]
        self.assertEqual((record["size_bytes"], record["persisted_bytes"]), (8, 8))
        self.assertEqual(record["sha256"], hashlib.sha256(b"evidence").hexdigest())
        self.assertTrue(all(record[key] for key in ("flush_completed", "fsync_completed", "close_completed")))

    def test_existing_prefix_file_is_never_overwritten_and_duplex_closes(self):
        path = self.output / "client.stderr.original"
        path.write_bytes(b"original")
        duplex = Duplex()
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            compiler._CompilerAttachV1(duplex, self.output)
        self.assertEqual(path.read_bytes(), b"original")
        self.assertTrue(duplex.facts["closed"])
        self.assertTrue(caught.exception.facts["files"]["attach.headers.original"]["close_completed"])

    def test_close_without_wire_eof_never_reports_complete(self):
        attach, duplex = self.attach(frame(1, b"pending"))
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.close()
        self.assertEqual(caught.exception.causes[0], "attach_incomplete")
        self.assertFalse(attach.facts["complete"])
        self.assertTrue(duplex.facts["closed"])

    def test_read_contract_error_and_duplex_close_error_are_distinct(self):
        class Broken(Duplex):
            def read(self, count):
                return b"x" * (count + 1)
            def close(self):
                self.facts["closed"] = True
                raise compiler.FixtureCompilerError("docker_endpoint_drift")
        attach = compiler._CompilerAttachV1(Broken(), self.output)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.close()
        self.assertEqual(caught.exception.causes[0], "attach_read_contract")
        self.assertIn("docker_endpoint_drift", caught.exception.causes)
        self.assertTrue(attach.facts["duplex_closed"])
        self.assertFalse(attach.facts["duplex_close_completed"])

    def fault_attach(self, fault):
        original = Path.open
        def opened(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            return FaultFile(file, fault) if path.name == "client.stderr.original" else file
        with mock.patch.object(Path, "open", opened):
            return self.attach(frame(2, b"evidence"))

    def test_write_exception_keeps_unknown_extent_and_fixed_cause(self):
        attach, duplex = self.fault_attach("write")
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.close()
        self.assertEqual(caught.exception.causes[0], "attach_prefix_write")
        row = attach.facts["files"]["client.stderr.original"]
        self.assertTrue(row["write_extent_unknown"])
        self.assertIsNone(row["size_bytes"])
        self.assertIsNone(row["sha256"])
        self.assertEqual(row["written_bytes"], 0)
        self.assertEqual((self.output / "client.stderr.original").read_bytes(), b"ev")
        self.assertTrue(duplex.facts["closed"])

    def test_short_write_records_confirmed_prefix_without_retry(self):
        attach, _ = self.fault_attach("short")
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.close()
        self.assertEqual(caught.exception.causes[0], "attach_prefix_short_write")
        row = attach.facts["files"]["client.stderr.original"]
        self.assertEqual((row["written_bytes"], row["size_bytes"]), (2, 2))
        self.assertEqual(row["sha256"], hashlib.sha256(b"ev").hexdigest())

    def test_short_header_summary_matches_confirmed_original_prefix(self):
        original = Path.open
        def opened(path, *args, **kwargs):
            file = original(path, *args, **kwargs)
            return FaultFile(file, "short") if path.name == "attach.headers.original" else file
        with mock.patch.object(Path, "open", opened):
            attach, _ = self.attach(frame(1, b"payload"))
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()
        actual = (self.output / "attach.headers.original").read_bytes()
        record = attach.facts["files"]["attach.headers.original"]
        self.assertEqual(actual, frame(1, b"payload")[:2])
        self.assertEqual(attach.facts["headers_observed_bytes"], 8)
        self.assertEqual(attach.facts["headers_retained_bytes"], len(actual))
        self.assertEqual(record["size_bytes"], len(actual))
        self.assertEqual(record["sha256"], hashlib.sha256(actual).hexdigest())

    def test_short_stderr_summary_matches_confirmed_original_prefix(self):
        attach, _ = self.fault_attach("short")
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.read(1)
        with self.assertRaises(compiler.FixtureCompilerError):
            attach.close()
        actual = (self.output / "client.stderr.original").read_bytes()
        record = attach.facts["files"]["client.stderr.original"]
        self.assertEqual(actual, b"ev")
        self.assertEqual(attach.facts["stderr"]["observed_bytes"], len(b"evidence"))
        self.assertEqual(attach.facts["stderr"]["retained_bytes"], len(actual))
        self.assertEqual(record["size_bytes"], len(actual))
        self.assertEqual(record["sha256"], hashlib.sha256(actual).hexdigest())

    def test_unreturned_write_extent_is_unknown_in_each_retained_summary(self):
        original = Path.open
        for target in ("attach.headers.original", "client.stderr.original"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp).resolve()
                def opened(path, *args, **kwargs):
                    file = original(path, *args, **kwargs)
                    return FaultFile(file, "write") if path.name == target else file
                with mock.patch.object(Path, "open", opened):
                    attach = compiler._CompilerAttachV1(Duplex(frame(2, b"evidence")), output)
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.read(1)
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.close()
                record = attach.facts["files"][target]
                self.assertEqual((output / target).stat().st_size, 2)
                self.assertTrue(record["write_extent_unknown"])
                self.assertIsNone(record["size_bytes"])
                self.assertIsNone(record["sha256"])
                summary = (attach.facts["headers_retained_bytes"] if target == "attach.headers.original"
                           else attach.facts["stderr"]["retained_bytes"])
                self.assertIsNone(summary, "a returned-write total cannot describe an unreturned extent")

    def test_flush_and_close_failures_do_not_skip_other_cleanup(self):
        for fault in ("flush", "close"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                self.output = Path(tmp).resolve()
                attach, duplex = self.fault_attach(fault)
                self.assertEqual(attach.read(1), b"")
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    attach.close()
                self.assertEqual(caught.exception.causes[0], "attach_prefix_" + fault)
                self.assertTrue(duplex.facts["closed"])
                self.assertTrue(attach.facts["files"]["attach.headers.original"]["close_completed"])
                self.assertFalse(attach.facts["complete"])

    def test_fsync_failure_is_sticky_and_close_is_attempted_once(self):
        attach, duplex = self.attach()
        self.assertEqual(attach.read(1), b"")
        with mock.patch.object(compiler.os, "fsync", side_effect=OSError("untrusted")) as sync:
            with self.assertRaises(compiler.FixtureCompilerError) as caught:
                attach.close()
            with self.assertRaises(compiler.FixtureCompilerError):
                attach.close()
        self.assertEqual(sync.call_count, 2)
        self.assertEqual(caught.exception.causes, ["attach_prefix_fsync"])
        self.assertTrue(duplex.facts["closed"])
        self.assertTrue(all(row["close_completed"] for row in attach.facts["files"].values()))

    def test_unopened_file_has_no_original_size_or_hash_claim(self):
        (self.output / "client.stderr.original").write_bytes(b"held")
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            compiler._CompilerAttachV1(Duplex(), self.output)
        row = caught.exception.facts["files"]["client.stderr.original"]
        self.assertFalse(row.get("open_completed"))
        self.assertIsNone(row["size_bytes"])
        self.assertIsNone(row["sha256"])

    def test_transport_error_after_stdout_returns_prefix_then_close_refuses(self):
        class Broken(Duplex):
            def read(self, count):
                if self.offset == len(self.data):
                    raise compiler.FixtureCompilerError("docker_data_deadline")
                return super().read(count)
        attach = compiler._CompilerAttachV1(Broken(frame(1, b"prefix")), self.output)
        self.assertEqual(attach.read(9), b"prefix")
        with self.assertRaises(compiler.FixtureCompilerError) as caught:
            attach.close()
        self.assertEqual(caught.exception.causes[0], "docker_data_deadline")
        self.assertFalse(attach.facts["complete"])

    def test_failed_send_and_shutdown_use_sticky_fixed_causes(self):
        class Broken(Duplex):
            def sendall(self, data):
                raise OSError("untrusted")
            def shutdown_write(self):
                raise OSError("untrusted")
        for method, args, cause in (("sendall", (b"request",), "attach_send"),
                                    ("shutdown_write", (), "attach_shutdown")):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as tmp:
                attach = compiler._CompilerAttachV1(Broken(), Path(tmp).resolve())
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    getattr(attach, method)(*args)
                self.assertEqual(caught.exception.causes[0], cause)
                with self.assertRaises(compiler.FixtureCompilerError):
                    attach.close()


if __name__ == "__main__":
    unittest.main()
