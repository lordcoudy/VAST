"""Producer report clocks and returned persistence facts; all I/O is doubled."""
from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"))
import build_production_fixture_v2 as positive
import build_per_cell_minimum_refusal_v1 as negative
from tests.fixtures import accepted_policy_fixture_compiler_admission_v1 as admission
from tests.fixtures import accepted_policy_fixture_provenance_v1 as provenance
from tests.fixtures import accepted_policy_physical_fixture_v2 as physical
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader

NOW = 1_000_000_000
ABSOLUTE = NOW + 200_000_000_000


def complete_facts(count):
    return {"attempted": True, "written_bytes": count, "write_extent_unknown": False,
        "fsync_completed": True, "close_completed": True, "causes": []}


class PreparationReached(AssertionError):
    pass


class ProducerReportPersistenceTests(unittest.TestCase):
    def invoke(self, value, *, clock=ABSOLUTE, missing=False, facts=None,
               ticks=None, linesep="\n", encode=False):
        self.error, self.result = None, None
        raw = b'{"value":1}' + linesep.encode("ascii")
        self.facts = complete_facts(len(raw)) if facts is None else facts
        with ExitStack() as stack:
            self.opened = stack.enter_context(patch.object(Path, "open"))
            self.opened.return_value.__enter__.return_value.write.return_value = len(raw)
            self.persist = stack.enter_context(patch.object(reader, "_write_result_v2", return_value=self.facts))
            stack.enter_context(patch.object(reader, "_monotonic_ns",
                side_effect=ticks if ticks is not None else lambda: NOW))
            stack.enter_context(patch.object(positive.os, "linesep", linesep))
            if encode:
                from tests.fixtures import accepted_policy_fixture_report_v1 as report
                self.encoder = stack.enter_context(patch.object(report, "fixture_report_bytes_v1",
                    return_value=b'{"value":1}\n'))
            kwargs = {} if missing else {"absolute_deadline_ns": clock}
            try:
                self.result = positive._fresh_json(ROOT / "controlled-report.json", value, **kwargs)
            except BaseException as error:
                self.error = error

    def test_missing_clock_refuses_before_old_text_writer(self):
        self.invoke({"value": 1}, missing=True, encode=True)
        self.assertIsInstance(self.error, ValueError)
        self.encoder.assert_not_called()
        self.opened.assert_not_called()
        self.persist.assert_not_called()

    def test_invalid_or_expired_clock_refuses_before_encoding_or_io(self):
        for clock in (False, 1.0, 0, NOW, NOW - 1):
            with self.subTest(clock=clock):
                self.invoke({"value": 1}, clock=clock, encode=True)
                self.assertIsInstance(self.error, ValueError)
                self.encoder.assert_not_called()
                self.opened.assert_not_called()
                self.persist.assert_not_called()

    def test_same_absolute_clock_and_native_newline_reach_existing_writer(self):
        for linesep in ("\n", "\r\n"):
            with self.subTest(linesep=linesep):
                self.invoke({"value": 1}, linesep=linesep)
                self.assertIsNone(self.error)
                self.assertIs(self.result, self.facts)
                self.opened.assert_not_called()
                self.persist.assert_called_once_with(ROOT / "controlled-report.json",
                    b'{"value":1}' + linesep.encode("ascii"), ABSOLUTE)

    def test_encoding_that_consumes_remaining_clock_never_opens_output(self):
        self.invoke({"value": 1}, ticks=[NOW, ABSOLUTE], encode=True)
        self.assertIsInstance(self.error, ValueError)
        self.encoder.assert_called_once()
        self.persist.assert_not_called()
        self.opened.assert_not_called()

    def test_incomplete_persistence_preserves_exact_returned_facts(self):
        faults = [
            {"attempted": False, "written_bytes": 0, "fsync_completed": False,
                "close_completed": False, "causes": ["result_open"]},
            {"written_bytes": 1, "causes": ["result_short_write"]},
            {"write_extent_unknown": True, "causes": ["result_write"]},
            {"fsync_completed": False, "close_completed": False,
                "causes": ["result_fsync", "result_close"]},
            {"fsync_completed": False},
            {"close_completed": False},
        ]
        for fault in faults:
            with self.subTest(fault=fault):
                facts = {**complete_facts(12), **copy.deepcopy(fault)}
                self.invoke({"value": 1}, facts=facts)
                self.assertIsNotNone(self.error)
                self.assertIs(getattr(self.error, "facts", None), facts)
                self.assertEqual(getattr(self.error, "causes", None), facts["causes"])
                self.opened.assert_not_called()

    def test_late_persistence_cannot_be_accepted_as_complete(self):
        for causes in ([], ["result_fsync", "result_close"]):
            with self.subTest(original_causes=causes):
                facts = {**complete_facts(12), "causes": causes.copy()}
                before = copy.deepcopy(facts)
                self.invoke({"value": 1}, facts=facts, ticks=[NOW, NOW, ABSOLUTE])
                self.assertIsNotNone(self.error)
                self.assertIs(getattr(self.error, "facts", None), facts)
                self.assertEqual(facts, before)
                self.assertEqual(getattr(self.error, "causes", None),
                    causes + ["fixture_report_deadline_exceeded"])
                self.persist.assert_called_once()

    def test_clock_failure_after_writer_retains_original_facts_and_clock_error(self):
        for causes in ([], ["result_fsync", "result_close"]):
            with self.subTest(original_causes=causes):
                facts = {**complete_facts(12), "causes": causes.copy()}
                if causes:
                    facts.update(fsync_completed=False, close_completed=False)
                before = copy.deepcopy(facts)
                clock_error = OSError("controlled post-write clock failure")
                self.invoke({"value": 1}, facts=facts, ticks=[NOW, NOW, clock_error])
                self.assertIs(getattr(self.error, "facts", None), facts)
                self.assertIs(getattr(self.error, "primary", None), clock_error)
                self.assertIs(self.error.__cause__, clock_error)
                self.assertEqual(facts, before)
                self.assertEqual(getattr(self.error, "causes", None),
                    causes + ["fixture_report_clock_unavailable"])
                self.persist.assert_called_once()

    def test_both_literal_callers_forward_original_report_deadline(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                clock = {"absolute_monotonic_ns": ABSOLUTE, "term_grace_ns": 5_000_000_000,
                    "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}
                seal = {"path": "controlled.json", "size_bytes": 1, "sha256": "b" * 64}
                argv = [str(builder.__file__), "--project-root", str(ROOT),
                    "--expected-source-commit", "a" * 40, "--artifact-base", str(ROOT / "controlled-inputs"),
                    "--namespace", "controlled", "--output-dir", str(ROOT / "controlled-output"), "--source-capture-dir", str(ROOT / "controlled-source-capture"),
                    "--compiler-qualification-json", json.dumps(seal),
                    "--compiler-admission-json", json.dumps(seal),
                    "--compiler-deadline-ns", str(NOW + 100_000_000_000),
                    "--reader-deadline-json", json.dumps(clock)]
                with ExitStack() as stack:
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    stack.enter_context(redirect_stderr(io.StringIO()))
                    stack.enter_context(patch.object(sys, "argv", argv))
                    stack.enter_context(patch.object(builder, "_fixture_source_capture_v2", return_value=nullcontext(object())))
                    stack.enter_context(patch.object(builder, "_git", side_effect=lambda root, *args, **kwargs:
                        b"a" * 40 + b"\n" if args[0] == "rev-parse" else b""))
                    if builder is negative:
                        stack.enter_context(patch.object(builder, "_raw_committed_source_proof",
                            return_value={"original_exit_code": 0}))
                    reporter = stack.enter_context(patch.object(builder, "_fresh_json"))
                    stack.enter_context(patch.object(builder, "_fixture_observation_maps_v2", return_value=({}, {})))
                    stack.enter_context(patch.object(builder, "_fixture_entrypoint_sha256_v2", return_value="d" * 64))
                    stack.enter_context(patch.object(builder, "_canonical_fixture_root_v2", return_value=ROOT))
                    stack.enter_context(patch.object(builder, "_canonical_fixture_directory_v2",
                        side_effect=lambda value, **kwargs: Path(value)))
                    stack.enter_context(patch.object(Path, "is_dir", return_value=True))
                    stack.enter_context(patch.object(Path, "exists", return_value=False))
                    stack.enter_context(patch.object(provenance, "loaded_fixture_production_sources_v1", return_value=[]))
                    stack.enter_context(patch.object(physical, "prepared_complete_fixture_inputs_v2",
                        side_effect=PreparationReached()))
                    stack.enter_context(patch.object(reader, "_monotonic_ns", return_value=NOW))
                    stack.enter_context(patch.object(admission.time, "monotonic_ns", return_value=NOW))
                    with self.assertRaises(PreparationReached):
                        builder.main()
                self.assertGreater(reporter.call_count, 0)
                for call in reporter.call_args_list:
                    self.assertEqual(call.kwargs.get("absolute_deadline_ns"), ABSOLUTE)


if __name__ == "__main__":
    unittest.main()
