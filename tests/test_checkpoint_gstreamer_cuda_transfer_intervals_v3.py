from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CheckpointGstreamerCudaTransferIntervalsV3Tests(unittest.TestCase):
    def test_native_probe_wires_cuda_rows_and_invariant_postprocess_topology(self) -> None:
        source = (
            ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp"
        ).read_text(encoding="utf-8")
        for token in (
            "cuda_transfer_native_event_material",
            "checkpoint_resource_interval_emitter_->emit_cuda_transfer",
            "result.cuda_transfer_intervals[0]",
            "result.cuda_transfer_intervals[1]",
            '"postprocess_" + terminal.branch_id',
            '"postprocess",',
            "{postprocess_id}",
            "decision.selected_resource",
            'write_event(trace, decode_stage, end, end, "nvdec")',
            "result.inference_finished_monotonic_ns",
            "correlate_monotonic_point_to_realtime",
        ):
            self.assertIn(token, source)
        self.assertNotIn('"localhost,cpu,"', source)
        self.assertNotIn("(terminal_timestamp_ns - path_entry_timestamp_ns) / 2", source)

    def test_native_client_and_emitter_are_exact_and_fail_closed(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "checkpoint-gstreamer-cuda-transfer-v3-test"
            fragment = root / "resource_intervals.runtime.csv"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-pthread",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_gstreamer_cuda_transfer_v3_test.cpp"),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(binary), str(fragment)],
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            event_materials = completed.stdout.splitlines()
            self.assertEqual(
                [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in event_materials],
                [
                    "49ede9393089ee17cbe7bb6710189f0b3fa21c38b4fd03c09330b8a292c56dd6",
                    "fb91785aee8bfd07d445d9604b77e5d7b78951092350ce4fb9f42b1ba5f57747",
                ],
            )
            with fragment.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual([row["direction"] for row in rows], ["h2d", "d2h"])
        self.assertEqual([row["component"] for row in rows], ["transfer", "transfer"])
        self.assertEqual(
            [row["duration_provenance"] for row in rows],
            ["native_cuda_event_interval_v1", "native_cuda_event_interval_v1"],
        )
        self.assertEqual([row["duration_ns"] for row in rows], ["250", "300"])
        self.assertEqual([row["bytes"] for row in rows], ["4", "32"])
        self.assertEqual(
            [row["device_id"] for row in rows],
            [
                "gpu:gpu-00000000-0000-0000-0000-000000000001",
                "gpu:gpu-00000000-0000-0000-0000-000000000001",
            ],
        )
        self.assertEqual([row["host_start_timestamp_ns"] for row in rows], ["1000001000", "1000001600"])
        self.assertEqual([row["host_end_timestamp_ns"] for row in rows], ["1000001400", "1000002000"])
        self.assertEqual(len({row["native_event_id"] for row in rows}), 2)
        self.assertTrue(all(row["counter_scope"] == "per_trace_interval" for row in rows))
        self.assertTrue(all(row["telemetry_source"] == "native" for row in rows))


if __name__ == "__main__":
    unittest.main()
