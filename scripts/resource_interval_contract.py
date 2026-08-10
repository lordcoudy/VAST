#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


TELEMETRY_SCHEMA_VERSION = 2
RESOURCE_INTERVAL_CONTRACT_VERSION = 2
RESOURCE_INTERVAL_SIDECAR = "resource_intervals.csv"
RESOURCE_INTERVAL_VALIDATION_STATUS = "validated_extension_not_publication_bound"
RESOURCE_INTERVAL_STATIC_STATUS = "validator_ready_not_emitted_not_publication_bound"
CURRENT_PUBLICATION_BUNDLE_SCOPE = "primary_architecture_raw_evidence_v1"
FUTURE_PUBLICATION_BUNDLE_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"

RESOURCE_INTERVAL_COLUMNS = [
    "schema_version",
    "interval_contract_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "component",
    "direction",
    "stage",
    "branch_id",
    "execution_id",
    "host_start_timestamp_ns",
    "host_end_timestamp_ns",
    "duration_ns",
    "bytes",
    "device_id",
    "counter_scope",
    "native_event_id",
    "duration_provenance",
    "telemetry_source",
]

RESOURCE_INTERVAL_COMPONENTS = {"transfer", "nvdec_submit_complete", "fanout"}
RESOURCE_INTERVAL_DIRECTIONS = {"h2d", "d2h", "none"}
RESOURCE_INTERVAL_PROVENANCE = {
    "transfer": "native_cuda_event_interval_v1",
    "nvdec_submit_complete": "native_decoder_submit_complete_interval_v1",
    "fanout": "native_gstreamer_pad_probe_interval_v1",
}
RESOURCE_INTERVAL_DURATION_SEMANTICS = {
    "transfer": "device_event_elapsed_additive_resource_work",
    "nvdec_submit_complete": "decoder_submit_to_output_elapsed_nonadditive_diagnostic",
    "fanout": "queue_sink_to_src_elapsed_nonadditive_diagnostic",
}
RESOURCE_INTERVAL_ADDITIVE_COMPONENTS = {"transfer"}
RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS = RESOURCE_INTERVAL_COMPONENTS - RESOURCE_INTERVAL_ADDITIVE_COMPONENTS
RESOURCE_INTERVAL_SOURCE_MARKERS = {
    "RESOURCE_INTERVAL_CONTRACT_VERSION",
    "validate_resource_intervals",
    "summarize_resource_interval_extension",
    "native_cuda_event_interval_v1",
    "native_decoder_submit_complete_interval_v1",
    "native_gstreamer_pad_probe_interval_v1",
    "RESOURCE_INTERVAL_DURATION_SEMANTICS",
    "RESOURCE_INTERVAL_ADDITIVE_COMPONENTS",
    "decoder_submit_to_output_elapsed_nonadditive_diagnostic",
    "queue_sink_to_src_elapsed_nonadditive_diagnostic",
    "evidence_accepted",
    "publication_bundle_bound",
}

_INTEGER_COLUMNS = {
    "schema_version",
    "interval_contract_version",
    "stream_id",
    "frame_id",
    "host_start_timestamp_ns",
    "host_end_timestamp_ns",
    "duration_ns",
    "bytes",
}
_LINKAGE_COLUMNS = ["run_id", "trace_id", "stream_id", "frame_id"]
_TOPOLOGY_REQUIRED_COLUMNS = {
    *_LINKAGE_COLUMNS,
    "input_frame_key",
    "event_kind",
    "stage",
    "branch_id",
    "execution_id",
    "parent_execution_ids_json",
    "timestamp_ms",
}
_FRAME_EVENT_REQUIRED_COLUMNS = {
    *_LINKAGE_COLUMNS,
    "stage",
    "resource",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
}
_INGRESS_REQUIRED_COLUMNS = {
    *_LINKAGE_COLUMNS,
    "input_frame_key",
    "ingress_timestamp_ms",
    "terminal_timestamp_ms",
}
_DEVICE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_.:-]*")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP_TOLERANCE_NS = 1_000_000


class ResourceIntervalContractError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ResourceIntervalContractError(message)


def _parse_exact_nonnegative_integer(value: Any, *, path: Path, row_number: int, column: str) -> int:
    text = str(value)
    if not re.fullmatch(r"0|[1-9][0-9]*", text):
        raise ResourceIntervalContractError(
            f"{path}:{row_number}: {column} must be a canonical non-negative integer"
        )
    return int(text)


def _required_text(value: Any, *, path: Path, row_number: int, column: str) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "unavailable", "nan", "null"}:
        raise ResourceIntervalContractError(f"{path}:{row_number}: {column} must be explicit")
    if any(character in text for character in "\r\n"):
        raise ResourceIntervalContractError(f"{path}:{row_number}: {column} contains a line break")
    return text


def _read_resource_interval_rows(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise ResourceIntervalContractError(f"resource interval sidecar must be a regular file: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RESOURCE_INTERVAL_COLUMNS:
            raise ResourceIntervalContractError(
                f"{path}: expected exact resource interval header {RESOURCE_INTERVAL_COLUMNS}"
            )
        rows: list[dict[str, Any]] = []
        for row_number, raw in enumerate(reader, start=2):
            if None in raw or any(value is None for value in raw.values()):
                raise ResourceIntervalContractError(f"{path}:{row_number}: malformed CSV row")
            row: dict[str, Any] = {}
            for column in RESOURCE_INTERVAL_COLUMNS:
                value = raw[column]
                row[column] = (
                    _parse_exact_nonnegative_integer(
                        value,
                        path=path,
                        row_number=row_number,
                        column=column,
                    )
                    if column in _INTEGER_COLUMNS
                    else _required_text(
                        value,
                        path=path,
                        row_number=row_number,
                        column=column,
                    )
                )
            rows.append(row)
    if not rows:
        raise ResourceIntervalContractError(f"{path}: resource interval sidecar must not be empty")
    return rows


def _require_columns(frame: pd.DataFrame, required: set[str], *, name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ResourceIntervalContractError(f"{name} is missing columns: {', '.join(missing)}")


def _integer_identity(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ResourceIntervalContractError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceIntervalContractError(f"{name} must be an integer") from exc
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceIntervalContractError(f"{name} must be numeric") from exc
    if not math.isfinite(numeric) or numeric != number:
        raise ResourceIntervalContractError(f"{name} must be an exact integer")
    return number


def _finite_number(value: Any, *, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResourceIntervalContractError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ResourceIntervalContractError(f"{name} must be finite")
    return number


def _frame_key(row: dict[str, Any] | pd.Series) -> tuple[str, str, int, int]:
    return (
        str(row["run_id"]),
        str(row["trace_id"]),
        _integer_identity(row["stream_id"], name="stream_id"),
        _integer_identity(row["frame_id"], name="frame_id"),
    )


def _stage_base_name(stage: str) -> str:
    for prefix in ("decode_", "preprocess_"):
        if stage.startswith(prefix):
            return prefix[:-1]
    return stage


def _parse_topology_parents(value: Any, *, execution_id: str) -> tuple[str, ...]:
    try:
        parents = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ResourceIntervalContractError(
            f"topology execution {execution_id} has invalid parent_execution_ids_json"
        ) from exc
    if not isinstance(parents, list) or any(not isinstance(parent, str) or not parent for parent in parents):
        raise ResourceIntervalContractError(
            f"topology execution {execution_id} parents must be non-empty strings"
        )
    if len(parents) != len(set(parents)):
        raise ResourceIntervalContractError(f"topology execution {execution_id} has duplicate parents")
    return tuple(parents)


def _normalized_linkage(
    ingress_ledger: pd.DataFrame,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
) -> tuple[
    dict[tuple[str, str, int, int], dict[str, Any]],
    dict[tuple[tuple[str, str, int, int], str], dict[str, Any]],
    dict[tuple[tuple[str, str, int, int], str], dict[str, Any]],
]:
    _require_columns(ingress_ledger, _INGRESS_REQUIRED_COLUMNS, name="ingress_ledger")
    _require_columns(topology_events, _TOPOLOGY_REQUIRED_COLUMNS, name="topology_events")
    _require_columns(frame_events, _FRAME_EVENT_REQUIRED_COLUMNS, name="frame_events")

    ingress_by_key: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for row in ingress_ledger.to_dict(orient="records"):
        key = _frame_key(row)
        if key in ingress_by_key:
            raise ResourceIntervalContractError(f"ingress_ledger contains duplicate frame key: {key}")
        ingress_by_key[key] = row

    topology_by_key: dict[tuple[tuple[str, str, int, int], str], dict[str, Any]] = {}
    for row in topology_events.to_dict(orient="records"):
        key = (_frame_key(row), str(row["execution_id"]))
        if key in topology_by_key:
            raise ResourceIntervalContractError(f"topology_events contains duplicate execution key: {key}")
        normalized = dict(row)
        normalized["parents"] = _parse_topology_parents(
            row["parent_execution_ids_json"],
            execution_id=str(row["execution_id"]),
        )
        topology_by_key[key] = normalized

    frame_event_by_key: dict[tuple[tuple[str, str, int, int], str], dict[str, Any]] = {}
    for row in frame_events.to_dict(orient="records"):
        key = (_frame_key(row), str(row["stage"]))
        if key in frame_event_by_key:
            raise ResourceIntervalContractError(f"frame_events contains duplicate frame/stage key: {key}")
        frame_event_by_key[key] = row
    return ingress_by_key, topology_by_key, frame_event_by_key


def _nearest_stage_ancestors(
    frame_key: tuple[str, str, int, int],
    row: dict[str, Any],
    topology_by_key: dict[tuple[tuple[str, str, int, int], str], dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    selected: dict[str, dict[str, Any]] = {}
    pending = list(row["parents"])
    visited: set[str] = set()
    while pending:
        execution_id = pending.pop()
        if execution_id in visited:
            continue
        visited.add(execution_id)
        parent = topology_by_key.get((frame_key, execution_id))
        if parent is None:
            raise ResourceIntervalContractError(
                f"topology execution {row['execution_id']} references missing parent {execution_id}"
            )
        if str(parent["event_kind"]) == "stage_complete":
            selected[execution_id] = parent
        else:
            pending.extend(parent["parents"])
    return tuple(selected[key] for key in sorted(selected))


def _expected_transfer_keys(
    topology_by_key: dict[tuple[tuple[str, str, int, int], str], dict[str, Any]],
    frame_event_by_key: dict[tuple[tuple[str, str, int, int], str], dict[str, Any]],
) -> set[tuple[tuple[str, str, int, int], str, str]]:
    expected: set[tuple[tuple[str, str, int, int], str, str]] = set()
    for (frame_key, execution_id), row in topology_by_key.items():
        if str(row["event_kind"]) != "stage_complete":
            continue
        child_event = frame_event_by_key.get((frame_key, str(row["stage"])))
        if child_event is None:
            raise ResourceIntervalContractError(
                f"topology stage {execution_id} has no matching frame_event"
            )
        child_resource = str(child_event["resource"]).strip().lower()
        for parent in _nearest_stage_ancestors(frame_key, row, topology_by_key):
            parent_event = frame_event_by_key.get((frame_key, str(parent["stage"])))
            if parent_event is None:
                raise ResourceIntervalContractError(
                    f"topology parent stage {parent['execution_id']} has no matching frame_event"
                )
            parent_resource = str(parent_event["resource"]).strip().lower()
            if parent_resource == "cpu" and child_resource == "gpu":
                expected.add((frame_key, execution_id, "h2d"))
            elif parent_resource == "gpu" and child_resource == "cpu":
                expected.add((frame_key, execution_id, "d2h"))
    return expected


def validate_resource_intervals(
    path: Path,
    *,
    ingress_ledger: pd.DataFrame,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
) -> pd.DataFrame:
    """Validate native per-trace intervals without accepting publication evidence."""

    rows = _read_resource_interval_rows(path)
    ingress_by_key, topology_by_key, frame_event_by_key = _normalized_linkage(
        ingress_ledger,
        topology_events,
        frame_events,
    )
    expected_transfers = _expected_transfer_keys(topology_by_key, frame_event_by_key)

    native_event_ids: set[tuple[str, str]] = set()
    interval_identities: set[tuple[Any, ...]] = set()
    exclusive_component_executions: set[tuple[Any, ...]] = set()
    observed_transfer_keys: set[tuple[tuple[str, str, int, int], str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        _require(
            row["schema_version"] == TELEMETRY_SCHEMA_VERSION,
            f"{path}:{row_number}: schema_version must equal {TELEMETRY_SCHEMA_VERSION}",
        )
        _require(
            row["interval_contract_version"] == RESOURCE_INTERVAL_CONTRACT_VERSION,
            f"{path}:{row_number}: interval_contract_version must equal {RESOURCE_INTERVAL_CONTRACT_VERSION}",
        )
        component = str(row["component"])
        direction = str(row["direction"])
        _require(component in RESOURCE_INTERVAL_COMPONENTS, f"{path}:{row_number}: unsupported component")
        _require(direction in RESOURCE_INTERVAL_DIRECTIONS, f"{path}:{row_number}: unsupported direction")
        expected_direction = direction in {"h2d", "d2h"}
        _require(
            (component == "transfer") == expected_direction,
            f"{path}:{row_number}: transfer rows require h2d/d2h and other components require none",
        )
        _require(
            str(row["duration_provenance"]) == RESOURCE_INTERVAL_PROVENANCE[component],
            f"{path}:{row_number}: duration_provenance does not match component",
        )
        _require(str(row["counter_scope"]) == "per_trace_interval", f"{path}:{row_number}: counter_scope drift")
        _require(str(row["telemetry_source"]) == "native", f"{path}:{row_number}: telemetry_source must be native")
        _require(
            bool(_DEVICE_ID_PATTERN.fullmatch(str(row["device_id"]))),
            f"{path}:{row_number}: device_id must be canonical",
        )
        _require(
            bool(_SHA256_PATTERN.fullmatch(str(row["native_event_id"]))),
            f"{path}:{row_number}: native_event_id must be lowercase SHA-256",
        )

        start_ns = int(row["host_start_timestamp_ns"])
        end_ns = int(row["host_end_timestamp_ns"])
        duration_ns = int(row["duration_ns"])
        payload_bytes = int(row["bytes"])
        _require(start_ns < end_ns, f"{path}:{row_number}: host interval must have positive width")
        _require(duration_ns > 0, f"{path}:{row_number}: duration_ns must be positive")
        _require(
            duration_ns <= end_ns - start_ns,
            f"{path}:{row_number}: native duration exceeds enclosing host interval",
        )
        _require(payload_bytes > 0, f"{path}:{row_number}: bytes must be positive")
        if component in RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS:
            _require(
                duration_ns == end_ns - start_ns,
                f"{path}:{row_number}: diagnostic elapsed duration must equal its host interval",
            )

        frame_key = _frame_key(row)
        ingress = ingress_by_key.get(frame_key)
        _require(ingress is not None, f"{path}:{row_number}: interval has no matching ingress row")
        _require(
            str(row["input_frame_key"]) == str(ingress["input_frame_key"]),
            f"{path}:{row_number}: input_frame_key does not match ingress ledger",
        )
        ingress_ns = round(_finite_number(ingress["ingress_timestamp_ms"], name="ingress timestamp") * 1_000_000)
        terminal_ns = round(_finite_number(ingress["terminal_timestamp_ms"], name="terminal timestamp") * 1_000_000)
        _require(
            ingress_ns <= start_ns < end_ns <= terminal_ns,
            f"{path}:{row_number}: interval is outside the ingress-terminal lifetime",
        )

        execution_key = (frame_key, str(row["execution_id"]))
        topology = topology_by_key.get(execution_key)
        _require(topology is not None, f"{path}:{row_number}: execution_id has no matching topology event")
        for field in ("input_frame_key", "stage", "branch_id"):
            _require(
                str(row[field]) == str(topology[field]),
                f"{path}:{row_number}: {field} does not match topology event",
            )
        topology_timestamp_ns = round(
            _finite_number(topology["timestamp_ms"], name="topology timestamp") * 1_000_000
        )
        _require(
            end_ns <= topology_timestamp_ns + _TIMESTAMP_TOLERANCE_NS,
            f"{path}:{row_number}: interval ends after the linked topology event",
        )

        frame_event = frame_event_by_key.get((frame_key, str(row["stage"])))
        if component == "fanout":
            _require(
                str(topology["event_kind"]) == "fanout",
                f"{path}:{row_number}: fanout interval must link to a fanout topology event",
            )
            _require(
                abs(end_ns - topology_timestamp_ns) <= _TIMESTAMP_TOLERANCE_NS,
                f"{path}:{row_number}: fanout interval end must match fanout topology time",
            )
            parent_times = [
                round(
                    _finite_number(
                        topology_by_key[(frame_key, parent_id)]["timestamp_ms"],
                        name="fanout parent timestamp",
                    )
                    * 1_000_000
                )
                for parent_id in topology["parents"]
            ]
            _require(
                bool(parent_times) and start_ns >= max(parent_times),
                f"{path}:{row_number}: fanout interval starts before its topology parent completes",
            )
        else:
            _require(
                str(topology["event_kind"]) == "stage_complete" and frame_event is not None,
                f"{path}:{row_number}: device interval must link to one frame stage",
            )
            stage_start_ns = round(
                _finite_number(frame_event["stage_start_timestamp_ms"], name="stage start") * 1_000_000
            )
            stage_end_ns = round(
                _finite_number(frame_event["stage_end_timestamp_ms"], name="stage end") * 1_000_000
            )
            _require(
                stage_start_ns - _TIMESTAMP_TOLERANCE_NS <= start_ns < end_ns <= stage_end_ns + _TIMESTAMP_TOLERANCE_NS,
                f"{path}:{row_number}: device interval is outside the linked stage interval",
            )
            if component == "nvdec_submit_complete":
                _require(
                    _stage_base_name(str(row["stage"])) == "decode"
                    and str(frame_event["resource"]).strip().lower() == "nvdec",
                    f"{path}:{row_number}: nvdec submit-complete interval requires a decode stage assigned to NVDEC",
                )
                _require(
                    str(row["device_id"]).startswith("nvdec:"),
                    f"{path}:{row_number}: nvdec submit-complete interval device_id must start with nvdec:",
                )
            else:
                transfer_key = (frame_key, str(row["execution_id"]), direction)
                _require(
                    transfer_key in expected_transfers,
                    f"{path}:{row_number}: transfer direction does not match a CPU/GPU topology edge",
                )
                observed_transfer_keys.add(transfer_key)
                _require(
                    str(row["device_id"]).startswith("gpu:"),
                    f"{path}:{row_number}: transfer interval device_id must start with gpu:",
                )

        native_id = (str(row["run_id"]), str(row["native_event_id"]))
        _require(native_id not in native_event_ids, f"{path}:{row_number}: native_event_id is reused")
        native_event_ids.add(native_id)
        interval_identity = (
            frame_key,
            component,
            direction,
            str(row["execution_id"]),
            start_ns,
            end_ns,
            duration_ns,
            str(row["device_id"]),
        )
        _require(
            interval_identity not in interval_identities,
            f"{path}:{row_number}: native interval is duplicated under another event id",
        )
        interval_identities.add(interval_identity)
        if component in RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS:
            exclusive_key = (frame_key, component, str(row["execution_id"]))
            _require(
                exclusive_key not in exclusive_component_executions,
                f"{path}:{row_number}: {component} execution has more than one interval",
            )
            exclusive_component_executions.add(exclusive_key)

    _require(
        observed_transfer_keys.issubset(expected_transfers),
        f"{path}: observed transfer set is inconsistent with topology resources",
    )
    return pd.DataFrame(rows, columns=RESOURCE_INTERVAL_COLUMNS)


def summarize_resource_interval_extension(
    intervals: pd.DataFrame,
    *,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
    topology_kind: str,
) -> dict[str, Any]:
    """Summarize validator coverage while keeping publication acceptance false."""

    _require_columns(topology_events, _TOPOLOGY_REQUIRED_COLUMNS, name="topology_events")
    _require_columns(frame_events, _FRAME_EVENT_REQUIRED_COLUMNS, name="frame_events")
    if list(intervals.columns) != RESOURCE_INTERVAL_COLUMNS:
        raise ResourceIntervalContractError("intervals must be the normalized validator output")
    _, topology_by_key, frame_event_by_key = _normalized_linkage(
        pd.DataFrame(
            [
                {
                    **{column: row[column] for column in _LINKAGE_COLUMNS},
                    "input_frame_key": row["input_frame_key"],
                    "ingress_timestamp_ms": row["host_start_timestamp_ns"] / 1_000_000,
                    "terminal_timestamp_ms": row["host_end_timestamp_ns"] / 1_000_000,
                }
                for row in intervals.to_dict(orient="records")
            ]
        ).drop_duplicates(subset=_LINKAGE_COLUMNS),
        topology_events,
        frame_events,
    )
    expected_transfer = _expected_transfer_keys(topology_by_key, frame_event_by_key)
    expected_nvdec_submit_complete: set[tuple[tuple[str, str, int, int], str]] = set()
    expected_fanout: set[tuple[tuple[str, str, int, int], str]] = set()
    for (frame_key, execution_id), topology in topology_by_key.items():
        if str(topology["event_kind"]) == "fanout":
            expected_fanout.add((frame_key, execution_id))
        if str(topology["event_kind"]) == "stage_complete" and _stage_base_name(str(topology["stage"])) == "decode":
            frame_event = frame_event_by_key.get((frame_key, str(topology["stage"])))
            if frame_event is not None and str(frame_event["resource"]).strip().lower() == "nvdec":
                expected_nvdec_submit_complete.add((frame_key, execution_id))

    observed_transfer: set[tuple[tuple[str, str, int, int], str, str]] = set()
    observed_nvdec_submit_complete: set[tuple[tuple[str, str, int, int], str]] = set()
    observed_fanout: set[tuple[tuple[str, str, int, int], str]] = set()
    for row in intervals.to_dict(orient="records"):
        frame_key = _frame_key(row)
        component = str(row["component"])
        if component == "transfer":
            observed_transfer.add((frame_key, str(row["execution_id"]), str(row["direction"])))
        elif component == "nvdec_submit_complete":
            observed_nvdec_submit_complete.add((frame_key, str(row["execution_id"])))
        elif component == "fanout":
            observed_fanout.add((frame_key, str(row["execution_id"])))

    transfer_complete = observed_transfer == expected_transfer
    nvdec_submit_complete_complete = (
        bool(expected_nvdec_submit_complete)
        and observed_nvdec_submit_complete == expected_nvdec_submit_complete
    )
    fanout_complete = (
        observed_fanout == expected_fanout
        if topology_kind == "shared_video_dag"
        else not expected_fanout and not observed_fanout
    )
    coverage_complete = transfer_complete and nvdec_submit_complete_complete and fanout_complete
    duration_by_component = {
        component: int(
            intervals.loc[intervals["component"] == component, "duration_ns"].astype(int).sum()
        )
        for component in sorted(RESOURCE_INTERVAL_COMPONENTS)
    }
    bytes_by_direction = {
        direction: int(
            intervals.loc[intervals["direction"] == direction, "bytes"].astype(int).sum()
        )
        for direction in ("h2d", "d2h")
    }
    return {
        "assessment_schema_version": 1,
        "status": (
            "complete_linkage_extension_not_publication_bound"
            if coverage_complete
            else "incomplete_linkage_extension_not_publication_bound"
        ),
        "contract_version": RESOURCE_INTERVAL_CONTRACT_VERSION,
        "contract_valid": True,
        "coverage_complete": coverage_complete,
        "linkage_coverage_complete": coverage_complete,
        "full_resource_coverage_complete": False,
        "transfer_coverage_complete": transfer_complete,
        "nvdec_submit_complete_coverage_complete": nvdec_submit_complete_complete,
        "fanout_coverage_complete": fanout_complete,
        "expected_transfer_intervals": len(expected_transfer),
        "expected_nvdec_submit_complete_intervals": len(expected_nvdec_submit_complete),
        "expected_fanout_intervals": len(expected_fanout),
        "observed_intervals": int(intervals.shape[0]),
        "duration_ns_sum_by_component": duration_by_component,
        "duration_semantics_by_component": {
            component: RESOURCE_INTERVAL_DURATION_SEMANTICS[component]
            for component in sorted(RESOURCE_INTERVAL_COMPONENTS)
        },
        "additive_duration_components": sorted(RESOURCE_INTERVAL_ADDITIVE_COMPONENTS),
        "nonadditive_elapsed_components": sorted(RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS),
        "additive_duration_ns_by_component": {
            component: duration_by_component[component]
            for component in sorted(RESOURCE_INTERVAL_ADDITIVE_COMPONENTS)
        },
        "nonadditive_elapsed_ns_sum_by_component": {
            component: duration_by_component[component]
            for component in sorted(RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS)
        },
        "nvdec_busy_time_measured": False,
        "fanout_resource_work_measured": False,
        "bytes_by_direction": bytes_by_direction,
        "publication_bundle_bound": False,
        "evidence_accepted": False,
        "current_publication_bundle_scope": CURRENT_PUBLICATION_BUNDLE_SCOPE,
        "future_publication_scope_required": FUTURE_PUBLICATION_BUNDLE_SCOPE,
        "interpretation": (
            "The interval rows satisfy the standalone native linkage contract. Only "
            "CUDA-event transfer duration is additive resource work. Decoder submit-to-output "
            "and queue sink-to-src spans are non-additive diagnostics; their sums cannot be "
            "inserted into C_obs and do not measure NVDEC busy time or fanout resource work. "
            "The frozen measurement passport v4 and publication evidence bundle v1 "
            "do not include this extension. No full-resource publication claim is accepted."
        ),
    }


def static_contract_status() -> dict[str, Any]:
    return {
        "assessment_schema_version": 1,
        "status": RESOURCE_INTERVAL_STATIC_STATUS,
        "contract_version": RESOURCE_INTERVAL_CONTRACT_VERSION,
        "sidecar": RESOURCE_INTERVAL_SIDECAR,
        "components": sorted(RESOURCE_INTERVAL_COMPONENTS),
        "duration_semantics_by_component": {
            component: RESOURCE_INTERVAL_DURATION_SEMANTICS[component]
            for component in sorted(RESOURCE_INTERVAL_COMPONENTS)
        },
        "additive_duration_components": sorted(RESOURCE_INTERVAL_ADDITIVE_COMPONENTS),
        "nonadditive_elapsed_components": sorted(RESOURCE_INTERVAL_NONADDITIVE_COMPONENTS),
        "nvdec_busy_time_measured": False,
        "fanout_resource_work_measured": False,
        "publication_bundle_bound": False,
        "evidence_accepted": False,
        "current_publication_bundle_scope": CURRENT_PUBLICATION_BUNDLE_SCOPE,
        "future_publication_scope_required": FUTURE_PUBLICATION_BUNDLE_SCOPE,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate non-publication native resource intervals")
    parser.add_argument("--intervals", type=Path)
    parser.add_argument("--ingress-ledger", type=Path)
    parser.add_argument("--topology-events", type=Path)
    parser.add_argument("--frame-events", type=Path)
    parser.add_argument(
        "--topology-kind",
        choices=("independent_processes", "shared_video_dag"),
    )
    args = parser.parse_args()
    paths = (args.intervals, args.ingress_ledger, args.topology_events, args.frame_events)
    if not any(paths) and args.topology_kind is None:
        print(json.dumps(static_contract_status(), sort_keys=True, separators=(",", ":")))
        return 0
    if not all(paths) or args.topology_kind is None:
        parser.error("interval validation requires all four sidecars and --topology-kind")
    try:
        intervals = validate_resource_intervals(
            args.intervals,
            ingress_ledger=pd.read_csv(args.ingress_ledger),
            topology_events=pd.read_csv(args.topology_events),
            frame_events=pd.read_csv(args.frame_events),
        )
        result = summarize_resource_interval_extension(
            intervals,
            topology_events=pd.read_csv(args.topology_events),
            frame_events=pd.read_csv(args.frame_events),
            topology_kind=args.topology_kind,
        )
    except (OSError, ValueError, ResourceIntervalContractError) as exc:
        print(f"resource interval validation failed: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
