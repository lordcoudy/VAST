#!/usr/bin/env python3
"""Pure closed Q4 qualification-input graph; never authorizes execution."""
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
SCHEMA_VERSION = 4
ARTIFACT_KIND = "vast_backend_runtime_qualification_v4_input_index"
PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION = 3
PUBLICATION_LAUNCHER_INVOCATION_V3_KIND = (
    "vast_backend_publication_launcher_invocation_v3"
)
RUNTIME_AUTHORITY_SCHEMA_VERSION = 2
RUNTIME_AUTHORITY_KIND = "vast_backend_publication_runtime_authority_v2"
LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION = 1
LAUNCHER_RUNTIME_AUTHORITY_KIND = (
    "vast_backend_publication_launcher_runtime_authority"
)
UPSTREAM_IDENTITY_FIELDS = (
    "dataset_manifest_sha256", "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
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
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind",
    "descriptor", "content_identity_sha256",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "upstream_identities",
    "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256", "systems",
    "input_index_sha256",
})
_SYSTEM_FIELDS = frozenset({
    "system", "runtime_binding_identity_v4_sha256",
    "runtime_authority_set_sha256", "runtime_authorities",
    "launcher_runtime_authority_ref",
    "launcher_runtime_authority_sha256", "cells",
})
_AUTHORITY_FIELDS = frozenset({
    "coordinate", "authority_ref", "authority_sha256",
})
_AUTHORITY_COORDINATE_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy",
})
_CELL_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "cell_index", "runtime_authority_sha256", "raw_evidence_ref",
})


class BackendRuntimeQualificationV4InputIndexError(ValueError):
    """The Q4 qualification-input graph or an external pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeQualificationV4InputIndexError(message)


def _canonical_sha(value: object) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeQualificationV4InputIndexError(
            "Q4 input material is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
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


def _upstream(value: Any, label: str) -> dict[str, str]:
    _require(type(value) is dict
             and set(value) == set(UPSTREAM_IDENTITY_FIELDS),
             f"{label} upstream identity fields drifted")
    return {field: _sha(value[field], field)
            for field in UPSTREAM_IDENTITY_FIELDS}


def _pin_map(value: Any, label: str) -> dict[str, str]:
    _require(type(value) is dict and set(value) == set(SYSTEMS),
             f"{label} system membership drifted")
    return {system: _sha(value[system], f"{label} {system}")
            for system in SYSTEMS}


def runtime_binding_identity_v4(
    *, system: str, upstream_identities: Mapping[str, Any],
    runtime_authority_set_sha256: str,
    launcher_runtime_authority_sha256: str,
    publication_launcher_invocation_v3_sha256: str,
) -> str:
    """Bind exact Q4 upstream, ABI, authority-set, and launcher identities."""
    _require(type(system) is str and system in SYSTEMS,
             "runtime binding v4 system is invalid")
    return _canonical_sha({
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_backend_publication_runtime_binding_v4",
        "system": system,
        "upstream_identities": _upstream(upstream_identities, "binding"),
        "runtime_authority_set_sha256": _sha(
            runtime_authority_set_sha256, "runtime authority set"
        ),
        "launcher_runtime_authority_sha256": _sha(
            launcher_runtime_authority_sha256, "launcher runtime authority"
        ),
        "publication_launcher_invocation_v3_sha256": _sha(
            publication_launcher_invocation_v3_sha256,
            "publication launcher invocation v3",
        ),
    })


def _authority_coordinate(
    value: Any, *, expected_system: str,
) -> tuple[dict[str, str], tuple[str, str, str, str]]:
    _require(type(value) is dict and set(value) == _AUTHORITY_COORDINATE_FIELDS,
             "runtime authority coordinate fields drifted")
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    _require(type(system) is str and system == expected_system
             and codec in CODECS and topology in TOPOLOGIES
             and policy in POLICIES,
             "runtime authority coordinate is missing or relabelled")
    coordinate = {
        "system": system, "codec": codec,
        "topology_kind": topology, "policy": policy,
    }
    return coordinate, (system, codec, topology, policy)


def _authorities(
    value: Any, *, system: str,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], str]]:
    _require(type(value) is list and len(value) == 28,
             f"Q4 {system} requires exactly 28 runtime authorities")
    expected = sorted([
        (system, codec, topology, policy)
        for codec in CODECS for topology in TOPOLOGIES for policy in POLICIES
    ])
    checked: list[dict[str, Any]] = []
    coordinate_map: dict[tuple[str, str, str], str] = {}
    semantic: set[str] = set()
    for position, (raw, expected_coordinate) in enumerate(zip(value, expected)):
        _require(type(raw) is dict and set(raw) == _AUTHORITY_FIELDS,
                 f"Q4 authority[{position}] fields drifted")
        coordinate, coordinate_tuple = _authority_coordinate(
            raw.get("coordinate"), expected_system=system,
        )
        _require(coordinate_tuple == expected_coordinate,
                 "runtime authority order/coverage drifted")
        authority_ref = _typed_ref(
            raw.get("authority_ref"), "runtime authority",
            schema_version=RUNTIME_AUTHORITY_SCHEMA_VERSION,
            artifact_kind=RUNTIME_AUTHORITY_KIND,
        )
        authority_sha = _sha(raw.get("authority_sha256"),
                             "runtime authority")
        _require(authority_ref["content_identity_sha256"] == authority_sha,
                 "runtime authority reference semantic identity drifted")
        _require(authority_sha not in semantic,
                 "runtime authority semantic identity is duplicated")
        semantic.add(authority_sha)
        coordinate_map[coordinate_tuple[1:]] = authority_sha
        checked.append({
            "coordinate": coordinate,
            "authority_ref": authority_ref,
            "authority_sha256": authority_sha,
        })
    return checked, coordinate_map


def _deadline_position(value: Any) -> int:
    _require(type(value) in {int, float} and math.isfinite(float(value)),
             "Q4 deadline type drifted")
    positions = [
        index for index, expected in enumerate(DEADLINES_MS)
        if type(value) is type(expected) and value == expected
    ]
    _require(len(positions) == 1, "Q4 deadline value/type drifted")
    return positions[0]


def _cell_coordinate(
    value: Mapping[str, Any], *, expected_system: str,
) -> tuple[dict[str, Any], tuple[str, str, str], int]:
    system = value.get("system")
    codec = value.get("codec")
    topology = value.get("topology_kind")
    policy = value.get("policy")
    deadline = value.get("deadline_ms")
    cell_index = value.get("cell_index")
    _require(type(system) is str and system == expected_system
             and codec in CODECS and topology in TOPOLOGIES
             and policy in POLICIES,
             "Q4 cell coordinate is missing or relabelled")
    deadline_index = _deadline_position(deadline)
    expected_index = (((
        (SYSTEMS.index(system) * len(CODECS) + CODECS.index(codec))
        * len(TOPOLOGIES) + TOPOLOGIES.index(topology)
    ) * len(POLICIES) + POLICIES.index(policy)
    ) * len(DEADLINES_MS) + deadline_index)
    _require(type(cell_index) is int and cell_index == expected_index,
             "Q4 cell index does not match the global coordinate ordinal")
    coordinate = {
        "system": system, "codec": codec, "topology_kind": topology,
        "policy": policy, "deadline_ms": deadline, "cell_index": cell_index,
    }
    return coordinate, (codec, topology, policy), deadline_index


def _cells(
    value: Any, *, system: str,
    authority_by_coordinate: Mapping[tuple[str, str, str], str],
) -> list[dict[str, Any]]:
    _require(type(value) is list and len(value) == 140,
             f"Q4 {system} requires exactly 140 cells")
    checked: list[dict[str, Any]] = []
    uses: dict[str, set[int]] = {}
    first_index = SYSTEMS.index(system) * 140
    for position, raw in enumerate(value):
        _require(type(raw) is dict and set(raw) == _CELL_FIELDS,
                 f"Q4 cell[{position}] fields drifted")
        coordinate, authority_coordinate, deadline_index = _cell_coordinate(
            raw, expected_system=system,
        )
        _require(coordinate["cell_index"] == first_index + position,
                 "Q4 cell order/coverage drifted")
        authority_sha = _sha(raw.get("runtime_authority_sha256"),
                             "Q4 cell runtime authority")
        _require(authority_sha == authority_by_coordinate.get(authority_coordinate),
                 "Q4 cell/runtime-authority cross-binding drifted")
        evidence = _ref(raw.get("raw_evidence_ref"), "raw evidence")
        checked.append({
            **coordinate,
            "runtime_authority_sha256": authority_sha,
            "raw_evidence_ref": evidence,
        })
        uses.setdefault(authority_sha, set()).add(deadline_index)
    _require(len(uses) == 28
             and all(deadlines == set(range(5)) for deadlines in uses.values()),
             "each Q4 runtime authority must bind exactly five deadlines")
    return checked


def _references(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    references = [value["publication_launcher_invocation_v3_ref"]]
    for system in value["systems"]:
        references.append(system["launcher_runtime_authority_ref"])
        references.extend(item["authority_ref"]
                          for item in system["runtime_authorities"])
        references.extend(item["raw_evidence_ref"] for item in system["cells"])
    return references


def _unique_references(
    references: Sequence[Mapping[str, Any]], *, reserved_semantic: set[str],
) -> None:
    paths: set[str] = set()
    file_shas: set[str] = set()
    content_shas: set[str] = set()
    serialized: set[str] = set()
    for reference in references:
        descriptor = reference["descriptor"]
        path = descriptor["path"]
        file_sha = descriptor["sha256"]
        content_sha = reference["content_identity_sha256"]
        encoded = json.dumps(
            reference, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        )
        path_collision_key = path.casefold()
        _require(path_collision_key not in paths,
                 "Q4 artifact reference path is duplicated")
        _require(file_sha not in file_shas,
                 "Q4 artifact reference file identity is duplicated")
        _require(content_sha not in content_shas,
                 "Q4 artifact reference content identity is duplicated")
        _require(encoded not in serialized,
                 "Q4 artifact reference is duplicated")
        _require(content_sha not in reserved_semantic,
                 "Q4 artifact reference forms a reserved identity cycle")
        paths.add(path_collision_key)
        file_shas.add(file_sha)
        content_shas.add(content_sha)
        serialized.add(encoded)


def _validate_system(
    value: Any, *, expected_system: str, upstream: Mapping[str, Any],
    abi_sha: str, expected_binding_sha: str, expected_set_sha: str,
    expected_launcher_sha: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _SYSTEM_FIELDS,
             f"Q4 {expected_system} system fields drifted")
    _require(type(value.get("system")) is str
             and value.get("system") == expected_system,
             "Q4 system order/membership drifted")
    authorities, authority_map = _authorities(
        value.get("runtime_authorities"), system=expected_system,
    )
    authority_set_sha = _canonical_sha(authorities)
    _require(_sha(value.get("runtime_authority_set_sha256"),
                  "runtime authority set") == authority_set_sha
             == expected_set_sha,
             "Q4 runtime authority set identity drifted")
    launcher_ref = _typed_ref(
        value.get("launcher_runtime_authority_ref"),
        "launcher runtime authority",
        schema_version=LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION,
        artifact_kind=LAUNCHER_RUNTIME_AUTHORITY_KIND,
    )
    launcher_sha = _sha(value.get("launcher_runtime_authority_sha256"),
                        "launcher runtime authority")
    _require(launcher_ref["content_identity_sha256"] == launcher_sha
             == expected_launcher_sha,
             "Q4 launcher runtime authority identity drifted")
    binding = runtime_binding_identity_v4(
        system=expected_system, upstream_identities=upstream,
        runtime_authority_set_sha256=authority_set_sha,
        launcher_runtime_authority_sha256=launcher_sha,
        publication_launcher_invocation_v3_sha256=abi_sha,
    )
    _require(_sha(value.get("runtime_binding_identity_v4_sha256"),
                  "runtime binding v4") == binding == expected_binding_sha,
             "Q4 runtime binding identity v4 drifted")
    cells = _cells(value.get("cells"), system=expected_system,
                   authority_by_coordinate=authority_map)
    return {
        "system": expected_system,
        "runtime_binding_identity_v4_sha256": binding,
        "runtime_authority_set_sha256": authority_set_sha,
        "runtime_authorities": authorities,
        "launcher_runtime_authority_ref": launcher_ref,
        "launcher_runtime_authority_sha256": launcher_sha,
        "cells": cells,
    }


def validate_backend_runtime_qualification_v4_input_index(
    value: Any, *, expected_semantic_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runtime_binding_identity_v4_sha256_by_system: Mapping[str, Any],
    expected_runtime_authority_set_sha256_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256_by_system: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a Q4 input graph against all mandatory external pins."""
    semantic_pin = _sha(expected_semantic_sha256, "expected Q4 input index")
    expected_upstream = _upstream(
        expected_upstream_identities, "expected"
    )
    abi_pin = _sha(
        expected_publication_launcher_invocation_v3_sha256,
        "expected publication launcher invocation v3",
    )
    binding_pins = _pin_map(
        expected_runtime_binding_identity_v4_sha256_by_system,
        "expected runtime binding v4",
    )
    set_pins = _pin_map(
        expected_runtime_authority_set_sha256_by_system,
        "expected runtime authority set",
    )
    launcher_pins = _pin_map(
        expected_launcher_runtime_authority_sha256_by_system,
        "expected launcher runtime authority",
    )
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "Q4 input index fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "Q4 input index header drifted")
    upstream = _upstream(value.get("upstream_identities"), "Q4 input")
    _require(upstream == expected_upstream,
             "Q4 input upstream identities do not match external pins")
    abi_ref = _typed_ref(
        value.get("publication_launcher_invocation_v3_ref"),
        "publication launcher invocation v3",
        schema_version=PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION,
        artifact_kind=PUBLICATION_LAUNCHER_INVOCATION_V3_KIND,
    )
    abi_sha = _sha(value.get("publication_launcher_invocation_v3_sha256"),
                   "publication launcher invocation v3")
    _require(abi_ref["content_identity_sha256"] == abi_sha == abi_pin,
             "Q4 publication launcher invocation v3 identity drifted")
    raw_systems = value.get("systems")
    _require(type(raw_systems) is list and len(raw_systems) == len(SYSTEMS),
             "Q4 input requires exactly four systems")
    systems = [
        _validate_system(
            raw_systems[position], expected_system=system,
            upstream=upstream, abi_sha=abi_sha,
            expected_binding_sha=binding_pins[system],
            expected_set_sha=set_pins[system],
            expected_launcher_sha=launcher_pins[system],
        )
        for position, system in enumerate(SYSTEMS)
    ]
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "upstream_identities": upstream,
        "publication_launcher_invocation_v3_ref": abi_ref,
        "publication_launcher_invocation_v3_sha256": abi_sha,
        "systems": systems,
    }
    index_sha = _sha(value.get("input_index_sha256"), "Q4 input index")
    _require(index_sha == _canonical_sha(normalized) == semantic_pin,
             "Q4 input index semantic identity drifted")
    normalized["input_index_sha256"] = index_sha
    reserved = {
        index_sha, *upstream.values(),
        *binding_pins.values(), *set_pins.values(),
    }
    _unique_references(_references(normalized), reserved_semantic=reserved)
    authority_semantics = {
        item["authority_sha256"]
        for system in systems for item in system["runtime_authorities"]
    }
    _require(len(authority_semantics) == 112,
             "Q4 runtime authorities are not globally unique")
    return copy.deepcopy(normalized)


def build_backend_runtime_qualification_v4_input_index(
    *, upstream_identities: Mapping[str, Any],
    publication_launcher_invocation_v3_ref: Mapping[str, Any],
    systems: Sequence[Mapping[str, Any]], expected_semantic_sha256: str,
    expected_upstream_identities: Mapping[str, Any],
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_runtime_binding_identity_v4_sha256_by_system: Mapping[str, Any],
    expected_runtime_authority_set_sha256_by_system: Mapping[str, Any],
    expected_launcher_runtime_authority_sha256_by_system: Mapping[str, Any],
) -> dict[str, Any]:
    """Build in memory and accept only the externally pinned Q4 input graph."""
    abi_ref = copy.deepcopy(publication_launcher_invocation_v3_ref)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "upstream_identities": copy.deepcopy(upstream_identities),
        "publication_launcher_invocation_v3_ref": abi_ref,
        "publication_launcher_invocation_v3_sha256": (
            abi_ref.get("content_identity_sha256")
            if type(abi_ref) is dict else None
        ),
        "systems": copy.deepcopy(list(systems)),
    }
    value["input_index_sha256"] = _canonical_sha(value)
    return validate_backend_runtime_qualification_v4_input_index(
        value, expected_semantic_sha256=expected_semantic_sha256,
        expected_upstream_identities=expected_upstream_identities,
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_runtime_binding_identity_v4_sha256_by_system=(
            expected_runtime_binding_identity_v4_sha256_by_system
        ),
        expected_runtime_authority_set_sha256_by_system=(
            expected_runtime_authority_set_sha256_by_system
        ),
        expected_launcher_runtime_authority_sha256_by_system=(
            expected_launcher_runtime_authority_sha256_by_system
        ),
    )


__all__ = [
    "ARTIFACT_KIND", "SCHEMA_VERSION", "SYSTEMS", "CODECS", "TOPOLOGIES",
    "POLICIES", "DEADLINES_MS", "UPSTREAM_IDENTITY_FIELDS",
    "PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION",
    "PUBLICATION_LAUNCHER_INVOCATION_V3_KIND",
    "RUNTIME_AUTHORITY_SCHEMA_VERSION", "RUNTIME_AUTHORITY_KIND",
    "LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION",
    "LAUNCHER_RUNTIME_AUTHORITY_KIND",
    "BackendRuntimeQualificationV4InputIndexError",
    "runtime_binding_identity_v4",
    "build_backend_runtime_qualification_v4_input_index",
    "validate_backend_runtime_qualification_v4_input_index",
]
