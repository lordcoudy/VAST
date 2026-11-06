"""Test-only stock sample semantics; portable tests are not full acceptance.

Real native sidecars/reset validators run below. Only the portable arm's absent
upstream acceptance authority is substituted, explicitly at that boundary.
Existing semantic unit arms also stub downstream inputs and prove only samples.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification as stock
from tests.fixtures import accepted_policy_stock_sample_reference_v1 as reference
from tests import test_accepted_policy_f5_real_refusals as real_refusals
from tests.test_publication_qualification_policy_pilot_validator_v2 import _Arm, _decision


STOCK_SHA256 = "f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde"
EXPECTED_REFERENCE_DIFF = """\
--- stock
+++ reference
@@ -1 +1 @@
-def _default_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
+def stock_sample_reference_v1(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
@@ -121,0 +122,2 @@
+            require_reset_evidence=True,
+            expected_streams=6,
"""


class AcceptedPolicyStockSampleReferenceV1Tests(unittest.TestCase):
    def portable_arm(self):
        temporary = tempfile.TemporaryDirectory(prefix="stock-sample-reference-")
        self.addCleanup(temporary.cleanup)
        return real_refusals._PortableArm(Path(temporary.name).resolve())

    def run_portable(self, arm, validator):
        module = inspect.getmodule(validator)
        # This is explicitly limited portable evidence, never a genuine comparison.
        with mock.patch.object(module, "validate_checkpoint_qualification_pilot_acceptance_v1",
                               return_value=dict(arm.acceptance)):
            return validator(arm.pilot, arm.context)

    def test_original_stock_retains_real_reset_prerequisite_refusal(self):
        arm = self.portable_arm()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "reset validation requires topology kind, stream count, and branch set"):
            self.run_portable(arm, stock._default_pilot_validator)

    def test_reference_passes_real_six_stream_reset_to_dataset_gate(self):
        arm = self.portable_arm()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "unknown dataset 'kpp_iss_publication_v3_h264'"):
            self.run_portable(arm, reference.stock_sample_reference_v1)

    def test_reference_missing_reset_refuses_before_dataset_gate(self):
        arm = self.portable_arm()
        (arm.output / "reset_evidence.csv").unlink()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "checkpoint acceptance evidence is missing: reset_evidence.csv"):
            self.run_portable(arm, reference.stock_sample_reference_v1)

    def test_reference_malformed_reset_uses_real_validator(self):
        arm = self.portable_arm()
        source = arm.output / "reset_evidence.csv"
        pd.read_csv(source).drop(columns=["reset_provenance"]).to_csv(source, index=False)
        arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "reset_evidence.csv.*missing or empty value for reset_provenance"):
            self.run_portable(arm, reference.stock_sample_reference_v1)

    def test_reference_incomplete_six_stream_reset_uses_real_validator(self):
        arm = self.portable_arm()
        source = arm.output / "reset_evidence.csv"
        rows = pd.read_csv(source)
        rows.loc[rows["stream_id"] != 5].to_csv(source, index=False)
        arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError, "reset process coverage differs; missing="):
            self.run_portable(arm, reference.stock_sample_reference_v1)

    def test_complete_text_diff_and_original_production_bytes_are_locked(self):
        self.assertEqual(reference.STOCK_SHA256, STOCK_SHA256)
        self.assertEqual(reference.EXPECTED_DIFF, EXPECTED_REFERENCE_DIFF)
        diff = "".join(difflib.unified_diff(
            inspect.getsource(stock._default_pilot_validator).splitlines(keepends=True),
            inspect.getsource(reference.stock_sample_reference_v1).splitlines(keepends=True),
            "stock", "reference", n=0))
        self.assertEqual(diff, EXPECTED_REFERENCE_DIFF)
        reference.validate_stock_sample_reference_v1()
        self.assertEqual(hashlib.sha256(Path(stock.__file__).read_bytes()).hexdigest(),
                         STOCK_SHA256)
        f5_path = Path(real_refusals.f5.__file__)
        self.assertEqual(hashlib.sha256(f5_path.read_bytes()).hexdigest(),
                         "48fbc62494cdc40bd5f925cee6ff16dad02269feacf1803d263a9d165523f246")

    def test_reference_bindings_are_original_stock_objects(self):
        for name in ("math", "defaultdict", "Path", "Any", "KPP_DATASET_BY_CODEC",
                     "QualificationError", "QualificationPilotAcceptanceV1Error",
                     "_read_jsonl", "_sha256_file", "_stable_id", "_valid_sha",
                     "_validate_evidence_descriptors", "_verify_descriptor",
                     "validate_checkpoint_qualification_pilot_acceptance_v1"):
            with self.subTest(name=name):
                self.assertIs(getattr(reference, name), getattr(stock, name))

    def test_comparison_guard_refuses_unreviewed_hash_or_diff(self):
        with mock.patch.object(reference, "STOCK_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "original module SHA256 drift"):
                reference.validate_stock_sample_reference_v1()
        with mock.patch.object(reference, "EXPECTED_DIFF", "unreviewed"):
            with self.assertRaisesRegex(RuntimeError, "reviewed exact diff"):
                reference.validate_stock_sample_reference_v1()

    def test_genuine_comparator_wiring_and_report_scope_are_explicit(self):
        self.assertIs(real_refusals.stock_reference, reference)
        function = ast.parse(inspect.getsource(real_refusals.assert_genuine_f5_stock_samples_v1)).body[0]
        calls = [ast.unparse(node.func) for statement in function.body
                 for node in ast.walk(statement) if isinstance(node, ast.Call)]
        self.assertIn("stock_reference.validate_stock_sample_reference_v1", calls)
        self.assertIn("stock_reference.stock_sample_reference_v1", calls)
        self.assertNotIn("stock._default_pilot_validator", calls)
        self.assertLess(calls.index("stock_reference.validate_stock_sample_reference_v1"),
                        calls.index("f5.policy_pilot_validator"))
        returned = next(node for node in function.body if isinstance(node, ast.Return)).value
        report = {key.value: value.value for key, value in zip(returned.keys, returned.values)
                  if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)}
        self.assertEqual(report["comparison_basis"],
                         "stock_sample_semantics_with_reviewed_six_stream_reset_prerequisites")
        self.assertIs(report["unchanged_stock_default_acceptance_claimed"], False)

    def semantic_arm(self, resource, decisions, **kwargs):
        temporary = tempfile.TemporaryDirectory(prefix="stock-sample-semantics-")
        self.addCleanup(temporary.cleanup)
        return _Arm(Path(temporary.name).resolve(), resource, decisions, **kwargs)

    def run_semantic(self, arm, validator):
        # These upstream/downstream stubs test sample semantics, not real acceptance.
        with arm.stubs(), mock.patch.object(
                reference, "_validate_evidence_descriptors", return_value=dict(arm.paths)), mock.patch.object(
                reference, "validate_checkpoint_qualification_pilot_acceptance_v1",
                return_value=dict(arm.acceptance)):
            return validator(dict(arm.pilot), arm.context())

    def test_cpu_and_positive_transfer_gpu_samples_equal_f5(self):
        for resource in ("cpu", "gpu"):
            with self.subTest(resource=resource):
                arm = self.semantic_arm(resource, [_decision("t1", "plate_number", resource),
                                                   _decision("t1", "damage", resource)],
                                        ingress={"t1": "completed"},
                                        transfer={("t1", "plate_number"), ("t1", "damage")})
                self.assertEqual(self.run_semantic(arm, reference.stock_sample_reference_v1),
                                 arm.run(real_refusals.f5.policy_pilot_validator))

    def test_reference_retains_stock_gpu_no_transfer_refusal_even_for_drop(self):
        for status in ("completed", "drop"):
            with self.subTest(status=status):
                arm = self.semantic_arm("gpu", [_decision("t1", "plate_number", "gpu")],
                                        ingress={"t1": status}, transfer=set())
                with self.assertRaisesRegex(stock.QualificationError, "lacks native transfer interval"):
                    self.run_semantic(arm, reference.stock_sample_reference_v1)


if __name__ == "__main__":
    unittest.main()
