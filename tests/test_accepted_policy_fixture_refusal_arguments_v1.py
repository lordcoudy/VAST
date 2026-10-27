"""Negative-29 caller admission arguments; all external effects are doubled."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
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
DRIVER = DIRECTORY / "build_per_cell_minimum_refusal_v1.py"
spec = importlib.util.spec_from_file_location("_fixture_refusal_arguments_v1_control", DRIVER)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader


class PreparationReached(AssertionError):
    pass


class FixtureRefusalArgumentsTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000_000
        self.qualification = {"path": "controlled-qualification.json", "size_bytes": 1, "sha256": "b" * 64}
        self.admission = {"path": "controlled-admission.json", "size_bytes": 1, "sha256": "c" * 64}
        self.compiler_deadline = self.now + 100_000_000_000
        self.reader_deadline = {"absolute_monotonic_ns": self.now + 200_000_000_000,
            "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}

    def run_driver(self, *, missing=False, expired=False, compiler_expired=False,
                   oversized=False, nonobject=False, overrides=None):
        argv = [str(DRIVER), "--project-root", str(ROOT), "--expected-source-commit", "a" * 40,
            "--artifact-base", str(ROOT / "controlled-artifacts"), "--namespace", "controlled",
            "--output-dir", str(ROOT / "controlled-output")]
        deadline = {**self.reader_deadline, "absolute_monotonic_ns": self.now} if expired else self.reader_deadline
        if not missing:
            qualification = " " * 4097 if oversized else "[]" if nonobject else json.dumps(self.qualification)
            argv += ["--compiler-qualification-json", qualification,
                     "--compiler-admission-json", json.dumps(self.admission),
                     "--compiler-deadline-ns", str(self.now if compiler_expired else self.compiler_deadline),
                     "--reader-deadline-json", json.dumps(deadline)]
            if overrides is not None:
                argv += ["--qualification-samples-json", json.dumps(overrides)]
        prep = Mock(side_effect=PreparationReached())

        def git_reply(root, *args, **kwargs):
            return b"a" * 40 + b"\n" if args[0] == "rev-parse" else b""

        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(sys, "argv", argv))
            self.git = stack.enter_context(patch.object(builder, "_git", side_effect=git_reply))
            self.raw_proof = stack.enter_context(patch.object(builder, "_raw_committed_source_proof",
                return_value={"original_exit_code": 0}))
            stack.enter_context(patch.object(builder, "_fresh_json"))
            stack.enter_context(patch.object(builder, "_canonical_fixture_root_v2", return_value=ROOT))
            stack.enter_context(patch.object(builder, "_canonical_fixture_directory_v2",
                side_effect=lambda value, **kwargs: Path(value)))
            stack.enter_context(patch.object(Path, "read_bytes", return_value=b"{}"))
            stack.enter_context(patch.object(Path, "is_dir", return_value=False))
            stack.enter_context(patch.object(provenance, "loaded_fixture_production_sources_v1", return_value=[]))
            stack.enter_context(patch.object(physical, "prepared_complete_fixture_inputs_v2", prep))
            stack.enter_context(patch.object(reader, "_monotonic_ns", return_value=self.now))
            stack.enter_context(patch.object(admission.time, "monotonic_ns", return_value=self.now))
            self.preparation = prep
            self.error = None
            try:
                builder.main()
            except BaseException as error:
                self.error = error

    def test_original_compiler_seals_and_absolute_deadline_reach_preparation(self):
        self.run_driver()
        self.assertIsInstance(self.error, PreparationReached)
        kwargs = self.preparation.call_args.kwargs
        self.assertEqual(kwargs.get("compiler_qualification"), self.qualification)
        self.assertEqual(kwargs.get("compiler_admission"), self.admission)
        self.assertEqual(kwargs.get("compiler_absolute_deadline_ns"), self.compiler_deadline)

    def test_missing_execution_arguments_refuse_before_git_raw_proof_or_preparation(self):
        self.run_driver(missing=True)
        self.assertIsInstance(self.error, SystemExit)
        self.assertEqual(self.error.code, 2)
        self.git.assert_not_called()
        self.raw_proof.assert_not_called()
        self.preparation.assert_not_called()

    def test_expired_clocks_refuse_before_git_raw_proof_or_preparation(self):
        for keyword in ("expired", "compiler_expired"):
            with self.subTest(clock=keyword):
                self.run_driver(**{keyword: True})
                expected = admission.executor.FixtureCompilerError if keyword == "compiler_expired" else ValueError
                self.assertIsInstance(self.error, expected)
                self.git.assert_not_called()
                self.raw_proof.assert_not_called()
                self.preparation.assert_not_called()

    def test_bounded_object_arguments_refuse_before_git_raw_proof_or_preparation(self):
        for keyword in ("oversized", "nonobject"):
            with self.subTest(argument=keyword):
                self.run_driver(**{keyword: True})
                self.assertIsInstance(self.error, ValueError)
                self.git.assert_not_called()
                self.raw_proof.assert_not_called()
                self.preparation.assert_not_called()

    def test_fixed_refusal_recipe_rejects_positive_count_overrides_before_git(self):
        for overrides in ({}, {"controlled-operation": 30}):
            with self.subTest(overrides=overrides):
                self.run_driver(overrides=overrides)
                self.assertIsInstance(self.error, ValueError)
                self.git.assert_not_called()
                self.raw_proof.assert_not_called()
                self.preparation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
