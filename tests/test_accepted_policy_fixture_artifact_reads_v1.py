"""Fixed-role physical fixture reads; no real files, compiler or native replay."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures import accepted_policy_physical_fixture_v2 as fixture


class ReadReached(Exception):
    """Stop the public pipeline exactly at the selected controlled read."""


class FixtureArtifactReadTests(unittest.TestCase):
    def setUp(self):
        self.root = Path.cwd()
        outputs = {key: str(self.root / key) for key in
                   ("measurement_dir", "native_domain", "process_receipt", "container_receipt")}
        original = {"container_image": "controlled", "outputs": outputs}
        self.payloads = {"candidate.json": b"{}", "original.json": json.dumps(original).encode(),
            "source.json": b'{"topology_kind":"shared_video_dag","streams":[]}',
            "calibration.json": b"{}", "native_operational_requests.v1.jsonl": b"{}\n",
            "runtime.json": b'{"bundles":[]}'}
        row = {"operation_id": "op", "phase": "ancillary", "policy": "cpu_only",
            "system": "gstreamer_custom", "codec": "h264", "run_id": "run", "arm_id": "arm",
            "original_operation": {"path": str(self.root / "original.json")},
            "descriptors": {role: {"path": str(self.root / name)} for role, name in
                            (("source_plan", "source.json"), ("calibration", "calibration.json"))},
            "front_workers_by_route": {}}
        self.prepared = {"root": self.root, "output_dir": self.root,
            "transaction": {"candidate_manifest_path": self.root / "candidate.json"},
            "capture_plan": {"operation_manifest": {"operations": [row]},
                "index": {"native_contexts": [{"operation_id": "op", "descriptor": {}}]},
                "native_contexts_by_id": {"op": {"native_header": {}}}},
            "engine": type("Engine", (), {"engine_socket": {}})(), "capture_engine": object(),
            "runtime": {"receipt_path": self.root / "runtime.json"}}

    def run_read(self, target, *, mode="observations", oversize=False, forward=False):
        calls, verifications, payloads = [], [], self.payloads

        class Custody:
            def __enter__(self):
                return self

            def __exit__(self, *ignored):
                return False

            def verify(self):
                verifications.append(True)

            def read_descriptor(self, path, *, label, maximum, capture=False):
                name = Path(path).name
                calls.append((name, maximum, capture))
                if name == target and oversize:
                    raise ValueError("controlled pre-allocation size refusal")
                if name == target and not forward:
                    raise ReadReached(name)
                raw = payloads[name]
                return {"path": name, "size_bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()}, raw if capture else None

        def old_read(path):
            if path.name == target:
                raise AssertionError("selected artifact still uses unbounded read_bytes")
            return payloads[path.name]

        with patch.object(PhysicalRootCustodyV1, "open", return_value=Custody()), \
                patch.object(Path, "read_bytes", autospec=True, side_effect=old_read), \
                patch.object(fixture, "_fixture_operation_sample_counts_v2", return_value={"op": 30}), \
                patch.object(fixture, "write_native_policy_fixture_cell_v2", return_value={}), \
                patch.object(fixture, "capture_original_fixture_operation_v1",
                    side_effect=ReadReached("capture boundary")) as capture:
            self.calls, self.verifications, self.capture = calls, verifications, capture
            if mode == "runtime":
                return fixture.finalize_fixture_qualification_cells_v2(
                    prepared=self.prepared, native={"operations": []},
                    guardian_authority_path=self.root / "unused-authority")
            if mode == "patch":
                images, probes = {}, {}
                for number, system in enumerate(("openvino_gva", "gstreamer_custom"), 1):
                    image_id = "sha256:" + str(number) * 64
                    images[image_id] = {"Id": image_id}
                    probes[system] = {}
                return fixture._fixture_command_replies_v2(identity_patch_path=self.root / target,
                    image_inspections=images, device_probes=probes)
            return fixture.build_original_native_fixture_observations_v2(prepared=self.prepared)

    def check_role(self, target, maximum, *, mode="observations"):
        with self.assertRaisesRegex(ReadReached, target):
            self.run_read(target, mode=mode)
        self.assertEqual(self.calls[-1], (target, maximum, True))
        self.capture.assert_not_called()

    def test_candidate_capability_is_bounded_before_json(self):
        self.check_role("candidate.json", 16 * 1024**2)

    def test_original_operation_is_bounded_before_json(self):
        self.check_role("original.json", 1024**2)

    def test_source_plan_is_bounded_before_json(self):
        self.check_role("source.json", 16 * 1024**2)

    def test_calibration_is_bounded_before_json(self):
        self.check_role("calibration.json", 16 * 1024**2)

    def test_native_payload_is_bounded_before_capture(self):
        self.check_role("native_operational_requests.v1.jsonl", 64 * 1024**2)

    def test_runtime_receipt_is_bounded_before_json(self):
        self.check_role("runtime.json", 64 * 1024**2, mode="runtime")

    def test_identity_patch_is_bounded_before_json(self):
        self.check_role("patch.json", 16 * 1024**2, mode="patch")

    def test_oversized_native_payload_never_reaches_capture(self):
        with self.assertRaisesRegex(ValueError, "pre-allocation size"):
            self.run_read("native_operational_requests.v1.jsonl", oversize=True)
        self.capture.assert_not_called()

    def test_valid_original_native_bytes_are_forwarded_unchanged_after_custody(self):
        with self.assertRaisesRegex(ReadReached, "capture boundary"):
            self.run_read("native_operational_requests.v1.jsonl", forward=True)
        self.assertEqual(self.capture.call_args.kwargs["native_domain_payload"], b"{}\n")
        self.assertEqual(len(self.verifications), 5)
        self.assertEqual([maximum for _, maximum, _ in self.calls],
                         [16 * 1024**2, 1024**2, 16 * 1024**2, 16 * 1024**2, 64 * 1024**2])


if __name__ == "__main__":
    unittest.main()
