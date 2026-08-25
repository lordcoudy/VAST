#!/usr/bin/env python3
"""Fail-closed CPU OpenVINO versus NVIDIA CUDA/TensorRT model parity contract.

The module never downloads, converts, builds, or executes a model.  It only
canonicalizes a frozen requirements manifest and assesses already-local,
hash-bound artifacts and evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import yaml

from benchmark_contract import ContractError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
SCHEMA_VERSION = 3
ARTIFACT_KIND = "checkpoint_analytics_model_parity_manifest"
EXECUTION_CONFIG_PATH = "configs/analytics_execution_layer.yaml"
EXECUTION_CONFIG_SHA256 = "d9bec961f22395c005ac6866633aeeb8b9a829fd39bd776776a3b0cd84526033"
EXECUTION_CONFIG_CONTENT_IDENTITY_SHA256 = "3daed67a3e4c6549bf463b929e5de840e5aab7daacac75fff328f624b867b512"
EXECUTION_CONFIG_WORKER_PROJECTION_SHA256 = "b515a96dbd8f7d9cd7ebcb375fdeefc5c3f3deb687dfb803bef58faf2ab04b85"
BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
MIN_CALIBRATION_SAMPLES = 30
MIN_PARITY_SAMPLES = 30
MAX_EVIDENCE_JSON_BYTES = 64 * 1024 * 1024
PARITY_TOLERANCES = {
    "raw_max_abs_error": 0.02,
    "raw_max_rel_error": 0.05,
    "raw_mean_abs_error": 0.005,
    "raw_max_cosine_distance": 0.001,
    "top1_mismatch_rate": 0.0,
}
RELATIVE_ERROR_FLOOR = PARITY_TOLERANCES["raw_max_abs_error"]
SLOT_BINDINGS = {
    "plate_number": ("opaque_rn18", "resnet18_v1_7"),
    "vehicle_type": ("opaque_rn34", "resnet34_v1_7"),
    "damage": ("opaque_rn50", "resnet50_v1_12"),
    "foreign_object": ("opaque_rn101", "resnet101_v1_7"),
}
SOURCE_IDS = tuple(source for _, source in SLOT_BINDINGS.values())
EVIDENCE_NAMES = (
    "cpu_execution_probe",
    "cuda_execution_probe",
    "calibration_corpus",
    "evaluation_corpus",
    "cpu_policy_calibration",
    "cuda_policy_calibration",
    "cpu_raw_output_bundle",
    "cuda_raw_output_bundle",
)
LINEAGE_MODES = ("common_source",)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")

CommandRunner = Callable[[list[str]], str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError(f"model parity value is not canonical JSON: {error}") from error


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == expected, f"{label} fields have drifted")
    return value


def _string_or_none(value: Any, label: str) -> None:
    _require(value is None or (type(value) is str and bool(value.strip())), f"{label} is invalid")


def _digest_or_none(value: Any, label: str) -> None:
    _require(value is None or (type(value) is str and _SHA256_RE.fullmatch(value) is not None), f"{label} must be a lowercase SHA-256 or null")


def _artifact_ref(value: Any, label: str) -> None:
    record = _exact_fields(value, {"path", "sha256"}, label)
    _string_or_none(record.get("path"), f"{label}.path")
    _digest_or_none(record.get("sha256"), f"{label}.sha256")


def _required_digest(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA256_RE.fullmatch(value) is not None, f"{label} must be a lowercase SHA-256")
    return value


def _required_string(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value.strip()) and "\n" not in value and "\r" not in value, f"{label} is invalid")
    return value


def _validate_ref_v2(value: Any, label: str, *, digest_required: bool, size_required: bool = False) -> Mapping[str, Any]:
    fields = {"path", "sha256", "size_bytes"} if size_required else {"path", "sha256"}
    record = _exact_fields(value, fields, label)
    _required_string(record.get("path"), f"{label}.path")
    if digest_required:
        _required_digest(record.get("sha256"), f"{label}.sha256")
    else:
        _digest_or_none(record.get("sha256"), f"{label}.sha256")
    if size_required:
        _require(type(record.get("size_bytes")) is int and record["size_bytes"] > 0, f"{label}.size_bytes is invalid")
    return record


def _validate_source_v2(source_id: str, value: Any) -> None:
    record = _exact_fields(
        value,
        {
            "repository", "repository_revision", "resolve_url", "filename", "path", "sha256",
            "size_bytes", "license", "format", "onnx_ir_version", "onnx_opset",
            "input", "output",
        },
        f"source_registry.{source_id}",
    )
    repository = _required_string(record.get("repository"), f"{source_id}: repository")
    revision = _required_string(record.get("repository_revision"), f"{source_id}: repository_revision")
    _require(re.fullmatch(r"[0-9a-f]{40}", revision) is not None, f"{source_id}: repository_revision must be a commit SHA")
    filename = _required_string(record.get("filename"), f"{source_id}: filename")
    expected_repository = f"https://huggingface.co/onnxmodelzoo/{filename.removesuffix('.onnx')}"
    _require(repository == expected_repository, f"{source_id}: canonical repository URL drifted")
    _require(record.get("resolve_url") == f"{repository}/resolve/{revision}/{filename}", f"{source_id}: revision-pinned resolve URL drifted")
    _required_string(record.get("path"), f"{source_id}: path")
    _required_digest(record.get("sha256"), f"{source_id}: sha256")
    _require(type(record.get("size_bytes")) is int and record["size_bytes"] > 0, f"{source_id}: size_bytes is invalid")
    _require(record.get("license") == "Apache-2.0", f"{source_id}: license drifted")
    _require(record.get("format") == "onnx", f"{source_id}: format must be ONNX")
    _require(record.get("onnx_ir_version") in {"0.0.3", "0.0.4"}, f"{source_id}: ONNX IR version is invalid")
    _require(type(record.get("onnx_opset")) is int and 7 <= record["onnx_opset"] <= 30, f"{source_id}: ONNX opset is invalid")
    input_contract = _exact_fields(
        record.get("input"),
        {"name", "dtype", "layout", "source_shape", "execution_shape", "dynamic_shape_binding"},
        f"{source_id}: input",
    )
    _require(input_contract.get("name") == "data", f"{source_id}: input name drifted")
    _require(input_contract.get("dtype") == "float32" and input_contract.get("layout") == "NCHW", f"{source_id}: input dtype/layout drifted")
    _require(input_contract.get("source_shape") == ["batch", 3, 224, 224], f"{source_id}: source input shape drifted")
    _require(input_contract.get("execution_shape") == [1, 3, 224, 224], f"{source_id}: execution input shape drifted")
    binding = _exact_fields(input_contract.get("dynamic_shape_binding"), {"batch_dynamic", "min", "opt", "max"}, f"{source_id}: dynamic shape binding")
    _require(binding.get("batch_dynamic") is True, f"{source_id}: source batch must be recorded as dynamic")
    for name in ("min", "opt", "max"):
        _require(binding.get(name) == [1, 3, 224, 224], f"{source_id}: {name} binding drifted")
    output_contract = _exact_fields(
        record.get("output"),
        {"name", "dtype", "source_shape", "execution_shape", "contract_ref"},
        f"{source_id}: output",
    )
    _required_string(output_contract.get("name"), f"{source_id}: output name")
    _require(output_contract.get("dtype") == "float32", f"{source_id}: output dtype drifted")
    _require(output_contract.get("source_shape") == ["batch", 1000], f"{source_id}: source output shape drifted")
    _require(output_contract.get("execution_shape") == [1, 1000], f"{source_id}: execution output shape drifted")
    _require(output_contract.get("contract_ref") == "imagenet_1000_raw_logits_fp32_v2", f"{source_id}: classification contract drifted")


def _validate_toolchains_v2(value: Any) -> None:
    registry = _exact_fields(value, {"openvino_cpu", "tensorrt_cuda"}, "toolchain_registry")
    ov = _exact_fields(registry["openvino_cpu"], {"runtime", "converter", "version", "image", "image_id", "device", "precision"}, "OpenVINO toolchain")
    _require(ov.get("runtime") == "openvino" and ov.get("converter") == "ovc" and ov.get("device") == "CPU" and ov.get("precision") == "float32", "OpenVINO toolchain drifted")
    _require(ov.get("version") == "2026.1.0-21367-63e31528c62-releases/2026/1", "OpenVINO version drifted")
    _require(ov.get("image") == "vast/openvino-native-probe:dlstreamer-2026.1", "OpenVINO image drifted")
    _require(_IMAGE_ID_RE.fullmatch(str(ov.get("image_id", ""))) is not None, "OpenVINO image_id is invalid")
    trt = _exact_fields(
        registry["tensorrt_cuda"],
        {"runtime", "builder", "version", "cuda_version", "image", "image_id", "device_api", "gpu_name", "gpu_uuid", "pci_bus_id", "driver_version", "compute_capability", "precision", "tf32"},
        "TensorRT toolchain",
    )
    _require(trt.get("runtime") == "tensorrt" and trt.get("builder") == "trtexec" and trt.get("device_api") == "NVIDIA_CUDA", "TensorRT runtime binding drifted")
    _require(trt.get("precision") == "float32" and trt.get("tf32") is False, "TensorRT FP32/noTF32 binding drifted")
    expected_trt = {
        "version": "8.6.1.6",
        "cuda_version": "12.2.2",
        "image": "vast/deepstream-native-probe:7.0",
        "gpu_name": "NVIDIA GeForce RTX 3060",
        "gpu_uuid": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
        "pci_bus_id": "00000000:01:00.0",
        "driver_version": "610.47",
        "compute_capability": "8.6",
    }
    _require(all(trt.get(field) == expected for field, expected in expected_trt.items()), "TensorRT toolchain/hardware identity drifted")
    _require(_IMAGE_ID_RE.fullmatch(str(trt.get("image_id", ""))) is not None, "TensorRT image_id is invalid")


def _validate_worker_runtime_registry_v3(
    value: Any,
    *,
    toolchains: Mapping[str, Any],
) -> None:
    registry = _exact_fields(
        value,
        {"execution_config", "openvino_cpu", "tensorrt_cuda"},
        "worker_runtime_registry",
    )
    execution_config = _exact_fields(
        registry["execution_config"],
        {"path", "sha256", "content_identity_sha256", "worker_projection_sha256"},
        "worker runtime execution config",
    )
    _require(
        execution_config.get("path") == EXECUTION_CONFIG_PATH,
        "worker runtime execution config path drifted",
    )
    _require(
        execution_config.get("sha256") == EXECUTION_CONFIG_SHA256
        and execution_config.get("content_identity_sha256")
        == EXECUTION_CONFIG_CONTENT_IDENTITY_SHA256,
        "worker runtime execution config identity drifted",
    )
    fields = {
        "toolchain_ref", "execution_resource", "base_image", "base_image_id",
        "image", "image_id", "worker_implementation_sha256",
    }
    for resource, execution_resource in (("openvino_cpu", "cpu"), ("tensorrt_cuda", "gpu")):
        runtime = _exact_fields(
            registry[resource], fields, f"{resource} worker runtime"
        )
        toolchain = toolchains[resource]
        _require(
            runtime.get("toolchain_ref") == resource
            and runtime.get("execution_resource") == execution_resource,
            f"{resource} worker runtime coordinate drifted",
        )
        _require(
            runtime.get("base_image") == toolchain["image"]
            and runtime.get("base_image_id") == toolchain["image_id"],
            f"{resource} worker runtime base/toolchain provenance drifted",
        )
        _required_string(runtime.get("image"), f"{resource} worker runtime image")
        _require(
            _IMAGE_ID_RE.fullmatch(str(runtime.get("image_id", ""))) is not None,
            f"{resource} worker runtime image_id is invalid",
        )
        _required_digest(
            runtime.get("worker_implementation_sha256"),
            f"{resource} worker runtime implementation SHA-256",
        )
        _require(
            runtime["image_id"] != runtime["base_image_id"],
            f"{resource} worker runtime image must not be relabelled as its base image",
        )
    projection = {
        resource: dict(registry[resource])
        for resource in ("openvino_cpu", "tensorrt_cuda")
    }
    _require(
        execution_config.get("worker_projection_sha256")
        == EXECUTION_CONFIG_WORKER_PROJECTION_SHA256
        == _sha256_bytes(_canonical_json(projection)),
        "worker runtime execution-config projection identity drifted",
    )


def _validate_derived_v2(branch: str, source: Mapping[str, Any], value: Any, *, kind: str) -> None:
    if kind == "openvino":
        record = _exact_fields(value, {"model", "weights", "derived_from_source_sha256", "toolchain_ref", "canonical_argv", "canonical_argv_sha256", "reproducibility"}, f"{branch}: openvino_ir")
        _validate_ref_v2(record["model"], f"{branch}: OpenVINO model", digest_required=True, size_required=True)
        _validate_ref_v2(record["weights"], f"{branch}: OpenVINO weights", digest_required=True, size_required=True)
        _require(record.get("toolchain_ref") == "openvino_cpu", f"{branch}: OpenVINO toolchain_ref drifted")
        _require(record.get("reproducibility") == "byte_reproducible_observed", f"{branch}: OpenVINO reproducibility fact drifted")
        expected_argv = ["ovc", "SOURCE.onnx", "--output_model", "DEST.xml", "--input", "data[1,3,224,224]", "--output", source["output"]["name"], "--compress_to_fp16=False"]
    else:
        record = _exact_fields(value, {"artifact", "derived_from_source_sha256", "toolchain_ref", "canonical_argv", "canonical_argv_sha256", "engine_authority", "rebuild_sha_expected", "parser_facts"}, f"{branch}: tensorrt_engine")
        _validate_ref_v2(record["artifact"], f"{branch}: TensorRT engine", digest_required=True, size_required=True)
        _require(record.get("toolchain_ref") == "tensorrt_cuda", f"{branch}: TensorRT toolchain_ref drifted")
        _require(record.get("engine_authority") == "archived_exact_engine_artifact", f"{branch}: TensorRT engine authority drifted")
        _require(record.get("rebuild_sha_expected") is False, f"{branch}: TensorRT rebuild SHA must not be expected")
        parser_facts = _exact_fields(record.get("parser_facts"), {"int64_initializers_cast_to_int32", "warning_disposition"}, f"{branch}: TensorRT parser facts")
        _require(parser_facts.get("int64_initializers_cast_to_int32") is True, f"{branch}: TensorRT INT64 cast warning fact drifted")
        _require(parser_facts.get("warning_disposition") == "non_blocking_if_numeric_parity_passes", f"{branch}: TensorRT warning disposition drifted")
        expected_argv = ["trtexec", "--onnx=SOURCE.onnx", "--saveEngine=DEST.engine", "--minShapes=data:1x3x224x224", "--optShapes=data:1x3x224x224", "--maxShapes=data:1x3x224x224", "--inputIOFormats=fp32:chw", "--outputIOFormats=fp32:chw", "--noTF32", "--memPoolSize=workspace:2048", "--builderOptimizationLevel=3", "--minTiming=1", "--avgTiming=8", "--noBuilderCache", "--skipInference", "--profilingVerbosity=detailed", "--tempfileControls=in_memory:allow,temporary:deny"]
    _require(record.get("derived_from_source_sha256") == source.get("sha256"), f"{branch}: {kind} source lineage mismatch")
    argv = record.get("canonical_argv")
    _require(type(argv) is list and argv == expected_argv, f"{branch}: {kind} canonical_argv drifted")
    _require(not any(Path(item).is_absolute() or re.match(r"^[A-Za-z]:[\\/]", item) for item in argv), f"{branch}: canonical_argv must not contain host absolute paths")
    _require(record.get("canonical_argv_sha256") == _sha256_bytes(_canonical_json(argv)), f"{branch}: {kind} canonical_argv_sha256 drifted")


def _validate_slot_v2(branch: str, value: Any, sources: Mapping[str, Any]) -> None:
    record = _exact_fields(value, {"slot_id", "source_ref", "semantic_claim", "openvino_ir", "tensorrt_engine", "evidence"}, f"{branch}: workload slot")
    expected_slot, expected_source = SLOT_BINDINGS[branch]
    _require(record.get("slot_id") == expected_slot and record.get("source_ref") == expected_source, f"{branch}: opaque workload binding drifted")
    _require(record.get("semantic_claim") == "topology_load_proxy_only", f"{branch}: semantic claim drifted")
    source = sources[expected_source]
    _validate_derived_v2(branch, source, record["openvino_ir"], kind="openvino")
    _validate_derived_v2(branch, source, record["tensorrt_engine"], kind="tensorrt")
    evidence = _exact_fields(record.get("evidence"), set(EVIDENCE_NAMES), f"{branch}: evidence")
    for name in EVIDENCE_NAMES:
        _validate_ref_v2(evidence[name], f"{branch}: {name}", digest_required=False)


def _validate_manifest_v3(value: Any) -> None:
    manifest = _exact_fields(
        value,
        {"schema_version", "artifact_kind", "manifest_id", "claim_scope", "semantic_claim", "required_branches", "matrix_binding", "preprocessing_contract", "classification_contract", "evidence_policy", "source_registry", "toolchain_registry", "worker_runtime_registry", "workload_slots"},
        "model parity manifest",
    )
    _require(manifest.get("schema_version") == SCHEMA_VERSION, "model parity schema_version drifted")
    _require(manifest.get("artifact_kind") == ARTIFACT_KIND, "model parity artifact_kind drifted")
    _require(_STABLE_ID_RE.fullmatch(str(manifest.get("manifest_id") or "")) is not None and str(manifest["manifest_id"]).endswith("-v3"), "model parity manifest_id is invalid")
    _require(manifest.get("claim_scope") == "cpu_openvino_vs_nvidia_cuda_tensorrt", "model parity claim_scope drifted")
    _require(manifest.get("semantic_claim") == "topology_load_proxy_only", "model parity semantic claim drifted")
    _require(manifest.get("required_branches") == list(BRANCHES), "model parity frozen branch order drifted")
    matrix = _exact_fields(manifest.get("matrix_binding"), {"cpu", "gpu", "openvino_gpu_accepted", "network_download_allowed", "same_source_semantics_required"}, "matrix_binding")
    cpu = _exact_fields(matrix.get("cpu"), {"runtime", "device_api", "device_id", "image", "image_id"}, "CPU matrix binding")
    gpu = _exact_fields(matrix.get("gpu"), {"runtime", "device_api", "device_id_prefix", "image", "image_id"}, "GPU matrix binding")
    _require(cpu.get("runtime") == "openvino" and cpu.get("device_api") == "OPENVINO_CPU" and cpu.get("device_id") == "CPU", "CPU matrix binding must be exact OpenVINO CPU")
    _require(gpu.get("runtime") == "tensorrt" and gpu.get("device_api") == "NVIDIA_CUDA" and gpu.get("device_id_prefix") == "GPU-", "GPU matrix binding must be exact NVIDIA CUDA/TensorRT")
    for label, binding in (("CPU", cpu), ("GPU", gpu)):
        _required_string(binding.get("image"), f"{label} image")
        _require(_IMAGE_ID_RE.fullmatch(str(binding.get("image_id", ""))) is not None, f"{label} image_id is invalid")
    _require(matrix.get("openvino_gpu_accepted") is False, "OpenVINO GPU cannot count as NVIDIA CUDA")
    _require(matrix.get("network_download_allowed") is False, "model parity assessment must not download")
    _require(matrix.get("same_source_semantics_required") is True, "same-source semantics must be required")
    preprocessing = _exact_fields(manifest.get("preprocessing_contract"), {"contract_id", "decoded_color_order", "tensor_color_order", "decode_dtype", "resize_shorter_side", "resize_long_side_formula", "resize_algorithm", "resize_coordinate_transform", "half_pixel_coordinate_formula", "border_mode", "interpolation_accumulator_dtype", "interpolation_output_dtype", "interpolation_rounding", "resize_rounding", "center_crop", "normalization_scale", "normalization_mean", "normalization_std", "normalization_evaluation_order", "normalization_accumulator_dtype", "channel_transform", "output_dtype", "output_layout", "execution_shape", "tensor_serialization", "tensor_header", "tensor_endianness", "tensor_memory_order"}, "preprocessing_contract")
    _require(preprocessing.get("contract_id") == "imagenet_resnet_fp32_center_crop_v2", "preprocessing contract id drifted")
    _require(preprocessing.get("decoded_color_order") == "RGB" and preprocessing.get("tensor_color_order") == "RGB" and preprocessing.get("decode_dtype") == "uint8", "preprocessing decode contract drifted")
    _require(preprocessing.get("resize_shorter_side") == 256 and preprocessing.get("center_crop") == [224, 224], "preprocessing geometry drifted")
    _require(preprocessing.get("resize_long_side_formula") == "floor(long_side*256/short_side+0.5)" and preprocessing.get("resize_algorithm") == "bilinear" and preprocessing.get("resize_coordinate_transform") == "half_pixel" and preprocessing.get("half_pixel_coordinate_formula") == "src=(dst+0.5)*src_size/dst_size-0.5" and preprocessing.get("border_mode") == "edge_clamp", "preprocessing resize geometry drifted")
    _require(preprocessing.get("interpolation_accumulator_dtype") == "float32" and preprocessing.get("interpolation_output_dtype") == "float32" and preprocessing.get("interpolation_rounding") == "none", "preprocessing interpolation numeric semantics drifted")
    _require(preprocessing.get("normalization_scale") == 1.0 / 255.0 and preprocessing.get("normalization_mean") == [0.485, 0.456, 0.406] and preprocessing.get("normalization_std") == [0.229, 0.224, 0.225], "preprocessing normalization drifted")
    _require(preprocessing.get("normalization_evaluation_order") == "float32((float32(pixel)*scale-mean[channel])/std[channel])" and preprocessing.get("normalization_accumulator_dtype") == "float32", "preprocessing normalization evaluation drifted")
    _require(preprocessing.get("channel_transform") == "HWC_RGB_to_CHW_RGB" and preprocessing.get("output_dtype") == "float32" and preprocessing.get("output_layout") == "NCHW" and preprocessing.get("execution_shape") == [1, 3, 224, 224], "preprocessing output contract drifted")
    _require(preprocessing.get("tensor_serialization") == "raw_f32_le_c_contiguous_v1" and preprocessing.get("tensor_header") == "none" and preprocessing.get("tensor_endianness") == "little" and preprocessing.get("tensor_memory_order") == "C", "preprocessed tensor serialization drifted")
    classification = _exact_fields(manifest.get("classification_contract"), {"contract_id", "dtype", "semantics", "class_count", "softmax_applied", "argmax_tie_break"}, "classification_contract")
    _require(classification == {"contract_id": "imagenet_1000_raw_logits_fp32_v2", "dtype": "float32", "semantics": "raw_logits_pre_softmax", "class_count": 1000, "softmax_applied": False, "argmax_tie_break": "lowest_class_index"}, "classification raw-logits contract drifted")
    policy = _exact_fields(manifest.get("evidence_policy"), {"minimum_calibration_samples_per_branch_resource", "minimum_parity_samples_per_branch", "calibration_and_evaluation_disjoint", "claimed_aggregates_accepted", "max_evidence_json_bytes", "relative_error_floor", "tolerances"}, "evidence_policy")
    _require(policy.get("minimum_calibration_samples_per_branch_resource") == MIN_CALIBRATION_SAMPLES and policy.get("minimum_parity_samples_per_branch") == MIN_PARITY_SAMPLES, "evidence sample minimum drifted")
    _require(policy.get("calibration_and_evaluation_disjoint") is True and policy.get("claimed_aggregates_accepted") is False, "raw evidence policy drifted")
    _require(policy.get("max_evidence_json_bytes") == MAX_EVIDENCE_JSON_BYTES and policy.get("relative_error_floor") == RELATIVE_ERROR_FLOOR, "evidence safety/numeric policy drifted")
    tolerances = policy.get("tolerances")
    _require(type(tolerances) is dict and set(tolerances) == set(PARITY_TOLERANCES), "classification parity tolerance fields drifted")
    for key, expected in PARITY_TOLERANCES.items():
        actual = tolerances.get(key)
        _require(type(actual) in {int, float} and not isinstance(actual, bool) and math.isfinite(float(actual)) and float(actual) == expected, f"classification parity tolerance {key} drifted")
    sources = manifest.get("source_registry")
    _require(type(sources) is dict and set(sources) == set(SOURCE_IDS), "source_registry must exactly cover frozen sources")
    for source_id in SOURCE_IDS:
        _validate_source_v2(source_id, sources[source_id])
    _validate_toolchains_v2(manifest.get("toolchain_registry"))
    toolchains = manifest["toolchain_registry"]
    _require(toolchains["openvino_cpu"]["image"] == cpu["image"] and toolchains["openvino_cpu"]["image_id"] == cpu["image_id"], "OpenVINO image identity binding drifted")
    _require(toolchains["tensorrt_cuda"]["image"] == gpu["image"] and toolchains["tensorrt_cuda"]["image_id"] == gpu["image_id"], "TensorRT image identity binding drifted")
    _validate_worker_runtime_registry_v3(
        manifest.get("worker_runtime_registry"), toolchains=toolchains
    )
    slots = manifest.get("workload_slots")
    _require(type(slots) is dict and set(slots) == set(BRANCHES), "workload_slots must exactly cover frozen branches")
    for branch in BRANCHES:
        _validate_slot_v2(branch, slots[branch], sources)


def _with_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    result = _json_copy(value)
    result["identity"] = {
        "schema_version": 2,
        "algorithm": "sha256",
        "canonicalization": "sorted_compact_json_utf8_v2",
        "sha256": _sha256_bytes(_canonical_json(result)),
    }
    return result


def validate_manifest_identity(value: Mapping[str, Any]) -> None:
    _require(type(value) is dict, "model parity identity object must be a dictionary")
    identity = value.get("identity")
    _require(type(identity) is dict, "model parity identity is missing")
    expected = _sha256_bytes(_canonical_json({key: item for key, item in value.items() if key != "identity"}))
    _require(
        identity
        == {
            "schema_version": 2,
            "algorithm": "sha256",
            "canonicalization": "sorted_compact_json_utf8_v2",
            "sha256": expected,
        },
        "model parity manifest identity drifted",
    )
    _validate_manifest_v3({key: item for key, item in value.items() if key != "identity"})


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key: {key}", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010

_ManifestSnapshot = tuple[int, int, int, int, int, int, int]
_ManifestChainSnapshot = tuple[tuple[Path, _ManifestSnapshot], ...]


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    class _FileId128(ctypes.Structure):
        _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

    class _FileIdInfo(ctypes.Structure):
        _fields_ = [
            ("VolumeSerialNumber", ctypes.c_ulonglong),
            ("FileId", _FileId128),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE_W = _KERNEL32.CreateFileW
    _CREATE_FILE_W.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CREATE_FILE_W.restype = wintypes.HANDLE
    _GET_FILE_INFORMATION_BY_HANDLE = _KERNEL32.GetFileInformationByHandle
    _GET_FILE_INFORMATION_BY_HANDLE.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    _GET_FILE_INFORMATION_BY_HANDLE.restype = wintypes.BOOL
    _GET_FILE_INFORMATION_BY_HANDLE_EX = _KERNEL32.GetFileInformationByHandleEx
    _GET_FILE_INFORMATION_BY_HANDLE_EX.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _GET_FILE_INFORMATION_BY_HANDLE_EX.restype = wintypes.BOOL
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _CLOSE_HANDLE.restype = wintypes.BOOL

    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _FILE_READ_ATTRIBUTES = 0x00000080
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _OPEN_EXISTING = 3
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_ID_INFO_CLASS = 18
    _WINDOWS_TO_UNIX_EPOCH_100NS = 116444736000000000


def _stat_snapshot(observed: os.stat_result) -> _ManifestSnapshot:
    return (
        int(observed.st_dev),
        int(observed.st_ino),
        int(stat.S_IFMT(observed.st_mode)),
        int(observed.st_nlink),
        int(observed.st_size),
        int(observed.st_mtime_ns),
        int(observed.st_ctime_ns),
    )


def _snapshot_identity(value: _ManifestSnapshot) -> tuple[int, int, int]:
    return value[:3]


def _snapshot_cross_view_fields(
    value: _ManifestSnapshot,
) -> tuple[int, int, int, int, int, int]:
    # CPython's Windows path-stat and CRT fstat views can expose different
    # creation/change-time interpretations.  All other fields, including
    # mtime, are directly comparable; ctime remains bound within each view.
    return value[:6]


def _require_unique_manifest_path(value: _ManifestSnapshot) -> None:
    _require(
        value[3] == 1,
        "model parity manifest must have a unique path; hardlinks are rejected",
    )


def _manifest_chain_snapshot(path: Path) -> _ManifestChainSnapshot:
    """Validate every component and snapshot the plain lexical path chain."""

    _require(path.is_absolute(), "model parity manifest path is not absolute")
    parts = path.parts
    _require(bool(parts), "model parity manifest path is empty")
    current = Path(parts[0])
    result: list[tuple[Path, _ManifestSnapshot]] = []
    for index, part in enumerate(parts):
        if index:
            current /= part
        try:
            observed = current.lstat()
        except OSError as error:
            raise ContractError(
                f"model parity manifest was not found: {path}"
            ) from error
        attributes = int(getattr(observed, "st_file_attributes", 0))
        _require(
            not stat.S_ISLNK(observed.st_mode)
            and not (attributes & _FILE_ATTRIBUTE_REPARSE_POINT),
            (
                "model parity manifest was not found: path contains a link "
                f"or reparse point: {current}"
            ),
        )
        is_leaf = index == len(parts) - 1
        _require(
            stat.S_ISREG(observed.st_mode)
            if is_leaf
            else stat.S_ISDIR(observed.st_mode),
            f"model parity manifest was not found: {path}",
        )
        snapshot = _stat_snapshot(observed)
        if is_leaf:
            _require_unique_manifest_path(snapshot)
        result.append((current, snapshot))
    return tuple(result)


def _manifest_file_snapshot(path: Path) -> _ManifestSnapshot:
    return _manifest_chain_snapshot(path)[-1][1]


def _manifest_handle_snapshot(source: Any) -> _ManifestSnapshot:
    observed = os.fstat(source.fileno())
    attributes = int(getattr(observed, "st_file_attributes", 0))
    _require(
        stat.S_ISREG(observed.st_mode)
        and not stat.S_ISLNK(observed.st_mode)
        and not (attributes & _FILE_ATTRIBUTE_REPARSE_POINT),
        "model parity manifest handle is not a plain regular file",
    )
    snapshot = _stat_snapshot(observed)
    _require_unique_manifest_path(snapshot)
    return snapshot


def _require_manifest_chain_unchanged(
    before: _ManifestChainSnapshot,
    after: _ManifestChainSnapshot,
    *,
    bind_leaf_ctime: bool = True,
) -> None:
    _require(
        len(before) == len(after),
        "model parity manifest path chain changed during read",
    )
    for (before_path, before_state), (after_path, after_state) in zip(
        before, after
    ):
        _require(
            before_path == after_path
            and _snapshot_identity(before_state) == _snapshot_identity(after_state),
            "model parity manifest path chain changed during read",
        )
    if bind_leaf_ctime:
        leaf_unchanged = before[-1][1] == after[-1][1]
    else:
        leaf_unchanged = (
            _snapshot_cross_view_fields(before[-1][1])
            == _snapshot_cross_view_fields(after[-1][1])
        )
    _require(
        leaf_unchanged,
        "model parity manifest identity changed during read",
    )


def _windows_filetime_ns(value: Any) -> int:
    ticks = (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
    return (ticks - _WINDOWS_TO_UNIX_EPOCH_100NS) * 100


def _windows_handle_snapshot(handle: int) -> tuple[_ManifestSnapshot, int]:
    details = _ByHandleFileInformation()
    if not _GET_FILE_INFORMATION_BY_HANDLE(handle, ctypes.byref(details)):
        raise ContractError(
            "model parity manifest native handle metadata query failed: "
            f"Windows error {ctypes.get_last_error()}"
        )
    identity = _FileIdInfo()
    if not _GET_FILE_INFORMATION_BY_HANDLE_EX(
        handle,
        _FILE_ID_INFO_CLASS,
        ctypes.byref(identity),
        ctypes.sizeof(identity),
    ):
        raise ContractError(
            "model parity manifest native FileId query failed: "
            f"Windows error {ctypes.get_last_error()}"
        )
    attributes = int(details.dwFileAttributes)
    mode_type = (
        stat.S_IFDIR
        if attributes & _FILE_ATTRIBUTE_DIRECTORY
        else stat.S_IFREG
    )
    snapshot: _ManifestSnapshot = (
        int(identity.VolumeSerialNumber),
        int.from_bytes(bytes(identity.FileId.Identifier), "little"),
        mode_type,
        int(details.nNumberOfLinks),
        (int(details.nFileSizeHigh) << 32) | int(details.nFileSizeLow),
        _windows_filetime_ns(details.ftLastWriteTime),
        _windows_filetime_ns(details.ftCreationTime),
    )
    return snapshot, attributes


def _close_windows_handle(handle: int) -> None:
    if not _CLOSE_HANDLE(handle):
        raise ContractError(
            "model parity manifest native custody close failed: "
            f"Windows error {ctypes.get_last_error()}"
        )


def _open_windows_custody_handle(
    path: Path,
    *,
    is_directory: bool,
) -> tuple[int, _ManifestSnapshot, int]:
    access = _FILE_READ_ATTRIBUTES if is_directory else _GENERIC_READ
    flags = _FILE_FLAG_OPEN_REPARSE_POINT
    if is_directory:
        flags |= _FILE_FLAG_BACKUP_SEMANTICS
    handle = _CREATE_FILE_W(
        os.fspath(path),
        access,
        _FILE_SHARE_READ
        | (_FILE_SHARE_WRITE if is_directory else 0),
        None,
        _OPEN_EXISTING,
        flags,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        raise ContractError(
            "model parity manifest native custody could not be acquired "
            f"for {path}: "
            f"Windows error {ctypes.get_last_error()}"
        )
    try:
        snapshot, attributes = _windows_handle_snapshot(handle)
        _require(
            not (attributes & _FILE_ATTRIBUTE_REPARSE_POINT),
            "model parity manifest native custody encountered a reparse point",
        )
        _require(
            snapshot[2] == (stat.S_IFDIR if is_directory else stat.S_IFREG),
            "model parity manifest native custody object type differs",
        )
        if not is_directory:
            _require_unique_manifest_path(snapshot)
        return int(handle), snapshot, attributes
    except BaseException as error:
        try:
            _close_windows_handle(handle)
        except ContractError as close_error:
            error.add_note(str(close_error))
        raise


@contextlib.contextmanager
def _windows_manifest_custody(
    chains: tuple[_ManifestChainSnapshot, ...],
) -> Iterator[tuple[tuple[Path, int, bool, _ManifestSnapshot], ...]]:
    entries: list[tuple[Path, int, bool, _ManifestSnapshot]] = []
    try:
        for chain in chains:
            # Keep the volume root and immediate parent undeletable while the
            # leaf is held no-write/no-delete. Intermediate ancestors are
            # identity-bound by the pre/open/final chain rescans below.
            selected_indices = {0, max(0, len(chain) - 2), len(chain) - 1}
            for index, (path, path_state) in enumerate(chain):
                if index not in selected_indices:
                    continue
                is_directory = index != len(chain) - 1
                handle, native_state, _ = _open_windows_custody_handle(
                    path,
                    is_directory=is_directory,
                )
                entries.append((path, handle, is_directory, native_state))
                _require(
                    _snapshot_identity(native_state)
                    == _snapshot_identity(path_state),
                    "model parity manifest native/path identity differs",
                )
                if not is_directory:
                    _require(
                        _snapshot_cross_view_fields(native_state)
                        == _snapshot_cross_view_fields(path_state),
                        "model parity manifest native/path metadata differs",
                    )
        yield tuple(entries)
    finally:
        active_error = sys.exc_info()[1]
        close_errors: list[str] = []
        for _, handle, _, _ in reversed(entries):
            try:
                _close_windows_handle(handle)
            except ContractError as error:
                close_errors.append(str(error))
        if close_errors:
            message = "; ".join(close_errors)
            if active_error is not None:
                active_error.add_note(message)
            else:
                raise ContractError(message)


@contextlib.contextmanager
def _manifest_native_custody(
    chains: tuple[_ManifestChainSnapshot, ...],
) -> Iterator[tuple[tuple[Path, int, bool, _ManifestSnapshot], ...]]:
    if os.name == "nt":
        with _windows_manifest_custody(chains) as entries:
            yield entries
        return

    # POSIX has no Windows share-mode analogue.  The loader therefore makes no
    # exclusion claim there and relies on no-link chain scans plus dev/inode,
    # type, nlink, size, mtime, and ctime binding around the open handle/read.
    yield ()


def _validate_native_custody(
    entries: tuple[tuple[Path, int, bool, _ManifestSnapshot], ...],
    *,
    leaf_state: _ManifestSnapshot | None = None,
) -> None:
    if os.name != "nt":
        return
    for _, handle, is_directory, initial_state in entries:
        current_state, attributes = _windows_handle_snapshot(handle)
        _require(
            not (attributes & _FILE_ATTRIBUTE_REPARSE_POINT),
            "model parity manifest native custody changed to a reparse point",
        )
        if is_directory:
            _require(
                _snapshot_identity(current_state)
                == _snapshot_identity(initial_state),
                "model parity manifest ancestor identity changed during read",
            )
        else:
            _require(
                current_state == initial_state,
                "model parity manifest native handle changed during read",
            )
            if leaf_state is not None:
                _require(
                    _snapshot_cross_view_fields(current_state)
                    == _snapshot_cross_view_fields(leaf_state),
                    "model parity manifest native/open-handle metadata differs",
                )


def _read_manifest_preflight(
    path: Path,
    expected_state: _ManifestSnapshot,
) -> bytes:
    flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
    flags |= int(getattr(os, "O_NOINHERIT", 0))
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as source:
            handle_before = _manifest_handle_snapshot(source)
            state_equal = (
                _snapshot_cross_view_fields(handle_before)
                == _snapshot_cross_view_fields(expected_state)
                if os.name == "nt"
                else handle_before == expected_state
            )
            _require(
                state_equal,
                "model parity manifest identity changed before preflight read",
            )
            payload = source.read()
            handle_after = _manifest_handle_snapshot(source)
            _require(
                handle_after == handle_before,
                "model parity manifest handle changed during preflight read",
            )
    except OSError as error:
        raise ContractError(
            "invalid model parity manifest preflight read failure: "
            f"{error}"
        ) from error
    return payload


def load_parity_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict[str, Any]:
    candidate = Path(path)
    lexical_path = Path(os.path.abspath(os.fspath(candidate)))
    lexical_before_chain = _manifest_chain_snapshot(lexical_path)
    lexical_before = lexical_before_chain[-1][1]
    preflight_payload = _read_manifest_preflight(lexical_path, lexical_before)
    lexical_preflight_chain = _manifest_chain_snapshot(lexical_path)
    _require_manifest_chain_unchanged(
        lexical_before_chain,
        lexical_preflight_chain,
    )
    with _manifest_native_custody(
        (lexical_before_chain,)
    ) as lexical_custody:
        lexical_custody_chain = _manifest_chain_snapshot(lexical_path)
        _require_manifest_chain_unchanged(
            lexical_before_chain,
            lexical_custody_chain,
        )
        try:
            manifest_path = lexical_path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ContractError(
                f"model parity manifest was not found: {lexical_path}"
            ) from error
        resolved_before_chain = _manifest_chain_snapshot(manifest_path)
        resolved_before = resolved_before_chain[-1][1]
        _require(
            lexical_before == resolved_before,
            "model parity manifest lexical/resolved identity differs",
        )
        _validate_native_custody(lexical_custody)
        with _manifest_native_custody(
            (resolved_before_chain,)
        ) as resolved_custody:
            custody = lexical_custody + resolved_custody
            lexical_guard_chain = _manifest_chain_snapshot(lexical_path)
            resolved_guard_chain = _manifest_chain_snapshot(manifest_path)
            _require_manifest_chain_unchanged(
                lexical_before_chain,
                lexical_guard_chain,
            )
            _require_manifest_chain_unchanged(
                resolved_before_chain,
                resolved_guard_chain,
            )
            _validate_native_custody(custody)
            try:
                with manifest_path.open("rb") as source:
                    handle_before = _manifest_handle_snapshot(source)
                    lexical_read_chain = _manifest_chain_snapshot(lexical_path)
                    resolved_read_chain = _manifest_chain_snapshot(manifest_path)
                    _require_manifest_chain_unchanged(
                        lexical_before_chain,
                        lexical_read_chain,
                    )
                    _require_manifest_chain_unchanged(
                        resolved_before_chain,
                        resolved_read_chain,
                    )
                    open_path_state_equal = (
                        _snapshot_cross_view_fields(handle_before)
                        == _snapshot_cross_view_fields(
                            lexical_read_chain[-1][1]
                        )
                        == _snapshot_cross_view_fields(
                            resolved_read_chain[-1][1]
                        )
                        if os.name == "nt"
                        else handle_before
                        == lexical_read_chain[-1][1]
                        == resolved_read_chain[-1][1]
                    )
                    _require(
                        open_path_state_equal,
                        (
                            "model parity manifest identity was substituted "
                            "before read: "
                            f"path={lexical_read_chain[-1][1]!r} "
                            f"handle={handle_before!r}"
                        ),
                    )
                    if os.name != "nt":
                        _require(
                            handle_before == lexical_before,
                            "model parity manifest identity changed before read",
                        )
                    _validate_native_custody(
                        custody,
                        leaf_state=handle_before,
                    )
                    payload = source.read()
                    _require(
                        payload == preflight_payload,
                        "model parity manifest bytes changed before native custody",
                    )
                    handle_after = _manifest_handle_snapshot(source)
                    _require(
                        handle_after == handle_before,
                        "model parity manifest handle changed during read",
                    )
                    try:
                        raw = yaml.load(
                            payload.decode("utf-8"),
                            Loader=_UniqueKeyLoader,
                        )
                    except (
                        RecursionError,
                        TypeError,
                        UnicodeError,
                        yaml.YAMLError,
                    ) as error:
                        raise ContractError(
                            f"invalid model parity manifest: {error}"
                        ) from error
                    _validate_manifest_v3(raw)
                    result = _with_identity(raw)

                    handle_final = _manifest_handle_snapshot(source)
                    lexical_after_chain = _manifest_chain_snapshot(lexical_path)
                    resolved_after_chain = _manifest_chain_snapshot(
                        manifest_path
                    )
                    _require(
                        handle_final == handle_before,
                        "model parity manifest handle changed before return",
                    )
                    _require_manifest_chain_unchanged(
                        lexical_read_chain,
                        lexical_after_chain,
                    )
                    _require_manifest_chain_unchanged(
                        resolved_read_chain,
                        resolved_after_chain,
                    )
                    _validate_native_custody(
                        custody,
                        leaf_state=handle_before,
                    )
            except OSError as error:
                raise ContractError(
                    "invalid model parity manifest identity substitution or read "
                    f"failure: {error}"
                ) from error
    return result


def build_image_inspect_command(image: str) -> list[str]:
    _require(type(image) is str and bool(image.strip()), "runtime image reference is invalid")
    return ["docker", "image", "inspect", "--format", "{{json .}}", image]


def _default_command_runner(command: list[str]) -> str:
    try:
        return subprocess.check_output(
            command,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ContractError("local image inspect failed") from error


def _inspect_image(image: str, command_runner: CommandRunner) -> dict[str, Any] | None:
    try:
        raw = json.loads(command_runner(build_image_inspect_command(image)))
    except (ContractError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if type(raw) is not dict or _IMAGE_ID_RE.fullmatch(str(raw.get("Id", ""))) is None:
        return None
    digests = raw.get("RepoDigests") or []
    if type(digests) is not list or any(type(item) is not str for item in digests):
        return None
    return {
        "reference": image,
        "image_id": str(raw["Id"]),
        "repo_digests": sorted(set(digests)),
        "architecture": str(raw.get("Architecture", "")),
        "os": str(raw.get("Os", "")),
    }


def _safe_path(root: Path, value: Any) -> Path | None:
    if type(value) is not str or not value.strip():
        return None
    root = root.resolve()
    raw_candidate = root / value if not Path(value).is_absolute() else Path(value)
    lexical_candidate = Path(os.path.abspath(os.fspath(raw_candidate)))
    candidate = raw_candidate.resolve()
    try:
        lexical_candidate.relative_to(root)
        candidate.relative_to(root)
    except ValueError:
        return None
    if lexical_candidate != candidate or raw_candidate.is_symlink():
        return None
    return candidate


def _artifact_state(
    root: Path,
    value: Mapping[str, Any],
    *,
    missing_blocker: str,
    digest_blocker_prefix: str,
    blockers: list[str],
) -> dict[str, Any]:
    path = _safe_path(root, value.get("path"))
    declared = value.get("sha256")
    declared_size = value.get("size_bytes")
    state = {
        "path": value.get("path"),
        "declared_sha256": declared,
        "declared_size_bytes": declared_size,
        "present": False,
        "actual_size_bytes": None,
        "actual_sha256": None,
        "stable_during_hash": False,
        "verified": False,
    }
    if path is None or path.is_symlink() or not path.is_file():
        blockers.append(missing_blocker)
    else:
        try:
            before = path.stat()
            before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            state["present"] = True
            state["actual_size_bytes"] = before.st_size
            actual = _sha256_file(path)
            after = path.stat()
            after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        except OSError:
            blockers.append(f"{digest_blocker_prefix}_unreadable")
        else:
            state["actual_sha256"] = actual
            state["stable_during_hash"] = before_identity == after_identity
            if not state["stable_during_hash"]:
                blockers.append(f"{digest_blocker_prefix}_changed_during_hash")
            if declared_size is not None and before.st_size != declared_size:
                blockers.append(f"{digest_blocker_prefix}_size_mismatch")
            if declared is None:
                blockers.append(f"{digest_blocker_prefix}_sha256_missing")
            elif actual != declared:
                blockers.append(f"{digest_blocker_prefix}_sha256_mismatch")
            elif state["stable_during_hash"] and (declared_size is None or before.st_size == declared_size):
                state["verified"] = True
    if declared is None and not state["present"]:
        blockers.append(f"{digest_blocker_prefix}_sha256_missing")
    return state


def _load_verified_json(
    root: Path,
    reference: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    invalid_blocker: str,
    blockers: list[str],
) -> dict[str, Any] | None:
    if not state.get("verified"):
        return None
    path = _safe_path(root, reference.get("path"))

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = item
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    try:
        if path is None or path.stat().st_size > MAX_EVIDENCE_JSON_BYTES:
            raise ValueError("evidence JSON size exceeds the frozen limit")
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        value = None
    if type(value) is not dict:
        blockers.append(invalid_blocker)
        return None
    return value


def _execution_probe_blockers_v3(
    branch: str,
    slot: Mapping[str, Any],
    source: Mapping[str, Any],
    value: dict[str, Any] | None,
    *,
    resource: str,
    preprocessing_sha: str,
    output_sha: str,
    toolchains: Mapping[str, Any],
    worker_runtimes: Mapping[str, Any],
) -> list[str]:
    if value is None:
        return []
    label = "cpu" if resource == "openvino_cpu" else "cuda"
    expected = {
        "schema_version", "artifact_kind", "branch", "workload_slot_id", "resource",
        "runtime", "device_api", "device_id", "success", "source_sha256",
        "model_sha256", "weights_sha256", "engine_sha256",
        "preprocessing_contract_sha256", "output_contract_sha256", "runtime_image_id",
        "worker_implementation_sha256",
        "input_name", "input_shape", "input_dtype", "output_name", "output_shape",
        "output_dtype", "sample_count", "all_outputs_finite",
    }
    if set(value) != expected or value.get("schema_version") != 3 or value.get("artifact_kind") != "checkpoint_model_execution_probe" or value.get("branch") != branch or value.get("workload_slot_id") != slot["slot_id"] or value.get("resource") != resource:
        return [f"branch:{branch}:{label}_execution_probe_schema_invalid"]
    blockers: list[str] = []
    ov = slot["openvino_ir"]
    trt = slot["tensorrt_engine"]
    if resource == "openvino_cpu":
        tool = toolchains["openvino_cpu"]
        if value.get("runtime") != "openvino" or value.get("device_api") != "OPENVINO_CPU" or value.get("device_id") != "CPU":
            blockers.append(f"branch:{branch}:cpu_execution_probe_not_openvino_cpu")
        if value.get("model_sha256") != ov["model"]["sha256"] or value.get("weights_sha256") != ov["weights"]["sha256"] or value.get("engine_sha256") is not None:
            blockers.append(f"branch:{branch}:cpu_execution_probe_artifact_mismatch")
    else:
        tool = toolchains["tensorrt_cuda"]
        if value.get("runtime") != "tensorrt" or value.get("device_api") != "NVIDIA_CUDA" or value.get("device_id") != tool["gpu_uuid"]:
            blockers.append(f"branch:{branch}:cuda_execution_probe_not_nvidia_tensorrt")
        if value.get("model_sha256") is not None or value.get("weights_sha256") is not None or value.get("engine_sha256") != trt["artifact"]["sha256"]:
            blockers.append(f"branch:{branch}:cuda_execution_probe_artifact_mismatch")
    if value.get("source_sha256") != source["sha256"]:
        blockers.append(f"branch:{branch}:{label}_execution_probe_lineage_mismatch")
    if value.get("preprocessing_contract_sha256") != preprocessing_sha or value.get("output_contract_sha256") != output_sha:
        blockers.append(f"branch:{branch}:{label}_execution_probe_semantics_mismatch")
    worker_runtime = worker_runtimes[resource]
    if value.get("runtime_image_id") != worker_runtime["image_id"]:
        blockers.append(f"branch:{branch}:{label}_execution_probe_image_mismatch")
    if value.get("worker_implementation_sha256") != worker_runtime["worker_implementation_sha256"]:
        blockers.append(f"branch:{branch}:{label}_execution_probe_implementation_mismatch")
    input_contract = source["input"]
    output_contract = source["output"]
    if value.get("input_name") != input_contract["name"] or value.get("input_shape") != input_contract["execution_shape"] or value.get("input_dtype") != input_contract["dtype"]:
        blockers.append(f"branch:{branch}:{label}_execution_probe_input_mismatch")
    if value.get("output_name") != output_contract["name"] or value.get("output_shape") != output_contract["execution_shape"] or value.get("output_dtype") != output_contract["dtype"]:
        blockers.append(f"branch:{branch}:{label}_execution_probe_output_mismatch")
    if value.get("success") is not True or value.get("all_outputs_finite") is not True or type(value.get("sample_count")) is not int or value["sample_count"] < 1:
        blockers.append(f"branch:{branch}:{label}_execution_probe_not_successful")
    return blockers


def _corpus_blockers_v2(
    branch: str,
    slot_id: str,
    value: dict[str, Any] | None,
    *,
    role: str,
    minimum: int,
    root: Path,
    preprocessing_sha: str,
) -> tuple[list[str], list[dict[str, Any]] | None, dict[str, Any]]:
    if value is None:
        return [], None, {}
    expected = {
        "schema_version", "artifact_kind", "branch", "workload_slot_id", "corpus_role",
        "dataset_manifest", "dataset_aggregate_sha256", "producer_contract",
        "sample_count", "samples", "samples_sha256",
    }
    label = "calibration" if role == "calibration" else "evaluation"
    prefix = f"branch:{branch}:{label}_corpus"
    if set(value) != expected or value.get("schema_version") != 2 or value.get("artifact_kind") != "checkpoint_model_parity_corpus" or value.get("branch") != branch or value.get("workload_slot_id") != slot_id or value.get("corpus_role") != role:
        return [f"{prefix}_schema_invalid"], None, {}
    blockers: list[str] = []
    states: dict[str, Any] = {"dataset_files": {}, "producer_implementations": {}, "sample_bundles": {}}
    dataset_ref = value.get("dataset_manifest")
    if type(dataset_ref) is not dict or set(dataset_ref) != {"path", "sha256"} or _SHA256_RE.fullmatch(str(dataset_ref.get("sha256", ""))) is None:
        return [f"{prefix}_dataset_manifest_reference_invalid"], None, states
    dataset_state = _artifact_state(root, dataset_ref, missing_blocker=f"{prefix}_dataset_manifest_missing", digest_blocker_prefix=f"{prefix}_dataset_manifest", blockers=blockers)
    states["dataset_manifest"] = dataset_state
    dataset = _load_verified_json(root, dataset_ref, dataset_state, invalid_blocker=f"{prefix}_dataset_manifest_invalid", blockers=blockers)
    dataset_files_by_id: dict[str, dict[str, Any]] = {}
    dataset_aggregate: str | None = None
    if dataset is not None:
        dataset_fields = {"schema_version", "artifact_kind", "dataset_id", "files", "files_sha256"}
        files = dataset.get("files")
        if set(dataset) != dataset_fields or dataset.get("schema_version") != 2 or dataset.get("artifact_kind") != "checkpoint_model_dataset_manifest" or _STABLE_ID_RE.fullmatch(str(dataset.get("dataset_id", ""))) is None or type(files) is not list or not files:
            blockers.append(f"{prefix}_dataset_manifest_schema_invalid")
        else:
            files_valid = True
            for index, item in enumerate(files):
                fields = {"file_id", "file_index", "path", "sha256", "size_bytes", "codec", "container"}
                if type(item) is not dict or set(item) != fields or _STABLE_ID_RE.fullmatch(str(item.get("file_id", ""))) is None or item.get("file_index") != index or type(item.get("path")) is not str or _SHA256_RE.fullmatch(str(item.get("sha256", ""))) is None or type(item.get("size_bytes")) is not int or item["size_bytes"] <= 0 or item.get("codec") not in {"h264", "h265"} or type(item.get("container")) is not str or not item["container"]:
                    files_valid = False
                    continue
                if item["file_id"] in dataset_files_by_id:
                    files_valid = False
                    continue
                dataset_files_by_id[item["file_id"]] = item
                file_state = _artifact_state(root, item, missing_blocker=f"{prefix}_dataset_file_missing:{item['file_id']}", digest_blocker_prefix=f"{prefix}_dataset_file:{item['file_id']}", blockers=blockers)
                states["dataset_files"][item["file_id"]] = file_state
            if not files_valid or set(item.get("codec") for item in files if type(item) is dict) != {"h264", "h265"}:
                blockers.append(f"{prefix}_dataset_manifest_files_invalid")
            if dataset.get("files_sha256") != _sha256_bytes(_canonical_json(files)):
                blockers.append(f"{prefix}_dataset_manifest_files_sha256_invalid")
            dataset_aggregate = _sha256_bytes(_canonical_json({"dataset_id": dataset["dataset_id"], "files": files}))
            if value.get("dataset_aggregate_sha256") != dataset_aggregate:
                blockers.append(f"{prefix}_dataset_aggregate_identity_mismatch")
    producer = value.get("producer_contract")
    producer_fields = {"decoder", "preprocessing"}
    if type(producer) is not dict or set(producer) != producer_fields:
        blockers.append(f"{prefix}_producer_contract_invalid")
    else:
        decoder = producer.get("decoder")
        preprocessing = producer.get("preprocessing")
        decoder_fields = {"name", "version", "runtime_image_id", "implementation", "canonical_argv_sha256", "pixel_format"}
        preprocessing_fields = {"implementation", "canonical_argv_sha256", "contract_sha256"}
        if type(decoder) is not dict or set(decoder) != decoder_fields or type(decoder.get("name")) is not str or not decoder["name"] or type(decoder.get("version")) is not str or not decoder["version"] or _IMAGE_ID_RE.fullmatch(str(decoder.get("runtime_image_id", ""))) is None or _SHA256_RE.fullmatch(str(decoder.get("canonical_argv_sha256", ""))) is None or decoder.get("pixel_format") != "rgb24":
            blockers.append(f"{prefix}_decoder_contract_invalid")
        else:
            implementation = decoder.get("implementation")
            if type(implementation) is not dict or set(implementation) != {"path", "sha256", "size_bytes"}:
                blockers.append(f"{prefix}_decoder_implementation_invalid")
            else:
                states["producer_implementations"]["decoder"] = _artifact_state(root, implementation, missing_blocker=f"{prefix}_decoder_implementation_missing", digest_blocker_prefix=f"{prefix}_decoder_implementation", blockers=blockers)
        if type(preprocessing) is not dict or set(preprocessing) != preprocessing_fields or _SHA256_RE.fullmatch(str(preprocessing.get("canonical_argv_sha256", ""))) is None or preprocessing.get("contract_sha256") != preprocessing_sha:
            blockers.append(f"{prefix}_preprocessing_producer_contract_invalid")
        else:
            implementation = preprocessing.get("implementation")
            if type(implementation) is not dict or set(implementation) != {"path", "sha256", "size_bytes"}:
                blockers.append(f"{prefix}_preprocessing_implementation_invalid")
            else:
                states["producer_implementations"]["preprocessing"] = _artifact_state(root, implementation, missing_blocker=f"{prefix}_preprocessing_implementation_missing", digest_blocker_prefix=f"{prefix}_preprocessing_implementation", blockers=blockers)
    samples = value.get("samples")
    count = value.get("sample_count")
    if type(samples) is not list or type(count) is not int or count != len(samples):
        return list(dict.fromkeys(blockers + [f"{prefix}_schema_invalid"])), None, states
    bundle_cache: dict[tuple[str, str, int], bytes | None] = {}

    def bundle_bytes(descriptor: Mapping[str, Any], kind: str) -> bytes | None:
        key = (str(descriptor.get("path")), str(descriptor.get("sha256")), int(descriptor.get("size_bytes", -1)))
        if key in bundle_cache:
            return bundle_cache[key]
        state = _artifact_state(root, descriptor, missing_blocker=f"{prefix}_{kind}_bundle_missing", digest_blocker_prefix=f"{prefix}_{kind}_bundle", blockers=blockers)
        states["sample_bundles"]["|".join(map(str, key))] = state
        if not state.get("verified"):
            bundle_cache[key] = None
            return None
        path = _safe_path(root, descriptor.get("path"))
        try:
            before = path.stat() if path else None
            payload = path.read_bytes() if path else b""
            after = path.stat() if path else None
        except OSError:
            payload = b""
            before = after = None
        stable = before is not None and after is not None and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if not stable or len(payload) != descriptor.get("size_bytes") or _sha256_bytes(payload) != descriptor.get("sha256"):
            blockers.append(f"{prefix}_{kind}_bundle_changed_during_read")
            bundle_cache[key] = None
        else:
            bundle_cache[key] = payload
        return bundle_cache[key]

    normalized: list[dict[str, Any]] = []
    sample_fields = {"sample_id", "physical_sample_sha256", "dataset_file_id", "dataset_file_sha256", "codec", "file_index", "stream_index", "frame_index", "pts_ns", "input_sha256", "preprocessed_tensor_sha256", "raw_frame", "preprocessed_tensor"}
    codecs_seen: set[str] = set()
    for sample in samples:
        if type(sample) is not dict or set(sample) != sample_fields:
            blockers.append(f"{prefix}_sample_invalid")
            continue
        file_record = dataset_files_by_id.get(str(sample.get("dataset_file_id")))
        coordinates_valid = type(sample.get("file_index")) is int and sample["file_index"] >= 0 and type(sample.get("stream_index")) is int and sample["stream_index"] >= 0 and type(sample.get("frame_index")) is int and sample["frame_index"] >= 0 and type(sample.get("pts_ns")) is int and sample["pts_ns"] >= 0
        if _STABLE_ID_RE.fullmatch(str(sample.get("sample_id", ""))) is None or file_record is None or not coordinates_valid or sample.get("dataset_file_sha256") != (file_record or {}).get("sha256") or sample.get("file_index") != (file_record or {}).get("file_index") or sample.get("codec") != (file_record or {}).get("codec"):
            blockers.append(f"{prefix}_physical_source_binding_invalid")
            continue
        codecs_seen.add(sample["codec"])
        raw = sample.get("raw_frame")
        tensor = sample.get("preprocessed_tensor")
        common_bundle_fields = {"path", "sha256", "size_bytes", "offset_bytes", "length_bytes", "segment_sha256", "encoding", "dtype", "shape", "layout", "color_order"}
        if type(raw) is not dict or set(raw) != common_bundle_fields or raw.get("encoding") != "raw_bytes_v1" or raw.get("dtype") != "uint8" or raw.get("layout") != "HWC" or raw.get("color_order") != "RGB" or type(raw.get("shape")) is not list or len(raw["shape"]) != 3 or any(type(dimension) is not int or dimension <= 0 for dimension in raw["shape"]) or raw["shape"][-1] != 3:
            blockers.append(f"{prefix}_raw_frame_descriptor_invalid")
            continue
        if type(tensor) is not dict or set(tensor) != common_bundle_fields or tensor.get("encoding") != "raw_f32_le_c_contiguous_v1" or tensor.get("dtype") != "float32" or tensor.get("layout") != "NCHW" or tensor.get("color_order") != "RGB" or tensor.get("shape") != [1, 3, 224, 224]:
            blockers.append(f"{prefix}_preprocessed_tensor_descriptor_invalid")
            continue
        descriptor_valid = True
        for descriptor, kind, bytes_per_item in ((raw, "raw_frame", 1), (tensor, "preprocessed_tensor", 4)):
            for field in ("size_bytes", "offset_bytes", "length_bytes"):
                if type(descriptor.get(field)) is not int or descriptor[field] < (0 if field == "offset_bytes" else 1):
                    descriptor_valid = False
            expected_length = math.prod(descriptor["shape"]) * bytes_per_item
            if descriptor.get("length_bytes") != expected_length or _SHA256_RE.fullmatch(str(descriptor.get("sha256", ""))) is None or _SHA256_RE.fullmatch(str(descriptor.get("segment_sha256", ""))) is None:
                descriptor_valid = False
            payload = bundle_bytes(descriptor, kind) if descriptor_valid else None
            offset = descriptor.get("offset_bytes", -1)
            length = descriptor.get("length_bytes", -1)
            if payload is None or offset + length > len(payload) or _sha256_bytes(payload[offset:offset + length]) != descriptor.get("segment_sha256"):
                descriptor_valid = False
                blockers.append(f"{prefix}_{kind}_segment_invalid")
        if not descriptor_valid or sample.get("input_sha256") != raw.get("segment_sha256") or sample.get("preprocessed_tensor_sha256") != tensor.get("segment_sha256"):
            blockers.append(f"{prefix}_materialized_sample_hash_invalid")
            continue
        physical_payload = {
            "dataset_aggregate_sha256": dataset_aggregate,
            "dataset_file_id": sample["dataset_file_id"],
            "dataset_file_sha256": sample["dataset_file_sha256"],
            "codec": sample["codec"],
            "file_index": sample["file_index"],
            "stream_index": sample["stream_index"],
            "frame_index": sample["frame_index"],
            "pts_ns": sample["pts_ns"],
            "raw_frame_sha256": sample["input_sha256"],
        }
        if sample.get("physical_sample_sha256") != _sha256_bytes(_canonical_json(physical_payload)):
            blockers.append(f"{prefix}_physical_sample_sha256_invalid")
            continue
        normalized.append(dict(sample))
    if count < minimum or len(normalized) != count or len({sample["sample_id"] for sample in normalized}) != count or len({sample["physical_sample_sha256"] for sample in normalized}) != count:
        blockers.append(f"{prefix}_below_{minimum}")
    if codecs_seen != {"h264", "h265"}:
        blockers.append(f"{prefix}_codec_coverage_invalid")
    if value.get("samples_sha256") != _sha256_bytes(_canonical_json(samples)):
        blockers.append(f"{prefix}_samples_sha256_invalid")
    blockers = list(dict.fromkeys(blockers))
    return blockers, normalized if not blockers else None, states
def _policy_calibration_blockers_v2(
    branch: str,
    slot: Mapping[str, Any],
    source: Mapping[str, Any],
    value: dict[str, Any] | None,
    *,
    resource: str,
    corpus: list[dict[str, str]] | None,
    corpus_sha: str | None,
    execution_probe_sha: str | None,
    worker_runtimes: Mapping[str, Any],
) -> list[str]:
    if value is None:
        return []
    label = "cpu" if resource == "openvino_cpu" else "cuda"
    expected = {
        "schema_version", "artifact_kind", "branch", "workload_slot_id", "resource",
        "source_sha256", "model_sha256", "weights_sha256", "engine_sha256",
        "runtime_image_id", "execution_probe_sha256", "corpus_manifest_sha256",
        "sample_count", "samples",
    }
    if set(value) != expected or value.get("schema_version") != 2 or value.get("artifact_kind") != "checkpoint_model_policy_calibration" or value.get("branch") != branch or value.get("workload_slot_id") != slot["slot_id"] or value.get("resource") != resource:
        return [f"branch:{branch}:{label}_policy_calibration_schema_invalid"]
    blockers: list[str] = []
    ov = slot["openvino_ir"]
    trt = slot["tensorrt_engine"]
    worker_runtime = worker_runtimes[resource]
    if resource == "openvino_cpu":
        artifacts_match = value.get("model_sha256") == ov["model"]["sha256"] and value.get("weights_sha256") == ov["weights"]["sha256"] and value.get("engine_sha256") is None
    else:
        artifacts_match = value.get("model_sha256") is None and value.get("weights_sha256") is None and value.get("engine_sha256") == trt["artifact"]["sha256"]
    if not artifacts_match:
        blockers.append(f"branch:{branch}:{label}_policy_calibration_artifact_mismatch")
    if value.get("source_sha256") != source["sha256"] or value.get("runtime_image_id") != worker_runtime["image_id"] or value.get("execution_probe_sha256") != execution_probe_sha or value.get("corpus_manifest_sha256") != corpus_sha:
        blockers.append(f"branch:{branch}:{label}_policy_calibration_binding_mismatch")
    samples = value.get("samples")
    count = value.get("sample_count")
    if type(samples) is not list or type(count) is not int or count != len(samples) or count < MIN_CALIBRATION_SAMPLES:
        blockers.append(f"branch:{branch}:{label}_policy_calibration_below_{MIN_CALIBRATION_SAMPLES}")
        return blockers
    sample_ids: list[str] = []
    for sample in samples:
        if type(sample) is not dict or set(sample) != {"sample_id", "service_time_ms"}:
            blockers.append(f"branch:{branch}:{label}_policy_calibration_sample_invalid")
            continue
        duration = sample.get("service_time_ms")
        if type(sample.get("sample_id")) is not str or type(duration) not in {int, float} or isinstance(duration, bool) or not math.isfinite(float(duration)) or float(duration) <= 0:
            blockers.append(f"branch:{branch}:{label}_policy_calibration_sample_invalid")
            continue
        sample_ids.append(sample["sample_id"])
    if corpus is None or sample_ids != [sample["sample_id"] for sample in corpus]:
        blockers.append(f"branch:{branch}:{label}_policy_calibration_sample_order_mismatch")
    return list(dict.fromkeys(blockers))


def _raw_bundle_blockers_v2(
    branch: str,
    slot: Mapping[str, Any],
    source: Mapping[str, Any],
    value: dict[str, Any] | None,
    *,
    resource: str,
    corpus: list[dict[str, str]] | None,
    corpus_sha: str | None,
    execution_probe_sha: str | None,
    preprocessing_sha: str,
    output_sha: str,
    worker_runtimes: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, Any]] | None]:
    if value is None:
        return [], None
    label = "cpu" if resource == "openvino_cpu" else "cuda"
    expected = {
        "schema_version", "artifact_kind", "branch", "workload_slot_id", "resource",
        "source_sha256", "model_sha256", "weights_sha256", "engine_sha256",
        "runtime_image_id", "execution_probe_sha256", "corpus_manifest_sha256",
        "preprocessing_contract_sha256", "output_contract_sha256", "tensor_name",
        "dtype", "sample_shape", "sample_count", "samples",
    }
    if set(value) != expected or value.get("schema_version") != 2 or value.get("artifact_kind") != "checkpoint_model_raw_output_bundle" or value.get("branch") != branch or value.get("workload_slot_id") != slot["slot_id"] or value.get("resource") != resource:
        return [f"branch:{branch}:{label}_raw_output_bundle_schema_invalid"], None
    blockers: list[str] = []
    ov = slot["openvino_ir"]
    trt = slot["tensorrt_engine"]
    worker_runtime = worker_runtimes[resource]
    if resource == "openvino_cpu":
        artifacts_match = value.get("model_sha256") == ov["model"]["sha256"] and value.get("weights_sha256") == ov["weights"]["sha256"] and value.get("engine_sha256") is None
    else:
        artifacts_match = value.get("model_sha256") is None and value.get("weights_sha256") is None and value.get("engine_sha256") == trt["artifact"]["sha256"]
    if not artifacts_match:
        blockers.append(f"branch:{branch}:{label}_raw_output_bundle_artifact_mismatch")
    bindings_match = value.get("source_sha256") == source["sha256"] and value.get("runtime_image_id") == worker_runtime["image_id"] and value.get("execution_probe_sha256") == execution_probe_sha and value.get("corpus_manifest_sha256") == corpus_sha and value.get("preprocessing_contract_sha256") == preprocessing_sha and value.get("output_contract_sha256") == output_sha
    if not bindings_match:
        blockers.append(f"branch:{branch}:{label}_raw_output_bundle_binding_mismatch")
    output = source["output"]
    if value.get("tensor_name") != output["name"] or value.get("dtype") != "float32" or value.get("sample_shape") != [1, 1000]:
        blockers.append(f"branch:{branch}:{label}_raw_output_bundle_tensor_contract_mismatch")
    samples = value.get("samples")
    count = value.get("sample_count")
    if type(samples) is not list or type(count) is not int or count != len(samples) or count < MIN_PARITY_SAMPLES:
        blockers.append(f"branch:{branch}:{label}_raw_output_bundle_below_{MIN_PARITY_SAMPLES}")
        return blockers, None
    normalized: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if type(sample) is not dict or set(sample) != {"sample_id", "input_sha256", "preprocessed_tensor_sha256", "values"}:
            blockers.append(f"branch:{branch}:{label}_raw_output_sample_invalid")
            continue
        values = sample.get("values")
        if type(values) is not list or len(values) != 1000:
            blockers.append(f"branch:{branch}:{label}_raw_output_shape_invalid")
            continue
        numbers: list[float] = []
        finite = True
        for number in values:
            if type(number) not in {int, float} or isinstance(number, bool):
                finite = False
                break
            try:
                converted = float(number)
                fp32 = struct.unpack("<f", struct.pack("<f", converted))[0]
            except (OverflowError, ValueError, struct.error):
                finite = False
                break
            if not math.isfinite(converted) or not math.isfinite(fp32):
                finite = False
                break
            numbers.append(fp32)
        if not finite:
            blockers.append(f"branch:{branch}:{label}_raw_output_non_finite_or_non_numeric")
            continue
        corpus_sample = corpus[index] if corpus is not None and index < len(corpus) else None
        expected_sample = (
            {key: corpus_sample[key] for key in ("sample_id", "input_sha256", "preprocessed_tensor_sha256")}
            if corpus_sample is not None
            else None
        )
        metadata = {key: sample.get(key) for key in ("sample_id", "input_sha256", "preprocessed_tensor_sha256")}
        if expected_sample is None or metadata != expected_sample:
            blockers.append(f"branch:{branch}:{label}_raw_output_sample_order_or_hash_mismatch")
            continue
        normalized.append({"sample_id": sample["sample_id"], "values": numbers})
    if corpus is None or len(samples) != len(corpus) or len(normalized) != len(samples):
        blockers.append(f"branch:{branch}:{label}_raw_output_sample_order_or_hash_mismatch")
    blockers = list(dict.fromkeys(blockers))
    return blockers, normalized if not blockers else None


def _recompute_classification_parity_v2(
    branch: str,
    cpu_samples: list[dict[str, Any]],
    cuda_samples: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    per_sample: list[dict[str, Any]] = []
    all_abs: list[float] = []
    max_rel = 0.0
    max_cosine = 0.0
    mismatches = 0
    for cpu, cuda in zip(cpu_samples, cuda_samples):
        _require(cpu["sample_id"] == cuda["sample_id"], f"{branch}: internal sample alignment failure")
        left = cpu["values"]
        right = cuda["values"]
        absolute = [abs(a - b) for a, b in zip(left, right)]
        relative = [difference / max(abs(a), abs(b), RELATIVE_ERROR_FLOOR) for a, b, difference in zip(left, right, absolute)]
        norm_left = math.sqrt(math.fsum(item * item for item in left))
        norm_right = math.sqrt(math.fsum(item * item for item in right))
        if norm_left == 0.0 and norm_right == 0.0:
            cosine_distance = 0.0
        elif norm_left == 0.0 or norm_right == 0.0:
            cosine_distance = 1.0
        else:
            similarity = math.fsum(a * b for a, b in zip(left, right)) / (norm_left * norm_right)
            cosine_distance = max(0.0, min(2.0, 1.0 - similarity))
        cpu_top1 = max(range(len(left)), key=left.__getitem__)
        cuda_top1 = max(range(len(right)), key=right.__getitem__)
        top1_match = cpu_top1 == cuda_top1
        if not top1_match:
            mismatches += 1
        sample_max_abs = max(absolute)
        sample_max_rel = max(relative)
        sample_mean_abs = math.fsum(absolute) / len(absolute)
        all_abs.extend(absolute)
        max_rel = max(max_rel, sample_max_rel)
        max_cosine = max(max_cosine, cosine_distance)
        per_sample.append(
            {
                "sample_id": cpu["sample_id"],
                "raw_max_abs_error": sample_max_abs,
                "raw_max_rel_error": sample_max_rel,
                "raw_mean_abs_error": sample_mean_abs,
                "cosine_distance": cosine_distance,
                "cpu_top1": cpu_top1,
                "cuda_top1": cuda_top1,
                "top1_match": top1_match,
            }
        )
    aggregates = {
        "raw_max_abs_error": max(all_abs),
        "raw_max_rel_error": max_rel,
        "raw_mean_abs_error": math.fsum(all_abs) / len(all_abs),
        "raw_max_cosine_distance": max_cosine,
        "top1_mismatch_rate": mismatches / len(per_sample),
    }
    blockers = [
        f"branch:{branch}:numeric_parity_tolerance_exceeded:{metric}"
        for metric, limit in PARITY_TOLERANCES.items()
        if aggregates[metric] > limit
    ]
    return {
        "schema_version": 2,
        "artifact_kind": "checkpoint_model_recomputed_numeric_parity",
        "sample_count": len(per_sample),
        "output_values_compared": len(all_abs),
        "relative_error_floor": RELATIVE_ERROR_FLOOR,
        "per_sample": per_sample,
        "aggregates": aggregates,
        "tolerances": dict(PARITY_TOLERANCES),
        "passed": not blockers,
    }, blockers


def _assess_slot_v2(
    branch: str,
    manifest: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    blockers: list[str] = []
    prefix = f"branch:{branch}"
    slot = manifest["workload_slots"][branch]
    source = manifest["source_registry"][slot["source_ref"]]
    ov = slot["openvino_ir"]
    trt = slot["tensorrt_engine"]
    source_ref = {"path": source["path"], "sha256": source["sha256"], "size_bytes": source["size_bytes"]}
    states: dict[str, Any] = {
        "canonical_source": _artifact_state(root, source_ref, missing_blocker=f"{prefix}:canonical_source_artifact_missing", digest_blocker_prefix=f"{prefix}:canonical_source", blockers=blockers),
        "openvino_model": _artifact_state(root, ov["model"], missing_blocker=f"{prefix}:openvino_model_artifact_missing", digest_blocker_prefix=f"{prefix}:openvino_model", blockers=blockers),
        "openvino_weights": _artifact_state(root, ov["weights"], missing_blocker=f"{prefix}:openvino_weights_artifact_missing", digest_blocker_prefix=f"{prefix}:openvino_weights", blockers=blockers),
        "tensorrt_engine": _artifact_state(root, trt["artifact"], missing_blocker=f"{prefix}:tensorrt_engine_artifact_missing", digest_blocker_prefix=f"{prefix}:tensorrt_engine", blockers=blockers),
    }
    preprocessing_sha = _sha256_bytes(_canonical_json(manifest["preprocessing_contract"]))
    output_contract = {"classification_contract": manifest["classification_contract"], "source_output": source["output"]}
    output_sha = _sha256_bytes(_canonical_json(output_contract))
    evidence_states: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, Any] | None] = {}
    for name in EVIDENCE_NAMES:
        reference = slot["evidence"][name]
        state = _artifact_state(root, reference, missing_blocker=f"{prefix}:{name}_evidence_missing", digest_blocker_prefix=f"{prefix}:{name}_evidence", blockers=blockers)
        evidence_states[name] = state
        documents[name] = _load_verified_json(root, reference, state, invalid_blocker=f"{prefix}:{name}_evidence_invalid", blockers=blockers)
    states["evidence"] = evidence_states
    toolchains = manifest["toolchain_registry"]
    worker_runtimes = manifest["worker_runtime_registry"]
    blockers.extend(_execution_probe_blockers_v3(branch, slot, source, documents["cpu_execution_probe"], resource="openvino_cpu", preprocessing_sha=preprocessing_sha, output_sha=output_sha, toolchains=toolchains, worker_runtimes=worker_runtimes))
    blockers.extend(_execution_probe_blockers_v3(branch, slot, source, documents["cuda_execution_probe"], resource="tensorrt_cuda", preprocessing_sha=preprocessing_sha, output_sha=output_sha, toolchains=toolchains, worker_runtimes=worker_runtimes))
    calibration_blockers, calibration_corpus, calibration_states = _corpus_blockers_v2(branch, slot["slot_id"], documents["calibration_corpus"], role="calibration", minimum=MIN_CALIBRATION_SAMPLES, root=root, preprocessing_sha=preprocessing_sha)
    evaluation_blockers, evaluation_corpus, evaluation_states = _corpus_blockers_v2(branch, slot["slot_id"], documents["evaluation_corpus"], role="evaluation", minimum=MIN_PARITY_SAMPLES, root=root, preprocessing_sha=preprocessing_sha)
    states["corpus_materialization"] = {"calibration": calibration_states, "evaluation": evaluation_states}
    blockers.extend(calibration_blockers)
    blockers.extend(evaluation_blockers)
    if calibration_corpus is not None and evaluation_corpus is not None and not {sample["physical_sample_sha256"] for sample in calibration_corpus}.isdisjoint(sample["physical_sample_sha256"] for sample in evaluation_corpus):
        blockers.append(f"{prefix}:calibration_and_evaluation_corpora_not_disjoint")
    evidence = slot["evidence"]
    blockers.extend(_policy_calibration_blockers_v2(branch, slot, source, documents["cpu_policy_calibration"], resource="openvino_cpu", corpus=calibration_corpus, corpus_sha=evidence["calibration_corpus"]["sha256"], execution_probe_sha=evidence["cpu_execution_probe"]["sha256"], worker_runtimes=worker_runtimes))
    blockers.extend(_policy_calibration_blockers_v2(branch, slot, source, documents["cuda_policy_calibration"], resource="tensorrt_cuda", corpus=calibration_corpus, corpus_sha=evidence["calibration_corpus"]["sha256"], execution_probe_sha=evidence["cuda_execution_probe"]["sha256"], worker_runtimes=worker_runtimes))
    cpu_blockers, cpu_outputs = _raw_bundle_blockers_v2(branch, slot, source, documents["cpu_raw_output_bundle"], resource="openvino_cpu", corpus=evaluation_corpus, corpus_sha=evidence["evaluation_corpus"]["sha256"], execution_probe_sha=evidence["cpu_execution_probe"]["sha256"], preprocessing_sha=preprocessing_sha, output_sha=output_sha, worker_runtimes=worker_runtimes)
    cuda_blockers, cuda_outputs = _raw_bundle_blockers_v2(branch, slot, source, documents["cuda_raw_output_bundle"], resource="tensorrt_cuda", corpus=evaluation_corpus, corpus_sha=evidence["evaluation_corpus"]["sha256"], execution_probe_sha=evidence["cuda_execution_probe"]["sha256"], preprocessing_sha=preprocessing_sha, output_sha=output_sha, worker_runtimes=worker_runtimes)
    blockers.extend(cpu_blockers)
    blockers.extend(cuda_blockers)
    recomputed_parity = None
    if cpu_outputs is not None and cuda_outputs is not None:
        recomputed_parity, parity_blockers = _recompute_classification_parity_v2(branch, cpu_outputs, cuda_outputs)
        blockers.extend(parity_blockers)
    blockers = list(dict.fromkeys(blockers))
    return {
        "ready": not blockers,
        "workload_slot_id": slot["slot_id"],
        "source_ref": slot["source_ref"],
        "source_identity_sha256": source["sha256"],
        "semantic_claim": slot["semantic_claim"],
        "preprocessing_contract_sha256": preprocessing_sha,
        "output_contract_sha256": output_sha,
        "artifacts": states,
        "non_blocking_parser_facts": trt["parser_facts"],
        "recomputed_parity": recomputed_parity,
        "blockers": blockers,
    }


def _model_inventory(root: Path) -> dict[str, int]:
    counts = {extension: 0 for extension in (".onnx", ".xml", ".bin", ".engine", ".plan")}
    model_root = root / "models"
    if not model_root.is_dir():
        return counts
    for path in model_root.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in counts:
            counts[path.suffix.lower()] += 1
    return counts


def assess_model_parity(
    manifest_path: Path | str = DEFAULT_MANIFEST,
    *,
    project_root: Path | str = PROJECT_ROOT,
    command_runner: CommandRunner = _default_command_runner,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    manifest = load_parity_manifest(manifest_path)
    matrix = manifest["matrix_binding"]
    global_blockers: list[str] = []
    images: dict[str, Any] = {}
    for resource in ("cpu", "gpu"):
        image = str(matrix[resource]["image"])
        record = _inspect_image(image, command_runner)
        images[resource] = record or {"reference": image, "available": False}
        if record is None:
            global_blockers.append(f"runtime_image_missing:{resource}")
        elif record["image_id"] != matrix[resource]["image_id"]:
            global_blockers.append(f"runtime_image_id_mismatch:{resource}")
    branches = {
        branch: _assess_slot_v2(
            branch,
            manifest,
            root=root,
        )
        for branch in BRANCHES
    }
    blockers = list(global_blockers)
    for branch in BRANCHES:
        blockers.extend(branches[branch]["blockers"])
    result = {
        "schema_version": 3,
        "artifact_kind": "checkpoint_analytics_model_parity_assessment",
        "manifest_identity_sha256": manifest["identity"]["sha256"],
        "claim_scope": manifest["claim_scope"],
        "semantic_claim": manifest["semantic_claim"],
        "publication_ready": not blockers,
        "openvino_gpu_counted_as_nvidia_cuda": False,
        "network_or_download_performed": False,
        "permitted_external_command": "docker image inspect only",
        "claimed_aggregate_metrics_accepted": False,
        "raw_per_sample_outputs_recomputed": all(branches[branch]["recomputed_parity"] is not None for branch in BRANCHES),
        "runtime_images": images,
        "local_model_inventory": _model_inventory(root),
        "branches": branches,
        "blockers": list(dict.fromkeys(blockers)),
    }
    return _with_identity(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Canonicalize or assess the frozen CPU OpenVINO/NVIDIA TensorRT model parity contract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--config", type=Path, default=DEFAULT_MANIFEST)
    assess = subparsers.add_parser("assess")
    assess.add_argument("--config", type=Path, default=DEFAULT_MANIFEST)
    assess.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            result = load_parity_manifest(args.config)
            exit_code = 0
        else:
            result = assess_model_parity(
                args.config,
                project_root=args.project_root,
            )
            exit_code = 0 if result["publication_ready"] else 78
    except ContractError as error:
        result = {
            "schema_version": 3,
            "artifact_kind": "checkpoint_analytics_model_parity_error",
            "status": "contract_error",
            "message": str(error),
        }
        exit_code = 78
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND",
    "BRANCHES",
    "EVIDENCE_NAMES",
    "MAX_EVIDENCE_JSON_BYTES",
    "MIN_CALIBRATION_SAMPLES",
    "MIN_PARITY_SAMPLES",
    "PARITY_TOLERANCES",
    "RELATIVE_ERROR_FLOOR",
    "SCHEMA_VERSION",
    "SLOT_BINDINGS",
    "assess_model_parity",
    "build_image_inspect_command",
    "build_parser",
    "load_parity_manifest",
    "main",
    "validate_manifest_identity",
]
