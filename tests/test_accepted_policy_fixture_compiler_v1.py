"""Portable wire/ownership faults; these do not qualify an actual runtime."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler


def export_bytes(*, elf=b"fixture ELF bytes", stdout=b"compiler text", stderr=b"", code=0):
    def member(raw):
        return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "eof": True, "observed_bytes": len(raw), "discarded_bytes": 0}
    header = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_export_v1",
        "source": {"size_bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()},
        "compiler": {"returncode": code, "started": True, "reaped": True,
            "stdout": member(stdout), "stderr": member(stderr)},
        "elf": {"size_bytes": len(elf), "sha256": hashlib.sha256(elf).hexdigest(), "available": bool(elf)},
        "causes": [], "descendants_reaped": True}
    raw = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii")
    return b"VASTCE1\n" + struct.pack(">I", len(raw)) + raw + stdout + stderr + elf


def writer_fault(filename, *, write="normal", close=False):
    """Fault only a declared output's external I/O, after real tiny writes/closes."""
    original_open = Path.open
    class Writer:
        def __init__(self, file):
            self.file = file
        def __enter__(self):
            return self
        def __exit__(self, *error):
            self.file.close()
            if close:
                raise ValueError("synthetic reporting fault after real close")
        def write(self, data):
            if write == "raise":
                raise OSError("synthetic write fault")
            if write in ("short", "partial_raise"):
                self.file.write(data[:3])
                if write == "partial_raise":
                    raise OSError("synthetic fault after real prefix write")
                return 3
            return self.file.write(data)
        def flush(self):
            return self.file.flush()
        def fileno(self):
            return self.file.fileno()
    def open_output(path, *args, **kwargs):
        file = original_open(path, *args, **kwargs)
        return Writer(file) if path.name == filename and args == ("xb",) else file
    return patch.object(Path, "open", new=open_output)


class CompilerExportTests(unittest.TestCase):
    def test_exact_binary_frame_keeps_compiler_text_out_of_elf(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            result = compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"compiler text")
            self.assertEqual((root / "engine.unaccepted").read_bytes(), b"fixture ELF bytes")
            self.assertTrue(result["complete"])
            self.assertFalse((root / "engine").exists())

    def test_truncation_retains_exact_prefix_and_no_accepted_elf(self):
        raw = export_bytes()[:-3]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with self.assertRaises(compiler.FixtureCompilerError) as caught:
                compiler.capture_export_v1(io.BytesIO(raw).read, root)
            self.assertIn("export_truncated", caught.exception.causes)
            self.assertEqual((root / "engine.unaccepted").read_bytes(), b"fixture ELF by")
            self.assertFalse((root / "engine").exists())

    def test_bad_hash_retains_original_member_and_refuses(self):
        raw = export_bytes().replace(b"compiler text", b"compiler TEXT")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with self.assertRaises(compiler.FixtureCompilerError):
                compiler.capture_export_v1(io.BytesIO(raw).read, root)
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"compiler TEXT")
            self.assertFalse((root / "engine").exists())

    def test_oversized_metadata_is_refused_before_payload_read_or_write(self):
        reads = []
        raw = io.BytesIO(b"VASTCE1\n" + struct.pack(">I", 65525))
        def read(count):
            reads.append(count)
            return raw.read(count)
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(compiler.FixtureCompilerError):
                compiler.capture_export_v1(read, Path(name).resolve(strict=True))
            self.assertEqual(reads, [12])
            self.assertEqual((Path(name) / "export.prefix.original").read_bytes(),
                b"VASTCE1\n" + struct.pack(">I", 65525))

    def test_partial_header_original_survives_truncation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            raw = export_bytes()[:30]
            with self.assertRaises(compiler.FixtureCompilerError) as caught:
                compiler.capture_export_v1(io.BytesIO(raw).read, root)
            self.assertIn("export_truncated", caught.exception.causes)
            self.assertEqual((root / "export.prefix.original").read_bytes(), raw)

    def test_short_write_reports_confirmed_prefix_separately_from_observed_input(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("compiler.stdout.original", write="short"):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            actual = (root / "compiler.stdout.original").read_bytes()
            self.assertEqual(actual, b"com")
            self.assertEqual(caught.exception.causes[0], "export_member_short_write")
            row = caught.exception.facts["members"]["stdout"]
            self.assertEqual(row["size_bytes"], len(actual))
            self.assertEqual(row["sha256"], hashlib.sha256(actual).hexdigest())
            self.assertEqual(row["observed_bytes"], len(b"compiler text"))
            self.assertEqual(row["observed_sha256"], hashlib.sha256(b"compiler text").hexdigest())
            self.assertFalse((root / "engine").exists())

    def test_write_exception_marks_unreturned_persisted_extent_unavailable(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("compiler.stdout.original", write="partial_raise"):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"com")
            self.assertEqual(caught.exception.causes[0], "export_OSError")
            row = caught.exception.facts["members"]["stdout"]
            self.assertIsNone(row["size_bytes"])
            self.assertIsNone(row["sha256"])
            self.assertFalse(row["persisted"])
            self.assertEqual(row["observed_bytes"], len(b"compiler text"))
            self.assertFalse((root / "engine").exists())

    def test_header_write_primary_survives_distinct_close_reporting_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("export.header.original", write="raise", close=True):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            self.assertEqual(caught.exception.causes[0], "export_OSError")
            self.assertIn("export_close_ValueError", caught.exception.causes[1:])
            self.assertTrue((root / "export.prefix.original").is_file())
            self.assertFalse((root / "engine").exists())

    def test_read_primary_survives_distinct_member_close_reporting_failure(self):
        raw = io.BytesIO(export_bytes())
        calls = 0
        def read(count):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("synthetic member read fault")
            return raw.read(count)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("compiler.stdout.original", close=True):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(read, root)
            self.assertEqual(calls, 3)
            self.assertEqual(caught.exception.causes[0], "export_OSError")
            self.assertIn("export_close_ValueError", caught.exception.causes[1:])
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"")
            self.assertFalse((root / "engine").exists())

    def test_persistence_primary_survives_distinct_close_reporting_failure(self):
        original_fsync = compiler.os.fsync
        calls = 0
        def fsync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic member fsync fault")
            return original_fsync(fd)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("compiler.stdout.original", close=True), patch.object(compiler.os, "fsync", new=fsync):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            self.assertEqual(caught.exception.causes[0], "export_persistence_OSError")
            self.assertIn("export_close_ValueError", caught.exception.causes[1:])
            self.assertFalse(caught.exception.facts["members"]["stdout"]["persisted"])
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"compiler text")
            self.assertFalse((root / "engine").exists())

    def test_close_failure_does_not_relabel_completed_fsync_as_stream_closure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("compiler.stdout.original", close=True):
                with self.assertRaises(compiler.FixtureCompilerError) as caught:
                    compiler.capture_export_v1(io.BytesIO(export_bytes()).read, root)
            self.assertEqual(caught.exception.causes[0], "export_close_ValueError")
            row = caught.exception.facts["members"]["stdout"]
            self.assertTrue(row["persisted"])
            self.assertIs(row.get("close_completed"), False)
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"compiler text")
            self.assertFalse((root / "engine").exists())

    def test_original_refusal_survives_prefix_write_and_close_faults(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            with writer_fault("export.prefix.original", write="raise", close=True):
                with self.assertRaises(BaseException) as caught:
                    compiler.capture_export_v1(io.BytesIO(b"BADMAGIC" + struct.pack(">I", 1)).read, root)
            self.assertIsInstance(caught.exception, compiler.FixtureCompilerError)
            self.assertEqual(caught.exception.causes[0], "export_magic")
            self.assertIn("export_prefix_persistence_OSError", caught.exception.causes[1:])
            self.assertIn("export_prefix_close_ValueError", caught.exception.causes[1:])
            self.assertFalse(caught.exception.facts["header_prefix_persisted"])
            self.assertIs(caught.exception.facts.get("header_prefix_close_completed"), False)
            self.assertFalse((root / "engine").exists())


if __name__ == "__main__":
    unittest.main()
