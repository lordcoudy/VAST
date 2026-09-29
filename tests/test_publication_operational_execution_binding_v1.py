"""Local 37-original cold binding seam; no physical benchmark acceptance.

Builder, held pins, distinct original coordinators, native/proxy seqpacket
transports, sealed memfd, guardian recorder and cold multiset are actual code.
Inference is the existing local backend fixture. Process/container validators
and the stock measured CSV cohort adapter are explicitly mocked; the latter
returns only maps obtained from actual coordinator promotion. This fixture
does not claim stock graph/reset/resource or original process acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from analytics_execution_endpoint import expected_capability_from_binding_and_probe, terminal_detector_identity
from analytics_execution_protocol import canonical_json_bytes, canonical_sha256, close_fds, create_sealed_memfd, receive_packet, send_packet
from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator
from checkpoint_deepstream_protocol_bridge import analytics_backend_identity
from checkpoint_runtime_plan import validate_checkpoint_runtime_plan
from publication_operational_capture_plan_v1 import build_operational_capture_plan_v1, held_operational_capture_plan_v1, QUALIFICATION_MODE
from publication_operational_request_domain_v1 import payload_with_sha256_v1
import publication_policy_qualification_execution_closure_v1 as closure
from tests.test_publication_operational_boundary_v1 import _BoundaryFixture, _descriptor, _native_request_identity, _write_json
from tests.test_checkpoint_gstreamer_analytics_sidecar import _binding, _probe, _worker_request
from tests.test_checkpoint_native_policy_runtime import calibration

BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
NATIVE = {"gstreamer_custom", "openvino_gva"}


def _relative(root, descriptor):
    return {**descriptor, "path": Path(descriptor["path"]).relative_to(root).as_posix()}


def _sealed_file(path, value, key="sha256"):
    unsigned = {name: item for name, item in value.items() if name != key}
    value = {**unsigned, key: hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()}
    return _write_json(path, value), value


class _OriginalBindingFixture:
    def __init__(self, root):
        self.root = root
        self.boundary = _BoundaryFixture(root)
        # The stock parser reads the original seven-field config file, then
        # adds its normalized identity. Keep the physical source in that form.
        config_source = Path(self.boundary.inputs["execution_config"]["path"])
        config_source.write_bytes(canonical_json_bytes(
            {key: value for key, value in self.boundary.config.items() if key != "identity"}) + b"\n")
        self.boundary.inputs["execution_config"] = _descriptor(config_source)
        self.maps = {}
        self.outputs = []
        self.runtime_bundles = {}
        # The real stock engine is external to project_root. This byte pin
        # models only the explicitly mocked original-process authority seam.
        self.engine_path = root.parent / (root.name + ".fixture-only-original-engine")
        self.engine_path.write_bytes(b"fixture-only original engine bytes\n")
        self.engine_ref = _descriptor(self.engine_path)
        planner_module = importlib.import_module("tests.test_publication_operational_capture_plan_v1")
        planner_module.CapturePlanTests.setUpClass()
        planner = planner_module.CapturePlanTests("runTest")
        planner.root = root
        planner.calls = []
        (root / "outputs").mkdir()
        planner.guardian = {role: self.boundary.inputs[role] for role in
            ("capability_manifest", "execution_config", "execution_code_closure", "model_authority")}
        for role, source in (
            ("native_protocol_source", ROOT / "deploy/native_gst_probe/vast_native_gst_probe.cpp"),
            ("proxy_protocol_source", ROOT / "scripts/checkpoint_deepstream_protocol_bridge.py")):
            path = root / "inputs" / source.name
            path.write_bytes(source.read_bytes())
            planner.guardian[role] = _descriptor(path)
        self.capabilities = {(branch, resource): expected_capability_from_binding_and_probe(
            binding=_binding(branch, resource, self.boundary.config),
            runtime_probe=_probe(resource, self.boundary.config), resource=resource)
            for branch in BRANCHES for resource in ("cpu", "gpu")}
        self.rows = planner.qualification_operations()
        self.calibrations = {system: calibration(self.boundary.manifest, system=system)
            for system in {row["system"] for row in self.rows}}
        calibration_refs = {system: _write_json(root / "inputs" / ("calibration-" + system + ".json"), value)
            for system, value in self.calibrations.items()}
        for row in self.rows:
            row["descriptors"].update({
                **{role: self.boundary.inputs[role] for role in
                    ("capability_manifest", "execution_code_closure", "model_authority")},
                "calibration": calibration_refs[row["system"]],
                "policy_request_source": planner.guardian["native_protocol_source"],
                "policy_coordinator_source": self._copy_source("checkpoint_native_policy_runtime.py"),
            })
            if row["system"] not in NATIVE:
                for route, workers in row["front_workers_by_route"].items():
                    worker_id = self.capabilities[tuple(route.split(":"))]["worker_id"]
                    for worker in workers:
                        worker["worker_id"] = worker_id
            directory = root / "outputs" / row["operation_id"]
            reservation = {"measurement_dir": str(directory),
                "native_domain": str(root / "operational" / row["operation_id"] / "native_operational_requests.v1.jsonl"),
                "process_receipt": str(root / "process-fixtures" / row["operation_id"] / "process.json"),
                "container_receipt": str(root / "process-fixtures" / row["operation_id"] / "container.json")}
            image = {"image_id": "sha256:" + "a" * 64,
                "repository_digest": "vast/local-binding-fixture@sha256:" + "b" * 64,
                "inspect_projection_sha256": "c" * 64, "base_image_id": "sha256:" + "d" * 64}
            original = {"schema_version": 1, "artifact_kind": "vast_original_native_operation_input_v1",
                "operation": {key: value for key, value in row.items() if key != "original_operation"},
                "container_image": image, "outputs": reservation}
            # Replace the unsealed planning fixture before physical plan freeze.
            Path(row["original_operation"]["path"]).unlink()
            row["original_operation"], _ = _sealed_file(Path(row["original_operation"]["path"]), original)

        def original_validator(row, assets):
            original = json.loads(assets[row["original_operation"]["path"]])
            if original["operation"] != {key: value for key, value in row.items() if key != "original_operation"}:
                raise AssertionError("local original operation changed")
            plan = json.loads(assets[row["descriptors"]["source_plan"]["path"]])
            validate_checkpoint_runtime_plan(plan)
            if plan["system"] != row["system"] or plan["scenario"] != row["scenario"]:
                raise AssertionError("local stock source plan changed")

        self.plan = build_operational_capture_plan_v1(project_root=root, output_dir=root / "outputs/capture-plan",
            mode=QUALIFICATION_MODE, operations=self.rows, guardian_descriptors=planner.guardian,
            guardian_output_dir=root / "outputs/guardian-operational", original_operation_validator=original_validator)
        with held_operational_capture_plan_v1(project_root=root,
                index_path=Path(self.plan["descriptor"]["path"]), expected_descriptor=self.plan["descriptor"]) as held:
            self.contexts = copy.deepcopy(held["native_contexts_by_id"])
            self.context_refs = {row["operation_id"]: row["descriptor"] for row in held["index"]["native_contexts"]}
            self.boundary.service._operational_context = {
                "headers_by_route": {tuple(route.split(":")): copy.deepcopy(header)
                    for route, header in held["guardian_context"]["headers_by_route"].items()},
                "output_dir": Path(held["guardian_context"]["output_dir"])}
        probes = {}
        for resource in ("cpu", "gpu"):
            probes[resource] = _relative(root, _write_json(root / "inputs" / ("probe-" + resource + ".json"),
                _probe(resource, self.boundary.config)))
            probes[resource]["worker_implementation_sha256"] = _probe(resource, self.boundary.config)["worker_implementation_sha256"]
        self.preprocessing = {"candidate_manifest": _relative(root, self.boundary.inputs["capability_manifest"]),
            "model_parity_refresh_authority": {
                "execution_config": _relative(root, self.boundary.inputs["execution_config"]),
                "runtime_probes": probes,
                "binding_set": {"index": _relative(root, _descriptor(root / "bindings/index.json")),
                    "bindings": {f"{branch}:{resource}": _relative(root, _descriptor(
                        root / "bindings" / (branch + "." + self.capabilities[(branch, resource)]["engine"] + ".json")))
                        for branch in BRANCHES for resource in ("cpu", "gpu")}}}}
        self.runtime = {"receipt": {"path": "runtime-bundles/materialization.json"}}
        (root / "runtime-bundles").mkdir()

    def _copy_source(self, name):
        path = self.root / "inputs" / name
        if not path.exists():
            path.write_bytes((ROOT / "scripts" / name).read_bytes())
        return _descriptor(path)

    def execute(self):
        self.boundary.start()
        try:
            for row in self.rows:
                original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
                directory = Path(original["outputs"]["measurement_dir"])
                context = self.contexts[row["operation_id"]]
                # Match the original native GStreamer producer constructor;
                # SDK coordinators use the original trial arm directly.
                reset_arm = (f"{row['run_id']}:{row['scenario']}:{row['codec']}:{row['policy']}:{float(row['deadline_ms'])}"
                    if row["system"] in NATIVE else row["arm_id"])
                coordinator = NativePolicyRuntimeCoordinator(
                    **{key: row[key] for key in ("run_id", "system", "scenario", "codec", "policy", "deadline_ms")},
                    arm_id=reset_arm,
                    branches=BRANCHES, capability_manifest=self.boundary.manifest,
                    calibration=self.calibrations[row["system"]],
                    operational_context={"header": context["native_header"],
                        "output_dir": Path(original["outputs"]["native_domain"]).parent})
                canonical = {}
                for frame in (1, 2, 3):
                    for branch in BRANCHES:
                        request = self.complete(row, coordinator, frame, branch)
                        if frame == 2:
                            canonical[request["input_frame_key"]] = {
                                "trace_id": row["run_id"] + ":canonical:0:2",
                                "stream_id": 0, "frame_id": 2}
                promoted = coordinator.promote(directory, canonical_frames=canonical)
                self.maps[row["operation_id"]] = canonical
                # This CSV is a local mapping placeholder; the stock adapter is
                # explicitly mocked below, never called or claimed accepted.
                ledger = directory / "ingress_ledger.csv"
                ledger.write_text("fixture_only,input_frame_key,trace_id,stream_id,frame_id\n" +
                    "".join(f"true,{key},{value['trace_id']},0,2\n" for key, value in canonical.items()), encoding="ascii")
                process = _write_json(Path(original["outputs"]["process_receipt"]), {"fixture_only": True})
                container = _write_json(Path(original["outputs"]["container_receipt"]), {"fixture_only": True})
                self.outputs.append({"operation_id": row["operation_id"],
                    "native_domain": promoted["operational_domain"],
                    "measurement_decisions": _descriptor(directory / "publication_policy_decisions.jsonl"),
                    "accepted_ingress": _descriptor(ledger), "process_receipt": process, "container_receipt": container})
                if row["phase"] == "qualification_cell":
                    context_ref = _relative(self.root, self.context_refs[row["operation_id"]])
                    contract = {"operational_capture": {"mode": QUALIFICATION_MODE, "output_dir": "request_output_dir_sibling_v1"},
                        "container_image": original["container_image"],
                        "files": {"operational_request_context": context_ref,
                            "container_engine": copy.deepcopy(self.engine_ref),
                            "policy_capability_manifest": _relative(self.root, row["descriptors"]["capability_manifest"]),
                            "policy_calibration": _relative(self.root, row["descriptors"]["calibration"])}}
                    doc = {"runtime_inputs": {"dataset": {row["system"] + "_publication_runtime_v3": contract}}}
                    ref, doc = _sealed_file(self.root / "runtime-bundles" / (row["operation_id"] + ".json"),
                                           doc, "bundle_sha256")
                    self.runtime_bundles[row["arm_id"]] = {
                        "path": Path(ref["path"]).name, "size_bytes": ref["size_bytes"],
                        "sha256": ref["sha256"], "bundle_sha256": doc["bundle_sha256"]}
        finally:
            self.boundary.stop()
        self.binding, _ = _sealed_file(self.root / "execution-binding.json", {
            "schema_version": 1, "artifact_kind": "vast_original_operational_execution_binding_v1",
            "mode": QUALIFICATION_MODE, "capture_plan": self.plan["descriptor"],
            "guardian_companion": self.boundary.service.operational_group, "operation_outputs": self.outputs})
        self.pilot = {"guardian_request_workload": {"cells": [
            {"arm_id": row["arm_id"], "request_count": 4}
            for row in self.rows if row["phase"] == "qualification_cell"]}}

    def complete(self, row, coordinator, frame, branch):
        resource = row["policy"].removesuffix("_only")
        worker = next(item["worker_id"] for item in row["front_workers_by_route"][branch + ":" + resource]
                      if item["stream_id"] == 0)
        arrival, finish = {1: (900.0, 935.0), 2: (1100.0, 2210.0), 3: (2099.5, 2185.0)}[frame]
        request = {"schema_version": 1, "message_type": "decision_request",
            "run_id": row["run_id"], "worker_id": worker,
            "input_frame_key": f"dataset:0:source:{frame}:1000", "trace_id": row["run_id"] + f":0:{frame}",
            "stream_id": 0, "frame_id": frame, "transport_pts_ns": frame * 1000, "branch": branch,
            "arrival_ms": arrival, "decision_time_ms": arrival + 20.0,
            "feature_observed_timestamp_ms": arrival + 10.0, "queue_depths": {"cpu": 0, "gpu": 0}}
        decision = coordinator.handle_message(worker, request)
        binding = self.boundary.manifest["systems"][row["system"]]["branches"][branch][resource]
        path = {"schema_version": 1, "message_type": "path_enter", "run_id": row["run_id"],
            "worker_id": worker, "decision_id": decision["decision_id"], "input_frame_key": request["input_frame_key"],
            "branch": branch, "transport_pts_ns": request["transport_pts_ns"], "selected_resource": resource,
            "implementation_id": binding["implementation_id"], "emitter_id": binding["native_evidence"]["emitter_id"],
            "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
            "event_id": f"local-original-{branch}-{frame}", "timestamp_ms": arrival + 21.0}
        coordinator.handle_message(worker, path)
        capability = self.capabilities[(branch, resource)]
        client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        client.settimeout(5.0)
        payload = b"\x01\x02\x03" if row["system"] in NATIVE else b"\x00\x00\x00\x00"
        descriptor = create_sealed_memfd("original-37-local-frame", payload)
        try:
            client.connect(str(self.boundary.service.front_socket))
            if row["system"] in NATIVE:
                front = {"schema_version": 1, "message_type": "analytics_execute",
                    "request_id": _native_request_identity(request, decision), "run_id": row["run_id"],
                    "arm_id": hashlib.sha256(("analytics_execution_arm_v1\n" + row["run_id"] + "\n" +
                        row["policy"] + "\n100.000000").encode()).hexdigest(),
                    "gstreamer_worker_id": worker,
                    "frame": {key: request[key] for key in ("input_frame_key", "stream_id", "frame_id", "transport_pts_ns", "branch")},
                    "decision": {"decision_id": decision["decision_id"], "decision_seq": decision["decision_seq"],
                        "selected_resource": resource, "selected_implementation_id": binding["implementation_id"],
                        "emitter_id": binding["native_evidence"]["emitter_id"], "emitter_sha256": binding["native_evidence"]["emitter_sha256"]},
                    "deadline_monotonic_ns": time.monotonic_ns() + 60_000_000_000,
                    "payload": {"kind": "raw_gstreamer_frame", "format": "BGR", "width": 1, "height": 1,
                        "stride": 3, "byte_length": 3, "sha256": hashlib.sha256(payload).hexdigest(),
                        "preprocessing_contract_sha256": capability["preprocessing_contract_sha256"]}}
                send_packet(client, front, fds=(descriptor,))
                response, output_fds = receive_packet(client, expected_fds=0)
                status = response["terminal_status"]
            else:
                send_packet(client, {"schema_version": 1, "message_type": "hello",
                    "expected_capability_sha256": canonical_sha256(capability), "nonce": "local-original-37"})
                acknowledgement, hello_fds = receive_packet(client, expected_fds=0)
                close_fds(hello_fds)
                if acknowledgement["capability"] != capability:
                    raise AssertionError("actual proxy handshake changed capability")
                front = _worker_request(capability, payload)
                material = f"{decision['decision_id']}\0{request['input_frame_key']}\0{branch}\0{worker}"
                front.update(run_id=row["run_id"], arm_id=row["arm_id"],
                    request_id="deepstream-" + hashlib.sha256(material.encode()).hexdigest()[:48])
                front["frame"] = {key: request[key] for key in ("input_frame_key", "stream_id", "frame_id", "transport_pts_ns", "branch")}
                send_packet(client, front, fds=(descriptor,))
                response, output_fds = receive_packet(client, expected_fds=1)
                status = response["terminal"]["status"]
            close_fds(output_fds)
            if response["request_id"] != front["request_id"]:
                raise AssertionError("actual front changed original request identity")
        finally:
            close_fds((descriptor,))
            client.close()
        terminal = {"schema_version": 1, "message_type": "terminal", "run_id": row["run_id"],
            "worker_id": worker, "decision_id": decision["decision_id"], "input_frame_key": request["input_frame_key"],
            "branch": branch, "transport_pts_ns": request["transport_pts_ns"], "selected_resource": resource,
            "terminal_status": status, "terminal_timestamp_ms": finish,
            "actual_service_ms": finish - path["timestamp_ms"],
            "detector": terminal_detector_identity(capability), "backend": analytics_backend_identity(capability)}
        coordinator.handle_message(worker, terminal)
        return request

    def reconcile(self, *, during_cohort=None, validator_result=None, **changes):
        process_module = importlib.import_module("publication_operational_process_custody_v1")
        container_module = importlib.import_module("publication_operational_container_custody_v1")
        args = dict(project_root=self.root, binding_path=Path(self.binding["path"]),
            guardian_authority_path=self.boundary.service.evidence.authority_path,
            preprocessing_receipt=self.preprocessing, lifecycle_counters=self.boundary.lifecycle["counters"],
            scratch_root=self.root / "binding-cold-scratch", expected_mode=QUALIFICATION_MODE,
            pilot_execution=self.pilot, runtime=self.runtime, runtime_bundles=self.runtime_bundles)
        args.update(changes)
        mapped = []
        def cohort(**kwargs):
            identity = kwargs["operation"]["operation_id"]
            mapped.append(identity)
            if kwargs["ingress_descriptor"] != next(row["accepted_ingress"] for row in self.outputs if row["operation_id"] == identity):
                raise AssertionError("mocked cohort received foreign physical ingress")
            if during_cohort is not None and len(mapped) == 1:
                during_cohort()
            return copy.deepcopy(self.maps[identity])
        fixture_result = {"fixture_only": True, "validated_inputs": [],
            "measurement": {"launch": {"engine": copy.deepcopy(self.engine_ref)}}}
        with mock.patch.object(closure, "_operational_measured_ingress_v1", side_effect=cohort), \
                mock.patch.object(process_module, "original_process_validator_v1",
                    return_value=fixture_result if validator_result is None else
                        {**fixture_result, **validator_result}) as process, \
                mock.patch.object(container_module, "original_container_validator_v1", return_value=fixture_result) as container:
            result = closure.reconcile_operational_capture_binding_v1(**args)
        return result, mapped, process.call_count, container.call_count


@unittest.skipUnless(os.name == "posix" and hasattr(os, "memfd_create"), "actual Linux transport is required")
class OperationalExecutionBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="vast-original-37-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.fixture = _OriginalBindingFixture(Path(cls.temporary.name))
        cls.addClassCleanup(cls.fixture.engine_path.unlink)
        cls.fixture.execute()

    def test_actual_37_originals_join_32_selected_cells_and_all_three_phases(self):
        result, mapped, processes, containers = self.fixture.reconcile()
        self.assertEqual(result["original_operation_count"], 37)
        self.assertEqual(result["qualification_cell_count"], 32)
        self.assertFalse(result["publication_authority"])
        self.assertEqual(result["reconciliation"]["request_count"], 444)
        self.assertEqual(result["reconciliation"]["measurement_request_count"], 148)
        self.assertEqual(result["reconciliation"]["excluded_request_count"], 296)
        self.assertEqual(result["reconciliation"]["requests_by_worker"],
                         self.fixture.boundary.lifecycle["counters"]["requests_by_worker"])
        self.assertEqual(mapped, [row["operation_id"] for row in self.fixture.rows])
        self.assertEqual((processes, containers), (37, 37))

    def test_same_count_foreign_preprocessing_candidate_cannot_supply_original_authority(self):
        foreign = copy.deepcopy(self.fixture.preprocessing)
        foreign["candidate_manifest"] = dict(foreign["candidate_manifest"], sha256="f" * 64)
        with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error, "candidate differs"):
            self.fixture.reconcile(preprocessing_receipt=foreign)

    def test_same_count_32_cell_workload_substitution_is_rejected(self):
        pilot = copy.deepcopy(self.fixture.pilot)
        pilot["guardian_request_workload"]["cells"][0]["request_count"] = 5
        pilot["guardian_request_workload"]["cells"][1]["request_count"] = 3
        with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error, "32-cell measured subset"):
            self.fixture.reconcile(pilot_execution=pilot)

    def test_physically_resealed_runtime_bundle_cannot_detach_original_capture_or_authority(self):
        selected = next(row for row in self.fixture.rows if row["phase"] == "qualification_cell")
        expected_errors = {"context": "substituted the original capture context",
            "activation": "exact original capture activation", "image": "image differs",
            "capability_manifest": "capability_manifest differs", "calibration": "calibration differs"}
        for mutation, expected in expected_errors.items():
            with self.subTest(mutation=mutation):
                directory = Path(tempfile.mkdtemp(prefix="foreign-bundle-", dir=self.fixture.root))
                self.addCleanup(shutil.rmtree, directory)
                source = self.fixture.root / "runtime-bundles"
                for path in source.iterdir():
                    shutil.copyfile(path, directory / path.name)
                records = copy.deepcopy(self.fixture.runtime_bundles)
                record = records[selected["arm_id"]]
                path = directory / record["path"]
                document = json.loads(path.read_bytes())
                contract = document["runtime_inputs"]["dataset"][selected["system"] + "_publication_runtime_v3"]
                if mutation == "activation":
                    contract["operational_capture"]["output_dir"] = "/opt/vast/foreign"
                elif mutation == "image":
                    contract["container_image"]["image_id"] = "sha256:" + "e" * 64
                else:
                    role = {"context": "operational_request_context",
                        "capability_manifest": "policy_capability_manifest",
                        "calibration": "policy_calibration"}[mutation]
                    original = self.fixture.root / contract["files"][role]["path"]
                    foreign = directory / ("same-bytes-foreign-" + mutation + ".json")
                    shutil.copyfile(original, foreign)
                    contract["files"][role] = _relative(self.fixture.root, _descriptor(foreign))
                path.unlink()
                descriptor, document = _sealed_file(path, document, "bundle_sha256")
                record.update(size_bytes=descriptor["size_bytes"], sha256=descriptor["sha256"],
                              bundle_sha256=document["bundle_sha256"])
                runtime = {"receipt": {"path": (directory / "materialization.json").relative_to(self.fixture.root).as_posix()}}
                with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error, expected):
                    self.fixture.reconcile(runtime=runtime, runtime_bundles=records)

    def test_resealed_equal_count_original_operation_substitution_is_rejected(self):
        value = json.loads(Path(self.fixture.binding["path"]).read_bytes())
        value["operation_outputs"][-1] = copy.deepcopy(value["operation_outputs"][0])
        path = self.fixture.root / "same-count-foreign-execution-binding.json"
        _sealed_file(path, value)
        self.addCleanup(path.unlink)
        with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error, "producing invocation"):
            self.fixture.reconcile(binding_path=path)

    def test_original_binding_drift_during_full_cold_validation_is_rejected(self):
        path = Path(self.fixture.binding["path"])
        original = path.read_bytes()
        try:
            with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                    "binding|document|changed|drift"):
                self.fixture.reconcile(during_cohort=lambda: path.write_bytes(original + b"\n"))
        finally:
            path.write_bytes(original)

    def test_same_bytes_original_binding_replacement_is_not_held_custody(self):
        path = Path(self.fixture.binding["path"])
        saved = path.with_name("temporarily-held-original-binding.json")
        original = path.read_bytes()
        def replace():
            path.rename(saved)
            path.write_bytes(original)
        try:
            with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                    "binding|document|changed|drift|identity"):
                self.fixture.reconcile(during_cohort=replace)
        finally:
            if saved.exists():
                path.unlink()
                saved.rename(path)

    def _physical_leaf_witness(self, path):
        info = path.lstat()
        return {"descriptor": _descriptor(path), "epoch": [
            info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns]}

    def test_original_validator_leaf_drift_after_validator_return_is_rejected(self):
        # The original process/container validators are the explicit mocked
        # seam. Their physical witnesses must still remain held by the real
        # outer caller through the entire unmocked reconciliation.
        path = self.fixture.root / "fixture-original-validator-output.bin"
        path.write_bytes(b"original physical metadata\n")
        self.addCleanup(path.unlink)
        result = {"validated_inputs": [self._physical_leaf_witness(path)]}
        with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                "changed|drift|identity"):
            self.fixture.reconcile(validator_result=result,
                during_cohort=lambda: path.write_bytes(b"substituted physical metadata\n"))

    def test_same_bytes_original_validator_leaf_replacement_is_rejected(self):
        path = self.fixture.root / "fixture-original-validator-aba.bin"
        saved = path.with_name("temporarily-held-original-validator-aba.bin")
        path.write_bytes(b"original physical metadata\n")
        original = path.read_bytes()
        result = {"validated_inputs": [self._physical_leaf_witness(path)]}
        def replace():
            path.rename(saved)
            path.write_bytes(original)
        try:
            with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                    "changed|drift|identity"):
                self.fixture.reconcile(validator_result=result, during_cohort=replace)
        finally:
            if saved.exists():
                path.unlink()
                saved.rename(path)
            path.unlink()

    def test_original_validator_malformed_epoch_is_rejected(self):
        path = self.fixture.root / "fixture-original-validator-malformed.bin"
        path.write_bytes(b"original physical metadata\n")
        self.addCleanup(path.unlink)
        witness = self._physical_leaf_witness(path)
        witness["epoch"].pop()
        with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                "epoch is malformed"):
            self.fixture.reconcile(validator_result={"validated_inputs": [witness]})

    def test_original_validator_empty_output_witness_is_held(self):
        path = self.fixture.root / "fixture-original-validator-empty.stdout"
        path.write_bytes(b"")
        self.addCleanup(path.unlink)
        result, _, _, _ = self.fixture.reconcile(
            validator_result={"validated_inputs": [self._physical_leaf_witness(path)]})
        self.assertEqual(result["reconciliation"]["request_count"], 444)

    def test_original_validator_external_engine_witness_is_held(self):
        # Stock Docker is external to project_root. This local file exercises
        # only retention of an already-validator-proved engine witness; the
        # explicit process seam does not claim a real engine or container.
        result, _, _, _ = self.fixture.reconcile(
            validator_result={"validated_inputs": [self._physical_leaf_witness(self.fixture.engine_path)]})
        self.assertEqual(result["reconciliation"]["request_count"], 444)

    def test_foreign_external_engine_cannot_replace_original_runtime_bundle_authority(self):
        with tempfile.TemporaryDirectory(prefix="vast-original-foreign-engine-") as directory:
            path = Path(directory) / "fixture-only-foreign-engine"
            path.write_bytes(self.fixture.engine_path.read_bytes())
            witness = self._physical_leaf_witness(path)
            for mutation in ("witness", "launch"):
                with self.subTest(mutation=mutation):
                    result = ({"validated_inputs": [witness]} if mutation == "witness" else
                        {"validated_inputs": [self._physical_leaf_witness(self.fixture.engine_path)],
                         "measurement": {"launch": {"engine": _descriptor(path)}}})
                    with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                            "engine|external|escaped|foreign"):
                        self.fixture.reconcile(validator_result=result)

    def test_original_validator_ancestor_alias_after_return_is_rejected(self):
        directory = self.fixture.root / "fixture-original-validator-ancestor"
        saved = directory.with_name("temporarily-held-validator-ancestor")
        directory.mkdir()
        path = directory / "original.bin"
        path.write_bytes(b"original physical metadata\n")
        result = {"validated_inputs": [self._physical_leaf_witness(path)]}
        def alias():
            directory.rename(saved)
            directory.symlink_to(saved, target_is_directory=True)
        try:
            with self.assertRaisesRegex(closure.QualificationExecutionClosureV1Error,
                    "changed|drift|identity|symlink|alias"):
                self.fixture.reconcile(validator_result=result, during_cohort=alias)
        finally:
            if directory.is_symlink():
                directory.unlink()
                saved.rename(directory)
            shutil.rmtree(directory)
