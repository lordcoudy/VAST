from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publication_immutable_directory_v1 as target  # noqa: E402


class InjectedCrash(RuntimeError):
    pass


def _stage(root: Path) -> Path:
    staging = root / ".result.staging"
    staging.mkdir()
    nested = staging / "nested"
    nested.mkdir()
    (staging / "a.json").write_bytes(b"{\"a\":1}\n")
    (nested / "b.bin").write_bytes(b"evidence\x00")
    for file in (staging / "a.json", nested / "b.bin"):
        file.chmod(0o444)
    return staging


class PublicationImmutableDirectoryV1Tests(unittest.TestCase):
    def test_three_crash_windows_exact_adoption_and_inode_preservation(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory(
                prefix=".immutable-dir-test-", dir=ROOT / ".test-tmp"
            ) as temporary:
                root = Path(temporary).resolve()
                staging = _stage(root)
                final = root / "result"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(step)

                with self.assertRaises(InjectedCrash):
                    target.commit_or_adopt_immutable_directory_v1(
                        project_root=root,
                        staging=staging,
                        target=final,
                        after_publish_step=crash,
                    )
                if not staging.exists():
                    staging = _stage(root)
                result = target.commit_or_adopt_immutable_directory_v1(
                    project_root=root, staging=staging, target=final
                )
                self.assertIn(result["disposition"], {"published", "adopted"})
                identity = final.stat().st_dev, final.stat().st_ino
                if staging.exists():
                    staging.chmod(0o755)
                    shutil.rmtree(staging)
                staging = _stage(root)
                adopted = target.commit_or_adopt_immutable_directory_v1(
                    project_root=root, staging=staging, target=final
                )
                self.assertEqual(adopted["disposition"], "adopted")
                self.assertEqual((final.stat().st_dev, final.stat().st_ino), identity)

    def test_foreign_target_and_aba_restore_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".immutable-dir-foreign-", dir=ROOT / ".test-tmp"
        ) as temporary:
            root = Path(temporary).resolve()
            staging = _stage(root)
            foreign = root / "result"
            foreign.mkdir()
            with self.assertRaisesRegex(Exception, "without intent"):
                target.commit_or_adopt_immutable_directory_v1(
                    project_root=root, staging=staging, target=foreign
                )

        with tempfile.TemporaryDirectory(
            prefix=".immutable-dir-aba-", dir=ROOT / ".test-tmp"
        ) as temporary:
            root = Path(temporary).resolve()
            staging = _stage(root)
            final = root / "result"
            target.commit_or_adopt_immutable_directory_v1(
                project_root=root, staging=staging, target=final
            )
            leaf = final / "a.json"
            original = leaf.read_bytes()
            leaf.chmod(0o600)
            leaf.write_bytes(b"{\"a\":2}\n")
            leaf.write_bytes(original)
            leaf.chmod(0o444)
            staging = _stage(root)
            with self.assertRaisesRegex(Exception, "ABA-restored"):
                target.commit_or_adopt_immutable_directory_v1(
                    project_root=root, staging=staging, target=final
                )


if __name__ == "__main__":
    unittest.main()
