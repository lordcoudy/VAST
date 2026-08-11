#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

import psutil

from full_resource_contract import (
    FULL_RESOURCE_CONTRACT_VERSION,
    HARDWARE_RESOURCE_SAMPLE_COLUMNS,
    HARDWARE_SAMPLE_PROVENANCE,
    TELEMETRY_SCHEMA_VERSION,
)


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


@dataclass(frozen=True)
class HardwareResourceSample:
    device_id: str
    nvdec_util_percent: float
    gpu_util_percent: float
    memory_util_percent: float
    vram_used_bytes: int
    sample_period_us: int


class NvmlBackend(Protocol):
    def initialize(self) -> list[str]: ...

    def sample(self, device_id: str) -> HardwareResourceSample: ...

    def shutdown(self) -> None: ...


class PynvmlBackend:
    """Minimal fail-closed adapter around the official NVML Python binding."""

    def __init__(self) -> None:
        self._pynvml: Any = None
        self._handles: dict[str, Any] = {}
        self._initialized = False

    def initialize(self) -> list[str]:
        pynvml = importlib.import_module("pynvml")
        pynvml.nvmlInit()
        self._pynvml = pynvml
        self._initialized = True
        count = int(pynvml.nvmlDeviceGetCount())
        if count <= 0:
            raise RuntimeError("NVML reports no GPU devices")
        for index in range(count):
            device_id = f"gpu:{index}"
            self._handles[device_id] = pynvml.nvmlDeviceGetHandleByIndex(index)
        return list(self._handles)

    def sample(self, device_id: str) -> HardwareResourceSample:
        if not self._initialized or self._pynvml is None:
            raise RuntimeError("NVML backend was not initialized")
        handle = self._handles[device_id]
        decoder_util, sample_period_us = self._pynvml.nvmlDeviceGetDecoderUtilization(handle)
        utilization = self._pynvml.nvmlDeviceGetUtilizationRates(handle)
        memory = self._pynvml.nvmlDeviceGetMemoryInfo(handle)
        if int(sample_period_us) <= 0:
            raise RuntimeError(f"NVML returned a non-positive decoder sample period for {device_id}")
        return HardwareResourceSample(
            device_id=device_id,
            nvdec_util_percent=float(decoder_util),
            gpu_util_percent=float(utilization.gpu),
            memory_util_percent=float(utilization.memory),
            vram_used_bytes=int(memory.used),
            sample_period_us=int(sample_period_us),
        )

    def shutdown(self) -> None:
        if self._initialized and self._pynvml is not None:
            self._pynvml.nvmlShutdown()
        self._initialized = False
        self._handles.clear()


class HardwareResourceCollector(threading.Thread):
    """Writes accepted v2 device samples and never hides a sampling failure."""

    def __init__(
        self,
        output_csv: Path,
        *,
        run_id: str,
        interval_s: float = 1.0,
        backend: NvmlBackend | None = None,
    ) -> None:
        super().__init__(daemon=True)
        if not run_id.strip():
            raise ValueError("run_id must be nonempty")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        self.output_csv = output_csv
        self.run_id = run_id
        self.interval_s = interval_s
        self.backend = backend or PynvmlBackend()
        self._stop_event = threading.Event()
        self._failure: BaseException | None = None
        self._ready_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def wait_until_ready(self, *, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if not self._ready_event.wait(timeout_s):
            raise RuntimeError(
                f"hardware resource collector did not become ready within {timeout_s:g}s"
            )
        self.raise_if_failed()

    def raise_if_failed(self) -> None:
        if self._failure is not None:
            raise RuntimeError(f"hardware resource collection failed: {self._failure}") from self._failure

    def _write_samples(
        self,
        writer: csv.DictWriter,
        device_ids: list[str],
        sequences: dict[str, int],
    ) -> float:
        timestamp_ns = time.time_ns()
        wait_s = self.interval_s
        for device_id in device_ids:
            sample = self.backend.sample(device_id)
            if sample.sample_period_us <= 0:
                raise RuntimeError(
                    f"NVML backend returned a non-positive sample period for {device_id}"
                )
            # Poll before the shortest NVML aggregation window ends, leaving margin for jitter.
            wait_s = min(wait_s, sample.sample_period_us / 1_000_000.0 * 0.9)
            if sample.device_id != device_id:
                raise RuntimeError(
                    f"NVML backend device identity drift: expected {device_id}, got {sample.device_id}"
                )
            sequences[device_id] += 1
            writer.writerow(
                {
                    "schema_version": TELEMETRY_SCHEMA_VERSION,
                    "resource_contract_version": FULL_RESOURCE_CONTRACT_VERSION,
                    "run_id": self.run_id,
                    "sample_seq": sequences[device_id],
                    "timestamp_ns": timestamp_ns,
                    "sample_period_us": sample.sample_period_us,
                    "device_id": sample.device_id,
                    "nvdec_util_percent": sample.nvdec_util_percent,
                    "gpu_util_percent": sample.gpu_util_percent,
                    "memory_util_percent": sample.memory_util_percent,
                    "vram_used_bytes": sample.vram_used_bytes,
                    "counter_scope": "device_sample",
                    "sample_provenance": HARDWARE_SAMPLE_PROVENANCE,
                    "telemetry_source": "native",
                }
            )

        return wait_s

    def run(self) -> None:
        self.output_csv.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.output_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=HARDWARE_RESOURCE_SAMPLE_COLUMNS)
                writer.writeheader()
                device_ids = self.backend.initialize()
                sequences = {device_id: 0 for device_id in device_ids}
                wait_s = self._write_samples(writer, device_ids, sequences)
                handle.flush()
                self._ready_event.set()
                while not self._stop_event.wait(wait_s):
                    wait_s = self._write_samples(writer, device_ids, sequences)
                    handle.flush()
                # Capture a sample whose NVML interval reaches past process completion.
                self._write_samples(writer, device_ids, sequences)
                handle.flush()
        except BaseException as exc:
            self._failure = exc
            self._ready_event.set()
        finally:
            try:
                self.backend.shutdown()
            except BaseException as exc:
                if self._failure is None:
                    self._failure = exc
            self._ready_event.set()

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
