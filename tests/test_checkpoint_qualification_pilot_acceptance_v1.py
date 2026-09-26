from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_qualification_pilot_acceptance_v1 as target  # noqa: E402
from benchmark_contract import ContractError  # noqa: E402
from checkpoint_publication_runtime import (  # noqa: E402
    commit_checkpoint_publication_acceptance,
)
from publication_acceptance_evidence import (  # noqa: E402
    accepted_arm_evidence_files,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class _Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.output_dir = (
            root / "pilots/deepstream/gpu/h264/shared_video_dag"
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = "qualification-run-deepstream-gpu-h264-shared-0001"
        self.arm_id = "qualification-pilot.deepstream.gpu.h264.shared_video_dag.v1"
        self.policy_contract_sha256 = "a" * 64
        self.hardware_resource_collector_path = root / "scripts/collect_metrics.py"
        self.hardware_resource_collector_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        self.hardware_resource_collector_path.write_bytes(
            b"# qualification collector fixture\n"
        )

        evidence_names = accepted_arm_evidence_files(
            "gpu_only", full_resource=True
        )
        if len(evidence_names) != 14:
            raise AssertionError("fixture expects the frozen exact 14-file set")
        self.evidence_sha256: dict[str, str] = {}
        for name in evidence_names:
            path = self.output_dir / name
            path.write_bytes(f"physical:{name}:{self.run_id}\n".encode("ascii"))
            self.evidence_sha256[name] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()

        self.candidate_manifest_path = root / "bootstrap/candidate/manifest.json"
        self.qualification_index_path = root / "bootstrap/candidate/index.json"
        self.candidate_receipt_path = root / "bootstrap/candidate/receipt.json"
        candidate_manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_capability_manifest",
            "policy_contract_sha256": self.policy_contract_sha256,
            "systems": {system: {"branches": {}} for system in SYSTEMS},
        }
        _write_json(self.candidate_manifest_path, candidate_manifest)
        candidate_index = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_index",
            "policy_contract_sha256": self.policy_contract_sha256,
            "dataset_manifest": {
                "path": "configs/datasets.yaml",
                "size_bytes": 1,
                "sha256": "b" * 64,
            },
            "bindings": [],
            "pilots": [],
        }
        _write_json(self.qualification_index_path, candidate_index)
        candidate_receipt = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_publication_policy_qualification_candidate_receipt"
            ),
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": self.policy_contract_sha256,
            "qualification_index": _descriptor(
                root, self.qualification_index_path
            ),
            "candidate_manifest": _descriptor(
                root, self.candidate_manifest_path
            ),
            "blockers": [
                "candidate_is_not_a_full_publication_authority",
                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
            ],
        }
        candidate_receipt["sha256"] = _canonical_sha(candidate_receipt)
        _write_json(self.candidate_receipt_path, candidate_receipt)

        parity_dir = root / "accepted-parity"
        self.parity_manifest_path = parity_dir / "manifest.yaml"
        self.parity_assessment_path = parity_dir / "assessment.json"
        self.parity_receipt_path = parity_dir / "receipt.json"
        self.transaction_path = parity_dir / "transaction_index.json"
        self.parity_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.parity_manifest_path.write_text("schema_version: 3\n", encoding="utf-8")
        _write_json(self.parity_assessment_path, {"accepted": True})
        _write_json(self.parity_receipt_path, {"accepted": True})
        _write_json(self.transaction_path, {"schema_version": 2})
        transaction = {
            **_descriptor(root, self.transaction_path),
            "transaction_sha256": "1" * 64,
            "files_sha256": "2" * 64,
            "output_segments_sha256": "3" * 64,
            "execution_bundle_count": 480,
            "execution_bundles_sha256": "4" * 64,
        }
        binding = {
            "schema_version": 2,
            "artifact_kind": "vast_verified_model_parity_acceptance_binding",
            "receipt": _descriptor(root, self.parity_receipt_path),
            "accepted_manifest": _descriptor(root, self.parity_manifest_path),
            "accepted_assessment": _descriptor(root, self.parity_assessment_path),
            "evidence_sha256": "5" * 64,
            "transaction_index": transaction,
        }
        binding["binding_sha256"] = _canonical_sha(binding)
        self.parity_binding = binding

        bootstrap_dir = root / "bootstrap/materialized"
        self.bootstrap_mapping_path = bootstrap_dir / (
            "checkpoint_policy_qualification_bootstrap_mapping.v2.json"
        )
        self.bootstrap_receipt_path = bootstrap_dir / (
            "checkpoint_policy_qualification_bootstrap_receipt.v2.json"
        )
        self.bootstrap_calibration_paths: dict[str, Path] = {}
        physical_sha = _canonical_sha([])
        calibrations: dict[str, dict[str, object]] = {}
        for system in SYSTEMS:
            calibration = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": self.policy_contract_sha256,
                "costs": {},
                "status": "qualification_bootstrap_not_accepted",
                "accepted": False,
                "publication_ready": False,
                "scope": "forced_resource_qualification_pilots_only",
                "authority": "nonaccepted_qualification_bootstrap_v2",
                "source_candidate_manifest_sha256": _descriptor(
                    root, self.candidate_manifest_path
                )["sha256"],
                "source_model_parity_acceptance_binding_sha256": binding[
                    "binding_sha256"
                ],
                "source_physical_response_evidence_sha256": physical_sha,
            }
            path = bootstrap_dir / (
                "checkpoint_policy_qualification_bootstrap_calibration."
                f"{system}.v2.json"
            )
            _write_json(path, calibration)
            self.bootstrap_calibration_paths[system] = path
            calibrations[system] = calibration
        mapping = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_bootstrap_calibration_mapping"
            ),
            "status": "qualification_bootstrap_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": self.policy_contract_sha256,
            "aggregation_rule": (
                "median_of_accepted_physical_model_parity_samples_v2"
            ),
            "minimum_samples_per_branch_resource": 30,
            "candidate_manifest_sha256": _descriptor(
                root, self.candidate_manifest_path
            )["sha256"],
            "candidate_receipt_sha256": _descriptor(
                root, self.candidate_receipt_path
            )["sha256"],
            "model_parity_acceptance_binding_sha256": binding[
                "binding_sha256"
            ],
            "calibration_evidence_sha256": _canonical_sha([]),
            "physical_response_evidence_sha256": physical_sha,
            "calibrations": calibrations,
        }
        _write_json(self.bootstrap_mapping_path, mapping)
        bootstrap_receipt = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_bootstrap_receipt"
            ),
            "status": "qualification_bootstrap_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": self.policy_contract_sha256,
            "candidate_manifest": _descriptor(root, self.candidate_manifest_path),
            "candidate_receipt": _descriptor(root, self.candidate_receipt_path),
            "candidate_receipt_identity_sha256": candidate_receipt["sha256"],
            "qualification_index": _descriptor(root, self.qualification_index_path),
            "accepted_model_parity_manifest": binding["accepted_manifest"],
            "accepted_model_parity_assessment": binding["accepted_assessment"],
            "accepted_model_parity_receipt": binding["receipt"],
            "model_parity_acceptance_binding_sha256": binding["binding_sha256"],
            "accepted_model_parity_evidence_sha256": binding["evidence_sha256"],
            "calibration_evidence": [],
            "calibration_evidence_sha256": _canonical_sha([]),
            "transaction_index": transaction,
            "physical_response_evidence": [],
            "physical_response_evidence_sha256": physical_sha,
            "mapping": _descriptor(root, self.bootstrap_mapping_path),
            "calibrations": {
                system: _descriptor(root, path)
                for system, path in self.bootstrap_calibration_paths.items()
            },
            "blockers": [
                "bootstrap_is_not_policy_qualification_acceptance",
                "bootstrap_is_not_full_publication_authority",
                "bootstrap_is_valid_only_for_forced_cpu_only_gpu_only_pilots",
            ],
        }
        bootstrap_receipt["receipt_sha256"] = _canonical_sha(
            bootstrap_receipt
        )
        _write_json(self.bootstrap_receipt_path, bootstrap_receipt)

        operational_dir = root / "operational"
        self.qualification_transaction_receipt_path = (
            operational_dir / "qualification_input_transaction.v2.receipt.json"
        )
        self.runtime_input_materialization_receipt_path = (
            operational_dir / "qualification-runtime-inputs.materialization.v2.json"
        )
        self.runtime_input_bundle_path = operational_dir / "cell-runtime-input.json"
        self.guardian_service_authority_path = (
            operational_dir / "service_authority.v1.json"
        )
        self.preprocessing_contract_path = (
            operational_dir / "checkpoint_analytics_preprocessing_contract.v1.json"
        )
        self.preprocessing_contract_receipt_path = operational_dir / (
            "checkpoint_analytics_preprocessing_contract.v1.receipt.json"
        )
        _write_json(self.qualification_transaction_receipt_path, {"role": "tx"})
        _write_json(
            self.runtime_input_materialization_receipt_path,
            {"role": "runtime-materialization"},
        )
        _write_json(self.runtime_input_bundle_path, {"role": "runtime-bundle"})
        _write_json(
            self.guardian_service_authority_path,
            {"role": "guardian-service"},
        )
        _write_json(
            self.preprocessing_contract_path,
            {"role": "preprocessing-contract"},
        )
        _write_json(
            self.preprocessing_contract_receipt_path,
            {
                "preprocessing_contract": _descriptor(
                    root, self.preprocessing_contract_path
                )
            },
        )
        self.operational_binding = {
            "hardware_resource_collector": _descriptor(
                root, self.hardware_resource_collector_path
            ),
            "qualification_input_transaction_receipt": _descriptor(
                root, self.qualification_transaction_receipt_path
            ),
            "qualification_input_transaction_receipt_identity_sha256": "8" * 64,
            "runtime_input_materialization_receipt": _descriptor(
                root, self.runtime_input_materialization_receipt_path
            ),
            "runtime_input_materialization_receipt_identity_sha256": "9" * 64,
            "runtime_input_bundle": _descriptor(root, self.runtime_input_bundle_path),
            "runtime_input_bundle_identity_sha256": "a" * 64,
            "guardian_service_authority": _descriptor(
                root, self.guardian_service_authority_path
            ),
            "guardian_service_authority_identity_sha256": "b" * 64,
            "guardian_preprocessing_contract_receipt": _descriptor(
                root, self.preprocessing_contract_receipt_path
            ),
            "guardian_preprocessing_contract_receipt_identity_sha256": "c" * 64,
        }

        self.full_resource_summary = {
            "assessment_schema_version": 1,
            "resource_contract_version": 2,
            "evidence_accepted": True,
            "publication_bundle_bound": True,
            "full_resource_coverage_complete": True,
            "measurement_window_start_ns": 100,
            "measurement_window_end_ns": 200,
            "nvdec_busy_equivalent_ns": 50,
            "nvdec_interval_device_ids": ["GPU-" + "6" * 32],
            "nvdec_sampled_gpu_device_ids": ["GPU-" + "6" * 32],
            "nvdec_counter_scope": "device_sample",
            "fanout_thread_cpu_time_ns": 50,
            "fanout_work_units": 10,
            "fanout_counter_scope": "per_trace_resource_work",
            "resource_interval_summary": {},
        }
        self.prepared = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_publication_runtime_acceptance",
            "status": "accepted_native_checkpoint_arm",
            "run_id": self.run_id,
            "system": "deepstream",
            "scenario": "checkpoint_video_dag_shared",
            "codec": "h264",
            "policy": "gpu_only",
            "deadline_ms": 40.0,
            "execution_binding_provenance": (
                "native_scheduler_execution_binding_v1"
            ),
            "topology_kind": "shared_video_dag",
            "cohort_id": "qualification-cohort-v1",
            "measurement_schedule_fingerprint_sha256": "7" * 64,
            "completed_frames_by_stream": {"0": 30},
            "summary": {"accepted_frames": 30},
            "evidence_sha256": dict(self.evidence_sha256),
            "full_resource_evidence_sha256": {
                name: self.evidence_sha256[name]
                for name in (
                    "resource_intervals.csv",
                    "hardware_resource_samples.csv",
                    "fanout_work_counters.csv",
                )
            },
            "full_resource_summary": copy.deepcopy(self.full_resource_summary),
            "acceptance_finalization": {
                "hardware_collector_stopped": True,
                "validation": "full_resource_evidence_v2_passed",
            },
        }

    def finalize(self) -> dict[str, object]:
        with (
            mock.patch.object(
                target,
                "prepare_checkpoint_publication_acceptance",
                return_value=copy.deepcopy(self.prepared),
            ),
            mock.patch.object(
                target.model_parity_acceptance,
                "load_verified_model_parity_acceptance",
                return_value=copy.deepcopy(self.parity_binding),
            ),
            mock.patch.object(
                target,
                "_operational_material",
                return_value=copy.deepcopy(self.operational_binding),
            ),
        ):
            return target.finalize_checkpoint_qualification_pilot_acceptance_v1(
                project_root=self.root,
                output_dir=self.output_dir,
                expected_run_id=self.run_id,
                expected_arm_id=self.arm_id,
                expected_system="deepstream",
                expected_resource="gpu",
                expected_scenario="checkpoint_video_dag_shared",
                expected_codec="h264",
                expected_policy="gpu_only",
                expected_deadline_ms=40.0,
                topology_kind="shared_video_dag",
                hardware_collector_stopped=True,
                candidate_manifest_path=self.candidate_manifest_path,
                candidate_receipt_path=self.candidate_receipt_path,
                qualification_index_path=self.qualification_index_path,
                bootstrap_mapping_path=self.bootstrap_mapping_path,
                bootstrap_calibration_path=self.bootstrap_calibration_paths[
                    "deepstream"
                ],
                bootstrap_receipt_path=self.bootstrap_receipt_path,
                **self.operational_arguments(),
            )

    def operational_arguments(self) -> dict[str, Path]:
        return {
            "qualification_transaction_receipt_path": (
                self.qualification_transaction_receipt_path
            ),
            "runtime_input_materialization_receipt_path": (
                self.runtime_input_materialization_receipt_path
            ),
            "runtime_input_bundle_path": self.runtime_input_bundle_path,
            "guardian_service_authority_path": (
                self.guardian_service_authority_path
            ),
            "preprocessing_contract_path": self.preprocessing_contract_path,
            "preprocessing_contract_receipt_path": (
                self.preprocessing_contract_receipt_path
            ),
        }


class CheckpointQualificationPilotAcceptanceV1Tests(unittest.TestCase):
    def test_acceptance_atomic_commit_three_windows_exact_retry(self) -> None:
        windows = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for window in windows:
            with self.subTest(window=window), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output = root / "pilot"
                output.mkdir()
                path = output / target.ACCEPTANCE_FILENAME
                value = {"artifact_kind": target.ARTIFACT_KIND, "status": target.STATUS}

                def crash(step: str) -> None:
                    if step == window:
                        raise RuntimeError("synthetic physical crash")

                with self.assertRaisesRegex(RuntimeError, "synthetic physical crash"):
                    target._write_immutable_json(  # noqa: SLF001
                        root, path, value, _fault_hook=crash
                    )
                identity = None
                if path.exists():
                    info = path.stat()
                    identity = (info.st_dev, info.st_ino)
                target._write_immutable_json(root, path, value)  # noqa: SLF001
                self.assertEqual(path.read_bytes(), _canonical_bytes(value) + b"\n")
                if identity is not None:
                    info = path.stat()
                    self.assertEqual((info.st_dev, info.st_ino), identity)

    def test_guardian_live_validation_is_bound_to_preprocessing_authority(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar

        preprocessing_authority = {"policy_contract_sha256": "1" * 64}
        runtime_expectations = {
            "execution_config_identity_sha256": "7" * 64,
            "binding_set_identity_sha256": "8" * 64,
            "bindings_identity_sha256": "9" * 64,
            "worker_image_ids": {
                "cpu": "sha256:" + "a" * 64,
                "gpu": "sha256:" + "b" * 64,
            },
            "policy_contract_sha256": "1" * 64,
            "preprocessing_contract_content_sha256": "c" * 64,
        }
        checked = {
            "front_socket": {"path": "/tmp/guardian.sock"},
            "execution_config_identity_sha256": "2" * 64,
            "binding_set_identity_sha256": "3" * 64,
            "worker_image_ids": {
                "cpu": "sha256:" + "4" * 64,
                "gpu": "sha256:" + "5" * 64,
            },
            "preprocessing_contract_authority": preprocessing_authority,
            "service_identity_sha256": "6" * 64,
        }
        with (
            mock.patch.object(
                sidecar,
                "validate_publication_sidecar_service_authority_v1",
                return_value=checked,
            ),
            mock.patch.object(
                sidecar,
                "assert_publication_sidecar_service_authority_v1",
                return_value=checked,
            ) as assertion,
            mock.patch.object(
                sidecar,
                "assert_publication_sidecar_service_authority_identity_v1",
                return_value=checked,
            ) as offline_assertion,
        ):
            self.assertEqual(
                target._validate_guardian_service_authority(
                    checked,
                    require_live=True,
                    expected_preprocessing_contract_authority=(
                        preprocessing_authority
                    ),
                    expected_runtime_expectations=runtime_expectations,
                ),
                checked,
            )
            self.assertEqual(
                target._validate_guardian_service_authority(
                    checked,
                    require_live=False,
                    expected_preprocessing_contract_authority=(
                        preprocessing_authority
                    ),
                    expected_runtime_expectations=runtime_expectations,
                ),
                checked,
            )
        assertion.assert_called_once_with(
            checked,
            expected_front_socket="/tmp/guardian.sock",
            expected_execution_config_identity_sha256="7" * 64,
            expected_binding_set_identity_sha256="8" * 64,
            expected_worker_image_ids=runtime_expectations["worker_image_ids"],
            expected_preprocessing_contract_authority=preprocessing_authority,
            expected_service_identity_sha256="6" * 64,
            expected_policy_contract_sha256="1" * 64,
        )
        offline_assertion.assert_called_once_with(
            checked,
            expected_front_socket="/tmp/guardian.sock",
            expected_execution_config_identity_sha256="7" * 64,
            expected_binding_set_identity_sha256="8" * 64,
            expected_worker_image_ids=runtime_expectations["worker_image_ids"],
            expected_preprocessing_contract_authority=preprocessing_authority,
            expected_service_identity_sha256="6" * 64,
            expected_policy_contract_sha256="1" * 64,
        )

    def test_accepts_real_index_v2_and_bootstrap_v2_output_shapes(self) -> None:
        import publication_policy_qualification_bootstrap_v2 as bootstrap
        import publication_policy_qualification_index_v2 as index_builder
        from tests.test_publication_policy_qualification import (
            SYSTEMS as POLICY_SYSTEMS,
            _fake_fragment_validator,
            _fragment_bound_fixture,
        )
        from tests.test_publication_policy_qualification_bootstrap_v2 import (
            BootstrapFixture,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _index_path, source_index = _fragment_bound_fixture(root)
            fragments = {
                system: root
                / next(
                    row
                    for row in source_index["bindings"]
                    if row["system"] == system
                )["fragment_artifact"]["path"]
                for system in POLICY_SYSTEMS
            }
            candidate = index_builder.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=None,
                output_dir=root / "real-candidate-v2",
                fragment_validator=_fake_fragment_validator,
            )
            parity = BootstrapFixture(root)
            with (
                mock.patch.object(
                    bootstrap.model_parity_acceptance,
                    "load_verified_model_parity_acceptance",
                    side_effect=parity.acceptance_loader,
                ),
                mock.patch.object(
                    bootstrap,
                    "_load_model_parity_manifest",
                    side_effect=parity.manifest_loader,
                ),
            ):
                bootstrap_result = (
                    bootstrap.build_qualification_bootstrap_calibration_v2(
                        project_root=root,
                        candidate_manifest_path=candidate[
                            "candidate_manifest_path"
                        ],
                        candidate_receipt_path=candidate[
                            "candidate_receipt_path"
                        ],
                        accepted_model_parity_manifest_path=(
                            parity.accepted_manifest_path
                        ),
                        accepted_model_parity_assessment_path=(
                            parity.accepted_assessment_path
                        ),
                        accepted_model_parity_receipt_path=(
                            parity.accepted_receipt_path
                        ),
                        output_dir=root / "publication-store/real-bootstrap-v2",
                    )
                )
            physical = _Fixture(root)
            (
                physical.output_dir
                / "checkpoint_qualification_pilot_acceptance.json"
            ).unlink()
            with (
                mock.patch.object(
                    target,
                    "prepare_checkpoint_publication_acceptance",
                    return_value=copy.deepcopy(physical.prepared),
                ),
                mock.patch.object(
                    target.model_parity_acceptance,
                    "load_verified_model_parity_acceptance",
                    side_effect=parity.acceptance_loader,
                ),
                mock.patch.object(
                    target,
                    "_operational_material",
                    return_value=copy.deepcopy(physical.operational_binding),
                ),
            ):
                acceptance = (
                    target.finalize_checkpoint_qualification_pilot_acceptance_v1(
                        project_root=root,
                        output_dir=physical.output_dir,
                        expected_run_id=physical.run_id,
                        expected_arm_id=physical.arm_id,
                        expected_system="deepstream",
                        expected_resource="gpu",
                        expected_scenario="checkpoint_video_dag_shared",
                        expected_codec="h264",
                        expected_policy="gpu_only",
                        expected_deadline_ms=40.0,
                        topology_kind="shared_video_dag",
                        hardware_collector_stopped=True,
                        candidate_manifest_path=candidate[
                            "candidate_manifest_path"
                        ],
                        candidate_receipt_path=candidate[
                            "candidate_receipt_path"
                        ],
                        qualification_index_path=candidate["index_path"],
                        bootstrap_mapping_path=bootstrap_result["mapping_path"],
                        bootstrap_calibration_path=bootstrap_result[
                            "calibration_paths"
                        ]["deepstream"],
                        bootstrap_receipt_path=bootstrap_result["receipt_path"],
                        **physical.operational_arguments(),
                    )
                )
            self.assertEqual(acceptance["artifact_kind"], target.ARTIFACT_KIND)

    def test_commits_distinct_non_authorizing_acceptance_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _Fixture(Path(tmp))
            events: list[str] = []
            immutable_writer = target._write_immutable_json

            def prepare(**kwargs: object) -> dict[str, object]:
                self.assertEqual(kwargs["expected_run_id"], fixture.run_id)
                events.append("prepare")
                return copy.deepcopy(fixture.prepared)

            def write(
                root: Path, path: Path, value: dict[str, object]
            ) -> None:
                events.append(path.name)
                immutable_writer(root, path, value)

            with (
                mock.patch.object(
                    target,
                    "prepare_checkpoint_publication_acceptance",
                    side_effect=prepare,
                ),
                mock.patch.object(
                    target.model_parity_acceptance,
                    "load_verified_model_parity_acceptance",
                    return_value=copy.deepcopy(fixture.parity_binding),
                ),
                mock.patch.object(
                    target, "_write_immutable_json", side_effect=write
                ),
                mock.patch.object(
                    target,
                    "_operational_material",
                    return_value=copy.deepcopy(fixture.operational_binding),
                ),
            ):
                acceptance = target.finalize_checkpoint_qualification_pilot_acceptance_v1(
                    project_root=fixture.root,
                    output_dir=fixture.output_dir,
                    expected_run_id=fixture.run_id,
                    expected_arm_id=fixture.arm_id,
                    expected_system="deepstream",
                    expected_resource="gpu",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="gpu_only",
                    expected_deadline_ms=40.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                    candidate_manifest_path=fixture.candidate_manifest_path,
                    candidate_receipt_path=fixture.candidate_receipt_path,
                    qualification_index_path=fixture.qualification_index_path,
                    bootstrap_mapping_path=fixture.bootstrap_mapping_path,
                    bootstrap_calibration_path=(
                        fixture.bootstrap_calibration_paths["deepstream"]
                    ),
                    bootstrap_receipt_path=fixture.bootstrap_receipt_path,
                    **fixture.operational_arguments(),
                )

            self.assertEqual(
                events,
                ["prepare", target.ACCEPTANCE_FILENAME],
            )
            self.assertEqual(
                acceptance["artifact_kind"],
                "vast_checkpoint_qualification_pilot_acceptance_v1",
            )
            self.assertEqual(
                acceptance["status"], "accepted_native_qualification_pilot"
            )
            self.assertEqual(
                acceptance["scope"],
                "pre_run_policy_and_full_resource_qualification_only",
            )
            for flag in (
                "accepted_for_full_publication",
                "publication_ready",
                "authorization_eligible",
            ):
                self.assertIs(acceptance[flag], False)
            self.assertEqual(
                acceptance["blockers"],
                ["qualification_pilot_is_not_full_publication_arm"],
            )
            self.assertEqual(len(acceptance["evidence_sha256"]), 14)
            self.assertEqual(
                acceptance["coordinate"],
                {
                    "system": "deepstream",
                    "resource": "gpu",
                    "codec": "h264",
                    "topology_kind": "shared_video_dag",
                },
            )
            self.assertEqual(acceptance["run_id"], fixture.run_id)
            self.assertEqual(acceptance["arm_id"], fixture.arm_id)
            unsigned = dict(acceptance)
            claimed_sha = unsigned.pop("sha256")
            self.assertEqual(_canonical_sha(unsigned), claimed_sha)
            self.assertFalse(
                (fixture.output_dir / "checkpoint_publication_acceptance.json").exists()
            )
            self.assertTrue(
                (fixture.output_dir / target.ACCEPTANCE_FILENAME).is_file()
            )
            forbidden = {
                "production_metadata_binding",
                "output_receipt",
                "resource_capability_grant",
                "backend_runtime_grant",
                "model_parity_grant",
            }
            self.assertTrue(forbidden.isdisjoint(acceptance))

            with self.assertRaises(ContractError):
                commit_checkpoint_publication_acceptance(
                    output_dir=fixture.output_dir,
                    acceptance=acceptance,
                    run_metadata_path=fixture.output_dir / "run_metadata.json",
                    expected_execution_binding={},
                )

    def test_validator_rehashes_evidence_bootstrap_and_model_parity_binding(self) -> None:
        cases = (
            "evidence",
            "mapping",
            "calibration",
            "parity_binding",
            "operational_binding",
            "extra_production_field",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                fixture = _Fixture(Path(tmp))
                acceptance = fixture.finalize()
                if case == "evidence":
                    (fixture.output_dir / "frames.csv").write_bytes(b"tampered")
                elif case == "mapping":
                    fixture.bootstrap_mapping_path.write_bytes(b"{}\n")
                elif case == "calibration":
                    fixture.bootstrap_calibration_paths["deepstream"].write_bytes(
                        b"{}\n"
                    )
                elif case == "parity_binding":
                    fixture.parity_binding["binding_sha256"] = "f" * 64
                elif case == "operational_binding":
                    acceptance["operational_binding"][
                        "runtime_input_bundle_identity_sha256"
                    ] = "f" * 64
                    unsigned = dict(acceptance)
                    unsigned.pop("sha256")
                    acceptance["sha256"] = _canonical_sha(unsigned)
                    _write_json(
                        fixture.output_dir / target.ACCEPTANCE_FILENAME,
                        acceptance,
                    )
                else:
                    acceptance["production_metadata_binding"] = {
                        "forbidden": True
                    }
                    unsigned = dict(acceptance)
                    unsigned.pop("sha256")
                    acceptance["sha256"] = _canonical_sha(unsigned)
                    _write_json(
                        fixture.output_dir / target.ACCEPTANCE_FILENAME,
                        acceptance,
                    )
                with (
                    mock.patch.object(
                        target.model_parity_acceptance,
                        "load_verified_model_parity_acceptance",
                        return_value=copy.deepcopy(fixture.parity_binding),
                    ),
                    mock.patch.object(
                        target,
                        "_operational_material",
                        return_value=copy.deepcopy(fixture.operational_binding),
                    ),
                    self.assertRaises(target.QualificationPilotAcceptanceV1Error),
                ):
                    target.validate_checkpoint_qualification_pilot_acceptance_v1(
                        project_root=fixture.root,
                        acceptance_path=(
                            fixture.output_dir / target.ACCEPTANCE_FILENAME
                        ),
                        expected_system="deepstream",
                        expected_resource="gpu",
                        expected_codec="h264",
                        expected_topology_kind="shared_video_dag",
                        expected_run_id=fixture.run_id,
                        expected_arm_id=fixture.arm_id,
                    )

    def test_validator_requires_exact_14_hashes_and_exact_identities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _Fixture(Path(tmp))
            acceptance = fixture.finalize()
            acceptance["evidence_sha256"]["unexpected.csv"] = "9" * 64
            unsigned = dict(acceptance)
            unsigned.pop("sha256")
            acceptance["sha256"] = _canonical_sha(unsigned)
            _write_json(
                fixture.output_dir / target.ACCEPTANCE_FILENAME, acceptance
            )
            with (
                mock.patch.object(
                    target.model_parity_acceptance,
                    "load_verified_model_parity_acceptance",
                    return_value=copy.deepcopy(fixture.parity_binding),
                ),
                mock.patch.object(
                    target,
                    "_operational_material",
                    return_value=copy.deepcopy(fixture.operational_binding),
                ),
                self.assertRaisesRegex(
                    target.QualificationPilotAcceptanceV1Error,
                    "14|evidence",
                ),
            ):
                target.validate_checkpoint_qualification_pilot_acceptance_v1(
                    project_root=fixture.root,
                    acceptance_path=(
                        fixture.output_dir / target.ACCEPTANCE_FILENAME
                    ),
                    expected_system="deepstream",
                    expected_resource="gpu",
                    expected_codec="h264",
                    expected_topology_kind="shared_video_dag",
                    expected_run_id=fixture.run_id,
                    expected_arm_id=fixture.arm_id,
                )

            acceptance["evidence_sha256"].pop("unexpected.csv")
            unsigned = dict(acceptance)
            unsigned.pop("sha256")
            acceptance["sha256"] = _canonical_sha(unsigned)
            _write_json(
                fixture.output_dir / target.ACCEPTANCE_FILENAME, acceptance
            )
            with (
                mock.patch.object(
                    target.model_parity_acceptance,
                    "load_verified_model_parity_acceptance",
                    return_value=copy.deepcopy(fixture.parity_binding),
                ),
                mock.patch.object(
                    target,
                    "_operational_material",
                    return_value=copy.deepcopy(fixture.operational_binding),
                ),
                self.assertRaisesRegex(
                    target.QualificationPilotAcceptanceV1Error,
                    "run_id drifted",
                ),
            ):
                target.validate_checkpoint_qualification_pilot_acceptance_v1(
                    project_root=fixture.root,
                    acceptance_path=(
                        fixture.output_dir / target.ACCEPTANCE_FILENAME
                    ),
                    expected_system="deepstream",
                    expected_resource="gpu",
                    expected_codec="h264",
                    expected_topology_kind="shared_video_dag",
                    expected_run_id="another-run-identity",
                    expected_arm_id=fixture.arm_id,
                )


if __name__ == "__main__":
    unittest.main()
