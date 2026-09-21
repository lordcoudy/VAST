#!/usr/bin/env python3
"""Materialize fail-closed phase-one GStreamer qualification bindings."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

import yaml


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_publication_qualification_system_fragment_v1"
SYSTEM = "gstreamer_custom"
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
    "configs/checkpoint_analytics_model_parity.refreshed.v4.a59.accepted.yaml", 29684,
    "766cc161ec0ab46d0dfc4e8d232a952fd0ffd118c5ce19acc694730be0f38643",
)
ACCEPTED_PARITY_CONTENT_SHA256 = (
    "6d5b87b63baaba29dc76b9b32d822e61b44b175326fa23182ea2a1207aa743d4"
)
PREPROCESSING_CONTRACT_SHA256 = (
    "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090"
)
ANALYTICS_INDEX = (
    "artifacts/model_parity_v4_refresh_20260902_attempt59/bindings/index.json", 1877,
    "e9544b01aac52aee08fd618fff00c489fb50ca265f2db3ef97522dcefeef66bb",
)
ANALYTICS_INDEX_IDENTITY = (
    "a17abc4fe6d4f8e9f07a4090adb54d6764656f6a36c9079aeac7e940eff46fe3"
)
ANALYTICS_BINDINGS_IDENTITY = (
    "bb4992081aa1f4fb94bb4c2e7a9c7ecf54e7ea1ea48e308bad09936cf79d71fc"
)
EXECUTION_CONFIG_IDENTITY = (
    "9e32e5462fe3c951153eff21eb0bfb8579a144160b483bc8c7672d297f3f710e"
)
MODEL_PARITY_MANIFEST_IDENTITY = (
    "159c09dd483f3435a78167d9be93a654badfd664833623bb17fad667da0538df"
)
PROTOCOL_IDENTITY = (
    "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff"
)
RUNTIME_PROBES = {
    "cpu": (
        "artifacts/model_parity_v4_refresh_20260902_attempt59/runtime_probes/cpu_runtime_probe.json",
        659, "0b496134ac3fec04449072218ddb6e2767d21b782127ab0d57c81c3b0daac874",
    ),
    "gpu": (
        "artifacts/model_parity_v4_refresh_20260902_attempt59/runtime_probes/gpu_runtime_probe.json",
        654, "9c8a85a12f5da797dd9e85ca4a1b6a790772d1d873b6e7203147f6631de241e4",
    ),
}
CPU_WORKER_IMAGE_ID = (
    "sha256:f98d48637805419d0d97a9c2912104e148b4ccecf1a81ea49357e63ad8b20575"
)
GPU_WORKER_IMAGE_ID = (
    "sha256:78ac4695c4cdc4e687024ce7b5f90d0624cca7f7d05dd066b08d9d27bf5c1f5f"
)
WORKER_IMPLEMENTATIONS = {
    "cpu": "b5782c91b6bdab9958a4f63485acae8975b4930843453a61e2fbe61b2c4da63b",
    "gpu": "d06205b56b0cfa504e2cd9ca627d1eecccd65ec89b7f6a43d45c2decf3776a60",
}
GSTREAMER_IMAGE_REFERENCE = (
    "vast/gstreamer-custom-publication-runtime-v3:materialized"
)
GSTREAMER_IMAGE_ID = (
    "sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4"
)
GSTREAMER_REPOSITORY_DIGEST = (
    "vast/gstreamer-custom-publication-runtime-v3@"
    "sha256:4e1cbec0c51eb2d47964242888b3ee87f1747cfa06d17cf04318a1a061d7eab4"
)
GSTREAMER_IMAGE_PROJECTION_SHA256 = (
    "86eb1cfd4b7cae749b95a2e0f310867f664f44b7cfb655ce0d368f9650541269"
)
GSTREAMER_BASE_IMAGE_ID = (
    "sha256:a022b7f35e91ab24199de2ff72475c81f340a1f1ffb24efbd558e8b44c48b618"
)
GSTREAMER_RUNTIME_SOURCE_SHA256 = (
    "2a7edf7b95158440d1dd2f730330ee2f77ea1f046c8825e22656bcb9c6335dd7"
)
GSTREAMER_NATIVE_SOURCE_SHA256 = (
    "ba9159f239751a4f226e836606e68dd40d5394782e9e678ef455d832a17dbb90"
)
GSTREAMER_DEPENDENCY_SET_SHA256 = (
    "0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e"
)
GSTREAMER_SOURCE_ALLOWLIST_SHA256 = (
    "dea819344804486529aeb32c0076690b42acfd8f5f861c2651d02b01c54608dc"
)
NATIVE_PROBE_SHA256 = (
    "cdbed23e0513391453659be23b240ded91a1d0502ea1f545d129f4dd9e77f36d"
)
ANALYTICS_TERMINAL_SHA256 = (
    "04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45"
)
GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
GPU_NAME = "NVIDIA GeForce RTX 3060"
GPU_DRIVER = "610.47"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{7,4095}$")


class QualificationFragmentError(RuntimeError):
    """An input, physical binding, or immutable output is unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationFragmentError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return (json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationFragmentError("non-canonical qualification JSON") from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _is_link(path: Path) -> bool:
    info = path.lstat()
    attrs = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


def _project_root(value: Path) -> Path:
    root = Path(value).resolve(strict=True)
    _require(root.is_dir() and not _is_link(root), "project_root must be physical")
    return root


def _relative_file(root: Path, raw: str, label: str) -> Path:
    _require(type(raw) is str and raw and "\\" not in raw, f"{label} path invalid")
    pure = PurePosixPath(raw)
    _require(
        not pure.is_absolute() and pure.as_posix() == raw
        and all(part not in {"", ".", ".."} for part in pure.parts),
        f"{label} path is not normalized",
    )
    cursor = root
    for part in pure.parts:
        cursor /= part
        _require(not _is_link(cursor), f"{label} path contains a link")
    path = root.joinpath(*pure.parts)
    _require(path.resolve(strict=True) == path, f"{label} path is aliased")
    info = path.lstat()
    _require(
        stat.S_ISREG(info.st_mode) and int(info.st_nlink) == 1,
        f"{label} must be a single-link regular file",
    )
    return path


def _stable_hash(path: Path, label: str) -> tuple[int, str]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    _require(
        tuple(getattr(before, item) for item in fields)
        == tuple(getattr(after, item) for item in fields),
        f"{label} changed while hashing",
    )
    return int(before.st_size), digest.hexdigest()


def _descriptor(root: Path, raw: str, label: str) -> dict[str, Any]:
    size, digest = _stable_hash(_relative_file(root, raw, label), label)
    return {"path": raw, "size_bytes": size, "sha256": digest}


def _exact_descriptor(root: Path, exact: tuple[str, int, str], label: str) -> dict[str, Any]:
    raw, size, digest = exact
    value = _descriptor(root, raw, label)
    _require(
        value == {"path": raw, "size_bytes": size, "sha256": digest},
        f"{label} exact size/SHA-256 drifted",
    )
    return value


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationFragmentError(f"invalid {label}: {error}") from error
    _require(type(value) is dict, f"{label} must be an object")
    return value


def _yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise QualificationFragmentError(f"invalid {label}: {error}") from error
    _require(type(value) is dict, f"{label} must be a mapping")
    return value


def _accepted_parity(root: Path) -> dict[str, Any]:
    descriptor = _exact_descriptor(root, ACCEPTED_PARITY, "accepted model parity")
    manifest = _yaml(root / ACCEPTED_PARITY[0], "accepted model parity")
    _require(
        _canonical_sha(manifest) == ACCEPTED_PARITY_CONTENT_SHA256,
        "accepted model parity content identity drifted",
    )
    _require(
        _canonical_sha(manifest.get("preprocessing_contract"))
        == PREPROCESSING_CONTRACT_SHA256,
        "accepted preprocessing contract identity drifted",
    )
    workers = manifest.get("worker_runtime_registry") or {}
    cpu, gpu = workers.get("openvino_cpu"), workers.get("tensorrt_cuda")
    _require(
        type(cpu) is dict and cpu.get("image_id") == CPU_WORKER_IMAGE_ID
        and cpu.get("worker_implementation_sha256") == WORKER_IMPLEMENTATIONS["cpu"],
        "accepted CPU worker identity drifted",
    )
    _require(
        type(gpu) is dict and gpu.get("image_id") == GPU_WORKER_IMAGE_ID
        and gpu.get("worker_implementation_sha256") == WORKER_IMPLEMENTATIONS["gpu"],
        "accepted GPU worker identity drifted",
    )
    _require(
        type(workers.get("execution_config")) is dict
        and workers["execution_config"].get("content_identity_sha256")
        == EXECUTION_CONFIG_IDENTITY,
        "accepted execution configuration identity drifted",
    )
    toolchain = (manifest.get("toolchain_registry") or {}).get("tensorrt_cuda")
    _require(
        type(toolchain) is dict and toolchain.get("gpu_uuid") == GPU_UUID
        and toolchain.get("gpu_name") == GPU_NAME
        and str(toolchain.get("driver_version")) == GPU_DRIVER,
        "accepted NVIDIA hardware identity drifted",
    )
    return {**descriptor, "content_identity_sha256": ACCEPTED_PARITY_CONTENT_SHA256}


def _analytics_bindings(
    root: Path,
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    descriptor = _exact_descriptor(root, ANALYTICS_INDEX, "analytics binding index")
    index = _json(root / ANALYTICS_INDEX[0], "analytics binding index")
    _require(
        index.get("artifact_kind") == "vast_analytics_execution_worker_binding_set"
        and (index.get("identity") or {}).get("sha256") == ANALYTICS_INDEX_IDENTITY
        and index.get("bindings_identity_sha256") == ANALYTICS_BINDINGS_IDENTITY
        and index.get("execution_config_identity_sha256") == EXECUTION_CONFIG_IDENTITY
        and index.get("model_parity_manifest_identity_sha256")
        == MODEL_PARITY_MANIFEST_IDENTITY
        and index.get("protocol_identity_sha256") == PROTOCOL_IDENTITY
        and index.get("worker_implementation_sha256") == {
            "openvino_cpu": WORKER_IMPLEMENTATIONS["cpu"],
            "tensorrt_cuda": WORKER_IMPLEMENTATIONS["gpu"],
        },
        "analytics binding index identity drifted",
    )
    files = index.get("files")
    _require(type(files) is list and len(files) == 8, "analytics binding set drifted")
    expected = {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    base = PurePosixPath(ANALYTICS_INDEX[0]).parent
    for item in files:
        _require(
            type(item) is dict and set(item) == {"path", "bytes", "sha256"},
            "analytics binding row fields drifted",
        )
        match = re.fullmatch(
            r"(plate_number|vehicle_type|damage|foreign_object)\."
            r"(openvino_cpu|tensorrt_cuda)\.json",
            str(item.get("path", "")),
        )
        _require(match is not None, "analytics binding filename drifted")
        resource = "cpu" if match.group(2) == "openvino_cpu" else "gpu"
        key = (match.group(1), resource)
        _require(key in expected and key not in observed, "analytics binding coverage drifted")
        relative = (base / str(item["path"])).as_posix()
        binding_descriptor = _exact_descriptor(
            root, (relative, int(item["bytes"]), str(item["sha256"])),
            f"analytics binding {key}",
        )
        binding = _json(root / relative, f"analytics binding {key}")
        expected_kind = (
            "vast_openvino_execution_worker_binding"
            if resource == "cpu" else "vast_tensorrt_execution_worker_binding"
        )
        expected_image = CPU_WORKER_IMAGE_ID if resource == "cpu" else GPU_WORKER_IMAGE_ID
        _require(
            binding.get("artifact_kind") == expected_kind
            and binding.get("branch") == key[0]
            and binding.get("worker_image_id") == expected_image
            and type(binding.get("model_id")) is str
            and bool(binding["model_id"])
            and binding.get("preprocessing_contract_sha256")
            == PREPROCESSING_CONTRACT_SHA256,
            f"analytics binding {key} identity drifted",
        )
        observed[key] = {"descriptor": binding_descriptor, "binding": binding}
    _require(set(observed) == expected, "analytics binding coordinate set drifted")
    return {**descriptor, "identity_sha256": ANALYTICS_INDEX_IDENTITY}, observed


def _runtime_probes(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        descriptor = _exact_descriptor(root, RUNTIME_PROBES[resource], f"{resource} probe")
        probe = _json(root / descriptor["path"], f"{resource} probe")
        engine = "openvino_cpu" if resource == "cpu" else "tensorrt_cuda"
        api = "CPU" if resource == "cpu" else "NVIDIA_CUDA"
        _require(
            probe.get("artifact_kind")
            == "vast_analytics_execution_worker_runtime_probe"
            and probe.get("engine") == engine and probe.get("device_api") == api
            and probe.get("protocol_identity_sha256") == PROTOCOL_IDENTITY
            and probe.get("worker_implementation_sha256")
            == WORKER_IMPLEMENTATIONS[resource],
            f"{resource} runtime probe identity drifted",
        )
        if resource == "gpu":
            _require(probe.get("device_id") == GPU_UUID, "GPU probe UUID drifted")
        result[resource] = {"descriptor": descriptor, "probe": probe}
    return result


def _openvino_bindings(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    relative = "configs/checkpoint_analytics_models_openvino.yaml"
    descriptor = _descriptor(root, relative, "OpenVINO model manifest")
    manifest = _yaml(root / relative, "OpenVINO model manifest")
    branches = manifest.get("branches")
    _require(
        manifest.get("schema_version") == 2
        and manifest.get("artifact_kind") == "checkpoint_analytics_model_bindings"
        and manifest.get("runtime_family") == "openvino_dlstreamer"
        and type(branches) is dict and set(branches) == set(BRANCHES),
        "OpenVINO model manifest identity drifted",
    )
    result: dict[str, dict[str, Any]] = {}
    for branch in BRANCHES:
        binding = branches[branch]
        _require(
            type(binding) is dict and binding.get("factory") in {"gvadetect", "object_detect"}
            and binding.get("device") == "CPU"
            and _SHA_RE.fullmatch(str(binding.get("model_sha256", ""))) is not None
            and _SHA_RE.fullmatch(str(binding.get("weights_sha256", ""))) is not None,
            f"OpenVINO binding {branch} invalid",
        )
        model = (root / "configs" / str(binding["model_path"])).resolve(strict=True)
        weights = (root / "configs" / str(binding["weights_path"])).resolve(strict=True)
        try:
            model_relative = model.relative_to(root).as_posix()
            weights_relative = weights.relative_to(root).as_posix()
        except ValueError as error:
            raise QualificationFragmentError(f"OpenVINO binding {branch} escaped") from error
        result[branch] = {
            "factory": binding["factory"],
            "device": "CPU",
            "detector_id": str(binding.get("detector_id", "")),
            "model": _exact_descriptor(
                root, (model_relative, model.stat().st_size, str(binding["model_sha256"])),
                f"OpenVINO {branch} model",
            ),
            "weights": _exact_descriptor(
                root, (weights_relative, weights.stat().st_size, str(binding["weights_sha256"])),
                f"OpenVINO {branch} weights",
            ),
        }
    return descriptor, result


def _policy_contract(root: Path) -> dict[str, Any]:
    descriptor = _descriptor(root, "scripts/publication_policy_contract.py", "policy contract")
    try:
        from publication_policy_contract import policy_contract_identity
        identity = policy_contract_identity()
    except Exception as error:
        raise QualificationFragmentError(f"policy contract unavailable: {error}") from error
    _require(
        type(identity) is dict and identity.get("schema_version") == 1
        and _SHA_RE.fullmatch(str(identity.get("sha256", ""))) is not None,
        "policy contract identity invalid",
    )
    return {**descriptor, "identity_sha256": identity["sha256"]}


def _runtime_sources(root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "native_probe_source": "deploy/native_gst_probe/vast_native_gst_probe.cpp",
        "analytics_execution_client": "deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp",
        "resource_interval_emitter": "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
        "analytics_execution_protocol": "scripts/analytics_execution_protocol.py",
        "analytics_bridge": "scripts/checkpoint_gstreamer_analytics_bridge.py",
        "native_policy_runtime": "scripts/checkpoint_native_policy_runtime.py",
        "analytics_sidecar": "scripts/checkpoint_gstreamer_analytics_sidecar.py",
        "gstreamer_runtime": "scripts/checkpoint_gstreamer_runtime.py",
        "container_boundary": "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
        "container_source_allowlist": "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
        "source_closure_validator": "deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py",
        "hardware_collector": "scripts/collect_metrics.py",
        "full_resource_validator": "scripts/full_resource_contract.py",
        "interval_validator": "scripts/resource_interval_contract.py",
    }
    return {role: _descriptor(root, path, role) for role, path in paths.items()}


def _source_set_identity(root: Path) -> dict[str, Any]:
    relative = "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt"
    descriptor = _descriptor(root, relative, "GStreamer source allowlist")
    _require(
        descriptor["sha256"] == GSTREAMER_SOURCE_ALLOWLIST_SHA256,
        "GStreamer source allowlist identity drifted",
    )
    validator_relative = (
        "deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py"
    )
    validator_descriptor = _descriptor(
        root, validator_relative, "GStreamer source closure validator",
    )
    validator_path = root / validator_relative
    specification = importlib.util.spec_from_file_location(
        "qualification_gstreamer_runtime_source_closure_v3", validator_path,
    )
    _require(
        specification is not None and specification.loader is not None,
        "GStreamer runtime source closure validator cannot be loaded",
    )
    module = importlib.util.module_from_spec(specification)
    try:
        specification.loader.exec_module(module)
        result = module.validate_runtime_source_closure(
            project_root=root, manifest_path=root / relative,
        )
    except (OSError, ValueError, AttributeError, ImportError) as error:
        raise QualificationFragmentError(
            "GStreamer runtime source closure validation failed"
        ) from error
    values = result.get("all_sources") if type(result) is dict else None
    _require(
        type(values) in {tuple, list} and bool(values),
        "GStreamer runtime source closure is empty",
    )
    rows = bytearray()
    native_rows = bytearray()
    for value in values:
        path = _relative_file(root, str(value), "GStreamer runtime source")
        _, digest = _stable_hash(path, "GStreamer runtime source")
        row = f"{digest}  {value}\n".encode("ascii")
        rows.extend(row)
        if str(value).startswith("deploy/native_gst_probe/"):
            native_rows.extend(row)
    runtime_sha = hashlib.sha256(rows).hexdigest()
    native_sha = hashlib.sha256(native_rows).hexdigest()
    _require(
        runtime_sha == GSTREAMER_RUNTIME_SOURCE_SHA256
        and native_sha == GSTREAMER_NATIVE_SOURCE_SHA256,
        "GStreamer transitive runtime source identity drifted",
    )
    _require(
        _descriptor(root, relative, "GStreamer source allowlist") == descriptor,
        "GStreamer source allowlist changed during validation",
    )
    _require(
        _descriptor(root, validator_relative, "GStreamer source closure validator")
        == validator_descriptor,
        "GStreamer source closure validator changed during validation",
    )
    return {
        **descriptor,
        "validator": validator_descriptor,
        "runtime_source_sha256": runtime_sha,
        "native_source_sha256": native_sha,
        "validated_source_count": len(values),
    }


def _image_identity(root: Path) -> dict[str, Any]:
    return {
        "final_reference": GSTREAMER_IMAGE_REFERENCE,
        "image_id": GSTREAMER_IMAGE_ID,
        "repository_digest": GSTREAMER_REPOSITORY_DIGEST,
        "inspect_projection_sha256": GSTREAMER_IMAGE_PROJECTION_SHA256,
        "base_image_id": GSTREAMER_BASE_IMAGE_ID,
        "runtime_source_sha256": GSTREAMER_RUNTIME_SOURCE_SHA256,
        "native_probe_source_sha256": GSTREAMER_NATIVE_SOURCE_SHA256,
        "dependency_set_sha256": GSTREAMER_DEPENDENCY_SET_SHA256,
        "runtime_source_allowlist_sha256": GSTREAMER_SOURCE_ALLOWLIST_SHA256,
        "embedded_native_probe_sha256": NATIVE_PROBE_SHA256,
        "embedded_analytics_terminal_sha256": ANALYTICS_TERMINAL_SHA256,
        "source_set": _source_set_identity(root),
    }


def _policy_identity(
    resource: str,
    worker: Mapping[str, Any],
    probe: Mapping[str, Any],
) -> dict[str, Any]:
    terminal_detector = (
        f"{worker['model_id']};"
        f"model_sha256={worker['source_model_sha256']}"
    )
    device = "CPU" if resource == "cpu" else "NVIDIA_CUDA:0"
    terminal_backend = (
        f"analytics-execution:{probe['engine']};runtime={probe['runtime_name']};"
        f"native_api={probe['native_inference_api']};device={device}"
    )
    return {
        "runtime_backend": (
            "gstreamer_custom_analytics_sidecar_openvino_cpu_v3"
            if resource == "cpu"
            else "gstreamer_custom_analytics_sidecar_tensorrt_cuda_v3"
        ),
        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "gpu_id": None if resource == "cpu" else 0,
        "worker_image_digest": (
            CPU_WORKER_IMAGE_ID if resource == "cpu" else GPU_WORKER_IMAGE_ID
        ),
        "implementation_version": "sha256:" + WORKER_IMPLEMENTATIONS[resource],
        "terminal_detector": terminal_detector,
        "terminal_backend": terminal_backend,
    }


def _resource_identity(resource: str) -> dict[str, str]:
    return {
        "runtime_backend": "gstreamer_custom_immutable_container_runtime_v3",
        "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "decoder_device_api": "NVIDIA_NVDEC",
        "worker_image_digest": GSTREAMER_IMAGE_ID,
        "implementation_version": (
            "gstreamer-custom-publication-runtime-v3:" + GSTREAMER_RUNTIME_SOURCE_SHA256
        ),
        "hardware_binding_id": f"nvidia-gpu:{GPU_UUID}:driver-{GPU_DRIVER}",
    }


def _material_values(root: Path) -> list[tuple[str, str, str, dict[str, Any]]]:
    parity = _accepted_parity(root)
    binding_index, bindings = _analytics_bindings(root)
    probes = _runtime_probes(root)
    model_manifest, openvino = _openvino_bindings(root)
    policy_contract = _policy_contract(root)
    sources = _runtime_sources(root)
    image = _image_identity(root)
    materials: list[tuple[str, str, str, dict[str, Any]]] = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            worker = bindings[(branch, resource)]
            local = openvino[branch]
            worker_value = worker["binding"]
            implementation_id = (
                f"gstreamer-custom-analytics-execution-v3:{branch}:{resource}:"
                f"{WORKER_IMPLEMENTATIONS[resource]}:{GSTREAMER_RUNTIME_SOURCE_SHA256}"
            )
            emitter_id = f"vast-native-gst-policy-path-v1:{branch}:{resource}"
            runtime_identity = _policy_identity(
                resource, worker_value, probes[resource]["probe"],
            )
            artifact = {
                "schema_version": 1,
                "artifact_kind": "vast_gstreamer_custom_policy_binding_material_v1",
                "system": SYSTEM,
                "role": "policy",
                "branch": branch,
                "resource": resource,
                "implementation_id": implementation_id,
                "emitter_id": emitter_id,
                "runtime_identity": runtime_identity,
                "policy_contract": policy_contract,
                "accepted_model_parity_manifest": parity,
                "preprocessing_contract_sha256": PREPROCESSING_CONTRACT_SHA256,
                "analytics_execution_binding_index": binding_index,
                "analytics_execution_worker_binding": worker["descriptor"],
                "analytics_execution_worker_binding_identity": {
                    "artifact_kind": worker_value["artifact_kind"],
                    "model_id": worker_value["model_id"],
                    "model_artifact_sha256": worker_value["model_artifact_sha256"],
                    "worker_image_id": worker_value["worker_image_id"],
                },
                "analytics_runtime_probe": probes[resource]["descriptor"],
                "gstreamer_runtime_image": image,
                "native_emitter": {
                    "container_path": "/usr/local/bin/vast_native_gst_probe",
                    "sha256": NATIVE_PROBE_SHA256,
                    "terminal_plugin_container_path": (
                        "/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so"
                    ),
                    "terminal_plugin_sha256": ANALYTICS_TERMINAL_SHA256,
                },
                "runtime_sources": sources,
                "openvino_cpu_model_manifest": model_manifest,
                "openvino_cpu_binding": local,
                "nvidia_hardware_binding": {
                    "uuid": GPU_UUID, "name": GPU_NAME, "driver_version": GPU_DRIVER,
                },
            }
            materials.append(("policy", branch, resource, artifact))
    for resource in RESOURCES:
        implementation_id = (
            f"gstreamer-custom-full-resource-v2:{resource}:{GSTREAMER_IMAGE_ID}"
        )
        emitter_id = (
            f"gstreamer-custom-full-resource-v2-native-emitters:{resource}:"
            f"{NATIVE_PROBE_SHA256}"
        )
        artifact = {
            "schema_version": 1,
            "artifact_kind": "vast_gstreamer_custom_resource_binding_material_v1",
            "system": SYSTEM,
            "role": "resource",
            "branch": "all_branches",
            "resource": resource,
            "implementation_id": implementation_id,
            "emitter_id": emitter_id,
            "runtime_identity": _resource_identity(resource),
            "accepted_model_parity_manifest": parity,
            "preprocessing_contract_sha256": PREPROCESSING_CONTRACT_SHA256,
            "gstreamer_runtime_image": image,
            "analytics_runtime_probe": probes[resource]["descriptor"],
            "resource_emitters": {
                "resource_intervals": {
                    "producer": sources["resource_interval_emitter"],
                    "native_probe_sha256": NATIVE_PROBE_SHA256,
                },
                "hardware_resource_samples": {
                    "producer": sources["hardware_collector"],
                    "device_api": "NVIDIA_NVML", "device_id": GPU_UUID,
                },
                "fanout_work_counters": {
                    "producer": sources["native_probe_source"],
                    "native_probe_sha256": NATIVE_PROBE_SHA256,
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
                "uuid": GPU_UUID, "name": GPU_NAME, "driver_version": GPU_DRIVER,
                "decoder_device_api": "NVIDIA_NVDEC",
            },
        }
        materials.append(("resource", "all_branches", resource, artifact))
    return materials


def _output_dir(root: Path, value: Path) -> Path:
    output = Path(os.path.abspath(os.fspath(value)))
    try:
        relative = output.relative_to(root)
    except ValueError as error:
        raise QualificationFragmentError("output must remain under project_root") from error
    _require(output != root, "output cannot be project_root")
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.exists():
            _require(cursor.is_dir() and not _is_link(cursor), "output path unsafe")
        else:
            cursor.mkdir(mode=0o755)
            _require(not _is_link(cursor), "created output directory unsafe")
    _require(output.resolve(strict=True) == output, "output path is aliased")
    return output


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        info = path.lstat()
        _require(
            not _is_link(path) and stat.S_ISREG(info.st_mode)
            and int(info.st_nlink) == 1 and path.read_bytes() == payload,
            f"immutable qualification output collision: {path.name}",
        )
        return
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    _require(not _is_link(path.parent), "binding directory unsafe")
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        _require(int(temporary.lstat().st_nlink) == 1, "temporary output aliased")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_path(
    root: Path, output: Path, role: str, branch: str, resource: str,
) -> str:
    name = (
        f"{branch}.{resource}.binding.json"
        if role == "policy" else f"{resource}.binding.json"
    )
    return (output / "bindings" / role / name).relative_to(root).as_posix()


def _expected(
    root: Path, output: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    policy: list[dict[str, Any]] = []
    resource: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    for role, branch, coordinate, artifact in _material_values(root):
        relative = _artifact_path(root, output, role, branch, coordinate)
        payload = _canonical_bytes(artifact)
        payloads[relative] = payload
        row = {
            "role": role,
            "branch": branch,
            "resource": coordinate,
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "implementation_id": artifact["implementation_id"],
            "emitter_id": artifact["emitter_id"],
            "runtime_identity": artifact["runtime_identity"],
        }
        (policy if role == "policy" else resource).append(row)
    return ({
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "system": SYSTEM,
        "policy_bindings": policy,
        "resource_bindings": resource,
        "pilots": [],
    }, payloads)


def _failure(message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_qualification_system_fragment_assessment_v1",
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
    *, project_root: Path, fragment_path: Path,
) -> dict[str, Any]:
    """Re-hash all physical inputs and reject self-declared phase-one state."""
    try:
        root = _project_root(project_root)
        candidate = Path(fragment_path).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise QualificationFragmentError("fragment escaped project_root") from error
        info = candidate.lstat()
        _require(
            candidate.name == FRAGMENT_FILENAME and not _is_link(candidate)
            and stat.S_ISREG(info.st_mode) and int(info.st_nlink) == 1,
            "fragment must be a physical regular file",
        )
        value = _json(candidate, "qualification fragment")
        _require(set(value) == FRAGMENT_FIELDS, "qualification fragment fields drifted")
        _require(
            value.get("schema_version") == 1 and value.get("artifact_kind") == ARTIFACT_KIND
            and value.get("system") == SYSTEM,
            "qualification fragment identity drifted",
        )
        _require(value.get("pilots") == [], "phase-one pilots must remain empty")
        expected, payloads = _expected(root, candidate.parent)
        _require(value == expected, "qualification fragment binding values drifted")
        paths: set[str] = set()
        identities: set[tuple[int, int]] = set()
        for row in (*value["policy_bindings"], *value["resource_bindings"]):
            _require(type(row) is dict and set(row) == ROW_FIELDS, "binding row fields drifted")
            fields = POLICY_RUNTIME_FIELDS if row["role"] == "policy" else RESOURCE_RUNTIME_FIELDS
            _require(
                type(row["runtime_identity"]) is dict
                and set(row["runtime_identity"]) == fields,
                "binding runtime identity fields drifted",
            )
            _require(
                _ID_RE.fullmatch(str(row["implementation_id"])) is not None
                and _ID_RE.fullmatch(str(row["emitter_id"])) is not None,
                "binding implementation/emitter ID unstable",
            )
            artifact = _relative_file(root, row["path"], "physical binding")
            artifact_info = artifact.lstat()
            identity = (int(artifact_info.st_dev), int(artifact_info.st_ino))
            _require(
                row["path"] not in paths and identity not in identities,
                "physical binding path/inode alias prohibited",
            )
            paths.add(row["path"])
            identities.add(identity)
            payload = artifact.read_bytes()
            _require(
                payload == payloads[row["path"]] and len(payload) == row["size"]
                and hashlib.sha256(payload).hexdigest() == row["sha256"],
                "physical binding bytes/size/SHA-256 drifted",
            )
        _require(len(paths) == len(identities) == 10, "binding coverage drifted")
        return {
            "schema_version": 1,
            "artifact_kind": "vast_publication_qualification_system_fragment_assessment_v1",
            "passed": True,
            "status": "bindings_materialized_pilots_pending",
            "blockers": [],
            "fragment_sha256": _stable_hash(candidate, "qualification fragment")[1],
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
    *, project_root: Path, output_dir: Path,
) -> dict[str, Any]:
    """Write ten immutable physical bindings and commit the fragment last."""
    root = _project_root(project_root)
    output = _output_dir(root, output_dir)
    fragment, payloads = _expected(root, output)
    for relative, payload in payloads.items():
        _write_immutable(root / relative, payload)
    fragment_path = output / FRAGMENT_FILENAME
    _write_immutable(fragment_path, _canonical_bytes(fragment))
    assessment = assess_qualification_fragment(
        project_root=root, fragment_path=fragment_path,
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
    parser = argparse.ArgumentParser(description="Materialize GStreamer qualification fragment")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--assess-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.assess_only:
        result = assess_qualification_fragment(
            project_root=args.project_root,
            fragment_path=args.output_dir / FRAGMENT_FILENAME,
        )
    else:
        result = materialize_qualification_fragment(
            project_root=args.project_root, output_dir=args.output_dir,
        )
        result = {**result, "fragment_path": str(result["fragment_path"])}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND", "BRANCHES", "CPU_WORKER_IMAGE_ID", "FRAGMENT_FILENAME",
    "GPU_WORKER_IMAGE_ID", "GSTREAMER_IMAGE_ID", "GSTREAMER_IMAGE_REFERENCE",
    "QualificationFragmentError",
    "RESOURCES", "assess_qualification_fragment", "materialize_qualification_fragment",
]
