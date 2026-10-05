"""Pure synthetic inventory tests; these do not establish physical media readiness."""
from __future__ import annotations
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

def intake_fixture(duration_ns=33_333_333):
    recordings = {}
    for recording in ("front_gate", "underbody"):
        source_sha = hashlib.sha256(recording.encode()).hexdigest()
        recordings[recording] = {
            "descriptor": {"path": "/synthetic/" + recording + ".mp4",
                           "size_bytes": 44200, "sha256": source_sha},
            "access_units": [
                {"ordinal": i, "pts_ns": i * 20 * 1_000_000_000 // 600,
                 "dts_ns": i * 20 * 1_000_000_000 // 600,
                 "duration_ns": duration_ns,
                 "payload_sha256": hashlib.sha256((recording + str(i)).encode()).hexdigest(),
                 "payload_size_bytes": 100}
                for i in range(442)],
        }
    return {"dataset_id": "synthetic_study", "recordings": recordings}

def material_fixture():
    return {"source_commit": "a" * 40, "runtime_image_id": "sha256:" + "b" * 64,
            "worker_images": {"cpu": "sha256:" + "c" * 64, "gpu": "sha256:" + "d" * 64},
            "model_authority_sha256": "e" * 64, "fixture_only": True}

class CanonicalStudyPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan_module = importlib.import_module("canonical_systems_study_plan_v1")

    def plan(self, intake=None):
        return self.plan_module.build_study_plan(intake or intake_fixture(), material_fixture())

    def test_exact_matrix_counterbalance_and_private_seed(self):
        first, second = self.plan(), self.plan()
        self.assertEqual(first, second)
        self.assertEqual(first["kind"], "finite-component-study")
        self.assertEqual(len(first["arms"]), 24)
        self.assertEqual(len(first["pairs"]), 12)
        self.assertEqual(len({a["arm_id"] for a in first["arms"]}), 24)
        repeat1 = [p for p in first["pairs"] if p["repeat"] == 1]
        repeat2 = [p for p in first["pairs"] if p["repeat"] == 2]
        self.assertEqual([(p["resource"], p["rate"]) for p in repeat2],
                         list(reversed([(p["resource"], p["rate"]) for p in repeat1])))
        for pair in first["pairs"]:
            members = [a for a in first["arms"] if a["pair_id"] == pair["pair_id"]]
            self.assertEqual([a["topology"] for a in members],
                             ["baseline", "shared"] if pair["repeat"] == 1 else ["shared", "baseline"])

    def test_stream_mapping_and_conditional_pilot_are_separate(self):
        plan = self.plan()
        self.assertEqual([s["recording"] for s in plan["streams"]],
                         ["front_gate"] * 5 + ["underbody"])
        self.assertEqual(len(plan["pilots"]["initial"]), 4)
        self.assertEqual(len(plan["pilots"]["conditional"]), 4)
        self.assertEqual(plan["limits"]["max_operations"], 32)
        self.assertEqual(plan["limits"]["max_admissions_per_stream"], 442)
        self.assertFalse(plan["qualification_eligible"])
        self.assertFalse(plan["full_run_eligible"])
        self.assertFalse(plan["canonical_study_complete"])

    def test_cumulative_native_duration_not_nominal_denominators(self):
        plan = self.plan()
        rows = plan["schedules"]["front_gate"]["2"]["rows"]
        self.assertEqual(rows[60]["schedule_offset_ns"], 29_999_999_700)
        self.assertFalse(rows[60]["measurement"])
        self.assertTrue(rows[61]["measurement"])
        self.assertFalse(rows[420]["measurement"])
        self.assertTrue(rows[420]["eligible_before_stop"])
        self.assertEqual(sum(r["measurement"] for r in rows), 359)
        ones = plan["schedules"]["front_gate"]["1"]["rows"]
        self.assertEqual(sum(r["measurement"] for r in ones), 179)
        changed = intake_fixture()
        changed["recordings"]["front_gate"]["access_units"][0]["duration_ns"] += 30
        altered = self.plan(changed)["schedules"]["front_gate"]["2"]["rows"]
        self.assertTrue(altered[60]["measurement"])
        self.assertEqual(sum(r["measurement"] for r in altered), 360)

    def test_scaled_native_pts_dts_and_source_identity(self):
        plan = self.plan()
        row = plan["schedules"]["front_gate"]["2"]["rows"][61]
        unit = plan["intake"]["recordings"]["front_gate"]["access_units"][61]
        self.assertEqual(row["transport_pts_ns"], unit["pts_ns"] * 15)
        self.assertEqual(row["transport_dts_ns"], unit["dts_ns"] * 15)
        slot = self.plan_module.stream_schedule(plan, 3, "2")[61]
        sha = plan["intake"]["recordings"]["front_gate"]["descriptor"]["sha256"]
        self.assertEqual(slot["input_frame_key"], f"synthetic_study:3:{sha}:0:{unit['pts_ns']}")
        self.assertEqual(slot["payload_sha256"], unit["payload_sha256"])
        self.assertEqual(slot["source_cycle"], 0)

    def test_plan_validation_refuses_foreign_legacy_kind(self):
        plan = self.plan()
        for kind in ("vast_gstreamer_component_pair_v1", "qualification", "full"):
            changed = copy.deepcopy(plan)
            changed["kind"] = kind
            with self.assertRaisesRegex(ValueError, "kind"):
                self.plan_module.validate_study_plan(changed)

    def test_plan_drift_and_pair_reordering_fail(self):
        for mutation in (lambda p: p["arms"].reverse(),
                         lambda p: p["schedules"]["front_gate"]["2"]["rows"][61].update(measurement=False),
                         lambda p: p["selected_material"].update(source_commit="f" * 40),
                         lambda p: p.update(seed=1)):
            altered = self.plan()
            mutation(altered)
            with self.assertRaises(ValueError):
                self.plan_module.validate_study_plan(altered)

    def test_inventory_count_duplicates_and_missing_timestamp_refuse(self):
        for mutation in (
            lambda r: r["access_units"].pop(),
            lambda r: r["access_units"].append(copy.deepcopy(r["access_units"][-1])),
            lambda r: r["access_units"][1].update(pts_ns=0),
            lambda r: r["access_units"][1].update(dts_ns=None),
            lambda r: r["access_units"][0].update(ordinal=1),
            lambda r: r["access_units"][0].update(payload_size_bytes=16 * 1024 * 1024 + 1),
        ):
            intake = intake_fixture()
            mutation(intake["recordings"]["front_gate"])
            with self.assertRaises(ValueError):
                self.plan(intake)
        long_key = intake_fixture()
        long_key["dataset_id"] = "x" * 64
        with self.assertRaisesRegex(ValueError, "input_frame_key"):
            self.plan(long_key)
        upper = intake_fixture()
        upper["dataset_id"] = "FixtureUppercase"
        with self.assertRaisesRegex(ValueError, "dataset_id"):
            self.plan(upper)

    def test_duration_overflow_zero_bool_and_insufficient_prefix_refuse(self):
        for value in (0, -1, True, 1 << 64, 1):
            intake = intake_fixture(value)
            with self.assertRaises(ValueError):
                self.plan(intake)

    def test_nonfinite_material_and_plan_caps_refuse(self):
        with self.assertRaises(ValueError):
            self.plan_module.build_study_plan(intake_fixture(), {"clock": float("nan")})
        with self.assertRaises(ValueError):
            self.plan_module.build_study_plan(intake_fixture(), {"huge": "x" * (4 * 1024 * 1024)})

    def test_builder_never_mutates_input_and_hash_is_canonical(self):
        intake, material = intake_fixture(), material_fixture()
        original = copy.deepcopy((intake, material))
        plan = self.plan_module.build_study_plan(intake, material)
        self.assertEqual((intake, material), original)
        unsigned = dict(plan)
        digest = unsigned.pop("sha256")
        self.assertEqual(digest, hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False).encode("ascii")).hexdigest())
        self.assertEqual(self.plan_module.validate_study_plan(plan), plan)

if __name__ == "__main__":
    unittest.main()

