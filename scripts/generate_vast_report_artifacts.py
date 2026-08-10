#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
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
    PRIMARY_ARCHITECTURE_PAIR_METADATA_CONTRACT_VERSION,
    STAGE_SEMANTIC_CONTRACT_VERSION,
    assess_decoder_placement,
    assess_hardware_target,
    assess_primary_policy_equivalence_scope,
    assess_primary_policy_runtime_compatibility,
    branch_analytics_contract_sha256,
    canonicalize_frames_csv,
    dataset_manifest_identity,
    evaluate_primary_policy_proxy_replay,
    load_dataset,
    measurement_signature_identity_is_valid,
    publication_run_contract_identity,
    resolve_publication_evidence_bundle_scope,
    resolve_publication_run_contract,
    resolve_scenario_contract,
    scenario_contract_identity,
    semantic_prefix_contract_sha256,
    stage_base_name,
    summarize_measurement_passport,
    validate_drop_counters,
    validate_frame_events,
    validate_policy_decisions,
    validate_publication_evidence_bundle,
    validate_primary_architecture_contrast,
    validate_primary_policy_ablation,
    validate_required_sidecars,
    validate_resource_events,
)
from topology_contract import validate_topology_events  # noqa: E402


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
MEASUREMENT_PASSPORT_COLUMNS = [
    "scenario",
    "system",
    "policy",
    "dataset",
    "deadline_ms",
    "streams",
    "repeat",
    "input_schedule_sha256",
    "input_frame_key_sequence_sha256",
    "measurement_window_duration_ms",
    "ingress_censoring_rule",
    "resource_attribution",
    "measurement_signature",
    "measurement_signature_payload_json",
    "ingress_frame_count",
    "completed_frame_count",
    "dropped_frame_count",
    "censored_frame_count",
    "c_obs_total_ms",
    "c_obs_cpu_total_ms",
    "c_obs_gpu_total_ms",
    "c_obs_in_ms_per_ingress",
    "c_obs_cpu_in_ms_per_ingress",
    "c_obs_gpu_in_ms_per_ingress",
    "c_obs_comp_ms_per_completed",
    "c_obs_is_partial",
]
PRIMARY_PAIR_METRICS = {
    "delta_reuse_obs_c_obs_in": ("coprimary", "lower_above_zero"),
    "delta_event_factor_decode": ("coprimary", "lower_above_zero"),
    "delta_event_factor_preprocess": ("coprimary", "lower_above_zero"),
    "shared_minus_baseline_vmax_completed_slo_violation_rate_percentage_points": (
        "quality_guardrail",
        "upper_at_or_below_zero",
    ),
    "shared_minus_baseline_drop_max_ingress_rate_percentage_points": (
        "quality_guardrail",
        "upper_at_or_below_zero",
    ),
}
PRIMARY_RESOURCE_MIX_DIAGNOSTIC_FIELDS = (
    "baseline_minus_shared_c_obs_cpu_in_ms_per_ingress",
    "baseline_minus_shared_c_obs_gpu_in_ms_per_ingress",
    "baseline_c_obs_cpu_share_percent",
    "shared_c_obs_cpu_share_percent",
    "shared_minus_baseline_c_obs_cpu_share_percentage_points",
    "baseline_c_obs_gpu_share_percent",
    "shared_c_obs_gpu_share_percent",
    "shared_minus_baseline_c_obs_gpu_share_percentage_points",
)
PRIMARY_POLICY_PAIR_METRICS = {
    "online_minus_frozen_vmax_completed_slo_violation_rate_percentage_points": (
        "primary",
        "upper_below_zero",
    ),
}


def load_report_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    validate_primary_architecture_contrast(config)
    validate_primary_policy_ablation(config)
    benchmark = config.get("benchmark") or {}
    scenarios = benchmark.get("report_scenarios") or []
    if not scenarios:
        raise ContractError(f"{path} must define benchmark.report_scenarios")
    missing = [name for name in scenarios if name not in (config.get("scenarios") or {})]
    if missing:
        raise ContractError(f"benchmark.report_scenarios contains unknown scenarios: {', '.join(missing)}")
    blocked = [
        str(name)
        for name in scenarios
        if str(config["scenarios"][name].get("benchmark_status", "supported")) != "supported"
    ]
    if blocked:
        raise ContractError(
            "benchmark.report_scenarios contains non-publishable scenarios: "
            + ", ".join(blocked)
        )
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
    if "run_mode" not in proof.columns:
        raise ContractError("publishable summary must contain run_mode")
    missing_identity = sorted(
        {"system", "policy", "repeat", "status", "telemetry_source"} - set(proof.columns)
    )
    if missing_identity:
        raise ContractError(
            "publishable summary is missing row identity fields: "
            + ", ".join(missing_identity)
        )
    unknown_statuses = sorted(
        set(proof["status"].astype(str))
        - {"planned", "completed", "skipped", "failed"}
    )
    if unknown_statuses:
        raise ContractError(
            "publishable summary contains unknown statuses: " + ", ".join(unknown_statuses)
        )
    expected_cell_key = [
        column
        for column in (
            "dataset",
            "scenario",
            "deadline_ms",
            "deployment_mode",
            "system",
            "policy",
            "repeat",
        )
        if column in proof.columns
    ]
    duplicate_cells = proof.duplicated(expected_cell_key, keep=False)
    if duplicate_cells.any():
        sample_columns = expected_cell_key + (
            ["summary_path"] if "summary_path" in proof.columns else []
        )
        sample = proof.loc[duplicate_cells, sample_columns].head(5).to_dict("records")
        raise ContractError(
            "publishable summary contains duplicate rows for one expected matrix cell; "
            f"sample={sample}"
        )
    non_benchmark = proof[proof["run_mode"].astype(str) != "benchmark"]
    if not non_benchmark.empty:
        sample = non_benchmark[["scenario", "system", "policy", "repeat", "run_mode"]].head(5).to_dict("records")
        raise ContractError(f"publishable report only accepts run_mode=benchmark rows; sample={sample}")
    completed = proof[proof["status"].astype(str) == "completed"]
    bad = completed[completed["telemetry_source"].astype(str) != "native"]
    if not bad.empty:
        sample = bad[["scenario", "system", "policy", "repeat", "telemetry_source"]].head(5).to_dict("records")
        raise ContractError(f"publishable report only accepts completed native telemetry rows; sample={sample}")
    if "topology_trace_complete" not in completed.columns:
        raise ContractError("publishable summary must contain topology_trace_complete")
    topology_complete = completed["topology_trace_complete"].astype(str).str.lower().isin({"true", "1"})
    if not topology_complete.all():
        sample = completed.loc[
            ~topology_complete,
            ["scenario", "system", "policy", "repeat", "topology_trace_complete"],
        ].head(5).to_dict("records")
        raise ContractError(f"publishable report requires complete native topology traces; sample={sample}")
    ingress_columns = {
        "ingress_ledger_complete",
        "ingress_frame_count",
        "completed_frame_count",
        "dropped_frame_count",
        "censored_frame_count",
        "ingress_censoring_rule",
    }
    missing_ingress_columns = sorted(ingress_columns - set(completed.columns))
    if missing_ingress_columns:
        raise ContractError(
            "publishable summary is missing ingress cohort fields: " + ", ".join(missing_ingress_columns)
        )
    ingress_complete = completed["ingress_ledger_complete"].astype(str).str.lower().isin({"true", "1"})
    if not ingress_complete.all():
        sample = completed.loc[
            ~ingress_complete,
            ["scenario", "system", "policy", "repeat", "ingress_ledger_complete"],
        ].head(5).to_dict("records")
        raise ContractError(f"publishable report requires a complete native ingress ledger; sample={sample}")
    ingress_count = pd.to_numeric(completed["ingress_frame_count"], errors="coerce")
    completed_count = pd.to_numeric(completed["completed_frame_count"], errors="coerce")
    dropped_count = pd.to_numeric(completed["dropped_frame_count"], errors="coerce")
    censored_count = pd.to_numeric(completed["censored_frame_count"], errors="coerce")
    invalid_balance = (
        ingress_count.isna()
        | completed_count.isna()
        | dropped_count.isna()
        | censored_count.isna()
        | (ingress_count <= 0)
        | (ingress_count != completed_count + dropped_count + censored_count)
    )
    if "frames" in completed.columns:
        invalid_balance |= pd.to_numeric(completed["frames"], errors="coerce") != completed_count
    censoring_rule = completed["ingress_censoring_rule"].astype(str).str.strip().str.lower()
    invalid_balance |= censoring_rule.isin({"", "unavailable", "none", "nan"})
    if invalid_balance.any():
        sample = completed.loc[
            invalid_balance,
            [
                "scenario",
                "system",
                "policy",
                "repeat",
                "ingress_frame_count",
                "completed_frame_count",
                "dropped_frame_count",
                "censored_frame_count",
                "ingress_censoring_rule",
            ],
        ].head(5).to_dict("records")
        raise ContractError(f"publishable report requires a closed or explicitly censored ingress balance; sample={sample}")

    branch_terminal_columns = {
        "branch_terminal_trace_complete",
        "branch_terminal_event_count",
        "native_branch_drop_event_count",
        "checkpoint_frame_aggregation_complete",
        "branch_analytics_contract_sha256",
    }
    missing_branch_terminal_columns = sorted(branch_terminal_columns - set(completed.columns))
    if missing_branch_terminal_columns:
        raise ContractError(
            "publishable summary is missing branch terminal fields: "
            + ", ".join(missing_branch_terminal_columns)
        )
    branch_terminal_complete = completed["branch_terminal_trace_complete"].astype(str).str.lower().isin(
        {"true", "1"}
    )
    frame_aggregation_complete = completed["checkpoint_frame_aggregation_complete"].astype(str).str.lower().isin(
        {"true", "1"}
    )
    branch_terminal_count = pd.to_numeric(completed["branch_terminal_event_count"], errors="coerce")
    native_branch_drop_count = pd.to_numeric(completed["native_branch_drop_event_count"], errors="coerce")
    branch_analytics_hash = completed["branch_analytics_contract_sha256"].astype(str).str.strip()
    invalid_branch_terminals = (
        ~branch_terminal_complete
        | ~frame_aggregation_complete
        | branch_terminal_count.isna()
        | (branch_terminal_count <= 0)
        | native_branch_drop_count.isna()
        | (native_branch_drop_count < dropped_count)
        | ~branch_analytics_hash.str.fullmatch(r"[0-9a-f]{64}", na=False)
    )
    if invalid_branch_terminals.any():
        sample = completed.loc[
            invalid_branch_terminals,
            [
                "scenario",
                "system",
                "policy",
                "repeat",
                "branch_terminal_trace_complete",
                "branch_terminal_event_count",
                "native_branch_drop_event_count",
                "checkpoint_frame_aggregation_complete",
                "branch_analytics_contract_sha256",
            ],
        ].head(5).to_dict("records")
        raise ContractError(f"publishable report requires complete native branch terminal traces; sample={sample}")

    semantic_columns = {
        "stage_semantic_contract_complete",
        "semantic_contract_version",
        "semantic_prefix_contract_sha256",
    }
    missing_semantic_columns = sorted(semantic_columns - set(completed.columns))
    if missing_semantic_columns:
        raise ContractError(
            "publishable summary is missing stage semantic contract fields: "
            + ", ".join(missing_semantic_columns)
        )
    semantic_complete = completed["stage_semantic_contract_complete"].astype(str).str.lower().isin({"true", "1"})
    semantic_version = pd.to_numeric(completed["semantic_contract_version"], errors="coerce")
    semantic_hash = completed["semantic_prefix_contract_sha256"].astype(str).str.strip()
    valid_hash = semantic_hash.str.fullmatch(r"[0-9a-f]{64}", na=False)
    invalid_semantic = (
        ~semantic_complete
        | (semantic_version != STAGE_SEMANTIC_CONTRACT_VERSION)
        | ~valid_hash
    )
    if invalid_semantic.any():
        sample = completed.loc[
            invalid_semantic,
            [
                "scenario",
                "system",
                "policy",
                "repeat",
                "stage_semantic_contract_complete",
                "semantic_contract_version",
                "semantic_prefix_contract_sha256",
            ],
        ].head(5).to_dict("records")
        raise ContractError(
            "publishable report requires complete stage semantic contract "
            f"v{STAGE_SEMANTIC_CONTRACT_VERSION} metadata; sample={sample}"
        )

    measurement_columns = {
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
    missing_measurement_columns = sorted(measurement_columns - set(completed.columns))
    if missing_measurement_columns:
        raise ContractError(
            "publishable summary is missing measurement passport fields: "
            + ", ".join(missing_measurement_columns)
        )
    attribution_complete = completed["resource_attribution_complete"].astype(str).str.lower().isin(
        {"true", "1"}
    )
    attribution = completed["resource_attribution"].astype(str).str.strip()
    attributed_ingress = pd.to_numeric(completed["resource_attributed_ingress_count"], errors="coerce")
    unattributed_events = pd.to_numeric(completed["resource_unattributed_event_count"], errors="coerce")
    schedule_hash = completed["input_schedule_sha256"].astype(str).str.strip()
    sequence_hash = completed["input_frame_key_sequence_sha256"].astype(str).str.strip()
    measurement_signature = completed["measurement_signature"].astype(str).str.strip()
    measurement_window = pd.to_numeric(completed["measurement_window_duration_ms"], errors="coerce")
    c_obs_total = pd.to_numeric(completed["c_obs_total_ms"], errors="coerce")
    c_obs_cpu_total = pd.to_numeric(completed["c_obs_cpu_total_ms"], errors="coerce")
    c_obs_gpu_total = pd.to_numeric(completed["c_obs_gpu_total_ms"], errors="coerce")
    c_obs_in = pd.to_numeric(completed["c_obs_in_ms_per_ingress"], errors="coerce")
    c_obs_cpu_in = pd.to_numeric(
        completed["c_obs_cpu_in_ms_per_ingress"], errors="coerce"
    )
    c_obs_gpu_in = pd.to_numeric(
        completed["c_obs_gpu_in_ms_per_ingress"], errors="coerce"
    )
    c_obs_comp = pd.to_numeric(completed["c_obs_comp_ms_per_completed"], errors="coerce")
    component_total_matches = np.isclose(
        c_obs_total,
        c_obs_cpu_total + c_obs_gpu_total,
        rtol=1.0e-9,
        atol=1.0e-6,
    )
    component_ingress_matches = np.isclose(
        c_obs_in,
        c_obs_cpu_in + c_obs_gpu_in,
        rtol=1.0e-9,
        atol=1.0e-6,
    )
    valid_hashes = (
        schedule_hash.str.fullmatch(r"[0-9a-f]{64}", na=False)
        & sequence_hash.str.fullmatch(r"[0-9a-f]{64}", na=False)
        & measurement_signature.str.fullmatch(r"[0-9a-f]{64}", na=False)
    )
    invalid_measurement = (
        ~attribution_complete
        | attribution.isin({"", "unavailable", "none", "nan"})
        | attributed_ingress.isna()
        | (attributed_ingress != ingress_count)
        | (censored_count != 0)
        | unattributed_events.isna()
        | (unattributed_events != 0)
        | ~valid_hashes
        | measurement_window.isna()
        | (measurement_window <= 0)
        | c_obs_total.isna()
        | (c_obs_total <= 0)
        | c_obs_cpu_total.isna()
        | (c_obs_cpu_total < 0)
        | c_obs_gpu_total.isna()
        | (c_obs_gpu_total < 0)
        | c_obs_in.isna()
        | (c_obs_in <= 0)
        | c_obs_cpu_in.isna()
        | (c_obs_cpu_in < 0)
        | c_obs_gpu_in.isna()
        | (c_obs_gpu_in < 0)
        | c_obs_comp.isna()
        | (c_obs_comp <= 0)
        | ~component_total_matches
        | ~component_ingress_matches
    )
    for index, row in completed.iterrows():
        payload_valid = measurement_signature_identity_is_valid(
            row["measurement_signature_payload_json"],
            row["measurement_signature"],
            resource_attribution=str(row["resource_attribution"]),
        )
        if not payload_valid:
            invalid_measurement.loc[index] = True
    if invalid_measurement.any():
        sample = completed.loc[
            invalid_measurement,
            [
                "scenario",
                "system",
                "policy",
                "repeat",
                "resource_attribution_complete",
                "resource_attributed_ingress_count",
                "resource_unattributed_event_count",
                "measurement_signature",
                "c_obs_in_ms_per_ingress",
            ],
        ].head(5).to_dict("records")
        raise ContractError(f"publishable report requires a complete native measurement passport; sample={sample}")
    if {BASELINE_SCENARIO, SHARED_SCENARIO}.issubset(set(scenarios)):
        pair_rows = completed[
            completed["scenario"].astype(str).isin({BASELINE_SCENARIO, SHARED_SCENARIO})
        ].copy()
        pair_key = [
            column
            for column in (
                "system",
                "policy",
                "dataset",
                "deadline_ms",
                "streams",
                "scenario_variant",
                "repeat",
            )
            if column in pair_rows.columns
        ]
        for _, group in pair_rows.groupby(pair_key, dropna=False):
            if set(group["scenario"].astype(str)) != {BASELINE_SCENARIO, SHARED_SCENARIO}:
                continue
            rules = set(group["ingress_censoring_rule"].astype(str))
            if len(rules) != 1:
                sample = group[
                    ["scenario", "system", "policy", "repeat", "ingress_censoring_rule"]
                ].to_dict("records")
                raise ContractError(
                    f"paired baseline/shared rows must use one ingress censoring rule; sample={sample}"
                )
            prefix_hashes = set(group["semantic_prefix_contract_sha256"].astype(str))
            if len(prefix_hashes) != 1:
                sample = group[
                    ["scenario", "system", "policy", "repeat", "semantic_prefix_contract_sha256"]
                ].to_dict("records")
                raise ContractError(
                    "paired baseline/shared rows must use one semantic prefix contract; "
                    f"sample={sample}"
                )
            pair_fields = {
                "input_schedule_sha256": "one native input schedule",
                "input_frame_key_sequence_sha256": "one ordered input-frame-key sequence",
                "measurement_window_duration_ms": "one measurement window",
                "resource_attribution": "one resource attribution rule",
                "measurement_signature": "one measurement signature",
                "branch_analytics_contract_sha256": "one branch analytics contract",
            }
            for field, description in pair_fields.items():
                if group[field].nunique(dropna=False) != 1:
                    sample = group[["scenario", "system", "policy", "repeat", field]].to_dict("records")
                    raise ContractError(f"paired baseline/shared rows must use {description}; sample={sample}")


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
        & (df["run_mode"].astype(str) == "benchmark")
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


_EXPECTED_MATRIX_KEY_COLUMNS = (
    "dataset",
    "scenario",
    "deadline_ms",
    "deployment_mode",
    "host_topology",
    "system",
    "policy",
    "repeat",
)


def _expected_matrix_key(row: pd.Series, *, source: str) -> tuple[Any, ...]:
    missing = [column for column in _EXPECTED_MATRIX_KEY_COLUMNS if column not in row]
    if missing:
        raise ContractError(
            f"{source} is missing expected-matrix fields: " + ", ".join(missing)
        )
    try:
        deadline = float(row["deadline_ms"])
        repeat_value = float(row["repeat"])
        repeat = int(repeat_value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{source} has non-numeric deadline_ms or repeat") from exc
    if not math.isfinite(deadline) or not math.isfinite(repeat_value) or repeat_value != repeat:
        raise ContractError(f"{source} has non-finite deadline_ms or non-integer repeat")
    string_values = []
    for column in (
        "dataset",
        "scenario",
        "deployment_mode",
        "host_topology",
        "system",
        "policy",
    ):
        value = row[column]
        if pd.isna(value) or (column != "dataset" and not str(value).strip()):
            raise ContractError(f"{source} has an empty expected-matrix field: {column}")
        string_values.append(str(value))
    return (
        string_values[0],
        string_values[1],
        deadline,
        string_values[2],
        string_values[3],
        string_values[4],
        string_values[5],
        repeat,
    )


def validate_report_matrix_membership(
    df: pd.DataFrame,
    config: dict[str, Any],
    repeats: int,
) -> None:
    """Reject rows outside the frozen broad-report matrix; missing cells remain auditable."""
    scenarios = set(report_scenarios(config))
    observed = set(df.get("scenario", pd.Series(dtype=str)).astype(str))
    unexpected_scenarios = sorted(observed - scenarios)
    if unexpected_scenarios:
        raise ContractError(
            "publishable summary contains non-report scenarios: "
            + ", ".join(unexpected_scenarios)
        )
    expected = expected_matrix(config, repeats)
    if expected.empty:
        raise ContractError("expected publishable matrix is empty")
    expected_keys = {
        _expected_matrix_key(row, source="expected matrix")
        for _, row in expected.iterrows()
    }
    unexpected_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        key = _expected_matrix_key(row, source="publishable summary")
        if key not in expected_keys:
            unexpected_rows.append(
                {
                    column: row[column]
                    for column in _EXPECTED_MATRIX_KEY_COLUMNS
                }
            )
            if len(unexpected_rows) >= 5:
                break
    if unexpected_rows:
        raise ContractError(
            "publishable summary contains rows outside the expected matrix; "
            f"sample={unexpected_rows}"
        )


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


_RUN_METADATA_IDENTITY_FIELDS = (
    "system",
    "scenario",
    "repeat",
    "streams",
    "duration_s",
    "scenario_variant",
    "deployment_mode",
    "host_topology",
    "policy",
    "dataset",
    "deadline_ms",
    "seed",
    "run_seed",
    "status",
    "run_mode",
    "telemetry_source",
)
_RUN_METADATA_NUMERIC_FIELDS = {
    "repeat",
    "streams",
    "duration_s",
    "deadline_ms",
    "seed",
    "run_seed",
}


def _run_metadata_values_match(field: str, left: Any, right: Any) -> bool:
    if field in _RUN_METADATA_NUMERIC_FIELDS:
        try:
            return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1.0e-9)
        except (TypeError, ValueError):
            return False
    return str(left) == str(right)


def _configured_report_dataset(
    config: dict[str, Any],
    dataset_name: str,
) -> dict[str, Any] | None:
    manifest_value = str(
        ((config.get("benchmark") or {}).get("dataset_manifest") or "")
    ).strip()
    if not manifest_value:
        return None
    manifest_path = Path(manifest_value)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    return load_dataset(
        manifest_path,
        dataset_name,
        mode="benchmark",
        project_root=ROOT,
        require_files=False,
    )


def _configured_report_scenario(
    config: dict[str, Any],
    scenario_name: str,
    variant_name: str,
) -> dict[str, Any] | None:
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        return None
    raw_scenario = scenarios.get(scenario_name)
    if not isinstance(raw_scenario, dict):
        raise ContractError(
            f"publication metadata references unknown scenario: {scenario_name}"
        )
    return resolve_scenario_contract(
        scenario_name,
        raw_scenario,
        variant_name=variant_name,
    )


def validate_run_metadata_identity(
    run_dir: Path,
    row: pd.Series,
    *,
    expected_mode: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cross-check summary identity against the per-run metadata copy."""
    metadata_path = run_dir / "run_metadata.json"
    try:
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read publication metadata {metadata_path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ContractError(f"publication metadata must be a mapping: {metadata_path}")
    if metadata.get("schema_version") != 2:
        raise ContractError(f"publication metadata must use schema_version=2: {metadata_path}")
    result = metadata.get("result")
    if not isinstance(result, dict):
        raise ContractError(f"publication metadata must contain a result mapping: {metadata_path}")

    mismatches: list[str] = []
    metadata_mode = metadata.get("mode")
    result_mode = result.get("run_mode")
    summary_mode = row.get("run_mode")
    if metadata_mode != expected_mode:
        mismatches.append("metadata.mode")
    if result_mode != expected_mode:
        mismatches.append("result.run_mode")
    if summary_mode != expected_mode:
        mismatches.append("summary.run_mode")
    if metadata_mode != result_mode or result_mode != summary_mode:
        mismatches.append("mode_consistency")

    for field in _RUN_METADATA_IDENTITY_FIELDS:
        if field not in row or field not in result:
            mismatches.append(field)
            continue
        row_value = row[field]
        if pd.isna(row_value):
            if field == "scenario_variant":
                row_value = ""
            else:
                mismatches.append(field)
                continue
        if not _run_metadata_values_match(field, row_value, result[field]):
            mismatches.append(field)

    top_level_values = {
        "run_seed": metadata.get("run_seed"),
        "policy": metadata.get("policy"),
        "dataset": (
            metadata.get("dataset", {}).get("name")
            if isinstance(metadata.get("dataset"), dict)
            else None
        ),
    }
    for field, value in top_level_values.items():
        result_value = result.get(field)
        if value is None or result_value is None or not _run_metadata_values_match(
            field, value, result_value
        ):
            mismatches.append(f"metadata.{field}")

    configured_scenario = _configured_report_scenario(
        config or {},
        str(result.get("scenario", "")),
        str(result.get("scenario_variant", "") or ""),
    )
    if configured_scenario is not None:
        expected_scenario_identity = scenario_contract_identity(configured_scenario)
        metadata_scenario = metadata.get("resolved_scenario")
        declared_scenario_identity = metadata.get("scenario_contract_identity")
        if not isinstance(metadata_scenario, dict):
            mismatches.append("metadata.resolved_scenario")
        elif (
            scenario_contract_identity(metadata_scenario)["sha256"]
            != expected_scenario_identity["sha256"]
        ):
            mismatches.append("metadata.scenario_contract_identity")
        if not isinstance(declared_scenario_identity, dict):
            mismatches.append("metadata.scenario_contract_identity_declared")
        else:
            if (
                declared_scenario_identity.get("schema_version")
                != expected_scenario_identity["schema_version"]
            ):
                mismatches.append(
                    "metadata.scenario_contract_identity_schema_version"
                )
            if (
                declared_scenario_identity.get("sha256")
                != expected_scenario_identity["sha256"]
            ):
                mismatches.append("metadata.scenario_contract_identity_declared")
        if bool(configured_scenario.get("topology")):
            expected_evidence_scope = resolve_publication_evidence_bundle_scope(
                config or {},
                result,
            )
            try:
                validate_publication_evidence_bundle(
                    run_dir,
                    metadata.get("publication_evidence_bundle"),
                    metadata.get("publication_evidence_bundle_identity"),
                    expected_scope=expected_evidence_scope,
                )
            except ContractError as exc:
                mismatches.append(f"metadata.publication_evidence_bundle:{exc}")

    configured_dataset = _configured_report_dataset(
        config or {},
        str(result.get("dataset", "")),
    )
    if configured_dataset is not None:
        metadata_dataset = metadata.get("dataset")
        expected_identity = dataset_manifest_identity(configured_dataset)
        if not isinstance(metadata_dataset, dict):
            mismatches.append("metadata.dataset_manifest")
        else:
            metadata_identity = dataset_manifest_identity(metadata_dataset)
            if (
                metadata_dataset.get("manifest_identity_schema_version")
                != expected_identity["schema_version"]
            ):
                mismatches.append("metadata.dataset_manifest_identity_schema_version")
            if (
                metadata_dataset.get("manifest_identity_sha256")
                != expected_identity["sha256"]
            ):
                mismatches.append("metadata.dataset_manifest_identity_declared")
            if metadata_identity["sha256"] != expected_identity["sha256"]:
                mismatches.append("metadata.dataset_manifest_identity")
            if metadata_dataset.get("aggregate_sha256") != configured_dataset.get(
                "aggregate_sha256"
            ):
                mismatches.append("metadata.dataset_aggregate_sha256")

    configured_systems = (config or {}).get("systems")
    if isinstance(configured_systems, dict) and configured_systems:
        expected_publication_contract = resolve_publication_run_contract(
            config or {},
            result,
        )
        expected_publication_identity = publication_run_contract_identity(
            expected_publication_contract
        )
        metadata_publication_contract = metadata.get("publication_run_contract")
        declared_publication_identity = metadata.get(
            "publication_run_contract_identity"
        )
        if not isinstance(metadata_publication_contract, dict):
            mismatches.append("metadata.publication_run_contract")
        elif (
            publication_run_contract_identity(metadata_publication_contract)[
                "sha256"
            ]
            != expected_publication_identity["sha256"]
        ):
            mismatches.append("metadata.publication_run_contract_identity")
        if not isinstance(declared_publication_identity, dict):
            mismatches.append("metadata.publication_run_contract_identity_declared")
        else:
            if (
                declared_publication_identity.get("schema_version")
                != expected_publication_identity["schema_version"]
            ):
                mismatches.append(
                    "metadata.publication_run_contract_identity_schema_version"
                )
            if (
                declared_publication_identity.get("sha256")
                != expected_publication_identity["sha256"]
            ):
                mismatches.append(
                    "metadata.publication_run_contract_identity_declared"
                )

    configured_hardware_target = dict((config or {}).get("hardware_target") or {})
    if configured_hardware_target:
        metadata_hardware_target = metadata.get("hardware_target")
        detected_hardware = metadata.get("detected_hardware")
        if not isinstance(metadata_hardware_target, dict):
            mismatches.append("metadata.hardware_target")
        elif metadata_hardware_target != configured_hardware_target:
            mismatches.append("metadata.hardware_target_config_drift")
        if not isinstance(detected_hardware, dict):
            mismatches.append("metadata.detected_hardware")
        elif isinstance(metadata_hardware_target, dict):
            hardware_assessment = assess_hardware_target(
                configured_hardware_target,
                detected_hardware,
            )
            mismatches.extend(
                f"hardware_target:{value}"
                for value in hardware_assessment["blockers"]
            )

    if mismatches:
        raise ContractError(
            f"run_metadata.json does not match the publication summary at {metadata_path}: "
            + ", ".join(dict.fromkeys(mismatches))
        )
    return metadata


def completed_native_rows(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    required = {"scenario", "status", "run_mode", "telemetry_source"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ContractError("publishable summary is missing row provenance fields: " + ", ".join(missing))
    return df[
        (df["scenario"].astype(str).isin(report_scenarios(config)))
        & (df["status"].astype(str) == "completed")
        & (df["run_mode"].astype(str) == "benchmark")
        & (df["telemetry_source"].astype(str) == "native")
    ].copy()


def validate_completed_run_metadata(
    run_root: Path,
    df: pd.DataFrame,
    config: dict[str, Any],
) -> None:
    """Require consistent per-run metadata for every completed proof row."""
    for _, row in completed_native_rows(df, config).iterrows():
        run_dir = run_dir_for_row(run_root, row)
        validate_run_metadata_identity(
            run_dir,
            row,
            expected_mode="benchmark",
            config=config,
        )


def validate_completed_run_artifacts(
    run_root: Path,
    df: pd.DataFrame,
    config: dict[str, Any],
) -> None:
    """Revalidate every completed proof run before broad report output."""
    for _, row in completed_native_rows(df, config).iterrows():
        evidence = _validated_publication_run_artifacts(
            run_root,
            row,
            config,
            validate_metadata=False,
        )
        mismatches = _primary_summary_raw_mismatches(row, evidence["raw_summary"])
        if mismatches:
            raise ContractError(
                "publication summary differs from accepted raw sidecars at "
                f"{evidence['run_dir']}: "
                + ", ".join(mismatches)
            )


def build_measurement_passports(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    completed = completed_native_rows(df, config)
    missing = [column for column in MEASUREMENT_PASSPORT_COLUMNS if column not in completed.columns]
    if missing:
        raise ContractError("measurement passport export is missing fields: " + ", ".join(missing))
    return completed[MEASUREMENT_PASSPORT_COLUMNS].sort_values(
        ["dataset", "system", "policy", "repeat", "scenario"],
        kind="stable",
    )


def _truthy(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1"}


_PRIMARY_RAW_BOOLEAN_FIELDS = {
    "topology_trace_complete",
    "ingress_ledger_complete",
    "ingress_cohort_closed",
    "branch_terminal_trace_complete",
    "checkpoint_frame_aggregation_complete",
    "stage_semantic_contract_complete",
    "decoder_placement_verified",
    "decoder_factory_identity_complete",
    "decoder_factory_allowed",
    "resource_attribution_complete",
    "reset_state_verified",
    "c_obs_is_partial",
}
_PRIMARY_RAW_NUMERIC_FIELDS = {
    "measurement_window_duration_ms",
    "ingress_frame_count",
    "completed_frame_count",
    "dropped_frame_count",
    "censored_frame_count",
    "branch_terminal_event_count",
    "native_branch_drop_event_count",
    "resource_attributed_ingress_count",
    "resource_unattributed_event_count",
    "c_obs_total_ms",
    "c_obs_cpu_total_ms",
    "c_obs_gpu_total_ms",
    "c_obs_in_ms_per_ingress",
    "c_obs_cpu_in_ms_per_ingress",
    "c_obs_gpu_in_ms_per_ingress",
    "c_obs_comp_ms_per_completed",
    "semantic_contract_version",
    "decoder_placement_contract_version",
    "reset_contract_version",
}


def _primary_summary_raw_mismatches(row: pd.Series, raw: dict[str, Any]) -> list[str]:
    """Return pair-critical summary fields that differ from raw-sidecar derivation."""
    mismatches: list[str] = []
    for field, expected in raw.items():
        if field not in row or pd.isna(row[field]):
            mismatches.append(field)
            continue
        observed = row[field]
        if field in _PRIMARY_RAW_BOOLEAN_FIELDS:
            matches = _truthy(observed) == bool(expected)
        elif field in _PRIMARY_RAW_NUMERIC_FIELDS:
            try:
                matches = math.isclose(
                    float(observed),
                    float(expected),
                    rel_tol=1.0e-9,
                    abs_tol=1.0e-9,
                )
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(observed) == str(expected)
        if not matches:
            mismatches.append(field)
    return mismatches


def _native_frame_keys(df: pd.DataFrame) -> set[tuple[str, str, int, int]]:
    return {
        (str(row.run_id), str(row.trace_id), int(row.stream_id), int(row.frame_id))
        for row in df[["run_id", "trace_id", "stream_id", "frame_id"]].itertuples(index=False)
    }


def _primary_architecture_rows(summary: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    primary = validate_primary_architecture_contrast(config)
    rows = completed_native_rows(summary, config)
    deadline = pd.to_numeric(rows.get("deadline_ms"), errors="coerce")
    streams = pd.to_numeric(rows.get("streams"), errors="coerce")
    return rows[
        rows["scenario"].astype(str).isin(
            {str(primary["baseline_scenario"]), str(primary["shared_scenario"])}
        )
        & (rows["system"].astype(str) == str(primary["system"]))
        & (rows["policy"].astype(str) == str(primary["policy"]))
        & (rows["dataset"].astype(str) == str(primary["dataset"]))
        & np.isclose(deadline, float(primary["deadline_ms"]), rtol=0.0, atol=1.0e-9)
        & (streams == int(primary["streams"]))
    ].copy()


def _validated_publication_run_artifacts(
    run_root: Path,
    row: pd.Series,
    config: dict[str, Any],
    *,
    validate_metadata: bool = True,
) -> dict[str, Any]:
    run_dir = run_dir_for_row(run_root, row)
    metadata: dict[str, Any] | None = None
    if validate_metadata:
        metadata = validate_run_metadata_identity(
            run_dir,
            row,
            expected_mode="benchmark",
            config=config,
        )
    frames = canonicalize_frames_csv(
        run_dir / "frames.csv",
        mode="benchmark",
        run_id="",
        detector="",
        backend="",
    )
    scenario_name = str(row["scenario"])
    scenario = (config.get("scenarios") or {}).get(scenario_name)
    if not isinstance(scenario, dict):
        raise ContractError(f"publication report references unknown scenario: {scenario_name}")
    topology = scenario.get("topology")
    if not isinstance(topology, dict):
        raise ContractError(f"publication scenario has no topology contract: {scenario_name}")
    topology_kind = str(topology.get("kind", "")).strip()
    required_branches = topology.get("required_branches")
    if topology_kind not in {"independent_processes", "shared_video_dag"}:
        raise ContractError(
            f"publication scenario has unsupported topology kind {topology_kind!r}: {scenario_name}"
        )
    if not isinstance(required_branches, list) or not required_branches:
        raise ContractError(f"publication scenario has no required topology branches: {scenario_name}")
    try:
        expected_streams = int(row["streams"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"publication summary has invalid streams for {scenario_name}") from exc
    events = validate_frame_events(run_dir / "frame_events.csv").copy()
    topology_events = validate_topology_events(
        run_dir / "topology_events.csv",
        frames=frames,
        frame_events=events,
        scenario=scenario,
    )
    sidecars = validate_required_sidecars(
        run_dir,
        require_labeled_provenance=True,
        require_ingress_ledger=True,
        require_branch_terminals=True,
        require_stage_contracts=True,
        require_reset_evidence=True,
        required_branches=required_branches,
        topology_kind=topology_kind,
        expected_streams=expected_streams,
        frames=frames,
        topology_events=topology_events,
    )
    ingress = sidecars["ingress_ledger"]
    branch_terminals = sidecars["branch_terminals"]
    stage_contracts = sidecars["stage_contracts"]
    reset_evidence = sidecars["reset_evidence"]
    passport = summarize_measurement_passport(
        sidecars["resource_events"],
        ingress,
        events,
    )
    semantic_prefix_hash = semantic_prefix_contract_sha256(stage_contracts)
    configured_primary = (config.get("benchmark") or {}).get("primary_architecture_contrast")
    decoder_placement = (
        assess_decoder_placement(
            stage_contracts,
            validate_primary_architecture_contrast(config)["decoder_placement"],
        )
        if isinstance(configured_primary, dict)
        else {}
    )
    branch_analytics_hash = branch_analytics_contract_sha256(branch_terminals)
    reset_tokens_json = json.dumps(
        sorted(set(reset_evidence["process_start_token"].astype(str))),
        separators=(",", ":"),
    )
    reset_sink_id = str(reset_evidence["telemetry_sink_id"].iloc[0])

    statuses = ingress["terminal_status"].astype(str)
    branch_statuses = branch_terminals["terminal_status"].astype(str)
    raw_summary = {
        "topology_trace_complete": True,
        "ingress_ledger_complete": bool(ingress["ingress_claim_eligible"].all()),
        "ingress_cohort_closed": bool((statuses != "censored").all()),
        "branch_terminal_trace_complete": bool(
            branch_terminals["branch_terminal_claim_eligible"].all()
        ),
        "branch_terminal_event_count": int(branch_terminals.shape[0]),
        "native_branch_drop_event_count": int((branch_statuses == "drop").sum()),
        "checkpoint_frame_aggregation_complete": bool(
            branch_terminals["branch_terminal_claim_eligible"].all()
        ),
        "stage_semantic_contract_complete": bool(
            stage_contracts["semantic_contract_claim_eligible"].all()
        ),
        "resource_attribution_complete": bool(passport["resource_attribution_complete"]),
        "resource_attributed_ingress_count": int(passport["resource_attributed_ingress_count"]),
        "resource_unattributed_event_count": int(passport["resource_unattributed_event_count"]),
        "reset_state_verified": bool(reset_evidence["reset_claim_eligible"].all()),
        "input_schedule_sha256": passport["input_schedule_sha256"],
        "input_frame_key_sequence_sha256": passport["input_frame_key_sequence_sha256"],
        "measurement_window_duration_ms": passport["measurement_window_duration_ms"],
        "ingress_censoring_rule": str(ingress["censoring_rule"].iloc[0]),
        "resource_attribution": passport["resource_attribution"],
        "measurement_signature": passport["measurement_signature"],
        "measurement_signature_payload_json": passport["measurement_signature_payload_json"],
        "ingress_frame_count": int(ingress.shape[0]),
        "completed_frame_count": int((statuses == "completed").sum()),
        "dropped_frame_count": int((statuses == "drop").sum()),
        "censored_frame_count": int((statuses == "censored").sum()),
        "c_obs_total_ms": passport["c_obs_total_ms"],
        "c_obs_cpu_total_ms": passport["c_obs_cpu_total_ms"],
        "c_obs_gpu_total_ms": passport["c_obs_gpu_total_ms"],
        "c_obs_in_ms_per_ingress": passport["c_obs_in_ms_per_ingress"],
        "c_obs_cpu_in_ms_per_ingress": passport["c_obs_cpu_in_ms_per_ingress"],
        "c_obs_gpu_in_ms_per_ingress": passport["c_obs_gpu_in_ms_per_ingress"],
        "c_obs_comp_ms_per_completed": passport["c_obs_comp_ms_per_completed"],
        "c_obs_is_partial": passport["c_obs_is_partial"],
        "semantic_contract_version": int(
            pd.to_numeric(stage_contracts["semantic_contract_version"], errors="raise").iloc[0]
        ),
        "semantic_prefix_contract_sha256": semantic_prefix_hash,
        **decoder_placement,
        "branch_analytics_contract_sha256": branch_analytics_hash,
        "reset_contract_version": int(
            pd.to_numeric(reset_evidence["reset_contract_version"], errors="raise").iloc[0]
        ),
        "reset_process_start_tokens_json": reset_tokens_json,
        "reset_telemetry_sink_id": reset_sink_id,
    }
    return {
        "run_dir": run_dir,
        "frames": frames,
        "events": events,
        "topology_events": topology_events,
        "sidecars": sidecars,
        "raw_summary": raw_summary,
        "metadata": metadata,
    }


def _primary_run_metric(
    run_root: Path,
    row: pd.Series,
    primary: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    evidence = _validated_publication_run_artifacts(run_root, row, config)
    run_dir = evidence["run_dir"]
    frames = evidence["frames"]
    events = evidence["events"]
    sidecars = evidence["sidecars"]
    raw_summary = evidence["raw_summary"]
    metadata = evidence["metadata"] or {}
    ingress = sidecars["ingress_ledger"]
    branch_terminals = sidecars["branch_terminals"]
    passport = summarize_measurement_passport(
        sidecars["resource_events"],
        ingress,
        events,
    )
    semantic_prefix_hash = str(raw_summary["semantic_prefix_contract_sha256"])
    decoder_factory = str(raw_summary["decoder_factory"])
    branch_analytics_hash = str(raw_summary["branch_analytics_contract_sha256"])
    reset_tokens_json = str(raw_summary["reset_process_start_tokens_json"])
    reset_sink_id = str(raw_summary["reset_telemetry_sink_id"])
    summary_raw_mismatches = _primary_summary_raw_mismatches(row, raw_summary)
    statuses = ingress["terminal_status"].astype(str)

    completed_ingress = ingress[ingress["terminal_status"].astype(str) == "completed"].copy()
    completed_keys = _native_frame_keys(completed_ingress)
    events["base_stage"] = events["stage"].astype(str).map(stage_base_name)
    events["frame_key"] = list(
        zip(
            events["run_id"].astype(str),
            events["trace_id"].astype(str),
            pd.to_numeric(events["stream_id"], errors="raise").astype(int),
            pd.to_numeric(events["frame_id"], errors="raise").astype(int),
            strict=True,
        )
    )
    proof_events = events[
        events["base_stage"].isin(PROOF_BASE_STAGES) & events["frame_key"].isin(completed_keys)
    ].copy()
    completed_count = len(completed_keys)
    event_factors: dict[str, float] = {}
    event_coverage_complete = completed_count > 0
    for stage in PROOF_BASE_STAGES:
        stage_events = proof_events[proof_events["base_stage"] == stage]
        covered = set(stage_events["frame_key"])
        event_coverage_complete &= covered == completed_keys
        event_factors[stage] = (
            float(stage_events.shape[0]) / float(completed_count) if completed_count > 0 else math.nan
        )

    ingress_stream_counts = ingress.groupby("stream_id", dropna=False).size()
    completed_stream_counts = completed_ingress.groupby("stream_id", dropna=False).size()
    expected_stream_count = int(primary["streams"])
    positive_ingress_per_stream = (
        len(ingress_stream_counts) == expected_stream_count and bool((ingress_stream_counts > 0).all())
    )
    positive_completed_per_stream = (
        set(completed_stream_counts.index) == set(ingress_stream_counts.index)
        and bool((completed_stream_counts > 0).all())
    )

    latency = frames.copy()
    latency["e2e_latency_ms"] = pd.to_numeric(latency["e2e_latency_ms"], errors="raise")
    per_stream_v = latency.groupby("stream_id", dropna=False)["e2e_latency_ms"].apply(
        lambda values: float((values > float(primary["deadline_ms"])).mean() * 100.0)
    )
    vmax = float(per_stream_v.max()) if not per_stream_v.empty else math.nan

    terminal = ingress.assign(is_drop=statuses.eq("drop"))
    per_stream_drop = terminal.groupby("stream_id", dropna=False)["is_drop"].mean() * 100.0
    drop_max = float(per_stream_drop.max()) if not per_stream_drop.empty else math.nan
    censored_count = int((statuses == "censored").sum())

    row_gates = {
        "topology_trace_complete": raw_summary["topology_trace_complete"],
        "ingress_ledger_complete": raw_summary["ingress_ledger_complete"],
        "branch_terminal_trace_complete": raw_summary["branch_terminal_trace_complete"],
        "stage_semantic_contract_complete": raw_summary["stage_semantic_contract_complete"],
        "decoder_placement_verified": raw_summary["decoder_placement_verified"],
        "resource_attribution_complete": raw_summary["resource_attribution_complete"],
        "reset_state_verified": raw_summary["reset_state_verified"],
        "summary_matches_raw_native_sidecars": not summary_raw_mismatches,
        "positive_ingress_frames_per_stream": positive_ingress_per_stream,
        "positive_completed_frames_per_stream": positive_completed_per_stream,
        "completed_cohort_event_coverage": bool(event_coverage_complete),
        "zero_censored_frames": censored_count == 0,
    }
    blockers = sorted(name for name, passed in row_gates.items() if not passed)
    blockers.extend(f"summary_raw_mismatch:{field}" for field in summary_raw_mismatches)
    pair_metadata = metadata.get("primary_architecture_pair")
    if not isinstance(pair_metadata, dict):
        pair_metadata = {}
    return {
        "scenario": str(row["scenario"]),
        "system": str(row["system"]),
        "policy": str(row["policy"]),
        "dataset": str(row["dataset"]),
        "deadline_ms": float(row["deadline_ms"]),
        "streams": int(row["streams"]),
        "repeat": int(row["repeat"]),
        "seed": int(row["seed"]) if "seed" in row and not pd.isna(row["seed"]) else math.nan,
        "run_seed": int(row["run_seed"]) if "run_seed" in row and not pd.isna(row["run_seed"]) else math.nan,
        "input_schedule_sha256": str(passport["input_schedule_sha256"]),
        "input_frame_key_sequence_sha256": str(passport["input_frame_key_sequence_sha256"]),
        "measurement_window_duration_ms": float(passport["measurement_window_duration_ms"]),
        "drain_rule": str(ingress["censoring_rule"].iloc[0]),
        "resource_attribution": str(passport["resource_attribution"]),
        "measurement_signature": str(passport["measurement_signature"]),
        "semantic_prefix_contract_sha256": semantic_prefix_hash,
        "decoder_factory": decoder_factory,
        "branch_analytics_contract_sha256": branch_analytics_hash,
        "reset_process_start_tokens_json": reset_tokens_json,
        "reset_telemetry_sink_id": reset_sink_id,
        "c_obs_in_ms_per_ingress": float(passport["c_obs_in_ms_per_ingress"]),
        "c_obs_cpu_in_ms_per_ingress": float(
            passport["c_obs_cpu_in_ms_per_ingress"]
        ),
        "c_obs_gpu_in_ms_per_ingress": float(
            passport["c_obs_gpu_in_ms_per_ingress"]
        ),
        "c_obs_is_partial": bool(passport["c_obs_is_partial"]),
        "pair_contract_version": pair_metadata.get("contract_version", math.nan),
        "pair_order_strategy": str(pair_metadata.get("strategy", "")),
        "pair_repeat": pair_metadata.get("repeat", math.nan),
        "pair_first_arm": str(pair_metadata.get("first_arm", "")),
        "pair_arm_position": pair_metadata.get("arm_position", math.nan),
        "pair_second_arm": str(pair_metadata.get("second_arm", "")),
        "event_factor_decode": event_factors["decode"],
        "event_factor_preprocess": event_factors["preprocess"],
        "vmax_completed_slo_violation_rate_percent": vmax,
        "drop_max_ingress_rate_percent": drop_max,
        "ingress_frame_count": int(ingress.shape[0]),
        "completed_frame_count": completed_count,
        "dropped_frame_count": int(ingress["terminal_status"].astype(str).eq("drop").sum()),
        "censored_frame_count": censored_count,
        "run_gate_pass": not blockers,
        "run_gate_blockers": ";".join(blockers),
        "run_dir": str(run_dir.relative_to(run_root)),
    }


def build_primary_architecture_run_metrics(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    primary = validate_primary_architecture_contrast(config)
    rows = [
        _primary_run_metric(run_root, row, primary, config)
        for _, row in _primary_architecture_rows(summary, config).iterrows()
    ]
    return pd.DataFrame(rows)


def _matching_pair_value(
    baseline: pd.Series,
    shared: pd.Series,
    field: str,
    blockers: list[str],
) -> Any:
    left = baseline.get(field)
    right = shared.get(field)
    if pd.isna(left) or pd.isna(right) or left != right:
        blockers.append(f"pair_mismatch:{field}")
        return math.nan
    return left


def _reset_process_tokens(value: Any, *, arm: str, blockers: list[str]) -> set[str]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        blockers.append(f"{arm}:invalid_reset_process_start_tokens")
        return set()
    if not isinstance(parsed, list) or not parsed or any(not isinstance(token, str) for token in parsed):
        blockers.append(f"{arm}:invalid_reset_process_start_tokens")
        return set()
    tokens = {token.strip().lower() for token in parsed}
    if len(tokens) != len(parsed) or any(
        len(token) != 64 or any(character not in "0123456789abcdef" for character in token)
        for token in tokens
    ):
        blockers.append(f"{arm}:invalid_reset_process_start_tokens")
        return set()
    return tokens


def _component_share(component: float, total: float) -> float:
    if not math.isfinite(component) or not math.isfinite(total) or total <= 0.0:
        return math.nan
    return component / total


def build_primary_architecture_pairs_from_run_metrics(
    run_metrics: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    primary = validate_primary_architecture_contrast(config)
    baseline_name = str(primary["baseline_scenario"])
    shared_name = str(primary["shared_scenario"])
    rows: list[dict[str, Any]] = []
    repeat_values = (
        pd.to_numeric(run_metrics["repeat"], errors="coerce")
        if "repeat" in run_metrics.columns
        else pd.Series(index=run_metrics.index, dtype=float)
    )
    for repeat in range(1, int(primary["repeats"]) + 1):
        repeat_rows = run_metrics[repeat_values == repeat]
        scenario_values = (
            repeat_rows["scenario"].astype(str)
            if "scenario" in repeat_rows.columns
            else pd.Series(index=repeat_rows.index, dtype=str)
        )
        baseline_rows = repeat_rows[scenario_values == baseline_name]
        shared_rows = repeat_rows[scenario_values == shared_name]
        blockers: list[str] = []
        if len(baseline_rows) != 1:
            blockers.append("missing_baseline_arm" if baseline_rows.empty else "duplicate_baseline_arm")
        if len(shared_rows) != 1:
            blockers.append("missing_shared_arm" if shared_rows.empty else "duplicate_shared_arm")
        pair: dict[str, Any] = {
            "repeat": repeat,
            "system": str(primary["system"]),
            "policy": str(primary["policy"]),
            "dataset": str(primary["dataset"]),
            "deadline_ms": float(primary["deadline_ms"]),
            "streams": int(primary["streams"]),
        }
        if blockers:
            pair.update(
                {
                    metric: math.nan for metric in PRIMARY_PAIR_METRICS
                }
            )
            pair.update(
                {field: math.nan for field in PRIMARY_RESOURCE_MIX_DIAGNOSTIC_FIELDS}
            )
            pair.update({"pair_complete": False, "pair_gate_pass": False, "pair_blockers": ";".join(blockers)})
            rows.append(pair)
            continue

        baseline = baseline_rows.iloc[0]
        shared = shared_rows.iloc[0]
        for field in (
            "seed",
            "run_seed",
            "input_schedule_sha256",
            "input_frame_key_sequence_sha256",
            "measurement_window_duration_ms",
            "drain_rule",
            "resource_attribution",
            "measurement_signature",
            "semantic_prefix_contract_sha256",
            "decoder_factory",
            "branch_analytics_contract_sha256",
            "c_obs_is_partial",
        ):
            pair[field] = _matching_pair_value(baseline, shared, field, blockers)
        if pair.get("seed") != int(primary["seed"]):
            blockers.append("pair_mismatch:preregistered_seed")
        if not np.isclose(
            float(pair.get("measurement_window_duration_ms", math.nan)),
            float(primary["measurement_s"]) * 1000.0,
            rtol=0.0,
            atol=1.0,
        ):
            blockers.append("pair_mismatch:preregistered_measurement_window")

        expected_first = str(primary["arm_order"]["first_arm_by_pair"][repeat - 1])
        expected_second = shared_name if expected_first == baseline_name else baseline_name
        expected_positions = {expected_first: 1, expected_second: 2}
        for arm_role, arm_name, arm_row in (
            ("baseline", baseline_name, baseline),
            ("shared", shared_name, shared),
        ):
            try:
                contract_version = int(
                    float(arm_row.get("pair_contract_version", math.nan))
                )
            except (TypeError, ValueError):
                contract_version = -1
            if contract_version != PRIMARY_ARCHITECTURE_PAIR_METADATA_CONTRACT_VERSION:
                blockers.append(f"{arm_role}:pair_contract_version_mismatch")
            if str(arm_row.get("pair_order_strategy", "")) != str(
                primary["arm_order"]["strategy"]
            ):
                blockers.append(f"{arm_role}:pair_order_strategy_mismatch")
            try:
                pair_repeat = int(float(arm_row.get("pair_repeat", math.nan)))
            except (TypeError, ValueError):
                pair_repeat = -1
            if pair_repeat != repeat:
                blockers.append(f"{arm_role}:pair_repeat_mismatch")
            if str(arm_row.get("pair_first_arm", "")) != expected_first:
                blockers.append(f"{arm_role}:pair_first_arm_mismatch")
            if str(arm_row.get("pair_second_arm", "")) != expected_second:
                blockers.append(f"{arm_role}:pair_second_arm_mismatch")
            try:
                arm_position = int(float(arm_row.get("pair_arm_position", math.nan)))
            except (TypeError, ValueError):
                arm_position = -1
            if arm_position != expected_positions[arm_name]:
                blockers.append(f"{arm_role}:pair_arm_position_mismatch")
        if not bool(baseline.get("run_gate_pass", False)):
            blockers.extend(
                f"baseline:{value}" for value in str(baseline.get("run_gate_blockers", "")).split(";") if value
            )
        if not bool(shared.get("run_gate_pass", False)):
            blockers.extend(
                f"shared:{value}" for value in str(shared.get("run_gate_blockers", "")).split(";") if value
            )
        baseline_tokens = _reset_process_tokens(
            baseline.get("reset_process_start_tokens_json"), arm="baseline", blockers=blockers
        )
        shared_tokens = _reset_process_tokens(
            shared.get("reset_process_start_tokens_json"), arm="shared", blockers=blockers
        )
        if baseline_tokens & shared_tokens:
            blockers.append("pair_reset_process_start_token_reused")
        baseline_sink = str(baseline.get("reset_telemetry_sink_id", "")).strip().lower()
        shared_sink = str(shared.get("reset_telemetry_sink_id", "")).strip().lower()
        if (
            len(baseline_sink) != 64
            or len(shared_sink) != 64
            or any(character not in "0123456789abcdef" for character in baseline_sink)
            or any(character not in "0123456789abcdef" for character in shared_sink)
        ):
            blockers.append("pair_reset_telemetry_sink_id_invalid")
        elif baseline_sink == shared_sink:
            blockers.append("pair_reset_telemetry_sink_reused")

        baseline_c_obs = float(baseline["c_obs_in_ms_per_ingress"])
        shared_c_obs = float(shared["c_obs_in_ms_per_ingress"])
        baseline_c_obs_cpu = float(baseline["c_obs_cpu_in_ms_per_ingress"])
        shared_c_obs_cpu = float(shared["c_obs_cpu_in_ms_per_ingress"])
        baseline_c_obs_gpu = float(baseline["c_obs_gpu_in_ms_per_ingress"])
        shared_c_obs_gpu = float(shared["c_obs_gpu_in_ms_per_ingress"])
        baseline_cpu_share = _component_share(baseline_c_obs_cpu, baseline_c_obs)
        shared_cpu_share = _component_share(shared_c_obs_cpu, shared_c_obs)
        baseline_gpu_share = _component_share(baseline_c_obs_gpu, baseline_c_obs)
        shared_gpu_share = _component_share(shared_c_obs_gpu, shared_c_obs)
        if not math.isfinite(baseline_c_obs) or baseline_c_obs <= 0:
            blockers.append("nonpositive_baseline_c_obs_in")
            delta_reuse = math.nan
        else:
            delta_reuse = (baseline_c_obs - shared_c_obs) / baseline_c_obs
        pair.update(
            {
                "baseline_c_obs_in_ms_per_ingress": baseline_c_obs,
                "shared_c_obs_in_ms_per_ingress": shared_c_obs,
                "baseline_c_obs_cpu_in_ms_per_ingress": baseline_c_obs_cpu,
                "shared_c_obs_cpu_in_ms_per_ingress": shared_c_obs_cpu,
                "baseline_minus_shared_c_obs_cpu_in_ms_per_ingress": (
                    baseline_c_obs_cpu - shared_c_obs_cpu
                ),
                "baseline_c_obs_gpu_in_ms_per_ingress": baseline_c_obs_gpu,
                "shared_c_obs_gpu_in_ms_per_ingress": shared_c_obs_gpu,
                "baseline_minus_shared_c_obs_gpu_in_ms_per_ingress": (
                    baseline_c_obs_gpu - shared_c_obs_gpu
                ),
                "baseline_c_obs_cpu_share_percent": baseline_cpu_share * 100.0,
                "shared_c_obs_cpu_share_percent": shared_cpu_share * 100.0,
                "shared_minus_baseline_c_obs_cpu_share_percentage_points": (
                    (shared_cpu_share - baseline_cpu_share) * 100.0
                ),
                "baseline_c_obs_gpu_share_percent": baseline_gpu_share * 100.0,
                "shared_c_obs_gpu_share_percent": shared_gpu_share * 100.0,
                "shared_minus_baseline_c_obs_gpu_share_percentage_points": (
                    (shared_gpu_share - baseline_gpu_share) * 100.0
                ),
                "c_obs_is_partial": bool(pair["c_obs_is_partial"]),
                "delta_reuse_obs_c_obs_in": delta_reuse,
                "baseline_event_factor_decode": float(baseline["event_factor_decode"]),
                "shared_event_factor_decode": float(shared["event_factor_decode"]),
                "delta_event_factor_decode": float(baseline["event_factor_decode"])
                - float(shared["event_factor_decode"]),
                "baseline_event_factor_preprocess": float(baseline["event_factor_preprocess"]),
                "shared_event_factor_preprocess": float(shared["event_factor_preprocess"]),
                "delta_event_factor_preprocess": float(baseline["event_factor_preprocess"])
                - float(shared["event_factor_preprocess"]),
                "baseline_vmax_completed_slo_violation_rate_percent": float(
                    baseline["vmax_completed_slo_violation_rate_percent"]
                ),
                "shared_vmax_completed_slo_violation_rate_percent": float(
                    shared["vmax_completed_slo_violation_rate_percent"]
                ),
                "shared_minus_baseline_vmax_completed_slo_violation_rate_percentage_points": float(
                    shared["vmax_completed_slo_violation_rate_percent"]
                )
                - float(baseline["vmax_completed_slo_violation_rate_percent"]),
                "baseline_drop_max_ingress_rate_percent": float(baseline["drop_max_ingress_rate_percent"]),
                "shared_drop_max_ingress_rate_percent": float(shared["drop_max_ingress_rate_percent"]),
                "shared_minus_baseline_drop_max_ingress_rate_percentage_points": float(
                    shared["drop_max_ingress_rate_percent"]
                )
                - float(baseline["drop_max_ingress_rate_percent"]),
                "pair_complete": True,
                "pair_gate_pass": not blockers,
                "pair_blockers": ";".join(sorted(set(blockers))),
            }
        )
        rows.append(pair)
    return pd.DataFrame(rows)


def build_primary_architecture_pairs(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    return build_primary_architecture_pairs_from_run_metrics(
        build_primary_architecture_run_metrics(run_root, summary, config),
        config,
    )


def paired_percentile_bootstrap_median_ci(
    values: pd.Series,
    *,
    resamples: int,
    seed: int,
    confidence_level: float,
) -> tuple[float, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if numeric.size == 0:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    samples = rng.choice(numeric, size=(int(resamples), numeric.size), replace=True)
    statistics = np.median(samples, axis=1)
    alpha = 1.0 - float(confidence_level)
    lower, upper = np.quantile(statistics, [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(lower), float(upper)


def build_primary_architecture_inference(
    pairs: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    primary = validate_primary_architecture_contrast(config)
    interval = primary["interval"]
    expected_pairs = int(primary["repeats"])
    accepted = pairs[pairs.get("pair_gate_pass", pd.Series(dtype=bool)).astype(bool)].copy()
    complete = len(pairs) == expected_pairs and len(accepted) == expected_pairs
    rows: list[dict[str, Any]] = []
    for metric, (metric_role, bound_rule) in PRIMARY_PAIR_METRICS.items():
        values = pd.to_numeric(accepted.get(metric), errors="coerce").dropna()
        analysis_status = "accepted_preregistered_inference" if complete and len(values) == expected_pairs else (
            "blocked_missing_required_pairs_or_gates"
        )
        if analysis_status == "accepted_preregistered_inference":
            lower, upper = paired_percentile_bootstrap_median_ci(
                values,
                resamples=int(interval["resamples"]),
                seed=int(interval["seed"]),
                confidence_level=float(interval["confidence_level"]),
            )
            q1, q3 = values.quantile([0.25, 0.75]).tolist()
            median = float(values.median())
        else:
            lower = upper = q1 = q3 = median = math.nan
        rows.append(
            {
                "metric": metric,
                "metric_role": metric_role,
                "bound_rule": bound_rule,
                "analysis_status": analysis_status,
                "expected_pairs": expected_pairs,
                "accepted_pairs": int(len(values)),
                "median": median,
                "q1": float(q1),
                "q3": float(q3),
                "iqr": float(q3 - q1),
                "ci95_lower": lower,
                "ci95_upper": upper,
                "bootstrap_method": str(interval["method"]),
                "bootstrap_statistic": str(interval["statistic"]),
                "bootstrap_resamples": int(interval["resamples"]),
                "bootstrap_seed": int(interval["seed"]),
            }
        )
    return pd.DataFrame(rows)


def _finite_descriptive_summary(values: pd.Series) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric)]
    if numeric.empty:
        return {"count": 0, "median": None, "min": None, "max": None}
    return {
        "count": int(numeric.size),
        "median": float(numeric.median()),
        "min": float(numeric.min()),
        "max": float(numeric.max()),
    }


def _primary_architecture_resource_mix_diagnostics(
    pairs: pd.DataFrame,
    pair_gate: pd.Series,
) -> dict[str, Any]:
    accepted = pairs.loc[pair_gate].copy() if not pairs.empty else pd.DataFrame()
    summaries = {
        field: _finite_descriptive_summary(
            accepted[field] if field in accepted.columns else pd.Series(dtype=float)
        )
        for field in PRIMARY_RESOURCE_MIX_DIAGNOSTIC_FIELDS
    }
    return {
        "role": "secondary_descriptive_not_claim_condition",
        "aggregation": "unweighted_sum_of_attributed_device_milliseconds_v1",
        "component_delta_units": "milliseconds_per_ingress",
        "component_share_units": "percent_and_percentage_points",
        "threshold_rule": "none_preregistered",
        "interpretation": (
            "CPU/GPU component deltas and share shifts describe resource composition only. "
            "They do not calibrate cross-device work and do not alter the preregistered claim rule."
        ),
        "accepted_pairs": int(pair_gate.sum()),
        "summaries": summaries,
    }


def evaluate_primary_architecture_claim_state(
    pairs: pd.DataFrame,
    inference: pd.DataFrame,
    config: dict[str, Any],
) -> dict[str, Any]:
    primary = validate_primary_architecture_contrast(config)
    expected_pairs = int(primary["repeats"])
    pair_gate = pairs.get("pair_gate_pass", pd.Series(dtype=bool)).astype(bool)
    accepted_pairs = int(pair_gate.sum())
    blockers = sorted(
        {
            item
            for value in pairs.loc[~pair_gate, "pair_blockers"].astype(str)
            for item in value.split(";")
            if item
        }
    ) if not pairs.empty and "pair_blockers" in pairs.columns else []
    complete = len(pairs) == expected_pairs and accepted_pairs == expected_pairs
    conditions: list[dict[str, Any]] = []
    all_bounds_pass = complete
    for metric, (_, rule) in PRIMARY_PAIR_METRICS.items():
        metric_rows = inference[inference["metric"].astype(str) == metric]
        if len(metric_rows) != 1:
            passed = False
            bound_value = math.nan
        else:
            result = metric_rows.iloc[0]
            if rule == "lower_above_zero":
                bound_value = float(result["ci95_lower"])
                passed = math.isfinite(bound_value) and bound_value > 0.0
            else:
                bound_value = float(result["ci95_upper"])
                passed = math.isfinite(bound_value) and bound_value <= 0.0
        all_bounds_pass &= passed
        conditions.append(
            {
                "metric": metric,
                "rule": rule,
                "bound_value": bound_value if math.isfinite(bound_value) else None,
                "passed": bool(passed),
            }
        )
    accepted_partial_coverage = bool(
        complete
        and "c_obs_is_partial" in pairs.columns
        and pairs.loc[pair_gate, "c_obs_is_partial"].astype(bool).any()
    )
    if not complete:
        state = "blocked_missing_required_pairs_or_gates"
    elif all_bounds_pass:
        state = (
            "favorable_preregistered_rule_satisfied_partial_resource_coverage"
            if accepted_partial_coverage
            else "favorable_preregistered_rule_satisfied"
        )
    else:
        state = "not_confirmed_interval_conditions_failed"
    return {
        "claim_state": state,
        "interpretation": (
            "The state applies only to the preregistered architecture cell. Partial resource coverage limits "
            "the favorable state to the measured CPU/GPU interval signature and does not establish complete "
            "CPU/GPU/NVDEC/transfer/fanout savings or universal superiority. CPU/GPU component deltas and "
            "share shifts remain secondary descriptions of an unweighted device-time sum."
            if accepted_partial_coverage
            else "The state applies only to the preregistered architecture cell and does not establish universal "
            "superiority. CPU/GPU component deltas and share shifts remain secondary descriptions of an "
            "unweighted device-time sum."
        ),
        "resource_coverage": (
            "unavailable"
            if not complete
            else ("partial" if accepted_partial_coverage else "complete")
        ),
        "system": str(primary["system"]),
        "policy": str(primary["policy"]),
        "dataset": str(primary["dataset"]),
        "deadline_ms": float(primary["deadline_ms"]),
        "streams": int(primary["streams"]),
        "expected_pairs": expected_pairs,
        "accepted_pairs": accepted_pairs,
        "blockers": blockers,
        "conditions": conditions,
        "resource_mix_diagnostics": _primary_architecture_resource_mix_diagnostics(
            pairs,
            pair_gate,
        ),
        "claim_rule": str(primary["interval"]["claim_rule"]),
    }


def _primary_policy_rows(summary: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    ablation = validate_primary_policy_ablation(config)
    rows = completed_native_rows(summary, config)
    deadline = pd.to_numeric(rows.get("deadline_ms"), errors="coerce")
    streams = pd.to_numeric(rows.get("streams"), errors="coerce")
    return rows[
        (rows["scenario"].astype(str) == str(ablation["architecture_scenario"]))
        & (rows["system"].astype(str) == str(ablation["system"]))
        & rows["policy"].astype(str).isin(
            {str(ablation["frozen_policy"]), str(ablation["online_policy"])}
        )
        & (rows["dataset"].astype(str) == str(ablation["dataset"]))
        & np.isclose(deadline, float(ablation["deadline_ms"]), rtol=0.0, atol=1.0e-9)
        & (streams == int(ablation["streams"]))
    ].copy()


def _terminal_identity_json(ingress: pd.DataFrame) -> str:
    ordered = ingress.sort_values(["admission_seq", "input_frame_key"], kind="stable")
    payload = [
        [str(row.input_frame_key), str(row.terminal_status)]
        for row in ordered[["input_frame_key", "terminal_status"]].itertuples(index=False)
    ]
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _primary_policy_run_metric(
    run_root: Path,
    row: pd.Series,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ablation = validate_primary_policy_ablation(config)
    evidence = _validated_publication_run_artifacts(run_root, row, config)
    run_dir = evidence["run_dir"]
    frames = evidence["frames"]
    sidecars = evidence["sidecars"]
    raw_summary = evidence["raw_summary"]
    ingress = sidecars["ingress_ledger"]
    decisions = sidecars["policy_decisions"]
    metadata = validate_run_metadata_identity(
        run_dir,
        row,
        expected_mode="benchmark",
        config=config,
    )
    summary_raw_mismatches = _primary_summary_raw_mismatches(row, raw_summary)

    statuses = ingress["terminal_status"].astype(str)
    completed_ingress = ingress[statuses == "completed"]
    ingress_streams = set(pd.to_numeric(ingress["stream_id"], errors="raise").astype(int))
    completed_stream_counts = completed_ingress.groupby("stream_id", dropna=False).size()
    positive_completed_per_stream = (
        len(ingress_streams) == int(ablation["streams"])
        and set(pd.to_numeric(completed_stream_counts.index, errors="raise").astype(int))
        == ingress_streams
        and bool((completed_stream_counts > 0).all())
    )

    latency = frames.copy()
    latency["e2e_latency_ms"] = pd.to_numeric(latency["e2e_latency_ms"], errors="raise")
    per_stream_v = latency.groupby("stream_id", dropna=False)["e2e_latency_ms"].apply(
        lambda values: float((values > float(ablation["deadline_ms"])).mean() * 100.0)
    )
    vmax = float(per_stream_v.max()) if not per_stream_v.empty else math.nan
    terminal = ingress.assign(is_drop=statuses.eq("drop"))
    per_stream_drop = terminal.groupby("stream_id", dropna=False)["is_drop"].mean() * 100.0
    drop_max = float(per_stream_drop.max()) if not per_stream_drop.empty else math.nan

    policy = str(row["policy"])
    is_online = policy == str(ablation["online_policy"])
    feedback = sidecars.get("policy_feedback")
    benchmark_adapter = metadata.get("benchmark_adapter")
    dataset_consuming_policy_path = (
        isinstance(benchmark_adapter, dict)
        and str(benchmark_adapter.get("contract", "")) == "strict_native_schema_v2_topology_v1"
        and str(benchmark_adapter.get("scenario", ""))
        == str(ablation["architecture_scenario"])
        and str(row["system"]) == str(ablation["system"])
        and set(decisions["decision_mode"].astype(str)) == {"applied"}
    )
    architecture_scenario_accepted = all(
        bool(raw_summary[field])
        for field in (
            "topology_trace_complete",
            "ingress_ledger_complete",
            "branch_terminal_trace_complete",
            "stage_semantic_contract_complete",
            "decoder_placement_verified",
            "resource_attribution_complete",
            "reset_state_verified",
        )
    ) and not summary_raw_mismatches
    policy_trace_complete = bool(decisions["policy_claim_eligible"].all())
    policy_causal_trace_complete = bool(decisions["causal_policy_claim_eligible"].all())
    policy_online_trace_complete = bool(
        not is_online
        or (
            feedback is not None
            and not feedback.empty
            and feedback["policy_feedback_claim_eligible"].all()
        )
    )
    slo_drop_balance = (
        bool(raw_summary["ingress_ledger_complete"])
        and int(raw_summary["ingress_frame_count"])
        == int(raw_summary["completed_frame_count"])
        + int(raw_summary["dropped_frame_count"])
        + int(raw_summary["censored_frame_count"])
    )
    run_gates = {
        "architecture_scenario_accepted": architecture_scenario_accepted,
        "dataset_consuming_policy_path": dataset_consuming_policy_path,
        "ingress_ledger_complete": bool(raw_summary["ingress_ledger_complete"]),
        "slo_drop_balance": slo_drop_balance,
        "policy_trace_complete": policy_trace_complete,
        "policy_causal_trace_complete": policy_causal_trace_complete,
        "policy_online_trace_complete": policy_online_trace_complete,
        "reset_state_verified": bool(raw_summary["reset_state_verified"]),
        "positive_completed_frames_per_stream": positive_completed_per_stream,
    }
    blockers = sorted(name for name, passed in run_gates.items() if not passed)
    blockers.extend(f"summary_raw_mismatch:{field}" for field in summary_raw_mismatches)

    pair_metadata = metadata.get("primary_policy_pair")
    if not isinstance(pair_metadata, dict):
        pair_metadata = {}
    metric = {
        "scenario": str(row["scenario"]),
        "system": str(row["system"]),
        "policy": policy,
        "dataset": str(row["dataset"]),
        "deadline_ms": float(row["deadline_ms"]),
        "streams": int(row["streams"]),
        "repeat": int(row["repeat"]),
        "seed": int(row["seed"]) if "seed" in row and not pd.isna(row["seed"]) else math.nan,
        "run_seed": int(row["run_seed"])
        if "run_seed" in row and not pd.isna(row["run_seed"])
        else math.nan,
        "input_schedule_sha256": str(raw_summary["input_schedule_sha256"]),
        "input_frame_key_sequence_sha256": str(
            raw_summary["input_frame_key_sequence_sha256"]
        ),
        "terminal_identity_json": _terminal_identity_json(ingress),
        "measurement_window_duration_ms": float(
            raw_summary["measurement_window_duration_ms"]
        ),
        "drain_rule": str(raw_summary["ingress_censoring_rule"]),
        "resource_attribution": str(raw_summary["resource_attribution"]),
        "measurement_signature": str(raw_summary["measurement_signature"]),
        "semantic_prefix_contract_sha256": str(
            raw_summary["semantic_prefix_contract_sha256"]
        ),
        "branch_analytics_contract_sha256": str(
            raw_summary["branch_analytics_contract_sha256"]
        ),
        "reset_process_start_tokens_json": str(
            raw_summary["reset_process_start_tokens_json"]
        ),
        "reset_telemetry_sink_id": str(raw_summary["reset_telemetry_sink_id"]),
        "vmax_completed_slo_violation_rate_percent": vmax,
        "drop_max_ingress_rate_percent": drop_max,
        "ingress_frame_count": int(raw_summary["ingress_frame_count"]),
        "completed_frame_count": int(raw_summary["completed_frame_count"]),
        "dropped_frame_count": int(raw_summary["dropped_frame_count"]),
        "censored_frame_count": int(raw_summary["censored_frame_count"]),
        "positive_completed_frames_per_stream": positive_completed_per_stream,
        "pair_contract_version": pair_metadata.get("contract_version", math.nan),
        "pair_order_strategy": str(pair_metadata.get("strategy", "")),
        "pair_repeat": pair_metadata.get("repeat", math.nan),
        "pair_first_arm": str(pair_metadata.get("first_arm", "")),
        "pair_arm_position": pair_metadata.get("arm_position", math.nan),
        "pair_second_arm": str(pair_metadata.get("second_arm", "")),
        "run_gate_pass": not blockers,
        "run_gate_blockers": ";".join(sorted(set(blockers))),
        "run_dir": str(run_dir.relative_to(run_root)),
    }
    return metric, {
        "decisions": decisions,
        "feedback": feedback,
        "metadata": metadata,
    }


def build_primary_policy_run_metrics(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, dict[tuple[int, str], list[dict[str, Any]]]]:
    metrics: list[dict[str, Any]] = []
    evidence: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for _, row in _primary_policy_rows(summary, config).iterrows():
        metric, run_evidence = _primary_policy_run_metric(run_root, row, config)
        metrics.append(metric)
        key = (int(metric["repeat"]), str(metric["policy"]))
        evidence.setdefault(key, []).append(run_evidence)
    return pd.DataFrame(metrics), evidence


def _policy_replay_blockers(
    assessment: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(assessment, dict):
        return ["policy_implementation_equivalence:not_performed"]
    blockers: list[str] = []
    if assessment.get("gate") != "policy_implementation_equivalence":
        blockers.append("policy_implementation_equivalence:wrong_gate")
    if assessment.get("scope") != "frozen_v4_proxy_passport_replay":
        blockers.append("policy_implementation_equivalence:wrong_scope")
    if assessment.get("runtime_reference_replay_performed") is not True:
        blockers.append("policy_implementation_equivalence:not_performed")
    if assessment.get("passed") is not True:
        blockers.append("policy_implementation_equivalence:failed")
    if assessment.get("artifact_identity_verified") is not True:
        blockers.append("policy_implementation_equivalence:artifact_identity_failed")
    if assessment.get("formal_aw_heft_equivalence_evaluated") is not False:
        blockers.append("policy_implementation_equivalence:formal_scope_contamination")
    for value in assessment.get("blockers", []):
        blockers.append(f"policy_implementation_equivalence:{value}")
    return list(dict.fromkeys(blockers))


def build_primary_policy_pairs_from_run_metrics(
    run_metrics: pd.DataFrame,
    config: dict[str, Any],
    *,
    replay_assessments: dict[int, dict[str, Any]] | None = None,
    architecture_prerequisite_passed: bool = False,
    runtime_compatibility_passed: bool = False,
) -> pd.DataFrame:
    ablation = validate_primary_policy_ablation(config)
    frozen_name = str(ablation["frozen_policy"])
    online_name = str(ablation["online_policy"])
    replay_assessments = replay_assessments or {}
    repeat_values = (
        pd.to_numeric(run_metrics["repeat"], errors="coerce")
        if "repeat" in run_metrics.columns
        else pd.Series(index=run_metrics.index, dtype=float)
    )
    rows: list[dict[str, Any]] = []
    for repeat in range(1, int(ablation["repeats"]) + 1):
        repeat_rows = run_metrics[repeat_values == repeat]
        policy_values = (
            repeat_rows["policy"].astype(str)
            if "policy" in repeat_rows.columns
            else pd.Series(index=repeat_rows.index, dtype=str)
        )
        frozen_rows = repeat_rows[policy_values == frozen_name]
        online_rows = repeat_rows[policy_values == online_name]
        blockers: list[str] = []
        if len(frozen_rows) != 1:
            blockers.append(
                "missing_frozen_arm" if frozen_rows.empty else "duplicate_frozen_arm"
            )
        if len(online_rows) != 1:
            blockers.append(
                "missing_online_arm" if online_rows.empty else "duplicate_online_arm"
            )
        if not architecture_prerequisite_passed:
            blockers.append("primary_architecture_contrast_not_accepted")
        if not runtime_compatibility_passed:
            blockers.append("runtime_policy_implementation_not_compatible")
        pair: dict[str, Any] = {
            "repeat": repeat,
            "scenario": str(ablation["architecture_scenario"]),
            "system": str(ablation["system"]),
            "dataset": str(ablation["dataset"]),
            "deadline_ms": float(ablation["deadline_ms"]),
            "streams": int(ablation["streams"]),
        }
        replay_assessment = replay_assessments.get(repeat)
        replay_blockers = _policy_replay_blockers(replay_assessment)
        pair.update(
            {
                "policy_replay_status": str(
                    replay_assessment.get("status", "")
                    if isinstance(replay_assessment, dict)
                    else ""
                ),
                "policy_replay_assessment_json": json.dumps(
                    replay_assessment if isinstance(replay_assessment, dict) else {},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ),
            }
        )
        if len(frozen_rows) != 1 or len(online_rows) != 1:
            pair.update(
                {
                    metric: math.nan for metric in PRIMARY_POLICY_PAIR_METRICS
                }
            )
            pair.update(
                {
                    "frozen_vmax_completed_slo_violation_rate_percent": math.nan,
                    "online_vmax_completed_slo_violation_rate_percent": math.nan,
                    "frozen_drop_max_ingress_rate_percent": math.nan,
                    "online_drop_max_ingress_rate_percent": math.nan,
                    "online_minus_frozen_drop_max_ingress_rate_percentage_points": math.nan,
                    "frozen_censored_frame_count": math.nan,
                    "online_censored_frame_count": math.nan,
                    "policy_implementation_equivalence_passed": False,
                    "pair_complete": False,
                    "pair_gate_pass": False,
                    "pair_blockers": ";".join(sorted(set(blockers))),
                }
            )
            rows.append(pair)
            continue

        frozen = frozen_rows.iloc[0]
        online = online_rows.iloc[0]
        for field in (
            "seed",
            "run_seed",
            "input_schedule_sha256",
            "input_frame_key_sequence_sha256",
            "terminal_identity_json",
            "measurement_window_duration_ms",
            "drain_rule",
            "resource_attribution",
            "measurement_signature",
            "semantic_prefix_contract_sha256",
            "branch_analytics_contract_sha256",
        ):
            pair[field] = _matching_pair_value(frozen, online, field, blockers)
        if pair.get("seed") != int(ablation["seed"]):
            blockers.append("pair_mismatch:preregistered_seed")
        if not np.isclose(
            float(pair.get("measurement_window_duration_ms", math.nan)),
            float(ablation["measurement_s"]) * 1000.0,
            rtol=0.0,
            atol=1.0,
        ):
            blockers.append("pair_mismatch:preregistered_measurement_window")

        expected_first = str(ablation["arm_order"]["first_arm_by_pair"][repeat - 1])
        expected_positions = {
            expected_first: 1,
            online_name if expected_first == frozen_name else frozen_name: 2,
        }
        expected_second = online_name if expected_first == frozen_name else frozen_name
        for arm_name, arm_row in ((frozen_name, frozen), (online_name, online)):
            try:
                contract_version = int(
                    float(arm_row.get("pair_contract_version", math.nan))
                )
            except (TypeError, ValueError):
                contract_version = -1
            if contract_version != 1:
                blockers.append(f"{arm_name}:pair_contract_version_mismatch")
            if str(arm_row.get("pair_order_strategy", "")) != str(
                ablation["arm_order"]["strategy"]
            ):
                blockers.append(f"{arm_name}:pair_order_strategy_mismatch")
            try:
                pair_repeat = int(float(arm_row.get("pair_repeat", math.nan)))
            except (TypeError, ValueError):
                pair_repeat = -1
            if pair_repeat != repeat:
                blockers.append(f"{arm_name}:pair_repeat_mismatch")
            if str(arm_row.get("pair_first_arm", "")) != expected_first:
                blockers.append(f"{arm_name}:pair_first_arm_mismatch")
            if str(arm_row.get("pair_second_arm", "")) != expected_second:
                blockers.append(f"{arm_name}:pair_second_arm_mismatch")
            try:
                arm_position = int(float(arm_row.get("pair_arm_position", math.nan)))
            except (TypeError, ValueError):
                arm_position = -1
            if arm_position != expected_positions[arm_name]:
                blockers.append(f"{arm_name}:pair_arm_position_mismatch")

        for arm, arm_row in (("frozen", frozen), ("online", online)):
            if not bool(arm_row.get("run_gate_pass", False)):
                blockers.extend(
                    f"{arm}:{value}"
                    for value in str(arm_row.get("run_gate_blockers", "")).split(";")
                    if value
                )
        frozen_tokens = _reset_process_tokens(
            frozen.get("reset_process_start_tokens_json"),
            arm="frozen",
            blockers=blockers,
        )
        online_tokens = _reset_process_tokens(
            online.get("reset_process_start_tokens_json"),
            arm="online",
            blockers=blockers,
        )
        if frozen_tokens & online_tokens:
            blockers.append("pair_reset_process_start_token_reused")
        frozen_sink = str(frozen.get("reset_telemetry_sink_id", "")).strip().lower()
        online_sink = str(online.get("reset_telemetry_sink_id", "")).strip().lower()
        if (
            len(frozen_sink) != 64
            or len(online_sink) != 64
            or any(character not in "0123456789abcdef" for character in frozen_sink)
            or any(character not in "0123456789abcdef" for character in online_sink)
        ):
            blockers.append("pair_reset_telemetry_sink_id_invalid")
        elif frozen_sink == online_sink:
            blockers.append("pair_reset_telemetry_sink_reused")
        blockers.extend(replay_blockers)

        frozen_vmax = float(frozen["vmax_completed_slo_violation_rate_percent"])
        online_vmax = float(online["vmax_completed_slo_violation_rate_percent"])
        frozen_drop = float(frozen["drop_max_ingress_rate_percent"])
        online_drop = float(online["drop_max_ingress_rate_percent"])
        frozen_censored = int(frozen["censored_frame_count"])
        online_censored = int(online["censored_frame_count"])
        if frozen_censored != 0:
            blockers.append("frozen:censored_rate_not_zero")
        if online_censored != 0:
            blockers.append("online:censored_rate_not_zero")
        if online_drop - frozen_drop > float(
            ablation["guardrails"]["max_online_minus_frozen_drop_rate_percent"]
        ) + 1e-12:
            blockers.append("guardrail:online_drop_rate_increased")
        for arm, arm_row in (("frozen", frozen), ("online", online)):
            if not bool(arm_row.get("positive_completed_frames_per_stream", False)):
                blockers.append(f"{arm}:nonpositive_completed_frames_per_stream")

        pair.update(
            {
                "frozen_vmax_completed_slo_violation_rate_percent": frozen_vmax,
                "online_vmax_completed_slo_violation_rate_percent": online_vmax,
                "online_minus_frozen_vmax_completed_slo_violation_rate_percentage_points": (
                    online_vmax - frozen_vmax
                ),
                "frozen_drop_max_ingress_rate_percent": frozen_drop,
                "online_drop_max_ingress_rate_percent": online_drop,
                "online_minus_frozen_drop_max_ingress_rate_percentage_points": (
                    online_drop - frozen_drop
                ),
                "frozen_censored_frame_count": frozen_censored,
                "online_censored_frame_count": online_censored,
                "policy_implementation_equivalence_passed": not replay_blockers,
                "pair_complete": True,
                "pair_gate_pass": not blockers,
                "pair_blockers": ";".join(sorted(set(blockers))),
            }
        )
        rows.append(pair)
    return pd.DataFrame(rows)


def build_primary_policy_pairs(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
    *,
    architecture_prerequisite_passed: bool,
) -> pd.DataFrame:
    run_metrics, evidence = build_primary_policy_run_metrics(run_root, summary, config)
    ablation = validate_primary_policy_ablation(config)
    runtime_compatibility = assess_primary_policy_runtime_compatibility(config)
    replay_assessments: dict[int, dict[str, Any]] = {}
    for repeat in range(1, int(ablation["repeats"]) + 1):
        frozen_entries = evidence.get((repeat, str(ablation["frozen_policy"])), [])
        online_entries = evidence.get((repeat, str(ablation["online_policy"])), [])
        if len(frozen_entries) != 1 or len(online_entries) != 1:
            continue
        frozen_evidence = frozen_entries[0]
        online_evidence = online_entries[0]
        feedback = online_evidence.get("feedback")
        if feedback is None:
            continue
        replay_assessments[repeat] = evaluate_primary_policy_proxy_replay(
            config,
            frozen_decisions=frozen_evidence["decisions"],
            online_decisions=online_evidence["decisions"],
            online_feedback=feedback,
            frozen_metadata=frozen_evidence["metadata"],
            online_metadata=online_evidence["metadata"],
        )
    return build_primary_policy_pairs_from_run_metrics(
        run_metrics,
        config,
        replay_assessments=replay_assessments,
        architecture_prerequisite_passed=architecture_prerequisite_passed,
        runtime_compatibility_passed=bool(runtime_compatibility["passed"]),
    )


def build_primary_policy_inference(
    pairs: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    ablation = validate_primary_policy_ablation(config)
    expected_pairs = int(ablation["repeats"])
    accepted = pairs[pairs.get("pair_gate_pass", False).astype(bool)].copy()
    rows: list[dict[str, Any]] = []
    for metric, (role, rule) in PRIMARY_POLICY_PAIR_METRICS.items():
        values = pd.to_numeric(accepted.get(metric), errors="coerce").dropna()
        if len(values) != expected_pairs:
            rows.append(
                {
                    "metric": metric,
                    "role": role,
                    "rule": rule,
                    "pair_count": int(len(values)),
                    "median": math.nan,
                    "iqr": math.nan,
                    "ci95_lower": math.nan,
                    "ci95_upper": math.nan,
                    "analysis_status": "blocked_missing_required_pairs_or_gates",
                }
            )
            continue
        lower, upper = paired_percentile_bootstrap_median_ci(
            values,
            resamples=int(ablation["interval"]["resamples"]),
            seed=int(ablation["interval"]["seed"]),
            confidence_level=float(ablation["interval"]["confidence_level"]),
        )
        rows.append(
            {
                "metric": metric,
                "role": role,
                "rule": rule,
                "pair_count": int(len(values)),
                "median": float(values.median()),
                "iqr": float(values.quantile(0.75) - values.quantile(0.25)),
                "ci95_lower": lower,
                "ci95_upper": upper,
                "analysis_status": "complete",
            }
        )
    return pd.DataFrame(rows)


def _architecture_prerequisite_passed(
    architecture_claim_state: dict[str, Any] | None,
    config: dict[str, Any],
) -> bool:
    if not isinstance(architecture_claim_state, dict):
        return False
    primary = validate_primary_architecture_contrast(config)
    return (
        int(architecture_claim_state.get("accepted_pairs", -1)) == int(primary["repeats"])
        and not architecture_claim_state.get("blockers")
        and architecture_claim_state.get("claim_state")
        in {
            "favorable_preregistered_rule_satisfied",
            "favorable_preregistered_rule_satisfied_partial_resource_coverage",
            "not_confirmed_interval_conditions_failed",
        }
    )


def evaluate_primary_policy_claim_state(
    pairs: pd.DataFrame,
    inference: pd.DataFrame,
    config: dict[str, Any],
    *,
    architecture_claim_state: dict[str, Any] | None,
) -> dict[str, Any]:
    ablation = validate_primary_policy_ablation(config)
    expected_pairs = int(ablation["repeats"])
    accepted_pairs = int(pairs.get("pair_gate_pass", False).astype(bool).sum())
    blockers = sorted(
        {
            blocker
            for value in pairs.get("pair_blockers", pd.Series(dtype=str)).astype(str)
            for blocker in value.split(";")
            if blocker
        }
    )
    architecture_passed = _architecture_prerequisite_passed(
        architecture_claim_state,
        config,
    )
    if not architecture_passed:
        blockers.append("primary_architecture_contrast_not_accepted")
    metric_rows = inference[
        inference.get("metric", pd.Series(dtype=str)).astype(str)
        == "online_minus_frozen_vmax_completed_slo_violation_rate_percentage_points"
    ]
    upper = (
        float(metric_rows.iloc[0]["ci95_upper"])
        if len(metric_rows) == 1
        else math.nan
    )
    complete = (
        accepted_pairs == expected_pairs
        and architecture_passed
        and len(metric_rows) == 1
        and str(metric_rows.iloc[0]["analysis_status"]) == "complete"
    )
    favorable = complete and math.isfinite(upper) and upper < 0.0
    if not complete:
        state = "blocked_missing_required_pairs_or_gates"
    elif favorable:
        state = "favorable_proxy_update_rule_satisfied"
    else:
        state = "not_confirmed_interval_condition_failed"
    return {
        "claim_state": state,
        "interpretation": (
            "The state applies only to the preregistered frozen/online CPU/GPU "
            "technical proxy update. It does not establish formal AW-HEFT, H2b, "
            "or universal policy superiority."
        ),
        "scenario": str(ablation["architecture_scenario"]),
        "system": str(ablation["system"]),
        "dataset": str(ablation["dataset"]),
        "deadline_ms": float(ablation["deadline_ms"]),
        "streams": int(ablation["streams"]),
        "expected_pairs": expected_pairs,
        "accepted_pairs": accepted_pairs,
        "architecture_prerequisite_passed": architecture_passed,
        "blockers": sorted(set(blockers)),
        "condition": {
            "metric": "online_minus_frozen_vmax_completed_slo_violation_rate_percentage_points",
            "rule": str(ablation["interval"]["claim_rule"]),
            "ci95_upper": upper if math.isfinite(upper) else None,
            "passed": favorable,
        },
        "formal_aw_heft_equivalence_evaluated": False,
    }


def write_primary_policy_analysis(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
    output_dir: Path,
    *,
    architecture_claim_state: dict[str, Any] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    architecture_passed = _architecture_prerequisite_passed(
        architecture_claim_state,
        config,
    )
    pairs = build_primary_policy_pairs(
        run_root,
        summary,
        config,
        architecture_prerequisite_passed=architecture_passed,
    )
    pairs.to_csv(output_dir / "primary_policy_pairs.csv", index=False)
    inference = build_primary_policy_inference(pairs, config)
    inference.to_csv(output_dir / "primary_policy_inference.csv", index=False)
    claim_state = evaluate_primary_policy_claim_state(
        pairs,
        inference,
        config,
        architecture_claim_state=architecture_claim_state,
    )
    (output_dir / "primary_policy_claim_state.json").write_text(
        json.dumps(claim_state, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return pairs, inference, claim_state


def write_primary_policy_equivalence_scope(
    config: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    assessment = assess_primary_policy_equivalence_scope(config)
    (output_dir / "primary_policy_equivalence_scope.json").write_text(
        json.dumps(assessment, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return assessment


def write_primary_architecture_analysis(
    run_root: Path,
    summary: pd.DataFrame,
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    pairs = build_primary_architecture_pairs(run_root, summary, config)
    pairs.to_csv(output_dir / "primary_architecture_pairs.csv", index=False)
    inference = build_primary_architecture_inference(pairs, config)
    inference.to_csv(output_dir / "primary_architecture_inference.csv", index=False)
    claim_state = evaluate_primary_architecture_claim_state(pairs, inference, config)
    (output_dir / "primary_architecture_claim_state.json").write_text(
        json.dumps(claim_state, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    write_primary_policy_equivalence_scope(config, output_dir)
    write_primary_policy_analysis(
        run_root,
        summary,
        config,
        output_dir,
        architecture_claim_state=claim_state,
    )
    return pairs, inference, claim_state


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
    workload = config.get("scenarios", {}).get(BASELINE_SCENARIO, {}).get("workload") or {}
    if str(workload.get("routing_mode", "")) != "all_branches_per_stream":
        raise ContractError(
            f"{BASELINE_SCENARIO} event-factor analysis requires resolved routing_mode=all_branches_per_stream"
        )
    consumer_count = int(workload.get("analytics_function_types", 0) or 0)
    if consumer_count <= 0:
        raise ContractError(f"{BASELINE_SCENARIO} must define analytics_function_types")
    required = baseline[baseline["base_stage"].isin(PROOF_BASE_STAGES)]
    bad = required[(required["frames"] > 0) & (required["event_factor"] < max(1.0, consumer_count * 0.9))]
    if not bad.empty:
        sample = bad[["system", "policy", "deadline_ms", "repeat", "base_stage", "event_factor"]].head(5).to_dict("records")
        raise ContractError(
            f"{BASELINE_SCENARIO} must show decode/preprocess event factor near analytics function types={consumer_count}; sample={sample}"
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
        native_transfer = resource_metrics[
            resource_metrics["transfer_provenance"].astype(str) == "native_hardware_counter"
        ]
        if not native_transfer.empty:
            transfer = (
                native_transfer.groupby(["scenario", "deadline_ms", "policy", "dataset"], dropna=False)[
                    ["h2d_bytes", "d2h_bytes"]
                ]
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

        timeline = resource_metrics[
            resource_metrics["time_provenance"].astype(str).isin(
                {"native_hardware_counter", "derived_from_native_stage_timestamps"}
            )
        ].copy()
        timeline["time_ms"] = pd.to_numeric(timeline["timestamp_ms"], errors="coerce")
        timeline["compute_ms"] = pd.to_numeric(timeline["cpu_time_ms"], errors="coerce") + pd.to_numeric(
            timeline["gpu_time_ms"], errors="coerce"
        )
        if not timeline.empty:
            plt.figure(figsize=(10, 4.8))
            sns.lineplot(
                data=timeline.head(50000),
                x="time_ms",
                y="compute_ms",
                hue="scenario",
                estimator="mean",
                errorbar=None,
            )
            plt.xlabel("Timestamp, ms")
            plt.ylabel("CPU+GPU stage time, ms")
            plt.tight_layout()
            plt.savefig(out_dir / "resource_timeline.png", dpi=180)
            plt.close()

    if not drop_metrics.empty:
        publishable_drop = drop_metrics.copy()
        publishable_drop.loc[
            publishable_drop["drop_provenance"].astype(str) != "native_drop_event",
            "drop_rate_percent",
        ] = float("nan")
        publishable_drop.loc[
            ~publishable_drop["late_provenance"].astype(str).isin(
                {"native_deadline_event", "derived_from_native_frame_latency"}
            ),
            "late_rate_percent",
        ] = float("nan")
        drops = (
            publishable_drop.groupby(["scenario", "deadline_ms", "policy", "dataset"], dropna=False)[
                ["drop_rate_percent", "late_rate_percent"]
            ]
            .mean()
            .reset_index()
        )
        melted = drops.melt(
            id_vars=["scenario", "deadline_ms", "policy", "dataset"],
            value_vars=["drop_rate_percent", "late_rate_percent"],
            var_name="metric",
            value_name="percent",
        ).dropna(subset=["percent"])
        if not melted.empty:
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
    parser.add_argument(
        "--primary-architecture-only",
        action="store_true",
        help="Generate only the preregistered baseline/shared pair, inference, and claim-state artifacts",
    )
    args = parser.parse_args()

    config = load_report_config(args.config)
    repeats = args.expected_repeats if args.expected_repeats > 0 else int(config.get("protocol", {}).get("repeats", 1))

    df = read_summaries(args.run_root)
    if args.primary_architecture_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _, _, primary_claim_state = write_primary_architecture_analysis(
            args.run_root,
            df,
            config,
            args.output_dir,
        )
        print(f"primary_architecture_claim_state={primary_claim_state['claim_state']}")
        print(f"output_dir={args.output_dir}")
        return
    validate_report_inputs(df, config)
    validate_report_matrix_membership(df, config, repeats)
    validate_completed_run_metadata(args.run_root, df, config)
    validate_completed_run_artifacts(args.run_root, df, config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output_dir / "summary_combined.csv", index=False)
    build_measurement_passports(df, config).to_csv(
        args.output_dir / "measurement_passports.csv",
        index=False,
    )
    _, _, primary_claim_state = write_primary_architecture_analysis(
        args.run_root,
        df,
        config,
        args.output_dir,
    )

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
    print(f"primary_architecture_claim_state={primary_claim_state['claim_state']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
