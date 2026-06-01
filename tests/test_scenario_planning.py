#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from distributed_executor import build_distributed_plan
from run_experiments import expand_scenario, load_config, normalize_scenario


class ScenarioPlanningTests(unittest.TestCase):
    def test_baseline_scenario_uses_new_schema(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("baseline", cfg["scenarios"]["baseline"])

        self.assertEqual(scenario["workload"]["streams"], 6)
        self.assertEqual(scenario["pipeline"], ["decode", "detect"])
        self.assertFalse(scenario["distributed"]["enabled"])

    def test_stream_range_expands_to_variants(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        variants = expand_scenario(cfg, "stream_scaling")

        self.assertEqual(variants[0]["streams"], 1)
        self.assertEqual(variants[-1]["streams"], 16)
        self.assertEqual(len(variants), 16)

    def test_hybrid_variant_sets_placement_policy(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        variants = expand_scenario(cfg, "hybrid_placement")
        policies = [v["scenario"]["placement"]["policy"] for v in variants]

        self.assertEqual(policies, ["cpu_only", "gpu_only", "cpu_gpu_split"])

    def test_distributed_plan_maps_roles_to_hosts(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario(
            "edge_worker_aggregator_distributed",
            cfg["scenarios"]["edge_worker_aggregator_distributed"],
        )
        hosts_config = {
            "hosts": [
                {
                    "address": "edge.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["edge"],
                },
                {
                    "address": "gpu.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["gpu_worker"],
                },
                {
                    "address": "agg.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["aggregator"],
                },
            ]
        }

        steps = build_distributed_plan(
            hosts_config=hosts_config,
            scenario=scenario,
            system_key="custom_cpp_cuda_qt",
            command_template=cfg["systems"]["custom_cpp_cuda_qt"]["command"],
            run_relpath="runs/test/scenario/streams_1/custom/rep_01",
            duration_s=5,
            streams=1,
            min_objects=0,
            max_objects=1,
        )

        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertIn("EXPERIMENT_DISTRIBUTED=1", steps[0]["remote_command"])
        self.assertIn("EXPERIMENT_RTP_INPUT_PORT=5700", steps[0]["remote_command"])
        self.assertIn("--output /opt/vast/runs/test", steps[0]["remote_command"])


if __name__ == "__main__":
    unittest.main()
