#!/usr/bin/env python3
"""Bounded Unix seqpacket protocol for native analytics inference workers.

Control records are canonical JSON datagrams.  Tensor bytes never travel in
JSON: the coordinator passes a sealed memfd with SCM_RIGHTS.  This keeps the
frame identity and byte digest explicit while allowing CPU and CUDA workers to
consume the same real preprocessed buffer without an identity-only adapter.
"""

from __future__ import annotations

import array
import fcntl
import hashlib
import json
import math
import os
import re
import socket
import stat
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
PROTOCOL_ARTIFACT_KIND = "vast_analytics_execution_protocol"
TRANSPORT_KIND = "unix_seqpacket_scm_rights_sealed_memfd"
MAX_CONTROL_BYTES = 65_536
MAX_TENSOR_BYTES = 67_108_864
MAX_ANCILLARY_FDS = 2
MAX_DIMENSIONS = 8
ENGINE_OPENVINO_CPU = "openvino_cpu"
ENGINE_TENSORRT_CUDA = "tensorrt_cuda"
ENGINES = (ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA)
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
DTYPE_BYTES = {"uint8": 1, "float16": 2, "float32": 4}

PROTOCOL_CONTRACT: dict[str, Any] = {
    "artifact_kind": PROTOCOL_ARTIFACT_KIND,
    "schema_version": SCHEMA_VERSION,
    "transport": TRANSPORT_KIND,
    "control_encoding": "canonical_json_utf8_one_datagram",
    "tensor_transport": "one_sealed_memfd_per_request_or_response",
    "max_control_bytes": MAX_CONTROL_BYTES,
    "max_tensor_bytes": MAX_TENSOR_BYTES,
    "max_ancillary_fds": MAX_ANCILLARY_FDS,
    "max_inflight_requests_per_worker": 1,
    "engines": list(ENGINES),
    "branches": list(BRANCHES),
    "native_transfer_timing": {
        ENGINE_OPENVINO_CPU: "forbidden_no_cuda_transfer",
        ENGINE_TENSORRT_CUDA: {
            "intervals": ["h2d", "d2h"],
            "duration_provenance": "native_cuda_event_interval_v1",
            "duration_api": "cudaEventElapsedTime",
            "host_envelope_clock": "CLOCK_MONOTONIC",
        },
    },
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_GPU_UUID_RE = re.compile(
    r"^GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class ProtocolError(RuntimeError):
    """The peer, message, or file descriptor violated the frozen contract."""


class PeerClosed(ProtocolError):
    """The peer performed a clean record-boundary EOF on a SEQPACKET socket."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProtocolError(f"analytics execution value is not canonical JSON: {error}") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


PROTOCOL_IDENTITY_SHA256 = canonical_sha256(PROTOCOL_CONTRACT)


def _duplicate_safe_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"analytics execution JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ProtocolError(f"analytics execution JSON contains non-finite number: {value}")


def parse_canonical_json(payload: bytes) -> dict[str, Any]:
    _require(0 < len(payload) <= MAX_CONTROL_BYTES, "analytics execution control datagram size is invalid")
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_safe_object,
            parse_constant=_reject_json_constant,
        )
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"analytics execution control datagram is invalid JSON: {error}") from error
    _require(isinstance(value, dict), "analytics execution control datagram must be a mapping")
    _require(canonical_json_bytes(value) == payload, "analytics execution control datagram is not canonical JSON")
    return value


def _require_seqpacket(sock: socket.socket) -> None:
    _require(sock.family == socket.AF_UNIX, "analytics execution socket must use AF_UNIX")
    try:
        socket_type = sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
    except OSError as error:
        raise ProtocolError(f"cannot inspect analytics execution socket: {error}") from error
    _require(socket_type == socket.SOCK_SEQPACKET, "analytics execution socket must use SOCK_SEQPACKET")


def close_fds(fds: Sequence[int]) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def send_packet(
    sock: socket.socket,
    message: Mapping[str, Any],
    *,
    fds: Sequence[int] = (),
) -> None:
    _require_seqpacket(sock)
    _require(isinstance(message, Mapping), "analytics execution message must be a mapping")
    _require(len(fds) <= MAX_ANCILLARY_FDS, "analytics execution message has too many file descriptors")
    payload = canonical_json_bytes(dict(message))
    _require(0 < len(payload) <= MAX_CONTROL_BYTES, "analytics execution control datagram is too large")
    ancillary: list[tuple[int, int, bytes]] = []
    if fds:
        descriptor_array = array.array("i", fds)
        _require(all(type(fd) is int and fd >= 0 for fd in fds), "analytics execution FD is invalid")
        ancillary.append((socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptor_array.tobytes()))
    try:
        sent = sock.sendmsg([payload], ancillary, socket.MSG_NOSIGNAL if hasattr(socket, "MSG_NOSIGNAL") else 0)
    except OSError as error:
        raise ProtocolError(f"failed to send analytics execution datagram: {error}") from error
    _require(sent == len(payload), "analytics execution control datagram was partially sent")


def receive_packet(
    sock: socket.socket,
    *,
    expected_fds: int | None = None,
) -> tuple[dict[str, Any], list[int]]:
    _require_seqpacket(sock)
    if expected_fds is not None:
        _require(
            type(expected_fds) is int and 0 <= expected_fds <= MAX_ANCILLARY_FDS,
            "expected analytics execution FD count is invalid",
        )
    descriptor_bytes = array.array("i").itemsize * MAX_ANCILLARY_FDS
    try:
        payload, ancillary, flags, _ = sock.recvmsg(
            MAX_CONTROL_BYTES + 1,
            socket.CMSG_SPACE(descriptor_bytes),
        )
    except OSError as error:
        raise ProtocolError(f"failed to receive analytics execution datagram: {error}") from error
    received_fds: list[int] = []
    try:
        if payload == b"":
            raise PeerClosed("analytics execution peer closed the socket")
        _require(not (flags & socket.MSG_TRUNC), "analytics execution control datagram was truncated")
        _require(not (flags & socket.MSG_CTRUNC), "analytics execution ancillary data was truncated")
        for level, kind, data in ancillary:
            _require(
                level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS,
                "analytics execution message contains unsupported ancillary data",
            )
            descriptors = array.array("i")
            usable = len(data) - (len(data) % descriptors.itemsize)
            descriptors.frombytes(data[:usable])
            received_fds.extend(int(fd) for fd in descriptors)
        _require(
            len(received_fds) <= MAX_ANCILLARY_FDS,
            "analytics execution message contains too many file descriptors",
        )
        if expected_fds is not None:
            _require(
                len(received_fds) == expected_fds,
                f"analytics execution message must contain exactly {expected_fds} file descriptors",
            )
        return parse_canonical_json(payload), received_fds
    except BaseException:
        close_fds(received_fds)
        raise


def _required_seals() -> int:
    names = ("F_SEAL_SEAL", "F_SEAL_SHRINK", "F_SEAL_GROW", "F_SEAL_WRITE")
    _require(all(hasattr(fcntl, name) for name in names), "Linux memfd sealing is unavailable")
    return sum(int(getattr(fcntl, name)) for name in names)


def create_sealed_memfd(name: str, payload: bytes | bytearray | memoryview) -> int:
    _require(hasattr(os, "memfd_create"), "Linux memfd_create is unavailable")
    _require(_STABLE_ID_RE.fullmatch(name) is not None, "analytics execution memfd name is invalid")
    value = bytes(payload)
    _require(0 < len(value) <= MAX_TENSOR_BYTES, "analytics execution tensor byte length is invalid")
    flags = int(getattr(os, "MFD_CLOEXEC", 0x0001)) | int(getattr(os, "MFD_ALLOW_SEALING", 0x0002))
    try:
        fd = os.memfd_create(name, flags=flags)
    except OSError as error:
        raise ProtocolError(f"failed to create analytics execution memfd: {error}") from error
    try:
        offset = 0
        while offset < len(value):
            written = os.write(fd, value[offset:])
            _require(written > 0, "failed to write analytics execution memfd")
            offset += written
        os.fsync(fd)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, _required_seals())
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_fd_exact(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        _require(chunk != b"", "analytics execution memfd ended before its declared size")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def verify_sealed_memfd(
    fd: int,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> bytes:
    _require(type(fd) is int and fd >= 0, "analytics execution FD is invalid")
    _require(
        type(expected_bytes) is int and 0 < expected_bytes <= MAX_TENSOR_BYTES,
        "analytics execution expected byte length is invalid",
    )
    _require(_SHA256_RE.fullmatch(expected_sha256) is not None, "analytics execution expected SHA-256 is invalid")
    try:
        metadata = os.fstat(fd)
        _require(stat.S_ISREG(metadata.st_mode), "analytics execution FD must reference a regular memfd")
        _require(metadata.st_size == expected_bytes, "analytics execution memfd size differs from the contract")
        seals = int(fcntl.fcntl(fd, fcntl.F_GET_SEALS))
        required = _required_seals()
        _require((seals & required) == required, "analytics execution memfd is not fully sealed")
        payload = _read_fd_exact(fd, expected_bytes)
    except ProtocolError:
        raise
    except OSError as error:
        raise ProtocolError(f"failed to inspect analytics execution memfd: {error}") from error
    _require(
        hashlib.sha256(payload).hexdigest() == expected_sha256,
        "analytics execution memfd SHA-256 differs from the contract",
    )
    return payload


def _exact_mapping(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _stable_id(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _visible_text(value: Any, label: str, *, maximum: int = 512) -> str:
    result = str(value or "")
    _require(0 < len(result) <= maximum, f"{label} length is invalid")
    _require(all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result), f"{label} contains controls")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    return int(value)


def validate_frame_identity(value: Any) -> dict[str, Any]:
    frame = _exact_mapping(
        value,
        {"input_frame_key", "stream_id", "frame_id", "transport_pts_ns", "branch"},
        "analytics execution frame",
    )
    result = {
        "input_frame_key": _visible_text(frame["input_frame_key"], "analytics execution input_frame_key"),
        "stream_id": _positive_int(frame["stream_id"], "analytics execution stream_id", allow_zero=True),
        "frame_id": _positive_int(frame["frame_id"], "analytics execution frame_id", allow_zero=True),
        "transport_pts_ns": _positive_int(
            frame["transport_pts_ns"], "analytics execution transport_pts_ns", allow_zero=True
        ),
        "branch": str(frame["branch"]),
    }
    _require(result["branch"] in BRANCHES, "analytics execution branch is invalid")
    return result


def _validate_tensor(value: Any) -> dict[str, Any]:
    tensor = _exact_mapping(
        value,
        {"name", "dtype", "layout", "shape", "byte_length", "sha256", "preprocessing_contract_sha256"},
        "analytics execution tensor",
    )
    dtype = str(tensor["dtype"])
    layout = str(tensor["layout"])
    _require(dtype in DTYPE_BYTES, "analytics execution tensor dtype is invalid")
    _require(layout in {"NCHW", "NHWC"}, "analytics execution tensor layout is invalid")
    shape = tensor["shape"]
    _require(
        type(shape) is list
        and 1 <= len(shape) <= MAX_DIMENSIONS
        and all(type(dimension) is int and 0 < dimension <= 1_000_000 for dimension in shape),
        "analytics execution tensor shape is invalid",
    )
    elements = math.prod(shape)
    expected = elements * DTYPE_BYTES[dtype]
    byte_length = _positive_int(tensor["byte_length"], "analytics execution tensor byte_length")
    _require(expected == byte_length, "analytics execution tensor byte_length differs from dtype and shape")
    _require(byte_length <= MAX_TENSOR_BYTES, "analytics execution tensor exceeds the bounded maximum")
    return {
        "name": _visible_text(tensor["name"], "analytics execution tensor name", maximum=256),
        "dtype": dtype,
        "layout": layout,
        "shape": list(shape),
        "byte_length": byte_length,
        "sha256": _sha(tensor["sha256"], "analytics execution tensor sha256"),
        "preprocessing_contract_sha256": _sha(
            tensor["preprocessing_contract_sha256"],
            "analytics execution preprocessing contract sha256",
        ),
    }


def validate_inference_request(value: Any) -> dict[str, Any]:
    request = _exact_mapping(
        value,
        {
            "schema_version",
            "message_type",
            "request_id",
            "run_id",
            "arm_id",
            "worker_id",
            "frame",
            "engine",
            "deadline_monotonic_ns",
            "model",
            "tensor",
            "expected_output_contract_sha256",
        },
        "analytics execution request",
    )
    _require(request["schema_version"] == SCHEMA_VERSION, "analytics execution request schema_version is invalid")
    _require(request["message_type"] == "infer_request", "analytics execution request message_type is invalid")
    engine = str(request["engine"])
    _require(engine in ENGINES, "analytics execution request engine is invalid")
    model = _exact_mapping(
        request["model"],
        {"model_id", "source_sha256", "runtime_artifact_sha256", "runtime_weights_sha256"},
        "analytics execution model",
    )
    weights = model["runtime_weights_sha256"]
    if engine == ENGINE_OPENVINO_CPU:
        _require(
            type(weights) is str and _SHA256_RE.fullmatch(weights) is not None,
            "OpenVINO CPU request requires an exact runtime weights SHA-256",
        )
    else:
        _require(weights is None, "TensorRT CUDA request must bind one serialized engine and no IR weights")
    result = {
        "schema_version": SCHEMA_VERSION,
        "message_type": "infer_request",
        "request_id": _stable_id(request["request_id"], "analytics execution request_id"),
        "run_id": _stable_id(request["run_id"], "analytics execution run_id"),
        "arm_id": _stable_id(request["arm_id"], "analytics execution arm_id"),
        "worker_id": _stable_id(request["worker_id"], "analytics execution worker_id"),
        "frame": validate_frame_identity(request["frame"]),
        "engine": engine,
        "deadline_monotonic_ns": _positive_int(
            request["deadline_monotonic_ns"], "analytics execution deadline_monotonic_ns"
        ),
        "model": {
            "model_id": _stable_id(model["model_id"], "analytics execution model_id"),
            "source_sha256": _sha(model["source_sha256"], "analytics execution source model sha256"),
            "runtime_artifact_sha256": _sha(
                model["runtime_artifact_sha256"], "analytics execution runtime artifact sha256"
            ),
            "runtime_weights_sha256": weights,
        },
        "tensor": _validate_tensor(request["tensor"]),
        "expected_output_contract_sha256": _sha(
            request["expected_output_contract_sha256"],
            "analytics execution expected output contract sha256",
        ),
    }
    return result


def valid_image_id(value: Any) -> bool:
    return type(value) is str and _IMAGE_ID_RE.fullmatch(value) is not None


def valid_gpu_uuid(value: Any) -> bool:
    return type(value) is str and _GPU_UUID_RE.fullmatch(value) is not None


__all__ = [
    "BRANCHES",
    "DTYPE_BYTES",
    "ENGINE_OPENVINO_CPU",
    "ENGINE_TENSORRT_CUDA",
    "ENGINES",
    "MAX_CONTROL_BYTES",
    "MAX_TENSOR_BYTES",
    "PROTOCOL_CONTRACT",
    "PROTOCOL_IDENTITY_SHA256",
    "PeerClosed",
    "ProtocolError",
    "SCHEMA_VERSION",
    "TRANSPORT_KIND",
    "canonical_json_bytes",
    "canonical_sha256",
    "close_fds",
    "create_sealed_memfd",
    "parse_canonical_json",
    "receive_packet",
    "send_packet",
    "valid_gpu_uuid",
    "valid_image_id",
    "validate_frame_identity",
    "validate_inference_request",
    "verify_sealed_memfd",
]
