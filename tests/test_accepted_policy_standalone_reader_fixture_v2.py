"""Actual standalone reader command/refusal boundary, not full acceptance."""
from pathlib import Path
import hashlib
import json
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AcceptedPolicyStandaloneReaderFixtureV2Tests(unittest.TestCase):
    def test_fresh_interpreter_uses_actual_default_reader_and_preserves_real_refusal(self):
        from tests.fixtures.accepted_policy_standalone_reader_fixture_v2 import run_fixture_standalone_guardian_cold_reader_v2

        with tempfile.TemporaryDirectory(prefix="accepted-policy-standalone-boundary-") as raw:
            output = Path(raw)
            guardian = {"contract_path": ROOT / "artifacts" / output.name / "missing-contract.json",
                        "receipt_path": ROOT / "artifacts" / output.name / "missing-receipt.json",
                        "preprocessing_contract_sha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "fresh standalone default guardian reader refused"):
                run_fixture_standalone_guardian_cold_reader_v2(
                    project_root=ROOT, output_dir=output, guardian=guardian,
                    accepted_capability_path=ROOT / "artifacts" / output.name / "missing-capability.json",
                    deadline={"absolute_monotonic_ns": time.monotonic_ns() + 64_000_000_000,
                              "term_grace_ns": 1_000_000_000, "kill_grace_ns": 1_000_000_000,
                              "final_ns": 2_000_000_000})
            result = json.loads((output / "standalone-guardian-cold-reader.result.v2.json").read_bytes())
            self.assertNotEqual(result["original_exit_code"], 0)
            self.assertFalse(result["standalone_guardian_cold_reader_passed"])
            self.assertEqual(result["command"][1:3], ["-B", "-c"])
            self.assertEqual(result["cwd"], str(ROOT))
            self.assertEqual(result["expected_default_module_path"],
                             str(ROOT / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"))
            self.assertEqual(result["expected_default_module_sha256"], hashlib.sha256(
                (ROOT / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py").read_bytes()).hexdigest())
            self.assertEqual(result["stdout_bytes"], len((output / "standalone-guardian-cold-reader.stdout.raw").read_bytes()))
            stderr = (output / "standalone-guardian-cold-reader.stderr.raw").read_bytes()
            self.assertEqual(result["stderr_bytes"], len(stderr))
            self.assertIn(b"AcceptedPolicyGuardianPreprocessingContractV1Error", stderr)
            self.assertIn(b"accepted-policy preprocessing contract", stderr)
            self.assertFalse((ROOT / "artifacts" / output.name).exists())


if __name__ == "__main__":
    unittest.main()
