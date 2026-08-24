from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_endpoint import (  # noqa: E402
    expected_capability_from_binding_and_probe,
)
from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    PROTOCOL_IDENTITY_SHA256,
)

TOPOLOGY_IMPORTS_AFTER_ENDPOINT_IMPORT = {
    name: name in sys.modules
    for name in ("checkpoint_runtime", "checkpoint_openvino_execution_bridge")
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class AnalyticsExecutionEndpointTests(unittest.TestCase):
    def test_cpu_binding_and_probe_assemble_exact_capability_without_topology_import(self) -> None:
        binding = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_execution_worker_binding",
            "worker_id": "vast.plate_number.openvino",
            "branch": "plate_number",
            "model_id": "plate-number-v1",
            "source_path": "/workspace/source.onnx",
            "source_model_sha256": _sha("source"),
            "input": {"name": "input", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 224, 224]},
            "preprocessing_contract_sha256": _sha("preprocess"),
            "output_contract_sha256": _sha("output"),
            "outputs": [{"name": "scores", "dtype": "float32", "shape": [1, 1000]}],
            "worker_image_id": "sha256:" + _sha("image"),
            "model_artifact_sha256": _sha("xml"),
            "model_path": "/workspace/model.xml",
            "weights_path": "/workspace/model.bin",
            "runtime_weights_sha256": _sha("bin"),
        }
        probe = {
            "schema_version": 1,
            "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "engine": ENGINE_OPENVINO_CPU,
            "runtime_name": "OpenVINO",
            "runtime_version": "2026.1",
            "device_api": "CPU",
            "device_id": "Intel CPU",
            "native_inference_api": "openvino.CompiledModel.__call__",
            "execution_path": "openvino_cpu_native",
            "worker_implementation_sha256": _sha("implementation"),
            "socket_seqpacket": True,
            "scm_rights": True,
            "memfd_sealing": True,
            "model_loaded": False,
            "inference_performed": False,
        }
        capability = expected_capability_from_binding_and_probe(
            binding=binding,
            runtime_probe=probe,
            resource="cpu",
        )
        self.assertEqual(capability["branch"], "plate_number")
        self.assertEqual(capability["engine"], ENGINE_OPENVINO_CPU)
        self.assertEqual(
            TOPOLOGY_IMPORTS_AFTER_ENDPOINT_IMPORT,
            {
                "checkpoint_runtime": False,
                "checkpoint_openvino_execution_bridge": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
