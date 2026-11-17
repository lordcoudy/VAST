"""Real buffered I/O fault reproductions; no native component execution."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
from tests.fixtures import accepted_policy_fixture_compiler_recovery_v1 as f2
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket, reply


class PartialFaultRaw(io.RawIOBase):
    def __init__(self, file):
        super().__init__()
        self.file = file

    def writable(self):
        return True

    def write(self, data):
        self.file.write(bytes(data[:1]))
        raise OSError("controlled partial underlying write")

    def fileno(self):
        return self.file.fileno()

    def close(self):
        try:
            super().close()
        finally:
            self.file.close()


class OriginalWriterExtentTests(unittest.TestCase):
    def check_partial_underlying_write(self, writer):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "record.original.json"
            original_open = Path.open
            streams = []

            def controlled_open(target, mode="r", buffering=-1, *args, **kwargs):
                if target != path or mode != "xb":
                    return original_open(target, mode, buffering, *args, **kwargs)
                raw = PartialFaultRaw(original_open(target, mode, buffering=0))
                stream = raw if buffering == 0 else io.BufferedWriter(raw)
                streams.append(stream)
                return stream

            try:
                with patch.object(Path, "open", controlled_open):
                    with self.assertRaises(Exception) as caught:
                        writer(path)
                facts = caught.exception.facts
                self.assertTrue(facts["write_extent_unknown"], facts)
                self.assertFalse(facts["complete"])
                self.assertFalse(facts["fsync_completed"])
                self.assertGreater(path.stat().st_size, 0)
                self.assertLess(path.stat().st_size, len(b'{"value":"controlled record"}'))
            finally:
                for stream in streams:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def test_c_record_reports_unknown_extent_after_partial_underlying_write(self):
        self.check_partial_underlying_write(
            lambda path: c.write_record_v1(path, {"value": "controlled record"}))

    def test_f2_record_reports_unknown_extent_after_partial_underlying_write(self):
        self.check_partial_underlying_write(
            lambda path: f2._write_json(path, {"value": "controlled record"}))

    def check_transport_partial_write(self, role):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / ("RPC01." + role + ".original")
            original_open = Path.open
            streams = []

            def controlled_open(target, mode="r", buffering=-1, *args, **kwargs):
                if target != path or mode != "xb":
                    return original_open(target, mode, buffering, *args, **kwargs)
                raw = PartialFaultRaw(original_open(target, mode, buffering=0))
                stream = raw if buffering == 0 else io.BufferedWriter(raw)
                streams.append(stream)
                return stream

            client = compiler._DockerClientV1(root, 20_000_000_000,
                clock=lambda: 1_000_000_000, socket_factory=lambda: FakeSocket(reply()))
            try:
                with patch.object(Path, "open", controlled_open), \
                        patch.object(client, "_observe_endpoint", return_value=((1, 2, 0, 0, 0o140660, 17),)):
                    with self.assertRaises(compiler.FixtureCompilerError):
                        client.request("GET", "/info")
                row = client.facts["rpc"][0]
                self.assertTrue(row[role + "_write_extent_unknown"], row)
                self.assertFalse(row[role + "_persisted"])
                self.assertFalse(row["complete"])
                self.assertGreater(path.stat().st_size, 0)
            finally:
                for stream in streams:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def test_shared_request_reports_unknown_extent_after_partial_underlying_write(self):
        self.check_transport_partial_write("request")

    def test_shared_reply_reports_unknown_extent_after_partial_underlying_write(self):
        self.check_transport_partial_write("reply")


if __name__ == "__main__":
    unittest.main()
