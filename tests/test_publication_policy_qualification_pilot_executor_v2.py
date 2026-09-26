#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import importlib.util
import io
import inspect
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_pilot_executor_v2 as target  # noqa: E402
import publication_policy_qualification_execution_code_closure_v1 as code_closure_target  # noqa: E402
import checkpoint_qualification_pilot_acceptance_v1 as acceptance_target  # noqa: E402
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationOutcomeV3,
    NativePublicationRequestV3,
)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value).rstrip(b"\n")).hexdigest()


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


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def descriptor(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def acceptance_payload(
    cell: target.QualificationPilotCellV2,
    fixture: "InputFixture | None" = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_checkpoint_qualification_pilot_acceptance_v1",
        "status": "accepted_native_qualification_pilot",
        "scope": "pre_run_policy_and_full_resource_qualification_only",
        "run_id": cell.run_id,
        "arm_id": cell.arm_id,
        "coordinate": {
            "system": cell.system,
            "resource": cell.resource,
            "codec": cell.codec,
            "topology_kind": cell.topology_kind,
        },
        "scenario": cell.scenario,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "accepted_for_full_publication": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": ["qualification_pilot_is_not_full_publication_arm"],
    }
    if fixture is not None:
        value["operational_binding"] = fixture.operational_binding(cell)
    return value


def write_child_evidence(
    output_dir: Path,
    cell: target.QualificationPilotCellV2,
    evidence_names: tuple[str, ...] = target.CHILD_EVIDENCE_FILES,
) -> None:
    candidate_name = "checkpoint_publication_candidate.json"
    for name in evidence_names:
        if name != candidate_name:
            (output_dir / name).write_text(
                f"{cell.run_id}:{name}\n", encoding="utf-8"
            )
    prefinal_names = target.CHILD_EVIDENCE_FILES[:-3]
    candidate = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_candidate",
        "status": "pending_full_resource_validation",
        "run_id": cell.run_id,
        "system": cell.system,
        "scenario": cell.scenario,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "execution_binding_provenance": "native_scheduler_execution_binding_v1",
        "topology_kind": cell.topology_kind,
        "cohort_id": f"cohort-{cell.arm_id}",
        "measurement_schedule_fingerprint_sha256": "6" * 64,
        "completed_frames_by_stream": {str(index): 1 for index in range(6)},
        "summary": {},
        "evidence_sha256": {
            name: sha256(output_dir / name) for name in prefinal_names
        },
        "pending_full_resource_evidence": [
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        ],
    }
    write_json(output_dir / candidate_name, candidate)


def write_request_child_evidence(request: NativePublicationRequestV3) -> None:
    cell = next(
        item
        for item in target.qualification_pilot_cells_v2()
        if item.arm_id == request.arm_id
    )
    write_child_evidence(
        request.output_dir,
        cell,
        request.launcher_evidence_files,
    )


def commit_pilot_output(
    fixture: "InputFixture", cell: target.QualificationPilotCellV2
) -> Path:
    pilot_root = fixture.pilot_root
    final = (
        pilot_root / cell.system / cell.resource / cell.codec / cell.topology_kind
    )
    final.mkdir(parents=True)
    write_child_evidence(final, cell)
    (final / "hardware_resource_samples.csv").write_text("hardware\n", encoding="utf-8")
    write_json(
        final / target.ACCEPTANCE_FILENAME,
        acceptance_payload(cell, fixture),
    )
    return final


class InputFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.input_dir = root / "qualification-input"
        self.bootstrap_dir = root / "bootstrap"
        self.pilot_root = root / "pilots"
        self.checkpoint = root / "state/pilot-execution.v3.json"
        self.input_dir.mkdir(parents=True)
        self.bootstrap_dir.mkdir()
        self.pilot_root.mkdir()
        self.checkpoint.parent.mkdir()
        self.policy_contract_sha256 = "1" * 64
        self.parity_binding_sha256 = "3" * 64
        self.physical_evidence_sha256 = canonical_sha([])
        self.hardware_resource_collector = root / "scripts/collect_metrics.py"
        self.hardware_resource_collector.parent.mkdir(parents=True, exist_ok=True)
        self.hardware_resource_collector.write_bytes(
            b"# qualification collector fixture\n"
        )
        for module in code_closure_target.SEED_MODULES:
            source = root / "scripts" / f"{module}.py"
            if not source.exists():
                source.write_text(
                    "from __future__ import annotations\n", encoding="utf-8"
                )
        self.execution_code_closure_receipt = (
            root / "authority/execution-code-closure.v1.json"
        )
        code_closure_target.materialize_execution_code_closure_v1(
            project_root=root,
            receipt_path=self.execution_code_closure_receipt,
        )

        self.candidate_manifest = self.input_dir / "candidate-manifest.json"
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_capability_manifest",
            "policy_contract_sha256": self.policy_contract_sha256,
            "systems": {system: {} for system in target.SYSTEMS},
        }
        write_json(self.candidate_manifest, manifest)

        self.candidate_index = self.input_dir / "candidate-index.json"
        index = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_index",
            "policy_contract_sha256": self.policy_contract_sha256,
            "dataset_manifest": {
                "path": "configs/datasets.yaml",
                "size_bytes": 1,
                "sha256": "2" * 64,
            },
            "bindings": [
                {
                    "system": system,
                    "branch": branch,
                    "resource": resource,
                }
                for system in target.SYSTEMS
                for branch in ("plate_number", "vehicle_type", "damage", "foreign_object")
                for resource in target.RESOURCES
            ],
            "pilots": [],
        }
        write_json(self.candidate_index, index)

        self.candidate_receipt = self.input_dir / "candidate-receipt.json"
        receipt = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": self.policy_contract_sha256,
            "qualification_index": descriptor(root, self.candidate_index),
            "candidate_manifest": descriptor(root, self.candidate_manifest),
            "blockers": ["candidate_is_not_a_full_publication_authority"],
        }
        receipt["sha256"] = canonical_sha(receipt)
        write_json(self.candidate_receipt, receipt)

        parity_dir = root / "accepted-parity"
        parity_dir.mkdir()
        self.parity_manifest = parity_dir / "manifest.yaml"
        self.parity_assessment = parity_dir / "assessment.json"
        self.parity_receipt = parity_dir / "receipt.json"
        self.parity_manifest.write_text("schema_version: 3\n", encoding="ascii")
        write_json(self.parity_assessment, {"accepted": True})
        write_json(self.parity_receipt, {"accepted": True})
        transaction_index = {
            "path": "accepted-parity/transaction-index.json",
            "size_bytes": 1,
            "sha256": "4" * 64,
        }

        calibrations: dict[str, object] = {}
        self.calibration_paths: dict[str, Path] = {}
        for system in target.SYSTEMS:
            path = self.bootstrap_dir / target.BOOTSTRAP_CALIBRATION_FILENAME.format(
                system=system
            )
            value = {
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
                "source_candidate_manifest_sha256": sha256(
                    self.candidate_manifest
                ),
                "source_model_parity_acceptance_binding_sha256": (
                    self.parity_binding_sha256
                ),
                "source_physical_response_evidence_sha256": (
                    self.physical_evidence_sha256
                ),
            }
            write_json(path, value)
            self.calibration_paths[system] = path
            calibrations[system] = value

        self.bootstrap_mapping = self.bootstrap_dir / "mapping.json"
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
            "candidate_manifest_sha256": sha256(self.candidate_manifest),
            "candidate_receipt_sha256": sha256(self.candidate_receipt),
            "model_parity_acceptance_binding_sha256": self.parity_binding_sha256,
            "calibration_evidence_sha256": canonical_sha([]),
            "physical_response_evidence_sha256": self.physical_evidence_sha256,
            "calibrations": calibrations,
        }
        write_json(self.bootstrap_mapping, mapping)

        self.bootstrap_receipt = self.bootstrap_dir / "receipt.json"
        bootstrap_receipt = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_bootstrap_receipt",
            "status": "qualification_bootstrap_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": self.policy_contract_sha256,
            "candidate_manifest": descriptor(root, self.candidate_manifest),
            "candidate_receipt": descriptor(root, self.candidate_receipt),
            "candidate_receipt_identity_sha256": receipt["sha256"],
            "qualification_index": descriptor(root, self.candidate_index),
            "accepted_model_parity_manifest": descriptor(
                root, self.parity_manifest
            ),
            "accepted_model_parity_assessment": descriptor(
                root, self.parity_assessment
            ),
            "accepted_model_parity_receipt": descriptor(
                root, self.parity_receipt
            ),
            "model_parity_acceptance_binding_sha256": self.parity_binding_sha256,
            "accepted_model_parity_evidence_sha256": "5" * 64,
            "calibration_evidence": [],
            "calibration_evidence_sha256": canonical_sha([]),
            "transaction_index": transaction_index,
            "physical_response_evidence": [],
            "physical_response_evidence_sha256": self.physical_evidence_sha256,
            "mapping": descriptor(root, self.bootstrap_mapping),
            "calibrations": {
                system: descriptor(root, path)
                for system, path in self.calibration_paths.items()
            },
            "blockers": [
                "bootstrap_is_not_policy_qualification_acceptance",
                "bootstrap_is_not_full_publication_authority",
                "bootstrap_is_valid_only_for_forced_cpu_only_gpu_only_pilots",
            ],
        }
        bootstrap_receipt["receipt_sha256"] = canonical_sha(bootstrap_receipt)
        write_json(self.bootstrap_receipt, bootstrap_receipt)

        self.socket_path = root / "analytics.sock"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.socket_path))
        self.socket.listen(8)

        self.fragment_paths: dict[str, Path] = {}
        for system in target.SYSTEMS:
            fragment_path = root / f"fragments/{system}/qualification_fragment.json"
            write_json(fragment_path, {"system": system})
            self.fragment_paths[system] = fragment_path
        self.image_patch = root / "authorities/image-patch.json"
        write_json(self.image_patch, {"patch_sha256": "8" * 64})
        self.transaction_receipt = (
            self.input_dir / "qualification_input_transaction.v2.receipt.json"
        )
        transaction_receipt = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_input_transaction_v2"
            ),
            "status": "qualification_inputs_materialized_nonaccepted",
            "scope": "forced_resource_qualification_pilots_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "systems": list(target.SYSTEMS),
            "cell_count": 32,
            "hardware_resource_collector": descriptor(
                root, self.hardware_resource_collector
            ),
            "image_identity_patch": descriptor(root, self.image_patch),
            "image_identity_patch_sha256": "8" * 64,
            "accepted_model_parity_manifest": descriptor(
                root, self.parity_manifest
            ),
            "accepted_model_parity_assessment": descriptor(
                root, self.parity_assessment
            ),
            "accepted_model_parity_receipt": descriptor(
                root, self.parity_receipt
            ),
            "model_parity_acceptance_binding_sha256": (
                self.parity_binding_sha256
            ),
            "model_parity_acceptance_schema_version": 2,
            "image_patch_resolution": {
                "candidate_binding_eligible": True,
                "resolved_blockers": [],
                "resolution": "unchanged_v3_parity",
            },
            "fragments": {
                system: descriptor(root, path)
                for system, path in self.fragment_paths.items()
            },
            "candidate": {
                "index": descriptor(root, self.candidate_index),
                "manifest": descriptor(root, self.candidate_manifest),
                "receipt": descriptor(root, self.candidate_receipt),
            },
            "bootstrap": {
                "mapping": descriptor(root, self.bootstrap_mapping),
                "calibrations": {
                    system: descriptor(root, path)
                    for system, path in self.calibration_paths.items()
                },
                "receipt": descriptor(root, self.bootstrap_receipt),
            },
            "blockers": [
                "transaction_is_not_policy_qualification_acceptance",
                "transaction_is_not_full_publication_authority",
                "transaction_requires_exact_32_physical_pilots",
            ],
        }
        transaction_receipt["receipt_sha256"] = canonical_sha(
            transaction_receipt
        )
        write_json(self.transaction_receipt, transaction_receipt)

        runtime_root = self.bootstrap_dir / target.RUNTIME_BUNDLE_DIRECTORY
        self.runtime_bundle_paths: dict[str, Path] = {}
        bundle_records: list[dict[str, object]] = []
        for cell in target.qualification_pilot_cells_v2():
            bundle_path = (
                runtime_root
                / cell.system
                / cell.resource
                / cell.codec
                / f"{cell.topology_kind}.json"
            )
            bundle = {
                "schema_version": 2,
                "artifact_kind": target.RUNTIME_BUNDLE_KIND,
                "status": "materialized_for_native_qualification_only",
                "accepted": False,
                "publication_ready": False,
                "authorization_eligible": False,
                "scope": target.RUNTIME_BUNDLE_SCOPE,
                "system": cell.system,
                "resource": cell.resource,
                "codec": cell.codec,
                "topology_kind": cell.topology_kind,
                "run_id": cell.run_id,
                "arm_id": cell.arm_id,
                "hardware_resource_collector": descriptor(
                    root, self.hardware_resource_collector
                ),
                "runtime_inputs": {},
                "launcher_evidence_files": list(target.CHILD_EVIDENCE_FILES),
            }
            bundle["bundle_sha256"] = canonical_sha(bundle)
            write_json(bundle_path, bundle)
            self.runtime_bundle_paths[cell.arm_id] = bundle_path
            bundle_descriptor = descriptor(root, bundle_path)
            bundle_records.append(
                {
                    "arm_id": cell.arm_id,
                    "run_id": cell.run_id,
                    "path": bundle_path.relative_to(runtime_root).as_posix(),
                    "size_bytes": bundle_descriptor["size_bytes"],
                    "sha256": bundle_descriptor["sha256"],
                    "bundle_sha256": bundle["bundle_sha256"],
                }
            )
        socket_info = self.socket_path.stat()
        socket_binding = {
            "path": str(self.socket_path),
            "device": int(socket_info.st_dev),
            "inode": int(socket_info.st_ino),
            "owner_uid": int(socket_info.st_uid),
            "owner_gid": int(socket_info.st_gid),
        }
        engine_asset = runtime_root / "_assets/container-engine/docker"
        engine_asset.parent.mkdir(parents=True, exist_ok=True)
        engine_asset.write_bytes(b"docker-test-asset\n")
        generated_assets = []
        for system in target.SYSTEMS:
            path = runtime_root / f"_assets/{system}/adapter-config.json"
            write_json(path, {"system": system})
            record = descriptor(root, path)
            generated_assets.append(
                {
                    "system": system,
                    **record,
                    "container_path": f"/opt/vast/{system}/adapter.json",
                }
            )
        self.runtime_materialization_receipt = (
            runtime_root / target.RUNTIME_MATERIALIZATION_RECEIPT_FILENAME
        )
        materialization = {
            "schema_version": 2,
            "artifact_kind": target.RUNTIME_MATERIALIZATION_RECEIPT_KIND,
            "status": "materialized_for_native_qualification_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "scope": target.RUNTIME_BUNDLE_SCOPE,
            "matrix_sha256": target._matrix_sha(
                target.qualification_pilot_cells_v2()
            ),
            "inputs": {
                "candidate_index_sha256": sha256(self.candidate_index),
                "candidate_manifest_sha256": sha256(self.candidate_manifest),
                "candidate_receipt_sha256": sha256(self.candidate_receipt),
                "bootstrap_mapping_sha256": sha256(self.bootstrap_mapping),
                "bootstrap_receipt_sha256": sha256(self.bootstrap_receipt),
                "qualification_input_transaction_receipt_sha256": sha256(
                    self.transaction_receipt
                ),
                "hardware_resource_collector": descriptor(
                    root, self.hardware_resource_collector
                ),
                "inventory_sha256": "9" * 64,
            },
            "container_engine": {
                "source_path": "/usr/bin/docker",
                "asset_path": engine_asset.relative_to(root).as_posix(),
                "size_bytes": engine_asset.stat().st_size,
                "sha256": sha256(engine_asset),
            },
            "live_sockets": {
                "container_engine": socket_binding,
                "analytics_execution": socket_binding,
            },
            "container_images": {system: {} for system in target.SYSTEMS},
            "device_probes": {
                "openvino_gva": {},
                "gstreamer_custom": {},
            },
            "generated_assets": generated_assets,
            "bundles": bundle_records,
            "blockers": [
                "qualification_runtime_inputs_are_not_production_authority"
            ],
        }
        materialization["receipt_sha256"] = canonical_sha(materialization)
        write_json(self.runtime_materialization_receipt, materialization)

        self.guardian_service_authority = root / "guardian/service_authority.v1.json"
        self.preprocessing_authority = {
            "preprocessing_contract_content_sha256": "d" * 64,
            "materialization_receipt_identity_sha256": "b" * 64,
            "materialization_receipt_file_sha256": "0" * 64,
            "qualification_transaction_receipt_sha256": transaction_receipt[
                "receipt_sha256"
            ],
            "policy_contract_sha256": self.policy_contract_sha256,
        }
        self.runtime_expectations = {
            "execution_config_identity_sha256": "e" * 64,
            "binding_set_identity_sha256": "f" * 64,
            "bindings_identity_sha256": "0" * 64,
            "worker_image_ids": {
                "cpu": "sha256:" + "1" * 64,
                "gpu": "sha256:" + "2" * 64,
            },
            "policy_contract_sha256": self.policy_contract_sha256,
            "preprocessing_contract_content_sha256": "d" * 64,
        }
        service_authority = {
            "service_authority_sha256": "a" * 64,
            "service_identity_sha256": "c" * 64,
            "preprocessing_contract_authority": self.preprocessing_authority,
            "execution_config_identity_sha256": self.runtime_expectations[
                "execution_config_identity_sha256"
            ],
            "binding_set_identity_sha256": self.runtime_expectations[
                "binding_set_identity_sha256"
            ],
            "worker_image_ids": self.runtime_expectations["worker_image_ids"],
            "front_socket": socket_binding,
        }
        write_json(self.guardian_service_authority, service_authority)
        self.preprocessing_contract = root / "guardian/preprocessing-contract.json"
        write_json(self.preprocessing_contract, {"contract": "frozen"})
        self.preprocessing_receipt = root / "guardian/preprocessing-receipt.json"
        write_json(
            self.preprocessing_receipt,
            {"preprocessing_contract": descriptor(root, self.preprocessing_contract)},
        )
        self.preprocessing_authority["materialization_receipt_file_sha256"] = sha256(
            self.preprocessing_receipt
        )
        service_authority["preprocessing_contract_authority"] = (
            self.preprocessing_authority
        )
        write_json(self.guardian_service_authority, service_authority)

    def close(self) -> None:
        self.socket.close()
        self.socket_path.unlink(missing_ok=True)

    def arguments(self) -> dict[str, object]:
        return {
            "project_root": self.root,
            "candidate_index_path": self.candidate_index,
            "candidate_manifest_path": self.candidate_manifest,
            "candidate_receipt_path": self.candidate_receipt,
            "bootstrap_mapping_path": self.bootstrap_mapping,
            "bootstrap_receipt_path": self.bootstrap_receipt,
            "bootstrap_dir": self.bootstrap_dir,
            "transaction_receipt_path": self.transaction_receipt,
            "runtime_input_materialization_receipt_path": (
                self.runtime_materialization_receipt
            ),
            "guardian_service_authority_path": self.guardian_service_authority,
            "preprocessing_contract_path": self.preprocessing_contract,
            "preprocessing_contract_receipt_path": self.preprocessing_receipt,
            "execution_code_closure_receipt_path": (
                self.execution_code_closure_receipt
            ),
            "pilot_root": self.pilot_root,
            "checkpoint_path": self.checkpoint,
            "deadline_ms": 100,
            "duration_s": 180,
            "service_authority_validator": lambda value, **_kwargs: dict(value),
            "preprocessing_contract_loader": self.preprocessing_loader,
            "runtime_expectations_loader": (
                lambda _receipt: dict(self.runtime_expectations)
            ),
        }

    def preprocessing_loader(self, **_kwargs: object) -> dict[str, object]:
        return {
            "preprocessing_contract": json.loads(
                self.preprocessing_contract.read_bytes()
            ),
            "receipt": json.loads(self.preprocessing_receipt.read_bytes()),
            "authority": dict(self.preprocessing_authority),
        }

    def operational_binding(
        self, cell: target.QualificationPilotCellV2
    ) -> dict[str, object]:
        transaction = json.loads(self.transaction_receipt.read_bytes())
        materialization = json.loads(
            self.runtime_materialization_receipt.read_bytes()
        )
        bundle_path = self.runtime_bundle_paths[cell.arm_id]
        bundle = json.loads(bundle_path.read_bytes())
        service = json.loads(self.guardian_service_authority.read_bytes())
        return {
            "hardware_resource_collector": descriptor(
                self.root, self.hardware_resource_collector
            ),
            "qualification_input_transaction_receipt": descriptor(
                self.root, self.transaction_receipt
            ),
            "qualification_input_transaction_receipt_identity_sha256": transaction[
                "receipt_sha256"
            ],
            "runtime_input_materialization_receipt": descriptor(
                self.root, self.runtime_materialization_receipt
            ),
            "runtime_input_materialization_receipt_identity_sha256": materialization[
                "receipt_sha256"
            ],
            "runtime_input_bundle": descriptor(self.root, bundle_path),
            "runtime_input_bundle_identity_sha256": bundle["bundle_sha256"],
            "guardian_service_authority": descriptor(
                self.root, self.guardian_service_authority
            ),
            "guardian_service_authority_identity_sha256": service[
                "service_authority_sha256"
            ],
            "guardian_preprocessing_contract_receipt": descriptor(
                self.root, self.preprocessing_receipt
            ),
            "guardian_preprocessing_contract_receipt_identity_sha256": "b" * 64,
        }

    def request(
        self,
        cell: target.QualificationPilotCellV2,
        output_dir: Path,
        evidence_names: tuple[str, ...],
    ) -> NativePublicationRequestV3:
        info = self.socket_path.stat()
        socket_binding = {
            "path": str(self.socket_path),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
            "owner_uid": int(info.st_uid),
            "owner_gid": int(info.st_gid),
        }
        runtime_key = target.RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
        endpoint = {
            **socket_binding,
            "container_path": "/run/vast/analytics-execution.sock",
        }
        contract = {
            "defer_full_resource_acceptance": True,
            "evidence_mapping": {name: name for name in evidence_names},
            "container_engine_socket": socket_binding,
            "endpoint_sockets": (
                [
                    {
                        "host_path": endpoint.pop("path"),
                        **endpoint,
                    }
                ]
                if cell.system in {"deepstream", "savant"}
                else {"analytics_execution": endpoint}
            ),
        }
        runtime_inputs = {
            "system": cell.system,
            "resource": cell.resource,
            "scenario": cell.scenario,
            "topology_kind": cell.topology_kind,
            "codec": cell.codec,
            "policy": cell.policy,
            "deadline_ms": cell.deadline_ms,
            "duration_s": cell.duration_s,
            "streams": 6,
            "run_id": cell.run_id,
            "dataset": {runtime_key: contract},
        }
        return NativePublicationRequestV3(
            system=cell.system,
            topology_kind=cell.topology_kind,
            scenario=cell.scenario,
            project_root=self.root,
            output_dir=output_dir,
            arm_contract_path=self.candidate_index,
            arm_contract_file_sha256=sha256(self.candidate_index),
            run_id=cell.run_id,
            arm_id=cell.arm_id,
            runtime_inputs=runtime_inputs,
            launcher_evidence_files=evidence_names,
        )


class FakeCollector:
    def __init__(self, path: Path, *, run_id: str, events: list[tuple[str, str]]) -> None:
        self.path = path
        self.run_id = run_id
        self.events = events
        self.started = False
        self.stopped = False
        self.joined = False

    def start(self) -> None:
        self.started = True
        self.events.append((self.run_id, "collector.start"))
        self.path.write_text("hardware\n", encoding="utf-8")

    def wait_until_ready(self, *, timeout_s: float) -> None:
        if not self.started or timeout_s <= 0:
            raise AssertionError("collector readiness ordering drifted")

    def stop(self) -> None:
        self.stopped = True
        self.events.append((self.run_id, "collector.stop"))

    def join(self, timeout: float | None = None) -> None:
        if not self.stopped or timeout is None or timeout <= 0:
            raise AssertionError("collector join ordering drifted")
        self.joined = True
        self.events.append((self.run_id, "collector.join"))

    def is_alive(self) -> bool:
        return False

    def raise_if_failed(self) -> None:
        if not self.joined:
            raise AssertionError("collector was not joined")


class QualificationPilotExecutorV2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        def validate_fake_acceptance(**kwargs: object) -> dict[str, object]:
            path = kwargs["acceptance_path"]
            self.assertIsInstance(path, Path)
            return json.loads(path.read_text(encoding="ascii"))  # type: ignore[union-attr]

        patcher = mock.patch.object(
            target,
            "validate_checkpoint_qualification_pilot_acceptance_v1",
            side_effect=validate_fake_acceptance,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_acceptance_operational_binding_rehashes_collector_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = InputFixture(Path(temporary).resolve())
            cell = target.qualification_pilot_cells_v2()[0]
            service = json.loads(
                fixture.guardian_service_authority.read_bytes()
            )

            def material() -> dict[str, object]:
                return acceptance_target._operational_material(
                    root=fixture.root,
                    expected_system=cell.system,
                    expected_resource=cell.resource,
                    expected_codec=cell.codec,
                    expected_topology_kind=cell.topology_kind,
                    expected_run_id=cell.run_id,
                    expected_arm_id=cell.arm_id,
                    candidate_manifest_path=fixture.candidate_manifest,
                    qualification_transaction_receipt_path=(
                        fixture.transaction_receipt
                    ),
                    runtime_input_materialization_receipt_path=(
                        fixture.runtime_materialization_receipt
                    ),
                    runtime_input_bundle_path=fixture.runtime_bundle_paths[
                        cell.arm_id
                    ],
                    guardian_service_authority_path=(
                        fixture.guardian_service_authority
                    ),
                    preprocessing_contract_path=fixture.preprocessing_contract,
                    preprocessing_contract_receipt_path=(
                        fixture.preprocessing_receipt
                    ),
                    require_live_service=False,
                )

            try:
                with (
                    mock.patch.object(
                        acceptance_target,
                        "_load_guardian_preprocessing",
                        side_effect=fixture.preprocessing_loader,
                    ),
                    mock.patch.object(
                        acceptance_target,
                        "_runtime_expectations_from_preprocessing_receipt",
                        return_value=dict(fixture.runtime_expectations),
                    ),
                    mock.patch.object(
                        acceptance_target,
                        "_validate_guardian_service_authority",
                        return_value=service,
                    ),
                ):
                    binding = material()
                    self.assertEqual(
                        binding["hardware_resource_collector"],
                        descriptor(
                            fixture.root,
                            fixture.hardware_resource_collector,
                        ),
                    )
                    fixture.hardware_resource_collector.write_bytes(
                        b"# tampered qualification collector\n"
                    )
                    with self.assertRaisesRegex(
                        acceptance_target.QualificationPilotAcceptanceV1Error,
                        "hardware resource collector binding drifted",
                    ):
                        material()
            finally:
                fixture.close()

    def test_frozen_matrix_is_exact_and_forced_resource_only(self) -> None:
        cells = target.qualification_pilot_cells_v2(
            deadline_ms=100, duration_s=180
        )
        self.assertEqual(len(cells), 32)
        self.assertEqual(
            {(cell.system, cell.resource, cell.codec, cell.topology_kind) for cell in cells},
            {
                (system, resource, codec, topology)
                for system in target.SYSTEMS
                for resource in target.RESOURCES
                for codec in target.CODECS
                for topology in target.TOPOLOGIES
            },
        )
        self.assertEqual(
            {cell.policy for cell in cells}, {"cpu_only", "gpu_only"}
        )
        self.assertEqual(
            {cell.resource: cell.policy for cell in cells},
            {"cpu": "cpu_only", "gpu": "gpu_only"},
        )
        self.assertEqual(
            {cell.topology_kind: cell.scenario for cell in cells},
            target.SCENARIO_BY_TOPOLOGY,
        )
        self.assertEqual(len({cell.run_id for cell in cells}), 32)
        self.assertEqual(len({cell.arm_id for cell in cells}), 32)
        self.assertTrue(all(cell.deadline_ms == 100 for cell in cells))
        self.assertTrue(all(cell.duration_s == 180 for cell in cells))

    def test_canonical_bundle_mapping_order_is_not_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = InputFixture(Path(temporary).resolve())
            try:
                inputs = target._load_qualification_inputs(
                    project_root=fixture.root,
                    candidate_index_path=fixture.candidate_index,
                    candidate_manifest_path=fixture.candidate_manifest,
                    candidate_receipt_path=fixture.candidate_receipt,
                    bootstrap_mapping_path=fixture.bootstrap_mapping,
                    bootstrap_receipt_path=fixture.bootstrap_receipt,
                    bootstrap_dir=fixture.bootstrap_dir,
                    transaction_receipt_path=fixture.transaction_receipt,
                )
                cell = target.qualification_pilot_cells_v2()[0]
                request = fixture.request(
                    cell,
                    fixture.pilot_root,
                    target.CHILD_EVIDENCE_FILES,
                )
                canonical_runtime_inputs = json.loads(
                    canonical_bytes(request.runtime_inputs)
                )
                mapping = canonical_runtime_inputs["dataset"][
                    target.RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
                ]["evidence_mapping"]
                self.assertNotEqual(tuple(mapping), target.CHILD_EVIDENCE_FILES)

                target._validate_request(
                    replace(request, runtime_inputs=canonical_runtime_inputs),
                    inputs=inputs,
                    cell=cell,
                    output_dir=fixture.pilot_root,
                )
            finally:
                fixture.close()

    def test_custodied_pin_rejects_parent_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_parent = root / "inputs"
            source_parent.mkdir()
            source = source_parent / "authority.json"
            source.write_bytes(target._canonical_bytes({"authority": "original"}))
            with target.PhysicalRootCustodyV1.open(
                root, label="test qualification root"
            ) as custody:
                token = target._ACTIVE_PHYSICAL_CUSTODY.set(custody)
                try:
                    pin = target._pin_json(root, source, label="test authority")
                    source_parent.rename(root / "inputs-held")
                    source_parent.mkdir()
                    source.write_bytes(
                        target._canonical_bytes({"authority": "replacement"})
                    )
                    with self.assertRaisesRegex(
                        target.QualificationPilotExecutorV2Error,
                        "custody|changed",
                    ):
                        target._assert_pin_unchanged(pin, label="test authority")
                finally:
                    target._ACTIVE_PHYSICAL_CUSTODY.reset(token)

    def test_checkpoint_exact_retry_binds_prior_inode_prefix_and_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            state = root / "state"
            state.mkdir()
            checkpoint = state / "checkpoint.json"
            with target.PhysicalRootCustodyV1.open(
                root, label="test qualification root"
            ) as custody:
                token = target._ACTIVE_PHYSICAL_CUSTODY.set(custody)
                try:
                    first = target._write_checkpoint(
                        checkpoint,
                        {"completed": []},
                        expected_previous_identity=None,
                        expected_completed_prefix=(),
                    )
                    retried = target._write_checkpoint(
                        checkpoint,
                        {"completed": []},
                        expected_previous_identity=first,
                        expected_completed_prefix=(),
                    )
                    self.assertNotEqual(first, retried)
                    with self.assertRaisesRegex(
                        target.QualificationPilotExecutorV2Error,
                        "deterministic prefix",
                    ):
                        target._write_checkpoint(
                            checkpoint,
                            {"completed": [{"arm_id": "wrong"}]},
                            expected_previous_identity=retried,
                            expected_completed_prefix=("expected",),
                        )
                    alias = state / "checkpoint.alias.json"
                    alias.hardlink_to(checkpoint)
                    with self.assertRaises(target.QualificationPilotExecutorV2Error):
                        target._write_checkpoint(
                            checkpoint,
                            {"completed": []},
                            expected_previous_identity=retried,
                            expected_completed_prefix=(),
                        )
                    alias.unlink()
                    collision = state / "collision.json"
                    collision.write_text("collision\n", encoding="ascii")
                    with self.assertRaisesRegex(
                        target.QualificationPilotExecutorV2Error, "appeared|collision"
                    ):
                        target._write_checkpoint(
                            collision,
                            {"completed": []},
                            expected_previous_identity=None,
                            expected_completed_prefix=(),
                        )
                    dangling = state / "dangling.json"
                    dangling.symlink_to(state / "missing.json")
                    with self.assertRaisesRegex(
                        target.QualificationPilotExecutorV2Error, "appeared|collision"
                    ):
                        target._write_checkpoint(
                            dangling,
                            {"completed": []},
                            expected_previous_identity=None,
                            expected_completed_prefix=(),
                        )
                finally:
                    target._ACTIVE_PHYSICAL_CUSTODY.reset(token)

    def test_initial_checkpoint_anchor_three_physical_windows(self) -> None:
        windows = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for window in windows:
            with self.subTest(window=window), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                state = root / "state"
                state.mkdir()
                checkpoint = state / "checkpoint.json"
                payload = {"completed": []}

                def crash(step: str) -> None:
                    if step == window:
                        raise RuntimeError("synthetic physical crash")

                with target.PhysicalRootCustodyV1.open(
                    root, label="test qualification root"
                ) as custody:
                    token = target._ACTIVE_PHYSICAL_CUSTODY.set(custody)
                    try:
                        with self.assertRaisesRegex(
                            RuntimeError, "synthetic physical crash"
                        ):
                            target._write_checkpoint(
                                checkpoint,
                                payload,
                                expected_previous_identity=None,
                                expected_completed_prefix=(),
                                _fault_hook=crash,
                            )
                        if checkpoint.exists():
                            descriptor, captured, identity = (
                                custody.read_descriptor_identity(
                                    checkpoint,
                                    label="published initial checkpoint anchor",
                                    maximum=1024,
                                    capture=True,
                                )
                            )
                            self.assertEqual(captured, target._canonical_bytes(payload))
                            self.assertEqual(
                                descriptor["sha256"],
                                hashlib.sha256(captured).hexdigest(),
                            )
                            self.assertEqual(
                                identity,
                                (checkpoint.stat().st_dev, checkpoint.stat().st_ino),
                            )
                        else:
                            target._write_checkpoint(
                                checkpoint,
                                payload,
                                expected_previous_identity=None,
                                expected_completed_prefix=(),
                            )
                            self.assertEqual(
                                checkpoint.read_bytes(), target._canonical_bytes(payload)
                            )
                    finally:
                        target._ACTIVE_PHYSICAL_CUSTODY.reset(token)

    @unittest.skipUnless(
        is_wsl_drvfs_workspace(),
        "live no-replace fallback requires the WSL DrvFS workspace",
    )
    def test_drvfs_directory_commit_succeeds_and_never_overwrites_collision(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".qualification-directory-commit.", dir=ROOT
        ) as temporary:
            parent = Path(temporary)
            source = parent / "source"
            destination = parent / "destination"
            source.mkdir()
            (source / "payload").write_text("first\n", encoding="ascii")

            target._rename_directory_noreplace(source, destination)  # noqa: SLF001
            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "payload").read_text(encoding="ascii"),
                "first\n",
            )

            colliding_source = parent / "colliding-source"
            colliding_source.mkdir()
            (colliding_source / "payload").write_text(
                "second\n", encoding="ascii"
            )
            with self.assertRaises(target.QualificationPilotExecutorV2Error):
                target._rename_directory_noreplace(  # noqa: SLF001
                    colliding_source, destination
                )
            self.assertEqual(
                (destination / "payload").read_text(encoding="ascii"),
                "first\n",
            )
            self.assertEqual(
                (colliding_source / "payload").read_text(encoding="ascii"),
                "second\n",
            )

    @unittest.skipUnless(
        is_wsl_drvfs_workspace(),
        "live no-replace fallback requires the WSL DrvFS workspace",
    )
    def test_drvfs_directory_commit_does_not_depend_on_ambient_cwd(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".qualification-directory-commit.", dir=ROOT
        ) as temporary, tempfile.TemporaryDirectory() as ambient:
            parent = Path(temporary)
            source = parent / "source"
            destination = parent / "destination"
            source.mkdir()
            (source / "payload").write_text("first\n", encoding="ascii")
            vanished_cwd = Path(ambient) / "vanished-cwd"
            vanished_cwd.mkdir()
            original_cwd = os.open(".", os.O_RDONLY)
            try:
                os.chdir(vanished_cwd)
                vanished_cwd.rmdir()
                target._rename_directory_noreplace(  # noqa: SLF001
                    source, destination
                )
            finally:
                os.fchdir(original_cwd)
                os.close(original_cwd)

            self.assertFalse(source.exists())
            self.assertEqual(
                (destination / "payload").read_text(encoding="ascii"),
                "first\n",
            )

    def test_registry_is_the_four_direct_lower_native_runtime_callables(self) -> None:
        from checkpoint_deepstream_publication_runtime_v3 import (
            run_checkpoint_deepstream_publication_runtime_v3,
        )
        from checkpoint_gstreamer_publication_runtime_v3 import (
            run_checkpoint_gstreamer_publication_runtime_v3,
        )
        from checkpoint_openvino_gva_publication_runtime_v3 import (
            run_checkpoint_openvino_gva_publication_runtime_v3,
        )
        from checkpoint_savant_publication_runtime_v3 import (
            run_checkpoint_savant_publication_runtime_v3,
        )

        self.assertEqual(set(target.NATIVE_RUNTIME_REGISTRY), set(target.SYSTEMS))
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["deepstream"],
            run_checkpoint_deepstream_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["savant"],
            run_checkpoint_savant_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["openvino_gva"],
            run_checkpoint_openvino_gva_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["gstreamer_custom"],
            run_checkpoint_gstreamer_publication_runtime_v3,
        )

    def _validate_generated_asset_inventory(self, fixture: InputFixture):
        inputs = target._load_qualification_inputs(
            project_root=fixture.root,
            candidate_index_path=fixture.candidate_index,
            candidate_manifest_path=fixture.candidate_manifest,
            candidate_receipt_path=fixture.candidate_receipt,
            bootstrap_mapping_path=fixture.bootstrap_mapping,
            bootstrap_receipt_path=fixture.bootstrap_receipt,
            bootstrap_dir=fixture.bootstrap_dir,
            transaction_receipt_path=fixture.transaction_receipt,
        )
        cells = target.qualification_pilot_cells_v2()
        return target._validate_runtime_materialization_receipt(
            inputs=inputs,
            bootstrap_dir=fixture.bootstrap_dir,
            cells=cells,
            receipt=target._pin_json(
                fixture.root, fixture.runtime_materialization_receipt,
                label="test runtime materialization",
            ),
            runtime_bundles=target._pin_runtime_bundles(
                inputs=inputs, bootstrap_dir=fixture.bootstrap_dir, cells=cells,
            ),
        )

    def test_runtime_generated_assets_cover_all_four_systems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                value = self._validate_generated_asset_inventory(fixture)
                self.assertEqual(
                    {row["system"] for row in value["generated_assets"]},
                    {"deepstream", "savant", "openvino_gva", "gstreamer_custom"},
                )
                self.assertEqual(len(value["generated_assets"]), 4)
            finally:
                fixture.close()

    def test_runtime_generated_assets_reject_inventory_and_physical_drift(self) -> None:
        cases = [(kind, system) for kind in ("missing", "duplicate", "bytes")
                 for system in target.SYSTEMS] + [("unknown", "openvino_gva")]
        for kind, system in cases:
            with self.subTest(kind=kind, system=system), tempfile.TemporaryDirectory() as tmp:
                fixture = InputFixture(Path(tmp).resolve())
                try:
                    receipt = json.loads(fixture.runtime_materialization_receipt.read_bytes())
                    rows = receipt["generated_assets"]
                    row = next(item for item in rows if item["system"] == system)
                    if kind == "missing":
                        rows.remove(row)
                    elif kind == "duplicate":
                        rows.append(dict(row))
                    elif kind == "unknown":
                        row["system"] = "unregistered_runtime"
                    else:
                        (fixture.root / row["path"]).write_bytes(b"changed asset bytes\n")
                    receipt["receipt_sha256"] = canonical_sha(
                        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
                    )
                    write_json(fixture.runtime_materialization_receipt, receipt)
                    with self.assertRaises(target.QualificationPilotExecutorV2Error):
                        self._validate_generated_asset_inventory(fixture)
                finally:
                    fixture.close()

    def test_operational_chain_fails_closed_on_each_live_authority_drift(
        self,
    ) -> None:
        def load_inputs(fixture: InputFixture) -> target._QualificationInputs:
            return target._load_qualification_inputs(
                project_root=fixture.root,
                candidate_index_path=fixture.candidate_index,
                candidate_manifest_path=fixture.candidate_manifest,
                candidate_receipt_path=fixture.candidate_receipt,
                bootstrap_mapping_path=fixture.bootstrap_mapping,
                bootstrap_receipt_path=fixture.bootstrap_receipt,
                bootstrap_dir=fixture.bootstrap_dir,
                transaction_receipt_path=fixture.transaction_receipt,
            )

        def load_operational(
            fixture: InputFixture,
            *,
            preprocessing_loader=None,
        ) -> target._OperationalInputs:
            return target._load_operational_inputs(
                inputs=load_inputs(fixture),
                bootstrap_dir=fixture.bootstrap_dir,
                cells=target.qualification_pilot_cells_v2(),
                runtime_input_materialization_receipt_path=(
                    fixture.runtime_materialization_receipt
                ),
                guardian_service_authority_path=(
                    fixture.guardian_service_authority
                ),
                preprocessing_contract_path=fixture.preprocessing_contract,
                preprocessing_contract_receipt_path=(
                    fixture.preprocessing_receipt
                ),
                service_authority_validator=lambda value, **_kwargs: dict(value),
                preprocessing_contract_loader=(
                    fixture.preprocessing_loader
                    if preprocessing_loader is None
                    else preprocessing_loader
                ),
                runtime_expectations_loader=(
                    lambda _receipt: dict(fixture.runtime_expectations)
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                transaction = json.loads(fixture.transaction_receipt.read_bytes())
                transaction["receipt_sha256"] = "0" * 64
                write_json(fixture.transaction_receipt, transaction)
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "transaction receipt identity",
                ):
                    load_inputs(fixture)
            finally:
                fixture.close()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                transaction = json.loads(fixture.transaction_receipt.read_bytes())
                transaction.pop("hardware_resource_collector")
                transaction["receipt_sha256"] = canonical_sha(
                    {
                        key: value
                        for key, value in transaction.items()
                        if key != "receipt_sha256"
                    }
                )
                write_json(fixture.transaction_receipt, transaction)
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "transaction receipt identity",
                ):
                    load_inputs(fixture)
            finally:
                fixture.close()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                fixture.hardware_resource_collector.write_bytes(
                    b"# tampered qualification collector\n"
                )
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "hardware resource collector|descriptor content",
                ):
                    load_inputs(fixture)
            finally:
                fixture.close()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                receipt = json.loads(
                    fixture.runtime_materialization_receipt.read_bytes()
                )
                receipt["inputs"][
                    "qualification_input_transaction_receipt_sha256"
                ] = "0" * 64
                receipt["receipt_sha256"] = canonical_sha(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                )
                write_json(fixture.runtime_materialization_receipt, receipt)
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "runtime-input materialization receipt binding",
                ):
                    load_operational(fixture)
            finally:
                fixture.close()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                service = json.loads(
                    fixture.guardian_service_authority.read_bytes()
                )
                service["front_socket"]["inode"] += 1
                write_json(fixture.guardian_service_authority, service)
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "guardian authority is not cross-bound",
                ):
                    load_operational(fixture)
            finally:
                fixture.close()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                def drifted_preprocessing(**kwargs: object) -> dict[str, object]:
                    loaded = fixture.preprocessing_loader(**kwargs)
                    loaded["authority"][  # type: ignore[index]
                        "qualification_transaction_receipt_sha256"
                    ] = "0" * 64
                    return loaded

                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "preprocessing receipt operational binding",
                ):
                    load_operational(
                        fixture,
                        preprocessing_loader=drifted_preprocessing,
                    )
            finally:
                fixture.close()

    def test_default_guardian_assertion_requires_preprocessing_and_service_identity(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar

        preprocessing_authority = {
            "policy_contract_sha256": "1" * 64,
        }
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
        ):
            self.assertEqual(
                target._default_service_authority_validator(
                    {},
                    expected_preprocessing_contract_authority=(
                        preprocessing_authority
                    ),
                    expected_runtime_expectations=runtime_expectations,
                ),
                checked,
            )
        assertion.assert_called_once_with(
            {},
            expected_front_socket="/tmp/guardian.sock",
            expected_execution_config_identity_sha256="7" * 64,
            expected_binding_set_identity_sha256="8" * 64,
            expected_worker_image_ids=runtime_expectations["worker_image_ids"],
            expected_preprocessing_contract_authority=preprocessing_authority,
            expected_service_identity_sha256="6" * 64,
            expected_policy_contract_sha256="1" * 64,
        )

    def test_bootstrap_accepts_exact_v4_refresh_and_rejects_receipt_drift(
        self,
    ) -> None:
        from tests.test_checkpoint_model_parity_acceptance_v4 import _refresh

        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            try:
                refresh = _refresh()
                refresh_descriptors = [
                    ("image-patch", refresh["image_identity_patch"]),
                    ("execution-config", refresh["execution_config"]),
                    ("binding-index", refresh["binding_set"]["index"]),
                    *(
                        (
                            f"runtime-probe-{resource}",
                            refresh["runtime_probes"][resource],
                        )
                        for resource in target.RESOURCES
                    ),
                    *(
                        (f"binding-{coordinate}", item)
                        for coordinate, item in sorted(
                            refresh["binding_set"]["bindings"].items()
                        )
                    ),
                ]
                for label, item in refresh_descriptors:
                    path = fixture.root / item["path"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((label + "\n").encode("ascii"))
                    item.update(descriptor(fixture.root, path))

                mapping = json.loads(fixture.bootstrap_mapping.read_bytes())
                mapping["model_parity_refresh_authority"] = refresh
                write_json(fixture.bootstrap_mapping, mapping)
                receipt = json.loads(fixture.bootstrap_receipt.read_bytes())
                receipt["model_parity_refresh_authority"] = json.loads(
                    json.dumps(refresh)
                )
                receipt["mapping"] = descriptor(
                    fixture.root, fixture.bootstrap_mapping
                )
                receipt["receipt_sha256"] = canonical_sha(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                )
                write_json(fixture.bootstrap_receipt, receipt)

                precommit = target._load_qualification_inputs(
                    project_root=fixture.root,
                    candidate_index_path=fixture.candidate_index,
                    candidate_manifest_path=fixture.candidate_manifest,
                    candidate_receipt_path=fixture.candidate_receipt,
                    bootstrap_mapping_path=fixture.bootstrap_mapping,
                    bootstrap_receipt_path=fixture.bootstrap_receipt,
                    bootstrap_dir=fixture.bootstrap_dir,
                )
                self.assertIsNone(precommit.transaction_receipt)

                transaction = json.loads(
                    fixture.transaction_receipt.read_bytes()
                )
                transaction["image_identity_patch"] = descriptor(
                    fixture.root,
                    fixture.root / refresh["image_identity_patch"]["path"],
                )
                transaction["image_identity_patch_sha256"] = refresh[
                    "image_identity_patch"
                ]["patch_sha256"]
                transaction["model_parity_acceptance_schema_version"] = 4
                transaction["image_patch_resolution"] = {
                    "candidate_binding_eligible": False,
                    "resolved_blockers": list(
                        target.INPUT_TRANSACTION_REFRESH_BLOCKERS
                    ),
                    "resolution": "physical_patch_bound_v4_parity_refresh",
                }
                transaction["bootstrap"]["mapping"] = descriptor(
                    fixture.root, fixture.bootstrap_mapping
                )
                transaction["bootstrap"]["receipt"] = descriptor(
                    fixture.root, fixture.bootstrap_receipt
                )
                transaction["receipt_sha256"] = canonical_sha(
                    {
                        key: value
                        for key, value in transaction.items()
                        if key != "receipt_sha256"
                    }
                )
                write_json(fixture.transaction_receipt, transaction)
                public_inputs = target._load_qualification_inputs(
                    project_root=fixture.root,
                    candidate_index_path=fixture.candidate_index,
                    candidate_manifest_path=fixture.candidate_manifest,
                    candidate_receipt_path=fixture.candidate_receipt,
                    bootstrap_mapping_path=fixture.bootstrap_mapping,
                    bootstrap_receipt_path=fixture.bootstrap_receipt,
                    bootstrap_dir=fixture.bootstrap_dir,
                    transaction_receipt_path=fixture.transaction_receipt,
                )
                self.assertIsNotNone(public_inputs.transaction_receipt)

                receipt["model_parity_refresh_authority"]["workers"]["cpu"][
                    "image_id"
                ] = "sha256:" + "f" * 64
                receipt["receipt_sha256"] = canonical_sha(
                    {
                        key: value
                        for key, value in receipt.items()
                        if key != "receipt_sha256"
                    }
                )
                write_json(fixture.bootstrap_receipt, receipt)
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "refresh authority cross-binding",
                ):
                    target._load_qualification_inputs(
                        project_root=fixture.root,
                        candidate_index_path=fixture.candidate_index,
                        candidate_manifest_path=fixture.candidate_manifest,
                        candidate_receipt_path=fixture.candidate_receipt,
                        bootstrap_mapping_path=fixture.bootstrap_mapping,
                        bootstrap_receipt_path=fixture.bootstrap_receipt,
                        bootstrap_dir=fixture.bootstrap_dir,
                    )
            finally:
                fixture.close()

    def test_executes_32_cells_with_host_collector_and_nonauthorizing_commit_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            events: list[tuple[str, str]] = []
            requests: list[NativePublicationRequestV3] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                request = fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )
                requests.append(request)
                return request

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                events.append((request.run_id, "runtime"))
                self.assertFalse(
                    (request.output_dir / "hardware_resource_samples.csv").exists()
                )
                self.assertNotIn(
                    "hardware_resource_samples.csv", request.launcher_evidence_files
                )
                self.assertNotIn(
                    "checkpoint_publication_acceptance.json",
                    request.launcher_evidence_files,
                )
                self.assertNotIn(
                    target.ACCEPTANCE_FILENAME, request.launcher_evidence_files
                )
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def collector_factory(
                path: Path, *, run_id: str
            ) -> FakeCollector:
                return FakeCollector(path, run_id=run_id, events=events)

            def finalizer(**kwargs: object) -> dict[str, object]:
                run_id = str(kwargs["expected_run_id"])
                output = kwargs["output_dir"]
                self.assertIsInstance(output, Path)
                output = output  # type: ignore[assignment]
                events.append((run_id, "finalize"))
                self.assertTrue((output / "hardware_resource_samples.csv").is_file())
                self.assertFalse(
                    (output / "checkpoint_publication_acceptance.json").exists()
                )
                self.assertTrue(kwargs["hardware_collector_stopped"])
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                acceptance = acceptance_payload(cell, fixture)
                write_json(output / target.ACCEPTANCE_FILENAME, acceptance)
                return acceptance

            registry = {system: runtime for system in target.SYSTEMS}
            try:
                result = target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["completed_cells"], 32)
                self.assertEqual(len(requests), 32)
                for request in requests:
                    contract = request.runtime_inputs["dataset"][
                        target.RUNTIME_INPUT_KEY_BY_SYSTEM[request.system]
                    ]
                    self.assertIs(contract["defer_full_resource_acceptance"], True)
                    self.assertEqual(
                        [event for rid, event in events if rid == request.run_id],
                        [
                            "collector.start",
                            "runtime",
                            "collector.stop",
                            "collector.join",
                            "finalize",
                        ],
                    )
                checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
                self.assertEqual(checkpoint["status"], "completed")
                self.assertEqual(len(checkpoint["completed"]), 32)
                self.assertTrue(
                    all(
                        (fixture.pilot_root / entry["pilot_path"] / target.ACCEPTANCE_FILENAME).is_file()
                        for entry in checkpoint["completed"]
                    )
                )
            finally:
                fixture.close()

    def test_resume_skips_valid_commits_and_never_overwrites_a_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            calls: list[str] = []
            fail_after = 1

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                if len(calls) > fail_after:
                    raise RuntimeError("injected interruption")
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                output = kwargs["output_dir"]
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(output / target.ACCEPTANCE_FILENAME, value)  # type: ignore[operator]
                return value

            collector_factory = lambda path, run_id: FakeCollector(  # noqa: E731
                path, run_id=run_id, events=[]
            )
            registry = {system: runtime for system in target.SYSTEMS}
            try:
                with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                first_calls = list(calls)
                self.assertEqual(len(first_calls), 2)
                checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
                self.assertEqual(len(checkpoint["completed"]), 1)

                fail_after = 10_000
                target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(calls.count(first_calls[0]), 1)
                count_after_resume = len(calls)
                target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(len(calls), count_after_resume)

                collision = fixture.pilot_root / "deepstream/cpu/h264/independent_processes"
                frames = collision / "frames.csv"
                frames_before = frames.read_bytes()
                frames.write_text("tampered child evidence\n", encoding="utf-8")
                with self.assertRaises(target.QualificationPilotExecutorV2Error):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                self.assertEqual(frames.read_text(encoding="utf-8"), "tampered child evidence\n")
                frames.write_bytes(frames_before)
                acceptance = collision / target.ACCEPTANCE_FILENAME
                acceptance.write_text("tampered\n", encoding="utf-8")
                before = acceptance.read_bytes()
                with self.assertRaises(target.QualificationPilotExecutorV2Error):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                self.assertEqual(acceptance.read_bytes(), before)
            finally:
                fixture.close()

    def test_resume_rejects_final_without_anchor_and_orphan_writer_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            cells = target.qualification_pilot_cells_v2(deadline_ms=100, duration_s=180)
            adopted = cells[0]
            adopted_final = commit_pilot_output(fixture, adopted)
            try:
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "without an initial anchor checkpoint",
                ):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={
                            system: mock.Mock(name=f"runtime-{system}")
                            for system in target.SYSTEMS
                        },
                        request_factory=lambda **kwargs: fixture.request(
                            kwargs["cell"],
                            kwargs["output_dir"],
                            kwargs["evidence_names"],
                        ),
                    )
                self.assertFalse(fixture.checkpoint.exists())
                self.assertTrue(adopted_final.is_dir())
            finally:
                fixture.close()

    def test_mutate_restore_during_cell_poisoned_anchor_and_restart_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            original = fixture.candidate_index.read_bytes()
            calls = 0

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                nonlocal calls
                calls += 1
                fixture.candidate_index.write_bytes(b"mutated\n")
                fixture.candidate_index.write_bytes(original)
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            try:
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "changed after execution started",
                ):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={system: runtime for system in target.SYSTEMS},
                        request_factory=request_factory,
                        collector_factory=lambda path, run_id: FakeCollector(
                            path, run_id=run_id, events=[]
                        ),
                    )
                self.assertEqual(calls, 1)
                checkpoint = json.loads(fixture.checkpoint.read_bytes())
                self.assertEqual(checkpoint["schema_version"], 3)
                self.assertEqual(checkpoint["completed"], [])
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "checkpoint drifted",
                ):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={system: runtime for system in target.SYSTEMS},
                        request_factory=request_factory,
                        collector_factory=lambda path, run_id: FakeCollector(
                            path, run_id=run_id, events=[]
                        ),
                    )
                self.assertEqual(calls, 1)
            finally:
                fixture.close()

    def test_precommit_barrier_mutate_restore_never_publishes_or_adopts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            original = fixture.candidate_index.read_bytes()

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(kwargs["output_dir"] / target.ACCEPTANCE_FILENAME, value)  # type: ignore[operator]
                fixture.candidate_index.write_bytes(b"mutated-after-a\n")
                fixture.candidate_index.write_bytes(original)
                return value

            common = {
                **fixture.arguments(),
                "runtime_registry": {system: runtime for system in target.SYSTEMS},
                "request_factory": request_factory,
                "collector_factory": lambda path, run_id: FakeCollector(
                    path, run_id=run_id, events=[]
                ),
                "acceptance_finalizer": finalizer,
            }
            try:
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "changed after execution started",
                ):
                    target.execute_qualification_pilots_v2(**common)
                first = target.qualification_pilot_cells_v2()[0]
                final = fixture.pilot_root / first.system / first.resource / first.codec / first.topology_kind
                self.assertFalse(final.exists())
                self.assertFalse(os.path.lexists(final))
                self.assertEqual(json.loads(fixture.checkpoint.read_bytes())["completed"], [])
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "checkpoint drifted",
                ):
                    target.execute_qualification_pilots_v2(**common)
            finally:
                fixture.close()

    def test_late_project_import_fails_precommit_barrier_without_final_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            late_source = root / "scripts/qualification_late_escape.py"
            late_source.parent.mkdir(parents=True)
            late_source.write_text("MARKER = 'late-unpinned'\n", encoding="utf-8")
            fixture = InputFixture(root)
            module_name = "qualification_late_escape"

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                spec = importlib.util.spec_from_file_location(module_name, late_source)
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)  # type: ignore[union-attr]
                module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                sys.modules[module_name] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                self.assertEqual(module.MARKER, "late-unpinned")
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(
                    kwargs["output_dir"] / target.ACCEPTANCE_FILENAME,  # type: ignore[operator]
                    value,
                )
                return value

            first = target.qualification_pilot_cells_v2()[0]
            final = (
                fixture.pilot_root
                / first.system
                / first.resource
                / first.codec
                / first.topology_kind
            )
            try:
                with self.assertRaisesRegex(
                    target.QualificationPilotExecutorV2Error,
                    "loaded project module escaped execution code closure",
                ):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={system: runtime for system in target.SYSTEMS},
                        request_factory=request_factory,
                        collector_factory=lambda path, run_id: FakeCollector(
                            path, run_id=run_id, events=[]
                        ),
                        acceptance_finalizer=finalizer,
                    )
                self.assertFalse(final.exists())
                self.assertFalse(os.path.lexists(final))
                self.assertEqual(
                    json.loads(fixture.checkpoint.read_bytes())["completed"], []
                )
            finally:
                sys.modules.pop(module_name, None)
                fixture.close()

    def test_hard_crash_after_barrier_b_before_checkpoint_is_exactly_adoptable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            calls: list[str] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(kwargs["output_dir"] / target.ACCEPTANCE_FILENAME, value)  # type: ignore[operator]
                return value

            common = {
                **fixture.arguments(),
                "runtime_registry": {system: runtime for system in target.SYSTEMS},
                "request_factory": request_factory,
                "collector_factory": lambda path, run_id: FakeCollector(
                    path, run_id=run_id, events=[]
                ),
                "acceptance_finalizer": finalizer,
            }
            real_write = target._write_checkpoint

            def crash_after_b(path: Path, value: object, **kwargs: object) -> object:
                if value["completed"]:  # type: ignore[index]
                    raise SystemExit("hard crash after barrier B")
                return real_write(path, value, **kwargs)  # type: ignore[arg-type]

            try:
                with mock.patch.object(target, "_write_checkpoint", side_effect=crash_after_b):
                    with self.assertRaisesRegex(SystemExit, "hard crash after barrier B"):
                        target.execute_qualification_pilots_v2(**common)
                first = target.qualification_pilot_cells_v2()[0]
                self.assertEqual(json.loads(fixture.checkpoint.read_bytes())["completed"], [])
                first_call_count = calls.count(first.run_id)

                def stop_after_adoption(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                    calls.append(request.run_id)
                    raise RuntimeError("stop after adoption")

                with self.assertRaisesRegex(RuntimeError, "stop after adoption"):
                    target.execute_qualification_pilots_v2(
                        **{**common, "runtime_registry": {system: stop_after_adoption for system in target.SYSTEMS}}
                    )
                checkpoint = json.loads(fixture.checkpoint.read_bytes())
                self.assertEqual([entry["arm_id"] for entry in checkpoint["completed"]], [first.arm_id])
                self.assertEqual(calls.count(first.run_id), first_call_count)
            finally:
                fixture.close()

    def test_sigkill_after_final_rename_recovers_owned_attempt_without_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            calls: list[str] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(
                    kwargs["output_dir"] / target.ACCEPTANCE_FILENAME,  # type: ignore[operator]
                    value,
                )
                return value

            common = {
                **fixture.arguments(),
                "runtime_registry": {system: runtime for system in target.SYSTEMS},
                "request_factory": request_factory,
                "collector_factory": lambda path, run_id: FakeCollector(
                    path, run_id=run_id, events=[]
                ),
                "acceptance_finalizer": finalizer,
            }
            real_rename = target._rename_directory_noreplace

            def publish_then_sigkill(source: Path, destination: Path) -> None:
                real_rename(source, destination)
                raise SystemExit("simulated SIGKILL after final rename")

            try:
                with (
                    mock.patch.object(
                        target,
                        "_rename_directory_noreplace",
                        side_effect=publish_then_sigkill,
                    ),
                    mock.patch.object(target, "_safe_remove_attempt", return_value=None),
                    self.assertRaisesRegex(SystemExit, "simulated SIGKILL"),
                ):
                    target.execute_qualification_pilots_v2(**common)

                first = target.qualification_pilot_cells_v2()[0]
                first_call_count = calls.count(first.run_id)
                staging_root = (
                    fixture.pilot_root / ".qualification-pilot-staging-v2"
                )
                attempts = [
                    entry
                    for entry in staging_root.iterdir()
                    if entry.name != target._STAGING_OWNER_FILENAME
                ]
                self.assertEqual(len(attempts), 1)
                self.assertEqual(
                    {entry.name for entry in attempts[0].iterdir()},
                    {target._ATTEMPT_OWNER_FILENAME},
                )
                self.assertEqual(
                    json.loads(fixture.checkpoint.read_bytes())["completed"], []
                )

                def stop_after_adoption(
                    request: NativePublicationRequestV3,
                ) -> NativePublicationOutcomeV3:
                    calls.append(request.run_id)
                    raise RuntimeError("stop after orphan adoption")

                with self.assertRaisesRegex(RuntimeError, "stop after orphan adoption"):
                    target.execute_qualification_pilots_v2(
                        **{
                            **common,
                            "runtime_registry": {
                                system: stop_after_adoption
                                for system in target.SYSTEMS
                            },
                        }
                    )
                checkpoint = json.loads(fixture.checkpoint.read_bytes())
                self.assertEqual(
                    [entry["arm_id"] for entry in checkpoint["completed"]],
                    [first.arm_id],
                )
                self.assertEqual(calls.count(first.run_id), first_call_count)
                self.assertEqual(
                    {entry.name for entry in staging_root.iterdir()},
                    {target._STAGING_OWNER_FILENAME},
                )
            finally:
                fixture.close()

    def test_sigkill_during_postcommit_barrier_adopts_without_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            calls: list[str] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(
                    kwargs["output_dir"] / target.ACCEPTANCE_FILENAME,  # type: ignore[operator]
                    value,
                )
                return value

            common = {
                **fixture.arguments(),
                "runtime_registry": {system: runtime for system in target.SYSTEMS},
                "request_factory": request_factory,
                "collector_factory": lambda path, run_id: FakeCollector(
                    path, run_id=run_id, events=[]
                ),
                "acceptance_finalizer": finalizer,
            }
            first = target.qualification_pilot_cells_v2()[0]
            final = (
                fixture.pilot_root
                / first.system
                / first.resource
                / first.codec
                / first.topology_kind
            )
            real_barrier = target._assert_execution_barrier

            def barrier_then_sigkill(**kwargs: object) -> None:
                real_barrier(**kwargs)  # type: ignore[arg-type]
                if final.exists():
                    raise SystemExit("simulated SIGKILL during postcommit barrier")

            try:
                with (
                    mock.patch.object(
                        target,
                        "_assert_execution_barrier",
                        side_effect=barrier_then_sigkill,
                    ),
                    mock.patch.object(target, "_safe_remove_attempt", return_value=None),
                    self.assertRaisesRegex(SystemExit, "postcommit barrier"),
                ):
                    target.execute_qualification_pilots_v2(**common)

                first_call_count = calls.count(first.run_id)
                self.assertEqual(first_call_count, 1)
                self.assertTrue(final.is_dir())
                self.assertEqual(
                    json.loads(fixture.checkpoint.read_bytes())["completed"], []
                )

                def stop_after_adoption(
                    request: NativePublicationRequestV3,
                ) -> NativePublicationOutcomeV3:
                    calls.append(request.run_id)
                    raise RuntimeError("stop after postcommit adoption")

                with self.assertRaisesRegex(RuntimeError, "postcommit adoption"):
                    target.execute_qualification_pilots_v2(
                        **{
                            **common,
                            "runtime_registry": {
                                system: stop_after_adoption
                                for system in target.SYSTEMS
                            },
                        }
                    )
                checkpoint = json.loads(fixture.checkpoint.read_bytes())
                self.assertEqual(
                    [entry["arm_id"] for entry in checkpoint["completed"]],
                    [first.arm_id],
                )
                self.assertEqual(calls.count(first.run_id), first_call_count)
            finally:
                fixture.close()

    def test_orphan_staging_attempt_is_never_automatically_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp).resolve() / ".qualification-pilot-staging-v2"
            staging.mkdir()
            target._write_owner_marker(
                staging,
                filename=target._STAGING_OWNER_FILENAME,
                kind="vast_qualification_pilot_staging_owner_v2",
            )
            orphan = staging / "qualification-arm-v2-deepstream-cpu-h264-independent-processes.stale"
            orphan.mkdir()
            with self.assertRaisesRegex(
                target.QualificationPilotExecutorV2Error,
                "orphan qualification writer/container state",
            ):
                target._refuse_orphaned_staging_state(staging)
            self.assertTrue(orphan.is_dir())

    def test_cold_512_scan_rejects_mutate_restore_of_code_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell, fixture)
                write_json(kwargs["output_dir"] / target.ACCEPTANCE_FILENAME, value)  # type: ignore[operator]
                return value

            source = fixture.root / "scripts/publication_policy_qualification_pilot_executor_v2.py"
            original_source = source.read_bytes()
            original_read = target.PhysicalRootCustodyV1.read_descriptor
            mutated = False

            def mutate_during_cold(custody: object, value: object, **kwargs: object) -> object:
                nonlocal mutated
                if (
                    not mutated
                    and kwargs.get("label") == "cold checkpoint evidence[0]"
                ):
                    source.write_bytes(b"# cold transient mutation\n")
                    source.write_bytes(original_source)
                    mutated = True
                return original_read(custody, value, **kwargs)  # type: ignore[arg-type]

            try:
                with mock.patch.object(
                    target.PhysicalRootCustodyV1,
                    "read_descriptor",
                    new=mutate_during_cold,
                ):
                    with self.assertRaisesRegex(
                        target.QualificationPilotExecutorV2Error,
                        "cold qualification",
                    ):
                        target.execute_qualification_pilots_v2(
                            **fixture.arguments(),
                            runtime_registry={system: runtime for system in target.SYSTEMS},
                            request_factory=request_factory,
                            collector_factory=lambda path, run_id: FakeCollector(
                                path, run_id=run_id, events=[]
                            ),
                            acceptance_finalizer=finalizer,
                        )
                self.assertTrue(mutated)
                checkpoint = json.loads(fixture.checkpoint.read_bytes())
                self.assertEqual(len(checkpoint["completed"]), 32)
            finally:
                fixture.close()

    def test_child_parent_evidence_or_production_claim_is_rejected(self) -> None:
        for violation in (
            "hardware",
            "production_acceptance",
            "production_grant",
            "nonpending_candidate",
        ):
            with self.subTest(violation=violation), tempfile.TemporaryDirectory() as tmp:
                fixture = InputFixture(Path(tmp).resolve())

                def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                    request = fixture.request(
                        kwargs["cell"],  # type: ignore[arg-type]
                        kwargs["output_dir"],  # type: ignore[arg-type]
                        kwargs["evidence_names"],  # type: ignore[arg-type]
                    )
                    if violation == "production_grant":
                        runtime_inputs = dict(request.runtime_inputs)
                        runtime_inputs["backend_runtime_grant_sha256"] = "a" * 64
                        request = NativePublicationRequestV3(
                            **{**request.__dict__, "runtime_inputs": runtime_inputs}
                        )
                    return request

                def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                    write_request_child_evidence(request)
                    if violation == "nonpending_candidate":
                        candidate_path = (
                            request.output_dir
                            / "checkpoint_publication_candidate.json"
                        )
                        candidate = json.loads(
                            candidate_path.read_text(encoding="ascii")
                        )
                        candidate["status"] = "accepted_native_checkpoint_arm"
                        write_json(candidate_path, candidate)
                    if violation == "hardware":
                        (request.output_dir / "hardware_resource_samples.csv").write_text(
                            "forbidden\n", encoding="utf-8"
                        )
                    if violation == "production_acceptance":
                        (request.output_dir / "checkpoint_publication_acceptance.json").write_text(
                            "forbidden\n", encoding="utf-8"
                        )
                    return NativePublicationOutcomeV3(exit_code=0)

                try:
                    with self.assertRaises(target.QualificationPilotExecutorV2Error):
                        target.execute_qualification_pilots_v2(
                            **fixture.arguments(),
                            runtime_registry={system: runtime for system in target.SYSTEMS},
                            request_factory=request_factory,
                            collector_factory=lambda path, run_id: FakeCollector(
                                path, run_id=run_id, events=[]
                            ),
                            acceptance_finalizer=mock.Mock(
                                side_effect=AssertionError("must not finalize")
                            ),
                        )
                    self.assertFalse(
                        any(fixture.pilot_root.rglob(target.ACCEPTANCE_FILENAME))
                    )
                finally:
                    fixture.close()

    def test_finalizer_failure_retains_hardware_resource_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            cell = target.qualification_pilot_cells_v2()[0]
            payload = b"nvml-gap-evidence\n"

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def collector_factory(path: Path, *, run_id: str) -> FakeCollector:
                collector = FakeCollector(path, run_id=run_id, events=[])
                start = collector.start

                def write_payload() -> None:
                    start()
                    path.write_bytes(payload)

                collector.start = write_payload  # type: ignore[method-assign]
                return collector

            def finalizer(**kwargs: object) -> dict[str, object]:
                raise RuntimeError(
                    "full-resource final validation failed: "
                    "hardware_resource_samples.csv:1872: NVML sampling gap is not allowed"
                )

            try:
                with self.assertRaisesRegex(RuntimeError, "NVML sampling gap is not allowed"):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={system: runtime for system in target.SYSTEMS},
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                retained = (
                    fixture.pilot_root
                    / ".failed-cell-evidence-v1"
                    / cell.arm_id
                    / target.HARDWARE_EVIDENCE_FILENAME
                )
                self.assertEqual(retained.read_bytes(), payload)
                staging = fixture.pilot_root / ".qualification-pilot-staging-v2"
                leftovers = [
                    entry.name
                    for entry in staging.iterdir()
                    if entry.name != target._STAGING_OWNER_FILENAME
                ]
                self.assertEqual(leftovers, [])
                self.assertFalse(any(fixture.pilot_root.rglob(target.ACCEPTANCE_FILENAME)))
            finally:
                fixture.close()

    def test_openvino_probe_identity_failure_retains_observed_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            cell = target.qualification_pilot_cells_v2()[0]
            payload = (
                b'{"artifact_kind":"vast_openvino_checkpoint_device_probe",'
                b'"schema_version":1}\n'
            )

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                observed = Path(request.output_dir) / "openvino_device_probe.observed.json"
                observed.write_bytes(payload)
                raise RuntimeError("openvino_gva_device_probe_identity_changed")

            try:
                with self.assertRaisesRegex(
                    RuntimeError, "openvino_gva_device_probe_identity_changed"
                ):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry={system: runtime for system in target.SYSTEMS},
                        request_factory=request_factory,
                        collector_factory=lambda path, run_id: FakeCollector(
                            path, run_id=run_id, events=[]
                        ),
                        acceptance_finalizer=mock.Mock(
                            side_effect=AssertionError("must not finalize")
                        ),
                    )
                retained = (
                    fixture.pilot_root
                    / ".failed-cell-evidence-v1"
                    / cell.arm_id
                    / "openvino_device_probe.observed.json"
                )
                self.assertEqual(retained.read_bytes(), payload)
                staging = fixture.pilot_root / ".qualification-pilot-staging-v2"
                leftovers = [
                    entry.name
                    for entry in staging.iterdir()
                    if entry.name != target._STAGING_OWNER_FILENAME
                ]
                self.assertEqual(leftovers, [])
                self.assertFalse(any(fixture.pilot_root.rglob(target.ACCEPTANCE_FILENAME)))
            finally:
                fixture.close()

    def test_deadline_duration_and_defer_mode_are_not_user_configurable(self) -> None:
        with self.assertRaises(target.QualificationPilotExecutorV2Error):
            target.qualification_pilot_cells_v2(deadline_ms=99, duration_s=180)
        with self.assertRaises(target.QualificationPilotExecutorV2Error):
            target.qualification_pilot_cells_v2(deadline_ms=100, duration_s=179)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            target._parse_args(  # noqa: SLF001
                [
                    "--project-root", "/tmp/project",
                    "--candidate-index", "index.json",
                    "--candidate-manifest", "manifest.json",
                    "--candidate-receipt", "receipt.json",
                    "--bootstrap-mapping", "mapping.json",
                    "--bootstrap-receipt", "bootstrap-receipt.json",
                    "--bootstrap-dir", "bootstrap",
                    "--pilot-root", "pilots",
                    "--checkpoint", "checkpoint.json",
                    "--defer-full-resource-acceptance", "false",
                ]
            )
        argv = [
            "--project-root", "/tmp/project",
            "--candidate-index", "index.json",
            "--candidate-manifest", "manifest.json",
            "--candidate-receipt", "receipt.json",
            "--bootstrap-mapping", "mapping.json",
            "--bootstrap-receipt", "bootstrap-receipt.json",
            "--bootstrap-dir", "bootstrap",
            "--qualification-transaction-receipt", "transaction.json",
            "--runtime-input-materialization-receipt", "runtime-receipt.json",
            "--guardian-service-authority", "service-authority.json",
            "--preprocessing-contract", "preprocessing.json",
            "--preprocessing-contract-receipt", "preprocessing-receipt.json",
            "--execution-code-closure-receipt", "execution-code-closure.json",
            "--pilot-root", "pilots",
            "--checkpoint", "checkpoint.json",
        ]
        required_parameters = (
            "transaction_receipt_path",
            "runtime_input_materialization_receipt_path",
            "guardian_service_authority_path",
            "preprocessing_contract_path",
            "preprocessing_contract_receipt_path",
            "execution_code_closure_receipt_path",
        )
        signature = inspect.signature(target.execute_qualification_pilots_v2)
        for parameter in required_parameters:
            self.assertIs(
                signature.parameters[parameter].default,
                inspect.Parameter.empty,
            )
        for flag in (
            "--qualification-transaction-receipt",
            "--runtime-input-materialization-receipt",
            "--guardian-service-authority",
            "--preprocessing-contract",
            "--preprocessing-contract-receipt",
            "--execution-code-closure-receipt",
        ):
            position = argv.index(flag)
            missing = argv[:position] + argv[position + 2 :]
            with self.subTest(required_flag=flag), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    target._parse_args(missing)  # noqa: SLF001
        completed = {
            "schema_version": 3,
            "artifact_kind": target.CHECKPOINT_KIND,
            "status": "completed",
            "completed_cells": 32,
            "pilot_root": Path("/tmp/project/pilots"),
            "checkpoint_path": Path("/tmp/project/checkpoint.json"),
            "publication_ready": False,
            "authorization_eligible": False,
            "blockers": [
                "qualification_pilots_are_not_full_publication_arms"
            ],
        }
        with mock.patch.object(
            target, "execute_qualification_pilots_v2", return_value=completed
        ) as execute, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(target.main(argv), 0)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.kwargs["deadline_ms"], 100)
        self.assertEqual(execute.call_args.kwargs["duration_s"], 180)
        self.assertNotIn("defer_full_resource_acceptance", execute.call_args.kwargs)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                **completed,
                "pilot_root": "/tmp/project/pilots",
                "checkpoint_path": "/tmp/project/checkpoint.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
