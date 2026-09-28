from __future__ import annotations

import copy
import csv
import hashlib
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_checkpoint_native_policy_runtime import (  # noqa: E402
    calibration, capability_manifest, coordinator, path_message, request_message, terminal_message,
)
from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator, NativePolicyRuntimeError  # noqa: E402


def issue(runtime, frame_id: int, branch: str = "plate_number"):
    request = request_message(frame_id=frame_id, branch=branch)
    request["trace_id"] += ":worker-branch-" + branch
    response = runtime.handle_message(request["worker_id"], request)
    runtime.handle_message(request["worker_id"], path_message(response, request=request))
    return request, response


def complete(runtime, request, response):
    return runtime.handle_message(
        request["worker_id"], terminal_message(response, request=request)
    )


def cohort(*requests):
    return {
        request["input_frame_key"]: {
            "trace_id": "canonical-native-frame-%04d" % request["frame_id"],
            "stream_id": request["stream_id"], "frame_id": request["frame_id"],
        }
        for request in requests
    }


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


class PublicationProjectionCoordinatorTests(unittest.TestCase):
    def test_warmup_gap_projects_both_coordinates_without_changing_live_hashes(self):
        runtime = coordinator("cpu_only")
        warmup, warmup_response = issue(runtime, 1)
        complete(runtime, warmup, warmup_response)
        measured, measured_response = issue(runtime, 2)
        complete(runtime, measured, measured_response)
        original_issued = copy.deepcopy(runtime._engine._issued)
        original_accepted = copy.deepcopy(runtime._states[measured_response["decision_id"]].accepted)
        with tempfile.TemporaryDirectory() as tmp:
            runtime.promote(Path(tmp), canonical_frames=cohort(measured))
            records = read_jsonl(Path(tmp) / "publication_policy_decisions.jsonl")
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["decision_seq"], 1)
            self.assertEqual(record["request"]["decision_seq"], 1)
            self.assertEqual(record["trace_id"], "canonical-native-frame-0002")
            self.assertEqual(record["request"]["trace_id"], record["trace_id"])
            self.assertEqual(record["publication_projection"]["original_runtime_decision_seq"], 2)
            self.assertEqual(record["publication_projection"]["original_worker_trace_id"], measured["trace_id"])
            from publication_policy_projection_v1 import reconstruct_original_decision_v1
            accepted, issued = reconstruct_original_decision_v1(record)
            self.assertEqual(accepted, original_accepted)
            self.assertEqual(issued, original_issued[record["decision_id"]])
            with (Path(tmp) / "policy_decisions.csv").open(newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(int(row["decision_seq"]), 1)
            self.assertEqual(row["trace_id"], record["trace_id"])
            self.assertFalse((Path(tmp) / "publication_policy_runtime_history.jsonl").exists())
            self.assertFalse((Path(tmp) / "publication_policy_feedback.jsonl").exists())
        self.assertEqual(runtime._engine._issued, original_issued)
        self.assertEqual(runtime._states[record["decision_id"]].accepted, original_accepted)
        self.assertEqual(measured_response["decision_seq"], 2)

    def test_actual_interleaving_preserves_excluded_feedback_and_measurement_state(self):
        runtime = coordinator("adaptive_weights")
        warmup, warmup_response = issue(runtime, 1)
        measured1, response1 = issue(runtime, 2)
        complete(runtime, warmup, warmup_response)
        measured2, response2 = issue(runtime, 3, "damage")
        complete(runtime, measured2, response2)
        complete(runtime, measured1, response1)
        originals = {key: copy.deepcopy(state.accepted) for key, state in runtime._states.items()}
        raw_feedback = {key: copy.deepcopy(state.feedback) for key, state in runtime._states.items()}
        with tempfile.TemporaryDirectory() as tmp:
            runtime.promote(Path(tmp), canonical_frames=cohort(measured1, measured2))
            records = read_jsonl(Path(tmp) / "publication_policy_decisions.jsonl")
            feedback = read_jsonl(Path(tmp) / "publication_policy_feedback.jsonl")
            history = read_jsonl(Path(tmp) / "publication_policy_runtime_history.jsonl")
            self.assertEqual([record["decision_seq"] for record in records], [1, 2])
            self.assertEqual([record["decision_id"] for record in feedback], [response2["decision_id"], response1["decision_id"]])
            self.assertEqual(feedback, [raw_feedback[response2["decision_id"]], raw_feedback[response1["decision_id"]]])
            self.assertEqual([event["event_type"] for event in history[1:]], ["decision_issued", "decision_issued", "feedback_applied", "decision_issued", "feedback_applied", "feedback_applied"])
            self.assertEqual(history[1]["accepted_record"], originals[warmup_response["decision_id"]])
            self.assertEqual(history[3]["feedback_record"], raw_feedback[warmup_response["decision_id"]])
            self.assertEqual(history[0]["event_count"], 6)
            self.assertEqual(history[0]["measurement_feedback_count"], 2)
            from publication_policy_projection_v1 import validate_published_decisions_v1
            with (Path(tmp) / "policy_decisions.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            ingress = [dict(value, input_frame_key=key) for key, value in cohort(measured1, measured2).items()]
            report = validate_published_decisions_v1(records, rows, ingress_rows=ingress,
                history_path=Path(tmp) / "publication_policy_runtime_history.jsonl", feedback_records=feedback)
            self.assertTrue(report["runtime_history_verified"])
            self.assertEqual([row["feedback_seq"] for row in report["feedback_rows"]], [1, 2])
            self.assertEqual(report["original_accepted_records"], [originals[response1["decision_id"]], originals[response2["decision_id"]]])

    def test_incomplete_excluded_decision_blocks_publication(self):
        runtime = coordinator("cpu_only")
        issue(runtime, 1)
        measured, response = issue(runtime, 2)
        complete(runtime, measured, response)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(NativePolicyRuntimeError, "unterminated"):
                runtime.promote(Path(tmp), canonical_frames=cohort(measured))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_invalid_canonical_coordinate_fails_before_any_sidecar_is_exposed(self):
        runtime = coordinator("cpu_only")
        measured, response = issue(runtime, 1)
        complete(runtime, measured, response)
        mapping = cohort(measured)
        mapping[measured["input_frame_key"]]["frame_id"] = -1
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((NativePolicyRuntimeError, ValueError)):
                runtime.promote(Path(tmp), canonical_frames=mapping)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_existing_target_is_preserved_without_partial_publication(self):
        runtime = coordinator("adaptive_weights")
        measured, response = issue(runtime, 1)
        complete(runtime, measured, response)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "publication_policy_runtime_history.jsonl"
            target.write_bytes(b"existing immutable evidence\n")
            with self.assertRaisesRegex(NativePolicyRuntimeError, "overwrite"):
                runtime.promote(Path(tmp), canonical_frames=cohort(measured))
            self.assertEqual(target.read_bytes(), b"existing immutable evidence\n")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_duplicate_frame_branch_from_distinct_workers_cannot_be_promoted(self):
        runtime = coordinator("cpu_only")
        first, response1 = issue(runtime, 1)
        complete(runtime, first, response1)
        second = request_message(frame_id=1)
        second["worker_id"] = "worker-shared-0002"
        second["trace_id"] += ":worker-branch-plate_number"
        response2 = runtime.handle_message(second["worker_id"], second)
        runtime.handle_message(second["worker_id"], path_message(response2, request=second))
        complete(runtime, second, response2)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "duplicate publication input-frame/branch"):
                runtime.promote(Path(tmp), canonical_frames=cohort(first))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_capture_overflow_is_a_sticky_failure_before_publication(self):
        runtime = coordinator("adaptive_weights")
        with mock.patch("checkpoint_native_policy_runtime.MAX_RUNTIME_HISTORY_EVENTS_V1", 0):
            with self.assertRaisesRegex(NativePolicyRuntimeError, "bounds"):
                issue(runtime, 1)
        with self.assertRaisesRegex(NativePolicyRuntimeError, "bounds"):
            runtime.handle_message("worker-shared-0001", request_message(frame_id=2))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NativePolicyRuntimeError):
                runtime.promote(Path(tmp), canonical_frames={})
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_exclusive_publication_race_rolls_back_only_its_own_links(self):
        runtime = coordinator("cpu_only")
        measured, response = issue(runtime, 1)
        complete(runtime, measured, response)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            import os
            actual_link = os.link
            calls = []
            def concurrent_writer(source, target):
                calls.append(target)
                if len(calls) == 2:
                    Path(target).write_bytes(b"other producer evidence\n")
                return actual_link(source, target)
            with mock.patch("checkpoint_native_policy_runtime.os.link", side_effect=concurrent_writer):
                with self.assertRaises(FileExistsError):
                    runtime.promote(output, canonical_frames=cohort(measured))
            self.assertFalse((output / "publication_policy_decisions.jsonl").exists())
            self.assertEqual((output / "policy_decisions.csv").read_bytes(), b"other producer evidence\n")
            self.assertEqual(len(list(output.iterdir())), 1)

    def test_actual_coordinator_outputs_pass_independent_q4_verified_byte_loader(self):
        from publication_policy_contract import ANALYTICS_BRANCHES, POLICIES, select_static_hybrid_map
        validator_path = ROOT / "scripts/publication_q4_evidence_validator_v4.py"
        validator_sha = hashlib.sha256(validator_path.read_bytes()).hexdigest()
        driver = '''import csv, hashlib, json, sys
from pathlib import Path
source = Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(source).hexdigest() == sys.argv[2]
scope = {"__name__": "verified_q4_projection_coordinator_check"}
exec(compile(source, sys.argv[1], "exec"), scope)
root = Path(sys.argv[3]); policy = sys.argv[4]
with (root / "policy_decisions.csv").open(newline="") as stream:
    rows = list(csv.DictReader(stream))
records = scope["_validate_jsonl"](root / "publication_policy_decisions.jsonl",
    policy=policy, system="gstreamer_custom", run_id="run-native-policy-0001",
    expected_policy_contract_sha256=sys.argv[5], csv_decisions=rows)
scope["_validate_feedback"](root / "publication_policy_feedback.jsonl" if policy == "adaptive_weights" else None,
    policy=policy, decisions=records, run_id="run-native-policy-0001",
    runtime_history_path=root / "publication_policy_runtime_history.jsonl" if policy == "adaptive_weights" else None,
    accepted_ingress_input_keys=set(json.loads(sys.argv[6])))
print("verified independent replay passed", policy, len(records))
'''
        for policy in POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                manifest = capability_manifest()
                profile = calibration(manifest)
                static = select_static_hybrid_map("gstreamer_custom", profile, manifest)
                runtime = NativePolicyRuntimeCoordinator(run_id="run-native-policy-0001", arm_id="run-native-policy-0001",
                    system="gstreamer_custom", scenario="checkpoint_video_dag_shared", codec="h265", policy=policy,
                    deadline_ms=100.0, branches=ANALYTICS_BRANCHES, capability_manifest=manifest,
                    calibration=profile, static_hybrid_map=static if policy == "static_hybrid" else None)
                warmup, warmup_response = issue(runtime, 1)
                first, response1 = issue(runtime, 2)
                complete(runtime, warmup, warmup_response)
                second, response2 = issue(runtime, 3, "damage")
                complete(runtime, second, response2)
                complete(runtime, first, response1)
                mapping = cohort(first, second)
                runtime.promote(Path(tmp), canonical_frames=mapping)
                result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", driver,
                    str(validator_path), validator_sha, tmp, policy, manifest["policy_contract_sha256"], json.dumps(list(mapping))],
                    capture_output=True, text=True, check=False, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("verified independent replay passed", result.stdout)


class PublicationProjectionColdReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.runtime = coordinator("adaptive_weights")
        warmup, warmup_response = issue(self.runtime, 1)
        self.first, response1 = issue(self.runtime, 2)
        complete(self.runtime, warmup, warmup_response)
        self.second, response2 = issue(self.runtime, 3, "damage")
        complete(self.runtime, self.second, response2)
        complete(self.runtime, self.first, response1)
        drain, drain_response = issue(self.runtime, 4, "foreign_object")
        complete(self.runtime, drain, drain_response)
        self.runtime.promote(self.output, canonical_frames=cohort(self.first, self.second))
        self.records = read_jsonl(self.output / "publication_policy_decisions.jsonl")
        self.feedback = read_jsonl(self.output / "publication_policy_feedback.jsonl")
        self.history_path = self.output / "publication_policy_runtime_history.jsonl"
        self.history = read_jsonl(self.history_path)
        with (self.output / "policy_decisions.csv").open(newline="") as stream:
            self.rows = list(csv.DictReader(stream))
        self.ingress = [dict(value, input_frame_key=key) for key, value in cohort(self.first, self.second).items()]

    def validate(self, **changes):
        from publication_policy_projection_v1 import validate_published_decisions_v1
        arguments = dict(ingress_rows=self.ingress, history_path=self.history_path, feedback_records=self.feedback)
        arguments.update(changes)
        return validate_published_decisions_v1(self.records, self.rows, **arguments)

    def write_history(self):
        from publication_policy_frozen_replay_v1 import canonical_json_v1, payload_with_sha256_v1
        self.history_path.write_bytes(b"".join(canonical_json_v1(payload_with_sha256_v1(row)) + b"\n" for row in self.history))

    def rehash_record(self, index=0):
        from publication_policy_frozen_replay_v1 import payload_with_sha256_v1
        self.records[index] = payload_with_sha256_v1(self.records[index])

    def test_real_cold_reader_accepts_dense_view_with_actual_warmup_and_drain_history(self):
        from benchmark_contract import validate_frozen_policy_decisions, validate_frozen_policy_feedback, validate_policy_decisions
        decisions = validate_policy_decisions(self.output / "policy_decisions.csv",
            require_labeled_provenance=True, require_full_trace=True, require_causal_trace=True)
        records = validate_frozen_policy_decisions(self.output / "publication_policy_decisions.jsonl",
            decisions=decisions, expected_policy="adaptive_weights", ingress_rows=self.ingress)
        feedback = validate_frozen_policy_feedback(self.output / "publication_policy_feedback.jsonl",
            decisions=decisions, require_complete=True, ingress_rows=self.ingress)
        self.assertEqual(records, self.records)
        self.assertEqual(feedback["feedback_seq"].tolist(), [1, 2])
        self.assertTrue(self.validate()["runtime_history_verified"])

    def test_original_accepted_hash_and_issued_hash_cannot_be_relabelled(self):
        for key in ("accepted_record_sha256", "issued_record_sha256"):
            with self.subTest(key=key):
                original = copy.deepcopy(self.records)
                self.records[0]["publication_projection"][key] = "f" * 64
                self.rehash_record()
                with self.assertRaisesRegex(ValueError, "original .* hash"):
                    self.validate()
                self.records = original

    def test_dense_outer_and_request_ordinals_still_require_exact_csv_linkage(self):
        self.records[0]["decision_seq"] = self.records[0]["request"]["decision_seq"] = 9
        self.rehash_record()
        with self.assertRaisesRegex(ValueError, "dense/increasing"):
            self.validate()

    def test_csv_cannot_relabel_native_applied_evidence_as_another_claim(self):
        for field, value in (("decision_mode", "modelled"), ("telemetry_source", "derived"),
                             ("policy_version", "different-frozen-engine-v1")):
            with self.subTest(field=field):
                original = copy.deepcopy(self.rows)
                self.rows[0][field] = value
                with self.assertRaisesRegex(ValueError, "full native applied"):
                    self.validate()
                self.rows = original

    def test_physical_mapping_and_original_worker_provenance_are_authoritative(self):
        for kind in ("input_key", "coordinate", "worker_trace"):
            with self.subTest(kind=kind):
                ingress, rows = copy.deepcopy(self.ingress), copy.deepcopy(self.rows)
                if kind == "input_key":
                    self.ingress[0]["input_frame_key"] += ":substituted"
                elif kind == "coordinate":
                    self.ingress[0]["frame_id"] += 1
                else:
                    value = json.loads(self.rows[0]["feature_provenance_json"])
                    value["native_queue_depths"]["source_trace_id"] += ":substituted"
                    self.rows[0]["feature_provenance_json"] = json.dumps(value)
                with self.assertRaisesRegex(ValueError, "mapping|provenance"):
                    self.validate()
                self.ingress, self.rows = ingress, rows

    def test_duplicate_accepted_ingress_projection_is_rejected(self):
        self.ingress.append(copy.deepcopy(self.ingress[0]))
        with self.assertRaisesRegex(ValueError, "mapping is ambiguous"):
            self.validate()

    def test_resealed_original_native_event_reuse_cannot_cross_two_executions(self):
        from publication_policy_frozen_replay_v1 import payload_with_sha256_v1
        from publication_policy_projection_v1 import reconstruct_original_decision_v1, project_accepted_decision_v1
        original, issued = reconstruct_original_decision_v1(self.records[1])
        original["native_decision_evidence"]["event_id"] = self.records[0]["native_decision_evidence"]["event_id"]
        original = payload_with_sha256_v1(original)
        self.records[1] = project_accepted_decision_v1(original,
            canonical_trace_id=self.records[1]["trace_id"], publication_decision_seq=2,
            issued_record_sha256=issued["sha256"])
        for event in self.history[1:]:
            if event["event_type"] == "decision_issued" and event["decision_id"] == original["decision_id"]:
                event["accepted_record_sha256"] = original["sha256"]
        self.write_history()
        with self.assertRaisesRegex(ValueError, "duplicate publication original native event_id"):
            self.validate()

    def test_resealed_excluded_native_event_reuse_also_breaks_actual_history(self):
        from publication_policy_frozen_replay_v1 import payload_with_sha256_v1
        event = self.history[-2]
        self.assertEqual(event["event_type"], "decision_issued")
        self.assertFalse(event["measurement"])
        original = event["accepted_record"]
        original["native_decision_evidence"]["event_id"] = self.records[0]["native_decision_evidence"]["event_id"]
        original = payload_with_sha256_v1(original)
        event["accepted_record"] = original
        event["accepted_record_sha256"] = original["sha256"]
        self.write_history()
        with self.assertRaisesRegex(ValueError, "duplicate original native event_id in runtime history"):
            self.validate()

    def test_projection_version_fields_and_mixed_arms_are_strict(self):
        for kind in ("version", "extra", "mixed"):
            with self.subTest(kind=kind):
                original = copy.deepcopy(self.records)
                if kind == "version":
                    self.records[0]["publication_projection"]["schema_version"] = 2
                elif kind == "extra":
                    self.records[0]["publication_projection"]["synthetic_reset"] = True
                else:
                    self.records[0].pop("publication_projection")
                self.rehash_record()
                with self.assertRaises(ValueError):
                    self.validate()
                self.records = original

    def test_missing_history_and_removed_excluded_predecessor_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "require actual runtime history"):
            self.validate(history_path=None)
        del self.history[1]
        self.history[0]["event_count"] -= 1
        self.write_history()
        with self.assertRaisesRegex(ValueError, "closure|sequence"):
            self.validate()

    def test_interleaved_feedback_reorder_and_wrong_admission_hash_fail(self):
        for kind in ("reorder", "issued_hash"):
            with self.subTest(kind=kind):
                original = copy.deepcopy(self.history)
                if kind == "reorder":
                    self.history[3], self.history[4] = self.history[4], self.history[3]
                    for ordinal, event in enumerate(self.history[1:], 1):
                        event["event_seq"] = ordinal
                else:
                    self.history[3]["issued_record_sha256"] = "f" * 64
                self.write_history()
                with self.assertRaisesRegex(ValueError, "actual history|admission"):
                    self.validate()
                self.history = original
        self.write_history()

    def test_measurement_omission_cannot_be_hidden_as_an_excluded_decision(self):
        omitted = self.records.pop()
        self.rows.pop()
        self.feedback = [record for record in self.feedback if record["decision_id"] != omitted["decision_id"]]
        self.history[0]["measurement_decision_count"] -= 1
        self.history[0]["measurement_feedback_count"] -= 1
        for event in self.history[1:]:
            if event["decision_id"] == omitted["decision_id"]:
                event["measurement"] = False
                if event["event_type"] == "decision_issued":
                    event["accepted_record"] = self.runtime._states[omitted["decision_id"]].accepted
                else:
                    event["feedback_record"] = self.runtime._states[omitted["decision_id"]].feedback
        self.write_history()
        with self.assertRaisesRegex(ValueError, "omits/substitutes"):
            self.validate()

    def test_original_feedback_payload_state_and_native_terminal_must_match(self):
        from publication_policy_frozen_replay_v1 import payload_with_sha256_v1
        self.feedback[0]["state_after"]["weights"]["gpu"] += 0.02
        self.feedback[0] = payload_with_sha256_v1(self.feedback[0])
        for event in self.history[1:]:
            if event["event_type"] == "feedback_applied" and event["decision_id"] == self.feedback[0]["decision_id"]:
                event["feedback_record_sha256"] = self.feedback[0]["sha256"]
        self.write_history()
        with self.assertRaisesRegex(ValueError, "frozen transition"):
            self.validate()

    def test_actual_reset_and_current_manifest_authority_are_required(self):
        self.history[0]["initial_state"]["weights"]["cpu"] = 0.9
        self.write_history()
        with self.assertRaisesRegex(ValueError, "actual initial reset"):
            self.validate()
        self.history[0]["initial_state"]["weights"]["cpu"] = 1.0
        self.write_history()
        with self.assertRaisesRegex(ValueError, "capability/native authority"):
            self.validate(authority_callback=lambda record: {"passed": False})

    def test_strict_reader_rejects_duplicate_keys_nonfinite_and_truncation(self):
        from publication_policy_projection_v1 import read_runtime_history_v1
        for payload in (b'{"sha256":"a","sha256":"b"}\n', b'{"value":NaN}\n', b'{"value":1}'):
            with self.subTest(payload=payload):
                self.history_path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    read_runtime_history_v1(self.history_path)

    def test_streaming_reader_and_writer_enforce_byte_event_and_line_bounds(self):
        import publication_policy_projection_v1 as projection
        for name, limit in (("MAX_RUNTIME_HISTORY_BYTES_V1", self.history_path.stat().st_size - 1),
                            ("MAX_RUNTIME_HISTORY_EVENTS_V1", len(self.history) - 2),
                            ("MAX_RUNTIME_HISTORY_LINE_BYTES_V1", 128)):
            with self.subTest(name=name), mock.patch.object(projection, name, limit):
                with self.assertRaisesRegex(ValueError, "bound"):
                    projection.read_runtime_history_v1(self.history_path)
        consumed = []
        def source():
            for event in self.history[1:]:
                consumed.append(event)
                yield event
        with mock.patch.object(projection, "MAX_RUNTIME_HISTORY_BYTES_V1", 1024):
            with self.assertRaisesRegex(ValueError, "bound"):
                projection.serialize_runtime_history_v1(self.history[0], source())
        self.assertLess(len(consumed), len(self.history) - 1)


if __name__ == "__main__":
    unittest.main()
