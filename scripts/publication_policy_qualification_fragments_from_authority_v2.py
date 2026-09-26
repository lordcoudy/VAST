#!/usr/bin/env python3
"""Materialize four qualification fragments from current physical authorities.

The legacy per-system fragment builders freeze image and model-parity identities
in source constants.  This module is the versioned transaction boundary used
after a physical image refreeze.  It accepts either the unchanged v3 authority
or the patch-bound v4 refresh authority, re-hashes the analytics binding set,
runtime probes, image patch, and parity acceptance, verifies live Docker image
identity, and writes fresh non-authorizing fragment binding documents.

No production grant or publication acceptance is created here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import yaml
from analytics_execution_endpoint import (
    expected_capability_from_binding_and_probe,
    terminal_detector_identity,
)
from analytics_execution_protocol import ProtocolError
from checkpoint_deepstream_protocol_bridge import (
    DeepStreamProtocolBridgeError,
    analytics_backend_identity,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 2
BINDING_KIND = "vast_publication_policy_qualification_authority_binding_v2"
FRAGMENT_KIND = "vast_publication_qualification_system_fragment_v1"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
ENGINE_BY_RESOURCE = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}
REFRESH_BLOCKERS = (
    "analytics_worker:cpu_identity_changed_requires_parity_refresh",
    "analytics_worker:gpu_identity_changed_requires_parity_refresh",
)
PATCH_KIND = "vast_publication_qualification_image_identity_patch_v1"
V3_BINDING_KIND = "vast_verified_model_parity_acceptance_binding"
V4_BINDING_KIND = "vast_verified_model_parity_acceptance_binding_v4"
V3_BINDING_INDEX = "artifacts/analytics_execution_bindings/publication_v3/index.json"
V3_RUNTIME_PROBES = {
    "cpu": "artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json",
    "gpu": "artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json",
}
OMZ_MANIFEST = "configs/checkpoint_analytics_models_openvino.yaml"
POLICY_CONTRACT = "scripts/publication_policy_contract.py"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_.-]+$")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}


class QualificationFragmentsFromAuthorityV2Error(RuntimeError):
    """A source authority, live image, or immutable fragment failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationFragmentsFromAuthorityV2Error(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            "qualification fragment material is not canonical JSON"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _self_sha(value: Mapping[str, Any], field: str) -> str:
    return _canonical_sha({key: item for key, item in value.items() if key != field})


def _is_link(path: Path, info: os.stat_result | None = None) -> bool:
    observed = path.lstat() if info is None else info
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    junction = getattr(os.path, "isjunction", lambda _path: False)
    return stat.S_ISLNK(observed.st_mode) or bool(attributes & reparse) or junction(path)


def _root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        resolved = lexical.resolve(strict=True)
        info = lexical.lstat()
    except OSError as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            "project_root is unavailable"
        ) from error
    _require(
        lexical == resolved
        and stat.S_ISDIR(info.st_mode)
        and not _is_link(lexical, info)
        and resolved != Path(resolved.anchor),
        "project_root must be one canonical physical directory",
    )
    return resolved


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    if not raw.is_absolute():
        text = raw.as_posix()
        pure = PurePosixPath(text)
        _require(
            bool(text)
            and pure.as_posix() == text
            and not pure.is_absolute()
            and all(part not in {"", ".", ".."} for part in pure.parts),
            f"{label} path is not canonical relative",
        )
        raw = root.joinpath(*pure.parts)
    path = Path(os.path.abspath(os.fspath(raw)))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"{label} escaped project_root"
        ) from error
    return path


def _physical_file(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationFragmentsFromAuthorityV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_link(path, info)
        and int(info.st_nlink) == 1
        and resolved == path,
        f"{label} must be one canonical physical file",
    )
    return path


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationFragmentsFromAuthorityV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(path, info) and resolved == path,
        f"{label} must be one canonical physical directory",
    )
    return path


def _file_sha(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    _require(
        (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        f"physical file changed while hashing: {path}",
    )
    return digest.hexdigest()


def file_descriptor(project_root: Path | str, value: Path | str) -> dict[str, Any]:
    root = _root(project_root)
    path = _physical_file(root, value, label="descriptor input")
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": int(path.stat().st_size),
        "sha256": _file_sha(path),
    }


def _descriptor(root: Path, value: Any, *, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    observed = file_descriptor(root, str(value.get("path")))
    _require(observed == value, f"{label} descriptor drifted")
    return observed


def _read_json(root: Path, value: Path | str, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = _physical_file(root, value, label=label)
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationFragmentsFromAuthorityV2Error(f"{label} is not JSON") from error
    _require(type(parsed) is dict, f"{label} must be a JSON object")
    return path, parsed


def _read_yaml(root: Path, value: Path | str, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = _physical_file(root, value, label=label)
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (UnicodeError, yaml.YAMLError) as error:
        raise QualificationFragmentsFromAuthorityV2Error(f"{label} is not YAML") from error
    _require(type(parsed) is dict, f"{label} must be a YAML mapping")
    return path, parsed


def _default_load_identity_patch(**kwargs: Any) -> dict[str, Any]:
    from publication_qualification_image_refreeze_v1 import load_identity_patch

    return load_identity_patch(**kwargs)


def _default_load_v3_acceptance(**kwargs: Any) -> dict[str, Any]:
    from checkpoint_model_parity_acceptance import load_verified_model_parity_acceptance

    return load_verified_model_parity_acceptance(**kwargs)


def _default_load_v4_acceptance(**kwargs: Any) -> dict[str, Any]:
    from checkpoint_model_parity_acceptance_v4 import (
        load_verified_model_parity_acceptance_v4,
    )

    return load_verified_model_parity_acceptance_v4(**kwargs)


def _default_inspect_image(docker: str, reference: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", reference],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"Docker image inspect failed: {reference}"
        ) from error
    _require(
        completed.returncode == 0
        and len(completed.stdout) <= 16 * 1024 * 1024
        and len(completed.stderr) <= 16 * 1024 * 1024,
        f"Docker image inspect failed: {reference}",
    )
    try:
        values = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"Docker image inspect is not JSON: {reference}"
        ) from error
    _require(
        type(values) is list and len(values) == 1 and type(values[0]) is dict,
        f"Docker image inspect cardinality drifted: {reference}",
    )
    return dict(values[0])


@dataclass(frozen=True)
class FragmentAuthorityDependenciesV2:
    load_identity_patch: Callable[..., dict[str, Any]] = _default_load_identity_patch
    load_v3_acceptance: Callable[..., dict[str, Any]] = _default_load_v3_acceptance
    load_v4_acceptance: Callable[..., dict[str, Any]] = _default_load_v4_acceptance
    inspect_image: Callable[[str, str], dict[str, Any]] = _default_inspect_image


DEFAULT_DEPENDENCIES = FragmentAuthorityDependenciesV2()


def _receipt_kind(root: Path, receipt_path: Path | str) -> str:
    _path, value = _read_json(root, receipt_path, label="model-parity acceptance receipt")
    kind = value.get("artifact_kind")
    _require(type(kind) is str and bool(kind), "model-parity receipt kind is absent")
    return kind


def _primary_descriptors(
    root: Path,
    binding: Mapping[str, Any],
    *,
    manifest_path: Path | str,
    assessment_path: Path | str,
    receipt_path: Path | str,
) -> dict[str, dict[str, Any]]:
    expected = {
        "accepted_manifest": file_descriptor(root, manifest_path),
        "accepted_assessment": file_descriptor(root, assessment_path),
        "receipt": file_descriptor(root, receipt_path),
    }
    for field, descriptor in expected.items():
        _require(binding.get(field) == descriptor, f"parity {field} cross-binding drifted")
    return expected


def _v3_refresh_authority(
    root: Path,
    binding: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    execution = manifest.get("worker_runtime_registry", {}).get("execution_config")
    _require(type(execution) is dict, "v3 execution-config descriptor is absent")
    execution_descriptor = file_descriptor(root, str(execution.get("path")))
    _require(
        execution_descriptor["sha256"] == execution.get("sha256"),
        "v3 execution config descriptor drifted",
    )
    index_descriptor = file_descriptor(root, V3_BINDING_INDEX)
    _index_path, index = _read_json(root, V3_BINDING_INDEX, label="v3 binding-set index")
    records = index.get("files")
    _require(type(records) is list and len(records) == 8, "v3 binding-set coverage drifted")
    binding_descriptors: dict[str, dict[str, Any]] = {}
    index_parent = PurePosixPath(V3_BINDING_INDEX).parent
    for record in records:
        _require(
            type(record) is dict
            and set(record) == {"path", "bytes", "sha256"}
            and type(record.get("path")) is str,
            "v3 binding-set record drifted",
        )
        descriptor = file_descriptor(root, (index_parent / record["path"]).as_posix())
        _require(
            descriptor["size_bytes"] == record["bytes"]
            and descriptor["sha256"] == record["sha256"],
            "v3 binding-set file descriptor drifted",
        )
        binding_descriptors[record["path"]] = descriptor
    probes = {
        resource: file_descriptor(root, V3_RUNTIME_PROBES[resource])
        for resource in RESOURCES
    }
    return {
        "execution_config": {
            **execution_descriptor,
            "content_identity_sha256": execution.get("content_identity_sha256"),
            "worker_projection_sha256": execution.get("worker_projection_sha256"),
        },
        "binding_set": {
            "index": index_descriptor,
            "identity_sha256": index.get("identity", {}).get("sha256"),
            "bindings_identity_sha256": index.get("bindings_identity_sha256"),
            "bindings": binding_descriptors,
        },
        "runtime_probes": probes,
        "resolved_blockers": [],
        "acceptance_binding_sha256": binding.get("binding_sha256"),
    }


def _normalize_v4_refresh_authority(root: Path, binding: Mapping[str, Any]) -> dict[str, Any]:
    refresh = binding.get("refresh_authority")
    _require(type(refresh) is dict, "v4 refresh authority is absent")
    patch_record = refresh.get("image_identity_patch")
    _require(type(patch_record) is dict, "v4 patch refresh binding is absent")
    patch_descriptor = {
        key: patch_record.get(key) for key in _DESCRIPTOR_FIELDS
    }
    _descriptor(root, patch_descriptor, label="v4 patch refresh")
    execution = refresh.get("execution_config")
    _require(type(execution) is dict, "v4 execution-config authority is absent")
    _descriptor(
        root,
        {key: execution.get(key) for key in _DESCRIPTOR_FIELDS},
        label="v4 execution config",
    )
    binding_set = refresh.get("binding_set")
    _require(type(binding_set) is dict, "v4 binding-set authority is absent")
    _descriptor(root, binding_set.get("index"), label="v4 binding-set index")
    raw_bindings = binding_set.get("bindings")
    _require(type(raw_bindings) is dict and len(raw_bindings) == 8, "v4 binding coverage drifted")
    normalized_bindings: dict[str, dict[str, Any]] = {}
    for coordinate, descriptor in raw_bindings.items():
        record = _descriptor(root, descriptor, label=f"v4 binding {coordinate}")
        normalized_bindings[Path(record["path"]).name] = record
    _require(len(normalized_bindings) == 8, "v4 binding filenames are not unique")
    probes = refresh.get("runtime_probes")
    _require(type(probes) is dict and set(probes) == set(RESOURCES), "v4 probe coverage drifted")
    workers = refresh.get("workers")
    _require(
        type(workers) is dict and set(workers) == set(RESOURCES),
        "v4 worker coverage drifted",
    )
    normalized_probes: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        probe = probes[resource]
        _require(
            type(probe) is dict
            and set(probe) == _DESCRIPTOR_FIELDS | {"worker_implementation_sha256"},
            f"v4 {resource} probe authority fields drifted",
        )
        implementation = probe.get("worker_implementation_sha256")
        worker = workers[resource]
        _require(
            type(worker) is dict
            and _SHA.fullmatch(str(implementation)) is not None
            and worker.get("worker_implementation_sha256") == implementation,
            f"v4 {resource} probe/worker implementation drifted",
        )
        normalized_probes[resource] = _descriptor(
            root,
            {key: probe[key] for key in _DESCRIPTOR_FIELDS},
            label=f"v4 {resource} probe",
        )
    refresh_blockers = patch_record.get("refresh_blockers")
    resolved_blockers = patch_record.get("resolved_blockers")
    _require(
        refresh_blockers == list(REFRESH_BLOCKERS)
        and resolved_blockers == [],
        "v4 acceptance is not bound to the exact unresolved refresh-only patch",
    )
    return {
        "image_identity_patch": {**patch_descriptor, **{
            "patch_sha256": patch_record.get("patch_sha256"),
            "refresh_blockers": list(refresh_blockers),
            "resolved_blockers": [],
        }},
        "workers": copy.deepcopy(workers),
        "execution_config": copy.deepcopy(execution),
        "binding_set": {
            "index": copy.deepcopy(binding_set["index"]),
            "identity_sha256": binding_set.get("identity_sha256"),
            "bindings_identity_sha256": binding_set.get("bindings_identity_sha256"),
            "bindings": normalized_bindings,
        },
        "runtime_probes": normalized_probes,
        "resolved_blockers": list(REFRESH_BLOCKERS),
        "acceptance_binding_sha256": binding.get("binding_sha256"),
    }


def _load_parity_authority(
    *,
    root: Path,
    manifest_path: Path | str,
    assessment_path: Path | str,
    receipt_path: Path | str,
    dependencies: FragmentAuthorityDependenciesV2,
) -> dict[str, Any]:
    kind = _receipt_kind(root, receipt_path)
    try:
        if kind == "vast_checkpoint_model_parity_acceptance_receipt_v4":
            binding = dependencies.load_v4_acceptance(
                project_root=root, receipt_path=_physical_file(
                    root, receipt_path, label="v4 parity receipt"
                )
            )
            from checkpoint_model_parity_v4 import load_parity_manifest_v4

            manifest = load_parity_manifest_v4(
                _physical_file(root, manifest_path, label="v4 parity manifest"),
                project_root=root,
            )
            refresh = _normalize_v4_refresh_authority(root, binding)
            version = 4
        else:
            binding = dependencies.load_v3_acceptance(
                project_root=root, receipt_path=_physical_file(
                    root, receipt_path, label="v3 parity receipt"
                )
            )
            from checkpoint_model_parity import load_parity_manifest

            manifest = load_parity_manifest(
                _physical_file(root, manifest_path, label="v3 parity manifest")
            )
            refresh = _v3_refresh_authority(root, binding, manifest)
            version = 3
    except QualificationFragmentsFromAuthorityV2Error:
        raise
    except Exception as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"model-parity authority validation failed closed: {error}"
        ) from error
    _require(
        type(binding) is dict
        and binding.get("artifact_kind")
        == (V4_BINDING_KIND if version == 4 else V3_BINDING_KIND)
        and binding.get("schema_version") == (4 if version == 4 else 2)
        and _SHA.fullmatch(str(binding.get("binding_sha256", ""))) is not None,
        "model-parity acceptance binding kind/schema drifted",
    )
    primary = _primary_descriptors(
        root,
        binding,
        manifest_path=manifest_path,
        assessment_path=assessment_path,
        receipt_path=receipt_path,
    )
    _require(
        type(manifest) is dict
        and type(manifest.get("identity")) is dict
        and _SHA.fullmatch(str(manifest["identity"].get("sha256", ""))) is not None,
        "accepted model-parity manifest identity is absent",
    )
    return {
        "version": version,
        "binding": copy.deepcopy(binding),
        "binding_sha256": binding["binding_sha256"],
        "manifest": copy.deepcopy(manifest),
        "manifest_identity_sha256": manifest["identity"]["sha256"],
        "primary": primary,
        "refresh": refresh,
    }


def _load_patch_authority(
    *,
    root: Path,
    patch_path: Path | str,
    parity: Mapping[str, Any],
    dependencies: FragmentAuthorityDependenciesV2,
) -> tuple[dict[str, Any], dict[str, Any]]:
    physical = _physical_file(root, patch_path, label="qualification image patch")
    try:
        patch = dependencies.load_identity_patch(
            project_root=root,
            patch_path=physical,
            require_candidate_eligible=False,
        )
    except Exception as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"qualification image patch validation failed closed: {error}"
        ) from error
    _require(
        type(patch) is dict
        and patch.get("artifact_kind") == PATCH_KIND
        and _SHA.fullmatch(str(patch.get("patch_sha256", ""))) is not None
        and type(patch.get("systems")) is dict
        and set(patch["systems"]) == set(SYSTEMS)
        and type(patch.get("workers")) is dict
        and set(patch["workers"]) == set(RESOURCES),
        "qualification image patch envelope/coverage drifted",
    )
    if patch.get("candidate_binding_eligible") is True:
        _require(patch.get("blockers") == [], "eligible image patch retains blockers")
    else:
        _require(
            parity.get("version") == 4
            and patch.get("blockers") == list(REFRESH_BLOCKERS),
            "ineligible patch is not the exact parity-refresh-only case",
        )
        refresh_patch = parity["refresh"].get("image_identity_patch")
        _require(
            type(refresh_patch) is dict
            and refresh_patch.get("patch_sha256") == patch["patch_sha256"]
            and refresh_patch.get("refresh_blockers") == list(REFRESH_BLOCKERS)
            and refresh_patch.get("resolved_blockers") == [],
            "v4 parity acceptance is stale or cross-bound to another patch",
        )
        refresh_workers = parity["refresh"].get("workers")
        _require(type(refresh_workers) is dict and set(refresh_workers) == set(RESOURCES), "v4 worker refresh coverage drifted")
        for resource in RESOURCES:
            _require(
                refresh_workers[resource].get("image_id")
                == patch["workers"][resource].get("image_id"),
                f"v4 {resource} worker refresh is cross-bound",
            )
    return patch, file_descriptor(root, physical)


def _binding_files(
    root: Path, parity: Mapping[str, Any]
) -> tuple[
    dict[str, Any],
    dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]],
    dict[str, tuple[dict[str, Any], dict[str, Any]]],
]:
    refresh = parity["refresh"]
    config_record = _descriptor(
        root,
        {key: refresh["execution_config"].get(key) for key in _DESCRIPTOR_FIELDS},
        label="analytics execution config",
    )
    config_path, config_raw = _read_yaml(
        root, config_record["path"], label="analytics execution config"
    )
    try:
        from analytics_execution_capability import load_execution_layer_config

        config = load_execution_layer_config(config_path)
    except Exception as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"analytics execution config rejected: {error}"
        ) from error
    _require(
        config.get("identity", {}).get("sha256")
        == refresh["execution_config"].get("content_identity_sha256"),
        "analytics execution config content identity drifted",
    )
    del config_raw
    raw_binding_descriptors = refresh["binding_set"]["bindings"]
    by_coordinate: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for branch in BRANCHES:
        for resource in RESOURCES:
            filename = f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
            descriptor = raw_binding_descriptors.get(filename)
            _require(type(descriptor) is dict, f"analytics binding is absent: {filename}")
            record = _descriptor(root, descriptor, label=f"analytics binding {branch}/{resource}")
            _path, value = _read_json(root, record["path"], label=f"analytics binding {branch}/{resource}")
            _require(
                value.get("branch") == branch
                and value.get("worker_image_id")
                == config.get("workers", {}).get(resource, {}).get("image_id"),
                f"analytics binding {branch}/{resource} identity drifted",
            )
            by_coordinate[(branch, resource)] = (record, value)
    probes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for resource in RESOURCES:
        record = _descriptor(
            root,
            refresh["runtime_probes"][resource],
            label=f"analytics {resource} runtime probe",
        )
        _path, value = _read_json(root, record["path"], label=f"analytics {resource} runtime probe")
        _require(
            value.get("artifact_kind")
            == "vast_analytics_execution_worker_runtime_probe"
            and value.get("engine") == ENGINE_BY_RESOURCE[resource]
            and value.get("worker_implementation_sha256")
            == config.get("workers", {}).get(resource, {}).get(
                "worker_implementation_sha256"
            ),
            f"analytics {resource} runtime probe drifted",
        )
        probes[resource] = (record, value)
    return config, by_coordinate, probes


def _inspect_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    config = value.get("Config")
    _require(type(config) is dict, "Docker inspect Config is absent")
    labels = config.get("Labels") or {}
    repos = value.get("RepoDigests") or []
    _require(type(labels) is dict and type(repos) is list, "Docker inspect labels/digests drifted")
    return {
        "id": value.get("Id"),
        "repo_digests": sorted(repos),
        "architecture": value.get("Architecture"),
        "os": value.get("Os"),
        "created": value.get("Created"),
        "config": {
            "entrypoint": config.get("Entrypoint"),
            "user": config.get("User") or "root",
            "labels": {key: labels[key] for key in sorted(labels)},
        },
    }


def _verify_live_images(
    patch: Mapping[str, Any], *, docker: str, inspector: Callable[[str, str], dict[str, Any]]
) -> None:
    _require(type(docker) is str and docker and "\x00" not in docker, "docker is invalid")
    for resource in RESOURCES:
        worker = patch["workers"][resource]
        image_id = worker.get("image_id")
        observed = inspector(docker, str(image_id))
        _require(
            _IMAGE.fullmatch(str(image_id)) is not None
            and observed.get("Id") == image_id
            and worker.get("image_inspect_sha256")
            == _canonical_sha(_inspect_projection(observed)),
            f"live analytics {resource} worker differs from freeze receipt",
        )
    for system in SYSTEMS:
        system_record = patch["systems"][system]
        physical = system_record.get("physical_identity")
        fragment = system_record.get("fragment_identity")
        _require(type(physical) is dict and type(fragment) is dict, f"{system} image identity is absent")
        image_id = physical.get("image_id")
        final_reference = physical.get("final_reference")
        deterministic_references = physical.get("deterministic_references")
        observed = inspector(docker, str(final_reference))
        _require(
            _IMAGE.fullmatch(str(image_id)) is not None
            and _IMAGE_REFERENCE.fullmatch(str(final_reference)) is not None
            and deterministic_references == [
                str(final_reference) + "-determinism-a",
                str(final_reference) + "-determinism-b",
            ]
            and fragment.get("image_id") == image_id
            and observed.get("Id") == image_id
            and physical.get("inspect_full_sha256") == _canonical_sha(observed),
            f"live {system} runtime image differs from refreeze receipt",
        )


def _nvidia_identity(manifest: Mapping[str, Any]) -> dict[str, str]:
    value = manifest.get("toolchain_registry", {}).get("tensorrt_cuda")
    _require(type(value) is dict, "accepted NVIDIA toolchain identity is absent")
    result = {
        "uuid": value.get("gpu_uuid"),
        "name": value.get("gpu_name"),
        "driver_version": value.get("driver_version"),
    }
    _require(all(type(item) is str and item for item in result.values()), "NVIDIA identity is incomplete")
    return result


def _omz_bindings(root: Path) -> dict[str, dict[str, Any]]:
    _path, manifest = _read_yaml(root, OMZ_MANIFEST, label="nonterminal OMZ manifest")
    branches = manifest.get("branches")
    _require(
        manifest.get("schema_version") == 2
        and manifest.get("artifact_kind") == "checkpoint_analytics_model_bindings"
        and type(branches) is dict
        and set(branches) == set(BRANCHES),
        "nonterminal OMZ manifest identity/coverage drifted",
    )
    result: dict[str, dict[str, Any]] = {}
    for branch in BRANCHES:
        row = branches[branch]
        _require(
            type(row) is dict and row.get("semantic_claim") == "topology_load_proxy_only",
            f"{branch} OMZ binding is not explicitly nonterminal",
        )
        def model_descriptor(field: str, digest_field: str) -> dict[str, Any]:
            raw = PurePosixPath("configs") / PurePosixPath(str(row.get(field)))
            normalized = PurePosixPath(os.path.normpath(raw.as_posix()).replace("\\", "/"))
            _require(
                not normalized.is_absolute()
                and all(part not in {"", ".", ".."} for part in normalized.parts),
                f"{branch} OMZ path escaped project_root",
            )
            descriptor = file_descriptor(root, normalized.as_posix())
            _require(descriptor["sha256"] == row.get(digest_field), f"{branch} OMZ digest drifted")
            return descriptor
        result[branch] = {
            "semantic_claim": "topology_load_proxy_only",
            "detector_id": row.get("detector_id"),
            "device": row.get("device"),
            "factory": row.get("factory"),
            "model": model_descriptor("model_path", "model_sha256"),
            "weights": model_descriptor("weights_path", "weights_sha256"),
        }
    return result


def _system_image_projection(patch: Mapping[str, Any], system: str) -> dict[str, Any]:
    fragment = copy.deepcopy(patch["systems"][system]["fragment_identity"])
    physical = patch["systems"][system]["physical_identity"]
    final_reference = physical.get("final_reference")
    _require(
        _IMAGE_REFERENCE.fullmatch(str(final_reference)) is not None
        and (
            fragment.get("final_reference") is None
            or fragment.get("final_reference") == final_reference
        ),
        f"{system} runtime image reference drifted",
    )
    fragment["final_reference"] = final_reference
    if system == "deepstream":
        return {"image_identity": fragment}
    if system == "savant":
        return {"savant_runtime_image": {"identity": fragment}}
    if system == "openvino_gva":
        return {"openvino_gva_runtime_image": fragment}
    return {"gstreamer_runtime_image": fragment}


def _policy_runtime_identity(
    *, system: str, resource: str, binding: Mapping[str, Any], probe: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        capability = expected_capability_from_binding_and_probe(
            binding=binding,
            runtime_probe=probe,
            resource=resource,
        )
        terminal = analytics_backend_identity(capability)
    except (ProtocolError, DeepStreamProtocolBridgeError) as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            "terminal worker capability identity is invalid"
        ) from error
    implementation = str(capability.get("worker_implementation_sha256"))
    image = str(capability.get("worker_image_id"))
    _require(_SHA.fullmatch(implementation) is not None and _IMAGE.fullmatch(image) is not None, "terminal worker identity is invalid")
    if resource == "cpu":
        device_api: str = "CPU"
        gpu_id: int | None = None
    else:
        device_api = "NVIDIA_CUDA"
        gpu_id = 0
    _require(
        capability.get("engine") == ENGINE_BY_RESOURCE[resource]
        and capability.get("device_api") == device_api,
        "terminal worker resource identity is inconsistent",
    )
    return {
        "runtime_backend": f"{system}_{ENGINE_BY_RESOURCE[resource]}_authority_v2",
        "device_api": device_api,
        "gpu_id": gpu_id,
        "worker_image_digest": image,
        "implementation_version": f"sha256:{implementation}",
        "terminal_detector": terminal_detector_identity(capability),
        "terminal_backend": terminal,
    }


def _resource_runtime_identity(
    *, system: str, resource: str, image_id: str, patch_sha256: str, nvidia: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "runtime_backend": f"{system}_physical_runtime_authority_v2",
        "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "decoder_device_api": "NVIDIA_NVDEC",
        "worker_image_digest": image_id,
        "implementation_version": f"patch-sha256:{patch_sha256}",
        "hardware_binding_id": (
            f"nvidia-gpu:{nvidia['uuid']}:driver-{nvidia['driver_version']}"
        ),
    }


def _binding_authority(
    *, patch_descriptor: Mapping[str, Any], patch: Mapping[str, Any], parity: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "image_identity_patch": {
            **copy.deepcopy(patch_descriptor),
            "patch_sha256": patch["patch_sha256"],
            "candidate_binding_eligible": patch["candidate_binding_eligible"],
            "resolved_blockers": (
                [] if patch["candidate_binding_eligible"] else list(REFRESH_BLOCKERS)
            ),
        },
        "model_parity": {
            "schema_version": parity["version"],
            "acceptance_binding_sha256": parity["binding_sha256"],
            "manifest_identity_sha256": parity["manifest_identity_sha256"],
            **copy.deepcopy(parity["primary"]),
        },
    }


def _document(
    *,
    system: str,
    role: str,
    branch: str,
    resource: str,
    implementation_id: str,
    emitter_id: str,
    runtime_identity: Mapping[str, Any],
    authority: Mapping[str, Any],
    system_image: Mapping[str, Any],
    nvidia: Mapping[str, str],
    policy_contract: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    binding_index: Mapping[str, Any],
    analytics_binding: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
    runtime_probe: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
    local_omz: Mapping[str, Any] | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "system": system,
        "role": role,
        "branch": branch,
        "resource": resource,
        "implementation_id": implementation_id,
        "emitter_id": emitter_id,
        "runtime_identity": copy.deepcopy(runtime_identity),
        "authority": copy.deepcopy(authority),
        "policy_contract": copy.deepcopy(policy_contract),
        "system_image": copy.deepcopy(system_image),
        "nvidia_hardware_binding": copy.deepcopy(nvidia),
        "execution_config": copy.deepcopy(execution_config),
        "analytics_execution_binding_index": copy.deepcopy(binding_index),
    }
    value.update(copy.deepcopy(system_image))
    if analytics_binding is not None and runtime_probe is not None:
        descriptor, binding = analytics_binding
        probe_descriptor, probe = runtime_probe
        value.update(
            {
                "analytics_execution_worker_binding": copy.deepcopy(descriptor),
                "analytics_execution_worker_binding_identity": {
                    key: binding.get(key)
                    for key in (
                        "artifact_kind",
                        "model_id",
                        "source_model_sha256",
                        "model_artifact_sha256",
                        "worker_image_id",
                    )
                },
                "analytics_runtime_probe": copy.deepcopy(probe_descriptor),
                "analytics_runtime_probe_identity_sha256": _canonical_sha(probe),
            }
        )
    if local_omz is not None:
        field = (
            "gva_sdk_binding_nonterminal"
            if system == "openvino_gva"
            else "openvino_cpu_binding"
        )
        value[field] = copy.deepcopy(local_omz)
        if system == "openvino_gva":
            value["terminal_authority"] = "external_analytics_execution_worker_only"
    value["binding_sha256"] = _self_sha(value, "binding_sha256")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> tuple[int, str]:
    payload = _canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o444)
    return len(payload), hashlib.sha256(payload).hexdigest()


def _fragment_row(
    *, root: Path, path: Path, value: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "branch": value["branch"],
        "resource": value["resource"],
        "role": value["role"],
        "implementation_id": value["implementation_id"],
        "emitter_id": value["emitter_id"],
        "path": path.relative_to(root).as_posix(),
        "size": int(path.stat().st_size),
        "sha256": _file_sha(path),
        "runtime_identity": copy.deepcopy(value["runtime_identity"]),
    }


def _materialization_inputs(
    *,
    root: Path,
    identity_patch_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    docker: str,
    dependencies: FragmentAuthorityDependenciesV2,
    verify_live: bool,
) -> dict[str, Any]:
    parity = _load_parity_authority(
        root=root,
        manifest_path=accepted_model_parity_manifest_path,
        assessment_path=accepted_model_parity_assessment_path,
        receipt_path=accepted_model_parity_receipt_path,
        dependencies=dependencies,
    )
    patch, patch_descriptor = _load_patch_authority(
        root=root,
        patch_path=identity_patch_path,
        parity=parity,
        dependencies=dependencies,
    )
    if verify_live:
        _verify_live_images(patch, docker=docker, inspector=dependencies.inspect_image)
    config, bindings, probes = _binding_files(root, parity)
    for resource in RESOURCES:
        _require(
            config.get("workers", {}).get(resource, {}).get("image_id")
            == patch["workers"][resource].get("image_id"),
            f"analytics {resource} config is stale relative to image patch",
        )
    policy_descriptor = file_descriptor(root, POLICY_CONTRACT)
    try:
        from publication_policy_contract import policy_contract_identity

        policy_identity = policy_contract_identity()["sha256"]
    except Exception as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"policy contract identity failed: {error}"
        ) from error
    policy_descriptor["identity_sha256"] = policy_identity
    return {
        "parity": parity,
        "patch": patch,
        "patch_descriptor": patch_descriptor,
        "config": config,
        "bindings": bindings,
        "probes": probes,
        "policy_contract": policy_descriptor,
        "nvidia": _nvidia_identity(parity["manifest"]),
        "omz": _omz_bindings(root),
    }


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(path, info),
        "fragment directory identity is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    from publication_policy_qualification_pilot_executor_v2 import (
        _rename_directory_noreplace as publish,
    )

    publish(source, destination)


def _cleanup_staging(
    staging: Path,
    *,
    destination: Path,
    expected_staging_identity: tuple[int, int],
    expected_destination_identity: tuple[int, int],
) -> None:
    _require(
        staging.parent == destination
        and staging.name.startswith(".authority-fragments-v2.")
        and _directory_identity(destination) == expected_destination_identity
        and _directory_identity(staging) == expected_staging_identity,
        "unsafe fragment staging cleanup target",
    )
    for path in staging.rglob("*"):
        info = path.lstat()
        _require(
            (
                stat.S_ISDIR(info.st_mode)
                and not _is_link(path, info)
            )
            or (
                stat.S_ISREG(info.st_mode)
                and not _is_link(path, info)
                and int(info.st_nlink) == 1
            ),
            "fragment staging cleanup found an unowned inode",
        )
    shutil.rmtree(staging)


def _materialize_publication_policy_qualification_fragments_from_authority_v2_held(
    *,
    project_root: Path | str,
    fragments_root: Path | str,
    identity_patch_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    docker: str = "docker",
    dependencies: FragmentAuthorityDependenciesV2 = DEFAULT_DEPENDENCIES,
) -> dict[str, Path]:
    """Create exact 4 fragments/40 binding files after physical preflight."""

    root = _root(project_root)
    _require(type(dependencies) is FragmentAuthorityDependenciesV2, "fragment dependencies are invalid")
    destination = _physical_directory(root, fragments_root, label="fragments root")
    _require(destination != root, "fragments root cannot be project_root")
    _require(
        not any(os.path.lexists(destination / system) for system in SYSTEMS),
        "fragment output already exists",
    )
    inputs = _materialization_inputs(
        root=root,
        identity_patch_path=identity_patch_path,
        accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
        accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
        accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
        docker=docker,
        dependencies=dependencies,
        verify_live=True,
    )
    authority = _binding_authority(
        patch_descriptor=inputs["patch_descriptor"],
        patch=inputs["patch"],
        parity=inputs["parity"],
    )
    refresh = inputs["parity"]["refresh"]
    execution_descriptor = copy.deepcopy(refresh["execution_config"])
    binding_index = {
        **copy.deepcopy(refresh["binding_set"]["index"]),
        "identity_sha256": refresh["binding_set"]["identity_sha256"],
        "bindings_identity_sha256": refresh["binding_set"]["bindings_identity_sha256"],
    }
    staging = Path(tempfile.mkdtemp(prefix=".authority-fragments-v2.", dir=destination))
    destination_identity = _directory_identity(destination)
    staging_identity = _directory_identity(staging)
    committed: list[Path] = []
    try:
        for system in SYSTEMS:
            system_root = staging / system
            policy_root = system_root / "bindings" / "policy"
            resource_root = system_root / "bindings" / "resource"
            policy_rows: list[dict[str, Any]] = []
            resource_rows: list[dict[str, Any]] = []
            system_image = _system_image_projection(inputs["patch"], system)
            image_id = inputs["patch"]["systems"][system]["fragment_identity"]["image_id"]
            for branch in BRANCHES:
                for resource in RESOURCES:
                    binding_record, binding_value = inputs["bindings"][(branch, resource)]
                    probe_record, probe_value = inputs["probes"][resource]
                    runtime_identity = _policy_runtime_identity(
                        system=system,
                        resource=resource,
                        binding=binding_value,
                        probe=probe_value,
                    )
                    coordinate_sha = _canonical_sha(
                        {
                            "system": system,
                            "branch": branch,
                            "resource": resource,
                            "patch_sha256": inputs["patch"]["patch_sha256"],
                            "parity_binding_sha256": inputs["parity"]["binding_sha256"],
                            "analytics_binding_sha256": binding_record["sha256"],
                            "runtime_probe_sha256": probe_record["sha256"],
                        }
                    )
                    implementation_id = (
                        f"{system}-qualification-authority-v2:{branch}:{resource}:"
                        f"{coordinate_sha}"
                    )
                    emitter_id = (
                        f"{system}-native-policy-emitter-v2:{branch}:{resource}:"
                        f"{coordinate_sha}"
                    )
                    document = _document(
                        system=system,
                        role="policy",
                        branch=branch,
                        resource=resource,
                        implementation_id=implementation_id,
                        emitter_id=emitter_id,
                        runtime_identity=runtime_identity,
                        authority=authority,
                        system_image=system_image,
                        nvidia=inputs["nvidia"],
                        policy_contract=inputs["policy_contract"],
                        execution_config=execution_descriptor,
                        binding_index=binding_index,
                        analytics_binding=(binding_record, binding_value),
                        runtime_probe=(probe_record, probe_value),
                        local_omz=(
                            inputs["omz"][branch]
                            if system in {"openvino_gva", "gstreamer_custom"}
                            else None
                        ),
                    )
                    path = policy_root / f"{branch}.{resource}.binding.json"
                    _write_json(path, document)
                    policy_rows.append(_fragment_row(root=root, path=path, value=document))
            for resource in RESOURCES:
                coordinate_sha = _canonical_sha(
                    {
                        "system": system,
                        "resource": resource,
                        "image_id": image_id,
                        "patch_sha256": inputs["patch"]["patch_sha256"],
                    }
                )
                implementation_id = (
                    f"{system}-full-resource-authority-v2:{resource}:{coordinate_sha}"
                )
                emitter_id = (
                    f"{system}-native-resource-emitter-v2:{resource}:{coordinate_sha}"
                )
                document = _document(
                    system=system,
                    role="resource",
                    branch="all_branches",
                    resource=resource,
                    implementation_id=implementation_id,
                    emitter_id=emitter_id,
                    runtime_identity=_resource_runtime_identity(
                        system=system,
                        resource=resource,
                        image_id=image_id,
                        patch_sha256=inputs["patch"]["patch_sha256"],
                        nvidia=inputs["nvidia"],
                    ),
                    authority=authority,
                    system_image=system_image,
                    nvidia=inputs["nvidia"],
                    policy_contract=inputs["policy_contract"],
                    execution_config=execution_descriptor,
                    binding_index=binding_index,
                    analytics_binding=None,
                    runtime_probe=None,
                    local_omz=None,
                )
                path = resource_root / f"{resource}.binding.json"
                _write_json(path, document)
                resource_rows.append(_fragment_row(root=root, path=path, value=document))
            fragment = {
                "schema_version": 1,
                "artifact_kind": FRAGMENT_KIND,
                "system": system,
                "policy_bindings": policy_rows,
                "resource_bindings": resource_rows,
                "pilots": [],
            }
            _write_json(system_root / "qualification_fragment.json", fragment)

        # Paths in the staged documents must name final paths, not private staging.
        # Rebase once before commit and regenerate the 40 dependent hashes.
        for system in SYSTEMS:
            system_root = staging / system
            fragment_path = system_root / "qualification_fragment.json"
            fragment = json.loads(fragment_path.read_bytes())
            for rows in (fragment["policy_bindings"], fragment["resource_bindings"]):
                for row in rows:
                    raw = PurePosixPath(row["path"])
                    marker = PurePosixPath(staging.relative_to(root).as_posix()) / system
                    _require(tuple(raw.parts[: len(marker.parts)]) == tuple(marker.parts), "staged binding path escaped transaction")
                    final_relative = PurePosixPath(destination.relative_to(root).as_posix()) / system / PurePosixPath(*raw.parts[len(marker.parts):])
                    row["path"] = final_relative.as_posix()
            fragment_path.chmod(0o600)
            fragment_path.unlink()
            _write_json(fragment_path, fragment)

        for system in SYSTEMS:
            source = staging / system
            target = destination / system
            _require(not target.exists() and not os.path.lexists(target), f"{system} fragment collided before commit")
            _require(
                _directory_identity(destination) == destination_identity,
                "fragments root changed before commit",
            )
            _rename_directory_noreplace(source, target)
            committed.append(target)
        staging.rmdir()
        result = {
            system: destination / system / "qualification_fragment.json"
            for system in SYSTEMS
        }
        validate_publication_policy_qualification_fragments_from_authority_v2(
            project_root=root,
            fragment_paths=result,
            identity_patch=inputs["patch"],
            identity_patch_path=identity_patch_path,
            accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
            accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
            accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
            dependencies=dependencies,
        )
        return result
    except Exception:
        # Committed system directories are immutable phase artifacts.  Never
        # erase them here: a partial phase must remain visible and fail closed.
        raise
    finally:
        if staging.exists():
            _cleanup_staging(
                staging,
                destination=destination,
                expected_staging_identity=staging_identity,
                expected_destination_identity=destination_identity,
            )


@wraps(_materialize_publication_policy_qualification_fragments_from_authority_v2_held)
def materialize_publication_policy_qualification_fragments_from_authority_v2(
    *args: Any, **kwargs: Any
) -> dict[str, Path]:
    """Materialize under held custody, then validate from a fresh root handle."""

    _require(not args, "fragment materializer accepts keyword arguments only")
    root = _root(kwargs.get("project_root"))
    input_paths = (
        kwargs.get("identity_patch_path"),
        kwargs.get("accepted_model_parity_manifest_path"),
        kwargs.get("accepted_model_parity_assessment_path"),
        kwargs.get("accepted_model_parity_receipt_path"),
    )
    destination = _physical_directory(
        root, kwargs.get("fragments_root"), label="fragments root"
    )
    destination_identity = _directory_identity(destination)
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification fragments project_root"
        ) as custody:
            namespace = custody.capture_read_namespace(
                input_paths, label="qualification fragment authorities"
            )
            result = _materialize_publication_policy_qualification_fragments_from_authority_v2_held(
                **kwargs
            )
            custody.verify_read_namespace(
                namespace, label="qualification fragment authorities"
            )
            _require(
                _directory_identity(destination) == destination_identity,
                "fragments root changed during materialization",
            )
            custody.verify()
        with PhysicalRootCustodyV1.open(
            root, label="qualification fragments cold project_root"
        ) as cold:
            validated = validate_publication_policy_qualification_fragments_from_authority_v2(
                project_root=root,
                fragment_paths=result,
                identity_patch_path=kwargs.get("identity_patch_path"),
                accepted_model_parity_manifest_path=kwargs.get(
                    "accepted_model_parity_manifest_path"
                ),
                accepted_model_parity_assessment_path=kwargs.get(
                    "accepted_model_parity_assessment_path"
                ),
                accepted_model_parity_receipt_path=kwargs.get(
                    "accepted_model_parity_receipt_path"
                ),
                dependencies=kwargs.get("dependencies", DEFAULT_DEPENDENCIES),
            )
            _require(set(validated) == set(SYSTEMS), "cold fragment coverage drifted")
            cold.verify()
        return result
    except QualificationFragmentsFromAuthorityV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"qualification fragment physical custody failed: {error}"
        ) from error


def _validate_binding_document(
    *,
    root: Path,
    path: Path,
    expected_system: str,
    expected_role: str,
    expected_branch: str,
    expected_resource: str,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    _path, value = _read_json(root, path, label="authority binding document")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == BINDING_KIND
        and value.get("system") == expected_system
        and value.get("role") == expected_role
        and value.get("branch") == expected_branch
        and value.get("resource") == expected_resource
        and value.get("binding_sha256") == _self_sha(value, "binding_sha256"),
        "authority binding coordinate/self-identity drifted",
    )
    expected_authority = _binding_authority(
        patch_descriptor=inputs["patch_descriptor"],
        patch=inputs["patch"],
        parity=inputs["parity"],
    )
    _require(value.get("authority") == expected_authority, "authority binding is stale or cross-bound")
    _require(
        value.get("policy_contract") == inputs["policy_contract"]
        and value.get("nvidia_hardware_binding") == inputs["nvidia"]
        and value.get("system_image")
        == _system_image_projection(inputs["patch"], expected_system),
        "authority binding physical source projection drifted",
    )
    if expected_role == "policy":
        binding_record, binding = inputs["bindings"][(expected_branch, expected_resource)]
        probe_record, probe = inputs["probes"][expected_resource]
        expected_runtime = _policy_runtime_identity(
            system=expected_system,
            resource=expected_resource,
            binding=binding,
            probe=probe,
        )
        _require(
            value.get("runtime_identity") == expected_runtime
            and value.get("analytics_execution_worker_binding") == binding_record
            and value.get("analytics_runtime_probe") == probe_record
            and value.get("analytics_runtime_probe_identity_sha256")
            == _canonical_sha(probe),
            "policy binding terminal authority drifted",
        )
        if expected_system in {"openvino_gva", "gstreamer_custom"}:
            field = (
                "gva_sdk_binding_nonterminal"
                if expected_system == "openvino_gva"
                else "openvino_cpu_binding"
            )
            _require(
                value.get(field) == inputs["omz"][expected_branch]
                and (
                    expected_system != "openvino_gva"
                    or value.get("terminal_authority")
                    == "external_analytics_execution_worker_only"
                ),
                "dual local-nonterminal/terminal-worker binding drifted",
            )
    else:
        image_id = inputs["patch"]["systems"][expected_system]["fragment_identity"]["image_id"]
        _require(
            value.get("runtime_identity")
            == _resource_runtime_identity(
                system=expected_system,
                resource=expected_resource,
                image_id=image_id,
                patch_sha256=inputs["patch"]["patch_sha256"],
                nvidia=inputs["nvidia"],
            ),
            "resource binding runtime authority drifted",
        )
    return value


def _validate_one_fragment(
    *, root: Path, system: str, fragment_path: Path | str, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    path, fragment = _read_json(root, fragment_path, label=f"{system} qualification fragment")
    _require(
        set(fragment)
        == {"schema_version", "artifact_kind", "system", "policy_bindings", "resource_bindings", "pilots"}
        and fragment.get("schema_version") == 1
        and fragment.get("artifact_kind") == FRAGMENT_KIND
        and fragment.get("system") == system
        and fragment.get("pilots") == [],
        f"{system} qualification fragment envelope drifted",
    )
    policies = fragment.get("policy_bindings")
    resources = fragment.get("resource_bindings")
    _require(type(policies) is list and len(policies) == 8 and type(resources) is list and len(resources) == 2, f"{system} fragment coverage drifted")
    policy_coordinates = {(row.get("branch"), row.get("resource")) for row in policies if type(row) is dict}
    resource_coordinates = {row.get("resource") for row in resources if type(row) is dict}
    _require(
        policy_coordinates == {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
        and resource_coordinates == set(RESOURCES),
        f"{system} fragment coordinate set drifted",
    )
    identities: set[tuple[int, int]] = set()
    for row in (*policies, *resources):
        role = row.get("role")
        branch = row.get("branch")
        resource = row.get("resource")
        _require(role in {"policy", "resource"} and resource in RESOURCES, f"{system} fragment row coordinate invalid")
        binding_path = _physical_file(root, row.get("path"), label=f"{system} fragment binding")
        info = binding_path.stat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(identity not in identities, f"{system} fragment binding alias detected")
        identities.add(identity)
        _require(
            row.get("size") == int(info.st_size)
            and row.get("sha256") == _file_sha(binding_path),
            f"{system} fragment binding descriptor drifted",
        )
        document = _validate_binding_document(
            root=root,
            path=binding_path,
            expected_system=system,
            expected_role=str(role),
            expected_branch=str(branch),
            expected_resource=str(resource),
            inputs=inputs,
        )
        _require(
            row.get("implementation_id") == document.get("implementation_id")
            and row.get("emitter_id") == document.get("emitter_id")
            and row.get("runtime_identity") == document.get("runtime_identity"),
            f"{system} fragment row/document projection drifted",
        )
    return fragment


def validate_publication_policy_qualification_fragments_from_authority_v2(
    *,
    project_root: Path | str,
    fragment_paths: Mapping[str, Path | str],
    identity_patch: Mapping[str, Any] | None = None,
    identity_patch_path: Path | str | None = None,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    dependencies: FragmentAuthorityDependenciesV2 = DEFAULT_DEPENDENCIES,
) -> dict[str, dict[str, Any]]:
    """Re-hash all 40 binding files and return exact fragment descriptors."""

    root = _root(project_root)
    _require(type(fragment_paths) is dict and set(fragment_paths) == set(SYSTEMS), "fragment path coverage drifted")
    if identity_patch_path is None:
        _require(type(identity_patch) is dict, "identity patch or its path is required")
        authority_path = identity_patch.get("__physical_path")
        if authority_path is None:
            # The canonical patch path is fixed by the image-refreeze v1 contract.
            authority_path = "artifacts/publication_image_build_v1/qualification_image_identity_patch.v1.json"
    else:
        authority_path = identity_patch_path
    inputs = _materialization_inputs(
        root=root,
        identity_patch_path=authority_path,
        accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
        accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
        accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
        docker="docker",
        dependencies=dependencies,
        verify_live=False,
    )
    if identity_patch is not None:
        _require(inputs["patch"] == identity_patch, "supplied image patch differs from physical authority")
    result: dict[str, dict[str, Any]] = {}
    fragment_identities: set[tuple[int, int]] = set()
    for system in SYSTEMS:
        path = _physical_file(root, fragment_paths[system], label=f"{system} fragment")
        info = path.stat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(identity not in fragment_identities, "fragment physical alias is prohibited")
        fragment_identities.add(identity)
        _validate_one_fragment(root=root, system=system, fragment_path=path, inputs=inputs)
        result[system] = file_descriptor(root, path)
    return result


def validate_publication_policy_qualification_fragment_from_authority_v2(
    system: str, fragment_path: Path, project_root: Path
) -> dict[str, Any]:
    """Index-compatible validator using authorities embedded in one fragment."""

    root = _root(project_root)
    _require(system in SYSTEMS, "unsupported qualification fragment system")
    _path, fragment = _read_json(root, fragment_path, label=f"{system} fragment")
    rows = fragment.get("policy_bindings")
    _require(type(rows) is list and bool(rows), f"{system} fragment policy bindings are absent")
    first_path = _physical_file(root, rows[0].get("path"), label=f"{system} authority binding")
    _binding_path, first = _read_json(root, first_path, label=f"{system} authority binding")
    authority = first.get("authority")
    _require(type(authority) is dict, f"{system} embedded authority is absent")
    patch_record = authority.get("image_identity_patch")
    parity_record = authority.get("model_parity")
    _require(type(patch_record) is dict and type(parity_record) is dict, f"{system} embedded authority drifted")
    dependencies = DEFAULT_DEPENDENCIES
    inputs = _materialization_inputs(
        root=root,
        identity_patch_path=patch_record.get("path"),
        accepted_model_parity_manifest_path=parity_record.get("accepted_manifest", {}).get("path"),
        accepted_model_parity_assessment_path=parity_record.get("accepted_assessment", {}).get("path"),
        accepted_model_parity_receipt_path=parity_record.get("receipt", {}).get("path"),
        docker="docker",
        dependencies=dependencies,
        verify_live=False,
    )
    return _validate_one_fragment(
        root=root, system=system, fragment_path=fragment_path, inputs=inputs
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--fragments-root", type=Path, required=True)
    parser.add_argument("--identity-patch", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-manifest", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-assessment", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-receipt", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_publication_policy_qualification_fragments_from_authority_v2(
            project_root=args.project_root,
            fragments_root=args.fragments_root,
            identity_patch_path=args.identity_patch,
            accepted_model_parity_manifest_path=args.accepted_model_parity_manifest,
            accepted_model_parity_assessment_path=args.accepted_model_parity_assessment,
            accepted_model_parity_receipt_path=args.accepted_model_parity_receipt,
            docker=args.docker,
        )
    except (OSError, QualificationFragmentsFromAuthorityV2Error) as error:
        print(f"qualification fragment materialization blocked: {error}", file=os.sys.stderr)
        return 78
    print(json.dumps({system: str(result[system]) for system in SYSTEMS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BINDING_KIND",
    "DEFAULT_DEPENDENCIES",
    "FragmentAuthorityDependenciesV2",
    "QualificationFragmentsFromAuthorityV2Error",
    "SYSTEMS",
    "materialize_publication_policy_qualification_fragments_from_authority_v2",
    "validate_publication_policy_qualification_fragment_from_authority_v2",
    "validate_publication_policy_qualification_fragments_from_authority_v2",
]
