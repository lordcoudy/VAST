from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "scripts", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import publication_q4_evidence_validator_v4 as target
from publication_policy_contract import PolicyEngine, select_static_hybrid_map
from test_publication_policy_contract import calibration, valid_capability_manifest
from test_publication_q4_evidence_validator_v4 import (
    EvidenceFixture, canonical, write_csv, write_json,
)


HISTORY = "publication_policy_runtime_history.jsonl"


def seal(value: dict) -> dict:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return {**payload, "sha256": target.canonical_sha256(payload)}


def project(original: dict, trace: str, sequence: int) -> dict:
    issued = copy.deepcopy(original)
    issued["record_status"] = "replayable_not_runtime_accepted"
    issued["native_decision_evidence"] = None
    issued = seal(issued)
    result = copy.deepcopy(original)
    result["publication_projection"] = {
        "schema_version": 1,
        "original_worker_trace_id": original["trace_id"],
        "original_runtime_decision_seq": original["decision_seq"],
        "issued_record_sha256": issued["sha256"],
        "accepted_record_sha256": original["sha256"],
    }
    result["trace_id"] = result["request"]["trace_id"] = trace
    result["decision_seq"] = result["request"]["decision_seq"] = sequence
    return seal(result)


class ProjectedFixture(EvidenceFixture):
    """Use the real engine to generate originals, not Q4's replay equations."""

    def __init__(self, root: Path, *, policy: str = "cpu_only", runtime_authority_sha: str = "1" * 64, expired_deadline: bool = False, arrival_after_decision: bool = False) -> None:
        super().__init__(root, policy=policy, runtime_authority_sha=runtime_authority_sha)
        self.decision_path = self.evidence / target.POLICY_DECISIONS_JSONL
        self.feedback_path = self.evidence / target.POLICY_FEEDBACK_JSONL
        self.history_path = self.evidence / HISTORY
        self.originals: list[dict] = []
        self.feedback: list[dict] = []
        self.events: list[dict] = []
        samples = [json.loads(line) for line in self.decision_path.read_bytes().splitlines()]
        manifest = valid_capability_manifest()
        for branch in target.BRANCHES:
            for resource in target.RESOURCES:
                manifest["systems"]["deepstream"]["branches"][branch][resource][
                    "implementation_id"
                ] = f"impl-{branch}-{resource}"
        static_map = None
        if policy == "static_hybrid":
            profile = calibration("deepstream", manifest)
            for branch in target.BRANCHES:
                selected = "cpu" if branch in {"plate_number", "damage"} else "gpu"
                for resource in target.RESOURCES:
                    profile["costs"][branch][resource]["service_ms"] = 2.0 if resource == selected else 50.0
                    profile["costs"][branch][resource]["transfer_ms"] = 0.0
            static_map = select_static_hybrid_map("deepstream", profile, manifest)
        engine = PolicyEngine(policy=policy, system="deepstream", capability_manifest=manifest, static_hybrid_map=static_map)
        engine.reset(self.run_id)
        initial = engine.state_snapshot()
        issued_records: dict[str, dict] = {}
        accepted_records: dict[str, dict] = {}
        measurement_ids: set[str] = set()

        def issue(sample: dict, *, measured: bool, suffix: str = "") -> dict:
            request = copy.deepcopy(sample["request"])
            request["decision_seq"] = len(issued_records) + 1
            request["decision_id"] += suffix
            request["trace_id"] = f"worker:{sample['trace_id']}:{sample['branch']}{suffix}"
            if expired_deadline:
                request["deadline_ms"] = 0.25
            if arrival_after_decision:
                request["arrival_ms"] = request["decision_time_ms"] + 1.0
            if policy == "adaptive_weights":
                request["candidates"]["cpu"]["estimated_service_ms"] = 50.0
            issued = engine.decide(request)
            accepted = copy.deepcopy(issued)
            accepted["record_status"] = "accepted_native_runtime_decision"
            accepted["native_decision_evidence"] = copy.deepcopy(sample["native_decision_evidence"])
            accepted["native_decision_evidence"]["decision_id"] = issued["decision_id"]
            accepted["native_decision_evidence"]["event_id"] += suffix
            if not measured:
                accepted["native_decision_evidence"]["input_frame_key"] += suffix
                accepted["native_decision_evidence"]["transport_pts_ns"] += 1_000_000_000
                if suffix == "-warmup" and policy == "adaptive_weights":
                    accepted["native_decision_evidence"]["terminal_timestamp_ms"] = 20.0
                    accepted["native_decision_evidence"]["actual_service_ms"] = 17.0
            accepted = seal(accepted)
            issued_records[issued["decision_id"]] = issued
            accepted_records[issued["decision_id"]] = accepted
            if measured:
                measurement_ids.add(issued["decision_id"])
                self.originals.append(accepted)
            self.events.append({
                "event_type": "decision_issued",
                "runtime_decision_seq": issued["decision_seq"],
                "decision_id": issued["decision_id"], "measurement": measured,
                "issued_record_sha256": issued["sha256"],
                "accepted_record_sha256": accepted["sha256"],
                "accepted_record": None if measured else accepted,
            })
            return issued

        def feedback(issued: dict) -> None:
            native = accepted_records[issued["decision_id"]]["native_decision_evidence"]
            item = engine.feedback(issued, actual_service_ms=native["actual_service_ms"], completed_at_ms=native["terminal_timestamp_ms"])
            measured = issued["decision_id"] in measurement_ids
            if measured:
                self.feedback.append(item)
            self.events.append({
                "event_type": "feedback_applied",
                "runtime_feedback_seq": sum(
                    event["event_type"] == "feedback_applied" for event in self.events
                ) + 1,
                "decision_id": issued["decision_id"], "measurement": measured,
                "issued_record_sha256": issued["sha256"],
                "feedback_record_sha256": item["sha256"],
                "feedback_record": None if measured else item,
            })

        if policy == "adaptive_weights":
            predecessor = issue(samples[0], measured=False, suffix="-warmup")
            first = issue(samples[0], measured=True)
            feedback(predecessor)
            interleaved = issue(samples[1], measured=False, suffix="-drain")
            second = issue(samples[1], measured=True)
            feedback(interleaved)
            feedback(second)
            feedback(first)
            for sample in samples[2:]:
                feedback(issue(sample, measured=True))
        else:
            issue(samples[0], measured=False, suffix="-warmup")
            for sample in samples:
                issue(sample, measured=True)

        self.projected = [
            project(original, sample["trace_id"], number)
            for number, (original, sample) in enumerate(zip(self.originals, samples), start=1)
        ]
        self.write_decisions()
        with (self.evidence / "policy_decisions.csv").open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        for row, original in zip(rows, self.originals):
            native = original["native_decision_evidence"]
            row["feature_provenance_json"] = canonical({"native_queue_depths": {
                "source": f"native_worker_socket:{native['worker_id']}",
                "source_trace_id": original["trace_id"],
            }}).decode("ascii")
        write_csv(self.evidence / "policy_decisions.csv", target.POLICY_DECISION_COLUMNS, rows)
        self.policy_contract_sha = manifest["policy_contract_sha256"]
        contract = json.loads(self.contract_path.read_bytes())
        graph = contract["native_graph_contract"]
        graph["upstream_identities"]["policy_contract_sha256"] = self.policy_contract_sha
        if policy == "adaptive_weights":
            names = list(target.qualification_launcher_evidence_files_v4(policy))
            names.insert(names.index(target.POLICY_FEEDBACK_JSONL) + 1, HISTORY)
            graph["launcher_evidence_files"] = names
            template = contract["runtime_inputs"]["dataset"]["deepstream_publication_runtime_v3"]
            template["evidence_mapping"][HISTORY] = HISTORY
            graph["runtime_inputs_sha256"] = target.canonical_sha256(contract["runtime_inputs"])
            self.feedback_path.write_bytes(b"".join(canonical(item) + b"\n" for item in self.feedback))
            self.header = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_runtime_history_v1",
                "record_kind": "header", "run_id": self.run_id,
                "arm_id": self.run_id, "system": "deepstream", "policy": policy,
                "policy_contract_sha256": self.policy_contract_sha,
                "engine_implementation_id": "vast-publication-policy-engine-v1",
                "initial_state": initial,
                "runtime_decision_count": len(issued_records),
                "runtime_feedback_count": len(issued_records),
                "measurement_decision_count": len(self.projected),
                "measurement_feedback_count": len(self.feedback),
                "event_count": len(self.events),
            }
            self.write_history()
        graph.pop("graph_contract_sha256")
        graph["graph_contract_sha256"] = target.canonical_sha256(graph)
        contract.pop("contract_sha256")
        contract["contract_sha256"] = target.canonical_sha256(contract)
        write_json(self.contract_path, contract)
        self.refresh_candidate()

    def write_decisions(self) -> None:
        self.decision_path.write_bytes(b"".join(canonical(item) + b"\n" for item in self.projected))

    def write_history(self) -> None:
        records = [seal(self.header)]
        records += [seal({
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_runtime_history_event_v1",
            "event_seq": number, **event,
        }) for number, event in enumerate(self.events, start=1)]
        self.history_path.write_bytes(b"".join(canonical(item) + b"\n" for item in records))

    def refresh_candidate(self) -> None:
        path = self.evidence / target.CANDIDATE_FILENAME
        candidate = json.loads(path.read_bytes())
        names = list(target.pre_finalization_evidence_files_v4(self.coordinate["policy"]))
        if self.coordinate["policy"] == "adaptive_weights":
            names.append(HISTORY)
        candidate["evidence_sha256"] = {
            name: hashlib.sha256((self.evidence / name).read_bytes()).hexdigest()
            for name in names
        }
        write_json(path, candidate)


class PublicationQ4PolicyProjectionV1Tests(unittest.TestCase):
    def validate(self, fixture: ProjectedFixture) -> dict:
        return target.validate_publication_q4_evidence_files_v4(
            project_root=fixture.root, raw_evidence_manifest=fixture.manifest(),
        )

    def test_projected_nonadaptive_engine_records_and_filtered_ordinals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve())
            self.assertEqual(fixture.originals[0]["decision_seq"], 2)
            self.assertEqual(fixture.projected[0]["decision_seq"], 1)
            self.assertNotEqual(fixture.originals[0]["trace_id"], fixture.projected[0]["trace_id"])
            self.assertEqual(self.validate(fixture)["replay_result"], target.QUALIFIED_REPLAY_RESULT)

    def test_projected_adaptive_actual_predecessor_and_interleaved_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
            self.assertEqual(fixture.feedback[0]["decision_id"], fixture.projected[1]["decision_id"])
            self.assertNotEqual(fixture.originals[1]["state_before"], fixture.header["initial_state"])
            self.assertEqual(fixture.events[2]["feedback_record"]["outcome"], "late")
            self.assertGreater(fixture.originals[1]["state_before"]["weights"]["gpu"], 1.0)
            self.assertEqual(self.validate(fixture)["replay_result"], target.QUALIFIED_REPLAY_RESULT)

    def test_all_nonadaptive_projected_frozen_policy_paths_replay(self) -> None:
        for policy in target.POLICIES[:-1]:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy=policy)
                self.assertFalse(fixture.history_path.exists())
                self.assertFalse(fixture.feedback_path.exists())
                self.assertEqual(self.validate(fixture)["replay_result"], target.QUALIFIED_REPLAY_RESULT)

    def test_projected_expired_engine_deadlines_replay_and_legacy_timing_stays_strict(self) -> None:
        for policy in target.POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy=policy, expired_deadline=True)
                original = fixture.originals[0]
                self.assertGreater(original["request"]["decision_time_ms"], original["request"]["deadline_ms"])
                self.assertEqual(self.validate(fixture)["replay_result"], target.QUALIFIED_REPLAY_RESULT)
                with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "request timing drifted"):
                    target._validate_native_decision_record(
                        original, policy=policy, system="deepstream", arm_id=fixture.run_id,
                        contract_sha256=fixture.policy_contract_sha, label="legacy original",
                    )

    def test_actual_coordinator_clamp_replays_expired_excluded_predecessor(self) -> None:
        from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator
        from tests.test_checkpoint_native_policy_runtime import (
            capability_manifest, calibration as native_calibration,
            request_message, path_message, terminal_message,
        )

        manifest = capability_manifest()
        run_id = "native-expired-history-review-arm"
        native = NativePolicyRuntimeCoordinator(
            run_id=run_id, arm_id=run_id, system="gstreamer_custom",
            scenario="checkpoint_video_dag_shared", codec="h265", policy="adaptive_weights",
            deadline_ms=100.0, branches=target.BRANCHES,
            capability_manifest=manifest, calibration=native_calibration(manifest),
        )

        def issue(frame_id, *, arrival, decision, feature):
            request = request_message(frame_id=frame_id, run_id=run_id)
            request.update(arrival_ms=arrival, decision_time_ms=decision,
                           feature_observed_timestamp_ms=feature)
            response = native.handle_message(request["worker_id"], request)
            native.handle_message(request["worker_id"], path_message(response, request=request))
            native.handle_message(request["worker_id"], terminal_message(response, request=request))
            return request, response

        issue(1, arrival=1990.0, decision=2000.0, feature=1999.0)
        expired, response = issue(2, arrival=900.0, decision=1999.0, feature=1998.0)
        measured, measured_response = issue(3, arrival=2090.0, decision=2100.0, feature=2099.0)
        original = native._states[response["decision_id"]].accepted
        self.assertEqual(original["request"]["decision_time_ms"], 2000.0)
        self.assertEqual(original["request"]["deadline_ms"], 1000.0)
        self.assertNotEqual(original["request"]["decision_time_ms"], expired["decision_time_ms"])
        self.assertEqual(native._states[response["decision_id"]].feedback["outcome"], "late")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            native.promote(output, canonical_frames={measured["input_frame_key"]: {
                "trace_id": f"{run_id}:0:3", "stream_id": 0, "frame_id": 3,
            }})
            with (output / "policy_decisions.csv").open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            decisions = target._validate_jsonl(
                output / target.POLICY_DECISIONS_JSONL, policy="adaptive_weights", system="gstreamer_custom",
                run_id=run_id, expected_policy_contract_sha256=manifest["policy_contract_sha256"], csv_decisions=rows,
            )
            self.assertEqual([item["decision_id"] for item in decisions], [measured_response["decision_id"]])
            target._validate_feedback(
                output / target.POLICY_FEEDBACK_JSONL, policy="adaptive_weights", decisions=decisions,
                runtime_history_path=output / HISTORY, run_id=run_id,
                accepted_ingress_input_keys={measured["input_frame_key"]},
            )

    def test_projected_engine_arrival_and_decision_are_independently_nonnegative(self) -> None:
        for policy in target.POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy=policy, arrival_after_decision=True)
                original = fixture.originals[0]
                self.assertGreater(original["request"]["arrival_ms"], original["request"]["decision_time_ms"])
                self.assertEqual(self.validate(fixture)["replay_result"], target.QUALIFIED_REPLAY_RESULT)
                with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "request timing drifted"):
                    target._validate_native_decision_record(
                        original, policy=policy, system="deepstream", arm_id=fixture.run_id,
                        contract_sha256=fixture.policy_contract_sha, label="legacy original",
                    )

    def test_projected_measured_native_event_id_reuse_is_rejected_after_resealing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve())
            original = copy.deepcopy(fixture.originals[1])
            original["native_decision_evidence"]["event_id"] = fixture.originals[0]["native_decision_evidence"]["event_id"]
            fixture.projected[1] = project(seal(original), fixture.projected[1]["trace_id"], 2)
            fixture.write_decisions()
            fixture.refresh_candidate()
            with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "native decision event_id reused"):
                self.validate(fixture)

    def test_excluded_history_native_event_id_reuse_is_rejected_after_resealing(self) -> None:
        for duplicate in ("measured event", "excluded event"):
            with self.subTest(duplicate=duplicate), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
                excluded = [event for event in fixture.events if event["event_type"] == "decision_issued" and not event["measurement"]]
                event = excluded[0] if duplicate == "measured event" else excluded[1]
                other = fixture.originals[0] if duplicate == "measured event" else excluded[0]["accepted_record"]
                event["accepted_record"]["native_decision_evidence"]["event_id"] = other["native_decision_evidence"]["event_id"]
                event["accepted_record"] = seal(event["accepted_record"])
                event["accepted_record_sha256"] = event["accepted_record"]["sha256"]
                fixture.write_history()
                fixture.refresh_candidate()
                with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "native decision event_id reused"):
                    self.validate(fixture)

    def test_projection_metadata_and_original_authority_drift_rejected(self) -> None:
        mutations = {
            "version": lambda item: item["publication_projection"].update(schema_version=2),
            "issued hash": lambda item: item["publication_projection"].update(issued_record_sha256="0" * 64),
            "accepted hash": lambda item: item["publication_projection"].update(accepted_record_sha256="0" * 64),
            "extra field": lambda item: item["publication_projection"].update(extra=1),
            "request trace": lambda item: item["request"].update(trace_id="unbound-frame"),
            "reset state": lambda item: item["state_before"]["weights"].update(cpu=1.1),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve())
                mutate(fixture.projected[0])
                fixture.projected[0] = seal(fixture.projected[0])
                fixture.write_decisions()
                fixture.refresh_candidate()
                with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                    self.validate(fixture)

    def test_mixed_records_and_invalid_source_mapping_rejected(self) -> None:
        for label in ("legacy row", "worker trace", "worker identity", "input key"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve())
                if label == "legacy row":
                    original = copy.deepcopy(fixture.projected[0])
                    original.pop("publication_projection")
                    fixture.projected[0] = seal(original)
                elif label == "input key":
                    original = copy.deepcopy(fixture.originals[0])
                    original["native_decision_evidence"]["input_frame_key"] = "unbound-input"
                    fixture.projected[0] = project(seal(original), fixture.projected[0]["trace_id"], 1)
                else:
                    path = fixture.evidence / "policy_decisions.csv"
                    with path.open(newline="", encoding="utf-8") as source:
                        rows = list(csv.DictReader(source))
                    provenance = json.loads(rows[0]["feature_provenance_json"])
                    key = "source_trace_id" if label == "worker trace" else "source"
                    provenance["native_queue_depths"][key] = "unbound-worker"
                    rows[0]["feature_provenance_json"] = canonical(provenance).decode("ascii")
                    write_csv(path, target.POLICY_DECISION_COLUMNS, rows)
                fixture.write_decisions()
                fixture.refresh_candidate()
                with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                    self.validate(fixture)

    def test_resealed_originals_require_frozen_numeric_types_and_reset(self) -> None:
        for label in ("boolean arrival", "integer arrival", "integer reset", "integer evaluation", "native PTS"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve())
                original = copy.deepcopy(fixture.originals[0])
                if label == "boolean arrival":
                    original["request"]["arrival_ms"] = False
                elif label == "integer arrival":
                    original["request"]["arrival_ms"] = 0
                elif label == "integer reset":
                    original["state_before"]["weights"]["cpu"] = 1
                elif label == "integer evaluation":
                    original["evaluations"]["cpu"]["available_ms"] = 0
                else:
                    original["native_decision_evidence"]["transport_pts_ns"] = -1
                fixture.projected[0] = project(seal(original), fixture.projected[0]["trace_id"], 1)
                fixture.write_decisions()
                fixture.refresh_candidate()
                with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                    self.validate(fixture)

    def test_excluded_history_cannot_hide_a_measured_input_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
            event = fixture.events[0]
            event["accepted_record"]["native_decision_evidence"]["input_frame_key"] = fixture.originals[0]["native_decision_evidence"]["input_frame_key"]
            event["accepted_record"] = seal(event["accepted_record"])
            event["accepted_record_sha256"] = event["accepted_record"]["sha256"]
            fixture.write_history()
            fixture.refresh_candidate()
            with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                self.validate(fixture)

    def test_measurement_projection_cannot_duplicate_one_branch_and_omit_another(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve())
            original = copy.deepcopy(fixture.originals[0])
            decision_id = fixture.originals[1]["decision_id"]
            original["decision_id"] = original["request"]["decision_id"] = decision_id
            original["decision_seq"] = original["request"]["decision_seq"] = fixture.originals[1]["decision_seq"]
            original["native_decision_evidence"]["decision_id"] = decision_id
            original["native_decision_evidence"]["event_id"] = f"native-{decision_id}"
            fixture.projected[1] = project(seal(original), fixture.projected[1]["trace_id"], 2)
            fixture.write_decisions()
            path = fixture.evidence / "policy_decisions.csv"
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            for field in ("stage", "decision", "resource", "feature_provenance_json"):
                rows[1][field] = rows[0][field]
            write_csv(path, target.POLICY_DECISION_COLUMNS, rows)
            fixture.refresh_candidate()
            with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                self.validate(fixture)

    def test_adaptive_history_actual_order_and_closure_corruption_rejected(self) -> None:
        labels = (
            "initial reset", "missing predecessor", "reordered feedback", "duplicate issuance",
            "runtime ordinal", "orphan feedback", "measurement cohort", "issued authority",
            "excluded payload", "feedback state", "header count", "history version",
        )
        for label in labels:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
                if label == "initial reset":
                    fixture.header["initial_state"]["weights"]["gpu"] = 1.1
                elif label == "missing predecessor":
                    del fixture.events[2]
                    fixture.header["event_count"] -= 1
                elif label == "reordered feedback":
                    fixture.events[2], fixture.events[3] = fixture.events[3], fixture.events[2]
                elif label == "duplicate issuance":
                    fixture.events[1] = copy.deepcopy(fixture.events[0])
                elif label == "runtime ordinal":
                    fixture.events[0]["runtime_decision_seq"] = 2
                elif label == "orphan feedback":
                    fixture.events[2]["decision_id"] = "missing-decision"
                elif label == "measurement cohort":
                    fixture.events[1]["measurement"] = False
                    fixture.events[1]["accepted_record"] = fixture.originals[0]
                elif label == "issued authority":
                    fixture.events[2]["issued_record_sha256"] = "0" * 64
                elif label == "excluded payload":
                    fixture.events[0]["accepted_record"] = None
                elif label == "feedback state":
                    fixture.feedback[0]["state_after"]["weights"]["gpu"] = 1.25
                    fixture.feedback[0] = seal(fixture.feedback[0])
                    fixture.events[6]["feedback_record_sha256"] = fixture.feedback[0]["sha256"]
                    fixture.feedback_path.write_bytes(b"".join(canonical(item) + b"\n" for item in fixture.feedback))
                elif label == "header count":
                    fixture.header["runtime_decision_count"] += 1
                else:
                    fixture.header["schema_version"] = 2
                fixture.write_history()
                fixture.refresh_candidate()
                with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                    self.validate(fixture)

    def test_history_missing_for_projected_or_added_to_legacy_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
            fixture.history_path.unlink()
            with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                self.validate(fixture)
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
            fixture.projected = [
                seal({key: value for key, value in item.items() if key != "publication_projection"})
                for item in fixture.projected
            ]
            fixture.write_decisions()
            fixture.refresh_candidate()
            with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                self.validate(fixture)

    def test_history_bounded_and_duplicate_nonfinite_records_rejected(self) -> None:
        for label in ("line limit", "file limit", "event limit", "duplicate key", "nonfinite"):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
                if label == "line limit":
                    fixture.history_path.write_bytes(b" " * (256 * 1024 + 1) + b"\n")
                elif label == "file limit":
                    with fixture.history_path.open("wb") as output:
                        output.truncate(64 * 1024 * 1024 + 1)
                elif label == "event limit":
                    fixture.header["event_count"] = 1_000_001
                    fixture.write_history()
                elif label == "duplicate key":
                    fixture.history_path.write_bytes(b'{"schema_version":1,"schema_version":1}\n')
                else:
                    fixture.history_path.write_bytes(b'{"state":NaN}\n')
                fixture.refresh_candidate()
                with self.assertRaises(target.PublicationQ4EvidenceV4Error):
                    self.validate(fixture)

    @unittest.skipIf(os.name == "nt", "the pinned isolated interpreter is exercised in WSL")
    def test_actual_isolated_formal_runner_accepts_projected_cpu_and_rejects_drift(self) -> None:
        import test_publication_q4_evidence_runner_v4 as runner_tests

        case = runner_tests.PublicationQ4EvidenceRunnerV4Tests()
        with mock.patch.object(runner_tests, "EvidenceFixture", ProjectedFixture):
            case.setUp()
        try:
            before = {path.relative_to(case.root).as_posix(): path.read_bytes() for path in case.root.rglob("*") if path.is_file()}
            result = case.invoke()
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout)["replay_result"], target.QUALIFIED_REPLAY_RESULT)
            after = {path.relative_to(case.root).as_posix(): path.read_bytes() for path in case.root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

            case.evidence.projected[0]["publication_projection"]["issued_record_sha256"] = "0" * 64
            case.evidence.projected[0] = seal(case.evidence.projected[0])
            case.evidence.write_decisions()
            case.evidence.refresh_candidate()
            raw = case.evidence.manifest()
            write_json(case.root / "authority/raw-evidence.json", raw)
            request = copy.deepcopy(case.request)
            request["raw_evidence_ref"] = {
                "descriptor": runner_tests.descriptor(case.root, "authority/raw-evidence.json"),
                "content_identity_sha256": raw["raw_evidence_manifest_sha256"],
            }
            request.pop("request_sha256")
            request["request_sha256"] = target.canonical_sha256(request)
            write_json(case.root / "authority/request.json", request)
            argv = list(case.argv)
            argv[argv.index("--request-file-sha256") + 1] = runner_tests.descriptor(case.root, "authority/request.json")["sha256"]
            argv[argv.index("--request-sha256") + 1] = request["request_sha256"]
            result = case.invoke(argv)
            self.assertEqual(result.returncode, 78, result.stderr.decode())
            self.assertIn(b"original issued hash", result.stderr)
            self.assertEqual(result.stdout, b"")
        finally:
            case.tearDown()

    @unittest.skipIf(os.name == "nt", "the pinned isolated interpreter is exercised in WSL")
    def test_actual_isolated_verified_byte_loader_replays_adaptive_history(self) -> None:
        program = """
import hashlib, json, pathlib, sys, types
runner_path, runner_sha, validator_path, validator_sha, root, manifest_path, manifest_sha = sys.argv[1:]
def pinned(path, expected):
    raw = pathlib.Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('verified source bytes drifted')
    return raw
runner_source = pinned(runner_path, runner_sha)
validator_source = pinned(validator_path, validator_sha)
manifest = json.loads(pinned(manifest_path, manifest_sha))
runner = types.ModuleType('_verified_q4_runner')
runner.__file__ = runner_path
exec(compile(runner_source.decode('utf-8'), runner_path, 'exec', dont_inherit=True), runner.__dict__)
with runner._ReadOnlyNetworkFence():
    module = runner._load_validator_module(pathlib.Path(validator_path), validator_source)
    result = module.validate_publication_q4_evidence_files_v4(project_root=root, raw_evidence_manifest=manifest)
if any(name.startswith('publication_policy_') for name in sys.modules):
    raise ValueError('project policy helper was imported')
print(json.dumps(result['replay_result'], sort_keys=True, separators=(',', ':')))
"""
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProjectedFixture(Path(directory).resolve(), policy="adaptive_weights")
            manifest_path = fixture.root / "manifest.json"
            runner_path = ROOT / "scripts/publication_q4_evidence_runner_v4.py"
            validator_path = ROOT / "scripts/publication_q4_evidence_validator_v4.py"
            for invalid in (False, True):
                with self.subTest(invalid=invalid):
                    if invalid:
                        fixture.events[2], fixture.events[3] = fixture.events[3], fixture.events[2]
                        fixture.write_history()
                        fixture.refresh_candidate()
                    write_json(manifest_path, fixture.manifest())
                    before = {path.relative_to(fixture.root).as_posix(): path.read_bytes() for path in fixture.root.rglob("*") if path.is_file()}
                    paths = (runner_path, validator_path)
                    args = [item for path in paths for item in (str(path), hashlib.sha256(path.read_bytes()).hexdigest())]
                    completed = subprocess.run(
                        [sys.executable, "-I", "-S", "-B", "-c", program, *args, str(fixture.root), str(manifest_path), hashlib.sha256(manifest_path.read_bytes()).hexdigest()],
                        cwd=fixture.root, env={}, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                        close_fds=True, check=False,
                    )
                    if invalid:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(b"state linkage", completed.stderr)
                        self.assertEqual(completed.stdout, b"")
                    else:
                        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                        self.assertEqual(json.loads(completed.stdout), target.QUALIFIED_REPLAY_RESULT)
                        self.assertEqual(completed.stderr, b"")
                    after = {path.relative_to(fixture.root).as_posix(): path.read_bytes() for path in fixture.root.rglob("*") if path.is_file()}
                    self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
