"""Small metadata fixtures; no benchmark, model, engine or acceptance authority."""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

HEADERS = {
    "frames.csv": "schema_version,run_id,trace_id,stream_id,frame_id,ingress_timestamp_ms,egress_timestamp_ms,e2e_latency_ms,objects,detector,backend,telemetry_source",
    "ingress_ledger.csv": "schema_version,run_id,cohort_id,trace_id,input_frame_key,admission_seq,source_sha256,source_cycle,access_unit_pts_ns,payload_sha256,payload_size_bytes,schedule_offset_ns,stream_id,frame_id,ingress_timestamp_ms,window_start_timestamp_ms,window_end_timestamp_ms,terminal_status,terminal_timestamp_ms,drain_end_timestamp_ms,terminal_reason,censoring_rule,ingress_provenance,terminal_provenance,telemetry_source",
    "branch_terminals.csv": "schema_version,run_id,cohort_id,trace_id,input_frame_key,stream_id,frame_id,branch_id,terminal_status,terminal_timestamp_ms,objects,detector,backend,terminal_reason,terminal_provenance,telemetry_source",
    "frame_events.csv": "schema_version,run_id,trace_id,stream_id,frame_id,stage,role,host,resource,queue_enter_timestamp_ms,stage_start_timestamp_ms,stage_end_timestamp_ms,queue_depth,estimated_cost_ms,policy_action",
}


class EvidenceFixture:
    def __init__(self, path: Path, topology: str = "shared"):
        self.path, self.topology = path, topology
        path.mkdir()
        self.rows = {name: [] for name in HEADERS}

    def add(self, frame_id=0, prefix=20, latency=100, critical="a", status="completed", other_prefix=None):
        ingress = 1000 + frame_id * 1000
        identity = dict(schema_version=2, run_id="fixture", trace_id=f"fixture:0:{frame_id}", stream_id=0, frame_id=frame_id)
        terminal = ingress + latency if status != "censored" else 11000
        ledger = dict(identity, cohort_id="fixture:measurement", input_frame_key=f"fixture-input:{frame_id}", admission_seq=frame_id + 1,
                      source_sha256="1" * 64, source_cycle=0, access_unit_pts_ns=frame_id * 1666667,
                      payload_sha256="2" * 64, payload_size_bytes=75, schedule_offset_ns=frame_id * 1000000000,
                      ingress_timestamp_ms=ingress, window_start_timestamp_ms=1000, window_end_timestamp_ms=10000,
                      terminal_status=status, terminal_timestamp_ms=terminal, drain_end_timestamp_ms=11000,
                      terminal_reason="all_required_branches_joined" if status == "completed" else "fixture_terminal",
                      censoring_rule="drain_to_empty", ingress_provenance="native_ingress_event",
                      terminal_provenance="native_completion_event", telemetry_source="native")
        self.rows["ingress_ledger.csv"].append(ledger)
        if status == "completed":
            self.rows["frames.csv"].append(dict(identity, ingress_timestamp_ms=ingress, egress_timestamp_ms=terminal,
                                                e2e_latency_ms=latency, objects=2, detector="fixture_aggregate", backend="fixture", telemetry_source="native"))
        if self.topology == "shared":
            self.event(identity, "decode", ingress, ingress + prefix)
            self.event(identity, "preprocess", ingress + prefix, ingress + prefix)
        for branch in ("a", "b"):
            branch_prefix = prefix if branch == critical or other_prefix is None else other_prefix
            if self.topology == "baseline":
                self.event(identity, "decode_" + branch, ingress, ingress + branch_prefix)
                self.event(identity, "preprocess_" + branch, ingress + branch_prefix, ingress + branch_prefix)
            if status == "censored" and branch == "b":
                continue
            dropped = status == "drop" and branch == "b"
            end = ingress + prefix if dropped else ingress + max(0, latency - (1 if branch == critical else 2))
            branch_row = dict(identity, cohort_id=ledger["cohort_id"], input_frame_key=ledger["input_frame_key"], branch_id=branch,
                              terminal_status="drop" if dropped else "completed", terminal_timestamp_ms=end, objects=0 if dropped else 1,
                              detector="fixture_model", backend="fixture", terminal_reason="native_pre_detector_queue_full_drop_newest" if dropped else "native_inference_completed",
                              terminal_provenance="native_drop_event" if dropped else "native_completion_event", telemetry_source="native")
            self.rows["branch_terminals.csv"].append(branch_row)
            if not dropped:
                post_start = max(ingress + branch_prefix, end - 1)
                self.event(identity, branch, ingress + branch_prefix, post_start)
                self.event(identity, "postprocess_" + branch, post_start, end)
        if status == "completed":
            self.event(identity, "aggregate", ingress + max(0, latency - 1), terminal)
            self.event(identity, "record", terminal, terminal)
        elif status == "drop":
            # Stock drop terminal is the latest branch outcome; a completed
            # aggregate join may finish later than its latest postprocess.
            ledger["terminal_timestamp_ms"] = max(r["terminal_timestamp_ms"] for r in self.rows["branch_terminals.csv"] if r["frame_id"] == frame_id)
        return self

    def event(self, identity, stage, start, end):
        self.rows["frame_events.csv"].append(dict(identity, stage=stage, role="local", host="fixture-host", resource="nvdec" if stage.startswith("decode") else "cpu",
                                                  queue_enter_timestamp_ms=start, stage_start_timestamp_ms=start, stage_end_timestamp_ms=end,
                                                  queue_depth=0, estimated_cost_ms=end - start, policy_action="cpu_only:fixed_outside_analytics_scope:cpu"))

    def policy(self):
        records = []
        ledger = {r["trace_id"]: r for r in self.rows["ingress_ledger.csv"]}
        terminals = {(r["trace_id"], r["branch_id"]): r for r in self.rows["branch_terminals.csv"]}
        for seq, stage in enumerate((r for r in self.rows["frame_events.csv"] if r["stage"] in {"a", "b"}), 1):
            row, branch = ledger[stage["trace_id"]], stage["stage"]
            decision = f"fixture:native-policy:{seq}:worker:123:{branch}"
            stage["policy_action"] = "cpu_only:cpu:" + decision
            path = stage["stage_start_timestamp_ms"] + .25
            terminal = terminals[(stage["trace_id"], branch)]["terminal_timestamp_ms"] + .4
            records.append(dict(schema_version=1, trace_id=stage["trace_id"], branch=branch, decision_id=decision,
                                selected_resource="cpu", policy="cpu_only", request=dict(trace_id=stage["trace_id"], branch=branch, decision_id=decision,
                                arrival_ms=row["ingress_timestamp_ms"], deadline_ms=row["ingress_timestamp_ms"] + 100, decision_time_ms=path - .1),
                                native_decision_evidence=dict(branch=branch, decision_id=decision, input_frame_key=row["input_frame_key"],
                                transport_pts_ns=123, selected_resource="cpu", terminal_status="completed", path_entry_timestamp_ms=path,
                                terminal_timestamp_ms=terminal, actual_service_ms=terminal - path)))
        return records

    def save(self, policy=None):
        for name, rows in self.rows.items():
            with (self.path / name).open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=HEADERS[name].split(","))
                writer.writeheader()
                writer.writerows(rows)
        if policy is not None:
            (self.path / "publication_policy_decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in policy), encoding="utf-8")
        return self.path


class ComponentLatencyDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = EvidenceFixture(self.root / "evidence")
        self.diag = importlib.import_module("analyze_component_latency_v1")

    def run_report(self, policy=None, deadline="100"):
        directory = self.fixture.save(policy)
        return self.diag.run_diagnostic(directory, self.root / "output", deadline_ms=deadline,
                                        native_policy_evidence=directory / "publication_policy_decisions.jsonl" if policy is not None else None)

    def snapshot(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.fixture.path.iterdir() if p.is_file() and not p.is_symlink()}

    def rejected(self, match=""):
        before = self.snapshot()
        with self.assertRaisesRegex(self.diag.DiagnosticError, match):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100")
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / "output/diagnostic.json").exists())

    def test_shared_critical_branches_and_nonadditive_medians(self):
        self.fixture.add(0, 90, 100, "a").add(1, 10, 100, "b").add(2, 10, 20, "a")
        report = self.run_report()
        self.assertEqual(report["topology"], "shared_video_dag")
        self.assertEqual(report["critical_path"]["decoder_prefix_ms"]["p50"], 10)
        self.assertEqual(report["critical_path"]["postdecode_residual_ms"]["p50"], 10)
        self.assertEqual(report["latency_ms"]["p50"], 100)
        with (self.root / "output/per_completed_frame.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([r["critical_branch"] for r in rows], ["a", "b", "a"])
        for row in rows:
            self.assertEqual(float(row["decoder_prefix_ms"]) + float(row["postdecode_residual_ms"]), float(row["e2e_latency_ms"]))
        self.assertEqual(json.loads((self.root / "output/diagnostic.json").read_text()), report)

    def test_baseline_uses_decoder_of_actual_critical_branch(self):
        self.fixture.topology = "baseline"
        self.fixture.add(prefix=20, latency=100, critical="a", other_prefix=80).add(1, 70, 100, "b", other_prefix=10)
        report = self.run_report()
        self.assertEqual(report["topology"], "independent_processes")
        self.assertEqual(report["critical_path"]["decoder_prefix_ms"]["p50"], 45)

    def test_ties_are_deterministic_and_zero_latency_share_is_unknown(self):
        self.fixture.add(prefix=0, latency=0)
        report = self.run_report()
        self.assertEqual(report["critical_branch_counts"], {"b": 1})
        self.assertIsNone(report["critical_path"]["decoder_share"]["p50"])
        self.assertEqual(report["critical_path"]["decoder_share"]["reason"], "no_positive_latency_frames")

    def test_recorded_cohort_early_ingress_and_shuffled_rows_are_preserved(self):
        self.fixture.add().add(1, 30, 120, "b")
        for name, rows in self.fixture.rows.items():
            rows.reverse()
        self.fixture.rows["ingress_ledger.csv"][-1]["window_start_timestamp_ms"] = 1001
        self.fixture.rows["ingress_ledger.csv"][0]["window_start_timestamp_ms"] = 1001
        report = self.run_report()
        self.assertEqual(report["counts"]["admitted"], 2)
        self.assertEqual(report["deadline"]["completed_misses"], 1)
        self.assertEqual(report["deadline"]["provenance"], "caller_parameter")

    def test_drops_censoring_and_branch_populations_remain_separate(self):
        self.fixture.add().add(1, status="drop").add(2, status="censored")
        report = self.run_report()
        self.assertEqual(report["counts"], {"admitted": 3, "completed": 1, "dropped": 1, "censored": 1, "branch_completed": 4, "branch_dropped": 1})
        self.assertAlmostEqual(report["completion_coverage"], 1 / 3)
        self.assertEqual(report["branch_drop_reasons"], {"native_pre_detector_queue_full_drop_newest": 1})
        self.assertEqual(report["latency_ms"]["count"], 1)

    def test_empty_completed_population_has_null_quantiles_with_reason(self):
        self.fixture.add(status="drop")
        report = self.run_report()
        self.assertEqual(report["latency_ms"]["count"], 0)
        self.assertIsNone(report["latency_ms"]["p95"])
        self.assertEqual(report["latency_ms"]["reason"], "empty_population")

    def test_linear_quantiles_not_nearest_rank(self):
        self.fixture.add(latency=100).add(1, latency=200)
        report = self.run_report()
        self.assertEqual(report["latency_ms"]["p95"], 195)
        self.assertEqual(report["latency_ms"]["p99"], 199)

    def test_promoted_zero_queue_span_does_not_claim_zero_true_wait(self):
        self.fixture.add()
        report = self.run_report()
        self.assertEqual(report["stages"]["decode"]["recorded_queue_span_ms"]["p50"], 0)
        self.assertEqual(report["stages"]["decode"]["semantics"], "parent_to_completion_envelope")
        for field in ("true_queue_wait_ms", "pure_inference_service_ms", "nvdec_busy_ms"):
            self.assertIsNone(report["unknown_components"][field]["value"])
            self.assertTrue(report["unknown_components"][field]["reason"])
        self.assertFalse(report["qualification_eligible"])
        self.assertFalse(report["publication_ready"])

    def test_policy_population_includes_successful_branches_of_dropped_frames(self):
        self.fixture.add().add(1, status="drop")
        policy = self.fixture.policy()
        policy.reverse()
        policy[0]["native_decision_evidence"]["actual_service_ms"] += .0006
        report = self.run_report(policy)
        self.assertEqual(report["policy_path"]["count"], 3)
        self.assertEqual(report["policy_path"]["population"], "measured_completed_branch_paths_including_dropped_frames")
        self.assertEqual(report["policy_path"]["by_branch"]["a"]["parent_to_path_ms"]["count"], 2)
        self.assertAlmostEqual(report["policy_path"]["by_branch"]["a"]["parent_to_path_ms"]["p50"], .25)

    def test_carried_native_path_span_gross_or_outside_precision_mismatch_fails(self):
        self.fixture.add()
        good = self.fixture.policy()
        for delta in (1000000, .00101):
            with self.subTest(delta=delta):
                bad = copy.deepcopy(good)
                bad[0]["native_decision_evidence"]["actual_service_ms"] += delta
                self.fixture.save(bad)
                output = self.root / ("output_" + str(delta))
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.run_diagnostic(self.fixture.path, output, deadline_ms="100",
                                             native_policy_evidence=self.fixture.path / "publication_policy_decisions.jsonl")
                self.assertFalse(output.exists())

    def test_completed_frame_requires_aggregate_and_record_events(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        for missing in ("aggregate", "record"):
            with self.subTest(missing=missing):
                self.fixture.rows = copy.deepcopy(original)
                self.fixture.rows["frame_events.csv"] = [r for r in self.fixture.rows["frame_events.csv"] if r["stage"] != missing]
                self.fixture.save()
                output = self.root / ("output_missing_" + missing)
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.run_diagnostic(self.fixture.path, output, deadline_ms="100")
                self.assertFalse(output.exists())

    def test_aggregate_record_times_must_agree_with_postprocess_and_frame_join(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        mutations = (("aggregate", ("queue_enter_timestamp_ms",), 1098),
                     ("aggregate", ("queue_enter_timestamp_ms", "stage_start_timestamp_ms"), 1098),
                     ("aggregate", ("stage_end_timestamp_ms",), 1099),
                     ("record", ("queue_enter_timestamp_ms", "stage_start_timestamp_ms"), 1099),
                     ("record", ("queue_enter_timestamp_ms", "stage_start_timestamp_ms", "stage_end_timestamp_ms"), 1099))
        for index, (stage, fields, value) in enumerate(mutations):
            with self.subTest(stage=stage, fields=fields):
                self.fixture.rows = copy.deepcopy(original)
                row = next(r for r in self.fixture.rows["frame_events.csv"] if r["stage"] == stage)
                row.update({field: value for field in fields})
                self.fixture.save()
                output = self.root / ("output_join_" + str(index))
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.run_diagnostic(self.fixture.path, output, deadline_ms="100")
                self.assertFalse(output.exists())

    def test_valid_aggregate_join_can_complete_well_after_latest_postprocess(self):
        self.fixture.add()
        self.fixture.rows["frames.csv"][0].update(egress_timestamp_ms=1130, e2e_latency_ms=130)
        self.fixture.rows["ingress_ledger.csv"][0]["terminal_timestamp_ms"] = 1130
        for row in self.fixture.rows["frame_events.csv"]:
            if row["stage"] == "aggregate":
                row["stage_end_timestamp_ms"] = 1130
            elif row["stage"] == "record":
                row.update(queue_enter_timestamp_ms=1130, stage_start_timestamp_ms=1130, stage_end_timestamp_ms=1130)
        report = self.run_report()
        self.assertEqual(report["critical_path"]["postdecode_residual_ms"]["p50"], 110)
        self.assertEqual(report["stages"]["aggregate"]["parent_to_completion_ms"]["p50"], 31)

    def test_missing_optional_policy_reports_unavailable_not_zero(self):
        self.fixture.add()
        report = self.run_report()
        self.assertIsNone(report["policy_path"]["count"])
        self.assertEqual(report["policy_path"]["reason"], "not_supplied")

    def test_native_terminal_may_precede_postprocess_and_frame_join(self):
        self.fixture.add()
        policy = self.fixture.policy()
        for row in policy:
            native = row["native_decision_evidence"]
            native["terminal_timestamp_ms"] -= 4
            native["actual_service_ms"] -= 4
            row["request"]["arrival_ms"] += 3
            row["request"]["deadline_ms"] += 3
        report = self.run_report(policy)
        self.assertAlmostEqual(report["policy_path"]["by_branch"]["a"]["native_terminal_to_postprocess_ms"]["p50"], 3.6)
        self.assertEqual(report["critical_path"]["postdecode_residual_ms"]["p50"], 80)

    def test_policy_wrong_associations_deadline_and_missing_path_fail(self):
        self.fixture.add()
        good = self.fixture.policy()
        for scope, field, value in (("native_decision_evidence", "input_frame_key", "foreign"),
                                    ("request", "trace_id", "foreign"), ("native_decision_evidence", "branch", "foreign"),
                                    ("native_decision_evidence", "decision_id", "foreign"), ("request", "deadline_ms", 1110),
                                    ("native_decision_evidence", "path_entry_timestamp_ms", 1200)):
            with self.subTest(field=field):
                bad = copy.deepcopy(good)
                bad[0][scope][field] = value
                self.fixture.save(bad)
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100",
                                             native_policy_evidence=self.fixture.path / "publication_policy_decisions.jsonl")
                self.assertFalse((self.root / "output/diagnostic.json").exists())
        self.fixture.save(good[:-1])
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100",
                                     native_policy_evidence=self.fixture.path / "publication_policy_decisions.jsonl")

    def test_supplied_projection_must_reference_the_same_worker_trace(self):
        self.fixture.add()
        policy = self.fixture.policy()
        policy[0]["publication_projection"] = dict(schema_version=1, original_worker_trace_id="foreign")
        self.fixture.save(policy)
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100",
                                     native_policy_evidence=self.fixture.path / "publication_policy_decisions.jsonl")
        self.assertFalse((self.root / "output").exists())

    def test_native_arrival_before_canonical_ingress_fails(self):
        self.fixture.add()
        policy = self.fixture.policy()
        policy[0]["request"].update(arrival_ms=900, deadline_ms=1000)
        self.fixture.save(policy)
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100",
                                     native_policy_evidence=self.fixture.path / "publication_policy_decisions.jsonl")
        self.assertFalse((self.root / "output").exists())

    def test_conflicting_input_key_and_stream_admission_sequence_fail(self):
        self.fixture.add().add(1)
        original = copy.deepcopy(self.fixture.rows)
        for field in ("input_frame_key", "admission_seq"):
            with self.subTest(field=field):
                self.fixture.rows = copy.deepcopy(original)
                self.fixture.rows["ingress_ledger.csv"][1][field] = self.fixture.rows["ingress_ledger.csv"][0][field]
                if field == "input_frame_key":
                    for row in self.fixture.rows["branch_terminals.csv"]:
                        if row["frame_id"] == 1:
                            row[field] = self.fixture.rows["ingress_ledger.csv"][0][field]
                self.fixture.save()
                output = self.root / ("output_" + field)
                with self.assertRaises(self.diag.DiagnosticError):
                    self.diag.run_diagnostic(self.fixture.path, output, deadline_ms="100")
                self.assertFalse(output.exists())

    def test_duplicate_policy_json_keys_and_identity_fail(self):
        self.fixture.add()
        policy = self.fixture.policy()
        self.fixture.save(policy + policy[:1])
        path = self.fixture.path / "publication_policy_decisions.jsonl"
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100", native_policy_evidence=path)
        path.write_text('{"trace_id":"fixture:0:0","trace_id":"foreign"}\n', encoding="utf-8")
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100", native_policy_evidence=path)

    def test_conflicting_frame_ledger_terminal_and_branch_status_fail(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        mutations = (("frames.csv", "trace_id", "foreign"), ("frames.csv", "egress_timestamp_ms", 1200),
                     ("frames.csv", "e2e_latency_ms", 999), ("ingress_ledger.csv", "terminal_timestamp_ms", 1200),
                     ("branch_terminals.csv", "terminal_status", "drop"), ("branch_terminals.csv", "input_frame_key", "foreign"))
        for name, field, value in mutations:
            with self.subTest(field=field):
                self.fixture.rows = copy.deepcopy(original)
                self.fixture.rows[name][0][field] = value
                self.fixture.save()
                self.rejected()

    def test_duplicate_frame_stage_branch_or_ledger_fail(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        for name in HEADERS:
            with self.subTest(name=name):
                self.fixture.rows = copy.deepcopy(original)
                self.fixture.rows[name].append(copy.deepcopy(self.fixture.rows[name][0]))
                self.fixture.save()
                self.rejected("duplicate")

    def test_incomplete_completed_path_and_mixed_decoder_layout_fail(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        self.fixture.rows["frame_events.csv"] = [r for r in original["frame_events.csv"] if r["stage"] != "postprocess_b"]
        self.fixture.save()
        self.rejected()
        self.fixture.rows = original
        extra = copy.deepcopy(original["frame_events.csv"][0])
        extra["stage"] = "decode_a"
        self.fixture.rows["frame_events.csv"].append(extra)
        self.fixture.save()
        self.rejected()

    def test_unrepresentable_deadline_fails(self):
        self.fixture.add().save()
        with self.assertRaises(self.diag.DiagnosticError):
            self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="1e-1000")

    def test_foreign_postprocess_branch_fails(self):
        self.fixture.add().save()
        extra = copy.deepcopy(self.fixture.rows["frame_events.csv"][-1])
        extra["stage"] = "postprocess_foreign"
        self.fixture.rows["frame_events.csv"].append(extra)
        self.fixture.save()
        self.rejected()

    def test_empty_supplied_policy_does_not_claim_deadline_corroboration(self):
        self.fixture.add(status="drop")
        for branch in self.fixture.rows["branch_terminals.csv"]:
            branch.update(terminal_status="drop", terminal_timestamp_ms=1020, objects=0)
        self.fixture.rows["ingress_ledger.csv"][0]["terminal_timestamp_ms"] = 1020
        self.fixture.rows["frame_events.csv"] = [r for r in self.fixture.rows["frame_events.csv"] if r["stage"] in {"decode", "preprocess"}]
        report = self.run_report([])
        self.assertEqual(report["policy_path"]["count"], 0)
        self.assertEqual(report["policy_path"]["reason"], "empty_population")
        self.assertFalse(report["deadline"]["policy_corroborated"])

    def test_nonfinite_reversed_and_invalid_numbers_fail(self):
        self.fixture.add()
        original = copy.deepcopy(self.fixture.rows)
        for name, field, value in (("frames.csv", "e2e_latency_ms", "NaN"), ("frame_events.csv", "stage_end_timestamp_ms", "Infinity"),
                                    ("frame_events.csv", "stage_end_timestamp_ms", 900), ("ingress_ledger.csv", "stream_id", "0.5"),
                                    ("ingress_ledger.csv", "window_end_timestamp_ms", 900)):
            with self.subTest(field=field):
                self.fixture.rows = copy.deepcopy(original)
                self.fixture.rows[name][0][field] = value
                self.fixture.save()
                self.rejected()

    def test_missing_input_invalid_utf8_and_duplicate_headers_fail(self):
        self.fixture.add().save()
        path = self.fixture.path / "frames.csv"
        path.unlink()
        self.rejected()
        self.fixture.save()
        path.write_bytes(b"\xff")
        self.rejected()
        self.fixture.save()
        text = path.read_text()
        path.write_text(text.replace("schema_version,", "run_id,", 1), encoding="utf-8")
        self.rejected("header")

    def test_csv_extra_or_missing_fields_fail(self):
        self.fixture.add().save()
        path = self.fixture.path / "frames.csv"
        text = path.read_text()
        path.write_text(text.rstrip() + ",unexpected\n", encoding="utf-8")
        self.rejected()
        path.write_text(text.rsplit(",", 1)[0] + "\n", encoding="utf-8")
        self.rejected()

    def test_required_deadline_is_finite_and_positive(self):
        self.fixture.add().save()
        for value in ("0", "-1", "NaN", "Infinity", ""):
            with self.subTest(deadline=value), self.assertRaises(self.diag.DiagnosticError):
                self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms=value)

    def test_input_hashes_identify_exact_bytes_and_inputs_remain_unchanged(self):
        self.fixture.add().save()
        before = self.snapshot()
        report = self.diag.run_diagnostic(self.fixture.path, self.root / "output", deadline_ms="100")
        self.assertEqual(before, self.snapshot())
        for item in report["inputs"]:
            self.assertEqual(item["sha256"], before[Path(item["path"]).name])
            self.assertEqual(item["size_bytes"], Path(item["path"]).stat().st_size)

    def test_occupied_output_preserves_existing_files_and_source(self):
        self.fixture.add().save()
        output = self.root / "output"
        output.mkdir()
        marker = output / "keep"
        marker.write_bytes(b"unchanged")
        self.rejected("exist|occupied")
        self.assertEqual(marker.read_bytes(), b"unchanged")
        self.assertEqual(list(output.iterdir()), [marker])

    def test_nonregular_and_symlink_inputs_fail(self):
        self.fixture.add().save()
        path = self.fixture.path / "frames.csv"
        path.unlink()
        path.mkdir()
        self.rejected("regular")
        path.rmdir()
        target = self.root / "external.csv"
        target.write_text(HEADERS["frames.csv"] + "\n", encoding="utf-8")
        # Linux mandatory lanes exercise the physical symlink; the Windows
        # fallback exercises the same unsafe lstat mode without requiring admin.
        try:
            path.symlink_to(target)
        except OSError:
            self.fixture.save()
            original_lstat = Path.lstat
            def observed(item, *args, **kwargs):
                info = original_lstat(item, *args, **kwargs)
                if item == path:
                    values = list(info)
                    values[0] = 0o120777
                    return type(info)(values)
                return info
            with mock.patch.object(Path, "lstat", observed):
                self.rejected("regular|symlink")
        else:
            self.rejected("regular|symlink")

    def test_individual_and_total_input_limits_fail_before_output(self):
        self.fixture.add().save()
        self.assertEqual(self.diag.MAX_INPUT_BYTES, 64 * 1024 * 1024)
        self.assertEqual(self.diag.MAX_TOTAL_INPUT_BYTES, 256 * 1024 * 1024)
        path = self.fixture.path / "frames.csv"
        with path.open("wb") as handle:
            handle.truncate(64 * 1024 * 1024 + 1)
        self.rejected("limit")
        self.fixture.save()
        with mock.patch.object(self.diag, "MAX_TOTAL_INPUT_BYTES", 1):
            self.rejected("limit")

    def test_cli_real_entrypoint_uses_only_selected_fixture_directory(self):
        self.fixture.add().save()
        command = [sys.executable, "-I", "-B", str(ROOT / "scripts/analyze_component_latency_v1.py"),
                   "--evidence-dir", str(self.fixture.path), "--deadline-ms", "100", "--output-dir", str(self.root / "output")]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.root / "output/diagnostic.json").read_text())
        self.assertEqual(report["counts"]["completed"], 1)
        self.assertEqual({p.name for p in (self.root / "output").iterdir()}, {"diagnostic.json", "per_completed_frame.csv", "report.md"})
        missing = subprocess.run(command[:command.index("--deadline-ms")] + command[command.index("--output-dir"):], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(missing.returncode, 0)


if __name__ == "__main__":
    unittest.main()
