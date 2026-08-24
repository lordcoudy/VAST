from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_archive import (  # noqa: E402
    PairArchiveError,
    build_pair_archive,
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


class MutatingStore(FakeStore):
    def __init__(self, pair_dir: Path) -> None:
        super().__init__()
        self.pair_dir = pair_dir

    def upload_and_verify(self, path: Path, *, remote_name: str) -> dict:
        result = super().upload_and_verify(path, remote_name=remote_name)
        (self.pair_dir / "manifest.json").write_text(
            '{"accepted":false}\n', encoding="utf-8"
        )
        return result


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
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )
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

    def test_rejects_pair_without_bound_acceptance_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0003"
            pair_dir.mkdir(parents=True)
            (pair_dir / "frames.csv").write_text("frame\n1\n", encoding="utf-8")

            with self.assertRaisesRegex(PairArchiveError, "acceptance marker"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="pair-0003.tar.zst",
                    store=FakeStore(),
                )

            self.assertTrue(pair_dir.is_dir())

    def test_rejects_noncanonical_pair_namespace_and_remote_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "other" / "pair-0004"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(PairArchiveError, "pairs namespace"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="different.tar.zst",
                    store=FakeStore(),
                )

            self.assertTrue(pair_dir.is_dir())

    def test_pair_mutated_after_readback_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0005"
            pair_dir.mkdir(parents=True)
            marker = pair_dir / "manifest.json"
            marker.write_text('{"accepted":true}\n', encoding="utf-8")
            (pair_dir / "raw.bin").write_bytes(b"accepted evidence")

            with (
                mock.patch("publication_archive.shutil.rmtree") as remove_tree,
                self.assertRaisesRegex(PairArchiveError, "changed after archiving"),
            ):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="pair-0005.tar.zst",
                    store=MutatingStore(pair_dir),
                )

            remove_tree.assert_not_called()
            self.assertTrue(pair_dir.is_dir())
            self.assertFalse(json.loads(marker.read_text(encoding="utf-8"))["accepted"])

    def test_cleanup_only_removes_identity_bound_quarantine_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0006"
            spool = run_root / "spool"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )
            (pair_dir / "raw.bin").write_bytes(b"accepted evidence")
            removed: list[Path] = []
            real_rmtree = shutil.rmtree

            def checked_remove(path: Path) -> None:
                candidate = Path(path)
                removed.append(candidate)
                self.assertEqual(candidate.parent, (run_root / "pairs").resolve())
                self.assertTrue(candidate.name.startswith(".pair-0006.verified-delete."))
                self.assertNotEqual(candidate, pair_dir.resolve())
                self.assertNotEqual(candidate, run_root.resolve())
                self.assertNotEqual(candidate, Path.cwd().resolve())
                real_rmtree(candidate)

            with mock.patch(
                "publication_archive.shutil.rmtree", side_effect=checked_remove
            ):
                result = drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=spool,
                    remote_name="pair-0006.tar.zst",
                    store=FakeStore(),
                )

            self.assertEqual(len(removed), 1)
            self.assertTrue(result["pair_directory_deleted"])

    def test_reparse_pair_is_rejected_before_upload_or_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0007"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )
            store = FakeStore()

            with (
                mock.patch(
                    "publication_archive._is_reparse_point",
                    side_effect=lambda path: Path(path) == pair_dir.resolve(),
                ),
                mock.patch("publication_archive.shutil.rmtree") as remove_tree,
                self.assertRaisesRegex(PairArchiveError, "reparse|junction|symlink"),
            ):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="pair-0007.tar.zst",
                    store=store,
                )

            self.assertEqual(store.uploaded, [])
            remove_tree.assert_not_called()
            self.assertTrue(pair_dir.is_dir())

    def test_pair_cleanup_target_must_not_be_the_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0008"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )
            store = FakeStore()

            with (
                mock.patch(
                    "publication_archive.Path.cwd",
                    return_value=pair_dir.resolve(),
                ),
                self.assertRaisesRegex(PairArchiveError, "current directory"),
            ):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="pair-0008.tar.zst",
                    store=store,
                )

            self.assertEqual(store.uploaded, [])
            self.assertTrue(pair_dir.is_dir())

    def test_remote_name_must_be_bound_to_exact_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0009"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(PairArchiveError, "bound to the exact pair"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "spool",
                    remote_name="pair-9999.tar.zst",
                    store=FakeStore(),
                )

            self.assertTrue(pair_dir.is_dir())

    def test_spool_must_be_the_dedicated_run_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir = run_root / "pairs" / "pair-0010"
            pair_dir.mkdir(parents=True)
            (pair_dir / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )

            with self.assertRaisesRegex(PairArchiveError, "dedicated run spool"):
                drain_pair_to_store(
                    pair_dir=pair_dir,
                    run_root=run_root,
                    spool_root=run_root / "arbitrary-spool",
                    remote_name="pair-0010.tar.zst",
                    store=FakeStore(),
                )

            self.assertTrue(pair_dir.is_dir())

    def test_archive_source_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_pair = root / "real-pair"
            real_pair.mkdir()
            (real_pair / "manifest.json").write_text(
                '{"accepted":true}\n', encoding="utf-8"
            )
            alias = root / "pair-alias"
            try:
                alias.symlink_to(real_pair, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            archive = root / "pair-alias.tar.zst"

            with self.assertRaisesRegex(
                PairArchiveError, "symlink|junction|reparse|alias"
            ):
                build_pair_archive(pair_dir=alias, archive_path=archive)

            self.assertTrue(real_pair.is_dir())
            self.assertTrue(alias.is_symlink())
            self.assertFalse(archive.exists())

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
