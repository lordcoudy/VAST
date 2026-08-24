#!/usr/bin/env python3
"""Coordinator client and serial native-worker harness for analytics execution."""

from __future__ import annotations

import hashlib
import mmap
import os
import re
import resource
import secrets
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from analytics_execution_protocol import (
    DTYPE_BYTES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_TENSOR_BYTES,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    TRANSPORT_KIND,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
    valid_gpu_uuid,
    valid_image_id,
    validate_frame_identity,
    validate_inference_request,
    verify_sealed_memfd,
)


WORKER_CAPABILITY_KIND = "vast_analytics_execution_worker_capability"
WORKER_RUNTIME_PROBE_KIND = "vast_analytics_execution_worker_runtime_probe"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class WorkerRejected(RuntimeError):
    """A native worker refused a request without executing inference."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class BackendInference:
    """Native backend result before common receipt fields are attached."""

    output: bytes
    output_tensors: tuple[Mapping[str, Any], ...]
    objects: int
    terminal_reason: str
    accelerator_memory_bytes: int
    cuda_h2d_bytes: int
    cuda_d2h_bytes: int


class NativeInferenceBackend(Protocol):
    def capability(self) -> dict[str, Any]: ...

    def infer(self, request: dict[str, Any], tensor: memoryview) -> BackendInference: ...


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _visible(value: Any, label: str, maximum: int = 512) -> str:
    result = str(value or "")
    _require(0 < len(result) <= maximum, f"{label} length is invalid")
    _require(all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result), f"{label} contains controls")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    return int(value)


def validate_worker_capability(value: Any) -> dict[str, Any]:
    capability = _exact(
        value,
        {
            "schema_version", "artifact_kind", "protocol_identity_sha256",
            "worker_id", "branch", "engine", "worker_image_id",
            "worker_implementation_sha256", "runtime_name", "runtime_version",
            "device_api", "device_id", "native_inference_api", "execution_path",
            "model_id", "source_model_sha256", "model_artifact_sha256",
            "runtime_weights_sha256", "preprocessing_contract_sha256",
            "output_contract_sha256", "transport", "max_inflight_requests",
            "max_tensor_bytes",
        },
        "analytics execution worker capability",
    )
    _require(capability["schema_version"] == 1, "analytics execution worker capability schema_version is invalid")
    _require(capability["artifact_kind"] == WORKER_CAPABILITY_KIND, "analytics execution worker capability kind is invalid")
    _require(capability["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution worker protocol identity mismatch")
    engine = str(capability["engine"])
    _require(engine in {ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA}, "analytics execution worker engine is invalid")
    runtime_name = str(capability["runtime_name"])
    device_api = str(capability["device_api"])
    native_api = str(capability["native_inference_api"])
    execution_path = str(capability["execution_path"])
    weights = capability["runtime_weights_sha256"]
    if engine == ENGINE_OPENVINO_CPU:
        _require(runtime_name == "OpenVINO", "OpenVINO CPU worker runtime must be OpenVINO")
        _require(device_api == "CPU", "OpenVINO CPU worker device_api must be CPU")
        _require(native_api == "openvino.CompiledModel.__call__", "OpenVINO CPU worker native inference API is invalid")
        _require(execution_path == "openvino_cpu_native", "OpenVINO CPU worker execution path is invalid")
        _require(type(weights) is str and _SHA256_RE.fullmatch(weights) is not None, "OpenVINO CPU worker requires IR weights SHA-256")
    else:
        _require(runtime_name == "TensorRT", "TensorRT CUDA worker runtime must be TensorRT")
        _require(device_api == "NVIDIA_CUDA", "TensorRT CUDA worker device_api must be NVIDIA_CUDA")
        _require(valid_gpu_uuid(capability["device_id"]), "TensorRT CUDA worker device_id must be an NVIDIA GPU UUID")
        _require(native_api == "nvinfer1::IExecutionContext::enqueueV3", "TensorRT CUDA worker native inference API is invalid")
        _require(execution_path == "tensorrt_cuda_native", "TensorRT CUDA worker execution path is invalid")
        _require(weights is None, "TensorRT CUDA worker must bind one engine and no IR weights")
    result = dict(capability)
    result["worker_id"] = _stable(capability["worker_id"], "analytics execution worker_id")
    result["branch"] = validate_frame_identity({
        "input_frame_key": "capability", "stream_id": 0, "frame_id": 0,
        "transport_pts_ns": 0, "branch": capability["branch"],
    })["branch"]
    _require(valid_image_id(capability["worker_image_id"]), "analytics execution worker image ID is invalid")
    result["worker_implementation_sha256"] = _sha(capability["worker_implementation_sha256"], "analytics execution worker implementation sha256")
    result["runtime_version"] = _visible(capability["runtime_version"], "analytics execution runtime version", 128)
    result["device_id"] = _visible(capability["device_id"], "analytics execution device ID", 256)
    result["model_id"] = _stable(capability["model_id"], "analytics execution model_id")
    for field in ("source_model_sha256", "model_artifact_sha256", "preprocessing_contract_sha256", "output_contract_sha256"):
        result[field] = _sha(capability[field], f"analytics execution {field}")
    result["transport"] = str(capability["transport"])
    _require(result["transport"] == TRANSPORT_KIND, "analytics execution worker transport is invalid")
    _require(capability["max_inflight_requests"] == 1, "analytics execution worker must allow exactly one inflight request")
    _require(capability["max_tensor_bytes"] == MAX_TENSOR_BYTES, "analytics execution worker tensor bound has drifted")
    return result


def validate_runtime_probe(value: Any, *, engine: str) -> dict[str, Any]:
    probe = _exact(
        value,
        {
            "schema_version", "artifact_kind", "protocol_identity_sha256", "engine",
            "runtime_name", "runtime_version", "device_api", "device_id",
            "native_inference_api", "execution_path", "worker_implementation_sha256",
            "socket_seqpacket", "scm_rights", "memfd_sealing", "model_loaded",
            "inference_performed",
        },
        "analytics execution worker runtime probe",
    )
    _require(probe["schema_version"] == 1, "analytics execution worker runtime probe schema is invalid")
    _require(probe["artifact_kind"] == WORKER_RUNTIME_PROBE_KIND, "analytics execution worker runtime probe kind is invalid")
    _require(probe["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution worker runtime probe protocol mismatch")
    _require(probe["engine"] == engine, "analytics execution worker runtime probe engine mismatch")
    _require(all(probe[field] is True for field in ("socket_seqpacket", "scm_rights", "memfd_sealing")), "analytics execution worker runtime probe lacks IPC primitives")
    _require(probe["model_loaded"] is False, "capability probe must not load a model")
    _require(probe["inference_performed"] is False, "capability probe must not execute inference")
    _sha(probe["worker_implementation_sha256"], "analytics execution worker probe implementation sha256")
    _visible(probe["runtime_version"], "analytics execution worker probe runtime version", 128)
    if engine == ENGINE_OPENVINO_CPU:
        _require(probe["runtime_name"] == "OpenVINO", "OpenVINO CPU probe must use OpenVINO")
        _require(probe["device_api"] == "CPU", "OpenVINO CPU probe must report CPU")
        _require(probe["native_inference_api"] == "openvino.CompiledModel.__call__", "OpenVINO CPU probe API is invalid")
        _require(probe["execution_path"] == "openvino_cpu_native", "OpenVINO CPU probe path is invalid")
        _visible(probe["device_id"], "OpenVINO CPU probe device ID", 256)
    elif engine == ENGINE_TENSORRT_CUDA:
        _require(probe["runtime_name"] == "TensorRT", "TensorRT CUDA probe must use TensorRT")
        _require(probe["device_api"] == "NVIDIA_CUDA", "TensorRT CUDA probe must report NVIDIA_CUDA")
        _require(valid_gpu_uuid(probe["device_id"]), "TensorRT CUDA probe must report a GPU UUID")
        _require(probe["native_inference_api"] == "nvinfer1::IExecutionContext::enqueueV3", "TensorRT CUDA probe API is invalid")
        _require(probe["execution_path"] == "tensorrt_cuda_native", "TensorRT CUDA probe path is invalid")
    else:
        raise ProtocolError("analytics execution worker runtime probe engine is invalid")
    return dict(probe)


def _validate_request_against_capability(request: dict[str, Any], capability: dict[str, Any]) -> None:
    _require(request["worker_id"] == capability["worker_id"], "analytics execution request worker binding mismatch")
    _require(request["frame"]["branch"] == capability["branch"], "analytics execution request branch binding mismatch")
    _require(request["engine"] == capability["engine"], "analytics execution request engine binding mismatch")
    model = request["model"]
    _require(model["model_id"] == capability["model_id"], "analytics execution request model_id mismatch")
    _require(model["source_sha256"] == capability["source_model_sha256"], "analytics execution request source model mismatch")
    _require(model["runtime_artifact_sha256"] == capability["model_artifact_sha256"], "analytics execution request runtime artifact mismatch")
    _require(model["runtime_weights_sha256"] == capability["runtime_weights_sha256"], "analytics execution request runtime weights mismatch")
    _require(request["tensor"]["preprocessing_contract_sha256"] == capability["preprocessing_contract_sha256"], "analytics execution request preprocessing contract mismatch")
    _require(request["expected_output_contract_sha256"] == capability["output_contract_sha256"], "analytics execution request output contract mismatch")


def _validate_backend_result(
    result: BackendInference,
    *,
    engine: str,
    input_bytes: int,
) -> tuple[bytes, list[dict[str, Any]], dict[str, int]]:
    _require(isinstance(result, BackendInference), "native analytics backend returned an invalid result type")
    output = bytes(result.output)
    _require(0 < len(output) <= MAX_TENSOR_BYTES, "native analytics backend output byte length is invalid")
    _require(type(result.objects) is int and result.objects >= 0, "native analytics backend objects count is invalid")
    _visible(result.terminal_reason, "native analytics backend terminal reason", 256)
    descriptors: list[dict[str, Any]] = []
    offset = 0
    _require(result.output_tensors, "native analytics backend must describe at least one output tensor")
    for index, raw in enumerate(result.output_tensors):
        descriptor = _exact(raw, {"name", "dtype", "shape", "offset", "byte_length"}, f"native analytics backend output tensor {index}")
        dtype = str(descriptor["dtype"])
        _require(dtype in DTYPE_BYTES, f"native analytics backend output tensor {index} dtype is invalid")
        shape = descriptor["shape"]
        _require(type(shape) is list and shape and all(type(value) is int and value > 0 for value in shape), f"native analytics backend output tensor {index} shape is invalid")
        byte_length = _integer(descriptor["byte_length"], f"native analytics backend output tensor {index} byte_length", minimum=1)
        elements = 1
        for dimension in shape:
            elements *= dimension
        _require(elements * DTYPE_BYTES[dtype] == byte_length, f"native analytics backend output tensor {index} byte length differs from dtype and shape")
        _require(descriptor["offset"] == offset, "native analytics backend output tensors must be contiguous and ordered")
        descriptors.append({
            "name": _visible(descriptor["name"], f"native analytics backend output tensor {index} name", 256),
            "dtype": dtype,
            "shape": list(shape),
            "offset": offset,
            "byte_length": byte_length,
        })
        offset += byte_length
    _require(offset == len(output), "native analytics backend output descriptors do not cover the output memfd")
    resources = {
        "accelerator_memory_bytes": _integer(result.accelerator_memory_bytes, "native analytics accelerator memory"),
        "cuda_h2d_bytes": _integer(result.cuda_h2d_bytes, "native analytics CUDA H2D bytes"),
        "cuda_d2h_bytes": _integer(result.cuda_d2h_bytes, "native analytics CUDA D2H bytes"),
    }
    if engine == ENGINE_OPENVINO_CPU:
        _require(resources == {"accelerator_memory_bytes": 0, "cuda_h2d_bytes": 0, "cuda_d2h_bytes": 0}, "OpenVINO CPU backend cannot report CUDA transfer or accelerator allocation")
    else:
        _require(resources["accelerator_memory_bytes"] > 0, "TensorRT CUDA backend must report device allocation")
        _require(resources["cuda_h2d_bytes"] == input_bytes, "TensorRT CUDA H2D bytes must equal the real input")
        _require(resources["cuda_d2h_bytes"] == len(output), "TensorRT CUDA D2H bytes must equal the real output")
    return output, descriptors, resources


def _rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _hello(capability: dict[str, Any], nonce: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "hello",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "nonce": nonce,
        "expected_capability_sha256": canonical_sha256(capability),
    }


def _validate_hello(value: Any, capability: dict[str, Any]) -> dict[str, Any]:
    message = _exact(value, {"schema_version", "message_type", "protocol_identity_sha256", "nonce", "expected_capability_sha256"}, "analytics execution hello")
    _require(message["schema_version"] == 1 and message["message_type"] == "hello", "analytics execution hello is invalid")
    _require(message["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution hello protocol mismatch")
    _require(type(message["nonce"]) is str and _HEX_64_RE.fullmatch(message["nonce"]) is not None, "analytics execution hello nonce is invalid")
    _require(message["expected_capability_sha256"] == canonical_sha256(capability), "analytics execution hello expected capability mismatch")
    return dict(message)


def _hello_ack(capability: dict[str, Any], nonce: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "hello_ack",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "nonce": nonce,
        "capability": capability,
    }


def _hello_reject() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "hello_reject",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "code": "capability_mismatch",
        "retryable": False,
    }


def _error_response(request_id: str, code: str, message: str) -> dict[str, Any]:
    _require(_STABLE_ID_RE.fullmatch(request_id) is not None, "analytics execution error request_id is invalid")
    _require(code in {"deadline_expired", "contract_rejected", "backend_failure"}, "analytics execution error code is invalid")
    return {
        "schema_version": 1,
        "message_type": "infer_error",
        "request_id": request_id,
        "code": code,
        "message": _visible(message, "analytics execution error message", 256),
        "retryable": False,
    }


class WorkerHarness:
    """Serve one attested backend serially over an already-connected socket."""

    def __init__(self, sock: socket.socket, backend: NativeInferenceBackend, *, max_requests: int) -> None:
        _require(type(max_requests) is int and 0 <= max_requests <= 1_000_000, "analytics worker max_requests is invalid")
        self._socket = sock
        self._backend = backend
        self._max_requests = max_requests
        self._capability = validate_worker_capability(backend.capability())

    def _handshake(self) -> bool:
        message, fds = receive_packet(self._socket, expected_fds=0)
        _require(not fds, "analytics execution hello cannot contain file descriptors")
        try:
            hello = _validate_hello(message, self._capability)
        except ProtocolError:
            send_packet(self._socket, _hello_reject())
            return False
        send_packet(self._socket, _hello_ack(self._capability, hello["nonce"]))
        return True

    def _handle_one(self) -> None:
        message, fds = receive_packet(self._socket, expected_fds=1)
        request_id = str(message.get("request_id") or "invalid")
        try:
            request = validate_inference_request(message)
            _validate_request_against_capability(request, self._capability)
        except ProtocolError:
            close_fds(fds)
            if _STABLE_ID_RE.fullmatch(request_id) is not None:
                send_packet(self._socket, _error_response(request_id, "contract_rejected", "request_contract_rejected"))
                return
            raise
        input_fd = fds[0]
        try:
            tensor_spec = request["tensor"]
            payload = verify_sealed_memfd(input_fd, expected_bytes=tensor_spec["byte_length"], expected_sha256=tensor_spec["sha256"])
            received_ns = time.monotonic_ns()
            if received_ns >= request["deadline_monotonic_ns"]:
                send_packet(self._socket, _error_response(request["request_id"], "deadline_expired", "deadline_expired"))
                return
            rss_before = _rss_bytes()
            cpu_before = time.process_time_ns()
            inference_started = time.monotonic_ns()
            try:
                # F_SEAL_WRITE intentionally rejects shared mappings on some kernels;
                # a private read-only mapping cannot mutate the sealed source memfd.
                with mmap.mmap(
                    input_fd,
                    len(payload),
                    flags=mmap.MAP_PRIVATE,
                    prot=mmap.PROT_READ,
                ) as mapped:
                    tensor_view = memoryview(mapped)
                    try:
                        result = self._backend.infer(request, tensor_view)
                    finally:
                        tensor_view.release()
            except Exception:
                send_packet(self._socket, _error_response(request["request_id"], "backend_failure", "native_backend_failure"))
                return
            inference_finished = max(time.monotonic_ns(), inference_started + 1)
            cpu_after = time.process_time_ns()
            rss_after = _rss_bytes()
            output, descriptors, native_resources = _validate_backend_result(result, engine=request["engine"], input_bytes=len(payload))
            output_sha = hashlib.sha256(output).hexdigest()
            completed_ns = max(time.monotonic_ns(), inference_finished)
            response = {
                "schema_version": 1, "message_type": "infer_response",
                "request_id": request["request_id"], "run_id": request["run_id"],
                "arm_id": request["arm_id"], "worker_id": request["worker_id"],
                "frame": request["frame"], "engine": request["engine"],
                "terminal": {"status": "completed", "objects": result.objects, "reason": result.terminal_reason},
                "output": {
                    "byte_length": len(output), "sha256": output_sha,
                    "contract_sha256": request["expected_output_contract_sha256"],
                    "tensor_count": len(descriptors), "tensors": descriptors,
                },
                "provenance": {
                    "worker_image_id": self._capability["worker_image_id"],
                    "worker_implementation_sha256": self._capability["worker_implementation_sha256"],
                    "runtime_name": self._capability["runtime_name"],
                    "runtime_version": self._capability["runtime_version"],
                    "device_api": self._capability["device_api"], "device_id": self._capability["device_id"],
                    "native_inference_api": self._capability["native_inference_api"],
                    "execution_path": self._capability["execution_path"], "model_id": self._capability["model_id"],
                    "source_model_sha256": self._capability["source_model_sha256"],
                    "model_artifact_sha256": self._capability["model_artifact_sha256"],
                    "runtime_weights_sha256": self._capability["runtime_weights_sha256"],
                    "preprocessing_contract_sha256": self._capability["preprocessing_contract_sha256"],
                    "output_contract_sha256": self._capability["output_contract_sha256"],
                    "input_sha256": tensor_spec["sha256"], "output_sha256": output_sha,
                },
                "timing": {
                    "worker_received_monotonic_ns": received_ns,
                    "inference_started_monotonic_ns": inference_started,
                    "inference_finished_monotonic_ns": inference_finished,
                    "worker_completed_monotonic_ns": completed_ns,
                    "inference_latency_ns": inference_finished - inference_started,
                },
                "resource": {
                    "process_cpu_time_ns": max(0, cpu_after - cpu_before),
                    "rss_before_bytes": rss_before, "rss_after_bytes": rss_after,
                    **native_resources,
                },
            }
            validate_inference_response(response, request=request, capability=self._capability)
            output_fd = create_sealed_memfd(f"vast-output-{request['request_id']}", output)
            try:
                send_packet(self._socket, response, fds=(output_fd,))
            finally:
                os.close(output_fd)
        finally:
            os.close(input_fd)

    def serve(self) -> None:
        if not self._handshake():
            return
        for _ in range(self._max_requests):
            self._handle_one()


def validate_inference_response(
    value: Any,
    *,
    request: dict[str, Any],
    capability: dict[str, Any],
) -> dict[str, Any]:
    response = _exact(
        value,
        {
            "schema_version", "message_type", "request_id", "run_id", "arm_id",
            "worker_id", "frame", "engine", "terminal", "output", "provenance",
            "timing", "resource",
        },
        "analytics execution response",
    )
    _require(response["schema_version"] == 1 and response["message_type"] == "infer_response", "analytics execution response header is invalid")
    for field in ("request_id", "run_id", "arm_id", "worker_id", "engine"):
        _require(response[field] == request[field], f"analytics execution response {field} binding mismatch")
    _require(validate_frame_identity(response["frame"]) == request["frame"], "analytics execution response frame binding mismatch")
    terminal = _exact(response["terminal"], {"status", "objects", "reason"}, "analytics execution terminal")
    _require(terminal["status"] == "completed", "analytics execution terminal status is invalid")
    _integer(terminal["objects"], "analytics execution terminal objects")
    _visible(terminal["reason"], "analytics execution terminal reason", 256)
    output = _exact(response["output"], {"byte_length", "sha256", "contract_sha256", "tensor_count", "tensors"}, "analytics execution output")
    output_bytes = _integer(output["byte_length"], "analytics execution output byte_length", minimum=1)
    _require(output_bytes <= MAX_TENSOR_BYTES, "analytics execution output exceeds bounded maximum")
    output_sha = _sha(output["sha256"], "analytics execution output sha256")
    _require(output["contract_sha256"] == request["expected_output_contract_sha256"], "analytics execution output contract mismatch")
    tensors = output["tensors"]
    _require(type(tensors) is list and tensors, "analytics execution output tensors are invalid")
    _require(output["tensor_count"] == len(tensors), "analytics execution output tensor_count mismatch")
    offset = 0
    for index, descriptor in enumerate(tensors):
        item = _exact(descriptor, {"name", "dtype", "shape", "offset", "byte_length"}, f"analytics execution output tensor {index}")
        _visible(item["name"], f"analytics execution output tensor {index} name", 256)
        _require(item["dtype"] in DTYPE_BYTES, f"analytics execution output tensor {index} dtype is invalid")
        shape = item["shape"]
        _require(type(shape) is list and shape and all(type(d) is int and d > 0 for d in shape), f"analytics execution output tensor {index} shape is invalid")
        length = _integer(item["byte_length"], f"analytics execution output tensor {index} byte_length", minimum=1)
        elements = 1
        for dimension in shape:
            elements *= dimension
        _require(elements * DTYPE_BYTES[item["dtype"]] == length, f"analytics execution output tensor {index} size mismatch")
        _require(item["offset"] == offset, "analytics execution output tensors are not contiguous")
        offset += length
    _require(offset == output_bytes, "analytics execution output tensors do not cover output bytes")
    provenance_fields = {
        "worker_image_id", "worker_implementation_sha256", "runtime_name", "runtime_version",
        "device_api", "device_id", "native_inference_api", "execution_path", "model_id",
        "source_model_sha256", "model_artifact_sha256", "runtime_weights_sha256",
        "preprocessing_contract_sha256", "output_contract_sha256", "input_sha256",
        "output_sha256",
    }
    provenance = _exact(response["provenance"], provenance_fields, "analytics execution provenance")
    for field in (
        "worker_image_id", "worker_implementation_sha256", "runtime_name", "runtime_version",
        "device_api", "device_id", "native_inference_api", "execution_path", "model_id",
        "source_model_sha256", "model_artifact_sha256", "runtime_weights_sha256",
        "preprocessing_contract_sha256", "output_contract_sha256",
    ):
        _require(provenance[field] == capability[field], f"analytics execution provenance {field} mismatch")
    _require(provenance["input_sha256"] == request["tensor"]["sha256"], "analytics execution provenance input digest mismatch")
    _require(provenance["output_sha256"] == output_sha, "analytics execution provenance output digest mismatch")
    timing = _exact(
        response["timing"],
        {"worker_received_monotonic_ns", "inference_started_monotonic_ns", "inference_finished_monotonic_ns", "worker_completed_monotonic_ns", "inference_latency_ns"},
        "analytics execution timing",
    )
    received = _integer(timing["worker_received_monotonic_ns"], "analytics execution receive time", minimum=1)
    started = _integer(timing["inference_started_monotonic_ns"], "analytics execution start time", minimum=1)
    finished = _integer(timing["inference_finished_monotonic_ns"], "analytics execution finish time", minimum=1)
    completed = _integer(timing["worker_completed_monotonic_ns"], "analytics execution completion time", minimum=1)
    _require(received <= started < finished <= completed, "analytics execution timing order is invalid")
    _require(timing["inference_latency_ns"] == finished - started, "analytics execution latency binding mismatch")
    resources = _exact(
        response["resource"],
        {"process_cpu_time_ns", "rss_before_bytes", "rss_after_bytes", "accelerator_memory_bytes", "cuda_h2d_bytes", "cuda_d2h_bytes"},
        "analytics execution resource",
    )
    for field in resources:
        _integer(resources[field], f"analytics execution resource {field}")
    if request["engine"] == ENGINE_OPENVINO_CPU:
        _require(all(resources[field] == 0 for field in ("accelerator_memory_bytes", "cuda_h2d_bytes", "cuda_d2h_bytes")), "OpenVINO CPU response cannot claim CUDA resources")
    else:
        _require(resources["accelerator_memory_bytes"] > 0, "TensorRT CUDA response must bind device allocation")
        _require(resources["cuda_h2d_bytes"] == request["tensor"]["byte_length"], "TensorRT CUDA H2D binding mismatch")
        _require(resources["cuda_d2h_bytes"] == output_bytes, "TensorRT CUDA D2H binding mismatch")
    return dict(response)


class ExecutionClient:
    """Fail-closed coordinator endpoint for one serial native worker."""

    def __init__(self, sock: socket.socket, *, expected_capability: Mapping[str, Any]) -> None:
        self._socket = sock
        self._expected = validate_worker_capability(expected_capability)
        self._handshaken = False

    def handshake(self) -> dict[str, Any]:
        _require(not self._handshaken, "analytics execution client handshake already completed")
        nonce = secrets.token_hex(32)
        send_packet(self._socket, _hello(self._expected, nonce))
        response, fds = receive_packet(self._socket, expected_fds=0)
        _require(not fds, "analytics execution hello_ack cannot contain file descriptors")
        if response.get("message_type") == "hello_reject":
            rejection = _exact(
                response,
                {"schema_version", "message_type", "protocol_identity_sha256", "code", "retryable"},
                "analytics execution hello_reject",
            )
            _require(rejection["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution hello_reject protocol mismatch")
            _require(rejection["retryable"] is False, "analytics execution hello_reject must fail closed")
            raise ProtocolError("analytics execution worker capability mismatch")
        ack = _exact(response, {"schema_version", "message_type", "protocol_identity_sha256", "nonce", "capability"}, "analytics execution hello_ack")
        _require(ack["schema_version"] == 1 and ack["message_type"] == "hello_ack", "analytics execution hello_ack is invalid")
        _require(ack["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256, "analytics execution hello_ack protocol mismatch")
        _require(ack["nonce"] == nonce, "analytics execution hello_ack nonce mismatch")
        actual = validate_worker_capability(ack["capability"])
        _require(actual == self._expected, "analytics execution worker capability mismatch")
        self._handshaken = True
        return actual

    def infer(self, request: Mapping[str, Any], tensor: bytes | bytearray | memoryview) -> tuple[dict[str, Any], bytes]:
        _require(self._handshaken, "analytics execution client handshake is required")
        validated = validate_inference_request(request)
        _validate_request_against_capability(validated, self._expected)
        payload = bytes(tensor)
        _require(len(payload) == validated["tensor"]["byte_length"], "analytics execution client tensor byte length mismatch")
        _require(hashlib.sha256(payload).hexdigest() == validated["tensor"]["sha256"], "analytics execution client tensor SHA-256 mismatch")
        input_fd = create_sealed_memfd(f"vast-input-{validated['request_id']}", payload)
        try:
            send_packet(self._socket, validated, fds=(input_fd,))
        finally:
            os.close(input_fd)
        response, output_fds = receive_packet(self._socket)
        message_type = response.get("message_type")
        if message_type == "infer_error":
            close_fds(output_fds)
            error = _exact(response, {"schema_version", "message_type", "request_id", "code", "message", "retryable"}, "analytics execution inference error")
            _require(error["schema_version"] == 1, "analytics execution inference error schema is invalid")
            _require(error["request_id"] == validated["request_id"], "analytics execution inference error request mismatch")
            _require(error["retryable"] is False, "analytics execution inference errors must fail closed")
            raise WorkerRejected(str(error["code"]), str(error["message"]))
        _require(message_type == "infer_response", "analytics execution worker returned an unexpected message")
        _require(len(output_fds) == 1, "analytics execution response must contain exactly one output memfd")
        try:
            checked = validate_inference_response(response, request=validated, capability=self._expected)
            output_record = checked["output"]
            output = verify_sealed_memfd(output_fds[0], expected_bytes=output_record["byte_length"], expected_sha256=output_record["sha256"])
            return checked, output
        finally:
            close_fds(output_fds)


__all__ = [
    "BackendInference", "ExecutionClient", "NativeInferenceBackend",
    "WORKER_CAPABILITY_KIND", "WORKER_RUNTIME_PROBE_KIND", "WorkerHarness",
    "WorkerRejected", "validate_inference_response", "validate_runtime_probe",
    "validate_worker_capability",
]
