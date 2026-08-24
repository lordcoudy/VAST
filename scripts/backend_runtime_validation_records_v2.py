#!/usr/bin/env python3
"""Pure, closed validation-record graph for Q4 and caller-bound ABI v3."""
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

SCHEMA_VERSION = 2
CONTEXT_KIND = "vast_backend_runtime_validation_system_context_v2"
REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RECORD_KIND = "vast_backend_runtime_cell_validation_record_v2"
SHARD_KIND = "vast_backend_runtime_validation_system_shard_v2"
INDEX_KIND = "vast_backend_runtime_validation_record_set_index_v2"
Q4_INPUT_SCHEMA_VERSION = 4
Q4_INPUT_KIND = "vast_backend_runtime_qualification_v4_input_index"
Q4_VALIDATOR_SCHEMA_VERSION = 1
Q4_VALIDATOR_KIND = "vast_backend_runtime_validator_authority_q4"
RUNNER_AUTHORITY_SCHEMA_VERSION = 1
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_validation_runner_authority"
ABI_V3_SCHEMA_VERSION = 3
ABI_V3_KIND = "vast_backend_publication_launcher_invocation_v3"
LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION = 1
LAUNCHER_RUNTIME_AUTHORITY_KIND = (
    "vast_backend_publication_launcher_runtime_authority"
)
RUNTIME_AUTHORITY_SCHEMA_VERSION = 2
RUNTIME_AUTHORITY_KIND = "vast_backend_publication_runtime_authority_v2"

_SHA_PATTERN = r"[0-9a-f]{64}"
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_REF_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind",
    "descriptor", "content_identity_sha256",
})


class BackendRuntimeValidationRecordV2Error(ValueError):
    """A Q4 validation-record node is malformed or cross-bound incorrectly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeValidationRecordV2Error(message)


def canonical_identity(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeValidationRecordV2Error(
            "validation-record v2 node is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str
             and re.fullmatch(_SHA_PATTERN, value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _path(value: Any, label: str) -> str:
    _require(
        type(value) is str and bool(value)
        and not value.startswith(("/", "\\")) and not value.endswith("/")
        and "\\" not in value and ":" not in value and "\x00" not in value
        and "//" not in value,
        f"{label} path is unsafe",
    )
    parts = value.split("/")
    _require(all(
        part not in ("", ".", "..") and not part.endswith((".", " "))
        and not any(ord(character) < 32 for character in part)
        and part.split(".", 1)[0].upper() not in _RESERVED
        for part in parts
    ), f"{label} path is unsafe")
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and 0 < size <= 8 * 1024 * 1024 * 1024,
             f"{label} size is invalid")
    return {
        "path": _path(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _ref(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REF_FIELDS,
             f"{label} reference fields drifted")
    return {
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic"
        ),
    }


def _typed_ref(
    value: Any, label: str, *, schema_version: int, artifact_kind: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _TYPED_REF_FIELDS,
             f"{label} typed reference fields drifted")
    _require(type(value.get("artifact_schema_version")) is int
             and value.get("artifact_schema_version") == schema_version,
             f"{label} artifact schema version drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == artifact_kind,
             f"{label} artifact kind drifted")
    checked = _ref({
        "descriptor": value.get("descriptor"),
        "content_identity_sha256": value.get("content_identity_sha256"),
    }, label)
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        **checked,
    }


def _pinned_ref(
    value: Any, pin: Any, label: str, *, schema_version: int,
    artifact_kind: str,
) -> tuple[dict[str, Any], str]:
    checked = _typed_ref(
        value, label, schema_version=schema_version, artifact_kind=artifact_kind,
    )
    identity = _sha(pin, label)
    _require(checked["content_identity_sha256"] == identity,
             f"{label} reference semantic identity drifted")
    return checked, identity


def _deadline_position(value: Any) -> int:
    _require(type(value) in {int, float} and math.isfinite(float(value)),
             "deadline type drifted")
    matches = [
        position for position, expected in enumerate(DEADLINES_MS)
        if type(value) is type(expected) and value == expected
    ]
    _require(len(matches) == 1, "deadline value/type drifted")
    return matches[0]


def _coordinate(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == set(COORDINATE_FIELDS),
             "coordinate fields drifted")
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    deadline = value.get("deadline_ms")
    cell_index = value.get("cell_index")
    _require(type(system) is str and system in SYSTEMS
             and type(codec) is str and codec in CODECS
             and type(topology) is str and topology in TOPOLOGIES
             and type(policy) is str and policy in POLICIES,
             "coordinate value drifted")
    deadline_position = _deadline_position(deadline)
    expected_index = (((
        (SYSTEMS.index(system) * len(CODECS) + CODECS.index(codec))
        * len(TOPOLOGIES) + TOPOLOGIES.index(topology)
    ) * len(POLICIES) + POLICIES.index(policy)
    ) * len(DEADLINES_MS) + deadline_position)
    _require(type(cell_index) is int and cell_index == expected_index,
             "cell index does not match global coordinate ordinal")
    return {field: copy.deepcopy(value[field]) for field in COORDINATE_FIELDS}


def _coordinate_for_index(cell_index: int) -> dict[str, Any]:
    _require(type(cell_index) is int and 0 <= cell_index < 560,
             "cell index is invalid")
    remaining, deadline_position = divmod(cell_index, len(DEADLINES_MS))
    remaining, policy_position = divmod(remaining, len(POLICIES))
    remaining, topology_position = divmod(remaining, len(TOPOLOGIES))
    system_codec_position, codec_position = divmod(remaining, len(CODECS))
    return {
        "system": SYSTEMS[system_codec_position],
        "codec": CODECS[codec_position],
        "topology_kind": TOPOLOGIES[topology_position],
        "policy": POLICIES[policy_position],
        "deadline_ms": DEADLINES_MS[deadline_position],
        "cell_index": cell_index,
    }


def coordinate_for_cell_index_v2(cell_index: int) -> dict[str, Any]:
    """Return the sole canonical coordinate for one global Q4 cell ordinal."""
    return _coordinate_for_index(cell_index)


_GLOBAL_FIELDS = frozenset({
    "q4_input_ref", "q4_input_sha256",
    "q4_validator_authority_ref", "q4_validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256",
    "runner_invocation_identity_sha256",
})
_SYSTEM_BINDING_FIELDS = frozenset({
    "runtime_binding_identity_v4_sha256", "runtime_authority_set_sha256",
    "launcher_runtime_authority_ref", "launcher_runtime_authority_sha256",
})


def _global_bindings(
    *, q4_input_ref: Any, q4_input_sha256: Any,
    q4_validator_authority_ref: Any, q4_validator_authority_sha256: Any,
    runner_authority_ref: Any, runner_authority_sha256: Any,
    publication_launcher_invocation_v3_ref: Any,
    publication_launcher_invocation_v3_sha256: Any,
    runner_invocation_identity_sha256: Any,
) -> dict[str, Any]:
    q4_ref, q4_sha = _pinned_ref(
        q4_input_ref, q4_input_sha256, "Q4 input",
        schema_version=Q4_INPUT_SCHEMA_VERSION, artifact_kind=Q4_INPUT_KIND,
    )
    validator_ref, validator_sha = _pinned_ref(
        q4_validator_authority_ref, q4_validator_authority_sha256,
        "Q4 validator authority", schema_version=Q4_VALIDATOR_SCHEMA_VERSION,
        artifact_kind=Q4_VALIDATOR_KIND,
    )
    runner_ref, runner_sha = _pinned_ref(
        runner_authority_ref, runner_authority_sha256, "runner authority",
        schema_version=RUNNER_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNNER_AUTHORITY_KIND,
    )
    abi_ref, abi_sha = _pinned_ref(
        publication_launcher_invocation_v3_ref,
        publication_launcher_invocation_v3_sha256,
        "publication launcher invocation v3",
        schema_version=ABI_V3_SCHEMA_VERSION, artifact_kind=ABI_V3_KIND,
    )
    return {
        "q4_input_ref": q4_ref, "q4_input_sha256": q4_sha,
        "q4_validator_authority_ref": validator_ref,
        "q4_validator_authority_sha256": validator_sha,
        "runner_authority_ref": runner_ref,
        "runner_authority_sha256": runner_sha,
        "publication_launcher_invocation_v3_ref": abi_ref,
        "publication_launcher_invocation_v3_sha256": abi_sha,
        "runner_invocation_identity_sha256": _sha(
            runner_invocation_identity_sha256, "runner invocation identity"
        ),
    }


def _system_bindings(
    *, runtime_binding_identity_v4_sha256: Any,
    runtime_authority_set_sha256: Any,
    launcher_runtime_authority_ref: Any,
    launcher_runtime_authority_sha256: Any,
) -> dict[str, Any]:
    launcher_ref, launcher_sha = _pinned_ref(
        launcher_runtime_authority_ref, launcher_runtime_authority_sha256,
        "launcher runtime authority",
        schema_version=LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=LAUNCHER_RUNTIME_AUTHORITY_KIND,
    )
    return {
        "runtime_binding_identity_v4_sha256": _sha(
            runtime_binding_identity_v4_sha256, "runtime binding v4"
        ),
        "runtime_authority_set_sha256": _sha(
            runtime_authority_set_sha256, "runtime authority set"
        ),
        "launcher_runtime_authority_ref": launcher_ref,
        "launcher_runtime_authority_sha256": launcher_sha,
    }


def _global_from_value(value: Mapping[str, Any]) -> dict[str, Any]:
    return _global_bindings(**{field: value.get(field) for field in _GLOBAL_FIELDS})


def _system_from_value(value: Mapping[str, Any]) -> dict[str, Any]:
    return _system_bindings(**{
        field: value.get(field) for field in _SYSTEM_BINDING_FIELDS
    })


def _expected_global(
    *, expected_q4_input_ref: Any, expected_q4_input_sha256: Any,
    expected_q4_validator_authority_ref: Any,
    expected_q4_validator_authority_sha256: Any,
    expected_runner_authority_ref: Any, expected_runner_authority_sha256: Any,
    expected_publication_launcher_invocation_v3_ref: Any,
    expected_publication_launcher_invocation_v3_sha256: Any,
    expected_runner_invocation_identity_sha256: Any,
) -> dict[str, Any]:
    return _global_bindings(
        q4_input_ref=expected_q4_input_ref,
        q4_input_sha256=expected_q4_input_sha256,
        q4_validator_authority_ref=expected_q4_validator_authority_ref,
        q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        runner_authority_ref=expected_runner_authority_ref,
        runner_authority_sha256=expected_runner_authority_sha256,
        publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    )


def _expected_system(
    *, expected_runtime_binding_identity_v4_sha256: Any,
    expected_runtime_authority_set_sha256: Any,
    expected_launcher_runtime_authority_ref: Any,
    expected_launcher_runtime_authority_sha256: Any,
) -> dict[str, Any]:
    return _system_bindings(
        runtime_binding_identity_v4_sha256=(
            expected_runtime_binding_identity_v4_sha256
        ),
        runtime_authority_set_sha256=expected_runtime_authority_set_sha256,
        launcher_runtime_authority_ref=(
            expected_launcher_runtime_authority_ref
        ),
        launcher_runtime_authority_sha256=(
            expected_launcher_runtime_authority_sha256
        ),
    )


def _unsigned_identity(value: Mapping[str, Any], identity_field: str) -> str:
    return canonical_identity({
        field: copy.deepcopy(item) for field, item in value.items()
        if field != identity_field
    })


def _typed_ref_for_node(
    value: Any, label: str, *, kind: str,
) -> dict[str, Any]:
    return _typed_ref(
        value, label, schema_version=SCHEMA_VERSION, artifact_kind=kind,
    )


_CONTEXT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system",
    *_GLOBAL_FIELDS, *_SYSTEM_BINDING_FIELDS, "context_sha256",
})


def build_backend_runtime_validation_system_context_v2(
    *, system: str, q4_input_ref: Mapping[str, Any], q4_input_sha256: str,
    q4_validator_authority_ref: Mapping[str, Any],
    q4_validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_sha256: str,
    runner_invocation_identity_sha256: str,
    runtime_binding_identity_v4_sha256: str,
    runtime_authority_set_sha256: str,
    launcher_runtime_authority_ref: Mapping[str, Any],
    launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(system) is str and system in SYSTEMS,
             "system context system is invalid")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": CONTEXT_KIND,
        "system": system,
        **_global_bindings(
            q4_input_ref=q4_input_ref, q4_input_sha256=q4_input_sha256,
            q4_validator_authority_ref=q4_validator_authority_ref,
            q4_validator_authority_sha256=q4_validator_authority_sha256,
            runner_authority_ref=runner_authority_ref,
            runner_authority_sha256=runner_authority_sha256,
            publication_launcher_invocation_v3_ref=(
                publication_launcher_invocation_v3_ref
            ),
            publication_launcher_invocation_v3_sha256=(
                publication_launcher_invocation_v3_sha256
            ),
            runner_invocation_identity_sha256=(
                runner_invocation_identity_sha256
            ),
        ),
        **_system_bindings(
            runtime_binding_identity_v4_sha256=(
                runtime_binding_identity_v4_sha256
            ),
            runtime_authority_set_sha256=runtime_authority_set_sha256,
            launcher_runtime_authority_ref=launcher_runtime_authority_ref,
            launcher_runtime_authority_sha256=(
                launcher_runtime_authority_sha256
            ),
        ),
    }
    value["context_sha256"] = canonical_identity(value)
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"], value["context_sha256"],
        ],
    )
    return copy.deepcopy(value)


def validate_backend_runtime_validation_system_context_v2(
    value: Any, *, expected_semantic_sha256: str, expected_system: str,
    expected_q4_input_ref: Mapping[str, Any], expected_q4_input_sha256: str,
    expected_q4_validator_authority_ref: Mapping[str, Any],
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_ref: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_launcher_runtime_authority_ref: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _CONTEXT_FIELDS,
             "system context v2 fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and value.get("artifact_kind") == CONTEXT_KIND,
             "system context v2 header drifted")
    _require(type(expected_system) is str and expected_system in SYSTEMS
             and value.get("system") == expected_system,
             "system context v2 system drifted")
    actual_global = _global_from_value(value)
    actual_system = _system_from_value(value)
    expected_global = _expected_global(
        expected_q4_input_ref=expected_q4_input_ref,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_ref=(
            expected_q4_validator_authority_ref
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_ref=expected_runner_authority_ref,
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    )
    expected_system_bindings = _expected_system(
        expected_runtime_binding_identity_v4_sha256=(
            expected_runtime_binding_identity_v4_sha256
        ),
        expected_runtime_authority_set_sha256=(
            expected_runtime_authority_set_sha256
        ),
        expected_launcher_runtime_authority_ref=(
            expected_launcher_runtime_authority_ref
        ),
        expected_launcher_runtime_authority_sha256=(
            expected_launcher_runtime_authority_sha256
        ),
    )
    _require(actual_global == expected_global
             and actual_system == expected_system_bindings,
             "system context v2 external trust pin drifted")
    context_sha = _sha(value.get("context_sha256"), "system context v2")
    _require(context_sha == _unsigned_identity(value, "context_sha256")
             == _sha(expected_semantic_sha256, "expected system context v2"),
             "system context v2 semantic identity drifted")
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"], context_sha,
        ],
    )
    return copy.deepcopy(value)


_REQUEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", *COORDINATE_FIELDS,
    "context_ref", "context_sha256", "runtime_authority_ref",
    "runtime_authority_sha256", "raw_evidence_ref",
    *_GLOBAL_FIELDS, *_SYSTEM_BINDING_FIELDS, "request_sha256",
})


def build_backend_runtime_validation_request_v2(
    *, system: str, codec: str, topology_kind: str, policy: str,
    deadline_ms: int | float, cell_index: int,
    context_ref: Mapping[str, Any],
    runtime_authority_ref: Mapping[str, Any], runtime_authority_sha256: str,
    raw_evidence_ref: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any], q4_input_sha256: str,
    q4_validator_authority_ref: Mapping[str, Any],
    q4_validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_sha256: str,
    runner_invocation_identity_sha256: str,
    runtime_binding_identity_v4_sha256: str,
    runtime_authority_set_sha256: str,
    launcher_runtime_authority_ref: Mapping[str, Any],
    launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    coordinate = _coordinate({
        "system": system, "codec": codec, "topology_kind": topology_kind,
        "policy": policy, "deadline_ms": deadline_ms,
        "cell_index": cell_index,
    })
    context = _typed_ref_for_node(context_ref, "system context", kind=CONTEXT_KIND)
    authority, authority_sha = _pinned_ref(
        runtime_authority_ref, runtime_authority_sha256, "runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": REQUEST_KIND,
        **coordinate, "context_ref": context,
        "context_sha256": context["content_identity_sha256"],
        "runtime_authority_ref": authority,
        "runtime_authority_sha256": authority_sha,
        "raw_evidence_ref": _ref(raw_evidence_ref, "raw evidence"),
        **_global_bindings(
            q4_input_ref=q4_input_ref, q4_input_sha256=q4_input_sha256,
            q4_validator_authority_ref=q4_validator_authority_ref,
            q4_validator_authority_sha256=q4_validator_authority_sha256,
            runner_authority_ref=runner_authority_ref,
            runner_authority_sha256=runner_authority_sha256,
            publication_launcher_invocation_v3_ref=(
                publication_launcher_invocation_v3_ref
            ),
            publication_launcher_invocation_v3_sha256=(
                publication_launcher_invocation_v3_sha256
            ),
            runner_invocation_identity_sha256=(
                runner_invocation_identity_sha256
            ),
        ),
        **_system_bindings(
            runtime_binding_identity_v4_sha256=(
                runtime_binding_identity_v4_sha256
            ),
            runtime_authority_set_sha256=runtime_authority_set_sha256,
            launcher_runtime_authority_ref=launcher_runtime_authority_ref,
            launcher_runtime_authority_sha256=(
                launcher_runtime_authority_sha256
            ),
        ),
    }
    value["request_sha256"] = canonical_identity(value)
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["context_ref"],
            value["runtime_authority_ref"], value["raw_evidence_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"], value["request_sha256"],
        ],
    )
    return copy.deepcopy(value)


def validate_backend_runtime_validation_request_v2(
    value: Any, *, expected_semantic_sha256: str,
    expected_coordinate: Mapping[str, Any],
    expected_context_ref: Mapping[str, Any],
    expected_runtime_authority_ref: Mapping[str, Any],
    expected_runtime_authority_sha256: str,
    expected_raw_evidence_ref: Mapping[str, Any],
    expected_q4_input_ref: Mapping[str, Any], expected_q4_input_sha256: str,
    expected_q4_validator_authority_ref: Mapping[str, Any],
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_ref: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_launcher_runtime_authority_ref: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REQUEST_FIELDS,
             "validation request v2 fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and value.get("artifact_kind") == REQUEST_KIND,
             "validation request v2 header drifted")
    coordinate = _coordinate({
        field: value.get(field) for field in COORDINATE_FIELDS
    })
    _require(coordinate == _coordinate(dict(expected_coordinate)),
             "validation request v2 coordinate drifted")
    context = _typed_ref_for_node(
        value.get("context_ref"), "system context", kind=CONTEXT_KIND,
    )
    expected_context = _typed_ref_for_node(
        expected_context_ref, "expected system context", kind=CONTEXT_KIND,
    )
    _require(context == expected_context
             and context["content_identity_sha256"]
             == value.get("context_sha256"),
             "validation request v2 parent context drifted")
    authority, authority_sha = _pinned_ref(
        value.get("runtime_authority_ref"),
        value.get("runtime_authority_sha256"), "runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    expected_authority, expected_authority_sha = _pinned_ref(
        expected_runtime_authority_ref, expected_runtime_authority_sha256,
        "expected runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    evidence = _ref(value.get("raw_evidence_ref"), "raw evidence")
    _require(authority == expected_authority
             and authority_sha == expected_authority_sha
             and evidence == _ref(expected_raw_evidence_ref,
                                   "expected raw evidence"),
             "validation request v2 cell artifact drifted")
    _require(_global_from_value(value) == _expected_global(
        expected_q4_input_ref=expected_q4_input_ref,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_ref=(
            expected_q4_validator_authority_ref
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_ref=expected_runner_authority_ref,
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    ) and _system_from_value(value) == _expected_system(
        expected_runtime_binding_identity_v4_sha256=(
            expected_runtime_binding_identity_v4_sha256
        ),
        expected_runtime_authority_set_sha256=(
            expected_runtime_authority_set_sha256
        ),
        expected_launcher_runtime_authority_ref=(
            expected_launcher_runtime_authority_ref
        ),
        expected_launcher_runtime_authority_sha256=(
            expected_launcher_runtime_authority_sha256
        ),
    ), "validation request v2 external trust pin drifted")
    request_sha = _sha(value.get("request_sha256"), "validation request v2")
    _require(request_sha == _unsigned_identity(value, "request_sha256")
             == _sha(expected_semantic_sha256,
                     "expected validation request v2"),
             "validation request v2 semantic identity drifted")
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["context_ref"],
            value["runtime_authority_ref"], value["raw_evidence_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"], request_sha,
        ],
    )
    return copy.deepcopy(value)


_REPLAY_RESULT_FIELDS = frozenset({
    "record_status", "accepted", "synthetic", "nonpublication",
    "publication_capable", "deterministic_replay_completed", "blocker_codes",
})
QUALIFIED_REPLAY_RESULT = {
    "record_status": "qualified", "accepted": True,
    "synthetic": False, "nonpublication": False,
    "publication_capable": True,
    "deterministic_replay_completed": True, "blocker_codes": [],
}
_REPLAY_BOOL_FIELDS = (
    "accepted", "synthetic", "nonpublication", "publication_capable",
    "deterministic_replay_completed",
)


def _qualified_replay_result(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REPLAY_RESULT_FIELDS,
             "validation replay result v2 fields drifted")
    _require(type(value.get("record_status")) is str
             and value.get("record_status") == "qualified"
             and all(type(value.get(field)) is bool
                     for field in _REPLAY_BOOL_FIELDS)
             and type(value.get("blocker_codes")) is list
             and value.get("blocker_codes") == []
             and value == QUALIFIED_REPLAY_RESULT,
             "validation replay result v2 is not qualified")
    return copy.deepcopy(value)


_RECORD_FIELDS = frozenset({
    "schema_version", "artifact_kind", *COORDINATE_FIELDS,
    "authorization_eligible", "execution_authorized",
    "validation_records_authenticated",
    "request_ref", "request_sha256",
    "runtime_authority_ref", "runtime_authority_sha256", "raw_evidence_ref",
    *_GLOBAL_FIELDS, *_SYSTEM_BINDING_FIELDS,
    "replay_result", "validation_record_sha256",
})


def build_backend_runtime_validation_record_v2(
    *, system: str, codec: str, topology_kind: str, policy: str,
    deadline_ms: int | float, cell_index: int,
    request_ref: Mapping[str, Any],
    runtime_authority_ref: Mapping[str, Any], runtime_authority_sha256: str,
    raw_evidence_ref: Mapping[str, Any], replay_result: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any], q4_input_sha256: str,
    q4_validator_authority_ref: Mapping[str, Any],
    q4_validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_sha256: str,
    runner_invocation_identity_sha256: str,
    runtime_binding_identity_v4_sha256: str,
    runtime_authority_set_sha256: str,
    launcher_runtime_authority_ref: Mapping[str, Any],
    launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    coordinate = _coordinate({
        "system": system, "codec": codec, "topology_kind": topology_kind,
        "policy": policy, "deadline_ms": deadline_ms,
        "cell_index": cell_index,
    })
    request = _typed_ref_for_node(
        request_ref, "validation request", kind=REQUEST_KIND,
    )
    authority, authority_sha = _pinned_ref(
        runtime_authority_ref, runtime_authority_sha256, "runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    result = _qualified_replay_result(replay_result)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": RECORD_KIND,
        "authorization_eligible": False, "execution_authorized": False,
        "validation_records_authenticated": False,
        **coordinate, "request_ref": request,
        "request_sha256": request["content_identity_sha256"],
        "runtime_authority_ref": authority,
        "runtime_authority_sha256": authority_sha,
        "raw_evidence_ref": _ref(raw_evidence_ref, "raw evidence"),
        **_global_bindings(
            q4_input_ref=q4_input_ref, q4_input_sha256=q4_input_sha256,
            q4_validator_authority_ref=q4_validator_authority_ref,
            q4_validator_authority_sha256=q4_validator_authority_sha256,
            runner_authority_ref=runner_authority_ref,
            runner_authority_sha256=runner_authority_sha256,
            publication_launcher_invocation_v3_ref=(
                publication_launcher_invocation_v3_ref
            ),
            publication_launcher_invocation_v3_sha256=(
                publication_launcher_invocation_v3_sha256
            ),
            runner_invocation_identity_sha256=(
                runner_invocation_identity_sha256
            ),
        ),
        **_system_bindings(
            runtime_binding_identity_v4_sha256=(
                runtime_binding_identity_v4_sha256
            ),
            runtime_authority_set_sha256=runtime_authority_set_sha256,
            launcher_runtime_authority_ref=launcher_runtime_authority_ref,
            launcher_runtime_authority_sha256=(
                launcher_runtime_authority_sha256
            ),
        ),
        "replay_result": result,
    }
    value["validation_record_sha256"] = canonical_identity(value)
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["request_ref"],
            value["runtime_authority_ref"], value["raw_evidence_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"],
            value["validation_record_sha256"],
        ],
    )
    return copy.deepcopy(value)


def validate_backend_runtime_validation_record_v2(
    value: Any, *, expected_semantic_sha256: str,
    expected_coordinate: Mapping[str, Any],
    expected_request_ref: Mapping[str, Any],
    expected_runtime_authority_ref: Mapping[str, Any],
    expected_runtime_authority_sha256: str,
    expected_raw_evidence_ref: Mapping[str, Any],
    expected_q4_input_ref: Mapping[str, Any], expected_q4_input_sha256: str,
    expected_q4_validator_authority_ref: Mapping[str, Any],
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_ref: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_launcher_runtime_authority_ref: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _RECORD_FIELDS,
             "validation record v2 fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and value.get("artifact_kind") == RECORD_KIND,
             "validation record v2 header drifted")
    _require(value.get("authorization_eligible") is False
             and value.get("execution_authorized") is False
             and value.get("validation_records_authenticated") is False,
             "validation record v2 made an authorizing claim")
    coordinate = _coordinate({
        field: value.get(field) for field in COORDINATE_FIELDS
    })
    _require(coordinate == _coordinate(dict(expected_coordinate)),
             "validation record v2 coordinate drifted")
    request = _typed_ref_for_node(
        value.get("request_ref"), "validation request", kind=REQUEST_KIND,
    )
    expected_request = _typed_ref_for_node(
        expected_request_ref, "expected validation request", kind=REQUEST_KIND,
    )
    _require(request == expected_request
             and request["content_identity_sha256"]
             == value.get("request_sha256"),
             "validation record v2 parent request drifted")
    authority, authority_sha = _pinned_ref(
        value.get("runtime_authority_ref"),
        value.get("runtime_authority_sha256"), "runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    expected_authority, expected_authority_sha = _pinned_ref(
        expected_runtime_authority_ref, expected_runtime_authority_sha256,
        "expected runtime authority",
        schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=RUNTIME_AUTHORITY_KIND,
    )
    _require(authority == expected_authority
             and authority_sha == expected_authority_sha
             and _ref(value.get("raw_evidence_ref"), "raw evidence")
             == _ref(expected_raw_evidence_ref, "expected raw evidence"),
             "validation record v2 cell artifact drifted")
    _qualified_replay_result(value.get("replay_result"))
    _require(_global_from_value(value) == _expected_global(
        expected_q4_input_ref=expected_q4_input_ref,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_ref=(
            expected_q4_validator_authority_ref
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_ref=expected_runner_authority_ref,
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    ) and _system_from_value(value) == _expected_system(
        expected_runtime_binding_identity_v4_sha256=(
            expected_runtime_binding_identity_v4_sha256
        ),
        expected_runtime_authority_set_sha256=(
            expected_runtime_authority_set_sha256
        ),
        expected_launcher_runtime_authority_ref=(
            expected_launcher_runtime_authority_ref
        ),
        expected_launcher_runtime_authority_sha256=(
            expected_launcher_runtime_authority_sha256
        ),
    ), "validation record v2 external trust pin drifted")
    record_sha = _sha(value.get("validation_record_sha256"),
                      "validation record v2")
    _require(record_sha == _unsigned_identity(
        value, "validation_record_sha256"
    ) == _sha(expected_semantic_sha256, "expected validation record v2"),
             "validation record v2 semantic identity drifted")
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["request_ref"],
            value["runtime_authority_ref"], value["raw_evidence_ref"],
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"], record_sha,
        ],
    )
    return copy.deepcopy(value)


_SHARD_ENTRY_FIELDS = frozenset({*COORDINATE_FIELDS, "validation_record_ref"})
_SHARD_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "context_ref",
    "context_sha256", *_GLOBAL_FIELDS, *_SYSTEM_BINDING_FIELDS,
    "validation_record_refs", "validation_record_set_sha256",
    "system_shard_sha256",
})


def _distinct_refs(references: Sequence[Mapping[str, Any]], label: str) -> None:
    paths = [item["descriptor"]["path"].casefold() for item in references]
    files = [item["descriptor"]["sha256"] for item in references]
    contents = [item["content_identity_sha256"] for item in references]
    _require(len(paths) == len(set(paths)), f"{label} path is duplicated")
    _require(len(files) == len(set(files)),
             f"{label} file identity is duplicated")
    _require(len(contents) == len(set(contents)),
             f"{label} content identity is duplicated")


def _shard_entries(value: Any, system: str) -> list[dict[str, Any]]:
    _require(type(value) is list and len(value) == 140,
             "system shard v2 requires exactly 140 validation records")
    first = SYSTEMS.index(system) * 140
    checked: list[dict[str, Any]] = []
    for offset, item in enumerate(value):
        _require(type(item) is dict and set(item) == _SHARD_ENTRY_FIELDS,
                 "system shard v2 entry fields drifted")
        coordinate = _coordinate({
            field: item.get(field) for field in COORDINATE_FIELDS
        })
        _require(coordinate["system"] == system
                 and coordinate["cell_index"] == first + offset,
                 "system shard v2 order/coverage drifted")
        checked.append({
            **coordinate,
            "validation_record_ref": _typed_ref_for_node(
                item.get("validation_record_ref"), "validation record",
                kind=RECORD_KIND,
            ),
        })
    _distinct_refs(
        [item["validation_record_ref"] for item in checked],
        "validation record reference",
    )
    return checked


def build_backend_runtime_validation_system_shard_v2(
    *, system: str, context_ref: Mapping[str, Any],
    validation_record_refs: Sequence[Mapping[str, Any]],
    q4_input_ref: Mapping[str, Any], q4_input_sha256: str,
    q4_validator_authority_ref: Mapping[str, Any],
    q4_validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_sha256: str,
    runner_invocation_identity_sha256: str,
    runtime_binding_identity_v4_sha256: str,
    runtime_authority_set_sha256: str,
    launcher_runtime_authority_ref: Mapping[str, Any],
    launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(system) is str and system in SYSTEMS,
             "system shard v2 system is invalid")
    context = _typed_ref_for_node(
        context_ref, "system context", kind=CONTEXT_KIND,
    )
    entries = _shard_entries(list(validation_record_refs), system)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": SHARD_KIND,
        "system": system, "context_ref": context,
        "context_sha256": context["content_identity_sha256"],
        **_global_bindings(
            q4_input_ref=q4_input_ref, q4_input_sha256=q4_input_sha256,
            q4_validator_authority_ref=q4_validator_authority_ref,
            q4_validator_authority_sha256=q4_validator_authority_sha256,
            runner_authority_ref=runner_authority_ref,
            runner_authority_sha256=runner_authority_sha256,
            publication_launcher_invocation_v3_ref=(
                publication_launcher_invocation_v3_ref
            ),
            publication_launcher_invocation_v3_sha256=(
                publication_launcher_invocation_v3_sha256
            ),
            runner_invocation_identity_sha256=(
                runner_invocation_identity_sha256
            ),
        ),
        **_system_bindings(
            runtime_binding_identity_v4_sha256=(
                runtime_binding_identity_v4_sha256
            ),
            runtime_authority_set_sha256=runtime_authority_set_sha256,
            launcher_runtime_authority_ref=launcher_runtime_authority_ref,
            launcher_runtime_authority_sha256=(
                launcher_runtime_authority_sha256
            ),
        ),
        "validation_record_refs": entries,
        "validation_record_set_sha256": canonical_identity(entries),
    }
    value["system_shard_sha256"] = canonical_identity(value)
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["context_ref"],
            *(item["validation_record_ref"]
              for item in value["validation_record_refs"]),
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"],
            value["validation_record_set_sha256"],
            value["system_shard_sha256"],
        ],
    )
    return copy.deepcopy(value)


def validate_backend_runtime_validation_system_shard_v2(
    value: Any, *, expected_semantic_sha256: str, expected_system: str,
    expected_context_ref: Mapping[str, Any],
    expected_validation_record_refs: Sequence[Mapping[str, Any]],
    expected_q4_input_ref: Mapping[str, Any], expected_q4_input_sha256: str,
    expected_q4_validator_authority_ref: Mapping[str, Any],
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_ref: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256: str,
    expected_runtime_authority_set_sha256: str,
    expected_launcher_runtime_authority_ref: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _SHARD_FIELDS,
             "system shard v2 fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and value.get("artifact_kind") == SHARD_KIND
             and type(expected_system) is str and expected_system in SYSTEMS
             and value.get("system") == expected_system,
             "system shard v2 header drifted")
    context = _typed_ref_for_node(
        value.get("context_ref"), "system context", kind=CONTEXT_KIND,
    )
    expected_context = _typed_ref_for_node(
        expected_context_ref, "expected system context", kind=CONTEXT_KIND,
    )
    _require(context == expected_context
             and context["content_identity_sha256"]
             == value.get("context_sha256"),
             "system shard v2 parent context drifted")
    entries = _shard_entries(value.get("validation_record_refs"), expected_system)
    expected_entries = _shard_entries(
        list(expected_validation_record_refs), expected_system,
    )
    _require(entries == expected_entries
             and value.get("validation_record_set_sha256")
             == canonical_identity(entries),
             "system shard v2 validation-record set drifted")
    _require(_global_from_value(value) == _expected_global(
        expected_q4_input_ref=expected_q4_input_ref,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_ref=(
            expected_q4_validator_authority_ref
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_ref=expected_runner_authority_ref,
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    ) and _system_from_value(value) == _expected_system(
        expected_runtime_binding_identity_v4_sha256=(
            expected_runtime_binding_identity_v4_sha256
        ),
        expected_runtime_authority_set_sha256=(
            expected_runtime_authority_set_sha256
        ),
        expected_launcher_runtime_authority_ref=(
            expected_launcher_runtime_authority_ref
        ),
        expected_launcher_runtime_authority_sha256=(
            expected_launcher_runtime_authority_sha256
        ),
    ), "system shard v2 external trust pin drifted")
    shard_sha = _sha(value.get("system_shard_sha256"), "system shard v2")
    _require(shard_sha == _unsigned_identity(value, "system_shard_sha256")
             == _sha(expected_semantic_sha256, "expected system shard v2"),
             "system shard v2 semantic identity drifted")
    _assert_identity_namespace(
        [
            value["q4_input_ref"], value["q4_validator_authority_ref"],
            value["runner_authority_ref"],
            value["publication_launcher_invocation_v3_ref"],
            value["launcher_runtime_authority_ref"], value["context_ref"],
            *(item["validation_record_ref"] for item in entries),
        ],
        [
            value["runner_invocation_identity_sha256"],
            value["runtime_binding_identity_v4_sha256"],
            value["runtime_authority_set_sha256"],
            value["validation_record_set_sha256"], shard_sha,
        ],
    )
    return copy.deepcopy(value)


_INDEX_SHARD_FIELDS = frozenset({
    "system", "system_shard_ref", "system_shard_sha256",
    "context_ref", "context_sha256", "validation_record_set_sha256",
})
_FLAT_ENTRY_FIELDS = frozenset({"coordinate", "validation_record_ref"})
_COVERAGE_FIELDS = frozenset({
    "system_count", "cells_per_system", "validation_record_count",
})
_INDEX_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "validation_records_authenticated",
    *_GLOBAL_FIELDS, "system_shards", "system_shard_set_sha256",
    "validation_records", "validation_record_global_set_sha256",
    "coverage", "index_sha256",
})


def _system_pin_map(value: Any, label: str) -> dict[str, str]:
    _require(type(value) is dict and set(value) == set(SYSTEMS),
             f"{label} system membership drifted")
    checked = {system: _sha(value[system], f"{label} {system}")
               for system in SYSTEMS}
    _require(len(set(checked.values())) == len(SYSTEMS),
             f"{label} identities are not distinct across four systems")
    return checked


def _launcher_ref_map(value: Any) -> dict[str, dict[str, Any]]:
    _require(type(value) is dict and set(value) == set(SYSTEMS),
             "launcher runtime authority reference system membership drifted")
    checked = {
        system: _typed_ref(
            value[system], f"launcher runtime authority {system}",
            schema_version=LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION,
            artifact_kind=LAUNCHER_RUNTIME_AUTHORITY_KIND,
        )
        for system in SYSTEMS
    }
    _distinct_refs(list(checked.values()), "launcher runtime authority reference")
    return checked


def _ref_key(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )


def _global_reference_registry(
    references: Sequence[Mapping[str, Any]],
) -> None:
    by_path: dict[str, str] = {}
    by_file: dict[str, str] = {}
    by_content: dict[str, str] = {}
    for reference in references:
        encoded = _ref_key(reference)
        descriptor = reference["descriptor"]
        keys = (
            (by_path, descriptor["path"].casefold(), "path"),
            (by_file, descriptor["sha256"], "file identity"),
            (by_content, reference["content_identity_sha256"],
             "content identity"),
        )
        for registry, identity, label in keys:
            previous = registry.get(identity)
            _require(previous is None or previous == encoded,
                     f"global artifact reference {label} collision")
            registry[identity] = encoded


def _assert_identity_namespace(
    references: Sequence[Mapping[str, Any]],
    reserved_semantic_identities: Sequence[str],
) -> None:
    _global_reference_registry(references)
    reserved = [
        _sha(identity, "reserved semantic identity")
        for identity in reserved_semantic_identities
    ]
    _require(len(reserved) == len(set(reserved)),
             "reserved semantic identity is duplicated")
    contents = {reference["content_identity_sha256"]
                for reference in references}
    _require(contents.isdisjoint(reserved),
             "artifact reference forms a semantic identity cycle")


def _validate_shard_document_for_index(
    value: Any, *, expected_system: str,
    global_bindings: Mapping[str, Any],
    binding_sha: str, set_sha: str,
    launcher_ref: Mapping[str, Any], launcher_sha: str,
) -> dict[str, Any]:
    _require(type(value) is dict, "system shard v2 document is invalid")
    entries = value.get("validation_record_refs")
    return validate_backend_runtime_validation_system_shard_v2(
        value,
        expected_semantic_sha256=value.get("system_shard_sha256"),
        expected_system=expected_system,
        expected_context_ref=value.get("context_ref"),
        expected_validation_record_refs=entries,
        expected_q4_input_ref=global_bindings["q4_input_ref"],
        expected_q4_input_sha256=global_bindings["q4_input_sha256"],
        expected_q4_validator_authority_ref=(
            global_bindings["q4_validator_authority_ref"]
        ),
        expected_q4_validator_authority_sha256=(
            global_bindings["q4_validator_authority_sha256"]
        ),
        expected_runner_authority_ref=global_bindings["runner_authority_ref"],
        expected_runner_authority_sha256=(
            global_bindings["runner_authority_sha256"]
        ),
        expected_publication_launcher_invocation_v3_ref=(
            global_bindings["publication_launcher_invocation_v3_ref"]
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            global_bindings["publication_launcher_invocation_v3_sha256"]
        ),
        expected_runner_invocation_identity_sha256=(
            global_bindings["runner_invocation_identity_sha256"]
        ),
        expected_runtime_binding_identity_v4_sha256=binding_sha,
        expected_runtime_authority_set_sha256=set_sha,
        expected_launcher_runtime_authority_ref=launcher_ref,
        expected_launcher_runtime_authority_sha256=launcher_sha,
    )


def _index_material(
    *, system_shards: Sequence[Mapping[str, Any]],
    system_shard_refs: Sequence[Mapping[str, Any]],
    global_bindings: Mapping[str, Any],
    binding_pins: Mapping[str, str], set_pins: Mapping[str, str],
    launcher_refs: Mapping[str, Mapping[str, Any]],
    launcher_pins: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _require(type(system_shards) in {list, tuple} and len(system_shards) == 4,
             "validation index v2 requires four shard documents")
    _require(type(system_shard_refs) in {list, tuple}
             and len(system_shard_refs) == 4,
             "validation index v2 requires four shard references")
    checked_shards: list[dict[str, Any]] = []
    checked_refs: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for position, system in enumerate(SYSTEMS):
        shard = _validate_shard_document_for_index(
            system_shards[position], expected_system=system,
            global_bindings=global_bindings,
            binding_sha=binding_pins[system], set_sha=set_pins[system],
            launcher_ref=launcher_refs[system],
            launcher_sha=launcher_pins[system],
        )
        shard_ref = _typed_ref_for_node(
            system_shard_refs[position], "system shard", kind=SHARD_KIND,
        )
        _require(shard_ref["content_identity_sha256"]
                 == shard["system_shard_sha256"],
                 "system shard reference semantic identity drifted")
        context_ref = _typed_ref_for_node(
            shard["context_ref"], "system context", kind=CONTEXT_KIND,
        )
        checked_shards.append(shard)
        checked_refs.append({
            "system": system, "system_shard_ref": shard_ref,
            "system_shard_sha256": shard["system_shard_sha256"],
            "context_ref": context_ref,
            "context_sha256": shard["context_sha256"],
            "validation_record_set_sha256": (
                shard["validation_record_set_sha256"]
            ),
        })
        flat.extend({
            "coordinate": {
                field: copy.deepcopy(entry[field])
                for field in COORDINATE_FIELDS
            },
            "validation_record_ref": copy.deepcopy(
                entry["validation_record_ref"]
            ),
        } for entry in shard["validation_record_refs"])
    _distinct_refs(
        [item["system_shard_ref"] for item in checked_refs],
        "system shard reference",
    )
    _distinct_refs(
        [item["context_ref"] for item in checked_refs],
        "system context reference",
    )
    _distinct_refs(
        [item["validation_record_ref"] for item in flat],
        "flattened validation record reference",
    )
    _require(len(flat) == 560
             and all(item["coordinate"] == _coordinate_for_index(position)
                     for position, item in enumerate(flat)),
             "flattened validation record coverage drifted")
    global_references: list[Mapping[str, Any]] = [
        global_bindings["q4_input_ref"],
        global_bindings["q4_validator_authority_ref"],
        global_bindings["runner_authority_ref"],
        global_bindings["publication_launcher_invocation_v3_ref"],
        *launcher_refs.values(),
        *(item["system_shard_ref"] for item in checked_refs),
        *(item["context_ref"] for item in checked_refs),
        *(item["validation_record_ref"] for item in flat),
    ]
    _global_reference_registry(global_references)
    return checked_refs, flat


def build_backend_runtime_validation_index_v2(
    *, system_shards: Sequence[Mapping[str, Any]],
    system_shard_refs: Sequence[Mapping[str, Any]],
    q4_input_ref: Mapping[str, Any], q4_input_sha256: str,
    q4_validator_authority_ref: Mapping[str, Any],
    q4_validator_authority_sha256: str,
    runner_authority_ref: Mapping[str, Any], runner_authority_sha256: str,
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    publication_launcher_invocation_v3_sha256: str,
    runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256_by_system: Mapping[str, Any],
    expected_runtime_authority_set_sha256_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_ref_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256_by_system: Mapping[str, Any],
) -> dict[str, Any]:
    global_bindings = _global_bindings(
        q4_input_ref=q4_input_ref, q4_input_sha256=q4_input_sha256,
        q4_validator_authority_ref=q4_validator_authority_ref,
        q4_validator_authority_sha256=q4_validator_authority_sha256,
        runner_authority_ref=runner_authority_ref,
        runner_authority_sha256=runner_authority_sha256,
        publication_launcher_invocation_v3_ref=(
            publication_launcher_invocation_v3_ref
        ),
        publication_launcher_invocation_v3_sha256=(
            publication_launcher_invocation_v3_sha256
        ),
        runner_invocation_identity_sha256=runner_invocation_identity_sha256,
    )
    binding_pins = _system_pin_map(
        expected_runtime_binding_identity_v4_sha256_by_system,
        "runtime binding v4",
    )
    set_pins = _system_pin_map(
        expected_runtime_authority_set_sha256_by_system,
        "runtime authority set",
    )
    launcher_refs = _launcher_ref_map(
        expected_launcher_runtime_authority_ref_by_system
    )
    launcher_pins = _system_pin_map(
        expected_launcher_runtime_authority_sha256_by_system,
        "launcher runtime authority",
    )
    _require(all(launcher_refs[system]["content_identity_sha256"]
                 == launcher_pins[system] for system in SYSTEMS),
             "launcher runtime authority reference semantic identity drifted")
    shard_entries, flat = _index_material(
        system_shards=system_shards, system_shard_refs=system_shard_refs,
        global_bindings=global_bindings, binding_pins=binding_pins,
        set_pins=set_pins, launcher_refs=launcher_refs,
        launcher_pins=launcher_pins,
    )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": INDEX_KIND,
        "status": "persisted_for_deterministic_replay_v2",
        "authorization_eligible": False, "execution_authorized": False,
        "validation_records_authenticated": False,
        **global_bindings, "system_shards": shard_entries,
        "system_shard_set_sha256": canonical_identity(shard_entries),
        "validation_records": flat,
        "validation_record_global_set_sha256": canonical_identity(flat),
        "coverage": {
            "system_count": 4, "cells_per_system": 140,
            "validation_record_count": 560,
        },
    }
    value["index_sha256"] = canonical_identity(value)
    return copy.deepcopy(value)


def validate_backend_runtime_validation_index_v2(
    value: Any, *, expected_semantic_sha256: str,
    expected_system_shards: Sequence[Mapping[str, Any]],
    expected_q4_input_ref: Mapping[str, Any],
    expected_q4_input_sha256: str,
    expected_q4_validator_authority_ref: Mapping[str, Any],
    expected_q4_validator_authority_sha256: str,
    expected_runner_authority_ref: Mapping[str, Any],
    expected_runner_authority_sha256: str,
    expected_publication_launcher_invocation_v3_ref: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runner_invocation_identity_sha256: str,
    expected_runtime_binding_identity_v4_sha256_by_system: Mapping[str, Any],
    expected_runtime_authority_set_sha256_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_ref_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256_by_system: Mapping[str, Any],
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _INDEX_FIELDS,
             "validation index v2 fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and value.get("artifact_kind") == INDEX_KIND
             and value.get("status")
             == "persisted_for_deterministic_replay_v2",
             "validation index v2 header drifted")
    _require(value.get("authorization_eligible") is False
             and value.get("execution_authorized") is False
             and value.get("validation_records_authenticated") is False,
             "validation index v2 made an authorizing claim")
    global_bindings = _global_from_value(value)
    expected_global = _expected_global(
        expected_q4_input_ref=expected_q4_input_ref,
        expected_q4_input_sha256=expected_q4_input_sha256,
        expected_q4_validator_authority_ref=(
            expected_q4_validator_authority_ref
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_runner_authority_ref=expected_runner_authority_ref,
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_publication_launcher_invocation_v3_ref=(
            expected_publication_launcher_invocation_v3_ref
        ),
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runner_invocation_identity_sha256=(
            expected_runner_invocation_identity_sha256
        ),
    )
    _require(global_bindings == expected_global,
             "validation index v2 external global pin drifted")
    binding_pins = _system_pin_map(
        expected_runtime_binding_identity_v4_sha256_by_system,
        "runtime binding v4",
    )
    set_pins = _system_pin_map(
        expected_runtime_authority_set_sha256_by_system,
        "runtime authority set",
    )
    launcher_refs = _launcher_ref_map(
        expected_launcher_runtime_authority_ref_by_system
    )
    launcher_pins = _system_pin_map(
        expected_launcher_runtime_authority_sha256_by_system,
        "launcher runtime authority",
    )
    _require(all(launcher_refs[system]["content_identity_sha256"]
                 == launcher_pins[system] for system in SYSTEMS),
             "launcher runtime authority reference semantic identity drifted")
    raw_index_shards = value.get("system_shards")
    _require(type(raw_index_shards) is list and len(raw_index_shards) == 4,
             "validation index v2 system shard entries drifted")
    supplied_refs = []
    for position, item in enumerate(raw_index_shards):
        _require(type(item) is dict and set(item) == _INDEX_SHARD_FIELDS
                 and item.get("system") == SYSTEMS[position],
                 "validation index v2 shard entry drifted")
        supplied_refs.append(item.get("system_shard_ref"))
    shard_entries, flat = _index_material(
        system_shards=expected_system_shards,
        system_shard_refs=supplied_refs, global_bindings=global_bindings,
        binding_pins=binding_pins, set_pins=set_pins,
        launcher_refs=launcher_refs, launcher_pins=launcher_pins,
    )
    _require(raw_index_shards == shard_entries
             and value.get("system_shard_set_sha256")
             == canonical_identity(shard_entries),
             "validation index v2 shard commitment drifted")
    raw_flat = value.get("validation_records")
    _require(type(raw_flat) is list and len(raw_flat) == 560
             and all(type(item) is dict and set(item) == _FLAT_ENTRY_FIELDS
                     for item in raw_flat)
             and raw_flat == flat
             and value.get("validation_record_global_set_sha256")
             == canonical_identity(flat),
             "validation index v2 flattened record commitment drifted")
    coverage = value.get("coverage")
    _require(type(coverage) is dict and set(coverage) == _COVERAGE_FIELDS
             and coverage == {
                 "system_count": 4, "cells_per_system": 140,
                 "validation_record_count": 560,
             }, "validation index v2 coverage drifted")
    index_sha = _sha(value.get("index_sha256"), "validation index v2")
    _require(index_sha == _unsigned_identity(value, "index_sha256")
             == _sha(expected_semantic_sha256, "expected validation index v2"),
             "validation index v2 semantic identity drifted")
    return copy.deepcopy(value)


__all__ = [
    "SCHEMA_VERSION", "CONTEXT_KIND", "REQUEST_KIND", "RECORD_KIND",
    "SHARD_KIND", "INDEX_KIND", "Q4_INPUT_SCHEMA_VERSION", "Q4_INPUT_KIND",
    "Q4_VALIDATOR_SCHEMA_VERSION", "Q4_VALIDATOR_KIND",
    "RUNNER_AUTHORITY_SCHEMA_VERSION", "RUNNER_AUTHORITY_KIND",
    "ABI_V3_SCHEMA_VERSION", "ABI_V3_KIND",
    "LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION",
    "LAUNCHER_RUNTIME_AUTHORITY_KIND", "RUNTIME_AUTHORITY_SCHEMA_VERSION",
    "RUNTIME_AUTHORITY_KIND", "SYSTEMS", "CODECS", "TOPOLOGIES",
    "POLICIES", "DEADLINES_MS", "COORDINATE_FIELDS",
    "QUALIFIED_REPLAY_RESULT", "BackendRuntimeValidationRecordV2Error",
    "canonical_identity", "coordinate_for_cell_index_v2",
    "build_backend_runtime_validation_system_context_v2",
    "validate_backend_runtime_validation_system_context_v2",
    "build_backend_runtime_validation_request_v2",
    "validate_backend_runtime_validation_request_v2",
    "build_backend_runtime_validation_record_v2",
    "validate_backend_runtime_validation_record_v2",
    "build_backend_runtime_validation_system_shard_v2",
    "validate_backend_runtime_validation_system_shard_v2",
    "build_backend_runtime_validation_index_v2",
    "validate_backend_runtime_validation_index_v2",
]
