"""Selected-cohort quantity bounds before data allocation; no fixture generation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_native_fixture_v2 as native
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.test_accepted_policy_production_validation import verified_fixture_manifest


def plan():
    return {"operation_manifest": {"operations": [
        {"operation_id": "qualification-%d" % index, "phase": "qualification_cell"}
        for index in range(32)] + [
        {"operation_id": "ancillary-%d" % index, "phase": "ancillary"}
        for index in range(5)]}}


def prepared(value):
    return {"root": Path.cwd(), "output_dir": Path("quantity-output-never-created"),
        "capture_plan": value,
        "transaction": {"candidate_manifest_path": Path("quantity-input-never-read.json")}}


class FixtureQuantityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capability = verified_fixture_manifest()

    def test_native_excess_refuses_before_output_or_coordinator(self):
        for count in (986, 2**64):
            with self.subTest(count=count), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("quantity bound reached allocation")), \
                    patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("quantity bound reached coordinator")):
                with self.assertRaisesRegex(ValueError, "985"):
                    native.write_native_policy_fixture_cell_v2(
                        output_dir=Path("quantity-output-never-created"), capability=self.capability,
                        system="gstreamer_custom", resource="cpu", codec="h264",
                        topology_kind="independent_processes", samples_per_branch=count)

    def test_native_985_and_underfill29_reach_only_the_allocation_marker(self):
        class AllocationReached(RuntimeError):
            pass

        for count in (985, 29):
            with self.subTest(count=count), patch.object(Path, "mkdir", side_effect=AllocationReached), \
                    patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("fixture generation is not selected")):
                with self.assertRaises(AllocationReached):
                    native.write_native_policy_fixture_cell_v2(
                        output_dir=Path("quantity-output-never-created"), capability=self.capability,
                        system="gstreamer_custom", resource="cpu", codec="h264",
                        topology_kind="independent_processes", samples_per_branch=count)

    def test_excess_global_count_refuses_before_candidate_read(self):
        for count in (986, 2**64):
            with self.subTest(count=count), \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("excess global count reached candidate read")):
                with self.assertRaisesRegex(ValueError, "985"):
                    physical.build_original_native_fixture_observations_v2(
                        prepared=prepared(plan()), samples_per_branch=count)

    def test_excess_mixed_count_refuses_before_candidate_read(self):
        for count in (986, 2**64):
            with self.subTest(count=count), \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("excess mixed count reached candidate read")):
                with self.assertRaisesRegex(ValueError, "985"):
                    physical.build_original_native_fixture_observations_v2(
                        prepared=prepared(plan()), samples_per_branch=30,
                        qualification_samples_by_operation_id={"qualification-0": count})

    def test_selected_mixed_total_and_underfill_mapping_are_preserved(self):
        overrides = {"qualification-%d" % index: 984 if index % 2 == 0 else 985 for index in range(32)}
        counts = physical._fixture_operation_sample_counts_v2(
            plan(), samples_per_branch=30, qualification_samples_by_operation_id=overrides)
        self.assertEqual(sum(counts["qualification-%d" % index] * 4 for index in range(32)), 126016)
        self.assertEqual({counts["ancillary-%d" % index] for index in range(5)}, {30})
        underfill = physical._fixture_operation_sample_counts_v2(
            plan(), samples_per_branch=31, qualification_samples_by_operation_id={"qualification-0": 29})
        self.assertEqual(underfill["qualification-0"], 29)
        self.assertEqual(len(underfill), 37)

    def test_wrong_operation_roster_refuses_before_candidate_read(self):
        for count in (36, 38):
            value = plan()
            if count == 36:
                value["operation_manifest"]["operations"].pop()
            else:
                value["operation_manifest"]["operations"].append({"operation_id": "extra", "phase": "ancillary"})
            with self.subTest(count=count), \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("wrong roster reached candidate read")):
                with self.assertRaisesRegex(ValueError, "37"):
                    physical.build_original_native_fixture_observations_v2(prepared=prepared(value))

    def test_excess_override_count_refuses_before_set_materialization(self):
        overrides = {"qualification-%d" % index: 30 for index in range(33)}
        with patch.object(physical, "set", create=True,
                side_effect=AssertionError("oversized overrides reached set construction")):
            with self.assertRaisesRegex(ValueError, "32"):
                physical._fixture_operation_sample_counts_v2(plan(), samples_per_branch=30,
                    qualification_samples_by_operation_id=overrides)

    def test_wrong_qualification_count_refuses_before_candidate_read(self):
        value = plan()
        value["operation_manifest"]["operations"][-1]["phase"] = "qualification_cell"
        with patch.object(Path, "read_bytes", side_effect=AssertionError("wrong qualification roster reached read")):
            with self.assertRaisesRegex(ValueError, "32"):
                physical.build_original_native_fixture_observations_v2(prepared=prepared(value))


if __name__ == "__main__":
    unittest.main()
