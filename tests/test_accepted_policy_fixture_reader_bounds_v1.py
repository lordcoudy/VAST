"""Fixture I/O adapters use bounded custody; every case is I/O-only."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_policy_qualification import CALIBRATION_MAPPING_FILENAME, QUALIFICATION_RECEIPT_FILENAME
import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
from tests.fixtures import accepted_policy_consumer_assertions_v1 as assertions
from tests.fixtures import accepted_policy_consumer_fixture_v2 as consumer
from tests.fixtures import accepted_policy_guardian_journal_fixture_v1 as journal


class CustodyDouble:
    """Small data-only adapter double; the production custody API is unchanged."""
    def __init__(self, root, payloads):
        self.root, self.payloads, self.calls, self.verifications = root, payloads, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        return False

    def verify(self):
        self.verifications += 1

    def read_descriptor(self, value, *, label, maximum, capture=False):
        self.calls.append((Path(value).name, maximum, capture))
        path = Path(value)
        payload = self.payloads[path.name]
        if len(payload) > maximum:
            raise ValueError("controlled bounded read refusal")
        relative = path.relative_to(self.root).as_posix() if path.is_absolute() else path.as_posix()
        descriptor = {"path": relative, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        return descriptor, payload if capture else None


class FixtureReaderBoundsTests(unittest.TestCase):
    def test_both_descriptors_stream_without_whole_file_capture(self):
        root = Path.cwd()
        for module in (consumer, assertions):
            custody = CustodyDouble(root, {"artifact.json": b'{"value":1}\n'})
            with self.subTest(module=module.__name__), \
                    patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("descriptor allocated whole file")):
                result = module._descriptor(root, root / "artifact.json")
                self.assertEqual(result["sha256"], hashlib.sha256(b'{"value":1}\n').hexdigest())
                self.assertEqual(custody.calls, [("artifact.json", 64 * 1024**2, False)])
                self.assertGreater(custody.verifications, 0)

    def test_descriptor_fields_and_byte_hash_remain_unchanged(self):
        root, payload = Path.cwd(), b'{"value":1}\n'
        expected = {"path": "artifact.json", "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for module in (consumer, assertions):
            custody = CustodyDouble(root, {"artifact.json": payload})
            with self.subTest(module=module.__name__), \
                    patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                    patch.object(Path, "read_bytes", return_value=payload):
                self.assertEqual(module._descriptor(root, root / "artifact.json"), expected)

    def test_operational_binding_passes_distinct_decision_and_ingress_limits(self):
        root = Path.cwd()
        prepared = {"root": root, "output_dir": root / "output-never-created", "capture_plan_descriptor": {}}
        native = {"operations": [{"operation": {"operation_id": "op"},
            "capture": {key: {} for key in ("native_domain", "process_receipt", "container_receipt")},
            "original": {"outputs": {"measurement_dir": str(root / "measurement-never-created")}}}]}
        with patch.object(consumer, "_descriptor", return_value={}) as descriptor, \
                patch.object(consumer, "write_operational_execution_binding_v1"):
            consumer._write_fixture_operational_binding_v2(prepared=prepared, native=native,
                journals={"operational_group": {}})
        self.assertEqual([call.kwargs.get("maximum") for call in descriptor.call_args_list],
                         [64 * 1024**2, 1024**2])

    def test_runtime_probe_json_uses_bounded_custody_capture(self):
        root, payload = Path.cwd(), b'{"probe":true}\n'
        custody = CustodyDouble(root, {"probe.json": payload})
        with patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("runtime probe allocated unbounded bytes")):
            self.assertEqual(consumer._json(root / "probe.json"), {"probe": True})
        self.assertEqual(custody.calls, [("probe.json", 64 * 1024**2, True)])
        self.assertGreater(custody.verifications, 0)

    def test_runtime_probe_json_refuses_nonobject_shape(self):
        root, payload = Path.cwd(), b"[]"
        custody = CustodyDouble(root, {"probe.json": payload})
        with patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                patch.object(Path, "read_bytes", return_value=payload):
            with self.assertRaisesRegex(ValueError, "object"):
                consumer._json(root / "probe.json")

    def test_runtime_probe_json_preserves_valid_object(self):
        root, payload = Path.cwd(), b'{"probe":true}\n'
        custody = CustodyDouble(root, {"probe.json": payload})
        with patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                patch.object(Path, "read_bytes", return_value=payload):
            self.assertEqual(consumer._json(root / "probe.json"), {"probe": True})

    def test_fixture_coverage_duplicate_reads_are_bounded(self):
        root = Path.cwd()
        receipt = {"coverage": {"binding_count": 32, "pilot_cell_count": 32,
            "minimum_samples_per_branch_cell": 30, "accepted_sample_count": 3840}}
        calibration = {"calibrations": {"controlled": {"costs": {"damage": {
            "cpu": {"samples": 120}, "gpu": {"samples": 120}}}}}}
        custody = CustodyDouble(root, {QUALIFICATION_RECEIPT_FILENAME: json.dumps(receipt).encode("ascii"),
            CALIBRATION_MAPPING_FILENAME: json.dumps(calibration).encode("ascii")})
        # This test checks duplicate-read I/O only. It does not validate a cohort.
        with patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("coverage read is unbounded")), \
                patch.object(guardian, "_validate_measured_coverage",
                    side_effect=guardian.AcceptedPolicyGuardianPreprocessingContractV1Error("controlled I/O-only refusal")):
            result = assertions.check_fixture_measured_coverage_refusals_v1(accepted_dir=root)
        self.assertEqual(len(result), 21)
        self.assertTrue(all(row["refused"] for row in result))
        self.assertEqual(custody.calls, [(QUALIFICATION_RECEIPT_FILENAME, 64 * 1024**2, True),
                                        (CALIBRATION_MAPPING_FILENAME, 64 * 1024**2, True)])
        self.assertGreater(custody.verifications, 0)

    def journal_case(self, *, changed, same_length=False):
        root = Path.cwd()
        payload = (b"[]" if same_length else b"changed") if changed else b"{}"
        descriptor = {"path": str(root / "companion.json"), "size_bytes": 2,
                      "sha256": hashlib.sha256(b"{}").hexdigest()}
        custody = CustodyDouble(root, {"companion.json": payload})

        class RecorderDouble:
            def finish(self, counters):
                return descriptor

            def close(self):
                pass

        with patch.object(journal, "GuardianOperationalRecorder", return_value=RecorderDouble()), \
                patch.object(PhysicalRootCustodyV1, "open", return_value=custody), \
                patch.object(Path, "read_bytes", side_effect=None if changed else AssertionError("companion allocated whole file"),
                    return_value=payload):
            if changed:
                with self.assertRaisesRegex(ValueError, "descriptor changed"):
                    journal.write_fixture_guardian_operational_journals_v1(
                        output_dir=root, headers_by_route={}, native_domains=[], capability_manifest={})
            else:
                result = journal.write_fixture_guardian_operational_journals_v1(
                    output_dir=root, headers_by_route={}, native_domains=[], capability_manifest={})
                self.assertEqual(result["operational_group"], descriptor)
                self.assertEqual(custody.calls, [("companion.json", 1024**2, False)])
                self.assertGreater(custody.verifications, 0)

    def test_companion_hash_streams_under_its_own_one_mib_role(self):
        self.journal_case(changed=False)

    def test_companion_size_hash_drift_still_refuses(self):
        for same_length in (False, True):
            with self.subTest(same_length=same_length):
                self.journal_case(changed=True, same_length=same_length)


if __name__ == "__main__":
    unittest.main()
