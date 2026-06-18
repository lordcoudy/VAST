#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


def find_latest_run(root: Path) -> Path:
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run folders found in {root}")
    return sorted(candidates)[-1]


def normalize_summary(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "throughput_mean_fps": "throughput_fps",
        "mean_fps": "throughput_fps",
        "p95_latency_ms": "latency_p95_ms",
    }
    for old, new in aliases.items():
        if new not in df.columns and old in df.columns:
            df = df.rename(columns={old: new})
    defaults = {
        "status": "legacy",
        "telemetry_source": "legacy",
        "scenario_variant": "",
        "placement_policy": "",
        "distributed": False,
        "deployment_mode": "legacy",
        "host_topology": "legacy",
        "host_role": "local",
        "detector": "legacy",
        "backend": "legacy",
        "policy": "legacy",
        "dataset": "legacy",
        "latency_p50_ms": np.nan,
        "latency_p99_ms": np.nan,
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
    return df


def ci95(stddev: pd.Series, count: pd.Series) -> pd.Series:
    return 1.96 * stddev.fillna(0.0) / np.sqrt(count.clip(lower=1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze benchmark summary and generate publishable plots")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--run", type=Path, default=None, help="Path to a specific run folder")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument(
        "--include-nonpublishable",
        action="store_true",
        help="Include synthetic, skipped, and legacy rows for diagnostics only",
    )
    args = parser.parse_args()

    run_dir = args.run if args.run else find_latest_run(args.runs_root)
    summary_path = run_dir / "summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.csv not found in {run_dir}")

    out_dir = args.output / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    df = normalize_summary(pd.read_csv(summary_path))
    if df.empty:
        raise ValueError("Summary file is empty")
    if not args.include_nonpublishable:
        df = df[(df["status"] == "completed") & (df["telemetry_source"] == "native")]
        if df.empty:
            raise ValueError("No publishable native benchmark rows found; use --include-nonpublishable for diagnostics")

    group_cols = [
        "scenario",
        "system",
        "detector",
        "backend",
        "policy",
        "placement_policy",
        "distributed",
        "deployment_mode",
        "host_topology",
        "dataset",
    ]
    agg = (
        df.groupby(group_cols, as_index=False, dropna=False)
        .agg(
            repeats=("repeat", "count"),
            throughput_fps_mean=("throughput_fps", "mean"),
            throughput_fps_stddev=("throughput_fps", "std"),
            latency_p50_ms_mean=("latency_p50_ms", "mean"),
            latency_p95_ms_mean=("latency_p95_ms", "mean"),
            latency_p99_ms_mean=("latency_p99_ms", "mean"),
            slo_violation_rate_percent_mean=("slo_violation_rate_percent", "mean"),
        )
        .sort_values(["scenario", "throughput_fps_mean"], ascending=[True, False])
    )
    agg["throughput_fps_ci95"] = ci95(agg["throughput_fps_stddev"], agg["repeats"])
    agg.to_csv(out_dir / "summary_aggregated.csv", index=False)

    sns.set_theme(style="whitegrid")
    plt.figure(figsize=(13, 6))
    sns.barplot(data=agg, x="scenario", y="throughput_fps_mean", hue="system")
    plt.xticks(rotation=25, ha="right")
    plt.title("Measured throughput by scenario and native adapter")
    plt.tight_layout()
    plt.savefig(out_dir / "throughput_by_scenario.png", dpi=160)
    plt.close()

    plt.figure(figsize=(13, 6))
    sns.barplot(data=agg, x="scenario", y="slo_violation_rate_percent_mean", hue="system")
    plt.xticks(rotation=25, ha="right")
    plt.title("SLO violation rate by scenario and native adapter")
    plt.tight_layout()
    plt.savefig(out_dir / "slo_violations_by_scenario.png", dpi=160)
    plt.close()

    distributed = agg[agg["distributed"].astype(bool)]
    if not distributed.empty:
        plt.figure(figsize=(13, 6))
        sns.barplot(data=distributed, x="scenario", y="latency_p95_ms_mean", hue="policy")
        plt.xticks(rotation=25, ha="right")
        plt.title("Distributed E2E p95 latency by scheduler policy")
        plt.tight_layout()
        plt.savefig(out_dir / "distributed_latency_by_policy.png", dpi=160)
        plt.close()
    print(f"Analysis saved to {out_dir}")


if __name__ == "__main__":
    main()
