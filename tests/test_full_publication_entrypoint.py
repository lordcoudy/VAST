from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_publication_entrypoint as entrypoint_module  # noqa: E402
from benchmark_contract import ContractError  # noqa: E402
from benchmark_contract import FULL_RESOURCE_PUBLICATION_SCOPE  # noqa: E402
from full_publication_entrypoint import (  # noqa: E402
    _consume_cloud_links_from_environment,
    _default_command_runner,
    _validated_run_root,
    build_offline_publication_plan,
    create_application,
    ImmutableFileGuard,
    ProductionEntrypoint,
    RealArmRunner,
    build_identity_material,
    build_parser,
    main,
    production_readiness_validator,
)
from full_publication_runner import (  # noqa: E402
    ArmContext,
    CallbackDecision,
    ExitCode,
    PairContext,
    RunContext,
    RunResult,
)
from model_parity_grant import model_parity_grant_from_identity_artifacts  # noqa: E402
from seafile_artifact_store import SeafileShareLinks  # noqa: E402


MATRIX_SHA = "a" * 64
RUN_SHA = "b" * 64


def canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resource_capability_grant() -> dict[str, object]:
    grant: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_pre_run_resource_capability_grant",
        "status": "accepted_pre_run_resource_capability_qualification",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": "a" * 64,
        "qualification_receipt": {
            "path": "artifacts/checkpoint_full_resource_qualification_receipt.json",
            "size_bytes": 101,
            "sha256": "b" * 64,
        },
        "capability_manifest": {
            "path": "artifacts/checkpoint_full_resource_capability_manifest.json",
            "size_bytes": 202,
            "sha256": "c" * 64,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    grant["grant_sha256"] = canonical_sha(grant)
    return grant


def identity_descriptor(path: str) -> dict[str, object]:
    return {
        "path": path,
        "size_bytes": 10,
        "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
    }


def model_parity_identity() -> dict[str, object]:
    receipt = identity_descriptor("accepted/parity-receipt.json")
    manifest = identity_descriptor("configs/parity.accepted.yaml")
    assessment = identity_descriptor("accepted/parity-assessment.json")
    transaction_file = identity_descriptor(
        "evidence/model_parity/v4/transaction_index.json"
    )
    transaction = {
        **transaction_file,
        "transaction_sha256": "1" * 64,
        "files_sha256": "2" * 64,
        "output_segments_sha256": "3" * 64,
        "execution_bundle_count": 480,
        "execution_bundles_sha256": "4" * 64,
    }
    evidence = [
        identity_descriptor(f"evidence/model_parity/v3/{index:02d}.json")
        for index in range(32)
    ]
    parity_files = sorted(
        [receipt, manifest, assessment, transaction_file, *evidence],
        key=lambda item: str(item["path"]),
    )
    parity: dict[str, object] = {
        "schema_version": 2,
        "artifact_kind": "vast_verified_model_parity_acceptance_binding",
        "receipt": receipt,
        "accepted_manifest": manifest,
        "accepted_assessment": assessment,
        "transaction_index": transaction,
        "acceptance_identity_sha256": "a" * 64,
        "accepted_manifest_content_identity_sha256": "b" * 64,
        "canonical_assessment_identity_sha256": "c" * 64,
        "evidence_count": 32,
        "evidence_sha256": "d" * 64,
        "runtime_registries_sha256": "e" * 64,
        "runtime_images_sha256": "f" * 64,
        "files": parity_files,
        "files_sha256": canonical_sha(parity_files),
    }
    parity["binding_sha256"] = canonical_sha(parity)
    identity_manifest = identity_descriptor("configs/full-publication.json")
    files = sorted(
        [identity_manifest, *parity_files],
        key=lambda item: str(item["path"]),
    )
    identity: dict[str, object] = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_identity_artifact_binding",
        "manifest": identity_manifest,
        "bindings": {
            "analytics_model_parity": parity,
            "analytics_execution_layer": {},
            "policy_qualification": {},
            "resource_qualification": {},
            "backend_runtime_qualification": {},
        },
        "files": files,
        "files_sha256": canonical_sha(files),
    }
    identity["binding_sha256"] = canonical_sha(identity)
    return identity


def frozen_arm(**overrides: object) -> dict[str, object]:
    arm: dict[str, object] = {
        "arm_id": "gstreamer_custom--h264--cpu_only--d100--r01--a1",
        "arm_position": 1,
        "scenario": "checkpoint_video_dag_shared",
        "system": "gstreamer_custom",
        "codec": "h264",
        "dataset": "kpp_iss_publication_v3_h264",
        "policy": "cpu_only",
        "deadline_ms": 100.0,
        "repeat": 1,
        "seed": 20260323,
        "streams": 6,
        "warmup_s": 30,
        "measurement_s": 180,
    }
    arm.update(overrides)
    return arm


def arm_context(arm: dict[str, object] | None = None) -> ArmContext:
    selected = frozen_arm() if arm is None else arm
    pair = {
        "pair_id": "gstreamer_custom--h264--cpu_only--d100--r01",
        "arms": [selected, frozen_arm(arm_id="other--a2", arm_position=2)],
    }
    pair_context = PairContext(
        run=RunContext(
            run_root=Path("/tmp/full-run"),
            matrix_identity={"schema_version": 2, "sha256": MATRIX_SHA},
            run_identity={"schema_version": 1, "sha256": RUN_SHA},
            next_sequence=0,
            total_pairs=1,
        ),
        sequence=0,
        pair=pair,
        attempt=1,
    )
    return ArmContext(pair_context=pair_context, arm_index=0, arm=selected)


def minimal_config(project_root: Path) -> dict[str, object]:
    systems = {
        name: {"container_image": f"example/{name}:frozen", "command": "unused"}
        for name in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
    }
    scenario = {
        "benchmark_status": "supported",
        "workload": {
            "streams": 6,
            "object_density": {"min": 1, "max": 12},
        },
        "pipeline": ["decode", "record"],
        "placement": {"stages": {"decode": "local", "record": "local"}},
        "network": {},
        "distributed": {"enabled": False},
    }
    return {
        "benchmark": {
            "dataset_manifest": "configs/datasets.yaml",
            "scheduler_policies": [
                "cpu_only",
                "gpu_only",
                "static_hybrid",
                "heft",
                "deadline_aware_heft",
                "queue_aware_edf",
                "adaptive_weights",
            ],
            "deadline_ms": [16.7, 33.3, 50, 100, 500],
            "default_seed": 20260323,
        },
        "protocol": {"warmup_s": 30, "measurement_s": 180, "repeats": 10},
        "hardware_target": {
            "gpu_model": "NVIDIA GeForce RTX 3060",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22,
        },
        "scenarios": {
            "checkpoint_independent_processes_baseline": copy.deepcopy(scenario),
            "checkpoint_video_dag_shared": copy.deepcopy(scenario),
        },
        "systems": systems,
    }


def resolved_dataset(project_root: Path, name: str, codec: str) -> dict[str, object]:
    path = project_root / "data" / f"{name}.avi"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    dataset = {
        "name": name,
        "publishable": True,
        "streams": [
            {
                "path": path.relative_to(project_root).as_posix(),
                "absolute_path": str(path),
                "sha256": digest,
                "resolved_sha256": digest,
                "codec_name": "hevc" if codec == "h265" else "h264",
            }
        ],
        "aggregate_sha256": hashlib.sha256(digest.encode("utf-8")).hexdigest(),
    }
    dataset["manifest_identity_schema_version"] = 1
    dataset["manifest_identity_sha256"] = canonical_sha(dataset)
    return dataset


class RealArmRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "configs").mkdir()
        (self.root / "data").mkdir()
        (self.root / "data" / "kpp_iss_publication_v3_h264.avi").write_bytes(b"h264-data")
        (self.root / "data" / "kpp_iss_publication_v3_h265.avi").write_bytes(b"h265-data")
        self.config = minimal_config(self.root)
        self.datasets = {
            "kpp_iss_publication_v3_h264": resolved_dataset(
                self.root, "kpp_iss_publication_v3_h264", "h264"
            ),
            "kpp_iss_publication_v3_h265": resolved_dataset(
                self.root, "kpp_iss_publication_v3_h265", "h265"
            ),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_real_arm_routes_only_through_production_v3_transaction(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_production_v3_executor(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            execution = kwargs["execution_binding"]
            return {
                "schema_version": 3,
                "artifact_kind": (
                    "vast_backend_publication_production_output_receipt_authority_v3"
                ),
                "status": "accepted_publishable_backend_output",
                "execution_scope": "full_publication_measurement_v3",
                "full_publication_execution_binding": execution,
                "run_identity_sha256": RUN_SHA,
                "dispatch_resolution_sha256": "d" * 64,
                "evidence_files": [
                    {
                        "path": "checkpoint_publication_acceptance.json",
                        "size_bytes": 101,
                        "sha256": "e" * 64,
                    },
                    {
                        "path": "run_metadata.json",
                        "size_bytes": 202,
                        "sha256": "f" * 64,
                    },
                ],
                "semantic_evidence_assessment": {
                    "accepted_measurement_evidence": True,
                    "semantic_evidence_validated": True,
                    "status": "accepted",
                    "validator_identity_sha256": kwargs[
                        "semantic_validator_identity_sha256"
                    ],
                },
                "accepted_measurement_evidence": True,
                "publication_output_accepted": True,
                "publication_ready": True,
                "promotable": True,
                "semantic_evidence_validated": True,
                "external_pins_validated": True,
                "process_tree_quiescent": True,
            }

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            production_v3_executor_fn=fake_production_v3_executor,
        )
        arm_root = self.root / "run" / "arm"
        result = runner(arm_context(), arm_root)

        self.assertEqual(
            result, {"status": "completed", "arm_id": frozen_arm()["arm_id"]}
        )
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["arm_root"], arm_root)
        self.assertEqual(call["arm"], frozen_arm())
        self.assertEqual(
            call["semantic_evidence_validator"],
            entrypoint_module.publication_arm_semantic_evidence_validator_v3,
        )
        self.assertRegex(
            str(call["semantic_validator_identity_sha256"]), r"^[0-9a-f]{64}$"
        )

    def test_production_v3_rejects_unaccepted_semantic_authority(self) -> None:
        def rejected_executor(**kwargs: object) -> dict[str, object]:
            return {
                "schema_version": 3,
                "artifact_kind": (
                    "vast_backend_publication_production_output_receipt_authority_v3"
                ),
                "status": "accepted_publishable_backend_output",
                "execution_scope": "full_publication_measurement_v3",
                "full_publication_execution_binding": kwargs["execution_binding"],
                "run_identity_sha256": RUN_SHA,
                "dispatch_resolution_sha256": "d" * 64,
                "evidence_files": [],
                "semantic_evidence_assessment": {
                    "accepted_measurement_evidence": False,
                    "semantic_evidence_validated": False,
                    "status": "rejected",
                    "validator_identity_sha256": kwargs[
                        "semantic_validator_identity_sha256"
                    ],
                },
            }

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            production_v3_executor_fn=rejected_executor,
        )
        with self.assertRaisesRegex(ContractError, "semantic evidence"):
            runner(arm_context(), self.root / "run" / "arm")

    def test_semantic_validator_crossbinds_acceptance_metadata_and_evidence(self) -> None:
        arm = {
            "runtime_inputs": {
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "codec": "h264",
                "policy": "cpu_only",
                "deadline_ms": 100,
                "dataset": {"name": "kpp_iss_publication_v3_h264"},
                "streams": 6,
                "duration_s": 180,
                "repeat_index": 1,
                "base_seed": 20260323,
                "run_seed": 123456,
                "run_id": "arm-run-id",
            },
            "full_publication_execution_binding": {
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_arm_execution_binding",
                "run_identity_sha256": RUN_SHA,
                "sequence": 0,
                "pair_id": "pair-0000",
                "attempt": 1,
                "arm_id": frozen_arm()["arm_id"],
            },
            "resource_capability_grant_sha256": "1" * 64,
            "backend_runtime_grant_sha256": "2" * 64,
            "model_parity_grant_sha256": "3" * 64,
            "model_parity_acceptance_binding_sha256": "4" * 64,
            "identity_artifact_binding_sha256": "5" * 64,
        }
        metadata = {
            "schema_version": 2,
            "mode": "benchmark",
            "run_seed": 123456,
            "result": {
                "status": "completed",
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "policy": "cpu_only",
                "dataset": "kpp_iss_publication_v3_h264",
                "repeat": 1,
                "streams": 6,
                "duration_s": 180,
                "seed": 20260323,
                "run_seed": 123456,
                "deadline_ms": 100.0,
                "distributed": False,
                "deployment_mode": "heterogeneous",
            },
            "publication_run_contract": {
                "full_publication_execution_binding": arm[
                    "full_publication_execution_binding"
                ],
                "pre_run_resource_capability_grant": {"grant_sha256": "1" * 64},
                "pre_run_backend_runtime_grant": {"grant_sha256": "2" * 64},
                "pre_run_model_parity_grant": {
                    "grant_sha256": "3" * 64,
                    "parity_acceptance_binding_sha256": "4" * 64,
                },
            },
        }
        metadata_payload = json.dumps(metadata, sort_keys=True).encode("ascii")
        metadata_sha256 = hashlib.sha256(metadata_payload).hexdigest()
        evidence_payload = b'{"native":true}\n'
        evidence_sha256 = hashlib.sha256(evidence_payload).hexdigest()
        binding = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_publication_acceptance_metadata_binding",
            "run_metadata_file": "run_metadata.json",
            "run_metadata_size_bytes": len(metadata_payload),
            "run_metadata_sha256": metadata_sha256,
            "identity_artifact_binding_sha256": "5" * 64,
            "resource_capability_grant_sha256": "1" * 64,
            "backend_runtime_grant_sha256": "2" * 64,
            "model_parity_grant_sha256": "3" * 64,
            "model_parity_acceptance_binding_sha256": "4" * 64,
            "execution_binding": arm["full_publication_execution_binding"],
            "binding_sha256": "b" * 64,
        }
        acceptance = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_publication_runtime_acceptance",
            "status": "accepted_native_checkpoint_arm",
            "system": "gstreamer_custom",
            "scenario": "checkpoint_video_dag_shared",
            "codec": "h264",
            "policy": "cpu_only",
            "deadline_ms": 100.0,
            "run_id": "arm-run-id",
            "measurement_schedule_fingerprint_sha256": "c" * 64,
            "summary": {
                "resource_contract_version": 2,
                **{
                    gate: True
                    for gate in (
                        "ingress_ledger_complete",
                        "ingress_cohort_closed",
                        "branch_terminal_trace_complete",
                        "checkpoint_frame_aggregation_complete",
                        "stage_semantic_contract_complete",
                        "decoder_placement_verified",
                        "resource_attribution_complete",
                        "reset_state_verified",
                        "full_resource_evidence_accepted",
                        "full_resource_coverage_complete",
                    )
                },
            },
            "evidence_sha256": {"native-evidence.json": evidence_sha256},
            "full_resource_evidence_sha256": {
                "native-evidence.json": evidence_sha256
            },
            "full_resource_summary": {
                "resource_contract_version": 2,
                "evidence_accepted": True,
                "publication_bundle_bound": True,
                "full_resource_coverage_complete": True,
            },
            "acceptance_finalization": {
                "hardware_collector_stopped": True,
                "validation": "full_resource_evidence_v2_passed",
            },
            "publication_metadata_binding": binding,
        }
        acceptance_payload = json.dumps(acceptance, sort_keys=True).encode("ascii")
        acceptance_sha256 = hashlib.sha256(acceptance_payload).hexdigest()
        descriptors = [
            {
                "path": "checkpoint_publication_acceptance.json",
                "size_bytes": len(acceptance_payload),
                "sha256": acceptance_sha256,
            },
            {
                "path": "native-evidence.json",
                "size_bytes": len(evidence_payload),
                "sha256": evidence_sha256,
            },
            {
                "path": "run_metadata.json",
                "size_bytes": len(metadata_payload),
                "sha256": metadata_sha256,
            },
        ]
        request = {
            "schema_version": 3,
            "artifact_kind": (
                "vast_backend_publication_production_semantic_evidence_request_v3"
            ),
            "arm_contract": arm,
            "arm_contract_file": {
                "path": "backend_publication_arm_contract.json",
                "size_bytes": 1,
                "sha256": "f" * 64,
            },
            "evidence_files": descriptors,
            "evidence_aggregate_sha256": "0" * 64,
            "evidence_payloads": {
                "checkpoint_publication_acceptance.json": acceptance_payload,
                "native-evidence.json": evidence_payload,
                "run_metadata.json": metadata_payload,
            },
        }

        accepted = entrypoint_module.publication_arm_semantic_evidence_validator_v3(
            request
        )
        self.assertTrue(accepted["accepted"])
        tampered = copy.deepcopy(request)
        tampered_metadata = copy.deepcopy(metadata)
        tampered_metadata["result"]["policy"] = "gpu_only"
        tampered["evidence_payloads"]["run_metadata.json"] = json.dumps(
            tampered_metadata, sort_keys=True
        ).encode("ascii")
        rejected = entrypoint_module.publication_arm_semantic_evidence_validator_v3(
            tampered
        )
        self.assertFalse(rejected["accepted"])

    def test_production_executor_passes_ro_ext4_contract_to_transaction(self) -> None:
        identity_sha = "5" * 64
        arm = frozen_arm()
        context = arm_context(arm)
        execution_binding = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_arm_execution_binding",
            "run_identity_sha256": RUN_SHA,
            "sequence": 0,
            "pair_id": context.pair_context.pair["pair_id"],
            "attempt": 1,
            "arm_id": arm["arm_id"],
        }
        invocation = entrypoint_module.publication_launcher_invocation_v3_contract()
        selected = {
            "launcher": {
                "path": "scripts/checkpoint_gstreamer_custom_publication_launcher_v3.py",
                "size_bytes": 321,
                "sha256": "6" * 64,
            },
            "launcher_invocation": invocation,
            "cell_identity_sha256": "7" * 64,
            "validation_record_sha256": "8" * 64,
            "runtime_authority_sha256": "9" * 64,
            "model_parity_acceptance_binding_sha256": "4" * 64,
            "dataset_runtime_input_key": "gstreamer_custom_publication_runtime_v3",
            "dataset_runtime_input": {
                "evidence_mapping": {
                    "checkpoint_publication_acceptance.json": (
                        "checkpoint_publication_acceptance.json"
                    ),
                    "run_metadata.json": "run_metadata.json",
                }
            },
            "launcher_evidence_files": [
                "checkpoint_publication_acceptance.json",
                "run_metadata.json",
            ],
        }
        runtime_binding = {
            "schema_version": 3,
            "artifact_kind": (
                "vast_backend_publication_production_runtime_bind_mount_v3"
            ),
            "source_runtime_root": "/runtime",
            "source_python_relative_path": "bin/python",
            "source_python_size_bytes": 123,
            "source_python_sha256": "a" * 64,
            "project_runtime_mount": (
                ".publication-runtime/full-publication-cp312-v1"
            ),
            "project_python_path": (
                ".publication-runtime/full-publication-cp312-v1/bin/python"
            ),
            "runtime_filesystem": "ext4",
            "source_runtime_mount_read_only": True,
            "runtime_mount_read_only": True,
            "binding_sha256": "b" * 64,
        }
        grants = {
            "resource": {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": "1" * 64,
            },
            "backend": {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": "2" * 64,
            },
            "model": {
                "identity_artifact_binding_sha256": identity_sha,
                "grant_sha256": "3" * 64,
                "parity_acceptance_binding_sha256": "4" * 64,
            },
        }
        run_calls: list[dict[str, object]] = []

        def fake_prepare(**kwargs: object) -> dict[str, object]:
            payload = (
                entrypoint_module.backend_dispatch_v3.
                canonical_backend_publication_arm_contract_bytes_v3(
                    kwargs["arm_contract"]
                )
            )
            return {
                "status": "prepared_production_arm_not_executed",
                "sha256": hashlib.sha256(payload).hexdigest(),
                **{
                    field: False
                    for field in entrypoint_module.production_transaction_v3.
                    PRODUCTION_ACCEPTANCE_CLAIM_FIELDS
                },
            }

        def fake_run(**kwargs: object) -> dict[str, object]:
            run_calls.append(kwargs)
            return {"sentinel": "committed"}

        arm_root = self.root / "run" / "production-arm"
        arm_root.parent.mkdir(parents=True)
        with (
            patch(
                "full_publication_entrypoint._select_production_v3_authority",
                return_value=selected,
            ),
            patch.object(
                entrypoint_module.production_transaction_v3,
                "prepare_backend_publication_production_transaction_v3",
                side_effect=fake_prepare,
            ) as prepare,
            patch.object(
                entrypoint_module.production_transaction_v3,
                "run_or_resume_backend_publication_production_transaction_v3",
                side_effect=fake_run,
            ),
        ):
            result = entrypoint_module._execute_production_v3_arm(
                config=self.config,
                project_root=self.root.resolve(),
                arm_root=arm_root,
                arm=arm,
                scenario=self.config["scenarios"][arm["scenario"]],
                dataset=self.datasets[arm["dataset"]],
                execution_binding=execution_binding,
                resource_capability_grant=grants["resource"],
                backend_runtime_grant=grants["backend"],
                model_parity_grant=grants["model"],
                identity_artifacts={"binding_sha256": identity_sha},
                production_runtime_bind_mount=runtime_binding,
                semantic_evidence_validator=(
                    entrypoint_module.publication_arm_semantic_evidence_validator_v3
                ),
                semantic_validator_identity_sha256="c" * 64,
            )

        self.assertEqual(result, {"sentinel": "committed"})
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(len(run_calls), 1)
        transaction = run_calls[0]
        self.assertEqual(
            transaction["execution_scope"],
            entrypoint_module.production_transaction_v3.PRODUCTION_EXECUTION_SCOPE,
        )
        self.assertEqual(
            transaction["expected_production_runtime_bind_mount"], runtime_binding
        )
        self.assertEqual(
            transaction["expected_runtime_binding_identity_sha256"],
            runtime_binding["binding_sha256"],
        )
        self.assertEqual(
            transaction["semantic_evidence_validator"],
            entrypoint_module.publication_arm_semantic_evidence_validator_v3,
        )

    def test_exactly_maps_frozen_arm_to_run_one_in_local_heterogeneous_mode(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_run_one(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            arm = frozen_arm()
            return {
                "status": "completed",
                "system": arm["system"],
                "scenario": arm["scenario"],
                "repeat": arm["repeat"],
                "streams": arm["streams"],
                "duration_s": arm["measurement_s"],
                "policy": arm["policy"],
                "dataset": arm["dataset"],
                "seed": arm["seed"],
                "deadline_ms": arm["deadline_ms"],
                "distributed": False,
                "deployment_mode": "heterogeneous",
            }

        identity = model_parity_identity()
        parity_grant = model_parity_grant_from_identity_artifacts(identity)
        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            resource_capability_grant=resource_capability_grant(),
            model_parity_grant=parity_grant,
            identity_artifacts=identity,
            run_one_fn=fake_run_one,
        )
        arm_root = self.root / "run" / "arm"
        result = runner(arm_context(), arm_root)

        self.assertEqual(result, {"status": "completed", "arm_id": frozen_arm()["arm_id"]})
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["config"], self.config)
        self.assertEqual(call["project_root"], self.root.resolve())
        self.assertEqual(call["dataset"]["name"], "kpp_iss_publication_v3_h264")
        self.assertEqual(call["system_key"], "gstreamer_custom")
        self.assertEqual(call["scenario"]["name"], "checkpoint_video_dag_shared")
        self.assertEqual(call["streams"], 6)
        self.assertEqual(call["duration_s"], 180)
        self.assertEqual(call["repeat_index"], 1)
        self.assertEqual(call["run_root"], arm_root)
        self.assertEqual(call["mode"], "benchmark")
        self.assertEqual(call["policy"], "cpu_only")
        self.assertEqual(call["deadline_ms"], 100.0)
        self.assertEqual(call["base_seed"], 20260323)
        self.assertFalse(call["dry_run_plan"])
        self.assertEqual(
            call["directory_dataset_name"], "kpp_iss_publication_v3_h264"
        )
        self.assertEqual(call["directory_policy"], "cpu_only")
        self.assertEqual(
            call["resource_capability_grant"], resource_capability_grant()
        )
        self.assertEqual(call["model_parity_grant"], parity_grant)
        self.assertEqual(call["full_publication_identity_artifacts"], identity)
        context = call["execution_context"]
        self.assertEqual(context.run_kind, "heterogeneous")
        self.assertEqual(context.deployment_mode, "heterogeneous")
        self.assertFalse(context.distributed_enabled)

    def test_rejects_parity_grant_that_does_not_match_immutable_identity(self) -> None:
        identity = model_parity_identity()
        drifted_identity = copy.deepcopy(identity)
        parity = drifted_identity["bindings"]["analytics_model_parity"]
        parity["evidence_sha256"] = "0" * 64
        parity["binding_sha256"] = canonical_sha(
            {
                key: value
                for key, value in parity.items()
                if key != "binding_sha256"
            }
        )
        drifted_identity["binding_sha256"] = canonical_sha(
            {
                key: value
                for key, value in drifted_identity.items()
                if key != "binding_sha256"
            }
        )
        with self.assertRaisesRegex(ContractError, "differs from immutable"):
            RealArmRunner(
                config=self.config,
                project_root=self.root,
                dataset_manifest_path=self.root / "configs" / "datasets.yaml",
                verified_datasets=self.datasets,
                model_parity_grant=model_parity_grant_from_identity_artifacts(
                    identity
                ),
                identity_artifacts=drifted_identity,
                run_one_fn=lambda **_: {},
            )

    def test_rejects_run_one_that_cannot_receive_parity_grant_before_launch(self) -> None:
        identity = model_parity_identity()

        def legacy_run_one() -> dict[str, object]:
            raise AssertionError("legacy run_one was launched")

        with self.assertRaisesRegex(ContractError, "cannot receive"):
            RealArmRunner(
                config=self.config,
                project_root=self.root,
                dataset_manifest_path=self.root / "configs" / "datasets.yaml",
                verified_datasets=self.datasets,
                model_parity_grant=model_parity_grant_from_identity_artifacts(
                    identity
                ),
                identity_artifacts=identity,
                run_one_fn=legacy_run_one,
            )

    def test_rejects_arm_protocol_drift_before_launch(self) -> None:
        called = False

        def fake_run_one(**kwargs: object) -> dict[str, object]:
            nonlocal called
            called = True
            return {}

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            run_one_fn=fake_run_one,
        )
        with self.assertRaisesRegex(ContractError, "warmup_s"):
            runner(arm_context(frozen_arm(warmup_s=29)), self.root / "arm")
        self.assertFalse(called)

    def test_rejects_codec_dataset_mapping_drift(self) -> None:
        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            run_one_fn=lambda **_: {},
        )
        with self.assertRaisesRegex(ContractError, "codec/dataset"):
            runner(
                arm_context(
                    frozen_arm(
                        codec="h265",
                        dataset="kpp_iss_publication_v3_h264",
                    )
                ),
                self.root / "arm",
            )

    def test_rejects_run_one_result_identity_drift(self) -> None:
        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            run_one_fn=lambda **_: {
                "status": "completed",
                "system": "deepstream",
                "scenario": "checkpoint_video_dag_shared",
                "repeat": 1,
                "streams": 6,
                "duration_s": 180,
                "policy": "cpu_only",
                "dataset": "kpp_iss_publication_v3_h264",
                "seed": 20260323,
                "deadline_ms": 100.0,
                "distributed": False,
                "deployment_mode": "heterogeneous",
            },
        )
        with self.assertRaisesRegex(ContractError, "system"):
            runner(arm_context(), self.root / "arm")

    def test_pins_every_container_reference_to_frozen_image_id(self) -> None:
        calls: list[dict[str, object]] = []
        frozen_ids = {
            name: "sha256:" + hashlib.sha256(name.encode("utf-8")).hexdigest()
            for name in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
        }

        def fake_run_one(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            arm = frozen_arm()
            return {
                "status": "completed",
                "system": arm["system"],
                "scenario": arm["scenario"],
                "repeat": arm["repeat"],
                "streams": arm["streams"],
                "duration_s": arm["measurement_s"],
                "policy": arm["policy"],
                "dataset": arm["dataset"],
                "seed": arm["seed"],
                "deadline_ms": arm["deadline_ms"],
                "distributed": False,
                "deployment_mode": "heterogeneous",
            }

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            frozen_image_ids=frozen_ids,
            run_one_fn=fake_run_one,
        )
        runner(arm_context(), self.root / "arm")
        executed_config = calls[0]["config"]
        self.assertEqual(
            executed_config["systems"]["gstreamer_custom"]["container_image"],
            frozen_ids["gstreamer_custom"],
        )

    def test_rejects_execution_input_drift_before_launch(self) -> None:
        guarded = self.root / "scripts" / "runtime.sh"
        guarded.parent.mkdir(exist_ok=True)
        guarded.write_bytes(b"old")
        stat = guarded.stat()
        guard = ImmutableFileGuard(
            path=guarded,
            size_bytes=int(stat.st_size),
            mtime_ns=int(stat.st_mtime_ns),
            sha256=hashlib.sha256(b"old").hexdigest(),
        )
        called = False

        def fake_run_one(**_: object) -> dict[str, object]:
            nonlocal called
            called = True
            return {}

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            execution_guards=(guard,),
            run_one_fn=fake_run_one,
        )
        guarded.write_bytes(b"changed")
        with self.assertRaisesRegex(ContractError, "immutable execution input changed"):
            runner(arm_context(), self.root / "arm")
        self.assertFalse(called)

    def test_identity_artifact_guard_rehashes_despite_unchanged_size_and_mtime(self) -> None:
        guarded = self.root / "accepted" / "receipt.json"
        guarded.parent.mkdir()
        guarded.write_bytes(b"old")
        original = guarded.stat()
        guard = ImmutableFileGuard(
            path=guarded,
            size_bytes=int(original.st_size),
            mtime_ns=int(original.st_mtime_ns),
            sha256=hashlib.sha256(b"old").hexdigest(),
            always_rehash=True,
        )
        called = False

        def fake_run_one(**_: object) -> dict[str, object]:
            nonlocal called
            called = True
            return {}

        runner = RealArmRunner(
            config=self.config,
            project_root=self.root,
            dataset_manifest_path=self.root / "configs" / "datasets.yaml",
            verified_datasets=self.datasets,
            execution_guards=(guard,),
            run_one_fn=fake_run_one,
        )
        guarded.write_bytes(b"new")
        os.utime(
            guarded,
            ns=(int(original.st_atime_ns), int(original.st_mtime_ns)),
        )
        with self.assertRaisesRegex(ContractError, "immutable execution input changed"):
            runner(arm_context(), self.root / "arm")
        self.assertFalse(called)


class IdentityMaterialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in (
            "scripts", "deploy", "configs", "policies", "data", "models", "accepted"
        ):
            (self.root / directory).mkdir()
        (self.root / "scripts" / "tracked.py").write_text("print('tracked')\n", encoding="utf-8")
        (self.root / "scripts" / "untracked.py").write_text("print('untracked')\n", encoding="utf-8")
        (self.root / "deploy" / "native.cpp").write_text("int main(){}\n", encoding="utf-8")
        (self.root / "policies" / "frozen.policy").write_bytes(b"policy")
        (self.root / "CMakeLists.txt").write_text("project(vast)\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text("PyYAML==6.0\n", encoding="utf-8")
        (self.root / "data" / "kpp_iss_publication_v3_h264.avi").write_bytes(
            b"h264-data"
        )
        (self.root / "data" / "kpp_iss_publication_v3_h265.avi").write_bytes(
            b"h265-data"
        )
        (self.root / "models" / "branch.xml").write_bytes(b"xml-model")
        (self.root / "models" / "branch.bin").write_bytes(b"bin-weights")

        self.config = minimal_config(self.root)
        self.config_path = self.root / "configs" / "experiments.yaml"
        self.config_path.write_text(yaml.safe_dump(self.config, sort_keys=False), encoding="utf-8")
        self.datasets_path = self.root / "configs" / "datasets.yaml"
        self.datasets_path.write_text("datasets: {}\n", encoding="utf-8")
        self.models_path = self.root / "configs" / "models.yaml"
        model_sha = hashlib.sha256((self.root / "models" / "branch.xml").read_bytes()).hexdigest()
        weights_sha = hashlib.sha256((self.root / "models" / "branch.bin").read_bytes()).hexdigest()
        self.models_path.write_text(
            yaml.safe_dump(
                {
                    "branches": {
                        "plate_number": {
                            "model_path": "../models/branch.xml",
                            "model_sha256": model_sha,
                            "weights_path": "../models/branch.bin",
                            "weights_sha256": weights_sha,
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.links = SeafileShareLinks.from_urls(
            "https://seafile.example/u/d/UploadSecretToken",
            "https://seafile.example/d/ReadSecretToken",
        )
        accepted_path = self.root / "accepted" / "identity-receipt.json"
        accepted_path.write_bytes(b"{}\n")
        accepted_record = {
            "path": accepted_path.relative_to(self.root).as_posix(),
            "size_bytes": accepted_path.stat().st_size,
            "sha256": hashlib.sha256(accepted_path.read_bytes()).hexdigest(),
        }
        self.identity_artifacts = {
            "schema_version": 2,
            "artifact_kind": "vast_full_publication_identity_artifact_binding",
            "manifest": accepted_record,
            "bindings": {},
            "files": [accepted_record],
            "files_sha256": canonical_sha([accepted_record]),
        }
        self.identity_artifacts["binding_sha256"] = canonical_sha(
            self.identity_artifacts
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _dataset_loader(self, manifest_path: Path, name: str, **kwargs: object) -> dict[str, object]:
        codec = "h265" if name.endswith("h265") else "h264"
        return resolved_dataset(self.root, name, codec)

    @staticmethod
    def _command_runner(command: list[str]) -> str:
        if command[:3] == ["docker", "image", "inspect"]:
            reference = command[-1]
            suffix = hashlib.sha256(reference.encode("utf-8")).hexdigest()
            return json.dumps(
                {
                    "Id": f"sha256:{suffix}",
                    "RepoDigests": [f"{reference.split(':')[0]}@sha256:{suffix}"],
                    "Architecture": "amd64",
                    "Os": "linux",
                }
            )
        if command[:2] == ["docker", "version"]:
            return json.dumps(
                {
                    "Client": {"Version": "28.0", "ApiVersion": "1.48", "GitCommit": "client"},
                    "Server": {
                        "Version": "28.0",
                        "ApiVersion": "1.48",
                        "GitCommit": "server",
                        "Os": "linux",
                        "Arch": "amd64",
                        "KernelVersion": "6.6",
                        "Components": [
                            {"Name": "Engine", "Version": "28.0"},
                            {"Name": "containerd", "Version": "1.7"},
                            {"Name": "runc", "Version": "1.2"},
                        ],
                    },
                }
            )
        if command[0] == "nvidia-smi":
            return "NVIDIA GeForce RTX 3060, GPU-uuid, 00000000:01:00.0, 555.42\n"
        if command[0] == "lscpu":
            return json.dumps(
                {
                    "lscpu": [
                        {"field": "Architecture:", "data": "x86_64"},
                        {"field": "CPU(s):", "data": "28"},
                        {"field": "Model name:", "data": "Intel Core i7-14700K"},
                        {"field": "Vendor ID:", "data": "GenuineIntel"},
                    ]
                }
            )
        raise AssertionError(command)

    def test_identity_binds_untracked_sources_actual_artifacts_images_hardware_and_redacted_cloud(self) -> None:
        material = build_identity_material(
            project_root=self.root,
            config_path=self.config_path,
            dataset_manifest_path=self.datasets_path,
            model_manifest_path=self.models_path,
            config=self.config,
            cloud_links=self.links,
            cloud_destination_id="vast-full-publication-private-v1",
            dataset_loader=self._dataset_loader,
            command_runner=self._command_runner,
            ram_bytes=22 * 1024**3,
            identity_artifacts=self.identity_artifacts,
        )
        identity = material.identity_inputs
        source_paths = {record["path"] for record in identity["runtime_sources"]["files"]}
        self.assertIn("scripts/untracked.py", source_paths)
        self.assertIn("deploy/native.cpp", source_paths)
        self.assertIn("configs/experiments.yaml", source_paths)
        self.assertIn("policies/frozen.policy", source_paths)
        self.assertEqual(identity["config"]["sha256"], hashlib.sha256(self.config_path.read_bytes()).hexdigest())
        self.assertEqual(
            set(identity["datasets"]),
            {
                "kpp_iss_publication_v3_h264",
                "kpp_iss_publication_v3_h265",
            },
        )
        self.assertEqual(identity["models"]["artifacts"][0]["sha256"], hashlib.sha256((self.root / "models" / "branch.xml").read_bytes()).hexdigest())
        self.assertEqual(len(identity["container_images"]), 4)
        self.assertEqual(identity["hardware_runtime"]["detected_hardware"]["ram_gb"], 22.0)
        rendered = json.dumps(identity, sort_keys=True)
        self.assertNotIn("UploadSecretToken", rendered)
        self.assertNotIn("ReadSecretToken", rendered)
        self.assertNotIn("seafile.example", rendered)
        self.assertRegex(identity["cloud_destination"]["destination_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            set(material.datasets),
            {
                "kpp_iss_publication_v3_h264",
                "kpp_iss_publication_v3_h265",
            },
        )
        guarded_paths = {guard.path.relative_to(self.root).as_posix() for guard in material.execution_guards}
        self.assertIn("scripts/untracked.py", guarded_paths)
        self.assertIn("models/branch.xml", guarded_paths)
        self.assertIn("data/kpp_iss_publication_v3_h264.avi", guarded_paths)
        accepted_guard = next(
            guard
            for guard in material.execution_guards
            if guard.path == self.root / "accepted" / "identity-receipt.json"
        )
        self.assertTrue(accepted_guard.always_rehash)
        self.assertEqual(
            identity["identity_artifacts"]["binding_sha256"],
            self.identity_artifacts["binding_sha256"],
        )

    def test_windows_cpu_probe_falls_back_to_cim_when_lscpu_is_unavailable(self) -> None:
        def windows_runner(command: list[str]) -> str:
            if command[0] == "lscpu":
                raise OSError("lscpu is not installed on the Windows host")
            if command[0] == "powershell":
                return json.dumps(
                    {
                        "Name": "Intel Core i7-14700K",
                        "Manufacturer": "GenuineIntel",
                        "NumberOfLogicalProcessors": 28,
                        "Architecture": 9,
                        "ProcessorId": "BFEBFBFF000B0671",
                    }
                )
            return self._command_runner(command)

        with patch("full_publication_entrypoint.platform.system", return_value="Windows"):
            material = build_identity_material(
                project_root=self.root,
                config_path=self.config_path,
                dataset_manifest_path=self.datasets_path,
                model_manifest_path=self.models_path,
                config=self.config,
                cloud_links=self.links,
                cloud_destination_id="vast-full-publication-private-v1",
                dataset_loader=self._dataset_loader,
                command_runner=windows_runner,
                ram_bytes=22 * 1024**3,
                identity_artifacts=self.identity_artifacts,
            )

        cpu = material.identity_inputs["hardware_runtime"]["cpu"]
        self.assertEqual(cpu["source"], "windows_cim")
        self.assertEqual(cpu["model_name"], "Intel Core i7-14700K")
        self.assertEqual(cpu["logical_cpus"], "28")

    def test_cloud_identity_survives_capability_rotation_but_binds_destination_id(self) -> None:
        def identity(links: SeafileShareLinks, destination_id: str) -> dict[str, object]:
            return build_identity_material(
                project_root=self.root,
                config_path=self.config_path,
                dataset_manifest_path=self.datasets_path,
                model_manifest_path=self.models_path,
                config=self.config,
                cloud_links=links,
                cloud_destination_id=destination_id,
                dataset_loader=self._dataset_loader,
                command_runner=self._command_runner,
                ram_bytes=22 * 1024**3,
                identity_artifacts=self.identity_artifacts,
            ).identity_inputs["cloud_destination"]

        rotated = SeafileShareLinks.from_urls(
            "https://seafile.example/u/d/NewUploadToken99",
            "https://seafile.example/d/NewReadToken99",
        )
        before = identity(self.links, "vast-full-publication-private-v1")
        after = identity(rotated, "vast-full-publication-private-v1")
        other = identity(rotated, "vast-full-publication-private-v2")
        self.assertEqual(before, after)
        self.assertNotEqual(after["destination_sha256"], other["destination_sha256"])

    def test_cloud_capability_environment_is_consumed_before_local_probes(self) -> None:
        values = {
            "VAST_SEAFILE_UPLOAD_LINK": "https://seafile.example/u/d/UploadSecretToken",
            "VAST_SEAFILE_READ_LINK": "https://seafile.example/d/ReadSecretToken",
        }
        with patch.dict("full_publication_entrypoint.os.environ", values, clear=False):
            links = _consume_cloud_links_from_environment()
            self.assertEqual(links.base_url, "https://seafile.example")
            self.assertNotIn(
                "VAST_SEAFILE_UPLOAD_LINK",
                sys.modules["full_publication_entrypoint"].os.environ,
            )
            self.assertNotIn(
                "VAST_SEAFILE_READ_LINK",
                sys.modules["full_publication_entrypoint"].os.environ,
            )

    def test_model_hash_mismatch_is_permanent_contract_error(self) -> None:
        manifest = yaml.safe_load(self.models_path.read_text(encoding="utf-8"))
        manifest["branches"]["plate_number"]["model_sha256"] = "0" * 64
        self.models_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "model_sha256"):
            build_identity_material(
                project_root=self.root,
                config_path=self.config_path,
                dataset_manifest_path=self.datasets_path,
                model_manifest_path=self.models_path,
                config=self.config,
                cloud_links=self.links,
                cloud_destination_id="vast-full-publication-private-v1",
                dataset_loader=self._dataset_loader,
                command_runner=self._command_runner,
                ram_bytes=22 * 1024**3,
                identity_artifacts=self.identity_artifacts,
            )

    def test_legacy_identity_binding_cannot_build_execution_identity(self) -> None:
        legacy = copy.deepcopy(self.identity_artifacts)
        legacy["schema_version"] = 1
        legacy["binding_sha256"] = canonical_sha(
            {key: value for key, value in legacy.items() if key != "binding_sha256"}
        )
        with self.assertRaisesRegex(
            ContractError, "identity artifact binding is invalid"
        ):
            build_identity_material(
                project_root=self.root,
                config_path=self.config_path,
                dataset_manifest_path=self.datasets_path,
                model_manifest_path=self.models_path,
                config=self.config,
                cloud_links=self.links,
                cloud_destination_id="vast-full-publication-private-v1",
                dataset_loader=self._dataset_loader,
                command_runner=self._command_runner,
                ram_bytes=22 * 1024**3,
                identity_artifacts=legacy,
            )

    def test_missing_local_container_image_fails_closed(self) -> None:
        def missing_image(command: list[str]) -> str:
            if command[:3] == ["docker", "image", "inspect"]:
                raise OSError("image missing")
            return self._command_runner(command)

        with self.assertRaisesRegex(ContractError, "container image inspect failed"):
            build_identity_material(
                project_root=self.root,
                config_path=self.config_path,
                dataset_manifest_path=self.datasets_path,
                model_manifest_path=self.models_path,
                config=self.config,
                cloud_links=self.links,
                cloud_destination_id="vast-full-publication-private-v1",
                dataset_loader=self._dataset_loader,
                command_runner=missing_image,
                ram_bytes=22 * 1024**3,
                identity_artifacts=self.identity_artifacts,
            )


class FakeRunner:
    MANIFEST_NAME = "run_manifest.json"
    CHECKPOINT_NAME = "checkpoint.json"

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.run_calls = 0
        self.finalize_calls = 0
        self.plan_value = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_execution_plan",
            "matrix_identity": {"schema_version": 2, "sha256": MATRIX_SHA},
            "run_identity": {"schema_version": 1, "sha256": RUN_SHA},
            "expected_pairs": 2800,
            "expected_arms": 5600,
            "pairs": [],
        }

    def plan(self) -> dict[str, object]:
        return copy.deepcopy(self.plan_value)

    def run(self) -> RunResult:
        self.run_calls += 1
        self.run_root.mkdir(parents=True, exist_ok=True)
        return RunResult(
            exit_code=ExitCode.TRANSIENT,
            status="paused_transient",
            completed_pairs=12,
            completed_arms=24,
            total_pairs=2800,
            total_arms=5600,
            next_sequence=12,
            message="cloud retry",
        )

    def status(self) -> dict[str, object]:
        return {
            "artifact_kind": "status",
            "exit_code": 75,
            "state": "paused_transient",
            "completed_pairs": 12,
            "total_pairs": 2800,
            "matrix_identity": {"schema_version": 2, "sha256": MATRIX_SHA},
            "run_identity": {"schema_version": 1, "sha256": RUN_SHA},
        }

    def verify(self) -> dict[str, object]:
        return {"artifact_kind": "verify", "passed": True, "complete": False}

    def finalize(self) -> dict[str, object]:
        self.finalize_calls += 1
        return {"artifact_kind": "finalization", "verified": True}

    def finalized_snapshot(self) -> dict[str, object]:
        raise ContractError("full publication results require a finalized run")


class FakeRuntime:
    def __init__(self, decision: CallbackDecision) -> None:
        self.decision = decision
        self.contexts: list[RunContext] = []

    def preflight(self, context: RunContext) -> CallbackDecision:
        self.contexts.append(context)
        return self.decision


class ProductionRunRootGuardTests(unittest.TestCase):
    def test_run_root_is_confined_to_a_dedicated_publication_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "repo"
            project_root.mkdir()
            expected = project_root / "runs" / "full_publication" / "run-001"
            self.assertEqual(
                _validated_run_root(expected, project_root=project_root),
                expected.resolve(),
            )
            for unsafe in (
                project_root,
                project_root / "scripts" / "run",
                project_root / ".git" / "run",
                project_root / "data" / "run",
                project_root / "runs" / "full_publication",
                project_root / "runs" / "other",
            ):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(
                    ContractError, "run_root must"
                ):
                    _validated_run_root(unsafe, project_root=project_root)


class OfflinePublicationPlanTests(unittest.TestCase):
    def test_real_plan_factory_is_offline_read_only_and_needs_no_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "repo"
            config_path = project_root / "configs" / "experiments.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                yaml.safe_dump(minimal_config(project_root), sort_keys=False),
                encoding="utf-8",
            )
            args = build_parser().parse_args(
                [
                    "--project-root",
                    str(project_root),
                    "--config",
                    str(config_path),
                    "plan",
                ]
            )

            with (
                patch(
                    "full_publication_entrypoint._consume_cloud_links_from_environment",
                    side_effect=AssertionError("plan touched Seafile capabilities"),
                ),
                patch(
                    "full_publication_entrypoint.build_identity_material",
                    side_effect=AssertionError("plan built execution/hardware identity"),
                ),
                patch(
                    "full_publication_entrypoint.load_full_publication_identity_artifacts",
                    side_effect=AssertionError("plan read accepted identity artifacts"),
                ),
                patch(
                    "full_publication_entrypoint.subprocess.check_output",
                    side_effect=AssertionError("plan launched a system probe"),
                ),
            ):
                app = create_application(args)
                exit_code, plan = app.dispatch("plan")

            self.assertEqual(exit_code, 0)
            self.assertEqual(plan["artifact_kind"], "vast_full_publication_offline_plan")
            self.assertTrue(plan["planning_only"])
            self.assertEqual(plan["execution_identity_status"], "not_built_offline")
            self.assertNotIn("run_identity", plan)
            self.assertEqual(plan["expected_pairs"], 2800)
            self.assertEqual(plan["expected_arms"], 5600)
            self.assertEqual(len(plan["pairs"]), 2800)
            self.assertEqual(
                plan["policy_contract_identity"],
                plan["matrix_contract"]["policy_contract_identity"],
            )
            self.assertEqual(len(plan["policies"]), 7)
            self.assertFalse((project_root / "runs").exists())

    def test_offline_plan_fails_closed_on_frozen_policy_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            config = minimal_config(project_root)
            config["benchmark"]["scheduler_policies"] = list(
                reversed(config["benchmark"]["scheduler_policies"])
            )
            with self.assertRaisesRegex(ContractError, "frozen policy contract"):
                build_offline_publication_plan(config)

    def test_nonplan_factory_still_requires_a_run_root(self) -> None:
        args = build_parser().parse_args(["preflight"])
        with self.assertRaisesRegex(ContractError, "--run-root is required"):
            create_application(args)

    def test_nonplan_missing_identity_manifest_blocks_before_cloud_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "repo"
            config_path = project_root / "configs" / "experiments.yaml"
            config_path.parent.mkdir(parents=True)
            config_path.write_text(
                yaml.safe_dump(minimal_config(project_root), sort_keys=False),
                encoding="utf-8",
            )
            run_root = project_root / "runs" / "full_publication" / "blocked"
            args = build_parser().parse_args(
                [
                    "--project-root",
                    str(project_root),
                    "--run-root",
                    str(run_root),
                    "--config",
                    str(config_path),
                    "preflight",
                ]
            )

            with (
                patch(
                    "full_publication_entrypoint._validated_run_root",
                    return_value=run_root,
                ),
                patch(
                    "full_publication_entrypoint._consume_cloud_links_from_environment",
                    side_effect=AssertionError(
                        "blocked identity consumed cloud capabilities"
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    ContractError, "identity artifact manifest is missing"
                ):
                    create_application(args)

            self.assertFalse(run_root.exists())

    def test_system_probe_child_environment_excludes_seafile_capabilities(self) -> None:
        secrets = {
            "VAST_SEAFILE_UPLOAD_LINK": "https://seafile.example/u/d/UploadSecretToken",
            "VAST_SEAFILE_READ_LINK": "https://seafile.example/d/ReadSecretToken",
        }
        with (
            patch.dict("full_publication_entrypoint.os.environ", secrets, clear=False),
            patch(
                "full_publication_entrypoint.subprocess.check_output",
                return_value="probe-output\n",
            ) as check_output,
        ):
            self.assertEqual(_default_command_runner(["probe"]), "probe-output")

        child_environment = check_output.call_args.kwargs["env"]
        self.assertNotIn("VAST_SEAFILE_UPLOAD_LINK", child_environment)
        self.assertNotIn("VAST_SEAFILE_READ_LINK", child_environment)


class ProductionEntrypointTests(unittest.TestCase):
    def test_blocked_run_does_not_initialize_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "must-not-exist"
            runner = FakeRunner(run_root)
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(
                    CallbackDecision.rejected("scientific readiness blocked", retryable=False)
                ),
            )
            exit_code, payload = app.dispatch("run")
            self.assertEqual(exit_code, int(ExitCode.PERMANENT))
            self.assertEqual(payload["status"], "blocked_preflight")
            self.assertEqual(runner.run_calls, 0)
            self.assertFalse(run_root.exists())
            self.assertFalse((run_root / "run_manifest.json").exists())

    def test_transient_external_preflight_maps_to_75_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(Path(tmp) / "run")
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(
                    CallbackDecision.rejected("cloud unavailable", retryable=True)
                ),
            )
            exit_code, payload = app.dispatch("run")
            self.assertEqual(exit_code, int(ExitCode.TRANSIENT))
            self.assertTrue(payload["retryable"])
            self.assertEqual(runner.run_calls, 0)

    def test_ready_run_delegates_and_preserves_runner_exit_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(Path(tmp) / "run")
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(CallbackDecision.passed({"ready": True})),
            )
            exit_code, payload = app.dispatch("run")
            self.assertEqual(exit_code, 75)
            self.assertEqual(payload["exit_code"], 75)
            self.assertEqual(payload["completed_pairs"], 12)
            self.assertEqual(runner.run_calls, 1)

    def test_plan_and_preflight_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            runner = FakeRunner(run_root)
            runtime = FakeRuntime(CallbackDecision.passed({"cloud": "ready"}))
            app = ProductionEntrypoint(runner=runner, runtime=runtime)
            plan_exit, plan = app.dispatch("plan")
            preflight_exit, preflight = app.dispatch("preflight")
            self.assertEqual((plan_exit, preflight_exit), (0, 0))
            self.assertEqual(plan["expected_arms"], 5600)
            self.assertEqual(preflight["status"], "ready")
            self.assertFalse(run_root.exists())
            self.assertEqual(runtime.contexts[0].total_pairs, 2800)

    def test_external_preflight_uses_durable_resume_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            run_root.mkdir()
            (run_root / "run_manifest.json").write_text("{}\n", encoding="utf-8")
            (run_root / "checkpoint.json").write_text("{}\n", encoding="utf-8")
            runner = FakeRunner(run_root)
            runtime = FakeRuntime(CallbackDecision.passed({"cloud": "ready"}))
            app = ProductionEntrypoint(runner=runner, runtime=runtime)
            exit_code, _ = app.dispatch("preflight")
            self.assertEqual(exit_code, 0)
            self.assertEqual(runtime.contexts[0].next_sequence, 12)

    def test_status_verify_and_finalize_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            run_root.mkdir()
            runner = FakeRunner(run_root)
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(CallbackDecision.passed()),
            )
            self.assertEqual(app.dispatch("status")[0], 75)
            self.assertEqual(app.dispatch("verify")[0], 75)
            self.assertEqual(app.dispatch("finalize")[0], 0)
            self.assertEqual(runner.finalize_calls, 1)

    def test_incomplete_run_is_not_exported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            run_root.mkdir()
            runner = FakeRunner(run_root)
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(CallbackDecision.passed()),
            )
            with self.assertRaisesRegex(ContractError, "finalized run"):
                app.dispatch("export")
            self.assertFalse((run_root / "results").exists())

    def test_finalized_export_uses_run_root_default_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            run_root.mkdir()
            runner = FakeRunner(run_root)
            calls: list[object] = []

            def fake_exporter(selected_runner: object) -> dict[str, object]:
                calls.append(selected_runner)
                output = run_root / "results"
                output.mkdir()
                (output / "result_bundle_manifest.json").write_text("{}\n", encoding="utf-8")
                return {
                    "schema_version": 1,
                    "artifact_kind": "vast_full_publication_compact_result_bundle",
                    "verified_pairs": 2800,
                    "verified_arms": 5600,
                }

            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(CallbackDecision.passed()),
                results_exporter=fake_exporter,
            )
            exit_code, payload = app.dispatch("export")
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["verified_arms"], 5600)
            self.assertEqual(calls, [runner])
            self.assertTrue((run_root / "results" / "result_bundle_manifest.json").is_file())

    def test_main_prints_json_and_returns_strict_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner(Path(tmp) / "run")
            app = ProductionEntrypoint(
                runner=runner,
                runtime=FakeRuntime(CallbackDecision.passed()),
            )
            output: list[str] = []
            code = main(
                ["--run-root", str(runner.run_root), "plan"],
                application_factory=lambda _args: app,
                output_fn=output.append,
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output[0])["expected_pairs"], 2800)

    def test_parser_exposes_no_cloud_credentials(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertNotIn("upload-link", help_text)
        self.assertNotIn("read-link", help_text)
        args = parser.parse_args(["--run-root", "run", "plan"])
        self.assertEqual(args.command, "plan")
        export_args = parser.parse_args(["--run-root", "run", "export"])
        self.assertEqual(export_args.command, "export")


class ProductionReadinessTests(unittest.TestCase):
    def test_hardware_mismatch_blocks_otherwise_ready_assessment(self) -> None:
        config = {
            "hardware_target": {
                "gpu_model": "NVIDIA GeForce RTX 3060",
                "cpu_model": "Intel Core i7-14700K",
                "ram_gb": 22,
            }
        }
        hardware = {
            "gpu_model": "NVIDIA GeForce RTX 4090",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22.0,
        }
        result = production_readiness_validator(
            config,
            detected_hardware=hardware,
            scientific_validator=lambda _: {
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_readiness",
                "passed": True,
                "status": "ready",
                "blockers": [],
            },
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("hardware:gpu_model_mismatch", result["blockers"])

    def test_verified_grant_is_forwarded_to_scientific_readiness(self) -> None:
        config = {
            "hardware_target": {
                "gpu_model": "NVIDIA GeForce RTX 3060",
                "cpu_model": "Intel Core i7-14700K",
                "ram_gb": 22,
            }
        }
        hardware = {
            "gpu_model": "NVIDIA GeForce RTX 3060",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22.0,
        }
        received: list[tuple[object, object, object]] = []

        def scientific(
            _config: dict[str, object],
            *,
            resource_capability_grant: object,
            backend_runtime_grant: object,
            model_parity_grant: object,
        ) -> dict[str, object]:
            received.append(
                (
                    resource_capability_grant,
                    backend_runtime_grant,
                    model_parity_grant,
                )
            )
            return {
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_readiness",
                "passed": True,
                "status": "ready",
                "blockers": [],
            }

        parity_grant = model_parity_grant_from_identity_artifacts(
            model_parity_identity()
        )
        result = production_readiness_validator(
            config,
            detected_hardware=hardware,
            resource_capability_grant=resource_capability_grant(),
            model_parity_grant=parity_grant,
            scientific_validator=scientific,
        )

        self.assertTrue(result["passed"])
        self.assertEqual(
            received,
            [(resource_capability_grant(), None, parity_grant)],
        )

    def test_tampered_parity_grant_is_rejected_before_scientific_readiness(self) -> None:
        parity_grant = model_parity_grant_from_identity_artifacts(
            model_parity_identity()
        )
        parity_grant["status"] = "fake_ready"
        called = False

        def scientific(
            _config: dict[str, object], **_grants: object
        ) -> dict[str, object]:
            nonlocal called
            called = True
            return {"passed": True, "blockers": []}

        with self.assertRaisesRegex(ContractError, "model-parity"):
            production_readiness_validator(
                {"hardware_target": {}},
                detected_hardware={},
                model_parity_grant=parity_grant,
                scientific_validator=scientific,
            )
        self.assertFalse(called)

    def test_verified_grant_rejects_legacy_scientific_validator_signature(self) -> None:
        config = {
            "hardware_target": {
                "gpu_model": "NVIDIA GeForce RTX 3060",
                "cpu_model": "Intel Core i7-14700K",
                "ram_gb": 22,
            }
        }
        with self.assertRaisesRegex(
            ContractError, "cannot receive all verified pre-run grants"
        ):
            production_readiness_validator(
                config,
                detected_hardware={
                    "gpu_model": "NVIDIA GeForce RTX 3060",
                    "cpu_model": "Intel Core i7-14700K",
                    "ram_gb": 22.0,
                },
                resource_capability_grant=resource_capability_grant(),
                scientific_validator=lambda _config: {
                    "passed": True,
                    "blockers": [],
                },
            )


if __name__ == "__main__":
    unittest.main()
