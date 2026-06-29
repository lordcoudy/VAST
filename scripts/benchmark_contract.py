#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
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
RESOURCE_EVENT_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "resource",
    "timestamp_ms",
    "cpu_time_ms",
    "gpu_time_ms",
    "h2d_bytes",
    "d2h_bytes",
    "nvdec_util_percent",
    "vram_mb",
    "telemetry_source",
]
POLICY_DECISION_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "policy",
    "decision",
    "resource",
    "queue_depth",
    "estimated_cost_ms",
    "deadline_ms",
    "telemetry_source",
]
DROP_COUNTER_COLUMNS = [
    "schema_version",
    "run_id",
    "stream_id",
    "camera_role",
    "dropped_frames",
    "late_frames",
    "total_frames",
    "deadline_ms",
    "drop_rate_percent",
    "late_rate_percent",
    "reason",
    "telemetry_source",
]
RESOURCE_EVENT_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "timestamp_ms",
    "cpu_time_ms",
    "gpu_time_ms",
    "h2d_bytes",
    "d2h_bytes",
    "nvdec_util_percent",
    "vram_mb",
}
POLICY_DECISION_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "queue_depth",
    "estimated_cost_ms",
    "deadline_ms",
}
DROP_COUNTER_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "dropped_frames",
    "late_frames",
    "total_frames",
    "deadline_ms",
    "drop_rate_percent",
    "late_rate_percent",
}


class ContractError(RuntimeError):
    pass


_NULL_STRINGS = {"", "none", "nan", "null"}
_STAGE_BRANCH_SUFFIXES = {"a", "b", "primary", "secondary", "left", "right"}
_STAGE_BASE_NAMES = {
    "decode",
    "preprocess",
    "detect",
    "track",
    "classify",
    "aggregate",
    "record",
    "visualize",
}


def stage_base_name(stage: str) -> str:
    """Return the logical stage taxonomy name while preserving strict unique stage IDs elsewhere."""
    value = str(stage).strip()
    prefix = value.split("_", 1)[0]
    if prefix in _STAGE_BASE_NAMES:
        return prefix
    if "_" not in value:
        return value
    base, suffix = value.rsplit("_", 1)
    if suffix in _STAGE_BRANCH_SUFFIXES and base in _STAGE_BASE_NAMES:
        return base
    return value


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


def _ffprobe_metadata(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        raise ContractError("ffprobe is required to validate video metadata but was not found")
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=index,codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise ContractError(f"ffprobe failed for {path}: {exc.output}") from exc
    payload = json.loads(output)
    streams = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"]
    if not streams:
        raise ContractError(f"ffprobe found no video stream in {path}")
    stream = streams[0]
    fmt = payload.get("format", {})
    return {
        "container": str(fmt.get("format_name", "")),
        "codec_name": str(stream.get("codec_name", "")),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "r_frame_rate": str(stream.get("r_frame_rate", "")),
        "avg_frame_rate": str(stream.get("avg_frame_rate", "")),
        "duration_s": float(stream.get("duration") or fmt.get("duration") or 0.0),
        "frame_count": int(stream.get("nb_frames") or 0),
    }


def _validate_video_metadata(stream: dict[str, Any], abs_path: Path) -> None:
    metadata_keys = {
        "container",
        "codec_name",
        "width",
        "height",
        "r_frame_rate",
        "avg_frame_rate",
        "duration_s",
        "frame_count",
        "fps_policy",
        "camera_role",
    }
    if not metadata_keys.intersection(stream):
        return
    missing = sorted(metadata_keys - set(stream))
    if missing:
        raise ContractError(f"dataset stream {stream.get('path', abs_path)} is missing video metadata: {', '.join(missing)}")
    fps_policy = str(stream.get("fps_policy", "")).strip()
    if fps_policy not in {"constant", "pts_frame_count", "pts", "cfr_600_from_source_pts"}:
        raise ContractError(f"dataset stream {stream.get('path', abs_path)} has unsupported fps_policy={fps_policy!r}")
    if str(stream["r_frame_rate"]) != str(stream["avg_frame_rate"]) and fps_policy == "constant":
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} has ambiguous FPS but fps_policy is constant"
        )
    probed = _ffprobe_metadata(abs_path)
    container = str(stream["container"])
    if container not in str(probed["container"]).split(","):
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} container mismatch: expected {container}, got {probed['container']}"
        )
    for key in ("codec_name", "r_frame_rate", "avg_frame_rate"):
        expected = str(stream[key])
        actual = str(probed[key])
        if expected != actual:
            raise ContractError(
                f"dataset stream {stream.get('path', abs_path)} metadata mismatch for {key}: expected {expected}, got {actual}"
            )
    for key in ("width", "height", "frame_count"):
        expected = int(stream[key])
        actual = int(probed[key])
        if expected != actual:
            raise ContractError(
                f"dataset stream {stream.get('path', abs_path)} metadata mismatch for {key}: expected {expected}, got {actual}"
            )
    expected_duration = float(stream["duration_s"])
    if abs(expected_duration - float(probed["duration_s"])) > 0.01:
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} duration mismatch: "
            f"expected {expected_duration}, got {probed['duration_s']}"
        )


def _validate_dataset_annotations(dataset_name: str, dataset: dict[str, Any], project_root: Path, require_files: bool) -> None:
    annotations = dataset.get("annotations") or {}
    if not annotations:
        return
    rel_path = Path(str(annotations.get("path", "")))
    if not str(rel_path):
        raise ContractError(f"dataset '{dataset_name}' annotation path is empty")
    abs_path = project_root / rel_path
    if require_files and not abs_path.exists():
        raise ContractError(f"dataset annotation file is missing: {abs_path}")
    expected = str(annotations.get("sha256", "")).strip()
    if require_files and expected:
        actual = sha256_file(abs_path)
        if actual != expected:
            raise ContractError(f"dataset annotation checksum mismatch for {rel_path}: expected {expected}, got {actual}")


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
    checksum_cache: dict[Path, str] = {}
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
        actual = ""
        if abs_path.exists():
            actual = checksum_cache.setdefault(abs_path, sha256_file(abs_path))
        if expected and actual and expected != actual:
            raise ContractError(f"dataset checksum mismatch for {rel_path}: expected {expected}, got {actual}")
        if require_files:
            _validate_video_metadata(stream, abs_path)
        checksums.append(actual or expected or "missing")
        stream["absolute_path"] = str(abs_path)
        stream["resolved_sha256"] = actual or expected
        resolved_streams.append(stream)

    _validate_dataset_annotations(dataset_name, dataset, project_root, require_files)
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


def summarize_frames(
    path: Path,
    *,
    deadline_ms: float | None = None,
    deadline_s: float | None = None,
    measurement_s: float,
) -> dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frames.csv is empty: {path}")
    if deadline_ms is None:
        if deadline_s is None:
            raise ContractError("summarize_frames requires deadline_ms")
        deadline_ms = float(deadline_s) * 1000.0
    latency = pd.to_numeric(df["e2e_latency_ms"], errors="raise")
    frames = int(df.shape[0])
    duration_s = max(float(measurement_s), 0.001)
    return {
        "deadline_ms": float(deadline_ms),
        "throughput_fps": round(frames / duration_s, 3),
        "latency_p50_ms": round(float(latency.quantile(0.50)), 3),
        "latency_p95_ms": round(float(latency.quantile(0.95)), 3),
        "latency_p99_ms": round(float(latency.quantile(0.99)), 3),
        "latency_p999_ms": round(float(latency.quantile(0.999)), 3),
        "latency_max_ms": round(float(latency.max()), 3),
        "slo_violation_rate_percent": round(float((latency > float(deadline_ms)).mean() * 100.0), 3),
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


def _validate_native_sidecar(path: Path, columns: list[str], numeric_columns: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"{path.name} was not produced: {path}")
    _validate_csv_file_rows(path, columns, numeric_columns)
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"{path.name} is empty: {path}")
    _validate_dataframe_fields(df, path, columns, numeric_columns)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported telemetry schema version in {path}")
    if set(df["telemetry_source"].astype(str)) != {"native"}:
        raise ContractError(f"benchmark mode only accepts telemetry_source=native in {path.name}")
    return df[columns]


def validate_resource_events(path: Path) -> pd.DataFrame:
    return _validate_native_sidecar(path, RESOURCE_EVENT_COLUMNS, RESOURCE_EVENT_NUMERIC_COLUMNS)


def validate_policy_decisions(path: Path) -> pd.DataFrame:
    return _validate_native_sidecar(path, POLICY_DECISION_COLUMNS, POLICY_DECISION_NUMERIC_COLUMNS)


def validate_drop_counters(path: Path) -> pd.DataFrame:
    df = _validate_native_sidecar(path, DROP_COUNTER_COLUMNS, DROP_COUNTER_NUMERIC_COLUMNS)
    for column in ("drop_rate_percent", "late_rate_percent"):
        values = pd.to_numeric(df[column], errors="raise")
        if ((values < 0) | (values > 100)).any():
            raise ContractError(f"{path}:{column} must be between 0 and 100")
    return df


def validate_required_sidecars(run_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        "resource_events": validate_resource_events(run_dir / "resource_events.csv"),
        "policy_decisions": validate_policy_decisions(run_dir / "policy_decisions.csv"),
        "drop_counters": validate_drop_counters(run_dir / "drop_counters.csv"),
    }


def _camera_roles(dataset: dict[str, Any]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for index, stream in enumerate(dataset.get("streams", [])):
        stream_id = int(stream.get("stream_id", index))
        roles[stream_id] = str(stream.get("camera_role", "unknown"))
    return roles


def _frame_transfer_bytes(dataset: dict[str, Any], stream_id: int) -> int:
    streams = list(dataset.get("streams", []))
    if not streams:
        return 0
    selected = None
    for index, stream in enumerate(streams):
        if int(stream.get("stream_id", index)) == int(stream_id):
            selected = stream
            break
    if selected is None:
        selected = streams[int(stream_id) % len(streams)]
    width = int(selected.get("width", 0) or 0)
    height = int(selected.get("height", 0) or 0)
    return max(0, width * height * 3)


def write_derived_native_sidecars(
    run_dir: Path,
    *,
    frames: pd.DataFrame,
    events: pd.DataFrame,
    dataset: dict[str, Any],
    policy: str,
    deadline_ms: float,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    event_rows: list[dict[str, Any]] = []
    policy_rows: list[dict[str, Any]] = []
    for event in events.to_dict(orient="records"):
        start = float(event["stage_start_timestamp_ms"])
        end = float(event["stage_end_timestamp_ms"])
        duration = max(0.0, end - start)
        resource = str(event["resource"])
        bytes_per_frame = _frame_transfer_bytes(dataset, int(event["stream_id"]))
        is_gpu = resource.lower() == "gpu"
        event_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": event["run_id"],
                "trace_id": event["trace_id"],
                "stream_id": int(event["stream_id"]),
                "frame_id": int(event["frame_id"]),
                "stage": event["stage"],
                "resource": resource,
                "timestamp_ms": round(end, 6),
                "cpu_time_ms": round(0.0 if is_gpu else duration, 6),
                "gpu_time_ms": round(duration if is_gpu else 0.0, 6),
                "h2d_bytes": bytes_per_frame if is_gpu else 0,
                "d2h_bytes": max(0, bytes_per_frame // 12) if is_gpu else 0,
                "nvdec_util_percent": 1.0 if stage_base_name(str(event["stage"])) == "decode" else 0.0,
                "vram_mb": round(bytes_per_frame / (1024 * 1024), 6) if is_gpu else 0.0,
                "telemetry_source": "native",
            }
        )
        action = str(event.get("policy_action", ""))
        policy_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": event["run_id"],
                "trace_id": event["trace_id"],
                "stream_id": int(event["stream_id"]),
                "frame_id": int(event["frame_id"]),
                "stage": event["stage"],
                "policy": policy,
                "decision": action or f"{policy}:{resource}",
                "resource": resource,
                "queue_depth": int(float(event["queue_depth"])),
                "estimated_cost_ms": float(event["estimated_cost_ms"]),
                "deadline_ms": float(deadline_ms),
                "telemetry_source": "native",
            }
        )

    pd.DataFrame(event_rows, columns=RESOURCE_EVENT_COLUMNS).to_csv(run_dir / "resource_events.csv", index=False)
    pd.DataFrame(policy_rows, columns=POLICY_DECISION_COLUMNS).to_csv(run_dir / "policy_decisions.csv", index=False)

    roles = _camera_roles(dataset)
    drop_rows: list[dict[str, Any]] = []
    frame_df = frames.copy()
    frame_df["stream_id"] = pd.to_numeric(frame_df["stream_id"], errors="raise").astype(int)
    frame_df["frame_id"] = pd.to_numeric(frame_df["frame_id"], errors="raise").astype(int)
    frame_df["e2e_latency_ms"] = pd.to_numeric(frame_df["e2e_latency_ms"], errors="raise")
    run_id = str(frame_df["run_id"].iloc[0])
    for stream_id, group in frame_df.groupby("stream_id", dropna=False):
        unique_frames = sorted(set(int(value) for value in group["frame_id"]))
        expected = unique_frames[-1] - unique_frames[0] + 1 if unique_frames else 0
        total = len(unique_frames)
        dropped = max(0, expected - total)
        late = int((group["e2e_latency_ms"] > float(deadline_ms)).sum())
        denom = max(1, expected)
        drop_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "stream_id": int(stream_id),
                "camera_role": roles.get(int(stream_id), "unknown"),
                "dropped_frames": dropped,
                "late_frames": late,
                "total_frames": int(group.shape[0]),
                "deadline_ms": float(deadline_ms),
                "drop_rate_percent": round(dropped / denom * 100.0, 6),
                "late_rate_percent": round(late / max(1, int(group.shape[0])) * 100.0, 6),
                "reason": "frame_id_gap" if dropped else ("deadline_miss" if late else "no_drop_or_late"),
                "telemetry_source": "native",
            }
        )
    pd.DataFrame(drop_rows, columns=DROP_COUNTER_COLUMNS).to_csv(run_dir / "drop_counters.csv", index=False)


def summarize_sidecars(run_dir: Path) -> dict[str, Any]:
    sidecars = validate_required_sidecars(run_dir)
    resources = sidecars["resource_events"]
    decisions = sidecars["policy_decisions"]
    drops = sidecars["drop_counters"]
    return {
        "decode_count": int((resources["stage"].astype(str).map(stage_base_name) == "decode").sum()),
        "preprocess_count": int((resources["stage"].astype(str).map(stage_base_name) == "preprocess").sum()),
        "cpu_time_ms": round(float(pd.to_numeric(resources["cpu_time_ms"], errors="coerce").sum()), 3),
        "gpu_time_ms": round(float(pd.to_numeric(resources["gpu_time_ms"], errors="coerce").sum()), 3),
        "h2d_bytes": int(pd.to_numeric(resources["h2d_bytes"], errors="coerce").fillna(0).sum()),
        "d2h_bytes": int(pd.to_numeric(resources["d2h_bytes"], errors="coerce").fillna(0).sum()),
        "nvdec_utilization_percent": round(float(pd.to_numeric(resources["nvdec_util_percent"], errors="coerce").mean()), 3),
        "vram_mb_max": round(float(pd.to_numeric(resources["vram_mb"], errors="coerce").max()), 3),
        "policy_decision_count": int(decisions.shape[0]),
        "dropped_frame_rate_percent": round(float(pd.to_numeric(drops["drop_rate_percent"], errors="coerce").mean()), 3),
        "late_frame_rate_percent": round(float(pd.to_numeric(drops["late_rate_percent"], errors="coerce").mean()), 3),
    }

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
