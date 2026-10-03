"""Real coordinator/front-transport regression; inference is a local fixture.

This is not a physical benchmark or publication acceptance. Original RED logs
retain the legacy measurement-only scanner failure. The same fixture now uses
the actual producer, guardian recorder and complete cold join.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import publication_policy_qualification_execution_closure_v1 as closure
from analytics_execution_endpoint import (
    expected_capability_from_binding_and_probe,
    terminal_detector_identity,
)
from analytics_execution_protocol import (
    PeerClosed,
    canonical_json_bytes,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
)
from checkpoint_deepstream_protocol_bridge import analytics_backend_identity
from checkpoint_gstreamer_analytics_sidecar import (
    GStreamerAnalyticsProductionService,
    PRODUCTION_MAX_CONNECTIONS_MINIMUM,
    PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
    PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
    request_publication_sidecar_guardian_stop_v1,
    validate_publication_sidecar_service_authority_v1,
    validate_publication_sidecar_service_lifecycle_v1,
)
from checkpoint_native_policy_runtime import (
    NativePolicyRuntimeCoordinator,
    NativePolicyRuntimeError,
)
from publication_policy_contract import (
    ANALYTICS_BRANCHES,
    PUBLISHABLE_SYSTEMS,
    RESOURCES,
    assess_capability_manifest,
    validate_decision_record,
)
from publication_policy_projection_v1 import (
    project_accepted_decision_v1,
    reconstruct_original_decision_v1,
)
from publication_operational_request_domain_v1 import payload_with_sha256_v1, seal_guardian_event_v1
from publication_guardian_operational_recorder_v1 import DEFAULT_BUDGETS
from publication_operational_request_reconciliation_v1 import reconcile_operational_request_domain_v1
from publication_operational_request_reconciliation_v1 import KEY, MAX_SCRATCH_FILES, _Scratch
from test_checkpoint_gstreamer_analytics_sidecar import (
    PREPROCESSING_CONTRACT,
    SHA,
    _Bridge,
    _ProcessFactory,
    _binding,
    _external_runtime_expectations,
    _load_execution_config,
    _preprocessing_authority,
    _probe,
    _write_binding_set,
)
from test_checkpoint_native_policy_runtime import capability_manifest, calibration


def _descriptor(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json_bytes(value) + b"\n")
    return _descriptor(path)


def _native_request_identity(request: dict[str, Any], decision: dict[str, Any]) -> str:
    # These are the unchanged vast_native_gst_probe.cpp transport equations.
    material = "\n".join(
        (
            "analytics_execution_request_v1",
            request["run_id"],
            request["input_frame_key"],
            request["branch"],
            decision["decision_id"],
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _native_wire_arm(run_id: str) -> str:
    material = f"analytics_execution_arm_v1\n{run_id}\ncpu_only\n100.000000"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _coherent_manifest(config: dict[str, Any]) -> dict[str, Any]:
    manifest = capability_manifest()
    for branch in ANALYTICS_BRANCHES:
        for resource in RESOURCES:
            capability = expected_capability_from_binding_and_probe(
                binding=_binding(branch, resource, config),
                runtime_probe=_probe(resource, config),
                resource=resource,
            )
            identity = {
                "runtime_backend": f"fixture-{resource}-native-worker",
                "device_api": capability["device_api"],
                "gpu_id": None if resource == "cpu" else 0,
                "worker_image_digest": capability["worker_image_id"],
                "implementation_version": "sha256:" + capability["worker_implementation_sha256"],
                "terminal_detector": terminal_detector_identity(capability),
                "terminal_backend": analytics_backend_identity(capability),
            }
            for system in PUBLISHABLE_SYSTEMS:
                row = manifest["systems"][system]["branches"][branch][resource]
                row.update(identity)
                row["runtime_identity"] = copy.deepcopy(identity)
    if not assess_capability_manifest(manifest)["passed"]:
        raise AssertionError("shared coordinator/guardian capability fixture is invalid")
    return manifest


class _BoundaryBridge(_Bridge):
    """Only the inference backend is replaced; inherited validation is real."""

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        self.execution_calls = 0

    def execute(self, request: dict[str, Any], payload: bytes) -> dict[str, Any]:
        self.execution_calls += 1
        response = super().execute(request, payload)
        route = (request["frame"]["branch"], request["decision"]["selected_resource"])
        capability = self.capabilities[route]
        return {
            **response,
            "detector": terminal_detector_identity(capability),
            "backend": analytics_backend_identity(capability),
        }


class _BoundaryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.config = _load_execution_config()
        self.manifest = _coherent_manifest(self.config)
        self.factory = _ProcessFactory(self.config)
        self.run_id = "run-operational-boundary-0001"
        self.arm_id = "arm-operational-boundary-cpu-0001"
        self.worker_id = "worker-shared-boundary-0001"
        self.calibration = calibration(self.manifest)
        self.canonical_frame_id = 2
        bindings = _write_binding_set(root / "bindings", self.config)
        inputs = root / "inputs"
        self.inputs = {
            "capability_manifest": _write_json(inputs / "manifest.json", self.manifest),
            "calibration": _write_json(inputs / "calibration.json", self.calibration),
            "execution_config": _write_json(inputs / "execution_config.json", self.config),
            "source_plan": _write_json(inputs / "source_plan.json", {"fixture_only": True, "stream_id": 0, "worker_id": self.worker_id}),
            "model_authority": _descriptor(bindings / "index.json"),
            "execution_code_closure": _write_json(inputs / "execution_code_closure.json", {
                name: _descriptor(ROOT / "scripts" / name)
                for name in ("checkpoint_native_policy_runtime.py", "checkpoint_gstreamer_analytics_sidecar.py")
            }),
            "operation_input": _write_json(inputs / "operation.json", {"fixture_only": True, "run_id": self.run_id, "arm_id": self.arm_id}),
        }
        preprocessing = _preprocessing_authority()
        preprocessing["candidate_manifest_file_sha256"] = hashlib.sha256(
            canonical_json_bytes(self.manifest) + b"\n"
        ).hexdigest()
        preprocessing["policy_contract_sha256"] = self.manifest["policy_contract_sha256"]
        expectations = _external_runtime_expectations(self.config, bindings)
        expectations["policy_contract_sha256"] = preprocessing["policy_contract_sha256"]
        runtime_dir = root / "runtime"
        runtime_dir.mkdir()
        self.service = GStreamerAnalyticsProductionService(
            execution_config=self.config,
            binding_set_dir=bindings,
            policy_capability_manifest=self.manifest,
            preprocessing_contract=PREPROCESSING_CONTRACT,
            preprocessing_authority=preprocessing,
            production_runtime_expectations=expectations,
            runtime_dir=runtime_dir,
            front_socket=runtime_dir / "analytics.sock",
            evidence_root=root / "guardian",
            process_factory=self.factory,
            bridge_factory=lambda **values: _BoundaryBridge(
                process_factory=self.factory, **values
            ),
            max_connections=PRODUCTION_MAX_CONNECTIONS_MINIMUM,
            max_requests_per_connection=PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
            max_total_requests=PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM,
            startup_timeout_s=3.0,
            shutdown_timeout_s=1.0,
            monitor_interval_s=0.01,
            operational_context={"headers_by_route": self._guardian_headers(), "output_dir": root / "guardian-operational"},
        )
        self.coordinator_arguments = dict(
            run_id=self.run_id,
            arm_id=self.arm_id,
            system="gstreamer_custom",
            scenario="checkpoint_video_dag_shared",
            codec="h264",
            policy="cpu_only",
            deadline_ms=100.0,
            branches=ANALYTICS_BRANCHES,
            capability_manifest=self.manifest,
            calibration=self.calibration,
        )
        initial = NativePolicyRuntimeCoordinator(**self.coordinator_arguments)
        self.native_header = self._native_header(initial)
        self.coordinator = NativePolicyRuntimeCoordinator(
            **self.coordinator_arguments,
            operational_context={"header": self.native_header, "output_dir": root / "native-operational"},
        )
        self.authority: dict[str, Any] | None = None
        self.lifecycle: dict[str, Any] | None = None
        self.occurrences: list[dict[str, Any]] = []
        self.finished_domains: list[dict[str, Any]] = []
        self.finished_measurements: list[dict[str, Any]] = []
        self.output = root / "producer"

    def _native_header(self, coordinator) -> dict[str, Any]:
        return payload_with_sha256_v1({
            "schema_version": 1, "artifact_kind": "vast_qualification_operational_native_domain_v1",
            "record_kind": "header", "digest_algorithm": "sha256",
            "operation_input": self.inputs["operation_input"], "run_id": self.run_id,
            "context_arm_id": self.arm_id, "system": "gstreamer_custom",
            "scenario": "checkpoint_video_dag_shared", "codec": "h264", "policy": "cpu_only", "deadline_ms": 100.0,
            "protocol": {"schema_version": 1, "decision_request": "decision_request", "path": "path_enter", "terminal": "terminal", "source_descriptor": "policy_request_source"},
            "descriptors": {**{key: self.inputs[key] for key in ("capability_manifest", "source_plan", "model_authority", "calibration", "execution_code_closure")},
                "policy_request_source": _descriptor(ROOT / "deploy/native_gst_probe/vast_native_gst_probe.cpp"),
                "policy_coordinator_source": _descriptor(ROOT / "scripts/checkpoint_native_policy_runtime.py")},
            "initial_state": coordinator._initial_policy_state,
            "counts": dict.fromkeys(("complete_decision_count", "measurement_decision_count", "excluded_decision_count", "runtime_feedback_count", "measurement_feedback_count", "excluded_feedback_count"), 0),
            "adaptive_history": None,
        })

    def _guardian_headers(self) -> dict[tuple[str, str], dict[str, Any]]:
        descriptors = {
            **{key: self.inputs[key] for key in ("capability_manifest", "execution_config", "execution_code_closure", "model_authority", "source_plan")},
            "accounting_input": self.inputs["operation_input"],
            # Actual service start replaces this placeholder with its real file.
            "service_authority": self.inputs["operation_input"],
            "native_protocol_source": _descriptor(ROOT / "deploy/native_gst_probe/vast_native_gst_probe.cpp"),
            "proxy_protocol_source": _descriptor(ROOT / "scripts/checkpoint_deepstream_protocol_bridge.py"),
        }
        return {(branch, resource): {
            "schema_version": 1, "artifact_kind": "vast_guardian_operational_request_journal_v1",
            "record_kind": "header", "digest_algorithm": "sha256", "descriptors": copy.deepcopy(descriptors),
            "lifecycle_id": "0" * 32, "owner": {"uid": 0, "gid": 0, "pid": 1, "proc_stat_starttime_ticks": 1},
            "route": {"branch": branch, "resource": resource},
            "protocols": [{"id": 0, "schema_version": 1, "message_type": "analytics_execute", "transport": "unix_seqpacket_scm_rights_sealed_memfd", "source_descriptor": "native_protocol_source"}],
            "contexts": [{"id": 0, "protocol": 0, "run_id": self.run_id, "arm_id": _native_wire_arm(self.run_id), "system": "gstreamer_custom", "policy": "cpu_only"}],
            "front_workers": [{"id": 0, "worker_id": self.worker_id, "stream_id": 0}],
            "bindings": [{"id": 0, "context": 0, "front_worker": 0}],
            "worker_capability": {},
            "initial_counters": dict.fromkeys(("requests_started", "requests_completed", "requests_failed", "unfinished_requests", "connections_accepted", "event_count"), 0),
            "budgets": dict(DEFAULT_BUDGETS), "sha256": "0" * 64,
        } for branch in ANALYTICS_BRANCHES for resource in RESOURCES}

    def start(self) -> None:
        self.authority = self.service.start()
        validate_publication_sidecar_service_authority_v1(self.authority)
        self.backend_bridge = self.service._bridge

    def complete(
        self, frame_id: int, branch: str,
        *, substitute_front_frame: dict[str, Any] | None = None,
    ) -> None:
        # The final input is admitted before stop, in the existing final 1 ms
        # measurement boundary guard, then its branch executes during drain.
        phase_times = {1: (900.0, 935.0), 2: (1_100.0, 2_210.0), 3: (2_099.5, 2_185.0)}
        arrival, completion = phase_times[frame_id]
        request = {
            "schema_version": 1,
            "message_type": "decision_request",
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "input_frame_key": f"dataset:0:source:{frame_id}:1000",
            "trace_id": f"{self.run_id}:0:{frame_id}",
            "stream_id": 0,
            "frame_id": frame_id,
            "transport_pts_ns": frame_id * 1000,
            "branch": branch,
            "arrival_ms": arrival,
            "decision_time_ms": arrival + 20.0,
            "feature_observed_timestamp_ms": arrival + 10.0,
            "queue_depths": {"cpu": 0, "gpu": 0},
        }
        decision = self.coordinator.handle_message(request["worker_id"], request)
        binding = self.manifest["systems"]["gstreamer_custom"]["branches"][branch]["cpu"]
        path = {
            "schema_version": 1,
            "message_type": "path_enter",
            "run_id": self.run_id,
            "worker_id": request["worker_id"],
            "decision_id": decision["decision_id"],
            "input_frame_key": request["input_frame_key"],
            "branch": branch,
            "transport_pts_ns": request["transport_pts_ns"],
            "selected_resource": "cpu",
            "implementation_id": binding["implementation_id"],
            "emitter_id": binding["native_evidence"]["emitter_id"],
            "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
            "event_id": f"boundary-native-path-{branch}-{frame_id}",
            "timestamp_ms": arrival + 21.0,
        }
        self.coordinator.handle_message(request["worker_id"], path)
        payload = b"\x01\x02\x03"
        front = {
            "schema_version": 1,
            "message_type": "analytics_execute",
            "request_id": _native_request_identity(request, decision),
            "run_id": self.run_id,
            "arm_id": _native_wire_arm(self.run_id),
            "gstreamer_worker_id": request["worker_id"],
            "frame": {
                field: request[field]
                for field in ("input_frame_key", "stream_id", "frame_id", "transport_pts_ns", "branch")
            },
            "decision": {
                "decision_id": decision["decision_id"],
                "decision_seq": decision["decision_seq"],
                "selected_resource": "cpu",
                "selected_implementation_id": binding["implementation_id"],
                "emitter_id": binding["native_evidence"]["emitter_id"],
                "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
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
        if substitute_front_frame is not None:
            front["frame"].update(substitute_front_frame)
        client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        client.settimeout(5.0)
        descriptor = create_sealed_memfd("boundary-native-input", payload)
        try:
            client.connect(str(self.service.front_socket))
            send_packet(client, front, fds=(descriptor,))
            response, descriptors = receive_packet(client, expected_fds=0)
            close_fds(descriptors)
        finally:
            close_fds((descriptor,))
            client.close()
        if response["request_id"] != front["request_id"]:
            raise AssertionError("real front response lost its request identity")
        terminal = {
            "schema_version": 1,
            "message_type": "terminal",
            "run_id": self.run_id,
            "worker_id": request["worker_id"],
            "decision_id": decision["decision_id"],
            "input_frame_key": request["input_frame_key"],
            "branch": branch,
            "transport_pts_ns": request["transport_pts_ns"],
            "selected_resource": response["selected_resource"],
            "terminal_status": response["terminal_status"],
            "terminal_timestamp_ms": completion,
            "actual_service_ms": completion - path["timestamp_ms"],
            "detector": response["detector"],
            "backend": response["backend"],
        }
        self.coordinator.handle_message(request["worker_id"], terminal)
        self.occurrences.append({"request": request, "decision": decision, "path": path, "terminal": terminal, "observed_front": front})

    def finish(self, *, stop: bool = True) -> None:
        canonical = {
            occurrence["request"]["input_frame_key"]: {
                "trace_id": "canonical-measurement-boundary-0002",
                "stream_id": 0,
                "frame_id": self.canonical_frame_id,
            }
            for occurrence in self.occurrences
            if occurrence["request"]["frame_id"] == 2
        }
        self.summary = self.coordinator.promote(self.output, canonical_frames=canonical)
        self.canonical_frames = canonical
        self.expected_native_header = payload_with_sha256_v1({**self.native_header, "counts": self.summary["operational_counts"]})
        domain = self.summary["operational_domain"]
        self.finished_domains.append({"path": Path(domain["path"]), "descriptor": domain, "expected_header": self.expected_native_header})
        self.finished_measurements.append({"path": self.output / "publication_policy_decisions.jsonl", "descriptor": _descriptor(self.output / "publication_policy_decisions.jsonl"), "canonical_frames": canonical})
        if stop:
            self.stop()

    def next_original_operation(self) -> None:
        if self.lifecycle is not None or not self.finished_domains:
            raise AssertionError("next operation requires a drained first producer and live guardian")
        operation = len(self.finished_domains)
        initial = NativePolicyRuntimeCoordinator(**self.coordinator_arguments)
        self.native_header = self._native_header(initial)
        self.native_header["operation_input"] = _write_json(
            self.root / "inputs" / f"operation-{operation}.json",
            {"fixture_only": True, "run_id": self.run_id, "arm_id": self.arm_id, "original_operation": operation},
        )
        self.native_header = payload_with_sha256_v1(self.native_header)
        self.coordinator = NativePolicyRuntimeCoordinator(
            **self.coordinator_arguments,
            operational_context={"header": self.native_header, "output_dir": self.root / f"native-operational-{operation}"},
        )
        self.output = self.root / f"producer-{operation}"
        self.occurrences = []

    def stop(self) -> None:
        if self.authority is not None and self.lifecycle is None:
            request_publication_sidecar_guardian_stop_v1(self.authority)
            self.lifecycle = self.service.stop()
            validate_publication_sidecar_service_lifecycle_v1(self.lifecycle, expected_authority=self.authority)
            if not self.factory.all_stopped():
                raise AssertionError("owned fixture workers remained running")

    def _authority(self, occurrence: dict[str, Any]) -> None:
        accepted = occurrence["accepted_record"]
        projected = project_accepted_decision_v1(accepted, canonical_trace_id=accepted["trace_id"],
            publication_decision_seq=accepted["decision_seq"], issued_record_sha256=occurrence["issued_record_sha256"])
        reconstructed, issued = reconstruct_original_decision_v1(projected)
        if reconstructed != accepted or issued["sha256"] != occurrence["issued_record_sha256"]:
            raise AssertionError("original issued/accepted inverse changed")
        validate_decision_record(accepted, self.manifest)

    def cold_workload(self, *, companion: dict[str, Any] | None = None) -> dict[str, Any]:
        group = self.service.operational_group if companion is None else companion
        return reconcile_operational_request_domain_v1(
            producer_domains=self.finished_domains,
            guardian_companion={"path": Path(group["path"]), "descriptor": group},
            measurement_descriptors=self.finished_measurements,
            expected_context={"mode": "complete_qualification_operational_identity_v1", "operation_count": len(self.finished_domains),
                "guardian_headers": {f"{branch}:{resource}": header for (branch, resource), header in self.service.operational_headers.items()}},
            authority_validator=self._authority, scratch_root=self.root / "cold-scratch",
        )

    def resealed_guardian_mutation(self, mutate) -> dict[str, Any]:
        """Adversarial copy; retain original requests/counters and authority."""
        group = json.loads(Path(self.service.operational_group["path"]).read_bytes())
        journal = next(row for row in group["journals"] if row["route"] == "damage:cpu")
        original_events = journal["event_count"]
        records = [json.loads(line) for line in Path(journal["path"]).read_bytes().splitlines()]
        mutate(records)
        records[0] = payload_with_sha256_v1(records[0])
        previous = records[0]["sha256"]
        for index in range(1, len(records)):
            unsigned = {key: value for key, value in records[index].items() if key != "sha256"}
            records[index] = seal_guardian_event_v1(unsigned, previous_sha256=previous)
            previous = records[index]["sha256"]
        directory = Path(tempfile.mkdtemp(prefix="tampered-", dir=self.root))
        path = directory / "damage.cpu.jsonl"
        with path.open("xb") as stream:
            for record in records:
                stream.write(canonical_json_bytes(record) + b"\n")
        journal.update(_descriptor(path))
        journal["event_count"] = len(records) - 1
        journal["final_event_sha256"] = previous
        group["counts"]["event_count"] += journal["event_count"] - original_events
        return _write_json(directory / "companion.json", payload_with_sha256_v1(group))


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SOCK_SEQPACKET")
    and hasattr(socket, "SO_PEERCRED") and hasattr(os, "memfd_create"),
    "real Linux seqpacket, peer credentials and sealed memfd are required",
)
class PublicationOperationalBoundaryTests(unittest.TestCase):
    def test_complete_cold_workload_includes_warmup_measurement_and_drain(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                for frame in (1, 2, 3):
                    for branch in ANALYTICS_BRANCHES:
                        fixture.complete(frame, branch)
                fixture.finish()
                measured = [json.loads(line) for line in (fixture.output / "publication_policy_decisions.jsonl").read_text(encoding="ascii").splitlines()]
                self.assertEqual(fixture.summary["runtime_decision_count"], 12)
                self.assertEqual(fixture.summary["accepted_decision_count"], 4)
                self.assertEqual({row["branch"] for row in measured}, set(ANALYTICS_BRANCHES))
                self.assertTrue(all(row["native_decision_evidence"]["terminal_timestamp_ms"] > 2_100.0 for row in measured))
                drain = [row for row in fixture.occurrences if row["request"]["frame_id"] == 3]
                self.assertTrue(all(row["request"]["arrival_ms"] < 2_100.0 < row["request"]["decision_time_ms"] for row in drain))
                counters = fixture.lifecycle["counters"]
                self.assertEqual(counters["requests_started"], 12)
                self.assertEqual(counters["requests_completed"], 12)
                self.assertEqual(counters["requests_failed"], 0)
                self.assertEqual({key: value for key, value in counters["requests_by_worker"].items() if value}, {f"{branch}:cpu": 3 for branch in ANALYTICS_BRANCHES})
                workload = fixture.cold_workload()
                self.assertEqual(workload["request_count"], counters["requests_completed"], "complete cold closure must include the eight excluded original executions; legacy measurement scanner returns only four")
                self.assertEqual(workload["measurement_request_count"], 4)
                self.assertEqual(workload["excluded_request_count"], 8)
                self.assertEqual(workload["requests_by_worker"], counters["requests_by_worker"])
            finally:
                fixture.stop()

    def test_same_count_foreign_front_frame_cannot_pass_complete_cold_join(self) -> None:
        for field, foreign in (
            ("input_frame_key", "foreign-dataset:0:source:2:1000"),
            ("frame_id", 3),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
                fixture = _BoundaryFixture(Path(temporary))
                try:
                    fixture.start()
                    for branch in ANALYTICS_BRANCHES:
                        fixture.complete(
                            2, branch,
                            substitute_front_frame={field: foreign} if branch == "damage" else None,
                        )
                    fixture.finish()
                    counters = fixture.lifecycle["counters"]
                    self.assertEqual(counters["requests_started"], 4)
                    self.assertEqual(counters["requests_completed"], 4)
                    self.assertEqual(counters["requests_failed"], 0)
                    self.assertEqual(fixture.summary["accepted_decision_count"], 4)
                    substituted = next(row for row in fixture.occurrences if row["request"]["branch"] == "damage")
                    self.assertNotEqual(substituted["request"][field], substituted["observed_front"]["frame"][field])
                    with self.assertRaisesRegex(ValueError, "substituted|foreign|domains differ", msg="same-count foreign front identity must be rejected by complete cold join"):
                        fixture.cold_workload()
                finally:
                    fixture.stop()

    def test_observed_stream_substitution_is_rejected_before_inference(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                with self.assertRaises(PeerClosed):
                    fixture.complete(2, "damage", substitute_front_frame={"stream_id": 1})
                fixture.stop()
                self.assertEqual(fixture.lifecycle["counters"]["requests_started"], 1)
                self.assertEqual(fixture.lifecycle["counters"]["requests_completed"], 0)
                self.assertEqual(fixture.lifecycle["counters"]["requests_failed"], 1)
                self.assertEqual(fixture.backend_bridge.execution_calls, 0)
                self.assertEqual(fixture.lifecycle["status"], "failed_stop_nonpublication")
            finally:
                fixture.stop()

    def test_duplicate_actual_terminal_is_rejected_without_an_extra_front_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                original = fixture.occurrences[0]
                with self.assertRaises(NativePolicyRuntimeError):
                    fixture.coordinator.handle_message(original["request"]["worker_id"], original["terminal"])
                fixture.finish()
                self.assertEqual(fixture.lifecycle["counters"]["requests_completed"], 4)
                self.assertEqual(fixture.summary["runtime_decision_count"], 4)
            finally:
                fixture.stop()

    def test_resealed_guardian_identity_and_terminal_mutations_fail_cold_validation(self) -> None:
        def frame_substitution(records):
            records[1]["frame_id"] = 3

        def stream_substitution(records):
            records[0]["front_workers"][0]["stream_id"] = 1

        def terminal_duplicate(records):
            duplicate = copy.deepcopy(records[-1])
            duplicate["seq"] = 9
            records.append(duplicate)

        def terminal_missing(records):
            records.pop()

        for mutation in (frame_substitution, stream_substitution, terminal_duplicate, terminal_missing):
            with self.subTest(mutation=mutation.__name__), tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
                fixture = _BoundaryFixture(Path(temporary))
                try:
                    fixture.start()
                    for branch in ANALYTICS_BRANCHES:
                        fixture.complete(2, branch)
                    fixture.finish()
                    self.assertEqual(fixture.cold_workload()["request_count"], 4)
                    changed = fixture.resealed_guardian_mutation(mutation)
                    with self.assertRaises(ValueError):
                        fixture.cold_workload(companion=changed)
                    self.assertEqual(fixture.lifecycle["counters"]["requests_completed"], 4)
                finally:
                    fixture.stop()

    def test_stock_canonical_frame_mapping_can_differ_from_original_worker_frame(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            fixture.canonical_frame_id = 202
            try:
                fixture.start()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                fixture.finish()
                self.assertEqual({row["request"]["frame_id"] for row in fixture.occurrences}, {2})
                self.assertEqual({frame["frame_id"] for frame in fixture.canonical_frames.values()}, {202})
                workload = fixture.cold_workload()
                self.assertEqual(workload["request_count"], 4)
                self.assertEqual(workload["measurement_request_count"], 4)
            finally:
                fixture.stop()

    def test_legitimate_repeated_wire_identity_keeps_both_original_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                original_ids = [row["observed_front"]["request_id"] for row in fixture.occurrences]
                fixture.finish(stop=False)
                fixture.next_original_operation()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                self.assertEqual([row["observed_front"]["request_id"] for row in fixture.occurrences], original_ids)
                fixture.finish()
                self.assertEqual(fixture.lifecycle["counters"]["requests_completed"], 8)
                workload = fixture.cold_workload()
                self.assertEqual(workload["original_operation_count"], 2)
                self.assertEqual(workload["request_count"], 8)
                self.assertEqual(workload["measurement_request_count"], 8)
            finally:
                fixture.stop()

    def test_lazy_canonical_ingress_provider_is_called_once_for_each_original_operation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-lazy-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                fixture.finish(stop=False)
                fixture.next_original_operation()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                fixture.finish()
                calls = []
                for ordinal, measurement in enumerate(fixture.finished_measurements):
                    original = copy.deepcopy(measurement["canonical_frames"])
                    def provide(ordinal=ordinal, original=original):
                        calls.append(ordinal)
                        return copy.deepcopy(original)
                    measurement["canonical_frames"] = provide
                workload = fixture.cold_workload()
                self.assertEqual(calls, [0, 1])
                self.assertEqual(workload["original_operation_count"], 2)
                self.assertEqual(workload["request_count"], 8)
                self.assertEqual(workload["measurement_request_count"], 8)
            finally:
                fixture.stop()

    def test_lazy_canonical_ingress_provider_cannot_substitute_same_count_stream_mapping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-boundary-lazy-foreign-") as temporary:
            fixture = _BoundaryFixture(Path(temporary))
            try:
                fixture.start()
                for branch in ANALYTICS_BRANCHES:
                    fixture.complete(2, branch)
                fixture.finish()
                measurement = fixture.finished_measurements[0]
                foreign = copy.deepcopy(measurement["canonical_frames"])
                for frame in foreign.values():
                    frame["stream_id"] = 1
                calls = []
                def provide():
                    calls.append(0)
                    return foreign
                measurement["canonical_frames"] = provide
                with self.assertRaisesRegex(ValueError, "measured original stream differs from ingress"):
                    fixture.cold_workload()
                self.assertEqual(calls, [0])
                self.assertEqual(fixture.lifecycle["counters"]["requests_completed"], 4)
            finally:
                fixture.stop()

    def test_default_scratch_file_exhaustion_is_bounded_and_cleans_only_private_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vast-cold-scratch-") as temporary:
            root = Path(temporary)
            sentinel = root / "original-evidence.json"
            sentinel.write_bytes(b"original evidence\n")
            scratch = _Scratch(root)
            private = scratch.path
            try:
                for ordinal in range(MAX_SCRATCH_FILES):
                    scratch.write([KEY.pack(bytes(32), 0, ordinal, 1)])
                with self.assertRaisesRegex(ValueError, "scratch budget exhausted"):
                    scratch.write([KEY.pack(bytes(32), 0, MAX_SCRATCH_FILES, 1)])
                self.assertEqual(len(list(private.iterdir())), MAX_SCRATCH_FILES)
            finally:
                scratch.close()
            self.assertFalse(private.exists())
            self.assertEqual(sentinel.read_bytes(), b"original evidence\n")


if __name__ == "__main__":
    unittest.main()
