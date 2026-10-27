"""Literal caller read roles using existing custody API; all I/O is doubled."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(DIRECTORY))
import build_production_fixture_v2 as positive
import build_per_cell_minimum_refusal_v1 as negative
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader


class PreparationReached(AssertionError):
    pass


class LiteralReadBoundsTests(unittest.TestCase):
    def run_driver(self, builder, *, forbid="maps", drift=None, payload=b"{}"):
        now = 1_000_000_000
        driver = Path(builder.__file__)
        seal = {"path": "controlled-seal.json", "size_bytes": 1, "sha256": "b" * 64}
        clock = {"absolute_monotonic_ns": now + 200_000_000_000,
            "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}
        argv = [str(driver), "--project-root", str(ROOT), "--expected-source-commit", "a" * 40,
            "--artifact-base", str(ROOT / "controlled-artifacts"), "--namespace", "controlled",
            "--output-dir", str(ROOT / "controlled-output"),
            "--compiler-qualification-json", json.dumps(seal), "--compiler-admission-json", json.dumps(seal),
            "--compiler-deadline-ns", str(now + 100_000_000_000), "--reader-deadline-json", json.dumps(clock)]
        maps = {"image-inspect-map.json", "device-probe-map.json"}

        def unbounded_read(path):
            if (forbid == "maps" and path.name in maps) or (forbid == "entrypoint" and path == driver):
                raise AssertionError("literal caller attempted an unbounded read")
            return payload if path.name in maps else b"{}"

        def git_reply(root, *args, **kwargs):
            return b"a" * 40 + b"\n" if args[0] == "rev-parse" else b""

        def captured_read(path, **kwargs):
            return ({"sha256": "d" * 64}, None) if path == driver else ({}, payload)

        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(builder, "_git", side_effect=git_reply))
            if builder is negative:
                stack.enter_context(patch.object(builder, "_raw_committed_source_proof",
                    return_value={"original_exit_code": 0}))
            stack.enter_context(patch.object(builder, "_fresh_json"))
            stack.enter_context(patch.object(builder, "_canonical_fixture_root_v2", return_value=ROOT))
            stack.enter_context(patch.object(builder, "_canonical_fixture_directory_v2",
                side_effect=lambda value, **kwargs: Path(value)))
            stack.enter_context(patch.object(Path, "read_bytes", side_effect=unbounded_read, autospec=True))
            stack.enter_context(patch.object(Path, "is_dir", return_value=False))
            stack.enter_context(patch.object(provenance, "loaded_fixture_production_sources_v1", return_value=[]))
            self.preparation = stack.enter_context(patch.object(physical, "prepared_complete_fixture_inputs_v2",
                side_effect=PreparationReached()))
            opened = stack.enter_context(patch.object(PhysicalRootCustodyV1, "open"))
            opened.return_value.__exit__.return_value = False
            custody = opened.return_value.__enter__.return_value
            custody.read_descriptor.side_effect = captured_read
            custody.verify.side_effect = drift
            stack.enter_context(patch.object(reader, "_monotonic_ns", return_value=now))
            stack.enter_context(patch.object(admission.time, "monotonic_ns", return_value=now))
            self.error = None
            try:
                builder.main()
            except BaseException as error:
                self.error = error
            self.reads = list(custody.read_descriptor.call_args_list)

    def test_observation_maps_use_two_fixed_16mib_captures_before_preparation(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                self.run_driver(builder)
                self.assertIsInstance(self.error, PreparationReached)
                selected = [call for call in self.reads if call.args[0].name in
                    {"image-inspect-map.json", "device-probe-map.json"}]
                self.assertEqual({call.args[0].name for call in selected},
                    {"image-inspect-map.json", "device-probe-map.json"})
                self.assertEqual(len(selected), 2)
                for call in selected:
                    self.assertEqual(call.kwargs["maximum"], 16 * 1024**2)
                    self.assertIs(call.kwargs["capture"], True)

    def test_entrypoint_hash_streams_the_existing_2mib_role(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                self.run_driver(builder, forbid="entrypoint")
                self.assertIsInstance(self.error, PreparationReached)
                selected = [call for call in self.reads if call.args[0] == Path(builder.__file__)]
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0].kwargs["maximum"], 2 * 1024**2)
                self.assertIs(selected[0].kwargs["capture"], False)

    def test_custody_drift_refuses_before_preparation(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                failure = RuntimeError("controlled custody drift")
                self.run_driver(builder, forbid="", drift=failure)
                self.assertIs(self.error, failure)
                self.preparation.assert_not_called()

    def test_nonobject_maps_refuse_before_preparation(self):
        for builder in (positive, negative):
            for payload in (b"[]", b"null", b"true", b"0", b'"value"'):
                with self.subTest(caller=builder.__name__, payload=payload):
                    self.run_driver(builder, forbid="", payload=payload)
                    self.assertIsInstance(self.error, ValueError)
                    self.preparation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
