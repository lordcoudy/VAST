#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (
    ContractError,
    canonicalize_frames_csv,
    load_dataset,
    network_profile_matches,
    summarize_frames,
    validate_frame_events,
)
from distributed_executor import parse_chrony_tracking, parse_iperf_output, parse_ping_output


class BenchmarkContractTests(unittest.TestCase):
    def test_smoke_legacy_csv_is_canonicalized_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "objects": 2, "latency_ms": 12.5}]
            ).to_csv(path, index=False)
            df = canonicalize_frames_csv(path, mode="smoke", run_id="r", detector="d", backend="b")
            self.assertEqual(df.iloc[0]["telemetry_source"], "synthetic")
            self.assertEqual(float(df.iloc[0]["e2e_latency_ms"]), 12.5)

    def test_benchmark_rejects_legacy_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame([{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "latency_ms": 1}]).to_csv(
                path, index=False
            )
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_requires_frame_event_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame_events.csv"
            pd.DataFrame([{"schema_version": 2, "run_id": "r"}]).to_csv(path, index=False)
            with self.assertRaises(ContractError):
                validate_frame_events(path)

    def test_throughput_uses_completed_frames_per_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [
                    {"e2e_latency_ms": 10, "telemetry_source": "native"},
                    {"e2e_latency_ms": 20, "telemetry_source": "native"},
                    {"e2e_latency_ms": 40, "telemetry_source": "native"},
                    {"e2e_latency_ms": 80, "telemetry_source": "native"},
                ]
            ).to_csv(path, index=False)
            result = summarize_frames(path, deadline_s=0.05, measurement_s=2)
            self.assertEqual(result["throughput_fps"], 2.0)
            self.assertEqual(result["slo_violation_rate_percent"], 25.0)

    def test_publishable_dataset_requires_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "datasets.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "datasets": {
                            "public": {
                                "publishable": True,
                                "streams": [{"path": "clip.mp4", "sha256": "SET_AFTER_PREPARATION"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ContractError):
                load_dataset(manifest, "public", mode="benchmark", project_root=root, require_files=False)

    def test_network_acceptance_gate(self) -> None:
        ok, reason = network_profile_matches({"latency_ms": 80}, {"latency_ms": [60, 140]})
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        ok, reason = network_profile_matches({"latency_ms": 10}, {"latency_ms": [60, 140]})
        self.assertFalse(ok)
        self.assertIn("outside", reason)

    def test_preflight_parsers(self) -> None:
        ping = "4 packets transmitted, 4 received, 0% packet loss\nrtt min/avg/max/mdev = 1.0/2.0/3.0/0.5 ms"
        self.assertEqual(parse_ping_output(ping)["latency_ms"], 2.0)
        self.assertEqual(parse_chrony_tracking("Last offset     : +0.000002 seconds"), 0.002)
        self.assertEqual(parse_iperf_output('{"end":{"sum_received":{"bits_per_second":125000000}}}'), 125.0)


if __name__ == "__main__":
    unittest.main()
