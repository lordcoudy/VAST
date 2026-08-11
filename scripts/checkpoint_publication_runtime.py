#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from benchmark_contract import (
    BRANCH_TERMINAL_COLUMNS,
    CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
    ContractError,
    DROP_COUNTER_COLUMNS,
    FRAME_COLUMNS,
    FRAME_EVENT_COLUMNS,
    INGRESS_LEDGER_COLUMNS,
    RESET_EVIDENCE_COLUMNS,
    STAGE_CONTRACT_COLUMNS,
    TELEMETRY_SCHEMA_VERSION,
    canonicalize_frames_csv,
    summarize_sidecars,
    validate_drop_counters,
    validate_frame_events,
    validate_required_sidecars,
    validate_stage_trace_coverage,
    write_provenance_labeled_sidecars,
)
from checkpoint_runtime import RuntimeRunResult, SourceLaunchSpec, WorkerLaunchSpec
from topology_contract import SUPPORTED_EVENT_KINDS, TOPOLOGY_EVENT_COLUMNS, validate_topology_events


PUBLICATION_ACCEPTANCE_SCHEMA_VERSION = 1
PUBLICATION_RESET_PROVENANCE = "native_process_lifecycle_queue_and_sink_snapshot_v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    _require(bool(values), f"accepted {path.name} must not be empty")
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row[column] for column in columns} for row in values)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _linkage_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (
        str(row["run_id"]),
        str(row["trace_id"]),
        int(row["stream_id"]),
        int(row["frame_id"]),
    )


def _accepted_ingress_rows(
    result: RuntimeRunResult,
    *,
    run_id: str,
) -> tuple[list[dict[str, Any]], str]:
    rows = [dict(row) for row in result.terminal_ingress_rows]
    _require(bool(rows), "publication checkpoint runtime produced no measurement ingress rows")
    _require({str(row["run_id"]) for row in rows} == {run_id}, "runtime ingress run_id drifted")
    _require(
        {str(row["terminal_status"]) for row in rows} <= {"completed", "drop"},
        "publication checkpoint runtime rejects censored measurement ingress",
    )
    _require(
        all(
            str(row["terminal_provenance"])
            == (
                "native_completion_event"
                if str(row["terminal_status"]) == "completed"
                else "native_drop_event"
            )
            for row in rows
        ),
        "publication checkpoint ingress contains a non-native terminal outcome",
    )
    cohort_id = (
        f"{run_id}:measurement:{int(rows[0]['window_start_timestamp_ms'])}:"
        f"{int(rows[0]['window_end_timestamp_ms'])}"
    )
    for row in rows:
        row["cohort_id"] = cohort_id
        row["censoring_rule"] = "drain_to_empty"
        row["telemetry_source"] = "native"
    return rows, cohort_id


def _accepted_branch_rows(
    result: RuntimeRunResult,
    *,
    ledger_rows: list[dict[str, Any]],
    cohort_id: str,
    required_branches: list[str],
) -> list[dict[str, Any]]:
    ledger_by_key = {_linkage_key(row): row for row in ledger_rows}
    _require(len(ledger_by_key) == len(ledger_rows), "accepted ingress linkage keys are duplicated")
    branch_set = set(required_branches)
    grouped: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}
    for source in result.branch_terminal_records:
        row = dict(source)
        key = _linkage_key(row)
        if key not in ledger_by_key:
            continue
        _require(int(row["runtime_protocol_version"]) == 3, "accepted branch outcome is not protocol-v3")
        _require(str(row["telemetry_source"]) == "native", "accepted branch outcome is not native")
        _require(str(row["event_provenance"]) == "native_runtime_event", "branch event provenance is not native")
        grouped.setdefault(key, []).append(row)

    accepted: list[dict[str, Any]] = []
    for key, ledger in ledger_by_key.items():
        values = grouped.get(key, [])
        _require(
            {str(row["branch_id"]) for row in values} == branch_set
            and len(values) == len(branch_set),
            f"accepted ingress row lacks exactly one native outcome per branch: {key}",
        )
        ledger_status = str(ledger["terminal_status"])
        statuses = {str(row["terminal_status"]) for row in values}
        if ledger_status == "completed":
            _require(statuses == {"completed"}, f"completed ingress has a non-completed branch: {key}")
        else:
            _require("drop" in statuses, f"dropped ingress has no native branch drop: {key}")
        for row in values:
            status = str(row["terminal_status"])
            accepted.append(
                {
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "run_id": str(row["run_id"]),
                    "cohort_id": cohort_id,
                    "trace_id": str(row["trace_id"]),
                    "input_frame_key": str(row["input_frame_key"]),
                    "stream_id": int(row["stream_id"]),
                    "frame_id": int(row["frame_id"]),
                    "branch_id": str(row["branch_id"]),
                    "terminal_status": status,
                    "terminal_timestamp_ms": int(row["terminal_timestamp_ms"]),
                    "objects": int(row["objects"]),
                    "detector": str(row["detector"]),
                    "backend": str(row["backend"]),
                    "terminal_reason": str(row["terminal_reason"]),
                    "terminal_provenance": (
                        "native_completion_event" if status == "completed" else "native_drop_event"
                    ),
                    "telemetry_source": "native",
                }
            )
    return sorted(
        accepted,
        key=lambda row: (int(row["stream_id"]), int(row["frame_id"]), str(row["branch_id"])),
    )


def _accepted_frames(
    ledger_rows: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    objects_by_key: dict[tuple[str, str, int, int], int] = {}
    for row in branch_rows:
        key = _linkage_key(row)
        objects_by_key[key] = objects_by_key.get(key, 0) + int(row["objects"])
    frames: list[dict[str, Any]] = []
    for row in ledger_rows:
        if str(row["terminal_status"]) != "completed":
            continue
        ingress = int(row["ingress_timestamp_ms"])
        egress = int(row["terminal_timestamp_ms"])
        key = _linkage_key(row)
        frames.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": str(row["run_id"]),
                "trace_id": str(row["trace_id"]),
                "stream_id": int(row["stream_id"]),
                "frame_id": int(row["frame_id"]),
                "ingress_timestamp_ms": ingress,
                "egress_timestamp_ms": egress,
                "e2e_latency_ms": egress - ingress,
                "objects": objects_by_key[key],
                "detector": CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
                "backend": "openvino_dlstreamer_branch_aggregate_v1",
                "telemetry_source": "native",
            }
        )
    _require(bool(frames), "publication checkpoint runtime has no completed measurement frames")
    return sorted(frames, key=lambda row: (int(row["stream_id"]), int(row["frame_id"])))


def _accepted_topology_rows(
    result: RuntimeRunResult,
    *,
    completed_keys: set[tuple[str, str, int, int]],
) -> list[dict[str, Any]]:
    rows = [
        {column: row[column] for column in TOPOLOGY_EVENT_COLUMNS}
        for row in result.events
        if _linkage_key(row) in completed_keys
        and str(row["event_kind"]) in SUPPORTED_EVENT_KINDS
    ]
    _require(bool(rows), "accepted topology trace is empty")
    _require(
        all(
            str(row["event_provenance"]) == "native_runtime_event"
            and str(row["telemetry_source"]) == "native"
            for row in rows
        ),
        "accepted topology trace contains non-native events",
    )
    return rows


def _accepted_frame_event_rows(
    result: RuntimeRunResult,
    *,
    ledger_rows: list[dict[str, Any]],
    policy: str,
) -> list[dict[str, Any]]:
    ledger_by_key = {_linkage_key(row): row for row in ledger_rows}
    runtime_by_key: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}
    for source in result.events:
        key = _linkage_key(source)
        if key in ledger_by_key:
            runtime_by_key.setdefault(key, []).append(dict(source))

    accepted: list[dict[str, Any]] = []
    for key, ledger in ledger_by_key.items():
        runtime_rows = runtime_by_key.get(key, [])
        by_execution = {str(row["execution_id"]): row for row in runtime_rows}
        stage_rows = [row for row in runtime_rows if str(row["event_kind"]) == "stage_complete"]
        _require(bool(stage_rows), f"measurement ingress has no native stage events: {key}")
        for row in stage_rows:
            parents = json.loads(str(row["parent_execution_ids_json"]))
            _require(isinstance(parents, list) and bool(parents), f"stage event has no direct parent: {key}")
            parent_rows = [by_execution.get(str(parent)) for parent in parents]
            _require(all(parent is not None for parent in parent_rows), f"stage parent is missing: {key}")
            start = max(int(parent["timestamp_ms"]) for parent in parent_rows if parent is not None)
            end = int(row["timestamp_ms"])
            _require(start <= end, f"native stage interval is negative: {key}")
            stage = str(row["stage"])
            resource = "gpu" if stage.split("_", 1)[0] == "decode" else "cpu"
            accepted.append(
                {
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "run_id": key[0],
                    "trace_id": key[1],
                    "stream_id": key[2],
                    "frame_id": key[3],
                    "stage": stage,
                    "role": "local",
                    "host": str(row["execution_domain"]),
                    "resource": resource,
                    "queue_enter_timestamp_ms": start,
                    "stage_start_timestamp_ms": start,
                    "stage_end_timestamp_ms": end,
                    "queue_depth": 0,
                    "estimated_cost_ms": end - start,
                    "policy_action": f"{policy}:{resource}",
                }
            )

        observed_bases = {str(row["stage"]).split("_", 1)[0] for row in stage_rows}
        _require(
            {"decode", "preprocess"}.issubset(observed_bases),
            f"measurement ingress lacks a native decode/preprocess prefix: {key}",
        )
        if str(ledger["terminal_status"]) == "completed":
            branch_terminal_rows = [
                row for row in runtime_rows if str(row["event_kind"]) == "branch_complete"
            ]
            joins = [row for row in runtime_rows if str(row["event_kind"]) == "join_complete"]
            _require(branch_terminal_rows and len(joins) == 1, f"completed frame lacks native join: {key}")
            aggregate_start = max(int(row["timestamp_ms"]) for row in branch_terminal_rows)
            aggregate_end = int(joins[0]["timestamp_ms"])
            _require(aggregate_start <= aggregate_end, f"aggregate interval is negative: {key}")
            host = str(joins[0]["execution_domain"])
            for stage, start, end in (
                ("aggregate", aggregate_start, aggregate_end),
                ("record", aggregate_end, aggregate_end),
            ):
                accepted.append(
                    {
                        "schema_version": TELEMETRY_SCHEMA_VERSION,
                        "run_id": key[0],
                        "trace_id": key[1],
                        "stream_id": key[2],
                        "frame_id": key[3],
                        "stage": stage,
                        "role": "local",
                        "host": host,
                        "resource": "cpu",
                        "queue_enter_timestamp_ms": start,
                        "stage_start_timestamp_ms": start,
                        "stage_end_timestamp_ms": end,
                        "queue_depth": 0,
                        "estimated_cost_ms": end - start,
                        "policy_action": f"{policy}:cpu",
                    }
                )
    return sorted(
        accepted,
        key=lambda row: (
            int(row["stream_id"]),
            int(row["frame_id"]),
            float(row["stage_end_timestamp_ms"]),
            str(row["stage"]),
        ),
    )


def _accepted_reset_rows(
    runtime_rows: Iterable[dict[str, Any]],
    *,
    cohort_id: str,
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in runtime_rows]
    _require(bool(rows), "publication reset evidence is empty")
    for row in rows:
        row["cohort_id"] = cohort_id
        row["reset_provenance"] = PUBLICATION_RESET_PROVENANCE
        row["telemetry_source"] = "native"
    return rows


def _accepted_drop_rows(
    ledger_rows: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    *,
    deadline_ms: float,
    camera_roles: dict[int, str],
) -> list[dict[str, Any]]:
    frames_by_stream: dict[int, list[dict[str, Any]]] = {}
    for row in frames:
        frames_by_stream.setdefault(int(row["stream_id"]), []).append(row)
    ingress_by_stream: dict[int, list[dict[str, Any]]] = {}
    for row in ledger_rows:
        ingress_by_stream.setdefault(int(row["stream_id"]), []).append(row)
    rows: list[dict[str, Any]] = []
    run_id = str(ledger_rows[0]["run_id"])
    for stream_id in sorted(ingress_by_stream):
        ingress = ingress_by_stream[stream_id]
        completed = frames_by_stream.get(stream_id, [])
        dropped = sum(str(row["terminal_status"]) == "drop" for row in ingress)
        late = sum(float(row["e2e_latency_ms"]) > float(deadline_ms) for row in completed)
        ingress_count = len(ingress)
        completed_count = len(completed)
        rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "stream_id": stream_id,
                "camera_role": camera_roles.get(stream_id, "unknown"),
                "dropped_frames": dropped,
                "late_frames": late,
                "total_frames": ingress_count,
                "deadline_ms": float(deadline_ms),
                "drop_rate_percent": round(dropped / ingress_count * 100.0, 6),
                "late_rate_percent": round(late / max(1, completed_count) * 100.0, 6),
                "reason": "native_terminal_ledger",
                "drop_provenance": "native_drop_event",
                "late_provenance": "derived_from_native_frame_latency",
                "telemetry_source": "native",
            }
        )
    return rows


def publish_checkpoint_runtime(
    *,
    output_dir: Path,
    plan: dict[str, Any],
    scenario: dict[str, Any],
    dataset: dict[str, Any],
    result: RuntimeRunResult,
    reset_rows: Iterable[dict[str, Any]],
    reset_audit: dict[str, Any],
    cohort_audit: dict[str, Any],
    stage_contract_runtime_path: Path,
    worker_specs: Iterable[WorkerLaunchSpec],
    source_specs: Iterable[SourceLaunchSpec],
    run_id: str,
    policy: str,
    deadline_ms: float,
) -> dict[str, Any]:
    """Promote a closed, directly observed native checkpoint arm to accepted v1 sidecars."""
    _require(str(plan.get("benchmark_status")) == "supported", "publication plan is not benchmark-supported")
    workers = list(worker_specs)
    sources = list(source_specs)
    _require(workers and sources, "publication checkpoint arm requires native workers and sources")
    _require(all(spec.native_event_source for spec in workers), "publication worker is not a native event source")
    _require(all(spec.native_source for spec in sources), "publication source is not native")
    _require(not result.unresolved_frames, "publication checkpoint arm has unresolved runtime frames")
    terminal_audit = result.terminal_admission_audit or {}
    _require(
        bool(terminal_audit.get("engineering_terminal_accounting_complete"))
        and bool(terminal_audit.get("engineering_cohort_closed_without_censoring")),
        "publication checkpoint arm lacks closed direct terminal accounting",
    )
    _require(
        bool(cohort_audit.get("external_ingress_schedule_proven")),
        "publication checkpoint arm lacks external schedule proof",
    )
    _require(
        str(cohort_audit.get("measurement_schedule_fingerprint_sha256"))
        == str(terminal_audit.get("measurement_schedule_fingerprint_sha256")),
        "runtime cohort and terminal schedule fingerprints differ",
    )
    _require(
        bool(reset_audit.get("engineering_reset_state_complete")),
        "native lifecycle/reset audit did not pass",
    )
    _require(
        all(states and states[0] == "READY" and states[-1] == "DRAINED" for states in result.lifecycle_statuses.values()),
        "publication checkpoint lifecycle is not READY-to-DRAINED for every process",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_rows, cohort_id = _accepted_ingress_rows(result, run_id=run_id)
    required_branches = [str(value) for value in plan["required_branches"]]
    branch_rows = _accepted_branch_rows(
        result,
        ledger_rows=ledger_rows,
        cohort_id=cohort_id,
        required_branches=required_branches,
    )
    frame_rows = _accepted_frames(ledger_rows, branch_rows)
    completed_keys = {_linkage_key(row) for row in frame_rows}
    topology_rows = _accepted_topology_rows(result, completed_keys=completed_keys)
    frame_event_rows = _accepted_frame_event_rows(result, ledger_rows=ledger_rows, policy=policy)
    accepted_reset_rows = _accepted_reset_rows(reset_rows, cohort_id=cohort_id)

    stage_df = pd.read_csv(stage_contract_runtime_path)
    _require(not stage_df.empty, "native runtime stage contract is empty")
    _require(list(stage_df.columns) == STAGE_CONTRACT_COLUMNS, "runtime stage contract schema drifted")
    _require(set(stage_df["telemetry_source"].astype(str)) == {"native"}, "stage contracts are not native")

    _write_csv(output_dir / "ingress_ledger.csv", INGRESS_LEDGER_COLUMNS, ledger_rows)
    _write_csv(output_dir / "branch_terminals.csv", BRANCH_TERMINAL_COLUMNS, branch_rows)
    _write_csv(output_dir / "frames.csv", FRAME_COLUMNS, frame_rows)
    _write_csv(output_dir / "topology_events.csv", TOPOLOGY_EVENT_COLUMNS, topology_rows)
    _write_csv(output_dir / "frame_events.csv", FRAME_EVENT_COLUMNS, frame_event_rows)
    _write_csv(output_dir / "reset_evidence.csv", RESET_EVIDENCE_COLUMNS, accepted_reset_rows)
    stage_df.to_csv(output_dir / "stage_contracts.csv", index=False)

    camera_roles = {
        int(row.get("stream_id", index)): str(row.get("camera_role", "unknown"))
        for index, row in enumerate(dataset.get("streams", []))
    }
    drop_rows = _accepted_drop_rows(
        ledger_rows,
        frame_rows,
        deadline_ms=deadline_ms,
        camera_roles=camera_roles,
    )
    _write_csv(output_dir / "drop_counters.csv", DROP_COUNTER_COLUMNS, drop_rows)

    frames_df = canonicalize_frames_csv(
        output_dir / "frames.csv",
        mode="benchmark",
        run_id=run_id,
        detector=CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
        backend="openvino_dlstreamer_branch_aggregate_v1",
    )
    events_df = validate_frame_events(output_dir / "frame_events.csv")
    validate_stage_trace_coverage(
        output_dir / "frames.csv",
        output_dir / "frame_events.csv",
        required_stages=[str(value) for value in scenario["pipeline"]],
    )
    topology_df = validate_topology_events(
        output_dir / "topology_events.csv",
        frames=frames_df,
        frame_events=events_df,
        scenario=scenario,
    )
    validate_drop_counters(output_dir / "drop_counters.csv", require_labeled_provenance=True)
    write_provenance_labeled_sidecars(
        output_dir,
        frames=frames_df,
        events=events_df,
        dataset=dataset,
        policy=policy,
        deadline_ms=deadline_ms,
    )
    validate_required_sidecars(
        output_dir,
        require_labeled_provenance=True,
        require_ingress_ledger=True,
        require_branch_terminals=True,
        require_stage_contracts=True,
        require_reset_evidence=True,
        required_branches=required_branches,
        topology_kind=str(plan["topology_kind"]),
        expected_streams=len(plan["streams"]),
        expected_run_id=run_id,
        frames=frames_df,
        topology_events=topology_df,
    )
    summary = summarize_sidecars(
        output_dir,
        frames=frames_df,
        topology_events=topology_df,
        required_branches=required_branches,
        topology_kind=str(plan["topology_kind"]),
        expected_streams=len(plan["streams"]),
        require_reset_evidence=True,
        expected_run_id=run_id,
        decoder_placement_contract=plan["decoder_placement"],
    )
    required_gates = (
        "ingress_ledger_complete",
        "ingress_cohort_closed",
        "branch_terminal_trace_complete",
        "checkpoint_frame_aggregation_complete",
        "stage_semantic_contract_complete",
        "decoder_placement_verified",
        "resource_attribution_complete",
        "reset_state_verified",
    )
    _require(all(bool(summary.get(gate)) for gate in required_gates), "accepted checkpoint sidecar gate failed")
    _require(
        math.isfinite(float(summary["c_obs_total_ms"])) and float(summary["c_obs_total_ms"]) > 0,
        "accepted checkpoint resource observation is empty",
    )
    completed_by_stream = {
        int(stream_id): int(group.shape[0])
        for stream_id, group in frames_df.groupby("stream_id", dropna=False)
    }
    _require(
        set(completed_by_stream) == set(range(len(plan["streams"])))
        and all(value > 0 for value in completed_by_stream.values()),
        "publication arm lacks a positive completed cohort on every logical stream",
    )

    evidence_files = [
        "frames.csv",
        "frame_events.csv",
        "resource_events.csv",
        "policy_decisions.csv",
        "drop_counters.csv",
        "topology_events.csv",
        "ingress_ledger.csv",
        "branch_terminals.csv",
        "stage_contracts.csv",
        "reset_evidence.csv",
    ]
    acceptance = {
        "schema_version": PUBLICATION_ACCEPTANCE_SCHEMA_VERSION,
        "artifact_kind": "checkpoint_publication_runtime_acceptance",
        "status": "accepted_native_checkpoint_arm",
        "run_id": run_id,
        "scenario": str(scenario["name"]),
        "topology_kind": str(plan["topology_kind"]),
        "cohort_id": cohort_id,
        "measurement_schedule_fingerprint_sha256": str(
            terminal_audit["measurement_schedule_fingerprint_sha256"]
        ),
        "completed_frames_by_stream": completed_by_stream,
        "summary": summary,
        "evidence_sha256": {
            name: _sha256_file(output_dir / name) for name in evidence_files
        },
    }
    (output_dir / "checkpoint_publication_acceptance.json").write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return acceptance
