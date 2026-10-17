"""Fixture count boundaries and real native 29-sample refusal building blocks.

These tests do not assert accepted policy promotion or complete guardian
acceptance. Complete per-cell refusal evidence requires a fresh physical chain.
"""
from pathlib import Path
import ast
import importlib
import inspect
import tempfile
import unittest

from tests.test_accepted_policy_production_validation import validate_native_cell, verified_fixture_manifest
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures.accepted_policy_native_fixture_v2 import write_native_policy_fixture_cell_v2
from tests.fixtures.accepted_policy_change_paths_v1 import consumer_evidence_directory_v1


class AcceptedPolicyFixtureSampleCountsV2Tests(unittest.TestCase):
    def _plan(self):
        return {"operation_manifest": {"operations": [
            {"operation_id": f"qualification-{position}", "phase": "qualification_cell"} for position in range(32)
        ] + [{"operation_id": f"ancillary-{position}", "phase": "ancillary"} for position in range(5)]}}

    def test_mixed_counts_change_one_qualification_cell_and_leave_others_at31(self):
        counts = physical._fixture_operation_sample_counts_v2(
            self._plan(), samples_per_branch=31, qualification_samples_by_operation_id={"qualification-0": 29})
        self.assertEqual(counts["qualification-0"], 29)
        self.assertTrue(all(value == 31 for key, value in counts.items() if key != "qualification-0"))
        self.assertEqual(sum(counts[f"qualification-{position}"] * 4 for position in range(32)), 3960)

    def test_negative_entrypoint_compiles_and_uses_actual_call_signatures_without_changing_positive_gate(self):
        root = Path(__file__).resolve().parents[1]
        directory = consumer_evidence_directory_v1(root)
        positive = ast.parse((directory / "build_production_fixture_v2.py").read_bytes())
        self.assertTrue(any(isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute)
                            and node.left.attr == "samples_per_branch" and len(node.ops) == 1
                            and isinstance(node.ops[0], ast.Lt) and isinstance(node.comparators[0], ast.Constant)
                            and node.comparators[0].value == 30 for node in ast.walk(positive)))
        path = directory / "build_per_cell_minimum_refusal_v1.py"
        tree = ast.parse(path.read_bytes(), filename=str(path))
        compile(tree, str(path), "exec")
        imported = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and (root / "scripts" / (node.module + ".py")).is_file():
                module = importlib.import_module(node.module)
                imported.update({alias.asname or alias.name: getattr(module, alias.name) for alias in node.names})
        checked = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in imported:
                target = imported[node.func.id]
                if inspect.isfunction(target):
                    inspect.signature(target, follow_wrapped=False).bind_partial(
                        *[object() for argument in node.args if not isinstance(argument, ast.Starred)],
                        **{keyword.arg: object() for keyword in node.keywords if keyword.arg is not None})
                    checked.add(node.func.id)
        self.assertTrue({"assess_policy_qualification", "promote_policy_qualification", "policy_pilot_validator"}.issubset(checked))

    def test_invalid_global_or_mixed_counts_refuse_before_native_writes(self):
        invalid = (True, "29", 29.0, 0, -1)
        with tempfile.TemporaryDirectory(prefix="accepted-policy-count-boundary-") as raw:
            output = Path(raw) / "must-remain-absent"
            prepared = {"root": Path(raw), "output_dir": output, "capture_plan": self._plan()}
            for value in invalid:
                with self.subTest(native=value), self.assertRaises(ValueError):
                    write_native_policy_fixture_cell_v2(
                        output_dir=output, capability={}, system="gstreamer_custom", resource="cpu",
                        codec="h264", topology_kind="independent_processes", samples_per_branch=value)
                self.assertFalse(output.exists())
                with self.subTest(mixed=value), self.assertRaises(ValueError):
                    physical._fixture_operation_sample_counts_v2(
                        self._plan(), samples_per_branch=31,
                        qualification_samples_by_operation_id={"qualification-0": value})
                with self.subTest(builder_mixed=value), self.assertRaises(ValueError):
                    physical.build_original_native_fixture_observations_v2(
                        prepared=prepared, samples_per_branch=31,
                        qualification_samples_by_operation_id={"qualification-0": value})
                self.assertFalse(output.exists())
                with self.subTest(global_count=value), self.assertRaises(ValueError):
                    physical._fixture_operation_sample_counts_v2(
                        self._plan(), samples_per_branch=value, qualification_samples_by_operation_id=None)
            with self.assertRaises(ValueError):
                physical._fixture_operation_sample_counts_v2(
                    self._plan(), samples_per_branch=29, qualification_samples_by_operation_id=None)
            for overrides in ({"unknown": 29}, {"ancillary-0": 29}, [("qualification-0", 29)]):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    physical._fixture_operation_sample_counts_v2(
                        self._plan(), samples_per_branch=31, qualification_samples_by_operation_id=overrides)
                with self.subTest(builder_overrides=overrides), self.assertRaises(ValueError):
                    physical.build_original_native_fixture_observations_v2(
                        prepared=prepared, samples_per_branch=31, qualification_samples_by_operation_id=overrides)
            duplicated = self._plan()
            duplicated["operation_manifest"]["operations"][1]["operation_id"] = "qualification-0"
            with self.assertRaises(ValueError):
                physical._fixture_operation_sample_counts_v2(
                    duplicated, samples_per_branch=31, qualification_samples_by_operation_id={"qualification-0": 29})
            self.assertFalse(output.exists())

    def test_real29_native_coordinator_sidecars_and_reset_are_valid_before_policy_minimum(self):
        manifest = verified_fixture_manifest()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-real29-") as raw:
            for resource in ("cpu", "gpu"):
                for topology in ("independent_processes", "shared_video_dag"):
                    with self.subTest(resource=resource, topology=topology):
                        output = Path(raw) / resource / topology
                        metadata = write_native_policy_fixture_cell_v2(
                            output_dir=output, capability=manifest, system="gstreamer_custom", resource=resource,
                            codec="h264", topology_kind=topology, samples_per_branch=29,
                            dropped_ingress=resource == "gpu")
                        frames, sidecars = validate_native_cell(output, metadata, topology)
                        self.assertEqual(len(frames), 29)
                        self.assertTrue(sidecars["reset_evidence"]["reset_claim_eligible"].all())
                        self.assertTrue(sidecars["resource_intervals"].attrs["full_resource_summary"]["full_resource_coverage_complete"])
                        completed = sidecars["policy_decisions"]
                        drops = set(sidecars["ingress_ledger"].loc[
                            sidecars["ingress_ledger"]["terminal_status"] == "drop", "trace_id"])
                        completed = completed.loc[~completed["trace_id"].isin(drops)]
                        for branch in manifest["systems"]["gstreamer_custom"]["branches"]:
                            self.assertEqual((completed["stage"] == branch).sum(), 29)


if __name__ == "__main__":
    unittest.main()
