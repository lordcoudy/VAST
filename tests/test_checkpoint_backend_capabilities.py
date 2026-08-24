#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_adapters import (  # noqa: E402
    checkpoint_backend_capability,
    checkpoint_runtime_cell_blockers,
)


CHECKPOINT_SCENARIO = "checkpoint_video_dag_shared"


class CheckpointBackendCapabilityTests(unittest.TestCase):
    def test_only_gstreamer_has_a_genuine_checkpoint_topology_launcher(self) -> None:
        gstreamer = checkpoint_backend_capability("gstreamer_custom")
        self.assertTrue(gstreamer.topology_runtime_implemented)
        self.assertEqual(gstreamer.launcher, "scripts/checkpoint_gstreamer_runtime.py")
        self.assertFalse(gstreamer.publication_ready)
        self.assertEqual(gstreamer.codecs, ("h264", "h265"))
        self.assertEqual(gstreamer.policies, ("cpu_only",))
        self.assertEqual(gstreamer.deadlines_ms, (16.7, 33.3, 50.0, 100.0, 500.0))
        self.assertFalse(gstreamer.distributed)
        self.assertIn("CUDA/TensorRT parity", " ".join(gstreamer.blockers))

        for system in ("deepstream", "savant", "openvino_gva"):
            with self.subTest(system=system):
                capability = checkpoint_backend_capability(system)
                self.assertFalse(capability.topology_runtime_implemented)
                self.assertFalse(capability.publication_ready)
                self.assertIn(system, " ".join(capability.blockers))
                self.assertNotEqual(capability.launcher, gstreamer.launcher)

    def test_checkpoint_cell_requires_all_five_explicit_dimensions(self) -> None:
        blockers = checkpoint_runtime_cell_blockers(
            system="gstreamer_custom",
            scenario=CHECKPOINT_SCENARIO,
            codec=None,
            policy=None,
            deadline_ms=None,
            distributed=False,
        )
        self.assertIn("checkpoint codec is not explicit", blockers)
        self.assertIn("checkpoint policy is not explicit", blockers)
        self.assertIn("checkpoint deadline_ms is not explicit", blockers)

    def test_gstreamer_exact_matrix_coordinates_reach_capability_gates(self) -> None:
        h265 = checkpoint_runtime_cell_blockers(
            system="gstreamer_custom",
            scenario=CHECKPOINT_SCENARIO,
            codec="h265",
            policy="cpu_only",
            deadline_ms=100.0,
            distributed=False,
        )
        self.assertFalse(any("codec is outside" in value for value in h265))
        self.assertTrue(any("capability and calibration" in value for value in h265))

        alternate_deadline = checkpoint_runtime_cell_blockers(
            system="gstreamer_custom",
            scenario=CHECKPOINT_SCENARIO,
            codec="h264",
            policy="cpu_only",
            deadline_ms=33.3,
            distributed=False,
        )
        self.assertFalse(any("deadline is outside" in value for value in alternate_deadline))
        self.assertTrue(any("capability and calibration" in value for value in alternate_deadline))

        mixed = checkpoint_runtime_cell_blockers(
            system="gstreamer_custom",
            scenario=CHECKPOINT_SCENARIO,
            codec="h264",
            policy="static_hybrid",
            deadline_ms=100.0,
            distributed=False,
        )
        self.assertTrue(any("CUDA/TensorRT parity" in value for value in mixed))

    def test_non_finite_deadline_is_a_blocker_not_an_exception(self) -> None:
        blockers = checkpoint_runtime_cell_blockers(
            system="gstreamer_custom",
            scenario=CHECKPOINT_SCENARIO,
            codec="h264",
            policy="static_hybrid",
            deadline_ms=float("nan"),
            distributed=False,
        )
        self.assertIn("checkpoint deadline_ms must be a finite positive number", blockers)

    def test_shell_fails_before_docker_when_gpu_policy_binding_is_absent(self) -> None:
        streams = [
            {
                "stream_id": 0,
                "path": "data/videos/kpp/h264/2.mp4",
                "codec_name": "h264",
            }
        ]
        env = {
            **os.environ,
            "BENCHMARK_MODE": "benchmark",
            "DATASET_NAME": "kpp_real_h264",
            "DATASET_STREAMS_JSON": json.dumps(streams),
            "CHECKPOINT_CODEC": "h264",
            "SCHEDULER_POLICY": "static_hybrid",
            "EXPERIMENT_DISTRIBUTED": "0",
            "REAL_DRY_RUN": "1",
        }
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    "gstreamer_custom",
                    "--scenario",
                    CHECKPOINT_SCENARIO,
                    "--duration",
                    "5",
                    "--streams",
                    "1",
                    "--output",
                    str(Path(tmp) / "frames.csv"),
                    "--deadline-ms",
                    "100",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("CUDA/TensorRT parity", completed.stderr)
        self.assertNotIn("docker run", completed.stdout)

    def test_shell_cpu_path_fails_before_docker_without_exact_artifacts(self) -> None:
        env = {
            **os.environ,
            "BENCHMARK_MODE": "benchmark",
            "DATASET_NAME": "kpp_real_h265",
            "DATASET_STREAMS_JSON": json.dumps(
                [
                    {
                        "stream_id": 0,
                        "path": "data/videos/kpp/h265/2.mp4",
                        "codec_name": "h265",
                    }
                ]
            ),
            "CHECKPOINT_CODEC": "h265",
            "SCHEDULER_POLICY": "cpu_only",
            "EXPERIMENT_DISTRIBUTED": "0",
            "REAL_DRY_RUN": "1",
            "CHECKPOINT_POLICY_CAPABILITY_MANIFEST": str(
                ROOT / "configs" / "missing-policy-capability.yaml"
            ),
            "CHECKPOINT_POLICY_CALIBRATION": str(
                ROOT / "configs" / "missing-policy-calibration.yaml"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    "gstreamer_custom",
                    "--scenario",
                    CHECKPOINT_SCENARIO,
                    "--duration",
                    "5",
                    "--streams",
                    "1",
                    "--output",
                    str(Path(tmp) / "frames.csv"),
                    "--deadline-ms",
                    "33.3",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("native policy artifact is missing", completed.stderr)
        self.assertNotIn("docker run", completed.stdout)


if __name__ == "__main__":
    unittest.main()
