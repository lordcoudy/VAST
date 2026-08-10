#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from formal_aw_heft_reference import (
    DecisionRequest,
    FeedbackRequest,
    FormalAwHeftError,
    ReadyTask,
    ResourceCandidate,
    ResourceFeedbackState,
    compute_upward_ranks,
    evaluate_decision,
    evaluate_feedback,
    formal_graph_profile_sha256,
    formal_replay_json_value,
    load_formal_replay_packet,
    project_box_mean_one,
    replay_formal_aw_heft_trace,
    select_ready_task,
    validate_reference_artifact,
)


def candidate(
    *,
    allowed: bool = True,
    ready: float = 100.0,
    available: float = 100.0,
    queue_wait: float = 0.0,
    communication: float = 0.0,
    memory: float = 0.0,
    execution: float = 10.0,
    queue_depth: int = 0,
) -> ResourceCandidate:
    return ResourceCandidate(
        allowed=allowed,
        ready_ms=ready,
        available_ms=available,
        queue_wait_ms=queue_wait,
        communication_ms=communication,
        memory_ms=memory,
        execution_ms=execution,
        queue_depth=queue_depth,
    )


def decision_request() -> DecisionRequest:
    return DecisionRequest(
        stage_id="detect",
        trace_id="stream-1:frame-7:detect",
        rank_u_ms=21.0,
        decision_time_ms=100.0,
        deadline_ms=120.0,
        candidates={
            "cpu": candidate(queue_wait=2.0, communication=3.0, memory=1.0, execution=10.0, queue_depth=2),
            "gpu": candidate(available=104.0, queue_wait=1.0, communication=2.0, memory=1.0, execution=5.0, queue_depth=1),
            "nvdec": candidate(allowed=False),
        },
        weights={"cpu": 1.0, "gpu": 1.0, "nvdec": 1.0},
        deadline_risk_lambda=2.0,
        heavy_object_threshold=32.0,
        heavy_gpu_bonus=2.0,
        score_epsilon_ms=1e-9,
    )


def feedback_request(**changes: object) -> FeedbackRequest:
    request = FeedbackRequest(
        terminal_status="completed",
        latency_ms=120.0,
        deadline_ms=100.0,
        feedback_seq=3,
        current_parameter_snapshot_seq=1,
        source_decision_ids=("decision-1",),
        source_parameter_snapshot_seqs=(1,),
        old_weights={"cpu": 1.0, "gpu": 1.0, "nvdec": 1.0},
        lower_bounds={"cpu": 0.5, "gpu": 0.5, "nvdec": 0.5},
        upper_bounds={"cpu": 1.5, "gpu": 1.5, "nvdec": 1.5},
        resource_states={
            "cpu": ResourceFeedbackState(False, (), (), (), 0),
            "gpu": ResourceFeedbackState(True, (3,), (60.0,), (False, False), 0),
            "nvdec": ResourceFeedbackState(False, (), (), (), 0),
        },
        overload_queue_thresholds={"cpu": 1, "gpu": 1, "nvdec": 1},
        stable_queue_thresholds={"cpu": 1, "gpu": 1, "nvdec": 1},
        overload_wait_fraction=0.5,
        stable_wait_fraction=0.2,
        history_length=2,
        lag_limit=8,
        cooldown_events=2,
        penalty_step=0.1,
        reward_step=0.05,
        variation_before=0.0,
        variation_budget=0.5,
    )
    return replace(request, **changes)


def candidate_payload(value: ResourceCandidate) -> dict[str, object]:
    return {
        "allowed": value.allowed,
        "ready_ms": value.ready_ms,
        "available_ms": value.available_ms,
        "queue_wait_ms": value.queue_wait_ms,
        "communication_ms": value.communication_ms,
        "memory_ms": value.memory_ms,
        "execution_ms": value.execution_ms,
        "queue_depth": value.queue_depth,
    }


def state_payload(value: ResourceFeedbackState) -> dict[str, object]:
    return {
        "used": value.used,
        "queue_depths": list(value.queue_depths),
        "queue_wait_ms": list(value.queue_wait_ms),
        "history_bad": list(value.history_bad),
        "last_update_feedback_seq": value.last_update_feedback_seq,
    }


def replay_decision_event(
    *,
    event_seq: int,
    decision_seq: int,
    decision_id: str,
    trace_id: str,
    decision_time_ms: float,
    rank_u_ms: float,
    weights: dict[str, float],
    parameter_snapshot_seq: int,
) -> tuple[dict[str, object], dict[str, object]]:
    candidates = {
        "cpu": candidate(
            ready=decision_time_ms,
            available=decision_time_ms,
            queue_wait=2.0,
            communication=1.0,
            memory=1.0,
            execution=10.0,
            queue_depth=2,
        ),
        "gpu": candidate(
            ready=decision_time_ms,
            available=decision_time_ms,
            queue_wait=1.0,
            communication=1.0,
            memory=1.0,
            execution=4.0,
            queue_depth=1,
        ),
        "nvdec": candidate(
            allowed=False,
            ready=decision_time_ms,
            available=decision_time_ms,
        ),
    }
    request = DecisionRequest(
        stage_id="detect",
        trace_id=trace_id,
        rank_u_ms=rank_u_ms,
        decision_time_ms=decision_time_ms,
        deadline_ms=decision_time_ms + 100.0,
        candidates=candidates,
        weights=weights,
        deadline_risk_lambda=2.0,
        heavy_object_threshold=32.0,
        heavy_gpu_bonus=2.0,
        score_epsilon_ms=1.0e-9,
    )
    result = evaluate_decision(request)
    event = {
        "event_seq": event_seq,
        "kind": "decision",
        "event_time_ms": decision_time_ms,
        "decision_id": decision_id,
        "decision_seq": decision_seq,
        "trace_id": trace_id,
        "parameter_snapshot_seq": parameter_snapshot_seq,
        "applied": True,
        "ready_tasks": [
            {
                "stage_id": "detect",
                "trace_id": trace_id,
                "recorded_rank_u_ms": rank_u_ms,
                "deadline_ms": decision_time_ms + 100.0,
                "arrival_ms": decision_time_ms,
            }
        ],
        "request": {
            "stage_id": "detect",
            "trace_id": trace_id,
            "rank_u_ms": rank_u_ms,
            "decision_time_ms": decision_time_ms,
            "deadline_ms": decision_time_ms + 100.0,
            "candidates": {
                resource: candidate_payload(value) for resource, value in candidates.items()
            },
            "weights": dict(weights),
            "deadline_risk_lambda": 2.0,
            "heavy_object_threshold": 32.0,
            "heavy_gpu_bonus": 2.0,
            "score_epsilon_ms": 1.0e-9,
            "resource_order": ["cpu", "gpu", "nvdec"],
            "object_feature": None,
            "object_feature_observed_at_ms": None,
            "object_feature_source": "unavailable",
        },
        "recorded_result": formal_replay_json_value(result),
    }
    return event, result


def replay_feedback_event(
    *,
    event_seq: int,
    feedback_seq: int,
    trace_id: str,
    source_decision_id: str,
    source_parameter_snapshot_seq: int,
    event_time_ms: float,
    old_weights: dict[str, float],
    current_parameter_snapshot_seq: int,
    current_update_seq: int,
    variation_before: float,
    policy_mode: str,
    first_consumer_decision_id: str | None,
    overloaded: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    if overloaded:
        states = {
            "cpu": ResourceFeedbackState(False, (), (), (), 0),
            "gpu": ResourceFeedbackState(True, (3,), (60.0,), (False, False), 0),
            "nvdec": ResourceFeedbackState(False, (), (), (), 0),
        }
        latency_ms = 120.0
    else:
        states = {
            resource: ResourceFeedbackState(False, (), (), (), current_update_seq)
            for resource in ("cpu", "gpu", "nvdec")
        }
        latency_ms = 80.0
    request = FeedbackRequest(
        terminal_status="completed",
        latency_ms=latency_ms,
        deadline_ms=100.0,
        feedback_seq=feedback_seq,
        current_parameter_snapshot_seq=current_parameter_snapshot_seq,
        source_decision_ids=(source_decision_id,),
        source_parameter_snapshot_seqs=(source_parameter_snapshot_seq,),
        old_weights=old_weights,
        lower_bounds={"cpu": 0.5, "gpu": 0.5, "nvdec": 0.5},
        upper_bounds={"cpu": 1.5, "gpu": 1.5, "nvdec": 1.5},
        resource_states=states,
        overload_queue_thresholds={"cpu": 1, "gpu": 1, "nvdec": 1},
        stable_queue_thresholds={"cpu": 1, "gpu": 1, "nvdec": 1},
        overload_wait_fraction=0.5,
        stable_wait_fraction=0.2,
        history_length=2,
        lag_limit=8,
        cooldown_events=1,
        penalty_step=0.1,
        reward_step=0.05,
        variation_before=variation_before,
        variation_budget=0.5,
        updates_enabled=policy_mode == "formal_online",
    )
    result = evaluate_feedback(request)
    resulting_snapshot = current_parameter_snapshot_seq + int(result["parameter_snapshot_seq_increment"])
    resulting_update = current_update_seq + int(result["update_seq_increment"])
    event = {
        "event_seq": event_seq,
        "kind": "feedback",
        "event_time_ms": event_time_ms,
        "trace_id": trace_id,
        "feedback_seq": feedback_seq,
        "current_parameter_snapshot_seq": current_parameter_snapshot_seq,
        "current_update_seq": current_update_seq,
        "source_decision_ids": [source_decision_id],
        "request": {
            "terminal_status": "completed",
            "latency_ms": latency_ms,
            "deadline_ms": 100.0,
            "source_parameter_snapshot_seqs": [source_parameter_snapshot_seq],
            "old_weights": dict(old_weights),
            "lower_bounds": {"cpu": 0.5, "gpu": 0.5, "nvdec": 0.5},
            "upper_bounds": {"cpu": 1.5, "gpu": 1.5, "nvdec": 1.5},
            "resource_states": {
                resource: state_payload(value) for resource, value in states.items()
            },
            "overload_queue_thresholds": {"cpu": 1, "gpu": 1, "nvdec": 1},
            "stable_queue_thresholds": {"cpu": 1, "gpu": 1, "nvdec": 1},
            "overload_wait_fraction": 0.5,
            "stable_wait_fraction": 0.2,
            "history_length": 2,
            "lag_limit": 8,
            "cooldown_events": 1,
            "penalty_step": 0.1,
            "reward_step": 0.05,
            "variation_before": variation_before,
            "variation_budget": 0.5,
            "updates_enabled": policy_mode == "formal_online",
        },
        "recorded_result": formal_replay_json_value(result),
        "first_consumer_decision_id": first_consumer_decision_id,
        "resulting_parameter_snapshot_seq": resulting_snapshot,
        "resulting_update_seq": resulting_update,
    }
    return event, result


def formal_replay_packet(policy_mode: str = "formal_online") -> dict[str, object]:
    graph_profile = {
        "graph_version": "fixture-video-dag-v1",
        "profile_version": "fixture-cost-profile-v1",
        "execution_costs_ms": {"detect": {"cpu": 10.0, "gpu": 4.0}},
        "successors": {"detect": []},
        "communication_costs_ms": [],
    }
    rank_u_ms = 7.0
    initial_weights = {"cpu": 1.0, "gpu": 1.0, "nvdec": 1.0}
    first_decision, _ = replay_decision_event(
        event_seq=1,
        decision_seq=1,
        decision_id="decision-1",
        trace_id="trace-1",
        decision_time_ms=100.0,
        rank_u_ms=rank_u_ms,
        weights=initial_weights,
        parameter_snapshot_seq=0,
    )
    first_feedback, first_feedback_result = replay_feedback_event(
        event_seq=2,
        feedback_seq=1,
        trace_id="trace-1",
        source_decision_id="decision-1",
        source_parameter_snapshot_seq=0,
        event_time_ms=130.0,
        old_weights=initial_weights,
        current_parameter_snapshot_seq=0,
        current_update_seq=0,
        variation_before=0.0,
        policy_mode=policy_mode,
        first_consumer_decision_id=("decision-2" if policy_mode == "formal_online" else None),
        overloaded=True,
    )
    events = [first_decision, first_feedback]
    if policy_mode == "formal_online":
        next_weights = {
            resource: float(first_feedback_result["new_weights"][resource])
            for resource in ("cpu", "gpu", "nvdec")
        }
        second_decision, _ = replay_decision_event(
            event_seq=3,
            decision_seq=2,
            decision_id="decision-2",
            trace_id="trace-2",
            decision_time_ms=131.0,
            rank_u_ms=rank_u_ms,
            weights=next_weights,
            parameter_snapshot_seq=1,
        )
        second_feedback, _ = replay_feedback_event(
            event_seq=4,
            feedback_seq=2,
            trace_id="trace-2",
            source_decision_id="decision-2",
            source_parameter_snapshot_seq=1,
            event_time_ms=150.0,
            old_weights=next_weights,
            current_parameter_snapshot_seq=1,
            current_update_seq=1,
            variation_before=float(first_feedback_result["variation_after"]),
            policy_mode=policy_mode,
            first_consumer_decision_id=None,
            overloaded=False,
        )
        events.extend([second_decision, second_feedback])
    return {
        "schema_version": 1,
        "implementation_id": "formal-aw-heft-reference-v1",
        "evidence_status": "replay_input_only_not_accepted_telemetry",
        "policy_mode": policy_mode,
        "numeric_tolerance": 1.0e-9,
        "graph_profile": graph_profile,
        "graph_profile_sha256": formal_graph_profile_sha256(graph_profile),
        "initial_state": {
            "parameter_snapshot_seq": 0,
            "update_seq": 0,
            "weights": initial_weights,
            "variation": 0.0,
        },
        "events": events,
    }


class FormalAwHeftReferenceTests(unittest.TestCase):
    def test_upward_rank_uses_mean_execution_and_communication_profiles(self) -> None:
        ranks = compute_upward_ranks(
            {
                "decode": {"cpu": 8.0, "nvdec": 2.0},
                "preprocess": {"cpu": 4.0, "gpu": 2.0},
                "detect": {"cpu": 10.0, "gpu": 4.0},
            },
            {"decode": ["preprocess"], "preprocess": ["detect"], "detect": []},
            {("decode", "preprocess"): [0.0, 2.0], ("preprocess", "detect"): [0.0, 4.0]},
        )

        self.assertEqual(ranks, {"detect": 7.0, "preprocess": 12.0, "decode": 18.0})

    def test_upward_rank_rejects_cycles_and_missing_edge_profiles(self) -> None:
        with self.assertRaisesRegex(FormalAwHeftError, "cycle"):
            compute_upward_ranks(
                {"a": {"cpu": 1.0}, "b": {"gpu": 1.0}},
                {"a": ["b"], "b": ["a"]},
                {("a", "b"): [0.0], ("b", "a"): [0.0]},
            )
        with self.assertRaisesRegex(FormalAwHeftError, "no compatible communication"):
            compute_upward_ranks(
                {"a": {"cpu": 1.0}, "b": {"gpu": 1.0}},
                {"a": ["b"], "b": []},
                {},
            )

    def test_ready_order_is_rank_deadline_arrival_trace_then_stage(self) -> None:
        selected = select_ready_task(
            [
                ReadyTask("a", 10.0, 150.0, 2.0, "trace-b"),
                ReadyTask("b", 11.0, 200.0, 1.0, "trace-z"),
                ReadyTask("c", 11.0, 100.0, 3.0, "trace-c"),
                ReadyTask("d", 11.0, 100.0, 2.0, "trace-d"),
                ReadyTask("e", 11.0, 100.0, 2.0, "trace-a"),
            ]
        )

        self.assertEqual(selected.stage_id, "e")

    def test_decision_exposes_all_resource_components_and_deadline_risk(self) -> None:
        result = evaluate_decision(decision_request())

        self.assertEqual(result["selected_resource"], "gpu")
        self.assertEqual(result["reason"], "minimum_aw_heft_score")
        self.assertEqual(set(result["alternatives"]), {"cpu", "gpu", "nvdec"})
        self.assertAlmostEqual(result["alternatives"]["cpu"]["finish_ms"], 116.0)
        self.assertAlmostEqual(result["alternatives"]["cpu"]["deadline_risk_ms"], 0.0)
        self.assertAlmostEqual(result["alternatives"]["gpu"]["finish_ms"], 113.0)
        self.assertTrue(result["alternatives"]["nvdec"]["weighted_score_ms"] == float("inf"))

        tighter = evaluate_decision(replace(decision_request(), deadline_ms=110.0))
        self.assertAlmostEqual(tighter["alternatives"]["cpu"]["deadline_risk_ms"], 6.0)
        self.assertAlmostEqual(tighter["alternatives"]["cpu"]["heft_score_ms"], 28.0)
        self.assertAlmostEqual(tighter["alternatives"]["gpu"]["heft_score_ms"], 19.0)

    def test_decision_is_invariant_to_common_monotonic_clock_shift(self) -> None:
        original = decision_request()
        shifted_candidates = {
            resource: replace(value, ready_ms=value.ready_ms + 1000.0, available_ms=value.available_ms + 1000.0)
            for resource, value in original.candidates.items()
        }
        shifted = replace(
            original,
            decision_time_ms=original.decision_time_ms + 1000.0,
            deadline_ms=original.deadline_ms + 1000.0,
            candidates=shifted_candidates,
        )

        first = evaluate_decision(original)
        second = evaluate_decision(shifted)
        self.assertEqual(first["selected_resource"], second["selected_resource"])
        for resource in ("cpu", "gpu"):
            self.assertAlmostEqual(
                first["alternatives"][resource]["weighted_score_ms"],
                second["alternatives"][resource]["weighted_score_ms"],
            )

    def test_heavy_feature_must_be_causally_available(self) -> None:
        base = decision_request()
        candidates = {
            "cpu": candidate(execution=10.0),
            "gpu": candidate(execution=12.0),
            "nvdec": candidate(allowed=False),
        }
        without_feature = evaluate_decision(replace(base, candidates=candidates, deadline_risk_lambda=0.0))
        with_feature = evaluate_decision(
            replace(
                base,
                candidates=candidates,
                deadline_risk_lambda=0.0,
                object_feature=40.0,
                object_feature_observed_at_ms=99.0,
                object_feature_source="previous_completed_frame",
            )
        )
        self.assertEqual(without_feature["selected_resource"], "cpu")
        self.assertEqual(with_feature["selected_resource"], "gpu")
        self.assertTrue(with_feature["alternatives"]["gpu"]["heavy_correction_applied"])

        with self.assertRaisesRegex(FormalAwHeftError, "not causally available"):
            evaluate_decision(
                replace(base, object_feature=40.0, object_feature_observed_at_ms=101.0)
            )

    def test_score_tie_uses_communication_then_queue_then_fixed_order(self) -> None:
        base = decision_request()
        communication_tie = evaluate_decision(
            replace(
                base,
                deadline_risk_lambda=0.0,
                candidates={
                    "cpu": candidate(communication=2.0, execution=8.0),
                    "gpu": candidate(communication=1.0, execution=9.0),
                    "nvdec": candidate(communication=3.0, execution=7.0),
                },
            )
        )
        self.assertEqual(communication_tie["selected_resource"], "gpu")
        self.assertEqual(communication_tie["reason"], "score_tie_lower_communication")

        queue_tie = evaluate_decision(
            replace(
                base,
                deadline_risk_lambda=0.0,
                candidates={
                    "cpu": candidate(execution=10.0, queue_depth=2),
                    "gpu": candidate(execution=10.0, queue_depth=1),
                    "nvdec": candidate(execution=10.0, queue_depth=3),
                },
            )
        )
        self.assertEqual(queue_tie["selected_resource"], "gpu")
        self.assertEqual(queue_tie["reason"], "score_tie_lower_queue_depth")

        order_tie = evaluate_decision(
            replace(
                base,
                deadline_risk_lambda=0.0,
                candidates={resource: candidate(execution=10.0) for resource in ("cpu", "gpu", "nvdec")},
                resource_order=("nvdec", "gpu", "cpu"),
            )
        )
        self.assertEqual(order_tie["selected_resource"], "nvdec")
        self.assertEqual(order_tie["reason"], "score_tie_fixed_resource_order")

    def test_projection_enforces_three_resource_box_and_mean_one(self) -> None:
        projected = project_box_mean_one(
            {"cpu": 2.0, "gpu": 1.0, "nvdec": 1.0},
            {"cpu": 0.5, "gpu": 0.5, "nvdec": 0.5},
            {"cpu": 1.5, "gpu": 1.5, "nvdec": 1.5},
        )

        self.assertAlmostEqual(projected["cpu"], 1.5)
        self.assertAlmostEqual(projected["gpu"], 0.75)
        self.assertAlmostEqual(projected["nvdec"], 0.75)
        self.assertAlmostEqual(sum(projected.values()) / 3.0, 1.0)

    def test_bad_overloaded_resource_is_penalized_atomically(self) -> None:
        result = evaluate_feedback(feedback_request())

        self.assertTrue(result["applied"])
        self.assertEqual(result["reason"], "atomic_bounded_weight_update")
        self.assertEqual(result["per_resource_reason"]["gpu"], "penalize_overloaded_resource")
        self.assertGreater(result["new_weights"]["gpu"], result["old_weights"]["gpu"])
        self.assertAlmostEqual(sum(result["new_weights"].values()) / 3.0, 1.0)
        self.assertEqual(result["update_seq_increment"], 1)

    def test_good_resource_requires_full_stable_history_before_reward(self) -> None:
        stable_state = ResourceFeedbackState(True, (0, 1), (5.0, 10.0), (False, False), 0)
        stable = evaluate_feedback(
            feedback_request(
                latency_ms=80.0,
                resource_states={
                    "cpu": ResourceFeedbackState(False, (), (), (), 0),
                    "gpu": stable_state,
                    "nvdec": ResourceFeedbackState(False, (), (), (), 0),
                },
            )
        )
        self.assertTrue(stable["applied"])
        self.assertEqual(stable["per_resource_reason"]["gpu"], "reward_stable_resource")
        self.assertLess(stable["new_weights"]["gpu"], stable["old_weights"]["gpu"])

        incomplete = evaluate_feedback(
            feedback_request(
                latency_ms=80.0,
                resource_states={
                    "cpu": ResourceFeedbackState(False, (), (), (), 0),
                    "gpu": replace(stable_state, history_bad=(False,)),
                    "nvdec": ResourceFeedbackState(False, (), (), (), 0),
                },
            )
        )
        self.assertFalse(incomplete["applied"])
        self.assertEqual(incomplete["per_resource_reason"]["gpu"], "insufficient_stable_history")

    def test_drop_censored_stale_and_cooldown_paths_do_not_reward(self) -> None:
        low_queue_states = {
            "cpu": ResourceFeedbackState(False, (), (), (), 0),
            "gpu": ResourceFeedbackState(True, (0,), (1.0,), (False, False), 0),
            "nvdec": ResourceFeedbackState(False, (), (), (), 0),
        }
        dropped = evaluate_feedback(
            feedback_request(terminal_status="drop", latency_ms=0.0, resource_states=low_queue_states)
        )
        self.assertFalse(dropped["applied"])
        self.assertEqual(dropped["per_resource_reason"]["gpu"], "drop_without_attributable_overload")

        censored = evaluate_feedback(feedback_request(terminal_status="censored"))
        self.assertFalse(censored["applied"])
        self.assertEqual(censored["reason"], "censored_feedback")

        stale = evaluate_feedback(
            feedback_request(current_parameter_snapshot_seq=10, source_parameter_snapshot_seqs=(1,))
        )
        self.assertFalse(stale["applied"])
        self.assertEqual(stale["reason"], "stale_feedback")

        cooldown_states = dict(feedback_request().resource_states)
        cooldown_states["gpu"] = replace(cooldown_states["gpu"], last_update_feedback_seq=2)
        cooldown = evaluate_feedback(feedback_request(resource_states=cooldown_states))
        self.assertFalse(cooldown["applied"])
        self.assertEqual(cooldown["reason"], "cooldown_active")

    def test_variation_budget_and_incomplete_source_are_fail_closed(self) -> None:
        exhausted = evaluate_feedback(feedback_request(variation_before=0.45, variation_budget=0.5))
        self.assertFalse(exhausted["applied"])
        self.assertEqual(exhausted["reason"], "variation_budget_exhausted")
        self.assertEqual(exhausted["new_weights"], exhausted["old_weights"])

        incomplete = evaluate_feedback(
            feedback_request(source_decision_ids=(), source_parameter_snapshot_seqs=())
        )
        self.assertFalse(incomplete["applied"])
        self.assertEqual(incomplete["reason"], "incomplete_source_decisions")

    def test_formal_frozen_mode_preserves_feedback_linkage_without_updates(self) -> None:
        result = evaluate_feedback(feedback_request(updates_enabled=False))

        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "updates_disabled_by_policy_mode")
        self.assertEqual(result["old_weights"], result["new_weights"])
        self.assertEqual(result["update_seq_increment"], 0)

    def test_formal_replay_verifies_online_state_and_first_consumer(self) -> None:
        packet = formal_replay_packet("formal_online")

        result = replay_formal_aw_heft_trace(packet)

        self.assertTrue(result["replay_verified"])
        self.assertFalse(result["evidence_accepted"])
        self.assertFalse(result["benchmark_eligible"])
        self.assertEqual(result["decision_count"], 2)
        self.assertEqual(result["feedback_count"], 2)
        self.assertEqual(result["applied_update_count"], 1)
        self.assertEqual(result["final_parameter_snapshot_seq"], 1)
        self.assertEqual(result["final_update_seq"], 1)

    def test_formal_replay_verifies_frozen_mode_as_no_update(self) -> None:
        result = replay_formal_aw_heft_trace(formal_replay_packet("formal_frozen"))

        self.assertTrue(result["replay_verified"])
        self.assertEqual(result["decision_count"], 1)
        self.assertEqual(result["feedback_count"], 1)
        self.assertEqual(result["applied_update_count"], 0)
        self.assertEqual(result["final_weights"], {"cpu": 1.0, "gpu": 1.0, "nvdec": 1.0})

    def test_formal_replay_fails_closed_on_graph_rank_and_decision_drift(self) -> None:
        mutations = []

        graph_hash = formal_replay_packet()
        graph_hash["graph_profile_sha256"] = "0" * 64
        mutations.append((graph_hash, "graph_profile_sha256"))

        rank = formal_replay_packet()
        rank["events"][0]["ready_tasks"][0]["recorded_rank_u_ms"] = 8.0
        mutations.append((rank, "recorded rank"))

        decision = formal_replay_packet()
        decision["events"][0]["recorded_result"]["selected_resource"] = "cpu"
        mutations.append((decision, "recorded_result.selected_resource"))

        allowed = formal_replay_packet()
        allowed["events"][0]["request"]["candidates"]["gpu"]["allowed"] = False
        mutations.append((allowed, "allowed candidates"))

        sequence = formal_replay_packet()
        sequence["events"][2]["parameter_snapshot_seq"] = 0
        mutations.append((sequence, "stale parameter snapshot"))

        for packet, message in mutations:
            with self.subTest(message=message):
                with self.assertRaisesRegex(FormalAwHeftError, message):
                    replay_formal_aw_heft_trace(packet)

    def test_formal_replay_fails_closed_on_source_mode_and_consumer_drift(self) -> None:
        source_set = formal_replay_packet()
        source_set["events"][1]["source_decision_ids"] = []
        with self.assertRaisesRegex(FormalAwHeftError, "source set"):
            replay_formal_aw_heft_trace(source_set)

        mode = formal_replay_packet()
        mode["events"][1]["request"]["updates_enabled"] = False
        with self.assertRaisesRegex(FormalAwHeftError, "policy_mode"):
            replay_formal_aw_heft_trace(mode)

        consumer = formal_replay_packet()
        consumer["events"][1]["first_consumer_decision_id"] = "different-decision"
        with self.assertRaisesRegex(FormalAwHeftError, "first consumer"):
            replay_formal_aw_heft_trace(consumer)

        incomplete = formal_replay_packet()
        incomplete["events"] = incomplete["events"][:2]
        with self.assertRaisesRegex(FormalAwHeftError, "ends before the first consumer"):
            replay_formal_aw_heft_trace(incomplete)

    def test_formal_replay_file_loader_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "duplicate.json"
            trace_path.write_text(
                '{"schema_version":1,"schema_version":1}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(FormalAwHeftError, "duplicate key schema_version"):
                load_formal_replay_packet(trace_path)

    def test_formal_replay_cli_reports_input_only_scope(self) -> None:
        artifact = ROOT / "policies" / "aw_heft_reference_v1.json"
        with tempfile.TemporaryDirectory() as tmp_dir:
            trace_path = Path(tmp_dir) / "formal-trace.json"
            trace_path.write_text(json.dumps(formal_replay_packet()), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "formal_aw_heft_reference.py"),
                    "--artifact",
                    str(artifact),
                    "--trace",
                    str(trace_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertTrue(result["replay_verified"])
        self.assertFalse(result["evidence_accepted"])
        self.assertFalse(result["benchmark_eligible"])
        self.assertEqual(result["status"], "formal_reference_replay_verified_input_not_accepted")

    def test_reference_artifact_and_cli_preserve_non_runtime_scope(self) -> None:
        artifact = ROOT / "policies" / "aw_heft_reference_v1.json"
        payload = validate_reference_artifact(artifact)
        self.assertEqual(payload["resource_scope"], ["cpu", "gpu", "nvdec"])
        self.assertFalse(payload["benchmark_eligible"])
        self.assertIsNone(payload["runtime_binding"])

        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "formal_aw_heft_reference.py"), "--artifact", str(artifact)],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["reference_contract_verified"])
        self.assertFalse(result["runtime_bound"])
        self.assertFalse(result["benchmark_eligible"])
        self.assertTrue(result["formal_reference_replay_implemented"])
        self.assertFalse(result["accepted_formal_trace_replay_performed"])
        self.assertEqual(result["artifact_sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
