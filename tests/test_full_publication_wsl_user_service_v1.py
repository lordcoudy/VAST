from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_publication_wsl_user_service_v1 as service  # noqa: E402


class InjectedCrash(BaseException):
    pass


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        (self.root / "scripts").mkdir(parents=True)
        (self.root / "configs").mkdir()
        (self.root / "artifacts").mkdir()
        (self.root / "runs" / "full_publication").mkdir(parents=True)
        (self.root / "tools").mkdir()
        self.attempt_id = "publication-20260830-a1"
        self.run_root = self.root / "runs" / "full_publication" / self.attempt_id
        self.state_path = self.run_root / "full_publication_supervisor_state.v1.json"
        self.output_dir = self.root / "artifacts" / ("wsl-service-" + self.attempt_id)
        self.unit_dir = self.root / "user-units"
        self.files: dict[str, Path] = {}
        for name, relative in {
            "manager": "scripts/full_publication_wsl_user_service_v1.py",
            "supervisor": "scripts/full_publication_supervisor.py",
            "entrypoint": "scripts/full_publication_entrypoint.py",
            "config": "configs/experiments.yaml",
            "datasets": "configs/datasets.yaml",
            "models": "configs/models.yaml",
            "identity_artifacts": "artifacts/identity.json",
            "capacity_attestation": "artifacts/capacity.json",
            "cloud_links_file": "seafile.txt",
            "python_executable": "tools/python3.12",
            "docker_executable": "tools/docker",
        }.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((name + "\n").encode("ascii"))
            if os.name != "nt" and name in {
                "manager",
                "python_executable",
                "docker_executable",
            }:
                path.chmod(0o700)
            self.files[name] = path
        self.files["cloud_links_file"].write_text(
            "download link - https://seafile.example/d/ReadCapabilityToken99\n"
            "upload link - https://seafile.example/u/d/UploadCapabilityToken99\n",
            encoding="utf-8",
        )

    def materialize(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = dict(
            project_root=self.root,
            run_root=self.run_root,
            state_path=self.state_path,
            output_dir=self.output_dir,
            attempt_id=self.attempt_id,
            user_uid=1000,
            user_unit_dir=self.unit_dir,
            manager_path=self.files["manager"],
            supervisor_path=self.files["supervisor"],
            entrypoint_path=self.files["entrypoint"],
            python_executable=self.files["python_executable"],
            docker_executable=self.files["docker_executable"],
            config_path=self.files["config"],
            dataset_manifest_path=self.files["datasets"],
            model_manifest_path=self.files["models"],
            identity_artifact_manifest_path=self.files["identity_artifacts"],
            capacity_attestation_path=self.files["capacity_attestation"],
            cloud_links_file=self.files["cloud_links_file"],
            cloud_destination_id="vast-full-publication-private-v1",
        )
        arguments.update(overrides)
        return service.materialize_bundle_v1(**arguments)


class FullPublicationWslUserServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_materialization_is_canonical_self_hashed_and_does_not_start(self) -> None:
        with mock.patch.object(service.subprocess, "run") as run_process:
            result = self.fixture.materialize()
        run_process.assert_not_called()
        receipt_path = Path(str(result["receipt_path"]))
        manifest_path = Path(str(result["manifest_path"]))
        unit_path = Path(str(result["unit_path"]))
        validated = service.validate_bundle_v1(receipt_path)
        self.assertEqual(validated.manifest["attempt_id"], self.fixture.attempt_id)
        self.assertEqual(
            manifest_path.read_bytes(),
            service.canonical_json_bytes(validated.manifest) + b"\n",
        )
        self.assertEqual(
            receipt_path.read_bytes(),
            service.canonical_json_bytes(validated.receipt) + b"\n",
        )
        unit = unit_path.read_text(encoding="utf-8")
        manager = validated.manifest["sources"]["manager"]
        self.assertIn("WantedBy=default.target", unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("RestartPreventExitStatus=78", unit)
        self.assertIn('"-I"', unit)
        self.assertIn('"-B"', unit)
        self.assertIn('"-c"', unit)
        self.assertIn(str(manager["path"]), unit)
        self.assertIn(str(manager["size_bytes"]), unit)
        self.assertIn(str(manager["sha256"]), unit)
        self.assertNotIn("MemoryMax", unit)
        self.assertNotIn("MemoryHigh", unit)
        self.assertNotIn("bcd", unit.lower())
        self.assertNotIn("windows", unit.lower())

    def test_materialize_api_default_disables_unexpected_retries(self) -> None:
        result = self.fixture.materialize()
        bundle = service.validate_bundle_v1(Path(str(result["receipt_path"])))

        self.assertEqual(
            bundle.manifest["supervisor_contract"]["max_unexpected_retries"], 0
        )
        command = service.supervisor_command_v1(bundle.manifest)
        option = command.index("--max-unexpected-retries")
        self.assertEqual(command[option + 1], "0")

    def test_materialize_cli_default_disables_unexpected_retries(self) -> None:
        args = service.build_parser().parse_args(
            [
                "materialize",
                "--attempt-id",
                "publication-20260830-a1",
                "--run-root",
                "/tmp/runs/full_publication/publication-20260830-a1",
                "--output-dir",
                "/tmp/artifacts/wsl-service-publication-20260830-a1",
                "--python-executable",
                "/tmp/python3.12",
                "--identity-artifacts",
                "/tmp/identity.json",
                "--capacity-attestation",
                "/tmp/capacity.json",
                "--cloud-links-file",
                "/tmp/seafile.txt",
                "--cloud-destination-id",
                "vast-full-publication-private-v1",
            ]
        )

        self.assertEqual(args.max_unexpected_retries, 0)

    def test_pinned_source_command_rejects_post_manifest_replacement(self) -> None:
        source = self.fixture.root / "scripts" / "pinned_entrypoint.py"
        marker = self.fixture.root / "pinned-source-marker.txt"
        original = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('original', encoding='utf-8')\n"
        )
        replacement = original.replace("original", "replaced")
        self.assertEqual(len(original.encode()), len(replacement.encode()))
        source.write_text(original, encoding="utf-8")
        manifest = {
            "sources": {
                "python_executable": {"path": sys.executable},
                "entrypoint": service._stable_file_descriptor(
                    source, label="pinned test source"
                ),
            },
            "entrypoint_args": [],
        }
        command = service.entrypoint_command_v1(manifest, "status")
        completed = subprocess.run(command, check=False, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "original")
        marker.unlink()

        candidate = source.with_suffix(".replacement")
        candidate.write_text(replacement, encoding="utf-8")
        os.replace(candidate, source)
        completed = subprocess.run(command, check=False, capture_output=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(marker.exists())

    def test_bundle_leaf_and_directory_crash_windows_retry_same_path(self) -> None:
        windows = [
            *(f"{leaf}:{step}" for leaf in ("manifest", "unit", "receipt") for step in (
                "mid_write",
                "post_fsync_pre_publish",
                "post_publish_pre_parent_fsync",
            )),
            *(
                f"bundle:{step}"
                for step in (
                    "mid_write",
                    "post_fsync_pre_publish",
                    "post_publish_pre_parent_fsync",
                )
            ),
        ]
        for window in windows:
            with self.subTest(window=window), tempfile.TemporaryDirectory() as name:
                fixture = Fixture(Path(name))

                def crash(step: str, _path: Path) -> None:
                    if step == window:
                        raise InjectedCrash(window)

                with self.assertRaises(InjectedCrash):
                    fixture.materialize(after_physical_commit_step=crash)
                recovered = fixture.materialize()
                receipt = Path(str(recovered["receipt_path"]))
                service.validate_bundle_v1(receipt)
                before = receipt.parent.stat()
                again = fixture.materialize()
                after = Path(str(again["receipt_path"])).parent.stat()
                self.assertEqual(
                    (before.st_dev, before.st_ino),
                    (after.st_dev, after.st_ino),
                )

    def test_bundle_rejects_foreign_partial_target_tamper_and_rebind(self) -> None:
        self.fixture.output_dir.mkdir()
        (self.fixture.output_dir / service.MANIFEST_NAME).write_bytes(b"partial")
        with self.assertRaisesRegex(
            service.ServiceContractError, "directory publication"
        ):
            self.fixture.materialize()

        shutil.rmtree(self.fixture.output_dir)
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        unit = Path(str(result["unit_path"]))
        unit.write_bytes(unit.read_bytes() + b"# tamper\n")
        with self.assertRaisesRegex(
            service.ServiceContractError, "tampered|differs|drift"
        ):
            service.validate_bundle_v1(receipt)

        with tempfile.TemporaryDirectory() as name:
            fixture = Fixture(Path(name))
            result = fixture.materialize()
            receipt = Path(str(result["receipt_path"]))
            original = receipt.parent
            backup = original.with_name(original.name + ".original")
            original.rename(backup)
            shutil.copytree(backup, original)
            with self.assertRaisesRegex(
                service.ServiceContractError, "rebound|ABA|physical"
            ):
                service.validate_bundle_v1(original / service.RECEIPT_NAME)

    def test_bundle_rejects_preexisting_empty_or_symlink_target(self) -> None:
        self.fixture.output_dir.mkdir()
        with self.assertRaisesRegex(
            service.ServiceContractError, "directory publication"
        ):
            self.fixture.materialize()
        shutil.rmtree(self.fixture.output_dir)
        if not hasattr(os, "symlink"):
            return
        foreign = self.fixture.root / "foreign-bundle"
        foreign.mkdir()
        try:
            self.fixture.output_dir.symlink_to(foreign, target_is_directory=True)
        except OSError:
            return
        with self.assertRaisesRegex(
            service.ServiceContractError, "invalid existing type"
        ):
            self.fixture.materialize()

    def test_manifest_binds_same_exact_run_root_state_and_command_sources(self) -> None:
        result = self.fixture.materialize()
        bundle = service.validate_bundle_v1(Path(str(result["receipt_path"])))
        manifest = bundle.manifest
        self.assertEqual(
            manifest["schema_version"], service.MANIFEST_SCHEMA_VERSION
        )
        self.assertEqual(
            manifest["frozen_publication_contract"],
            {
                "matrix_schema_version": 4,
                "matrix_sha256": service.FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
                "policy_contract_sha256": (
                    service.FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256
                ),
            },
        )
        self.assertEqual(manifest["run_root"], str(self.fixture.run_root))
        self.assertEqual(manifest["state_path"], str(self.fixture.state_path))
        self.assertEqual(manifest["user_uid"], 1000)
        self.assertEqual(
            manifest["unit_name"],
            "vast-full-publication-publication-20260830-a1.service",
        )
        args = manifest["entrypoint_args"]
        self.assertIn(str(self.fixture.run_root), args)
        self.assertEqual(args.count("--run-root"), 1)
        self.assertEqual(args.count("--expected-matrix-sha256"), 1)
        self.assertEqual(args.count("--expected-policy-contract-sha256"), 1)
        self.assertIn(service.FROZEN_FULL_PUBLICATION_MATRIX_SHA256, args)
        self.assertIn(service.FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256, args)
        for label in (
            "manager",
            "supervisor",
            "entrypoint",
            "python_executable",
            "docker_executable",
            "capacity_attestation",
            "cloud_links_file",
        ):
            self.assertRegex(manifest["sources"][label]["sha256"], r"^[0-9a-f]{64}$")

    @unittest.skipUnless(
        sys.platform.startswith("linux") and shutil.which("systemd-analyze"),
        "systemd-analyze is unavailable",
    )
    def test_rendered_unit_passes_systemd_verify(self) -> None:
        result = self.fixture.materialize()
        completed = subprocess.run(
            ["systemd-analyze", "verify", str(result["unit_path"])],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_materialization_rejects_run_root_outside_exact_namespace(self) -> None:
        self.fixture.run_root = self.fixture.root / "other" / self.fixture.attempt_id
        self.fixture.state_path = self.fixture.run_root / "state.json"
        with self.assertRaisesRegex(service.ServiceContractError, "run_root"):
            self.fixture.materialize()

    def test_materialization_rejects_attempt_mismatch_and_symlinked_input(self) -> None:
        self.fixture.attempt_id = "different-attempt"
        with self.assertRaisesRegex(service.ServiceContractError, "attempt"):
            self.fixture.materialize()
        if hasattr(os, "symlink"):
            self.fixture.attempt_id = self.fixture.run_root.name
            target = self.fixture.files["config"]
            link = target.with_name("linked.yaml")
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlinks are unavailable")
            self.fixture.files["config"] = link
            with self.assertRaisesRegex(service.ServiceContractError, "symlink"):
                self.fixture.materialize()

    def test_materialization_rejects_alternate_frozen_contract_pins(self) -> None:
        for overrides in (
            {"expected_matrix_sha256": "0" * 64},
            {"expected_policy_contract_sha256": "0" * 64},
        ):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                service.ServiceContractError, "must equal the frozen"
            ):
                self.fixture.materialize(**overrides)
            self.assertFalse(self.fixture.output_dir.exists())

    def test_fully_rehashed_manifest_and_receipt_pin_drift_is_rejected(self) -> None:
        result = self.fixture.materialize()
        receipt_path = Path(str(result["receipt_path"]))
        manifest_path = Path(str(result["manifest_path"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("manifest_sha256")
        manifest["frozen_publication_contract"]["matrix_sha256"] = "0" * 64
        manifest["manifest_sha256"] = service._semantic_sha256(manifest)
        manifest_path.write_bytes(service.canonical_json_bytes(manifest) + b"\n")

        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["manifest"] = service._stable_file_descriptor(
            manifest_path, label="tampered materialized manifest"
        )
        receipt.pop("receipt_sha256")
        receipt["receipt_sha256"] = service._semantic_sha256(receipt)
        receipt_path.write_bytes(service.canonical_json_bytes(receipt) + b"\n")

        operations = (
            lambda: service.validate_bundle_v1(receipt_path),
            lambda: service.install_bundle_v1(
                receipt_path,
                command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("drifted receipt reached install control command")
                ),
                current_uid=1000,
                require_wsl=False,
            ),
            lambda: service.start_bundle_v1(
                receipt_path,
                command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("drifted receipt reached start control command")
                ),
                current_uid=1000,
                require_wsl=False,
                require_docker=False,
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(
                service.ServiceContractError, "tampered|differs|drift"
            ):
                operation()

    def test_validation_fails_on_source_unit_and_receipt_tampering(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        self.fixture.files["config"].write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(service.ServiceContractError, "identity drift"):
            service.validate_bundle_v1(receipt)
        self.fixture.files["config"].write_text("config\n", encoding="utf-8")
        unit = Path(str(result["unit_path"]))
        unit.write_text(unit.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        with self.assertRaisesRegex(
            service.ServiceContractError, "unit.*drift|bundle differs"
        ):
            service.validate_bundle_v1(receipt)

    def test_install_is_idempotent_never_enables_and_requires_linger(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        first = service.install_bundle_v1(
            receipt, command_runner=runner, current_uid=1000, require_wsl=False
        )
        second = service.install_bundle_v1(
            receipt, command_runner=runner, current_uid=1000, require_wsl=False
        )
        self.assertTrue(first["installed"])
        self.assertTrue(second["installed"])
        installed = self.fixture.unit_dir / service.unit_name_for_attempt(self.fixture.attempt_id)
        self.assertEqual(installed.read_bytes(), Path(str(result["unit_path"])).read_bytes())
        flattened = [item for command in calls for item in command]
        self.assertNotIn("enable", flattened)
        self.assertNotIn("start", flattened)
        self.assertEqual(flattened.count("daemon-reload"), 2)

        def no_linger(command: list[str], **_: object) -> SimpleNamespace:
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="no\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        installed.unlink()
        with self.assertRaisesRegex(service.ServiceContractError, "linger"):
            service.install_bundle_v1(
                receipt,
                command_runner=no_linger,
                current_uid=1000,
                require_wsl=False,
            )

    def test_install_refuses_drifted_existing_unit(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        self.fixture.unit_dir.mkdir()
        installed = self.fixture.unit_dir / service.unit_name_for_attempt(self.fixture.attempt_id)
        installed.write_text("wrong\n", encoding="utf-8")

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with self.assertRaisesRegex(
            service.ServiceContractError, "installed systemd unit"
        ):
            service.install_bundle_v1(
                receipt, command_runner=runner, current_uid=1000, require_wsl=False
            )

    @staticmethod
    def _successful_control_runner(
        command: list[str], **_: object
    ) -> SimpleNamespace:
        if command[:2] == ["/usr/bin/loginctl", "show-user"]:
            return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_install_crash_windows_retry_same_path_and_preserve_inode(self) -> None:
        windows = [
            f"install_{leaf}:{step}"
            for leaf in ("anchor", "unit", "receipt")
            for step in (
                "mid_write",
                "post_fsync_pre_publish",
                "post_publish_pre_parent_fsync",
            )
        ]
        for window in windows:
            with self.subTest(window=window), tempfile.TemporaryDirectory() as name:
                fixture = Fixture(Path(name))
                result = fixture.materialize()
                receipt = Path(str(result["receipt_path"]))

                def crash(step: str, _path: Path) -> None:
                    if step == window:
                        raise InjectedCrash(window)

                with self.assertRaises(InjectedCrash):
                    service.install_bundle_v1(
                        receipt,
                        command_runner=self._successful_control_runner,
                        current_uid=1000,
                        require_wsl=False,
                        after_physical_commit_step=crash,
                    )
                recovered = service.install_bundle_v1(
                    receipt,
                    command_runner=self._successful_control_runner,
                    current_uid=1000,
                    require_wsl=False,
                )
                installed = Path(str(recovered["installed_unit_path"]))
                before = installed.stat()
                again = service.install_bundle_v1(
                    receipt,
                    command_runner=self._successful_control_runner,
                    current_uid=1000,
                    require_wsl=False,
                )
                after = Path(str(again["installed_unit_path"])).stat()
                self.assertEqual(
                    (before.st_dev, before.st_ino),
                    (after.st_dev, after.st_ino),
                )

    def test_install_rejects_partial_journal_symlink_and_unit_dir_aba(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        unit_name = service.unit_name_for_attempt(self.fixture.attempt_id)
        self.fixture.unit_dir.mkdir()
        journal = self.fixture.unit_dir / service.EXTERNAL_UNIT_JOURNAL
        journal.mkdir()
        (journal / "foreign.partial").write_bytes(b"foreign")
        installed = self.fixture.unit_dir / unit_name
        installed.write_bytes(b"partial")
        with self.assertRaisesRegex(service.ServiceContractError, "installed systemd unit"):
            service.install_bundle_v1(
                receipt,
                command_runner=self._successful_control_runner,
                current_uid=1000,
                require_wsl=False,
            )

        shutil.rmtree(self.fixture.unit_dir)
        foreign = self.fixture.root / "foreign-unit-dir"
        foreign.mkdir()
        try:
            self.fixture.unit_dir.symlink_to(foreign, target_is_directory=True)
        except OSError:
            pass
        else:
            with self.assertRaisesRegex(
                service.ServiceContractError, "user_unit_dir|directory"
            ):
                service.install_bundle_v1(
                    receipt,
                    command_runner=self._successful_control_runner,
                    current_uid=1000,
                    require_wsl=False,
                )
            self.fixture.unit_dir.unlink()

        service.install_bundle_v1(
            receipt,
            command_runner=self._successful_control_runner,
            current_uid=1000,
            require_wsl=False,
        )
        original = self.fixture.unit_dir
        backup = original.with_name(original.name + ".original")
        original.rename(backup)
        shutil.copytree(backup, original, copy_function=shutil.copy2)
        with self.assertRaisesRegex(
            service.ServiceContractError, "tampered|rebound|ABA|identity"
        ):
            service.start_bundle_v1(
                receipt,
                command_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("rebound unit directory reached a control command")
                ),
                current_uid=1000,
                require_wsl=False,
                require_docker=False,
            )

    def _install_exact_unit(self, result: dict[str, object]) -> Path:
        receipt = Path(str(result["receipt_path"]))

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        installed = service.install_bundle_v1(
            receipt,
            command_runner=runner,
            current_uid=1000,
            require_wsl=False,
        )["installed_unit_path"]
        return Path(str(installed))

    def test_start_never_enables_when_preflight_is_not_exact_ready(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        self._install_exact_unit(result)
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
            if command[-1:] == ["preflight"]:
                return SimpleNamespace(
                    returncode=75,
                    stdout=json.dumps(
                        {
                            "schema_version": 1,
                            "artifact_kind": "vast_full_publication_external_preflight",
                            "status": "blocked_preflight",
                            "passed": False,
                            "retryable": True,
                            "reason": "not ready",
                            "details": {},
                        }
                    ),
                    stderr="",
                )
            raise AssertionError(command)

        response = service.start_bundle_v1(
            receipt,
            command_runner=runner,
            current_uid=1000,
            require_wsl=False,
            require_docker=False,
        )
        self.assertEqual(response["exit_code"], 75)
        self.assertFalse(any("enable" in command for command in calls))

    def test_start_enables_only_after_exact_preflight_ready(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        self._install_exact_unit(result)
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            if command[:2] == ["/usr/bin/loginctl", "show-user"]:
                return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
            if command[-1:] == ["preflight"]:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "schema_version": 1,
                            "artifact_kind": "vast_full_publication_external_preflight",
                            "status": "ready",
                            "passed": True,
                            "retryable": False,
                            "details": {},
                        }
                    ),
                    stderr="",
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        response = service.start_bundle_v1(
            receipt,
            command_runner=runner,
            current_uid=1000,
            require_wsl=False,
            require_docker=False,
        )
        self.assertEqual(response["exit_code"], 0)
        self.assertIn(
            [
                "/usr/bin/systemctl",
                "--user",
                "enable",
                "--now",
                service.unit_name_for_attempt(self.fixture.attempt_id),
            ],
            calls,
        )

    def test_launch_returns_transient_for_unready_docker_and_never_execs(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        self._install_exact_unit(result)

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            self.assertIn("info", command)
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon down")

        with mock.patch.object(service.os, "execve") as execve:
            code, payload = service.launch_bundle_v1(
                receipt,
                command_runner=runner,
                current_uid=1000,
                require_wsl=False,
            )
        self.assertEqual(code, 75)
        self.assertEqual(payload["status"], "docker_unavailable")
        execve.assert_not_called()

    def test_launch_execs_exact_supervisor_only_after_preflight(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        bundle = service.validate_bundle_v1(receipt)
        self._install_exact_unit(result)
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            if "info" in command:
                return SimpleNamespace(returncode=0, stdout="27.1.1\n", stderr="")
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {
                        "schema_version": 1,
                        "artifact_kind": "vast_full_publication_external_preflight",
                        "status": "ready",
                        "passed": True,
                        "retryable": False,
                        "details": {},
                    }
                ),
                stderr="",
            )

        with mock.patch.object(service.os, "execve", side_effect=RuntimeError("exec")) as execve:
            with self.assertRaisesRegex(RuntimeError, "exec"):
                service.launch_bundle_v1(
                    receipt,
                    command_runner=runner,
                    current_uid=1000,
                    require_wsl=False,
                    environment={
                        "SAFE": "1",
                        "VAST_SEAFILE_UPLOAD_LINK": "secret-upload",
                        "VAST_SEAFILE_READ_LINK": "secret-read",
                        "PYTHONPATH": "untrusted",
                        "DOCKER_HOST": "tcp://untrusted:2375",
                    },
                )
        expected = service.supervisor_command_v1(bundle.manifest)
        invoked_path, invoked_argv, invoked_env = execve.call_args.args
        self.assertEqual(invoked_path, expected[0])
        self.assertEqual(invoked_argv, expected)
        self.assertEqual(invoked_env["SAFE"], "1")
        self.assertNotIn("VAST_SEAFILE_UPLOAD_LINK", invoked_env)
        self.assertNotIn("VAST_SEAFILE_READ_LINK", invoked_env)
        self.assertNotIn("PYTHONPATH", invoked_env)
        self.assertEqual(invoked_env["DOCKER_HOST"], "unix:///run/docker.sock")
        self.assertEqual(
            invoked_env["VAST_PUBLICATION_RUNTIME_SOURCE"],
            str(self.fixture.files["python_executable"].parent.parent),
        )

    def test_status_crosschecks_supervisor_command_identity(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        bundle = service.validate_bundle_v1(receipt)
        self._install_exact_unit(result)
        self.fixture.run_root.mkdir()
        state = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_supervisor_state",
            "command_identity_sha256": service.expected_supervisor_command_identity_sha256_v1(
                bundle.manifest
            ),
            "phase": "run",
            "attempt_seq": 4,
            "transient_streak": 1,
            "unexpected_streak": 0,
            "last_exit_code": 75,
            "last_artifact_kind": "vast_full_publication_command_error",
            "last_payload_sha256": "a" * 64,
            "updated_at": "2026-08-30T00:00:00+00:00",
            "completed_at": None,
        }
        self.fixture.state_path.write_text(json.dumps(state), encoding="utf-8")

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            self.assertIn("show", command)
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "LoadState=loaded\nActiveState=active\nSubState=running\n"
                    "UnitFileState=enabled\nResult=success\nMainPID=123\n"
                ),
                stderr="",
            )

        status = service.status_bundle_v1(
            receipt, command_runner=runner, current_uid=1000, require_wsl=False
        )
        self.assertEqual(status["unit"]["ActiveState"], "active")
        self.assertEqual(status["supervisor_state"]["phase"], "run")
        state["command_identity_sha256"] = "0" * 64
        self.fixture.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(service.ServiceContractError, "command identity"):
            service.status_bundle_v1(
                receipt, command_runner=runner, current_uid=1000, require_wsl=False
            )

    def test_stop_targets_only_exact_installed_unit_and_disables_it(self) -> None:
        result = self.fixture.materialize()
        receipt = Path(str(result["receipt_path"]))
        installed = self._install_exact_unit(result)
        calls: list[list[str]] = []

        def runner(command: list[str], **_: object) -> SimpleNamespace:
            calls.append(command)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        response = service.stop_bundle_v1(
            receipt, command_runner=runner, current_uid=1000, require_wsl=False
        )
        self.assertTrue(response["stopped"])
        self.assertIn(
            [
                "/usr/bin/systemctl",
                "--user",
                "disable",
                "--now",
                service.unit_name_for_attempt(self.fixture.attempt_id),
            ],
            calls,
        )
        installed.write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(
            service.ServiceContractError, "installed systemd unit.*drift"
        ):
            service.stop_bundle_v1(
                receipt, command_runner=runner, current_uid=1000, require_wsl=False
            )

    def test_wsl_gate_rejects_non_wsl_and_accepts_explicit_probe(self) -> None:
        with mock.patch.object(service, "is_wsl", return_value=False):
            with self.assertRaisesRegex(service.ServiceContractError, "WSL"):
                service.require_wsl()
        with mock.patch.object(service, "is_wsl", return_value=True):
            service.require_wsl()


if __name__ == "__main__":
    unittest.main()
