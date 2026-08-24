#!/usr/bin/env python3
"""Pure, closed, non-authorizing validation-record graph schemas."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)
COORDINATE_FIELDS = (
    "system", "codec", "topology_kind", "policy", "deadline_ms", "cell_index",
)
UPSTREAM_IDENTITY_FIELDS = (
    "dataset_manifest_sha256", "policy_contract_sha256",
    "policy_qualification_receipt_sha256", "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
)
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_REF_FIELDS = frozenset({"descriptor", "content_identity_sha256"})


class BackendRuntimeValidationRecordError(ValueError):
    """A persisted replay graph node is malformed or cross-bound incorrectly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeValidationRecordError(message)


def canonical_identity(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeValidationRecordError(
            "validation record node is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _path(value: Any) -> str:
    _require(type(value) is str and bool(value) and "\\" not in value
             and ":" not in value and "\x00" not in value
             and not value.startswith("/") and not value.endswith("/"),
             "artifact path is unsafe")
    parts = value.split("/")
    _require(all(part not in {"", ".", ".."}
                 and not part.endswith((".", " "))
                 and not any(ord(character) < 32 for character in part)
                 and part.split(".", 1)[0].upper() not in _RESERVED
                 for part in parts), "artifact path is unsafe")
    return value


def _ref(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REF_FIELDS,
             f"{label} reference fields drifted")
    descriptor = value.get("descriptor")
    _require(type(descriptor) is dict and set(descriptor) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    checked = {
        "path": _path(descriptor.get("path")),
        "size_bytes": descriptor.get("size_bytes"),
        "sha256": _sha(descriptor.get("sha256"), f"{label} file"),
    }
    _require(type(checked["size_bytes"]) is int
             and 0 < checked["size_bytes"] <= 8 * 1024 * 1024 * 1024,
             f"{label} size is invalid")
    identity = _sha(value.get("content_identity_sha256"), f"{label} semantic")
    return {"descriptor": checked, "content_identity_sha256": identity}


def _require_unique_ref_identities(
    references: Sequence[Mapping[str, Any]], label: str,
) -> None:
    paths = [reference["descriptor"]["path"] for reference in references]
    file_identities = [
        reference["descriptor"]["sha256"] for reference in references
    ]
    content_identities = [
        reference["content_identity_sha256"] for reference in references
    ]
    _require(len(paths) == len(set(paths)), f"{label} path is duplicated")
    _require(len(file_identities) == len(set(file_identities)),
             f"{label} file identity is duplicated")
    _require(len(content_identities) == len(set(content_identities)),
             f"{label} semantic identity is duplicated")


def _upstream(value: Any) -> dict[str, str]:
    _require(type(value) is dict and set(value) == set(UPSTREAM_IDENTITY_FIELDS),
             "upstream identity fields drifted")
    return {key: _sha(value[key], key) for key in UPSTREAM_IDENTITY_FIELDS}


def _coordinate(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(set(value) == set(COORDINATE_FIELDS), "coordinate fields drifted")
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    deadline = value.get("deadline_ms")
    cell_index = value.get("cell_index")
    _require(system in SYSTEMS and codec in CODECS and topology in TOPOLOGIES
             and policy in POLICIES, "coordinate value is invalid")
    _require(type(deadline) in {int, float} and math.isfinite(float(deadline)),
             "deadline is invalid")
    matching_deadlines = [
        index for index, expected_deadline in enumerate(DEADLINES_MS)
        if type(deadline) is type(expected_deadline) and deadline == expected_deadline
    ]
    _require(len(matching_deadlines) == 1, "deadline is invalid")
    _require(type(cell_index) is int and 0 <= cell_index < 560,
             "cell index is invalid")
    expected = (((SYSTEMS.index(system) * len(CODECS) + CODECS.index(codec))
                 * len(TOPOLOGIES) + TOPOLOGIES.index(topology))
                * len(POLICIES) + POLICIES.index(policy))
    expected = expected * len(DEADLINES_MS) + matching_deadlines[0]
    _require(cell_index == expected, "cell index does not match global ordinal")
    return {key: copy.deepcopy(value[key]) for key in COORDINATE_FIELDS}


_CONTEXT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "qualification_index_ref",
    "qualification_index_sha256", "upstream_identities",
    "runtime_binding_identity_sha256", "runtime_authority_set_sha256",
    "validator_authority_ref", "validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "runner_invocation_identity_sha256", "validation_protocol_identity_sha256",
    "input_schema_identity_sha256", "output_schema_identity_sha256",
    "context_sha256",
})


def build_backend_runtime_validation_system_context(
    *, system: str, qualification_index_ref: Mapping[str, Any],
    qualification_index_sha256: str, upstream_identities: Mapping[str, Any],
    runtime_binding_identity_sha256: str, runtime_authority_set_sha256: str,
    validator_authority_ref: Mapping[str, Any], validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    runner_invocation_identity_sha256: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str, output_schema_identity_sha256: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validation_system_context",
        "system": system,
        "qualification_index_ref": copy.deepcopy(dict(qualification_index_ref)),
        "qualification_index_sha256": qualification_index_sha256,
        "upstream_identities": copy.deepcopy(dict(upstream_identities)),
        "runtime_binding_identity_sha256": runtime_binding_identity_sha256,
        "runtime_authority_set_sha256": runtime_authority_set_sha256,
        "validator_authority_ref": copy.deepcopy(dict(validator_authority_ref)),
        "validator_authority_sha256": validator_authority_sha256,
        "runner_authority_ref": copy.deepcopy(dict(runner_authority_ref)),
        "runner_authority_sha256": runner_authority_sha256,
        "runner_invocation_identity_sha256": runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
    }
    value["context_sha256"] = canonical_identity(value)
    return validate_backend_runtime_validation_system_context(
        value, expected_semantic_sha256=value["context_sha256"],
        expected_system=system,
        expected_qualification_index_ref=qualification_index_ref,
        expected_qualification_index_sha256=qualification_index_sha256,
        expected_upstream_identities=upstream_identities,
        expected_runtime_binding_identity_sha256=runtime_binding_identity_sha256,
        expected_runtime_authority_set_sha256=runtime_authority_set_sha256,
        expected_validator_authority_ref=validator_authority_ref,
        expected_validator_authority_sha256=validator_authority_sha256,
        expected_runner_authority_ref=runner_authority_ref,
        expected_runner_authority_sha256=runner_authority_sha256,
        expected_runner_invocation_identity_sha256=runner_invocation_identity_sha256,
        expected_validation_protocol_identity_sha256=validation_protocol_identity_sha256,
        expected_input_schema_identity_sha256=input_schema_identity_sha256,
        expected_output_schema_identity_sha256=output_schema_identity_sha256,
    )


def validate_backend_runtime_validation_system_context(
    value: Any, *, expected_semantic_sha256: str, expected_system: str,
    expected_qualification_index_ref: Mapping[str, Any],
    expected_qualification_index_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_runtime_binding_identity_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_validator_authority_ref: Mapping[str, Any],
    expected_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_validation_protocol_identity_sha256: str,
    expected_input_schema_identity_sha256: str,
    expected_output_schema_identity_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _CONTEXT_FIELDS,
             "system context fields drifted")
    _require(value.get("schema_version") == 1
             and value.get("artifact_kind")
             == "vast_backend_runtime_validation_system_context"
             and value.get("system") in SYSTEMS, "system context header drifted")
    qualification_ref = _ref(value.get("qualification_index_ref"), "qualification index")
    validator_ref = _ref(value.get("validator_authority_ref"), "validator authority")
    runner_ref = _ref(value.get("runner_authority_ref"), "runner authority")
    _upstream(value.get("upstream_identities"))
    for field in (
        "qualification_index_sha256", "runtime_binding_identity_sha256",
        "runtime_authority_set_sha256", "validator_authority_sha256",
        "runner_authority_sha256", "runner_invocation_identity_sha256",
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256", "context_sha256",
    ):
        _sha(value.get(field), field)
    _require(qualification_ref["content_identity_sha256"]
             == value["qualification_index_sha256"]
             and validator_ref["content_identity_sha256"]
             == value["validator_authority_sha256"]
             and runner_ref["content_identity_sha256"]
             == value["runner_authority_sha256"],
             "system context artifact semantic cross-binding drifted")
    expected = {
        "system": expected_system,
        "qualification_index_ref": expected_qualification_index_ref,
        "qualification_index_sha256": expected_qualification_index_sha256,
        "upstream_identities": expected_upstream_identities,
        "runtime_binding_identity_sha256": expected_runtime_binding_identity_sha256,
        "runtime_authority_set_sha256": expected_runtime_authority_set_sha256,
        "validator_authority_ref": expected_validator_authority_ref,
        "validator_authority_sha256": expected_validator_authority_sha256,
        "runner_authority_ref": expected_runner_authority_ref,
        "runner_authority_sha256": expected_runner_authority_sha256,
        "runner_invocation_identity_sha256": expected_runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": expected_validation_protocol_identity_sha256,
        "input_schema_identity_sha256": expected_input_schema_identity_sha256,
        "output_schema_identity_sha256": expected_output_schema_identity_sha256,
    }
    _require(all(value.get(key) == item for key, item in expected.items()),
             "system context external trust pin drifted")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "context_sha256"}
    _require(value["context_sha256"] == canonical_identity(unsigned)
             == _sha(expected_semantic_sha256, "expected context"),
             "system context semantic identity drifted")
    return copy.deepcopy(value)


_REQUEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", *COORDINATE_FIELDS, "context_ref",
    "context_sha256", "qualification_index_sha256", "upstream_identities",
    "runtime_binding_identity_sha256", "runtime_authority_set_sha256",
    "runtime_authority_ref", "runtime_authority_sha256", "raw_evidence_ref",
    "validator_authority_sha256", "runner_authority_sha256",
    "runner_invocation_identity_sha256", "validation_protocol_identity_sha256",
    "input_schema_identity_sha256", "output_schema_identity_sha256",
    "request_sha256",
})


def build_backend_runtime_validation_request(
    *, system: str, codec: str, topology_kind: str, policy: str,
    deadline_ms: int | float, cell_index: int,
    context_ref: Mapping[str, Any], context_sha256: str,
    qualification_index_sha256: str, upstream_identities: Mapping[str, Any],
    runtime_binding_identity_sha256: str, runtime_authority_set_sha256: str,
    runtime_authority_ref: Mapping[str, Any], runtime_authority_sha256: str,
    raw_evidence_ref: Mapping[str, Any], validator_authority_sha256: str,
    runner_authority_sha256: str, runner_invocation_identity_sha256: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str, output_schema_identity_sha256: str,
) -> dict[str, Any]:
    coordinate = _coordinate({
        "system": system, "codec": codec, "topology_kind": topology_kind,
        "policy": policy, "deadline_ms": deadline_ms, "cell_index": cell_index,
    })
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validation_replay_request",
        **coordinate, "context_ref": copy.deepcopy(dict(context_ref)),
        "context_sha256": context_sha256,
        "qualification_index_sha256": qualification_index_sha256,
        "upstream_identities": copy.deepcopy(dict(upstream_identities)),
        "runtime_binding_identity_sha256": runtime_binding_identity_sha256,
        "runtime_authority_set_sha256": runtime_authority_set_sha256,
        "runtime_authority_ref": copy.deepcopy(dict(runtime_authority_ref)),
        "runtime_authority_sha256": runtime_authority_sha256,
        "raw_evidence_ref": copy.deepcopy(dict(raw_evidence_ref)),
        "validator_authority_sha256": validator_authority_sha256,
        "runner_authority_sha256": runner_authority_sha256,
        "runner_invocation_identity_sha256": runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
    }
    value["request_sha256"] = canonical_identity(value)
    return validate_backend_runtime_validation_request(
        value, expected_semantic_sha256=value["request_sha256"],
        expected_context_ref=context_ref, expected_context_sha256=context_sha256,
        expected_coordinate=coordinate,
        expected_qualification_index_sha256=qualification_index_sha256,
        expected_upstream_identities=upstream_identities,
        expected_runtime_binding_identity_sha256=runtime_binding_identity_sha256,
        expected_runtime_authority_set_sha256=runtime_authority_set_sha256,
        expected_runtime_authority_ref=runtime_authority_ref,
        expected_runtime_authority_sha256=runtime_authority_sha256,
        expected_raw_evidence_ref=raw_evidence_ref,
        expected_validator_authority_sha256=validator_authority_sha256,
        expected_runner_authority_sha256=runner_authority_sha256,
        expected_runner_invocation_identity_sha256=runner_invocation_identity_sha256,
        expected_validation_protocol_identity_sha256=validation_protocol_identity_sha256,
        expected_input_schema_identity_sha256=input_schema_identity_sha256,
        expected_output_schema_identity_sha256=output_schema_identity_sha256,
    )


def validate_backend_runtime_validation_request(
    value: Any, *, expected_semantic_sha256: str,
    expected_context_ref: Mapping[str, Any], expected_context_sha256: str,
    expected_coordinate: Mapping[str, Any],
    expected_qualification_index_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_runtime_binding_identity_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_runtime_authority_ref: Mapping[str, Any],
    expected_runtime_authority_sha256: str,
    expected_raw_evidence_ref: Mapping[str, Any],
    expected_validator_authority_sha256: str,
    expected_runner_authority_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_validation_protocol_identity_sha256: str,
    expected_input_schema_identity_sha256: str,
    expected_output_schema_identity_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REQUEST_FIELDS,
             "validation request fields drifted")
    _require(value.get("schema_version") == 1
             and value.get("artifact_kind")
             == "vast_backend_runtime_validation_replay_request",
             "validation request header drifted")
    coordinate = _coordinate({key: value.get(key) for key in COORDINATE_FIELDS})
    context_checked = _ref(value.get("context_ref"), "context")
    runtime_ref = _ref(value.get("runtime_authority_ref"), "runtime authority")
    _ref(value.get("raw_evidence_ref"), "raw evidence")
    _upstream(value.get("upstream_identities"))
    for field in (
        "context_sha256", "qualification_index_sha256",
        "runtime_binding_identity_sha256", "runtime_authority_set_sha256",
        "runtime_authority_sha256", "validator_authority_sha256",
        "runner_authority_sha256", "runner_invocation_identity_sha256",
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256", "request_sha256",
    ):
        _sha(value.get(field), field)
    _require(runtime_ref["content_identity_sha256"]
             == value["runtime_authority_sha256"],
             "runtime authority reference semantic identity drifted")
    _require(context_checked["content_identity_sha256"] == value["context_sha256"],
             "context reference semantic identity drifted")
    expected = {
        "context_ref": expected_context_ref, "context_sha256": expected_context_sha256,
        "qualification_index_sha256": expected_qualification_index_sha256,
        "upstream_identities": expected_upstream_identities,
        "runtime_binding_identity_sha256": expected_runtime_binding_identity_sha256,
        "runtime_authority_set_sha256": expected_runtime_authority_set_sha256,
        "runtime_authority_ref": expected_runtime_authority_ref,
        "runtime_authority_sha256": expected_runtime_authority_sha256,
        "raw_evidence_ref": expected_raw_evidence_ref,
        "validator_authority_sha256": expected_validator_authority_sha256,
        "runner_authority_sha256": expected_runner_authority_sha256,
        "runner_invocation_identity_sha256": expected_runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": expected_validation_protocol_identity_sha256,
        "input_schema_identity_sha256": expected_input_schema_identity_sha256,
        "output_schema_identity_sha256": expected_output_schema_identity_sha256,
    }
    _require(coordinate == _coordinate(dict(expected_coordinate))
             and all(value.get(key) == item for key, item in expected.items()),
             "validation request external trust pin drifted")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "request_sha256"}
    _require(value["request_sha256"] == canonical_identity(unsigned)
             == _sha(expected_semantic_sha256, "expected request"),
             "validation request semantic identity drifted")
    return copy.deepcopy(value)


_REPLAY_RESULT_FIELDS = frozenset({
    "record_status", "accepted", "synthetic", "nonpublication",
    "publication_capable", "deterministic_replay_completed", "blocker_codes",
})
_RECORD_FIELDS = frozenset({
    "schema_version", "artifact_kind", *COORDINATE_FIELDS, "request_ref",
    "request_sha256", "qualification_index_sha256", "upstream_identities",
    "raw_evidence_ref", "runtime_authority_ref", "runtime_authority_sha256",
    "validator_authority_ref", "validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "runner_invocation_identity_sha256", "validation_protocol_identity_sha256",
    "input_schema_identity_sha256", "output_schema_identity_sha256",
    "replay_result", "validation_record_sha256",
})


def build_backend_runtime_validation_record(
    *, system: str, codec: str, topology_kind: str, policy: str,
    deadline_ms: int | float, cell_index: int,
    request_ref: Mapping[str, Any], request_sha256: str,
    qualification_index_sha256: str, upstream_identities: Mapping[str, Any],
    raw_evidence_ref: Mapping[str, Any], runtime_authority_ref: Mapping[str, Any],
    runtime_authority_sha256: str,
    validator_authority_ref: Mapping[str, Any], validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    runner_invocation_identity_sha256: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str, output_schema_identity_sha256: str,
    replay_result: Mapping[str, Any],
) -> dict[str, Any]:
    coordinate = _coordinate({
        "system": system, "codec": codec, "topology_kind": topology_kind,
        "policy": policy, "deadline_ms": deadline_ms, "cell_index": cell_index,
    })
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_cell_validation_record",
        **coordinate, "request_ref": copy.deepcopy(dict(request_ref)),
        "request_sha256": request_sha256,
        "qualification_index_sha256": qualification_index_sha256,
        "upstream_identities": copy.deepcopy(dict(upstream_identities)),
        "raw_evidence_ref": copy.deepcopy(dict(raw_evidence_ref)),
        "runtime_authority_ref": copy.deepcopy(dict(runtime_authority_ref)),
        "runtime_authority_sha256": runtime_authority_sha256,
        "validator_authority_ref": copy.deepcopy(dict(validator_authority_ref)),
        "validator_authority_sha256": validator_authority_sha256,
        "runner_authority_ref": copy.deepcopy(dict(runner_authority_ref)),
        "runner_authority_sha256": runner_authority_sha256,
        "runner_invocation_identity_sha256": runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
        "replay_result": copy.deepcopy(dict(replay_result)),
    }
    value["validation_record_sha256"] = canonical_identity(value)
    return validate_backend_runtime_validation_record(
        value, expected_semantic_sha256=value["validation_record_sha256"],
        expected_request_ref=request_ref, expected_request_sha256=request_sha256,
        expected_coordinate=coordinate,
        expected_qualification_index_sha256=qualification_index_sha256,
        expected_upstream_identities=upstream_identities,
        expected_raw_evidence_ref=raw_evidence_ref,
        expected_runtime_authority_ref=runtime_authority_ref,
        expected_runtime_authority_sha256=runtime_authority_sha256,
        expected_validator_authority_ref=validator_authority_ref,
        expected_validator_authority_sha256=validator_authority_sha256,
        expected_runner_authority_ref=runner_authority_ref,
        expected_runner_authority_sha256=runner_authority_sha256,
        expected_runner_invocation_identity_sha256=runner_invocation_identity_sha256,
        expected_validation_protocol_identity_sha256=validation_protocol_identity_sha256,
        expected_input_schema_identity_sha256=input_schema_identity_sha256,
        expected_output_schema_identity_sha256=output_schema_identity_sha256,
    )


def validate_backend_runtime_validation_record(
    value: Any, *, expected_semantic_sha256: str,
    expected_request_ref: Mapping[str, Any], expected_request_sha256: str,
    expected_coordinate: Mapping[str, Any],
    expected_qualification_index_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_raw_evidence_ref: Mapping[str, Any],
    expected_runtime_authority_ref: Mapping[str, Any],
    expected_runtime_authority_sha256: str,
    expected_validator_authority_ref: Mapping[str, Any],
    expected_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_validation_protocol_identity_sha256: str,
    expected_input_schema_identity_sha256: str,
    expected_output_schema_identity_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _RECORD_FIELDS,
             "validation record fields drifted")
    _require(value.get("schema_version") == 1
             and value.get("artifact_kind")
             == "vast_backend_runtime_cell_validation_record",
             "validation record header drifted")
    coordinate = _coordinate({key: value.get(key) for key in COORDINATE_FIELDS})
    references = {
        field: _ref(value.get(field), field)
        for field in ("request_ref", "raw_evidence_ref", "runtime_authority_ref",
                      "validator_authority_ref", "runner_authority_ref")
    }
    _upstream(value.get("upstream_identities"))
    for field in (
        "request_sha256", "qualification_index_sha256",
        "runtime_authority_sha256", "validator_authority_sha256",
        "runner_authority_sha256", "runner_invocation_identity_sha256",
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256", "validation_record_sha256",
    ):
        _sha(value.get(field), field)
    result = value.get("replay_result")
    _require(type(result) is dict and set(result) == _REPLAY_RESULT_FIELDS,
             "validation replay result fields drifted")
    _require(result == {
        "record_status": "qualified", "accepted": True,
        "synthetic": False, "nonpublication": False,
        "publication_capable": True,
        "deterministic_replay_completed": True, "blocker_codes": [],
    }, "validation replay result is not qualified")
    _require(references["request_ref"]["content_identity_sha256"]
             == value["request_sha256"]
             and references["runtime_authority_ref"]["content_identity_sha256"]
             == value["runtime_authority_sha256"]
             and references["validator_authority_ref"]["content_identity_sha256"]
             == value["validator_authority_sha256"]
             and references["runner_authority_ref"]["content_identity_sha256"]
             == value["runner_authority_sha256"],
             "validation record artifact semantic cross-binding drifted")
    expected = {
        "request_ref": expected_request_ref, "request_sha256": expected_request_sha256,
        "qualification_index_sha256": expected_qualification_index_sha256,
        "upstream_identities": expected_upstream_identities,
        "raw_evidence_ref": expected_raw_evidence_ref,
        "runtime_authority_ref": expected_runtime_authority_ref,
        "runtime_authority_sha256": expected_runtime_authority_sha256,
        "validator_authority_ref": expected_validator_authority_ref,
        "validator_authority_sha256": expected_validator_authority_sha256,
        "runner_authority_ref": expected_runner_authority_ref,
        "runner_authority_sha256": expected_runner_authority_sha256,
        "runner_invocation_identity_sha256": expected_runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": expected_validation_protocol_identity_sha256,
        "input_schema_identity_sha256": expected_input_schema_identity_sha256,
        "output_schema_identity_sha256": expected_output_schema_identity_sha256,
    }
    _require(coordinate == _coordinate(dict(expected_coordinate))
             and all(value.get(key) == item for key, item in expected.items()),
             "validation record external trust pin drifted")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "validation_record_sha256"}
    _require(value.get("validation_record_sha256") == canonical_identity(unsigned)
             == _sha(expected_semantic_sha256, "expected validation record"),
             "validation record semantic identity drifted")
    return copy.deepcopy(value)


_SHARD_ENTRY_FIELDS = frozenset({*COORDINATE_FIELDS, "validation_record_ref"})
_SHARD_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "context_ref",
    "context_sha256", "validation_record_refs",
    "validation_record_set_sha256", "system_shard_sha256",
})


def _shard_entries(value: Any, system: str) -> list[dict[str, Any]]:
    _require(type(value) is list and len(value) == 140,
             "system shard requires exactly 140 record references")
    checked: list[dict[str, Any]] = []
    expected_start = SYSTEMS.index(system) * 140
    for offset, item in enumerate(value):
        _require(type(item) is dict and set(item) == _SHARD_ENTRY_FIELDS,
                 "system shard entry fields drifted")
        coordinate = _coordinate({key: item.get(key) for key in COORDINATE_FIELDS})
        _require(coordinate["system"] == system
                 and coordinate["cell_index"] == expected_start + offset,
                 "system shard record order/coverage drifted")
        checked.append({**coordinate,
                        "validation_record_ref": _ref(
                            item.get("validation_record_ref"), "validation record"
                        )})
    _require_unique_ref_identities(
        [item["validation_record_ref"] for item in checked],
        "validation record reference",
    )
    return checked


def build_backend_runtime_validation_system_shard(
    *, system: str, context_ref: Mapping[str, Any], context_sha256: str,
    validation_record_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _require(system in SYSTEMS, "system shard system is invalid")
    entries = _shard_entries(list(validation_record_refs), system)
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validation_system_shard",
        "system": system, "context_ref": _ref(context_ref, "context"),
        "context_sha256": _sha(context_sha256, "context"),
        "validation_record_refs": entries,
        "validation_record_set_sha256": canonical_identity(entries),
    }
    value["system_shard_sha256"] = canonical_identity(value)
    return validate_backend_runtime_validation_system_shard(
        value, expected_semantic_sha256=value["system_shard_sha256"],
        expected_system=system, expected_context_ref=context_ref,
        expected_context_sha256=context_sha256,
        expected_validation_record_refs=entries,
        expected_validation_record_set_sha256=value[
            "validation_record_set_sha256"
        ],
    )


def validate_backend_runtime_validation_system_shard(
    value: Any, *, expected_semantic_sha256: str, expected_system: str,
    expected_context_ref: Mapping[str, Any], expected_context_sha256: str,
    expected_validation_record_refs: Sequence[Mapping[str, Any]],
    expected_validation_record_set_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _SHARD_FIELDS,
             "system shard fields drifted")
    _require(value.get("schema_version") == 1
             and value.get("artifact_kind")
             == "vast_backend_runtime_validation_system_shard"
             and value.get("system") in SYSTEMS, "system shard header drifted")
    entries = _shard_entries(value.get("validation_record_refs"), value["system"])
    context_checked = _ref(value.get("context_ref"), "context")
    for field in ("context_sha256", "validation_record_set_sha256",
                  "system_shard_sha256"):
        _sha(value.get(field), field)
    _require(context_checked["content_identity_sha256"] == value["context_sha256"],
             "system shard context semantic cross-binding drifted")
    _require(value["system"] == expected_system
             and value["context_ref"] == expected_context_ref
             and value["context_sha256"] == expected_context_sha256
             and entries == _shard_entries(list(expected_validation_record_refs), expected_system)
             and value["validation_record_set_sha256"]
             == canonical_identity(entries)
             == expected_validation_record_set_sha256,
             "system shard external trust pin drifted")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "system_shard_sha256"}
    _require(value["system_shard_sha256"] == canonical_identity(unsigned)
             == expected_semantic_sha256, "system shard semantic identity drifted")
    return copy.deepcopy(value)


_INDEX_SHARD_FIELDS = frozenset({
    "system", "system_shard_ref", "validation_record_set_sha256",
})
_INDEX_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "validation_records_authenticated",
    "qualification_index_ref", "qualification_index_sha256",
    "upstream_identities", "validator_authority_ref",
    "validator_authority_sha256", "runner_authority_ref",
    "runner_authority_sha256", "runner_invocation_identity_sha256",
    "validation_protocol_identity_sha256", "input_schema_identity_sha256",
    "output_schema_identity_sha256", "system_shards",
    "system_shard_set_sha256", "validation_record_global_set_sha256",
    "coverage", "index_sha256",
})


def _index_shards(value: Any) -> list[dict[str, Any]]:
    _require(type(value) is list and len(value) == 4,
             "validation index requires four system shards")
    checked = []
    for position, item in enumerate(value):
        _require(type(item) is dict and set(item) == _INDEX_SHARD_FIELDS,
                 "validation index shard fields drifted")
        _require(item.get("system") == SYSTEMS[position],
                 "validation index shard order drifted")
        checked.append({
            "system": item["system"],
            "system_shard_ref": _ref(item.get("system_shard_ref"), "system shard"),
            "validation_record_set_sha256": _sha(
                item.get("validation_record_set_sha256"), "record set"
            ),
        })
    _require_unique_ref_identities(
        [item["system_shard_ref"] for item in checked],
        "system shard reference",
    )
    return checked


def build_backend_runtime_validation_index(
    *, qualification_index_ref: Mapping[str, Any],
    qualification_index_sha256: str, upstream_identities: Mapping[str, Any],
    validator_authority_ref: Mapping[str, Any], validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    runner_invocation_identity_sha256: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str, output_schema_identity_sha256: str,
    system_shard_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    shards = _index_shards(list(system_shard_refs))
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validation_record_set_index",
        "status": "persisted_for_deterministic_replay",
        "authorization_eligible": False, "execution_authorized": False,
        "validation_records_authenticated": False,
        "qualification_index_ref": _ref(
            qualification_index_ref, "qualification index"
        ),
        "qualification_index_sha256": qualification_index_sha256,
        "upstream_identities": copy.deepcopy(dict(upstream_identities)),
        "validator_authority_ref": _ref(validator_authority_ref, "validator authority"),
        "validator_authority_sha256": validator_authority_sha256,
        "runner_authority_ref": _ref(runner_authority_ref, "runner authority"),
        "runner_authority_sha256": runner_authority_sha256,
        "runner_invocation_identity_sha256": runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
        "system_shards": shards,
        "system_shard_set_sha256": canonical_identity(shards),
        "validation_record_global_set_sha256": canonical_identity([
            item["validation_record_set_sha256"] for item in shards
        ]),
        "coverage": {
            "system_count": 4, "cells_per_system": 140,
            "validation_record_count": 560,
        },
    }
    value["index_sha256"] = canonical_identity(value)
    return validate_backend_runtime_validation_index(
        value, expected_semantic_sha256=value["index_sha256"],
        expected_qualification_index_ref=qualification_index_ref,
        expected_qualification_index_sha256=qualification_index_sha256,
        expected_upstream_identities=upstream_identities,
        expected_validator_authority_ref=validator_authority_ref,
        expected_validator_authority_sha256=validator_authority_sha256,
        expected_runner_authority_ref=runner_authority_ref,
        expected_runner_authority_sha256=runner_authority_sha256,
        expected_runner_invocation_identity_sha256=runner_invocation_identity_sha256,
        expected_validation_protocol_identity_sha256=validation_protocol_identity_sha256,
        expected_input_schema_identity_sha256=input_schema_identity_sha256,
        expected_output_schema_identity_sha256=output_schema_identity_sha256,
        expected_system_shard_refs=shards,
        expected_system_shard_set_sha256=value["system_shard_set_sha256"],
        expected_validation_record_global_set_sha256=value[
            "validation_record_global_set_sha256"
        ],
    )


def validate_backend_runtime_validation_index(
    value: Any, *, expected_semantic_sha256: str,
    expected_qualification_index_ref: Mapping[str, Any],
    expected_qualification_index_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_validator_authority_ref: Mapping[str, Any],
    expected_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_validation_protocol_identity_sha256: str,
    expected_input_schema_identity_sha256: str,
    expected_output_schema_identity_sha256: str,
    expected_system_shard_refs: Sequence[Mapping[str, Any]],
    expected_system_shard_set_sha256: str,
    expected_validation_record_global_set_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _INDEX_FIELDS,
             "validation index fields drifted")
    _require(value.get("schema_version") == 1
             and value.get("artifact_kind")
             == "vast_backend_runtime_validation_record_set_index"
             and value.get("status") == "persisted_for_deterministic_replay",
             "validation index header drifted")
    _require(value.get("authorization_eligible") is False
             and value.get("execution_authorized") is False
             and value.get("validation_records_authenticated") is False,
             "validation index made an authorizing claim")
    shards = _index_shards(value.get("system_shards"))
    qualification_ref = _ref(value.get("qualification_index_ref"), "qualification index")
    validator_ref = _ref(value.get("validator_authority_ref"), "validator authority")
    runner_ref = _ref(value.get("runner_authority_ref"), "runner authority")
    _upstream(value.get("upstream_identities"))
    for field in (
        "qualification_index_sha256", "validator_authority_sha256",
        "runner_authority_sha256", "runner_invocation_identity_sha256",
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256", "system_shard_set_sha256",
        "validation_record_global_set_sha256", "index_sha256",
    ):
        _sha(value.get(field), field)
    _require(qualification_ref["content_identity_sha256"]
             == value["qualification_index_sha256"]
             and validator_ref["content_identity_sha256"]
             == value["validator_authority_sha256"]
             and runner_ref["content_identity_sha256"]
             == value["runner_authority_sha256"],
             "validation index artifact semantic cross-binding drifted")
    _require(value.get("coverage") == {
        "system_count": 4, "cells_per_system": 140,
        "validation_record_count": 560,
    }, "validation index coverage drifted")
    expected = {
        "qualification_index_ref": expected_qualification_index_ref,
        "qualification_index_sha256": expected_qualification_index_sha256,
        "upstream_identities": expected_upstream_identities,
        "validator_authority_ref": expected_validator_authority_ref,
        "validator_authority_sha256": expected_validator_authority_sha256,
        "runner_authority_ref": expected_runner_authority_ref,
        "runner_authority_sha256": expected_runner_authority_sha256,
        "runner_invocation_identity_sha256": expected_runner_invocation_identity_sha256,
        "validation_protocol_identity_sha256": expected_validation_protocol_identity_sha256,
        "input_schema_identity_sha256": expected_input_schema_identity_sha256,
        "output_schema_identity_sha256": expected_output_schema_identity_sha256,
    }
    _require(all(value.get(key) == item for key, item in expected.items())
             and shards == _index_shards(list(expected_system_shard_refs)),
             "validation index external trust pin drifted")
    expected_shards_sha = canonical_identity(shards)
    expected_records_sha = canonical_identity([
        item["validation_record_set_sha256"] for item in shards
    ])
    _require(value.get("system_shard_set_sha256") == expected_shards_sha
             == expected_system_shard_set_sha256
             and value.get("validation_record_global_set_sha256")
             == expected_records_sha == expected_validation_record_global_set_sha256,
             "validation index set identity drifted")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "index_sha256"}
    _require(value.get("index_sha256") == canonical_identity(unsigned)
             == expected_semantic_sha256,
             "validation index semantic identity drifted")
    return copy.deepcopy(value)


__all__ = [
    "SYSTEMS", "CODECS", "TOPOLOGIES", "POLICIES", "DEADLINES_MS",
    "COORDINATE_FIELDS", "UPSTREAM_IDENTITY_FIELDS",
    "BackendRuntimeValidationRecordError", "canonical_identity",
    "build_backend_runtime_validation_system_context",
    "validate_backend_runtime_validation_system_context",
    "build_backend_runtime_validation_request",
    "validate_backend_runtime_validation_request",
    "build_backend_runtime_validation_record",
    "validate_backend_runtime_validation_record",
    "build_backend_runtime_validation_system_shard",
    "validate_backend_runtime_validation_system_shard",
    "build_backend_runtime_validation_index",
    "validate_backend_runtime_validation_index",
]
