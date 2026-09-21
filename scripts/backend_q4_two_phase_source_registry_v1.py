#!/usr/bin/env python3
"""Physical source-registry boundary for the exact backend Q4 two-phase run.

The producer consumes only already accepted, physically reloadable authorities.
It closes their complete descriptor set, proves the two live UNIX sockets and
six immutable container images, and commits the exact source-registry schema
consumed by :mod:`backend_q4_two_phase_executor_v1`.  It never starts a
service, runs a benchmark, creates a grant, or claims production acceptance.
"""
from __future__ import annotations

import copy
import contextvars
import hashlib
import json
import math
import os
import re
import socket
import stat
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_q4_runtime_contract_v4 import RUNTIME_MODULE_BY_SYSTEM


SCHEMA_VERSION = 1
PATH_PLAN_KIND = "vast_backend_q4_two_phase_source_registry_path_plan_v1"
SOURCE_REGISTRY_KIND = "vast_backend_q4_two_phase_source_registry_v1"
RESULT_KIND = "vast_backend_q4_two_phase_source_registry_materialization_result_v1"
EXIT_REJECTED = 78

SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
SOCKET_ROLES = ("container_engine", "analytics_execution")
IMAGE_ROLES = (
    "cpu_worker", "gpu_worker", "deepstream_runtime", "savant_runtime",
    "openvino_gva_runtime", "gstreamer_custom_runtime",
)
RUNTIME_FILE_ROLES_BY_SYSTEM = {
    system: frozenset(RUNTIME_MODULE_BY_SYSTEM[system].FILE_ROLES)
    for system in SYSTEMS
}

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_PLAN_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "model_parity_acceptance_receipt_path",
    "policy_qualification_receipt_path", "policy_capability_manifest_path",
    "policy_calibration_mapping_path", "resource_qualification_receipt_path",
    "resource_capability_manifest_path", "runtime_candidate_registry_path",
    "analytics_service_authority_path", "guardian_preprocessing_contract_path",
    "guardian_preprocessing_receipt_path",
    "expected_analytics_service_identity_sha256", "plan_sha256",
})
_REGISTRY_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "accepted",
    "model_parity", "policy_qualification", "resource_qualification",
    "runtime_candidate_registry", "files", "sockets", "images",
    "analytics_guardian", "registry_sha256",
})
_GUARDIAN_FIELDS = frozenset({
    "preprocessing_contract", "preprocessing_receipt",
    "preprocessing_authority", "preprocessing_authority_sha256",
    "service_identity_sha256", "policy_contract_sha256",
})
_SOCKET_FIELDS = frozenset({
    "role", "transport", "ownership", "path", "device", "inode",
    "owner_uid", "owner_gid", "service_authority",
})
_IMAGE_FIELDS = frozenset({
    "role", "reference", "image_id", "os", "architecture",
    "engine_socket_role",
})
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_MAX_JSON_BYTES = 512 * 1024 * 1024
_MAX_FILE_BYTES = 16 * 1024 * 1024 * 1024
_CLI_OPTIONS = (
    "--project-root", "--plan", "--plan-file-sha256", "--plan-sha256",
    "--output", "--result-output",
)


class BackendQ4SourceRegistryV1Error(RuntimeError):
    """An accepted source, live pin, or immutable output drifted."""


_ACTIVE_PHYSICAL_CUSTODY: contextvars.ContextVar[
    PhysicalRootCustodyV1 | None
] = contextvars.ContextVar("q4_source_registry_physical_custody", default=None)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendQ4SourceRegistryV1Error(message)


def _physical_custody(
    root: Path,
) -> tuple[PhysicalRootCustodyV1, bool]:
    active = _ACTIVE_PHYSICAL_CUSTODY.get()
    if active is not None:
        _require(active.root == root, "Q4 source registry custody root drifted")
        active.verify()
        return active, False
    return (
        PhysicalRootCustodyV1.open(
            root, label="Q4 source registry project_root"
        ),
        True,
    )


def _strict_json(value: Any, *, active: set[int] | None = None, depth: int = 0) -> None:
    _require(depth <= 96, "source-registry JSON nesting is excessive")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "source-registry JSON is non-finite")
        return
    _require(type(value) in {dict, list}, "source-registry value is not JSON")
    active = set() if active is None else active
    identity = id(value)
    _require(identity not in active, "source-registry JSON contains a cycle")
    active.add(identity)
    try:
        if type(value) is dict:
            _require(
                all(type(key) is str for key in value),
                "source-registry JSON key type drifted",
            )
            items = value.values()
        else:
            items = value
        for item in items:
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
        raise BackendQ4SourceRegistryV1Error(
            "source-registry value is not canonical JSON"
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


def _is_link(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _root(project_root: Path | str) -> Path:
    candidate = Path(project_root)
    try:
        lexical = candidate.absolute()
        lexical_info = lexical.lstat()
        resolved = candidate.resolve(strict=True)
        info = resolved.lstat()
    except OSError as error:
        raise BackendQ4SourceRegistryV1Error(
            f"project_root is unavailable: {error}"
        ) from error
    _require(
        lexical == resolved and not _is_link(lexical_info)
        and stat.S_ISDIR(info.st_mode) and not _is_link(info),
        "project_root must be one physical directory",
    )
    return resolved


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


def _under_root(
    root: Path, value: Path | str, *, label: str, must_exist: bool = True,
) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root.joinpath(*PurePosixPath(_relative(str(value), label)).parts)
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} escaped project_root"
        ) from error
    cursor = root
    for part in relative.parts:
        cursor /= part
        if not cursor.exists():
            break
        try:
            info = cursor.lstat()
        except OSError as error:
            raise BackendQ4SourceRegistryV1Error(
                f"{label} cannot be inspected: {error}"
            ) from error
        _require(not _is_link(info), f"{label} contains a link/reparse point")
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} is missing or escaped project_root: {error}"
        ) from error
    _require(resolved == candidate, f"{label} resolved through an alias")
    return resolved


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    path = _relative(value.get("path"), label)
    size = value.get("size_bytes")
    _require(
        type(size) is int and 0 < size <= _MAX_FILE_BYTES,
        f"{label} descriptor size is invalid",
    )
    return {"path": path, "size_bytes": size, "sha256": _sha(value.get("sha256"), label)}


def _mount_descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} descriptor is missing")
    _require(
        set(value) in {_DESCRIPTOR_FIELDS, _DESCRIPTOR_FIELDS | {"container_path"}},
        f"{label} descriptor fields drifted",
    )
    return _descriptor(
        {key: value[key] for key in _DESCRIPTOR_FIELDS}, label,
    )


def _hash_fd(file_descriptor: int, maximum: int) -> tuple[int, str]:
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(file_descriptor, min(1024 * 1024, maximum + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        _require(size <= maximum, "physical source exceeded its size bound")
        digest.update(chunk)
    return size, digest.hexdigest()


def _verify_descriptor(
    root: Path, value: Any, label: str,
) -> tuple[dict[str, Any], Path, tuple[int, int]]:
    item = _descriptor(value, label)
    custody: PhysicalRootCustodyV1 | None = None
    owned = False
    try:
        custody, owned = _physical_custody(root)
        observed, _payload, identity = custody.read_descriptor_identity(
            item["path"],
            label=label,
            maximum=_MAX_FILE_BYTES,
            capture=False,
        )
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} physical descriptor cannot be read"
        ) from error
    finally:
        if owned and custody is not None:
            custody.close()
    _require(
        observed == item,
        f"{label} physical descriptor drifted",
    )
    return observed, root.joinpath(*PurePosixPath(item["path"]).parts), identity


def _descriptor_for(root: Path, path: Path, label: str) -> dict[str, Any]:
    try:
        relative = Path(os.path.abspath(path)).relative_to(root).as_posix()
    except ValueError as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} escaped project_root"
        ) from error
    custody: PhysicalRootCustodyV1 | None = None
    owned = False
    try:
        custody, owned = _physical_custody(root)
        descriptor, _payload = custody.read_descriptor(
            relative,
            label=label,
            maximum=_MAX_FILE_BYTES,
            capture=False,
        )
        return descriptor
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} physical descriptor cannot be read"
        ) from error
    finally:
        if owned and custody is not None:
            custody.close()


def _read_json(
    root: Path, path: Path | str, label: str, *, maximum: int = _MAX_JSON_BYTES
) -> dict[str, Any]:
    custody: PhysicalRootCustodyV1 | None = None
    owned = False
    try:
        custody, owned = _physical_custody(root)
        _descriptor_record, payload = custody.read_descriptor(
            path, label=label, maximum=maximum, capture=True
        )
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} cannot be read"
        ) from error
    finally:
        if owned and custody is not None:
            custody.close()
    _require(payload is not None, f"{label} JSON payload is unavailable")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BackendQ4SourceRegistryV1Error(f"{label} is not valid JSON") from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(
        payload in {canonical_bytes(value), canonical_bytes(value, newline=True)},
        f"{label} is not canonical JSON",
    )
    return value


def _load_path_json(
    root: Path, value: Path | str, label: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    custody: PhysicalRootCustodyV1 | None = None
    owned = False
    try:
        custody, owned = _physical_custody(root)
        record, payload = custody.read_descriptor(
            value, label=label, maximum=_MAX_JSON_BYTES, capture=True
        )
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} cannot be read"
        ) from error
    finally:
        if owned and custody is not None:
            custody.close()
    _require(payload is not None, f"{label} JSON payload is unavailable")
    try:
        document = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} is not valid JSON"
        ) from error
    _require(type(document) is dict, f"{label} must be a JSON object")
    _require(
        payload in {canonical_bytes(document), canonical_bytes(document, newline=True)},
        f"{label} is not canonical JSON",
    )
    path = root.joinpath(*PurePosixPath(record["path"]).parts)
    return record, dict(document), path


def build_backend_q4_two_phase_source_registry_path_plan_v1(
    *, model_parity_acceptance_receipt_path: str,
    policy_qualification_receipt_path: str,
    policy_capability_manifest_path: str,
    policy_calibration_mapping_path: str,
    resource_qualification_receipt_path: str,
    resource_capability_manifest_path: str,
    runtime_candidate_registry_path: str,
    analytics_service_authority_path: str,
    guardian_preprocessing_contract_path: str,
    guardian_preprocessing_receipt_path: str,
    expected_analytics_service_identity_sha256: str,
) -> dict[str, Any]:
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": PATH_PLAN_KIND,
        "status": "planned_accepted_physical_q4_sources",
        "authorization_eligible": False,
        "execution_authorized": False,
        "model_parity_acceptance_receipt_path": model_parity_acceptance_receipt_path,
        "policy_qualification_receipt_path": policy_qualification_receipt_path,
        "policy_capability_manifest_path": policy_capability_manifest_path,
        "policy_calibration_mapping_path": policy_calibration_mapping_path,
        "resource_qualification_receipt_path": resource_qualification_receipt_path,
        "resource_capability_manifest_path": resource_capability_manifest_path,
        "runtime_candidate_registry_path": runtime_candidate_registry_path,
        "analytics_service_authority_path": analytics_service_authority_path,
        "guardian_preprocessing_contract_path": guardian_preprocessing_contract_path,
        "guardian_preprocessing_receipt_path": guardian_preprocessing_receipt_path,
        "expected_analytics_service_identity_sha256": (
            expected_analytics_service_identity_sha256
        ),
    }
    return validate_backend_q4_two_phase_source_registry_path_plan_v1(
        {**unsigned, "plan_sha256": canonical_sha256(unsigned)}
    )


def validate_backend_q4_two_phase_source_registry_path_plan_v1(
    value: Any,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _PLAN_FIELDS, "Q4 source path-plan fields drifted")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == PATH_PLAN_KIND
        and value.get("status") == "planned_accepted_physical_q4_sources"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 source path-plan header/claims drifted",
    )
    path_fields = sorted(field for field in _PLAN_FIELDS if field.endswith("_path"))
    paths = [_relative(value.get(field), f"path-plan {field}") for field in path_fields]
    _require(len(paths) == len(set(path.casefold() for path in paths)), "Q4 source path-plan paths alias")
    _sha(
        value.get("expected_analytics_service_identity_sha256"),
        "path-plan expected analytics service identity",
    )
    unsigned = {key: item for key, item in value.items() if key != "plan_sha256"}
    identity = _sha(value.get("plan_sha256"), "Q4 source path-plan")
    _require(identity == canonical_sha256(unsigned), "Q4 source path-plan self-hash drifted")
    return copy.deepcopy(value)


def _embedded_output_path(
    *, root: Path, receipt_descriptor: Mapping[str, Any], embedded: Any,
    label: str,
) -> str:
    item = _descriptor(embedded, label)
    receipt_parent = root.joinpath(
        *PurePosixPath(str(receipt_descriptor["path"])).parent.parts
    )
    first = receipt_parent.joinpath(*PurePosixPath(item["path"]).parts)
    second = root.joinpath(*PurePosixPath(item["path"]).parts)
    candidates: list[Path] = []
    for candidate in (first, second):
        if candidate not in candidates and candidate.exists():
            candidates.append(candidate)
    _require(len(candidates) == 1, f"{label} embedded path is missing or ambiguous")
    actual = _descriptor_for(root, candidates[0], label)
    _require(
        actual["size_bytes"] == item["size_bytes"]
        and actual["sha256"] == item["sha256"],
        f"{label} embedded descriptor drifted",
    )
    return actual["path"]


def _default_load_model_parity(
    *, project_root: Path, receipt_path: Path | str,
) -> dict[str, Any]:
    try:
        from checkpoint_model_parity_acceptance_v4 import (
            load_verified_model_parity_acceptance_v4,
        )
        binding = load_verified_model_parity_acceptance_v4(
            project_root=project_root, receipt_path=receipt_path,
        )
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"verified model-parity v4 acceptance loader rejected input: {error}"
        ) from error
    _require(type(binding) is dict, "model-parity v4 loader returned no binding")
    receipt = _descriptor(binding.get("receipt"), "model-parity receipt")
    receipt_document = _read_json(
        project_root,
        project_root.joinpath(*PurePosixPath(receipt["path"]).parts),
        "model-parity v4 acceptance receipt",
    )
    binding_path = receipt_document.get("acceptance_binding_path")
    _require(type(binding_path) is str, "model-parity v4 binding path is missing")
    binding_descriptor = _descriptor_for(
        project_root,
        project_root.joinpath(*PurePosixPath(_relative(binding_path, "model-parity binding")).parts),
        "model-parity v4 acceptance binding",
    )
    return {**copy.deepcopy(binding), "binding_descriptor": binding_descriptor}


def _default_load_policy_qualification(
    *, project_root: Path, receipt_path: Path | str,
    capability_path: Path | str, calibration_path: Path | str,
) -> dict[str, Any]:
    try:
        import full_publication_identity_artifacts as identity
        registry = identity._Registry(project_root)
        normalized, receipt = identity._validate_policy(
            {
                "receipt": _descriptor_for(
                    project_root,
                    _under_root(project_root, receipt_path, label="policy receipt"),
                    "policy receipt",
                ),
                "outputs": {
                    "capability_manifest": _descriptor_for(
                        project_root,
                        _under_root(project_root, capability_path, label="policy capability"),
                        "policy capability",
                    ),
                    "calibration_mapping": _descriptor_for(
                        project_root,
                        _under_root(project_root, calibration_path, label="policy calibration"),
                        "policy calibration",
                    ),
                },
            },
            registry=registry,
            assessor=identity._default_policy_assessor,
        )
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"official policy qualification loader rejected input: {error}"
        ) from error
    outputs = normalized["outputs"]
    return {
        "receipt": normalized["receipt"],
        "capability_manifest": outputs["capability_manifest"],
        "calibration_mapping": outputs["calibration_mapping"],
        "receipt_document": copy.deepcopy(receipt),
        "files": [
            copy.deepcopy(registry.files[path]) for path in sorted(registry.files)
        ],
    }


def _default_load_resource_qualification(
    *, project_root: Path, receipt_path: Path | str,
    capability_path: Path | str,
) -> dict[str, Any]:
    try:
        import full_publication_identity_artifacts as identity
        registry = identity._Registry(project_root)
        normalized, receipt, _capability = identity._validate_resource_binding(
            {
                "receipt": _descriptor_for(
                    project_root,
                    _under_root(project_root, receipt_path, label="resource receipt"),
                    "resource receipt",
                ),
                "outputs": {
                    "capability_manifest": _descriptor_for(
                        project_root,
                        _under_root(project_root, capability_path, label="resource capability"),
                        "resource capability",
                    )
                },
            },
            registry=registry,
        )
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"official resource qualification loader rejected input: {error}"
        ) from error
    return {
        "receipt": normalized["receipt"],
        "capability_manifest": normalized["outputs"]["capability_manifest"],
        "receipt_document": copy.deepcopy(receipt),
        "files": [
            copy.deepcopy(registry.files[path]) for path in sorted(registry.files)
        ],
    }


def _walk_descriptors(value: Any, *, location: str = "runtime registry") -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if type(value) is dict:
        if _DESCRIPTOR_FIELDS.issubset(value) and set(value).issubset(
            _DESCRIPTOR_FIELDS | {"container_path"}
        ):
            records.append(_mount_descriptor(value, location))
        else:
            for key, item in value.items():
                records.extend(_walk_descriptors(item, location=f"{location}.{key}"))
    elif type(value) is list:
        for position, item in enumerate(value):
            records.extend(
                _walk_descriptors(item, location=f"{location}[{position}]")
            )
    return records


def _default_load_runtime_candidate_registry(
    *, project_root: Path, registry_path: Path | str,
) -> dict[str, Any]:
    record, value, _path = _load_path_json(
        project_root, registry_path, "Q4 runtime candidate registry v4",
    )
    try:
        from publication_q4_runtime_contract_v4 import (
            validate_publication_q4_runtime_candidate_registry_v4,
        )
        checked = validate_publication_q4_runtime_candidate_registry_v4(value)
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"public Q4 runtime-candidate registry loader rejected input: {error}"
        ) from error
    by_path = {record["path"]: record}
    for position, descriptor in enumerate(_walk_descriptors(checked)):
        existing = by_path.get(descriptor["path"])
        _require(
            existing is None or existing == descriptor,
            f"runtime-candidate recurring descriptor[{position}] drifted",
        )
        by_path[descriptor["path"]] = descriptor
    return {
        "registry": checked,
        "descriptor": record,
        "files": [copy.deepcopy(by_path[path]) for path in sorted(by_path)],
    }


def _default_load_service_authority(
    *, project_root: Path, authority_path: Path | str,
    expected_front_socket: Path,
    expected_execution_config_identity_sha256: str,
    expected_binding_set_identity_sha256: str,
    expected_worker_image_ids: Mapping[str, str],
    expected_preprocessing_contract_authority: Mapping[str, Any],
    expected_service_identity_sha256: str,
    expected_policy_contract_sha256: str,
) -> dict[str, Any]:
    record, value, _path = _load_path_json(
        project_root, authority_path, "analytics sidecar service authority",
    )
    try:
        from checkpoint_gstreamer_analytics_sidecar import (
            assert_publication_sidecar_service_authority_v1,
            validate_publication_sidecar_service_authority_v1,
        )
        checked = validate_publication_sidecar_service_authority_v1(value)
        asserted = assert_publication_sidecar_service_authority_v1(
            checked,
            expected_front_socket=expected_front_socket,
            expected_execution_config_identity_sha256=(
                expected_execution_config_identity_sha256
            ),
            expected_binding_set_identity_sha256=(
                expected_binding_set_identity_sha256
            ),
            expected_worker_image_ids=dict(expected_worker_image_ids),
            expected_preprocessing_contract_authority=(
                expected_preprocessing_contract_authority
            ),
            expected_service_identity_sha256=expected_service_identity_sha256,
            expected_policy_contract_sha256=expected_policy_contract_sha256,
        )
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"foreground analytics guardian authority rejected input: {error}"
        ) from error
    _require(asserted == checked, "analytics guardian normalized authority drifted")
    return {"descriptor": record, "authority": copy.deepcopy(checked)}


def _default_load_accepted_guardian_preprocessing(
    *, project_root: Path, preprocessing_contract_path: Path | str,
    materialization_receipt_path: Path | str,
    accepted_policy_capability_manifest_path: Path | str,
) -> dict[str, Any]:
    try:
        from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
            load_accepted_policy_guardian_preprocessing_contract_v1,
        )
        loaded = load_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=project_root,
            preprocessing_contract_path=preprocessing_contract_path,
            materialization_receipt_path=materialization_receipt_path,
            accepted_policy_capability_manifest_path=(
                accepted_policy_capability_manifest_path
            ),
        )
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"accepted-policy guardian preprocessing loader rejected input: {error}"
        ) from error
    _require(type(loaded) is dict, "accepted-policy preprocessing loader returned no material")
    contract = _descriptor_for(
        project_root,
        _under_root(
            project_root, preprocessing_contract_path,
            label="accepted guardian preprocessing contract",
        ),
        "accepted guardian preprocessing contract",
    )
    receipt = _descriptor_for(
        project_root,
        _under_root(
            project_root, materialization_receipt_path,
            label="accepted guardian preprocessing receipt",
        ),
        "accepted guardian preprocessing receipt",
    )
    receipt_document = loaded.get("receipt")
    _require(type(receipt_document) is dict, "accepted-policy preprocessing receipt is missing")
    by_path = {contract["path"]: contract, receipt["path"]: receipt}
    for position, item in enumerate(_walk_descriptors(receipt_document)):
        record, _path, _inode = _verify_descriptor(
            project_root, item,
            f"accepted-policy preprocessing source[{position}]",
        )
        existing = by_path.get(record["path"])
        _require(
            existing is None or existing == record,
            "accepted-policy preprocessing recurring descriptor drifted",
        )
        by_path[record["path"]] = record
    return {
        "contract": contract,
        "receipt": receipt,
        "authority": copy.deepcopy(loaded.get("authority")),
        "runtime_expectations": copy.deepcopy(loaded.get("runtime_expectations")),
        "files": [copy.deepcopy(by_path[path]) for path in sorted(by_path)],
    }


def _docker_http_body(*, engine_socket_path: Path, target: str) -> bytes:
    request = (
        f"GET {target} HTTP/1.1\r\nHost: docker\r\nAccept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.settimeout(10.0)
    try:
        endpoint.connect(str(engine_socket_path))
        endpoint.sendall(request)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = endpoint.recv(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            _require(size <= 64 * 1024 * 1024, "Docker inspect response exceeded its bound")
            chunks.append(chunk)
    except OSError as error:
        raise BackendQ4SourceRegistryV1Error(
            f"Docker inspect transport failed: {error}"
        ) from error
    finally:
        endpoint.close()
    payload = b"".join(chunks)
    head, separator, body = payload.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    _require(separator == b"\r\n\r\n" and lines and lines[0] == b"HTTP/1.1 200 OK", "Docker inspect returned non-success")
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        name, marker, item = line.partition(b":")
        _require(marker == b":" and bool(name), "Docker inspect response header is malformed")
        key = name.strip().lower()
        _require(key not in headers, "Docker inspect response has duplicate headers")
        headers[key] = item.strip()
    if headers.get(b"transfer-encoding", b"").lower() == b"chunked":
        decoded = bytearray()
        cursor = body
        while True:
            line, marker, cursor = cursor.partition(b"\r\n")
            _require(marker == b"\r\n", "Docker inspect chunk header is truncated")
            try:
                length = int(line.split(b";", 1)[0], 16)
            except ValueError as error:
                raise BackendQ4SourceRegistryV1Error("Docker inspect chunk length is invalid") from error
            if length == 0:
                _require(cursor in {b"", b"\r\n"}, "Docker inspect trailer is unsupported")
                break
            _require(len(cursor) >= length + 2 and cursor[length:length + 2] == b"\r\n", "Docker inspect chunk is truncated")
            decoded.extend(cursor[:length])
            cursor = cursor[length + 2:]
        body = bytes(decoded)
    elif b"content-length" in headers:
        try:
            expected = int(headers[b"content-length"])
        except ValueError as error:
            raise BackendQ4SourceRegistryV1Error("Docker inspect length is invalid") from error
        _require(expected == len(body), "Docker inspect body length drifted")
    return body


def _default_inspect_image(
    *, engine_socket_path: Path, reference: str,
) -> dict[str, str]:
    payload = _docker_http_body(
        engine_socket_path=engine_socket_path,
        target=f"/images/{urllib.parse.quote(reference, safe='')}/json",
    )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendQ4SourceRegistryV1Error("Docker inspect JSON is invalid") from error
    _require(type(value) is dict, "Docker inspect payload is not an object")
    image_id = value.get("Id")
    architecture = value.get("Architecture")
    _require(
        type(image_id) is str and _IMAGE_ID_RE.fullmatch(image_id) is not None
        and value.get("Os") == "linux" and type(architecture) is str
        and bool(architecture),
        "Docker inspect image identity/platform drifted",
    )
    return {
        "reference": reference, "image_id": image_id,
        "os": "linux", "architecture": architecture,
    }


@dataclass(frozen=True, slots=True)
class BackendQ4SourceRegistryDependenciesV1:
    load_model_parity: Callable[..., dict[str, Any]] = _default_load_model_parity
    load_policy_qualification: Callable[..., dict[str, Any]] = (
        _default_load_policy_qualification
    )
    load_resource_qualification: Callable[..., dict[str, Any]] = (
        _default_load_resource_qualification
    )
    load_runtime_candidate_registry: Callable[..., dict[str, Any]] = (
        _default_load_runtime_candidate_registry
    )
    load_accepted_guardian_preprocessing: Callable[..., dict[str, Any]] = (
        _default_load_accepted_guardian_preprocessing
    )
    load_service_authority: Callable[..., dict[str, Any]] = (
        _default_load_service_authority
    )
    inspect_image: Callable[..., dict[str, str]] = _default_inspect_image


class _Closure:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.by_path: dict[str, dict[str, Any]] = {}
        self.by_inode: dict[tuple[int, int], str] = {}

    def add(self, value: Any, label: str) -> dict[str, Any]:
        record, _path, inode = _verify_descriptor(self.root, value, label)
        existing = self.by_path.get(record["path"])
        if existing is not None:
            _require(existing == record, f"{label} recurring descriptor drifted")
            _require(
                self.by_inode.get(inode) == record["path"],
                f"{label} inode identity drifted",
            )
            return copy.deepcopy(existing)
        _require(
            inode not in self.by_inode,
            f"{label} hardlink-aliases {self.by_inode.get(inode, '')}",
        )
        self.by_path[record["path"]] = record
        self.by_inode[inode] = record["path"]
        return copy.deepcopy(record)

    def add_many(self, value: Any, label: str) -> list[dict[str, Any]]:
        _require(type(value) is list and bool(value), f"{label} file closure is empty")
        return [self.add(item, f"{label}[{position}]") for position, item in enumerate(value)]

    def files(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self.by_path[path]) for path in sorted(self.by_path)]


def _normalize_model_parity(
    root: Path, value: Any, closure: _Closure,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _require(type(value) is dict, "model-parity v4 loader result is invalid")
    files = value.get("files")
    closure.add_many(files, "model-parity v4 accepted files")
    receipt = closure.add(value.get("receipt"), "model-parity v4 receipt")
    manifest = closure.add(value.get("accepted_manifest"), "model-parity v4 manifest")
    assessment = closure.add(value.get("accepted_assessment"), "model-parity v4 assessment")
    binding_descriptor = closure.add(
        value.get("binding_descriptor"), "model-parity v4 acceptance binding",
    )
    _sha(value.get("binding_sha256"), "model-parity v4 binding")
    _sha(
        value.get("accepted_manifest_content_identity_sha256"),
        "model-parity v4 manifest content",
    )
    refresh = value.get("refresh_authority")
    _require(type(refresh) is dict, "model-parity v4 refresh authority is missing")
    patch = refresh.get("image_identity_patch")
    execution = refresh.get("execution_config")
    binding_set = refresh.get("binding_set")
    workers = refresh.get("workers")
    _require(
        type(patch) is dict and type(execution) is dict
        and type(binding_set) is dict and type(workers) is dict
        and set(workers) == {"cpu", "gpu"},
        "model-parity v4 refresh authority fields drifted",
    )
    patch_record = closure.add(
        {key: patch[key] for key in _DESCRIPTOR_FIELDS},
        "model-parity image identity patch",
    )
    execution_record = closure.add(
        {key: execution[key] for key in _DESCRIPTOR_FIELDS},
        "model-parity execution config",
    )
    binding_index = binding_set.get("index")
    _require(type(binding_index) is dict, "model-parity binding-set index is missing")
    closure.add(
        {key: binding_index[key] for key in _DESCRIPTOR_FIELDS},
        "model-parity binding-set index",
    )
    parity_paths = {
        _descriptor(item, f"model-parity v4 files[{position}]")["path"]
        for position, item in enumerate(files)
    }
    _require(
        {patch_record["path"], execution_record["path"], binding_index["path"]}
        .issubset(parity_paths),
        "model-parity refresh authority is outside its full files closure",
    )
    identity_inputs = {
        "analytics_model_parity": {
            "receipt": receipt,
            "accepted_manifest": manifest,
            "accepted_assessment": assessment,
        },
        "analytics_execution_layer": {
            "artifact": execution_record,
            "content_identity_sha256": _sha(
                execution.get("content_identity_sha256"),
                "analytics execution config content",
            ),
        },
    }
    normalized = copy.deepcopy(value)
    normalized["receipt"] = receipt
    normalized["accepted_manifest"] = manifest
    normalized["accepted_assessment"] = assessment
    normalized["binding_descriptor"] = binding_descriptor
    return normalized, identity_inputs, patch_record


def _normalize_policy(
    value: Any, closure: _Closure,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(type(value) is dict, "policy qualification loader result is invalid")
    closure.add_many(value.get("files"), "policy qualification files")
    receipt = closure.add(value.get("receipt"), "policy qualification receipt")
    capability = closure.add(
        value.get("capability_manifest"), "policy capability manifest",
    )
    calibration = closure.add(
        value.get("calibration_mapping"), "policy calibration mapping",
    )
    document = value.get("receipt_document")
    _require(type(document) is dict, "policy receipt document is missing")
    _sha(document.get("policy_contract_sha256"), "policy contract")
    _sha(document.get("dataset_manifest_sha256"), "policy qualification dataset")
    _sha(document.get("sha256"), "policy qualification receipt")
    return (
        {
            **copy.deepcopy(value), "receipt": receipt,
            "capability_manifest": capability,
            "calibration_mapping": calibration,
        },
        {
            "receipt": receipt, "capability_manifest": capability,
            "calibration_mapping": calibration,
        },
    )


def _normalize_resource(
    value: Any, closure: _Closure,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require(type(value) is dict, "resource qualification loader result is invalid")
    closure.add_many(value.get("files"), "resource qualification files")
    receipt = closure.add(value.get("receipt"), "resource qualification receipt")
    capability = closure.add(
        value.get("capability_manifest"), "resource capability manifest",
    )
    document = value.get("receipt_document")
    _require(type(document) is dict, "resource receipt document is missing")
    _sha(document.get("resource_contract_identity_sha256"), "resource contract")
    _sha(document.get("dataset_manifest_sha256"), "resource qualification dataset")
    _sha(document.get("sha256"), "resource qualification receipt")
    return (
        {**copy.deepcopy(value), "receipt": receipt, "capability_manifest": capability},
        {"receipt": receipt, "capability_manifest": capability},
    )


def _expected_snapshot_coordinates() -> list[dict[str, str]]:
    return [
        {
            "system": system, "codec": codec,
            "topology_kind": topology, "policy": policy,
        }
        for system in SYSTEMS
        for codec in CODECS
        for topology in TOPOLOGIES
        for policy in POLICIES
    ]


def _normalize_runtime_registry(
    value: Any, closure: _Closure,
) -> dict[str, Any]:
    _require(type(value) is dict, "runtime-candidate loader result is invalid")
    registry = value.get("registry")
    _require(
        type(registry) is dict
        and registry.get("schema_version") == 4
        and registry.get("artifact_kind")
        == "vast_publication_q4_runtime_candidate_registry_v4"
        and registry.get("status") == "physically_prepared_runtime_candidates"
        and registry.get("accepted_as_input") is True
        and registry.get("authorization_eligible") is False
        and registry.get("execution_authorized") is False,
        "runtime-candidate registry is not an accepted non-authorizing input",
    )
    named_input = _descriptor(
        value.get("descriptor"), "runtime-candidate registry"
    )
    expected_files = {named_input["path"]: named_input}
    for position, descriptor in enumerate(_walk_descriptors(registry)):
        previous = expected_files.get(descriptor["path"])
        _require(
            previous is None or previous == descriptor,
            f"runtime-candidate embedded descriptor[{position}] drifted",
        )
        expected_files[descriptor["path"]] = descriptor
    declared_raw = value.get("files")
    _require(
        type(declared_raw) is list and bool(declared_raw),
        "runtime-candidate descriptor closure is empty",
    )
    declared_files: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(declared_raw):
        descriptor = _descriptor(
            item, f"runtime-candidate descriptor closure[{position}]"
        )
        _require(
            descriptor["path"] not in declared_files,
            "runtime-candidate descriptor closure repeats a path",
        )
        declared_files[descriptor["path"]] = descriptor
    _require(
        declared_files == expected_files,
        "runtime-candidate descriptor closure is not exact",
    )
    closure.add_many(declared_raw, "runtime-candidate descriptor closure")
    named = closure.add(named_input, "runtime-candidate registry")
    snapshots = registry.get("authority_snapshots")
    expected = _expected_snapshot_coordinates()
    _require(
        type(snapshots) is list and len(snapshots) == len(expected),
        "runtime-candidate registry must contain exact 112 authorities",
    )
    for position, (snapshot, coordinate) in enumerate(zip(snapshots, expected, strict=True)):
        _require(
            type(snapshot) is dict and snapshot.get("coordinate") == coordinate
            and type(snapshot.get("upstream_identities")) is dict
            and type(snapshot.get("runtime_input_template")) is dict,
            f"runtime-candidate authority[{position}] coordinate/material drifted",
        )
    return {"registry": copy.deepcopy(registry), "descriptor": named}


def _normalize_accepted_guardian_preprocessing(
    value: Any, closure: _Closure,
) -> dict[str, Any]:
    _require(type(value) is dict, "accepted guardian preprocessing loader result is invalid")
    closure.add_many(value.get("files"), "accepted guardian preprocessing files")
    contract = closure.add(
        value.get("contract"), "accepted guardian preprocessing contract",
    )
    receipt = closure.add(
        value.get("receipt"), "accepted guardian preprocessing receipt",
    )
    try:
        from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
            validate_accepted_policy_guardian_preprocessing_authority_v1,
        )

        authority = validate_accepted_policy_guardian_preprocessing_authority_v1(
            value.get("authority")
        )
    except BackendQ4SourceRegistryV1Error:
        raise
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"accepted guardian preprocessing authority rejected: {error}"
        ) from error
    expectations = value.get("runtime_expectations")
    _require(
        type(expectations) is dict
        and set(expectations)
        == {
            "execution_config_identity_sha256", "binding_set_identity_sha256",
            "bindings_identity_sha256", "worker_image_ids",
            "policy_contract_sha256", "preprocessing_contract_content_sha256",
        }
        and type(expectations.get("worker_image_ids")) is dict
        and set(expectations["worker_image_ids"]) == {"cpu", "gpu"},
        "accepted guardian preprocessing authority/runtime pins drifted",
    )
    for field in (
        "execution_config_identity_sha256", "binding_set_identity_sha256",
        "bindings_identity_sha256", "policy_contract_sha256",
        "preprocessing_contract_content_sha256",
    ):
        _sha(expectations.get(field), f"accepted guardian {field}")
    for resource in ("cpu", "gpu"):
        image_id = expectations["worker_image_ids"].get(resource)
        _require(
            type(image_id) is str and _IMAGE_ID_RE.fullmatch(image_id) is not None,
            f"accepted guardian {resource} worker image drifted",
        )
    _require(
        authority.get("preprocessing_contract_file_sha256") == contract["sha256"]
        and authority.get("materialization_receipt_file_sha256")
        == receipt["sha256"]
        and authority.get("execution_config_identity_sha256")
        == expectations["execution_config_identity_sha256"]
        and authority.get("binding_set_identity_sha256")
        == expectations["binding_set_identity_sha256"]
        and authority.get("bindings_identity_sha256")
        == expectations["bindings_identity_sha256"]
        and authority.get("worker_image_ids") == expectations["worker_image_ids"]
        and authority.get("policy_contract_sha256")
        == expectations["policy_contract_sha256"]
        and authority.get("preprocessing_contract_content_sha256")
        == expectations["preprocessing_contract_content_sha256"],
        "accepted guardian preprocessing authority semantic pins drifted",
    )
    return {
        "contract": contract,
        "receipt": receipt,
        "authority": copy.deepcopy(authority),
        "runtime_expectations": copy.deepcopy(expectations),
    }


def _socket_node(value: Any, *, endpoint: bool, label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} socket binding is missing")
    path_key = "host_path" if endpoint and "host_path" in value else "path"
    expected = {path_key, "device", "inode", "owner_uid", "owner_gid"}
    if endpoint:
        expected.add("container_path")
    _require(set(value) == expected, f"{label} socket binding fields drifted")
    path = value.get(path_key)
    _require(
        type(path) is str and path.startswith("/") and "\\" not in path
        and "\x00" not in path and os.path.normpath(path) == path
        and len(os.fsencode(path)) < 108
        and all(
            type(value.get(field)) is int and value[field] >= 0
            for field in ("device", "inode", "owner_uid", "owner_gid")
        ),
        f"{label} socket binding values drifted",
    )
    return {
        "path": path,
        **{field: value[field] for field in ("device", "inode", "owner_uid", "owner_gid")},
    }


def _socket_transport(path: Path) -> str:
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical socket transport validation requires Linux/WSL",
    )
    try:
        payload = Path("/proc/net/unix").read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise BackendQ4SourceRegistryV1Error(
            f"cannot inspect live AF_UNIX transport: {error}"
        ) from error
    matches: list[str] = []
    for raw in payload.splitlines()[1:]:
        fields = raw.split(maxsplit=7)
        if len(fields) == 8 and fields[7] == str(path):
            matches.append(fields[4])
    _require(len(matches) == 1, "live AF_UNIX socket is absent or ambiguous")
    transport = {"0001": "AF_UNIX/SOCK_STREAM", "0005": "AF_UNIX/SOCK_SEQPACKET"}.get(matches[0])
    _require(transport is not None, "live AF_UNIX socket transport is unsupported")
    return transport


def _verify_socket(node: Mapping[str, Any], *, expected_transport: str, label: str) -> Path:
    path = Path(str(node["path"]))
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BackendQ4SourceRegistryV1Error(f"{label} live socket is missing: {error}") from error
    _require(
        resolved == path and stat.S_ISSOCK(info.st_mode) and not _is_link(info)
        and int(info.st_dev) == node["device"]
        and int(info.st_ino) == node["inode"]
        and int(info.st_uid) == node["owner_uid"]
        and int(info.st_gid) == node["owner_gid"]
        and _socket_transport(path) == expected_transport,
        f"{label} live socket identity/transport drifted",
    )
    return path


def _accepted_policy_calibrations(
    root: Path,
    mapping_descriptor: Mapping[str, Any],
    *,
    expected_policy_contract_sha256: str,
) -> dict[str, dict[str, Any]]:
    record, path, _identity = _verify_descriptor(
        root, mapping_descriptor, "accepted policy calibration mapping"
    )
    mapping = _read_json(root, path, "accepted policy calibration mapping")
    _require(
        set(mapping)
        == {
            "schema_version",
            "artifact_kind",
            "policy_contract_sha256",
            "aggregation_rule",
            "minimum_samples_per_branch_cell",
            "calibrations",
        }
        and mapping.get("schema_version") == 1
        and mapping.get("artifact_kind")
        == "vast_publication_policy_calibration_mapping"
        and mapping.get("policy_contract_sha256")
        == expected_policy_contract_sha256
        and mapping.get("aggregation_rule")
        == "median_of_balanced_native_codec_topology_cells_v1"
        and mapping.get("minimum_samples_per_branch_cell") == 30,
        "accepted policy calibration mapping schema/contract drifted",
    )
    calibrations = mapping.get("calibrations")
    _require(
        type(calibrations) is dict and set(calibrations) == set(SYSTEMS),
        "accepted policy calibration mapping system coverage drifted",
    )
    checked: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        calibration = calibrations.get(system)
        _require(
            type(calibration) is dict
            and set(calibration)
            == {
                "schema_version",
                "artifact_kind",
                "system",
                "policy_contract_sha256",
                "costs",
            }
            and calibration.get("schema_version") == 1
            and calibration.get("artifact_kind")
            == "vast_publication_policy_calibration"
            and calibration.get("system") == system
            and calibration.get("policy_contract_sha256")
            == expected_policy_contract_sha256
            and type(calibration.get("costs")) is dict,
            f"accepted {system} policy calibration schema/contract drifted",
        )
        checked[system] = copy.deepcopy(calibration)
    _require(
        record == dict(mapping_descriptor),
        "accepted policy calibration mapping descriptor normalized",
    )
    return checked


def _template_material(
    root: Path,
    runtime: Mapping[str, Any],
    *,
    policy_capability: Mapping[str, Any],
    accepted_policy_calibrations: Mapping[str, Mapping[str, Any]],
    execution_config: Mapping[str, Any],
    preprocessing_contract_sha256: str,
    expected_upstream: Mapping[str, str],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    engine: dict[str, Any] | None = None
    analytics: dict[str, Any] | None = None
    system_images: dict[str, dict[str, Any]] = {}
    system_calibrations: dict[str, dict[str, Any]] = {}
    for position, snapshot in enumerate(runtime["registry"]["authority_snapshots"]):
        upstream = snapshot["upstream_identities"]
        for field, expected in expected_upstream.items():
            _require(
                upstream.get(field) == expected,
                f"runtime-candidate authority[{position}] upstream {field} drifted",
            )
        template = snapshot["runtime_input_template"]
        current_engine = _socket_node(
            template.get("container_engine_socket"), endpoint=False,
            label=f"runtime template[{position}] container engine",
        )
        endpoints = template.get("endpoint_sockets")
        _require(
            type(endpoints) is list and len(endpoints) == 1,
            f"runtime template[{position}] analytics socket coverage drifted",
        )
        current_analytics = _socket_node(
            endpoints[0], endpoint=True,
            label=f"runtime template[{position}] analytics endpoint",
        )
        engine = current_engine if engine is None else engine
        analytics = current_analytics if analytics is None else analytics
        _require(current_engine == engine, "runtime templates container-engine socket pins drifted")
        _require(current_analytics == analytics, "runtime templates analytics socket pins drifted")
        system = snapshot["coordinate"]["system"]
        files = template.get("files")
        expected_roles = RUNTIME_FILE_ROLES_BY_SYSTEM[system]
        _require(
            type(files) is dict and set(files) == set(expected_roles),
            f"runtime template[{position}] {system} file-role coverage drifted",
        )
        for role, expected_descriptor in (
            ("policy_capability_manifest", policy_capability),
        ):
            _require(
                _mount_descriptor(files.get(role), f"runtime template[{position}] {role}")
                == dict(expected_descriptor),
                f"runtime template[{position}] {role} cross-binding drifted",
            )
        if "analytics_execution_manifest" in expected_roles:
            from checkpoint_native_policy_runtime import (
                EXTERNAL_EXECUTION_MANIFEST_KIND,
                assess_gstreamer_native_policy_execution_manifest,
            )

            label = f"runtime template[{position}] execution manifest"
            manifest_pin = _mount_descriptor(files.get("analytics_execution_manifest"), label)
            _record, manifest_path, _identity = _verify_descriptor(root, manifest_pin, label)
            manifest = _read_json(root, manifest_path, label)
            _require(
                manifest.get("artifact_kind") == EXTERNAL_EXECUTION_MANIFEST_KIND
                and manifest.get("execution_config") == dict(execution_config)
                and template.get("preprocessing_contract_sha256") == preprocessing_contract_sha256,
                f"{label} config/preprocessing cross-binding drifted",
            )
            _record, policy_path, _identity = _verify_descriptor(root, policy_capability, "accepted policy capability")
            accepted_policy = _read_json(root, policy_path, "accepted policy capability")
            assessment = assess_gstreamer_native_policy_execution_manifest(
                manifest, system=system, capability_manifest=accepted_policy,
                preprocessing_contract_sha256=preprocessing_contract_sha256,
            )
            _require(assessment["passed"], f"{label} authority drifted: " + ",".join(assessment["blockers"]))
        calibration_descriptor = _mount_descriptor(
            files.get("policy_calibration"),
            f"runtime template[{position}] policy_calibration",
        )
        previous_calibration = system_calibrations.setdefault(
            system, calibration_descriptor
        )
        _require(
            previous_calibration == calibration_descriptor,
            f"{system} runtime calibration descriptor drifted across templates",
        )
        _record, calibration_path, _identity = _verify_descriptor(
            root,
            calibration_descriptor,
            f"{system} runtime policy calibration",
        )
        observed_calibration = _read_json(
            root,
            calibration_path,
            f"{system} runtime policy calibration",
        )
        _require(
            observed_calibration == accepted_policy_calibrations[system],
            f"{system} runtime policy calibration differs from accepted mapping",
        )
        image = template.get("container_image")
        _require(type(image) is dict, f"runtime template[{position}] container image is missing")
        image_id = image.get("image_id")
        _require(
            type(image_id) is str and _IMAGE_ID_RE.fullmatch(image_id) is not None,
            f"runtime template[{position}] container image identity is invalid",
        )
        observed = system_images.setdefault(system, {"image_id": image_id})
        _require(observed["image_id"] == image_id, f"{system} runtime image identity drifted across templates")
    _require(
        engine is not None
        and analytics is not None
        and set(system_images) == set(SYSTEMS)
        and set(system_calibrations) == set(SYSTEMS)
        and len(
            {
                descriptor["path"].casefold()
                for descriptor in system_calibrations.values()
            }
        )
        == len(SYSTEMS),
        "runtime template socket/image/calibration coverage is incomplete",
    )
    for system, descriptor in system_calibrations.items():
        _record, path, _identity = _verify_descriptor(
            root,
            descriptor,
            f"{system} runtime policy calibration post-snapshot",
        )
        _require(
            _read_json(
                root,
                path,
                f"{system} runtime policy calibration post-snapshot",
            )
            == accepted_policy_calibrations[system],
            f"{system} runtime policy calibration changed during derivation",
        )
    return engine, analytics, system_images, system_calibrations


def _load_image_patch(
    root: Path, descriptor: Mapping[str, Any], expected_patch_sha256: Any,
) -> dict[str, Any]:
    record, path, _inode = _verify_descriptor(root, descriptor, "image identity patch")
    value = _read_json(root, path, "image identity patch")
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind")
        == "vast_publication_qualification_image_identity_patch_v1"
        and value.get("patch_sha256")
        == _sha(expected_patch_sha256, "model-parity image patch"),
        "image identity patch header/acceptance binding drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "patch_sha256"}
    _require(
        value["patch_sha256"] == canonical_sha256(unsigned),
        "image identity patch self-hash drifted",
    )
    _require(
        type(value.get("workers")) is dict
        and set(value["workers"]) == {"cpu", "gpu"}
        and type(value.get("systems")) is dict
        and set(value["systems"]) == set(SYSTEMS),
        "image identity patch worker/system coverage drifted",
    )
    _require(record == dict(descriptor), "image identity patch descriptor normalized")
    return value


def _image_pins(
    *, root: Path, model: Mapping[str, Any], patch_descriptor: Mapping[str, Any],
    runtime_system_images: Mapping[str, Mapping[str, Any]],
    engine_socket_path: Path, dependencies: BackendQ4SourceRegistryDependenciesV1,
) -> list[dict[str, Any]]:
    refresh = model["refresh_authority"]
    patch_ref = refresh["image_identity_patch"]
    patch = _load_image_patch(
        root, patch_descriptor, patch_ref.get("patch_sha256"),
    )
    expected: dict[str, dict[str, str]] = {}
    workers = refresh["workers"]
    for resource, role in (("cpu", "cpu_worker"), ("gpu", "gpu_worker")):
        accepted = workers.get(resource)
        frozen = patch["workers"].get(resource)
        _require(type(accepted) is dict and type(frozen) is dict, f"{role} image authority is missing")
        reference = accepted.get("image")
        image_id = accepted.get("image_id")
        _require(
            reference == frozen.get("target_reference")
            and image_id == frozen.get("image_id")
            and type(reference) is str and bool(reference)
            and type(image_id) is str and _IMAGE_ID_RE.fullmatch(image_id) is not None,
            f"{role} parity/image-patch identity drifted",
        )
        expected[role] = {"reference": reference, "image_id": image_id}
    for system in SYSTEMS:
        role = f"{system}_runtime"
        physical = (patch["systems"].get(system) or {}).get("physical_identity")
        _require(type(physical) is dict, f"{role} physical image identity is missing")
        reference = physical.get("final_reference")
        image_id = physical.get("image_id")
        _require(
            type(reference) is str and bool(reference)
            and type(image_id) is str and _IMAGE_ID_RE.fullmatch(image_id) is not None
            and physical.get("os") == "linux"
            and type(physical.get("architecture")) is str
            and bool(physical["architecture"])
            and runtime_system_images[system]["image_id"] == image_id,
            f"{role} runtime-template/image-patch identity drifted",
        )
        expected[role] = {"reference": reference, "image_id": image_id}
    _require(set(expected) == set(IMAGE_ROLES), "six-image Q4 coverage drifted")
    pins: list[dict[str, Any]] = []
    for role in sorted(IMAGE_ROLES):
        authority = expected[role]
        try:
            observed = dependencies.inspect_image(
                engine_socket_path=engine_socket_path,
                reference=authority["reference"],
            )
        except BackendQ4SourceRegistryV1Error:
            raise
        except Exception as error:
            raise BackendQ4SourceRegistryV1Error(
                f"{role} live image inspection failed: {error}"
            ) from error
        _require(
            type(observed) is dict
            and set(observed) == {"reference", "image_id", "os", "architecture"}
            and observed.get("reference") == authority["reference"]
            and observed.get("image_id") == authority["image_id"]
            and observed.get("os") == "linux"
            and type(observed.get("architecture")) is str
            and bool(observed["architecture"]),
            f"{role} live immutable image identity drifted",
        )
        if role.endswith("_runtime"):
            system = role.removesuffix("_runtime")
            physical = patch["systems"][system]["physical_identity"]
            _require(
                observed["os"] == physical["os"]
                and observed["architecture"] == physical["architecture"],
                f"{role} live image platform drifted from physical patch",
            )
        pins.append({
            "role": role, **copy.deepcopy(observed),
            "engine_socket_role": "container_engine",
        })
    return pins


def _service_and_socket_pins(
    *, root: Path, engine: Mapping[str, Any], analytics: Mapping[str, Any],
    model: Mapping[str, Any], accepted_preprocessing: Mapping[str, Any],
    expected_service_identity_sha256: str,
    service_authority_path: Path | str,
    closure: _Closure, dependencies: BackendQ4SourceRegistryDependenciesV1,
) -> tuple[list[dict[str, Any]], Path]:
    engine_path = _verify_socket(
        engine, expected_transport="AF_UNIX/SOCK_STREAM",
        label="container engine",
    )
    analytics_path = _verify_socket(
        analytics, expected_transport="AF_UNIX/SOCK_SEQPACKET",
        label="analytics execution",
    )
    refresh = model["refresh_authority"]
    worker_ids = {
        resource: str(
            accepted_preprocessing["runtime_expectations"]["worker_image_ids"][
                resource
            ]
        ) for resource in ("cpu", "gpu")
    }
    try:
        loaded = dependencies.load_service_authority(
            project_root=root,
            authority_path=service_authority_path,
            expected_front_socket=analytics_path,
            expected_execution_config_identity_sha256=accepted_preprocessing[
                "runtime_expectations"
            ]["execution_config_identity_sha256"],
            expected_binding_set_identity_sha256=accepted_preprocessing[
                "runtime_expectations"
            ]["binding_set_identity_sha256"],
            expected_worker_image_ids=worker_ids,
            expected_preprocessing_contract_authority=accepted_preprocessing[
                "authority"
            ],
            expected_service_identity_sha256=expected_service_identity_sha256,
            expected_policy_contract_sha256=accepted_preprocessing[
                "runtime_expectations"
            ]["policy_contract_sha256"],
        )
    except BackendQ4SourceRegistryV1Error:
        raise
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"analytics guardian authority loader failed: {error}"
        ) from error
    _require(type(loaded) is dict, "analytics guardian loader result is invalid")
    service_record = closure.add(
        loaded.get("descriptor"), "analytics guardian service authority",
    )
    authority = loaded.get("authority")
    _require(type(authority) is dict, "analytics guardian authority is missing")
    front = _socket_node(
        authority.get("front_socket"), endpoint=False,
        label="analytics guardian front socket",
    )
    _require(front == dict(analytics), "guardian/runtime-template analytics socket drifted")
    sockets = [
        {
            "role": "container_engine",
            "transport": "AF_UNIX/SOCK_STREAM",
            "ownership": "external_container_engine",
            **copy.deepcopy(dict(engine)),
            "service_authority": None,
        },
        {
            "role": "analytics_execution",
            "transport": "AF_UNIX/SOCK_SEQPACKET",
            "ownership": "executor_managed_sidecar_v1",
            **copy.deepcopy(dict(analytics)),
            "service_authority": service_record,
        },
    ]
    return sockets, engine_path


def _call_loader(loader: Callable[..., dict[str, Any]], label: str, **kwargs: Any) -> dict[str, Any]:
    try:
        value = loader(**kwargs)
    except BackendQ4SourceRegistryV1Error:
        raise
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(f"{label} loader failed: {error}") from error
    _require(type(value) is dict, f"{label} loader returned no material")
    return value


def _derive_registry(
    *, root: Path, model_parity_receipt_path: Path | str,
    policy_receipt_path: Path | str, policy_capability_path: Path | str,
    policy_calibration_path: Path | str, resource_receipt_path: Path | str,
    resource_capability_path: Path | str, runtime_registry_path: Path | str,
    service_authority_path: Path | str,
    guardian_preprocessing_contract_path: Path | str,
    guardian_preprocessing_receipt_path: Path | str,
    expected_analytics_service_identity_sha256: str,
    dependencies: BackendQ4SourceRegistryDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    closure = _Closure(root)
    model, partial_identity, patch_record = _normalize_model_parity(
        root,
        _call_loader(
            dependencies.load_model_parity, "model-parity v4",
            project_root=root, receipt_path=model_parity_receipt_path,
        ),
        closure,
    )
    policy, policy_identity = _normalize_policy(
        _call_loader(
            dependencies.load_policy_qualification, "policy qualification",
            project_root=root, receipt_path=policy_receipt_path,
            capability_path=policy_capability_path,
            calibration_path=policy_calibration_path,
        ),
        closure,
    )
    resource, resource_identity = _normalize_resource(
        _call_loader(
            dependencies.load_resource_qualification, "resource qualification",
            project_root=root, receipt_path=resource_receipt_path,
            capability_path=resource_capability_path,
        ),
        closure,
    )
    runtime = _normalize_runtime_registry(
        _call_loader(
            dependencies.load_runtime_candidate_registry,
            "runtime-candidate registry v4", project_root=root,
            registry_path=runtime_registry_path,
        ),
        closure,
    )
    accepted_preprocessing = _normalize_accepted_guardian_preprocessing(
        _call_loader(
            dependencies.load_accepted_guardian_preprocessing,
            "accepted guardian preprocessing",
            project_root=root,
            preprocessing_contract_path=guardian_preprocessing_contract_path,
            materialization_receipt_path=guardian_preprocessing_receipt_path,
            accepted_policy_capability_manifest_path=policy_capability_path,
        ),
        closure,
    )
    expected_upstream = {
        "dataset_manifest_sha256": policy["receipt_document"]["dataset_manifest_sha256"],
        "policy_contract_sha256": policy["receipt_document"]["policy_contract_sha256"],
        "policy_qualification_receipt_sha256": policy["receipt_document"]["sha256"],
        "resource_contract_identity_sha256": resource["receipt_document"]["resource_contract_identity_sha256"],
        "resource_qualification_receipt_sha256": resource["receipt_document"]["sha256"],
        "analytics_execution_config_identity_sha256": partial_identity[
            "analytics_execution_layer"
        ]["content_identity_sha256"],
        "model_parity_manifest_identity_sha256": model[
            "accepted_manifest_content_identity_sha256"
        ],
        "model_parity_acceptance_binding_sha256": model["binding_sha256"],
    }
    _require(
        resource["receipt_document"]["dataset_manifest_sha256"]
        == expected_upstream["dataset_manifest_sha256"],
        "policy/resource accepted dataset identity drifted",
    )
    preprocessing_expectations = accepted_preprocessing["runtime_expectations"]
    model_refresh = model["refresh_authority"]
    _require(
        preprocessing_expectations["execution_config_identity_sha256"]
        == model_refresh["execution_config"]["content_identity_sha256"]
        == expected_upstream["analytics_execution_config_identity_sha256"]
        and preprocessing_expectations["binding_set_identity_sha256"]
        == model_refresh["binding_set"]["identity_sha256"]
        and preprocessing_expectations["bindings_identity_sha256"]
        == model_refresh["binding_set"]["bindings_identity_sha256"]
        and preprocessing_expectations["worker_image_ids"]
        == {
            resource: model_refresh["workers"][resource]["image_id"]
            for resource in ("cpu", "gpu")
        }
        and preprocessing_expectations["policy_contract_sha256"]
        == expected_upstream["policy_contract_sha256"],
        "accepted guardian preprocessing/model/policy external pins drifted",
    )
    accepted_policy_calibrations = _accepted_policy_calibrations(
        root,
        policy_identity["calibration_mapping"],
        expected_policy_contract_sha256=expected_upstream[
            "policy_contract_sha256"
        ],
    )
    (
        engine,
        analytics,
        runtime_system_images,
        runtime_policy_calibrations,
    ) = _template_material(
        root,
        runtime,
        policy_capability=policy_identity["capability_manifest"],
        accepted_policy_calibrations=accepted_policy_calibrations,
        execution_config=partial_identity["analytics_execution_layer"]["artifact"],
        preprocessing_contract_sha256=preprocessing_expectations["preprocessing_contract_content_sha256"],
        expected_upstream=expected_upstream,
    )
    sockets, engine_socket_path = _service_and_socket_pins(
        root=root, engine=engine, analytics=analytics, model=model,
        accepted_preprocessing=accepted_preprocessing,
        expected_service_identity_sha256=_sha(
            expected_analytics_service_identity_sha256,
            "expected analytics guardian service identity",
        ),
        service_authority_path=service_authority_path, closure=closure,
        dependencies=dependencies,
    )
    images = _image_pins(
        root=root, model=model, patch_descriptor=patch_record,
        runtime_system_images=runtime_system_images,
        engine_socket_path=engine_socket_path, dependencies=dependencies,
    )
    identity_inputs = {
        **partial_identity,
        "policy_qualification": {
            **policy_identity,
            "runtime_calibrations": runtime_policy_calibrations,
        },
        "resource_qualification": resource_identity,
    }
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": SOURCE_REGISTRY_KIND,
        "status": "accepted_reachable_runtime_candidates",
        "accepted": True,
        "model_parity": partial_identity["analytics_model_parity"]["receipt"],
        "policy_qualification": policy_identity["receipt"],
        "resource_qualification": resource_identity["receipt"],
        "runtime_candidate_registry": runtime["descriptor"],
        "analytics_guardian": {
            "preprocessing_contract": accepted_preprocessing["contract"],
            "preprocessing_receipt": accepted_preprocessing["receipt"],
            "preprocessing_authority": accepted_preprocessing["authority"],
            "preprocessing_authority_sha256": canonical_sha256(
                accepted_preprocessing["authority"]
            ),
            "service_identity_sha256": expected_analytics_service_identity_sha256,
            "policy_contract_sha256": preprocessing_expectations[
                "policy_contract_sha256"
            ],
        },
        "files": closure.files(),
        "sockets": sockets,
        "images": images,
    }
    registry = {**unsigned, "registry_sha256": canonical_sha256(unsigned)}
    return registry, identity_inputs


def _registry_shape(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REGISTRY_FIELDS, "Q4 source registry fields drifted")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == SOURCE_REGISTRY_KIND
        and value.get("status") == "accepted_reachable_runtime_candidates"
        and value.get("accepted") is True,
        "Q4 source registry accepted header drifted",
    )
    files = value.get("files")
    _require(type(files) is list and bool(files), "Q4 source registry file closure is empty")
    normalized = [
        _descriptor(item, f"Q4 source registry file[{position}]")
        for position, item in enumerate(files)
    ]
    _require(
        normalized == sorted(normalized, key=lambda item: item["path"])
        and len({item["path"] for item in normalized}) == len(normalized),
        "Q4 source registry files are not sorted and unique",
    )
    named = [
        _descriptor(value.get(field), f"Q4 source registry {field}")
        for field in (
            "model_parity", "policy_qualification",
            "resource_qualification", "runtime_candidate_registry",
        )
    ]
    _require(all(item in normalized for item in named), "Q4 named source is outside exact closure")
    guardian = value.get("analytics_guardian")
    _require(
        type(guardian) is dict and set(guardian) == _GUARDIAN_FIELDS,
        "Q4 analytics guardian independent pin fields drifted",
    )
    guardian_contract = _descriptor(
        guardian.get("preprocessing_contract"),
        "Q4 guardian preprocessing contract",
    )
    guardian_receipt = _descriptor(
        guardian.get("preprocessing_receipt"),
        "Q4 guardian preprocessing receipt",
    )
    try:
        from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
            validate_accepted_policy_guardian_preprocessing_authority_v1,
        )

        guardian_authority = (
            validate_accepted_policy_guardian_preprocessing_authority_v1(
                guardian.get("preprocessing_authority")
            )
        )
    except BackendQ4SourceRegistryV1Error:
        raise
    except Exception as error:
        raise BackendQ4SourceRegistryV1Error(
            f"Q4 accepted guardian preprocessing authority rejected: {error}"
        ) from error
    _require(
        guardian_contract in normalized
        and guardian_receipt in normalized
        and guardian.get("preprocessing_authority_sha256")
        == canonical_sha256(guardian_authority)
        and guardian_authority.get("preprocessing_contract_file_sha256")
        == guardian_contract["sha256"]
        and guardian_authority.get("materialization_receipt_file_sha256")
        == guardian_receipt["sha256"]
        and _sha(
            guardian.get("service_identity_sha256"),
            "Q4 guardian expected service identity",
        )
        and _sha(
            guardian.get("policy_contract_sha256"),
            "Q4 guardian expected policy identity",
        )
        and guardian_authority.get("policy_contract_sha256")
        == guardian["policy_contract_sha256"],
        "Q4 analytics guardian independent pins drifted",
    )
    sockets = value.get("sockets")
    images = value.get("images")
    _require(
        type(sockets) is list and len(sockets) == len(SOCKET_ROLES)
        and type(images) is list and len(images) == len(IMAGE_ROLES),
        "Q4 source registry socket/image coverage drifted",
    )
    for expected_role, item in zip(SOCKET_ROLES, sockets, strict=True):
        _require(
            type(item) is dict and set(item) == _SOCKET_FIELDS
            and item.get("role") == expected_role,
            f"Q4 {expected_role} socket record fields/order drifted",
        )
        node = _socket_node(
            {
                key: item[key]
                for key in ("path", "device", "inode", "owner_uid", "owner_gid")
            },
            endpoint=False,
            label=f"Q4 {expected_role}",
        )
        if expected_role == "container_engine":
            _require(
                item.get("transport") == "AF_UNIX/SOCK_STREAM"
                and item.get("ownership") == "external_container_engine"
                and item.get("service_authority") is None,
                "Q4 container-engine socket semantics drifted",
            )
        else:
            _require(
                item.get("transport") == "AF_UNIX/SOCK_SEQPACKET"
                and item.get("ownership") == "executor_managed_sidecar_v1"
                and _descriptor(item.get("service_authority"), "analytics service authority") in normalized,
                "Q4 analytics socket semantics drifted",
            )
        _require(node["path"] == item["path"], f"Q4 {expected_role} socket normalization drifted")
    observed_roles: list[str] = []
    for position, item in enumerate(images):
        _require(type(item) is dict and set(item) == _IMAGE_FIELDS, f"Q4 image[{position}] fields drifted")
        role = item.get("role")
        observed_roles.append(str(role))
        _require(
            role in IMAGE_ROLES and type(item.get("reference")) is str
            and bool(item["reference"])
            and not any(character in item["reference"] for character in "\r\n\x00")
            and type(item.get("image_id")) is str
            and _IMAGE_ID_RE.fullmatch(item["image_id"]) is not None
            and item.get("os") == "linux"
            and type(item.get("architecture")) is str and bool(item["architecture"])
            and item.get("engine_socket_role") == "container_engine",
            f"Q4 image[{position}] values drifted",
        )
    _require(
        observed_roles == sorted(IMAGE_ROLES),
        "Q4 image roles are not exact and role-sorted",
    )
    unsigned = {key: item for key, item in value.items() if key != "registry_sha256"}
    _require(
        value.get("registry_sha256") == canonical_sha256(unsigned),
        "Q4 source registry self-hash drifted",
    )
    result = copy.deepcopy(value)
    result["files"] = normalized
    return result


def _paths_from_registry(
    *, root: Path, registry: Mapping[str, Any],
    dependencies: BackendQ4SourceRegistryDependenciesV1,
) -> dict[str, str]:
    runtime_descriptor = _descriptor(
        registry["runtime_candidate_registry"], "runtime-candidate registry",
    )
    guardian = registry["analytics_guardian"]
    guardian_receipt = _descriptor(
        guardian["preprocessing_receipt"],
        "accepted guardian preprocessing receipt",
    )
    guardian_receipt_document = _read_json(
        root,
        root.joinpath(*PurePosixPath(guardian_receipt["path"]).parts),
        "accepted guardian preprocessing receipt",
    )
    policy_capability = _descriptor(
        guardian_receipt_document.get("accepted_policy_capability_manifest"),
        "accepted guardian policy capability",
    )
    policy_calibration = _descriptor(
        guardian_receipt_document.get("accepted_policy_calibration_mapping"),
        "accepted guardian policy calibration",
    )
    resource_receipt = _descriptor(
        registry["resource_qualification"], "resource qualification receipt",
    )
    resource_document = _read_json(
        root,
        root.joinpath(*PurePosixPath(resource_receipt["path"]).parts),
        "resource qualification receipt",
    )
    outputs = resource_document.get("outputs")
    _require(
        type(outputs) is dict and set(outputs) == {"capability_manifest"},
        "resource qualification receipt output descriptor is unavailable",
    )
    resource_capability = _embedded_output_path(
        root=root, receipt_descriptor=resource_receipt,
        embedded=outputs["capability_manifest"],
        label="resource capability manifest",
    )
    analytics_socket = registry["sockets"][1]
    service = _descriptor(
        analytics_socket["service_authority"], "analytics service authority",
    )
    return {
        "model_parity_receipt_path": registry["model_parity"]["path"],
        "policy_receipt_path": registry["policy_qualification"]["path"],
        "policy_capability_path": policy_capability["path"],
        "policy_calibration_path": policy_calibration["path"],
        "resource_receipt_path": resource_receipt["path"],
        "resource_capability_path": resource_capability,
        "runtime_registry_path": runtime_descriptor["path"],
        "service_authority_path": service["path"],
        "guardian_preprocessing_contract_path": guardian[
            "preprocessing_contract"
        ]["path"],
        "guardian_preprocessing_receipt_path": guardian_receipt["path"],
        "expected_analytics_service_identity_sha256": guardian[
            "service_identity_sha256"
        ],
    }


def validate_backend_q4_two_phase_source_registry_v1(
    value: Any, *, project_root: Path | str,
    dependencies: BackendQ4SourceRegistryDependenciesV1 = BackendQ4SourceRegistryDependenciesV1(),
) -> dict[str, Any]:
    """Reload every official authority, live pin, and exact closure member."""
    root = _root(project_root)
    checked = _registry_shape(value)
    physical = _Closure(root)
    physical.add_many(checked["files"], "Q4 source registry physical closure")
    paths = _paths_from_registry(
        root=root, registry=checked, dependencies=dependencies,
    )
    expected, identity_inputs = _derive_registry(
        root=root, dependencies=dependencies, **paths,
    )
    _require(checked == expected, "Q4 source registry differs from official physical derivation")
    _require(
        physical.files() == checked["files"],
        "Q4 source registry physical closure normalization drifted",
    )
    return {"registry": checked, "identity_inputs": identity_inputs}


def load_backend_q4_two_phase_source_registry_v1(
    *, project_root: Path | str, registry_path: Path | str,
    dependencies: BackendQ4SourceRegistryDependenciesV1 = BackendQ4SourceRegistryDependenciesV1(),
) -> dict[str, Any]:
    root = _root(project_root)
    descriptor, value, _path = _load_path_json(
        root, registry_path, "Q4 two-phase source registry",
    )
    loaded = validate_backend_q4_two_phase_source_registry_v1(
        value, project_root=root, dependencies=dependencies,
    )
    return {**loaded, "source_registry": descriptor}


def _immutable_write(
    root: Path,
    output_path: Path | str,
    value: Mapping[str, Any],
    *,
    label: str,
    custody: PhysicalRootCustodyV1 | None = None,
) -> dict[str, Any]:
    payload = canonical_bytes(value, newline=True)
    owned = custody is None
    active = custody
    try:
        if active is None:
            active = PhysicalRootCustodyV1.open(
                root, label="Q4 source registry project_root"
            )
        return active.write_exclusive(
            output_path,
            payload,
            label=label,
            mode=0o444,
            create_parents=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            f"{label} immutable commit failed"
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
    destination = _under_root(
        root, output_path, label=label, must_exist=False
    )
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
        label=f"Q4 source registry {boundary} fault boundary"
    )
    mutation_watch = custody.begin_read_namespace_mutation_watch(
        list(watched_paths),
        label=f"Q4 source registry {boundary} fault boundary",
    )
    try:
        callback(boundary)
    except BaseException:
        if mutation_watch is not None:
            mutation_watch.close()
        raise
    custody.verify_pinned_directory_mutation_watch(
        mutation_watch,
        label=f"Q4 source registry {boundary} fault boundary",
    )
    custody.verify_pinned_directory_epochs(
        epochs,
        label=f"Q4 source registry {boundary} fault boundary",
    )


def _validate_result(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version", "artifact_kind", "status", "plan_sha256",
        "source_registry", "source_registry_sha256", "identity_inputs",
        "result_sha256",
    }
    _require(type(value) is dict and set(value) == fields, "Q4 source registry result fields drifted")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == RESULT_KIND
        and value.get("status") == "materialized_accepted_physical_q4_sources",
        "Q4 source registry result header drifted",
    )
    _sha(value.get("plan_sha256"), "Q4 source registry result plan")
    _descriptor(value.get("source_registry"), "Q4 source registry result")
    _sha(value.get("source_registry_sha256"), "Q4 source registry result semantic")
    _require(
        type(value.get("identity_inputs")) is dict
        and set(value["identity_inputs"]) == {
            "analytics_model_parity", "analytics_execution_layer",
            "policy_qualification", "resource_qualification",
        },
        "Q4 source registry result identity_inputs drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "result_sha256"}
    _require(value.get("result_sha256") == canonical_sha256(unsigned), "Q4 source registry result self-hash drifted")
    return copy.deepcopy(value)


def materialize_backend_q4_two_phase_source_registry_v1(
    *, project_root: Path | str, path_plan_path: Path | str,
    expected_plan_file_sha256: str, expected_plan_sha256: str,
    output_path: Path | str, result_output_path: Path | str,
    dependencies: BackendQ4SourceRegistryDependenciesV1 = BackendQ4SourceRegistryDependenciesV1(),
    after_artifact_commit: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Commit one immutable registry after all official/live checks succeed."""
    root = _root(project_root)
    try:
        with PhysicalRootCustodyV1.open(
            root, label="Q4 source registry project_root"
        ) as custody:
            token = _ACTIVE_PHYSICAL_CUSTODY.set(custody)
            try:
                return _materialize_backend_q4_two_phase_source_registry_v1(
                    root=root,
                    custody=custody,
                    path_plan_path=path_plan_path,
                    expected_plan_file_sha256=expected_plan_file_sha256,
                    expected_plan_sha256=expected_plan_sha256,
                    output_path=output_path,
                    result_output_path=result_output_path,
                    dependencies=dependencies,
                    after_artifact_commit=after_artifact_commit,
                )
            finally:
                _ACTIVE_PHYSICAL_CUSTODY.reset(token)
    except PublicationPhysicalIoV1Error as error:
        raise BackendQ4SourceRegistryV1Error(
            "Q4 source registry physical custody failed"
        ) from error


def _materialize_backend_q4_two_phase_source_registry_v1(
    *,
    root: Path,
    custody: PhysicalRootCustodyV1,
    path_plan_path: Path | str,
    expected_plan_file_sha256: str,
    expected_plan_sha256: str,
    output_path: Path | str,
    result_output_path: Path | str,
    dependencies: BackendQ4SourceRegistryDependenciesV1,
    after_artifact_commit: Callable[[str], None] | None,
) -> dict[str, Any]:
    registry_destination = _under_root(
        root,
        output_path,
        label="Q4 source registry output",
        must_exist=False,
    )
    result_destination = _under_root(
        root,
        result_output_path,
        label="Q4 source registry materialization result output",
        must_exist=False,
    )
    _require(
        registry_destination.as_posix().casefold()
        != result_destination.as_posix().casefold(),
        "Q4 source registry and result outputs alias",
    )
    registry_preexists = os.path.lexists(registry_destination)
    result_preexists = os.path.lexists(result_destination)
    _require(
        not result_preexists or registry_preexists,
        "Q4 source registry result exists without its causal registry",
    )
    plan_descriptor, raw_plan, _plan_path = _load_path_json(
        root, path_plan_path, "Q4 source path-plan",
    )
    _require(
        plan_descriptor["sha256"] == _sha(
            expected_plan_file_sha256, "expected Q4 source path-plan file",
        ),
        "Q4 source path-plan physical file pin drifted",
    )
    plan = validate_backend_q4_two_phase_source_registry_path_plan_v1(raw_plan)
    _require(
        plan["plan_sha256"] == _sha(expected_plan_sha256, "expected Q4 source path-plan semantic"),
        "Q4 source path-plan semantic pin drifted",
    )
    registry, identity_inputs = _derive_registry(
        root=root,
        model_parity_receipt_path=plan["model_parity_acceptance_receipt_path"],
        policy_receipt_path=plan["policy_qualification_receipt_path"],
        policy_capability_path=plan["policy_capability_manifest_path"],
        policy_calibration_path=plan["policy_calibration_mapping_path"],
        resource_receipt_path=plan["resource_qualification_receipt_path"],
        resource_capability_path=plan["resource_capability_manifest_path"],
        runtime_registry_path=plan["runtime_candidate_registry_path"],
        service_authority_path=plan["analytics_service_authority_path"],
        guardian_preprocessing_contract_path=plan[
            "guardian_preprocessing_contract_path"
        ],
        guardian_preprocessing_receipt_path=plan[
            "guardian_preprocessing_receipt_path"
        ],
        expected_analytics_service_identity_sha256=plan[
            "expected_analytics_service_identity_sha256"
        ],
        dependencies=dependencies,
    )
    registry_payload = canonical_bytes(registry, newline=True)
    source_descriptor = _transaction_descriptor(
        root,
        output_path,
        registry_payload,
        label="Q4 source registry output",
    )
    def registry_fault_step(step: str) -> None:
        _after_artifact_commit(
            after_artifact_commit,
            f"source_registry:{step}",
            custody=custody,
            watched_paths=[source_descriptor["path"]],
        )

    observed, registry_identity, registry_disposition = (
        custody.commit_or_adopt_exact_identity(
            source_descriptor["path"],
            registry_payload,
            label="Q4 source registry",
            mode=0o444,
            create_parents=True,
            after_publish_step=(
                registry_fault_step if after_artifact_commit is not None else None
            ),
        )
    )
    _require(
        observed == source_descriptor,
        "Q4 source registry committed/adopted descriptor drifted",
    )
    if registry_disposition == "published":
        _after_artifact_commit(
            after_artifact_commit,
            "source_registry",
            custody=custody,
            watched_paths=[source_descriptor["path"]],
        )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=source_descriptor,
        payload=registry_payload,
        label="pre-result Q4 source registry",
        expected_identity=registry_identity,
    )
    loaded = load_backend_q4_two_phase_source_registry_v1(
        project_root=root, registry_path=source_descriptor["path"],
        dependencies=dependencies,
    )
    _require(
        loaded["registry"] == registry
        and loaded["identity_inputs"] == identity_inputs
        and loaded["source_registry"] == source_descriptor,
        "Q4 source registry changed across immutable commit/reload",
    )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RESULT_KIND,
        "status": "materialized_accepted_physical_q4_sources",
        "plan_sha256": plan["plan_sha256"],
        "source_registry": source_descriptor,
        "source_registry_sha256": registry["registry_sha256"],
        "identity_inputs": identity_inputs,
    }
    result = _validate_result(
        {**unsigned, "result_sha256": canonical_sha256(unsigned)}
    )
    result_payload = canonical_bytes(result, newline=True)
    result_descriptor = _transaction_descriptor(
        root,
        result_output_path,
        result_payload,
        label="Q4 source registry materialization result output",
    )
    def result_fault_step(step: str) -> None:
        _after_artifact_commit(
            after_artifact_commit,
            f"source_registry_materialization_result:{step}",
            custody=custody,
            watched_paths=[source_descriptor["path"], result_descriptor["path"]],
        )

    observed, result_identity, result_disposition = (
        custody.commit_or_adopt_exact_identity(
            result_descriptor["path"],
            result_payload,
            label="Q4 source registry materialization result",
            mode=0o444,
            create_parents=True,
            after_publish_step=(
                result_fault_step if after_artifact_commit is not None else None
            ),
        )
    )
    _require(
        observed == result_descriptor,
        "Q4 source registry result committed/adopted descriptor drifted",
    )
    if result_disposition == "published":
        _after_artifact_commit(
            after_artifact_commit,
            "source_registry_materialization_result",
            custody=custody,
            watched_paths=[source_descriptor["path"], result_descriptor["path"]],
        )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=source_descriptor,
        payload=registry_payload,
        label="committed Q4 source registry",
        expected_identity=registry_identity,
    )
    _read_exact_transaction_leaf(
        custody=custody,
        descriptor=result_descriptor,
        payload=result_payload,
        label="committed Q4 source registry materialization result",
        expected_identity=result_identity,
    )
    observed_descriptor, observed_result, _observed_path = _load_path_json(
        root,
        result_descriptor["path"],
        "Q4 source registry materialization result",
    )
    _require(
        observed_descriptor == result_descriptor
        and _validate_result(observed_result) == result,
        "Q4 source registry result changed after receipt-last commit",
    )
    return result


def _parse_cli(argv: Sequence[str]) -> dict[str, str]:
    _require(type(argv) in {list, tuple} and len(argv) == len(_CLI_OPTIONS) * 2, "CLI argv arity drifted")
    result: dict[str, str] = {}
    for position, option in enumerate(_CLI_OPTIONS):
        observed = argv[position * 2]
        value = argv[position * 2 + 1]
        _require(observed == option, f"CLI argv option[{position}] drifted")
        _require(type(value) is str and bool(value), f"CLI argv value[{position}] is empty")
        result[option] = value
    return result


def run_cli(
    argv: Sequence[str], *,
    dependencies: BackendQ4SourceRegistryDependenciesV1 = BackendQ4SourceRegistryDependenciesV1(),
) -> int:
    try:
        arguments = _parse_cli(argv)
        result = materialize_backend_q4_two_phase_source_registry_v1(
            project_root=arguments["--project-root"],
            path_plan_path=arguments["--plan"],
            expected_plan_file_sha256=arguments["--plan-file-sha256"],
            expected_plan_sha256=arguments["--plan-sha256"],
            output_path=arguments["--output"],
            result_output_path=arguments["--result-output"],
            dependencies=dependencies,
        )
        payload = canonical_bytes(result, newline=True)
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(payload.decode("ascii"))
            sys.stdout.flush()
        return 0
    except BackendQ4SourceRegistryV1Error as error:
        sys.stderr.write(f"Q4 source registry rejected: {error}\n")
        sys.stderr.flush()
        return EXIT_REJECTED
    except Exception as error:
        sys.stderr.write(
            f"Q4 source registry rejected: {type(error).__name__}: {error}\n"
        )
        sys.stderr.flush()
        return EXIT_REJECTED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BackendQ4SourceRegistryDependenciesV1", "BackendQ4SourceRegistryV1Error",
    "CODECS", "IMAGE_ROLES", "PATH_PLAN_KIND", "POLICIES", "RESULT_KIND",
    "RUNTIME_FILE_ROLES_BY_SYSTEM", "SCHEMA_VERSION", "SOCKET_ROLES",
    "SOURCE_REGISTRY_KIND", "SYSTEMS", "TOPOLOGIES",
    "build_backend_q4_two_phase_source_registry_path_plan_v1",
    "canonical_bytes", "canonical_sha256",
    "load_backend_q4_two_phase_source_registry_v1", "main",
    "materialize_backend_q4_two_phase_source_registry_v1", "run_cli",
    "validate_backend_q4_two_phase_source_registry_path_plan_v1",
    "validate_backend_q4_two_phase_source_registry_v1",
]
