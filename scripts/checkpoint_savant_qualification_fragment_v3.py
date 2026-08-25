#!/usr/bin/env python3
"""Materialize fail-closed phase-one Savant qualification bindings."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import checkpoint_gstreamer_custom_qualification_fragment_v3 as common


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_publication_qualification_system_fragment_v1"
SYSTEM = "savant"
FRAGMENT_FILENAME = "qualification_fragment.json"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
ROW_FIELDS = {
    "role", "branch", "resource", "path", "sha256", "size",
    "implementation_id", "emitter_id", "runtime_identity",
}
FRAGMENT_FIELDS = {
    "schema_version", "artifact_kind", "system", "policy_bindings",
    "resource_bindings", "pilots",
}
POLICY_RUNTIME_FIELDS = {
    "runtime_backend", "device_api", "gpu_id", "worker_image_digest",
    "implementation_version", "terminal_detector", "terminal_backend",
}
RESOURCE_RUNTIME_FIELDS = {
    "runtime_backend", "analytics_device_api", "decoder_device_api",
    "worker_image_digest", "implementation_version", "hardware_binding_id",
}

ACCEPTED_PARITY = (
    "configs/checkpoint_analytics_model_parity.accepted.yaml", 25229,
    "a570b8cc4bcc66119930f01239ed0fb2de7accd449b769d5a4b0511d70fb72b6",
)
ACCEPTED_PARITY_CONTENT_SHA256 = (
    "05059ee44a21a82728f2608dc13804f55cc7df9eeedb245ad2d63a7c1ca46ee8"
)
PREPROCESSING_CONTRACT_SHA256 = (
    "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090"
)
PROTOCOL_IDENTITY_SHA256 = (
    "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff"
)
EXECUTION_CONFIG_IDENTITY_SHA256 = (
    "3daed67a3e4c6549bf463b929e5de840e5aab7daacac75fff328f624b867b512"
)
BASE_PARITY_IDENTITY_SHA256 = (
    "4065e9a766bbdf82771534ec1f5f13f32f4d6ab6de9ac27143663cc27634fd80"
)
ANALYTICS_INDEX = (
    "artifacts/analytics_execution_bindings/publication_v3/index.json", 1877,
    "8ff3d495b80024eca2067a43239fc984961629465288d307d7f8f4de32c31e87",
)
ANALYTICS_INDEX_IDENTITY = (
    "6fb0a64f19d61ef7021a50ae35f04f55b344f0fe67911d29d43e03a00ebb635b"
)
ANALYTICS_BINDINGS_IDENTITY = (
    "7504b2a73c886cbda01b3d1d02c1dab360146285c3dba2cdec6496b7510956ab"
)
RUNTIME_PROBES = {
    "cpu": (
        "artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json",
        659, "e6008e33e137d315f1672adb2e241004e2ea08f1220467dcbf089a566060ddfb",
    ),
    "gpu": (
        "artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json",
        654, "24986e7aadd93ab9bb72704c5a83d568bc0e4fd70154803e303b3bda5aa4a752",
    ),
}
CPU_WORKER_IMAGE_ID = (
    "sha256:e2b01f8f40da08fc59d671e19a7f4eca6dd7d46678de0138ab7af51b09cb9b03"
)
GPU_WORKER_IMAGE_ID = (
    "sha256:2ff600e743e6fc089ace1ea40894d73581fcda8007fa758fd0f32eb9b1c72f09"
)
WORKER_IMPLEMENTATIONS = {
    "cpu": "f15ab5fd7d846376ccba55e55b663f4d16e114ef4cf5519794795cde7a416f8b",
    "gpu": "eb6fce9ec42f26e0d38263053aedbb8d9c247c1872be39d67d7f3c0da4c48ab7",
}
SAVANT_BASE_IMAGE_ID = (
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
NATIVE_BUILDER_IMAGE_ID = (
    "sha256:ef70f6fae0558d1d90ae32fc931256bc71169749c15ae00b70a8ca00c0b70513"
)
NATIVE_BUILDER_SOURCE_SHA256 = (
    "e38aa56050381aef7ce9ff6fb934ae3da0d44175f10fb67f4cecea34433ded01"
)
GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
GPU_NAME = "NVIDIA GeForce RTX 3060"
GPU_DRIVER = "610.47"
IMAGE_FIELDS = {
    "schema_version", "artifact_kind", "image_id", "repository_digests",
    "inspect_projection_sha256", "entrypoint", "architecture", "os",
    "savant_version", "deepstream_version", "base_image_id",
    "native_builder_image_id", "native_builder_source_sha256",
    "runtime_source_sha256", "runtime_bundle_sha256",
    "publication_ready_label",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")

QualificationFragmentError = common.QualificationFragmentError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationFragmentError(message)


def _aggregate_sha256(root: Path, paths: Sequence[Path]) -> str:
    rows = bytearray()
    for path in sorted(paths, key=lambda value: value.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        _require(path.is_file() and not common._is_link(path), f"source unsafe: {relative}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    _require(bool(rows), "runtime source set is empty")
    return hashlib.sha256(rows).hexdigest()


def _validated_runtime_source_paths(root: Path) -> tuple[Path, ...]:
    validator_path = (
        root / "deploy/savant/publication/validate_runtime_source_closure_v3.py"
    )
    manifest_path = (
        root / "deploy/savant/publication/runtime-source-allowlist.txt"
    )
    specification = importlib.util.spec_from_file_location(
        "validate_savant_runtime_source_closure_v3", validator_path,
    )
    _require(
        specification is not None and specification.loader is not None,
        "runtime source closure validator cannot be loaded",
    )
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
        result = module.validate_runtime_source_closure(
            project_root=root, manifest_path=manifest_path,
        )
    except (OSError, ValueError, AttributeError) as error:
        raise QualificationFragmentError(
            "runtime source closure validation failed"
        ) from error
    paths = tuple(root / str(relative) for relative in result["all_sources"])
    _require(bool(paths), "runtime source closure is empty")
    return paths


def runtime_source_sha256(project_root: Path) -> str:
    root = common._project_root(project_root)
    return _aggregate_sha256(root, _validated_runtime_source_paths(root))


def runtime_bundle_sha256(project_root: Path) -> str:
    root = common._project_root(project_root)
    paths = list((root / "deploy/deepstream/checkpoint/wheels").glob("*"))
    paths.append(
        root / "deploy/deepstream/checkpoint/requirements.lock",
    )
    return _aggregate_sha256(root, tuple(paths))


def _accepted_parity(root: Path) -> dict[str, Any]:
    descriptor = common._exact_descriptor(root, ACCEPTED_PARITY, "accepted parity")
    manifest = common._yaml(root / ACCEPTED_PARITY[0], "accepted parity")
    _require(
        common._canonical_sha(manifest) == ACCEPTED_PARITY_CONTENT_SHA256,
        "accepted parity content identity drifted",
    )
    _require(
        common._canonical_sha(manifest["preprocessing_contract"])
        == PREPROCESSING_CONTRACT_SHA256,
        "preprocessing contract identity drifted",
    )
    workers = manifest.get("worker_runtime_registry") or {}
    cpu = workers.get("openvino_cpu") or {}
    gpu = workers.get("tensorrt_cuda") or {}
    _require(
        cpu.get("image_id") == CPU_WORKER_IMAGE_ID
        and cpu.get("worker_implementation_sha256") == WORKER_IMPLEMENTATIONS["cpu"]
        and gpu.get("image_id") == GPU_WORKER_IMAGE_ID
        and gpu.get("worker_implementation_sha256") == WORKER_IMPLEMENTATIONS["gpu"],
        "accepted analytics worker identities drifted",
    )
    execution = workers.get("execution_config") or {}
    _require(
        execution.get("content_identity_sha256")
        == EXECUTION_CONFIG_IDENTITY_SHA256,
        "accepted execution config identity drifted",
    )
    toolchain = (manifest.get("toolchain_registry") or {}).get("tensorrt_cuda") or {}
    _require(
        toolchain.get("gpu_uuid") == GPU_UUID
        and toolchain.get("gpu_name") == GPU_NAME
        and str(toolchain.get("driver_version")) == GPU_DRIVER,
        "accepted GPU identity drifted",
    )
    return {**descriptor, "content_identity_sha256": ACCEPTED_PARITY_CONTENT_SHA256}


def _analytics_bindings(
    root: Path,
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    descriptor = common._exact_descriptor(root, ANALYTICS_INDEX, "analytics index")
    index = common._json(root / ANALYTICS_INDEX[0], "analytics index")
    _require(
        index.get("artifact_kind") == "vast_analytics_execution_worker_binding_set"
        and (index.get("identity") or {}).get("sha256") == ANALYTICS_INDEX_IDENTITY
        and index.get("bindings_identity_sha256") == ANALYTICS_BINDINGS_IDENTITY
        and index.get("execution_config_identity_sha256")
        == EXECUTION_CONFIG_IDENTITY_SHA256
        and index.get("model_parity_manifest_identity_sha256")
        == BASE_PARITY_IDENTITY_SHA256
        and index.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256,
        "analytics binding index identity drifted",
    )
    files = index.get("files")
    _require(type(files) is list and len(files) == 8, "analytics binding set drifted")
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    base = PurePosixPath(ANALYTICS_INDEX[0]).parent
    for item in files:
        match = re.fullmatch(
            r"(plate_number|vehicle_type|damage|foreign_object)\."
            r"(openvino_cpu|tensorrt_cuda)\.json",
            str((item or {}).get("path", "")),
        )
        _require(match is not None, "analytics binding filename drifted")
        resource = "cpu" if match.group(2) == "openvino_cpu" else "gpu"
        key = (match.group(1), resource)
        relative = (base / str(item["path"])).as_posix()
        binding_descriptor = common._exact_descriptor(
            root, (relative, int(item["bytes"]), str(item["sha256"])),
            f"analytics binding {key}",
        )
        binding = common._json(root / relative, f"analytics binding {key}")
        expected_kind = (
            "vast_openvino_execution_worker_binding"
            if resource == "cpu" else "vast_tensorrt_execution_worker_binding"
        )
        expected_image = CPU_WORKER_IMAGE_ID if resource == "cpu" else GPU_WORKER_IMAGE_ID
        _require(
            key not in observed and binding.get("artifact_kind") == expected_kind
            and binding.get("branch") == key[0]
            and binding.get("worker_image_id") == expected_image
            and binding.get("preprocessing_contract_sha256")
            == PREPROCESSING_CONTRACT_SHA256,
            f"analytics binding identity drifted: {key}",
        )
        observed[key] = {"descriptor": binding_descriptor, "binding": binding}
    _require(
        set(observed) == {(branch, resource) for branch in BRANCHES for resource in RESOURCES},
        "analytics binding coverage drifted",
    )
    return {
        **descriptor,
        "identity_sha256": ANALYTICS_INDEX_IDENTITY,
        "bindings_identity_sha256": ANALYTICS_BINDINGS_IDENTITY,
    }, observed


def _runtime_probes(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        descriptor = common._exact_descriptor(
            root, RUNTIME_PROBES[resource], f"{resource} runtime probe",
        )
        probe = common._json(root / descriptor["path"], f"{resource} runtime probe")
        engine = "openvino_cpu" if resource == "cpu" else "tensorrt_cuda"
        api = "CPU" if resource == "cpu" else "NVIDIA_CUDA"
        _require(
            probe.get("artifact_kind")
            == "vast_analytics_execution_worker_runtime_probe"
            and probe.get("engine") == engine
            and probe.get("device_api") == api
            and probe.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256
            and probe.get("worker_implementation_sha256")
            == WORKER_IMPLEMENTATIONS[resource],
            f"{resource} runtime probe identity drifted",
        )
        if resource == "gpu":
            _require(probe.get("device_id") == GPU_UUID, "GPU runtime probe UUID drifted")
        result[resource] = descriptor
    return result


def _runtime_sources(root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "sdk_worker": "scripts/checkpoint_savant_sdk_runtime_v3.py",
        "native_module": "scripts/checkpoint_savant_native_module.py",
        "native_ingress": "scripts/checkpoint_savant_ingress.py",
        "protocol_adapter": "scripts/checkpoint_savant_protocol_adapter_v3.py",
        "protocol_bridge": "scripts/checkpoint_savant_protocol_bridge.py",
        "physical_resource_recorder": "scripts/checkpoint_savant_resource_runtime_v3.py",
        "arm_specs": "scripts/checkpoint_savant_publication_specs_v3.py",
        "arm_coordinator": "scripts/checkpoint_savant_container_runtime_v3.py",
        "host_boundary": "scripts/checkpoint_savant_publication_runtime_v3.py",
        "native_policy_runtime": "scripts/checkpoint_native_policy_runtime.py",
        "hardware_collector": "scripts/collect_metrics.py",
        "full_resource_validator": "scripts/full_resource_contract.py",
        "interval_validator": "scripts/resource_interval_contract.py",
        "image_builder": "scripts/build_savant_publication_runtime_v3.sh",
        "dockerfile": "deploy/savant/publication/Dockerfile",
        "entrypoint": "deploy/savant/publication/vast_savant_checkpoint_runtime",
    }
    return {
        role: common._descriptor(root, path, role)
        for role, path in paths.items()
    }


def _image_materialization(
    root: Path, runtime_image_manifest: Path,
) -> dict[str, Any]:
    path = Path(runtime_image_manifest).resolve(strict=True)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise QualificationFragmentError("runtime image manifest escaped project_root") from error
    descriptor = common._descriptor(root, relative, "runtime image manifest")
    value = common._json(path, "runtime image manifest")
    _require(set(value) == IMAGE_FIELDS, "runtime image manifest fields drifted")
    _require(
        value.get("schema_version") == 3
        and value.get("artifact_kind")
        == "vast_savant_runtime_image_materialization_v3"
        and _IMAGE_RE.fullmatch(str(value.get("image_id", ""))) is not None
        and _SHA_RE.fullmatch(str(value.get("inspect_projection_sha256", "")))
        is not None
        and value.get("entrypoint")
        == ["/usr/local/bin/vast_savant_checkpoint_runtime"]
        and value.get("architecture") == "amd64"
        and value.get("os") == "linux"
        and value.get("savant_version") == "0.5.17"
        and value.get("deepstream_version") == "7.0"
        and value.get("base_image_id") == SAVANT_BASE_IMAGE_ID
        and value.get("native_builder_image_id") == NATIVE_BUILDER_IMAGE_ID
        and value.get("native_builder_source_sha256")
        == NATIVE_BUILDER_SOURCE_SHA256
        and value.get("publication_ready_label") == "false",
        "runtime image identity drifted",
    )
    repositories = value.get("repository_digests")
    _require(
        type(repositories) is list
        and len(repositories) == len(set(repositories))
        and all(_REPO_RE.fullmatch(str(item)) is not None for item in repositories),
        "runtime repository digest set drifted",
    )
    _require(
        value.get("runtime_source_sha256") == runtime_source_sha256(root)
        and value.get("runtime_bundle_sha256") == runtime_bundle_sha256(root),
        "runtime image source/bundle label drifted",
    )
    return {"descriptor": descriptor, "identity": value}


def _policy_identity(
    resource: str, binding: Mapping[str, Any],
) -> dict[str, Any]:
    worker_id = str(binding["worker_id"])
    detector = f"{worker_id};model_sha256={binding['model_artifact_sha256']}"
    return {
        "runtime_backend": (
            "savant_0.5.17_direct_openvino_cpu_endpoint_v3"
            if resource == "cpu"
            else "savant_0.5.17_direct_tensorrt_cuda_endpoint_v3"
        ),
        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "gpu_id": None if resource == "cpu" else 0,
        "worker_image_digest": (
            CPU_WORKER_IMAGE_ID if resource == "cpu" else GPU_WORKER_IMAGE_ID
        ),
        "implementation_version": "sha256:" + WORKER_IMPLEMENTATIONS[resource],
        "terminal_detector": detector,
        "terminal_backend": (
            "openvino-execution-worker;device=CPU"
            if resource == "cpu"
            else "tensorrt-execution-worker;device=NVIDIA_CUDA:0"
        ),
    }


def _resource_identity(
    resource: str, image: Mapping[str, Any],
) -> dict[str, str]:
    identity = image["identity"]
    return {
        "runtime_backend": "savant_0.5.17_deepstream_7.0_single_arm_container_v3",
        "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "decoder_device_api": "NVIDIA_NVDEC",
        "worker_image_digest": str(identity["image_id"]),
        "implementation_version": "sha256:" + str(identity["runtime_source_sha256"]),
        "hardware_binding_id": f"nvidia-gpu:{GPU_UUID}:driver-{GPU_DRIVER}",
    }


def _material_values(
    root: Path, runtime_image_manifest: Path,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    parity = _accepted_parity(root)
    binding_index, bindings = _analytics_bindings(root)
    probes = _runtime_probes(root)
    policy_contract = common._policy_contract(root)
    sources = _runtime_sources(root)
    image = _image_materialization(root, runtime_image_manifest)
    image_identity = image["identity"]
    materials: list[tuple[str, str, str, dict[str, Any]]] = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            worker = bindings[(branch, resource)]
            binding = worker["binding"]
            implementation_id = (
                f"savant-direct-openvino-cpu-v3:{branch}:"
                f"{WORKER_IMPLEMENTATIONS['cpu']}"
                if resource == "cpu"
                else f"savant-direct-tensorrt-cuda-v3:{branch}:"
                f"{WORKER_IMPLEMENTATIONS['gpu']}"
            )
            emitter_id = (
                f"vast-savant-protocol-terminal-v3:{branch}:{resource}:"
                f"{PROTOCOL_IDENTITY_SHA256}"
            )
            artifact = {
                "schema_version": 1,
                "artifact_kind": "vast_savant_policy_binding_material_v1",
                "system": SYSTEM,
                "role": "policy",
                "branch": branch,
                "resource": resource,
                "implementation_id": implementation_id,
                "emitter_id": emitter_id,
                "runtime_identity": _policy_identity(resource, binding),
                "policy_contract": policy_contract,
                "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
                "execution_config_identity_sha256": EXECUTION_CONFIG_IDENTITY_SHA256,
                "accepted_model_parity_manifest": parity,
                "preprocessing_contract_sha256": PREPROCESSING_CONTRACT_SHA256,
                "analytics_execution_binding_index": binding_index,
                "analytics_execution_worker_binding": worker["descriptor"],
                "analytics_execution_worker_binding_identity": {
                    "artifact_kind": binding["artifact_kind"],
                    "model_artifact_sha256": binding["model_artifact_sha256"],
                    "worker_image_id": binding["worker_image_id"],
                    "worker_id": binding["worker_id"],
                },
                "analytics_runtime_probe": probes[resource],
                "savant_runtime_image": image,
                "runtime_sources": sources,
                "nvidia_hardware_binding": {
                    "uuid": GPU_UUID,
                    "name": GPU_NAME,
                    "driver_version": GPU_DRIVER,
                },
            }
            materials.append(("policy", branch, resource, artifact))
    for resource in RESOURCES:
        implementation_id = (
            f"savant-full-resource-v2:{resource}:{image_identity['image_id']}"
        )
        emitter_id = (
            f"vast-savant-native-resource-recorder-v3:{resource}:"
            f"{sources['physical_resource_recorder']['sha256']}"
        )
        artifact = {
            "schema_version": 1,
            "artifact_kind": "vast_savant_resource_binding_material_v1",
            "system": SYSTEM,
            "role": "resource",
            "branch": "all_branches",
            "resource": resource,
            "implementation_id": implementation_id,
            "emitter_id": emitter_id,
            "runtime_identity": _resource_identity(resource, image),
            "accepted_model_parity_manifest": parity,
            "preprocessing_contract_sha256": PREPROCESSING_CONTRACT_SHA256,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "savant_runtime_image": image,
            "analytics_runtime_probe": probes[resource],
            "resource_emitters": {
                "resource_intervals": {
                    "producer": sources["physical_resource_recorder"],
                    "native_callbacks": [
                        "nvdec_submit_complete", "fanout",
                        "cuda_h2d", "cuda_d2h",
                    ],
                },
                "hardware_resource_samples": {
                    "producer": sources["hardware_collector"],
                    "device_api": "NVIDIA_NVML",
                    "device_id": GPU_UUID,
                },
                "fanout_work_counters": {
                    "producer": sources["physical_resource_recorder"],
                    "counter_provenance": "native_thread_cpu_time_v1",
                },
            },
            "resource_contracts": {
                "contract_version": 2,
                "publication_scope": "primary_architecture_full_resource_raw_evidence_v2",
                "full_resource_validator": sources["full_resource_validator"],
                "interval_validator": sources["interval_validator"],
            },
            "runtime_sources": sources,
            "nvidia_hardware_binding": {
                "uuid": GPU_UUID,
                "name": GPU_NAME,
                "driver_version": GPU_DRIVER,
                "decoder_device_api": "NVIDIA_NVDEC",
            },
        }
        materials.append(("resource", "all_branches", resource, artifact))
    return materials


def _artifact_path(
    root: Path, output: Path, role: str, branch: str, resource: str,
) -> str:
    name = (
        f"{branch}.{resource}.binding.json"
        if role == "policy" else f"{resource}.binding.json"
    )
    return (output / "bindings" / role / name).relative_to(root).as_posix()


def _expected(
    root: Path, output: Path, runtime_image_manifest: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    policy: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    for role, branch, resource, artifact in _material_values(
        root, runtime_image_manifest,
    ):
        relative = _artifact_path(root, output, role, branch, resource)
        payload = common._canonical_bytes(artifact)
        payloads[relative] = payload
        row = {
            "role": role,
            "branch": branch,
            "resource": resource,
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "implementation_id": artifact["implementation_id"],
            "emitter_id": artifact["emitter_id"],
            "runtime_identity": artifact["runtime_identity"],
        }
        (policy if role == "policy" else resources).append(row)
    return ({
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "system": SYSTEM,
        "policy_bindings": policy,
        "resource_bindings": resources,
        "pilots": [],
    }, payloads)


def _failure(message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind":
            "vast_publication_qualification_system_fragment_assessment_v1",
        "passed": False,
        "status": "blocked",
        "blockers": [message],
        "coverage": {
            "policy_binding_count": 0,
            "resource_binding_count": 0,
            "pilot_cell_count": 0,
        },
    }


def assess_qualification_fragment(
    *,
    project_root: Path,
    fragment_path: Path,
    runtime_image_manifest: Path,
) -> dict[str, Any]:
    """Re-hash every material and reject self-declared phase-one state."""
    try:
        root = common._project_root(project_root)
        candidate = Path(fragment_path).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise QualificationFragmentError("fragment escaped project_root") from error
        info = candidate.lstat()
        _require(
            candidate.name == FRAGMENT_FILENAME
            and not common._is_link(candidate)
            and stat.S_ISREG(info.st_mode)
            and int(info.st_nlink) == 1,
            "fragment must be a physical regular file",
        )
        value = common._json(candidate, "qualification fragment")
        _require(set(value) == FRAGMENT_FIELDS, "qualification fragment fields drifted")
        _require(
            value.get("schema_version") == SCHEMA_VERSION
            and value.get("artifact_kind") == ARTIFACT_KIND
            and value.get("system") == SYSTEM,
            "qualification fragment identity drifted",
        )
        _require(value.get("pilots") == [], "phase-one pilots must remain empty")
        expected, payloads = _expected(
            root, candidate.parent, Path(runtime_image_manifest),
        )
        _require(value == expected, "qualification fragment binding values drifted")
        paths: set[str] = set()
        inodes: set[tuple[int, int]] = set()
        implementation_ids: set[str] = set()
        emitter_ids: set[str] = set()
        for row in (*value["policy_bindings"], *value["resource_bindings"]):
            _require(
                type(row) is dict and set(row) == ROW_FIELDS,
                "binding row fields drifted",
            )
            fields = (
                POLICY_RUNTIME_FIELDS
                if row["role"] == "policy" else RESOURCE_RUNTIME_FIELDS
            )
            _require(
                type(row["runtime_identity"]) is dict
                and set(row["runtime_identity"]) == fields,
                "binding runtime identity fields drifted",
            )
            implementation_id = str(row["implementation_id"])
            emitter_id = str(row["emitter_id"])
            _require(
                common._ID_RE.fullmatch(implementation_id) is not None
                and common._ID_RE.fullmatch(emitter_id) is not None
                and implementation_id not in implementation_ids
                and emitter_id not in emitter_ids,
                "binding implementation/emitter identity duplicated or unstable",
            )
            implementation_ids.add(implementation_id)
            emitter_ids.add(emitter_id)
            artifact = common._relative_file(root, row["path"], "physical binding")
            artifact_info = artifact.lstat()
            inode = (int(artifact_info.st_dev), int(artifact_info.st_ino))
            _require(
                row["path"] not in paths and inode not in inodes,
                "physical binding path/inode alias prohibited",
            )
            paths.add(row["path"])
            inodes.add(inode)
            payload = artifact.read_bytes()
            _require(
                payload == payloads[row["path"]]
                and len(payload) == row["size"]
                and hashlib.sha256(payload).hexdigest() == row["sha256"],
                "physical binding bytes/size/SHA-256 drifted",
            )
        _require(
            len(paths) == len(inodes) == len(implementation_ids)
            == len(emitter_ids) == 10,
            "binding coverage drifted",
        )
        return {
            "schema_version": 1,
            "artifact_kind":
                "vast_publication_qualification_system_fragment_assessment_v1",
            "passed": True,
            "status": "bindings_materialized_pilots_pending",
            "blockers": [],
            "fragment_sha256": common._stable_hash(
                candidate, "qualification fragment",
            )[1],
            "coverage": {
                "policy_binding_count": 8,
                "resource_binding_count": 2,
                "pilot_cell_count": 0,
            },
        }
    except QualificationFragmentError as error:
        return _failure(str(error))
    except Exception as error:
        return _failure(f"qualification fragment validation failed closed: {error}")


def materialize_qualification_fragment(
    *,
    project_root: Path,
    output_dir: Path,
    runtime_image_manifest: Path,
) -> dict[str, Any]:
    """Write ten immutable physical bindings and commit the fragment last."""
    root = common._project_root(project_root)
    output = common._output_dir(root, output_dir)
    fragment, payloads = _expected(root, output, runtime_image_manifest)
    for relative, payload in payloads.items():
        common._write_immutable(root / relative, payload)
    fragment_path = output / FRAGMENT_FILENAME
    common._write_immutable(fragment_path, common._canonical_bytes(fragment))
    assessment = assess_qualification_fragment(
        project_root=root,
        fragment_path=fragment_path,
        runtime_image_manifest=runtime_image_manifest,
    )
    if not assessment["passed"]:
        raise QualificationFragmentError(
            "materialized fragment blocked: " + ", ".join(assessment["blockers"])
        )
    return {
        "fragment_path": fragment_path,
        "fragment_sha256": assessment["fragment_sha256"],
        "coverage": assessment["coverage"],
        "status": assessment["status"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize Savant qualification system fragment",
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-image-manifest", type=Path, required=True)
    parser.add_argument("--assess-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.assess_only:
        result = assess_qualification_fragment(
            project_root=args.project_root,
            fragment_path=args.output_dir / FRAGMENT_FILENAME,
            runtime_image_manifest=args.runtime_image_manifest,
        )
    else:
        result = materialize_qualification_fragment(
            project_root=args.project_root,
            output_dir=args.output_dir,
            runtime_image_manifest=args.runtime_image_manifest,
        )
        result = {**result, "fragment_path": str(result["fragment_path"])}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTED_PARITY", "ARTIFACT_KIND", "BRANCHES", "CPU_WORKER_IMAGE_ID",
    "FRAGMENT_FILENAME", "GPU_WORKER_IMAGE_ID", "NATIVE_BUILDER_IMAGE_ID",
    "NATIVE_BUILDER_SOURCE_SHA256", "POLICY_RUNTIME_FIELDS",
    "PROTOCOL_IDENTITY_SHA256", "QualificationFragmentError",
    "RESOURCES", "RESOURCE_RUNTIME_FIELDS", "ROW_FIELDS",
    "SAVANT_BASE_IMAGE_ID", "assess_qualification_fragment",
    "materialize_qualification_fragment", "runtime_bundle_sha256",
    "runtime_source_sha256",
]
