"""Portable wire/ownership faults; these do not qualify an actual runtime."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
