from __future__ import annotations

import csv
import io
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_metrics import (  # noqa: E402
    HardwareResourceCollector,
    HardwareResourceSample,
    NVML_POLL_INTERVAL_FRACTION,
)
from full_resource_contract import HARDWARE_RESOURCE_SAMPLE_COLUMNS  # noqa: E402


class FakeNvmlBackend:
    def __init__(self, *, fail: bool = False, sample_period_us: int = 1000) -> None:
        self.fail = fail
        self.sample_period_us = sample_period_us
        self.initialized = False
        self.shutdown_called = False
        self.sample_calls = 0

    def initialize(self) -> list[str]:
        self.initialized = True
        return ["gpu:0"]

    def sample(self, device_id: str) -> HardwareResourceSample:
        self.sample_calls += 1
        if self.fail:
            raise RuntimeError("decoder counter unavailable")
        return HardwareResourceSample(
            device_id=device_id,
            nvdec_util_percent=37.0,
            gpu_util_percent=51.0,
            memory_util_percent=12.0,
            vram_used_bytes=123456,
            sample_period_us=self.sample_period_us,
        )

    def shutdown(self) -> None:
        self.shutdown_called = True


class HardwareResourceCollectorTests(unittest.TestCase):
    def test_nvml_poll_interval_has_exact_quarter_period_headroom(self) -> None:
        backend = FakeNvmlBackend(sample_period_us=200_000)
        collector = HardwareResourceCollector(
            Path("unused.csv"),
            run_id="run-1",
            interval_s=1.0,
            backend=backend,
        )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=HARDWARE_RESOURCE_SAMPLE_COLUMNS)

        wait_s = collector._write_samples(writer, ["gpu:0"], {"gpu:0": 0})

        self.assertEqual(NVML_POLL_INTERVAL_FRACTION, 0.25)
        self.assertEqual(wait_s, 0.05)

    def test_sample_timestamp_is_captured_after_native_nvml_query(self) -> None:
        backend = FakeNvmlBackend(sample_period_us=200_000)
        collector = HardwareResourceCollector(
            Path("unused.csv"),
            run_id="run-1",
            interval_s=1.0,
            backend=backend,
        )
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=HARDWARE_RESOURCE_SAMPLE_COLUMNS)

        def timestamp_after_sample() -> int:
            if backend.sample_calls == 0:
                raise AssertionError("timestamp captured before native NVML query")
            return 123456789

        backend.initialize()
        with mock.patch("collect_metrics.time.time_ns", side_effect=timestamp_after_sample):
            collector._write_samples(writer, ["gpu:0"], {"gpu:0": 0})

        output.seek(0)
        row = next(csv.DictReader(io.StringIO(
            ",".join(HARDWARE_RESOURCE_SAMPLE_COLUMNS) + "\n" + output.getvalue()
        )))
        self.assertEqual(int(row["timestamp_ns"]), 123456789)

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
            self.assertFalse(path.exists())
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
