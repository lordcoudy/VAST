#!/usr/bin/env python3
"""Evidence-driven promotion of native policy capabilities and calibration.

The qualification index is only an inventory.  Proof is obtained by re-hashing
physical artifacts, re-validating accepted pilot bundles, and deriving the
capability/calibration outputs from native observations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import time
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping, Sequence

from checkpoint_qualification_pilot_acceptance_v1 import (
    QualificationPilotAcceptanceV1Error,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


QUALIFICATION_INDEX_SCHEMA_VERSION = 2
SUPPORTED_QUALIFICATION_INDEX_SCHEMA_VERSIONS = frozenset({2})
QUALIFICATION_ASSESSMENT_SCHEMA_VERSION = 1
QUALIFICATION_RECEIPT_SCHEMA_VERSION = 1
CAPABILITY_MANIFEST_FILENAME = "checkpoint_policy_capability_manifest.json"
CALIBRATION_MAPPING_FILENAME = "checkpoint_policy_calibration_mapping.json"
QUALIFICATION_RECEIPT_FILENAME = "checkpoint_policy_qualification_receipt.json"
_PROMOTION_FILE_SEQUENCE = (
    CAPABILITY_MANIFEST_FILENAME,
    CALIBRATION_MAPPING_FILENAME,
    QUALIFICATION_RECEIPT_FILENAME,
)
_IMMUTABLE_CONCURRENT_WAIT_SECONDS = 5.0
CODECS = ("h264", "h265")
KPP_DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
TOPOLOGIES = ("independent_processes", "shared_video_dag")
PILOT_EVIDENCE_ROLES = (
    "checkpoint_acceptance", "policy_decisions_jsonl", "resource_intervals",
    "ingress_ledger", "topology_events", "frames", "frame_events", "branch_terminals",
)
_SHA256_CHARS = frozenset("0123456789abcdef")
_RUNTIME_IDENTITY_FIELDS = {
    "runtime_backend", "device_api", "gpu_id", "worker_image_digest",
    "implementation_version", "terminal_detector", "terminal_backend",
}
_TERMINAL_BACKEND_PATTERNS = {
    "cpu": re.compile(
        r"^analytics-execution:openvino_cpu;runtime=[^;\r\n]+;"
        r"native_api=[^;\r\n]+;device=CPU:[^;\r\n]+$"
    ),
    "gpu": re.compile(
        r"^analytics-execution:tensorrt_cuda;runtime=[^;\r\n]+;"
        r"native_api=[^;\r\n]+;device=NVIDIA_CUDA:[^;\r\n]+$"
    ),
}


class QualificationError(RuntimeError):
    """A qualification input, evidence bundle, or immutable output is unsafe."""


PilotValidator = Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]
FragmentValidator = Callable[[str, Path, Path], dict[str, Any]]


def _load_execution_closure(**kwargs: Any) -> dict[str, Any]:
    from publication_policy_qualification_execution_closure_v1 import (
        load_publication_policy_qualification_execution_closure_v1,
    )

    return load_publication_policy_qualification_execution_closure_v1(**kwargs)


def _verify_execution_closure(root: Path, raw: Any) -> dict[str, Any]:
    verified = _verify_descriptor(
        root,
        raw,
        "qualification execution closure receipt",
        forbid_hardlinks=True,
    )
    descriptor = {
        key: verified[key] for key in ("path", "size_bytes", "sha256")
    }
    try:
        loaded = _load_execution_closure(
            project_root=root,
            receipt_path=root / descriptor["path"],
        )
    except QualificationError:
        raise
    except Exception as exc:
        raise QualificationError(
            f"qualification execution closure validation failed: {exc}"
        ) from exc
    receipt = loaded.get("receipt") if type(loaded) is dict else None
    pilot_execution = receipt.get("pilot_execution") if type(receipt) is dict else None
    if not (
        type(loaded) is dict
        and loaded.get("receipt_descriptor") == descriptor
        and type(receipt) is dict
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_execution_closure_v1"
        and receipt.get("status") == "qualification_execution_closed_nonpublication"
        and receipt.get("qualification_execution_complete") is True
        and receipt.get("accepted_for_full_publication") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and type(pilot_execution) is dict
        and type(pilot_execution.get("cells")) is list
        and len(pilot_execution["cells"]) == 32
    ):
        raise QualificationError("qualification execution closure identity drifted")
    return descriptor


def _load_policy_contract() -> Any:
    # Keep heavy benchmark dependencies lazy.  Fail-early evidence checks and
    # pure orchestration tests do not require pandas/PyYAML at import time.
    import publication_policy_contract as policy_contract

    return policy_contract


def _default_fragment_validator(
    system: str,
    fragment_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    if system == "deepstream":
        from checkpoint_deepstream_qualification_fragment_v1 import (
            validate_deepstream_qualification_fragment,
        )

        return validate_deepstream_qualification_fragment(
            project_root=project_root,
            fragment_path=fragment_path,
        )
    modules = {
        "savant": "checkpoint_savant_qualification_fragment_v3",
        "openvino_gva": "checkpoint_openvino_gva_qualification_fragment_v3",
        "gstreamer_custom": "checkpoint_gstreamer_custom_qualification_fragment_v3",
    }
    module_name = modules.get(system)
    if module_name is None:
        raise QualificationError(f"unsupported qualification fragment system: {system}")
    module = __import__(module_name, fromlist=["assess_qualification_fragment"])
    assessment = module.assess_qualification_fragment(
        project_root=project_root,
        fragment_path=fragment_path,
    )
    if type(assessment) is not dict or assessment.get("passed") is not True:
        blockers = assessment.get("blockers", []) if isinstance(assessment, dict) else []
        raise QualificationError(
            f"{system} qualification fragment rejected: "
            + ", ".join(str(value) for value in blockers[:8])
        )
    return _load_json_object(fragment_path, f"{system} qualification fragment")


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError("qualification artifact is not canonical JSON") from exc


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and set(text) <= _SHA256_CHARS


def _stable_id(value: Any) -> bool:
    text = str(value)
    return len(text) >= 8 and text == text.strip() and not any(ch in "\r\n\x00" for ch in text)


def _validate_runtime_identity(value: Any, *, key: tuple[str, str, str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _RUNTIME_IDENTITY_FIELDS:
        raise QualificationError(f"binding {key} runtime_identity fields drifted")
    string_fields = _RUNTIME_IDENTITY_FIELDS - {"device_api", "gpu_id"}
    if any(type(value[field]) is not str or not _stable_id(value[field]) for field in string_fields):
        raise QualificationError(f"binding {key} runtime_identity is incomplete")
    image = value["worker_image_digest"]
    if not image.startswith("sha256:") or not _valid_sha(image[7:]):
        raise QualificationError(f"binding {key} worker image digest is invalid")

    resource = key[2]
    device_api = value["device_api"]
    gpu_id = value["gpu_id"]
    terminal_backend = value["terminal_backend"]
    if resource == "cpu":
        if (
            device_api != "CPU"
            or gpu_id is not None
            or _TERMINAL_BACKEND_PATTERNS[resource].fullmatch(terminal_backend) is None
        ):
            raise QualificationError(f"binding {key} CPU runtime identity is inconsistent")
    elif resource == "gpu":
        if (
            device_api != "NVIDIA_CUDA"
            or type(gpu_id) is not int
            or gpu_id != 0
            or _TERMINAL_BACKEND_PATTERNS[resource].fullmatch(terminal_backend) is None
        ):
            raise QualificationError(f"binding {key} GPU runtime identity is inconsistent")
    else:  # pragma: no cover - the policy resource domain is checked before this helper
        raise QualificationError(f"binding {key} runtime resource is unsupported")
    return dict(value)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise QualificationError(f"{label} must be a JSON object")
    return value


def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise QualificationError(f"artifact stat failed: {path}: {exc}") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _resolve_relative_regular_file(project_root: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise QualificationError(f"{label} path must be a non-empty POSIX relative path")
    relative = Path(value)
    if relative.is_absolute() or value != relative.as_posix() or any(part in ("", ".", "..") for part in relative.parts):
        raise QualificationError(f"{label} path escapes or is not normalized: {value!r}")
    root = project_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_reparse_or_link(cursor):
            raise QualificationError(f"{label} path contains a symlink/reparse point: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"{label} path escapes project root: {value}") from exc
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise QualificationError(f"{label} is not a regular file: {value}")
    return candidate


def _verify_descriptor(project_root: Path, descriptor: Any, label: str, *, forbid_hardlinks: bool) -> dict[str, Any]:
    if type(descriptor) is not dict or set(descriptor) != {"path", "size_bytes", "sha256"}:
        raise QualificationError(f"{label} artifact descriptor fields drifted")
    expected_size = descriptor.get("size_bytes")
    expected_sha = descriptor.get("sha256")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
        raise QualificationError(f"{label} artifact size is invalid")
    if not _valid_sha(expected_sha):
        raise QualificationError(f"{label} artifact SHA-256 is invalid")
    path = _resolve_relative_regular_file(project_root, descriptor.get("path"), label)
    before = path.stat()
    if forbid_hardlinks and int(before.st_nlink) != 1:
        raise QualificationError(f"{label} hardlink alias is prohibited")
    digest = _sha256_file(path)
    after = path.stat()
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, int(getattr(before, "st_ctime_ns", 0)))
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, int(getattr(after, "st_ctime_ns", 0)))
    if before_id != after_id:
        raise QualificationError(f"{label} artifact changed while hashing")
    if before.st_size != expected_size or digest != expected_sha:
        raise QualificationError(f"{label} artifact size/SHA drift")
    return {
        "path": descriptor["path"], "size_bytes": expected_size, "sha256": digest,
        "filesystem_identity": (int(before.st_dev), int(before.st_ino)),
    }


def _binding_key(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(value.get("system", "")), str(value.get("branch", "")), str(value.get("resource", "")))


def _pilot_key(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (str(value.get("system", "")), str(value.get("resource", "")), str(value.get("codec", "")), str(value.get("topology_kind", "")))


def _derive_manifest(bindings: Sequence[Any], *, project_root: Path, policy: Any) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
    branches = tuple(policy.ANALYTICS_BRANCHES)
    resources = tuple(policy.RESOURCES)
    expected = {(system, branch, resource) for system in systems for branch in branches for resource in resources}
    if not isinstance(bindings, list) or len(bindings) != len(expected):
        raise QualificationError("binding set must contain exactly 32 system/branch/resource rows")
    observed: dict[tuple[str, str, str], dict[str, Any]] = {}
    path_aliases: set[str] = set()
    inode_aliases: set[tuple[int, int]] = set()
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()
    for position, raw in enumerate(bindings):
        if type(raw) is not dict:
            raise QualificationError(f"binding[{position}] must be an object")
        required = {
            "system", "branch", "resource", "implementation_id", "implementation_artifact",
            "emitter_id", "emitter_artifact", "runtime_binding", "runtime_identity",
        }
        if set(raw) != required:
            raise QualificationError(f"binding[{position}] fields drifted")
        key = _binding_key(raw)
        if key not in expected or key in observed:
            raise QualificationError(f"binding coverage duplicate/unknown: {key}")
        implementation_id = str(raw["implementation_id"])
        emitter_id = str(raw["emitter_id"])
        runtime_binding = str(raw["runtime_binding"])
        if not all(_stable_id(value) for value in (implementation_id, emitter_id, runtime_binding)):
            raise QualificationError(f"binding {key} contains a placeholder/unstable runtime identity")
        if implementation_id in implementation_ids or emitter_id in emitter_ids:
            raise QualificationError(f"binding {key} implementation/emitter identity is not unique")
        implementation_ids.add(implementation_id)
        emitter_ids.add(emitter_id)
        runtime_identity = _validate_runtime_identity(raw["runtime_identity"], key=key)
        artifacts = []
        for role in ("implementation_artifact", "emitter_artifact"):
            verified = _verify_descriptor(project_root, raw[role], f"binding {key} {role}", forbid_hardlinks=True)
            if verified["path"] in path_aliases or verified["filesystem_identity"] in inode_aliases:
                raise QualificationError(f"binding {key} artifact alias is prohibited")
            path_aliases.add(verified["path"])
            inode_aliases.add(verified["filesystem_identity"])
            artifacts.append(verified)
        implementation, emitter = artifacts
        observed[key] = {
            "status": "implemented_and_native_evidence_bound",
            "implementation_id": implementation_id,
            "implementation_sha256": implementation["sha256"],
            "runtime_binding": runtime_binding,
            "runtime_identity": runtime_identity,
            **runtime_identity,
            "native_evidence": {
                "status": "accepted_native_runtime_emitter",
                "telemetry_source": "native",
                "emitter_id": emitter_id,
                "emitter_sha256": emitter["sha256"],
                "implementation_id_field": "implementation_id",
                "resource_field": "selected_resource",
            },
        }
    if set(observed) != expected:
        raise QualificationError("binding_cell_set_mismatch")
    manifest = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_capability_manifest",
        "policy_scope": policy.POLICY_SCOPE,
        "policy_contract_sha256": policy.policy_contract_identity()["sha256"],
        "systems": {
            system: {"branches": {
                branch: {resource: observed[(system, branch, resource)] for resource in resources}
                for branch in branches
            }} for system in systems
        },
    }
    assessment = policy.assess_capability_manifest(manifest)
    if not assessment.get("passed"):
        raise QualificationError("derived capability manifest rejected: " + ", ".join(assessment.get("blockers", [])[:8]))
    return manifest, observed


def _derive_fragment_bound_manifest(
    bindings: Sequence[Any],
    *,
    project_root: Path,
    policy: Any,
    fragment_validator: FragmentValidator,
) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
    branches = tuple(policy.ANALYTICS_BRANCHES)
    resources = tuple(policy.RESOURCES)
    expected = {
        (system, branch, resource)
        for system in systems
        for branch in branches
        for resource in resources
    }
    if not isinstance(bindings, list) or len(bindings) != len(expected):
        raise QualificationError("binding set must contain exactly 32 system/branch/resource rows")

    required = {
        "system",
        "branch",
        "resource",
        "implementation_id",
        "emitter_id",
        "binding_artifact",
        "fragment_artifact",
        "runtime_binding",
        "runtime_identity",
    }
    raw_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    verified_bindings: dict[tuple[str, str, str], dict[str, Any]] = {}
    fragments: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    binding_paths: set[str] = set()
    binding_inodes: set[tuple[int, int]] = set()
    fragment_paths: set[str] = set()
    fragment_inodes: set[tuple[int, int]] = set()
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()

    for position, raw in enumerate(bindings):
        if type(raw) is not dict or set(raw) != required:
            raise QualificationError(f"binding[{position}] fragment-bound fields drifted")
        key = _binding_key(raw)
        if key not in expected or key in raw_by_key:
            raise QualificationError(f"binding coverage duplicate/unknown: {key}")
        implementation_id = str(raw["implementation_id"])
        emitter_id = str(raw["emitter_id"])
        runtime_binding = str(raw["runtime_binding"])
        if not all(_stable_id(value) for value in (implementation_id, emitter_id, runtime_binding)):
            raise QualificationError(f"binding {key} contains a placeholder/unstable runtime identity")
        if implementation_id in implementation_ids or emitter_id in emitter_ids:
            raise QualificationError(f"binding {key} implementation/emitter identity is not unique")
        implementation_ids.add(implementation_id)
        emitter_ids.add(emitter_id)
        runtime_identity = _validate_runtime_identity(raw["runtime_identity"], key=key)
        binding_artifact = _verify_descriptor(
            project_root,
            raw["binding_artifact"],
            f"binding {key} physical binding",
            forbid_hardlinks=True,
        )
        if (
            binding_artifact["path"] in binding_paths
            or binding_artifact["filesystem_identity"] in binding_inodes
        ):
            raise QualificationError(f"binding {key} physical binding alias is prohibited")
        binding_paths.add(binding_artifact["path"])
        binding_inodes.add(binding_artifact["filesystem_identity"])
        expected_runtime_binding = (
            f"{key[0]}:{key[1]}:{key[2]}:fragment-v1:{binding_artifact['sha256']}"
        )
        if runtime_binding != expected_runtime_binding:
            raise QualificationError(f"binding {key} runtime_binding is not fragment-derived")

        fragment_artifact = _verify_descriptor(
            project_root,
            raw["fragment_artifact"],
            f"binding {key} system fragment",
            forbid_hardlinks=True,
        )
        prior = fragments.get(key[0])
        fragment_descriptor = {
            field: fragment_artifact[field]
            for field in ("path", "size_bytes", "sha256", "filesystem_identity")
        }
        if prior is None:
            if (
                fragment_artifact["path"] in fragment_paths
                or fragment_artifact["filesystem_identity"] in fragment_inodes
            ):
                raise QualificationError(f"binding {key} system fragment alias is prohibited")
            fragment_paths.add(fragment_artifact["path"])
            fragment_inodes.add(fragment_artifact["filesystem_identity"])
            fragment_path = project_root / fragment_artifact["path"]
            fragment_value = fragment_validator(key[0], fragment_path, project_root)
            if type(fragment_value) is not dict:
                raise QualificationError(f"{key[0]} qualification fragment validator returned invalid data")
            fragments[key[0]] = (fragment_descriptor, fragment_value)
        elif prior[0] != fragment_descriptor:
            raise QualificationError(f"binding {key} system fragment descriptor drifted")

        raw_by_key[key] = raw
        verified_bindings[key] = {
            "artifact": binding_artifact,
            "runtime_identity": runtime_identity,
            "runtime_binding": runtime_binding,
            "implementation_id": implementation_id,
            "emitter_id": emitter_id,
        }

    if set(raw_by_key) != expected or set(fragments) != set(systems):
        raise QualificationError("binding_cell_set_mismatch")

    observed: dict[tuple[str, str, str], dict[str, Any]] = {}
    expected_fragment_fields = {
        "schema_version",
        "artifact_kind",
        "system",
        "policy_bindings",
        "resource_bindings",
        "pilots",
    }
    for system in systems:
        fragment = fragments[system][1]
        if (
            set(fragment) != expected_fragment_fields
            or fragment.get("schema_version") != 1
            or fragment.get("artifact_kind")
            != "vast_publication_qualification_system_fragment_v1"
            or fragment.get("system") != system
        ):
            raise QualificationError(f"{system} qualification fragment identity drifted")
        rows = fragment.get("policy_bindings")
        if type(rows) is not list or len(rows) != len(branches) * len(resources):
            raise QualificationError(f"{system} qualification fragment policy coverage drifted")
        rows_by_coordinate: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if type(row) is not dict:
                raise QualificationError(f"{system} qualification fragment policy row invalid")
            coordinate = (str(row.get("branch", "")), str(row.get("resource", "")))
            if coordinate in rows_by_coordinate:
                raise QualificationError(f"{system} qualification fragment policy row duplicate")
            rows_by_coordinate[coordinate] = row
        if set(rows_by_coordinate) != {(branch, resource) for branch in branches for resource in resources}:
            raise QualificationError(f"{system} qualification fragment policy coverage drifted")

        for branch in branches:
            for resource in resources:
                key = (system, branch, resource)
                verified = verified_bindings[key]
                artifact = verified["artifact"]
                fragment_row = rows_by_coordinate[(branch, resource)]
                if not all(
                    (
                        fragment_row.get("role") == "policy",
                        fragment_row.get("branch") == branch,
                        fragment_row.get("resource") == resource,
                        fragment_row.get("path") == artifact["path"],
                        fragment_row.get("size") == artifact["size_bytes"],
                        fragment_row.get("sha256") == artifact["sha256"],
                        fragment_row.get("implementation_id") == verified["implementation_id"],
                        fragment_row.get("emitter_id") == verified["emitter_id"],
                        fragment_row.get("runtime_identity") == verified["runtime_identity"],
                    )
                ):
                    raise QualificationError(f"binding {key} fragment policy binding drift")
                identity = verified["runtime_identity"]
                observed[key] = {
                    "status": "implemented_and_native_evidence_bound",
                    "implementation_id": verified["implementation_id"],
                    "implementation_sha256": artifact["sha256"],
                    "runtime_binding": verified["runtime_binding"],
                    "runtime_identity": identity,
                    **identity,
                    "native_evidence": {
                        "status": "accepted_native_runtime_emitter",
                        "telemetry_source": "native",
                        "emitter_id": verified["emitter_id"],
                        "emitter_sha256": artifact["sha256"],
                        "implementation_id_field": "implementation_id",
                        "resource_field": "selected_resource",
                    },
                }

    manifest = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_capability_manifest",
        "policy_scope": policy.POLICY_SCOPE,
        "policy_contract_sha256": policy.policy_contract_identity()["sha256"],
        "systems": {
            system: {
                "branches": {
                    branch: {
                        resource: observed[(system, branch, resource)]
                        for resource in resources
                    }
                    for branch in branches
                }
            }
            for system in systems
        },
    }
    assessment = policy.assess_capability_manifest(manifest)
    if not assessment.get("passed"):
        raise QualificationError(
            "derived capability manifest rejected: "
            + ", ".join(assessment.get("blockers", [])[:8])
        )
    return manifest, observed


def _validate_evidence_descriptors(project_root: Path, pilot: Mapping[str, Any]) -> dict[str, Path]:
    evidence = pilot.get("evidence")
    if type(evidence) is not dict or set(evidence) != set(PILOT_EVIDENCE_ROLES):
        raise QualificationError("pilot raw evidence descriptor set drifted")
    verified: dict[str, Path] = {}
    paths: set[str] = set()
    inodes: set[tuple[int, int]] = set()
    for role in PILOT_EVIDENCE_ROLES:
        descriptor = _verify_descriptor(project_root, evidence[role], f"pilot {role}", forbid_hardlinks=True)
        if descriptor["path"] in paths or descriptor["filesystem_identity"] in inodes:
            raise QualificationError(f"pilot evidence alias is prohibited: {role}")
        paths.add(descriptor["path"])
        inodes.add(descriptor["filesystem_identity"])
        verified[role] = project_root / descriptor["path"]
    parents = {path.parent.resolve(strict=True) for path in verified.values()}
    if len(parents) != 1:
        raise QualificationError("pilot evidence files must share one accepted arm directory")
    return verified


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for number, line in enumerate(source, start=1):
                if not line.strip():
                    raise QualificationError(f"{path}:{number}: blank JSONL records are prohibited")
                value = json.loads(line)
                if type(value) is not dict:
                    raise QualificationError(f"{path}:{number}: decision record must be an object")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid native decision JSONL: {exc}") from exc
    if not records:
        raise QualificationError("native decision JSONL is empty")
    return records


def _default_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    project_root = Path(context["project_root"])
    manifest = context["capability_manifest"]
    policy = context["policy"]
    paths = _validate_evidence_descriptors(project_root, pilot)
    expected_identity = {
        "policy": "cpu_only" if pilot["resource"] == "cpu" else "gpu_only",
    }
    try:
        acceptance = validate_checkpoint_qualification_pilot_acceptance_v1(
            project_root=project_root,
            acceptance_path=paths["checkpoint_acceptance"],
            expected_system=pilot["system"],
            expected_resource=pilot["resource"],
            expected_codec=pilot["codec"],
            expected_topology_kind=pilot["topology_kind"],
        )
    except QualificationPilotAcceptanceV1Error as exc:
        raise QualificationError(
            f"checkpoint acceptance is not a qualification pilot: {exc}"
        ) from exc
    run_id = acceptance.get("run_id")
    if not _stable_id(run_id):
        raise QualificationError("checkpoint acceptance run_id is invalid")
    expected_scenario = (
        "checkpoint_independent_processes_baseline"
        if pilot["topology_kind"] == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    if acceptance.get("scenario") != expected_scenario:
        raise QualificationError("checkpoint acceptance scenario/topology mismatch")
    evidence_hashes = acceptance.get("evidence_sha256")
    if type(evidence_hashes) is not dict:
        raise QualificationError("checkpoint acceptance evidence hashes are missing")
    from publication_acceptance_evidence import accepted_arm_evidence_files

    required_acceptance_files = set(
        accepted_arm_evidence_files(
            expected_identity["policy"],
            full_resource=True,
        )
    )
    if set(evidence_hashes) != required_acceptance_files:
        raise QualificationError("checkpoint acceptance evidence hash set drifted")
    arm_root = paths["checkpoint_acceptance"].parent
    for filename, expected_sha in evidence_hashes.items():
        if type(filename) is not str or Path(filename).name != filename or not _valid_sha(expected_sha):
            raise QualificationError("checkpoint acceptance contains an unsafe evidence identity")
        current = arm_root / filename
        try:
            relative = current.relative_to(project_root).as_posix()
            size = current.stat().st_size
        except (OSError, ValueError) as exc:
            raise QualificationError(f"checkpoint acceptance evidence is missing: {filename}") from exc
        _verify_descriptor(
            project_root,
            {"path": relative, "size_bytes": size, "sha256": expected_sha},
            f"checkpoint acceptance {filename}",
            forbid_hardlinks=True,
        )
    acceptance_roles = {
        "resource_intervals": "resource_intervals.csv",
        "ingress_ledger": "ingress_ledger.csv",
        "topology_events": "topology_events.csv",
        "frames": "frames.csv",
        "frame_events": "frame_events.csv",
        "branch_terminals": "branch_terminals.csv",
    }
    for role, filename in acceptance_roles.items():
        if paths[role].name != filename or evidence_hashes.get(filename) != _sha256_file(paths[role]):
            raise QualificationError(f"checkpoint acceptance does not bind current {filename}")
    summary = acceptance.get("full_resource_summary")
    if type(summary) is not dict or not all(
        summary.get(field) is True
        for field in ("evidence_accepted", "publication_bundle_bound", "full_resource_coverage_complete")
    ):
        raise QualificationError("checkpoint acceptance full-resource proof is not accepted")
    finalization = acceptance.get("full_resource_finalization")
    if finalization != {
        "hardware_collector_stopped": True,
        "validation": "full_resource_evidence_v2_passed",
        "prepared_by": "prepare_checkpoint_publication_acceptance",
    }:
        raise QualificationError("checkpoint acceptance finalization proof drifted")

    # Re-run complete sidecar validators; receipt hashes alone are not proof.
    try:
        from benchmark_contract import (
            canonicalize_frames_csv, load_dataset, validate_frame_events,
            validate_required_sidecars,
        )
        from topology_contract import validate_topology_events

        frames = canonicalize_frames_csv(paths["frames"], mode="benchmark", run_id="", detector="", backend="")
        frame_events = validate_frame_events(paths["frame_events"])
        scenario = {
            "name": expected_scenario,
            "workload": {
                "routing_mode": "all_branches_per_stream",
                "analytics_function_types": len(policy.ANALYTICS_BRANCHES),
            },
            "topology": {
                "contract_version": 2,
                "kind": pilot["topology_kind"],
                "routing_mode": "all_branches_per_stream",
                "required_branches": list(policy.ANALYTICS_BRANCHES),
            },
        }
        topology_events = validate_topology_events(
            paths["topology_events"], frames=frames, frame_events=frame_events, scenario=scenario,
        )
        sidecars = validate_required_sidecars(
            paths["frames"].parent,
            require_labeled_provenance=True,
            require_full_policy_trace=True,
            require_causal_policy_trace=True,
            require_ingress_ledger=True,
            require_branch_terminals=True,
            required_branches=list(policy.ANALYTICS_BRANCHES),
            topology_kind=pilot["topology_kind"],
            require_full_resource_evidence=True,
            expected_run_id=str(run_id),
            frames=frames,
            topology_events=topology_events,
        )
        dataset_manifest = project_root / context["dataset_manifest"]["path"]
        dataset = load_dataset(
            dataset_manifest,
            KPP_DATASET_BY_CODEC[pilot["codec"]],
            mode="benchmark",
            project_root=project_root,
            require_files=True,
        )
        expected_sources = {str(stream["resolved_sha256"]) for stream in dataset["streams"]}
        observed_sources = set(sidecars["ingress_ledger"]["source_sha256"].astype(str))
        if observed_sources != expected_sources:
            raise QualificationError("pilot ingress is not bound to the frozen KPP codec dataset")
    except QualificationError:
        raise
    except Exception as exc:
        raise QualificationError(f"pilot sidecar revalidation failed: {exc}") from exc

    decisions = _read_jsonl(paths["policy_decisions_jsonl"])
    policy_rows = sidecars["policy_decisions"]
    intervals = sidecars["resource_intervals"]
    terminals = sidecars["branch_terminals"]
    policy_by_decision = {str(row["decision_id"]): row for row in policy_rows.to_dict(orient="records")}
    if len(policy_by_decision) != len(policy_rows):
        raise QualificationError("policy_decisions.csv contains duplicate decision_id")
    terminal_keys = {
        (str(row["trace_id"]), str(row["branch_id"]))
        for row in terminals.to_dict(orient="records")
        if str(row["terminal_status"]) == "completed"
    }
    transfer_by_key: dict[tuple[str, str], float] = defaultdict(float)
    for row in intervals.to_dict(orient="records"):
        if str(row["component"]) == "transfer":
            transfer_by_key[(str(row["trace_id"]), str(row["branch_id"]))] += float(row["duration_ns"]) / 1_000_000.0

    samples = []
    seen_decisions: set[str] = set()
    seen_events: set[str] = set()
    for record in decisions:
        decision_id = str(record.get("decision_id", ""))
        trace_id = str(record.get("trace_id", ""))
        branch = str(record.get("branch", ""))
        resource = str(record.get("selected_resource", ""))
        assessment = policy.validate_decision_record(record, manifest)
        if not assessment.get("passed"):
            raise QualificationError("accepted native decision replay failed: " + ", ".join(assessment.get("blockers", [])[:6]))
        if record.get("system") != pilot["system"] or resource != pilot["resource"] or branch not in policy.ANALYTICS_BRANCHES:
            raise QualificationError("native decision does not belong to the declared pilot cell")
        evidence = record.get("native_decision_evidence")
        if type(evidence) is not dict:
            raise QualificationError("native decision evidence is missing")
        event_id = str(evidence.get("event_id", ""))
        if decision_id in seen_decisions or event_id in seen_events:
            raise QualificationError("duplicate native decision/event sample")
        seen_decisions.add(decision_id)
        seen_events.add(event_id)
        row = policy_by_decision.get(decision_id)
        if row is None or str(row["trace_id"]) != trace_id or str(row["stage"]) != branch or str(row["resource"]) != resource:
            raise QualificationError("native decision JSONL/CSV linkage mismatch")
        if (trace_id, branch) not in terminal_keys:
            raise QualificationError("native decision lacks accepted branch terminal linkage")
        service_ms = evidence.get("actual_service_ms")
        if isinstance(service_ms, bool) or not isinstance(service_ms, (int, float)) or not math.isfinite(float(service_ms)) or float(service_ms) <= 0:
            raise QualificationError("native decision actual_service_ms is invalid")
        transfer_ms = transfer_by_key.get((trace_id, branch), 0.0)
        if resource == "gpu" and transfer_ms <= 0:
            raise QualificationError("GPU qualification sample lacks native transfer interval")
        samples.append({
            "system": pilot["system"], "resource": resource, "codec": pilot["codec"],
            "topology_kind": pilot["topology_kind"], "branch": branch,
            "decision_id": decision_id, "trace_id": trace_id,
            "service_ms": float(service_ms), "transfer_ms": float(transfer_ms),
        })
    return samples


def _validate_samples(
    rows: Any,
    *,
    pilot_key: tuple[str, str, str, str],
    branches: Sequence[str],
    minimum_samples: int,
    global_decisions: set[str],
    global_traces: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise QualificationError(f"pilot {pilot_key} validator did not return a sample list")
    expected_fields = {
        "system", "resource", "codec", "topology_kind", "branch",
        "decision_id", "trace_id", "service_ms", "transfer_ms",
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position, row in enumerate(rows):
        if type(row) is not dict or set(row) != expected_fields:
            raise QualificationError(f"pilot {pilot_key} sample[{position}] fields drifted")
        if (row["system"], row["resource"], row["codec"], row["topology_kind"]) != pilot_key:
            raise QualificationError(f"pilot {pilot_key} sample escaped its cell")
        branch = str(row["branch"])
        decision_id = str(row["decision_id"])
        trace_id = str(row["trace_id"])
        if branch not in branches or not _stable_id(decision_id) or not _stable_id(trace_id):
            raise QualificationError(f"pilot {pilot_key} sample identity is invalid")
        trace_key = (pilot_key[0], trace_id, branch)
        if decision_id in global_decisions or trace_key in global_traces:
            raise QualificationError(f"pilot {pilot_key} contains duplicate decision/trace sample")
        global_decisions.add(decision_id)
        global_traces.add(trace_key)
        for field, positive in (("service_ms", True), ("transfer_ms", False)):
            value = row[field]
            invalid = (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                or (positive and float(value) <= 0)
            )
            if invalid:
                raise QualificationError(f"pilot {pilot_key} sample {field} is invalid")
        grouped[branch].append(dict(row))
    if set(grouped) != set(branches):
        raise QualificationError(f"pilot {pilot_key} branch coverage mismatch")
    for branch in branches:
        if len(grouped[branch]) < minimum_samples:
            raise QualificationError(f"pilot {pilot_key}/{branch} requires at least {minimum_samples} accepted samples")
    return [row for branch in branches for row in grouped[branch]]


def _assessment_failure(blockers: list[str], *, index_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_policy_qualification_assessment",
        "passed": False,
        "status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "index_sha256": index_sha,
        "coverage": {"binding_count": 0, "pilot_cell_count": 0, "accepted_sample_count": 0},
        "capability_manifest": None,
        "calibration_mapping": None,
    }


def assess_policy_qualification(
    *,
    project_root: Path,
    index_path: Path,
    pilot_validator: PilotValidator | None = None,
    fragment_validator: FragmentValidator | None = None,
) -> dict[str, Any]:
    """Purely assess and derive qualification artifacts; never write output."""
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir() or _is_reparse_or_link(root):
            raise QualificationError("project_root must be a physical non-reparse directory")
        index_candidate = Path(index_path)
        if index_candidate.is_absolute():
            try:
                relative_index = index_candidate.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise QualificationError("qualification index must remain under project_root") from exc
        else:
            relative_index = index_candidate.as_posix()
        index_file = _resolve_relative_regular_file(root, relative_index, "qualification index")
        index_sha = _sha256_file(index_file)
        index = _load_json_object(index_file, "qualification index")
        base_fields = {
            "schema_version", "artifact_kind", "policy_contract_sha256",
            "dataset_manifest", "bindings", "pilots",
        }
        pilots_value = index.get("pilots")
        requires_execution_closure = (
            isinstance(pilots_value, list) and bool(pilots_value)
        )
        expected_fields = (
            base_fields | {"qualification_execution_closure"}
            if requires_execution_closure
            else base_fields
        )
        schema_ok = (
            set(index) == expected_fields
            and index.get("schema_version")
            in SUPPORTED_QUALIFICATION_INDEX_SCHEMA_VERSIONS
            and index.get("artifact_kind") == "vast_publication_policy_qualification_index"
        )
        if not schema_ok:
            raise QualificationError("qualification index schema/fields drifted")
        policy = _load_policy_contract()
        contract_sha = policy.policy_contract_identity()["sha256"]
        if index.get("policy_contract_sha256") != contract_sha:
            raise QualificationError("qualification index policy contract SHA-256 drifted")
        execution_closure = (
            _verify_execution_closure(
                root, index["qualification_execution_closure"]
            )
            if requires_execution_closure
            else None
        )
        dataset = _verify_descriptor(root, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
        if index["schema_version"] == 1:
            manifest, bindings = _derive_manifest(
                index["bindings"], project_root=root, policy=policy,
            )
        else:
            manifest, bindings = _derive_fragment_bound_manifest(
                index["bindings"],
                project_root=root,
                policy=policy,
                fragment_validator=(
                    fragment_validator or _default_fragment_validator
                ),
            )
        expected_pilots = {
            (system, resource, codec, topology)
            for system in policy.PUBLISHABLE_SYSTEMS
            for resource in policy.RESOURCES
            for codec in CODECS
            for topology in TOPOLOGIES
        }
        pilots = index["pilots"]
        if not isinstance(pilots, list) or len(pilots) != len(expected_pilots):
            raise QualificationError("pilot_cell_set_mismatch: expected exactly 32 pilots")
        by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for position, raw in enumerate(pilots):
            if type(raw) is not dict or set(raw) != {"system", "resource", "codec", "topology_kind", "evidence"}:
                raise QualificationError(f"pilot[{position}] fields drifted")
            key = _pilot_key(raw)
            if key not in expected_pilots or key in by_key:
                raise QualificationError(f"pilot_cell_set_mismatch: duplicate/unknown {key}")
            by_key[key] = raw
        if set(by_key) != expected_pilots:
            raise QualificationError("pilot_cell_set_mismatch")
        validator = pilot_validator or _default_pilot_validator
        samples: list[dict[str, Any]] = []
        global_decisions: set[str] = set()
        global_traces: set[tuple[str, str, str]] = set()
        for key in sorted(expected_pilots):
            raw_rows = validator(by_key[key], {
                "project_root": root,
                "policy": policy,
                "capability_manifest": manifest,
                "bindings": bindings,
                "dataset_manifest": dataset,
            })
            samples.extend(_validate_samples(
                raw_rows,
                pilot_key=key,
                branches=tuple(policy.ANALYTICS_BRANCHES),
                minimum_samples=int(policy.MIN_CALIBRATION_SAMPLES),
                global_decisions=global_decisions,
                global_traces=global_traces,
            ))
        calibrations: dict[str, Any] = {}
        for system in policy.PUBLISHABLE_SYSTEMS:
            costs = {}
            for branch in policy.ANALYTICS_BRANCHES:
                costs[branch] = {}
                for resource in policy.RESOURCES:
                    selected = [
                        row for row in samples
                        if row["system"] == system and row["branch"] == branch and row["resource"] == resource
                    ]
                    balanced_minimum = len(CODECS) * len(TOPOLOGIES) * int(policy.MIN_CALIBRATION_SAMPLES)
                    if len(selected) < balanced_minimum:
                        raise QualificationError(f"calibration coverage below balanced minimum: {system}/{branch}/{resource}")
                    costs[branch][resource] = {
                        "implementation_id": bindings[(system, branch, resource)]["implementation_id"],
                        "service_ms": float(median(row["service_ms"] for row in selected)),
                        "transfer_ms": float(median(row["transfer_ms"] for row in selected)),
                        "samples": len(selected),
                    }
            calibrations[system] = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": contract_sha,
                "costs": costs,
            }
        calibration_mapping = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration_mapping",
            "policy_contract_sha256": contract_sha,
            "aggregation_rule": "median_of_balanced_native_codec_topology_cells_v1",
            "minimum_samples_per_branch_cell": int(policy.MIN_CALIBRATION_SAMPLES),
            "calibrations": calibrations,
        }
        return {
            "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
            "artifact_kind": "vast_publication_policy_qualification_assessment",
            "passed": True,
            "status": "ready_for_atomic_promotion",
            "blockers": [],
            "index_sha256": index_sha,
            "dataset_manifest_sha256": dataset["sha256"],
            "qualification_execution_closure": execution_closure,
            "coverage": {
                "binding_count": len(bindings),
                "pilot_cell_count": len(by_key),
                "accepted_sample_count": len(samples),
                "minimum_samples_per_branch_cell": int(policy.MIN_CALIBRATION_SAMPLES),
            },
            "capability_manifest": manifest,
            "calibration_mapping": calibration_mapping,
        }
    except QualificationError as exc:
        return _assessment_failure([str(exc)], index_sha=locals().get("index_sha"))
    except Exception as exc:
        return _assessment_failure([f"qualification validation failed closed: {exc}"], index_sha=locals().get("index_sha"))


def _write_immutable_json(
    path: Path,
    value: dict[str, Any],
    *,
    custody: PhysicalRootCustodyV1 | None = None,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Durably publish or adopt one exact immutable JSON leaf."""

    payload = _canonical_bytes(value) + b"\n"
    owned_custody: PhysicalRootCustodyV1 | None = None
    try:
        holder = custody
        if holder is None:
            owned_custody = PhysicalRootCustodyV1.open(
                path.parent, label="qualification output parent"
            )
            holder = owned_custody
        relative = path.relative_to(holder.root).as_posix()
        expected = {
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

        def physical_step(step: str) -> None:
            if after_physical_commit_step is not None:
                after_physical_commit_step(step, path)

        observed, identity, disposition = holder.commit_or_adopt_exact_identity(
            relative,
            payload,
            label=f"immutable qualification output {path.name}",
            mode=0o444,
            create_parents=False,
            after_publish_step=physical_step,
        )
        cold, observed_payload, observed_identity = holder.read_descriptor_identity(
            relative,
            label=f"immutable qualification output {path.name}",
            maximum=len(payload),
            capture=True,
        )
        observed_mode, stat_identity = holder.stat_regular_identity(
            relative, label=f"immutable qualification output {path.name}"
        )
        if (
            disposition not in {"published", "adopted"}
            or observed != expected
            or cold != expected
            or observed_payload != payload
            or observed_identity != identity
            or stat_identity != identity
            or observed_mode != 0o444
        ):
            raise QualificationError(
                f"immutable qualification output collision: {path.name}"
            )
        return {
            "path": path.name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    except QualificationError:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise QualificationError(
            f"immutable qualification output collision: {path.name}"
        ) from error
    finally:
        if owned_custody is not None:
            owned_custody.close()


def _require_promotion_namespace(
    custody: PhysicalRootCustodyV1,
    destination: Path,
    *,
    complete: bool,
) -> None:
    try:
        names = set(
            custody.list_directory_names(
                destination, label="policy qualification output namespace"
            )
        )
    except PublicationPhysicalIoV1Error as error:
        raise QualificationError(
            "policy qualification output namespace is unsafe"
        ) from error
    allowed_prefixes = {
        frozenset(_PROMOTION_FILE_SEQUENCE[:length])
        for length in range(len(_PROMOTION_FILE_SEQUENCE) + 1)
    }
    if complete:
        valid = names == set(_PROMOTION_FILE_SEQUENCE)
    else:
        valid = frozenset(names) in allowed_prefixes
    if not valid:
        raise QualificationError(
            "policy qualification output namespace contains unexpected entries"
        )


def _cold_read_promoted_json(
    custody: PhysicalRootCustodyV1,
    path: Path,
    *,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        descriptor, payload, identity = custody.read_descriptor_identity(
            path,
            label=label,
            maximum=64 * 1024 * 1024,
            capture=True,
        )
        mode, stat_identity = custody.stat_regular_identity(path, label=label)
    except PublicationPhysicalIoV1Error as error:
        raise QualificationError(f"{label} cold validation failed") from error
    if payload is None or identity != stat_identity or mode != 0o444:
        raise QualificationError(f"{label} is not one readonly immutable file")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = item
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise QualificationError(f"{label} is not canonical JSON") from error
    if type(value) is not dict or payload != _canonical_bytes(value) + b"\n":
        raise QualificationError(f"{label} is not canonical JSON")
    return value, {
        "path": path.name,
        "size_bytes": descriptor["size_bytes"],
        "sha256": descriptor["sha256"],
    }


def _cold_validate_promoted_policy_bundle(
    *,
    project_root: Path,
    destination: Path,
    expected_capability: Mapping[str, Any],
    expected_calibration: Mapping[str, Any],
    expected_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Reopen a completed promotion with no producer descriptors alive."""

    try:
        with PhysicalRootCustodyV1.open(
            project_root, label="cold policy qualification project_root"
        ) as custody:
            _require_promotion_namespace(custody, destination, complete=True)
            capability, capability_descriptor = _cold_read_promoted_json(
                custody,
                destination / CAPABILITY_MANIFEST_FILENAME,
                label="promoted policy capability manifest",
            )
            calibration, calibration_descriptor = _cold_read_promoted_json(
                custody,
                destination / CALIBRATION_MAPPING_FILENAME,
                label="promoted policy calibration mapping",
            )
            receipt, _receipt_descriptor = _cold_read_promoted_json(
                custody,
                destination / QUALIFICATION_RECEIPT_FILENAME,
                label="promoted policy qualification receipt",
            )
            custody.verify()
    except QualificationError:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise QualificationError(
            "promoted policy qualification cold validation failed"
        ) from error
    unsigned = dict(receipt)
    claimed = unsigned.pop("sha256", None)
    if not (
        capability == dict(expected_capability)
        and calibration == dict(expected_calibration)
        and receipt == dict(expected_receipt)
        and claimed == _canonical_sha(unsigned)
        and receipt.get("outputs")
        == {
            "capability_manifest": capability_descriptor,
            "calibration_mapping": calibration_descriptor,
        }
    ):
        raise QualificationError(
            "promoted policy qualification bundle identity drifted"
        )
    return receipt


def promote_policy_qualification(
    *,
    project_root: Path,
    index_path: Path,
    output_dir: Path,
    pilot_validator: PilotValidator | None = None,
    fragment_validator: FragmentValidator | None = None,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Emit two derived artifacts and commit an immutable receipt last."""
    assessment = assess_policy_qualification(
        project_root=project_root,
        index_path=index_path,
        pilot_validator=pilot_validator,
        fragment_validator=fragment_validator,
    )
    if not assessment["passed"]:
        raise QualificationError("policy qualification is blocked: " + ", ".join(assessment["blockers"][:8]))
    root = Path(project_root).resolve(strict=True)
    supplied_destination = Path(output_dir)
    if not supplied_destination.is_absolute():
        if any(part in ("", ".", "..") for part in supplied_destination.parts):
            raise QualificationError("qualification output_dir must be normalized")
        supplied_destination = root / supplied_destination
    destination = Path(os.path.abspath(os.fspath(supplied_destination)))
    try:
        relative_destination = destination.relative_to(root)
    except ValueError as exc:
        raise QualificationError("qualification output_dir must remain under project_root") from exc
    if not relative_destination.parts:
        raise QualificationError("qualification output_dir must be a dedicated directory")
    try:
        with PhysicalRootCustodyV1.open(
            root, label="policy qualification project_root"
        ) as custody:
            destination = custody.ensure_directory(
                relative_destination.as_posix(),
                label="policy qualification output_dir",
            )
            _require_promotion_namespace(custody, destination, complete=False)
            capability_descriptor = _write_immutable_json(
                destination / CAPABILITY_MANIFEST_FILENAME,
                assessment["capability_manifest"],
                custody=custody,
                after_physical_commit_step=after_physical_commit_step,
            )
            calibration_descriptor = _write_immutable_json(
                destination / CALIBRATION_MAPPING_FILENAME,
                assessment["calibration_mapping"],
                custody=custody,
                after_physical_commit_step=after_physical_commit_step,
            )
            receipt = {
                "schema_version": QUALIFICATION_RECEIPT_SCHEMA_VERSION,
                "artifact_kind": "vast_publication_policy_qualification_receipt",
                "status": "accepted_evidence_driven_policy_qualification",
                "policy_contract_sha256": assessment["capability_manifest"]["policy_contract_sha256"],
                "qualification_index_sha256": assessment["index_sha256"],
                "dataset_manifest_sha256": assessment["dataset_manifest_sha256"],
                "coverage": assessment["coverage"],
                "outputs": {
                    "capability_manifest": capability_descriptor,
                    "calibration_mapping": calibration_descriptor,
                },
            }
            receipt["sha256"] = _canonical_sha(receipt)
            _write_immutable_json(
                destination / QUALIFICATION_RECEIPT_FILENAME,
                receipt,
                custody=custody,
                after_physical_commit_step=after_physical_commit_step,
            )
            _require_promotion_namespace(custody, destination, complete=True)
            custody.verify()
    except QualificationError:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise QualificationError(
            "qualification output_dir physical custody failed"
        ) from error
    receipt = _cold_validate_promoted_policy_bundle(
        project_root=root,
        destination=destination,
        expected_capability=assessment["capability_manifest"],
        expected_calibration=assessment["calibration_mapping"],
        expected_receipt=receipt,
    )
    return {"passed": True, "status": "promoted", "receipt": receipt, "output_dir": str(destination)}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--index-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = promote_policy_qualification(
        project_root=args.project_root,
        index_path=args.index_path,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPABILITY_MANIFEST_FILENAME",
    "CALIBRATION_MAPPING_FILENAME",
    "QUALIFICATION_RECEIPT_FILENAME",
    "KPP_DATASET_BY_CODEC",
    "QualificationError",
    "assess_policy_qualification",
    "main",
    "promote_policy_qualification",
]
