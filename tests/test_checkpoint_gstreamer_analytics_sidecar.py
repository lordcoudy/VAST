from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_protocol import (  # noqa: E402
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    PROTOCOL_IDENTITY_SHA256,
    canonical_json_bytes,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
)
from analytics_execution_worker import ExecutionClient  # noqa: E402
from checkpoint_gstreamer_analytics_sidecar import (  # noqa: E402
    DockerWorkerProcessFactory,
    GStreamerAnalyticsSidecar,
    GStreamerAnalyticsProductionService,
    ProductionLifecycleEvidenceSink,
    PRODUCTION_MAX_CONNECTIONS_MINIMUM,
    PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
    PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
    PRODUCTION_RETIRED_SOCKET_NODE_COUNT,
    SidecarError,
    WorkerLaunchSpec,
    assert_publication_sidecar_service_authority_identity_v1,
    assert_publication_sidecar_service_authority_v1,
    build_parser,
    load_materialized_binding_set,
    main,
    request_publication_sidecar_guardian_stop_v1,
    validate_publication_sidecar_service_authority_v1,
    validate_publication_sidecar_service_lifecycle_v1,
)


RESOURCES = ("cpu", "gpu")
ENGINE_BY_RESOURCE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
GPU_UUID = "GPU-00000000-0000-0000-0000-000000000001"
PREPROCESSING_CONTRACT = {"fixture": True}
SHA = canonical_sha256(PREPROCESSING_CONTRACT)


def _preprocessing_authority(
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_sha = canonical_sha256(contract or PREPROCESSING_CONTRACT)
    return {
        "schema_version": 1,
        "artifact_kind": "vast_guardian_preprocessing_contract_authority_v1",
        "preprocessing_contract_content_sha256": content_sha,
        "preprocessing_contract_file_sha256": SHA,
        "materialization_receipt_identity_sha256": SHA,
        "materialization_receipt_file_sha256": SHA,
        "qualification_transaction_receipt_sha256": SHA,
        "candidate_manifest_file_sha256": hashlib.sha256(
            canonical_json_bytes(_policy_manifest()) + b"\n"
        ).hexdigest(),
        "candidate_receipt_identity_sha256": SHA,
        "model_parity_acceptance_binding_sha256": SHA,
        "policy_contract_sha256": SHA,
        "accepted_model_parity_manifest_file_sha256": SHA,
        "accepted_model_parity_assessment_file_sha256": SHA,
        "accepted_model_parity_receipt_file_sha256": SHA,
        "model_parity_acceptance_binding_file_sha256": SHA,
        "model_parity_acceptance_files_sha256": SHA,
        "model_parity_refresh_authority_sha256": SHA,
        "model_parity_transaction_index_file_sha256": SHA,
        "model_parity_transaction_sha256": SHA,
    }


def _external_runtime_expectations(
    config: dict[str, Any], binding_set: Path
) -> dict[str, Any]:
    index = json.loads((binding_set / "index.json").read_text(encoding="ascii"))
    return {
        "execution_config_identity_sha256": config["identity"]["sha256"],
        "binding_set_identity_sha256": index["identity"]["sha256"],
        "bindings_identity_sha256": index["bindings_identity_sha256"],
        "worker_image_ids": {
            resource: config["workers"][resource]["image_id"]
            for resource in RESOURCES
        },
        "policy_contract_sha256": _preprocessing_authority()[
            "policy_contract_sha256"
        ],
        "preprocessing_contract_content_sha256": SHA,
    }


def _load_execution_config() -> dict[str, Any]:
    value = yaml.safe_load(
        (ROOT / "configs" / "analytics_execution_layer.yaml").read_text(
            encoding="utf-8"
        )
    )
    value["identity"] = {
        "algorithm": "sha256",
        "sha256": canonical_sha256(value),
    }
    return value


def _probe(resource: str, config: dict[str, Any]) -> dict[str, Any]:
    cpu = resource == "cpu"
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": ENGINE_BY_RESOURCE[resource],
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "2026.1.0" if cpu else "8.6.1.6",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Fixture CPU" if cpu else GPU_UUID,
        "native_inference_api": (
            "openvino.CompiledModel.__call__"
            if cpu
            else "nvinfer1::IExecutionContext::enqueueV3"
        ),
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "worker_implementation_sha256": config["workers"][resource][
            "worker_implementation_sha256"
        ],
        "socket_seqpacket": True,
        "scm_rights": True,
        "memfd_sealing": True,
        "model_loaded": False,
        "inference_performed": False,
    }


def _binding(branch: str, resource: str, config: dict[str, Any]) -> dict[str, Any]:
    common = {
        "schema_version": 1,
        "worker_id": f"vast.{branch}.{'openvino' if resource == 'cpu' else 'tensorrt'}",
        "branch": branch,
        "model_id": f"fixture-{branch}",
        "source_path": f"/workspace/models/{branch}.onnx",
        "source_model_sha256": SHA,
        "input": {
            "name": "data",
            "dtype": "float32",
            "layout": "NCHW",
            "shape": [1, 3, 224, 224],
        },
        "preprocessing_contract_sha256": SHA,
        "output_contract_sha256": SHA,
        "outputs": [{"name": "logits", "dtype": "float32", "shape": [1, 1000]}],
        "worker_image_id": config["workers"][resource]["image_id"],
        "model_artifact_sha256": SHA,
    }
    if resource == "cpu":
        return {
            **common,
            "artifact_kind": "vast_openvino_execution_worker_binding",
            "model_path": f"/workspace/models/{branch}.xml",
            "weights_path": f"/workspace/models/{branch}.bin",
            "runtime_weights_sha256": SHA,
        }
    return {
        **common,
        "artifact_kind": "vast_tensorrt_execution_worker_binding",
        "engine_path": f"/workspace/models/{branch}.engine",
        "gpu_device_index": 0,
        "gpu_uuid": GPU_UUID,
    }


def _write_binding_set(
    root: Path,
    config: dict[str, Any],
    *,
    omit: tuple[str, str] | None = None,
) -> Path:
    root.mkdir()
    records: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    for branch in BRANCHES:
        for resource in RESOURCES:
            if omit == (branch, resource):
                continue
            engine = ENGINE_BY_RESOURCE[resource]
            filename = f"{branch}.{engine}.json"
            value = _binding(branch, resource, config)
            payload = canonical_json_bytes(value) + b"\n"
            (root / filename).write_bytes(payload)
            records.append(
                {
                    "path": filename,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            identities[filename] = canonical_sha256(value)
    core = {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_binding_set",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "execution_config_identity_sha256": config["identity"]["sha256"],
        "model_parity_manifest_identity_sha256": SHA,
        "worker_project_root": "/workspace",
        "worker_implementation_sha256": {
            ENGINE_BY_RESOURCE[resource]: config["workers"][resource][
                "worker_implementation_sha256"
            ]
            for resource in RESOURCES
        },
        "bindings_identity_sha256": canonical_sha256(identities),
        "files": records,
    }
    index = {
        **core,
        "identity": {"algorithm": "sha256", "sha256": canonical_sha256(core)},
    }
    (root / "index.json").write_bytes(canonical_json_bytes(index) + b"\n")
    return root


def _policy_manifest() -> dict[str, Any]:
    return {
        "systems": {
            "gstreamer_custom": {
                "branches": {
                    branch: {
                        resource: {
                            "implementation_id": f"gst-{branch}-{resource}-v1",
                            "terminal_detector": f"{branch}-{resource}-detector-v1",
                            "terminal_backend": (
                                "openvino-sidecar;device=CPU"
                                if resource == "cpu"
                                else "tensorrt-sidecar;device=NVIDIA_CUDA:0"
                            ),
                            "native_evidence": {
                                "emitter_id": f"gst-{branch}-{resource}-emitter-v1",
                                "emitter_sha256": SHA,
                            },
                        }
                        for resource in RESOURCES
                    }
                    for branch in BRANCHES
                }
            }
        }
    }


class _Handle:
    def __init__(self, process: subprocess.Popen[bytes], *, peer_pid_offset: int = 0) -> None:
        self._process = process
        self.pid = process.pid
        self._peer_pid_offset = peer_pid_offset
        self.terminated = False
        self.killed = False

    def expected_peer_pid(self, timeout_s: float) -> int:
        del timeout_s
        return self.pid + self._peer_pid_offset

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout_s: float) -> int:
        return self._process.wait(timeout=timeout_s)

    def terminate(self) -> None:
        self.terminated = True
        if self.poll() is None:
            self._process.terminate()

    def kill(self) -> None:
        self.killed = True
        if self.poll() is None:
            self._process.kill()


class _ProcessFactory:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        crash_at_start: tuple[str, str] | None = None,
        peer_pid_drift: tuple[str, str] | None = None,
    ) -> None:
        self.config = config
        self.crash_at_start = crash_at_start
        self.peer_pid_drift = peer_pid_drift
        self.specs: list[WorkerLaunchSpec] = []
        self.handles: dict[tuple[str, str], _Handle] = {}

    def probe(self, resource: str, worker_config: dict[str, Any]) -> dict[str, Any]:
        if worker_config != self.config["workers"][resource]:
            raise AssertionError("worker config drift")
        return _probe(resource, self.config)

    def start(self, spec: WorkerLaunchSpec) -> _Handle:
        self.specs.append(spec)
        key = (spec.branch, spec.resource)
        if key == self.crash_at_start:
            command = [sys.executable, "-c", "raise SystemExit(23)"]
        else:
            code = (
                "import socket,sys,time;"
                "s=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET);"
                "deadline=time.monotonic()+5;"
                "\nwhile True:"
                "\n try:s.connect(sys.argv[1]);break"
                "\n except OSError:"
                "\n  if time.monotonic()>=deadline:raise"
                "\n  time.sleep(.01)"
                "\ntry:s.recv(1)"
                "\nexcept OSError:pass"
                "\ns.close()"
            )
            command = [sys.executable, "-c", code, str(spec.socket_path)]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        handle = _Handle(
            process,
            peer_pid_offset=1 if key == self.peer_pid_drift else 0,
        )
        self.handles[key] = handle
        return handle

    def all_stopped(self) -> bool:
        return bool(self.handles) and all(
            handle.poll() is not None for handle in self.handles.values()
        )


class _Bridge:
    def __init__(
        self,
        *,
        process_factory: _ProcessFactory,
        fail_execute: bool = False,
        **values: Any,
    ) -> None:
        expected = {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
        if set(values["worker_connections"]) != expected:
            raise AssertionError("worker connection coverage drift")
        if set(values["worker_capabilities"]) != expected:
            raise AssertionError("worker capability coverage drift")
        if set(values["worker_bindings"]) != expected:
            raise AssertionError("worker binding coverage drift")
        if any(handle.poll() is not None for handle in process_factory.handles.values()):
            raise AssertionError("bridge constructed before every worker was live")
        self.connections = dict(values["worker_connections"])
        self.capabilities = {
            key: dict(capability)
            for key, capability in values["worker_capabilities"].items()
        }
        self.fail_execute = fail_execute

    def worker_protocol_handshake(
        self, value: dict[str, Any]
    ) -> tuple[tuple[str, str], dict[str, Any]]:
        expected = value["expected_capability_sha256"]
        matches = [
            (key, capability)
            for key, capability in self.capabilities.items()
            if canonical_sha256(capability) == expected
        ]
        if len(matches) != 1:
            raise RuntimeError("fixture capability is absent or ambiguous")
        key, capability = matches[0]
        return key, {
            "schema_version": 1,
            "message_type": "hello_ack",
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "nonce": value["nonce"],
            "capability": capability,
        }

    def execute_worker_protocol(
        self,
        request: dict[str, Any],
        payload: bytes,
        *,
        route: tuple[str, str],
    ) -> tuple[dict[str, Any], bytes]:
        if self.fail_execute:
            raise RuntimeError("injected bridge failure")
        capability = self.capabilities[route]
        output = b"\x00\x00\x00\x00"
        received = time.monotonic_ns()
        started = received + 1
        finished = started + 1
        completed = finished + 1
        return {
            "schema_version": 1,
            "message_type": "infer_response",
            "request_id": request["request_id"],
            "run_id": request["run_id"],
            "arm_id": request["arm_id"],
            "worker_id": request["worker_id"],
            "frame": request["frame"],
            "engine": request["engine"],
            "terminal": {
                "status": "completed",
                "objects": 0,
                "reason": "fixture_completed",
            },
            "output": {
                "byte_length": len(output),
                "sha256": hashlib.sha256(output).hexdigest(),
                "contract_sha256": request[
                    "expected_output_contract_sha256"
                ],
                "tensor_count": 1,
                "tensors": [
                    {
                        "name": "fixture_output",
                        "dtype": "float32",
                        "shape": [1],
                        "offset": 0,
                        "byte_length": len(output),
                    }
                ],
            },
            "provenance": {
                "worker_image_id": capability["worker_image_id"],
                "worker_implementation_sha256": capability[
                    "worker_implementation_sha256"
                ],
                "runtime_name": capability["runtime_name"],
                "runtime_version": capability["runtime_version"],
                "device_api": capability["device_api"],
                "device_id": capability["device_id"],
                "native_inference_api": capability["native_inference_api"],
                "execution_path": capability["execution_path"],
                "model_id": capability["model_id"],
                "source_model_sha256": capability["source_model_sha256"],
                "model_artifact_sha256": capability[
                    "model_artifact_sha256"
                ],
                "runtime_weights_sha256": capability[
                    "runtime_weights_sha256"
                ],
                "preprocessing_contract_sha256": capability[
                    "preprocessing_contract_sha256"
                ],
                "output_contract_sha256": capability[
                    "output_contract_sha256"
                ],
                "input_sha256": request["tensor"]["sha256"],
                "output_sha256": hashlib.sha256(output).hexdigest(),
            },
            "timing": {
                "worker_received_monotonic_ns": received,
                "inference_started_monotonic_ns": started,
                "inference_finished_monotonic_ns": finished,
                "worker_completed_monotonic_ns": completed,
                "inference_latency_ns": finished - started,
            },
            "resource": {
                "process_cpu_time_ns": 1,
                "rss_before_bytes": 1,
                "rss_after_bytes": 1,
                "accelerator_memory_bytes": 0,
                "cuda_h2d_bytes": 0,
                "cuda_d2h_bytes": 0,
                "cuda_transfer_intervals": [],
            },
        }, output

    def execute(self, request: dict[str, Any], payload: bytes) -> dict[str, Any]:
        if self.fail_execute:
            raise RuntimeError("injected bridge failure")
        return {
            "schema_version": 1,
            "message_type": "analytics_execute_response",
            "request_id": request["request_id"],
            "decision_id": request["decision"]["decision_id"],
            "decision_seq": request["decision"]["decision_seq"],
            "branch": request["frame"]["branch"],
            "selected_resource": request["decision"]["selected_resource"],
            "worker_id": f"vast.{request['frame']['branch']}.fixture",
            "raw_input_sha256": hashlib.sha256(payload).hexdigest(),
            "worker_implementation_sha256": SHA,
            "terminal_status": "completed",
        }

    def close(self) -> None:
        for connection in self.connections.values():
            try:
                connection.close()
            except OSError:
                pass
        self.connections.clear()


def _request(payload: bytes, *, request_id: str = "sidecar-request-0001") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "analytics_execute",
        "request_id": request_id,
        "run_id": "run-sidecar-0001",
        "arm_id": "arm-sidecar-0001",
        "gstreamer_worker_id": "gst-worker-0001",
        "frame": {
            "input_frame_key": "dataset:0:source:1:90000",
            "stream_id": 0,
            "frame_id": 1,
            "transport_pts_ns": 90000,
            "branch": "damage",
        },
        "decision": {
            "decision_id": "decision-sidecar-0001",
            "decision_seq": 1,
            "selected_resource": "gpu",
            "selected_implementation_id": "gst-damage-gpu-v1",
            "emitter_id": "gst-damage-gpu-emitter-v1",
            "emitter_sha256": SHA,
        },
        "deadline_monotonic_ns": time.monotonic_ns() + 60_000_000_000,
        "payload": {
            "kind": "raw_gstreamer_frame",
            "format": "BGR",
            "width": 1,
            "height": 1,
            "stride": len(payload),
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "preprocessing_contract_sha256": SHA,
        },
    }


def _worker_request(
    capability: dict[str, Any], payload: bytes
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "infer_request",
        "request_id": "worker-proxy-request-0001",
        "run_id": "worker-proxy-run-0001",
        "arm_id": "worker-proxy-arm-0001",
        "worker_id": capability["worker_id"],
        "frame": {
            "input_frame_key": "dataset:0:source:2:180000",
            "stream_id": 0,
            "frame_id": 2,
            "transport_pts_ns": 180000,
            "branch": capability["branch"],
        },
        "engine": capability["engine"],
        "deadline_monotonic_ns": time.monotonic_ns() + 60_000_000_000,
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
            "name": "data",
            "dtype": "float32",
            "layout": "NCHW",
            "shape": [1],
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


@unittest.skipUnless(
    os.name == "posix"
    and hasattr(socket, "SOCK_SEQPACKET")
    and hasattr(socket, "SO_PEERCRED")
    and hasattr(os, "memfd_create"),
    "Linux Unix credential and memfd primitives are required",
)
class GStreamerAnalyticsSidecarTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _load_execution_config()

    def _owner(
        self,
        root: Path,
        factory: _ProcessFactory,
        *,
        binding_set: Path | None = None,
        fail_execute: bool = False,
    ) -> GStreamerAnalyticsSidecar:
        runtime = root / "runtime"
        runtime.mkdir(exist_ok=True)
        evidence = root / "engineering-evidence"
        bindings = binding_set or _write_binding_set(root / "bindings", self.config)
        return GStreamerAnalyticsSidecar(
            execution_config=self.config,
            binding_set_dir=bindings,
            policy_capability_manifest=_policy_manifest(),
            preprocessing_contract=PREPROCESSING_CONTRACT,
            runtime_dir=runtime,
            front_socket=runtime / "analytics-front.sock",
            evidence_root=evidence,
            process_factory=factory,
            bridge_factory=lambda **values: _Bridge(
                process_factory=factory,
                fail_execute=fail_execute,
                **values,
            ),
            max_connections=1,
            max_requests_per_connection=1,
            startup_timeout_s=3.0,
            shutdown_timeout_s=1.0,
            monitor_interval_s=0.01,
        )

    def _production_service(
        self,
        root: Path,
        factory: _ProcessFactory,
        *,
        fail_execute: bool = False,
        max_connections: int = PRODUCTION_MAX_CONNECTIONS_MINIMUM,
        max_requests_per_connection: int = (
            PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM
        ),
        max_total_requests: int = PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
        preprocessing_contract: dict[str, Any] | None = None,
        preprocessing_authority: dict[str, Any] | None = None,
        production_runtime_expectations: dict[str, Any] | None = None,
    ) -> GStreamerAnalyticsProductionService:
        runtime = root / "runtime"
        runtime.mkdir(exist_ok=True)
        binding_set = _write_binding_set(root / "bindings", self.config)
        selected_contract = (
            PREPROCESSING_CONTRACT
            if preprocessing_contract is None
            else preprocessing_contract
        )
        selected_authority = (
            _preprocessing_authority(selected_contract)
            if preprocessing_authority is None
            else preprocessing_authority
        )
        selected_expectations = (
            _external_runtime_expectations(self.config, binding_set)
            if production_runtime_expectations is None
            else production_runtime_expectations
        )
        if production_runtime_expectations is None:
            selected_expectations["preprocessing_contract_content_sha256"] = (
                canonical_sha256(selected_contract)
            )
            selected_expectations["policy_contract_sha256"] = selected_authority[
                "policy_contract_sha256"
            ]
        return GStreamerAnalyticsProductionService(
            execution_config=self.config,
            binding_set_dir=binding_set,
            policy_capability_manifest=_policy_manifest(),
            preprocessing_contract=selected_contract,
            preprocessing_authority=selected_authority,
            production_runtime_expectations=selected_expectations,
            runtime_dir=runtime,
            front_socket=runtime / "analytics-front.sock",
            evidence_root=root / "production-evidence",
            process_factory=factory,
            bridge_factory=lambda **values: _Bridge(
                process_factory=factory,
                fail_execute=fail_execute,
                **values,
            ),
            max_connections=max_connections,
            max_requests_per_connection=max_requests_per_connection,
            max_total_requests=max_total_requests,
            startup_timeout_s=3.0,
            shutdown_timeout_s=1.0,
            monitor_interval_s=0.01,
        )

    @staticmethod
    def _wait_for(path: Path, *, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.01)
        raise AssertionError(f"timed out waiting for {path}")

    @staticmethod
    def _capture_error(callable_value: Any, errors: list[BaseException]) -> None:
        try:
            callable_value()
        except BaseException as error:
            errors.append(error)

    def test_production_readiness_parent_swap_never_redirects_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            namespace = root / "namespace"
            evidence = namespace / "evidence"
            displaced = namespace / "evidence-displaced"
            attacker = root / "attacker"
            namespace.mkdir()
            attacker.mkdir()
            sink = ProductionLifecycleEvidenceSink(evidence)
            custody = sink._directory_custody
            original_open = os.open
            swapped = False

            def race_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and dir_fd == custody.directory_fd
                    and path == "service_authority.v1.json"
                    and bool(flags & os.O_WRONLY)
                ):
                    swapped = True
                    evidence.rename(displaced)
                    evidence.symlink_to(attacker, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            try:
                with (
                    mock.patch.object(os, "open", side_effect=race_open),
                    self.assertRaisesRegex(SidecarError, "custody|directory chain|changed"),
                ):
                    sink.persist_authority({"ready": True})
                self.assertTrue(swapped)
                self.assertFalse((attacker / "service_authority.v1.json").exists())
                self.assertFalse((displaced / "service_authority.v1.json").exists())
            finally:
                sink.close()

    def test_production_lifecycle_parent_swap_preserves_attacker_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            namespace = root / "namespace"
            evidence = namespace / "evidence"
            displaced = namespace / "evidence-displaced"
            attacker = root / "attacker"
            namespace.mkdir()
            attacker.mkdir()
            canary = attacker / "service_lifecycle.v1.json"
            canary.write_bytes(b"attacker-canary\n")
            sink = ProductionLifecycleEvidenceSink(evidence)
            sink.persist_authority({"ready": True})
            custody = sink._directory_custody
            original_open = os.open
            swapped = False

            def race_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and dir_fd == custody.directory_fd
                    and path == "service_lifecycle.v1.json"
                    and bool(flags & os.O_WRONLY)
                ):
                    swapped = True
                    evidence.rename(displaced)
                    evidence.symlink_to(attacker, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            try:
                with (
                    mock.patch.object(os, "open", side_effect=race_open),
                    self.assertRaisesRegex(SidecarError, "custody|directory chain|changed"),
                ):
                    sink.persist_lifecycle({"stopped": True})
                self.assertTrue(swapped)
                self.assertEqual(canary.read_bytes(), b"attacker-canary\n")
                self.assertFalse((displaced / "service_lifecycle.v1.json").exists())
            finally:
                sink.close()

    def test_full_lifecycle_attests_exact_eight_and_persists_raw_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory)
            result: dict[str, Any] = {}
            errors: list[BaseException] = []

            def run() -> None:
                try:
                    result.update(owner.run())
                except BaseException as error:
                    errors.append(error)

            thread = threading.Thread(target=run)
            thread.start()
            self._wait_for(owner.front_socket)
            payload = b"\x01\x02\x03"
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(owner.front_socket))
            descriptor = create_sealed_memfd("sidecar-test-input", payload)
            try:
                send_packet(client, _request(payload), fds=(descriptor,))
            finally:
                close_fds((descriptor,))
            response, fds = receive_packet(client, expected_fds=0)
            close_fds(fds)
            client.close()
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result["status"], "engineering_complete_nonpublication")
            self.assertFalse(result["publication_ready"])
            self.assertFalse(result["accepted_evidence_written"])
            self.assertEqual(set(result["runtime_probes"]), {"cpu", "gpu"})
            self.assertEqual(len(result["capabilities"]), 8)
            self.assertEqual(
                {
                    (record["branch"], record["resource"])
                    for record in result["capabilities"]
                },
                {(branch, resource) for branch in BRANCHES for resource in RESOURCES},
            )
            self.assertEqual(
                result["binding_index"]["artifact_kind"],
                "vast_analytics_execution_worker_binding_set",
            )
            self.assertEqual(len(factory.specs), 8)
            self.assertEqual(
                {(spec.branch, spec.resource) for spec in factory.specs},
                {(branch, resource) for branch in BRANCHES for resource in RESOURCES},
            )
            for worker in result["workers"]:
                peer = worker["peer_identity"]
                self.assertEqual(
                    worker["peer_identity_sha256"], peer["identity_sha256"]
                )
                self.assertEqual(peer["peer_identity_mode"], "native-visible")
                self.assertTrue(peer["peer_pid_visible_in_controller_namespace"])
                self.assertTrue(peer["peer_identity_by_pid_attested"])
                self.assertTrue(
                    peer["protocol_nonce_capability_handshake_performed"]
                )
                self.assertTrue(
                    peer["global_eight_worker_handshake_barrier_attested"]
                )
            self.assertEqual(response["request_id"], "sidecar-request-0001")
            self.assertTrue(factory.all_stopped())
            self.assertFalse(owner.front_socket.exists())
            self.assertEqual(list((root / "runtime").iterdir()), [])

            bundle = root / "engineering-evidence" / "calls" / "sidecar-request-0001"
            self.assertEqual((bundle / "input.frame.bin").read_bytes(), payload)
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["artifact_kind"],
                "vast_gstreamer_analytics_sidecar_engineering_call",
            )
            self.assertFalse(manifest["publication_ready"])
            self.assertFalse(manifest["accepted_evidence_written"])
            self.assertEqual(
                json.loads((bundle / "response.json").read_text(encoding="utf-8")),
                response,
            )

    def test_incomplete_materialized_binding_set_fails_before_process_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindings = _write_binding_set(
                root / "bindings",
                self.config,
                omit=("foreign_object", "gpu"),
            )
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory, binding_set=bindings)
            with self.assertRaisesRegex(SidecarError, "exact 8|coverage"):
                owner.run()
            self.assertEqual(factory.specs, [])
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_binding_index_digest_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindings = _write_binding_set(root / "bindings", self.config)
            target = bindings / f"damage.{ENGINE_TENSORRT_CUDA}.json"
            target.write_bytes(target.read_bytes() + b" ")
            with self.assertRaisesRegex(SidecarError, "SHA-256|bytes|canonical"):
                load_materialized_binding_set(
                    bindings,
                    execution_config=self.config,
                    runtime_probes={
                        resource: _probe(resource, self.config)
                        for resource in RESOURCES
                    },
                )

    def test_peer_pid_drift_fails_closed_and_cleans_every_owned_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(
                self.config,
                peer_pid_drift=("plate_number", "cpu"),
            )
            owner = self._owner(root, factory)
            with self.assertRaisesRegex(SidecarError, "peer PID"):
                owner.run()
            self.assertTrue(factory.all_stopped())
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_startup_worker_crash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(
                self.config,
                crash_at_start=("vehicle_type", "gpu"),
            )
            owner = self._owner(root, factory)
            with self.assertRaisesRegex(SidecarError, "exited during startup|startup"):
                owner.run()
            self.assertTrue(factory.all_stopped())
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_runtime_worker_crash_interrupts_front_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory)
            errors: list[BaseException] = []
            thread = threading.Thread(
                target=lambda: self._capture_error(owner.run, errors)
            )
            thread.start()
            self._wait_for(owner.front_socket)
            factory.handles[("damage", "gpu")].terminate()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertRegex(str(errors[0]), "worker.*exited|exited.*worker")
            self.assertTrue(factory.all_stopped())
            self.assertFalse(owner.front_socket.exists())
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_worker_crash_interrupts_idle_client_and_leaves_no_service_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory)
            errors: list[BaseException] = []
            owner_thread = threading.Thread(
                target=lambda: self._capture_error(owner.run, errors)
            )
            owner_thread.start()
            self._wait_for(owner.front_socket)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(owner.front_socket))
            deadline = time.monotonic() + 2
            while (
                not any(
                    thread.name.startswith("vast-gst-analytics-front-")
                    for thread in threading.enumerate()
                )
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            factory.handles[("foreign_object", "cpu")].terminate()
            owner_thread.join(timeout=10)
            leaked = [
                thread
                for thread in threading.enumerate()
                if thread.name.startswith("vast-gst-analytics-front-")
                and thread.is_alive()
            ]
            client.close()
            for thread in leaked:
                thread.join(timeout=2)
            self.assertFalse(owner_thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertEqual(leaked, [])
            self.assertTrue(factory.all_stopped())
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_bridge_failure_is_fatal_and_raw_socket_nodes_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory, fail_execute=True)
            errors: list[BaseException] = []
            thread = threading.Thread(
                target=lambda: self._capture_error(owner.run, errors)
            )
            thread.start()
            self._wait_for(owner.front_socket)
            payload = b"abc"
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(owner.front_socket))
            descriptor = create_sealed_memfd("sidecar-failure-input", payload)
            try:
                send_packet(client, _request(payload), fds=(descriptor,))
            finally:
                close_fds((descriptor,))
            client.close()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertRegex(str(errors[0]), "bridge failure")
            self.assertTrue(factory.all_stopped())
            self.assertEqual(list((root / "runtime").iterdir()), [])
            failed_bundle = (
                root
                / "engineering-evidence"
                / "calls"
                / "sidecar-request-0001"
            )
            self.assertEqual(
                (failed_bundle / "input.frame.bin").read_bytes(),
                payload,
            )
            failed_manifest = json.loads(
                (failed_bundle / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failed_manifest["outcome"], "failed")
            self.assertFalse(failed_manifest["publication_ready"])
            self.assertFalse(failed_manifest["accepted_evidence_written"])

    def test_front_collision_is_preserved_and_workers_are_drained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            collision = runtime / "occupied.sock"
            collision.write_text("CANARY\n", encoding="utf-8")
            bindings = _write_binding_set(root / "bindings", self.config)
            factory = _ProcessFactory(self.config)
            owner = GStreamerAnalyticsSidecar(
                execution_config=self.config,
                binding_set_dir=bindings,
                policy_capability_manifest=_policy_manifest(),
                preprocessing_contract={"fixture": True},
                runtime_dir=runtime,
                front_socket=collision,
                evidence_root=root / "engineering-evidence",
                process_factory=factory,
                bridge_factory=lambda **values: _Bridge(
                    process_factory=factory, **values
                ),
                max_connections=1,
                max_requests_per_connection=1,
                startup_timeout_s=3.0,
                shutdown_timeout_s=1.0,
                monitor_interval_s=0.01,
            )
            with self.assertRaisesRegex(Exception, "already exists"):
                owner.run()
            self.assertEqual(collision.read_text(encoding="utf-8"), "CANARY\n")
            self.assertTrue(factory.all_stopped())
            self.assertEqual(list(runtime.iterdir()), [collision])

    def test_atomic_front_publish_collision_preserves_canary_and_hidden_node_absent(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            collision = root / "front.sock"
            collision.write_text("CANARY\n", encoding="utf-8")
            with self.assertRaisesRegex(SidecarError, "already exists"):
                sidecar_module._open_owned_listener(
                    collision,
                    backlog=1,
                    atomic_publish=True,
                )
            self.assertEqual(collision.read_text(encoding="utf-8"), "CANARY\n")
            self.assertEqual(list(root.iterdir()), [collision])

    def test_atomic_front_publish_uses_direct_bind_without_link_cleanup(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "front.sock"
            with mock.patch.object(
                sidecar_module.os,
                "link",
                side_effect=AssertionError("link cleanup is forbidden"),
            ):
                owned = sidecar_module._open_owned_listener(
                    target,
                    backlog=1,
                    atomic_publish=True,
                )
            try:
                self.assertTrue(stat.S_ISSOCK(target.lstat().st_mode))
                self.assertEqual(owned.identity, sidecar_module._stat_identity(target))
            finally:
                if owned.listener is not None:
                    owned.listener.close()
                target.unlink()

    def test_atomic_front_publish_post_bind_failure_never_unlinks_node(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "front.sock"
            original_identity = sidecar_module._stat_identity
            def fail_after_bind(path: Path) -> Any:
                self.assertEqual(path, target)
                raise SidecarError("injected post-bind failure")

            with (
                mock.patch.object(
                    sidecar_module,
                    "_stat_identity",
                    side_effect=fail_after_bind,
                ),
                self.assertRaisesRegex(SidecarError, "post-bind failure"),
            ):
                sidecar_module._open_owned_listener(
                    target,
                    backlog=1,
                    atomic_publish=True,
                )
            self.assertTrue(stat.S_ISSOCK(target.lstat().st_mode))
            self.assertEqual(original_identity(target)[2], stat.S_IFSOCK)
            target.unlink()

    def test_owned_socket_retirement_never_deletes_raced_node(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "front.sock"
            displaced = root / "owned-displaced.sock"
            owned = sidecar_module._open_owned_listener(
                target,
                backlog=1,
                atomic_publish=True,
            )
            custody = sidecar_module.DirectoryFdCustodyV1.open_existing(
                root,
                label="socket race fixture",
            )
            retirement = sidecar_module.DirectoryFdCustodyV1.open_existing(
                root,
                label="socket retirement race parent",
            )
            retirement.mkdir_child_exclusive(
                ".retired-socket-race",
                mode=0o700,
            )
            attacker = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            original_rename = sidecar_module._renameat2_noreplace_socket_node
            raced = False

            def race_before_quarantine(
                source_directory_fd: int,
                source_name: str,
                target_directory_fd: int,
                target_name: str,
            ) -> None:
                nonlocal raced
                if not raced and source_name == target.name:
                    raced = True
                    target.rename(displaced)
                    attacker.bind(str(target))
                return original_rename(
                    source_directory_fd,
                    source_name,
                    target_directory_fd,
                    target_name,
                )

            try:
                with (
                    mock.patch.object(
                        sidecar_module,
                        "_renameat2_noreplace_socket_node",
                        side_effect=race_before_quarantine,
                    ),
                    self.assertRaisesRegex(SidecarError, "identity changed"),
                ):
                    sidecar_module._close_owned_socket(
                        owned,
                        directory_custody=custody,
                        retirement_custody=retirement,
                        lifecycle_id="a" * 32,
                    )
                self.assertTrue(raced)
                self.assertFalse(target.exists())
                self.assertTrue(displaced.exists())
                self.assertTrue(stat.S_ISSOCK(displaced.lstat().st_mode))
                retired_nodes = list(retirement.path.iterdir())
                self.assertEqual(len(retired_nodes), 1)
                self.assertTrue(stat.S_ISSOCK(retired_nodes[0].lstat().st_mode))
            finally:
                custody.close()
                retirement.close()
                attacker.close()
                for path in (target, displaced):
                    if os.path.lexists(path):
                        path.unlink()

    def test_retired_socket_post_stat_swap_is_nondestructive_and_fails_cold(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            target = runtime / "front.sock"
            owned = sidecar_module._open_owned_listener(
                target,
                backlog=1,
                atomic_publish=True,
            )
            runtime_custody = sidecar_module.DirectoryFdCustodyV1.open_existing(
                runtime,
                label="post-stat runtime fixture",
            )
            retirement = sidecar_module.DirectoryFdCustodyV1.open_existing(
                root,
                label="post-stat retirement parent fixture",
            )
            lifecycle_id = "b" * 32
            retirement.mkdir_child_exclusive(
                f".vast-gst-analytics-retired-{lifecycle_id}",
                mode=0o700,
            )
            attacker = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            displaced = retirement.path / "owned-displaced.sock"
            original_stat = sidecar_module.os.stat
            swapped = False

            def swap_after_retired_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
                nonlocal swapped
                metadata = original_stat(path, *args, **kwargs)
                if (
                    not swapped
                    and kwargs.get("dir_fd") == retirement.directory_fd
                    and str(path).endswith(".sock")
                ):
                    swapped = True
                    retired_path = retirement.path / str(path)
                    retired_path.rename(displaced)
                    attacker_source = root / "attacker.sock"
                    attacker.bind(str(attacker_source))
                    attacker_source.rename(retired_path)
                return metadata

            try:
                with mock.patch.object(
                    sidecar_module.os,
                    "stat",
                    side_effect=swap_after_retired_stat,
                ):
                    record = sidecar_module._close_owned_socket(
                        owned,
                        directory_custody=runtime_custody,
                        retirement_custody=retirement,
                        lifecycle_id=lifecycle_id,
                    )
                self.assertTrue(swapped)
                self.assertIsNotNone(record)
                with self.assertRaisesRegex(
                    SidecarError,
                    "retirement directory|physical identity",
                ):
                    sidecar_module._validate_retired_socket_records_v1(
                        [record],
                        expected_lifecycle_id=lifecycle_id,
                        expected_active_names={target.name},
                        verify_physical=True,
                    )
                self.assertTrue(stat.S_ISSOCK(displaced.lstat().st_mode))
                current = retirement.path / str(record["retired_name"])
                self.assertTrue(stat.S_ISSOCK(current.lstat().st_mode))
            finally:
                runtime_custody.close()
                retirement.close()
                attacker.close()

    def test_runtime_symlink_is_rejected_without_touching_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_runtime = root / "real-runtime"
            real_runtime.mkdir()
            canary = real_runtime / "KEEP"
            canary.write_text("keep\n", encoding="utf-8")
            alias = root / "runtime"
            alias.symlink_to(real_runtime, target_is_directory=True)
            bindings = _write_binding_set(root / "bindings", self.config)
            factory = _ProcessFactory(self.config)
            with self.assertRaisesRegex(SidecarError, "symlink|alias|reparse"):
                GStreamerAnalyticsSidecar(
                    execution_config=self.config,
                    binding_set_dir=bindings,
                    policy_capability_manifest=_policy_manifest(),
                    preprocessing_contract={"fixture": True},
                    runtime_dir=alias,
                    front_socket=alias / "front.sock",
                    evidence_root=root / "engineering-evidence",
                    process_factory=factory,
                    bridge_factory=lambda **values: _Bridge(
                        process_factory=factory, **values
                    ),
                    max_connections=1,
                    max_requests_per_connection=1,
                )
            self.assertEqual(canary.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual(factory.specs, [])

    def test_running_guardian_fails_closed_if_runtime_directory_is_rebound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            runtime = service.runtime_dir
            displaced = root / "runtime-displaced"
            runtime.rename(displaced)
            runtime.mkdir()
            try:
                with self.assertRaisesRegex(
                    SidecarError, "runtime.*(custody|directory)|directory.*changed"
                ):
                    service.assert_live(authority)
                lifecycle = service.stop()
                self.assertEqual(
                    lifecycle["status"], "failed_stop_nonpublication"
                )
                self.assertTrue(
                    any(
                        "runtime_directory" in item
                        for item in lifecycle["cleanup_errors"]
                    )
                )
                self.assertIsNone(service._runtime_directory_custody)
                retained = {item.name for item in displaced.iterdir()}
                self.assertEqual(
                    retained,
                    {
                        "analytics-front.sock",
                        "production-guardian-control.sock",
                    },
                )
                self.assertTrue(
                    all(
                        stat.S_ISSOCK(item.lstat().st_mode)
                        for item in displaced.iterdir()
                    )
                )
            finally:
                for entry in displaced.iterdir():
                    entry.unlink()

    def test_production_service_has_stable_authority_clean_eof_and_rolling_lifecycle(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)

            authority = service.start()
            checked = validate_publication_sidecar_service_authority_v1(authority)
            self.assertEqual(checked, authority)
            self.assertEqual(
                authority["preprocessing_contract_authority"],
                _preprocessing_authority(),
            )
            self.assertEqual(
                authority["capacity"]["max_total_requests"],
                PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
            )
            self.assertEqual(
                authority["capacity"]["worker_request_upper_bound"],
                PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
            )
            self.assertEqual(
                {spec.max_requests for spec in factory.specs},
                {PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM},
            )
            self.assertEqual(len(authority["peer_identities"]), 8)
            self.assertTrue(
                all(
                    row["peer_identity"][
                        "protocol_nonce_capability_handshake_performed"
                    ]
                    is True
                    and row["peer_identity"][
                        "global_eight_worker_handshake_barrier_attested"
                    ]
                    is True
                    for row in authority["peer_identities"]
                )
            )
            readiness = root / "production-evidence" / "service_authority.v1.json"
            self.assertEqual(
                json.loads(readiness.read_text(encoding="ascii")),
                authority,
            )
            self.assertFalse((root / "production-evidence" / "calls").exists())

            pin = dict(authority["front_socket"])
            self.assertEqual(pin["device"], service.front_socket.lstat().st_dev)
            self.assertEqual(pin["inode"], service.front_socket.lstat().st_ino)
            expected_images = {
                resource: self.config["workers"][resource]["image_id"]
                for resource in RESOURCES
            }
            self.assertEqual(
                assert_publication_sidecar_service_authority_v1(
                    authority,
                    expected_front_socket=service.front_socket,
                    expected_execution_config_identity_sha256=(
                        self.config["identity"]["sha256"]
                    ),
                    expected_binding_set_identity_sha256=authority[
                        "binding_set_identity_sha256"
                    ],
                    expected_worker_image_ids=expected_images,
                    expected_preprocessing_contract_authority=authority[
                        "preprocessing_contract_authority"
                    ],
                    expected_service_identity_sha256=authority[
                        "service_identity_sha256"
                    ],
                    expected_policy_contract_sha256=authority[
                        "preprocessing_contract_authority"
                    ]["policy_contract_sha256"],
                ),
                authority,
            )

            # A topology probe may connect and close before sending a request.
            empty_client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            empty_client.connect(str(service.front_socket))
            empty_client.close()

            payload = b"\x01\x02\x03"
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(service.front_socket))
            descriptor = create_sealed_memfd("production-sidecar-input", payload)
            try:
                send_packet(client, _request(payload), fds=(descriptor,))
            finally:
                close_fds((descriptor,))
            response, descriptors = receive_packet(client, expected_fds=0)
            close_fds(descriptors)
            self.assertEqual(response["request_id"], "sidecar-request-0001")
            client.close()

            # Publication adapters speak the native worker protocol on the same
            # stable guardian front socket.  The hello has zero FDs; inference
            # carries one sealed input memfd and receives one sealed output.
            self.assertIsInstance(service._bridge, _Bridge)
            capability = service._bridge.capabilities[("damage", "cpu")]
            worker_client_socket = socket.socket(
                socket.AF_UNIX, socket.SOCK_SEQPACKET
            )
            worker_client_socket.connect(str(service.front_socket))
            worker_client = ExecutionClient(
                worker_client_socket,
                expected_capability=capability,
            )
            self.assertEqual(worker_client.handshake(), capability)
            worker_payload = b"\x00\x00\x00\x00"
            worker_response, worker_output = worker_client.infer(
                _worker_request(capability, worker_payload), worker_payload
            )
            self.assertEqual(
                worker_response["request_id"], "worker-proxy-request-0001"
            )
            self.assertEqual(worker_output, b"\x00\x00\x00\x00")
            worker_client_socket.close()

            live = service.assert_live(authority)
            self.assertEqual(live["front_socket"], pin)
            self.assertEqual(service.front_socket.lstat().st_ino, pin["inode"])
            request_publication_sidecar_guardian_stop_v1(authority)
            lifecycle = service.stop()

            self.assertFalse(service.front_socket.exists())
            self.assertEqual(lifecycle["status"], "clean_stop_nonpublication")
            self.assertEqual(
                len(lifecycle["retired_socket_nodes"]),
                PRODUCTION_RETIRED_SOCKET_NODE_COUNT,
            )
            self.assertEqual(
                {
                    item["active_name"]
                    for item in lifecycle["retired_socket_nodes"]
                },
                {
                    *{
                        f"worker-{branch}-{resource}.sock"
                        for branch in BRANCHES
                        for resource in RESOURCES
                    },
                    Path(authority["front_socket"]["path"]).name,
                    Path(authority["control_socket"]["path"]).name,
                },
            )
            self.assertEqual(lifecycle["service_authority_sha256"], authority[
                "service_authority_sha256"
            ])
            self.assertEqual(lifecycle["counters"]["requests_completed"], 2)
            self.assertEqual(lifecycle["counters"]["requests_failed"], 0)
            self.assertGreaterEqual(
                lifecycle["counters"]["connections_clean_eof"], 1
            )
            self.assertEqual(service._call_manifests, [])
            lifecycle_path = (
                root / "production-evidence" / "service_lifecycle.v1.json"
            )
            self.assertEqual(
                json.loads(lifecycle_path.read_text(encoding="ascii")),
                lifecycle,
            )
            self.assertEqual(
                assert_publication_sidecar_service_authority_identity_v1(
                    authority,
                    expected_front_socket=service.front_socket,
                    expected_execution_config_identity_sha256=(
                        self.config["identity"]["sha256"]
                    ),
                    expected_binding_set_identity_sha256=authority[
                        "binding_set_identity_sha256"
                    ],
                    expected_worker_image_ids=expected_images,
                    expected_preprocessing_contract_authority=authority[
                        "preprocessing_contract_authority"
                    ],
                    expected_service_identity_sha256=authority[
                        "service_identity_sha256"
                    ],
                    expected_policy_contract_sha256=authority[
                        "preprocessing_contract_authority"
                    ]["policy_contract_sha256"],
                ),
                authority,
            )

    def test_retired_socket_validator_binds_exact_count_and_sibling_path(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            request_publication_sidecar_guardian_stop_v1(authority)
            lifecycle = service.stop()
            records = lifecycle["retired_socket_nodes"]
            self.assertEqual(
                len(records), PRODUCTION_RETIRED_SOCKET_NODE_COUNT
            )

            reduced = copy.deepcopy(records[:-1])
            with self.assertRaisesRegex(SidecarError, "cardinality"):
                sidecar_module._validate_retired_socket_records_v1(
                    reduced,
                    expected_lifecycle_id=authority["lifecycle_id"],
                    expected_active_names={
                        item["active_name"] for item in reduced
                    },
                    expected_record_count=(
                        PRODUCTION_RETIRED_SOCKET_NODE_COUNT
                    ),
                    expected_retirement_directory=(
                        service._socket_retirement_directory
                    ),
                    verify_physical=False,
                )

            original_retirement = service._socket_retirement_directory
            relocated_retirement = root / ".relocated-retired-sockets"
            original_retirement.rename(relocated_retirement)
            tampered = copy.deepcopy(lifecycle)
            for record in tampered["retired_socket_nodes"]:
                record["retirement_directory"]["path"] = str(
                    relocated_retirement
                )
                record_core = {
                    key: value
                    for key, value in record.items()
                    if key != "identity"
                }
                record["identity"] = {
                    "algorithm": "sha256",
                    "sha256": canonical_sha256(record_core),
                }
            lifecycle_core = {
                key: value
                for key, value in tampered.items()
                if key != "identity"
            }
            tampered["identity"] = {
                "algorithm": "sha256",
                "sha256": canonical_sha256(lifecycle_core),
            }
            with self.assertRaisesRegex(SidecarError, "path binding"):
                validate_publication_sidecar_service_lifecycle_v1(
                    tampered,
                    expected_authority=authority,
                )

    def test_cached_stop_cold_revalidates_retired_socket_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            request_publication_sidecar_guardian_stop_v1(authority)
            lifecycle = service.stop()
            record = lifecycle["retired_socket_nodes"][0]
            retired_path = (
                Path(record["retirement_directory"]["path"])
                / record["retired_name"]
            )
            displaced = root / "displaced-retired-socket.sock"
            retired_path.rename(displaced)

            with self.assertRaisesRegex(
                SidecarError,
                "retirement directory|physical identity|cold reopen",
            ):
                service.stop()

    def test_strict_authority_assert_rejects_distinct_valid_expected_identities(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            expected_images = {
                resource: self.config["workers"][resource]["image_id"]
                for resource in RESOURCES
            }
            base = {
                "expected_front_socket": service.front_socket,
                "expected_execution_config_identity_sha256": self.config[
                    "identity"
                ]["sha256"],
                "expected_binding_set_identity_sha256": authority[
                    "binding_set_identity_sha256"
                ],
                "expected_worker_image_ids": expected_images,
                "expected_preprocessing_contract_authority": authority[
                    "preprocessing_contract_authority"
                ],
                "expected_service_identity_sha256": authority[
                    "service_identity_sha256"
                ],
                "expected_policy_contract_sha256": authority[
                    "preprocessing_contract_authority"
                ]["policy_contract_sha256"],
            }
            try:
                distinct_preprocessing = copy.deepcopy(
                    authority["preprocessing_contract_authority"]
                )
                distinct_preprocessing[
                    "materialization_receipt_identity_sha256"
                ] = "f" * 64
                cases = (
                    {
                        **base,
                        "expected_preprocessing_contract_authority": (
                            distinct_preprocessing
                        ),
                    },
                    {
                        **base,
                        "expected_service_identity_sha256": "e" * 64,
                    },
                    {
                        **base,
                        "expected_policy_contract_sha256": "d" * 64,
                    },
                )
                for expected in cases:
                    with self.subTest(expected=expected), self.assertRaises(
                        SidecarError
                    ):
                        assert_publication_sidecar_service_authority_v1(
                            authority,
                            **expected,
                        )
            finally:
                service.stop()

    def test_production_preprocessing_contract_checks_all_bindings_before_worker_start(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            drifted_contract = {"fixture": False}
            service = self._production_service(
                root,
                factory,
                preprocessing_contract=drifted_contract,
                preprocessing_authority=_preprocessing_authority(drifted_contract),
            )
            with self.assertRaisesRegex(
                SidecarError,
                "preprocessing.*(binding|capability|eight|8)",
            ):
                service.start()
            self.assertEqual(factory.specs, [])
            self.assertEqual(list((root / "runtime").iterdir()), [])

    def test_production_rejects_external_runtime_expectation_drift_before_worker_start(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for field in (
                "execution_config_identity_sha256",
                "binding_set_identity_sha256",
                "bindings_identity_sha256",
                "worker_image_ids",
                "policy_contract_sha256",
            ):
                case_root = root / field
                case_root.mkdir()
                factory = _ProcessFactory(self.config)
                binding_set = _write_binding_set(
                    case_root / "expected-bindings", self.config
                )
                expectations = _external_runtime_expectations(
                    self.config, binding_set
                )
                if field == "worker_image_ids":
                    expectations[field]["gpu"] = "sha256:" + "f" * 64
                else:
                    expectations[field] = "f" * 64
                with self.subTest(field=field), self.assertRaisesRegex(
                    SidecarError,
                    "external|expected|runtime|policy|binding|worker",
                ):
                    service = self._production_service(
                        case_root,
                        factory,
                        production_runtime_expectations=expectations,
                    )
                    service.start()
                self.assertEqual(factory.specs, [])

    def test_production_preprocessing_receipt_binds_runtime_candidate_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            drifted_authority = _preprocessing_authority()
            drifted_authority["candidate_manifest_file_sha256"] = "0" * 64
            with self.assertRaisesRegex(
                SidecarError,
                "preprocessing.*candidate manifest",
            ):
                self._production_service(
                    root,
                    factory,
                    preprocessing_authority=drifted_authority,
                )
            self.assertEqual(factory.specs, [])

    def test_production_capacity_is_contract_derived_and_not_one_million(self) -> None:
        self.assertEqual(PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM, 4_320_000)
        self.assertEqual(PRODUCTION_MAX_CONNECTIONS_MINIMUM, 202_560)
        self.assertEqual(PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM, 29_168_640_000)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            for field, values in (
                (
                    "connections",
                    {
                        "max_connections": PRODUCTION_MAX_CONNECTIONS_MINIMUM - 1,
                    },
                ),
                (
                    "per_connection",
                    {
                        "max_requests_per_connection": (
                            PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM - 1
                        ),
                    },
                ),
                (
                    "total",
                    {
                        "max_total_requests": (
                            PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM - 1
                        ),
                    },
                ),
            ):
                case_root = root / field
                case_root.mkdir()
                with self.subTest(field=field), self.assertRaises(SidecarError):
                    self._production_service(case_root, factory, **values)

    def test_production_per_connection_bound_exhaustion_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            # Exercise the terminal branch without issuing 4.32 million fixture calls.
            service.max_requests_per_connection = 1
            payload = b"\x01\x02\x03"
            client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            client.connect(str(service.front_socket))
            descriptor = create_sealed_memfd("production-bound-input", payload)
            try:
                send_packet(client, _request(payload), fds=(descriptor,))
            finally:
                close_fds((descriptor,))
            response, response_fds = receive_packet(client, expected_fds=0)
            close_fds(response_fds)
            self.assertEqual(response["request_id"], "sidecar-request-0001")
            client.close()

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    service.assert_live(authority)
                except SidecarError:
                    break
                time.sleep(0.01)
            else:
                self.fail("production request bound exhaustion stayed live")
            lifecycle = service.stop()
            self.assertEqual(lifecycle["status"], "failed_stop_nonpublication")
            self.assertEqual(lifecycle["counters"]["requests_completed"], 1)
            self.assertEqual(lifecycle["counters"]["connections_failed"], 1)

    def test_production_authority_rejects_hash_inode_and_owner_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            try:
                for path, replacement in (
                    (("front_socket", "inode"), authority["front_socket"]["inode"] + 1),
                    (("owner_process", "pid"), os.getpid() + 100_000),
                    (("service_authority_sha256",), "0" * 64),
                ):
                    tampered = copy.deepcopy(authority)
                    target = tampered
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = replacement
                    with self.subTest(path=path), self.assertRaises(SidecarError):
                        service.assert_live(tampered)
            finally:
                service.stop()

    def test_production_start_is_one_shot_and_does_not_replace_front_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            inode = authority["front_socket"]["inode"]
            try:
                with self.assertRaises(SidecarError):
                    service.start()
                self.assertEqual(service.front_socket.lstat().st_ino, inode)
            finally:
                service.stop()

    def test_guardian_authenticated_stop_unblocks_foreground_wait(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            waiter_errors: list[BaseException] = []
            waiter = threading.Thread(
                target=lambda: self._capture_error(
                    service.wait_for_guardian_stop,
                    waiter_errors,
                )
            )
            waiter.start()

            acknowledgement = request_publication_sidecar_guardian_stop_v1(
                authority
            )
            waiter.join(timeout=5)
            self.assertFalse(waiter.is_alive())
            self.assertEqual(waiter_errors, [])
            self.assertEqual(
                acknowledgement["service_authority_sha256"],
                authority["service_authority_sha256"],
            )
            lifecycle = service.stop()
            attestation = lifecycle["guardian_stop_attestation"]
            self.assertEqual(
                attestation["artifact_kind"],
                "vast_gstreamer_analytics_guardian_stop_attestation_v1",
            )
            self.assertEqual(
                attestation["lifecycle_id"], authority["lifecycle_id"]
            )
            self.assertEqual(
                attestation["service_authority_sha256"],
                authority["service_authority_sha256"],
            )
            self.assertEqual(attestation["nonce"], acknowledgement["nonce"])
            self.assertEqual(
                attestation["canonical_command_sha256"],
                acknowledgement["canonical_command_sha256"],
            )
            self.assertEqual(
                attestation["canonical_command_sha256"],
                canonical_sha256(
                    {
                        "schema_version": 1,
                        "message_type": "production_guardian_stop",
                        "lifecycle_id": authority["lifecycle_id"],
                        "service_authority_sha256": authority[
                            "service_authority_sha256"
                        ],
                        "nonce": acknowledgement["nonce"],
                    }
                ),
            )
            self.assertEqual(attestation["peer_process"]["pid"], os.getpid())
            self.assertEqual(attestation["peer_process"]["uid"], os.getuid())
            self.assertEqual(attestation["peer_process"]["gid"], os.getgid())
            self.assertGreater(
                attestation["peer_process"]["proc_stat_starttime_ticks"], 0
            )
            self.assertGreaterEqual(
                attestation["accepted_monotonic_ns"],
                authority["started_monotonic_ns"],
            )
            self.assertLessEqual(
                attestation["accepted_monotonic_ns"],
                lifecycle["finished_monotonic_ns"],
            )
            attestation_core = {
                key: value
                for key, value in attestation.items()
                if key != "identity"
            }
            self.assertEqual(
                attestation["identity"],
                {
                    "algorithm": "sha256",
                    "sha256": canonical_sha256(attestation_core),
                },
            )
            self.assertEqual(
                validate_publication_sidecar_service_lifecycle_v1(
                    lifecycle,
                    expected_authority=authority,
                ),
                lifecycle,
            )

    def test_guardian_stores_stop_attestation_before_acknowledgement(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            original_send = sidecar_module.send_packet
            attestation_present_at_ack: list[bool] = []

            def observe_send(*args: Any, **kwargs: Any) -> Any:
                message = args[1] if len(args) > 1 else kwargs.get("message")
                if (
                    isinstance(message, dict)
                    and message.get("message_type")
                    == "production_guardian_stop_accepted"
                ):
                    with service._guardian_stop_attestation_lock:
                        attestation_present_at_ack.append(
                            service._guardian_stop_attestation is not None
                        )
                return original_send(*args, **kwargs)

            with mock.patch.object(
                sidecar_module,
                "send_packet",
                side_effect=observe_send,
            ):
                request_publication_sidecar_guardian_stop_v1(authority)
            lifecycle = service.stop()
            self.assertEqual(attestation_present_at_ack, [True])
            self.assertEqual(lifecycle["status"], "clean_stop_nonpublication")

    def test_guardian_stop_attestation_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            request_publication_sidecar_guardian_stop_v1(authority)
            lifecycle = service.stop()

            def rehash_attestation(document: dict[str, Any]) -> None:
                attestation = document["guardian_stop_attestation"]
                attestation_core = {
                    key: value
                    for key, value in attestation.items()
                    if key != "identity"
                }
                attestation["identity"] = {
                    "algorithm": "sha256",
                    "sha256": canonical_sha256(attestation_core),
                }

            def rehash_lifecycle(document: dict[str, Any]) -> None:
                core = {
                    key: value
                    for key, value in document.items()
                    if key != "identity"
                }
                document["identity"] = {
                    "algorithm": "sha256",
                    "sha256": canonical_sha256(core),
                }

            cases: tuple[tuple[str, Any], ...] = (
                (
                    "stale_self_hash",
                    lambda document: document["guardian_stop_attestation"].__setitem__(
                        "nonce", "f" * 64
                    ),
                ),
                (
                    "canonical_command",
                    lambda document: (
                        document["guardian_stop_attestation"].__setitem__(
                            "canonical_command_sha256", "0" * 64
                        ),
                        rehash_attestation(document),
                    ),
                ),
                (
                    "authority_binding",
                    lambda document: (
                        document["guardian_stop_attestation"].__setitem__(
                            "service_authority_sha256", "0" * 64
                        ),
                        rehash_attestation(document),
                    ),
                ),
                (
                    "peer_identity",
                    lambda document: (
                        document["guardian_stop_attestation"][
                            "peer_process"
                        ].__setitem__("uid", authority["owner_process"]["uid"] + 1),
                        rehash_attestation(document),
                    ),
                ),
                (
                    "accepted_time",
                    lambda document: (
                        document["guardian_stop_attestation"].__setitem__(
                            "accepted_monotonic_ns",
                            document["finished_monotonic_ns"] + 1,
                        ),
                        rehash_attestation(document),
                    ),
                ),
            )
            for label, mutate in cases:
                tampered = copy.deepcopy(lifecycle)
                mutate(tampered)
                rehash_lifecycle(tampered)
                with self.subTest(label=label), self.assertRaises(SidecarError):
                    validate_publication_sidecar_service_lifecycle_v1(
                        tampered,
                        expected_authority=authority,
                    )

    def test_signal_or_direct_stop_is_failed_and_non_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for mode, directory_name in (
                ("direct", "d"),
                ("signal_event", "s"),
            ):
                case_root = root / directory_name
                case_root.mkdir()
                factory = _ProcessFactory(self.config)
                service = self._production_service(case_root, factory)
                authority = service.start()
                if mode == "signal_event":
                    service._guardian_stop_requested.set()
                    service.wait_for_guardian_stop()
                lifecycle = service.stop()
                self.assertEqual(
                    lifecycle["status"], "failed_stop_nonpublication"
                )
                self.assertIsNone(lifecycle["guardian_stop_attestation"])
                self.assertIn(
                    "guardian_stop_attestation_missing",
                    lifecycle["cleanup_errors"],
                )
                self.assertEqual(
                    lifecycle["evidence_role"],
                    "operational_non_authorizing_lifecycle",
                )
                self.assertEqual(
                    validate_publication_sidecar_service_lifecycle_v1(
                        lifecycle,
                        expected_authority=authority,
                    ),
                    lifecycle,
                )

    def test_guardian_status_fails_closed_after_any_worker_dies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            handle = factory.handles[("damage", "cpu")]
            handle.terminate()
            handle.wait(3.0)
            try:
                with self.assertRaises(SidecarError):
                    service.assert_live(authority)
            finally:
                lifecycle = service.stop()
            self.assertEqual(
                lifecycle["status"],
                "failed_stop_nonpublication",
            )
            self.assertIsNotNone(lifecycle["failure"])

    def test_guardian_status_and_bounded_stop_cli_use_readiness_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            service = self._production_service(root, factory)
            authority = service.start()
            authority_path = Path(authority["readiness_artifact_path"])

            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_code = main(
                    [
                        "--production-status-authority",
                        str(authority_path),
                        "--control-timeout-seconds",
                        "3",
                    ]
                )
            self.assertEqual(status_code, 0)
            self.assertEqual(json.loads(status_output.getvalue()), authority)

            closer_errors: list[BaseException] = []

            def close_guardian() -> None:
                try:
                    service.wait_for_guardian_stop()
                    service.stop()
                except BaseException as error:
                    closer_errors.append(error)

            closer = threading.Thread(target=close_guardian)
            closer.start()
            stop_output = io.StringIO()
            with redirect_stdout(stop_output):
                stop_code = main(
                    [
                        "--production-stop-authority",
                        str(authority_path),
                        "--control-timeout-seconds",
                        "3",
                    ]
                )
            closer.join(timeout=5)
            self.assertFalse(closer.is_alive())
            self.assertEqual(closer_errors, [])
            self.assertEqual(stop_code, 0)
            self.assertEqual(
                json.loads(stop_output.getvalue())["status"],
                "clean_stop_nonpublication",
            )

    def test_guardian_stop_cli_rejects_acknowledgement_binding_drift(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            replacements = {
                "nonce": "f" * 64,
                "lifecycle_id": "b" * 32,
                "service_authority_sha256": "e" * 64,
                "canonical_command_sha256": "d" * 64,
            }
            original_request = (
                sidecar_module.request_publication_sidecar_guardian_stop_v1
            )
            for index, (field, replacement) in enumerate(
                replacements.items()
            ):
                case_root = root / str(index)
                case_root.mkdir()
                factory = _ProcessFactory(self.config)
                service = self._production_service(case_root, factory)
                authority = service.start()
                authority_path = Path(authority["readiness_artifact_path"])
                closer_errors: list[BaseException] = []

                def close_guardian() -> None:
                    try:
                        service.wait_for_guardian_stop()
                        service.stop()
                    except BaseException as error:
                        closer_errors.append(error)

                def drifted_request(*args: Any, **kwargs: Any) -> dict[str, Any]:
                    acknowledgement = original_request(*args, **kwargs)
                    acknowledgement[field] = replacement
                    return acknowledgement

                closer = threading.Thread(target=close_guardian)
                closer.start()
                output = io.StringIO()
                error = io.StringIO()
                with (
                    self.subTest(field=field),
                    mock.patch.object(
                        sidecar_module,
                        "request_publication_sidecar_guardian_stop_v1",
                        side_effect=drifted_request,
                    ),
                    redirect_stdout(output),
                    redirect_stderr(error),
                ):
                    stop_code = main(
                        [
                            "--production-stop-authority",
                            str(authority_path),
                            "--control-timeout-seconds",
                            "3",
                        ]
                    )
                closer.join(timeout=5)
                self.assertFalse(closer.is_alive())
                self.assertEqual(closer_errors, [])
                self.assertEqual(stop_code, 78)
                self.assertEqual(output.getvalue(), "")
                self.assertRegex(
                    error.getvalue(),
                    "acknowledgement|attestation|binding",
                )

    def test_foreground_guardian_cli_commits_readiness_then_waits_for_stop(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            evidence = root / "production-evidence"
            bindings = _write_binding_set(root / "bindings", self.config)
            policy_path = root / "policy.json"
            policy_path.write_text(
                json.dumps(_policy_manifest()),
                encoding="utf-8",
            )
            preprocessing_path = root / "preprocessing.json"
            preprocessing_receipt_path = root / "preprocessing.receipt.json"
            preprocessing_path.write_text("{}\n", encoding="ascii")
            preprocessing_receipt_path.write_text("{}\n", encoding="ascii")
            factory = _ProcessFactory(self.config)
            controller_errors: list[BaseException] = []

            def controller() -> None:
                try:
                    readiness = evidence / "service_authority.v1.json"
                    self._wait_for(readiness)
                    request_publication_sidecar_guardian_stop_v1(
                        json.loads(readiness.read_text(encoding="ascii"))
                    )
                except BaseException as error:
                    controller_errors.append(error)

            controller_thread = threading.Thread(target=controller)
            controller_thread.start()
            output = io.StringIO()
            with (
                mock.patch.object(
                    sidecar_module,
                    "DockerWorkerProcessFactory",
                    return_value=factory,
                ),
                mock.patch.object(
                    sidecar_module,
                    "load_execution_config",
                    return_value=self.config,
                ),
                mock.patch.object(
                    sidecar_module,
                    "load_guardian_preprocessing_contract_v1",
                    return_value={
                        "preprocessing_contract": PREPROCESSING_CONTRACT,
                        "receipt": {},
                        "authority": _preprocessing_authority(),
                    },
                ),
                mock.patch.object(
                    sidecar_module,
                    "runtime_expectations_from_preprocessing_receipt_v1",
                    return_value=_external_runtime_expectations(
                        self.config, bindings
                    ),
                ),
                mock.patch.object(
                    sidecar_module,
                    "_default_bridge_factory",
                    side_effect=lambda **values: _Bridge(
                        process_factory=factory,
                        **values,
                    ),
                ),
                redirect_stdout(output),
            ):
                exit_code = main(
                    [
                        "--production-guardian",
                        "--binding-set",
                        str(bindings),
                        "--policy-capability-manifest",
                        str(policy_path),
                        "--preprocessing-contract",
                        str(preprocessing_path),
                        "--preprocessing-contract-receipt",
                        str(preprocessing_receipt_path),
                        "--runtime-dir",
                        str(runtime),
                        "--evidence-root",
                        str(evidence),
                        "--max-connections",
                        str(PRODUCTION_MAX_CONNECTIONS_MINIMUM),
                        "--max-requests-per-connection",
                        str(PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM),
                        "--max-total-requests",
                        str(PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM),
                        "--startup-timeout-seconds",
                        "3",
                        "--shutdown-timeout-seconds",
                        "1",
                    ]
                )
            controller_thread.join(timeout=5)
            self.assertFalse(controller_thread.is_alive())
            self.assertEqual(controller_errors, [])
            self.assertEqual(exit_code, 0)
            documents = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(documents), 2)
            self.assertEqual(
                documents[0]["artifact_kind"],
                "vast_gstreamer_analytics_production_service_authority_v1",
            )
            self.assertEqual(documents[1]["status"], "clean_stop_nonpublication")
            self.assertFalse((runtime / "analytics-execution.sock").exists())

    def test_foreground_guardian_cli_requires_preprocessing_receipt(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        error = io.StringIO()
        with (
            mock.patch.object(
                sidecar_module,
                "load_execution_config",
                return_value=self.config,
            ),
            redirect_stderr(error),
        ):
            code = main(
                [
                    "--production-guardian",
                    "--binding-set",
                    "/run/vast/bindings",
                    "--policy-capability-manifest",
                    "/run/vast/policy.json",
                    "--preprocessing-contract",
                    "/run/vast/preprocessing.json",
                    "--runtime-dir",
                    "/run/vast/runtime",
                    "--evidence-root",
                    "/run/vast/evidence",
                    "--max-connections",
                    str(PRODUCTION_MAX_CONNECTIONS_MINIMUM),
                    "--max-requests-per-connection",
                    str(PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM),
                    "--max-total-requests",
                    str(PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM),
                ]
            )
        self.assertEqual(code, 78)
        self.assertRegex(error.getvalue(), "preprocessing.*receipt")

    def test_authority_loader_rejects_named_file_swap_during_fd_read(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "authority.json"
            replacement = root / "replacement.json"
            displaced = root / "displaced.json"
            source.write_bytes(canonical_json_bytes({"source": True}) + b"\n")
            replacement.write_bytes(
                canonical_json_bytes({"source": False}) + b"\n"
            )
            original_read = sidecar_module.os.read
            swapped = False

            def race_read(descriptor: int, byte_count: int) -> bytes:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    source.rename(displaced)
                    replacement.rename(source)
                return original_read(descriptor, byte_count)

            with (
                mock.patch.object(
                    sidecar_module.os, "read", side_effect=race_read
                ),
                self.assertRaisesRegex(
                    SidecarError,
                    "changed|replaced|identity|custody",
                ),
            ):
                sidecar_module._load_canonical_json_mapping(
                    source,
                    label="race authority",
                )

    def test_cli_contract_is_explicit_and_requires_bounded_counts(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--binding-set",
                "/run/vast/bindings",
                "--policy-capability-manifest",
                "/run/vast/policy.yaml",
                "--runtime-dir",
                "/run/vast/sidecar",
                "--evidence-root",
                "/var/lib/vast/engineering",
                "--max-connections",
                "6",
                "--max-requests-per-connection",
                "100",
                "--plan-only",
            ]
        )
        self.assertEqual(args.max_connections, 6)
        self.assertEqual(args.max_requests_per_connection, 100)
        self.assertTrue(args.plan_only)

    def test_cli_modes_reject_incompatible_arguments_before_input_reads(self) -> None:
        cases = (
            (
                [
                    "--production-status-authority",
                    "/run/vast/authority.json",
                    "--binding-set",
                    "/run/vast/bindings",
                ],
                "status.*incompatible|incompatible.*binding",
            ),
            (
                [
                    "--plan-only",
                    "--binding-set",
                    "/run/vast/bindings",
                    "--policy-capability-manifest",
                    "/run/vast/policy.json",
                    "--preprocessing-contract",
                    "/run/vast/preprocessing.json",
                    "--runtime-dir",
                    "/run/vast/runtime",
                    "--evidence-root",
                    "/run/vast/evidence",
                    "--max-connections",
                    "1",
                    "--max-requests-per-connection",
                    "1",
                ],
                "plan.*incompatible|incompatible.*preprocessing",
            ),
        )
        for argv, pattern in cases:
            error = io.StringIO()
            with self.subTest(argv=argv), redirect_stderr(error):
                code = main(argv)
            self.assertEqual(code, 78)
            self.assertRegex(error.getvalue(), pattern)

    def test_front_socket_is_requested_as_atomic_publish_only_after_bridge(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            factory = _ProcessFactory(self.config)
            owner = self._owner(root, factory)
            calls: list[tuple[Path, bool]] = []
            original = sidecar_module._open_owned_listener

            def observed_open(
                path: Path, *, backlog: int, atomic_publish: bool = False
            ) -> Any:
                calls.append((path, atomic_publish))
                if atomic_publish:
                    return original(
                        path, backlog=backlog, atomic_publish=atomic_publish
                    )
                return original(path, backlog=backlog)

            errors: list[BaseException] = []
            with mock.patch.object(
                sidecar_module,
                "_open_owned_listener",
                side_effect=observed_open,
            ):
                thread = threading.Thread(
                    target=lambda: self._capture_error(owner.run, errors)
                )
                thread.start()
                self._wait_for(owner.front_socket)
                payload = b"abc"
                client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                client.connect(str(owner.front_socket))
                descriptor = create_sealed_memfd("atomic-front-input", payload)
                try:
                    send_packet(client, _request(payload), fds=(descriptor,))
                    receive_packet(client, expected_fds=0)
                finally:
                    close_fds((descriptor,))
                    client.close()
                thread.join(timeout=10)
            self.assertEqual(errors, [])
            self.assertEqual(
                sum(path == owner.front_socket and atomic for path, atomic in calls),
                1,
            )
            self.assertEqual(
                sum(path != owner.front_socket and not atomic for path, atomic in calls),
                8,
            )

    def test_docker_factory_plan_is_pinned_no_network_and_gpu_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            bindings = root / "bindings"
            runtime = root / "runtime"
            project.mkdir()
            bindings.mkdir()
            runtime.mkdir()
            binding_path = bindings / f"damage.{ENGINE_TENSORRT_CUDA}.json"
            binding_path.write_text("{}\n", encoding="utf-8")
            commands: list[list[str]] = []

            class FakeDockerProcess:
                pid = 4242

                @staticmethod
                def poll() -> None:
                    return None

                @staticmethod
                def wait(timeout: float | None = None) -> int:
                    del timeout
                    return 0

                @staticmethod
                def terminate() -> None:
                    return None

                @staticmethod
                def kill() -> None:
                    return None

            def popen(command: list[str], **kwargs: Any) -> FakeDockerProcess:
                del kwargs
                commands.append(command)
                return FakeDockerProcess()

            def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
                del kwargs
                commands.append(command)
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(_probe("gpu", self.config)),
                    stderr="",
                )

            factory = DockerWorkerProcessFactory(
                project_root=project,
                binding_set_root=bindings,
                runtime_dir=runtime,
                command_runner=runner,
                popen_factory=popen,
            )
            probe = factory.probe("gpu", self.config["workers"]["gpu"])
            self.assertEqual(probe["engine"], ENGINE_TENSORRT_CUDA)
            factory.start(
                WorkerLaunchSpec(
                    branch="damage",
                    resource="gpu",
                    engine=ENGINE_TENSORRT_CUDA,
                    binding_path=binding_path,
                    socket_path=runtime / "worker-damage-gpu.sock",
                    container_binding_path=(
                        f"/run/vast/bindings/damage.{ENGINE_TENSORRT_CUDA}.json"
                    ),
                    container_socket_path="/run/vast/analytics/worker-damage-gpu.sock",
                    worker_config=self.config["workers"]["gpu"],
                    max_requests=600,
                    lifecycle_id="a" * 32,
                )
            )
            self.assertEqual(len(commands), 2)
            probe_command, run_command = commands
            expected_user = f"{runtime.stat().st_uid}:{runtime.stat().st_gid}"
            self.assertEqual(probe_command[:4], ["docker", "run", "--rm", "--network"])
            self.assertIn("none", probe_command)
            self.assertIn("--gpus", probe_command)
            self.assertEqual(
                probe_command[probe_command.index("--user") + 1],
                expected_user,
            )
            self.assertEqual(run_command[:2], ["docker", "run"])
            self.assertIn("--network", run_command)
            self.assertEqual(
                run_command[run_command.index("--network") + 1],
                "none",
            )
            self.assertIn("--gpus", run_command)
            self.assertIn("--read-only", run_command)
            self.assertIn("--cap-drop", run_command)
            self.assertEqual(
                run_command[run_command.index("--user") + 1],
                expected_user,
            )
            self.assertEqual(
                run_command[run_command.index("--workdir") + 1],
                "/workspace",
            )
            self.assertIn("--tmpfs", run_command)
            self.assertIn(
                "/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
                run_command,
            )
            self.assertIn("HOME=/tmp", run_command)
            self.assertIn("XDG_CACHE_HOME=/tmp", run_command)
            self.assertIn("XDG_CONFIG_HOME=/tmp", run_command)
            self.assertIn(self.config["workers"]["gpu"]["image_id"], run_command)
            self.assertNotIn(self.config["workers"]["gpu"]["image"], run_command)
            self.assertIn(self.config["workers"]["gpu"]["image_id"], probe_command)
            self.assertNotIn(self.config["workers"]["gpu"]["image"], probe_command)
            self.assertNotIn(":latest", " ".join(run_command))
            self.assertEqual(
                run_command[run_command.index("--max-requests") + 1],
                "600",
            )


if __name__ == "__main__":
    unittest.main()
