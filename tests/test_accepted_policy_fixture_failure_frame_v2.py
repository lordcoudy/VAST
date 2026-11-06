"""Fixed producer diagnostics: controlled effects, retained tiny CLI children."""
from contextlib import ExitStack, nullcontext
import ast
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"))
import build_production_fixture_v2 as positive
import build_per_cell_minimum_refusal_v1 as negative
import tests.test_accepted_policy_fixture_producer_failures_v2 as legacy
import tests.test_accepted_policy_fixture_sidecar_bounds_v1 as sidecar_legacy
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader
from tests.fixtures import accepted_policy_literal_source_capture_v2 as source
from tests.fixtures import accepted_policy_native_fixture_v2 as native
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler
from tests.fixtures import accepted_policy_consumer_fixture_v2 as consumer
from tests.fixtures.accepted_policy_fixture_report_v1 import fixture_report_bytes_v1
import tests.test_accepted_policy_f5_real_refusals as f5
import publication_policy_qualification as qualification
import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian_module
from publication_policy_qualification import QualificationError

EMISSION_LIMIT = 485376
NOW = 1_000_000_000
ABSOLUTE = NOW + 200_000_000_000


def persistence(count=0):
    return {"attempted": True, "written_bytes": count, "write_extent_unknown": False,
        "fsync_completed": True, "close_completed": True, "causes": []}


def capture(prefix="/controlled", *, causes=None):
    def channel(name):
        return {"observed_bytes": 4, "retained_bytes": 4, "discarded_bytes": 0,
            "remainder_unknown": False, "eof": True, "overflow": False,
            "retained_sha256": "a" * 64,
            "file": {"path": prefix + "/" + name, "written_bytes": 4,
                "write_extent_unknown": False, "sha256": "b" * 64,
                "fsync_completed": True, "close_completed": True}}
    return {"causes": [] if causes is None else causes,
        "deadline": {"absolute_monotonic_ns": ABSOLUTE, "term_grace_ns": 5_000_000_000,
            "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000,
            "observe_end_ns": ABSOLUTE - 15_000_000_000},
        "pid": 1234, "start_ticks": 5678, "returncode": 1, "signal": None,
        "forced": False, "term_sent": False, "kill_sent": False,
        "term_delivered": 0, "kill_delivered": 0,
        "closure": {"closed": True, "owned_descendants": [],
            "descendants_unknown": False, "subreaper_restored": True},
        "stdout": channel("stdout"), "stderr": channel("stderr")}


def source_context(recipe="positive"):
    context = object.__new__(source.LiteralSourceCaptureV2)
    context.slots = (("head", "status", "guardian") if recipe == "positive" else
        ("before-head", "before-status", "before-proof", "after-proof", "after-head", "after-status"))
    context.used, context.records = [], []
    context.root = ROOT
    context.expected_commit = "a" * 40
    for slot in context.slots:
        facts = capture("/controlled/" + slot)
        context.used.append(slot)
        context.records.append({"schema_version": 2, "slot": slot, "capture": facts,
            "capture_returned": True, "capture_return_observed_ns": NOW,
            "post_return_clock_failed": False, "returned_within_observation": True,
            "stdout_path": facts["stdout"]["file"]["path"],
            "stderr_path": facts["stderr"]["file"]["path"],
            "result_path": "/controlled/" + slot + "/result", "result_complete": True,
            "result_persistence": persistence(100), "result_sha256": "c" * 64,
            "causes": [], "command": ["EXCLUDED_COMMAND"], "campaign_authority": False})
    return context


def table_facts(filename, *, failed=False):
    return {"filename": filename, "admitted_upper_bytes": 3,
        "accepted_text_bytes": 2 if failed else 3, "open_completed": True,
        "serialization_completed": not failed, "flush_completed": not failed,
        "fsync_completed": not failed, "close_attempted": True,
        "close_completed": not failed, "write_extent_unknown": False,
        "failure_stage": "write" if failed else None}


class FailureFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inherited = os.environ.get("VAST_PR9_FIXTURE_TEST_DEADLINE_NS")
        if inherited is not None:
            if not inherited.isascii() or not inherited.isdecimal() or len(inherited) > 20:
                raise ValueError("controlled test deadline is invalid")
            cls.absolute = int(inherited)
        else:
            # Generic CI establishes one fixture-only clock for the whole class.
            cls.absolute = time.monotonic_ns() + 180_000_000_000
        if time.monotonic_ns() >= cls.absolute - 15_000_000_000:
            raise ValueError("controlled test deadline is expired")

    def state(self, recipe="positive"):
        return positive._fixture_failure_state_v2(recipe)

    def frame(self, error, state):
        raw = positive._fixture_failure_frame_v2(error, state)
        self.assertIs(type(raw), bytes)
        self.assertLessEqual(len(raw), EMISSION_LIMIT)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertTrue(raw.isascii())
        value = json.loads(raw)
        self.assertIs(value["campaign_authority"], False)
        return raw, value

    def invoke_body_failure(self, builder, error, *, state=None, context=None):
        control = legacy.ProducerFailureTests(
            "test_positive_report_failure_keeps_original_and_distinct_secondary")
        control.invoke(builder, fault="body", primary=error,
            failure_state=state, source_context=context)
        return control

    def test_actual_failure_reports_never_format_unknown_errors_or_tracebacks(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                events = []
                class Hostile(RuntimeError):
                    def __str__(self):
                        events.append("str")
                        return "controlled error"
                    def __repr__(self):
                        events.append("repr")
                        raise AssertionError("error repr forbidden")
                error = Hostile("original")
                with patch.object(traceback, "format_exc",
                        side_effect=AssertionError("traceback formatting forbidden")) as formatted:
                    control = self.invoke_body_failure(builder, error)
                self.assertEqual(events, [])
                formatted.assert_not_called()
                self.assertTrue(control.error is error)

    def test_actual_failure_reports_never_read_dynamic_error_names_or_hash_types(self):
        for builder in (positive, negative):
            with self.subTest(caller=builder.__name__):
                events = []
                class Guard(type):
                    def __getattribute__(cls, name):
                        if name == "__name__":
                            events.append("name")
                            raise AssertionError("dynamic error name forbidden")
                        return super().__getattribute__(name)
                    def __hash__(cls):
                        events.append("class_hash")
                        raise AssertionError("error class hash forbidden")
                class Hostile(RuntimeError, metaclass=Guard):
                    def __hash__(self):
                        events.append("object_hash")
                        raise AssertionError("error hash forbidden")
                error = Hostile("original")
                events.clear()
                control = self.invoke_body_failure(builder, error)
                self.assertEqual(events, [])
                self.assertTrue(control.error is error)

    def test_actual_sidecar_catch_retains_output_directory_and_prior_facts(self):
        output = Path("sidecar-output-never-created")
        metadata = {"run_id": "r", "observations": [], "source_sha256_by_stream": {},
            "canonical_frames": {"input:0:1": {"trace_id": "r:0:1", "stream_id": 0, "frame_id": 1}},
            "limits": {"coordinate": {"system": "gstreamer_custom", "resource": "cpu", "codec": "h264",
                "topology_kind": "shared_video_dag"}, "completed_samples_per_branch": 1}}
        policies = native.pd.DataFrame(columns=["trace_id", "stage"])
        prior = table_facts("frames.csv")
        error = native._FixtureSidecarWriteErrorV2(table_facts("events.csv", failed=True),
            OSError("controlled"), [])
        def staged(directory, filename, columns, rows):
            if filename == "frames.csv":
                return prior
            error.facts["filename"] = filename
            raise error
        caught = None
        with patch.object(native.pd, "read_csv", return_value=policies), \
                patch.object(native, "_write_fixture_sidecar_table_v2", side_effect=staged), \
                patch.object(Path, "open", side_effect=AssertionError("no output expected")):
            try:
                native._write_native_sidecars_v1(output, sidecar_legacy.verified_fixture_manifest(), metadata)
            except BaseException as current:
                caught = current
        self.assertTrue(caught is error)
        self.assertTrue(getattr(error, "output_directory", None) == output)
        self.assertEqual(error.completed, {"frames.csv": prior})

    def test_both_main_paths_keep_actual_source_context_after_body_unwinds(self):
        for builder, recipe in ((positive, "positive"), (negative, "negative")):
            with self.subTest(recipe=recipe):
                state = self.state(recipe)
                context = source_context(recipe)
                error = RuntimeError("controlled body")
                with patch.object(source.LiteralSourceCaptureV2, "__enter__", return_value=context), \
                        patch.object(source.LiteralSourceCaptureV2, "__exit__", return_value=False):
                    control = self.invoke_body_failure(builder, error, state=state, context=context)
                self.assertTrue(control.error is error)
                self.assertTrue(state["source_context"] is context)
                raw, value = self.frame(error, state)
                self.assertEqual(len(value["source_slots"]), len(context.slots))
                self.assertEqual(len(value["captures"]), len(context.slots))
                self.assertNotIn(b"EXCLUDED_COMMAND", raw)
                self.assertEqual(value["captures"][0]["returncode"], 1)

    def test_report_state_saves_exact_return_before_a_post_write_clock_error(self):
        for clock_failed in (False, True):
            with self.subTest(clock_failed=clock_failed):
                state = self.state()
                facts = persistence(12)
                clock_error = OSError("controlled clock")
                ticks = [NOW, NOW, clock_error if clock_failed else NOW]
                with patch.object(reader, "_write_result_v2", return_value=facts) as writer, \
                        patch.object(reader, "_monotonic_ns", side_effect=ticks):
                    try:
                        positive._fresh_json(ROOT / "controlled.json", {"value": 1},
                            absolute_deadline_ns=ABSOLUTE, _failure_state=state, _failure_site="stage")
                    except positive.FixtureReportPersistenceRefusedV2 as error:
                        self.assertTrue(clock_failed)
                        self.assertTrue(error.primary is clock_error)
                site = state["reports"]["stage"]
                self.assertTrue(site["facts"] is facts)
                self.assertTrue(site["writer_entered"] and site["writer_returned"])
                self.assertEqual(site["clock_available"], not clock_failed)
                self.assertEqual(site["encoded_bytes"], 12)
                writer.assert_called_once()

    def test_actual_main_failure_report_keeps_assessment_source_and_writer_refusal(self):
        fresh_json = positive._fresh_json
        for builder, recipe in ((positive, "positive"), (negative, "negative")):
            with self.subTest(recipe=recipe):
                state = self.state(recipe)
                assessment = {"passed": False, "blockers": ["controlled"]}
                state["assessment"] = assessment
                context = source_context(recipe)
                primary = OSError("controlled body")
                failed = {**persistence(1), "fsync_completed": False, "causes": ["result_fsync"]}
                def writer(path, raw, absolute):
                    return failed if "failure" in path.name else persistence(len(raw))
                control = legacy.ProducerFailureTests(
                    "test_positive_report_failure_keeps_original_and_distinct_secondary")
                with patch.object(reader, "_write_result_v2", side_effect=writer), \
                        patch.object(source.LiteralSourceCaptureV2, "__enter__", return_value=context), \
                        patch.object(source.LiteralSourceCaptureV2, "__exit__", return_value=False):
                    control.invoke(builder, fault="body", primary=primary, failure_state=state,
                        source_context=context, report_callback=fresh_json)
                self.assertTrue(type(control.error) is positive._FixtureProducerFailureV2)
                self.assertTrue(control.error.primary is primary)
                self.assertTrue(control.failure_report["actual_f1_assessment"] is assessment)
                self.assertTrue(state["reports"]["failure"]["facts"] is failed)
                self.assertTrue(state["source_context"] is context)
                _, value = self.frame(control.error, state)
                self.assertEqual(len(value["captures"]), len(context.slots))
                site = next(row for row in value["report_sites"] if row["site"] == "failure")
                self.assertEqual(site["persistence"]["causes"], ["result_fsync"])
                self.assertEqual(value["errors"][0]["primary"], 1)
                self.assertEqual(value["errors"][0]["secondary"], [2])
                self.assertEqual(value["assessment_failure_report_site"], "failure")

    def test_report_writer_exception_has_no_invented_returned_facts(self):
        state = self.state()
        error = OSError("writer unavailable")
        with patch.object(reader, "_write_result_v2", side_effect=error), \
                patch.object(reader, "_monotonic_ns", return_value=NOW):
            caught = None
            try:
                positive._fresh_json(ROOT / "controlled.json", {}, absolute_deadline_ns=ABSOLUTE,
                    _failure_state=state, _failure_site="failure")
            except BaseException as current:
                caught = current
        self.assertTrue(caught is error)
        site = state["reports"]["failure"]
        self.assertTrue(site["writer_entered"])
        self.assertFalse(site["writer_returned"])
        self.assertIsNone(site["facts"])

    def test_report_sites_are_named_not_sequential_and_reuse_refuses_before_write(self):
        state = self.state("negative")
        with patch.object(reader, "_write_result_v2", return_value=persistence(3)) as writer, \
                patch.object(reader, "_monotonic_ns", return_value=NOW):
            for name in ("failure", "after-proof"):
                positive._fresh_json(ROOT / (name + ".json"), {}, absolute_deadline_ns=ABSOLUTE,
                    _failure_state=state, _failure_site=name)
            self.assertEqual(writer.call_count, 2)
            for name in ("failure", "foreign"):
                with self.subTest(site=name):
                    with self.assertRaises(ValueError):
                        positive._fresh_json(ROOT / "refused.json", {}, absolute_deadline_ns=ABSOLUTE,
                            _failure_state=state, _failure_site=name)
                    self.assertEqual(writer.call_count, 2)

    def test_opaque_error_projection_never_observes_custom_metadata(self):
        events = []
        class Hostile(RuntimeError):
            def __str__(self):
                events.append("str")
                raise AssertionError("str forbidden")
            def __repr__(self):
                events.append("repr")
                raise AssertionError("repr forbidden")
            def __hash__(self):
                events.append("hash")
                raise AssertionError("hash forbidden")
            def __eq__(self, other):
                events.append("equality")
                raise AssertionError("equality forbidden")
            @property
            def facts(self):
                events.append("facts")
                raise AssertionError("foreign facts forbidden")
            @property
            def fixture_cleanup_causes(self):
                events.append("cleanup")
                raise AssertionError("foreign cleanup forbidden")
        raw, value = self.frame(Hostile(object()), self.state())
        self.assertEqual(events, [])
        self.assertEqual(value["errors"][0]["kind"], "opaque_exception")
        self.assertNotIn(b"Hostile", raw)

    def test_owned_error_links_preserve_order_and_identity_without_fact_duplication(self):
        state = self.state()
        facts = persistence(1)
        state["reports"]["stage"].update(entered=True, writer_entered=True,
            writer_returned=True, facts=facts, encoded_bytes=1, clock_available=True)
        class Primary(OSError):
            def __eq__(self, other):
                raise AssertionError("error equality forbidden")
            def __hash__(self):
                raise AssertionError("error hash forbidden")
        primary = Primary("primary")
        report_error = positive.FixtureReportPersistenceRefusedV2(facts)
        error = positive._FixtureProducerFailureV2(primary, [report_error, report_error, primary])
        error.fixture_cleanup_causes = ("fixture_socket_close_OSError", "fixture_elf_close_ValueError")
        _, value = self.frame(error, state)
        root = value["errors"][0]
        self.assertEqual(root["primary"], 1)
        self.assertEqual(root["secondary"], [2])
        self.assertEqual(root["fixture_cleanup_causes"], list(error.fixture_cleanup_causes))
        self.assertEqual(len(value["errors"]), 3)
        self.assertNotIn("facts", value["errors"][2])
        self.assertEqual(value["report_sites"][4]["persistence"]["written_bytes"], 1)

    def test_compiler_singleton_never_traverses_heterogeneous_facts(self):
        events = []
        class Opaque:
            def __repr__(self):
                events.append("repr")
                raise AssertionError("opaque compiler facts")
        first, second = compiler.FixtureCompilerError("compiler_one"), compiler.FixtureCompilerError("compiler_two")
        first.facts = {"unprojected": Opaque()}
        second.facts = Opaque()
        _, value = self.frame(positive._FixtureProducerFailureV2(first, [second]), self.state())
        self.assertEqual(events, [])
        self.assertEqual(value["compiler"]["causes"], ["compiler_one"])
        self.assertEqual(value["compiler"]["facts_kind"], "exact_dict")
        self.assertIsNone(value["compiler"]["facts_reference"])
        self.assertFalse(value["facts_complete"])

    def consumer_failure(self, assessment, state, *, after_reader=False, reader_error=None):
        output = ROOT / "controlled-consumer"
        chain = {"index_path": ROOT / "index.json", "execution_config_path": ROOT / "execution.json",
            "binding_set_dir": ROOT / "bindings", "finalized": [],
            "journals": {"operational_group": {}}, "lifecycle": {"lifecycle_descriptor": {}},
            "closure": {"receipt_path": ROOT / "closure.json"}}
        prepared = {"root": ROOT, "output_dir": output,
            "preprocessing": {"contract_path": ROOT / "contract.json", "receipt_path": ROOT / "receipt.json"}}
        pilots = [{"resource": "cpu"}, {"resource": "gpu"}]
        guardian = {"contract_path": ROOT / "guardian-contract.json", "receipt_path": ROOT / "guardian-receipt.json",
            "preprocessing_contract_sha256": "a" * 64}
        evidence = {"capture": capture(), "result_persistence": persistence(3),
            "result_complete": True, "standalone_guardian_cold_reader_passed": True,
            "stdout_path": "/controlled/reader.stdout", "stderr_path": "/controlled/reader.stderr"}
        failure = OSError("controlled post-reader refusal")
        error = None
        with ExitStack() as stack:
            stack.enter_context(patch.object(consumer, "_sealed_deadline_v2"))
            stack.enter_context(patch.object(consumer, "materialize_fixture_completed_execution_v2", return_value=chain))
            stack.enter_context(patch.object(f5, "genuine_f5_context_v1", return_value=({}, pilots)))
            stack.enter_context(patch.object(f5, "assert_genuine_f5_stock_samples_v1", return_value={}))
            stack.enter_context(patch.object(qualification, "assess_policy_qualification", return_value=assessment))
            stack.enter_context(patch.object(qualification, "promote_policy_qualification", return_value={}))
            stack.enter_context(patch.object(consumer, "run_approved_guardian_snapshot_red_v1", return_value={}))
            stack.enter_context(patch.object(guardian_module, "materialize_accepted_policy_guardian_preprocessing_contract_v1", return_value=guardian))
            stack.enter_context(patch.object(guardian_module, "load_accepted_policy_guardian_preprocessing_contract_v1",
                return_value={"receipt": {"preprocessing_contract_content_sha256": "a" * 64}}))
            reader_call = stack.enter_context(patch.object(consumer, "run_fixture_standalone_guardian_cold_reader_v2",
                return_value=evidence, side_effect=reader_error))
            stack.enter_context(patch.object(consumer, "validate_fixture_identity_policy_component_v1", side_effect=failure))
            try:
                consumer.complete_fixture_production_consumers_v2(prepared=prepared,
                    native={"stock_positive_gpu_coordinate": {"resource": "gpu"}},
                    approved_guardian_source=b"controlled", approved_guardian_commit="a" * 40,
                    standalone_reader_deadline={}, _failure_state=state)
            except BaseException as current:
                error = current
        return error, evidence, failure, output, reader_call

    def test_consumer_retains_actual_assessment_before_constant_refusal(self):
        events = []
        class Assessment(dict):
            def __str__(self):
                events.append("str")
                raise AssertionError("assessment format forbidden")
            def __repr__(self):
                events.append("repr")
                raise AssertionError("assessment repr forbidden")
        assessment = Assessment(passed=False)
        state = self.state()
        error, unused, unused_failure, unused_output, reader_call = self.consumer_failure(assessment, state)
        self.assertTrue(type(error) is ValueError)
        self.assertTrue(state["assessment"] is assessment)
        self.assertTrue(state["assessment_returned"])
        self.assertTrue(getattr(error, "fixture_assessment", None) is assessment)
        self.assertEqual(events, [])
        reader_call.assert_not_called()
        state = self.state()
        error, unused, unused_failure, unused_output, reader_call = self.consumer_failure(None, state)
        self.assertTrue(state["assessment_returned"])
        self.assertIsNone(state["assessment"])
        _, value = self.frame(error, state)
        self.assertTrue(value["assessment_available"])
        self.assertIsNone(value["assessment_passed"])
        report = positive._fixture_failure_report_v2({}, error, state)
        self.assertIn("actual_f1_assessment", report)
        self.assertIsNone(report["actual_f1_assessment"])

    def test_consumer_retains_actual_reader_return_before_later_refusal(self):
        state = self.state()
        error, evidence, failure, output, reader_call = self.consumer_failure({"passed": True}, state, after_reader=True)
        self.assertTrue(error is failure)
        self.assertTrue(state["cold_reader"] is evidence)
        self.assertEqual(state["reader_output_dir"], output)
        reader_call.assert_called_once()
        _, value = self.frame(error, state)
        self.assertTrue(value["reader"]["call_site_entered"])
        self.assertTrue(value["reader"]["returned_evidence_available"])
        state = self.state()
        unavailable = OSError("controlled unavailable reader return")
        error, unused, unused_failure, output, reader_call = self.consumer_failure(
            {"passed": True}, state, reader_error=unavailable)
        self.assertTrue(error is unavailable)
        self.assertIsNone(state["cold_reader"])
        self.assertEqual(state["reader_output_dir"], output)
        reader_call.assert_called_once()
        _, value = self.frame(error, state)
        self.assertTrue(value["reader"]["call_site_entered"])
        self.assertFalse(value["reader"]["returned_evidence_available"])
        self.assertIsNone(value["reader"]["capture"])
        self.assertIsNone(value["reader"]["result_persistence"])
        target = value["files"][value["reader"]["intended_result"]]
        self.assertTrue(target["intended_target_only"])

    def test_sidecar_fact_block_is_global_and_preserves_text_not_disk_extent(self):
        first = native._FixtureSidecarWriteErrorV2(table_facts("frame_events.csv", failed=True), OSError("first"), [])
        first.completed = {"frames.csv": table_facts("frames.csv")}
        first.output_directory = Path("/controlled/sidecars")
        second = native._FixtureSidecarWriteErrorV2(table_facts("frame_events.csv", failed=True), OSError("second"), [])
        second.output_directory = Path("/controlled/other")
        _, value = self.frame(positive._FixtureProducerFailureV2(first, [second]), self.state())
        self.assertEqual(value["sidecar"]["failed"]["accepted_text_bytes"], 2)
        self.assertNotIn("written_bytes", value["sidecar"]["failed"])
        self.assertEqual(len(value["sidecar"]["completed"]), 1)
        self.assertFalse(value["facts_complete"])

        events = []
        class Filename:
            def __eq__(self, other):
                events.append("equality")
                raise AssertionError("filename equality forbidden")
        for filename in (Filename(), "x" * 65):
            first.completed = {"frames.csv": {**table_facts("frames.csv"), "filename": filename}}
            first.facts["filename"] = filename
            _, value = self.frame(first, self.state())
            self.assertFalse(value["facts_complete"])
            self.assertIsNone(value["sidecar"]["failed"])
        self.assertEqual(events, [])

    def test_complete_admitted_geometry_keeps_global_caps_and_worst_paths(self):
        state = self.state("negative")
        context = source_context("negative")
        state["source_context"] = context
        ordinal = 0
        for record in context.records:
            for name in ("stdout", "stderr", "result"):
                path = "/" + chr(0x1F600 + ordinal) * 639
                ordinal += 1
                record[name + "_path"] = path
                if name != "result":
                    record["capture"][name]["file"]["path"] = path
            record["capture"]["causes"] = ["reader_" + str(index).zfill(3) + "x" * 118 for index in range(64)]
            record["capture"]["closure"]["owned_descendants"] = [
                {"pid": 2**63 - 1 - index, "start_ticks": 2**63 - 1} for index in range(64)]
        for site in state["reports"].values():
            site.update(entered=True, writer_entered=True, writer_returned=True,
                facts=persistence(3), encoded_bytes=3, clock_available=True,
                clock_observed_ns=NOW, path="/" + chr(0x1F600 + ordinal) * 639)
            ordinal += 1
        names = list(native._FIXTURE_SIDECAR_SPECS_V2)
        compilation = compiler.FixtureCompilerError(*["compiler_" + str(index).zfill(3) + "x" * 116 for index in range(64)])
        sidecar = native._FixtureSidecarWriteErrorV2(table_facts(names[-1], failed=True), compilation, [])
        sidecar.completed = {name: table_facts(name) for name in names[:-1]}
        sidecar.output_directory = Path("/" + chr(0x1F600 + ordinal) * 639)
        groups = [positive._FixtureProducerFailureV2(RuntimeError("primary"),
            [RuntimeError("secondary") for unused in range(7)]) for unused in range(6)]
        groups.append(positive._FixtureProducerFailureV2(RuntimeError("primary"),
            [RuntimeError("secondary") for unused in range(4)]))
        error = positive._FixtureProducerFailureV2(sidecar, [*groups, RuntimeError("last")])
        raw, value = self.frame(error, state)
        self.assertEqual(len(value["files"]), 22)
        self.assertEqual(len(value["captures"]), 6)
        self.assertEqual(len(value["source_slots"]), 6)
        self.assertEqual(len(value["errors"]), 64)
        self.assertEqual(value["sidecar"]["failed"]["filename"], names[-1])
        self.assertEqual([row["filename"] for row in value["sidecar"]["completed"]], names[:-1])
        for record, projected in zip(context.records, value["captures"]):
            self.assertEqual(projected["causes"], record["capture"]["causes"])
            self.assertEqual(projected["closure"]["owned_descendants"],
                record["capture"]["closure"]["owned_descendants"])
            for name in ("stdout", "stderr", "result"):
                self.assertTrue(any(row["path"] == record[name + "_path"] for row in value["files"]))
        self.assertEqual(value["compiler"]["causes"], compilation.causes)
        self.assertLessEqual(len(value["projection_refusals"]), 32)
        self.assertLessEqual(len(raw), EMISSION_LIMIT)
        directory = Path(tempfile.mkdtemp(prefix="failureframe-geometry-"))
        written = reader._write_result_v2(directory / "frame.original.json", raw, self.absolute)
        self.assertEqual(written["causes"], [])
        self.assertEqual(written["written_bytes"], len(raw))
        self.assertTrue(written["fsync_completed"] and written["close_completed"])
        print(fixture_report_bytes_v1({"controlled_geometry_path": str(directory / "frame.original.json"),
            "result_persistence": written, "physical_acceptance": False}, limit=4096).decode("ascii"),
            end="", flush=True)

    def test_unsafe_cause_alphabets_are_refused_without_echoing_them(self):
        for code in ('bad"code', "bad\\code", "bad\ncode", "bad\x7fcode", "bad\u00e9code", "x" * 129):
            with self.subTest(length=len(code)):
                state = self.state()
                context = source_context()
                context.records[0]["capture"]["causes"] = [code]
                state["source_context"] = context
                raw, value = self.frame(RuntimeError("controlled"), state)
                self.assertFalse(value["facts_complete"])
                self.assertIsNone(value["captures"][0]["causes"])
                escaped = json.dumps(code, ensure_ascii=True).encode("ascii")
                self.assertNotIn(escaped, raw)

    def test_cli_tails_and_positive_main_namespace_keep_owned_class_identity(self):
        for builder, recipe in ((positive, "positive"), (negative, "negative")):
            with self.subTest(recipe=recipe):
                with Path(builder.__file__).open("rb") as stream:
                    raw = stream.read(65537)
                self.assertLessEqual(len(raw), 65536)
                tree = ast.parse(raw)
                expected = ast.parse('if __name__ == "__main__":\n'
                    '    raise SystemExit(_fixture_cli_v2(main, "' + recipe + '"))\n').body[0]
                self.assertEqual(ast.dump(tree.body[-1]), ast.dump(expected))
                if recipe == "positive":
                    # Execute only the reviewed definitions; the real tail is excluded.
                    namespace = {"__name__": "__main__", "__file__": builder.__file__}
                    exec(compile(ast.Module(body=tree.body[:-1], type_ignores=[]),
                        builder.__file__, "exec"), namespace)
                    error = namespace["_FixtureProducerFailureV2"](RuntimeError("primary"), [])
                    self.assertTrue(type(error) is not positive._FixtureProducerFailureV2)
                    frame = namespace["_fixture_failure_frame_v2"](error,
                        namespace["_fixture_failure_state_v2"]("positive"))
                    self.assertEqual(json.loads(frame)["errors"][0]["kind"], "producer_failure")

    def test_cause_identity_and_error_graph_caps_refuse_incomplete_not_recurse(self):
        for mode in ("causes", "identities", "depth", "nodes", "cleanup"):
            with self.subTest(mode=mode):
                state = self.state()
                context = source_context("positive")
                state["source_context"] = context
                error = RuntimeError("controlled")
                if mode == "causes":
                    context.records[0]["capture"]["causes"] = ["code"] * 65
                elif mode == "identities":
                    context.records[0]["capture"]["closure"]["owned_descendants"] = [
                        {"pid": index + 1, "start_ticks": 1} for index in range(65)]
                elif mode == "depth":
                    for unused in range(10):
                        error = positive._FixtureProducerFailureV2(error, [])
                elif mode == "cleanup":
                    error = positive._FixtureProducerFailureV2(error, [])
                    error.fixture_cleanup_causes = ("fixture_elf_close_OSError",) * 3
                else:
                    groups = [positive._FixtureProducerFailureV2(RuntimeError("primary"),
                        [RuntimeError("secondary") for unused in range(7)]) for unused in range(8)]
                    error = positive._FixtureProducerFailureV2(groups[0], groups[1:])
                _, value = self.frame(error, state)
                self.assertFalse(value["facts_complete"])
                self.assertLessEqual(len(value["errors"]), 64)
                if mode == "cleanup":
                    self.assertIsNone(value["errors"][0]["fixture_cleanup_causes"])
                    self.assertIn("invalid_cause_codes", value["projection_refusals"])

    def test_paths_use_worst_json_escaping_and_excess_is_explicit_unknown(self):
        for length in (640, 641):
            with self.subTest(codepoints=length):
                state = self.state()
                context = source_context()
                context.records[0]["stdout_path"] = "\U0001f642" * length
                context.records[0]["capture"]["stdout"]["file"]["path"] = "\U0001f642" * length
                state["source_context"] = context
                raw, value = self.frame(RuntimeError("controlled"), state)
                if length == 640:
                    self.assertTrue(any(row["path"] == "\U0001f642" * length for row in value["files"]))
                    for row in value["files"]:
                        self.assertLessEqual(len(json.dumps(row, ensure_ascii=True, separators=(",", ":")).encode("ascii")), 8192)
                else:
                    self.assertFalse(value["facts_complete"])
                    self.assertNotIn(("\\ud83d\\ude42" * length).encode("ascii"), raw)

    def test_promoter_guard_preserves_known_short_check_without_formatting_foreign_args(self):
        expected = "policy qualification is blocked: controlled expected refusal"
        negative._require_plain_promoter_refusal_v1(QualificationError(expected), expected)
        events = []
        class Argument:
            def __str__(self):
                events.append("str")
                raise AssertionError("argument format forbidden")
            def __repr__(self):
                events.append("repr")
                raise AssertionError("argument repr forbidden")
        class Foreign(QualificationError):
            def __str__(self):
                events.append("subclass_str")
                raise AssertionError("subclass format forbidden")
        for error in (Foreign(expected), QualificationError(Argument()),
                      QualificationError("one", "two"), QualificationError("x" * (len(expected) + 1))):
            caught = None
            try:
                negative._require_plain_promoter_refusal_v1(error, expected)
            except BaseException as current:
                caught = current
            self.assertTrue(caught is error)
        self.assertEqual(events, [])

    def test_single_stderr_attempt_never_retries_partial_or_failed_emission(self):
        def fail(*, _failure_state):
            raise RuntimeError("controlled")
        for action in (lambda descriptor, raw: len(raw) - 1,
                       lambda descriptor, raw: True, OSError("closed stderr")):
            with self.subTest(action_kind=type(action) is OSError):
                with patch.object(positive.os, "write", side_effect=action) as written:
                    status = positive._fixture_cli_v2(fail, "positive")
                self.assertIs(type(status), int)
                self.assertNotEqual(status, 0)
                written.assert_called_once()
                self.assertLessEqual(len(written.call_args.args[1]), EMISSION_LIMIT)

    def test_actual_tiny_cli_children_have_one_frame_or_originated_help_exit(self):
        cases = (("positive", "error", 1), ("negative", "error", 1),
                 ("positive", "body-exit-zero", 1), ("negative", "body-exit-zero", 1),
                 ("positive", "help", 0), ("negative", "bad-arg", 2))
        absolute = self.absolute
        deadline = {"absolute_monotonic_ns": absolute, "term_grace_ns": 5_000_000_000,
            "kill_grace_ns": 5_000_000_000, "final_ns": 5_000_000_000}
        program = '''import sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root));sys.path.insert(0,str(root/"scripts"));sys.path.insert(0,str(root/"openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"))
import build_production_fixture_v2 as p
import build_per_cell_minimum_refusal_v1 as n
recipe,mode=sys.argv[2:]
def forbidden(*a,**kw): raise RuntimeError("production main forbidden")
p.main=n.main=forbidden
class Hostile(RuntimeError):
 def __str__(self): raise RuntimeError("FORMAT_CALLBACK_FORBIDDEN")
 def __repr__(self): raise RuntimeError("FORMAT_CALLBACK_FORBIDDEN")
def entry(*,_failure_state):
 if mode=="help" or mode=="bad-arg":
  parser=p._fixture_argument_parser_v2(_failure_state,prog="controlled-cli")
  parser.parse_args(["--help"] if mode=="help" else ["--bad"])
 elif mode=="body-exit-zero": raise SystemExit(0)
 else: raise Hostile("controlled")
raise SystemExit(p._fixture_cli_v2(entry,recipe))
'''
        for recipe, mode, expected in cases:
            with self.subTest(recipe=recipe, mode=mode):
                directory = Path(tempfile.mkdtemp(prefix="failureframe-cli-"))
                facts, stdout, stderr = reader._capture_owned_reader_v2(
                    command=[sys.executable, "-I", "-B", "-c", program, str(ROOT), recipe, mode],
                    cwd=ROOT, outputs={name: directory / (name + ".original") for name in ("stdout", "stderr")},
                    deadline=deadline)
                self.assertEqual(facts["returncode"], expected)
                self.assertTrue(facts["closure"]["closed"])
                self.assertFalse(facts["forced"])
                self.assertEqual(facts["causes"], [])
                for name in ("stdout", "stderr"):
                    self.assertTrue(facts[name]["eof"])
                    self.assertFalse(facts[name]["overflow"])
                    self.assertFalse(facts[name]["remainder_unknown"])
                    self.assertTrue(facts[name]["file"]["fsync_completed"])
                    self.assertTrue(facts[name]["file"]["close_completed"])
                if mode == "help":
                    self.assertIn(b"usage:", stdout)
                    self.assertEqual(stderr, b"")
                else:
                    self.assertEqual(stderr.count(b"\n"), 1)
                    self.assertLessEqual(len(stderr), EMISSION_LIMIT)
                    value = json.loads(stderr)
                    self.assertFalse(value["campaign_authority"])
                    self.assertNotIn(b"Traceback", stderr)
                    self.assertNotIn(b"FORMAT_CALLBACK_FORBIDDEN", stderr)
                self.assertIsNone(facts["signal"])
                self.assertTrue(facts["closure"]["subreaper_restored"])
                raw = fixture_report_bytes_v1(facts, limit=32768)
                persistence_facts = reader._write_result_v2(directory / "capture.original.json", raw, absolute)
                self.assertEqual(persistence_facts["causes"], [])
                self.assertEqual(persistence_facts["written_bytes"], len(raw))
                self.assertTrue(persistence_facts["fsync_completed"] and persistence_facts["close_completed"])
                self.assertFalse(persistence_facts["write_extent_unknown"])
                outer = fixture_report_bytes_v1({"controlled_cli": [recipe, mode],
                    "capture_path": str(directory / "capture.original.json"),
                    "result_persistence": persistence_facts, "physical_acceptance": False}, limit=4096)
                print(outer.decode("ascii"), end="", flush=True)


if __name__ == "__main__":
    unittest.main()
