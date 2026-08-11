#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd
from resource_interval_contract import (
    summarize_resource_interval_extension,
    validate_resource_intervals,
)



TELEMETRY_SCHEMA_VERSION = 2
FULL_RESOURCE_CONTRACT_VERSION = 2
HARDWARE_SAMPLE_PROVENANCE = "nvml_device_decoder_utilization_v1"
FANOUT_COUNTER_PROVENANCE = "native_thread_cpu_time_v1"

HARDWARE_RESOURCE_SAMPLE_COLUMNS = [
    "schema_version",
    "resource_contract_version",
    "run_id",
    "sample_seq",
    "timestamp_ns",
    "sample_period_us",
    "device_id",
    "nvdec_util_percent",
    "gpu_util_percent",
    "memory_util_percent",
    "vram_used_bytes",
    "counter_scope",
    "sample_provenance",
    "telemetry_source",
]

FANOUT_WORK_COUNTER_COLUMNS = [
    "schema_version",
    "resource_contract_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "branch_id",
    "execution_id",
    "thread_cpu_time_ns",
    "work_units",
    "device_id",
    "counter_scope",
    "counter_provenance",
    "telemetry_source",
]

_HARDWARE_INTEGER_COLUMNS = {
    "schema_version",
    "resource_contract_version",
    "sample_seq",
    "timestamp_ns",
    "sample_period_us",
    "vram_used_bytes",
}
_FANOUT_INTEGER_COLUMNS = {
    "schema_version",
    "resource_contract_version",
    "stream_id",
    "frame_id",
    "thread_cpu_time_ns",
    "work_units",
}
_PERCENT_COLUMNS = {
    "nvdec_util_percent",
    "gpu_util_percent",
    "memory_util_percent",
}
_DEVICE_PATTERN = re.compile(r"[a-z][a-z0-9_.:-]*")


class FullResourceContractError(RuntimeError):
    pass


def _read_rows(path: Path, columns: list[str]) -> list[dict[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise FullResourceContractError(f"resource sidecar must be a regular file: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise FullResourceContractError(f"{path}: expected exact header {columns}")
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise FullResourceContractError(f"{path}:{row_number}: malformed CSV row")
            rows.append(dict(row))
    return rows


def _canonical_nonnegative_int(value: Any, *, path: Path, row: int, column: str) -> int:
    text = str(value)
    if not re.fullmatch(r"0|[1-9][0-9]*", text):
        raise FullResourceContractError(
            f"{path}:{row}: {column} must be a canonical non-negative integer"
        )
    return int(text)


def _required_text(value: Any, *, path: Path, row: int, column: str) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "unavailable", "nan", "null"}:
        raise FullResourceContractError(f"{path}:{row}: {column} must be explicit")
    if any(character in text for character in "\r\n"):
        raise FullResourceContractError(f"{path}:{row}: {column} contains a line break")
    return text


def _percent(value: Any, *, path: Path, row: int, column: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FullResourceContractError(f"{path}:{row}: {column} must be numeric") from exc
    if not math.isfinite(number) or number < 0.0 or number > 100.0:
        raise FullResourceContractError(f"{path}:{row}: {column} must be within [0, 100]")
    return number


def validate_hardware_resource_samples(
    path: Path,
    *,
    expected_run_id: str,
    window_start_ns: int,
    window_end_ns: int,
) -> pd.DataFrame:
    if not expected_run_id:
        raise FullResourceContractError("expected_run_id must be nonempty")
    if window_start_ns < 0 or window_end_ns <= window_start_ns:
        raise FullResourceContractError("measurement window is invalid")
    raw_rows = _read_rows(path, HARDWARE_RESOURCE_SAMPLE_COLUMNS)
    if not raw_rows:
        raise FullResourceContractError(f"{path}: hardware samples must not be empty")

    rows: list[dict[str, Any]] = []
    previous_end_by_device: dict[str, int] = {}
    expected_seq_by_device: dict[str, int] = {}
    first_start = None
    last_end = None
    for row_number, raw in enumerate(raw_rows, start=2):
        row: dict[str, Any] = {}
        for column in HARDWARE_RESOURCE_SAMPLE_COLUMNS:
            if column in _HARDWARE_INTEGER_COLUMNS:
                row[column] = _canonical_nonnegative_int(
                    raw[column],
                    path=path,
                    row=row_number,
                    column=column,
                )
            elif column in _PERCENT_COLUMNS:
                row[column] = _percent(
                    raw[column],
                    path=path,
                    row=row_number,
                    column=column,
                )
            else:
                row[column] = _required_text(
                    raw[column],
                    path=path,
                    row=row_number,
                    column=column,
                )

        if row["schema_version"] != TELEMETRY_SCHEMA_VERSION:
            raise FullResourceContractError(f"{path}:{row_number}: schema_version drift")
        if row["resource_contract_version"] != FULL_RESOURCE_CONTRACT_VERSION:
            raise FullResourceContractError(
                f"{path}:{row_number}: resource_contract_version drift"
            )
        if row["run_id"] != expected_run_id:
            raise FullResourceContractError(f"{path}:{row_number}: run_id mismatch")
        if row["sample_period_us"] <= 0:
            raise FullResourceContractError(f"{path}:{row_number}: sample_period_us must be positive")
        if row["counter_scope"] != "device_sample":
            raise FullResourceContractError(f"{path}:{row_number}: counter_scope must be device_sample")
        if row["sample_provenance"] != HARDWARE_SAMPLE_PROVENANCE:
            raise FullResourceContractError(f"{path}:{row_number}: sample_provenance drift")
        if row["telemetry_source"] != "native":
            raise FullResourceContractError(f"{path}:{row_number}: telemetry_source must be native")
        if not _DEVICE_PATTERN.fullmatch(row["device_id"]) or not row["device_id"].startswith("gpu:"):
            raise FullResourceContractError(f"{path}:{row_number}: invalid GPU device_id")

        device = row["device_id"]
        expected_seq = expected_seq_by_device.get(device, 1)
        if row["sample_seq"] != expected_seq:
            raise FullResourceContractError(
                f"{path}:{row_number}: sample_seq must be contiguous per device"
            )
        expected_seq_by_device[device] = expected_seq + 1
        interval_end = row["timestamp_ns"]
        interval_start = interval_end - row["sample_period_us"] * 1000
        if interval_start < 0:
            raise FullResourceContractError(f"{path}:{row_number}: sample interval starts before zero")
        previous_end = previous_end_by_device.get(device)
        if previous_end is not None:
            if interval_end <= previous_end:
                raise FullResourceContractError(
                    f"{path}:{row_number}: sample timestamps must increase"
                )
            if interval_start > previous_end:
                raise FullResourceContractError(
                    f"{path}:{row_number}: NVML sampling gap is not allowed"
                )
        previous_end_by_device[device] = interval_end
        first_start = interval_start if first_start is None else min(first_start, interval_start)
        last_end = interval_end if last_end is None else max(last_end, interval_end)
        rows.append(row)

    covered = bool(first_start is not None and first_start <= window_start_ns and last_end >= window_end_ns)
    if not covered:
        raise FullResourceContractError("NVML samples do not cover the measurement window")
    frame = pd.DataFrame(rows, columns=HARDWARE_RESOURCE_SAMPLE_COLUMNS)
    frame.attrs["measurement_window_covered"] = True
    frame.attrs["window_start_ns"] = int(window_start_ns)
    frame.attrs["window_end_ns"] = int(window_end_ns)
    return frame


def summarize_hardware_resource_samples(samples: pd.DataFrame) -> dict[str, Any]:
    if list(samples.columns) != HARDWARE_RESOURCE_SAMPLE_COLUMNS or samples.empty:
        raise FullResourceContractError("samples must be normalized hardware resource samples")
    busy_ns = sum(
        round(
            float(row["nvdec_util_percent"])
            / 100.0
            * int(row["sample_period_us"])
            * 1000
        )
        for row in samples.to_dict(orient="records")
    )
    return {
        "assessment_schema_version": 1,
        "resource_contract_version": FULL_RESOURCE_CONTRACT_VERSION,
        "sample_count": int(samples.shape[0]),
        "device_ids": sorted(set(str(value) for value in samples["device_id"])),
        "counter_scope": "device_sample",
        "sample_provenance": HARDWARE_SAMPLE_PROVENANCE,
        "measurement_window_covered": bool(
            samples.attrs.get("measurement_window_covered", False)
        ),
        "nvdec_busy_equivalent_ns": int(busy_ns),
        "per_trace_nvdec_busy_claimed": False,
        "evidence_accepted": True,
    }


def validate_fanout_work_counters(
    path: Path,
    *,
    expected_run_id: str,
    expected_fanout_keys: set[tuple[str, int, int, str, str]],
    require_rows: bool,
) -> pd.DataFrame:
    raw_rows = _read_rows(path, FANOUT_WORK_COUNTER_COLUMNS)
    if require_rows and not raw_rows:
        raise FullResourceContractError(f"{path}: shared topology requires fanout work rows")
    if not require_rows and raw_rows:
        raise FullResourceContractError(
            f"{path}: independent topology must not report fanout resource work"
        )

    rows: list[dict[str, Any]] = []
    observed: set[tuple[str, int, int, str, str]] = set()
    for row_number, raw in enumerate(raw_rows, start=2):
        row: dict[str, Any] = {}
        for column in FANOUT_WORK_COUNTER_COLUMNS:
            row[column] = (
                _canonical_nonnegative_int(
                    raw[column],
                    path=path,
                    row=row_number,
                    column=column,
                )
                if column in _FANOUT_INTEGER_COLUMNS
                else _required_text(
                    raw[column],
                    path=path,
                    row=row_number,
                    column=column,
                )
            )
        if row["schema_version"] != TELEMETRY_SCHEMA_VERSION:
            raise FullResourceContractError(f"{path}:{row_number}: schema_version drift")
        if row["resource_contract_version"] != FULL_RESOURCE_CONTRACT_VERSION:
            raise FullResourceContractError(
                f"{path}:{row_number}: resource_contract_version drift"
            )
        if row["run_id"] != expected_run_id:
            raise FullResourceContractError(f"{path}:{row_number}: run_id mismatch")
        if row["thread_cpu_time_ns"] <= 0 or row["work_units"] <= 0:
            raise FullResourceContractError(
                f"{path}:{row_number}: fanout resource work counters must be positive"
            )
        if row["device_id"] != "host:fanout":
            raise FullResourceContractError(f"{path}:{row_number}: device_id must be host:fanout")
        if row["counter_scope"] != "per_trace_resource_work":
            raise FullResourceContractError(
                f"{path}:{row_number}: counter_scope must be per_trace_resource_work"
            )
        if row["counter_provenance"] != FANOUT_COUNTER_PROVENANCE:
            raise FullResourceContractError(f"{path}:{row_number}: counter_provenance drift")
        if row["telemetry_source"] != "native":
            raise FullResourceContractError(f"{path}:{row_number}: telemetry_source must be native")
        key = (
            row["trace_id"],
            row["stream_id"],
            row["frame_id"],
            row["branch_id"],
            row["execution_id"],
        )
        if key in observed:
            raise FullResourceContractError(f"{path}:{row_number}: duplicate fanout work key")
        observed.add(key)
        rows.append(row)

    if observed != expected_fanout_keys:
        raise FullResourceContractError(
            "fanout work counter coverage does not match accepted topology fanout executions"
        )
    return pd.DataFrame(rows, columns=FANOUT_WORK_COUNTER_COLUMNS)

def validate_full_resource_evidence(
    run_dir: Path,
    *,
    expected_run_id: str,
    ingress_ledger: pd.DataFrame,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
    topology_kind: str,
) -> dict[str, Any]:
    """Validate and bind all v2 resource sidecars to one accepted measurement cohort."""

    required_window_columns = {
        "window_start_timestamp_ms",
        "window_end_timestamp_ms",
    }
    if ingress_ledger.empty or not required_window_columns.issubset(ingress_ledger.columns):
        raise FullResourceContractError(
            "full resource evidence requires an accepted ingress measurement window"
        )
    window_starts = pd.to_numeric(
        ingress_ledger["window_start_timestamp_ms"],
        errors="coerce",
    )
    window_ends = pd.to_numeric(
        ingress_ledger["window_end_timestamp_ms"],
        errors="coerce",
    )
    if (
        window_starts.isna().any()
        or window_ends.isna().any()
        or window_starts.nunique() != 1
        or window_ends.nunique() != 1
    ):
        raise FullResourceContractError("ingress measurement window must be finite and unique")
    window_start_ns = round(float(window_starts.iloc[0]) * 1_000_000)
    window_end_ns = round(float(window_ends.iloc[0]) * 1_000_000)
    if window_end_ns <= window_start_ns:
        raise FullResourceContractError("ingress measurement window is invalid")

    if topology_kind not in {"independent_processes", "shared_video_dag"}:
        raise FullResourceContractError(f"unsupported topology_kind: {topology_kind}")
    required_topology_columns = {
        "event_kind",
        "trace_id",
        "stream_id",
        "frame_id",
        "branch_id",
        "execution_id",
    }
    if not required_topology_columns.issubset(topology_events.columns):
        raise FullResourceContractError("topology events lack fanout linkage columns")
    expected_fanout_keys = {
        (
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
            str(row["branch_id"]),
            str(row["execution_id"]),
        )
        for row in topology_events.to_dict(orient="records")
        if str(row["event_kind"]) == "fanout"
    }
    require_fanout_rows = topology_kind == "shared_video_dag"
    if require_fanout_rows != bool(expected_fanout_keys):
        raise FullResourceContractError(
            "fanout topology coverage is inconsistent with the declared topology kind"
        )

    intervals = validate_resource_intervals(
        run_dir / "resource_intervals.csv",
        ingress_ledger=ingress_ledger,
        topology_events=topology_events,
        frame_events=frame_events,
    )
    interval_summary = summarize_resource_interval_extension(
        intervals,
        topology_events=topology_events,
        frame_events=frame_events,
        topology_kind=topology_kind,
    )
    if not bool(interval_summary.get("coverage_complete")):
        raise FullResourceContractError(
            "resource interval linkage coverage is incomplete"
        )

    hardware_samples = validate_hardware_resource_samples(
        run_dir / "hardware_resource_samples.csv",
        expected_run_id=expected_run_id,
        window_start_ns=window_start_ns,
        window_end_ns=window_end_ns,
    )
    hardware_summary = summarize_hardware_resource_samples(hardware_samples)
    fanout_counters = validate_fanout_work_counters(
        run_dir / "fanout_work_counters.csv",
        expected_run_id=expected_run_id,
        expected_fanout_keys=expected_fanout_keys,
        require_rows=require_fanout_rows,
    )
    fanout_thread_cpu_time_ns = int(
        pd.to_numeric(fanout_counters["thread_cpu_time_ns"], errors="raise").sum()
    )
    fanout_work_units = int(
        pd.to_numeric(fanout_counters["work_units"], errors="raise").sum()
    )
    summary = {
        "assessment_schema_version": 1,
        "resource_contract_version": FULL_RESOURCE_CONTRACT_VERSION,
        "evidence_accepted": True,
        "publication_bundle_bound": True,
        "full_resource_coverage_complete": True,
        "measurement_window_start_ns": int(window_start_ns),
        "measurement_window_end_ns": int(window_end_ns),
        "nvdec_busy_equivalent_ns": int(hardware_summary["nvdec_busy_equivalent_ns"]),
        "nvdec_counter_scope": hardware_summary["counter_scope"],
        "fanout_thread_cpu_time_ns": fanout_thread_cpu_time_ns,
        "fanout_work_units": fanout_work_units,
        "fanout_counter_scope": "per_trace_resource_work",
        "resource_interval_summary": interval_summary,
    }
    return {
        "resource_intervals": intervals,
        "hardware_resource_samples": hardware_samples,
        "fanout_work_counters": fanout_counters,
        "summary": summary,
    }
