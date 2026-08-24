from __future__ import annotations

import hashlib
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
)
from checkpoint_openvino_execution_bridge import (  # noqa: E402
    GVA_SDK_BINDING,
    ExecutionEndpoint,
    OpenVINOGVAExecutionBridge,
    expected_capability_from_binding_and_probe,
    execution_endpoint_from_socket,
)
from analytics_execution_worker import BackendInference, WorkerHarness  # noqa: E402
from checkpoint_runtime import (  # noqa: E402
    DirectRuntimeJoinCoordinator,
    RuntimeMessage,
    WorkerBinding,
)
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
RESOURCE_ENGINE_FOR_TEST = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
SHA_SOURCE = hashlib.sha256(b"source-model").hexdigest()
SHA_MODEL = hashlib.sha256(b"runtime-model").hexdigest()
SHA_WEIGHTS = hashlib.sha256(b"runtime-weights").hexdigest()
SHA_PREPROCESS = hashlib.sha256(b"preprocess").hexdigest()
SHA_OUTPUT = hashlib.sha256(b"output-contract").hexdigest()
PAYLOAD_SHA = hashlib.sha256(b"compressed-access-unit").hexdigest()
POLICY_SHA = hashlib.sha256(b"policy-decision").hexdigest()


def capability(branch: str, resource: str) -> dict[str, Any]:
    cpu = resource == "cpu"
    engine = ENGINE_OPENVINO_CPU if cpu else ENGINE_TENSORRT_CUDA
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_capability",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": f"analytics-{branch}-{resource}",
        "branch": branch,
        "engine": engine,
        "worker_image_id": "sha256:" + hashlib.sha256(f"image-{resource}".encode()).hexdigest(),
        "worker_implementation_sha256": hashlib.sha256(
            f"implementation-{resource}".encode()
        ).hexdigest(),
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": (
            "Intel CPU"
            if cpu
            else "GPU-00000000-0000-0000-0000-000000000001"
        ),
        "native_inference_api": (
            "openvino.CompiledModel.__call__"
            if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "model_id": f"opaque-{branch}-v1",
        "source_model_sha256": SHA_SOURCE,
        "model_artifact_sha256": SHA_MODEL,
        "runtime_weights_sha256": SHA_WEIGHTS if cpu else None,
        "preprocessing_contract_sha256": SHA_PREPROCESS,
        "output_contract_sha256": SHA_OUTPUT,
        "transport": "unix_seqpacket_scm_rights_sealed_memfd",
        "max_inflight_requests": 1,
        "max_tensor_bytes": 67_108_864,
    }


def runtime_probe_for(expected: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": expected["engine"],
        "runtime_name": expected["runtime_name"],
        "runtime_version": expected["runtime_version"],
        "device_api": expected["device_api"],
        "device_id": expected["device_id"],
        "native_inference_api": expected["native_inference_api"],
        "execution_path": expected["execution_path"],
        "worker_implementation_sha256": expected["worker_implementation_sha256"],
        "socket_seqpacket": True,
        "scm_rights": True,
        "memfd_sealing": True,
        "model_loaded": False,
        "inference_performed": False,
    }


def materialized_binding(expected: dict[str, Any], resource: str) -> dict[str, Any]:
    common = {
        "schema_version": 1,
        "worker_id": expected["worker_id"],
        "branch": expected["branch"],
        "model_id": expected["model_id"],
        "source_path": "/workspace/models/source.onnx",
        "source_model_sha256": expected["source_model_sha256"],
        "input": {"name": "input", "dtype": "uint8", "layout": "NHWC", "shape": [1, 2, 2, 3]},
        "preprocessing_contract_sha256": expected["preprocessing_contract_sha256"],
        "output_contract_sha256": expected["output_contract_sha256"],
        "outputs": [{"name": "scores", "dtype": "uint8", "shape": [1, 32]}],
        "worker_image_id": expected["worker_image_id"],
        "model_artifact_sha256": expected["model_artifact_sha256"],
    }
    if resource == "cpu":
        return {
            **common,
            "artifact_kind": "vast_openvino_execution_worker_binding",
            "model_path": "/workspace/models/model.xml",
            "weights_path": "/workspace/models/model.bin",
            "runtime_weights_sha256": expected["runtime_weights_sha256"],
        }
    return {
        **common,
        "artifact_kind": "vast_tensorrt_execution_worker_binding",
        "engine_path": "/workspace/models/model.engine",
        "gpu_device_index": 0,
        "gpu_uuid": expected["device_id"],
    }


class FakeExecutionClient:
    def __init__(self, expected: dict[str, Any]) -> None:
        self.expected = expected
        self.handshake_count = 0
        self.requests: list[dict[str, Any]] = []

    def handshake(self) -> dict[str, Any]:
        self.handshake_count += 1
        return dict(self.expected)

    def infer(
        self, request: dict[str, Any], tensor: bytes
    ) -> tuple[dict[str, Any], bytes]:
        self.requests.append(request)
        output = hashlib.sha256(bytes(tensor) + request["engine"].encode()).digest()
        cpu = request["engine"] == ENGINE_OPENVINO_CPU
        response = {
            "schema_version": 1,
            "message_type": "infer_response",
            "request_id": request["request_id"],
            "run_id": request["run_id"],
            "arm_id": request["arm_id"],
            "worker_id": request["worker_id"],
            "frame": dict(request["frame"]),
            "engine": request["engine"],
            "terminal": {
                "status": "completed",
                "objects": 2,
                "reason": "native_inference_completed",
            },
            "output": {
                "byte_length": len(output),
                "sha256": hashlib.sha256(output).hexdigest(),
                "contract_sha256": self.expected["output_contract_sha256"],
                "tensor_count": 1,
                "tensors": [
                    {
                        "name": "scores",
                        "dtype": "uint8",
                        "shape": [1, len(output)],
                        "offset": 0,
                        "byte_length": len(output),
                    }
                ],
            },
            "provenance": {
                "worker_image_id": self.expected["worker_image_id"],
                "worker_implementation_sha256": self.expected[
                    "worker_implementation_sha256"
                ],
                "runtime_name": self.expected["runtime_name"],
                "runtime_version": self.expected["runtime_version"],
                "device_api": self.expected["device_api"],
                "device_id": self.expected["device_id"],
                "native_inference_api": self.expected["native_inference_api"],
                "execution_path": self.expected["execution_path"],
                "model_id": self.expected["model_id"],
                "source_model_sha256": self.expected["source_model_sha256"],
                "model_artifact_sha256": self.expected["model_artifact_sha256"],
                "runtime_weights_sha256": self.expected["runtime_weights_sha256"],
                "preprocessing_contract_sha256": self.expected[
                    "preprocessing_contract_sha256"
                ],
                "output_contract_sha256": self.expected["output_contract_sha256"],
                "input_sha256": request["tensor"]["sha256"],
                "output_sha256": hashlib.sha256(output).hexdigest(),
            },
            "timing": {
                "worker_received_monotonic_ns": 100,
                "inference_started_monotonic_ns": 110,
                "inference_finished_monotonic_ns": 120,
                "worker_completed_monotonic_ns": 130,
                "inference_latency_ns": 10,
            },
            "resource": {
                "process_cpu_time_ns": 10,
                "rss_before_bytes": 1000,
                "rss_after_bytes": 1100,
                "accelerator_memory_bytes": 0 if cpu else 4096,
                "cuda_h2d_bytes": 0 if cpu else len(tensor),
                "cuda_d2h_bytes": 0 if cpu else len(output),
            },
        }
        return response, output


class SyntheticNativeBackend:
    def __init__(self, expected: dict[str, Any]) -> None:
        self.expected = expected
        self.seen: list[bytes] = []

    def capability(self) -> dict[str, Any]:
        return dict(self.expected)

    def infer(self, request: dict[str, Any], tensor: memoryview) -> BackendInference:
        payload = bytes(tensor)
        self.seen.append(payload)
        output = hashlib.sha256(payload + request["engine"].encode()).digest()
        cpu = request["engine"] == ENGINE_OPENVINO_CPU
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
            objects=1,
            terminal_reason="native_inference_completed",
            accelerator_memory_bytes=0 if cpu else 4096,
            cuda_h2d_bytes=0 if cpu else len(payload),
            cuda_d2h_bytes=0 if cpu else len(output),
        )


def endpoint_inventory() -> tuple[list[ExecutionEndpoint], dict[tuple[str, str], FakeExecutionClient]]:
    clients: dict[tuple[str, str], FakeExecutionClient] = {}
    endpoints = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            expected = capability(branch, resource)
            client = FakeExecutionClient(expected)
            clients[(branch, resource)] = client
            endpoints.append(
                ExecutionEndpoint(
                    resource=resource,
                    capability=expected,
                    client=client,
                )
            )
    return endpoints, clients


def context(
    *,
    branch: str,
    resource: str,
    topology_kind: str,
    topology_worker_id: str,
    topology_worker_trace_id: str,
    event_sequence: int,
    parent_execution_id: str,
) -> dict[str, Any]:
    return {
        "sdk_binding": GVA_SDK_BINDING,
        "tensor_origin": "verified_preprocess_src_pad",
        "pts_origin": "GST_BUFFER_PTS",
        "run_id": "run-openvino-gva-0001",
        "arm_id": "arm-openvino-gva-0001",
        "request_id": f"request-{topology_worker_id}-{event_sequence}",
        "topology_kind": topology_kind,
        "topology_worker_id": topology_worker_id,
        "topology_worker_trace_id": topology_worker_trace_id,
        "event_sequence": event_sequence,
        "stream_id": 0,
        "frame_id": 7,
        "input_frame_key": "kpp-real-h264-stream-0-frame-7",
        "transport_pts_ns": 233_333_333,
        "branch": branch,
        "selected_resource": resource,
        "parent_execution_id": parent_execution_id,
        "terminal_execution_id": f"{topology_worker_trace_id}-{branch}-terminal",
        "admission_id": "admission-stream-0-frame-7",
        "payload_sha256": PAYLOAD_SHA,
        "policy_decision_id": f"policy-{branch}-{resource}-0001",
        "policy_decision_sha256": POLICY_SHA,
        "deadline_monotonic_ns": 10_000_000_000,
    }


def tensor_descriptor() -> dict[str, Any]:
    return {
        "name": "input",
        "dtype": "uint8",
        "layout": "NHWC",
        "shape": [1, 2, 2, 3],
        "preprocessing_contract_sha256": SHA_PREPROCESS,
        "contiguous": True,
        "read_only": True,
    }


def runtime_event(
    *,
    worker_id: str,
    sequence: int,
    topology_kind: str,
    trace_id: str,
    branch: str,
    event_kind: str,
    stage: str,
    execution_id: str,
    parents: list[str],
    timestamp_ms: int,
) -> dict[str, Any]:
    return {
        "protocol_version": 2,
        "worker_id": worker_id,
        "sequence": sequence,
        "run_id": "run-openvino-gva-0001",
        "trace_id": trace_id,
        "stream_id": 0,
        "frame_id": 7,
        "input_frame_key": "kpp-real-h264-stream-0-frame-7",
        "topology_kind": topology_kind,
        "event_kind": event_kind,
        "stage": stage,
        "branch_id": branch,
        "execution_id": execution_id,
        "parent_execution_ids": parents,
        "timestamp_ms": timestamp_ms,
        "admission_id": "admission-stream-0-frame-7",
        "payload_sha256": PAYLOAD_SHA,
    }


class OpenVINOGVAExecutionBridgeTests(unittest.TestCase):
    def test_expected_capability_is_assembled_from_binding_and_runtime_probe(self) -> None:
        for branch, resource in (("plate_number", "cpu"), ("damage", "gpu")):
            expected = capability(branch, resource)
            assembled = expected_capability_from_binding_and_probe(
                binding=materialized_binding(expected, resource),
                runtime_probe=runtime_probe_for(expected),
                resource=resource,
            )
            self.assertEqual(assembled, expected)

        expected = capability("damage", "gpu")
        binding = materialized_binding(expected, "gpu")
        binding["gpu_uuid"] = "GPU-00000000-0000-0000-0000-000000000002"
        with self.assertRaisesRegex(ProtocolError, "GPU UUID"):
            expected_capability_from_binding_and_probe(
                binding=binding,
                runtime_probe=runtime_probe_for(expected),
                resource="gpu",
            )

    def test_exact_eight_endpoint_inventory_handshakes_nonpublication(self) -> None:
        endpoints, clients = endpoint_inventory()
        bridge = OpenVINOGVAExecutionBridge(endpoints, clock_ms=lambda: 1000)

        audit = bridge.handshake_all()

        self.assertEqual(audit["endpoint_count"], 8)
        self.assertEqual(audit["branches"], list(BRANCHES))
        self.assertEqual(audit["resources"], ["cpu", "gpu"])
        self.assertFalse(audit["publication_ready"])
        self.assertFalse(audit["accepted_evidence_written"])
        self.assertTrue(all(client.handshake_count == 1 for client in clients.values()))

    def test_cpu_and_gpu_dispatch_use_exact_frozen_native_engines(self) -> None:
        endpoints, clients = endpoint_inventory()
        bridge = OpenVINOGVAExecutionBridge(endpoints, clock_ms=lambda: 1000)
        bridge.handshake_all()
        payload = bytes(range(12))

        cpu_result = bridge.execute(
            context=context(
                branch="plate_number",
                resource="cpu",
                topology_kind=INDEPENDENT_PROCESSES,
                topology_worker_id="stream-0-branch-plate_number",
                topology_worker_trace_id="trace-plate-number",
                event_sequence=5,
                parent_execution_id="plate-number-analytics",
            ),
            tensor=payload,
            tensor_descriptor=tensor_descriptor(),
        )
        gpu_result = bridge.execute(
            context=context(
                branch="damage",
                resource="gpu",
                topology_kind=SHARED_VIDEO_DAG,
                topology_worker_id="stream-0-shared-video-dag",
                topology_worker_trace_id="trace-shared",
                event_sequence=6,
                parent_execution_id="damage-analytics",
            ),
            tensor=payload,
            tensor_descriptor=tensor_descriptor(),
        )

        self.assertEqual(cpu_result["request"]["engine"], ENGINE_OPENVINO_CPU)
        self.assertEqual(cpu_result["response"]["provenance"]["device_api"], "CPU")
        self.assertEqual(gpu_result["request"]["engine"], ENGINE_TENSORRT_CUDA)
        self.assertEqual(
            gpu_result["response"]["provenance"]["device_api"], "NVIDIA_CUDA"
        )
        self.assertEqual(gpu_result["response"]["provenance"]["runtime_name"], "TensorRT")
        self.assertEqual(cpu_result["request"]["frame"]["transport_pts_ns"], 233_333_333)
        self.assertEqual(cpu_result["request"]["tensor"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(len(clients[("plate_number", "cpu")].requests), 1)
        self.assertEqual(len(clients[("damage", "gpu")].requests), 1)
        for result in (cpu_result, gpu_result):
            parsed = RuntimeMessage.parse(json.dumps(result["terminal_event"]))
            self.assertEqual(parsed.protocol_version, 3)
            self.assertEqual(parsed.event_kind, "branch_complete")
            self.assertFalse(result["publication_ready"])
            self.assertFalse(result["accepted_evidence_written"])

    @unittest.skipUnless(
        hasattr(socket, "SOCK_SEQPACKET"),
        "Linux SOCK_SEQPACKET is required",
    )
    def test_real_execution_client_transport_receives_cpu_and_gpu_terminals(self) -> None:
        endpoints, _ = endpoint_inventory()
        real_keys = {("plate_number", "cpu"), ("damage", "gpu")}
        endpoints = [
            endpoint
            for endpoint in endpoints
            if (str(endpoint.capability["branch"]), endpoint.resource) not in real_keys
        ]
        sockets: list[socket.socket] = []
        servers: list[socket.socket] = []
        threads: list[threading.Thread] = []
        backends: dict[tuple[str, str], SyntheticNativeBackend] = {}
        for branch, resource in sorted(real_keys):
            server, client_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            expected = capability(branch, resource)
            backend = SyntheticNativeBackend(expected)
            worker = WorkerHarness(server, backend, max_requests=1)
            thread = threading.Thread(target=worker.serve, daemon=True)
            thread.start()
            endpoints.append(
                execution_endpoint_from_socket(
                    client_socket,
                    resource=resource,
                    expected_capability=expected,
                )
            )
            sockets.append(client_socket)
            servers.append(server)
            threads.append(thread)
            backends[(branch, resource)] = backend
        try:
            bridge = OpenVINOGVAExecutionBridge(endpoints, clock_ms=lambda: 1000)
            bridge.handshake_all()
            payload = bytes(range(12))
            for branch, resource, topology_kind in (
                ("plate_number", "cpu", INDEPENDENT_PROCESSES),
                ("damage", "gpu", SHARED_VIDEO_DAG),
            ):
                raw = context(
                    branch=branch,
                    resource=resource,
                    topology_kind=topology_kind,
                    topology_worker_id=f"topology-{branch}-{resource}",
                    topology_worker_trace_id=f"trace-{branch}-{resource}",
                    event_sequence=5,
                    parent_execution_id=f"{branch}-analytics",
                )
                raw["deadline_monotonic_ns"] = time.monotonic_ns() + 10_000_000_000
                result = bridge.execute(
                    context=raw,
                    tensor=payload,
                    tensor_descriptor=tensor_descriptor(),
                )
                self.assertEqual(result["terminal_event"]["event_kind"], "branch_complete")
                self.assertEqual(result["terminal_event"]["backend"], RESOURCE_ENGINE_FOR_TEST[resource])
                self.assertEqual(backends[(branch, resource)].seen, [payload])
        finally:
            for value in sockets:
                value.close()
            for thread in threads:
                thread.join(timeout=5)
            for value in servers:
                value.close()
        self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_gpu_endpoint_cannot_relabel_openvino_as_cuda(self) -> None:
        endpoints, _ = endpoint_inventory()
        bad = capability("damage", "gpu")
        bad["runtime_name"] = "OpenVINO"
        endpoints = [
            endpoint
            for endpoint in endpoints
            if not (endpoint.resource == "gpu" and endpoint.capability["branch"] == "damage")
        ] + [ExecutionEndpoint(resource="gpu", capability=bad, client=FakeExecutionClient(bad))]

        with self.assertRaisesRegex(ProtocolError, "TensorRT"):
            OpenVINOGVAExecutionBridge(endpoints)

    def test_rejects_generic_tensor_origin_before_inference(self) -> None:
        endpoints, clients = endpoint_inventory()
        bridge = OpenVINOGVAExecutionBridge(endpoints)
        bridge.handshake_all()
        raw = context(
            branch="plate_number",
            resource="cpu",
            topology_kind=INDEPENDENT_PROCESSES,
            topology_worker_id="stream-0-branch-plate_number",
            topology_worker_trace_id="trace-plate-number",
            event_sequence=5,
            parent_execution_id="plate-number-analytics",
        )
        raw["sdk_binding"] = "generic-probe"

        with self.assertRaisesRegex(ProtocolError, "SDK binding"):
            bridge.execute(
                context=raw,
                tensor=bytes(range(12)),
                tensor_descriptor=tensor_descriptor(),
            )
        self.assertFalse(clients[("plate_number", "cpu")].requests)

    def test_baseline_and_shared_events_close_live_protocol_v3_joins(self) -> None:
        payload = bytes(range(12))

        endpoints, _ = endpoint_inventory()
        baseline_bridge = OpenVINOGVAExecutionBridge(endpoints, clock_ms=lambda: 1000)
        baseline_bridge.handshake_all()
        baseline_bindings = [
            WorkerBinding(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                pid=2000 + index,
                execution_domain=f"baseline-pid-{2000 + index}",
                native_event_source=True,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        baseline = DirectRuntimeJoinCoordinator(
            run_id="run-openvino-gva-0001",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=baseline_bindings,
            clock_ms=lambda: 1000,
        )
        for index, branch in enumerate(BRANCHES):
            worker = f"stream-0-branch-{branch}"
            trace = f"trace-{branch}"
            source = f"{branch}-source"
            decode = f"{branch}-decode"
            preprocess = f"{branch}-preprocess"
            analytics = f"{branch}-analytics"
            events = (
                runtime_event(worker_id=worker, sequence=1, topology_kind=INDEPENDENT_PROCESSES, trace_id=trace, branch=branch, event_kind="source_read", stage="source", execution_id=source, parents=[], timestamp_ms=10),
                runtime_event(worker_id=worker, sequence=2, topology_kind=INDEPENDENT_PROCESSES, trace_id=trace, branch=branch, event_kind="stage_complete", stage=f"decode_{branch}", execution_id=decode, parents=[source], timestamp_ms=20),
                runtime_event(worker_id=worker, sequence=3, topology_kind=INDEPENDENT_PROCESSES, trace_id=trace, branch=branch, event_kind="stage_complete", stage=f"preprocess_{branch}", execution_id=preprocess, parents=[decode], timestamp_ms=30),
                runtime_event(worker_id=worker, sequence=4, topology_kind=INDEPENDENT_PROCESSES, trace_id=trace, branch=branch, event_kind="stage_complete", stage=branch, execution_id=analytics, parents=[preprocess], timestamp_ms=40),
            )
            for event in events:
                baseline.accept(json.dumps(event), observed_worker_id=worker, observed_pid=2000 + index)
            terminal = baseline_bridge.execute(
                context=context(
                    branch=branch,
                    resource="cpu",
                    topology_kind=INDEPENDENT_PROCESSES,
                    topology_worker_id=worker,
                    topology_worker_trace_id=trace,
                    event_sequence=5,
                    parent_execution_id=analytics,
                ),
                tensor=payload,
                tensor_descriptor=tensor_descriptor(),
            )["terminal_event"]
            baseline.accept(json.dumps(terminal), observed_worker_id=worker, observed_pid=2000 + index)
        self.assertTrue(baseline.terminal_frame_records()[0]["joined"])
        self.assertEqual(len(baseline.branch_terminal_records()), 4)

        endpoints, _ = endpoint_inventory()
        terminal_times = iter((100, 200, 300, 400))
        shared_bridge = OpenVINOGVAExecutionBridge(
            endpoints,
            clock_ms=lambda: next(terminal_times),
        )
        shared_bridge.handshake_all()
        worker = "stream-0-shared-video-dag"
        trace = "trace-shared"
        shared = DirectRuntimeJoinCoordinator(
            run_id="run-openvino-gva-0001",
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            bindings=[
                WorkerBinding(
                    worker_id=worker,
                    stream_id=0,
                    branch_id=None,
                    pid=3000,
                    execution_domain="shared-pid-3000",
                    native_event_source=True,
                )
            ],
            clock_ms=lambda: 1000,
        )
        source, decode, preprocess = "shared-source", "shared-decode", "shared-preprocess"
        prefix = (
            runtime_event(worker_id=worker, sequence=1, topology_kind=SHARED_VIDEO_DAG, trace_id=trace, branch="shared", event_kind="source_read", stage="source", execution_id=source, parents=[], timestamp_ms=10),
            runtime_event(worker_id=worker, sequence=2, topology_kind=SHARED_VIDEO_DAG, trace_id=trace, branch="shared", event_kind="stage_complete", stage="decode", execution_id=decode, parents=[source], timestamp_ms=20),
            runtime_event(worker_id=worker, sequence=3, topology_kind=SHARED_VIDEO_DAG, trace_id=trace, branch="shared", event_kind="stage_complete", stage="preprocess", execution_id=preprocess, parents=[decode], timestamp_ms=30),
        )
        for event in prefix:
            shared.accept(json.dumps(event), observed_worker_id=worker, observed_pid=3000)
        sequence = 4
        for index, branch in enumerate(BRANCHES):
            fanout = f"shared-{branch}-fanout"
            analytics = f"shared-{branch}-analytics"
            shared.accept(
                json.dumps(runtime_event(worker_id=worker, sequence=sequence, topology_kind=SHARED_VIDEO_DAG, trace_id=trace, branch=branch, event_kind="fanout", stage="fanout", execution_id=fanout, parents=[preprocess], timestamp_ms=50 + 100 * index)),
                observed_worker_id=worker,
                observed_pid=3000,
            )
            sequence += 1
            shared.accept(
                json.dumps(runtime_event(worker_id=worker, sequence=sequence, topology_kind=SHARED_VIDEO_DAG, trace_id=trace, branch=branch, event_kind="stage_complete", stage=branch, execution_id=analytics, parents=[fanout], timestamp_ms=60 + 100 * index)),
                observed_worker_id=worker,
                observed_pid=3000,
            )
            sequence += 1
            resource = "cpu" if index % 2 == 0 else "gpu"
            terminal = shared_bridge.execute(
                context=context(
                    branch=branch,
                    resource=resource,
                    topology_kind=SHARED_VIDEO_DAG,
                    topology_worker_id=worker,
                    topology_worker_trace_id=trace,
                    event_sequence=sequence,
                    parent_execution_id=analytics,
                ),
                tensor=payload,
                tensor_descriptor=tensor_descriptor(),
            )["terminal_event"]
            shared.accept(json.dumps(terminal), observed_worker_id=worker, observed_pid=3000)
            sequence += 1
        self.assertTrue(shared.terminal_frame_records()[0]["joined"])
        terminals = shared.branch_terminal_records()
        self.assertEqual(len(terminals), 4)
        self.assertEqual(
            {row["backend"] for row in terminals},
            {ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA},
        )

    def test_native_queue_drop_is_protocol_v3_and_never_accepted_evidence(self) -> None:
        endpoints, clients = endpoint_inventory()
        bridge = OpenVINOGVAExecutionBridge(endpoints, clock_ms=lambda: 1000)
        bridge.handshake_all()
        raw = context(
            branch="foreign_object",
            resource="gpu",
            topology_kind=SHARED_VIDEO_DAG,
            topology_worker_id="stream-0-shared-video-dag",
            topology_worker_trace_id="trace-shared",
            event_sequence=6,
            parent_execution_id="foreign-object-fanout",
        )

        result = bridge.emit_drop(
            context=raw,
            reason="native_pre_detector_queue_full_drop_newest",
        )

        parsed = RuntimeMessage.parse(json.dumps(result["terminal_event"]))
        self.assertEqual(parsed.event_kind, "branch_drop")
        self.assertEqual(parsed.objects, 0)
        self.assertFalse(result["inference_performed"])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["accepted_evidence_written"])
        self.assertFalse(clients[("foreign_object", "gpu")].requests)


if __name__ == "__main__":
    unittest.main()
