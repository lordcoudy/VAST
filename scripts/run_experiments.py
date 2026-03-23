#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psutil
import yaml
from collect_metrics import MetricsCollector


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def detect_gpu_name() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out.splitlines()[0] if out else "unknown"
    except Exception:
        return "unknown"


def detect_cpu_name() -> str:
    try:
        return subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def validate_hardware(cfg: dict[str, Any]) -> None:
    target = cfg.get("hardware_target", {})
    gpu_target = str(target.get("gpu_model", ""))
    cpu_target = str(target.get("cpu_model", "")).lower()
    ram_target = int(target.get("ram_gb", 0))

    gpu_detected = detect_gpu_name()
    cpu_detected = detect_cpu_name()
    ram_detected = round(psutil.virtual_memory().total / (1024**3))

    print(f"[hardware] detected GPU: {gpu_detected}")
    print(f"[hardware] detected CPU: {cpu_detected}")
    print(f"[hardware] detected RAM: {ram_detected} GB")

    if gpu_target and gpu_target.lower() not in gpu_detected.lower():
        print(f"[warning] GPU mismatch: expected contains '{gpu_target}'")
    if cpu_target and cpu_target not in cpu_detected.lower():
        print(f"[warning] CPU mismatch: expected contains '{cpu_target}'")
    if ram_target and abs(ram_detected - ram_target) > 2:
        print(f"[warning] RAM mismatch: expected about {ram_target} GB")


def summarize_frames(frames_csv: Path, deadline_s: float) -> dict[str, float]:
    if not frames_csv.exists():
        return {
            "throughput_mean_fps": float("nan"),
            "latency_p95_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
        }

    df = pd.read_csv(frames_csv)
    if df.empty:
        return {
            "throughput_mean_fps": float("nan"),
            "latency_p95_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
        }

    throughput = float(df["fps_instant"].mean())
    p95 = float(df["latency_ms"].quantile(0.95))
    slo_rate = float((df["latency_ms"] > deadline_s * 1000.0).mean() * 100.0)

    return {
        "throughput_mean_fps": round(throughput, 3),
        "latency_p95_ms": round(p95, 3),
        "slo_violation_rate_percent": round(slo_rate, 3),
        "frames": int(df.shape[0]),
    }


def run_one(
    config: dict[str, Any],
    system_key: str,
    scenario_key: str,
    streams: int,
    min_objects: int,
    max_objects: int,
    duration_s: int,
    repeat_index: int,
    run_root: Path,
) -> dict[str, Any]:
    protocol = config["protocol"]
    deadline_s = float(config["hardware_target"]["deadline_s"])

    scenario_dir = run_root / scenario_key / f"streams_{streams}" / system_key / f"rep_{repeat_index:02d}"
    scenario_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = scenario_dir / "system_metrics.csv"
    frames_path = scenario_dir / "frames.csv"
    metadata_path = scenario_dir / "run_metadata.json"

    collector = MetricsCollector(metrics_path, interval_s=float(protocol.get("metric_interval_s", 1.0)))

    command_template = config["systems"][system_key]["command"]
    cmd = command_template.format(
        scenario=scenario_key,
        duration_s=duration_s,
        streams=streams,
        min_objects=min_objects,
        max_objects=max_objects,
        output_dir=scenario_dir,
    )

    warmup_s = float(protocol.get("warmup_s", 0))
    if warmup_s > 0:
        time.sleep(warmup_s)

    collector.start()
    completed = subprocess.run(cmd, shell=True, check=False)
    collector.stop()
    collector.join(timeout=2)

    summary = summarize_frames(frames_path, deadline_s)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": system_key,
        "scenario": scenario_key,
        "repeat": repeat_index,
        "exit_code": int(completed.returncode),
        "streams": streams,
        "duration_s": duration_s,
        **summary,
    }

    metadata = {
        "command": cmd,
        "result": result,
        "hardware_target": config.get("hardware_target", {}),
        "protocol": config.get("protocol", {}),
    }

    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return result


def expand_scenario(config: dict[str, Any], scenario_key: str) -> list[dict[str, int]]:
    scenario = config["scenarios"][scenario_key]
    if "stream_range" in scenario:
        start, end = scenario["stream_range"]
        return [
            {
                "streams": s,
                "min_objects": int(scenario.get("min_objects", 0)),
                "max_objects": int(scenario.get("max_objects", 20)),
            }
            for s in range(int(start), int(end) + 1)
        ]

    return [
        {
            "streams": int(scenario.get("streams", 6)),
            "min_objects": int(scenario.get("min_objects", 0)),
            "max_objects": int(scenario.get("max_objects", 20)),
        }
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run experiment matrix and capture metrics")
    parser.add_argument("--config", default="configs/experiments.yaml")
    parser.add_argument("--systems", nargs="*", default=["all"])
    parser.add_argument("--scenarios", nargs="*", default=["all"])
    parser.add_argument("--repeats", type=int, default=-1)
    parser.add_argument("--measurement", type=int, default=-1, help="Override measurement seconds")
    parser.add_argument("--warmup", type=int, default=-1, help="Override warmup seconds")
    parser.add_argument("--output-root", default="runs")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))

    if args.warmup >= 0:
        cfg["protocol"]["warmup_s"] = int(args.warmup)

    validate_hardware(cfg)

    systems = list(cfg["systems"].keys()) if args.systems == ["all"] else args.systems
    scenarios = list(cfg["scenarios"].keys()) if args.scenarios == ["all"] else args.scenarios

    repeats = int(cfg["protocol"]["repeats"] if args.repeats < 0 else args.repeats)
    measurement_s = int(cfg["protocol"]["measurement_s"] if args.measurement < 0 else args.measurement)

    run_root = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []

    for scenario in scenarios:
        if scenario not in cfg["scenarios"]:
            print(f"[error] unknown scenario: {scenario}")
            sys.exit(2)
        scenario_variants = expand_scenario(cfg, scenario)

        for system in systems:
            if system not in cfg["systems"]:
                print(f"[error] unknown system: {system}")
                sys.exit(2)

            for variant in scenario_variants:
                for rep in range(1, repeats + 1):
                    row = run_one(
                        config=cfg,
                        system_key=system,
                        scenario_key=scenario,
                        streams=variant["streams"],
                        min_objects=variant["min_objects"],
                        max_objects=variant["max_objects"],
                        duration_s=measurement_s,
                        repeat_index=rep,
                        run_root=run_root,
                    )
                    all_rows.append(row)
                    print(
                        f"[done] scenario={scenario} streams={variant['streams']} system={system} rep={rep} "
                        f"fps={row['throughput_mean_fps']} p95={row['latency_p95_ms']} "
                        f"slo={row['slo_violation_rate_percent']}%"
                    )

    summary_csv = run_root / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "timestamp",
            "system",
            "scenario",
            "repeat",
            "exit_code",
            "streams",
            "duration_s",
            "throughput_mean_fps",
            "latency_p95_ms",
            "slo_violation_rate_percent",
            "frames",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"[result] summary saved to {summary_csv}")


if __name__ == "__main__":
    main()
