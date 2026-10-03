from __future__ import annotations

import copy
import hashlib
import os
import signal
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "backend_publication_v3_process_fixture.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_publication_dispatch_v3 as dispatch  # noqa: E402
import backend_publication_output_transaction_production_v3 as production  # noqa: E402
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
from production_parent_artifact_pin_store_v1 import (  # noqa: E402
    ProductionParentArtifactPinStoreV1,
)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def accept_synthetic_semantics(request: dict[str, object]) -> dict[str, object]:
    payloads = request["evidence_payloads"]
    if not isinstance(payloads, dict) or not payloads or not all(
        bytes(value).startswith(b"VAST:synthetic-backend-publication-evidence:v3\0")
        for value in payloads.values()
    ):
        return {
            "accepted": False,
            "status": "rejected",
            "details": {"reason": "invalid synthetic evidence"},
        }
    return {
        "accepted": True,
        "status": "accepted",
        "details": {"validated_files": sorted(payloads)},
    }


def reject_synthetic_semantics(_request: dict[str, object]) -> dict[str, object]:
    return {
        "accepted": False,
        "status": "rejected",
        "details": {"reason": "semantic evidence rejected"},
    }


def accept_all_semantics(_request: dict[str, object]) -> dict[str, object]:
    return {"accepted": True, "status": "accepted", "details": {}}


class SyntheticProductionAbort(BaseException):
    pass


class BackendPublicationOutputTransactionProductionV3Tests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if os.name == "nt":
            scratch = ROOT / ".test-tmp"
            scratch.mkdir(exist_ok=True)
            self.temporary = tempfile.TemporaryDirectory(dir=scratch)
            self.project_root = ROOT.resolve(strict=True)
            self.python_path = Path(sys.executable).resolve(strict=True)
        else:
            self.temporary = tempfile.TemporaryDirectory()
            self.project_root = Path("/").resolve(strict=True)
            self.python_path = Path(sys.executable).resolve(strict=True)
        self.addCleanup(self.temporary.cleanup)
        self.output_dir = Path(self.temporary.name).resolve(strict=True) / "transaction"
        self.arm_path = self.output_dir / dispatch.ARM_CONTRACT_FILENAME
        self.python_descriptor = self._project_descriptor(self.python_path)
        self.launcher_descriptor = self._project_descriptor(FIXTURE.resolve(strict=True))
        self.coordinate = {
            "system": "deepstream",
            "codec": "h264",
            "topology_kind": "shared_video_dag",
            "policy": "cpu_only",
            "deadline_ms": 50,
        }
        self.invocation = publication_launcher_invocation_v3_contract()
        self.dispatch_pins = {
            "expected_coordinate": self.coordinate,
            "expected_python_executable": self.python_descriptor,
            "expected_publication_launcher": self.launcher_descriptor,
            "expected_launcher_invocation_sha256": self.invocation["invocation_sha256"],
            "expected_backend_runtime_grant_sha256": "3" * 64,
            "expected_identity_artifact_binding_sha256": "4" * 64,
            "expected_cell_identity_sha256": "5" * 64,
            "expected_validation_record_sha256": "6" * 64,
            "expected_runtime_binding_identity_sha256": "7" * 64,
        }
        self.resolution = dispatch.build_backend_publication_dispatch_resolution_v3(
            coordinate=self.coordinate,
            python_executable=self.python_descriptor,
            publication_launcher=self.launcher_descriptor,
            launcher_invocation=self.invocation,
            backend_runtime_grant_sha256="3" * 64,
            identity_artifact_binding_sha256="4" * 64,
            cell_identity_sha256="5" * 64,
            validation_record_sha256="6" * 64,
            runtime_binding_identity_sha256="7" * 64,
        )
        self.execution = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_arm_execution_binding",
            "run_identity_sha256": "8" * 64,
            "sequence": 4,
            "pair_id": "pair-0004",
            "attempt": 1,
            "arm_id": "arm-0004-b",
        }
        self.evidence = ["latency_samples.json", "runtime_assessment.json"]
        self.validator_identity = production.semantic_evidence_validator_identity_v3(
            accept_synthetic_semantics
        )
        self.arm_pins = {
            "expected_dispatch_resolution_sha256": self.resolution["resolution_sha256"],
            "expected_full_publication_execution_binding": self.execution,
            "expected_resource_capability_grant_sha256": "9" * 64,
            "expected_model_parity_grant_sha256": "a" * 64,
            "expected_model_parity_acceptance_binding_sha256": "b" * 64,
            "expected_launcher_evidence_files": self.evidence,
        }
        self._set_arm("success")

    def _project_descriptor(self, path: Path) -> dict[str, object]:
        info = path.stat()
        return {
            "path": path.relative_to(self.project_root).as_posix(),
            "size_bytes": int(info.st_size),
            "sha256": _sha_file(path),
        }

    def _set_arm(
        self, mode: str, *, extra_dataset: dict[str, object] | None = None
    ) -> None:
        self.runtime_inputs = {
            **self.coordinate,
            "scenario": "checkpoint_video_dag_shared",
            "dataset": {
                "name": "synthetic-kpp",
                "split": "test",
                "synthetic_process_fixture_mode": mode,
                "synthetic_stdout_hex": b"stdout\x00\xff\n".hex(),
                "synthetic_stderr_hex": b"stderr\x00\xfe\n".hex(),
                **(extra_dataset or {}),
            },
            "streams": 6,
            "duration_s": 30,
            "repeat_index": 0,
            "base_seed": 20260323,
            "run_seed": 8675309,
            "run_id": "run-0001",
            "project_root": str(self.project_root),
            "output_dir": str(self.output_dir),
            "arm_contract_path": str(self.arm_path),
        }
        self.arm = dispatch.build_backend_publication_arm_contract_v3(
            dispatch_resolution=self.resolution,
            full_publication_execution_binding=self.execution,
            resource_capability_grant_sha256="9" * 64,
            model_parity_grant_sha256="a" * 64,
            model_parity_acceptance_binding_sha256="b" * 64,
            runtime_inputs=self.runtime_inputs,
            launcher_evidence_files=self.evidence,
        )
        self.arm_pins["expected_runtime_inputs"] = self.runtime_inputs

    def _prepare(self) -> dict[str, object]:
        return production.prepare_backend_publication_production_transaction_v3(
            output_dir=self.output_dir,
            arm_contract=self.arm,
        )

    def _arguments(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "project_root": self.project_root,
            "output_dir": self.output_dir,
            "expected_arm_contract_file_sha256": hashlib.sha256(
                dispatch.canonical_backend_publication_arm_contract_bytes_v3(self.arm)
            ).hexdigest(),
            "execution_scope": production.PRODUCTION_EXECUTION_SCOPE,
            "expected_semantic_validator_identity_sha256": self.validator_identity,
            "semantic_evidence_validator": accept_synthetic_semantics,
            **self.dispatch_pins,
            **self.arm_pins,
        }
        values.update(overrides)
        return values

    def _run(self, **overrides: object) -> dict[str, object]:
        return production.run_or_resume_backend_publication_production_transaction_v3(
            **self._arguments(**overrides)
        )

    def _durable_parent_pin(self, state: str) -> dict[str, object]:
        names = {
            "result": dispatch.LAUNCHER_RESULT_FILENAME,
            "receipt_intent": dispatch.OUTPUT_RECEIPT_FILENAME,
            "committed": dispatch.OUTPUT_RECEIPT_FILENAME,
        }
        path = self.output_dir / names[state]
        payload = path.read_bytes()
        return {
            "state": state,
            "path": path.name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    @unittest.skipIf(os.name == "nt", "bootstrap hard-crash recovery is POSIX")
    def test_prepare_bootstrap_all_physical_windows_retry_same_path(self) -> None:
        steps = (
            "bootstrap_intent:mid_write",
            "bootstrap_intent:post_fsync_pre_publish",
            "bootstrap_intent:post_publish_pre_parent_fsync",
            "bootstrap_directory:post_create_fsync",
            "arm_contract:mid_write",
            "arm_contract:post_fsync_pre_publish",
            "arm_contract:post_publish_pre_parent_fsync",
            "transaction_directory:mid_write",
            "transaction_directory:post_fsync_pre_publish",
            "transaction_directory:post_publish_pre_parent_fsync",
            "bootstrap_receipt:mid_write",
            "bootstrap_receipt:post_fsync_pre_publish",
            "bootstrap_receipt:post_publish_pre_parent_fsync",
        )
        base = Path(self.temporary.name).resolve(strict=True)
        for index, step in enumerate(steps):
            with self.subTest(step=step):
                case = base / f"bootstrap-window-{index:02d}"
                case.mkdir()
                self.output_dir = case / "transaction"
                self.arm_path = self.output_dir / dispatch.ARM_CONTRACT_FILENAME
                self._set_arm("success")
                child = os.fork()
                if child == 0:
                    def crash(observed: str) -> None:
                        if observed == step:
                            os._exit(73)

                    try:
                        production.prepare_backend_publication_production_transaction_v3(
                            output_dir=self.output_dir,
                            arm_contract=self.arm,
                            after_bootstrap_step=crash,
                        )
                    except BaseException:
                        os._exit(74)
                    os._exit(75)
                _pid, status = os.waitpid(child, 0)
                self.assertTrue(os.WIFEXITED(status), status)
                self.assertEqual(os.WEXITSTATUS(status), 73, step)
                output_identity = None
                arm_identity = None
                if self.output_dir.is_dir() and self.arm_path.is_file():
                    output_info = self.output_dir.stat()
                    arm_info = self.arm_path.stat()
                    output_identity = (output_info.st_dev, output_info.st_ino)
                    arm_identity = (arm_info.st_dev, arm_info.st_ino)
                authority = self._prepare()
                self.assertEqual(
                    authority["status"], "prepared_production_arm_not_executed"
                )
                self.assertEqual(
                    {item.name for item in self.output_dir.iterdir()},
                    {dispatch.ARM_CONTRACT_FILENAME},
                )
                if output_identity is not None and arm_identity is not None:
                    output_info = self.output_dir.stat()
                    arm_info = self.arm_path.stat()
                    self.assertEqual(
                        (output_info.st_dev, output_info.st_ino), output_identity
                    )
                    self.assertEqual((arm_info.st_dev, arm_info.st_ino), arm_identity)
                repeated = self._prepare()
                self.assertEqual(repeated, authority)

                paths = production.engineering._bootstrap_paths_v1(
                    custody_root=self.output_dir.parent,
                    output_dir=self.output_dir,
                )
                stage = self.output_dir.parent.joinpath(
                    *Path(paths["stage"]).parts
                )
                if stage.exists():
                    self.assertEqual(
                        {item.name for item in stage.iterdir()},
                        {dispatch.ARM_CONTRACT_FILENAME},
                    )
                    self.assertEqual(
                        (stage / dispatch.ARM_CONTRACT_FILENAME).read_bytes(),
                        self.arm_path.read_bytes(),
                    )

    @unittest.skipIf(os.name == "nt", "foreign bootstrap custody is POSIX")
    def test_prepare_rejects_foreign_precreated_exact_arm_namespace(self) -> None:
        self.output_dir.mkdir(mode=0o700)
        payload = dispatch.canonical_backend_publication_arm_contract_bytes_v3(
            self.arm
        )
        self.arm_path.write_bytes(payload)
        self.arm_path.chmod(0o600)
        output_info = self.output_dir.stat()
        arm_info = self.arm_path.stat()
        expected_output = (output_info.st_dev, output_info.st_ino)
        expected_arm = (arm_info.st_dev, arm_info.st_ino)
        with self.assertRaisesRegex(Exception, "directory commit/adoption failed"):
            self._prepare()
        self.assertEqual(self.arm_path.read_bytes(), payload)
        output_info = self.output_dir.stat()
        arm_info = self.arm_path.stat()
        self.assertEqual((output_info.st_dev, output_info.st_ino), expected_output)
        self.assertEqual((arm_info.st_dev, arm_info.st_ino), expected_arm)

    @unittest.skipIf(os.name == "nt", "bootstrap ABA custody is POSIX")
    def test_prepare_rejects_directory_aba_during_publish_and_on_retry(self) -> None:
        payload = dispatch.canonical_backend_publication_arm_contract_bytes_v3(
            self.arm
        )
        moved = self.output_dir.parent / "transaction-owned-moved"
        attacker_identity: tuple[int, int] | None = None

        def replace(step: str) -> None:
            nonlocal attacker_identity
            if step != "transaction_directory:post_publish_pre_parent_fsync":
                return
            self.output_dir.rename(moved)
            self.output_dir.mkdir(mode=0o700)
            self.arm_path.write_bytes(payload)
            self.arm_path.chmod(0o600)
            info = self.output_dir.stat()
            attacker_identity = (info.st_dev, info.st_ino)

        with self.assertRaisesRegex(Exception, "directory commit/adoption failed"):
            production.prepare_backend_publication_production_transaction_v3(
                output_dir=self.output_dir,
                arm_contract=self.arm,
                after_bootstrap_step=replace,
            )
        self.assertIsNotNone(attacker_identity)
        self.assertTrue((moved / dispatch.ARM_CONTRACT_FILENAME).is_file())
        self.assertEqual(self.arm_path.read_bytes(), payload)
        info = self.output_dir.stat()
        self.assertEqual((info.st_dev, info.st_ino), attacker_identity)
        with self.assertRaisesRegex(Exception, "directory commit/adoption failed"):
            self._prepare()
        info = self.output_dir.stat()
        self.assertEqual((info.st_dev, info.st_ino), attacker_identity)

    def _bootstrap_cleanup_case(
        self, name: str
    ) -> tuple[
        Path,
        Path,
        Path,
        dict[str, str],
        bytes,
        tuple[int, int],
        tuple[int, int],
    ]:
        bootstrap_root = Path(self.temporary.name).resolve(strict=True) / name
        bootstrap_root.mkdir(mode=0o700)
        output = bootstrap_root / "transaction"
        output.mkdir(mode=0o700)
        payload = dispatch.canonical_backend_publication_arm_contract_bytes_v3(
            self.arm
        )
        final_arm = output / dispatch.ARM_CONTRACT_FILENAME
        final_arm.write_bytes(payload)
        final_arm.chmod(0o600)
        paths = production.engineering._bootstrap_paths_v1(
            custody_root=bootstrap_root,
            output_dir=output,
        )
        stage = bootstrap_root.joinpath(*Path(paths["stage"]).parts)
        stage.mkdir(mode=0o700)
        stage_arm = stage / dispatch.ARM_CONTRACT_FILENAME
        stage_arm.write_bytes(payload)
        stage_arm.chmod(0o600)
        final_info = output.stat()
        final_arm_info = final_arm.stat()
        return (
            bootstrap_root,
            output,
            stage,
            paths,
            payload,
            (int(final_info.st_dev), int(final_info.st_ino)),
            (int(final_arm_info.st_dev), int(final_arm_info.st_ino)),
        )

    @unittest.skipIf(os.name == "nt", "anchored staging cleanup is POSIX")
    def test_adopted_bootstrap_cleanup_rejects_stage_rebind_without_deletion(self) -> None:
        (
            bootstrap_root,
            output,
            stage,
            paths,
            payload,
            final_identity,
            final_arm_identity,
        ) = self._bootstrap_cleanup_case("cleanup-rebind")
        with production.engineering.PhysicalRootCustodyV1.open(
            bootstrap_root, label="bootstrap cleanup test root"
        ) as custody:
            _mode, expected_stage_identity = custody.stat_directory_identity(
                paths["stage"], label="owned bootstrap stage"
            )
            stage_arm_info = (stage / dispatch.ARM_CONTRACT_FILENAME).stat()
            expected_stage_arm_identity = (
                int(stage_arm_info.st_dev),
                int(stage_arm_info.st_ino),
            )
            moved = bootstrap_root / "owned-stage-moved"
            stage.rename(moved)
            stage.mkdir(mode=0o700)
            foreign_arm = stage / dispatch.ARM_CONTRACT_FILENAME
            foreign_arm.write_bytes(payload)
            foreign_arm.chmod(0o600)
            foreign_identity = foreign_arm.stat()
            with self.assertRaisesRegex(Exception, "staging directory was rebound"):
                production.engineering._remove_exact_bootstrap_stage_v1(
                    custody,
                    paths=paths,
                    stage_path=stage,
                    expected_directory_identity=expected_stage_identity,
                    expected_arm_identity=expected_stage_arm_identity,
                )
        self.assertEqual(foreign_arm.read_bytes(), payload)
        self.assertEqual(
            (foreign_arm.stat().st_dev, foreign_arm.stat().st_ino),
            (foreign_identity.st_dev, foreign_identity.st_ino),
        )
        self.assertEqual(
            (moved / dispatch.ARM_CONTRACT_FILENAME).read_bytes(), payload
        )
        self.assertEqual((output.stat().st_dev, output.stat().st_ino), final_identity)
        final_arm = output / dispatch.ARM_CONTRACT_FILENAME
        self.assertEqual(
            (final_arm.stat().st_dev, final_arm.stat().st_ino), final_arm_identity
        )

    @unittest.skipIf(os.name == "nt", "anchored staging cleanup is POSIX")
    def test_adopted_bootstrap_cleanup_rejects_extra_entry_before_arm_unlink(self) -> None:
        (
            bootstrap_root,
            output,
            stage,
            paths,
            payload,
            final_identity,
            final_arm_identity,
        ) = self._bootstrap_cleanup_case("cleanup-extra")
        stage_arm = stage / dispatch.ARM_CONTRACT_FILENAME
        stage_arm_info = stage_arm.stat()
        extra = stage / "foreign-entry"
        extra.write_bytes(b"foreign")
        with production.engineering.PhysicalRootCustodyV1.open(
            bootstrap_root, label="bootstrap cleanup test root"
        ) as custody:
            _mode, expected_stage_identity = custody.stat_directory_identity(
                paths["stage"], label="owned bootstrap stage"
            )
            with self.assertRaisesRegex(Exception, "staging namespace is foreign"):
                production.engineering._remove_exact_bootstrap_stage_v1(
                    custody,
                    paths=paths,
                    stage_path=stage,
                    expected_directory_identity=expected_stage_identity,
                    expected_arm_identity=(
                        int(stage_arm_info.st_dev),
                        int(stage_arm_info.st_ino),
                    ),
                )
        self.assertEqual(stage_arm.read_bytes(), payload)
        self.assertEqual(extra.read_bytes(), b"foreign")
        self.assertEqual((output.stat().st_dev, output.stat().st_ino), final_identity)
        final_arm = output / dispatch.ARM_CONTRACT_FILENAME
        self.assertEqual(
            (final_arm.stat().st_dev, final_arm.stat().st_ino), final_arm_identity
        )

    @unittest.skipIf(os.name == "nt", "anchored staging cleanup is POSIX")
    def test_adopted_bootstrap_cleanup_rejects_hardlinked_arm_before_unlink(self) -> None:
        (
            bootstrap_root,
            output,
            stage,
            paths,
            payload,
            final_identity,
            final_arm_identity,
        ) = self._bootstrap_cleanup_case("cleanup-hardlink")
        stage_arm = stage / dispatch.ARM_CONTRACT_FILENAME
        external_link = bootstrap_root / "foreign-arm-link"
        os.link(stage_arm, external_link)
        stage_arm_info = stage_arm.stat()
        self.assertEqual(stage_arm_info.st_nlink, 2)
        with production.engineering.PhysicalRootCustodyV1.open(
            bootstrap_root, label="bootstrap cleanup test root"
        ) as custody:
            _mode, expected_stage_identity = custody.stat_directory_identity(
                paths["stage"], label="owned bootstrap stage"
            )
            with self.assertRaisesRegex(Exception, "staging arm is not uniquely owned"):
                production.engineering._remove_exact_bootstrap_stage_v1(
                    custody,
                    paths=paths,
                    stage_path=stage,
                    expected_directory_identity=expected_stage_identity,
                    expected_arm_identity=(
                        int(stage_arm_info.st_dev),
                        int(stage_arm_info.st_ino),
                    ),
                )
        self.assertEqual(stage_arm.read_bytes(), payload)
        self.assertEqual(external_link.read_bytes(), payload)
        self.assertEqual(stage_arm.stat().st_nlink, 2)
        self.assertEqual((output.stat().st_dev, output.stat().st_ino), final_identity)
        final_arm = output / dispatch.ARM_CONTRACT_FILENAME
        self.assertEqual(
            (final_arm.stat().st_dev, final_arm.stat().st_ino), final_arm_identity
        )

    def test_success_commits_distinct_publishable_receipt_and_read_only_authority(self) -> None:
        prepared = self._prepare()
        self.assertEqual(prepared["status"], "prepared_production_arm_not_executed")
        authority = self._run()
        self.assertEqual(authority["artifact_kind"], production.RECEIPT_AUTHORITY_KIND)
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        for field in production.PRODUCTION_ACCEPTANCE_CLAIM_FIELDS:
            self.assertIs(authority[field], True)
        self.assertNotIn("nonpublication", str(authority))
        expected_names = {
            dispatch.ARM_CONTRACT_FILENAME,
            dispatch.LAUNCH_FENCE_FILENAME,
            dispatch.CAPTURE_STDOUT_FILENAME,
            dispatch.CAPTURE_STDERR_FILENAME,
            dispatch.LAUNCHER_RESULT_FILENAME,
            dispatch.OUTPUT_RECEIPT_FILENAME,
            *self.evidence,
        }
        self.assertEqual({item.name for item in self.output_dir.iterdir()}, expected_names)
        snapshot = {item.name: item.read_bytes() for item in self.output_dir.iterdir()}
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("committed validation spawned child"),
        ):
            with self.assertRaisesRegex(Exception, "durable parent artifact pin"):
                production.validate_backend_publication_production_transaction_v3(
                    **self._arguments()
                )
            repeated = production.validate_backend_publication_production_transaction_v3(
                **self._arguments(
                    expected_durable_parent_artifact_pin=(
                        self._durable_parent_pin("committed")
                    )
                )
            )
        self.assertEqual(repeated, authority)
        self.assertEqual(
            {item.name: item.read_bytes() for item in self.output_dir.iterdir()}, snapshot
        )

    def test_rejected_semantic_evidence_never_creates_publishable_result_or_receipt(self) -> None:
        self._prepare()

        with self.assertRaisesRegex(Exception, "semantic evidence was rejected"):
            self._run(
                expected_semantic_validator_identity_sha256=(
                    production.semantic_evidence_validator_identity_v3(
                        reject_synthetic_semantics
                    )
                ),
                semantic_evidence_validator=reject_synthetic_semantics,
            )
        self.assertTrue((self.output_dir / dispatch.CAPTURE_STDOUT_FILENAME).is_file())
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())

    def test_fence_only_attempt_is_ambiguous_and_never_relaunched(self) -> None:
        self._prepare()

        def stop_after_fence(phase: str) -> None:
            if phase == "after_fence_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(_fault_hook=stop_after_fence)
        self.assertTrue((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).is_file())
        with mock.patch.object(
            production.process_supervisor.subprocess,
            "Popen",
            side_effect=AssertionError("fence-only resume relaunched child"),
        ):
            with self.assertRaisesRegex(Exception, "orphaned"):
                self._run()

    @unittest.skipIf(os.name == "nt", "production durable broker recovery is POSIX")
    def test_killed_production_coordinator_live_broker_resumes_without_rerun(self) -> None:
        counter = Path(self.temporary.name).resolve(strict=True) / "spawn-count.txt"
        self._set_arm(
            "delayed_success",
            extra_dataset={
                "synthetic_delay_seconds": 1.5,
                "synthetic_spawn_counter_path": str(counter),
            },
        )
        self._prepare()
        coordinator = os.fork()
        if coordinator == 0:
            try:
                self._run(durable_parent_artifact_pin_sink=lambda _pin: None)
            except BaseException:
                os._exit(93)
            os._exit(0)
        fence = self.output_dir / dispatch.LAUNCH_FENCE_FILENAME
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if fence.is_file() and counter.is_file():
                break
            time.sleep(0.02)
        else:
            os.kill(coordinator, signal.SIGKILL)
            os.waitpid(coordinator, 0)
            self.fail("production durable broker did not launch")
        os.kill(coordinator, signal.SIGKILL)
        os.waitpid(coordinator, 0)
        pins: list[dict[str, object]] = []
        authority = self._run(
            durable_parent_artifact_pin_sink=lambda pin: pins.append(
                copy.deepcopy(pin)
            )
        )
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertEqual(counter.read_text(encoding="ascii"), "spawn\n")
        self.assertEqual([pin["state"] for pin in pins], [
            "result", "receipt_intent", "committed"
        ])

    def test_result_only_resume_finalizes_receipt_without_spawn(self) -> None:
        self._prepare()

        def stop_after_result(phase: str) -> None:
            if phase == "after_result_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(_fault_hook=stop_after_result)
        self.assertTrue((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).is_file())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
        parent_pin = self._durable_parent_pin("result")
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("result-only resume spawned child"),
        ):
            authority = self._run(expected_durable_parent_artifact_pin=parent_pin)
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())

    def test_parent_pin_sink_closes_result_and_receipt_crash_windows(self) -> None:
        self._prepare()
        persisted: list[dict[str, object]] = []

        def persist(pin: dict[str, object]) -> None:
            persisted.append(copy.deepcopy(pin))

        def stop_after_result(phase: str) -> None:
            if phase == "after_result_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(
                durable_parent_artifact_pin_sink=persist,
                _fault_hook=stop_after_result,
            )
        self.assertEqual(persisted, [self._durable_parent_pin("result")])

        committed: list[dict[str, object]] = []
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("result-only resume spawned child"),
        ):
            authority = self._run(
                expected_durable_parent_artifact_pin=persisted[0],
                durable_parent_artifact_pin_sink=lambda pin: committed.append(
                    copy.deepcopy(pin)
                ),
            )
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertEqual(
            committed,
            [
                self._durable_parent_pin("receipt_intent"),
                self._durable_parent_pin("committed"),
            ],
        )

    def test_receipt_intent_resume_creates_receipt_without_spawn(self) -> None:
        self._prepare()
        persisted: list[dict[str, object]] = []

        def persist(pin: dict[str, object]) -> None:
            persisted.append(copy.deepcopy(pin))

        def stop_after_intent(phase: str) -> None:
            if phase == "after_receipt_intent_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(
                durable_parent_artifact_pin_sink=persist,
                _fault_hook=stop_after_intent,
            )
        self.assertEqual(
            [pin["state"] for pin in persisted],
            ["result", "receipt_intent"],
        )
        self.assertFalse(
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists()
        )
        promoted: list[dict[str, object]] = []
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("receipt-intent resume spawned child"),
        ):
            authority = self._run(
                expected_durable_parent_artifact_pin=persisted[-1],
                durable_parent_artifact_pin_sink=lambda pin: promoted.append(
                    copy.deepcopy(pin)
                ),
            )
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertEqual([pin["state"] for pin in promoted], ["committed"])

    def test_receipt_file_with_only_intent_promotes_without_spawn(self) -> None:
        self._prepare()
        persisted: list[dict[str, object]] = []

        def stop_after_receipt_file(phase: str) -> None:
            if phase == "after_receipt_file_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(
                durable_parent_artifact_pin_sink=lambda pin: persisted.append(
                    copy.deepcopy(pin)
                ),
                _fault_hook=stop_after_receipt_file,
            )
        self.assertEqual(
            [pin["state"] for pin in persisted],
            ["result", "receipt_intent"],
        )
        self.assertTrue(
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file()
        )
        promoted: list[dict[str, object]] = []
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("committed-intent resume spawned child"),
        ):
            authority = self._run(
                expected_durable_parent_artifact_pin=persisted[-1],
                durable_parent_artifact_pin_sink=lambda pin: promoted.append(
                    copy.deepcopy(pin)
                ),
            )
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertEqual([pin["state"] for pin in promoted], ["committed"])

    def test_committed_pin_sink_failure_is_recoverable_without_spawn(self) -> None:
        self._prepare()
        persisted: list[dict[str, object]] = []

        def fail_committed(pin: dict[str, object]) -> None:
            if pin["state"] == "committed":
                raise RuntimeError("simulated committed pin persistence failure")
            persisted.append(copy.deepcopy(pin))

        with self.assertRaisesRegex(RuntimeError, "simulated committed"):
            self._run(durable_parent_artifact_pin_sink=fail_committed)
        self.assertEqual(
            [pin["state"] for pin in persisted],
            ["result", "receipt_intent"],
        )
        self.assertTrue(
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file()
        )
        promoted: list[dict[str, object]] = []
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("committed sink recovery spawned child"),
        ):
            authority = self._run(
                expected_durable_parent_artifact_pin=persisted[-1],
                durable_parent_artifact_pin_sink=lambda pin: promoted.append(
                    copy.deepcopy(pin)
                ),
            )
        self.assertEqual(authority["status"], "accepted_publishable_backend_output")
        self.assertEqual([pin["state"] for pin in promoted], ["committed"])

    def test_real_parent_store_recovers_receipt_window_without_spawn(self) -> None:
        self._prepare()
        arm_sha = hashlib.sha256(
            dispatch.canonical_backend_publication_arm_contract_bytes_v3(self.arm)
        ).hexdigest()

        def stop_after_receipt_file(phase: str) -> None:
            if phase == "after_receipt_file_commit":
                raise SyntheticProductionAbort()

        with ProductionParentArtifactPinStoreV1(
            project_root=self.project_root,
            output_dir=self.output_dir,
            arm_contract_file_sha256=arm_sha,
            execution_binding=self.execution,
        ) as store:
            self.assertIsNone(store.load_expected_pin())
            with self.assertRaises(SyntheticProductionAbort):
                self._run(
                    durable_parent_artifact_pin_sink=store,
                    _fault_hook=stop_after_receipt_file,
                )
            expected = store.load_expected_pin()
            self.assertEqual(expected["state"], "receipt_intent")
            with mock.patch.object(
                production,
                "run_backend_publication_process_v3",
                side_effect=AssertionError("real-store resume spawned child"),
            ):
                authority = self._run(
                    expected_durable_parent_artifact_pin=expected,
                    durable_parent_artifact_pin_sink=store,
                )
            self.assertEqual(
                authority["status"],
                "accepted_publishable_backend_output",
            )
            self.assertEqual(store.load_expected_pin()["state"], "committed")

    def test_result_only_resume_without_durable_parent_pin_is_ambiguous(self) -> None:
        self._prepare()

        def stop_after_result(phase: str) -> None:
            if phase == "after_result_commit":
                raise SyntheticProductionAbort()

        with self.assertRaises(SyntheticProductionAbort):
            self._run(_fault_hook=stop_after_result)
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("untrusted result resume spawned child"),
        ):
            with self.assertRaisesRegex(Exception, "durable parent artifact pin"):
                self._run()
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())

    def test_receipt_is_last_and_tamper_fails_read_only_validation(self) -> None:
        self._prepare()
        phases: list[str] = []

        def observe_order(phase: str) -> None:
            phases.append(phase)
            if phase == "after_captures_commit":
                self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
                self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
            if phase == "after_result_commit":
                self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
            if phase == "after_receipt_intent_commit":
                self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
            if phase == "after_receipt_file_commit":
                self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())
            if phase == "after_receipt_commit":
                self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())

        self._run(_fault_hook=observe_order)
        self.assertLess(phases.index("after_result_commit"), phases.index("after_receipt_commit"))
        self.assertLess(
            phases.index("after_receipt_intent_commit"),
            phases.index("after_receipt_file_commit"),
        )
        self.assertLess(
            phases.index("after_receipt_file_commit"),
            phases.index("after_receipt_commit"),
        )
        receipt = self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME
        committed_pin = self._durable_parent_pin("committed")
        payload = bytearray(receipt.read_bytes())
        payload[len(payload) // 2] ^= 1
        receipt.write_bytes(payload)
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("tamper validation spawned child"),
        ):
            with self.assertRaises(Exception):
                production.validate_backend_publication_production_transaction_v3(
                    **self._arguments(
                        expected_durable_parent_artifact_pin=committed_pin
                    )
                )

    def test_accept_all_callback_cannot_impersonate_pinned_validator(self) -> None:
        self._prepare()
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("validator impersonation crossed launch fence"),
        ):
            with self.assertRaisesRegex(Exception, "validator identity"):
                self._run(semantic_evidence_validator=accept_all_semantics)
        self.assertFalse((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).exists())

    @unittest.skipIf(os.name == "nt", "POSIX held-fd execution only")
    def test_transient_parent_swap_never_executes_replacement_python_or_launcher(self) -> None:
        project = Path(self.temporary.name).resolve(strict=True) / "held-project"
        runtime = project / "runtime"
        launchers = project / "launchers"
        supervisor_runtime = project / "supervisor-runtime"
        runtime_bin = runtime / "bin"
        runtime_bin.mkdir(parents=True)
        launchers.mkdir(parents=True)
        supervisor_runtime.mkdir(parents=True)
        python = runtime_bin / "python"
        launcher = launchers / "launcher.py"
        supervisor_source = (
            supervisor_runtime / Path(production.process_supervisor.__file__).name
        )
        invocation_source = (
            supervisor_runtime / "backend_publication_launcher_invocation_v3.py"
        )
        shutil.copy2(self.python_path, python, follow_symlinks=True)
        python.chmod(0o700)
        evidence_literal = repr(self.evidence)
        launcher.write_text(
            "import sys, time\n"
            "from pathlib import Path\n"
            "time.sleep(0.25)\n"
            "output = Path(sys.argv[8])\n"
            f"for name in {evidence_literal}:\n"
            "    (output / name).write_bytes("
            "b'VAST:synthetic-backend-publication-evidence:v3\\0' "
            "+ name.encode('ascii') + b'\\n')\n",
            encoding="ascii",
        )
        launcher.chmod(0o600)
        shutil.copy2(
            Path(production.process_supervisor.__file__).resolve(strict=True),
            supervisor_source,
        )
        shutil.copy2(
            SCRIPTS / "backend_publication_launcher_invocation_v3.py",
            invocation_source,
        )

        self.project_root = project.resolve(strict=True)
        self.output_dir = self.project_root / "transaction"
        self.arm_path = self.output_dir / dispatch.ARM_CONTRACT_FILENAME
        self.python_descriptor = self._project_descriptor(python)
        self.launcher_descriptor = self._project_descriptor(launcher)
        self.dispatch_pins["expected_python_executable"] = self.python_descriptor
        self.dispatch_pins["expected_publication_launcher"] = self.launcher_descriptor
        self.resolution = dispatch.build_backend_publication_dispatch_resolution_v3(
            coordinate=self.coordinate,
            python_executable=self.python_descriptor,
            publication_launcher=self.launcher_descriptor,
            launcher_invocation=self.invocation,
            backend_runtime_grant_sha256="3" * 64,
            identity_artifact_binding_sha256="4" * 64,
            cell_identity_sha256="5" * 64,
            validation_record_sha256="6" * 64,
            runtime_binding_identity_sha256="7" * 64,
        )
        self.arm_pins["expected_dispatch_resolution_sha256"] = self.resolution[
            "resolution_sha256"
        ]
        self._set_arm("success")
        self._prepare()

        python_marker = project / "replacement-python-executed"
        launcher_marker = project / "replacement-launcher-executed"
        supervisor_marker = project / "replacement-supervisor-executed"
        held_runtime = project / "runtime-held"
        held_launchers = project / "launchers-held"
        held_supervisor_runtime = project / "supervisor-runtime-held"
        restore_thread: threading.Thread | None = None

        def restore_originals() -> None:
            time.sleep(0.10)
            shutil.rmtree(runtime)
            shutil.rmtree(launchers)
            shutil.rmtree(supervisor_runtime)
            held_runtime.rename(runtime)
            held_launchers.rename(launchers)
            held_supervisor_runtime.rename(supervisor_runtime)

        def transient_swap(phase: str) -> None:
            nonlocal restore_thread
            if phase != "after_fence_commit":
                return
            runtime.rename(held_runtime)
            launchers.rename(held_launchers)
            supervisor_runtime.rename(held_supervisor_runtime)
            runtime_bin.mkdir(parents=True)
            launchers.mkdir(parents=True)
            supervisor_runtime.mkdir(parents=True)
            python.write_text(
                "#!/bin/sh\n"
                f"printf owned > '{python_marker}'\n"
                f"exec '{self.python_path}' \"$@\"\n",
                encoding="ascii",
            )
            python.chmod(0o700)
            launcher.write_text(
                "import sys, time\n"
                "from pathlib import Path\n"
                f"Path({str(launcher_marker)!r}).write_text('owned')\n"
                "time.sleep(0.25)\n"
                "output = Path(sys.argv[8])\n"
                f"for name in {evidence_literal}:\n"
                "    (output / name).write_bytes("
                "b'VAST:synthetic-backend-publication-evidence:v3\\0' "
                "+ name.encode('ascii') + b'\\n')\n",
                encoding="ascii",
            )
            supervisor_source.write_text(
                "from pathlib import Path\n"
                f"Path({str(supervisor_marker)!r}).write_text('owned')\n"
                "raise SystemExit(97)\n",
                encoding="ascii",
            )
            restore_thread = threading.Thread(target=restore_originals)
            restore_thread.start()

        authority: dict[str, object] | None = None
        secure_failure: BaseException | None = None
        try:
            with mock.patch.object(
                production.process_supervisor,
                "__file__",
                str(supervisor_source),
            ):
                authority = self._run(_fault_hook=transient_swap)
        except production.BackendPublicationOutputProductionV3Error as error:
            secure_failure = error
        finally:
            if restore_thread is not None:
                restore_thread.join(timeout=5.0)
        self.assertFalse(python_marker.exists())
        self.assertFalse(launcher_marker.exists())
        self.assertFalse(supervisor_marker.exists())
        if secure_failure is None:
            assert authority is not None
            self.assertEqual(authority["status"], "accepted_publishable_backend_output")

    @unittest.skipIf(os.name == "nt", "WSL runtime bind contract only")
    def test_canonical_wsl_venv_requires_plain_copied_python(self) -> None:
        runtime_root = (
            Path.home()
            / ".local/state/vast/publication/runtime/full-publication-cp312-v1"
        )
        if not runtime_root.is_dir():
            self.skipTest("canonical WSL publication venv is not installed")
        python_entry = runtime_root / "bin/python"
        mount_relative = ".publication-runtime/full-publication-cp312-v1"
        if python_entry.is_symlink():
            with self.assertRaisesRegex(Exception, "--copies"):
                production.build_production_runtime_bind_mount_contract_v3(
                    source_runtime_root=runtime_root,
                    project_runtime_mount=mount_relative,
                    source_python_relative_path="bin/python",
                )
            return
        mounted_python = ROOT / mount_relative / "bin/python"
        if not mounted_python.is_file():
            self.skipTest("canonical WSL publication venv bind is not mounted")
        mounted_info = mounted_python.stat()
        descriptor = {
            "path": f"{mount_relative}/bin/python",
            "size_bytes": int(mounted_info.st_size),
            "sha256": _sha_file(mounted_python),
        }
        contract = production.build_production_runtime_bind_mount_contract_v3(
            source_runtime_root=runtime_root,
            project_runtime_mount=mount_relative,
            source_python_relative_path="bin/python",
        )
        validated = production.preflight_production_runtime_bind_mount_v3(
            project_root=ROOT,
            expected_python_executable=descriptor,
            expected_binding=contract,
        )
        self.assertEqual(validated, contract)

    @unittest.skipIf(os.name == "nt", "POSIX runtime bind contract only")
    def test_runtime_copy_is_not_accepted_as_read_only_bind_mount(self) -> None:
        base = Path(self.temporary.name).resolve(strict=True)
        source_runtime = base / "external-runtime"
        source_bin = source_runtime / "bin"
        source_bin.mkdir(parents=True)
        source_python = source_bin / "python"
        shutil.copy2(self.python_path, source_python, follow_symlinks=True)
        source_python.chmod(0o700)
        project = base / "bind-project"
        project.mkdir()
        mount_relative = ".publication-runtime/full-publication-cp312-v1"
        copied_runtime = project / mount_relative
        shutil.copytree(source_runtime, copied_runtime)
        copied_python = copied_runtime / "bin/python"
        copied_info = copied_python.stat()
        descriptor = {
            "path": f"{mount_relative}/bin/python",
            "size_bytes": int(copied_info.st_size),
            "sha256": _sha_file(copied_python),
        }
        contract = production.build_production_runtime_bind_mount_contract_v3(
            source_runtime_root=source_runtime,
            project_runtime_mount=mount_relative,
            source_python_relative_path="bin/python",
        )
        with self.assertRaisesRegex(Exception, "read-only bind mount"):
            production.preflight_production_runtime_bind_mount_v3(
                project_root=project,
                expected_python_executable=descriptor,
                expected_binding=contract,
            )

    @unittest.skipIf(os.name == "nt", "POSIX runtime bind contract only")
    def test_runtime_source_must_be_an_exact_read_only_ext4_mount(self) -> None:
        base = Path(self.temporary.name).resolve(strict=True)
        source_runtime = base / "external-runtime"
        source_bin = source_runtime / "bin"
        source_bin.mkdir(parents=True)
        source_python = source_bin / "python"
        shutil.copy2(self.python_path, source_python, follow_symlinks=True)
        source_python.chmod(0o700)
        project = base / "bind-project"
        project.mkdir()
        mount_relative = ".publication-runtime/full-publication-cp312-v1"
        copied_runtime = project / mount_relative
        shutil.copytree(source_runtime, copied_runtime)
        copied_python = copied_runtime / "bin/python"
        copied_info = copied_python.stat()
        descriptor = {
            "path": f"{mount_relative}/bin/python",
            "size_bytes": int(copied_info.st_size),
            "sha256": _sha_file(copied_python),
        }
        contract = production.build_production_runtime_bind_mount_contract_v3(
            source_runtime_root=source_runtime,
            project_runtime_mount=mount_relative,
            source_python_relative_path="bin/python",
        )
        fake_mounts = [
            (str(copied_runtime), frozenset({"ro"}), "ext4"),
            (str(source_runtime), frozenset({"rw"}), "ext4"),
        ]
        with mock.patch.object(
            production,
            "_linux_mountinfo_v3",
            return_value=fake_mounts,
        ):
            with self.assertRaisesRegex(Exception, "source.*read-only"):
                production.preflight_production_runtime_bind_mount_v3(
                    project_root=project,
                    expected_python_executable=descriptor,
                    expected_binding=contract,
                )

    def test_child_cannot_precreate_parent_owned_receipt(self) -> None:
        self._prepare()
        real_run = production.run_backend_publication_process_v3
        attacker_payload = b"attacker-owned-production-receipt\n"

        def collide(*args: object, **kwargs: object) -> object:
            result = real_run(*args, **kwargs)
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).write_bytes(
                attacker_payload
            )
            return result

        with mock.patch.object(
            production, "run_backend_publication_process_v3", side_effect=collide
        ):
            with self.assertRaises(Exception):
                self._run()
        self.assertEqual(
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).read_bytes(),
            attacker_payload,
        )
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())

    def test_external_pin_drift_fails_before_spawn_and_again_on_reread(self) -> None:
        self._prepare()
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("invalid external pin spawned child"),
        ):
            with self.assertRaises(Exception):
                self._run(expected_resource_capability_grant_sha256="0" * 64)
        self.assertFalse((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).exists())
        self._run()
        committed_pin = self._durable_parent_pin("committed")
        with mock.patch.object(
            production,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("reread validation spawned child"),
        ):
            with self.assertRaises(Exception):
                production.validate_backend_publication_production_transaction_v3(
                    **self._arguments(
                        expected_resource_capability_grant_sha256="0" * 64,
                        expected_durable_parent_artifact_pin=committed_pin,
                    )
                )


if __name__ == "__main__":
    unittest.main()
