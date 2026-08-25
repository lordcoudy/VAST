#!/usr/bin/env python3
"""Fail-closed backend runtime grant derived from validated identity artifacts.

The grant is pre-run authorization material only.  It does not accept a
benchmark arm and it does not change runtime readiness or dispatch policy.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Mapping

from backend_publication_dispatch import (
    runtime_binding_identity,
    validate_launcher_invocation,
)
from backend_publication_launcher_invocation_v3 import (
    validate_publication_launcher_invocation_v3,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)

SCHEMA_VERSION = 2
GRANT_KIND = "vast_verified_pre_run_backend_runtime_grant"
GRANT_STATUS = "accepted_pre_run_backend_runtime_qualification_v2"
PUBLICATION_SCOPE = "backend_native_runtime_evidence_backed_cells_v2"
GRANT_V3_KIND = "vast_verified_pre_run_backend_runtime_grant_v3"
GRANT_V3_STATUS = "accepted_persisted_physical_q4_qualification"
PUBLICATION_SCOPE_V3 = "backend_native_runtime_authenticated_q4_v3"
PRODUCTION_RECEIPT_PROTOCOL_KIND = (
    "vast_backend_publication_production_output_receipt_protocol_binding_v3"
)

UPSTREAM_IDENTITY_FIELDS = frozenset(
    {
        "dataset_manifest_sha256",
        "policy_contract_sha256",
        "policy_qualification_receipt_sha256",
        "resource_contract_identity_sha256",
        "resource_qualification_receipt_sha256",
        "analytics_execution_config_identity_sha256",
        "model_parity_manifest_identity_sha256",
        "model_parity_acceptance_binding_sha256",
    }
)
SYSTEM_FIELDS = frozenset(
    {
        "system",
        "runtime_binding_identity_sha256",
        "launcher",
        "launcher_invocation",
        "launcher_kind",
        "publication_capable",
        "qualified_cells",
        "qualified_cells_sha256",
        "raw_evidence_set_sha256",
    }
)
CELL_FIELDS = frozenset(
    {
        "system",
        "codec",
        "topology_kind",
        "policy",
        "deadline_ms",
        "cell_identity_sha256",
        "raw_evidence",
        "launcher_invocation_sha256",
        "validator_identity_sha256",
        "validation_record_sha256",
    }
)
COVERAGE_FIELDS = frozenset(
    {"system_count", "runtime_cell_count", "cells_per_system"}
)
GRANT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "publication_scope",
        "identity_artifact_binding_sha256",
        "qualification_index_sha256",
        "qualification_binding_index",
        "qualification_receipts",
        "upstream_identities",
        "systems",
        "coverage",
        "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated",
        "grant_sha256",
    }
)
IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "manifest",
        "bindings",
        "files",
        "files_sha256",
        "binding_sha256",
    }
)
BACKEND_V2_FIELDS = frozenset(
    {
        "schema_version",
        "qualification_index_sha256",
        "binding_index",
        "receipts",
        "upstream_identities",
        "systems",
        "coverage",
        "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated",
    }
)
_SHA_RE = re.compile(r"[0-9a-f]{64}")

GRANT_V3_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "publication_scope",
    "identity_artifact_binding_sha256", "qualification_index_sha256",
    "catalog_sha256", "validator_identity_sha256",
    "qualification_binding_index", "qualification_receipts",
    "upstream_identities", "production_output_receipt_protocol", "systems",
    "coverage", "post_run_per_arm_evidence_required",
    "configuration_evidence_accepted_mutated", "grant_sha256",
})
SYSTEM_V3_FIELDS = frozenset({
    "system", "runtime_binding_identity_sha256",
    "runtime_authority_set_sha256", "runtime_authorities",
    "launcher_runtime_authority", "launcher_runtime_authority_sha256",
    "launcher", "launcher_invocation", "launcher_kind",
    "publication_capable", "qualified_cells", "qualified_cells_sha256",
    "raw_evidence_set_sha256",
})
AUTHORITY_V3_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "artifact",
    "runtime_authority_sha256",
})
CELL_V3_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "cell_identity_sha256", "runtime_authority_sha256", "raw_evidence",
    "launcher_invocation_sha256", "validator_identity_sha256",
    "validation_record_sha256",
})
COVERAGE_V3 = {
    "system_count": 4,
    "runtime_authority_count": 112,
    "runtime_authorities_per_system": 28,
    "runtime_cell_count": 560,
    "cells_per_system": 140,
    "validation_request_count": 560,
    "validation_record_count": 560,
}
_PROTOCOL_FILE_PATHS = {
    "full_publication_entrypoint": "scripts/full_publication_entrypoint.py",
    "production_output_transaction": (
        "scripts/backend_publication_output_transaction_production_v3.py"
    ),
    "engineering_output_transaction": (
        "scripts/backend_publication_output_transaction_v3.py"
    ),
    "dispatch_abi": "scripts/backend_publication_dispatch_v3.py",
    "process_supervisor": "scripts/backend_publication_process_supervisor_v3.py",
}


class BackendRuntimeGrantError(RuntimeError):
    """Backend qualification identity or grant is incomplete or unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BackendRuntimeGrantError(
            "backend runtime grant material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        raise BackendRuntimeGrantError(f"{label} descriptor fields drifted")
    path = value.get("path")
    size = value.get("size_bytes")
    if (
        type(path) is not str
        or not path
        or "\\" in path
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or type(size) is not int
        or size <= 0
        or not _valid_sha(value.get("sha256"))
    ):
        raise BackendRuntimeGrantError(f"{label} descriptor is invalid")
    return copy.deepcopy(value)


def _expected_coordinates(
    system: str,
) -> set[tuple[str, str, str, str, int | float]]:
    return {
        (system, codec, topology, policy, deadline)
        for codec in CODECS
        for topology in TOPOLOGIES
        for policy in POLICIES
        for deadline in DEADLINES_MS
    }


def _validate_coverage(value: Any) -> dict[str, int]:
    if type(value) is not dict or set(value) != COVERAGE_FIELDS:
        raise BackendRuntimeGrantError("backend grant coverage fields drifted")
    expected = {
        "system_count": len(SYSTEMS),
        "runtime_cell_count": 560,
        "cells_per_system": 140,
    }
    if value != expected:
        raise BackendRuntimeGrantError("backend grant coverage drifted")
    return copy.deepcopy(value)


def _validate_system_binding(
    value: Any,
    *,
    system: str,
    upstream_identities: Mapping[str, Any],
    known_files: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != SYSTEM_FIELDS:
        raise BackendRuntimeGrantError(f"backend system {system} fields drifted")
    if value.get("system") != system or not _valid_sha(
        value.get("runtime_binding_identity_sha256")
    ):
        raise BackendRuntimeGrantError(f"backend system {system} identity drifted")
    if (
        value.get("launcher_kind") != "dedicated_publication_runtime"
        or value.get("publication_capable") is not True
    ):
        raise BackendRuntimeGrantError(
            f"backend system {system} launcher is not publication capable"
        )
    launcher = _descriptor(value.get("launcher"), f"backend system {system} launcher")
    if known_files is not None and known_files.get(launcher["path"]) != launcher:
        raise BackendRuntimeGrantError(
            f"backend system {system} launcher descriptor is unbound"
        )
    try:
        launcher_invocation = validate_launcher_invocation(
            value.get("launcher_invocation")
        )
    except Exception as error:
        raise BackendRuntimeGrantError(
            f"backend system {system} launcher invocation is invalid: {error}"
        ) from error
    if value.get("runtime_binding_identity_sha256") != runtime_binding_identity(
        system=system,
        launcher=launcher,
        launcher_invocation=launcher_invocation,
        upstream_identities=upstream_identities,
    ):
        raise BackendRuntimeGrantError(
            f"backend system {system} runtime binding identity drifted"
        )

    cells = value.get("qualified_cells")
    if type(cells) is not list or len(cells) != 140:
        raise BackendRuntimeGrantError(
            f"backend system {system} must contain exactly 140 qualified cells"
        )
    expected = _expected_coordinates(system)
    observed: set[tuple[str, str, str, str, int | float]] = set()
    normalized_cells: list[dict[str, Any]] = []
    evidence_descriptors: list[dict[str, Any]] = []
    evidence_paths: set[str] = set()
    for position, raw in enumerate(cells):
        if type(raw) is not dict or set(raw) != CELL_FIELDS:
            raise BackendRuntimeGrantError(
                f"backend system {system} cell[{position}] fields drifted"
            )
        deadline = raw.get("deadline_ms")
        if (
            type(deadline) not in {int, float}
            or not math.isfinite(float(deadline))
            or deadline not in DEADLINES_MS
        ):
            raise BackendRuntimeGrantError(
                f"backend system {system} cell[{position}] deadline drifted"
            )
        coordinate = (
            str(raw.get("system")),
            str(raw.get("codec")),
            str(raw.get("topology_kind")),
            str(raw.get("policy")),
            deadline,
        )
        if coordinate not in expected or coordinate in observed:
            raise BackendRuntimeGrantError(
                f"backend system {system} cell is missing, duplicate, or relabelled"
            )
        coordinate_payload = {
            "system": coordinate[0],
            "codec": coordinate[1],
            "topology_kind": coordinate[2],
            "policy": coordinate[3],
            "deadline_ms": coordinate[4],
        }
        if raw.get("cell_identity_sha256") != _canonical_sha(coordinate_payload):
            raise BackendRuntimeGrantError(
                f"backend system {system} cell identity drifted"
            )
        evidence = _descriptor(
            raw.get("raw_evidence"),
            f"backend system {system} cell[{position}] raw evidence",
        )
        if evidence["path"] in evidence_paths:
            raise BackendRuntimeGrantError(
                f"backend system {system} raw evidence alias is prohibited"
            )
        if known_files is not None and known_files.get(evidence["path"]) != evidence:
            raise BackendRuntimeGrantError(
                f"backend system {system} raw evidence descriptor is unbound"
            )
        if not _valid_sha(raw.get("validator_identity_sha256")) or not _valid_sha(
            raw.get("validation_record_sha256")
        ):
            raise BackendRuntimeGrantError(
                f"backend system {system} raw validation identity is invalid"
            )
        if (
            raw.get("launcher_invocation_sha256")
            != launcher_invocation["invocation_sha256"]
        ):
            raise BackendRuntimeGrantError(
                f"backend system {system} cell launcher invocation binding drifted"
            )
        observed.add(coordinate)
        evidence_paths.add(evidence["path"])
        normalized = copy.deepcopy(raw)
        normalized["raw_evidence"] = evidence
        normalized_cells.append(normalized)
        evidence_descriptors.append(evidence)
    if observed != expected:
        raise BackendRuntimeGrantError(
            f"backend system {system} qualified cell coverage mismatch"
        )
    if value.get("qualified_cells_sha256") != _canonical_sha(normalized_cells):
        raise BackendRuntimeGrantError(
            f"backend system {system} qualified cell set hash drifted"
        )
    if value.get("raw_evidence_set_sha256") != _canonical_sha(evidence_descriptors):
        raise BackendRuntimeGrantError(
            f"backend system {system} raw evidence set hash drifted"
        )
    return {
        "system": system,
        "runtime_binding_identity_sha256": value["runtime_binding_identity_sha256"],
        "launcher": launcher,
        "launcher_invocation": launcher_invocation,
        "launcher_kind": "dedicated_publication_runtime",
        "publication_capable": True,
        "qualified_cells": normalized_cells,
        "qualified_cells_sha256": value["qualified_cells_sha256"],
        "raw_evidence_set_sha256": value["raw_evidence_set_sha256"],
    }


def _validate_nested_grant(
    value: Mapping[str, Any],
    *,
    known_files: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise BackendRuntimeGrantError("backend grant schema version mismatch")
    if value.get("artifact_kind") != GRANT_KIND:
        raise BackendRuntimeGrantError("backend grant artifact kind mismatch")
    if value.get("status") != GRANT_STATUS:
        raise BackendRuntimeGrantError("backend grant status mismatch")
    if value.get("publication_scope") != PUBLICATION_SCOPE:
        raise BackendRuntimeGrantError("backend grant publication scope mismatch")
    if not _valid_sha(value.get("identity_artifact_binding_sha256")):
        raise BackendRuntimeGrantError("backend grant identity binding is invalid")
    if not _valid_sha(value.get("qualification_index_sha256")):
        raise BackendRuntimeGrantError("backend qualification index identity is invalid")
    binding_index = _descriptor(
        value.get("qualification_binding_index"),
        "backend qualification binding index",
    )
    if known_files is not None and known_files.get(binding_index["path"]) != binding_index:
        raise BackendRuntimeGrantError("backend qualification binding index is unbound")
    receipts = value.get("qualification_receipts")
    if type(receipts) is not dict or set(receipts) != set(SYSTEMS):
        raise BackendRuntimeGrantError("backend qualification receipt set drifted")
    normalized_receipts = {}
    for system in SYSTEMS:
        item = _descriptor(receipts[system], f"backend qualification receipt {system}")
        if known_files is not None and known_files.get(item["path"]) != item:
            raise BackendRuntimeGrantError(
                f"backend qualification receipt {system} is unbound"
            )
        normalized_receipts[system] = item
    upstream = value.get("upstream_identities")
    if type(upstream) is not dict or set(upstream) != UPSTREAM_IDENTITY_FIELDS:
        raise BackendRuntimeGrantError("backend upstream identity fields drifted")
    if not all(_valid_sha(item) for item in upstream.values()):
        raise BackendRuntimeGrantError("backend upstream identity is invalid")
    systems = value.get("systems")
    if type(systems) is not dict or set(systems) != set(SYSTEMS):
        raise BackendRuntimeGrantError("backend grant system set drifted")
    normalized_systems = {
        system: _validate_system_binding(
            systems[system],
            system=system,
            upstream_identities=upstream,
            known_files=known_files,
        )
        for system in SYSTEMS
    }
    coverage = _validate_coverage(value.get("coverage"))
    if value.get("post_run_per_arm_evidence_required") is not True:
        raise BackendRuntimeGrantError("backend grant post-run boundary drifted")
    if value.get("configuration_evidence_accepted_mutated") is not False:
        raise BackendRuntimeGrantError("backend grant config boundary drifted")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": GRANT_KIND,
        "status": GRANT_STATUS,
        "publication_scope": PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": value["identity_artifact_binding_sha256"],
        "qualification_index_sha256": value["qualification_index_sha256"],
        "qualification_binding_index": binding_index,
        "qualification_receipts": normalized_receipts,
        "upstream_identities": copy.deepcopy(upstream),
        "systems": normalized_systems,
        "coverage": coverage,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }


def _validate_production_receipt_protocol_v3(
    value: Any, *, systems: Mapping[str, Mapping[str, Any]],
    known_files: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    fields = {
        "schema_version", "artifact_kind", "execution_scope", "receipt_kind",
        "receipt_authority_kind", "atomicity",
        "parent_owned_transaction_required",
        "semantic_evidence_validation_required", "protocol_files", "systems",
        "protocol_binding_sha256",
    }
    if (
        type(value) is not dict or set(value) != fields
        or value.get("schema_version") != 3
        or value.get("artifact_kind") != PRODUCTION_RECEIPT_PROTOCOL_KIND
        or value.get("execution_scope") != "full_publication_measurement_v3"
        or value.get("receipt_kind")
        != "vast_backend_publication_production_output_receipt_v3"
        or value.get("receipt_authority_kind")
        != "vast_backend_publication_production_output_receipt_authority_v3"
        or value.get("atomicity")
        != "launcher_result_then_output_receipt_last_v3"
        or value.get("parent_owned_transaction_required") is not True
        or value.get("semantic_evidence_validation_required") is not True
    ):
        raise BackendRuntimeGrantError(
            "production-v3 output receipt protocol fields drifted"
        )
    raw_files = value.get("protocol_files")
    if type(raw_files) is not dict or set(raw_files) != set(_PROTOCOL_FILE_PATHS):
        raise BackendRuntimeGrantError(
            "production-v3 output receipt protocol file set drifted"
        )
    files: dict[str, dict[str, Any]] = {}
    for role, expected_path in _PROTOCOL_FILE_PATHS.items():
        descriptor = _descriptor(
            raw_files[role], f"production-v3 receipt protocol {role}",
        )
        if descriptor["path"] != expected_path:
            raise BackendRuntimeGrantError(
                f"production-v3 receipt protocol {role} path drifted"
            )
        if known_files is not None and known_files.get(expected_path) != descriptor:
            raise BackendRuntimeGrantError(
                f"production-v3 receipt protocol {role} is unbound"
            )
        files[role] = descriptor
    raw_systems = value.get("systems")
    if type(raw_systems) is not dict or set(raw_systems) != set(SYSTEMS):
        raise BackendRuntimeGrantError(
            "production-v3 output receipt protocol system set drifted"
        )
    protocol_systems: dict[str, dict[str, Any]] = {}
    protocol_system_fields = {
        "launcher", "launcher_runtime_authority_descriptor",
        "launcher_runtime_authority_sha256", "launcher_invocation_sha256",
    }
    for system in SYSTEMS:
        item = raw_systems[system]
        if type(item) is not dict or set(item) != protocol_system_fields:
            raise BackendRuntimeGrantError(
                f"production-v3 receipt protocol {system} fields drifted"
            )
        launcher = _descriptor(
            item["launcher"], f"production-v3 receipt protocol {system} launcher",
        )
        authority = _descriptor(
            item["launcher_runtime_authority_descriptor"],
            f"production-v3 receipt protocol {system} launcher authority",
        )
        if (
            launcher != systems[system]["launcher"]
            or authority != systems[system]["launcher_runtime_authority"]
            or item.get("launcher_runtime_authority_sha256")
            != systems[system]["launcher_runtime_authority_sha256"]
            or item.get("launcher_invocation_sha256")
            != systems[system]["launcher_invocation"]["invocation_sha256"]
            or not _valid_sha(item.get("launcher_runtime_authority_sha256"))
        ):
            raise BackendRuntimeGrantError(
                f"production-v3 receipt protocol {system} launcher binding drifted"
            )
        if known_files is not None and (
            known_files.get(launcher["path"]) != launcher
            or known_files.get(authority["path"]) != authority
        ):
            raise BackendRuntimeGrantError(
                f"production-v3 receipt protocol {system} physical binding is missing"
            )
        protocol_systems[system] = {
            "launcher": launcher,
            "launcher_runtime_authority_descriptor": authority,
            "launcher_runtime_authority_sha256": item[
                "launcher_runtime_authority_sha256"
            ],
            "launcher_invocation_sha256": item["launcher_invocation_sha256"],
        }
    normalized: dict[str, Any] = {
        "schema_version": 3,
        "artifact_kind": PRODUCTION_RECEIPT_PROTOCOL_KIND,
        "execution_scope": "full_publication_measurement_v3",
        "receipt_kind": "vast_backend_publication_production_output_receipt_v3",
        "receipt_authority_kind": (
            "vast_backend_publication_production_output_receipt_authority_v3"
        ),
        "atomicity": "launcher_result_then_output_receipt_last_v3",
        "parent_owned_transaction_required": True,
        "semantic_evidence_validation_required": True,
        "protocol_files": files,
        "systems": protocol_systems,
    }
    if value.get("protocol_binding_sha256") != _canonical_sha(normalized):
        raise BackendRuntimeGrantError(
            "production-v3 output receipt protocol self-hash drifted"
        )
    normalized["protocol_binding_sha256"] = value["protocol_binding_sha256"]
    return normalized


def _validate_system_binding_v3(
    value: Any, *, system: str,
    known_files: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if (
        type(value) is not dict or set(value) != SYSTEM_V3_FIELDS
        or value.get("system") != system
        or value.get("launcher_kind") != "dedicated_publication_runtime_v3"
        or value.get("publication_capable") is not True
        or not _valid_sha(value.get("runtime_binding_identity_sha256"))
        or not _valid_sha(value.get("runtime_authority_set_sha256"))
        or not _valid_sha(value.get("launcher_runtime_authority_sha256"))
    ):
        raise BackendRuntimeGrantError(
            f"backend Q4 grant system {system} fields drifted"
        )
    launcher = _descriptor(value.get("launcher"), f"backend Q4 {system} launcher")
    launcher_authority = _descriptor(
        value.get("launcher_runtime_authority"),
        f"backend Q4 {system} launcher authority",
    )
    if known_files is not None and (
        known_files.get(launcher["path"]) != launcher
        or known_files.get(launcher_authority["path"]) != launcher_authority
    ):
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} launcher closure is unbound"
        )
    try:
        invocation = validate_publication_launcher_invocation_v3(
            value.get("launcher_invocation")
        )
    except Exception as error:
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} launcher invocation is invalid: {error}"
        ) from error
    if launcher["path"] != f"scripts/checkpoint_{system}_publication_launcher_v3.py":
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} launcher path is not production ABI-v3"
        )

    raw_authorities = value.get("runtime_authorities")
    if type(raw_authorities) is not list or len(raw_authorities) != 28:
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} requires exactly 28 runtime authorities"
        )
    expected_authorities = {
        (system, codec, topology, policy)
        for codec in CODECS for topology in TOPOLOGIES for policy in POLICIES
    }
    observed_authorities: dict[tuple[str, str, str, str], str] = {}
    authorities: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_authorities):
        if type(raw) is not dict or set(raw) != AUTHORITY_V3_FIELDS:
            raise BackendRuntimeGrantError(
                f"backend Q4 {system} authority[{position}] fields drifted"
            )
        coordinate = tuple(str(raw.get(field)) for field in (
            "system", "codec", "topology_kind", "policy",
        ))
        identity = raw.get("runtime_authority_sha256")
        artifact = _descriptor(
            raw.get("artifact"), f"backend Q4 {system} authority[{position}]",
        )
        if (
            coordinate not in expected_authorities
            or coordinate in observed_authorities
            or not _valid_sha(identity)
            or known_files is not None
            and known_files.get(artifact["path"]) != artifact
        ):
            raise BackendRuntimeGrantError(
                f"backend Q4 {system} runtime authority coverage/binding drifted"
            )
        observed_authorities[coordinate] = str(identity)
        authorities.append({
            "system": coordinate[0], "codec": coordinate[1],
            "topology_kind": coordinate[2], "policy": coordinate[3],
            "artifact": artifact, "runtime_authority_sha256": identity,
        })
    if set(observed_authorities) != expected_authorities:
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} runtime authority coordinate set drifted"
        )

    raw_cells = value.get("qualified_cells")
    if type(raw_cells) is not list or len(raw_cells) != 140:
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} requires exactly 140 qualified cells"
        )
    expected_cells = _expected_coordinates(system)
    observed_cells: set[tuple[str, str, str, str, int | float]] = set()
    cells: list[dict[str, Any]] = []
    evidence_paths: set[str] = set()
    for position, raw in enumerate(raw_cells):
        if type(raw) is not dict or set(raw) != CELL_V3_FIELDS:
            raise BackendRuntimeGrantError(
                f"backend Q4 {system} cell[{position}] fields drifted"
            )
        deadline = raw.get("deadline_ms")
        coordinate = (
            str(raw.get("system")), str(raw.get("codec")),
            str(raw.get("topology_kind")), str(raw.get("policy")), deadline,
        )
        evidence = _descriptor(
            raw.get("raw_evidence"),
            f"backend Q4 {system} cell[{position}] raw evidence",
        )
        authority_coordinate = coordinate[:4]
        if (
            coordinate not in expected_cells or coordinate in observed_cells
            or evidence["path"] in evidence_paths
            or known_files is not None
            and known_files.get(evidence["path"]) != evidence
            or raw.get("runtime_authority_sha256")
            != observed_authorities.get(authority_coordinate)
            or raw.get("launcher_invocation_sha256")
            != invocation["invocation_sha256"]
            or not all(_valid_sha(raw.get(field)) for field in (
                "cell_identity_sha256", "validator_identity_sha256",
                "validation_record_sha256",
            ))
        ):
            raise BackendRuntimeGrantError(
                f"backend Q4 {system} cell coverage/binding drifted"
            )
        observed_cells.add(coordinate)
        evidence_paths.add(evidence["path"])
        normalized_cell = copy.deepcopy(raw)
        normalized_cell["raw_evidence"] = evidence
        cells.append(normalized_cell)
    if (
        observed_cells != expected_cells
        or value.get("qualified_cells_sha256") != _canonical_sha(cells)
        or value.get("raw_evidence_set_sha256") != _canonical_sha([
            item["raw_evidence"] for item in cells
        ])
    ):
        raise BackendRuntimeGrantError(
            f"backend Q4 {system} qualified cell set hash drifted"
        )
    return {
        "system": system,
        "runtime_binding_identity_sha256": value[
            "runtime_binding_identity_sha256"
        ],
        "runtime_authority_set_sha256": value["runtime_authority_set_sha256"],
        "runtime_authorities": authorities,
        "launcher_runtime_authority": launcher_authority,
        "launcher_runtime_authority_sha256": value[
            "launcher_runtime_authority_sha256"
        ],
        "launcher": launcher,
        "launcher_invocation": invocation,
        "launcher_kind": "dedicated_publication_runtime_v3",
        "publication_capable": True,
        "qualified_cells": cells,
        "qualified_cells_sha256": value["qualified_cells_sha256"],
        "raw_evidence_set_sha256": value["raw_evidence_set_sha256"],
    }


def _validate_nested_grant_v3(
    value: Mapping[str, Any], *,
    known_files: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if (
        value.get("schema_version") != 3
        or value.get("artifact_kind") != GRANT_V3_KIND
        or value.get("status") != GRANT_V3_STATUS
        or value.get("publication_scope") != PUBLICATION_SCOPE_V3
    ):
        raise BackendRuntimeGrantError("backend Q4 grant header drifted")
    for field in (
        "identity_artifact_binding_sha256", "qualification_index_sha256",
        "catalog_sha256", "validator_identity_sha256",
    ):
        if not _valid_sha(value.get(field)):
            raise BackendRuntimeGrantError(f"backend Q4 grant {field} is invalid")
    binding_index = _descriptor(
        value.get("qualification_binding_index"), "backend Q4 binding index",
    )
    if known_files is not None and known_files.get(
        binding_index["path"]
    ) != binding_index:
        raise BackendRuntimeGrantError("backend Q4 binding index is unbound")
    receipts = value.get("qualification_receipts")
    if type(receipts) is not dict or set(receipts) != set(SYSTEMS):
        raise BackendRuntimeGrantError("backend Q4 receipt set drifted")
    normalized_receipts: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        descriptor = _descriptor(receipts[system], f"backend Q4 receipt {system}")
        if known_files is not None and known_files.get(
            descriptor["path"]
        ) != descriptor:
            raise BackendRuntimeGrantError(f"backend Q4 receipt {system} is unbound")
        normalized_receipts[system] = descriptor
    upstream = value.get("upstream_identities")
    if (
        type(upstream) is not dict or set(upstream) != UPSTREAM_IDENTITY_FIELDS
        or not all(_valid_sha(item) for item in upstream.values())
    ):
        raise BackendRuntimeGrantError("backend Q4 upstream identities drifted")
    raw_systems = value.get("systems")
    if type(raw_systems) is not dict or set(raw_systems) != set(SYSTEMS):
        raise BackendRuntimeGrantError("backend Q4 grant system set drifted")
    systems = {
        system: _validate_system_binding_v3(
            raw_systems[system], system=system, known_files=known_files,
        )
        for system in SYSTEMS
    }
    protocol = _validate_production_receipt_protocol_v3(
        value.get("production_output_receipt_protocol"), systems=systems,
        known_files=known_files,
    )
    if value.get("coverage") != COVERAGE_V3:
        raise BackendRuntimeGrantError("backend Q4 grant coverage drifted")
    if (
        value.get("post_run_per_arm_evidence_required") is not True
        or value.get("configuration_evidence_accepted_mutated") is not False
    ):
        raise BackendRuntimeGrantError("backend Q4 grant evidence boundary drifted")
    return {
        "schema_version": 3,
        "artifact_kind": GRANT_V3_KIND,
        "status": GRANT_V3_STATUS,
        "publication_scope": PUBLICATION_SCOPE_V3,
        "identity_artifact_binding_sha256": value[
            "identity_artifact_binding_sha256"
        ],
        "qualification_index_sha256": value["qualification_index_sha256"],
        "catalog_sha256": value["catalog_sha256"],
        "validator_identity_sha256": value["validator_identity_sha256"],
        "qualification_binding_index": binding_index,
        "qualification_receipts": normalized_receipts,
        "upstream_identities": copy.deepcopy(upstream),
        "production_output_receipt_protocol": protocol,
        "systems": systems,
        "coverage": copy.deepcopy(COVERAGE_V3),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }


def assess_pre_run_backend_runtime_grant(value: Any) -> dict[str, Any]:
    """Pure dependency-light assessment of an already materialized grant."""

    if (
        type(value) is dict and value.get("schema_version") == 3
        and value.get("artifact_kind") == GRANT_V3_KIND
    ):
        return assess_pre_run_backend_runtime_grant_v3(value)

    blockers: list[str] = []
    try:
        if type(value) is not dict:
            raise BackendRuntimeGrantError("backend runtime grant must be a mapping")
        if set(value) != GRANT_FIELDS:
            raise BackendRuntimeGrantError("backend runtime grant fields drifted")
        normalized = _validate_nested_grant(value)
        grant_sha = value.get("grant_sha256")
        if not _valid_sha(grant_sha) or grant_sha != _canonical_sha(normalized):
            raise BackendRuntimeGrantError("backend runtime grant self-hash mismatch")
    except BackendRuntimeGrantError as error:
        blockers.append(str(error))
    except Exception as error:
        blockers.append(f"backend runtime grant failed closed: {error}")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_pre_run_backend_runtime_grant_assessment",
        "passed": not blockers,
        "status": "accepted" if not blockers else "blocked",
        "publication_scope": PUBLICATION_SCOPE,
        "blockers": blockers,
        "grant_sha256": (
            str(value.get("grant_sha256"))
            if type(value) is dict and not blockers
            else None
        ),
    }


def validate_pre_run_backend_runtime_grant(value: Any) -> dict[str, Any]:
    """Return a defensive copy or reject the grant fail-closed."""

    if (
        type(value) is dict and value.get("schema_version") == 3
        and value.get("artifact_kind") == GRANT_V3_KIND
    ):
        return validate_pre_run_backend_runtime_grant_v3(value)

    assessment = assess_pre_run_backend_runtime_grant(value)
    if not assessment["passed"]:
        raise BackendRuntimeGrantError(
            "pre-run backend runtime grant is invalid: "
            + ", ".join(str(item) for item in assessment["blockers"])
        )
    return copy.deepcopy(value)


def _backend_runtime_grant_v3_from_full_identity(
    *, identity_artifacts: Mapping[str, Any], backend: Mapping[str, Any],
    parity: Mapping[str, Any],
    known_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if (
        backend.get("schema_version") != 3
        or backend.get("artifact_kind")
        != "vast_full_publication_backend_runtime_qualification_binding_v3"
        or backend.get("authorization_eligible") is not True
        or backend.get("validation_trust_status")
        != "authenticated_persisted_physical_q4_v4"
        or backend.get("semantic_crossbinding_complete") is not True
        or backend.get("authorization_blockers") != []
        or not _valid_sha(backend.get("identity_binding_sha256"))
    ):
        raise BackendRuntimeGrantError(
            "validated backend qualification v2 material is required unless an "
            "authenticated persisted physical Q4 full-identity binding is present"
        )
    unsigned_backend = {
        key: item for key, item in backend.items()
        if key != "identity_binding_sha256"
    }
    if backend["identity_binding_sha256"] != _canonical_sha(unsigned_backend):
        raise BackendRuntimeGrantError("backend Q4 identity binding self-hash drifted")
    upstream = backend.get("upstream_identities")
    if (
        type(upstream) is not dict
        or upstream.get("model_parity_acceptance_binding_sha256")
        != parity.get("binding_sha256")
    ):
        raise BackendRuntimeGrantError(
            "backend Q4 model-parity acceptance cross-binding drifted"
        )
    physical_files = backend.get("physical_files")
    if (
        type(physical_files) is not list or not physical_files
        or backend.get("physical_files_sha256") != _canonical_sha(physical_files)
    ):
        raise BackendRuntimeGrantError("backend Q4 physical file closure drifted")
    for position, descriptor in enumerate(physical_files):
        checked = _descriptor(descriptor, f"backend Q4 physical file[{position}]")
        if known_files.get(checked["path"]) != checked:
            raise BackendRuntimeGrantError(
                f"backend Q4 physical file[{position}] is absent from full identity"
            )

    raw_systems = backend.get("systems")
    if type(raw_systems) is not dict or set(raw_systems) != set(SYSTEMS):
        raise BackendRuntimeGrantError("backend Q4 identity system set drifted")
    grant_systems: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        source = raw_systems[system]
        authorities = source.get("runtime_authorities")
        if type(authorities) is not list:
            raise BackendRuntimeGrantError(
                f"backend Q4 identity {system} runtime authorities are missing"
            )
        grant_authorities: list[dict[str, Any]] = []
        for position, authority in enumerate(authorities):
            content = authority.get("artifact") if type(authority) is dict else None
            descriptor = (
                authority.get("artifact_descriptor")
                if type(authority) is dict else None
            )
            if (
                type(content) is not dict
                or content.get("authority_sha256")
                != authority.get("runtime_authority_sha256")
            ):
                raise BackendRuntimeGrantError(
                    f"backend Q4 identity {system} authority[{position}] content drifted"
                )
            grant_authorities.append({
                **{
                    field: authority[field] for field in (
                        "system", "codec", "topology_kind", "policy",
                        "runtime_authority_sha256",
                    )
                },
                "artifact": descriptor,
            })
        launcher_authority = source.get("launcher_runtime_authority")
        if (
            type(launcher_authority) is not dict
            or launcher_authority.get("launcher_runtime_authority_sha256")
            != source.get("launcher_runtime_authority_sha256")
        ):
            raise BackendRuntimeGrantError(
                f"backend Q4 identity {system} launcher authority content drifted"
            )
        grant_systems[system] = {
            "system": system,
            "runtime_binding_identity_sha256": source.get(
                "runtime_binding_identity_sha256"
            ),
            "runtime_authority_set_sha256": source.get(
                "runtime_authority_set_sha256"
            ),
            "runtime_authorities": grant_authorities,
            "launcher_runtime_authority": source.get(
                "launcher_runtime_authority_descriptor"
            ),
            "launcher_runtime_authority_sha256": source.get(
                "launcher_runtime_authority_sha256"
            ),
            "launcher": source.get("launcher"),
            "launcher_invocation": source.get("launcher_invocation"),
            "launcher_kind": source.get("launcher_kind"),
            "publication_capable": source.get("publication_capable"),
            "qualified_cells": source.get("qualified_cells"),
            "qualified_cells_sha256": source.get("qualified_cells_sha256"),
            "raw_evidence_set_sha256": source.get("raw_evidence_set_sha256"),
        }
    material = {
        "schema_version": 3,
        "artifact_kind": GRANT_V3_KIND,
        "status": GRANT_V3_STATUS,
        "publication_scope": PUBLICATION_SCOPE_V3,
        "identity_artifact_binding_sha256": identity_artifacts[
            "binding_sha256"
        ],
        "qualification_index_sha256": backend.get(
            "qualification_index_sha256"
        ),
        "catalog_sha256": backend.get("catalog_sha256"),
        "validator_identity_sha256": backend.get(
            "observed_validator_identity_sha256"
        ),
        "qualification_binding_index": backend.get("binding_index"),
        "qualification_receipts": backend.get("receipts"),
        "upstream_identities": upstream,
        "production_output_receipt_protocol": backend.get(
            "production_output_receipt_protocol"
        ),
        "systems": grant_systems,
        "coverage": backend.get("coverage"),
        "post_run_per_arm_evidence_required": backend.get(
            "post_run_per_arm_evidence_required"
        ),
        "configuration_evidence_accepted_mutated": backend.get(
            "configuration_evidence_accepted_mutated"
        ),
    }
    normalized = _validate_nested_grant_v3(material, known_files=known_files)
    normalized["grant_sha256"] = _canonical_sha(normalized)
    return validate_pre_run_backend_runtime_grant_v3(normalized)


def backend_runtime_grant_from_identity_artifacts(
    identity_artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Derive authorization only from a canonical validated v2 identity binding."""

    if type(identity_artifacts) is not dict or set(identity_artifacts) != IDENTITY_FIELDS:
        raise BackendRuntimeGrantError("validated full publication identity fields drifted")
    if (
        identity_artifacts.get("schema_version") != 2
        or identity_artifacts.get("artifact_kind")
        != "vast_full_publication_identity_artifact_binding"
        or not _valid_sha(identity_artifacts.get("binding_sha256"))
    ):
        raise BackendRuntimeGrantError(
            "schema-2 validated full publication identity is required"
        )
    unsigned_identity = {
        key: item
        for key, item in identity_artifacts.items()
        if key != "binding_sha256"
    }
    if identity_artifacts["binding_sha256"] != _canonical_sha(unsigned_identity):
        raise BackendRuntimeGrantError(
            "validated full publication identity self-hash drifted"
        )
    files = identity_artifacts.get("files")
    if type(files) is not list or not files:
        raise BackendRuntimeGrantError("validated identity artifact file set is empty")
    normalized_files = [
        _descriptor(item, f"validated identity file[{position}]")
        for position, item in enumerate(files)
    ]
    if (
        len({item["path"] for item in normalized_files}) != len(normalized_files)
        or identity_artifacts.get("files_sha256") != _canonical_sha(normalized_files)
    ):
        raise BackendRuntimeGrantError("validated identity artifact file set hash drifted")
    known_files = {item["path"]: item for item in normalized_files}
    bindings = identity_artifacts.get("bindings")
    if type(bindings) is not dict:
        raise BackendRuntimeGrantError("validated identity bindings are missing")
    parity = bindings.get("analytics_model_parity")
    if (
        type(parity) is not dict
        or not _valid_sha(parity.get("binding_sha256"))
    ):
        raise BackendRuntimeGrantError(
            "validated physical model parity acceptance binding is required"
        )
    backend = bindings.get("backend_runtime_qualification")
    if (
        type(backend) is dict
        and backend.get("schema_version") == 3
        and backend.get("artifact_kind")
        == "vast_full_publication_backend_runtime_qualification_binding_v3"
    ):
        return _backend_runtime_grant_v3_from_full_identity(
            identity_artifacts=identity_artifacts, backend=backend,
            parity=parity, known_files=known_files,
        )
    if (
        type(backend) is not dict
        or set(backend) != BACKEND_V2_FIELDS
        or backend.get("schema_version") != SCHEMA_VERSION
    ):
        raise BackendRuntimeGrantError(
            "validated backend qualification v2 material is required; v1 cannot be promoted"
        )
    upstream = backend.get("upstream_identities")
    if (
        type(upstream) is not dict
        or upstream.get("model_parity_acceptance_binding_sha256")
        != parity["binding_sha256"]
    ):
        raise BackendRuntimeGrantError(
            "backend model parity acceptance cross-binding drifted"
        )
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": GRANT_KIND,
        "status": GRANT_STATUS,
        "publication_scope": PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": identity_artifacts["binding_sha256"],
        "qualification_index_sha256": backend.get("qualification_index_sha256"),
        "qualification_binding_index": backend.get("binding_index"),
        "qualification_receipts": backend.get("receipts"),
        "upstream_identities": backend.get("upstream_identities"),
        "systems": backend.get("systems"),
        "coverage": backend.get("coverage"),
        "post_run_per_arm_evidence_required": backend.get(
            "post_run_per_arm_evidence_required"
        ),
        "configuration_evidence_accepted_mutated": backend.get(
            "configuration_evidence_accepted_mutated"
        ),
    }
    normalized = _validate_nested_grant(material, known_files=known_files)
    normalized["grant_sha256"] = _canonical_sha(normalized)
    return validate_pre_run_backend_runtime_grant(normalized)


def assess_pre_run_backend_runtime_grant_v3(value: Any) -> dict[str, Any]:
    """Accept only a materialized grant derived from authenticated full identity.

    Raw catalogs and pre-identity candidate bindings retain the historical
    fail-closed result.
    """

    blockers: list[str] = []
    grant_sha = None
    if (
        type(value) is dict and value.get("schema_version") == 3
        and value.get("artifact_kind") == GRANT_V3_KIND
    ):
        try:
            if set(value) != GRANT_V3_FIELDS:
                raise BackendRuntimeGrantError(
                    "backend Q4 grant fields drifted"
                )
            normalized = _validate_nested_grant_v3(value)
            grant_sha = value.get("grant_sha256")
            if not _valid_sha(grant_sha) or grant_sha != _canonical_sha(normalized):
                raise BackendRuntimeGrantError(
                    "backend Q4 grant self-hash mismatch"
                )
        except BackendRuntimeGrantError as error:
            blockers.append(str(error))
        except Exception as error:
            blockers.append(f"backend Q4 grant failed closed: {error}")
    else:
        blockers.append(
            "persisted Q4 qualification receipts and binding index must be "
            "registered and physically revalidated by the full publication "
            "identity layer before any execution-authorizing grant can exist"
        )
    return {
        "schema_version": 3,
        "artifact_kind": "vast_pre_run_backend_runtime_grant_v3_assessment",
        "passed": not blockers,
        "status": "accepted" if not blockers else "blocked",
        "publication_scope": PUBLICATION_SCOPE_V3,
        "blockers": blockers,
        "grant_sha256": grant_sha if not blockers else None,
    }


def validate_pre_run_backend_runtime_grant_v3(value: Any) -> dict[str, Any]:
    """Return one authenticated persisted-Q4 grant or reject fail-closed."""

    assessment = assess_pre_run_backend_runtime_grant_v3(value)
    if not assessment["passed"]:
        raise BackendRuntimeGrantError(
            "pre-run backend runtime grant v3 is invalid: "
            + ", ".join(assessment["blockers"])
        )
    return copy.deepcopy(value)


def backend_runtime_grant_v3_from_qualification_catalog(
    catalog: Any, *, identity_artifact_binding_sha256: str,
) -> dict[str, Any]:
    """Never promote an in-memory/pre-identity catalog into a v3 grant."""

    try:
        from backend_runtime_qualification_v3 import (
            validate_backend_runtime_qualification_v3_catalog,
        )

        validate_backend_runtime_qualification_v3_catalog(catalog)
    except Exception as error:
        raise BackendRuntimeGrantError(
            f"backend qualification v3 catalog is invalid: {error}"
        ) from error
    if not _valid_sha(identity_artifact_binding_sha256):
        raise BackendRuntimeGrantError(
            "schema-v3 full publication identity binding is invalid"
        )
    raise BackendRuntimeGrantError(
        "persisted schema-v3 receipts and binding index in a physically "
        "validated full publication identity are required; a pre-identity "
        "catalog cannot authorize execution"
    )


def backend_launcher_output_receipt_protocol_ready(value: Any) -> bool:
    """Derive readiness from an authenticated protocol-bound Q4 grant."""
    try:
        grant = validate_pre_run_backend_runtime_grant(value)
    except BackendRuntimeGrantError:
        return False
    return (
        grant.get("schema_version") == 3
        and grant.get("artifact_kind") == GRANT_V3_KIND
        and grant.get("production_output_receipt_protocol", {}).get(
            "artifact_kind"
        ) == PRODUCTION_RECEIPT_PROTOCOL_KIND
    )


__all__ = [
    "BackendRuntimeGrantError",
    "GRANT_KIND",
    "GRANT_STATUS",
    "GRANT_V3_KIND",
    "GRANT_V3_STATUS",
    "PUBLICATION_SCOPE",
    "PUBLICATION_SCOPE_V3",
    "PRODUCTION_RECEIPT_PROTOCOL_KIND",
    "SCHEMA_VERSION",
    "SYSTEMS",
    "assess_pre_run_backend_runtime_grant",
    "assess_pre_run_backend_runtime_grant_v3",
    "backend_launcher_output_receipt_protocol_ready",
    "backend_runtime_grant_from_identity_artifacts",
    "backend_runtime_grant_v3_from_qualification_catalog",
    "validate_pre_run_backend_runtime_grant",
    "validate_pre_run_backend_runtime_grant_v3",
]
