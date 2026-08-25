#!/usr/bin/env python3
"""Fail-closed GStreamer buffer router for frozen analytics workers.

The bridge does not implement inference. It binds one policy decision to one
of the eight existing analytics worker sockets, forwards a real tensor through
the sealed-memfd protocol, validates the worker response, and only then emits
terminal provenance suitable for the native GStreamer policy client.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import socket
import stat
import threading
from collections.abc import Mapping
from typing import Any

from analytics_execution_protocol import (
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    ProtocolError,
    canonical_sha256,
    close_fds,
    receive_packet,
    send_packet,
    validate_frame_identity,
    verify_sealed_memfd,
)
from analytics_execution_worker import ExecutionClient, validate_worker_capability


BRIDGE_SCHEMA_VERSION = 1
BRIDGE_MESSAGE_TYPE = "analytics_execute"
BRIDGE_RESPONSE_TYPE = "analytics_execute_response"
RESOURCES = ("cpu", "gpu")
RESOURCE_ENGINE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,512}$")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    return value


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    result = _mapping(value, label)
    _require(set(result) == fields, f"{label} fields have drifted")
    return result


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _visible(value: Any, label: str, *, maximum: int = 1024) -> str:
    result = str(value or "")
    _require(0 < len(result) <= maximum, f"{label} length is invalid")
    _require(
        all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result),
        f"{label} contains controls",
    )
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    return int(value)


def _worker_key(branch: str, resource: str) -> tuple[str, str]:
    _require(branch in BRANCHES, "GStreamer analytics bridge branch is invalid")
    _require(resource in RESOURCES, "GStreamer analytics bridge resource is invalid")
    return branch, resource


def _unix_socket_path(value: os.PathLike[str] | str) -> str:
    raw = os.fspath(value)
    _require(type(raw) is str and raw.startswith("/"), "bridge socket path must be absolute")
    _require("\x00" not in raw and len(os.fsencode(raw)) < 108, "bridge socket path is invalid")
    parent = os.path.dirname(raw)
    _require(parent and os.path.isdir(parent), "bridge socket parent is missing")
    parent_stat = os.lstat(parent)
    _require(not stat.S_ISLNK(parent_stat.st_mode), "bridge socket parent is a symlink")
    _require(os.path.realpath(parent) == parent, "bridge socket parent is an alias")
    _require(not os.path.lexists(raw), "bridge socket path already exists")
    return raw


def open_bridge_listener(path: os.PathLike[str] | str, *, backlog: int = 1) -> socket.socket:
    """Create a fail-closed pathname ``SOCK_SEQPACKET`` listener.

    The caller owns both the returned socket and eventual removal of the socket
    node.  Existing filesystem entries are never unlinked or replaced.
    """

    _require(type(backlog) is int and 1 <= backlog <= 128, "bridge socket backlog is invalid")
    resolved = _unix_socket_path(path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        listener.bind(resolved)
        listener.listen(backlog)
        mode = os.lstat(resolved).st_mode
        _require(stat.S_ISSOCK(mode), "bridge listener did not create a socket node")
        return listener
    except BaseException:
        listener.close()
        raise


def _policy_binding(manifest: Mapping[str, Any], branch: str, resource: str) -> dict[str, Any]:
    try:
        value = manifest["systems"]["gstreamer_custom"]["branches"][branch][resource]
    except (KeyError, TypeError) as error:
        raise ProtocolError(
            f"GStreamer analytics bridge policy binding is missing: {branch}/{resource}"
        ) from error
    binding = _mapping(value, f"GStreamer analytics bridge policy binding {branch}/{resource}")
    native = _mapping(binding.get("native_evidence"), "GStreamer analytics bridge native evidence")
    result = {
        "implementation_id": _stable(binding.get("implementation_id"), "policy implementation_id"),
        "emitter_id": _stable(native.get("emitter_id"), "policy emitter_id"),
        "emitter_sha256": _sha(native.get("emitter_sha256"), "policy emitter_sha256"),
        "terminal_detector": _visible(binding.get("terminal_detector"), "policy terminal_detector"),
        "terminal_backend": _visible(binding.get("terminal_backend"), "policy terminal_backend"),
    }
    if resource == "cpu":
        _require(
            result["terminal_backend"].endswith(";device=CPU"),
            "CPU policy terminal backend is not CPU",
        )
    else:
        _require(
            result["terminal_backend"].endswith(";device=NVIDIA_CUDA:0")
            and not result["terminal_backend"].startswith("openvino"),
            "GPU policy terminal backend is not NVIDIA CUDA",
        )
    return result


def _validate_worker_binding(
    value: Mapping[str, Any],
    capability: Mapping[str, Any],
    *,
    branch: str,
    resource: str,
) -> dict[str, Any]:
    binding = dict(_mapping(value, f"analytics worker binding {branch}/{resource}"))
    expected = {
        "worker_id": capability["worker_id"],
        "branch": branch,
        "model_id": capability["model_id"],
        "source_model_sha256": capability["source_model_sha256"],
        "model_artifact_sha256": capability["model_artifact_sha256"],
        "runtime_weights_sha256": capability["runtime_weights_sha256"],
        "preprocessing_contract_sha256": capability["preprocessing_contract_sha256"],
        "output_contract_sha256": capability["output_contract_sha256"],
    }
    for field, expected_value in expected.items():
        _require(binding.get(field) == expected_value, f"analytics worker binding {field} mismatch")
    input_contract = _exact(
        binding.get("input"),
        {"name", "dtype", "layout", "shape"},
        f"analytics worker input binding {branch}/{resource}",
    )
    _require(
        type(input_contract["shape"]) is list
        and input_contract["shape"]
        and all(type(value) is int and value > 0 for value in input_contract["shape"]),
        "analytics worker input shape is invalid",
    )
    binding["input"] = dict(input_contract)
    return binding


def _validate_tensor_payload(value: Any, binding: Mapping[str, Any]) -> dict[str, Any]:
    tensor = _exact(
        value,
        {
            "kind", "name", "dtype", "layout", "shape", "byte_length",
            "sha256", "preprocessing_contract_sha256",
        },
        "GStreamer analytics bridge tensor payload",
    )
    _require(tensor["kind"] == "preprocessed_tensor", "bridge payload is not a tensor")
    input_contract = binding["input"]
    for field in ("name", "dtype", "layout", "shape"):
        _require(tensor[field] == input_contract[field], f"bridge tensor {field} differs from worker binding")
    byte_length = _integer(tensor["byte_length"], "bridge tensor byte_length", minimum=1)
    _sha(tensor["sha256"], "bridge tensor sha256")
    _require(
        tensor["preprocessing_contract_sha256"] == binding["preprocessing_contract_sha256"],
        "bridge tensor preprocessing contract mismatch",
    )
    result = dict(tensor)
    result["byte_length"] = byte_length
    return result


def _validate_raw_frame_payload(value: Any, binding: Mapping[str, Any]) -> dict[str, Any]:
    frame = _exact(
        value,
        {
            "kind", "format", "width", "height", "stride", "byte_length",
            "sha256", "preprocessing_contract_sha256",
        },
        "GStreamer analytics bridge raw frame payload",
    )
    _require(frame["kind"] == "raw_gstreamer_frame", "bridge payload is not a raw frame")
    pixel_format = str(frame["format"])
    _require(pixel_format in {"RGB", "BGR"}, "bridge raw frame format is unsupported")
    width = _integer(frame["width"], "bridge raw frame width", minimum=1)
    height = _integer(frame["height"], "bridge raw frame height", minimum=1)
    stride = _integer(frame["stride"], "bridge raw frame stride", minimum=width * 3)
    byte_length = _integer(frame["byte_length"], "bridge raw frame byte_length", minimum=1)
    _require(byte_length == height * stride, "bridge raw frame byte length/stride mismatch")
    _sha(frame["sha256"], "bridge raw frame sha256")
    _require(
        frame["preprocessing_contract_sha256"] == binding["preprocessing_contract_sha256"],
        "bridge raw frame preprocessing contract mismatch",
    )
    return {
        **dict(frame),
        "format": pixel_format,
        "width": width,
        "height": height,
        "stride": stride,
        "byte_length": byte_length,
    }


def preprocess_gstreamer_frame(
    payload: bytes | bytearray | memoryview,
    *,
    frame: Mapping[str, Any],
    preprocessing_contract: Mapping[str, Any],
    expected_contract_sha256: str,
    tensor_name: str,
) -> tuple[bytes, dict[str, Any]]:
    """Apply the frozen ImageNet resize/crop/normalization to a packed GstBuffer."""

    import numpy as np

    contract = dict(_mapping(preprocessing_contract, "GStreamer preprocessing contract"))
    _require(
        canonical_sha256(contract) == _sha(expected_contract_sha256, "preprocessing contract sha256"),
        "GStreamer preprocessing contract SHA-256 mismatch",
    )
    required = {
        "decoded_color_order": "RGB",
        "tensor_color_order": "RGB",
        "decode_dtype": "uint8",
        "resize_shorter_side": 256,
        "resize_long_side_formula": "floor(long_side*256/short_side+0.5)",
        "resize_algorithm": "bilinear",
        "resize_coordinate_transform": "half_pixel",
        "half_pixel_coordinate_formula": "src=(dst+0.5)*src_size/dst_size-0.5",
        "border_mode": "edge_clamp",
        "interpolation_accumulator_dtype": "float32",
        "interpolation_output_dtype": "float32",
        "interpolation_rounding": "none",
        "resize_rounding": "round_half_up",
        "center_crop": [224, 224],
        "normalization_evaluation_order": (
            "float32((float32(pixel)*scale-mean[channel])/std[channel])"
        ),
        "normalization_accumulator_dtype": "float32",
        "channel_transform": "HWC_RGB_to_CHW_RGB",
        "output_dtype": "float32",
        "output_layout": "NCHW",
        "execution_shape": [1, 3, 224, 224],
        "tensor_serialization": "raw_f32_le_c_contiguous_v1",
        "tensor_header": "none",
        "tensor_endianness": "little",
        "tensor_memory_order": "C",
    }
    for field, expected in required.items():
        _require(contract.get(field) == expected, f"GStreamer preprocessing {field} drifted")
    scale = contract.get("normalization_scale")
    mean = contract.get("normalization_mean")
    std = contract.get("normalization_std")
    _require(type(scale) in {int, float} and math.isfinite(float(scale)), "normalization scale is invalid")
    _require(
        type(mean) is list
        and type(std) is list
        and len(mean) == len(std) == 3
        and all(type(value) in {int, float} and math.isfinite(float(value)) for value in (*mean, *std))
        and all(float(value) > 0.0 for value in std),
        "normalization vectors are invalid",
    )
    raw_frame = _exact(
        frame,
        {"format", "width", "height", "stride"},
        "GStreamer raw frame descriptor",
    )
    pixel_format = str(raw_frame["format"])
    _require(pixel_format in {"RGB", "BGR"}, "GStreamer raw frame format is unsupported")
    width = _integer(raw_frame["width"], "GStreamer raw frame width", minimum=1)
    height = _integer(raw_frame["height"], "GStreamer raw frame height", minimum=1)
    stride = _integer(raw_frame["stride"], "GStreamer raw frame stride", minimum=width * 3)
    source_bytes = bytes(payload)
    _require(len(source_bytes) == height * stride, "GStreamer raw frame byte length/stride mismatch")
    rows = np.frombuffer(source_bytes, dtype=np.uint8).reshape(height, stride)
    image = rows[:, : width * 3].reshape(height, width, 3)
    if pixel_format == "BGR":
        image = image[:, :, ::-1]
    source = image.astype(np.float32, copy=False)

    shorter = min(height, width)
    longer = max(height, width)
    resized_long = math.floor(longer * 256 / shorter + 0.5)
    if height <= width:
        resized_height, resized_width = 256, resized_long
    else:
        resized_height, resized_width = resized_long, 256
    f32 = np.float32
    y = (np.arange(resized_height, dtype=np.float32) + f32(0.5)) * f32(
        height / resized_height
    ) - f32(0.5)
    x = (np.arange(resized_width, dtype=np.float32) + f32(0.5)) * f32(
        width / resized_width
    ) - f32(0.5)
    y0_raw = np.floor(y).astype(np.int64)
    x0_raw = np.floor(x).astype(np.int64)
    y1_raw = y0_raw + 1
    x1_raw = x0_raw + 1
    wy = (y - y0_raw.astype(np.float32)).reshape(-1, 1, 1)
    wx = (x - x0_raw.astype(np.float32)).reshape(1, -1, 1)
    y0 = np.clip(y0_raw, 0, height - 1)
    y1 = np.clip(y1_raw, 0, height - 1)
    x0 = np.clip(x0_raw, 0, width - 1)
    x1 = np.clip(x1_raw, 0, width - 1)
    one = f32(1.0)
    top = np.add(
        np.multiply(source[y0[:, None], x0[None, :], :], one - wx, dtype=np.float32),
        np.multiply(source[y0[:, None], x1[None, :], :], wx, dtype=np.float32),
        dtype=np.float32,
    )
    bottom = np.add(
        np.multiply(source[y1[:, None], x0[None, :], :], one - wx, dtype=np.float32),
        np.multiply(source[y1[:, None], x1[None, :], :], wx, dtype=np.float32),
        dtype=np.float32,
    )
    resized = np.add(
        np.multiply(top, one - wy, dtype=np.float32),
        np.multiply(bottom, wy, dtype=np.float32),
        dtype=np.float32,
    )
    top_offset = (resized_height - 224) // 2
    left_offset = (resized_width - 224) // 2
    crop = resized[top_offset : top_offset + 224, left_offset : left_offset + 224, :]
    _require(crop.shape == (224, 224, 3), "GStreamer preprocessing center crop is incomplete")
    normalized = np.multiply(crop, f32(scale), dtype=np.float32)
    normalized = np.subtract(normalized, np.asarray(mean, dtype=np.float32), dtype=np.float32)
    normalized = np.divide(normalized, np.asarray(std, dtype=np.float32), dtype=np.float32)
    tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...], dtype="<f4")
    tensor_bytes = tensor.tobytes(order="C")
    descriptor = {
        "name": _stable(tensor_name, "GStreamer analytics tensor name"),
        "dtype": "float32",
        "layout": "NCHW",
        "shape": [1, 3, 224, 224],
        "byte_length": len(tensor_bytes),
        "sha256": hashlib.sha256(tensor_bytes).hexdigest(),
        "preprocessing_contract_sha256": expected_contract_sha256,
    }
    return tensor_bytes, descriptor


def _validate_request(value: Any) -> dict[str, Any]:
    request = _exact(
        value,
        {
            "schema_version", "message_type", "request_id", "run_id", "arm_id",
            "gstreamer_worker_id", "frame", "decision", "deadline_monotonic_ns", "payload",
        },
        "GStreamer analytics bridge request",
    )
    _require(request["schema_version"] == BRIDGE_SCHEMA_VERSION, "bridge schema_version is invalid")
    _require(request["message_type"] == BRIDGE_MESSAGE_TYPE, "bridge message_type is invalid")
    decision = _exact(
        request["decision"],
        {
            "decision_id", "decision_seq", "selected_resource",
            "selected_implementation_id", "emitter_id", "emitter_sha256",
        },
        "GStreamer analytics bridge decision",
    )
    resource = str(decision["selected_resource"])
    _require(resource in RESOURCES, "bridge decision selected_resource is invalid")
    return {
        **dict(request),
        "request_id": _stable(request["request_id"], "bridge request_id"),
        "run_id": _stable(request["run_id"], "bridge run_id"),
        "arm_id": _stable(request["arm_id"], "bridge arm_id"),
        "gstreamer_worker_id": _stable(
            request["gstreamer_worker_id"], "bridge gstreamer_worker_id"
        ),
        "frame": validate_frame_identity(request["frame"]),
        "decision": {
            "decision_id": _stable(decision["decision_id"], "bridge decision_id"),
            "decision_seq": _integer(decision["decision_seq"], "bridge decision_seq", minimum=1),
            "selected_resource": resource,
            "selected_implementation_id": _stable(
                decision["selected_implementation_id"], "bridge selected implementation"
            ),
            "emitter_id": _stable(decision["emitter_id"], "bridge emitter_id"),
            "emitter_sha256": _sha(decision["emitter_sha256"], "bridge emitter_sha256"),
        },
        "deadline_monotonic_ns": _integer(
            request["deadline_monotonic_ns"], "bridge deadline_monotonic_ns", minimum=1
        ),
    }


class AnalyticsExecutionBridge:
    """Route GStreamer tensors to eight frozen, already-connected workers."""

    def __init__(
        self,
        *,
        policy_capability_manifest: Mapping[str, Any],
        worker_connections: Mapping[tuple[str, str], socket.socket],
        worker_capabilities: Mapping[tuple[str, str], Mapping[str, Any]],
        worker_bindings: Mapping[tuple[str, str], Mapping[str, Any]],
        preprocessing_contract: Mapping[str, Any] | None = None,
    ) -> None:
        from analytics_execution_endpoint import execution_endpoint_from_socket

        expected_keys = {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
        _require(set(worker_connections) == expected_keys, "bridge worker connections must cover exact 8 bindings")
        _require(set(worker_capabilities) == expected_keys, "bridge worker capabilities must cover exact 8 bindings")
        _require(set(worker_bindings) == expected_keys, "bridge worker bindings must cover exact 8 bindings")
        self._policy_manifest = policy_capability_manifest
        self._sockets: dict[tuple[str, str], socket.socket] = {}
        self._clients: dict[tuple[str, str], ExecutionClient] = {}
        self._capabilities: dict[tuple[str, str], dict[str, Any]] = {}
        self._bindings: dict[tuple[str, str], dict[str, Any]] = {}
        self._locks = {key: threading.Lock() for key in expected_keys}
        self._preprocessing_contract = (
            None
            if preprocessing_contract is None
            else dict(_mapping(preprocessing_contract, "GStreamer preprocessing contract"))
        )
        try:
            for branch in BRANCHES:
                for resource in RESOURCES:
                    key = (branch, resource)
                    capability = validate_worker_capability(worker_capabilities[key])
                    _require(capability["branch"] == branch, "bridge worker capability branch mismatch")
                    _require(
                        capability["engine"] == RESOURCE_ENGINE[resource],
                        "bridge worker capability resource/engine mismatch",
                    )
                    _policy_binding(self._policy_manifest, branch, resource)
                    binding = _validate_worker_binding(
                        worker_bindings[key], capability, branch=branch, resource=resource
                    )
                    endpoint = execution_endpoint_from_socket(
                        worker_connections[key],
                        resource=resource,
                        expected_capability=capability,
                    )
                    observed = endpoint.client.handshake()
                    _require(observed == capability, "bridge worker hello capability mismatch")
                    self._sockets[key] = worker_connections[key]
                    self._clients[key] = endpoint.client
                    self._capabilities[key] = capability
                    self._bindings[key] = binding
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        sockets = getattr(self, "_sockets", {})
        for endpoint in sockets.values():
            try:
                endpoint.close()
            except OSError:
                pass
        sockets.clear()

    def execute(self, value: Mapping[str, Any], payload: bytes | bytearray | memoryview) -> dict[str, Any]:
        request = _validate_request(value)
        branch = request["frame"]["branch"]
        resource = request["decision"]["selected_resource"]
        key = _worker_key(branch, resource)
        policy = _policy_binding(self._policy_manifest, branch, resource)
        decision = request["decision"]
        for field, expected in (
            ("selected_implementation_id", policy["implementation_id"]),
            ("emitter_id", policy["emitter_id"]),
            ("emitter_sha256", policy["emitter_sha256"]),
        ):
            _require(decision[field] == expected, f"bridge decision {field} mismatch")

        binding = self._bindings[key]
        raw_payload = bytes(payload)
        raw_sha = hashlib.sha256(raw_payload).hexdigest()
        payload_record = _mapping(request["payload"], "GStreamer analytics bridge payload")
        if payload_record.get("kind") == "preprocessed_tensor":
            tensor = _validate_tensor_payload(payload_record, binding)
            inference_payload = raw_payload
        elif payload_record.get("kind") == "raw_gstreamer_frame":
            frame_payload = _validate_raw_frame_payload(payload_record, binding)
            _require(
                self._preprocessing_contract is not None,
                "bridge raw frame requires a frozen preprocessing contract",
            )
            inference_payload, tensor_descriptor = preprocess_gstreamer_frame(
                raw_payload,
                frame={
                    "format": frame_payload["format"],
                    "width": frame_payload["width"],
                    "height": frame_payload["height"],
                    "stride": frame_payload["stride"],
                },
                preprocessing_contract=self._preprocessing_contract,
                expected_contract_sha256=frame_payload["preprocessing_contract_sha256"],
                tensor_name=binding["input"]["name"],
            )
            tensor = _validate_tensor_payload(
                {"kind": "preprocessed_tensor", **tensor_descriptor}, binding
            )
        else:
            raise ProtocolError("GStreamer analytics bridge payload kind is invalid")
        _require(len(raw_payload) == payload_record["byte_length"], "bridge payload byte length mismatch")
        _require(raw_sha == payload_record["sha256"], "bridge payload SHA-256 mismatch")
        capability = self._capabilities[key]
        inference_request = {
            "schema_version": 1,
            "message_type": "infer_request",
            "request_id": request["request_id"],
            "run_id": request["run_id"],
            "arm_id": request["arm_id"],
            "worker_id": capability["worker_id"],
            "frame": request["frame"],
            "engine": capability["engine"],
            "deadline_monotonic_ns": request["deadline_monotonic_ns"],
            "model": {
                "model_id": capability["model_id"],
                "source_sha256": capability["source_model_sha256"],
                "runtime_artifact_sha256": capability["model_artifact_sha256"],
                "runtime_weights_sha256": capability["runtime_weights_sha256"],
            },
            "tensor": {field: tensor[field] for field in (
                "name", "dtype", "layout", "shape", "byte_length", "sha256",
                "preprocessing_contract_sha256",
            )},
            "expected_output_contract_sha256": capability["output_contract_sha256"],
        }
        with self._locks[key]:
            response, output = self._clients[key].infer(inference_request, inference_payload)
        provenance = response["provenance"]
        terminal = response["terminal"]
        timing = response["timing"]
        worker_resource = _exact(
            response["resource"],
            {
                "process_cpu_time_ns",
                "rss_before_bytes",
                "rss_after_bytes",
                "accelerator_memory_bytes",
                "cuda_h2d_bytes",
                "cuda_d2h_bytes",
                "cuda_transfer_intervals",
            },
            "GStreamer analytics bridge worker resource",
        )
        resource_receipt = {
            field: worker_resource[field]
            for field in (
                "process_cpu_time_ns",
                "rss_before_bytes",
                "rss_after_bytes",
                "accelerator_memory_bytes",
                "cuda_h2d_bytes",
                "cuda_d2h_bytes",
            )
        }
        resource_receipt["cuda_transfer_intervals"] = [
            dict(_mapping(interval, "GStreamer analytics bridge CUDA transfer interval"))
            for interval in worker_resource["cuda_transfer_intervals"]
        ]
        _require(hashlib.sha256(output).hexdigest() == provenance["output_sha256"], "bridge output digest mismatch")
        return {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "message_type": BRIDGE_RESPONSE_TYPE,
            "request_id": request["request_id"],
            "decision_id": decision["decision_id"],
            "decision_seq": decision["decision_seq"],
            "branch": branch,
            "selected_resource": resource,
            "terminal_status": terminal["status"],
            "terminal_reason": terminal["reason"],
            "objects": terminal["objects"],
            "detector": policy["terminal_detector"],
            "backend": policy["terminal_backend"],
            "worker_id": capability["worker_id"],
            "engine": capability["engine"],
            "worker_image_id": provenance["worker_image_id"],
            "worker_implementation_sha256": provenance["worker_implementation_sha256"],
            "runtime_name": provenance["runtime_name"],
            "runtime_version": provenance["runtime_version"],
            "device_api": provenance["device_api"],
            "device_id": provenance["device_id"],
            "native_inference_api": provenance["native_inference_api"],
            "execution_path": provenance["execution_path"],
            "model_id": provenance["model_id"],
            "source_model_sha256": provenance["source_model_sha256"],
            "model_artifact_sha256": provenance["model_artifact_sha256"],
            "preprocessing_contract_sha256": provenance["preprocessing_contract_sha256"],
            "output_contract_sha256": provenance["output_contract_sha256"],
            "raw_input_sha256": raw_sha,
            "input_sha256": provenance["input_sha256"],
            "output_sha256": provenance["output_sha256"],
            "output_bytes": len(output),
            "worker_received_monotonic_ns": timing["worker_received_monotonic_ns"],
            "inference_started_monotonic_ns": timing["inference_started_monotonic_ns"],
            "inference_finished_monotonic_ns": timing["inference_finished_monotonic_ns"],
            "worker_completed_monotonic_ns": timing["worker_completed_monotonic_ns"],
            "inference_latency_ns": timing["inference_latency_ns"],
            "resource": resource_receipt,
        }

    def serve_connection(self, endpoint: socket.socket, *, max_requests: int) -> None:
        _require(type(max_requests) is int and 0 <= max_requests <= 1_000_000, "bridge max_requests is invalid")
        for _ in range(max_requests):
            message, fds = receive_packet(endpoint, expected_fds=1)
            try:
                payload_record = _mapping(message.get("payload"), "bridge payload record")
                byte_length = _integer(payload_record.get("byte_length"), "bridge payload byte_length", minimum=1)
                digest = _sha(payload_record.get("sha256"), "bridge payload sha256")
                payload = verify_sealed_memfd(
                    fds[0], expected_bytes=byte_length, expected_sha256=digest
                )
                send_packet(endpoint, self.execute(message, payload))
            finally:
                close_fds(fds)

    def serve_listener(
        self,
        listener: socket.socket,
        *,
        max_connections: int,
        max_requests_per_connection: int,
    ) -> None:
        _require(
            listener.family == socket.AF_UNIX
            and listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_SEQPACKET,
            "bridge listener must be an AF_UNIX SOCK_SEQPACKET socket",
        )
        _require(
            type(max_connections) is int and 1 <= max_connections <= 1_000_000,
            "bridge max_connections is invalid",
        )
        connection_errors: list[BaseException] = []
        error_lock = threading.Lock()
        threads: list[threading.Thread] = []

        def serve_endpoint(endpoint: socket.socket) -> None:
            try:
                self.serve_connection(
                    endpoint,
                    max_requests=max_requests_per_connection,
                )
            except BaseException as error:
                with error_lock:
                    connection_errors.append(error)
            finally:
                endpoint.close()

        try:
            for connection_index in range(max_connections):
                endpoint, _address = listener.accept()
                thread = threading.Thread(
                    target=serve_endpoint,
                    args=(endpoint,),
                    name=f"vast-analytics-front-{connection_index}",
                )
                threads.append(thread)
                thread.start()
        finally:
            for thread in threads:
                thread.join()
        if connection_errors:
            raise connection_errors[0]


__all__ = [
    "AnalyticsExecutionBridge",
    "BRIDGE_MESSAGE_TYPE",
    "BRIDGE_RESPONSE_TYPE",
    "BRIDGE_SCHEMA_VERSION",
    "open_bridge_listener",
    "preprocess_gstreamer_frame",
]
