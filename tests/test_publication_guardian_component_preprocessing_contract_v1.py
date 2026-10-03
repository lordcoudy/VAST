"""Component seam fixtures: real files/front transport, local inference only.

The source-authority fixture is explicit and cannot establish model/image
acceptance; its physical selected-loader contracts are tested separately.
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
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import publication_guardian_component_preprocessing_contract_v1 as target
import publication_guardian_runtime_expectations_v1 as expectations
from analytics_execution_protocol import (PeerClosed, canonical_json_bytes, close_fds,
    create_sealed_memfd, receive_packet, send_packet)
from checkpoint_gstreamer_analytics_sidecar import GStreamerAnalyticsProductionService, SidecarError
from publication_guardian_preprocessing_contract_v1 import load_guardian_preprocessing_contract_v1
from publication_operational_capture_plan_v1 import (BASELINE, SHARED, DIAGNOSTIC_MODE, ROUTES,
    _guardian_context, _native_context)
from publication_operational_request_domain_v1 import payload_with_sha256_v1
from test_publication_guardian_runtime_expectations_v1 import receipt as legacy_receipt
from test_publication_operational_boundary_v1 import _BoundaryFixture, _native_wire_arm


def descriptor(path):
    raw = path.read_bytes()
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")
    return descriptor(path)


class FileFixture:
    def __init__(self, root):
        self.root = root
        asset = write(root / "input/asset.json", {"fixture_only": True})
        contract = {"fixture_preprocessing": "unchanged"}
        self.capability = write(root / "input/capability.json", {"historical_complete_table": True})
        execution = write(root / "input/execution.json", {"workers": "fixture"})
        branches = ("plate_number", "vehicle_type", "damage", "foreign_object")
        self.source_plans = {name: {"fixture_plan": name,
            "topology_kind": "independent_processes" if name == "baseline" else "shared_video_dag",
            "streams": [{"stream_id": stream, **({"workers": [{"branch_id": branch,
                "process_id": f"worker-0-{branch}-{stream}"} for branch in branches]} if name == "baseline" else
                {"graph_process": {"process_id": f"worker-1-{stream}"}})} for stream in range(6)]}
            for name in ("baseline", "shared")}
        source_refs = {name: write(root / f"input/{name}.json", plan) for name, plan in self.source_plans.items()}
        projection = copy.deepcopy(legacy_receipt()["model_parity_refresh_authority"])
        del projection["image_identity_patch"]
        projection["execution_config"].update({**execution, "path": "input/execution.json"})
        self.rows = []
        self.cells = []
        for i, scenario in enumerate((BASELINE, SHARED)):
            run = f"component-fixture-{i}"
            arm = f"component-arm-{i}"
            self.cells.append({"arm_id": arm, "run_id": run, "system": "gstreamer_custom", "resource": "cpu",
                "codec": "h264", "topology_kind": "independent_processes" if i == 0 else "shared_video_dag",
                "scenario": scenario, "policy": "cpu_only", "deadline_ms": 100.0, "duration_s": 180})
            desc = {key: asset for key in ("calibration", "model_authority", "capability_manifest",
                "execution_code_closure", "policy_request_source", "policy_coordinator_source")}
            desc["capability_manifest"] = self.capability
            desc["source_plan"] = source_refs["baseline" if i == 0 else "shared"]
            self.rows.append({"operation_id": f"original-{i}", "phase": "diagnostic", "arm_id": arm, "run_id": run,
                "system": "gstreamer_custom", "scenario": scenario, "codec": "h264", "policy": "cpu_only",
                "deadline_ms": 100.0, "warmup_s": 30.0, "measurement_s": 180.0, "drain_timeout_s": 10.0,
                "streams": 6, "branches": 4, "original_operation": asset, "descriptors": desc,
                "front_workers_by_route": {route: [{"worker_id": f"worker-0-{route.split(':')[0]}-{stream}" if i == 0
                    else f"worker-1-{stream}", "stream_id": stream}
                    for stream in range(6)] for route in ROUTES}})
        def relative(ref):
            return {**ref, "path": str(Path(ref["path"]).relative_to(root))}
        self.source = {"root": root, "document": {"sha256": "a" * 64, "policy_contract_sha256": "b" * 64,
                "model_authority": relative(asset), "execution_code_closure": relative(asset),
                "source_plans": {name: relative(ref) for name, ref in source_refs.items()}},
            "capability_manifest_descriptor": relative(self.capability), "worker_projection": projection,
            "calibration_descriptor": relative(asset), "execution_code_closure_descriptor": relative(asset),
            "policy_request_source_descriptor": relative(asset), "policy_coordinator_source_descriptor": relative(asset),
            "preprocessing_contract": contract, "planned_cells": self.cells, "source_plans": self.source_plans,
            "verify_barrier": lambda: None}
        self.source_path = root / "input/source-authority.json"
        self.source["descriptor"] = relative(write(self.source_path, {"fixture_source_authority": True}))
        manifest = write(root / "capture/operations.json", payload_with_sha256_v1({
            "schema_version": 1, "artifact_kind": "vast_original_operational_capture_manifest_v1",
            "mode": DIAGNOSTIC_MODE, "accepted": False, "publication_ready": False, "operations": self.rows}))
        inventory = write(root / "capture/inventory.json", payload_with_sha256_v1({
            "schema_version": 1, "artifact_kind": "vast_operational_source_plan_inventory_v1", "mode": DIAGNOSTIC_MODE,
            "accepted": False, "publication_ready": False, "source_plans": [{"operation_id": row["operation_id"],
                "descriptor": row["descriptors"]["source_plan"]} for row in self.rows]}))
        guardian_descriptors = {"capability_manifest": self.capability, "execution_config": execution,
            "execution_code_closure": asset, "model_authority": asset, "native_protocol_source": asset, "proxy_protocol_source": asset}
        self.context = _guardian_context(self.rows, DIAGNOSTIC_MODE, guardian_descriptors, manifest, inventory, root / "operational")
        self.context_path = root / "capture/guardian.json"
        write(self.context_path, self.context)

    def reseal_context(self):
        """A tamper fixture recomputes all supplied context/manifest seals."""
        manifest_path = self.root / "capture/operations.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["operations"] = self.rows
        manifest = write(manifest_path, payload_with_sha256_v1(manifest))
        old = self.context["headers_by_route"][ROUTES[0]]["descriptors"]
        guardian_inputs = {key: old[key] for key in ("capability_manifest", "execution_config",
            "execution_code_closure", "model_authority", "native_protocol_source", "proxy_protocol_source")}
        self.context = _guardian_context(self.rows, DIAGNOSTIC_MODE, guardian_inputs, manifest,
            old["source_plan"], self.root / "operational")
        context_descriptor = write(self.context_path, self.context)
        receipt_path = self.root / "preprocessing" / target.RECEIPT_FILENAME
        receipt = json.loads(receipt_path.read_bytes())
        receipt["operational_context"] = {**context_descriptor,
            "path": str(self.context_path.relative_to(self.root))}
        receipt["receipt_sha256"] = target._semantic_sha({key: value for key, value in receipt.items() if key != "receipt_sha256"})
        receipt_path.chmod(0o600)
        write(receipt_path, receipt)

    @contextmanager
    def held(self, **kwargs):
        if kwargs.get("expected_descriptor") is not None:
            if kwargs["expected_descriptor"] != self.source["descriptor"]:
                raise ValueError("fixture source descriptor mismatch")
        yield self.source

    def materialize(self):
        return target.materialize_component_guardian_preprocessing_contract_v1(project_root=self.root,
            component_authority_path=self.source_path, operational_context_path=self.context_path, output_dir=self.root / "preprocessing")

    def load(self):
        return target.load_component_guardian_preprocessing_contract_v1(project_root=self.root,
            preprocessing_contract_path=self.root / "preprocessing" / target.CONTRACT_FILENAME,
            materialization_receipt_path=self.root / "preprocessing" / target.RECEIPT_FILENAME,
            capability_manifest_path=self.root / "input/capability.json")


class ComponentPreprocessingTests(unittest.TestCase):
    def test_original_long_stock_cell_ids_remain_accepted_without_a_new_clamp(self):
        from publication_policy_qualification_runtime_inputs_v2 import qualification_pilot_cells_v2
        for resource in ("cpu", "gpu"):
            rows = [{"operation_id": "original-" + cell.arm_id, "arm_id": cell.arm_id, "run_id": cell.run_id,
                "system": cell.system, "scenario": cell.scenario, "codec": cell.codec, "policy": cell.policy,
                "deadline_ms": cell.deadline_ms, "wire_arm_id": hashlib.sha256(("analytics_execution_arm_v1\n" +
                    cell.run_id + "\n" + cell.policy + "\n100.000000").encode("ascii")).hexdigest()}
                for cell in qualification_pilot_cells_v2() if cell.system == "gstreamer_custom"
                    and cell.resource == resource and cell.codec == "h264"]
            self.assertEqual(target._validate_operations(rows), rows)

    def test_physical_receipt_last_roundtrip_nonpromotion_and_all_eight_worker_pins(self):
        with tempfile.TemporaryDirectory() as name:
            fixture = FileFixture(Path(name))
            with patch.object(target, "held_component_authority_v1", fixture.held):
                fixture.materialize()
                loaded = fixture.load()
                self.assertFalse(loaded["receipt"]["accepted"])
                self.assertFalse(loaded["receipt"]["publication_ready"])
                self.assertEqual(len(loaded["authority"]["allowed_operations"]), 2)
                actual = expectations.runtime_expectations_from_preprocessing_receipt_v1(loaded["receipt"])
                self.assertEqual(set(actual["worker_image_ids"]), {"cpu", "gpu"})
                with self.assertRaises(Exception):
                    load_guardian_preprocessing_contract_v1(project_root=fixture.root,
                        preprocessing_contract_path=fixture.root / "preprocessing" / target.CONTRACT_FILENAME,
                        materialization_receipt_path=fixture.root / "preprocessing" / target.RECEIPT_FILENAME,
                        candidate_manifest_path=fixture.root / "input/capability.json",
                        acceptance_loader=lambda **kwargs: self.fail("full loader must reject component kind first"))

    def test_resealed_capture_foreign_coordinates_are_rejected_before_materialization(self):
        with tempfile.TemporaryDirectory() as name:
            fixture = FileFixture(Path(name))
            fixture.source["planned_cells"][0]["run_id"] = "foreign-run"
            with patch.object(target, "held_component_authority_v1", fixture.held):
                with self.assertRaisesRegex(target.ComponentGuardianPreprocessingContractV1Error, "coordinates"):
                    fixture.materialize()
            self.assertFalse((fixture.root / "preprocessing").exists())

    def test_original_source_or_contract_byte_mutation_rejects_cold_loader(self):
        for field in ("plan", "contract", "receipt"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as name:
                fixture = FileFixture(Path(name))
                with patch.object(target, "held_component_authority_v1", fixture.held):
                    fixture.materialize()
                    path = (fixture.root / "input/baseline.json" if field == "plan" else fixture.root / "preprocessing" /
                        (target.CONTRACT_FILENAME if field == "contract" else target.RECEIPT_FILENAME))
                    raw = json.loads(path.read_bytes())
                    raw["foreign"] = True
                    path.chmod(0o600)
                    path.write_bytes(canonical_json_bytes(raw) + b"\n")
                    with self.assertRaises(Exception):
                        fixture.load()

    def test_physically_resealed_foreign_front_workers_cannot_activate(self):
        with tempfile.TemporaryDirectory() as name:
            fixture = FileFixture(Path(name))
            with patch.object(target, "held_component_authority_v1", fixture.held):
                fixture.materialize()
                fixture.rows[0]["front_workers_by_route"]["damage:cpu"][0]["worker_id"] = "foreign-valid-worker"
                fixture.reseal_context()
                with self.assertRaisesRegex(target.ComponentGuardianPreprocessingContractV1Error, "front workers"):
                    fixture.load()

    def test_physically_resealed_foreign_native_descriptor_roles_cannot_activate(self):
        for role in ("calibration", "capability_manifest", "model_authority", "execution_code_closure",
            "policy_request_source", "policy_coordinator_source"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as name:
                fixture = FileFixture(Path(name))
                with patch.object(target, "held_component_authority_v1", fixture.held):
                    fixture.materialize()
                    fixture.rows[0]["descriptors"][role] = write(fixture.root / "foreign" / (role + ".json"), {"foreign_valid": role})
                    fixture.reseal_context()
                    with self.assertRaisesRegex(target.ComponentGuardianPreprocessingContractV1Error, "native descriptor"):
                        fixture.load()

    def test_legacy_kind_still_requires_original_image_patch_and_component_exact_four_projection(self):
        full = legacy_receipt()
        expected = expectations.runtime_expectations_from_preprocessing_receipt_v1(full)
        projection = copy.deepcopy(full["model_parity_refresh_authority"])
        del projection["image_identity_patch"]
        component = {"artifact_kind": target.RECEIPT_KIND, "worker_projection": projection,
            "policy_contract_sha256": full["policy_contract_sha256"],
            "preprocessing_contract_content_sha256": full["preprocessing_contract_content_sha256"]}
        self.assertEqual(expectations.runtime_expectations_from_preprocessing_receipt_v1(component), expected)
        full["model_parity_refresh_authority"] = projection
        with self.assertRaises(expectations.GuardianRuntimeExpectationsV1Error):
            expectations.runtime_expectations_from_preprocessing_receipt_v1(full)
        projection["image_identity_patch"] = {}
        with self.assertRaises(expectations.GuardianRuntimeExpectationsV1Error):
            expectations.runtime_expectations_from_preprocessing_receipt_v1(component)


class ComponentFrontTests(unittest.TestCase):
    def build(self, root):
        fixture = _BoundaryFixture(root)
        service = fixture.service
        headers = service._operational_context["headers_by_route"]
        second_run = "run-component-second"
        for header in headers.values():
            header["contexts"].append({"id": 1, "protocol": 0, "run_id": second_run,
                "arm_id": _native_wire_arm(second_run), "system": "gstreamer_custom", "policy": "cpu_only"})
            header["bindings"].append({"id": 1, "context": 1, "front_worker": 0})
        service._operational_context["output_dir"] = str(service._operational_context["output_dir"])
        context = payload_with_sha256_v1({"schema_version": 1, "artifact_kind": "vast_guardian_operational_capture_context_v1",
            "mode": DIAGNOSTIC_MODE, "headers_by_route": {":".join(route): header for route, header in headers.items()},
            "output_dir": service._operational_context["output_dir"]})
        operations = [{"operation_id": f"original-{i}", "arm_id": f"original-arm-{i}", "run_id": run,
            "system": "gstreamer_custom", "scenario": SHARED if i == 0 else BASELINE, "codec": "h264",
            "policy": "cpu_only", "deadline_ms": 100.0, "wire_arm_id": _native_wire_arm(run)}
            for i, run in enumerate((fixture.run_id, second_run))]
        authority = {"schema_version": 1, "artifact_kind": target.AUTHORITY_KIND, "allowed_operations": operations,
            **dict.fromkeys(target.AUTHORITY_SHA_FIELDS, "a" * 64)}
        authority.update({"capability_manifest_file_sha256": hashlib.sha256(canonical_json_bytes(fixture.manifest) + b"\n").hexdigest(),
            "preprocessing_contract_content_sha256": service.preprocessing_authority["preprocessing_contract_content_sha256"],
            "policy_contract_sha256": service.preprocessing_authority["policy_contract_sha256"],
            "operational_context_identity_sha256": context["sha256"],
            "operational_context_file_sha256": hashlib.sha256(canonical_json_bytes(context) + b"\n").hexdigest()})
        # Fixture authority is explicitly in-memory; service start/recorder/front
        # and accounting are real. It is not evidence of selected model custody.
        target.validate_component_operational_context_v1(authority, service._operational_context)
        service.preprocessing_authority = authority
        return fixture

    def test_active_context_binding_rejects_absent_or_changed_context(self):
        with tempfile.TemporaryDirectory() as name:
            fixture = self.build(Path(name))
            try:
                fixture.start()
                with self.assertRaises(target.ComponentGuardianPreprocessingContractV1Error):
                    target.validate_component_operational_context_v1(fixture.service.preprocessing_authority, None)
                changed = copy.deepcopy(fixture.service._operational_context)
                changed["headers_by_route"][("damage", "cpu")]["contexts"][0]["system"] = "openvino_gva"
                with self.assertRaises(target.ComponentGuardianPreprocessingContractV1Error):
                    target.validate_component_operational_context_v1(fixture.service.preprocessing_authority, changed)
                old = fixture.service
                before = len(os.listdir("/proc/self/fd"))
                invalid_runtime = Path(name) / "not-created-runtime"
                with self.assertRaisesRegex(SidecarError, "active operational capture"):
                    GStreamerAnalyticsProductionService(execution_config=old.execution_config,
                        binding_set_dir=old.binding_set_dir, policy_capability_manifest=old.policy_capability_manifest,
                        preprocessing_contract=old.preprocessing_contract, preprocessing_authority=old.preprocessing_authority,
                        production_runtime_expectations=old.production_runtime_expectations,
                        runtime_dir=invalid_runtime, front_socket=invalid_runtime / "analytics.sock",
                        evidence_root=Path(name) / "not-created-evidence", process_factory=fixture.factory,
                        max_connections=old.max_connections, max_requests_per_connection=old.max_requests_per_connection,
                        max_total_requests=old.max_total_requests)
                self.assertEqual(len(os.listdir("/proc/self/fd")), before)
                self.assertFalse(invalid_runtime.exists())
            finally:
                fixture.service.stop()

    def test_real_memfd_front_permits_selected_gstreamer_and_records_original_calls(self):
        with tempfile.TemporaryDirectory() as name:
            fixture = self.build(Path(name))
            try:
                fixture.start()
                fixture.complete(2, "damage")
                self.assertEqual(fixture.backend_bridge.execution_calls, 1)
            finally:
                fixture.service.stop()

    def test_real_memfd_front_foreign_run_or_gva_implementation_or_resource_never_executes(self):
        for negative in ("run", "implementation", "resource", "stream"):
            with self.subTest(negative=negative), tempfile.TemporaryDirectory() as name:
                fixture = self.build(Path(name))
                try:
                    fixture.start()
                    resource = "gpu" if negative == "resource" else "cpu"
                    binding = fixture.manifest["systems"]["openvino_gva" if negative == "implementation" else "gstreamer_custom"]["branches"]["damage"][resource]
                    payload = b"\x01\x02\x03"
                    request = {"schema_version": 1, "message_type": "analytics_execute", "request_id": "a" * 64,
                        "run_id": "foreign" if negative == "run" else fixture.run_id,
                        "arm_id": _native_wire_arm(fixture.run_id), "gstreamer_worker_id": fixture.worker_id,
                        "frame": {"input_frame_key": "dataset:0:source:2:2000", "stream_id": 1 if negative == "stream" else 0,
                            "frame_id": 2, "transport_pts_ns": 2000, "branch": "damage"},
                        "decision": {"decision_id": "b" * 64, "decision_seq": 1, "selected_resource": resource,
                            "selected_implementation_id": binding["implementation_id"],
                            "emitter_id": binding["native_evidence"]["emitter_id"], "emitter_sha256": binding["native_evidence"]["emitter_sha256"]},
                        "deadline_monotonic_ns": time.monotonic_ns() + 60_000_000_000,
                        "payload": {"kind": "raw_gstreamer_frame", "format": "BGR", "width": 1, "height": 1, "stride": 3,
                            "byte_length": 3, "sha256": hashlib.sha256(payload).hexdigest(),
                            "preprocessing_contract_sha256": fixture.service.preprocessing_authority["preprocessing_contract_content_sha256"]}}
                    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                    client.settimeout(3)
                    fd = create_sealed_memfd("component-negative", payload)
                    try:
                        client.connect(str(fixture.service.front_socket))
                        send_packet(client, request, fds=(fd,))
                        with self.assertRaises((PeerClosed, ConnectionResetError)):
                            receive_packet(client, expected_fds=0)
                    finally:
                        close_fds((fd,)); client.close()
                    self.assertEqual(fixture.backend_bridge.execution_calls, 0)
                    until = time.monotonic() + 1
                    while fixture.service._production_counters.snapshot()["requests_failed"] == 0 and time.monotonic() < until:
                        time.sleep(0.001)
                    self.assertEqual(fixture.service._production_counters.snapshot()["requests_failed"], 1)
                finally:
                    fixture.service.stop()


if __name__ == "__main__":
    unittest.main()
