#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from resource_interval_contract import (
    RESOURCE_INTERVAL_COLUMNS,
    RESOURCE_INTERVAL_CONTRACT_VERSION,
    ResourceIntervalContractError,
    static_contract_status,
    summarize_resource_interval_extension,
    validate_resource_intervals,
)


FRAME_KEY = {
    "run_id": "run-1",
    "trace_id": "run-1:0:1",
    "stream_id": 0,
    "frame_id": 1,
}
INPUT_FRAME_KEY = "kpp-h264:stream0:pts90000"


def ingress_ledger() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **FRAME_KEY,
                "input_frame_key": INPUT_FRAME_KEY,
                "ingress_timestamp_ms": 1000.0,
                "terminal_timestamp_ms": 1100.0,
            }
        ]
    )


def topology_row(
    *,
    event_kind: str,
    stage: str,
    branch_id: str,
    execution_id: str,
    parents: list[str],
    timestamp_ms: float,
) -> dict[str, object]:
    return {
        **FRAME_KEY,
        "input_frame_key": INPUT_FRAME_KEY,
        "event_kind": event_kind,
        "stage": stage,
        "branch_id": branch_id,
        "execution_id": execution_id,
        "parent_execution_ids_json": json.dumps(parents, separators=(",", ":")),
        "timestamp_ms": timestamp_ms,
    }


def topology_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            topology_row(
                event_kind="source_read",
                stage="source",
                branch_id="shared",
                execution_id="source-1",
                parents=[],
                timestamp_ms=1000.0,
            ),
            topology_row(
                event_kind="stage_complete",
                stage="decode",
                branch_id="shared",
                execution_id="decode-1",
                parents=["source-1"],
                timestamp_ms=1010.0,
            ),
            topology_row(
                event_kind="stage_complete",
                stage="preprocess",
                branch_id="shared",
                execution_id="preprocess-1",
                parents=["decode-1"],
                timestamp_ms=1020.0,
            ),
            topology_row(
                event_kind="fanout",
                stage="fanout",
                branch_id="plate_number",
                execution_id="fanout-1",
                parents=["preprocess-1"],
                timestamp_ms=1021.0,
            ),
            topology_row(
                event_kind="stage_complete",
                stage="plate_number",
                branch_id="plate_number",
                execution_id="analytics-1",
                parents=["fanout-1"],
                timestamp_ms=1030.0,
            ),
            topology_row(
                event_kind="stage_complete",
                stage="record",
                branch_id="shared",
                execution_id="record-1",
                parents=["analytics-1"],
                timestamp_ms=1040.0,
            ),
        ]
    )


def frame_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **FRAME_KEY,
                "stage": "decode",
                "resource": "nvdec",
                "stage_start_timestamp_ms": 1001.0,
                "stage_end_timestamp_ms": 1010.0,
            },
            {
                **FRAME_KEY,
                "stage": "preprocess",
                "resource": "cpu",
                "stage_start_timestamp_ms": 1010.0,
                "stage_end_timestamp_ms": 1020.0,
            },
            {
                **FRAME_KEY,
                "stage": "plate_number",
                "resource": "gpu",
                "stage_start_timestamp_ms": 1021.0,
                "stage_end_timestamp_ms": 1030.0,
            },
            {
                **FRAME_KEY,
                "stage": "record",
                "resource": "cpu",
                "stage_start_timestamp_ms": 1030.0,
                "stage_end_timestamp_ms": 1040.0,
            },
        ]
    )


def interval_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": 2,
        "interval_contract_version": RESOURCE_INTERVAL_CONTRACT_VERSION,
        **FRAME_KEY,
        "input_frame_key": INPUT_FRAME_KEY,
        "component": "nvdec_submit_complete",
        "direction": "none",
        "stage": "decode",
        "branch_id": "shared",
        "execution_id": "decode-1",
        "host_start_timestamp_ns": 1_002_000_000,
        "host_end_timestamp_ns": 1_009_500_000,
        "duration_ns": 7_500_000,
        "bytes": 4096,
        "device_id": "nvdec:0",
        "counter_scope": "per_trace_interval",
        "native_event_id": "1" * 64,
        "duration_provenance": "native_decoder_submit_complete_interval_v1",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def valid_rows() -> list[dict[str, object]]:
    return [
        interval_row(),
        interval_row(
            component="fanout",
            direction="none",
            stage="fanout",
            branch_id="plate_number",
            execution_id="fanout-1",
            host_start_timestamp_ns=1_020_000_000,
            host_end_timestamp_ns=1_021_000_000,
            duration_ns=1_000_000,
            bytes=6_220_800,
            device_id="host:tee0",
            native_event_id="2" * 64,
            duration_provenance="native_gstreamer_pad_probe_interval_v1",
        ),
        interval_row(
            component="transfer",
            direction="h2d",
            stage="plate_number",
            branch_id="plate_number",
            execution_id="analytics-1",
            host_start_timestamp_ns=1_021_200_000,
            host_end_timestamp_ns=1_022_200_000,
            duration_ns=500_000,
            bytes=6_220_800,
            device_id="gpu:0",
            native_event_id="3" * 64,
            duration_provenance="native_cuda_event_interval_v1",
        ),
        interval_row(
            component="transfer",
            direction="d2h",
            stage="record",
            branch_id="shared",
            execution_id="record-1",
            host_start_timestamp_ns=1_030_200_000,
            host_end_timestamp_ns=1_031_200_000,
            duration_ns=400_000,
            bytes=1024,
            device_id="gpu:0",
            native_event_id="4" * 64,
            duration_provenance="native_cuda_event_interval_v1",
        ),
    ]


def write_intervals(path: Path, rows: list[dict[str, object]], *, columns: list[str] | None = None) -> None:
    selected = columns or RESOURCE_INTERVAL_COLUMNS
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class ResourceIntervalContractTests(unittest.TestCase):
    def validate(self, path: Path) -> pd.DataFrame:
        return validate_resource_intervals(
            path,
            ingress_ledger=ingress_ledger(),
            topology_events=topology_events(),
            frame_events=frame_events(),
        )

    def test_valid_shared_packet_has_complete_nonpublication_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, valid_rows())
            intervals = self.validate(path)

        summary = summarize_resource_interval_extension(
            intervals,
            topology_events=topology_events(),
            frame_events=frame_events(),
            topology_kind="shared_video_dag",
        )
        self.assertTrue(summary["contract_valid"])
        self.assertTrue(summary["coverage_complete"])
        self.assertEqual(summary["expected_transfer_intervals"], 2)
        self.assertEqual(summary["expected_nvdec_submit_complete_intervals"], 1)
        self.assertEqual(summary["expected_fanout_intervals"], 1)
        self.assertEqual(summary["bytes_by_direction"]["h2d"], 6_220_800)
        self.assertEqual(summary["bytes_by_direction"]["d2h"], 1024)
        self.assertFalse(summary["publication_bundle_bound"])
        self.assertFalse(summary["evidence_accepted"])
        self.assertEqual(summary["status"], "complete_linkage_extension_not_publication_bound")
        self.assertFalse(summary["full_resource_coverage_complete"])
        self.assertEqual(summary["additive_duration_components"], ["transfer"])
        self.assertEqual(
            summary["nonadditive_elapsed_components"],
            ["fanout", "nvdec_submit_complete"],
        )
        self.assertEqual(
            summary["additive_duration_ns_by_component"],
            {"transfer": 900_000},
        )
        self.assertFalse(summary["nvdec_busy_time_measured"])
        self.assertFalse(summary["fanout_resource_work_measured"])

    def test_static_status_is_explicitly_nonpublication(self) -> None:
        status = static_contract_status()
        self.assertEqual(status["contract_version"], 2)
        self.assertFalse(status["publication_bundle_bound"])
        self.assertFalse(status["evidence_accepted"])
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "resource_interval_contract.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), status)

    def test_exact_header_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, valid_rows(), columns=[*RESOURCE_INTERVAL_COLUMNS, "unexpected"])
            with self.assertRaisesRegex(ResourceIntervalContractError, "exact resource interval header"):
                self.validate(path)

    def test_proxy_or_unlabeled_provenance_is_rejected(self) -> None:
        rows = valid_rows()
        rows[0]["duration_provenance"] = "stage_presence_proxy"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "duration_provenance"):
                self.validate(path)

    def test_duplicate_native_event_id_is_rejected(self) -> None:
        rows = valid_rows()
        rows[1]["native_event_id"] = rows[0]["native_event_id"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "native_event_id is reused"):
                self.validate(path)

    def test_same_interval_under_another_event_id_is_rejected(self) -> None:
        rows = valid_rows()
        duplicate = dict(rows[2])
        duplicate["native_event_id"] = "5" * 64
        rows.append(duplicate)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "duplicated under another event id"):
                self.validate(path)

    def test_nvdec_or_fanout_execution_cannot_be_counted_twice(self) -> None:
        for row_index, component in ((0, "nvdec_submit_complete"), (1, "fanout")):
            with self.subTest(component=component):
                rows = valid_rows()
                duplicate = dict(rows[row_index])
                duplicate["native_event_id"] = "6" * 64
                duplicate["host_start_timestamp_ns"] = int(duplicate["host_start_timestamp_ns"]) + 1000
                duplicate["duration_ns"] = int(duplicate["duration_ns"]) - 1000
                rows.append(duplicate)
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "resource_intervals.csv"
                    write_intervals(path, rows)
                    with self.assertRaisesRegex(ResourceIntervalContractError, "more than one interval"):
                        self.validate(path)

    def test_duration_cannot_exceed_host_interval(self) -> None:
        rows = valid_rows()
        rows[0]["duration_ns"] = 8_000_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "exceeds enclosing host interval"):
                self.validate(path)

    def test_component_direction_contract_is_strict(self) -> None:
        rows = valid_rows()
        rows[1]["direction"] = "h2d"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "transfer rows require"):
                self.validate(path)

    def test_transfer_direction_must_match_cpu_gpu_edge(self) -> None:
        rows = valid_rows()
        rows[2]["direction"] = "d2h"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "does not match a CPU/GPU topology edge"):
                self.validate(path)

    def test_frame_and_execution_linkage_is_fail_closed(self) -> None:
        for field, value, pattern in (
            ("input_frame_key", "wrong", "input_frame_key does not match"),
            ("execution_id", "missing", "no matching topology event"),
            ("stage", "preprocess", "stage does not match topology event"),
        ):
            with self.subTest(field=field):
                rows = valid_rows()
                rows[0][field] = value
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "resource_intervals.csv"
                    write_intervals(path, rows)
                    with self.assertRaisesRegex(ResourceIntervalContractError, pattern):
                        self.validate(path)

    def test_interval_must_stay_inside_frame_and_stage(self) -> None:
        rows = valid_rows()
        rows[0]["host_start_timestamp_ns"] = 999_000_000
        rows[0]["duration_ns"] = 10_500_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "outside the ingress-terminal lifetime"):
                self.validate(path)

        rows = valid_rows()
        rows[2]["host_start_timestamp_ns"] = 1_019_000_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "outside the linked stage interval"):
                self.validate(path)

    def test_fanout_interval_cannot_precede_parent(self) -> None:
        rows = valid_rows()
        rows[1]["host_start_timestamp_ns"] = 1_019_000_000
        rows[1]["duration_ns"] = 2_000_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "starts before its topology parent"):
                self.validate(path)

    def test_missing_component_keeps_extension_incomplete(self) -> None:
        for component, coverage_field in (
            ("transfer", "transfer_coverage_complete"),
            ("nvdec_submit_complete", "nvdec_submit_complete_coverage_complete"),
            ("fanout", "fanout_coverage_complete"),
        ):
            with self.subTest(component=component):
                rows = [row for row in valid_rows() if row["component"] != component]
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "resource_intervals.csv"
                    write_intervals(path, rows)
                    intervals = self.validate(path)
                summary = summarize_resource_interval_extension(
                    intervals,
                    topology_events=topology_events(),
                    frame_events=frame_events(),
                    topology_kind="shared_video_dag",
                )
                self.assertFalse(summary["coverage_complete"])
                self.assertFalse(summary[coverage_field])
                self.assertEqual(
                    summary["status"],
                    "incomplete_linkage_extension_not_publication_bound",
                )
                self.assertFalse(summary["evidence_accepted"])

    def test_noncanonical_integer_is_rejected(self) -> None:
        rows = valid_rows()
        rows[0]["duration_ns"] = "7000000.0"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resource_intervals.csv"
            write_intervals(path, rows)
            with self.assertRaisesRegex(ResourceIntervalContractError, "canonical non-negative integer"):
                self.validate(path)


if __name__ == "__main__":
    unittest.main()
