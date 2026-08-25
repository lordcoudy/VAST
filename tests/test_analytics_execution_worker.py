from __future__ import annotations

import hashlib
import socket
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
)
from analytics_execution_worker import (  # noqa: E402
    BackendInference,
    ExecutionClient,
    WorkerHarness,
    WorkerRejected,
    validate_worker_capability,
)


SHA_A = hashlib.sha256(b"source").hexdigest()
SHA_B = hashlib.sha256(b"model").hexdigest()
SHA_C = hashlib.sha256(b"weights").hexdigest()
IMAGE_CPU = "sha256:" + hashlib.sha256(b"cpu-image").hexdigest()
IMPLEMENTATION = hashlib.sha256(b"implementation").hexdigest()


def capability(*, engine: str = ENGINE_OPENVINO_CPU) -> dict[str, object]:
    cpu = engine == ENGINE_OPENVINO_CPU
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_capability",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": "worker-plate-cpu-0001" if cpu else "worker-plate-gpu-0001",
        "branch": "plate_number",
        "engine": engine,
        "worker_image_id": IMAGE_CPU,
        "worker_implementation_sha256": IMPLEMENTATION,
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Intel CPU" if cpu else "GPU-00000000-0000-0000-0000-000000000001",
        "native_inference_api": (
            "openvino.CompiledModel.__call__"
            if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "model_id": "topology-proxy-plate-v1",
        "source_model_sha256": SHA_A,
        "model_artifact_sha256": SHA_B,
        "runtime_weights_sha256": SHA_C if cpu else None,
        "preprocessing_contract_sha256": SHA_A,
        "output_contract_sha256": SHA_B,
        "transport": "unix_seqpacket_scm_rights_sealed_memfd",
        "max_inflight_requests": 1,
        "max_tensor_bytes": 67_108_864,
    }


def request_for(payload: bytes, *, deadline_ns: int | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_type": "infer_request",
        "request_id": "request-0001",
        "run_id": "run-0001",
        "arm_id": "arm-0001",
        "worker_id": "worker-plate-cpu-0001",
        "frame": {
            "input_frame_key": "dataset:stream-0:frame-7",
            "stream_id": 0,
            "frame_id": 7,
            "transport_pts_ns": 233_333_333,
            "branch": "plate_number",
        },
        "engine": ENGINE_OPENVINO_CPU,
        "deadline_monotonic_ns": deadline_ns or time.monotonic_ns() + 10_000_000_000,
        "model": {
            "model_id": "topology-proxy-plate-v1",
            "source_sha256": SHA_A,
            "runtime_artifact_sha256": SHA_B,
            "runtime_weights_sha256": SHA_C,
        },
        "tensor": {
            "name": "input",
            "dtype": "uint8",
            "layout": "NHWC",
            "shape": [1, 2, 2, 3],
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "preprocessing_contract_sha256": SHA_A,
        },
        "expected_output_contract_sha256": SHA_B,
    }


class FakeBackend:
    def __init__(self) -> None:
        self.seen: list[bytes] = []

    def capability(self) -> dict[str, object]:
        return capability()

    def infer(self, request: dict[str, object], tensor: memoryview) -> BackendInference:
        value = bytes(tensor)
        self.seen.append(value)
        output = hashlib.sha256(value).digest()
        return BackendInference(
            output=output,
            output_tensors=(
                {
                    "name": "scores",
                    "dtype": "uint8",
                    "shape": [1, len(output)],
                    "offset": 0,
                    "byte_length": len(output),
                },
            ),
            objects=3,
            terminal_reason="native_inference_completed",
            accelerator_memory_bytes=0,
            cuda_h2d_bytes=0,
            cuda_d2h_bytes=0,
            cuda_transfer_intervals=(),
        )


@unittest.skipUnless(
    hasattr(socket, "SOCK_SEQPACKET"),
    "Linux SOCK_SEQPACKET is required",
)
class AnalyticsExecutionWorkerTests(unittest.TestCase):
    def test_fake_backend_roundtrip_binds_frame_model_input_output_and_provenance(self) -> None:
        server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        backend = FakeBackend()
        worker = WorkerHarness(server, backend, max_requests=1)
        thread = threading.Thread(target=worker.serve, daemon=True)
        thread.start()
        try:
            client = ExecutionClient(client_socket, expected_capability=capability())
            self.assertEqual(client.handshake(), capability())
            payload = bytes(range(12))
            response, output = client.infer(request_for(payload), payload)
            self.assertEqual(backend.seen, [payload])
            self.assertEqual(output, hashlib.sha256(payload).digest())
            self.assertEqual(response["provenance"]["input_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(response["provenance"]["output_sha256"], hashlib.sha256(output).hexdigest())
            self.assertEqual(response["provenance"]["device_api"], "CPU")
            self.assertEqual(response["terminal"]["objects"], 3)
            self.assertEqual(response["frame"], request_for(payload)["frame"])
            self.assertGreater(response["timing"]["inference_latency_ns"], 0)
        finally:
            client_socket.close()
            thread.join(timeout=5)
            server.close()
        self.assertFalse(thread.is_alive())

    def test_worker_rejects_expired_request_without_calling_backend(self) -> None:
        server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        backend = FakeBackend()
        worker = WorkerHarness(server, backend, max_requests=1)
        thread = threading.Thread(target=worker.serve, daemon=True)
        thread.start()
        try:
            client = ExecutionClient(client_socket, expected_capability=capability())
            client.handshake()
            payload = bytes(range(12))
            with self.assertRaisesRegex(WorkerRejected, "deadline_expired"):
                client.infer(request_for(payload, deadline_ns=1), payload)
            self.assertEqual(backend.seen, [])
        finally:
            client_socket.close()
            thread.join(timeout=5)
            server.close()

    def test_gpu_capability_cannot_relabel_cpu_or_openvino_as_cuda(self) -> None:
        fake_gpu = capability(engine=ENGINE_TENSORRT_CUDA)
        self.assertEqual(validate_worker_capability(fake_gpu), fake_gpu)
        fake_gpu["runtime_name"] = "OpenVINO"
        with self.assertRaisesRegex(ProtocolError, "TensorRT"):
            validate_worker_capability(fake_gpu)

        fake_gpu = capability(engine=ENGINE_TENSORRT_CUDA)
        fake_gpu["device_api"] = "GPU"
        with self.assertRaisesRegex(ProtocolError, "NVIDIA_CUDA"):
            validate_worker_capability(fake_gpu)

    def test_client_rejects_capability_not_bound_to_expected_image(self) -> None:
        server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        backend = FakeBackend()
        worker = WorkerHarness(server, backend, max_requests=0)
        thread = threading.Thread(target=worker.serve, daemon=True)
        thread.start()
        expected = capability()
        expected["worker_image_id"] = "sha256:" + "f" * 64
        try:
            client = ExecutionClient(client_socket, expected_capability=expected)
            with self.assertRaisesRegex(ProtocolError, "capability mismatch"):
                client.handshake()
        finally:
            client_socket.close()
            thread.join(timeout=5)
            server.close()


if __name__ == "__main__":
    unittest.main()
