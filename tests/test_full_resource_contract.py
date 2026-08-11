from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from full_resource_contract import (  # noqa: E402
    FANOUT_WORK_COUNTER_COLUMNS,
    HARDWARE_RESOURCE_SAMPLE_COLUMNS,
    FullResourceContractError,
    summarize_hardware_resource_samples,
    validate_full_resource_evidence,
    validate_fanout_work_counters,
    validate_hardware_resource_samples,
)


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def hardware_rows() -> list[dict]:
    return [
        {
            "schema_version": 2,
            "resource_contract_version": 2,
            "run_id": "run-1",
            "sample_seq": index,
            "timestamp_ns": index * 1_000_000_000,
            "sample_period_us": 1_000_000,
            "device_id": "gpu:0",
            "nvdec_util_percent": utilization,
            "gpu_util_percent": 25,
            "memory_util_percent": 10,
            "vram_used_bytes": 1_000_000,
            "counter_scope": "device_sample",
            "sample_provenance": "nvml_device_decoder_utilization_v1",
            "telemetry_source": "native",
        }
        for index, utilization in ((1, 50), (2, 100), (3, 0))
    ]


def fanout_row(**overrides: object) -> dict:
    row = {
        "schema_version": 2,
        "resource_contract_version": 2,
        "run_id": "run-1",
        "trace_id": "run-1:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "input_frame_key": "source:0:1",
        "branch_id": "damage",
        "execution_id": "fanout-1",
        "thread_cpu_time_ns": 25000,
        "work_units": 1,
        "device_id": "host:fanout",
        "counter_scope": "per_trace_resource_work",
        "counter_provenance": "native_thread_cpu_time_v1",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


class FullResourceContractTests(unittest.TestCase):
    def test_combined_gate_binds_window_and_exact_shared_fanout_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resource_intervals.csv").write_text("mocked\n", encoding="utf-8")
            write_csv(
                root / "hardware_resource_samples.csv",
                HARDWARE_RESOURCE_SAMPLE_COLUMNS,
                hardware_rows(),
            )
            write_csv(
                root / "fanout_work_counters.csv",
                FANOUT_WORK_COUNTER_COLUMNS,
                [fanout_row()],
            )
            ingress = pd.DataFrame(
                [{"window_start_timestamp_ms": 0.0, "window_end_timestamp_ms": 3000.0}]
            )
            topology = pd.DataFrame(
                [
                    {
                        "event_kind": "fanout",
                        "trace_id": "run-1:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "branch_id": "damage",
                        "execution_id": "fanout-1",
                    }
                ]
            )
            with (
                patch(
                    "full_resource_contract.validate_resource_intervals",
                    return_value=pd.DataFrame(),
                ) as validate_intervals,
                patch(
                    "full_resource_contract.summarize_resource_interval_extension",
                    return_value={"coverage_complete": True},
                ),
            ):
                evidence = validate_full_resource_evidence(
                    root,
                    expected_run_id="run-1",
                    ingress_ledger=ingress,
                    topology_events=topology,
                    frame_events=pd.DataFrame(),
                    topology_kind="shared_video_dag",
                )

        validate_intervals.assert_called_once()
        self.assertTrue(evidence["summary"]["evidence_accepted"])
        self.assertEqual(evidence["summary"]["fanout_thread_cpu_time_ns"], 25000)
        self.assertEqual(evidence["summary"]["nvdec_busy_equivalent_ns"], 1_500_000_000)
    def test_nvml_samples_integrate_device_level_decoder_busy_equivalent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_resource_samples.csv"
            write_csv(path, HARDWARE_RESOURCE_SAMPLE_COLUMNS, hardware_rows())
            samples = validate_hardware_resource_samples(
                path,
                expected_run_id="run-1",
                window_start_ns=0,
                window_end_ns=3_000_000_000,
            )
            summary = summarize_hardware_resource_samples(samples)

        self.assertEqual(summary["nvdec_busy_equivalent_ns"], 1_500_000_000)
        self.assertEqual(summary["sample_count"], 3)
        self.assertTrue(summary["measurement_window_covered"])
        self.assertEqual(summary["counter_scope"], "device_sample")
        self.assertFalse(summary["per_trace_nvdec_busy_claimed"])

    def test_nvml_samples_reject_wrong_scope_or_window_gap(self) -> None:
        rows = hardware_rows()
        rows[0]["counter_scope"] = "per_trace_interval"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_resource_samples.csv"
            write_csv(path, HARDWARE_RESOURCE_SAMPLE_COLUMNS, rows)
            with self.assertRaisesRegex(FullResourceContractError, "counter_scope"):
                validate_hardware_resource_samples(
                    path,
                    expected_run_id="run-1",
                    window_start_ns=0,
                    window_end_ns=3_000_000_000,
                )

        rows = hardware_rows()
        rows[1]["timestamp_ns"] = 2_500_000_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_resource_samples.csv"
            write_csv(path, HARDWARE_RESOURCE_SAMPLE_COLUMNS, rows)
            with self.assertRaisesRegex(FullResourceContractError, "sampling gap"):
                validate_hardware_resource_samples(
                    path,
                    expected_run_id="run-1",
                    window_start_ns=0,
                    window_end_ns=3_000_000_000,
                )

    def test_fanout_work_is_native_thread_time_not_queue_elapsed(self) -> None:
        expected = {("run-1:0:1", 0, 1, "damage", "fanout-1")}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fanout_work_counters.csv"
            write_csv(path, FANOUT_WORK_COUNTER_COLUMNS, [fanout_row()])
            counters = validate_fanout_work_counters(
                path,
                expected_run_id="run-1",
                expected_fanout_keys=expected,
                require_rows=True,
            )

        self.assertEqual(int(counters.iloc[0]["thread_cpu_time_ns"]), 25000)
        self.assertNotIn("duration_ns", counters.columns)
        self.assertNotIn("queue_elapsed_ns", counters.columns)

    def test_independent_topology_accepts_header_only_fanout_counter_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fanout_work_counters.csv"
            write_csv(path, FANOUT_WORK_COUNTER_COLUMNS, [])
            counters = validate_fanout_work_counters(
                path,
                expected_run_id="run-1",
                expected_fanout_keys=set(),
                require_rows=False,
            )
        self.assertTrue(counters.empty)


if __name__ == "__main__":
    unittest.main()
