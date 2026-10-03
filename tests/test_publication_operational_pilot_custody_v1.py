"""The stock pilot commits capture separately and retains failed originals."""
from __future__ import annotations
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import publication_policy_qualification_pilot_executor_v2 as pilot
from publication_operational_request_domain_v1 import write_native_domain_v1
from tests.test_publication_operational_request_domain_v1 import authority, native_fixture, native_header


class OperationalPilotCustodyTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "attempt"
        attempt.mkdir()
        output = attempt / "pilot"
        output.mkdir()
        (output / "legacy.txt").write_bytes(b"original stock namespace")
        capture = attempt / "pilot.operational"
        capture.mkdir()
        runtime, records = native_fixture()
        descriptor = write_native_domain_v1(capture / "native_operational_requests.v1.jsonl",
            native_header(runtime, records), records, original_authority_validator=authority)
        request = SimpleNamespace(project_root=root, output_dir=output)
        contract = {"operational_capture": {"mode": "complete_qualification_operational_identity_v1",
            "output_dir": "request_output_dir_sibling_v1"}}
        final = root / "pilots/gstreamer_custom/cpu/h264/shared_video_dag"
        final.parent.mkdir(parents=True)
        return request, contract, final, capture, descriptor

    def test_stock_pilot_capture_commits_separately_and_keeps_original_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, contract, final, capture, descriptor = self.fixture(Path(tmp))
            original = copy.deepcopy(contract)
            pilot._commit_operational_capture_for_cell(request=request, contract=contract, final=final)
            target = Path(str(final) + ".operational") / "native_operational_requests.v1.jsonl"
            self.assertEqual(target.stat().st_size, descriptor["size_bytes"])
            self.assertEqual({p.name for p in request.output_dir.iterdir()}, {"legacy.txt"})
            self.assertFalse(capture.exists())
            self.assertEqual(contract, original)

    def test_capture_collision_retains_original_and_rejects_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            request, contract, final, capture, descriptor = self.fixture(Path(tmp))
            target = Path(str(final) + ".operational")
            target.mkdir()
            (target / "foreign.txt").write_bytes(b"foreign")
            with self.assertRaises(pilot.QualificationPilotExecutorV2Error):
                pilot._commit_operational_capture_for_cell(request=request, contract=contract, final=final)
            self.assertTrue(capture.is_dir())
            self.assertEqual((capture / "native_operational_requests.v1.jsonl").stat().st_size,
                             descriptor["size_bytes"])
            self.assertEqual((target / "foreign.txt").read_bytes(), b"foreign")

    def test_active_missing_capture_cannot_fall_back_to_legacy_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = SimpleNamespace(project_root=root, output_dir=root / "pilot")
            contract = {"operational_capture": {"mode": "complete_qualification_operational_identity_v1",
                "output_dir": "request_output_dir_sibling_v1"}}
            with self.assertRaises(pilot.QualificationPilotExecutorV2Error):
                pilot._commit_operational_capture_for_cell(request=request, contract=contract,
                                                           final=root / "final")
            self.assertIsNone(pilot._commit_operational_capture_for_cell(request=request,
                contract={}, final=root / "final"))


if __name__ == "__main__":
    unittest.main()
