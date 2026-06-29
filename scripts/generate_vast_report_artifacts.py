#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_contract import (  # noqa: E402
    ContractError,
    canonicalize_frames_csv,
    stage_base_name,
    validate_drop_counters,
    validate_frame_events,
    validate_policy_decisions,
    validate_resource_events,
)


GROUP_COLUMNS = [
    "scenario",
    "deadline_ms",
    "deployment_mode",
    "host_topology",
    "system",
    "policy",
    "detector",
    "backend",
    "dataset",
]
PROOF_BASE_STAGES = ["decode", "preprocess"]
BASELINE_SCENARIO = "checkpoint_independent_processes_baseline"
SHARED_SCENARIO = "checkpoint_video_dag_shared"


def load_report_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    benchmark = config.get("benchmark") or {}
    scenarios = benchmark.get("report_scenarios") or []
    if not scenarios:
        raise ContractError(f"{path} must define benchmark.report_scenarios")
    missing = [name for name in scenarios if name not in (config.get("scenarios") or {})]
    if missing:
        raise ContractError(f"benchmark.report_scenarios contains unknown scenarios: {', '.join(missing)}")
    deadlines = benchmark.get("report_deadline_ms") or []
    if not deadlines:
        raise ContractError(f"{path} must define benchmark.report_deadline_ms")
    if any(float(value) == 3000.0 for value in deadlines):
        raise ContractError("publishable report_deadline_ms must not include 3000 ms")
    return config


def report_scenarios(config: dict[str, Any]) -> list[str]:
    return [str(name) for name in config.get("benchmark", {}).get("report_scenarios", [])]


def report_deadlines_ms(config: dict[str, Any]) -> list[float]:
    return [float(value) for value in config.get("benchmark", {}).get("report_deadline_ms", [])]


def system_order(config: dict[str, Any]) -> list[str]:
    return [str(name) for name in (config.get("systems") or {}).keys()]


def policy_order(config: dict[str, Any]) -> list[str]:
    benchmark = config.get("benchmark", {})
    return list(dict.fromkeys(
        [str(name) for name in benchmark.get("scheduler_policies", [])]
        + [str(name) for name in benchmark.get("scheduler_ablations", [])]
    ))


def dataset_order(config: dict[str, Any]) -> list[str]:
    benchmark = config.get("benchmark", {})
    return [str(name) for name in benchmark.get("report_datasets") or benchmark.get("benchmark_datasets") or []]


def scenario_deployment(config: dict[str, Any], scenario: str) -> tuple[str, str]:
    raw = config.get("scenarios", {}).get(scenario) or {}
    if bool((raw.get("distributed") or {}).get("enabled")):
        return "single-server-distributed", "single_host_ssh"
    return "heterogeneous", "single_host"


def read_summaries(run_root: Path) -> pd.DataFrame:
    paths = sorted(run_root.rglob("summary.csv"))
    if not paths:
        raise FileNotFoundError(f"no summary.csv files found under {run_root}")
    frames: list[pd.DataFrame] = []
    for path in paths:
        df = pd.read_csv(path)
        if df.empty:
            continue
        df["summary_path"] = str(path.relative_to(run_root))
        frames.append(df)
    if not frames:
        raise ValueError("all summary.csv files are empty")
    return pd.concat(frames, ignore_index=True)


def validate_report_inputs(df: pd.DataFrame, config: dict[str, Any]) -> None:
    scenarios = report_scenarios(config)
    observed = set(df.get("scenario", pd.Series(dtype=str)).astype(str))
    missing = [scenario for scenario in scenarios if scenario not in observed]
    if missing:
        raise ContractError(f"summary is missing proof scenarios: {', '.join(missing)}")
    if "deadline_ms" not in df.columns:
        raise ContractError("summary.csv must contain deadline_ms")
    expected_datasets = dataset_order(config)
    if expected_datasets:
        observed_datasets = set(df.get("dataset", pd.Series(dtype=str)).astype(str))
        missing_datasets = [dataset for dataset in expected_datasets if dataset not in observed_datasets]
        if missing_datasets:
            raise ContractError(f"summary is missing publishable datasets: {', '.join(missing_datasets)}")
        unexpected = sorted(observed_datasets - set(expected_datasets))
        if unexpected:
            raise ContractError(f"publishable summary contains non-report datasets: {', '.join(unexpected)}")
    legacy = sorted(observed.intersection({"baseline", "high_density_multistage", "bursty_workload", "stream_scaling", "canonical_heterogeneous", "duplicated_decode_baseline", "canonical_distributed"}))
    if legacy:
        raise ContractError(f"publishable summary contains legacy scenarios: {', '.join(legacy)}")
    proof = df[df["scenario"].astype(str).isin(scenarios)].copy()
    completed = proof[proof["status"].astype(str) == "completed"]
    bad = completed[completed["telemetry_source"].astype(str) != "native"]
    if not bad.empty:
        sample = bad[["scenario", "system", "policy", "repeat", "telemetry_source"]].head(5).to_dict("records")
        raise ContractError(f"publishable report only accepts completed native telemetry rows; sample={sample}")


def ci95(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return math.nan
    lo, hi = bootstrap_mean_ci(values, iterations=1000)
    return round((hi - lo) / 2.0, 6)


def aggregate(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    for column in [
        "throughput_fps",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "slo_violation_rate_percent",
        "frames",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    completed = df[
        (df["scenario"].astype(str).isin(report_scenarios(config)))
        & (df["status"].astype(str) == "completed")
        & (df["telemetry_source"].astype(str) == "native")
    ].copy()
    metrics = (
        completed.groupby(GROUP_COLUMNS, dropna=False)
        .agg(
            completed_repeats=("repeat", "count"),
            throughput_fps_mean=("throughput_fps", "mean"),
            throughput_fps_std=("throughput_fps", "std"),
            throughput_fps_ci95=("throughput_fps", ci95),
            latency_p50_ms_mean=("latency_p50_ms", "mean"),
            latency_p95_ms_mean=("latency_p95_ms", "mean"),
            latency_p99_ms_mean=("latency_p99_ms", "mean"),
            latency_p999_ms_mean=("latency_p999_ms", "mean"),
            latency_max_ms_mean=("latency_max_ms", "mean"),
            slo_violation_rate_percent_mean=("slo_violation_rate_percent", "mean"),
            frames_total=("frames", "sum"),
        )
        .reset_index()
    )
    status = (
        df[df["scenario"].astype(str).isin(report_scenarios(config))]
        .groupby(["scenario", "deadline_ms", "deployment_mode", "system", "policy", "dataset", "status"], dropna=False)
        .size()
        .reset_index(name="runs")
    )
    return metrics, status


def expected_matrix(config: dict[str, Any], repeats: int) -> pd.DataFrame:
    rows = []
    datasets = dataset_order(config) or [""]
    for dataset in datasets:
        for scenario in report_scenarios(config):
            deployment_mode, host_topology = scenario_deployment(config, scenario)
            for deadline_ms in report_deadlines_ms(config):
                for system in system_order(config):
                    for policy in policy_order(config):
                        for repeat in range(1, repeats + 1):
                            rows.append(
                                {
                                    "dataset": dataset,
                                    "scenario": scenario,
                                    "deadline_ms": float(deadline_ms),
                                    "deployment_mode": deployment_mode,
                                    "host_topology": host_topology,
                                    "system": system,
                                    "policy": policy,
                                    "repeat": repeat,
                                }
                            )
    return pd.DataFrame(rows)


def write_expected_audit(df: pd.DataFrame, config: dict[str, Any], out_dir: Path, repeats: int) -> pd.DataFrame:
    expected = expected_matrix(config, repeats)
    actual = df[["dataset", "scenario", "deadline_ms", "deployment_mode", "system", "policy", "repeat", "status"]].copy()
    actual = actual[actual["scenario"].astype(str).isin(report_scenarios(config))]
    merged = expected.merge(actual, on=["dataset", "scenario", "deadline_ms", "deployment_mode", "system", "policy", "repeat"], how="left")
    merged["status"] = merged["status"].fillna("missing")
    merged.to_csv(out_dir / "expected_matrix_audit.csv", index=False)
    return merged


def run_dir_for_row(run_root: Path, row: pd.Series) -> Path:
    roots = [run_root]
    dataset = str(row.get("dataset", "")).strip()
    policy = str(row.get("policy", "")).strip()
    if dataset and dataset.lower() != "nan" and policy and policy.lower() != "nan":
        roots.insert(0, run_root / f"dataset_{dataset}" / f"policy_{policy}")
    for root in roots:
        scenario_dir = root / str(row["scenario"])
        variant = str(row.get("scenario_variant", "")).strip()
        if variant and variant.lower() != "nan":
            scenario_dir /= f"variant_{variant}"
        base = scenario_dir / f"streams_{int(row['streams'])}"
        if "deadline_ms" in row and not pd.isna(row["deadline_ms"]):
            slug = f"{float(row['deadline_ms']):g}".replace(".", "p")
            candidate = base / f"deadline_{slug}" / str(row["system"]) / f"rep_{int(row['repeat']):02d}"
            if candidate.exists():
                return candidate
        candidate = base / str(row["system"]) / f"rep_{int(row['repeat']):02d}"
        if candidate.exists():
            return candidate
    return roots[0] / str(row["scenario"]) / f"streams_{int(row['streams'])}" / str(row["system"]) / f"rep_{int(row['repeat']):02d}"


def completed_native_rows(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    return df[
        (df["scenario"].astype(str).isin(report_scenarios(config)))
        & (df["status"].astype(str) == "completed")
        & (df["telemetry_source"].astype(str) == "native")
    ].copy()


def deadline_rows_for_frames(frames: pd.DataFrame, deadlines_ms: list[float], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    latency = pd.to_numeric(frames["e2e_latency_ms"], errors="raise")
    rows: list[dict[str, Any]] = []
    frame_count = int(frames.shape[0])
    duration_s = max(float(metadata.get("duration_s", 0.0)), 0.001)
    for deadline_ms in deadlines_ms:
        rows.append(
            {
                **metadata,
                "deadline_ms": float(deadline_ms),
                "frames": frame_count,
                "throughput_fps": round(frame_count / duration_s, 3),
                "latency_p95_ms": round(float(latency.quantile(0.95)), 3),
                "latency_p99_ms": round(float(latency.quantile(0.99)), 3),
                "slo_violation_rate_percent": round(float((latency > float(deadline_ms)).mean() * 100.0), 3),
            }
        )
    return rows


def build_deadline_metrics(run_root: Path, df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    deadlines = report_deadlines_ms(config)
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        frames = canonicalize_frames_csv(
            run_dir / "frames.csv",
            mode="benchmark",
            run_id="",
            detector="",
            backend="",
        )
        metadata = {
            "scenario": row["scenario"],
            "deadline_ms_run": float(row.get("deadline_ms", math.nan)),
            "deadline_ms": float(row.get("deadline_ms", math.nan)),
            "deployment_mode": row["deployment_mode"],
            "host_topology": row["host_topology"],
            "system": row["system"],
            "policy": row["policy"],
            "repeat": int(row["repeat"]),
            "streams": int(row["streams"]),
            "duration_s": float(row["duration_s"]),
            "dataset": row["dataset"],
            "run_dir": str(run_dir.relative_to(run_root)),
        }
        rows.extend(deadline_rows_for_frames(frames, deadlines, metadata))
    return pd.DataFrame(rows)


def stage_metric_rows_for_events(events: pd.DataFrame, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    df = events.copy()
    df["stage_duration_ms"] = pd.to_numeric(df["stage_end_timestamp_ms"], errors="raise") - pd.to_numeric(
        df["stage_start_timestamp_ms"], errors="raise"
    )
    df["queue_wait_ms"] = pd.to_numeric(df["stage_start_timestamp_ms"], errors="raise") - pd.to_numeric(
        df["queue_enter_timestamp_ms"], errors="raise"
    )
    df["base_stage"] = df["stage"].astype(str).map(stage_base_name)
    rows: list[dict[str, Any]] = []
    for keys, group in df.groupby(["stage", "base_stage", "role", "resource"], dropna=False):
        stage, base_stage, role, resource = keys
        durations = pd.to_numeric(group["stage_duration_ms"], errors="coerce")
        waits = pd.to_numeric(group["queue_wait_ms"], errors="coerce")
        rows.append(
            {
                **metadata,
                "stage": stage,
                "base_stage": base_stage,
                "role": role,
                "resource": resource,
                "event_count": int(group.shape[0]),
                "stage_duration_ms_total": round(float(durations.sum()), 3),
                "stage_duration_ms_mean": round(float(durations.mean()), 3),
                "stage_duration_ms_p95": round(float(durations.quantile(0.95)), 3),
                "stage_duration_ms_p99": round(float(durations.quantile(0.99)), 3),
                "queue_wait_ms_mean": round(float(waits.mean()), 3),
            }
        )
    return rows


def build_stage_metrics(run_root: Path, df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        events = validate_frame_events(run_dir / "frame_events.csv")
        metadata = {
            "scenario": row["scenario"],
            "deadline_ms": float(row.get("deadline_ms", math.nan)),
            "deployment_mode": row["deployment_mode"],
            "host_topology": row["host_topology"],
            "system": row["system"],
            "policy": row["policy"],
            "repeat": int(row["repeat"]),
            "streams": int(row["streams"]),
            "dataset": row["dataset"],
            "run_dir": str(run_dir.relative_to(run_root)),
        }
        rows.extend(stage_metric_rows_for_events(events, metadata))
    return pd.DataFrame(rows)


def build_checkpoint_event_factor(stage_metrics: pd.DataFrame, summary: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if stage_metrics.empty:
        return pd.DataFrame()
    if "dataset" not in summary.columns:
        summary = summary.copy()
        summary["dataset"] = ""
    if "dataset" not in stage_metrics.columns:
        stage_metrics = stage_metrics.copy()
        stage_metrics["dataset"] = ""
    completed = completed_native_rows(summary, config)[
        [
            "scenario",
            "deadline_ms",
            "system",
            "policy",
            "dataset",
            "repeat",
            "frames",
            "throughput_fps",
            "latency_p95_ms",
            "latency_p99_ms",
            "slo_violation_rate_percent",
        ]
    ].copy()
    completed["frames"] = pd.to_numeric(completed["frames"], errors="coerce")
    base = (
        stage_metrics[stage_metrics["base_stage"].isin(PROOF_BASE_STAGES)]
        .groupby(["scenario", "deadline_ms", "system", "policy", "dataset", "repeat", "base_stage"], dropna=False)
        .agg(event_count=("event_count", "sum"), stage_duration_ms_total=("stage_duration_ms_total", "sum"))
        .reset_index()
    )
    base = base.merge(completed, on=["scenario", "deadline_ms", "system", "policy", "dataset", "repeat"], how="left")
    base["event_factor"] = base["event_count"] / base["frames"].replace(0, math.nan)

    baseline = base[base["scenario"] == BASELINE_SCENARIO].copy()
    consumer_count = int((config.get("scenarios", {}).get(BASELINE_SCENARIO, {}).get("workload") or {}).get("logical_consumers", 4))
    required = baseline[baseline["base_stage"].isin(PROOF_BASE_STAGES)]
    bad = required[(required["frames"] > 0) & (required["event_factor"] < max(1.0, consumer_count * 0.9))]
    if not bad.empty:
        sample = bad[["system", "policy", "deadline_ms", "repeat", "base_stage", "event_factor"]].head(5).to_dict("records")
        raise ContractError(
            f"{BASELINE_SCENARIO} must show decode/preprocess event factor near logical consumers={consumer_count}; sample={sample}"
        )

    shared = base[base["scenario"] == SHARED_SCENARIO].copy()
    shared_bad = shared[(shared["frames"] > 0) & (shared["event_factor"] > 1.25)]
    if not shared_bad.empty:
        sample = shared_bad[["system", "policy", "deadline_ms", "repeat", "base_stage", "event_factor"]].head(5).to_dict("records")
        raise ContractError(f"{SHARED_SCENARIO} must keep common-stage event factor near 1x; sample={sample}")

    pairs = shared.merge(
        baseline,
        on=["system", "policy", "dataset", "deadline_ms", "repeat", "base_stage"],
        suffixes=("_shared", "_baseline"),
        how="inner",
    )
    if pairs.empty:
        return pairs
    pairs["event_factor_ratio"] = pairs["event_factor_baseline"] / pairs["event_factor_shared"].replace(0, math.nan)
    pairs["stage_time_ratio"] = pairs["stage_duration_ms_total_baseline"] / pairs[
        "stage_duration_ms_total_shared"
    ].replace(0, math.nan)
    pairs["fps_ratio_baseline_vs_shared"] = pairs["throughput_fps_baseline"] / pairs[
        "throughput_fps_shared"
    ].replace(0, math.nan)
    return pairs


build_shared_vs_duplicated = build_checkpoint_event_factor


def fmt_num(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return "--"
    return f"{float(value):.{digits}f}"


def latex_escape(value: object) -> str:
    text = str(value)
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def scenario_caption(scenario: str) -> str:
    captions = {
        "checkpoint_video_dag_shared": "Shared Video-DAG KPP metrics on real AVI inputs",
        "checkpoint_independent_processes_baseline": "Independent process KPP baseline metrics on real AVI inputs",
    }
    return captions.get(scenario, f"Completed native metrics for {scenario}")


def scenario_label(scenario: str) -> str:
    return "tab:vast_metrics_" + scenario.replace("_", "")


def plot_metric(metrics: pd.DataFrame, config: dict[str, Any], out_dir: Path, metric: str, filename: str, ylabel: str) -> None:
    if metrics.empty:
        return
    sns.set_theme(style="whitegrid", context="paper")
    plot_df = metrics.copy()
    plot_df["system"] = pd.Categorical(plot_df["system"], system_order(config), ordered=True)
    plot_df["policy"] = pd.Categorical(plot_df["policy"], policy_order(config), ordered=True)
    for scenario in report_scenarios(config):
        subset = plot_df[plot_df["scenario"] == scenario].sort_values(["system", "policy"])
        if subset.empty:
            continue
        plt.figure(figsize=(12, 5.4))
        ax = sns.barplot(data=subset, x="system", y=metric, hue="policy")
        ax.set_title(f"{ylabel} - {scenario}")
        ax.set_xlabel("System")
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=18)
        ax.legend(title="Policy", ncols=2, fontsize=8)
        plt.tight_layout()
        plt.savefig(out_dir / f"{filename}_{scenario}.png", dpi=180)
        plt.close()


def plot_deadlines(deadline_metrics: pd.DataFrame, config: dict[str, Any], out_dir: Path) -> None:
    if deadline_metrics.empty:
        return
    plot_df = (
        deadline_metrics.groupby(["scenario", "dataset", "deadline_ms", "policy"], dropna=False)["slo_violation_rate_percent"]
        .mean()
        .reset_index()
    )
    for scenario in report_scenarios(config):
        subset = plot_df[plot_df["scenario"] == scenario]
        if subset.empty:
            continue
        plt.figure(figsize=(8.5, 4.8))
        ax = sns.lineplot(data=subset, x="deadline_ms", y="slo_violation_rate_percent", hue="policy", marker="o")
        ax.set_title(f"Deadline sensitivity - {scenario}")
        ax.set_xlabel("Deadline, ms")
        ax.set_ylabel("SLO violation rate, %")
        plt.tight_layout()
        plt.savefig(out_dir / f"deadline_sensitivity_{scenario}.png", dpi=180)
        plt.close()


def plot_status(status_audit: pd.DataFrame, out_dir: Path) -> None:
    if status_audit.empty:
        return
    counts = status_audit.groupby(["scenario", "status"], dropna=False).size().reset_index(name="runs")
    plt.figure(figsize=(10, 4.8))
    ax = sns.barplot(data=counts, x="scenario", y="runs", hue="status")
    ax.set_title("Benchmark matrix completion status")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Runs")
    ax.tick_params(axis="x", rotation=12)
    ax.legend(title="Status")
    plt.tight_layout()
    plt.savefig(out_dir / "status_counts_by_scenario.png", dpi=180)
    plt.close()


def plot_checkpoint_event_factor(checkpoint_event_factor: pd.DataFrame, out_dir: Path) -> None:
    if checkpoint_event_factor.empty:
        return
    plot_df = (
        checkpoint_event_factor.groupby("base_stage", dropna=False)[
            ["event_factor_shared", "event_factor_baseline", "event_factor_ratio"]
        ]
        .mean()
        .reset_index()
    )
    melted = plot_df.melt(
        id_vars=["base_stage"],
        value_vars=["event_factor_shared", "event_factor_baseline"],
        var_name="scenario",
        value_name="events_per_frame",
    )
    plt.figure(figsize=(6.8, 4.2))
    ax = sns.barplot(data=melted, x="base_stage", y="events_per_frame", hue="scenario")
    ax.set_title("Shared Video-DAG versus independent common-stage events")
    ax.set_xlabel("Base stage")
    ax.set_ylabel("Events per completed frame")
    plt.tight_layout()
    plt.savefig(out_dir / "checkpoint_event_factor.png", dpi=180)
    plt.close()


def bootstrap_mean_ci(series: pd.Series, *, iterations: int = 2000, seed: int = 20260323) -> tuple[float, float]:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if values.size == 0:
        return math.nan, math.nan
    if values.size == 1:
        return float(values[0]), float(values[0])
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(iterations, values.size), replace=True).mean(axis=1)
    lo, hi = np.quantile(samples, [0.025, 0.975])
    return float(lo), float(hi)


def paired_wilcoxon_pvalue(a: pd.Series, b: pd.Series) -> float:
    left = pd.to_numeric(a, errors="coerce")
    right = pd.to_numeric(b, errors="coerce")
    diff = (left - right).dropna().to_numpy(dtype=float)
    diff = diff[diff != 0.0]
    n = int(diff.size)
    if n == 0:
        return 1.0

    order = np.argsort(np.abs(diff), kind="mergesort")
    ranks = np.empty(n, dtype=float)
    abs_sorted = np.abs(diff)[order]
    start = 0
    while start < n:
        end = start + 1
        while end < n and abs_sorted[end] == abs_sorted[start]:
            end += 1
        rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = rank
        start = end

    w_plus = float(ranks[diff > 0].sum())
    total = float(ranks.sum())
    observed = min(w_plus, total - w_plus)
    if n <= 25:
        scaled_ranks = [int(round(rank * 2.0)) for rank in ranks]
        total_scaled = sum(scaled_ranks)
        observed_scaled = int(round(observed * 2.0))
        sums = [0]
        for rank in scaled_ranks:
            sums += [value + rank for value in sums]
        extreme = sum(1 for value in sums if min(value, total_scaled - value) <= observed_scaled)
        return float(min(1.0, extreme / len(sums)))

    mean = total / 2.0
    sd = math.sqrt(float((ranks * ranks).sum()) / 4.0)
    if sd == 0.0:
        return 1.0
    z = max(0.0, (abs(w_plus - mean) - 0.5) / sd)
    return float(math.erfc(z / math.sqrt(2.0)))

def paired_permutation_pvalue(a: pd.Series, b: pd.Series, *, iterations: int = 10000, seed: int = 20260323) -> float:
    left = pd.to_numeric(a, errors="coerce")
    right = pd.to_numeric(b, errors="coerce")
    diff = (left - right).dropna().to_numpy(dtype=float)
    if diff.size == 0:
        return math.nan
    observed = abs(float(diff.mean()))
    if observed == 0.0:
        return 1.0
    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(iterations, diff.size), replace=True)
    sampled = np.abs((signs * diff).mean(axis=1))
    return float((np.count_nonzero(sampled >= observed) + 1) / (iterations + 1))


def holm_adjust(p_values: list[float]) -> list[float]:
    indexed = [(idx, p) for idx, p in enumerate(p_values)]
    finite = sorted((item for item in indexed if math.isfinite(item[1])), key=lambda item: item[1])
    adjusted = [math.nan] * len(p_values)
    running = 0.0
    m = len(finite)
    for rank, (idx, p_value) in enumerate(finite):
        value = min(1.0, (m - rank) * p_value)
        running = max(running, value)
        adjusted[idx] = running
    return adjusted


def build_stat_tests(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    completed = completed_native_rows(df, config).copy()
    rows: list[dict[str, Any]] = []
    metrics = ["throughput_fps", "latency_p95_ms", "latency_p99_ms", "slo_violation_rate_percent"]
    keys = ["system", "policy", "dataset", "deadline_ms", "repeat"]
    shared = completed[completed["scenario"] == SHARED_SCENARIO]
    baseline = completed[completed["scenario"] == BASELINE_SCENARIO]
    for metric in metrics:
        paired = shared[keys + [metric]].merge(
            baseline[keys + [metric]],
            on=keys,
            suffixes=("_shared", "_baseline"),
            how="inner",
        )
        if paired.empty:
            continue
        p_value = paired_permutation_pvalue(paired[f"{metric}_shared"], paired[f"{metric}_baseline"])
        wilcoxon_p = paired_wilcoxon_pvalue(paired[f"{metric}_shared"], paired[f"{metric}_baseline"])
        shared_lo, shared_hi = bootstrap_mean_ci(paired[f"{metric}_shared"])
        base_lo, base_hi = bootstrap_mean_ci(paired[f"{metric}_baseline"])
        rows.append(
            {
                "comparison": f"{SHARED_SCENARIO} vs {BASELINE_SCENARIO}",
                "metric": metric,
                "pairs": int(paired.shape[0]),
                "shared_mean": float(pd.to_numeric(paired[f"{metric}_shared"], errors="coerce").mean()),
                "shared_ci95_low": shared_lo,
                "shared_ci95_high": shared_hi,
                "baseline_mean": float(pd.to_numeric(paired[f"{metric}_baseline"], errors="coerce").mean()),
                "baseline_ci95_low": base_lo,
                "baseline_ci95_high": base_hi,
                "paired_permutation_p": p_value,
                "paired_wilcoxon_p": wilcoxon_p,
            }
        )
    permutation_adjusted = holm_adjust([float(row["paired_permutation_p"]) for row in rows])
    wilcoxon_adjusted = holm_adjust([float(row["paired_wilcoxon_p"]) for row in rows])
    for row, permutation_p_adj, wilcoxon_p_adj in zip(rows, permutation_adjusted, wilcoxon_adjusted, strict=True):
        row["paired_permutation_holm_p"] = permutation_p_adj
        row["paired_wilcoxon_holm_p"] = wilcoxon_p_adj
        row["holm_p"] = permutation_p_adj
    return pd.DataFrame(rows)


def build_resource_metrics(run_root: Path, df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        resource = validate_resource_events(run_dir / "resource_events.csv").copy()
        resource["scenario"] = row["scenario"]
        resource["deadline_ms"] = float(row["deadline_ms"])
        resource["system"] = row["system"]
        resource["policy"] = row["policy"]
        resource["dataset"] = row["dataset"]
        resource["repeat"] = int(row["repeat"])
        resource["run_dir"] = str(run_dir.relative_to(run_root))
        rows.append(resource)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_drop_metrics(run_root: Path, df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        drops = validate_drop_counters(run_dir / "drop_counters.csv").copy()
        drops["scenario"] = row["scenario"]
        drops["deadline_ms"] = float(row["deadline_ms"])
        drops["system"] = row["system"]
        drops["policy"] = row["policy"]
        drops["dataset"] = row["dataset"]
        drops["repeat"] = int(row["repeat"])
        drops["run_dir"] = str(run_dir.relative_to(run_root))
        rows.append(drops)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build_policy_metrics(run_root: Path, df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        decisions = validate_policy_decisions(run_dir / "policy_decisions.csv").copy()
        decisions["scenario"] = row["scenario"]
        decisions["deadline_ms"] = float(row["deadline_ms"])
        decisions["system"] = row["system"]
        decisions["policy"] = row["policy"]
        decisions["dataset"] = row["dataset"]
        decisions["repeat"] = int(row["repeat"])
        decisions["run_dir"] = str(run_dir.relative_to(run_root))
        rows.append(decisions)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def plot_latency_distributions(run_root: Path, df: pd.DataFrame, config: dict[str, Any], out_dir: Path) -> None:
    rows: list[pd.DataFrame] = []
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        frames = canonicalize_frames_csv(run_dir / "frames.csv", mode="benchmark", run_id="", detector="", backend="")
        sample = frames[["e2e_latency_ms"]].copy()
        sample["scenario"] = row["scenario"]
        sample["deadline_ms"] = float(row["deadline_ms"])
        sample["policy"] = row["policy"]
        sample["dataset"] = row["dataset"]
        rows.append(sample)
    if not rows:
        return
    latency = pd.concat(rows, ignore_index=True)
    for scenario in report_scenarios(config):
        subset = latency[latency["scenario"] == scenario]
        if subset.empty:
            continue
        plt.figure(figsize=(8.5, 4.8))
        sns.ecdfplot(data=subset, x="e2e_latency_ms", hue="policy")
        plt.xlabel("Latency, ms")
        plt.ylabel("CDF")
        plt.tight_layout()
        plt.savefig(out_dir / f"latency_cdf_{scenario}.png", dpi=180)
        plt.close()
        plt.figure(figsize=(8.5, 4.8))
        sns.histplot(data=subset, x="e2e_latency_ms", hue="policy", stat="density", common_norm=False, bins=50)
        plt.xlabel("Latency, ms")
        plt.ylabel("PDF")
        plt.tight_layout()
        plt.savefig(out_dir / f"latency_pdf_{scenario}.png", dpi=180)
        plt.close()


def plot_resource_metrics(resource_metrics: pd.DataFrame, drop_metrics: pd.DataFrame, out_dir: Path) -> None:
    if not resource_metrics.empty:
        transfer = (
            resource_metrics.groupby(["scenario", "deadline_ms", "policy", "dataset"], dropna=False)[["h2d_bytes", "d2h_bytes"]]
            .sum()
            .reset_index()
        )
        melted = transfer.melt(
            id_vars=["scenario", "deadline_ms", "policy", "dataset"],
            value_vars=["h2d_bytes", "d2h_bytes"],
            var_name="direction",
            value_name="bytes",
        )
        plt.figure(figsize=(10, 4.8))
        sns.lineplot(data=melted, x="deadline_ms", y="bytes", hue="direction", style="scenario", marker="o")
        plt.xlabel("Deadline, ms")
        plt.ylabel("Bytes")
        plt.tight_layout()
        plt.savefig(out_dir / "h2d_d2h_by_deadline.png", dpi=180)
        plt.close()

        timeline = resource_metrics.copy()
        timeline["time_ms"] = pd.to_numeric(timeline["timestamp_ms"], errors="coerce")
        timeline["compute_ms"] = pd.to_numeric(timeline["cpu_time_ms"], errors="coerce") + pd.to_numeric(
            timeline["gpu_time_ms"], errors="coerce"
        )
        plt.figure(figsize=(10, 4.8))
        sns.lineplot(data=timeline.head(50000), x="time_ms", y="compute_ms", hue="scenario", estimator="mean", errorbar=None)
        plt.xlabel("Timestamp, ms")
        plt.ylabel("CPU+GPU stage time, ms")
        plt.tight_layout()
        plt.savefig(out_dir / "resource_timeline.png", dpi=180)
        plt.close()

    if not drop_metrics.empty:
        drops = (
            drop_metrics.groupby(["scenario", "deadline_ms", "policy", "dataset"], dropna=False)[["drop_rate_percent", "late_rate_percent"]]
            .mean()
            .reset_index()
        )
        melted = drops.melt(
            id_vars=["scenario", "deadline_ms", "policy", "dataset"],
            value_vars=["drop_rate_percent", "late_rate_percent"],
            var_name="metric",
            value_name="percent",
        )
        plt.figure(figsize=(10, 4.8))
        sns.lineplot(data=melted, x="deadline_ms", y="percent", hue="metric", style="scenario", marker="o")
        plt.xlabel("Deadline, ms")
        plt.ylabel("Rate, %")
        plt.tight_layout()
        plt.savefig(out_dir / "drop_late_rate_by_deadline.png", dpi=180)
        plt.close()


def write_winning_deadline(deadline_metrics: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    if deadline_metrics.empty:
        result = pd.DataFrame()
        result.to_csv(out_dir / "shared_winning_deadline.csv", index=False)
        return result
    grouped = (
        deadline_metrics.groupby(["scenario", "dataset", "deadline_ms"], dropna=False)
        .agg(
            slo_violation_rate_percent=("slo_violation_rate_percent", "mean"),
            latency_p95_ms=("latency_p95_ms", "mean"),
            throughput_fps=("throughput_fps", "mean"),
        )
        .reset_index()
    )
    shared = grouped[grouped["scenario"] == SHARED_SCENARIO]
    baseline = grouped[grouped["scenario"] == BASELINE_SCENARIO]
    paired = shared.merge(baseline, on=["dataset", "deadline_ms"], suffixes=("_shared", "_baseline"), how="inner")
    if paired.empty:
        paired.to_csv(out_dir / "shared_winning_deadline.csv", index=False)
        return paired
    paired["shared_wins"] = (
        (paired["slo_violation_rate_percent_shared"] <= paired["slo_violation_rate_percent_baseline"])
        & (paired["latency_p95_ms_shared"] <= paired["latency_p95_ms_baseline"])
    ) | (paired["throughput_fps_shared"] > paired["throughput_fps_baseline"])
    winners = paired[paired["shared_wins"]].sort_values("deadline_ms")
    result = winners.head(1) if not winners.empty else paired.head(0)
    result.to_csv(out_dir / "shared_winning_deadline.csv", index=False)
    return result


def write_latex_tables(
    metrics: pd.DataFrame,
    status_audit: pd.DataFrame,
    raw: pd.DataFrame,
    stage_metrics: pd.DataFrame,
    checkpoint_event_factor: pd.DataFrame,
    config: dict[str, Any],
    out_dir: Path,
) -> None:
    lines: list[str] = []
    counts = status_audit.groupby(["scenario", "status"], dropna=False).size().reset_index(name="runs")
    lines.extend([
        "% Auto-generated status table",
        "\\begin{table}[H]",
        "\\centering",
        "\\small",
        "\\caption{Execution status counts for the expected VAST proof matrix}\\label{tab:vast_status_counts}",
        "\\begin{tabular}{|l|l|r|}",
        "\\hline",
        "Scenario & Status & Runs \\",
        "\\hline",
    ])
    for row in counts.itertuples(index=False):
        lines.append(f"{latex_escape(row.scenario)} & {latex_escape(row.status)} & {int(row.runs)} \\")
        lines.append("\\hline")
    lines.extend(["\\end{tabular}", "\\end{table}", ""])

    non_completed = raw[(raw["scenario"].astype(str).isin(report_scenarios(config))) & (raw["status"] != "completed")].copy()
    if not non_completed.empty:
        lines.extend([
            "% Auto-generated non-completed run table",
            "\\begin{table}[H]",
            "\\centering",
            "\\scriptsize",
            "\\caption{Non-completed VAST benchmark runs and recorded reasons}\\label{tab:vast_failed_reasons}",
            "\\begin{tabular}{|l|l|l|r|l|p{3.8cm}|}",
            "\\hline",
            "Scenario & System & Policy & Rep. & Status & Reason \\",
            "\\hline",
        ])
        for row in non_completed.sort_values(["scenario", "system", "policy", "repeat"]).itertuples(index=False):
            reason = getattr(row, "skip_reason", "")
            if pd.isna(reason) or not str(reason):
                reason = "not recorded"
            lines.append(
                " & ".join(
                    [
                        latex_escape(row.scenario),
                        latex_escape(row.system),
                        latex_escape(row.policy),
                        str(int(row.repeat)),
                        latex_escape(row.status),
                        latex_escape(reason),
                    ]
                )
                + " \\")
            lines.append("\\hline")
        lines.extend(["\\end{tabular}", "\\end{table}", ""])

    for scenario in report_scenarios(config):
        subset = metrics[metrics["scenario"] == scenario].copy()
        if subset.empty:
            continue
        subset["system"] = pd.Categorical(subset["system"], system_order(config), ordered=True)
        subset["policy"] = pd.Categorical(subset["policy"], policy_order(config), ordered=True)
        subset = subset.sort_values(["system", "policy"])
        lines.extend([
            f"% Auto-generated metric table for {scenario}",
            "\\begin{landscape}",
            "\\begin{table}[p]",
            "\\centering",
            "\\scriptsize",
            f"\\caption{{{scenario_caption(scenario)}}}\\label{{{scenario_label(scenario)}}}",
            "\\setlength{\\tabcolsep}{2pt}",
            "\\renewcommand{\\arraystretch}{1.08}",
            "\\begin{tabular}{|l|l|r|r|r|r|r|r|r|r|}",
            "\\hline",
            "System & Policy & n & FPS & FPS CI95 & P50 ms & P95 ms & P99 ms & SLO \\% & Frames \\",
            "\\hline",
        ])
        for row in subset.itertuples(index=False):
            lines.append(
                " & ".join(
                    [
                        latex_escape(row.system),
                        latex_escape(row.policy),
                        str(int(row.completed_repeats)),
                        fmt_num(row.throughput_fps_mean),
                        fmt_num(row.throughput_fps_ci95),
                        fmt_num(row.latency_p50_ms_mean),
                        fmt_num(row.latency_p95_ms_mean),
                        fmt_num(row.latency_p99_ms_mean),
                        fmt_num(row.slo_violation_rate_percent_mean),
                        str(int(row.frames_total)),
                    ]
                )
                + " \\")
            lines.append("\\hline")
        lines.extend(["\\end{tabular}", "\\end{table}", "\\end{landscape}", ""])

    if not stage_metrics.empty:
        stage_summary = (
            stage_metrics.groupby(["scenario", "base_stage"], dropna=False)["stage_duration_ms_total"]
            .mean()
            .reset_index()
            .sort_values(["scenario", "base_stage"])
        )
        lines.extend([
            "% Auto-generated stage summary table",
            "\\begin{table}[H]",
            "\\centering",
            "\\small",
            "\\caption{Mean total native stage time by proof scenario and base stage}\\label{tab:vast_stage_metrics}",
            "\\begin{tabular}{|l|l|r|}",
            "\\hline",
            "Scenario & Base stage & Mean stage time ms \\",
            "\\hline",
        ])
        for row in stage_summary.itertuples(index=False):
            lines.append(f"{latex_escape(row.scenario)} & {latex_escape(row.base_stage)} & {fmt_num(row.stage_duration_ms_total)} \\")
            lines.append("\\hline")
        lines.extend(["\\end{tabular}", "\\end{table}", ""])

    if not checkpoint_event_factor.empty:
        comparison = (
            checkpoint_event_factor.groupby("base_stage", dropna=False)[
                ["event_factor_shared", "event_factor_baseline", "event_factor_ratio", "stage_time_ratio"]
            ]
            .mean()
            .reset_index()
        )
        comparison.to_csv(out_dir / "checkpoint_event_factor_summary.csv", index=False)
        lines.extend([
            "% Auto-generated shared-vs-duplicated proof table",
            "\\begin{table}[H]",
            "\\centering",
            "\\small",
            "\\caption{Shared Video-DAG versus independent decode/preprocess redundancy}\\label{tab:vast_checkpoint_event_factor}",
            "\\begin{tabular}{|l|r|r|r|r|}",
            "\\hline",
            "Base stage & Shared events/frame & Independent events/frame & Event factor & Stage-time factor \\",
            "\\hline",
        ])
        for row in comparison.itertuples(index=False):
            lines.append(
                " & ".join(
                    [
                        latex_escape(row.base_stage),
                        fmt_num(row.event_factor_shared, 3),
                        fmt_num(row.event_factor_baseline, 3),
                        fmt_num(row.event_factor_ratio, 3),
                        fmt_num(row.stage_time_ratio, 3),
                    ]
                )
                + " \\")
            lines.append("\\hline")
        lines.extend(["\\end{tabular}", "\\end{table}", ""])

    (out_dir / "latex_tables.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VAST report CSV, figures, and LaTeX tables")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "experiments.yaml")
    parser.add_argument("--expected-repeats", type=int, default=0)
    args = parser.parse_args()

    config = load_report_config(args.config)
    repeats = args.expected_repeats if args.expected_repeats > 0 else int(config.get("protocol", {}).get("repeats", 1))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    df = read_summaries(args.run_root)
    validate_report_inputs(df, config)
    df.to_csv(args.output_dir / "summary_combined.csv", index=False)

    metrics, status = aggregate(df, config)
    metrics.to_csv(args.output_dir / "summary_metrics.csv", index=False)
    status.to_csv(args.output_dir / "status_counts_raw.csv", index=False)
    df[(df["scenario"].astype(str).isin(report_scenarios(config))) & (df["status"] != "completed")].to_csv(
        args.output_dir / "non_completed_runs.csv", index=False
    )

    audit = write_expected_audit(df, config, args.output_dir, repeats)
    audit.groupby(["dataset", "scenario", "deadline_ms", "status"], dropna=False).size().reset_index(name="runs").to_csv(
        args.output_dir / "status_counts_expected.csv", index=False
    )

    stat_tests = build_stat_tests(df, config)
    stat_tests.to_csv(args.output_dir / "stat_tests.csv", index=False)
    resource_metrics = build_resource_metrics(args.run_root, df, config)
    resource_metrics.to_csv(args.output_dir / "resource_metrics.csv", index=False)
    drop_metrics = build_drop_metrics(args.run_root, df, config)
    drop_metrics.to_csv(args.output_dir / "drop_metrics.csv", index=False)
    policy_metrics = build_policy_metrics(args.run_root, df, config)
    policy_metrics.to_csv(args.output_dir / "policy_decisions_combined.csv", index=False)

    deadline_metrics = build_deadline_metrics(args.run_root, df, config)
    deadline_metrics.to_csv(args.output_dir / "deadline_metrics.csv", index=False)
    stage_metrics = build_stage_metrics(args.run_root, df, config)
    stage_metrics.to_csv(args.output_dir / "stage_metrics.csv", index=False)
    checkpoint_event_factor = build_checkpoint_event_factor(stage_metrics, df, config)
    checkpoint_event_factor.to_csv(args.output_dir / "checkpoint_event_factor.csv", index=False)

    plot_metric(metrics, config, args.output_dir, "throughput_fps_mean", "throughput_by_policy", "Throughput, FPS")
    plot_metric(metrics, config, args.output_dir, "latency_p95_ms_mean", "latency_p95_by_policy", "P95 latency, ms")
    plot_metric(
        metrics,
        config,
        args.output_dir,
        "slo_violation_rate_percent_mean",
        "slo_violation_by_policy",
        "SLO violation rate, %",
    )
    plot_deadlines(deadline_metrics, config, args.output_dir)
    plot_latency_distributions(args.run_root, df, config, args.output_dir)
    plot_resource_metrics(resource_metrics, drop_metrics, args.output_dir)
    write_winning_deadline(deadline_metrics, args.output_dir)
    plot_status(audit, args.output_dir)
    plot_checkpoint_event_factor(checkpoint_event_factor, args.output_dir)
    write_latex_tables(metrics, audit, df, stage_metrics, checkpoint_event_factor, config, args.output_dir)

    expected_total = len(expected_matrix(config, repeats))
    observed_total = len(df[df["scenario"].astype(str).isin(report_scenarios(config))])
    print(f"combined_rows={observed_total}")
    print(f"expected_rows={expected_total}")
    print(f"missing_rows={int((audit['status'] == 'missing').sum())}")
    print(f"deadline_rows={len(deadline_metrics)}")
    print(f"stage_rows={len(stage_metrics)}")
    print(f"resource_rows={len(resource_metrics)}")
    print(f"drop_rows={len(drop_metrics)}")
    print(f"stat_tests={len(stat_tests)}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
