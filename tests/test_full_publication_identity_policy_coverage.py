from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_full_publication_identity_artifacts import (
    BRANCHES,
    RESOURCES,
    SYSTEMS,
    Fixture,
    descriptor,
    self_hashed,
    target,
    write_json,
)


class FullPublicationIdentityPolicyCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)
        self.receipt_path = self.fixture.output / "checkpoint_policy_qualification_receipt.json"
        self.calibration_path = self.fixture.output / "checkpoint_policy_calibration_mapping.json"
        self.capability_path = self.fixture.output / "checkpoint_policy_capability_manifest.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _rewrite_policy(self, *, coverage=None, calibration=None, capability=None) -> None:
        # Rebind every downstream physical descriptor, so semantic refusals cannot
        # be attributed to an intentionally stale SHA or receipt self-hash.
        if calibration is not None:
            write_json(self.calibration_path, calibration)
        if capability is not None:
            write_json(self.capability_path, capability)
        receipt = json.loads(self.receipt_path.read_text())
        receipt.pop("sha256")
        if coverage is not None:
            receipt["coverage"] = coverage
        receipt["outputs"] = {
            "capability_manifest": descriptor(self.root, self.capability_path, base=self.fixture.output),
            "calibration_mapping": descriptor(self.root, self.calibration_path, base=self.fixture.output),
        }
        write_json(self.receipt_path, self_hashed(receipt))
        manifest = json.loads(self.fixture.manifest_path.read_text())
        manifest["bindings"]["policy_qualification"] = {
            "receipt": descriptor(self.root, self.receipt_path),
            "outputs": {
                "capability_manifest": descriptor(self.root, self.capability_path),
                "calibration_mapping": descriptor(self.root, self.calibration_path),
            },
        }
        backend = manifest["bindings"]["backend_runtime_qualification"]
        for system, raw_descriptor in backend["receipts"].items():
            path = self.root / raw_descriptor["path"]
            backend_receipt = json.loads(path.read_text())
            backend_receipt.pop("sha256")
            backend_receipt["policy_qualification_receipt_sha256"] = descriptor(
                self.root, self.receipt_path
            )["sha256"]
            write_json(path, self_hashed(backend_receipt))
            backend["receipts"][system] = descriptor(self.root, path)
        index_path = self.root / backend["binding_index"]["path"]
        index = json.loads(index_path.read_text())
        index.pop("sha256")
        index["receipts"] = {
            system: descriptor(self.root, self.root / item["path"], base=index_path.parent)
            for system, item in backend["receipts"].items()
        }
        write_json(index_path, self_hashed(index))
        backend["binding_index"] = descriptor(self.root, index_path)
        write_json(self.fixture.manifest_path, manifest)

    def _coverage(self):
        return json.loads(self.receipt_path.read_text())["coverage"]

    def _calibration(self):
        return json.loads(self.calibration_path.read_text())

    def _set_measured_total(self, total: int) -> None:
        calibration = self._calibration()
        coordinates = [
            calibration["calibrations"][system]["costs"][branch][resource]
            for system in SYSTEMS for branch in BRANCHES for resource in RESOURCES
        ]
        quotient, remainder = divmod(total, len(coordinates))
        for position, row in enumerate(coordinates):
            row["samples"] = quotient + (position < remainder)
        coverage = self._coverage()
        coverage["accepted_sample_count"] = total
        self._rewrite_policy(coverage=coverage, calibration=calibration)

    def test_real_identity_reader_preserves_supported_minimum(self) -> None:
        result = self.fixture.load(production_policy=True)
        self.assertEqual(
            result["bindings"]["policy_qualification"]["receipt"],
            descriptor(self.root, self.receipt_path),
        )
        self.assertEqual(json.loads(self.receipt_path.read_text())["coverage"]["accepted_sample_count"], 3840)

    def test_real_identity_reader_preserves_126016_measured_samples(self) -> None:
        self._set_measured_total(126016)
        result = self.fixture.load(production_policy=True)
        self.assertEqual(
            result["bindings"]["policy_qualification"]["receipt"],
            descriptor(self.root, self.receipt_path),
        )
        self.assertEqual(json.loads(self.receipt_path.read_text())["coverage"]["accepted_sample_count"], 126016)

    def test_real_identity_reader_preserves_above_minimum_and_uneven_totals(self) -> None:
        for count in (3968, 3969):
            with self.subTest(count=count):
                self.fixture = Fixture(self.root)
                self._set_measured_total(count)
                result = self.fixture.load(production_policy=True)
                self.assertEqual(
                    result["bindings"]["policy_qualification"]["receipt"],
                    descriptor(self.root, self.receipt_path),
                )
                self.assertEqual(self._coverage()["accepted_sample_count"], count)

    def test_coverage_requires_exact_integer_counts_and_keys(self) -> None:
        changes = [
            (field, bad)
            for field, valid in self._coverage().items()
            for bad in (True, str(valid), float(valid), valid - 1)
        ]
        changes.extend((("missing", None), ("extra", 1)))
        for field, bad in changes:
            with self.subTest(field=field, value=bad):
                self.fixture = Fixture(self.root)
                coverage = self._coverage()
                if field == "missing":
                    coverage.pop("accepted_sample_count")
                elif field == "extra":
                    coverage["unsupported_count"] = bad
                else:
                    coverage[field] = bad
                self._rewrite_policy(coverage=coverage)
                with self.assertRaises(target.IdentityArtifactError):
                    self.fixture.load(production_policy=True)

    def test_calibration_requires_all_system_branch_resource_coordinates(self) -> None:
        for level in ("system", "branch", "resource"):
            for mutation in ("missing", "extra"):
                with self.subTest(level=level, mutation=mutation):
                    self.fixture = Fixture(self.root)
                    calibration = self._calibration()
                    if level == "system":
                        rows, key = calibration["calibrations"], SYSTEMS[0]
                    elif level == "branch":
                        rows, key = calibration["calibrations"][SYSTEMS[0]]["costs"], BRANCHES[0]
                    else:
                        rows = calibration["calibrations"][SYSTEMS[0]]["costs"][BRANCHES[0]]
                        key = RESOURCES[0]
                    if mutation == "missing":
                        rows.pop(key)
                    else:
                        rows["unsupported_coordinate"] = rows[key]
                    self._rewrite_policy(calibration=calibration)
                    with self.assertRaises(target.IdentityArtifactError):
                        self.fixture.load(production_policy=True)

    def test_calibration_rejects_noninteger_underbalanced_or_inconsistent_samples(self) -> None:
        for bad in (True, "120", 120.0, 119, 121):
            with self.subTest(samples=bad):
                self.fixture = Fixture(self.root)
                calibration = self._calibration()
                calibration["calibrations"][SYSTEMS[0]]["costs"][BRANCHES[0]][RESOURCES[0]]["samples"] = bad
                self._rewrite_policy(calibration=calibration)
                with self.assertRaises(target.IdentityArtifactError):
                    self.fixture.load(production_policy=True)

    def test_balanced_minimum_applies_even_when_total_agrees(self) -> None:
        calibration = self._calibration()
        costs = calibration["calibrations"][SYSTEMS[0]]["costs"][BRANCHES[0]]
        costs[RESOURCES[0]]["samples"] = 119
        costs[RESOURCES[1]]["samples"] = 121
        self._rewrite_policy(calibration=calibration)
        with self.assertRaises(target.IdentityArtifactError):
            self.fixture.load(production_policy=True)

    def test_calibration_implementation_is_bound_to_real_capability(self) -> None:
        calibration = self._calibration()
        calibration["calibrations"][SYSTEMS[0]]["costs"][BRANCHES[0]][RESOURCES[0]]["implementation_id"] = "foreign-implementation"
        self._rewrite_policy(calibration=calibration)
        with self.assertRaises(target.IdentityArtifactError):
            self.fixture.load(production_policy=True)

    def test_real_capability_validation_remains_active(self) -> None:
        capability = json.loads(self.capability_path.read_text())
        capability["systems"][SYSTEMS[0]]["branches"][BRANCHES[0]][RESOURCES[0]]["status"] = "unbound"
        self._rewrite_policy(capability=capability)
        with self.assertRaisesRegex(target.IdentityArtifactError, "capability manifest is not accepted"):
            self.fixture.load(production_policy=True)


if __name__ == "__main__":
    unittest.main()
