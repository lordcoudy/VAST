"""Current promotion fails closed on legacy evidence; history stays readable.

The active report seam tests cold recomputation dispatch, not physical 37-arm
execution. Real transport and original child/container tests live separately.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import publication_policy_qualification_execution_closure_v1 as target
from test_publication_policy_qualification_execution_closure_v1 import (
    Fixture, descriptor, semantic_sha, write_json,
)


class OperationalClosureColdGateTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return Fixture(Path(temp.name))

    def load(self, fixture, receipt_path, **kwargs):
        return target.load_publication_policy_qualification_execution_closure_v1(
            project_root=fixture.root, receipt_path=receipt_path,
            dependencies=fixture.dependencies(), **kwargs)

    def test_legacy_exact_32_closure_remains_readable_but_cannot_promote(self):
        fixture = self.fixture()
        result = fixture.invoke()
        path = Path(result["receipt_path"])
        self.assertEqual(self.load(fixture, path)["receipt"]["pilot_execution"]
                         ["guardian_request_workload"]["request_count"], 128)
        with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error,
                                    "requires complete original operational accounting"):
            self.load(fixture, path, require_complete_operational_accounting=True)
        self.assertNotIn("operational_accounting", json.loads(path.read_bytes())["guardian"])

    def attach_report(self, fixture, path):
        binding = fixture.root / "binding.json"
        write_json(binding, {"fixture_only": True})
        unsigned = {"schema_version": 1, "artifact_kind": "vast_original_operational_accounting_v1",
            "mode": "complete_qualification_operational_identity_v1", "binding": descriptor(fixture.root, binding),
            "capture_plan": {"fixture_only": True}, "original_operation_count": 37,
            "qualification_cell_count": 32, "reconciliation": {"request_count": 444},
            "publication_authority": False}
        report = {**unsigned, "sha256": semantic_sha(unsigned)}
        receipt = json.loads(path.read_bytes())
        receipt["guardian"]["operational_accounting"] = report
        receipt["receipt_sha256"] = semantic_sha({key: value for key, value in receipt.items()
                                                  if key != "receipt_sha256"})
        path.chmod(0o644)
        write_json(path, receipt)
        path.chmod(0o444)
        return report, binding

    def test_present_report_is_recomputed_from_physical_binding_before_comparison(self):
        fixture = self.fixture()
        path = Path(fixture.invoke()["receipt_path"])
        report, binding = self.attach_report(fixture, path)
        with mock.patch.object(target, "reconcile_operational_capture_binding_v1",
                               return_value=copy.deepcopy(report)) as reconcile:
            loaded = self.load(fixture, path, require_complete_operational_accounting=True)
        self.assertEqual(loaded["receipt"]["guardian"]["operational_accounting"], report)
        self.assertEqual(reconcile.call_count, 1)
        args = reconcile.call_args.kwargs
        self.assertEqual(Path(args["binding_path"]), Path(binding.relative_to(fixture.root)))
        self.assertEqual(args["expected_mode"], report["mode"])
        self.assertEqual(len(args["pilot_execution"]["guardian_request_workload"]["cells"]), 32)

    def test_self_resealed_foreign_report_does_not_replace_cold_recomputed_result(self):
        fixture = self.fixture()
        path = Path(fixture.invoke()["receipt_path"])
        report, _ = self.attach_report(fixture, path)
        actual = copy.deepcopy(report)
        actual["reconciliation"]["request_count"] = 445
        actual["sha256"] = semantic_sha({key: value for key, value in actual.items() if key != "sha256"})
        with mock.patch.object(target, "reconcile_operational_capture_binding_v1", return_value=actual):
            with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error,
                                        "guardian field drifted: operational_accounting"):
                self.load(fixture, path, require_complete_operational_accounting=True)

    def test_current_gate_rejects_truthy_non_boolean_and_resealed_wrong_scope(self):
        fixture = self.fixture()
        path = Path(fixture.invoke()["receipt_path"])
        with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error, "explicit Boolean"):
            self.load(fixture, path, require_complete_operational_accounting="true")
        self.attach_report(fixture, path)
        receipt = json.loads(path.read_bytes())
        report = receipt["guardian"]["operational_accounting"]
        report["original_operation_count"] = 32
        report["sha256"] = semantic_sha({key: value for key, value in report.items() if key != "sha256"})
        receipt["receipt_sha256"] = semantic_sha({key: value for key, value in receipt.items()
                                                  if key != "receipt_sha256"})
        path.chmod(0o644)
        write_json(path, receipt)
        path.chmod(0o444)
        with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error, "schema/scope drifted"):
            self.load(fixture, path, require_complete_operational_accounting=True)


if __name__ == "__main__":
    unittest.main()
