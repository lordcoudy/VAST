from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_archive import (  # noqa: E402
    PairArchiveError,
    drain_pair_to_store,
)


class FakeStore:
    def __init__(self, *, corrupt: bool = False) -> None:
        self.corrupt = corrupt
        self.uploaded: list[str] = []

    def upload_and_verify(self, path: Path, *, remote_name: str) -> dict:
        self.uploaded.append(remote_name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.corrupt:
            digest = "0" * 64
        return {
            "status": "uploaded_and_verified",
            "remote_name": remote_name,
            "size_bytes": path.stat().st_size,
            "sha256": digest,
        }


class PublicationArchiveTests(unittest.TestCase):
    def test_verified_upload_deletes_pair_and_local_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0001"
            spool = run_root / "spool"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text('{"accepted":true}\n', encoding="utf-8")
            (pair_dir / "frames.csv").write_text("schema_version\n2\n", encoding="utf-8")
            store = FakeStore()

            result = drain_pair_to_store(
                pair_dir=pair_dir,
                run_root=run_root,
                spool_root=spool,
                remote_name="pair-0001.tar.zst",
                store=store,
            )

            self.assertEqual(result["status"], "uploaded_verified_local_deleted")
            self.assertFalse(pair_dir.exists())
            self.assertFalse((spool / "pair-0001.tar.zst").exists())
            self.assertEqual(store.uploaded, ["pair-0001.tar.zst"])
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")

    def test_integrity_mismatch_preserves_pair_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0002"
            spool = run_root / "spool"
            pair_dir.mkdir(parents=True)
            (pair_dir / "raw.bin").write_bytes(b"critical evidence")
            store = FakeStore(corrupt=True)

            with self.assertRaisesRegex(PairArchiveError, "verification"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=spool,
                    remote_name="pair-0002.tar.zst",
                    store=store,
                )

            self.assertTrue(pair_dir.is_dir())
            self.assertTrue((spool / "pair-0002.tar.zst").is_file())

    def test_pair_must_be_below_exact_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pair_dir = root / "outside"
            pair_dir.mkdir()
            with self.assertRaisesRegex(PairArchiveError, "inside run_root"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=root / "run",
                    spool_root=root / "run" / "spool",
                    remote_name="pair.tar.zst",
                    store=FakeStore(),
                )
            self.assertTrue(pair_dir.exists())


if __name__ == "__main__":
    unittest.main()
