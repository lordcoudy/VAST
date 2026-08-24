from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
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


def admission(run_id: str) -> dict[str, object]:
    dataset, pts = "kpp-real-h264", 90_000
    return {
        "protocol_version": 1,
        "source_process_id": "stream-0-source-coordinator",
        "sequence": 1,
        "run_id": run_id,
        "dataset_id": dataset,
        "stream_id": 0,
        "admission_id": f"{run_id}:0:admission:1",
        "input_frame_key": f"{dataset}:0:{VIDEO_SHA}:0:{pts}",
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
        "stream_id": 0,
        "frame_id": 0,
        "transport_pts_ns": value["access_unit_pts_ns"],
        "payload_sha256": value["payload_sha256"],
        "nvds_source_id": 0,
        "nvds_frame_num": 0,
        "nvds_buf_pts_ns": value["access_unit_pts_ns"],
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
                "inference_finished_monotonic_ns": 1_300_000,
                "worker_completed_monotonic_ns": 1_400_000,
                "inference_latency_ns": 200_000,
            },
            "resource": {
                "process_cpu_time_ns": 100_000,
                "rss_before_bytes": 1_000_000,
                "rss_after_bytes": 1_001_000,
                "accelerator_memory_bytes": 0 if cpu else 4_096,
                "cuda_h2d_bytes": 0 if cpu else len(payload),
                "cuda_d2h_bytes": 0 if cpu else len(output),
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
    def test_public_bridge_surface_exists(self) -> None:
        self.assertTrue(DeepStreamExecutionEndpoint)
        self.assertTrue(DeepStreamProtocolBridge)
        self.assertTrue(DeepStreamProtocolBridgeError)
        self.assertTrue(analytics_backend_identity)

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
        terminals = [row for row in raw_events if row["event_kind"] == "branch_complete"]
        self.assertEqual(len(terminals), 4)
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
        self.assertEqual(kinds.count("branch_complete"), 4)
        terminals = [
            message for message in policy.messages if message["message_type"] == "terminal"
        ]
        self.assertEqual(len(terminals), 4)
        for message in terminals:
            branch = str(message["branch"])
            expected = capability(branch, placements[branch])
            self.assertEqual(message["selected_resource"], placements[branch])
            self.assertEqual(message["detector"], expected["model_id"])
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
