"""Bounded operational evidence contracts; fixtures confer no publication authority."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_policy_contract import validate_decision_record
from checkpoint_native_policy_runtime import NativePolicyRuntimeError
from publication_policy_projection_v1 import (
    project_accepted_decision_v1,
    reconstruct_original_decision_v1,
)
from tests.test_checkpoint_native_policy_runtime import (
    capability_manifest,
    coordinator,
    path_message,
    request_message,
    terminal_message,
)


NATIVE_FIELDS = {
    "schema_version", "artifact_kind", "runtime_decision_seq", "decision_id",
    "measurement", "decision_request", "accepted_record", "path", "terminal",
    "issued_record_sha256", "accepted_record_sha256", "sha256",
}
BEGIN_FIELDS = {
    "type", "seq", "request_seq", "connection", "local_seq", "binding",
    "request_id", "input_key", "frame_id", "pts_ns", "decision_id",
    "control_sha256", "at_ns", "sha256",
}
TERMINAL_FIELDS = {
    "seq", "begin_seq", "at_ns", "response", "outcome", "send", "sha256",
}
NATIVE_KIND = "vast_qualification_operational_native_domain_v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def sealed(value):
    result = copy.deepcopy(value)
    result.pop("sha256", None)
    result["sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def native_fixture(policy="cpu_only", *, runtime=None):
    """Three actual coordinator phases, four branches each; only frame 2 measured."""
    runtime = coordinator(policy) if runtime is None else runtime
    occurrences = []
    for frame in (1, 2, 3):
        for branch in runtime.branches:
            request = request_message(frame_id=frame, branch=branch)
            response = runtime.handle_message(request["worker_id"], request)
            path = path_message(response, request=request)
            terminal = terminal_message(response, request=request)
            runtime.handle_message(request["worker_id"], path)
            runtime.handle_message(request["worker_id"], terminal)
            state = runtime._states[response["decision_id"]]
            occurrences.append(sealed({
                "schema_version": 1, "artifact_kind": NATIVE_KIND,
                "runtime_decision_seq": state.record["decision_seq"],
                "decision_id": state.record["decision_id"], "measurement": frame == 2,
                "decision_request": request, "accepted_record": state.accepted,
                "path": state.path, "terminal": state.terminal,
                "issued_record_sha256": state.record["sha256"],
                "accepted_record_sha256": state.accepted["sha256"],
            }))
    return runtime, occurrences


def authority(record):
    """Use actual frozen equations, original inverse and native capability binding."""
    accepted = record["accepted_record"]
    projected = project_accepted_decision_v1(
        accepted, canonical_trace_id=accepted["trace_id"],
        publication_decision_seq=accepted["decision_seq"],
        issued_record_sha256=record["issued_record_sha256"],
    )
    reconstructed, issued = reconstruct_original_decision_v1(projected)
    if reconstructed != accepted or issued["sha256"] != record["issued_record_sha256"]:
        raise ValueError("original issued/accepted inverse drift")
    assessment = validate_decision_record(accepted, capability_manifest())
    if not assessment["passed"]:
        raise ValueError("original native capability assessment failed: " + ",".join(assessment["blockers"]))


def native_header(runtime, records):
    descriptor = {"path": "fixtures/authority.v1.json", "size_bytes": 1,
                  "sha256": "5" * 64}
    return sealed({
        "schema_version": 1, "artifact_kind": NATIVE_KIND,
        "record_kind": "header", "digest_algorithm": "sha256",
        "operation_input": descriptor, "run_id": runtime.run_id,
        "context_arm_id": runtime.arm_id, "system": runtime.system,
        "scenario": runtime.scenario, "codec": runtime.codec,
        "policy": runtime.policy, "deadline_ms": runtime.deadline_ms,
        "protocol": {"schema_version": 1, "decision_request": "decision_request",
                     "path": "path_enter", "terminal": "terminal",
                     "source_descriptor": "policy_request_source"},
        "descriptors": {key: descriptor for key in (
            "capability_manifest", "source_plan", "model_authority", "calibration",
            "policy_request_source", "policy_coordinator_source", "execution_code_closure",
        )},
        "initial_state": runtime._initial_policy_state,
        "counts": {"complete_decision_count": len(records),
                   "measurement_decision_count": sum(row["measurement"] for row in records),
                   "excluded_decision_count": sum(not row["measurement"] for row in records),
                   "runtime_feedback_count": 0, "measurement_feedback_count": 0,
                   "excluded_feedback_count": 0},
        "adaptive_history": None,
    })


def active_coordinator(root, policy="cpu_only"):
    baseline = coordinator(policy)
    return type(baseline)(
        run_id=baseline.run_id, arm_id=baseline.arm_id, system=baseline.system,
        scenario=baseline.scenario, codec=baseline.codec, policy=baseline.policy,
        deadline_ms=baseline.deadline_ms, branches=baseline.branches,
        capability_manifest=baseline._capability_manifest,
        calibration=baseline._calibration,
        operational_context={"header": native_header(baseline, []),
                             "output_dir": root / "operational"},
    )


class OperationalRequestDomainTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("publication_operational_request_domain_v1")
        except ModuleNotFoundError as exc:
            if exc.name != "publication_operational_request_domain_v1":
                raise
            self.fail("bounded complete operational evidence feature is not implemented")

    def test_complete_native_occurrences_preserve_all_three_phases_and_original_hashes(self):
        _, originals = native_fixture()
        # These preconditions execute existing production code before the new feature.
        self.assertEqual(len(originals), 12)
        self.assertEqual(sum(row["measurement"] for row in originals), 4)
        for record in originals:
            authority(record)
        api = self.api()
        for original in originals:
            built = api.build_native_occurrence_v1(
                runtime_decision_seq=original["runtime_decision_seq"],
                measurement=original["measurement"],
                decision_request=original["decision_request"],
                accepted_record=original["accepted_record"], path=original["path"],
                terminal=original["terminal"],
                issued_record_sha256=original["issued_record_sha256"],
            )
            self.assertEqual(set(built), NATIVE_FIELDS)
            self.assertEqual(built, original)
            api.validate_native_occurrence_v1(
                built, expected_header=None, original_authority_validator=authority,
            )
            self.assertLessEqual(len(canonical(built)) + 1, 9_216)

    def test_each_policy_keeps_original_values_without_an_extra_issued_object(self):
        api = self.api()
        for policy in ("cpu_only", "gpu_only", "static_hybrid", "heft",
                       "deadline_aware_heft", "queue_aware_edf", "adaptive_weights"):
            with self.subTest(policy=policy):
                _, records = native_fixture(policy)
                for record in records:
                    api.validate_native_occurrence_v1(
                        record, expected_header=None,
                        original_authority_validator=authority,
                    )
                    self.assertEqual(set(record), NATIVE_FIELDS)
                    self.assertNotIn("issued_record", record)
                    self.assertIs(type(record["decision_request"]["stream_id"]), int)
                    self.assertIs(type(record["decision_request"]["arrival_ms"]), float)

    def test_integer_spelling_of_native_binary64_clocks_is_retained_losslessly(self):
        runtime = coordinator("cpu_only")
        request = request_message()
        for key in ("arrival_ms", "decision_time_ms", "feature_observed_timestamp_ms"):
            request[key] = int(request[key])
        response = runtime.handle_message(request["worker_id"], request)
        path = path_message(response, request=request)
        path["timestamp_ms"] = int(path["timestamp_ms"])
        terminal = terminal_message(response, request=request)
        for key in ("terminal_timestamp_ms", "actual_service_ms"):
            terminal[key] = int(terminal[key])
        runtime.handle_message(request["worker_id"], path)
        runtime.handle_message(request["worker_id"], terminal)
        state = runtime._states[response["decision_id"]]
        record = self.api().build_native_occurrence_v1(
            runtime_decision_seq=state.record["decision_seq"], measurement=True,
            decision_request=request, accepted_record=state.accepted,
            path=state.path, terminal=state.terminal,
            issued_record_sha256=state.record["sha256"],
        )
        self.api().validate_native_occurrence_v1(
            record, expected_header=None, original_authority_validator=authority,
        )
        self.assertIs(type(record["terminal"]["actual_service_ms"]), int)
        self.assertIs(type(record["accepted_record"]["native_decision_evidence"]["actual_service_ms"]), float)
        self.assertEqual(record["decision_request"], request)
        self.assertEqual(record["path"], path)
        self.assertEqual(record["terminal"], terminal)

    def test_resealed_request_path_and_terminal_coordinate_substitutions_are_rejected(self):
        _, records = native_fixture()
        api = self.api()
        substitutions = (
            ("decision_request", "worker_id", "foreign-worker-0001"),
            ("decision_request", "transport_pts_ns", 999_999),
            ("decision_request", "arrival_ms", 1.0),
            ("decision_request", "queue_depths", {"cpu": 10, "gpu": 20}),
            ("decision_request", "decision_time_ms", 100_000.0),
            ("decision_request", "feature_observed_timestamp_ms", 100_000.0),
            ("path", "input_frame_key", "foreign:0:source:2:1000"),
            ("path", "implementation_id", "foreign-implementation-0001"),
            ("terminal", "selected_resource", "gpu"),
            ("terminal", "backend", "foreign-backend-0001"),
        )
        for section, field, value in substitutions:
            with self.subTest(section=section, field=field):
                changed = copy.deepcopy(records[0])
                changed[section][field] = value
                changed = sealed(changed)
                with self.assertRaises(ValueError):
                    api.validate_native_occurrence_v1(
                        changed, expected_header=None,
                        original_authority_validator=authority,
                    )

    def test_wrong_original_issued_or_accepted_hash_is_not_repaired(self):
        _, records = native_fixture()
        api = self.api()
        for key in ("issued_record_sha256", "accepted_record_sha256"):
            with self.subTest(key=key):
                changed = copy.deepcopy(records[0])
                changed[key] = "0" * 64
                with self.assertRaises(ValueError):
                    api.validate_native_occurrence_v1(
                        sealed(changed), expected_header=None,
                        original_authority_validator=authority,
                    )

    def test_strict_json_rejects_ambiguous_numbers_duplicate_keys_and_oversized_lines(self):
        api = self.api()
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}',
                    b'{"a":-Infinity}', b'{"a":1', b'[]', b'"scalar"'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    api.strict_json_object_v1(raw, max_bytes=9_216)
        with self.assertRaises(ValueError):
            api.strict_json_object_v1(b'{"a":"' + b"x" * 9_216 + b'"}',
                                      max_bytes=9_216)

    def test_native_record_byte_cap_is_checked_before_authority_callback(self):
        _, records = native_fixture()
        changed = copy.deepcopy(records[0])
        changed["decision_request"]["input_frame_key"] = "x" * 9_216
        calls = []
        with self.assertRaises(ValueError):
            self.api().validate_native_occurrence_v1(
                sealed(changed), expected_header=None,
                original_authority_validator=lambda record: calls.append(record),
            )
        self.assertEqual(calls, [])

    def test_guardian_chain_vectors_keep_short_explicit_fields_and_full_dynamic_values(self):
        begin = {
            "type": "begin", "seq": 1, "request_seq": 1, "connection": 1,
            "local_seq": 1, "binding": 0, "request_id": "request-native-0001",
            "input_key": "dataset:0:source:1:1000", "frame_id": 1,
            "pts_ns": 1000, "decision_id": "decision-native-0001",
            "control_sha256": "1" * 64, "at_ns": 10,
        }
        terminal = {
            "seq": 2, "begin_seq": 1, "at_ns": 20, "response": "2" * 64,
            "outcome": "completed", "send": "sent",
        }
        api = self.api()
        previous = "3" * 64
        for payload, expected_fields, cap in ((begin, BEGIN_FIELDS, 768),
                                              (terminal, TERMINAL_FIELDS, 256)):
            event = api.seal_guardian_event_v1(payload, previous_sha256=previous)
            expected = hashlib.sha256(bytes.fromhex(previous) + canonical(payload)).hexdigest()
            self.assertEqual(event["sha256"], expected)
            self.assertEqual(set(event), expected_fields)
            self.assertLessEqual(len(canonical(event)) + 1, cap)
            api.validate_guardian_event_v1(event, previous_sha256=previous)
            with self.assertRaises(ValueError):
                api.validate_guardian_event_v1(event, previous_sha256="4" * 64)
            previous = event["sha256"]

    def test_guardian_resealed_wrong_shapes_missing_reference_and_nonfinite_time_fail(self):
        api = self.api()
        terminal = {"seq": 2, "begin_seq": 1, "at_ns": 20, "response": None,
                    "outcome": "failed", "send": "closed"}
        for changed in ({**terminal, "begin_seq": 0}, {**terminal, "seq": True},
                        {**terminal, "extra": "unreviewed"},
                        {key: value for key, value in terminal.items() if key != "begin_seq"}):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    api.seal_guardian_event_v1(changed, previous_sha256="3" * 64)
        with self.assertRaises(ValueError):
            api.seal_guardian_event_v1({**terminal, "at_ns": float("inf")},
                                      previous_sha256="3" * 64)

    def test_last_one_based_guardian_terminal_fits_reserved_cap_and_references_earlier_begin(self):
        api = self.api()
        terminal = {
            "seq": 1_000_000, "begin_seq": 999_999,
            "at_ns": (1 << 64) - 1, "response": "f" * 64,
            "outcome": "completed", "send": "failed",
        }
        event = api.seal_guardian_event_v1(terminal, previous_sha256="3" * 64)
        self.assertLessEqual(len(canonical(event)) + 1, 256)
        api.validate_guardian_event_v1(event, previous_sha256="3" * 64)
        for bad in ({**terminal, "begin_seq": 1_000_000},
                    {**terminal, "seq": 1_000_001}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    api.seal_guardian_event_v1(bad, previous_sha256="3" * 64)

    def test_native_stream_roundtrip_has_exact_counts_physical_hash_and_exclusive_creation(self):
        runtime, records = native_fixture()
        header = native_header(runtime, records)
        api = self.api()
        calls = []

        def checked(record):
            calls.append(record["runtime_decision_seq"])
            authority(record)

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "native_operational_requests.v1.jsonl"
            descriptor = api.write_native_domain_v1(
                path, header, iter(records), original_authority_validator=checked,
            )
            self.assertEqual(calls, list(range(1, 13)))
            self.assertEqual(set(descriptor), {"path", "size_bytes", "sha256"})
            self.assertEqual(descriptor["size_bytes"], path.stat().st_size)
            self.assertEqual(descriptor["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(path.read_bytes().splitlines()[0], canonical(header))
            decoded = list(api.iter_native_domain_v1(
                path, expected_descriptor=descriptor,
                original_authority_validator=authority,
            ))
            self.assertEqual(decoded, records)
            with self.assertRaises((ValueError, FileExistsError)):
                api.write_native_domain_v1(
                    path, header, iter(records), original_authority_validator=authority,
                )

    def test_stream_reader_rejects_truncation_descriptor_drift_and_wrong_complete_counts(self):
        runtime, records = native_fixture()
        api = self.api()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "native_operational_requests.v1.jsonl"
            descriptor = api.write_native_domain_v1(
                path, native_header(runtime, records), iter(records),
                original_authority_validator=authority,
            )
            original = path.read_bytes()
            path.write_bytes(original[:-1])
            changed = {**descriptor, "size_bytes": path.stat().st_size,
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            with self.assertRaises(ValueError):
                list(api.iter_native_domain_v1(
                    path, expected_descriptor=changed,
                    original_authority_validator=authority,
                ))
            path.write_bytes(original)
            other = path.with_name("foreign.jsonl")
            other.write_bytes(original)
            with self.assertRaises(ValueError):
                list(api.iter_native_domain_v1(
                    other, expected_descriptor=descriptor,
                    original_authority_validator=authority,
                ))
            with self.assertRaises(ValueError):
                list(api.iter_native_domain_v1(
                    path, expected_descriptor={**descriptor, "sha256": "0" * 64},
                    original_authority_validator=authority,
                ))
            malformed = native_header(runtime, records)
            malformed["counts"]["complete_decision_count"] += 1
            malformed["counts"]["excluded_decision_count"] += 1
            malformed = sealed(malformed)
            with self.assertRaises(ValueError):
                api.write_native_domain_v1(
                    Path(temporary) / "wrong-counts.jsonl", malformed, iter(records),
                    original_authority_validator=authority,
                )

    def test_explicit_coordinator_capture_publishes_separate_complete_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = active_coordinator(root)
            _, records = native_fixture(runtime=active)
            for record in records:
                self.assertEqual(active._states[record["decision_id"]].decision_request,
                                 record["decision_request"])
            measured = records[4]["decision_request"]
            result = active.promote(root / "measurement", canonical_frames={
                measured["input_frame_key"]: {"trace_id": "canonical-measured-0001",
                                             "stream_id": 0, "frame_id": 0},
            })
            self.assertEqual(result["operational_counts"]["complete_decision_count"], 12)
            self.assertEqual(result["operational_counts"]["measurement_decision_count"], 4)
            self.assertEqual(result["operational_counts"]["excluded_decision_count"], 8)
            self.assertEqual(Path(result["operational_domain"]["path"]).parent,
                             (root / "operational").resolve())
            actual = list(self.api().iter_native_domain_v1(
                root / "operational" / "native_operational_requests.v1.jsonl",
                expected_descriptor=result["operational_domain"],
                original_authority_validator=authority,
            ))
            self.assertEqual(actual, records)
            self.assertEqual({path.name for path in (root / "measurement").iterdir()},
                             {"policy_decisions.csv", "publication_policy_decisions.jsonl"})

    def test_raw_request_snapshot_is_independent_and_inactive_capture_is_absent(self):
        inactive, records = native_fixture()
        self.assertTrue(all(state.decision_request is None for state in inactive._states.values()))
        with tempfile.TemporaryDirectory() as temporary:
            active = active_coordinator(Path(temporary))
            request = request_message()
            original = copy.deepcopy(request)
            response = active.handle_message(request["worker_id"], request)
            request["frame_id"] = 999
            request["queue_depths"]["cpu"] = 123
            self.assertEqual(active._states[response["decision_id"]].decision_request, original)

    def test_supported_source_bounds_and_6744_cap_block_before_engine_allocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            active = active_coordinator(Path(temporary))
            invalid = request_message(frame_id=281)
            with self.assertRaises(NativePolicyRuntimeError) as initial:
                active.handle_message(invalid["worker_id"], invalid)
            self.assertEqual(active._states, {})
            self.assertEqual(active._engine._next_decision_seq, 1)
            valid = request_message()
            with self.assertRaises(NativePolicyRuntimeError) as subsequent:
                active.handle_message(valid["worker_id"], valid)
            self.assertEqual(str(initial.exception), str(subsequent.exception))
        with tempfile.TemporaryDirectory() as temporary:
            active = active_coordinator(Path(temporary))
            request = request_message()
            response = active.handle_message(request["worker_id"], request)
            original = active._states[response["decision_id"]]
            active._states = {str(index): original for index in range(6_744)}
            extra = request_message(frame_id=2)
            with self.assertRaises(NativePolicyRuntimeError):
                active.handle_message(extra["worker_id"], extra)
            self.assertEqual(len(active._states), 6_744)
            self.assertEqual(active._next_decision_seq, 2)
            self.assertEqual(active._engine._next_decision_seq, 2)
            with self.assertRaises(NativePolicyRuntimeError):
                active.promote(Path(temporary) / "measurement", canonical_frames={})

    def test_active_adaptive_domain_binds_existing_history_and_all_feedback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = active_coordinator(root, "adaptive_weights")
            _, records = native_fixture(runtime=active)
            measured = records[4]["decision_request"]
            result = active.promote(root / "measurement", canonical_frames={
                measured["input_frame_key"]: {"trace_id": "canonical-measured-0001",
                                             "stream_id": 0, "frame_id": 0},
            })
            actual = list(self.api().iter_native_domain_v1(
                result["operational_domain"]["path"], expected_descriptor=result["operational_domain"],
                original_authority_validator=authority,
            ))
            self.assertEqual(actual, records)
            counts = result["operational_counts"]
            self.assertEqual((counts["runtime_feedback_count"], counts["measurement_feedback_count"],
                              counts["excluded_feedback_count"]), (12, 4, 8))
            native = Path(result["operational_domain"]["path"])
            header = json.loads(native.read_bytes().splitlines()[0])
            history = Path(header["adaptive_history"]["path"])
            self.assertEqual(header["adaptive_history"], {
                "path": str(history), "size_bytes": history.stat().st_size,
                "sha256": hashlib.sha256(history.read_bytes()).hexdigest(),
            })

    def test_failed_operational_publication_preserves_original_file_and_first_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = active_coordinator(root)
            _, records = native_fixture(runtime=active)
            operational = root / "operational" / "native_operational_requests.v1.jsonl"
            operational.parent.mkdir()
            operational.write_bytes(b"earlier-original-evidence\n")
            measured = records[4]["decision_request"]
            with self.assertRaises(FileExistsError) as initial:
                active.promote(root / "measurement", canonical_frames={
                    measured["input_frame_key"]: {"trace_id": "canonical-measured-0001",
                                                 "stream_id": 0, "frame_id": 0},
                })
            self.assertEqual(operational.read_bytes(), b"earlier-original-evidence\n")
            self.assertEqual(list((root / "measurement").iterdir()), [])
            with self.assertRaises(NativePolicyRuntimeError) as subsequent:
                active.promote(root / "measurement", canonical_frames={})
            self.assertIn(str(initial.exception), str(subsequent.exception))


if __name__ == "__main__":
    unittest.main()
