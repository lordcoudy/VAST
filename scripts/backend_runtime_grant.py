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


def assess_pre_run_backend_runtime_grant(value: Any) -> dict[str, Any]:
    """Pure dependency-light assessment of an already materialized grant."""

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

    assessment = assess_pre_run_backend_runtime_grant(value)
    if not assessment["passed"]:
        raise BackendRuntimeGrantError(
            "pre-run backend runtime grant is invalid: "
            + ", ".join(str(item) for item in assessment["blockers"])
        )
    return copy.deepcopy(value)


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
    """Fail closed until schema-v3 candidates are persisted in full identity.

    A qualified catalog, its four receipts, and its binding index are only
    pre-identity candidates.  This boundary intentionally has no successful
    branch until the full-publication identity layer registers and revalidates
    those physical artifacts.
    """

    candidate_sha = None
    if type(value) is dict:
        candidate_sha = value.get("grant_sha256") or value.get("catalog_sha256")
    return {
        "schema_version": 3,
        "artifact_kind": "vast_pre_run_backend_runtime_grant_v3_assessment",
        "passed": False,
        "status": "blocked",
        "publication_scope": "backend_runtime_authority_grant_v3",
        "blockers": [
            "persisted schema-v3 qualification receipts and binding index must "
            "be registered and physically revalidated by the full publication "
            "identity layer before any execution-authorizing grant can exist"
        ],
        "grant_sha256": candidate_sha if _valid_sha(candidate_sha) else None,
    }


def validate_pre_run_backend_runtime_grant_v3(value: Any) -> dict[str, Any]:
    """Reject all v3 material until full-identity integration is implemented."""

    assessment = assess_pre_run_backend_runtime_grant_v3(value)
    raise BackendRuntimeGrantError(
        "pre-run backend runtime grant v3 is invalid: "
        + ", ".join(assessment["blockers"])
    )


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


__all__ = [
    "BackendRuntimeGrantError",
    "GRANT_KIND",
    "GRANT_STATUS",
    "PUBLICATION_SCOPE",
    "SCHEMA_VERSION",
    "SYSTEMS",
    "assess_pre_run_backend_runtime_grant",
    "assess_pre_run_backend_runtime_grant_v3",
    "backend_runtime_grant_from_identity_artifacts",
    "backend_runtime_grant_v3_from_qualification_catalog",
    "validate_pre_run_backend_runtime_grant",
    "validate_pre_run_backend_runtime_grant_v3",
]
