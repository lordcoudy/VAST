from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_owned_staging_cleanup_v1 import (  # noqa: E402
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
    OwnedStagingFileV1,
    retire_owned_runtime_output_v1,
)


def is_wsl_drvfs_workspace() -> bool:
    if os.name != "posix" or not Path("/proc/self/mountinfo").is_file():
        return False
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(
            encoding="ascii"
        )
        mount_lines = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return False
    if "microsoft" not in release.lower():
        return False
    root = ROOT.resolve()
    for line in mount_lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mountpoint = Path(fields[4].replace("\\040", " "))
        except (IndexError, ValueError):
            continue
        if root != mountpoint and mountpoint not in root.parents:
            continue
        filesystem = fields[separator + 1]
        super_options = fields[separator + 3 :]
        if filesystem == "drvfs" or (
            filesystem == "9p"
            and any("aname=drvfs" in item for item in super_options)
        ):
            return True
    return False


@unittest.skipUnless(os.name == "posix", "canonical cleanup custody is POSIX-only")
class OwnedStagingCleanupV1Tests(unittest.TestCase):
    @unittest.skipUnless(
        is_wsl_drvfs_workspace(),
        "live post-rename descriptor loss requires the WSL DrvFS workspace",
    )
    def test_drvfs_post_rename_fd_loss_uses_final_inode_and_tree_anchors(
        self,
    ) -> None:
        from publication_policy_qualification_pilot_executor_v2 import (
            _rename_directory_noreplace,
        )

        with tempfile.TemporaryDirectory(
            prefix=".owned-staging-drvfs.", dir=ROOT
        ) as temporary:
            root = Path(temporary)
            staging_parent = root / "staging-parent"
            final_parent = root / "final-parent"
            staging_parent.mkdir()
            final_parent.mkdir()
            staging = staging_parent / "pilot"
            final = final_parent / "pilot"
            displaced = root / "displaced-final"
            staging.mkdir()
            (staging / "leaf").write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=staging_parent,
                expected_prefix="",
                label="DrvFS pilot output",
            ) as anchor:
                anchor.seal_tree()
                _rename_directory_noreplace(staging, final)
                anchor.assert_published_to(final)
                _rename_directory_noreplace(final, displaced)
                shutil.copytree(displaced, final)
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.assert_published_to(final)
            self.assertEqual((final / "leaf").read_bytes(), b"owned")
            self.assertEqual((displaced / "leaf").read_bytes(), b"owned")

    def test_exact_runtime_tree_is_retired_without_touching_accepted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            accepted = output / "frames.csv"
            accepted.write_bytes(b"accepted\n")
            runtime = output / "native_runtime"
            (runtime / "worker-00").mkdir(parents=True)
            (runtime / "worker-00" / "trace.bin").write_bytes(b"trace")
            (runtime / "manifest.json").write_bytes(b"{}\n")

            self.assertEqual(
                retire_owned_runtime_output_v1(runtime, output_root=output),
                "owned_tree_retired",
            )

            self.assertFalse(runtime.exists())
            self.assertEqual(accepted.read_bytes(), b"accepted\n")

    def test_runtime_retirement_rejects_nonexact_leaf_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            foreign = output / "native_runtime_foreign"
            foreign.mkdir()
            (foreign / "leaf").write_bytes(b"foreign")

            with self.assertRaises(OwnedStagingCleanupV1Error):
                retire_owned_runtime_output_v1(foreign, output_root=output)

            self.assertEqual((foreign / "leaf").read_bytes(), b"foreign")

    def test_runtime_retirement_rejects_hardlinked_leaf_without_deleting_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            runtime = output / "native_runtime"
            runtime.mkdir()
            outside = output / "outside"
            outside.write_bytes(b"shared")
            os.link(outside, runtime / "hardlink")

            with self.assertRaises(OwnedStagingCleanupV1Error):
                retire_owned_runtime_output_v1(runtime, output_root=output)

            self.assertEqual((runtime / "hardlink").read_bytes(), b"shared")
            self.assertEqual(outside.read_bytes(), b"shared")

    def test_runtime_retirement_rejects_same_name_rebind_without_deleting_foreign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            runtime = output / "native_runtime"
            displaced = output / "displaced"
            runtime.mkdir()
            (runtime / "leaf").write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                runtime,
                expected_parent=output,
                expected_prefix="native_runtim",
                label="test runtime",
            ) as anchor:
                anchor.seal_tree()
                os.rename(runtime, displaced)
                runtime.mkdir()
                (runtime / "leaf").write_bytes(b"foreign")
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.retire_owned_tree()

            self.assertEqual((runtime / "leaf").read_bytes(), b"foreign")
            self.assertEqual((displaced / "leaf").read_bytes(), b"owned")
    def test_adopted_staging_cleanup_preserves_final_and_removes_only_owned_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            final.mkdir()
            (final / "receipt.json").write_bytes(b"final\n")
            final_identity = final.stat().st_dev, final.stat().st_ino
            staging = root / ".final.staging.owned"
            staging.mkdir()
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=root,
                expected_prefix=".final.staging.",
                label="test staging",
            ) as anchor:
                (staging / "nested").mkdir()
                (staging / "nested" / "evidence.bin").write_bytes(b"evidence")
                (staging / "receipt.json").write_bytes(b"receipt\n")
                anchor.seal_tree()
                self.assertEqual(
                    anchor.cleanup_after_publication(final_target=final),
                    "adopted_staging_removed",
                )
            self.assertFalse(staging.exists())
            self.assertEqual((final.stat().st_dev, final.stat().st_ino), final_identity)
            self.assertEqual((final / "receipt.json").read_bytes(), b"final\n")

    def test_published_staging_is_recognized_by_exact_final_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".final.staging.owned"
            final = root / "final"
            staging.mkdir()
            (staging / "leaf").write_bytes(b"payload")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=root,
                expected_prefix=".final.staging.",
                label="test staging",
            ) as anchor:
                anchor.seal_tree()
                owned_identity = staging.stat().st_dev, staging.stat().st_ino
                os.rename(staging, final)
                self.assertEqual(
                    anchor.cleanup_after_publication(final_target=final), "published"
                )
            self.assertEqual((final.stat().st_dev, final.stat().st_ino), owned_identity)
            self.assertEqual((final / "leaf").read_bytes(), b"payload")

    def test_same_path_foreign_rebind_is_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            final.mkdir()
            final_identity = final.stat().st_dev, final.stat().st_ino
            staging = root / ".final.staging.owned"
            stolen = root / "stolen"
            staging.mkdir()
            (staging / "leaf").write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=root,
                expected_prefix=".final.staging.",
                label="test staging",
            ) as anchor:
                anchor.seal_tree()
                os.rename(staging, stolen)
                staging.mkdir()
                (staging / "foreign").write_bytes(b"foreign")
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.cleanup_after_publication(final_target=final)
            self.assertEqual((staging / "foreign").read_bytes(), b"foreign")
            self.assertEqual((stolen / "leaf").read_bytes(), b"owned")
            self.assertEqual((final.stat().st_dev, final.stat().st_ino), final_identity)

    def test_mutate_restore_after_seal_is_rejected_by_physical_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "final"
            final.mkdir()
            staging = root / ".final.staging.owned"
            staging.mkdir()
            leaf = staging / "leaf"
            leaf.write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=root,
                expected_prefix=".final.staging.",
                label="test staging",
            ) as anchor:
                anchor.seal_tree()
                original_mtime = leaf.stat().st_mtime_ns
                leaf.write_bytes(b"other")
                leaf.write_bytes(b"owned")
                os.utime(leaf, ns=(leaf.stat().st_atime_ns, original_mtime))
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.cleanup_after_publication(final_target=final)
            self.assertEqual(leaf.read_bytes(), b"owned")

    def test_sealed_staging_directory_swap_is_rejected_without_deleting_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".final.staging.owned"
            displaced = root / "displaced"
            staging.mkdir()
            (staging / "leaf").write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=root,
                expected_prefix=".final.staging.",
                label="test staging",
            ) as anchor:
                anchor.seal_tree()
                os.rename(staging, displaced)
                shutil.copytree(displaced, staging)
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.assert_staging_unchanged()
            self.assertEqual((staging / "leaf").read_bytes(), b"owned")
            self.assertEqual((displaced / "leaf").read_bytes(), b"owned")

    def test_published_final_directory_swap_is_rejected_before_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging_parent = root / "staging-parent"
            final_parent = root / "final-parent"
            staging_parent.mkdir()
            final_parent.mkdir()
            staging = staging_parent / "pilot"
            final = final_parent / "pilot"
            displaced = root / "displaced-final"
            staging.mkdir()
            (staging / "leaf").write_bytes(b"owned")
            with OwnedStagingDirectoryV1.capture(
                staging,
                expected_parent=staging_parent,
                expected_prefix="",
                label="test pilot output",
            ) as anchor:
                anchor.seal_tree()
                os.rename(staging, final)
                anchor.assert_published_to(final)
                os.rename(final, displaced)
                shutil.copytree(displaced, final)
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.assert_published_to(final)
            self.assertEqual((final / "leaf").read_bytes(), b"owned")
            self.assertEqual((displaced / "leaf").read_bytes(), b"owned")

    def test_candidate_rebind_is_not_unlinked_and_final_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "accepted.yaml"
            final.write_bytes(b"final")
            final_identity = final.stat().st_dev, final.stat().st_ino
            candidate = root / ".accepted.yaml.candidate.1"
            stolen = root / "stolen-candidate"
            candidate.write_bytes(b"owned")
            with OwnedStagingFileV1.capture(
                candidate, label="test candidate"
            ) as anchor:
                os.rename(candidate, stolen)
                candidate.write_bytes(b"foreign")
                with self.assertRaises(OwnedStagingCleanupV1Error):
                    anchor.unlink_owned(final_target=final)
            self.assertEqual(candidate.read_bytes(), b"foreign")
            self.assertEqual(stolen.read_bytes(), b"owned")
            self.assertEqual((final.stat().st_dev, final.stat().st_ino), final_identity)


if __name__ == "__main__":
    unittest.main()
