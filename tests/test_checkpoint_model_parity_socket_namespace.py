from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_model_parity_materializer as materializer  # noqa: E402
from checkpoint_model_parity_materializer import MaterializerError  # noqa: E402


class WorkerSocketNamespaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "posix":
            self.skipTest("the external socket namespace contract is POSIX-only")
        self._cleanup_paths: list[Path] = []

    def tearDown(self) -> None:
        for path in reversed(getattr(self, "_cleanup_paths", [])):
            if not os.path.lexists(path):
                continue
            if path.is_symlink() or not path.is_dir():
                path.unlink()
                continue
            for child in tuple(path.iterdir()):
                if child.is_symlink() or not child.is_dir():
                    child.unlink()
                else:
                    child.rmdir()
            path.rmdir()

    def _external_directory(self, *, prefix: str = "vast-mpv4-contract-") -> Path:
        path = Path(
            tempfile.mkdtemp(
                prefix=f"{prefix}{os.getpid()}-{time.monotonic_ns()}-",
                dir="/var/tmp",
            )
        )
        path.chmod(0o700)
        self._cleanup_paths.append(path)
        return path

    def _contract(self, path: Path) -> object:
        return materializer._worker_socket_namespace_contract(ROOT, path)

    def test_accepts_exact_private_external_namespace_and_checks_empty_after(self) -> None:
        path = self._external_directory()

        contract = self._contract(path)

        self.assertEqual(contract.path, path)
        self.assertTrue(contract.external)
        with contract.lifecycle():
            transient = path / "worker.sock"
            transient.touch()
            transient.unlink()

    def test_preserves_existing_under_project_directory_behavior(self) -> None:
        staging = ROOT / "staging"
        staging.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="socket-contract-", dir=staging) as temporary:
            project_root = Path(temporary).resolve()
            socket_dir = project_root / "sockets"
            socket_dir.mkdir()
            (socket_dir / "preexisting-entry").write_bytes(b"internal behavior")

            contract = materializer._worker_socket_namespace_contract(
                project_root, socket_dir
            )

            self.assertFalse(contract.external)
            with contract.lifecycle():
                pass

    def test_rejects_arbitrary_root_non_vast_and_nested_external_paths(self) -> None:
        non_vast = self._external_directory(prefix="mpv4-contract-")
        parent = self._external_directory()
        nested = parent / "nested"
        nested.mkdir(mode=0o700)

        for path in (Path("/"), Path("/var/tmp"), non_vast, nested):
            with self.subTest(path=path):
                with self.assertRaisesRegex(
                    MaterializerError, r"exact /var/tmp/vast-\*"
                ):
                    self._contract(path)

    def test_rejects_external_symlink(self) -> None:
        target = self._external_directory()
        alias = Path(
            "/var/tmp"
        ) / f"vast-mpv4-alias-{os.getpid()}-{time.monotonic_ns()}"
        alias.symlink_to(target, target_is_directory=True)
        self._cleanup_paths.append(alias)

        with self.assertRaisesRegex(MaterializerError, "alias|symlink"):
            self._contract(alias)

    def test_rejects_nonempty_external_namespace_before_lifecycle(self) -> None:
        path = self._external_directory()
        (path / "unexpected").write_bytes(b"occupied")

        with self.assertRaisesRegex(MaterializerError, "must be empty before"):
            self._contract(path)

    def test_rejects_wrong_external_namespace_mode(self) -> None:
        path = self._external_directory()
        path.chmod(0o750)

        with self.assertRaisesRegex(MaterializerError, "mode must be 0700"):
            self._contract(path)

    def test_rejects_wrong_external_namespace_uid_and_gid(self) -> None:
        path = self._external_directory()
        metadata = path.stat()

        with mock.patch.object(materializer.os, "getuid", return_value=metadata.st_uid + 1):
            with self.assertRaisesRegex(MaterializerError, "owned by current uid/gid"):
                self._contract(path)
        with mock.patch.object(materializer.os, "getgid", return_value=metadata.st_gid + 1):
            with self.assertRaisesRegex(MaterializerError, "owned by current uid/gid"):
                self._contract(path)

    def test_rejects_namespace_left_nonempty_after_lifecycle(self) -> None:
        path = self._external_directory()
        contract = self._contract(path)

        with self.assertRaisesRegex(MaterializerError, "must be empty after"):
            with contract.lifecycle():
                (path / "leaked.sock").touch()

    def test_rejects_namespace_inode_replacement_during_lifecycle(self) -> None:
        path = self._external_directory()
        replacement = path.with_name(f"{path.name}-original")
        self._cleanup_paths.insert(0, replacement)
        contract = self._contract(path)

        with self.assertRaisesRegex(MaterializerError, "inode identity changed"):
            with contract.lifecycle():
                path.rename(replacement)
                path.mkdir(mode=0o700)


if __name__ == "__main__":
    unittest.main()
