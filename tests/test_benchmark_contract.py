#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_vast_report_artifacts as report_generator
import check_dataset as dataset_checker

from benchmark_contract import (
    BRANCH_TERMINAL_COLUMNS,
    CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
    ContractError,
    ENGINEERING_POLICY_DECISION_COLUMNS,
    FRAME_EVENT_COLUMNS,
    INGRESS_LEDGER_COLUMNS,
    POLICY_CAUSAL_TRACE_COLUMNS,
    POLICY_DECISION_COLUMNS,
    POLICY_FEEDBACK_COLUMNS,
    POLICY_TRACE_COLUMNS,
    PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
    PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS,
    PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE,
    PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
    PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
    RESET_EVIDENCE_COLUMNS,
    RESOURCE_EVENT_COLUMNS,
    STAGE_CONTRACT_COLUMNS,
    STAGE_SEMANTIC_CONTRACT_VERSION,
    build_publication_evidence_bundle,
    assess_decoder_placement,
    branch_analytics_contract_sha256,
    canonicalize_frames_csv,
    dataset_manifest_identity,
    evaluate_primary_policy_proxy_replay,
    load_dataset,
    network_profile_matches,
    publication_run_contract_identity,
    publication_evidence_bundle_identity,
    publication_evidence_bundle_files,
    resolve_publication_evidence_bundle_scope,
    resolve_publication_run_contract,
    resolve_scenario_contract,
    scenario_contract_identity,
    stage_base_name,
    semantic_prefix_contract_sha256,
    summarize_frames,
    summarize_measurement_passport,
    summarize_sidecars,
    validate_drop_counters,
    validate_branch_terminals,
    validate_frame_events,
    validate_ingress_ledger,
    validate_policy_decisions,
    validate_policy_feedback,
    validate_publication_evidence_bundle,
    validate_reset_evidence,
    validate_required_sidecars,
    validate_resource_events,
    validate_stage_trace_coverage,
    validate_stage_contracts,
    write_provenance_labeled_sidecars,
)
from generate_vast_report_artifacts import (
    build_primary_architecture_inference,
    build_primary_architecture_pairs_from_run_metrics,
    build_primary_policy_inference,
    build_primary_policy_pairs_from_run_metrics,
    build_shared_vs_duplicated,
    deadline_rows_for_frames,
    evaluate_primary_architecture_claim_state,
    evaluate_primary_policy_claim_state,
)
from deploy.savant.native_probe import BasePyFuncPlugin, SavantLocalTelemetryProbe, frame_event_filename, merge_local_outputs
from distributed_executor import _combine_csv, parse_chrony_tracking, parse_iperf_output, parse_ping_output
from rtp_trace import RtpTrace, pack_trace, unpack_trace


def native_frame_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "ingress_timestamp_ms": 100,
        "egress_timestamp_ms": 130,
        "e2e_latency_ms": 30,
        "objects": 1,
        "detector": "d",
        "backend": "b",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def native_event_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "stage": "decode",
        "role": "local",
        "host": "localhost",
        "resource": "cpu",
        "queue_enter_timestamp_ms": 100,
        "stage_start_timestamp_ms": 100,
        "stage_end_timestamp_ms": 110,
        "queue_depth": 0,
        "estimated_cost_ms": 10,
        "policy_action": "native:test",
    }
    row.update(overrides)
    return row


def ingress_ledger_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "cohort_id": "r:cohort:1",
        "trace_id": "r:0:1",
        "input_frame_key": "source:0:1",
        "admission_seq": 1,
        "source_sha256": "1" * 64,
        "source_cycle": 0,
        "access_unit_pts_ns": 90_000,
        "payload_sha256": "2" * 64,
        "payload_size_bytes": 4096,
        "schedule_offset_ns": 1_000_000,
        "stream_id": 0,
        "frame_id": 1,
        "ingress_timestamp_ms": 100.0,
        "window_start_timestamp_ms": 90.0,
        "window_end_timestamp_ms": 200.0,
        "terminal_status": "completed",
        "terminal_timestamp_ms": 130.0,
        "drain_end_timestamp_ms": 250.0,
        "terminal_reason": "native_output_committed",
        "censoring_rule": "fixed_drain_cutoff_v1",
        "ingress_provenance": "native_ingress_event",
        "terminal_provenance": "native_completion_event",
        "telemetry_source": "native",
    }
    row.update(overrides)
    sequence = int(row["frame_id"])
    if "admission_seq" not in overrides:
        row["admission_seq"] = sequence
    if "access_unit_pts_ns" not in overrides:
        row["access_unit_pts_ns"] = sequence * 90_000
    if "payload_sha256" not in overrides:
        row["payload_sha256"] = hashlib.sha256(str(row["input_frame_key"]).encode("utf-8")).hexdigest()
    if "schedule_offset_ns" not in overrides:
        row["schedule_offset_ns"] = sequence * 1_000_000
    return row


def reset_evidence_rows(*, topology_kind: str = "shared_video_dag") -> list[dict]:
    shared = topology_kind == "shared_video_dag"
    common = {
        "schema_version": 2,
        "reset_contract_version": 1,
        "run_id": "r",
        "cohort_id": "r:cohort:1",
        "stream_id": 0,
        "telemetry_sink_id": "c" * 64,
        "telemetry_sink_preexisting_entry_count": 0,
        "warmup_included_in_measurement": "false",
        "admission_stopped_before_drain": "true",
        "terminal_state": "DRAINED",
        "reset_provenance": "native_process_lifecycle_queue_and_sink_snapshot_v1",
        "telemetry_source": "native",
    }
    rows = [
        {
            **common,
            "process_instance_id": "stream-0-source-coordinator",
            "process_role": "source_coordinator",
            "branch_id": "not_applicable",
            "observed_pid": 1001,
            "process_start_token": "a" * 64,
            "ready_timestamp_ns": 1_000_000,
            "analytics_queue_depths_json": "{}",
            "source_cycle_first": 0,
            "admission_seq_first": 1,
        }
    ]
    if shared:
        rows.append(
            {
                **common,
                "process_instance_id": "stream-0-shared-video-dag",
                "process_role": "shared_graph_worker",
                "branch_id": "not_applicable",
                "observed_pid": 1002,
                "process_start_token": "b" * 64,
                "ready_timestamp_ns": 1_000_001,
                "analytics_queue_depths_json": '{"a":0,"b":0}',
                "source_cycle_first": -1,
                "admission_seq_first": -1,
            }
        )
    else:
        for index, branch in enumerate(("a", "b"), start=2):
            rows.append(
                {
                    **common,
                    "process_instance_id": f"stream-0-branch-{branch}",
                    "process_role": "independent_branch_worker",
                    "branch_id": branch,
                    "observed_pid": 1000 + index,
                    "process_start_token": f"{index:064x}",
                    "ready_timestamp_ns": 1_000_000 + index,
                    "analytics_queue_depths_json": json.dumps({branch: 0}),
                    "source_cycle_first": -1,
                    "admission_seq_first": -1,
                }
            )
    return rows


def resource_event_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "stage": "decode",
        "resource": "cpu",
        "timestamp_ms": 110.0,
        "cpu_time_ms": 10.0,
        "gpu_time_ms": 0.0,
        "h2d_bytes": 0,
        "d2h_bytes": 0,
        "nvdec_util_percent": 0.0,
        "vram_mb": 0.0,
        "time_provenance": "derived_from_native_stage_timestamps",
        "transfer_provenance": "unavailable",
        "nvdec_provenance": "unavailable",
        "vram_provenance": "unavailable",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def verified_detector_identity(detector_id: str, *, model_digit: str = "a") -> str:
    return (
        f"{detector_id};model_sha256={model_digit * 64};"
        f"weights_sha256={'b' * 64}"
    )


def branch_terminal_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "cohort_id": "r:cohort:1",
        "trace_id": "r:0:1",
        "input_frame_key": "source:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "branch_id": "damage",
        "terminal_status": "completed",
        "terminal_timestamp_ms": 130.0,
        "objects": 1,
        "detector": verified_detector_identity("native-damage-v1"),
        "backend": "openvino-dlstreamer:gvadetect",
        "terminal_reason": "native_result_committed",
        "terminal_provenance": "native_completion_event",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def stage_contract_row(**overrides):
    stage = str(overrides.get("stage", "decode"))
    base_stage = stage_base_name(stage)
    implementation_config = overrides.pop(
        "implementation_config",
        {"backend": "ffmpeg", "stage": base_stage, "settings": {"threads": 2}},
    )
    config_json = json.dumps(implementation_config, sort_keys=True, separators=(",", ":"))
    config_sha256 = hashlib.sha256(config_json.encode("utf-8")).hexdigest()
    implementation_artifacts = overrides.pop(
        "implementation_artifacts",
        [
            {
                "role": "stage_host",
                "logical_name": "vast-native-stage-runtime",
                "kind": "executable",
                "sha256": hashlib.sha256(b"stage-runtime").hexdigest(),
            },
            {
                "role": "stage_plugin",
                "logical_name": f"native-{base_stage}",
                "kind": "plugin",
                "sha256": hashlib.sha256(f"plugin-{base_stage}".encode("utf-8")).hexdigest(),
            },
        ],
    )
    implementation_artifacts_json = json.dumps(
        implementation_artifacts,
        sort_keys=True,
        separators=(",", ":"),
    )
    row = {
        "schema_version": 2,
        "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
        "run_id": "r",
        "contract_id": f"r:domain-a:{stage}",
        "execution_domain": "domain-a",
        "stage": stage,
        "base_stage": base_stage,
        "implementation_name": f"native-{base_stage}",
        "implementation_version": "1.0.0",
        "implementation_config_json": config_json,
        "config_sha256": config_sha256,
        "implementation_artifacts_json": implementation_artifacts_json,
        "implementation_artifacts_sha256": hashlib.sha256(
            implementation_artifacts_json.encode("utf-8")
        ).hexdigest(),
        "implementation_artifact_provenance": "runtime_loaded_artifacts_v1",
        "transform_json": json.dumps(
            {
                "resize": {"mode": "identity"},
                "normalization": {"mode": "identity"},
            },
            sort_keys=True,
        ),
        "output_media_type": "video/x-raw",
        "output_format": "rgb24",
        "output_dtype": "uint8",
        "output_shape_json": json.dumps([1080, 1920, 3]),
        "ordering_contract": "stream_frame_monotonic_v1",
        "contract_provenance": "runtime_loaded_configuration",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def stage_contract_topology(*domain_stages):
    return pd.DataFrame(
        [
            {
                "run_id": "r",
                "event_kind": "stage_complete",
                "execution_domain": domain,
                "stage": stage,
            }
            for domain, stage in domain_stages
        ]
    )


def write_publication_evidence_fixture(
    root: Path,
    *,
    scope: str = PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
) -> tuple[dict, dict]:
    for relative_name in publication_evidence_bundle_files(scope):
        path = root / relative_name
        if not path.exists():
            path.write_bytes((relative_name + "\n").encode("utf-8"))
    bundle = build_publication_evidence_bundle(root, scope=scope)
    identity = publication_evidence_bundle_identity(bundle)
    return bundle, identity


def full_policy_decision_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "stage": "detect",
        "policy": "ql_heft_online",
        "decision": "ql_heft_online:gpu",
        "resource": "gpu",
        "queue_depth": 1,
        "estimated_cost_ms": 2.0,
        "deadline_ms": 100.0,
        "policy_version": "aw-heft-v1",
        "allowed_resources_json": json.dumps(["cpu", "gpu"]),
        "alternative_scores_json": json.dumps({"cpu": 3.0, "gpu": 2.0}),
        "cost_components_json": json.dumps(
            {
                "cpu": {"queue_ms": 1.0, "exec_ms": 2.0},
                "gpu": {"queue_ms": 0.5, "exec_ms": 1.5},
            }
        ),
        "parameters_json": json.dumps({"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.8}}),
        "tie_break_rule": "transfer_then_queue_then_fixed_order",
        "decision_mode": "applied",
        "update_seq": 0,
        "update_json": "{}",
        "reason": "minimum_weighted_score",
        "decision_provenance": "native_scheduler_trace",
        "trace_completeness": "full",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def policy_update_json(
    *,
    old_gpu: float = 0.8,
    new_gpu: float = 0.9,
    gpu_queue_depth: int = 4,
) -> str:
    return json.dumps(
        {
            "reason": "deadline_miss_and_gpu_overload",
            "features": {
                "trace_id": "r:0:1",
                "latency_ms": 120.0,
                "deadline_ms": 100.0,
                "gpu_queue_depth": gpu_queue_depth,
                "terminal_status": "completed",
                "terminal_timestamp_ms": 120.0,
            },
            "old_weights": {"cpu": 1.0, "gpu": old_gpu},
            "new_weights": {"cpu": 1.0, "gpu": new_gpu},
        }
    )


def feature_provenance_json(
    *,
    trace_id: str = "r:0:1",
    observed_timestamp_ms: float = 99.0,
    decision_timestamp_ms: float = 100.0,
) -> str:
    return json.dumps(
        {
            "objects": {
                "source": "native_ingress_metadata",
                "source_trace_id": trace_id,
                "observed_timestamp_ms": observed_timestamp_ms,
                "age_ms": decision_timestamp_ms - observed_timestamp_ms,
                "estimator_version": "object-count-v1",
            }
        }
    )


def causal_policy_decision_row(**overrides):
    row = full_policy_decision_row()
    row.update(
        {
            "queue_depth": 4,
            "cost_components_json": json.dumps(
                {
                    "cpu": {"queue_depth": 0, "queue_ms": 1.0, "exec_ms": 2.0},
                    "gpu": {"queue_depth": 4, "queue_ms": 0.5, "exec_ms": 1.5},
                }
            ),
            "decision_id": "r:ql_heft_online:decision:1",
            "decision_seq": 1,
            "decision_timestamp_ms": 100.0,
            "graph_version": "video-dag-v1",
            "profile_version": "native-profile-v1",
            "feature_provenance_json": feature_provenance_json(),
            "terminal_status": "completed",
            "terminal_timestamp_ms": 120.0,
            "update_timestamp_ms": 0.0,
            "source_decision_ids_json": "[]",
            "first_consumer_decision_id": "unavailable",
            "first_consumer_decision_seq": 0,
            "causal_trace_completeness": "full",
        }
    )
    row.update(overrides)
    return row


def causal_update_consumer_row(*, update_json: str | None = None, **overrides):
    second_id = "r:ql_heft_online:decision:2"
    row = causal_policy_decision_row(
        trace_id="r:0:2",
        frame_id=2,
        decision_id=second_id,
        decision_seq=2,
        decision_timestamp_ms=130.0,
        feature_provenance_json=feature_provenance_json(
            trace_id="r:0:2",
            observed_timestamp_ms=129.0,
            decision_timestamp_ms=130.0,
        ),
        terminal_timestamp_ms=150.0,
        update_seq=1,
        update_json=update_json or policy_update_json(),
        parameters_json=json.dumps(
            {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
        ),
        update_timestamp_ms=125.0,
        source_decision_ids_json=json.dumps(["r:ql_heft_online:decision:1"]),
        first_consumer_decision_id=second_id,
        first_consumer_decision_seq=2,
    )
    row.update(overrides)
    return row


def bounded_policy_parameters(weights: dict[str, float]) -> str:
    return json.dumps(
        {
            "score_epsilon": 1e-9,
            "weights": weights,
            "weight_lower_bounds": {"cpu": 0.5, "gpu": 0.5},
            "weight_upper_bounds": {"cpu": 1.5, "gpu": 1.5},
            "projection_rule": "euclidean_box_mean_one_v1",
            "feedback_lag_limit": 1,
            "feedback_cooldown_events": 1,
            "variation_budget": 0.4,
            "feedback_update_rule": "simplified_gpu_queue_terminal_signal_v1",
            "feedback_update_parameters": {"penalty_step": 0.1, "reward_step": 0.01},
        },
        sort_keys=True,
    )


def bounded_policy_update_json() -> str:
    return json.dumps(
        {
            "reason": "prototype_deadline_miss_with_gpu_backlog",
            "features": {
                "trace_id": "r:0:1",
                "latency_ms": 120.0,
                "deadline_ms": 100.0,
                "gpu_queue_depth": 4,
                "terminal_status": "completed",
                "terminal_timestamp_ms": 120.0,
            },
            "old_weights": {"cpu": 1.1, "gpu": 0.9},
            "new_weights": {"cpu": 1.05, "gpu": 0.95},
        },
        sort_keys=True,
    )


def bounded_policy_decisions() -> pd.DataFrame:
    first_id = "r:ql_heft_online:decision:1"
    second_id = "r:ql_heft_online:decision:2"
    rows = [
        causal_policy_decision_row(
            decision_id=first_id,
            parameters_json=bounded_policy_parameters({"cpu": 1.1, "gpu": 0.9}),
        ),
        causal_policy_decision_row(
            trace_id="r:0:2",
            frame_id=2,
            decision_id=second_id,
            decision_seq=2,
            decision_timestamp_ms=130.0,
            feature_provenance_json=feature_provenance_json(
                trace_id="r:0:2",
                observed_timestamp_ms=129.0,
                decision_timestamp_ms=130.0,
            ),
            terminal_timestamp_ms=150.0,
            update_seq=1,
            update_json=bounded_policy_update_json(),
            parameters_json=bounded_policy_parameters({"cpu": 1.05, "gpu": 0.95}),
            update_timestamp_ms=125.0,
            source_decision_ids_json=json.dumps([first_id]),
            first_consumer_decision_id=second_id,
            first_consumer_decision_seq=2,
        ),
    ]
    return pd.DataFrame(rows, columns=POLICY_DECISION_COLUMNS)


def bounded_policy_feedback_rows() -> list[dict]:
    common = {
        "schema_version": 2,
        "run_id": "r",
        "policy": "ql_heft_online",
        "weight_lower_bounds_json": json.dumps({"cpu": 0.5, "gpu": 0.5}),
        "weight_upper_bounds_json": json.dumps({"cpu": 1.5, "gpu": 1.5}),
        "projection_rule": "euclidean_box_mean_one_v1",
        "variation_budget": 0.4,
        "feedback_provenance": "native_terminal_feedback",
        "feedback_trace_completeness": "full",
        "telemetry_source": "native",
    }
    return [
        {
            **common,
            "feedback_seq": 1,
            "feedback_timestamp_ms": 125.0,
            "source_trace_id": "r:0:1",
            "terminal_status": "completed",
            "terminal_timestamp_ms": 120.0,
            "source_decision_ids_json": json.dumps(["r:ql_heft_online:decision:1"]),
            "source_parameter_snapshot_seq": 0,
            "parameter_lag": 0,
            "events_since_update": 1,
            "old_weights_json": json.dumps({"cpu": 1.1, "gpu": 0.9}),
            "raw_weights_json": json.dumps({"cpu": 1.1, "gpu": 1.0}),
            "projected_weights_json": json.dumps({"cpu": 1.05, "gpu": 0.95}),
            "variation_before": 0.0,
            "variation_after": 0.1,
            "feedback_features_json": json.dumps(
                {
                    "trace_id": "r:0:1",
                    "terminal_status": "completed",
                    "terminal_timestamp_ms": 120.0,
                    "latency_ms": 120.0,
                    "gpu_queue_depth": 4,
                }
            ),
            "feedback_action": "update",
            "reason": "prototype_deadline_miss_with_gpu_backlog",
            "update_seq": 1,
            "first_consumer_decision_id": "r:ql_heft_online:decision:2",
            "first_consumer_decision_seq": 2,
        },
        {
            **common,
            "feedback_seq": 2,
            "feedback_timestamp_ms": 155.0,
            "source_trace_id": "r:0:2",
            "terminal_status": "completed",
            "terminal_timestamp_ms": 150.0,
            "source_decision_ids_json": json.dumps(["r:ql_heft_online:decision:2"]),
            "source_parameter_snapshot_seq": 1,
            "parameter_lag": 0,
            "events_since_update": 1,
            "old_weights_json": json.dumps({"cpu": 1.05, "gpu": 0.95}),
            "raw_weights_json": json.dumps({"cpu": 1.05, "gpu": 0.95}),
            "projected_weights_json": json.dumps({"cpu": 1.05, "gpu": 0.95}),
            "variation_before": 0.1,
            "variation_after": 0.1,
            "feedback_features_json": json.dumps(
                {
                    "trace_id": "r:0:2",
                    "terminal_status": "completed",
                    "terminal_timestamp_ms": 150.0,
                    "latency_ms": 110.0,
                    "gpu_queue_depth": 1,
                }
            ),
            "feedback_action": "no_op",
            "reason": "no_weight_update",
            "update_seq": 1,
            "first_consumer_decision_id": "unavailable",
            "first_consumer_decision_seq": 0,
        },
    ]


def primary_proxy_parameters() -> str:
    return json.dumps(
        {
            "score_epsilon": 1e-9,
            "weights": {"cpu": 1.322315, "gpu": 0.677685},
            "weight_lower_bounds": {"cpu": 0.5, "gpu": 0.5},
            "weight_upper_bounds": {"cpu": 1.5, "gpu": 1.5},
            "projection_rule": "euclidean_box_mean_one_v1",
            "feedback_lag_limit": 8,
            "feedback_cooldown_events": 2,
            "variation_budget": 0.25,
            "feedback_update_rule": "simplified_gpu_queue_terminal_signal_v1",
            "feedback_update_parameters": {"penalty_step": 0.002, "reward_step": 0.0002},
            "heavy_gpu_bonus": 1.968103,
            "heavy_object_threshold": 32,
            "heavy_scene": False,
            "stage_preference": "gpu",
            "policy_scope": "simplified_cpu_gpu_queue_weighted_proxy",
        },
        sort_keys=True,
    )


def primary_proxy_decision_row(*, policy: str, run_id: str) -> dict:
    trace_id = f"{run_id}:0:1"
    decision_id = f"{run_id}:{policy}:decision:1"
    cpu_score = 2.0 * 1.1 * 1.322315
    gpu_score = 2.0 * 1.0 * 1.1 * 0.677685
    provenance_entry = {
        "source": "native_scheduler_snapshot",
        "source_trace_id": f"{run_id}:{policy}",
        "observed_timestamp_ms": 99.0,
        "age_ms": 1.0,
        "estimator_version": "proxy-replay-test-v1",
    }
    return {
        "schema_version": 2,
        "run_id": run_id,
        "trace_id": trace_id,
        "stream_id": 0,
        "frame_id": 1,
        "stage": "detect",
        "policy": policy,
        "decision": f"{policy}:gpu",
        "resource": "gpu",
        "queue_depth": 1,
        "estimated_cost_ms": gpu_score,
        "deadline_ms": 100.0,
        "policy_version": (
            "simplified-cpu-gpu-weighted-proxy-v4-online"
            if policy.endswith("_online")
            else "simplified-cpu-gpu-weighted-proxy-v4-frozen"
        ),
        "allowed_resources_json": json.dumps(["cpu", "gpu"]),
        "alternative_scores_json": json.dumps({"cpu": cpu_score, "gpu": gpu_score}),
        "cost_components_json": json.dumps(
            {
                "cpu": {
                    "profile_exec_proxy_ms": 2.0,
                    "object_multiplier": 1.1,
                    "queue_depth": 0,
                    "active_tasks": 0,
                    "queue_wait_proxy_ms": 0.0,
                    "weight": 1.322315,
                    "heavy_multiplier": 1.0,
                },
                "gpu": {
                    "profile_exec_proxy_ms": 1.0,
                    "object_multiplier": 1.1,
                    "queue_depth": 1,
                    "active_tasks": 0,
                    "queue_wait_proxy_ms": 1.1,
                    "weight": 0.677685,
                    "heavy_multiplier": 1.0,
                },
            },
            sort_keys=True,
        ),
        "parameters_json": primary_proxy_parameters(),
        "tie_break_rule": "score_then_queue_depth_then_stage_preference",
        "decision_mode": "applied",
        "update_seq": 0,
        "update_json": "{}",
        "reason": "minimum_weighted_proxy_score",
        "decision_id": decision_id,
        "decision_seq": 1,
        "decision_timestamp_ms": 100.0,
        "graph_version": "proxy-replay-graph-v1",
        "profile_version": "custom-signal-stage-proxy-v2",
        "feature_provenance_json": json.dumps({"scheduler_snapshot": provenance_entry}),
        "terminal_status": "completed",
        "terminal_timestamp_ms": 120.0,
        "update_timestamp_ms": 0.0,
        "source_decision_ids_json": "[]",
        "first_consumer_decision_id": "unavailable",
        "first_consumer_decision_seq": 0,
        "causal_trace_completeness": "full",
        "decision_provenance": "native_scheduler_trace",
        "trace_completeness": "full",
        "telemetry_source": "native",
    }


def primary_proxy_feedback_row(*, run_id: str) -> dict:
    policy = "ql_heft_online"
    decision_id = f"{run_id}:{policy}:decision:1"
    weights = {"cpu": 1.322315, "gpu": 0.677685}
    return {
        "schema_version": 2,
        "run_id": run_id,
        "policy": policy,
        "feedback_seq": 1,
        "feedback_timestamp_ms": 125.0,
        "source_trace_id": f"{run_id}:0:1",
        "terminal_status": "completed",
        "terminal_timestamp_ms": 120.0,
        "source_decision_ids_json": json.dumps([decision_id]),
        "source_parameter_snapshot_seq": 0,
        "parameter_lag": 0,
        "events_since_update": 1,
        "old_weights_json": json.dumps(weights),
        "raw_weights_json": json.dumps(weights),
        "projected_weights_json": json.dumps(weights),
        "weight_lower_bounds_json": json.dumps({"cpu": 0.5, "gpu": 0.5}),
        "weight_upper_bounds_json": json.dumps({"cpu": 1.5, "gpu": 1.5}),
        "projection_rule": "euclidean_box_mean_one_v1",
        "variation_before": 0.0,
        "variation_after": 0.0,
        "variation_budget": 0.25,
        "feedback_features_json": json.dumps(
            {
                "trace_id": f"{run_id}:0:1",
                "terminal_status": "completed",
                "terminal_timestamp_ms": 120.0,
                "latency_ms": 90.0,
                "deadline_ms": 100.0,
                "gpu_queue_depth": 1,
            },
            sort_keys=True,
        ),
        "feedback_action": "no_op",
        "reason": "cooldown_active",
        "update_seq": 0,
        "first_consumer_decision_id": "unavailable",
        "first_consumer_decision_seq": 0,
        "feedback_provenance": "native_terminal_feedback",
        "feedback_trace_completeness": "full",
        "telemetry_source": "native",
    }


def primary_proxy_runtime_metadata() -> dict:
    return {
        "mode": "benchmark",
        "ql_heft_policy_artifact": {
            "path": "policies/ql_heft_frozen.policy",
            "sha256": "0a961ae5e9e500dc3f07b386743b1a17c1991398018a44c5756d0f3a3b6045b5",
        },
    }


def write_savant_event_fragments(stream_dir: Path, rows: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["stage"]), []).append(row)
    for stage, stage_rows in grouped.items():
        pd.DataFrame(stage_rows).to_csv(stream_dir / frame_event_filename(stage), index=False)


class BenchmarkContractTests(unittest.TestCase):
    def test_smoke_legacy_csv_is_canonicalized_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "objects": 2, "latency_ms": 12.5}]
            ).to_csv(path, index=False)
            df = canonicalize_frames_csv(path, mode="smoke", run_id="r", detector="d", backend="b")
            self.assertEqual(df.iloc[0]["telemetry_source"], "synthetic")
            self.assertEqual(float(df.iloc[0]["e2e_latency_ms"]), 12.5)

    def test_benchmark_rejects_legacy_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame([{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "latency_ms": 1}]).to_csv(
                path, index=False
            )
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_rejects_schema_v2_synthetic_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 120,
                        "e2e_latency_ms": 20,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "synthetic",
                    }
                ]
            ).to_csv(path, index=False)
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_requires_frame_event_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame_events.csv"
            pd.DataFrame([{"schema_version": 2, "run_id": "r"}]).to_csv(path, index=False)
            with self.assertRaises(ContractError):
                validate_frame_events(path)

    def test_benchmark_rejects_missing_native_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(root / "frames.csv", mode="benchmark", run_id="r", detector="d", backend="b")
            with self.assertRaises(ContractError):
                validate_frame_events(root / "frame_events.csv")

    def test_rtp_trace_roundtrip(self) -> None:
        trace = RtpTrace(stream_id=3, frame_id=42, ingress_timestamp_ms=123456789)
        self.assertEqual(unpack_trace(pack_trace(trace)), trace)

    def test_native_frames_and_events_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 120,
                        "e2e_latency_ms": 20,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "stage": "aggregate",
                        "role": "aggregator",
                        "host": "localhost",
                        "resource": "cpu",
                        "queue_enter_timestamp_ms": 119,
                        "stage_start_timestamp_ms": 119,
                        "stage_end_timestamp_ms": 120,
                        "queue_depth": 0,
                        "estimated_cost_ms": 1,
                        "policy_action": "native:cpu",
                    }
                ]
            ).to_csv(events, index=False)

            canonicalize_frames_csv(frames, mode="benchmark", run_id="r", detector="d", backend="b")
            validate_frame_events(events)

    def test_required_sidecars_are_derived_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row(), native_frame_row(trace_id="r:0:2", frame_id=2, e2e_latency_ms=120)])
            events = pd.DataFrame(
                [
                    native_event_row(stage="decode", resource="cpu"),
                    native_event_row(stage="preprocess", resource="cpu"),
                    native_event_row(stage="plate_number", resource="gpu"),
                ]
            )
            dataset = {
                "streams": [
                    {"stream_id": 0, "camera_role": "plate_number", "width": 1920, "height": 1080},
                ]
            }

            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset=dataset,
                policy="heft",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)

            resources = validate_resource_events(root / "resource_events.csv")
            decisions = validate_policy_decisions(root / "policy_decisions.csv")
            self.assertEqual(set(resources["time_provenance"]), {"derived_from_native_stage_timestamps"})
            self.assertEqual(set(resources["transfer_provenance"]), {"estimated_from_frame_dimensions"})
            self.assertEqual(set(decisions["trace_completeness"]), {"selected_action_only"})
            drops = validate_drop_counters(root / "drop_counters.csv")
            self.assertEqual(float(drops.iloc[0]["late_rate_percent"]), 50.0)
            self.assertEqual(set(drops["drop_provenance"]), {"inferred_from_frame_id_gaps"})
            validate_required_sidecars(root, require_labeled_provenance=True)

            summary = summarize_sidecars(root)
            self.assertTrue(pd.isna(summary["h2d_bytes"]))
            self.assertTrue(pd.isna(summary["d2h_bytes"]))
            self.assertTrue(pd.isna(summary["nvdec_utilization_percent"]))
            self.assertTrue(pd.isna(summary["dropped_frame_rate_percent"]))
            self.assertEqual(summary["late_frame_rate_percent"], 50.0)
            self.assertFalse(summary["policy_trace_complete"])
            self.assertFalse(summary["policy_causal_trace_complete"])
            self.assertFalse(summary["ingress_ledger_complete"])
            self.assertTrue(pd.isna(summary["ingress_frame_count"]))
            self.assertFalse(summary["stage_semantic_contract_complete"])
            self.assertEqual(summary["semantic_prefix_contract_sha256"], "unavailable")
            with self.assertRaisesRegex(ContractError, "without a replayable full policy trace"):
                validate_policy_decisions(root / "policy_decisions.csv", require_full_trace=True)

    def test_stage_contracts_validate_semantic_prefix_and_stable_hash(self) -> None:
        topology = stage_contract_topology(
            ("domain-a", "decode_plate_number"),
            ("domain-a", "preprocess_plate_number"),
            ("domain-b", "decode_damage"),
            ("domain-b", "preprocess_damage"),
        )
        rows = [
            stage_contract_row(
                execution_domain=domain,
                stage=stage,
                contract_id=f"r:{domain}:{stage}",
            )
            for domain, stage in zip(topology["execution_domain"], topology["stage"])
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stage_contracts.csv"
            pd.DataFrame(rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(path, index=False)

            contracts = validate_stage_contracts(path, topology_events=topology)
            prefix_hash = semantic_prefix_contract_sha256(contracts)

            self.assertTrue(bool(contracts["semantic_contract_claim_eligible"].all()))
            self.assertRegex(prefix_hash, r"^[0-9a-f]{64}$")

            changed_rows = []
            for row in rows:
                changed = dict(row)
                if changed["base_stage"] == "decode":
                    artifacts = json.loads(changed["implementation_artifacts_json"])
                    artifacts[-1]["sha256"] = "f" * 64
                    artifacts_json = json.dumps(
                        artifacts,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    changed["implementation_artifacts_json"] = artifacts_json
                    changed["implementation_artifacts_sha256"] = hashlib.sha256(
                        artifacts_json.encode("utf-8")
                    ).hexdigest()
                changed_rows.append(changed)
            pd.DataFrame(changed_rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(path, index=False)
            changed_contracts = validate_stage_contracts(path, topology_events=topology)
            self.assertNotEqual(
                semantic_prefix_contract_sha256(changed_contracts),
                prefix_hash,
            )

    def test_decoder_placement_requires_allowed_nvdec_factory(self) -> None:
        topology = stage_contract_topology(
            ("domain-a", "decode"),
            ("domain-a", "preprocess"),
        )

        def validated_contracts(factory: str) -> pd.DataFrame:
            rows = [
                stage_contract_row(
                    stage="decode",
                    contract_id="r:domain-a:decode",
                    implementation_config={
                        "backend": "gstreamer",
                        "stage": "decode",
                        "decoder_factory": factory,
                    },
                ),
                stage_contract_row(
                    stage="preprocess",
                    contract_id="r:domain-a:preprocess",
                ),
            ]
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "stage_contracts.csv"
                pd.DataFrame(rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(path, index=False)
                return validate_stage_contracts(path, topology_events=topology)

        for factory in ("nvh264dec", "nvv4l2decoder"):
            with self.subTest(factory=factory):
                assessment = assess_decoder_placement(
                    validated_contracts(factory),
                    PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
                )
                self.assertTrue(assessment["decoder_placement_verified"])
                self.assertTrue(assessment["decoder_factory_allowed"])
                self.assertEqual(assessment["decoder_factory"], factory)
                self.assertEqual(
                    assessment["decoder_placement_evidence_limit"],
                    "factory_selection_does_not_measure_nvdec_busy_time",
                )

        software = assess_decoder_placement(
            validated_contracts("avdec_h264"),
            PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
        )
        self.assertFalse(software["decoder_placement_verified"])
        self.assertFalse(software["decoder_factory_allowed"])
        self.assertEqual(software["decoder_factory"], "avdec_h264")

        incomplete = assess_decoder_placement(
            pd.DataFrame(
                {
                    "base_stage": ["decode", "decode"],
                    "implementation_config_json": [
                        json.dumps({"decoder_factory": "nvh264dec"}),
                        json.dumps({"stage": "decode"}),
                    ],
                }
            ),
            PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
        )
        self.assertFalse(incomplete["decoder_factory_identity_complete"])
        self.assertFalse(incomplete["decoder_placement_verified"])
        self.assertEqual(incomplete["decoder_factory"], "unavailable")

    def test_required_sidecars_require_native_stage_contracts_for_topology_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row()])
            events = pd.DataFrame(
                [
                    native_event_row(stage="decode"),
                    native_event_row(stage="preprocess", stage_start_timestamp_ms=110, stage_end_timestamp_ms=120),
                ]
            )
            topology = stage_contract_topology(("domain-a", "decode"), ("domain-a", "preprocess"))
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset={"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]},
                policy="heft",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)

            with self.assertRaisesRegex(ContractError, "stage_contracts.csv was not produced"):
                validate_required_sidecars(
                    root,
                    require_stage_contracts=True,
                    topology_events=topology,
                )

            rows = [
                stage_contract_row(stage="decode", contract_id="r:domain-a:decode"),
                stage_contract_row(stage="preprocess", contract_id="r:domain-a:preprocess"),
            ]
            pd.DataFrame(rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(
                root / "stage_contracts.csv",
                index=False,
            )
            sidecars = validate_required_sidecars(
                root,
                require_stage_contracts=True,
                topology_events=topology,
            )
            summary = summarize_sidecars(root, topology_events=topology)

            self.assertIn("stage_contracts", sidecars)
            self.assertTrue(summary["stage_semantic_contract_complete"])
            self.assertEqual(
                summary["semantic_contract_version"],
                STAGE_SEMANTIC_CONTRACT_VERSION,
            )
            self.assertRegex(summary["semantic_prefix_contract_sha256"], r"^[0-9a-f]{64}$")

    def test_stage_contracts_reject_bad_hash_or_incomplete_topology_coverage(self) -> None:
        topology = stage_contract_topology(("domain-a", "decode"), ("domain-a", "preprocess"))
        cases = [
            (
                [
                    stage_contract_row(stage="decode", config_sha256="A" * 64),
                    stage_contract_row(stage="preprocess", contract_id="r:domain-a:preprocess"),
                ],
                "lowercase SHA-256",
            ),
            (
                [
                    stage_contract_row(
                        stage="decode",
                        implementation_artifacts_sha256="A" * 64,
                    ),
                    stage_contract_row(stage="preprocess", contract_id="r:domain-a:preprocess"),
                ],
                "implementation_artifacts_sha256 must be a lowercase SHA-256",
            ),
            (
                [
                    stage_contract_row(
                        stage="decode",
                        implementation_artifact_provenance="configuration_declared_artifacts",
                    ),
                    stage_contract_row(stage="preprocess", contract_id="r:domain-a:preprocess"),
                ],
                "stage artifacts must come from runtime_loaded_artifacts_v1",
            ),
            ([stage_contract_row(stage="decode")], "do not exactly cover topology"),
        ]
        for rows, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "stage_contracts.csv"
                pd.DataFrame(rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_stage_contracts(path, topology_events=topology)

    def test_stage_contracts_reject_branch_mismatch_or_underspecified_transform(self) -> None:
        topology = stage_contract_topology(
            ("domain-a", "decode_plate_number"),
            ("domain-a", "preprocess_plate_number"),
            ("domain-b", "decode_damage"),
            ("domain-b", "preprocess_damage"),
        )
        rows = [
            stage_contract_row(
                execution_domain=domain,
                stage=stage,
                contract_id=f"r:{domain}:{stage}",
            )
            for domain, stage in zip(topology["execution_domain"], topology["stage"])
        ]
        cases = [
            (
                [{**row, "output_format": "bgr24"} if row["stage"] == "decode_damage" else row for row in rows],
                "decode contracts differ across execution domains",
            ),
            (
                [
                    {
                        **row,
                        "implementation_artifacts_json": json.dumps(
                            [
                                {
                                    **artifact,
                                    "sha256": "f" * 64,
                                }
                                if artifact["role"] == "stage_plugin"
                                else artifact
                                for artifact in json.loads(row["implementation_artifacts_json"])
                            ],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    if row["stage"] == "decode_damage"
                    else row
                    for row in rows
                ],
                "implementation_artifacts_sha256 does not match",
            ),
            (
                [
                    {
                        **row,
                        "transform_json": json.dumps({"resize": {"mode": "identity"}}),
                    }
                    if row["stage"] == "preprocess_damage"
                    else row
                    for row in rows
                ],
                "must contain exactly resize and normalization",
            ),
            (
                [{**row, "output_shape_json": "[]"} if row["stage"] == "decode_damage" else row for row in rows],
                "output_shape_json must not be empty",
            ),
        ]
        for case_rows, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "stage_contracts.csv"
                pd.DataFrame(case_rows, columns=STAGE_CONTRACT_COLUMNS).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_stage_contracts(path, topology_events=topology)

    def test_native_ingress_ledger_closes_completed_drop_and_censored_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ingress_ledger.csv"
            rows = [
                ingress_ledger_row(),
                ingress_ledger_row(
                    trace_id="r:0:2",
                    input_frame_key="source:0:2",
                    frame_id=2,
                    ingress_timestamp_ms=120.0,
                    terminal_status="drop",
                    terminal_timestamp_ms=140.0,
                    terminal_reason="queue_overflow",
                    terminal_provenance="native_drop_event",
                ),
                ingress_ledger_row(
                    trace_id="r:0:3",
                    input_frame_key="source:0:3",
                    frame_id=3,
                    ingress_timestamp_ms=190.0,
                    terminal_status="censored",
                    terminal_timestamp_ms=250.0,
                    terminal_reason="drain_cutoff",
                    terminal_provenance="explicit_censoring_at_drain_end",
                ),
            ]
            pd.DataFrame(rows, columns=INGRESS_LEDGER_COLUMNS).to_csv(path, index=False)
            frames = pd.DataFrame([native_frame_row()])
            drops = pd.DataFrame(
                [{"stream_id": 0, "dropped_frames": 1, "drop_provenance": "native_drop_event"}]
            )

            ledger = validate_ingress_ledger(path, frames=frames, drop_counters=drops)

            self.assertTrue(bool(ledger["ingress_claim_eligible"].all()))
            self.assertEqual(set(ledger["terminal_status"]), {"completed", "drop", "censored"})

    def test_measurement_passport_hashes_schedule_and_attributes_complete_prefix_work(self) -> None:
        ingress = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        events = pd.DataFrame(
            [
                native_event_row(
                    queue_enter_timestamp_ms=100.0,
                    stage_start_timestamp_ms=102.0,
                    stage_end_timestamp_ms=112.0,
                ),
                native_event_row(
                    stage="preprocess",
                    resource="gpu",
                    queue_enter_timestamp_ms=110.0,
                    stage_start_timestamp_ms=112.0,
                    stage_end_timestamp_ms=120.0,
                ),
            ],
            columns=FRAME_EVENT_COLUMNS,
        )
        resources = pd.DataFrame(
            [
                resource_event_row(),
                resource_event_row(
                    stage="preprocess",
                    resource="gpu",
                    timestamp_ms=120.0,
                    cpu_time_ms=0.0,
                    gpu_time_ms=8.0,
                ),
            ],
            columns=RESOURCE_EVENT_COLUMNS,
        )

        passport = summarize_measurement_passport(resources, ingress, events)

        self.assertTrue(passport["resource_attribution_complete"])
        self.assertEqual(
            passport["resource_attribution"],
            "native_per_trace_bounded_stage_interval_ingress_cohort_v3",
        )
        self.assertRegex(passport["input_schedule_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(passport["input_frame_key_sequence_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(passport["measurement_signature"], r"^[0-9a-f]{64}$")
        self.assertEqual(passport["measurement_window_duration_ms"], 110.0)
        self.assertEqual(passport["c_obs_total_ms"], 18.0)
        self.assertEqual(passport["c_obs_cpu_total_ms"], 10.0)
        self.assertEqual(passport["c_obs_gpu_total_ms"], 8.0)
        self.assertEqual(passport["c_obs_in_ms_per_ingress"], 18.0)
        self.assertEqual(passport["c_obs_cpu_in_ms_per_ingress"], 10.0)
        self.assertEqual(passport["c_obs_gpu_in_ms_per_ingress"], 8.0)
        self.assertEqual(passport["c_obs_comp_ms_per_completed"], 18.0)
        self.assertTrue(passport["c_obs_is_partial"])
        signature_payload = json.loads(passport["measurement_signature_payload_json"])
        self.assertEqual(
            passport["measurement_signature_payload_json"],
            json.dumps(
                signature_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )
        self.assertEqual(signature_payload["contract_version"], 4)
        self.assertEqual(
            signature_payload["resource_time_aggregation"],
            "unweighted_sum_of_attributed_device_milliseconds_v1",
        )
        self.assertEqual(
            signature_payload["resource_time_non_equivalence"],
            "not_energy_flops_monetary_cost_or_cross_device_equivalent_work_v1",
        )

        drifted = ingress.copy()
        drifted.loc[0, "schedule_offset_ns"] += 1
        drifted_passport = summarize_measurement_passport(resources, drifted, events)
        self.assertNotEqual(passport["input_schedule_sha256"], drifted_passport["input_schedule_sha256"])
        self.assertEqual(
            passport["input_frame_key_sequence_sha256"],
            drifted_passport["input_frame_key_sequence_sha256"],
        )

    def test_measurement_passport_rejects_unattributed_or_incomplete_resource_work(self) -> None:
        ingress = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        events = pd.DataFrame(
            [
                native_event_row(),
                native_event_row(
                    stage="preprocess",
                    stage_start_timestamp_ms=112.0,
                    stage_end_timestamp_ms=120.0,
                ),
            ],
            columns=FRAME_EVENT_COLUMNS,
        )
        incomplete = pd.DataFrame([resource_event_row()], columns=RESOURCE_EVENT_COLUMNS)
        self.assertFalse(
            summarize_measurement_passport(incomplete, ingress, events)[
                "resource_attribution_complete"
            ]
        )

        outside = pd.DataFrame(
            [
                resource_event_row(),
                resource_event_row(stage="preprocess", timestamp_ms=120.0),
                resource_event_row(
                    trace_id="r:0:2",
                    frame_id=2,
                    stage="decode",
                    timestamp_ms=125.0,
                ),
            ],
            columns=RESOURCE_EVENT_COLUMNS,
        )
        passport = summarize_measurement_passport(outside, ingress, events)
        self.assertFalse(passport["resource_attribution_complete"])
        self.assertEqual(passport["resource_unattributed_event_count"], 1)

    def test_measurement_passport_rejects_duplicate_or_inconsistent_stage_intervals(self) -> None:
        ingress = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        events = pd.DataFrame(
            [
                native_event_row(),
                native_event_row(
                    stage="preprocess",
                    resource="gpu",
                    stage_start_timestamp_ms=112.0,
                    stage_end_timestamp_ms=120.0,
                ),
            ],
            columns=FRAME_EVENT_COLUMNS,
        )
        resources = pd.DataFrame(
            [
                resource_event_row(),
                resource_event_row(
                    stage="preprocess",
                    resource="gpu",
                    timestamp_ms=120.0,
                    cpu_time_ms=0.0,
                    gpu_time_ms=8.0,
                ),
            ],
            columns=RESOURCE_EVENT_COLUMNS,
        )

        duplicate = pd.concat([resources, resources.iloc[[0]]], ignore_index=True)
        self.assertFalse(
            summarize_measurement_passport(duplicate, ingress, events)[
                "resource_attribution_complete"
            ]
        )

        duplicate_stage = pd.concat([events, events.iloc[[0]]], ignore_index=True)
        self.assertFalse(
            summarize_measurement_passport(resources, ingress, duplicate_stage)[
                "resource_attribution_complete"
            ]
        )

        uncovered_stage = pd.concat(
            [
                events,
                pd.DataFrame(
                    [
                        native_event_row(
                            stage="detect",
                            stage_start_timestamp_ms=120.0,
                            stage_end_timestamp_ms=125.0,
                        )
                    ],
                    columns=FRAME_EVENT_COLUMNS,
                ),
            ],
            ignore_index=True,
        )
        self.assertFalse(
            summarize_measurement_passport(resources, ingress, uncovered_stage)[
                "resource_attribution_complete"
            ]
        )

        wrong_duration = resources.copy()
        wrong_duration.loc[0, "cpu_time_ms"] = 9.0
        self.assertFalse(
            summarize_measurement_passport(wrong_duration, ingress, events)[
                "resource_attribution_complete"
            ]
        )

        outside_interval = resources.copy()
        outside_interval.loc[0, "timestamp_ms"] = 111.0
        self.assertFalse(
            summarize_measurement_passport(outside_interval, ingress, events)[
                "resource_attribution_complete"
            ]
        )

        starts_before_ingress = events.copy()
        starts_before_ingress.loc[0, "queue_enter_timestamp_ms"] = 99.0
        starts_before_ingress.loc[0, "stage_start_timestamp_ms"] = 99.0
        starts_before_ingress.loc[0, "stage_end_timestamp_ms"] = 109.0
        starts_before_ingress_resources = resources.copy()
        starts_before_ingress_resources.loc[0, "timestamp_ms"] = 109.0
        self.assertFalse(
            summarize_measurement_passport(
                starts_before_ingress_resources,
                ingress,
                starts_before_ingress,
            )["resource_attribution_complete"]
        )

        ends_after_terminal = events.copy()
        ends_after_terminal.loc[1, "stage_start_timestamp_ms"] = 124.0
        ends_after_terminal.loc[1, "stage_end_timestamp_ms"] = 132.0
        ends_after_terminal_resources = resources.copy()
        ends_after_terminal_resources.loc[1, "timestamp_ms"] = 129.0
        self.assertFalse(
            summarize_measurement_passport(
                ends_after_terminal_resources,
                ingress,
                ends_after_terminal,
            )["resource_attribution_complete"]
        )

    def test_strict_sidecar_validation_requires_native_ingress_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row()])
            events = pd.DataFrame([native_event_row()])
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset={"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]},
                policy="heft",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)

            with self.assertRaisesRegex(ContractError, "ingress_ledger.csv was not produced"):
                validate_required_sidecars(root, require_ingress_ledger=True, frames=frames)

            pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS).to_csv(
                root / "ingress_ledger.csv",
                index=False,
            )
            sidecars = validate_required_sidecars(root, require_ingress_ledger=True, frames=frames)
            self.assertIn("ingress_ledger", sidecars)
            summary = summarize_sidecars(root, frames=frames)
            self.assertTrue(summary["ingress_ledger_complete"])
            self.assertTrue(summary["ingress_cohort_closed"])
            self.assertEqual(summary["ingress_frame_count"], 1)
            self.assertEqual(summary["completed_frame_count"], 1)
            self.assertEqual(summary["dropped_frame_count"], 0)
            self.assertEqual(summary["censored_frame_count"], 0)
            self.assertEqual(summary["dropped_frame_rate_percent"], 0.0)
            self.assertEqual(summary["censored_frame_rate_percent"], 0.0)
            self.assertEqual(summary["drain_duration_ms"], 50.0)

    def test_native_reset_evidence_covers_processes_queues_origin_and_sink(self) -> None:
        ingress = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reset_evidence.csv"
            pd.DataFrame(reset_evidence_rows(), columns=RESET_EVIDENCE_COLUMNS).to_csv(path, index=False)

            result = validate_reset_evidence(
                path,
                ingress_ledger=ingress,
                topology_kind="shared_video_dag",
                expected_streams=1,
                required_branches=["a", "b"],
            )

            self.assertTrue(result["reset_claim_eligible"].all())
            self.assertEqual(set(result["process_role"]), {"source_coordinator", "shared_graph_worker"})

    def test_reset_origin_is_independent_of_warmup_excluded_measurement_sequence(self) -> None:
        ingress = pd.DataFrame(
            [ingress_ledger_row(admission_seq=31, access_unit_pts_ns=2_700_000)],
            columns=INGRESS_LEDGER_COLUMNS,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reset_evidence.csv"
            pd.DataFrame(reset_evidence_rows(), columns=RESET_EVIDENCE_COLUMNS).to_csv(path, index=False)

            result = validate_reset_evidence(
                path,
                ingress_ledger=ingress,
                topology_kind="shared_video_dag",
                expected_streams=1,
                required_branches=["a", "b"],
            )

        self.assertTrue(result["reset_claim_eligible"].all())
        self.assertEqual(int(result.loc[result["process_role"] == "source_coordinator", "admission_seq_first"].iloc[0]), 1)

    def test_reset_evidence_rejects_nonempty_queue_or_engineering_source(self) -> None:
        ingress = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        mutations = [
            ("analytics_queue_depths_json", '{"a":1,"b":0}', "queue depth"),
            ("observed_pid", 1002.5, "observed_pid must contain integers"),
            ("telemetry_source", "engineering_runtime", "telemetry_source=native"),
        ]
        for field, value, message in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                rows = reset_evidence_rows()
                rows[-1][field] = value
                path = Path(tmp) / "reset_evidence.csv"
                pd.DataFrame(rows, columns=RESET_EVIDENCE_COLUMNS).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_reset_evidence(
                        path,
                        ingress_ledger=ingress,
                        topology_kind="shared_video_dag",
                        expected_streams=1,
                        required_branches=["a", "b"],
                    )
    def test_ingress_ledger_rejects_derived_ingress_or_out_of_window_frame(self) -> None:
        frames = pd.DataFrame([native_frame_row()])
        cases = [
            ("ingress_provenance", "derived_from_frames_csv", "native_ingress_event"),
            ("ingress_timestamp_ms", 200.0, "outside \\[t0, t1\\)"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "ingress_ledger.csv"
                pd.DataFrame(
                    [ingress_ledger_row(**{field: value})],
                    columns=INGRESS_LEDGER_COLUMNS,
                ).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_ingress_ledger(path, frames=frames)

    def test_ingress_ledger_bounds_schedule_selected_wall_clock_start_jitter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ingress_ledger.csv"
            accepted = ingress_ledger_row(
                ingress_timestamp_ms=98.0,
                window_start_timestamp_ms=100.0,
            )
            pd.DataFrame([accepted], columns=INGRESS_LEDGER_COLUMNS).to_csv(path, index=False)

            ledger = validate_ingress_ledger(
                path,
                frames=pd.DataFrame([native_frame_row(ingress_timestamp_ms=98.0)]),
            )

            self.assertEqual(float(ledger.iloc[0]["ingress_timestamp_ms"]), 98.0)

            rejected = ingress_ledger_row(
                ingress_timestamp_ms=94.0,
                window_start_timestamp_ms=100.0,
            )
            pd.DataFrame([rejected], columns=INGRESS_LEDGER_COLUMNS).to_csv(path, index=False)
            with self.assertRaisesRegex(ContractError, "outside \\[t0, t1\\)"):
                validate_ingress_ledger(
                    path,
                    frames=pd.DataFrame([native_frame_row(ingress_timestamp_ms=94.0)]),
                )

    def test_ingress_ledger_rejects_completed_frame_or_censoring_mismatch(self) -> None:
        cases = [
            (
                ingress_ledger_row(terminal_timestamp_ms=131.0),
                "completed terminal timestamp does not match frames.csv",
            ),
            (
                ingress_ledger_row(
                    terminal_status="censored",
                    terminal_timestamp_ms=240.0,
                    terminal_reason="drain_cutoff",
                    terminal_provenance="explicit_censoring_at_drain_end",
                ),
                "censored terminal time must equal drain end",
            ),
            (
                ingress_ledger_row(
                    terminal_status="censored",
                    terminal_timestamp_ms=250.0,
                    terminal_reason="drain_cutoff",
                    terminal_provenance="explicit_censoring_at_drain_end",
                    censoring_rule="drain_to_empty",
                ),
                "drain_to_empty cannot leave censored",
            ),
        ]
        for row, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "ingress_ledger.csv"
                pd.DataFrame([row], columns=INGRESS_LEDGER_COLUMNS).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_ingress_ledger(path, frames=pd.DataFrame([native_frame_row()]))

    def test_ingress_ledger_rejects_native_drop_counter_or_topology_identity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ingress_ledger.csv"
            pd.DataFrame(
                [
                    ingress_ledger_row(),
                    ingress_ledger_row(
                        trace_id="r:0:2",
                        input_frame_key="source:0:2",
                        frame_id=2,
                        ingress_timestamp_ms=120.0,
                        terminal_status="drop",
                        terminal_timestamp_ms=140.0,
                        terminal_reason="queue_overflow",
                        terminal_provenance="native_drop_event",
                    ),
                ],
                columns=INGRESS_LEDGER_COLUMNS,
            ).to_csv(path, index=False)
            drops = pd.DataFrame(
                [{"stream_id": 0, "dropped_frames": 0, "drop_provenance": "native_drop_event"}]
            )
            with self.assertRaisesRegex(ContractError, "native drop counter does not match"):
                validate_ingress_ledger(path, frames=pd.DataFrame([native_frame_row()]), drop_counters=drops)

            topology = pd.DataFrame(
                [
                    {
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "input_frame_key": "different-source-frame",
                    }
                ]
            )
            with self.assertRaisesRegex(ContractError, "topology input_frame_key does not match"):
                validate_ingress_ledger(path, frames=pd.DataFrame([native_frame_row()]), topology_events=topology)

    def test_branch_terminals_close_completed_drop_and_censored_checkpoint_frames(self) -> None:
        branches = ("damage", "people_counting", "smoke_fire", "foreign_object")
        ledger = pd.DataFrame(
            [
                ingress_ledger_row(),
                ingress_ledger_row(
                    trace_id="r:0:2",
                    input_frame_key="source:0:2",
                    frame_id=2,
                    ingress_timestamp_ms=120.0,
                    terminal_status="drop",
                    terminal_timestamp_ms=145.0,
                    terminal_reason="native_branch_drop",
                    terminal_provenance="native_drop_event",
                ),
                ingress_ledger_row(
                    trace_id="r:0:3",
                    input_frame_key="source:0:3",
                    frame_id=3,
                    ingress_timestamp_ms=190.0,
                    terminal_status="censored",
                    terminal_timestamp_ms=250.0,
                    terminal_reason="drain_cutoff",
                    terminal_provenance="explicit_censoring_at_drain_end",
                ),
            ],
            columns=INGRESS_LEDGER_COLUMNS,
        )
        frames = pd.DataFrame(
            [
                native_frame_row(
                    objects=4,
                    detector=CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
                )
            ]
        )
        rows = [
            branch_terminal_row(
                branch_id=branch,
                terminal_timestamp_ms=127.0 + index,
                detector=verified_detector_identity(f"native-{branch}-v1"),
            )
            for index, branch in enumerate(branches)
        ]
        rows.extend(
            branch_terminal_row(
                trace_id="r:0:2",
                input_frame_key="source:0:2",
                frame_id=2,
                branch_id=branch,
                terminal_status="drop" if branch == "damage" else "completed",
                terminal_timestamp_ms=145.0 if branch == "damage" else 140.0 + index,
                objects=0 if branch == "damage" else 1,
                detector=verified_detector_identity(f"native-{branch}-v1"),
                terminal_reason="native_queue_drop" if branch == "damage" else "native_result_committed",
                terminal_provenance="native_drop_event" if branch == "damage" else "native_completion_event",
            )
            for index, branch in enumerate(branches)
        )
        rows.extend(
            branch_terminal_row(
                trace_id="r:0:3",
                input_frame_key="source:0:3",
                frame_id=3,
                branch_id=branch,
                terminal_timestamp_ms=220.0 + index,
                detector=verified_detector_identity(f"native-{branch}-v1"),
            )
            for index, branch in enumerate(branches[:-1])
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "branch_terminals.csv"
            pd.DataFrame(rows, columns=BRANCH_TERMINAL_COLUMNS).to_csv(path, index=False)

            terminals = validate_branch_terminals(
                path,
                ingress_ledger=ledger,
                frames=frames,
                required_branches=branches,
            )

        self.assertTrue(bool(terminals["branch_terminal_claim_eligible"].all()))
        self.assertEqual(int((terminals["terminal_status"] == "drop").sum()), 1)
        identity_hash = branch_analytics_contract_sha256(terminals)
        self.assertRegex(identity_hash, r"^[0-9a-f]{64}$")
        self.assertEqual(
            identity_hash,
            branch_analytics_contract_sha256(terminals.iloc[::-1].reset_index(drop=True)),
        )

        malformed = [dict(row) for row in rows]
        malformed[0]["detector"] = "native-damage-v1"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "branch_terminals.csv"
            pd.DataFrame(malformed, columns=BRANCH_TERMINAL_COLUMNS).to_csv(path, index=False)
            with self.assertRaisesRegex(ContractError, "verified model identity"):
                validate_branch_terminals(
                    path,
                    ingress_ledger=ledger,
                    frames=frames,
                    required_branches=branches,
                )

        drifted = [dict(row) for row in rows]
        drifted[len(branches)]["detector"] = verified_detector_identity(
            "native-damage-v1",
            model_digit="c",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "branch_terminals.csv"
            pd.DataFrame(drifted, columns=BRANCH_TERMINAL_COLUMNS).to_csv(path, index=False)
            with self.assertRaisesRegex(ContractError, "analytics identity changed within branch damage"):
                validate_branch_terminals(
                    path,
                    ingress_ledger=ledger,
                    frames=frames,
                    required_branches=branches,
                )

    def test_completed_aggregate_join_may_follow_last_branch_terminal_but_not_precede_it(self) -> None:
        branches = ("damage", "people_counting")
        ledger = pd.DataFrame(
            [ingress_ledger_row(terminal_timestamp_ms=135.0)],
            columns=INGRESS_LEDGER_COLUMNS,
        )
        frames = pd.DataFrame(
            [
                native_frame_row(
                    egress_timestamp_ms=135.0,
                    e2e_latency_ms=35.0,
                    objects=2,
                    detector=CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
                )
            ]
        )
        rows = [
            branch_terminal_row(
                branch_id=branch,
                terminal_timestamp_ms=127.0 + index,
                detector=verified_detector_identity(f"native-{branch}-v1"),
            )
            for index, branch in enumerate(branches)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "branch_terminals.csv"
            pd.DataFrame(rows, columns=BRANCH_TERMINAL_COLUMNS).to_csv(path, index=False)
            result = validate_branch_terminals(
                path,
                ingress_ledger=ledger,
                frames=frames,
                required_branches=branches,
            )
            self.assertTrue(result["branch_terminal_claim_eligible"].all())

            early_ledger = ledger.copy()
            early_ledger.loc[:, "terminal_timestamp_ms"] = 127.5
            with self.assertRaisesRegex(ContractError, "aggregate join precedes"):
                validate_branch_terminals(
                    path,
                    ingress_ledger=early_ledger,
                    frames=frames,
                    required_branches=branches,
                )

    def test_branch_terminals_reject_missing_branch_inferred_drop_and_ambiguous_frame_aggregate(self) -> None:
        branches = ("damage", "people_counting")
        completed_ledger = pd.DataFrame([ingress_ledger_row()], columns=INGRESS_LEDGER_COLUMNS)
        aggregate_frame = pd.DataFrame(
            [native_frame_row(objects=2, detector=CHECKPOINT_FRAME_AGGREGATE_DETECTOR)]
        )
        cases = [
            (
                [branch_terminal_row(branch_id="damage", objects=2)],
                completed_ledger,
                aggregate_frame,
                "does not cover every required branch",
            ),
            (
                [
                    branch_terminal_row(branch_id="damage", terminal_timestamp_ms=129.0),
                    branch_terminal_row(branch_id="people_counting"),
                ],
                pd.DataFrame(
                    [
                        ingress_ledger_row(
                            terminal_status="drop",
                            terminal_reason="missing_output",
                            terminal_provenance="native_drop_event",
                        )
                    ],
                    columns=INGRESS_LEDGER_COLUMNS,
                ),
                pd.DataFrame(columns=aggregate_frame.columns),
                "has no native branch drop event",
            ),
            (
                [
                    branch_terminal_row(branch_id="damage", terminal_timestamp_ms=129.0),
                    branch_terminal_row(branch_id="people_counting"),
                ],
                completed_ledger,
                pd.DataFrame([native_frame_row(objects=2, detector="damage")]),
                "checkpoint frames.csv detector must be",
            ),
        ]
        for rows, ledger, frames, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "branch_terminals.csv"
                pd.DataFrame(rows, columns=BRANCH_TERMINAL_COLUMNS).to_csv(path, index=False)
                with self.assertRaisesRegex(ContractError, message):
                    validate_branch_terminals(
                        path,
                        ingress_ledger=ledger,
                        frames=frames,
                        required_branches=branches,
                    )

    def test_full_policy_trace_is_replayable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            pd.DataFrame([full_policy_decision_row()], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(
                path,
                index=False,
            )

            decisions = validate_policy_decisions(path, require_full_trace=True)
            self.assertTrue(bool(decisions.iloc[0]["policy_claim_eligible"]))
            self.assertFalse(bool(decisions.iloc[0]["causal_policy_claim_eligible"]))
            with self.assertRaisesRegex(ContractError, "without a complete causal policy trace"):
                validate_policy_decisions(path, require_causal_trace=True)

    def test_native_full_policy_trace_is_not_overwritten_by_sidecar_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = root / "policy_decisions.csv"
            pd.DataFrame([full_policy_decision_row()], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(
                policy_path,
                index=False,
            )
            original = policy_path.read_bytes()
            write_provenance_labeled_sidecars(
                root,
                frames=pd.DataFrame([native_frame_row()]),
                events=pd.DataFrame(
                    [
                        native_event_row(
                            stage="detect",
                            resource="gpu",
                            queue_depth=1,
                            estimated_cost_ms=2.0,
                            policy_action="ql_heft_online:gpu",
                        )
                    ]
                ),
                dataset={"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]},
                policy="ql_heft_online",
                deadline_ms=100.0,
            )
            pd.DataFrame(
                [
                    native_event_row(
                        stage="detect",
                        resource="gpu",
                        queue_depth=1,
                        estimated_cost_ms=2.0,
                        policy_action="ql_heft_online:gpu",
                    )
                ]
            ).to_csv(root / "frame_events.csv", index=False)

            self.assertEqual(policy_path.read_bytes(), original)
            validate_policy_decisions(policy_path, require_full_trace=True)
            validate_required_sidecars(root, require_full_policy_trace=True)
            self.assertTrue(summarize_sidecars(root)["policy_trace_complete"])
            self.assertFalse(summarize_sidecars(root)["policy_causal_trace_complete"])

    def test_required_sidecars_reject_unlinked_applied_policy_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row()])
            events = pd.DataFrame([native_event_row(stage="detect", resource="gpu")])
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset={"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]},
                policy="heft",
                deadline_ms=100.0,
            )
            events.assign(resource="cpu").to_csv(root / "frame_events.csv", index=False)

            with self.assertRaisesRegex(ContractError, "resource does not match frame event"):
                validate_required_sidecars(root)

    def test_full_policy_trace_rejects_nonminimum_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(resource="cpu", decision="ql_heft_online:cpu", estimated_cost_ms=3.0)
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "does not minimize alternative scores"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_requires_selected_cost_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(estimated_cost_ms=2.5)
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "does not match the selected alternative score"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_requires_monotonic_update_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            rows = [
                full_policy_decision_row(
                    update_seq=1,
                    update_json=policy_update_json(),
                    parameters_json=json.dumps(
                        {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                    ),
                ),
                full_policy_decision_row(
                    trace_id="r:0:2",
                    frame_id=2,
                    update_seq=0,
                    update_json="{}",
                    parameters_json=json.dumps(
                        {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                    ),
                ),
            ]
            pd.DataFrame(rows, columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "update_seq must be monotonic"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_rejects_gaps_in_update_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(
                update_seq=2,
                update_json=policy_update_json(),
                parameters_json=json.dumps(
                    {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                ),
            )
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "update_seq must advance by one"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_weighted_policy_trace_requires_all_resource_weights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(
                parameters_json=json.dumps({"score_epsilon": 1e-9, "weights": {"gpu": 0.8}})
            )
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "must cover every allowed resource"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_requires_update_payload_when_sequence_advances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            pd.DataFrame(
                [full_policy_decision_row(update_seq=1)],
                columns=ENGINEERING_POLICY_DECISION_COLUMNS,
            ).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "advances without a replayable update_json"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_accepts_replayable_update_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(
                update_seq=1,
                update_json=policy_update_json(),
                parameters_json=json.dumps(
                    {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                ),
            )
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            decisions = validate_policy_decisions(path, require_full_trace=True)
            self.assertTrue(bool(decisions.iloc[0]["policy_claim_eligible"]))

    def test_full_policy_trace_rejects_update_without_sequence_increment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(update_json=policy_update_json())
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "without an update_seq increment"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_full_policy_trace_rejects_updates_for_frozen_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = full_policy_decision_row(
                policy="ql_heft_frozen",
                decision="ql_heft_frozen:gpu",
                update_seq=1,
                update_json=policy_update_json(),
                parameters_json=json.dumps(
                    {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                ),
            )
            pd.DataFrame([row], columns=ENGINEERING_POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "frozen policy must keep update_seq=0"):
                validate_policy_decisions(path, require_full_trace=True)

    def test_causal_policy_trace_links_terminal_feedback_to_first_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            first_id = "r:ql_heft_online:decision:1"
            second_id = "r:ql_heft_online:decision:2"
            rows = [
                causal_policy_decision_row(),
                causal_policy_decision_row(
                    trace_id="r:0:2",
                    frame_id=2,
                    decision_id=second_id,
                    decision_seq=2,
                    decision_timestamp_ms=130.0,
                    feature_provenance_json=feature_provenance_json(
                        trace_id="r:0:2",
                        observed_timestamp_ms=129.0,
                        decision_timestamp_ms=130.0,
                    ),
                    terminal_timestamp_ms=150.0,
                    update_seq=1,
                    update_json=policy_update_json(),
                    parameters_json=json.dumps(
                        {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                    ),
                    update_timestamp_ms=125.0,
                    source_decision_ids_json=json.dumps([first_id]),
                    first_consumer_decision_id=second_id,
                    first_consumer_decision_seq=2,
                ),
            ]
            pd.DataFrame(rows, columns=POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            decisions = validate_policy_decisions(path, require_causal_trace=True)
            self.assertTrue(bool(decisions["causal_policy_claim_eligible"].all()))

    def test_causal_policy_trace_rejects_post_completion_queue_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            rows = [
                causal_policy_decision_row(),
                causal_update_consumer_row(update_json=policy_update_json(gpu_queue_depth=3)),
            ]
            pd.DataFrame(rows, columns=POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "does not match source decision snapshots"):
                validate_policy_decisions(path, require_causal_trace=True)

    def test_causal_policy_trace_rejects_future_feature_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            row = causal_policy_decision_row(
                feature_provenance_json=feature_provenance_json(
                    observed_timestamp_ms=101.0,
                    decision_timestamp_ms=100.0,
                )
            )
            pd.DataFrame([row], columns=POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "must be observed no later than the decision"):
                validate_policy_decisions(path, require_causal_trace=True)

    def test_causal_policy_trace_rejects_censored_feedback_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            first_id = "r:ql_heft_online:decision:1"
            second_id = "r:ql_heft_online:decision:2"
            rows = [
                causal_policy_decision_row(terminal_status="censored"),
                causal_policy_decision_row(
                    trace_id="r:0:2",
                    frame_id=2,
                    decision_id=second_id,
                    decision_seq=2,
                    decision_timestamp_ms=130.0,
                    feature_provenance_json=feature_provenance_json(
                        trace_id="r:0:2",
                        observed_timestamp_ms=129.0,
                        decision_timestamp_ms=130.0,
                    ),
                    terminal_timestamp_ms=150.0,
                    update_seq=1,
                    update_json=policy_update_json(),
                    parameters_json=json.dumps(
                        {"score_epsilon": 1e-9, "weights": {"cpu": 1.0, "gpu": 0.9}}
                    ),
                    update_timestamp_ms=125.0,
                    source_decision_ids_json=json.dumps([first_id]),
                    first_consumer_decision_id=second_id,
                    first_consumer_decision_seq=2,
                ),
            ]
            pd.DataFrame(rows, columns=POLICY_DECISION_COLUMNS).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "censored or unresolved decision"):
                validate_policy_decisions(path, require_causal_trace=True)

    def test_causal_policy_trace_rejects_partial_column_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy_decisions.csv"
            columns = [column for column in POLICY_DECISION_COLUMNS if column != POLICY_CAUSAL_TRACE_COLUMNS[-1]]
            pd.DataFrame([causal_policy_decision_row()], columns=columns).to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "incomplete causal policy trace columns"):
                validate_policy_decisions(path)

    def test_online_policy_feedback_validates_projection_noop_and_first_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision_path = root / "policy_decisions.csv"
            feedback_path = root / "policy_feedback.csv"
            bounded_policy_decisions().to_csv(decision_path, index=False)
            decisions = validate_policy_decisions(decision_path, require_causal_trace=True)
            pd.DataFrame(bounded_policy_feedback_rows(), columns=POLICY_FEEDBACK_COLUMNS).to_csv(
                feedback_path,
                index=False,
            )

            feedback = validate_policy_feedback(
                feedback_path,
                decisions=decisions,
                require_complete=True,
            )
            self.assertTrue(bool(feedback["policy_feedback_claim_eligible"].all()))
            self.assertEqual(list(feedback["feedback_action"]), ["update", "no_op"])

    def test_online_policy_feedback_lag_uses_oldest_applied_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision_path = root / "policy_decisions.csv"
            feedback_path = root / "policy_feedback.csv"
            first_id = "r:ql_heft_online:decision:1"
            older_id = "r:ql_heft_online:decision:2"
            newest_id = "r:ql_heft_online:decision:3"
            decisions_frame = pd.DataFrame(
                [
                    causal_policy_decision_row(
                        decision_id=first_id,
                        parameters_json=bounded_policy_parameters({"cpu": 1.1, "gpu": 0.9}),
                    ),
                    causal_policy_decision_row(
                        trace_id="r:0:2",
                        frame_id=2,
                        decision_id=older_id,
                        decision_seq=2,
                        decision_timestamp_ms=110.0,
                        feature_provenance_json=feature_provenance_json(
                            trace_id="r:0:2",
                            observed_timestamp_ms=109.0,
                            decision_timestamp_ms=110.0,
                        ),
                        terminal_timestamp_ms=150.0,
                        parameters_json=bounded_policy_parameters({"cpu": 1.1, "gpu": 0.9}),
                    ),
                    causal_policy_decision_row(
                        trace_id="r:0:2",
                        frame_id=2,
                        decision_id=newest_id,
                        decision_seq=3,
                        decision_timestamp_ms=130.0,
                        feature_provenance_json=feature_provenance_json(
                            trace_id="r:0:2",
                            observed_timestamp_ms=129.0,
                            decision_timestamp_ms=130.0,
                        ),
                        terminal_timestamp_ms=150.0,
                        update_seq=1,
                        update_json=bounded_policy_update_json(),
                        parameters_json=bounded_policy_parameters({"cpu": 1.05, "gpu": 0.95}),
                        update_timestamp_ms=125.0,
                        source_decision_ids_json=json.dumps([first_id]),
                        first_consumer_decision_id=newest_id,
                        first_consumer_decision_seq=3,
                    ),
                ],
                columns=POLICY_DECISION_COLUMNS,
            )
            decisions_frame.to_csv(decision_path, index=False)
            decisions = validate_policy_decisions(decision_path, require_causal_trace=True)
            rows = bounded_policy_feedback_rows()
            rows[0]["first_consumer_decision_id"] = newest_id
            rows[0]["first_consumer_decision_seq"] = 3
            rows[1]["source_decision_ids_json"] = json.dumps([older_id, newest_id])
            rows[1]["source_parameter_snapshot_seq"] = 0
            rows[1]["parameter_lag"] = 1
            pd.DataFrame(rows, columns=POLICY_FEEDBACK_COLUMNS).to_csv(feedback_path, index=False)

            feedback = validate_policy_feedback(
                feedback_path,
                decisions=decisions,
                require_complete=True,
            )
            self.assertEqual(int(feedback.iloc[1]["source_parameter_snapshot_seq"]), 0)
            self.assertEqual(int(feedback.iloc[1]["parameter_lag"]), 1)

            rows[1]["source_parameter_snapshot_seq"] = 1
            rows[1]["parameter_lag"] = 0
            pd.DataFrame(rows, columns=POLICY_FEEDBACK_COLUMNS).to_csv(feedback_path, index=False)
            with self.assertRaisesRegex(ContractError, "oldest source parameter snapshot"):
                validate_policy_feedback(
                    feedback_path,
                    decisions=decisions,
                    require_complete=True,
                )

    def test_sidecar_summary_exposes_online_policy_trace_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame(
                [
                    native_frame_row(),
                    native_frame_row(
                        trace_id="r:0:2",
                        frame_id=2,
                        ingress_timestamp_ms=121,
                        egress_timestamp_ms=150,
                        e2e_latency_ms=29,
                    ),
                ]
            )
            events = pd.DataFrame(
                [
                    native_event_row(
                        stage="detect", resource="gpu", queue_depth=4,
                        estimated_cost_ms=2.0, policy_action="ql_heft_online:gpu",
                    ),
                    native_event_row(
                        trace_id="r:0:2", frame_id=2, stage="detect", resource="gpu",
                        queue_enter_timestamp_ms=121, stage_start_timestamp_ms=121,
                        stage_end_timestamp_ms=130, queue_depth=4,
                        estimated_cost_ms=2.0, policy_action="ql_heft_online:gpu",
                    ),
                ]
            )
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset={"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]},
                policy="ql_heft_online",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)
            bounded_policy_decisions().to_csv(root / "policy_decisions.csv", index=False)
            pd.DataFrame(bounded_policy_feedback_rows(), columns=POLICY_FEEDBACK_COLUMNS).to_csv(
                root / "policy_feedback.csv", index=False
            )

            self.assertTrue(summarize_sidecars(root)["policy_online_trace_complete"])

    def test_online_policy_feedback_rejects_non_deterministic_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision_path = root / "policy_decisions.csv"
            feedback_path = root / "policy_feedback.csv"
            bounded_policy_decisions().to_csv(decision_path, index=False)
            decisions = validate_policy_decisions(decision_path, require_causal_trace=True)
            rows = bounded_policy_feedback_rows()
            rows[0]["projected_weights_json"] = json.dumps({"cpu": 1.1, "gpu": 0.9})
            pd.DataFrame(rows, columns=POLICY_FEEDBACK_COLUMNS).to_csv(feedback_path, index=False)

            with self.assertRaisesRegex(ContractError, "do not match deterministic projection"):
                validate_policy_feedback(feedback_path, decisions=decisions, require_complete=True)

    def test_online_policy_feedback_rejects_sequence_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision_path = root / "policy_decisions.csv"
            feedback_path = root / "policy_feedback.csv"
            bounded_policy_decisions().to_csv(decision_path, index=False)
            decisions = validate_policy_decisions(decision_path, require_causal_trace=True)
            rows = bounded_policy_feedback_rows()
            rows[1]["feedback_seq"] = 3
            pd.DataFrame(rows, columns=POLICY_FEEDBACK_COLUMNS).to_csv(feedback_path, index=False)

            with self.assertRaisesRegex(ContractError, "feedback_seq must be gap-free"):
                validate_policy_feedback(feedback_path, decisions=decisions, require_complete=True)

    def test_online_policy_feedback_rejects_unexplained_eligible_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision_path = root / "policy_decisions.csv"
            feedback_path = root / "policy_feedback.csv"
            bounded_policy_decisions().to_csv(decision_path, index=False)
            decisions = validate_policy_decisions(decision_path, require_causal_trace=True)
            rows = bounded_policy_feedback_rows()
            rows[1]["raw_weights_json"] = json.dumps({"cpu": 1.05, "gpu": 1.05})
            rows[1]["projected_weights_json"] = json.dumps({"cpu": 1.0, "gpu": 1.0})
            rows[1]["reason"] = "no_weight_update"
            pd.DataFrame(rows, columns=POLICY_FEEDBACK_COLUMNS).to_csv(feedback_path, index=False)

            with self.assertRaisesRegex(ContractError, "eligible bounded update was recorded"):
                validate_policy_feedback(feedback_path, decisions=decisions, require_complete=True)

    def test_primary_proxy_reference_replay_accepts_exact_v4_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_dir = root / "frozen"
            online_dir = root / "online"
            frozen_dir.mkdir()
            online_dir.mkdir()
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_frozen", run_id="frozen-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(frozen_dir / "policy_decisions.csv", index=False)
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_online", run_id="online-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(online_dir / "policy_decisions.csv", index=False)
            pd.DataFrame(
                [primary_proxy_feedback_row(run_id="online-run")],
                columns=POLICY_FEEDBACK_COLUMNS,
            ).to_csv(online_dir / "policy_feedback.csv", index=False)
            frozen = validate_policy_decisions(
                frozen_dir / "policy_decisions.csv",
                require_full_trace=True,
                require_causal_trace=True,
            )
            online = validate_policy_decisions(
                online_dir / "policy_decisions.csv",
                require_full_trace=True,
                require_causal_trace=True,
            )
            feedback = validate_policy_feedback(
                online_dir / "policy_feedback.csv",
                decisions=online,
                require_complete=True,
            )
            config = yaml.safe_load((ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8"))

            assessment = evaluate_primary_policy_proxy_replay(
                config,
                frozen_decisions=frozen,
                online_decisions=online,
                online_feedback=feedback,
                frozen_metadata=primary_proxy_runtime_metadata(),
                online_metadata=primary_proxy_runtime_metadata(),
            )

            self.assertTrue(assessment["passed"])
            self.assertEqual(assessment["status"], "passed_proxy_reference_replay")
            self.assertTrue(assessment["runtime_reference_replay_performed"])
            self.assertTrue(assessment["artifact_identity_verified"])
            self.assertEqual(assessment["online_feedback"]["replayed_feedback_count"], 1)
            self.assertFalse(assessment["formal_aw_heft_equivalence_evaluated"])

    def test_primary_proxy_reference_replay_rejects_score_not_recomputed_from_components(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_path = root / "frozen.csv"
            online_path = root / "online.csv"
            feedback_path = root / "policy_feedback.csv"
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_frozen", run_id="frozen-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(frozen_path, index=False)
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_online", run_id="online-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(online_path, index=False)
            pd.DataFrame(
                [primary_proxy_feedback_row(run_id="online-run")],
                columns=POLICY_FEEDBACK_COLUMNS,
            ).to_csv(feedback_path, index=False)
            frozen = validate_policy_decisions(frozen_path, require_causal_trace=True)
            online = validate_policy_decisions(online_path, require_causal_trace=True)
            feedback = validate_policy_feedback(
                feedback_path,
                decisions=online,
                require_complete=True,
            )
            tampered_scores = json.loads(str(online.loc[0, "alternative_scores_json"]))
            tampered_scores["cpu"] += 0.25
            online.loc[0, "alternative_scores_json"] = json.dumps(tampered_scores)
            config = yaml.safe_load((ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8"))

            assessment = evaluate_primary_policy_proxy_replay(
                config,
                frozen_decisions=frozen,
                online_decisions=online,
                online_feedback=feedback,
                frozen_metadata=primary_proxy_runtime_metadata(),
                online_metadata=primary_proxy_runtime_metadata(),
            )

            self.assertFalse(assessment["passed"])
            self.assertIn(
                "online:decision_row_2:cpu_score_replay_mismatch",
                assessment["blockers"],
            )

    def test_primary_proxy_reference_replay_rejects_unbound_runtime_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frozen_path = root / "frozen.csv"
            online_path = root / "online.csv"
            feedback_path = root / "policy_feedback.csv"
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_frozen", run_id="frozen-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(frozen_path, index=False)
            pd.DataFrame(
                [primary_proxy_decision_row(policy="ql_heft_online", run_id="online-run")],
                columns=POLICY_DECISION_COLUMNS,
            ).to_csv(online_path, index=False)
            pd.DataFrame(
                [primary_proxy_feedback_row(run_id="online-run")],
                columns=POLICY_FEEDBACK_COLUMNS,
            ).to_csv(feedback_path, index=False)
            frozen = validate_policy_decisions(frozen_path, require_causal_trace=True)
            online = validate_policy_decisions(online_path, require_causal_trace=True)
            feedback = validate_policy_feedback(
                feedback_path,
                decisions=online,
                require_complete=True,
            )
            metadata = primary_proxy_runtime_metadata()
            metadata["ql_heft_policy_artifact"]["sha256"] = "0" * 64
            config = yaml.safe_load((ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8"))

            assessment = evaluate_primary_policy_proxy_replay(
                config,
                frozen_decisions=frozen,
                online_decisions=online,
                online_feedback=feedback,
                frozen_metadata=metadata,
                online_metadata=primary_proxy_runtime_metadata(),
            )

            self.assertFalse(assessment["passed"])
            self.assertFalse(assessment["artifact_identity_verified"])
            self.assertIn(
                "frozen:runtime_metadata:policy_artifact_sha256_mismatch",
                assessment["blockers"],
            )

    def test_custom_cpp_policy_header_matches_current_contract(self) -> None:
        source = (ROOT / "deploy" / "custom_cpp_cuda_qt" / "adaptive_scheduler_app.cu").read_text(
            encoding="utf-8"
        )
        header_line = next(line for line in source.splitlines() if 'policy << "schema_version' in line)
        emitted_header = header_line.split('"', 2)[1].removesuffix("\\n").split(",")
        self.assertEqual(emitted_header, POLICY_DECISION_COLUMNS)

    def test_sidecar_provenance_rejects_unknown_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row()])
            events = pd.DataFrame([native_event_row()])
            dataset = {"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]}
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset=dataset,
                policy="heft",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)
            path = root / "resource_events.csv"
            resource = pd.read_csv(path)
            resource.loc[:, "transfer_provenance"] = "claimed_native_without_counter"
            resource.to_csv(path, index=False)

            with self.assertRaisesRegex(ContractError, "unsupported provenance values"):
                validate_resource_events(path)

    def test_legacy_sidecars_are_diagnostic_but_fail_strict_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = pd.DataFrame([native_frame_row()])
            events = pd.DataFrame([native_event_row()])
            dataset = {"streams": [{"stream_id": 0, "width": 1920, "height": 1080}]}
            write_provenance_labeled_sidecars(
                root,
                frames=frames,
                events=events,
                dataset=dataset,
                policy="heft",
                deadline_ms=100.0,
            )
            events.to_csv(root / "frame_events.csv", index=False)
            provenance_columns = {
                "resource_events.csv": [
                    "time_provenance",
                    "transfer_provenance",
                    "nvdec_provenance",
                    "vram_provenance",
                ],
                "policy_decisions.csv": [
                    *POLICY_TRACE_COLUMNS,
                    *POLICY_CAUSAL_TRACE_COLUMNS,
                    "decision_provenance",
                    "trace_completeness",
                ],
                "drop_counters.csv": ["drop_provenance", "late_provenance"],
            }
            for filename, columns in provenance_columns.items():
                path = root / filename
                pd.read_csv(path).drop(columns=columns).to_csv(path, index=False)

            sidecars = validate_required_sidecars(root)
            self.assertEqual(set(sidecars["resource_events"]["time_provenance"]), {"unlabeled_legacy"})
            with self.assertRaisesRegex(ContractError, "lacks explicit metric provenance"):
                validate_required_sidecars(root, require_labeled_provenance=True)

    def test_required_sidecars_reject_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ContractError, "resource_events.csv was not produced"):
                validate_required_sidecars(Path(tmp))

    def test_benchmark_rejects_malformed_frame_timestamps(self) -> None:
        for bad_value in ("None", "", "not-a-number"):
            with self.subTest(bad_value=bad_value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "frames.csv"
                pd.DataFrame([native_frame_row(ingress_timestamp_ms=bad_value)]).to_csv(path, index=False)

                with self.assertRaisesRegex(ContractError, r"frames\.csv:2: .*ingress_timestamp_ms"):
                    canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_rejects_malformed_frame_event_timestamps(self) -> None:
        for bad_value in ("None", "", "not-a-number"):
            with self.subTest(bad_value=bad_value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "frame_events.csv"
                pd.DataFrame([native_event_row(stage_start_timestamp_ms=bad_value)]).to_csv(path, index=False)

                with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                    validate_frame_events(path)

    def test_benchmark_rejects_extra_frame_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame_events.csv"
            row = native_event_row()
            path.write_text(
                ",".join(FRAME_EVENT_COLUMNS)
                + "\n"
                + ",".join(str(row[column]) for column in FRAME_EVENT_COLUMNS)
                + ",extra\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: unexpected extra CSV fields"):
                validate_frame_events(path)

    def test_stage_trace_coverage_accepts_merged_role_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 130,
                        "e2e_latency_ms": 30,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)

            role_rows = {
                "edge": ("decode", 100, 110),
                "gpu_worker": ("detect", 111, 125),
                "aggregator": ("aggregate", 126, 130),
            }
            paths = []
            for role, (stage, start, end) in role_rows.items():
                path = root / "roles" / role / "frame_events.csv"
                path.parent.mkdir(parents=True)
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": "r:0:1",
                            "stream_id": 0,
                            "frame_id": 1,
                            "stage": stage,
                            "role": role,
                            "host": "localhost",
                            "resource": "gpu" if role == "gpu_worker" else "cpu",
                            "queue_enter_timestamp_ms": start,
                            "stage_start_timestamp_ms": start,
                            "stage_end_timestamp_ms": end,
                            "queue_depth": 0,
                            "estimated_cost_ms": end - start,
                            "policy_action": f"native:{stage}",
                        }
                    ]
                ).to_csv(path, index=False)
                paths.append(path)

            merged_events = root / "frame_events.csv"
            _combine_csv(paths, merged_events, FRAME_EVENT_COLUMNS)
            validate_stage_trace_coverage(frames, merged_events, required_stages=["decode", "detect", "aggregate"])

    def test_stage_trace_coverage_accepts_edge_preroll_with_per_stream_frame_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            frame_rows = []
            event_rows = []
            run_id = "r"
            measured_frames = 3
            edge_frames = 7
            for stream_id in range(2):
                for frame_id in range(measured_frames):
                    trace_id = f"{run_id}:{stream_id}:{frame_id}"
                    frame_rows.append(native_frame_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id))
                    for stage in ("detect", "track", "aggregate", "record"):
                        event_rows.append(native_event_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id, stage=stage))
                for frame_id in range(edge_frames):
                    trace_id = f"{run_id}:{stream_id}:{frame_id}"
                    event_rows.append(native_event_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id, stage="decode"))

            pd.DataFrame(frame_rows).to_csv(frames, index=False)
            pd.DataFrame(event_rows).to_csv(events, index=False)

            validate_stage_trace_coverage(
                frames,
                events,
                required_stages=["decode", "detect", "track", "aggregate", "record"],
            )

    def test_distributed_combine_rejects_truncated_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "roles" / "edge" / "frame_events.csv"
            source.parent.mkdir(parents=True)
            source.write_text(
                ",".join(FRAME_EVENT_COLUMNS)
                + "\n"
                + "2,r,r:0:1,0,1,decode,edge,localhost,cpu,100\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                _combine_csv([source], root / "frame_events.csv", FRAME_EVENT_COLUMNS)

    def test_stage_trace_coverage_rejects_missing_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 130,
                        "e2e_latency_ms": 30,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "stage": "decode",
                        "role": "edge",
                        "host": "localhost",
                        "resource": "cpu",
                        "queue_enter_timestamp_ms": 100,
                        "stage_start_timestamp_ms": 100,
                        "stage_end_timestamp_ms": 110,
                        "queue_depth": 0,
                        "estimated_cost_ms": 10,
                        "policy_action": "native:decode",
                    }
                ]
            ).to_csv(events, index=False)
            with self.assertRaises(ContractError):
                validate_stage_trace_coverage(frames, events, required_stages=["decode", "detect", "aggregate"])

    def test_stage_trace_coverage_rejects_missing_declared_extra_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame([native_frame_row()]).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    native_event_row(stage="decode"),
                    native_event_row(stage="detect", resource="gpu"),
                    native_event_row(stage="track", resource="gpu"),
                    native_event_row(stage="record"),
                ]
            ).to_csv(events, index=False)

            with self.assertRaisesRegex(ContractError, "stage 'classify'"):
                validate_stage_trace_coverage(
                    frames,
                    events,
                    required_stages=["decode", "detect", "track", "classify", "record"],
                )

    def test_stage_base_name_strips_branch_suffixes(self) -> None:
        self.assertEqual(stage_base_name("decode_a"), "decode")
        self.assertEqual(stage_base_name("preprocess_b"), "preprocess")
        self.assertEqual(stage_base_name("detect_primary"), "detect")
        self.assertEqual(stage_base_name("track_right"), "track")
        self.assertEqual(stage_base_name("aggregate"), "aggregate")
        self.assertEqual(stage_base_name("custom_a"), "custom_a")

    def test_report_deadline_rows_use_raw_frame_latencies(self) -> None:
        frames = pd.DataFrame(
            [
                native_frame_row(trace_id="r:0:1", frame_id=1, e2e_latency_ms=10),
                native_frame_row(trace_id="r:0:2", frame_id=2, e2e_latency_ms=20),
                native_frame_row(trace_id="r:0:3", frame_id=3, e2e_latency_ms=40),
                native_frame_row(trace_id="r:0:4", frame_id=4, e2e_latency_ms=80),
            ]
        )
        rows = deadline_rows_for_frames(frames, [16.7, 50], {"duration_s": 2.0, "scenario": "s"})

        self.assertEqual(rows[0]["deadline_ms"], 16.7)
        self.assertEqual(rows[0]["slo_violation_rate_percent"], 75.0)
        self.assertEqual(rows[1]["deadline_ms"], 50.0)
        self.assertEqual(rows[1]["slo_violation_rate_percent"], 25.0)
        self.assertEqual(rows[0]["throughput_fps"], 2.0)

    def test_shared_vs_duplicated_requires_common_stage_factor_two(self) -> None:
        config = {
            "benchmark": {"report_scenarios": ["checkpoint_video_dag_shared", "checkpoint_independent_processes_baseline"]},
            "scenarios": {
                "checkpoint_independent_processes_baseline": {
                    "workload": {
                        "routing_mode": "all_branches_per_stream",
                        "analytics_function_types": 4,
                    }
                }
            },
        }
        summary = pd.DataFrame(
            [
                {
                    "scenario": "checkpoint_video_dag_shared",
                    "system": "custom_cpp_cuda_qt",
                    "policy": "heft",
                    "repeat": 1,
                    "frames": 2,
                    "throughput_fps": 10.0,
                    "latency_p95_ms": 30.0,
                    "latency_p99_ms": 35.0,
                    "slo_violation_rate_percent": 0.0,
                    "deadline_ms": 100.0,
                    "status": "completed",
                    "run_mode": "benchmark",
                    "telemetry_source": "native",
                },
                {
                    "scenario": "checkpoint_independent_processes_baseline",
                    "system": "custom_cpp_cuda_qt",
                    "policy": "heft",
                    "repeat": 1,
                    "frames": 2,
                    "throughput_fps": 8.0,
                    "latency_p95_ms": 45.0,
                    "latency_p99_ms": 50.0,
                    "slo_violation_rate_percent": 1.0,
                    "deadline_ms": 100.0,
                    "status": "completed",
                    "run_mode": "benchmark",
                    "telemetry_source": "native",
                },
            ]
        )
        stage_metrics = pd.DataFrame(
            [
                {"scenario": "checkpoint_video_dag_shared", "system": "custom_cpp_cuda_qt", "policy": "heft", "repeat": 1, "deadline_ms": 100.0, "base_stage": "decode", "event_count": 2, "stage_duration_ms_total": 20.0},
                {"scenario": "checkpoint_video_dag_shared", "system": "custom_cpp_cuda_qt", "policy": "heft", "repeat": 1, "deadline_ms": 100.0, "base_stage": "preprocess", "event_count": 2, "stage_duration_ms_total": 10.0},
                {"scenario": "checkpoint_independent_processes_baseline", "system": "custom_cpp_cuda_qt", "policy": "heft", "repeat": 1, "deadline_ms": 100.0, "base_stage": "decode", "event_count": 8, "stage_duration_ms_total": 44.0},
                {"scenario": "checkpoint_independent_processes_baseline", "system": "custom_cpp_cuda_qt", "policy": "heft", "repeat": 1, "deadline_ms": 100.0, "base_stage": "preprocess", "event_count": 8, "stage_duration_ms_total": 24.0},
            ]
        )

        result = build_shared_vs_duplicated(stage_metrics, summary, config)
        self.assertEqual(set(result["base_stage"]), {"decode", "preprocess"})
        self.assertTrue((result["event_factor_baseline"] >= 4.0).all())
        self.assertTrue((result["event_factor_ratio"] >= 4.0).all())

        bad = stage_metrics.copy()
        bad.loc[
            (bad["scenario"] == "checkpoint_independent_processes_baseline") & (bad["base_stage"] == "preprocess"),
            "event_count",
        ] = 3
        with self.assertRaisesRegex(ContractError, "analytics function types=4"):
            build_shared_vs_duplicated(bad, summary, config)

    def test_primary_run_metric_rederives_raw_passport_and_blocks_summary_drift(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        primary = config["benchmark"]["primary_architecture_contrast"]
        metadata_dataset = load_dataset(
            ROOT / "configs" / "datasets.yaml",
            "kpp_real_h264",
            mode="benchmark",
            project_root=ROOT,
            require_files=False,
        )
        metadata_scenario = resolve_scenario_contract(
            "checkpoint_video_dag_shared",
            config["scenarios"]["checkpoint_video_dag_shared"],
        )
        metadata_scenario_identity = scenario_contract_identity(metadata_scenario)
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            run_dir = (
                run_root
                / "dataset_kpp_real_h264"
                / "policy_static_hybrid"
                / "checkpoint_video_dag_shared"
                / "streams_6"
                / "deadline_100"
                / "gstreamer_custom"
                / "rep_01"
            )
            run_dir.mkdir(parents=True)
            frames = pd.DataFrame(
                [
                    native_frame_row(
                        trace_id=f"r:{stream_id}:1",
                        stream_id=stream_id,
                    )
                    for stream_id in range(6)
                ]
            )
            events = pd.DataFrame(
                [
                    native_event_row(
                        trace_id=f"r:{stream_id}:1",
                        stream_id=stream_id,
                        stage=stage,
                        resource="cpu" if stage == "decode" else "gpu",
                        stage_start_timestamp_ms=timestamp - duration,
                        stage_end_timestamp_ms=timestamp,
                    )
                    for stream_id in range(6)
                    for stage, timestamp, duration in (("decode", 110, 10), ("preprocess", 120, 8))
                ]
            )
            frames.to_csv(run_dir / "frames.csv", index=False)
            events.to_csv(run_dir / "frame_events.csv", index=False)

            ingress = pd.DataFrame(
                [
                    ingress_ledger_row(
                        trace_id=f"r:{stream_id}:1",
                        input_frame_key=f"source:{stream_id}:1",
                        stream_id=stream_id,
                    )
                    for stream_id in range(6)
                ],
                columns=INGRESS_LEDGER_COLUMNS,
            )
            ingress["ingress_claim_eligible"] = True
            resources = pd.DataFrame(
                [
                    resource_event_row(
                        trace_id=f"r:{stream_id}:1",
                        stream_id=stream_id,
                        stage=stage,
                        resource="cpu" if stage == "decode" else "gpu",
                        timestamp_ms=timestamp,
                        cpu_time_ms=duration if stage == "decode" else 0.0,
                        gpu_time_ms=duration if stage == "preprocess" else 0.0,
                    )
                    for stream_id in range(6)
                    for stage, timestamp, duration in (("decode", 110.0, 10.0), ("preprocess", 120.0, 8.0))
                ],
                columns=RESOURCE_EVENT_COLUMNS,
            )
            branch_terminals = pd.DataFrame(
                {
                    "branch_id": ["damage"],
                    "terminal_status": ["completed"],
                    "detector": [verified_detector_identity("native-damage-v1")],
                    "backend": ["openvino-dlstreamer:gvadetect"],
                    "branch_terminal_claim_eligible": [True],
                }
            )
            stage_contracts = pd.DataFrame(
                [
                    {
                        "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
                        "base_stage": "decode",
                        "implementation_config_json": json.dumps(
                            {"decoder_factory": "nvh264dec"},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "semantic_stage_sha256": "1" * 64,
                        "semantic_contract_claim_eligible": True,
                    },
                    {
                        "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
                        "base_stage": "preprocess",
                        "implementation_config_json": json.dumps(
                            {"stage": "preprocess"},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "semantic_stage_sha256": "2" * 64,
                        "semantic_contract_claim_eligible": True,
                    },
                ]
            )
            reset_evidence = pd.DataFrame(
                {
                    "reset_contract_version": [1],
                    "process_start_token": ["a" * 64],
                    "telemetry_sink_id": ["b" * 64],
                    "reset_claim_eligible": [True],
                }
            )
            passport = summarize_measurement_passport(resources, ingress, events)
            semantic_hash = semantic_prefix_contract_sha256(stage_contracts)
            branch_analytics_hash = branch_analytics_contract_sha256(branch_terminals)
            row = pd.Series(
                {
                    "scenario": "checkpoint_video_dag_shared",
                    "system": "gstreamer_custom",
                    "policy": "static_hybrid",
                    "dataset": "kpp_real_h264",
                    "status": "completed",
                    "run_mode": "benchmark",
                    "telemetry_source": "native",
                    "deadline_ms": 100.0,
                    "streams": 6,
                    "duration_s": 180,
                    "repeat": 1,
                    "scenario_variant": float("nan"),
                    "deployment_mode": "single-server-distributed",
                    "host_topology": "single_host_ssh",
                    "seed": 20260323,
                    "run_seed": 1001,
                    "topology_trace_complete": True,
                    "ingress_ledger_complete": True,
                    "ingress_cohort_closed": True,
                    "branch_terminal_trace_complete": True,
                    "branch_terminal_event_count": 1,
                    "native_branch_drop_event_count": 0,
                    "checkpoint_frame_aggregation_complete": True,
                    "stage_semantic_contract_complete": True,
                    "resource_attribution_complete": True,
                    "resource_attributed_ingress_count": passport["resource_attributed_ingress_count"],
                    "resource_unattributed_event_count": passport["resource_unattributed_event_count"],
                    "reset_state_verified": True,
                    "input_schedule_sha256": passport["input_schedule_sha256"],
                    "input_frame_key_sequence_sha256": passport["input_frame_key_sequence_sha256"],
                    "measurement_window_duration_ms": passport["measurement_window_duration_ms"],
                    "ingress_censoring_rule": "fixed_drain_cutoff_v1",
                    "resource_attribution": passport["resource_attribution"],
                    "measurement_signature": passport["measurement_signature"],
                    "measurement_signature_payload_json": passport["measurement_signature_payload_json"],
                    "ingress_frame_count": 6,
                    "completed_frame_count": 6,
                    "dropped_frame_count": 0,
                    "censored_frame_count": 0,
                    "c_obs_total_ms": passport["c_obs_total_ms"],
                    "c_obs_cpu_total_ms": passport["c_obs_cpu_total_ms"],
                    "c_obs_gpu_total_ms": passport["c_obs_gpu_total_ms"],
                    "c_obs_in_ms_per_ingress": passport["c_obs_in_ms_per_ingress"],
                    "c_obs_cpu_in_ms_per_ingress": passport[
                        "c_obs_cpu_in_ms_per_ingress"
                    ],
                    "c_obs_gpu_in_ms_per_ingress": passport[
                        "c_obs_gpu_in_ms_per_ingress"
                    ],
                    "c_obs_comp_ms_per_completed": passport["c_obs_comp_ms_per_completed"],
                    "c_obs_is_partial": passport["c_obs_is_partial"],
                    "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
                    "semantic_prefix_contract_sha256": semantic_hash,
                    "decoder_placement_verified": True,
                    "decoder_placement_contract_version": 1,
                    "decoder_required_resource": "nvdec",
                    "decoder_factory_identity_complete": True,
                    "decoder_factory": "nvh264dec",
                    "decoder_factory_allowed": True,
                    "decoder_factory_identity_source": (
                        "stage_contracts.decode.implementation_config_json.decoder_factory"
                    ),
                    "decoder_placement_evidence_limit": (
                        "factory_selection_does_not_measure_nvdec_busy_time"
                    ),
                    "branch_analytics_contract_sha256": branch_analytics_hash,
                    "reset_contract_version": 1,
                    "reset_process_start_tokens_json": json.dumps(["a" * 64], separators=(",", ":")),
                    "reset_telemetry_sink_id": "b" * 64,
                }
            )
            metadata_result = row.to_dict()
            metadata_result["scenario_variant"] = ""
            publication_run_contract = resolve_publication_run_contract(
                config,
                metadata_result,
            )
            publication_run_identity = publication_run_contract_identity(
                publication_run_contract
            )
            evidence_bundle, evidence_identity = write_publication_evidence_fixture(
                run_dir
            )
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "mode": "benchmark",
                        "run_seed": 1001,
                        "policy": "static_hybrid",
                        "dataset": metadata_dataset,
                        "resolved_scenario": metadata_scenario,
                        "scenario_contract_identity": {
                            "schema_version": metadata_scenario_identity[
                                "schema_version"
                            ],
                            "sha256": metadata_scenario_identity["sha256"],
                        },
                        "publication_run_contract": publication_run_contract,
                        "publication_run_contract_identity": {
                            "schema_version": publication_run_identity[
                                "schema_version"
                            ],
                            "sha256": publication_run_identity["sha256"],
                        },
                        "publication_evidence_bundle": evidence_bundle,
                        "publication_evidence_bundle_identity": {
                            "schema_version": evidence_identity["schema_version"],
                            "sha256": evidence_identity["sha256"],
                        },
                        "hardware_target": config["hardware_target"],
                        "detected_hardware": {
                            "gpu_model": "NVIDIA GeForce RTX 3060",
                            "cpu_model": "Intel(R) Core(TM) i7-14700K",
                            "ram_gb": 22.0,
                        },
                        "result": metadata_result,
                    },
                    default=lambda value: value.item(),
                ),
                encoding="utf-8",
            )
            accepted_sidecars = {
                "ingress_ledger": ingress,
                "branch_terminals": branch_terminals,
                "stage_contracts": stage_contracts,
                "reset_evidence": reset_evidence,
                "resource_events": resources,
            }
            with (
                mock.patch.object(
                    report_generator,
                    "validate_topology_events",
                    return_value=pd.DataFrame(),
                ) as validate_topology,
                mock.patch.object(
                    report_generator,
                    "validate_required_sidecars",
                    return_value=accepted_sidecars,
                ) as validate_sidecars,
            ):
                metric = report_generator._primary_run_metric(run_root, row, primary, config)
                drifted = row.copy()
                drifted["c_obs_in_ms_per_ingress"] = 999.0
                drifted_metric = report_generator._primary_run_metric(run_root, drifted, primary, config)

            self.assertEqual(validate_topology.call_count, 2)
            self.assertEqual(validate_sidecars.call_count, 2)
            for call in validate_sidecars.call_args_list:
                self.assertTrue(call.kwargs["require_labeled_provenance"])
                self.assertTrue(call.kwargs["require_ingress_ledger"])
                self.assertTrue(call.kwargs["require_branch_terminals"])
                self.assertTrue(call.kwargs["require_stage_contracts"])
                self.assertTrue(call.kwargs["require_reset_evidence"])
            self.assertTrue(metric["run_gate_pass"])
            self.assertEqual(metric["c_obs_in_ms_per_ingress"], 18.0)
            self.assertFalse(drifted_metric["run_gate_pass"])
            self.assertEqual(drifted_metric["c_obs_in_ms_per_ingress"], 18.0)
            self.assertIn(
                "summary_raw_mismatch:c_obs_in_ms_per_ingress",
                drifted_metric["run_gate_blockers"],
            )

            stage_contracts_path = run_dir / "stage_contracts.csv"
            original_stage_contracts = stage_contracts_path.read_bytes()
            stage_contracts_path.write_bytes(original_stage_contracts + b"tampered")
            with self.assertRaisesRegex(
                ContractError,
                "metadata.publication_evidence_bundle",
            ):
                report_generator._primary_run_metric(
                    run_root,
                    row,
                    primary,
                    config,
                )
            stage_contracts_path.write_bytes(original_stage_contracts)

            drifted_metadata = json.loads(
                (run_dir / "run_metadata.json").read_text(encoding="utf-8")
            )
            drifted_metadata["publication_run_contract"]["protocol"][
                "warmup_s"
            ] = 31
            (run_dir / "run_metadata.json").write_text(
                json.dumps(drifted_metadata),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ContractError,
                "metadata.publication_run_contract_identity",
            ):
                report_generator._primary_run_metric(
                    run_root,
                    row,
                    primary,
                    config,
                )

            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "mode": "smoke",
                        "run_seed": 1001,
                        "policy": "static_hybrid",
                        "dataset": metadata_dataset,
                        "resolved_scenario": metadata_scenario,
                        "scenario_contract_identity": {
                            "schema_version": metadata_scenario_identity[
                                "schema_version"
                            ],
                            "sha256": metadata_scenario_identity["sha256"],
                        },
                        "publication_run_contract": publication_run_contract,
                        "publication_run_contract_identity": {
                            "schema_version": publication_run_identity[
                                "schema_version"
                            ],
                            "sha256": publication_run_identity["sha256"],
                        },
                        "publication_evidence_bundle": evidence_bundle,
                        "publication_evidence_bundle_identity": {
                            "schema_version": evidence_identity["schema_version"],
                            "sha256": evidence_identity["sha256"],
                        },
                        "hardware_target": config["hardware_target"],
                        "detected_hardware": {
                            "gpu_model": "NVIDIA GeForce RTX 3060",
                            "cpu_model": "Intel(R) Core(TM) i7-14700K",
                            "ram_gb": 22.0,
                        },
                        "result": metadata_result,
                    },
                    default=lambda value: value.item(),
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ContractError,
                "run_metadata.json does not match the publication summary.*metadata.mode.*mode_consistency",
            ):
                report_generator._primary_run_metric(run_root, row, primary, config)

            online_row = row.copy()
            online_row["policy"] = "ql_heft_online"
            online_result = online_row.to_dict()
            online_result["scenario_variant"] = ""
            online_publication_contract = resolve_publication_run_contract(
                config,
                online_result,
            )
            online_publication_identity = publication_run_contract_identity(
                online_publication_contract
            )
            online_bundle, online_bundle_identity = (
                write_publication_evidence_fixture(
                    run_dir,
                    scope=PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
                )
            )
            (run_dir / "run_metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "mode": "benchmark",
                        "run_seed": 1001,
                        "policy": "ql_heft_online",
                        "dataset": metadata_dataset,
                        "resolved_scenario": metadata_scenario,
                        "scenario_contract_identity": {
                            "schema_version": metadata_scenario_identity[
                                "schema_version"
                            ],
                            "sha256": metadata_scenario_identity["sha256"],
                        },
                        "publication_run_contract": online_publication_contract,
                        "publication_run_contract_identity": {
                            "schema_version": online_publication_identity[
                                "schema_version"
                            ],
                            "sha256": online_publication_identity["sha256"],
                        },
                        "publication_evidence_bundle": online_bundle,
                        "publication_evidence_bundle_identity": {
                            "schema_version": online_bundle_identity[
                                "schema_version"
                            ],
                            "sha256": online_bundle_identity["sha256"],
                        },
                        "hardware_target": config["hardware_target"],
                        "detected_hardware": {
                            "gpu_model": "NVIDIA GeForce RTX 3060",
                            "cpu_model": "Intel(R) Core(TM) i7-14700K",
                            "ram_gb": 22.0,
                        },
                        "result": online_result,
                    },
                    default=lambda value: value.item(),
                ),
                encoding="utf-8",
            )
            report_generator.validate_run_metadata_identity(
                run_dir,
                online_row,
                expected_mode="benchmark",
                config=config,
            )
            feedback_path = run_dir / "policy_feedback.csv"
            original_feedback = feedback_path.read_bytes()
            feedback_path.write_bytes(original_feedback + b"tampered")
            with self.assertRaisesRegex(
                ContractError,
                "metadata.publication_evidence_bundle",
            ):
                report_generator.validate_run_metadata_identity(
                    run_dir,
                    online_row,
                    expected_mode="benchmark",
                    config=config,
                )

    def test_completed_proof_rows_require_consistent_run_metadata(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            production_config = yaml.safe_load(handle)
        hardware_target = {
            "gpu_model": "NVIDIA GeForce RTX 3060",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22,
        }
        config = {
            "benchmark": {
                "report_scenarios": ["checkpoint_video_dag_shared"],
                "dataset_manifest": "configs/datasets.yaml",
            },
            "hardware_target": hardware_target,
            "scenarios": {
                "checkpoint_video_dag_shared": production_config["scenarios"][
                    "checkpoint_video_dag_shared"
                ]
            },
        }
        metadata_dataset = load_dataset(
            ROOT / "configs" / "datasets.yaml",
            "kpp_real_h264",
            mode="benchmark",
            project_root=ROOT,
            require_files=False,
        )
        metadata_scenario = resolve_scenario_contract(
            "checkpoint_video_dag_shared",
            config["scenarios"]["checkpoint_video_dag_shared"],
        )
        metadata_scenario_identity = scenario_contract_identity(metadata_scenario)
        row = {
            "scenario": "checkpoint_video_dag_shared",
            "system": "gstreamer_custom",
            "policy": "static_hybrid",
            "dataset": "kpp_real_h264",
            "status": "completed",
            "run_mode": "benchmark",
            "telemetry_source": "native",
            "deadline_ms": 100.0,
            "streams": 6,
            "duration_s": 180,
            "repeat": 1,
            "scenario_variant": float("nan"),
            "deployment_mode": "single-server-distributed",
            "host_topology": "single_host_ssh",
            "seed": 20260323,
            "run_seed": 1001,
        }
        summary = pd.DataFrame([row])
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            run_dir = (
                run_root
                / "dataset_kpp_real_h264"
                / "policy_static_hybrid"
                / "checkpoint_video_dag_shared"
                / "streams_6"
                / "deadline_100"
                / "gstreamer_custom"
                / "rep_01"
            )
            run_dir.mkdir(parents=True)
            evidence_bundle, evidence_identity = write_publication_evidence_fixture(
                run_dir
            )
            metadata_result = dict(row)
            metadata_result["scenario_variant"] = ""
            metadata = {
                "schema_version": 2,
                "mode": "benchmark",
                "run_seed": 1001,
                "policy": "static_hybrid",
                "dataset": json.loads(json.dumps(metadata_dataset)),
                "resolved_scenario": json.loads(json.dumps(metadata_scenario)),
                "scenario_contract_identity": {
                    "schema_version": metadata_scenario_identity["schema_version"],
                    "sha256": metadata_scenario_identity["sha256"],
                },
                "publication_evidence_bundle": evidence_bundle,
                "publication_evidence_bundle_identity": {
                    "schema_version": evidence_identity["schema_version"],
                    "sha256": evidence_identity["sha256"],
                },
                "hardware_target": hardware_target,
                "detected_hardware": {
                    "gpu_model": "NVIDIA GeForce RTX 3060",
                    "cpu_model": "Intel(R) Core(TM) i7-14700K",
                    "ram_gb": 22.0,
                },
                "result": metadata_result,
            }
            metadata_path = run_dir / "run_metadata.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            report_generator.validate_completed_run_metadata(run_root, summary, config)

            metadata["detected_hardware"]["gpu_model"] = "unknown"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "hardware_target:detected_gpu_model_missing",
            ):
                report_generator.validate_completed_run_metadata(run_root, summary, config)

            metadata["detected_hardware"]["gpu_model"] = "NVIDIA GeForce RTX 3060"

            metadata["dataset"]["streams"][0]["camera_role"] = "foreign_object"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "metadata.dataset_manifest_identity",
            ):
                report_generator.validate_completed_run_metadata(run_root, summary, config)
            metadata["dataset"] = json.loads(json.dumps(metadata_dataset))

            metadata["resolved_scenario"]["pipeline"][0] = "decode_drift"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "metadata.scenario_contract_identity",
            ):
                report_generator.validate_completed_run_metadata(
                    run_root,
                    summary,
                    config,
                )
            metadata["resolved_scenario"] = json.loads(
                json.dumps(metadata_scenario)
            )

            metadata["result"]["deadline_ms"] = 50.0
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "run_metadata.json does not match the publication summary.*deadline_ms",
            ):
                report_generator.validate_completed_run_metadata(run_root, summary, config)

    def test_completed_proof_rows_revalidate_raw_sidecars_and_summary_copy(self) -> None:
        scenario = "checkpoint_video_dag_shared"
        config = {
            "benchmark": {"report_scenarios": [scenario]},
            "scenarios": {
                scenario: {
                    "topology": {
                        "kind": "shared_video_dag",
                        "required_branches": ["plate_number"],
                    }
                }
            },
        }
        ingress = pd.DataFrame(
            {
                "terminal_status": ["completed"],
                "ingress_claim_eligible": [True],
                "censoring_rule": ["fixed_drain_cutoff_v1"],
            }
        )
        branch_terminals = pd.DataFrame(
            {
                "branch_id": ["plate_number"],
                "terminal_status": ["completed"],
                "detector": [verified_detector_identity("native-plate-number-v1")],
                "backend": ["openvino-dlstreamer:gvadetect"],
                "branch_terminal_claim_eligible": [True],
            }
        )
        stage_contracts = pd.DataFrame(
            {
                "semantic_contract_version": [
                    STAGE_SEMANTIC_CONTRACT_VERSION,
                    STAGE_SEMANTIC_CONTRACT_VERSION,
                ],
                "base_stage": ["decode", "preprocess"],
                "semantic_stage_sha256": ["1" * 64, "2" * 64],
                "semantic_contract_claim_eligible": [True, True],
            }
        )
        reset_evidence = pd.DataFrame(
            {
                "reset_contract_version": [1],
                "process_start_token": ["a" * 64],
                "telemetry_sink_id": ["b" * 64],
                "reset_claim_eligible": [True],
            }
        )
        resources = pd.DataFrame()
        passport = {
            "resource_attribution_complete": True,
            "resource_attributed_ingress_count": 1,
            "resource_unattributed_event_count": 0,
            "input_schedule_sha256": "c" * 64,
            "input_frame_key_sequence_sha256": "d" * 64,
            "measurement_window_duration_ms": 180000.0,
            "resource_attribution": "native_per_trace_ingress_cohort_v1",
            "measurement_signature": "e" * 64,
            "measurement_signature_payload_json": '{"covered":["cpu_time_ms","gpu_time_ms"]}',
            "c_obs_total_ms": 18.0,
            "c_obs_cpu_total_ms": 10.0,
            "c_obs_gpu_total_ms": 8.0,
            "c_obs_in_ms_per_ingress": 18.0,
            "c_obs_cpu_in_ms_per_ingress": 10.0,
            "c_obs_gpu_in_ms_per_ingress": 8.0,
            "c_obs_comp_ms_per_completed": 18.0,
            "c_obs_is_partial": True,
        }
        row = {
            "scenario": scenario,
            "system": "gstreamer_custom",
            "policy": "static_hybrid",
            "dataset": "kpp_real_h264",
            "status": "completed",
            "run_mode": "benchmark",
            "telemetry_source": "native",
            "deadline_ms": 100.0,
            "streams": 1,
            "duration_s": 180,
            "repeat": 1,
            "scenario_variant": "",
            "topology_trace_complete": True,
            "ingress_ledger_complete": True,
            "ingress_cohort_closed": True,
            "branch_terminal_trace_complete": True,
            "branch_terminal_event_count": 1,
            "native_branch_drop_event_count": 0,
            "checkpoint_frame_aggregation_complete": True,
            "stage_semantic_contract_complete": True,
            "resource_attribution_complete": True,
            "resource_attributed_ingress_count": 1,
            "resource_unattributed_event_count": 0,
            "reset_state_verified": True,
            "input_schedule_sha256": passport["input_schedule_sha256"],
            "input_frame_key_sequence_sha256": passport["input_frame_key_sequence_sha256"],
            "measurement_window_duration_ms": passport["measurement_window_duration_ms"],
            "ingress_censoring_rule": "fixed_drain_cutoff_v1",
            "resource_attribution": passport["resource_attribution"],
            "measurement_signature": passport["measurement_signature"],
            "measurement_signature_payload_json": passport["measurement_signature_payload_json"],
            "ingress_frame_count": 1,
            "completed_frame_count": 1,
            "dropped_frame_count": 0,
            "censored_frame_count": 0,
            "c_obs_total_ms": 18.0,
            "c_obs_cpu_total_ms": 10.0,
            "c_obs_gpu_total_ms": 8.0,
            "c_obs_in_ms_per_ingress": 18.0,
            "c_obs_cpu_in_ms_per_ingress": 10.0,
            "c_obs_gpu_in_ms_per_ingress": 8.0,
            "c_obs_comp_ms_per_completed": 18.0,
            "c_obs_is_partial": True,
            "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
            "semantic_prefix_contract_sha256": "f" * 64,
            "branch_analytics_contract_sha256": branch_analytics_contract_sha256(
                branch_terminals
            ),
            "reset_contract_version": 1,
            "reset_process_start_tokens_json": json.dumps(["a" * 64], separators=(",", ":")),
            "reset_telemetry_sink_id": "b" * 64,
        }
        summary = pd.DataFrame([row])
        sidecars = {
            "ingress_ledger": ingress,
            "branch_terminals": branch_terminals,
            "stage_contracts": stage_contracts,
            "reset_evidence": reset_evidence,
            "resource_events": resources,
        }
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp)
            with (
                mock.patch.object(
                    report_generator,
                    "canonicalize_frames_csv",
                    return_value=pd.DataFrame(),
                ),
                mock.patch.object(
                    report_generator,
                    "validate_frame_events",
                    return_value=pd.DataFrame(),
                ),
                mock.patch.object(
                    report_generator,
                    "validate_topology_events",
                    return_value=pd.DataFrame(),
                ) as validate_topology,
                mock.patch.object(
                    report_generator,
                    "validate_required_sidecars",
                    return_value=sidecars,
                ) as validate_sidecars,
                mock.patch.object(
                    report_generator,
                    "summarize_measurement_passport",
                    return_value=passport,
                ),
                mock.patch.object(
                    report_generator,
                    "semantic_prefix_contract_sha256",
                    return_value="f" * 64,
                ),
            ):
                report_generator.validate_completed_run_artifacts(run_root, summary, config)
                drifted = summary.copy()
                drifted.loc[0, "c_obs_in_ms_per_ingress"] = 999.0
                with self.assertRaisesRegex(
                    ContractError,
                    "publication summary differs from accepted raw sidecars.*c_obs_in_ms_per_ingress",
                ):
                    report_generator.validate_completed_run_artifacts(run_root, drifted, config)

            self.assertEqual(validate_topology.call_count, 2)
            self.assertEqual(validate_sidecars.call_count, 2)
            for call in validate_sidecars.call_args_list:
                self.assertTrue(call.kwargs["require_labeled_provenance"])
                self.assertTrue(call.kwargs["require_ingress_ledger"])
                self.assertTrue(call.kwargs["require_branch_terminals"])
                self.assertTrue(call.kwargs["require_stage_contracts"])
                self.assertTrue(call.kwargs["require_reset_evidence"])
                self.assertEqual(call.kwargs["topology_kind"], "shared_video_dag")
                self.assertEqual(call.kwargs["required_branches"], ["plate_number"])

    @staticmethod
    def _primary_analysis_fixture(*, shared_vmax: float = 4.0) -> tuple[dict, pd.DataFrame]:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        rows = []
        first_arms = config["benchmark"]["primary_architecture_contrast"]["arm_order"][
            "first_arm_by_pair"
        ]
        for repeat in range(1, 11):
            first_arm = first_arms[repeat - 1]
            second_arm = (
                "checkpoint_video_dag_shared"
                if first_arm == "checkpoint_independent_processes_baseline"
                else "checkpoint_independent_processes_baseline"
            )
            positions = {first_arm: 1, second_arm: 2}
            common = {
                "system": "gstreamer_custom",
                "policy": "static_hybrid",
                "dataset": "kpp_real_h264",
                "deadline_ms": 100.0,
                "streams": 6,
                "repeat": repeat,
                "seed": 20260323,
                "run_seed": 1000 + repeat,
                "input_schedule_sha256": f"{repeat:064x}",
                "input_frame_key_sequence_sha256": f"{repeat + 100:064x}",
                "measurement_window_duration_ms": 180000.0,
                "drain_rule": "drain_to_empty",
                "resource_attribution": "native_per_trace_bounded_stage_interval_ingress_cohort_v3",
                "measurement_signature": "a" * 64,
                "semantic_prefix_contract_sha256": "b" * 64,
                "decoder_factory": "nvh264dec",
                "branch_analytics_contract_sha256": "c" * 64,
                "c_obs_is_partial": True,
                "pair_contract_version": 1,
                "pair_order_strategy": "counterbalanced_alternating",
                "pair_repeat": repeat,
                "pair_first_arm": first_arm,
                "pair_second_arm": second_arm,
                "run_gate_pass": True,
                "run_gate_blockers": "",
            }
            rows.append(
                {
                    **common,
                    "scenario": "checkpoint_independent_processes_baseline",
                    "pair_arm_position": positions[
                        "checkpoint_independent_processes_baseline"
                    ],
                    "reset_process_start_tokens_json": json.dumps([f"{repeat:064x}"]),
                    "reset_telemetry_sink_id": f"{repeat + 2000:064x}",
                    "c_obs_in_ms_per_ingress": 10.0 + repeat / 10.0,
                    "c_obs_cpu_in_ms_per_ingress": 6.0 + repeat * 0.06,
                    "c_obs_gpu_in_ms_per_ingress": 4.0 + repeat * 0.04,
                    "event_factor_decode": 4.0,
                    "event_factor_preprocess": 4.0,
                    "vmax_completed_slo_violation_rate_percent": 5.0,
                    "drop_max_ingress_rate_percent": 2.0,
                }
            )
            rows.append(
                {
                    **common,
                    "scenario": "checkpoint_video_dag_shared",
                    "pair_arm_position": positions["checkpoint_video_dag_shared"],
                    "reset_process_start_tokens_json": json.dumps([f"{repeat + 1000:064x}"]),
                    "reset_telemetry_sink_id": f"{repeat + 3000:064x}",
                    "c_obs_in_ms_per_ingress": 5.0 + repeat / 20.0,
                    "c_obs_cpu_in_ms_per_ingress": 3.0 + repeat * 0.03,
                    "c_obs_gpu_in_ms_per_ingress": 2.0 + repeat * 0.02,
                    "event_factor_decode": 1.0,
                    "event_factor_preprocess": 1.0,
                    "vmax_completed_slo_violation_rate_percent": shared_vmax,
                    "drop_max_ingress_rate_percent": 1.0,
                }
            )
        return config, pd.DataFrame(rows)

    @staticmethod
    def _primary_policy_analysis_fixture(
        *,
        online_vmax: float = 4.0,
        online_drop: float = 1.0,
    ) -> tuple[dict, pd.DataFrame, dict[int, dict], dict]:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        rows = []
        replay_assessments: dict[int, dict] = {}
        first_arms = config["benchmark"]["primary_policy_ablation"]["arm_order"][
            "first_arm_by_pair"
        ]
        for repeat in range(1, 11):
            first_arm = first_arms[repeat - 1]
            positions = {
                first_arm: 1,
                (
                    "ql_heft_online"
                    if first_arm == "ql_heft_frozen"
                    else "ql_heft_frozen"
                ): 2,
            }
            common = {
                "scenario": "checkpoint_video_dag_shared",
                "system": "gstreamer_custom",
                "dataset": "kpp_real_h264",
                "deadline_ms": 100.0,
                "streams": 6,
                "repeat": repeat,
                "seed": 20260323,
                "run_seed": 5000 + repeat,
                "input_schedule_sha256": f"{repeat + 100:064x}",
                "input_frame_key_sequence_sha256": f"{repeat + 200:064x}",
                "terminal_identity_json": json.dumps(
                    [[f"frame-{repeat}-1", "completed"]], separators=(",", ":")
                ),
                "measurement_window_duration_ms": 180000.0,
                "drain_rule": "fixed_drain_cutoff_v1",
                "resource_attribution": "native_per_trace_ingress_cohort_v1",
                "measurement_signature": f"{repeat + 300:064x}",
                "semantic_prefix_contract_sha256": "b" * 64,
                "branch_analytics_contract_sha256": "c" * 64,
                "ingress_frame_count": 60,
                "completed_frame_count": 60,
                "dropped_frame_count": 0,
                "censored_frame_count": 0,
                "positive_completed_frames_per_stream": True,
                "pair_contract_version": 1,
                "pair_order_strategy": "counterbalanced_alternating",
                "pair_repeat": repeat,
                "pair_first_arm": first_arm,
                "pair_second_arm": (
                    "ql_heft_online"
                    if first_arm == "ql_heft_frozen"
                    else "ql_heft_frozen"
                ),
                "run_gate_pass": True,
                "run_gate_blockers": "",
            }
            rows.append(
                {
                    **common,
                    "policy": "ql_heft_frozen",
                    "pair_arm_position": positions["ql_heft_frozen"],
                    "reset_process_start_tokens_json": json.dumps(
                        [f"{repeat + 1000:064x}"]
                    ),
                    "reset_telemetry_sink_id": f"{repeat + 2000:064x}",
                    "vmax_completed_slo_violation_rate_percent": 5.0,
                    "drop_max_ingress_rate_percent": 1.0,
                }
            )
            rows.append(
                {
                    **common,
                    "policy": "ql_heft_online",
                    "pair_arm_position": positions["ql_heft_online"],
                    "reset_process_start_tokens_json": json.dumps(
                        [f"{repeat + 3000:064x}"]
                    ),
                    "reset_telemetry_sink_id": f"{repeat + 4000:064x}",
                    "vmax_completed_slo_violation_rate_percent": online_vmax,
                    "drop_max_ingress_rate_percent": online_drop,
                }
            )
            replay_assessments[repeat] = {
                "gate": "policy_implementation_equivalence",
                "scope": "frozen_v4_proxy_passport_replay",
                "status": "passed_proxy_reference_replay",
                "runtime_reference_replay_performed": True,
                "passed": True,
                "artifact_identity_verified": True,
                "formal_aw_heft_equivalence_evaluated": False,
                "blockers": [],
            }
        architecture_claim = {
            "claim_state": "favorable_preregistered_rule_satisfied",
            "accepted_pairs": 10,
            "blockers": [],
        }
        return config, pd.DataFrame(rows), replay_assessments, architecture_claim

    def test_primary_architecture_pair_bootstrap_and_favorable_claim_are_deterministic(self) -> None:
        config, run_metrics = self._primary_analysis_fixture()
        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        self.assertEqual(len(pairs), 10)
        self.assertTrue(pairs["pair_gate_pass"].all())
        self.assertTrue((pairs["delta_event_factor_decode"] == 3.0).all())
        self.assertTrue(
            np.allclose(
                pairs["baseline_c_obs_in_ms_per_ingress"],
                pairs["baseline_c_obs_cpu_in_ms_per_ingress"]
                + pairs["baseline_c_obs_gpu_in_ms_per_ingress"],
            )
        )

        self.assertTrue(
            np.allclose(
                pairs["shared_c_obs_in_ms_per_ingress"],
                pairs["shared_c_obs_cpu_in_ms_per_ingress"]
                + pairs["shared_c_obs_gpu_in_ms_per_ingress"],
            )
        )
        self.assertTrue(
            np.allclose(
                pairs["baseline_minus_shared_c_obs_cpu_in_ms_per_ingress"],
                pairs["baseline_c_obs_cpu_in_ms_per_ingress"]
                - pairs["shared_c_obs_cpu_in_ms_per_ingress"],
            )
        )
        self.assertTrue(
            np.allclose(
                pairs["baseline_minus_shared_c_obs_gpu_in_ms_per_ingress"],
                pairs["baseline_c_obs_gpu_in_ms_per_ingress"]
                - pairs["shared_c_obs_gpu_in_ms_per_ingress"],
            )
        )
        self.assertTrue(
            np.allclose(pairs["baseline_c_obs_cpu_share_percent"], 60.0)
        )
        self.assertTrue(
            np.allclose(pairs["shared_c_obs_cpu_share_percent"], 60.0)
        )
        self.assertTrue(
            np.allclose(
                pairs["shared_minus_baseline_c_obs_cpu_share_percentage_points"],
                0.0,
            )
        )

        first = build_primary_architecture_inference(pairs, config)
        second = build_primary_architecture_inference(pairs, config)
        pd.testing.assert_frame_equal(first, second)
        state = evaluate_primary_architecture_claim_state(pairs, first, config)
        self.assertEqual(
            state["claim_state"],
            "favorable_preregistered_rule_satisfied_partial_resource_coverage",
        )
        self.assertEqual(state["resource_coverage"], "partial")
        self.assertEqual(state["accepted_pairs"], 10)
        self.assertTrue(all(condition["passed"] for condition in state["conditions"]))
        mix = state["resource_mix_diagnostics"]
        self.assertEqual(mix["role"], "secondary_descriptive_not_claim_condition")
        self.assertEqual(mix["threshold_rule"], "none_preregistered")
        self.assertEqual(mix["accepted_pairs"], 10)
        self.assertEqual(
            mix["summaries"][
                "shared_minus_baseline_c_obs_cpu_share_percentage_points"
            ]["median"],
            0.0,
        )

        complete_metrics = run_metrics.copy()
        complete_metrics.loc[:, "c_obs_is_partial"] = False
        complete_pairs = build_primary_architecture_pairs_from_run_metrics(
            complete_metrics,
            config,
        )
        complete_inference = build_primary_architecture_inference(complete_pairs, config)
        complete_state = evaluate_primary_architecture_claim_state(
            complete_pairs,
            complete_inference,
            config,
        )
        self.assertEqual(
            complete_state["claim_state"],
            "favorable_preregistered_rule_satisfied",
        )
        self.assertEqual(complete_state["resource_coverage"], "complete")

    def test_primary_architecture_pair_requires_recorded_counterbalanced_arm_order(self) -> None:
        config, run_metrics = self._primary_analysis_fixture()
        run_metrics.loc[
            (run_metrics["repeat"] == 1)
            & (run_metrics["scenario"] == "checkpoint_independent_processes_baseline"),
            "pair_arm_position",
        ] = math.nan

        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        first_pair = pairs[pairs["repeat"] == 1].iloc[0]

        self.assertFalse(first_pair["pair_gate_pass"])
        self.assertIn(
            "baseline:pair_arm_position_mismatch",
            first_pair["pair_blockers"],
        )

    def test_primary_architecture_pair_requires_complete_metadata_contract(self) -> None:
        cases = [
            (
                "pair_contract_version",
                2,
                "baseline:pair_contract_version_mismatch",
            ),
            ("pair_repeat", 2, "baseline:pair_repeat_mismatch"),
            (
                "pair_second_arm",
                "checkpoint_independent_processes_baseline",
                "baseline:pair_second_arm_mismatch",
            ),
        ]
        for field, value, blocker in cases:
            with self.subTest(field=field):
                config, run_metrics = self._primary_analysis_fixture()
                run_metrics.loc[
                    (run_metrics["repeat"] == 1)
                    & (
                        run_metrics["scenario"]
                        == "checkpoint_independent_processes_baseline"
                    ),
                    field,
                ] = value
                pairs = build_primary_architecture_pairs_from_run_metrics(
                    run_metrics,
                    config,
                )
                first_pair = pairs[pairs["repeat"] == 1].iloc[0]
                self.assertFalse(first_pair["pair_gate_pass"])
                self.assertIn(blocker, first_pair["pair_blockers"])

    def test_primary_architecture_resource_mix_shift_stays_descriptive(self) -> None:
        config, run_metrics = self._primary_analysis_fixture()
        shared_mask = run_metrics["scenario"] == "checkpoint_video_dag_shared"
        shared_total = run_metrics.loc[shared_mask, "c_obs_in_ms_per_ingress"]
        run_metrics.loc[shared_mask, "c_obs_cpu_in_ms_per_ingress"] = shared_total * 0.2
        run_metrics.loc[shared_mask, "c_obs_gpu_in_ms_per_ingress"] = shared_total * 0.8

        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        inference = build_primary_architecture_inference(pairs, config)
        state = evaluate_primary_architecture_claim_state(pairs, inference, config)

        self.assertEqual(
            state["claim_state"],
            "favorable_preregistered_rule_satisfied_partial_resource_coverage",
        )
        self.assertTrue(
            np.allclose(pairs["shared_c_obs_cpu_share_percent"], 20.0)
        )
        self.assertTrue(
            np.allclose(
                pairs["shared_minus_baseline_c_obs_cpu_share_percentage_points"],
                -40.0,
            )
        )
        mix = state["resource_mix_diagnostics"]
        cpu_shift = mix["summaries"][
            "shared_minus_baseline_c_obs_cpu_share_percentage_points"
        ]
        gpu_shift = mix["summaries"][
            "shared_minus_baseline_c_obs_gpu_share_percentage_points"
        ]
        self.assertEqual(cpu_shift["median"], -40.0)
        self.assertEqual(gpu_shift["median"], 40.0)
        self.assertEqual(mix["threshold_rule"], "none_preregistered")

    def test_primary_pairing_rejects_branch_analytics_contract_mismatch(self) -> None:
        config, architecture_metrics = self._primary_analysis_fixture()
        architecture_metrics.loc[
            (architecture_metrics["scenario"] == "checkpoint_video_dag_shared")
            & (architecture_metrics["repeat"] == 1),
            "branch_analytics_contract_sha256",
        ] = "d" * 64
        architecture_pairs = build_primary_architecture_pairs_from_run_metrics(
            architecture_metrics,
            config,
        )
        architecture_first = architecture_pairs[
            architecture_pairs["repeat"] == 1
        ].iloc[0]
        self.assertFalse(architecture_first["pair_gate_pass"])
        self.assertIn(
            "pair_mismatch:branch_analytics_contract_sha256",
            architecture_first["pair_blockers"],
        )

        config, policy_metrics, replay, _ = self._primary_policy_analysis_fixture()
        policy_metrics.loc[
            (policy_metrics["policy"] == "ql_heft_online")
            & (policy_metrics["repeat"] == 1),
            "branch_analytics_contract_sha256",
        ] = "d" * 64
        policy_pairs = build_primary_policy_pairs_from_run_metrics(
            policy_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=True,
        )
        policy_first = policy_pairs[policy_pairs["repeat"] == 1].iloc[0]
        self.assertFalse(policy_first["pair_gate_pass"])
        self.assertIn(
            "pair_mismatch:branch_analytics_contract_sha256",
            policy_first["pair_blockers"],
        )

    def test_primary_analysis_writes_unexecuted_policy_replay_scope(self) -> None:
        config, _ = self._primary_analysis_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)

            assessment = report_generator.write_primary_policy_equivalence_scope(
                config,
                output_dir,
            )

            stored = json.loads(
                (output_dir / "primary_policy_equivalence_scope.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(stored, assessment)
            self.assertFalse(stored["proxy_passport_equivalence"]["passed"])
            self.assertTrue(
                stored["proxy_passport_equivalence"]["runtime_reference_replay_implemented"]
            )
            self.assertEqual(
                stored["proxy_passport_equivalence"]["status"],
                "ready_runtime_reference_replay_not_executed",
            )
            self.assertFalse(stored["formal_aw_heft_equivalence"]["passed"])
            self.assertEqual(
                stored["policy_analysis"]["claim_state"],
                "blocked_missing_accepted_policy_pairs_or_gates",
            )
            self.assertTrue(stored["policy_analysis"]["pair_analysis_implemented"])

    def test_primary_policy_pair_bootstrap_and_proxy_claim_are_deterministic(self) -> None:
        config, run_metrics, replay, architecture_claim = self._primary_policy_analysis_fixture()
        pairs = build_primary_policy_pairs_from_run_metrics(
            run_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=True,
        )
        self.assertEqual(len(pairs), 10)
        self.assertTrue(pairs["pair_gate_pass"].all())
        self.assertTrue(
            (
                pairs[
                    "online_minus_frozen_vmax_completed_slo_violation_rate_percentage_points"
                ]
                == -1.0
            ).all()
        )
        replay_record = json.loads(pairs.iloc[0]["policy_replay_assessment_json"])
        self.assertEqual(replay_record, replay[1])
        self.assertEqual(
            pairs.iloc[0]["policy_replay_status"],
            "passed_proxy_reference_replay",
        )

        first = build_primary_policy_inference(pairs, config)
        second = build_primary_policy_inference(pairs, config)
        pd.testing.assert_frame_equal(first, second)
        state = evaluate_primary_policy_claim_state(
            pairs,
            first,
            config,
            architecture_claim_state=architecture_claim,
        )
        self.assertEqual(state["claim_state"], "favorable_proxy_update_rule_satisfied")
        self.assertEqual(state["accepted_pairs"], 10)
        self.assertTrue(state["condition"]["passed"])
        self.assertFalse(state["formal_aw_heft_equivalence_evaluated"])
        self.assertIn("technical proxy", state["interpretation"])

    def test_primary_policy_pair_is_blocked_without_executed_replay(self) -> None:
        config, run_metrics, replay, architecture_claim = self._primary_policy_analysis_fixture()
        replay.pop(1)
        pairs = build_primary_policy_pairs_from_run_metrics(
            run_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=True,
        )
        first_pair = pairs[pairs["repeat"] == 1].iloc[0]
        self.assertFalse(first_pair["pair_gate_pass"])
        self.assertIn(
            "policy_implementation_equivalence:not_performed",
            first_pair["pair_blockers"],
        )
        inference = build_primary_policy_inference(pairs, config)
        state = evaluate_primary_policy_claim_state(
            pairs,
            inference,
            config,
            architecture_claim_state=architecture_claim,
        )
        self.assertEqual(state["claim_state"], "blocked_missing_required_pairs_or_gates")
        self.assertEqual(state["accepted_pairs"], 9)

    def test_primary_policy_pair_is_blocked_by_drop_guardrail(self) -> None:
        config, run_metrics, replay, architecture_claim = self._primary_policy_analysis_fixture(
            online_drop=1.1
        )
        pairs = build_primary_policy_pairs_from_run_metrics(
            run_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=True,
        )
        self.assertFalse(pairs["pair_gate_pass"].any())
        self.assertTrue(
            pairs["pair_blockers"].str.contains(
                "guardrail:online_drop_rate_increased",
                regex=False,
            ).all()
        )
        inference = build_primary_policy_inference(pairs, config)
        state = evaluate_primary_policy_claim_state(
            pairs,
            inference,
            config,
            architecture_claim_state=architecture_claim,
        )
        self.assertEqual(state["claim_state"], "blocked_missing_required_pairs_or_gates")

    def test_primary_policy_pair_requires_recorded_counterbalanced_arm_order(self) -> None:
        config, run_metrics, replay, _ = self._primary_policy_analysis_fixture()
        run_metrics.loc[run_metrics["repeat"] == 1, "pair_arm_position"] = math.nan
        pairs = build_primary_policy_pairs_from_run_metrics(
            run_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=True,
        )
        first_pair = pairs[pairs["repeat"] == 1].iloc[0]
        self.assertFalse(first_pair["pair_gate_pass"])
        self.assertIn("pair_arm_position_mismatch", first_pair["pair_blockers"])

    def test_primary_policy_pair_requires_complete_metadata_contract(self) -> None:
        cases = [
            ("pair_contract_version", 2, "pair_contract_version_mismatch"),
            ("pair_repeat", 2, "pair_repeat_mismatch"),
            ("pair_second_arm", "ql_heft_frozen", "pair_second_arm_mismatch"),
        ]
        for field, value, blocker in cases:
            with self.subTest(field=field):
                config, run_metrics, replay, _ = self._primary_policy_analysis_fixture()
                run_metrics.loc[run_metrics["repeat"] == 1, field] = value
                pairs = build_primary_policy_pairs_from_run_metrics(
                    run_metrics,
                    config,
                    replay_assessments=replay,
                    architecture_prerequisite_passed=True,
                    runtime_compatibility_passed=True,
                )
                first_pair = pairs[pairs["repeat"] == 1].iloc[0]
                self.assertFalse(first_pair["pair_gate_pass"])
                self.assertIn(blocker, first_pair["pair_blockers"])

    def test_primary_policy_pair_is_blocked_by_runtime_implementation_mismatch(self) -> None:
        config, run_metrics, replay, architecture_claim = self._primary_policy_analysis_fixture()
        pairs = build_primary_policy_pairs_from_run_metrics(
            run_metrics,
            config,
            replay_assessments=replay,
            architecture_prerequisite_passed=True,
            runtime_compatibility_passed=False,
        )
        self.assertFalse(pairs["pair_gate_pass"].any())
        self.assertTrue(
            pairs["pair_blockers"].str.contains(
                "runtime_policy_implementation_not_compatible",
                regex=False,
            ).all()
        )
        inference = build_primary_policy_inference(pairs, config)
        state = evaluate_primary_policy_claim_state(
            pairs,
            inference,
            config,
            architecture_claim_state=architecture_claim,
        )
        self.assertEqual(state["claim_state"], "blocked_missing_required_pairs_or_gates")
        self.assertEqual(state["accepted_pairs"], 0)

    def test_primary_policy_analysis_writes_blocked_artifacts_without_policy_runs(self) -> None:
        config, _ = self._primary_analysis_fixture()
        empty_pairs = build_primary_policy_pairs_from_run_metrics(
            pd.DataFrame(),
            config,
            architecture_prerequisite_passed=False,
        )
        architecture_claim = {
            "claim_state": "blocked_missing_required_pairs_or_gates",
            "accepted_pairs": 0,
            "blockers": ["missing_shared_arm"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            with mock.patch.object(
                report_generator,
                "build_primary_policy_pairs",
                return_value=empty_pairs,
            ):
                pairs, inference, claim = report_generator.write_primary_policy_analysis(
                    output_dir,
                    pd.DataFrame(),
                    config,
                    output_dir,
                    architecture_claim_state=architecture_claim,
                )

            self.assertEqual(len(pairs), 10)
            self.assertFalse(pairs["pair_gate_pass"].any())
            self.assertEqual(
                set(inference["analysis_status"]),
                {"blocked_missing_required_pairs_or_gates"},
            )
            self.assertEqual(
                claim["claim_state"],
                "blocked_missing_required_pairs_or_gates",
            )
            self.assertEqual(claim["accepted_pairs"], 0)
            for name in (
                "primary_policy_pairs.csv",
                "primary_policy_inference.csv",
                "primary_policy_claim_state.json",
            ):
                self.assertTrue((output_dir / name).is_file())

    def test_primary_architecture_claim_is_blocked_by_missing_pair(self) -> None:
        config, run_metrics = self._primary_analysis_fixture()
        run_metrics = run_metrics[
            ~(
                (run_metrics["scenario"] == "checkpoint_video_dag_shared")
                & (run_metrics["repeat"] == 10)
            )
        ]
        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        inference = build_primary_architecture_inference(pairs, config)
        state = evaluate_primary_architecture_claim_state(pairs, inference, config)
        self.assertEqual(state["claim_state"], "blocked_missing_required_pairs_or_gates")
        self.assertEqual(state["accepted_pairs"], 9)
        self.assertIn("missing_shared_arm", state["blockers"])
        self.assertIn(
            "shared_minus_baseline_c_obs_cpu_share_percentage_points",
            pairs.columns,
        )
        self.assertTrue(
            math.isnan(
                pairs.loc[
                    pairs["repeat"] == 10,
                    "shared_minus_baseline_c_obs_cpu_share_percentage_points",
                ].iloc[0]
            )
        )
        self.assertTrue((inference["analysis_status"] == "blocked_missing_required_pairs_or_gates").all())

    def test_primary_architecture_claim_is_not_confirmed_when_guardrail_interval_fails(self) -> None:
        config, run_metrics = self._primary_analysis_fixture(shared_vmax=6.0)
        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        inference = build_primary_architecture_inference(pairs, config)
        state = evaluate_primary_architecture_claim_state(pairs, inference, config)
        self.assertEqual(state["claim_state"], "not_confirmed_interval_conditions_failed")
        failed = [condition["metric"] for condition in state["conditions"] if not condition["passed"]]
        self.assertEqual(
            failed,
            ["shared_minus_baseline_vmax_completed_slo_violation_rate_percentage_points"],
        )

    def test_primary_architecture_pair_rejects_reused_process_or_sink_reset_identity(self) -> None:
        config, run_metrics = self._primary_analysis_fixture()
        baseline = run_metrics[
            (run_metrics["scenario"] == "checkpoint_independent_processes_baseline")
            & (run_metrics["repeat"] == 1)
        ].iloc[0]
        shared_mask = (
            (run_metrics["scenario"] == "checkpoint_video_dag_shared")
            & (run_metrics["repeat"] == 1)
        )
        run_metrics.loc[shared_mask, "reset_process_start_tokens_json"] = baseline[
            "reset_process_start_tokens_json"
        ]
        run_metrics.loc[shared_mask, "reset_telemetry_sink_id"] = baseline["reset_telemetry_sink_id"]

        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        first = pairs[pairs["repeat"] == 1].iloc[0]

        self.assertFalse(first["pair_gate_pass"])
        self.assertIn("pair_reset_process_start_token_reused", first["pair_blockers"])
        self.assertIn("pair_reset_telemetry_sink_reused", first["pair_blockers"])

        run_metrics.loc[shared_mask, "reset_telemetry_sink_id"] = "z" * 64
        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        first = pairs[pairs["repeat"] == 1].iloc[0]
        self.assertFalse(first["pair_gate_pass"])
        self.assertIn("pair_reset_telemetry_sink_id_invalid", first["pair_blockers"])

        run_metrics.loc[shared_mask, "reset_telemetry_sink_id"] = "d" * 64
        run_metrics.loc[shared_mask, "reset_process_start_tokens_json"] = json.dumps(["z" * 64])
        pairs = build_primary_architecture_pairs_from_run_metrics(run_metrics, config)
        first = pairs[pairs["repeat"] == 1].iloc[0]
        self.assertFalse(first["pair_gate_pass"])
        self.assertIn("shared:invalid_reset_process_start_tokens", first["pair_blockers"])

    def test_primary_architecture_only_skips_broad_report_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "runs"
            output_dir = root / "report"
            run_root.mkdir()
            summary = pd.DataFrame([{"scenario": "checkpoint_video_dag_shared"}])
            claim_state = {"claim_state": "blocked_missing_required_pairs_or_gates"}
            argv = [
                "generate_vast_report_artifacts.py",
                "--run-root",
                str(run_root),
                "--output-dir",
                str(output_dir),
                "--primary-architecture-only",
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    report_generator,
                    "load_report_config",
                    return_value={"protocol": {"repeats": 10}},
                ),
                mock.patch.object(report_generator, "read_summaries", return_value=summary),
                mock.patch.object(
                    report_generator,
                    "write_primary_architecture_analysis",
                    return_value=(pd.DataFrame(), pd.DataFrame(), claim_state),
                ) as write_primary,
                mock.patch.object(report_generator, "validate_report_inputs") as validate_broad,
            ):
                report_generator.main()

            self.assertTrue(output_dir.is_dir())
            write_primary.assert_called_once_with(run_root, summary, mock.ANY, output_dir)
            validate_broad.assert_not_called()

    def test_broad_report_runs_metadata_and_raw_preflight_before_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "runs"
            output_dir = root / "report"
            run_root.mkdir()
            summary = pd.DataFrame([{"scenario": "checkpoint_video_dag_shared"}])
            argv = [
                "generate_vast_report_artifacts.py",
                "--run-root",
                str(run_root),
                "--output-dir",
                str(output_dir),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.object(
                    report_generator,
                    "load_report_config",
                    return_value={"protocol": {"repeats": 10}},
                ),
                mock.patch.object(report_generator, "read_summaries", return_value=summary),
                mock.patch.object(report_generator, "validate_report_inputs") as validate_broad,
                mock.patch.object(
                    report_generator,
                    "validate_report_matrix_membership",
                ) as validate_matrix,
                mock.patch.object(
                    report_generator,
                    "validate_completed_run_metadata",
                ) as validate_metadata,
                mock.patch.object(
                    report_generator,
                    "validate_completed_run_artifacts",
                    side_effect=ContractError("raw artifact gate stopped report"),
                ) as validate_artifacts,
            ):
                with self.assertRaisesRegex(ContractError, "raw artifact gate stopped report"):
                    report_generator.main()

            validate_broad.assert_called_once_with(summary, mock.ANY)
            validate_matrix.assert_called_once_with(summary, mock.ANY, 10)
            validate_metadata.assert_called_once_with(run_root, summary, mock.ANY)
            validate_artifacts.assert_called_once_with(run_root, summary, mock.ANY)
            self.assertFalse(output_dir.exists())

    def test_savant_local_stream_outputs_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for stream_id in range(2):
                stream_dir = root / "streams" / f"stream_{stream_id}"
                stream_dir.mkdir(parents=True)
                trace_id = f"r:{stream_id}:1"
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": 1,
                            "ingress_timestamp_ms": 100,
                            "egress_timestamp_ms": 130,
                            "e2e_latency_ms": 30,
                            "objects": 3,
                            "detector": "peoplenet",
                            "backend": "deepstream_tensorrt",
                            "telemetry_source": "native",
                        }
                    ]
                ).to_csv(stream_dir / "frames.csv", index=False)
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": 1,
                            "stage": stage,
                            "role": "local",
                            "host": "localhost",
                            "resource": "gpu" if stage == "detect" else "cpu",
                            "queue_enter_timestamp_ms": 100 + idx * 10,
                            "stage_start_timestamp_ms": 100 + idx * 10,
                            "stage_end_timestamp_ms": 110 + idx * 10,
                            "queue_depth": 0,
                            "estimated_cost_ms": 10,
                            "policy_action": "native:savant",
                        }
                        for idx, stage in enumerate(["decode", "detect", "aggregate"])
                    ]
                ).to_csv(stream_dir / "frame_events.csv", index=False)

            merge_local_outputs(root, streams=2)
            frames = canonicalize_frames_csv(root / "frames.csv", mode="benchmark", run_id="r", detector="d", backend="b")
            events = validate_frame_events(root / "frame_events.csv")
            validate_stage_trace_coverage(
                root / "frames.csv",
                root / "frame_events.csv",
                required_stages=["decode", "detect", "aggregate"],
            )
            self.assertEqual(frames.shape[0], 2)
            self.assertEqual(events.shape[0], 6)

    def test_savant_local_stage_event_fragments_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    native_frame_row(
                        trace_id="r:0:1",
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    )
                ]
            ).to_csv(stream_dir / "frames.csv", index=False)
            write_savant_event_fragments(
                stream_dir,
                [
                    native_event_row(trace_id="r:0:1", stage="decode", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="detect", resource="gpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="track", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="classify", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="record", resource="cpu", policy_action="native:savant"),
                ],
            )

            with mock.patch.dict(os.environ, {"EXPERIMENT_PIPELINE_STAGES": "decode,detect,track,classify,record"}):
                merge_local_outputs(root, streams=1)
            events = validate_frame_events(root / "frame_events.csv")
            self.assertEqual(set(events["stage"]), {"decode", "detect", "track", "classify", "record"})
            self.assertEqual(events.shape[0], 5)

    def test_savant_local_probe_writes_only_declared_stage_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"EXPERIMENT_PIPELINE_STAGES": "decode,detect"},
        ):
            root = Path(tmp)
            inactive = SavantLocalTelemetryProbe(
                stage="track",
                output_dir=str(root),
                run_id="r",
                detector="d",
                backend="b",
            )

            self.assertIsNone(inactive.events)
            self.assertFalse((root / frame_event_filename("track")).exists())
            inactive.on_stop()

    def test_savant_local_merge_filters_measurement_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "measurement_start_ms").write_text("1000\n", encoding="utf-8")
            (root / "measurement_end_ms").write_text("2000\n", encoding="utf-8")
            for stream_id in range(2):
                stream_dir = root / "streams" / f"stream_{stream_id}"
                stream_dir.mkdir(parents=True)
                frame_rows = []
                event_rows = []
                samples = [
                    (1, 100, 130),
                    (2, 1100, 1130),
                    (3, 2100, 2130),
                ]
                for frame_id, ingress_ms, egress_ms in samples:
                    trace_id = f"r:{stream_id}:{frame_id}"
                    frame_rows.append(
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": frame_id,
                            "ingress_timestamp_ms": ingress_ms,
                            "egress_timestamp_ms": egress_ms,
                            "e2e_latency_ms": egress_ms - ingress_ms,
                            "objects": 3,
                            "detector": "peoplenet",
                            "backend": "deepstream_tensorrt",
                            "telemetry_source": "native",
                        }
                    )
                    for idx, stage in enumerate(["decode", "detect", "aggregate"]):
                        start_ms = ingress_ms + idx * 10
                        event_rows.append(
                            {
                                "schema_version": 2,
                                "run_id": "r",
                                "trace_id": trace_id,
                                "stream_id": stream_id,
                                "frame_id": frame_id,
                                "stage": stage,
                                "role": "local",
                                "host": "localhost",
                                "resource": "gpu" if stage == "detect" else "cpu",
                                "queue_enter_timestamp_ms": start_ms,
                                "stage_start_timestamp_ms": start_ms,
                                "stage_end_timestamp_ms": start_ms + 1,
                                "queue_depth": 0,
                                "estimated_cost_ms": 1,
                                "policy_action": "native:savant",
                            }
                        )
                pd.DataFrame(frame_rows).to_csv(stream_dir / "frames.csv", index=False)
                pd.DataFrame(event_rows).to_csv(stream_dir / "frame_events.csv", index=False)

            merge_local_outputs(root, streams=2)
            frames = canonicalize_frames_csv(
                root / "frames.csv",
                mode="benchmark",
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
            )
            events = validate_frame_events(root / "frame_events.csv")
            validate_stage_trace_coverage(
                root / "frames.csv",
                root / "frame_events.csv",
                required_stages=["decode", "detect", "aggregate"],
            )
            self.assertEqual(set(frames["frame_id"]), {2})
            self.assertEqual(frames.shape[0], 2)
            self.assertEqual(events.shape[0], 6)

    def test_savant_local_merge_rejects_malformed_unmeasured_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "measurement_start_ms").write_text("1000\n", encoding="utf-8")
            (root / "measurement_end_ms").write_text("2000\n", encoding="utf-8")
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    native_frame_row(
                        trace_id="r:0:1",
                        frame_id=1,
                        ingress_timestamp_ms=100,
                        egress_timestamp_ms=130,
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    ),
                    native_frame_row(
                        trace_id="r:0:2",
                        frame_id=2,
                        ingress_timestamp_ms=1100,
                        egress_timestamp_ms=1130,
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    ),
                ]
            ).to_csv(stream_dir / "frames.csv", index=False)
            write_savant_event_fragments(
                stream_dir,
                [
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="decode", policy_action="native:savant"),
                    native_event_row(
                        trace_id="r:0:1",
                        frame_id=1,
                        stage="detect",
                        stage_start_timestamp_ms="None",
                        policy_action="native:savant",
                    ),
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="detect", resource="gpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="aggregate", policy_action="native:savant"),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, r"frame_events_detect\.csv:2: .*stage_start_timestamp_ms"):
                merge_local_outputs(root, streams=1)

    def test_savant_local_merge_rejects_malformed_measured_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame([native_frame_row(trace_id="r:0:1", detector="peoplenet", backend="deepstream_tensorrt")]).to_csv(
                stream_dir / "frames.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    native_event_row(
                        trace_id="r:0:1",
                        stage_start_timestamp_ms="None",
                        policy_action="native:savant",
                    )
                ]
            ).to_csv(stream_dir / "frame_events.csv", index=False)

            with self.assertRaisesRegex(RuntimeError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                merge_local_outputs(root, streams=1)

    def test_savant_local_stage_event_writers_handle_concurrent_stage_writes(self) -> None:
        class Buffer:
            def __init__(self, frame_id: int) -> None:
                self.pts = frame_id
                self.offset = frame_id

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probes = [
                SavantLocalTelemetryProbe(
                    stage=stage,
                    output_dir=str(root),
                    run_id="r",
                    detector="peoplenet",
                    backend="deepstream_tensorrt",
                    min_objects=1,
                    max_objects=3,
                )
                for stage in ("decode", "detect", "aggregate")
            ]
            errors: list[BaseException] = []

            def write_stage(probe: SavantLocalTelemetryProbe) -> None:
                try:
                    for frame_id in range(1000, 1050):
                        probe.process_buffer(Buffer(frame_id))
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write_stage, args=(probe,)) for probe in probes]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertEqual(errors, [])
            finally:
                for probe in probes:
                    probe.on_stop()

            self.assertFalse((root / "frame_events.csv").exists())
            for stage in ("decode", "detect", "aggregate"):
                path = root / frame_event_filename(stage)
                with path.open("r", newline="", encoding="utf-8") as src:
                    rows = list(csv.DictReader(src))
                self.assertEqual(len(rows), 50)
                for row_number, row in enumerate(rows, start=2):
                    for column in FRAME_EVENT_COLUMNS:
                        self.assertIsNotNone(row.get(column), f"row {row_number} column {column}")
                        self.assertNotEqual(str(row.get(column)).strip(), "", f"row {row_number} column {column}")
                validate_frame_events(path)

    def test_savant_local_pyfunc_writes_native_rows_from_buffer(self) -> None:
        class Buffer:
            pts = 42
            offset = 42

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decode = SavantLocalTelemetryProbe(
                stage="decode",
                output_dir=str(root),
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
                min_objects=1,
                max_objects=3,
            )
            aggregate = SavantLocalTelemetryProbe(
                stage="aggregate",
                output_dir=str(root),
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
                min_objects=1,
                max_objects=3,
            )

            self.assertIsInstance(decode, BasePyFuncPlugin)
            decode.process_buffer(Buffer())
            aggregate.process_buffer(Buffer())
            self.assertTrue(decode.on_stop())
            self.assertTrue(aggregate.on_stop())

            frames = canonicalize_frames_csv(
                root / "frames.csv",
                mode="benchmark",
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
            )
            decode_events = validate_frame_events(root / frame_event_filename("decode"))
            aggregate_events = validate_frame_events(root / frame_event_filename("aggregate"))
            events = pd.concat([decode_events, aggregate_events], ignore_index=True)

            self.assertFalse((root / "frame_events.csv").exists())
            self.assertEqual(frames.shape[0], 1)
            self.assertEqual(set(events["stage"]), {"decode", "aggregate"})

    def test_throughput_uses_completed_frames_per_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [
                    {"e2e_latency_ms": 10, "telemetry_source": "native"},
                    {"e2e_latency_ms": 20, "telemetry_source": "native"},
                    {"e2e_latency_ms": 40, "telemetry_source": "native"},
                    {"e2e_latency_ms": 80, "telemetry_source": "native"},
                ]
            ).to_csv(path, index=False)
            result = summarize_frames(path, deadline_s=0.05, measurement_s=2)
            self.assertEqual(result["throughput_fps"], 2.0)
            self.assertEqual(result["slo_violation_rate_percent"], 25.0)

    @unittest.skipUnless((ROOT / "data" / "videos" / "kpp" / "1.avi").exists(), "real KPP AVI files are not present")
    @unittest.skipUnless(shutil.which("ffprobe") is not None, "ffprobe is required for AVI metadata validation")
    def test_kpp_real_avi_manifest_validates_real_files_and_fps_policy(self) -> None:
        dataset = load_dataset(
            ROOT / "configs" / "datasets.yaml",
            "kpp_real_avi",
            mode="benchmark",
            project_root=ROOT,
            require_files=True,
        )

        self.assertEqual(dataset["name"], "kpp_real_avi")
        self.assertEqual(len(dataset["streams"]), 6)
        underbody = [stream for stream in dataset["streams"] if stream["camera_role"] == "foreign_object"]
        self.assertEqual(len(underbody), 1)
        self.assertEqual(underbody[0]["frame_count"], 81173)
        plate = [stream for stream in dataset["streams"] if stream["path"] == "data/videos/kpp/2.avi"][0]
        self.assertEqual(plate["r_frame_rate"], "30/1")
        self.assertEqual(plate["avg_frame_rate"], "600/1")
        self.assertEqual(plate["fps_policy"], "pts_frame_count")
        self.assertEqual(dataset["annotations"]["accuracy_ground_truth"], False)

    def test_publishable_dataset_requires_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "datasets.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "datasets": {
                            "public": {
                                "publishable": True,
                                "streams": [{"path": "clip.mp4", "sha256": "SET_AFTER_PREPARATION"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ContractError):
                load_dataset(manifest, "public", mode="benchmark", project_root=root, require_files=False)

    def test_dataset_manifest_identity_covers_logical_stream_contract(self) -> None:
        dataset = load_dataset(
            ROOT / "configs" / "datasets.yaml",
            "kpp_real_h264",
            mode="benchmark",
            project_root=ROOT,
            require_files=False,
        )
        expected = dataset_manifest_identity(dataset)
        self.assertEqual(dataset["manifest_identity_schema_version"], expected["schema_version"])
        self.assertEqual(dataset["manifest_identity_sha256"], expected["sha256"])

        runtime_only = json.loads(json.dumps(dataset))
        runtime_only["streams"][0]["absolute_path"] = "/different/host/path.mp4"
        runtime_only["streams"][0]["resolved_sha256"] = "f" * 64
        self.assertEqual(dataset_manifest_identity(runtime_only)["sha256"], expected["sha256"])

        mutations = []
        reordered = json.loads(json.dumps(dataset))
        reordered["streams"][0], reordered["streams"][1] = (
            reordered["streams"][1],
            reordered["streams"][0],
        )
        mutations.append(reordered)
        changed_role = json.loads(json.dumps(dataset))
        changed_role["streams"][0]["camera_role"] = "foreign_object"
        mutations.append(changed_role)
        changed_checksum = json.loads(json.dumps(dataset))
        changed_checksum["streams"][0]["sha256"] = "0" * 64
        mutations.append(changed_checksum)
        changed_annotations = json.loads(json.dumps(dataset))
        changed_annotations["annotations"]["sha256"] = "1" * 64
        mutations.append(changed_annotations)

        for changed in mutations:
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    dataset_manifest_identity(changed)["sha256"],
                    expected["sha256"],
                )

    def test_scenario_contract_identity_covers_resolved_execution_contract(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            config = yaml.safe_load(handle)
        scenario = resolve_scenario_contract(
            "checkpoint_video_dag_shared",
            config["scenarios"]["checkpoint_video_dag_shared"],
        )
        expected = scenario_contract_identity(scenario)

        reordered_mapping = json.loads(json.dumps(scenario))
        reordered_mapping["network"] = dict(
            reversed(list(reordered_mapping["network"].items()))
        )
        self.assertEqual(
            scenario_contract_identity(reordered_mapping)["sha256"],
            expected["sha256"],
        )

        mutations = []
        reordered_pipeline = json.loads(json.dumps(scenario))
        reordered_pipeline["pipeline"][0], reordered_pipeline["pipeline"][1] = (
            reordered_pipeline["pipeline"][1],
            reordered_pipeline["pipeline"][0],
        )
        mutations.append(reordered_pipeline)
        changed_topology = json.loads(json.dumps(scenario))
        changed_topology["topology"]["kind"] = "independent_processes"
        mutations.append(changed_topology)
        changed_placement = json.loads(json.dumps(scenario))
        changed_placement["placement"]["stages"]["decode"] = "gpu_worker"
        mutations.append(changed_placement)
        changed_routing = json.loads(json.dumps(scenario))
        changed_routing["workload"]["routing_scope"] = "production"
        mutations.append(changed_routing)

        for changed in mutations:
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    scenario_contract_identity(changed)["sha256"],
                    expected["sha256"],
                )

    def test_publication_run_contract_covers_protocol_system_and_primary_cell(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            config = yaml.safe_load(handle)
        result = {
            "run_mode": "benchmark",
            "system": "gstreamer_custom",
            "scenario": "checkpoint_video_dag_shared",
            "scenario_variant": "",
            "repeat": 1,
            "streams": 6,
            "duration_s": 180,
            "deployment_mode": "local",
            "host_topology": "local",
            "distributed": False,
            "placement_policy": "checkpoint_video_dag_local_cpu_gpu",
            "detector": "custom_gstreamer_native",
            "backend": "gstreamer",
            "policy": "static_hybrid",
            "dataset": "kpp_real_h264",
            "deadline_ms": 100.0,
            "seed": 20260323,
            "run_seed": 1001,
        }
        contract = resolve_publication_run_contract(config, result)
        expected = publication_run_contract_identity(contract)
        self.assertIn("primary_architecture_contrast", contract)
        self.assertNotIn("primary_policy_ablation", contract)

        reordered = json.loads(json.dumps(contract))
        reordered["protocol"] = dict(reversed(list(reordered["protocol"].items())))
        self.assertEqual(
            publication_run_contract_identity(reordered)["sha256"],
            expected["sha256"],
        )

        mutations = []
        changed_protocol = json.loads(json.dumps(contract))
        changed_protocol["protocol"]["warmup_s"] = 31
        mutations.append(changed_protocol)
        changed_system = json.loads(json.dumps(contract))
        changed_system["system"]["configuration"]["command"] += " --drift"
        mutations.append(changed_system)
        changed_primary = json.loads(json.dumps(contract))
        changed_primary["primary_architecture_contrast"]["interval"][
            "resamples"
        ] = 9999
        mutations.append(changed_primary)
        for changed in mutations:
            with self.subTest(changed=changed):
                self.assertNotEqual(
                    publication_run_contract_identity(changed)["sha256"],
                    expected["sha256"],
                )

        policy_result = dict(result)
        policy_result["policy"] = "ql_heft_online"
        policy_contract = resolve_publication_run_contract(config, policy_result)
        self.assertIn("primary_architecture_contrast", policy_contract)
        self.assertIn("primary_policy_ablation", policy_contract)

    def test_publication_evidence_bundle_rejects_missing_tampered_or_symlinked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, identity = write_publication_evidence_fixture(root)

            validated = validate_publication_evidence_bundle(
                root,
                bundle,
                {
                    "schema_version": identity["schema_version"],
                    "sha256": identity["sha256"],
                },
                expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
            )
            self.assertEqual(validated, bundle)
            self.assertEqual(
                [record["relative_path"] for record in bundle["files"]],
                sorted(PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS),
            )

            target = root / "stage_contracts.csv"
            original = target.read_bytes()
            target.write_bytes(original + b"tampered")
            with self.assertRaisesRegex(ContractError, "does not match current"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
                )
            target.write_bytes(original)

            target.unlink()
            with self.assertRaisesRegex(ContractError, "is missing"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
                )
            target.symlink_to(root / "frames.csv")
            with self.assertRaisesRegex(ContractError, "must not be a symbolic link"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
                )

            target.unlink()
            target.write_bytes(original)
            drifted_identity = dict(identity)
            drifted_identity["sha256"] = "f" * 64
            with self.assertRaisesRegex(ContractError, "identity SHA-256"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    drifted_identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
                )

    def test_publication_evidence_bundle_policy_scope_binds_online_feedback(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            config = yaml.safe_load(handle)
        result = {
            "system": "gstreamer_custom",
            "scenario": "checkpoint_video_dag_shared",
            "policy": "static_hybrid",
        }
        self.assertEqual(
            resolve_publication_evidence_bundle_scope(config, result),
            PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
        )
        result["policy"] = "ql_heft_frozen"
        self.assertEqual(
            resolve_publication_evidence_bundle_scope(config, result),
            PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE,
        )
        result["policy"] = "ql_heft_online"
        self.assertEqual(
            resolve_publication_evidence_bundle_scope(config, result),
            PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
        )
        self.assertNotIn(
            "policy_feedback.csv",
            publication_evidence_bundle_files(
                PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE
            ),
        )
        self.assertIn(
            "policy_feedback.csv",
            publication_evidence_bundle_files(
                PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, identity = write_publication_evidence_fixture(
                root,
                scope=PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
            )
            validate_publication_evidence_bundle(
                root,
                bundle,
                identity,
                expected_scope=PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
            )
            with self.assertRaisesRegex(ContractError, "scope does not match"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
                )

            feedback_path = root / "policy_feedback.csv"
            original_feedback = feedback_path.read_bytes()
            feedback_path.write_bytes(original_feedback + b"tampered")
            with self.assertRaisesRegex(ContractError, "does not match current"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
                )

    def test_dataset_preflight_prints_byte_and_manifest_identities(self) -> None:
        dataset = {
            "name": "fixture",
            "streams": [{"stream_id": 0}],
            "aggregate_sha256": "a" * 64,
            "manifest_identity_schema_version": 1,
            "manifest_identity_sha256": "b" * 64,
        }
        argv = ["check_dataset.py", "--dataset", "fixture"]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(dataset_checker, "load_dataset", return_value=dataset),
            mock.patch("builtins.print") as print_output,
        ):
            dataset_checker.main()

        rendered = print_output.call_args.args[0]
        self.assertIn("aggregate_sha256=", rendered)
        self.assertIn("manifest_identity_schema_version=1", rendered)
        self.assertIn("manifest_identity_sha256=", rendered)

    def test_network_acceptance_gate(self) -> None:
        ok, reason = network_profile_matches({"latency_ms": 80}, {"latency_ms": [60, 140]})
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        ok, reason = network_profile_matches({"latency_ms": 10}, {"latency_ms": [60, 140]})
        self.assertFalse(ok)
        self.assertIn("outside", reason)

    def test_preflight_parsers(self) -> None:
        ping = "4 packets transmitted, 4 received, 0% packet loss\nrtt min/avg/max/mdev = 1.0/2.0/3.0/0.5 ms"
        self.assertEqual(parse_ping_output(ping)["latency_ms"], 2.0)
        self.assertEqual(parse_chrony_tracking("Last offset     : +0.000002 seconds"), 0.002)
        self.assertEqual(parse_iperf_output('{"end":{"sum_received":{"bits_per_second":125000000}}}'), 125.0)


if __name__ == "__main__":
    unittest.main()
