"""Capture cannot substitute original cell/candidate/calibration authority."""
from __future__ import annotations
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publication_policy_qualification_runtime_inputs_v2 as materializer
from publication_policy_qualification_pilot_executor_v2 import qualification_pilot_cells_v2


class OperationalRuntimeInputBindingTests(unittest.TestCase):
    def fixture(self, root):
        cell = next(c for c in qualification_pilot_cells_v2() if c.system == "gstreamer_custom")
        def pin(name, payload):
            path = root / name
            path.write_bytes(payload)
            return SimpleNamespace(path=path, snapshot=(0, 0, 0, 1, len(payload)),
                                   sha256=hashlib.sha256(payload).hexdigest())
        candidate, calibration = pin("candidate.json", b"candidate"), pin("calibration.json", b"calibration")
        context = pin("context.json", b"original context")
        descriptor = lambda p: {"path": p.path.relative_to(root).as_posix(),
            "size_bytes": p.snapshot[4], "sha256": p.sha256}
        inputs = SimpleNamespace(root=root, candidate_manifest=candidate,
                                 calibrations={cell.system: calibration})
        operation = {key: getattr(cell, key) for key in
            ("arm_id", "run_id", "system", "scenario", "codec", "policy", "deadline_ms")}
        operation.update(phase="diagnostic", warmup_s=30.0, measurement_s=180.0,
                         drain_timeout_s=10.0, streams=6, branches=4)
        row = {"operation": operation, "descriptor": descriptor(context),
               "context": {"mode": "bounded_native_diagnostic_operational_v1",
                   "native_header": {"descriptors": {
                       "capability_manifest": descriptor(candidate), "calibration": descriptor(calibration)}}}}
        plan = {"index": {"mode": "bounded_native_diagnostic_operational_v1"},
                "runtime_contexts_by_arm": {cell.arm_id: row}}
        contract = {"files": {"original": {"sha256": "untouched"}}, "static_hybrid_map": None}
        return cell, inputs, plan, contract

    def test_selected_original_cell_gets_pinned_primary_context_without_input_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cell, inputs, plan, contract = self.fixture(Path(tmp))
            original = copy.deepcopy(contract)
            result = materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                contract=contract, capture_plan=plan)
            self.assertEqual(contract, original)
            self.assertEqual(result["operational_capture"]["output_dir"], "request_output_dir_sibling_v1")
            self.assertIn("operational_request_context", result["files"])
            self.assertEqual(result["files"]["original"], original["files"]["original"])
            self.assertEqual(result["operational_capture"]["mode"], "bounded_native_diagnostic_operational_v1")

    def test_foreign_original_run_or_calibration_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cell, inputs, plan, contract = self.fixture(Path(tmp))
            for field in ("run_id", "policy", "measurement_s"):
                foreign = copy.deepcopy(plan)
                foreign["runtime_contexts_by_arm"][cell.arm_id]["operation"][field] = "foreign"
                with self.subTest(field=field), self.assertRaises(materializer.QualificationRuntimeInputMaterializationV2Error):
                    materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                        contract=contract, capture_plan=foreign)
            foreign = copy.deepcopy(plan)
            foreign["runtime_contexts_by_arm"][cell.arm_id]["context"]["native_header"]["descriptors"]["calibration"]["sha256"] = "0" * 64
            with self.assertRaises(materializer.QualificationRuntimeInputMaterializationV2Error):
                materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                    contract=contract, capture_plan=foreign)

    def test_unselected_diagnostic_bundle_is_inactive_and_qualification_missing_cell_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cell, inputs, plan, contract = self.fixture(Path(tmp))
            plan["runtime_contexts_by_arm"] = {}
            self.assertEqual(materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                contract=contract, capture_plan=plan), contract)
            plan["index"]["mode"] = "complete_qualification_operational_identity_v1"
            with self.assertRaises(materializer.QualificationRuntimeInputMaterializationV2Error):
                materializer._bind_operational_context_for_cell(cell=cell, inputs=inputs,
                    contract=contract, capture_plan=plan)


if __name__ == "__main__":
    unittest.main()
