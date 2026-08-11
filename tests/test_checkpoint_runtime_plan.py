#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError
from checkpoint_runtime_plan import (
    CLAIM_STATUS,
    DECODER_PLACEMENT_RUNTIME_GATE,
    PUBLICATION_RUNTIME_CONTRACT,
    build_primary_pair_plans,
    validate_checkpoint_runtime_plan,
)


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


class CheckpointRuntimePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        config = load_yaml(ROOT / "configs" / "experiments.yaml")
        datasets = load_yaml(ROOT / "configs" / "datasets.yaml")["datasets"]
        self.pair = build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")

    def test_primary_pair_keeps_planning_only_status_and_exact_input_pairing(self) -> None:
        self.assertEqual(self.pair["claim_status"], CLAIM_STATUS)
        baseline = self.pair["baseline"]
        shared = self.pair["shared"]
        self.assertEqual(baseline["benchmark_status"], "supported")
        self.assertEqual(shared["benchmark_status"], "supported")
        self.assertEqual(baseline["publication_runtime"], PUBLICATION_RUNTIME_CONTRACT)
        self.assertEqual(shared["publication_runtime"], PUBLICATION_RUNTIME_CONTRACT)
        self.assertEqual(len(baseline["streams"]), 6)
        self.assertEqual(len(shared["streams"]), 6)
        self.assertEqual(baseline["cohort_protocol"]["warmup_s"], 30)
        self.assertEqual(baseline["cohort_protocol"]["measurement_s"], 180)
        self.assertEqual(baseline["cohort_protocol"]["total_runtime_s"], 210)
        self.assertEqual(self.pair["analytics_queue"]["max_buffers"], 1)
        self.assertEqual(
            self.pair["analytics_queue"]["capacity_semantics"],
            "waiting_buffers_excluding_inflight_detector_buffer",
        )
        self.assertEqual(baseline["analytics_queue"], self.pair["analytics_queue"])
        self.assertEqual(shared["analytics_queue"], self.pair["analytics_queue"])
        self.assertEqual(
            self.pair["decoder_placement"]["allowed_factories"],
            ["nvh264dec", "nvv4l2decoder"],
        )
        self.assertEqual(self.pair["decoder_placement_runtime_gate"], DECODER_PLACEMENT_RUNTIME_GATE)
        self.assertEqual(baseline["decoder_placement"], self.pair["decoder_placement"])
        self.assertEqual(shared["decoder_placement"], self.pair["decoder_placement"])
        self.assertEqual(baseline["decoder_placement_runtime_gate"], DECODER_PLACEMENT_RUNTIME_GATE)
        self.assertEqual(shared["decoder_placement_runtime_gate"], DECODER_PLACEMENT_RUNTIME_GATE)
        self.assertEqual(
            baseline["frame_identity"]["source"],
            "native_common_source_coordinator_compressed_access_unit_before_decode",
        )
        self.assertEqual(baseline["frame_identity"]["contract_version"], 3)
        self.assertIn("{source_cycle}", baseline["frame_identity"]["input_frame_key_template"])
        self.assertEqual(len(baseline["source_coordinators"]), 6)
        self.assertEqual(len(shared["source_coordinators"]), 6)
        self.assertEqual(
            baseline["external_admission"]["implementation_status"],
            "locally_executed_native_h264_h265_publication_runtime_v1",
        )
        self.assertEqual(baseline["source_playback"]["contract_version"], 6)
        self.assertEqual(baseline["source_playback"]["measurement_end_boundary_guard_ns"], 1_000_000)
        self.assertEqual(baseline["source_playback"]["offered_playback_fps"], 1)
        self.assertEqual(baseline["source_playback"]["timestamp_scale"], 600)
        self.assertEqual(
            baseline["source_playback"]["compressed_timestamp_order"],
            "native_pts_may_reorder_for_b_frames",
        )
        self.assertFalse(baseline["source_playback"]["independent_worker_file_readers_pair_eligible"])
        for left, right in zip(baseline["streams"], shared["streams"], strict=True):
            self.assertEqual(
                {worker["source_sha256"] for worker in left["workers"]},
                {right["graph_process"]["source_sha256"]},
            )
            self.assertEqual(
                {worker["source_duration_ns"] for worker in left["workers"]},
                {right["graph_process"]["source_duration_ns"]},
            )
            self.assertEqual(
                {worker["source_duration_ns"] for worker in left["workers"]},
                {right["graph_process"]["native_source_duration_ns"] * 600},
            )
            self.assertTrue(all(worker["playback_timestamp_scale"] == 600 for worker in left["workers"]))
            self.assertFalse(any(worker["continuous_replay_required"] for worker in left["workers"]))
            self.assertFalse(right["graph_process"]["continuous_replay_required"])

    def test_baseline_has_four_os_process_workers_per_logical_stream(self) -> None:
        baseline = self.pair["baseline"]
        self.assertEqual(sum(len(stream["workers"]) for stream in baseline["streams"]), 24)
        for stream in baseline["streams"]:
            workers = stream["workers"]
            self.assertEqual(len(workers), 4)
            self.assertEqual(len({worker["execution_domain_template"] for worker in workers}), 4)
            self.assertTrue(all(worker["process_kind"] == "independent_branch_worker" for worker in workers))
            self.assertTrue(all(worker["completion_delivery"] == "direct_runtime_ipc" for worker in workers))
            self.assertTrue(all(worker["analytics_queue"] == self.pair["analytics_queue"] for worker in workers))

    def test_shared_has_one_prefix_tee_and_four_queued_routes_per_stream(self) -> None:
        shared = self.pair["shared"]
        for stream in shared["streams"]:
            graph = stream["graph_process"]
            self.assertEqual(graph["shared_prefix_stages"], ["decode", "preprocess"])
            self.assertEqual(graph["fanout_primitive"], "gstreamer_tee")
            self.assertEqual(len(graph["branches"]), 4)
            self.assertTrue(all(branch["queue_required"] for branch in graph["branches"]))
            self.assertTrue(
                all(branch["analytics_queue"] == self.pair["analytics_queue"] for branch in graph["branches"])
            )

    def test_validator_rejects_shared_execution_domain_for_baseline_workers(self) -> None:
        plan = copy.deepcopy(self.pair["baseline"])
        for worker in plan["streams"][0]["workers"]:
            worker["execution_domain_template"] = "host:pid=one"
        with self.assertRaisesRegex(ContractError, "distinct execution domains"):
            validate_checkpoint_runtime_plan(plan)

    def test_validator_rejects_posthoc_join_or_missing_branch_queue(self) -> None:
        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["runtime_join"]["source"] = "posthoc_csv_merge"
        with self.assertRaisesRegex(ContractError, "direct runtime"):
            validate_checkpoint_runtime_plan(baseline)

        shared = copy.deepcopy(self.pair["shared"])
        shared["streams"][0]["graph_process"]["branches"][0]["queue_required"] = False
        with self.assertRaisesRegex(ContractError, "branch queue"):
            validate_checkpoint_runtime_plan(shared)

    def test_validator_rejects_analytics_queue_contract_drift(self) -> None:
        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "analytics queue contract drifted"):
            validate_checkpoint_runtime_plan(baseline)

        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["streams"][0]["workers"][0]["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "baseline branch analytics queue contract drifted"):
            validate_checkpoint_runtime_plan(baseline)

        shared = copy.deepcopy(self.pair["shared"])
        shared["streams"][0]["graph_process"]["branches"][0]["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "shared branch analytics queue contract drifted"):
            validate_checkpoint_runtime_plan(shared)

    def test_validator_rejects_decoder_placement_or_runtime_gate_drift(self) -> None:
        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["decoder_placement"]["allowed_factories"] = ["avdec_h264"]
        with self.assertRaisesRegex(ContractError, "decoder placement contract drifted"):
            validate_checkpoint_runtime_plan(baseline)

        shared = copy.deepcopy(self.pair["shared"])
        shared["decoder_placement_runtime_gate"]["required_state"] = "STARTED"
        with self.assertRaisesRegex(ContractError, "runtime gate drifted"):
            validate_checkpoint_runtime_plan(shared)

        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["streams"][0]["workers"][0]["source_codec"] = "h265"
        with self.assertRaisesRegex(ContractError, "source codec differs"):
            validate_checkpoint_runtime_plan(baseline)

    def test_validator_rejects_missing_common_source_coordinator(self) -> None:
        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["source_coordinators"].pop()
        with self.assertRaisesRegex(ContractError, "one source coordinator"):
            validate_checkpoint_runtime_plan(baseline)

        shared = copy.deepcopy(self.pair["shared"])
        shared["external_admission"]["pair_gate"] = "intersection_of_worker_keys"
        with self.assertRaisesRegex(ContractError, "admission contract drifted"):
            validate_checkpoint_runtime_plan(shared)

    def test_validator_rejects_publication_runtime_contract_drift(self) -> None:
        baseline = copy.deepcopy(self.pair["baseline"])
        baseline["publication_runtime"]["accepted_exporter"] = "scripts/unbound_exporter.py"
        with self.assertRaisesRegex(ContractError, "publication runtime contract drifted"):
            validate_checkpoint_runtime_plan(baseline)

    def test_pair_builder_rejects_preregistered_coordinate_drift(self) -> None:
        config = load_yaml(ROOT / "configs" / "experiments.yaml")
        datasets = load_yaml(ROOT / "configs" / "datasets.yaml")["datasets"]
        config["benchmark"]["primary_architecture_contrast"]["streams"] = 5
        with self.assertRaisesRegex(ContractError, "primary stream count does not match scenario"):
            build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")

    def test_pair_builder_rejects_missing_finite_source_contract(self) -> None:
        config = load_yaml(ROOT / "configs" / "experiments.yaml")
        datasets = load_yaml(ROOT / "configs" / "datasets.yaml")["datasets"]
        datasets["kpp_real_h264"]["streams"][0].pop("duration_s")
        with self.assertRaisesRegex(ContractError, "duration_s"):
            build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")

    def test_pair_builder_rejects_playback_contract_drift(self) -> None:
        config = load_yaml(ROOT / "configs" / "experiments.yaml")
        datasets = load_yaml(ROOT / "configs" / "datasets.yaml")["datasets"]
        datasets["kpp_real_h264"]["benchmark_playback"]["timestamp_scale"] = 1
        with self.assertRaisesRegex(ContractError, "benchmark playback contract drifted"):
            build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")

    def test_cli_writes_blueprint_without_scientific_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "checkpoint-runtime-plan.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "checkpoint_runtime_plan.py"),
                    "--config",
                    str(ROOT / "configs" / "experiments.yaml"),
                    "--datasets",
                    str(ROOT / "configs" / "datasets.yaml"),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["claim_status"], CLAIM_STATUS)
            self.assertEqual({path.name for path in Path(tmp).iterdir()}, {"checkpoint-runtime-plan.json"})


if __name__ == "__main__":
    unittest.main()
