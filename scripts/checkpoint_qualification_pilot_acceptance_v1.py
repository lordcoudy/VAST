#!/usr/bin/env python3
"""Commit a physical checkpoint run as a nonauthorizing qualification pilot.

This artifact deliberately cannot stand in for a production arm acceptance.
It exists only to break the bootstrap cycle for the 32 forced-resource policy
and FULL-RESOURCE qualification pilots.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

import checkpoint_model_parity_acceptance as model_parity_acceptance
from benchmark_contract import ContractError
from checkpoint_publication_runtime import (
    NATIVE_EXECUTION_BINDING_PROVENANCE,
    prepare_checkpoint_publication_acceptance,
)
from publication_acceptance_evidence import (
    FULL_RESOURCE_EVIDENCE_FILES,
    accepted_arm_evidence_files,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_checkpoint_qualification_pilot_acceptance_v1"
STATUS = "accepted_native_qualification_pilot"
SCOPE = "pre_run_policy_and_full_resource_qualification_only"
NONAUTHORITY_BLOCKER = "qualification_pilot_is_not_full_publication_arm"
ACCEPTANCE_FILENAME = "checkpoint_qualification_pilot_acceptance.json"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SYSTEMS = frozenset(
    {"deepstream", "savant", "openvino_gva", "gstreamer_custom"}
)
_RESOURCE_POLICIES = {"cpu": "cpu_only", "gpu": "gpu_only"}
_TOPOLOGY_SCENARIOS = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
_COORDINATE_FIELDS = {"system", "resource", "codec", "topology_kind"}
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_BOOTSTRAP_BINDING_FIELDS = {
    "candidate_manifest",
    "candidate_index",
    "candidate_receipt",
    "bootstrap_mapping",
    "bootstrap_calibration",
    "bootstrap_receipt",
    "model_parity_acceptance_binding_sha256",
}
_OPERATIONAL_BINDING_FIELDS = {
    "hardware_resource_collector",
    "qualification_input_transaction_receipt",
    "qualification_input_transaction_receipt_identity_sha256",
    "runtime_input_materialization_receipt",
    "runtime_input_materialization_receipt_identity_sha256",
    "runtime_input_bundle",
    "runtime_input_bundle_identity_sha256",
    "guardian_service_authority",
    "guardian_service_authority_identity_sha256",
    "guardian_preprocessing_contract_receipt",
    "guardian_preprocessing_contract_receipt_identity_sha256",
}
_ACCEPTANCE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "accepted_for_full_publication",
    "publication_ready",
    "authorization_eligible",
    "blockers",
    "run_id",
    "arm_id",
    "coordinate",
    "scenario",
    "policy",
    "deadline_ms",
    "execution_binding_provenance",
    "cohort_id",
    "measurement_schedule_fingerprint_sha256",
    "completed_frames_by_stream",
    "summary",
    "evidence_sha256",
    "full_resource_evidence_sha256",
    "full_resource_summary",
    "full_resource_finalization",
    "bootstrap_binding",
    "operational_binding",
    "sha256",
}
_PREPARED_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "run_id",
    "system",
    "scenario",
    "codec",
    "policy",
    "deadline_ms",
    "execution_binding_provenance",
    "topology_kind",
    "cohort_id",
    "measurement_schedule_fingerprint_sha256",
    "completed_frames_by_stream",
    "summary",
    "evidence_sha256",
    "full_resource_evidence_sha256",
    "full_resource_summary",
    "acceptance_finalization",
}
_CANDIDATE_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "policy_contract_sha256",
    "qualification_index",
    "candidate_manifest",
    "blockers",
    "sha256",
}
_BOOTSTRAP_MAPPING_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "policy_contract_sha256",
    "aggregation_rule",
    "minimum_samples_per_branch_resource",
    "candidate_manifest_sha256",
    "candidate_receipt_sha256",
    "model_parity_acceptance_binding_sha256",
    "calibration_evidence_sha256",
    "physical_response_evidence_sha256",
    "calibrations",
}
_MODEL_PARITY_REFRESH_FIELD = "model_parity_refresh_authority"
_BOOTSTRAP_CALIBRATION_FIELDS = {
    "schema_version",
    "artifact_kind",
    "system",
    "policy_contract_sha256",
    "costs",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "source_candidate_manifest_sha256",
    "source_model_parity_acceptance_binding_sha256",
    "source_physical_response_evidence_sha256",
}
_BOOTSTRAP_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "policy_contract_sha256",
    "candidate_manifest",
    "candidate_receipt",
    "candidate_receipt_identity_sha256",
    "qualification_index",
    "accepted_model_parity_manifest",
    "accepted_model_parity_assessment",
    "accepted_model_parity_receipt",
    "model_parity_acceptance_binding_sha256",
    "accepted_model_parity_evidence_sha256",
    "calibration_evidence",
    "calibration_evidence_sha256",
    "transaction_index",
    "physical_response_evidence",
    "physical_response_evidence_sha256",
    "mapping",
    "calibrations",
    "blockers",
    "receipt_sha256",
}
_INPUT_TRANSACTION_KIND = (
    "vast_publication_policy_qualification_input_transaction_v2"
)
_RUNTIME_MATERIALIZATION_KIND = (
    "vast_qualification_native_runtime_input_materialization_v2"
)
_RUNTIME_BUNDLE_KIND = "vast_qualification_native_runtime_input_bundle_v2"
_RUNTIME_EXPECTATION_FIELDS = {
    "execution_config_identity_sha256",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
    "preprocessing_contract_content_sha256",
}


class QualificationPilotAcceptanceV1Error(RuntimeError):
    """A qualification acceptance or one of its physical bindings is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationPilotAcceptanceV1Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationPilotAcceptanceV1Error(
            "qualification acceptance is not canonical JSON"
        ) from exc


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _stable_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) >= 8
        and value == value.strip()
        and value.lower() not in {"unknown", "unavailable", "placeholder"}
        and not any(character in value for character in "\r\n\x00")
    )


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"artifact stat failed: {path}: {exc}"
        ) from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _physical_root(project_root: Path | str) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as exc:
        raise QualificationPilotAcceptanceV1Error(
            "project_root is unavailable"
        ) from exc
    _require(root.is_dir() and not _is_link(root), "project_root is not physical")
    return root


def _relative_under_root(root: Path, value: Path | str, label: str) -> str:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"{label} must exist under project_root"
        ) from exc
    text = relative.as_posix()
    _require(
        bool(text)
        and text == Path(text).as_posix()
        and all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label} path is not normalized",
    )
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        _require(not _is_link(cursor), f"{label} path contains a link/reparse point")
    return text


def _stable_descriptor(
    root: Path, value: Path | str, label: str
) -> dict[str, Any]:
    relative = _relative_under_root(root, value, label)
    path = root / relative
    before = path.stat()
    _require(
        stat.S_ISREG(path.lstat().st_mode), f"{label} is not a regular file"
    )
    _require(int(before.st_nlink) == 1, f"{label} hardlink alias is prohibited")
    digest = _sha256_file(path)
    after = path.stat()
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        int(getattr(before, "st_ctime_ns", 0)),
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        int(getattr(after, "st_ctime_ns", 0)),
    )
    _require(before_identity == after_identity, f"{label} changed while hashing")
    _require(before.st_size > 0, f"{label} is empty")
    return {
        "path": relative,
        "size_bytes": int(before.st_size),
        "sha256": digest,
    }


def _descriptor_fields(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict
        and set(value) == _DESCRIPTOR_FIELDS
        and type(value.get("path")) is str
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] > 0
        and _valid_sha(value.get("sha256")),
        f"{label} descriptor drifted",
    )
    return dict(value)


def _read_canonical_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"invalid {label}: {exc}"
        ) from exc
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(
        path.read_bytes() == _canonical_bytes(value) + b"\n",
        f"{label} bytes are not canonical",
    )
    return value


def _verify_declared_descriptor(
    root: Path, declared: Any, label: str
) -> dict[str, Any]:
    expected = _descriptor_fields(declared, label)
    actual = _stable_descriptor(root, expected["path"], label)
    _require(actual == expected, f"{label} descriptor/hash drifted")
    return actual


def _validate_nonaccepted_identity(
    value: Mapping[str, Any], *, label: str
) -> None:
    _require(
        value.get("status") == "qualification_bootstrap_not_accepted"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("scope") == "forced_resource_qualification_pilots_only"
        and value.get("authority") == "nonaccepted_qualification_bootstrap_v2",
        f"{label} lost its nonauthorizing bootstrap identity",
    )


def _validate_bootstrap_refresh_authority(
    *,
    root: Path,
    mapping: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any] | None:
    mapping_has_refresh = _MODEL_PARITY_REFRESH_FIELD in mapping
    receipt_has_refresh = _MODEL_PARITY_REFRESH_FIELD in receipt
    _require(
        mapping_has_refresh == receipt_has_refresh,
        "bootstrap model-parity refresh authority coverage drifted",
    )
    if not mapping_has_refresh:
        return None
    try:
        from checkpoint_model_parity_acceptance_v4 import (
            validate_refresh_authority_v4,
        )

        refresh = validate_refresh_authority_v4(
            mapping[_MODEL_PARITY_REFRESH_FIELD]
        )
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"bootstrap model-parity v4 refresh authority failed: {exc}"
        ) from exc
    _require(
        refresh
        == mapping[_MODEL_PARITY_REFRESH_FIELD]
        == receipt[_MODEL_PARITY_REFRESH_FIELD],
        "bootstrap model-parity v4 refresh authority cross-binding drifted",
    )
    descriptors = [
        ("image identity patch", refresh["image_identity_patch"]),
        ("execution config", refresh["execution_config"]),
        ("binding-set index", refresh["binding_set"]["index"]),
        *(
            (f"{resource} runtime probe", refresh["runtime_probes"][resource])
            for resource in ("cpu", "gpu")
        ),
        *(
            (f"endpoint binding {coordinate}", item)
            for coordinate, item in sorted(
                refresh["binding_set"]["bindings"].items()
            )
        ),
    ]
    for label, item in descriptors:
        declared = {key: item[key] for key in _DESCRIPTOR_FIELDS}
        _require(
            _verify_declared_descriptor(
                root, declared, f"model-parity refresh {label}"
            )
            == declared,
            f"model-parity refresh {label} descriptor drifted",
        )
    return refresh


def _load_verified_model_parity_binding(
    *, root: Path, receipt_path: Path
) -> dict[str, Any]:
    receipt = _read_canonical_json(receipt_path, "accepted model-parity receipt")
    try:
        if (
            receipt.get("schema_version") == 4
            and receipt.get("artifact_kind")
            == "vast_checkpoint_model_parity_acceptance_receipt_v4"
        ):
            from checkpoint_model_parity_acceptance_v4 import (
                load_verified_model_parity_acceptance_v4,
            )

            return load_verified_model_parity_acceptance_v4(
                project_root=root, receipt_path=receipt_path
            )
        return model_parity_acceptance.load_verified_model_parity_acceptance(
            project_root=root, receipt_path=receipt_path
        )
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"model-parity binding revalidation failed: {exc}"
        ) from exc


def _bootstrap_material(
    *,
    root: Path,
    expected_system: str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    qualification_index_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_calibration_path: Path | str,
    bootstrap_receipt_path: Path | str,
) -> dict[str, Any]:
    paths = {
        "candidate_manifest": candidate_manifest_path,
        "candidate_index": qualification_index_path,
        "candidate_receipt": candidate_receipt_path,
        "bootstrap_mapping": bootstrap_mapping_path,
        "bootstrap_calibration": bootstrap_calibration_path,
        "bootstrap_receipt": bootstrap_receipt_path,
    }
    descriptors: dict[str, dict[str, Any]] = {}
    identities: set[tuple[int, int]] = set()
    for role, path_value in paths.items():
        descriptor = _stable_descriptor(root, path_value, role)
        info = (root / descriptor["path"]).stat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(identity not in identities, "bootstrap artifacts contain an alias")
        identities.add(identity)
        descriptors[role] = descriptor

    candidate = _read_canonical_json(
        root / descriptors["candidate_manifest"]["path"],
        "candidate capability manifest",
    )
    _require(
        candidate.get("schema_version") == 1
        and candidate.get("artifact_kind")
        == "vast_publication_policy_capability_manifest"
        and type(candidate.get("systems")) is dict
        and expected_system in candidate["systems"]
        and _valid_sha(candidate.get("policy_contract_sha256")),
        "candidate capability manifest identity drifted",
    )
    policy_sha = candidate["policy_contract_sha256"]

    index = _read_canonical_json(
        root / descriptors["candidate_index"]["path"],
        "candidate qualification index",
    )
    _require(
        set(index)
        == {
            "schema_version",
            "artifact_kind",
            "policy_contract_sha256",
            "dataset_manifest",
            "bindings",
            "pilots",
        }
        and index.get("schema_version") == 2
        and index.get("artifact_kind")
        == "vast_publication_policy_qualification_index"
        and index.get("policy_contract_sha256") == policy_sha
        and index.get("pilots") == [],
        "candidate qualification index is not the fragment-only v2 bootstrap",
    )

    candidate_receipt = _read_canonical_json(
        root / descriptors["candidate_receipt"]["path"],
        "candidate receipt",
    )
    _require(
        set(candidate_receipt) == _CANDIDATE_RECEIPT_FIELDS
        and candidate_receipt.get("schema_version") == 1
        and candidate_receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_candidate_receipt"
        and candidate_receipt.get("status")
        == "qualification_candidate_not_accepted"
        and candidate_receipt.get("accepted") is False
        and candidate_receipt.get("publication_ready") is False
        and candidate_receipt.get("scope")
        == "forced_resource_qualification_pilots_only"
        and candidate_receipt.get("policy_contract_sha256") == policy_sha,
        "candidate receipt identity drifted",
    )
    candidate_receipt_identity = candidate_receipt.get("sha256")
    _require(
        _valid_sha(candidate_receipt_identity)
        and candidate_receipt_identity
        == _canonical_sha(
            {
                key: value
                for key, value in candidate_receipt.items()
                if key != "sha256"
            }
        ),
        "candidate receipt self-hash drifted",
    )
    _require(
        _descriptor_fields(
            candidate_receipt.get("candidate_manifest"), "candidate manifest"
        )
        == descriptors["candidate_manifest"]
        and _descriptor_fields(
            candidate_receipt.get("qualification_index"), "candidate index"
        )
        == descriptors["candidate_index"]
        and type(candidate_receipt.get("blockers")) is list
        and "candidate_is_not_a_full_publication_authority"
        in candidate_receipt["blockers"],
        "candidate receipt cross-hash drifted",
    )

    mapping = _read_canonical_json(
        root / descriptors["bootstrap_mapping"]["path"],
        "bootstrap mapping",
    )
    _require(
        frozenset(mapping)
        in {
            frozenset(_BOOTSTRAP_MAPPING_FIELDS),
            frozenset(_BOOTSTRAP_MAPPING_FIELDS | {_MODEL_PARITY_REFRESH_FIELD}),
        }
        and mapping.get("schema_version") == 2
        and mapping.get("artifact_kind")
        == "vast_publication_policy_qualification_bootstrap_calibration_mapping",
        "bootstrap mapping schema drifted",
    )
    _validate_nonaccepted_identity(mapping, label="bootstrap mapping")
    _require(
        mapping.get("policy_contract_sha256") == policy_sha
        and mapping.get("candidate_manifest_sha256")
        == descriptors["candidate_manifest"]["sha256"]
        and mapping.get("candidate_receipt_sha256")
        == descriptors["candidate_receipt"]["sha256"]
        and type(mapping.get("calibrations")) is dict
        and expected_system in mapping["calibrations"],
        "bootstrap mapping candidate cross-hash drifted",
    )

    calibration = _read_canonical_json(
        root / descriptors["bootstrap_calibration"]["path"],
        "bootstrap calibration",
    )
    _require(
        set(calibration) == _BOOTSTRAP_CALIBRATION_FIELDS
        and calibration.get("schema_version") == 1
        and calibration.get("artifact_kind")
        == "vast_publication_policy_calibration"
        and calibration.get("system") == expected_system
        and calibration.get("policy_contract_sha256") == policy_sha
        and type(calibration.get("costs")) is dict,
        "bootstrap calibration identity drifted",
    )
    _validate_nonaccepted_identity(calibration, label="bootstrap calibration")
    _require(
        mapping["calibrations"][expected_system] == calibration
        and calibration.get("source_candidate_manifest_sha256")
        == descriptors["candidate_manifest"]["sha256"],
        "bootstrap mapping/calibration cross-hash drifted",
    )

    receipt = _read_canonical_json(
        root / descriptors["bootstrap_receipt"]["path"],
        "bootstrap receipt",
    )
    _require(
        frozenset(receipt)
        in {
            frozenset(_BOOTSTRAP_RECEIPT_FIELDS),
            frozenset(_BOOTSTRAP_RECEIPT_FIELDS | {_MODEL_PARITY_REFRESH_FIELD}),
        }
        and receipt.get("schema_version") == 2
        and receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_bootstrap_receipt",
        "bootstrap receipt schema drifted",
    )
    _validate_nonaccepted_identity(receipt, label="bootstrap receipt")
    _require(
        receipt.get("policy_contract_sha256") == policy_sha
        and receipt.get("candidate_receipt_identity_sha256")
        == candidate_receipt_identity
        and _descriptor_fields(
            receipt.get("candidate_manifest"), "receipt candidate manifest"
        )
        == descriptors["candidate_manifest"]
        and _descriptor_fields(
            receipt.get("candidate_receipt"), "receipt candidate receipt"
        )
        == descriptors["candidate_receipt"]
        and _descriptor_fields(
            receipt.get("qualification_index"), "receipt candidate index"
        )
        == descriptors["candidate_index"]
        and _descriptor_fields(receipt.get("mapping"), "receipt mapping")
        == descriptors["bootstrap_mapping"],
        "bootstrap receipt candidate/mapping cross-hash drifted",
    )
    receipt_calibrations = receipt.get("calibrations")
    _require(
        type(receipt_calibrations) is dict
        and expected_system in receipt_calibrations
        and _descriptor_fields(
            receipt_calibrations[expected_system], "receipt calibration"
        )
        == descriptors["bootstrap_calibration"],
        "bootstrap receipt calibration cross-hash drifted",
    )
    _require(
        type(receipt.get("calibration_evidence")) is list
        and receipt.get("calibration_evidence_sha256")
        == _canonical_sha(receipt["calibration_evidence"])
        and type(receipt.get("physical_response_evidence")) is list
        and receipt.get("physical_response_evidence_sha256")
        == _canonical_sha(receipt["physical_response_evidence"])
        and _valid_sha(receipt.get("receipt_sha256"))
        and receipt["receipt_sha256"]
        == _canonical_sha(
            {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
        ),
        "bootstrap receipt evidence/self-hash drifted",
    )
    refresh = _validate_bootstrap_refresh_authority(
        root=root, mapping=mapping, receipt=receipt
    )

    accepted_receipt = _verify_declared_descriptor(
        root,
        receipt.get("accepted_model_parity_receipt"),
        "accepted model-parity receipt",
    )
    _verify_declared_descriptor(
        root,
        receipt.get("accepted_model_parity_manifest"),
        "accepted model-parity manifest",
    )
    _verify_declared_descriptor(
        root,
        receipt.get("accepted_model_parity_assessment"),
        "accepted model-parity assessment",
    )
    parity_binding = _load_verified_model_parity_binding(
        root=root, receipt_path=root / accepted_receipt["path"]
    )
    parity_coordinate = (
        parity_binding.get("schema_version"),
        parity_binding.get("artifact_kind"),
    ) if type(parity_binding) is dict else None
    _require(
        type(parity_binding) is dict
        and parity_coordinate
        in {
            (2, "vast_verified_model_parity_acceptance_binding"),
            (4, "vast_verified_model_parity_acceptance_binding_v4"),
        }
        and (refresh is None) == (parity_coordinate[0] == 2)
        and _valid_sha(parity_binding.get("binding_sha256"))
        and parity_binding["binding_sha256"]
        == _canonical_sha(
            {
                key: value
                for key, value in parity_binding.items()
                if key != "binding_sha256"
            }
        ),
        "model-parity binding identity/self-hash drifted",
    )
    parity_sha = parity_binding["binding_sha256"]
    _require(
        receipt.get("model_parity_acceptance_binding_sha256") == parity_sha
        and mapping.get("model_parity_acceptance_binding_sha256") == parity_sha
        and (
            refresh is None
            or parity_binding.get("refresh_authority") == refresh
        )
        and calibration.get("source_model_parity_acceptance_binding_sha256")
        == parity_sha
        and receipt.get("accepted_model_parity_evidence_sha256")
        == parity_binding.get("evidence_sha256")
        and receipt.get("transaction_index")
        == parity_binding.get("transaction_index")
        and _descriptor_fields(
            receipt.get("accepted_model_parity_receipt"),
            "accepted model-parity receipt",
        )
        == _descriptor_fields(
            parity_binding.get("receipt"), "parity binding receipt"
        )
        and _descriptor_fields(
            receipt.get("accepted_model_parity_manifest"),
            "accepted model-parity manifest",
        )
        == _descriptor_fields(
            parity_binding.get("accepted_manifest"),
            "parity binding manifest",
        )
        and _descriptor_fields(
            receipt.get("accepted_model_parity_assessment"),
            "accepted model-parity assessment",
        )
        == _descriptor_fields(
            parity_binding.get("accepted_assessment"),
            "parity binding assessment",
        ),
        "bootstrap/model-parity v2 cross-hash drifted",
    )
    physical_sha = receipt["physical_response_evidence_sha256"]
    _require(
        mapping.get("physical_response_evidence_sha256") == physical_sha
        and calibration.get("source_physical_response_evidence_sha256")
        == physical_sha
        and mapping.get("calibration_evidence_sha256")
        == receipt.get("calibration_evidence_sha256"),
        "bootstrap physical/calibration evidence cross-hash drifted",
    )
    return {
        **descriptors,
        "model_parity_acceptance_binding_sha256": parity_sha,
    }


def _validate_guardian_service_authority(
    value: Mapping[str, Any],
    *,
    require_live: bool,
    expected_preprocessing_contract_authority: Mapping[str, Any],
    expected_runtime_expectations: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        from checkpoint_gstreamer_analytics_sidecar import (
            assert_publication_sidecar_service_authority_identity_v1,
            assert_publication_sidecar_service_authority_v1,
            validate_publication_sidecar_service_authority_v1,
        )

        checked = validate_publication_sidecar_service_authority_v1(value)
        assertion = (
            assert_publication_sidecar_service_authority_v1
            if require_live
            else assert_publication_sidecar_service_authority_identity_v1
        )
        checked = assertion(
            value,
            expected_front_socket=checked["front_socket"]["path"],
            expected_execution_config_identity_sha256=expected_runtime_expectations[
                "execution_config_identity_sha256"
            ],
            expected_binding_set_identity_sha256=expected_runtime_expectations[
                "binding_set_identity_sha256"
            ],
            expected_worker_image_ids=expected_runtime_expectations[
                "worker_image_ids"
            ],
            expected_preprocessing_contract_authority=(
                expected_preprocessing_contract_authority
            ),
            expected_service_identity_sha256=checked[
                "service_identity_sha256"
            ],
            expected_policy_contract_sha256=(
                expected_preprocessing_contract_authority[
                    "policy_contract_sha256"
                ]
            ),
        )
        return checked
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"guardian service authority validation failed: {exc}"
        ) from exc


def _load_guardian_preprocessing(**kwargs: Any) -> dict[str, Any]:
    try:
        from publication_guardian_preprocessing_contract_v1 import (
            load_guardian_preprocessing_contract_v1,
        )

        return load_guardian_preprocessing_contract_v1(**kwargs)
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"guardian preprocessing receipt validation failed: {exc}"
        ) from exc


def _runtime_expectations_from_preprocessing_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        from publication_guardian_runtime_expectations_v1 import (
            runtime_expectations_from_preprocessing_receipt_v1,
        )

        return runtime_expectations_from_preprocessing_receipt_v1(receipt)
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"guardian runtime expectations validation failed: {exc}"
        ) from exc


def _operational_material(
    *,
    root: Path,
    expected_system: str,
    expected_resource: str,
    expected_codec: str,
    expected_topology_kind: str,
    expected_run_id: str,
    expected_arm_id: str,
    candidate_manifest_path: Path | str,
    qualification_transaction_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    runtime_input_bundle_path: Path | str,
    guardian_service_authority_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_contract_receipt_path: Path | str,
    require_live_service: bool,
) -> dict[str, Any]:
    paths = {
        "qualification_input_transaction_receipt": (
            qualification_transaction_receipt_path
        ),
        "runtime_input_materialization_receipt": (
            runtime_input_materialization_receipt_path
        ),
        "runtime_input_bundle": runtime_input_bundle_path,
        "guardian_service_authority": guardian_service_authority_path,
        "guardian_preprocessing_contract": preprocessing_contract_path,
        "guardian_preprocessing_contract_receipt": (
            preprocessing_contract_receipt_path
        ),
    }
    descriptors: dict[str, dict[str, Any]] = {}
    identities: set[tuple[int, int]] = set()
    for role, path_value in paths.items():
        descriptor = _stable_descriptor(root, path_value, role)
        info = (root / descriptor["path"]).stat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(
            identity not in identities,
            "qualification operational artifacts contain an alias",
        )
        identities.add(identity)
        descriptors[role] = descriptor

    transaction = _read_canonical_json(
        root / descriptors["qualification_input_transaction_receipt"]["path"],
        "qualification input transaction receipt",
    )
    transaction_identity = transaction.get("receipt_sha256")
    _require(
        transaction.get("schema_version") == 2
        and transaction.get("artifact_kind") == _INPUT_TRANSACTION_KIND
        and transaction.get("status")
        == "qualification_inputs_materialized_nonaccepted"
        and transaction.get("accepted") is False
        and transaction.get("publication_ready") is False
        and transaction.get("authorization_eligible") is False
        and _valid_sha(transaction_identity)
        and transaction_identity
        == _canonical_sha(
            {
                key: value
                for key, value in transaction.items()
                if key != "receipt_sha256"
            }
        ),
        "qualification input transaction operational identity drifted",
    )
    hardware_resource_collector = _descriptor_fields(
        transaction.get("hardware_resource_collector"),
        "qualification hardware resource collector",
    )
    _require(
        hardware_resource_collector["path"] == "scripts/collect_metrics.py"
        and _stable_descriptor(
            root,
            hardware_resource_collector["path"],
            "qualification hardware resource collector",
        )
        == hardware_resource_collector,
        "qualification hardware resource collector binding drifted",
    )
    materialization = _read_canonical_json(
        root / descriptors["runtime_input_materialization_receipt"]["path"],
        "runtime-input materialization receipt",
    )
    materialization_identity = materialization.get("receipt_sha256")
    runtime_inputs = materialization.get("inputs")
    bundle_rows = materialization.get("bundles")
    _require(
        materialization.get("schema_version") == 2
        and materialization.get("artifact_kind")
        == _RUNTIME_MATERIALIZATION_KIND
        and materialization.get("status")
        == "materialized_for_native_qualification_only"
        and materialization.get("accepted") is False
        and materialization.get("publication_ready") is False
        and materialization.get("authorization_eligible") is False
        and type(runtime_inputs) is dict
        and runtime_inputs.get(
            "qualification_input_transaction_receipt_sha256"
        )
        == descriptors["qualification_input_transaction_receipt"]["sha256"]
        and runtime_inputs.get("hardware_resource_collector")
        == hardware_resource_collector
        and type(bundle_rows) is list
        and _valid_sha(materialization_identity)
        and materialization_identity
        == _canonical_sha(
            {
                key: value
                for key, value in materialization.items()
                if key != "receipt_sha256"
            }
        ),
        "runtime-input materialization operational identity drifted",
    )
    bundle = _read_canonical_json(
        root / descriptors["runtime_input_bundle"]["path"],
        "cell runtime-input bundle",
    )
    bundle_identity = bundle.get("bundle_sha256")
    _require(
        bundle.get("schema_version") == 2
        and bundle.get("artifact_kind") == _RUNTIME_BUNDLE_KIND
        and bundle.get("status") == "materialized_for_native_qualification_only"
        and bundle.get("accepted") is False
        and bundle.get("publication_ready") is False
        and bundle.get("authorization_eligible") is False
        and bundle.get("system") == expected_system
        and bundle.get("resource") == expected_resource
        and bundle.get("codec") == expected_codec
        and bundle.get("topology_kind") == expected_topology_kind
        and bundle.get("run_id") == expected_run_id
        and bundle.get("arm_id") == expected_arm_id
        and bundle.get("hardware_resource_collector")
        == hardware_resource_collector
        and _valid_sha(bundle_identity)
        and bundle_identity
        == _canonical_sha(
            {
                key: value
                for key, value in bundle.items()
                if key != "bundle_sha256"
            }
        ),
        "cell runtime-input bundle operational identity drifted",
    )
    expected_bundle_record = {
        "arm_id": expected_arm_id,
        "run_id": expected_run_id,
        "path": Path(
            descriptors["runtime_input_bundle"]["path"]
        ).relative_to(
            Path(
                descriptors["runtime_input_materialization_receipt"]["path"]
            ).parent
        ).as_posix(),
        "size_bytes": descriptors["runtime_input_bundle"]["size_bytes"],
        "sha256": descriptors["runtime_input_bundle"]["sha256"],
        "bundle_sha256": bundle_identity,
    }
    _require(
        bundle_rows.count(expected_bundle_record) == 1,
        "cell runtime-input bundle is absent from materialization receipt",
    )
    service_value = _read_canonical_json(
        root / descriptors["guardian_service_authority"]["path"],
        "guardian service authority",
    )
    live_sockets = materialization.get("live_sockets")
    preprocessing = _load_guardian_preprocessing(
        project_root=root,
        preprocessing_contract_path=(
            root / descriptors["guardian_preprocessing_contract"]["path"]
        ),
        materialization_receipt_path=(
            root
            / descriptors["guardian_preprocessing_contract_receipt"]["path"]
        ),
        candidate_manifest_path=candidate_manifest_path,
    )
    preprocessing_receipt = (
        preprocessing.get("receipt") if type(preprocessing) is dict else None
    )
    preprocessing_authority = (
        preprocessing.get("authority") if type(preprocessing) is dict else None
    )
    _require(
        type(preprocessing) is dict
        and set(preprocessing)
        == {"preprocessing_contract", "receipt", "authority"}
        and type(preprocessing_receipt) is dict
        and type(preprocessing_authority) is dict
        and preprocessing_receipt
        == _read_canonical_json(
            root
            / descriptors["guardian_preprocessing_contract_receipt"]["path"],
            "guardian preprocessing materialization receipt",
        )
        and preprocessing_authority.get(
            "materialization_receipt_file_sha256"
        )
        == descriptors["guardian_preprocessing_contract_receipt"]["sha256"]
        and preprocessing_authority.get(
            "qualification_transaction_receipt_sha256"
        )
        == transaction_identity
        and _valid_sha(
            preprocessing_authority.get(
                "materialization_receipt_identity_sha256"
            )
        ),
        "guardian preprocessing operational binding drifted",
    )
    runtime_expectations = _runtime_expectations_from_preprocessing_receipt(
        preprocessing_receipt
    )
    worker_image_ids = (
        runtime_expectations.get("worker_image_ids")
        if type(runtime_expectations) is dict
        else None
    )
    _require(
        type(runtime_expectations) is dict
        and set(runtime_expectations) == _RUNTIME_EXPECTATION_FIELDS
        and all(
            _valid_sha(runtime_expectations.get(field))
            for field in (
                "execution_config_identity_sha256",
                "binding_set_identity_sha256",
                "bindings_identity_sha256",
                "policy_contract_sha256",
                "preprocessing_contract_content_sha256",
            )
        )
        and type(worker_image_ids) is dict
        and set(worker_image_ids) == set(_RESOURCE_POLICIES)
        and all(
            type(worker_image_ids.get(resource)) is str
            and _IMAGE_ID_RE.fullmatch(worker_image_ids[resource]) is not None
            for resource in _RESOURCE_POLICIES
        )
        and runtime_expectations["policy_contract_sha256"]
        == preprocessing_authority.get("policy_contract_sha256")
        and runtime_expectations["preprocessing_contract_content_sha256"]
        == preprocessing_authority.get(
            "preprocessing_contract_content_sha256"
        ),
        "guardian runtime expectations/preprocessing authority binding drifted",
    )
    service = _validate_guardian_service_authority(
        service_value,
        require_live=require_live_service,
        expected_preprocessing_contract_authority=preprocessing_authority,
        expected_runtime_expectations=runtime_expectations,
    )
    _require(
        service == service_value
        and _valid_sha(service.get("service_authority_sha256"))
        and service.get("preprocessing_contract_authority")
        == preprocessing_authority
        and service.get("execution_config_identity_sha256")
        == runtime_expectations["execution_config_identity_sha256"]
        and service.get("binding_set_identity_sha256")
        == runtime_expectations["binding_set_identity_sha256"]
        and service.get("worker_image_ids") == worker_image_ids
        and type(live_sockets) is dict
        and service.get("front_socket")
        == live_sockets.get("analytics_execution"),
        "guardian service/runtime expectations/socket binding drifted",
    )
    return {
        "hardware_resource_collector": hardware_resource_collector,
        "qualification_input_transaction_receipt": descriptors[
            "qualification_input_transaction_receipt"
        ],
        "qualification_input_transaction_receipt_identity_sha256": (
            transaction_identity
        ),
        "runtime_input_materialization_receipt": descriptors[
            "runtime_input_materialization_receipt"
        ],
        "runtime_input_materialization_receipt_identity_sha256": (
            materialization_identity
        ),
        "runtime_input_bundle": descriptors["runtime_input_bundle"],
        "runtime_input_bundle_identity_sha256": bundle_identity,
        "guardian_service_authority": descriptors[
            "guardian_service_authority"
        ],
        "guardian_service_authority_identity_sha256": service[
            "service_authority_sha256"
        ],
        "guardian_preprocessing_contract_receipt": descriptors[
            "guardian_preprocessing_contract_receipt"
        ],
        "guardian_preprocessing_contract_receipt_identity_sha256": (
            preprocessing_authority[
                "materialization_receipt_identity_sha256"
            ]
        ),
    }


def _validate_coordinate(
    value: Any,
    *,
    expected_system: str | None,
    expected_resource: str | None,
    expected_codec: str | None,
    expected_topology_kind: str | None,
) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == _COORDINATE_FIELDS,
        "qualification coordinate fields drifted",
    )
    coordinate = {key: str(value[key]) for key in _COORDINATE_FIELDS}
    _require(
        coordinate["system"] in _SYSTEMS
        and coordinate["resource"] in _RESOURCE_POLICIES
        and coordinate["codec"] in {"h264", "h265"}
        and coordinate["topology_kind"] in _TOPOLOGY_SCENARIOS,
        "qualification coordinate is unsupported",
    )
    expected = {
        "system": expected_system,
        "resource": expected_resource,
        "codec": expected_codec,
        "topology_kind": expected_topology_kind,
    }
    for field, expected_value in expected.items():
        if expected_value is not None:
            _require(
                coordinate[field] == expected_value,
                f"qualification coordinate identity drift: {field}",
            )
    return coordinate


def _validate_full_resource_summary(value: Any) -> dict[str, Any]:
    _require(type(value) is dict, "full-resource summary is missing")
    required = {
        "resource_contract_version": 2,
        "evidence_accepted": True,
        "publication_bundle_bound": True,
        "full_resource_coverage_complete": True,
        "nvdec_counter_scope": "device_sample",
        "fanout_counter_scope": "per_trace_resource_work",
    }
    _require(
        all(value.get(field) == expected for field, expected in required.items()),
        "full-resource summary is not accepted",
    )
    for field in (
        "nvdec_busy_equivalent_ns",
        "fanout_thread_cpu_time_ns",
        "fanout_work_units",
    ):
        number = value.get(field)
        _require(
            type(number) is int and number >= 0,
            f"full-resource summary {field} is invalid",
        )
    return dict(value)


def _validate_acceptance_value(
    *,
    root: Path,
    acceptance_path: Path,
    acceptance: dict[str, Any],
    expected_system: str | None,
    expected_resource: str | None,
    expected_codec: str | None,
    expected_topology_kind: str | None,
    expected_run_id: str | None,
    expected_arm_id: str | None,
) -> dict[str, Any]:
    _require(set(acceptance) == _ACCEPTANCE_FIELDS, "acceptance fields drifted")
    _require(
        acceptance.get("schema_version") == SCHEMA_VERSION
        and acceptance.get("artifact_kind") == ARTIFACT_KIND
        and acceptance.get("status") == STATUS
        and acceptance.get("scope") == SCOPE,
        "qualification acceptance identity drifted",
    )
    _require(
        acceptance.get("accepted_for_full_publication") is False
        and acceptance.get("publication_ready") is False
        and acceptance.get("authorization_eligible") is False
        and acceptance.get("blockers") == [NONAUTHORITY_BLOCKER],
        "qualification acceptance gained publication authority",
    )
    run_id = acceptance.get("run_id")
    arm_id = acceptance.get("arm_id")
    _require(_stable_id(run_id), "qualification run_id is invalid")
    _require(_stable_id(arm_id), "qualification arm_id is invalid")
    if expected_run_id is not None:
        _require(run_id == expected_run_id, "qualification run_id drifted")
    if expected_arm_id is not None:
        _require(arm_id == expected_arm_id, "qualification arm_id drifted")
    coordinate = _validate_coordinate(
        acceptance.get("coordinate"),
        expected_system=expected_system,
        expected_resource=expected_resource,
        expected_codec=expected_codec,
        expected_topology_kind=expected_topology_kind,
    )
    _require(
        acceptance.get("policy") == _RESOURCE_POLICIES[coordinate["resource"]]
        and acceptance.get("scenario")
        == _TOPOLOGY_SCENARIOS[coordinate["topology_kind"]]
        and acceptance.get("execution_binding_provenance")
        == NATIVE_EXECUTION_BINDING_PROVENANCE,
        "qualification scenario/policy/execution identity drifted",
    )
    deadline = acceptance.get("deadline_ms")
    _require(
        not isinstance(deadline, bool)
        and isinstance(deadline, (int, float))
        and math.isfinite(float(deadline))
        and float(deadline) > 0.0,
        "qualification deadline is invalid",
    )
    _require(
        _stable_id(acceptance.get("cohort_id"))
        and _valid_sha(acceptance.get("measurement_schedule_fingerprint_sha256"))
        and type(acceptance.get("completed_frames_by_stream")) is dict
        and bool(acceptance["completed_frames_by_stream"])
        and all(
            type(stream_id) is str
            and stream_id.isdigit()
            and type(count) is int
            and count > 0
            for stream_id, count in acceptance["completed_frames_by_stream"].items()
        )
        and type(acceptance.get("summary")) is dict,
        "qualification cohort/schedule/summary identity drifted",
    )

    expected_evidence = set(
        accepted_arm_evidence_files(acceptance["policy"], full_resource=True)
    )
    evidence = acceptance.get("evidence_sha256")
    _require(
        len(expected_evidence) == 14
        and type(evidence) is dict
        and len(evidence) == 14
        and set(evidence) == expected_evidence,
        "qualification acceptance requires exact 14 evidence hashes",
    )
    arm_root = acceptance_path.parent
    for filename, expected_sha in evidence.items():
        _require(
            type(filename) is str
            and Path(filename).name == filename
            and _valid_sha(expected_sha),
            "qualification evidence identity is unsafe",
        )
        path = arm_root / filename
        descriptor = _stable_descriptor(root, path, f"qualification evidence {filename}")
        _require(
            descriptor["sha256"] == expected_sha,
            f"qualification evidence hash drift: {filename}",
        )
    expected_full = {
        filename: evidence[filename]
        for filename in FULL_RESOURCE_EVIDENCE_FILES
    }
    _require(
        acceptance.get("full_resource_evidence_sha256") == expected_full,
        "qualification full-resource evidence hashes drifted",
    )
    _validate_full_resource_summary(acceptance.get("full_resource_summary"))
    _require(
        acceptance.get("full_resource_finalization")
        == {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
            "prepared_by": "prepare_checkpoint_publication_acceptance",
        },
        "qualification full-resource finalization drifted",
    )
    binding = acceptance.get("bootstrap_binding")
    _require(
        type(binding) is dict and set(binding) == _BOOTSTRAP_BINDING_FIELDS,
        "qualification bootstrap binding fields drifted",
    )
    material = _bootstrap_material(
        root=root,
        expected_system=coordinate["system"],
        candidate_manifest_path=_descriptor_fields(
            binding["candidate_manifest"], "bound candidate manifest"
        )["path"],
        candidate_receipt_path=_descriptor_fields(
            binding["candidate_receipt"], "bound candidate receipt"
        )["path"],
        qualification_index_path=_descriptor_fields(
            binding["candidate_index"], "bound candidate index"
        )["path"],
        bootstrap_mapping_path=_descriptor_fields(
            binding["bootstrap_mapping"], "bound bootstrap mapping"
        )["path"],
        bootstrap_calibration_path=_descriptor_fields(
            binding["bootstrap_calibration"], "bound bootstrap calibration"
        )["path"],
        bootstrap_receipt_path=_descriptor_fields(
            binding["bootstrap_receipt"], "bound bootstrap receipt"
        )["path"],
    )
    _require(material == binding, "qualification bootstrap cross-binding drifted")
    operational = acceptance.get("operational_binding")
    _require(
        type(operational) is dict
        and set(operational) == _OPERATIONAL_BINDING_FIELDS,
        "qualification operational binding fields drifted",
    )
    bound_preprocessing_receipt = _read_canonical_json(
        root
        / _descriptor_fields(
            operational["guardian_preprocessing_contract_receipt"],
            "bound guardian preprocessing receipt",
        )["path"],
        "bound guardian preprocessing receipt",
    )
    bound_preprocessing_contract = _descriptor_fields(
        bound_preprocessing_receipt.get("preprocessing_contract"),
        "bound guardian preprocessing contract",
    )
    operational_material = _operational_material(
        root=root,
        expected_system=coordinate["system"],
        expected_resource=coordinate["resource"],
        expected_codec=coordinate["codec"],
        expected_topology_kind=coordinate["topology_kind"],
        expected_run_id=run_id,
        expected_arm_id=arm_id,
        candidate_manifest_path=binding["candidate_manifest"]["path"],
        qualification_transaction_receipt_path=_descriptor_fields(
            operational["qualification_input_transaction_receipt"],
            "bound qualification input transaction receipt",
        )["path"],
        runtime_input_materialization_receipt_path=_descriptor_fields(
            operational["runtime_input_materialization_receipt"],
            "bound runtime-input materialization receipt",
        )["path"],
        runtime_input_bundle_path=_descriptor_fields(
            operational["runtime_input_bundle"],
            "bound cell runtime-input bundle",
        )["path"],
        guardian_service_authority_path=_descriptor_fields(
            operational["guardian_service_authority"],
            "bound guardian service authority",
        )["path"],
        preprocessing_contract_path=bound_preprocessing_contract["path"],
        preprocessing_contract_receipt_path=_descriptor_fields(
            operational["guardian_preprocessing_contract_receipt"],
            "bound guardian preprocessing receipt",
        )["path"],
        require_live_service=False,
    )
    _require(
        operational_material == operational,
        "qualification operational cross-binding drifted",
    )
    claimed_sha = acceptance.get("sha256")
    _require(
        _valid_sha(claimed_sha)
        and claimed_sha
        == _canonical_sha(
            {
                key: value
                for key, value in acceptance.items()
                if key != "sha256"
            }
        ),
        "qualification acceptance self-hash drifted",
    )
    _require(
        not (arm_root / "checkpoint_publication_acceptance.json").exists(),
        "qualification pilot cannot also claim production arm acceptance",
    )
    return json.loads(_canonical_bytes(acceptance))


def validate_checkpoint_qualification_pilot_acceptance_v1(
    *,
    project_root: Path | str,
    acceptance_path: Path | str,
    expected_system: str | None = None,
    expected_resource: str | None = None,
    expected_codec: str | None = None,
    expected_topology_kind: str | None = None,
    expected_run_id: str | None = None,
    expected_arm_id: str | None = None,
) -> dict[str, Any]:
    """Re-hash every physical binding and return the exact pilot acceptance."""

    root = _physical_root(project_root)
    descriptor = _stable_descriptor(root, acceptance_path, "pilot acceptance")
    _require(
        Path(descriptor["path"]).name == ACCEPTANCE_FILENAME,
        "qualification acceptance filename drifted",
    )
    path = root / descriptor["path"]
    acceptance = _read_canonical_json(path, "qualification pilot acceptance")
    return _validate_acceptance_value(
        root=root,
        acceptance_path=path,
        acceptance=acceptance,
        expected_system=expected_system,
        expected_resource=expected_resource,
        expected_codec=expected_codec,
        expected_topology_kind=expected_topology_kind,
        expected_run_id=expected_run_id,
        expected_arm_id=expected_arm_id,
    )


def _write_immutable_json(
    root: Path,
    path: Path,
    value: dict[str, Any],
    *,
    _fault_hook: Any | None = None,
) -> None:
    payload = _canonical_bytes(value) + b"\n"
    try:
        relative = path.relative_to(root).as_posix()
        with PhysicalRootCustodyV1.open(
            root, label="qualification acceptance project root"
        ) as custody:
            custody.commit_or_adopt_exact_identity(
                relative,
                payload,
                label="qualification pilot acceptance",
                mode=0o444,
                create_parents=False,
                after_publish_step=_fault_hook,
            )
    except (ValueError, PublicationPhysicalIoV1Error) as error:
        raise QualificationPilotAcceptanceV1Error(
            "immutable qualification acceptance collision"
        ) from error


def finalize_checkpoint_qualification_pilot_acceptance_v1(
    *,
    project_root: Path | str,
    output_dir: Path | str,
    expected_run_id: str,
    expected_arm_id: str,
    expected_system: str,
    expected_resource: str,
    expected_scenario: str,
    expected_codec: str,
    expected_policy: str,
    expected_deadline_ms: float,
    topology_kind: str,
    hardware_collector_stopped: bool,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    qualification_index_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_calibration_path: Path | str,
    bootstrap_receipt_path: Path | str,
    qualification_transaction_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    runtime_input_bundle_path: Path | str,
    guardian_service_authority_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_contract_receipt_path: Path | str,
) -> dict[str, Any]:
    """Prepare physical evidence, transform it, and commit only pilot authority."""

    root = _physical_root(project_root)
    try:
        output = Path(output_dir).resolve(strict=True)
        output.relative_to(root)
    except (OSError, ValueError) as exc:
        raise QualificationPilotAcceptanceV1Error(
            "output_dir must be a physical directory under project_root"
        ) from exc
    _require(output.is_dir() and not _is_link(output), "output_dir is not physical")
    _require(_stable_id(expected_run_id), "expected_run_id is invalid")
    _require(_stable_id(expected_arm_id), "expected_arm_id is invalid")
    coordinate = _validate_coordinate(
        {
            "system": expected_system,
            "resource": expected_resource,
            "codec": str(expected_codec).strip().lower().replace("hevc", "h265"),
            "topology_kind": topology_kind,
        },
        expected_system=expected_system,
        expected_resource=expected_resource,
        expected_codec=str(expected_codec).strip().lower().replace("hevc", "h265"),
        expected_topology_kind=topology_kind,
    )
    _require(
        expected_policy == _RESOURCE_POLICIES[coordinate["resource"]],
        "forced resource/policy coordinate drifted",
    )
    _require(
        expected_scenario == _TOPOLOGY_SCENARIOS[coordinate["topology_kind"]],
        "scenario/topology coordinate drifted",
    )
    first_material = _bootstrap_material(
        root=root,
        expected_system=expected_system,
        candidate_manifest_path=candidate_manifest_path,
        candidate_receipt_path=candidate_receipt_path,
        qualification_index_path=qualification_index_path,
        bootstrap_mapping_path=bootstrap_mapping_path,
        bootstrap_calibration_path=bootstrap_calibration_path,
        bootstrap_receipt_path=bootstrap_receipt_path,
    )
    first_operational = _operational_material(
        root=root,
        expected_system=coordinate["system"],
        expected_resource=coordinate["resource"],
        expected_codec=coordinate["codec"],
        expected_topology_kind=coordinate["topology_kind"],
        expected_run_id=expected_run_id,
        expected_arm_id=expected_arm_id,
        candidate_manifest_path=candidate_manifest_path,
        qualification_transaction_receipt_path=(
            qualification_transaction_receipt_path
        ),
        runtime_input_materialization_receipt_path=(
            runtime_input_materialization_receipt_path
        ),
        runtime_input_bundle_path=runtime_input_bundle_path,
        guardian_service_authority_path=guardian_service_authority_path,
        preprocessing_contract_path=preprocessing_contract_path,
        preprocessing_contract_receipt_path=(
            preprocessing_contract_receipt_path
        ),
        require_live_service=True,
    )
    try:
        prepared = prepare_checkpoint_publication_acceptance(
            output_dir=output,
            expected_run_id=expected_run_id,
            expected_system=expected_system,
            expected_scenario=expected_scenario,
            expected_codec=coordinate["codec"],
            expected_policy=expected_policy,
            expected_deadline_ms=expected_deadline_ms,
            topology_kind=topology_kind,
            hardware_collector_stopped=hardware_collector_stopped,
        )
    except ContractError:
        raise
    except Exception as exc:
        raise QualificationPilotAcceptanceV1Error(
            f"physical checkpoint preparation failed: {exc}"
        ) from exc
    _require(
        type(prepared) is dict and set(prepared) == _PREPARED_FIELDS,
        "prepared checkpoint acceptance fields drifted",
    )
    expected_prepared = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_acceptance",
        "status": "accepted_native_checkpoint_arm",
        "run_id": expected_run_id,
        "system": expected_system,
        "scenario": expected_scenario,
        "codec": coordinate["codec"],
        "policy": expected_policy,
        "execution_binding_provenance": NATIVE_EXECUTION_BINDING_PROVENANCE,
        "topology_kind": topology_kind,
    }
    for field, expected in expected_prepared.items():
        _require(
            prepared.get(field) == expected,
            f"prepared checkpoint identity drift: {field}",
        )
    actual_deadline = prepared.get("deadline_ms")
    _require(
        not isinstance(actual_deadline, bool)
        and isinstance(actual_deadline, (int, float))
        and math.isclose(
            float(actual_deadline),
            float(expected_deadline_ms),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        "prepared checkpoint deadline drifted",
    )
    _validate_full_resource_summary(prepared.get("full_resource_summary"))
    _require(
        prepared.get("acceptance_finalization")
        == {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
        },
        "prepared checkpoint full-resource finalization drifted",
    )
    second_material = _bootstrap_material(
        root=root,
        expected_system=expected_system,
        candidate_manifest_path=candidate_manifest_path,
        candidate_receipt_path=candidate_receipt_path,
        qualification_index_path=qualification_index_path,
        bootstrap_mapping_path=bootstrap_mapping_path,
        bootstrap_calibration_path=bootstrap_calibration_path,
        bootstrap_receipt_path=bootstrap_receipt_path,
    )
    second_operational = _operational_material(
        root=root,
        expected_system=coordinate["system"],
        expected_resource=coordinate["resource"],
        expected_codec=coordinate["codec"],
        expected_topology_kind=coordinate["topology_kind"],
        expected_run_id=expected_run_id,
        expected_arm_id=expected_arm_id,
        candidate_manifest_path=candidate_manifest_path,
        qualification_transaction_receipt_path=(
            qualification_transaction_receipt_path
        ),
        runtime_input_materialization_receipt_path=(
            runtime_input_materialization_receipt_path
        ),
        runtime_input_bundle_path=runtime_input_bundle_path,
        guardian_service_authority_path=guardian_service_authority_path,
        preprocessing_contract_path=preprocessing_contract_path,
        preprocessing_contract_receipt_path=(
            preprocessing_contract_receipt_path
        ),
        require_live_service=True,
    )
    _require(
        second_material == first_material,
        "bootstrap/model-parity inputs changed during physical preparation",
    )
    _require(
        second_operational == first_operational,
        "qualification operational inputs changed during physical preparation",
    )
    acceptance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": STATUS,
        "scope": SCOPE,
        "accepted_for_full_publication": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": [NONAUTHORITY_BLOCKER],
        "run_id": expected_run_id,
        "arm_id": expected_arm_id,
        "coordinate": coordinate,
        "scenario": expected_scenario,
        "policy": expected_policy,
        "deadline_ms": prepared["deadline_ms"],
        "execution_binding_provenance": prepared[
            "execution_binding_provenance"
        ],
        "cohort_id": prepared["cohort_id"],
        "measurement_schedule_fingerprint_sha256": prepared[
            "measurement_schedule_fingerprint_sha256"
        ],
        "completed_frames_by_stream": prepared["completed_frames_by_stream"],
        "summary": prepared["summary"],
        "evidence_sha256": prepared["evidence_sha256"],
        "full_resource_evidence_sha256": prepared[
            "full_resource_evidence_sha256"
        ],
        "full_resource_summary": prepared["full_resource_summary"],
        "full_resource_finalization": {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
            "prepared_by": "prepare_checkpoint_publication_acceptance",
        },
        "bootstrap_binding": second_material,
        "operational_binding": second_operational,
    }
    acceptance["sha256"] = _canonical_sha(acceptance)
    acceptance_path = output / ACCEPTANCE_FILENAME
    _validate_acceptance_value(
        root=root,
        acceptance_path=acceptance_path,
        acceptance=acceptance,
        expected_system=expected_system,
        expected_resource=expected_resource,
        expected_codec=coordinate["codec"],
        expected_topology_kind=topology_kind,
        expected_run_id=expected_run_id,
        expected_arm_id=expected_arm_id,
    )
    _write_immutable_json(root, acceptance_path, acceptance)
    return json.loads(_canonical_bytes(acceptance))


__all__ = [
    "ACCEPTANCE_FILENAME",
    "ARTIFACT_KIND",
    "NONAUTHORITY_BLOCKER",
    "QualificationPilotAcceptanceV1Error",
    "SCHEMA_VERSION",
    "SCOPE",
    "STATUS",
    "finalize_checkpoint_qualification_pilot_acceptance_v1",
    "validate_checkpoint_qualification_pilot_acceptance_v1",
]
