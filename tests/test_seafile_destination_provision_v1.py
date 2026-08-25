from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import seafile_destination_provision_v1 as target  # noqa: E402
from tests.test_seafile_capacity_attestation_v1 import GIB, rows  # noqa: E402


class FakeStore:
    def __init__(self, origin: str, *, remote_file_count: int = 0) -> None:
        self.origin = origin
        self.remote_file_count = remote_file_count

    def preflight(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "vast_seafile_preflight",
            "status": "ready",
            "transport": "https",
            "origin": self.origin,
            "read_capability": "verified",
            "upload_capability": "verified_get_only",
            "remote_file_count": self.remote_file_count,
            "remote_size_bytes": 0 if self.remote_file_count == 0 else 7,
            "quota_visibility": "not_exposed_by_share_link",
        }


class FakeClient:
    def __init__(self, *, available_gib: int = 800) -> None:
        self.base_url = "https://seafile.example"
        self.account_token = "AccountSuperSecretToken99"
        self.available_gib = available_gib
        self.calls: list[tuple[str, object]] = []
        self.deleted: list[str] = []
        self.next_id = 1

    def __repr__(self) -> str:
        return "FakeClient(account_token=AccountSuperSecretToken99)"

    def get_account_info(self) -> dict[str, int]:
        self.calls.append(("account", None))
        return {"total": (self.available_gib + 100) * GIB, "usage": 100 * GIB}

    def create_repository(self, name: str) -> dict[str, str]:
        self.calls.append(("create", name))
        number = self.next_id
        self.next_id += 1
        return {
            "repo_id": f"0000000{number}-0000-4000-8000-00000000000{number}",
            "name": name,
        }

    def create_upload_link(self, repo_id: str) -> str:
        self.calls.append(("upload", repo_id))
        return f"https://seafile.example/u/d/UploadSecret{repo_id[-1]}"

    def create_read_link(self, repo_id: str) -> str:
        self.calls.append(("read", repo_id))
        return f"https://seafile.example/d/ReadSecret{repo_id[-1]}"

    def delete_repository(self, repo_id: str) -> None:
        self.calls.append(("delete", repo_id))
        self.deleted.append(repo_id)


class SeafileDestinationProvisionV1Tests(unittest.TestCase):
    @staticmethod
    def _layout(root: Path) -> tuple[Path, Path, Path]:
        root = Path(root).resolve(strict=True)
        project_root = root / "project"
        attestation_parent = project_root / "configs"
        secret_parent = root / "wsl-ext4"
        attestation_parent.mkdir(parents=True)
        secret_parent.mkdir()
        return (
            project_root,
            secret_parent / "seafile-bindings",
            attestation_parent / "capacity_attestation.json",
        )

    @staticmethod
    def _server_identity() -> dict[str, str]:
        return {
            "deployment_id": "external-seafile-publication-store-v1",
            "server_version": "13.0.0",
            "storage_scope": "account_quota_api",
        }

    @staticmethod
    def _ext4(_path: Path) -> str:
        return "ext4"

    @unittest.skipUnless(os.name == "posix", "POSIX mode semantics required")
    def test_provisions_separate_final_and_scratch_and_commits_secrets_0600(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            project_root, secret_output, capacity_output = self._layout(root)
            client = FakeClient()
            stores: list[str] = []

            def store_factory(upload: str, read: str) -> FakeStore:
                stores.extend((upload, read))
                return FakeStore("https://seafile.example")

            result = target.provision_seafile_destinations_v1(
                client=client,
                observed_pair_archives=rows(),
                project_root=project_root,
                secret_output_dir=secret_output,
                capacity_attestation_path=capacity_output,
                observed_at_utc="2026-08-25T18:00:00Z",
                server_identity=self._server_identity(),
                store_factory=store_factory,
                secret_filesystem_type_resolver=self._ext4,
            )
            self.assertEqual(client.calls[0], ("account", None))
            self.assertEqual([call[0] for call in client.calls].count("create"), 2)
            self.assertNotEqual(result["final_repo_id"], result["scratch_repo_id"])
            self.assertEqual(client.deleted, [])
            self.assertTrue(capacity_output.is_file())
            self.assertFalse((secret_output / "capacity_attestation.json").exists())
            self.assertEqual(stat.S_IMODE(secret_output.stat().st_mode), 0o700)
            for filename in ("final.env", "scratch.env"):
                path = secret_output / filename
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            final_env = (secret_output / "final.env").read_text(encoding="utf-8")
            scratch_env = (secret_output / "scratch.env").read_text(encoding="utf-8")
            self.assertIn(str(result["final_repo_id"]), final_env)
            self.assertIn(str(capacity_output.resolve()), final_env)
            self.assertNotIn(str(result["scratch_repo_id"]), final_env)
            self.assertIn(str(result["scratch_repo_id"]), scratch_env)
            self.assertEqual(result["capacity_attestation"], str(capacity_output.resolve()))
            self.assertEqual(
                result["final_environment"],
                str(secret_output.resolve() / "final.env"),
            )
            self.assertEqual(
                result["scratch_environment"],
                str(secret_output.resolve() / "scratch.env"),
            )
            rendered = json.dumps(result, sort_keys=True)
            self.assertNotIn("Secret", rendered)
            self.assertNotIn("AccountSuperSecretToken99", rendered)
            attestation = capacity_output.read_text(encoding="utf-8")
            self.assertNotIn("Secret", attestation)
            self.assertEqual(len(stores), 4)

    @unittest.skipUnless(
        os.name == "posix" and shutil.which("findmnt") is not None,
        "Linux findmnt and POSIX mode semantics required",
    )
    def test_real_filesystem_split_uses_project_storage_and_external_ext4(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".seafile-project-test.", dir=ROOT
        ) as project_tmp, tempfile.TemporaryDirectory(
            prefix="seafile-secret-test."
        ) as secret_tmp:
            project_root = Path(project_tmp).resolve(strict=True)
            configs = project_root / "configs"
            configs.mkdir()
            secret_parent = Path(secret_tmp).resolve(strict=True)
            secret_output = secret_parent / "bindings"
            capacity_output = configs / "capacity_attestation.json"
            client = FakeClient()

            result = target.provision_seafile_destinations_v1(
                client=client,
                observed_pair_archives=rows(),
                project_root=project_root,
                secret_output_dir=secret_output,
                capacity_attestation_path=capacity_output,
                observed_at_utc="2026-08-25T18:00:00Z",
                server_identity=self._server_identity(),
                store_factory=lambda _upload, _read: FakeStore(client.base_url),
            )

            self.assertEqual(result["capacity_attestation"], str(capacity_output))
            self.assertTrue(capacity_output.is_file())
            self.assertTrue((secret_output / "final.env").is_file())
            self.assertEqual(stat.S_IMODE(secret_output.stat().st_mode), 0o700)

    def test_quota_shortfall_prevents_external_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, secret_output, capacity_output = self._layout(Path(tmp))
            client = FakeClient(available_gib=499)
            with self.assertRaisesRegex(target.SeafileDestinationProvisionV1Error, "quota"):
                target.provision_seafile_destinations_v1(
                    client=client,
                    observed_pair_archives=rows(),
                    project_root=project_root,
                    secret_output_dir=secret_output,
                    capacity_attestation_path=capacity_output,
                    observed_at_utc="2026-08-25T18:00:00Z",
                    server_identity=self._server_identity(),
                    store_factory=lambda _upload, _read: FakeStore(client.base_url),
                    secret_filesystem_type_resolver=self._ext4,
                )
            self.assertEqual(client.calls, [("account", None)])
            self.assertEqual(client.deleted, [])
            self.assertFalse(secret_output.exists())
            self.assertFalse(capacity_output.exists())

    def test_nonempty_final_destination_rolls_back_only_new_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, secret_output, capacity_output = self._layout(Path(tmp))
            client = FakeClient()
            call = 0

            def store_factory(_upload: str, _read: str) -> FakeStore:
                nonlocal call
                call += 1
                return FakeStore(client.base_url, remote_file_count=1 if call == 2 else 0)

            with self.assertRaisesRegex(
                target.SeafileDestinationProvisionV1Error, "provisioning failed"
            ) as failure:
                target.provision_seafile_destinations_v1(
                    client=client,
                    observed_pair_archives=rows(),
                    project_root=project_root,
                    secret_output_dir=secret_output,
                    capacity_attestation_path=capacity_output,
                    observed_at_utc="2026-08-25T18:00:00Z",
                    server_identity=self._server_identity(),
                    store_factory=store_factory,
                    secret_filesystem_type_resolver=self._ext4,
                )
            self.assertEqual(len(client.deleted), 2)
            self.assertFalse(secret_output.exists())
            self.assertFalse(capacity_output.exists())
            self.assertNotIn("Secret", str(failure.exception))
            self.assertNotIn("AccountSuperSecretToken99", str(failure.exception))

    def test_paths_are_preflighted_before_account_or_repository_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            project_root, secret_output, capacity_output = self._layout(root)
            outside = root / "outside"
            outside.mkdir()

            cases = (
                (secret_output, outside / "capacity.json", "inside project_root"),
                (project_root / "secrets", capacity_output, "outside project_root"),
            )
            for candidate_secret, candidate_capacity, pattern in cases:
                with self.subTest(pattern=pattern):
                    client = FakeClient()
                    with self.assertRaisesRegex(
                        target.SeafileDestinationProvisionV1Error, pattern
                    ):
                        target.provision_seafile_destinations_v1(
                            client=client,
                            observed_pair_archives=rows(),
                            project_root=project_root,
                            secret_output_dir=candidate_secret,
                            capacity_attestation_path=candidate_capacity,
                            observed_at_utc="2026-08-25T18:00:00Z",
                            server_identity=self._server_identity(),
                            store_factory=lambda _upload, _read: FakeStore(client.base_url),
                            secret_filesystem_type_resolver=self._ext4,
                        )
                    self.assertEqual(client.calls, [])

            capacity_output.write_text("collision", encoding="utf-8")
            client = FakeClient()
            with self.assertRaisesRegex(
                target.SeafileDestinationProvisionV1Error, "collision"
            ):
                target.provision_seafile_destinations_v1(
                    client=client,
                    observed_pair_archives=rows(),
                    project_root=project_root,
                    secret_output_dir=secret_output,
                    capacity_attestation_path=capacity_output,
                    observed_at_utc="2026-08-25T18:00:00Z",
                    server_identity=self._server_identity(),
                    store_factory=lambda _upload, _read: FakeStore(client.base_url),
                    secret_filesystem_type_resolver=self._ext4,
                )
            self.assertEqual(client.calls, [])

    def test_rejects_non_ext4_secret_parent_before_external_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, secret_output, capacity_output = self._layout(Path(tmp))
            client = FakeClient()
            with self.assertRaisesRegex(
                target.SeafileDestinationProvisionV1Error, "ext4"
            ):
                target.provision_seafile_destinations_v1(
                    client=client,
                    observed_pair_archives=rows(),
                    project_root=project_root,
                    secret_output_dir=secret_output,
                    capacity_attestation_path=capacity_output,
                    observed_at_utc="2026-08-25T18:00:00Z",
                    server_identity=self._server_identity(),
                    store_factory=lambda _upload, _read: FakeStore(client.base_url),
                    secret_filesystem_type_resolver=lambda _path: "9p",
                )
            self.assertEqual(client.calls, [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_rejects_aliased_parent_before_external_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            project_root, _secret_output, capacity_output = self._layout(root)
            physical_secret_parent = root / "physical-secrets"
            physical_secret_parent.mkdir()
            alias = root / "secret-alias"
            try:
                alias.symlink_to(physical_secret_parent, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"cannot create directory symlink: {exc}")
            client = FakeClient()
            with self.assertRaisesRegex(
                target.SeafileDestinationProvisionV1Error, "physical"
            ):
                target.provision_seafile_destinations_v1(
                    client=client,
                    observed_pair_archives=rows(),
                    project_root=project_root,
                    secret_output_dir=alias / "bindings",
                    capacity_attestation_path=capacity_output,
                    observed_at_utc="2026-08-25T18:00:00Z",
                    server_identity=self._server_identity(),
                    store_factory=lambda _upload, _read: FakeStore(client.base_url),
                    secret_filesystem_type_resolver=self._ext4,
                )
            self.assertEqual(client.calls, [])

    @unittest.skipUnless(os.name == "posix", "POSIX mode semantics required")
    def test_failed_second_local_commit_removes_owned_attestation_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, secret_output, capacity_output = self._layout(Path(tmp))
            client = FakeClient()
            real_mkdir = os.mkdir

            def mkdir(
                path: os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
            ) -> None:
                if Path(path) == secret_output.resolve():
                    raise OSError("injected secret commit failure")
                real_mkdir(path, mode, dir_fd=dir_fd)

            with mock.patch.object(target.os, "mkdir", side_effect=mkdir):
                with self.assertRaisesRegex(
                    target.SeafileDestinationProvisionV1Error, "rolled back"
                ):
                    target.provision_seafile_destinations_v1(
                        client=client,
                        observed_pair_archives=rows(),
                        project_root=project_root,
                        secret_output_dir=secret_output,
                        capacity_attestation_path=capacity_output,
                        observed_at_utc="2026-08-25T18:00:00Z",
                        server_identity=self._server_identity(),
                        store_factory=lambda _upload, _read: FakeStore(client.base_url),
                        secret_filesystem_type_resolver=self._ext4,
                    )
            self.assertEqual(len(client.deleted), 2)
            self.assertFalse(secret_output.exists())
            self.assertFalse(capacity_output.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX mode semantics required")
    def test_partial_secret_file_commit_is_removed_before_repository_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root, secret_output, capacity_output = self._layout(Path(tmp))
            client = FakeClient()
            real_rename = os.rename

            def rename(
                source: os.PathLike[str],
                destination: os.PathLike[str],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if (
                    Path(source).name == "scratch.env"
                    and Path(destination).parent == secret_output.resolve()
                ):
                    raise OSError("injected second secret file failure")
                if src_dir_fd is None and dst_dir_fd is None:
                    real_rename(source, destination)
                else:
                    real_rename(
                        source,
                        destination,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                    )

            with mock.patch.object(target.os, "rename", side_effect=rename):
                with self.assertRaisesRegex(
                    target.SeafileDestinationProvisionV1Error, "rolled back"
                ):
                    target.provision_seafile_destinations_v1(
                        client=client,
                        observed_pair_archives=rows(),
                        project_root=project_root,
                        secret_output_dir=secret_output,
                        capacity_attestation_path=capacity_output,
                        observed_at_utc="2026-08-25T18:00:00Z",
                        server_identity=self._server_identity(),
                        store_factory=lambda _upload, _read: FakeStore(client.base_url),
                        secret_filesystem_type_resolver=self._ext4,
                    )
            self.assertEqual(len(client.deleted), 2)
            self.assertFalse(secret_output.exists())
            self.assertFalse(capacity_output.exists())
            self.assertEqual(list(secret_output.parent.iterdir()), [])
            self.assertEqual(list(capacity_output.parent.iterdir()), [])

    def test_cli_exposes_only_explicit_split_output_flags(self) -> None:
        argv = [
            "seafile_destination_provision_v1.py",
            "--base-url",
            "https://seafile.example",
            "--sizing-json",
            "sizing.json",
            "--project-root",
            "/mnt/e/STUDY/VAST",
            "--secret-output-dir",
            "/home/user/.local/state/vast/seafile",
            "--capacity-attestation-output",
            "/mnt/e/STUDY/VAST/configs/seafile_capacity_attestation.json",
            "--observed-at-utc",
            "2026-08-25T18:00:00Z",
            "--deployment-id",
            "external-seafile-publication-store-v1",
            "--server-version",
            "13.0.0",
        ]
        with mock.patch.object(sys, "argv", argv):
            args = target._parse_args()
        self.assertFalse(hasattr(args, "output_dir"))
        self.assertEqual(args.project_root, Path("/mnt/e/STUDY/VAST"))
        self.assertEqual(
            args.secret_output_dir,
            Path("/home/user/.local/state/vast/seafile"),
        )
        self.assertEqual(
            args.capacity_attestation_output,
            Path("/mnt/e/STUDY/VAST/configs/seafile_capacity_attestation.json"),
        )

    def test_http_client_repr_redacts_token_and_rejects_non_https(self) -> None:
        client = target.SeafileAccountClient(
            "https://seafile.example", "AccountSuperSecretToken99"
        )
        self.assertNotIn("AccountSuperSecretToken99", repr(client))
        with self.assertRaisesRegex(target.SeafileDestinationProvisionV1Error, "HTTPS"):
            target.SeafileAccountClient(
                "http://seafile.example", "AccountSuperSecretToken99"
            )


if __name__ == "__main__":
    unittest.main()
