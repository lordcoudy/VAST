#!/usr/bin/env python3
"""TensorRT CUDA worker using a small native C++/CUDA inference library."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import socket
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from analytics_execution_protocol import (
    BRANCHES,
    DTYPE_BYTES,
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
    verify_sealed_memfd,
)
from analytics_execution_worker import (
    BackendInference,
    WORKER_CAPABILITY_KIND,
    WORKER_RUNTIME_PROBE_KIND,
    WorkerHarness,
)


BINDING_KIND = "vast_tensorrt_execution_worker_binding"
DEFAULT_LIBRARY = Path("/opt/vast/lib/libvast_tensorrt_backend.so")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_NUMPY_TYPES = {"uint8": np.uint8, "float16": np.float16, "float32": np.float32}
_NATIVE_DTYPES = {0: "uint8", 1: "float16", 2: "float32"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _artifact(value: Any, *, binding_path: Path, suffix: str, label: str) -> Path:
    raw = str(value or "")
    _require(raw and "\n" not in raw and "\r" not in raw, f"{label} path is invalid")
    path = Path(raw)
    resolved = (path if path.is_absolute() else binding_path.parent / path).resolve()
    _require(resolved.is_file() and not resolved.is_symlink(), f"{label} artifact was not found")
    _require(resolved.suffix == suffix, f"{label} artifact suffix is invalid")
    return resolved


def _tensor(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, {"name", "dtype", "layout", "shape"}, label)
    dtype = str(item["dtype"])
    layout = str(item["layout"])
    shape = item["shape"]
    _require(dtype in DTYPE_BYTES, f"{label} dtype is invalid")
    _require(layout in {"NCHW", "NHWC"}, f"{label} layout is invalid")
    _require(type(shape) is list and shape and all(type(dimension) is int and dimension > 0 for dimension in shape), f"{label} shape is invalid")
    _require(math.prod(shape) * DTYPE_BYTES[dtype] <= MAX_TENSOR_BYTES, f"{label} exceeds the tensor bound")
    return {"name": _stable(item["name"], f"{label} name"), "dtype": dtype, "layout": layout, "shape": list(shape)}


def _output(value: Any, index: int) -> dict[str, Any]:
    item = _exact(value, {"name", "dtype", "shape"}, f"TensorRT output {index}")
    dtype = str(item["dtype"])
    shape = item["shape"]
    _require(dtype in DTYPE_BYTES, f"TensorRT output {index} dtype is invalid")
    _require(type(shape) is list and shape and all(type(dimension) is int and dimension > 0 for dimension in shape), f"TensorRT output {index} shape is invalid")
    return {"name": _stable(item["name"], f"TensorRT output {index} name"), "dtype": dtype, "shape": list(shape)}


def load_binding(path: Path | str) -> dict[str, Any]:
    binding_path = Path(path).resolve()
    _require(binding_path.is_file(), f"TensorRT worker binding was not found: {binding_path}")
    try:
        raw = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProtocolError(f"cannot read TensorRT worker binding: {error}") from error
    value = _exact(
        raw,
        {
            "schema_version", "artifact_kind", "worker_id", "branch", "model_id",
            "source_path", "source_model_sha256", "engine_path", "model_artifact_sha256",
            "input", "preprocessing_contract_sha256", "output_contract_sha256",
            "outputs", "worker_image_id", "gpu_device_index", "gpu_uuid",
        },
        "TensorRT worker binding",
    )
    _require(value["schema_version"] == 1, "TensorRT worker binding schema_version is invalid")
    _require(value["artifact_kind"] == BINDING_KIND, "TensorRT worker binding kind is invalid")
    branch = str(value["branch"])
    _require(branch in BRANCHES, "TensorRT worker binding branch is invalid")
    source = _artifact(value["source_path"], binding_path=binding_path, suffix=".onnx", label="TensorRT source")
    engine = _artifact(value["engine_path"], binding_path=binding_path, suffix=".engine", label="TensorRT engine")
    source_sha = _digest(value["source_model_sha256"], "TensorRT source SHA-256")
    engine_sha = _digest(value["model_artifact_sha256"], "TensorRT engine SHA-256")
    _require(_sha_file(source) == source_sha, "TensorRT source SHA-256 differs from the artifact")
    _require(_sha_file(engine) == engine_sha, "TensorRT engine SHA-256 differs from the authoritative artifact")
    outputs_raw = value["outputs"]
    _require(type(outputs_raw) is list and outputs_raw, "TensorRT worker outputs are invalid")
    outputs = [_output(item, index) for index, item in enumerate(outputs_raw)]
    _require(len({item["name"] for item in outputs}) == len(outputs), "TensorRT worker output names must be unique")
    image_id = value["worker_image_id"]
    _require(valid_image_id(image_id), "TensorRT worker image ID is invalid")
    gpu_index = value["gpu_device_index"]
    _require(type(gpu_index) is int and 0 <= gpu_index < 64, "TensorRT worker GPU index is invalid")
    gpu_uuid = str(value["gpu_uuid"])
    _require(valid_gpu_uuid(gpu_uuid), "TensorRT worker GPU UUID is invalid")
    return {
        "schema_version": 1,
        "artifact_kind": BINDING_KIND,
        "worker_id": _stable(value["worker_id"], "TensorRT worker_id"),
        "branch": branch,
        "model_id": _stable(value["model_id"], "TensorRT model_id"),
        "source_path": str(source),
        "source_model_sha256": source_sha,
        "engine_path": str(engine),
        "model_artifact_sha256": engine_sha,
        "input": _tensor(value["input"], "TensorRT input"),
        "preprocessing_contract_sha256": _digest(value["preprocessing_contract_sha256"], "TensorRT preprocessing contract SHA-256"),
        "output_contract_sha256": _digest(value["output_contract_sha256"], "TensorRT output contract SHA-256"),
        "outputs": outputs,
        "worker_image_id": image_id,
        "gpu_device_index": gpu_index,
        "gpu_uuid": gpu_uuid,
    }


class NativeTensorRTSession:
    """ctypes facade over the persistent TensorRT/CUDA C++ session."""

    def __init__(self, engine_path: str, expected_sha256: str, device_index: int, *, library_path: Path = DEFAULT_LIBRARY) -> None:
        self._library_path = Path(library_path).resolve()
        _require(self._library_path.is_file(), f"TensorRT native library was not found: {self._library_path}")
        self._lib = ctypes.CDLL(str(self._library_path))
        self._configure()
        error = ctypes.create_string_buffer(1024)
        handle = ctypes.c_void_p()
        uuid = ctypes.create_string_buffer(64)
        status = self._lib.vast_trt_create(
            os.fsencode(engine_path), expected_sha256.encode("ascii"), device_index,
            ctypes.byref(handle), uuid, len(uuid), error, len(error),
        )
        _require(status == 0 and handle.value, f"TensorRT native session creation failed: {error.value.decode('utf-8', 'replace')}")
        self._handle = handle
        self.gpu_uuid = uuid.value.decode("ascii")
        self.runtime_version = self._lib.vast_trt_runtime_version().decode("ascii")
        self.input_contract = self._query_tensor(input_tensor=True, index=0)
        output_count = int(self._lib.vast_trt_output_count(self._handle))
        _require(0 < output_count <= 64, "TensorRT native output count is invalid")
        self.output_contracts = tuple(self._query_tensor(input_tensor=False, index=index) for index in range(output_count))
        allocation = ctypes.c_uint64()
        _require(self._lib.vast_trt_device_allocation_bytes(self._handle, ctypes.byref(allocation)) == 0, "TensorRT allocation query failed")
        self.device_allocation_bytes = int(allocation.value)
        self._output_bytes = sum(math.prod(item["shape"]) * DTYPE_BYTES[item["dtype"]] for item in self.output_contracts)

    def _configure(self) -> None:
        lib = self._lib
        lib.vast_trt_runtime_version.restype = ctypes.c_char_p
        lib.vast_trt_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        lib.vast_trt_create.restype = ctypes.c_int
        lib.vast_trt_destroy.argtypes = [ctypes.c_void_p]
        lib.vast_trt_destroy.restype = None
        lib.vast_trt_output_count.argtypes = [ctypes.c_void_p]
        lib.vast_trt_output_count.restype = ctypes.c_int
        info_args = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int64), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p, ctypes.c_size_t]
        lib.vast_trt_tensor_info.argtypes = info_args
        lib.vast_trt_tensor_info.restype = ctypes.c_int
        lib.vast_trt_device_allocation_bytes.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
        lib.vast_trt_device_allocation_bytes.restype = ctypes.c_int
        lib.vast_trt_infer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p, ctypes.c_size_t]
        lib.vast_trt_infer.restype = ctypes.c_int

    def _query_tensor(self, *, input_tensor: bool, index: int) -> dict[str, Any]:
        name = ctypes.create_string_buffer(256)
        dtype = ctypes.c_int()
        dimensions = (ctypes.c_int64 * 8)()
        rank = ctypes.c_size_t()
        byte_length = ctypes.c_uint64()
        error = ctypes.create_string_buffer(1024)
        native_index = -1 if input_tensor else index
        status = self._lib.vast_trt_tensor_info(self._handle, native_index, name, len(name), ctypes.byref(dtype), dimensions, 8, ctypes.byref(rank), ctypes.byref(byte_length), error, len(error))
        _require(status == 0, f"TensorRT tensor metadata query failed: {error.value.decode('utf-8', 'replace')}")
        dtype_name = _NATIVE_DTYPES.get(int(dtype.value))
        _require(dtype_name is not None, "TensorRT native tensor dtype is unsupported")
        shape = [int(dimensions[index]) for index in range(rank.value)]
        _require(math.prod(shape) * DTYPE_BYTES[dtype_name] == byte_length.value, "TensorRT native tensor byte length mismatch")
        return {"name": name.value.decode("utf-8"), "dtype": dtype_name, "shape": shape}

    def infer(self, array: np.ndarray) -> bytes:
        contiguous = np.ascontiguousarray(array)
        output = ctypes.create_string_buffer(self._output_bytes)
        written = ctypes.c_uint64()
        error = ctypes.create_string_buffer(1024)
        status = self._lib.vast_trt_infer(
            self._handle, ctypes.c_void_p(contiguous.ctypes.data), contiguous.nbytes,
            output, self._output_bytes, ctypes.byref(written), error, len(error),
        )
        _require(status == 0, f"TensorRT native inference failed: {error.value.decode('utf-8', 'replace')}")
        _require(written.value == self._output_bytes, "TensorRT native inference returned an unexpected byte length")
        return output.raw[: written.value]

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle is not None and handle.value:
            self._lib.vast_trt_destroy(handle)
            self._handle = ctypes.c_void_p()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _implementation_sha256() -> str:
    paths = [Path(__file__).resolve(), Path(sys.modules["analytics_execution_protocol"].__file__).resolve(), Path(sys.modules["analytics_execution_worker"].__file__).resolve()]
    library = Path(os.environ.get("VAST_TENSORRT_BACKEND_LIBRARY", str(DEFAULT_LIBRARY))).resolve()
    source = Path(__file__).with_name("tensorrt_backend.cpp").resolve()
    if library.is_file():
        paths.append(library)
    elif source.is_file():
        paths.append(source)
    inventory = [{"name": path.name, "sha256": _sha_file(path)} for path in sorted(paths, key=lambda item: item.name)]
    return canonical_sha256(inventory)


class TensorRTBackend:
    def __init__(self, binding: Mapping[str, Any], *, native_session: Any | None = None) -> None:
        self._binding = dict(binding)
        self._native = native_session or NativeTensorRTSession(
            self._binding["engine_path"], self._binding["model_artifact_sha256"],
            self._binding["gpu_device_index"],
            library_path=Path(os.environ.get("VAST_TENSORRT_BACKEND_LIBRARY", str(DEFAULT_LIBRARY))),
        )
        _require(self._native.gpu_uuid == self._binding["gpu_uuid"], "TensorRT native GPU UUID differs from the binding")
        expected_input = {key: self._binding["input"][key] for key in ("name", "dtype", "shape")}
        _require(self._native.input_contract == expected_input, "TensorRT native input contract differs from the binding")
        _require(tuple(self._native.output_contracts) == tuple(self._binding["outputs"]), "TensorRT native output contracts differ from the binding")
        _require(type(self._native.device_allocation_bytes) is int and self._native.device_allocation_bytes > 0, "TensorRT native session has no device allocation")

    def capability(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "artifact_kind": WORKER_CAPABILITY_KIND,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "worker_id": self._binding["worker_id"], "branch": self._binding["branch"],
            "engine": ENGINE_TENSORRT_CUDA, "worker_image_id": self._binding["worker_image_id"],
            "worker_implementation_sha256": _implementation_sha256(),
            "runtime_name": "TensorRT", "runtime_version": self._native.runtime_version,
            "device_api": "NVIDIA_CUDA", "device_id": self._native.gpu_uuid,
            "native_inference_api": "nvinfer1::IExecutionContext::enqueueV3",
            "execution_path": "tensorrt_cuda_native", "model_id": self._binding["model_id"],
            "source_model_sha256": self._binding["source_model_sha256"],
            "model_artifact_sha256": self._binding["model_artifact_sha256"],
            "runtime_weights_sha256": None,
            "preprocessing_contract_sha256": self._binding["preprocessing_contract_sha256"],
            "output_contract_sha256": self._binding["output_contract_sha256"],
            "transport": TRANSPORT_KIND, "max_inflight_requests": 1,
            "max_tensor_bytes": MAX_TENSOR_BYTES,
        }

    def infer(self, request: dict[str, Any], tensor: memoryview) -> BackendInference:
        record = request["tensor"]
        for field in ("name", "dtype", "layout", "shape"):
            _require(record[field] == self._binding["input"][field], f"TensorRT request input {field} differs from the binding")
        array = np.frombuffer(
            tensor, dtype=_NUMPY_TYPES[record["dtype"]]
        ).reshape(record["shape"]).copy(order="C")
        output = self._native.infer(array)
        descriptors: list[dict[str, Any]] = []
        offset = 0
        for contract in self._binding["outputs"]:
            byte_length = math.prod(contract["shape"]) * DTYPE_BYTES[contract["dtype"]]
            descriptors.append({**contract, "offset": offset, "byte_length": byte_length})
            offset += byte_length
        _require(offset == len(output), "TensorRT native output byte length differs from the binding")
        return BackendInference(
            output=output, output_tensors=tuple(descriptors), objects=1,
            terminal_reason="native_inference_completed",
            accelerator_memory_bytes=self._native.device_allocation_bytes,
            cuda_h2d_bytes=array.nbytes, cuda_d2h_bytes=len(output),
        )


def _ipc_capabilities() -> dict[str, bool]:
    result = {"socket_seqpacket": False, "scm_rights": False, "memfd_sealing": False}
    left = right = None
    fd = None
    received_fds: list[int] = []
    payload = b"tensorrt-worker-ipc-probe"
    try:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        result["socket_seqpacket"] = True
        fd = create_sealed_memfd("tensorrt-ipc-probe", payload)
        result["memfd_sealing"] = True
        message = {"message_type": "ipc_probe", "schema_version": 1}
        send_packet(left, message, fds=(fd,))
        received, received_fds = receive_packet(right, expected_fds=1)
        _require(received == message, "TensorRT IPC probe message mismatch")
        _require(
            verify_sealed_memfd(
                received_fds[0], expected_bytes=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            ) == payload,
            "TensorRT IPC probe payload mismatch",
        )
        result["scm_rights"] = True
    finally:
        close_fds(received_fds)
        if fd is not None:
            close_fds((fd,))
        if left is not None:
            left.close()
        if right is not None:
            right.close()
    return result


def runtime_probe(*, device_index: int = 0, library_path: Path = DEFAULT_LIBRARY) -> dict[str, Any]:
    path = Path(library_path).resolve()
    _require(path.is_file(), f"TensorRT native library was not found: {path}")
    library = ctypes.CDLL(str(path))
    library.vast_trt_runtime_version.restype = ctypes.c_char_p
    library.vast_trt_probe.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
    library.vast_trt_probe.restype = ctypes.c_int
    uuid = ctypes.create_string_buffer(64)
    error = ctypes.create_string_buffer(1024)
    status = library.vast_trt_probe(device_index, uuid, len(uuid), error, len(error))
    _require(status == 0, f"TensorRT native capability probe failed: {error.value.decode('utf-8', 'replace')}")
    gpu_uuid = uuid.value.decode("ascii")
    _require(valid_gpu_uuid(gpu_uuid), "TensorRT native capability probe returned an invalid GPU UUID")
    return {
        "schema_version": 1,
        "artifact_kind": WORKER_RUNTIME_PROBE_KIND,
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": ENGINE_TENSORRT_CUDA,
        "runtime_name": "TensorRT",
        "runtime_version": library.vast_trt_runtime_version().decode("ascii"),
        "device_api": "NVIDIA_CUDA",
        "device_id": gpu_uuid,
        "native_inference_api": "nvinfer1::IExecutionContext::enqueueV3",
        "execution_path": "tensorrt_cuda_native",
        "worker_implementation_sha256": _implementation_sha256(),
        **_ipc_capabilities(),
        "model_loaded": False,
        "inference_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native TensorRT CUDA analytics execution worker.")
    parser.add_argument("--capability", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--gpu-device-index", type=int, default=0)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.capability:
            _require(args.binding is None and args.socket is None and args.max_requests is None, "capability probe cannot load a binding")
            result = runtime_probe(device_index=args.gpu_device_index, library_path=args.library)
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        _require(args.binding is not None and args.socket is not None and args.max_requests is not None, "binding, socket, and max-requests are required")
        _require(0 <= args.max_requests <= 1_000_000, "max-requests is invalid")
        binding = load_binding(args.binding)
        _require(args.gpu_device_index == binding["gpu_device_index"], "CLI GPU index differs from the binding")
        native = NativeTensorRTSession(
            binding["engine_path"], binding["model_artifact_sha256"], binding["gpu_device_index"],
            library_path=args.library,
        )
        try:
            backend = TensorRTBackend(binding, native_session=native)
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                connection.connect(str(args.socket))
                WorkerHarness(connection, backend, max_requests=args.max_requests).serve()
            finally:
                connection.close()
        finally:
            native.close()
        return 0
    except ProtocolError as error:
        print(json.dumps({"status": "contract_error", "message": str(error)}, sort_keys=True), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BINDING_KIND", "DEFAULT_LIBRARY", "NativeTensorRTSession", "TensorRTBackend",
    "load_binding", "main", "runtime_probe",
]
