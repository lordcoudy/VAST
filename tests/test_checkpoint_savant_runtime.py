from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from checkpoint_native_policy_runtime import (  # noqa: E402
    POLICY_RPC_FD_ENV,
    POLICY_RPC_MAX_MESSAGE_BYTES,
    POLICY_RPC_SCHEMA_VERSION,
)
from checkpoint_savant_runtime import (  # noqa: E402
    FROZEN_CPU_MANIFEST_SHA256,
    PLAN_CLAIM_STATUS,
    POLICY_PATH_ENTER_FIELDS,
    POLICY_REQUEST_FIELDS,
    POLICY_RESPONSE_FIELDS,
    POLICY_TERMINAL_FIELDS,
    PROBE_CLAIM_STATUS,
    SAVANT_ENTRYPOINT,
    SAVANT_IMAGE,
    SAVANT_IMAGE_ID,
    SAVANT_IMAGE_REPO_DIGEST,
    SAVANT_VERSION,
    SavantRuntimeError,
    assess_savant_runtime_readiness,
    build_probe_command,
    build_savant_runtime_plan,
    parse_probe_payload,
    validate_savant_runtime_plan,
)
from publication_policy_contract import POLICIES  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
REQUIRED_ELEMENTS = (
    "appsrc",
    "h264parse",
    "h265parse",
    "nvv4l2decoder",
    "nvstreammux",
    "nvvideoconvert",
    "nvinfer",
    "tee",
    "queue",
    "appsink",
    "fakesink",
)


def load_inputs() -> tuple[dict, dict]:
    config = yaml.safe_load(
        (ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8")
    )
    datasets = yaml.safe_load(
        (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
    )["datasets"]
    return config, datasets


def build_plan(
    scenario: str = "checkpoint_video_dag_shared",
    *,
    codec: str = "h264",
    policy: str = "heft",
    deadline_ms: float = 33.3,
) -> dict:
    config, datasets = load_inputs()
    return build_savant_runtime_plan(
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
        "artifact_kind": "savant_checkpoint_capability_probe",
        "claim_status": PROBE_CLAIM_STATUS,
        "system": "savant",
        "image": SAVANT_IMAGE,
        "image_id": SAVANT_IMAGE_ID,
        "image_repo_digest": SAVANT_IMAGE_REPO_DIGEST,
        "savant_version": SAVANT_VERSION,
        "savant_import_path": "/usr/local/lib/python3.10/dist-packages/savant/__init__.py",
        "savant_entrypoint": list(SAVANT_ENTRYPOINT),
        "deepstream_sdk_version": "7.0.0",
        "gpu": {
            "name": "NVIDIA GeForce RTX 3060",
            "uuid": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
            "driver_version": "610.47",
            "visible": True,
        },
        "required_elements": {
            name: {
                "available": True,
                "plugin_filename": f"/opt/nvidia/deepstream/libgst{name}.so",
                "plugin_version": "7.0.0",
            }
            for name in REQUIRED_ELEMENTS
        },
        "decoder_probes": {
            codec: {
                "passed": True,
                "decoder_factory": "nvv4l2decoder",
                "parser_factory": f"{codec}parse",
                "gpu_id": 0,
                "decoded_buffers": 1,
                "source_sha256": hashlib.sha256(codec.encode()).hexdigest(),
                "pipeline_status": "sample_observed",
                "output_caps": (
                    "video/x-raw(memory:NVMM), format=(string)NV12, "
                    "gpu-id=(int)0"
                ),
                "buffer_evidence": "appsink_sample",
            }
            for codec in ("h264", "h265")
        },
        "dedicated_checkpoint_runtime_present": False,
        "protocol_v3_policy_adapter_present": False,
        "resource_v2_emitter_present": False,
        "generic_probe_executed": False,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }


class SavantRuntimePlanTests(unittest.TestCase):
    def test_baseline_has_exactly_twenty_four_isolated_savant_module_processes(self) -> None:
        plan = build_plan("checkpoint_independent_processes_baseline")
        self.assertEqual(plan["claim_status"], PLAN_CLAIM_STATUS)
        self.assertFalse(plan["topology_runtime_implemented"])
        self.assertFalse(plan["publication_ready"])
        self.assertEqual(plan["topology_kind"], "independent_processes")
        self.assertEqual(plan["stream_count"], 6)
        self.assertEqual(plan["queued_branches_per_stream"], 4)
        self.assertEqual(len(plan["processes"]), 24)
        self.assertEqual({value["branch"] for value in plan["processes"]}, set(BRANCHES))
        self.assertEqual(len({value["process_id"] for value in plan["processes"]}), 24)
        self.assertRegex(plan["topology_plan_sha256"], r"^[0-9a-f]{64}$")
        for process in plan["processes"]:
            self.assertEqual(process["process_isolation"], "os_process")
            self.assertEqual(process["module_entrypoint"], list(SAVANT_ENTRYPOINT))
            self.assertEqual(process["branches"], [process["branch"]])
            self.assertEqual(process["module_config_status"], "missing_not_built")
            factories = [value["factory"] for value in process["physical_pipeline"]]
            self.assertEqual(
                factories[:6],
                [
                    "appsrc",
                    "h264parse",
                    "nvv4l2decoder",
                    "nvstreammux",
                    "nvvideoconvert",
                    "queue",
                ],
            )
            self.assertEqual(factories[6:8], ["vastsavantpolicydispatch", "vastsavantbranchterminal"])

    def test_shared_has_six_decode_preprocess_modules_and_four_queued_routes(self) -> None:
        plan = build_plan()
        self.assertEqual(plan["topology_kind"], "shared_video_dag")
        self.assertEqual(len(plan["processes"]), 6)
        for process in plan["processes"]:
            self.assertEqual(process["process_isolation"], "os_process")
            self.assertEqual(process["module_entrypoint"], list(SAVANT_ENTRYPOINT))
            self.assertEqual(process["branches"], list(BRANCHES))
            self.assertEqual(
                [value["factory"] for value in process["shared_prefix"]],
                [
                    "appsrc",
                    "h264parse",
                    "nvv4l2decoder",
                    "nvstreammux",
                    "nvvideoconvert",
                    "tee",
                ],
            )
            self.assertEqual(len(process["routes"]), 4)
            self.assertEqual({route["branch"] for route in process["routes"]}, set(BRANCHES))
            for route in process["routes"]:
                queue = route["elements"][0]
                self.assertEqual(queue["factory"], "queue")
                self.assertEqual(queue["max_size_buffers"], 1)
                self.assertEqual(queue["leaky"], "upstream")
                self.assertEqual(route["elements"][1]["factory"], "vastsavantpolicydispatch")
                self.assertEqual(route["elements"][2]["factory"], "vastsavantbranchterminal")

    def test_policy_protocol_and_nvidia_cuda_contract_are_exact(self) -> None:
        plan = build_plan()
        binding = plan["policy_binding"]
        self.assertEqual(binding["rpc_schema_version"], POLICY_RPC_SCHEMA_VERSION)
        self.assertEqual(binding["fd_environment"], POLICY_RPC_FD_ENV)
        self.assertEqual(binding["max_message_bytes"], POLICY_RPC_MAX_MESSAGE_BYTES)
        self.assertEqual(binding["request_fields"], list(POLICY_REQUEST_FIELDS))
        self.assertEqual(binding["response_fields"], list(POLICY_RESPONSE_FIELDS))
        self.assertEqual(binding["path_enter_fields"], list(POLICY_PATH_ENTER_FIELDS))
        self.assertEqual(binding["terminal_fields"], list(POLICY_TERMINAL_FIELDS))
        gpu = binding["nvidia_gpu_path_requirements"]
        self.assertEqual(gpu["factory"], "nvinfer")
        self.assertEqual(gpu["backend"], "deepstream_tensorrt")
        self.assertEqual(gpu["device_api"], "NVIDIA_CUDA")
        self.assertFalse(gpu["gvadetect_gpu_label_accepted"])
        self.assertFalse(plan["model_binding"]["peoplenet_sample_model_accepted"])
        self.assertEqual(
            plan["model_binding"]["frozen_cpu_manifest_sha256"],
            FROZEN_CPU_MANIFEST_SHA256,
        )

    def test_pair_uses_identical_frozen_sources_and_schedule_gate(self) -> None:
        baseline = build_plan("checkpoint_independent_processes_baseline")
        shared = build_plan("checkpoint_video_dag_shared")
        self.assertEqual(baseline["sources"], shared["sources"])
        self.assertEqual(baseline["pair_schedule_gate"], shared["pair_schedule_gate"])
        self.assertEqual(
            baseline["pair_schedule_gate"]["required_rule"],
            "equal_measurement_schedule_fingerprint_sha256",
        )
        self.assertEqual(
            baseline["admission_binding"]["selection_basis"],
            "decode_order_schedule_offset_half_open",
        )
        self.assertNotEqual(baseline["topology_plan_sha256"], shared["topology_plan_sha256"])

    def test_all_frozen_matrix_coordinates_propagate_without_drift(self) -> None:
        config, datasets = load_inputs()
        for scenario in (
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        ):
            for codec in ("h264", "h265"):
                for policy in POLICIES:
                    for deadline_ms in config["benchmark"]["deadline_ms"]:
                        with self.subTest(
                            scenario=scenario,
                            codec=codec,
                            policy=policy,
                            deadline_ms=deadline_ms,
                        ):
                            plan = build_savant_runtime_plan(
                                config=config,
                                datasets=datasets,
                                scenario=scenario,
                                codec=codec,
                                policy=policy,
                                deadline_ms=deadline_ms,
                            )
                            self.assertEqual(plan["codec"], codec)
                            self.assertEqual(plan["dataset"], f"kpp_real_{codec}")
                            self.assertEqual(plan["parser_factory"], f"{codec}parse")
                            self.assertEqual(plan["policy"], policy)
                            self.assertEqual(plan["deadline_ms"], float(deadline_ms))
                            self.assertTrue(
                                all(
                                    value["source_codec"] == codec
                                    for value in plan["sources"]
                                )
                            )
                            self.assertEqual(
                                len(plan["processes"]),
                                24 if scenario.endswith("baseline") else 6,
                            )
                            validate_savant_runtime_plan(plan)

    def test_matrix_dataset_and_topology_relabel_drift_fail_closed(self) -> None:
        config, datasets = load_inputs()
        for values in (
            {"codec": "vp9", "policy": "heft", "deadline_ms": 100.0},
            {"codec": "h264", "policy": "random", "deadline_ms": 100.0},
            {"codec": "h264", "policy": "heft", "deadline_ms": 17.0},
        ):
            with self.subTest(values=values), self.assertRaises(ContractError):
                build_savant_runtime_plan(
                    config=config,
                    datasets=datasets,
                    scenario="checkpoint_video_dag_shared",
                    **values,
                )
        drifted = copy.deepcopy(config)
        drifted["scenarios"]["checkpoint_video_dag_shared"]["workload"]["streams"] = 5
        with self.assertRaisesRegex(ContractError, "six logical streams"):
            build_savant_runtime_plan(
                config=drifted,
                datasets=datasets,
                scenario="checkpoint_video_dag_shared",
                codec="h264",
                policy="heft",
                deadline_ms=100.0,
            )
        image_drift = copy.deepcopy(config)
        image_drift["systems"]["savant"]["container_image"] = "example.invalid/savant:latest"
        with self.assertRaisesRegex(ContractError, "pinned image"):
            build_savant_runtime_plan(
                config=image_drift,
                datasets=datasets,
                scenario="checkpoint_video_dag_shared",
                codec="h264",
                policy="heft",
                deadline_ms=100.0,
            )
        bad_dataset = copy.deepcopy(datasets)
        bad_dataset["kpp_real_h264"]["streams"][0]["codec_name"] = "h265"
        with self.assertRaisesRegex(ContractError, "codec"):
            build_savant_runtime_plan(
                config=config,
                datasets=bad_dataset,
                scenario="checkpoint_video_dag_shared",
                codec="h264",
                policy="heft",
                deadline_ms=100.0,
            )

        plan = build_plan()
        software = copy.deepcopy(plan)
        software["processes"][0]["shared_prefix"][2]["factory"] = "avdec_h264"
        with self.assertRaisesRegex(SavantRuntimeError, "nvv4l2decoder"):
            validate_savant_runtime_plan(software)
        collapsed = copy.deepcopy(plan)
        collapsed["processes"].pop()
        with self.assertRaisesRegex(SavantRuntimeError, "six shared"):
            validate_savant_runtime_plan(collapsed)
        no_queue = copy.deepcopy(plan)
        no_queue["processes"][0]["routes"][0]["elements"].pop(0)
        with self.assertRaisesRegex(SavantRuntimeError, "queue"):
            validate_savant_runtime_plan(no_queue)
        relabelled = copy.deepcopy(plan)
        relabelled["runtime_executable"] = "/usr/local/bin/vast_native_gst_probe"
        with self.assertRaisesRegex(SavantRuntimeError, "generic probe"):
            validate_savant_runtime_plan(relabelled)
        gva_gpu = copy.deepcopy(plan)
        gva_gpu["processes"][0]["routes"][0]["elements"][1]["selected_execution_paths"]["gpu"]["factory"] = "gvadetect"
        with self.assertRaisesRegex(SavantRuntimeError, "NVIDIA CUDA"):
            validate_savant_runtime_plan(gva_gpu)


class SavantCapabilityProbeTests(unittest.TestCase):
    def test_probe_is_strict_and_cannot_claim_generic_or_publication_evidence(self) -> None:
        payload = good_probe()
        self.assertEqual(parse_probe_payload(json.dumps(payload)), payload)
        for field in ("publication_ready", "accepted_measurement_evidence_emitted"):
            bad = copy.deepcopy(payload)
            bad[field] = True
            with self.subTest(field=field), self.assertRaises(SavantRuntimeError):
                parse_probe_payload(json.dumps(bad))
        generic = copy.deepcopy(payload)
        generic["generic_probe_executed"] = True
        with self.assertRaisesRegex(SavantRuntimeError, "generic probe"):
            parse_probe_payload(json.dumps(generic))
        wrong_digest = copy.deepcopy(payload)
        wrong_digest["image_id"] = "sha256:" + "b" * 64
        with self.assertRaisesRegex(SavantRuntimeError, "immutable image"):
            parse_probe_payload(json.dumps(wrong_digest))
        extra = copy.deepcopy(payload)
        extra["derived_gpu_label"] = "GPU"
        with self.assertRaisesRegex(SavantRuntimeError, "fields have drifted"):
            parse_probe_payload(json.dumps(extra))
        inferred = copy.deepcopy(payload)
        inferred["decoder_probes"]["h264"]["buffer_evidence"] = "exit_code_inference"
        with self.assertRaisesRegex(SavantRuntimeError, "appsink"):
            parse_probe_payload(json.dumps(inferred))

    def test_successful_savant_sdk_and_nvdec_probe_remains_blocked(self) -> None:
        assessment = assess_savant_runtime_readiness(build_plan(), good_probe())
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(assessment["savant_sdk_probe_passed"])
        self.assertTrue(assessment["cuda_tensorrt_capability_detected"])
        self.assertFalse(assessment["frozen_cpu_cuda_parity_ready"])
        self.assertEqual(assessment["hardware_decoder_support"], {"h264": True, "h265": True})
        blockers = set(assessment["blockers"])
        for blocker in (
            "savant_dedicated_checkpoint_runtime_missing",
            "savant_frozen_topology_module_configs_missing",
            "savant_common_admission_protocol_v3_binding_missing",
            "savant_protocol_v3_bridge_not_sdk_bound_or_hardware_piloted",
            "savant_native_policy_seqpacket_binding_missing",
            "savant_equivalent_cpu_cuda_branch_models_missing",
            "savant_accepted_resource_v2_emitter_missing",
            "savant_hardware_pilot_pair_missing",
        ):
            self.assertIn(blocker, blockers)

    def test_failed_h265_or_required_element_probe_adds_precise_blocker(self) -> None:
        probe = good_probe()
        probe["decoder_probes"]["h265"].update(
            passed=False,
            decoded_buffers=0,
            pipeline_status="eos_without_buffer",
            output_caps="",
            buffer_evidence="no_decoded_sample",
        )
        probe["required_elements"]["nvinfer"]["available"] = False
        assessment = assess_savant_runtime_readiness(
            build_plan(codec="h265"),
            parse_probe_payload(json.dumps(probe)),
        )
        self.assertIn("savant_h265_nvdec_probe_failed", assessment["blockers"])
        self.assertIn("savant_gstreamer_element_missing:nvinfer", assessment["blockers"])
        self.assertFalse(assessment["cuda_tensorrt_capability_detected"])

    def test_probe_command_is_pinned_argument_safe_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="vast-savant-probe-command-",
        ) as temporary:
            fixture_root = Path(temporary)
            probe_dir = fixture_root / "deploy" / "savant" / "checkpoint"
            probe_dir.mkdir(parents=True)
            (probe_dir / "savant_checkpoint_capability_probe.py").write_text(
                "# synthetic command-construction fixture\n", encoding="utf-8"
            )
            for codec in ("h264", "h265"):
                source = fixture_root / "data" / "videos" / "kpp" / codec / "1.mp4"
                source.parent.mkdir(parents=True)
                source.write_bytes(f"synthetic-{codec}".encode())
            command = build_probe_command(fixture_root)
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertEqual(command[command.index("--entrypoint") + 1], "python3")
        self.assertEqual(command[command.index("--gpus") + 1], "all")
        mounts = [
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--mount"
        ]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all("type=bind" in value and "readonly" in value for value in mounts))
        self.assertNotIn("vast_native_gst_probe", " ".join(command))
        self.assertNotIn("checkpoint_publication_runtime", " ".join(command))
        self.assertEqual(command[-2], SAVANT_IMAGE)
        self.assertEqual(
            command[-1],
            "/opt/vast/checkpoint/savant_checkpoint_capability_probe.py",
        )
        with self.assertRaisesRegex(SavantRuntimeError, "image is not frozen"):
            build_probe_command(ROOT, image="ghcr.io/example/savant:latest")


if __name__ == "__main__":
    unittest.main()
