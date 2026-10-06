"""Finite study schedule and immutable coordinates; never a physical/full grant.

The caller supplies the prepared native Gst AU inventory and genuinely validated
material. Pure validation binds those bytes but does not validate an engine/model.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import random
import re

KIND = "finite-component-study"
SEED = 20260323
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RATES = {"0.25": 120, "1": 30, "2": 15}
MAX_PLAN_BYTES = 4 * 1024 * 1024
UINT64_MAX = (1 << 64) - 1
MEASUREMENT_START_NS = 30_000_000_000
OFFER_END_NS = 210_000_000_000
MEASUREMENT_END_NS = OFFER_END_NS - 1_000_000
ADMISSION_STOP_LEAD_NS = 250_000_000  # Amendment8: STOP before the half-open offer end.
_SHA = re.compile(r"^[0-9a-f]{64}$")


class StudyPlanError(ValueError):
    """Malformed, drifted or out-of-scope finite plan."""


def canonical_bytes(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, RecursionError) as exc:
        raise StudyPlanError("plan is not bounded finite JSON") from exc
    if len(raw) > MAX_PLAN_BYTES:
        raise StudyPlanError("plan byte cap exceeded")
    return raw


def _require(condition, message):
    if not condition:
        raise StudyPlanError(message)


def _integer(value, label, minimum=0, maximum=UINT64_MAX):
    _require(type(value) is int and minimum <= value <= maximum, label + " integer bound")
    return value


def _sha(value):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, "invalid SHA256")
    return value


def _descriptor(value):
    _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256"},
             "descriptor fields")
    _require(type(value["path"]) is str and 0 < len(value["path"]) <= 4096,
             "descriptor path bound")
    _integer(value["size_bytes"], "descriptor size", 1)
    _sha(value["sha256"])


def _schedules(intake):
    _require(type(intake) is dict and set(intake) == {"dataset_id", "recordings"},
             "intake fields")
    dataset = intake["dataset_id"]
    _require(type(dataset) is str and re.fullmatch(r"[a-z0-9_-]{1,64}", dataset),
             "dataset_id domain")
    recordings = intake["recordings"]
    _require(type(recordings) is dict and set(recordings) == {"front_gate", "underbody"},
             "exact two recording inputs required")
    schedules = {}
    for name, recording in recordings.items():
        _require(type(recording) is dict and {"descriptor", "access_units"} <= set(recording),
                 "recording fields")
        _descriptor(recording["descriptor"])
        allowed = {"descriptor", "access_units", "width", "height", "parent_descriptor",
                   "context_descriptor", "normalization_descriptor", "reference_descriptor", "inventory_descriptor"}
        _require(set(recording) <= allowed, "unknown recording binding")
        width, height = (1920, 1080) if name == "front_gate" else (1700, 236)
        for field, expected in (("width", width), ("height", height)):
            if field in recording:
                _require(type(recording[field]) is int and recording[field] == expected,
                         "recording geometry changed")
        for field in allowed - {"descriptor", "access_units", "width", "height"}:
            if field in recording:
                _descriptor(recording[field])
        units = recording["access_units"]
        _require(type(units) is list and len(units) == 442, "exact 442 AU inventory required")
        previous_pts = -1
        for ordinal, unit in enumerate(units):
            _require(type(unit) is dict and set(unit) == {
                "ordinal", "pts_ns", "dts_ns", "duration_ns",
                "payload_sha256", "payload_size_bytes"}, "AU inventory fields")
            _require(type(unit["ordinal"]) is int and unit["ordinal"] == ordinal,
                     "AU ordinal domain changed")
            pts = _integer(unit["pts_ns"], "native PTS")
            _require(pts > previous_pts and (ordinal != 0 or pts == 0), "native PTS order/origin")
            _require(_integer(unit["dts_ns"], "native DTS") == pts, "all-I DTS/PTS mismatch")
            _integer(unit["duration_ns"], "native duration", 1, UINT64_MAX // 120)
            _integer(unit["payload_size_bytes"], "payload size", 1, 16 * 1024 * 1024)
            _sha(unit["payload_sha256"])
            _require(len(f"{dataset}:5:{recording['descriptor']['sha256']}:0:{pts}") <= 136,
                     "native input_frame_key byte bound")
            previous_pts = pts
        schedules[name] = {}
        for rate, scale in RATES.items():
            offset, rows = 0, []
            for unit in units:
                pts = _integer(unit["pts_ns"] * scale, "scaled PTS")
                dts = _integer(unit["dts_ns"] * scale, "scaled DTS")
                duration = unit["duration_ns"] * scale
                rows.append({
                    "derived_ordinal": unit["ordinal"], "access_unit_pts_ns": unit["pts_ns"],
                    "source_sequence": unit["ordinal"] + 1,
                    "transport_pts_ns": pts, "transport_dts_ns": dts,
                    "payload_sha256": unit["payload_sha256"],
                    "payload_size_bytes": unit["payload_size_bytes"],
                    "schedule_offset_ns": offset, "duration_ns": duration,
                    "planned": offset < OFFER_END_NS,
                    "eligible_before_stop": offset < OFFER_END_NS,
                    "measurement": MEASUREMENT_START_NS <= offset < MEASUREMENT_END_NS,
                })
                offset = _integer(offset + duration, "schedule cumulative duration")
            _require(offset >= OFFER_END_NS and any(r["measurement"] for r in rows),
                     "bounded inventory does not cover original offer window")
            schedules[name][rate] = {
                "scale": scale, "rows": rows,
                "schedule_sha256": hashlib.sha256(canonical_bytes(rows)).hexdigest(),
            }
    return schedules


def _arm(arm_id, *, pair_id, resource, rate, repeat, topology, stage, order):
    return {"arm_id": arm_id, "pair_id": pair_id, "resource": resource,
            "rate": rate, "repeat": repeat, "topology": topology, "stage": stage,
            "order": order}


def build_study_plan(intake, selected_material):
    """Build a finite pure plan; physical material readiness remains caller-owned."""
    _require(type(selected_material) is dict and bool(selected_material),
             "selected material binding required")
    canonical_bytes(selected_material)
    schedules = _schedules(intake)
    blocks = [(resource, rate) for resource in ("cpu", "gpu") for rate in RATES]
    random.Random(SEED).shuffle(blocks)
    arms, pairs = [], []
    for repeat, sequence in ((1, blocks), (2, list(reversed(blocks)))):
        for resource, rate in sequence:
            pair_id = f"effect-r{repeat}-{resource}-{rate}"
            members = []
            for topology in (("baseline", "shared") if repeat == 1 else ("shared", "baseline")):
                arm_id = f"{pair_id}-{topology}"
                members.append(arm_id)
                arms.append(_arm(arm_id, pair_id=pair_id, resource=resource, rate=rate,
                                 repeat=repeat, topology=topology, stage="effect", order=len(arms)))
            pairs.append({"pair_id": pair_id, "repeat": repeat, "resource": resource,
                          "rate": rate, "arm_ids": members})
    pilots = {}
    for stage in ("initial", "conditional"):
        pilots[stage] = [
            _arm(f"pilot-{stage}-{resource}-{topology}", pair_id=None, resource=resource,
                 rate="1", repeat=0, topology=topology, stage="pilot-" + stage, order=i)
            for i, (resource, topology) in enumerate(
                (("cpu", "baseline"), ("cpu", "shared"), ("gpu", "baseline"), ("gpu", "shared")))]
    material = copy.deepcopy(selected_material)
    bundle = {"intake": copy.deepcopy(intake), "selected_material": material}
    result = {
        "schema_version": 1, "kind": KIND, "seed": SEED,
        "shuffle_algorithm": "CPython3.12.3 random.Random(20260323).shuffle",
        "branches": list(BRANCHES),
        "streams": [{"stream_id": i, "recording": "front_gate" if i < 5 else "underbody"}
                    for i in range(6)],
        "phases": {"warmup_ns": MEASUREMENT_START_NS, "measurement_ns": 180_000_000_000,
                   "drain_ns": 10_000_000_000, "boundary_guard_ns": 1_000_000,
                   "deadline_ns": 100_000_000},
        "intake": bundle["intake"], "selected_material": material, "schedules": schedules,
        "bundle_sha256": hashlib.sha256(canonical_bytes(bundle)).hexdigest(),
        "arms": arms, "pairs": pairs, "pilots": pilots,
        "limits": {"max_operations": 32, "max_admissions_per_stream": 442,
                   "max_requests_per_arm": 10608, "preparation_s": 14400,
                   "campaign_s": 14400, "max_raw_bytes_per_arm": 512 * 1024 * 1024,
                   "max_campaign_raw_bytes": 24 * 1024 * 1024 * 1024},
        "pilot_rule": {"minimum_observations": 30, "median_wait_fraction": 0.10,
                       "initial_variant": "global-client", "conditional_variant": "branch-channel"},
        "canonical_study_complete": False, "qualification_eligible": False,
        "q4_eligible": False, "publication_eligible": False, "full_run_eligible": False,
    }
    result["sha256"] = hashlib.sha256(canonical_bytes(result)).hexdigest()
    canonical_bytes(result)
    return result


def validate_study_plan(plan):
    """Reconstruct every coordinate/schedule from the original bound inputs."""
    _require(type(plan) is dict and plan.get("kind") == KIND, "study kind required")
    canonical_bytes(plan)
    _require("intake" in plan and "selected_material" in plan, "plan inputs missing")
    expected = build_study_plan(plan["intake"], plan["selected_material"])
    _require(canonical_bytes(plan) == canonical_bytes(expected), "plan hash/coordinates/bindings drifted")
    return plan


def admission_stop_lead_ns(plan, rate, *, lead_ns=ADMISSION_STOP_LEAD_NS):
    """STOP lead before the offer end, proven against every stream schedule of this rate."""
    _require(type(lead_ns) is int and 0 < lead_ns < OFFER_END_NS, "admission STOP lead is invalid")
    planned = []
    for stream_id in range(6):
        for row in stream_schedule(plan, stream_id, rate):
            if row["planned"]:
                _require(row["schedule_offset_ns"] < OFFER_END_NS - lead_ns, "planned AU lies inside the STOP lead")
                planned.append(row["schedule_offset_ns"])
            else:
                _require(row["schedule_offset_ns"] >= OFFER_END_NS, "unplanned AU precedes the half-open offer end")
    _require(bool(planned) and 2 * lead_ns <= OFFER_END_NS - max(planned), "STOP lead exceeds half the final offer gap")
    return lead_ns


CLOCK_DOMAIN_LABEL = "timens-offsets:monotonic=0,0;boottime=0,0"


def clock_domain_label(offsets_text, time_namespace, time_for_children):
    """Zero monotonic/boottime offsets of the namespace the process actually runs in share the initial clock."""
    _require(type(time_namespace) is str and re.fullmatch(r"time:\[[0-9]+\]", time_namespace) is not None and
             time_namespace == time_for_children, "study clock time and time_for_children namespaces differ")
    _require(type(offsets_text) is str and len(offsets_text) <= 4096 and
             [row.split() for row in offsets_text.splitlines()] == [["monotonic", "0", "0"], ["boottime", "0", "0"]],
             "study clock namespace offsets are missing, malformed or nonzero")
    return CLOCK_DOMAIN_LABEL


def actual_clock_domain_label(proc="/proc/self"):
    with open(proc+"/timens_offsets", "rb") as stream:
        raw = stream.read(4097)
    return clock_domain_label(raw.decode("ascii"), os.readlink(proc+"/ns/time"), os.readlink(proc+"/ns/time_for_children"))


def stream_schedule(plan, stream_id, rate):
    """Expand the original native admission key without guessing run-relative IDs."""
    _integer(stream_id, "stream", 0, 5)
    _require(rate in RATES, "unsupported study rate")
    recording = plan["streams"][stream_id]["recording"]
    sha = plan["intake"]["recordings"][recording]["descriptor"]["sha256"]
    return [dict(row, stream_id=stream_id, source_sha256=sha, source_cycle=0,
                 input_frame_key=f"{plan['intake']['dataset_id']}:{stream_id}:{sha}:0:{row['access_unit_pts_ns']}")
            for row in plan["schedules"][recording][rate]["rows"]]

