#!/usr/bin/env python3
"""Describe retained component timing envelopes; never execute or qualify a run.

Only the four CSVs selected by --evidence-dir and explicitly supplied optional
policy JSONL are read. Stage starts are promoted parent completions, not native
entry timestamps. This module deliberately does not import benchmark/runtime
code or reconstruct source PTS, a declared DAG, or missing queue/service data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 256 * 1024 * 1024
DEADLINE_SERIALIZATION_TOLERANCE_MS = Decimal("0.001")
NATIVE_PATH_SERIALIZATION_TOLERANCE_MS = Decimal("0.001")
CSV_TIMESTAMP_RESOLUTION_MS = Decimal(1)
IDENTITY = ("run_id", "trace_id", "stream_id", "frame_id")
HEADERS = {
    "frames.csv": "schema_version,run_id,trace_id,stream_id,frame_id,ingress_timestamp_ms,egress_timestamp_ms,e2e_latency_ms,objects,detector,backend,telemetry_source",
    "ingress_ledger.csv": "schema_version,run_id,cohort_id,trace_id,input_frame_key,admission_seq,source_sha256,source_cycle,access_unit_pts_ns,payload_sha256,payload_size_bytes,schedule_offset_ns,stream_id,frame_id,ingress_timestamp_ms,window_start_timestamp_ms,window_end_timestamp_ms,terminal_status,terminal_timestamp_ms,drain_end_timestamp_ms,terminal_reason,censoring_rule,ingress_provenance,terminal_provenance,telemetry_source",
    "branch_terminals.csv": "schema_version,run_id,cohort_id,trace_id,input_frame_key,stream_id,frame_id,branch_id,terminal_status,terminal_timestamp_ms,objects,detector,backend,terminal_reason,terminal_provenance,telemetry_source",
    "frame_events.csv": "schema_version,run_id,trace_id,stream_id,frame_id,stage,role,host,resource,queue_enter_timestamp_ms,stage_start_timestamp_ms,stage_end_timestamp_ms,queue_depth,estimated_cost_ms,policy_action",
}
INTEGERS = {"schema_version", "stream_id", "frame_id", "objects", "admission_seq", "source_cycle",
            "access_unit_pts_ns", "payload_size_bytes", "schedule_offset_ns", "queue_depth"}


class DiagnosticError(ValueError):
    """Invalid, inconsistent, unsafe or unrepresentable diagnostic input."""


def require(condition, message):
    if not condition:
        raise DiagnosticError(message)


def number(value, label):
    require(not isinstance(value, bool), f"{label}: expected finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise DiagnosticError(f"{label}: expected finite number") from error
    require(result.is_finite(), f"{label}: expected finite number")
    # JSON has no Infinity; reject magnitudes which cannot be exported finitely.
    as_float = float(result)
    require(math.isfinite(as_float) and (result == 0 or as_float != 0),
            f"{label}: number exceeds finite nonzero export range")
    return result


def integer(value, label):
    result = number(value, label)
    require(result >= 0 and result == result.to_integral_value(), f"{label}: expected nonnegative integer")
    return int(result)


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: missing identifier/value")
    return value


def exported(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        result = float(value)
        require(math.isfinite(result) and (value == 0 or result != 0), "derived statistic exceeds finite nonzero export range")
        return result
    if isinstance(value, dict):
        return {key: exported(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [exported(item) for item in value]
    return value


def distribution(values, empty_reason="empty_population"):
    values = sorted(values)
    result = {"count": len(values), "p50": None, "p95": None, "p99": None,
              "reason": None if values else empty_reason}
    for name, q in (("p50", Decimal(".50")), ("p95", Decimal(".95")), ("p99", Decimal(".99"))):
        if values:
            position = q * (len(values) - 1)
            lower = int(position)
            upper = min(lower + 1, len(values) - 1)
            result[name] = values[lower] + (position - lower) * (values[upper] - values[lower])
    return result


def file_state(path):
    try:
        info = path.lstat()
    except OSError as error:
        raise DiagnosticError(f"{path}: missing/unreadable input: {error}") from error
    require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and not (getattr(info, "st_file_attributes", 0) & 0x400),
            f"{path}: input must be a regular file, never a symlink/reparse point")
    require(info.st_size <= MAX_INPUT_BYTES, f"{path}: individual input size limit exceeded")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def read_inputs(evidence_dir, native_policy_evidence):
    paths = [evidence_dir / name for name in HEADERS]
    if native_policy_evidence is not None:
        paths.append(Path(native_policy_evidence).absolute())
    states = [file_state(path) for path in paths]
    require(sum(state[2] for state in states) <= MAX_TOTAL_INPUT_BYTES, "total input size limit exceeded")
    payloads, inputs = {}, []
    for path, before in zip(paths, states):
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(path, flags), "rb") as handle:
                opened = os.fstat(handle.fileno())
                require(stat.S_ISREG(opened.st_mode)
                        and (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) == before,
                        f"{path}: input changed while opening")
                raw = handle.read(MAX_INPUT_BYTES + 1)
            require(len(raw) == before[2] and len(raw) <= MAX_INPUT_BYTES,
                    f"{path}: input changed or input size limit exceeded")
            require(file_state(path) == before, f"{path}: input changed while reading")
            payloads[path] = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeError) as error:
            raise DiagnosticError(f"{path}: cannot read UTF-8 regular input: {error}") from error
        inputs.append({"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return payloads, inputs, dict(zip(paths, states))


def csv_rows(payload, name):
    try:
        reader = csv.DictReader(io.StringIO(payload, newline=""), strict=True)
        fields = reader.fieldnames
        require(fields is not None and len(fields) == len(set(fields)), f"{name}: missing/duplicate header")
        require(set(HEADERS[name].split(",")) <= set(fields), f"{name}: required header fields missing")
        rows = []
        for line, row in enumerate(reader, 2):
            require(None not in row and None not in row.values(), f"{name}:{line}: CSV field width mismatch")
            for field in HEADERS[name].split(","):
                value = row[field]
                if field in INTEGERS:
                    row[field] = integer(value, f"{name}:{line}:{field}")
                elif field.endswith("_ms"):
                    row[field] = number(value, f"{name}:{line}:{field}")
                else:
                    text(value, f"{name}:{line}:{field}")
            require(row["schema_version"] == 2, f"{name}:{line}: expected schema_version=2")
            rows.append(row)
        return rows
    except csv.Error as error:
        raise DiagnosticError(f"{name}: malformed CSV: {error}") from error


def identity(row):
    return tuple(row[field] for field in IDENTITY)


def indexed(rows, label, suffix=()):
    result = {}
    for row in rows:
        key = (*identity(row), *(row[field] for field in suffix))
        require(key not in result, f"{label}: duplicate identity {key}")
        result[key] = row
    return result


def validate_csvs(rows):
    ledgers = indexed(rows["ingress_ledger.csv"], "ingress_ledger.csv")
    frames = indexed(rows["frames.csv"], "frames.csv")
    terminals = indexed(rows["branch_terminals.csv"], "branch_terminals.csv", ("branch_id",))
    stages = indexed(rows["frame_events.csv"], "frame_events.csv", ("stage",))
    require(bool(ledgers), "ingress_ledger.csv: empty recorded cohort")
    for field in ("run_id", "cohort_id", "window_start_timestamp_ms", "window_end_timestamp_ms", "drain_end_timestamp_ms"):
        require(len({row[field] for row in ledgers.values()}) == 1, f"ingress_ledger.csv: conflicting cohort {field}")
    traces, stream_frames, input_keys, admissions = set(), set(), set(), set()
    for key, row in ledgers.items():
        require((key[0], key[1]) not in traces and (key[0], key[2], key[3]) not in stream_frames,
                "ingress_ledger.csv: conflicting trace/stream/frame identity")
        traces.add((key[0], key[1]))
        stream_frames.add((key[0], key[2], key[3]))
        require(row["input_frame_key"] not in input_keys
                and (key[2], row["admission_seq"]) not in admissions,
                f"ingress_ledger.csv: conflicting input_frame_key/admission_seq identity {key}")
        require(row["admission_seq"] > 0 and row["payload_size_bytes"] > 0,
                f"ingress_ledger.csv: admission_seq/payload_size_bytes must be positive {key}")
        input_keys.add(row["input_frame_key"])
        admissions.add((key[2], row["admission_seq"]))
        require(row["window_start_timestamp_ms"] < row["window_end_timestamp_ms"] <= row["drain_end_timestamp_ms"],
                f"ingress_ledger.csv: reversed window/drain timing for {key}")
        require(row["ingress_timestamp_ms"] <= row["terminal_timestamp_ms"] <= row["drain_end_timestamp_ms"],
                f"ingress_ledger.csv: reversed/outside drain timing for {key}")
        require(row["terminal_status"] in {"completed", "drop", "censored"}, f"ingress_ledger.csv: invalid status for {key}")
        if row["terminal_status"] == "censored":
            require(row["terminal_timestamp_ms"] == row["drain_end_timestamp_ms"], f"censored row must end at drain: {key}")
    completed = {key for key, row in ledgers.items() if row["terminal_status"] == "completed"}
    require(set(frames) == completed, "frames.csv: completed frame identities disagree with recorded ledger")
    for key, frame in frames.items():
        ledger = ledgers[key]
        require(frame["ingress_timestamp_ms"] == ledger["ingress_timestamp_ms"]
                and frame["egress_timestamp_ms"] == ledger["terminal_timestamp_ms"],
                f"frames.csv: timing disagrees with ledger for {key}")
        require(frame["e2e_latency_ms"] >= 0
                and frame["e2e_latency_ms"] == frame["egress_timestamp_ms"] - frame["ingress_timestamp_ms"],
                f"frames.csv: e2e latency disagrees with timestamps for {key}")
    branches = sorted({row["branch_id"] for row in terminals.values()})
    require(bool(branches), "branch_terminals.csv: empty observed branch set")
    grouped = defaultdict(dict)
    for full_key, row in terminals.items():
        key = full_key[:4]
        require(key in ledgers, f"branch_terminals.csv: missing ledger identity {key}")
        ledger = ledgers[key]
        require(row["cohort_id"] == ledger["cohort_id"] and row["input_frame_key"] == ledger["input_frame_key"],
                f"branch_terminals.csv: conflicting cohort/input association {key}")
        require(row["terminal_status"] in {"completed", "drop"}, f"branch_terminals.csv: invalid status {key}")
        require(ledger["ingress_timestamp_ms"] <= row["terminal_timestamp_ms"] <= ledger["terminal_timestamp_ms"],
                f"branch_terminals.csv: terminal outside ledger interval {key}")
        require(row["terminal_status"] != "drop" or row["objects"] == 0, f"dropped branch has objects: {key}")
        grouped[key][row["branch_id"]] = row
    for key, ledger in ledgers.items():
        group = grouped[key]
        statuses = {row["terminal_status"] for row in group.values()}
        status = ledger["terminal_status"]
        if status == "censored":
            require(set(group) != set(branches) and "drop" not in statuses, f"inconsistent censored branch population {key}")
            continue
        require(set(group) == set(branches), f"incomplete terminal branch population {key}")
        if status == "completed":
            require(statuses == {"completed"}, f"completed frame has dropped branch {key}")
            require(frames[key]["objects"] == sum(row["objects"] for row in group.values()), f"frame/branch objects disagree {key}")
        else:
            require("drop" in statuses and ledger["terminal_timestamp_ms"] == max(row["terminal_timestamp_ms"] for row in group.values()),
                    f"dropped frame terminal disagrees with branch outcomes {key}")
    for full_key, row in stages.items():
        key = full_key[:4]
        require(key in ledgers, f"frame_events.csv: missing ledger identity {key}")
        ledger = ledgers[key]
        require(ledger["ingress_timestamp_ms"] <= row["queue_enter_timestamp_ms"] <= row["stage_start_timestamp_ms"]
                <= row["stage_end_timestamp_ms"] <= ledger["terminal_timestamp_ms"],
                f"frame_events.csv: reversed/outside frame timing {full_key}")
    stage_names = {row["stage"] for row in stages.values()}
    require({name for name in stage_names if name.startswith("postprocess_")}
            <= {"postprocess_" + branch for branch in branches},
            "frame_events.csv: postprocess branch conflicts with observed terminals")
    baseline_decoders = {name for name in stage_names if name.startswith("decode_")}
    shared = "decode" in stage_names
    require(shared != bool(baseline_decoders), "frame_events.csv: missing or mixed decoder layout")
    if baseline_decoders:
        require(baseline_decoders == {"decode_" + branch for branch in branches}, "decoder branch set conflicts with observed terminals")
    for full_key, terminal in terminals.items():
        key, branch = full_key[:4], full_key[4]
        post = stages.get((*key, "postprocess_" + branch))
        if terminal["terminal_status"] == "drop":
            require(post is None, f"dropped branch has completed postprocess {full_key}")
            continue
        analytics = stages.get((*key, branch))
        decode = stages.get((*key, "decode" if shared else "decode_" + branch))
        require(post is not None and analytics is not None and decode is not None, f"incomplete completed branch path {full_key}")
        require(post["stage_end_timestamp_ms"] == terminal["terminal_timestamp_ms"]
                and decode["stage_end_timestamp_ms"] <= analytics["stage_start_timestamp_ms"]
                and analytics["stage_end_timestamp_ms"] <= post["stage_start_timestamp_ms"],
                f"completed branch path timing disagrees {full_key}")
    for key, frame in frames.items():
        aggregate = stages.get((*key, "aggregate"))
        record = stages.get((*key, "record"))
        require(aggregate is not None and record is not None, f"incomplete completed aggregate/record path {key}")
        latest_postprocess = max(stages[(*key, "postprocess_" + branch)]["stage_end_timestamp_ms"] for branch in branches)
        egress = frame["egress_timestamp_ms"]
        # These CSV rows originate from one integer-ms promotion: aggregate
        # starts at the latest branch terminal, while the join can finish later.
        require(aggregate["queue_enter_timestamp_ms"] == aggregate["stage_start_timestamp_ms"] == latest_postprocess
                and aggregate["stage_end_timestamp_ms"] == egress
                and record["queue_enter_timestamp_ms"] == record["stage_start_timestamp_ms"]
                == record["stage_end_timestamp_ms"] == egress,
                f"aggregate/record timing disagrees with latest postprocess or frame join {key}")
    return ledgers, frames, terminals, stages, branches, "shared_video_dag" if shared else "independent_processes"


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"policy JSONL: duplicate JSON key {key}")
        result[key] = value
    return result


def policy_paths(payload, ledgers, terminals, stages, branches, deadline):
    if payload is None:
        return {"count": None, "reason": "not_supplied", "by_branch": {}}
    trace_keys = {key[1]: key for key in ledgers}
    expected = {full_key for full_key, row in terminals.items() if row["terminal_status"] == "completed"}
    seen, decisions, values = set(), set(), defaultdict(lambda: defaultdict(list))
    for line, source in enumerate(payload.splitlines(), 1):
        require(bool(source.strip()), f"policy JSONL:{line}: empty record")
        try:
            row = json.loads(source, parse_float=Decimal, object_pairs_hook=unique_json_object,
                             parse_constant=lambda value: number(value, f"policy JSONL:{line}"))
            require(isinstance(row, dict), f"policy JSONL:{line}: expected object")
            trace, branch, decision = (text(row[field], f"policy JSONL:{line}:{field}") for field in ("trace_id", "branch", "decision_id"))
            request, native = row["request"], row["native_decision_evidence"]
            require(integer(row["schema_version"], "policy schema_version") == 1,
                    f"policy JSONL:{line}: expected schema_version=1")
            require(isinstance(request, dict) and isinstance(native, dict), f"policy JSONL:{line}: request/native must be objects")
            require(trace in trace_keys and branch in branches, f"policy JSONL:{line}: foreign trace/branch")
            key = trace_keys[trace]
            full_key = (*key, branch)
            require(full_key in expected and full_key not in seen and decision not in decisions,
                    f"policy JSONL:{line}: duplicate/conflicting policy identity")
            require(request["trace_id"] == trace and request["branch"] == native["branch"] == branch
                    and request["decision_id"] == native["decision_id"] == decision,
                    f"policy JSONL:{line}: request/native association disagrees")
            if "publication_projection" in row:
                projection = row["publication_projection"]
                require(isinstance(projection, dict) and projection.get("original_worker_trace_id") == trace,
                        f"policy JSONL:{line}: publication projection worker trace disagrees")
            require(native["input_frame_key"] == ledgers[key]["input_frame_key"]
                    and native["terminal_status"] == "completed", f"policy JSONL:{line}: input/terminal association disagrees")
            stage, post = stages[full_key], stages[(*key, "postprocess_" + branch)]
            resource = text(row["selected_resource"], f"policy JSONL:{line}:selected_resource")
            require(resource == native["selected_resource"] == stage["resource"]
                    and stage["policy_action"] == f"{row['policy']}:{resource}:{decision}",
                    f"policy JSONL:{line}: resource/decision stage association disagrees")
            arrival = number(request["arrival_ms"], "policy arrival_ms")
            requested_deadline = number(request["deadline_ms"], "policy deadline_ms")
            require(abs(requested_deadline - arrival - deadline) <= DEADLINE_SERIALIZATION_TOLERANCE_MS,
                    f"policy JSONL:{line}: caller deadline contradicts request deadline-arrival")
            path = number(native["path_entry_timestamp_ms"], "policy path_entry_timestamp_ms")
            terminal = number(native["terminal_timestamp_ms"], "policy terminal_timestamp_ms")
            carried = number(native["actual_service_ms"], "policy carried actual_service_ms")
            decision_time = number(request["decision_time_ms"], "policy decision_time_ms")
            require(stage["stage_start_timestamp_ms"] <= path <= terminal
                    and ledgers[key]["ingress_timestamp_ms"] <= arrival <= decision_time <= path and carried >= 0,
                    f"policy JSONL:{line}: reversed native path/request timing")
            # Separate serialized native floats can differ by less than 1us;
            # validate that agreement without calling either span pure service.
            require(abs(carried - (terminal - path)) <= NATIVE_PATH_SERIALIZATION_TOLERANCE_MS,
                    f"policy JSONL:{line}: carried actual_service_ms contradicts native path span beyond serialization tolerance")
            # Native terminal can precede postprocess; CSV wall clocks are
            # truncated to milliseconds while native JSON timestamps are floats.
            require(terminal <= post["stage_end_timestamp_ms"] + CSV_TIMESTAMP_RESOLUTION_MS,
                    f"policy JSONL:{line}: native terminal follows postprocess beyond CSV precision")
            seen.add(full_key)
            decisions.add(decision)
            values[branch]["parent_to_path_ms"].append(path - stage["stage_start_timestamp_ms"])
            values[branch]["path_to_terminal_ms"].append(terminal - path)
            values[branch]["carried_actual_service_ms"].append(carried)
            values[branch]["native_terminal_to_postprocess_ms"].append(post["stage_end_timestamp_ms"] - terminal)
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise DiagnosticError(f"policy JSONL:{line}: malformed/incomplete record: {error}") from error
    require(seen == expected, "policy JSONL: missing completed branch paths")
    return {"count": len(seen), "reason": None if seen else "empty_population",
            "population": "measured_completed_branch_paths_including_dropped_frames",
            "includes_completed_paths_of_censored_frames": True,
            "semantics": "native_path_envelope_including_transport_preparation_waits_and_execution",
            "carried_actual_service_semantics": "original_field_carried_separately_not_pure_inference_service",
            "carried_path_serialization_tolerance_ms": NATIVE_PATH_SERIALIZATION_TOLERANCE_MS,
            "csv_timestamp_resolution_ms": CSV_TIMESTAMP_RESOLUTION_MS,
            "by_branch": {branch: {field: distribution(items) for field, items in sorted(fields.items())}
                          for branch, fields in sorted(values.items())}}


def build_report(inputs, ledgers, frames, terminals, stages, branches, topology, policy, deadline):
    per_frame, critical_counts = [], Counter()
    for key, frame in sorted(frames.items(), key=lambda item: (item[0][0], item[0][2], item[0][3], item[0][1])):
        critical = max(branches, key=lambda branch: (stages[(*key, "postprocess_" + branch)]["stage_end_timestamp_ms"], branch))
        decode = stages[(*key, "decode" if topology == "shared_video_dag" else "decode_" + critical)]["stage_end_timestamp_ms"]
        prefix = decode - frame["ingress_timestamp_ms"]
        residual = frame["egress_timestamp_ms"] - decode
        latency = frame["e2e_latency_ms"]
        require(prefix >= 0 and residual >= 0 and prefix + residual == latency, f"critical decomposition failed for {key}")
        critical_counts[critical] += 1
        per_frame.append(dict(zip(IDENTITY, key), critical_branch=critical, decoder_prefix_ms=prefix,
                              postdecode_residual_ms=residual, e2e_latency_ms=latency,
                              decoder_share=prefix / latency if latency > 0 else None,
                              decoder_share_reason=None if latency > 0 else "nonpositive_latency"))
    stage_values = defaultdict(lambda: defaultdict(list))
    for row in stages.values():
        stage_values[row["stage"]]["parent_to_completion_ms"].append(row["stage_end_timestamp_ms"] - row["stage_start_timestamp_ms"])
        stage_values[row["stage"]]["recorded_queue_span_ms"].append(row["stage_start_timestamp_ms"] - row["queue_enter_timestamp_ms"])
    frame_counts = Counter(row["terminal_status"] for row in ledgers.values())
    branch_counts = Counter(row["terminal_status"] for row in terminals.values())
    misses = sum(row["e2e_latency_ms"] > deadline for row in frames.values())
    report = {
        "schema_version": 1, "artifact_kind": "component_latency_diagnostic",
        "diagnostic_only": True, "qualification_eligible": False, "publication_ready": False,
        "full_campaign_ready": False, "q4_ready": False,
        "inputs": inputs, "topology": topology, "observed_branch_set": branches,
        "branch_set_provenance": "inferred_observed_terminals_not_declared_DAG_completeness",
        "cohort": {"run_id": next(iter(ledgers))[0], "cohort_id": next(iter(ledgers.values()))["cohort_id"],
                   "selection": "all_recorded_ledger_rows_no_wall_clock_reselection"},
        "counts": {"admitted": len(ledgers), "completed": frame_counts["completed"], "dropped": frame_counts["drop"],
                   "censored": frame_counts["censored"], "branch_completed": branch_counts["completed"], "branch_dropped": branch_counts["drop"]},
        "completion_coverage": Decimal(len(frames)) / len(ledgers),
        "branch_drop_reasons": dict(sorted(Counter(row["terminal_reason"] for row in terminals.values() if row["terminal_status"] == "drop").items())),
        "deadline": {"deadline_ms": deadline, "provenance": "caller_parameter", "completed_misses": misses,
                     "completed_on_time": len(frames) - misses, "population": "completed_frames",
                     "timely_completion_coverage": Decimal(len(frames) - misses) / len(ledgers),
                     "policy_corroborated": bool(policy["count"]),
                     "policy_serialization_tolerance_ms": DEADLINE_SERIALIZATION_TOLERANCE_MS},
        "latency_ms": distribution([row["e2e_latency_ms"] for row in per_frame]),
        "critical_branch_counts": dict(sorted(critical_counts.items())),
        "critical_path": {"population": "completed_frames", "tie_break": "lexicographically_largest_branch_name",
                          "decoder_prefix_ms": distribution([row["decoder_prefix_ms"] for row in per_frame]),
                          "postdecode_residual_ms": distribution([row["postdecode_residual_ms"] for row in per_frame]),
                          "decoder_share": distribution([row["decoder_share"] for row in per_frame if row["decoder_share"] is not None], "no_positive_latency_frames"),
                          "per_frame_sum_verified": True},
        "quantiles": {"method": "linear_interpolation", "position": "q*(n-1)", "marginal_quantiles_are_additive": False},
        "stages": {stage: {"semantics": "parent_to_completion_envelope", "population": "all_recorded_stage_rows_in_cohort",
                           **{field: distribution(items) for field, items in sorted(fields.items())}}
                   for stage, fields in sorted(stage_values.items())},
        "unknown_components": {
            "true_queue_wait_ms": {"value": None, "reason": "promoted_queue_enter_and_start_do_not_observe_native_queue_boundaries"},
            "pure_inference_service_ms": {"value": None, "reason": "stage_and_native_path_envelopes_include_preparation_transport_waits_and_execution"},
            "nvdec_busy_ms": {"value": None, "reason": "ingress_to_decoder_completion_is_residence_envelope_not_hardware_busy_time"}},
        "policy_path": policy,
        "scientific_limits": ["Recorded branch set does not certify the declared DAG or experiment acceptance.",
                              "Completed-frame latency excludes dropped/censored frames; branch outcomes have separate denominators.",
                              "Prefix plus residual equals latency per frame; marginal quantiles must not be added.",
                              "Promoted stages are parent-to-completion envelopes; recorded zero queue spans do not prove zero queue wait.",
                              "Native paths include preparation, transport, mapping/hash, waits and execution; carried actual_service_ms is not pure inference service.",
                              "Decoder residence is not NVDEC busy time or proof of reorder/display/hardware causation.",
                              "Overlapping partial C_obs is not work, energy or causal speedup; different completed subsets and baseline-first ordering remain confounders.",
                              "Original deadlines, drops, workloads and source evidence are unchanged; no cold/full/Q4/publication authority is granted."]}
    return report, per_frame


def markdown_report(report):
    counts = report["counts"]
    lines = ["# Retained component latency diagnostic", "", "Diagnostic only. Qualification/publication/full campaign/Q4 readiness remain false.", "",
             f"Recorded run: {report['cohort']['run_id']}; cohort: {report['cohort']['cohort_id']}.",
             f"Observed topology: {report['topology']}; observed branches: {', '.join(report['observed_branch_set'])}.",
             "The branch set is inferred from retained outcomes and does not certify a declared DAG.", "",
             f"Admissions {counts['admitted']}; completed {counts['completed']}; dropped {counts['dropped']}; censored {counts['censored']}.",
             f"Branch completions {counts['branch_completed']}; branch drops {counts['branch_dropped']}.",
             f"Completed coverage {report['completion_coverage']:.6g}; caller deadline {report['deadline']['deadline_ms']} ms; completed misses {report['deadline']['completed_misses']}.", "",
             "Quantiles use linear interpolation at q*(n-1), for completed frames only. Prefix + residual is verified per frame; marginal quantiles are not additive.", ""]
    for label, metric in (("End-to-end latency", report["latency_ms"]), ("Ingress-to-decoder envelope", report["critical_path"]["decoder_prefix_ms"]),
                          ("Decoder-to-frame-join envelope", report["critical_path"]["postdecode_residual_ms"]), ("Per-frame decoder share", report["critical_path"]["decoder_share"])):
        lines.append(f"- {label}: count={metric['count']}, p50={metric['p50']}, p95={metric['p95']}, p99={metric['p99']}; reason={metric['reason']}.")
    lines += ["", "Stage and recorded queue spans (all retained stage rows):", ""]
    for stage, metrics in report["stages"].items():
        span, queue = metrics["parent_to_completion_ms"], metrics["recorded_queue_span_ms"]
        lines.append(f"- {stage}: parent-to-completion envelope count={span['count']}, p50/p95/p99={span['p50']}/{span['p95']}/{span['p99']} ms; recorded queue span p50/p95/p99={queue['p50']}/{queue['p95']}/{queue['p99']} ms.")
    lines += ["", "Native policy paths:", ""]
    if report["policy_path"]["count"] is None:
        lines.append("Unavailable: not_supplied. No zero path/service values are inferred.")
    else:
        lines.append(f"Population: {report['policy_path']['population']}; count={report['policy_path']['count']}.")
        lines.append("Native timestamps have millisecond CSV comparison resolution; terminal may precede postprocess. Carried actual_service_ms is checked against terminal-minus-path with 0.001 ms serialization tolerance; both remain path envelopes, not pure inference service.")
        lines.append("")
        for branch, metrics in report["policy_path"]["by_branch"].items():
            for label, metric in metrics.items():
                lines.append(f"- {branch} {label}: count={metric['count']}, p50/p95/p99={metric['p50']}/{metric['p95']}/{metric['p99']} ms; native path envelopes include waits/execution.")
    lines += ["", "Unknown components:", ""]
    lines += [f"- {name}: null ({value['reason']})." for name, value in report["unknown_components"].items()]
    lines += ["", "Scientific limits:", ""] + ["- " + limit for limit in report["scientific_limits"]]
    lines += ["", "Exact input provenance:", ""]
    lines += [f"- {item['path']} ({item['size_bytes']} bytes; SHA256 {item['sha256']})." for item in report["inputs"]]
    return "\n".join(lines) + "\n"


def run_diagnostic(evidence_dir: Path, output_dir: Path, *, deadline_ms, native_policy_evidence: Path | None = None):
    """Validate selected retained data before creating three exclusive outputs."""
    evidence_dir, output_dir = Path(evidence_dir).absolute(), Path(output_dir).absolute()
    require(not os.path.lexists(output_dir), f"{output_dir}: output directory already exists/occupied")
    deadline = number(deadline_ms, "deadline_ms")
    require(deadline > 0, "deadline_ms must be finite and positive")
    payloads, inputs, states = read_inputs(evidence_dir, native_policy_evidence)
    rows = {name: csv_rows(payloads[evidence_dir / name], name) for name in HEADERS}
    ledgers, frames, terminals, stages, branches, topology = validate_csvs(rows)
    policy_payload = None if native_policy_evidence is None else payloads[Path(native_policy_evidence).absolute()]
    policy = policy_paths(policy_payload, ledgers, terminals, stages, branches, deadline)
    report, per_frame = build_report(inputs, ledgers, frames, terminals, stages, branches, topology, policy, deadline)
    report = exported(report)
    csv_output = io.StringIO(newline="")
    fields = (*IDENTITY, "critical_branch", "decoder_prefix_ms", "postdecode_residual_ms", "e2e_latency_ms", "decoder_share", "decoder_share_reason")
    writer = csv.DictWriter(csv_output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(per_frame)
    outputs = {"per_completed_frame.csv": csv_output.getvalue(), "report.md": markdown_report(report),
               "diagnostic.json": json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"}
    for path, before in states.items():
        require(file_state(path) == before, f"{path}: input changed during analysis")
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
        # JSON is written last: failed validation/writes never publish a success JSON.
        for name, payload in outputs.items():
            with (output_dir / name).open("x", encoding="utf-8", newline="") as handle:
                handle.write(payload)
    except OSError as error:
        raise DiagnosticError(f"{output_dir}: cannot create exclusive output: {error}") from error
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--native-policy-evidence", type=Path, help="optional explicit publication_policy_decisions.jsonl")
    parser.add_argument("--deadline-ms", required=True, help="finite positive caller diagnostic deadline; no CSV default")
    parser.add_argument("--output-dir", type=Path, required=True, help="fresh exclusive directory")
    args = parser.parse_args(argv)
    try:
        run_diagnostic(args.evidence_dir, args.output_dir, deadline_ms=args.deadline_ms, native_policy_evidence=args.native_policy_evidence)
    except DiagnosticError as error:
        parser.error(str(error))
    print(args.output_dir / "diagnostic.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
