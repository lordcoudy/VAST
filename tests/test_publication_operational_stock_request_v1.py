"""Physical stock request seam; fixture authority is never image acceptance."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tests import test_publication_operational_stock_operations_v1 as seam
import publication_operational_stock_operations_v1 as target
import publication_policy_qualification_pilot_executor_v2 as pilot
from publication_operational_capture_plan_v1 import held_operational_capture_plan_v1
from publication_operational_request_domain_v1 import canonical_json_v1
from publication_operational_runtime_context_v1 import CAPTURE_ROLE, CAPTURE_KEY, OUTPUT_PATH_RULE
from checkpoint_publication_launcher_adapter_v3 import NativePublicationRequestV3


@unittest.skipUnless(sys.platform.startswith("linux"), "actual external engine and Unix socket pins require Linux")
class HeldStockRequestTests(unittest.TestCase):
    MODE = target.DIAGNOSTIC_MODE

    def select_operation(self, held):
        return next(iter(held["operations_by_id"].values()))

    def declared_context(self, descriptor):
        return descriptor

    def setUp(self):
        self.fixture = seam.PhysicalStockOperationPlanningSeamTests(
            "test_stock_native_pair_selection_preserves_two_distinct_contexts_and_mode")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.plan = self.fixture.prepare(self.MODE, "cpu" if self.MODE == target.DIAGNOSTIC_MODE else None)
        with held_operational_capture_plan_v1(project_root=self.root, index_path=self.plan["descriptor"]["path"]) as held:
            self.operations = list(held["operations_by_id"].values())
            self.native_contexts = {row["operation_id"]: row["descriptor"] for row in held["index"]["native_contexts"]}
            self.operation = self.select_operation(held)
            # The stock bundle of this arm declares its runtime-selected context.
            self.context = held["runtime_contexts_by_arm"][self.operation["arm_id"]]["descriptor"]
            self.own_context = self.native_contexts[self.operation["operation_id"]]
        self.cell = next(c for c in pilot.qualification_pilot_cells_v2() if c.arm_id == self.operation["arm_id"])
        self.original = json.loads(Path(self.operation["original_operation"]["path"]).read_bytes())
        self.inputs = SimpleNamespace(root=self.root)
        for field in ("candidate_index", "candidate_receipt", "bootstrap_mapping", "bootstrap_receipt", "transaction_receipt"):
            descriptor = self.fixture.write(field + ".json", {"fixture_authority_only": True, "role": field})
            setattr(self.inputs, field, pilot._pin_json(self.root, descriptor["path"], label="fixture authority " + field))
        self.inputs.candidate_manifest = pilot._pin_json(self.root, self.fixture.candidate["path"], label="fixture candidate")
        self.inputs.calibrations = {self.cell.system: pilot._pin_json(self.root,
            self.operation["descriptors"]["calibration"]["path"], label="fixture calibration")}
        collector = self.fixture.write("collector.json", {"fixture_authority_only": True})
        self.inputs.hardware_resource_collector = pilot._pin_file(self.root, collector["path"], label="fixture collector")
        self.inputs.pins = tuple(getattr(self.inputs, key) for key in (
            "candidate_index", "candidate_manifest", "candidate_receipt", "bootstrap_mapping", "bootstrap_receipt", "transaction_receipt"))
        self.inputs.pins += (*self.inputs.calibrations.values(), self.inputs.hardware_resource_collector)
        self.preprocessing_receipt = self.fixture.write("preprocessing-receipt.json", {
            "candidate_manifest": self.fixture.candidate,
            "candidate_receipt": self.descriptor(self.inputs.candidate_receipt)})
        other = {}
        for role in ("preprocessing_contract", "guardian_service_authority", "runtime_materialization_receipt"):
            ref = self.fixture.write(role + ".json", {"fixture_authority_only": True, "role": role})
            other[role] = pilot._pin_json(self.root, ref["path"], label="fixture " + role)
        other["preprocessing_receipt"] = pilot._pin_json(self.root, self.preprocessing_receipt["path"], label="fixture preprocessing")
        self.operational = SimpleNamespace(**other)
        self.operational.pins = tuple(other.values())
        engine = Path(sys.executable).resolve()
        raw = engine.read_bytes()
        self.engine = {"path": str(engine), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        info = self.fixture.socket_path.lstat()
        engine_socket = {"path": str(self.fixture.socket_path), "device": info.st_dev, "inode": info.st_ino,
                         "owner_uid": info.st_uid, "owner_gid": info.st_gid}
        self.analytics = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.addCleanup(self.analytics.close)
        path = self.root / "analytics.sock"
        self.analytics.bind(str(path))
        info = path.lstat()
        analytics_socket = {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
                            "owner_uid": info.st_uid, "owner_gid": info.st_gid}
        self.contract = {
            "defer_full_resource_acceptance": True,
            "evidence_mapping": {name: name for name in pilot.CHILD_EVIDENCE_FILES},
            "files": {"policy_capability_manifest": self.descriptor(self.inputs.candidate_manifest),
                      "policy_calibration": self.descriptor(self.inputs.calibrations[self.cell.system]),
                      "container_engine": self.engine, CAPTURE_ROLE: self.declared_context(self.context)},
            "container_image": self.original["container_image"],
            "container_engine_socket": engine_socket,
            "endpoint_sockets": {"analytics_execution": analytics_socket},
            CAPTURE_KEY: {"mode": self.MODE, "output_dir": OUTPUT_PATH_RULE}}
        self.bundle_path = self.root / "runtime-bundle.json"
        self.save_bundle()
        code = self.fixture.write("fixture-code-closure.json", {"fixture_authority_only": True})
        pin = pilot._pin_json(self.root, code["path"], label="fixture closure")
        interpreter = {**self.engine, "snapshot": pilot._snapshot_record(pilot._snapshot(engine.stat()))}
        self.closure = pilot._ExecutionCodeClosure(receipt_pin=pin, receipt={"project_sources": []},
            source_pins=(), interpreter=interpreter)

    def descriptor(self, pin):
        return {"path": pin.path.relative_to(self.root).as_posix(), "size_bytes": pin.snapshot[4], "sha256": pin.sha256}

    def save_bundle(self):
        runtime = {"system": self.cell.system, "resource": self.cell.resource, "scenario": self.cell.scenario,
            "topology_kind": self.cell.topology_kind, "codec": self.cell.codec, "policy": self.cell.policy,
            "duration_s": self.cell.duration_s, "streams": 6, "run_id": self.cell.run_id,
            "deadline_ms": self.cell.deadline_ms, "dataset": {
                pilot.RUNTIME_INPUT_KEY_BY_SYSTEM[self.cell.system]: self.contract}}
        bundle = {"schema_version": 2, "artifact_kind": pilot.RUNTIME_BUNDLE_KIND,
            "status": "materialized_for_native_qualification_only", "accepted": False, "publication_ready": False,
            "authorization_eligible": False, "scope": pilot.RUNTIME_BUNDLE_SCOPE,
            **{key: getattr(self.cell, key) for key in ("system", "resource", "codec", "topology_kind", "run_id", "arm_id")},
            "hardware_resource_collector": self.descriptor(self.inputs.hardware_resource_collector),
            "runtime_inputs": runtime, "launcher_evidence_files": list(pilot.CHILD_EVIDENCE_FILES)}
        bundle["bundle_sha256"] = hashlib.sha256(canonical_json_v1(bundle)).hexdigest()
        self.bundle_path.write_bytes(canonical_json_v1(bundle) + b"\n")
        pin = pilot._pin_json(self.root, self.bundle_path, label="fixture stock bundle")
        self.operational.runtime_bundles = {self.cell.arm_id: pin}

    @contextmanager
    def hold(self, **changes):
        arguments = dict(project_root=self.root, capture_plan_path=self.plan["descriptor"]["path"],
            operation_id=self.operation["operation_id"], runtime_bundle_path=self.bundle_path,
            candidate_index_path=self.inputs.candidate_index.path,
            preprocessing_contract_path=self.operational.preprocessing_contract.path,
            preprocessing_receipt_path=self.preprocessing_receipt["path"],
            runtime_materialization_receipt_path=self.operational.runtime_materialization_receipt.path,
            guardian_authority_path=self.operational.guardian_service_authority.path,
            transaction_receipt_path=self.inputs.transaction_receipt.path,
            bootstrap_mapping_path=self.inputs.bootstrap_mapping.path, bootstrap_receipt_path=self.inputs.bootstrap_receipt.path)
        arguments.update(changes)
        # Only expensive stock authority loads are fixture replacements. The
        # physical plan, request constructor, validator, sockets and barriers run.
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(pilot, "_load_qualification_inputs", return_value=self.inputs))
            stack.enter_context(mock.patch.object(pilot, "_load_operational_inputs", return_value=self.operational))
            stack.enter_context(mock.patch.object(pilot, "_load_execution_code_closure", return_value=self.closure))
            constructor = stack.enter_context(mock.patch.object(pilot, "_request_from_bootstrap_bundle", wraps=pilot._request_from_bootstrap_bundle))
            validator = stack.enter_context(mock.patch.object(pilot, "_validate_request", wraps=pilot._validate_request))
            barrier = stack.enter_context(mock.patch.object(pilot, "_assert_execution_barrier", wraps=pilot._assert_execution_barrier))
            with target.held_stock_operational_request_v1(**arguments) as value:
                yield value, constructor, validator, barrier

    def test_physical_stock_request_constructor_validator_finalizer_and_barriers(self):
        with self.hold() as (held, constructor, validator, barrier):
            self.assertIs(type(held["request"]), NativePublicationRequestV3)
            self.assertEqual(held["request"].arm_id, self.cell.arm_id)
            self.assertEqual(held["request"].output_dir, Path(self.original["outputs"]["measurement_dir"]))
            self.assertEqual(held["native_context_descriptor"], self.context)
            self.assertEqual(held["engine_descriptor"], self.engine)
            self.assertEqual(held["finalizer_kwargs"]["runtime_input_bundle_path"], self.bundle_path)
            self.assertEqual(held["finalizer_kwargs"]["expected_run_id"], self.cell.run_id)
            self.assertEqual(held["finalizer_kwargs"]["candidate_manifest_path"], self.inputs.candidate_manifest.path)
            self.assertTrue(held["finalizer_kwargs"]["hardware_collector_stopped"])
            held["execution_barrier"]()
            constructor.assert_called_once()
            validator.assert_called_once()
            self.assertGreaterEqual(barrier.call_count, 2)
        self.assertGreaterEqual(barrier.call_count, 3)
        self.assertIsNone(pilot._ACTIVE_PHYSICAL_CUSTODY.get())
        self.assertFalse(Path(self.original["outputs"]["measurement_dir"]).exists())

    def test_missing_or_foreign_context_is_rejected_before_request_yield(self):
        original = copy.deepcopy(self.contract)
        for foreign in (None, {**self.context, "path": self.fixture.model["path"]}):
            with self.subTest(foreign=foreign):
                self.contract = copy.deepcopy(original)
                if foreign is None:
                    self.contract["files"].pop(CAPTURE_ROLE)
                else:
                    self.contract["files"][CAPTURE_ROLE] = foreign
                self.save_bundle()
                with self.assertRaisesRegex(ValueError, "exact capture context"):
                    with self.hold():
                        self.fail("detached capture context yielded a request")

    def test_missing_or_alias_engine_is_rejected_without_launch(self):
        original = copy.deepcopy(self.contract)
        alias = self.root / "engine-alias"
        alias.symlink_to(self.engine["path"])
        for path in (self.root / "absent-engine", alias):
            with self.subTest(path=path):
                self.contract = copy.deepcopy(original)
                self.contract["files"]["container_engine"]["path"] = str(path)
                self.save_bundle()
                with self.assertRaises((ValueError, RuntimeError)):
                    with self.hold():
                        self.fail("missing or aliased engine yielded a request")

    def test_orphan_bundle_and_occupied_original_output_are_rejected(self):
        orphan = self.root / "orphan-bundle.json"
        orphan.write_bytes(self.bundle_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "detached from stock materialization"):
            with self.hold(runtime_bundle_path=orphan):
                self.fail("orphan bundle yielded a request")
        directory = Path(self.original["outputs"]["measurement_dir"])
        directory.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "output is occupied"):
            with self.hold():
                self.fail("occupied original output yielded a request")

    def test_actual_declared_context_drift_is_rejected_by_held_exit_barrier(self):
        with self.assertRaises((ValueError, RuntimeError)):
            with self.hold() as (held, *_):
                context = Path(self.context["path"])
                os.chmod(context, 0o600)
                context.write_bytes(context.read_bytes() + b" ")
                held["execution_barrier"]()

    def test_qualification_activation_in_diagnostic_plan_is_rejected(self):
        self.contract[CAPTURE_KEY] = {"mode": target.QUALIFICATION_MODE, "output_dir": OUTPUT_PATH_RULE}
        self.save_bundle()
        with self.assertRaisesRegex(ValueError, "exact capture context"):
            with self.hold():
                self.fail("qualification activation yielded a diagnostic request")


class _HeldQualificationOriginalRequestTests(HeldStockRequestTests):
    """Held prechecks/Savant reuse the real stock cell bundle and request spine."""
    MODE = target.QUALIFICATION_MODE
    PHASE = SYSTEM = None
    # These diagnostic-plan regressions stay in HeldStockRequestTests.
    test_physical_stock_request_constructor_validator_finalizer_and_barriers = None
    test_missing_or_foreign_context_is_rejected_before_request_yield = None
    test_missing_or_alias_engine_is_rejected_without_launch = None
    test_orphan_bundle_and_occupied_original_output_are_rejected = None
    test_actual_declared_context_drift_is_rejected_by_held_exit_barrier = None
    test_qualification_activation_in_diagnostic_plan_is_rejected = None

    def select_operation(self, held):
        rows = [row for row in held["operations_by_id"].values()
                if row["phase"] == self.PHASE and row["system"] == self.SYSTEM]
        self.assertTrue(rows)
        return rows[0]

    def declared_context(self, descriptor):
        relative = Path(descriptor["path"]).relative_to(self.root).as_posix()
        container = ("/opt/vast/input/operational/native-context.json" if self.SYSTEM in {"deepstream", "savant"}
                     else "/workspace/project/" + relative)
        return {"path": relative, "size_bytes": descriptor["size_bytes"], "sha256": descriptor["sha256"],
                "container_path": container}

    def runtime_module(self):
        import importlib
        return importlib.import_module({"openvino_gva": "checkpoint_openvino_gva_publication_runtime_v3",
            "gstreamer_custom": "checkpoint_gstreamer_publication_runtime_v3",
            "savant": "checkpoint_savant_publication_runtime_v3"}[self.SYSTEM])

    def test_held_original_reuses_stock_cell_bundle_with_only_its_own_context(self):
        self.assertNotEqual(self.own_context, self.context)
        bundle = self.bundle_path.read_bytes()
        with self.hold() as (held, constructor, validator, barrier):
            self.assertEqual((held["operation"]["phase"], held["cell"].system), (self.PHASE, self.SYSTEM))
            self.assertEqual(held["native_context_descriptor"], self.own_context)
            self.assertEqual(held["request"].output_dir, Path(self.original["outputs"]["measurement_dir"]))
            contract = held["request"].runtime_inputs["dataset"][pilot.RUNTIME_INPUT_KEY_BY_SYSTEM[self.SYSTEM]]
            expected = copy.deepcopy(self.contract)
            expected["files"][CAPTURE_ROLE] = self.declared_context(self.own_context)
            self.assertEqual(contract, expected)
            self.assertEqual(held["finalizer_kwargs"]["runtime_input_bundle_path"], self.bundle_path)
            self.assertEqual(held["finalizer_kwargs"]["expected_arm_id"], self.cell.arm_id)
            self.assertEqual(held["engine_descriptor"], self.engine)
            constructor.assert_called_once()
            self.assertEqual(validator.call_count, 2)
            held["execution_barrier"]()
            # The unchanged stock runtime of this system pins the substituted
            # context by its own size/SHA and container path rule.
            runtime = self.runtime_module()
            pin = runtime._open_pin(self.root, CAPTURE_ROLE, contract["files"][CAPTURE_ROLE])
            try:
                self.assertEqual((pin.size, pin.sha256, pin.container_path), (self.own_context["size_bytes"],
                    self.own_context["sha256"], contract["files"][CAPTURE_ROLE]["container_path"]))
                self.assertEqual(str(pin.path), self.own_context["path"])
            finally:
                os.close(pin.fd)
            for foreign in ({**contract["files"][CAPTURE_ROLE], "sha256": self.context["sha256"]},
                            {**contract["files"][CAPTURE_ROLE], "size_bytes": self.own_context["size_bytes"] + 1}):
                with self.assertRaises(Exception):
                    runtime._open_pin(self.root, CAPTURE_ROLE, foreign)
        self.assertGreaterEqual(barrier.call_count, 3)
        self.assertEqual(self.bundle_path.read_bytes(), bundle)
        self.assertIsNone(pilot._ACTIVE_PHYSICAL_CUSTODY.get())
        self.assertFalse(Path(self.original["outputs"]["measurement_dir"]).exists())

    def test_cell_phase_and_unheld_system_are_refused(self):
        self.assertFalse(any("deepstream" in systems for systems in target.HELD_OPERATIONS.values()))
        refused = [next(row for row in self.operations if row["phase"] == "qualification_cell" and row["arm_id"] == self.cell.arm_id),
                   next(row for row in self.operations if row["system"] == "deepstream")]
        for row in refused:
            with self.subTest(operation=row["operation_id"]), \
                    self.assertRaisesRegex(ValueError, "authorized forced native pair"):
                with self.hold(operation_id=row["operation_id"]):
                    self.fail("unheld original yielded a request")

    def test_bundle_with_foreign_cell_own_or_diagnostic_context_is_refused(self):
        other = next(row for row in self.operations if row["phase"] == "qualification_cell" and row["arm_id"] != self.cell.arm_id)
        original = copy.deepcopy(self.contract)
        cases = {"another_cell": (CAPTURE_ROLE, self.declared_context(self.native_contexts[other["operation_id"]])),
                 "own_context": (CAPTURE_ROLE, self.declared_context(self.own_context)),
                 "diagnostic_mode": (CAPTURE_KEY, {"mode": target.DIAGNOSTIC_MODE, "output_dir": OUTPUT_PATH_RULE})}
        for name, (key, value) in cases.items():
            with self.subTest(case=name):
                self.contract = copy.deepcopy(original)
                if key == CAPTURE_ROLE:
                    self.contract["files"][key] = value
                else:
                    self.contract[key] = value
                self.save_bundle()
                with self.assertRaisesRegex(ValueError, "exact cell capture context"):
                    with self.hold():
                        self.fail("detached held context yielded a request")


class HeldOpenvinoGvaPrecheckRequestTests(_HeldQualificationOriginalRequestTests):
    PHASE, SYSTEM = "native_precheck", "openvino_gva"


class HeldGstreamerCustomPrecheckRequestTests(_HeldQualificationOriginalRequestTests):
    PHASE, SYSTEM = "native_precheck", "gstreamer_custom"


class HeldSavantOriginalRequestTests(_HeldQualificationOriginalRequestTests):
    PHASE, SYSTEM = "savant_original", "savant"


# The parameterized base is not itself a test case.
del _HeldQualificationOriginalRequestTests


if __name__ == "__main__":
    unittest.main()
