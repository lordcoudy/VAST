"""Synthetic regressions for the descriptive service profile/latency model; not experiment evidence."""
from __future__ import annotations

import contextlib
import copy
import gzip
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from test_canonical_systems_study_plan_v1 import intake_fixture, material_fixture
from test_reduce_canonical_systems_study_v1 import arm_fixture
from canonical_systems_study_plan_v1 import CLOCK_DOMAIN_LABEL, build_study_plan, stream_schedule

LATENCIES = (20, 40, 80, 100)
NATIVE_DOMAIN = {"clock": "CLOCK_MONOTONIC", "boot_id": "fixture-boot", "time_namespace": CLOCK_DOMAIN_LABEL, "pid": 42}
BRIDGE_DOMAIN = dict(NATIVE_DOMAIN, pid=43)
WORKER_DOMAIN = dict(NATIVE_DOMAIN, pid=44)
MS = 1_000_000


def augment(plan, arm, raw):
    """Add path entry and native/bridge/worker wait rows whose 7 components sum to each latency."""
    raw = copy.deepcopy(raw)
    for index, record in enumerate(raw["native_terminals"]):
        request = record["decision_request"]
        latency = LATENCIES[index]
        record["path"]["timestamp_ms"] = 1005
        request_id = f"{arm['arm_id']}-{request['branch']}"
        attempt = 10_000 * MS + index * 1000 * MS
        acquired = attempt + MS // 2                  # native_wait 0.5 ms
        b_attempt = acquired + MS                     # bridge_pre 1 ms
        b_acquired = b_attempt + MS                   # route_wait 1 ms
        released = attempt + (latency - 7) * MS       # probe_pre 2 ms, prefix 5 ms
        b_released = released - MS // 2               # bridge_post 0.5 ms
        common = {"request_id": request_id}
        raw["waits"].append(dict(common, kind="native_client", clock_domain=NATIVE_DOMAIN,
                                 attempt_ns=attempt, acquired_ns=acquired, reply_ns=released, released_ns=released,
                                 run_id=request["run_id"], input_frame_key=request["input_frame_key"],
                                 branch=request["branch"], stream_id=request["stream_id"], frame_id=request["frame_id"],
                                 resource=arm["resource"]))
        raw["waits"].append(dict(common, kind="bridge_route", clock_domain=BRIDGE_DOMAIN, attempt_ns=b_attempt,
                                 acquired_ns=b_acquired, reply_ns=b_released, released_ns=b_released))
        raw["waits"].append(dict(common, kind="worker", clock_domain=WORKER_DOMAIN,
                                 received_ns=b_acquired, inference_started_ns=b_acquired + MS,
                                 inference_finished_ns=b_acquired + 2 * MS, completed_ns=b_released))
    return raw


def save(path, value, jsonl=False):
    body = (b"".join((json.dumps(row, separators=(",", ":")) + "\n").encode() for row in value) if jsonl
            else (json.dumps(value, separators=(",", ":")) + "\n").encode())
    path.write_bytes(body)
    return {"path": str(path), "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


class ServiceProfileModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = importlib.import_module("service_profile_latency_model_v1")
        cls.reducer = importlib.import_module("reduce_canonical_systems_study_v1")
        cls.plan = build_study_plan(intake_fixture(), material_fixture())

    def raw(self, arm=None):
        arm = arm or self.plan["arms"][0]
        return augment(self.plan, arm, arm_fixture(self.plan, arm, latencies=LATENCIES))

    def closed_fixture(self, root, *, drop_arm=False):
        arms = {}
        for index, arm in enumerate(self.plan["arms"]):
            raw = self.raw(arm)
            arms[arm["arm_id"]] = {role: save(root / f"{index}-{role}.json", value) if role == "closure"
                                   else [save(root / f"{index}-{role}.jsonl", value, True)]
                                   for role, value in raw.items()}
        binding = {"kind": "finite-component-study-closed-inputs", "plan": save(root / "plan.json", self.plan),
                   "plan_sha256": self.plan["sha256"], "bundle_sha256": self.plan["bundle_sha256"],
                   "final_variant": "global-client", "arms": arms}
        reduction = self.reducer.reduce_closed_study(binding)
        if drop_arm:
            binding["arms"].pop(self.plan["arms"][0]["arm_id"])
        descriptor = save(root / "binding.json", binding)
        archive_body = gzip.compress(json.dumps({"binding": descriptor, "reduction": reduction}).encode(), mtime=0)
        archive = root / "study-results.json.gz"
        archive.write_bytes(archive_body)
        pins = {"binding": {"size_bytes": descriptor["size_bytes"], "sha256": descriptor["sha256"]},
                "archive": {"size_bytes": len(archive_body), "sha256": hashlib.sha256(archive_body).hexdigest()}}
        return binding, descriptor, archive, pins

    def run_model(self, descriptor, archive, pins, *, deadline=None, replicas=2):
        return self.m.run_model(descriptor, archive, pins, deadline=deadline or time.monotonic() + 600,
                                analysis_deadline_seconds=600, source_commit="a" * 40, replicas=replicas)

    # ---------------------------------------------------------------- 1.1 / 1.2 loader and archive

    def test_success_reports_every_descriptor_and_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding, descriptor, archive, pins = self.closed_fixture(Path(temporary))
            report = self.run_model(descriptor, archive, pins)
            self.assertEqual(len(report["inputs"]["closed_input_descriptors"]), 1 + 24 * 6)
            self.assertEqual(report["inputs"]["closed_input_descriptors"][0], binding["plan"])
            self.assertNotIn(descriptor, report["inputs"]["closed_input_descriptors"])
            self.assertEqual(report["inputs"]["binding"], descriptor)
            self.assertTrue(report["new_descriptive_read_not_rereduction"])
            self.assertEqual(len(report["comparisons"]), 24 + 16 + 24)
            self.assertNotIn("artifact_kind", report)
            for flag in self.m.ELIGIBILITY:
                self.assertIs(report[flag], False)

    def test_pin_symlink_arm_count_drift_and_deadline_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, descriptor, archive, pins = self.closed_fixture(root)
            bad = copy.deepcopy(pins)
            bad["binding"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "pinned study binding"):
                self.run_model(descriptor, archive, bad)
            bad = copy.deepcopy(pins)
            bad["archive"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA256"):
                self.run_model(descriptor, archive, bad)
            link = root / "binding-link.json"
            link.symlink_to(descriptor["path"])
            with self.assertRaisesRegex(ValueError, "raw"):
                self.run_model(dict(descriptor, path=str(link)), archive, pins)
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.run_model(descriptor, archive, pins, deadline=time.monotonic() - 1)
            path = Path(json.loads(Path(descriptor["path"]).read_bytes())["arms"][self.plan["arms"][0]["arm_id"]]
                        ["admissions"][0]["path"])
            actual = self.m.reduce_arm
            drifted = []

            def drift(*args, **kwargs):
                result = actual(*args, **kwargs)
                if not drifted:
                    os.utime(path, ns=(1, 1))
                    drifted.append(True)
                return result
            with mock.patch.object(self.m, "reduce_arm", side_effect=drift):
                with self.assertRaisesRegex(ValueError, "epoch"):
                    self.run_model(descriptor, archive, pins)
        with tempfile.TemporaryDirectory() as temporary:
            _, descriptor, archive, pins = self.closed_fixture(Path(temporary), drop_arm=True)
            with self.assertRaisesRegex(ValueError, "24 effect arms"):
                self.run_model(descriptor, archive, pins)

    def test_archive_arm_binding_and_descriptor_mismatch_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, descriptor, archive, pins = self.closed_fixture(root)
            original = json.loads(gzip.decompress(archive.read_bytes()))

            def rewrite(mutate):
                value = copy.deepcopy(original)
                mutate(value)
                body = gzip.compress(json.dumps(value).encode(), mtime=0)
                archive.write_bytes(body)
                return dict(pins, archive={"size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            arm = self.plan["arms"][3]["arm_id"]
            with self.assertRaisesRegex(ValueError, "differs from archive"):
                self.run_model(descriptor, archive, rewrite(lambda v: v["reduction"]["arms"][arm].update(Y100_frame=0.5)))
            with self.assertRaisesRegex(ValueError, "archive binding"):
                self.run_model(descriptor, archive, rewrite(lambda v: v["binding"].update(size_bytes=1)))
            with self.assertRaisesRegex(ValueError, "closed_input_descriptors"):
                self.run_model(descriptor, archive, rewrite(lambda v: v["reduction"]["closed_input_descriptors"].pop()))

    # ---------------------------------------------------------------- 2.1 profile

    def profile(self, raw, arm=None):
        return self.m.arm_profile(self.plan, arm or self.plan["arms"][0], raw)

    def test_full_join_components_sum_and_replay(self):
        raw = self.raw()
        profile, pools, drops = self.profile(raw)
        self.assertEqual(profile["counts"]["measured_completed"], 4)
        for index, branch in enumerate(self.plan["branches"]):
            components = profile["per_branch"][branch]["components"]
            self.assertEqual({c: v["unknown"] for c, v in components.items()}, {c: 0 for c in self.m.COMPONENTS})
            replay = sum(components[c]["p50"] for c in self.m.COMPONENTS)
            self.assertAlmostEqual(replay, LATENCIES[index], delta=self.m.SUM_TOLERANCE_MS)
            self.assertAlmostEqual(components["prefix"]["p50"], 5)
            self.assertAlmostEqual(components["probe_pre"]["p50"], 2)
            self.assertAlmostEqual(components["bridge_pre"]["p50"], 1)
            self.assertEqual(profile["per_branch"][branch]["worker_unknown"], 0)
            self.assertEqual(profile["per_branch"][branch]["tuple_pool_n"], 1)
        self.assertEqual(drops, {r: 0 for r in self.m.DROP_REASONS})

    def test_missing_joins_increase_unknown(self):
        raw = self.raw()
        branch = self.plan["branches"][0]
        native = next(r for r in raw["waits"] if r["kind"] == "native_client" and r["branch"] == branch)
        raw["waits"] = [r for r in raw["waits"] if not (r["kind"] in ("bridge_route", "worker")
                                                        and r["request_id"] == native["request_id"])]
        profile, pools, _ = self.profile(raw)
        item = profile["per_branch"][branch]
        for component in ("bridge_pre", "route_wait", "route_hold", "bridge_post"):
            self.assertEqual(item["components"][component]["unknown"], 1)
            self.assertEqual(item["components"][component]["n"], 0)
        self.assertEqual(item["components"]["prefix"]["n"], 1)
        self.assertEqual(item["worker_unknown"], 1)
        self.assertEqual(pools["tuples"][branch], [])

    def test_duplicate_negative_identity_and_sum_refuse(self):
        raw = self.raw()
        raw["waits"].append(copy.deepcopy(next(r for r in raw["waits"] if r["kind"] == "bridge_route")))
        with self.assertRaisesRegex(ValueError, "duplicate request_id"):
            self.profile(raw)
        raw = self.raw()
        bridge = next(r for r in raw["waits"] if r["kind"] == "bridge_route")
        bridge["released_ns"] = bridge["reply_ns"] = bridge["released_ns"] + 2 * MS   # after native release
        with self.assertRaisesRegex(ValueError, "negative component: bridge_post"):
            self.profile(raw)
        raw = self.raw()
        next(r for r in raw["waits"] if r["kind"] == "native_client")["frame_id"] = 999
        with self.assertRaisesRegex(ValueError, "identity mismatch: frame_id"):
            self.profile(raw)
        with mock.patch.object(self.m, "SUM_TOLERANCE_MS", -1.0):
            with self.assertRaisesRegex(ValueError, "component sum"):
                self.profile(self.raw())

    def test_foreign_clock_domain_leaves_cross_process_components_unknown(self):
        for change in ({"boot_id": "other-boot"}, {"time_namespace": "timens-offsets:monotonic=5,0;boottime=0,0"}):
            raw = self.raw()
            for row in raw["waits"]:
                if row["kind"] == "bridge_route":
                    row["clock_domain"] = dict(row["clock_domain"], **change)
            profile, pools, _ = self.profile(raw)
            for item in profile["per_branch"].values():
                self.assertEqual(item["components"]["bridge_pre"]["unknown"], 1)
                self.assertEqual(item["components"]["bridge_post"]["unknown"], 1)
                self.assertEqual(item["components"]["route_hold"]["unknown"], 0)
            self.assertEqual(sum(len(v) for v in pools["tuples"].values()), 0)

    def test_warmup_counts_only_and_prefix_gap_classes(self):
        arm = self.plan["arms"][0]
        raw = self.raw(arm)
        measured = next(r for r in stream_schedule(self.plan, 0, arm["rate"]) if r["measurement"])
        warmup = next(r for r in stream_schedule(self.plan, 0, arm["rate"]) if not r["measurement"])
        branch = self.plan["branches"][0]
        template = next(r for r in raw["native_terminals"] if r["decision_request"]["branch"] == branch)
        raw["admissions"].append(dict(raw["admissions"][0], input_frame_key=warmup["input_frame_key"],
                                      admission_timestamp_ms=500))
        for name, key, entry, end in (("warm", warmup["input_frame_key"], 503, 990),):
            record = copy.deepcopy(template)
            record["decision_request"]["input_frame_key"] = key
            record["path"]["timestamp_ms"] = entry
            record["terminal"]["terminal_timestamp_ms"] = end
            raw["native_terminals"].append(record)
        # The warmup terminal ends at 990 ms; measured path entry 1005 ms gives a 15 ms gap (unqueued).
        profile, pools, _ = self.profile(raw)
        self.assertEqual(profile["counts"], {"measured_completed": 4, "warmup_completed": 1, "drain_completed": 0})
        self.assertEqual(profile["per_branch"][branch]["prefix_gap_bins"]["10_100ms"], 1)
        for end, bucket, pooled in ((1003, "le_10ms", 0), (855, "gt_100ms", 1)):
            raw["native_terminals"][-1]["terminal"]["terminal_timestamp_ms"] = end
            profile, pools, _ = self.profile(raw)
            self.assertEqual(profile["per_branch"][branch]["prefix_gap_bins"][bucket], 1)
            self.assertEqual(profile["per_branch"][branch]["prefix_unqueued_pool_n"], pooled)
        self.assertEqual(measured["input_frame_key"], raw["admissions"][0]["input_frame_key"])

    # ---------------------------------------------------------------- 3.1 / 3.2 predictor

    def simulate(self, topology, rate, prefix, tuple_, replicas=1):
        arm = next(a for a in self.plan["arms"] if a["topology"] == topology and a["rate"] == rate)
        pools = {"prefix": {"shared": [prefix]} if topology == "shared" else {b: [prefix] for b in self.plan["branches"]},
                 "tuples": {b: [tuple_] for b in self.plan["branches"]}}
        return self.m.predict(self.plan, "test:" + arm["arm_id"], arm, pools, replicas)

    def test_deterministic_service_below_capacity_has_exact_latency(self):
        predicted, reason = self.simulate("shared", "1", 1.0, (1.0, 0.0, 1.0, 2.0, 0.5))
        self.assertIsNone(reason)
        self.assertEqual(predicted["drop_fraction"]["mean"], 0)
        self.assertEqual(predicted["Y100_frame"]["mean"], 1)
        # Six streams reach each FIFO route together: frame latencies 5.5, 7.5, ..., 15.5 ms.
        self.assertAlmostEqual(predicted["p50_ms"]["mean"], 9.5)
        self.assertAlmostEqual(predicted["p95_ms"]["mean"], 15.5)
        planned = sum(r["measurement"] for s in range(6) for r in stream_schedule(self.plan, s, "1"))
        self.assertEqual(predicted["planned_frames"], planned)

    def test_route_overload_drops_at_analytics_queue(self):
        interval = next(r for r in stream_schedule(self.plan, 0, "2") if r["measurement"])["duration_ns"] / 1e6
        predicted, _ = self.simulate("baseline", "2", 0.001, (0.0, 0.0, 0.0, interval, 0.0))
        by_reason = predicted["drop_fraction_by_reason"]
        self.assertEqual(by_reason[self.m.PREFIX_DROP]["mean"], 0)
        # One route serves one request per interval for six streams: long-run completion 1/6, buffers aside.
        self.assertAlmostEqual(by_reason[self.m.ANALYTICS_DROP]["mean"], 5 / 6, delta=0.03)

    def test_prefix_overload_shared_drops_whole_frames(self):
        interval = next(r for r in stream_schedule(self.plan, 0, "2") if r["measurement"])["duration_ns"] / 1e6
        tiny = (0.0, 0.0, 0.0, 0.001, 0.0)
        for topology in ("shared", "baseline"):
            predicted, _ = self.simulate(topology, "2", 2.4 * interval, tiny)
            fraction = predicted["drop_fraction_by_reason"][self.m.PREFIX_DROP]["mean"]
            self.assertAlmostEqual(fraction, 1 - 1 / 2.4, delta=0.03)
            self.assertEqual(predicted["drop_fraction_by_reason"][self.m.ANALYTICS_DROP]["mean"], 0)
            if topology == "shared":
                dropped = round(fraction * 4 * predicted["planned_frames"])
                self.assertEqual(dropped % 4, 0)

    def test_empty_pool_is_null_and_seeded_runs_are_identical(self):
        arm = self.plan["arms"][0]
        pools = {"prefix": {b: [1.0] for b in self.plan["branches"]},
                 "tuples": {b: ([] if b == "damage" else [(1.0, 0.0, 1.0, 2.0, 0.5)]) for b in self.plan["branches"]}}
        predicted, reason = self.m.predict(self.plan, "x", arm, pools, 2)
        self.assertIsNone(predicted)
        self.assertIn("tuples:damage", reason)
        pools["tuples"]["damage"] = [(3.0, 0.0, 1.0, 2.0, 0.5), (1.0, 0.0, 1.0, 9.0, 0.5)]
        first = self.m.canonical(self.m.predict(self.plan, "x", arm, pools, 3))
        second = self.m.canonical(self.m.predict(self.plan, "x", arm, pools, 3))
        self.assertEqual(first, second)
        self.assertEqual(self.m.replica_seed("x", 0), self.m.replica_seed("x", 0))
        self.assertNotEqual(self.m.replica_seed("x", 0), self.m.replica_seed("x", 1))

    def test_buffer_capacities_match_k_source_commit(self):
        commit = self.m.K_SOURCE_COMMIT
        probe = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", commit + "^{commit}"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if probe.returncode != 0:
            self.skipTest("K source commit is not present in this checkout (shallow clone)")
        config = subprocess.run(["git", "-C", str(ROOT), "show", commit + ":configs/experiments.yaml"],
                                check=True, stdout=subprocess.PIPE).stdout.decode()
        native = subprocess.run(["git", "-C", str(ROOT), "show",
                                 commit + ":deploy/native_gst_probe/vast_native_gst_probe.cpp"],
                                check=True, stdout=subprocess.PIPE).stdout.decode()
        lines = config.splitlines()
        values = {lines[i + 3].strip() for i, line in enumerate(lines) if line.strip() == "analytics_queue:"}
        self.assertEqual(values, {f"max_buffers: {self.m.ANALYTICS_QUEUE_CAPACITY}"})
        prefix = [native.splitlines()[i + 2].strip() for i, line in enumerate(native.splitlines())
                  if "vastcheckpointprefixqueue name=checkpoint_prefix_queue" in line]
        self.assertTrue(prefix)
        self.assertEqual(set(prefix), {f'<< " max-buffers={self.m.PREFIX_QUEUE_CAPACITY}"'})

    # ---------------------------------------------------------------- 4.1 thresholds and gates

    def predicted(self, y100=0.5, drop=0.0, p50=100.0, defined=None):
        return {"planned_frames": 10, "replicas": 4, "p50_defined_replicas": 4 if defined is None else defined,
                "Y100_frame": {"mean": y100}, "drop_fraction": {"mean": drop}, "p50_ms": {"mean": p50}}

    def test_threshold_boundaries(self):
        observed = {"planned_frames": 10, "Y100_frame": 0.25, "drop_fraction": 0.1, "completed_frames": 5, "p50_ms": 200.0}
        ok = lambda **kw: self.m.evaluate(observed, self.predicted(**kw), None)[:2]
        self.assertEqual(ok(y100=0.3, drop=0.1, p50=200.0), (True, []))
        self.assertEqual(ok(y100=0.3001, drop=0.1, p50=200.0)[1], ["Y100_frame"])
        self.assertEqual(ok(y100=0.25, drop=0.15, p50=200.0), (True, []))
        self.assertEqual(ok(y100=0.25, drop=0.1501, p50=200.0)[1], ["drop_fraction"])
        self.assertEqual(ok(y100=0.25, drop=0.1, p50=220.0), (True, []))      # 10 % of 200 ms
        self.assertEqual(ok(y100=0.25, drop=0.1, p50=220.01)[1], ["p50_ms"])
        small = dict(observed, p50_ms=50.0)
        self.assertTrue(self.m.evaluate(small, self.predicted(y100=0.25, drop=0.1, p50=60.0), None)[0])  # 10 ms floor
        self.assertFalse(self.m.evaluate(small, self.predicted(y100=0.25, drop=0.1, p50=60.01), None)[0])
        self.assertIn("p50_undefined_in_some_replicas", ok(y100=0.25, drop=0.1, p50=200.0, defined=3)[1])
        none = dict(observed, completed_frames=0, p50_ms=None)
        self.assertEqual(set(self.m.evaluate(none, self.predicted(y100=0.25, drop=0.1), None)[1]),
                         {"observed_completed_frames_zero", "p50_ms"})
        self.assertEqual(self.m.evaluate(observed, None, "empty calibration pool: shared")[:2],
                         (False, ["prediction null: empty calibration pool: shared"]))

    def test_gate_scenarios(self):
        def comparisons(fail_gpu=None, fail_cpu=None):
            rows = []
            for resource, fail in (("gpu", fail_gpu), ("cpu", fail_cpu)):
                for group, count in (("a", 12), ("b", 8), ("c", 12)):
                    for i in range(count):
                        identifier = f"{group}:{resource}:{i}"
                        rows.append({"comparison_id": identifier, "group": group, "resource": resource,
                                     "pass": identifier != fail})
            return rows
        both = self.m.gates(comparisons())
        self.assertEqual((both["gpu_latency_profile_use_permitted"], both["queueing_extrapolation_use_permitted"]),
                         (True, True))
        gpu_only = self.m.gates(comparisons(fail_cpu="b:cpu:3"))
        self.assertEqual((gpu_only["gpu_latency_profile_use_permitted"], gpu_only["queueing_extrapolation_use_permitted"]),
                         (True, False))
        self.assertEqual(gpu_only["cpu_failed_comparisons"], ["b:cpu:3"])
        neither = self.m.gates(comparisons(fail_gpu="a:gpu:0"))
        self.assertEqual((neither["gpu_latency_profile_use_permitted"], neither["queueing_extrapolation_use_permitted"]),
                         (False, False))
        self.assertTrue(self.m.gates(comparisons(fail_gpu="c:gpu:1"))["gpu_latency_profile_use_permitted"])
        with self.assertRaisesRegex(ValueError, "composition"):
            self.m.gates(comparisons()[1:])

    # ---------------------------------------------------------------- 4.2 report and consumers

    def test_cli_report_is_exclusive_deterministic_and_rejected_by_consumers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, descriptor, archive, pins = self.closed_fixture(root)
            argv = ["--study", "fixture", "--binding", descriptor["path"], "--archive", str(archive),
                    "--source-commit", "b" * 40, "--analysis-deadline-seconds", "600"]
            outputs = []
            with mock.patch.dict(self.m.KNOWN_STUDIES, {"fixture": pins}), mock.patch.object(self.m, "REPLICAS", 2):
                for name in ("first.json", "second.json"):
                    stdout = io.StringIO()
                    with contextlib.redirect_stdout(stdout):
                        self.assertEqual(self.m.main(argv + ["--output", str(root / name)]), 0)
                    receipt = json.loads(stdout.getvalue())
                    self.assertIn("elapsed_s", receipt)
                    outputs.append((root / name).read_bytes())
                    self.assertEqual(receipt["report"]["sha256"], hashlib.sha256(outputs[-1]).hexdigest())
                self.assertEqual(outputs[0], outputs[1])
                self.assertNotIn(b"elapsed", outputs[0])
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(self.m.main(argv + ["--output", str(root / "first.json")]), 1)
                link = root / "link.json"
                link.symlink_to(root / "absent.json")
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.m.main(argv + ["--output", str(link)]), 1)
                self.assertFalse((root / "absent.json").exists())
            self.assertEqual((root / "first.json").read_bytes(), outputs[0])
            report = json.loads(outputs[0])
            self.assertEqual(report["kind"], self.m.KIND)
            self.assertNotIn("artifact_kind", report)
            contract = importlib.import_module("publication_policy_contract")
            with mock.patch.object(contract, "_require_capabilities", return_value=None):
                with self.assertRaises(contract.PolicyContractError):
                    contract.select_static_hybrid_map("gstreamer_custom", report, {})
            with self.assertRaisesRegex(ValueError, "binding fields/kind"):
                self.reducer.reduce_closed_study(report)


if __name__ == "__main__":
    unittest.main()
