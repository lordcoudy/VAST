#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from benchmark_contract import (
    ContractError,
    RESET_EVIDENCE_CONTRACT_VERSION,
    TELEMETRY_SCHEMA_VERSION,
)
from checkpoint_admission import DirectAdmissionCoordinator, SourceBinding
from checkpoint_runtime_plan import validate_checkpoint_runtime_plan
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG, TOPOLOGY_EVENT_COLUMNS


RUNTIME_EVENT_PROTOCOL_VERSION = 1
RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION = 2
RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL = 3
RUNTIME_EVENT_FD_ENV = "VAST_CHECKPOINT_EVENT_FD"
RUNTIME_CONTROL_FD_ENV = "VAST_CHECKPOINT_CONTROL_FD"
RUNTIME_STATUS_FD_ENV = "VAST_CHECKPOINT_STATUS_FD"
RUNTIME_ADMISSION_EVENT_FD_ENV = "VAST_CHECKPOINT_ADMISSION_EVENT_FD"
RUNTIME_ADMISSION_ACK_FD_ENV = "VAST_CHECKPOINT_ADMISSION_ACK_FD"
RUNTIME_ADMISSION_CONSUMER_FDS_ENV = "VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON"
RUNTIME_ADMISSION_DATA_FD_ENV = "VAST_CHECKPOINT_ADMISSION_DATA_FD"
RUNTIME_LIFECYCLE_PROTOCOL_VERSION = 1
RUNTIME_LIFECYCLE_STATES = {
    "READY",
    "STARTED",
    "DECODER_PLACEMENT_VERIFIED",
    "ADMISSION_STOPPED",
    "DRAINED",
    "CENSORED",
}
NATIVE_CLOCK_MAX_READY_AGE_NS = 5_000_000_000
RUNTIME_MESSAGE_FIELDS = {
    "protocol_version",
    "worker_id",
    "sequence",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "topology_kind",
    "event_kind",
    "stage",
    "branch_id",
    "execution_id",
    "parent_execution_ids",
    "timestamp_ms",
}
RUNTIME_ADMISSION_LINK_FIELDS = {"admission_id", "payload_sha256"}
RUNTIME_BRANCH_TERMINAL_FIELDS = {"terminal_reason", "objects", "detector", "backend"}
WORKER_EVENT_KINDS = {"source_read", "stage_complete", "fanout", "branch_complete", "branch_drop"}
RUNTIME_TERMINAL_CLAIM_STATUS = "runtime_terminal_closure_not_accepted_ingress_ledger"
RUNTIME_TERMINAL_TELEMETRY_SOURCE = "engineering_runtime"
RUNTIME_RESET_PROVENANCE = "engineering_coordinator_lifecycle_observation_v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ContractError(f"runtime event {name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"runtime event {name} must be an integer") from exc
    _require(str(number) == str(value) or isinstance(value, int), f"runtime event {name} must be an exact integer")
    return number


def _text(value: Any, name: str) -> str:
    text = str(value).strip()
    _require(bool(text), f"runtime event {name} must be non-empty")
    return text


def select_native_monotonic_clock(
    ready_timestamps_ns: Iterable[int],
    *,
    candidate_clocks_ns: dict[str, int] | None = None,
) -> tuple[str, int]:
    """Select the Python clock sharing the native C++ steady-clock epoch."""
    ready_values = tuple(int(value) for value in ready_timestamps_ns)
    _require(bool(ready_values) and all(value > 0 for value in ready_values), "native READY timestamps are invalid")
    if candidate_clocks_ns is None:
        candidates = {"python_monotonic": time.monotonic_ns()}
        for constant_name, label in (
            ("CLOCK_MONOTONIC", "clock_monotonic"),
            ("CLOCK_MONOTONIC_RAW", "clock_monotonic_raw"),
            ("CLOCK_BOOTTIME", "clock_boottime"),
        ):
            clock_id = getattr(time, constant_name, None)
            if clock_id is not None:
                candidates[label] = time.clock_gettime_ns(clock_id)
    else:
        candidates = {str(name): int(value) for name, value in candidate_clocks_ns.items()}
    _require(bool(candidates) and all(value > 0 for value in candidates.values()), "native clock candidates are invalid")
    latest_ready = max(ready_values)
    clock_name, clock_now_ns = min(
        candidates.items(),
        key=lambda item: abs(item[1] - latest_ready),
    )
    ready_age_ns = clock_now_ns - latest_ready
    _require(
        0 <= ready_age_ns <= NATIVE_CLOCK_MAX_READY_AGE_NS,
        "native READY timestamps do not match an available coordinator monotonic clock",
    )
    return clock_name, clock_now_ns


@dataclass(frozen=True)
class RuntimeMessage:
    protocol_version: int
    worker_id: str
    sequence: int
    run_id: str
    trace_id: str
    stream_id: int
    frame_id: int
    input_frame_key: str
    topology_kind: str
    event_kind: str
    stage: str
    branch_id: str
    execution_id: str
    parent_execution_ids: tuple[str, ...]
    timestamp_ms: int
    admission_id: str | None = None
    payload_sha256: str | None = None
    terminal_reason: str | None = None
    objects: int | None = None
    detector: str | None = None
    backend: str | None = None

    @classmethod
    def parse(cls, line: str) -> RuntimeMessage:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError("runtime event is not valid JSON") from exc
        _require(isinstance(raw, dict), "runtime event must be a JSON object")
        protocol_version = _integer(raw.get("protocol_version"), "protocol_version")
        if protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL:
            expected_fields = RUNTIME_MESSAGE_FIELDS | RUNTIME_ADMISSION_LINK_FIELDS | RUNTIME_BRANCH_TERMINAL_FIELDS
        elif protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION:
            expected_fields = RUNTIME_MESSAGE_FIELDS | RUNTIME_ADMISSION_LINK_FIELDS
        else:
            expected_fields = RUNTIME_MESSAGE_FIELDS
        missing = sorted(expected_fields - set(raw))
        extra = sorted(set(raw) - expected_fields)
        _require(not missing, f"runtime event is missing fields: {', '.join(missing)}")
        _require(not extra, f"runtime event has unexpected fields: {', '.join(extra)}")
        parents = raw["parent_execution_ids"]
        _require(
            isinstance(parents, list) and all(isinstance(value, str) and value.strip() for value in parents),
            "runtime event parent_execution_ids must be an array of non-empty strings",
        )
        normalized_parents = tuple(value.strip() for value in parents)
        _require(len(normalized_parents) == len(set(normalized_parents)), "runtime event parents contain duplicates")
        message = cls(
            protocol_version=protocol_version,
            worker_id=_text(raw["worker_id"], "worker_id"),
            sequence=_integer(raw["sequence"], "sequence"),
            run_id=_text(raw["run_id"], "run_id"),
            trace_id=_text(raw["trace_id"], "trace_id"),
            stream_id=_integer(raw["stream_id"], "stream_id"),
            frame_id=_integer(raw["frame_id"], "frame_id"),
            input_frame_key=_text(raw["input_frame_key"], "input_frame_key"),
            topology_kind=_text(raw["topology_kind"], "topology_kind"),
            event_kind=_text(raw["event_kind"], "event_kind"),
            stage=_text(raw["stage"], "stage"),
            branch_id=_text(raw["branch_id"], "branch_id"),
            execution_id=_text(raw["execution_id"], "execution_id"),
            parent_execution_ids=normalized_parents,
            timestamp_ms=_integer(raw["timestamp_ms"], "timestamp_ms"),
            admission_id=(
                _text(raw["admission_id"], "admission_id")
                if protocol_version in {
                    RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION,
                    RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL,
                }
                else None
            ),
            payload_sha256=(
                _text(raw["payload_sha256"], "payload_sha256")
                if protocol_version in {
                    RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION,
                    RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL,
                }
                else None
            ),
            terminal_reason=(
                _text(raw["terminal_reason"], "terminal_reason")
                if protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL
                else None
            ),
            objects=(
                _integer(raw["objects"], "objects")
                if protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL
                else None
            ),
            detector=(
                _text(raw["detector"], "detector")
                if protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL
                else None
            ),
            backend=(
                _text(raw["backend"], "backend")
                if protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL
                else None
            ),
        )
        _require(
            message.protocol_version in {
                RUNTIME_EVENT_PROTOCOL_VERSION,
                RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION,
                RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL,
            },
            "unsupported runtime event protocol",
        )
        if message.protocol_version in {
            RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION,
            RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL,
        }:
            _require(
                len(str(message.payload_sha256)) == 64
                and all(value in "0123456789abcdef" for value in str(message.payload_sha256)),
                "runtime event payload_sha256 must be lowercase SHA-256",
            )
        _require(message.sequence > 0, "runtime event sequence must be positive")
        _require(message.stream_id >= 0 and message.frame_id >= 0, "runtime frame identity must be non-negative")
        _require(message.timestamp_ms >= 0, "runtime event timestamp must be non-negative")
        _require(message.event_kind in WORKER_EVENT_KINDS, "worker may not emit this runtime event kind")
        if message.protocol_version == RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL:
            _require(
                message.event_kind in {"branch_complete", "branch_drop"},
                "runtime protocol version 3 is reserved for branch terminal events",
            )
            _require(int(message.objects or 0) >= 0, "runtime branch terminal objects must be non-negative")
            if message.event_kind == "branch_drop":
                _require(message.objects == 0, "runtime branch drop must not report accepted objects")
        else:
            _require(message.event_kind != "branch_drop", "branch_drop requires runtime protocol version 3")
        if message.event_kind == "source_read":
            _require(not message.parent_execution_ids, "source_read must not have parents")
        else:
            _require(bool(message.parent_execution_ids), f"{message.event_kind} must have parents")
        return message


@dataclass(frozen=True)
class WorkerLaunchSpec:
    worker_id: str
    stream_id: int
    branch_id: str | None
    command: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict)
    native_event_source: bool = False


@dataclass(frozen=True)
class SourceLaunchSpec:
    source_process_id: str
    stream_id: int
    dataset_id: str
    source_sha256: str
    command: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict)
    native_source: bool = False


@dataclass(frozen=True)
class WorkerBinding:
    worker_id: str
    stream_id: int
    branch_id: str | None
    pid: int
    execution_domain: str
    native_event_source: bool


@dataclass
class _FrameState:
    input_frame_key: str
    stream_id: int
    canonical_trace_id: str
    canonical_frame_id: int
    worker_frame_keys: dict[str, tuple[str, int]] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    branch_terminals: dict[str, dict[str, Any]] = field(default_factory=dict)
    joined: bool = False
    terminal_status: str | None = None
    terminal_timestamp_ms: int | None = None
    terminal_reason: str | None = None
    terminal_event_provenance: str | None = None
    terminal_telemetry_source: str | None = None
    admission_id: str | None = None
    payload_sha256: str | None = None


@dataclass(frozen=True)
class RuntimeRunResult:
    events: tuple[dict[str, Any], ...]
    unresolved_frames: tuple[tuple[str, int, int], ...]
    process_ids: dict[str, int]
    event_observed_ns: dict[str, int]
    process_exit_ns: dict[str, int]
    source_process_ids: dict[str, int] = field(default_factory=dict)
    lifecycle_statuses: dict[str, tuple[str, ...]] = field(default_factory=dict)
    lifecycle_records: dict[str, tuple[RuntimeLifecycleStatus, ...]] = field(default_factory=dict)
    common_start_clock: str = ""
    common_start_monotonic_ns: int = 0
    window_start_timestamp_ms: int = 0
    window_end_timestamp_ms: int = 0
    drain_end_timestamp_ms: int = 0
    admission_audit: dict[str, Any] | None = None
    terminal_ingress_rows: tuple[dict[str, Any], ...] = ()
    terminal_admission_audit: dict[str, Any] | None = None
    branch_terminal_records: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RuntimeLifecycleStatus:
    state: str
    worker_id: str
    timestamp: int

    @classmethod
    def parse(cls, line: str) -> RuntimeLifecycleStatus:
        fields = line.strip().split()
        _require(len(fields) == 4, "runtime lifecycle status must contain four fields")
        version = _integer(fields[0], "lifecycle protocol_version")
        _require(version == RUNTIME_LIFECYCLE_PROTOCOL_VERSION, "unsupported runtime lifecycle protocol")
        state = _text(fields[1], "lifecycle state")
        _require(state in RUNTIME_LIFECYCLE_STATES, "unsupported runtime lifecycle state")
        worker_id = _text(fields[2], "lifecycle worker_id")
        timestamp = _integer(fields[3], "lifecycle timestamp")
        _require(timestamp >= 0, "runtime lifecycle timestamp must be non-negative")
        return cls(state=state, worker_id=worker_id, timestamp=timestamp)


def build_runtime_reset_evidence(
    *,
    run_id: str,
    topology_kind: str,
    branches: Iterable[str],
    specs: Iterable[WorkerLaunchSpec],
    source_specs: Iterable[SourceLaunchSpec],
    result: RuntimeRunResult,
    telemetry_sink_id: str,
    telemetry_sink_preexisting_entry_count: int,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Build an engineering-only reset audit from direct process/lifecycle observations."""
    branch_values = tuple(str(value) for value in branches)
    _require(bool(branch_values) and len(branch_values) == len(set(branch_values)), "reset branches must be unique")
    _require(topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}, "unsupported reset topology")
    sink_id = str(telemetry_sink_id).strip().lower()
    _require(len(sink_id) == 64 and all(char in "0123456789abcdef" for char in sink_id), "invalid reset sink ID")
    preexisting = int(telemetry_sink_preexisting_entry_count)
    _require(preexisting >= 0, "reset sink preexisting entry count must be non-negative")
    ingress_rows = list(result.terminal_ingress_rows)
    _require(bool(ingress_rows), "runtime reset evidence requires terminal ingress rows")
    cohort_ids = {str(row["cohort_id"]) for row in ingress_rows}
    _require(len(cohort_ids) == 1, "runtime reset evidence requires one cohort")
    cohort_id = next(iter(cohort_ids))
    first_ingress: dict[int, dict[str, Any]] = {}
    for row in sorted(ingress_rows, key=lambda item: (int(item["stream_id"]), int(item["admission_seq"]))):
        first_ingress.setdefault(int(row["stream_id"]), row)

    def lifecycle(instance_id: str) -> tuple[RuntimeLifecycleStatus, ...]:
        records = result.lifecycle_records.get(instance_id, ())
        _require(bool(records), f"missing reset lifecycle records for {instance_id}")
        _require(records[0].state == "READY", f"{instance_id}: reset lifecycle must begin with READY")
        return records

    def token(instance_id: str, pid: int, ready_timestamp: int) -> str:
        payload = f"{run_id}\0{instance_id}\0{pid}\0{ready_timestamp}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    rows: list[dict[str, Any]] = []

    def append_row(
        *,
        instance_id: str,
        role: str,
        stream_id: int,
        branch_id: str,
        pid: int,
        queue_depths: dict[str, int],
        source_cycle_first: int,
        admission_seq_first: int,
    ) -> None:
        records = lifecycle(instance_id)
        states = [record.state for record in records]
        ready_timestamp = int(records[0].timestamp)
        rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "reset_contract_version": RESET_EVIDENCE_CONTRACT_VERSION,
                "run_id": run_id,
                "cohort_id": cohort_id,
                "process_instance_id": instance_id,
                "process_role": role,
                "stream_id": int(stream_id),
                "branch_id": branch_id,
                "observed_pid": int(pid),
                "process_start_token": token(instance_id, int(pid), ready_timestamp),
                "ready_timestamp_ns": ready_timestamp,
                "analytics_queue_depths_json": json.dumps(queue_depths, sort_keys=True, separators=(",", ":")),
                "source_cycle_first": int(source_cycle_first),
                "admission_seq_first": int(admission_seq_first),
                "telemetry_sink_id": sink_id,
                "telemetry_sink_preexisting_entry_count": preexisting,
                "warmup_included_in_measurement": "false",
                "admission_stopped_before_drain": str("ADMISSION_STOPPED" in states).lower(),
                "terminal_state": states[-1],
                "reset_provenance": RUNTIME_RESET_PROVENANCE,
                "telemetry_source": "engineering_runtime",
            }
        )

    source_values = tuple(source_specs)
    for spec in source_values:
        first = first_ingress.get(int(spec.stream_id))
        _require(first is not None, f"missing first direct admission for reset stream {spec.stream_id}")
        append_row(
            instance_id=spec.source_process_id,
            role="source_coordinator",
            stream_id=spec.stream_id,
            branch_id="not_applicable",
            pid=result.source_process_ids[spec.source_process_id],
            queue_depths={},
            source_cycle_first=int(first["source_cycle"]),
            admission_seq_first=int(first["admission_seq"]),
        )

    worker_values = tuple(specs)
    for spec in worker_values:
        if topology_kind == INDEPENDENT_PROCESSES:
            _require(spec.branch_id is not None, "independent reset worker must have a branch")
            role = "independent_branch_worker"
            branch_id = str(spec.branch_id)
            queue_depths = {branch_id: 0}
        else:
            role = "shared_graph_worker"
            branch_id = "not_applicable"
            queue_depths = {branch: 0 for branch in branch_values}
        append_row(
            instance_id=spec.worker_id,
            role=role,
            stream_id=spec.stream_id,
            branch_id=branch_id,
            pid=result.process_ids[spec.worker_id],
            queue_depths=queue_depths,
            source_cycle_first=-1,
            admission_seq_first=-1,
        )

    process_tokens = [str(row["process_start_token"]) for row in rows]
    terminal_states = {str(row["terminal_state"]) for row in rows}
    reset_complete = (
        preexisting == 0
        and terminal_states == {"DRAINED"}
        and len(process_tokens) == len(set(process_tokens))
        and all(
            int(first["source_cycle"]) == 0 and int(first["admission_seq"]) == 1
            for first in first_ingress.values()
        )
    )
    audit = {
        "schema_version": 1,
        "artifact_kind": "checkpoint_runtime_reset_evidence_audit",
        "claim_status": "engineering_reset_evidence_not_accepted_sidecar",
        "process_count": len(rows),
        "source_process_count": len(source_values),
        "worker_process_count": len(worker_values),
        "telemetry_sink_id": sink_id,
        "telemetry_sink_preexisting_entry_count": preexisting,
        "engineering_reset_state_complete": reset_complete,
        "accepted_reset_evidence_written": False,
    }
    return tuple(rows), audit


def expected_worker_assignments(plan: dict[str, Any]) -> list[tuple[str, int, str | None]]:
    validate_checkpoint_runtime_plan(plan)
    assignments: list[tuple[str, int, str | None]] = []
    if plan["topology_kind"] == INDEPENDENT_PROCESSES:
        for stream in plan["streams"]:
            for worker in stream["workers"]:
                assignments.append((str(worker["process_id"]), int(stream["stream_id"]), str(worker["branch_id"])))
    else:
        for stream in plan["streams"]:
            graph = stream["graph_process"]
            assignments.append((str(graph["process_id"]), int(stream["stream_id"]), None))
    return assignments


class DirectRuntimeJoinCoordinator:
    def __init__(
        self,
        *,
        run_id: str,
        topology_kind: str,
        branches: Iterable[str],
        bindings: Iterable[WorkerBinding],
        coordinator_pid: int | None = None,
        hostname: str | None = None,
        clock_ms: Callable[[], int] | None = None,
        admission_coordinator: DirectAdmissionCoordinator | None = None,
    ) -> None:
        self.run_id = _text(run_id, "run_id")
        self.topology_kind = topology_kind
        _require(topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}, "unsupported runtime topology")
        self.branches = tuple(str(value) for value in branches)
        _require(bool(self.branches) and len(self.branches) == len(set(self.branches)), "runtime branches must be unique")
        binding_values = list(bindings)
        self.bindings = {binding.worker_id: binding for binding in binding_values}
        _require(len(self.bindings) == len(binding_values), "runtime worker IDs must be unique")
        self._validate_bindings(binding_values)
        self.coordinator_pid = int(coordinator_pid if coordinator_pid is not None else os.getpid())
        self.hostname = hostname or socket.gethostname()
        self.coordinator_domain = f"{self.hostname}:pid-{self.coordinator_pid}:checkpoint-coordinator"
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.admission_coordinator = admission_coordinator
        self._worker_sequence = {worker_id: 0 for worker_id in self.bindings}
        self._worker_timestamp = {worker_id: -1 for worker_id in self.bindings}
        self._frames: dict[tuple[int, str], _FrameState] = {}
        self._input_key_streams: dict[str, int] = {}
        self._next_frame_id: dict[int, int] = {}
        self._execution_ids: set[str] = set()
        self._lock = threading.Lock()

    def _validate_bindings(self, bindings: list[WorkerBinding]) -> None:
        _require(all(binding.pid > 0 for binding in bindings), "runtime worker PID must be positive")
        _require(len({binding.execution_domain for binding in bindings}) == len(bindings), "worker domains must be unique")
        by_stream: dict[int, list[WorkerBinding]] = {}
        for binding in bindings:
            by_stream.setdefault(binding.stream_id, []).append(binding)
        if self.topology_kind == INDEPENDENT_PROCESSES:
            for stream_id, values in by_stream.items():
                _require(
                    {binding.branch_id for binding in values} == set(self.branches),
                    f"baseline stream {stream_id} does not bind exactly one process per branch",
                )
                _require(
                    len({binding.pid for binding in values}) == len(self.branches),
                    f"baseline stream {stream_id} branch workers do not have distinct PIDs",
                )
        else:
            for stream_id, values in by_stream.items():
                _require(len(values) == 1, f"shared stream {stream_id} must bind one graph process")
                _require(values[0].branch_id is None, "shared graph binding must not select one branch")

    @staticmethod
    def _frame_key(message: RuntimeMessage) -> tuple[int, str]:
        return (message.stream_id, message.input_frame_key)

    def _new_frame_state(self, message: RuntimeMessage) -> _FrameState:
        canonical_frame_id = self._next_frame_id.get(message.stream_id, 0)
        self._next_frame_id[message.stream_id] = canonical_frame_id + 1
        return _FrameState(
            input_frame_key=message.input_frame_key,
            stream_id=message.stream_id,
            canonical_trace_id=f"{self.run_id}:{message.stream_id}:{canonical_frame_id}",
            canonical_frame_id=canonical_frame_id,
        )

    @staticmethod
    def _bind_worker_frame(state: _FrameState, message: RuntimeMessage) -> None:
        worker_frame_key = (message.trace_id, message.frame_id)
        existing = state.worker_frame_keys.get(message.worker_id)
        if existing is None:
            _require(message.event_kind == "source_read", "worker frame must begin with a direct source_read")
            if state.admission_id is None:
                state.admission_id = message.admission_id
                state.payload_sha256 = message.payload_sha256
            else:
                _require(state.admission_id == message.admission_id, "workers used different admission IDs for one frame")
                _require(state.payload_sha256 == message.payload_sha256, "workers used different payloads for one frame")
            state.worker_frame_keys[message.worker_id] = worker_frame_key
            return
        _require(existing == worker_frame_key, "worker changed local trace/frame identity within one input frame")
        _require(message.event_kind != "source_read", "worker emitted duplicate source_read for one input frame")

    def _validate_shape(self, message: RuntimeMessage, binding: WorkerBinding, state: _FrameState) -> None:
        parent_rows = [state.events.get(parent_id) for parent_id in message.parent_execution_ids]
        _require(all(parent is not None for parent in parent_rows), "runtime event parent has not been observed directly")
        _require(
            all(int(parent["timestamp_ms"]) <= message.timestamp_ms for parent in parent_rows if parent is not None),
            "runtime event precedes its parent",
        )
        parent_shapes = {
            (str(parent["event_kind"]), str(parent["stage"]), str(parent["branch_id"]))
            for parent in parent_rows
            if parent is not None
        }
        branch = message.branch_id
        if self.topology_kind == INDEPENDENT_PROCESSES:
            _require(binding.branch_id == branch, "baseline worker emitted an event for another branch")
            if message.event_kind == "source_read":
                _require(message.stage == "source", "baseline source event has the wrong stage")
            elif message.event_kind == "stage_complete" and message.stage == f"decode_{branch}":
                _require(parent_shapes == {("source_read", "source", branch)}, "baseline decode parent mismatch")
            elif message.event_kind == "stage_complete" and message.stage == f"preprocess_{branch}":
                _require(
                    parent_shapes == {("stage_complete", f"decode_{branch}", branch)},
                    "baseline preprocess parent mismatch",
                )
            elif message.event_kind == "stage_complete" and message.stage == branch:
                _require(
                    parent_shapes == {("stage_complete", f"preprocess_{branch}", branch)},
                    "baseline analytics parent mismatch",
                )
            elif message.event_kind == "branch_complete" and message.stage == branch:
                _require(parent_shapes == {("stage_complete", branch, branch)}, "baseline completion parent mismatch")
            elif message.event_kind == "branch_drop" and message.stage == branch:
                _require(
                    parent_shapes == {("stage_complete", f"preprocess_{branch}", branch)},
                    "baseline drop parent mismatch",
                )
            else:
                raise ContractError("baseline worker emitted an event outside its source/decode/preprocess/branch chain")
        else:
            _require(binding.branch_id is None, "shared event came from a branch-only binding")
            if message.event_kind == "source_read":
                _require(message.stage == "source" and branch == "shared", "shared source event mismatch")
            elif message.event_kind == "stage_complete" and message.stage == "decode" and branch == "shared":
                _require(parent_shapes == {("source_read", "source", "shared")}, "shared decode parent mismatch")
            elif message.event_kind == "stage_complete" and message.stage == "preprocess" and branch == "shared":
                _require(
                    parent_shapes == {("stage_complete", "decode", "shared")},
                    "shared preprocess parent mismatch",
                )
            elif message.event_kind == "fanout" and message.stage == "fanout" and branch in self.branches:
                _require(
                    parent_shapes == {("stage_complete", "preprocess", "shared")},
                    "shared fanout parent mismatch",
                )
            elif message.event_kind == "stage_complete" and message.stage == branch and branch in self.branches:
                _require(parent_shapes == {("fanout", "fanout", branch)}, "shared analytics parent mismatch")
            elif message.event_kind == "branch_complete" and message.stage == branch and branch in self.branches:
                _require(parent_shapes == {("stage_complete", branch, branch)}, "shared completion parent mismatch")
            elif message.event_kind == "branch_drop" and message.stage == branch and branch in self.branches:
                _require(parent_shapes == {("fanout", "fanout", branch)}, "shared drop parent mismatch")
            else:
                raise ContractError("shared worker emitted an event outside its prefix/fanout/branch chain")

    def accept(self, line: str, *, observed_worker_id: str, observed_pid: int) -> tuple[dict[str, Any], ...]:
        message = RuntimeMessage.parse(line)
        with self._lock:
            binding = self.bindings.get(observed_worker_id)
            _require(binding is not None, f"unregistered runtime worker: {observed_worker_id}")
            _require(message.worker_id == observed_worker_id, "runtime event worker ID does not match its pipe")
            _require(binding.pid == observed_pid, "runtime event pipe is not bound to the launched worker PID")
            _require(message.run_id == self.run_id, "runtime event run_id mismatch")
            _require(message.topology_kind == self.topology_kind, "runtime event topology mismatch")
            _require(message.stream_id == binding.stream_id, "runtime worker emitted another stream")
            expected_sequence = self._worker_sequence[observed_worker_id] + 1
            _require(message.sequence == expected_sequence, "runtime worker sequence is not gap-free")
            _require(
                message.timestamp_ms >= self._worker_timestamp[observed_worker_id],
                "runtime worker timestamps are not monotonic",
            )
            frame_key = self._frame_key(message)
            state = self._frames.get(frame_key)
            if state is None:
                _require(message.event_kind == "source_read", "first runtime event for a frame must be source_read")
                previous_stream = self._input_key_streams.get(message.input_frame_key)
                _require(
                    previous_stream is None or previous_stream == message.stream_id,
                    "runtime input_frame_key is reused across logical streams",
                )
                self._input_key_streams[message.input_frame_key] = message.stream_id
                state = self._new_frame_state(message)
                self._frames[frame_key] = state
            _require(state.terminal_status is None, "runtime worker emitted an event after terminal frame outcome")
            if self.admission_coordinator is not None:
                _require(
                    message.protocol_version in {
                        RUNTIME_EVENT_PROTOCOL_WITH_ADMISSION,
                        RUNTIME_EVENT_PROTOCOL_WITH_BRANCH_TERMINAL,
                    },
                    "admission-enforced runtime requires event protocol version 2 or 3",
                )
                if message.event_kind == "source_read":
                    consumer_id = binding.branch_id or "shared"
                    self.admission_coordinator.observe_worker_source(message, consumer_id=consumer_id)
                else:
                    _require(state.admission_id == message.admission_id, "runtime event changed admission_id")
                    _require(state.payload_sha256 == message.payload_sha256, "runtime event changed payload_sha256")
            self._bind_worker_frame(state, message)
            _require(message.execution_id not in self._execution_ids, "duplicate runtime execution_id")
            self._validate_shape(message, binding, state)
            row = {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": message.run_id,
                "trace_id": state.canonical_trace_id,
                "stream_id": state.stream_id,
                "frame_id": state.canonical_frame_id,
                "input_frame_key": message.input_frame_key,
                "topology_kind": message.topology_kind,
                "event_kind": message.event_kind,
                "stage": message.stage,
                "branch_id": message.branch_id,
                "execution_id": message.execution_id,
                "parent_execution_ids_json": json.dumps(list(message.parent_execution_ids), separators=(",", ":")),
                "execution_domain": binding.execution_domain,
                "timestamp_ms": message.timestamp_ms,
                "event_provenance": "native_runtime_event" if binding.native_event_source else "runtime_contract_test",
                "telemetry_source": "native" if binding.native_event_source else "contract_test",
                "runtime_protocol_version": message.protocol_version,
                "terminal_reason": message.terminal_reason,
                "objects": message.objects,
                "detector": message.detector,
                "backend": message.backend,
            }
            state.events[message.execution_id] = row
            self._execution_ids.add(message.execution_id)
            self._worker_sequence[observed_worker_id] = message.sequence
            self._worker_timestamp[observed_worker_id] = message.timestamp_ms
            emitted = [row]
            if message.event_kind in {"branch_complete", "branch_drop"}:
                _require(message.branch_id not in state.branch_terminals, "duplicate runtime branch terminal event")
                state.branch_terminals[message.branch_id] = row
                if set(state.branch_terminals) == set(self.branches):
                    terminal_rows = [state.branch_terminals[branch] for branch in self.branches]
                    terminal_timestamp = max(int(value["timestamp_ms"]) for value in terminal_rows)
                    all_native = all(value.native_event_source for value in self.bindings.values())
                    drop_rows = [value for value in terminal_rows if value["event_kind"] == "branch_drop"]
                    if drop_rows:
                        state.terminal_status = "drop"
                        state.terminal_timestamp_ms = terminal_timestamp
                        state.terminal_reason = ";".join(
                            sorted({str(value["terminal_reason"]) for value in drop_rows})
                        )
                        state.terminal_event_provenance = (
                            "native_drop_event" if all_native else "runtime_contract_test_drop_event"
                        )
                        state.terminal_telemetry_source = "native" if all_native else "contract_test"
                        return tuple({column: value[column] for column in TOPOLOGY_EVENT_COLUMNS} for value in emitted)
                    join_id = f"{state.canonical_trace_id}:join"
                    _require(join_id not in self._execution_ids, "duplicate runtime join execution_id")
                    join_timestamp = max(self.clock_ms(), terminal_timestamp)
                    join = {
                        "schema_version": TELEMETRY_SCHEMA_VERSION,
                        "run_id": message.run_id,
                        "trace_id": state.canonical_trace_id,
                        "stream_id": state.stream_id,
                        "frame_id": state.canonical_frame_id,
                        "input_frame_key": message.input_frame_key,
                        "topology_kind": message.topology_kind,
                        "event_kind": "join_complete",
                        "stage": "join",
                        "branch_id": "shared",
                        "execution_id": join_id,
                        "parent_execution_ids_json": json.dumps(
                            [value["execution_id"] for value in terminal_rows], separators=(",", ":")
                        ),
                        "execution_domain": self.coordinator_domain,
                        "timestamp_ms": join_timestamp,
                        "event_provenance": "native_runtime_event" if all_native else "runtime_contract_test",
                        "telemetry_source": "native" if all_native else "contract_test",
                    }
                    state.events[join_id] = join
                    state.joined = True
                    state.terminal_status = "completed"
                    state.terminal_timestamp_ms = join_timestamp
                    state.terminal_reason = "all_required_branches_joined"
                    state.terminal_event_provenance = str(join["event_provenance"])
                    state.terminal_telemetry_source = str(join["telemetry_source"])
                    self._execution_ids.add(join_id)
                    emitted.append(join)
            return tuple({column: value[column] for column in TOPOLOGY_EVENT_COLUMNS} for value in emitted)

    def unresolved_frames(self) -> tuple[tuple[str, int, int], ...]:
        with self._lock:
            return tuple(
                sorted(
                    (value.canonical_trace_id, value.stream_id, value.canonical_frame_id)
                    for value in self._frames.values()
                    if value.terminal_status is None
                )
            )

    def terminal_frame_records(self) -> tuple[dict[str, Any], ...]:
        """Return coordinator-owned join state without inferring a scientific outcome."""
        with self._lock:
            records: list[dict[str, Any]] = []
            for state in self._frames.values():
                if state.admission_id is None:
                    continue
                records.append(
                    {
                        "admission_id": state.admission_id,
                        "input_frame_key": state.input_frame_key,
                        "stream_id": state.stream_id,
                        "trace_id": state.canonical_trace_id,
                        "frame_id": state.canonical_frame_id,
                        "joined": state.joined,
                        "terminal_status": state.terminal_status,
                        "terminal_timestamp_ms": state.terminal_timestamp_ms,
                        "terminal_reason": state.terminal_reason,
                        "terminal_event_provenance": state.terminal_event_provenance,
                        "terminal_telemetry_source": state.terminal_telemetry_source,
                    }
                )
            return tuple(sorted(records, key=lambda row: (int(row["stream_id"]), int(row["frame_id"]))))

    def branch_terminal_records(self) -> tuple[dict[str, Any], ...]:
        """Return direct branch outcomes without promoting them to an accepted sidecar."""
        with self._lock:
            records: list[dict[str, Any]] = []
            for state in self._frames.values():
                for branch_id, row in state.branch_terminals.items():
                    records.append(
                        {
                            "run_id": self.run_id,
                            "trace_id": state.canonical_trace_id,
                            "input_frame_key": state.input_frame_key,
                            "stream_id": state.stream_id,
                            "frame_id": state.canonical_frame_id,
                            "branch_id": branch_id,
                            "terminal_status": (
                                "drop" if str(row["event_kind"]) == "branch_drop" else "completed"
                            ),
                            "terminal_timestamp_ms": int(row["timestamp_ms"]),
                            "objects": row.get("objects"),
                            "detector": row.get("detector"),
                            "backend": row.get("backend"),
                            "terminal_reason": row.get("terminal_reason"),
                            "runtime_protocol_version": int(row["runtime_protocol_version"]),
                            "event_provenance": str(row["event_provenance"]),
                            "telemetry_source": str(row["telemetry_source"]),
                        }
                    )
            return tuple(
                sorted(
                    records,
                    key=lambda row: (
                        int(row["stream_id"]),
                        int(row["frame_id"]),
                        str(row["branch_id"]),
                    ),
                )
            )


def build_runtime_terminal_ingress_ledger(
    *,
    admission_records: Iterable[dict[str, Any]],
    terminal_frame_records: Iterable[dict[str, Any]],
    lifecycle_statuses: dict[str, tuple[str, ...]],
    window_start_timestamp_ms: int,
    window_end_timestamp_ms: int,
    drain_end_timestamp_ms: int,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Close direct admissions for engineering diagnostics without producing an accepted ledger."""
    _require(window_start_timestamp_ms < window_end_timestamp_ms, "terminal ingress window is invalid")
    _require(drain_end_timestamp_ms >= window_end_timestamp_ms, "terminal ingress drain boundary is invalid")
    admissions = list(admission_records)
    frames = list(terminal_frame_records)
    run_ids = {str(row["run_id"]) for row in admissions}
    _require(len(run_ids) <= 1, "terminal ingress admissions contain multiple runs")
    run_id = next(iter(run_ids), "")
    admission_ids = [str(row["admission_id"]) for row in admissions]
    admission_id_set = set(admission_ids)
    _require(len(admission_ids) == len(admission_id_set), "terminal ingress admissions contain duplicate IDs")
    frames_by_admission: dict[str, dict[str, Any]] = {}
    for frame in frames:
        admission_id = str(frame["admission_id"])
        _require(admission_id not in frames_by_admission, "terminal ingress frame linkage is duplicated")
        frames_by_admission[admission_id] = frame

    measurement = [
        row
        for row in admissions
        if window_start_timestamp_ms <= int(row["admission_timestamp_ms"]) < window_end_timestamp_ms
    ]
    pre_window_count = sum(int(row["admission_timestamp_ms"]) < window_start_timestamp_ms for row in admissions)
    post_window_count = sum(int(row["admission_timestamp_ms"]) >= window_end_timestamp_ms for row in admissions)
    measurement_ids = {str(row["admission_id"]) for row in measurement}
    extra_terminal_frame_count = sum(admission_id not in admission_id_set for admission_id in frames_by_admission)
    has_censored = any(
        frames_by_admission.get(str(row["admission_id"]), {}).get("terminal_status") not in {"completed", "drop"}
        for row in measurement
    )
    censoring_rule = "explicit_censoring_at_drain_end" if has_censored else "drain_to_empty"
    cohort_id = f"{run_id}:engineering-window:{window_start_timestamp_ms}:{window_end_timestamp_ms}"
    ledger_rows: list[dict[str, Any]] = []
    native_completion_count = 0
    native_drop_count = 0
    complete_consumer_coverage_count = 0

    for admission in measurement:
        admission_id = str(admission["admission_id"])
        frame = frames_by_admission.get(admission_id)
        coverage_complete = bool(admission.get("consumer_coverage_complete"))
        complete_consumer_coverage_count += int(coverage_complete)
        frame_terminal_status = str(frame.get("terminal_status")) if frame is not None else ""
        if frame_terminal_status in {"completed", "drop"}:
            terminal_timestamp_ms = int(frame["terminal_timestamp_ms"])
            _require(
                int(admission["admission_timestamp_ms"]) <= terminal_timestamp_ms <= drain_end_timestamp_ms,
                "runtime terminal event is outside the admission/drain interval",
            )
            terminal_status = frame_terminal_status
            terminal_reason = str(frame["terminal_reason"])
            native_terminal = frame.get("terminal_telemetry_source") == "native"
            if terminal_status == "completed":
                terminal_provenance = (
                    "native_completion_event" if native_terminal else "runtime_contract_test_completion_event"
                )
                native_completion_count += int(native_terminal)
            else:
                terminal_provenance = (
                    "native_drop_event" if native_terminal else "runtime_contract_test_drop_event"
                )
                native_drop_count += int(native_terminal)
            trace_id = str(frame["trace_id"])
            frame_id = int(frame["frame_id"])
        else:
            terminal_timestamp_ms = drain_end_timestamp_ms
            terminal_status = "censored"
            terminal_reason = "no_complete_join_at_drain_end"
            terminal_provenance = "explicit_censoring_at_drain_end"
            trace_id = (
                str(frame["trace_id"])
                if frame is not None
                else f"{run_id}:{int(admission['stream_id'])}:admission-censored:{int(admission['sequence'])}"
            )
            frame_id = int(frame["frame_id"]) if frame is not None else int(admission["sequence"]) - 1
        ledger_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "cohort_id": cohort_id,
                "trace_id": trace_id,
                "input_frame_key": str(admission["input_frame_key"]),
                "admission_seq": int(admission["sequence"]),
                "source_sha256": str(admission["source_sha256"]),
                "source_cycle": int(admission["source_cycle"]),
                "access_unit_pts_ns": int(admission["access_unit_pts_ns"]),
                "payload_sha256": str(admission["payload_sha256"]),
                "payload_size_bytes": int(admission["payload_size_bytes"]),
                "schedule_offset_ns": int(admission["schedule_offset_ns"]),
                "stream_id": int(admission["stream_id"]),
                "frame_id": frame_id,
                "ingress_timestamp_ms": int(admission["admission_timestamp_ms"]),
                "window_start_timestamp_ms": window_start_timestamp_ms,
                "window_end_timestamp_ms": window_end_timestamp_ms,
                "terminal_status": terminal_status,
                "terminal_timestamp_ms": terminal_timestamp_ms,
                "drain_end_timestamp_ms": drain_end_timestamp_ms,
                "terminal_reason": terminal_reason,
                "censoring_rule": censoring_rule,
                "ingress_provenance": "native_ingress_event",
                "terminal_provenance": terminal_provenance,
                "telemetry_source": RUNTIME_TERMINAL_TELEMETRY_SOURCE,
            }
        )

    completed_count = sum(row["terminal_status"] == "completed" for row in ledger_rows)
    drop_count = sum(row["terminal_status"] == "drop" for row in ledger_rows)
    censored_count = sum(row["terminal_status"] == "censored" for row in ledger_rows)
    lifecycle_terminal = bool(lifecycle_statuses) and all(
        states and states[-1] in {"DRAINED", "CENSORED"} for states in lifecycle_statuses.values()
    )
    every_measurement_admission_linked = measurement_ids <= set(frames_by_admission)
    engineering_terminal_closure_complete = (
        bool(measurement)
        and len(ledger_rows) == len(measurement)
        and completed_count + drop_count + censored_count == len(measurement)
        and lifecycle_terminal
        and post_window_count == 0
        and extra_terminal_frame_count == 0
    )
    engineering_terminal_accounting_complete = (
        engineering_terminal_closure_complete
        and every_measurement_admission_linked
        and complete_consumer_coverage_count == len(measurement)
    )
    audit = {
        "schema_version": 1,
        "artifact_kind": "checkpoint_terminal_admission_audit",
        "claim_status": RUNTIME_TERMINAL_CLAIM_STATUS,
        "run_id": run_id,
        "cohort_id": cohort_id,
        "admission_count": len(admissions),
        "pre_window_admission_count": pre_window_count,
        "measurement_admission_count": len(measurement),
        "post_window_admission_count": post_window_count,
        "terminal_row_count": len(ledger_rows),
        "completed_count": completed_count,
        "drop_count": drop_count,
        "censored_count": censored_count,
        "complete_consumer_coverage_count": complete_consumer_coverage_count,
        "measurement_frame_linkage_count": sum(
            str(row["admission_id"]) in frames_by_admission for row in measurement
        ),
        "extra_terminal_frame_count": extra_terminal_frame_count,
        "native_completion_event_count": native_completion_count,
        "native_drop_event_count": native_drop_count,
        "all_measurement_admissions_have_frame_linkage": every_measurement_admission_linked,
        "all_measurement_admissions_have_consumer_coverage": (
            complete_consumer_coverage_count == len(measurement)
        ),
        "engineering_terminal_closure_complete": engineering_terminal_closure_complete,
        "engineering_terminal_accounting_complete": engineering_terminal_accounting_complete,
        "engineering_cohort_closed_without_censoring": (
            engineering_terminal_accounting_complete and censored_count == 0
        ),
        "native_drop_event_coverage_complete": (
            drop_count > 0 and native_drop_count == drop_count
        ),
        "terminal_ingress_ledger_complete": False,
        "accepted_frames_linkage_complete": False,
        "accepted_ingress_ledger_written": False,
        "runtime_ledger_telemetry_source": RUNTIME_TERMINAL_TELEMETRY_SOURCE,
        "censoring_rule": censoring_rule,
        "publication_blockers": [
            "runtime ingress rows are not accepted ingress_ledger.csv",
            "accepted native frames.csv linkage is absent",
            "accepted native branch terminal sidecar is not emitted",
            "target KPP execution and resource attribution are absent",
        ],
    }
    return tuple(ledger_rows), audit


def _terminate_processes(processes: dict[str, subprocess.Popen[Any]]) -> None:
    for process in processes.values():
        if process.poll() is None:
            process.terminate()
    for process in processes.values():
        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


def _write_fd_line(fd: int, value: str) -> None:
    payload = value.encode("utf-8")
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        _require(written > 0, "checkpoint control pipe write failed")
        offset += written


def run_worker_processes(
    *,
    run_id: str,
    topology_kind: str,
    branches: Iterable[str],
    specs: Iterable[WorkerLaunchSpec],
    source_specs: Iterable[SourceLaunchSpec] = (),
    timeout_s: float = 30.0,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    synchronized_lifecycle: bool = False,
    warmup_s: float = 0.0,
    measurement_s: float = 0.0,
    drain_timeout_s: float = 10.0,
    start_lead_s: float = 0.1,
    require_decoder_placement_verification: bool = False,
) -> RuntimeRunResult:
    _require(os.name == "posix", "direct checkpoint event pipes require a POSIX runtime")
    spec_values = list(specs)
    source_spec_values = list(source_specs)
    _require(bool(spec_values), "no checkpoint workers were configured")
    if source_spec_values:
        _require(synchronized_lifecycle, "direct admission sources require synchronized lifecycle")
        source_by_stream = {spec.stream_id: spec for spec in source_spec_values}
        _require(
            len(source_by_stream) == len(source_spec_values),
            "exactly one admission source process per logical stream is required",
        )
        _require(
            {spec.stream_id for spec in spec_values} == set(source_by_stream),
            "admission source processes do not cover every worker stream",
        )
    if synchronized_lifecycle:
        _require(warmup_s >= 0, "checkpoint warmup must be non-negative")
        _require(measurement_s > 0, "checkpoint measurement must be positive")
        _require(drain_timeout_s > 0, "checkpoint drain timeout must be positive")
        _require(start_lead_s >= 0, "checkpoint start lead must be non-negative")
        _require(
            timeout_s > start_lead_s + warmup_s + measurement_s,
            "checkpoint timeout must extend beyond the synchronized measurement window",
        )
    if require_decoder_placement_verification:
        _require(synchronized_lifecycle, "decoder placement verification requires synchronized lifecycle")
        _require(warmup_s > 0, "decoder placement verification requires a positive warmup")
    processes: dict[str, subprocess.Popen[Any]] = {}
    source_processes: dict[str, subprocess.Popen[Any]] = {}
    read_fds: dict[str, int] = {}
    source_read_fds: dict[str, int] = {}
    source_ack_write_fds: dict[str, int] = {}
    control_write_fds: dict[str, int] = {}
    status_read_fds: dict[str, int] = {}
    admission_delivery_fds: dict[str, tuple[int, int]] = {}
    bindings: list[WorkerBinding] = []
    source_bindings: list[SourceBinding] = []
    try:
        if source_spec_values:
            admission_delivery_fds = {spec.worker_id: os.pipe() for spec in spec_values}
        for spec in spec_values:
            _require(spec.worker_id not in processes, "checkpoint worker IDs must be unique")
            _require(bool(spec.command), f"checkpoint worker {spec.worker_id} has no command")
            read_fd, write_fd = os.pipe()
            control_read_fd = -1
            control_write_fd = -1
            status_read_fd = -1
            status_write_fd = -1
            if synchronized_lifecycle:
                control_read_fd, control_write_fd = os.pipe()
                status_read_fd, status_write_fd = os.pipe()
            read_fds[spec.worker_id] = read_fd
            if synchronized_lifecycle:
                control_write_fds[spec.worker_id] = control_write_fd
                status_read_fds[spec.worker_id] = status_read_fd
            environment = os.environ.copy()
            environment.update(spec.environment)
            environment.update(
                {
                    RUNTIME_EVENT_FD_ENV: str(write_fd),
                    "VAST_CHECKPOINT_WORKER_ID": spec.worker_id,
                    "VAST_CHECKPOINT_RUN_ID": run_id,
                    "VAST_CHECKPOINT_TOPOLOGY_KIND": topology_kind,
                    "VAST_CHECKPOINT_STREAM_ID": str(spec.stream_id),
                    "VAST_CHECKPOINT_BRANCH_ID": spec.branch_id or "shared",
                }
            )
            inherited_fds = [write_fd]
            if source_spec_values:
                delivery_read_fd, _ = admission_delivery_fds[spec.worker_id]
                environment[RUNTIME_ADMISSION_DATA_FD_ENV] = str(delivery_read_fd)
                inherited_fds.append(delivery_read_fd)
            if synchronized_lifecycle:
                environment[RUNTIME_CONTROL_FD_ENV] = str(control_read_fd)
                environment[RUNTIME_STATUS_FD_ENV] = str(status_write_fd)
                inherited_fds.extend((control_read_fd, status_write_fd))
            try:
                process = subprocess.Popen(spec.command, env=environment, pass_fds=tuple(inherited_fds))
            finally:
                os.close(write_fd)
                if synchronized_lifecycle:
                    os.close(control_read_fd)
                    os.close(status_write_fd)
                if source_spec_values:
                    os.close(admission_delivery_fds[spec.worker_id][0])
                    admission_delivery_fds[spec.worker_id] = (-1, admission_delivery_fds[spec.worker_id][1])
            processes[spec.worker_id] = process
            domain = f"{socket.gethostname()}:pid-{process.pid}:worker-{spec.worker_id}"
            bindings.append(
                WorkerBinding(
                    worker_id=spec.worker_id,
                    stream_id=spec.stream_id,
                    branch_id=spec.branch_id,
                    pid=process.pid,
                    execution_domain=domain,
                    native_event_source=spec.native_event_source,
                )
            )

        for spec in source_spec_values:
            _require(spec.source_process_id not in source_processes, "admission source IDs must be unique")
            _require(spec.source_process_id not in processes, "admission source ID collides with a worker ID")
            _require(bool(spec.command), f"admission source {spec.source_process_id} has no command")
            event_read_fd, event_write_fd = os.pipe()
            ack_read_fd, ack_write_fd = os.pipe()
            control_read_fd, control_write_fd = os.pipe()
            status_read_fd, status_write_fd = os.pipe()
            source_read_fds[spec.source_process_id] = event_read_fd
            source_ack_write_fds[spec.source_process_id] = ack_write_fd
            control_write_fds[spec.source_process_id] = control_write_fd
            status_read_fds[spec.source_process_id] = status_read_fd
            consumers = {
                worker.worker_id: admission_delivery_fds[worker.worker_id][1]
                for worker in spec_values
                if worker.stream_id == spec.stream_id
            }
            _require(bool(consumers), f"admission source {spec.source_process_id} has no consumers")
            environment = os.environ.copy()
            environment.update(spec.environment)
            environment.update(
                {
                    RUNTIME_ADMISSION_EVENT_FD_ENV: str(event_write_fd),
                    RUNTIME_ADMISSION_ACK_FD_ENV: str(ack_read_fd),
                    RUNTIME_ADMISSION_CONSUMER_FDS_ENV: json.dumps(consumers, separators=(",", ":")),
                    RUNTIME_CONTROL_FD_ENV: str(control_read_fd),
                    RUNTIME_STATUS_FD_ENV: str(status_write_fd),
                    "VAST_CHECKPOINT_WORKER_ID": spec.source_process_id,
                    "VAST_CHECKPOINT_RUN_ID": run_id,
                    "VAST_CHECKPOINT_TOPOLOGY_KIND": topology_kind,
                    "VAST_CHECKPOINT_STREAM_ID": str(spec.stream_id),
                    "VAST_CHECKPOINT_DATASET_ID": spec.dataset_id,
                    "VAST_CHECKPOINT_SOURCE_SHA256": spec.source_sha256,
                }
            )
            inherited_fds = [
                event_write_fd,
                ack_read_fd,
                control_read_fd,
                status_write_fd,
                *consumers.values(),
            ]
            try:
                process = subprocess.Popen(spec.command, env=environment, pass_fds=tuple(inherited_fds))
            finally:
                os.close(event_write_fd)
                os.close(ack_read_fd)
                os.close(control_read_fd)
                os.close(status_write_fd)
                for worker_id in consumers:
                    write_fd = admission_delivery_fds[worker_id][1]
                    if write_fd >= 0:
                        os.close(write_fd)
                        admission_delivery_fds[worker_id] = (-1, -1)
            source_processes[spec.source_process_id] = process
            source_bindings.append(
                SourceBinding(
                    source_process_id=spec.source_process_id,
                    stream_id=spec.stream_id,
                    pid=process.pid,
                    dataset_id=spec.dataset_id,
                    source_sha256=spec.source_sha256,
                    native_source=spec.native_source,
                )
            )
    except Exception:
        for read_fd in read_fds.values():
            os.close(read_fd)
        for fd in control_write_fds.values():
            os.close(fd)
        for fd in status_read_fds.values():
            os.close(fd)
        for fd in source_read_fds.values():
            os.close(fd)
        for fd in source_ack_write_fds.values():
            os.close(fd)
        for read_fd, write_fd in admission_delivery_fds.values():
            for fd in (read_fd, write_fd):
                if fd >= 0:
                    os.close(fd)
        _terminate_processes(processes)
        _terminate_processes(source_processes)
        raise

    admission_coordinator = (
        DirectAdmissionCoordinator(
            run_id=run_id,
            topology_kind=topology_kind,
            branches=branches,
            bindings=source_bindings,
        )
        if source_bindings
        else None
    )
    coordinator = DirectRuntimeJoinCoordinator(
        run_id=run_id,
        topology_kind=topology_kind,
        branches=branches,
        bindings=bindings,
        admission_coordinator=admission_coordinator,
    )
    events: list[dict[str, Any]] = []
    observed_ns: dict[str, int] = {}
    exit_ns: dict[str, int] = {}
    errors: list[BaseException] = []
    lifecycle_statuses: dict[str, list[RuntimeLifecycleStatus]] = {
        process_id: [] for process_id in (*processes, *source_processes)
    }
    output_lock = threading.Lock()

    def consume(worker_id: str, read_fd: int, pid: int) -> None:
        try:
            with os.fdopen(read_fd, "r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    emitted = coordinator.accept(line, observed_worker_id=worker_id, observed_pid=pid)
                    now_ns = time.monotonic_ns()
                    with output_lock:
                        for row in emitted:
                            events.append(row)
                            observed_ns[str(row["execution_id"])] = now_ns
                            if on_event is not None:
                                on_event(row)
        except BaseException as exc:
            with output_lock:
                errors.append(exc)

    def consume_status(worker_id: str, read_fd: int) -> None:
        try:
            with os.fdopen(read_fd, "r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    status = RuntimeLifecycleStatus.parse(line)
                    _require(status.worker_id == worker_id, "lifecycle status worker ID does not match its pipe")
                    with output_lock:
                        values = lifecycle_statuses[worker_id]
                        _require(
                            not values or values[-1].state != status.state,
                            "runtime lifecycle emitted a duplicate consecutive state",
                        )
                        values.append(status)
        except BaseException as exc:
            with output_lock:
                errors.append(exc)

    def consume_admission(source_process_id: str, read_fd: int, ack_write_fd: int, pid: int) -> None:
        try:
            _require(admission_coordinator is not None, "admission consumer has no coordinator")
            with os.fdopen(read_fd, "r", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    message = admission_coordinator.accept(
                        line,
                        observed_source_process_id=source_process_id,
                        observed_pid=pid,
                    )
                    _write_fd_line(ack_write_fd, f"1 ACK {message.sequence}\n")
        except BaseException as exc:
            with output_lock:
                errors.append(exc)
        finally:
            os.close(ack_write_fd)

    threads = [
        threading.Thread(
            target=consume,
            args=(worker_id, read_fds[worker_id], process.pid),
            name=f"checkpoint-events-{worker_id}",
            daemon=True,
        )
        for worker_id, process in processes.items()
    ]
    for thread in threads:
        thread.start()

    admission_threads = [
        threading.Thread(
            target=consume_admission,
            args=(
                source_process_id,
                source_read_fds[source_process_id],
                source_ack_write_fds[source_process_id],
                process.pid,
            ),
            name=f"checkpoint-admission-{source_process_id}",
            daemon=True,
        )
        for source_process_id, process in source_processes.items()
    ]
    for thread in admission_threads:
        thread.start()

    status_threads = [
        threading.Thread(
            target=consume_status,
            args=(worker_id, status_read_fds[worker_id]),
            name=f"checkpoint-status-{worker_id}",
            daemon=True,
        )
        for worker_id in status_read_fds
    ]
    for thread in status_threads:
        thread.start()

    deadline = time.monotonic() + timeout_s
    common_start_monotonic_ns = 0
    common_start_clock = ""
    window_start_timestamp_ms = 0
    window_end_timestamp_ms = 0
    drain_end_timestamp_ms = 0
    stop_monotonic_ns = 0
    stop_sent = False
    all_processes = {**processes, **source_processes}
    try:
        if synchronized_lifecycle:
            while True:
                with output_lock:
                    ready = {
                        worker_id
                        for worker_id, values in lifecycle_statuses.items()
                        if values and values[0].state == "READY"
                    }
                    current_errors = tuple(errors)
                if current_errors:
                    raise current_errors[0]
                _require(
                    not any(process.poll() is not None for process in all_processes.values()),
                    "checkpoint worker exited before the common start barrier",
                )
                if ready == set(all_processes):
                    break
                _require(time.monotonic() < deadline, "checkpoint READY barrier timed out")
                time.sleep(0.005)

            with output_lock:
                ready_statuses = {
                    worker_id: values[0]
                    for worker_id, values in lifecycle_statuses.items()
                    if values and values[0].state == "READY"
                }
            _require(
                set(ready_statuses) == set(all_processes),
                "checkpoint READY timestamps do not cover every process",
            )
            common_start_clock, native_clock_now_ns = select_native_monotonic_clock(
                status.timestamp for status in ready_statuses.values()
            )
            lead_ns = int(start_lead_s * 1_000_000_000)
            common_start_monotonic_ns = native_clock_now_ns + lead_ns
            coordinator_start_monotonic_ns = time.monotonic_ns() + lead_ns
            start_timestamp_ms = int(time.time() * 1000 + start_lead_s * 1000)
            window_start_timestamp_ms = start_timestamp_ms + int(warmup_s * 1000)
            window_end_timestamp_ms = window_start_timestamp_ms + int(measurement_s * 1000)
            drain_end_timestamp_ms = window_end_timestamp_ms + int(drain_timeout_s * 1000)
            stop_monotonic_ns = coordinator_start_monotonic_ns + int(
                (warmup_s + measurement_s) * 1_000_000_000
            )
            start_command = (
                f"{RUNTIME_LIFECYCLE_PROTOCOL_VERSION} START {common_start_monotonic_ns} "
                f"{window_start_timestamp_ms} {window_end_timestamp_ms} {drain_end_timestamp_ms}\n"
            )
            for fd in control_write_fds.values():
                _write_fd_line(fd, start_command)

            if require_decoder_placement_verification:
                worker_ids = set(processes)
                while True:
                    with output_lock:
                        verified = {
                            worker_id: values[2]
                            for worker_id, values in lifecycle_statuses.items()
                            if worker_id in worker_ids
                            and len(values) >= 3
                            and [value.state for value in values[:3]]
                            == ["READY", "STARTED", "DECODER_PLACEMENT_VERIFIED"]
                        }
                        current_errors = tuple(errors)
                    if current_errors:
                        raise current_errors[0]
                    _require(
                        not any(process.poll() is not None for process in processes.values()),
                        "checkpoint worker exited before decoder placement verification",
                    )
                    now_timestamp_ms = int(time.time() * 1000)
                    _require(
                        now_timestamp_ms < window_start_timestamp_ms,
                        "decoder placement was not verified before the measurement window",
                    )
                    if set(verified) == worker_ids:
                        _require(
                            all(value.timestamp < window_start_timestamp_ms for value in verified.values()),
                            "decoder placement verification timestamp is outside the warmup",
                        )
                        break
                    _require(time.monotonic() < deadline, "decoder placement verification timed out")
                    time.sleep(0.005)

        while len(exit_ns) != len(all_processes):
            now_ns = time.monotonic_ns()
            if synchronized_lifecycle and not stop_sent and now_ns >= stop_monotonic_ns:
                stop_command = (
                    f"{RUNTIME_LIFECYCLE_PROTOCOL_VERSION} STOP {window_end_timestamp_ms}\n"
                )
                for worker_id, fd in list(control_write_fds.items()):
                    _write_fd_line(fd, stop_command)
                    os.close(fd)
                    del control_write_fds[worker_id]
                stop_sent = True
            for process_id, process in all_processes.items():
                if process_id in exit_ns:
                    continue
                return_code = process.poll()
                if return_code is None:
                    continue
                exit_ns[process_id] = time.monotonic_ns()
                _require(return_code == 0, f"checkpoint process failed: {process_id} rc={return_code}")
            with output_lock:
                current_errors = tuple(errors)
            if current_errors:
                raise current_errors[0]
            _require(time.monotonic() < deadline, "checkpoint worker timeout expired")
            if len(exit_ns) != len(all_processes):
                time.sleep(0.005)

        for process_id, process in all_processes.items():
            process.wait()
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        _require(not any(thread.is_alive() for thread in threads), "checkpoint event pipe did not close")
        for thread in admission_threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        _require(not any(thread.is_alive() for thread in admission_threads), "checkpoint admission pipe did not close")
        for thread in status_threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        _require(not any(thread.is_alive() for thread in status_threads), "checkpoint status pipe did not close")
        if errors:
            raise errors[0]
        if synchronized_lifecycle:
            _require(stop_sent, "checkpoint workers exited before coordinated stop-admission")
            for worker_id, values in lifecycle_statuses.items():
                states = [value.state for value in values]
                decoder_gate_required = require_decoder_placement_verification and worker_id in processes
                expected_prefix = ["READY", "STARTED"]
                if decoder_gate_required:
                    expected_prefix.append("DECODER_PLACEMENT_VERIFIED")
                expected_prefix.append("ADMISSION_STOPPED")
                _require(
                    states[: len(expected_prefix)] == expected_prefix,
                    f"{worker_id}: incomplete synchronized lifecycle prefix",
                )
                _require(
                    len(states) == len(expected_prefix) + 1 and states[-1] in {"DRAINED", "CENSORED"},
                    f"{worker_id}: lifecycle must end with DRAINED or CENSORED",
                )
    except Exception:
        for fd in control_write_fds.values():
            os.close(fd)
        control_write_fds.clear()
        _terminate_processes(processes)
        _terminate_processes(source_processes)
        for thread in (*threads, *admission_threads, *status_threads):
            thread.join(timeout=2)
        raise

    lifecycle_state_values = {
        worker_id: tuple(value.state for value in values)
        for worker_id, values in lifecycle_statuses.items()
        if values
    }
    lifecycle_record_values = {
        worker_id: tuple(values)
        for worker_id, values in lifecycle_statuses.items()
        if values
    }
    terminal_ingress_rows: tuple[dict[str, Any], ...] = ()
    terminal_admission_audit: dict[str, Any] | None = None
    if admission_coordinator is not None:
        terminal_ingress_rows, terminal_admission_audit = build_runtime_terminal_ingress_ledger(
            admission_records=admission_coordinator.admission_records(),
            terminal_frame_records=coordinator.terminal_frame_records(),
            lifecycle_statuses=lifecycle_state_values,
            window_start_timestamp_ms=window_start_timestamp_ms,
            window_end_timestamp_ms=window_end_timestamp_ms,
            drain_end_timestamp_ms=drain_end_timestamp_ms,
        )

    return RuntimeRunResult(
        events=tuple(events),
        unresolved_frames=coordinator.unresolved_frames(),
        process_ids={worker_id: process.pid for worker_id, process in processes.items()},
        source_process_ids={source_id: process.pid for source_id, process in source_processes.items()},
        event_observed_ns=observed_ns,
        process_exit_ns=exit_ns,
        lifecycle_statuses=lifecycle_state_values,
        lifecycle_records=lifecycle_record_values,
        common_start_clock=common_start_clock,
        common_start_monotonic_ns=common_start_monotonic_ns,
        window_start_timestamp_ms=window_start_timestamp_ms,
        window_end_timestamp_ms=window_end_timestamp_ms,
        drain_end_timestamp_ms=drain_end_timestamp_ms,
        admission_audit=admission_coordinator.audit() if admission_coordinator is not None else None,
        terminal_ingress_rows=terminal_ingress_rows,
        terminal_admission_audit=terminal_admission_audit,
        branch_terminal_records=coordinator.branch_terminal_records(),
    )
