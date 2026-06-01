#!/usr/bin/env python3
from __future__ import annotations

import csv
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil


@dataclass
class MetricSample:
    timestamp_ms: int
    gpu_util_percent: Optional[float]
    gpu_memory_mb: Optional[float]
    gpu_power_w: Optional[float]
    cpu_total_percent: float
    cpu_per_core_percent: str
    cpu_memory_mb: float
    cpu_power_w: Optional[float]


def _query_gpu() -> tuple[Optional[float], Optional[float], Optional[float]]:
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        if not output:
            return None, None, None
        first = output.splitlines()[0]
        util, mem, power = [x.strip() for x in first.split(",")]
        return float(util), float(mem), float(power)
    except Exception:
        return None, None, None


def _query_cpu_energy_uj() -> Optional[float]:
    for path in (
        Path("/sys/class/powercap/intel-rapl:0/energy_uj"),
        Path("/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"),
    ):
        try:
            return float(path.read_text(encoding="utf-8").strip())
        except Exception:
            continue
    return None


class MetricsCollector(threading.Thread):
    def __init__(self, output_csv: Path, interval_s: float = 1.0):
        super().__init__(daemon=True)
        self.output_csv = output_csv
        self.interval_s = interval_s
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        with self.output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp_ms",
                    "gpu_util_percent",
                    "gpu_memory_mb",
                    "gpu_power_w",
                    "cpu_total_percent",
                    "cpu_per_core_percent",
                    "cpu_memory_mb",
                    "cpu_power_w",
                ]
            )

            psutil.cpu_percent(interval=None)
            previous_energy_uj = _query_cpu_energy_uj()
            previous_energy_ts = time.monotonic()
            while not self._stop_event.is_set():
                ts = int(time.time() * 1000)
                gpu_util, gpu_mem, gpu_power = _query_gpu()
                cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
                cpu_total = sum(cpu_per_core) / max(1, len(cpu_per_core))
                cpu_mem_mb = psutil.virtual_memory().used / (1024 * 1024)
                current_energy_uj = _query_cpu_energy_uj()
                current_energy_ts = time.monotonic()
                cpu_power_w = None
                if previous_energy_uj is not None and current_energy_uj is not None:
                    elapsed_s = current_energy_ts - previous_energy_ts
                    if elapsed_s > 0 and current_energy_uj >= previous_energy_uj:
                        cpu_power_w = (current_energy_uj - previous_energy_uj) / 1_000_000.0 / elapsed_s
                previous_energy_uj = current_energy_uj
                previous_energy_ts = current_energy_ts

                writer.writerow(
                    [
                        ts,
                        gpu_util,
                        gpu_mem,
                        gpu_power,
                        round(cpu_total, 3),
                        "|".join(f"{x:.2f}" for x in cpu_per_core),
                        round(cpu_mem_mb, 3),
                        "" if cpu_power_w is None else round(cpu_power_w, 3),
                    ]
                )
                f.flush()
                time.sleep(self.interval_s)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Collect CPU/GPU metrics to CSV")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=0.0, help="0 means run until Ctrl+C")
    args = parser.parse_args()

    collector = MetricsCollector(output_csv=args.output, interval_s=args.interval)
    collector.start()
    start = time.time()

    try:
        while True:
            if args.duration > 0 and (time.time() - start) >= args.duration:
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop()
        collector.join(timeout=2)
