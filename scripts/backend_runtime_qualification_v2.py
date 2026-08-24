#!/usr/bin/env python3
"""Evidence-backed, fail-closed backend runtime qualification v2.

Every one of the 560 capability cells references a physical raw evidence file
and is independently accepted by a caller-supplied raw validator.  Promotion
does not make any runtime publication-ready and does not alter dispatch.
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
from pathlib import Path
from typing import Any, Callable, Mapping

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
UPSTREAM_FIELDS = frozenset(
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
INDEX_FIELDS = frozenset(
    {"schema_version", "artifact_kind", "upstream_identities", "systems"}
)
SYSTEM_FIELDS = frozenset(
    {
        "system",
        "runtime_binding_identity_sha256",
        "launcher",
        "launcher_invocation",
        "launcher_kind",
        "publication_capable",
        "cells",
    }
)
INPUT_CELL_FIELDS = frozenset(
    {"system", "codec", "topology_kind", "policy", "deadline_ms", "raw_evidence"}
)
VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "system",
        "codec",
        "topology_kind",
        "policy",
        "deadline_ms",
        "accepted",
        "synthetic",
        "nonpublication",
        "publication_capable",
        "runtime_binding_identity_sha256",
        "launcher_sha256",
        "launcher_invocation_sha256",
        "raw_evidence_sha256",
        "upstream_identities",
        "validator_identity_sha256",
        "validation_record_sha256",
    }
)
PUBLICATION_SCOPE = "backend_native_runtime_evidence_backed_cells_v2"
BINDING_INDEX_FILENAME = "checkpoint_backend_runtime_qualification_binding_index.json"
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class BackendRuntimeQualificationV2Error(RuntimeError):
    """Qualification input, evidence, validation, or output is unsafe."""


RawEvidenceValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


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
        raise BackendRuntimeQualificationV2Error(
            "backend qualification v2 material is not canonical JSON"
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


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_file(root: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise BackendRuntimeQualificationV2Error(f"{label} path is unsafe")
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BackendRuntimeQualificationV2Error(f"{label} path is not normalized")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if _is_link_or_reparse(cursor):
                raise BackendRuntimeQualificationV2Error(
                    f"{label} path contains a link/reparse point"
                )
        except FileNotFoundError as error:
            raise BackendRuntimeQualificationV2Error(f"{label} is missing") from error
    try:
        candidate = (root / relative).resolve(strict=True)
        candidate.relative_to(root)
    except (OSError, ValueError) as error:
        raise BackendRuntimeQualificationV2Error(
            f"{label} escapes project root"
        ) from error
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise BackendRuntimeQualificationV2Error(f"{label} is not a regular file")
    return candidate


def _verify_descriptor(
    root: Path,
    value: Any,
    label: str,
    *,
    registry: set[tuple[int, int]],
    paths: set[str],
) -> tuple[dict[str, Any], Path]:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        raise BackendRuntimeQualificationV2Error(f"{label} descriptor fields drifted")
    if (
        type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
        or not _valid_sha(value.get("sha256"))
    ):
        raise BackendRuntimeQualificationV2Error(f"{label} descriptor is invalid")
    path = _resolve_file(root, value["path"], label)
    before = path.stat()
    identity = (int(before.st_dev), int(before.st_ino))
    if int(before.st_nlink) != 1:
        raise BackendRuntimeQualificationV2Error(f"{label} hardlink is prohibited")
    if identity in registry or value["path"] in paths:
        raise BackendRuntimeQualificationV2Error(f"{label} artifact alias is prohibited")
    digest = _sha_file(path)
    after = path.stat()
    before_id = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        int(getattr(before, "st_ctime_ns", 0)),
    )
    after_id = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        int(getattr(after, "st_ctime_ns", 0)),
    )
    if before_id != after_id:
        raise BackendRuntimeQualificationV2Error(f"{label} changed while hashing")
    if before.st_size != value["size_bytes"] or digest != value["sha256"]:
        raise BackendRuntimeQualificationV2Error(f"{label} size/SHA drift")
    registry.add(identity)
    paths.add(value["path"])
    return copy.deepcopy(value), path


def _default_raw_evidence_validator(
    _cell: dict[str, Any], _context: dict[str, Any]
) -> dict[str, Any]:
    raise BackendRuntimeQualificationV2Error(
        "raw backend cell evidence validator is required; declarations are not proof"
    )


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


def _validate_raw_result(
    value: Any,
    *,
    coordinate: tuple[str, str, str, str, int | float],
    runtime_identity: str,
    launcher: Mapping[str, Any],
    launcher_invocation: Mapping[str, Any],
    raw_evidence: Mapping[str, Any],
    upstream: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != VALIDATION_FIELDS:
        raise BackendRuntimeQualificationV2Error(
            f"backend cell {coordinate} validator fields drifted"
        )
    if (
        value.get("schema_version") != 2
        or value.get("artifact_kind")
        != "vast_backend_runtime_cell_raw_evidence_validation"
        or tuple(
            value[field]
            for field in ("system", "codec", "topology_kind", "policy", "deadline_ms")
        )
        != coordinate
    ):
        raise BackendRuntimeQualificationV2Error(
            f"backend cell {coordinate} validator relabelled the coordinate"
        )
    if (
        value.get("accepted") is not True
        or value.get("synthetic") is not False
        or value.get("nonpublication") is not False
        or value.get("publication_capable") is not True
    ):
        raise BackendRuntimeQualificationV2Error(
            f"backend cell {coordinate} is unaccepted or nonpublication"
        )
    if (
        value.get("runtime_binding_identity_sha256") != runtime_identity
        or value.get("launcher_sha256") != launcher["sha256"]
        or value.get("launcher_invocation_sha256")
        != launcher_invocation["invocation_sha256"]
        or value.get("raw_evidence_sha256") != raw_evidence["sha256"]
        or value.get("upstream_identities") != upstream
        or not _valid_sha(value.get("validator_identity_sha256"))
    ):
        raise BackendRuntimeQualificationV2Error(
            f"backend cell {coordinate} validation cross-binding drifted"
        )
    unsigned = {
        key: item for key, item in value.items() if key != "validation_record_sha256"
    }
    if value.get("validation_record_sha256") != _canonical_sha(unsigned):
        raise BackendRuntimeQualificationV2Error(
            f"backend cell {coordinate} validation record hash drifted"
        )
    coordinate_value = {
        "system": coordinate[0],
        "codec": coordinate[1],
        "topology_kind": coordinate[2],
        "policy": coordinate[3],
        "deadline_ms": coordinate[4],
    }
    return {
        **coordinate_value,
        "cell_identity_sha256": _canonical_sha(coordinate_value),
        "raw_evidence": copy.deepcopy(raw_evidence),
        "launcher_invocation_sha256": launcher_invocation[
            "invocation_sha256"
        ],
        "validator_identity_sha256": value["validator_identity_sha256"],
        "validation_record_sha256": value["validation_record_sha256"],
    }


def _failure(blocker: str, *, index_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "artifact_kind": "vast_backend_runtime_qualification_v2_assessment",
        "passed": False,
        "status": "blocked",
        "blockers": [blocker],
        "qualification_index_sha256": index_sha,
        "coverage": {"system_count": 0, "runtime_cell_count": 0, "cells_per_system": 0},
        "upstream_identities": None,
        "systems": None,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }


def assess_backend_runtime_qualification_v2(
    *,
    project_root: Path,
    index_path: Path,
    raw_evidence_validator: RawEvidenceValidator | None = None,
) -> dict[str, Any]:
    """Pure assessment of physical per-cell evidence and validator results."""

    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir() or _is_link_or_reparse(root):
            raise BackendRuntimeQualificationV2Error(
                "project_root must be a physical non-reparse directory"
            )
        candidate = Path(index_path)
        if candidate.is_absolute():
            try:
                relative = candidate.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as error:
                raise BackendRuntimeQualificationV2Error(
                    "qualification v2 index must remain under project_root"
                ) from error
        else:
            relative = candidate.as_posix()
        index_file = _resolve_file(root, relative, "qualification v2 index")
        if int(index_file.stat().st_nlink) != 1:
            raise BackendRuntimeQualificationV2Error(
                "qualification v2 index hardlink is prohibited"
            )
        index_sha = _sha_file(index_file)
        try:
            index = json.loads(index_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise BackendRuntimeQualificationV2Error(
                f"invalid qualification v2 index: {error}"
            ) from error
        if (
            type(index) is not dict
            or set(index) != INDEX_FIELDS
            or index.get("schema_version") != 2
            or index.get("artifact_kind")
            != "vast_backend_runtime_qualification_v2_index"
        ):
            raise BackendRuntimeQualificationV2Error(
                "qualification v2 index schema/fields drifted"
            )
        upstream = index.get("upstream_identities")
        if (
            type(upstream) is not dict
            or set(upstream) != UPSTREAM_FIELDS
            or not all(_valid_sha(value) for value in upstream.values())
        ):
            raise BackendRuntimeQualificationV2Error(
                "qualification v2 upstream identities drifted"
            )
        systems = index.get("systems")
        if type(systems) is not dict or set(systems) != set(SYSTEMS):
            raise BackendRuntimeQualificationV2Error(
                "qualification v2 system membership drifted"
            )
        validator = raw_evidence_validator or _default_raw_evidence_validator
        registry: set[tuple[int, int]] = set()
        paths: set[str] = set()
        qualified_systems = {}
        for system in SYSTEMS:
            item = systems[system]
            if type(item) is not dict or set(item) != SYSTEM_FIELDS:
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} fields drifted"
                )
            runtime_identity = item.get("runtime_binding_identity_sha256")
            if item.get("system") != system or not _valid_sha(runtime_identity):
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} identity drifted"
                )
            if (
                item.get("launcher_kind") != "dedicated_publication_runtime"
                or item.get("publication_capable") is not True
            ):
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} launcher is engineering-only or nonpublication"
                )
            launcher, launcher_path = _verify_descriptor(
                root,
                item.get("launcher"),
                f"qualification v2 system {system} launcher",
                registry=registry,
                paths=paths,
            )
            try:
                launcher_invocation = validate_launcher_invocation(
                    item.get("launcher_invocation")
                )
            except Exception as error:
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} launcher invocation is invalid: {error}"
                ) from error
            if runtime_identity != runtime_binding_identity(
                system=system,
                launcher=launcher,
                launcher_invocation=launcher_invocation,
                upstream_identities=upstream,
            ):
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} runtime binding identity drifted"
                )
            cells = item.get("cells")
            if type(cells) is not list or len(cells) != 140:
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} must declare exactly 140 cells"
                )
            expected = _expected_coordinates(system)
            observed: set[
                tuple[str, str, str, str, int | float]
            ] = set()
            verified_inputs = []
            for position, cell in enumerate(cells):
                if type(cell) is not dict or set(cell) != INPUT_CELL_FIELDS:
                    raise BackendRuntimeQualificationV2Error(
                        f"qualification v2 system {system} cell[{position}] fields drifted"
                    )
                deadline = cell.get("deadline_ms")
                if (
                    type(deadline) not in {int, float}
                    or not math.isfinite(float(deadline))
                    or deadline not in DEADLINES_MS
                ):
                    raise BackendRuntimeQualificationV2Error(
                        f"qualification v2 system {system} deadline type drifted"
                    )
                coordinate = (
                    str(cell.get("system")),
                    str(cell.get("codec")),
                    str(cell.get("topology_kind")),
                    str(cell.get("policy")),
                    deadline,
                )
                if coordinate not in expected or coordinate in observed:
                    raise BackendRuntimeQualificationV2Error(
                        f"qualification v2 system {system} cell is missing, duplicate, or relabelled"
                    )
                evidence, evidence_path = _verify_descriptor(
                    root,
                    cell.get("raw_evidence"),
                    f"qualification v2 cell {coordinate} raw evidence",
                    registry=registry,
                    paths=paths,
                )
                verified_inputs.append(
                    (copy.deepcopy(cell), coordinate, evidence, evidence_path)
                )
                observed.add(coordinate)
            if observed != expected:
                raise BackendRuntimeQualificationV2Error(
                    f"qualification v2 system {system} cell coverage mismatch"
                )

            qualified_cells = []
            for cell, coordinate, evidence, evidence_path in verified_inputs:
                raw_result = validator(
                    cell,
                    {
                        "project_root": root,
                        "raw_evidence": copy.deepcopy(evidence),
                        "raw_evidence_path": evidence_path,
                        "runtime_binding_identity_sha256": runtime_identity,
                        "launcher": copy.deepcopy(launcher),
                        "launcher_path": launcher_path,
                        "launcher_invocation": copy.deepcopy(
                            launcher_invocation
                        ),
                        "upstream_identities": copy.deepcopy(upstream),
                    },
                )
                qualified_cells.append(
                    _validate_raw_result(
                        raw_result,
                        coordinate=coordinate,
                        runtime_identity=runtime_identity,
                        launcher=launcher,
                        launcher_invocation=launcher_invocation,
                        raw_evidence=evidence,
                        upstream=upstream,
                    )
                )
            qualified_systems[system] = {
                "system": system,
                "runtime_binding_identity_sha256": runtime_identity,
                "launcher": launcher,
                "launcher_invocation": launcher_invocation,
                "launcher_kind": "dedicated_publication_runtime",
                "publication_capable": True,
                "qualified_cells": qualified_cells,
                "qualified_cells_sha256": _canonical_sha(qualified_cells),
                "raw_evidence_set_sha256": _canonical_sha(
                    [cell["raw_evidence"] for cell in qualified_cells]
                ),
            }
        return {
            "schema_version": 2,
            "artifact_kind": "vast_backend_runtime_qualification_v2_assessment",
            "passed": True,
            "status": "ready_for_atomic_promotion",
            "blockers": [],
            "qualification_index_sha256": index_sha,
            "upstream_identities": copy.deepcopy(upstream),
            "coverage": {
                "system_count": 4,
                "runtime_cell_count": 560,
                "cells_per_system": 140,
            },
            "systems": qualified_systems,
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
    except BackendRuntimeQualificationV2Error as error:
        return _failure(str(error), index_sha=locals().get("index_sha"))
    except Exception as error:
        return _failure(
            f"backend runtime qualification v2 failed closed: {error}",
            index_sha=locals().get("index_sha"),
        )


def _write_immutable_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if (
            _is_link_or_reparse(path)
            or not path.is_file()
            or int(path.stat().st_nlink) != 1
            or path.read_bytes() != payload
        ):
            raise BackendRuntimeQualificationV2Error(
                f"immutable backend qualification v2 collision: {path.name}"
            )
        return {
            "path": path.name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
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
        "path": path.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _output_directory(root: Path, output_dir: Path) -> Path:
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise BackendRuntimeQualificationV2Error(
            "backend qualification v2 output must remain under project_root"
        ) from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise BackendRuntimeQualificationV2Error(
            "backend qualification v2 output must be a normalized child"
        )
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if not cursor.exists():
            break
        if _is_link_or_reparse(cursor):
            raise BackendRuntimeQualificationV2Error(
                "backend qualification v2 output contains a link/reparse point"
            )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def promote_backend_runtime_qualification_v2(
    *,
    project_root: Path,
    index_path: Path,
    output_dir: Path,
    raw_evidence_validator: RawEvidenceValidator | None = None,
) -> dict[str, Any]:
    """Atomically promote four immutable v2 receipts, committing index last."""

    assessment = assess_backend_runtime_qualification_v2(
        project_root=project_root,
        index_path=index_path,
        raw_evidence_validator=raw_evidence_validator,
    )
    if not assessment["passed"]:
        raise BackendRuntimeQualificationV2Error(
            "backend runtime qualification v2 is blocked: "
            + ", ".join(assessment["blockers"][:8])
        )
    root = Path(project_root).resolve(strict=True)
    destination = _output_directory(root, output_dir)
    receipts = {}
    for system in SYSTEMS:
        system_value = assessment["systems"][system]
        receipt = {
            "schema_version": 2,
            "artifact_kind": "vast_backend_runtime_qualification_receipt",
            "status": "accepted_pre_run_backend_runtime_qualification_v2",
            "qualification_scope": PUBLICATION_SCOPE,
            "system": system,
            "qualification_index_sha256": assessment["qualification_index_sha256"],
            "upstream_identities": copy.deepcopy(assessment["upstream_identities"]),
            "runtime_binding_identity_sha256": system_value[
                "runtime_binding_identity_sha256"
            ],
            "launcher": copy.deepcopy(system_value["launcher"]),
            "launcher_invocation": copy.deepcopy(
                system_value["launcher_invocation"]
            ),
            "launcher_kind": "dedicated_publication_runtime",
            "publication_capable": True,
            "qualified_cells": copy.deepcopy(system_value["qualified_cells"]),
            "qualified_cells_sha256": system_value["qualified_cells_sha256"],
            "raw_evidence_set_sha256": system_value["raw_evidence_set_sha256"],
            "coverage": {
                "system_count": 1,
                "runtime_cell_count": 140,
                "cells_per_system": 140,
            },
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
        receipt["sha256"] = _canonical_sha(receipt)
        receipts[system] = receipt
    receipt_descriptors = {
        system: {
            "path": f"checkpoint_{system}_backend_runtime_qualification_receipt.json",
            "size_bytes": len(_canonical_bytes(receipts[system]) + b"\n"),
            "sha256": hashlib.sha256(
                _canonical_bytes(receipts[system]) + b"\n"
            ).hexdigest(),
        }
        for system in SYSTEMS
    }
    binding = {
        "schema_version": 2,
        "artifact_kind": "vast_backend_runtime_qualification_binding_index",
        "status": "accepted_pre_run_backend_runtime_qualification_set_v2",
        "qualification_scope": PUBLICATION_SCOPE,
        "qualification_index_sha256": assessment["qualification_index_sha256"],
        "upstream_identities": copy.deepcopy(assessment["upstream_identities"]),
        "systems": list(SYSTEMS),
        "receipts": receipt_descriptors,
        "coverage": copy.deepcopy(assessment["coverage"]),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    binding["sha256"] = _canonical_sha(binding)
    planned = {
        destination
        / f"checkpoint_{system}_backend_runtime_qualification_receipt.json": receipts[
            system
        ]
        for system in SYSTEMS
    }
    planned[destination / BINDING_INDEX_FILENAME] = binding
    for path, value in planned.items():
        if path.exists() and path.read_bytes() != _canonical_bytes(value) + b"\n":
            raise BackendRuntimeQualificationV2Error(
                f"immutable backend qualification v2 collision: {path.name}"
            )
    for system in SYSTEMS:
        filename = f"checkpoint_{system}_backend_runtime_qualification_receipt.json"
        descriptor = _write_immutable_json(destination / filename, receipts[system])
        if descriptor != receipt_descriptors[system]:
            raise BackendRuntimeQualificationV2Error(
                f"backend qualification v2 receipt {system} descriptor drifted"
            )
    binding_descriptor = _write_immutable_json(
        destination / BINDING_INDEX_FILENAME, binding
    )
    return {
        "passed": True,
        "status": "promoted",
        "binding_index": binding,
        "binding_index_descriptor": binding_descriptor,
        "receipt_descriptors": receipt_descriptors,
        "output_dir": str(destination),
    }


__all__ = [
    "BINDING_INDEX_FILENAME",
    "BackendRuntimeQualificationV2Error",
    "PUBLICATION_SCOPE",
    "SYSTEMS",
    "assess_backend_runtime_qualification_v2",
    "promote_backend_runtime_qualification_v2",
]
