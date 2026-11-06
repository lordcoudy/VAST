"""Copied fixture labels and drop counts refuse before native allocation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_policy_contract import ANALYTICS_BRANCHES, RESOURCES
from tests.fixtures import accepted_policy_native_fixture_v2 as native
from tests.test_accepted_policy_production_validation import verified_fixture_manifest


class AllocationReached(RuntimeError):
    pass


class FixtureBindingBoundsTests(unittest.TestCase):
    def setUp(self):
        self.capability = verified_fixture_manifest()

    def call(self, **overrides):
        arguments = dict(output_dir=Path("binding-output-never-created"),
            capability=self.capability, system="gstreamer_custom", resource="cpu",
            codec="h264", topology_kind="independent_processes")
        arguments.update(overrides)
        return native.write_native_policy_fixture_cell_v2(**arguments)

    def test_nonboolean_drop_refuses_before_allocation(self):
        for value in (0, 1, -1, 2**64, None, "false"):
            with self.subTest(value=value), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("drop reached allocation")), \
                    patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("drop reached coordinator")):
                with self.assertRaisesRegex(ValueError, "Boolean"):
                    self.call(dropped_ingress=value)

    def test_both_boolean_drop_values_reach_only_allocation_marker(self):
        for value in (False, True):
            with self.subTest(value=value), \
                    patch.object(Path, "mkdir", side_effect=AllocationReached), \
                    patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("generation is unselected")):
                with self.assertRaises(AllocationReached):
                    self.call(dropped_ingress=value)

    def test_oversized_copied_binding_labels_refuse_before_allocation(self):
        for field in ("implementation_id", "terminal_detector", "terminal_backend"):
            capability = deepcopy(self.capability)
            capability["systems"]["gstreamer_custom"]["branches"][ANALYTICS_BRANCHES[0]]["cpu"][field] = "x" * 513
            with self.subTest(field=field), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("label reached allocation")):
                with self.assertRaisesRegex(ValueError, "512"):
                    self.call(capability=capability)

    def test_escaped_or_nonscalar_copied_binding_labels_refuse_before_allocation(self):
        for value in ('a"b', "a\\b", "a\nb", "\u00e9", 7, None):
            capability = deepcopy(self.capability)
            capability["systems"]["gstreamer_custom"]["branches"][ANALYTICS_BRANCHES[0]]["cpu"]["terminal_detector"] = value
            with self.subTest(value=value), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("unsafe label reached allocation")):
                with self.assertRaisesRegex(ValueError, "512"):
                    self.call(capability=capability)

    def test_unselected_resource_calibration_implementation_is_also_bounded(self):
        capability = deepcopy(self.capability)
        capability["systems"]["gstreamer_custom"]["branches"][ANALYTICS_BRANCHES[-1]]["gpu"]["implementation_id"] = "x" * 513
        with patch.object(Path, "mkdir", side_effect=AssertionError("calibration label reached allocation")):
            with self.assertRaisesRegex(ValueError, "512"):
                self.call(capability=capability)

    def test_512_byte_labels_are_preserved_and_other_systems_are_outside_scope(self):
        capability = deepcopy(self.capability)
        label = "x" * 512
        for branch in ANALYTICS_BRANCHES:
            for resource in RESOURCES:
                binding = capability["systems"]["gstreamer_custom"]["branches"][branch][resource]
                for field in ("implementation_id", "terminal_detector", "terminal_backend"):
                    binding[field] = label
        capability["systems"]["unselected-system"] = {"unbounded-test-marker": "x" * 513}
        before = deepcopy(capability)
        with patch.object(Path, "mkdir", side_effect=AllocationReached), \
                patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("generation is unselected")):
            with self.assertRaises(AllocationReached):
                self.call(capability=capability)
        self.assertEqual(capability, before)


if __name__ == "__main__":
    unittest.main()
