"""Synthetic closed-row/real-file regressions, not scientific experiment evidence."""
from __future__ import annotations
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_canonical_systems_study_plan_v1 import intake_fixture, material_fixture
from canonical_systems_study_plan_v1 import build_study_plan, stream_schedule

DOMAIN = {"clock": "CLOCK_REALTIME", "boot_id": "fixture-boot", "time_namespace": "time:[fixture]"}
SELF_DOMAIN = {"clock": "CLOCK_MONOTONIC", "boot_id": "fixture-boot",
               "time_namespace": "time:[fixture]", "pid": 12}

def arm_fixture(plan, arm, *, latencies=(20, 40, 80, 100)):
    topology, resource = arm["topology"], arm["resource"]
    recipients = {str(s): ({b: f"native-{s}-{b}" for b in plan["branches"]}
                          if topology == "baseline" else {"shared": f"native-{s}-shared"})
                  for s in range(6)}
    closure = {"arm_id": arm["arm_id"], "run_id": arm["arm_id"],
               "plan_sha256": plan["sha256"], "bundle_sha256": plan["bundle_sha256"],
               "final_variant": "global-client", "source_window_closed": True,
               "source_streams_closed": list(range(6)), "infra_errors": [], "close_errors": [],
               "source_clock_domain": DOMAIN, "native_clock_domain": DOMAIN,
               "recipient_bindings": recipients, "drain_deadline_reached": False}
    raw = {"admissions": [], "source_events": [], "native_terminals": [],
           "guardian_events": [], "waits": [], "closure": closure}
    slot = next(r for r in stream_schedule(plan, 0, arm["rate"]) if r["measurement"])
    common = {"run_id": arm["arm_id"], "stream_id": 0,
              "input_frame_key": slot["input_frame_key"],
              "derived_ordinal": slot["derived_ordinal"], "source_cycle": 0,
              "access_unit_pts_ns": slot["access_unit_pts_ns"],
              "payload_sha256": slot["payload_sha256"],
              "planned_schedule_offset_ns": slot["schedule_offset_ns"]}
    for n, kind in enumerate(("source_offered", "source_admitted", "source_ack")):
        raw["source_events"].append(dict(common, type=kind, actual_monotonic_ns=100+n,
                                        source_lateness_ns=5_000_000))
    raw["admissions"].append({"run_id": arm["arm_id"], "stream_id": 0,
        "input_frame_key": slot["input_frame_key"], "source_cycle": 0,
        "access_unit_pts_ns": slot["access_unit_pts_ns"], "payload_sha256": slot["payload_sha256"],
        "payload_size_bytes": slot["payload_size_bytes"],
        "schedule_offset_ns": slot["schedule_offset_ns"], "admission_timestamp_ms": 1000})
    for recipient in recipients["0"].values():
        raw["source_events"].append(dict(common, type="fanout_enqueued", recipient_id=recipient,
                                        actual_monotonic_ns=105))
        raw["source_events"].append(dict(common, type="recipient_delivered", recipient_id=recipient,
                                        actual_monotonic_ns=110))
        raw["source_events"].append(dict(common, type="recipient_received", recipient_id=recipient,
                                        actual_monotonic_ns=120))
    for i, branch in enumerate(plan["branches"]):
        decision = f"decision-{branch}"
        raw["native_terminals"].append({
            "decision_id": decision,
            "decision_request": {"run_id": arm["arm_id"], "input_frame_key": slot["input_frame_key"],
                "stream_id": 0, "frame_id": slot["derived_ordinal"], "branch": branch,
                "transport_pts_ns": slot["transport_pts_ns"]},
            "path": {"selected_resource": resource, "decision_id": decision},
            "terminal": {"terminal_status": "completed", "terminal_timestamp_ms": 1000+latencies[i],
                         "actual_service_ms": 1, "selected_resource": resource}})
        raw["guardian_events"].append({
            "identity": {"run_id": arm["arm_id"], "arm_id": arm["arm_id"],
                         "input_frame_key": slot["input_frame_key"], "stream_id": 0,
                         "frame_id": slot["derived_ordinal"], "transport_pts_ns": slot["transport_pts_ns"],
                         "branch": branch, "resource": resource, "decision_id": decision},
            "begin": {"seq": i*2+1, "input_key": slot["input_frame_key"],
                      "pts_ns": slot["transport_pts_ns"], "decision_id": decision},
            "terminal": {"seq": i*2+2, "begin_seq": i*2+1, "outcome": "completed",
                         "send": "sent", "response": "f"*64}})
    return raw

class CanonicalStudyReducerTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("reduce_canonical_systems_study_v1")
        self.plan = build_study_plan(intake_fixture(), material_fixture())
        self.arm = self.plan["arms"][0]
        self.raw = arm_fixture(self.plan, self.arm)

    def reduce(self, raw=None):
        return self.module.reduce_arm(self.plan, self.arm["arm_id"], raw or self.raw)

    def closed_fixture(self, root):
        def save(name, value, jsonl=False):
            path = root / name
            body = (b"".join((json.dumps(row, separators=(",", ":"))+"\n").encode()
                             for row in value) if jsonl else
                    (json.dumps(value, separators=(",", ":"))+"\n").encode())
            path.write_bytes(body)
            return {"path": str(path), "size_bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest()}
        arms = {}
        for index, arm in enumerate(self.plan["arms"]):
            raw = arm_fixture(self.plan, arm)
            arms[arm["arm_id"]] = {role: save(f"{index}-{role}.json", value) if role == "closure"
                                   else [save(f"{index}-{role}.jsonl", value, True)]
                                   for role, value in raw.items()}
        binding = {"kind": "finite-component-study-closed-inputs", "plan": save("plan.json", self.plan),
                   "plan_sha256": self.plan["sha256"], "bundle_sha256": self.plan["bundle_sha256"],
                   "final_variant": "global-client", "arms": arms}
        return binding, save("binding.json", binding)

    def test_closed_role_descriptors_and_same_reducer_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding, descriptor = self.closed_fixture(root)
            before = len(os.listdir("/proc/self/fd"))
            result = self.module.reduce_closed_study(binding)
            self.assertEqual(result["actual_effect_arms"], 24)
            self.assertEqual(len(result["pairs"]), 12)
            self.assertFalse(result["canonical_study_complete"])
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)
            output = root / "reduction.json"
            command = [sys.executable, "-I", "-B", str(Path(self.module.__file__)),
                       "--binding", descriptor["path"], "--binding-size-bytes", str(descriptor["size_bytes"]),
                       "--binding-sha256", descriptor["sha256"], "--output", str(output),
                       "--deadline-monotonic", str(self.module.time.monotonic()+10)]
            original = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertEqual(original.returncode, 0, original.stderr)
            self.assertEqual(json.loads(output.read_bytes()), result)
            self.assertFalse(json.loads(original.stdout)["canonical_study_complete"])
            collision = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(json.loads(output.read_bytes()), result)
            replaced = root / "rebound-report.json"
            real_write = os.write
            def rebind_report(fd, body):
                written = real_write(fd, body)
                replaced.rename(root / "held-report.json")
                replaced.write_bytes(b"foreign sentinel")
                return written
            with mock.patch.object(self.module.os, "write", side_effect=rebind_report):
                with self.assertRaisesRegex(ValueError, "report.*rebound"):
                    self.module._write_exclusive_report(replaced, b"{}\n", self.module.time.monotonic()+10)
            self.assertEqual(replaced.read_bytes(), b"foreign sentinel")
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_closed_binding_foreign_alias_and_post_read_epoch_drift_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding, _ = self.closed_fixture(Path(temporary))
            bad = copy.deepcopy(binding)
            bad["plan_sha256"] = "0"*64
            with self.assertRaisesRegex(ValueError, "plan"):
                self.module.reduce_closed_study(bad)
            bad = copy.deepcopy(binding)
            arm = self.plan["arms"][0]["arm_id"]
            bad["arms"][arm]["waits"] = bad["arms"][arm]["admissions"]
            with self.assertRaisesRegex(ValueError, "alias"):
                self.module.reduce_closed_study(bad)
            actual_reduce = self.module.reduce_study
            path = Path(binding["arms"][arm]["admissions"][0]["path"])
            def drift(*args, **kwargs):
                result = actual_reduce(*args, **kwargs)
                path.write_bytes(path.read_bytes()+b" ")
                return result
            with mock.patch.object(self.module, "reduce_study", side_effect=drift):
                with self.assertRaisesRegex(ValueError, "epoch"):
                    self.module.reduce_closed_study(binding)
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.module.reduce_closed_study(binding, deadline=0)
        with tempfile.TemporaryDirectory() as temporary:
            binding, _ = self.closed_fixture(Path(temporary))
            actual_reduce = self.module.reduce_study
            def sibling_activity(*args, **kwargs):
                result = actual_reduce(*args, **kwargs)
                # A different owner's /tmp entry changes its metadata, not our directory identity.
                with tempfile.TemporaryDirectory(dir=Path(temporary).parent):
                    pass
                return result
            with mock.patch.object(self.module, "reduce_study", side_effect=sibling_activity):
                result = self.module.reduce_closed_study(binding)
            self.assertEqual(result["actual_effect_arms"], 24)

    def test_full_planned_denominator_not_completed_only(self):
        result = self.reduce()
        expected = sum(r["measurement"] for s in range(6)
                       for r in stream_schedule(self.plan, s, self.arm["rate"]))
        self.assertEqual(result["frames"]["N_planned"], expected)
        self.assertEqual(result["frames"]["N_completed"], 1)
        self.assertEqual(result["frames"]["N_on_time"], 1)
        self.assertEqual(result["Y100_frame"], 1/expected)
        self.assertEqual(result["frames"]["N_not_offered"], expected-1)
        self.assertEqual(result["branches"]["N_planned"], 4*expected)
        self.assertEqual(result["source_lateness_ns"]["p50"], 5_000_000)
        self.assertTrue(result["raw_reconciliation_complete"])
        self.assertFalse(result["canonical_study_complete"])
        self.assertFalse(result["full_run_eligible"])

    def test_critical_branch_and_latency_tail_without_zero_losses(self):
        raw = arm_fixture(self.plan, self.arm, latencies=(1, 2, 3, 100.001))
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_on_time"], 0)
        self.assertAlmostEqual(result["completed_frame_latency_ms"]["p50"], 100.001)
        self.assertEqual(result["completed_frame_latency_ms"]["n"], 1)
        self.assertEqual(result["branches"]["N_on_time"], 3)
        empty = copy.deepcopy(self.raw)
        for field in ("source_events", "admissions", "native_terminals", "guardian_events"):
            empty[field] = []
        result = self.reduce(empty)
        self.assertEqual(result["completed_frame_latency_ms"]["n"], 0)
        self.assertIsNone(result["completed_frame_latency_ms"]["p50"])
        self.assertEqual(result["Y100_frame"], 0)

    def test_admitted_before_ack_failed_delivery_key_survives(self):
        raw = copy.deepcopy(self.raw)
        # Central durable acceptance survives even when source never receives its ACK.
        raw["source_events"] = raw["source_events"][:1]
        raw["native_terminals"] = []
        raw["guardian_events"] = []
        raw["closure"]["infra_errors"] = ["actual pipe failure"]
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_admitted"], 1)
        self.assertEqual(result["frames"]["N_delivery_failed"], 1)
        self.assertEqual(result["frames"]["N_completed"], 0)
        self.assertFalse(result["raw_reconciliation_complete"])
        self.assertIn(self.raw["admissions"][0]["input_frame_key"], result["admitted_keys"])

    def test_enqueued_and_pipe_write_are_not_validated_receive(self):
        raw = copy.deepcopy(self.raw)
        raw["source_events"] = [r for r in raw["source_events"] if r["type"] != "recipient_received"]
        raw["native_terminals"] = []
        raw["guardian_events"] = []
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_delivery_failed"], 1)
        self.assertFalse(result["raw_reconciliation_complete"])

    def test_durable_parent_acceptance_missing_does_not_admit(self):
        raw = copy.deepcopy(self.raw)
        raw["admissions"] = []
        with self.assertRaisesRegex(ValueError, "durable admission"):
            self.reduce(raw)

    def test_partial_frame_and_missing_guardian_never_complete(self):
        raw = copy.deepcopy(self.raw)
        raw["native_terminals"].pop()
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_completed"], 0)
        self.assertEqual(result["branches"]["N_unknown"], 1)
        self.assertFalse(result["raw_reconciliation_complete"])
        raw = copy.deepcopy(self.raw)
        raw["guardian_events"].pop()
        with self.assertRaisesRegex(ValueError, "guardian"):
            self.reduce(raw)

    def test_partial_baseline_delivery_keeps_actual_completed_branches(self):
        raw = copy.deepcopy(self.raw)
        self.assertEqual(self.arm["topology"], "baseline")
        branch = self.plan["branches"][-1]
        recipient = raw["closure"]["recipient_bindings"]["0"][branch]
        raw["source_events"] = [r for r in raw["source_events"]
                                if not (r["type"] == "recipient_received" and r["recipient_id"] == recipient)]
        raw["native_terminals"].pop()
        raw["guardian_events"].pop()
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_completed"], 0)
        self.assertEqual(result["frames"]["N_delivery_failed"], 1)
        self.assertEqual(result["branches"]["N_completed"], 3)
        self.assertEqual(result["branches"]["N_delivery_failed"], 1)
        self.assertEqual(result["completed_branch_latency_ms"]["n"], 3)
        self.assertFalse(result["raw_reconciliation_complete"])

    def test_foreign_key_duplicate_payload_resource_and_bundle_drift_refuse(self):
        changes = (
            lambda r: r["source_events"].append(copy.deepcopy(r["source_events"][0])),
            lambda r: r["source_events"][0].update(input_frame_key="foreign"),
            lambda r: r["source_events"][0].update(payload_sha256="0"*64),
            lambda r: r["native_terminals"][0]["path"].update(selected_resource="foreign"),
            lambda r: r["closure"].update(bundle_sha256="0"*64),
            lambda r: r["native_terminals"].append(copy.deepcopy(r["native_terminals"][0])),
        )
        for change in changes:
            with self.subTest(change=change):
                raw = copy.deepcopy(self.raw)
                change(raw)
                with self.assertRaises(ValueError):
                    self.reduce(raw)

    def test_clock_domain_mismatch_never_subtracts(self):
        raw = copy.deepcopy(self.raw)
        raw["closure"]["native_clock_domain"] = dict(DOMAIN, time_namespace="foreign")
        with self.assertRaisesRegex(ValueError, "clock domain"):
            self.reduce(raw)

    def test_censor_and_drop_require_original_runtime_ledger_and_drain(self):
        raw = copy.deepcopy(self.raw)
        original = raw["admissions"][0]
        raw["native_terminals"] = []
        raw["guardian_events"] = []
        raw["closure"].update(window_start_timestamp_ms=900, window_end_timestamp_ms=1100,
            drain_end_timestamp_ms=1200, drain_deadline_reached=True,
            lifecycle_statuses={"native-0": ["ADMISSION_STOPPED", "CENSORED"]})
        row = dict(original, frame_id=next(r for r in stream_schedule(self.plan, 0, self.arm["rate"])
                       if r["measurement"])["derived_ordinal"], ingress_timestamp_ms=1000,
            window_start_timestamp_ms=900, window_end_timestamp_ms=1100, drain_end_timestamp_ms=1200,
            terminal_status="censored", terminal_timestamp_ms=1200,
            terminal_provenance="explicit_censoring_at_drain_end", terminal_reason="no_complete_join_at_drain_end")
        raw["closure"]["runtime_ledger"] = [row]
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_censored"], 1)
        self.assertEqual(result["branches"]["N_unknown"], 4)
        self.assertFalse(result["raw_reconciliation_complete"])
        row["terminal_provenance"] = "constructed_from_EOF"
        with self.assertRaisesRegex(ValueError, "runtime censor"):
            self.reduce(raw)
        row.update(terminal_status="drop", terminal_timestamp_ms=1150,
                   terminal_provenance="native_drop_event", terminal_reason="native_policy_drop")
        raw["closure"]["lifecycle_statuses"] = {"native-0": ["ADMISSION_STOPPED", "DRAINED"]}
        self.assertEqual(self.reduce(raw)["frames"]["N_controlled_dropped"], 1)
        row["terminal_provenance"] = "runtime_contract_test_drop_event"
        with self.assertRaisesRegex(ValueError, "runtime drop"):
            self.reduce(raw)

    def test_actual_native_queue_drop_reconciles_closed_negative_frame_and_branch(self):
        raw = copy.deepcopy(self.raw)
        admission = raw["admissions"][0]
        admission["admission_id"] = "original-admission-1"
        branch = self.plan["branches"][0]
        native = raw["native_terminals"].pop(0)
        raw["guardian_events"].pop(0)
        key, frame = admission["input_frame_key"], native["decision_request"]["frame_id"]
        reason = "native_pre_detector_queue_full_drop_newest"
        detector, backend = "synthetic-frozen-proxy;model_sha256="+"a"*64, "openvino-dlstreamer:synthetic-factory"
        terminal = {"run_id": self.arm["arm_id"], "trace_id": "original-trace-1",
                    "input_frame_key": key, "stream_id": 0, "frame_id": frame, "branch_id": branch,
                    "terminal_status": "drop", "terminal_timestamp_ms": 1150, "objects": 0,
                    "detector": detector, "backend": backend, "terminal_reason": reason,
                    "runtime_protocol_version": 3, "event_provenance": "native_runtime_event", "telemetry_source": "native"}
        event = {"protocol_version": 3, "run_id": self.arm["arm_id"], "trace_id": "original-trace-1",
                 "input_frame_key": key, "stream_id": 0, "frame_id": frame, "branch_id": branch,
                 "event_kind": "branch_drop", "admission_id": admission["admission_id"],
                 "payload_sha256": admission["payload_sha256"], "timestamp_ms": 1150,
                 "terminal_reason": reason, "objects": 0, "detector": detector, "backend": backend}
        raw["native_terminals"].append({"branch_terminal": terminal, "original_event": event,
                                        "resource": self.arm["resource"]})
        raw["closure"].update(window_start_timestamp_ms=900, window_end_timestamp_ms=1100,
            drain_end_timestamp_ms=1200, lifecycle_statuses={"native-0": ["ADMISSION_STOPPED", "DRAINED"]},
            native_drop_bindings={b: {"detector": detector, "backend": backend} for b in self.plan["branches"]},
            runtime_frame_terminals=[{"admission_id": admission["admission_id"], "input_frame_key": key,
                "stream_id": 0, "frame_id": frame, "terminal_status": "drop", "terminal_timestamp_ms": 1150,
                "terminal_reason": reason, "terminal_event_provenance": "native_drop_event", "terminal_telemetry_source": "native"}],
            runtime_ledger=[dict(admission, frame_id=frame, ingress_timestamp_ms=1000,
                window_start_timestamp_ms=900, window_end_timestamp_ms=1100, drain_end_timestamp_ms=1200,
                terminal_status="drop", terminal_timestamp_ms=1150, terminal_provenance="native_drop_event",
                terminal_reason=reason)])
        result = self.reduce(raw)
        self.assertEqual(result["frames"]["N_controlled_dropped"], 1)
        self.assertEqual(result["branches"]["N_controlled_dropped"], 1)
        self.assertEqual(result["branches"]["N_completed"], 3)
        self.assertEqual(result["branches"]["N_unknown"], 0)
        self.assertEqual(result["per_branch"][branch]["N_controlled_dropped"], 1)
        self.assertEqual(result["Y100_frame"], 0)
        self.assertTrue(result["raw_reconciliation_complete"])
        raws = {a["arm_id"]: arm_fixture(self.plan, a) for a in self.plan["arms"]}
        raws[self.arm["arm_id"]] = raw
        self.assertTrue(self.module.reduce_study(self.plan, raws, "global-client")["raw_effect_matrix_complete"])
        alternate = copy.deepcopy(raw)
        reason2 = "native_postdecode_preprocess_queue_full_drop_newest"
        for container in (alternate["native_terminals"][-1]["branch_terminal"],
                          alternate["native_terminals"][-1]["original_event"],
                          alternate["closure"]["runtime_frame_terminals"][0], alternate["closure"]["runtime_ledger"][0]):
            container["terminal_reason"] = reason2
        self.assertTrue(self.reduce(alternate)["raw_reconciliation_complete"])
        for field, value in (("terminal_reason", "constructed_from_EOF"), ("objects", 1),
                             ("detector", "foreign-model"), ("backend", "foreign-backend")):
            bad = copy.deepcopy(raw)
            bad["native_terminals"][-1]["branch_terminal"][field] = value
            bad["native_terminals"][-1]["original_event"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.reduce(bad)
        for field in ("admission_id", "payload_sha256"):
            bad = copy.deepcopy(raw)
            bad["native_terminals"][-1]["original_event"][field] = "foreign"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.reduce(bad)
        bad = copy.deepcopy(raw)
        bad["closure"]["runtime_ledger"][0]["terminal_status"] = "completed"
        bad["closure"]["runtime_ledger"][0]["terminal_provenance"] = "native_completion_event"
        with self.assertRaises(ValueError):
            self.reduce(bad)
        bad = copy.deepcopy(raw)
        bad["native_terminals"].pop()
        self.assertFalse(self.reduce(bad)["raw_reconciliation_complete"])

    def test_wait_self_domains_and_worker_labels_no_constructed_queue(self):
        raw = copy.deepcopy(self.raw)
        raw["waits"] = [
            {"kind": "native_client", "request_id": "x", "clock_domain": SELF_DOMAIN,
             "attempt_ns": 10, "acquired_ns": 20, "reply_ns": 30, "released_ns": 40,
             "outcome": "completed"},
            {"kind": "worker", "request_id": "x", "clock_domain": dict(SELF_DOMAIN, pid=99),
             "received_ns": 12, "inference_started_ns": 15, "inference_finished_ns": 25,
             "completed_ns": 28},
            {"kind": "bridge_route", "request_id": "y", "clock_domain": SELF_DOMAIN,
             "attempt_ns": 10, "acquired_ns": None, "reply_ns": None,
             "released_ns": 20, "outcome": "failed"}]
        result = self.reduce(raw)["waits"]
        self.assertEqual(result["native_client"]["wait_ns"]["p50"], 10)
        self.assertEqual(result["native_client"]["residence_ns"]["p50"], 30)
        self.assertEqual(result["native_client"]["median_wait_fraction"], 1/3)
        self.assertEqual(result["bridge_route"]["unknown"], 1)
        self.assertEqual(result["worker"]["backend_interval_ns"]["p50"], 10)
        self.assertEqual(result["worker"]["received_label"], "accepted/verified after sealed-memfd check")
        self.assertEqual(result["queue_wait"], "unknown")

    def test_existing_worker_wire_self_intervals_keep_unknown_namespace(self):
        raw = copy.deepcopy(self.raw)
        raw["waits"] = [{"kind": "worker", "request_id": "actual-protocol-shaped-id",
            "worker_identity": {"worker_id": "worker-vehicle_type-cpu", "capability_sha256": "a"*64},
            "clock_domain": {"clock": "CLOCK_MONOTONIC", "boot_id": None,
                             "time_namespace": None, "pid": None},
            "received_ns": 10, "inference_started_ns": 15,
            "inference_finished_ns": 25, "completed_ns": 30}]
        result = self.reduce(raw)["waits"]
        self.assertEqual(result["worker"]["backend_interval_ns"]["p50"], 10)
        self.assertTrue(result["worker"]["namespace_identity_unknown"])
        self.assertFalse(result["cross_process_monotonic_subtraction"])
        raw["waits"][0].pop("worker_identity")
        with self.assertRaisesRegex(ValueError, "worker identity"):
            self.reduce(raw)

    def test_whole24_and12_pairs_pilots_never_substitute(self):
        raws = {a["arm_id"]: arm_fixture(self.plan, a) for a in self.plan["arms"]}
        result = self.module.reduce_study(self.plan, raws, "global-client")
        self.assertTrue(result["raw_effect_matrix_complete"])
        self.assertEqual(len(result["pairs"]), 12)
        self.assertEqual(result["actual_effect_arms"], 24)
        self.assertFalse(result["canonical_study_complete"])
        pair = self.plan["pairs"][0]
        shared = next(a for a in self.plan["arms"]
                      if a["pair_id"] == pair["pair_id"] and a["topology"] == "shared")
        negative = copy.deepcopy(raws)
        negative[shared["arm_id"]] = arm_fixture(self.plan, shared, latencies=(200, 200, 200, 200))
        effect = self.module.reduce_study(self.plan, negative, "global-client")["pairs"][0]
        self.assertLess(effect["Y100_shared_minus_baseline"], 0)
        self.assertEqual(effect["completed_frame_quantile_delta_ms"]["p50"], 100)
        self.assertEqual(effect["common_completed_latency_delta_ms"]["p50"], 100)
        missing = dict(raws)
        missing.pop(self.plan["arms"][0]["arm_id"])
        missing[self.plan["pilots"]["initial"][0]["arm_id"]] = self.raw
        with self.assertRaisesRegex(ValueError, "24 effect"):
            self.module.reduce_study(self.plan, missing, "global-client")
        changed = copy.deepcopy(raws)
        changed[self.plan["arms"][0]["arm_id"]]["closure"]["final_variant"] = "branch-channel"
        with self.assertRaisesRegex(ValueError, "variant"):
            self.module.reduce_study(self.plan, changed, "global-client")

    def test_nearest_rank_small_population_and_undefined(self):
        self.assertEqual(self.module.distribution([1, 2, 100, 4])["p50"], 2)
        self.assertEqual(self.module.distribution([1, 2, 100, 4])["p95"], 100)
        self.assertIsNone(self.module.distribution([])["p99"])
        with self.assertRaises(ValueError):
            self.module.distribution([float("nan")])

    def test_per_branch_and_recipient_populations_are_separate(self):
        result = self.reduce()
        for branch, latency in zip(self.plan["branches"], (20, 40, 80, 100)):
            self.assertEqual(result["per_branch"][branch]["N_completed"], 1)
            self.assertEqual(result["per_branch"][branch]["latency_ms"]["p50"], latency)
        self.assertEqual(result["per_stream"]["0"]["N_completed"], 1)
        self.assertEqual(result["per_stream"]["1"]["N_completed"], 0)
        for recipient in self.raw["closure"]["recipient_bindings"]["0"].values():
            self.assertEqual(result["delivery"][recipient]["enqueued"], 1)
            self.assertEqual(result["delivery"][recipient]["validated_received"], 1)

    def test_unadmitted_guardian_and_warmup_delivery_fault_refuse_or_fail(self):
        raw = copy.deepcopy(self.raw)
        raw["source_events"] = []
        raw["admissions"] = []
        raw["native_terminals"] = []
        with self.assertRaisesRegex(ValueError, "guardian"):
            self.reduce(raw)
        warm = next(r for r in stream_schedule(self.plan, 0, self.arm["rate"])
                    if r["planned"] and not r["measurement"])
        raw = copy.deepcopy(self.raw)
        original = raw["admissions"][0]
        early = dict(original, input_frame_key=warm["input_frame_key"],
                     access_unit_pts_ns=warm["access_unit_pts_ns"], payload_sha256=warm["payload_sha256"],
                     schedule_offset_ns=warm["schedule_offset_ns"])
        raw["admissions"].append(early)
        for kind in ("source_offered", "source_admitted"):
            raw["source_events"].append({"type": kind, "run_id": original["run_id"], "stream_id": 0,
                "input_frame_key": warm["input_frame_key"], "derived_ordinal": warm["derived_ordinal"],
                "source_cycle": 0, "access_unit_pts_ns": warm["access_unit_pts_ns"],
                "payload_sha256": warm["payload_sha256"],
                "planned_schedule_offset_ns": warm["schedule_offset_ns"], "actual_monotonic_ns": 90})
        self.assertFalse(self.reduce(raw)["raw_reconciliation_complete"])

    def test_actual_short_read_zero_progress_and_continuous_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            body = b'{"x":1}\n'
            path.write_bytes(body)
            descriptor = {"path": str(path), "size_bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest()}
            actual = os.pread
            calls = []
            def zero(fd, size, offset):
                calls.append(offset)
                return actual(fd, 2, offset) if len(calls) == 1 else b""
            with mock.patch.object(self.module.os, "pread", side_effect=zero):
                with self.assertRaisesRegex(ValueError, "EOF"):
                    self.module.read_closed_rows(descriptor)
            self.assertEqual(calls, [0, 2])
            calls.clear()
            clock = [99]
            def advance(fd, size, offset):
                calls.append(offset)
                fragment = actual(fd, 2, offset)
                clock[0] = 101
                return fragment
            with mock.patch.object(self.module.time, "monotonic", side_effect=lambda: clock[0]), \
                 mock.patch.object(self.module.os, "pread", side_effect=advance):
                with self.assertRaisesRegex(ValueError, "deadline"):
                    self.module.read_closed_rows(descriptor, deadline=100)
            self.assertEqual(calls, [0])

    def test_real_raw_holder_primary_and_close_errors_retire_all_fds(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            body = b'{"x":1}\n'
            path.write_bytes(body)
            descriptor = {"path": str(path), "size_bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest()}
            actual = os.close
            before = len(os.listdir("/proc/self/fd"))
            calls = []
            def close_fault(fd):
                actual(fd)
                calls.append(fd)
                if len(calls) == 1:
                    raise OSError("injected post-close retirement error")
            with mock.patch.object(self.module.os, "close", side_effect=close_fault):
                with self.assertRaisesRegex(ValueError, "SHA256") as failed:
                    self.module.read_closed_rows(dict(descriptor, sha256="0"*64))
            self.assertEqual(len(calls), len(path.parts))
            self.assertTrue(any("close failures" in n for n in failed.exception.__notes__))
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)
            calls.clear()
            with mock.patch.object(self.module.os, "close", side_effect=close_fault):
                with self.assertRaisesRegex(ValueError, "FD close failure"):
                    self.module.read_closed_rows(descriptor)
            self.assertEqual(len(calls), len(path.parts))
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)
            os.link(path, Path(temporary) / "alias")
            with self.assertRaisesRegex(ValueError, "alias"):
                self.module.read_closed_rows(descriptor)

    def test_real_closed_file_hash_epochs_short_reads_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            body = b'{"value":1}\n{"value":2}\n'
            path.write_bytes(body)
            descriptor = {"path": str(path), "size_bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest()}
            before = len(os.listdir("/proc/self/fd"))
            self.assertEqual(self.module.read_closed_rows(descriptor), [{"value": 1}, {"value": 2}])
            actual = os.pread
            def short(fd, size, offset):
                return actual(fd, min(3, size), offset)
            with mock.patch.object(self.module.os, "pread", side_effect=short):
                self.assertEqual(self.module.read_closed_rows(descriptor), [{"value": 1}, {"value": 2}])
            bad = dict(descriptor, sha256="0"*64)
            with self.assertRaises(ValueError):
                self.module.read_closed_rows(bad)
            with self.assertRaises(ValueError):
                self.module.read_closed_rows(descriptor, max_bytes=2)
            path.write_bytes(b'{"x":1,"x":2}\n')
            duplicate = dict(descriptor, size_bytes=path.stat().st_size,
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, "duplicate"):
                self.module.read_closed_rows(duplicate)
            self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_real_held_file_growth_rebind_symlink_and_deadline_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.jsonl"
            body = b'{"x":1}\n'
            path.write_bytes(body)
            desc = {"path": str(path), "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            actual = os.pread
            done = False
            def mutate(fd, size, offset):
                nonlocal done
                part = actual(fd, size, offset)
                if not done:
                    done = True
                    path.write_bytes(body + b" ")
                return part
            with mock.patch.object(self.module.os, "pread", side_effect=mutate):
                with self.assertRaises(ValueError):
                    self.module.read_closed_rows(desc)
            path.write_bytes(body)
            done = False
            def rebind(fd, size, offset):
                nonlocal done
                fragment = actual(fd, size, offset)
                if not done:
                    done = True
                    path.rename(Path(temporary) / "original")
                    path.write_bytes(body)
                return fragment
            with mock.patch.object(self.module.os, "pread", side_effect=rebind):
                with self.assertRaisesRegex(ValueError, "epoch"):
                    self.module.read_closed_rows(desc)
            link = Path(temporary) / "link"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                self.module.read_closed_rows(dict(desc, path=str(link)))
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.module.read_closed_rows(desc, deadline=0)

if __name__ == "__main__":
    unittest.main()

