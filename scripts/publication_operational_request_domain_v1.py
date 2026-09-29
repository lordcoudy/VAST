"""Bounded ordinary JSON operational evidence, without capability or execution grants.

Policy/native and physical source authority remain caller-supplied. Exhaust readers
before accepting their output: final file identity, hash and count checks run at EOF.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

NATIVE_OPERATIONAL_JSONL = "native_operational_requests.v1.jsonl"
NATIVE_DOMAIN_KIND_V1 = "vast_qualification_operational_native_domain_v1"
GUARDIAN_JOURNAL_KIND_V1 = "vast_guardian_operational_request_journal_v1"
MAX_NATIVE_DOMAIN_BYTES_V1 = 64 * 1024 * 1024
MAX_NATIVE_HEADER_BYTES_V1 = 64 * 1024
MAX_NATIVE_RECORD_BYTES_V1 = 9_216
MAX_NATIVE_DECISIONS_V1 = 6_744
MAX_GUARDIAN_EVENTS_V1 = 1_000_000
MAX_GUARDIAN_BEGIN_BYTES_V1 = 768
MAX_GUARDIAN_TERMINAL_BYTES_V1 = 256
UINT64_MAX = (1 << 64) - 1
_SHA = re.compile(r"^[0-9a-f]{64}$")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
POLICIES = ("cpu_only", "gpu_only", "static_hybrid", "heft", "deadline_aware_heft",
            "queue_aware_edf", "adaptive_weights")
NATIVE_OCCURRENCE_FIELDS_V1 = frozenset({
    "schema_version", "artifact_kind", "runtime_decision_seq", "decision_id", "measurement",
    "decision_request", "accepted_record", "path", "terminal", "issued_record_sha256",
    "accepted_record_sha256", "sha256",
})
NATIVE_HEADER_FIELDS_V1 = frozenset({
    "schema_version", "artifact_kind", "record_kind", "digest_algorithm", "operation_input",
    "run_id", "context_arm_id", "system", "scenario", "codec", "policy", "deadline_ms",
    "protocol", "descriptors", "initial_state", "counts", "adaptive_history", "sha256",
})
NATIVE_COUNT_FIELDS_V1 = frozenset({
    "complete_decision_count", "measurement_decision_count", "excluded_decision_count",
    "runtime_feedback_count", "measurement_feedback_count", "excluded_feedback_count",
})
NATIVE_DESCRIPTOR_ROLES_V1 = frozenset({
    "capability_manifest", "source_plan", "model_authority", "calibration",
    "policy_request_source", "policy_coordinator_source", "execution_code_closure",
})
GUARDIAN_BEGIN_FIELDS_V1 = frozenset({
    "type", "seq", "request_seq", "connection", "local_seq", "binding", "request_id",
    "input_key", "frame_id", "pts_ns", "decision_id", "control_sha256", "at_ns", "sha256",
})
GUARDIAN_TERMINAL_FIELDS_V1 = frozenset({
    "seq", "begin_seq", "at_ns", "response", "outcome", "send", "sha256",
})
_REQUEST_FIELDS = frozenset({"schema_version", "message_type", "run_id", "worker_id",
    "input_frame_key", "trace_id", "stream_id", "frame_id", "transport_pts_ns", "branch",
    "arrival_ms", "decision_time_ms", "feature_observed_timestamp_ms", "queue_depths"})
_PATH_FIELDS = frozenset({"schema_version", "message_type", "run_id", "worker_id", "decision_id",
    "input_frame_key", "branch", "transport_pts_ns", "selected_resource", "implementation_id",
    "emitter_id", "emitter_sha256", "event_id", "timestamp_ms"})
_TERMINAL_FIELDS = frozenset({"schema_version", "message_type", "run_id", "worker_id", "decision_id",
    "input_frame_key", "branch", "transport_pts_ns", "selected_resource", "terminal_status",
    "terminal_timestamp_ms", "actual_service_ms", "detector", "backend"})


class OperationalDomainError(ValueError):
    """Malformed, incomplete, over-budget or physically changed evidence."""


def canonical_json_v1(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise OperationalDomainError("evidence is not finite canonical JSON") from exc


def payload_with_sha256_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result.pop("sha256", None)
    result["sha256"] = hashlib.sha256(canonical_json_v1(result)).hexdigest()
    return result


def _fields(value, fields, label):
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise OperationalDomainError(f"{label} fields mismatch")


def _integer(value, label, maximum=UINT64_MAX, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise OperationalDomainError(f"{label} is outside the supported integer domain")
    return value


def _text(value, label, maximum):
    if (type(value) is not str or not value or len(value) > maximum
            or not value.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise OperationalDomainError(f"{label} is outside the supported ASCII source domain")
    return value


def _sha(value, label="sha256"):
    if type(value) is not str or not _SHA.fullmatch(value):
        raise OperationalDomainError(f"{label} is invalid")
    return value


def _self_hash(value):
    if payload_with_sha256_v1(value)["sha256"] != _sha(value.get("sha256")):
        raise OperationalDomainError("evidence self hash mismatch")


def _same(left, right, label):
    if canonical_json_v1(left) != canonical_json_v1(right):
        raise OperationalDomainError(f"{label} mismatch")


def strict_json_object_v1(raw: bytes, *, max_bytes: int) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise OperationalDomainError("JSON line exceeds its byte bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise OperationalDomainError("duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise OperationalDomainError("nonfinite JSON number")
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OperationalDomainError("invalid JSON object") from exc
    if type(value) is not dict:
        raise OperationalDomainError("JSON evidence must be an object")
    return value


def validate_descriptor_v1(value):
    _fields(value, {"path", "size_bytes", "sha256"}, "descriptor")
    _text(value["path"], "descriptor.path", 512)
    _integer(value["size_bytes"], "descriptor.size_bytes", minimum=1)
    _sha(value["sha256"])


def validate_native_header_v1(header, *, require_sha=True):
    fields = NATIVE_HEADER_FIELDS_V1 if require_sha else NATIVE_HEADER_FIELDS_V1 - {"sha256"}
    _fields(header, fields, "native header")
    if len(canonical_json_v1(header)) + 1 > MAX_NATIVE_HEADER_BYTES_V1:
        raise OperationalDomainError("native header exceeds its byte bound")
    if (type(header["schema_version"]) is not int or header["schema_version"] != 1
            or header["artifact_kind"] != NATIVE_DOMAIN_KIND_V1
            or header["record_kind"] != "header" or header["digest_algorithm"] != "sha256"):
        raise OperationalDomainError("native header version/kind mismatch")
    for key, cap in (("run_id", 64), ("context_arm_id", 68)):
        _text(header[key], key, cap)
    if (header["system"] not in {"deepstream", "savant", "openvino_gva", "gstreamer_custom"}
            or header["scenario"] not in {"checkpoint_independent_processes_baseline", "checkpoint_video_dag_shared"}
            or header["codec"] not in {"h264", "h265"} or header["policy"] not in POLICIES
            or type(header["deadline_ms"]) not in {int, float} or header["deadline_ms"] != 100.0):
        raise OperationalDomainError("native header is outside the supported source scope")
    expected_protocol = {"schema_version": 1, "decision_request": "decision_request",
        "path": "path_enter", "terminal": "terminal", "source_descriptor": "policy_request_source"}
    _same(header["protocol"], expected_protocol, "native protocol")
    validate_descriptor_v1(header["operation_input"])
    _fields(header["descriptors"], NATIVE_DESCRIPTOR_ROLES_V1, "native descriptors")
    for descriptor in header["descriptors"].values():
        validate_descriptor_v1(descriptor)
    state = header["initial_state"]
    _fields(state, {"arm_id", "weights", "service_ewma_ms"}, "initial state")
    _text(state["arm_id"], "initial arm", 137)
    _same(state["weights"], {"cpu": 1.0, "gpu": 1.0}, "initial weights")
    _same(state["service_ewma_ms"], {}, "initial EWMA")
    counts = header["counts"]
    _fields(counts, NATIVE_COUNT_FIELDS_V1, "native counts")
    for key, count in counts.items():
        _integer(count, key, MAX_NATIVE_DECISIONS_V1)
    for total, measured, excluded in (("complete_decision_count", "measurement_decision_count", "excluded_decision_count"),
                                     ("runtime_feedback_count", "measurement_feedback_count", "excluded_feedback_count")):
        if counts[total] != counts[measured] + counts[excluded]:
            raise OperationalDomainError("native count partition mismatch")
    if header["adaptive_history"] is not None:
        validate_descriptor_v1(header["adaptive_history"])
        if header["policy"] != "adaptive_weights":
            raise OperationalDomainError("nonadaptive operational evidence has adaptive history")
    if require_sha:
        _self_hash(header)


def validate_native_occurrence_v1(record, *, expected_header, original_authority_validator):
    _fields(record, NATIVE_OCCURRENCE_FIELDS_V1, "native occurrence")
    if len(canonical_json_v1(record)) + 1 > MAX_NATIVE_RECORD_BYTES_V1:
        raise OperationalDomainError("native occurrence exceeds its byte bound")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1 or record["artifact_kind"] != NATIVE_DOMAIN_KIND_V1:
        raise OperationalDomainError("native occurrence version/kind mismatch")
    _integer(record["runtime_decision_seq"], "runtime sequence", MAX_NATIVE_DECISIONS_V1, 1)
    _text(record["decision_id"], "decision_id", 157)
    if type(record["measurement"]) is not bool:
        raise OperationalDomainError("measurement membership must be boolean")
    _self_hash(record)
    _sha(record["issued_record_sha256"])
    raw, accepted, path, terminal = (record[key] for key in ("decision_request", "accepted_record", "path", "terminal"))
    _fields(raw, _REQUEST_FIELDS, "original request")
    _fields(path, _PATH_FIELDS, "original path")
    _fields(terminal, _TERMINAL_FIELDS, "original terminal")
    for value, label in ((raw, "decision_request"), (path, "path_enter"), (terminal, "terminal")):
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["message_type"] != label:
            raise OperationalDomainError("original native protocol mismatch")
    validate_native_request_source_v1(raw)
    if not isinstance(accepted, Mapping) or accepted.get("record_status") != "accepted_native_runtime_decision":
        raise OperationalDomainError("original accepted record missing")
    _self_hash(accepted)
    _same(accepted["sha256"], record["accepted_record_sha256"], "original accepted hash")
    for key, value in (("decision_id", record["decision_id"]), ("decision_seq", record["runtime_decision_seq"]),
                       ("trace_id", raw["trace_id"]), ("branch", raw["branch"])):
        _same(accepted.get(key), value, key)
    request = accepted.get("request")
    if not isinstance(request, Mapping):
        raise OperationalDomainError("original normalized request missing")
    _same(request.get("arrival_ms"), float(raw["arrival_ms"]), "original arrival")
    for resource in ("cpu", "gpu"):
        _same(request["candidates"][resource]["queue_depth"], raw["queue_depths"][resource],
              f"original {resource} queue depth")
    # The coordinator serializes/clamps decision time while retaining the raw
    # worker observation. Exact max(previous, submitted) is a stream invariant.
    if float(raw["decision_time_ms"]) > float(request["decision_time_ms"]):
        raise OperationalDomainError("original submitted decision follows serialized decision")
    evidence = accepted.get("native_decision_evidence")
    if not isinstance(evidence, Mapping):
        raise OperationalDomainError("original native evidence missing")
    for key in ("run_id", "worker_id", "input_frame_key", "branch", "transport_pts_ns"):
        _same(path[key], raw[key], f"path {key}")
        _same(terminal[key], raw[key], f"terminal {key}")
        if key != "run_id":
            _same(evidence.get(key), raw[key], f"native {key}")
    for value in (path, terminal):
        _same(value["decision_id"], record["decision_id"], "original decision_id")
        _same(value["selected_resource"], accepted["selected_resource"], "original resource")
    for key in ("implementation_id", "emitter_id", "emitter_sha256", "event_id"):
        _same(path[key], evidence.get(key), key)
    _same(path["timestamp_ms"], evidence.get("path_entry_timestamp_ms"), "path timestamp")
    for key in ("terminal_status", "terminal_timestamp_ms", "actual_service_ms", "detector", "backend"):
        value = terminal[key]
        if key in {"terminal_timestamp_ms", "actual_service_ms"}:
            # C++ number(double) may spell an integral binary64 as an integer;
            # the original terminal is retained, and the existing coordinator
            # explicitly casts these two accepted evidence fields to float.
            if (type(value) not in {int, float} or len(canonical_json_v1(value)) > 24
                    or not math.isfinite(value) or value <= 0):
                raise OperationalDomainError("original terminal numeric domain mismatch")
            value = float(value)
        _same(value, evidence.get(key), key)
    if expected_header is not None:
        for key in ("system", "policy"):
            _same(accepted[key], expected_header[key], key)
        _same(raw["run_id"], expected_header["run_id"], "run_id")
        _same(accepted["arm_id"], expected_header["initial_state"]["arm_id"], "runtime arm")
    original_authority_validator(record)
    return record


def validate_native_request_source_v1(raw):
    """Supported-mode bounds before coordinator retained-state allocation."""
    _fields(raw, _REQUEST_FIELDS, "original request")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or raw["message_type"] != "decision_request":
        raise OperationalDomainError("original native request protocol mismatch")
    for key, cap in (("run_id", 64), ("worker_id", 37), ("input_frame_key", 136), ("trace_id", 108)):
        _text(raw[key], key, cap)
    _integer(raw["stream_id"], "stream_id", 5)
    _integer(raw["frame_id"], "frame_id", 280)
    _integer(raw["transport_pts_ns"], "transport_pts_ns")
    if raw["branch"] not in BRANCHES:
        raise OperationalDomainError("native request branch is unsupported")
    _fields(raw["queue_depths"], {"cpu", "gpu"}, "queue depths")
    for depth in raw["queue_depths"].values():
        _integer(depth, "queue depth", (1 << 32) - 1)
    for key in ("arrival_ms", "decision_time_ms", "feature_observed_timestamp_ms"):
        value = raw[key]
        if type(value) not in {int, float} or len(canonical_json_v1(value)) > 24 or not math.isfinite(value):
            raise OperationalDomainError("native request clock exceeds the proved numeric domain")
    if (raw["arrival_ms"] < 0 or raw["decision_time_ms"] <= 0
            or raw["feature_observed_timestamp_ms"] <= 0
            or raw["arrival_ms"] > raw["decision_time_ms"]
            or raw["feature_observed_timestamp_ms"] > raw["decision_time_ms"]):
        raise OperationalDomainError("original request clock order is invalid")


def build_native_occurrence_v1(*, runtime_decision_seq, measurement, decision_request,
                               accepted_record, path, terminal, issued_record_sha256):
    return payload_with_sha256_v1({
        "schema_version": 1, "artifact_kind": NATIVE_DOMAIN_KIND_V1,
        "runtime_decision_seq": runtime_decision_seq, "decision_id": accepted_record["decision_id"],
        "measurement": measurement, "decision_request": decision_request, "accepted_record": accepted_record,
        "path": path, "terminal": terminal, "issued_record_sha256": issued_record_sha256,
        "accepted_record_sha256": accepted_record["sha256"],
    })


def _guardian_shape(event):
    if not isinstance(event, Mapping):
        raise OperationalDomainError("guardian event must be an object")
    fields = set(event) - {"sha256"}
    if fields == GUARDIAN_BEGIN_FIELDS_V1 - {"sha256"}:
        if event["type"] != "begin":
            raise OperationalDomainError("guardian begin kind mismatch")
        _integer(event["seq"], "begin seq", MAX_GUARDIAN_EVENTS_V1 - 1, 1)
        for key, cap, minimum in (("request_seq", 500_000, 1), ("connection", 1_000_000, 1),
                                  ("local_seq", 6_744, 1), ("binding", 221, 0), ("frame_id", 280, 0)):
            _integer(event[key], key, cap, minimum)
        for key, cap in (("request_id", 64), ("input_key", 136)):
            _text(event[key], key, cap)
        if event["decision_id"] is not None:
            _text(event["decision_id"], "decision_id", 157)
        _integer(event["pts_ns"], "pts_ns")
        _sha(event["control_sha256"])
        cap = MAX_GUARDIAN_BEGIN_BYTES_V1
    elif fields == GUARDIAN_TERMINAL_FIELDS_V1 - {"sha256"}:
        seq = _integer(event["seq"], "terminal seq", MAX_GUARDIAN_EVENTS_V1, 2)
        _integer(event["begin_seq"], "begin_seq", seq - 1, 1)
        if event["response"] is not None:
            _sha(event["response"], "response")
        if event["outcome"] not in {"completed", "failed"} or event["send"] not in {"sent", "failed", "closed"}:
            raise OperationalDomainError("guardian terminal outcome mismatch")
        cap = MAX_GUARDIAN_TERMINAL_BYTES_V1
    else:
        raise OperationalDomainError("guardian event fields mismatch")
    _integer(event["at_ns"], "at_ns")
    return cap


def seal_guardian_event_v1(event, *, previous_sha256):
    cap = _guardian_shape(event)
    if "sha256" in event:
        raise OperationalDomainError("refusing to reseal a guardian event")
    result = copy.deepcopy(dict(event))
    result["sha256"] = hashlib.sha256(bytes.fromhex(_sha(previous_sha256)) + canonical_json_v1(result)).hexdigest()
    if len(canonical_json_v1(result)) + 1 > cap:
        raise OperationalDomainError("guardian event exceeds its byte bound")
    return result


def validate_guardian_event_v1(event, *, previous_sha256):
    cap = _guardian_shape(event)
    if len(canonical_json_v1(event)) + 1 > cap:
        raise OperationalDomainError("guardian event exceeds its byte bound")
    _sha(event.get("sha256"))
    unsigned = dict(event)
    unsigned.pop("sha256")
    if seal_guardian_event_v1(unsigned, previous_sha256=previous_sha256)["sha256"] != event["sha256"]:
        raise OperationalDomainError("guardian event chain mismatch")
    return event


def _table_row(rows, reference, label):
    if type(rows) is not list or len(rows) > 222:
        raise OperationalDomainError(f"{label} table exceeds supported scope")
    checked = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise OperationalDomainError(f"{label} row is invalid")
        index = _integer(row.get("id"), label, 221)
        if index in checked:
            raise OperationalDomainError(f"duplicate {label} reference")
        checked[index] = row
    if reference not in checked:
        raise OperationalDomainError(f"unknown {label} reference")
    return checked[reference]


def expand_guardian_identity_v1(header, begin):
    if set(begin) != GUARDIAN_BEGIN_FIELDS_V1:
        raise OperationalDomainError("identity expansion requires a complete begin")
    _guardian_shape(begin)
    binding = _table_row(header["bindings"], begin["binding"], "binding")
    _fields(binding, {"id", "context", "front_worker"}, "binding")
    context = _table_row(header["contexts"], binding["context"], "context")
    _fields(context, {"id", "protocol", "run_id", "arm_id", "system", "policy"}, "context")
    worker = _table_row(header["front_workers"], binding["front_worker"], "front worker")
    _fields(worker, {"id", "worker_id", "stream_id"}, "front worker")
    protocol = _table_row(header["protocols"], context["protocol"], "protocol")
    _fields(protocol, {"id", "schema_version", "message_type", "transport", "source_descriptor"}, "protocol")
    _fields(header["route"], {"branch", "resource"}, "route")
    return {"protocol": protocol["message_type"], "run_id": context["run_id"],
        "arm_id": context["arm_id"], "system": context["system"], "policy": context["policy"],
        "worker_id": worker["worker_id"], "stream_id": worker["stream_id"],
        "request_id": begin["request_id"], "input_frame_key": begin["input_key"],
        "frame_id": begin["frame_id"], "transport_pts_ns": begin["pts_ns"],
        "decision_id": begin["decision_id"], "branch": header["route"]["branch"],
        "resource": header["route"]["resource"]}


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _physical_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OperationalDomainError("evidence must be one original regular file")
    return info


def write_native_domain_v1(path, header, occurrences: Iterable, *, original_authority_validator):
    validate_native_header_v1(header)
    path = Path(path)
    digest = hashlib.sha256()
    size = complete = measured = 0
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb", buffering=64 * 1024) as stream:
        def append(payload, cap):
            nonlocal size
            line = canonical_json_v1(payload) + b"\n"
            if len(line) > cap or size + len(line) > MAX_NATIVE_DOMAIN_BYTES_V1:
                raise OperationalDomainError("native domain exceeds its byte budget")
            if stream.write(line) != len(line):
                raise OperationalDomainError("short native domain write")
            size += len(line)
            digest.update(line)
        append(header, MAX_NATIVE_HEADER_BYTES_V1)
        for record in occurrences:
            if complete >= MAX_NATIVE_DECISIONS_V1:
                raise OperationalDomainError("native domain exceeds its occurrence budget")
            validate_native_occurrence_v1(record, expected_header=header,
                                          original_authority_validator=original_authority_validator)
            if record["runtime_decision_seq"] != complete + 1:
                raise OperationalDomainError("native runtime sequence is incomplete or duplicated")
            append(record, MAX_NATIVE_RECORD_BYTES_V1)
            complete += 1
            measured += int(record["measurement"])
        _same((complete, measured, complete - measured), tuple(header["counts"][key] for key in
              ("complete_decision_count", "measurement_decision_count", "excluded_decision_count")), "native counts")
        stream.flush()
        os.fsync(stream.fileno())
    _physical_file(path)
    return {"path": str(path.resolve()), "size_bytes": size, "sha256": digest.hexdigest()}


def iter_native_domain_v1(path, *, expected_descriptor, original_authority_validator):
    path = Path(path)
    validate_descriptor_v1(expected_descriptor)
    if path.absolute() != Path(expected_descriptor["path"]).absolute():
        raise OperationalDomainError("native domain descriptor path mismatch")
    before = _physical_file(path)
    if before.st_size > MAX_NATIVE_DOMAIN_BYTES_V1 or before.st_size != expected_descriptor["size_bytes"]:
        raise OperationalDomainError("native domain file size mismatch")
    digest = hashlib.sha256()
    complete = measured = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb", buffering=64 * 1024) as stream:
        if _identity(before) != _identity(os.fstat(stream.fileno())):
            raise OperationalDomainError("native domain inode changed before read")
        def read(cap):
            line = stream.readline(cap + 1)
            if not line:
                return None
            if len(line) > cap or not line.endswith(b"\n"):
                raise OperationalDomainError("native domain line is oversized or truncated")
            value = strict_json_object_v1(line, max_bytes=cap)
            if canonical_json_v1(value) + b"\n" != line:
                raise OperationalDomainError("native domain is not canonical JSONL")
            digest.update(line)
            return value
        header = read(MAX_NATIVE_HEADER_BYTES_V1)
        validate_native_header_v1(header)
        while (record := read(MAX_NATIVE_RECORD_BYTES_V1)) is not None:
            if complete >= MAX_NATIVE_DECISIONS_V1:
                raise OperationalDomainError("native domain count exceeds supported scope")
            validate_native_occurrence_v1(record, expected_header=header,
                                          original_authority_validator=original_authority_validator)
            if record["runtime_decision_seq"] != complete + 1:
                raise OperationalDomainError("native runtime sequence is incomplete or duplicated")
            complete += 1
            measured += int(record["measurement"])
            yield record
        _same((complete, measured, complete - measured), tuple(header["counts"][key] for key in
              ("complete_decision_count", "measurement_decision_count", "excluded_decision_count")), "native counts")
        if (_identity(before) != _identity(os.fstat(stream.fileno()))
                or _identity(before) != _identity(_physical_file(path))
                or digest.hexdigest() != expected_descriptor["sha256"]):
            raise OperationalDomainError("native domain physical identity/hash changed")
