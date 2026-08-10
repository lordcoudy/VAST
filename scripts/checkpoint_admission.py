#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from benchmark_contract import ContractError
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG


ADMISSION_PROTOCOL_VERSION = 1
ADMISSION_PROVENANCE = "native_common_source_coordinator"
ADMISSION_MESSAGE_FIELDS = {
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
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ContractError(f"admission event {name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"admission event {name} must be an integer") from exc
    _require(str(number) == str(value) or isinstance(value, int), f"admission event {name} must be exact")
    return number


def _text(value: Any, name: str) -> str:
    result = str(value).strip()
    _require(bool(result), f"admission event {name} must be non-empty")
    return result


def _sha256(value: Any, name: str) -> str:
    result = _text(value, name).lower()
    _require(bool(_SHA256_PATTERN.fullmatch(result)), f"admission event {name} must be lowercase SHA-256")
    return result


@dataclass(frozen=True)
class SourceBinding:
    source_process_id: str
    stream_id: int
    pid: int
    dataset_id: str
    source_sha256: str
    native_source: bool


@dataclass(frozen=True)
class AdmissionMessage:
    protocol_version: int
    source_process_id: str
    sequence: int
    run_id: str
    dataset_id: str
    stream_id: int
    admission_id: str
    input_frame_key: str
    source_sha256: str
    source_cycle: int
    access_unit_pts_ns: int
    payload_sha256: str
    payload_size_bytes: int
    schedule_offset_ns: int
    admission_timestamp_ms: int
    event_provenance: str

    @classmethod
    def parse(cls, line: str) -> AdmissionMessage:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError("admission event is not valid JSON") from exc
        _require(isinstance(raw, dict), "admission event must be a JSON object")
        missing = sorted(ADMISSION_MESSAGE_FIELDS - set(raw))
        extra = sorted(set(raw) - ADMISSION_MESSAGE_FIELDS)
        _require(not missing, f"admission event is missing fields: {', '.join(missing)}")
        _require(not extra, f"admission event has unexpected fields: {', '.join(extra)}")
        message = cls(
            protocol_version=_integer(raw["protocol_version"], "protocol_version"),
            source_process_id=_text(raw["source_process_id"], "source_process_id"),
            sequence=_integer(raw["sequence"], "sequence"),
            run_id=_text(raw["run_id"], "run_id"),
            dataset_id=_text(raw["dataset_id"], "dataset_id"),
            stream_id=_integer(raw["stream_id"], "stream_id"),
            admission_id=_text(raw["admission_id"], "admission_id"),
            input_frame_key=_text(raw["input_frame_key"], "input_frame_key"),
            source_sha256=_sha256(raw["source_sha256"], "source_sha256"),
            source_cycle=_integer(raw["source_cycle"], "source_cycle"),
            access_unit_pts_ns=_integer(raw["access_unit_pts_ns"], "access_unit_pts_ns"),
            payload_sha256=_sha256(raw["payload_sha256"], "payload_sha256"),
            payload_size_bytes=_integer(raw["payload_size_bytes"], "payload_size_bytes"),
            schedule_offset_ns=_integer(raw["schedule_offset_ns"], "schedule_offset_ns"),
            admission_timestamp_ms=_integer(raw["admission_timestamp_ms"], "admission_timestamp_ms"),
            event_provenance=_text(raw["event_provenance"], "event_provenance"),
        )
        _require(message.protocol_version == ADMISSION_PROTOCOL_VERSION, "unsupported admission protocol")
        _require(message.sequence > 0, "admission event sequence must be positive")
        _require(message.stream_id >= 0, "admission stream_id must be non-negative")
        _require(message.source_cycle >= 0, "admission source_cycle must be non-negative")
        _require(message.access_unit_pts_ns >= 0, "admission access-unit PTS must be non-negative")
        _require(message.payload_size_bytes > 0, "admission payload size must be positive")
        _require(message.schedule_offset_ns >= 0, "admission schedule offset must be non-negative")
        _require(message.admission_timestamp_ms >= 0, "admission timestamp must be non-negative")
        _require(message.event_provenance == ADMISSION_PROVENANCE, "admission event provenance is not native")
        expected_id = f"{message.run_id}:{message.stream_id}:admission:{message.sequence}"
        _require(message.admission_id == expected_id, "admission_id does not bind run, stream, and sequence")
        expected_key = (
            f"{message.dataset_id}:{message.stream_id}:{message.source_sha256}:"
            f"{message.source_cycle}:{message.access_unit_pts_ns}"
        )
        _require(message.input_frame_key == expected_key, "input_frame_key does not bind the admitted access unit")
        return message


@dataclass
class _AdmissionState:
    message: AdmissionMessage
    consumers: set[str]


class DirectAdmissionCoordinator:
    """Accept source events before worker reads and preserve an auditable schedule."""

    def __init__(
        self,
        *,
        run_id: str,
        topology_kind: str,
        branches: Iterable[str],
        bindings: Iterable[SourceBinding],
    ) -> None:
        self.run_id = _text(run_id, "run_id")
        _require(topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}, "unsupported admission topology")
        self.topology_kind = topology_kind
        self.branches = tuple(str(value) for value in branches)
        _require(bool(self.branches) and len(self.branches) == len(set(self.branches)), "admission branches must be unique")
        binding_values = list(bindings)
        self.bindings = {binding.source_process_id: binding for binding in binding_values}
        _require(len(self.bindings) == len(binding_values), "source process IDs must be unique")
        _require(bool(binding_values), "at least one source coordinator is required")
        _require(all(binding.pid > 0 for binding in binding_values), "source coordinator PID must be positive")
        _require(all(binding.native_source for binding in binding_values), "source coordinator must be native")
        _require(
            len({binding.stream_id for binding in binding_values}) == len(binding_values),
            "exactly one source coordinator per logical stream is required",
        )
        _require(
            all(bool(_SHA256_PATTERN.fullmatch(binding.source_sha256)) for binding in binding_values),
            "source binding SHA-256 is invalid",
        )
        self._sequences = {binding.source_process_id: 0 for binding in binding_values}
        self._last_schedule_offset = {binding.source_process_id: -1 for binding in binding_values}
        self._last_timestamp = {binding.source_process_id: -1 for binding in binding_values}
        self._last_source_cycle: dict[str, int] = {}
        self._admissions: dict[str, _AdmissionState] = {}
        self._input_keys: set[str] = set()

    def accept(self, line: str, *, observed_source_process_id: str, observed_pid: int) -> AdmissionMessage:
        message = AdmissionMessage.parse(line)
        binding = self.bindings.get(observed_source_process_id)
        _require(binding is not None, f"unregistered source coordinator: {observed_source_process_id}")
        _require(message.source_process_id == observed_source_process_id, "admission source ID does not match its pipe")
        _require(binding.pid == observed_pid, "admission pipe is not bound to the launched source PID")
        _require(message.run_id == self.run_id, "admission run_id mismatch")
        _require(message.stream_id == binding.stream_id, "source coordinator emitted another logical stream")
        _require(message.dataset_id == binding.dataset_id, "admission dataset differs from source binding")
        _require(message.source_sha256 == binding.source_sha256, "admission source SHA-256 differs from binding")
        expected_sequence = self._sequences[observed_source_process_id] + 1
        _require(message.sequence == expected_sequence, "source admission sequence is not gap-free")
        _require(
            message.schedule_offset_ns > self._last_schedule_offset[observed_source_process_id],
            "source admission schedule offsets must be strictly increasing",
        )
        _require(
            message.admission_timestamp_ms >= self._last_timestamp[observed_source_process_id],
            "source admission timestamps must be monotonic",
        )
        previous_cycle = self._last_source_cycle.get(observed_source_process_id)
        if previous_cycle is None:
            _require(message.source_cycle == 0, "source admission must begin at source_cycle zero")
        else:
            _require(
                message.source_cycle in {previous_cycle, previous_cycle + 1},
                "source_cycle must stay constant or increment exactly once",
            )
        _require(message.admission_id not in self._admissions, "duplicate admission_id")
        _require(message.input_frame_key not in self._input_keys, "duplicate admitted input_frame_key")
        self._sequences[observed_source_process_id] = message.sequence
        self._last_schedule_offset[observed_source_process_id] = message.schedule_offset_ns
        self._last_timestamp[observed_source_process_id] = message.admission_timestamp_ms
        self._last_source_cycle[observed_source_process_id] = message.source_cycle
        self._admissions[message.admission_id] = _AdmissionState(message=message, consumers=set())
        self._input_keys.add(message.input_frame_key)
        return message

    def observe_worker_source(self, message: Any, *, consumer_id: str) -> None:
        admission_id = getattr(message, "admission_id", None)
        payload_sha256 = getattr(message, "payload_sha256", None)
        _require(bool(admission_id) and bool(payload_sha256), "worker source_read lacks direct admission linkage")
        state = self._admissions.get(str(admission_id))
        _require(state is not None, "worker source_read precedes its direct source admission")
        admitted = state.message
        _require(int(message.stream_id) == admitted.stream_id, "worker source_read stream differs from admission")
        _require(str(message.input_frame_key) == admitted.input_frame_key, "worker source_read key differs from admission")
        _require(str(payload_sha256) == admitted.payload_sha256, "worker source_read payload differs from admission")
        _require(int(message.timestamp_ms) >= admitted.admission_timestamp_ms, "worker source_read precedes admission time")
        expected_consumers = set(self.branches) if self.topology_kind == INDEPENDENT_PROCESSES else {"shared"}
        _require(consumer_id in expected_consumers, "worker source_read has an unexpected admission consumer")
        _require(consumer_id not in state.consumers, "admission consumer emitted duplicate source_read")
        state.consumers.add(consumer_id)

    def admission_records(self) -> tuple[dict[str, Any], ...]:
        """Return an immutable engineering snapshot of admitted access units."""
        expected = set(self.branches) if self.topology_kind == INDEPENDENT_PROCESSES else {"shared"}
        records: list[dict[str, Any]] = []
        for state in self._admissions.values():
            record = asdict(state.message)
            record["consumer_ids"] = tuple(sorted(state.consumers))
            record["consumer_coverage_complete"] = state.consumers == expected
            records.append(record)
        return tuple(sorted(records, key=lambda row: (int(row["stream_id"]), int(row["sequence"]))))

    def schedule_fingerprint(self) -> str:
        rows = [
            {
                "stream_id": state.message.stream_id,
                "sequence": state.message.sequence,
                "source_sha256": state.message.source_sha256,
                "source_cycle": state.message.source_cycle,
                "access_unit_pts_ns": state.message.access_unit_pts_ns,
                "payload_sha256": state.message.payload_sha256,
                "payload_size_bytes": state.message.payload_size_bytes,
                "schedule_offset_ns": state.message.schedule_offset_ns,
            }
            for state in self._admissions.values()
        ]
        rows.sort(key=lambda row: (int(row["stream_id"]), int(row["sequence"])))
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def audit(self) -> dict[str, Any]:
        expected = set(self.branches) if self.topology_kind == INDEPENDENT_PROCESSES else {"shared"}
        complete = sum(state.consumers == expected for state in self._admissions.values())
        return {
            "schema_version": 1,
            "artifact_kind": "checkpoint_direct_admission_audit",
            "claim_status": "runtime_protocol_evidence_not_terminal_ingress_ledger",
            "source_process_count": len(self.bindings),
            "admission_count": len(self._admissions),
            "complete_consumer_coverage_count": complete,
            "schedule_fingerprint_sha256": self.schedule_fingerprint(),
            "direct_source_schedule_observed": bool(self._admissions),
            "terminal_ingress_ledger_complete": False,
            "accepted_ingress_ledger_written": False,
        }


def require_matching_schedule_fingerprints(left: DirectAdmissionCoordinator, right: DirectAdmissionCoordinator) -> str:
    left_fingerprint = left.schedule_fingerprint()
    right_fingerprint = right.schedule_fingerprint()
    _require(left_fingerprint == right_fingerprint, "paired baseline/shared admission schedules differ")
    return left_fingerprint


def require_matching_persisted_schedule_fingerprints(left: dict[str, Any], right: dict[str, Any]) -> str:
    for audit in (left, right):
        _require(
            audit.get("artifact_kind") == "checkpoint_direct_admission_audit",
            "paired admission audit has an unexpected artifact kind",
        )
        _require(
            audit.get("claim_status") == "runtime_protocol_evidence_not_terminal_ingress_ledger",
            "paired admission audit has an unexpected claim status",
        )
        _require(int(audit.get("admission_count", 0) or 0) > 0, "paired admission audit is empty")
        _require(
            int(audit.get("admission_count", 0) or 0)
            == int(audit.get("complete_consumer_coverage_count", -1) or -1),
            "paired admission audit has incomplete consumer coverage",
        )
        _sha256(audit.get("schedule_fingerprint_sha256"), "schedule_fingerprint_sha256")
    left_fingerprint = str(left["schedule_fingerprint_sha256"])
    right_fingerprint = str(right["schedule_fingerprint_sha256"])
    _require(left_fingerprint == right_fingerprint, "persisted baseline/shared admission schedules differ")
    return left_fingerprint
