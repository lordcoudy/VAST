from __future__ import annotations

import copy
import hashlib
import os
import socket
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_protocol import (  # noqa: E402
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
)
from analytics_execution_worker import BackendInference, WorkerHarness  # noqa: E402
from checkpoint_deepstream_protocol_bridge import analytics_backend_identity  # noqa: E402
from checkpoint_gstreamer_analytics_bridge import (  # noqa: E402
    AnalyticsExecutionBridge,
    BRIDGE_MESSAGE_TYPE,
    _policy_binding,
    open_bridge_listener,
    preprocess_gstreamer_frame,
)


CPU_IMAGE = "sha256:41735f9c51fe9fb54b618f78983f312b5bd1135cc59e33526d24e1853e8d8235"
GPU_IMAGE = "sha256:75205ae88ebe9b53eec71bcdcc65b620437609dd8d84e582223cd0a8cf2495a6"
CPU_IMPLEMENTATION = "11bb76091b0380fae4a374abae8f305c216b17ee96019106902e2e987730f182"
GPU_IMPLEMENTATION = "7a09892dc72f86c825b3ec9055fdb25859f497caf86e9e32c4d35d79f96c5c46"
GPU_UUID = "GPU-00000000-0000-0000-0000-000000000001"
PREPROCESSING_SHA = hashlib.sha256(b"preprocessing").hexdigest()
OUTPUT_SHA = hashlib.sha256(b"output").hexdigest()


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _preprocessing_contract() -> dict[str, object]:
    return {
        "decoded_color_order": "RGB",
        "tensor_color_order": "RGB",
        "decode_dtype": "uint8",
        "resize_shorter_side": 256,
        "resize_long_side_formula": "floor(long_side*256/short_side+0.5)",
        "resize_algorithm": "bilinear",
        "resize_coordinate_transform": "half_pixel",
        "half_pixel_coordinate_formula": "src=(dst+0.5)*src_size/dst_size-0.5",
        "border_mode": "edge_clamp",
        "interpolation_accumulator_dtype": "float32",
        "interpolation_output_dtype": "float32",
        "interpolation_rounding": "none",
        "resize_rounding": "round_half_up",
        "center_crop": [224, 224],
        "normalization_scale": 0.00392156862745098,
        "normalization_mean": [0.485, 0.456, 0.406],
        "normalization_std": [0.229, 0.224, 0.225],
        "normalization_evaluation_order": (
            "float32((float32(pixel)*scale-mean[channel])/std[channel])"
        ),
        "normalization_accumulator_dtype": "float32",
        "channel_transform": "HWC_RGB_to_CHW_RGB",
        "output_dtype": "float32",
        "output_layout": "NCHW",
        "execution_shape": [1, 3, 224, 224],
        "tensor_serialization": "raw_f32_le_c_contiguous_v1",
        "tensor_header": "none",
        "tensor_endianness": "little",
        "tensor_memory_order": "C",
    }


def _capability(branch: str, engine: str) -> dict[str, object]:
    cpu = engine == ENGINE_OPENVINO_CPU
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_capability",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": f"vast.{branch}.{'openvino' if cpu else 'tensorrt'}",
        "branch": branch,
        "engine": engine,
        "worker_image_id": CPU_IMAGE if cpu else GPU_IMAGE,
        "worker_implementation_sha256": CPU_IMPLEMENTATION if cpu else GPU_IMPLEMENTATION,
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1.0" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Intel CPU fixture" if cpu else GPU_UUID,
        "native_inference_api": (
            "openvino.CompiledModel.__call__"
            if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "model_id": f"model-{branch}",
        "source_model_sha256": _sha(f"source-{branch}"),
        "model_artifact_sha256": _sha(f"artifact-{branch}-{engine}"),
        "runtime_weights_sha256": _sha(f"weights-{branch}") if cpu else None,
        "preprocessing_contract_sha256": PREPROCESSING_SHA,
        "output_contract_sha256": OUTPUT_SHA,
        "transport": "unix_seqpacket_scm_rights_sealed_memfd",
        "max_inflight_requests": 1,
        "max_tensor_bytes": 67_108_864,
    }


def _binding(capability: dict[str, object]) -> dict[str, object]:
    return {
        "worker_id": capability["worker_id"],
        "branch": capability["branch"],
        "model_id": capability["model_id"],
        "source_model_sha256": capability["source_model_sha256"],
        "model_artifact_sha256": capability["model_artifact_sha256"],
        "runtime_weights_sha256": capability["runtime_weights_sha256"],
        "preprocessing_contract_sha256": PREPROCESSING_SHA,
        "output_contract_sha256": OUTPUT_SHA,
        "input": {"name": "input", "dtype": "uint8", "layout": "NCHW", "shape": [1, 1, 1, 4]},
    }


def _policy_manifest() -> dict[str, object]:
    branch_bindings: dict[str, object] = {}
    for branch in BRANCHES:
        resources: dict[str, object] = {}
        for resource in ("cpu", "gpu"):
            capability = _capability(
                branch,
                ENGINE_OPENVINO_CPU if resource == "cpu" else ENGINE_TENSORRT_CUDA,
            )
            resources[resource] = {
                "implementation_id": f"gstreamer-{branch}-{resource}-implementation-v1",
                "terminal_detector": (
                    f"{capability['model_id']};"
                    f"model_sha256={capability['source_model_sha256']}"
                ),
                "terminal_backend": analytics_backend_identity(capability),
                "native_evidence": {
                    "emitter_id": f"gstreamer-{branch}-{resource}-emitter-v1",
                    "emitter_sha256": _sha(f"emitter-{branch}-{resource}"),
                },
            }
        branch_bindings[branch] = resources
    return {"systems": {"gstreamer_custom": {"branches": branch_bindings}}}


class _FixedBackend:
    def __init__(self, capability: dict[str, object]) -> None:
        self._capability = capability
        self.seen: list[bytes] = []

    def capability(self) -> dict[str, object]:
        return self._capability

    def infer(self, request: dict[str, object], tensor: memoryview) -> BackendInference:
        payload = bytes(tensor)
        self.seen.append(payload)
        output = hashlib.sha256(payload + str(self._capability["engine"]).encode("ascii")).digest()
        gpu = self._capability["engine"] == ENGINE_TENSORRT_CUDA
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
            terminal_reason="native_fixed_tensor_completed",
            accelerator_memory_bytes=4096 if gpu else 0,
            cuda_h2d_bytes=len(payload) if gpu else 0,
            cuda_d2h_bytes=len(output) if gpu else 0,
            cuda_transfer_intervals=(
                (
                    {
                        "direction": "h2d",
                        "host_start_monotonic_ns": 1_000_000,
                        "host_end_monotonic_ns": 1_400_000,
                        "device_elapsed_ns": 250_000,
                        "bytes": len(payload),
                        "device_id": self._capability["device_id"],
                        "timing_source": "cudaEventElapsedTime",
                    },
                    {
                        "direction": "d2h",
                        "host_start_monotonic_ns": 1_500_000,
                        "host_end_monotonic_ns": 1_800_000,
                        "device_elapsed_ns": 200_000,
                        "bytes": len(output),
                        "device_id": self._capability["device_id"],
                        "timing_source": "cudaEventElapsedTime",
                    },
                )
                if gpu
                else ()
            ),
        )


def _request(branch: str, resource: str, payload: bytes, *, sequence: int) -> dict[str, object]:
    policy = _policy_manifest()["systems"]["gstreamer_custom"]["branches"][branch][resource]
    return {
        "schema_version": 1,
        "message_type": BRIDGE_MESSAGE_TYPE,
        "request_id": f"bridge-request-{sequence:04d}",
        "run_id": "run-bridge-0001",
        "arm_id": "arm-bridge-0001",
        "gstreamer_worker_id": "checkpoint-worker-0001",
        "frame": {
            "input_frame_key": f"dataset:stream-0:frame-{sequence}",
            "stream_id": 0,
            "frame_id": sequence,
            "transport_pts_ns": sequence * 33_333_333,
            "branch": branch,
        },
        "decision": {
            "decision_id": f"decision-{sequence:04d}",
            "decision_seq": sequence,
            "selected_resource": resource,
            "selected_implementation_id": policy["implementation_id"],
            "emitter_id": policy["native_evidence"]["emitter_id"],
            "emitter_sha256": policy["native_evidence"]["emitter_sha256"],
        },
        "deadline_monotonic_ns": time.monotonic_ns() + 10_000_000_000,
        "payload": {
            "kind": "preprocessed_tensor",
            "name": "input",
            "dtype": "uint8",
            "layout": "NCHW",
            "shape": [1, 1, 1, 4],
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "preprocessing_contract_sha256": PREPROCESSING_SHA,
        },
    }


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SOCK_SEQPACKET") and hasattr(os, "memfd_create"),
    "Linux SOCK_SEQPACKET and memfd are required",
)
class GStreamerAnalyticsBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backends: dict[tuple[str, str], _FixedBackend] = {}
        self.worker_threads: list[threading.Thread] = []
        self.worker_server_sockets: list[socket.socket] = []
        self.worker_errors: list[BaseException] = []
        connections: dict[tuple[str, str], socket.socket] = {}
        capabilities: dict[tuple[str, str], dict[str, object]] = {}
        bindings: dict[tuple[str, str], dict[str, object]] = {}
        for branch in BRANCHES:
            for resource, engine in (
                ("cpu", ENGINE_OPENVINO_CPU),
                ("gpu", ENGINE_TENSORRT_CUDA),
            ):
                capability = _capability(branch, engine)
                backend = _FixedBackend(capability)
                server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                harness = WorkerHarness(server, backend, max_requests=2)

                def serve_worker(value: WorkerHarness = harness) -> None:
                    try:
                        value.serve()
                    except ProtocolError as error:
                        if str(error) != "analytics execution peer closed the socket":
                            self.worker_errors.append(error)

                thread = threading.Thread(target=serve_worker, daemon=True)
                thread.start()
                key = (branch, resource)
                self.backends[key] = backend
                self.worker_threads.append(thread)
                self.worker_server_sockets.append(server)
                connections[key] = client
                capabilities[key] = capability
                bindings[key] = _binding(capability)
        self.bridge = AnalyticsExecutionBridge(
            policy_capability_manifest=_policy_manifest(),
            worker_connections=connections,
            worker_capabilities=capabilities,
            worker_bindings=bindings,
        )

    def tearDown(self) -> None:
        self.bridge.close()
        for thread in self.worker_threads:
            thread.join(timeout=5)
        for server in self.worker_server_sockets:
            server.close()
        self.assertEqual(self.worker_errors, [])

    def test_policy_terminal_identity_is_exactly_worker_capability_bound(self) -> None:
        manifest = _policy_manifest()
        for branch in BRANCHES:
            for resource, engine in (
                ("cpu", ENGINE_OPENVINO_CPU),
                ("gpu", ENGINE_TENSORRT_CUDA),
            ):
                capability = _capability(branch, engine)
                policy = _policy_binding(manifest, branch, resource, capability)
                self.assertEqual(
                    policy["terminal_detector"],
                    (
                        f"{capability['model_id']};"
                        f"model_sha256={capability['source_model_sha256']}"
                    ),
                )
                self.assertEqual(
                    policy["terminal_backend"],
                    analytics_backend_identity(capability),
                )

        abbreviated = copy.deepcopy(manifest)
        abbreviated["systems"]["gstreamer_custom"]["branches"]["plate_number"][
            "gpu"
        ]["terminal_backend"] = (
            "analytics-execution:tensorrt_cuda;device=NVIDIA_CUDA:0"
        )
        with self.assertRaisesRegex(
            ProtocolError, "policy terminal identity differs from worker capability"
        ):
            _policy_binding(
                abbreviated,
                "plate_number",
                "gpu",
                _capability("plate_number", ENGINE_TENSORRT_CUDA),
            )

    def test_worker_protocol_proxy_binds_hello_route_and_forwards_one_memfd(self) -> None:
        capability = _capability("damage", ENGINE_OPENVINO_CPU)
        nonce = "a" * 64
        route, acknowledgement = self.bridge.worker_protocol_handshake(
            {
                "schema_version": 1,
                "message_type": "hello",
                "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
                "nonce": nonce,
                "expected_capability_sha256": canonical_sha256(capability),
            }
        )
        self.assertEqual(route, ("damage", "cpu"))
        self.assertEqual(acknowledgement["nonce"], nonce)
        self.assertEqual(acknowledgement["capability"], capability)

        payload = b"\x01\x02\x03\x04"
        request = {
            "schema_version": 1,
            "message_type": "infer_request",
            "request_id": "proxy-request-0001",
            "run_id": "proxy-run-0001",
            "arm_id": "proxy-arm-0001",
            "worker_id": capability["worker_id"],
            "frame": {
                "input_frame_key": "dataset:stream-0:frame-1",
                "stream_id": 0,
                "frame_id": 1,
                "transport_pts_ns": 33_333_333,
                "branch": "damage",
            },
            "engine": capability["engine"],
            "deadline_monotonic_ns": time.monotonic_ns() + 10_000_000_000,
            "model": {
                "model_id": capability["model_id"],
                "source_sha256": capability["source_model_sha256"],
                "runtime_artifact_sha256": capability[
                    "model_artifact_sha256"
                ],
                "runtime_weights_sha256": capability[
                    "runtime_weights_sha256"
                ],
            },
            "tensor": {
                "name": "input",
                "dtype": "uint8",
                "layout": "NCHW",
                "shape": [1, 1, 1, 4],
                "byte_length": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "preprocessing_contract_sha256": capability[
                    "preprocessing_contract_sha256"
                ],
            },
            "expected_output_contract_sha256": capability[
                "output_contract_sha256"
            ],
        }
        response, output = self.bridge.execute_worker_protocol(
            request, payload, route=route
        )
        self.assertEqual(response["message_type"], "infer_response")
        self.assertEqual(response["request_id"], "proxy-request-0001")
        self.assertEqual(hashlib.sha256(output).hexdigest(), response["output"]["sha256"])
        self.assertEqual(self.backends[route].seen, [payload])

        with self.assertRaisesRegex(ProtocolError, "absent or ambiguous"):
            self.bridge.worker_protocol_handshake(
                {
                    "schema_version": 1,
                    "message_type": "hello",
                    "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
                    "nonce": "b" * 64,
                    "expected_capability_sha256": "0" * 64,
                }
            )

    def test_routes_all_eight_branch_resource_bindings_through_real_memfd_worker_roundtrip(self) -> None:
        sequence = 1
        for branch in BRANCHES:
            for resource in ("cpu", "gpu"):
                payload = bytes((sequence, sequence + 1, sequence + 2, sequence + 3))
                response = self.bridge.execute(_request(branch, resource, payload, sequence=sequence), payload)
                self.assertEqual(self.backends[(branch, resource)].seen, [payload])
                self.assertEqual(response["decision_id"], f"decision-{sequence:04d}")
                self.assertEqual(response["selected_resource"], resource)
                self.assertEqual(response["terminal_status"], "completed")
                self.assertEqual(response["objects"], 1)
                self.assertEqual(response["device_api"], "CPU" if resource == "cpu" else "NVIDIA_CUDA")
                self.assertEqual(response["worker_image_id"], CPU_IMAGE if resource == "cpu" else GPU_IMAGE)
                self.assertEqual(response["raw_input_sha256"], hashlib.sha256(payload).hexdigest())
                self.assertRegex(response["output_sha256"], r"^[0-9a-f]{64}$")
                receipt = response["resource"]
                self.assertEqual(
                    set(receipt),
                    {
                        "process_cpu_time_ns",
                        "rss_before_bytes",
                        "rss_after_bytes",
                        "accelerator_memory_bytes",
                        "cuda_h2d_bytes",
                        "cuda_d2h_bytes",
                        "cuda_transfer_intervals",
                    },
                )
                if resource == "cpu":
                    self.assertEqual(receipt["accelerator_memory_bytes"], 0)
                    self.assertEqual(receipt["cuda_h2d_bytes"], 0)
                    self.assertEqual(receipt["cuda_d2h_bytes"], 0)
                    self.assertEqual(receipt["cuda_transfer_intervals"], [])
                else:
                    self.assertEqual(receipt["accelerator_memory_bytes"], 4096)
                    self.assertEqual(receipt["cuda_h2d_bytes"], len(payload))
                    self.assertEqual(receipt["cuda_d2h_bytes"], 32)
                    intervals = receipt["cuda_transfer_intervals"]
                    self.assertEqual(
                        [interval["direction"] for interval in intervals],
                        ["h2d", "d2h"],
                    )
                    self.assertTrue(
                        all(interval["device_id"] == GPU_UUID for interval in intervals)
                    )
                    self.assertTrue(
                        all(
                            interval["timing_source"] == "cudaEventElapsedTime"
                            for interval in intervals
                        )
                    )
                sequence += 1

    def test_front_transport_rejects_relabel_and_accepts_one_sealed_tensor(self) -> None:
        payload = b"\x01\x02\x03\x04"
        request = _request("plate_number", "cpu", payload, sequence=9)
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        thread = threading.Thread(target=self.bridge.serve_connection, args=(server,), kwargs={"max_requests": 1}, daemon=True)
        thread.start()
        input_fd = create_sealed_memfd("bridge-test-input", payload)
        try:
            send_packet(client, request, fds=(input_fd,))
        finally:
            os.close(input_fd)
        response, fds = receive_packet(client, expected_fds=0)
        close_fds(fds)
        self.assertEqual(response["message_type"], "analytics_execute_response")
        self.assertEqual(response["input_sha256"], hashlib.sha256(payload).hexdigest())
        client.close()
        thread.join(timeout=5)
        server.close()
        self.assertFalse(thread.is_alive())

        relabelled = _request("damage", "gpu", payload, sequence=10)
        relabelled["decision"]["selected_implementation_id"] = "forged-gpu-implementation"
        with self.assertRaisesRegex(ProtocolError, "implementation"):
            self.bridge.execute(relabelled, payload)

    def test_absolute_unix_socket_listener_accepts_a_real_path_client(self) -> None:
        import tempfile

        payload = b"\x01\x02\x03\x04"
        request = _request("plate_number", "cpu", payload, sequence=12)
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "gstreamer-analytics.sock"
            listener = open_bridge_listener(socket_path)
            thread = threading.Thread(
                target=self.bridge.serve_listener,
                args=(listener,),
                kwargs={"max_connections": 1, "max_requests_per_connection": 1},
                daemon=True,
            )
            thread.start()
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(socket_path))
            input_fd = create_sealed_memfd("bridge-path-input", payload)
            try:
                send_packet(client, request, fds=(input_fd,))
            finally:
                os.close(input_fd)
            response, fds = receive_packet(client, expected_fds=0)
            close_fds(fds)
            client.close()
            thread.join(timeout=5)
            listener.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(response["terminal_status"], "completed")
            self.assertEqual(response["raw_input_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertTrue(socket_path.exists())

            with self.assertRaisesRegex(ProtocolError, "already exists"):
                open_bridge_listener(socket_path)

    def test_listener_serves_two_persistent_path_clients_concurrently(self) -> None:
        import tempfile

        first_payload = b"\x01\x02\x03\x04"
        second_payload = b"\x05\x06\x07\x08"
        server_errors: list[BaseException] = []
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = Path(tmp) / "gstreamer-concurrent.sock"
            listener = open_bridge_listener(socket_path, backlog=2)

            def serve() -> None:
                try:
                    self.bridge.serve_listener(
                        listener,
                        max_connections=2,
                        max_requests_per_connection=1,
                    )
                except BaseException as error:
                    server_errors.append(error)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            first = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            second = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            first.settimeout(2.0)
            second.settimeout(2.0)
            first.connect(str(socket_path))
            second.connect(str(socket_path))
            try:
                second_fd = create_sealed_memfd("bridge-second-input", second_payload)
                try:
                    send_packet(
                        second,
                        _request("damage", "gpu", second_payload, sequence=14),
                        fds=(second_fd,),
                    )
                finally:
                    os.close(second_fd)
                second_response, second_fds = receive_packet(second, expected_fds=0)
                close_fds(second_fds)

                first_fd = create_sealed_memfd("bridge-first-input", first_payload)
                try:
                    send_packet(
                        first,
                        _request("plate_number", "cpu", first_payload, sequence=13),
                        fds=(first_fd,),
                    )
                finally:
                    os.close(first_fd)
                first_response, first_fds = receive_packet(first, expected_fds=0)
                close_fds(first_fds)
            finally:
                first.close()
                second.close()
                thread.join(timeout=5)
                listener.close()

            self.assertFalse(thread.is_alive())
            self.assertEqual(server_errors, [])
            self.assertEqual(second_response["selected_resource"], "gpu")
            self.assertEqual(first_response["selected_resource"], "cpu")

    def test_raw_bgr_frame_is_exactly_preprocessed_to_frozen_fp32_nchw_contract(self) -> None:
        contract = _preprocessing_contract()
        # BGR=(30,20,10), with one padding byte per row. The RGB image is constant,
        # so resize/crop cannot hide channel-order or stride errors.
        row = bytes([30, 20, 10] * 4 + [255])
        tensor, descriptor = preprocess_gstreamer_frame(
            row * 2,
            frame={"format": "BGR", "width": 4, "height": 2, "stride": 13},
            preprocessing_contract=contract,
            expected_contract_sha256=canonical_sha256(contract),
            tensor_name="input",
        )
        self.assertEqual(descriptor["dtype"], "float32")
        self.assertEqual(descriptor["layout"], "NCHW")
        self.assertEqual(descriptor["shape"], [1, 3, 224, 224])
        self.assertEqual(descriptor["byte_length"], 1 * 3 * 224 * 224 * 4)
        self.assertEqual(descriptor["sha256"], hashlib.sha256(tensor).hexdigest())
        import numpy as np

        values = np.frombuffer(tensor, dtype="<f4").reshape(1, 3, 224, 224)
        expected = [
            (10.0 / 255.0 - 0.485) / 0.229,
            (20.0 / 255.0 - 0.456) / 0.224,
            (30.0 / 255.0 - 0.406) / 0.225,
        ]
        for channel in range(3):
            self.assertTrue(np.all(values[0, channel] == values[0, channel, 0, 0]))
            self.assertAlmostEqual(float(values[0, channel, 0, 0]), expected[channel], places=6)

    def test_raw_gstbuffer_reaches_selected_frozen_worker_as_exact_preprocessed_tensor(self) -> None:
        contract = _preprocessing_contract()
        preprocessing_sha = canonical_sha256(contract)
        worker_threads: list[threading.Thread] = []
        worker_servers: list[socket.socket] = []
        worker_errors: list[BaseException] = []
        connections: dict[tuple[str, str], socket.socket] = {}
        capabilities: dict[tuple[str, str], dict[str, object]] = {}
        bindings: dict[tuple[str, str], dict[str, object]] = {}
        backends: dict[tuple[str, str], _FixedBackend] = {}
        for branch in BRANCHES:
            for resource, engine in (
                ("cpu", ENGINE_OPENVINO_CPU),
                ("gpu", ENGINE_TENSORRT_CUDA),
            ):
                capability = _capability(branch, engine)
                capability["preprocessing_contract_sha256"] = preprocessing_sha
                binding = _binding(capability)
                binding["preprocessing_contract_sha256"] = preprocessing_sha
                binding["input"] = {
                    "name": "input",
                    "dtype": "float32",
                    "layout": "NCHW",
                    "shape": [1, 3, 224, 224],
                }
                backend = _FixedBackend(capability)
                server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                harness = WorkerHarness(server, backend, max_requests=1)

                def serve_worker(value: WorkerHarness = harness) -> None:
                    try:
                        value.serve()
                    except ProtocolError as error:
                        if str(error) != "analytics execution peer closed the socket":
                            worker_errors.append(error)

                thread = threading.Thread(target=serve_worker, daemon=True)
                thread.start()
                key = (branch, resource)
                worker_threads.append(thread)
                worker_servers.append(server)
                connections[key] = client
                capabilities[key] = capability
                bindings[key] = binding
                backends[key] = backend
        bridge = AnalyticsExecutionBridge(
            policy_capability_manifest=_policy_manifest(),
            worker_connections=connections,
            worker_capabilities=capabilities,
            worker_bindings=bindings,
            preprocessing_contract=contract,
        )
        try:
            row = bytes([30, 20, 10] * 4 + [255])
            raw = row * 2
            request = _request("foreign_object", "gpu", raw, sequence=11)
            request["payload"] = {
                "kind": "raw_gstreamer_frame",
                "format": "BGR",
                "width": 4,
                "height": 2,
                "stride": 13,
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "preprocessing_contract_sha256": preprocessing_sha,
            }
            expected_tensor, expected_descriptor = preprocess_gstreamer_frame(
                raw,
                frame={"format": "BGR", "width": 4, "height": 2, "stride": 13},
                preprocessing_contract=contract,
                expected_contract_sha256=preprocessing_sha,
                tensor_name="input",
            )
            response = bridge.execute(request, raw)
            self.assertEqual(backends[("foreign_object", "gpu")].seen, [expected_tensor])
            self.assertEqual(response["selected_resource"], "gpu")
            self.assertEqual(response["device_api"], "NVIDIA_CUDA")
            self.assertEqual(response["raw_input_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(response["input_sha256"], expected_descriptor["sha256"])
        finally:
            bridge.close()
            for thread in worker_threads:
                thread.join(timeout=5)
            for server in worker_servers:
                server.close()
        self.assertEqual(worker_errors, [])


if __name__ == "__main__":
    unittest.main()
