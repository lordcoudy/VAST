from __future__ import annotations

import copy
import hashlib
import itertools
import json
import sys
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_deepstream_protocol_bridge import (  # noqa: E402
    DeepStreamExecutionEndpoint,
    DeepStreamProtocolBridge,
    DeepStreamProtocolBridgeError,
    analytics_backend_identity,
)
from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
)
from analytics_execution_endpoint import terminal_detector_identity  # noqa: E402
from checkpoint_runtime import DirectRuntimeJoinCoordinator, WorkerBinding  # noqa: E402
from publication_policy_contract import ANALYTICS_BRANCHES  # noqa: E402
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG  # noqa: E402


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


SOURCE_MODEL_SHA = sha("source-model")
CPU_ARTIFACT_SHA = sha("cpu-artifact")
GPU_ARTIFACT_SHA = sha("gpu-artifact")
WEIGHTS_SHA = sha("weights")
PREPROCESS_SHA = sha("preprocess")
OUTPUT_CONTRACT_SHA = sha("output-contract")
IMPLEMENTATION_SHA = sha("worker-source")
VIDEO_SHA = sha("video")
AU_SHA = sha("access-unit")
IMAGE_ID = "sha256:" + sha("worker-image")


class StepClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        self.value += 1.0
        return self.value


class SequenceClock:
    def __init__(self, *values: float) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


def mock_service_clock(test_case: unittest.TestCase) -> None:
    # Pair the synthetic worker's 1 ms envelope with a deterministic elapsed
    # clock. Epoch timestamps remain independently controlled by each test.
    test_case.enterContext(mock.patch(
        "checkpoint_deepstream_protocol_bridge.time.monotonic_ns",
        side_effect=itertools.count(1_000_000, 1_000_000),
    ))


def admission(run_id: str, *, stream_id: int = 0) -> dict[str, object]:
    dataset, pts = "kpp-real-h264", 90_000
    return {
        "protocol_version": 1,
        "source_process_id": f"stream-{stream_id}-source-coordinator",
        "sequence": 1,
        "run_id": run_id,
        "dataset_id": dataset,
        "stream_id": stream_id,
        "admission_id": f"{run_id}:{stream_id}:admission:1",
        "input_frame_key": f"{dataset}:{stream_id}:{VIDEO_SHA}:0:{pts}",
        "source_sha256": VIDEO_SHA,
        "source_cycle": 0,
        "access_unit_pts_ns": pts,
        "payload_sha256": AU_SHA,
        "payload_size_bytes": 1_024,
        "schedule_offset_ns": 0,
        "admission_timestamp_ms": 1_000,
        "event_provenance": "native_common_source_coordinator",
    }


def nvds_identity(value: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "deepstream_nvds_frame_identity",
        "admission_id": value["admission_id"],
        "input_frame_key": value["input_frame_key"],
        "stream_id": value["stream_id"],
        "frame_id": 0,
        "transport_pts_ns": value["access_unit_pts_ns"],
        "payload_sha256": value["payload_sha256"],
        "nvds_source_id": 0,
        "nvds_frame_num": 0,
        "nvds_buf_pts_ns": value["access_unit_pts_ns"],
        "mux_gst_buffer_pts_ns": 123,
        "decoder_factory": "nvv4l2decoder",
        "decoder_gpu_id": 0,
    }


def tensor(branch: str) -> tuple[dict[str, object], bytes]:
    payload = bytes([ANALYTICS_BRANCHES.index(branch) + 1]) * 12
    return {
        "name": "input",
        "dtype": "uint8",
        "layout": "NHWC",
        "shape": [1, 2, 2, 3],
        "byte_length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "preprocessing_contract_sha256": PREPROCESS_SHA,
    }, payload


def capability(branch: str, resource: str) -> dict[str, object]:
    cpu = resource == "cpu"
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_capability",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": f"analytics-{branch}-{resource}",
        "branch": branch,
        "engine": ENGINE_OPENVINO_CPU if cpu else ENGINE_TENSORRT_CUDA,
        "worker_image_id": IMAGE_ID,
        "worker_implementation_sha256": IMPLEMENTATION_SHA,
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Intel CPU" if cpu else "GPU-00000000-0000-0000-0000-000000000001",
        "native_inference_api": (
            "openvino.CompiledModel.__call__" if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "model_id": f"topology-proxy-{branch}-v1",
        "source_model_sha256": SOURCE_MODEL_SHA,
        "model_artifact_sha256": CPU_ARTIFACT_SHA if cpu else GPU_ARTIFACT_SHA,
        "runtime_weights_sha256": WEIGHTS_SHA if cpu else None,
        "preprocessing_contract_sha256": PREPROCESS_SHA,
        "output_contract_sha256": OUTPUT_CONTRACT_SHA,
        "transport": "unix_seqpacket_scm_rights_sealed_memfd",
        "max_inflight_requests": 1,
        "max_tensor_bytes": 67_108_864,
    }


class FakeExecutionClient:
    def __init__(self, attestation: dict[str, object], *, corrupt: bool = False) -> None:
        self.attestation = attestation
        self.corrupt = corrupt

    def infer(self, request: dict[str, object], payload: bytes) -> tuple[dict, bytes]:
        output = hashlib.sha256(payload).digest()
        cpu = request["engine"] == ENGINE_OPENVINO_CPU
        transfer_intervals = [] if cpu else [
            {
                "direction": "h2d",
                "host_start_monotonic_ns": 1_000_000,
                "host_end_monotonic_ns": 1_400_000,
                "device_elapsed_ns": 250_000,
                "bytes": len(payload),
                "device_id": self.attestation["device_id"],
                "timing_source": "cudaEventElapsedTime",
            },
            {
                "direction": "d2h",
                "host_start_monotonic_ns": 1_500_000,
                "host_end_monotonic_ns": 1_800_000,
                "device_elapsed_ns": 200_000,
                "bytes": len(output),
                "device_id": self.attestation["device_id"],
                "timing_source": "cudaEventElapsedTime",
            },
        ]
        provenance = {
            "worker_image_id": self.attestation["worker_image_id"],
            "worker_implementation_sha256": self.attestation["worker_implementation_sha256"],
            "runtime_name": self.attestation["runtime_name"],
            "runtime_version": self.attestation["runtime_version"],
            "device_api": self.attestation["device_api"],
            "device_id": self.attestation["device_id"],
            "native_inference_api": self.attestation["native_inference_api"],
            "execution_path": self.attestation["execution_path"],
            "model_id": self.attestation["model_id"],
            "source_model_sha256": self.attestation["source_model_sha256"],
            "model_artifact_sha256": self.attestation["model_artifact_sha256"],
            "runtime_weights_sha256": self.attestation["runtime_weights_sha256"],
            "preprocessing_contract_sha256": self.attestation["preprocessing_contract_sha256"],
            "output_contract_sha256": self.attestation["output_contract_sha256"],
            "input_sha256": hashlib.sha256(payload).hexdigest(),
            "output_sha256": hashlib.sha256(output).hexdigest(),
        }
        if self.corrupt:
            provenance["device_api"] = "NVIDIA_CUDA" if cpu else "CPU"
        return {
            "schema_version": 1,
            "message_type": "infer_response",
            "request_id": request["request_id"],
            "run_id": request["run_id"],
            "arm_id": request["arm_id"],
            "worker_id": request["worker_id"],
            "frame": copy.deepcopy(request["frame"]),
            "engine": request["engine"],
            "terminal": {
                "status": "completed", "objects": 2,
                "reason": "native_inference_completed",
            },
            "output": {
                "byte_length": len(output),
                "sha256": hashlib.sha256(output).hexdigest(),
                "contract_sha256": request["expected_output_contract_sha256"],
                "tensor_count": 1,
                "tensors": [{
                    "name": "scores", "dtype": "uint8", "shape": [1, len(output)],
                    "offset": 0, "byte_length": len(output),
                }],
            },
            "provenance": provenance,
            "timing": {
                "worker_received_monotonic_ns": 1_000_000,
                "inference_started_monotonic_ns": 1_100_000,
                "inference_finished_monotonic_ns": 1_900_000,
                "worker_completed_monotonic_ns": 2_000_000,
                "inference_latency_ns": 800_000,
            },
            "resource": {
                "process_cpu_time_ns": 100_000,
                "rss_before_bytes": 1_000_000,
                "rss_after_bytes": 1_001_000,
                "accelerator_memory_bytes": 0 if cpu else 4_096,
                "cuda_h2d_bytes": 0 if cpu else len(payload),
                "cuda_d2h_bytes": 0 if cpu else len(output),
                "cuda_transfer_intervals": transfer_intervals,
            },
        }, output


class FakePolicyExchange:
    def __init__(self, placements: dict[str, str]) -> None:
        self.placements = placements
        self.messages: list[dict[str, object]] = []
        self.sequence = 0

    def __call__(self, message: dict[str, object]) -> dict[str, object]:
        self.messages.append(copy.deepcopy(message))
        if message["message_type"] == "decision_request":
            self.sequence += 1
            resource = self.placements[str(message["branch"])]
            return {
                "schema_version": 1,
                "message_type": "decision_response",
                "decision_id": f"decision-{self.sequence}",
                "decision_seq": self.sequence,
                "selected_resource": resource,
                "selected_implementation_id": f"deepstream-{message['branch']}-{resource}",
                "emitter_id": "deepstream-protocol-bridge-v1",
                "emitter_sha256": "e" * 64,
            }
        suffix = "path" if message["message_type"] == "path_enter" else "terminal"
        return {
            "schema_version": 1,
            "message_type": f"{suffix}_ack",
            "decision_id": message["decision_id"],
            "accepted": True,
        }


class FakeResourceRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record_analytics_transfers(self, **values: object) -> None:
        self.calls.append(copy.deepcopy(values))


def endpoints(
    branches: tuple[str, ...], *, corrupt_branch: str | None = None,
) -> dict[str, dict[str, DeepStreamExecutionEndpoint]]:
    result: dict[str, dict[str, DeepStreamExecutionEndpoint]] = {}
    for branch in branches:
        result[branch] = {}
        for resource in ("cpu", "gpu"):
            attestation = capability(branch, resource)
            result[branch][resource] = DeepStreamExecutionEndpoint(
                resource=resource,
                implementation_id=f"deepstream-{branch}-{resource}",
                capability=attestation,
                client=FakeExecutionClient(
                    attestation,
                    corrupt=branch == corrupt_branch and resource == "cpu",
                ),
            )
    return result


class DeepStreamProtocolBridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        mock_service_clock(self)

    def test_public_bridge_surface_exists(self) -> None:
        self.assertTrue(DeepStreamExecutionEndpoint)
        self.assertTrue(DeepStreamProtocolBridge)
        self.assertTrue(DeepStreamProtocolBridgeError)
        self.assertTrue(analytics_backend_identity)

    def test_nonzero_logical_stream_uses_physical_single_mux_source_zero(self) -> None:
        run_id = "run-deepstream-logical-stream-5"
        admitted = admission(run_id, stream_id=5)
        identity = nvds_identity(admitted)
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-logical-stream-5",
            worker_id="deepstream-stream-5-branch-damage",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=5,
            branch_id="damage",
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({"damage": "cpu"}),
            analytics_endpoints=endpoints(("damage",)),
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)

    def test_serialized_events_clamp_prelock_observation_timestamp_race(self) -> None:
        run_id = "run-deepstream-observation-race"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        rows: list[dict[str, object]] = []
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-observation-race",
            worker_id="deepstream-stream-0-branch-damage",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id="damage",
            event_sink=lambda line: rows.append(json.loads(line)),
            policy_exchange=FakePolicyExchange({"damage": "cpu"}),
            analytics_endpoints=endpoints(("damage",)),
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(
            json.dumps(admitted), observed_timestamp_ms=1_000
        )
        bridge.observe_decoded_frame(identity, observed_timestamp_ms=1_002)
        bridge.observe_preprocessed_frame(identity, observed_timestamp_ms=1_001)
        self.assertEqual(
            [row["timestamp_ms"] for row in rows],
            [1_000, 1_002, 1_002],
        )

    def test_shared_fanout_returns_clamped_serialized_timestamp(self) -> None:
        run_id = "run-deepstream-fanout-observation-race"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        rows: list[dict[str, object]] = []
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-fanout-observation-race",
            worker_id="deepstream-shared-stream-0",
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=lambda line: rows.append(json.loads(line)),
            policy_exchange=FakePolicyExchange(
                {branch: "cpu" for branch in ANALYTICS_BRANCHES}
            ),
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(
            json.dumps(admitted), observed_timestamp_ms=1_000
        )
        bridge.observe_decoded_frame(identity, observed_timestamp_ms=1_005)
        bridge.observe_preprocessed_frame(identity, observed_timestamp_ms=1_004)
        serialized = bridge.observe_fanout(
            identity,
            branch="damage",
            observed_timestamp_ms=1_001,
        )
        self.assertEqual(serialized, 1_005)
        self.assertEqual(rows[-1]["timestamp_ms"], 1_005)

    def test_policy_path_clamps_wall_clock_regression_after_decision_ack(self) -> None:
        run_id = "run-deepstream-policy-clock-regression"
        branch = "damage"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        policy = FakePolicyExchange(
            {item: "cpu" for item in ANALYTICS_BRANCHES}
        )
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-policy-clock-regression",
            worker_id="deepstream-shared-stream-0",
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=lambda _line: None,
            policy_exchange=policy,
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            clock_ms=SequenceClock(2_000.5, 1_999.5, 2_003.0),
        )
        spec, payload = tensor(branch)
        bridge.admit_access_unit(
            json.dumps(admitted), observed_timestamp_ms=1_000
        )
        bridge.observe_decoded_frame(identity, observed_timestamp_ms=1_001)
        bridge.observe_preprocessed_frame(
            identity, observed_timestamp_ms=1_002
        )
        bridge.observe_fanout(
            identity,
            branch=branch,
            tensor_spec=spec,
            observed_timestamp_ms=1_003,
        )

        result = bridge.execute_branch(
            str(admitted["input_frame_key"]),
            branch,
            tensor_payload=payload,
            queue_depths={"cpu": 0, "gpu": 0},
            deadline_monotonic_ns=10_000_000_000,
        )

        self.assertEqual(result.selected_resource, "cpu")
        decision = next(
            message
            for message in policy.messages
            if message["message_type"] == "decision_request"
        )
        path = next(
            message
            for message in policy.messages
            if message["message_type"] == "path_enter"
        )
        self.assertEqual(decision["decision_time_ms"], 2_000.5)
        self.assertEqual(path["timestamp_ms"], 2_000.5)

    def test_gpu_topology_uses_native_d2h_boundaries(self) -> None:
        run_id = "run-deepstream-gpu-transfer-boundaries"
        branch = "damage"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        rows: list[dict[str, object]] = []
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-gpu-transfer-boundaries",
            worker_id="deepstream-stream-0-branch-damage",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id=branch,
            event_sink=lambda line: rows.append(json.loads(line)),
            policy_exchange=FakePolicyExchange({branch: "gpu"}),
            analytics_endpoints=endpoints((branch,)),
            clock_ms=StepClock(),
        )
        spec, payload = tensor(branch)
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity, tensor_spec=spec)
        bridge.execute_branch(
            str(admitted["input_frame_key"]),
            branch,
            tensor_payload=payload,
            queue_depths={"cpu": 0, "gpu": 0},
            deadline_monotonic_ns=10_000_000_000,
        )

        analytics = next(row for row in rows if row["stage"] == branch)
        postprocess = next(
            row for row in rows if row["stage"] == f"postprocess_{branch}"
        )
        self.assertEqual(analytics["timestamp_ms"], 1_006)
        self.assertEqual(postprocess["timestamp_ms"], 1_006)
        self.assertEqual(
            postprocess["parent_execution_ids"], [analytics["execution_id"]]
        )

    def test_pre_detector_queue_drop_retains_verified_branch_model_identity(self) -> None:
        run_id = "run-deepstream-queue-drop-model-identity"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        rows: list[dict[str, object]] = []
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-queue-drop-model-identity",
            worker_id="deepstream-stream-0-branch-damage",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id="damage",
            event_sink=lambda line: rows.append(json.loads(line)),
            policy_exchange=FakePolicyExchange({"damage": "cpu"}),
            analytics_endpoints=endpoints(("damage",)),
            clock_ms=StepClock(),
        )
        spec, _payload = tensor("damage")
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity, tensor_spec=spec)
        bridge.drop_branch(
            str(admitted["input_frame_key"]),
            "damage",
            reason="native_pre_detector_queue_full_drop_newest",
        )

        terminal = rows[-1]
        self.assertEqual(terminal["event_kind"], "branch_drop")
        self.assertEqual(
            terminal["detector"],
            terminal_detector_identity(capability("damage", "cpu")),
        )
        self.assertEqual(terminal["backend"], "deepstream:native_pre_detector_queue")

    def test_baseline_four_independent_workers_form_one_causal_join(self) -> None:
        run_id = "run-deepstream-baseline"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        placements = {
            branch: ("cpu" if index % 2 == 0 else "gpu")
            for index, branch in enumerate(ANALYTICS_BRANCHES)
        }
        policy = FakePolicyExchange(placements)
        bindings = [
            WorkerBinding(
                worker_id=f"deepstream-baseline-{branch}",
                stream_id=0,
                branch_id=branch,
                pid=2_000 + index,
                execution_domain=f"fixture:baseline:{branch}",
                native_event_source=False,
            )
            for index, branch in enumerate(ANALYTICS_BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id=run_id,
            topology_kind=INDEPENDENT_PROCESSES,
            topology_contract_version=2,
            branches=ANALYTICS_BRANCHES,
            bindings=bindings,
            coordinator_pid=9_999,
            hostname="fixture",
            clock_ms=lambda: 2_000,
        )
        raw_events: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []
        for binding in bindings:
            def sink(line: str, current: WorkerBinding = binding) -> None:
                raw_events.append(json.loads(line))
                rows.extend(coordinator.accept(
                    line,
                    observed_worker_id=current.worker_id,
                    observed_pid=current.pid,
                ))

            branch = str(binding.branch_id)
            bridge = DeepStreamProtocolBridge(
                run_id=run_id,
                arm_id="arm-baseline",
                worker_id=binding.worker_id,
                topology_kind=INDEPENDENT_PROCESSES,
                stream_id=0,
                branch_id=branch,
                event_sink=sink,
                policy_exchange=policy,
                analytics_endpoints=endpoints((branch,)),
                clock_ms=StepClock(),
            )
            spec, payload = tensor(branch)
            bridge.admit_access_unit(json.dumps(admitted))
            bridge.observe_decoded_frame(identity)
            bridge.observe_preprocessed_frame(identity, tensor_spec=spec)
            result = bridge.execute_branch(
                str(admitted["input_frame_key"]),
                branch,
                tensor_payload=payload,
                queue_depths={"cpu": 0, "gpu": 0},
                deadline_monotonic_ns=10_000_000_000,
            )
            self.assertEqual(result.selected_resource, placements[branch])

        self.assertEqual(coordinator.unresolved_frames(), ())
        self.assertEqual(sum(row["event_kind"] == "join_complete" for row in rows), 1)
        self.assertEqual(sum(row["event_kind"] == "source_read" for row in raw_events), 4)
        canonical_prefix = f"{run_id}:0:0:"
        self.assertTrue(all(
            str(row["execution_id"]).startswith(canonical_prefix)
            for row in raw_events
            if row["event_kind"] != "source_read"
        ))
        self.assertTrue(all(
            str(row["execution_id"]).startswith(
                f"{run_id}:0:0:{row['worker_id']}:"
            )
            for row in raw_events
            if row["event_kind"] == "source_read"
        ))
        terminals = [row for row in raw_events if row["event_kind"] == "branch_complete"]
        self.assertEqual(len(terminals), 4)
        by_id = {str(row["execution_id"]): row for row in raw_events}
        for terminal in terminals:
            branch = str(terminal["branch_id"])
            postprocess = by_id[str(terminal["parent_execution_ids"][0])]
            self.assertEqual(postprocess["event_kind"], "stage_complete")
            self.assertEqual(postprocess["stage"], f"postprocess_{branch}")
            analytics = by_id[str(postprocess["parent_execution_ids"][0])]
            self.assertEqual(analytics["event_kind"], "stage_complete")
            self.assertEqual(analytics["stage"], branch)
        self.assertTrue(all(row["protocol_version"] == 3 for row in terminals))
        self.assertTrue(all(
            row["protocol_version"] == 2
            for row in raw_events
            if row["event_kind"] != "branch_complete"
        ))

    def test_shared_graph_has_one_prefix_four_fanouts_and_cpu_gpu_terminals(self) -> None:
        run_id = "run-deepstream-shared"
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        placements = {
            branch: ("cpu" if index % 2 == 0 else "gpu")
            for index, branch in enumerate(ANALYTICS_BRANCHES)
        }
        policy = FakePolicyExchange(placements)
        resource_recorder = FakeResourceRecorder()
        binding = WorkerBinding(
            worker_id="deepstream-shared-0",
            stream_id=0,
            branch_id=None,
            pid=3_000,
            execution_domain="fixture:shared:0",
            native_event_source=False,
        )
        coordinator = DirectRuntimeJoinCoordinator(
            run_id=run_id,
            topology_kind=SHARED_VIDEO_DAG,
            topology_contract_version=2,
            branches=ANALYTICS_BRANCHES,
            bindings=[binding],
            coordinator_pid=9_999,
            hostname="fixture",
            clock_ms=lambda: 2_000,
        )
        raw_events: list[dict[str, object]] = []
        rows: list[dict[str, object]] = []

        def sink(line: str) -> None:
            raw_events.append(json.loads(line))
            rows.extend(coordinator.accept(
                line, observed_worker_id=binding.worker_id, observed_pid=binding.pid
            ))

        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-shared",
            worker_id=binding.worker_id,
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=sink,
            policy_exchange=policy,
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            resource_recorder=resource_recorder,
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity)
        payloads: dict[str, bytes] = {}
        for branch in ANALYTICS_BRANCHES:
            spec, payloads[branch] = tensor(branch)
            bridge.observe_fanout(identity, branch=branch, tensor_spec=spec)
        for branch in ANALYTICS_BRANCHES:
            bridge.execute_branch(
                str(admitted["input_frame_key"]),
                branch,
                tensor_payload=payloads[branch],
                queue_depths={"cpu": 0, "gpu": 0},
                deadline_monotonic_ns=10_000_000_000,
            )

        self.assertEqual(coordinator.unresolved_frames(), ())
        self.assertEqual(sum(row["event_kind"] == "join_complete" for row in rows), 1)
        kinds = [row["event_kind"] for row in raw_events]
        self.assertEqual(kinds.count("source_read"), 1)
        self.assertEqual(kinds.count("fanout"), 4)
        self.assertEqual(kinds.count("stage_complete"), 10)
        self.assertEqual(kinds.count("branch_complete"), 4)
        by_id = {str(row["execution_id"]): row for row in raw_events}
        for terminal in (
            row for row in raw_events if row["event_kind"] == "branch_complete"
        ):
            branch = str(terminal["branch_id"])
            postprocess = by_id[str(terminal["parent_execution_ids"][0])]
            self.assertEqual(postprocess["stage"], f"postprocess_{branch}")
            analytics = by_id[str(postprocess["parent_execution_ids"][0])]
            self.assertEqual(analytics["stage"], branch)
        self.assertTrue(all(
            str(row["execution_id"]).startswith(f"{run_id}:0:0:")
            for row in raw_events
            if row["event_kind"] != "source_read"
        ))
        terminals = [
            message for message in policy.messages if message["message_type"] == "terminal"
        ]
        self.assertEqual(len(terminals), 4)
        self.assertEqual(len(resource_recorder.calls), 4)
        self.assertEqual(
            {
                (str(row["branch"]), str(row["selected_resource"]))
                for row in resource_recorder.calls
            },
            set(placements.items()),
        )
        for message in terminals:
            branch = str(message["branch"])
            expected = capability(branch, placements[branch])
            self.assertEqual(message["selected_resource"], placements[branch])
            self.assertEqual(
                message["detector"],
                (
                    f"{expected['model_id']};"
                    f"model_sha256={expected['source_model_sha256']}"
                ),
            )
            self.assertEqual(message["backend"], analytics_backend_identity(expected))

    def test_corrupt_provenance_cannot_be_relabelled_as_branch_terminal(self) -> None:
        run_id = "run-deepstream-negative"
        branch = ANALYTICS_BRANCHES[0]
        admitted = admission(run_id)
        identity = nvds_identity(admitted)
        policy = FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES})
        raw_events: list[dict[str, object]] = []
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-negative",
            worker_id="deepstream-negative-0",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id=branch,
            event_sink=lambda line: raw_events.append(json.loads(line)),
            policy_exchange=policy,
            analytics_endpoints=endpoints((branch,), corrupt_branch=branch),
            clock_ms=StepClock(),
        )
        spec, payload = tensor(branch)
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity, tensor_spec=spec)
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, "analytics execution"):
            bridge.execute_branch(
                str(admitted["input_frame_key"]), branch,
                tensor_payload=payload, queue_depths={"cpu": 0, "gpu": 0},
                deadline_monotonic_ns=10_000_000_000,
            )
        self.assertFalse(any(row["event_kind"] == "branch_complete" for row in raw_events))
        self.assertFalse(any(
            message["message_type"] == "terminal" for message in policy.messages
        ))

    def test_nvds_identity_cannot_relabel_software_decode_as_nvdec(self) -> None:
        run_id = "run-deepstream-identity"
        branch = ANALYTICS_BRANCHES[0]
        admitted = admission(run_id)
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-identity",
            worker_id="deepstream-identity-0",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id=branch,
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES}),
            analytics_endpoints=endpoints((branch,)),
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(json.dumps(admitted))
        relabelled = nvds_identity(admitted)
        relabelled["decoder_factory"] = "avdec_h264"
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, "nvv4l2decoder"):
            bridge.observe_decoded_frame(relabelled)

    def test_nvds_decoded_counter_is_not_relabelled_as_admission_sequence(self) -> None:
        run_id = "run-deepstream-reordered"
        branch = ANALYTICS_BRANCHES[0]
        admitted = admission(run_id)
        bridge = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-reordered",
            worker_id="deepstream-reordered-0",
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id=branch,
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES}),
            analytics_endpoints=endpoints((branch,)),
            clock_ms=StepClock(),
        )
        bridge.admit_access_unit(json.dumps(admitted))
        reordered = nvds_identity(admitted)
        reordered["nvds_frame_num"] = 7
        bridge.observe_decoded_frame(reordered)

        duplicate = admission(run_id)
        duplicate["sequence"] = 2
        duplicate["admission_id"] = f"{run_id}:0:admission:2"
        duplicate["access_unit_pts_ns"] = 91_000
        duplicate["input_frame_key"] = f"kpp-real-h264:0:{VIDEO_SHA}:0:91000"
        bridge.admit_access_unit(json.dumps(duplicate))
        duplicate_identity = nvds_identity(duplicate)
        duplicate_identity["frame_id"] = 1
        duplicate_identity["nvds_frame_num"] = 7
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, "reused"):
            bridge.observe_decoded_frame(duplicate_identity)


if __name__ == "__main__":
    unittest.main()
