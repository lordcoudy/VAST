from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from checkpoint_deepstream_runtime import (  # noqa: E402
    DEEPSTREAM_IMAGE,
    PLAN_CLAIM_STATUS,
    PROBE_CLAIM_STATUS,
    DeepStreamRuntimeError,
    assess_deepstream_runtime_readiness,
    build_deepstream_runtime_plan,
    build_probe_command,
    parse_probe_payload,
    validate_deepstream_runtime_plan,
)
from publication_policy_contract import POLICIES  # noqa: E402
from checkpoint_native_policy_runtime import (  # noqa: E402
    POLICY_RPC_FD_ENV,
    POLICY_RPC_MAX_MESSAGE_BYTES,
    POLICY_RPC_SCHEMA_VERSION,
)


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")


def load_inputs() -> tuple[dict, dict]:
    config = yaml.safe_load((ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8"))
    datasets = yaml.safe_load((ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8"))["datasets"]
    return config, datasets


def build_plan(
    scenario: str = "checkpoint_video_dag_shared",
    *,
    codec: str = "h264",
    policy: str = "heft",
    deadline_ms: float = 33.3,
) -> dict:
    config, datasets = load_inputs()
    return build_deepstream_runtime_plan(
        config=config,
        datasets=datasets,
        scenario=scenario,
        codec=codec,
        policy=policy,
        deadline_ms=deadline_ms,
    )


def good_probe() -> dict:
    return {
        "schema_version": 1,
        "artifact_kind": "deepstream_checkpoint_capability_probe",
        "claim_status": PROBE_CLAIM_STATUS,
        "system": "deepstream",
        "image": DEEPSTREAM_IMAGE,
        "image_id": "sha256:" + "a" * 64,
        "deepstream_sdk_version": "7.0.0",
        "gpu": {
            "name": "NVIDIA GeForce RTX 3060",
            "driver_version": "610.47",
            "visible": True,
        },
        "sdk_headers_present": True,
        "python_gi_present": True,
        "pyds_present": False,
        "required_elements": {
            name: {
                "available": True,
                "plugin_filename": f"/opt/nvidia/deepstream/libgst{name}.so",
                "plugin_version": "7.0.0",
            }
            for name in (
                "appsrc",
                "h264parse",
                "h265parse",
                "nvv4l2decoder",
                "nvstreammux",
                "nvvideoconvert",
                "capsfilter",
                "tee",
                "queue",
                "appsink",
            )
        },
        "decoder_probes": {
            codec: {
                "passed": True,
                "decoder_factory": "nvv4l2decoder",
                "parser_factory": f"{codec}parse",
                "gpu_id": 0,
                "decoded_buffers": 1,
                "source_sha256": hashlib.sha256(codec.encode()).hexdigest(),
                "command_exit_code": 0,
            }
            for codec in ("h264", "h265")
        },
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }


class DeepStreamRuntimePlanTests(unittest.TestCase):
    def test_baseline_expands_to_twenty_four_real_process_specs(self) -> None:
        plan = build_plan("checkpoint_independent_processes_baseline")
        self.assertEqual(plan["claim_status"], PLAN_CLAIM_STATUS)
        self.assertFalse(plan["topology_runtime_implemented"])
        self.assertFalse(plan["publication_ready"])
        self.assertEqual(
            plan["runtime_implementation_status"],
            "dedicated_native_sdk_runtime_source_and_offline_image_recipe_implemented_not_kpp_pair_piloted",
        )
        self.assertEqual(plan["topology_kind"], "independent_processes")
        self.assertEqual(plan["stream_count"], 6)
        self.assertEqual(len(plan["processes"]), 24)
        self.assertEqual({value["branch"] for value in plan["processes"]}, set(BRANCHES))
        self.assertEqual(len({value["process_id"] for value in plan["processes"]}), 24)
        self.assertEqual(plan["admission_binding"]["worker_event_protocol_version"], 3)
        self.assertEqual(plan["terminal_binding"]["native_branch_outcomes_per_frame"], 4)
        self.assertEqual(
            plan["terminal_binding"]["bridge_source"],
            "scripts/checkpoint_deepstream_protocol_bridge.py",
        )
        self.assertFalse(
            plan["terminal_binding"]["synthetic_bridge_events_accepted_as_native"]
        )
        self.assertEqual(plan["policy_binding"]["rpc_schema_version"], POLICY_RPC_SCHEMA_VERSION)
        self.assertEqual(plan["policy_binding"]["fd_environment"], POLICY_RPC_FD_ENV)
        self.assertEqual(
            plan["policy_binding"]["max_message_bytes"], POLICY_RPC_MAX_MESSAGE_BYTES
        )
        self.assertEqual(
            plan["resource_binding"]["status"],
            "native_per_frame_and_device_evidence_missing",
        )
        self.assertFalse(
            plan["resource_binding"][
                "uniform_per_branch_native_capability_receipt_emitted"
            ]
        )
        for process in plan["processes"]:
            self.assertEqual(process["process_isolation"], "os_process")
            self.assertEqual(process["branches"], [process["branch"]])
            factories = [value["factory"] for value in process["physical_pipeline"]]
            self.assertEqual(
                factories[:6],
                ["appsrc", "h264parse", "nvv4l2decoder", "nvstreammux", "nvvideoconvert", "capsfilter"],
            )
            self.assertEqual(factories[-1], "appsink")
            self.assertEqual(process["callback_dispatch"]["factory"], "vastdeepstreampolicydispatch")
            self.assertEqual(process["callback_terminal"]["factory"], "vastdeepstreambranchterminal")
            decoder = next(
                value
                for value in process["physical_pipeline"]
                if value["factory"] == "nvv4l2decoder"
            )
            self.assertEqual(decoder["execution_resource"], "nvdec")
            self.assertEqual(decoder["gpu_id"], 0)

    def test_shared_has_six_decode_preprocess_prefixes_and_four_queued_routes(self) -> None:
        plan = build_plan()
        self.assertEqual(plan["topology_kind"], "shared_video_dag")
        self.assertEqual(len(plan["processes"]), 6)
        for process in plan["processes"]:
            self.assertEqual(process["process_isolation"], "os_process")
            self.assertEqual(process["branches"], list(BRANCHES))
            prefix = [value["factory"] for value in process["shared_prefix"]]
            self.assertEqual(
                prefix,
                [
                    "appsrc",
                    "h264parse",
                    "nvv4l2decoder",
                    "nvstreammux",
                    "nvvideoconvert",
                    "capsfilter",
                    "tee",
                ],
            )
            self.assertEqual(len(process["routes"]), 4)
            self.assertEqual({route["branch"] for route in process["routes"]}, set(BRANCHES))
            for route in process["routes"]:
                self.assertEqual(route["elements"][0]["factory"], "queue")
                self.assertEqual(route["elements"][0]["max_size_buffers"], 1)
                self.assertEqual(route["elements"][0]["leaky"], "no")
                self.assertEqual(
                    route["elements"][1]["factory"], "appsink"
                )
                self.assertEqual(
                    route["callback_terminal"]["factory"], "vastdeepstreambranchterminal"
                )

    def test_pair_plan_requires_equal_persisted_measurement_schedule_fingerprint(self) -> None:
        baseline = build_plan("checkpoint_independent_processes_baseline")
        shared = build_plan("checkpoint_video_dag_shared")
        self.assertEqual(baseline["pair_schedule_gate"], shared["pair_schedule_gate"])
        self.assertEqual(
            baseline["pair_schedule_gate"]["required_rule"],
            "equal_measurement_schedule_fingerprint_sha256",
        )
        self.assertEqual(baseline["sources"], shared["sources"])
        self.assertEqual(
            baseline["admission_binding"]["source_event_protocol"],
            "direct_admission_json_v1",
        )
        self.assertEqual(
            baseline["admission_binding"]["selection_basis"],
            "decode_order_schedule_offset_half_open",
        )

    def test_h265_and_every_frozen_policy_deadline_are_propagated_exactly(self) -> None:
        config, datasets = load_inputs()
        for policy in POLICIES:
            for deadline_ms in config["benchmark"]["deadline_ms"]:
                with self.subTest(policy=policy, deadline_ms=deadline_ms):
                    plan = build_deepstream_runtime_plan(
                        config=config,
                        datasets=datasets,
                        scenario="checkpoint_video_dag_shared",
                        codec="h265",
                        policy=policy,
                        deadline_ms=deadline_ms,
                    )
                    self.assertEqual(plan["codec"], "h265")
                    self.assertEqual(plan["dataset"], "kpp_real_h265")
                    self.assertEqual(plan["policy"], policy)
                    self.assertEqual(plan["deadline_ms"], float(deadline_ms))
                    self.assertEqual(plan["parser_factory"], "h265parse")
                    self.assertTrue(
                        all(value["source_codec"] == "h265" for value in plan["sources"])
                    )
                    self.assertEqual(
                        plan["sources"][0]["source_duration_ns"],
                        54_718_999_800_000,
                    )
                    validate_deepstream_runtime_plan(plan)

    def test_plan_rejects_matrix_or_dataset_drift(self) -> None:
        config, datasets = load_inputs()
        cases = (
            {"codec": "vp9", "policy": "heft", "deadline_ms": 100.0},
            {"codec": "h264", "policy": "random", "deadline_ms": 100.0},
            {"codec": "h264", "policy": "heft", "deadline_ms": 17.0},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ContractError):
                build_deepstream_runtime_plan(
                    config=config,
                    datasets=datasets,
                    scenario="checkpoint_video_dag_shared",
                    **values,
                )

        drifted = copy.deepcopy(config)
        drifted["scenarios"]["checkpoint_video_dag_shared"]["workload"]["streams"] = 5
        with self.assertRaisesRegex(ContractError, "six logical streams"):
            build_deepstream_runtime_plan(
                config=drifted,
                datasets=datasets,
                scenario="checkpoint_video_dag_shared",
                codec="h264",
                policy="heft",
                deadline_ms=100.0,
            )

        bad_dataset = copy.deepcopy(datasets)
        bad_dataset["kpp_real_h264"]["streams"][0]["codec_name"] = "h265"
        with self.assertRaisesRegex(ContractError, "codec"):
            build_deepstream_runtime_plan(
                config=config,
                datasets=bad_dataset,
                scenario="checkpoint_video_dag_shared",
                codec="h264",
                policy="heft",
                deadline_ms=100.0,
            )

    def test_validator_rejects_relabelled_or_collapsed_topology(self) -> None:
        plan = build_plan()
        software = copy.deepcopy(plan)
        software["processes"][0]["shared_prefix"][2]["factory"] = "avdec_h264"
        with self.assertRaisesRegex(DeepStreamRuntimeError, "nvv4l2decoder"):
            validate_deepstream_runtime_plan(software)

        collapsed = copy.deepcopy(plan)
        collapsed["processes"].pop()
        with self.assertRaisesRegex(DeepStreamRuntimeError, "six shared"):
            validate_deepstream_runtime_plan(collapsed)

        no_queue = copy.deepcopy(plan)
        no_queue["processes"][0]["routes"][0]["elements"].pop(0)
        with self.assertRaisesRegex(DeepStreamRuntimeError, "queue"):
            validate_deepstream_runtime_plan(no_queue)

        relabelled = copy.deepcopy(plan)
        relabelled["runtime_executable"] = "/usr/local/bin/vast_native_gst_probe"
        with self.assertRaisesRegex(DeepStreamRuntimeError, "generic probe"):
            validate_deepstream_runtime_plan(relabelled)


class DeepStreamCapabilityProbeTests(unittest.TestCase):
    def test_probe_payload_is_strict_and_cannot_claim_publication_evidence(self) -> None:
        payload = good_probe()
        self.assertEqual(parse_probe_payload(json.dumps(payload)), payload)

        accepted = copy.deepcopy(payload)
        accepted["publication_ready"] = True
        with self.assertRaisesRegex(DeepStreamRuntimeError, "must remain false"):
            parse_probe_payload(json.dumps(accepted))

        evidence = copy.deepcopy(payload)
        evidence["accepted_measurement_evidence_emitted"] = True
        with self.assertRaisesRegex(DeepStreamRuntimeError, "must not emit"):
            parse_probe_payload(json.dumps(evidence))

        extra = copy.deepcopy(payload)
        extra["derived_decoder_label"] = "nvdec"
        with self.assertRaisesRegex(DeepStreamRuntimeError, "fields have drifted"):
            parse_probe_payload(json.dumps(extra))

    def test_successful_sdk_and_nvdec_probe_remains_fail_closed(self) -> None:
        assessment = assess_deepstream_runtime_readiness(build_plan(), good_probe())
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["status"], "blocked")
        self.assertFalse(assessment["topology_runtime_implemented"])
        self.assertFalse(assessment["publication_ready"])
        self.assertTrue(assessment["hardware_decoder_support"]["h264"])
        self.assertTrue(assessment["hardware_decoder_support"]["h265"])
        blockers = set(assessment["blockers"])
        self.assertIn("deepstream_runtime_image_not_accepted_or_kpp_pair_piloted", blockers)
        self.assertIn(
            "deepstream_protocol_v3_sdk_bridge_not_kpp_pair_piloted",
            blockers,
        )
        self.assertNotIn("deepstream_protocol_v3_emitter_missing", blockers)
        self.assertIn("deepstream_native_policy_capability_manifest_or_hardware_binding_missing", blockers)
        self.assertIn(
            "deepstream_cpu_gpu_branch_implementation_parity_missing", blockers
        )
        self.assertIn("deepstream_frozen_branch_model_parity_evidence_missing", blockers)
        self.assertIn("deepstream_accepted_resource_v2_emitter_missing", blockers)
        self.assertIn("deepstream_hardware_pilot_pair_missing", blockers)

    def test_failed_codec_probe_adds_exact_blocker(self) -> None:
        probe = good_probe()
        probe["decoder_probes"]["h265"]["passed"] = False
        probe["decoder_probes"]["h265"]["decoded_buffers"] = 0
        probe["decoder_probes"]["h265"]["command_exit_code"] = 1
        assessment = assess_deepstream_runtime_readiness(
            build_plan(codec="h265"),
            parse_probe_payload(json.dumps(probe)),
        )
        self.assertIn("deepstream_h265_nvdec_probe_failed", assessment["blockers"])

    def test_probe_command_is_argument_safe_and_mounts_only_read_only_inputs(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="vast-deepstream-probe-command-",
            dir=os.environ.get("TMPDIR"),
        ) as temporary:
            fixture_root = Path(temporary)
            probe_dir = fixture_root / "deploy" / "deepstream" / "checkpoint"
            probe_dir.mkdir(parents=True)
            (probe_dir / "deepstream_checkpoint_capability_probe.py").write_text(
                "# synthetic command-construction fixture\n", encoding="utf-8"
            )
            for codec in ("h264", "h265"):
                source = fixture_root / "data" / "videos" / "kpp" / codec / "1.mp4"
                source.parent.mkdir(parents=True)
                source.write_bytes(f"synthetic-{codec}".encode())
            command = build_probe_command(fixture_root, image=DEEPSTREAM_IMAGE)
        self.assertIsInstance(command, list)
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("--gpus", command)
        self.assertIn("all", command)
        mounts = [
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--mount"
        ]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all("readonly" in value for value in mounts))
        self.assertTrue(all("type=bind" in value for value in mounts))
        self.assertNotIn("vast_native_gst_probe", " ".join(command))
        self.assertEqual(
            command[-1],
            "/opt/vast/checkpoint/deepstream_checkpoint_capability_probe.py",
        )
        with self.assertRaisesRegex(DeepStreamRuntimeError, "image is not frozen"):
            build_probe_command(ROOT, image="example.invalid/deepstream:latest")


if __name__ == "__main__":
    unittest.main()
