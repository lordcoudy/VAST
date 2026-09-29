"""Current qualification consumers must request cold complete accounting."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import full_resource_qualification as resource
import full_resource_qualification_index_v1 as resource_index
import publication_guardian_accepted_policy_preprocessing_contract_v1 as accepted
import publication_policy_qualification as policy
import publication_policy_qualification_index_v2 as policy_index
from test_publication_guardian_accepted_policy_preprocessing_contract_v1 import Fixture
from unittest.mock import patch


class StrictColdGateReached(BaseException):
    """A test loader refuses to authorize any record after checking delegation."""


class CompleteOperationalPromotionGateV1Tests(unittest.TestCase):
    def strict_loader(self, **kwargs):
        self.assertIs(kwargs.get("require_complete_operational_accounting"), True)
        self.assertEqual(set(kwargs), {
            "project_root", "receipt_path", "require_complete_operational_accounting",
        })
        raise StrictColdGateReached

    @staticmethod
    def closure(root):
        path = root / "closure" / "qualification_execution_closure.v1.receipt.json"
        path.parent.mkdir()
        path.write_bytes(b'{"historical_fixture":true}\n')
        return path

    def test_policy_assessment_requires_strict_cold_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self.closure(root)
            descriptor = policy_index._descriptor(root, path, "test closure")
            with patch.object(policy, "_load_execution_closure", self.strict_loader):
                with self.assertRaises(StrictColdGateReached):
                    policy._verify_execution_closure(root, descriptor)

    def test_full_resource_assessment_requires_strict_cold_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self.closure(root)
            descriptor = policy_index._descriptor(root, path, "test closure")
            with patch.object(resource, "_load_execution_closure", self.strict_loader):
                with self.assertRaises(StrictColdGateReached):
                    resource._verify_execution_closure(root, descriptor)

    def test_completed_policy_index_requires_strict_cold_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self.closure(root)
            pilots = root / "pilots"
            pilots.mkdir()
            with self.assertRaises(StrictColdGateReached):
                policy_index._validated_execution_closure_descriptor(
                    root=root, pilot_root=pilots, receipt_path=path,
                    loader=self.strict_loader, expected_fragment_descriptors={},
                )

    def test_completed_resource_index_requires_strict_cold_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = self.closure(root)
            pilots = root / "pilots"
            pilots.mkdir()
            with self.assertRaises(StrictColdGateReached):
                resource_index._validated_execution_closure_descriptor(
                    root=root, pilot_root=pilots, receipt_path=path,
                    loader=self.strict_loader, expected_fragment_descriptors={},
                )

    def test_current_accepted_policy_guardian_requires_strict_cold_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            dependencies = replace(
                fixture.dependencies(), load_execution_closure=self.strict_loader,
            )
            with self.assertRaises(StrictColdGateReached):
                accepted._source_material(
                    root=root,
                    qualification_preprocessing_contract_path=fixture.predecessor_contract_path,
                    qualification_preprocessing_receipt_path=fixture.predecessor_receipt_path,
                    completed_qualification_index_path=fixture.index_path,
                    accepted_policy_qualification_receipt_path=fixture.accepted_receipt_path,
                    accepted_policy_capability_manifest_path=fixture.accepted_capability_path,
                    accepted_policy_calibration_mapping_path=fixture.accepted_calibration_path,
                    execution_config_path=fixture.config_path,
                    binding_set_dir=fixture.binding_dir,
                    dependencies=dependencies,
                )


if __name__ == "__main__":
    unittest.main()
