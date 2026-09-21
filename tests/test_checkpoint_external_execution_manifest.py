from __future__ import annotations

import copy
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
import checkpoint_gstreamer_runtime as coordinator
import checkpoint_native_policy_runtime as policy_runtime
import publication_policy_qualification_runtime_inputs_v2 as producer
from analytics_execution_endpoint import expected_capability_from_binding_and_probe
from checkpoint_deepstream_protocol_bridge import analytics_backend_identity
from test_checkpoint_native_policy_runtime import capability_manifest, calibration


def worker_manifest_fixture(execution_descriptor=None):
    fixture = SimpleNamespace()
    fixture.policy = capability_manifest()
    fixture.bindings = {}
    fixture.probes = {}
    engines = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}
    for resource in producer.RESOURCES:
        fixture.probes[resource] = json.loads((ROOT / "artifacts/analytics_runtime_probes/publication_v3" / f"{resource}_runtime_probe.json").read_bytes())
    for branch in producer.BRANCHES:
        for resource, engine in engines.items():
            binding = json.loads((ROOT / "artifacts/analytics_execution_bindings/publication_v3" / f"{branch}.{engine}.json").read_bytes())
            fixture.bindings[(branch, resource)] = binding
            cap = expected_capability_from_binding_and_probe(binding=binding, runtime_probe=fixture.probes[resource], resource=resource)
            for system in producer.SYSTEMS:
                p = fixture.policy["systems"][system]["branches"][branch][resource]
                identity = p["runtime_identity"]
                identity.update(worker_image_digest=cap["worker_image_id"], implementation_version="sha256:" + cap["worker_implementation_sha256"], terminal_detector=f"{cap['model_id']};model_sha256={cap['source_model_sha256']}", terminal_backend=analytics_backend_identity(cap))
                p.update(identity)
    descriptor = execution_descriptor or {"path": "configs/worker-config.json", "size_bytes": 10, "sha256": "a" * 64}
    execution_pin = SimpleNamespace(relative=descriptor["path"], size=descriptor["size_bytes"], sha256=descriptor["sha256"])
    fixture.inventory = SimpleNamespace(root=ROOT, analytics_bindings=fixture.bindings, runtime_probes=fixture.probes, capability=fixture.policy, analytics_execution_pin=execution_pin)
    fixture.preprocessing = fixture.bindings[("plate_number", "cpu")]["preprocessing_contract_sha256"]

    return fixture


class ExternalExecutionManifestTests(unittest.TestCase):
    def setUp(self):
        self.__dict__.update(worker_manifest_fixture().__dict__)

    def asset(self, system):
        path, payload, descriptor = producer._adapter_asset(self.inventory, system=system, final_root=ROOT / "artifacts/external-manifest-test")
        self.assertEqual(descriptor["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(descriptor["size_bytes"], len(payload))
        self.assertEqual(descriptor["container_path"], "/workspace/project/" + path.relative_to(ROOT).as_posix())
        return json.loads(payload)

    def assess(self, value, system, policy=None):
        return policy_runtime.assess_gstreamer_native_policy_execution_manifest(value, system=system, capability_manifest=policy or self.policy, preprocessing_contract_sha256=self.preprocessing)

    def test_native_policy_import_does_not_require_sdk_bridge(self):
        # Native final images deliberately omit this SDK-only module.
        code = "import sys; sys.path.insert(0, sys.argv[1]); sys.modules['checkpoint_deepstream_protocol_bridge'] = None; import checkpoint_native_policy_runtime"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "scripts")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_producer_manifest_passes_real_coordinator_startup_for_both_systems(self):
        class WorkerBoundaryReached(Exception):
            pass
        for system in ("openvino_gva", "gstreamer_custom"):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.asset(system)
                self.assertEqual(manifest["artifact_kind"], "vast_checkpoint_external_analytics_execution_manifest_v1")
                self.assertEqual(manifest["execution_config"]["path"], "configs/worker-config.json")
                self.assertTrue(self.assess(manifest, system)["passed"])
                paths = {}
                for name, value in (("execution", manifest), ("policy", self.policy), ("calibration", calibration(self.policy, system))):
                    paths[name] = root / (name + ".json")
                    paths[name].write_text(json.dumps(value))
                args = ["--config", str(ROOT / "configs/experiments.yaml"), "--datasets", str(ROOT / "configs/datasets.yaml"), "--scenario", "checkpoint_independent_processes_baseline", "--system", system, "--codec", "h264", "--policy", "cpu_only", "--deadline-ms", "100", "--analytics-execution-socket", str(root / "analytics.sock"), "--analytics-preprocessing-contract-sha256", self.preprocessing, "--analytics-execution-manifest", str(paths["execution"]), "--policy-capability-manifest", str(paths["policy"]), "--policy-calibration", str(paths["calibration"]), "--analytics-model-manifest", str(ROOT / "configs/checkpoint_analytics_models_openvino.yaml"), "--gst-registry-template", str(root / "registry.bin"), "--gst-plugin-path", str(root), "--checkpoint-analytics-mode", "native_terminal_socket_v1", "--warmup", "30", "--duration", "180", "--execute-publication-runtime"]
                with mock.patch.object(coordinator, "load_analytics_model_bindings", return_value={}), mock.patch.object(coordinator, "require_exact_native_cpu_capability_bindings") as legacy, mock.patch.object(coordinator, "build_gstreamer_worker_specs", side_effect=WorkerBoundaryReached) as boundary:
                    with self.assertRaises(WorkerBoundaryReached):
                        coordinator.main(args, publication_system_authority="openvino_gva" if system == "openvino_gva" else None)
                    boundary.assert_called_once()
                    legacy.assert_not_called()

    def test_external_manifest_rejects_real_identity_and_coverage_drift(self):
        system = "openvino_gva"
        original = self.asset(system)
        changes = {
            "missing_config": lambda v: v.pop("execution_config"),
            "unsafe_config": lambda v: v["execution_config"].update(path="../outside.json"),
            "missing_branch": lambda v: v["branches"].pop("damage"),
            "missing_gpu": lambda v: v["branches"]["damage"].pop("gpu"),
            "wrong_system": lambda v: v.update(system="gstreamer_custom"),
            "policy_hash": lambda v: v.update(policy_capability_manifest_sha256="0" * 64),
            "worker_image": lambda v: v["branches"]["damage"]["cpu"].update(worker_image_id="sha256:" + "1" * 64),
            "implementation": lambda v: v["branches"]["damage"]["gpu"].update(worker_implementation_sha256="2" * 64),
            "model": lambda v: v["branches"]["damage"]["cpu"].update(source_model_sha256="3" * 64),
            "preprocessing": lambda v: v["branches"]["damage"]["cpu"].update(preprocessing_contract_sha256="4" * 64),
            "branch_swap": lambda v: v["branches"]["damage"]["cpu"].update(branch="plate_number"),
            "openvino_gpu": lambda v: v["branches"]["damage"].update(gpu=copy.deepcopy(v["branches"]["damage"]["cpu"])),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                value = copy.deepcopy(original)
                change(value)
                result = self.assess(value, system)
                self.assertFalse(result["passed"])
                self.assertTrue(result["blockers"])
                self.assertEqual(result["eligible_policies"], [])


if __name__ == "__main__":
    unittest.main()
