#!/usr/bin/env python3
"""Fail-closed DeepStream callback bridge for checkpoint runtime protocols.

The bridge is production-side protocol logic, not a DeepStream runtime binary.
It accepts an already admitted compressed access unit, requires an exact
AU-to-``NvDsFrameMeta`` identity record, preserves the baseline/shared causal
shape, executes only an attested analytics endpoint selected by the native
policy path, and emits direct-runtime v2 events plus v3 branch terminals.

Synthetic use of this module remains contract-test evidence.  Native evidence
requires the future DeepStream SDK adapter to build identity records directly
inside pad callbacks and to write the emitted JSON to its inherited event FD.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from analytics_execution_protocol import (
    DTYPE_BYTES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_DIMENSIONS,
    MAX_TENSOR_BYTES,
    ProtocolError,
    validate_inference_request,
)
from analytics_execution_worker import (
    validate_inference_response,
    validate_worker_capability,
)
from analytics_execution_endpoint import terminal_detector_identity
BRIDGE_SCHEMA_VERSION = 1
BRIDGE_IMPLEMENTATION_STATUS = (
    "protocol_bridge_sdk_callback_adapter_source_implemented_not_kpp_pair_piloted"
)
NVDS_IDENTITY_KIND = "deepstream_nvds_frame_identity"
POLICY_RPC_SCHEMA_VERSION = 1
RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION = 2
RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL = 3
INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
ANALYTICS_BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
RESOURCES = ("cpu", "gpu")
RESOURCE_ENGINE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_NVDS_IDENTITY_FIELDS = {
    "schema_version",
    "artifact_kind",
    "admission_id",
    "input_frame_key",
    "stream_id",
    "frame_id",
    "transport_pts_ns",
    "payload_sha256",
    "nvds_source_id",
    "nvds_frame_num",
    "nvds_buf_pts_ns",
    "mux_gst_buffer_pts_ns",
    "decoder_factory",
    "decoder_gpu_id",
}
_TENSOR_FIELDS = {
    "name",
    "dtype",
    "layout",
    "shape",
    "byte_length",
    "sha256",
    "preprocessing_contract_sha256",
}
_DECISION_RESPONSE_FIELDS = {
    "schema_version",
    "message_type",
    "decision_id",
    "decision_seq",
    "selected_resource",
    "selected_implementation_id",
    "emitter_id",
    "emitter_sha256",
}
_PATH_ACK_FIELDS = {
    "schema_version",
    "message_type",
    "decision_id",
    "accepted",
}
_TERMINAL_ACK_FIELDS = _PATH_ACK_FIELDS


class DeepStreamProtocolBridgeError(RuntimeError):
    """A callback, policy, analytics, or runtime-event binding failed."""


class AnalyticsExecutionClient(Protocol):
    def infer(
        self,
        request: Mapping[str, Any],
        tensor: bytes | bytearray | memoryview,
    ) -> tuple[Mapping[str, Any], bytes]: ...


PolicyExchange = Callable[[dict[str, Any]], Mapping[str, Any]]
EventSink = Callable[[str], None]


@dataclass(frozen=True)
class DeepStreamExecutionEndpoint:
    """One branch/resource endpoint already handshaken by ExecutionClient."""

    resource: str
    implementation_id: str
    capability: Mapping[str, Any]
    client: AnalyticsExecutionClient


@dataclass(frozen=True)
class DeepStreamBranchExecutionResult:
    selected_resource: str
    decision_id: str
    request_id: str
    detector: str
    backend: str
    output_sha256: str
    output_size_bytes: int
    response: dict[str, Any]


@dataclass
class _FrameState:
    admission: "_AdmissionRecord"
    frame_id: int
    canonical_trace_id: str
    trace_id: str
    source_event_id: str
    decode_event_id: str | None = None
    preprocess_event_id: str | None = None
    fanout_event_ids: dict[str, str] = field(default_factory=dict)
    tensor_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    executing_branches: set[str] = field(default_factory=set)
    terminal_branches: set[str] = field(default_factory=set)
    failed_branches: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _AdmissionRecord:
    sequence: int
    run_id: str
    stream_id: int
    admission_id: str
    input_frame_key: str
    access_unit_pts_ns: int
    transport_pts_ns: int
    payload_sha256: str
    payload_size_bytes: int
    admission_timestamp_ms: int


_ADMISSION_JSON_FIELDS = {
    "protocol_version",
    "source_process_id",
    "sequence",
    "run_id",
    "dataset_id",
    "stream_id",
    "admission_id",
    "input_frame_key",
    "source_sha256",
    "source_cycle",
    "access_unit_pts_ns",
    "payload_sha256",
    "payload_size_bytes",
    "schedule_offset_ns",
    "admission_timestamp_ms",
    "event_provenance",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamProtocolBridgeError(message)


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    result = dict(value)
    missing = sorted(fields - set(result))
    extra = sorted(set(result) - fields)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if extra:
        details.append("extra=" + ",".join(extra))
    _require(not details, f"{label} fields drifted ({'; '.join(details)})")
    return result


def _text(value: Any, label: str) -> str:
    result = str(value).strip()
    _require(bool(result), f"{label} must be non-empty")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int, f"{label} must be an exact integer")
    result = int(value)
    _require(result >= minimum, f"{label} must be at least {minimum}")
    return result


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    _require(not isinstance(value, bool), f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DeepStreamProtocolBridgeError(f"{label} must be numeric") from exc
    _require(math.isfinite(result), f"{label} must be finite")
    if positive:
        _require(result > 0, f"{label} must be positive")
    return result


def _sha256(value: Any, label: str) -> str:
    result = _text(value, label).lower()
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be lowercase SHA-256")
    return result


def _stable_id(value: Any, label: str) -> str:
    result = _text(value, label)
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is not protocol-safe")
    return result


def _canonical_line(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DeepStreamProtocolBridgeError("runtime event is not canonical JSON") from exc


def analytics_backend_identity(capability: Mapping[str, Any]) -> str:
    """Derive the terminal backend from attested native execution fields."""

    try:
        checked = validate_worker_capability(capability)
    except ProtocolError as exc:
        raise DeepStreamProtocolBridgeError(
            f"analytics execution capability is invalid: {exc}"
        ) from exc
    return (
        f"analytics-execution:{checked['engine']};runtime={checked['runtime_name']};"
        f"native_api={checked['native_inference_api']};"
        f"device={checked['device_api']}:{checked['device_id']}"
    )


def _validate_tensor_spec(value: Any) -> dict[str, Any]:
    tensor = _exact(value, _TENSOR_FIELDS, "DeepStream analytics tensor")
    dtype = str(tensor["dtype"])
    layout = str(tensor["layout"])
    _require(dtype in DTYPE_BYTES, "DeepStream analytics tensor dtype is invalid")
    _require(layout in {"NCHW", "NHWC"}, "DeepStream analytics tensor layout is invalid")
    shape = tensor["shape"]
    _require(
        type(shape) is list
        and 1 <= len(shape) <= MAX_DIMENSIONS
        and all(type(value) is int and 0 < value <= 1_000_000 for value in shape),
        "DeepStream analytics tensor shape is invalid",
    )
    expected_bytes = math.prod(shape) * DTYPE_BYTES[dtype]
    byte_length = _integer(tensor["byte_length"], "DeepStream tensor byte_length", minimum=1)
    _require(byte_length == expected_bytes, "DeepStream tensor byte length differs from shape")
    _require(byte_length <= MAX_TENSOR_BYTES, "DeepStream tensor exceeds protocol maximum")
    return {
        "name": _text(tensor["name"], "DeepStream tensor name"),
        "dtype": dtype,
        "layout": layout,
        "shape": list(shape),
        "byte_length": byte_length,
        "sha256": _sha256(tensor["sha256"], "DeepStream tensor SHA-256"),
        "preprocessing_contract_sha256": _sha256(
            tensor["preprocessing_contract_sha256"],
            "DeepStream preprocessing contract SHA-256",
        ),
    }


class DeepStreamProtocolBridge:
    """Stateful callback bridge for one baseline branch or one shared graph."""

    def __init__(
        self,
        *,
        run_id: str,
        arm_id: str,
        worker_id: str,
        topology_kind: str,
        stream_id: int,
        branch_id: str | None,
        event_sink: EventSink,
        policy_exchange: PolicyExchange,
        analytics_endpoints: Mapping[
            str, Mapping[str, DeepStreamExecutionEndpoint]
        ],
        resource_recorder: Any | None = None,
        clock_ms: Callable[[], float] | None = None,
        nvds_source_id: int = 0,
    ) -> None:
        self.run_id = _stable_id(run_id, "DeepStream run_id")
        self.arm_id = _stable_id(arm_id, "DeepStream arm_id")
        self.worker_id = _text(worker_id, "DeepStream worker_id")
        self.stream_id = _integer(stream_id, "DeepStream stream_id")
        # DeepStream's single-source graph uses pad 0; Savant explicitly binds
        # its native mux pad to the logical stream. Never relabel observed meta.
        self.nvds_source_id = _integer(nvds_source_id, "expected native NvDs source_id")
        _require(
            topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG},
            "DeepStream topology kind is unsupported",
        )
        self.topology_kind = topology_kind
        if topology_kind == INDEPENDENT_PROCESSES:
            _require(branch_id in ANALYTICS_BRANCHES, "baseline bridge requires one frozen branch")
            expected_branches = {str(branch_id)}
            self.branch_id = str(branch_id)
        else:
            _require(branch_id is None, "shared bridge cannot bind one branch")
            expected_branches = set(ANALYTICS_BRANCHES)
            self.branch_id = None
        _require(callable(event_sink), "DeepStream event sink is not callable")
        _require(callable(policy_exchange), "DeepStream policy exchange is not callable")
        self._event_sink = event_sink
        self._policy_exchange = policy_exchange
        if resource_recorder is not None:
            _require(
                callable(getattr(resource_recorder, "record_analytics_transfers", None)),
                "DeepStream resource recorder lacks record_analytics_transfers()",
            )
        self._resource_recorder = resource_recorder
        self._clock_ms = clock_ms or (lambda: time.time_ns() / 1_000_000.0)
        self._lock = threading.RLock()
        self._sequence = 0
        self._last_event_timestamp_ms = -1
        self._frames: dict[str, _FrameState] = {}
        self._nvds_frame_numbers: set[int] = set()
        self._endpoints: dict[
            str, dict[str, tuple[DeepStreamExecutionEndpoint, dict[str, Any]]]
        ] = {}

        _require(
            isinstance(analytics_endpoints, Mapping)
            and set(analytics_endpoints) == expected_branches,
            "DeepStream analytics endpoint branch set does not match its topology process",
        )
        for branch in sorted(expected_branches):
            raw_resources = analytics_endpoints[branch]
            _require(
                isinstance(raw_resources, Mapping) and set(raw_resources) == set(RESOURCES),
                f"{branch}: DeepStream requires exact CPU and GPU analytics endpoints",
            )
            checked_resources: dict[
                str, tuple[DeepStreamExecutionEndpoint, dict[str, Any]]
            ] = {}
            for resource in RESOURCES:
                endpoint = raw_resources[resource]
                _require(
                    isinstance(endpoint, DeepStreamExecutionEndpoint),
                    f"{branch}/{resource}: invalid DeepStream execution endpoint",
                )
                _require(endpoint.resource == resource, f"{branch}/{resource}: resource binding drifted")
                _text(endpoint.implementation_id, f"{branch}/{resource}: implementation_id")
                _require(
                    callable(getattr(endpoint.client, "infer", None)),
                    f"{branch}/{resource}: analytics client lacks infer()",
                )
                try:
                    checked = validate_worker_capability(endpoint.capability)
                except ProtocolError as exc:
                    raise DeepStreamProtocolBridgeError(
                        f"{branch}/{resource}: analytics execution capability is invalid: {exc}"
                    ) from exc
                _require(checked["branch"] == branch, f"{branch}/{resource}: capability branch mismatch")
                _require(
                    checked["engine"] == RESOURCE_ENGINE[resource],
                    f"{branch}/{resource}: selected resource does not match native engine",
                )
                checked_resources[resource] = (endpoint, checked)
            cpu = checked_resources["cpu"][1]
            gpu = checked_resources["gpu"][1]
            for field_name in (
                "model_id",
                "source_model_sha256",
                "preprocessing_contract_sha256",
                "output_contract_sha256",
            ):
                _require(
                    cpu[field_name] == gpu[field_name],
                    f"{branch}: CPU/GPU model semantics differ at {field_name}",
                )
            self._endpoints[branch] = checked_resources

    def _clock_value(self, label: str) -> float:
        return _number(self._clock_ms(), label, positive=True)

    def _runtime_timestamp(self, observed_ms: float | int | None, label: str) -> int:
        value = self._clock_value(label) if observed_ms is None else _number(observed_ms, label)
        _require(value >= 0, f"{label} must be non-negative")
        timestamp = int(math.ceil(value))
        # Callback observations are captured before this bridge acquires its
        # serialization lock.  A later callback can therefore serialize first,
        # and an analytics RPC can finish after newer admissions were emitted.
        # The native RPC/resource records retain the precise stage timings; the
        # runtime event timestamp is the monotonic serialization clock.
        return max(timestamp, self._last_event_timestamp_ms)

    @staticmethod
    def _execution_id(state: _FrameState, suffix: str) -> str:
        return f"{state.canonical_trace_id}:{suffix}"

    def _emit(
        self,
        state: _FrameState,
        *,
        event_kind: str,
        stage: str,
        branch: str,
        execution_id: str,
        parents: list[str],
        observed_timestamp_ms: float | int | None = None,
        terminal: Mapping[str, Any] | None = None,
    ) -> int:
        timestamp_ms = self._runtime_timestamp(
            observed_timestamp_ms, "DeepStream runtime event timestamp_ms"
        )
        protocol_version = (
            RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL
            if terminal is not None
            else RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION
        )
        event: dict[str, Any] = {
            "protocol_version": protocol_version,
            "worker_id": self.worker_id,
            "sequence": self._sequence + 1,
            "run_id": self.run_id,
            "trace_id": state.trace_id,
            "stream_id": self.stream_id,
            "frame_id": state.frame_id,
            "input_frame_key": state.admission.input_frame_key,
            "topology_kind": self.topology_kind,
            "event_kind": event_kind,
            "stage": stage,
            "branch_id": branch,
            "execution_id": execution_id,
            "parent_execution_ids": list(parents),
            "timestamp_ms": timestamp_ms,
            "admission_id": state.admission.admission_id,
            "payload_sha256": state.admission.payload_sha256,
        }
        if terminal is not None:
            event.update(
                {
                    "terminal_reason": _text(
                        terminal.get("terminal_reason"), "DeepStream terminal reason"
                    ),
                    "objects": _integer(
                        terminal.get("objects"), "DeepStream terminal objects"
                    ),
                    "detector": _text(terminal.get("detector"), "DeepStream detector"),
                    "backend": _text(terminal.get("backend"), "DeepStream backend"),
                }
            )
        line = _canonical_line(event)
        self._event_sink(line)
        self._sequence += 1
        self._last_event_timestamp_ms = timestamp_ms
        return timestamp_ms

    def _frame(self, input_frame_key: str) -> _FrameState:
        key = _text(input_frame_key, "DeepStream input_frame_key")
        state = self._frames.get(key)
        _require(state is not None, "DeepStream callback references an unadmitted frame")
        return state

    def admit_access_unit(
        self,
        admission_json: str,
        *,
        observed_timestamp_ms: float | int | None = None,
    ) -> None:
        """Consume one direct-admission JSON record before appsrc push."""

        try:
            raw = json.loads(admission_json)
        except json.JSONDecodeError as exc:
            raise DeepStreamProtocolBridgeError(
                "DeepStream access-unit admission is not JSON"
            ) from exc
        admission = _exact(raw, _ADMISSION_JSON_FIELDS, "DeepStream admission event")
        _require(admission["protocol_version"] == 1, "DeepStream admission protocol drifted")
        _require(
            admission["event_provenance"] == "native_common_source_coordinator",
            "DeepStream admission provenance is not native",
        )
        sequence = _integer(admission["sequence"], "DeepStream admission sequence", minimum=1)
        run_id = _text(admission["run_id"], "DeepStream admission run_id")
        stream_id = _integer(admission["stream_id"], "DeepStream admission stream_id")
        admission_id = _text(admission["admission_id"], "DeepStream admission_id")
        _require(
            admission_id == f"{run_id}:{stream_id}:admission:{sequence}",
            "DeepStream admission_id does not bind run, stream, and sequence",
        )
        source_sha256 = _sha256(admission["source_sha256"], "DeepStream source SHA-256")
        dataset_id = _text(admission["dataset_id"], "DeepStream dataset_id")
        source_cycle = _integer(admission["source_cycle"], "DeepStream source_cycle")
        access_pts = _integer(admission["access_unit_pts_ns"], "DeepStream access-unit PTS")
        input_frame_key = _text(admission["input_frame_key"], "DeepStream input_frame_key")
        _require(
            input_frame_key
            == f"{dataset_id}:{stream_id}:{source_sha256}:{source_cycle}:{access_pts}",
            "DeepStream input_frame_key does not bind the admitted access unit",
        )
        admitted = _AdmissionRecord(
            sequence=sequence,
            run_id=run_id,
            stream_id=stream_id,
            admission_id=admission_id,
            input_frame_key=input_frame_key,
            access_unit_pts_ns=access_pts,
            transport_pts_ns=access_pts,
            payload_sha256=_sha256(
                admission["payload_sha256"], "DeepStream admission payload SHA-256"
            ),
            payload_size_bytes=_integer(
                admission["payload_size_bytes"],
                "DeepStream admission payload_size_bytes",
                minimum=1,
            ),
            admission_timestamp_ms=_integer(
                admission["admission_timestamp_ms"],
                "DeepStream admission timestamp_ms",
            ),
        )
        self._admit_record(admitted, observed_timestamp_ms=observed_timestamp_ms)

    def admit_transport_frame(
        self,
        frame: Any,
        *,
        observed_timestamp_ms: float | int | None = None,
    ) -> None:
        """Admit one byte-verified VASTAU01 frame received on the inherited FD."""

        sequence = _integer(getattr(frame, "sequence", None), "DeepStream transport sequence", minimum=1)
        access_pts = _integer(
            getattr(frame, "access_unit_pts_ns", None),
            "DeepStream transport access-unit PTS",
        )
        transport_pts = _integer(
            getattr(frame, "transport_pts_ns", None),
            "DeepStream transport PTS",
        )
        _require(transport_pts >= access_pts, "DeepStream transport PTS precedes access-unit PTS")
        admission_id = _text(getattr(frame, "admission_id", None), "DeepStream transport admission_id")
        _require(
            admission_id == f"{self.run_id}:{self.stream_id}:admission:{sequence}",
            "DeepStream transport admission_id does not bind this worker",
        )
        payload = bytes(getattr(frame, "payload", b""))
        payload_sha256 = _sha256(
            getattr(frame, "payload_sha256", None),
            "DeepStream transport payload SHA-256",
        )
        _require(bool(payload), "DeepStream transport payload is empty")
        _require(
            hashlib.sha256(payload).hexdigest() == payload_sha256,
            "DeepStream transport payload digest mismatch",
        )
        timestamp = (
            self._clock_value("DeepStream transport admission timestamp")
            if observed_timestamp_ms is None
            else _number(observed_timestamp_ms, "DeepStream transport admission timestamp")
        )
        admitted = _AdmissionRecord(
            sequence=sequence,
            run_id=self.run_id,
            stream_id=self.stream_id,
            admission_id=admission_id,
            input_frame_key=_text(
                getattr(frame, "input_frame_key", None),
                "DeepStream transport input_frame_key",
            ),
            access_unit_pts_ns=access_pts,
            transport_pts_ns=transport_pts,
            payload_sha256=payload_sha256,
            payload_size_bytes=len(payload),
            admission_timestamp_ms=int(math.floor(timestamp)),
        )
        self._admit_record(admitted, observed_timestamp_ms=timestamp)

    def _admit_record(
        self,
        admitted: _AdmissionRecord,
        *,
        observed_timestamp_ms: float | int | None,
    ) -> None:
        _require(admitted.run_id == self.run_id, "DeepStream admission run_id mismatch")
        _require(admitted.stream_id == self.stream_id, "DeepStream admission stream mismatch")
        with self._lock:
            _require(
                admitted.input_frame_key not in self._frames,
                "DeepStream frame was admitted twice",
            )
            frame_id = admitted.sequence - 1
            canonical_trace_id = f"{self.run_id}:{self.stream_id}:{frame_id}"
            trace_id = f"{canonical_trace_id}:{self.worker_id}"
            source_id = f"{trace_id}:source"
            state = _FrameState(
                admission=admitted,
                frame_id=frame_id,
                canonical_trace_id=canonical_trace_id,
                trace_id=trace_id,
                source_event_id=source_id,
            )
            timestamp = observed_timestamp_ms
            if timestamp is None:
                timestamp = self._clock_value("DeepStream source callback timestamp")
            _require(
                float(timestamp) >= admitted.admission_timestamp_ms,
                "DeepStream source callback precedes direct admission",
            )
            branch = self.branch_id or "shared"
            self._emit(
                state,
                event_kind="source_read",
                stage="source",
                branch=branch,
                execution_id=source_id,
                parents=[],
                observed_timestamp_ms=timestamp,
            )
            self._frames[admitted.input_frame_key] = state

    def _validate_nvds_identity(self, value: Any) -> _FrameState:
        identity = _exact(value, _NVDS_IDENTITY_FIELDS, "DeepStream NvDs frame identity")
        _require(
            _integer(identity["schema_version"], "NvDs identity schema_version", minimum=1)
            == BRIDGE_SCHEMA_VERSION,
            "NvDs identity schema drifted",
        )
        _require(identity["artifact_kind"] == NVDS_IDENTITY_KIND, "NvDs identity kind drifted")
        state = self._frame(_text(identity["input_frame_key"], "NvDs input_frame_key"))
        admitted = state.admission
        normalized = {
            "admission_id": _text(identity["admission_id"], "NvDs admission_id"),
            "stream_id": _integer(identity["stream_id"], "NvDs stream_id"),
            "frame_id": _integer(identity["frame_id"], "NvDs frame_id"),
            "transport_pts_ns": _integer(
                identity["transport_pts_ns"], "NvDs transport_pts_ns"
            ),
            "payload_sha256": _sha256(identity["payload_sha256"], "NvDs payload SHA-256"),
            "nvds_source_id": _integer(identity["nvds_source_id"], "NvDs source_id"),
            "nvds_frame_num": _integer(identity["nvds_frame_num"], "NvDs frame_num"),
            "nvds_buf_pts_ns": _integer(identity["nvds_buf_pts_ns"], "NvDs buf_pts_ns"),
            "mux_gst_buffer_pts_ns": _integer(
                identity["mux_gst_buffer_pts_ns"], "mux GstBuffer PTS"
            ),
            "decoder_factory": _text(identity["decoder_factory"], "NvDs decoder factory"),
            "decoder_gpu_id": _integer(identity["decoder_gpu_id"], "NvDs decoder gpu_id"),
        }
        expected = {
            "admission_id": admitted.admission_id,
            "stream_id": self.stream_id,
            "frame_id": state.frame_id,
            "transport_pts_ns": admitted.transport_pts_ns,
            "payload_sha256": admitted.payload_sha256,
            "nvds_source_id": self.nvds_source_id,
            "nvds_buf_pts_ns": admitted.transport_pts_ns,
            "decoder_factory": "nvv4l2decoder",
            "decoder_gpu_id": 0,
        }
        for field_name, expected_value in expected.items():
            _require(
                normalized[field_name] == expected_value,
                f"DeepStream NvDs {field_name} does not bind the admitted nvv4l2decoder frame",
            )
        native_frame_num = normalized["nvds_frame_num"]
        if state.decode_event_id is None:
            _require(
                native_frame_num not in self._nvds_frame_numbers,
                "DeepStream NvDs frame_num was reused by decoded output",
            )
            self._nvds_frame_numbers.add(native_frame_num)
        return state

    def observe_decoded_frame(
        self,
        nvds_identity: Mapping[str, Any],
        *,
        observed_timestamp_ms: float | int | None = None,
    ) -> None:
        with self._lock:
            state = self._validate_nvds_identity(nvds_identity)
            _require(state.decode_event_id is None, "DeepStream decode callback was duplicated")
            branch = self.branch_id or "shared"
            stage = f"decode_{branch}" if self.branch_id is not None else "decode"
            event_id = self._execution_id(state, f"{branch}:decode")
            self._emit(
                state,
                event_kind="stage_complete",
                stage=stage,
                branch=branch,
                execution_id=event_id,
                parents=[state.source_event_id],
                observed_timestamp_ms=observed_timestamp_ms,
            )
            state.decode_event_id = event_id

    def observe_preprocessed_frame(
        self,
        nvds_identity: Mapping[str, Any],
        *,
        tensor_spec: Mapping[str, Any] | None = None,
        observed_timestamp_ms: float | int | None = None,
    ) -> None:
        with self._lock:
            state = self._validate_nvds_identity(nvds_identity)
            _require(state.decode_event_id is not None, "DeepStream preprocess precedes decode")
            _require(state.preprocess_event_id is None, "DeepStream preprocess callback was duplicated")
            branch = self.branch_id or "shared"
            if self.branch_id is not None:
                if tensor_spec is not None:
                    state.tensor_specs[branch] = _validate_tensor_spec(tensor_spec)
                stage = f"preprocess_{branch}"
            else:
                _require(tensor_spec is None, "shared prefix cannot relabel one branch tensor")
                stage = "preprocess"
            event_id = self._execution_id(state, f"{branch}:preprocess")
            self._emit(
                state,
                event_kind="stage_complete",
                stage=stage,
                branch=branch,
                execution_id=event_id,
                parents=[state.decode_event_id],
                observed_timestamp_ms=observed_timestamp_ms,
            )
            state.preprocess_event_id = event_id

    def observe_fanout(
        self,
        nvds_identity: Mapping[str, Any],
        *,
        branch: str,
        tensor_spec: Mapping[str, Any] | None = None,
        observed_timestamp_ms: float | int | None = None,
    ) -> int:
        with self._lock:
            _require(self.topology_kind == SHARED_VIDEO_DAG, "baseline bridge cannot emit fanout")
            state = self._validate_nvds_identity(nvds_identity)
            _require(state.preprocess_event_id is not None, "DeepStream fanout precedes preprocess")
            _require(branch in ANALYTICS_BRANCHES, "DeepStream fanout branch is outside frozen set")
            _require(branch not in state.fanout_event_ids, "DeepStream fanout callback was duplicated")
            event_id = self._execution_id(state, f"{branch}:fanout")
            serialized_timestamp_ms = self._emit(
                state,
                event_kind="fanout",
                stage="fanout",
                branch=branch,
                execution_id=event_id,
                parents=[state.preprocess_event_id],
                observed_timestamp_ms=observed_timestamp_ms,
            )
            state.fanout_event_ids[branch] = event_id
            if tensor_spec is not None:
                state.tensor_specs[branch] = _validate_tensor_spec(tensor_spec)
            return serialized_timestamp_ms

    def bind_branch_tensor(
        self,
        nvds_identity: Mapping[str, Any],
        *,
        branch: str,
        tensor_spec: Mapping[str, Any],
    ) -> None:
        """Bind tensor bytes observed after the native preprocessing/fanout callback."""

        with self._lock:
            state = self._validate_nvds_identity(nvds_identity)
            _require(branch in self._endpoints, "DeepStream tensor branch is not bound")
            _require(branch not in state.tensor_specs, "DeepStream branch tensor was bound twice")
            if self.topology_kind == INDEPENDENT_PROCESSES:
                _require(branch == self.branch_id, "baseline tensor belongs to another branch")
                _require(state.preprocess_event_id is not None, "baseline tensor precedes preprocess")
            else:
                _require(branch in state.fanout_event_ids, "shared tensor precedes native fanout")
            state.tensor_specs[branch] = _validate_tensor_spec(tensor_spec)

    def drop_branch(
        self,
        input_frame_key: str,
        branch: str,
        *,
        reason: str,
        observed_timestamp_ms: float | int | None = None,
    ) -> None:
        """Emit a direct native queue-full terminal from the exact callback site."""

        _require(
            reason == "native_pre_detector_queue_full_drop_newest",
            "DeepStream branch drop reason is not the frozen native queue policy",
        )
        with self._lock:
            state = self._frame(input_frame_key)
            _require(branch in self._endpoints, "DeepStream drop branch is not bound to this process")
            _require(branch not in state.executing_branches, "executing branch cannot be queue-dropped")
            _require(branch not in state.terminal_branches, "DeepStream branch terminal is duplicated")
            _require(branch not in state.failed_branches, "failed branch cannot be queue-dropped")
            if self.topology_kind == INDEPENDENT_PROCESSES:
                _require(branch == self.branch_id, "baseline queue dropped another branch")
                parent = state.preprocess_event_id
            else:
                parent = state.fanout_event_ids.get(branch)
            _require(parent is not None, "DeepStream queue drop lacks a native causal parent")
            self._emit(
                state,
                event_kind="branch_drop",
                stage=branch,
                branch=branch,
                execution_id=self._execution_id(state, f"{branch}:drop"),
                parents=[str(parent)],
                observed_timestamp_ms=observed_timestamp_ms,
                terminal={
                    "terminal_reason": reason,
                    "objects": 0,
                    "detector": terminal_detector_identity(
                        self._endpoints[branch]["cpu"][1]
                    ),
                    "backend": "deepstream:native_pre_detector_queue",
                },
            )
            state.terminal_branches.add(branch)

    @staticmethod
    def _policy_response(value: Any) -> dict[str, Any]:
        response = _exact(value, _DECISION_RESPONSE_FIELDS, "DeepStream policy decision response")
        _require(
            response["schema_version"] == POLICY_RPC_SCHEMA_VERSION
            and response["message_type"] == "decision_response",
            "DeepStream policy decision response header drifted",
        )
        _text(response["decision_id"], "DeepStream decision_id")
        _integer(response["decision_seq"], "DeepStream decision sequence", minimum=1)
        _require(response["selected_resource"] in RESOURCES, "policy selected an unknown resource")
        _text(response["selected_implementation_id"], "selected implementation_id")
        _text(response["emitter_id"], "selected policy emitter_id")
        _sha256(response["emitter_sha256"], "selected policy emitter SHA-256")
        return response

    @staticmethod
    def _policy_ack(
        value: Any,
        *,
        decision_id: str,
        message_type: str,
    ) -> dict[str, Any]:
        fields = _PATH_ACK_FIELDS if message_type == "path_ack" else _TERMINAL_ACK_FIELDS
        ack = _exact(value, fields, f"DeepStream policy {message_type}")
        _require(
            ack["schema_version"] == POLICY_RPC_SCHEMA_VERSION
            and ack["message_type"] == message_type,
            f"DeepStream policy {message_type} header drifted",
        )
        _require(ack["decision_id"] == decision_id, f"DeepStream policy {message_type} decision mismatch")
        _require(ack["accepted"] is True, f"DeepStream policy {message_type} was not accepted")
        return ack

    def _exchange_policy(self, message: dict[str, Any], label: str) -> Mapping[str, Any]:
        try:
            response = self._policy_exchange(copy.deepcopy(message))
        except Exception as exc:
            raise DeepStreamProtocolBridgeError(f"DeepStream native policy {label} failed: {exc}") from exc
        _require(isinstance(response, Mapping), f"DeepStream native policy {label} returned no mapping")
        return response

    def _request(
        self,
        *,
        state: _FrameState,
        branch: str,
        decision_id: str,
        capability: Mapping[str, Any],
        tensor_spec: Mapping[str, Any],
        deadline_monotonic_ns: int,
    ) -> dict[str, Any]:
        request_digest = hashlib.sha256(
            (
                f"{decision_id}\0{state.admission.input_frame_key}\0{branch}\0"
                f"{capability['worker_id']}"
            ).encode("utf-8")
        ).hexdigest()
        request = {
            "schema_version": 1,
            "message_type": "infer_request",
            "request_id": f"deepstream-{request_digest[:48]}",
            "run_id": self.run_id,
            "arm_id": self.arm_id,
            "worker_id": capability["worker_id"],
            "frame": {
                "input_frame_key": state.admission.input_frame_key,
                "stream_id": self.stream_id,
                "frame_id": state.frame_id,
                "transport_pts_ns": state.admission.transport_pts_ns,
                "branch": branch,
            },
            "engine": capability["engine"],
            "deadline_monotonic_ns": deadline_monotonic_ns,
            "model": {
                "model_id": capability["model_id"],
                "source_sha256": capability["source_model_sha256"],
                "runtime_artifact_sha256": capability["model_artifact_sha256"],
                "runtime_weights_sha256": capability["runtime_weights_sha256"],
            },
            "tensor": copy.deepcopy(dict(tensor_spec)),
            "expected_output_contract_sha256": capability["output_contract_sha256"],
        }
        try:
            checked = validate_inference_request(request)
        except ProtocolError as exc:
            raise DeepStreamProtocolBridgeError(
                f"analytics execution request binding failed: {exc}"
            ) from exc
        _require(
            checked["tensor"]["preprocessing_contract_sha256"]
            == capability["preprocessing_contract_sha256"],
            "analytics execution preprocessing capability binding mismatch",
        )
        return checked

    def execute_branch(
        self,
        input_frame_key: str,
        branch: str,
        *,
        tensor_payload: bytes | bytearray | memoryview,
        queue_depths: Mapping[str, Any],
        deadline_monotonic_ns: int,
    ) -> DeepStreamBranchExecutionResult:
        """Select, enter, execute, acknowledge, then emit one branch terminal."""

        with self._lock:
            state = self._frame(input_frame_key)
            _require(branch in self._endpoints, "DeepStream branch is not bound to this process")
            _require(branch in state.tensor_specs, "DeepStream branch tensor was not observed natively")
            _require(branch not in state.executing_branches, "DeepStream branch is already executing")
            _require(branch not in state.terminal_branches, "DeepStream branch terminal is duplicated")
            _require(branch not in state.failed_branches, "DeepStream failed branch cannot be relabelled by retry")
            if self.topology_kind == INDEPENDENT_PROCESSES:
                _require(branch == self.branch_id, "baseline worker executed another branch")
                analytics_parent = state.preprocess_event_id
            else:
                analytics_parent = state.fanout_event_ids.get(branch)
            _require(analytics_parent is not None, "DeepStream analytics execution lacks causal parent")
            raw_depths = _exact(queue_depths, set(RESOURCES), "DeepStream policy queue depths")
            depths = {
                resource: _integer(
                    raw_depths[resource], f"DeepStream {resource} queue depth"
                )
                for resource in RESOURCES
            }
            deadline = _integer(
                deadline_monotonic_ns,
                "DeepStream analytics deadline_monotonic_ns",
                minimum=1,
            )
            tensor_spec = copy.deepcopy(state.tensor_specs[branch])
            payload = bytes(tensor_payload)
            _require(
                len(payload) == tensor_spec["byte_length"],
                "DeepStream analytics tensor payload length mismatch",
            )
            _require(
                hashlib.sha256(payload).hexdigest() == tensor_spec["sha256"],
                "DeepStream analytics tensor payload digest mismatch",
            )
            state.executing_branches.add(branch)

        decision_started = False
        try:
            decision_time_ms = self._clock_value("DeepStream policy decision timestamp")
            _require(
                decision_time_ms >= state.admission.admission_timestamp_ms,
                "DeepStream policy decision precedes admission",
            )
            decision_request = {
                "schema_version": POLICY_RPC_SCHEMA_VERSION,
                "message_type": "decision_request",
                "run_id": self.run_id,
                "worker_id": self.worker_id,
                "input_frame_key": state.admission.input_frame_key,
                "trace_id": state.trace_id,
                "stream_id": self.stream_id,
                "frame_id": state.frame_id,
                "transport_pts_ns": state.admission.transport_pts_ns,
                "branch": branch,
                "arrival_ms": float(state.admission.admission_timestamp_ms),
                "decision_time_ms": decision_time_ms,
                "feature_observed_timestamp_ms": decision_time_ms,
                "queue_depths": depths,
            }
            decision_started = True
            decision = self._policy_response(
                self._exchange_policy(decision_request, "decision")
            )
            selected = str(decision["selected_resource"])
            endpoint, capability = self._endpoints[branch][selected]
            _require(
                decision["selected_implementation_id"] == endpoint.implementation_id,
                "policy selected implementation does not match analytics endpoint",
            )
            # The path is created only after the decision exchange above has
            # returned its ACK.  WSL wall-clock synchronization can still make
            # the next time.time_ns() observation fractionally earlier.  Keep
            # the serialized causal clock monotonic instead of relabelling that
            # host-clock regression as a native ordering violation.
            path_timestamp_ms = max(
                self._clock_value("DeepStream native path timestamp"),
                decision_time_ms,
            )
            # Keep the epoch timestamp for the policy/event protocol, but
            # measure the enclosing service interval with an elapsed clock.
            # Wall-clock corrections during inference must not change latency.
            path_started_monotonic_ns = time.monotonic_ns()
            path_digest = hashlib.sha256(
                f"{decision['decision_id']}\0{self.worker_id}\0{branch}".encode("utf-8")
            ).hexdigest()
            path_enter = {
                "schema_version": POLICY_RPC_SCHEMA_VERSION,
                "message_type": "path_enter",
                "run_id": self.run_id,
                "worker_id": self.worker_id,
                "decision_id": decision["decision_id"],
                "input_frame_key": state.admission.input_frame_key,
                "branch": branch,
                "transport_pts_ns": state.admission.transport_pts_ns,
                "selected_resource": selected,
                "implementation_id": endpoint.implementation_id,
                "emitter_id": decision["emitter_id"],
                "emitter_sha256": decision["emitter_sha256"],
                "event_id": f"deepstream-path-{path_digest[:40]}",
                "timestamp_ms": path_timestamp_ms,
            }
            self._policy_ack(
                self._exchange_policy(path_enter, "path entry"),
                decision_id=str(decision["decision_id"]),
                message_type="path_ack",
            )
            request = self._request(
                state=state,
                branch=branch,
                decision_id=str(decision["decision_id"]),
                capability=capability,
                tensor_spec=tensor_spec,
                deadline_monotonic_ns=deadline,
            )
            try:
                raw_response, output = endpoint.client.infer(request, payload)
                response = validate_inference_response(
                    raw_response,
                    request=request,
                    capability=capability,
                )
            except Exception as exc:
                raise DeepStreamProtocolBridgeError(
                    f"analytics execution failed contract validation: {exc}"
                ) from exc
            output_bytes = bytes(output)
            output_record = response["output"]
            _require(
                len(output_bytes) == output_record["byte_length"],
                "analytics execution output byte length does not match returned memfd payload",
            )
            output_sha256 = hashlib.sha256(output_bytes).hexdigest()
            _require(
                output_sha256 == output_record["sha256"],
                "analytics execution output digest does not match returned memfd payload",
            )
            detector = terminal_detector_identity(capability)
            backend = analytics_backend_identity(capability)
            timing = response["timing"]
            worker_received_ns = int(timing["worker_received_monotonic_ns"])
            inference_finished_ns = int(timing["inference_finished_monotonic_ns"])
            worker_completed_ns = int(timing["worker_completed_monotonic_ns"])
            if selected == "gpu":
                transfers = response["resource"]["cuda_transfer_intervals"]
                _require(
                    isinstance(transfers, list) and len(transfers) == 2,
                    "DeepStream GPU response lacks its exact CUDA transfer pair",
                )
                h2d, d2h = transfers
                h2d_start_ns = int(h2d["host_start_monotonic_ns"])
                h2d_end_ns = int(h2d["host_end_monotonic_ns"])
                d2h_start_ns = int(d2h["host_start_monotonic_ns"])
                d2h_end_ns = int(d2h["host_end_monotonic_ns"])
                _require(
                    h2d["direction"] == "h2d"
                    and d2h["direction"] == "d2h"
                    and worker_received_ns
                    <= h2d_start_ns
                    < h2d_end_ns
                    <= d2h_start_ns
                    < d2h_end_ns
                    <= inference_finished_ns
                    <= worker_completed_ns,
                    "DeepStream CUDA transfer pair is outside native inference timing",
                )
                # The analytics topology node represents device computation and
                # therefore completes when the native D2H copy begins.  The
                # postprocess node completes when that copy ends.  Using the
                # worker's later `inference_finished`/`worker_completed` receipt
                # timestamps here would causally place D2H before its parent.
                analytics_offset_ns = d2h_start_ns - worker_received_ns
                postprocess_offset_ns = d2h_end_ns - worker_received_ns
            else:
                analytics_offset_ns = inference_finished_ns - worker_received_ns
                postprocess_offset_ns = worker_completed_ns - worker_received_ns
            analytics_timestamp_ms = (
                path_timestamp_ms + analytics_offset_ns / 1_000_000.0
            )
            postprocess_timestamp_ms = (
                path_timestamp_ms + postprocess_offset_ns / 1_000_000.0
            )
            if self._resource_recorder is not None:
                self._resource_recorder.record_analytics_transfers(
                    frame_id=state.frame_id,
                    input_frame_key=state.admission.input_frame_key,
                    branch=branch,
                    selected_resource=selected,
                    worker_received_monotonic_ns=worker_received_ns,
                    path_enter_timestamp_ns=round(path_timestamp_ms * 1_000_000),
                    resource=response["resource"],
                )

            with self._lock:
                actual_service_ns = time.monotonic_ns() - path_started_monotonic_ns
                _require(
                    actual_service_ns > 0,
                    "DeepStream analytics terminal does not follow path entry",
                )
                actual_service_ms = actual_service_ns / 1_000_000.0
                terminal_timestamp_ms = path_timestamp_ms + actual_service_ms
                _require(
                    actual_service_ns
                    >= int(response["timing"]["inference_latency_ns"]),
                    "DeepStream path service time is shorter than native inference",
                )
                _require(
                    actual_service_ns >= postprocess_offset_ns
                    and terminal_timestamp_ms >= postprocess_timestamp_ms
                    >= analytics_timestamp_ms >= path_timestamp_ms,
                    "DeepStream native analytics/postprocess timing is outside its path",
                )
                terminal_message = {
                    "schema_version": POLICY_RPC_SCHEMA_VERSION,
                    "message_type": "terminal",
                    "run_id": self.run_id,
                    "worker_id": self.worker_id,
                    "decision_id": decision["decision_id"],
                    "input_frame_key": state.admission.input_frame_key,
                    "branch": branch,
                    "transport_pts_ns": state.admission.transport_pts_ns,
                    "selected_resource": selected,
                    "terminal_status": "completed",
                    "terminal_timestamp_ms": terminal_timestamp_ms,
                    "actual_service_ms": actual_service_ms,
                    "detector": detector,
                    "backend": backend,
                }
                self._policy_ack(
                    self._exchange_policy(terminal_message, "terminal"),
                    decision_id=str(decision["decision_id"]),
                    message_type="terminal_ack",
                )
                analytics_id = self._execution_id(state, f"{branch}:analytics")
                postprocess_id = self._execution_id(state, f"{branch}:postprocess")
                terminal_id = self._execution_id(state, f"{branch}:complete")
                runtime_timestamp = math.ceil(terminal_timestamp_ms)
                self._emit(
                    state,
                    event_kind="stage_complete",
                    stage=branch,
                    branch=branch,
                    execution_id=analytics_id,
                    parents=[str(analytics_parent)],
                    observed_timestamp_ms=analytics_timestamp_ms,
                )
                self._emit(
                    state,
                    event_kind="stage_complete",
                    stage=f"postprocess_{branch}",
                    branch=branch,
                    execution_id=postprocess_id,
                    parents=[analytics_id],
                    observed_timestamp_ms=postprocess_timestamp_ms,
                )
                self._emit(
                    state,
                    event_kind="branch_complete",
                    stage=branch,
                    branch=branch,
                    execution_id=terminal_id,
                    parents=[postprocess_id],
                    observed_timestamp_ms=runtime_timestamp,
                    terminal={
                        "terminal_reason": response["terminal"]["reason"],
                        "objects": response["terminal"]["objects"],
                        "detector": detector,
                        "backend": backend,
                    },
                )
                state.executing_branches.remove(branch)
                state.terminal_branches.add(branch)
            return DeepStreamBranchExecutionResult(
                selected_resource=selected,
                decision_id=str(decision["decision_id"]),
                request_id=str(request["request_id"]),
                detector=detector,
                backend=backend,
                output_sha256=output_sha256,
                output_size_bytes=len(output_bytes),
                response=copy.deepcopy(response),
            )
        except Exception:
            with self._lock:
                state.executing_branches.discard(branch)
                if decision_started:
                    state.failed_branches.add(branch)
            raise


__all__ = [
    "BRIDGE_IMPLEMENTATION_STATUS",
    "DeepStreamBranchExecutionResult",
    "DeepStreamExecutionEndpoint",
    "DeepStreamProtocolBridge",
    "DeepStreamProtocolBridgeError",
    "NVDS_IDENTITY_KIND",
    "analytics_backend_identity",
]
