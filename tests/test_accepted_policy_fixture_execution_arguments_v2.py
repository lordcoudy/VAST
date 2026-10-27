"""Literal producer execution arguments; every external effect is doubled."""
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
DRIVER = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py"
spec = importlib.util.spec_from_file_location("_fixture_execution_arguments_v2_control", DRIVER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures import accepted_policy_consumer_fixture_v2 as consumer
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader


class PreparationReached(AssertionError):
    pass


class ConsumersReached(AssertionError):
    pass


class FixtureExecutionArgumentsTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.qualification = {"path": "controlled-qualification.json", "size_bytes": 1, "sha256": "b" * 64}
        self.admission = {"path": "controlled-admission.json", "size_bytes": 1, "sha256": "c" * 64}
        self.compiler_deadline = self.now + 100_000_000_000
        self.reader_deadline = {"absolute_monotonic_ns": self.now + 200_000_000_000,
            "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}

    def run_driver(self, *, missing=False, expired=False, oversized=False, nonobject=False,
                   samples=30, reach_consumers=False, overrides=None, finish=False):
        argv = [str(DRIVER), "--project-root", str(ROOT), "--expected-source-commit", "a" * 40,
            "--artifact-base", str(ROOT / "controlled-artifacts"), "--namespace", "controlled",
            "--output-dir", str(ROOT / "controlled-output"), "--source-capture-dir", str(ROOT / "controlled-source-capture"), "--samples-per-branch", str(samples)]
        deadline = {**self.reader_deadline, "absolute_monotonic_ns": self.now} if expired else self.reader_deadline
        if not missing:
            qualification = " " * 4097 if oversized else "[]" if nonobject else json.dumps(self.qualification)
            argv += ["--compiler-qualification-json", qualification,
                     "--compiler-admission-json", json.dumps(self.admission),
                     "--compiler-deadline-ns", str(self.compiler_deadline),
                     "--reader-deadline-json", json.dumps(deadline)]
            if overrides is not None:
                argv += ["--qualification-samples-json", json.dumps(overrides)]
        prepared = {"transaction": {"transaction_receipt_path": ROOT / "transaction"},
            "preprocessing": {"receipt_path": ROOT / "preprocessing"},
            "capture_plan_descriptor": {}, "runtime": {"receipt_path": ROOT / "runtime"},
            "capture_plan": {"operation_manifest": {"operations": [
                {"operation_id": "q" + str(index), "phase": "qualification_cell"} for index in range(32)] + [
                {"operation_id": "aux" + str(index), "phase": "ancillary"} for index in range(5)]}}}
        prep = Mock(return_value=nullcontext(prepared)) if reach_consumers else Mock(side_effect=PreparationReached())
        done = Mock(return_value={"assessment": {"coverage": {"accepted_sample_count": 126016}}}) if finish else Mock(side_effect=ConsumersReached())

        def git_reply(root, *args, **kwargs):
            return b"a" * 40 + b"\n" if args[0] == "rev-parse" else b"" if args[0] == "status" else b"controlled original source\n"

        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(builder, "_fixture_source_capture_v2", return_value=nullcontext(object())))
            self.git = stack.enter_context(patch.object(builder, "_git", side_effect=git_reply))
            self.reporter = stack.enter_context(patch.object(builder, "_fresh_json"))
            stack.enter_context(patch.object(builder, "_fixture_observation_maps_v2", return_value=({}, {}), create=True))
            stack.enter_context(patch.object(builder, "_fixture_entrypoint_sha256_v2", return_value="d" * 64, create=True))
            stack.enter_context(patch.object(builder, "_canonical_fixture_root_v2", return_value=ROOT))
            stack.enter_context(patch.object(builder, "_canonical_fixture_directory_v2", side_effect=lambda value, **kwargs: Path(value)))
            stack.enter_context(patch.object(Path, "read_bytes", return_value=b"{}"))
            stack.enter_context(patch.object(Path, "is_dir", return_value=False))
            stack.enter_context(patch.object(provenance, "loaded_fixture_production_sources_v1", return_value=[]))
            stack.enter_context(patch.object(physical, "prepared_complete_fixture_inputs_v2", prep))
            self.native = stack.enter_context(patch.object(physical, "build_original_native_fixture_observations_v2", return_value={
                "operations": [], "qualification_count": 0, "native_domains": []}))
            stack.enter_context(patch.object(consumer, "complete_fixture_production_consumers_v2", done))
            stack.enter_context(patch.object(reader, "_monotonic_ns", return_value=self.now))
            stack.enter_context(patch.object(admission.time, "monotonic_ns", return_value=self.now))
            self.preparation, self.consumers = prep, done
            self.error = None
            try:
                builder.main()
            except BaseException as error:
                self.error = error

    def test_explicit_compiler_seals_and_original_deadline_are_forwarded(self):
        self.run_driver()
        self.assertIsInstance(self.error, PreparationReached)
        kwargs = self.preparation.call_args.kwargs
        self.assertEqual(kwargs.get("compiler_qualification"), self.qualification)
        self.assertEqual(kwargs.get("compiler_admission"), self.admission)
        self.assertEqual(kwargs.get("compiler_absolute_deadline_ns"), self.compiler_deadline)

    def test_reader_clock_is_forwarded_to_complete_consumer(self):
        self.run_driver(reach_consumers=True)
        self.assertIsInstance(self.error, ConsumersReached)
        self.assertEqual(self.consumers.call_args.kwargs.get("standalone_reader_deadline"), self.reader_deadline)

    def test_missing_execution_arguments_refuse_before_git_or_preparation(self):
        self.run_driver(missing=True)
        self.assertIsInstance(self.error, SystemExit)
        self.assertEqual(self.error.code, 2)
        self.git.assert_not_called()
        self.preparation.assert_not_called()

    def test_expired_reader_clock_refuses_before_git_or_preparation(self):
        self.run_driver(expired=True)
        self.assertIsInstance(self.error, ValueError)
        self.git.assert_not_called()
        self.preparation.assert_not_called()

    def test_argument_json_is_bounded_and_object_only_before_git(self):
        for keyword in ("oversized", "nonobject"):
            with self.subTest(kind=keyword):
                self.run_driver(**{keyword: True})
                self.assertIsInstance(self.error, ValueError)
                self.git.assert_not_called()
                self.preparation.assert_not_called()

    def test_unsupported_global_sample_count_refuses_before_git(self):
        self.run_driver(samples=986)
        self.assertIsInstance(self.error, ValueError)
        self.git.assert_not_called()
        self.preparation.assert_not_called()

    def test_mixed126016_overrides_are_forwarded_and_counted_from_fixed_plan(self):
        overrides = {"q" + str(index): 984 for index in range(16)}
        self.run_driver(samples=985, reach_consumers=True, overrides=overrides, finish=True)
        self.assertIsNone(self.error)
        self.assertEqual(self.native.call_args.kwargs.get("qualification_samples_by_operation_id"), overrides)
        self.assertEqual(self.reporter.call_args.args[1]["expected_measured_sample_count"], 126016)

    def test_override_cardinality_and_value_types_refuse_before_git(self):
        for overrides in ({"q" + str(index): 30 for index in range(33)}, {"q0": True}, {"q0": 986}):
            with self.subTest(overrides=overrides):
                self.run_driver(overrides=overrides)
                self.assertIsInstance(self.error, ValueError)
                self.git.assert_not_called()
                self.preparation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
