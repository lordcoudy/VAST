from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from checkpoint_openvino_runtime import (  # noqa: E402
    BASE_PUBLICATION_BLOCKERS,
    BRANCHES,
    REQUIRED_GSTREAMER_ELEMENTS,
    build_device_probe_command,
    build_openvino_topology_plan,
    build_parser,
    classify_openvino_devices,
    load_deployment_contract,
    preflight_openvino_checkpoint,
    validate_openvino_topology_plan,
)


IMAGE_SHA = hashlib.sha256(b"openvino-checkpoint-image").hexdigest()


def image_payload() -> str:
    return json.dumps(
        {
            "Id": f"sha256:{IMAGE_SHA}",
            "RepoDigests": [f"vast/openvino-checkpoint@sha256:{IMAGE_SHA}"],
            "Architecture": "amd64",
            "Os": "linux",
        }
    )


def device_probe_payload(*, devices: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_device_probe",
            "openvino_version": "2026.1.0",
            "available_devices": devices,
            "gstreamer_elements": {
                element: {"available": True, "factory": element}
                for element in REQUIRED_GSTREAMER_ELEMENTS
            },
        }
    )


class TopologyPlanTests(unittest.TestCase):
    def test_h264_baseline_has_24_isolated_branch_workers(self) -> None:
        plan = build_openvino_topology_plan(
            scenario="checkpoint_independent_processes_baseline",
            codec="h264",
        )
        validate_openvino_topology_plan(plan)
        self.assertEqual(plan["system"], "openvino_gstreamer")
        self.assertEqual(plan["codec"], "h264")
        self.assertEqual(plan["dataset"], "kpp_iss_publication_v3_h264")
        self.assertEqual(plan["topology_kind"], "independent_processes")
        self.assertEqual(plan["decoder"]["parser_factory"], "h264parse")
        self.assertEqual(plan["process_counts"]["topology_workers"], 24)
        self.assertEqual(plan["process_counts"]["source_coordinators"], 6)
        self.assertEqual(plan["queued_branches_per_stream"], 4)
        workers = plan["workers"]
        self.assertEqual(len(workers), 24)
        self.assertEqual(len({worker["process_id"] for worker in workers}), 24)
        self.assertEqual({worker["branch_id"] for worker in workers}, set(BRANCHES))
        self.assertTrue(all(worker["process_kind"] == "independent_branch_worker" for worker in workers))
        self.assertTrue(all(worker["analytics_queue"]["max_buffers"] == 1 for worker in workers))
        self.assertFalse(plan["measurement_execution_allowed"])

    def test_h265_shared_has_6_graphs_and_four_queued_branches_each(self) -> None:
        plan = build_openvino_topology_plan(
            scenario="checkpoint_video_dag_shared",
            codec="h265",
        )
        validate_openvino_topology_plan(plan)
        self.assertEqual(plan["codec"], "h265")
        self.assertEqual(plan["dataset"], "kpp_iss_publication_v3_h265")
        self.assertEqual(plan["topology_kind"], "shared_video_dag")
        self.assertEqual(plan["decoder"]["parser_factory"], "h265parse")
        self.assertEqual(plan["decoder"]["compressed_caps"], "video/x-h265")
        self.assertEqual(plan["process_counts"]["topology_workers"], 6)
        self.assertEqual(len(plan["workers"]), 6)
        for graph in plan["workers"]:
            self.assertEqual(graph["process_kind"], "shared_video_dag_worker")
            self.assertEqual(graph["shared_prefix"], ["decode", "preprocess"])
            self.assertEqual(graph["fanout_factory"], "tee")
            self.assertEqual(len(graph["branches"]), 4)
            self.assertEqual({branch["branch_id"] for branch in graph["branches"]}, set(BRANCHES))
            self.assertTrue(all(branch["queue_required"] is True for branch in graph["branches"]))
            self.assertTrue(all(branch["analytics_queue"]["max_buffers"] == 1 for branch in graph["branches"]))

    def test_plan_identity_is_immutable_and_tamper_evident(self) -> None:
        plan = build_openvino_topology_plan(
            scenario="checkpoint_video_dag_shared",
            codec="h264",
        )
        self.assertRegex(plan["identity"]["sha256"], r"^[0-9a-f]{64}$")
        tampered = copy.deepcopy(plan)
        tampered["workers"][0]["branches"][0]["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "identity|queue"):
            validate_openvino_topology_plan(tampered)

    def test_rejects_unsupported_codec_or_scenario(self) -> None:
        with self.assertRaisesRegex(ContractError, "codec"):
            build_openvino_topology_plan(
                scenario="checkpoint_video_dag_shared",
                codec="vp9",
            )
        with self.assertRaisesRegex(ContractError, "scenario"):
            build_openvino_topology_plan(scenario="generic", codec="h264")

    def test_deployment_contract_is_explicitly_non_measurement(self) -> None:
        contract = load_deployment_contract(ROOT)
        self.assertEqual(contract["system"], "openvino_gstreamer")
        self.assertEqual(contract["codecs"], ["h264", "h265"])
        self.assertEqual(contract["baseline_worker_processes"], 24)
        self.assertEqual(contract["shared_graph_processes"], 6)
        self.assertEqual(contract["branches"], list(BRANCHES))
        self.assertFalse(contract["measurement_execution_allowed"])
        self.assertEqual(contract["status"], "capability_preflight_and_plan_only")


class DeviceClassificationTests(unittest.TestCase):
    def test_nvidia_named_device_is_never_counted_as_openvino_gpu(self) -> None:
        classified = classify_openvino_devices(
            [
                {"device_id": "CPU", "full_device_name": "Intel Core i7-14700K"},
                {"device_id": "GPU.0", "full_device_name": "NVIDIA GeForce RTX 3060"},
            ]
        )
        self.assertEqual(classified["cpu_devices"], ["CPU"])
        self.assertEqual(classified["intel_openvino_gpu_devices"], [])
        self.assertEqual(classified["rejected_gpu_devices"], ["GPU.0"])

    def test_intel_gpu_must_be_reported_by_openvino_and_vendor_verified(self) -> None:
        classified = classify_openvino_devices(
            [
                {"device_id": "CPU", "full_device_name": "Intel Core i7-14700K"},
                {"device_id": "GPU.0", "full_device_name": "Intel Arc A770 Graphics"},
            ]
        )
        self.assertEqual(classified["intel_openvino_gpu_devices"], ["GPU.0"])
        self.assertEqual(classified["rejected_gpu_devices"], [])


class CapabilityPreflightTests(unittest.TestCase):
    def test_cpu_only_image_is_not_publication_ready_with_exact_blockers(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str]) -> str:
            commands.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                return image_payload()
            if command and command[0] == "nvidia-smi":
                return "NVIDIA GeForce RTX 3060, GPU-host-uuid, 555.42\n"
            if command[:2] == ["docker", "run"]:
                return device_probe_payload(
                    devices=[
                        {
                            "device_id": "CPU",
                            "full_device_name": "Intel Core i7-14700K",
                            "device_type": "INTEGRATED",
                            "vendor": "Intel",
                        }
                    ]
                )
            raise AssertionError(command)

        result = preflight_openvino_checkpoint(
            image="vast/openvino-checkpoint:frozen",
            project_root=ROOT,
            command_runner=runner,
        )
        self.assertTrue(result["capability_preflight_passed"])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["topology_runtime_implemented"])
        self.assertFalse(result["measurement_execution_allowed"])
        self.assertFalse(result["generic_probe_relabelled"])
        self.assertEqual(tuple(result["blockers"]), BASE_PUBLICATION_BLOCKERS)
        self.assertEqual(result["openvino_devices"]["cpu_devices"], ["CPU"])
        self.assertEqual(result["openvino_devices"]["intel_openvino_gpu_devices"], [])
        self.assertEqual(result["nvidia_host_gpus"][0]["name"], "NVIDIA GeForce RTX 3060")
        self.assertEqual(len(result["topology_plan_identities"]), 4)
        self.assertTrue(all("--duration" not in command for command in commands))
        self.assertTrue(all("checkpoint_publication_runtime" not in " ".join(command) for command in commands))

    def test_missing_gstreamer_element_adds_fail_closed_blocker(self) -> None:
        payload = json.loads(
            device_probe_payload(
                devices=[{"device_id": "CPU", "full_device_name": "Intel CPU"}]
            )
        )
        payload["gstreamer_elements"]["h265parse"]["available"] = False

        def runner(command: list[str]) -> str:
            if command[:3] == ["docker", "image", "inspect"]:
                return image_payload()
            if command and command[0] == "nvidia-smi":
                return "NVIDIA GeForce RTX 3060, GPU-host-uuid, 555.42\n"
            if command[:2] == ["docker", "run"]:
                return json.dumps(payload)
            raise AssertionError(command)

        result = preflight_openvino_checkpoint(
            image="vast/openvino-checkpoint:frozen",
            project_root=ROOT,
            command_runner=runner,
        )
        self.assertIn(
            "required_gstreamer_element_missing:h265parse",
            result["blockers"],
        )

    def test_probe_command_is_read_only_capability_check_not_measurement(self) -> None:
        command = build_device_probe_command(
            image="vast/openvino-checkpoint:frozen",
            project_root=ROOT,
        )
        rendered = " ".join(command)
        self.assertIn("--network none", rendered)
        self.assertIn("--read-only", command)
        self.assertIn("probe_openvino_devices.py", rendered)
        self.assertNotIn("--duration", command)
        self.assertNotIn("--output-dir", command)
        self.assertNotIn("vast_native_gst_probe", rendered)

    def test_cli_has_plan_and_preflight_only(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args(["plan", "--codec", "h264", "--scenario", "checkpoint_video_dag_shared"]).command,
            "plan",
        )
        self.assertEqual(
            parser.parse_args(["preflight", "--image", "image:frozen"]).command,
            "preflight",
        )
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "--image", "image:frozen"])


if __name__ == "__main__":
    unittest.main()
