#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


RESOURCE_ORDER = ("cpu", "gpu", "nvdec")
REFERENCE_IMPLEMENTATION_ID = "formal-aw-heft-reference-v1"
REFERENCE_STATUS = "reference_only_not_runtime_bound"
FORMAL_TRACE_CONTRACT_VERSION = 1
FORMAL_REPLAY_NUMERIC_TOLERANCE = 1.0e-9
FORMAL_REPLAY_STATUS = "formal_reference_replay_verified_input_not_accepted"
FORMAL_REPLAY_EVIDENCE_STATUS = "replay_input_only_not_accepted_telemetry"
FORMAL_POLICY_MODES = {"formal_frozen", "formal_online"}


class FormalAwHeftError(ValueError):
    pass


@dataclass(frozen=True)
class ReadyTask:
    stage_id: str
    rank_u_ms: float
    deadline_ms: float
    arrival_ms: float
    trace_id: str


@dataclass(frozen=True)
class ResourceCandidate:
    allowed: bool
    ready_ms: float
    available_ms: float
    queue_wait_ms: float
    communication_ms: float
    memory_ms: float
    execution_ms: float
    queue_depth: int


@dataclass(frozen=True)
class DecisionRequest:
    stage_id: str
    trace_id: str
    rank_u_ms: float
    decision_time_ms: float
    deadline_ms: float
    candidates: Mapping[str, ResourceCandidate]
    weights: Mapping[str, float]
    deadline_risk_lambda: float
    heavy_object_threshold: float
    heavy_gpu_bonus: float
    score_epsilon_ms: float
    resource_order: Sequence[str] = RESOURCE_ORDER
    object_feature: float | None = None
    object_feature_observed_at_ms: float | None = None
    object_feature_source: str = "unavailable"


@dataclass(frozen=True)
class ResourceFeedbackState:
    used: bool
    queue_depths: Sequence[int]
    queue_wait_ms: Sequence[float]
    history_bad: Sequence[bool]
    last_update_feedback_seq: int


@dataclass(frozen=True)
class FeedbackRequest:
    terminal_status: str
    latency_ms: float
    deadline_ms: float
    feedback_seq: int
    current_parameter_snapshot_seq: int
    source_decision_ids: Sequence[str]
    source_parameter_snapshot_seqs: Sequence[int]
    old_weights: Mapping[str, float]
    lower_bounds: Mapping[str, float]
    upper_bounds: Mapping[str, float]
    resource_states: Mapping[str, ResourceFeedbackState]
    overload_queue_thresholds: Mapping[str, int]
    stable_queue_thresholds: Mapping[str, int]
    overload_wait_fraction: float
    stable_wait_fraction: float
    history_length: int
    lag_limit: int
    cooldown_events: int
    penalty_step: float
    reward_step: float
    variation_before: float
    variation_budget: float
    updates_enabled: bool = True


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FormalAwHeftError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise FormalAwHeftError(f"{name} must be finite")
    return number


def _nonnegative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise FormalAwHeftError(f"{name} must be nonnegative")
    return number


def _validate_resource_keys(values: Mapping[str, Any], name: str) -> None:
    if set(values) != set(RESOURCE_ORDER):
        raise FormalAwHeftError(f"{name} must contain exactly cpu, gpu, and nvdec")


def compute_upward_ranks(
    execution_costs_ms: Mapping[str, Mapping[str, float]],
    successors: Mapping[str, Sequence[str]],
    communication_costs_ms: Mapping[tuple[str, str], Sequence[float]],
) -> dict[str, float]:
    """Compute HEFT upward ranks from versioned execution and edge profiles."""

    if not execution_costs_ms:
        raise FormalAwHeftError("execution_costs_ms must not be empty")
    nodes = set(execution_costs_ms)
    mean_execution: dict[str, float] = {}
    normalized_successors: dict[str, tuple[str, ...]] = {}
    mean_communication: dict[tuple[str, str], float] = {}

    for node, costs in execution_costs_ms.items():
        if not costs:
            raise FormalAwHeftError(f"stage {node} has no allowed execution resource")
        if not set(costs).issubset(RESOURCE_ORDER):
            raise FormalAwHeftError(f"stage {node} contains an unknown resource")
        values = [_nonnegative(value, f"execution_costs_ms[{node}]") for value in costs.values()]
        mean_execution[node] = sum(values) / len(values)

    for node in nodes:
        children = tuple(str(child) for child in successors.get(node, ()))
        if len(set(children)) != len(children):
            raise FormalAwHeftError(f"stage {node} contains duplicate successor edges")
        for child in children:
            if child not in nodes:
                raise FormalAwHeftError(f"stage {node} references unknown successor {child}")
            edge = (node, child)
            costs = communication_costs_ms.get(edge)
            if not costs:
                raise FormalAwHeftError(f"edge {node}->{child} has no compatible communication profile")
            values = [_nonnegative(value, f"communication_costs_ms[{node}->{child}]") for value in costs]
            mean_communication[edge] = sum(values) / len(values)
        normalized_successors[node] = children

    unexpected_edges = set(communication_costs_ms) - {
        (node, child)
        for node, children in normalized_successors.items()
        for child in children
    }
    if unexpected_edges:
        raise FormalAwHeftError("communication_costs_ms contains edges outside the DAG")

    state: dict[str, int] = {}
    ranks: dict[str, float] = {}

    def visit(node: str) -> float:
        marker = state.get(node, 0)
        if marker == 1:
            raise FormalAwHeftError("Video-DAG contains a cycle")
        if marker == 2:
            return ranks[node]
        state[node] = 1
        tail = 0.0
        if normalized_successors[node]:
            tail = max(
                mean_communication[(node, child)] + visit(child)
                for child in normalized_successors[node]
            )
        ranks[node] = mean_execution[node] + tail
        state[node] = 2
        return ranks[node]

    for node in sorted(nodes):
        visit(node)
    return ranks


def select_ready_task(tasks: Sequence[ReadyTask]) -> ReadyTask:
    """Select by descending rank, then deadline, arrival, trace, and stage ID."""

    if not tasks:
        raise FormalAwHeftError("ready task set must not be empty")
    for task in tasks:
        _nonnegative(task.rank_u_ms, f"rank_u_ms[{task.trace_id}]")
        _finite(task.deadline_ms, f"deadline_ms[{task.trace_id}]")
        _finite(task.arrival_ms, f"arrival_ms[{task.trace_id}]")
        if not task.trace_id or not task.stage_id:
            raise FormalAwHeftError("ready tasks require nonempty trace_id and stage_id")
    return min(
        tasks,
        key=lambda task: (
            -task.rank_u_ms,
            task.deadline_ms,
            task.arrival_ms,
            task.trace_id,
            task.stage_id,
        ),
    )


def evaluate_decision(request: DecisionRequest) -> dict[str, Any]:
    """Evaluate all CPU/GPU/NVDEC alternatives for one ready stage instance."""

    _validate_resource_keys(request.candidates, "candidates")
    _validate_resource_keys(request.weights, "weights")
    if set(request.resource_order) != set(RESOURCE_ORDER) or len(request.resource_order) != len(RESOURCE_ORDER):
        raise FormalAwHeftError("resource_order must be a permutation of cpu, gpu, and nvdec")
    if not request.stage_id or not request.trace_id:
        raise FormalAwHeftError("decision requires nonempty stage_id and trace_id")

    decision_time = _finite(request.decision_time_ms, "decision_time_ms")
    deadline = _finite(request.deadline_ms, "deadline_ms")
    rank_u = _nonnegative(request.rank_u_ms, "rank_u_ms")
    risk_lambda = _nonnegative(request.deadline_risk_lambda, "deadline_risk_lambda")
    threshold = _nonnegative(request.heavy_object_threshold, "heavy_object_threshold")
    heavy_bonus = _finite(request.heavy_gpu_bonus, "heavy_gpu_bonus")
    epsilon = _nonnegative(request.score_epsilon_ms, "score_epsilon_ms")
    if heavy_bonus <= 1.0:
        raise FormalAwHeftError("heavy_gpu_bonus must be greater than one")

    weights = {resource: _finite(value, f"weights[{resource}]") for resource, value in request.weights.items()}
    if any(value <= 0.0 for value in weights.values()):
        raise FormalAwHeftError("resource weights must be positive")
    if not math.isclose(sum(weights.values()) / len(weights), 1.0, abs_tol=1e-9):
        raise FormalAwHeftError("resource weights must have arithmetic mean one")

    feature_available = request.object_feature is not None
    feature_value: float | None = None
    feature_time: float | None = None
    if feature_available:
        feature_value = _nonnegative(request.object_feature, "object_feature")
        if request.object_feature_observed_at_ms is None:
            raise FormalAwHeftError("object_feature requires its observation time")
        feature_time = _finite(request.object_feature_observed_at_ms, "object_feature_observed_at_ms")
        if feature_time > decision_time:
            raise FormalAwHeftError("object_feature was not causally available at decision time")
    elif request.object_feature_observed_at_ms is not None:
        raise FormalAwHeftError("object_feature_observed_at_ms requires object_feature")

    heavy_applied = bool(feature_available and feature_value is not None and feature_value > threshold)
    alternatives: dict[str, dict[str, Any]] = {}
    finite_scores: dict[str, float] = {}

    for resource in RESOURCE_ORDER:
        candidate = request.candidates[resource]
        components = {
            "ready_ms": _finite(candidate.ready_ms, f"{resource}.ready_ms"),
            "available_ms": _finite(candidate.available_ms, f"{resource}.available_ms"),
            "queue_wait_ms": _nonnegative(candidate.queue_wait_ms, f"{resource}.queue_wait_ms"),
            "communication_ms": _nonnegative(candidate.communication_ms, f"{resource}.communication_ms"),
            "memory_ms": _nonnegative(candidate.memory_ms, f"{resource}.memory_ms"),
            "execution_ms": _nonnegative(candidate.execution_ms, f"{resource}.execution_ms"),
        }
        if candidate.queue_depth < 0:
            raise FormalAwHeftError(f"{resource}.queue_depth must be nonnegative")
        if not candidate.allowed:
            alternatives[resource] = {
                "allowed": False,
                **components,
                "queue_depth": candidate.queue_depth,
                "finish_ms": math.inf,
                "remaining_ms": math.inf,
                "deadline_risk_ms": math.inf,
                "heft_score_ms": math.inf,
                "weight": weights[resource],
                "heavy_correction_applied": False,
                "weighted_score_ms": math.inf,
            }
            continue

        finish = max(components["ready_ms"], components["available_ms"])
        finish += (
            components["queue_wait_ms"]
            + components["communication_ms"]
            + components["memory_ms"]
            + components["execution_ms"]
        )
        remaining = max(0.0, finish - decision_time)
        risk = max(0.0, finish - deadline)
        heft_score = remaining + risk_lambda * risk
        weighted_score = heft_score * weights[resource]
        resource_heavy = heavy_applied and resource == "gpu"
        if resource_heavy:
            weighted_score /= heavy_bonus
        alternatives[resource] = {
            "allowed": True,
            **components,
            "queue_depth": candidate.queue_depth,
            "finish_ms": finish,
            "remaining_ms": remaining,
            "deadline_risk_ms": risk,
            "heft_score_ms": heft_score,
            "weight": weights[resource],
            "heavy_correction_applied": resource_heavy,
            "weighted_score_ms": weighted_score,
        }
        finite_scores[resource] = weighted_score

    if not finite_scores:
        raise FormalAwHeftError("stage has no allowed execution resource")
    minimum = min(finite_scores.values())
    tied = [resource for resource, score in finite_scores.items() if score <= minimum + epsilon]
    order_index = {resource: index for index, resource in enumerate(request.resource_order)}
    selected = min(
        tied,
        key=lambda resource: (
            alternatives[resource]["communication_ms"],
            alternatives[resource]["queue_depth"],
            order_index[resource],
        ),
    )
    if len(tied) == 1:
        reason = "minimum_aw_heft_score"
    elif len({alternatives[resource]["communication_ms"] for resource in tied}) > 1:
        reason = "score_tie_lower_communication"
    elif len({alternatives[resource]["queue_depth"] for resource in tied}) > 1:
        reason = "score_tie_lower_queue_depth"
    else:
        reason = "score_tie_fixed_resource_order"

    return {
        "implementation_id": REFERENCE_IMPLEMENTATION_ID,
        "stage_id": request.stage_id,
        "trace_id": request.trace_id,
        "rank_u_ms": rank_u,
        "selected_resource": selected,
        "reason": reason,
        "alternatives": alternatives,
        "tie_candidates": tied,
        "score_epsilon_ms": epsilon,
        "deadline_risk_lambda": risk_lambda,
        "object_feature": {
            "available": feature_available,
            "value": feature_value,
            "observed_at_ms": feature_time,
            "source": request.object_feature_source,
            "heavy_correction_applied": heavy_applied and "gpu" in finite_scores,
        },
    }


def project_box_mean_one(
    raw_weights: Mapping[str, float],
    lower_bounds: Mapping[str, float],
    upper_bounds: Mapping[str, float],
) -> dict[str, float]:
    """Euclidean projection onto per-resource boxes and arithmetic-mean one."""

    _validate_resource_keys(raw_weights, "raw_weights")
    _validate_resource_keys(lower_bounds, "lower_bounds")
    _validate_resource_keys(upper_bounds, "upper_bounds")
    raw = {resource: _finite(raw_weights[resource], f"raw_weights[{resource}]") for resource in RESOURCE_ORDER}
    lower = {resource: _finite(lower_bounds[resource], f"lower_bounds[{resource}]") for resource in RESOURCE_ORDER}
    upper = {resource: _finite(upper_bounds[resource], f"upper_bounds[{resource}]") for resource in RESOURCE_ORDER}
    if any(lower[resource] <= 0.0 or upper[resource] < lower[resource] for resource in RESOURCE_ORDER):
        raise FormalAwHeftError("weight bounds must be positive and ordered")
    target_sum = float(len(RESOURCE_ORDER))
    if sum(lower.values()) > target_sum + 1e-12 or sum(upper.values()) < target_sum - 1e-12:
        raise FormalAwHeftError("weight bounds do not intersect the mean-one plane")

    lo = min(raw[resource] - upper[resource] for resource in RESOURCE_ORDER)
    hi = max(raw[resource] - lower[resource] for resource in RESOURCE_ORDER)
    for _ in range(240):
        shift = (lo + hi) / 2.0
        projected_sum = sum(
            min(upper[resource], max(lower[resource], raw[resource] - shift))
            for resource in RESOURCE_ORDER
        )
        if projected_sum > target_sum:
            lo = shift
        else:
            hi = shift
    shift = (lo + hi) / 2.0
    projected = {
        resource: min(upper[resource], max(lower[resource], raw[resource] - shift))
        for resource in RESOURCE_ORDER
    }
    if not math.isclose(sum(projected.values()), target_sum, abs_tol=1e-9):
        raise FormalAwHeftError("weight projection did not reach the mean-one plane")
    return projected


def _feedback_noop(
    request: FeedbackRequest,
    reason: str,
    *,
    parameter_lag: int | None,
    per_resource: Mapping[str, str] | None = None,
    raw_weights: Mapping[str, float] | None = None,
    projected_weights: Mapping[str, float] | None = None,
    candidate_variation: float = 0.0,
) -> dict[str, Any]:
    old = {resource: float(request.old_weights[resource]) for resource in RESOURCE_ORDER}
    raw = dict(raw_weights or old)
    projected = dict(projected_weights or old)
    return {
        "implementation_id": REFERENCE_IMPLEMENTATION_ID,
        "feedback_seq": request.feedback_seq,
        "terminal_status": request.terminal_status,
        "parameter_lag": parameter_lag,
        "applied": False,
        "update_seq_increment": 0,
        "parameter_snapshot_seq_increment": 0,
        "reason": reason,
        "per_resource_reason": dict(per_resource or {}),
        "old_weights": old,
        "raw_weights": raw,
        "projected_weights": projected,
        "new_weights": old,
        "candidate_variation": candidate_variation,
        "variation_before": float(request.variation_before),
        "variation_after": float(request.variation_before),
    }


def evaluate_feedback(request: FeedbackRequest) -> dict[str, Any]:
    """Apply the formal bounded delayed-feedback rule to one terminal outcome."""

    _validate_resource_keys(request.old_weights, "old_weights")
    _validate_resource_keys(request.lower_bounds, "lower_bounds")
    _validate_resource_keys(request.upper_bounds, "upper_bounds")
    _validate_resource_keys(request.resource_states, "resource_states")
    _validate_resource_keys(request.overload_queue_thresholds, "overload_queue_thresholds")
    _validate_resource_keys(request.stable_queue_thresholds, "stable_queue_thresholds")
    if request.terminal_status not in {"completed", "drop", "censored"}:
        raise FormalAwHeftError("terminal_status must be completed, drop, or censored")
    latency = _nonnegative(request.latency_ms, "latency_ms")
    deadline = _finite(request.deadline_ms, "deadline_ms")
    if deadline <= 0.0:
        raise FormalAwHeftError("deadline_ms must be positive")
    if request.feedback_seq <= 0 or request.current_parameter_snapshot_seq < 0:
        raise FormalAwHeftError("feedback and parameter snapshot sequences are invalid")
    if request.history_length <= 0 or request.lag_limit < 0 or request.cooldown_events < 0:
        raise FormalAwHeftError("history, lag, and cooldown parameters are invalid")
    overload_fraction = _finite(request.overload_wait_fraction, "overload_wait_fraction")
    stable_fraction = _finite(request.stable_wait_fraction, "stable_wait_fraction")
    if not (0.0 < stable_fraction <= overload_fraction <= 1.0):
        raise FormalAwHeftError("wait fractions must satisfy 0 < stable <= overload <= 1")
    penalty = _finite(request.penalty_step, "penalty_step")
    reward = _finite(request.reward_step, "reward_step")
    if penalty <= 0.0 or reward <= 0.0:
        raise FormalAwHeftError("feedback steps must be positive")
    variation_before = _nonnegative(request.variation_before, "variation_before")
    variation_budget = _nonnegative(request.variation_budget, "variation_budget")

    old = {resource: _finite(request.old_weights[resource], f"old_weights[{resource}]") for resource in RESOURCE_ORDER}
    if not math.isclose(sum(old.values()) / len(old), 1.0, abs_tol=1e-9):
        raise FormalAwHeftError("old_weights must have arithmetic mean one")

    if not request.source_decision_ids or len(request.source_decision_ids) != len(
        request.source_parameter_snapshot_seqs
    ):
        return _feedback_noop(request, "incomplete_source_decisions", parameter_lag=None)
    if len(set(request.source_decision_ids)) != len(request.source_decision_ids):
        raise FormalAwHeftError("source_decision_ids must be unique")
    source_versions = [int(value) for value in request.source_parameter_snapshot_seqs]
    if any(value < 0 or value > request.current_parameter_snapshot_seq for value in source_versions):
        raise FormalAwHeftError("source parameter snapshot sequence is invalid")
    parameter_lag = request.current_parameter_snapshot_seq - min(source_versions)
    if request.terminal_status == "censored":
        return _feedback_noop(request, "censored_feedback", parameter_lag=parameter_lag)
    if parameter_lag > request.lag_limit:
        return _feedback_noop(request, "stale_feedback", parameter_lag=parameter_lag)
    if not request.updates_enabled:
        return _feedback_noop(
            request,
            "updates_disabled_by_policy_mode",
            parameter_lag=parameter_lag,
        )

    bad = request.terminal_status == "drop" or (
        request.terminal_status == "completed" and latency > deadline
    )
    good = request.terminal_status == "completed" and latency <= deadline
    raw = dict(old)
    per_resource: dict[str, str] = {}

    for resource in RESOURCE_ORDER:
        state = request.resource_states[resource]
        if state.last_update_feedback_seq < 0 or state.last_update_feedback_seq > request.feedback_seq:
            raise FormalAwHeftError(f"{resource} last update sequence is invalid")
        if any(int(depth) < 0 for depth in state.queue_depths):
            raise FormalAwHeftError(f"{resource} queue depth is invalid")
        waits = [_nonnegative(value, f"{resource}.queue_wait_ms") for value in state.queue_wait_ms]
        if len(state.queue_depths) != len(waits):
            raise FormalAwHeftError(f"{resource} queue snapshots are incomplete")
        if not state.used:
            per_resource[resource] = "resource_not_used"
            continue
        if not state.queue_depths:
            per_resource[resource] = "incomplete_resource_snapshots"
            continue
        events_since_update = request.feedback_seq - state.last_update_feedback_seq
        if events_since_update < request.cooldown_events:
            per_resource[resource] = "cooldown_active"
            continue
        overload_limit = int(request.overload_queue_thresholds[resource])
        stable_limit = int(request.stable_queue_thresholds[resource])
        if overload_limit < 0 or stable_limit < 0:
            raise FormalAwHeftError("queue thresholds must be nonnegative")
        overloaded = any(int(depth) > overload_limit for depth in state.queue_depths) or any(
            wait > overload_fraction * deadline for wait in waits
        )
        stable = (
            len(state.history_bad) == request.history_length
            and not any(bool(value) for value in state.history_bad)
            and all(int(depth) <= stable_limit for depth in state.queue_depths)
            and all(wait <= stable_fraction * deadline for wait in waits)
        )
        if bad and overloaded:
            raw[resource] += penalty
            per_resource[resource] = "penalize_overloaded_resource"
        elif good and stable:
            raw[resource] -= reward
            per_resource[resource] = "reward_stable_resource"
        elif request.terminal_status == "drop":
            per_resource[resource] = "drop_without_attributable_overload"
        elif bad:
            per_resource[resource] = "deadline_miss_without_attributable_overload"
        elif good:
            per_resource[resource] = "insufficient_stable_history"
        else:
            per_resource[resource] = "no_weight_update"

    if all(math.isclose(raw[resource], old[resource], abs_tol=1e-15) for resource in RESOURCE_ORDER):
        reason = (
            "cooldown_active"
            if any(value == "cooldown_active" for value in per_resource.values())
            else "no_weight_update"
        )
        return _feedback_noop(
            request,
            reason,
            parameter_lag=parameter_lag,
            per_resource=per_resource,
            raw_weights=raw,
        )

    projected = project_box_mean_one(raw, request.lower_bounds, request.upper_bounds)
    candidate_variation = sum(abs(projected[resource] - old[resource]) for resource in RESOURCE_ORDER)
    if candidate_variation <= 1e-12:
        return _feedback_noop(
            request,
            "no_weight_update",
            parameter_lag=parameter_lag,
            per_resource=per_resource,
            raw_weights=raw,
            projected_weights=projected,
            candidate_variation=candidate_variation,
        )
    if variation_before + candidate_variation > variation_budget + 1e-12:
        return _feedback_noop(
            request,
            "variation_budget_exhausted",
            parameter_lag=parameter_lag,
            per_resource=per_resource,
            raw_weights=raw,
            projected_weights=projected,
            candidate_variation=candidate_variation,
        )

    return {
        "implementation_id": REFERENCE_IMPLEMENTATION_ID,
        "feedback_seq": request.feedback_seq,
        "terminal_status": request.terminal_status,
        "parameter_lag": parameter_lag,
        "applied": True,
        "update_seq_increment": 1,
        "parameter_snapshot_seq_increment": 1,
        "reason": "atomic_bounded_weight_update",
        "per_resource_reason": per_resource,
        "old_weights": old,
        "raw_weights": raw,
        "projected_weights": projected,
        "new_weights": projected,
        "candidate_variation": candidate_variation,
        "variation_before": variation_before,
        "variation_after": variation_before + candidate_variation,
    }


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalAwHeftError(f"{path} must be an object")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise FormalAwHeftError(f"{path} must be an array")
    return value


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], path: str) -> None:
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unexpected = sorted(actual - keys)
        raise FormalAwHeftError(
            f"{path} keys differ: missing={missing}, unexpected={unexpected}"
        )


def _require_nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalAwHeftError(f"{path} must be a nonempty string")
    return value.strip()


def _require_int(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FormalAwHeftError(f"{path} must be an integer not below {minimum}")
    return value


def _require_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise FormalAwHeftError(f"{path} must be boolean")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        rendered = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise FormalAwHeftError("formal replay payload must be canonical JSON data") from exc
    return rendered.encode("ascii")


def _resource_float_map(value: Any, path: str, *, positive: bool = False) -> dict[str, float]:
    mapping = _require_mapping(value, path)
    _validate_resource_keys(mapping, path)
    result = {
        resource: _finite(mapping[resource], f"{path}.{resource}")
        for resource in RESOURCE_ORDER
    }
    if positive and any(number <= 0.0 for number in result.values()):
        raise FormalAwHeftError(f"{path} values must be positive")
    return result


def _resource_int_map(value: Any, path: str) -> dict[str, int]:
    mapping = _require_mapping(value, path)
    _validate_resource_keys(mapping, path)
    return {
        resource: _require_int(mapping[resource], f"{path}.{resource}")
        for resource in RESOURCE_ORDER
    }


def _normalize_formal_graph_profile(
    value: Any,
) -> tuple[
    dict[str, Any],
    dict[str, float],
    dict[str, dict[str, float]],
    dict[str, tuple[str, ...]],
    dict[tuple[str, str], list[float]],
]:
    profile = _require_mapping(value, "graph_profile")
    _require_exact_keys(
        profile,
        {
            "graph_version",
            "profile_version",
            "execution_costs_ms",
            "successors",
            "communication_costs_ms",
        },
        "graph_profile",
    )
    graph_version = _require_nonempty_string(profile["graph_version"], "graph_profile.graph_version")
    profile_version = _require_nonempty_string(
        profile["profile_version"], "graph_profile.profile_version"
    )

    execution_raw = _require_mapping(
        profile["execution_costs_ms"], "graph_profile.execution_costs_ms"
    )
    if not execution_raw:
        raise FormalAwHeftError("graph_profile.execution_costs_ms must not be empty")
    execution: dict[str, dict[str, float]] = {}
    for stage in sorted(execution_raw):
        stage_id = _require_nonempty_string(stage, "graph_profile.execution_costs_ms key")
        costs = _require_mapping(
            execution_raw[stage], f"graph_profile.execution_costs_ms.{stage_id}"
        )
        if not costs or not set(costs).issubset(RESOURCE_ORDER):
            raise FormalAwHeftError(
                f"graph_profile.execution_costs_ms.{stage_id} has invalid resources"
            )
        execution[stage_id] = {
            resource: _nonnegative(
                costs[resource],
                f"graph_profile.execution_costs_ms.{stage_id}.{resource}",
            )
            for resource in RESOURCE_ORDER
            if resource in costs
        }

    successors_raw = _require_mapping(profile["successors"], "graph_profile.successors")
    if set(successors_raw) != set(execution):
        raise FormalAwHeftError("graph_profile.successors must contain every stage exactly once")
    successors: dict[str, tuple[str, ...]] = {}
    for stage in sorted(execution):
        children_raw = _require_list(
            successors_raw[stage], f"graph_profile.successors.{stage}"
        )
        children = tuple(
            _require_nonempty_string(child, f"graph_profile.successors.{stage}")
            for child in children_raw
        )
        if len(set(children)) != len(children):
            raise FormalAwHeftError(f"graph_profile.successors.{stage} contains duplicates")
        successors[stage] = tuple(sorted(children))

    communication_raw = _require_list(
        profile["communication_costs_ms"], "graph_profile.communication_costs_ms"
    )
    communication: dict[tuple[str, str], list[float]] = {}
    normalized_edges: list[dict[str, Any]] = []
    for index, raw_edge in enumerate(communication_raw):
        edge = _require_mapping(raw_edge, f"graph_profile.communication_costs_ms[{index}]")
        _require_exact_keys(
            edge,
            {"source_stage", "target_stage", "costs_ms"},
            f"graph_profile.communication_costs_ms[{index}]",
        )
        source = _require_nonempty_string(
            edge["source_stage"],
            f"graph_profile.communication_costs_ms[{index}].source_stage",
        )
        target = _require_nonempty_string(
            edge["target_stage"],
            f"graph_profile.communication_costs_ms[{index}].target_stage",
        )
        key = (source, target)
        if key in communication:
            raise FormalAwHeftError("graph_profile contains duplicate communication edges")
        costs_raw = _require_list(
            edge["costs_ms"], f"graph_profile.communication_costs_ms[{index}].costs_ms"
        )
        if not costs_raw:
            raise FormalAwHeftError("graph_profile communication edge costs must not be empty")
        costs = [
            _nonnegative(value, f"graph_profile.communication_costs_ms[{index}].costs_ms")
            for value in costs_raw
        ]
        communication[key] = costs
        normalized_edges.append(
            {"source_stage": source, "target_stage": target, "costs_ms": costs}
        )

    ranks = compute_upward_ranks(execution, successors, communication)
    normalized = {
        "graph_version": graph_version,
        "profile_version": profile_version,
        "execution_costs_ms": execution,
        "successors": {stage: list(successors[stage]) for stage in sorted(successors)},
        "communication_costs_ms": sorted(
            normalized_edges,
            key=lambda edge: (edge["source_stage"], edge["target_stage"]),
        ),
    }
    return normalized, ranks, execution, successors, communication


def formal_graph_profile_sha256(profile: Mapping[str, Any]) -> str:
    """Return the canonical identity of the graph and cost-profile replay input."""

    normalized, _, _, _, _ = _normalize_formal_graph_profile(profile)
    return hashlib.sha256(_canonical_json_bytes(normalized)).hexdigest()


def formal_replay_json_value(value: Any) -> Any:
    """Convert deterministic reference output to strict JSON replay representation."""

    if isinstance(value, Mapping):
        return {str(key): formal_replay_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [formal_replay_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        if value > 0.0:
            return "infinity"
        if value < 0.0:
            return "-infinity"
        return "nan"
    return value


def _assert_replay_equal(recorded: Any, expected: Any, path: str, tolerance: float) -> None:
    expected = formal_replay_json_value(expected)
    if isinstance(expected, Mapping):
        actual = _require_mapping(recorded, path)
        if set(actual) != set(expected):
            raise FormalAwHeftError(f"{path} keys differ from replay output")
        for key in expected:
            _assert_replay_equal(actual[key], expected[key], f"{path}.{key}", tolerance)
        return
    if isinstance(expected, list):
        actual = _require_list(recorded, path)
        if len(actual) != len(expected):
            raise FormalAwHeftError(f"{path} length differs from replay output")
        for index, item in enumerate(expected):
            _assert_replay_equal(actual[index], item, f"{path}[{index}]", tolerance)
        return
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        if recorded != expected or type(recorded) is not type(expected):
            raise FormalAwHeftError(f"{path} differs from replay output")
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        actual = _finite(recorded, path)
        if not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=tolerance):
            raise FormalAwHeftError(f"{path} differs from replay output")
        return
    if recorded != expected:
        raise FormalAwHeftError(f"{path} differs from replay output")


def _parse_candidate(value: Any, path: str) -> ResourceCandidate:
    candidate = _require_mapping(value, path)
    _require_exact_keys(
        candidate,
        {
            "allowed",
            "ready_ms",
            "available_ms",
            "queue_wait_ms",
            "communication_ms",
            "memory_ms",
            "execution_ms",
            "queue_depth",
        },
        path,
    )
    return ResourceCandidate(
        allowed=_require_bool(candidate["allowed"], f"{path}.allowed"),
        ready_ms=_finite(candidate["ready_ms"], f"{path}.ready_ms"),
        available_ms=_finite(candidate["available_ms"], f"{path}.available_ms"),
        queue_wait_ms=_nonnegative(candidate["queue_wait_ms"], f"{path}.queue_wait_ms"),
        communication_ms=_nonnegative(
            candidate["communication_ms"], f"{path}.communication_ms"
        ),
        memory_ms=_nonnegative(candidate["memory_ms"], f"{path}.memory_ms"),
        execution_ms=_nonnegative(candidate["execution_ms"], f"{path}.execution_ms"),
        queue_depth=_require_int(candidate["queue_depth"], f"{path}.queue_depth"),
    )


def _parse_resource_feedback_state(value: Any, path: str) -> ResourceFeedbackState:
    state = _require_mapping(value, path)
    _require_exact_keys(
        state,
        {
            "used",
            "queue_depths",
            "queue_wait_ms",
            "history_bad",
            "last_update_feedback_seq",
        },
        path,
    )
    queue_depths = [
        _require_int(item, f"{path}.queue_depths")
        for item in _require_list(state["queue_depths"], f"{path}.queue_depths")
    ]
    queue_wait = [
        _nonnegative(item, f"{path}.queue_wait_ms")
        for item in _require_list(state["queue_wait_ms"], f"{path}.queue_wait_ms")
    ]
    history_bad = [
        _require_bool(item, f"{path}.history_bad")
        for item in _require_list(state["history_bad"], f"{path}.history_bad")
    ]
    return ResourceFeedbackState(
        used=_require_bool(state["used"], f"{path}.used"),
        queue_depths=queue_depths,
        queue_wait_ms=queue_wait,
        history_bad=history_bad,
        last_update_feedback_seq=_require_int(
            state["last_update_feedback_seq"],
            f"{path}.last_update_feedback_seq",
        ),
    )


def replay_formal_aw_heft_trace(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Replay a complete formal decision/feedback packet without accepting provenance."""

    trace = _require_mapping(payload, "formal_trace")
    _require_exact_keys(
        trace,
        {
            "schema_version",
            "implementation_id",
            "evidence_status",
            "policy_mode",
            "numeric_tolerance",
            "graph_profile",
            "graph_profile_sha256",
            "initial_state",
            "events",
        },
        "formal_trace",
    )
    if trace["schema_version"] != FORMAL_TRACE_CONTRACT_VERSION:
        raise FormalAwHeftError("formal_trace.schema_version has drifted")
    if trace["implementation_id"] != REFERENCE_IMPLEMENTATION_ID:
        raise FormalAwHeftError("formal_trace.implementation_id has drifted")
    if trace["evidence_status"] != FORMAL_REPLAY_EVIDENCE_STATUS:
        raise FormalAwHeftError("formal_trace.evidence_status is not replay-input-only")
    policy_mode = _require_nonempty_string(trace["policy_mode"], "formal_trace.policy_mode")
    if policy_mode not in FORMAL_POLICY_MODES:
        raise FormalAwHeftError("formal_trace.policy_mode must be formal_frozen or formal_online")
    tolerance = _finite(trace["numeric_tolerance"], "formal_trace.numeric_tolerance")
    if tolerance != FORMAL_REPLAY_NUMERIC_TOLERANCE:
        raise FormalAwHeftError("formal_trace.numeric_tolerance has drifted")

    normalized_profile, ranks, execution_costs, _, _ = _normalize_formal_graph_profile(
        trace["graph_profile"]
    )
    expected_profile_sha = hashlib.sha256(_canonical_json_bytes(normalized_profile)).hexdigest()
    if trace["graph_profile_sha256"] != expected_profile_sha:
        raise FormalAwHeftError("formal_trace.graph_profile_sha256 does not match the payload")

    initial = _require_mapping(trace["initial_state"], "formal_trace.initial_state")
    _require_exact_keys(
        initial,
        {"parameter_snapshot_seq", "update_seq", "weights", "variation"},
        "formal_trace.initial_state",
    )
    parameter_snapshot_seq = _require_int(
        initial["parameter_snapshot_seq"],
        "formal_trace.initial_state.parameter_snapshot_seq",
    )
    update_seq = _require_int(initial["update_seq"], "formal_trace.initial_state.update_seq")
    variation = _nonnegative(initial["variation"], "formal_trace.initial_state.variation")
    if parameter_snapshot_seq != 0 or update_seq != 0 or variation != 0.0:
        raise FormalAwHeftError("formal_trace initial state must start from reset sequence zero")
    weights = _resource_float_map(initial["weights"], "formal_trace.initial_state.weights", positive=True)
    if not math.isclose(sum(weights.values()) / len(weights), 1.0, abs_tol=tolerance):
        raise FormalAwHeftError("formal_trace initial weights must have arithmetic mean one")

    events = _require_list(trace["events"], "formal_trace.events")
    if not events:
        raise FormalAwHeftError("formal_trace.events must not be empty")
    decision_records: dict[str, dict[str, Any]] = {}
    applied_by_trace: dict[str, list[str]] = {}
    feedback_traces: set[str] = set()
    closed_traces: set[str] = set()
    pending_first_consumer: dict[str, Any] | None = None
    expected_decision_seq = 1
    expected_feedback_seq = 1
    last_event_time = -math.inf
    decision_count = 0
    feedback_count = 0
    applied_update_count = 0

    for expected_event_seq, raw_event in enumerate(events, start=1):
        event_path = f"formal_trace.events[{expected_event_seq - 1}]"
        event = _require_mapping(raw_event, event_path)
        if event.get("event_seq") != expected_event_seq:
            raise FormalAwHeftError(f"{event_path}.event_seq must be gap-free and start at one")
        kind = _require_nonempty_string(event.get("kind"), f"{event_path}.kind")
        event_time = _finite(event.get("event_time_ms"), f"{event_path}.event_time_ms")
        if event_time < last_event_time:
            raise FormalAwHeftError("formal_trace event time must be monotonic")
        last_event_time = event_time

        if kind == "decision":
            _require_exact_keys(
                event,
                {
                    "event_seq",
                    "kind",
                    "event_time_ms",
                    "decision_id",
                    "decision_seq",
                    "trace_id",
                    "parameter_snapshot_seq",
                    "applied",
                    "ready_tasks",
                    "request",
                    "recorded_result",
                },
                event_path,
            )
            decision_id = _require_nonempty_string(
                event["decision_id"], f"{event_path}.decision_id"
            )
            if decision_id in decision_records:
                raise FormalAwHeftError("formal_trace decision_id must be unique")
            decision_seq = _require_int(
                event["decision_seq"], f"{event_path}.decision_seq", minimum=1
            )
            if decision_seq != expected_decision_seq:
                raise FormalAwHeftError("formal_trace decision_seq must be gap-free and start at one")
            expected_decision_seq += 1
            trace_id = _require_nonempty_string(event["trace_id"], f"{event_path}.trace_id")
            if trace_id in closed_traces:
                raise FormalAwHeftError("formal_trace contains a decision after terminal feedback")
            event_snapshot = _require_int(
                event["parameter_snapshot_seq"],
                f"{event_path}.parameter_snapshot_seq",
            )
            if event_snapshot != parameter_snapshot_seq:
                raise FormalAwHeftError("formal_trace decision uses a stale parameter snapshot")
            applied = _require_bool(event["applied"], f"{event_path}.applied")

            ready_values = _require_list(event["ready_tasks"], f"{event_path}.ready_tasks")
            if not ready_values:
                raise FormalAwHeftError("formal_trace decision ready set must not be empty")
            ready_tasks: list[ReadyTask] = []
            ready_identities: set[tuple[str, str]] = set()
            for ready_index, raw_ready in enumerate(ready_values):
                ready_path = f"{event_path}.ready_tasks[{ready_index}]"
                ready = _require_mapping(raw_ready, ready_path)
                _require_exact_keys(
                    ready,
                    {
                        "stage_id",
                        "trace_id",
                        "recorded_rank_u_ms",
                        "deadline_ms",
                        "arrival_ms",
                    },
                    ready_path,
                )
                stage_id = _require_nonempty_string(ready["stage_id"], f"{ready_path}.stage_id")
                if stage_id not in ranks:
                    raise FormalAwHeftError("formal_trace ready task references an unknown stage")
                recorded_rank = _finite(
                    ready["recorded_rank_u_ms"], f"{ready_path}.recorded_rank_u_ms"
                )
                if not math.isclose(recorded_rank, ranks[stage_id], rel_tol=0.0, abs_tol=tolerance):
                    raise FormalAwHeftError("formal_trace recorded rank differs from graph replay")
                ready_trace_id = _require_nonempty_string(
                    ready["trace_id"], f"{ready_path}.trace_id"
                )
                ready_identity = (stage_id, ready_trace_id)
                if ready_identity in ready_identities:
                    raise FormalAwHeftError("formal_trace ready set contains duplicate task instances")
                ready_identities.add(ready_identity)
                ready_tasks.append(
                    ReadyTask(
                        stage_id=stage_id,
                        trace_id=ready_trace_id,
                        rank_u_ms=ranks[stage_id],
                        deadline_ms=_finite(ready["deadline_ms"], f"{ready_path}.deadline_ms"),
                        arrival_ms=_finite(ready["arrival_ms"], f"{ready_path}.arrival_ms"),
                    )
                )
            selected_task = select_ready_task(ready_tasks)

            raw_request = _require_mapping(event["request"], f"{event_path}.request")
            _require_exact_keys(
                raw_request,
                {
                    "stage_id",
                    "trace_id",
                    "rank_u_ms",
                    "decision_time_ms",
                    "deadline_ms",
                    "candidates",
                    "weights",
                    "deadline_risk_lambda",
                    "heavy_object_threshold",
                    "heavy_gpu_bonus",
                    "score_epsilon_ms",
                    "resource_order",
                    "object_feature",
                    "object_feature_observed_at_ms",
                    "object_feature_source",
                },
                f"{event_path}.request",
            )
            request_stage = _require_nonempty_string(
                raw_request["stage_id"], f"{event_path}.request.stage_id"
            )
            request_trace = _require_nonempty_string(
                raw_request["trace_id"], f"{event_path}.request.trace_id"
            )
            if (request_stage, request_trace) != (selected_task.stage_id, selected_task.trace_id):
                raise FormalAwHeftError("formal_trace request does not use the replayed ready task")
            if request_trace != trace_id:
                raise FormalAwHeftError("formal_trace event and request trace_id differ")
            request_rank = _finite(raw_request["rank_u_ms"], f"{event_path}.request.rank_u_ms")
            if not math.isclose(request_rank, selected_task.rank_u_ms, rel_tol=0.0, abs_tol=tolerance):
                raise FormalAwHeftError("formal_trace request rank differs from graph replay")
            request_time = _finite(
                raw_request["decision_time_ms"], f"{event_path}.request.decision_time_ms"
            )
            if not math.isclose(request_time, event_time, rel_tol=0.0, abs_tol=tolerance):
                raise FormalAwHeftError("formal_trace event and decision timestamps differ")
            request_weights = _resource_float_map(
                raw_request["weights"], f"{event_path}.request.weights", positive=True
            )
            _assert_replay_equal(request_weights, weights, f"{event_path}.request.weights", tolerance)
            candidates_raw = _require_mapping(
                raw_request["candidates"], f"{event_path}.request.candidates"
            )
            _validate_resource_keys(candidates_raw, f"{event_path}.request.candidates")
            candidates = {
                resource: _parse_candidate(
                    candidates_raw[resource],
                    f"{event_path}.request.candidates.{resource}",
                )
                for resource in RESOURCE_ORDER
            }
            allowed_resources = set(execution_costs[request_stage])
            if {
                resource for resource, value in candidates.items() if value.allowed
            } != allowed_resources:
                raise FormalAwHeftError(
                    "formal_trace allowed candidates differ from the graph execution profile"
                )
            resource_order = [
                _require_nonempty_string(item, f"{event_path}.request.resource_order")
                for item in _require_list(
                    raw_request["resource_order"], f"{event_path}.request.resource_order"
                )
            ]
            object_feature_raw = raw_request["object_feature"]
            object_feature = (
                None
                if object_feature_raw is None
                else _nonnegative(object_feature_raw, f"{event_path}.request.object_feature")
            )
            observed_raw = raw_request["object_feature_observed_at_ms"]
            observed_at = (
                None
                if observed_raw is None
                else _finite(observed_raw, f"{event_path}.request.object_feature_observed_at_ms")
            )
            request = DecisionRequest(
                stage_id=request_stage,
                trace_id=request_trace,
                rank_u_ms=request_rank,
                decision_time_ms=request_time,
                deadline_ms=_finite(
                    raw_request["deadline_ms"], f"{event_path}.request.deadline_ms"
                ),
                candidates=candidates,
                weights=request_weights,
                deadline_risk_lambda=_nonnegative(
                    raw_request["deadline_risk_lambda"],
                    f"{event_path}.request.deadline_risk_lambda",
                ),
                heavy_object_threshold=_nonnegative(
                    raw_request["heavy_object_threshold"],
                    f"{event_path}.request.heavy_object_threshold",
                ),
                heavy_gpu_bonus=_finite(
                    raw_request["heavy_gpu_bonus"], f"{event_path}.request.heavy_gpu_bonus"
                ),
                score_epsilon_ms=_nonnegative(
                    raw_request["score_epsilon_ms"],
                    f"{event_path}.request.score_epsilon_ms",
                ),
                resource_order=resource_order,
                object_feature=object_feature,
                object_feature_observed_at_ms=observed_at,
                object_feature_source=_require_nonempty_string(
                    raw_request["object_feature_source"],
                    f"{event_path}.request.object_feature_source",
                ),
            )
            replayed_result = evaluate_decision(request)
            _assert_replay_equal(
                event["recorded_result"],
                replayed_result,
                f"{event_path}.recorded_result",
                tolerance,
            )
            if pending_first_consumer is not None:
                if decision_id != pending_first_consumer["decision_id"]:
                    raise FormalAwHeftError("formal_trace first consumer does not match the update")
                if event_snapshot != pending_first_consumer["parameter_snapshot_seq"]:
                    raise FormalAwHeftError("formal_trace first consumer uses the wrong snapshot")
                pending_first_consumer = None

            decision_records[decision_id] = {
                "decision_seq": decision_seq,
                "trace_id": trace_id,
                "parameter_snapshot_seq": event_snapshot,
                "decision_time_ms": request_time,
                "applied": applied,
                "selected_resource": replayed_result["selected_resource"],
            }
            if applied:
                applied_by_trace.setdefault(trace_id, []).append(decision_id)
            decision_count += 1
            continue

        if kind == "feedback":
            _require_exact_keys(
                event,
                {
                    "event_seq",
                    "kind",
                    "event_time_ms",
                    "trace_id",
                    "feedback_seq",
                    "current_parameter_snapshot_seq",
                    "current_update_seq",
                    "source_decision_ids",
                    "request",
                    "recorded_result",
                    "first_consumer_decision_id",
                    "resulting_parameter_snapshot_seq",
                    "resulting_update_seq",
                },
                event_path,
            )
            trace_id = _require_nonempty_string(event["trace_id"], f"{event_path}.trace_id")
            if trace_id in feedback_traces:
                raise FormalAwHeftError("formal_trace permits only one terminal feedback per trace")
            feedback_seq = _require_int(
                event["feedback_seq"], f"{event_path}.feedback_seq", minimum=1
            )
            if feedback_seq != expected_feedback_seq:
                raise FormalAwHeftError("formal_trace feedback_seq must be gap-free and start at one")
            expected_feedback_seq += 1
            current_snapshot = _require_int(
                event["current_parameter_snapshot_seq"],
                f"{event_path}.current_parameter_snapshot_seq",
            )
            current_update = _require_int(
                event["current_update_seq"], f"{event_path}.current_update_seq"
            )
            if current_snapshot != parameter_snapshot_seq or current_update != update_seq:
                raise FormalAwHeftError("formal_trace feedback state does not match replay state")
            source_ids = [
                _require_nonempty_string(item, f"{event_path}.source_decision_ids")
                for item in _require_list(
                    event["source_decision_ids"], f"{event_path}.source_decision_ids"
                )
            ]
            expected_sources = applied_by_trace.get(trace_id, [])
            if not expected_sources or source_ids != expected_sources:
                raise FormalAwHeftError(
                    "formal_trace feedback source set must equal all applied decisions for the trace"
                )
            source_records = [decision_records[source_id] for source_id in source_ids]
            if event_time < max(float(record["decision_time_ms"]) for record in source_records):
                raise FormalAwHeftError("formal_trace feedback precedes a source decision")

            raw_request = _require_mapping(event["request"], f"{event_path}.request")
            _require_exact_keys(
                raw_request,
                {
                    "terminal_status",
                    "latency_ms",
                    "deadline_ms",
                    "source_parameter_snapshot_seqs",
                    "old_weights",
                    "lower_bounds",
                    "upper_bounds",
                    "resource_states",
                    "overload_queue_thresholds",
                    "stable_queue_thresholds",
                    "overload_wait_fraction",
                    "stable_wait_fraction",
                    "history_length",
                    "lag_limit",
                    "cooldown_events",
                    "penalty_step",
                    "reward_step",
                    "variation_before",
                    "variation_budget",
                    "updates_enabled",
                },
                f"{event_path}.request",
            )
            source_snapshots = [
                _require_int(item, f"{event_path}.request.source_parameter_snapshot_seqs")
                for item in _require_list(
                    raw_request["source_parameter_snapshot_seqs"],
                    f"{event_path}.request.source_parameter_snapshot_seqs",
                )
            ]
            expected_snapshots = [
                int(decision_records[source_id]["parameter_snapshot_seq"])
                for source_id in source_ids
            ]
            if source_snapshots != expected_snapshots:
                raise FormalAwHeftError("formal_trace source snapshot list differs from decisions")
            old_weights = _resource_float_map(
                raw_request["old_weights"], f"{event_path}.request.old_weights", positive=True
            )
            _assert_replay_equal(old_weights, weights, f"{event_path}.request.old_weights", tolerance)
            variation_before = _nonnegative(
                raw_request["variation_before"], f"{event_path}.request.variation_before"
            )
            if not math.isclose(variation_before, variation, rel_tol=0.0, abs_tol=tolerance):
                raise FormalAwHeftError("formal_trace variation state differs from replay state")
            updates_enabled = _require_bool(
                raw_request["updates_enabled"], f"{event_path}.request.updates_enabled"
            )
            if updates_enabled != (policy_mode == "formal_online"):
                raise FormalAwHeftError("formal_trace updates_enabled differs from policy_mode")
            resource_states_raw = _require_mapping(
                raw_request["resource_states"], f"{event_path}.request.resource_states"
            )
            _validate_resource_keys(resource_states_raw, f"{event_path}.request.resource_states")
            resource_states = {
                resource: _parse_resource_feedback_state(
                    resource_states_raw[resource],
                    f"{event_path}.request.resource_states.{resource}",
                )
                for resource in RESOURCE_ORDER
            }
            feedback_request = FeedbackRequest(
                terminal_status=_require_nonempty_string(
                    raw_request["terminal_status"], f"{event_path}.request.terminal_status"
                ),
                latency_ms=_nonnegative(
                    raw_request["latency_ms"], f"{event_path}.request.latency_ms"
                ),
                deadline_ms=_finite(
                    raw_request["deadline_ms"], f"{event_path}.request.deadline_ms"
                ),
                feedback_seq=feedback_seq,
                current_parameter_snapshot_seq=current_snapshot,
                source_decision_ids=source_ids,
                source_parameter_snapshot_seqs=source_snapshots,
                old_weights=old_weights,
                lower_bounds=_resource_float_map(
                    raw_request["lower_bounds"],
                    f"{event_path}.request.lower_bounds",
                    positive=True,
                ),
                upper_bounds=_resource_float_map(
                    raw_request["upper_bounds"],
                    f"{event_path}.request.upper_bounds",
                    positive=True,
                ),
                resource_states=resource_states,
                overload_queue_thresholds=_resource_int_map(
                    raw_request["overload_queue_thresholds"],
                    f"{event_path}.request.overload_queue_thresholds",
                ),
                stable_queue_thresholds=_resource_int_map(
                    raw_request["stable_queue_thresholds"],
                    f"{event_path}.request.stable_queue_thresholds",
                ),
                overload_wait_fraction=_finite(
                    raw_request["overload_wait_fraction"],
                    f"{event_path}.request.overload_wait_fraction",
                ),
                stable_wait_fraction=_finite(
                    raw_request["stable_wait_fraction"],
                    f"{event_path}.request.stable_wait_fraction",
                ),
                history_length=_require_int(
                    raw_request["history_length"],
                    f"{event_path}.request.history_length",
                    minimum=1,
                ),
                lag_limit=_require_int(
                    raw_request["lag_limit"], f"{event_path}.request.lag_limit"
                ),
                cooldown_events=_require_int(
                    raw_request["cooldown_events"], f"{event_path}.request.cooldown_events"
                ),
                penalty_step=_finite(
                    raw_request["penalty_step"], f"{event_path}.request.penalty_step"
                ),
                reward_step=_finite(
                    raw_request["reward_step"], f"{event_path}.request.reward_step"
                ),
                variation_before=variation_before,
                variation_budget=_nonnegative(
                    raw_request["variation_budget"],
                    f"{event_path}.request.variation_budget",
                ),
                updates_enabled=updates_enabled,
            )
            replayed_result = evaluate_feedback(feedback_request)
            _assert_replay_equal(
                event["recorded_result"],
                replayed_result,
                f"{event_path}.recorded_result",
                tolerance,
            )
            applied_update = bool(replayed_result["applied"])
            resulting_snapshot = _require_int(
                event["resulting_parameter_snapshot_seq"],
                f"{event_path}.resulting_parameter_snapshot_seq",
            )
            resulting_update = _require_int(
                event["resulting_update_seq"], f"{event_path}.resulting_update_seq"
            )
            first_consumer = event["first_consumer_decision_id"]
            if applied_update:
                if pending_first_consumer is not None:
                    raise FormalAwHeftError(
                        "formal_trace cannot supersede an update before its first consumer"
                    )
                if not isinstance(first_consumer, str) or not first_consumer.strip():
                    raise FormalAwHeftError("formal_trace update requires a first consumer")
                if resulting_snapshot != parameter_snapshot_seq + 1 or resulting_update != update_seq + 1:
                    raise FormalAwHeftError("formal_trace update sequences differ from replay")
                parameter_snapshot_seq = resulting_snapshot
                update_seq = resulting_update
                weights = {
                    resource: float(replayed_result["new_weights"][resource])
                    for resource in RESOURCE_ORDER
                }
                variation = float(replayed_result["variation_after"])
                pending_first_consumer = {
                    "decision_id": first_consumer.strip(),
                    "parameter_snapshot_seq": parameter_snapshot_seq,
                }
                applied_update_count += 1
            else:
                if first_consumer is not None:
                    raise FormalAwHeftError("formal_trace no-op feedback cannot name a first consumer")
                if resulting_snapshot != parameter_snapshot_seq or resulting_update != update_seq:
                    raise FormalAwHeftError("formal_trace no-op feedback changes replay sequences")
                variation = float(replayed_result["variation_after"])
            feedback_traces.add(trace_id)
            closed_traces.add(trace_id)
            feedback_count += 1
            continue

        raise FormalAwHeftError(f"{event_path}.kind must be decision or feedback")

    missing_feedback = sorted(set(applied_by_trace) - feedback_traces)
    if missing_feedback:
        raise FormalAwHeftError(
            "formal_trace lacks terminal feedback for applied traces: " + ", ".join(missing_feedback)
        )
    if pending_first_consumer is not None:
        raise FormalAwHeftError("formal_trace ends before the first consumer of an update")
    if decision_count == 0 or feedback_count == 0:
        raise FormalAwHeftError("formal_trace requires both decision and feedback events")
    if policy_mode == "formal_frozen" and applied_update_count:
        raise FormalAwHeftError("formal_frozen trace cannot apply parameter updates")

    packet_sha = hashlib.sha256(_canonical_json_bytes(trace)).hexdigest()
    return {
        "replay_schema_version": 1,
        "status": FORMAL_REPLAY_STATUS,
        "replay_verified": True,
        "evidence_accepted": False,
        "benchmark_eligible": False,
        "implementation_id": REFERENCE_IMPLEMENTATION_ID,
        "trace_contract_version": FORMAL_TRACE_CONTRACT_VERSION,
        "policy_mode": policy_mode,
        "graph_profile_sha256": expected_profile_sha,
        "replay_packet_sha256": packet_sha,
        "decision_count": decision_count,
        "feedback_count": feedback_count,
        "applied_update_count": applied_update_count,
        "final_parameter_snapshot_seq": parameter_snapshot_seq,
        "final_update_seq": update_seq,
        "final_weights": weights,
        "final_variation": variation,
        "interpretation": (
            "The packet reproduces the formal reference mathematics and state order only. "
            "Its provenance is not accepted telemetry, it is not runtime binding, and it "
            "does not establish a benchmark effect."
        ),
    }


def validate_reference_artifact(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalAwHeftError(f"cannot read formal AW-HEFT artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalAwHeftError("formal AW-HEFT artifact must be a JSON object")
    expected = {
        "schema_version": 1,
        "implementation_id": REFERENCE_IMPLEMENTATION_ID,
        "method": "AW-HEFT",
        "status": REFERENCE_STATUS,
        "benchmark_eligible": False,
        "resource_scope": list(RESOURCE_ORDER),
        "rank_u_semantics": "mean_exec_plus_max_mean_communication_successor_rank_v1",
        "ready_order_semantics": "descending_rank_then_deadline_arrival_trace_stage_v1",
        "transfer_cost_semantics": "directed_parent_resource_to_candidate_resource_ms_v1",
        "memory_cost_semantics": "candidate_resource_buffer_placement_ms_v1",
        "deadline_risk_semantics": "remaining_plus_lambda_positive_deadline_lateness_ms_v1",
        "stability_window_semantics": "terminal_history_lag_cooldown_and_total_variation_budget_v1",
        "weight_projection": "euclidean_box_mean_one_v1",
        "tie_break": ["communication_ms", "queue_depth", "resource_order"],
        "resource_order": list(RESOURCE_ORDER),
        "trace_contract_version": FORMAL_TRACE_CONTRACT_VERSION,
        "formal_trace_replay_semantics": (
            "recompute_rank_ready_decision_feedback_state_and_first_consumer_v1"
        ),
        "replay_numeric_tolerance": FORMAL_REPLAY_NUMERIC_TOLERANCE,
        "frozen_policy_semantics": "same_initial_weights_feedback_updates_disabled_v1",
        "implementation_module": "scripts/formal_aw_heft_reference.py",
        "runtime_binding": None,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise FormalAwHeftError(f"formal AW-HEFT artifact field {key} has drifted")
    limitations = payload.get("limitations")
    required_limitations = {
        "no_dataset_consuming_runtime_binding",
        "no_target_hardware_execution",
        "no_benchmark_measurement",
        "no_policy_effect_claim",
        "no_accepted_formal_trace_replay",
    }
    if not isinstance(limitations, list) or set(limitations) != required_limitations:
        raise FormalAwHeftError("formal AW-HEFT artifact limitations have drifted")
    return payload


def _reject_nonfinite_json(value: str) -> None:
    raise FormalAwHeftError(f"formal trace JSON contains non-finite constant {value}")


def _reject_duplicate_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FormalAwHeftError(f"formal trace JSON contains duplicate key {key}")
        result[key] = value
    return result


def load_formal_replay_packet(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except OSError as exc:
        raise FormalAwHeftError(f"cannot read formal replay packet: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FormalAwHeftError(f"formal replay packet is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalAwHeftError("formal replay packet must be a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the formal AW-HEFT reference contract")
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "policies" / "aw_heft_reference_v1.json",
    )
    parser.add_argument(
        "--trace",
        type=Path,
        help="Replay one input-only formal trace packet without accepting it as telemetry",
    )
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    validate_reference_artifact(artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if args.trace is not None:
        result = replay_formal_aw_heft_trace(load_formal_replay_packet(args.trace.resolve()))
        result["artifact_sha256"] = digest
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    print(
        json.dumps(
            {
                "implementation_id": REFERENCE_IMPLEMENTATION_ID,
                "status": REFERENCE_STATUS,
                "reference_contract_verified": True,
                "runtime_bound": False,
                "benchmark_eligible": False,
                "formal_reference_replay_implemented": True,
                "formal_reference_replay_entrypoint": (
                    "formal_aw_heft_reference.replay_formal_aw_heft_trace"
                ),
                "trace_contract_version": FORMAL_TRACE_CONTRACT_VERSION,
                "accepted_formal_trace_replay_performed": False,
                "artifact_sha256": digest,
                "interpretation": (
                    "Executable reference and input-only replay logic are available for "
                    "contract tests; no accepted trace was replayed, and this is not a "
                    "dataset-consuming runtime or benchmark result."
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
