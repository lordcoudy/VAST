from __future__ import annotations

import csv
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_metrics import (  # noqa: E402
    HardwareResourceCollector,
    HardwareResourceSample,
)
from full_resource_contract import HARDWARE_RESOURCE_SAMPLE_COLUMNS  # noqa: E402


class FakeNvmlBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.initialized = False
        self.shutdown_called = False

    def initialize(self) -> list[str]:
        self.initialized = True
        return ["gpu:0"]

    def sample(self, device_id: str) -> HardwareResourceSample:
        if self.fail:
            raise RuntimeError("decoder counter unavailable")
        return HardwareResourceSample(
            device_id=device_id,
            nvdec_util_percent=37.0,
            gpu_util_percent=51.0,
            memory_util_percent=12.0,
            vram_used_bytes=123456,
            sample_period_us=1000,
        )

    def shutdown(self) -> None:
        self.shutdown_called = True


class HardwareResourceCollectorTests(unittest.TestCase):
    def test_writes_exact_native_v2_rows_and_final_sample(self) -> None:
        backend = FakeNvmlBackend()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_resource_samples.csv"
            collector = HardwareResourceCollector(
                path,
                run_id="run-1",
                interval_s=0.05,
                backend=backend,
            )
            collector.start()
            collector.wait_until_ready(timeout_s=1)
            time.sleep(0.012)
            collector.stop()
            collector.join(timeout=1)
            collector.raise_if_failed()
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertTrue(backend.initialized)
        self.assertTrue(backend.shutdown_called)
        # The caller interval is only a cap: polling must follow NVML's shorter
        # decoder sampling period so that accepted evidence has no blind gaps.
        self.assertGreaterEqual(len(rows), 5)
        self.assertEqual(list(rows[0]), HARDWARE_RESOURCE_SAMPLE_COLUMNS)
        self.assertEqual([int(row["sample_seq"]) for row in rows], list(range(1, len(rows) + 1)))
        self.assertTrue(all(row["run_id"] == "run-1" for row in rows))
        self.assertTrue(all(row["counter_scope"] == "device_sample" for row in rows))
        self.assertTrue(all(row["telemetry_source"] == "native" for row in rows))

    def test_background_nvml_failure_is_fail_closed(self) -> None:
        backend = FakeNvmlBackend(fail=True)
        with tempfile.TemporaryDirectory() as tmp:
            collector = HardwareResourceCollector(
                Path(tmp) / "hardware_resource_samples.csv",
                run_id="run-1",
                interval_s=0.005,
                backend=backend,
            )
            collector.start()
            with self.assertRaisesRegex(RuntimeError, "decoder counter unavailable"):
                collector.wait_until_ready(timeout_s=1)
            collector.join(timeout=1)

        self.assertTrue(backend.shutdown_called)


if __name__ == "__main__":
    unittest.main()
