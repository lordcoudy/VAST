#!/usr/bin/env python3
"""Durable article-ready statistics sealed before pair archival and pruning."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from benchmark_contract import ContractError, stage_base_name, summarize_measurement_passport
from full_resource_contract import (
    FullResourceContractError,
    validate_full_resource_evidence,
)
from publication_acceptance_evidence import accepted_arm_evidence_files
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from resource_interval_contract import ResourceIntervalContractError


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_full_publication_article_statistics_pair"
BINDING_KIND = "vast_full_publication_article_statistics_binding"
STATUS = "sealed_article_ready_statistics"
ATTEMPT_COPY_NAME = "article_statistics.v1.json"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DISTRIBUTION_KEYS = {
    "count",
    "sum",
    "sum_squares",
    "sum_squared_deviations",
    "minimum",
    "p25",
    "p50",
    "p75",
    "p90",
    "p95",
    "p99",
    "maximum",
    "mean",
    "population_stddev",
}
_COORDINATE_KEYS = {
    "arm_position",
    "system",
    "scenario",
    "codec",
    "dataset",
    "policy",
    "deadline_ms",
    "repeat",
    "streams",
    "seed",
    "warmup_s",
    "measurement_s",
    "run_seed",
    "deployment_mode",
    "host_topology",
    "run_mode",
    "telemetry_source",
}
_DESCRIPTIVE_KEYS = {
    "measurement_window_duration_ms",
    "arm_performance",
    "per_stream",
    "stage_statistics",
    "resource_statistics",
    "policy_decision_statistics",
    "drop_counter_statistics",
    "measurement_passport",
    "full_resource_statistics",
}
_PERFORMANCE_KEYS = {
    "ingress",
    "completed_latency_ms",
    "deadline_outcomes",
    "throughput_completed_fps",
}
_INGRESS_KEYS = {
    "count",
    "completed",
    "dropped",
    "censored",
    "completed_rate_percent",
    "drop_rate_percent",
    "censored_rate_percent",
}
_POLICY_STAT_KEYS = {
    "row_count",
    "decision_counts",
    "resource_counts",
    "stage_counts",
    "reason_counts",
    "terminal_status_counts",
}
_DROP_STAT_KEYS = {
    "row_count",
    "dropped_frames",
    "late_frames",
    "total_frames",
    "drop_rate_percent",
    "late_rate_percent",
}
_STAGE_STAT_KEYS = {
    "stage",
    "base_stage",
    "role",
    "resource",
    "event_count",
    "stage_duration_ms",
    "queue_wait_ms",
}
_RESOURCE_STAT_KEYS = {
    "stage",
    "base_stage",
    "resource",
    "event_count",
    "numeric",
}
_RESOURCE_NUMERIC_KEYS = {
    "cpu_time_ms",
    "gpu_time_ms",
    "h2d_bytes",
    "d2h_bytes",
    "nvdec_util_percent",
    "vram_mb",
}
_FULL_RESOURCE_STAT_KEYS = {
    "summary",
    "hardware_by_device",
    "interval_by_component",
    "fanout",
}
_FULL_RESOURCE_SUMMARY_KEYS = {
    "assessment_schema_version",
    "resource_contract_version",
    "evidence_accepted",
    "publication_bundle_bound",
    "full_resource_coverage_complete",
    "measurement_window_start_ns",
    "measurement_window_end_ns",
    "nvdec_busy_equivalent_ns",
    "nvdec_interval_device_ids",
    "nvdec_sampled_gpu_device_ids",
    "nvdec_counter_scope",
    "fanout_thread_cpu_time_ns",
    "fanout_work_units",
    "fanout_counter_scope",
    "resource_interval_summary",
}
_MEASUREMENT_PASSPORT_KEYS = {
    "resource_attribution_complete",
    "resource_attribution",
    "resource_attributed_ingress_count",
    "resource_unattributed_event_count",
    "input_schedule_sha256",
    "input_frame_key_sequence_sha256",
    "measurement_window_duration_ms",
    "measurement_signature",
    "measurement_signature_payload_json",
    "c_obs_total_ms",
    "c_obs_cpu_total_ms",
    "c_obs_gpu_total_ms",
    "c_obs_in_ms_per_ingress",
    "c_obs_cpu_in_ms_per_ingress",
    "c_obs_gpu_in_ms_per_ingress",
    "c_obs_comp_ms_per_completed",
    "c_obs_is_partial",
}
_PAIR_IDENTITY_KEYS = {
    "matrix_sha256",
    "run_id",
    "pair_sequence",
    "pair_id",
    "pair_sha256",
    "attempt",
}


class ArticleStatisticsV1Error(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise ArticleStatisticsV1Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ArticleStatisticsV1Error(
            f"article-statistics value is not canonical JSON: {error}"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_immutable_write(
    custody: PhysicalRootCustodyV1,
    path: Path,
    payload: bytes,
    *,
    label: str,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """No-follow/no-replace commit with exact-byte idempotent recovery."""

    try:
        descriptor, _identity, _disposition = (
            custody.commit_or_adopt_exact_identity(
                path,
                payload,
                label=label,
                mode=0o600,
                create_parents=False,
                after_publish_step=after_publish_step,
            )
        )
    except PublicationPhysicalIoV1Error as error:
        raise ArticleStatisticsV1Error(
            f"immutable article-statistics commit/collision failed for "
            f"{path.name}: {error}"
        ) from error
    return {
        "relative_path": descriptor["path"],
        "size_bytes": descriptor["size_bytes"],
        "sha256": descriptor["sha256"],
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    item = getattr(value, "item", None)
    if callable(item):
        return _json_value(item())
    if isinstance(value, Mapping):
        return {str(key): _json_value(item_value) for key, item_value in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item_value) for item_value in value]
    return str(value)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(int(getattr(info, "st_file_attributes", 0)) & reparse_flag)


def _stable_descriptor(path: Path, *, relative_to: Path, expected_sha: str | None = None) -> dict[str, Any]:
    try:
        before = path.lstat()
    except FileNotFoundError:
        _fail(f"article-statistics evidence is missing: {path.name}")
    if _is_link_or_reparse(path) or not stat.S_ISREG(before.st_mode):
        _fail(f"article-statistics evidence must be a regular file: {path.name}")
    digest = _sha256_file(path)
    try:
        after = path.lstat()
    except FileNotFoundError:
        _fail(f"article-statistics evidence changed while hashing: {path.name}")
    identity_before = (
        int(before.st_dev),
        int(before.st_ino),
        int(before.st_size),
        int(getattr(before, "st_ctime_ns", 0)),
    )
    identity_after = (
        int(after.st_dev),
        int(after.st_ino),
        int(after.st_size),
        int(getattr(after, "st_ctime_ns", 0)),
    )
    if identity_before != identity_after:
        _fail(f"article-statistics evidence changed while hashing: {path.name}")
    if expected_sha is not None and digest != expected_sha:
        _fail(f"article-statistics evidence SHA-256 drift: {path.name}")
    try:
        relative = path.resolve().relative_to(relative_to.resolve()).as_posix()
    except ValueError:
        _fail(f"article-statistics evidence escaped pair root: {path.name}")
    return {
        "relative_path": relative,
        "size_bytes": int(after.st_size),
        "sha256": digest,
    }


def _number(value: Any, *, label: str, nullable: bool = False) -> float | int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be a finite number")
    return value


def _percentage(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) * 100.0 if denominator else None


def _distribution(values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="raise").astype(float)
    if numeric.empty:
        return {
            "count": 0,
            "sum": 0.0,
            "sum_squares": 0.0,
            "sum_squared_deviations": 0.0,
            "minimum": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "maximum": None,
            "mean": None,
            "population_stddev": None,
        }
    if not numeric.map(math.isfinite).all():
        _fail("descriptive distribution contains a non-finite observation")
    quantiles = numeric.quantile([0.25, 0.50, 0.75, 0.90, 0.95, 0.99])
    mean = float(numeric.mean())
    return {
        "count": int(numeric.shape[0]),
        "sum": float(numeric.sum()),
        "sum_squares": float((numeric * numeric).sum()),
        "sum_squared_deviations": float(((numeric - mean) ** 2).sum()),
        "minimum": float(numeric.min()),
        "p25": float(quantiles.loc[0.25]),
        "p50": float(quantiles.loc[0.50]),
        "p75": float(quantiles.loc[0.75]),
        "p90": float(quantiles.loc[0.90]),
        "p95": float(quantiles.loc[0.95]),
        "p99": float(quantiles.loc[0.99]),
        "maximum": float(numeric.max()),
        "mean": mean,
        "population_stddev": float(numeric.std(ddof=0)),
    }


def _performance_statistics(
    frames: pd.DataFrame,
    ingress: pd.DataFrame,
    *,
    deadlines_ms: Sequence[float],
    measurement_window_duration_ms: float,
) -> dict[str, Any]:
    statuses = ingress["terminal_status"].astype(str)
    ingress_count = int(ingress.shape[0])
    completed = int(statuses.eq("completed").sum())
    dropped = int(statuses.eq("drop").sum())
    censored = int(statuses.eq("censored").sum())
    latency = pd.to_numeric(frames["e2e_latency_ms"], errors="raise").astype(float)
    outcomes = []
    for deadline in deadlines_ms:
        violations = int((latency > float(deadline)).sum())
        outcomes.append(
            {
                "deadline_ms": float(deadline),
                "violations": violations,
                "rate_percent": _percentage(violations, int(latency.shape[0])),
            }
        )
    duration_seconds = float(measurement_window_duration_ms) / 1000.0
    if duration_seconds <= 0.0:
        _fail("measurement window duration must be positive")
    return {
        "ingress": {
            "count": ingress_count,
            "completed": completed,
            "dropped": dropped,
            "censored": censored,
            "completed_rate_percent": _percentage(completed, ingress_count),
            "drop_rate_percent": _percentage(dropped, ingress_count),
            "censored_rate_percent": _percentage(censored, ingress_count),
        },
        "completed_latency_ms": _distribution(latency),
        "deadline_outcomes": outcomes,
        "throughput_completed_fps": float(latency.shape[0]) / duration_seconds,
    }


def _frequency_rows(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if column not in frame.columns or frame.empty:
        return []
    counts = frame[column].astype(str).value_counts(dropna=False).sort_index()
    return [
        {"value": str(value), "count": int(count)}
        for value, count in counts.items()
    ]


def _policy_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "row_count": int(frame.shape[0]),
        "decision_counts": _frequency_rows(frame, "decision"),
        "resource_counts": _frequency_rows(frame, "resource"),
        "stage_counts": _frequency_rows(frame, "stage"),
        "reason_counts": _frequency_rows(frame, "reason"),
        "terminal_status_counts": _frequency_rows(frame, "terminal_status"),
    }


def _drop_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    def total(column: str) -> int:
        if frame.empty or column not in frame.columns:
            return 0
        return int(pd.to_numeric(frame[column], errors="raise").sum())

    dropped = total("dropped_frames")
    late = total("late_frames")
    total_frames = total("total_frames")
    return {
        "row_count": int(frame.shape[0]),
        "dropped_frames": dropped,
        "late_frames": late,
        "total_frames": total_frames,
        "drop_rate_percent": _percentage(dropped, total_frames),
        "late_rate_percent": _percentage(late, total_frames),
    }


def _stage_statistics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    events = frame.copy()
    events["base_stage"] = events["stage"].astype(str).map(stage_base_name)
    events["stage_duration_ms"] = (
        pd.to_numeric(events["stage_end_timestamp_ms"], errors="raise")
        - pd.to_numeric(events["stage_start_timestamp_ms"], errors="raise")
    )
    events["queue_wait_ms"] = (
        pd.to_numeric(events["stage_start_timestamp_ms"], errors="raise")
        - pd.to_numeric(events["queue_enter_timestamp_ms"], errors="raise")
    )
    rows = []
    keys = ["stage", "base_stage", "role", "resource"]
    for values, group in events.groupby(keys, dropna=False, sort=True):
        stage, base_stage, role, resource = values
        rows.append(
            {
                "stage": str(stage),
                "base_stage": str(base_stage),
                "role": str(role),
                "resource": str(resource),
                "event_count": int(group.shape[0]),
                "stage_duration_ms": _distribution(group["stage_duration_ms"]),
                "queue_wait_ms": _distribution(group["queue_wait_ms"]),
            }
        )
    return rows


def _resource_statistics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    resources = frame.copy()
    resources["base_stage"] = resources["stage"].astype(str).map(stage_base_name)
    numeric_columns = (
        "cpu_time_ms",
        "gpu_time_ms",
        "h2d_bytes",
        "d2h_bytes",
        "nvdec_util_percent",
        "vram_mb",
    )
    rows = []
    for values, group in resources.groupby(
        ["stage", "base_stage", "resource"], dropna=False, sort=True
    ):
        stage, base_stage, resource = values
        rows.append(
            {
                "stage": str(stage),
                "base_stage": str(base_stage),
                "resource": str(resource),
                "event_count": int(group.shape[0]),
                "numeric": {
                    column: _distribution(group[column]) for column in numeric_columns
                },
            }
        )
    return rows


def _full_resource_statistics(full: Mapping[str, Any]) -> dict[str, Any]:
    samples = full["hardware_resource_samples"]
    intervals = full["resource_intervals"]
    fanout = full["fanout_work_counters"]
    hardware_rows = []
    for device_id, group in samples.groupby("device_id", dropna=False, sort=True):
        hardware_rows.append(
            {
                "device_id": str(device_id),
                "sample_count": int(group.shape[0]),
                "sample_period_us": _distribution(group["sample_period_us"]),
                "nvdec_util_percent": _distribution(group["nvdec_util_percent"]),
                "gpu_util_percent": _distribution(group["gpu_util_percent"]),
                "memory_util_percent": _distribution(group["memory_util_percent"]),
                "vram_used_bytes": _distribution(group["vram_used_bytes"]),
            }
        )
    interval_rows = []
    for values, group in intervals.groupby(
        ["component", "direction", "device_id"], dropna=False, sort=True
    ):
        component, direction, device_id = values
        interval_rows.append(
            {
                "component": str(component),
                "direction": str(direction),
                "device_id": str(device_id),
                "row_count": int(group.shape[0]),
                "duration_ns": _distribution(group["duration_ns"]),
                "bytes": _distribution(group["bytes"]),
            }
        )
    return {
        "summary": _json_value(full["summary"]),
        "hardware_by_device": hardware_rows,
        "interval_by_component": interval_rows,
        "fanout": {
            "row_count": int(fanout.shape[0]),
            "thread_cpu_time_ns": int(
                pd.to_numeric(fanout.get("thread_cpu_time_ns", pd.Series(dtype=int)), errors="raise").sum()
            ),
            "work_units": int(
                pd.to_numeric(fanout.get("work_units", pd.Series(dtype=int)), errors="raise").sum()
            ),
        },
    }


def _validate_distribution(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DISTRIBUTION_KEYS:
        _fail(f"{label} distribution schema drift")
    count = value.get("count")
    if type(count) is not int or count < 0:
        _fail(f"{label} distribution count is invalid")
    for field in ("sum", "sum_squares", "sum_squared_deviations"):
        _number(value.get(field), label=f"{label}.{field}")
    if float(value["sum_squares"]) < 0.0 or float(value["sum_squared_deviations"]) < 0.0:
        _fail(f"{label} distribution squared totals must be non-negative")
    nullable_fields = _DISTRIBUTION_KEYS - {
        "count",
        "sum",
        "sum_squares",
        "sum_squared_deviations",
    }
    if count == 0:
        if any(value[field] is not None for field in nullable_fields):
            _fail(f"{label} empty distribution must use null summaries")
        if any(
            float(value[field]) != 0.0
            for field in ("sum", "sum_squares", "sum_squared_deviations")
        ):
            _fail(f"{label} empty distribution totals must be zero")
        return value
    for field in nullable_fields:
        _number(value.get(field), label=f"{label}.{field}")
    ordered = [
        float(value[field])
        for field in ("minimum", "p25", "p50", "p75", "p90", "p95", "p99", "maximum")
    ]
    if ordered != sorted(ordered):
        _fail(f"{label} distribution order is invalid")
    minimum = float(value["minimum"])
    maximum = float(value["maximum"])
    observed_sum = float(value["sum"])
    if observed_sum < minimum * count - 1e-9 or observed_sum > maximum * count + 1e-9:
        _fail(f"{label} distribution sum is outside its recorded range")
    expected_mean = float(value["sum"]) / count
    if not math.isclose(float(value["mean"]), expected_mean, rel_tol=1e-12, abs_tol=1e-12):
        _fail(f"{label} distribution mean is inconsistent")
    m2 = float(value["sum_squared_deviations"])
    expected_sum_squares = m2 + float(value["sum"]) ** 2 / count
    if not math.isclose(
        float(value["sum_squares"]),
        expected_sum_squares,
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        _fail(f"{label} distribution squared totals are inconsistent")
    variance = m2 / count
    if not math.isclose(
        float(value["population_stddev"]), math.sqrt(variance), rel_tol=1e-9, abs_tol=1e-9
    ):
        _fail(f"{label} distribution standard deviation is inconsistent")
    return value


def _validate_ingress(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _INGRESS_KEYS:
        _fail(f"{label} ingress schema drift")
    counts = []
    for field in ("count", "completed", "dropped", "censored"):
        item = value.get(field)
        if type(item) is not int or item < 0:
            _fail(f"{label}.{field} must be a non-negative integer")
        counts.append(item)
    total, completed, dropped, censored = counts
    if completed + dropped + censored != total:
        _fail(f"{label} ingress terminal counts do not close")
    for field, numerator in (
        ("completed_rate_percent", completed),
        ("drop_rate_percent", dropped),
        ("censored_rate_percent", censored),
    ):
        expected = _percentage(numerator, total)
        actual = value.get(field)
        if expected is None:
            if actual is not None:
                _fail(f"{label}.{field} must be null for an empty ingress cohort")
        elif not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            _fail(f"{label}.{field} is inconsistent with counts")
    return value


def _validate_performance(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PERFORMANCE_KEYS:
        _fail(f"{label} performance schema drift")
    ingress = _validate_ingress(value["ingress"], label=label)
    latency = _validate_distribution(value["completed_latency_ms"], label=f"{label}.latency")
    if latency["count"] != ingress["completed"]:
        _fail(f"{label} completed latency count differs from ingress completion count")
    deadlines = value.get("deadline_outcomes")
    if type(deadlines) is not list or not deadlines:
        _fail(f"{label} deadline outcomes are missing")
    previous = -math.inf
    previous_violations = latency["count"]
    for index, outcome in enumerate(deadlines):
        if type(outcome) is not dict or set(outcome) != {
            "deadline_ms", "violations", "rate_percent"
        }:
            _fail(f"{label} deadline outcome schema drift")
        deadline = float(_number(outcome["deadline_ms"], label=f"{label}.deadline_ms"))
        if deadline <= previous:
            _fail(f"{label} deadlines must be strictly sorted")
        previous = deadline
        violations = outcome.get("violations")
        if type(violations) is not int or violations < 0 or violations > latency["count"]:
            _fail(f"{label} deadline violation count is invalid")
        if violations > previous_violations:
            _fail(f"{label} deadline violations are not monotone")
        previous_violations = violations
        if latency["count"] > 0:
            if float(latency["maximum"]) <= deadline and violations != 0:
                _fail(f"{label} deadline violations contradict the latency maximum")
            if float(latency["minimum"]) > deadline and violations != latency["count"]:
                _fail(f"{label} deadline violations contradict the latency minimum")
        expected = _percentage(violations, latency["count"])
        actual = outcome.get("rate_percent")
        if expected is None:
            if actual is not None:
                _fail(f"{label} empty deadline rate must be null")
        elif not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            _fail(f"{label} deadline rate is inconsistent with counts")
    throughput = _number(
        value.get("throughput_completed_fps"), label=f"{label}.throughput"
    )
    if float(throughput) < 0.0:
        _fail(f"{label} throughput must be non-negative")
    return value


def _validate_frequency_statistics(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _POLICY_STAT_KEYS:
        _fail(f"{label} policy statistics schema drift")
    row_count = value.get("row_count")
    if type(row_count) is not int or row_count < 0:
        _fail(f"{label} policy row_count is invalid")
    for field in _POLICY_STAT_KEYS - {"row_count"}:
        rows = value[field]
        if type(rows) is not list:
            _fail(f"{label}.{field} must be a list")
        observed = []
        for row in rows:
            if type(row) is not dict or set(row) != {"value", "count"}:
                _fail(f"{label}.{field} frequency row schema drift")
            if type(row["value"]) is not str or type(row["count"]) is not int or row["count"] < 1:
                _fail(f"{label}.{field} frequency row is invalid")
            observed.append(row["value"])
        if observed != sorted(observed) or len(observed) != len(set(observed)):
            _fail(f"{label}.{field} frequencies are not unique and sorted")
        total = sum(row["count"] for row in rows)
        if total not in {0, row_count}:
            _fail(f"{label}.{field} frequencies do not close to row_count")
    return value


def _validate_drop_statistics(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DROP_STAT_KEYS:
        _fail(f"{label} drop statistics schema drift")
    for field in ("row_count", "dropped_frames", "late_frames", "total_frames"):
        if type(value.get(field)) is not int or value[field] < 0:
            _fail(f"{label}.{field} is invalid")
    if value["dropped_frames"] > value["total_frames"]:
        _fail(f"{label}.dropped_frames exceeds total_frames")
    if value["late_frames"] > value["total_frames"]:
        _fail(f"{label}.late_frames exceeds total_frames")
    for field, numerator in (
        ("drop_rate_percent", value["dropped_frames"]),
        ("late_rate_percent", value["late_frames"]),
    ):
        expected = _percentage(numerator, value["total_frames"])
        actual = value.get(field)
        if expected is None:
            if actual is not None:
                _fail(f"{label}.{field} must be null without total frames")
        elif not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(
            float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
        ):
            _fail(f"{label}.{field} is inconsistent")
    return value


def _validate_stage_statistics(value: Any, *, label: str) -> list[dict[str, Any]]:
    if type(value) is not list:
        _fail(f"{label} stage statistics must be a list")
    keys = []
    for row in value:
        if type(row) is not dict or set(row) != _STAGE_STAT_KEYS:
            _fail(f"{label} stage statistics schema drift")
        key = tuple(row[field] for field in ("stage", "base_stage", "role", "resource"))
        if any(type(item) is not str or not item for item in key):
            _fail(f"{label} stage statistics identity is invalid")
        if row["base_stage"] != stage_base_name(row["stage"]):
            _fail(f"{label} base stage identity drift")
        count = row["event_count"]
        if type(count) is not int or count < 1:
            _fail(f"{label} stage event_count is invalid")
        for field in ("stage_duration_ms", "queue_wait_ms"):
            distribution = _validate_distribution(
                row[field], label=f"{label}.{'.'.join(key)}.{field}"
            )
            if distribution["count"] != count:
                _fail(f"{label} stage distribution count drift")
            if float(distribution["minimum"]) < 0.0:
                _fail(f"{label} stage duration must be non-negative")
        keys.append(key)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _fail(f"{label} stage statistic rows are not unique and sorted")
    return value


def _validate_resource_statistics(value: Any, *, label: str) -> list[dict[str, Any]]:
    if type(value) is not list:
        _fail(f"{label} resource statistics must be a list")
    keys = []
    for row in value:
        if type(row) is not dict or set(row) != _RESOURCE_STAT_KEYS:
            _fail(f"{label} resource statistics schema drift")
        key = tuple(row[field] for field in ("stage", "base_stage", "resource"))
        if any(type(item) is not str or not item for item in key):
            _fail(f"{label} resource statistics identity is invalid")
        if row["base_stage"] != stage_base_name(row["stage"]):
            _fail(f"{label} resource base stage identity drift")
        count = row["event_count"]
        if type(count) is not int or count < 1:
            _fail(f"{label} resource event_count is invalid")
        numeric = row["numeric"]
        if type(numeric) is not dict or set(numeric) != _RESOURCE_NUMERIC_KEYS:
            _fail(f"{label} resource numeric schema drift")
        for field in sorted(_RESOURCE_NUMERIC_KEYS):
            distribution = _validate_distribution(
                numeric[field], label=f"{label}.{'.'.join(key)}.{field}"
            )
            if distribution["count"] != count:
                _fail(f"{label} resource distribution count drift")
            if float(distribution["minimum"]) < 0.0:
                _fail(f"{label} resource statistic must be non-negative")
        keys.append(key)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _fail(f"{label} resource statistic rows are not unique and sorted")
    return value


def _validate_full_resource_statistics(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _FULL_RESOURCE_STAT_KEYS:
        _fail(f"{label} full-resource statistics schema drift")
    summary = value["summary"]
    if type(summary) is not dict or set(summary) != _FULL_RESOURCE_SUMMARY_KEYS:
        _fail(f"{label} full-resource summary schema drift")
    if (
        summary["assessment_schema_version"] != 1
        or summary["resource_contract_version"] != 2
        or summary["evidence_accepted"] is not True
        or summary["publication_bundle_bound"] is not True
        or summary["full_resource_coverage_complete"] is not True
    ):
        _fail(f"{label} full-resource summary is not accepted")
    for field in (
        "measurement_window_start_ns",
        "measurement_window_end_ns",
        "nvdec_busy_equivalent_ns",
        "fanout_thread_cpu_time_ns",
        "fanout_work_units",
    ):
        if type(summary[field]) is not int or summary[field] < 0:
            _fail(f"{label} full-resource summary {field} is invalid")
    if summary["measurement_window_end_ns"] <= summary["measurement_window_start_ns"]:
        _fail(f"{label} full-resource measurement window is invalid")
    if summary["nvdec_busy_equivalent_ns"] <= 0:
        _fail(f"{label} full-resource NVDEC evidence is empty")
    for field in ("nvdec_interval_device_ids", "nvdec_sampled_gpu_device_ids"):
        identifiers = summary[field]
        if (
            type(identifiers) is not list
            or not identifiers
            or any(type(item) is not str or not item for item in identifiers)
            or identifiers != sorted(identifiers)
            or len(identifiers) != len(set(identifiers))
        ):
            _fail(f"{label} full-resource {field} is invalid")
    if (
        type(summary["nvdec_counter_scope"]) is not str
        or not summary["nvdec_counter_scope"]
        or summary["fanout_counter_scope"] != "per_trace_resource_work"
        or type(summary["resource_interval_summary"]) is not dict
    ):
        _fail(f"{label} full-resource provenance is invalid")
    _canonical_bytes(summary["resource_interval_summary"])

    hardware = value["hardware_by_device"]
    if type(hardware) is not list:
        _fail(f"{label} hardware statistics must be a list")
    hardware_ids = []
    for row in hardware:
        if type(row) is not dict or set(row) != {
            "device_id",
            "sample_count",
            "sample_period_us",
            "nvdec_util_percent",
            "gpu_util_percent",
            "memory_util_percent",
            "vram_used_bytes",
        }:
            _fail(f"{label} hardware statistic schema drift")
        device_id = row["device_id"]
        count = row["sample_count"]
        if type(device_id) is not str or not device_id.startswith("gpu:"):
            _fail(f"{label} hardware device identity is invalid")
        if type(count) is not int or count < 1:
            _fail(f"{label} hardware sample_count is invalid")
        for field in (
            "sample_period_us",
            "nvdec_util_percent",
            "gpu_util_percent",
            "memory_util_percent",
            "vram_used_bytes",
        ):
            distribution = _validate_distribution(
                row[field], label=f"{label}.{device_id}.{field}"
            )
            if distribution["count"] != count or float(distribution["minimum"]) < 0.0:
                _fail(f"{label} hardware distribution drift")
            if field.endswith("_percent") and float(distribution["maximum"]) > 100.0:
                _fail(f"{label} hardware percentage exceeds 100")
        hardware_ids.append(device_id)
    if hardware_ids != sorted(hardware_ids) or len(hardware_ids) != len(set(hardware_ids)):
        _fail(f"{label} hardware rows are not unique and sorted")
    if not set(summary["nvdec_sampled_gpu_device_ids"]).issubset(hardware_ids):
        _fail(f"{label} sampled NVDEC GPU identity aggregate drift")

    intervals = value["interval_by_component"]
    if type(intervals) is not list:
        _fail(f"{label} interval statistics must be a list")
    interval_keys = []
    for row in intervals:
        if type(row) is not dict or set(row) != {
            "component", "direction", "device_id", "row_count", "duration_ns", "bytes"
        }:
            _fail(f"{label} interval statistic schema drift")
        key = tuple(row[field] for field in ("component", "direction", "device_id"))
        if any(type(item) is not str or not item for item in key):
            _fail(f"{label} interval identity is invalid")
        count = row["row_count"]
        if type(count) is not int or count < 1:
            _fail(f"{label} interval row_count is invalid")
        for field in ("duration_ns", "bytes"):
            distribution = _validate_distribution(
                row[field], label=f"{label}.{'.'.join(key)}.{field}"
            )
            if distribution["count"] != count or float(distribution["minimum"]) < 0.0:
                _fail(f"{label} interval distribution drift")
        interval_keys.append(key)
    if interval_keys != sorted(interval_keys) or len(interval_keys) != len(set(interval_keys)):
        _fail(f"{label} interval rows are not unique and sorted")
    observed_nvdec = sorted({
        row["device_id"]
        for row in intervals
        if row["component"] == "nvdec_submit_complete"
    })
    if observed_nvdec != summary["nvdec_interval_device_ids"]:
        _fail(f"{label} NVDEC interval identity aggregate drift")

    fanout = value["fanout"]
    if type(fanout) is not dict or set(fanout) != {
        "row_count", "thread_cpu_time_ns", "work_units"
    }:
        _fail(f"{label} fanout statistic schema drift")
    for field in fanout:
        if type(fanout[field]) is not int or fanout[field] < 0:
            _fail(f"{label} fanout statistic is invalid")
    if (
        fanout["thread_cpu_time_ns"] != summary["fanout_thread_cpu_time_ns"]
        or fanout["work_units"] != summary["fanout_work_units"]
    ):
        _fail(f"{label} fanout aggregate drift")
    return value


def _validate_distribution_stream_aggregate(
    aggregate: Mapping[str, Any],
    parts: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> None:
    for field in ("count", "sum", "sum_squares"):
        expected = sum(part[field] for part in parts)
        actual = aggregate[field]
        if isinstance(expected, float) or isinstance(actual, float):
            if not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9):
                _fail(f"{label} aggregate drift: {field}")
        elif actual != expected:
            _fail(f"{label} aggregate drift: {field}")
    nonempty = [part for part in parts if part["count"] > 0]
    if not nonempty:
        if aggregate["count"] != 0:
            _fail(f"{label} empty aggregate drift")
        return
    if aggregate["minimum"] != min(part["minimum"] for part in nonempty):
        _fail(f"{label} aggregate drift: minimum")
    if aggregate["maximum"] != max(part["maximum"] for part in nonempty):
        _fail(f"{label} aggregate drift: maximum")
    aggregate_mean = float(aggregate["mean"])
    expected_m2 = sum(
        float(part["sum_squared_deviations"])
        + int(part["count"]) * (float(part["mean"]) - aggregate_mean) ** 2
        for part in nonempty
    )
    if not math.isclose(
        float(aggregate["sum_squared_deviations"]),
        expected_m2,
        rel_tol=1e-10,
        abs_tol=1e-6,
    ):
        _fail(f"{label} aggregate drift: sum_squared_deviations")


def _validate_stage_stream_aggregate(
    arm_rows: Sequence[Mapping[str, Any]],
    stream_rows: Sequence[Sequence[Mapping[str, Any]]],
    *,
    label: str,
) -> None:
    key_fields = ("stage", "base_stage", "role", "resource")
    arm = {tuple(row[field] for field in key_fields): row for row in arm_rows}
    parts: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for rows in stream_rows:
        for row in rows:
            parts.setdefault(tuple(row[field] for field in key_fields), []).append(row)
    if set(arm) != set(parts):
        _fail(f"{label} per-stream stage identity aggregate drift")
    for key, aggregate in arm.items():
        rows = parts[key]
        if aggregate["event_count"] != sum(row["event_count"] for row in rows):
            _fail(f"{label} per-stream stage event_count aggregate drift")
        for field in ("stage_duration_ms", "queue_wait_ms"):
            _validate_distribution_stream_aggregate(
                aggregate[field],
                [row[field] for row in rows],
                label=f"{label}.stage.{'.'.join(str(item) for item in key)}.{field}",
            )


def _validate_resource_stream_aggregate(
    arm_rows: Sequence[Mapping[str, Any]],
    stream_rows: Sequence[Sequence[Mapping[str, Any]]],
    *,
    label: str,
) -> None:
    key_fields = ("stage", "base_stage", "resource")
    arm = {tuple(row[field] for field in key_fields): row for row in arm_rows}
    parts: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for rows in stream_rows:
        for row in rows:
            parts.setdefault(tuple(row[field] for field in key_fields), []).append(row)
    if set(arm) != set(parts):
        _fail(f"{label} per-stream resource identity aggregate drift")
    for key, aggregate in arm.items():
        rows = parts[key]
        if aggregate["event_count"] != sum(row["event_count"] for row in rows):
            _fail(f"{label} per-stream resource event_count aggregate drift")
        for field in sorted(_RESOURCE_NUMERIC_KEYS):
            _validate_distribution_stream_aggregate(
                aggregate["numeric"][field],
                [row["numeric"][field] for row in rows],
                label=f"{label}.resource.{'.'.join(str(item) for item in key)}.{field}",
            )


def _validate_frequency_stream_aggregate(
    aggregate: Mapping[str, Any],
    parts: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> None:
    if aggregate["row_count"] != sum(part["row_count"] for part in parts):
        _fail(f"{label} row_count aggregate drift")
    for field in _POLICY_STAT_KEYS - {"row_count"}:
        expected: dict[str, int] = {}
        for part in parts:
            for row in part[field]:
                expected[row["value"]] = expected.get(row["value"], 0) + row["count"]
        actual = {row["value"]: row["count"] for row in aggregate[field]}
        if actual != expected:
            _fail(f"{label}.{field} aggregate drift")


def _validate_drop_stream_aggregate(
    aggregate: Mapping[str, Any],
    parts: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> None:
    for field in ("row_count", "dropped_frames", "late_frames", "total_frames"):
        if aggregate[field] != sum(part[field] for part in parts):
            _fail(f"{label}.{field} aggregate drift")


def _validate_measurement_passport(
    value: Any,
    *,
    ingress_count: int,
    completed_count: int,
    duration_ms: float,
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _MEASUREMENT_PASSPORT_KEYS:
        _fail(f"{label} measurement passport schema drift")
    if value["resource_attribution_complete"] is not True:
        _fail(f"{label} measurement passport attribution is incomplete")
    if type(value["resource_attribution"]) is not str or not value["resource_attribution"]:
        _fail(f"{label} measurement passport attribution identity is invalid")
    if value["resource_attributed_ingress_count"] != ingress_count:
        _fail(f"{label} measurement passport ingress coverage drift")
    if value["resource_unattributed_event_count"] != 0:
        _fail(f"{label} measurement passport has unattributed resource events")
    for field in (
        "input_schedule_sha256",
        "input_frame_key_sequence_sha256",
        "measurement_signature",
    ):
        if type(value[field]) is not str or _SHA256_RE.fullmatch(value[field]) is None:
            _fail(f"{label} measurement passport {field} is invalid")
    if not math.isclose(
        float(_number(value["measurement_window_duration_ms"], label=f"{label}.passport.duration")),
        duration_ms,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        _fail(f"{label} measurement passport duration drift")
    signature_json = value["measurement_signature_payload_json"]
    if type(signature_json) is not str:
        _fail(f"{label} measurement signature payload is invalid")
    try:
        signature_payload = json.loads(signature_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        _fail(f"{label} measurement signature payload is invalid JSON")
    if signature_json != json.dumps(
        signature_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ):
        _fail(f"{label} measurement signature payload is not canonical JSON")
    if hashlib.sha256(signature_json.encode("utf-8")).hexdigest() != value["measurement_signature"]:
        _fail(f"{label} measurement signature drift")
    numeric_fields = (
        "c_obs_total_ms",
        "c_obs_cpu_total_ms",
        "c_obs_gpu_total_ms",
        "c_obs_in_ms_per_ingress",
        "c_obs_cpu_in_ms_per_ingress",
        "c_obs_gpu_in_ms_per_ingress",
    )
    for field in numeric_fields:
        if float(_number(value[field], label=f"{label}.passport.{field}")) < 0.0:
            _fail(f"{label} measurement passport {field} is negative")
    if completed_count > 0:
        if float(_number(
            value["c_obs_comp_ms_per_completed"],
            label=f"{label}.passport.c_obs_comp_ms_per_completed",
        )) < 0.0:
            _fail(f"{label} completed resource cost is negative")
    elif value["c_obs_comp_ms_per_completed"] is not None:
        _fail(f"{label} completed resource cost must be null without completions")
    if type(value["c_obs_is_partial"]) is not bool:
        _fail(f"{label} c_obs_is_partial is invalid")
    total = float(value["c_obs_total_ms"])
    cpu = float(value["c_obs_cpu_total_ms"])
    gpu = float(value["c_obs_gpu_total_ms"])
    if not math.isclose(total, cpu + gpu, rel_tol=1e-9, abs_tol=2e-6):
        _fail(f"{label} measurement passport CPU/GPU resource totals drift")
    if ingress_count <= 0:
        _fail(f"{label} measurement passport requires positive ingress")
    for total_field, per_ingress_field in (
        ("c_obs_total_ms", "c_obs_in_ms_per_ingress"),
        ("c_obs_cpu_total_ms", "c_obs_cpu_in_ms_per_ingress"),
        ("c_obs_gpu_total_ms", "c_obs_gpu_in_ms_per_ingress"),
    ):
        if not math.isclose(
            float(value[per_ingress_field]),
            float(value[total_field]) / ingress_count,
            rel_tol=1e-8,
            abs_tol=1e-6,
        ):
            _fail(f"{label} measurement passport per-ingress resource cost drift")
    if completed_count > 0 and not math.isclose(
        float(value["c_obs_comp_ms_per_completed"]),
        total / completed_count,
        rel_tol=1e-8,
        abs_tol=1e-6,
    ):
        _fail(f"{label} measurement passport per-completion resource cost drift")
    return value


def _validate_descriptive(value: Any, *, streams: int, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTIVE_KEYS:
        _fail(f"{label} descriptive statistics schema drift")
    duration = float(
        _number(
            value["measurement_window_duration_ms"],
            label=f"{label}.measurement_window_duration_ms",
        )
    )
    if duration <= 0.0:
        _fail(f"{label} measurement window must be positive")
    arm_performance = _validate_performance(value["arm_performance"], label=f"{label}.arm")
    per_stream = value.get("per_stream")
    if type(per_stream) is not list or len(per_stream) != streams:
        _fail(f"{label} per-stream statistics do not cover the frozen stream count")
    expected_ids = list(range(streams))
    if [row.get("stream_id") for row in per_stream if type(row) is dict] != expected_ids:
        _fail(f"{label} per-stream identifiers must be contiguous and sorted")
    checked_streams = []
    stream_stage_statistics = []
    stream_resource_statistics = []
    stream_policy_statistics = []
    stream_drop_statistics = []
    for row in per_stream:
        if type(row) is not dict or set(row) != {
            "stream_id",
            "performance",
            "stage_statistics",
            "resource_statistics",
            "policy_decision_statistics",
            "drop_counter_statistics",
        }:
            _fail(f"{label} per-stream row schema drift")
        checked_streams.append(
            _validate_performance(
                row["performance"], label=f"{label}.stream-{row['stream_id']}"
            )
        )
        stream_stage_statistics.append(
            _validate_stage_statistics(
                row["stage_statistics"], label=f"{label}.stream-stage"
            )
        )
        stream_resource_statistics.append(
            _validate_resource_statistics(
                row["resource_statistics"], label=f"{label}.stream-resource"
            )
        )
        stream_policy_statistics.append(_validate_frequency_statistics(
            row["policy_decision_statistics"], label=f"{label}.stream-policy"
        ))
        stream_drop_statistics.append(_validate_drop_statistics(
            row["drop_counter_statistics"], label=f"{label}.stream-drop"
        ))
    for scope, performance in [("arm", arm_performance), *(
        (f"stream-{index}", row) for index, row in enumerate(checked_streams)
    )]:
        expected_throughput = (
            float(performance["completed_latency_ms"]["count"])
            / (duration / 1000.0)
        )
        if not math.isclose(
            float(performance["throughput_completed_fps"]),
            expected_throughput,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            _fail(f"{label}.{scope} throughput is inconsistent with the measurement window")
    aggregate_ingress = arm_performance["ingress"]
    for field in ("count", "completed", "dropped", "censored"):
        if aggregate_ingress[field] != sum(
            row["ingress"][field] for row in checked_streams
        ):
            _fail(f"{label} per-stream ingress aggregate drift: {field}")
    aggregate_latency = arm_performance["completed_latency_ms"]
    for field in ("count", "sum", "sum_squares"):
        actual = aggregate_latency[field]
        expected = sum(row["completed_latency_ms"][field] for row in checked_streams)
        if isinstance(actual, float) or isinstance(expected, float):
            if not math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-9):
                _fail(f"{label} per-stream latency aggregate drift: {field}")
        elif actual != expected:
            _fail(f"{label} per-stream latency aggregate drift: {field}")
    aggregate_mean = float(aggregate_latency["mean"] or 0.0)
    merged_m2 = sum(
        float(row["completed_latency_ms"]["sum_squared_deviations"])
        + int(row["completed_latency_ms"]["count"])
        * (float(row["completed_latency_ms"]["mean"] or 0.0) - aggregate_mean) ** 2
        for row in checked_streams
    )
    if not math.isclose(
        float(aggregate_latency["sum_squared_deviations"]),
        merged_m2,
        rel_tol=1e-10,
        abs_tol=1e-6,
    ):
        _fail(f"{label} per-stream latency aggregate drift: sum_squared_deviations")
    nonempty_latencies = [
        row["completed_latency_ms"]
        for row in checked_streams
        if row["completed_latency_ms"]["count"] > 0
    ]
    if nonempty_latencies:
        if aggregate_latency["minimum"] != min(
            row["minimum"] for row in nonempty_latencies
        ) or aggregate_latency["maximum"] != max(
            row["maximum"] for row in nonempty_latencies
        ):
            _fail(f"{label} per-stream latency range aggregate drift")
    elif aggregate_latency["count"] != 0:
        _fail(f"{label} empty per-stream latency aggregate drift")
    if not math.isclose(
        float(arm_performance["throughput_completed_fps"]),
        sum(float(row["throughput_completed_fps"]) for row in checked_streams),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        _fail(f"{label} per-stream throughput aggregate drift")
    for outcome_index, arm_outcome in enumerate(arm_performance["deadline_outcomes"]):
        if any(
            len(row["deadline_outcomes"])
            != len(arm_performance["deadline_outcomes"])
            for row in checked_streams
        ):
            _fail(f"{label} per-stream deadline grid length drift")
        if any(
            row["deadline_outcomes"][outcome_index]["deadline_ms"]
            != arm_outcome["deadline_ms"]
            for row in checked_streams
        ):
            _fail(f"{label} per-stream deadline grid drift")
        if arm_outcome["violations"] != sum(
            row["deadline_outcomes"][outcome_index]["violations"]
            for row in checked_streams
        ):
            _fail(f"{label} per-stream deadline violation aggregate drift")
    arm_stages = _validate_stage_statistics(
        value["stage_statistics"], label=f"{label}.stage"
    )
    arm_resources = _validate_resource_statistics(
        value["resource_statistics"], label=f"{label}.resource"
    )
    arm_policy = _validate_frequency_statistics(
        value["policy_decision_statistics"], label=f"{label}.policy"
    )
    arm_drops = _validate_drop_statistics(
        value["drop_counter_statistics"], label=f"{label}.drop"
    )
    _validate_stage_stream_aggregate(
        arm_stages, stream_stage_statistics, label=label
    )
    _validate_resource_stream_aggregate(
        arm_resources, stream_resource_statistics, label=label
    )
    _validate_frequency_stream_aggregate(
        arm_policy, stream_policy_statistics, label=f"{label}.policy"
    )
    _validate_drop_stream_aggregate(
        arm_drops, stream_drop_statistics, label=f"{label}.drop"
    )
    _validate_measurement_passport(
        value["measurement_passport"],
        ingress_count=arm_performance["ingress"]["count"],
        completed_count=arm_performance["ingress"]["completed"],
        duration_ms=duration,
        label=label,
    )
    _validate_full_resource_statistics(
        value["full_resource_statistics"], label=label
    )
    return value


def _validate_pair_identity(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PAIR_IDENTITY_KEYS:
        _fail("article-statistics pair identity schema drift")
    for field in ("matrix_sha256", "pair_sha256"):
        if type(value[field]) is not str or _SHA256_RE.fullmatch(value[field]) is None:
            _fail(f"article-statistics pair {field} is invalid")
    for field in ("run_id", "pair_id"):
        if type(value[field]) is not str or _IDENTIFIER_RE.fullmatch(value[field]) is None:
            _fail(f"article-statistics pair {field} is invalid")
    for field, minimum in (("pair_sequence", 0), ("attempt", 1)):
        if type(value[field]) is not int or value[field] < minimum:
            _fail(f"article-statistics pair {field} is invalid")
    return value


def _validate_evidence_files(
    value: Any, *, arm_id: str, position: int, policy: str, label: str
) -> list[dict[str, Any]]:
    if type(value) is not list:
        _fail(f"{label} evidence descriptor set is invalid")
    expected_names = set(accepted_arm_evidence_files(policy, full_resource=True)) | {
        "checkpoint_publication_acceptance.json",
        "run_metadata.json",
    }
    expected_prefix = f"arms/{position:02d}_{arm_id}/"
    names = []
    previous = ""
    for descriptor in value:
        if type(descriptor) is not dict or set(descriptor) != {
            "relative_path", "size_bytes", "sha256"
        }:
            _fail(f"{label} evidence descriptor schema drift")
        relative = descriptor["relative_path"]
        if (
            type(relative) is not str
            or not relative.startswith(expected_prefix)
            or Path(relative).as_posix() != relative
            or len(Path(relative).parts) != 3
        ):
            _fail(f"{label} raw evidence descriptor path is invalid")
        if relative <= previous:
            _fail(f"{label} evidence descriptors are not strictly sorted")
        previous = relative
        name = Path(relative).name
        names.append(name)
        if type(descriptor["size_bytes"]) is not int or descriptor["size_bytes"] < 0:
            _fail(f"{label} evidence descriptor size is invalid")
        if type(descriptor["sha256"]) is not str or _SHA256_RE.fullmatch(descriptor["sha256"]) is None:
            _fail(f"{label} evidence descriptor SHA-256 is invalid")
    if set(names) != expected_names or len(names) != len(expected_names):
        _fail(f"{label} evidence descriptor set does not match accepted-arm evidence")
    return value


def _primary_pair_material(arms: Sequence[Mapping[str, Any]], pair_metric: Any) -> dict[str, Any]:
    return {
        "arms": [
            {
                "arm_index": arm["arm_index"],
                "arm_id": arm["arm_id"],
                "descriptive_statistics": arm["descriptive_statistics"],
                "primary_architecture_run_metric": arm["primary_architecture_run_metric"],
            }
            for arm in arms
        ],
        "primary_architecture_pair_metric": pair_metric,
    }


def build_article_statistics_pair_record_v1(
    *,
    pair_identity: Mapping[str, Any],
    arms: Sequence[Mapping[str, Any]],
    primary_architecture_pair_metric: Mapping[str, Any] | None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_arms = _json_value(copy.deepcopy(list(arms)))
    if type(normalized_arms) is not list:
        _fail("article-statistics arms are invalid")
    for arm in normalized_arms:
        if type(arm) is not dict:
            _fail("article-statistics arm is invalid")
        arm["evidence_aggregate_sha256"] = _canonical_sha(arm.get("evidence_files"))
    pair = _json_value(copy.deepcopy(dict(pair_identity)))
    pair_metric = _json_value(copy.deepcopy(primary_architecture_pair_metric))
    evidence_material = [
        {
            "arm_index": arm.get("arm_index"),
            "arm_id": arm.get("arm_id"),
            "evidence_files": arm.get("evidence_files"),
        }
        for arm in normalized_arms
    ]
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": STATUS,
        "pair": pair,
        "arms": normalized_arms,
        "primary_architecture_pair_metric": pair_metric,
        "evidence_aggregate_sha256": _canonical_sha(evidence_material),
        "statistics_aggregate_sha256": _canonical_sha(
            _primary_pair_material(normalized_arms, pair_metric)
        ),
    }
    record["record_identity_sha256"] = _canonical_sha(record)
    return validate_article_statistics_pair_record_v1(record, config=config)


def _recompute_primary_pair_metric(
    arms: Sequence[Mapping[str, Any]], config: Mapping[str, Any]
) -> dict[str, Any] | None:
    metrics = [arm.get("primary_architecture_run_metric") for arm in arms]
    if metrics == [None, None]:
        return None
    if any(type(metric) is not dict for metric in metrics):
        _fail("primary architecture statistics must cover both paired arms")
    from generate_vast_report_artifacts import build_primary_architecture_pairs_from_run_metrics

    pairs = build_primary_architecture_pairs_from_run_metrics(
        pd.DataFrame(metrics), dict(config)
    )
    repeat = int(metrics[0]["repeat"])
    selected = pairs[pd.to_numeric(pairs["repeat"], errors="raise") == repeat]
    if len(selected) != 1:
        _fail("primary architecture pair statistics are not unique")
    row = _json_value(selected.iloc[0].to_dict())
    if row.get("pair_complete") is not True or row.get("pair_gate_pass") is not True:
        _fail(
            "primary architecture pair statistics failed: "
            + str(row.get("pair_blockers", ""))
        )
    return row


def validate_article_statistics_pair_record_v1(
    value: Any, *, config: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "artifact_kind",
        "status",
        "pair",
        "arms",
        "primary_architecture_pair_metric",
        "evidence_aggregate_sha256",
        "statistics_aggregate_sha256",
        "record_identity_sha256",
    }:
        _fail("article-statistics record schema drift")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != ARTIFACT_KIND
        or value.get("status") != STATUS
    ):
        _fail("article-statistics record identity drift")
    _validate_pair_identity(value["pair"])
    arms = value.get("arms")
    if type(arms) is not list or len(arms) != 2:
        _fail("article-statistics record must contain exactly two arms")
    if [arm.get("arm_index") for arm in arms if type(arm) is dict] != [0, 1]:
        _fail("article-statistics arms must be ordered by arm_index")
    arm_ids = []
    for arm in arms:
        if type(arm) is not dict or set(arm) != {
            "arm_index",
            "arm_id",
            "coordinate",
            "evidence_files",
            "evidence_aggregate_sha256",
            "descriptive_statistics",
            "primary_architecture_run_metric",
        }:
            _fail("article-statistics arm schema drift")
        arm_id = arm.get("arm_id")
        if type(arm_id) is not str or _IDENTIFIER_RE.fullmatch(arm_id) is None:
            _fail("article-statistics arm_id is invalid")
        arm_ids.append(arm_id)
        coordinate = arm.get("coordinate")
        if type(coordinate) is not dict or set(coordinate) != _COORDINATE_KEYS:
            _fail("article-statistics arm coordinate schema drift")
        for field in (
            "arm_position", "repeat", "streams", "seed", "warmup_s", "measurement_s", "run_seed"
        ):
            minimum = 1 if field in {"arm_position", "repeat", "streams", "measurement_s"} else 0
            if type(coordinate[field]) is not int or coordinate[field] < minimum:
                _fail(f"article-statistics arm coordinate {field} is invalid")
        if coordinate["arm_position"] != arm["arm_index"] + 1:
            _fail("article-statistics arm position/index drift")
        for field in (
            "system", "scenario", "codec", "dataset", "policy", "deployment_mode",
            "host_topology", "run_mode", "telemetry_source",
        ):
            if type(coordinate[field]) is not str or not coordinate[field]:
                _fail(f"article-statistics arm coordinate {field} is invalid")
        _number(coordinate["deadline_ms"], label="article-statistics deadline_ms")
        evidence = _validate_evidence_files(
            arm["evidence_files"],
            arm_id=arm_id,
            position=coordinate["arm_position"],
            policy=coordinate["policy"],
            label=arm_id,
        )
        if arm.get("evidence_aggregate_sha256") != _canonical_sha(evidence):
            _fail("article-statistics arm evidence aggregate drift")
        _validate_descriptive(
            arm["descriptive_statistics"], streams=coordinate["streams"], label=arm_id
        )
        if config is not None:
            from generate_vast_report_artifacts import report_deadlines_ms

            expected_deadlines = sorted(
                set(report_deadlines_ms(dict(config)))
                | {float(coordinate["deadline_ms"])}
            )
            observed_deadlines = [
                float(row["deadline_ms"])
                for row in arm["descriptive_statistics"]["arm_performance"][
                    "deadline_outcomes"
                ]
            ]
            if observed_deadlines != expected_deadlines:
                _fail("article-statistics descriptive deadline grid drift")
        primary_metric = arm.get("primary_architecture_run_metric")
        if primary_metric is not None:
            if type(primary_metric) is not dict or primary_metric.get("run_gate_pass") is not True:
                _fail("primary architecture run metric is not accepted")
            for field in (
                "system",
                "scenario",
                "policy",
                "dataset",
                "repeat",
                "streams",
                "seed",
                "run_seed",
            ):
                if primary_metric.get(field) != coordinate[field]:
                    _fail(f"primary architecture run metric coordinate drift: {field}")
            if primary_metric.get("pair_repeat") != coordinate["repeat"]:
                _fail("primary architecture pair repeat drift")
            if primary_metric.get("pair_arm_position") != coordinate["arm_position"]:
                _fail("primary architecture pair arm position drift")
            if not math.isclose(
                float(primary_metric.get("deadline_ms", math.nan)),
                float(coordinate["deadline_ms"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                _fail("primary architecture run metric deadline drift")
            deadlines = arm["descriptive_statistics"]["arm_performance"]["deadline_outcomes"]
            deadline_index = {
                float(row["deadline_ms"]): index for index, row in enumerate(deadlines)
            }
            current = deadline_index.get(float(coordinate["deadline_ms"]))
            if current is None:
                _fail("primary architecture deadline is absent from descriptive statistics")
            per_stream = arm["descriptive_statistics"]["per_stream"]
            vmax = max(
                float(row["performance"]["deadline_outcomes"][current]["rate_percent"])
                for row in per_stream
            )
            drop_max = max(
                float(row["performance"]["ingress"]["drop_rate_percent"])
                for row in per_stream
            )
            arm_performance = arm["descriptive_statistics"]["arm_performance"]
            ingress = arm_performance["ingress"]
            for metric_field, ingress_field in (
                ("ingress_frame_count", "count"),
                ("completed_frame_count", "completed"),
                ("dropped_frame_count", "dropped"),
                ("censored_frame_count", "censored"),
            ):
                if primary_metric.get(metric_field) != ingress[ingress_field]:
                    _fail(
                        "primary architecture ingress statistic drift: "
                        + metric_field
                    )
            descriptive = arm["descriptive_statistics"]
            if not math.isclose(
                float(primary_metric.get("measurement_window_duration_ms", math.nan)),
                float(descriptive["measurement_window_duration_ms"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                _fail("primary architecture measurement window drift")
            passport = descriptive["measurement_passport"]
            for field in (
                "input_schedule_sha256",
                "input_frame_key_sequence_sha256",
                "resource_attribution",
                "measurement_signature",
                "c_obs_is_partial",
            ):
                if primary_metric.get(field) != passport.get(field):
                    _fail(f"primary architecture measurement passport drift: {field}")
            for field in (
                "c_obs_in_ms_per_ingress",
                "c_obs_cpu_in_ms_per_ingress",
                "c_obs_gpu_in_ms_per_ingress",
            ):
                if not math.isclose(
                    float(primary_metric.get(field, math.nan)),
                    float(passport[field]),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    _fail(f"primary architecture measurement passport drift: {field}")
            expected_run_dir = (
                Path("pairs")
                / f"{value['pair']['pair_sequence']:04d}_{value['pair']['pair_id']}"
                / f"attempt-{value['pair']['attempt']:04d}"
                / "arms"
                / f"{coordinate['arm_position']:02d}_{arm_id}"
            ).as_posix()
            if primary_metric.get("run_dir") != expected_run_dir:
                _fail("primary architecture run directory binding drift")
            if not math.isclose(
                vmax,
                float(primary_metric.get("vmax_completed_slo_violation_rate_percent", math.nan)),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                _fail("primary architecture per-stream SLO statistic drift")
            if not math.isclose(
                drop_max,
                float(primary_metric.get("drop_max_ingress_rate_percent", math.nan)),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                _fail("primary architecture per-stream drop statistic drift")
    if len(set(arm_ids)) != 2:
        _fail("article-statistics arm identifiers must be unique")
    evidence_material = [
        {
            "arm_index": arm["arm_index"],
            "arm_id": arm["arm_id"],
            "evidence_files": arm["evidence_files"],
        }
        for arm in arms
    ]
    if value.get("evidence_aggregate_sha256") != _canonical_sha(evidence_material):
        _fail("article-statistics evidence aggregate drift")
    if value.get("statistics_aggregate_sha256") != _canonical_sha(
        _primary_pair_material(arms, value.get("primary_architecture_pair_metric"))
    ):
        _fail("article-statistics statistics aggregate drift")
    metrics_present = [arm.get("primary_architecture_run_metric") is not None for arm in arms]
    if any(metrics_present) != all(metrics_present):
        _fail("primary architecture statistics must cover both paired arms")
    if all(metrics_present) != (value.get("primary_architecture_pair_metric") is not None):
        _fail("primary architecture pair metric coverage drift")
    if config is not None and all(metrics_present):
        expected_pair = _recompute_primary_pair_metric(arms, config)
        if _canonical_bytes(expected_pair) != _canonical_bytes(
            value["primary_architecture_pair_metric"]
        ):
            _fail("primary architecture pair metric differs from preregistered logic")
    observed_identity = value.get("record_identity_sha256")
    unsigned = dict(value)
    unsigned.pop("record_identity_sha256", None)
    if type(observed_identity) is not str or observed_identity != _canonical_sha(unsigned):
        _fail("article-statistics self hash drift")
    return copy.deepcopy(value)


def persist_article_statistics_pair_record_v1(
    record: Mapping[str, Any],
    *,
    run_root: Path,
    pair_dir: Path,
    after_physical_commit_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    checked = validate_article_statistics_pair_record_v1(record)
    root = Path(run_root).resolve()
    pair_path = Path(pair_dir).resolve()
    try:
        relative_pair = pair_path.relative_to(root)
    except ValueError:
        _fail("article-statistics pair directory must be inside run_root")
    pair = checked["pair"]
    expected_pair = (
        Path("pairs")
        / f"{pair['pair_sequence']:04d}_{pair['pair_id']}"
        / f"attempt-{pair['attempt']:04d}"
    )
    if relative_pair != expected_pair or _is_link_or_reparse(pair_path) or not pair_path.is_dir():
        _fail("article-statistics pair directory layout drift")
    attempt_path = pair_path / ATTEMPT_COPY_NAME
    retained_path = (
        root
        / "article_statistics"
        / "pairs"
        / (
            f"{pair['pair_sequence']:04d}_{pair['pair_id']}"
            f".attempt-{pair['attempt']:04d}.v1.json"
        )
    )
    payload = _canonical_bytes(checked) + b"\n"
    try:
        with PhysicalRootCustodyV1.open(
            root, label="article-statistics run_root"
        ) as custody:
            # Validate and pin both physical parent chains before either leaf
            # is written.  A child-created redirect therefore cannot cause a
            # partial commit into an external namespace.
            custody.ensure_directory(
                attempt_path.parent,
                label="article-statistics attempt parent",
            )
            custody.ensure_directory(
                retained_path.parent,
                label="article-statistics retained parent",
            )
            attempt_descriptor = _atomic_immutable_write(
                custody,
                attempt_path,
                payload,
                label="attempt article-statistics copy",
                after_publish_step=(
                    None
                    if after_physical_commit_step is None
                    else lambda step: after_physical_commit_step(f"attempt:{step}")
                ),
            )
            retained_descriptor = _atomic_immutable_write(
                custody,
                retained_path,
                payload,
                label="retained article-statistics copy",
                after_publish_step=(
                    None
                    if after_physical_commit_step is None
                    else lambda step: after_physical_commit_step(f"retained:{step}")
                ),
            )
    except PublicationPhysicalIoV1Error as error:
        raise ArticleStatisticsV1Error(
            f"article-statistics physical namespace rejected: {error}"
        ) from error
    binding = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "status": "physically_bound_article_statistics",
        "pair": copy.deepcopy(checked["pair"]),
        "arm_ids": [arm["arm_id"] for arm in checked["arms"]],
        "record_identity_sha256": checked["record_identity_sha256"],
        "evidence_aggregate_sha256": checked["evidence_aggregate_sha256"],
        "statistics_aggregate_sha256": checked["statistics_aggregate_sha256"],
        "attempt_copy": attempt_descriptor,
        "retained_copy": retained_descriptor,
    }
    return validate_article_statistics_binding_v1(
        binding,
        run_root=root,
        pair_dir=pair_path,
        require_attempt_copy=True,
        require_retained_copy=True,
        require_raw_evidence=True,
    )


def _read_bound_record(path: Path, descriptor: Mapping[str, Any], *, label: str) -> tuple[bytes, dict[str, Any]]:
    if _is_link_or_reparse(path) or not path.is_file():
        _fail(f"{label} is missing or not a regular file")
    payload = path.read_bytes()
    if (
        len(payload) != descriptor.get("size_bytes")
        or hashlib.sha256(payload).hexdigest() != descriptor.get("sha256")
    ):
        _fail(f"{label} descriptor drift")
    if not payload.endswith(b"\n"):
        _fail(f"{label} is not newline-terminated canonical JSON")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        _fail(f"{label} is invalid JSON")
    checked = validate_article_statistics_pair_record_v1(value)
    if payload != _canonical_bytes(checked) + b"\n":
        _fail(f"{label} is not canonical JSON")
    return payload, checked


def validate_article_statistics_binding_v1(
    value: Any,
    *,
    run_root: Path,
    pair_dir: Path,
    require_attempt_copy: bool,
    require_retained_copy: bool,
    require_raw_evidence: bool,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "artifact_kind",
        "status",
        "pair",
        "arm_ids",
        "record_identity_sha256",
        "evidence_aggregate_sha256",
        "statistics_aggregate_sha256",
        "attempt_copy",
        "retained_copy",
    }:
        _fail("article-statistics binding schema drift")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != BINDING_KIND
        or value.get("status") != "physically_bound_article_statistics"
    ):
        _fail("article-statistics binding identity drift")
    root = Path(run_root).resolve()
    pair_path = Path(pair_dir).resolve()
    expected_attempt = pair_path / ATTEMPT_COPY_NAME
    descriptors = {}
    for field, expected_path, required, label in (
        ("attempt_copy", expected_attempt, require_attempt_copy, "attempt article-statistics copy"),
        ("retained_copy", None, require_retained_copy, "retained article-statistics copy"),
    ):
        descriptor = value.get(field)
        if type(descriptor) is not dict or set(descriptor) != {
            "relative_path", "size_bytes", "sha256"
        }:
            _fail(f"{label} descriptor schema drift")
        relative = descriptor.get("relative_path")
        if type(relative) is not str or Path(relative).is_absolute() or Path(relative).as_posix() != relative:
            _fail(f"{label} relative path is invalid")
        path = root / relative
        if expected_path is not None and path != expected_path:
            _fail(f"{label} path drift")
        if field == "retained_copy":
            parts = Path(relative).parts
            if len(parts) != 3 or parts[:2] != ("article_statistics", "pairs"):
                _fail("retained article-statistics copy path drift")
        if type(descriptor.get("size_bytes")) is not int or descriptor["size_bytes"] < 1:
            _fail(f"{label} size is invalid")
        if type(descriptor.get("sha256")) is not str or _SHA256_RE.fullmatch(descriptor["sha256"]) is None:
            _fail(f"{label} SHA-256 is invalid")
        descriptors[field] = (descriptor, path, required, label)
    records: list[tuple[bytes, dict[str, Any]]] = []
    for descriptor, path, required, label in descriptors.values():
        if path.exists() or _is_link_or_reparse(path):
            records.append(_read_bound_record(path, descriptor, label=label))
        elif required:
            _fail(f"{label} is missing or not a regular file")
    if not records:
        _fail("no physical article-statistics copy is available")
    first_payload, checked = records[0]
    if any(payload != first_payload for payload, _ in records[1:]):
        _fail("article-statistics physical copies differ")
    for field in (
        "record_identity_sha256", "evidence_aggregate_sha256", "statistics_aggregate_sha256"
    ):
        if value.get(field) != checked.get(field):
            _fail(f"article-statistics binding {field} drift")
    if value.get("pair") != checked.get("pair"):
        _fail("article-statistics binding pair identity drift")
    if value.get("arm_ids") != [arm["arm_id"] for arm in checked["arms"]]:
        _fail("article-statistics binding arm identity drift")
    pair = checked["pair"]
    expected_pair = (
        root
        / "pairs"
        / f"{pair['pair_sequence']:04d}_{pair['pair_id']}"
        / f"attempt-{pair['attempt']:04d}"
    )
    if pair_path != expected_pair:
        _fail("article-statistics binding pair identity drift")
    retained_expected = (
        root
        / "article_statistics"
        / "pairs"
        / f"{pair['pair_sequence']:04d}_{pair['pair_id']}.attempt-{pair['attempt']:04d}.v1.json"
    )
    if descriptors["retained_copy"][1] != retained_expected:
        _fail("retained article-statistics copy path drift")
    if require_raw_evidence:
        for arm in checked["arms"]:
            for descriptor in arm["evidence_files"]:
                raw_path = pair_path / descriptor["relative_path"]
                observed = _stable_descriptor(raw_path, relative_to=pair_path)
                if observed != descriptor:
                    _fail(
                        "raw evidence descriptor drift: " + descriptor["relative_path"]
                    )
    return copy.deepcopy(value)


def _coordinate(expected_arm: Mapping[str, Any], result: Mapping[str, Any], arm_index: int) -> dict[str, Any]:
    coordinate = {
        "arm_position": expected_arm.get("arm_position"),
        "system": expected_arm.get("system"),
        "scenario": expected_arm.get("scenario"),
        "codec": expected_arm.get("codec"),
        "dataset": expected_arm.get("dataset"),
        "policy": expected_arm.get("policy"),
        "deadline_ms": expected_arm.get("deadline_ms"),
        "repeat": expected_arm.get("repeat"),
        "streams": expected_arm.get("streams"),
        "seed": expected_arm.get("seed"),
        "warmup_s": expected_arm.get("warmup_s"),
        "measurement_s": expected_arm.get("measurement_s"),
        "run_seed": result.get("run_seed"),
        "deployment_mode": result.get("deployment_mode"),
        "host_topology": result.get("host_topology"),
        "run_mode": result.get("run_mode"),
        "telemetry_source": result.get("telemetry_source"),
    }
    if coordinate["arm_position"] != arm_index + 1:
        _fail("article-statistics expected arm position drift")
    return _json_value(coordinate)


def _arm_evidence_descriptors(
    *, pair_dir: Path, arm_root: Path, coordinate: Mapping[str, Any], record: Mapping[str, Any]
) -> list[dict[str, Any]]:
    expected_root = pair_dir / "arms" / f"{coordinate['arm_position']:02d}_{record['arm_id']}"
    if arm_root.resolve() != expected_root.resolve():
        _fail("article-statistics arm evidence root layout drift")
    expected_hashes = dict(record["evidence_sha256"])
    hashes = {
        **expected_hashes,
        "checkpoint_publication_acceptance.json": record["runtime_acceptance_sha256"],
        "run_metadata.json": record["run_metadata_sha256"],
    }
    return sorted(
        (
            _stable_descriptor(
                arm_root / name,
                relative_to=pair_dir,
                expected_sha=str(expected_sha),
            )
            for name, expected_sha in hashes.items()
        ),
        key=lambda item: item["relative_path"],
    )


def _descriptive_from_evidence(
    evidence: Mapping[str, Any],
    *,
    coordinate: Mapping[str, Any],
    full_resource: Mapping[str, Any],
    deadlines_ms: Sequence[float],
) -> dict[str, Any]:
    frames = evidence["frames"].copy()
    events = evidence["events"].copy()
    sidecars = evidence["sidecars"]
    ingress = sidecars["ingress_ledger"].copy()
    resources = sidecars["resource_events"].copy()
    decisions = sidecars["policy_decisions"].copy()
    drops = sidecars["drop_counters"].copy()
    passport = summarize_measurement_passport(resources, ingress, events)
    measurement_window = float(passport["measurement_window_duration_ms"])
    stream_ids = list(range(int(coordinate["streams"])))
    observed_ingress = sorted(
        set(pd.to_numeric(ingress["stream_id"], errors="raise").astype(int))
    )
    if observed_ingress != stream_ids:
        _fail("article-statistics ingress does not cover every frozen stream")
    per_stream = []
    for stream_id in stream_ids:
        stream_frames = frames[
            pd.to_numeric(frames["stream_id"], errors="raise").astype(int) == stream_id
        ]
        stream_ingress = ingress[
            pd.to_numeric(ingress["stream_id"], errors="raise").astype(int) == stream_id
        ]
        stream_events = events[
            pd.to_numeric(events["stream_id"], errors="raise").astype(int) == stream_id
        ]
        stream_resources = resources[
            pd.to_numeric(resources["stream_id"], errors="raise").astype(int) == stream_id
        ]
        stream_decisions = decisions[
            pd.to_numeric(decisions["stream_id"], errors="raise").astype(int) == stream_id
        ]
        stream_drops = drops[
            pd.to_numeric(drops["stream_id"], errors="raise").astype(int) == stream_id
        ]
        per_stream.append(
            {
                "stream_id": stream_id,
                "performance": _performance_statistics(
                    stream_frames,
                    stream_ingress,
                    deadlines_ms=deadlines_ms,
                    measurement_window_duration_ms=measurement_window,
                ),
                "stage_statistics": _stage_statistics(stream_events),
                "resource_statistics": _resource_statistics(stream_resources),
                "policy_decision_statistics": _policy_statistics(stream_decisions),
                "drop_counter_statistics": _drop_statistics(stream_drops),
            }
        )
    return {
        "measurement_window_duration_ms": measurement_window,
        "arm_performance": _performance_statistics(
            frames,
            ingress,
            deadlines_ms=deadlines_ms,
            measurement_window_duration_ms=measurement_window,
        ),
        "per_stream": per_stream,
        "stage_statistics": _stage_statistics(events),
        "resource_statistics": _resource_statistics(resources),
        "policy_decision_statistics": _policy_statistics(decisions),
        "drop_counter_statistics": _drop_statistics(drops),
        "measurement_passport": _json_value(passport),
        "full_resource_statistics": _full_resource_statistics(full_resource),
    }


def _primary_arm_matches(coordinate: Mapping[str, Any], primary: Mapping[str, Any]) -> bool:
    return bool(
        coordinate["system"] == primary["system"]
        and coordinate["codec"] == primary["codec"]
        and coordinate["dataset"] == primary["dataset"]
        and coordinate["policy"] == primary["policy"]
        and coordinate["scenario"]
        in {primary["baseline_scenario"], primary["shared_scenario"]}
        and math.isclose(
            float(coordinate["deadline_ms"]),
            float(primary["deadline_ms"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and coordinate["streams"] == primary["streams"]
        and 1 <= coordinate["repeat"] <= primary["repeats"]
        and coordinate["seed"] == primary["seed"]
        and coordinate["warmup_s"] == primary["warmup_s"]
        and coordinate["measurement_s"] == primary["measurement_s"]
    )


def seal_pair_article_statistics_v1(
    *,
    run_root: Path,
    pair_dir: Path,
    config: Mapping[str, Any],
    pair: Mapping[str, Any],
    arm_records: Sequence[Mapping[str, Any]],
    matrix_sha256: str,
    run_id: str,
    pair_sequence: int,
    pair_id: str,
    pair_sha256: str,
    attempt: int,
) -> dict[str, Any]:
    if type(pair.get("arms")) is not list or len(pair["arms"]) != 2:
        _fail("article-statistics sealing requires exactly two frozen arms")
    if len(arm_records) != 2:
        _fail("article-statistics sealing requires exactly two accepted arm records")
    from benchmark_contract import validate_primary_architecture_contrast
    from generate_vast_report_artifacts import (
        _primary_run_metric,
        _validated_publication_run_artifacts,
        report_deadlines_ms,
    )

    config_copy = _json_value(copy.deepcopy(dict(config)))
    primary = validate_primary_architecture_contrast(config_copy)
    deadlines = sorted(
        set(report_deadlines_ms(config_copy))
        | {float(arm["deadline_ms"]) for arm in pair["arms"]}
    )
    materials = []
    primary_coverage = []
    for arm_index, (expected_arm, record) in enumerate(
        zip(pair["arms"], arm_records, strict=True)
    ):
        if record.get("arm_id") != expected_arm.get("arm_id"):
            _fail("article-statistics accepted arm identity drift")
        coordinate = _coordinate(expected_arm, record["result"], arm_index)
        acceptance_relative = record.get("runtime_acceptance_relative_path")
        if type(acceptance_relative) is not str:
            _fail("article-statistics arm acceptance path is invalid")
        arm_root = (Path(run_root).resolve() / acceptance_relative).parent
        before = _arm_evidence_descriptors(
            pair_dir=Path(pair_dir).resolve(),
            arm_root=arm_root,
            coordinate=coordinate,
            record=record,
        )
        row = pd.Series(copy.deepcopy(record["result"]))
        try:
            evidence = _validated_publication_run_artifacts(
                Path(run_root).resolve(),
                row,
                config_copy,
                validate_metadata=False,
                run_dir_override=arm_root,
            )
            scenario = config_copy["scenarios"][coordinate["scenario"]]
            topology_kind = str(scenario["topology"]["kind"])
            full_resource = validate_full_resource_evidence(
                arm_root,
                expected_run_id=str(record["run_id"]),
                ingress_ledger=evidence["sidecars"]["ingress_ledger"],
                topology_events=evidence["topology_events"],
                frame_events=evidence["events"],
                topology_kind=topology_kind,
            )
        except (
            ContractError,
            FullResourceContractError,
            ResourceIntervalContractError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise ArticleStatisticsV1Error(
                f"article-statistics semantic evidence validation failed: {error}"
            ) from error
        descriptive = _descriptive_from_evidence(
            evidence,
            coordinate=coordinate,
            full_resource=full_resource,
            deadlines_ms=deadlines,
        )
        primary_match = _primary_arm_matches(coordinate, primary)
        primary_coverage.append(primary_match)
        primary_metric = None
        if primary_match:
            primary_row = pd.Series(
                {
                    **copy.deepcopy(record["result"]),
                    **copy.deepcopy(evidence["raw_summary"]),
                }
            )
            try:
                primary_metric = _primary_run_metric(
                    Path(run_root).resolve(),
                    primary_row,
                    primary,
                    config_copy,
                    run_dir_override=arm_root,
                    validate_metadata=False,
                    primary_pair_metadata_override=copy.deepcopy(
                        expected_arm.get("primary_architecture_pair")
                    ),
                )
            except (ContractError, KeyError, TypeError, ValueError) as error:
                raise ArticleStatisticsV1Error(
                    "primary architecture statistics validation failed: "
                    + str(error)
                ) from error
            if primary_metric.get("run_gate_pass") is not True:
                _fail(
                    "primary architecture article-statistics gate failed: "
                    + str(primary_metric.get("run_gate_blockers", ""))
                )
        after = _arm_evidence_descriptors(
            pair_dir=Path(pair_dir).resolve(),
            arm_root=arm_root,
            coordinate=coordinate,
            record=record,
        )
        if before != after:
            _fail("article-statistics raw evidence changed while aggregating")
        materials.append(
            {
                "arm_index": arm_index,
                "arm_id": str(expected_arm["arm_id"]),
                "coordinate": coordinate,
                "evidence_files": after,
                "descriptive_statistics": descriptive,
                "primary_architecture_run_metric": primary_metric,
            }
        )
    if any(primary_coverage) != all(primary_coverage):
        _fail("primary architecture pair coverage is asymmetric")
    pair_metric = (
        _recompute_primary_pair_metric(materials, config_copy)
        if all(primary_coverage)
        else None
    )
    record = build_article_statistics_pair_record_v1(
        pair_identity={
            "matrix_sha256": matrix_sha256,
            "run_id": run_id,
            "pair_sequence": pair_sequence,
            "pair_id": pair_id,
            "pair_sha256": pair_sha256,
            "attempt": attempt,
        },
        arms=materials,
        primary_architecture_pair_metric=pair_metric,
        config=config_copy,
    )
    return persist_article_statistics_pair_record_v1(
        record,
        run_root=Path(run_root),
        pair_dir=Path(pair_dir),
    )


def load_article_statistics_record_v1(path: Path) -> dict[str, Any]:
    candidate = Path(path)
    if _is_link_or_reparse(candidate) or not candidate.is_file():
        _fail("article-statistics record must be a regular file")
    payload = candidate.read_bytes()
    if not payload.endswith(b"\n"):
        _fail("article-statistics record is not newline-terminated")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        _fail("article-statistics record is invalid JSON")
    checked = validate_article_statistics_pair_record_v1(value)
    if payload != _canonical_bytes(checked) + b"\n":
        _fail("article-statistics record is not canonical JSON")
    return checked


def build_primary_architecture_inference_from_article_records_v1(
    paths: Sequence[Path], *, config: Mapping[str, Any]
) -> dict[str, Any]:
    from benchmark_contract import validate_primary_architecture_contrast
    from generate_vast_report_artifacts import (
        build_primary_architecture_inference,
        evaluate_primary_architecture_claim_state,
    )

    config_copy = _json_value(copy.deepcopy(dict(config)))
    primary = validate_primary_architecture_contrast(config_copy)
    rows = []
    source_records = []
    for path in paths:
        record = validate_article_statistics_pair_record_v1(
            load_article_statistics_record_v1(Path(path)), config=config_copy
        )
        expected_pair = _recompute_primary_pair_metric(record["arms"], config_copy)
        stored_pair = record.get("primary_architecture_pair_metric")
        if expected_pair is None:
            if stored_pair is not None:
                _fail("non-primary article-statistics record contains a primary pair")
            continue
        if _canonical_bytes(expected_pair) != _canonical_bytes(stored_pair):
            _fail("stored primary pair differs from preregistered inference input")
        rows.append(stored_pair)
        source_records.append(
            {
                "pair_sequence": record["pair"]["pair_sequence"],
                "pair_id": record["pair"]["pair_id"],
                "record_identity_sha256": record["record_identity_sha256"],
                "statistics_aggregate_sha256": record["statistics_aggregate_sha256"],
            }
        )
    if len(rows) != int(primary["repeats"]):
        _fail("article-statistics primary inference lacks the 10 preregistered pairs")
    repeats = [int(row["repeat"]) for row in rows]
    if sorted(repeats) != list(range(1, int(primary["repeats"]) + 1)):
        _fail("article-statistics primary repeat coverage is not exact")
    pairs = pd.DataFrame(rows).sort_values("repeat").reset_index(drop=True)
    inference = build_primary_architecture_inference(pairs, config_copy)
    claim_state = evaluate_primary_architecture_claim_state(
        pairs, inference, config_copy
    )
    result = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_article_primary_inference",
        "status": "derived_from_sealed_pair_statistics",
        "source_records": sorted(source_records, key=lambda row: row["pair_sequence"]),
        "source_records_aggregate_sha256": _canonical_sha(
            sorted(source_records, key=lambda row: row["pair_sequence"])
        ),
        "pairs": _json_value(pairs.to_dict(orient="records")),
        "inference": _json_value(inference.to_dict(orient="records")),
        "claim_state": _json_value(claim_state),
    }
    result["result_identity_sha256"] = _canonical_sha(result)
    return result


__all__ = [
    "ArticleStatisticsV1Error",
    "ATTEMPT_COPY_NAME",
    "build_article_statistics_pair_record_v1",
    "build_primary_architecture_inference_from_article_records_v1",
    "load_article_statistics_record_v1",
    "persist_article_statistics_pair_record_v1",
    "seal_pair_article_statistics_v1",
    "validate_article_statistics_binding_v1",
    "validate_article_statistics_pair_record_v1",
]
