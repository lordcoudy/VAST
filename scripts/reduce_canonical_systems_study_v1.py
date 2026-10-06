"""Bounded finite-study raw reconciliation, without publication/hardware authority.

The driver validates original native/policy/guardian records and physical closure,
then passes decoded original rows here. This module verifies their numerical joins;
it never turns a closure flag, pilot, or synthetic fixture into a hardware grant.
"""
from __future__ import annotations
import hashlib
import argparse
import json
import math
import os
from pathlib import Path
import stat
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical_systems_study_plan_v1 import stream_schedule, validate_study_plan

MAX_FILE_BYTES = 192 * 1024 * 1024  # Amendment7: measured worst file ~58 MiB.
MAX_ROWS = 100_000
MAX_ROW_BYTES = 64 * 1024  # Existing original native/guardian header cap.
MAX_ARM_ROWS = 250_000
MAX_FDS = 128
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024  # Amendment7: measured closure ~3.9 MiB.
MAX_INPUT_FILES = 2048
MAX_CAMPAIGN_BYTES = 24 * 1024 * 1024 * 1024  # Amendment7: equals the plan campaign limit.


def _deadline(deadline):
    if deadline is not None:
        _require(type(deadline) in (int, float) and math.isfinite(deadline)
                 and time.monotonic() < deadline, "original reduction deadline exceeded")


def _bounded_size(value, maximum):
    size = 0
    try:
        for chunk in json.JSONEncoder(separators=(",", ":"), allow_nan=False).iterencode(value):
            size += len(chunk.encode("utf-8"))
            _require(size <= maximum, "decoded raw arm byte cap")
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReductionError("decoded raw finite JSON/byte bound: " + str(exc)) from exc
    return size


class ReductionError(ValueError):
    """Foreign, inconsistent, incomplete or physically drifted retained input."""


def _require(value, message):
    if not value:
        raise ReductionError(message)


def _integer(value, label, minimum=0):
    _require(type(value) is int and minimum <= value < 2**64, label + " integer bound")
    return value


def _number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             label + " finite nonnegative bound")
    return value


def distribution(values, *, signed=False):
    """Nearest-rank quantiles; absence is undefined, never a fabricated zero."""
    _require(len(values) <= MAX_ARM_ROWS, "distribution count cap")
    if signed:
        _require(all(type(v) in (int, float) and math.isfinite(v) for v in values), "signed distribution finite bound")
        ordered = sorted(values)
    else:
        ordered = sorted(_number(v, "distribution") for v in values)
    n = len(ordered)
    return {"n": n, "p50": ordered[math.ceil(.50*n)-1] if n else None,
            "p95": ordered[math.ceil(.95*n)-1] if n else None,
            "p99": ordered[math.ceil(.99*n)-1] if n else None,
            "mean": statistics.fmean(ordered) if n else None,
            "minimum": ordered[0] if n else None, "maximum": ordered[-1] if n else None}


def _clock(domain, clock):
    _require(type(domain) is dict and domain.get("clock") == clock,
             "clock domain missing/wrong clock")
    for field in ("boot_id", "time_namespace"):
        _require(type(domain.get(field)) is str and bool(domain[field])
                 and domain[field].lower() != "unknown", "clock domain unknown")
    return tuple(domain[k] for k in ("clock", "boot_id", "time_namespace"))


def _waits(rows):
    samples = {kind: {"wait": [], "residence": [], "fractions": [], "unknown": 0,
                      "backend": []} for kind in ("native_client", "bridge_route", "worker")}
    seen = set()
    domains, worker_unknown = [], False
    for row in rows:
        _require(type(row) is dict and row.get("kind") in samples, "foreign wait kind")
        kind, request = row["kind"], row.get("request_id")
        _require(type(request) is str and 0 < len(request) <= 256, "wait request binding")
        domain = row.get("clock_domain")
        unknown_worker = kind == "worker" and type(domain) is dict and any(
            domain.get(k) in (None, "unknown", "UNKNOWN") for k in ("pid", "boot_id", "time_namespace"))
        if unknown_worker:
            _require(domain.get("clock") == "CLOCK_MONOTONIC", "worker clock source")
            worker_identity = row.get("worker_identity")
            _require(type(worker_identity) is dict and type(worker_identity.get("worker_id")) is str
                     and 0 < len(worker_identity["worker_id"]) <= 128, "worker identity missing")
            capability = worker_identity.get("capability_sha256")
            _require(type(capability) is str and len(capability) == 64
                     and all(c in "0123456789abcdef" for c in capability), "worker identity capability binding")
            identity = (kind, request, worker_identity["worker_id"])
            worker_unknown = True
        else:
            _clock(domain, "CLOCK_MONOTONIC")
            _integer(domain.get("pid"), "wait owner PID", 1)
            identity = (kind, request, domain["pid"])
        _require(identity not in seen, "duplicate wait observation")
        seen.add(identity)
        if domain not in domains:
            domains.append(domain)
        sample = samples[kind]
        if kind == "worker":
            values = [row.get(k) for k in ("received_ns", "inference_started_ns",
                      "inference_finished_ns", "completed_ns")]
            if any(v is None for v in values):
                sample["unknown"] += 1
                continue
            values = [_integer(v, "worker self clock") for v in values]
            _require(values == sorted(values), "worker self clock order")
            backend = values[2] - values[1]
            if "inference_latency_ns" in row:
                _require(row["inference_latency_ns"] == backend, "worker inference interval mismatch")
            sample["backend"].append(backend)
            sample["residence"].append(values[3] - values[0])
        else:
            attempt = _integer(row.get("attempt_ns"), "wait attempt")
            released = _integer(row.get("released_ns"), "wait release")
            _require(released >= attempt, "wait residence order")
            acquired, reply = row.get("acquired_ns"), row.get("reply_ns")
            if acquired is None or reply is None:
                sample["unknown"] += 1
                continue
            acquired = _integer(acquired, "wait acquired")
            reply = _integer(reply, "wait reply")
            _require(attempt <= acquired <= reply <= released, "wait self clock order")
            wait, residence = acquired - attempt, released - attempt
            sample["wait"].append(wait)
            sample["residence"].append(residence)
            if residence:
                sample["fractions"].append(wait/residence)
    result = {kind: {"wait_ns": distribution(s["wait"]),
                    "residence_ns": distribution(s["residence"]), "unknown": s["unknown"],
                    "median_wait_fraction": statistics.median(s["fractions"]) if s["fractions"] else None}
              for kind, s in samples.items()}
    result["worker"]["backend_interval_ns"] = distribution(samples["worker"]["backend"])
    result["worker"]["received_label"] = "accepted/verified after sealed-memfd check"
    result["worker"]["backend_label"] = "private mapping/backend/copies; not pure GPU kernel time"
    result["worker"]["namespace_identity_unknown"] = worker_unknown
    result["clock_domains"] = domains
    result["cross_process_monotonic_subtraction"] = False
    result["queue_wait"] = "unknown"
    return result


def _slot_binding(row, slots, run_id, *, source=False):
    _require(type(row) is dict and row.get("run_id") == run_id, "foreign original run")
    key = row.get("input_frame_key")
    _require(type(key) is str and key in slots, "foreign source key")
    slot = slots[key]
    expected = {"stream_id": slot["stream_id"], "source_cycle": 0,
                "access_unit_pts_ns": slot["access_unit_pts_ns"],
                "payload_sha256": slot["payload_sha256"]}
    if source:
        expected.update(derived_ordinal=slot["derived_ordinal"],
                        planned_schedule_offset_ns=slot["schedule_offset_ns"])
    else:
        expected.update(payload_size_bytes=slot["payload_size_bytes"],
                        schedule_offset_ns=slot["schedule_offset_ns"])
    _require(all(type(row.get(k)) is type(v) and row[k] == v for k, v in expected.items()),
             "source payload/PTS/schedule binding mismatch")
    for k, v in (("source_sha256", slot["source_sha256"]), ("sequence", slot["source_sequence"])):
        if k in row:
            _require(type(row[k]) is type(v) and row[k] == v, "source sequence/media identity mismatch")
    _require(slot["planned"], "source offered outside original STOP window")
    return key


def _runtime_dispositions(closure, slots, admissions, measured, run_id):
    """Original engineering ledger is a disposition, never a native completion substitute."""
    if "runtime_ledger" not in closure:
        return {}
    rows = closure["runtime_ledger"]
    _require(type(rows) is list and len(rows) <= 2652, "original runtime ledger count cap")
    lifecycle = closure.get("lifecycle_statuses")
    _require(type(lifecycle) is dict and bool(lifecycle) and all(type(v) in (list, tuple)
             and bool(v) and v[-1] in {"DRAINED", "CENSORED"} for v in lifecycle.values()),
             "original runtime lifecycle is not terminal")
    start, end, drain = [_number(closure.get(k), "original runtime phase") for k in
                         ("window_start_timestamp_ms", "window_end_timestamp_ms", "drain_end_timestamp_ms")]
    _require(start < end <= drain <= end+10_000, "original runtime window/drain bounds")
    result = {}
    for row in rows:
        key = _slot_binding(row, slots, run_id)
        _require(key in measured and key in admissions and key not in result, "runtime ledger foreign/duplicate admission")
        _require(row.get("frame_id") == slots[key]["derived_ordinal"] and
                 row.get("ingress_timestamp_ms") == admissions[key]["admission_timestamp_ms"], "runtime ledger admission binding")
        _require(all(row.get(k) == closure[k] for k in
                 ("window_start_timestamp_ms", "window_end_timestamp_ms", "drain_end_timestamp_ms")),
                 "original runtime ledger phase mismatch")
        status = row.get("terminal_status")
        timestamp = _number(row.get("terminal_timestamp_ms"), "runtime terminal timestamp")
        _require(admissions[key]["admission_timestamp_ms"] <= timestamp <= drain, "runtime terminal outside original drain")
        if status == "censored":
            _require(row.get("terminal_provenance") == "explicit_censoring_at_drain_end"
                     and timestamp == drain, "runtime censor lacks original drain disposition")
        elif status == "drop":
            _require(row.get("terminal_provenance") == "native_drop_event", "runtime drop is not original native policy telemetry")
        elif status == "completed":
            _require(row.get("terminal_provenance") == "native_completion_event", "runtime completion is not native telemetry")
        else:
            raise ReductionError("unknown original runtime disposition")
        result[key] = status
    _require(set(result) == set(admissions) & set(measured), "original runtime ledger admission membership incomplete")
    return result


def _native_queue_drop(record, closure, admissions, slots, arm, branches):
    """Verify original v3 queue telemetry, without inventing a policy/guardian call."""
    terminal, event = record.get("branch_terminal"), record.get("original_event")
    _require(type(terminal) is dict and type(event) is dict, "native queue drop original records missing")
    key, branch = terminal.get("input_frame_key"), terminal.get("branch_id")
    _require(type(key) is str and key in admissions and branch in branches, "native queue drop foreign key/branch")
    slot, admission = slots[key], admissions[key]
    _require(terminal.get("run_id") == closure["run_id"] and terminal.get("stream_id") == slot["stream_id"]
             and terminal.get("frame_id") == slot["derived_ordinal"] and record.get("resource") == arm["resource"],
             "native queue drop run/frame/resource mismatch")
    _require(terminal.get("terminal_status") == "drop" and terminal.get("runtime_protocol_version") == 3
             and terminal.get("event_provenance") == "native_runtime_event"
             and terminal.get("telemetry_source") == "native", "native queue drop provenance")
    reason = terminal.get("terminal_reason")
    _require(reason in {"native_pre_detector_queue_full_drop_newest",
                        "native_postdecode_preprocess_queue_full_drop_newest"}
             and type(terminal.get("objects")) is int and terminal["objects"] == 0, "native queue drop reason/objects")
    bindings = closure.get("native_drop_bindings")
    _require(type(bindings) is dict and set(bindings) == set(branches) and type(bindings.get(branch)) is dict
             and set(bindings[branch]) == {"detector", "backend"}, "native queue drop frozen model binding")
    _require(all(type(bindings[branch][f]) is str and bool(bindings[branch][f])
                 and terminal.get(f) == bindings[branch][f] for f in ("detector", "backend")),
             "native queue drop detector/backend mismatch")
    timestamp = _number(terminal.get("terminal_timestamp_ms"), "native queue drop timestamp")
    expected = {"protocol_version": 3, "event_kind": "branch_drop", "run_id": closure["run_id"],
                "input_frame_key": key, "stream_id": slot["stream_id"], "frame_id": slot["derived_ordinal"],
                "branch_id": branch, "admission_id": admission.get("admission_id"),
                "payload_sha256": admission["payload_sha256"], "timestamp_ms": timestamp,
                "terminal_reason": reason, "objects": 0, "detector": terminal["detector"], "backend": terminal["backend"]}
    _require(type(expected["admission_id"]) is str and bool(expected["admission_id"])
             and all(type(event.get(k)) is type(v) and event[k] == v for k, v in expected.items()),
             "native queue drop original event/admission/payload mismatch")
    frames = closure.get("runtime_frame_terminals")
    _require(type(frames) is list and len(frames) <= 2652, "native drop original frame records missing/cap")
    joined = [r for r in frames if type(r) is dict and r.get("input_frame_key") == key]
    _require(len(joined) == 1, "native drop original frame membership")
    frame = joined[0]
    _require(frame.get("admission_id") == admission["admission_id"] and frame.get("stream_id") == slot["stream_id"]
             and frame.get("frame_id") == slot["derived_ordinal"] and frame.get("terminal_status") == "drop"
             and frame.get("terminal_event_provenance") == "native_drop_event"
             and frame.get("terminal_telemetry_source") == "native", "native drop original frame binding/provenance")
    drain = _number(closure.get("drain_end_timestamp_ms"), "native drop original drain")
    frame_timestamp = _number(frame.get("terminal_timestamp_ms"), "native drop original frame clock")
    _require(admission["admission_timestamp_ms"] <= timestamp <= frame_timestamp <= drain,
             "native drop original admission/frame/drain clock")
    return key, branch, dict(terminal, terminal_status="controlled_dropped"), frame


def reduce_arm(plan, arm_id, arm_inputs, *, deadline=None):
    """Reconcile a closed effect/pilot arm. Physical source/CI gates remain driver-owned."""
    _deadline(deadline)
    validate_study_plan(plan)
    arms = plan["arms"] + plan["pilots"]["initial"] + plan["pilots"]["conditional"]
    matches = [a for a in arms if a["arm_id"] == arm_id]
    _require(len(matches) == 1, "foreign arm ID")
    arm = matches[0]
    _require(type(arm_inputs) is dict and set(arm_inputs) == {
        "admissions", "source_events", "native_terminals", "guardian_events", "waits", "closure"},
        "arm input roles")
    closure = arm_inputs["closure"]
    _require(type(closure) is dict and closure.get("arm_id") == arm_id,
             "closed arm identity")
    _require(closure.get("plan_sha256") == plan["sha256"]
             and closure.get("bundle_sha256") == plan["bundle_sha256"], "source bundle/plan mismatch")
    run_id = closure.get("run_id")
    _require(type(run_id) is str and 0 < len(run_id) <= 64, "original run ID missing")
    _require(closure.get("final_variant") in ("global-client", "branch-channel"), "foreign variant")
    for field in ("source_window_closed", "drain_deadline_reached"):
        _require(type(closure.get(field)) is bool, "closure boolean field missing")
    _require(type(closure.get("infra_errors")) is list and type(closure.get("close_errors")) is list,
             "original error disposition missing")
    _require(closure.get("source_streams_closed") == list(range(6)), "original source EOF set incomplete")
    _require(_clock(closure.get("source_clock_domain"), "CLOCK_REALTIME") ==
             _clock(closure.get("native_clock_domain"), "CLOCK_REALTIME"), "clock domain mismatch")
    roles = {k: arm_inputs[k] for k in arm_inputs if k != "closure"}
    _require(all(type(v) is list for v in roles.values()) and
             sum(len(v) for v in roles.values()) <= MAX_ARM_ROWS, "arm original row cap")
    decoded_bytes = _bounded_size(arm_inputs, plan["limits"]["max_raw_bytes_per_arm"])
    _deadline(deadline)
    slots = {r["input_frame_key"]: r for s in range(6) for r in stream_schedule(plan, s, arm["rate"])}
    measured = {k: r for k, r in slots.items() if r["measurement"]}
    recipients = closure.get("recipient_bindings")
    _require(type(recipients) is dict and set(recipients) == {str(s) for s in range(6)},
             "recipient stream domain")
    recipient_ids = []
    for mapping in recipients.values():
        expected = set(plan["branches"]) if arm["topology"] == "baseline" else {"shared"}
        _require(type(mapping) is dict and set(mapping) == expected, "recipient topology domain")
        _require(all(type(v) is str and 0 < len(v) <= 128 for v in mapping.values()), "recipient identity")
        recipient_ids.extend(mapping.values())
    _require(len(set(recipient_ids)) == len(recipient_ids), "aliased recipient binding")
    events = {k: {} for k in slots}
    allowed = {"source_offered", "source_admitted", "source_ack", "fanout_enqueued",
               "recipient_delivered", "recipient_received"}
    lateness = []
    for row in roles["source_events"]:
        _deadline(deadline)
        key = _slot_binding(row, slots, run_id, source=True)
        kind = row.get("type")
        _require(kind in allowed, "foreign source event")
        _integer(row.get("actual_monotonic_ns"), "original source observation clock")
        per_recipient = kind.startswith("recipient_") or kind == "fanout_enqueued"
        recipient = row.get("recipient_id") if per_recipient else None
        if per_recipient:
            _require(type(recipient) is str and 0 < len(recipient) <= 128, "recipient identity field")
            _require(recipient in recipients[str(slots[key]["stream_id"])].values(), "foreign recipient")
        identity = (kind, recipient)
        _require(identity not in events[key], "duplicate source event")
        events[key][identity] = row
        if kind == "source_offered" and key in measured and row.get("source_lateness_ns") is not None:
            lateness.append(_integer(row["source_lateness_ns"], "source lateness"))
    admissions = {}
    for row in roles["admissions"]:
        _deadline(deadline)
        key = _slot_binding(row, slots, run_id)
        _require(key not in admissions, "duplicate durable admission")
        _number(row.get("admission_timestamp_ms"), "common original admission clock")
        admissions[key] = row
    for key, rows in events.items():
        offered = ("source_offered", None) in rows
        admitted = ("source_admitted", None) in rows
        _require(not rows or offered, "source event without original offer")
        _require(not admitted or key in admissions, "durable admission missing/source acceptance mismatch")
        _require(key not in admissions or offered, "durable admission without original source offer")
        _require(not any(t[0] in {"source_ack", "fanout_enqueued", "recipient_delivered", "recipient_received"}
                         for t in rows) or key in admissions, "delivery before original durable admission")
    runtime_dispositions = _runtime_dispositions(closure, slots, admissions, measured, run_id)
    guardian = {}
    for row in roles["guardian_events"]:
        _deadline(deadline)
        _require(type(row) is dict and type(row.get("identity")) is dict, "guardian decoded identity")
        identity, begin, terminal = row["identity"], row.get("begin"), row.get("terminal")
        _require(type(begin) is dict and type(terminal) is dict, "guardian original begin/terminal missing")
        key = identity.get("input_frame_key")
        _require(key in admissions and identity.get("run_id") == run_id and identity.get("arm_id") == arm_id,
                 "guardian foreign/unadmitted run/key")
        slot = slots[key]
        branch = identity.get("branch")
        _require(branch in plan["branches"] and identity.get("resource") == arm["resource"],
                 "guardian branch/resource")
        _require(identity.get("stream_id") == slot["stream_id"]
                 and identity.get("frame_id") == slot["derived_ordinal"]
                 and identity.get("transport_pts_ns") == slot["transport_pts_ns"], "guardian frame/PTS")
        decision = identity.get("decision_id")
        _require(type(decision) is str and begin.get("decision_id") == decision
                 and begin.get("input_key") == key and begin.get("pts_ns") == slot["transport_pts_ns"],
                 "guardian original control binding")
        _integer(begin.get("seq"), "guardian begin seq", 1)
        _require(terminal.get("begin_seq") == begin["seq"]
                 and _integer(terminal.get("seq"), "guardian terminal seq", 1) > begin["seq"],
                 "guardian original terminal join")
        _require((key, branch) not in guardian, "duplicate guardian branch")
        guardian[key, branch] = (decision, terminal)
    terminals, dropped_frames = {}, {}
    for record in roles["native_terminals"]:
        _deadline(deadline)
        _require(type(record) is dict, "native original record")
        if "branch_terminal" in record:
            key, branch, terminal, original_frame = _native_queue_drop(
                record, closure, admissions, slots, arm, plan["branches"])
            _require((key, branch) not in terminals and (key, branch) not in guardian,
                     "native queue drop duplicate or entered guardian execution")
            terminals[key, branch] = terminal
            dropped_frames[key] = original_frame
            continue
        raw, path, terminal = (record.get(k) for k in ("decision_request", "path", "terminal"))
        _require(all(type(v) is dict for v in (raw, path, terminal)), "native original path/terminal missing")
        key, branch = raw.get("input_frame_key"), raw.get("branch")
        _require(key in slots and key in admissions and raw.get("run_id") == run_id,
                 "native foreign/unadmitted key")
        slot = slots[key]
        _require(branch in plan["branches"] and raw.get("stream_id") == slot["stream_id"]
                 and raw.get("frame_id") == slot["derived_ordinal"]
                 and raw.get("transport_pts_ns") == slot["transport_pts_ns"], "native branch/frame/PTS mismatch")
        decision = record.get("decision_id")
        _require(type(decision) is str and path.get("decision_id") == decision
                 and path.get("selected_resource") == arm["resource"]
                 and terminal.get("selected_resource") == arm["resource"], "native policy resource/decision mismatch")
        _require((key, branch) not in terminals, "duplicate native terminal branch")
        _require(terminal.get("terminal_status") in {"completed", "failed"},
                 "non-native drop/censor requires original runtime disposition")
        if terminal["terminal_status"] == "completed":
            _require((key, branch) in guardian, "native completed branch missing guardian terminal")
            gdecision, gterminal = guardian[key, branch]
            _require(gdecision == decision and gterminal.get("outcome") == "completed"
                     and gterminal.get("send") == "sent" and type(gterminal.get("response")) is str
                     and len(gterminal["response"]) == 64, "guardian completed response/decision mismatch")
            completed_at = _number(terminal.get("terminal_timestamp_ms"), "original native terminal clock")
            _require(completed_at >= admissions[key]["admission_timestamp_ms"], "negative end-to-end latency")
        terminals[key, branch] = terminal
    for key, frame in dropped_frames.items():
        reasons = sorted({r["terminal_reason"] for (k, _), r in terminals.items()
                          if k == key and r["terminal_status"] == "controlled_dropped"})
        _require(frame.get("terminal_reason") == ";".join(reasons), "native frame drop reason set mismatch")
        if key in measured:
            _require(runtime_dispositions.get(key) == "drop", "native drop missing original runtime ledger disposition")
            ledger = next(r for r in closure["runtime_ledger"] if r["input_frame_key"] == key)
            _require(ledger.get("terminal_timestamp_ms") == frame["terminal_timestamp_ms"],
                     "native drop runtime/frame clock mismatch")
    frames = {"N_" + name: 0 for name in ("planned", "not_offered", "offered", "not_admitted", "admitted",
              "delivery_failed", "delivered", "completed", "controlled_dropped", "censored", "failed", "unknown", "on_time")}
    branches = {"N_" + name: 0 for name in ("planned", "not_offered", "offered", "not_admitted", "admitted",
                "delivery_failed", "delivered", "completed", "controlled_dropped", "censored", "failed", "unknown", "on_time")}
    frame_latencies, branch_latencies, completed_keys, outcomes = [], [], [], []
    raw_complete = bool(closure["source_window_closed"] and not closure["infra_errors"] and not closure["close_errors"])
    per_branch = {b: {"N_planned": len(measured), "N_completed": 0, "N_on_time": 0,
                      "N_controlled_dropped": 0, "N_failed": 0, "N_unknown": 0,
                      "N_delivery_failed": 0, "samples": []}
                  for b in plan["branches"]}
    per_stream = {str(s): {"N_planned": sum(r["stream_id"] == s for r in measured.values()),
                          "N_offered": 0, "N_admitted": 0, "N_completed": 0} for s in range(6)}
    delivery = {r: {"expected": 0, "enqueued": 0, "complete_write": 0, "validated_received": 0,
                    "delivery_failed": 0} for r in recipient_ids}
    for key in admissions:
        rows = events[key]
        for recipient in recipients[str(slots[key]["stream_id"])].values():
            wrote = ("recipient_delivered", recipient) in rows
            received = ("recipient_received", recipient) in rows
            enqueued = ("fanout_enqueued", recipient) in rows
            _require(not wrote or enqueued, "complete pipe write without original recipient enqueue")
            _require(not received or wrote, "native receive without original complete pipe write")
            if not (wrote and received):
                raw_complete = False
            if key in measured:
                delivery[recipient]["expected"] += 1
                delivery[recipient]["enqueued"] += enqueued
                delivery[recipient]["complete_write"] += wrote
                delivery[recipient]["validated_received"] += received
                delivery[recipient]["delivery_failed"] += not (wrote and received)
        if any((key, branch) not in terminals or terminals[key, branch]["terminal_status"] not in {"completed", "controlled_dropped"}
               for branch in plan["branches"]):
            raw_complete = False
    for key, slot in measured.items():
        _deadline(deadline)
        frames["N_planned"] += 1
        branches["N_planned"] += 4
        rows = events[key]
        offered = ("source_offered", None) in rows
        if not offered:
            frames["N_not_offered"] += 1
            branches["N_not_offered"] += 4
            if not closure["source_window_closed"]:
                raw_complete = False
            continue
        frames["N_offered"] += 1
        branches["N_offered"] += 4
        per_stream[str(slot["stream_id"])]["N_offered"] += 1
        if key not in admissions:
            frames["N_not_admitted"] += 1
            branches["N_not_admitted"] += 4
            continue
        frames["N_admitted"] += 1
        branches["N_admitted"] += 4
        per_stream[str(slot["stream_id"])]["N_admitted"] += 1
        expected = set(recipients[str(slot["stream_id"])].values())
        delivered = all(("recipient_delivered", r) in rows and ("recipient_received", r) in rows for r in expected)
        latencies, statuses = [], []
        for branch in plan["branches"]:
            terminal = terminals.get((key, branch))
            recipient = recipients[str(slot["stream_id"])][branch if arm["topology"] == "baseline" else "shared"]
            if not (("recipient_delivered", recipient) in rows and ("recipient_received", recipient) in rows):
                branches["N_delivery_failed"] += 1
                per_branch[branch]["N_delivery_failed"] += 1
                statuses.append("delivery_failed")
                _require(terminal is None or terminal["terminal_status"] not in {"completed", "controlled_dropped"},
                         "native completion without validated recipient receive")
                continue
            branches["N_delivered"] += 1
            status = terminal["terminal_status"] if terminal else "unknown"
            statuses.append(status)
            branches["N_" + status] += 1
            if status != "completed":
                per_branch[branch]["N_" + status] += 1
            if status == "completed":
                latency = terminal["terminal_timestamp_ms"] - admissions[key]["admission_timestamp_ms"]
                latencies.append(latency)
                branch_latencies.append(latency)
                branches["N_on_time"] += latency <= plan["phases"]["deadline_ns"]/1e6
                per_branch[branch]["N_completed"] += 1
                per_branch[branch]["N_on_time"] += latency <= plan["phases"]["deadline_ns"]/1e6
                per_branch[branch]["samples"].append(latency)
        if not delivered:
            frames["N_delivery_failed"] += 1
            raw_complete = False
            continue
        frames["N_delivered"] += 1
        status = ("completed" if all(s == "completed" for s in statuses) else
                  "controlled_dropped" if all(s in {"completed", "controlled_dropped"} for s in statuses)
                  and "controlled_dropped" in statuses else "failed" if "failed" in statuses else "unknown")
        original_status = runtime_dispositions.get(key)
        if original_status is not None:
            _require(original_status != "completed" or status == "completed", "runtime completed frame lacks all four native/guardian branches")
            _require(status != "completed" or original_status == "completed", "native completed frame contradicts runtime disposition")
            if status == "unknown" and original_status in {"drop", "censored"}:
                status = "controlled_dropped" if original_status == "drop" else "censored"
        frames["N_" + status] += 1
        if status == "completed":
            latency = max(latencies)
            frame_latencies.append(latency)
            completed_keys.append(key)
            per_stream[str(slot["stream_id"])]["N_completed"] += 1
            frames["N_on_time"] += latency <= plan["phases"]["deadline_ns"]/1e6
            outcomes.append({"input_frame_key": key, "critical_branch_latency_ms": latency})
        elif status != "controlled_dropped":
            raw_complete = False
    _require(frames["N_planned"] == frames["N_not_offered"] + frames["N_offered"] and
             frames["N_offered"] == frames["N_not_admitted"] + frames["N_admitted"] and
             frames["N_admitted"] == frames["N_delivery_failed"] + frames["N_delivered"] and
             frames["N_delivered"] == sum(frames["N_"+n] for n in ("completed", "controlled_dropped", "censored", "failed", "unknown")),
             "source/frame accounting partition")
    for item in per_branch.values():
        item["latency_ms"] = distribution(item.pop("samples"))
    for item in per_stream.values():
        item["observed_offered_fps"] = item["N_offered"]/180
        item["observed_admitted_fps"] = item["N_admitted"]/180
    _deadline(deadline)
    return {"kind": "finite-component-study-arm-reduction", "arm_id": arm_id,
            "plan_sha256": plan["sha256"], "bundle_sha256": plan["bundle_sha256"],
            "final_variant": closure["final_variant"], "frames": frames, "branches": branches,
            "decoded_input_bytes": decoded_bytes,
            "per_branch": per_branch, "per_stream": per_stream, "delivery": delivery,
            "Y100_frame": frames["N_on_time"]/frames["N_planned"],
            "Y100_branch": branches["N_on_time"]/branches["N_planned"],
            "completed_frame_latency_ms": distribution(frame_latencies),
            "completed_branch_latency_ms": distribution(branch_latencies),
            "source_lateness_ns": distribution(lateness), "waits": _waits(roles["waits"]),
            "observed_offered_fps": frames["N_offered"]/180,
            "observed_admitted_fps": frames["N_admitted"]/180,
            "completed_keys": completed_keys, "completed_frame_rows": outcomes,
            "admitted_keys": sorted(admissions), "raw_reconciliation_complete": raw_complete,
            "original_errors": {"infra": closure["infra_errors"], "close": closure["close_errors"]},
            "limits": ["Driver must validate original native/policy/guardian schemas and physical closure.",
                       "Missing branch outcomes remain unknown; EOF is not controlled censoring.",
                       "No pure backend/kernel time or constructed queue ingress is inferred."],
            "canonical_study_complete": False, "qualification_eligible": False, "q4_eligible": False,
            "publication_eligible": False, "full_run_eligible": False}


def reduce_study(plan, arm_inputs, final_variant, *, deadline=None):
    """All twenty-four effect arms and twelve prespecified pairs, including negatives."""
    _deadline(deadline)
    validate_study_plan(plan)
    _require(type(arm_inputs) is dict and set(arm_inputs) == {a["arm_id"] for a in plan["arms"]},
             "exact 24 effect arm inputs required; pilots never substitute")
    _require(final_variant in {"global-client", "branch-channel"}, "foreign final variant")
    reductions = {}
    for arm in plan["arms"]:
        raw = arm_inputs[arm["arm_id"]]
        _require(raw.get("closure", {}).get("final_variant") == final_variant, "mixed final variant")
        reductions[arm["arm_id"]] = reduce_arm(plan, arm["arm_id"], raw, deadline=deadline)
    pairs = []
    for pair in plan["pairs"]:
        members = {a["topology"]: reductions[a["arm_id"]] for a in plan["arms"] if a["pair_id"] == pair["pair_id"]}
        baseline, shared = members["baseline"], members["shared"]
        _require(baseline["frames"]["N_planned"] == shared["frames"]["N_planned"], "paired plan denominator mismatch")
        common = set(baseline["completed_keys"]) & set(shared["completed_keys"])
        bframes = {r["input_frame_key"]: r["critical_branch_latency_ms"] for r in baseline["completed_frame_rows"]}
        sframes = {r["input_frame_key"]: r["critical_branch_latency_ms"] for r in shared["completed_frame_rows"]}
        quantile_delta = {q: (shared["completed_frame_latency_ms"][q]-baseline["completed_frame_latency_ms"][q]
                             if shared["completed_frame_latency_ms"][q] is not None
                             and baseline["completed_frame_latency_ms"][q] is not None else None)
                          for q in ("p50", "p95", "p99")}
        pairs.append(dict(pair, Y100_shared_minus_baseline=shared["Y100_frame"]-baseline["Y100_frame"],
                          completed_shared_minus_baseline=shared["frames"]["N_completed"]-baseline["frames"]["N_completed"],
                          shared_over_baseline_completed=(shared["frames"]["N_completed"]/baseline["frames"]["N_completed"]
                                                         if baseline["frames"]["N_completed"] else None),
                          common_completed_keys=sorted(common), common_completed_n=len(common),
                          completed_frame_quantile_delta_ms=quantile_delta,
                          common_completed_latency_delta_ms=distribution([sframes[k]-bframes[k] for k in common], signed=True),
                          completed_branch_quantile_delta_ms={branch: {
                              q: (shared["per_branch"][branch]["latency_ms"][q]-baseline["per_branch"][branch]["latency_ms"][q]
                                  if shared["per_branch"][branch]["latency_ms"][q] is not None
                                  and baseline["per_branch"][branch]["latency_ms"][q] is not None else None)
                              for q in ("p50", "p95", "p99")} for branch in plan["branches"]},
                          common_subset_is_secondary=True))
    _require(sum(r["decoded_input_bytes"] for r in reductions.values()) <= plan["limits"]["max_campaign_raw_bytes"],
             "campaign raw byte cap")
    _deadline(deadline)
    return {"kind": "finite-component-study-reduction", "plan_sha256": plan["sha256"],
            "bundle_sha256": plan["bundle_sha256"], "final_variant": final_variant,
            "actual_effect_arms": len(reductions), "arms": reductions, "pairs": pairs,
            "raw_effect_matrix_complete": all(r["raw_reconciliation_complete"] for r in reductions.values()),
            "canonical_study_complete": False, "qualification_eligible": False, "q4_eligible": False,
            "publication_eligible": False, "full_run_eligible": False}


def _epoch(st):
    return tuple(getattr(st, name) for name in
                 ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read_closed_rows(descriptor, *, max_bytes=MAX_FILE_BYTES, deadline=None,
                     document=False, observations=None):
    """Hold no-follow ancestors/leaf; read admitted bytes with progress and full rechecks."""
    _require(type(descriptor) is dict and set(descriptor) == {"path", "size_bytes", "sha256"}, "raw descriptor fields")
    _require(type(descriptor["path"]) is str, "raw path string required")
    path = Path(descriptor["path"])
    _require(path.is_absolute() and ".." not in path.parts and len(str(path)) <= 4096, "raw absolute path required")
    size = _integer(descriptor["size_bytes"], "raw size")
    _require(type(max_bytes) is int and 0 < max_bytes <= MAX_FILE_BYTES and size <= max_bytes, "raw file cap")
    sha = descriptor["sha256"]
    _require(type(sha) is str and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), "raw SHA256")
    deadline = time.monotonic()+120 if deadline is None else deadline
    _require(type(deadline) in (int, float) and math.isfinite(deadline), "raw deadline bound")
    held, ancestors, primary, close_errors = [], [], None, []
    body = bytearray()
    def check_clock():
        _require(time.monotonic() < deadline, "original raw read deadline exceeded")
    try:
        check_clock()
        _require(len(path.parts) <= MAX_FDS, "ancestor FD cap")
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        held.append(directory)
        ancestors.append((path.anchor, directory, _epoch(os.fstat(directory))))
        named = Path(path.anchor)
        for component in path.parts[1:-1]:
            check_clock()
            acquired = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            held.append(acquired)
            directory = acquired
            named /= component
            ancestors.append((str(named), acquired, _epoch(os.fstat(acquired))))
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        held.append(fd)
        initial = _epoch(os.fstat(fd))
        _require(stat.S_ISREG(initial[2]) and initial[3] == 1 and initial[4] == size, "raw regular/size/alias mismatch")
        while len(body) < size:
            check_clock()
            part = os.pread(fd, min(1024*1024, size-len(body)), len(body))
            _require(bool(part), "short original raw EOF")
            _require(len(part) <= size-len(body), "raw progress exceeded admitted cap")
            body.extend(part)
        check_clock()
        _require(os.pread(fd, 1, size) == b"", "raw file grew beyond admitted size")
        _require(hashlib.sha256(body).hexdigest() == sha, "raw full SHA256 mismatch")
        _require(_epoch(os.fstat(fd)) == initial and _epoch(os.lstat(path)) == initial, "raw held/named epoch drift")
        for ancestor_path, ancestor_fd, epoch in ancestors:
            check_clock()
            full = ancestor_path == str(path.parent)
            actual, visible = _epoch(os.fstat(ancestor_fd)), _epoch(os.lstat(ancestor_path))
            _require((actual == epoch and visible == epoch) if full else
                     (actual[:3] == epoch[:3] and visible[:3] == epoch[:3] and stat.S_ISDIR(visible[2])),
                     "raw ancestor held/named epoch drift")
        lines = [bytes(body)] if document else bytes(body).splitlines()
        if document:
            _require(0 < size <= MAX_DOCUMENT_BYTES, "raw JSON document cap")
        else:
            _require(len(lines) <= MAX_ROWS and all(0 < len(line) <= MAX_ROW_BYTES for line in lines), "raw JSONL row cap/empty row")
        result = []
        for line in lines:
            check_clock()
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_pairs,
                             parse_constant=lambda value: (_ for _ in ()).throw(ReductionError("nonfinite JSON")))
            _require(type(row) is dict, "raw JSONL object required")
            result.append(row)
        if observations is not None:
            observations.extend([(str(path), initial, True)] +
                                [(p, e, p == str(path.parent)) for p, _, e in ancestors])
        check_clock()
    except BaseException as exc:
        primary = exc
    finally:
        for fd in reversed(held):
            try:
                os.close(fd)
            except OSError as exc:
                close_errors.append(str(exc))
    if primary is not None:
        if close_errors:
            primary.add_note("Remaining raw FD closes attempted; close failures: " + repr(close_errors))
        if isinstance(primary, (OSError, UnicodeError, json.JSONDecodeError, RecursionError)):
            raise ReductionError("raw physical/JSON refusal: " + str(primary)) from primary
        raise primary
    _require(not close_errors, "raw FD close failure: " + repr(close_errors))
    check_clock()
    return result[0] if document else result


def _recheck_named(observations, deadline):
    for path, epoch, full in observations:
        _deadline(deadline)
        try:
            current = _epoch(os.lstat(path))
            matches = current == epoch if full else current[:3] == epoch[:3] and stat.S_ISDIR(current[2])
            _require(matches, "closed input named epoch drift: " + path +
                     " expected=" + repr(epoch) + " observed=" + repr(current))
        except OSError as exc:
            raise ReductionError("closed input named epoch unavailable: " + str(exc)) from exc


def reduce_closed_study(binding, *, deadline=None):
    """One physical loader for the driver and CLI, over closed decoded original roles.

    Planning/current-source and original native schema/owner closure remain driver
    gates. SHA/held epochs establish these numerical input bytes, not a new grant.
    """
    deadline = time.monotonic()+120 if deadline is None else deadline
    _deadline(deadline)
    _require(type(binding) is dict and set(binding) == {"kind", "plan", "plan_sha256", "bundle_sha256",
             "final_variant", "arms"} and binding["kind"] == "finite-component-study-closed-inputs",
             "closed study binding fields/kind")
    observations, descriptors, seen = [], [], set()
    total_bytes = 0
    def read(descriptor, document=False):
        nonlocal total_bytes
        _require(type(descriptor) is dict and type(descriptor.get("path")) is str, "closed role descriptor")
        name = str(Path(descriptor["path"]))
        _require(name not in seen, "closed role path alias")
        seen.add(name)
        _require(len(seen) <= MAX_INPUT_FILES, "closed input file count cap")
        total_bytes += _integer(descriptor.get("size_bytes"), "closed input size")
        _require(total_bytes <= MAX_CAMPAIGN_BYTES, "campaign raw byte cap")
        value = read_closed_rows(descriptor, max_bytes=MAX_DOCUMENT_BYTES if document else MAX_FILE_BYTES,
                                 deadline=deadline, document=document, observations=observations)
        descriptors.append(dict(descriptor))
        return value
    plan = read(binding["plan"], True)
    validate_study_plan(plan)
    _require(binding["plan_sha256"] == plan["sha256"] and binding["bundle_sha256"] == plan["bundle_sha256"],
             "closed plan/source bundle mismatch")
    arms = binding["arms"]
    _require(type(arms) is dict and set(arms) == {a["arm_id"] for a in plan["arms"]},
             "closed binding exact 24 effect arms required")
    decoded = {}
    row_roles = {"admissions", "source_events", "native_terminals", "guardian_events", "waits"}
    for arm in plan["arms"]:
        _deadline(deadline)
        roles = arms[arm["arm_id"]]
        _require(type(roles) is dict and set(roles) == row_roles | {"closure"}, "closed arm role set")
        before = total_bytes
        result = {"closure": read(roles["closure"], True)}
        for role in sorted(row_roles):
            _require(type(roles[role]) is list and 0 < len(roles[role]) <= 64, "closed role file count")
            result[role] = []
            for descriptor in roles[role]:
                result[role].extend(read(descriptor))
                _require(len(result[role]) <= MAX_ARM_ROWS, "closed arm role row cap")
        _require(total_bytes-before <= plan["limits"]["max_raw_bytes_per_arm"], "arm physical raw byte cap")
        decoded[arm["arm_id"]] = result
    result = reduce_study(plan, decoded, binding["final_variant"], deadline=deadline)
    _recheck_named(observations, deadline)
    result["closed_input_descriptors"] = descriptors
    result["physical_read_scope"] = {"full_sha256_and_held_named_leaf_epochs_checked": True,
                                    "containing_closed_input_directory_full_epochs_checked": True,
                                    "higher_ancestors_nofollow_dev_inode_mode_checked": True,
                                    "named_epochs_rechecked_after_reduction": True,
                                    "local_read_fds_close_completed": True,
                                    "original_native_schema_and_lifecycle_gate": "driver"}
    _deadline(deadline)
    return result


def _write_exclusive_report(path, body, deadline):
    _require(path.is_absolute() and ".." not in path.parts and len(path.parts) <= MAX_FDS,
             "report absolute path/ancestor cap")
    held, ancestors, primary, close_errors = [], [], None, []
    try:
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        held.append(directory)
        named = Path(path.anchor)
        ancestors.append((named, directory))
        for component in path.parts[1:-1]:
            _deadline(deadline)
            directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            held.append(directory)
            named /= component
            ancestors.append((named, directory))
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
        held.append(fd)
        initial = os.fstat(fd)
        offset = 0
        while offset < len(body):
            _deadline(deadline)
            written = os.write(fd, body[offset:offset+1024*1024])
            _require(written > 0, "report write made no progress")
            offset += written
        os.fsync(fd)
        actual, visible = os.fstat(fd), os.lstat(path)
        _require((actual.st_dev, actual.st_ino, actual.st_mode, actual.st_nlink, actual.st_size) ==
                 (visible.st_dev, visible.st_ino, visible.st_mode, visible.st_nlink, visible.st_size) and
                 (actual.st_dev, actual.st_ino, actual.st_mode) ==
                 (initial.st_dev, initial.st_ino, initial.st_mode) and actual.st_nlink == 1 and
                 actual.st_size == len(body), "report held/named leaf rebound")
        for named, acquired in ancestors:
            actual, visible = os.fstat(acquired), os.lstat(named)
            _require((actual.st_dev, actual.st_ino, actual.st_mode) ==
                     (visible.st_dev, visible.st_ino, visible.st_mode), "report ancestor rebound")
    except BaseException as exc:
        primary = exc
    finally:
        for fd in reversed(held):
            try:
                os.close(fd)
            except OSError as exc:
                close_errors.append(str(exc))
    if primary is not None:
        if close_errors:
            primary.add_note("Remaining report FD closes attempted: " + repr(close_errors))
        raise primary
    _require(not close_errors, "report FD close failure: " + repr(close_errors))
    _deadline(deadline)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--binding-size-bytes", type=int, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--deadline-monotonic", type=float, required=True,
                        help="Original continuous campaign/reduction deadline; no fresh clock.")
    args = parser.parse_args(argv)
    try:
        observations = []
        binding = read_closed_rows({"path": args.binding, "size_bytes": args.binding_size_bytes,
                                    "sha256": args.binding_sha256}, max_bytes=MAX_DOCUMENT_BYTES,
                                   deadline=args.deadline_monotonic, document=True, observations=observations)
        result = reduce_closed_study(binding, deadline=args.deadline_monotonic)
        _recheck_named(observations, args.deadline_monotonic)
        _bounded_size(result, MAX_FILE_BYTES)
        body = (json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
        _write_exclusive_report(Path(args.output), body, args.deadline_monotonic)
        print(json.dumps({"report": {"path": args.output, "size_bytes": len(body),
                                    "sha256": hashlib.sha256(body).hexdigest()},
                          "raw_effect_matrix_complete": result["raw_effect_matrix_complete"],
                          "canonical_study_complete": False}, separators=(",", ":")))
        _deadline(args.deadline_monotonic)
        return 0
    except (ReductionError, OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__+": "+str(exc), "canonical_study_complete": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
