"""Reversible publication coordinates and bounded actual adaptive history.

Only publication copies are projected. Runtime records, requests, native evidence
and feedback remain byte-for-byte reconstructible from their original hashes.
"""
from __future__ import annotations

import copy
import io
import itertools
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from publication_policy_frozen_replay_v1 import (
    FEEDBACK_FIELDS_V1,
    canonical_json_v1, initial_frozen_state_v1, payload_with_sha256_v1,
    normalize_frozen_request_v1,
    replay_frozen_decision_v1, require_record_sha256_v1, validate_frozen_feedback_v1,
)

RUNTIME_HISTORY_JSONL = "publication_policy_runtime_history.jsonl"
MAX_RUNTIME_HISTORY_BYTES_V1 = 64 * 1024 * 1024
MAX_RUNTIME_HISTORY_EVENTS_V1 = 1_000_000
MAX_RUNTIME_HISTORY_LINE_BYTES_V1 = 256 * 1024
MAX_ACCEPTANCE_AGGREGATE_BYTES_V1 = 256 * 1024 * 1024
PROJECTION_FIELDS_V1 = frozenset({"schema_version", "original_worker_trace_id",
    "original_runtime_decision_seq", "issued_record_sha256", "accepted_record_sha256"})
HISTORY_HEADER_FIELDS_V1 = frozenset({"schema_version", "artifact_kind", "record_kind", "run_id",
    "arm_id", "system", "policy", "policy_contract_sha256", "engine_implementation_id", "initial_state",
    "runtime_decision_count", "runtime_feedback_count", "measurement_decision_count",
    "measurement_feedback_count", "event_count", "sha256"})
DECISION_EVENT_FIELDS_V1 = frozenset({"schema_version", "artifact_kind", "event_seq", "event_type",
    "runtime_decision_seq", "decision_id", "measurement", "issued_record_sha256",
    "accepted_record_sha256", "accepted_record", "sha256"})
FEEDBACK_EVENT_FIELDS_V1 = frozenset({"schema_version", "artifact_kind", "event_seq", "event_type",
    "runtime_feedback_seq", "decision_id", "measurement", "issued_record_sha256",
    "feedback_record_sha256", "feedback_record", "sha256"})
_SHA = re.compile(r"^[0-9a-f]{64}$")


class PublicationProjectionError(ValueError):
    """Projection, physical mapping, history or original hashes failed validation."""


def _positive_int(value: Any, field: str, *, zero: bool = False) -> int:
    if type(value) is not int or value < (0 if zero else 1):
        raise PublicationProjectionError(f"{field} must be a {'nonnegative' if zero else 'positive'} integer")
    return value


def _coordinate_int(value: Any, field: str) -> int:
    # Validated CSV rows may carry numpy integer values or decimal strings.
    if isinstance(value, bool):
        raise PublicationProjectionError(f"{field} is invalid")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PublicationProjectionError(f"{field} is invalid") from exc
    if number < 0 or str(value) != str(number):
        raise PublicationProjectionError(f"{field} is not a nonnegative integer")
    return number


def _same(left: Any, right: Any, field: str) -> None:
    if canonical_json_v1(left) != canonical_json_v1(right):
        raise PublicationProjectionError(f"{field} mismatch")


def _sha(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise PublicationProjectionError(f"{field} is invalid")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PublicationProjectionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise PublicationProjectionError(f"nonfinite JSON number: {value}")


def _json(value: Any, field: str) -> Mapping[str, Any]:
    try:
        result = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant) if isinstance(value, str) else value
    except (ValueError, TypeError, RecursionError) as exc:
        raise PublicationProjectionError(f"{field} is not a valid JSON object") from exc
    if not isinstance(result, Mapping):
        raise PublicationProjectionError(f"{field} must be an object")
    return result


def project_accepted_decision_v1(accepted: Mapping[str, Any], *, canonical_trace_id: str,
                                publication_decision_seq: int,
                                issued_record_sha256: str) -> dict[str, Any]:
    """Build a reversible copy; never mutate the accepted/issued live objects."""
    replay_frozen_decision_v1(accepted)
    if accepted["record_status"] != "accepted_native_runtime_decision":
        raise PublicationProjectionError("only accepted native decisions can be projected")
    _positive_int(publication_decision_seq, "publication decision_seq")
    if type(canonical_trace_id) is not str or not canonical_trace_id.strip():
        raise PublicationProjectionError("canonical trace_id is invalid")
    original_issued = copy.deepcopy(dict(accepted))
    original_issued["record_status"] = "replayable_not_runtime_accepted"
    original_issued["native_decision_evidence"] = None
    original_issued = payload_with_sha256_v1(original_issued)
    if original_issued["sha256"] != _sha(issued_record_sha256, "issued_record_sha256"):
        raise PublicationProjectionError("original issued hash mismatch")
    result = copy.deepcopy(dict(accepted))
    result["publication_projection"] = {
        "schema_version": 1, "original_worker_trace_id": accepted["trace_id"],
        "original_runtime_decision_seq": accepted["decision_seq"],
        "issued_record_sha256": issued_record_sha256, "accepted_record_sha256": accepted["sha256"],
    }
    result["trace_id"] = result["request"]["trace_id"] = canonical_trace_id
    result["decision_seq"] = result["request"]["decision_seq"] = publication_decision_seq
    result = payload_with_sha256_v1(result)
    reconstruct_original_decision_v1(result)
    return result


def reconstruct_original_decision_v1(record: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Restore and physically verify the original accepted and issued payloads."""
    require_record_sha256_v1(record)
    metadata = record.get("publication_projection")
    if not isinstance(metadata, Mapping) or set(metadata) != PROJECTION_FIELDS_V1:
        raise PublicationProjectionError("publication_projection fields have drifted")
    if type(metadata["schema_version"]) is not int or metadata["schema_version"] != 1:
        raise PublicationProjectionError("unsupported publication_projection version")
    _positive_int(metadata["original_runtime_decision_seq"], "original_runtime_decision_seq")
    _positive_int(record.get("decision_seq"), "publication decision_seq")
    if record.get("record_status") != "accepted_native_runtime_decision":
        raise PublicationProjectionError("projected decision is not native runtime accepted")
    request = record.get("request")
    if not isinstance(request, Mapping):
        raise PublicationProjectionError("projected request is missing")
    _same(normalize_frozen_request_v1(request), request, "projected normalized request")
    for field in ("trace_id", "decision_seq", "decision_id", "branch"):
        _same(record.get(field), request.get(field), f"projected request {field}")
    accepted = copy.deepcopy(dict(record))
    accepted.pop("publication_projection")
    accepted["trace_id"] = accepted["request"]["trace_id"] = metadata["original_worker_trace_id"]
    accepted["decision_seq"] = accepted["request"]["decision_seq"] = metadata["original_runtime_decision_seq"]
    accepted = payload_with_sha256_v1(accepted)
    if accepted["sha256"] != _sha(metadata["accepted_record_sha256"], "accepted_record_sha256"):
        raise PublicationProjectionError("original accepted hash mismatch")
    replay_frozen_decision_v1(accepted)
    issued = copy.deepcopy(accepted)
    issued["record_status"] = "replayable_not_runtime_accepted"
    issued["native_decision_evidence"] = None
    issued = payload_with_sha256_v1(issued)
    if issued["sha256"] != _sha(metadata["issued_record_sha256"], "issued_record_sha256"):
        raise PublicationProjectionError("original issued hash mismatch")
    replay_frozen_decision_v1(issued)
    return accepted, issued


def _native_coordinates(record: Mapping[str, Any]) -> Mapping[str, Any]:
    evidence = record["native_decision_evidence"]
    if evidence.get("terminal_status") != "completed":
        raise PublicationProjectionError("original native decision has no completed terminal")
    for field in ("worker_id", "input_frame_key", "detector", "backend"):
        if type(evidence.get(field)) is not str or not evidence[field].strip():
            raise PublicationProjectionError(f"original native {field} is missing")
    _positive_int(evidence.get("transport_pts_ns"), "native transport_pts_ns", zero=True)
    times = {}
    for field in ("path_entry_timestamp_ms", "terminal_timestamp_ms", "actual_service_ms"):
        value = evidence.get(field)
        if isinstance(value, bool):
            raise PublicationProjectionError(f"original native {field} is invalid")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise PublicationProjectionError(f"original native {field} is invalid") from exc
        if not math.isfinite(number) or number <= 0:
            raise PublicationProjectionError(f"original native {field} is invalid")
        times[field] = number
    if times["terminal_timestamp_ms"] < times["path_entry_timestamp_ms"]:
        raise PublicationProjectionError("native terminal precedes selected path")
    return evidence


def _authority(record: Mapping[str, Any], callback: Callable | None) -> None:
    if callback is None:
        return
    result = callback(record)
    if result is not None and result is not True and not (
        isinstance(result, Mapping) and result.get("passed") is True
    ):
        raise PublicationProjectionError("actual capability/native authority rejected original record")


def _ingress_mapping(rows: Sequence[Mapping[str, Any]] | Any) -> dict[str, tuple[str, int, int]]:
    if rows is None:
        raise PublicationProjectionError("projected decisions require validated accepted-ingress mapping")
    if hasattr(rows, "to_dict") and not isinstance(rows, Mapping):
        rows = rows.to_dict(orient="records")
    result = {}
    coordinates = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise PublicationProjectionError("accepted-ingress row must be an object")
        key, trace = row.get("input_frame_key"), row.get("trace_id")
        if type(key) is not str or not key.strip() or type(trace) is not str or not trace.strip():
            raise PublicationProjectionError("accepted-ingress input key/trace is invalid")
        coordinate = (trace, _coordinate_int(row.get("stream_id"), "ingress stream_id"),
                      _coordinate_int(row.get("frame_id"), "ingress frame_id"))
        if key in result or coordinate in coordinates:
            raise PublicationProjectionError("accepted-ingress mapping is ambiguous")
        result[key], coordinates[coordinate] = coordinate, key
    if not result:
        raise PublicationProjectionError("accepted-ingress mapping is empty")
    return result


def _history_line(record: Mapping[str, Any]) -> bytes:
    line = canonical_json_v1(record) + b"\n"
    if len(line) > MAX_RUNTIME_HISTORY_LINE_BYTES_V1:
        raise PublicationProjectionError("runtime history record exceeds line byte bound")
    return line


def serialize_runtime_history_v1(header: Mapping[str, Any], events: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    event_count = 0
    for ordinal, record in enumerate(itertools.chain((header,), events)):
        if ordinal:
            event_count += 1
            if event_count > MAX_RUNTIME_HISTORY_EVENTS_V1:
                raise PublicationProjectionError("runtime history exceeds event count bound")
        line = _history_line(record)
        if buffer.tell() + len(line) > MAX_RUNTIME_HISTORY_BYTES_V1:
            raise PublicationProjectionError("runtime history exceeds file byte bound")
        buffer.write(line)
    if event_count != header.get("event_count"):
        raise PublicationProjectionError("runtime history serialized event count mismatch")
    return buffer.getvalue()


def read_runtime_history_v1(path: Path) -> dict[str, Any]:
    """Read with fixed byte/line/event limits before allocating decoded records."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_RUNTIME_HISTORY_BYTES_V1:
        raise PublicationProjectionError("runtime history is missing or exceeds file byte bound")
    records = []
    byte_count = 0
    with path.open("rb") as stream:
        while True:
            line = stream.readline(MAX_RUNTIME_HISTORY_LINE_BYTES_V1 + 1)
            if not line:
                break
            byte_count += len(line)
            if byte_count > MAX_RUNTIME_HISTORY_BYTES_V1 or len(line) > MAX_RUNTIME_HISTORY_LINE_BYTES_V1:
                raise PublicationProjectionError("runtime history exceeds byte bound")
            if len(records) > MAX_RUNTIME_HISTORY_EVENTS_V1:
                raise PublicationProjectionError("runtime history exceeds event count bound")
            if not line.endswith(b"\n"):
                raise PublicationProjectionError("runtime history is truncated")
            try:
                record = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                raise PublicationProjectionError("runtime history is not strict JSONL") from exc
            if not isinstance(record, dict) or _history_line(record) != line:
                raise PublicationProjectionError("runtime history line is not canonical")
            require_record_sha256_v1(record)
            records.append(record)
    if not records:
        raise PublicationProjectionError("runtime history has no header")
    return {"header": records[0], "events": records[1:]}


def _validate_history(header, events, *, accepted, issued, feedback, mapping, run_id, callback):
    if set(header) != HISTORY_HEADER_FIELDS_V1 or header["schema_version"] != 1 or type(header["schema_version"]) is not int:
        raise PublicationProjectionError("runtime history header schema has drifted")
    if header["artifact_kind"] != "vast_publication_policy_runtime_history_v1" or header["record_kind"] != "header":
        raise PublicationProjectionError("runtime history header identity has drifted")
    sample = next(iter(accepted.values()))
    for field in ("arm_id", "system", "policy", "policy_contract_sha256", "engine_implementation_id"):
        _same(header[field], sample[field], f"history {field}")
    if header["policy"] != "adaptive_weights" or header["run_id"] != run_id:
        raise PublicationProjectionError("runtime history run/policy mismatch")
    initial = initial_frozen_state_v1(header["arm_id"])
    _same(header["initial_state"], initial, "actual initial reset")
    counts = {field: _positive_int(header[field], field) for field in (
        "runtime_decision_count", "runtime_feedback_count", "measurement_decision_count", "measurement_feedback_count", "event_count")}
    if counts["event_count"] != len(events) or counts["event_count"] > MAX_RUNTIME_HISTORY_EVENTS_V1:
        raise PublicationProjectionError("runtime history event count mismatch")
    if counts["runtime_decision_count"] != counts["runtime_feedback_count"] or counts["event_count"] != 2 * counts["runtime_decision_count"]:
        raise PublicationProjectionError("runtime history has incomplete terminal feedback closure")
    if counts["measurement_decision_count"] != len(accepted) or counts["measurement_feedback_count"] != len(feedback):
        raise PublicationProjectionError("runtime history measurement count mismatch")
    measured_feedback = {}
    for record in feedback:
        require_record_sha256_v1(record)
        if set(record) != FEEDBACK_FIELDS_V1 or record["decision_id"] in measured_feedback:
            raise PublicationProjectionError("measurement feedback duplicate/schema mismatch")
        measured_feedback[record["decision_id"]] = record
    if set(measured_feedback) != set(accepted):
        raise PublicationProjectionError("measurement feedback has missing/orphan decisions")
    state = initial
    runtime_issued = {}
    runtime_accepted = {}
    runtime_native_event_ids = set()
    applied = set()
    decision_seq = feedback_seq = 0
    measured_decision_order, measured_feedback_order = [], []
    feedback_rows = []
    for ordinal, event in enumerate(events, 1):
        fields = DECISION_EVENT_FIELDS_V1 if event.get("event_type") == "decision_issued" else FEEDBACK_EVENT_FIELDS_V1
        if set(event) != fields or type(event["schema_version"]) is not int or event["schema_version"] != 1:
            raise PublicationProjectionError("runtime history event schema has drifted")
        if event["artifact_kind"] != "vast_publication_policy_runtime_history_event_v1" or type(event["measurement"]) is not bool:
            raise PublicationProjectionError("runtime history event identity has drifted")
        if _positive_int(event["event_seq"], "event_seq") != ordinal:
            raise PublicationProjectionError("runtime history event sequence is not contiguous")
        decision_id = event["decision_id"]
        measurement = event["measurement"]
        if measurement != (decision_id in accepted):
            raise PublicationProjectionError("runtime history measurement membership mismatch")
        if event["event_type"] == "decision_issued":
            decision_seq += 1
            if _positive_int(event["runtime_decision_seq"], "runtime_decision_seq") != decision_seq or decision_id in runtime_issued:
                raise PublicationProjectionError("runtime history decision sequence/duplicate mismatch")
            if measurement:
                if event["accepted_record"] is not None:
                    raise PublicationProjectionError("measurement history must reference original accepted record")
                original, raw_issued = accepted[decision_id], issued[decision_id]
                measured_decision_order.append(decision_id)
            else:
                original = event["accepted_record"]
                if not isinstance(original, Mapping) or original.get("record_status") != "accepted_native_runtime_decision":
                    raise PublicationProjectionError("excluded decision has no original accepted closure")
                replay_frozen_decision_v1(original)
                raw_issued = copy.deepcopy(dict(original))
                raw_issued["record_status"] = "replayable_not_runtime_accepted"
                raw_issued["native_decision_evidence"] = None
                raw_issued = payload_with_sha256_v1(raw_issued)
            for field in ("arm_id", "system", "policy", "policy_contract_sha256", "engine_implementation_id"):
                _same(original[field], header[field], f"history decision {field}")
            if original["decision_id"] != decision_id or original["decision_seq"] != decision_seq:
                raise PublicationProjectionError("runtime history original decision coordinates mismatch")
            if event["issued_record_sha256"] != raw_issued["sha256"] or event["accepted_record_sha256"] != original["sha256"]:
                raise PublicationProjectionError("runtime history original decision hash mismatch")
            native = _native_coordinates(original)
            if native["event_id"] in runtime_native_event_ids:
                raise PublicationProjectionError("duplicate original native event_id in runtime history")
            runtime_native_event_ids.add(native["event_id"])
            if measurement != (native["input_frame_key"] in mapping):
                raise PublicationProjectionError("runtime history omits/substitutes accepted measurement cohort")
            replay_frozen_decision_v1(raw_issued, expected_policy_contract_sha256=header["policy_contract_sha256"], expected_state=state)
            _authority(original, callback)
            runtime_issued[decision_id] = raw_issued
            runtime_accepted[decision_id] = original
        elif event["event_type"] == "feedback_applied":
            feedback_seq += 1
            if _positive_int(event["runtime_feedback_seq"], "runtime_feedback_seq") != feedback_seq:
                raise PublicationProjectionError("runtime history feedback sequence is not contiguous")
            if decision_id not in runtime_issued or decision_id in applied:
                raise PublicationProjectionError("runtime history feedback is duplicate/orphan/before issuance")
            if event["issued_record_sha256"] != runtime_issued[decision_id]["sha256"]:
                raise PublicationProjectionError("runtime feedback admission issued hash mismatch")
            if measurement:
                if event["feedback_record"] is not None:
                    raise PublicationProjectionError("measurement history must reference original feedback")
                record = measured_feedback[decision_id]
                measured_feedback_order.append(decision_id)
            else:
                record = event["feedback_record"]
                if not isinstance(record, Mapping):
                    raise PublicationProjectionError("excluded original feedback is missing")
            if record.get("decision_id") != decision_id or event["feedback_record_sha256"] != record.get("sha256"):
                raise PublicationProjectionError("runtime history original feedback hash/identity mismatch")
            native = runtime_accepted[decision_id]["native_decision_evidence"]
            if record.get("actual_service_ms") != native["actual_service_ms"] or record.get("completed_at_ms") != native["terminal_timestamp_ms"]:
                raise PublicationProjectionError("runtime feedback differs from original native terminal")
            state = validate_frozen_feedback_v1(record, runtime_issued[decision_id], state)
            applied.add(decision_id)
            if measurement:
                feedback_rows.append({"schema_version": 1, "run_id": run_id, "policy": "adaptive_weights",
                    "feedback_seq": len(feedback_rows) + 1, "decision_id": decision_id,
                    "completed_at_ms": record["completed_at_ms"], "actual_service_ms": record["actual_service_ms"],
                    "outcome": record["outcome"], "policy_feedback_claim_eligible": True})
        else:
            raise PublicationProjectionError("runtime history event_type is unsupported")
    if decision_seq != counts["runtime_decision_count"] or feedback_seq != counts["runtime_feedback_count"] or set(runtime_issued) != applied:
        raise PublicationProjectionError("runtime history lacks full original terminal closure")
    if measured_decision_order != list(accepted) or measured_feedback_order != [record["decision_id"] for record in feedback]:
        raise PublicationProjectionError("measurement decision/feedback order differs from actual runtime history")
    return feedback_rows


def validate_published_decisions_v1(records: Sequence[Mapping[str, Any]], csv_rows: Sequence[Mapping[str, Any]], *,
    ingress_rows=None, history_path: Path | None = None, feedback_records=None,
    authority_callback: Callable | None = None, expected_policy_contract_sha256: str | None = None) -> dict[str, Any]:
    """Validate canonical copies and actual replay; callers own physical custody."""
    if not records:
        raise PublicationProjectionError("publication decisions are empty")
    projected = ["publication_projection" in record for record in records]
    if not any(projected):
        if history_path is not None:
            raise PublicationProjectionError("unprojected evidence cannot expose runtime history")
        return {"projected": False, "original_accepted_records": list(records), "original_issued_records": [],
                "runtime_history_verified": False, "feedback_rows": []}
    if not all(projected):
        raise PublicationProjectionError("mixed projected/unprojected decisions in one arm")
    if hasattr(csv_rows, "to_dict"):
        csv_rows = csv_rows.to_dict(orient="records")
    mapping = _ingress_mapping(ingress_rows)
    rows_by_id = {}
    run_ids = set()
    for row in csv_rows:
        decision_id = row.get("decision_id")
        if decision_id in rows_by_id:
            raise PublicationProjectionError("duplicate CSV decision_id")
        rows_by_id[decision_id] = row
        run_ids.add(row.get("run_id"))
    if len(run_ids) != 1 or len(rows_by_id) != len(records):
        raise PublicationProjectionError("CSV decision count/run identity mismatch")
    run_id = next(iter(run_ids))
    originals, issued = {}, {}
    identity = None
    branch_coordinates = set()
    native_event_ids = set()
    previous_runtime_seq = 0
    for ordinal, record in enumerate(records, 1):
        original, raw_issued = reconstruct_original_decision_v1(record)
        replay_frozen_decision_v1(raw_issued, expected_policy_contract_sha256=expected_policy_contract_sha256)
        current_identity = tuple(original[field] for field in ("arm_id", "system", "policy", "policy_contract_sha256", "engine_implementation_id"))
        if identity is not None and identity != current_identity:
            raise PublicationProjectionError("publication arm/system/policy identity is mixed")
        identity = current_identity
        decision_id = record["decision_id"]
        if decision_id in originals or decision_id not in rows_by_id:
            raise PublicationProjectionError("publication decision duplicate/CSV mismatch")
        if record["decision_seq"] != ordinal or original["decision_seq"] <= previous_runtime_seq:
            raise PublicationProjectionError("publication/runtime decision order is not dense/increasing")
        previous_runtime_seq = original["decision_seq"]
        row = rows_by_id[decision_id]
        if any(row.get(field) != value for field, value in (
            ("decision_mode", "applied"), ("decision_provenance", "native_scheduler_trace"),
            ("trace_completeness", "full"), ("causal_trace_completeness", "full"),
            ("telemetry_source", "native"), ("policy_version", original["engine_implementation_id"]),
        )):
            raise PublicationProjectionError("publication CSV is not the same full native applied decision")
        for field, csv_field in (("trace_id", "trace_id"), ("branch", "stage"), ("policy", "policy"),
                                  ("selected_resource", "resource"), ("selected_implementation_id", "decision")):
            if record[field] != row.get(csv_field):
                raise PublicationProjectionError(f"publication CSV {field} mismatch")
        if _coordinate_int(row.get("decision_seq"), "CSV decision_seq") != ordinal:
            raise PublicationProjectionError("publication CSV decision_seq mismatch")
        native = _native_coordinates(original)
        coordinate = mapping.get(native["input_frame_key"])
        actual_coordinate = (row.get("trace_id"), _coordinate_int(row.get("stream_id"), "CSV stream_id"),
                             _coordinate_int(row.get("frame_id"), "CSV frame_id"))
        if coordinate != actual_coordinate:
            raise PublicationProjectionError("physical accepted-ingress/native input-frame mapping mismatch")
        branch_coordinate = (native["input_frame_key"], original["branch"])
        if branch_coordinate in branch_coordinates:
            raise PublicationProjectionError("duplicate publication input-frame/branch decision")
        branch_coordinates.add(branch_coordinate)
        if native["event_id"] in native_event_ids:
            raise PublicationProjectionError("duplicate publication original native event_id")
        native_event_ids.add(native["event_id"])
        provenance = _json(row.get("feature_provenance_json"), "CSV feature provenance")
        queue = provenance.get("native_queue_depths")
        if not isinstance(queue, Mapping) or queue.get("source_trace_id") != original["trace_id"] or queue.get("source") != "native_worker_socket:" + native["worker_id"]:
            raise PublicationProjectionError("original worker trace/source provenance mismatch")
        _authority(original, authority_callback)
        originals[decision_id], issued[decision_id] = original, raw_issued
    feedback_records = [] if feedback_records is None else list(feedback_records)
    feedback_rows = []
    verified = False
    if identity[2] == "adaptive_weights":
        if history_path is None:
            raise PublicationProjectionError("projected adaptive decisions require actual runtime history")
        history = read_runtime_history_v1(history_path)
        feedback_rows = _validate_history(history["header"], history["events"], accepted=originals,
            issued=issued, feedback=feedback_records, mapping=mapping, run_id=run_id, callback=authority_callback)
        verified = True
    elif history_path is not None or feedback_records:
        raise PublicationProjectionError("non-adaptive projection cannot expose history or feedback")
    return {"projected": True, "original_accepted_records": list(originals.values()),
            "original_issued_records": list(issued.values()), "runtime_history_verified": verified,
            "feedback_rows": feedback_rows}
