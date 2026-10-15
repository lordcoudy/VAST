"""Descriptive service profile and trace-driven queue/latency predictor over closed finite-study raw.

Host-only analysis (change ``add-service-profile-latency-model``). It reads closed
finite-study inputs through the reducer's pinned no-follow reader, reproduces the
canonical per-arm reduction, and never feeds policy calibration, runtime or legacy
gates. The report is descriptive, not a policy formula.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import random
import stat
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical_systems_study_plan_v1 import CLOCK_DOMAIN_LABEL, stream_schedule, validate_study_plan
from reduce_canonical_systems_study_v1 import (
    MAX_CAMPAIGN_BYTES, MAX_DOCUMENT_BYTES, MAX_FILE_BYTES, MAX_INPUT_FILES, ReductionError,
    _epoch, _pairs, _recheck_named, distribution, read_closed_rows, reduce_arm)

KIND = "vast-service-profile-latency-model-v1"
MODEL_SCHEMA_VERSION = 1
LABEL = "descriptive, not a policy formula"
SEED = 20260323
REPLICAS = 200
UNQUEUED_GAP_MS = 10.0
SUM_TOLERANCE_MS = 0.001
MAX_ANALYSIS_DEADLINE_S = 14400
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
K_SOURCE_COMMIT = "fefab7a93ab5e850ddcb90ac4c9d8eb351811fa0"
# Frozen at K_SOURCE_COMMIT: configs/experiments.yaml analytics_queue.max_buffers and the
# native probe vastcheckpointprefixqueue max-buffers (verified by a git-show test).
ANALYTICS_QUEUE_CAPACITY = 1
PREFIX_QUEUE_CAPACITY = 1
ANALYTICS_DROP = "native_pre_detector_queue_full_drop_newest"
PREFIX_DROP = "native_postdecode_preprocess_queue_full_drop_newest"
DROP_REASONS = (PREFIX_DROP, ANALYTICS_DROP)
COMPONENTS = ("prefix", "probe_pre", "native_wait", "bridge_pre", "route_wait", "route_hold", "bridge_post")
TUPLE_COMPONENTS = ("probe_pre", "native_wait", "bridge_pre", "route_hold", "bridge_post")
ARCHIVE_PATH = ("openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/"
                "physical-K-completed-v1/s__run/study-results.original.json.gz")
KNOWN_STUDIES = {
    "attempt-K": {
        "binding": {"size_bytes": 31496,
                    "sha256": "8f92bb401f8de4b4403dc46ecd227d30acbfbe5e80243fd86f5d11b57805ba90"},
        "archive": {"size_bytes": 590982,
                    "sha256": "c483d64fbb9ddac0127dcc93d8482cb0b409af0d35bb3870e1b2293181588d8b"},
    },
}
UNMODELLED_FACTORS = (
    "route threading.Lock acquisition order is not guaranteed FIFO",
    "single shared Python bridge process (GIL) runs pre-route preprocessing",
    "contention between routes on the shared GPU and CPU",
    "decode is part of the prefix server without its own queue",
    "policy decide RPC runs in the probe after the analytics queue but is counted in the prefix server",
    "prefix duration is sampled independently of the post-queue component tuple",
    "probe work after native client release is assumed to be zero",
    "within a frame each branch draws its own tuple (and in baseline its own prefix); the frame latency is the "
    "maximum over these independent draws",
)
ARRIVAL_ROWS = "frozen schedule rows with planned = true (rows beyond the offer end are never offered)"
CENSOR_AT = "last planned slot schedule_offset_ns + plan drain_ns"
SEED_RULE = ("random.Random(int.from_bytes(sha256('20260323:<comparison_id>:<replica>')[:8], 'big')); "
             "comparison_id = '<group>:<calibration_arm_id>-><target_arm_id>'")
ELIGIBILITY = ("qualification_eligible", "q4_eligible", "publication_eligible", "full_run_eligible",
               "canonical_study_complete", "policy_calibration_eligible")
CPU_GATE_NOTE = ("CPU rate 2 arms have only 34-103 completed frames and baseline CPU prefix pools per branch "
                 "hold few prefix_unqueued requests at rate 2; empty pools (null predictions) and the "
                 "p50-defined-in-all-replicas rule make queueing_extrapolation_use_permitted = false a likely, "
                 "admissible outcome that is not a reason to change thresholds.")


class ModelError(ReductionError):
    """Foreign, inconsistent or unpinned input for the descriptive model."""


def _require(condition, message):
    if not condition:
        raise ModelError(message)


def _deadline(deadline):
    _require(type(deadline) in (int, float) and math.isfinite(deadline) and time.monotonic() < deadline,
             "analysis deadline exceeded")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


# --------------------------------------------------------------------------- loading


def read_pinned_bytes(path, size_bytes, sha256, observations):
    """Regular, non-symlink file with the pinned size and SHA256; epoch kept for the final recheck."""
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "pinned path must be absolute")
    _require(type(size_bytes) is int and 0 < size_bytes <= MAX_ARCHIVE_BYTES, "pinned size bound")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ModelError("pinned file unavailable or symlink: " + str(exc)) from exc
    try:
        initial = _epoch(os.fstat(fd))
        _require(stat.S_ISREG(initial[2]) and initial[4] == size_bytes, "pinned file regular/size mismatch")
        body = bytearray()
        while len(body) < size_bytes:
            part = os.pread(fd, min(1024 * 1024, size_bytes - len(body)), len(body))
            _require(bool(part), "pinned file short read")
            body.extend(part)
        _require(os.pread(fd, 1, size_bytes) == b"", "pinned file grew")
        _require(hashlib.sha256(body).hexdigest() == sha256, "pinned file SHA256 mismatch")
        _require(_epoch(os.fstat(fd)) == initial and _epoch(os.lstat(path)) == initial, "pinned file epoch drift")
    finally:
        os.close(fd)
    observations.append((str(path), initial, True))
    return bytes(body)


def load_archive(path, pin, observations):
    body = read_pinned_bytes(path, pin["size_bytes"], pin["sha256"], observations)
    try:
        raw = gzip.decompress(body)
        _require(len(raw) <= MAX_ARCHIVE_BYTES, "archive decompressed cap")
        archive = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError("archive is not gzip JSON: " + str(exc)) from exc
    _require(type(archive) is dict and type(archive.get("reduction")) is dict
             and type(archive["reduction"].get("arms")) is dict, "archive reduction missing")
    return archive


def iter_closed_arms(binding, deadline, observations, descriptors):
    """Read like reduce_closed_study (plan, then per arm closure and sorted roles), one arm at a time."""
    _require(type(binding) is dict and set(binding) == {"kind", "plan", "plan_sha256", "bundle_sha256",
             "final_variant", "arms"} and binding["kind"] == "finite-component-study-closed-inputs",
             "closed study binding fields/kind")
    seen, total = set(), [0]

    def read(descriptor, document=False):
        _deadline(deadline)
        _require(type(descriptor) is dict and type(descriptor.get("path")) is str, "closed role descriptor")
        name = str(Path(descriptor["path"]))
        _require(name not in seen, "closed role path alias")
        seen.add(name)
        _require(len(seen) <= MAX_INPUT_FILES, "closed input file count cap")
        size = descriptor.get("size_bytes")
        _require(type(size) is int and size >= 0, "closed input size")
        total[0] += size
        _require(total[0] <= MAX_CAMPAIGN_BYTES, "campaign raw byte cap")
        value = read_closed_rows(descriptor, max_bytes=MAX_DOCUMENT_BYTES if document else MAX_FILE_BYTES,
                                 deadline=deadline, document=document, observations=observations)
        descriptors.append(dict(descriptor))
        return value

    plan = read(binding["plan"], True)
    validate_study_plan(plan)
    _require(binding["plan_sha256"] == plan["sha256"] and binding["bundle_sha256"] == plan["bundle_sha256"],
             "closed plan/source bundle mismatch")
    arms = binding["arms"]
    _require(type(arms) is dict and set(arms) == {a["arm_id"] for a in plan["arms"]} and len(arms) == 24,
             "closed binding exact 24 effect arms required")
    yield "plan", plan
    roles = ("admissions", "guardian_events", "native_terminals", "source_events", "waits")
    for arm in plan["arms"]:
        entry = arms[arm["arm_id"]]
        _require(type(entry) is dict and set(entry) == set(roles) | {"closure"}, "closed arm role set")
        before = total[0]
        result = {"closure": read(entry["closure"], True)}
        for role in sorted(roles):
            _require(type(entry[role]) is list and 0 < len(entry[role]) <= 64, "closed role file count")
            result[role] = []
            for descriptor in entry[role]:
                result[role].extend(read(descriptor))
        _require(total[0] - before <= plan["limits"]["max_raw_bytes_per_arm"], "arm physical raw byte cap")
        _require(result["closure"].get("final_variant") == binding["final_variant"], "mixed final variant")
        yield arm, result


# --------------------------------------------------------------------------- profile


def _ms(ns):
    return ns / 1e6


def _same_monotonic_domain(left, right):
    return all(type(d) is dict and d.get("clock") == "CLOCK_MONOTONIC" and d.get("time_namespace") == CLOCK_DOMAIN_LABEL
               and type(d.get("boot_id")) is str and d["boot_id"] not in ("", "unknown")
               for d in (left, right)) and left["boot_id"] == right["boot_id"]


def _ordered(row, fields, label):
    values = [row.get(f) for f in fields]
    _require(all(type(v) is int and v >= 0 for v in values), label + " integer endpoints")
    _require(values == sorted(values), label + " endpoint order")
    return values


def _nonnegative(value, label):
    _require(math.isfinite(value) and value >= 0, "negative component: " + label)
    return value


def _stats(values):
    result = distribution(values)
    result["cv"] = (statistics.pstdev(values) / result["mean"]) if values and result["mean"] else None
    return result


def arm_profile(plan, arm, raw):
    """Seven code-order components per measured completed branch request; see the spec."""
    slots = {r["input_frame_key"]: r for s in range(6) for r in stream_schedule(plan, s, arm["rate"])}
    admissions = {}
    for row in raw["admissions"]:
        key = row.get("input_frame_key")
        _require(key in slots and key not in admissions, "admission foreign/duplicate key")
        admissions[key] = row["admission_timestamp_ms"]
    waits = {"native_client": {}, "bridge_route": {}, "worker": {}}
    natives_by_request = {}
    for row in raw["waits"]:
        kind, request = row.get("kind"), row.get("request_id")
        _require(kind in waits and type(request) is str and bool(request), "wait kind/request binding")
        _require(request not in waits[kind], "duplicate request_id in " + kind)
        waits[kind][request] = row
        if kind == "native_client":
            pair = (row.get("input_frame_key"), row.get("branch"))
            _require(pair not in natives_by_request, "duplicate native client request for a branch")
            natives_by_request[pair] = row
    processed, drops = {}, {}
    for record in raw["native_terminals"]:
        if "branch_terminal" in record:
            terminal = record["branch_terminal"]
            pair = (terminal.get("input_frame_key"), terminal.get("branch_id"))
            _require(pair not in drops, "duplicate native drop")
            drops[pair] = terminal.get("terminal_reason")
            continue
        request, path, terminal = (record.get(k) for k in ("decision_request", "path", "terminal"))
        _require(all(type(v) is dict for v in (request, path, terminal)), "native terminal objects")
        pair = (request.get("input_frame_key"), request.get("branch"))
        _require(pair not in processed, "duplicate native terminal")
        evidence = (record.get("accepted_record") or {}).get("native_decision_evidence") or {}
        entry, end = path.get("timestamp_ms"), terminal.get("terminal_timestamp_ms")
        _require(type(entry) in (int, float) and type(end) in (int, float), "native path/terminal timestamps")
        _require(evidence.get("path_entry_timestamp_ms") == entry, "path entry evidence mismatch")
        _require(evidence.get("terminal_timestamp_ms") == end, "terminal evidence mismatch")
        processed[pair] = (request, entry, end, terminal.get("terminal_status"))
    # Terminal of the previous processed request of the same stream x branch, ordered by path entry.
    by_pair = {}
    for (key, branch), (request, entry, end, _) in processed.items():
        by_pair.setdefault((request.get("stream_id"), branch), []).append((entry, end, key))
    previous = {}
    for (_, branch), rows in by_pair.items():
        rows.sort()
        for index, (_, _, key) in enumerate(rows):
            previous[key, branch] = rows[index - 1][1] if index else None
    branches = plan["branches"]
    per_branch = {b: {"components": {c: [] for c in COMPONENTS}, "unknown": {c: 0 for c in COMPONENTS},
                      "worker_backend": [], "worker_residence": [], "worker_unknown": 0,
                      "gap_bins": {"le_10ms": 0, "10_100ms": 0, "gt_100ms": 0, "no_previous": 0},
                      "prefix_unqueued": [], "tuples": [], "route_wait_observed": []} for b in branches}
    counts = {"measured_completed": 0, "warmup_completed": 0, "drain_completed": 0}
    for (key, branch), (request, entry, end, status) in sorted(processed.items()):
        if status != "completed":
            continue
        slot = slots.get(key)
        _require(slot is not None and key in admissions and branch in branches, "terminal foreign key/branch")
        if not slot["measurement"]:
            warmup = slot["schedule_offset_ns"] < plan["phases"]["warmup_ns"]
            counts["warmup_completed" if warmup else "drain_completed"] += 1
            continue
        counts["measured_completed"] += 1
        item = per_branch[branch]
        latency = end - admissions[key]
        value = {"prefix": _nonnegative(entry - admissions[key], "prefix")}
        native = natives_by_request.get((key, branch))
        bridge = None
        if native is not None:
            for field in ("run_id", "input_frame_key", "branch", "stream_id", "frame_id"):
                _require(native.get(field) == request.get(field), "native client/terminal identity mismatch: " + field)
            attempt, acquired, reply, released = _ordered(
                native, ("attempt_ns", "acquired_ns", "reply_ns", "released_ns"), "native client")
            value["probe_pre"] = _nonnegative((end - entry) - _ms(released - attempt), "probe_pre")
            value["native_wait"] = _ms(acquired - attempt)
            bridge = waits["bridge_route"].get(native["request_id"])
        if bridge is not None:
            b_attempt, b_acquired, b_reply, b_released = _ordered(
                bridge, ("attempt_ns", "acquired_ns", "reply_ns", "released_ns"), "bridge route")
            value["route_wait"] = _ms(b_acquired - b_attempt)
            value["route_hold"] = _ms(b_released - b_acquired)
            if _same_monotonic_domain(native.get("clock_domain"), bridge.get("clock_domain")):
                value["bridge_pre"] = _nonnegative(_ms(b_attempt - acquired), "bridge_pre")
                value["bridge_post"] = _nonnegative(_ms(released - b_released), "bridge_post")
        for component in COMPONENTS:
            if component in value:
                item["components"][component].append(value[component])
            else:
                item["unknown"][component] += 1
        if all(c in value for c in COMPONENTS):
            _require(abs(sum(value[c] for c in COMPONENTS) - latency) <= SUM_TOLERANCE_MS,
                     "component sum differs from reducer latency")
            item["tuples"].append(tuple(value[c] for c in TUPLE_COMPONENTS))
            item["route_wait_observed"].append(value["route_wait"])
        worker = waits["worker"].get(native["request_id"]) if native is not None else None
        if worker is not None and all(type(worker.get(f)) is int for f in
                                      ("received_ns", "inference_started_ns", "inference_finished_ns", "completed_ns")):
            w = _ordered(worker, ("received_ns", "inference_started_ns", "inference_finished_ns", "completed_ns"), "worker")
            item["worker_backend"].append(_ms(w[2] - w[1]))
            item["worker_residence"].append(_ms(w[3] - w[0]))
        else:
            item["worker_unknown"] += 1
        gap_previous = previous[key, branch]
        if gap_previous is None:
            item["gap_bins"]["no_previous"] += 1
            item["prefix_unqueued"].append(value["prefix"])
        else:
            gap = entry - gap_previous
            bucket = "le_10ms" if gap <= UNQUEUED_GAP_MS else "10_100ms" if gap <= 100 else "gt_100ms"
            item["gap_bins"][bucket] += 1
            if gap > UNQUEUED_GAP_MS:
                item["prefix_unqueued"].append(value["prefix"])
    published = {}
    for branch, item in per_branch.items():
        published[branch] = {
            "components": {c: dict(_stats(v), unknown=item["unknown"][c]) for c, v in item["components"].items()},
            "worker_backend_ms": _stats(item["worker_backend"]), "worker_residence_ms": _stats(item["worker_residence"]),
            "worker_unknown": item["worker_unknown"],
            "worker_label": "private mapping/backend/copies; not pure GPU kernel time",
            "prefix_gap_bins": item["gap_bins"], "prefix_unqueued_pool_n": len(item["prefix_unqueued"]),
            "tuple_pool_n": len(item["tuples"]),
        }
    pools = {
        "prefix": ({"shared": [v for b in branches for v in per_branch[b]["prefix_unqueued"]]}
                   if arm["topology"] == "shared" else {b: per_branch[b]["prefix_unqueued"] for b in branches}),
        "tuples": {b: per_branch[b]["tuples"] for b in branches},
    }
    measured_drops = {r: 0 for r in DROP_REASONS}
    for (key, branch), reason in drops.items():
        _require(reason in DROP_REASONS and key in slots, "foreign drop reason/key")
        if slots[key]["measurement"]:
            measured_drops[reason] += 1
    profile = {"arm_id": arm["arm_id"], "per_branch": published, "counts": counts,
               "shared_prefix_pool_n": len(pools["prefix"].get("shared", [])) if arm["topology"] == "shared" else None,
               "observed_route_wait_ms": {b: _stats(per_branch[b]["route_wait_observed"]) for b in branches}}
    return profile, pools, measured_drops


# --------------------------------------------------------------------------- simulation


def _quantile(values, q):
    ordered = sorted(values)
    return ordered[math.ceil(q * len(ordered)) - 1] if ordered else None


def replica_seed(comparison_id, replica):
    digest = hashlib.sha256(f"{SEED}:{comparison_id}:{replica}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def simulate_replica(plan, rate, topology, pools, rng):
    """One replica of the frozen model; returns per measured frame/branch outcomes."""
    branches = plan["branches"]
    deadline_ms = plan["phases"]["deadline_ns"] / 1e6
    events, seq = [], [0]

    def push(when, kind, payload):
        seq[0] += 1
        heapq.heappush(events, (when, seq[0], kind, payload))

    frames, last = {}, 0.0
    for stream in range(6):
        for row in stream_schedule(plan, stream, rate):
            if row["planned"]:
                when = row["schedule_offset_ns"] / 1e6
                last = max(last, when)
                frames[row["input_frame_key"]] = {"arrival": when, "measured": row["measurement"], "stream": stream,
                                                  "outcome": {}}
                push(when, "frame", (stream, row["input_frame_key"]))
    end_ms = last + plan["phases"]["drain_ns"] / 1e6
    prefix_servers = {}   # process -> {"busy": bool, "waiting": [keys]}
    probes = {}           # (stream, branch) -> {"busy": bool, "waiting": [keys]}
    route_queue = {b: [] for b in branches}
    route_busy = {b: False for b in branches}

    def processes(stream):
        return [(stream, "shared")] if topology == "shared" else [(stream, b) for b in branches]

    def prefix_pool(process):
        return pools["prefix"]["shared" if topology == "shared" else process[1]]

    def start_prefix(process, key, now):
        prefix_servers[process]["busy"] = True
        push(now + rng.choice(prefix_pool(process)), "prefix_done", (process, key))

    def start_request(stream, branch, key, now):
        probes[stream, branch]["busy"] = True
        sample = rng.choice(pools["tuples"][branch])
        probe_pre, native_wait, bridge_pre, route_hold, bridge_post = sample
        push(now + probe_pre + native_wait + bridge_pre, "route_arrival",
             (stream, branch, key, route_hold, bridge_post))

    def arrive_analytics(stream, branch, key, now):
        probe = probes.setdefault((stream, branch), {"busy": False, "waiting": []})
        if not probe["busy"]:
            start_request(stream, branch, key, now)
        elif len(probe["waiting"]) < ANALYTICS_QUEUE_CAPACITY:
            probe["waiting"].append(key)
        else:
            frames[key]["outcome"][branch] = ("dropped", ANALYTICS_DROP)

    route_waits = {b: [] for b in branches}

    def start_route(branch, now):
        stream, _, key, route_hold, bridge_post, arrived = route_queue[branch].pop(0)
        route_busy[branch] = True
        if frames[key]["measured"]:
            route_waits[branch].append(now - arrived)
        push(now + route_hold, "route_done", (stream, branch, key, bridge_post))

    while events:
        now, _, kind, payload = heapq.heappop(events)
        if kind == "frame":
            stream, key = payload
            for process in processes(stream):
                server = prefix_servers.setdefault(process, {"busy": False, "waiting": []})
                if not server["busy"]:
                    start_prefix(process, key, now)
                elif len(server["waiting"]) < PREFIX_QUEUE_CAPACITY:
                    server["waiting"].append(key)
                else:
                    for branch in (branches if topology == "shared" else [process[1]]):
                        frames[key]["outcome"][branch] = ("dropped", PREFIX_DROP)
        elif kind == "prefix_done":
            process, key = payload
            stream = frames[key]["stream"]
            for branch in (branches if topology == "shared" else [process[1]]):
                arrive_analytics(stream, branch, key, now)
            server = prefix_servers[process]
            server["busy"] = False
            if server["waiting"]:
                start_prefix(process, server["waiting"].pop(0), now)
        elif kind == "route_arrival":
            stream, branch, key, route_hold, bridge_post = payload
            route_queue[branch].append(payload + (now,))
            if not route_busy[branch]:
                start_route(branch, now)
        elif kind == "route_done":
            stream, branch, key, bridge_post = payload
            route_busy[branch] = False
            if route_queue[branch]:
                start_route(branch, now)
            push(now + bridge_post, "request_done", (stream, branch, key))
        elif kind == "request_done":
            stream, branch, key = payload
            latency = now - frames[key]["arrival"]
            frames[key]["outcome"][branch] = (("completed", latency) if now <= end_ms else ("censored", None))
            probe = probes[stream, branch]
            probe["busy"] = False
            if probe["waiting"]:
                start_request(stream, branch, probe["waiting"].pop(0), now)
    planned = on_time = 0
    dropped = {r: 0 for r in DROP_REASONS}
    latencies = []
    for frame in frames.values():
        if not frame["measured"]:
            continue
        planned += 1
        outcomes = [frame["outcome"].get(b, ("censored", None)) for b in branches]
        for status, detail in outcomes:
            if status == "dropped":
                dropped[detail] += 1
        if all(status == "completed" for status, _ in outcomes):
            critical = max(detail for _, detail in outcomes)
            latencies.append(critical)
            on_time += critical <= deadline_ms
    branch_planned = 4 * planned
    return {"planned_frames": planned, "Y100_frame": on_time / planned if planned else None,
            "drop_fraction": sum(dropped.values()) / branch_planned if branch_planned else None,
            "drop_fraction_by_reason": {r: dropped[r] / branch_planned for r in DROP_REASONS} if branch_planned else None,
            "completed_frames": len(latencies),
            "p50": _quantile(latencies, .50), "p95": _quantile(latencies, .95),
            "route_wait_p50": {b: _quantile(route_waits[b], .50) for b in branches}}


def predict(plan, comparison_id, target_arm, pools, replicas=None):
    replicas = REPLICAS if replicas is None else replicas
    topology = target_arm["topology"]
    empty = [f"prefix:{name}" for name, pool in pools["prefix"].items() if not pool]
    empty += [f"tuples:{b}" for b, pool in pools["tuples"].items() if not pool]
    if empty:
        return None, "empty calibration pool: " + ", ".join(sorted(empty))
    runs = [simulate_replica(plan, target_arm["rate"], topology, pools,
                             random.Random(replica_seed(comparison_id, replica))) for replica in range(replicas)]
    planned = {r["planned_frames"] for r in runs}
    _require(len(planned) == 1, "replica planned frame count drift")

    def summary(values):
        return {"mean": statistics.fmean(values), "interval_2_5": _quantile(values, .025),
                "interval_97_5": _quantile(values, .975)} if values else None

    p50s = [r["p50"] for r in runs if r["p50"] is not None]
    return {
        "planned_frames": planned.pop(), "replicas": replicas,
        "Y100_frame": summary([r["Y100_frame"] for r in runs]),
        "drop_fraction": summary([r["drop_fraction"] for r in runs]),
        "drop_fraction_by_reason": {reason: summary([r["drop_fraction_by_reason"][reason] for r in runs])
                                    for reason in DROP_REASONS},
        "completed_frames": summary([r["completed_frames"] for r in runs]),
        "p50_ms": summary(p50s), "p95_ms": summary([r["p95"] for r in runs if r["p95"] is not None]),
        "p50_defined_replicas": len(p50s),
        "route_wait_p50_ms": {b: summary([r["route_wait_p50"][b] for r in runs if r["route_wait_p50"][b] is not None])
                              for b in plan["branches"]},
    }, None


# --------------------------------------------------------------------------- validation and gates


def observed_metrics(reduction, measured_drops):
    branches = reduction["branches"]
    return {"planned_frames": reduction["frames"]["N_planned"], "Y100_frame": reduction["Y100_frame"],
            "drop_fraction": branches["N_controlled_dropped"] / branches["N_planned"],
            "drop_fraction_by_reason": {r: measured_drops[r] / branches["N_planned"] for r in DROP_REASONS},
            "completed_frames": reduction["frames"]["N_completed"],
            "p50_ms": reduction["completed_frame_latency_ms"]["p50"],
            "p95_ms": reduction["completed_frame_latency_ms"]["p95"]}


def evaluate(observed, predicted, reason):
    """Spec thresholds; returns (pass, failures, deltas)."""
    if predicted is None:
        return False, ["prediction null: " + reason], None
    _require(predicted["planned_frames"] == observed["planned_frames"], "predicted/observed planned frames differ")
    deltas = {"Y100_frame": predicted["Y100_frame"]["mean"] - observed["Y100_frame"],
              "drop_fraction": predicted["drop_fraction"]["mean"] - observed["drop_fraction"],
              "p50_ms": (predicted["p50_ms"]["mean"] - observed["p50_ms"]
                         if predicted["p50_ms"] is not None and observed["p50_ms"] is not None else None)}
    failures = []
    if abs(deltas["Y100_frame"]) > 0.05:
        failures.append("Y100_frame")
    if abs(deltas["drop_fraction"]) > 0.05:
        failures.append("drop_fraction")
    if observed["completed_frames"] <= 0:
        failures.append("observed_completed_frames_zero")
    if predicted["p50_defined_replicas"] != predicted["replicas"]:
        failures.append("p50_undefined_in_some_replicas")
    if deltas["p50_ms"] is None or abs(deltas["p50_ms"]) > max(10.0, 0.10 * observed["p50_ms"]):
        failures.append("p50_ms")
    return not failures, failures, deltas


def comparison_plan(plan):
    """Groups (a) in-sample, (b) rate 1<->2 load extrapolation, (c) r1<->r2 cross-repeat."""
    arms = {(a["repeat"], a["resource"], a["rate"], a["topology"]): a for a in plan["arms"]}
    result = [("a", a, a) for a in plan["arms"]]
    for repeat in (1, 2):
        for resource in ("cpu", "gpu"):
            for topology in ("baseline", "shared"):
                for source, target in (("1", "2"), ("2", "1")):
                    result.append(("b", arms[repeat, resource, source, topology], arms[repeat, resource, target, topology]))
    for resource in ("cpu", "gpu"):
        for topology in ("baseline", "shared"):
            for rate in ("0.25", "1", "2"):
                for source, target in ((1, 2), (2, 1)):
                    result.append(("c", arms[source, resource, rate, topology], arms[target, resource, rate, topology]))
    return result


def gates(comparisons, arms=()):
    def failures(resource):
        return sorted(c["comparison_id"] for c in comparisons
                      if c["group"] in ("a", "b") and c["resource"] == resource and not c["pass"])
    counts = {(r, g): sum(1 for c in comparisons if c["resource"] == r and c["group"] == g)
              for r in ("cpu", "gpu") for g in ("a", "b")}
    _require(counts == {("cpu", "a"): 12, ("cpu", "b"): 8, ("gpu", "a"): 12, ("gpu", "b"): 8},
             "gate group composition drifted")
    gpu, cpu = failures("gpu"), failures("cpu")
    gpu_ok = not gpu
    queue_ok = gpu_ok and not cpu
    permitted = []
    if gpu_ok:
        permitted += [{"use": "GPU component distributions", "arm": a["arm_id"]} for a in arms
                      if a["resource"] == "gpu" and a["rate"] in ("1", "2")]
    if queue_ok:
        permitted += [{"use": "predicted waits and drops", "arm": a["arm_id"]} for a in arms
                      if a["rate"] in ("1", "2")]
    return {"gpu_latency_profile_use_permitted": gpu_ok, "queueing_extrapolation_use_permitted": queue_ok,
            "gpu_failed_comparisons": gpu, "cpu_failed_comparisons": cpu, "permitted_uses": permitted,
            "expected_cpu_gate_brittleness": CPU_GATE_NOTE}


# --------------------------------------------------------------------------- orchestration


def run_model(binding_descriptor, archive_path, pins, *, deadline, analysis_deadline_seconds, source_commit,
              replicas=None):
    """Full pipeline; any refusal raises before a report exists."""
    replicas = REPLICAS if replicas is None else replicas
    _deadline(deadline)
    _require(type(source_commit) is str and len(source_commit) == 40
             and all(c in "0123456789abcdef" for c in source_commit), "source commit must be a 40-hex SHA")
    _require(binding_descriptor["size_bytes"] == pins["binding"]["size_bytes"]
             and binding_descriptor["sha256"] == pins["binding"]["sha256"], "binding is not the pinned study binding")
    observations, descriptors = [], []
    binding = read_closed_rows(binding_descriptor, max_bytes=MAX_DOCUMENT_BYTES, deadline=deadline,
                               document=True, observations=observations)
    archive = load_archive(archive_path, pins["archive"], observations)
    _require(archive.get("binding") == binding_descriptor, "archive binding differs from the read binding")
    archived_arms = archive["reduction"]["arms"]
    plan, profiles, pools, observed = None, {}, {}, {}
    for arm, raw in iter_closed_arms(binding, deadline, observations, descriptors):
        if arm == "plan":
            plan = raw
            continue
        reduction = reduce_arm(plan, arm["arm_id"], raw, deadline=deadline)
        _require(arm["arm_id"] in archived_arms and canonical(reduction) == canonical(archived_arms[arm["arm_id"]]),
                 "recomputed arm reduction differs from archive: " + arm["arm_id"])
        profile, arm_pools, drops = arm_profile(plan, arm, raw)
        _require(profile["counts"]["measured_completed"] == reduction["branches"]["N_completed"],
                 "profile population differs from reducer completed branches")
        _require(sum(drops.values()) == reduction["branches"]["N_controlled_dropped"],
                 "drop reasons differ from reducer controlled drops")
        profiles[arm["arm_id"]], pools[arm["arm_id"]] = profile, arm_pools
        observed[arm["arm_id"]] = observed_metrics(reduction, drops)
    _require(descriptors == archive["reduction"].get("closed_input_descriptors"),
             "read descriptors differ from archived closed_input_descriptors")
    comparisons = []
    for group, calibration, target in comparison_plan(plan):
        _deadline(deadline)
        comparison_id = f"{group}:{calibration['arm_id']}->{target['arm_id']}"
        predicted, reason = predict(plan, comparison_id, target, pools[calibration["arm_id"]], replicas)
        passed, failures, deltas = evaluate(observed[target["arm_id"]], predicted, reason)
        comparisons.append({"comparison_id": comparison_id, "group": group, "resource": target["resource"],
                            "calibration_arm": calibration["arm_id"], "target_arm": target["arm_id"],
                            "observed": observed[target["arm_id"]], "predicted": predicted,
                            "null_reason": reason, "deltas": deltas, "pass": passed, "failures": failures})
    arms = {(a["repeat"], a["resource"], a["rate"], a["topology"]): a["arm_id"] for a in plan["arms"]}
    hold_025 = []
    for (repeat, resource, rate, topology), arm_id in sorted(arms.items()):
        if rate == "0.25":
            reference = arms[repeat, resource, "1", topology]
            hold_025.append({"arm": arm_id, "reference_rate_1_arm": reference, "route_hold_p50_ms": {
                b: {"rate_0_25": profiles[arm_id]["per_branch"][b]["components"]["route_hold"]["p50"],
                    "rate_1": profiles[reference]["per_branch"][b]["components"]["route_hold"]["p50"]}
                for b in plan["branches"]}, "cause": "not inferred"})
    _recheck_named(observations, deadline)
    report = {
        "kind": KIND, "model_schema_version": MODEL_SCHEMA_VERSION, "label": LABEL,
        "new_descriptive_read_not_rereduction": True,
        **{flag: False for flag in ELIGIBILITY},
        "inputs": {"binding": binding_descriptor, "archive": dict(pins["archive"], path=str(archive_path)),
                   "plan_sha256": plan["sha256"], "bundle_sha256": plan["bundle_sha256"],
                   "final_variant": binding["final_variant"], "closed_input_descriptors": descriptors},
        "analysis_deadline_seconds": analysis_deadline_seconds,
        "implementation": {"module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           "source_commit": source_commit},
        "model": {"seed": SEED, "replicas": replicas, "analytics_queue_capacity": ANALYTICS_QUEUE_CAPACITY,
                  "prefix_queue_capacity": PREFIX_QUEUE_CAPACITY, "capacity_source_commit": K_SOURCE_COMMIT,
                  "prefix_unqueued_gap_ms": UNQUEUED_GAP_MS, "sum_tolerance_ms": SUM_TOLERANCE_MS,
                  "components": list(COMPONENTS), "tuple_components": list(TUPLE_COMPONENTS),
                  "arrival_rows": ARRIVAL_ROWS, "censor_at": CENSOR_AT, "seed_rule": SEED_RULE,
                  "unmodelled_factors": list(UNMODELLED_FACTORS)},
        "profiles": profiles, "observed": observed, "comparisons": comparisons,
        "route_hold_rate_0_25_vs_1": hold_025, "gates": gates(comparisons, plan["arms"]),
    }
    _require("artifact_kind" not in report, "report must not carry artifact_kind")
    return report


def report_bytes(report):
    return (canonical(report) + "\n").encode("ascii")


def write_report_exclusive(path, body):
    """Write a sibling temporary file, then hard-link it to the new name; a failure leaves no report."""
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "report path must be absolute")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{path.name}.{os.getpid()}.partial"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            offset = 0
            while offset < len(body):
                written = os.write(fd, body[offset:offset + 1024 * 1024])
                _require(written > 0, "report write made no progress")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError as exc:
            raise ModelError("report path already exists") from exc
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, choices=sorted(KNOWN_STUDIES))
    parser.add_argument("--binding", required=True, help="Absolute path of the closed-inputs binding.")
    parser.add_argument("--archive", required=True, help="Absolute path of the archived study results (.json.gz).")
    parser.add_argument("--output", required=True, help="New report path (exclusive create).")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--analysis-deadline-seconds", type=int, default=MAX_ANALYSIS_DEADLINE_S)
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        _require(0 < args.analysis_deadline_seconds <= MAX_ANALYSIS_DEADLINE_S, "analysis deadline bound")
        deadline = started + args.analysis_deadline_seconds
        pins = KNOWN_STUDIES[args.study]
        binding = dict(pins["binding"], path=args.binding)
        report = run_model({"path": binding["path"], "size_bytes": binding["size_bytes"],
                            "sha256": binding["sha256"]}, Path(args.archive), pins, deadline=deadline,
                           analysis_deadline_seconds=args.analysis_deadline_seconds, source_commit=args.source_commit)
        body = report_bytes(report)
        _deadline(deadline)
        write_report_exclusive(Path(args.output), body)
        print(json.dumps({"report": {"path": args.output, "size_bytes": len(body),
                                     "sha256": hashlib.sha256(body).hexdigest()},
                          "elapsed_s": time.monotonic() - started,
                          "gates": {k: report["gates"][k] for k in
                                    ("gpu_latency_profile_use_permitted", "queueing_extrapolation_use_permitted")}},
                         separators=(",", ":")))
        return 0
    except (ReductionError, OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__ + ": " + str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
