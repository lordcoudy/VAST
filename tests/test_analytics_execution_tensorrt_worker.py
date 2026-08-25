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
WORKER_PATH = ROOT / "deploy" / "analytics_execution" / "tensorrt_worker.py"

from analytics_execution_worker import ExecutionClient, WorkerHarness  # noqa: E402


def load_worker_module():
    spec = importlib.util.spec_from_file_location("vast_tensorrt_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load TensorRT worker module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"


class FakeNativeSession:
    runtime_version = "8.6.1.6"
    gpu_uuid = GPU_UUID
    input_contract = {"name": "data", "dtype": "float32", "shape": [1, 3, 2, 2]}
    output_contracts = ({"name": "logits", "dtype": "float32", "shape": [1, 2]},)
    device_allocation_bytes = 4096

    def __init__(self) -> None:
        self.seen: list[np.ndarray] = []
        self.retained_input: np.ndarray | None = None

    def infer(self, array: np.ndarray) -> bytes:
        self.retained_input = array
        self.seen.append(np.array(array, copy=True))
        output = np.asarray(
            [[float(array.sum()), float(array.mean())]], dtype=np.float32
        ).tobytes()
        return output, (
            {
                "direction": "h2d",
                "host_start_monotonic_ns": 1_000_000,
                "host_end_monotonic_ns": 1_400_000,
                "device_elapsed_ns": 250_000,
                "bytes": array.nbytes,
                "device_id": self.gpu_uuid,
                "timing_source": "cudaEventElapsedTime",
            },
            {
                "direction": "d2h",
                "host_start_monotonic_ns": 1_500_000,
                "host_end_monotonic_ns": 1_800_000,
                "device_elapsed_ns": 200_000,
                "bytes": len(output),
                "device_id": self.gpu_uuid,
                "timing_source": "cudaEventElapsedTime",
            },
        )


class TensorRTExecutionWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_worker_module()

    def binding(self, root: Path) -> Path:
        source = root / "model.onnx"
        engine = root / "model.engine"
        source.write_bytes(b"source-onnx")
        engine.write_bytes(b"immutable-engine")
        value = {
            "schema_version": 1,
            "artifact_kind": "vast_tensorrt_execution_worker_binding",
            "worker_id": "worker-plate-gpu-0001",
            "branch": "plate_number",
            "model_id": "opaque-rn18",
            "source_path": source.name,
            "source_model_sha256": file_sha(source),
            "engine_path": engine.name,
            "model_artifact_sha256": file_sha(engine),
            "input": {"name": "data", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 2, 2]},
            "preprocessing_contract_sha256": hashlib.sha256(b"preprocess").hexdigest(),
            "output_contract_sha256": hashlib.sha256(b"output-contract").hexdigest(),
            "outputs": [{"name": "logits", "dtype": "float32", "shape": [1, 2]}],
            "worker_image_id": "sha256:" + hashlib.sha256(b"worker-image").hexdigest(),
            "gpu_device_index": 0,
            "gpu_uuid": GPU_UUID,
        }
        path = root / "binding.json"
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return path

    def test_binding_hashes_source_and_authoritative_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.binding(Path(tmp))
            binding = self.module.load_binding(path)
            self.assertTrue(Path(binding["engine_path"]).is_absolute())
            engine = Path(binding["engine_path"])
            engine.write_bytes(b"rebuilt-engine-with-different-bytes")
            with self.assertRaisesRegex(Exception, "engine.*differs"):
                self.module.load_binding(path)

    def test_backend_executes_exact_tensor_through_native_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            native = FakeNativeSession()
            backend = self.module.TensorRTBackend(binding, native_session=native)
            capability = backend.capability()
            self.assertEqual(capability["runtime_name"], "TensorRT")
            self.assertEqual(capability["device_api"], "NVIDIA_CUDA")
            self.assertIsNone(capability["runtime_weights_sha256"])

            input_array = np.arange(12, dtype=np.float32).reshape(1, 3, 2, 2)
            request = {"tensor": {"name": "data", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 2, 2]}}
            result = backend.infer(request, memoryview(input_array.tobytes()))
            self.assertTrue(np.array_equal(native.seen[0], input_array))
            self.assertEqual(result.cuda_h2d_bytes, input_array.nbytes)
            self.assertEqual(result.cuda_d2h_bytes, len(result.output))
            self.assertEqual(result.accelerator_memory_bytes, 4096)
            self.assertEqual(
                [item["direction"] for item in result.cuda_transfer_intervals],
                ["h2d", "d2h"],
            )
            self.assertTrue(
                all(
                    item["timing_source"] == "cudaEventElapsedTime"
                    and item["device_elapsed_ns"] > 0
                    and item["device_elapsed_ns"]
                    <= item["host_end_monotonic_ns"]
                    - item["host_start_monotonic_ns"]
                    for item in result.cuda_transfer_intervals
                )
            )

    def test_native_backend_source_uses_cuda_events_for_both_transfers(self) -> None:
        source = (
            ROOT / "deploy" / "analytics_execution" / "tensorrt_backend.cpp"
        ).read_text(encoding="utf-8")
        for marker in (
            "cudaEventCreateWithFlags",
            "cudaEventRecord",
            "cudaEventElapsedTime",
            "h2d_device_elapsed_ns",
            "d2h_device_elapsed_ns",
            "CLOCK_MONOTONIC",
        ):
            self.assertIn(marker, source)

    def test_backend_rejects_native_session_on_different_gpu_uuid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            native = FakeNativeSession()
            native.gpu_uuid = "GPU-11111111-1111-1111-1111-111111111111"
            with self.assertRaisesRegex(Exception, "GPU UUID"):
                self.module.TensorRTBackend(binding, native_session=native)

    def test_worker_roundtrip_releases_sealed_mmap_when_native_session_retains_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binding = self.module.load_binding(self.binding(Path(tmp)))
            native = FakeNativeSession()
            backend = self.module.TensorRTBackend(binding, native_session=native)
            input_array = np.arange(12, dtype=np.float32).reshape(1, 3, 2, 2)
            payload = input_array.tobytes()
            request = {
                "schema_version": 1,
                "message_type": "infer_request",
                "request_id": "nonpublication-tensorrt-mmap-regression",
                "run_id": "nonpublication.synthetic.regression",
                "arm_id": "nonpublication.synthetic.plate_number.tensorrt_cuda",
                "worker_id": binding["worker_id"],
                "frame": {
                    "input_frame_key": "synthetic-frame-0001",
                    "stream_id": 0,
                    "frame_id": 0,
                    "transport_pts_ns": 0,
                    "branch": binding["branch"],
                },
                "engine": "tensorrt_cuda",
                "deadline_monotonic_ns": time.monotonic_ns() + 10_000_000_000,
                "model": {
                    "model_id": binding["model_id"],
                    "source_sha256": binding["source_model_sha256"],
                    "runtime_artifact_sha256": binding["model_artifact_sha256"],
                    "runtime_weights_sha256": None,
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
            self.assertIsNotNone(native.retained_input)
            self.assertTrue(native.retained_input.flags.owndata)
            self.assertTrue(native.retained_input.flags.c_contiguous)


if __name__ == "__main__":
    unittest.main()
