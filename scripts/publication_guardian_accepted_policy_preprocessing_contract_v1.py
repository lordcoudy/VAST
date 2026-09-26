#!/usr/bin/env python3
"""Commit a receipt-last accepted-policy preprocessing input for the Q4 guardian."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import publication_guardian_preprocessing_contract_v1 as predecessor
from publication_guardian_runtime_expectations_v1 import (
    runtime_expectations_from_preprocessing_receipt_v1,
)


sys.dont_write_bytecode = True


SCHEMA_VERSION = 1
CONTRACT_FILENAME = "checkpoint_analytics_accepted_policy_preprocessing_contract.v1.json"
RECEIPT_FILENAME = (
    "checkpoint_analytics_accepted_policy_preprocessing_contract.v1.receipt.json"
)
RECEIPT_KIND = (
    "vast_guardian_accepted_policy_preprocessing_contract_materialization_v1"
)
AUTHORITY_KIND = (
    "vast_guardian_accepted_policy_preprocessing_contract_authority_v1"
)
SCOPE = "post_qualification_q4_guardian_preprocessing_only"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
NONAUTHORITY_BLOCKER = "accepted_policy_guardian_input_is_not_full_publication_authority"
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_ACCEPTED_POLICY_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "policy_contract_sha256",
    "qualification_index_sha256",
    "dataset_manifest_sha256",
    "coverage",
    "outputs",
    "sha256",
}
_COVERAGE = {
    "binding_count": 32,
    "pilot_cell_count": 32,
    "accepted_sample_count": 3840,
    "minimum_samples_per_branch_cell": 30,
}
_QUALIFICATION_INDEX_BASE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "policy_contract_sha256",
    "dataset_manifest",
    "bindings",
    "pilots",
}
_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "preprocessing_contract",
    "preprocessing_contract_content_sha256",
    "predecessor_qualification_preprocessing_contract",
    "predecessor_qualification_preprocessing_receipt",
    "predecessor_qualification_preprocessing_receipt_identity_sha256",
    "candidate_manifest",
    "candidate_receipt",
    "candidate_receipt_identity_sha256",
    "qualification_index",
    "qualification_execution_closure_receipt",
    "qualification_execution_closure_receipt_identity_sha256",
    "accepted_policy_qualification_receipt",
    "accepted_policy_qualification_receipt_identity_sha256",
    "accepted_policy_capability_manifest",
    "accepted_policy_capability_manifest_content_sha256",
    "accepted_policy_calibration_mapping",
    "accepted_policy_calibration_mapping_content_sha256",
    "model_parity_refresh_authority",
    "execution_config",
    "execution_config_identity_sha256",
    "binding_set_index",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "binding_preprocessing_consensus_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
    "blockers",
    "receipt_sha256",
}
_AUTHORITY_FIELDS = {
    "schema_version",
    "artifact_kind",
    "preprocessing_contract_content_sha256",
    "preprocessing_contract_file_sha256",
    "materialization_receipt_identity_sha256",
    "materialization_receipt_file_sha256",
    "predecessor_qualification_preprocessing_receipt_identity_sha256",
    "predecessor_qualification_preprocessing_receipt_file_sha256",
    "accepted_policy_qualification_receipt_identity_sha256",
    "accepted_policy_qualification_receipt_file_sha256",
    "accepted_policy_capability_manifest_file_sha256",
    "accepted_policy_capability_manifest_content_sha256",
    "accepted_policy_calibration_mapping_file_sha256",
    "accepted_policy_calibration_mapping_content_sha256",
    "qualification_execution_closure_receipt_identity_sha256",
    "qualification_execution_closure_receipt_file_sha256",
    "execution_config_identity_sha256",
    "execution_config_file_sha256",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "binding_set_index_file_sha256",
    "binding_preprocessing_consensus_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
}


class AcceptedPolicyGuardianPreprocessingContractV1Error(RuntimeError):
    """The accepted-policy guardian input or any predecessor drifted."""


def _fail(message: str) -> None:
    raise AcceptedPolicyGuardianPreprocessingContractV1Error(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise AcceptedPolicyGuardianPreprocessingContractV1Error(
            "accepted-policy guardian value is not canonical JSON"
        ) from error


def _semantic_sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _self_hash(value: Mapping[str, Any], field: str, *, label: str) -> str:
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    _require(
        _valid_sha(claimed) and claimed == _semantic_sha(unsigned),
        f"{label} self identity drifted",
    )
    return str(claimed)


def _translate(error: BaseException, label: str) -> AcceptedPolicyGuardianPreprocessingContractV1Error:
    return AcceptedPolicyGuardianPreprocessingContractV1Error(f"{label}: {error}")


def _root(value: Path | str) -> Path:
    try:
        return predecessor._physical_root(value)
    except Exception as error:
        raise _translate(error, "accepted-policy project_root rejected") from error


def _physical_file(root: Path, value: Path | str, *, label: str) -> Path:
    try:
        return predecessor._physical_file(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    try:
        return predecessor._physical_directory(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    try:
        return predecessor._under_root(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _read_json(root: Path, value: Path | str, *, label: str) -> dict[str, Any]:
    try:
        return predecessor._read_canonical_json(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _descriptor(root: Path, value: Path | str, *, label: str) -> dict[str, Any]:
    try:
        return predecessor._descriptor(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _descriptor_shape(value: object, *, label: str) -> dict[str, Any]:
    try:
        return predecessor._descriptor_shape(value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _verified_descriptor(
    root: Path, value: object, *, label: str
) -> tuple[dict[str, Any], Path]:
    try:
        return predecessor._verified_descriptor(root, value, label=label)
    except Exception as error:
        raise _translate(error, label) from error


def _default_load_qualification_preprocessing(**kwargs: Any) -> dict[str, Any]:
    return predecessor.load_guardian_preprocessing_contract_v1(**kwargs)


def _default_assess_policy_qualification(**kwargs: Any) -> dict[str, Any]:
    from publication_policy_qualification import assess_policy_qualification

    return assess_policy_qualification(**kwargs)


def _default_load_execution_closure(**kwargs: Any) -> dict[str, Any]:
    from publication_policy_qualification_execution_closure_v1 import (
        load_publication_policy_qualification_execution_closure_v1,
    )

    return load_publication_policy_qualification_execution_closure_v1(**kwargs)


def _default_load_execution_config(path: Path) -> dict[str, Any]:
    from checkpoint_gstreamer_analytics_sidecar import load_execution_config

    return load_execution_config(path)


def _default_load_runtime_probe(path: Path, *, engine: str) -> dict[str, Any]:
    from analytics_execution_worker import validate_runtime_probe

    try:
        payload = predecessor.read_file_bytes_fd_custody_v1(
            path, label="accepted guardian runtime probe"
        )
        value = json.loads(payload.decode("ascii"))
    except Exception as error:
        raise _translate(error, "accepted guardian runtime probe") from error
    _require(
        type(value) is dict and payload == _canonical(value) + b"\n",
        "accepted guardian runtime probe is not canonical JSON",
    )
    return validate_runtime_probe(value, engine=engine)


def _default_load_binding_set(
    path: Path,
    *,
    execution_config: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
) -> Any:
    from checkpoint_gstreamer_analytics_sidecar import load_materialized_binding_set

    return load_materialized_binding_set(
        path,
        execution_config=execution_config,
        runtime_probes=runtime_probes,
    )


@dataclass(frozen=True, slots=True)
class AcceptedPolicyGuardianDependenciesV1:
    load_qualification_preprocessing: Callable[..., dict[str, Any]] = (
        _default_load_qualification_preprocessing
    )
    assess_policy_qualification: Callable[..., dict[str, Any]] = (
        _default_assess_policy_qualification
    )
    load_execution_closure: Callable[..., dict[str, Any]] = (
        _default_load_execution_closure
    )
    load_execution_config: Callable[[Path], dict[str, Any]] = (
        _default_load_execution_config
    )
    load_runtime_probe: Callable[..., dict[str, Any]] = _default_load_runtime_probe
    load_binding_set: Callable[..., Any] = _default_load_binding_set


def _embedded_output(
    *,
    actual: Mapping[str, Any],
    embedded: object,
    expected_name: str,
    label: str,
) -> None:
    value = _descriptor_shape(embedded, label=label)
    _require(
        value["path"] == expected_name
        and value["size_bytes"] == actual["size_bytes"]
        and value["sha256"] == actual["sha256"],
        f"{label} embedded descriptor drifted",
    )


def _call(label: str, function: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return function(**kwargs)
    except AcceptedPolicyGuardianPreprocessingContractV1Error:
        raise
    except Exception as error:
        raise _translate(error, f"{label} rejected input") from error


def _source_material(
    *,
    root: Path,
    qualification_preprocessing_contract_path: Path | str,
    qualification_preprocessing_receipt_path: Path | str,
    completed_qualification_index_path: Path | str,
    accepted_policy_qualification_receipt_path: Path | str,
    accepted_policy_capability_manifest_path: Path | str,
    accepted_policy_calibration_mapping_path: Path | str,
    execution_config_path: Path | str,
    binding_set_dir: Path | str,
    dependencies: AcceptedPolicyGuardianDependenciesV1,
) -> dict[str, Any]:
    predecessor_contract_path = _physical_file(
        root,
        qualification_preprocessing_contract_path,
        label="qualification preprocessing contract",
    )
    predecessor_contract_descriptor = _descriptor(
        root, predecessor_contract_path, label="qualification preprocessing contract"
    )
    predecessor_contract = _read_json(
        root, predecessor_contract_path, label="qualification preprocessing contract"
    )
    predecessor_receipt_path = _physical_file(
        root,
        qualification_preprocessing_receipt_path,
        label="qualification preprocessing receipt",
    )
    predecessor_receipt_descriptor = _descriptor(
        root, predecessor_receipt_path, label="qualification preprocessing receipt"
    )
    predecessor_receipt_raw = _read_json(
        root, predecessor_receipt_path, label="qualification preprocessing receipt"
    )
    candidate_descriptor = _descriptor_shape(
        predecessor_receipt_raw.get("candidate_manifest"),
        label="qualification candidate manifest",
    )
    candidate_path = _physical_file(
        root, candidate_descriptor["path"], label="qualification candidate manifest"
    )
    loaded_predecessor = _call(
        "qualification preprocessing loader",
        dependencies.load_qualification_preprocessing,
        project_root=root,
        preprocessing_contract_path=predecessor_contract_path,
        materialization_receipt_path=predecessor_receipt_path,
        candidate_manifest_path=candidate_path,
        expected_preprocessing_contract_sha256=_semantic_sha(predecessor_contract),
    )
    _require(
        type(loaded_predecessor) is dict
        and loaded_predecessor.get("preprocessing_contract") == predecessor_contract
        and loaded_predecessor.get("receipt") == predecessor_receipt_raw
        and type(loaded_predecessor.get("authority")) is dict,
        "qualification preprocessing loader normalized a different predecessor",
    )
    predecessor_receipt_identity = _self_hash(
        predecessor_receipt_raw,
        "receipt_sha256",
        label="qualification preprocessing receipt",
    )
    predecessor_authority = loaded_predecessor["authority"]
    _require(
        predecessor_authority.get("materialization_receipt_identity_sha256")
        == predecessor_receipt_identity
        and predecessor_authority.get("materialization_receipt_file_sha256")
        == predecessor_receipt_descriptor["sha256"],
        "qualification preprocessing predecessor authority drifted",
    )
    try:
        runtime_expectations = runtime_expectations_from_preprocessing_receipt_v1(
            predecessor_receipt_raw
        )
    except Exception as error:
        raise _translate(error, "qualification preprocessing runtime authority") from error
    _require(
        runtime_expectations["preprocessing_contract_content_sha256"]
        == _semantic_sha(predecessor_contract),
        "qualification preprocessing content/runtime identity drifted",
    )

    bootstrap_index_descriptor, bootstrap_index_path = _verified_descriptor(
        root,
        predecessor_receipt_raw.get("qualification_index"),
        label="qualification bootstrap candidate index",
    )
    bootstrap_index = _read_json(
        root,
        bootstrap_index_path,
        label="qualification bootstrap candidate index",
    )
    _require(
        set(bootstrap_index) == _QUALIFICATION_INDEX_BASE_FIELDS
        and bootstrap_index.get("schema_version") == 2
        and bootstrap_index.get("artifact_kind")
        == "vast_publication_policy_qualification_index"
        and bootstrap_index.get("pilots") == []
        and bootstrap_index.get("policy_contract_sha256")
        == runtime_expectations["policy_contract_sha256"],
        "qualification predecessor index is not the exact fragment-only bootstrap",
    )

    index_path = _physical_file(
        root,
        completed_qualification_index_path,
        label="completed qualification index",
    )
    _require(
        index_path != bootstrap_index_path,
        "completed qualification index aliases the fragment-only bootstrap",
    )
    index_descriptor = _descriptor(
        root, index_path, label="completed qualification index"
    )
    index = _read_json(root, index_path, label="completed qualification index")
    _require(
        set(index)
        == _QUALIFICATION_INDEX_BASE_FIELDS | {"qualification_execution_closure"}
        and index.get("schema_version") == bootstrap_index["schema_version"]
        and index.get("artifact_kind") == bootstrap_index["artifact_kind"]
        and type(index.get("pilots")) is list
        and len(index["pilots"]) == 32
        and all(
            index.get(field) == bootstrap_index.get(field)
            for field in _QUALIFICATION_INDEX_BASE_FIELDS - {"pilots"}
        ),
        "completed qualification index drifted from its fragment-only bootstrap",
    )
    closure_descriptor, closure_path = _verified_descriptor(
        root,
        index.get("qualification_execution_closure"),
        label="qualification execution closure receipt",
    )
    closure = _call(
        "qualification execution closure loader",
        dependencies.load_execution_closure,
        project_root=root,
        receipt_path=closure_path,
    )
    _require(
        type(closure) is dict
        and closure.get("receipt_descriptor") == closure_descriptor
        and type(closure.get("receipt")) is dict
        and _valid_sha(closure.get("receipt_sha256")),
        "qualification execution closure lineage drifted",
    )
    transaction_descriptor, _transaction_path = _verified_descriptor(
        root,
        predecessor_receipt_raw.get("qualification_transaction_receipt"),
        label="qualification input transaction receipt",
    )
    transaction_identity = predecessor_receipt_raw.get(
        "qualification_transaction_receipt_sha256"
    )
    closure_receipt = closure["receipt"]
    closure_transaction = closure_receipt.get("qualification_input_transaction")
    closure_preprocessing = closure_receipt.get("guardian_preprocessing")
    _require(
        _valid_sha(transaction_identity)
        and type(closure_transaction) is dict
        and closure_transaction.get("receipt") == transaction_descriptor
        and closure_transaction.get("receipt_sha256") == transaction_identity
        and type(closure_preprocessing) is dict
        and closure_preprocessing.get("contract")
        == predecessor_contract_descriptor
        and closure_preprocessing.get("materialization_receipt")
        == predecessor_receipt_descriptor
        and closure_preprocessing.get(
            "materialization_receipt_identity_sha256"
        )
        == predecessor_receipt_identity
        and closure_preprocessing.get("policy_contract_sha256")
        == runtime_expectations["policy_contract_sha256"],
        "completed qualification closure cross-run transaction/preprocessing lineage drifted",
    )

    candidate_manifest = _read_json(
        root, candidate_path, label="qualification candidate manifest"
    )
    candidate_receipt_descriptor, _candidate_receipt_path = _verified_descriptor(
        root,
        predecessor_receipt_raw.get("candidate_receipt"),
        label="qualification candidate receipt",
    )
    candidate_receipt_identity = predecessor_receipt_raw.get(
        "candidate_receipt_identity_sha256"
    )
    _require(
        _valid_sha(candidate_receipt_identity),
        "qualification candidate receipt identity is invalid",
    )

    accepted_receipt_path = _physical_file(
        root,
        accepted_policy_qualification_receipt_path,
        label="accepted policy qualification receipt",
    )
    accepted_receipt_descriptor = _descriptor(
        root, accepted_receipt_path, label="accepted policy qualification receipt"
    )
    accepted_receipt = _read_json(
        root, accepted_receipt_path, label="accepted policy qualification receipt"
    )
    _require(
        set(accepted_receipt) == _ACCEPTED_POLICY_RECEIPT_FIELDS
        and accepted_receipt.get("schema_version") == 1
        and accepted_receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_receipt"
        and accepted_receipt.get("status")
        == "accepted_evidence_driven_policy_qualification"
        and accepted_receipt.get("coverage") == _COVERAGE,
        "accepted policy qualification receipt schema/status/coverage drifted",
    )
    accepted_receipt_identity = _self_hash(
        accepted_receipt,
        "sha256",
        label="accepted policy qualification receipt",
    )
    _require(
        accepted_receipt.get("qualification_index_sha256")
        == index_descriptor["sha256"],
        "candidate to accepted qualification index promotion drifted",
    )

    capability_path = _physical_file(
        root,
        accepted_policy_capability_manifest_path,
        label="accepted policy capability manifest",
    )
    capability_descriptor = _descriptor(
        root, capability_path, label="accepted policy capability manifest"
    )
    capability = _read_json(
        root, capability_path, label="accepted policy capability manifest"
    )
    calibration_path = _physical_file(
        root,
        accepted_policy_calibration_mapping_path,
        label="accepted policy calibration mapping",
    )
    calibration_descriptor = _descriptor(
        root, calibration_path, label="accepted policy calibration mapping"
    )
    calibration = _read_json(
        root, calibration_path, label="accepted policy calibration mapping"
    )
    outputs = accepted_receipt.get("outputs")
    _require(
        type(outputs) is dict
        and set(outputs) == {"capability_manifest", "calibration_mapping"}
        and capability_path.parent == accepted_receipt_path.parent
        and calibration_path.parent == accepted_receipt_path.parent,
        "accepted policy output namespace drifted",
    )
    _embedded_output(
        actual=capability_descriptor,
        embedded=outputs["capability_manifest"],
        expected_name=capability_path.name,
        label="accepted policy capability manifest",
    )
    _embedded_output(
        actual=calibration_descriptor,
        embedded=outputs["calibration_mapping"],
        expected_name=calibration_path.name,
        label="accepted policy calibration mapping",
    )
    _require(
        capability == candidate_manifest,
        "candidate to accepted capability promotion drifted",
    )
    assessment = _call(
        "official policy qualification assessor",
        dependencies.assess_policy_qualification,
        project_root=root,
        index_path=index_path,
    )
    _require(
        type(assessment) is dict
        and assessment.get("passed") is True
        and assessment.get("status") == "ready_for_atomic_promotion"
        and assessment.get("blockers") == []
        and assessment.get("index_sha256") == index_descriptor["sha256"]
        and assessment.get("dataset_manifest_sha256")
        == accepted_receipt.get("dataset_manifest_sha256")
        and assessment.get("qualification_execution_closure")
        == closure_descriptor
        and assessment.get("coverage") == accepted_receipt.get("coverage")
        and assessment.get("capability_manifest") == capability
        and assessment.get("calibration_mapping") == calibration
        and accepted_receipt.get("policy_contract_sha256")
        == runtime_expectations["policy_contract_sha256"]
        == capability.get("policy_contract_sha256")
        == calibration.get("policy_contract_sha256"),
        "official candidate to accepted policy promotion validation drifted",
    )

    refresh = predecessor_receipt_raw["model_parity_refresh_authority"]
    expected_config = {
        field: refresh["execution_config"][field] for field in _DESCRIPTOR_FIELDS
    }
    config_descriptor, config_authority_path = _verified_descriptor(
        root, expected_config, label="accepted guardian execution config"
    )
    requested_config_path = _physical_file(
        root, execution_config_path, label="requested accepted guardian execution config"
    )
    _require(
        requested_config_path == config_authority_path,
        "requested execution config differs from v4 parity authority",
    )
    config_physical = _read_json(
        root, config_authority_path, label="accepted guardian execution config"
    )
    config = _call(
        "execution config loader",
        dependencies.load_execution_config,
        path=config_authority_path,
    )
    _require(
        config == config_physical
        and type(config.get("identity")) is dict
        and config["identity"].get("sha256")
        == runtime_expectations["execution_config_identity_sha256"],
        "execution config content identity drifted from v4 parity authority",
    )
    workers = config.get("workers")
    _require(
        type(workers) is dict
        and set(workers) == set(RESOURCES)
        and {
            resource: workers[resource].get("image_id") for resource in RESOURCES
        }
        == runtime_expectations["worker_image_ids"],
        "execution config worker images drifted from v4 parity authority",
    )
    probes: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        raw_probe = refresh["runtime_probes"][resource]
        probe_descriptor, probe_path = _verified_descriptor(
            root,
            {field: raw_probe[field] for field in _DESCRIPTOR_FIELDS},
            label=f"accepted guardian {resource} runtime probe",
        )
        probe_physical = _read_json(
            root, probe_path, label=f"accepted guardian {resource} runtime probe"
        )
        checked_probe = _call(
            f"{resource} runtime probe loader",
            dependencies.load_runtime_probe,
            path=probe_path,
            engine=workers[resource]["engine"],
        )
        _require(
            checked_probe == probe_physical
            and checked_probe.get("worker_implementation_sha256")
            == raw_probe.get("worker_implementation_sha256"),
            f"{resource} runtime probe drifted from v4 parity authority",
        )
        _require(
            _descriptor(root, probe_path, label=f"post-load {resource} runtime probe")
            == probe_descriptor,
            f"{resource} runtime probe changed while validating",
        )
        probes[resource] = checked_probe

    binding_index_expected = refresh["binding_set"]["index"]
    binding_index_descriptor, binding_index_path = _verified_descriptor(
        root, binding_index_expected, label="accepted guardian binding-set index"
    )
    binding_root = _physical_directory(
        root, binding_set_dir, label="requested accepted guardian binding set"
    )
    _require(
        binding_root == binding_index_path.parent,
        "requested binding-set directory differs from v4 parity authority",
    )
    materialized = _call(
        "exact binding-set loader",
        dependencies.load_binding_set,
        path=binding_root,
        execution_config=config,
        runtime_probes=probes,
    )
    bindings = getattr(materialized, "bindings", None)
    capabilities = getattr(materialized, "capabilities", None)
    materialized_index = getattr(materialized, "index", None)
    expected_keys = {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
    _require(
        type(bindings) is dict
        and type(capabilities) is dict
        and set(bindings) == expected_keys
        and set(capabilities) == expected_keys
        and type(materialized_index) is dict
        and type(materialized_index.get("identity")) is dict
        and materialized_index["identity"].get("sha256")
        == runtime_expectations["binding_set_identity_sha256"]
        and materialized_index.get("bindings_identity_sha256")
        == runtime_expectations["bindings_identity_sha256"],
        "materialized binding-set identity/coverage drifted from v4 parity authority",
    )
    consensus_rows: list[dict[str, str]] = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            key = (branch, resource)
            _require(
                bindings[key].get("preprocessing_contract_sha256")
                == runtime_expectations["preprocessing_contract_content_sha256"]
                and capabilities[key].get("preprocessing_contract_sha256")
                == runtime_expectations["preprocessing_contract_content_sha256"],
                f"binding/capability preprocessing consensus drifted for {branch}/{resource}",
            )
            consensus_rows.append(
                {
                    "branch": branch,
                    "resource": resource,
                    "preprocessing_contract_sha256": runtime_expectations[
                        "preprocessing_contract_content_sha256"
                    ],
                }
            )

    return {
        "preprocessing_contract": copy.deepcopy(predecessor_contract),
        "predecessor_contract": predecessor_contract_descriptor,
        "predecessor_receipt": predecessor_receipt_descriptor,
        "predecessor_receipt_identity": predecessor_receipt_identity,
        "candidate_manifest": candidate_descriptor,
        "candidate_receipt": candidate_receipt_descriptor,
        "candidate_receipt_identity": candidate_receipt_identity,
        "qualification_index": index_descriptor,
        "execution_closure": closure_descriptor,
        "execution_closure_identity": closure["receipt_sha256"],
        "accepted_receipt": accepted_receipt_descriptor,
        "accepted_receipt_identity": accepted_receipt_identity,
        "accepted_capability": capability_descriptor,
        "accepted_capability_content_identity": _semantic_sha(capability),
        "accepted_calibration": calibration_descriptor,
        "accepted_calibration_content_identity": _semantic_sha(calibration),
        "model_parity_refresh_authority": copy.deepcopy(refresh),
        "execution_config": config_descriptor,
        "binding_set_index": binding_index_descriptor,
        "binding_preprocessing_consensus_sha256": _semantic_sha(consensus_rows),
        "runtime_expectations": runtime_expectations,
    }


def _receipt_unsigned(
    material: Mapping[str, Any], contract_descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    expectations = material["runtime_expectations"]
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": "materialized_from_accepted_policy_qualification",
        "scope": SCOPE,
        "accepted": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "preprocessing_contract": dict(contract_descriptor),
        "preprocessing_contract_content_sha256": expectations[
            "preprocessing_contract_content_sha256"
        ],
        "predecessor_qualification_preprocessing_contract": material[
            "predecessor_contract"
        ],
        "predecessor_qualification_preprocessing_receipt": material[
            "predecessor_receipt"
        ],
        "predecessor_qualification_preprocessing_receipt_identity_sha256": material[
            "predecessor_receipt_identity"
        ],
        "candidate_manifest": material["candidate_manifest"],
        "candidate_receipt": material["candidate_receipt"],
        "candidate_receipt_identity_sha256": material["candidate_receipt_identity"],
        "qualification_index": material["qualification_index"],
        "qualification_execution_closure_receipt": material["execution_closure"],
        "qualification_execution_closure_receipt_identity_sha256": material[
            "execution_closure_identity"
        ],
        "accepted_policy_qualification_receipt": material["accepted_receipt"],
        "accepted_policy_qualification_receipt_identity_sha256": material[
            "accepted_receipt_identity"
        ],
        "accepted_policy_capability_manifest": material["accepted_capability"],
        "accepted_policy_capability_manifest_content_sha256": material[
            "accepted_capability_content_identity"
        ],
        "accepted_policy_calibration_mapping": material["accepted_calibration"],
        "accepted_policy_calibration_mapping_content_sha256": material[
            "accepted_calibration_content_identity"
        ],
        "model_parity_refresh_authority": material[
            "model_parity_refresh_authority"
        ],
        "execution_config": material["execution_config"],
        "execution_config_identity_sha256": expectations[
            "execution_config_identity_sha256"
        ],
        "binding_set_index": material["binding_set_index"],
        "binding_set_identity_sha256": expectations["binding_set_identity_sha256"],
        "bindings_identity_sha256": expectations["bindings_identity_sha256"],
        "binding_preprocessing_consensus_sha256": material[
            "binding_preprocessing_consensus_sha256"
        ],
        "worker_image_ids": expectations["worker_image_ids"],
        "policy_contract_sha256": expectations["policy_contract_sha256"],
        "blockers": [NONAUTHORITY_BLOCKER],
    }


def validate_accepted_policy_guardian_preprocessing_authority_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _AUTHORITY_FIELDS,
        "accepted-policy guardian preprocessing authority fields drifted",
    )
    authority = dict(value)
    _require(
        authority.get("schema_version") == SCHEMA_VERSION
        and authority.get("artifact_kind") == AUTHORITY_KIND
        and all(
            _valid_sha(authority.get(field))
            for field in _AUTHORITY_FIELDS
            if field.endswith("_sha256")
        )
        and type(authority.get("worker_image_ids")) is dict
        and set(authority["worker_image_ids"]) == set(RESOURCES)
        and all(
            type(item) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", item)
            for item in authority["worker_image_ids"].values()
        ),
        "accepted-policy guardian preprocessing authority identities drifted",
    )
    return copy.deepcopy(authority)


def _authority(
    *,
    receipt: Mapping[str, Any],
    receipt_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    return validate_accepted_policy_guardian_preprocessing_authority_v1(
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": AUTHORITY_KIND,
            "preprocessing_contract_content_sha256": receipt[
                "preprocessing_contract_content_sha256"
            ],
            "preprocessing_contract_file_sha256": receipt[
                "preprocessing_contract"
            ]["sha256"],
            "materialization_receipt_identity_sha256": receipt["receipt_sha256"],
            "materialization_receipt_file_sha256": receipt_descriptor["sha256"],
            "predecessor_qualification_preprocessing_receipt_identity_sha256": receipt[
                "predecessor_qualification_preprocessing_receipt_identity_sha256"
            ],
            "predecessor_qualification_preprocessing_receipt_file_sha256": receipt[
                "predecessor_qualification_preprocessing_receipt"
            ]["sha256"],
            "accepted_policy_qualification_receipt_identity_sha256": receipt[
                "accepted_policy_qualification_receipt_identity_sha256"
            ],
            "accepted_policy_qualification_receipt_file_sha256": receipt[
                "accepted_policy_qualification_receipt"
            ]["sha256"],
            "accepted_policy_capability_manifest_file_sha256": receipt[
                "accepted_policy_capability_manifest"
            ]["sha256"],
            "accepted_policy_capability_manifest_content_sha256": receipt[
                "accepted_policy_capability_manifest_content_sha256"
            ],
            "accepted_policy_calibration_mapping_file_sha256": receipt[
                "accepted_policy_calibration_mapping"
            ]["sha256"],
            "accepted_policy_calibration_mapping_content_sha256": receipt[
                "accepted_policy_calibration_mapping_content_sha256"
            ],
            "qualification_execution_closure_receipt_identity_sha256": receipt[
                "qualification_execution_closure_receipt_identity_sha256"
            ],
            "qualification_execution_closure_receipt_file_sha256": receipt[
                "qualification_execution_closure_receipt"
            ]["sha256"],
            "execution_config_identity_sha256": receipt[
                "execution_config_identity_sha256"
            ],
            "execution_config_file_sha256": receipt["execution_config"]["sha256"],
            "binding_set_identity_sha256": receipt["binding_set_identity_sha256"],
            "bindings_identity_sha256": receipt["bindings_identity_sha256"],
            "binding_set_index_file_sha256": receipt["binding_set_index"]["sha256"],
            "binding_preprocessing_consensus_sha256": receipt[
                "binding_preprocessing_consensus_sha256"
            ],
            "worker_image_ids": copy.deepcopy(receipt["worker_image_ids"]),
            "policy_contract_sha256": receipt["policy_contract_sha256"],
        }
    )


def materialize_accepted_policy_guardian_preprocessing_contract_v1(
    *,
    project_root: Path | str,
    qualification_preprocessing_contract_path: Path | str,
    qualification_preprocessing_receipt_path: Path | str,
    completed_qualification_index_path: Path | str,
    accepted_policy_qualification_receipt_path: Path | str,
    accepted_policy_capability_manifest_path: Path | str,
    accepted_policy_calibration_mapping_path: Path | str,
    execution_config_path: Path | str,
    binding_set_dir: Path | str,
    output_dir: Path | str,
    dependencies: AcceptedPolicyGuardianDependenciesV1 = AcceptedPolicyGuardianDependenciesV1(),
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Validate every accepted predecessor, then commit its receipt last."""

    root = _root(project_root)
    output = _under_root(root, output_dir, label="accepted-policy guardian output")
    _require(
        output != root,
        "accepted-policy guardian output must be a dedicated directory",
    )
    material = _source_material(
        root=root,
        qualification_preprocessing_contract_path=(
            qualification_preprocessing_contract_path
        ),
        qualification_preprocessing_receipt_path=(
            qualification_preprocessing_receipt_path
        ),
        completed_qualification_index_path=completed_qualification_index_path,
        accepted_policy_qualification_receipt_path=(
            accepted_policy_qualification_receipt_path
        ),
        accepted_policy_capability_manifest_path=(
            accepted_policy_capability_manifest_path
        ),
        accepted_policy_calibration_mapping_path=(
            accepted_policy_calibration_mapping_path
        ),
        execution_config_path=execution_config_path,
        binding_set_dir=binding_set_dir,
        dependencies=dependencies,
    )
    contract_path = output / CONTRACT_FILENAME
    receipt_path = output / RECEIPT_FILENAME
    contract_payload = _canonical(material["preprocessing_contract"]) + b"\n"
    contract_descriptor = predecessor._planned_descriptor(
        root, contract_path, contract_payload
    )
    unsigned = _receipt_unsigned(material, contract_descriptor)
    receipt = {**unsigned, "receipt_sha256": _semantic_sha(unsigned)}
    receipt_payload = _canonical(receipt) + b"\n"
    try:
        predecessor._commit_receipt_last_bundle_v1(
            root=root,
            output=output,
            intent_kind=(
                "vast_guardian_accepted_policy_preprocessing_materialization_intent_v1"
            ),
            ordered_payloads=(
                (CONTRACT_FILENAME, contract_payload),
                (RECEIPT_FILENAME, receipt_payload),
            ),
            label="accepted-policy guardian preprocessing",
            after_physical_commit_step=after_physical_commit_step,
        )
        loaded = load_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=root,
            preprocessing_contract_path=contract_path,
            materialization_receipt_path=receipt_path,
            accepted_policy_capability_manifest_path=(
                accepted_policy_capability_manifest_path
            ),
            dependencies=dependencies,
        )
        _require(
            loaded["receipt"] == receipt
            and loaded["preprocessing_contract"] == material["preprocessing_contract"],
            "accepted-policy guardian post-commit cold load drifted",
        )
    except Exception as error:
        if isinstance(error, AcceptedPolicyGuardianPreprocessingContractV1Error):
            raise
        raise _translate(error, "accepted-policy guardian receipt-last commit failed") from error
    return {
        "contract_path": contract_path,
        "receipt_path": receipt_path,
        "preprocessing_contract_sha256": material["runtime_expectations"][
            "preprocessing_contract_content_sha256"
        ],
    }


def load_accepted_policy_guardian_preprocessing_contract_v1(
    *,
    project_root: Path | str,
    preprocessing_contract_path: Path | str,
    materialization_receipt_path: Path | str,
    accepted_policy_capability_manifest_path: Path | str,
    dependencies: AcceptedPolicyGuardianDependenciesV1 = AcceptedPolicyGuardianDependenciesV1(),
) -> dict[str, Any]:
    """Cold-load the distinct post-qualification receipt and all predecessors."""

    root = _root(project_root)
    contract_path = _physical_file(
        root, preprocessing_contract_path, label="accepted-policy preprocessing contract"
    )
    receipt_path = _physical_file(
        root, materialization_receipt_path, label="accepted-policy preprocessing receipt"
    )
    _require(
        contract_path.parent == receipt_path.parent
        and contract_path.name == CONTRACT_FILENAME
        and receipt_path.name == RECEIPT_FILENAME,
        "accepted-policy preprocessing contract/receipt namespace drifted",
    )
    contract_descriptor = _descriptor(
        root, contract_path, label="accepted-policy preprocessing contract"
    )
    contract = _read_json(
        root, contract_path, label="accepted-policy preprocessing contract"
    )
    receipt_descriptor = _descriptor(
        root, receipt_path, label="accepted-policy preprocessing receipt"
    )
    receipt = _read_json(root, receipt_path, label="accepted-policy preprocessing receipt")
    _require(
        set(receipt) == _RECEIPT_FIELDS
        and receipt.get("schema_version") == SCHEMA_VERSION
        and receipt.get("artifact_kind") == RECEIPT_KIND
        and receipt.get("status") == "materialized_from_accepted_policy_qualification"
        and receipt.get("scope") == SCOPE
        and receipt.get("accepted") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and receipt.get("preprocessing_contract") == contract_descriptor
        and receipt.get("preprocessing_contract_content_sha256")
        == _semantic_sha(contract)
        and receipt.get("blockers") == [NONAUTHORITY_BLOCKER],
        "accepted-policy preprocessing receipt identity drifted",
    )
    _self_hash(receipt, "receipt_sha256", label="accepted-policy preprocessing receipt")
    requested_capability = _descriptor(
        root,
        accepted_policy_capability_manifest_path,
        label="requested accepted policy capability manifest",
    )
    _require(
        requested_capability == receipt.get("accepted_policy_capability_manifest"),
        "requested accepted policy capability differs from materialization receipt",
    )
    predecessor_contract = _descriptor_shape(
        receipt.get("predecessor_qualification_preprocessing_contract"),
        label="predecessor qualification preprocessing contract",
    )
    predecessor_receipt = _descriptor_shape(
        receipt.get("predecessor_qualification_preprocessing_receipt"),
        label="predecessor qualification preprocessing receipt",
    )
    completed_index = _descriptor_shape(
        receipt.get("qualification_index"),
        label="completed qualification index",
    )
    accepted_receipt = _descriptor_shape(
        receipt.get("accepted_policy_qualification_receipt"),
        label="accepted policy qualification receipt",
    )
    accepted_calibration = _descriptor_shape(
        receipt.get("accepted_policy_calibration_mapping"),
        label="accepted policy calibration mapping",
    )
    execution_config = _descriptor_shape(
        receipt.get("execution_config"), label="accepted guardian execution config"
    )
    binding_index = _descriptor_shape(
        receipt.get("binding_set_index"), label="accepted guardian binding-set index"
    )
    material = _source_material(
        root=root,
        qualification_preprocessing_contract_path=predecessor_contract["path"],
        qualification_preprocessing_receipt_path=predecessor_receipt["path"],
        completed_qualification_index_path=completed_index["path"],
        accepted_policy_qualification_receipt_path=accepted_receipt["path"],
        accepted_policy_capability_manifest_path=requested_capability["path"],
        accepted_policy_calibration_mapping_path=accepted_calibration["path"],
        execution_config_path=execution_config["path"],
        binding_set_dir=(root / binding_index["path"]).parent,
        dependencies=dependencies,
    )
    expected_unsigned = _receipt_unsigned(material, contract_descriptor)
    expected = {**expected_unsigned, "receipt_sha256": _semantic_sha(expected_unsigned)}
    _require(receipt == expected, "accepted-policy preprocessing upstream chain drifted")
    return {
        "preprocessing_contract": contract,
        "receipt": receipt,
        "authority": _authority(receipt=receipt, receipt_descriptor=receipt_descriptor),
        "runtime_expectations": copy.deepcopy(material["runtime_expectations"]),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--qualification-preprocessing-contract", type=Path, required=True)
    parser.add_argument("--qualification-preprocessing-receipt", type=Path, required=True)
    parser.add_argument("--completed-qualification-index", type=Path, required=True)
    parser.add_argument("--accepted-policy-qualification-receipt", type=Path, required=True)
    parser.add_argument("--accepted-policy-capability-manifest", type=Path, required=True)
    parser.add_argument("--accepted-policy-calibration-mapping", type=Path, required=True)
    parser.add_argument("--execution-config", type=Path, required=True)
    parser.add_argument("--binding-set", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=args.project_root,
            qualification_preprocessing_contract_path=(
                args.qualification_preprocessing_contract
            ),
            qualification_preprocessing_receipt_path=(
                args.qualification_preprocessing_receipt
            ),
            completed_qualification_index_path=args.completed_qualification_index,
            accepted_policy_qualification_receipt_path=(
                args.accepted_policy_qualification_receipt
            ),
            accepted_policy_capability_manifest_path=(
                args.accepted_policy_capability_manifest
            ),
            accepted_policy_calibration_mapping_path=(
                args.accepted_policy_calibration_mapping
            ),
            execution_config_path=args.execution_config,
            binding_set_dir=args.binding_set,
            output_dir=args.output_dir,
        )
    except AcceptedPolicyGuardianPreprocessingContractV1Error as error:
        print(f"accepted-policy guardian preprocessing blocked: {error}", file=sys.stderr)
        return 78
    print(
        json.dumps(
            {key: str(value) if isinstance(value, Path) else value for key, value in result.items()},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTHORITY_KIND",
    "AcceptedPolicyGuardianDependenciesV1",
    "AcceptedPolicyGuardianPreprocessingContractV1Error",
    "CONTRACT_FILENAME",
    "RECEIPT_FILENAME",
    "RECEIPT_KIND",
    "SYSTEMS",
    "load_accepted_policy_guardian_preprocessing_contract_v1",
    "main",
    "materialize_accepted_policy_guardian_preprocessing_contract_v1",
    "validate_accepted_policy_guardian_preprocessing_authority_v1",
]
