from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_savant_launcher import (  # noqa: E402
    BRIDGE_CLASS,
    RUNTIME_EXECUTABLE,
    build_savant_module_descriptor,
    build_savant_worker_specs,
    launch_savant_worker_processes,
)
from checkpoint_savant_runtime import build_savant_runtime_plan  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")


def plan(topology: str) -> dict:
    config = yaml.safe_load(
        (ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8")
    )
    datasets = yaml.safe_load(
        (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
    )["datasets"]
    scenario = (
        "checkpoint_independent_processes_baseline"
        if topology == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    return build_savant_runtime_plan(
        config=config,
        datasets=datasets,
        scenario=scenario,
        codec="h264",
        policy="heft",
        deadline_ms=33.3,
    )


class SavantLauncherTests(unittest.TestCase):
    def test_baseline_maps_exact_frozen_process_ids_to_twenty_four_workers(self) -> None:
        value = plan("independent_processes")
        specs = build_savant_worker_specs(
            value, run_id="run-savant-baseline", arm_id="arm-savant-baseline"
        )
        self.assertEqual(len(specs), 24)
        self.assertEqual(
            {spec.worker_id for spec in specs},
            {row["process_id"] for row in value["processes"]},
        )
        self.assertTrue(all(spec.branch_id in BRANCHES for spec in specs))
        self.assertTrue(all(spec.native_event_source for spec in specs))
        self.assertTrue(all(spec.command[0] == RUNTIME_EXECUTABLE for spec in specs))
        self.assertTrue(all(spec.environment["VAST_SAVANT_BRIDGE_CLASS"] == BRIDGE_CLASS for spec in specs))
        self.assertTrue(all(spec.environment["VAST_SAVANT_MODULE_ID"] == spec.worker_id for spec in specs))

    def test_shared_maps_six_single_decode_four_route_workers(self) -> None:
        value = plan("shared_video_dag")
        specs = build_savant_worker_specs(
            value, run_id="run-savant-shared", arm_id="arm-savant-shared"
        )
        self.assertEqual(len(specs), 6)
        self.assertTrue(all(spec.branch_id is None for spec in specs))
        self.assertEqual({spec.stream_id for spec in specs}, set(range(6)))
        self.assertTrue(all(
            spec.environment["VAST_SAVANT_BRANCHES"] == ",".join(BRANCHES)
            for spec in specs
        ))
        for row, spec in zip(value["processes"], specs, strict=True):
            descriptor = build_savant_module_descriptor(value, row)
            self.assertEqual(descriptor["module_id"], spec.worker_id)
            self.assertEqual(descriptor["topology_kind"], "shared_video_dag")
            self.assertEqual(
                [item["factory"] for item in descriptor["shared_prefix"]],
                ["appsrc", "h264parse", "nvv4l2decoder", "nvstreammux", "nvvideoconvert", "tee"],
            )
            self.assertEqual(len(descriptor["routes"]), 4)
            self.assertFalse(descriptor["publication_ready"])
            self.assertFalse(descriptor["accepted_measurement_evidence_emitted"])

    def test_module_descriptors_bind_source_policy_and_inherited_fd_contract(self) -> None:
        value = plan("independent_processes")
        row = value["processes"][0]
        descriptor = build_savant_module_descriptor(value, row)
        self.assertEqual(descriptor["module_id"], row["process_id"])
        self.assertEqual(descriptor["stream_id"], row["stream_id"])
        self.assertEqual(descriptor["branches"], [row["branch"]])
        self.assertEqual(descriptor["source_process_id"], row["source_process_id"])
        self.assertEqual(descriptor["policy"], "heft")
        self.assertEqual(descriptor["deadline_ms"], 33.3)
        self.assertEqual(
            descriptor["inherited_fd_contract"],
            {
                "admission": "VAST_CHECKPOINT_ADMISSION_DATA_FD",
                "control": "VAST_CHECKPOINT_CONTROL_FD",
                "event": "VAST_CHECKPOINT_EVENT_FD",
                "policy": "VAST_CHECKPOINT_POLICY_FD",
                "status": "VAST_CHECKPOINT_STATUS_FD",
            },
        )

    def test_launcher_delegates_exact_specs_to_existing_fd_coordinator(self) -> None:
        captured: dict = {}

        def runner(**kwargs):
            captured.update(kwargs)
            return "sentinel"

        result = launch_savant_worker_processes(
            plan=plan("independent_processes"),
            run_id="run-savant-baseline",
            arm_id="arm-savant-baseline",
            source_specs=("source-0",),
            policy_socket_handler=lambda _worker, _socket: None,
            runner=runner,
            warmup_s=1.0,
            measurement_s=2.0,
            timeout_s=10.0,
        )
        self.assertEqual(result, "sentinel")
        self.assertEqual(len(captured["specs"]), 24)
        self.assertEqual(captured["source_specs"], ("source-0",))
        self.assertTrue(captured["synchronized_lifecycle"])
        self.assertTrue(captured["require_decoder_placement_verification"])
        self.assertIsNotNone(captured["policy_socket_handler"])

    def test_generic_configs_and_relabelled_processes_fail_closed(self) -> None:
        value = plan("shared_video_dag")
        value["processes"][0]["module_config_path"] = "deploy/savant/module.yml"
        with self.assertRaises(Exception):
            build_savant_worker_specs(value, run_id="run-savant", arm_id="arm-savant")


if __name__ == "__main__":
    unittest.main()
