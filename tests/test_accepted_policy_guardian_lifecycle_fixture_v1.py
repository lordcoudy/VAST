"""Focused protocol/custody fixtures, not upstream or campaign acceptance."""

import hashlib
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@unittest.skipUnless(sys.platform == "linux", "actual guardian socket custody requires Linux")
class AcceptedPolicyGuardianLifecycleFixtureTests(unittest.TestCase):
    def inputs(self):
        import checkpoint_gstreamer_analytics_sidecar as sidecar
        from analytics_execution_protocol import MAX_TENSOR_BYTES, TRANSPORT_KIND
        from analytics_execution_worker import WORKER_CAPABILITY_KIND
        from publication_guardian_preprocessing_contract_v1 import _AUTHORITY_FIELDS

        def digest(label):
            return hashlib.sha256(("non-authorizing-schema-fixture:" + label).encode()).hexdigest()

        preprocessing = {field: digest(field) for field in _AUTHORITY_FIELDS
            if field not in {"schema_version", "artifact_kind"}}
        preprocessing.update(schema_version=1, artifact_kind="vast_guardian_preprocessing_contract_authority_v1")
        expectations = {field: digest(field) for field in sidecar._PRODUCTION_RUNTIME_EXPECTATION_FIELDS
            if field != "worker_image_ids"}
        expectations["worker_image_ids"] = {resource: "sha256:" + digest(resource) for resource in sidecar.RESOURCES}
        capabilities = {}
        for branch, resource in sorted(sidecar.EXPECTED_KEYS):
            cpu = resource == "cpu"
            capabilities[f"{branch}:{resource}"] = {
                "schema_version": 1, "artifact_kind": WORKER_CAPABILITY_KIND,
                "protocol_identity_sha256": sidecar.PROTOCOL_IDENTITY_SHA256,
                "worker_id": f"fixture-{branch}-{resource}", "branch": branch,
                "engine": sidecar.ENGINE_BY_RESOURCE[resource],
                "worker_image_id": expectations["worker_image_ids"][resource],
                "worker_implementation_sha256": digest("implementation-" + resource),
                "runtime_name": "OpenVINO" if cpu else "TensorRT", "runtime_version": "fixture-only",
                "device_api": "CPU" if cpu else "NVIDIA_CUDA",
                "device_id": "CPU" if cpu else "GPU-11111111-2222-3333-4444-555555555555",
                "native_inference_api": "openvino.CompiledModel.__call__" if cpu else "nvinfer1::IExecutionContext::enqueueV3",
                "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
                "model_id": "fixture-" + branch,
                "source_model_sha256": digest("source-" + branch), "model_artifact_sha256": digest("artifact-" + branch),
                "runtime_weights_sha256": digest("weights-" + branch) if cpu else None,
                "preprocessing_contract_sha256": digest("preprocessing-" + branch),
                "output_contract_sha256": digest("output-" + branch), "transport": TRANSPORT_KIND,
                "max_inflight_requests": 1, "max_tensor_bytes": MAX_TENSOR_BYTES,
            }
        return preprocessing, expectations, capabilities

    def test_actual_live_query_stop_and_both_cold_readers_verify_same_ten_nodes(self):
        from tests.fixtures.accepted_policy_guardian_lifecycle_fixture_v1 import (
            begin_fixture_guardian_lifecycle_v1, finish_fixture_guardian_lifecycle_v1,
        )
        import checkpoint_gstreamer_analytics_sidecar as sidecar
        from publication_policy_qualification_execution_closure_v1 import (
            QualificationExecutionClosureV1Error, _independent_validate_guardian_documents,
        )

        with tempfile.TemporaryDirectory(prefix="agl-", dir="/var/tmp") as name:
            namespace = Path(name).resolve(strict=True)
            root = namespace / "project"
            root.mkdir(mode=0o700)
            runtime = namespace / "runtime"
            runtime.mkdir(mode=0o700)
            front, control = [socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) for _ in range(2)]
            session = None
            try:
                front.bind(str(runtime / "analytics-execution.sock"))
                control.bind(str(runtime / "analytics-control.sock"))
                preprocessing, expectations, capabilities = self.inputs()
                session = begin_fixture_guardian_lifecycle_v1(project_root=root,
                    authority_path=root / "authority.json", lifecycle_path=root / "lifecycle.json",
                    front_socket=front, control_socket=control, preprocessing_authority=preprocessing,
                    runtime_expectations=expectations, route_capabilities=capabilities)
                self.assertEqual(sidecar.query_publication_sidecar_guardian_v1(session.authority), session.authority)
                self.assertEqual(session.owner_process["pid"], __import__("os").getpid())
                result = finish_fixture_guardian_lifecycle_v1(session,
                    counters={"requests_started": 8, "requests_completed": 8, "requests_failed": 0,
                        "connections_accepted": 8, "requests_by_worker": {key: 1 for key in capabilities}})
                lifecycle = result["lifecycle"]
                self.assertEqual(len(lifecycle["retired_socket_nodes"]), 10)
                self.assertEqual(result["independent_counters"], lifecycle["counters"])
                self.assertFalse(result["limits"]["physical_inference_observed"])
                for record in lifecycle["retired_socket_nodes"]:
                    retired = Path(record["retirement_directory"]["path"]) / record["retired_name"]
                    self.assertEqual(retired.lstat().st_ino, record["socket_identity"]["st_ino"])
                    self.assertFalse((runtime / record["active_name"]).exists())
                victim = lifecycle["retired_socket_nodes"][0]
                retired = Path(victim["retirement_directory"]["path"]) / victim["retired_name"]
                retired.unlink()
                with self.assertRaises(sidecar.SidecarError):
                    sidecar.validate_publication_sidecar_service_lifecycle_v1(lifecycle, expected_authority=session.authority)
                with self.assertRaises(QualificationExecutionClosureV1Error):
                    _independent_validate_guardian_documents(authority_value=session.authority,
                        lifecycle_value=lifecycle, expected_front_socket=session.authority["front_socket"],
                        expected_execution_config_identity_sha256=expectations["execution_config_identity_sha256"],
                        expected_binding_set_identity_sha256=expectations["binding_set_identity_sha256"],
                        expected_worker_image_ids=expectations["worker_image_ids"],
                        expected_preprocessing_authority=preprocessing)
            finally:
                if session is not None:
                    session.close()
                front.close()
                control.close()

    def test_owner_lifetime_survives_fixture_clock_advance_and_explicit_close(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import patch

        import checkpoint_gstreamer_analytics_sidecar as sidecar
        from tests.fixtures import accepted_policy_guardian_lifecycle_fixture_v1 as fixture

        def exercise(authenticated_stop):
            offset = [0.0]
            fixture_clock = SimpleNamespace(
                monotonic=lambda: time.monotonic() + offset[0],
                monotonic_ns=time.monotonic_ns,
            )
            with tempfile.TemporaryDirectory(prefix="agl-owner-", dir="/var/tmp") as name:
                namespace = Path(name).resolve(strict=True)
                root, runtime = namespace / "project", namespace / "runtime"
                root.mkdir(mode=0o700)
                runtime.mkdir(mode=0o700)
                front, control = [socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) for _ in range(2)]
                session = None
                # Only the artificial responder's elapsed clock advances; production clocks stay real.
                with patch.object(fixture, "time", fixture_clock):
                    self.assertIs(sidecar.time, time)
                    try:
                        front.bind(str(runtime / "analytics-execution.sock"))
                        control.bind(str(runtime / "analytics-control.sock"))
                        preprocessing, expectations, capabilities = self.inputs()
                        session = fixture.begin_fixture_guardian_lifecycle_v1(project_root=root,
                            authority_path=root / "authority.json", lifecycle_path=root / "lifecycle.json",
                            front_socket=front, control_socket=control, preprocessing_authority=preprocessing,
                            runtime_expectations=expectations, route_capabilities=capabilities)
                        self.assertEqual(sidecar.query_publication_sidecar_guardian_v1(session.authority), session.authority)
                        offset[0] = 1801.0
                        session.thread.join(0.5)
                        self.assertTrue(session.thread.is_alive(),
                            f"fixture responder expired before owner stop: {session.errors!r}")
                        self.assertFalse(session.stop_event.is_set())
                        self.assertEqual(session.errors, [])
                        self.assertEqual(sidecar.query_publication_sidecar_guardian_v1(session.authority), session.authority)
                        if authenticated_stop:
                            result = fixture.finish_fixture_guardian_lifecycle_v1(session,
                                counters={"requests_started": 8, "requests_completed": 8, "requests_failed": 0,
                                    "connections_accepted": 8, "requests_by_worker": {key: 1 for key in capabilities}})
                            self.assertEqual(len(result["lifecycle"]["retired_socket_nodes"]), 10)
                            self.assertEqual(result["independent_counters"], result["lifecycle"]["counters"])
                            self.assertFalse(result["limits"]["physical_inference_observed"])
                            self.assertFalse(session.thread.is_alive())
                        else:
                            session.close()
                            self.assertTrue(session.stop_event.is_set())
                            self.assertFalse(session.thread.is_alive())
                            self.assertIsNone(session.stop_attestation)
                    finally:
                        if session is not None:
                            session.close()
                            self.assertFalse(session.thread.is_alive())
                        front.close()
                        control.close()

        exercise(authenticated_stop=True)
        exercise(authenticated_stop=False)

    def test_incomplete_capabilities_refuse_before_artifact_or_route_creation(self):
        from tests.fixtures.accepted_policy_guardian_lifecycle_fixture_v1 import begin_fixture_guardian_lifecycle_v1
        with tempfile.TemporaryDirectory(prefix="agl-", dir="/var/tmp") as name:
            root = Path(name).resolve(strict=True)
            front, control = [socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) for _ in range(2)]
            try:
                front.bind(str(root / "front.sock"))
                control.bind(str(root / "control.sock"))
                preprocessing, expectations, capabilities = self.inputs()
                capabilities.pop(next(iter(capabilities)))
                with self.assertRaisesRegex(ValueError, "exact eight"):
                    begin_fixture_guardian_lifecycle_v1(project_root=root,
                        authority_path=root / "authority.json", lifecycle_path=root / "lifecycle.json",
                        front_socket=front, control_socket=control, preprocessing_authority=preprocessing,
                        runtime_expectations=expectations, route_capabilities=capabilities)
                self.assertFalse((root / "authority.json").exists())
                self.assertEqual(list(root.glob("worker-*.sock")), [])
            finally:
                front.close()
                control.close()


if __name__ == "__main__":
    unittest.main()
