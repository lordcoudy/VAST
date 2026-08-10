#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from benchmark_contract import ContractError, TELEMETRY_SCHEMA_VERSION


TOPOLOGY_CONTRACT_VERSION = 1
TOPOLOGY_EVENT_COLUMNS = [
    "schema_version",
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
    "parent_execution_ids_json",
    "execution_domain",
    "timestamp_ms",
    "event_provenance",
    "telemetry_source",
]

INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
SUPPORTED_TOPOLOGY_KINDS = {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG}
SUPPORTED_EVENT_KINDS = {
    "source_read",
    "stage_complete",
    "fanout",
    "branch_complete",
    "join_complete",
}


def _text(row: dict[str, Any], column: str, *, path: Path, row_number: int) -> str:
    value = str(row.get(column, "")).strip()
    if not value:
        raise ContractError(f"{path}:{row_number}: missing or empty {column}")
    return value


def _integer(row: dict[str, Any], column: str, *, path: Path, row_number: int) -> int:
    value = _text(row, column, path=path, row_number=row_number)
    try:
        number = float(value)
    except ValueError as exc:
        raise ContractError(f"{path}:{row_number}: invalid numeric {column}: {value!r}") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ContractError(f"{path}:{row_number}: invalid integer {column}: {value!r}")
    return int(number)


def _parents(row: dict[str, Any], *, path: Path, row_number: int) -> list[str]:
    raw = str(row.get("parent_execution_ids_json", "")).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"{path}:{row_number}: parent_execution_ids_json must be a JSON array"
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) or not item.strip() for item in parsed):
        raise ContractError(f"{path}:{row_number}: parent_execution_ids_json must contain non-empty strings")
    parents = [item.strip() for item in parsed]
    if len(parents) != len(set(parents)):
        raise ContractError(f"{path}:{row_number}: parent_execution_ids_json contains duplicates")
    return parents


def load_topology_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ContractError(f"topology_events.csv was not produced: {path}")
    with path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in TOPOLOGY_EVENT_COLUMNS if column not in fieldnames]
        if missing:
            raise ContractError(f"{path} is missing topology event columns: {', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        for row_number, raw in enumerate(reader, start=2):
            if None in raw:
                raise ContractError(f"{path}:{row_number}: unexpected extra CSV fields")
            row = {column: raw.get(column, "") for column in TOPOLOGY_EVENT_COLUMNS}
            row["schema_version"] = _integer(row, "schema_version", path=path, row_number=row_number)
            row["stream_id"] = _integer(row, "stream_id", path=path, row_number=row_number)
            row["frame_id"] = _integer(row, "frame_id", path=path, row_number=row_number)
            row["timestamp_ms"] = _integer(row, "timestamp_ms", path=path, row_number=row_number)
            for column in (
                "run_id",
                "trace_id",
                "input_frame_key",
                "topology_kind",
                "event_kind",
                "stage",
                "branch_id",
                "execution_id",
                "execution_domain",
                "event_provenance",
                "telemetry_source",
            ):
                row[column] = _text(row, column, path=path, row_number=row_number)
            row["parents"] = _parents(row, path=path, row_number=row_number)
            if row["schema_version"] != TELEMETRY_SCHEMA_VERSION:
                raise ContractError(f"{path}:{row_number}: unsupported topology schema version")
            if row["topology_kind"] not in SUPPORTED_TOPOLOGY_KINDS:
                raise ContractError(f"{path}:{row_number}: unsupported topology_kind {row['topology_kind']!r}")
            if row["event_kind"] not in SUPPORTED_EVENT_KINDS:
                raise ContractError(f"{path}:{row_number}: unsupported event_kind {row['event_kind']!r}")
            if row["event_provenance"] != "native_runtime_event":
                raise ContractError(f"{path}:{row_number}: topology event is not a native runtime event")
            if row["telemetry_source"] != "native":
                raise ContractError(f"{path}:{row_number}: topology event telemetry_source must be native")
            if row["event_kind"] == "source_read" and row["parents"]:
                raise ContractError(f"{path}:{row_number}: source_read must not have parent executions")
            if row["event_kind"] != "source_read" and not row["parents"]:
                raise ContractError(f"{path}:{row_number}: {row['event_kind']} must have parent executions")
            rows.append(row)
    if not rows:
        raise ContractError(f"topology_events.csv is empty: {path}")
    return rows


def _frame_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
    return (str(row["run_id"]), str(row["trace_id"]), int(row["stream_id"]), int(row["frame_id"]))


def _single(
    rows: list[dict[str, Any]],
    *,
    event_kind: str,
    stage: str,
    branch_id: str,
    path: Path,
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row["event_kind"] == event_kind and row["stage"] == stage and row["branch_id"] == branch_id
    ]
    if len(selected) != 1:
        raise ContractError(
            f"{path}: expected exactly one {event_kind}/{stage}/{branch_id} topology event, got {len(selected)}"
        )
    return selected[0]


def _require_parents(row: dict[str, Any], expected: set[str], *, path: Path) -> None:
    observed = set(row["parents"])
    if observed != expected:
        raise ContractError(
            f"{path}: execution {row['execution_id']} has parents {sorted(observed)}, expected {sorted(expected)}"
        )


def _validate_stage_linkage(
    rows: list[dict[str, Any]],
    frame_events: pd.DataFrame,
    *,
    path: Path,
) -> None:
    event_end_by_key: dict[tuple[str, str, int, int, str], list[int]] = defaultdict(list)
    for event in frame_events.to_dict("records"):
        key = (
            str(event["run_id"]),
            str(event["trace_id"]),
            int(event["stream_id"]),
            int(event["frame_id"]),
            str(event["stage"]),
        )
        event_end_by_key[key].append(int(float(event["stage_end_timestamp_ms"])))
    for row in rows:
        if row["event_kind"] != "stage_complete":
            continue
        key = (*_frame_key(row), str(row["stage"]))
        timestamps = event_end_by_key.get(key, [])
        if timestamps != [int(row["timestamp_ms"])]:
            raise ContractError(
                f"{path}: topology stage execution {row['execution_id']} does not match exactly one native frame event"
            )


def _validate_independent_frame(
    rows: list[dict[str, Any]],
    branches: list[str],
    *,
    path: Path,
) -> None:
    expected_ids: set[str] = set()
    branch_domains: set[str] = set()
    branch_completions: list[dict[str, Any]] = []
    if any(row["event_kind"] == "fanout" for row in rows):
        raise ContractError(f"{path}: independent-process topology must not emit fanout events")
    for branch in branches:
        source = _single(rows, event_kind="source_read", stage="source", branch_id=branch, path=path)
        decode = _single(rows, event_kind="stage_complete", stage=f"decode_{branch}", branch_id=branch, path=path)
        preprocess = _single(
            rows,
            event_kind="stage_complete",
            stage=f"preprocess_{branch}",
            branch_id=branch,
            path=path,
        )
        analytics = _single(rows, event_kind="stage_complete", stage=branch, branch_id=branch, path=path)
        complete = _single(rows, event_kind="branch_complete", stage=branch, branch_id=branch, path=path)
        _require_parents(decode, {source["execution_id"]}, path=path)
        _require_parents(preprocess, {decode["execution_id"]}, path=path)
        _require_parents(analytics, {preprocess["execution_id"]}, path=path)
        _require_parents(complete, {analytics["execution_id"]}, path=path)
        domains = {row["execution_domain"] for row in (source, decode, preprocess, analytics, complete)}
        if len(domains) != 1:
            raise ContractError(f"{path}: baseline branch {branch} crosses execution domains")
        domain = next(iter(domains))
        if domain in branch_domains:
            raise ContractError(f"{path}: baseline branches do not use independent execution domains")
        branch_domains.add(domain)
        branch_completions.append(complete)
        expected_ids.update(row["execution_id"] for row in (source, decode, preprocess, analytics, complete))
    join = _single(rows, event_kind="join_complete", stage="join", branch_id="shared", path=path)
    _require_parents(join, {row["execution_id"] for row in branch_completions}, path=path)
    expected_ids.add(join["execution_id"])
    if int(join["timestamp_ms"]) < max(int(row["timestamp_ms"]) for row in branch_completions):
        raise ContractError(f"{path}: baseline join completed before a branch")
    observed_ids = {row["execution_id"] for row in rows}
    if observed_ids != expected_ids:
        raise ContractError(f"{path}: independent topology contains unexpected or missing events")


def _validate_shared_frame(
    rows: list[dict[str, Any]],
    branches: list[str],
    *,
    path: Path,
) -> None:
    expected_ids: set[str] = set()
    source = _single(rows, event_kind="source_read", stage="source", branch_id="shared", path=path)
    decode = _single(rows, event_kind="stage_complete", stage="decode", branch_id="shared", path=path)
    preprocess = _single(rows, event_kind="stage_complete", stage="preprocess", branch_id="shared", path=path)
    _require_parents(decode, {source["execution_id"]}, path=path)
    _require_parents(preprocess, {decode["execution_id"]}, path=path)
    if len({source["execution_domain"], decode["execution_domain"], preprocess["execution_domain"]}) != 1:
        raise ContractError(f"{path}: shared source/decode/preprocess prefix crosses execution domains")
    expected_ids.update(row["execution_id"] for row in (source, decode, preprocess))
    branch_completions: list[dict[str, Any]] = []
    for branch in branches:
        fanout = _single(rows, event_kind="fanout", stage="fanout", branch_id=branch, path=path)
        analytics = _single(rows, event_kind="stage_complete", stage=branch, branch_id=branch, path=path)
        complete = _single(rows, event_kind="branch_complete", stage=branch, branch_id=branch, path=path)
        _require_parents(fanout, {preprocess["execution_id"]}, path=path)
        _require_parents(analytics, {fanout["execution_id"]}, path=path)
        _require_parents(complete, {analytics["execution_id"]}, path=path)
        branch_completions.append(complete)
        expected_ids.update(row["execution_id"] for row in (fanout, analytics, complete))
    join = _single(rows, event_kind="join_complete", stage="join", branch_id="shared", path=path)
    _require_parents(join, {row["execution_id"] for row in branch_completions}, path=path)
    expected_ids.add(join["execution_id"])
    if int(join["timestamp_ms"]) < max(int(row["timestamp_ms"]) for row in branch_completions):
        raise ContractError(f"{path}: shared join completed before a branch")
    observed_ids = {row["execution_id"] for row in rows}
    if observed_ids != expected_ids:
        raise ContractError(f"{path}: shared topology contains unexpected or missing events")


def validate_topology_events(
    path: Path,
    *,
    frames: pd.DataFrame,
    frame_events: pd.DataFrame,
    scenario: dict[str, Any],
) -> pd.DataFrame:
    topology = dict(scenario.get("topology") or {})
    version = int(topology.get("contract_version", 0) or 0)
    if version != TOPOLOGY_CONTRACT_VERSION:
        raise ContractError(
            f"scenario '{scenario.get('name', '')}' must declare topology contract version {TOPOLOGY_CONTRACT_VERSION}"
        )
    topology_kind = str(topology.get("kind", ""))
    if topology_kind not in SUPPORTED_TOPOLOGY_KINDS:
        raise ContractError(f"scenario '{scenario.get('name', '')}' has unsupported topology kind {topology_kind!r}")
    routing_mode = str(topology.get("routing_mode", ""))
    if routing_mode != "all_branches_per_stream":
        raise ContractError(
            f"scenario '{scenario.get('name', '')}' topology contract v1 requires resolved "
            "routing_mode=all_branches_per_stream"
        )
    if str((scenario.get("workload") or {}).get("routing_mode", "")) != routing_mode:
        raise ContractError(
            f"scenario '{scenario.get('name', '')}' workload/topology routing_mode values must match"
        )
    branches = [str(branch).strip() for branch in topology.get("required_branches", []) if str(branch).strip()]
    if not branches or len(branches) != len(set(branches)):
        raise ContractError(f"scenario '{scenario.get('name', '')}' must declare unique required topology branches")
    analytics_function_types = int(
        (scenario.get("workload") or {}).get("analytics_function_types", len(branches))
    )
    if analytics_function_types != len(branches):
        raise ContractError(
            f"scenario '{scenario.get('name', '')}' analytics_function_types does not match required topology branches"
        )

    rows = load_topology_events(path)
    frame_records = frames.to_dict("records")
    frame_by_key = {_frame_key(row): row for row in frame_records}
    if len(frame_by_key) != len(frame_records):
        raise ContractError("frames contain duplicate topology linkage keys")
    grouped: dict[tuple[str, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    execution_ids: set[tuple[str, str]] = set()
    for row in rows:
        key = _frame_key(row)
        if key not in frame_by_key:
            raise ContractError(f"{path}: topology event has no matching completed frame: {key}")
        if row["topology_kind"] != topology_kind:
            raise ContractError(f"{path}: topology_kind does not match the resolved scenario")
        execution_key = (str(row["run_id"]), str(row["execution_id"]))
        if execution_key in execution_ids:
            raise ContractError(f"{path}: duplicate topology execution_id {row['execution_id']!r}")
        execution_ids.add(execution_key)
        grouped[key].append(row)

    missing_frames = set(frame_by_key) - set(grouped)
    if missing_frames:
        raise ContractError(f"{path}: topology trace is missing {len(missing_frames)} completed frames")
    _validate_stage_linkage(rows, frame_events, path=path)

    for key, frame_rows in grouped.items():
        frame = frame_by_key[key]
        input_keys = {row["input_frame_key"] for row in frame_rows}
        if len(input_keys) != 1:
            raise ContractError(f"{path}: topology rows for {key} do not share one input_frame_key")
        ingress = int(float(frame["ingress_timestamp_ms"]))
        egress = int(float(frame["egress_timestamp_ms"]))
        by_execution = {row["execution_id"]: row for row in frame_rows}
        for row in frame_rows:
            timestamp = int(row["timestamp_ms"])
            if timestamp < ingress or timestamp > egress:
                raise ContractError(f"{path}: topology event {row['execution_id']} is outside frame lifetime")
            for parent_id in row["parents"]:
                parent = by_execution.get(parent_id)
                if parent is None:
                    raise ContractError(f"{path}: topology parent {parent_id!r} is outside the frame trace")
                if int(parent["timestamp_ms"]) > timestamp:
                    raise ContractError(f"{path}: topology parent {parent_id!r} completes after its child")
        if topology_kind == INDEPENDENT_PROCESSES:
            _validate_independent_frame(frame_rows, branches, path=path)
        else:
            _validate_shared_frame(frame_rows, branches, path=path)

    return pd.DataFrame([{column: row[column] for column in TOPOLOGY_EVENT_COLUMNS} for row in rows])
