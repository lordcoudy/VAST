"""Build the physical Q4 authority/plan chain without executing Q4.

Phase 1 consumes one externally file- and semantic-pinned source specification,
physically builds the complete 112+4 authority closure and the runtime
materialization plan, then commits its receipt last.  Phase 2 consumes that
receipt plus the persisted result of the existing runtime-registry
materializer, verifies the actual registry, builds the source-registry path
plan and again commits its receipt last.  Neither phase authorizes execution.
"""
from __future__ import annotations

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
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)
from backend_publication_launcher_runtime_authority import (
    assess_backend_publication_launcher_runtime_authority,
    build_backend_publication_launcher_runtime_authority,
    validate_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (
    UPSTREAM_IDENTITY_FIELDS,
    assess_backend_publication_runtime_authority_v2,
    build_backend_publication_runtime_authority_v2,
    validate_backend_publication_runtime_authority_v2,
)
from backend_runtime_validation_runner_authority import (
    assess_backend_runtime_validation_runner_authority,
    build_backend_runtime_validation_runner_authority,
    validate_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    build_backend_runtime_validator_authority_v4,
    validate_backend_runtime_validator_authority_v4,
)
from backend_q4_two_phase_source_registry_v1 import (
    PATH_PLAN_KIND,
    build_backend_q4_two_phase_source_registry_path_plan_v1,
    validate_backend_q4_two_phase_source_registry_path_plan_v1,
)
from publication_guardian_preprocessing_contract_v1 import DirectoryFdCustodyV1
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_q4_runtime_contract_v4 import (
    CODECS,
    POLICIES,
    RUNTIME_CANDIDATE_REGISTRY_KIND,
    SYSTEMS,
    TOPOLOGIES,
    validate_publication_q4_runtime_candidate_registry_v4,
)
from publication_q4_runtime_registry_materializer_v4 import (
    PLAN_KIND,
    RESULT_KIND as RUNTIME_RESULT_KIND,
    SCHEMA_VERSION as RUNTIME_MATERIALIZATION_SCHEMA_VERSION,
    build_publication_q4_runtime_materialization_plan_v4,
    publication_q4_runtime_launcher_input_expectations_v5,
    validate_publication_q4_runtime_candidate_registry_against_plan_v5,
    validate_publication_q4_runtime_materialization_plan_v4,
)


SCHEMA_VERSION = 1
SOURCE_SPEC_KIND = "vast_publication_q4_authority_source_spec_v1"
SOURCE_SPEC_RESULT_KIND = (
    "vast_publication_q4_authority_source_spec_materialization_result_v1"
)
PHASE1_RECEIPT_KIND = "vast_publication_q4_authority_plan_phase1_receipt_v1"
PHASE2_RECEIPT_KIND = "vast_publication_q4_source_plan_phase2_receipt_v1"
PHASE1_RESULT_KIND = "vast_publication_q4_authority_plan_phase1_result_v1"
PHASE2_RESULT_KIND = "vast_publication_q4_source_plan_phase2_result_v1"
PHASE1_RECEIPT_FILENAME = "publication_q4_authority_plan.phase1.receipt.v1.json"
PHASE2_RECEIPT_FILENAME = "publication_q4_source_plan.phase2.receipt.v1.json"
RUNTIME_PLAN_FILENAME = "publication_q4_runtime_materialization_plan.v5.json"
SOURCE_PLAN_FILENAME = "backend_q4_source_registry_path_plan.v1.json"
INVOCATION_FILENAME = "publication_launcher_invocation.v3.json"
VALIDATOR_FILENAME = "backend_runtime_validator.q4.v1.json"
RUNNER_FILENAME = "backend_runtime_validation_runner.v1.json"
EXIT_REJECTED = 78

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind", "descriptor",
    "content_identity_sha256",
})
_COORDINATE_FIELDS = frozenset({"system", "codec", "topology_kind", "policy"})
_DATASET_FIELDS = frozenset({"codec_variant", "front_gate_path", "underbody_path"})
_ACCEPTED_SOURCE_FIELDS = frozenset({
    "model_parity_acceptance_receipt_path",
    "policy_qualification_receipt_path",
    "policy_capability_manifest_path",
    "policy_calibration_mapping_path",
    "resource_qualification_receipt_path",
    "resource_capability_manifest_path",
    "analytics_service_authority_path",
    "guardian_preprocessing_contract_path",
    "guardian_preprocessing_receipt_path",
    "expected_analytics_service_identity_sha256",
})
_PLANNED_OUTPUT_FIELDS = frozenset({
    "runtime_candidate_registry_path", "runtime_materialization_result_path",
    "source_registry_path", "source_materialization_result_path",
})
_RUNTIME_INPUT_FIELDS = frozenset({
    "dataset_manifest", "dataset_files", "source_runtime_artifacts",
    "backend_runtime_artifacts", "analytics_authority", "policy_authority",
    "cohort_topology_plan", "resource_contract",
    "system_specific_launcher_input",
})
_RUNTIME_BUILD_FIELDS = frozenset({
    "coordinate", "expected_authority_sha256", "inputs",
})
_LAUNCHER_BUILD_FIELDS = frozenset({
    "system", "runtime_closure_manifest_path", "python_executable_path",
    "publication_launcher_path", "runtime_leaf_paths",
    "expected_authority_sha256", "expected_closure_manifest_sha256",
    "expected_runtime_closure_set_sha256",
})
_VALIDATOR_BUILD_FIELDS = frozenset({
    "validator_id", "implementation_descriptor",
    "qualification_input_schema_identity_sha256",
    "validation_system_context_schema_identity_sha256",
    "validation_request_schema_identity_sha256",
    "validation_record_schema_identity_sha256",
    "validation_system_shard_schema_identity_sha256",
    "validation_record_set_index_schema_identity_sha256",
    "validation_protocol_identity_sha256",
    "validation_input_schema_identity_sha256",
    "validation_output_schema_identity_sha256",
    "expected_authority_sha256",
})
_RUNNER_BUILD_FIELDS = frozenset({
    "runner_id", "runtime_bundle_manifest_path", "runtime_leaf_paths",
    "python_executable_path", "runner_path",
    "validation_protocol_identity_sha256", "input_schema_identity_sha256",
    "output_schema_identity_sha256", "expected_runner_authority_sha256",
})
_SOURCE_SPEC_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "accepted_upstream_identities",
    "accepted_sources", "dataset_sources", "runtime_authority_builds",
    "launcher_runtime_authority_builds",
    "publication_launcher_invocation_v3_sha256",
    "q4_validator_authority_build", "runner_authority_build",
    "planned_outputs", "source_spec_sha256",
})
_SOURCE_SPEC_MATERIAL_FIELDS = _SOURCE_SPEC_FIELDS - {"source_spec_sha256"}
_RUNTIME_RECORD_FIELDS = frozenset({"coordinate", "artifact"})
_LAUNCHER_RECORD_FIELDS = frozenset({"system", "artifact"})
_PHASE1_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "source_spec", "source_spec_sha256",
    "accepted_upstream_identities", "accepted_sources", "planned_outputs",
    "publication_launcher_invocation_v3", "q4_validator_authority",
    "runner_authority", "launcher_runtime_authorities",
    "runtime_authorities", "runtime_materialization_plan", "receipt_sha256",
})
_PHASE2_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "phase1_receipt", "phase1_receipt_sha256",
    "source_spec", "source_spec_sha256", "runtime_materialization_result",
    "runtime_candidate_registry", "source_registry_path_plan",
    "planned_outputs", "receipt_sha256",
})
_RUNTIME_RESULT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "plan_sha256", "runtime_candidate_registry",
    "runtime_candidate_registry_sha256", "dataset_binding_count",
    "runtime_authority_count", "result_sha256",
})
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class PublicationQ4AuthorityPlanPipelineV1Error(RuntimeError):
    """The externally pinned Q4 authority/plan transaction drifted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4AuthorityPlanPipelineV1Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None, depth: int = 0) -> None:
    _require(depth <= 96, "Q4 authority-plan JSON nesting is excessive")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "Q4 authority-plan JSON is non-finite")
        return
    _require(type(value) in {dict, list}, "Q4 authority-plan value is not JSON")
    active = set() if active is None else active
    identity = id(value)
    _require(identity not in active, "Q4 authority-plan JSON contains a cycle")
    active.add(identity)
    try:
        values = value.values() if type(value) is dict else value
        if type(value) is dict:
            _require(all(type(key) is str for key in value), "Q4 authority-plan key type drifted")
        for item in values:
            _strict_json(item, active=active, depth=depth + 1)
    finally:
        active.remove(identity)


def canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    _strict_json(value)
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            "Q4 authority-plan value is not canonical JSON"
        ) from error
    return payload + (b"\n" if newline else b"")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _relative(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is empty")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value and ":" not in value and "\x00" not in value
        and not posix.is_absolute() and not windows.is_absolute()
        and posix.as_posix() == value and bool(posix.parts)
        and all(
            part not in {"", ".", ".."} and not part.endswith((".", " "))
            and part.split(".", 1)[0].upper() not in _RESERVED
            and all(ord(character) >= 32 for character in part)
            for part in posix.parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and size > 0, f"{label} descriptor size drifted")
    return {
        "path": _relative(value.get("path"), label), "size_bytes": size,
        "sha256": _sha(value.get("sha256"), label),
    }


def _coordinate(value: Any) -> dict[str, str]:
    _require(type(value) is dict and set(value) == _COORDINATE_FIELDS,
             "Q4 authority coordinate fields drifted")
    result = {key: value.get(key) for key in (
        "system", "codec", "topology_kind", "policy",
    )}
    _require(
        result["system"] in SYSTEMS and result["codec"] in CODECS
        and result["topology_kind"] in TOPOLOGIES
        and result["policy"] in POLICIES
        and all(type(item) is str for item in result.values()),
        "Q4 authority coordinate value drifted",
    )
    return {key: str(item) for key, item in result.items()}


def _coordinates() -> list[dict[str, str]]:
    return [
        {"system": system, "codec": codec, "topology_kind": topology,
         "policy": policy}
        for system in SYSTEMS for codec in CODECS
        for topology in TOPOLOGIES for policy in POLICIES
    ]


def _root(value: Path | str) -> Path:
    candidate = Path(os.path.abspath(os.fspath(value)))
    try:
        resolved = candidate.resolve(strict=True)
        info = candidate.lstat()
    except OSError as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            "project_root is unavailable"
        ) from error
    _require(
        candidate == resolved and stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
        "project_root is not one canonical physical directory",
    )
    return resolved


def _under_root(
    root: Path, value: Path | str, *, label: str, must_exist: bool = True,
) -> Path:
    raw = Path(value)
    candidate = (
        Path(os.path.abspath(raw)) if raw.is_absolute()
        else root.joinpath(*PurePosixPath(_relative(raw.as_posix(), label)).parts)
    )
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} escaped project_root"
        ) from error
    cursor = root
    for part in candidate.relative_to(root).parts:
        cursor /= part
        if not os.path.lexists(cursor):
            break
        info = cursor.lstat()
        _require(
            not stat.S_ISLNK(info.st_mode)
            and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
            f"{label} contains a link/reparse point",
        )
    if must_exist:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise PublicationQ4AuthorityPlanPipelineV1Error(
                f"{label} is unavailable"
            ) from error
        _require(resolved == candidate, f"{label} resolved through an alias")
    return candidate


def _file_fingerprint(info: os.stat_result) -> tuple[int, ...]:
    """Track physical/content identity without read-mutated access time."""

    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_uid), int(info.st_gid),
        int(info.st_size), int(info.st_mtime_ns), int(info.st_ctime_ns),
    )


def _open_directory_custody(
    root: Path, value: Path | str, label: str,
) -> DirectoryFdCustodyV1:
    path = _under_root(root, value, label=label)
    try:
        custody = DirectoryFdCustodyV1.open_existing(path, label=label)
        _require(custody.path == path, f"{label} custody path drifted")
        custody.verify()
        return custody
    except PublicationQ4AuthorityPlanPipelineV1Error:
        raise
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"cannot establish {label} directory custody"
        ) from error


def _read_bytes_descriptor_from_custody(
    root: Path,
    custody: DirectoryFdCustodyV1,
    value: Path | str,
    label: str,
) -> tuple[dict[str, Any], bytes, tuple[int, ...]]:
    """Read one direct child through an already-held parent namespace."""

    path = _under_root(root, value, label=label)
    _require(path != root and path.name not in {"", ".", ".."},
             f"{label} file leaf drifted")
    _require(
        path.parent == custody.path
        and PurePosixPath(path.name).parts == (path.name,),
        f"{label} escaped its held parent namespace",
    )
    descriptor = -1
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    size = 0
    try:
        nofollow = int(getattr(os, "O_NOFOLLOW", 0))
        _require(nofollow != 0 and os.open in os.supports_dir_fd,
                 f"{label} requires POSIX openat/O_NOFOLLOW custody")
        custody.verify()
        before = os.stat(
            path.name, dir_fd=custody.directory_fd, follow_symlinks=False,
        )
        _require(
            stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode)
            and not int(getattr(before, "st_file_attributes", 0)) & 0x400
            and int(before.st_nlink) == 1 and 0 < int(before.st_size) <= 512 * 1024 * 1024,
            f"{label} is not one bounded regular file",
        )
        descriptor = os.open(
            path.name, os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
            | nofollow
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=custody.directory_fd,
        )
        opened = os.fstat(descriptor)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            _require(
                size <= 512 * 1024 * 1024,
                f"{label} exceeded its size bound while being read",
            )
            chunks.append(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        named = os.stat(
            path.name, dir_fd=custody.directory_fd, follow_symlinks=False,
        )
        custody.verify()
        _require(
            _file_fingerprint(before) == _file_fingerprint(opened)
            == _file_fingerprint(after) == _file_fingerprint(named),
            f"{label} changed while being read",
        )
        _require(size == int(after.st_size), f"{label} size changed while being read")
    except PublicationQ4AuthorityPlanPipelineV1Error:
        raise
    except OSError as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} physical read failed"
        ) from error
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} directory custody changed while being read"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    payload = b"".join(chunks)
    return ({
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload), "sha256": digest.hexdigest(),
    }, payload, _file_fingerprint(after))


def _read_bytes_descriptor(
    root: Path, value: Path | str, label: str,
) -> tuple[dict[str, Any], bytes]:
    path = _under_root(root, value, label=label)
    custody = _open_directory_custody(root, path.parent, f"{label} parent")
    try:
        descriptor, payload, _fingerprint = _read_bytes_descriptor_from_custody(
            root, custody, path, label,
        )
        return descriptor, payload
    finally:
        custody.close()


def _load_json(
    root: Path, value: Path | str, label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor, payload = _read_bytes_descriptor(root, value, label)
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} is not JSON"
        ) from error
    _require(type(document) is dict, f"{label} is not a JSON object")
    _require(
        payload in {canonical_bytes(document), canonical_bytes(document, newline=True)},
        f"{label} is not canonical JSON",
    )
    return descriptor, dict(document)


def _load_json_from_custody(
    root: Path,
    custody: DirectoryFdCustodyV1,
    value: Path | str,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any], tuple[int, ...]]:
    descriptor, payload, fingerprint = _read_bytes_descriptor_from_custody(
        root, custody, value, label,
    )
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} is not JSON"
        ) from error
    _require(type(document) is dict, f"{label} is not a JSON object")
    _require(
        payload in {canonical_bytes(document), canonical_bytes(document, newline=True)},
        f"{label} is not canonical JSON",
    )
    return descriptor, dict(document), fingerprint


def _load_by_descriptor(
    root: Path, value: Any, label: str,
) -> dict[str, Any]:
    expected = _descriptor(value, label)
    observed, document = _load_json(root, expected["path"], label)
    _require(observed == expected, f"{label} physical descriptor drifted")
    return document


def _load_by_descriptor_from_custody(
    root: Path,
    custody: DirectoryFdCustodyV1,
    value: Any,
    expected_fingerprint: tuple[int, ...],
    label: str,
) -> dict[str, Any]:
    expected = _descriptor(value, label)
    observed, document, fingerprint = _load_json_from_custody(
        root, custody, expected["path"], label,
    )
    _require(
        observed == expected and fingerprint == expected_fingerprint,
        f"{label} physical descriptor/inode drifted",
    )
    return document


def _accepted_sources(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _ACCEPTED_SOURCE_FIELDS,
             "accepted Q4 source fields drifted")
    result = {
        key: (
            _sha(item, "accepted analytics service identity")
            if key == "expected_analytics_service_identity_sha256"
            else _relative(item, f"accepted source {key}")
        )
        for key, item in value.items()
    }
    paths = [item for key, item in result.items() if key.endswith("_path")]
    _require(len(paths) == len({item.casefold() for item in paths}),
             "accepted Q4 source paths alias")
    return result


def _planned_outputs(value: Any) -> dict[str, str]:
    _require(type(value) is dict and set(value) == _PLANNED_OUTPUT_FIELDS,
             "planned Q4 output fields drifted")
    result = {key: _relative(value.get(key), f"planned output {key}") for key in sorted(value)}
    _require(len(result) == len({item.casefold() for item in result.values()}),
             "planned Q4 output paths alias")
    return {key: result[key] for key in value}


def _typed_ref(
    descriptor: Mapping[str, Any], *, schema_version: int, kind: str,
    identity: str,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        "descriptor": copy.deepcopy(dict(descriptor)),
        "content_identity_sha256": _sha(identity, f"{kind} semantic"),
    }


def _validate_typed_ref(
    value: Any, *, schema_version: int, kind: str, label: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _TYPED_REF_FIELDS,
             f"{label} typed reference fields drifted")
    _require(
        type(value.get("artifact_schema_version")) is int
        and value.get("artifact_schema_version") == schema_version
        and value.get("artifact_kind") == kind,
        f"{label} typed reference identity drifted",
    )
    return {
        "artifact_schema_version": schema_version, "artifact_kind": kind,
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic",
        ),
    }


def _expected_policy_outputs(inputs: Mapping[str, Any]) -> dict[str, Any]:
    policy = inputs.get("policy_authority")
    _require(type(policy) is dict and set(policy) == {"capability", "calibration", "static_map"},
             "runtime build policy authority fields drifted")
    result: dict[str, Any] = {}
    for name in ("capability", "calibration", "static_map"):
        item = policy.get(name)
        if item is None:
            result[name] = None
        else:
            _require(type(item) is dict and type(item.get("descriptor")) is dict,
                     f"runtime build policy {name} is invalid")
            result[name] = copy.deepcopy(item["descriptor"])
    return result


def build_publication_q4_authority_source_spec_v1(
    *, accepted_upstream_identities: Mapping[str, Any],
    accepted_sources: Mapping[str, Any],
    dataset_sources: Sequence[Mapping[str, Any]],
    runtime_authority_builds: Sequence[Mapping[str, Any]],
    launcher_runtime_authority_builds: Sequence[Mapping[str, Any]],
    publication_launcher_invocation_v3_sha256: str,
    q4_validator_authority_build: Mapping[str, Any],
    runner_authority_build: Mapping[str, Any],
    planned_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact externally pinnable source specification."""

    unsigned: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SOURCE_SPEC_KIND,
        "status": "externally_pinned_accepted_q4_authority_sources",
        "authorization_eligible": False,
        "execution_authorized": False,
        "accepted_upstream_identities": copy.deepcopy(
            dict(accepted_upstream_identities)
        ),
        "accepted_sources": copy.deepcopy(dict(accepted_sources)),
        "dataset_sources": copy.deepcopy(list(dataset_sources)),
        "runtime_authority_builds": copy.deepcopy(list(runtime_authority_builds)),
        "launcher_runtime_authority_builds": copy.deepcopy(
            list(launcher_runtime_authority_builds)
        ),
        "publication_launcher_invocation_v3_sha256": (
            publication_launcher_invocation_v3_sha256
        ),
        "q4_validator_authority_build": copy.deepcopy(
            dict(q4_validator_authority_build)
        ),
        "runner_authority_build": copy.deepcopy(dict(runner_authority_build)),
        "planned_outputs": copy.deepcopy(dict(planned_outputs)),
    }
    return validate_publication_q4_authority_source_spec_v1(
        {**unsigned, "source_spec_sha256": canonical_sha256(unsigned)}
    )


def validate_publication_q4_authority_source_spec_v1(value: Any) -> dict[str, Any]:
    """Validate the one externally pinned complete authority build specification."""
    _require(type(value) is dict and set(value) == _SOURCE_SPEC_FIELDS,
             "Q4 authority source-spec fields drifted")
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == SOURCE_SPEC_KIND
        and value.get("status") == "externally_pinned_accepted_q4_authority_sources"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 authority source-spec header/claims drifted",
    )
    upstream = value.get("accepted_upstream_identities")
    _require(type(upstream) is dict and set(upstream) == set(UPSTREAM_IDENTITY_FIELDS),
             "Q4 authority source-spec upstream fields drifted")
    checked_upstream = {key: _sha(upstream.get(key), f"accepted upstream {key}") for key in sorted(upstream)}
    accepted = _accepted_sources(value.get("accepted_sources"))
    datasets_raw = value.get("dataset_sources")
    _require(type(datasets_raw) is list and len(datasets_raw) == len(CODECS),
             "Q4 authority source-spec dataset coverage drifted")
    datasets: list[dict[str, str]] = []
    for position, (item, codec) in enumerate(zip(datasets_raw, CODECS, strict=True)):
        _require(type(item) is dict and set(item) == _DATASET_FIELDS
                 and item.get("codec_variant") == codec,
                 f"Q4 authority source-spec dataset[{position}] drifted")
        datasets.append({
            "codec_variant": codec,
            "front_gate_path": _relative(item.get("front_gate_path"), "front source"),
            "underbody_path": _relative(item.get("underbody_path"), "underbody source"),
        })
    expected_coordinates = _coordinates()
    raw_runtime = value.get("runtime_authority_builds")
    _require(type(raw_runtime) is list and len(raw_runtime) == len(expected_coordinates),
             "Q4 authority source-spec runtime coverage drifted")
    runtime: list[dict[str, Any]] = []
    for position, (item, expected) in enumerate(zip(raw_runtime, expected_coordinates, strict=True)):
        _require(type(item) is dict and set(item) == _RUNTIME_BUILD_FIELDS,
                 f"runtime authority build[{position}] fields drifted")
        coordinate = _coordinate(item.get("coordinate"))
        _require(coordinate == expected, f"runtime authority build[{position}] order drifted")
        inputs = item.get("inputs")
        _require(type(inputs) is dict and set(inputs) == _RUNTIME_INPUT_FIELDS,
                 f"runtime authority build[{position}] input fields drifted")
        manifest = _descriptor(inputs.get("dataset_manifest"), "runtime dataset manifest")
        _require(manifest["sha256"] == checked_upstream["dataset_manifest_sha256"],
                 f"runtime authority build[{position}] dataset lineage drifted")
        files = inputs.get("dataset_files")
        _require(type(files) is list and len(files) == 2,
                 f"runtime authority build[{position}] dataset file coverage drifted")
        dataset_paths = {_descriptor(row, "runtime dataset file")["path"] for row in files}
        source_row = datasets[CODECS.index(coordinate["codec"])]
        _require(dataset_paths == {source_row["front_gate_path"], source_row["underbody_path"]},
                 f"runtime authority build[{position}] dataset sources drifted")
        _expected_policy_outputs(inputs)
        runtime.append({
            "coordinate": coordinate,
            "expected_authority_sha256": _sha(
                item.get("expected_authority_sha256"), "expected runtime authority",
            ),
            "inputs": copy.deepcopy(inputs),
        })
    raw_launchers = value.get("launcher_runtime_authority_builds")
    _require(type(raw_launchers) is list and len(raw_launchers) == len(SYSTEMS),
             "Q4 launcher build coverage drifted")
    launchers: list[dict[str, Any]] = []
    for position, (item, system) in enumerate(zip(raw_launchers, SYSTEMS, strict=True)):
        _require(type(item) is dict and set(item) == _LAUNCHER_BUILD_FIELDS
                 and item.get("system") == system,
                 f"launcher authority build[{position}] fields/order drifted")
        checked = copy.deepcopy(item)
        for key in ("runtime_closure_manifest_path", "python_executable_path", "publication_launcher_path"):
            checked[key] = _relative(item.get(key), f"launcher build {key}")
        leaves = item.get("runtime_leaf_paths")
        _require(type(leaves) is list and bool(leaves)
                 and all(type(row) is str for row in leaves),
                 f"launcher authority build[{position}] leaves drifted")
        checked["runtime_leaf_paths"] = [_relative(row, "launcher runtime leaf") for row in leaves]
        for key in ("expected_authority_sha256", "expected_closure_manifest_sha256", "expected_runtime_closure_set_sha256"):
            checked[key] = _sha(item.get(key), f"launcher build {key}")
        launchers.append(checked)
    invocation_sha = _sha(value.get("publication_launcher_invocation_v3_sha256"),
                          "publication launcher invocation v3")
    _require(invocation_sha == publication_launcher_invocation_v3_contract()["invocation_sha256"],
             "publication launcher invocation v3 external pin drifted")
    validator = value.get("q4_validator_authority_build")
    _require(type(validator) is dict and set(validator) == _VALIDATOR_BUILD_FIELDS,
             "Q4 validator build fields drifted")
    _descriptor(validator.get("implementation_descriptor"), "Q4 validator implementation")
    for key in _VALIDATOR_BUILD_FIELDS:
        if key.endswith("_sha256"):
            _sha(validator.get(key), f"Q4 validator {key}")
    runner = value.get("runner_authority_build")
    _require(type(runner) is dict and set(runner) == _RUNNER_BUILD_FIELDS,
             "Q4 runner build fields drifted")
    for key in _RUNNER_BUILD_FIELDS:
        if key.endswith("_sha256"):
            _sha(runner.get(key), f"Q4 runner {key}")
        elif key.endswith("_path"):
            _relative(runner.get(key), f"Q4 runner {key}")
    _require(type(runner.get("runtime_leaf_paths")) is list
             and bool(runner["runtime_leaf_paths"]), "Q4 runner leaves drifted")
    planned = _planned_outputs(value.get("planned_outputs"))
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "source_spec_sha256"}
    identity = _sha(value.get("source_spec_sha256"), "Q4 authority source-spec")
    _require(identity == canonical_sha256(unsigned), "Q4 authority source-spec self-hash drifted")
    return {
        **unsigned,
        "accepted_upstream_identities": checked_upstream,
        "accepted_sources": accepted, "dataset_sources": datasets,
        "runtime_authority_builds": runtime,
        "launcher_runtime_authority_builds": launchers,
        "planned_outputs": planned, "source_spec_sha256": identity,
    }


def load_publication_q4_authority_source_material_v1(
    *, project_root: Path | str, source_material_path: Path | str,
    expected_source_material_file_sha256: str,
    expected_source_material_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Cold-load one canonical unsigned source material with two external pins."""

    root = _root(project_root)
    descriptor, material = _load_json(
        root, source_material_path, "Q4 authority source material",
    )
    _require(
        descriptor["sha256"]
        == _sha(
            expected_source_material_file_sha256,
            "expected Q4 source-material file",
        ),
        "Q4 authority source-material file pin drifted",
    )
    _require(
        set(material) == _SOURCE_SPEC_MATERIAL_FIELDS,
        "Q4 authority source-material fields drifted",
    )
    identity = canonical_sha256(material)
    _require(
        identity
        == _sha(
            expected_source_material_sha256,
            "expected Q4 source-material semantic",
        ),
        "Q4 authority source-material semantic pin drifted",
    )
    source_spec = validate_publication_q4_authority_source_spec_v1(
        {**copy.deepcopy(material), "source_spec_sha256": identity}
    )
    return descriptor, source_spec


def load_publication_q4_authority_source_spec_v1(
    *, project_root: Path | str, source_spec_path: Path | str,
    expected_source_spec_file_sha256: str,
    expected_source_spec_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _root(project_root)
    descriptor, raw = _load_json(root, source_spec_path, "Q4 authority source-spec")
    _require(
        descriptor["sha256"]
        == _sha(expected_source_spec_file_sha256, "expected source-spec file"),
        "Q4 authority source-spec file pin drifted",
    )
    checked = validate_publication_q4_authority_source_spec_v1(raw)
    _require(
        checked["source_spec_sha256"]
        == _sha(expected_source_spec_sha256, "expected source-spec semantic"),
        "Q4 authority source-spec semantic pin drifted",
    )
    return descriptor, checked


def _output_relative(root: Path, value: Path | str, label: str) -> tuple[Path, str]:
    path = _under_root(root, value, label=label, must_exist=False)
    relative = path.relative_to(root).as_posix()
    _require(PurePosixPath(relative).name not in {"", ".", ".."}, f"{label} leaf drifted")
    return path, relative


def _create_output_custody(root: Path, value: Path | str, label: str) -> DirectoryFdCustodyV1:
    _require(os.name == "posix", "Q4 authority-plan output custody requires WSL/Linux")
    path, _relative_output = _output_relative(root, value, label)
    _require(not os.path.lexists(path), f"{label} already exists; overwrite refused")
    parent = path.parent
    _require(parent.exists(), f"{label} parent must already exist")
    try:
        custody = DirectoryFdCustodyV1.open_existing(parent, label=label)
        custody.mkdir_child_exclusive(path.name)
        return custody
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"cannot create {label} without overwrite"
        ) from error


def _open_or_create_output_custody(
    root: Path,
    value: Path | str,
    label: str,
) -> tuple[DirectoryFdCustodyV1, bool]:
    """Hold a new transaction directory or an exact resumable predecessor."""

    path, _relative_output = _output_relative(root, value, label)
    if os.path.lexists(path):
        return _open_directory_custody(root, path, label), False
    return _create_output_custody(root, path, label), True


def _observed_namespace_names(
    custody: DirectoryFdCustodyV1,
    label: str,
) -> tuple[str, ...]:
    try:
        custody.verify()
        observed = os.listdir(custody.directory_fd)
        _require(
            all(
                type(name) is str
                and name not in {"", ".", ".."}
                and PurePosixPath(name).parts == (name,)
                for name in observed
            )
            and len(observed) == len(set(observed))
            and len(observed) == len({name.casefold() for name in observed}),
            f"{label} namespace contains an invalid member",
        )
        custody.verify()
        return tuple(sorted(observed))
    except PublicationQ4AuthorityPlanPipelineV1Error:
        raise
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} namespace inspection failed"
        ) from error


def _read_exact_resumable_payload(
    *,
    root: Path,
    custody: DirectoryFdCustodyV1,
    physical_custody: PhysicalRootCustodyV1,
    name: str,
    payload: bytes,
    label: str,
    expected_fingerprint: tuple[int, ...] | None = None,
) -> tuple[int, ...]:
    path = custody.path / name
    durable_descriptor, durable_identity = (
        physical_custody.adopt_exact_durable_identity(
            path.relative_to(root).as_posix(),
            payload,
            label=label,
            mode=0o400,
            expected_identity=(
                None
                if expected_fingerprint is None
                else (expected_fingerprint[0], expected_fingerprint[1])
            ),
        )
    )
    descriptor, observed, fingerprint = _read_bytes_descriptor_from_custody(
        root, custody, path, label,
    )
    expected_descriptor = {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    _require(
        descriptor == expected_descriptor
        and durable_descriptor == expected_descriptor
        and observed == payload
        and fingerprint[:2] == durable_identity
        and (
            stat.S_IMODE(fingerprint[2]) == 0o400
            or not physical_custody.permission_modes_enforced
        ),
        f"{label} exact resumable payload drifted",
    )
    if expected_fingerprint is not None:
        _require(
            fingerprint == expected_fingerprint,
            f"{label} inode identity changed during transaction",
        )
    return fingerprint


def _after_artifact_commit(
    callback: Callable[[str], None] | None,
    boundary: str,
    *,
    root: Path,
    custody: DirectoryFdCustodyV1,
) -> None:
    if callback is not None:
        before = os.fstat(custody.directory_fd)
        epoch = (
            int(before.st_dev), int(before.st_ino), int(before.st_mode),
            int(before.st_nlink), int(before.st_uid), int(before.st_gid),
            int(before.st_mtime_ns), int(before.st_ctime_ns),
        )
        with PhysicalRootCustodyV1.open(
            root, label=f"{boundary} fault-boundary project_root"
        ) as watcher:
            relative_probe = (
                custody.path.relative_to(root) / ".publication-q4-fault-boundary"
            ).as_posix()
            mutation_watch = watcher.begin_read_namespace_mutation_watch(
                [relative_probe], label=f"{boundary} fault boundary"
            )
            try:
                callback(boundary)
            except BaseException:
                if mutation_watch is not None:
                    mutation_watch.close()
                raise
            watcher.verify_pinned_directory_mutation_watch(
                mutation_watch, label=f"{boundary} fault boundary"
            )
        custody.verify()
        after = os.fstat(custody.directory_fd)
        _require(
            epoch
            == (
                int(after.st_dev), int(after.st_ino), int(after.st_mode),
                int(after.st_nlink), int(after.st_uid), int(after.st_gid),
                int(after.st_mtime_ns), int(after.st_ctime_ns),
            ),
            f"{boundary} directory namespace changed across fault boundary",
        )


def _namespace_snapshot(
    custody: DirectoryFdCustodyV1, expected_names: Sequence[str], label: str,
) -> dict[str, tuple[int, ...]]:
    expected = list(expected_names)
    _require(
        bool(expected)
        and len(expected) == len(set(expected))
        and len(expected) == len({name.casefold() for name in expected})
        and all(
            type(name) is str
            and PurePosixPath(name).parts == (name,)
            and name not in {"", ".", ".."}
            for name in expected
        ),
        f"{label} expected namespace names drifted",
    )
    try:
        custody.verify()
        observed = os.listdir(custody.directory_fd)
        _require(all(type(name) is str for name in observed),
                 f"{label} namespace returned a non-text member")
        _require(
            len(observed) == len(expected)
            and set(observed) == set(expected)
            and len(observed) == len({name.casefold() for name in observed}),
            f"{label} namespace members drifted",
        )
        snapshot: dict[str, tuple[int, ...]] = {}
        for name in sorted(expected):
            info = os.stat(
                name, dir_fd=custody.directory_fd, follow_symlinks=False,
            )
            _require(
                stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                and not int(getattr(info, "st_file_attributes", 0)) & 0x400
                and int(info.st_nlink) == 1 and int(info.st_size) > 0,
                f"{label} member {name} is not one physical regular file",
            )
            snapshot[name] = _file_fingerprint(info)
        custody.verify()
        return snapshot
    except PublicationQ4AuthorityPlanPipelineV1Error:
        raise
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} namespace inspection failed"
        ) from error


def _require_namespace_stable(
    custody: DirectoryFdCustodyV1, expected_names: Sequence[str],
    expected_snapshot: Mapping[str, tuple[int, ...]], label: str,
) -> None:
    observed = _namespace_snapshot(custody, expected_names, label)
    _require(observed == dict(expected_snapshot),
             f"{label} namespace inode identities changed")


def materialize_publication_q4_authority_source_spec_v1(
    *, project_root: Path | str, source_material_path: Path | str,
    expected_source_material_file_sha256: str,
    expected_source_material_sha256: str, output_path: Path | str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Immutably commit and cold-reload one externally pinned source spec."""

    root = _root(project_root)
    _material_descriptor, source_spec = (
        load_publication_q4_authority_source_material_v1(
            project_root=root, source_material_path=source_material_path,
            expected_source_material_file_sha256=(
                expected_source_material_file_sha256
            ),
            expected_source_material_sha256=expected_source_material_sha256,
        )
    )
    output = _under_root(
        root, output_path, label="Q4 authority source-spec output",
        must_exist=False,
    )
    _require(
        output != root and output.name not in {"", ".", ".."},
        "Q4 authority source-spec output leaf drifted",
    )
    _require(
        output.parent.exists(),
        "Q4 authority source-spec output parent must already exist",
    )
    payload = canonical_bytes(source_spec, newline=True)
    expected_file_sha256 = hashlib.sha256(payload).hexdigest()
    custody = _open_directory_custody(
        root, output.parent, "Q4 authority source-spec output parent",
    )
    physical_custody = PhysicalRootCustodyV1.open(
        root, label="Q4 authority source-spec project_root"
    )
    try:
        def fault_step(step: str) -> None:
            _after_artifact_commit(
                after_artifact_commit,
                f"{output.name}:{step}",
                root=root,
                custody=custody,
            )

        committed_descriptor, identity, disposition = (
            physical_custody.commit_or_adopt_exact_identity(
                output.relative_to(root).as_posix(),
                payload,
                label="Q4 authority source-spec output",
                mode=0o400,
                create_parents=False,
                after_publish_step=(
                    fault_step if after_artifact_commit is not None else None
                ),
            )
        )
        _require(
            committed_descriptor["sha256"] == expected_file_sha256,
            "Q4 authority source-spec physical descriptor drifted",
        )
        if disposition == "published":
            _after_artifact_commit(
                after_artifact_commit,
                output.name,
                root=root,
                custody=custody,
            )
        custody.assert_owned(output.name, identity)
        descriptor, raw_loaded, fingerprint = _load_json_from_custody(
            root,
            custody,
            output,
            "committed Q4 authority source-spec",
        )
        loaded = validate_publication_q4_authority_source_spec_v1(raw_loaded)
        _require(
            loaded == source_spec
            and descriptor["sha256"] == expected_file_sha256
            and loaded["source_spec_sha256"]
            == source_spec["source_spec_sha256"]
            and fingerprint[:2] == identity,
            "Q4 authority source-spec changed across immutable cold reload",
        )
        custody.assert_owned(output.name, identity)
        custody.verify()
        return loaded
    finally:
        physical_custody.close()
        custody.close()


def _payload_descriptor(root: Path, output: Path, name: str, value: Any) -> tuple[dict[str, Any], bytes]:
    payload = canonical_bytes(value, newline=True)
    return {
        "path": (output / name).relative_to(root).as_posix(),
        "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
    }, payload


def _write_payloads_receipt_last(
    *, root: Path, output_dir: Path | str,
    payloads: Sequence[tuple[str, bytes]], receipt_name: str,
    receipt_payload: bytes, label: str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> None:
    custody, created_directory = _open_or_create_output_custody(
        root, output_dir, label
    )
    physical_custody = PhysicalRootCustodyV1.open(
        root, label=f"{label} project_root"
    )
    try:
        names = [name for name, _payload in payloads]
        _require(
            receipt_name not in names
            and len(names) == len(set(names))
            and len(names) == len({name.casefold() for name in names}),
            "receipt-last payload namespace aliases",
        )
        _require(
            all(type(payload) is bytes and bool(payload) for _name, payload in payloads)
            and type(receipt_payload) is bytes
            and bool(receipt_payload),
            f"{label} contains an empty/non-bytes payload",
        )
        if created_directory:
            _after_artifact_commit(
                after_artifact_commit,
                "output_directory",
                root=root,
                custody=custody,
            )

        observed_names = _observed_namespace_names(custody, f"{label} resumable")
        observed_set = set(observed_names)
        allowed_prefixes = {
            frozenset(names[:position]) for position in range(len(names) + 1)
        }
        committed_set = frozenset((*names, receipt_name))
        _require(
            frozenset(observed_set) in allowed_prefixes
            or frozenset(observed_set) == committed_set,
            f"{label} namespace is not an exact resumable prefix; overwrite refused",
        )
        _require(
            receipt_name not in observed_set or observed_set == set(committed_set),
            f"{label} receipt exists before its complete causal payload set",
        )

        directory_mode = stat.S_IMODE(os.fstat(custody.directory_fd).st_mode)
        _require(
            directory_mode == 0o700
            or (receipt_name in observed_set and directory_mode == 0o500)
            or not physical_custody.permission_modes_enforced,
            f"{label} resumable directory mode drifted",
        )

        expected_payloads = dict(payloads)
        expected_payloads[receipt_name] = receipt_payload
        fingerprints: dict[str, tuple[int, ...]] = {}
        for name in [*names, receipt_name]:
            if name in observed_set:
                fingerprints[name] = _read_exact_resumable_payload(
                    root=root,
                    custody=custody,
                    physical_custody=physical_custody,
                    name=name,
                    payload=expected_payloads[name],
                    label=f"{label} resumed {name}",
                )

        for name, payload in payloads:
            _require(name != receipt_name, "receipt appeared before transaction tail")
            if name in observed_set:
                continue
            def fault_step(step: str, *, artifact_name: str = name) -> None:
                _after_artifact_commit(
                    after_artifact_commit,
                    f"{artifact_name}:{step}",
                    root=root,
                    custody=custody,
                )

            _descriptor, identity, disposition = (
                physical_custody.commit_or_adopt_exact_identity(
                    (custody.path / name).relative_to(root).as_posix(),
                    payload,
                    label=f"{label} {name}",
                    mode=0o400,
                    create_parents=False,
                    after_publish_step=(
                        fault_step if after_artifact_commit is not None else None
                    ),
                )
            )
            fingerprints[name] = _read_exact_resumable_payload(
                root=root,
                custody=custody,
                physical_custody=physical_custody,
                name=name,
                payload=payload,
                label=f"{label} committed {name}",
            )
            _require(
                fingerprints[name][:2] == identity,
                f"{label} committed {name} inode custody drifted",
            )
            if disposition == "published":
                _after_artifact_commit(
                    after_artifact_commit, name, root=root, custody=custody
                )
            _read_exact_resumable_payload(
                root=root,
                custody=custody,
                physical_custody=physical_custody,
                name=name,
                payload=payload,
                label=f"{label} post-boundary {name}",
                expected_fingerprint=fingerprints[name],
            )

        if receipt_name not in observed_set:
            before_tail = _namespace_snapshot(custody, names, f"{label} pre-tail")
            _require(
                all(
                    before_tail[name] == fingerprints[name]
                    for name in names
                ),
                f"{label} pre-tail inode custody drifted",
            )
            def receipt_fault_step(step: str) -> None:
                _after_artifact_commit(
                    after_artifact_commit,
                    f"{receipt_name}:{step}",
                    root=root,
                    custody=custody,
                )

            _descriptor, receipt_identity, receipt_disposition = (
                physical_custody.commit_or_adopt_exact_identity(
                    (custody.path / receipt_name).relative_to(root).as_posix(),
                    receipt_payload,
                    label=f"{label} {receipt_name}",
                    mode=0o400,
                    create_parents=False,
                    after_publish_step=(
                        receipt_fault_step
                        if after_artifact_commit is not None
                        else None
                    ),
                )
            )
            fingerprints[receipt_name] = _read_exact_resumable_payload(
                root=root,
                custody=custody,
                physical_custody=physical_custody,
                name=receipt_name,
                payload=receipt_payload,
                label=f"{label} committed {receipt_name}",
            )
            _require(
                fingerprints[receipt_name][:2] == receipt_identity,
                f"{label} committed receipt inode custody drifted",
            )
            if receipt_disposition == "published":
                _after_artifact_commit(
                    after_artifact_commit,
                    receipt_name,
                    root=root,
                    custody=custody,
                )

        all_names = [*names, receipt_name]
        committed = _namespace_snapshot(custody, all_names, f"{label} committed")
        _require(
            all(committed[name] == fingerprints[name] for name in all_names),
            f"{label} committed inode custody drifted",
        )
        custody.fsync()
        custody.fsync_parent()
        custody.chmod(0o500)
        _require_namespace_stable(
            custody, all_names, committed, f"{label} hardened",
        )
    except PublicationQ4AuthorityPlanPipelineV1Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} receipt-last commit failed: {error}"
        ) from error
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"{label} receipt-last commit failed"
        ) from error
    finally:
        physical_custody.close()
        custody.close()


def _runtime_filename(position: int, coordinate: Mapping[str, str]) -> str:
    return (
        f"runtime-authority.{position:03d}.{coordinate['system']}."
        f"{coordinate['codec']}.{coordinate['topology_kind']}."
        f"{coordinate['policy']}.v2.json"
    )


def _launcher_filename(system: str) -> str:
    return f"launcher-runtime-authority.{system}.v1.json"


def _open_cold_output_namespace(
    *, root: Path, custody: DirectoryFdCustodyV1,
    receipt_descriptor: Mapping[str, Any],
    members: Sequence[tuple[str, Mapping[str, Any]]], receipt_name: str,
    label: str,
) -> tuple[list[str], dict[str, tuple[int, ...]]]:
    checked_receipt = _descriptor(receipt_descriptor, f"{label} receipt")
    receipt_path = PurePosixPath(checked_receipt["path"])
    parent = receipt_path.parent
    _require(
        receipt_path.name == receipt_name and parent.as_posix() not in {"", "."},
        f"{label} receipt canonical output path drifted",
    )
    names: list[str] = []
    for name, raw_descriptor in members:
        item = _descriptor(raw_descriptor, f"{label} member {name}")
        _require(
            PurePosixPath(item["path"]) == parent / name,
            f"{label} member {name} escaped its receipt namespace",
        )
        names.append(name)
    names.append(receipt_name)
    expected_parent = root.joinpath(*parent.parts)
    _require(
        custody.path == expected_parent,
        f"{label} held namespace path drifted",
    )
    snapshot = _namespace_snapshot(custody, names, label)
    return names, snapshot


def _phase1_output_members(
    receipt: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    members: list[tuple[str, Mapping[str, Any]]] = [
        (INVOCATION_FILENAME,
         receipt["publication_launcher_invocation_v3"]["descriptor"]),
        (VALIDATOR_FILENAME, receipt["q4_validator_authority"]["descriptor"]),
        (RUNNER_FILENAME, receipt["runner_authority"]["descriptor"]),
    ]
    members.extend(
        (_launcher_filename(row["system"]), row["artifact"]["descriptor"])
        for row in receipt["launcher_runtime_authorities"]
    )
    members.extend(
        (_runtime_filename(position, row["coordinate"]),
         row["artifact"]["descriptor"])
        for position, row in enumerate(receipt["runtime_authorities"])
    )
    members.append(
        (RUNTIME_PLAN_FILENAME, receipt["runtime_materialization_plan"]["descriptor"])
    )
    return members


def _phase2_output_members(
    receipt: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (SOURCE_PLAN_FILENAME, receipt["source_registry_path_plan"]["descriptor"]),
    ]


def _build_phase1_material(
    *, root: Path, output: Path, source_spec_descriptor: Mapping[str, Any],
    source_spec: Mapping[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    invocation = validate_publication_launcher_invocation_v3(
        publication_launcher_invocation_v3_contract()
    )
    _require(
        invocation["invocation_sha256"]
        == source_spec["publication_launcher_invocation_v3_sha256"],
        "publication launcher invocation external authority drifted",
    )

    validator_arguments = copy.deepcopy(source_spec["q4_validator_authority_build"])
    validator = build_backend_runtime_validator_authority_v4(**validator_arguments)
    validator_assessment = assess_backend_runtime_validator_authority_v4(
        validator, project_root=root,
        expected_authority_sha256=validator_arguments["expected_authority_sha256"],
    )
    _require(validator_assessment.get("status") == "physically_valid",
             "Q4 validator authority physical build failed")

    runner_arguments = copy.deepcopy(source_spec["runner_authority_build"])
    expected_runner = runner_arguments.pop("expected_runner_authority_sha256")
    runner = build_backend_runtime_validation_runner_authority(
        project_root=root, **runner_arguments,
    )
    _require(runner["runner_authority_sha256"] == expected_runner,
             "Q4 runner external authority pin drifted")
    _require(
        runner["validation_protocol_identity_sha256"]
        == validator["validation_protocol_identity_sha256"]
        and runner["input_schema_identity_sha256"]
        == validator["validation_input_schema_identity_sha256"]
        and runner["output_schema_identity_sha256"]
        == validator["validation_output_schema_identity_sha256"],
        "Q4 validator/runner protocol trust domain drifted",
    )

    launcher_values: list[dict[str, Any]] = []
    for position, build in enumerate(source_spec["launcher_runtime_authority_builds"]):
        try:
            authority = build_backend_publication_launcher_runtime_authority(
                project_root=root,
                system=build["system"],
                runtime_closure_manifest_path=build["runtime_closure_manifest_path"],
                python_executable_path=build["python_executable_path"],
                publication_launcher_path=build["publication_launcher_path"],
                runtime_leaf_paths=build["runtime_leaf_paths"],
                expected_authority_sha256=build["expected_authority_sha256"],
                expected_system=build["system"],
                expected_publication_launcher_invocation_v3_sha256=(
                    invocation["invocation_sha256"]
                ),
                expected_closure_manifest_sha256=build[
                    "expected_closure_manifest_sha256"
                ],
                expected_runtime_closure_set_sha256=build[
                    "expected_runtime_closure_set_sha256"
                ],
            )
        except Exception as error:
            raise PublicationQ4AuthorityPlanPipelineV1Error(
                f"launcher authority build[{position}] rejected: {error}"
            ) from error
        launcher_values.append(authority)

    runtime_values: list[dict[str, Any]] = []
    for position, build in enumerate(source_spec["runtime_authority_builds"]):
        coordinate = build["coordinate"]
        inputs = copy.deepcopy(build["inputs"])
        try:
            authority = build_backend_publication_runtime_authority_v2(
                project_root=root, **coordinate, **inputs,
                upstream_identities=source_spec["accepted_upstream_identities"],
                expected_upstream_identities=source_spec[
                    "accepted_upstream_identities"
                ],
                expected_policy_outputs=_expected_policy_outputs(inputs),
            )
        except Exception as error:
            raise PublicationQ4AuthorityPlanPipelineV1Error(
                f"runtime authority build[{position}] rejected: {error}"
            ) from error
        _require(
            authority["authority_sha256"] == build["expected_authority_sha256"],
            f"runtime authority build[{position}] external pin drifted",
        )
        runtime_values.append(authority)

    artifacts: list[tuple[str, dict[str, Any], dict[str, Any], int, str, str]] = []
    invocation_descriptor, invocation_payload = _payload_descriptor(
        root, output, INVOCATION_FILENAME, invocation,
    )
    validator_descriptor, validator_payload = _payload_descriptor(
        root, output, VALIDATOR_FILENAME, validator,
    )
    runner_descriptor, runner_payload = _payload_descriptor(
        root, output, RUNNER_FILENAME, runner,
    )
    payloads: list[tuple[str, bytes]] = [
        (INVOCATION_FILENAME, invocation_payload),
        (VALIDATOR_FILENAME, validator_payload),
        (RUNNER_FILENAME, runner_payload),
    ]
    invocation_reference = _typed_ref(
        invocation_descriptor,
        schema_version=3,
        kind="vast_backend_publication_launcher_invocation_v3",
        identity=invocation["invocation_sha256"],
    )
    validator_reference = _typed_ref(
        validator_descriptor,
        schema_version=1,
        kind="vast_backend_runtime_validator_authority_q4",
        identity=validator["authority_sha256"],
    )
    runner_reference = _typed_ref(
        runner_descriptor,
        schema_version=1,
        kind="vast_backend_runtime_validation_runner_authority",
        identity=runner["runner_authority_sha256"],
    )
    launcher_records: list[dict[str, Any]] = []
    launcher_plan_records: list[dict[str, Any]] = []
    for system, authority in zip(SYSTEMS, launcher_values, strict=True):
        name = _launcher_filename(system)
        descriptor, payload = _payload_descriptor(root, output, name, authority)
        payloads.append((name, payload))
        reference = _typed_ref(
            descriptor, schema_version=1,
            kind="vast_backend_publication_launcher_runtime_authority",
            identity=authority["launcher_runtime_authority_sha256"],
        )
        launcher_records.append({"system": system, "artifact": reference})
        launcher_plan_records.append({
            "system": system,
            "artifact": copy.deepcopy(reference),
            "closure_manifest_sha256": authority[
                "runtime_closure_manifest_content"
            ]["closure_manifest_sha256"],
            "runtime_closure_set_sha256": authority[
                "runtime_closure_set_sha256"
            ],
        })
    runtime_records: list[dict[str, Any]] = []
    runtime_plan_records: list[dict[str, Any]] = []
    for position, (build, authority) in enumerate(zip(
        source_spec["runtime_authority_builds"], runtime_values, strict=True,
    )):
        coordinate = build["coordinate"]
        name = _runtime_filename(position, coordinate)
        descriptor, payload = _payload_descriptor(root, output, name, authority)
        payloads.append((name, payload))
        reference = _typed_ref(
            descriptor, schema_version=2,
            kind="vast_backend_publication_runtime_authority_v2",
            identity=authority["authority_sha256"],
        )
        runtime_records.append({"coordinate": copy.deepcopy(coordinate), "artifact": reference})
        wrapper_record = authority["system_specific_launcher_input"]
        wrapper = wrapper_record["content"]
        runtime_plan_records.append({
            "coordinate": copy.deepcopy(coordinate),
            "artifact": copy.deepcopy(reference),
            "upstream_identities": copy.deepcopy(
                authority["upstream_identities"]
            ),
            "policy_outputs": _expected_policy_outputs(build["inputs"]),
            "launcher_input_expectations": (
                publication_q4_runtime_launcher_input_expectations_v5(
                    wrapper,
                    expected_system=coordinate["system"],
                    expected_policy=coordinate["policy"],
                )
            ),
        })
    dataset_plan_records: list[dict[str, Any]] = []
    for source in source_spec["dataset_sources"]:
        codec = source["codec_variant"]
        authority = next(
            item
            for item in runtime_values
            if item["coordinate"]["codec"] == codec
        )
        files = authority["dataset"]["files"]
        by_path = {
            item["path"]: _descriptor(item, f"Q4 {codec} dataset source")
            for item in files
        }
        front = by_path.get(source["front_gate_path"])
        underbody = by_path.get(source["underbody_path"])
        _require(
            front is not None and underbody is not None,
            f"Q4 {codec} dataset plan sources are absent from runtime authority",
        )
        dataset_plan_records.append({
            "codec_variant": codec,
            "front_gate_source": _typed_ref(
                front,
                schema_version=1,
                kind="vast_frozen_publication_dataset_source_v1",
                identity=front["sha256"],
            ),
            "underbody_source": _typed_ref(
                underbody,
                schema_version=1,
                kind="vast_frozen_publication_dataset_source_v1",
                identity=underbody["sha256"],
            ),
        })
    runtime_plan = build_publication_q4_runtime_materialization_plan_v4(
        dataset_sources=dataset_plan_records,
        runtime_authorities=runtime_plan_records,
        launcher_runtime_authorities=launcher_plan_records,
        publication_launcher_invocation_v3=invocation_reference,
        q4_validator_authority=validator_reference,
        runner_authority=runner_reference,
        runner_invocation_identity_sha256=runner["invocation_contract"][
            "invocation_sha256"
        ],
    )
    plan_descriptor, plan_payload = _payload_descriptor(
        root, output, RUNTIME_PLAN_FILENAME, runtime_plan,
    )
    payloads.append((RUNTIME_PLAN_FILENAME, plan_payload))
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PHASE1_RECEIPT_KIND,
        "status": "materialized_non_authorizing_q4_authority_plan_phase1",
        "authorization_eligible": False,
        "execution_authorized": False,
        "source_spec": _typed_ref(
            source_spec_descriptor, schema_version=SCHEMA_VERSION,
            kind=SOURCE_SPEC_KIND, identity=source_spec["source_spec_sha256"],
        ),
        "source_spec_sha256": source_spec["source_spec_sha256"],
        "accepted_upstream_identities": copy.deepcopy(
            source_spec["accepted_upstream_identities"]
        ),
        "accepted_sources": copy.deepcopy(source_spec["accepted_sources"]),
        "planned_outputs": copy.deepcopy(source_spec["planned_outputs"]),
        "publication_launcher_invocation_v3": invocation_reference,
        "q4_validator_authority": validator_reference,
        "runner_authority": runner_reference,
        "launcher_runtime_authorities": launcher_records,
        "runtime_authorities": runtime_records,
        "runtime_materialization_plan": _typed_ref(
            plan_descriptor,
            schema_version=RUNTIME_MATERIALIZATION_SCHEMA_VERSION,
            kind=PLAN_KIND,
            identity=runtime_plan["plan_sha256"],
        ),
    }
    receipt = {**unsigned, "receipt_sha256": canonical_sha256(unsigned)}
    return receipt, payloads


def validate_publication_q4_authority_plan_phase1_receipt_v1(
    value: Any,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _PHASE1_FIELDS,
             "Q4 Phase1 receipt fields drifted")
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == PHASE1_RECEIPT_KIND
        and value.get("status")
        == "materialized_non_authorizing_q4_authority_plan_phase1"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 Phase1 receipt header/claims drifted",
    )
    source_spec = _validate_typed_ref(
        value.get("source_spec"), schema_version=1, kind=SOURCE_SPEC_KIND,
        label="Q4 Phase1 source-spec",
    )
    source_sha = _sha(value.get("source_spec_sha256"), "Q4 Phase1 source-spec")
    _require(source_spec["content_identity_sha256"] == source_sha,
             "Q4 Phase1 source-spec binding drifted")
    upstream = value.get("accepted_upstream_identities")
    _require(type(upstream) is dict and set(upstream) == set(UPSTREAM_IDENTITY_FIELDS),
             "Q4 Phase1 accepted upstream fields drifted")
    for key in upstream:
        _sha(upstream[key], f"Q4 Phase1 upstream {key}")
    accepted = _accepted_sources(value.get("accepted_sources"))
    planned = _planned_outputs(value.get("planned_outputs"))
    invocation = _validate_typed_ref(
        value.get("publication_launcher_invocation_v3"), schema_version=3,
        kind="vast_backend_publication_launcher_invocation_v3",
        label="Q4 Phase1 launcher invocation",
    )
    validator = _validate_typed_ref(
        value.get("q4_validator_authority"), schema_version=1,
        kind="vast_backend_runtime_validator_authority_q4",
        label="Q4 Phase1 validator authority",
    )
    runner = _validate_typed_ref(
        value.get("runner_authority"), schema_version=1,
        kind="vast_backend_runtime_validation_runner_authority",
        label="Q4 Phase1 runner authority",
    )
    raw_launchers = value.get("launcher_runtime_authorities")
    _require(type(raw_launchers) is list and len(raw_launchers) == len(SYSTEMS),
             "Q4 Phase1 launcher authority coverage drifted")
    launchers: list[dict[str, Any]] = []
    for position, (record, system) in enumerate(zip(raw_launchers, SYSTEMS, strict=True)):
        _require(type(record) is dict and set(record) == _LAUNCHER_RECORD_FIELDS
                 and record.get("system") == system,
                 f"Q4 Phase1 launcher record[{position}] drifted")
        launchers.append({
            "system": system,
            "artifact": _validate_typed_ref(
                record.get("artifact"), schema_version=1,
                kind="vast_backend_publication_launcher_runtime_authority",
                label=f"Q4 Phase1 launcher[{position}]",
            ),
        })
    expected_coordinates = _coordinates()
    raw_runtime = value.get("runtime_authorities")
    _require(type(raw_runtime) is list and len(raw_runtime) == len(expected_coordinates),
             "Q4 Phase1 runtime authority coverage drifted")
    runtime: list[dict[str, Any]] = []
    for position, (record, expected) in enumerate(zip(raw_runtime, expected_coordinates, strict=True)):
        _require(type(record) is dict and set(record) == _RUNTIME_RECORD_FIELDS,
                 f"Q4 Phase1 runtime record[{position}] fields drifted")
        coordinate = _coordinate(record.get("coordinate"))
        _require(coordinate == expected, f"Q4 Phase1 runtime record[{position}] order drifted")
        runtime.append({
            "coordinate": coordinate,
            "artifact": _validate_typed_ref(
                record.get("artifact"), schema_version=2,
                kind="vast_backend_publication_runtime_authority_v2",
                label=f"Q4 Phase1 runtime[{position}]",
            ),
        })
    plan = _validate_typed_ref(
        value.get("runtime_materialization_plan"),
        schema_version=RUNTIME_MATERIALIZATION_SCHEMA_VERSION,
        kind=PLAN_KIND, label="Q4 Phase1 runtime materialization plan",
    )
    paths = [
        source_spec["descriptor"]["path"], invocation["descriptor"]["path"],
        validator["descriptor"]["path"], runner["descriptor"]["path"],
        plan["descriptor"]["path"],
        *(row["artifact"]["descriptor"]["path"] for row in launchers),
        *(row["artifact"]["descriptor"]["path"] for row in runtime),
    ]
    _require(len(paths) == len({path.casefold() for path in paths}),
             "Q4 Phase1 receipt artifact paths alias")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "receipt_sha256"}
    identity = _sha(value.get("receipt_sha256"), "Q4 Phase1 receipt")
    _require(identity == canonical_sha256(unsigned), "Q4 Phase1 receipt self-hash drifted")
    return {
        **unsigned, "source_spec": source_spec,
        "accepted_sources": accepted, "planned_outputs": planned,
        "publication_launcher_invocation_v3": invocation,
        "q4_validator_authority": validator, "runner_authority": runner,
        "launcher_runtime_authorities": launchers,
        "runtime_authorities": runtime,
        "runtime_materialization_plan": plan, "receipt_sha256": identity,
    }


def _cold_check_phase1(
    *, root: Path, receipt: Mapping[str, Any], source_spec: Mapping[str, Any],
    custody: DirectoryFdCustodyV1,
    namespace_snapshot: Mapping[str, tuple[int, ...]],
) -> None:
    def load_local(value: Any, label: str) -> dict[str, Any]:
        descriptor = _descriptor(value, label)
        name = PurePosixPath(descriptor["path"]).name
        _require(name in namespace_snapshot, f"{label} is outside the held namespace")
        return _load_by_descriptor_from_custody(
            root,
            custody,
            descriptor,
            namespace_snapshot[name],
            label,
        )

    invocation = validate_publication_launcher_invocation_v3(
        load_local(
            receipt["publication_launcher_invocation_v3"]["descriptor"],
            "Q4 Phase1 launcher invocation",
        )
    )
    _require(
        invocation["invocation_sha256"]
        == receipt["publication_launcher_invocation_v3"]["content_identity_sha256"]
        == source_spec["publication_launcher_invocation_v3_sha256"],
        "Q4 Phase1 launcher invocation cold binding drifted",
    )
    validator_build = source_spec["q4_validator_authority_build"]
    validator = validate_backend_runtime_validator_authority_v4(
        load_local(
            receipt["q4_validator_authority"]["descriptor"],
            "Q4 Phase1 validator authority",
        ),
        expected_authority_sha256=validator_build["expected_authority_sha256"],
    )
    validator_assessment = assess_backend_runtime_validator_authority_v4(
        validator, project_root=root,
        expected_authority_sha256=validator_build["expected_authority_sha256"],
    )
    _require(validator_assessment.get("status") == "physically_valid",
             "Q4 Phase1 validator cold physical assessment failed")
    runner_build = source_spec["runner_authority_build"]
    runner = validate_backend_runtime_validation_runner_authority(
        load_local(
            receipt["runner_authority"]["descriptor"],
            "Q4 Phase1 runner authority",
        ),
        expected_runner_authority_sha256=runner_build[
            "expected_runner_authority_sha256"
        ],
    )
    runner_assessment = assess_backend_runtime_validation_runner_authority(
        runner, project_root=root,
        expected_runner_authority_sha256=runner_build[
            "expected_runner_authority_sha256"
        ],
    )
    _require(runner_assessment.get("status") == "physically_valid",
             "Q4 Phase1 runner cold physical assessment failed")
    plan = validate_publication_q4_runtime_materialization_plan_v4(
        load_local(
            receipt["runtime_materialization_plan"]["descriptor"],
            "Q4 Phase1 runtime materialization plan",
        )
    )
    _require(
        plan["plan_sha256"]
        == receipt["runtime_materialization_plan"]["content_identity_sha256"],
        "Q4 Phase1 runtime plan semantic drifted",
    )
    _require(
        plan["publication_launcher_invocation_v3"]
        == receipt["publication_launcher_invocation_v3"]
        and plan["q4_validator_authority"]
        == receipt["q4_validator_authority"]
        and plan["runner_authority"] == receipt["runner_authority"]
        and plan["runner_invocation_identity_sha256"]
        == runner["invocation_contract"]["invocation_sha256"],
        "Q4 Phase1 runtime plan/global authority snapshot drifted",
    )
    for position, (record, build, plan_row) in enumerate(zip(
        receipt["launcher_runtime_authorities"],
        source_spec["launcher_runtime_authority_builds"],
        plan["launcher_runtime_authorities"],
        strict=True,
    )):
        authority = validate_backend_publication_launcher_runtime_authority(
            load_local(
                record["artifact"]["descriptor"],
                f"Q4 Phase1 launcher authority[{position}]",
            ),
            expected_authority_sha256=build["expected_authority_sha256"],
            expected_system=build["system"],
            expected_publication_launcher_invocation_v3_sha256=invocation[
                "invocation_sha256"
            ],
            expected_closure_manifest_sha256=build[
                "expected_closure_manifest_sha256"
            ],
            expected_runtime_closure_set_sha256=build[
                "expected_runtime_closure_set_sha256"
            ],
        )
        assessment = assess_backend_publication_launcher_runtime_authority(
            authority, project_root=root,
            expected_authority_sha256=build["expected_authority_sha256"],
            expected_system=build["system"],
            expected_publication_launcher_invocation_v3_sha256=invocation[
                "invocation_sha256"
            ],
            expected_closure_manifest_sha256=build[
                "expected_closure_manifest_sha256"
            ],
            expected_runtime_closure_set_sha256=build[
                "expected_runtime_closure_set_sha256"
            ],
        )
        _require(assessment.get("status") == "physically_valid",
                 f"Q4 Phase1 launcher authority[{position}] cold assessment failed")
        _require(authority["launcher_runtime_authority_sha256"]
                  == record["artifact"]["content_identity_sha256"],
                  f"Q4 Phase1 launcher authority[{position}] semantic drifted")
        _require(
            plan_row["system"] == record["system"] == build["system"]
            and plan_row["artifact"] == record["artifact"]
            and plan_row["closure_manifest_sha256"]
            == authority["runtime_closure_manifest_content"][
                "closure_manifest_sha256"
            ]
            and plan_row["runtime_closure_set_sha256"]
            == authority["runtime_closure_set_sha256"],
            f"Q4 Phase1 launcher authority[{position}] plan snapshot drifted",
        )
    cold_runtime_authorities: list[dict[str, Any]] = []
    for position, (record, build, plan_row) in enumerate(zip(
        receipt["runtime_authorities"],
        source_spec["runtime_authority_builds"],
        plan["runtime_authorities"],
        strict=True,
    )):
        inputs = build["inputs"]
        authority = validate_backend_publication_runtime_authority_v2(
            load_local(
                record["artifact"]["descriptor"],
                f"Q4 Phase1 runtime authority[{position}]",
            ),
            expected_system=build["coordinate"]["system"],
            expected_policy=build["coordinate"]["policy"],
            expected_topology_kind=build["coordinate"]["topology_kind"],
            expected_codec=build["coordinate"]["codec"],
            expected_upstream_identities=source_spec[
                "accepted_upstream_identities"
            ],
            expected_policy_outputs=_expected_policy_outputs(inputs),
        )
        assessment = assess_backend_publication_runtime_authority_v2(
            authority, project_root=root,
            expected_system=build["coordinate"]["system"],
            expected_policy=build["coordinate"]["policy"],
            expected_topology_kind=build["coordinate"]["topology_kind"],
            expected_codec=build["coordinate"]["codec"],
            expected_upstream_identities=source_spec[
                "accepted_upstream_identities"
            ],
            expected_policy_outputs=_expected_policy_outputs(inputs),
        )
        _require(assessment.get("status") == "physically_valid",
                 f"Q4 Phase1 runtime authority[{position}] cold assessment failed")
        _require(authority["authority_sha256"]
                  == record["artifact"]["content_identity_sha256"]
                  == build["expected_authority_sha256"],
                  f"Q4 Phase1 runtime authority[{position}] semantic drifted")
        wrapper = authority["system_specific_launcher_input"]["content"]
        _require(
            plan_row["coordinate"] == record["coordinate"] == build["coordinate"]
            and plan_row["artifact"] == record["artifact"]
            and plan_row["upstream_identities"]
            == authority["upstream_identities"]
            == source_spec["accepted_upstream_identities"]
            and plan_row["policy_outputs"]
            == _expected_policy_outputs(inputs)
            and plan_row["launcher_input_expectations"]
            == publication_q4_runtime_launcher_input_expectations_v5(
                wrapper,
                expected_system=build["coordinate"]["system"],
                expected_policy=build["coordinate"]["policy"],
            ),
            f"Q4 Phase1 runtime authority[{position}] plan snapshot drifted",
        )
        cold_runtime_authorities.append(authority)
    for plan_dataset, source in zip(
        plan["dataset_sources"], source_spec["dataset_sources"], strict=True,
    ):
        codec = source["codec_variant"]
        authority = next(
            item
            for item in cold_runtime_authorities
            if item["coordinate"]["codec"] == codec
        )
        by_path = {
            item["path"]: _descriptor(item, f"Q4 {codec} dataset source")
            for item in authority["dataset"]["files"]
        }
        _require(
            plan_dataset["codec_variant"] == codec
            and plan_dataset["front_gate_source"]["descriptor"]
            == by_path.get(source["front_gate_path"])
            and plan_dataset["underbody_source"]["descriptor"]
            == by_path.get(source["underbody_path"])
            and plan_dataset["front_gate_source"]["content_identity_sha256"]
            == plan_dataset["front_gate_source"]["descriptor"]["sha256"]
            and plan_dataset["underbody_source"]["content_identity_sha256"]
            == plan_dataset["underbody_source"]["descriptor"]["sha256"],
            f"Q4 Phase1 {codec} dataset raw/semantic plan snapshot drifted",
        )


def load_publication_q4_authority_plan_phase1_receipt_v1(
    *, project_root: Path | str, receipt_path: Path | str,
    expected_receipt_file_sha256: str, expected_receipt_sha256: str,
) -> dict[str, Any]:
    root = _root(project_root)
    receipt_file = _under_root(root, receipt_path, label="Q4 Phase1 receipt")
    _require(
        receipt_file.name == PHASE1_RECEIPT_FILENAME
        and receipt_file.parent != root,
        "Q4 Phase1 receipt canonical output path drifted",
    )
    custody = _open_directory_custody(
        root, receipt_file.parent, "Q4 Phase1 output namespace",
    )
    try:
        descriptor, raw, receipt_fingerprint = _load_json_from_custody(
            root, custody, receipt_file, "Q4 Phase1 receipt",
        )
        _require(
            descriptor["sha256"]
            == _sha(
                expected_receipt_file_sha256,
                "expected Q4 Phase1 receipt file",
            ),
            "Q4 Phase1 receipt file pin drifted",
        )
        receipt = validate_publication_q4_authority_plan_phase1_receipt_v1(raw)
        _require(
            receipt["receipt_sha256"]
            == _sha(expected_receipt_sha256, "expected Q4 Phase1 receipt semantic"),
            "Q4 Phase1 receipt semantic pin drifted",
        )
        names, snapshot = _open_cold_output_namespace(
            root=root,
            custody=custody,
            receipt_descriptor=descriptor,
            members=_phase1_output_members(receipt),
            receipt_name=PHASE1_RECEIPT_FILENAME,
            label="Q4 Phase1 output",
        )
        _require(
            snapshot[PHASE1_RECEIPT_FILENAME] == receipt_fingerprint,
            "Q4 Phase1 receipt inode drifted before namespace validation",
        )
        observed_descriptor, observed_raw, observed_fingerprint = (
            _load_json_from_custody(
                root,
                custody,
                descriptor["path"],
                "Q4 Phase1 receipt cold reread",
            )
        )
        _require(
            observed_descriptor == descriptor
            and observed_raw == raw
            and observed_fingerprint == receipt_fingerprint,
            "Q4 Phase1 receipt changed before cold closure validation",
        )
        source_document = _load_by_descriptor(
            root, receipt["source_spec"]["descriptor"], "Q4 Phase1 source-spec",
        )
        source_spec = validate_publication_q4_authority_source_spec_v1(source_document)
        _require(
            source_spec["source_spec_sha256"]
            == receipt["source_spec"]["content_identity_sha256"]
            == receipt["source_spec_sha256"]
            and source_spec["accepted_upstream_identities"]
            == receipt["accepted_upstream_identities"]
            and source_spec["accepted_sources"] == receipt["accepted_sources"]
            and source_spec["planned_outputs"] == receipt["planned_outputs"],
            "Q4 Phase1 source-spec/receipt binding drifted",
        )
        _cold_check_phase1(
            root=root,
            receipt=receipt,
            source_spec=source_spec,
            custody=custody,
            namespace_snapshot=snapshot,
        )
        _require_namespace_stable(
            custody, names, snapshot, "Q4 Phase1 output cold closure",
        )
        return receipt
    finally:
        custody.close()


def materialize_publication_q4_authority_plan_phase1_v1(
    *, project_root: Path | str, source_spec_path: Path | str,
    expected_source_spec_file_sha256: str,
    expected_source_spec_sha256: str, output_dir: Path | str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    source_descriptor, source_spec = load_publication_q4_authority_source_spec_v1(
        project_root=root, source_spec_path=source_spec_path,
        expected_source_spec_file_sha256=expected_source_spec_file_sha256,
        expected_source_spec_sha256=expected_source_spec_sha256,
    )
    output, _relative_output = _output_relative(root, output_dir, "Q4 Phase1 output")
    receipt, payloads = _build_phase1_material(
        root=root, output=output, source_spec_descriptor=source_descriptor,
        source_spec=source_spec,
    )
    receipt_payload = canonical_bytes(receipt, newline=True)
    _write_payloads_receipt_last(
        root=root, output_dir=output, payloads=payloads,
        receipt_name=PHASE1_RECEIPT_FILENAME, receipt_payload=receipt_payload,
        label="Q4 Phase1 output",
        after_artifact_commit=after_artifact_commit,
    )
    receipt_path = output / PHASE1_RECEIPT_FILENAME
    return load_publication_q4_authority_plan_phase1_receipt_v1(
        project_root=root, receipt_path=receipt_path,
        expected_receipt_file_sha256=hashlib.sha256(receipt_payload).hexdigest(),
        expected_receipt_sha256=receipt["receipt_sha256"],
    )


def _validate_runtime_materialization_result(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _RUNTIME_RESULT_FIELDS,
             "Q4 runtime materialization result fields drifted")
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == RUNTIME_MATERIALIZATION_SCHEMA_VERSION
        and value.get("artifact_kind") == RUNTIME_RESULT_KIND
        and value.get("status")
        == "physically_materialized_non_authorizing_runtime_registry"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False
        and type(value.get("dataset_binding_count")) is int
        and value.get("dataset_binding_count") == len(CODECS)
        and type(value.get("runtime_authority_count")) is int
        and value.get("runtime_authority_count") == len(_coordinates()),
        "Q4 runtime materialization result header/counts drifted",
    )
    _sha(value.get("plan_sha256"), "Q4 runtime result plan")
    _descriptor(value.get("runtime_candidate_registry"), "Q4 runtime result registry")
    _sha(value.get("runtime_candidate_registry_sha256"), "Q4 runtime result registry semantic")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "result_sha256"}
    identity = _sha(value.get("result_sha256"), "Q4 runtime materialization result")
    _require(identity == canonical_sha256(unsigned),
             "Q4 runtime materialization result self-hash drifted")
    return copy.deepcopy(value)


def _phase1_descriptor(root: Path, path: Path | str) -> dict[str, Any]:
    descriptor, _payload = _read_bytes_descriptor(root, path, "Q4 Phase1 receipt")
    return descriptor


def validate_publication_q4_source_plan_phase2_receipt_v1(
    value: Any,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _PHASE2_FIELDS,
             "Q4 Phase2 receipt fields drifted")
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == PHASE2_RECEIPT_KIND
        and value.get("status")
        == "finalized_non_authorizing_q4_source_path_plan_phase2"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 Phase2 receipt header/claims drifted",
    )
    phase1 = _validate_typed_ref(
        value.get("phase1_receipt"), schema_version=1,
        kind=PHASE1_RECEIPT_KIND, label="Q4 Phase2 Phase1 receipt",
    )
    _require(
        phase1["content_identity_sha256"]
        == _sha(value.get("phase1_receipt_sha256"), "Q4 Phase2 Phase1 receipt"),
        "Q4 Phase2 Phase1 receipt binding drifted",
    )
    source = _validate_typed_ref(
        value.get("source_spec"), schema_version=1, kind=SOURCE_SPEC_KIND,
        label="Q4 Phase2 source-spec",
    )
    _require(
        source["content_identity_sha256"]
        == _sha(value.get("source_spec_sha256"), "Q4 Phase2 source-spec"),
        "Q4 Phase2 source-spec binding drifted",
    )
    runtime_result = _validate_typed_ref(
        value.get("runtime_materialization_result"),
        schema_version=RUNTIME_MATERIALIZATION_SCHEMA_VERSION,
        kind=RUNTIME_RESULT_KIND, label="Q4 Phase2 runtime result",
    )
    runtime_registry = _validate_typed_ref(
        value.get("runtime_candidate_registry"), schema_version=4,
        kind=RUNTIME_CANDIDATE_REGISTRY_KIND,
        label="Q4 Phase2 runtime registry",
    )
    source_plan = _validate_typed_ref(
        value.get("source_registry_path_plan"), schema_version=1,
        kind=PATH_PLAN_KIND, label="Q4 Phase2 source path-plan",
    )
    planned = _planned_outputs(value.get("planned_outputs"))
    paths = [
        phase1["descriptor"]["path"], source["descriptor"]["path"],
        runtime_result["descriptor"]["path"],
        runtime_registry["descriptor"]["path"],
        source_plan["descriptor"]["path"],
    ]
    _require(len(paths) == len({path.casefold() for path in paths}),
             "Q4 Phase2 receipt artifact paths alias")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "receipt_sha256"}
    identity = _sha(value.get("receipt_sha256"), "Q4 Phase2 receipt")
    _require(identity == canonical_sha256(unsigned), "Q4 Phase2 receipt self-hash drifted")
    return {
        **unsigned, "phase1_receipt": phase1, "source_spec": source,
        "runtime_materialization_result": runtime_result,
        "runtime_candidate_registry": runtime_registry,
        "source_registry_path_plan": source_plan,
        "planned_outputs": planned, "receipt_sha256": identity,
    }


def _load_runtime_result_and_registry(
    *, root: Path, result_path: Path | str, expected_file_sha256: str,
    expected_result_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result_descriptor, raw = _load_json(
        root, result_path, "Q4 runtime materialization result",
    )
    _require(
        result_descriptor["sha256"]
        == _sha(expected_file_sha256, "expected Q4 runtime result file"),
        "Q4 runtime materialization result file pin drifted",
    )
    result = _validate_runtime_materialization_result(raw)
    _require(
        result["result_sha256"]
        == _sha(expected_result_sha256, "expected Q4 runtime result semantic"),
        "Q4 runtime materialization result semantic pin drifted",
    )
    registry_document = _load_by_descriptor(
        root, result["runtime_candidate_registry"], "Q4 runtime candidate registry",
    )
    try:
        registry = validate_publication_q4_runtime_candidate_registry_v4(
            registry_document
        )
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"Q4 runtime candidate registry rejected: {error}"
        ) from error
    _require(
        registry["registry_sha256"]
        == result["runtime_candidate_registry_sha256"],
        "Q4 runtime candidate registry/result semantic binding drifted",
    )
    return result_descriptor, result, registry


def _crossbind_runtime_registry_to_phase1(
    *,
    root: Path,
    phase1: Mapping[str, Any],
    runtime_registry: Mapping[str, Any],
) -> dict[str, Any]:
    plan_document = _load_by_descriptor(
        root,
        phase1["runtime_materialization_plan"]["descriptor"],
        "Q4 Phase1 runtime materialization plan",
    )
    plan = validate_publication_q4_runtime_materialization_plan_v4(
        plan_document
    )
    _require(
        plan["plan_sha256"]
        == phase1["runtime_materialization_plan"][
            "content_identity_sha256"
        ],
        "Q4 Phase2 Phase1 runtime plan semantic binding drifted",
    )
    try:
        checked = (
            validate_publication_q4_runtime_candidate_registry_against_plan_v5(
                runtime_registry,
                plan=plan,
            )
        )
    except Exception as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            f"Q4 Phase2 runtime registry/Phase1 snapshot crossbinding failed: {error}"
        ) from error
    _require(
        checked == runtime_registry,
        "Q4 Phase2 registry normalization drifted from its Phase1 snapshot",
    )
    return plan


def finalize_publication_q4_source_plan_phase2_v1(
    *, project_root: Path | str, phase1_receipt_path: Path | str,
    expected_phase1_receipt_file_sha256: str,
    expected_phase1_receipt_sha256: str,
    runtime_materialization_result_path: Path | str,
    expected_runtime_materialization_result_file_sha256: str,
    expected_runtime_materialization_result_sha256: str,
    output_dir: Path | str,
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    phase1 = load_publication_q4_authority_plan_phase1_receipt_v1(
        project_root=root, receipt_path=phase1_receipt_path,
        expected_receipt_file_sha256=expected_phase1_receipt_file_sha256,
        expected_receipt_sha256=expected_phase1_receipt_sha256,
    )
    phase1_descriptor = _phase1_descriptor(root, phase1_receipt_path)
    result_descriptor, runtime_result, runtime_candidate = (
        _load_runtime_result_and_registry(
            root=root, result_path=runtime_materialization_result_path,
            expected_file_sha256=(
                expected_runtime_materialization_result_file_sha256
            ),
            expected_result_sha256=(
                expected_runtime_materialization_result_sha256
            ),
        )
    )
    planned = phase1["planned_outputs"]
    _require(
        result_descriptor["path"]
        == planned["runtime_materialization_result_path"],
        "Q4 Phase2 cross-run planned runtime result path drifted",
    )
    _require(
        runtime_result["runtime_candidate_registry"]["path"]
        == planned["runtime_candidate_registry_path"],
        "Q4 Phase2 cross-run planned runtime registry path drifted",
    )
    _require(
        runtime_result["plan_sha256"]
        == phase1["runtime_materialization_plan"]["content_identity_sha256"],
        "Q4 Phase2 runtime plan binding drifted",
    )
    _crossbind_runtime_registry_to_phase1(
        root=root,
        phase1=phase1,
        runtime_registry=runtime_candidate,
    )
    registry_descriptor = _descriptor(
        runtime_result["runtime_candidate_registry"],
        "Q4 Phase2 runtime candidate registry",
    )
    accepted = phase1["accepted_sources"]
    source_plan = build_backend_q4_two_phase_source_registry_path_plan_v1(
        model_parity_acceptance_receipt_path=accepted[
            "model_parity_acceptance_receipt_path"
        ],
        policy_qualification_receipt_path=accepted[
            "policy_qualification_receipt_path"
        ],
        policy_capability_manifest_path=accepted[
            "policy_capability_manifest_path"
        ],
        policy_calibration_mapping_path=accepted[
            "policy_calibration_mapping_path"
        ],
        resource_qualification_receipt_path=accepted[
            "resource_qualification_receipt_path"
        ],
        resource_capability_manifest_path=accepted[
            "resource_capability_manifest_path"
        ],
        runtime_candidate_registry_path=registry_descriptor["path"],
        analytics_service_authority_path=accepted[
            "analytics_service_authority_path"
        ],
        guardian_preprocessing_contract_path=accepted[
            "guardian_preprocessing_contract_path"
        ],
        guardian_preprocessing_receipt_path=accepted[
            "guardian_preprocessing_receipt_path"
        ],
        expected_analytics_service_identity_sha256=accepted[
            "expected_analytics_service_identity_sha256"
        ],
    )
    output, _relative_output = _output_relative(root, output_dir, "Q4 Phase2 output")
    plan_descriptor, plan_payload = _payload_descriptor(
        root, output, SOURCE_PLAN_FILENAME, source_plan,
    )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PHASE2_RECEIPT_KIND,
        "status": "finalized_non_authorizing_q4_source_path_plan_phase2",
        "authorization_eligible": False,
        "execution_authorized": False,
        "phase1_receipt": _typed_ref(
            phase1_descriptor, schema_version=1, kind=PHASE1_RECEIPT_KIND,
            identity=phase1["receipt_sha256"],
        ),
        "phase1_receipt_sha256": phase1["receipt_sha256"],
        "source_spec": copy.deepcopy(phase1["source_spec"]),
        "source_spec_sha256": phase1["source_spec_sha256"],
        "runtime_materialization_result": _typed_ref(
            result_descriptor,
            schema_version=RUNTIME_MATERIALIZATION_SCHEMA_VERSION,
            kind=RUNTIME_RESULT_KIND,
            identity=runtime_result["result_sha256"],
        ),
        "runtime_candidate_registry": _typed_ref(
            registry_descriptor, schema_version=4,
            kind=RUNTIME_CANDIDATE_REGISTRY_KIND,
            identity=runtime_candidate["registry_sha256"],
        ),
        "source_registry_path_plan": _typed_ref(
            plan_descriptor, schema_version=1, kind=PATH_PLAN_KIND,
            identity=source_plan["plan_sha256"],
        ),
        "planned_outputs": copy.deepcopy(planned),
    }
    receipt = {**unsigned, "receipt_sha256": canonical_sha256(unsigned)}
    receipt_payload = canonical_bytes(receipt, newline=True)
    _write_payloads_receipt_last(
        root=root, output_dir=output,
        payloads=[(SOURCE_PLAN_FILENAME, plan_payload)],
        receipt_name=PHASE2_RECEIPT_FILENAME, receipt_payload=receipt_payload,
        label="Q4 Phase2 output",
        after_artifact_commit=after_artifact_commit,
    )
    return load_publication_q4_source_plan_phase2_receipt_v1(
        project_root=root, receipt_path=output / PHASE2_RECEIPT_FILENAME,
        expected_receipt_file_sha256=hashlib.sha256(receipt_payload).hexdigest(),
        expected_receipt_sha256=receipt["receipt_sha256"],
    )


def load_publication_q4_source_plan_phase2_receipt_v1(
    *, project_root: Path | str, receipt_path: Path | str,
    expected_receipt_file_sha256: str, expected_receipt_sha256: str,
) -> dict[str, Any]:
    root = _root(project_root)
    receipt_file = _under_root(root, receipt_path, label="Q4 Phase2 receipt")
    _require(
        receipt_file.name == PHASE2_RECEIPT_FILENAME
        and receipt_file.parent != root,
        "Q4 Phase2 receipt canonical output path drifted",
    )
    custody = _open_directory_custody(
        root, receipt_file.parent, "Q4 Phase2 output namespace",
    )
    try:
        descriptor, raw, receipt_fingerprint = _load_json_from_custody(
            root, custody, receipt_file, "Q4 Phase2 receipt",
        )
        _require(
            descriptor["sha256"]
            == _sha(
                expected_receipt_file_sha256,
                "expected Q4 Phase2 receipt file",
            ),
            "Q4 Phase2 receipt file pin drifted",
        )
        receipt = validate_publication_q4_source_plan_phase2_receipt_v1(raw)
        _require(
            receipt["receipt_sha256"]
            == _sha(expected_receipt_sha256, "expected Q4 Phase2 receipt semantic"),
            "Q4 Phase2 receipt semantic pin drifted",
        )
        names, snapshot = _open_cold_output_namespace(
            root=root,
            custody=custody,
            receipt_descriptor=descriptor,
            members=_phase2_output_members(receipt),
            receipt_name=PHASE2_RECEIPT_FILENAME,
            label="Q4 Phase2 output",
        )
        _require(
            snapshot[PHASE2_RECEIPT_FILENAME] == receipt_fingerprint,
            "Q4 Phase2 receipt inode drifted before namespace validation",
        )
        observed_descriptor, observed_raw, observed_fingerprint = (
            _load_json_from_custody(
                root,
                custody,
                descriptor["path"],
                "Q4 Phase2 receipt cold reread",
            )
        )
        _require(
            observed_descriptor == descriptor
            and observed_raw == raw
            and observed_fingerprint == receipt_fingerprint,
            "Q4 Phase2 receipt changed before cold closure validation",
        )
        phase1 = load_publication_q4_authority_plan_phase1_receipt_v1(
            project_root=root,
            receipt_path=receipt["phase1_receipt"]["descriptor"]["path"],
            expected_receipt_file_sha256=receipt["phase1_receipt"]["descriptor"][
                "sha256"
            ],
            expected_receipt_sha256=receipt["phase1_receipt_sha256"],
        )
        _require(
            phase1["source_spec"] == receipt["source_spec"]
            and phase1["source_spec_sha256"] == receipt["source_spec_sha256"]
            and phase1["planned_outputs"] == receipt["planned_outputs"],
            "Q4 Phase2 Phase1/source-spec binding drifted",
        )
        result_descriptor, runtime_result, runtime_registry = (
            _load_runtime_result_and_registry(
                root=root,
                result_path=receipt["runtime_materialization_result"]["descriptor"][
                    "path"
                ],
                expected_file_sha256=receipt[
                    "runtime_materialization_result"
                ]["descriptor"]["sha256"],
                expected_result_sha256=receipt[
                    "runtime_materialization_result"
                ]["content_identity_sha256"],
            )
        )
        _require(
            result_descriptor == receipt["runtime_materialization_result"]["descriptor"]
            and runtime_result["runtime_candidate_registry"]
            == receipt["runtime_candidate_registry"]["descriptor"]
            and runtime_registry["registry_sha256"]
            == receipt["runtime_candidate_registry"]["content_identity_sha256"]
            and runtime_result["plan_sha256"]
            == phase1["runtime_materialization_plan"]["content_identity_sha256"]
            and result_descriptor["path"]
            == receipt["planned_outputs"]["runtime_materialization_result_path"]
            and runtime_result["runtime_candidate_registry"]["path"]
            == receipt["planned_outputs"]["runtime_candidate_registry_path"],
            "Q4 Phase2 runtime result/registry cross-run binding drifted",
        )
        _crossbind_runtime_registry_to_phase1(
            root=root,
            phase1=phase1,
            runtime_registry=runtime_registry,
        )
        plan_descriptor = receipt["source_registry_path_plan"]["descriptor"]
        plan_name = PurePosixPath(plan_descriptor["path"]).name
        _require(
            plan_name in snapshot,
            "Q4 Phase2 source registry path-plan escaped the held namespace",
        )
        plan_document = _load_by_descriptor_from_custody(
            root,
            custody,
            plan_descriptor,
            snapshot[plan_name],
            "Q4 Phase2 source registry path-plan",
        )
        plan = validate_backend_q4_two_phase_source_registry_path_plan_v1(plan_document)
        _require(
            plan["plan_sha256"]
            == receipt["source_registry_path_plan"]["content_identity_sha256"]
            and plan["runtime_candidate_registry_path"]
            == runtime_result["runtime_candidate_registry"]["path"],
            "Q4 Phase2 source path-plan binding drifted",
        )
        for key, expected in phase1["accepted_sources"].items():
            _require(plan.get(key) == expected,
                     f"Q4 Phase2 source path-plan accepted source {key} drifted")
        _require_namespace_stable(
            custody, names, snapshot, "Q4 Phase2 output cold closure",
        )
        return receipt
    finally:
        custody.close()


_SOURCE_SPEC_CLI_OPTIONS = (
    "--project-root", "--source-material", "--source-material-file-sha256",
    "--source-material-sha256", "--output",
)
_PHASE1_CLI_OPTIONS = (
    "--project-root", "--source-spec", "--source-spec-file-sha256",
    "--source-spec-sha256", "--output-dir",
)
_PHASE2_CLI_OPTIONS = (
    "--project-root", "--phase1-receipt", "--phase1-receipt-file-sha256",
    "--phase1-receipt-sha256", "--runtime-materialization-result",
    "--runtime-materialization-result-file-sha256",
    "--runtime-materialization-result-sha256", "--output-dir",
)


def _parse_exact_options(
    argv: Sequence[str], expected: Sequence[str], label: str,
) -> dict[str, str]:
    _require(type(argv) in {list, tuple} and len(argv) == len(expected) * 2,
             f"{label} CLI argv arity drifted")
    result: dict[str, str] = {}
    for position, option in enumerate(expected):
        observed = argv[position * 2]
        item = argv[position * 2 + 1]
        _require(observed == option, f"{label} CLI option[{position}] drifted")
        _require(type(item) is str and bool(item), f"{label} CLI value[{position}] is empty")
        result[option] = item
    return result


def _result_summary(
    *, root: Path, receipt_path: Path, receipt: Mapping[str, Any], phase: int,
) -> dict[str, Any]:
    descriptor, _payload = _read_bytes_descriptor(
        root, receipt_path, f"Q4 Phase{phase} receipt",
    )
    if phase == 1:
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": PHASE1_RESULT_KIND,
            "status": "q4_authority_plan_phase1_committed_receipt_last",
            "authorization_eligible": False,
            "execution_authorized": False,
            "receipt": descriptor,
            "receipt_sha256": receipt["receipt_sha256"],
            "runtime_materialization_plan": copy.deepcopy(
                receipt["runtime_materialization_plan"]
            ),
            "runtime_authority_count": len(receipt["runtime_authorities"]),
            "launcher_runtime_authority_count": len(
                receipt["launcher_runtime_authorities"]
            ),
        }
    else:
        unsigned = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": PHASE2_RESULT_KIND,
            "status": "q4_source_plan_phase2_committed_receipt_last",
            "authorization_eligible": False,
            "execution_authorized": False,
            "receipt": descriptor,
            "receipt_sha256": receipt["receipt_sha256"],
            "runtime_candidate_registry": copy.deepcopy(
                receipt["runtime_candidate_registry"]
            ),
            "source_registry_path_plan": copy.deepcopy(
                receipt["source_registry_path_plan"]
            ),
        }
    return {**unsigned, "result_sha256": canonical_sha256(unsigned)}


def _source_spec_result_summary(
    *, root: Path, source_material_path: Path | str,
    source_spec_path: Path | str, source_spec: Mapping[str, Any],
) -> dict[str, Any]:
    material_descriptor, material_payload = _read_bytes_descriptor(
        root, source_material_path, "Q4 authority source material",
    )
    try:
        material = json.loads(material_payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationQ4AuthorityPlanPipelineV1Error(
            "Q4 authority source material changed after commit"
        ) from error
    _require(
        type(material) is dict and set(material) == _SOURCE_SPEC_MATERIAL_FIELDS,
        "Q4 authority source material changed after commit",
    )
    spec_descriptor, spec_payload = _read_bytes_descriptor(
        root, source_spec_path, "Q4 authority source-spec",
    )
    _require(
        spec_payload == canonical_bytes(dict(source_spec), newline=True),
        "Q4 authority source-spec result descriptor drifted",
    )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SOURCE_SPEC_RESULT_KIND,
        "status": "q4_authority_source_spec_committed_immutable",
        "authorization_eligible": False,
        "execution_authorized": False,
        "source_material": material_descriptor,
        "source_material_sha256": canonical_sha256(material),
        "source_spec": spec_descriptor,
        "source_spec_sha256": source_spec["source_spec_sha256"],
    }
    return {**unsigned, "result_sha256": canonical_sha256(unsigned)}


def run_cli(argv: Sequence[str]) -> int:
    try:
        _require(type(argv) in {list, tuple} and bool(argv), "Q4 pipeline CLI phase is missing")
        phase = argv[0]
        if phase == "source-spec":
            arguments = _parse_exact_options(
                argv[1:], _SOURCE_SPEC_CLI_OPTIONS, "source-spec",
            )
            root = _root(arguments["--project-root"])
            source_spec = materialize_publication_q4_authority_source_spec_v1(
                project_root=root,
                source_material_path=arguments["--source-material"],
                expected_source_material_file_sha256=arguments[
                    "--source-material-file-sha256"
                ],
                expected_source_material_sha256=arguments[
                    "--source-material-sha256"
                ],
                output_path=arguments["--output"],
            )
            result = _source_spec_result_summary(
                root=root,
                source_material_path=arguments["--source-material"],
                source_spec_path=arguments["--output"],
                source_spec=source_spec,
            )
        elif phase == "phase1":
            arguments = _parse_exact_options(argv[1:], _PHASE1_CLI_OPTIONS, "Phase1")
            root = _root(arguments["--project-root"])
            receipt = materialize_publication_q4_authority_plan_phase1_v1(
                project_root=root,
                source_spec_path=arguments["--source-spec"],
                expected_source_spec_file_sha256=arguments[
                    "--source-spec-file-sha256"
                ],
                expected_source_spec_sha256=arguments["--source-spec-sha256"],
                output_dir=arguments["--output-dir"],
            )
            output = _under_root(
                root, arguments["--output-dir"], label="Q4 Phase1 output",
            )
            result = _result_summary(
                root=root, receipt_path=output / PHASE1_RECEIPT_FILENAME,
                receipt=receipt, phase=1,
            )
        elif phase == "phase2":
            arguments = _parse_exact_options(argv[1:], _PHASE2_CLI_OPTIONS, "Phase2")
            root = _root(arguments["--project-root"])
            receipt = finalize_publication_q4_source_plan_phase2_v1(
                project_root=root,
                phase1_receipt_path=arguments["--phase1-receipt"],
                expected_phase1_receipt_file_sha256=arguments[
                    "--phase1-receipt-file-sha256"
                ],
                expected_phase1_receipt_sha256=arguments[
                    "--phase1-receipt-sha256"
                ],
                runtime_materialization_result_path=arguments[
                    "--runtime-materialization-result"
                ],
                expected_runtime_materialization_result_file_sha256=arguments[
                    "--runtime-materialization-result-file-sha256"
                ],
                expected_runtime_materialization_result_sha256=arguments[
                    "--runtime-materialization-result-sha256"
                ],
                output_dir=arguments["--output-dir"],
            )
            output = _under_root(
                root, arguments["--output-dir"], label="Q4 Phase2 output",
            )
            result = _result_summary(
                root=root, receipt_path=output / PHASE2_RECEIPT_FILENAME,
                receipt=receipt, phase=2,
            )
        else:
            raise PublicationQ4AuthorityPlanPipelineV1Error(
                "Q4 pipeline CLI phase must be exactly source-spec, phase1, or phase2"
            )
        sys.stdout.buffer.write(canonical_bytes(result, newline=True))
        sys.stdout.buffer.flush()
        return 0
    except Exception as error:
        diagnostic = f"Q4 authority-plan pipeline rejected: {error}\n"
        sys.stderr.write(diagnostic[:4096])
        sys.stderr.flush()
        return EXIT_REJECTED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_REJECTED", "PHASE1_RECEIPT_FILENAME", "PHASE1_RECEIPT_KIND",
    "PHASE1_RESULT_KIND", "PHASE2_RECEIPT_FILENAME", "PHASE2_RECEIPT_KIND",
    "PHASE2_RESULT_KIND", "RUNTIME_PLAN_FILENAME", "SOURCE_PLAN_FILENAME",
    "SOURCE_SPEC_KIND", "SOURCE_SPEC_RESULT_KIND",
    "PublicationQ4AuthorityPlanPipelineV1Error",
    "build_publication_q4_authority_source_spec_v1",
    "canonical_bytes", "canonical_sha256",
    "finalize_publication_q4_source_plan_phase2_v1",
    "load_publication_q4_authority_plan_phase1_receipt_v1",
    "load_publication_q4_authority_source_material_v1",
    "load_publication_q4_authority_source_spec_v1",
    "load_publication_q4_source_plan_phase2_receipt_v1", "main",
    "materialize_publication_q4_authority_plan_phase1_v1",
    "materialize_publication_q4_authority_source_spec_v1", "run_cli",
    "validate_publication_q4_authority_plan_phase1_receipt_v1",
    "validate_publication_q4_authority_source_spec_v1",
    "validate_publication_q4_source_plan_phase2_receipt_v1",
]
