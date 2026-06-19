#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


TELEMETRY_SCHEMA_VERSION = 2
FRAME_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
    "detector",
    "backend",
    "telemetry_source",
]
FRAME_EVENT_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "role",
    "host",
    "resource",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
    "policy_action",
]
FRAME_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
}
FRAME_EVENT_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
}
NETWORK_COLUMNS = [
    "timestamp_ms",
    "source_role",
    "target_role",
    "latency_ms",
    "jitter_ms",
    "packet_loss_percent",
    "bandwidth_mbps",
    "clock_offset_ms",
    "status",
]


class ContractError(RuntimeError):
    pass


_NULL_STRINGS = {"", "none", "nan", "null"}


def _missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _NULL_STRINGS


def _parse_finite_number(value: Any, *, path: Path, row_number: int, column: str) -> float:
    if _missing_value(value):
        raise ContractError(f"{path}:{row_number}: missing or empty value for {column}")
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{path}:{row_number}: invalid numeric value for {column}: {value!r}") from exc
    if not math.isfinite(number):
        raise ContractError(f"{path}:{row_number}: invalid numeric value for {column}: {value!r}")
    return number


def validate_csv_row_fields(
    row: dict[str, Any],
    fieldnames: list[str],
    *,
    path: Path,
    row_number: int,
    numeric_columns: set[str] | None = None,
) -> dict[str, Any]:
    if None in row:
        raise ContractError(f"{path}:{row_number}: unexpected extra CSV fields: {row[None]!r}")
    normalized: dict[str, Any] = {}
    for field in fieldnames:
        value = row.get(field)
        if _missing_value(value):
            raise ContractError(f"{path}:{row_number}: missing or empty value for {field}")
        normalized[field] = value
    if "trace_id" in fieldnames and not str(normalized.get("trace_id", "")).strip():
        raise ContractError(f"{path}:{row_number}: missing or empty trace_id")
    for field in numeric_columns or set():
        _parse_finite_number(normalized[field], path=path, row_number=row_number, column=field)
    return normalized


def _validate_csv_file_rows(path: Path, fieldnames: list[str], numeric_columns: set[str]) -> None:
    with path.open("r", newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        for row_number, row in enumerate(reader, start=2):
            validate_csv_row_fields(
                row,
                fieldnames,
                path=path,
                row_number=row_number,
                numeric_columns=numeric_columns,
            )


def _validate_dataframe_fields(
    df: pd.DataFrame,
    path: Path,
    fieldnames: list[str],
    numeric_columns: set[str],
) -> None:
    missing = [column for column in fieldnames if column not in df.columns]
    if missing:
        raise ContractError(f"{path} is missing required columns: {', '.join(missing)}")
    for row_index, row in df[fieldnames].iterrows():
        row_number = int(row_index) + 2
        for field in fieldnames:
            if _missing_value(row[field]):
                raise ContractError(f"{path}:{row_number}: missing or empty value for {field}")
        if "trace_id" in fieldnames and not str(row["trace_id"]).strip():
            raise ContractError(f"{path}:{row_number}: missing or empty trace_id")
        for field in numeric_columns:
            _parse_finite_number(row[field], path=path, row_number=row_number, column=field)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_dataset(
    manifest_path: Path,
    dataset_name: str,
    *,
    mode: str,
    project_root: Path,
    require_files: bool,
    allow_placeholder_checksums: bool = False,
) -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}
    datasets = manifest.get("datasets", {})
    if dataset_name not in datasets:
        raise ContractError(f"unknown dataset '{dataset_name}' in {manifest_path}")

    dataset = dict(datasets[dataset_name] or {})
    dataset["name"] = dataset_name
    streams = list(dataset.get("streams") or [])
    if not streams:
        raise ContractError(f"dataset '{dataset_name}' has no streams")
    if mode == "benchmark" and not bool(dataset.get("publishable")):
        raise ContractError(f"dataset '{dataset_name}' is not publishable and cannot be used in benchmark mode")

    resolved_streams: list[dict[str, Any]] = []
    checksums: list[str] = []
    for raw_stream in streams:
        stream = dict(raw_stream or {})
        rel_path = Path(str(stream.get("path", "")))
        if not str(rel_path):
            raise ContractError(f"dataset '{dataset_name}' contains a stream without path")
        abs_path = project_root / rel_path
        expected = str(stream.get("sha256", "")).strip()
        if mode == "benchmark" and not allow_placeholder_checksums and (not expected or expected.startswith("SET_")):
            raise ContractError(f"dataset '{dataset_name}' requires a real sha256 for {rel_path}")
        if require_files and not abs_path.exists():
            raise ContractError(f"dataset stream is missing: {abs_path}")
        actual = sha256_file(abs_path) if abs_path.exists() else ""
        if expected and actual and expected != actual:
            raise ContractError(f"dataset checksum mismatch for {rel_path}: expected {expected}, got {actual}")
        checksums.append(actual or expected or "missing")
        stream["absolute_path"] = str(abs_path)
        stream["resolved_sha256"] = actual or expected
        resolved_streams.append(stream)

    dataset["streams"] = resolved_streams
    dataset["aggregate_sha256"] = hashlib.sha256("\n".join(checksums).encode("utf-8")).hexdigest()
    return dataset


def _first_existing(df: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name]
    raise ContractError(f"frames.csv is missing required columns: one of {names}")


def canonicalize_frames_csv(
    path: Path,
    *,
    mode: str,
    run_id: str,
    detector: str,
    backend: str,
) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"frames.csv was not produced: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frames.csv is empty: {path}")

    missing = [column for column in FRAME_COLUMNS if column not in df.columns]
    if missing:
        if mode == "benchmark":
            raise ContractError(
                "benchmark mode requires native telemetry schema v2; "
                f"{path} is missing: {', '.join(missing)}"
            )
        egress = pd.to_numeric(_first_existing(df, "egress_timestamp_ms", "timestamp_ms"), errors="raise")
        latency = pd.to_numeric(_first_existing(df, "e2e_latency_ms", "latency_ms"), errors="raise")
        stream_ids = pd.to_numeric(_first_existing(df, "stream_id"), errors="raise").astype(int)
        frame_ids = pd.to_numeric(_first_existing(df, "frame_id"), errors="raise").astype(int)
        objects = (
            pd.to_numeric(df["objects"], errors="coerce").fillna(0).astype(int)
            if "objects" in df.columns
            else pd.Series([0] * len(df))
        )
        df = pd.DataFrame(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "trace_id": [
                    f"{run_id}:{stream_id}:{frame_id}"
                    for stream_id, frame_id in zip(stream_ids, frame_ids, strict=True)
                ],
                "stream_id": stream_ids,
                "frame_id": frame_ids,
                "ingress_timestamp_ms": egress - latency,
                "egress_timestamp_ms": egress,
                "e2e_latency_ms": latency,
                "objects": objects,
                "detector": detector,
                "backend": backend,
                "telemetry_source": "synthetic",
            }
        )
        df.to_csv(path, index=False)

    _validate_dataframe_fields(df, path, FRAME_COLUMNS, FRAME_NUMERIC_COLUMNS)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported telemetry schema version in {path}")
    if mode == "benchmark" and set(df["telemetry_source"].astype(str)) != {"native"}:
        raise ContractError("benchmark mode only accepts telemetry_source=native")
    if df["trace_id"].astype(str).duplicated().any():
        raise ContractError(f"duplicate trace_id values in {path}")
    if (pd.to_numeric(df["e2e_latency_ms"], errors="raise") < 0).any():
        raise ContractError(f"negative e2e latency in {path}")
    return df[FRAME_COLUMNS]


def summarize_frames(path: Path, *, deadline_s: float, measurement_s: float) -> dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frames.csv is empty: {path}")
    latency = pd.to_numeric(df["e2e_latency_ms"], errors="raise")
    frames = int(df.shape[0])
    duration_s = max(float(measurement_s), 0.001)
    return {
        "throughput_fps": round(frames / duration_s, 3),
        "latency_p50_ms": round(float(latency.quantile(0.50)), 3),
        "latency_p95_ms": round(float(latency.quantile(0.95)), 3),
        "latency_p99_ms": round(float(latency.quantile(0.99)), 3),
        "slo_violation_rate_percent": round(float((latency > deadline_s * 1000.0).mean() * 100.0), 3),
        "frames": frames,
        "telemetry_source": ",".join(sorted(set(df["telemetry_source"].astype(str)))),
    }


def validate_frame_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"frame_events.csv was not produced: {path}")
    _validate_csv_file_rows(path, FRAME_EVENT_COLUMNS, FRAME_EVENT_NUMERIC_COLUMNS)
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frame_events.csv is empty: {path}")
    missing = [column for column in FRAME_EVENT_COLUMNS if column not in df.columns]
    if missing:
        raise ContractError(f"{path} is missing frame event columns: {', '.join(missing)}")
    _validate_dataframe_fields(df, path, FRAME_EVENT_COLUMNS, FRAME_EVENT_NUMERIC_COLUMNS)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported frame event schema version in {path}")
    return df[FRAME_EVENT_COLUMNS]


def validate_stage_trace_coverage(
    frames_path: Path,
    frame_events_path: Path,
    *,
    required_stages: list[str],
) -> None:
    frames = canonicalize_frames_csv(
        frames_path,
        mode="benchmark",
        run_id="",
        detector="",
        backend="",
    )
    events = validate_frame_events(frame_events_path)
    frame_traces = set(frames["trace_id"].astype(str))
    if not frame_traces:
        raise ContractError(f"frames.csv has no trace_id values: {frames_path}")
    for stage in required_stages:
        stage_traces = set(events.loc[events["stage"].astype(str) == str(stage), "trace_id"].astype(str))
        missing = frame_traces - stage_traces
        if missing:
            sample = ", ".join(sorted(missing)[:5])
            raise ContractError(
                f"missing native frame_events for stage '{stage}' "
                f"on {len(missing)} completed frames; sample trace_id values: {sample}"
            )


def network_profile_matches(measured: dict[str, float], acceptance: dict[str, list[float]]) -> tuple[bool, str]:
    for key, limits in acceptance.items():
        if key not in measured:
            return False, f"missing measured network metric: {key}"
        if len(limits) != 2:
            return False, f"network acceptance range for {key} must contain [min, max]"
        lo, hi = float(limits[0]), float(limits[1])
        value = float(measured[key])
        if value < lo or value > hi:
            return False, f"{key}={value} is outside [{lo}, {hi}]"
    return True, ""


def git_manifest(project_root: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=project_root, text=True).strip()
        except Exception:
            return "unknown"

    status = run("status", "--porcelain")
    diff = run("diff", "--binary", "HEAD")
    return {
        "commit_sha": run("rev-parse", "HEAD"),
        "dirty": "true" if status else "false",
        "dirty_diff_sha256": hashlib.sha256((status + "\n" + diff).encode("utf-8")).hexdigest(),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
