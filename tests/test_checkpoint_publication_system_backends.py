"""Registry integration regressions; fixtures are never physical run evidence."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError
from checkpoint_publication_runtime import (
    _accepted_frames,
    checkpoint_aggregate_backend,
    publish_checkpoint_runtime,
)
from checkpoint_runtime import RuntimeRunResult


SYSTEM_BACKENDS = {
    "gstreamer_custom": "openvino_dlstreamer_branch_aggregate_v1",
    "deepstream": "deepstream_native_branch_aggregate_v1",
    "savant": "savant_native_branch_aggregate_v1",
    "openvino_gva": "openvino_gva_native_branch_aggregate_v1",
}


class PublicationSystemBackendTests(unittest.TestCase):
    def test_all_four_publication_systems_have_exact_backend_identity(self):
        for system, backend in SYSTEM_BACKENDS.items():
            with self.subTest(system=system):
                self.assertEqual(checkpoint_aggregate_backend(system), backend)

    def test_aggregate_frames_preserve_each_system_identity(self):
        linkage = dict(run_id="fixture", trace_id="fixture:0:1", stream_id=0, frame_id=1)
        ledger = [{**linkage, "terminal_status": "completed",
                   "ingress_timestamp_ms": 100, "terminal_timestamp_ms": 125}]
        branches = [{**linkage, "objects": 2}, {**linkage, "objects": 3}]
        for system, backend in SYSTEM_BACKENDS.items():
            with self.subTest(system=system):
                rows = _accepted_frames(ledger, branches,
                                        aggregate_backend=checkpoint_aggregate_backend(system))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["backend"], backend)
                self.assertEqual(rows[0]["objects"], 5)
                self.assertEqual(rows[0]["e2e_latency_ms"], 25)

    def test_recognized_system_still_requires_native_workers_and_sources(self):
        result = RuntimeRunResult(events=(), unresolved_frames=(), process_ids={},
                                  event_observed_ns={}, process_exit_ns={})
        for system in SYSTEM_BACKENDS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "output"
                with self.assertRaisesRegex(ContractError, "requires native workers and sources"):
                    publish_checkpoint_runtime(
                        output_dir=output,
                        plan={"system": system, "scenario": "checkpoint_video_dag_shared",
                              "decoder_placement": {"codec": "h264"}, "benchmark_status": "supported"},
                        scenario={"name": "checkpoint_video_dag_shared"},
                        dataset={"codec_variant": "h264"}, result=result,
                        reset_rows=(), reset_audit={}, cohort_audit={},
                        stage_contract_runtime_path=Path(tmp) / "missing.csv",
                        worker_specs=(), source_specs=(), run_id="fixture",
                        policy="cpu_only", deadline_ms=100,
                    )
                self.assertFalse(output.exists())

    def test_unknown_or_legacy_probe_system_is_rejected(self):
        for system in ("synthetic", "openvino_gstreamer", "Savant", "savant-probe", ""):
            with self.subTest(system=system):
                with self.assertRaisesRegex(ContractError, "no genuine runtime"):
                    checkpoint_aggregate_backend(system)
        with self.assertRaisesRegex(ContractError, "backend is not exact"):
            _accepted_frames([], [], aggregate_backend="synthetic")


if __name__ == "__main__":
    unittest.main()
