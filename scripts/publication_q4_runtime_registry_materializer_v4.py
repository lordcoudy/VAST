#!/usr/bin/env python3
"""Physically materialize the public arbitrary-Q4 runtime registry v4.

The materializer consumes an exact, self-hashed schema-v5 snapshot plan,
physically assesses all descriptor/semantic-pinned runtime, launcher,
validator, runner, invocation, and dataset authorities through their public
APIs, derives the two frozen six-stream dataset bindings, and commits one
immutable non-authorizing 112-authority registry.  It never runs a benchmark,
qualifies evidence, creates a grant, or mutates any source artifact.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping, Sequence

from backend_publication_launcher_invocation_v3 import (
    validate_publication_launcher_invocation_v3,
)
from backend_publication_launcher_runtime_authority import (
    assess_backend_publication_launcher_runtime_authority,
    validate_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (
    UPSTREAM_IDENTITY_FIELDS,
    assess_backend_publication_runtime_authority_v2,
    validate_backend_publication_runtime_authority_v2,
)
from backend_runtime_qualification_v4_input_index import (
    runtime_binding_identity_v4,
)
from backend_runtime_validation_runner_authority import (
    assess_backend_runtime_validation_runner_authority,
    validate_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    validate_backend_runtime_validator_authority_v4,
)
from publication_q4_runtime_contract_v4 import (
    CODECS,
    POLICIES,
    SCHEMA_VERSION as RUNTIME_REGISTRY_SCHEMA_VERSION,
    SYSTEMS,
    TOPOLOGIES,
    build_publication_q4_dataset_binding_v4,
    build_publication_q4_runtime_candidate_registry_v4,
    qualification_launcher_evidence_files_v4,
    validate_publication_q4_runtime_candidate_registry_v4,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from production_arm_evidence_finalizer_v1 import (
    finalized_production_evidence_files_v1,
    native_candidate_evidence_files_v1,
)


SCHEMA_VERSION = 5
PLAN_KIND = "vast_publication_q4_runtime_materialization_plan_v5"
RESULT_KIND = "vast_publication_q4_runtime_materialization_result_v5"
LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION = 3
LAUNCHER_INPUT_WRAPPER_KIND = (
    "vast_publication_q4_runtime_launcher_input_dual_projection_v3"
)
LAUNCHER_INPUT_WRAPPER_LAUNCHER_KIND = (
    "dedicated_publication_runtime_dual_projection_v3"
)
LAUNCHER_INPUT_PROJECTION_KIND = (
    "vast_publication_q4_runtime_launcher_input_projection_v3"
)
EXIT_REJECTED = 78
MAX_JSON_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024 * 1024

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_TYPED_REF_FIELDS = frozenset(
    {
        "artifact_schema_version",
        "artifact_kind",
        "descriptor",
        "content_identity_sha256",
    }
)
_DATASET_SOURCE_FIELDS = frozenset(
    {"codec_variant", "front_gate_source", "underbody_source"}
)
_AUTHORITY_PLAN_FIELDS = frozenset(
    {
        "coordinate",
        "artifact",
        "upstream_identities",
        "policy_outputs",
        "launcher_input_expectations",
    }
)
_AUTHORITY_COORDINATE_FIELDS = frozenset(
    {"system", "codec", "topology_kind", "policy"}
)
_LAUNCHER_PLAN_FIELDS = frozenset(
    {
        "system",
        "artifact",
        "closure_manifest_sha256",
        "runtime_closure_set_sha256",
    }
)
_POLICY_OUTPUT_FIELDS = frozenset({"capability", "calibration", "static_map"})
_LAUNCHER_INPUT_EXPECTATION_FIELDS = frozenset(
    {
        "wrapper_sha256",
        "projection_crossbinding_sha256",
        "qualification_projection_sha256",
        "qualification_runtime_input_template_sha256",
        "production_projection_sha256",
        "production_runtime_input_template_sha256",
    }
)
_LAUNCHER_INPUT_PROJECTION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "projection_role",
        "runtime_input_template",
        "runtime_input_template_sha256",
        "launcher_evidence_files",
        "launcher_evidence_namespace_sha256",
        "projection_sha256",
    }
)
_LAUNCHER_INPUT_WRAPPER_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "system",
        "policy",
        "launcher_kind",
        "dataset_runtime_input_key",
        "qualification_projection",
        "production_projection",
        "shared_runtime_configuration_sha256",
        "projection_crossbinding_sha256",
        "wrapper_sha256",
    }
)
_RUNTIME_INPUT_KEY_BY_SYSTEM = {
    "deepstream": "deepstream_publication_runtime_v3",
    "savant": "savant_publication_runtime_v3",
    "openvino_gva": "openvino_gva_publication_runtime_v3",
    "gstreamer_custom": "gstreamer_custom_publication_runtime_v3",
}
_PARENT_OWNED_EVIDENCE_FILES = frozenset(
    {
        "backend_publication_arm_contract.json",
        "backend_publication_launch_fence_v3.json",
        "backend_publication_output_receipt_v3.json",
    }
)
_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "dataset_sources",
        "runtime_authorities",
        "launcher_runtime_authorities",
        "publication_launcher_invocation_v3",
        "q4_validator_authority",
        "runner_authority",
        "runner_invocation_identity_sha256",
        "plan_sha256",
    }
)
_DATASET_SOURCE_KIND = "vast_frozen_publication_dataset_source_v1"
_RUNTIME_AUTHORITY_KIND = "vast_backend_publication_runtime_authority_v2"
_LAUNCHER_AUTHORITY_KIND = (
    "vast_backend_publication_launcher_runtime_authority"
)
_INVOCATION_KIND = "vast_backend_publication_launcher_invocation_v3"
_VALIDATOR_AUTHORITY_KIND = "vast_backend_runtime_validator_authority_q4"
_RUNNER_AUTHORITY_KIND = (
    "vast_backend_runtime_validation_runner_authority"
)
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class PublicationQ4RuntimeRegistryMaterializerV4Error(RuntimeError):
    """One materialization input, authority, or physical pin drifted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(message)


def _strict_json(
    value: Any, *, active: set[int] | None = None, depth: int = 0
) -> None:
    _require(depth <= 96, "Q4 materialization JSON nesting is excessive")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "Q4 materialization JSON is non-finite")
        return
    _require(type(value) in {dict, list}, "Q4 materialization value is not JSON")
    active = set() if active is None else active
    identity = id(value)
    _require(identity not in active, "Q4 materialization JSON contains a cycle")
    active.add(identity)
    try:
        values = value.values() if type(value) is dict else value
        if type(value) is dict:
            _require(
                all(type(key) is str for key in value),
                "Q4 materialization JSON key type drifted",
            )
        for item in values:
            _strict_json(item, active=active, depth=depth + 1)
    finally:
        active.remove(identity)


def canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    _strict_json(value)
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            "Q4 materialization value is not canonical JSON"
        ) from error
    return payload + (b"\n" if newline else b"")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return value


def _evidence_leaf(value: Any, label: str) -> str:
    _require(
        type(value) is str
        and bool(value)
        and PurePosixPath(value).name == value
        and PureWindowsPath(value).name == value
        and value not in _PARENT_OWNED_EVIDENCE_FILES
        and "\x00" not in value,
        f"{label} evidence filename is unsafe",
    )
    return value


def _projection_evidence_names(
    *, role: str, policy: str,
) -> tuple[str, ...]:
    qualification = tuple(qualification_launcher_evidence_files_v4(policy))
    native = tuple(native_candidate_evidence_files_v1(policy))
    _require(
        qualification == native,
        "qualification/native-candidate evidence namespace contract drifted",
    )
    if role == "qualification_raw":
        return qualification
    _require(
        role == "production_finalized",
        "runtime launcher-input projection role drifted",
    )
    finalized = tuple(finalized_production_evidence_files_v1(policy))
    _require(
        len(finalized) == len(set(finalized))
        and all(_evidence_leaf(item, "production finalized") for item in finalized),
        "production finalized evidence namespace drifted",
    )
    return finalized


def _runtime_template_evidence_mapping(
    value: Any,
    *,
    policy: str,
    label: str,
) -> dict[str, str]:
    _require(type(value) is dict, f"{label} runtime-input template is not an object")
    _require(
        value.get("schema_version") == 3
        and type(value.get("artifact_kind")) is str
        and bool(value["artifact_kind"])
        and value.get("defer_full_resource_acceptance") is True,
        f"{label} runtime-input template ABI drifted",
    )
    mapping = value.get("evidence_mapping")
    expected = tuple(native_candidate_evidence_files_v1(policy))
    _require(
        type(mapping) is dict
        and set(mapping) == set(expected)
        and len(set(mapping.values())) == len(mapping)
        and all(
            _evidence_leaf(source, f"{label} source")
            and _evidence_leaf(destination, f"{label} destination")
            for source, destination in mapping.items()
        ),
        f"{label} runtime evidence mapping drifted",
    )
    return {str(key): str(item) for key, item in mapping.items()}


def _build_launcher_input_projection_v3(
    *,
    role: str,
    policy: str,
    runtime_input_template: Mapping[str, Any],
) -> dict[str, Any]:
    template = copy.deepcopy(dict(runtime_input_template))
    _runtime_template_evidence_mapping(
        template, policy=policy, label=role.replace("_", " ")
    )
    evidence = list(_projection_evidence_names(role=role, policy=policy))
    unsigned: dict[str, Any] = {
        "schema_version": LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION,
        "artifact_kind": LAUNCHER_INPUT_PROJECTION_KIND,
        "projection_role": role,
        "runtime_input_template": template,
        "runtime_input_template_sha256": canonical_sha256(template),
        "launcher_evidence_files": evidence,
        "launcher_evidence_namespace_sha256": canonical_sha256(evidence),
    }
    return {**unsigned, "projection_sha256": canonical_sha256(unsigned)}


def _validate_launcher_input_projection_v3(
    value: Any,
    *,
    role: str,
    policy: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _LAUNCHER_INPUT_PROJECTION_FIELDS,
        f"{role} runtime launcher-input projection fields drifted",
    )
    _require(
        value.get("schema_version") == LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION
        and value.get("artifact_kind") == LAUNCHER_INPUT_PROJECTION_KIND
        and value.get("projection_role") == role,
        f"{role} runtime launcher-input projection header drifted",
    )
    template = copy.deepcopy(value.get("runtime_input_template"))
    _runtime_template_evidence_mapping(
        template, policy=policy, label=role.replace("_", " ")
    )
    template_sha = _sha(
        value.get("runtime_input_template_sha256"),
        f"{role} runtime-input template",
    )
    _require(
        template_sha == canonical_sha256(template),
        f"{role} runtime-input template self-hash drifted",
    )
    evidence = value.get("launcher_evidence_files")
    expected_evidence = list(_projection_evidence_names(role=role, policy=policy))
    _require(
        type(evidence) is list
        and evidence == expected_evidence
        and all(_evidence_leaf(item, role) for item in evidence),
        f"{role} launcher evidence namespace drifted",
    )
    evidence_sha = _sha(
        value.get("launcher_evidence_namespace_sha256"),
        f"{role} launcher evidence namespace",
    )
    _require(
        evidence_sha == canonical_sha256(evidence),
        f"{role} launcher evidence namespace self-hash drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "projection_sha256"}
    projection_sha = _sha(
        value.get("projection_sha256"), f"{role} launcher-input projection"
    )
    _require(
        projection_sha == canonical_sha256(unsigned),
        f"{role} launcher-input projection self-hash drifted",
    )
    return {
        "schema_version": LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION,
        "artifact_kind": LAUNCHER_INPUT_PROJECTION_KIND,
        "projection_role": role,
        "runtime_input_template": template,
        "runtime_input_template_sha256": template_sha,
        "launcher_evidence_files": list(evidence),
        "launcher_evidence_namespace_sha256": evidence_sha,
        "projection_sha256": projection_sha,
    }


def _shared_runtime_configuration(
    template: Mapping[str, Any],
) -> dict[str, Any]:
    # Evidence routing is execution semantics, not projection-local metadata.
    # Both projections must therefore pin the same complete runtime template.
    return copy.deepcopy(dict(template))


def _launcher_input_crossbinding_material(
    *,
    system: str,
    policy: str,
    dataset_runtime_input_key: str,
    qualification: Mapping[str, Any],
    production: Mapping[str, Any],
    shared_runtime_configuration_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION,
        "artifact_kind": (
            "vast_publication_q4_runtime_launcher_input_projection_crossbinding_v3"
        ),
        "system": system,
        "policy": policy,
        "dataset_runtime_input_key": dataset_runtime_input_key,
        "qualification_projection_sha256": qualification["projection_sha256"],
        "production_projection_sha256": production["projection_sha256"],
        "shared_runtime_configuration_sha256": (
            shared_runtime_configuration_sha256
        ),
    }


def build_publication_q4_runtime_launcher_input_wrapper_v3(
    *,
    system: str,
    policy: str,
    qualification_runtime_input_template: Mapping[str, Any],
    production_runtime_input_template: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the closed ABI-v3 qualification/production projection wrapper."""

    _require(system in SYSTEMS, "runtime launcher-input wrapper system drifted")
    _require(policy in POLICIES, "runtime launcher-input wrapper policy drifted")
    qualification = _build_launcher_input_projection_v3(
        role="qualification_raw",
        policy=policy,
        runtime_input_template=qualification_runtime_input_template,
    )
    production = _build_launcher_input_projection_v3(
        role="production_finalized",
        policy=policy,
        runtime_input_template=production_runtime_input_template,
    )
    qualification_shared = _shared_runtime_configuration(
        qualification["runtime_input_template"]
    )
    production_shared = _shared_runtime_configuration(
        production["runtime_input_template"]
    )
    _require(
        qualification_shared == production_shared,
        "qualification/production shared runtime configuration drifted",
    )
    shared_sha = canonical_sha256(qualification_shared)
    runtime_key = _RUNTIME_INPUT_KEY_BY_SYSTEM[system]
    crossbinding_sha = canonical_sha256(
        _launcher_input_crossbinding_material(
            system=system,
            policy=policy,
            dataset_runtime_input_key=runtime_key,
            qualification=qualification,
            production=production,
            shared_runtime_configuration_sha256=shared_sha,
        )
    )
    unsigned: dict[str, Any] = {
        "schema_version": LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION,
        "artifact_kind": LAUNCHER_INPUT_WRAPPER_KIND,
        "system": system,
        "policy": policy,
        "launcher_kind": LAUNCHER_INPUT_WRAPPER_LAUNCHER_KIND,
        "dataset_runtime_input_key": runtime_key,
        "qualification_projection": qualification,
        "production_projection": production,
        "shared_runtime_configuration_sha256": shared_sha,
        "projection_crossbinding_sha256": crossbinding_sha,
    }
    return validate_publication_q4_runtime_launcher_input_wrapper_v3(
        {**unsigned, "wrapper_sha256": canonical_sha256(unsigned)},
        expected_system=system,
        expected_policy=policy,
    )


def validate_publication_q4_runtime_launcher_input_wrapper_v3(
    value: Any,
    *,
    expected_system: str,
    expected_policy: str,
) -> dict[str, Any]:
    """Validate a closed dual projection and its raw/final evidence namespaces."""

    _require(
        type(value) is dict and set(value) == _LAUNCHER_INPUT_WRAPPER_FIELDS,
        "runtime launcher-input wrapper fields drifted or legacy flat input used",
    )
    _require(
        expected_system in SYSTEMS
        and expected_policy in POLICIES
        and value.get("schema_version") == LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION
        and value.get("artifact_kind") == LAUNCHER_INPUT_WRAPPER_KIND
        and value.get("system") == expected_system
        and value.get("policy") == expected_policy
        and value.get("launcher_kind") == LAUNCHER_INPUT_WRAPPER_LAUNCHER_KIND
        and value.get("dataset_runtime_input_key")
        == _RUNTIME_INPUT_KEY_BY_SYSTEM[expected_system],
        "runtime launcher-input wrapper header/coordinate drifted",
    )
    qualification = _validate_launcher_input_projection_v3(
        value.get("qualification_projection"),
        role="qualification_raw",
        policy=expected_policy,
    )
    production = _validate_launcher_input_projection_v3(
        value.get("production_projection"),
        role="production_finalized",
        policy=expected_policy,
    )
    qualification_shared = _shared_runtime_configuration(
        qualification["runtime_input_template"]
    )
    production_shared = _shared_runtime_configuration(
        production["runtime_input_template"]
    )
    _require(
        qualification_shared == production_shared,
        "qualification/production shared runtime configuration drifted",
    )
    shared_sha = _sha(
        value.get("shared_runtime_configuration_sha256"),
        "shared runtime configuration",
    )
    _require(
        shared_sha == canonical_sha256(qualification_shared),
        "shared runtime configuration self-hash drifted",
    )
    runtime_key = _RUNTIME_INPUT_KEY_BY_SYSTEM[expected_system]
    crossbinding_sha = _sha(
        value.get("projection_crossbinding_sha256"),
        "runtime launcher-input projection crossbinding",
    )
    _require(
        crossbinding_sha
        == canonical_sha256(
            _launcher_input_crossbinding_material(
                system=expected_system,
                policy=expected_policy,
                dataset_runtime_input_key=runtime_key,
                qualification=qualification,
                production=production,
                shared_runtime_configuration_sha256=shared_sha,
            )
        ),
        "runtime launcher-input projection crossbinding drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "wrapper_sha256"}
    wrapper_sha = _sha(value.get("wrapper_sha256"), "runtime launcher-input wrapper")
    _require(
        wrapper_sha == canonical_sha256(unsigned),
        "runtime launcher-input wrapper self-hash drifted",
    )
    return {
        "schema_version": LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION,
        "artifact_kind": LAUNCHER_INPUT_WRAPPER_KIND,
        "system": expected_system,
        "policy": expected_policy,
        "launcher_kind": LAUNCHER_INPUT_WRAPPER_LAUNCHER_KIND,
        "dataset_runtime_input_key": runtime_key,
        "qualification_projection": qualification,
        "production_projection": production,
        "shared_runtime_configuration_sha256": shared_sha,
        "projection_crossbinding_sha256": crossbinding_sha,
        "wrapper_sha256": wrapper_sha,
    }


def _relative(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is empty")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and not posix.is_absolute()
        and not windows.is_absolute()
        and posix.as_posix() == value
        and bool(posix.parts)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and part.split(".", 1)[0].upper() not in _RESERVED
            and all(ord(character) >= 32 for character in part)
            for part in posix.parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    size = value.get("size_bytes")
    _require(
        type(size) is int and size > 0,
        f"{label} descriptor size drifted",
    )
    return {
        "path": _relative(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), label),
    }


def _artifact_ref(
    value: Any,
    *,
    schema_version: int,
    kind: str,
    label: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _TYPED_REF_FIELDS,
        f"{label} artifact reference fields drifted",
    )
    _require(
        type(value.get("artifact_schema_version")) is int
        and value.get("artifact_schema_version") == schema_version
        and value.get("artifact_kind") == kind,
        f"{label} artifact reference type drifted",
    )
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} semantic")
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        "descriptor": descriptor,
        "content_identity_sha256": identity,
    }


def _upstream_identities(value: Any, label: str) -> dict[str, str]:
    _require(
        type(value) is dict
        and set(value) == set(UPSTREAM_IDENTITY_FIELDS),
        f"{label} upstream identity fields drifted",
    )
    return {
        key: _sha(value.get(key), f"{label} upstream {key}")
        for key in UPSTREAM_IDENTITY_FIELDS
    }


def _policy_output_expectations(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _POLICY_OUTPUT_FIELDS,
        f"{label} policy output expectation fields drifted",
    )
    result: dict[str, Any] = {}
    for name in ("capability", "calibration", "static_map"):
        item = value.get(name)
        result[name] = (
            None if item is None else _descriptor(item, f"{label} policy {name}")
        )
    return result


def _launcher_input_expectations(value: Any, label: str) -> dict[str, str]:
    _require(
        type(value) is dict
        and set(value) == _LAUNCHER_INPUT_EXPECTATION_FIELDS,
        f"{label} launcher-input expectation fields drifted",
    )
    return {
        key: _sha(value.get(key), f"{label} {key}")
        for key in sorted(_LAUNCHER_INPUT_EXPECTATION_FIELDS)
    }


def publication_q4_runtime_launcher_input_expectations_v5(
    wrapper: Mapping[str, Any],
    *,
    expected_system: str,
    expected_policy: str,
) -> dict[str, str]:
    """Project the independently plan-pinned dual-template identities."""

    checked = validate_publication_q4_runtime_launcher_input_wrapper_v3(
        copy.deepcopy(dict(wrapper)),
        expected_system=expected_system,
        expected_policy=expected_policy,
    )
    qualification = checked["qualification_projection"]
    production = checked["production_projection"]
    return {
        "projection_crossbinding_sha256": checked[
            "projection_crossbinding_sha256"
        ],
        "production_projection_sha256": production["projection_sha256"],
        "production_runtime_input_template_sha256": production[
            "runtime_input_template_sha256"
        ],
        "qualification_projection_sha256": qualification[
            "projection_sha256"
        ],
        "qualification_runtime_input_template_sha256": qualification[
            "runtime_input_template_sha256"
        ],
        "wrapper_sha256": checked["wrapper_sha256"],
    }


def _coordinate(value: Any) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == _AUTHORITY_COORDINATE_FIELDS,
        "Q4 runtime authority plan coordinate fields drifted",
    )
    result = {
        key: value.get(key)
        for key in ("system", "codec", "topology_kind", "policy")
    }
    _require(
        type(result["system"]) is str
        and result["system"] in SYSTEMS
        and type(result["codec"]) is str
        and result["codec"] in CODECS
        and type(result["topology_kind"]) is str
        and result["topology_kind"] in TOPOLOGIES
        and type(result["policy"]) is str
        and result["policy"] in POLICIES,
        "Q4 runtime authority plan coordinate value drifted",
    )
    return {key: str(item) for key, item in result.items()}


def _expected_coordinates() -> list[dict[str, str]]:
    return [
        {
            "system": system,
            "codec": codec,
            "topology_kind": topology,
            "policy": policy,
        }
        for system in SYSTEMS
        for codec in CODECS
        for topology in TOPOLOGIES
        for policy in POLICIES
    ]


def build_publication_q4_runtime_materialization_plan_v4(
    *,
    dataset_sources: Sequence[Mapping[str, Any]],
    runtime_authorities: Sequence[Mapping[str, Any]],
    launcher_runtime_authorities: Sequence[Mapping[str, Any]],
    publication_launcher_invocation_v3: Mapping[str, Any],
    q4_validator_authority: Mapping[str, Any],
    runner_authority: Mapping[str, Any],
    runner_invocation_identity_sha256: str,
) -> dict[str, Any]:
    """Build an exact descriptor/semantic-pinned materialization plan v5.

    The historical ``_v4`` callable name is retained for repository callers;
    the returned artifact is deliberately schema/kind v5 and rejects every
    path-only v4 plan.
    """

    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PLAN_KIND,
        "status": "requested_physical_non_authorizing_materialization",
        "authorization_eligible": False,
        "execution_authorized": False,
        "dataset_sources": copy.deepcopy(list(dataset_sources)),
        "runtime_authorities": copy.deepcopy(list(runtime_authorities)),
        "launcher_runtime_authorities": copy.deepcopy(
            list(launcher_runtime_authorities)
        ),
        "publication_launcher_invocation_v3": copy.deepcopy(
            dict(publication_launcher_invocation_v3)
        ),
        "q4_validator_authority": copy.deepcopy(dict(q4_validator_authority)),
        "runner_authority": copy.deepcopy(dict(runner_authority)),
        "runner_invocation_identity_sha256": runner_invocation_identity_sha256,
    }
    return validate_publication_q4_runtime_materialization_plan_v4(
        {**unsigned, "plan_sha256": canonical_sha256(unsigned)}
    )


def validate_publication_q4_runtime_materialization_plan_v4(
    value: Any,
) -> dict[str, Any]:
    """Validate descriptor, semantic, upstream, and template snapshot pins."""

    _require(
        type(value) is dict and set(value) == _PLAN_FIELDS,
        "Q4 runtime materialization plan fields drifted",
    )
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == PLAN_KIND
        and value.get("status")
        == "requested_physical_non_authorizing_materialization"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 runtime materialization plan header/claims drifted",
    )
    raw_datasets = value.get("dataset_sources")
    _require(
        type(raw_datasets) is list and len(raw_datasets) == len(CODECS),
        "Q4 runtime materialization dataset-source coverage drifted",
    )
    datasets: list[dict[str, Any]] = []
    for position, (raw, codec) in enumerate(zip(raw_datasets, CODECS)):
        _require(
            type(raw) is dict
            and set(raw) == _DATASET_SOURCE_FIELDS
            and raw.get("codec_variant") == codec,
            f"Q4 dataset source[{position}] order/fields drifted",
        )
        front = _artifact_ref(
            raw.get("front_gate_source"),
            schema_version=1,
            kind=_DATASET_SOURCE_KIND,
            label=f"Q4 {codec} front-gate source",
        )
        underbody = _artifact_ref(
            raw.get("underbody_source"),
            schema_version=1,
            kind=_DATASET_SOURCE_KIND,
            label=f"Q4 {codec} underbody source",
        )
        _require(
            front["descriptor"]["path"].casefold()
            != underbody["descriptor"]["path"].casefold()
            and front["descriptor"]["sha256"]
            == front["content_identity_sha256"]
            and underbody["descriptor"]["sha256"]
            == underbody["content_identity_sha256"]
            and front["content_identity_sha256"]
            != underbody["content_identity_sha256"],
            f"Q4 dataset source[{position}] raw/semantic pins alias or drifted",
        )
        datasets.append(
            {
                "codec_variant": codec,
                "front_gate_source": front,
                "underbody_source": underbody,
            }
        )
    raw_authorities = value.get("runtime_authorities")
    expected_coordinates = _expected_coordinates()
    _require(
        type(raw_authorities) is list
        and len(raw_authorities) == len(expected_coordinates),
        "Q4 runtime materialization authority path coverage drifted",
    )
    authorities: list[dict[str, Any]] = []
    for position, (raw, expected) in enumerate(
        zip(raw_authorities, expected_coordinates)
    ):
        _require(
            type(raw) is dict and set(raw) == _AUTHORITY_PLAN_FIELDS,
            f"Q4 runtime authority plan[{position}] fields drifted",
        )
        coordinate = _coordinate(raw.get("coordinate"))
        _require(
            coordinate == expected,
            f"Q4 runtime authority path[{position}] order drifted",
        )
        authorities.append(
            {
                "coordinate": coordinate,
                "artifact": _artifact_ref(
                    raw.get("artifact"),
                    schema_version=2,
                    kind=_RUNTIME_AUTHORITY_KIND,
                    label=f"Q4 runtime authority[{position}]",
                ),
                "upstream_identities": _upstream_identities(
                    raw.get("upstream_identities"),
                    f"Q4 runtime authority[{position}]",
                ),
                "policy_outputs": _policy_output_expectations(
                    raw.get("policy_outputs"),
                    f"Q4 runtime authority[{position}]",
                ),
                "launcher_input_expectations": _launcher_input_expectations(
                    raw.get("launcher_input_expectations"),
                    f"Q4 runtime authority[{position}]",
                ),
            }
        )
    raw_launchers = value.get("launcher_runtime_authorities")
    _require(
        type(raw_launchers) is list and len(raw_launchers) == len(SYSTEMS),
        "Q4 launcher runtime authority path coverage drifted",
    )
    launchers: list[dict[str, Any]] = []
    for position, (raw, system) in enumerate(zip(raw_launchers, SYSTEMS)):
        _require(
            type(raw) is dict
            and set(raw) == _LAUNCHER_PLAN_FIELDS
            and raw.get("system") == system,
            f"Q4 launcher authority plan[{position}] order/fields drifted",
        )
        launchers.append(
            {
                "system": system,
                "artifact": _artifact_ref(
                    raw.get("artifact"),
                    schema_version=1,
                    kind=_LAUNCHER_AUTHORITY_KIND,
                    label=f"Q4 {system} launcher authority",
                ),
                "closure_manifest_sha256": _sha(
                    raw.get("closure_manifest_sha256"),
                    f"Q4 {system} launcher closure manifest",
                ),
                "runtime_closure_set_sha256": _sha(
                    raw.get("runtime_closure_set_sha256"),
                    f"Q4 {system} launcher closure set",
                ),
            }
        )
    invocation = _artifact_ref(
        value.get("publication_launcher_invocation_v3"),
        schema_version=3,
        kind=_INVOCATION_KIND,
        label="publication launcher invocation v3",
    )
    validator = _artifact_ref(
        value.get("q4_validator_authority"),
        schema_version=1,
        kind=_VALIDATOR_AUTHORITY_KIND,
        label="Q4 validator authority",
    )
    runner = _artifact_ref(
        value.get("runner_authority"),
        schema_version=1,
        kind=_RUNNER_AUTHORITY_KIND,
        label="Q4 runner authority",
    )
    runner_invocation_identity = _sha(
        value.get("runner_invocation_identity_sha256"),
        "Q4 runner invocation identity",
    )
    refs = [
        *(item["front_gate_source"] for item in datasets),
        *(item["underbody_source"] for item in datasets),
        *(item["artifact"] for item in authorities),
        *(item["artifact"] for item in launchers),
        invocation,
        validator,
        runner,
    ]
    paths = [item["descriptor"]["path"] for item in refs]
    _require(
        len(paths) == len({item.casefold() for item in paths}),
        "Q4 runtime materialization plan paths alias",
    )
    _require(
        len(
            {
                item["artifact"]["content_identity_sha256"]
                for item in authorities
            }
        )
        == len(authorities),
        "Q4 runtime materialization authority semantic identities alias",
    )
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PLAN_KIND,
        "status": "requested_physical_non_authorizing_materialization",
        "authorization_eligible": False,
        "execution_authorized": False,
        "dataset_sources": datasets,
        "runtime_authorities": authorities,
        "launcher_runtime_authorities": launchers,
        "publication_launcher_invocation_v3": invocation,
        "q4_validator_authority": validator,
        "runner_authority": runner,
        "runner_invocation_identity_sha256": runner_invocation_identity,
    }
    identity = _sha(value.get("plan_sha256"), "Q4 materialization plan")
    _require(
        identity == canonical_sha256(normalized),
        "Q4 runtime materialization plan self-hash drifted",
    )
    return {**normalized, "plan_sha256": identity}


def _root(value: Path | str) -> Path:
    supplied = Path(os.path.abspath(os.fspath(value)))
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            "project_root is unavailable"
        ) from error
    _require(
        supplied == resolved
        and stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
        "project_root is not a canonical physical directory",
    )
    return resolved


def _physical_path(root: Path, relative: str, label: str) -> Path:
    checked = _relative(relative, label)
    path = root.joinpath(*PurePosixPath(checked).parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"{label} is unavailable"
        ) from error
    _require(
        resolved == path and resolved.is_relative_to(root),
        f"{label} escaped project_root or crossed a link",
    )
    cursor = root
    for part in PurePosixPath(checked).parts[:-1]:
        cursor /= part
        info = cursor.lstat()
        _require(
            stat.S_ISDIR(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
            f"{label} parent is unsafe",
        )
    return path


def _output_target(root: Path, value: Path | str, label: str) -> Path:
    raw = Path(value)
    path = (
        Path(os.path.abspath(raw))
        if raw.is_absolute()
        else root.joinpath(*PurePosixPath(_relative(raw.as_posix(), label)).parts)
    )
    try:
        path.relative_to(root)
    except ValueError as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"{label} escaped project_root"
        ) from error
    cursor = root
    for part in path.parent.relative_to(root).parts:
        cursor /= part
        if not os.path.lexists(cursor):
            break
        info = cursor.lstat()
        _require(
            stat.S_ISDIR(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
            f"{label} parent is unsafe",
        )
    return path


def _read_descriptor(
    root: Path,
    relative: str,
    label: str,
    *,
    maximum: int = MAX_JSON_BYTES,
    capture: bool = True,
    custody: PhysicalRootCustodyV1 | None = None,
) -> tuple[dict[str, Any], bytes]:
    owned = custody is None
    active = custody
    try:
        if active is None:
            active = PhysicalRootCustodyV1.open(
                root, label="Q4 runtime materialization project_root"
            )
        descriptor, payload = active.read_descriptor(
            relative,
            label=label,
            maximum=maximum,
            capture=capture,
        )
        return descriptor, b"" if payload is None else payload
    except PublicationPhysicalIoV1Error as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"{label} physical read failed"
        ) from error
    finally:
        if owned and active is not None:
            active.close()


def _load_json(
    root: Path,
    relative: str,
    label: str,
    *,
    custody: PhysicalRootCustodyV1 | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor, payload = _read_descriptor(
        root, relative, label, capture=True, custody=custody
    )
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"{label} is not JSON"
        ) from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(
        payload in {canonical_bytes(value), canonical_bytes(value, newline=True)},
        f"{label} is not canonical JSON",
    )
    return descriptor, dict(value)


def _read_expected_descriptor(
    root: Path,
    reference: Mapping[str, Any],
    label: str,
    *,
    maximum: int = MAX_JSON_BYTES,
    capture: bool = True,
    custody: PhysicalRootCustodyV1,
) -> tuple[dict[str, Any], bytes]:
    expected = _descriptor(reference.get("descriptor"), label)
    observed, payload = _read_descriptor(
        root,
        expected["path"],
        label,
        maximum=maximum,
        capture=capture,
        custody=custody,
    )
    _require(observed == expected, f"{label} raw descriptor pin drifted")
    return observed, payload


def _load_expected_json(
    root: Path,
    reference: Mapping[str, Any],
    label: str,
    *,
    custody: PhysicalRootCustodyV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = _descriptor(reference.get("descriptor"), label)
    observed, value = _load_json(
        root,
        expected["path"],
        label,
        custody=custody,
    )
    _require(observed == expected, f"{label} raw descriptor pin drifted")
    return observed, value


def _typed_ref(
    descriptor: Mapping[str, Any], *, schema_version: int, kind: str, identity: str
) -> dict[str, Any]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        "descriptor": copy.deepcopy(dict(descriptor)),
        "content_identity_sha256": _sha(identity, f"{kind} semantic"),
    }


def _write_immutable_json(
    root: Path,
    output_path: Path | str,
    value: Mapping[str, Any],
    *,
    label: str,
    custody: PhysicalRootCustodyV1 | None = None,
) -> dict[str, Any]:
    payload = canonical_bytes(dict(value), newline=True)
    owned = custody is None
    active = custody
    try:
        if active is None:
            active = PhysicalRootCustodyV1.open(
                root, label="Q4 runtime materialization project_root"
            )
        return active.write_exclusive(
            output_path,
            payload,
            label=label,
            mode=0o444,
            create_parents=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"{label} immutable write failed"
        ) from error
    finally:
        if owned and active is not None:
            active.close()


def _transaction_descriptor(
    root: Path,
    output_path: Path | str,
    payload: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    destination = _output_target(root, output_path, label)
    return {
        "path": destination.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _read_exact_transaction_leaf(
    *,
    custody: PhysicalRootCustodyV1,
    descriptor: Mapping[str, Any],
    payload: bytes,
    label: str,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], tuple[int, int]]:
    expected = _descriptor(dict(descriptor), label)
    observed, identity = custody.adopt_exact_durable_identity(
        expected["path"],
        payload,
        label=label,
        mode=0o444,
        expected_identity=expected_identity,
    )
    _require(
        observed == expected
        and observed["sha256"] == hashlib.sha256(payload).hexdigest(),
        f"{label} exact resumable payload/mode drifted",
    )
    return observed, identity


def _after_artifact_commit(
    callback: Callable[[str], None] | None,
    boundary: str,
    *,
    custody: PhysicalRootCustodyV1,
    watched_paths: Sequence[str],
) -> None:
    if callback is None:
        return
    epochs = custody.capture_pinned_directory_epochs(
        label=f"Q4 runtime {boundary} fault boundary"
    )
    mutation_watch = custody.begin_read_namespace_mutation_watch(
        list(watched_paths), label=f"Q4 runtime {boundary} fault boundary"
    )
    try:
        callback(boundary)
    except BaseException:
        if mutation_watch is not None:
            mutation_watch.close()
        raise
    custody.verify_pinned_directory_mutation_watch(
        mutation_watch, label=f"Q4 runtime {boundary} fault boundary"
    )
    custody.verify_pinned_directory_epochs(
        epochs, label=f"Q4 runtime {boundary} fault boundary"
    )


def _policy_outputs(authority: Mapping[str, Any]) -> dict[str, Any]:
    policy = authority.get("policy_authority")
    _require(type(policy) is dict, "runtime authority policy authority is missing")
    result: dict[str, Any] = {}
    for name in ("capability", "calibration", "static_map"):
        artifact = policy.get(name)
        result[name] = (
            None
            if artifact is None
            else copy.deepcopy(artifact.get("descriptor"))
        )
    return result


def _source_descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} source entry is not an object")
    _require(
        frozenset(value)
        in {
            _DESCRIPTOR_FIELDS,
            _DESCRIPTOR_FIELDS | {"container_path"},
        },
        f"{label} source descriptor fields drifted",
    )
    projected = {key: value.get(key) for key in _DESCRIPTOR_FIELDS}
    _require(
        set(projected) == _DESCRIPTOR_FIELDS
        and type(projected["path"]) is str
        and type(projected["size_bytes"]) is int
        and projected["size_bytes"] > 0,
        f"{label} source descriptor drifted",
    )
    _relative(projected["path"], label)
    _sha(projected["sha256"], f"{label} source")
    return projected


def validate_publication_q4_runtime_candidate_registry_against_plan_v5(
    registry: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Cross-bind every registry projection to the exact schema-v5 plan."""

    checked_plan = validate_publication_q4_runtime_materialization_plan_v4(
        copy.deepcopy(dict(plan))
    )
    try:
        checked_registry = validate_publication_q4_runtime_candidate_registry_v4(
            copy.deepcopy(dict(registry))
        )
    except Exception as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"Q4 runtime candidate registry rejected: {error}"
        ) from error

    expected_datasets = [
        build_publication_q4_dataset_binding_v4(
            codec_variant=item["codec_variant"],
            front_gate_sha256=item["front_gate_source"][
                "content_identity_sha256"
            ],
            underbody_sha256=item["underbody_source"][
                "content_identity_sha256"
            ],
        )
        for item in checked_plan["dataset_sources"]
    ]
    _require(
        checked_registry["dataset_bindings"] == expected_datasets,
        "Q4 registry dataset bindings are not the plan-pinned source snapshot",
    )
    datasets_by_codec = {
        item["codec_variant"]: item for item in expected_datasets
    }
    launchers = {
        item["system"]: item
        for item in checked_plan["launcher_runtime_authorities"]
    }
    invocation_ref = checked_plan["publication_launcher_invocation_v3"]
    validator_ref = checked_plan["q4_validator_authority"]
    runner_ref = checked_plan["runner_authority"]
    invocation_sha = invocation_ref["content_identity_sha256"]

    system_set_identities: dict[str, str] = {}
    system_binding_identities: dict[str, str] = {}
    for system in SYSTEMS:
        system_rows = [
            item
            for item in checked_plan["runtime_authorities"]
            if item["coordinate"]["system"] == system
        ]
        records = [
            {
                "coordinate": copy.deepcopy(item["coordinate"]),
                "authority_ref": copy.deepcopy(item["artifact"]),
                "authority_sha256": item["artifact"][
                    "content_identity_sha256"
                ],
            }
            for item in system_rows
        ]
        set_sha = canonical_sha256(records)
        launcher = launchers[system]
        binding_sha = runtime_binding_identity_v4(
            system=system,
            upstream_identities=system_rows[0]["upstream_identities"],
            runtime_authority_set_sha256=set_sha,
            launcher_runtime_authority_sha256=launcher["artifact"][
                "content_identity_sha256"
            ],
            publication_launcher_invocation_v3_sha256=invocation_sha,
        )
        system_set_identities[system] = set_sha
        system_binding_identities[system] = binding_sha

    for position, (snapshot, expected) in enumerate(
        zip(
            checked_registry["authority_snapshots"],
            checked_plan["runtime_authorities"],
            strict=True,
        )
    ):
        coordinate = expected["coordinate"]
        system = coordinate["system"]
        dataset = datasets_by_codec[coordinate["codec"]]
        launcher = launchers[system]
        try:
            invocation = validate_publication_launcher_invocation_v3(
                snapshot["publication_launcher_invocation_v3"]
            )
        except Exception as error:
            raise PublicationQ4RuntimeRegistryMaterializerV4Error(
                f"Q4 registry snapshot[{position}] invocation rejected: {error}"
            ) from error
        template_sha = canonical_sha256(snapshot["runtime_input_template"])
        _require(
            snapshot["coordinate"] == coordinate
            and snapshot["dataset_binding_sha256"]
            == dataset["dataset_binding_sha256"]
            and snapshot["upstream_identities"]
            == expected["upstream_identities"]
            and snapshot["runtime_authority_ref"] == expected["artifact"]
            and snapshot["runtime_authority_sha256"]
            == expected["artifact"]["content_identity_sha256"]
            and snapshot["runtime_authority_set_sha256"]
            == system_set_identities[system]
            and snapshot["runtime_binding_identity_v4_sha256"]
            == system_binding_identities[system]
            and snapshot["launcher_runtime_authority_ref"]
            == launcher["artifact"]
            and snapshot["launcher_runtime_authority_sha256"]
            == launcher["artifact"]["content_identity_sha256"]
            and snapshot["publication_launcher_invocation_v3_ref"]
            == invocation_ref
            and invocation["invocation_sha256"] == invocation_sha
            and snapshot["q4_validator_authority_ref"] == validator_ref
            and snapshot["q4_validator_authority_sha256"]
            == validator_ref["content_identity_sha256"]
            and snapshot["runner_authority_ref"] == runner_ref
            and snapshot["runner_authority_sha256"]
            == runner_ref["content_identity_sha256"]
            and snapshot["runner_invocation_identity_sha256"]
            == checked_plan["runner_invocation_identity_sha256"]
            and template_sha
            == expected["launcher_input_expectations"][
                "qualification_runtime_input_template_sha256"
            ],
            f"Q4 registry snapshot[{position}] is not exactly cross-bound "
            "to its plan-pinned authority/template projection",
        )
    return checked_registry


def materialize_publication_q4_runtime_candidate_registry_v4(
    *,
    project_root: Path | str,
    plan: Mapping[str, Any],
    output_path: Path | str,
    result_output_path: Path | str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Commit the registry first and its immutable materialization result last."""

    root = _root(project_root)
    try:
        with PhysicalRootCustodyV1.open(
            root, label="Q4 runtime materialization project_root"
        ) as custody:
            return _materialize_publication_q4_runtime_candidate_registry_v4(
                root=root,
                custody=custody,
                plan=plan,
                output_path=output_path,
                result_output_path=result_output_path,
                after_artifact_commit=after_artifact_commit,
            )
    except PublicationPhysicalIoV1Error as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            "Q4 runtime materialization physical custody failed"
        ) from error


def _materialize_publication_q4_runtime_candidate_registry_v4(
    *,
    root: Path,
    custody: PhysicalRootCustodyV1,
    plan: Mapping[str, Any],
    output_path: Path | str,
    result_output_path: Path | str,
    after_artifact_commit: Callable[[str], None] | None,
) -> dict[str, Any]:
    registry_destination = _output_target(
        root, output_path, "Q4 runtime candidate registry output"
    )
    result_destination = _output_target(
        root, result_output_path, "Q4 runtime materialization result output"
    )
    _require(
        registry_destination.as_posix().casefold()
        != result_destination.as_posix().casefold(),
        "Q4 runtime registry and materialization result outputs alias",
    )
    registry_preexists = os.path.lexists(registry_destination)
    result_preexists = os.path.lexists(result_destination)
    _require(
        not result_preexists or registry_preexists,
        "Q4 runtime materialization result exists without its causal registry",
    )
    checked_plan = validate_publication_q4_runtime_materialization_plan_v4(
        copy.deepcopy(dict(plan))
    )
    datasets: list[dict[str, Any]] = []
    dataset_descriptors: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in checked_plan["dataset_sources"]:
        front_ref = item["front_gate_source"]
        underbody_ref = item["underbody_source"]
        front, _ = _read_expected_descriptor(
            root,
            front_ref,
            f"{item['codec_variant']} front-gate source",
            maximum=MAX_SOURCE_BYTES,
            capture=False,
            custody=custody,
        )
        underbody, _ = _read_expected_descriptor(
            root,
            underbody_ref,
            f"{item['codec_variant']} underbody source",
            maximum=MAX_SOURCE_BYTES,
            capture=False,
            custody=custody,
        )
        _require(
            front["sha256"] == front_ref["content_identity_sha256"]
            and underbody["sha256"]
            == underbody_ref["content_identity_sha256"]
            and front["sha256"] != underbody["sha256"],
            f"{item['codec_variant']} dataset source identities alias",
        )
        dataset = build_publication_q4_dataset_binding_v4(
            codec_variant=item["codec_variant"],
            front_gate_sha256=front["sha256"],
            underbody_sha256=underbody["sha256"],
        )
        datasets.append(dataset)
        dataset_descriptors[item["codec_variant"]] = (front, underbody)

    invocation_descriptor, invocation_value = _load_json(
        root,
        checked_plan["publication_launcher_invocation_v3"]["descriptor"]["path"],
        "publication launcher invocation v3",
        custody=custody,
    )
    _require(
        invocation_descriptor
        == checked_plan["publication_launcher_invocation_v3"]["descriptor"],
        "publication launcher invocation v3 raw descriptor pin drifted",
    )
    try:
        invocation = validate_publication_launcher_invocation_v3(invocation_value)
    except Exception as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"publication launcher invocation v3 rejected: {error}"
        ) from error
    invocation_ref = _typed_ref(
        invocation_descriptor,
        schema_version=3,
        kind="vast_backend_publication_launcher_invocation_v3",
        identity=invocation["invocation_sha256"],
    )
    _require(
        invocation_ref == checked_plan["publication_launcher_invocation_v3"],
        "publication launcher invocation v3 semantic plan pin drifted",
    )

    validator_descriptor, validator_value = _load_json(
        root,
        checked_plan["q4_validator_authority"]["descriptor"]["path"],
        "Q4 validator authority",
        custody=custody,
    )
    _require(
        validator_descriptor
        == checked_plan["q4_validator_authority"]["descriptor"],
        "Q4 validator authority raw descriptor pin drifted",
    )
    try:
        validator = validate_backend_runtime_validator_authority_v4(
            validator_value,
            expected_authority_sha256=checked_plan[
                "q4_validator_authority"
            ]["content_identity_sha256"],
        )
        validator_assessment = assess_backend_runtime_validator_authority_v4(
            validator,
            project_root=root,
            expected_authority_sha256=validator["authority_sha256"],
        )
    except Exception as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"Q4 validator authority rejected: {error}"
        ) from error
    _require(
        validator_assessment.get("status") == "physically_valid",
        "Q4 validator authority is not physically valid",
    )
    validator_ref = _typed_ref(
        validator_descriptor,
        schema_version=1,
        kind="vast_backend_runtime_validator_authority_q4",
        identity=validator["authority_sha256"],
    )
    _require(
        validator_ref == checked_plan["q4_validator_authority"],
        "Q4 validator authority semantic plan pin drifted",
    )

    runner_descriptor, runner_value = _load_json(
        root,
        checked_plan["runner_authority"]["descriptor"]["path"],
        "Q4 runner authority",
        custody=custody,
    )
    _require(
        runner_descriptor == checked_plan["runner_authority"]["descriptor"],
        "Q4 runner authority raw descriptor pin drifted",
    )
    try:
        runner = validate_backend_runtime_validation_runner_authority(
            runner_value,
            expected_runner_authority_sha256=checked_plan[
                "runner_authority"
            ]["content_identity_sha256"],
        )
        runner_assessment = assess_backend_runtime_validation_runner_authority(
            runner,
            project_root=root,
            expected_runner_authority_sha256=runner[
                "runner_authority_sha256"
            ],
        )
    except Exception as error:
        raise PublicationQ4RuntimeRegistryMaterializerV4Error(
            f"Q4 runner authority rejected: {error}"
        ) from error
    _require(
        runner_assessment.get("status") == "physically_valid",
        "Q4 runner authority is not physically valid",
    )
    _require(
        runner["validation_protocol_identity_sha256"]
        == validator["validation_protocol_identity_sha256"]
        and runner["input_schema_identity_sha256"]
        == validator["validation_input_schema_identity_sha256"]
        and runner["output_schema_identity_sha256"]
        == validator["validation_output_schema_identity_sha256"],
        "Q4 validator/runner protocol trust domain drifted",
    )
    runner_ref = _typed_ref(
        runner_descriptor,
        schema_version=1,
        kind="vast_backend_runtime_validation_runner_authority",
        identity=runner["runner_authority_sha256"],
    )
    _require(
        runner_ref == checked_plan["runner_authority"],
        "Q4 runner authority semantic plan pin drifted",
    )
    _require(
        runner["invocation_contract"]["invocation_sha256"]
        == checked_plan["runner_invocation_identity_sha256"],
        "Q4 runner invocation semantic plan pin drifted",
    )

    launchers: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for item in checked_plan["launcher_runtime_authorities"]:
        descriptor, value = _load_json(
            root,
            item["artifact"]["descriptor"]["path"],
            f"{item['system']} launcher runtime authority",
            custody=custody,
        )
        _require(
            descriptor == item["artifact"]["descriptor"],
            f"{item['system']} launcher authority raw descriptor pin drifted",
        )
        try:
            launcher = validate_backend_publication_launcher_runtime_authority(
                value,
                expected_authority_sha256=item["artifact"][
                    "content_identity_sha256"
                ],
                expected_system=item["system"],
                expected_publication_launcher_invocation_v3_sha256=invocation[
                    "invocation_sha256"
                ],
                expected_closure_manifest_sha256=item[
                    "closure_manifest_sha256"
                ],
                expected_runtime_closure_set_sha256=item[
                    "runtime_closure_set_sha256"
                ],
            )
            assessment = assess_backend_publication_launcher_runtime_authority(
                launcher,
                project_root=root,
                expected_authority_sha256=launcher[
                    "launcher_runtime_authority_sha256"
                ],
                expected_system=item["system"],
                expected_publication_launcher_invocation_v3_sha256=invocation[
                    "invocation_sha256"
                ],
                expected_closure_manifest_sha256=item[
                    "closure_manifest_sha256"
                ],
                expected_runtime_closure_set_sha256=item[
                    "runtime_closure_set_sha256"
                ],
            )
        except Exception as error:
            raise PublicationQ4RuntimeRegistryMaterializerV4Error(
                f"{item['system']} launcher runtime authority rejected: {error}"
            ) from error
        _require(
            assessment.get("status") == "physically_valid",
            f"{item['system']} launcher runtime authority is not physically valid",
        )
        _require(
            _typed_ref(
                descriptor,
                schema_version=1,
                kind=_LAUNCHER_AUTHORITY_KIND,
                identity=launcher["launcher_runtime_authority_sha256"],
            )
            == item["artifact"],
            f"{item['system']} launcher authority semantic plan pin drifted",
        )
        launchers[item["system"]] = (descriptor, launcher)

    loaded_authorities: list[dict[str, Any]] = []
    for position, item in enumerate(checked_plan["runtime_authorities"]):
        descriptor, value = _load_json(
            root,
            item["artifact"]["descriptor"]["path"],
            f"Q4 runtime authority[{position}]",
            custody=custody,
        )
        _require(
            descriptor == item["artifact"]["descriptor"],
            f"Q4 runtime authority[{position}] raw descriptor pin drifted",
        )
        coordinate = item["coordinate"]
        expected_policy_outputs = item["policy_outputs"]
        upstream = item["upstream_identities"]
        try:
            authority = validate_backend_publication_runtime_authority_v2(
                value,
                expected_system=coordinate["system"],
                expected_policy=coordinate["policy"],
                expected_topology_kind=coordinate["topology_kind"],
                expected_codec=coordinate["codec"],
                expected_upstream_identities=upstream,
                expected_policy_outputs=expected_policy_outputs,
            )
            assessment = assess_backend_publication_runtime_authority_v2(
                authority,
                project_root=root,
                expected_system=coordinate["system"],
                expected_policy=coordinate["policy"],
                expected_topology_kind=coordinate["topology_kind"],
                expected_codec=coordinate["codec"],
                expected_upstream_identities=upstream,
                expected_policy_outputs=expected_policy_outputs,
            )
        except Exception as error:
            raise PublicationQ4RuntimeRegistryMaterializerV4Error(
                f"Q4 runtime authority[{position}] rejected: {error}"
            ) from error
        _require(
            assessment.get("status") == "physically_valid",
            f"Q4 runtime authority[{position}] is not physically valid",
        )
        _require(
            authority["authority_sha256"]
            == item["artifact"]["content_identity_sha256"],
            f"Q4 runtime authority[{position}] semantic plan pin drifted",
        )
        template_record = authority.get("system_specific_launcher_input")
        _require(
            type(template_record) is dict
            and set(template_record) == {"content", "content_identity_sha256"}
            and type(template_record.get("content")) is dict
            and template_record.get("content_identity_sha256")
            == canonical_sha256(template_record["content"]),
            f"Q4 runtime authority[{position}] launcher input is not closed",
        )
        wrapper = validate_publication_q4_runtime_launcher_input_wrapper_v3(
            template_record["content"],
            expected_system=coordinate["system"],
            expected_policy=coordinate["policy"],
        )
        _require(
            publication_q4_runtime_launcher_input_expectations_v5(
                wrapper,
                expected_system=coordinate["system"],
                expected_policy=coordinate["policy"],
            )
            == item["launcher_input_expectations"],
            f"Q4 runtime authority[{position}] launcher-input plan pin drifted",
        )
        runtime_template = copy.deepcopy(
            wrapper["qualification_projection"]["runtime_input_template"]
        )
        expected_sources = dataset_descriptors[coordinate["codec"]]
        template_sources = runtime_template.get("source_files")
        _require(
            type(template_sources) is list and len(template_sources) == 2,
            f"Q4 runtime authority[{position}] source template coverage drifted",
        )
        projected_sources = [
            _source_descriptor(source, f"Q4 runtime authority[{position}]")
            for source in template_sources
        ]
        _require(
            {
                (source["path"], source["size_bytes"], source["sha256"])
                for source in projected_sources
            }
            == {
                (source["path"], source["size_bytes"], source["sha256"])
                for source in expected_sources
            },
            f"Q4 runtime authority[{position}] frozen dataset source drifted",
        )
        authority_dataset_files = authority.get("dataset", {}).get("files")
        _require(
            type(authority_dataset_files) is list
            and all(source in authority_dataset_files for source in expected_sources),
            f"Q4 runtime authority[{position}] dataset authority lacks sources",
        )
        loaded_authorities.append(
            {
                "coordinate": coordinate,
                "descriptor": descriptor,
                "artifact": copy.deepcopy(item["artifact"]),
                "authority": authority,
                "runtime_input_template": runtime_template,
            }
        )

    snapshots: list[dict[str, Any]] = []
    for system in SYSTEMS:
        system_items = [
            item
            for item in loaded_authorities
            if item["coordinate"]["system"] == system
        ]
        authority_records = [
            {
                "coordinate": copy.deepcopy(item["coordinate"]),
                "authority_ref": copy.deepcopy(item["artifact"]),
                "authority_sha256": item["authority"]["authority_sha256"],
            }
            for item in system_items
        ]
        set_sha = canonical_sha256(authority_records)
        launcher_descriptor, launcher = launchers[system]
        launcher_ref = copy.deepcopy(
            next(
                item["artifact"]
                for item in checked_plan["launcher_runtime_authorities"]
                if item["system"] == system
            )
        )
        binding_sha = runtime_binding_identity_v4(
            system=system,
            upstream_identities=system_items[0]["authority"][
                "upstream_identities"
            ],
            runtime_authority_set_sha256=set_sha,
            launcher_runtime_authority_sha256=launcher[
                "launcher_runtime_authority_sha256"
            ],
            publication_launcher_invocation_v3_sha256=invocation[
                "invocation_sha256"
            ],
        )
        for item, record in zip(system_items, authority_records):
            codec = item["coordinate"]["codec"]
            unsigned: dict[str, Any] = {
                "schema_version": RUNTIME_REGISTRY_SCHEMA_VERSION,
                "artifact_kind": "vast_publication_runtime_authority_snapshot_v4",
                "status": "physically_prepared_non_authorizing_runtime",
                "coordinate": copy.deepcopy(item["coordinate"]),
                "dataset_binding_sha256": datasets[CODECS.index(codec)][
                    "dataset_binding_sha256"
                ],
                "upstream_identities": copy.deepcopy(
                    item["authority"]["upstream_identities"]
                ),
                "runtime_authority_ref": record["authority_ref"],
                "runtime_authority_sha256": record["authority_sha256"],
                "runtime_authority_set_sha256": set_sha,
                "runtime_binding_identity_v4_sha256": binding_sha,
                "launcher_runtime_authority_ref": launcher_ref,
                "launcher_runtime_authority_sha256": launcher[
                    "launcher_runtime_authority_sha256"
                ],
                "publication_launcher_invocation_v3_ref": invocation_ref,
                "publication_launcher_invocation_v3": invocation,
                "q4_validator_authority_ref": validator_ref,
                "q4_validator_authority_sha256": validator["authority_sha256"],
                "runner_authority_ref": runner_ref,
                "runner_authority_sha256": runner[
                    "runner_authority_sha256"
                ],
                "runner_invocation_identity_sha256": runner[
                    "invocation_contract"
                ]["invocation_sha256"],
                "runtime_input_template": item["runtime_input_template"],
            }
            snapshots.append(
                {
                    **unsigned,
                    "authority_snapshot_sha256": canonical_sha256(unsigned),
                }
            )
    registry = build_publication_q4_runtime_candidate_registry_v4(
        dataset_bindings=datasets, authority_snapshots=snapshots
    )
    registry = validate_publication_q4_runtime_candidate_registry_against_plan_v5(
        registry,
        plan=checked_plan,
    )
    registry_payload = canonical_bytes(registry, newline=True)
    descriptor = _transaction_descriptor(
        root,
        output_path,
        registry_payload,
        label="Q4 runtime candidate registry output",
    )
    def registry_fault_step(step: str) -> None:
        _after_artifact_commit(
            after_artifact_commit,
            f"runtime_candidate_registry:{step}",
            custody=custody,
            watched_paths=[descriptor["path"]],
        )

    observed, registry_identity, registry_disposition = (
        custody.commit_or_adopt_exact_identity(
            descriptor["path"],
            registry_payload,
            label="Q4 runtime candidate registry",
            mode=0o444,
            create_parents=True,
            after_publish_step=(
                registry_fault_step if after_artifact_commit is not None else None
            ),
        )
    )
    _require(
        observed == descriptor,
        "Q4 runtime candidate registry committed/adopted descriptor drifted",
    )
    if registry_disposition == "published":
        _after_artifact_commit(
            after_artifact_commit,
            "runtime_candidate_registry",
            custody=custody,
            watched_paths=[descriptor["path"]],
        )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=descriptor,
        payload=registry_payload,
        label="pre-result Q4 runtime candidate registry",
        expected_identity=registry_identity,
    )
    result_unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RESULT_KIND,
        "status": "physically_materialized_non_authorizing_runtime_registry",
        "authorization_eligible": False,
        "execution_authorized": False,
        "plan_sha256": checked_plan["plan_sha256"],
        "runtime_candidate_registry": descriptor,
        "runtime_candidate_registry_sha256": registry["registry_sha256"],
        "dataset_binding_count": len(datasets),
        "runtime_authority_count": len(snapshots),
    }
    result = {
        **result_unsigned,
        "result_sha256": canonical_sha256(result_unsigned),
    }
    result_payload = canonical_bytes(result, newline=True)
    result_descriptor = _transaction_descriptor(
        root,
        result_output_path,
        result_payload,
        label="Q4 runtime materialization result output",
    )
    def result_fault_step(step: str) -> None:
        _after_artifact_commit(
            after_artifact_commit,
            f"runtime_materialization_result:{step}",
            custody=custody,
            watched_paths=[descriptor["path"], result_descriptor["path"]],
        )

    observed, result_identity, result_disposition = (
        custody.commit_or_adopt_exact_identity(
            result_descriptor["path"],
            result_payload,
            label="Q4 runtime materialization result",
            mode=0o444,
            create_parents=True,
            after_publish_step=(
                result_fault_step if after_artifact_commit is not None else None
            ),
        )
    )
    _require(
        observed == result_descriptor,
        "Q4 runtime materialization result committed/adopted descriptor drifted",
    )
    if result_disposition == "published":
        _after_artifact_commit(
            after_artifact_commit,
            "runtime_materialization_result",
            custody=custody,
            watched_paths=[descriptor["path"], result_descriptor["path"]],
        )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=descriptor,
        payload=registry_payload,
        label="committed Q4 runtime candidate registry",
        expected_identity=registry_identity,
    )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=result_descriptor,
        payload=result_payload,
        label="committed Q4 runtime materialization result",
        expected_identity=result_identity,
    )
    _result_descriptor, observed_result = _load_json(
        root,
        result_descriptor["path"],
        "Q4 runtime materialization result",
        custody=custody,
    )
    _require(
        _result_descriptor == result_descriptor and observed_result == result,
        "Q4 runtime materialization result changed after receipt-last commit",
    )
    return result


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Physically materialize public arbitrary-Q4 runtime registry v4"
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-file-sha256", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--result-output", required=True)
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parse_args(sys.argv[1:] if argv is None else argv)
        root = _root(arguments.project_root)
        plan_relative = Path(arguments.plan)
        if plan_relative.is_absolute():
            plan_relative = plan_relative.relative_to(root)
        descriptor, plan = _load_json(root, plan_relative.as_posix(), "Q4 plan")
        _require(
            descriptor["sha256"]
            == _sha(arguments.plan_file_sha256, "expected Q4 plan file"),
            "Q4 materialization plan file pin drifted",
        )
        checked = validate_publication_q4_runtime_materialization_plan_v4(plan)
        _require(
            checked["plan_sha256"]
            == _sha(arguments.plan_sha256, "expected Q4 plan semantic"),
            "Q4 materialization plan semantic pin drifted",
        )
        result = materialize_publication_q4_runtime_candidate_registry_v4(
            project_root=root,
            plan=checked,
            output_path=arguments.output,
            result_output_path=arguments.result_output,
        )
        sys.stdout.buffer.write(canonical_bytes(result, newline=True))
        sys.stdout.buffer.flush()
        return 0
    except Exception as error:
        diagnostic = (
            f"Q4 runtime registry materialization rejected: {error}\n"
        ).encode("ascii", errors="replace")[:4096]
        sys.stderr.buffer.write(diagnostic)
        sys.stderr.buffer.flush()
        return EXIT_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_REJECTED",
    "LAUNCHER_INPUT_PROJECTION_KIND",
    "LAUNCHER_INPUT_WRAPPER_KIND",
    "LAUNCHER_INPUT_WRAPPER_LAUNCHER_KIND",
    "LAUNCHER_INPUT_WRAPPER_SCHEMA_VERSION",
    "PLAN_KIND",
    "RESULT_KIND",
    "SCHEMA_VERSION",
    "PublicationQ4RuntimeRegistryMaterializerV4Error",
    "build_publication_q4_runtime_launcher_input_wrapper_v3",
    "build_publication_q4_runtime_materialization_plan_v4",
    "canonical_bytes",
    "canonical_sha256",
    "main",
    "materialize_publication_q4_runtime_candidate_registry_v4",
    "publication_q4_runtime_launcher_input_expectations_v5",
    "validate_publication_q4_runtime_candidate_registry_against_plan_v5",
    "validate_publication_q4_runtime_launcher_input_wrapper_v3",
    "validate_publication_q4_runtime_materialization_plan_v4",
]
