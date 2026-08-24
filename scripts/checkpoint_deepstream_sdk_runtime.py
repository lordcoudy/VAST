#!/usr/bin/env python3
"""Dedicated DeepStream SDK adapter for checkpoint protocol-v3 workers.

This executable owns a real appsrc/parser/NVDEC/nvstreammux graph, consumes the
same framed access-unit FD as the native GStreamer worker, and binds every
admission to the observed ``NvDsFrameMeta`` through a tiny C ABI helper.  It is
not publication evidence by itself: accepted runs still require frozen model
bindings, policy/resource evidence, and paired KPP hardware pilots.

The import surface intentionally uses only the Python standard library.  GI and
the DeepStream helper are loaded lazily after the runtime has validated its FDs.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import os
import queue
import re
import selectors
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


ADMISSION_DATA_FD_ENV = "VAST_CHECKPOINT_ADMISSION_DATA_FD"
CONTROL_FD_ENV = "VAST_CHECKPOINT_CONTROL_FD"
EVENT_FD_ENV = "VAST_CHECKPOINT_EVENT_FD"
POLICY_FD_ENV = "VAST_CHECKPOINT_POLICY_FD"
STATUS_FD_ENV = "VAST_CHECKPOINT_STATUS_FD"
WORKER_ID_ENV = "VAST_CHECKPOINT_WORKER_ID"
RUN_ID_ENV = "VAST_CHECKPOINT_RUN_ID"
TOPOLOGY_KIND_ENV = "VAST_CHECKPOINT_TOPOLOGY_KIND"
STREAM_ID_ENV = "VAST_CHECKPOINT_STREAM_ID"
BRANCH_ID_ENV = "VAST_CHECKPOINT_BRANCH_ID"
BRANCHES_ENV = "VAST_DEEPSTREAM_BRANCHES"

ADMISSION_MAGIC = b"VASTAU01"
ADMISSION_PROTOCOL_VERSION = 1
ADMISSION_FLAG_KEYFRAME = 1 << 0
ADMISSION_KNOWN_FLAGS = ADMISSION_FLAG_KEYFRAME
ADMISSION_HEADER = struct.Struct(">8sHHQQQQQQIIIQ")
ADMISSION_MAX_TEXT_BYTES = 8192
ADMISSION_MAX_PAYLOAD_BYTES = 64 * 1024 * 1024
MISSING_TIMESTAMP = (1 << 64) - 1
LIFECYCLE_PROTOCOL_VERSION = 1
POLICY_RPC_MAX_MESSAGE_BYTES = 64 * 1024
NATIVE_QUEUE_CAPACITY_BUFFERS = 1
NATIVE_QUEUE_DROP_REASON = "native_pre_detector_queue_full_drop_newest"
INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
ANALYTICS_BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROTOCOL_TEXT_RE = re.compile(r"^[^\x00-\x20\x7f]+$")


class DeepStreamSdkRuntimeError(RuntimeError):
    """The SDK graph, callback binding, or inherited protocol failed closed."""


class AdmissionTransportError(DeepStreamSdkRuntimeError):
    """The inherited VASTAU01 stream violated its native framing contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamSdkRuntimeError(message)


def _read_exact(fd: int, size: int, *, clean_eof_allowed: bool = False) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        try:
            chunk = os.read(fd, size - len(data))
        except InterruptedError:
            continue
        if not chunk:
            if not data and clean_eof_allowed:
                return None
            raise AdmissionTransportError("truncated checkpoint admission frame")
        data.extend(chunk)
    return bytes(data)


def _write_exact(fd: int, payload: bytes, label: str) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except InterruptedError:
            continue
        if written <= 0:
            raise DeepStreamSdkRuntimeError(f"{label} write failed")
        offset += written


def _decode_transport_text(payload: bytes, label: str) -> str:
    if not payload or len(payload) > ADMISSION_MAX_TEXT_BYTES:
        raise AdmissionTransportError(f"checkpoint admission {label} size is out of range")
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AdmissionTransportError(f"checkpoint admission {label} is not UTF-8") from exc
    if _PROTOCOL_TEXT_RE.fullmatch(value) is None:
        raise AdmissionTransportError(f"checkpoint admission {label} is not protocol-safe")
    return value


@dataclass(frozen=True)
class AdmissionTransportFrame:
    sequence: int
    keyframe: bool
    source_cycle: int
    access_unit_pts_ns: int
    transport_pts_ns: int
    access_unit_dts_ns: int
    duration_ns: int
    admission_id: str
    input_frame_key: str
    payload_sha256: str
    payload: bytes

    @property
    def frame_id(self) -> int:
        return self.sequence - 1


def read_admission_transport_frame(fd: int) -> AdmissionTransportFrame | None:
    """Read one byte-exact frame emitted by CheckpointAdmissionTransport."""

    header_bytes = _read_exact(fd, ADMISSION_HEADER.size, clean_eof_allowed=True)
    if header_bytes is None:
        return None
    (
        magic,
        protocol,
        flags,
        sequence,
        source_cycle,
        access_unit_pts_ns,
        transport_pts_ns,
        access_unit_dts_ns,
        duration_ns,
        admission_size,
        key_size,
        digest_size,
        payload_size,
    ) = ADMISSION_HEADER.unpack(header_bytes)
    if magic != ADMISSION_MAGIC:
        raise AdmissionTransportError("checkpoint admission frame has invalid magic")
    if protocol != ADMISSION_PROTOCOL_VERSION or flags & ~ADMISSION_KNOWN_FLAGS:
        raise AdmissionTransportError("unsupported checkpoint admission transport protocol")
    if sequence <= 0:
        raise AdmissionTransportError("checkpoint admission sequence must be positive")
    if transport_pts_ns < access_unit_pts_ns:
        raise AdmissionTransportError("checkpoint transport PTS precedes access-unit PTS")
    for value, label in (
        (admission_size, "admission_id"),
        (key_size, "input_frame_key"),
        (digest_size, "payload_sha256"),
    ):
        if value <= 0 or value > ADMISSION_MAX_TEXT_BYTES:
            raise AdmissionTransportError(f"checkpoint admission {label} size is out of range")
    if payload_size <= 0 or payload_size > ADMISSION_MAX_PAYLOAD_BYTES:
        raise AdmissionTransportError("checkpoint admission payload size is out of range")

    admission_raw = _read_exact(fd, admission_size)
    key_raw = _read_exact(fd, key_size)
    digest_raw = _read_exact(fd, digest_size)
    payload = _read_exact(fd, payload_size)
    assert admission_raw is not None and key_raw is not None
    assert digest_raw is not None and payload is not None
    admission_id = _decode_transport_text(admission_raw, "admission_id")
    input_frame_key = _decode_transport_text(key_raw, "input_frame_key")
    payload_sha256 = _decode_transport_text(digest_raw, "payload_sha256")
    if _SHA256_RE.fullmatch(payload_sha256) is None:
        raise AdmissionTransportError("checkpoint admission payload digest is not lowercase SHA-256")
    if hashlib.sha256(payload).hexdigest() != payload_sha256:
        raise AdmissionTransportError("checkpoint admission payload digest mismatch")
    return AdmissionTransportFrame(
        sequence=sequence,
        keyframe=bool(flags & ADMISSION_FLAG_KEYFRAME),
        source_cycle=source_cycle,
        access_unit_pts_ns=access_unit_pts_ns,
        transport_pts_ns=transport_pts_ns,
        access_unit_dts_ns=access_unit_dts_ns,
        duration_ns=duration_ns,
        admission_id=admission_id,
        input_frame_key=input_frame_key,
        payload_sha256=payload_sha256,
        payload=payload,
    )


def admission_identity_sha256(frame: AdmissionTransportFrame) -> bytes:
    """Return the 32-byte identity copied into NvDsFrameMeta.misc_frame_info."""

    return hashlib.sha256(
        frame.admission_id.encode("utf-8")
        + b"\0"
        + frame.input_frame_key.encode("utf-8")
        + b"\0"
        + frame.payload_sha256.encode("ascii")
    ).digest()


def deepstream_buffer_timestamps(
    frame: AdmissionTransportFrame,
    *,
    clock_time_none: int = MISSING_TIMESTAMP,
) -> tuple[int, int, int]:
    """Map one scaled VASTAU01 timeline to GstBuffer PTS/DTS/duration."""

    _require(
        frame.transport_pts_ns >= frame.access_unit_pts_ns,
        "DeepStream transport PTS precedes access-unit PTS",
    )
    dts = clock_time_none
    if frame.access_unit_dts_ns != MISSING_TIMESTAMP:
        delta = int(frame.access_unit_dts_ns) - int(frame.access_unit_pts_ns)
        dts = int(frame.transport_pts_ns) + delta
        _require(dts >= 0, "DeepStream scaled DTS is negative")
    duration = int(frame.duration_ns) if frame.duration_ns > 0 else clock_time_none
    return int(frame.transport_pts_ns), dts, duration


class CanonicalEventFdSink:
    """Serialize each bridge event as exactly one canonical JSONL FD write."""

    def __init__(self, fd: int) -> None:
        _require(type(fd) is int and fd >= 0, "DeepStream event FD is invalid")
        self.fd = fd
        self._lock = threading.Lock()

    def __call__(self, line: str) -> None:
        try:
            value = json.loads(line)
            _require(isinstance(value, dict), "DeepStream runtime event must be a JSON object")
            payload = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii") + b"\n"
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DeepStreamSdkRuntimeError("DeepStream runtime event is not canonical JSON") from exc
        with self._lock:
            _write_exact(self.fd, payload, "DeepStream event FD")


class SeqpacketPolicyExchange:
    """One-request/one-response canonical JSON exchange on the inherited policy FD."""

    def __init__(self, fd: int) -> None:
        _require(type(fd) is int and fd >= 0, "DeepStream policy FD is invalid")
        self._socket = socket.socket(fileno=fd)
        _require(
            (self._socket.type & socket.SOCK_SEQPACKET) == socket.SOCK_SEQPACKET,
            "DeepStream policy FD is not SOCK_SEQPACKET",
        )
        self._lock = threading.Lock()

    def __call__(self, request: dict[str, Any]) -> Mapping[str, Any]:
        try:
            payload = json.dumps(
                request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError) as exc:
            raise DeepStreamSdkRuntimeError("DeepStream policy request is not canonical JSON") from exc
        _require(0 < len(payload) <= POLICY_RPC_MAX_MESSAGE_BYTES, "DeepStream policy request is too large")
        with self._lock:
            sent = self._socket.send(payload)
            _require(sent == len(payload), "DeepStream policy request was truncated")
            response = self._socket.recv(POLICY_RPC_MAX_MESSAGE_BYTES + 1)
        _require(0 < len(response) <= POLICY_RPC_MAX_MESSAGE_BYTES, "DeepStream policy response size is invalid")
        try:
            value = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeepStreamSdkRuntimeError("DeepStream policy response is not JSON") from exc
        _require(isinstance(value, dict), "DeepStream policy response must be an object")
        return value

    def close(self) -> None:
        self._socket.close()


@dataclass(frozen=True)
class LifecycleWindow:
    common_start_monotonic_ns: int
    window_start_timestamp_ms: int
    window_end_timestamp_ms: int
    drain_end_timestamp_ms: int


class LifecycleChannel:
    """Byte-exact worker side of checkpoint synchronized lifecycle v1."""

    def __init__(
        self,
        *,
        worker_id: str,
        control_fd: int,
        status_fd: int,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
    ) -> None:
        _require(bool(worker_id.strip()), "DeepStream worker ID is empty")
        _require(control_fd >= 0 and status_fd >= 0, "DeepStream lifecycle FD is invalid")
        self.worker_id = worker_id
        self.control_fd = control_fd
        self.status_fd = status_fd
        self._monotonic_ns = monotonic_ns
        self._wall_time_ms = wall_time_ms
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def _line(self) -> str:
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                payload = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                try:
                    return payload.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise DeepStreamSdkRuntimeError("DeepStream lifecycle command is not ASCII") from exc
            _require(len(self._buffer) <= 4096, "DeepStream lifecycle command is too large")
            try:
                chunk = os.read(self.control_fd, 4096)
            except InterruptedError:
                continue
            _require(bool(chunk), "DeepStream lifecycle control FD closed unexpectedly")
            self._buffer.extend(chunk)

    def _status(self, state: str, timestamp: int) -> None:
        _require(type(timestamp) is int and timestamp >= 0, "DeepStream lifecycle timestamp is invalid")
        payload = f"{LIFECYCLE_PROTOCOL_VERSION} {state} {self.worker_id} {timestamp}\n".encode("ascii")
        with self._lock:
            _write_exact(self.status_fd, payload, "DeepStream lifecycle status FD")

    def ready(self) -> None:
        self._status("READY", int(self._monotonic_ns()))

    def await_start(self) -> LifecycleWindow:
        parts = self._line().split()
        _require(len(parts) == 6 and parts[:2] == ["1", "START"], "invalid DeepStream START command")
        try:
            values = tuple(int(value) for value in parts[2:])
        except ValueError as exc:
            raise DeepStreamSdkRuntimeError("DeepStream START timestamps are invalid") from exc
        _require(all(value >= 0 for value in values), "DeepStream START timestamps are negative")
        _require(values[1] <= values[2] <= values[3], "DeepStream lifecycle window ordering is invalid")
        return LifecycleWindow(*values)

    def started(self) -> None:
        self._status("STARTED", int(self._wall_time_ms()))

    def decoder_placement_verified(self) -> None:
        self._status("DECODER_PLACEMENT_VERIFIED", int(self._wall_time_ms()))

    def await_stop(self) -> int:
        parts = self._line().split()
        _require(len(parts) == 3 and parts[:2] == ["1", "STOP"], "invalid DeepStream STOP command")
        try:
            timestamp = int(parts[2])
        except ValueError as exc:
            raise DeepStreamSdkRuntimeError("DeepStream STOP timestamp is invalid") from exc
        _require(timestamp >= 0, "DeepStream STOP timestamp is negative")
        return timestamp

    def admission_stopped(self, timestamp_ms: int) -> None:
        self._status("ADMISSION_STOPPED", timestamp_ms)

    def drained(self, timestamp_ms: int) -> None:
        self._status("DRAINED", timestamp_ms)

    def censored(self, timestamp_ms: int) -> None:
        self._status("CENSORED", timestamp_ms)


class NativeBranchQueue:
    """Observable pre-detector queue; capacity overflow drops the incoming item."""

    def __init__(
        self,
        *,
        branch: str,
        capacity_buffers: int,
        on_drop: Callable[[Any, str], None],
    ) -> None:
        _require(branch in ANALYTICS_BRANCHES, "DeepStream native queue branch is invalid")
        _require(capacity_buffers == 1, "DeepStream native branch queue capacity must remain one")
        _require(callable(on_drop), "DeepStream native queue drop callback is missing")
        self.branch = branch
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=capacity_buffers)
        self._on_drop = on_drop

    def submit(self, item: Any) -> bool:
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self._on_drop(item, NATIVE_QUEUE_DROP_REASON)
            return False
        return True

    def take(self, timeout: float | None = None) -> Any:
        return self._queue.get(timeout=timeout)

    def take_nowait(self) -> Any:
        return self._queue.get_nowait()

    def task_done(self) -> None:
        self._queue.task_done()

    def join(self) -> None:
        self._queue.join()


@dataclass(frozen=True)
class DeepStreamGraphSpec:
    topology_kind: str
    codec: str
    stream_id: int
    branches: tuple[str, ...]
    shared_prefix_factories: tuple[str, ...]
    routes: tuple[tuple[str, ...], ...]
    native_queue_capacity_buffers: int = NATIVE_QUEUE_CAPACITY_BUFFERS
    native_queue_drop_policy: str = "drop_newest"
    process_graph_count: int = 1
    decoder_count: int = 1

    @classmethod
    def build(
        cls,
        *,
        topology_kind: str,
        codec: str,
        stream_id: int,
        branches: Sequence[str],
    ) -> "DeepStreamGraphSpec":
        _require(topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}, "unsupported DeepStream topology")
        _require(codec in {"h264", "h265"}, "unsupported DeepStream codec")
        _require(type(stream_id) is int and stream_id >= 0, "DeepStream stream ID is invalid")
        branch_values = tuple(str(value) for value in branches)
        if topology_kind == INDEPENDENT_PROCESSES:
            _require(len(branch_values) == 1 and branch_values[0] in ANALYTICS_BRANCHES, "baseline process requires one branch")
        else:
            _require(branch_values == ANALYTICS_BRANCHES, "shared process requires the frozen four branch order")
        prefix = (
            "appsrc",
            f"{codec}parse",
            "nvv4l2decoder",
            "nvstreammux",
            "nvvideoconvert",
            "capsfilter",
        )
        if topology_kind == SHARED_VIDEO_DAG:
            prefix += ("tee",)
            routes = tuple((branch, "queue", "appsink") for branch in branch_values)
        else:
            routes = ((branch_values[0], "appsink"),)
        return cls(
            topology_kind=topology_kind,
            codec=codec,
            stream_id=stream_id,
            branches=branch_values,
            shared_prefix_factories=prefix,
            routes=routes,
        )


class _NativeObservation(ctypes.Structure):
    _fields_ = (
        ("abi_version", ctypes.c_uint32),
        ("num_frames_in_batch", ctypes.c_uint32),
        ("source_id", ctypes.c_uint32),
        ("batch_id", ctypes.c_uint32),
        ("frame_num", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
        ("buf_pts_ns", ctypes.c_uint64),
        ("identity_sha256", ctypes.c_uint8 * 32),
    )


@dataclass(frozen=True)
class NvDsFrameObservation:
    source_id: int
    batch_id: int
    frame_num: int
    buf_pts_ns: int
    identity_sha256: bytes


class NvDsMetaBridge:
    """ctypes binding to the SDK-compiled NvDsBatchMeta identity adapter."""

    def __init__(self, library_path: Path) -> None:
        _require(library_path.is_file(), f"DeepStream NvDs meta bridge is missing: {library_path}")
        self._library = ctypes.CDLL(str(library_path))
        pointer = ctypes.c_void_p
        digest = ctypes.POINTER(ctypes.c_uint8)
        observation = ctypes.POINTER(_NativeObservation)
        error = ctypes.POINTER(ctypes.c_char)
        for name in ("vast_deepstream_bind_admission", "vast_deepstream_verify_admission"):
            function = getattr(self._library, name)
            function.argtypes = (
                pointer,
                ctypes.c_uint32,
                ctypes.c_uint64,
                digest,
                observation,
                error,
                ctypes.c_size_t,
            )
            function.restype = ctypes.c_int

    @staticmethod
    def _convert(value: _NativeObservation) -> NvDsFrameObservation:
        _require(value.abi_version == 1, "DeepStream NvDs meta bridge ABI drifted")
        _require(value.num_frames_in_batch == 1, "DeepStream batch contains multiple frames")
        return NvDsFrameObservation(
            source_id=int(value.source_id),
            batch_id=int(value.batch_id),
            frame_num=int(value.frame_num),
            buf_pts_ns=int(value.buf_pts_ns),
            identity_sha256=bytes(value.identity_sha256),
        )

    def _call(
        self,
        name: str,
        *,
        buffer_pointer: int,
        stream_id: int,
        transport_pts_ns: int,
        identity_sha256: bytes,
    ) -> NvDsFrameObservation:
        _require(buffer_pointer > 0, "DeepStream GstBuffer pointer is invalid")
        _require(len(identity_sha256) == 32, "DeepStream admission identity digest is invalid")
        digest = (ctypes.c_uint8 * 32).from_buffer_copy(identity_sha256)
        observed = _NativeObservation()
        error = ctypes.create_string_buffer(512)
        result = getattr(self._library, name)(
            ctypes.c_void_p(buffer_pointer),
            stream_id,
            transport_pts_ns,
            digest,
            ctypes.byref(observed),
            error,
            len(error),
        )
        if result != 0:
            message = error.value.decode("utf-8", errors="replace") or f"native error {result}"
            raise DeepStreamSdkRuntimeError(f"DeepStream NvDs metadata binding failed: {message}")
        return self._convert(observed)

    def bind(self, **values: Any) -> NvDsFrameObservation:
        return self._call("vast_deepstream_bind_admission", **values)

    def verify(self, **values: Any) -> NvDsFrameObservation:
        return self._call("vast_deepstream_verify_admission", **values)


class DeepStreamCallbacks(Protocol):
    def admit_transport_frame(self, frame: AdmissionTransportFrame, *, observed_timestamp_ms: int) -> None: ...
    def observe_decoded_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None: ...
    def observe_preprocessed_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None: ...
    def observe_fanout(self, identity: Mapping[str, Any], *, branch: str, observed_timestamp_ms: int) -> None: ...
    def execute_branch_sample(self, identity: Mapping[str, Any], *, branch: str, sample: Any) -> None: ...
    def drop_branch(self, input_frame_key: str, branch: str, *, reason: str, observed_timestamp_ms: int) -> None: ...


class EngineeringCallbackRecorder:
    """Causal callback recorder for local SDK pilots; never emits benchmark events."""

    def __init__(self, graph: DeepStreamGraphSpec) -> None:
        self.graph = graph
        self._admitted: dict[str, AdmissionTransportFrame] = {}
        self._decoded: set[str] = set()
        self._preprocessed: set[str] = set()
        self._fanouts: set[tuple[str, str]] = set()
        self._terminals: set[tuple[str, str]] = set()
        self._drops: list[tuple[str, str, str]] = []
        self._lock = threading.Lock()

    def admit_transport_frame(self, frame: AdmissionTransportFrame, *, observed_timestamp_ms: int) -> None:
        del observed_timestamp_ms
        with self._lock:
            _require(frame.input_frame_key not in self._admitted, "pilot admitted a frame twice")
            self._admitted[frame.input_frame_key] = frame

    def observe_decoded_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None:
        del observed_timestamp_ms
        key = str(identity["input_frame_key"])
        with self._lock:
            _require(key in self._admitted, "pilot decode precedes admission")
            self._decoded.add(key)

    def observe_preprocessed_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None:
        del observed_timestamp_ms
        key = str(identity["input_frame_key"])
        with self._lock:
            _require(key in self._decoded, "pilot preprocess precedes decode")
            self._preprocessed.add(key)

    def observe_fanout(self, identity: Mapping[str, Any], *, branch: str, observed_timestamp_ms: int) -> None:
        del observed_timestamp_ms
        key = str(identity["input_frame_key"])
        with self._lock:
            _require(key in self._preprocessed, "pilot fanout precedes preprocess")
            self._fanouts.add((key, branch))

    def execute_branch_sample(self, identity: Mapping[str, Any], *, branch: str, sample: Any) -> None:
        del sample
        key = str(identity["input_frame_key"])
        with self._lock:
            if self.graph.topology_kind == SHARED_VIDEO_DAG:
                _require((key, branch) in self._fanouts, "pilot terminal precedes fanout")
            else:
                _require(key in self._preprocessed, "pilot terminal precedes preprocess")
            self._terminals.add((key, branch))

    def drop_branch(self, input_frame_key: str, branch: str, *, reason: str, observed_timestamp_ms: int) -> None:
        del observed_timestamp_ms
        with self._lock:
            _require(input_frame_key in self._preprocessed, "pilot drop precedes preprocess")
            self._drops.append((input_frame_key, branch, reason))
            self._terminals.add((input_frame_key, branch))

    def audit(self) -> dict[str, Any]:
        with self._lock:
            expected = {
                (key, branch)
                for key in self._admitted
                for branch in self.graph.branches
            }
            return {
                "schema_version": 1,
                "artifact_kind": "deepstream_sdk_engineering_callback_pilot",
                "claim_status": "engineering_only_not_measurement",
                "topology_kind": self.graph.topology_kind,
                "codec": self.graph.codec,
                "stream_id": self.graph.stream_id,
                "admitted_frames": len(self._admitted),
                "decoded_frames": len(self._decoded),
                "preprocessed_frames": len(self._preprocessed),
                "fanout_callbacks": len(self._fanouts),
                "terminal_callbacks": len(self._terminals),
                "native_queue_drop_callbacks": len(self._drops),
                "callback_causality_complete": self._terminals == expected,
                "accepted_measurement_evidence_emitted": False,
                "publication_ready": False,
            }


@dataclass
class _PendingFrame:
    frame: AdmissionTransportFrame
    identity_sha256: bytes
    identity: dict[str, Any] | None = None
    preprocessed: bool = False
    fanout_branches: set[str] | None = None
    terminal_branches: set[str] | None = None

    def __post_init__(self) -> None:
        if self.fanout_branches is None:
            self.fanout_branches = set()
        if self.terminal_branches is None:
            self.terminal_branches = set()


@dataclass(frozen=True)
class _BranchWork:
    identity: dict[str, Any]
    branch: str
    sample: Any


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _gst_buffer_pointer(buffer: Any) -> int:
    """Return the underlying GstBuffer pointer used by official pyds examples."""

    pointer = int(hash(buffer))
    _require(pointer > 0, "DeepStream GstBuffer pointer could not be resolved")
    return pointer


class DeepStreamSdkPipeline:
    """One physical baseline worker graph or one physical shared graph."""

    def __init__(
        self,
        *,
        graph: DeepStreamGraphSpec,
        callbacks: DeepStreamCallbacks,
        meta_bridge: NvDsMetaBridge,
        decoder_gpu_id: int = 0,
    ) -> None:
        _require(decoder_gpu_id == 0, "checkpoint DeepStream decoder GPU must remain zero")
        self.graph = graph
        self.callbacks = callbacks
        self.meta_bridge = meta_bridge
        self.decoder_gpu_id = decoder_gpu_id
        self._pending: dict[int, _PendingFrame] = {}
        self._seen_transport_pts: set[int] = set()
        self._pending_lock = threading.RLock()
        self._callback_error: BaseException | None = None
        self._callback_error_lock = threading.Lock()
        self.decoded_seen = threading.Event()
        self._eos_seen = threading.Event()
        self._executor_stop = threading.Event()
        self._queues: dict[str, NativeBranchQueue] = {}
        self._executor_threads: list[threading.Thread] = []
        self.Gst = self._load_gst()
        self.pipeline, self.appsrc = self._build_pipeline()
        self._bus_thread = threading.Thread(
            target=self._consume_bus,
            name=f"deepstream-bus-stream-{graph.stream_id}",
            daemon=True,
        )
        for branch in graph.branches:
            native_queue = NativeBranchQueue(
                branch=branch,
                capacity_buffers=NATIVE_QUEUE_CAPACITY_BUFFERS,
                on_drop=self._on_native_drop,
            )
            self._queues[branch] = native_queue
            thread = threading.Thread(
                target=self._execute_branch_queue,
                args=(branch, native_queue),
                name=f"deepstream-native-queue-{graph.stream_id}-{branch}",
                daemon=True,
            )
            self._executor_threads.append(thread)

    @staticmethod
    def _load_gst() -> Any:
        try:
            import gi  # type: ignore

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore
        except Exception as exc:
            raise DeepStreamSdkRuntimeError(
                "DeepStream Python GI/GStreamer bindings are unavailable"
            ) from exc
        Gst.init(None)
        return Gst

    @staticmethod
    def pipeline_factories(
        graph: DeepStreamGraphSpec,
    ) -> tuple[tuple[str, str, str], ...]:
        """Return the exact SDK graph inventory without importing GI."""

        values: list[tuple[str, str, str]] = [
            ("checkpoint_admission_source", "appsrc", f"video/x-{graph.codec},stream-format=byte-stream,alignment=au"),
            ("checkpoint_access_unit_parser", f"{graph.codec}parse", ""),
            ("checkpoint_nvdec_decoder", "nvv4l2decoder", "video/x-raw(memory:NVMM)"),
            ("checkpoint_single_stream_mux", "nvstreammux", "batch-size=1"),
            ("checkpoint_preprocess_surface", "nvvideoconvert", "video/x-raw(memory:NVMM),format=RGBA"),
            ("checkpoint_rgb_download", "capsfilter", "video/x-raw,format=RGB"),
        ]
        if graph.topology_kind == SHARED_VIDEO_DAG:
            values.append(("checkpoint_shared_fanout", "tee", ""))
        for branch in graph.branches:
            if graph.topology_kind == SHARED_VIDEO_DAG:
                values.append((f"checkpoint_route_{branch}", "queue", "max-size-buffers=1"))
            values.append((f"checkpoint_terminal_{branch}", "appsink", "video/x-raw,format=RGB"))
        return tuple(values)

    def _element(self, factory: str, name: str) -> Any:
        element = self.Gst.ElementFactory.make(factory, name)
        _require(element is not None, f"DeepStream element is unavailable: {factory}")
        return element

    def _build_pipeline(self) -> tuple[Any, Any]:
        Gst = self.Gst
        pipeline = Gst.Pipeline.new(f"vast-deepstream-stream-{self.graph.stream_id}")
        _require(pipeline is not None, "DeepStream pipeline allocation failed")
        appsrc = self._element("appsrc", "checkpoint_admission_source")
        parser = self._element(f"{self.graph.codec}parse", "checkpoint_access_unit_parser")
        decoder = self._element("nvv4l2decoder", "checkpoint_nvdec_decoder")
        mux = self._element("nvstreammux", "checkpoint_single_stream_mux")
        converter = self._element("nvvideoconvert", "checkpoint_preprocess_surface")
        rgb_caps = self._element("capsfilter", "checkpoint_rgb_download")
        prefix = [appsrc, parser, decoder, mux, converter, rgb_caps]
        tee = None
        if self.graph.topology_kind == SHARED_VIDEO_DAG:
            tee = self._element("tee", "checkpoint_shared_fanout")
            prefix.append(tee)
        for element in prefix:
            pipeline.add(element)

        appsrc.set_property("is-live", False)
        appsrc.set_property("format", Gst.Format.TIME)
        appsrc.set_property("block", True)
        appsrc.set_property("do-timestamp", False)
        caps = Gst.Caps.from_string(
            f"video/x-{self.graph.codec},stream-format=byte-stream,alignment=au"
        )
        appsrc.set_property("caps", caps)
        decoder.set_property("gpu-id", self.decoder_gpu_id)
        mux.set_property("batch-size", 1)
        mux.set_property("live-source", False)
        mux.set_property("batched-push-timeout", 40_000)
        mux.set_property("width", 1920)
        mux.set_property("height", 1080)
        rgb_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGB"))

        _require(appsrc.link(parser), "DeepStream appsrc->parser link failed")
        _require(parser.link(decoder), "DeepStream parser->NVDEC link failed")
        request_pad = (
            mux.request_pad_simple("sink_0")
            if hasattr(mux, "request_pad_simple")
            else mux.get_request_pad("sink_0")
        )
        decoder_pad = decoder.get_static_pad("src")
        _require(request_pad is not None and decoder_pad is not None, "DeepStream mux pads are unavailable")
        _require(
            decoder_pad.link(request_pad) == Gst.PadLinkReturn.OK,
            "DeepStream NVDEC->nvstreammux link failed",
        )
        _require(mux.link(converter), "DeepStream nvstreammux->nvvideoconvert link failed")
        _require(converter.link(rgb_caps), "DeepStream nvvideoconvert->RGB download link failed")

        mux_src = mux.get_static_pad("src")
        rgb_src = rgb_caps.get_static_pad("src")
        _require(mux_src is not None and rgb_src is not None, "DeepStream callback pads are unavailable")
        mux_src.add_probe(Gst.PadProbeType.BUFFER, self._on_mux_buffer)
        rgb_src.add_probe(Gst.PadProbeType.BUFFER, self._on_preprocess_buffer)

        for branch in self.graph.branches:
            sink = self._element("appsink", f"checkpoint_terminal_{branch}")
            sink.set_property("emit-signals", True)
            sink.set_property("sync", False)
            sink.set_property("max-buffers", 1)
            sink.set_property("drop", False)
            sink.connect("new-sample", self._on_new_sample, branch)
            pipeline.add(sink)
            if tee is None:
                _require(rgb_caps.link(sink), f"DeepStream baseline sink link failed: {branch}")
                continue
            route_queue = self._element("queue", f"checkpoint_route_{branch}")
            route_queue.set_property("max-size-buffers", 1)
            route_queue.set_property("max-size-bytes", 0)
            route_queue.set_property("max-size-time", 0)
            route_queue.set_property("leaky", 0)
            pipeline.add(route_queue)
            _require(tee.link(route_queue), f"DeepStream tee route link failed: {branch}")
            _require(route_queue.link(sink), f"DeepStream route sink link failed: {branch}")
        return pipeline, appsrc

    def _record_error(self, exc: BaseException) -> None:
        with self._callback_error_lock:
            if self._callback_error is None:
                self._callback_error = exc

    def raise_callback_error(self) -> None:
        with self._callback_error_lock:
            error = self._callback_error
        if error is not None:
            raise DeepStreamSdkRuntimeError(f"DeepStream callback failed: {error}") from error

    def _pending_for_buffer(self, buffer: Any) -> _PendingFrame:
        pts = int(buffer.pts)
        with self._pending_lock:
            pending = self._pending.get(pts)
        _require(pending is not None, "DeepStream callback buffer PTS has no admitted frame")
        return pending

    def _native_identity(
        self,
        pending: _PendingFrame,
        observed: NvDsFrameObservation,
    ) -> dict[str, Any]:
        frame = pending.frame
        _require(observed.identity_sha256 == pending.identity_sha256, "NvDs admission identity digest drifted")
        return {
            "schema_version": 1,
            "artifact_kind": "deepstream_nvds_frame_identity",
            "admission_id": frame.admission_id,
            "input_frame_key": frame.input_frame_key,
            "stream_id": self.graph.stream_id,
            "frame_id": frame.frame_id,
            "transport_pts_ns": frame.transport_pts_ns,
            "payload_sha256": frame.payload_sha256,
            "nvds_source_id": observed.source_id,
            "nvds_frame_num": observed.frame_num,
            "nvds_buf_pts_ns": observed.buf_pts_ns,
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": self.decoder_gpu_id,
        }

    def _metadata_values(self, pending: _PendingFrame, buffer: Any) -> dict[str, Any]:
        return {
            "buffer_pointer": _gst_buffer_pointer(buffer),
            "stream_id": self.graph.stream_id,
            "transport_pts_ns": pending.frame.transport_pts_ns,
            "identity_sha256": pending.identity_sha256,
        }

    def _on_mux_buffer(self, _pad: Any, info: Any) -> Any:
        try:
            buffer = info.get_buffer()
            _require(buffer is not None, "DeepStream mux callback has no GstBuffer")
            pending = self._pending_for_buffer(buffer)
            observed = self.meta_bridge.bind(**self._metadata_values(pending, buffer))
            identity = self._native_identity(pending, observed)
            with self._pending_lock:
                _require(pending.identity is None, "DeepStream decode callback was duplicated")
                pending.identity = identity
            self.callbacks.observe_decoded_frame(identity, observed_timestamp_ms=_now_ms())
            self.decoded_seen.set()
        except BaseException as exc:
            self._record_error(exc)
            return self.Gst.PadProbeReturn.DROP
        return self.Gst.PadProbeReturn.OK

    def _on_preprocess_buffer(self, _pad: Any, info: Any) -> Any:
        try:
            buffer = info.get_buffer()
            _require(buffer is not None, "DeepStream preprocess callback has no GstBuffer")
            pending = self._pending_for_buffer(buffer)
            _require(pending.identity is not None, "DeepStream preprocess callback precedes decode")
            self.meta_bridge.verify(**self._metadata_values(pending, buffer))
            with self._pending_lock:
                _require(not pending.preprocessed, "DeepStream preprocess callback was duplicated")
                pending.preprocessed = True
            self.callbacks.observe_preprocessed_frame(
                pending.identity,
                observed_timestamp_ms=_now_ms(),
            )
        except BaseException as exc:
            self._record_error(exc)
            return self.Gst.PadProbeReturn.DROP
        return self.Gst.PadProbeReturn.OK

    def _on_new_sample(self, sink: Any, branch: str) -> Any:
        try:
            sample = sink.emit("pull-sample")
            _require(sample is not None, f"DeepStream appsink returned no sample: {branch}")
            buffer = sample.get_buffer()
            _require(buffer is not None, f"DeepStream appsink sample has no buffer: {branch}")
            pending = self._pending_for_buffer(buffer)
            _require(pending.identity is not None and pending.preprocessed, "DeepStream route precedes preprocessing")
            self.meta_bridge.verify(**self._metadata_values(pending, buffer))
            if self.graph.topology_kind == SHARED_VIDEO_DAG:
                with self._pending_lock:
                    assert pending.fanout_branches is not None
                    _require(branch not in pending.fanout_branches, "DeepStream fanout callback was duplicated")
                    pending.fanout_branches.add(branch)
                self.callbacks.observe_fanout(
                    pending.identity,
                    branch=branch,
                    observed_timestamp_ms=_now_ms(),
                )
            self._queues[branch].submit(
                _BranchWork(identity=dict(pending.identity), branch=branch, sample=sample)
            )
        except BaseException as exc:
            self._record_error(exc)
            return self.Gst.FlowReturn.ERROR
        return self.Gst.FlowReturn.OK

    def _on_native_drop(self, raw: Any, reason: str) -> None:
        _require(isinstance(raw, _BranchWork), "DeepStream native queue dropped an unknown item")
        self.callbacks.drop_branch(
            str(raw.identity["input_frame_key"]),
            raw.branch,
            reason=reason,
            observed_timestamp_ms=_now_ms(),
        )
        self._mark_branch_terminal(raw)

    def _mark_branch_terminal(self, work: _BranchWork) -> None:
        transport_pts_ns = int(work.identity["transport_pts_ns"])
        with self._pending_lock:
            pending = self._pending.get(transport_pts_ns)
            _require(pending is not None, "DeepStream terminal has no admitted frame")
            _require(pending.identity == work.identity, "DeepStream terminal identity drifted")
            assert pending.terminal_branches is not None
            _require(
                work.branch in self.graph.branches
                and work.branch not in pending.terminal_branches,
                "DeepStream branch terminal was duplicated or unknown",
            )
            pending.terminal_branches.add(work.branch)
            if pending.terminal_branches == set(self.graph.branches):
                del self._pending[transport_pts_ns]

    def _execute_branch_queue(self, branch: str, native_queue: NativeBranchQueue) -> None:
        while not self._executor_stop.is_set():
            try:
                work = native_queue.take(timeout=0.1)
            except queue.Empty:
                continue
            try:
                _require(isinstance(work, _BranchWork), "DeepStream branch queue item is invalid")
                self.callbacks.execute_branch_sample(
                    work.identity,
                    branch=branch,
                    sample=work.sample,
                )
                self._mark_branch_terminal(work)
            except BaseException as exc:
                self._record_error(exc)
            finally:
                native_queue.task_done()

    def _consume_bus(self) -> None:
        Gst = self.Gst
        bus = self.pipeline.get_bus()
        while not self._executor_stop.is_set():
            message = bus.timed_pop_filtered(
                100 * Gst.MSECOND,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is None:
                continue
            if message.type == Gst.MessageType.EOS:
                self._eos_seen.set()
                return
            error, debug = message.parse_error()
            self._record_error(
                DeepStreamSdkRuntimeError(
                    f"DeepStream pipeline error: {error}; debug={debug or 'none'}"
                )
            )
            self._eos_seen.set()
            return

    def start(self) -> None:
        result = self.pipeline.set_state(self.Gst.State.PLAYING)
        _require(result != self.Gst.StateChangeReturn.FAILURE, "DeepStream pipeline failed to enter PLAYING")
        for thread in self._executor_threads:
            thread.start()
        self._bus_thread.start()

    def push(self, frame: AdmissionTransportFrame) -> None:
        self.raise_callback_error()
        with self._pending_lock:
            _require(
                frame.transport_pts_ns not in self._seen_transport_pts,
                "DeepStream transport PTS was admitted twice",
            )
            pending = _PendingFrame(frame=frame, identity_sha256=admission_identity_sha256(frame))
            self._pending[frame.transport_pts_ns] = pending
            self._seen_transport_pts.add(frame.transport_pts_ns)
        self.callbacks.admit_transport_frame(frame, observed_timestamp_ms=_now_ms())
        buffer = self.Gst.Buffer.new_allocate(None, len(frame.payload), None)
        _require(buffer is not None, "DeepStream GstBuffer allocation failed")
        _require(buffer.fill(0, frame.payload) == len(frame.payload), "DeepStream GstBuffer fill was truncated")
        buffer.pts, buffer.dts, buffer.duration = deepstream_buffer_timestamps(
            frame,
            clock_time_none=self.Gst.CLOCK_TIME_NONE,
        )
        if frame.keyframe:
            buffer.unset_flags(self.Gst.BufferFlags.DELTA_UNIT)
        else:
            buffer.set_flags(self.Gst.BufferFlags.DELTA_UNIT)
        result = self.appsrc.emit("push-buffer", buffer)
        _require(result == self.Gst.FlowReturn.OK, f"DeepStream appsrc push failed: {result}")

    def finish(self, *, timeout_s: float) -> None:
        _require(timeout_s > 0, "DeepStream drain timeout must be positive")
        result = self.appsrc.emit("end-of-stream")
        _require(result == self.Gst.FlowReturn.OK, f"DeepStream appsrc EOS failed: {result}")
        _require(self._eos_seen.wait(timeout_s), "DeepStream pipeline EOS timed out")
        deadline = time.monotonic() + timeout_s
        for native_queue in self._queues.values():
            while native_queue._queue.unfinished_tasks:  # exact queue drain, no inference.
                self.raise_callback_error()
                _require(time.monotonic() < deadline, "DeepStream native branch queue drain timed out")
                time.sleep(0.005)
        self.raise_callback_error()
        with self._pending_lock:
            _require(
                not self._pending,
                "DeepStream frames remain without exact branch terminal callbacks",
            )

    def close(self) -> None:
        self.pipeline.set_state(self.Gst.State.NULL)
        self._executor_stop.set()
        for thread in self._executor_threads:
            thread.join(timeout=2)
        self._bus_thread.join(timeout=2)


def _integer_environment(name: str) -> int:
    value = os.environ.get(name)
    _require(value is not None, f"required DeepStream environment is missing: {name}")
    try:
        result = int(value)
    except ValueError as exc:
        raise DeepStreamSdkRuntimeError(f"DeepStream environment is not an integer: {name}") from exc
    _require(result >= 0, f"DeepStream environment is negative: {name}")
    return result


def _text_environment(name: str) -> str:
    result = os.environ.get(name, "").strip()
    _require(bool(result), f"required DeepStream environment is missing: {name}")
    return result


def _load_callback_factory(
    reference: str,
    *,
    context: dict[str, Any],
    event_sink: CanonicalEventFdSink,
    policy_exchange: SeqpacketPolicyExchange,
) -> DeepStreamCallbacks:
    module_name, separator, function_name = reference.partition(":")
    _require(bool(separator and module_name and function_name), "DeepStream callback factory must be module:function")
    try:
        function = getattr(importlib.import_module(module_name), function_name)
        callbacks = function(
            context=context,
            event_sink=event_sink,
            policy_exchange=policy_exchange,
        )
    except Exception as exc:
        raise DeepStreamSdkRuntimeError(f"DeepStream callback factory failed: {exc}") from exc
    for name in (
        "admit_transport_frame",
        "observe_decoded_frame",
        "observe_preprocessed_frame",
        "observe_fanout",
        "execute_branch_sample",
        "drop_branch",
    ):
        _require(callable(getattr(callbacks, name, None)), f"DeepStream callbacks lack {name}()")
    return callbacks


def run_fd_worker(args: argparse.Namespace) -> dict[str, Any]:
    worker_id = _text_environment(WORKER_ID_ENV)
    run_id = _text_environment(RUN_ID_ENV)
    topology_kind = _text_environment(TOPOLOGY_KIND_ENV)
    stream_id = _integer_environment(STREAM_ID_ENV)
    _require(args.topology_kind == topology_kind, "DeepStream topology differs between argv and coordinator")
    _require(args.stream_id == stream_id, "DeepStream stream differs between argv and coordinator")
    branches = tuple(value for value in args.branches.split(",") if value)
    graph = DeepStreamGraphSpec.build(
        topology_kind=topology_kind,
        codec=args.codec,
        stream_id=stream_id,
        branches=branches,
    )
    admission_fd = _integer_environment(ADMISSION_DATA_FD_ENV)
    event_sink = CanonicalEventFdSink(_integer_environment(EVENT_FD_ENV))
    lifecycle = LifecycleChannel(
        worker_id=worker_id,
        control_fd=_integer_environment(CONTROL_FD_ENV),
        status_fd=_integer_environment(STATUS_FD_ENV),
    )
    policy = SeqpacketPolicyExchange(_integer_environment(POLICY_FD_ENV))
    context = {
        "run_id": run_id,
        "arm_id": args.arm_id,
        "worker_id": worker_id,
        "topology_kind": topology_kind,
        "stream_id": stream_id,
        "branches": list(branches),
        "codec": args.codec,
        "claim_status": "native_sdk_runtime_requires_external_acceptance",
    }
    callbacks = _load_callback_factory(
        args.callback_factory,
        context=context,
        event_sink=event_sink,
        policy_exchange=policy,
    )
    pipeline = DeepStreamSdkPipeline(
        graph=graph,
        callbacks=callbacks,
        meta_bridge=NvDsMetaBridge(args.nvds_meta_library),
    )
    stop_event = threading.Event()
    stop_timestamp: list[int] = []

    def receive_stop() -> None:
        try:
            stop_timestamp.append(lifecycle.await_stop())
        except BaseException as exc:
            pipeline._record_error(exc)
        finally:
            stop_event.set()

    lifecycle.ready()
    window = lifecycle.await_start()
    while time.monotonic_ns() < window.common_start_monotonic_ns:
        time.sleep(min(0.001, (window.common_start_monotonic_ns - time.monotonic_ns()) / 1e9))
    pipeline.start()
    lifecycle.started()
    stop_thread = threading.Thread(target=receive_stop, name=f"deepstream-stop-{worker_id}", daemon=True)
    stop_thread.start()
    decoder_status_sent = False
    selector = selectors.DefaultSelector()
    selector.register(admission_fd, selectors.EVENT_READ)
    frame_count = 0
    try:
        while not stop_event.is_set():
            pipeline.raise_callback_error()
            if pipeline.decoded_seen.is_set() and not decoder_status_sent:
                lifecycle.decoder_placement_verified()
                decoder_status_sent = True
            ready = selector.select(timeout=0.05)
            if not ready:
                continue
            frame = read_admission_transport_frame(admission_fd)
            _require(frame is not None, "DeepStream admission FD closed before STOP")
            pipeline.push(frame)
            frame_count += 1
        pipeline.raise_callback_error()
        _require(stop_timestamp, "DeepStream STOP timestamp was not received")
        lifecycle.admission_stopped(stop_timestamp[0])
        pipeline.finish(timeout_s=args.drain_timeout_s)
        if pipeline.decoded_seen.is_set() and not decoder_status_sent:
            lifecycle.decoder_placement_verified()
            decoder_status_sent = True
        _require(decoder_status_sent, "DeepStream NVDEC placement was never observed")
        lifecycle.drained(_now_ms())
    except BaseException:
        lifecycle.censored(min(_now_ms(), window.drain_end_timestamp_ms))
        raise
    finally:
        selector.close()
        pipeline.close()
        policy.close()
        close_callbacks = getattr(callbacks, "close", None)
        if callable(close_callbacks):
            close_callbacks()
        stop_thread.join(timeout=2)
    return {
        "schema_version": 1,
        "artifact_kind": "deepstream_sdk_worker_exit",
        "claim_status": "native_runtime_exit_not_publication_acceptance",
        "worker_id": worker_id,
        "physical_graph_count": 1,
        "decoded_process_count": 1,
        "admission_frames": frame_count,
        "publication_ready": False,
    }


def run_engineering_pilot(args: argparse.Namespace) -> dict[str, Any]:
    payload = args.input.read_bytes()
    _require(bool(payload), "DeepStream pilot access unit is empty")
    branches = tuple(value for value in args.branches.split(",") if value)
    graph = DeepStreamGraphSpec.build(
        topology_kind=args.topology_kind,
        codec=args.codec,
        stream_id=args.stream_id,
        branches=branches,
    )
    digest = hashlib.sha256(payload).hexdigest()
    frame = AdmissionTransportFrame(
        sequence=1,
        keyframe=True,
        source_cycle=0,
        access_unit_pts_ns=0,
        transport_pts_ns=0,
        access_unit_dts_ns=MISSING_TIMESTAMP,
        duration_ns=33_333_333,
        admission_id="deepstream-engineering-pilot:0:admission:1",
        input_frame_key=f"deepstream_engineering_{args.codec}:0:{digest}:0:0",
        payload_sha256=digest,
        payload=payload,
    )
    callbacks = EngineeringCallbackRecorder(graph)
    pipeline = DeepStreamSdkPipeline(
        graph=graph,
        callbacks=callbacks,
        meta_bridge=NvDsMetaBridge(args.nvds_meta_library),
    )
    try:
        pipeline.start()
        pipeline.push(frame)
        pipeline.finish(timeout_s=args.timeout_s)
    finally:
        pipeline.close()
    audit = callbacks.audit()
    audit.update(
        {
            "input_sha256": digest,
            "nvds_batch_meta_identity_bound": audit["decoded_frames"] == 1,
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": 0,
            "physical_process_scope": "single_process_engineering_pilot",
        }
    )
    _require(audit["callback_causality_complete"] is True, "DeepStream pilot callback causality is incomplete")
    return audit


def _print_json(value: Mapping[str, Any]) -> None:
    print(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dedicated DeepStream checkpoint SDK runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run one coordinator-bound physical worker")
    run_parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    run_parser.add_argument(
        "--topology-kind",
        choices=(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
        required=True,
    )
    run_parser.add_argument("--stream-id", type=int, required=True)
    run_parser.add_argument("--branches", required=True)
    run_parser.add_argument("--arm-id", required=True)
    run_parser.add_argument("--callback-factory", required=True)
    run_parser.add_argument(
        "--nvds-meta-library",
        type=Path,
        default=Path("/opt/vast/checkpoint/libvast_deepstream_meta_bridge.so"),
    )
    run_parser.add_argument("--drain-timeout-s", type=float, default=10.0)

    pilot_parser = subparsers.add_parser("pilot", help="one-buffer engineering SDK pilot")
    pilot_parser.add_argument("--input", type=Path, required=True)
    pilot_parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    pilot_parser.add_argument(
        "--topology-kind",
        choices=(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
        required=True,
    )
    pilot_parser.add_argument("--stream-id", type=int, default=0)
    pilot_parser.add_argument("--branches", required=True)
    pilot_parser.add_argument(
        "--nvds-meta-library",
        type=Path,
        default=Path("/opt/vast/checkpoint/libvast_deepstream_meta_bridge.so"),
    )
    pilot_parser.add_argument("--timeout-s", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        result = run_fd_worker(args) if args.command == "run" else run_engineering_pilot(args)
        _print_json(result)
        return 0
    except DeepStreamSdkRuntimeError as exc:
        print(f"deepstream sdk runtime blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
