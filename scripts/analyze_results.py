#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def find_latest_run(root: Path) -> Path:
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No run folders found in {root}")
    return sorted(candidates)[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze experiment summary and generate plots")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--run", type=Path, default=None, help="Path to a specific run folder")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args()

    run_dir = args.run if args.run else find_latest_run(args.runs_root)
    summary_path = run_dir / "summary.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.csv not found in {run_dir}")

    out_dir = args.output / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(summary_path)
    if df.empty:
        raise ValueError("Summary file is empty")

    # Support both legacy and current summary column names.
    if "mean_fps" not in df.columns and "throughput_mean_fps" in df.columns:
        df = df.rename(columns={"throughput_mean_fps": "mean_fps"})
    if "p95_latency_ms" not in df.columns and "latency_p95_ms" in df.columns:
        df = df.rename(columns={"latency_p95_ms": "p95_latency_ms"})

    agg = (
        df.groupby(["scenario", "system"], as_index=False)
        .agg(
            mean_fps=("mean_fps", "mean"),
            p95_latency_ms=("p95_latency_ms", "mean"),
            slo_violation_rate_percent=("slo_violation_rate_percent", "mean"),
        )
        .sort_values(["scenario", "mean_fps"], ascending=[True, False])
    )
    agg.to_csv(out_dir / "summary_aggregated.csv", index=False)

    sns.set_theme(style="whitegrid")

    plt.figure(figsize=(12, 6))
    sns.barplot(data=agg, x="scenario", y="mean_fps", hue="system")
    plt.xticks(rotation=25, ha="right")
    plt.title("Mean Throughput by Scenario and System")
    plt.tight_layout()
    plt.savefig(out_dir / "throughput_by_scenario.png", dpi=160)
    plt.close()

    plt.figure(figsize=(12, 6))
    sns.barplot(data=agg, x="scenario", y="slo_violation_rate_percent", hue="system")
    plt.xticks(rotation=25, ha="right")
    plt.title("SLO Violation Rate by Scenario and System")
    plt.tight_layout()
    plt.savefig(out_dir / "slo_violations_by_scenario.png", dpi=160)
    plt.close()

    print(f"Analysis saved to {out_dir}")


if __name__ == "__main__":
    main()
