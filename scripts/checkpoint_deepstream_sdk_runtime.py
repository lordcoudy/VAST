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
import csv
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
SOURCE_DURATION_NS_ENV = "VAST_DEEPSTREAM_SOURCE_DURATION_NS"

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
SINGLE_STREAM_MUX_SOURCE_ID = 0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROTOCOL_TEXT_RE = re.compile(r"^[^\x00-\x20\x7f]+$")
STAGE_CONTRACT_COLUMNS = (
    "schema_version",
    "semantic_contract_version",
    "run_id",
    "contract_id",
    "execution_domain",
    "stage",
    "base_stage",
    "implementation_name",
    "implementation_version",
    "implementation_config_json",
    "config_sha256",
    "implementation_artifacts_json",
    "implementation_artifacts_sha256",
    "implementation_artifact_provenance",
    "transform_json",
    "output_media_type",
    "output_format",
    "output_dtype",
    "output_shape_json",
    "ordering_contract",
    "contract_provenance",
    "telemetry_source",
)
_STAGE_ARTIFACT_KINDS = {
    "container_image", "executable", "model", "plugin", "policy", "shared_library",
}


class DeepStreamSdkRuntimeError(RuntimeError):
    """The SDK graph, callback binding, or inherited protocol failed closed."""


class AdmissionTransportError(DeepStreamSdkRuntimeError):
    """The inherited VASTAU01 stream violated its native framing contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamSdkRuntimeError(message)


def _sleep_until_monotonic_ns(
    target_ns: int,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait for a monotonic deadline without a negative-sleep clock race."""

    while True:
        remaining_ns = target_ns - monotonic_ns()
        if remaining_ns <= 0:
            return
        sleep(min(0.001, remaining_ns / 1e9))


def _canonical_json_text(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DeepStreamSdkRuntimeError(f"{label} is not canonical JSON") from exc


def _canonical_stage_artifacts(
    raw: Sequence[Mapping[str, Any]], *, label: str,
) -> list[dict[str, str]]:
    _require(bool(raw), f"{label} runtime artifact manifest is empty")
    result: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for index, value in enumerate(raw):
        _require(
            isinstance(value, Mapping)
            and set(value) == {"role", "kind", "logical_name", "sha256"},
            f"{label} runtime artifact {index} fields drifted",
        )
        role = str(value["role"]).strip()
        kind = str(value["kind"]).strip()
        logical_name = str(value["logical_name"]).strip()
        sha256 = str(value["sha256"]).strip()
        _require(re.fullmatch(r"[a-z][a-z0-9_.-]*", role) is not None, f"{label} artifact role is invalid")
        _require(kind in _STAGE_ARTIFACT_KINDS, f"{label} artifact kind is invalid")
        _require(bool(logical_name) and "\n" not in logical_name and "\r" not in logical_name, f"{label} artifact name is invalid")
        _require(_SHA256_RE.fullmatch(sha256) is not None, f"{label} artifact SHA-256 is invalid")
        identity = (role, kind, logical_name)
        _require(identity not in identities, f"{label} runtime artifact identity is duplicated")
        identities.add(identity)
        result.append({"role": role, "kind": kind, "logical_name": logical_name, "sha256": sha256})
    return sorted(result, key=lambda value: (value["role"], value["kind"], value["logical_name"], value["sha256"]))


def build_deepstream_stage_contract_rows(
    *,
    run_id: str,
    worker_id: str,
    topology_kind: str,
    branches: Sequence[str],
    execution_domain: str,
    implementation_version: str,
    decode_config: Mapping[str, Any],
    preprocess_config: Mapping[str, Any],
    artifacts_by_stage: Mapping[str, Sequence[Mapping[str, Any]]],
    decode_output: Mapping[str, Any],
    preprocess_output: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build semantic-contract rows only from an observed, loaded SDK graph."""

    _require(bool(str(run_id).strip()), "DeepStream stage run_id is empty")
    _require(bool(str(worker_id).strip()), "DeepStream stage worker_id is empty")
    _require(bool(str(execution_domain).strip()), "DeepStream stage execution domain is empty")
    _require(bool(str(implementation_version).strip()), "DeepStream implementation version is empty")
    branch_values = tuple(str(value) for value in branches)
    if topology_kind == INDEPENDENT_PROCESSES:
        _require(len(branch_values) == 1 and branch_values[0] in ANALYTICS_BRANCHES, "baseline stage contract requires one branch")
        suffix = f"_{branch_values[0]}"
    else:
        _require(topology_kind == SHARED_VIDEO_DAG and branch_values == ANALYTICS_BRANCHES, "shared stage contract requires the frozen branch order")
        suffix = ""
    _require(set(artifacts_by_stage) == {"decode", "preprocess"}, "DeepStream stage artifact set drifted")
    rows: list[dict[str, Any]] = []
    for base_stage, config, output in (
        ("decode", dict(decode_config), dict(decode_output)),
        ("preprocess", dict(preprocess_config), dict(preprocess_output)),
    ):
        _require(bool(config), f"DeepStream {base_stage} runtime configuration is empty")
        _require(set(output) == {"media_type", "format", "shape"}, f"DeepStream {base_stage} output fields drifted")
        media_type = str(output["media_type"]).strip()
        output_format = str(output["format"]).strip()
        shape = output["shape"]
        _require(bool(media_type) and bool(output_format), f"DeepStream {base_stage} output identity is empty")
        _require(type(shape) is list and bool(shape) and all((type(value) is int and value > 0) or (type(value) is str and bool(value.strip())) for value in shape), f"DeepStream {base_stage} output shape is invalid")
        config_json = _canonical_json_text(config, f"DeepStream {base_stage} configuration")
        artifacts = _canonical_stage_artifacts(artifacts_by_stage[base_stage], label=base_stage)
        artifacts_json = _canonical_json_text(artifacts, f"DeepStream {base_stage} artifacts")
        if base_stage == "decode":
            transform = {"normalization": {"mode": "identity"}, "resize": {"mode": "identity"}}
        else:
            transform = {"normalization": {"mode": "identity"}, "resize": {"algorithm": "nvstreammux", "mode": "fixed", "output_height": int(shape[0]), "output_width": int(shape[1])}}
        stage = base_stage + suffix
        rows.append({
            "schema_version": 2,
            "semantic_contract_version": 2,
            "run_id": str(run_id),
            "contract_id": f"{run_id}:{execution_domain}:{stage}",
            "execution_domain": str(execution_domain),
            "stage": stage,
            "base_stage": base_stage,
            "implementation_name": f"vast-deepstream-checkpoint-{base_stage}",
            "implementation_version": str(implementation_version),
            "implementation_config_json": config_json,
            "config_sha256": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
            "implementation_artifacts_json": artifacts_json,
            "implementation_artifacts_sha256": hashlib.sha256(artifacts_json.encode("utf-8")).hexdigest(),
            "implementation_artifact_provenance": "runtime_loaded_artifacts_v1",
            "transform_json": _canonical_json_text(transform, f"DeepStream {base_stage} transform"),
            "output_media_type": media_type,
            "output_format": output_format,
            "output_dtype": "uint8",
            "output_shape_json": _canonical_json_text(shape, f"DeepStream {base_stage} output shape"),
            "ordering_contract": "native_pts_preserved_with_gap_free_decode_order_admission_v3",
            "contract_provenance": "runtime_loaded_configuration",
            "telemetry_source": "native",
        })
    return rows


def write_deepstream_stage_contracts(
    output_dir: Path, rows: Sequence[Mapping[str, Any]],
) -> Path:
    """Atomically claim and write the exact per-worker runtime fragment."""

    directory = Path(output_dir)
    _require(directory.is_dir() and not directory.is_symlink(), "DeepStream worker output directory is invalid")
    path = directory / "stage_contracts.runtime.csv"
    try:
        with path.open("x", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=STAGE_CONTRACT_COLUMNS, extrasaction="raise")
            writer.writeheader()
            for value in rows:
                _require(set(value) == set(STAGE_CONTRACT_COLUMNS), "DeepStream stage contract fields drifted")
                writer.writerow(dict(value))
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise DeepStreamSdkRuntimeError("DeepStream stage contract already exists") from exc
    return path


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
    source_duration_ns: int,
    clock_time_none: int = MISSING_TIMESTAMP,
) -> tuple[int, int, int]:
    """Map one scaled VASTAU01 timeline to GstBuffer PTS/DTS/duration."""

    _require(
        type(source_duration_ns) is int and source_duration_ns > 0,
        "DeepStream source duration is invalid",
    )
    _require(
        frame.transport_pts_ns >= frame.access_unit_pts_ns,
        "DeepStream transport PTS precedes access-unit PTS",
    )
    dts = clock_time_none
    if frame.access_unit_dts_ns != MISSING_TIMESTAMP:
        dts = (
            int(frame.source_cycle) * source_duration_ns
            + int(frame.access_unit_dts_ns)
        )
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
    decoder_gpu_id: int = 0

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
        observe = self._library.vast_deepstream_observe_frame
        observe.argtypes = (
            pointer,
            ctypes.c_uint32,
            observation,
            error,
            ctypes.c_size_t,
        )
        observe.restype = ctypes.c_int

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
        source_id: int,
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
            source_id,
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

    def observe(
        self,
        *,
        buffer_pointer: int,
        source_id: int,
    ) -> NvDsFrameObservation:
        _require(buffer_pointer > 0, "DeepStream GstBuffer pointer is invalid")
        observed = _NativeObservation()
        error = ctypes.create_string_buffer(512)
        result = self._library.vast_deepstream_observe_frame(
            ctypes.c_void_p(buffer_pointer),
            source_id,
            ctypes.byref(observed),
            error,
            len(error),
        )
        if result != 0:
            message = error.value.decode("utf-8", errors="replace") or f"native error {result}"
            raise DeepStreamSdkRuntimeError(
                f"DeepStream NvDs metadata observation failed: {message}"
            )
        return self._convert(observed)


class DeepStreamCallbacks(Protocol):
    def admit_transport_frame(self, frame: AdmissionTransportFrame, *, observed_timestamp_ms: int) -> None: ...
    def observe_decoded_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None: ...
    def observe_preprocessed_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None: ...
    def observe_fanout(self, identity: Mapping[str, Any], *, branch: str, observed_timestamp_ms: int) -> int: ...
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

    def observe_fanout(self, identity: Mapping[str, Any], *, branch: str, observed_timestamp_ms: int) -> int:
        key = str(identity["input_frame_key"])
        with self._lock:
            _require(key in self._preprocessed, "pilot fanout precedes preprocess")
            self._fanouts.add((key, branch))
        return int(math.ceil(float(observed_timestamp_ms)))

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
    decode_submit_start_ns: int | None = None
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


def _ceil_epoch_ns_to_ms(value_ns: int) -> int:
    """Convert an exact epoch nanosecond observation without float rounding."""

    _require(
        type(value_ns) is int and value_ns >= 0,
        "DeepStream epoch timestamp must be a non-negative integer",
    )
    return (value_ns + 999_999) // 1_000_000


_COORDINATED_STOP_AFTER_ADMISSION_EOF_GRACE_S = 1.0


def _await_coordinated_stop_after_admission_eof(
    *,
    stop_event: threading.Event,
    stop_thread: threading.Thread,
    stop_timestamp: Sequence[int],
    timeout_s: float = _COORDINATED_STOP_AFTER_ADMISSION_EOF_GRACE_S,
) -> None:
    """Resolve the source-close/worker-STOP scheduling race without accepting raw EOF."""

    _require(timeout_s >= 0, "DeepStream coordinated STOP grace is negative")
    stop_thread.join(timeout=timeout_s)
    _require(
        stop_event.is_set() and bool(stop_timestamp),
        "DeepStream admission FD closed before STOP",
    )


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
        source_duration_ns: int,
        decoder_gpu_id: int = 0,
        resource_recorder: Any | None = None,
    ) -> None:
        _require(decoder_gpu_id == 0, "checkpoint DeepStream decoder GPU must remain zero")
        _require(
            type(source_duration_ns) is int and source_duration_ns > 0,
            "DeepStream source duration is invalid",
        )
        self.graph = graph
        self.callbacks = callbacks
        self.meta_bridge = meta_bridge
        self.source_duration_ns = source_duration_ns
        self.decoder_gpu_id = decoder_gpu_id
        self.resource_recorder = resource_recorder
        self._pending: dict[int, _PendingFrame] = {}
        self._seen_transport_pts: set[int] = set()
        self._pending_lock = threading.RLock()
        self._callback_error: BaseException | None = None
        self._callback_error_lock = threading.Lock()
        self.decoded_seen = threading.Event()
        self.preprocessed_seen = threading.Event()
        self._eos_seen = threading.Event()
        self._terminal_eos_seen = threading.Event()
        self._terminal_eos_branches: set[str] = set()
        self._terminal_eos_lock = threading.Lock()
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
        self._stage_elements = {
            "parser": parser,
            "decoder": decoder,
            "stream_mux": mux,
            "format_converter": converter,
            "caps_filter": rgb_caps,
        }

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
        if tee is not None:
            _require(rgb_caps.link(tee), "DeepStream RGB download->shared tee link failed")

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
            sink.connect("eos", self._on_sink_eos, branch)
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

    def _pending_for_buffer(self, buffer: Any, *, stage: str) -> _PendingFrame:
        observed = self.meta_bridge.observe(
            buffer_pointer=_gst_buffer_pointer(buffer),
            source_id=SINGLE_STREAM_MUX_SOURCE_ID,
        )
        pts = observed.buf_pts_ns
        with self._pending_lock:
            pending = self._pending.get(pts)
            if pending is None:
                pending_pts = tuple(self._pending)
                diagnostic = (
                    f"stage={stage} nvds_buf_pts_ns={pts} "
                    f"gst_buffer_pts_ns={int(buffer.pts)} "
                    f"pending_count={len(pending_pts)} "
                    f"pending_min_pts_ns={min(pending_pts) if pending_pts else 'none'} "
                    f"pending_max_pts_ns={max(pending_pts) if pending_pts else 'none'}"
                )
            else:
                diagnostic = ""
        _require(
            pending is not None,
            "DeepStream callback NvDsFrameMeta buf_pts has no admitted frame: "
            + diagnostic,
        )
        return pending

    def _native_identity(
        self,
        pending: _PendingFrame,
        observed: NvDsFrameObservation,
        *,
        mux_gst_buffer_pts_ns: int,
    ) -> dict[str, Any]:
        frame = pending.frame
        _require(observed.identity_sha256 == pending.identity_sha256, "NvDs admission identity digest drifted")
        _require(
            0 <= mux_gst_buffer_pts_ns < int(self.Gst.CLOCK_TIME_NONE),
            "DeepStream mux GstBuffer PTS is invalid",
        )
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
            "mux_gst_buffer_pts_ns": mux_gst_buffer_pts_ns,
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": self.decoder_gpu_id,
        }

    def _metadata_values(self, pending: _PendingFrame, buffer: Any) -> dict[str, Any]:
        return {
            "buffer_pointer": _gst_buffer_pointer(buffer),
            "source_id": SINGLE_STREAM_MUX_SOURCE_ID,
            "transport_pts_ns": pending.frame.transport_pts_ns,
            "identity_sha256": pending.identity_sha256,
        }

    def _on_mux_buffer(self, _pad: Any, info: Any) -> Any:
        try:
            buffer = info.get_buffer()
            _require(buffer is not None, "DeepStream mux callback has no GstBuffer")
            pending = self._pending_for_buffer(buffer, stage="mux")
            observed = self.meta_bridge.bind(**self._metadata_values(pending, buffer))
            identity = self._native_identity(
                pending,
                observed,
                mux_gst_buffer_pts_ns=int(buffer.pts),
            )
            completed_ns = time.time_ns()
            with self._pending_lock:
                _require(pending.identity is None, "DeepStream decode callback was duplicated")
                pending.identity = identity
            self.callbacks.observe_decoded_frame(
                identity,
                observed_timestamp_ms=_ceil_epoch_ns_to_ms(completed_ns),
            )
            if self.resource_recorder is not None:
                _require(
                    pending.decode_submit_start_ns is not None,
                    "DeepStream NVDEC callback lacks its native submit timestamp",
                )
                self.resource_recorder.record_nvdec(
                    frame_id=pending.frame.frame_id,
                    input_frame_key=pending.frame.input_frame_key,
                    payload_bytes=len(pending.frame.payload),
                    start_timestamp_ns=pending.decode_submit_start_ns,
                    end_timestamp_ns=completed_ns,
                )
            self.decoded_seen.set()
        except BaseException as exc:
            self._record_error(exc)
            return self.Gst.PadProbeReturn.DROP
        return self.Gst.PadProbeReturn.OK

    def _on_preprocess_buffer(self, _pad: Any, info: Any) -> Any:
        try:
            buffer = info.get_buffer()
            _require(buffer is not None, "DeepStream preprocess callback has no GstBuffer")
            pending = self._pending_for_buffer(buffer, stage="preprocess")
            _require(pending.identity is not None, "DeepStream preprocess callback precedes decode")
            self.meta_bridge.verify(**self._metadata_values(pending, buffer))
            _require(
                int(buffer.pts) == int(pending.identity["mux_gst_buffer_pts_ns"]),
                "DeepStream preprocess GstBuffer PTS drifted from mux output",
            )
            with self._pending_lock:
                _require(not pending.preprocessed, "DeepStream preprocess callback was duplicated")
                pending.preprocessed = True
            self.callbacks.observe_preprocessed_frame(
                pending.identity,
                observed_timestamp_ms=_now_ms(),
            )
            self.preprocessed_seen.set()
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
            pending = self._pending_for_buffer(buffer, stage="terminal")
            _require(pending.identity is not None and pending.preprocessed, "DeepStream route precedes preprocessing")
            fanout_started_ns = time.time_ns()
            fanout_started_thread_ns = time.thread_time_ns()
            self.meta_bridge.verify(**self._metadata_values(pending, buffer))
            if self.graph.topology_kind == SHARED_VIDEO_DAG:
                with self._pending_lock:
                    assert pending.fanout_branches is not None
                    _require(branch not in pending.fanout_branches, "DeepStream fanout callback was duplicated")
                    pending.fanout_branches.add(branch)
                fanout_completed_ns = time.time_ns()
                serialized_fanout_timestamp_ms = self.callbacks.observe_fanout(
                    pending.identity,
                    branch=branch,
                    observed_timestamp_ms=_ceil_epoch_ns_to_ms(
                        fanout_completed_ns
                    ),
                )
                _require(
                    type(serialized_fanout_timestamp_ms) is int
                    and serialized_fanout_timestamp_ms > 0,
                    "DeepStream fanout callback did not return its serialized topology timestamp",
                )
                fanout_completed_thread_ns = time.thread_time_ns()
                if self.resource_recorder is not None:
                    self.resource_recorder.record_fanout(
                        frame_id=pending.frame.frame_id,
                        input_frame_key=pending.frame.input_frame_key,
                        branch=branch,
                        payload_bytes=int(buffer.get_size()),
                        start_timestamp_ns=fanout_started_ns,
                        end_timestamp_ns=fanout_completed_ns,
                        serialized_topology_timestamp_ms=serialized_fanout_timestamp_ms,
                        thread_cpu_time_ns=(
                            fanout_completed_thread_ns - fanout_started_thread_ns
                        ),
                    )
            self._queues[branch].submit(
                _BranchWork(identity=dict(pending.identity), branch=branch, sample=sample)
            )
        except BaseException as exc:
            self._record_error(exc)
            return self.Gst.FlowReturn.ERROR
        return self.Gst.FlowReturn.OK

    def _on_sink_eos(self, _sink: Any, branch: str) -> None:
        try:
            _require(branch in self.graph.branches, "DeepStream EOS branch is unknown")
            with self._terminal_eos_lock:
                _require(branch not in self._terminal_eos_branches, "DeepStream branch EOS was duplicated")
                self._terminal_eos_branches.add(branch)
                if self._terminal_eos_branches == set(self.graph.branches):
                    self._terminal_eos_seen.set()
        except BaseException as exc:
            self._record_error(exc)

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
        # A source admission is recorded as a floored millisecond timestamp by
        # the native coordinator.  Source-read is a later completion edge, so
        # round its exact epoch observation upward.  Flooring both independent
        # process observations can invert their order when the clocks differ by
        # less than one quantization bucket on the WSL2/Docker boundary.
        self.callbacks.admit_transport_frame(
            frame,
            observed_timestamp_ms=_ceil_epoch_ns_to_ms(time.time_ns()),
        )
        with self._pending_lock:
            _require(
                frame.transport_pts_ns not in self._seen_transport_pts,
                "DeepStream transport PTS was admitted twice",
            )
            pending = _PendingFrame(
                frame=frame,
                identity_sha256=admission_identity_sha256(frame),
            )
            self._pending[frame.transport_pts_ns] = pending
            self._seen_transport_pts.add(frame.transport_pts_ns)
        buffer = self.Gst.Buffer.new_allocate(None, len(frame.payload), None)
        _require(buffer is not None, "DeepStream GstBuffer allocation failed")
        _require(buffer.fill(0, frame.payload) == len(frame.payload), "DeepStream GstBuffer fill was truncated")
        buffer.pts, buffer.dts, buffer.duration = deepstream_buffer_timestamps(
            frame,
            source_duration_ns=self.source_duration_ns,
            clock_time_none=self.Gst.CLOCK_TIME_NONE,
        )
        if frame.keyframe:
            buffer.unset_flags(self.Gst.BufferFlags.DELTA_UNIT)
        else:
            buffer.set_flags(self.Gst.BufferFlags.DELTA_UNIT)
        with self._pending_lock:
            pending = self._pending.get(frame.transport_pts_ns)
            _require(
                pending is not None and pending.frame is frame
                and pending.decode_submit_start_ns is None,
                "DeepStream NVDEC submission identity drifted",
            )
            pending.decode_submit_start_ns = time.time_ns()
        result = self.appsrc.emit("push-buffer", buffer)
        _require(result == self.Gst.FlowReturn.OK, f"DeepStream appsrc push failed: {result}")

    def finish(self, *, timeout_s: float) -> None:
        _require(timeout_s > 0, "DeepStream drain timeout must be positive")
        result = self.appsrc.emit("end-of-stream")
        _require(result == self.Gst.FlowReturn.OK, f"DeepStream appsrc EOS failed: {result}")
        deadline = time.monotonic() + timeout_s
        while not self._terminal_eos_seen.is_set():
            self.raise_callback_error()
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "DeepStream pipeline EOS timed out")
            self._terminal_eos_seen.wait(min(0.05, remaining))
        with self._terminal_eos_lock:
            _require(
                self._terminal_eos_branches == set(self.graph.branches),
                "DeepStream did not observe EOS at every physical branch terminal",
            )
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

    @staticmethod
    def _sha256_regular_file(path: Path, label: str) -> tuple[Path, str]:
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise DeepStreamSdkRuntimeError(f"{label} runtime artifact cannot be resolved") from exc
        _require(resolved.is_file(), f"{label} runtime artifact is not a regular file")
        digest = hashlib.sha256()
        try:
            with resolved.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise DeepStreamSdkRuntimeError(f"{label} runtime artifact cannot be hashed") from exc
        return resolved, digest.hexdigest()

    def _plugin_artifact(self, element_key: str, role: str) -> tuple[dict[str, str], str]:
        element = self._stage_elements[element_key]
        factory = element.get_factory()
        _require(factory is not None, f"DeepStream {element_key} has no loaded factory")
        factory_name = str(factory.get_name()).strip()
        _require(bool(factory_name), f"DeepStream {element_key} factory name is empty")
        plugin = factory.get_plugin()
        _require(plugin is not None, f"DeepStream {factory_name} has no loaded plugin")
        filename = str(plugin.get_filename() or "").strip()
        version = str(plugin.get_version() or "").strip()
        _require(bool(filename) and bool(version), f"DeepStream {factory_name} plugin identity is incomplete")
        _, sha256 = self._sha256_regular_file(Path(filename), f"DeepStream {factory_name} plugin")
        return {
            "role": role,
            "kind": "plugin",
            "logical_name": factory_name,
            "sha256": sha256,
        }, f"{factory_name}-{version}"

    @staticmethod
    def _negotiated_output(pad: Any, label: str) -> tuple[dict[str, Any], str]:
        caps = pad.get_current_caps()
        _require(caps is not None and not caps.is_empty() and caps.get_size() == 1, f"DeepStream {label} has no single negotiated caps")
        structure = caps.get_structure(0)
        _require(structure is not None, f"DeepStream {label} caps structure is unavailable")
        media_type = str(structure.get_name() or "").strip()
        pixel_format = str(structure.get_string("format") or "").strip()
        try:
            width = int(structure.get_value("width"))
            height = int(structure.get_value("height"))
        except (TypeError, ValueError) as exc:
            raise DeepStreamSdkRuntimeError(f"DeepStream {label} caps dimensions are invalid") from exc
        _require(media_type == "video/x-raw" and bool(pixel_format), f"DeepStream {label} caps identity drifted")
        _require(width > 0 and height > 0, f"DeepStream {label} caps dimensions are non-positive")
        caps_text = str(caps.to_string()).strip()
        _require(bool(caps_text), f"DeepStream {label} caps serialization is empty")
        if "memory:NVMM" in caps_text:
            media_type += "(memory:NVMM)"
        output_format = "rgb24" if pixel_format == "RGB" else pixel_format.lower()
        return {
            "media_type": media_type,
            "format": output_format,
            "shape": [height, width, 3],
        }, caps_text

    def runtime_stage_contract_rows(
        self,
        *,
        run_id: str,
        worker_id: str,
        nvds_meta_library: Path,
    ) -> list[dict[str, Any]]:
        """Inspect the loaded SDK graph and bind its artifacts/configuration to this PID."""

        _require(self.decoded_seen.is_set() and self.preprocessed_seen.is_set(), "DeepStream stage contracts require observed decode and preprocess callbacks")
        hostname = socket.gethostname().strip()
        _require(bool(hostname), "DeepStream runtime hostname is empty")
        execution_domain = f"{hostname}:pid-{os.getpid()}:worker-{worker_id}"
        decode_output, decode_caps = self._negotiated_output(
            self._stage_elements["stream_mux"].get_static_pad("src"), "decode output",
        )
        preprocess_output, preprocess_caps = self._negotiated_output(
            self._stage_elements["caps_filter"].get_static_pad("src"), "preprocess output",
        )
        decode_artifacts: list[dict[str, str]] = []
        preprocess_artifacts: list[dict[str, str]] = []
        versions: list[str] = []
        for key, role in (("parser", "codec_parser"), ("decoder", "decoder"), ("stream_mux", "stream_mux")):
            artifact, version = self._plugin_artifact(key, role)
            decode_artifacts.append(artifact)
            versions.append(version)
        for key, role in (("format_converter", "format_converter"), ("caps_filter", "caps_filter")):
            artifact, version = self._plugin_artifact(key, role)
            preprocess_artifacts.append(artifact)
            versions.append(version)
        stage_host, stage_host_sha = self._sha256_regular_file(Path(__file__), "DeepStream SDK worker")
        meta_bridge, meta_bridge_sha = self._sha256_regular_file(nvds_meta_library, "DeepStream NvDs meta bridge")
        common_artifacts = [
            {"role": "stage_host", "kind": "executable", "logical_name": stage_host.name, "sha256": stage_host_sha},
            {"role": "metadata_bridge", "kind": "shared_library", "logical_name": meta_bridge.name, "sha256": meta_bridge_sha},
        ]
        gst_version = ".".join(str(value) for value in self.Gst.version()[:3])
        implementation_version = "GStreamer-" + gst_version + "/" + "/".join(sorted(set(versions)))
        return build_deepstream_stage_contract_rows(
            run_id=run_id,
            worker_id=worker_id,
            topology_kind=self.graph.topology_kind,
            branches=self.graph.branches,
            execution_domain=execution_domain,
            implementation_version=implementation_version,
            decode_config={
                "backend": "deepstream",
                "codec": self.graph.codec,
                "decoder_factory": "nvv4l2decoder",
                "decoder_gpu_id": self.decoder_gpu_id,
                "output_caps": decode_caps,
                "parser_factory": f"{self.graph.codec}parse",
                "pipeline_role": "checkpoint",
                "software_fallback": "prohibited",
                "stream_mux_batch_size": 1,
                "stream_mux_factory": "nvstreammux",
            },
            preprocess_config={
                "backend": "deepstream",
                "converter_factory": "nvvideoconvert",
                "output_caps": preprocess_caps,
                "pipeline_role": "checkpoint",
                "stream_mux_height": int(preprocess_output["shape"][0]),
                "stream_mux_width": int(preprocess_output["shape"][1]),
            },
            artifacts_by_stage={
                "decode": [*common_artifacts, *decode_artifacts],
                "preprocess": [*common_artifacts, *preprocess_artifacts],
            },
            decode_output=decode_output,
            preprocess_output=preprocess_output,
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
    source_duration_ns = _integer_environment(SOURCE_DURATION_NS_ENV)
    _require(source_duration_ns > 0, "DeepStream source duration is zero")
    _require(args.topology_kind == topology_kind, "DeepStream topology differs between argv and coordinator")
    _require(args.stream_id == stream_id, "DeepStream stream differs between argv and coordinator")
    output_dir = Path(args.output_dir)
    _require(output_dir.is_absolute(), "DeepStream worker output directory must be absolute")
    _require(output_dir.is_dir() and not output_dir.is_symlink(), "DeepStream worker output directory is invalid")
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
        "source_duration_ns": source_duration_ns,
        "claim_status": "native_sdk_runtime_requires_external_acceptance",
    }
    from checkpoint_deepstream_resource_runtime_v3 import (
        DeepStreamNativeResourceRecorderV3,
    )

    resource_recorder = DeepStreamNativeResourceRecorderV3(
        output_dir=output_dir,
        run_id=run_id,
        worker_id=worker_id,
        stream_id=stream_id,
        topology_kind=topology_kind,
        branches=branches,
        decoder_gpu_index=graph.decoder_gpu_id,
    )
    context["resource_recorder"] = resource_recorder
    callbacks = None
    try:
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
            source_duration_ns=source_duration_ns,
            resource_recorder=resource_recorder,
            decoder_gpu_id=graph.decoder_gpu_id,
        )
    except BaseException:
        resource_recorder.close()
        policy.close()
        close_callbacks = getattr(callbacks, "close", None) if callbacks is not None else None
        if callable(close_callbacks):
            close_callbacks()
        raise
    stop_event = threading.Event()
    stop_timestamp: list[int] = []
    stop_drain_deadline: list[float] = []

    def receive_stop() -> None:
        try:
            stop_timestamp.append(lifecycle.await_stop())
            stop_drain_deadline.append(time.monotonic() + args.drain_timeout_s)
        except BaseException as exc:
            pipeline._record_error(exc)
        finally:
            stop_event.set()

    lifecycle.ready()
    window = lifecycle.await_start()
    _sleep_until_monotonic_ns(window.common_start_monotonic_ns)
    pipeline.start()
    lifecycle.started()
    stop_thread = threading.Thread(target=receive_stop, name=f"deepstream-stop-{worker_id}", daemon=True)
    stop_thread.start()
    decoder_status_sent = False
    selector = selectors.DefaultSelector()
    selector.register(admission_fd, selectors.EVENT_READ)
    frame_count = 0
    resource_paths: dict[str, Path] = {}
    try:
        # STOP closes source admission, but already admitted access units can
        # still be buffered in the independent consumer pipes. Every worker
        # must consume through source EOF before declaring its graph drained.
        while True:
            pipeline.raise_callback_error()
            if stop_event.is_set():
                _require(stop_timestamp and stop_drain_deadline, "DeepStream STOP timestamp was not received")
                _require(
                    time.monotonic() < stop_drain_deadline[0],
                    "DeepStream admission pipe drain timed out",
                )
            if pipeline.decoded_seen.is_set() and not decoder_status_sent:
                lifecycle.decoder_placement_verified()
                decoder_status_sent = True
            ready = selector.select(timeout=0.05)
            if not ready:
                continue
            frame = read_admission_transport_frame(admission_fd)
            if frame is None:
                _await_coordinated_stop_after_admission_eof(
                    stop_event=stop_event,
                    stop_thread=stop_thread,
                    stop_timestamp=stop_timestamp,
                )
                break
            pipeline.push(frame)
            frame_count += 1
        pipeline.raise_callback_error()
        _require(stop_timestamp, "DeepStream STOP timestamp was not received")
        lifecycle.admission_stopped(stop_timestamp[0])
        remaining_drain_s = stop_drain_deadline[0] - time.monotonic()
        _require(remaining_drain_s > 0, "DeepStream admission pipe drain timed out")
        pipeline.finish(timeout_s=remaining_drain_s)
        if pipeline.decoded_seen.is_set() and not decoder_status_sent:
            lifecycle.decoder_placement_verified()
            decoder_status_sent = True
        _require(decoder_status_sent, "DeepStream NVDEC placement was never observed")
        stage_contract_path = write_deepstream_stage_contracts(
            output_dir,
            pipeline.runtime_stage_contract_rows(
                run_id=run_id,
                worker_id=worker_id,
                nvds_meta_library=args.nvds_meta_library,
            ),
        )
        resource_paths = resource_recorder.close()
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
        resource_paths = resource_recorder.close()
        stop_thread.join(timeout=2)
    return {
        "schema_version": 1,
        "artifact_kind": "deepstream_sdk_worker_exit",
        "claim_status": "native_runtime_exit_not_publication_acceptance",
        "worker_id": worker_id,
        "physical_graph_count": 1,
        "decoded_process_count": 1,
        "admission_frames": frame_count,
        "stage_contract_runtime_path": str(stage_contract_path),
        "resource_interval_runtime_path": str(resource_paths["resource_intervals"]),
        "fanout_work_runtime_path": (
            str(resource_paths["fanout_work_counters"])
            if "fanout_work_counters" in resource_paths
            else None
        ),
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
        source_duration_ns=frame.duration_ns,
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
    run_parser.add_argument("--output-dir", type=Path, required=True)
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
        if args.command == "run":
            # The coordinator owns worker receipts through lifecycle/evidence
            # channels.  fd 1 is reserved for the exact native nvstreammux EOS
            # audit captured by the enclosing publication runtime.
            run_fd_worker(args)
        else:
            _print_json(run_engineering_pilot(args))
        return 0
    except DeepStreamSdkRuntimeError as exc:
        print(f"deepstream sdk runtime blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
