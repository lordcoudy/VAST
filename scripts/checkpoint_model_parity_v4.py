#!/usr/bin/env python3
"""Patch-bound physical model-parity refresh authority.

Schema 4 is deliberately separate from the frozen schema-3 contract.  It may
change the two derived analytics-worker identities and their exact refrozen
native-probe producer IDs after the patch reports the exact CPU/GPU
parity-refresh blockers.  Image references and every non-image semantic
contract remain frozen.  Worker
implementation identities are accepted only from live, validated capability
probes; they are never inferred from an image source-set hash.
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
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import yaml

import checkpoint_model_parity as parity_v3
import publication_qualification_image_refreeze_v1 as image_refreeze
from analytics_execution_protocol import canonical_sha256
from analytics_execution_worker import validate_runtime_probe
from benchmark_contract import ContractError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 4
MANIFEST_KIND = "checkpoint_analytics_model_parity_manifest_v4"
ASSESSMENT_KIND = "checkpoint_analytics_model_parity_assessment_v4"
REFRESH_BLOCKERS = (
    "analytics_worker:cpu_identity_changed_requires_parity_refresh",
    "analytics_worker:gpu_identity_changed_requires_parity_refresh",
)
WORKER_NAMES = {
    "cpu": "analytics_worker_openvino",
    "gpu": "analytics_worker_tensorrt",
}
RUNTIME_KEYS = {
    "cpu": "openvino_cpu",
    "gpu": "tensorrt_cuda",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,159}$")

CommandRunner = Callable[[list[str]], str]


class ModelParityV4Error(ContractError):
    """The refresh authority is incomplete, stale, or over-authorizing."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelParityV4Error(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ModelParityV4Error("model-parity v4 value is not canonical JSON") from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value).decode("ascii"))


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None, f"{label} is not a lowercase SHA-256")
    return value


def _image_id(value: Any, label: str) -> str:
    _require(type(value) is str and _IMAGE_RE.fullmatch(value) is not None, f"{label} is not an image ID")
    return value


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not a mapping")
    _require(set(value) == fields, f"{label} fields drifted")
    return value


def _relative(value: Any, label: str) -> str:
    _require(type(value) is str and value and "\\" not in value, f"{label} path is invalid")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, {"path", "size_bytes", "sha256"}, label)
    result = {
        "path": _relative(item.get("path"), label),
        "size_bytes": item.get("size_bytes"),
        "sha256": _sha(item.get("sha256"), f"{label} SHA-256"),
    }
    _require(type(result["size_bytes"]) is int and result["size_bytes"] > 0, f"{label} size is invalid")
    return result


def _physical_root(project_root: Path | str) -> Path:
    root = Path(os.path.abspath(os.fspath(project_root)))
    _require(root.is_dir() and not root.is_symlink() and root.resolve() == root, "project_root is unsafe")
    return root


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if getattr(os.path, "isjunction", lambda _value: False)(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _physical_file(root: Path, relative: str, label: str) -> Path:
    value = _relative(relative, label)
    lexical = Path(os.path.abspath(os.fspath(root.joinpath(*PurePosixPath(value).parts))))
    try:
        lexical.relative_to(root)
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise ModelParityV4Error(f"{label} is missing or escaped project_root") from error
    _require(
        lexical == resolved
        and lexical.is_file()
        and not _is_reparse(lexical)
        and stat.S_ISREG(lexical.lstat().st_mode),
        f"{label} is not one physical regular file",
    )
    return lexical


def file_descriptor(project_root: Path | str, path: Path | str, label: str = "artifact") -> dict[str, Any]:
    root = _physical_root(project_root)
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError as error:
            raise ModelParityV4Error(f"{label} escaped project_root") from error
    else:
        relative = candidate.as_posix()
    physical = _physical_file(root, relative, label)
    before = physical.stat()
    digest = hashlib.sha256()
    with physical.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = physical.stat()
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        f"{label} changed while hashing",
    )
    return {"path": relative, "size_bytes": before.st_size, "sha256": digest.hexdigest()}


def verify_descriptor(project_root: Path | str, value: Any, label: str) -> Path:
    expected = _descriptor(value, label)
    actual = file_descriptor(project_root, expected["path"], label)
    _require(actual == expected, f"{label} descriptor drifted")
    return _physical_root(project_root).joinpath(*PurePosixPath(expected["path"]).parts)


def _with_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _copy(value)
    result.pop("identity", None)
    result["identity"] = {
        "schema_version": 2,
        "algorithm": "sha256",
        "canonicalization": "sorted_compact_json_utf8_v2",
        "sha256": _canonical_sha(result),
    }
    return result


def _validate_identity(value: Mapping[str, Any], label: str) -> str:
    identity = _exact(
        value.get("identity"),
        {"schema_version", "algorithm", "canonicalization", "sha256"},
        f"{label} identity",
    )
    unsigned = {key: item for key, item in value.items() if key != "identity"}
    expected = _canonical_sha(unsigned)
    _require(
        identity == {
            "schema_version": 2,
            "algorithm": "sha256",
            "canonicalization": "sorted_compact_json_utf8_v2",
            "sha256": expected,
        },
        f"{label} identity drifted",
    )
    return expected


def validate_refresh_patch_v4(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only the exact two worker-identity refresh blockers."""

    _require(type(value) is dict, "qualification image patch is not an object")
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == image_refreeze.PATCH_KIND
        and value.get("authority") == "derived_physical_evidence_only",
        "qualification image patch header drifted",
    )
    declared = value.get("patch_sha256")
    _require(
        type(declared) is str
        and declared == image_refreeze.self_sha256(value, "patch_sha256"),
        "qualification image patch self-identity drifted",
    )
    _require(
        value.get("candidate_binding_eligible") is False
        and value.get("blockers") == list(REFRESH_BLOCKERS),
        "qualification image patch must contain the exact two analytics-worker parity refresh blockers",
    )
    workers = _exact(value.get("workers"), {"cpu", "gpu"}, "qualification image patch workers")
    receipts = _exact(
        value.get("receipts"),
        {"native_probe", "analytics_worker", "runtime_images"},
        "qualification image patch receipts",
    )
    worker_receipt = receipts.get("analytics_worker")
    _require(isinstance(worker_receipt, Mapping), "analytics-worker receipt descriptor is missing")
    receipt_sha = _sha(worker_receipt.get("receipt_sha256"), "analytics-worker receipt identity")
    projection: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        row = workers[resource]
        _require(isinstance(row, Mapping), f"{resource} patch worker is invalid")
        _require(
            row.get("name") == WORKER_NAMES[resource]
            and row.get("group") == "analytics_worker"
            and row.get("identity_changed") is True,
            f"{resource} patch worker coordinate drifted",
        )
        image = row.get("target_reference")
        _require(type(image) is str and image and "\n" not in image and "\r" not in image, f"{resource} patch worker image is invalid")
        image_id = _image_id(row.get("image_id"), f"{resource} patch worker image ID")
        previous = _image_id(row.get("previous_accepted_image_id"), f"{resource} previous worker image ID")
        _require(image_id != previous, f"{resource} patch worker image did not change")
        projection[resource] = {
            "image": image,
            "image_id": image_id,
            "base_image": str(row.get("base_reference") or ""),
            "base_image_id": _image_id(row.get("base_image_id"), f"{resource} patch base image ID"),
            "previous_accepted_image_id": previous,
            "source_set_sha256": _sha(row.get("source_set_sha256"), f"{resource} patch source set"),
            "receipt_sha256": receipt_sha,
        }
    return {
        "patch_sha256": declared,
        "refresh_blockers": list(REFRESH_BLOCKERS),
        "resolved_blockers": [],
        "workers": projection,
    }


def _execution_authority(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        {"path", "size_bytes", "sha256", "content_identity_sha256", "worker_projection_sha256"},
        "versioned execution config",
    )
    descriptor = _descriptor(
        {key: item[key] for key in ("path", "size_bytes", "sha256")},
        "versioned execution config",
    )
    return {
        **descriptor,
        "content_identity_sha256": _sha(item.get("content_identity_sha256"), "execution config content identity"),
        "worker_projection_sha256": _sha(item.get("worker_projection_sha256"), "execution config worker projection"),
    }


def _probe_authority(value: Any, resource: str) -> dict[str, Any]:
    item = _exact(
        value,
        {"path", "size_bytes", "sha256", "worker_implementation_sha256"},
        f"{resource} live runtime probe",
    )
    return {
        **_descriptor(
            {key: item[key] for key in ("path", "size_bytes", "sha256")},
            f"{resource} live runtime probe",
        ),
        "worker_implementation_sha256": _sha(
            item.get("worker_implementation_sha256"),
            f"{resource} worker implementation identity",
        ),
    }


def _source_descriptor(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        {"path", "size_bytes", "sha256"},
        "source schema-3 parity manifest",
    )
    return _descriptor(item, "source schema-3 parity manifest")


def build_patch_bound_manifest_v4(
    *,
    source_manifest: Mapping[str, Any],
    source_manifest_descriptor: Mapping[str, Any],
    image_patch: Mapping[str, Any],
    image_patch_descriptor: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the only permitted schema-4 manifest from a verified schema-3 source."""

    try:
        parity_v3.validate_manifest_identity(dict(source_manifest))
    except Exception as error:
        raise ModelParityV4Error(f"source schema-3 parity manifest is invalid: {error}") from error
    source = {key: _copy(item) for key, item in source_manifest.items() if key != "identity"}
    patch = validate_refresh_patch_v4(image_patch)
    patch_descriptor = _descriptor(image_patch_descriptor, "qualification image patch")
    config = _execution_authority(execution_config)
    _require(type(runtime_probes) is dict and set(runtime_probes) == {"cpu", "gpu"}, "live runtime probe coverage is not exact CPU/GPU")
    probes = {resource: _probe_authority(runtime_probes[resource], resource) for resource in ("cpu", "gpu")}

    source_workers = source["worker_runtime_registry"]
    dynamic_workers: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        runtime_key = RUNTIME_KEYS[resource]
        previous = source_workers[runtime_key]
        refreshed = patch["workers"][resource]
        _require(
            refreshed["previous_accepted_image_id"] == previous["image_id"]
            and refreshed["image"] == previous["image"]
            and refreshed["base_image"] == previous["base_image"],
            f"{resource} refresh changed more than the derived worker identity",
        )
        dynamic_workers[runtime_key] = {
            **_copy(previous),
            "base_image_id": refreshed["base_image_id"],
            "image_id": refreshed["image_id"],
            "worker_implementation_sha256": probes[resource]["worker_implementation_sha256"],
        }

    unsigned = _copy(source)
    unsigned["schema_version"] = SCHEMA_VERSION
    unsigned["artifact_kind"] = MANIFEST_KIND
    unsigned["manifest_id"] = f"checkpoint-analytics-model-parity-{patch['patch_sha256'][:16]}-v4"
    for resource in ("cpu", "gpu"):
        runtime_key = RUNTIME_KEYS[resource]
        producer_id = patch["workers"][resource]["base_image_id"]
        unsigned["matrix_binding"][resource]["image_id"] = producer_id
        unsigned["toolchain_registry"][runtime_key]["image_id"] = producer_id
    unsigned["worker_runtime_registry"] = {
        "execution_config": {
            "path": config["path"],
            "sha256": config["sha256"],
            "content_identity_sha256": config["content_identity_sha256"],
            "worker_projection_sha256": config["worker_projection_sha256"],
        },
        **dynamic_workers,
    }
    unsigned["refresh_authority"] = {
        "source_manifest": {
            **_source_descriptor(source_manifest_descriptor),
            "content_identity_sha256": source_manifest["identity"]["sha256"],
        },
        "image_identity_patch": {
            **patch_descriptor,
            "patch_sha256": patch["patch_sha256"],
            "refresh_blockers": patch["refresh_blockers"],
            "resolved_blockers": [],
            "workers": patch["workers"],
        },
        "runtime_probes": probes,
        "execution_config": config,
    }
    result = _with_identity(unsigned)
    validate_manifest_v4(result)
    return result


def _evidence_state(value: Mapping[str, Any]) -> str:
    states: set[str] = set()
    for branch in parity_v3.BRANCHES:
        evidence = value["workload_slots"][branch]["evidence"]
        _require(set(evidence) == set(parity_v3.EVIDENCE_NAMES), f"{branch} evidence coverage drifted")
        for name in parity_v3.EVIDENCE_NAMES:
            record = _exact(evidence[name], {"path", "sha256"}, f"{branch}/{name} evidence")
            if record.get("sha256") is None:
                _relative(record.get("path"), f"{branch}/{name} unmaterialized evidence")
                states.add("unmaterialized")
            else:
                _relative(record.get("path"), f"{branch}/{name} evidence")
                _sha(record.get("sha256"), f"{branch}/{name} evidence SHA-256")
                states.add("materialized")
    _require(len(states) == 1, "schema-4 evidence state is partially materialized")
    return next(iter(states))


def validate_manifest_v4(value: Mapping[str, Any]) -> None:
    _require(type(value) is dict, "model-parity v4 manifest is not an object")
    _validate_identity(value, "model-parity v4 manifest")
    unsigned = {key: _copy(item) for key, item in value.items() if key != "identity"}
    expected_fields = {
        "schema_version", "artifact_kind", "manifest_id", "claim_scope",
        "semantic_claim", "required_branches", "matrix_binding",
        "preprocessing_contract", "classification_contract", "evidence_policy",
        "source_registry", "toolchain_registry", "worker_runtime_registry",
        "workload_slots", "refresh_authority",
    }
    _exact(unsigned, expected_fields, "model-parity v4 manifest")
    _require(
        unsigned.get("schema_version") == SCHEMA_VERSION
        and unsigned.get("artifact_kind") == MANIFEST_KIND
        and _ID_RE.fullmatch(str(unsigned.get("manifest_id") or "")) is not None
        and str(unsigned["manifest_id"]).endswith("-v4"),
        "model-parity v4 schema/kind/manifest ID drifted",
    )
    authority = _exact(
        unsigned.get("refresh_authority"),
        {"source_manifest", "image_identity_patch", "runtime_probes", "execution_config"},
        "model-parity v4 refresh authority",
    )
    source = _exact(
        authority.get("source_manifest"),
        {"path", "size_bytes", "sha256", "content_identity_sha256"},
        "source schema-3 parity manifest authority",
    )
    _descriptor({key: source[key] for key in ("path", "size_bytes", "sha256")}, "source schema-3 parity manifest")
    _sha(source.get("content_identity_sha256"), "source schema-3 manifest content identity")
    patch = _exact(
        authority.get("image_identity_patch"),
        {"path", "size_bytes", "sha256", "patch_sha256", "refresh_blockers", "resolved_blockers", "workers"},
        "image identity patch authority",
    )
    _descriptor({key: patch[key] for key in ("path", "size_bytes", "sha256")}, "image identity patch")
    _sha(patch.get("patch_sha256"), "image identity patch self-identity")
    _require(
        patch.get("refresh_blockers") == list(REFRESH_BLOCKERS)
        and patch.get("resolved_blockers") == [],
        "model-parity v4 did not resolve only the exact two refresh blockers",
    )
    patch_workers = _exact(patch.get("workers"), {"cpu", "gpu"}, "image patch workers")
    probes = _exact(authority.get("runtime_probes"), {"cpu", "gpu"}, "live runtime probes")
    config = _execution_authority(authority.get("execution_config"))
    registry = _exact(
        unsigned.get("worker_runtime_registry"),
        {"execution_config", "openvino_cpu", "tensorrt_cuda"},
        "schema-4 worker runtime registry",
    )
    _require(registry["execution_config"] == {
        "path": config["path"],
        "sha256": config["sha256"],
        "content_identity_sha256": config["content_identity_sha256"],
        "worker_projection_sha256": config["worker_projection_sha256"],
    }, "schema-4 execution config authority drifted")
    for resource in ("cpu", "gpu"):
        worker = _exact(
            patch_workers[resource],
            {"image", "image_id", "base_image", "base_image_id", "previous_accepted_image_id", "source_set_sha256", "receipt_sha256"},
            f"{resource} image patch worker",
        )
        for field in ("image_id", "base_image_id", "previous_accepted_image_id"):
            _image_id(worker.get(field), f"{resource} patch worker {field}")
        _sha(worker.get("source_set_sha256"), f"{resource} patch worker source set")
        _sha(worker.get("receipt_sha256"), f"{resource} patch worker receipt")
        probe = _probe_authority(probes[resource], resource)
        runtime = registry[RUNTIME_KEYS[resource]]
        matrix = unsigned["matrix_binding"][resource]
        toolchain = unsigned["toolchain_registry"][RUNTIME_KEYS[resource]]
        _require(
            runtime.get("image") == worker["image"]
            and runtime.get("image_id") == worker["image_id"]
            and runtime.get("base_image") == worker["base_image"]
            and runtime.get("base_image_id") == worker["base_image_id"]
            and runtime.get("worker_implementation_sha256") == probe["worker_implementation_sha256"],
            f"{resource} patch/probe/runtime worker cross-binding drifted",
        )
        _require(
            matrix.get("image") == worker["base_image"]
            and matrix.get("image_id") == worker["base_image_id"]
            and toolchain.get("image") == worker["base_image"]
            and toolchain.get("image_id") == worker["base_image_id"],
            f"{resource} refrozen producer matrix/toolchain provenance drifted",
        )
    _evidence_state(unsigned)

    # Reuse every frozen semantic validator after replacing only the explicitly
    # dynamic worker registry with the canonical schema-3 registry.  This makes
    # any non-worker contract drift fail exactly as schema 3 would fail it.
    try:
        canonical_source = parity_v3.load_parity_manifest(parity_v3.DEFAULT_MANIFEST)
        projected = _copy(unsigned)
        projected.pop("refresh_authority")
        projected["schema_version"] = parity_v3.SCHEMA_VERSION
        projected["artifact_kind"] = parity_v3.ARTIFACT_KIND
        projected["manifest_id"] = canonical_source["manifest_id"]
        projected["worker_runtime_registry"] = _copy(canonical_source["worker_runtime_registry"])
        for resource in ("cpu", "gpu"):
            runtime_key = RUNTIME_KEYS[resource]
            projected["matrix_binding"][resource]["image_id"] = canonical_source[
                "matrix_binding"
            ][resource]["image_id"]
            projected["toolchain_registry"][runtime_key]["image_id"] = canonical_source[
                "toolchain_registry"
            ][runtime_key]["image_id"]
        parity_v3._validate_manifest_v3(projected)
    except Exception as error:
        raise ModelParityV4Error(f"schema-4 frozen semantic projection drifted: {error}") from error


def _read_yaml_physical(path: Path) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        raw = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ModelParityV4Error(f"invalid model-parity v4 manifest: {error}") from error
    _require(type(raw) is dict and "identity" not in raw, "physical model-parity v4 manifest must not carry a derived identity")
    return raw


def load_parity_manifest_v4(
    path: Path | str,
    *,
    project_root: Path | str = PROJECT_ROOT,
) -> dict[str, Any]:
    root = _physical_root(project_root)
    descriptor = file_descriptor(root, path, "model-parity v4 manifest")
    manifest_path = _physical_file(root, descriptor["path"], "model-parity v4 manifest")
    raw = _read_yaml_physical(manifest_path)
    value = _with_identity(raw)
    validate_manifest_v4(value)
    authority = value["refresh_authority"]

    source_path = verify_descriptor(root, {
        key: authority["source_manifest"][key] for key in ("path", "size_bytes", "sha256")
    }, "source schema-3 parity manifest")
    try:
        source = parity_v3.load_parity_manifest(source_path)
    except Exception as error:
        raise ModelParityV4Error(f"source schema-3 parity manifest rejected: {error}") from error
    _require(
        source["identity"]["sha256"] == authority["source_manifest"]["content_identity_sha256"],
        "source schema-3 parity manifest content identity drifted",
    )

    patch_path = verify_descriptor(root, {
        key: authority["image_identity_patch"][key] for key in ("path", "size_bytes", "sha256")
    }, "qualification image patch")
    try:
        patch_value = image_refreeze.load_identity_patch(
            project_root=root,
            patch_path=patch_path,
            require_candidate_eligible=False,
        )
    except Exception as error:
        raise ModelParityV4Error(f"qualification image patch rejected: {error}") from error
    patch_projection = validate_refresh_patch_v4(patch_value)
    _require(
        authority["image_identity_patch"]["patch_sha256"] == patch_projection["patch_sha256"]
        and authority["image_identity_patch"]["workers"] == patch_projection["workers"],
        "qualification image patch authority is stale",
    )

    config_path = verify_descriptor(root, {
        key: authority["execution_config"][key] for key in ("path", "size_bytes", "sha256")
    }, "versioned execution config")
    try:
        from checkpoint_gstreamer_analytics_sidecar import load_execution_config
        config_value = load_execution_config(config_path)
    except Exception as error:
        raise ModelParityV4Error(f"versioned execution config rejected: {error}") from error
    _require(
        config_value["identity"]["sha256"] == authority["execution_config"]["content_identity_sha256"]
        and canonical_sha256(config_value["workers"]) == authority["execution_config"]["worker_projection_sha256"],
        "versioned execution config content/worker projection drifted",
    )
    # The execution config is bound to the unmaterialized v4 manifest used by
    # all 480 requests.  The accepted manifest is a distinct commit-last copy
    # whose only permitted difference is its exact 32 evidence references.
    bound_manifest_relative = _relative(
        config_value["model_parity_manifest"],
        "versioned execution config model-parity manifest",
    )
    if bound_manifest_relative != descriptor["path"]:
        bound_path = _physical_file(
            root,
            bound_manifest_relative,
            "execution-bound base model-parity v4 manifest",
        )
        bound_value = _with_identity(_read_yaml_physical(bound_path))
        validate_manifest_v4(bound_value)
        _require(
            _evidence_state(bound_value) == "unmaterialized",
            "execution-bound base model-parity v4 manifest is not unmaterialized",
        )
        projected_current = {
            key: _copy(item) for key, item in value.items() if key != "identity"
        }
        bound_unsigned = {
            key: _copy(item) for key, item in bound_value.items() if key != "identity"
        }
        for branch in parity_v3.BRANCHES:
            projected_current["workload_slots"][branch]["evidence"] = _copy(
                bound_unsigned["workload_slots"][branch]["evidence"]
            )
        _require(
            projected_current == bound_unsigned,
            "accepted model-parity v4 manifest drifted from its execution-bound base",
        )

    for resource in ("cpu", "gpu"):
        probe_path = verify_descriptor(root, {
            key: authority["runtime_probes"][resource][key] for key in ("path", "size_bytes", "sha256")
        }, f"{resource} live runtime probe")
        try:
            probe_raw = probe_path.read_bytes()
            probe_value = json.loads(probe_raw.decode("utf-8"))
            _require(_canonical(probe_value) + b"\n" == probe_raw, f"{resource} runtime probe is not canonical JSON")
            checked = validate_runtime_probe(
                probe_value,
                engine=config_value["workers"][resource]["engine"],
            )
        except Exception as error:
            raise ModelParityV4Error(f"{resource} live runtime probe rejected: {error}") from error
        _require(
            checked["worker_implementation_sha256"]
            == authority["runtime_probes"][resource]["worker_implementation_sha256"]
            == config_value["workers"][resource]["worker_implementation_sha256"],
            f"{resource} live probe/config implementation identity drifted",
        )
        patch_worker = authority["image_identity_patch"]["workers"][resource]
        config_worker = config_value["workers"][resource]
        _require(
            config_worker["image"] == patch_worker["image"]
            and config_worker["image_id"] == patch_worker["image_id"]
            and config_worker["base_image"] == patch_worker["base_image"]
            and config_worker["base_image_id"] == patch_worker["base_image_id"],
            f"{resource} patch/config worker identity drifted",
        )

    expected = build_patch_bound_manifest_v4(
        source_manifest=source,
        source_manifest_descriptor={
            key: authority["source_manifest"][key] for key in ("path", "size_bytes", "sha256")
        },
        image_patch=patch_value,
        image_patch_descriptor={
            key: authority["image_identity_patch"][key] for key in ("path", "size_bytes", "sha256")
        },
        execution_config=authority["execution_config"],
        runtime_probes=authority["runtime_probes"],
    )
    observed_unsigned = {key: _copy(item) for key, item in value.items() if key != "identity"}
    expected_unsigned = {key: _copy(item) for key, item in expected.items() if key != "identity"}
    for branch in parity_v3.BRANCHES:
        expected_unsigned["workload_slots"][branch]["evidence"] = _copy(
            observed_unsigned["workload_slots"][branch]["evidence"]
        )
    _require(observed_unsigned == expected_unsigned, "model-parity v4 manifest is stale or changed outside the permitted evidence projection")
    _require(file_descriptor(root, descriptor["path"], "post-load model-parity v4 manifest") == descriptor, "model-parity v4 manifest drifted while loading")
    return value


def _default_runner(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=120.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ModelParityV4Error(f"external command failed: {command[0]}") from error
    _require(completed.returncode == 0, f"external command failed: {command[0]}")
    return completed.stdout.strip()


def assess_model_parity_v4(
    manifest_path: Path | str,
    *,
    project_root: Path | str = PROJECT_ROOT,
    command_runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    root = _physical_root(project_root)
    manifest = load_parity_manifest_v4(manifest_path, project_root=root)
    blockers: list[str] = []
    runtime_images: dict[str, Any] = {}
    worker_images: dict[str, Any] = {}
    for resource in ("cpu", "gpu"):
        base = manifest["matrix_binding"][resource]
        inspected = parity_v3._inspect_image(str(base["image"]), command_runner)
        runtime_images[resource] = inspected or {"reference": base["image"], "available": False}
        if inspected is None:
            blockers.append(f"runtime_image_missing:{resource}")
        elif inspected["image_id"] != base["image_id"]:
            blockers.append(f"runtime_image_id_mismatch:{resource}")
        patch_worker = manifest["refresh_authority"]["image_identity_patch"]["workers"][resource]
        worker_inspected = parity_v3._inspect_image(str(patch_worker["image"]), command_runner)
        worker_images[resource] = worker_inspected or {"reference": patch_worker["image"], "available": False}
        if worker_inspected is None:
            blockers.append(f"worker_runtime_image_missing:{resource}")
        elif worker_inspected["image_id"] != patch_worker["image_id"]:
            blockers.append(f"worker_runtime_image_id_mismatch:{resource}")
    branches = {
        branch: parity_v3._assess_slot_v2(branch, manifest, root=root)
        for branch in parity_v3.BRANCHES
    }
    for branch in parity_v3.BRANCHES:
        blockers.extend(branches[branch]["blockers"])
    blockers = list(dict.fromkeys(blockers))
    result = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "manifest_identity_sha256": manifest["identity"]["sha256"],
        "patch_sha256": manifest["refresh_authority"]["image_identity_patch"]["patch_sha256"],
        "claim_scope": manifest["claim_scope"],
        "semantic_claim": manifest["semantic_claim"],
        "publication_ready": not blockers,
        "refresh_blockers_resolved": list(REFRESH_BLOCKERS) if not blockers else [],
        "openvino_gpu_counted_as_nvidia_cuda": False,
        "network_or_download_performed": False,
        "permitted_external_command": "docker image inspect only",
        "claimed_aggregate_metrics_accepted": False,
        "raw_per_sample_outputs_recomputed": all(branches[branch]["recomputed_parity"] is not None for branch in parity_v3.BRANCHES),
        "runtime_images": runtime_images,
        "worker_runtime_images": worker_images,
        "local_model_inventory": parity_v3._model_inventory(root),
        "branches": branches,
        "blockers": blockers,
    }
    return _with_identity(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load or assess patch-bound model parity v4")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("manifest", "assess"):
        command = commands.add_parser(name)
        command.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
        command.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            value = load_parity_manifest_v4(args.config, project_root=args.project_root)
            code = 0
        else:
            value = assess_model_parity_v4(args.config, project_root=args.project_root)
            code = 0 if value["publication_ready"] else 78
    except (OSError, ModelParityV4Error) as error:
        value = {"schema_version": 4, "artifact_kind": "checkpoint_model_parity_v4_error", "error": str(error)}
        code = 78
    print(_canonical(value).decode("ascii"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSESSMENT_KIND", "MANIFEST_KIND", "ModelParityV4Error",
    "REFRESH_BLOCKERS", "SCHEMA_VERSION", "assess_model_parity_v4",
    "build_patch_bound_manifest_v4", "file_descriptor",
    "load_parity_manifest_v4", "validate_manifest_v4",
    "validate_refresh_patch_v4", "verify_descriptor",
]
