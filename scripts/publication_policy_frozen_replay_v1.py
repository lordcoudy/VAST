"""Frozen input/equation replay without capability grants or project imports.

Manifest-aware callers must separately validate actual native capabilities. This
dependency leaf shares the unchanged v1 equations with the live policy engine.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Mapping

ANALYTICS_BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
POLICIES = ("cpu_only", "gpu_only", "static_hybrid", "heft", "deadline_aware_heft", "queue_aware_edf", "adaptive_weights")
PUBLISHABLE_SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
ENGINE_IMPLEMENTATION_ID = "vast-publication-policy-engine-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{7,}$")
_PLACEHOLDER_IDS = {"cpu", "gpu", "native", "unknown", "unavailable", "label_only", "derived", "placeholder"}
DECISION_FIELDS_V1 = frozenset({
    "schema_version", "artifact_kind", "policy_contract_sha256", "engine_implementation_id",
    "policy_scope", "policy", "system", "arm_id", "decision_id", "decision_seq", "trace_id",
    "branch", "request", "state_before", "static_hybrid_map_sha256", "static_hybrid_placement",
    "evaluations", "selected_resource", "selected_implementation_id", "reason", "record_status",
    "native_decision_evidence", "sha256",
})
FEEDBACK_FIELDS_V1 = frozenset({
    "schema_version", "artifact_kind", "policy_contract_sha256", "engine_implementation_id", "policy",
    "system", "arm_id", "decision_id", "actual_service_ms", "completed_at_ms", "deadline_ms", "outcome",
    "state_before", "state_after", "sha256",
})


class FrozenPolicyReplayError(ValueError):
    """Frozen mathematical inputs, hashes or state transitions are inconsistent."""


def canonical_json_v1(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise FrozenPolicyReplayError("policy artifact is not canonical JSON") from exc


def payload_with_sha256_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result.pop("sha256", None)
    result["sha256"] = hashlib.sha256(canonical_json_v1(result)).hexdigest()
    return result


def require_record_sha256_v1(record: Mapping[str, Any]) -> None:
    if not isinstance(record, Mapping):
        raise FrozenPolicyReplayError("record must be an object")
    digest = record.get("sha256")
    if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
        raise FrozenPolicyReplayError("record sha256 is invalid")
    if payload_with_sha256_v1(record)["sha256"] != digest:
        raise FrozenPolicyReplayError("record sha256 mismatch")


def _real_id(value: Any) -> bool:
    return type(value) is str and bool(_REAL_ID_RE.fullmatch(value)) and value.lower() not in _PLACEHOLDER_IDS


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise FrozenPolicyReplayError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FrozenPolicyReplayError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise FrozenPolicyReplayError(f"{name} must be finite")
    return number


def _nonnegative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise FrozenPolicyReplayError(f"{name} must be nonnegative")
    return number


def _positive(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number <= 0.0:
        raise FrozenPolicyReplayError(f"{name} must be positive")
    return number


def initial_frozen_state_v1(arm_id: str) -> dict[str, Any]:
    if not _real_id(arm_id):
        raise FrozenPolicyReplayError("arm_id must be a real stable ID")
    return {"arm_id": arm_id, "weights": {"cpu": 1.0, "gpu": 1.0}, "service_ewma_ms": {}}


def validate_frozen_state_v1(state: Mapping[str, Any], arm_id: str) -> None:
    if not isinstance(state, Mapping) or set(state) != {"arm_id", "weights", "service_ewma_ms"}:
        raise FrozenPolicyReplayError("state fields have drifted")
    if state["arm_id"] != arm_id or not _real_id(arm_id):
        raise FrozenPolicyReplayError("state arm_id mismatch")
    weights = state["weights"]
    if not isinstance(weights, Mapping) or set(weights) != set(RESOURCES):
        raise FrozenPolicyReplayError("adaptive state weights have drifted")
    for resource, weight in weights.items():
        if not 0.5 <= _finite(weight, f"weight.{resource}") <= 1.5:
            raise FrozenPolicyReplayError("adaptive weight is outside frozen bounds")
    ewma = state["service_ewma_ms"]
    if not isinstance(ewma, Mapping) or set(ewma) - set(ANALYTICS_BRANCHES):
        raise FrozenPolicyReplayError("adaptive EWMA state has drifted")
    for branch, values in ewma.items():
        if not isinstance(values, Mapping) or not values or set(values) - set(RESOURCES):
            raise FrozenPolicyReplayError("adaptive branch EWMA state has drifted")
        for resource, value in values.items():
            _positive(value, f"EWMA.{branch}.{resource}")


def replay_frozen_decision_v1(record: Mapping[str, Any], *,
                              expected_policy_contract_sha256: str | None = None,
                              expected_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Strict input/equation replay; this function does not grant capabilities."""
    require_record_sha256_v1(record)
    if set(record) != DECISION_FIELDS_V1:
        raise FrozenPolicyReplayError("decision record fields have drifted")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise FrozenPolicyReplayError("decision record schema_version has drifted")
    if record["artifact_kind"] != "vast_publication_policy_decision":
        raise FrozenPolicyReplayError("decision record artifact_kind has drifted")
    contract = record["policy_contract_sha256"]
    if type(contract) is not str or not _SHA256_RE.fullmatch(contract):
        raise FrozenPolicyReplayError("decision record policy contract is invalid")
    if expected_policy_contract_sha256 is not None and contract != expected_policy_contract_sha256:
        raise FrozenPolicyReplayError("decision record policy contract has drifted")
    if record["engine_implementation_id"] != ENGINE_IMPLEMENTATION_ID or record["policy_scope"] != "analytics_only":
        raise FrozenPolicyReplayError("decision record engine/scope has drifted")
    policy = record["policy"]
    if policy not in POLICIES or record["system"] not in PUBLISHABLE_SYSTEMS:
        raise FrozenPolicyReplayError("decision policy/system is invalid")
    request = normalize_frozen_request_v1(record["request"])
    if canonical_json_v1(request) != canonical_json_v1(record["request"]):
        raise FrozenPolicyReplayError("decision request is not normalized")
    for field in ("decision_id", "decision_seq", "trace_id", "branch"):
        if record[field] != request[field] or type(record[field]) is not type(request[field]):
            raise FrozenPolicyReplayError(f"{field} does not match request")
    state = record["state_before"]
    validate_frozen_state_v1(state, record["arm_id"])
    if expected_state is not None and canonical_json_v1(state) != canonical_json_v1(expected_state):
        raise FrozenPolicyReplayError("decision state_before differs from actual history")
    if policy != "adaptive_weights" and canonical_json_v1(state) != canonical_json_v1(initial_frozen_state_v1(record["arm_id"])):
        raise FrozenPolicyReplayError("non-adaptive decision state is not the original reset")
    placement = record["static_hybrid_placement"]
    if policy == "static_hybrid":
        if not isinstance(placement, Mapping) or set(placement) != set(ANALYTICS_BRANCHES) or set(placement.values()) != set(RESOURCES):
            raise FrozenPolicyReplayError("static_hybrid placement has drifted")
        if type(record["static_hybrid_map_sha256"]) is not str or not _SHA256_RE.fullmatch(record["static_hybrid_map_sha256"]):
            raise FrozenPolicyReplayError("static_hybrid map hash is invalid")
    elif placement is not None or record["static_hybrid_map_sha256"] is not None:
        raise FrozenPolicyReplayError("non-static decision contains static placement")
    result = evaluate_frozen_policy_v1(policy, request, static_placement=placement, state_before=state)
    actual = {field: record[field] for field in result}
    if canonical_json_v1(result) != canonical_json_v1(actual):
        raise FrozenPolicyReplayError("replayed decision does not match recorded output")
    status = record["record_status"]
    if status == "replayable_not_runtime_accepted":
        if record["native_decision_evidence"] is not None:
            raise FrozenPolicyReplayError("issued decision contains native evidence")
    elif status == "accepted_native_runtime_decision":
        evidence = record["native_decision_evidence"]
        if not isinstance(evidence, Mapping):
            raise FrozenPolicyReplayError("accepted decision has no native evidence")
        for field in ("decision_id", "system", "branch", "selected_resource"):
            if evidence.get(field) != record[field]:
                raise FrozenPolicyReplayError(f"native evidence {field} mismatch")
        if evidence.get("implementation_id") != record["selected_implementation_id"] or evidence.get("telemetry_source") != "native":
            raise FrozenPolicyReplayError("native implementation/source mismatch")
        if not _real_id(evidence.get("event_id")) or not _real_id(evidence.get("emitter_id")) or not _SHA256_RE.fullmatch(str(evidence.get("emitter_sha256", ""))):
            raise FrozenPolicyReplayError("native event/emitter identity is invalid")
    else:
        raise FrozenPolicyReplayError("decision record status is invalid")
    return result


def advance_frozen_feedback_v1(decision_record: Mapping[str, Any], state_before: Mapping[str, Any], *,
                               actual_service_ms: float, completed_at_ms: float) -> dict[str, Any]:
    """Apply the unchanged adaptive v1 transition to an original issued decision."""
    if decision_record.get("policy") != "adaptive_weights":
        raise FrozenPolicyReplayError("feedback is defined only for adaptive_weights")
    validate_frozen_state_v1(state_before, str(decision_record["arm_id"]))
    actual = _positive(actual_service_ms, "actual_service_ms")
    completed = _nonnegative(completed_at_ms, "completed_at_ms")
    state_after = copy.deepcopy(dict(state_before))
    branch = str(decision_record["branch"])
    resource = str(decision_record["selected_resource"])
    branch_state = state_after["service_ewma_ms"].setdefault(branch, {})
    previous = branch_state.get(resource)
    branch_state[resource] = actual if previous is None else 0.1 * actual + 0.9 * previous
    deadline = float(decision_record["request"]["deadline_ms"])
    late = completed > deadline
    delta = 0.002 if late else -0.0002
    state_after["weights"][resource] = min(1.5, max(0.5, state_after["weights"][resource] + delta))
    return payload_with_sha256_v1({
        "schema_version": 1, "artifact_kind": "vast_publication_policy_feedback",
        "policy_contract_sha256": decision_record["policy_contract_sha256"],
        "engine_implementation_id": ENGINE_IMPLEMENTATION_ID, "policy": "adaptive_weights",
        "system": decision_record["system"], "arm_id": decision_record["arm_id"],
        "decision_id": decision_record["decision_id"], "actual_service_ms": actual,
        "completed_at_ms": completed, "deadline_ms": deadline, "outcome": "late" if late else "on_time",
        "state_before": copy.deepcopy(dict(state_before)), "state_after": state_after,
    })


def validate_frozen_feedback_v1(feedback: Mapping[str, Any], decision: Mapping[str, Any],
                               state_before: Mapping[str, Any]) -> dict[str, Any]:
    require_record_sha256_v1(feedback)
    if set(feedback) != FEEDBACK_FIELDS_V1:
        raise FrozenPolicyReplayError("feedback record fields have drifted")
    expected = advance_frozen_feedback_v1(decision, state_before,
        actual_service_ms=feedback["actual_service_ms"], completed_at_ms=feedback["completed_at_ms"])
    if canonical_json_v1(feedback) != canonical_json_v1(expected):
        raise FrozenPolicyReplayError("feedback state/order/output differs from frozen transition")
    return copy.deepcopy(expected["state_after"])


def normalize_frozen_request_v1(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise FrozenPolicyReplayError("decision request must be an object")
    expected = {
        "decision_id",
        "decision_seq",
        "trace_id",
        "branch",
        "arrival_ms",
        "decision_time_ms",
        "deadline_ms",
        "rank_u_ms",
        "candidates",
    }
    if set(request) != expected:
        raise FrozenPolicyReplayError("decision request fields have drifted")
    decision_id = str(request.get("decision_id", ""))
    trace_id = str(request.get("trace_id", ""))
    if not _real_id(decision_id) or not _real_id(trace_id):
        raise FrozenPolicyReplayError("decision_id and trace_id must be real stable IDs")
    decision_seq = request.get("decision_seq")
    if isinstance(decision_seq, bool) or not isinstance(decision_seq, int) or decision_seq <= 0:
        raise FrozenPolicyReplayError("decision_seq must be a positive integer")
    branch = str(request.get("branch", ""))
    if branch not in ANALYTICS_BRANCHES:
        raise FrozenPolicyReplayError("decision branch is outside policy_scope=analytics_only")
    candidates = request.get("candidates")
    if not isinstance(candidates, Mapping) or set(candidates) != set(RESOURCES):
        raise FrozenPolicyReplayError("decision candidates must contain exactly cpu and gpu")

    normalized_candidates: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        candidate = candidates.get(resource)
        fields = {
            "allowed",
            "implementation_id",
            "available_ms",
            "queue_depth",
            "estimated_service_ms",
            "transfer_ms",
        }
        if not isinstance(candidate, Mapping) or set(candidate) != fields:
            raise FrozenPolicyReplayError(f"{resource} candidate fields have drifted")
        if not isinstance(candidate.get("allowed"), bool):
            raise FrozenPolicyReplayError(f"{resource}.allowed must be boolean")
        expected_id = candidate.get("implementation_id")
        if not _real_id(expected_id):
            raise FrozenPolicyReplayError(f"{resource} implementation_id is invalid")
        queue_depth = candidate.get("queue_depth")
        if isinstance(queue_depth, bool) or not isinstance(queue_depth, int) or queue_depth < 0:
            raise FrozenPolicyReplayError(f"{resource}.queue_depth must be a nonnegative integer")
        normalized_candidates[resource] = {
            "allowed": candidate["allowed"],
            "implementation_id": expected_id,
            "available_ms": _nonnegative(candidate.get("available_ms"), f"{resource}.available_ms"),
            "queue_depth": queue_depth,
            "estimated_service_ms": _positive(
                candidate.get("estimated_service_ms"), f"{resource}.estimated_service_ms"
            ),
            "transfer_ms": _nonnegative(candidate.get("transfer_ms"), f"{resource}.transfer_ms"),
        }

    return {
        "decision_id": decision_id,
        "decision_seq": decision_seq,
        "trace_id": trace_id,
        "branch": branch,
        "arrival_ms": _nonnegative(request.get("arrival_ms"), "arrival_ms"),
        "decision_time_ms": _nonnegative(request.get("decision_time_ms"), "decision_time_ms"),
        "deadline_ms": _positive(request.get("deadline_ms"), "deadline_ms"),
        "rank_u_ms": _nonnegative(request.get("rank_u_ms"), "rank_u_ms"),
        "candidates": normalized_candidates,
    }


def evaluate_frozen_policy_v1(
    policy: str,
    request: Mapping[str, Any],
    *,
    static_placement: Mapping[str, str] | None,
    state_before: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = request["candidates"]
    decision_time = float(request["decision_time_ms"])
    deadline = float(request["deadline_ms"])
    branch = str(request["branch"])
    resource_index = {resource: index for index, resource in enumerate(RESOURCES)}
    evaluations: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        candidate = candidates[resource]
        start = max(decision_time, float(candidate["available_ms"]))
        service = float(candidate["estimated_service_ms"])
        transfer = float(candidate["transfer_ms"])
        finish = start + service + transfer
        evaluations[resource] = {
            "allowed": bool(candidate["allowed"]),
            "implementation_id": str(candidate["implementation_id"]),
            "available_ms": float(candidate["available_ms"]),
            "queue_depth": int(candidate["queue_depth"]),
            "estimated_service_ms": service,
            "transfer_ms": transfer,
            "predicted_start_ms": start,
            "predicted_finish_ms": finish,
            "predicted_lateness_ms": max(0.0, finish - deadline),
        }

    allowed = [resource for resource in RESOURCES if evaluations[resource]["allowed"]]
    if not allowed:
        raise FrozenPolicyReplayError("decision has no allowed real execution resource")

    def tie_tail(resource: str) -> tuple[Any, ...]:
        value = evaluations[resource]
        return (value["transfer_ms"], value["queue_depth"], resource_index[resource])

    if policy in {"cpu_only", "gpu_only"}:
        selected = "cpu" if policy == "cpu_only" else "gpu"
        if selected not in allowed:
            raise FrozenPolicyReplayError(f"{policy} required resource is not allowed")
        reason = "forced_policy_resource"
    elif policy == "static_hybrid":
        if static_placement is None:
            raise FrozenPolicyReplayError("static_hybrid placement is missing")
        selected = str(static_placement[branch])
        if selected not in allowed:
            raise FrozenPolicyReplayError("static_hybrid selected resource is not allowed")
        reason = "frozen_calibrated_mixed_map"
    elif policy == "heft":
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["predicted_finish_ms"],) + tie_tail(resource),
        )
        reason = "minimum_earliest_finish_time"
    elif policy == "deadline_aware_heft":
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["predicted_finish_ms"] > deadline,
                evaluations[resource]["predicted_lateness_ms"],
                evaluations[resource]["predicted_finish_ms"],
            )
            + tie_tail(resource),
        )
        reason = (
            "minimum_feasible_finish_time"
            if evaluations[selected]["predicted_finish_ms"] <= deadline
            else "minimum_predicted_lateness"
        )
    elif policy == "queue_aware_edf":
        for resource in RESOURCES:
            value = evaluations[resource]
            value["queue_completion_ms"] = max(
                decision_time, float(value["available_ms"])
            ) + (value["queue_depth"] + 1) * value["estimated_service_ms"] + value["transfer_ms"]
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["queue_completion_ms"],) + tie_tail(resource),
        )
        reason = "edf_task_minimum_queue_completion"
    elif policy == "adaptive_weights":
        weights = state_before.get("weights")
        ewma = state_before.get("service_ewma_ms")
        if not isinstance(weights, Mapping) or set(weights) != set(RESOURCES):
            raise FrozenPolicyReplayError("adaptive state weights have drifted")
        if not isinstance(ewma, Mapping):
            raise FrozenPolicyReplayError("adaptive EWMA state has drifted")
        branch_ewma = ewma.get(branch, {})
        if not isinstance(branch_ewma, Mapping):
            raise FrozenPolicyReplayError("adaptive branch EWMA state has drifted")
        for resource in RESOURCES:
            value = evaluations[resource]
            service_basis = float(
                branch_ewma.get(resource, value["estimated_service_ms"])
            )
            weight = float(weights[resource])
            value["service_basis_ms"] = service_basis
            value["adaptive_weight"] = weight
            value["adaptive_score_ms"] = (
                (value["queue_depth"] + 1) * service_basis * weight
                + value["transfer_ms"]
            )
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["adaptive_score_ms"],) + tie_tail(resource),
        )
        reason = "minimum_bounded_queue_ewma_cost"
    else:
        raise FrozenPolicyReplayError(f"unknown policy: {policy}")

    return {
        "evaluations": evaluations,
        "selected_resource": selected,
        "selected_implementation_id": evaluations[selected]["implementation_id"],
        "reason": reason,
    }
