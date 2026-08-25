#!/usr/bin/env python3
"""Materialize the DeepStream half of the frozen qualification inventory.

This phase intentionally contains no pilot claims.  It binds ten distinct
physical implementation/emitter envelopes to one exact local ABI-v3 image.
The four-system coordinator may consume the fragment only as a bootstrap
inventory; publication readiness remains false until all eight DeepStream
pilot cells pass the unmodified default validators.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_publication_qualification_system_fragment_v1"
SYSTEM = "deepstream"
FRAGMENT_FILENAME = "qualification_fragment.json"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
PILOT_BLOCKER = "deepstream_qualification_pilots_not_materialized"
EXPECTED_BASE_IMAGE = (
    "nvcr.io/nvidia/deepstream@sha256:"
    "c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759"
)
EXPECTED_ENTRYPOINT = "/usr/local/bin/vast_deepstream_publication_runtime_v3"
RESOURCE_RUNTIME_BACKEND = "NVIDIA-DeepStream-7.0.0-native-sdk-abi3"
EXPECTED_GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
EXPECTED_GPU_DRIVER = "610.47"
PROTOCOL_IDENTITY_SHA256 = "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff"
PREPROCESSING_CONTRACT_SHA256 = "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090"
ACCEPTED_PARITY = (
    "configs/checkpoint_analytics_model_parity.accepted.yaml",
    25229,
    "a570b8cc4bcc66119930f01239ed0fb2de7accd449b769d5a4b0511d70fb72b6",
)
ACCEPTED_PARITY_CONTENT_IDENTITY = "05059ee44a21a82728f2608dc13804f55cc7df9eeedb245ad2d63a7c1ca46ee8"
ACCEPTED_ASSESSMENT = (
    "configs/checkpoint_analytics_model_parity.accepted.assessment.json",
    1570,
    "e0b5200f662662d9b212e0bcfa50e904a9d8f023ca418ee9abdbd50c237a0152",
)
ACCEPTED_ASSESSMENT_IDENTITY = "a1de951cacf8a3d37d43f5e1f96e3d13323b40c4504d457cffff41037d1bba49"
CANONICAL_ASSESSMENT_IDENTITY = "7b0c185745211fe8779718d2a3f1c5af122873625eee9cb37d974f0d68496eb6"
ACCEPTED_RECEIPT = (
    "configs/checkpoint_analytics_model_parity.accepted.acceptance_receipt.json",
    11656,
    "26da3401dac32a2ded7b012fa0af74ad99d783aa531feadedf936196fefc1c0b",
)
ACCEPTED_RECEIPT_IDENTITY = "59de449e508bcb0e4287a5898b2b7c8af3fdac70c7361e74f299e9e04e85da3d"
ANALYTICS_INDEX = (
    "artifacts/analytics_execution_bindings/publication_v3/index.json",
    1877,
    "8ff3d495b80024eca2067a43239fc984961629465288d307d7f8f4de32c31e87",
)
ANALYTICS_INDEX_IDENTITY = "6fb0a64f19d61ef7021a50ae35f04f55b344f0fe67911d29d43e03a00ebb635b"
ANALYTICS_BINDINGS_IDENTITY = "7504b2a73c886cbda01b3d1d02c1dab360146285c3dba2cdec6496b7510956ab"
MODEL_PARITY_MANIFEST_IDENTITY = "4065e9a766bbdf82771534ec1f5f13f32f4d6ab6de9ac27143663cc27634fd80"
EXECUTION_CONFIG_IDENTITY = "3daed67a3e4c6549bf463b929e5de840e5aab7daacac75fff328f624b867b512"
WORKER_IMAGE_IDS = {
    "cpu": "sha256:e2b01f8f40da08fc59d671e19a7f4eca6dd7d46678de0138ab7af51b09cb9b03",
    "gpu": "sha256:2ff600e743e6fc089ace1ea40894d73581fcda8007fa758fd0f32eb9b1c72f09",
}
WORKER_IMPLEMENTATIONS = {
    "cpu": "f15ab5fd7d846376ccba55e55b663f4d16e114ef4cf5519794795cde7a416f8b",
    "gpu": "eb6fce9ec42f26e0d38263053aedbb8d9c247c1872be39d67d7f3c0da4c48ab7",
}
RUNTIME_PROBES = {
    "cpu": (
        "artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json",
        659,
        "e6008e33e137d315f1672adb2e241004e2ea08f1220467dcbf089a566060ddfb",
    ),
    "gpu": (
        "artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json",
        654,
        "24986e7aadd93ab9bb72704c5a83d568bc0e4fd70154803e303b3bda5aa4a752",
    ),
}
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GPU_UUID_RE = re.compile(r"^GPU-[0-9a-fA-F-]{16,}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
POLICY_RUNTIME_FIELDS = {
    "runtime_backend",
    "device_api",
    "gpu_id",
    "worker_image_digest",
    "implementation_version",
    "terminal_detector",
    "terminal_backend",
}
RESOURCE_RUNTIME_FIELDS = {
    "runtime_backend",
    "analytics_device_api",
    "decoder_device_api",
    "worker_image_digest",
    "implementation_version",
    "hardware_binding_id",
}
BINDING_FIELDS = {
    "role",
    "branch",
    "resource",
    "path",
    "sha256",
    "size",
    "implementation_id",
    "emitter_id",
    "runtime_identity",
}
POLICY_SOURCE_PATHS = (
    "scripts/checkpoint_native_policy_runtime.py",
    "scripts/checkpoint_deepstream_protocol_adapter.py",
    "scripts/checkpoint_deepstream_protocol_bridge.py",
)
RESOURCE_SOURCE_PATHS = (
    "scripts/checkpoint_deepstream_sdk_runtime.py",
    "scripts/checkpoint_deepstream_resource_runtime_v3.py",
    "scripts/checkpoint_gstreamer_runtime.py",
    "scripts/collect_metrics.py",
    "scripts/full_resource_contract.py",
    "scripts/resource_interval_contract.py",
)
POLICY_EVIDENCE_ROLES = (
    "checkpoint_acceptance",
    "publication_policy_decisions.jsonl",
    "resource_intervals",
    "ingress_ledger",
    "topology_events",
    "frames",
    "frame_events",
    "branch_terminals",
)
RESOURCE_EVIDENCE_ROLES = (
    "checkpoint_acceptance",
    "frames",
    "frame_events",
    "ingress_ledger",
    "topology_events",
    "resource_intervals",
    "hardware_resource_samples",
    "fanout_work_counters",
)


class DeepStreamQualificationFragmentV1Error(RuntimeError):
    """The physical binding inventory or exact runtime identity is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamQualificationFragmentV1Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DeepStreamQualificationFragmentV1Error(
            "DeepStream qualification material is not canonical JSON"
        ) from exc


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(dict(value))).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _physical_file(root: Path, relative: str, label: str) -> Path:
    _require(
        type(relative) is str
        and bool(relative)
        and "\\" not in relative
        and not Path(relative).is_absolute()
        and Path(relative).as_posix() == relative
        and not any(part in ("", ".", "..") for part in Path(relative).parts),
        f"{label} path is not normalized",
    )
    candidate = root.joinpath(*Path(relative).parts)
    try:
        before = candidate.lstat()
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DeepStreamQualificationFragmentV1Error(
            f"{label} physical file is missing or escapes project_root"
        ) from exc
    _require(
        stat.S_ISREG(before.st_mode)
        and not candidate.is_symlink()
        and int(before.st_nlink) == 1,
        f"{label} must be one physical regular file without hardlinks",
    )
    return candidate


def _descriptor(root: Path, relative: str, label: str) -> dict[str, Any]:
    path = _physical_file(root, relative, label)
    before = path.stat()
    sha = _sha256_file(path)
    after = path.stat()
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
        f"{label} changed while hashing",
    )
    return {
        "path": relative,
        "size": int(after.st_size),
        "sha256": sha,
    }


def _exact_descriptor(
    root: Path, exact: tuple[str, int, str], label: str
) -> dict[str, Any]:
    observed = _descriptor(root, exact[0], label)
    _require(
        observed
        == {"path": exact[0], "size": int(exact[1]), "sha256": exact[2]},
        f"{label} exact size/SHA-256 drifted",
    )
    return observed


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeepStreamQualificationFragmentV1Error(f"invalid {label}: {exc}") from exc
    _require(type(value) is dict, f"{label} must be a JSON object")
    return value


def _inspect_identity(image_inspect: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(image_inspect)
    image_id = str(value.get("Id", ""))
    config = value.get("Config")
    _require(
        IMAGE_ID_RE.fullmatch(image_id) is not None
        and value.get("Os") == "linux"
        and value.get("Architecture") == "amd64"
        and type(config) is dict,
        "DeepStream image identity is invalid",
    )
    labels = config.get("Labels")
    _require(type(labels) is dict, "DeepStream image labels are missing")
    expected_labels = {
        "org.vast.component": "deepstream-checkpoint-native-sdk-runtime",
        "org.vast.publication-runtime-abi": "3",
        "org.vast.publication-ready": "false",
        "org.vast.base-image-digest": EXPECTED_BASE_IMAGE,
    }
    for key, expected in expected_labels.items():
        _require(labels.get(key) == expected, f"DeepStream image {key} label drifted")
    source_sha = str(labels.get("org.vast.runtime-source-sha256", ""))
    _require(SHA_RE.fullmatch(source_sha) is not None, "DeepStream runtime source SHA-256 is invalid")
    _require(
        config.get("Entrypoint") == [EXPECTED_ENTRYPOINT],
        "DeepStream image entrypoint drifted",
    )
    env_values = config.get("Env")
    _require(type(env_values) is list, "DeepStream image environment is invalid")
    environment = {
        text.split("=", 1)[0]: text.split("=", 1)[1]
        for text in env_values
        if type(text) is str and "=" in text
    }
    _require(environment.get("DS_VERSION") == "7.0.0", "DeepStream SDK version drifted")
    repo_digests = value.get("RepoDigests")
    expected_repo = f"vast/deepstream-publication-runtime-v3@{image_id}"
    _require(
        type(repo_digests) is list and expected_repo in repo_digests,
        "DeepStream exact repository digest is not materialized",
    )
    return {
        "image_id": image_id,
        "repository_digest": expected_repo,
        "base_image_digest": EXPECTED_BASE_IMAGE,
        "runtime_source_sha256": source_sha,
        "deepstream_version": "7.0.0",
        "entrypoint": EXPECTED_ENTRYPOINT,
    }


def _terminal_identities(
    root: Path, gpu_uuid: str
) -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, Any]]:
    bindings_root = root / "artifacts/analytics_execution_bindings/publication_v3"
    parity_descriptor = _exact_descriptor(root, ACCEPTED_PARITY, "accepted model parity")
    assessment_descriptor = _exact_descriptor(
        root, ACCEPTED_ASSESSMENT, "accepted model parity assessment"
    )
    receipt_descriptor = _exact_descriptor(
        root, ACCEPTED_RECEIPT, "accepted model parity receipt"
    )
    index_descriptor = _exact_descriptor(
        root, ANALYTICS_INDEX, "analytics execution binding index"
    )
    assessment = _load_json(
        root / ACCEPTED_ASSESSMENT[0], "accepted model parity assessment"
    )
    receipt = _load_json(
        root / ACCEPTED_RECEIPT[0], "accepted model parity receipt"
    )
    accepted_manifest_ref = {
        "path": ACCEPTED_PARITY[0],
        "size_bytes": ACCEPTED_PARITY[1],
        "sha256": ACCEPTED_PARITY[2],
    }
    accepted_assessment_ref = {
        "path": ACCEPTED_ASSESSMENT[0],
        "size_bytes": ACCEPTED_ASSESSMENT[1],
        "sha256": ACCEPTED_ASSESSMENT[2],
    }
    _require(
        assessment.get("artifact_kind")
        == "vast_checkpoint_model_parity_accepted_assessment"
        and assessment.get("accepted_manifest") == accepted_manifest_ref
        and assessment.get("accepted_manifest_content_identity_sha256")
        == ACCEPTED_PARITY_CONTENT_IDENTITY
        and assessment.get("assessment_sha256") == ACCEPTED_ASSESSMENT_IDENTITY
        and assessment.get("canonical_assessment_identity_sha256")
        == CANONICAL_ASSESSMENT_IDENTITY
        and assessment.get("publication_ready") is True
        and assessment.get("blockers") == [],
        "accepted model parity assessment identity drifted",
    )
    _require(
        receipt.get("artifact_kind")
        == "vast_checkpoint_model_parity_acceptance_receipt"
        and receipt.get("accepted_manifest") == accepted_manifest_ref
        and receipt.get("accepted_assessment") == accepted_assessment_ref
        and receipt.get("accepted_manifest_content_identity_sha256")
        == ACCEPTED_PARITY_CONTENT_IDENTITY
        and receipt.get("accepted_assessment_identity_sha256")
        == ACCEPTED_ASSESSMENT_IDENTITY
        and receipt.get("canonical_assessment_identity_sha256")
        == CANONICAL_ASSESSMENT_IDENTITY
        and receipt.get("receipt_sha256") == ACCEPTED_RECEIPT_IDENTITY
        and receipt.get("publication_ready") is True
        and receipt.get("blockers") == [],
        "accepted model parity receipt identity drifted",
    )
    registry = receipt.get("worker_runtime_registry")
    toolchain = receipt.get("toolchain_registry")
    _require(
        type(registry) is dict
        and type(registry.get("openvino_cpu")) is dict
        and registry["openvino_cpu"].get("image_id") == WORKER_IMAGE_IDS["cpu"]
        and registry["openvino_cpu"].get("worker_implementation_sha256")
        == WORKER_IMPLEMENTATIONS["cpu"]
        and type(registry.get("tensorrt_cuda")) is dict
        and registry["tensorrt_cuda"].get("image_id") == WORKER_IMAGE_IDS["gpu"]
        and registry["tensorrt_cuda"].get("worker_implementation_sha256")
        == WORKER_IMPLEMENTATIONS["gpu"]
        and type(toolchain) is dict
        and type(toolchain.get("tensorrt_cuda")) is dict
        and toolchain["tensorrt_cuda"].get("gpu_uuid") == gpu_uuid
        and str(toolchain["tensorrt_cuda"].get("driver_version"))
        == EXPECTED_GPU_DRIVER,
        "accepted endpoint worker/GPU registry drifted",
    )
    index = _load_json(root / ANALYTICS_INDEX[0], "analytics execution binding index")
    _require(
        index.get("artifact_kind")
        == "vast_analytics_execution_worker_binding_set"
        and (index.get("identity") or {}).get("sha256")
        == ANALYTICS_INDEX_IDENTITY
        and index.get("bindings_identity_sha256") == ANALYTICS_BINDINGS_IDENTITY
        and index.get("model_parity_manifest_identity_sha256")
        == MODEL_PARITY_MANIFEST_IDENTITY
        and index.get("execution_config_identity_sha256")
        == EXECUTION_CONFIG_IDENTITY
        and index.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256
        and index.get("worker_implementation_sha256")
        == {
            "openvino_cpu": WORKER_IMPLEMENTATIONS["cpu"],
            "tensorrt_cuda": WORKER_IMPLEMENTATIONS["gpu"],
        },
        "analytics execution binding index identity drifted",
    )
    index_files = index.get("files")
    _require(type(index_files) is list and len(index_files) == 8, "analytics binding set drifted")
    indexed: dict[str, dict[str, Any]] = {}
    for item in index_files:
        _require(
            type(item) is dict and set(item) == {"path", "bytes", "sha256"}
            and type(item["path"]) is str and item["path"] not in indexed
            and type(item["bytes"]) is int and item["bytes"] > 0
            and SHA_RE.fullmatch(str(item["sha256"])) is not None,
            "analytics binding index row drifted",
        )
        indexed[str(item["path"])] = dict(item)
    probes = {
        resource: _load_json(root / RUNTIME_PROBES[resource][0], f"{resource} runtime probe")
        for resource in RESOURCES
    }
    probe_descriptors = {
        resource: _exact_descriptor(
            root, RUNTIME_PROBES[resource], f"{resource} runtime probe"
        )
        for resource in RESOURCES
    }
    expected_probe = {
        "cpu": {
            "engine": "openvino_cpu",
            "runtime_name": "OpenVINO",
            "native_inference_api": "openvino.CompiledModel.__call__",
            "device_api": "CPU",
        },
        "gpu": {
            "engine": "tensorrt_cuda",
            "runtime_name": "TensorRT",
            "native_inference_api": "nvinfer1::IExecutionContext::enqueueV3",
            "device_api": "NVIDIA_CUDA",
            "device_id": gpu_uuid,
        },
    }
    result: dict[tuple[str, str], dict[str, str]] = {}
    for resource in RESOURCES:
        probe = probes[resource]
        _require(
            all(probe.get(key) == expected for key, expected in expected_probe[resource].items()),
            f"DeepStream {resource} terminal runtime probe identity drifted",
        )
        _require(
            probe.get("artifact_kind")
            == "vast_analytics_execution_worker_runtime_probe"
            and probe.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256
            and probe.get("worker_implementation_sha256")
            == WORKER_IMPLEMENTATIONS[resource],
            f"DeepStream {resource} runtime probe pin drifted",
        )
        backend = (
            f"analytics-execution:{probe['engine']};runtime={probe['runtime_name']};"
            f"native_api={probe['native_inference_api']};"
            f"device={probe['device_api']}:{probe['device_id']}"
        )
        suffix = "openvino_cpu" if resource == "cpu" else "tensorrt_cuda"
        expected_kind = (
            "vast_openvino_execution_worker_binding"
            if resource == "cpu"
            else "vast_tensorrt_execution_worker_binding"
        )
        for branch in BRANCHES:
            path = bindings_root / f"{branch}.{suffix}.json"
            filename = path.name
            item = indexed.get(filename)
            _require(type(item) is dict, f"DeepStream {branch}/{resource} binding is not indexed")
            _exact_descriptor(
                root,
                (path.relative_to(root).as_posix(), int(item["bytes"]), str(item["sha256"])),
                f"{branch}/{resource} analytics binding",
            )
            binding = _load_json(path, f"{branch}/{resource} analytics binding")
            _require(
                binding.get("artifact_kind") == expected_kind
                and binding.get("branch") == branch
                and type(binding.get("model_id")) is str
                and bool(binding["model_id"]),
                f"DeepStream {branch}/{resource} terminal binding identity drifted",
            )
            worker_image = str(binding.get("worker_image_id", ""))
            worker_implementation = str(probe.get("worker_implementation_sha256", ""))
            _require(
                IMAGE_ID_RE.fullmatch(worker_image) is not None
                and SHA_RE.fullmatch(worker_implementation) is not None,
                f"DeepStream {branch}/{resource} worker identity is incomplete",
            )
            _require(
                worker_image == WORKER_IMAGE_IDS[resource]
                and worker_implementation == WORKER_IMPLEMENTATIONS[resource]
                and binding.get("preprocessing_contract_sha256")
                == PREPROCESSING_CONTRACT_SHA256,
                f"DeepStream {branch}/{resource} accepted worker pin drifted",
            )
            result[(branch, resource)] = {
                "terminal_detector": str(binding["model_id"]),
                "terminal_backend": backend,
                "worker_image_id": worker_image,
                "worker_implementation_sha256": worker_implementation,
                "binding_path": path.relative_to(root).as_posix(),
                "probe_path": RUNTIME_PROBES[resource][0],
            }
    _require(set(indexed) == {Path(value["binding_path"]).name for value in result.values()}, "analytics binding index coverage drifted")
    summary = {
        "accepted_model_parity_manifest": {
            **parity_descriptor,
            "content_identity_sha256": ACCEPTED_PARITY_CONTENT_IDENTITY,
        },
        "accepted_assessment": {
            **assessment_descriptor,
            "assessment_identity_sha256": ACCEPTED_ASSESSMENT_IDENTITY,
            "canonical_identity_sha256": CANONICAL_ASSESSMENT_IDENTITY,
        },
        "accepted_receipt": {
            **receipt_descriptor,
            "receipt_identity_sha256": ACCEPTED_RECEIPT_IDENTITY,
        },
        "analytics_binding_index": {
            **index_descriptor,
            "identity_sha256": ANALYTICS_INDEX_IDENTITY,
            "bindings_identity_sha256": ANALYTICS_BINDINGS_IDENTITY,
        },
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "preprocessing_contract_sha256": PREPROCESSING_CONTRACT_SHA256,
        "worker_image_ids": dict(WORKER_IMAGE_IDS),
        "worker_implementations": dict(WORKER_IMPLEMENTATIONS),
        "runtime_probes": probe_descriptors,
    }
    return result, summary


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    payload = _canonical_bytes(dict(value)) + b"\n"
    if path.exists():
        try:
            info = path.lstat()
            current = path.read_bytes()
        except OSError as exc:
            raise DeepStreamQualificationFragmentV1Error(
                f"immutable binding collision: {path}"
            ) from exc
        _require(
            stat.S_ISREG(info.st_mode)
            and not path.is_symlink()
            and int(info.st_nlink) == 1
            and current == payload,
            f"immutable binding collision or drift: {path}",
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _artifact(
    *,
    role: str,
    branch: str,
    resource: str,
    implementation_id: str,
    emitter_id: str,
    runtime_identity: Mapping[str, Any],
    image: Mapping[str, Any],
    accepted_model_material: Mapping[str, Any],
    sources: Sequence[Mapping[str, Any]],
    evidence_roles: Sequence[str],
    blockers: Sequence[str],
) -> dict[str, Any]:
    material = {
        "schema_version": 1,
        "artifact_kind": "vast_deepstream_qualification_physical_binding_v1",
        "status": "implemented_pilots_pending",
        "system": SYSTEM,
        "role": role,
        "branch": branch,
        "resource": resource,
        "implementation_id": implementation_id,
        "emitter_id": emitter_id,
        "runtime_identity": dict(runtime_identity),
        "image_identity": dict(image),
        "accepted_model_material": dict(accepted_model_material),
        "implementation_sources": list(sources),
        "native_evidence_contract": {
            "telemetry_source": "native",
            "roles": list(evidence_roles),
        },
        "blockers": list(blockers),
        "publication_ready": False,
    }
    material["binding_sha256"] = _canonical_sha(material)
    return material


def materialize_deepstream_qualification_fragment(
    *,
    project_root: Path,
    output_dir: Path,
    image_inspect: Mapping[str, Any],
    gpu_uuid: str,
) -> Path:
    root = Path(project_root).resolve(strict=True)
    _require(root.is_dir() and not root.is_symlink(), "project_root must be physical")
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = root / destination
    try:
        destination = destination.resolve(strict=False)
        destination.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DeepStreamQualificationFragmentV1Error(
            "DeepStream qualification output escapes project_root"
        ) from exc
    _require(
        GPU_UUID_RE.fullmatch(gpu_uuid) is not None
        and gpu_uuid == EXPECTED_GPU_UUID,
        "DeepStream GPU UUID is invalid or differs from accepted parity",
    )
    image = _inspect_identity(image_inspect)
    terminals, accepted_model_material = _terminal_identities(root, gpu_uuid)
    source_sha = str(image["runtime_source_sha256"])
    version = f"deepstream-publication-runtime-v3:{source_sha}"
    runtime_backend = RESOURCE_RUNTIME_BACKEND

    policy_common = [_descriptor(root, value, value) for value in POLICY_SOURCE_PATHS]
    resource_common = [_descriptor(root, value, value) for value in RESOURCE_SOURCE_PATHS]
    bindings_dir = destination / "bindings"
    policy_bindings: list[dict[str, Any]] = []
    resource_bindings: list[dict[str, Any]] = []
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()
    artifact_identities: set[tuple[int, int]] = set()

    for branch in BRANCHES:
        for resource in RESOURCES:
            terminal = terminals[(branch, resource)]
            blockers: list[str] = []
            implementation_id = (
                f"deepstream-protocol-adapter-v3:{branch}:{resource}:"
                f"{terminal['worker_implementation_sha256']}:{source_sha}"
            )
            emitter_id = (
                f"deepstream-native-policy-emitter-v3:{branch}:{resource}:{source_sha}"
            )
            runtime_identity = {
                "runtime_backend": (
                    "deepstream_protocol_adapter_openvino_cpu_v3"
                    if resource == "cpu"
                    else "deepstream_protocol_adapter_tensorrt_cuda_v3"
                ),
                "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                "gpu_id": None if resource == "cpu" else 0,
                "worker_image_digest": terminal["worker_image_id"],
                "implementation_version": (
                    "sha256:" + terminal["worker_implementation_sha256"]
                ),
                "terminal_detector": terminal["terminal_detector"],
                "terminal_backend": terminal["terminal_backend"],
            }
            terminal_sources = [
                _descriptor(root, terminal["binding_path"], f"{branch}/{resource} binding"),
                _descriptor(root, terminal["probe_path"], f"{branch}/{resource} probe"),
            ]
            artifact = _artifact(
                role="policy",
                branch=branch,
                resource=resource,
                implementation_id=implementation_id,
                emitter_id=emitter_id,
                runtime_identity=runtime_identity,
                image=image,
                accepted_model_material=accepted_model_material,
                sources=[*policy_common, *terminal_sources],
                evidence_roles=POLICY_EVIDENCE_ROLES,
                blockers=blockers,
            )
            path = bindings_dir / f"policy.{branch}.{resource}.json"
            _write_immutable(path, artifact)
            relative = path.relative_to(root).as_posix()
            descriptor = _descriptor(root, relative, f"policy {branch}/{resource}")
            policy_bindings.append(
                {
                    "role": "policy",
                    "branch": branch,
                    "resource": resource,
                    "path": descriptor["path"],
                    "sha256": descriptor["sha256"],
                    "size": descriptor["size"],
                    "implementation_id": implementation_id,
                    "emitter_id": emitter_id,
                    "runtime_identity": runtime_identity,
                }
            )

    for resource in RESOURCES:
        blockers: list[str] = []
        implementation_id = (
            f"deepstream-full-resource-v2:{resource}:{image['image_id']}"
        )
        emitter_id = (
            f"deepstream-native-resource-emitter-v3:{resource}:{source_sha}"
        )
        runtime_identity = {
            "runtime_backend": runtime_backend,
            "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
            "decoder_device_api": "NVIDIA_NVDEC",
            "worker_image_digest": image["image_id"],
            "implementation_version": version,
            "hardware_binding_id": (
                f"nvidia-gpu:{gpu_uuid}:driver-{EXPECTED_GPU_DRIVER}"
            ),
        }
        artifact = _artifact(
            role="resource",
            branch="all_branches",
            resource=resource,
            implementation_id=implementation_id,
            emitter_id=emitter_id,
            runtime_identity=runtime_identity,
            image=image,
            accepted_model_material=accepted_model_material,
            sources=resource_common,
            evidence_roles=RESOURCE_EVIDENCE_ROLES,
            blockers=blockers,
        )
        path = bindings_dir / f"resource.{resource}.json"
        _write_immutable(path, artifact)
        relative = path.relative_to(root).as_posix()
        descriptor = _descriptor(root, relative, f"resource {resource}")
        resource_bindings.append(
            {
                "role": "resource",
                "branch": "all_branches",
                "resource": resource,
                "path": descriptor["path"],
                "sha256": descriptor["sha256"],
                "size": descriptor["size"],
                "implementation_id": implementation_id,
                "emitter_id": emitter_id,
                "runtime_identity": runtime_identity,
            }
        )

    all_bindings = [*policy_bindings, *resource_bindings]
    for binding in all_bindings:
        _require(binding["implementation_id"] not in implementation_ids, "implementation_id collision")
        _require(binding["emitter_id"] not in emitter_ids, "emitter_id collision")
        implementation_ids.add(binding["implementation_id"])
        emitter_ids.add(binding["emitter_id"])
        info = (root / binding["path"]).stat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(identity not in artifact_identities, "physical binding inode alias")
        artifact_identities.add(identity)

    fragment = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "system": SYSTEM,
        "policy_bindings": policy_bindings,
        "resource_bindings": resource_bindings,
        "pilots": [],
    }
    fragment_path = destination / FRAGMENT_FILENAME
    _write_immutable(fragment_path, fragment)
    validate_deepstream_qualification_fragment(
        project_root=root,
        fragment_path=fragment_path,
    )
    return fragment_path


def validate_deepstream_qualification_fragment(
    *, project_root: Path, fragment_path: Path
) -> dict[str, Any]:
    root = Path(project_root).resolve(strict=True)
    path = Path(fragment_path).resolve(strict=True)
    try:
        relative_fragment = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise DeepStreamQualificationFragmentV1Error(
            "DeepStream qualification fragment escapes project_root"
        ) from exc
    _physical_file(root, relative_fragment, "qualification fragment")
    fragment = _load_json(path, "DeepStream qualification fragment")
    _terminals, accepted_model_material = _terminal_identities(
        root, EXPECTED_GPU_UUID
    )
    expected_top = {
        "schema_version",
        "artifact_kind",
        "system",
        "policy_bindings",
        "resource_bindings",
        "pilots",
    }
    _require(set(fragment) == expected_top, "DeepStream qualification fragment fields drifted")
    _require(
        fragment["schema_version"] == 1
        and fragment["artifact_kind"] == ARTIFACT_KIND
        and fragment["system"] == SYSTEM
        and fragment["pilots"] == [],
        "DeepStream qualification fragment identity/readiness drifted",
    )
    policy = fragment["policy_bindings"]
    resources = fragment["resource_bindings"]
    _require(type(policy) is list and len(policy) == 8, "policy binding count drifted")
    _require(type(resources) is list and len(resources) == 2, "resource binding count drifted")
    _require(
        {(row.get("branch"), row.get("resource")) for row in policy}
        == {(branch, resource) for branch in BRANCHES for resource in RESOURCES},
        "policy binding coverage drifted",
    )
    _require(
        {(row.get("branch"), row.get("resource")) for row in resources}
        == {("all_branches", resource) for resource in RESOURCES},
        "resource binding coverage drifted",
    )
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()
    paths: set[str] = set()
    inodes: set[tuple[int, int]] = set()
    for row in [*policy, *resources]:
        _require(type(row) is dict and set(row) == BINDING_FIELDS, "binding fields drifted")
        role = str(row["role"])
        resource = str(row["resource"])
        _require(role in {"policy", "resource"} and resource in RESOURCES, "binding role/resource drifted")
        expected_blockers: list[str] = []
        runtime = row["runtime_identity"]
        expected_runtime_fields = POLICY_RUNTIME_FIELDS if role == "policy" else RESOURCE_RUNTIME_FIELDS
        _require(type(runtime) is dict and set(runtime) == expected_runtime_fields, "runtime identity fields drifted")
        _require(IMAGE_ID_RE.fullmatch(str(runtime["worker_image_digest"])) is not None, "worker image digest is invalid")
        if role == "policy":
            expected_policy_backend = (
                "deepstream_protocol_adapter_openvino_cpu_v3"
                if resource == "cpu"
                else "deepstream_protocol_adapter_tensorrt_cuda_v3"
            )
            _require(
                runtime["runtime_backend"] == expected_policy_backend
                and runtime["device_api"]
                == ("CPU" if resource == "cpu" else "NVIDIA_CUDA")
                and runtime["gpu_id"] == (None if resource == "cpu" else 0)
                and re.fullmatch(
                    r"sha256:[0-9a-f]{64}",
                    str(runtime["implementation_version"]),
                )
                is not None
                and type(runtime["terminal_detector"]) is str
                and bool(runtime["terminal_detector"])
                and type(runtime["terminal_backend"]) is str
                and bool(runtime["terminal_backend"]),
                "policy runtime identity drifted",
            )
        else:
            _require(
                runtime["runtime_backend"] == RESOURCE_RUNTIME_BACKEND
                and runtime["analytics_device_api"]
                == ("HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA")
                and runtime["decoder_device_api"] == "NVIDIA_NVDEC"
                and re.fullmatch(
                    r"deepstream-publication-runtime-v3:[0-9a-f]{64}",
                    str(runtime["implementation_version"]),
                )
                is not None
                and re.fullmatch(
                    r"nvidia-gpu:GPU-[0-9a-fA-F-]{16,}:driver-[0-9.]+",
                    str(runtime["hardware_binding_id"]),
                )
                is not None,
                "resource runtime identity drifted",
            )
        relative = str(row["path"])
        descriptor = _descriptor(root, relative, f"{role} binding")
        _require(
            descriptor["sha256"] == row["sha256"] and descriptor["size"] == row["size"],
            "physical binding descriptor drift",
        )
        info = (root / relative).stat()
        inode = (int(info.st_dev), int(info.st_ino))
        _require(relative not in paths and inode not in inodes, "binding path/inode alias")
        paths.add(relative)
        inodes.add(inode)
        implementation = str(row["implementation_id"])
        emitter = str(row["emitter_id"])
        _require(
            len(implementation) >= 8
            and len(emitter) >= 8
            and implementation not in implementation_ids
            and emitter not in emitter_ids,
            "binding implementation/emitter identity collision",
        )
        implementation_ids.add(implementation)
        emitter_ids.add(emitter)
        artifact = _load_json(root / relative, f"{role} physical binding")
        native_evidence = artifact.get("native_evidence_contract")
        expected_roles = (
            list(POLICY_EVIDENCE_ROLES)
            if role == "policy"
            else list(RESOURCE_EVIDENCE_ROLES)
        )
        _require(
            artifact.get("artifact_kind") == "vast_deepstream_qualification_physical_binding_v1"
            and artifact.get("system") == SYSTEM
            and artifact.get("role") == role
            and artifact.get("branch") == row["branch"]
            and artifact.get("resource") == resource
            and artifact.get("implementation_id") == implementation
            and artifact.get("emitter_id") == emitter
            and artifact.get("runtime_identity") == runtime
            and artifact.get("accepted_model_material")
            == accepted_model_material
            and artifact.get("blockers") == expected_blockers
            and artifact.get("publication_ready") is False
            and native_evidence
            == {"telemetry_source": "native", "roles": expected_roles},
            "physical binding envelope drifted",
        )
        binding_sha = artifact.get("binding_sha256")
        artifact_material = {
            key: value for key, value in artifact.items() if key != "binding_sha256"
        }
        _require(binding_sha == _canonical_sha(artifact_material), "physical binding SHA drift")
    return fragment


def _docker_inspect(docker: str, image_id: str) -> dict[str, Any]:
    _require(IMAGE_ID_RE.fullmatch(image_id) is not None, "image ID is invalid")
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", image_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeepStreamQualificationFragmentV1Error("Docker image inspect failed") from exc
    _require(completed.returncode == 0 and not completed.stderr, "Docker image inspect failed")
    try:
        values = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeepStreamQualificationFragmentV1Error("Docker image inspect is invalid") from exc
    _require(type(values) is list and len(values) == 1 and type(values[0]) is dict, "Docker image inspect shape drifted")
    return values[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize DeepStream qualification bindings fragment v1")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--gpu-uuid", required=True)
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args(argv)
    fragment = materialize_deepstream_qualification_fragment(
        project_root=args.project_root,
        output_dir=args.output_dir,
        image_inspect=_docker_inspect(args.docker, args.image_id),
        gpu_uuid=args.gpu_uuid,
    )
    print(json.dumps({"fragment": str(fragment)}, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DeepStreamQualificationFragmentV1Error",
    "materialize_deepstream_qualification_fragment",
    "validate_deepstream_qualification_fragment",
]
