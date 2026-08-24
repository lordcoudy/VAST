#!/usr/bin/env python3
"""Fail-closed backend qualification catalog with exact runtime authorities.

Schema v3 binds every 4D backend coordinate (system, codec, topology, policy)
to one physically assessed runtime-authority artifact.  The five deadline
cells reuse that exact authority.  It can atomically persist only explicitly
non-authorizing pre-identity candidate receipts plus a commit-last index.  It
never writes grants, readiness state, or benchmark outputs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping

from backend_publication_dispatch import validate_launcher_invocation
from backend_publication_runtime_authority import (
    assess_backend_publication_runtime_authority,
    validate_backend_publication_runtime_authority,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)
SCHEMA_VERSION = 3
INDEX_KIND = "vast_backend_runtime_qualification_v3_index"
ASSESSMENT_KIND = "vast_backend_runtime_qualification_v3_assessment"
CATALOG_KIND = "vast_backend_runtime_qualification_v3_catalog"
CATALOG_STATUS = "qualified_runtime_authority_catalog_v3_pre_identity_candidate"
PUBLICATION_SCOPE = "backend_runtime_authority_catalog_v3_pre_identity_only"
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})
_UPSTREAM_FIELDS = frozenset({
    "dataset_manifest_sha256", "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
})
_INDEX_FIELDS = frozenset({
    "schema_version", "artifact_kind", "upstream_identities", "systems",
})
_INPUT_SYSTEM_FIELDS = frozenset({
    "system", "runtime_binding_identity_sha256",
    "runtime_authority_set_sha256", "runtime_authorities", "launcher",
    "launcher_invocation", "launcher_kind", "publication_capable", "cells",
})
_AUTHORITY_RECORD_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "artifact",
    "runtime_authority_sha256",
})
_INPUT_CELL_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "runtime_authority_sha256", "raw_evidence",
})
_VALIDATION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "codec", "topology_kind",
    "policy", "deadline_ms", "accepted", "synthetic", "nonpublication",
    "publication_capable", "runtime_binding_identity_sha256",
    "runtime_authority_sha256", "runtime_authority_set_sha256",
    "launcher_sha256", "launcher_invocation_sha256", "raw_evidence_sha256",
    "upstream_identities", "validator_identity_sha256",
    "validation_record_sha256",
})
_QUALIFIED_CELL_FIELDS = frozenset({
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "cell_identity_sha256", "runtime_authority_sha256", "raw_evidence",
    "launcher_invocation_sha256", "validator_identity_sha256",
    "validation_record_sha256",
})
_CATALOG_SYSTEM_FIELDS = frozenset({
    "system", "runtime_binding_identity_sha256",
    "runtime_authority_set_sha256", "runtime_authorities", "launcher",
    "launcher_invocation", "launcher_kind", "publication_capable",
    "qualified_cells", "qualified_cells_sha256", "raw_evidence_set_sha256",
})
_COVERAGE = {
    "system_count": 4,
    "runtime_authority_count": 112,
    "runtime_authorities_per_system": 28,
    "runtime_cell_count": 560,
    "cells_per_system": 140,
    "deadlines_per_runtime_authority": 5,
}
_CATALOG_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "publication_scope",
    "qualification_index_sha256", "upstream_identities", "systems",
    "coverage", "post_run_per_arm_evidence_required",
    "configuration_evidence_accepted_mutated", "catalog_sha256",
})


class BackendRuntimeQualificationV3Error(RuntimeError):
    """Schema-v3 authority catalog or raw runtime evidence is unsafe."""


RawEvidenceValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BackendRuntimeQualificationV3Error(
            "backend qualification v3 material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        raise BackendRuntimeQualificationV3Error(f"{label} descriptor fields drifted")
    path = value.get("path")
    size = value.get("size_bytes")
    if (
        type(path) is not str or not path or "\\" in path or ":" in path
        or "\x00" in path
    ):
        raise BackendRuntimeQualificationV3Error(f"{label} descriptor is invalid")
    relative = PurePosixPath(path)
    windows_relative = PureWindowsPath(path)
    if (
        relative.is_absolute() or relative.as_posix() != path
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.anchor != ""
        or windows_relative.drive != "" or windows_relative.root != ""
        or windows_relative.anchor != ""
        or any(
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
            for part in relative.parts
        )
        or type(size) is not int or size <= 0 or not _valid_sha(value.get("sha256"))
    ):
        raise BackendRuntimeQualificationV3Error(f"{label} descriptor is invalid")
    return copy.deepcopy(value)


def _physical_file(
    root: Path, value: Any, label: str, *, identities: set[tuple[int, int]],
    paths: set[str],
) -> tuple[dict[str, Any], Path, bytes]:
    descriptor = _descriptor(value, label)
    relative = PurePosixPath(descriptor["path"])
    path = root.joinpath(*relative.parts)
    cursor = root
    try:
        for part in relative.parts:
            cursor /= part
            info = cursor.lstat()
            if _is_link_or_reparse(cursor):
                raise BackendRuntimeQualificationV3Error(
                    f"{label} path contains a link/reparse point"
                )
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        before = resolved.stat()
    except BackendRuntimeQualificationV3Error:
        raise
    except (OSError, ValueError) as error:
        raise BackendRuntimeQualificationV3Error(
            f"{label} is missing or escapes root"
        ) from error
    if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
        raise BackendRuntimeQualificationV3Error(
            f"{label} must be one non-hardlinked regular file"
        )
    identity = (int(before.st_dev), int(before.st_ino))
    if identity in identities or descriptor["path"] in paths:
        raise BackendRuntimeQualificationV3Error(f"{label} artifact alias is prohibited")
    stable_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns, before.st_nlink,
    )
    descriptor_fd: int | None = None
    try:
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor_fd = os.open(resolved, flags)
        opened = os.fstat(descriptor_fd)
        path_opened = resolved.lstat()
        if (
            _is_link_or_reparse(resolved)
            or (opened.st_dev, opened.st_ino) != (
                path_opened.st_dev, path_opened.st_ino,
            )
            or (
                path_opened.st_dev, path_opened.st_ino, path_opened.st_size,
                path_opened.st_mtime_ns, path_opened.st_ctime_ns,
                path_opened.st_nlink,
            ) != stable_before
        ):
            raise BackendRuntimeQualificationV3Error(
                f"{label} changed while opening"
            )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > descriptor["size_bytes"]:
                raise BackendRuntimeQualificationV3Error(
                    f"{label} exceeded declared size"
                )
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor_fd)
        path_after = resolved.lstat()
    except BackendRuntimeQualificationV3Error:
        raise
    except OSError as error:
        raise BackendRuntimeQualificationV3Error(f"{label} cannot be read") from error
    finally:
        if descriptor_fd is not None:
            os.close(descriptor_fd)
    stable_after = (
        path_after.st_dev, path_after.st_ino, path_after.st_size,
        path_after.st_mtime_ns, path_after.st_ctime_ns, path_after.st_nlink,
    )
    if (
        stable_before != stable_after
        or (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino)
    ):
        raise BackendRuntimeQualificationV3Error(f"{label} changed while reading")
    if (
        len(payload) != descriptor["size_bytes"]
        or hashlib.sha256(payload).hexdigest() != descriptor["sha256"]
    ):
        raise BackendRuntimeQualificationV3Error(f"{label} physical size/SHA drifted")
    identities.add(identity)
    paths.add(descriptor["path"])
    return descriptor, resolved, payload


def _upstream(value: Any) -> dict[str, str]:
    if (
        type(value) is not dict or set(value) != _UPSTREAM_FIELDS
        or not all(_valid_sha(item) for item in value.values())
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 upstream identities drifted"
        )
    return copy.deepcopy(value)


def _authority_coordinate(record: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(record.get("system")), str(record.get("codec")),
        str(record.get("topology_kind")), str(record.get("policy")),
    )


def _expected_authority_coordinates(system: str) -> set[tuple[str, str, str, str]]:
    return {
        (system, codec, topology, policy)
        for codec in CODECS for topology in TOPOLOGIES for policy in POLICIES
    }


def _expected_cell_coordinates(system: str) -> set[tuple[str, str, str, str, int | float]]:
    return {
        (system, codec, topology, policy, deadline)
        for codec in CODECS for topology in TOPOLOGIES for policy in POLICIES
        for deadline in DEADLINES_MS
    }


def runtime_binding_identity_v3(
    *, system: str, launcher: Mapping[str, Any],
    launcher_invocation: Mapping[str, Any],
    upstream_identities: Mapping[str, Any],
    runtime_authority_set_sha256: str,
) -> str:
    """Bind launcher/ABI/upstreams and the exact 28-authority set."""
    if system not in SYSTEMS:
        raise BackendRuntimeQualificationV3Error("runtime binding v3 system is invalid")
    descriptor = _descriptor(dict(launcher), "runtime binding v3 launcher")
    try:
        invocation = validate_launcher_invocation(dict(launcher_invocation))
    except Exception as error:
        raise BackendRuntimeQualificationV3Error(
            "runtime binding v3 invocation is invalid"
        ) from error
    upstream = _upstream(dict(upstream_identities))
    if not _valid_sha(runtime_authority_set_sha256):
        raise BackendRuntimeQualificationV3Error("runtime authority set identity is invalid")
    return _canonical_sha({
        "schema_version": 3,
        "artifact_kind": "vast_backend_publication_runtime_binding_v3",
        "system": system,
        "launcher": descriptor,
        "launcher_invocation_sha256": invocation["invocation_sha256"],
        "upstream_identities": upstream,
        "runtime_authority_set_sha256": runtime_authority_set_sha256,
    })


def _normalize_authority_records(
    value: Any, *, system: str,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], str]]:
    if type(value) is not list or len(value) != 28:
        raise BackendRuntimeQualificationV3Error(
            f"qualification v3 system {system} must bind exactly 28 runtime authorities"
        )
    records: list[dict[str, Any]] = []
    observed: set[tuple[str, str, str, str]] = set()
    semantic: set[str] = set()
    by_coordinate: dict[tuple[str, str, str], str] = {}
    expected = _expected_authority_coordinates(system)
    for position, raw in enumerate(value):
        if type(raw) is not dict or set(raw) != _AUTHORITY_RECORD_FIELDS:
            raise BackendRuntimeQualificationV3Error(
                f"qualification v3 authority[{position}] fields drifted"
            )
        coordinate = _authority_coordinate(raw)
        if coordinate not in expected or coordinate in observed:
            raise BackendRuntimeQualificationV3Error(
                f"qualification v3 system {system} authority coordinate is missing, duplicate, or relabelled"
            )
        authority_sha = raw.get("runtime_authority_sha256")
        if not _valid_sha(authority_sha):
            raise BackendRuntimeQualificationV3Error(
                "runtime authority semantic identity is invalid"
            )
        if authority_sha in semantic:
            raise BackendRuntimeQualificationV3Error(
                "runtime authority semantic identity is duplicated"
            )
        record = {
            "system": coordinate[0], "codec": coordinate[1],
            "topology_kind": coordinate[2], "policy": coordinate[3],
            "artifact": _descriptor(
                raw.get("artifact"), "runtime authority artifact"
            ),
            "runtime_authority_sha256": authority_sha,
        }
        records.append(record)
        observed.add(coordinate)
        semantic.add(authority_sha)
        by_coordinate[(coordinate[1], coordinate[2], coordinate[3])] = authority_sha
    expected_sorted = sorted(records, key=lambda item: (
        item["system"], item["codec"], item["topology_kind"], item["policy"],
    ))
    if records != expected_sorted or observed != expected:
        raise BackendRuntimeQualificationV3Error(
            f"qualification v3 system {system} authority catalog is not canonical"
        )
    return records, by_coordinate


def _normalize_qualified_cells(
    value: Any, *, system: str,
    authority_by_coordinate: Mapping[tuple[str, str, str], str],
    launcher_invocation_sha256: str,
) -> list[dict[str, Any]]:
    if type(value) is not list or len(value) != 140:
        raise BackendRuntimeQualificationV3Error(
            f"qualification v3 system {system} must contain exactly 140 qualified cells"
        )
    expected = _expected_cell_coordinates(system)
    observed: set[tuple[str, str, str, str, int | float]] = set()
    uses: dict[str, set[int | float]] = {}
    normalized: list[dict[str, Any]] = []
    for position, raw in enumerate(value):
        if type(raw) is not dict or set(raw) != _QUALIFIED_CELL_FIELDS:
            raise BackendRuntimeQualificationV3Error(
                f"qualification v3 qualified cell[{position}] fields drifted"
            )
        deadline = raw.get("deadline_ms")
        if type(deadline) not in {int, float} or not math.isfinite(float(deadline)):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 deadline type drifted"
            )
        coordinate = (
            str(raw.get("system")), str(raw.get("codec")),
            str(raw.get("topology_kind")), str(raw.get("policy")), deadline,
        )
        if coordinate not in expected or coordinate in observed:
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 cell coverage drifted"
            )
        expected_authority = authority_by_coordinate.get(coordinate[1:4])
        if raw.get("runtime_authority_sha256") != expected_authority:
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 cell/authority cross-binding drifted"
            )
        coordinate_payload = {
            "system": coordinate[0], "codec": coordinate[1],
            "topology_kind": coordinate[2], "policy": coordinate[3],
            "deadline_ms": coordinate[4],
            "runtime_authority_sha256": expected_authority,
        }
        if raw.get("cell_identity_sha256") != _canonical_sha(coordinate_payload):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 cell identity drifted"
            )
        evidence = _descriptor(
            raw.get("raw_evidence"), "qualification v3 raw evidence"
        )
        if (
            raw.get("launcher_invocation_sha256") != launcher_invocation_sha256
            or not _valid_sha(raw.get("validator_identity_sha256"))
            or not _valid_sha(raw.get("validation_record_sha256"))
        ):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 cell validation binding drifted"
            )
        item = copy.deepcopy(raw)
        item["raw_evidence"] = evidence
        normalized.append(item)
        observed.add(coordinate)
        uses.setdefault(expected_authority, set()).add(deadline)
    if (
        observed != expected or len(uses) != 28
        or any(deadlines != set(DEADLINES_MS) for deadlines in uses.values())
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 must reuse each runtime authority for exactly five deadlines"
        )
    return normalized


def _normalize_catalog_system(
    value: Any, *, system: str, upstream: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _CATALOG_SYSTEM_FIELDS:
        raise BackendRuntimeQualificationV3Error(
            f"qualification v3 catalog system {system} fields drifted"
        )
    if value.get("system") != system:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog system relabelled"
        )
    authorities, authority_by_coordinate = _normalize_authority_records(
        value.get("runtime_authorities"), system=system,
    )
    set_sha = _canonical_sha(authorities)
    if value.get("runtime_authority_set_sha256") != set_sha:
        raise BackendRuntimeQualificationV3Error(
            "runtime authority set self-hash drifted"
        )
    launcher = _descriptor(
        value.get("launcher"), f"qualification v3 {system} launcher"
    )
    try:
        invocation = validate_launcher_invocation(value.get("launcher_invocation"))
    except Exception as error:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 launcher invocation drifted"
        ) from error
    if (
        value.get("launcher_kind") != "dedicated_publication_runtime"
        or value.get("publication_capable") is not True
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 launcher is nonpublication"
        )
    binding = runtime_binding_identity_v3(
        system=system, launcher=launcher, launcher_invocation=invocation,
        upstream_identities=upstream, runtime_authority_set_sha256=set_sha,
    )
    if value.get("runtime_binding_identity_sha256") != binding:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 runtime binding identity drifted"
        )
    cells = _normalize_qualified_cells(
        value.get("qualified_cells"), system=system,
        authority_by_coordinate=authority_by_coordinate,
        launcher_invocation_sha256=invocation["invocation_sha256"],
    )
    if value.get("qualified_cells_sha256") != _canonical_sha(cells):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 qualified-cell set hash drifted"
        )
    evidences = [item["raw_evidence"] for item in cells]
    if value.get("raw_evidence_set_sha256") != _canonical_sha(evidences):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 raw-evidence set hash drifted"
        )
    return {
        "system": system,
        "runtime_binding_identity_sha256": binding,
        "runtime_authority_set_sha256": set_sha,
        "runtime_authorities": authorities,
        "launcher": launcher,
        "launcher_invocation": invocation,
        "launcher_kind": "dedicated_publication_runtime",
        "publication_capable": True,
        "qualified_cells": cells,
        "qualified_cells_sha256": value["qualified_cells_sha256"],
        "raw_evidence_set_sha256": value["raw_evidence_set_sha256"],
    }


def validate_backend_runtime_qualification_v3_catalog(value: Any) -> dict[str, Any]:
    """Pure closed-schema validation for an in-memory v3 catalog."""
    if type(value) is not dict or set(value) != _CATALOG_FIELDS:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog fields drifted"
        )
    if (
        value.get("schema_version") != 3
        or value.get("artifact_kind") != CATALOG_KIND
        or value.get("status") != CATALOG_STATUS
        or value.get("publication_scope") != PUBLICATION_SCOPE
        or not _valid_sha(value.get("qualification_index_sha256"))
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog header drifted"
        )
    upstream = _upstream(value.get("upstream_identities"))
    systems = value.get("systems")
    if type(systems) is not dict or set(systems) != set(SYSTEMS):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog system set drifted"
        )
    normalized_systems = {
        system: _normalize_catalog_system(
            systems[system], system=system, upstream=upstream,
        )
        for system in SYSTEMS
    }
    authority_hashes = [
        record["runtime_authority_sha256"]
        for system in SYSTEMS
        for record in normalized_systems[system]["runtime_authorities"]
    ]
    if len(set(authority_hashes)) != 112:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 requires 112 globally unique authorities"
        )
    if value.get("coverage") != _COVERAGE:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog coverage drifted"
        )
    if value.get("post_run_per_arm_evidence_required") is not True:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 post-run boundary drifted"
        )
    if value.get("configuration_evidence_accepted_mutated") is not False:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 config boundary drifted"
        )
    normalized = {
        "schema_version": 3,
        "artifact_kind": CATALOG_KIND,
        "status": CATALOG_STATUS,
        "publication_scope": PUBLICATION_SCOPE,
        "qualification_index_sha256": value["qualification_index_sha256"],
        "upstream_identities": upstream,
        "systems": normalized_systems,
        "coverage": copy.deepcopy(_COVERAGE),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    if value.get("catalog_sha256") != _canonical_sha(normalized):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 catalog self-hash mismatch"
        )
    normalized["catalog_sha256"] = value["catalog_sha256"]
    return normalized


def _default_validator(
    _cell: dict[str, Any], _context: dict[str, Any],
) -> dict[str, Any]:
    raise BackendRuntimeQualificationV3Error(
        "raw backend cell evidence validator is required; declarations are not proof"
    )


def _raw_result(
    value: Any, *, coordinate: tuple[str, str, str, str, int | float],
    runtime_binding_sha: str, authority_sha: str, authority_set_sha: str,
    launcher: Mapping[str, Any], invocation: Mapping[str, Any],
    evidence: Mapping[str, Any], upstream: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _VALIDATION_FIELDS:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 raw validator fields drifted"
        )
    if (
        value.get("schema_version") != 3
        or value.get("artifact_kind")
        != "vast_backend_runtime_cell_raw_evidence_validation_v3"
        or tuple(value[key] for key in (
            "system", "codec", "topology_kind", "policy", "deadline_ms",
        )) != coordinate
        or value.get("accepted") is not True
        or value.get("synthetic") is not False
        or value.get("nonpublication") is not False
        or value.get("publication_capable") is not True
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 raw validation is unaccepted or relabelled"
        )
    if (
        value.get("runtime_binding_identity_sha256") != runtime_binding_sha
        or value.get("runtime_authority_sha256") != authority_sha
        or value.get("runtime_authority_set_sha256") != authority_set_sha
        or value.get("launcher_sha256") != launcher["sha256"]
        or value.get("launcher_invocation_sha256")
        != invocation["invocation_sha256"]
        or value.get("raw_evidence_sha256") != evidence["sha256"]
        or value.get("upstream_identities") != upstream
        or not _valid_sha(value.get("validator_identity_sha256"))
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 raw validation cross-binding drifted"
        )
    unsigned = {
        key: item for key, item in value.items()
        if key != "validation_record_sha256"
    }
    if value.get("validation_record_sha256") != _canonical_sha(unsigned):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 validation record self-hash drifted"
        )
    coordinate_payload = {
        "system": coordinate[0], "codec": coordinate[1],
        "topology_kind": coordinate[2], "policy": coordinate[3],
        "deadline_ms": coordinate[4],
        "runtime_authority_sha256": authority_sha,
    }
    return {
        **coordinate_payload,
        "cell_identity_sha256": _canonical_sha(coordinate_payload),
        "runtime_authority_sha256": authority_sha,
        "raw_evidence": copy.deepcopy(evidence),
        "launcher_invocation_sha256": invocation["invocation_sha256"],
        "validator_identity_sha256": value["validator_identity_sha256"],
        "validation_record_sha256": value["validation_record_sha256"],
    }


def _failure(blocker: str, index_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "artifact_kind": ASSESSMENT_KIND,
        "passed": False,
        "status": "blocked",
        "blockers": [blocker],
        "qualification_index_sha256": index_sha,
        "upstream_identities": None,
        "systems": None,
        "coverage": {
            "system_count": 0, "runtime_authority_count": 0,
            "runtime_authorities_per_system": 0, "runtime_cell_count": 0,
            "cells_per_system": 0, "deadlines_per_runtime_authority": 0,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }


def _read_index(
    root: Path, relative_value: str, *, identities: set[tuple[int, int]],
    paths: set[str],
) -> tuple[bytes, str]:
    """Read the caller-selected index through one stable file descriptor."""
    probe = {
        "path": relative_value, "size_bytes": 1, "sha256": "0" * 64,
    }
    relative = PurePosixPath(
        _descriptor(probe, "qualification v3 index")["path"]
    )
    path = root.joinpath(*relative.parts)
    cursor = root
    try:
        for part in relative.parts:
            cursor /= part
            info = cursor.lstat()
            if _is_link_or_reparse(cursor):
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 index path contains a link/reparse point"
                )
        before = path.lstat()
    except BackendRuntimeQualificationV3Error:
        raise
    except OSError as error:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 index is missing"
        ) from error
    if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 index must be one non-hardlinked regular file"
        )
    stable_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns, before.st_nlink,
    )
    descriptor_fd: int | None = None
    try:
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor_fd = os.open(path, flags)
        opened = os.fstat(descriptor_fd)
        path_opened = path.lstat()
        stable_opened = (
            path_opened.st_dev, path_opened.st_ino, path_opened.st_size,
            path_opened.st_mtime_ns, path_opened.st_ctime_ns,
            path_opened.st_nlink,
        )
        if (
            _is_link_or_reparse(path) or stable_opened != stable_before
            or (opened.st_dev, opened.st_ino)
            != (path_opened.st_dev, path_opened.st_ino)
        ):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 index changed while opening"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor_fd)
        path_after = path.lstat()
    except BackendRuntimeQualificationV3Error:
        raise
    except OSError as error:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 index cannot be read"
        ) from error
    finally:
        if descriptor_fd is not None:
            os.close(descriptor_fd)
    stable_after = (
        path_after.st_dev, path_after.st_ino, path_after.st_size,
        path_after.st_mtime_ns, path_after.st_ctime_ns, path_after.st_nlink,
    )
    if (
        not payload or stable_before != stable_after
        or (after.st_dev, after.st_ino)
        != (path_after.st_dev, path_after.st_ino)
    ):
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 index changed while reading or is empty"
        )
    identity = (int(after.st_dev), int(after.st_ino))
    if identity in identities or relative_value in paths:
        raise BackendRuntimeQualificationV3Error(
            "qualification v3 index aliases another artifact"
        )
    identities.add(identity)
    paths.add(relative_value)
    return payload, hashlib.sha256(payload).hexdigest()


def assess_backend_runtime_qualification_v3(
    *, project_root: Path, index_path: Path,
    raw_evidence_validator: RawEvidenceValidator | None = None,
) -> dict[str, Any]:
    """Physically assess exact authorities/evidence; never write artifacts."""
    try:
        supplied_root = Path(project_root)
        if not supplied_root.is_absolute():
            raise BackendRuntimeQualificationV3Error(
                "project_root must be absolute"
            )
        root = supplied_root.resolve(strict=True)
        if (
            root != supplied_root or not root.is_dir()
            or _is_link_or_reparse(root)
        ):
            raise BackendRuntimeQualificationV3Error(
                "project_root must be canonical and physical"
            )
        candidate = Path(index_path)
        if candidate.is_absolute():
            if candidate != candidate.resolve(strict=True):
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 index path must be canonical"
                )
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError as error:
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 index escapes project_root"
                ) from error
        else:
            relative = candidate.as_posix()
        identities: set[tuple[int, int]] = set()
        paths: set[str] = set()
        index_payload, index_sha = _read_index(
            root, relative, identities=identities, paths=paths,
        )
        try:
            index = json.loads(index_payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 index is invalid JSON"
            ) from error
        if (
            type(index) is not dict or set(index) != _INDEX_FIELDS
            or index.get("schema_version") != 3
            or index.get("artifact_kind") != INDEX_KIND
        ):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 index schema/fields drifted"
            )
        upstream = _upstream(index.get("upstream_identities"))
        systems = index.get("systems")
        if type(systems) is not dict or set(systems) != set(SYSTEMS):
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 system membership drifted"
            )
        validator = raw_evidence_validator or _default_validator
        normalized_systems: dict[str, Any] = {}
        global_authority_hashes: set[str] = set()
        for system in SYSTEMS:
            item = systems[system]
            if (
                type(item) is not dict or set(item) != _INPUT_SYSTEM_FIELDS
                or item.get("system") != system
            ):
                raise BackendRuntimeQualificationV3Error(
                    f"qualification v3 system {system} fields drifted"
                )
            authorities, authority_by_coordinate = _normalize_authority_records(
                item.get("runtime_authorities"), system=system,
            )
            set_sha = _canonical_sha(authorities)
            if item.get("runtime_authority_set_sha256") != set_sha:
                raise BackendRuntimeQualificationV3Error(
                    "runtime authority set self-hash drifted"
                )
            for record in authorities:
                artifact, _, payload = _physical_file(
                    root, record["artifact"],
                    f"qualification v3 {system} runtime authority",
                    identities=identities, paths=paths,
                )
                try:
                    authority = json.loads(payload.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise BackendRuntimeQualificationV3Error(
                        "runtime authority artifact is invalid JSON"
                    ) from error
                coordinate = _authority_coordinate(record)
                validate_backend_publication_runtime_authority(
                    authority, expected_system=coordinate[0],
                    expected_codec=coordinate[1],
                    expected_topology_kind=coordinate[2],
                    expected_policy=coordinate[3],
                )
                if (
                    authority.get("authority_sha256")
                    != record["runtime_authority_sha256"]
                ):
                    raise BackendRuntimeQualificationV3Error(
                        "runtime authority semantic identity drifted"
                    )
                physical = assess_backend_publication_runtime_authority(
                    authority, project_root=root,
                    expected_system=coordinate[0], expected_codec=coordinate[1],
                    expected_topology_kind=coordinate[2],
                    expected_policy=coordinate[3],
                )
                if physical.get("status") != "physically_valid":
                    raise BackendRuntimeQualificationV3Error(
                        "runtime authority physical assessment blocked: "
                        + ";".join(physical.get("blockers", []))
                    )
                authority_sha = record["runtime_authority_sha256"]
                if authority_sha in global_authority_hashes:
                    raise BackendRuntimeQualificationV3Error(
                        "runtime authorities must be globally unique"
                    )
                global_authority_hashes.add(authority_sha)
                record["artifact"] = artifact
            launcher, launcher_path, _ = _physical_file(
                root, item.get("launcher"),
                f"qualification v3 {system} launcher",
                identities=identities, paths=paths,
            )
            try:
                invocation = validate_launcher_invocation(
                    item.get("launcher_invocation")
                )
            except Exception as error:
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 launcher invocation drifted"
                ) from error
            if (
                item.get("launcher_kind")
                != "dedicated_publication_runtime"
                or item.get("publication_capable") is not True
            ):
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 launcher is nonpublication"
                )
            binding = runtime_binding_identity_v3(
                system=system, launcher=launcher,
                launcher_invocation=invocation,
                upstream_identities=upstream,
                runtime_authority_set_sha256=set_sha,
            )
            if item.get("runtime_binding_identity_sha256") != binding:
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 runtime binding identity drifted"
                )
            cells = item.get("cells")
            if type(cells) is not list or len(cells) != 140:
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 requires exactly 140 cells/system"
                )
            expected_cells = _expected_cell_coordinates(system)
            observed_cells: set[
                tuple[str, str, str, str, int | float]
            ] = set()
            prepared = []
            uses: dict[str, set[int | float]] = {}
            for position, cell in enumerate(cells):
                if type(cell) is not dict or set(cell) != _INPUT_CELL_FIELDS:
                    raise BackendRuntimeQualificationV3Error(
                        f"qualification v3 cell[{position}] fields drifted"
                    )
                deadline = cell.get("deadline_ms")
                if (
                    type(deadline) not in {int, float}
                    or not math.isfinite(float(deadline))
                ):
                    raise BackendRuntimeQualificationV3Error(
                        "qualification v3 deadline type drifted"
                    )
                coordinate = (
                    str(cell.get("system")), str(cell.get("codec")),
                    str(cell.get("topology_kind")), str(cell.get("policy")),
                    deadline,
                )
                if coordinate not in expected_cells or coordinate in observed_cells:
                    raise BackendRuntimeQualificationV3Error(
                        "qualification v3 cell coverage drifted"
                    )
                authority_sha = authority_by_coordinate.get(coordinate[1:4])
                if cell.get("runtime_authority_sha256") != authority_sha:
                    raise BackendRuntimeQualificationV3Error(
                        "qualification v3 cell/authority cross-binding drifted"
                    )
                evidence, evidence_path, _ = _physical_file(
                    root, cell.get("raw_evidence"),
                    f"qualification v3 cell {coordinate} raw evidence",
                    identities=identities, paths=paths,
                )
                prepared.append((
                    copy.deepcopy(cell), coordinate, authority_sha,
                    evidence, evidence_path,
                ))
                observed_cells.add(coordinate)
                uses.setdefault(authority_sha, set()).add(deadline)
            if (
                observed_cells != expected_cells or len(uses) != 28
                or any(value != set(DEADLINES_MS) for value in uses.values())
            ):
                raise BackendRuntimeQualificationV3Error(
                    "qualification v3 authority/deadline reuse drifted"
                )
            qualified = []
            for cell, coordinate, authority_sha, evidence, evidence_path in prepared:
                result = validator(cell, {
                    "project_root": root,
                    "raw_evidence": copy.deepcopy(evidence),
                    "raw_evidence_path": evidence_path,
                    "runtime_binding_identity_sha256": binding,
                    "runtime_authority_sha256": authority_sha,
                    "runtime_authority_set_sha256": set_sha,
                    "launcher": copy.deepcopy(launcher),
                    "launcher_path": launcher_path,
                    "launcher_invocation": copy.deepcopy(invocation),
                    "upstream_identities": copy.deepcopy(upstream),
                })
                qualified.append(_raw_result(
                    result, coordinate=coordinate,
                    runtime_binding_sha=binding, authority_sha=authority_sha,
                    authority_set_sha=set_sha, launcher=launcher,
                    invocation=invocation, evidence=evidence,
                    upstream=upstream,
                ))
            normalized_systems[system] = {
                "system": system,
                "runtime_binding_identity_sha256": binding,
                "runtime_authority_set_sha256": set_sha,
                "runtime_authorities": authorities,
                "launcher": launcher,
                "launcher_invocation": invocation,
                "launcher_kind": "dedicated_publication_runtime",
                "publication_capable": True,
                "qualified_cells": qualified,
                "qualified_cells_sha256": _canonical_sha(qualified),
                "raw_evidence_set_sha256": _canonical_sha([
                    value["raw_evidence"] for value in qualified
                ]),
            }
        if len(global_authority_hashes) != 112:
            raise BackendRuntimeQualificationV3Error(
                "qualification v3 requires 112 unique authorities"
            )
        return {
            "schema_version": 3,
            "artifact_kind": ASSESSMENT_KIND,
            "passed": True,
            "status": "ready_for_catalog_binding",
            "blockers": [],
            "qualification_index_sha256": index_sha,
            "upstream_identities": upstream,
            "systems": normalized_systems,
            "coverage": copy.deepcopy(_COVERAGE),
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
    except BackendRuntimeQualificationV3Error as error:
        return _failure(str(error), locals().get("index_sha"))
    except Exception as error:
        return _failure(
            f"backend runtime qualification v3 failed closed: {error}",
            locals().get("index_sha"),
        )


def qualification_catalog_v3_from_assessment(assessment: Any) -> dict[str, Any]:
    """Derive a self-hashed non-authorizing pre-identity candidate."""
    expected_fields = {
        "schema_version", "artifact_kind", "passed", "status", "blockers",
        "qualification_index_sha256", "upstream_identities", "systems",
        "coverage", "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated",
    }
    if (
        type(assessment) is not dict or set(assessment) != expected_fields
        or assessment.get("schema_version") != 3
        or assessment.get("artifact_kind") != ASSESSMENT_KIND
        or assessment.get("passed") is not True
        or assessment.get("status") != "ready_for_catalog_binding"
        or assessment.get("blockers") != []
    ):
        raise BackendRuntimeQualificationV3Error(
            "only a passed v3 physical assessment can form a catalog"
        )
    catalog = {
        "schema_version": 3,
        "artifact_kind": CATALOG_KIND,
        "status": CATALOG_STATUS,
        "publication_scope": PUBLICATION_SCOPE,
        "qualification_index_sha256": assessment[
            "qualification_index_sha256"
        ],
        "upstream_identities": copy.deepcopy(
            assessment["upstream_identities"]
        ),
        "systems": copy.deepcopy(assessment["systems"]),
        "coverage": copy.deepcopy(assessment["coverage"]),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    catalog["catalog_sha256"] = _canonical_sha(catalog)
    return validate_backend_runtime_qualification_v3_catalog(catalog)


BINDING_INDEX_FILENAME = (
    "checkpoint_backend_runtime_qualification_v3_binding_index.json"
)


def _output_directory(root: Path, output_dir: Path) -> Path:
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise BackendRuntimeQualificationV3Error(
            "backend qualification v3 output must remain under project_root"
        ) from error
    if not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise BackendRuntimeQualificationV3Error(
            "backend qualification v3 output must be a normalized child"
        )
    cursor = root
    for part in relative.parts:
        cursor /= part
        if not cursor.exists():
            break
        if _is_link_or_reparse(cursor):
            raise BackendRuntimeQualificationV3Error(
                "backend qualification v3 output contains a link/reparse point"
            )
        if cursor != resolved and not cursor.is_dir():
            raise BackendRuntimeQualificationV3Error(
                "backend qualification v3 output parent is not a directory"
            )
    resolved.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(resolved) or not resolved.is_dir():
        raise BackendRuntimeQualificationV3Error(
            "backend qualification v3 output is not a physical directory"
        )
    return resolved


def _write_immutable_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if (
            _is_link_or_reparse(path) or not path.is_file()
            or int(path.stat().st_nlink) != 1
            or path.read_bytes() != payload
        ):
            raise BackendRuntimeQualificationV3Error(
                f"immutable backend qualification v3 collision: {path.name}"
            )
        return {
            "path": path.name, "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": path.name, "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def promote_backend_runtime_qualification_v3(
    *, project_root: Path, index_path: Path, output_dir: Path,
    raw_evidence_validator: RawEvidenceValidator | None = None,
) -> dict[str, Any]:
    """Write four immutable pre-identity receipts, committing index last."""
    assessment = assess_backend_runtime_qualification_v3(
        project_root=project_root, index_path=index_path,
        raw_evidence_validator=raw_evidence_validator,
    )
    if not assessment["passed"]:
        raise BackendRuntimeQualificationV3Error(
            "backend runtime qualification v3 is blocked: "
            + ", ".join(assessment["blockers"][:8])
        )
    catalog = qualification_catalog_v3_from_assessment(assessment)
    root = Path(project_root).resolve(strict=True)
    destination = _output_directory(root, output_dir)
    receipts: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        system_value = catalog["systems"][system]
        receipt = {
            "schema_version": 3,
            "artifact_kind": "vast_backend_runtime_qualification_v3_receipt",
            "status": CATALOG_STATUS,
            "qualification_scope": PUBLICATION_SCOPE,
            "system": system,
            "qualification_index_sha256": catalog[
                "qualification_index_sha256"
            ],
            "upstream_identities": copy.deepcopy(
                catalog["upstream_identities"]
            ),
            "runtime_binding_identity_sha256": system_value[
                "runtime_binding_identity_sha256"
            ],
            "runtime_authority_set_sha256": system_value[
                "runtime_authority_set_sha256"
            ],
            "runtime_authorities": copy.deepcopy(
                system_value["runtime_authorities"]
            ),
            "launcher": copy.deepcopy(system_value["launcher"]),
            "launcher_invocation": copy.deepcopy(
                system_value["launcher_invocation"]
            ),
            "launcher_kind": "dedicated_publication_runtime",
            "publication_capable": True,
            "qualified_cells": copy.deepcopy(
                system_value["qualified_cells"]
            ),
            "qualified_cells_sha256": system_value[
                "qualified_cells_sha256"
            ],
            "raw_evidence_set_sha256": system_value[
                "raw_evidence_set_sha256"
            ],
            "coverage": {
                "system_count": 1,
                "runtime_authority_count": 28,
                "runtime_authorities_per_system": 28,
                "runtime_cell_count": 140,
                "cells_per_system": 140,
                "deadlines_per_runtime_authority": 5,
            },
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
        receipt["receipt_sha256"] = _canonical_sha(receipt)
        receipts[system] = receipt
    receipt_descriptors = {
        system: {
            "path": (
                f"checkpoint_{system}_backend_runtime_qualification_v3_"
                "receipt.json"
            ),
            "size_bytes": len(_canonical_bytes(receipts[system]) + b"\n"),
            "sha256": hashlib.sha256(
                _canonical_bytes(receipts[system]) + b"\n"
            ).hexdigest(),
        }
        for system in SYSTEMS
    }
    binding = {
        "schema_version": 3,
        "artifact_kind": (
            "vast_backend_runtime_qualification_v3_binding_index"
        ),
        "status": CATALOG_STATUS,
        "qualification_scope": PUBLICATION_SCOPE,
        "qualification_index_sha256": catalog[
            "qualification_index_sha256"
        ],
        "catalog_sha256": catalog["catalog_sha256"],
        "upstream_identities": copy.deepcopy(catalog["upstream_identities"]),
        "systems": list(SYSTEMS),
        "receipts": receipt_descriptors,
        "coverage": copy.deepcopy(_COVERAGE),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    binding["binding_sha256"] = _canonical_sha(binding)
    planned = {
        destination / receipt_descriptors[system]["path"]: receipts[system]
        for system in SYSTEMS
    }
    planned[destination / BINDING_INDEX_FILENAME] = binding
    for path, value in planned.items():
        if path.exists() and (
            _is_link_or_reparse(path) or not path.is_file()
            or int(path.stat().st_nlink) != 1
            or path.read_bytes() != _canonical_bytes(value) + b"\n"
        ):
            raise BackendRuntimeQualificationV3Error(
                f"immutable backend qualification v3 collision: {path.name}"
            )
    for system in SYSTEMS:
        descriptor = _write_immutable_json(
            destination / receipt_descriptors[system]["path"],
            receipts[system],
        )
        if descriptor != receipt_descriptors[system]:
            raise BackendRuntimeQualificationV3Error(
                f"backend qualification v3 receipt {system} descriptor drifted"
            )
    binding_descriptor = _write_immutable_json(
        destination / BINDING_INDEX_FILENAME, binding,
    )
    return {
        "passed": True,
        "status": "promoted_pre_identity_candidate",
        "binding_index": binding,
        "binding_index_descriptor": binding_descriptor,
        "receipt_descriptors": receipt_descriptors,
        "output_dir": str(destination),
    }


__all__ = [
    "ASSESSMENT_KIND", "BINDING_INDEX_FILENAME", "CATALOG_KIND",
    "CODECS", "DEADLINES_MS",
    "BackendRuntimeQualificationV3Error", "POLICIES", "PUBLICATION_SCOPE",
    "SCHEMA_VERSION", "SYSTEMS", "TOPOLOGIES",
    "assess_backend_runtime_qualification_v3",
    "qualification_catalog_v3_from_assessment",
    "promote_backend_runtime_qualification_v3",
    "runtime_binding_identity_v3",
    "validate_backend_runtime_qualification_v3_catalog",
]
