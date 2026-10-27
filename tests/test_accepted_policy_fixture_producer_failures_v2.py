"""Producer mains preserve initiating exceptions; all external effects doubled."""
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(DIRECTORY))
import build_production_fixture_v2 as positive
import build_per_cell_minimum_refusal_v1 as negative
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader

NOW = 1_000_000_000
ABSOLUTE = NOW + 200_000_000_000


class InitiatingFailure(RuntimeError):
    pass


class SecondaryFailure(OSError):
    pass


class ProducerFailureTests(unittest.TestCase):
    def invoke(self, builder, *, fault, same=False):
        self.primary = InitiatingFailure("original observation failed")
        self.secondary = self.primary if same else SecondaryFailure("secondary controlled failure")
        self.now, self.head_calls, self.status_calls, self.proof_calls = NOW, 0, 0, 0
        self.clock_unavailable = False
        self.failure_report, self.after_report = None, None
        seal = {"path": "controlled-seal.json", "size_bytes": 1, "sha256": "b" * 64}
        clock = {"absolute_monotonic_ns": ABSOLUTE, "term_grace_ns": 5_000_000_000,
            "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}
        argv = [str(Path(builder.__file__)), "--project-root", str(ROOT),
            "--expected-source-commit", "a" * 40, "--artifact-base", str(ROOT / "controlled-artifacts"),
            "--namespace", "controlled", "--output-dir", str(ROOT / "controlled-output"), "--source-capture-dir", str(ROOT / "controlled-source-capture"),
            "--compiler-qualification-json", json.dumps(seal), "--compiler-admission-json", json.dumps(seal),
            "--compiler-deadline-ns", str(NOW + 100_000_000_000),
            "--reader-deadline-json", json.dumps(clock)]

        def git(root, *args, **kwargs):
            if args[0] == "rev-parse":
                self.head_calls += 1
                if fault == "git" and self.head_calls == 2:
                    raise self.secondary
                return b"a" * 40 + b"\n"
            if args[0] == "status":
                self.status_calls += 1
                return b""
            return b"controlled original guardian\n"

        def proof(*args, **kwargs):
            self.proof_calls += 1
            if self.proof_calls == 2:
                if fault == "proof":
                    raise self.secondary
                if fault == "expiry-after-proof":
                    self.now = ABSOLUTE
                if fault == "clock-after-proof":
                    self.clock_unavailable = True
            return {"original_exit_code": 0}

        def observations(*args, **kwargs):
            if fault == "expiry-before-proof":
                self.now = ABSOLUTE
            if fault == "clock-before-proof":
                self.clock_unavailable = True
            raise self.primary

        def clock():
            if self.clock_unavailable:
                raise self.secondary
            return self.now

        def report(path, value, **kwargs):
            if "failure" in path.name:
                self.failure_report = value
                if fault == "report":
                    raise self.secondary
            if path.name == "raw-source-after.v1.json":
                self.after_report = value
                if fault == "after-report":
                    raise self.secondary

        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(builder, "_fixture_source_capture_v2", return_value=nullcontext(object())))
            stack.enter_context(patch.object(builder, "_git", side_effect=git))
            if builder is negative:
                stack.enter_context(patch.object(builder, "_raw_committed_source_proof", side_effect=proof))
            stack.enter_context(patch.object(builder, "_fresh_json", side_effect=report))
            stack.enter_context(patch.object(builder, "_fixture_observation_maps_v2", side_effect=observations))
            stack.enter_context(patch.object(builder, "_fixture_entrypoint_sha256_v2", return_value="d" * 64))
            stack.enter_context(patch.object(builder, "_canonical_fixture_root_v2", return_value=ROOT))
            stack.enter_context(patch.object(builder, "_canonical_fixture_directory_v2",
                side_effect=lambda value, **kwargs: Path(value)))
            stack.enter_context(patch.object(Path, "is_dir", return_value=True))
            stack.enter_context(patch.object(Path, "exists", return_value=False))
            stack.enter_context(patch.object(provenance, "loaded_fixture_production_sources_v1", return_value=[]))
            self.preparation = stack.enter_context(patch.object(physical, "prepared_complete_fixture_inputs_v2"))
            stack.enter_context(patch.object(reader, "_monotonic_ns", side_effect=clock))
            stack.enter_context(patch.object(admission.time, "monotonic_ns", return_value=NOW))
            self.error = None
            try:
                builder.main()
            except BaseException as error:
                self.error = error
        self.preparation.assert_not_called()

    def test_positive_report_failure_keeps_original_and_distinct_secondary(self):
        for same in (False, True):
            with self.subTest(same_object=same):
                self.invoke(positive, fault="report", same=same)
                if same:
                    self.assertIs(self.error, self.primary)
                else:
                    self.assertIs(getattr(self.error, "primary", None), self.primary)
                    self.assertEqual(getattr(self.error, "secondary", None), (self.secondary,))
                    self.assertIs(self.error.__cause__, self.primary)

    def test_negative_finalization_keeps_primary_and_continues_independent_checks(self):
        for fault in ("report", "proof", "after-report", "git"):
            with self.subTest(fault=fault):
                self.invoke(negative, fault=fault)
                self.assertIs(getattr(self.error, "primary", None), self.primary)
                self.assertEqual(getattr(self.error, "secondary", None), (self.secondary,))
                self.assertIs(self.error.__cause__, self.primary)
                self.assertEqual((self.proof_calls, self.head_calls, self.status_calls), (2, 2, 2))

    def test_negative_expiry_prevents_remaining_source_spawns_without_losing_primary(self):
        for fault in ("expiry-before-proof", "expiry-after-proof"):
            with self.subTest(fault=fault):
                self.invoke(negative, fault=fault)
                self.assertIs(getattr(self.error, "primary", None), self.primary)
                secondary = getattr(self.error, "secondary", ())
                self.assertEqual(len(secondary), 1)
                self.assertIsInstance(secondary[0], ValueError)
                self.assertEqual(str(secondary[0]), "fixture source finalization deadline expired")
                self.assertEqual(self.proof_calls, 1 if fault == "expiry-before-proof" else 2)
                self.assertEqual((self.head_calls, self.status_calls), (1, 1))

    def test_negative_clock_failure_keeps_primary_and_stops_remaining_source_spawns(self):
        for fault in ("clock-before-proof", "clock-after-proof"):
            with self.subTest(fault=fault):
                self.invoke(negative, fault=fault)
                self.assertIs(getattr(self.error, "primary", None), self.primary)
                self.assertEqual(getattr(self.error, "secondary", None), (self.secondary,))
                self.assertIs(self.error.__cause__, self.primary)
                self.assertEqual(self.proof_calls, 1 if fault == "clock-before-proof" else 2)
                self.assertEqual((self.head_calls, self.status_calls), (1, 1))


if __name__ == "__main__":
    unittest.main()
