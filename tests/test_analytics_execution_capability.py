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

from analytics_execution_capability import (  # noqa: E402
    assess_execution_layer,
    load_execution_layer_config,
)
from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
)


CPU_BASE_ID = "sha256:" + hashlib.sha256(b"cpu-base").hexdigest()
GPU_BASE_ID = "sha256:" + hashlib.sha256(b"gpu-base").hexdigest()
CPU_WORKER_ID = "sha256:" + hashlib.sha256(b"cpu-worker").hexdigest()
GPU_WORKER_ID = "sha256:" + hashlib.sha256(b"gpu-worker").hexdigest()
SOURCE_SHA = hashlib.sha256(b"source").hexdigest()
MODEL_SHA = hashlib.sha256(b"model").hexdigest()
WEIGHTS_SHA = hashlib.sha256(b"weights").hexdigest()
CPU_IMPLEMENTATION_SHA = hashlib.sha256(b"cpu-implementation").hexdigest()
GPU_IMPLEMENTATION_SHA = hashlib.sha256(b"gpu-implementation").hexdigest()


def config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_layer_config",
        "config_id": "kpp-analytics-execution-layer-v1",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "model_parity_manifest": "configs/checkpoint_analytics_model_parity.yaml",
        "transport": {
            "kind": "unix_seqpacket_scm_rights_sealed_memfd",
            "max_control_bytes": 65536,
            "max_tensor_bytes": 67108864,
            "max_inflight_requests_per_worker": 1,
        },
        "workers": {
            "cpu": {
                "engine": ENGINE_OPENVINO_CPU,
                "base_image": "vast/openvino-native-probe:dlstreamer-2026.1",
                "base_image_id": CPU_BASE_ID,
                "image": "vast/analytics-openvino-worker:v1",
                "image_id": CPU_WORKER_ID,
                "worker_implementation_sha256": CPU_IMPLEMENTATION_SHA,
                "entrypoint": "/opt/vast/analytics/openvino_worker.py",
                "requires_nvidia_runtime": False,
            },
            "gpu": {
                "engine": ENGINE_TENSORRT_CUDA,
                "base_image": "vast/deepstream-native-probe:7.0",
                "base_image_id": GPU_BASE_ID,
                "image": "vast/analytics-tensorrt-worker:v1",
                "image_id": GPU_WORKER_ID,
                "worker_implementation_sha256": GPU_IMPLEMENTATION_SHA,
                "entrypoint": "/opt/vast/bin/vast_tensorrt_worker",
                "requires_nvidia_runtime": True,
            },
        },
    }


def capability(resource: str) -> dict[str, object]:
    cpu = resource == "cpu"
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": ENGINE_OPENVINO_CPU if cpu else ENGINE_TENSORRT_CUDA,
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1.0" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Intel CPU" if cpu else "GPU-00000000-0000-0000-0000-000000000001",
        "native_inference_api": (
            "openvino.CompiledModel.__call__"
            if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "worker_implementation_sha256": (
            CPU_IMPLEMENTATION_SHA if cpu else GPU_IMPLEMENTATION_SHA
        ),
        "socket_seqpacket": True,
        "scm_rights": True,
        "memfd_sealing": True,
        "model_loaded": False,
        "inference_performed": False,
    }


def runner_for(configuration: dict[str, object]):
    calls: list[list[str]] = []
    image_ids = {
        configuration["workers"]["cpu"]["base_image"]: configuration["workers"]["cpu"]["base_image_id"],
        configuration["workers"]["gpu"]["base_image"]: configuration["workers"]["gpu"]["base_image_id"],
        configuration["workers"]["cpu"]["image"]: configuration["workers"]["cpu"]["image_id"],
        configuration["workers"]["gpu"]["image"]: configuration["workers"]["gpu"]["image_id"],
    }

    def runner(command: list[str]) -> str:
        calls.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            image = command[-1]
            labels = {}
            for resource in ("cpu", "gpu"):
                worker = configuration["workers"][resource]
                if image == worker["image"]:
                    labels = {
                        "org.vast.analytics_worker.base_image_id": worker["base_image_id"],
                        "org.vast.analytics_worker.engine": worker["engine"],
                    }
            return json.dumps({
                "Id": image_ids[image],
                "Architecture": "amd64",
                "Os": "linux",
                "Config": {"Labels": labels},
            })
        if command[:2] == ["docker", "run"]:
            resource = "gpu" if "--gpus" in command else "cpu"
            return json.dumps(capability(resource))
        raise AssertionError(command)

    return runner, calls


def ready_parity(*args, **kwargs) -> dict[str, object]:
    return {
        "publication_ready": True,
        "manifest_identity_sha256": hashlib.sha256(b"parity").hexdigest(),
        "blockers": [],
        "branches": {},
    }


class AnalyticsExecutionCapabilityTests(unittest.TestCase):
    def test_two_pinned_native_workers_and_model_parity_are_all_required(self) -> None:
        value = config()
        runner, calls = runner_for(value)
        result = assess_execution_layer(
            value,
            project_root=ROOT,
            command_runner=runner,
            model_parity_assessor=ready_parity,
            kernel_probe=lambda: {
                "socket_seqpacket": True,
                "scm_rights": True,
                "memfd_sealing": True,
            },
        )
        self.assertTrue(result["execution_layer_ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(sum(command[:3] == ["docker", "image", "inspect"] for command in calls), 4)
        self.assertEqual(sum(command[:2] == ["docker", "run"] for command in calls), 2)
        gpu_run = next(command for command in calls if command[:2] == ["docker", "run"] and "--gpus" in command)
        self.assertIn("all", gpu_run)

    def test_wrong_image_identity_and_openvino_gpu_claim_fail_closed(self) -> None:
        value = config()
        runner, _ = runner_for(value)

        def compromised_runner(command: list[str]) -> str:
            if command[:3] == ["docker", "image", "inspect"] and command[-1] == value["workers"]["gpu"]["image"]:
                return json.dumps({"Id": "sha256:" + "f" * 64, "Architecture": "amd64", "Os": "linux"})
            if command[:2] == ["docker", "run"] and "--gpus" in command:
                probe = capability("gpu")
                probe["runtime_name"] = "OpenVINO"
                probe["device_api"] = "GPU"
                return json.dumps(probe)
            return runner(command)

        result = assess_execution_layer(
            value,
            project_root=ROOT,
            command_runner=compromised_runner,
            model_parity_assessor=ready_parity,
            kernel_probe=lambda: {
                "socket_seqpacket": True,
                "scm_rights": True,
                "memfd_sealing": True,
            },
        )
        self.assertFalse(result["execution_layer_ready"])
        self.assertIn("worker_image_id_mismatch:gpu", result["blockers"])
        self.assertIn("worker_probe_contract_invalid:gpu", result["blockers"])
        self.assertFalse(result["openvino_gpu_counted_as_nvidia_cuda"])

    def test_incomplete_model_parity_and_missing_kernel_primitive_block_execution(self) -> None:
        value = config()
        runner, _ = runner_for(value)
        result = assess_execution_layer(
            value,
            project_root=ROOT,
            command_runner=runner,
            model_parity_assessor=lambda *args, **kwargs: {
                "publication_ready": False,
                "manifest_identity_sha256": hashlib.sha256(b"parity").hexdigest(),
                "blockers": ["branch:plate_number:source_artifact_missing"],
                "branches": {},
            },
            kernel_probe=lambda: {
                "socket_seqpacket": True,
                "scm_rights": True,
                "memfd_sealing": False,
            },
        )
        self.assertFalse(result["execution_layer_ready"])
        self.assertIn("kernel_capability_missing:memfd_sealing", result["blockers"])
        self.assertIn("model_parity_not_ready", result["blockers"])
        self.assertIn("model_parity:branch:plate_number:source_artifact_missing", result["blockers"])

    def test_worker_implementation_mismatch_blocks_execution(self) -> None:
        value = config()
        runner, _ = runner_for(value)

        def stale_worker_runner(command: list[str]) -> str:
            if command[:2] == ["docker", "run"] and "--gpus" not in command:
                probe = capability("cpu")
                probe["worker_implementation_sha256"] = hashlib.sha256(
                    b"stale-cpu-implementation"
                ).hexdigest()
                return json.dumps(probe)
            return runner(command)

        result = assess_execution_layer(
            value,
            project_root=ROOT,
            command_runner=stale_worker_runner,
            model_parity_assessor=ready_parity,
            kernel_probe=lambda: {
                "socket_seqpacket": True,
                "scm_rights": True,
                "memfd_sealing": True,
            },
        )
        self.assertFalse(result["execution_layer_ready"])
        self.assertIn("worker_implementation_sha256_mismatch:cpu", result["blockers"])

    def test_config_is_exact_and_current_repository_config_remains_blocked(self) -> None:
        loaded = load_execution_layer_config(ROOT / "configs" / "analytics_execution_layer.yaml")
        self.assertEqual(loaded["protocol_identity_sha256"], PROTOCOL_IDENTITY_SHA256)
        for resource in ("cpu", "gpu"):
            self.assertRegex(
                loaded["workers"][resource]["worker_implementation_sha256"],
                r"^[0-9a-f]{64}$",
            )
        changed = copy.deepcopy(loaded)
        changed["unexpected"] = True
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "fields have drifted"):
                load_execution_layer_config(path)


if __name__ == "__main__":
    unittest.main()
