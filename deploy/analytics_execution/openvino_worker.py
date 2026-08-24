#!/usr/bin/env python3
"""Native OpenVINO CPU worker for the common analytics execution protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
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
    ENGINE_OPENVINO_CPU,
    MAX_TENSOR_BYTES,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    TRANSPORT_KIND,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
    valid_image_id,
    verify_sealed_memfd,
)
from analytics_execution_worker import (
    BackendInference,
    WORKER_CAPABILITY_KIND,
    WORKER_RUNTIME_PROBE_KIND,
    WorkerHarness,
)


BINDING_KIND = "vast_openvino_execution_worker_binding"
COMPILE_CONFIG = {
    "PERFORMANCE_HINT": "LATENCY",
    "NUM_STREAMS": "1",
    "INFERENCE_NUM_THREADS": "1",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_OV_TYPE_NAMES = {"uint8": "u8", "float16": "f16", "float32": "f32"}
_NUMPY_TYPES = {"uint8": np.uint8, "float16": np.float16, "float32": np.float32}


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


def _artifact(path_value: Any, *, binding_path: Path, suffix: str, label: str) -> Path:
    raw = str(path_value or "")
    _require(raw and "\n" not in raw and "\r" not in raw, f"{label} path is invalid")
    path = Path(raw)
    resolved = (path if path.is_absolute() else binding_path.parent / path).resolve()
    _require(resolved.is_file() and not resolved.is_symlink(), f"{label} artifact was not found")
    _require(resolved.suffix == suffix, f"{label} artifact suffix is invalid")
    return resolved


def _tensor_contract(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, {"name", "dtype", "layout", "shape"}, label)
    name = str(item["name"] or "")
    dtype = str(item["dtype"])
    layout = str(item["layout"])
    shape = item["shape"]
    _require(name and len(name) <= 256 and "\n" not in name, f"{label} name is invalid")
    _require(dtype in DTYPE_BYTES, f"{label} dtype is invalid")
    _require(layout in {"NCHW", "NHWC"}, f"{label} layout is invalid")
    _require(type(shape) is list and shape and all(type(dimension) is int and dimension > 0 for dimension in shape), f"{label} shape is invalid")
    _require(math.prod(shape) * DTYPE_BYTES[dtype] <= MAX_TENSOR_BYTES, f"{label} exceeds the tensor bound")
    return {"name": name, "dtype": dtype, "layout": layout, "shape": list(shape)}


def _output_contract(value: Any, index: int) -> dict[str, Any]:
    item = _exact(value, {"name", "dtype", "shape"}, f"OpenVINO output {index}")
    dtype = str(item["dtype"])
    shape = item["shape"]
    _require(dtype in DTYPE_BYTES, f"OpenVINO output {index} dtype is invalid")
    _require(type(shape) is list and shape and all(type(dimension) is int and dimension > 0 for dimension in shape), f"OpenVINO output {index} shape is invalid")
    return {
        "name": _stable(item["name"], f"OpenVINO output {index} name"),
        "dtype": dtype,
        "shape": list(shape),
    }


def load_binding(path: Path | str) -> dict[str, Any]:
    binding_path = Path(path).resolve()
    _require(binding_path.is_file(), f"OpenVINO worker binding was not found: {binding_path}")
    try:
        raw = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProtocolError(f"cannot read OpenVINO worker binding: {error}") from error
    value = _exact(
        raw,
        {
            "schema_version", "artifact_kind", "worker_id", "branch", "model_id",
            "source_path", "source_model_sha256", "model_path", "model_artifact_sha256",
            "weights_path", "runtime_weights_sha256", "input",
            "preprocessing_contract_sha256", "output_contract_sha256", "outputs",
            "worker_image_id",
        },
        "OpenVINO worker binding",
    )
    _require(value["schema_version"] == 1, "OpenVINO worker binding schema_version is invalid")
    _require(value["artifact_kind"] == BINDING_KIND, "OpenVINO worker binding kind is invalid")
    branch = str(value["branch"])
    _require(branch in BRANCHES, "OpenVINO worker binding branch is invalid")
    source = _artifact(value["source_path"], binding_path=binding_path, suffix=".onnx", label="OpenVINO source")
    model = _artifact(value["model_path"], binding_path=binding_path, suffix=".xml", label="OpenVINO model")
    weights = _artifact(value["weights_path"], binding_path=binding_path, suffix=".bin", label="OpenVINO weights")
    _require(weights == model.with_suffix(".bin"), "OpenVINO weights must be the model sibling")
    digests = {
        "source_model_sha256": _digest(value["source_model_sha256"], "OpenVINO source SHA-256"),
        "model_artifact_sha256": _digest(value["model_artifact_sha256"], "OpenVINO model SHA-256"),
        "runtime_weights_sha256": _digest(value["runtime_weights_sha256"], "OpenVINO weights SHA-256"),
    }
    for file_path, field in ((source, "source_model_sha256"), (model, "model_artifact_sha256"), (weights, "runtime_weights_sha256")):
        _require(_sha_file(file_path) == digests[field], f"OpenVINO {field} differs from the artifact")
    outputs_raw = value["outputs"]
    _require(type(outputs_raw) is list and outputs_raw, "OpenVINO worker outputs are invalid")
    outputs = [_output_contract(output, index) for index, output in enumerate(outputs_raw)]
    _require(len({output["name"] for output in outputs}) == len(outputs), "OpenVINO worker output names must be unique")
    image_id = value["worker_image_id"]
    _require(valid_image_id(image_id), "OpenVINO worker image ID is invalid")
    return {
        "schema_version": 1,
        "artifact_kind": BINDING_KIND,
        "worker_id": _stable(value["worker_id"], "OpenVINO worker_id"),
        "branch": branch,
        "model_id": _stable(value["model_id"], "OpenVINO model_id"),
        "source_path": str(source),
        "source_model_sha256": digests["source_model_sha256"],
        "model_path": str(model),
        "model_artifact_sha256": digests["model_artifact_sha256"],
        "weights_path": str(weights),
        "runtime_weights_sha256": digests["runtime_weights_sha256"],
        "input": _tensor_contract(value["input"], "OpenVINO input"),
        "preprocessing_contract_sha256": _digest(value["preprocessing_contract_sha256"], "OpenVINO preprocessing contract SHA-256"),
        "output_contract_sha256": _digest(value["output_contract_sha256"], "OpenVINO output contract SHA-256"),
        "outputs": outputs,
        "worker_image_id": image_id,
    }


def _implementation_sha256() -> str:
    paths = (
        Path(__file__).resolve(),
        Path(sys.modules["analytics_execution_protocol"].__file__).resolve(),
        Path(sys.modules["analytics_execution_worker"].__file__).resolve(),
    )
    inventory = [{"name": path.name, "sha256": _sha_file(path)} for path in sorted(paths, key=lambda item: item.name)]
    return canonical_sha256(inventory)


def _cpu_identity() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value[:256]
    return (platform.processor() or platform.machine() or "CPU")[:256]


class OpenVINOBackend:
    def __init__(self, binding: Mapping[str, Any], *, openvino_module: Any | None = None) -> None:
        self._binding = dict(binding)
        if openvino_module is None:
            import openvino as openvino_module  # type: ignore[no-redef]
        self._ov = openvino_module
        self._core = self._ov.Core()
        _require("CPU" in list(self._core.available_devices), "OpenVINO runtime does not expose the CPU device")
        model = self._core.read_model(self._binding["model_path"])
        self._compiled = self._core.compile_model(model, "CPU", dict(COMPILE_CONFIG))
        input_contract = self._binding["input"]
        input_port = self._compiled.input(input_contract["name"])
        _require(list(input_port.shape) == input_contract["shape"], "OpenVINO compiled input shape differs from the binding")
        _require(input_port.element_type.get_type_name() == _OV_TYPE_NAMES[input_contract["dtype"]], "OpenVINO compiled input dtype differs from the binding")
        self._output_ports: list[Any] = []
        for output in self._binding["outputs"]:
            port = self._compiled.output(output["name"])
            _require(list(port.shape) == output["shape"], "OpenVINO compiled output shape differs from the binding")
            _require(port.element_type.get_type_name() == _OV_TYPE_NAMES[output["dtype"]], "OpenVINO compiled output dtype differs from the binding")
            self._output_ports.append(port)

    def capability(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact_kind": WORKER_CAPABILITY_KIND,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "worker_id": self._binding["worker_id"],
            "branch": self._binding["branch"],
            "engine": ENGINE_OPENVINO_CPU,
            "worker_image_id": self._binding["worker_image_id"],
            "worker_implementation_sha256": _implementation_sha256(),
            "runtime_name": "OpenVINO",
            "runtime_version": str(self._ov.__version__),
            "device_api": "CPU",
            "device_id": _cpu_identity(),
            "native_inference_api": "openvino.CompiledModel.__call__",
            "execution_path": "openvino_cpu_native",
            "model_id": self._binding["model_id"],
            "source_model_sha256": self._binding["source_model_sha256"],
            "model_artifact_sha256": self._binding["model_artifact_sha256"],
            "runtime_weights_sha256": self._binding["runtime_weights_sha256"],
            "preprocessing_contract_sha256": self._binding["preprocessing_contract_sha256"],
            "output_contract_sha256": self._binding["output_contract_sha256"],
            "transport": TRANSPORT_KIND,
            "max_inflight_requests": 1,
            "max_tensor_bytes": MAX_TENSOR_BYTES,
        }

    def infer(self, request: dict[str, Any], tensor: memoryview) -> BackendInference:
        tensor_record = request["tensor"]
        for field in ("name", "dtype", "layout", "shape"):
            _require(tensor_record[field] == self._binding["input"][field], f"OpenVINO request input {field} differs from the binding")
        array = np.frombuffer(
            tensor, dtype=_NUMPY_TYPES[tensor_record["dtype"]]
        ).reshape(tensor_record["shape"]).copy(order="C")
        results = self._compiled({tensor_record["name"]: array})
        chunks: list[bytes] = []
        descriptors: list[dict[str, Any]] = []
        offset = 0
        for contract, port in zip(self._binding["outputs"], self._output_ports):
            output = np.asarray(results[port])
            _require(list(output.shape) == contract["shape"], "OpenVINO inference output shape differs from the binding")
            _require(output.dtype == np.dtype(_NUMPY_TYPES[contract["dtype"]]), "OpenVINO inference output dtype differs from the binding")
            payload = np.ascontiguousarray(output).tobytes(order="C")
            chunks.append(payload)
            descriptors.append({
                "name": contract["name"], "dtype": contract["dtype"],
                "shape": contract["shape"], "offset": offset,
                "byte_length": len(payload),
            })
            offset += len(payload)
        return BackendInference(
            output=b"".join(chunks),
            output_tensors=tuple(descriptors),
            objects=1,
            terminal_reason="native_inference_completed",
            accelerator_memory_bytes=0,
            cuda_h2d_bytes=0,
            cuda_d2h_bytes=0,
        )


def _ipc_capabilities() -> dict[str, bool]:
    result = {"socket_seqpacket": False, "scm_rights": False, "memfd_sealing": False}
    left = right = None
    fd = None
    received_fds: list[int] = []
    payload = b"openvino-worker-ipc-probe"
    try:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        result["socket_seqpacket"] = True
        fd = create_sealed_memfd("openvino-ipc-probe", payload)
        result["memfd_sealing"] = True
        message = {"message_type": "ipc_probe", "schema_version": 1}
        send_packet(left, message, fds=(fd,))
        received, received_fds = receive_packet(right, expected_fds=1)
        _require(received == message, "OpenVINO IPC probe message mismatch")
        _require(verify_sealed_memfd(received_fds[0], expected_bytes=len(payload), expected_sha256=hashlib.sha256(payload).hexdigest()) == payload, "OpenVINO IPC probe payload mismatch")
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


def runtime_probe(openvino_module: Any | None = None) -> dict[str, Any]:
    if openvino_module is None:
        import openvino as openvino_module  # type: ignore[no-redef]
    core = openvino_module.Core()
    _require("CPU" in list(core.available_devices), "OpenVINO capability probe cannot see CPU")
    return {
        "schema_version": 1,
        "artifact_kind": WORKER_RUNTIME_PROBE_KIND,
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": ENGINE_OPENVINO_CPU,
        "runtime_name": "OpenVINO",
        "runtime_version": str(openvino_module.__version__),
        "device_api": "CPU",
        "device_id": _cpu_identity(),
        "native_inference_api": "openvino.CompiledModel.__call__",
        "execution_path": "openvino_cpu_native",
        "worker_implementation_sha256": _implementation_sha256(),
        **_ipc_capabilities(),
        "model_loaded": False,
        "inference_performed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native OpenVINO CPU analytics execution worker.")
    parser.add_argument("--capability", action="store_true")
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--max-requests", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.capability:
            _require(args.binding is None and args.socket is None and args.max_requests is None, "capability probe cannot load a binding")
            result = runtime_probe()
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        _require(args.binding is not None and args.socket is not None and args.max_requests is not None, "binding, socket, and max-requests are required")
        _require(0 <= args.max_requests <= 1_000_000, "max-requests is invalid")
        binding = load_binding(args.binding)
        backend = OpenVINOBackend(binding)
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            connection.connect(str(args.socket))
            WorkerHarness(connection, backend, max_requests=args.max_requests).serve()
        finally:
            connection.close()
        return 0
    except ProtocolError as error:
        print(json.dumps({"status": "contract_error", "message": str(error)}, sort_keys=True), file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["BINDING_KIND", "COMPILE_CONFIG", "OpenVINOBackend", "load_binding", "main", "runtime_probe"]
