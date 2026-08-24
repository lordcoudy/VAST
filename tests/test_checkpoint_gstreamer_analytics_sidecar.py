from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

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
from checkpoint_gstreamer_analytics_sidecar import (  # noqa: E402
    DockerWorkerProcessFactory,
    GStreamerAnalyticsSidecar,
    SidecarError,
    WorkerLaunchSpec,
    build_parser,
    load_materialized_binding_set,
)


RESOURCES = ("cpu", "gpu")
ENGINE_BY_RESOURCE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
GPU_UUID = "GPU-00000000-0000-0000-0000-000000000001"
SHA = hashlib.sha256(b"sidecar-fixture").hexdigest()


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
        self.fail_execute = fail_execute

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
            preprocessing_contract={"fixture": True},
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

    def test_atomic_front_publish_link_race_preserves_attacker_node(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "front.sock"
            original_link = sidecar_module.os.link

            def race_link(source: Any, destination: Any, **kwargs: Any) -> None:
                Path(destination).write_text("ATTACKER\n", encoding="utf-8")
                original_link(source, destination, **kwargs)

            with (
                mock.patch.object(sidecar_module.os, "link", side_effect=race_link),
                self.assertRaisesRegex(SidecarError, "already exists"),
            ):
                sidecar_module._open_owned_listener(
                    target,
                    backlog=1,
                    atomic_publish=True,
                )
            self.assertEqual(target.read_text(encoding="utf-8"), "ATTACKER\n")
            self.assertEqual(list(root.iterdir()), [target])

    def test_atomic_front_publish_post_link_failure_removes_owned_node(self) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "front.sock"
            original_identity = sidecar_module._stat_identity
            identity_calls = 0

            def fail_after_link(path: Path) -> Any:
                nonlocal identity_calls
                identity_calls += 1
                if identity_calls == 2:
                    raise SidecarError("injected post-link failure")
                return original_identity(path)

            with (
                mock.patch.object(
                    sidecar_module,
                    "_stat_identity",
                    side_effect=fail_after_link,
                ),
                self.assertRaisesRegex(SidecarError, "post-link failure"),
            ):
                sidecar_module._open_owned_listener(
                    target,
                    backlog=1,
                    atomic_publish=True,
                )
            self.assertEqual(list(root.iterdir()), [])

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
            self.assertEqual(probe_command[:4], ["docker", "run", "--rm", "--network"])
            self.assertIn("none", probe_command)
            self.assertIn("--gpus", probe_command)
            self.assertEqual(run_command[:2], ["docker", "run"])
            self.assertIn("--network", run_command)
            self.assertEqual(
                run_command[run_command.index("--network") + 1],
                "none",
            )
            self.assertIn("--gpus", run_command)
            self.assertIn("--read-only", run_command)
            self.assertIn("--cap-drop", run_command)
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
