from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
WORKER_PATH = ROOT / "deploy" / "analytics_execution" / "openvino_worker.py"

from analytics_execution_worker import ExecutionClient, WorkerHarness  # noqa: E402


def load_worker_module():
    spec = importlib.util.spec_from_file_location("vast_openvino_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load OpenVINO worker module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeElementType:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_type_name(self) -> str:
        return self._name


class FakePort:
    def __init__(self, name: str, shape: list[int]) -> None:
        self.name = name
        self.shape = shape
        self.element_type = FakeElementType("f32")


class FakeCompiledModel:
    def __init__(self) -> None:
        self.seen: list[np.ndarray] = []
        self.retained_input: np.ndarray | None = None
        self.input_port = FakePort("data", [1, 3, 2, 2])
        self.output_port = FakePort("logits", [1, 2])

    def input(self, name: str):
        if name != "data":
            raise KeyError(name)
        return self.input_port

    def output(self, name: str):
        if name != "logits":
            raise KeyError(name)
        return self.output_port

    def __call__(self, inputs):
        array = inputs["data"]
        self.retained_input = array
        self.seen.append(np.array(array, copy=True))
        return {self.output_port: np.asarray([[float(array.sum()), float(array.mean())]], dtype=np.float32)}


class FakeCore:
    def __init__(self) -> None:
        self.available_devices = ["CPU"]
        self.compiled = FakeCompiledModel()
        self.compile_calls: list[tuple[object, str, dict[str, str]]] = []

    def read_model(self, path: str):
        return {"path": path}

    def compile_model(self, model, device: str, config: dict[str, str]):
        self.compile_calls.append((model, device, config))
        return self.compiled


class FakeOpenVINO:
    __version__ = "2026.1.0-test"

    def __init__(self) -> None:
        self.core = FakeCore()

    def Core(self):
        return self.core


class OpenVINOExecutionWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_worker_module()

    def binding(self, root: Path) -> Path:
        source = root / "model.onnx"
        model = root / "model.xml"
        weights = root / "model.bin"
        source.write_bytes(b"source-onnx")
        model.write_text("<net/>", encoding="utf-8")
        weights.write_bytes(b"weights")
        value = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_execution_worker_binding",
            "worker_id": "worker-plate-cpu-0001",
            "branch": "plate_number",
            "model_id": "opaque-rn18",
            "source_path": source.name,
            "source_model_sha256": file_sha(source),
            "model_path": model.name,
            "model_artifact_sha256": file_sha(model),
            "weights_path": weights.name,
            "runtime_weights_sha256": file_sha(weights),
            "input": {
                "name": "data",
                "dtype": "float32",
                "layout": "NCHW",
                "shape": [1, 3, 2, 2],
            },
            "preprocessing_contract_sha256": hashlib.sha256(b"preprocess").hexdigest(),
            "output_contract_sha256": hashlib.sha256(b"output-contract").hexdigest(),
            "outputs": [
                {"name": "logits", "dtype": "float32", "shape": [1, 2]},
            ],
            "worker_image_id": "sha256:" + hashlib.sha256(b"worker-image").hexdigest(),
        }
        path = root / "binding.json"
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def test_binding_hashes_source_xml_and_weights_and_rejects_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.binding(Path(tmp))
            binding = self.module.load_binding(path)
            self.assertEqual(binding["input"]["shape"], [1, 3, 2, 2])
            self.assertTrue(Path(binding["model_path"]).is_absolute())

            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["unexpected"] = True
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "fields have drifted"):
                self.module.load_binding(path)

    def test_backend_executes_compiled_model_on_exact_preprocessed_tensor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            runtime = FakeOpenVINO()
            backend = self.module.OpenVINOBackend(binding, openvino_module=runtime)
            capability = backend.capability()
            self.assertEqual(capability["device_api"], "CPU")
            self.assertEqual(capability["model_artifact_sha256"], binding["model_artifact_sha256"])
            self.assertEqual(runtime.core.compile_calls[0][1], "CPU")
            self.assertEqual(
                runtime.core.compile_calls[0][2],
                {"PERFORMANCE_HINT": "LATENCY", "NUM_STREAMS": "1", "INFERENCE_NUM_THREADS": "1"},
            )

            input_array = np.arange(12, dtype=np.float32).reshape(1, 3, 2, 2)
            request = {
                "tensor": {
                    "name": "data",
                    "dtype": "float32",
                    "layout": "NCHW",
                    "shape": [1, 3, 2, 2],
                }
            }
            result = backend.infer(request, memoryview(input_array.tobytes()))
            self.assertTrue(np.array_equal(runtime.core.compiled.seen[0], input_array))
            self.assertEqual(np.frombuffer(result.output, dtype=np.float32).shape, (2,))
            self.assertEqual(result.output_tensors[0]["name"], "logits")
            self.assertEqual(result.accelerator_memory_bytes, 0)

    def test_backend_refuses_runtime_without_cpu_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            runtime = FakeOpenVINO()
            runtime.core.available_devices = ["GPU"]
            with self.assertRaisesRegex(Exception, "CPU"):
                self.module.OpenVINOBackend(binding, openvino_module=runtime)

    def test_worker_roundtrip_releases_sealed_mmap_when_runtime_retains_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            runtime = FakeOpenVINO()
            backend = self.module.OpenVINOBackend(binding, openvino_module=runtime)
            input_array = np.arange(12, dtype=np.float32).reshape(1, 3, 2, 2)
            payload = input_array.tobytes()
            request = {
                "schema_version": 1,
                "message_type": "infer_request",
                "request_id": "nonpublication-openvino-mmap-regression",
                "run_id": "nonpublication.synthetic.regression",
                "arm_id": "nonpublication.synthetic.plate_number.openvino_cpu",
                "worker_id": binding["worker_id"],
                "frame": {
                    "input_frame_key": "synthetic-frame-0001",
                    "stream_id": 0,
                    "frame_id": 0,
                    "transport_pts_ns": 0,
                    "branch": binding["branch"],
                },
                "engine": "openvino_cpu",
                "deadline_monotonic_ns": time.monotonic_ns() + 10_000_000_000,
                "model": {
                    "model_id": binding["model_id"],
                    "source_sha256": binding["source_model_sha256"],
                    "runtime_artifact_sha256": binding["model_artifact_sha256"],
                    "runtime_weights_sha256": binding["runtime_weights_sha256"],
                },
                "tensor": {
                    **binding["input"],
                    "byte_length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "preprocessing_contract_sha256": binding["preprocessing_contract_sha256"],
                },
                "expected_output_contract_sha256": binding["output_contract_sha256"],
            }
            server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            thread = threading.Thread(
                target=WorkerHarness(server, backend, max_requests=1).serve,
                daemon=True,
            )
            thread.start()
            try:
                client = ExecutionClient(client_socket, expected_capability=backend.capability())
                client.handshake()
                response, output = client.infer(request, payload)
            finally:
                client_socket.close()
                thread.join(timeout=2)
                server.close()

            self.assertFalse(thread.is_alive())
            self.assertEqual(response["terminal"]["status"], "completed")
            self.assertEqual(len(output), 2 * np.dtype(np.float32).itemsize)
            self.assertIsNotNone(runtime.core.compiled.retained_input)
            self.assertTrue(runtime.core.compiled.retained_input.flags.owndata)
            self.assertTrue(runtime.core.compiled.retained_input.flags.c_contiguous)


if __name__ == "__main__":
    unittest.main()
