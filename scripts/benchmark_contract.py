#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from formal_aw_heft_reference import FormalAwHeftError, validate_reference_artifact


TELEMETRY_SCHEMA_VERSION = 2
HARDWARE_TARGET_ASSESSMENT_VERSION = 1
HARDWARE_RAM_TOLERANCE_GB = 2.0
DATASET_MANIFEST_IDENTITY_VERSION = 1
SCENARIO_CONTRACT_IDENTITY_VERSION = 1
PUBLICATION_RUN_CONTRACT_IDENTITY_VERSION = 1
PUBLICATION_EVIDENCE_BUNDLE_IDENTITY_VERSION = 1
BRANCH_ANALYTICS_CONTRACT_VERSION = 1
FRAME_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
    "detector",
    "backend",
    "telemetry_source",
]
FRAME_EVENT_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "role",
    "host",
    "resource",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
    "policy_action",
]
FRAME_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "egress_timestamp_ms",
    "e2e_latency_ms",
    "objects",
}
FRAME_EVENT_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms",
    "stage_end_timestamp_ms",
    "queue_depth",
    "estimated_cost_ms",
}


def _normalize_hardware_model_name(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()
    normalized = re.sub(r"\b(r|tm)\b", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def assess_hardware_target(
    target: dict[str, Any],
    detected: dict[str, Any],
    *,
    ram_tolerance_gb: float = HARDWARE_RAM_TOLERANCE_GB,
) -> dict[str, Any]:
    """Compare a detected host with the frozen publication hardware target."""

    target_gpu = _normalize_hardware_model_name(target.get("gpu_model", ""))
    target_cpu = _normalize_hardware_model_name(target.get("cpu_model", ""))
    detected_gpu = _normalize_hardware_model_name(detected.get("gpu_model", ""))
    detected_cpu = _normalize_hardware_model_name(detected.get("cpu_model", ""))
    blockers: list[str] = []

    if not target_gpu:
        blockers.append("target_gpu_model_missing")
    elif not detected_gpu or detected_gpu == "unknown":
        blockers.append("detected_gpu_model_missing")
    elif target_gpu not in detected_gpu:
        blockers.append("gpu_model_mismatch")

    if not target_cpu:
        blockers.append("target_cpu_model_missing")
    elif not detected_cpu or detected_cpu == "unknown":
        blockers.append("detected_cpu_model_missing")
    elif target_cpu not in detected_cpu:
        blockers.append("cpu_model_mismatch")

    try:
        target_ram = float(target.get("ram_gb"))
    except (TypeError, ValueError):
        target_ram = math.nan
    try:
        detected_ram = float(detected.get("ram_gb"))
    except (TypeError, ValueError):
        detected_ram = math.nan
    if not math.isfinite(target_ram) or target_ram <= 0:
        blockers.append("target_ram_gb_missing")
    elif not math.isfinite(detected_ram) or detected_ram <= 0:
        blockers.append("detected_ram_gb_missing")
    elif abs(detected_ram - target_ram) > float(ram_tolerance_gb):
        blockers.append("ram_gb_mismatch")

    blockers = list(dict.fromkeys(blockers))
    return {
        "assessment_schema_version": HARDWARE_TARGET_ASSESSMENT_VERSION,
        "status": "target_hardware_verified" if not blockers else "blocked_hardware_target_mismatch",
        "passed": not blockers,
        "ram_tolerance_gb": float(ram_tolerance_gb),
        "target": dict(target),
        "detected": dict(detected),
        "blockers": blockers,
        "interpretation": (
            "The detected CPU, GPU, and RAM match the frozen publication target."
            if not blockers
            else "Publishable inference is blocked because the detected host does not match the frozen hardware target."
        ),
    }


NETWORK_COLUMNS = [
    "timestamp_ms",
    "source_role",
    "target_role",
    "latency_ms",
    "jitter_ms",
    "packet_loss_percent",
    "bandwidth_mbps",
    "clock_offset_ms",
    "status",
]
LEGACY_RESOURCE_EVENT_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "resource",
    "timestamp_ms",
    "cpu_time_ms",
    "gpu_time_ms",
    "h2d_bytes",
    "d2h_bytes",
    "nvdec_util_percent",
    "vram_mb",
    "telemetry_source",
]
RESOURCE_EVENT_PROVENANCE_COLUMNS = [
    "time_provenance",
    "transfer_provenance",
    "nvdec_provenance",
    "vram_provenance",
]
RESOURCE_EVENT_COLUMNS = [
    *LEGACY_RESOURCE_EVENT_COLUMNS[:-1],
    *RESOURCE_EVENT_PROVENANCE_COLUMNS,
    "telemetry_source",
]
LEGACY_POLICY_DECISION_COLUMNS = [
    "schema_version",
    "run_id",
    "trace_id",
    "stream_id",
    "frame_id",
    "stage",
    "policy",
    "decision",
    "resource",
    "queue_depth",
    "estimated_cost_ms",
    "deadline_ms",
    "telemetry_source",
]
POLICY_DECISION_PROVENANCE_COLUMNS = ["decision_provenance", "trace_completeness"]
PROVENANCE_POLICY_DECISION_COLUMNS = [
    *LEGACY_POLICY_DECISION_COLUMNS[:-1],
    *POLICY_DECISION_PROVENANCE_COLUMNS,
    "telemetry_source",
]
POLICY_TRACE_COLUMNS = [
    "policy_version",
    "allowed_resources_json",
    "alternative_scores_json",
    "cost_components_json",
    "parameters_json",
    "tie_break_rule",
    "decision_mode",
    "update_seq",
    "update_json",
    "reason",
]
ENGINEERING_POLICY_DECISION_COLUMNS = [
    *LEGACY_POLICY_DECISION_COLUMNS[:-1],
    *POLICY_TRACE_COLUMNS,
    *POLICY_DECISION_PROVENANCE_COLUMNS,
    "telemetry_source",
]
POLICY_CAUSAL_TRACE_COLUMNS = [
    "decision_id",
    "decision_seq",
    "decision_timestamp_ms",
    "graph_version",
    "profile_version",
    "feature_provenance_json",
    "terminal_status",
    "terminal_timestamp_ms",
    "update_timestamp_ms",
    "source_decision_ids_json",
    "first_consumer_decision_id",
    "first_consumer_decision_seq",
    "causal_trace_completeness",
]
POLICY_DECISION_COLUMNS = [
    *LEGACY_POLICY_DECISION_COLUMNS[:-1],
    *POLICY_TRACE_COLUMNS,
    *POLICY_CAUSAL_TRACE_COLUMNS,
    *POLICY_DECISION_PROVENANCE_COLUMNS,
    "telemetry_source",
]
POLICY_FEEDBACK_COLUMNS = [
    "schema_version",
    "run_id",
    "policy",
    "feedback_seq",
    "feedback_timestamp_ms",
    "source_trace_id",
    "terminal_status",
    "terminal_timestamp_ms",
    "source_decision_ids_json",
    "source_parameter_snapshot_seq",
    "parameter_lag",
    "events_since_update",
    "old_weights_json",
    "raw_weights_json",
    "projected_weights_json",
    "weight_lower_bounds_json",
    "weight_upper_bounds_json",
    "projection_rule",
    "variation_before",
    "variation_after",
    "variation_budget",
    "feedback_features_json",
    "feedback_action",
    "reason",
    "update_seq",
    "first_consumer_decision_id",
    "first_consumer_decision_seq",
    "feedback_provenance",
    "feedback_trace_completeness",
    "telemetry_source",
]
LEGACY_DROP_COUNTER_COLUMNS = [
    "schema_version",
    "run_id",
    "stream_id",
    "camera_role",
    "dropped_frames",
    "late_frames",
    "total_frames",
    "deadline_ms",
    "drop_rate_percent",
    "late_rate_percent",
    "reason",
    "telemetry_source",
]
DROP_COUNTER_PROVENANCE_COLUMNS = ["drop_provenance", "late_provenance"]
DROP_COUNTER_COLUMNS = [
    *LEGACY_DROP_COUNTER_COLUMNS[:-1],
    *DROP_COUNTER_PROVENANCE_COLUMNS,
    "telemetry_source",
]
INGRESS_LEDGER_COLUMNS = [
    "schema_version",
    "run_id",
    "cohort_id",
    "trace_id",
    "input_frame_key",
    "admission_seq",
    "source_sha256",
    "source_cycle",
    "access_unit_pts_ns",
    "payload_sha256",
    "payload_size_bytes",
    "schedule_offset_ns",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "window_start_timestamp_ms",
    "window_end_timestamp_ms",
    "terminal_status",
    "terminal_timestamp_ms",
    "drain_end_timestamp_ms",
    "terminal_reason",
    "censoring_rule",
    "ingress_provenance",
    "terminal_provenance",
    "telemetry_source",
]
CHECKPOINT_FRAME_AGGREGATE_DETECTOR = "checkpoint_all_branches_per_stream_v1"
BRANCH_TERMINAL_COLUMNS = [
    "schema_version",
    "run_id",
    "cohort_id",
    "trace_id",
    "input_frame_key",
    "stream_id",
    "frame_id",
    "branch_id",
    "terminal_status",
    "terminal_timestamp_ms",
    "objects",
    "detector",
    "backend",
    "terminal_reason",
    "terminal_provenance",
    "telemetry_source",
]
STAGE_SEMANTIC_CONTRACT_VERSION = 2
STAGE_CONTRACT_COLUMNS = [
    "schema_version",
    "semantic_contract_version",
    "run_id",
    "contract_id",
    "execution_domain",
    "stage",
    "base_stage",
    "implementation_name",
    "implementation_version",
    "implementation_config_json",
    "config_sha256",
    "implementation_artifacts_json",
    "implementation_artifacts_sha256",
    "implementation_artifact_provenance",
    "transform_json",
    "output_media_type",
    "output_format",
    "output_dtype",
    "output_shape_json",
    "ordering_contract",
    "contract_provenance",
    "telemetry_source",
]
RESET_EVIDENCE_CONTRACT_VERSION = 1
RESET_EVIDENCE_COLUMNS = [
    "schema_version",
    "reset_contract_version",
    "run_id",
    "cohort_id",
    "process_instance_id",
    "process_role",
    "stream_id",
    "branch_id",
    "observed_pid",
    "process_start_token",
    "ready_timestamp_ns",
    "analytics_queue_depths_json",
    "source_cycle_first",
    "admission_seq_first",
    "telemetry_sink_id",
    "telemetry_sink_preexisting_entry_count",
    "warmup_included_in_measurement",
    "admission_stopped_before_drain",
    "terminal_state",
    "reset_provenance",
    "telemetry_source",
]
RESOURCE_EVENT_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "timestamp_ms",
    "cpu_time_ms",
    "gpu_time_ms",
    "h2d_bytes",
    "d2h_bytes",
    "nvdec_util_percent",
    "vram_mb",
}
POLICY_DECISION_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "queue_depth",
    "estimated_cost_ms",
    "deadline_ms",
    "update_seq",
    "decision_seq",
    "decision_timestamp_ms",
    "terminal_timestamp_ms",
    "update_timestamp_ms",
    "first_consumer_decision_seq",
}
POLICY_FEEDBACK_NUMERIC_COLUMNS = {
    "schema_version",
    "feedback_seq",
    "feedback_timestamp_ms",
    "terminal_timestamp_ms",
    "source_parameter_snapshot_seq",
    "parameter_lag",
    "events_since_update",
    "variation_before",
    "variation_after",
    "variation_budget",
    "update_seq",
    "first_consumer_decision_seq",
}
DROP_COUNTER_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "dropped_frames",
    "late_frames",
    "total_frames",
    "deadline_ms",
    "drop_rate_percent",
    "late_rate_percent",
}
INGRESS_LEDGER_NUMERIC_COLUMNS = {
    "schema_version",
    "admission_seq",
    "source_cycle",
    "access_unit_pts_ns",
    "payload_size_bytes",
    "schedule_offset_ns",
    "stream_id",
    "frame_id",
    "ingress_timestamp_ms",
    "window_start_timestamp_ms",
    "window_end_timestamp_ms",
    "terminal_timestamp_ms",
    "drain_end_timestamp_ms",
}
BRANCH_TERMINAL_NUMERIC_COLUMNS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "terminal_timestamp_ms",
    "objects",
}
STAGE_CONTRACT_NUMERIC_COLUMNS = {
    "schema_version",
    "semantic_contract_version",
}
RESET_EVIDENCE_NUMERIC_COLUMNS = {
    "schema_version",
    "reset_contract_version",
    "stream_id",
    "observed_pid",
    "ready_timestamp_ns",
    "source_cycle_first",
    "admission_seq_first",
    "telemetry_sink_preexisting_entry_count",
}


class ContractError(RuntimeError):
    pass


PRIMARY_BASELINE_SCENARIO = "checkpoint_independent_processes_baseline"
PRIMARY_SHARED_SCENARIO = "checkpoint_video_dag_shared"
PRIMARY_ARCHITECTURE_SYSTEM = "gstreamer_custom"
PRIMARY_ARCHITECTURE_ESTIMANDS = {
    "delta_reuse_obs_c_obs_in",
    "decode_preprocess_event_factor_difference",
}
PRIMARY_ARCHITECTURE_GATES = {
    "topology_trace_complete",
    "ingress_ledger_complete",
    "branch_terminal_trace_complete",
    "stage_semantic_contract_complete",
    "decoder_placement_verified",
    "resource_attribution_complete",
    "measurement_signature_match",
    "paired_input_schedule_identity",
    "reset_state_verified",
    "slo_drop_balance",
}
PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT = {
    "contract_version": 1,
    "codec": "h264",
    "required_resource": "nvdec",
    "allowed_factories": ["nvh264dec", "nvv4l2decoder"],
    "factory_identity_source": (
        "stage_contracts.decode.implementation_config_json.decoder_factory"
    ),
    "software_fallback": "prohibited",
    "pair_rule": "exact_factory_match_across_baseline_and_shared",
    "evidence_limit": "factory_selection_does_not_measure_nvdec_busy_time",
}
PRIMARY_ANALYTICS_QUEUE_CONTRACT = {
    "contract_version": 1,
    "scope": "per_branch_waiting_queue_before_verified_detector",
    "max_buffers": 1,
    "capacity_semantics": "waiting_buffers_excluding_inflight_detector_buffer",
    "overflow_policy": "drop_newest",
    "terminal_reason": "native_pre_detector_queue_full_drop_newest",
    "non_overflow_terminal_policy": "flush_failure_or_missing_output_not_drop",
    "selection_basis": "minimal_positive_capacity_to_bound_backlog_before_results",
    "posthoc_retuning": "prohibited_for_primary_cell",
}
PRIMARY_ARCHITECTURE_RESET_CONTRACT = {
    "evidence_contract_version": RESET_EVIDENCE_CONTRACT_VERSION,
    "before_each_arm": "restart_all_source_and_worker_processes",
    "source_replay_origin": "cycle_0_admission_seq_1",
    "analytics_queues": "empty",
    "telemetry_sink": "new_run_directory",
    "warmup_included_in_measurement": False,
    "admission_after_measurement": "stopped_before_drain",
    "drain_terminal_rule": "no_censored_frames",
}
PRIMARY_ARCHITECTURE_PAIRING_KEYS = [
    "repeat",
    "seed",
    "run_seed",
    "input_schedule_sha256",
    "input_frame_key_sequence_sha256",
    "measurement_window_duration_ms",
    "ingress_censoring_rule",
    "resource_attribution",
    "measurement_signature",
]
PRIMARY_ARCHITECTURE_ESTIMAND_CONTRACT = {
    "delta_reuse_obs_c_obs_in": {
        "per_pair_definition": "baseline_minus_shared_over_positive_baseline_c_obs_in",
        "primary_summary": "median",
        "favorable_direction": "positive",
    },
    "decode_preprocess_event_factor_difference": {
        "per_stage_definition": "baseline_minus_shared_completed_cohort_event_factor",
        "stages": ["decode", "preprocess"],
        "denominator": "completed_frames_same_ingress_cohort",
        "primary_summary": "median",
        "favorable_direction": "positive",
        "stage_rule": "both_stages_required",
    },
}
PRIMARY_ARCHITECTURE_QUALITY_GUARDRAIL_ESTIMANDS = {
    "shared_minus_baseline_vmax_completed_slo_violation_rate_percentage_points": {
        "primary_summary": "median",
        "favorable_direction": "nonpositive",
    },
    "shared_minus_baseline_drop_max_ingress_rate_percentage_points": {
        "primary_summary": "median",
        "favorable_direction": "nonpositive",
    },
}
PRIMARY_ARCHITECTURE_GUARDRAILS = {
    "identical_ingress_input_frame_keys": True,
    "identical_measurement_signature": True,
    "identical_resource_attribution": True,
    "positive_baseline_c_obs_in": True,
    "censored_rate_percent_each_arm": 0.0,
    "require_positive_ingress_frames_per_stream": True,
    "require_positive_completed_frames_per_stream": True,
}
PRIMARY_ARCHITECTURE_INTERVAL = {
    "method": "paired_percentile_bootstrap",
    "statistic": "median",
    "confidence_level": 0.95,
    "resamples": 10000,
    "seed": 20260323,
    "multiplicity_rule": "intersection_union_all_coprimary_bounds_no_compensation",
    "claim_rule": (
        "all_coprimary_lower_bounds_above_zero_and_quality_upper_bounds_at_or_below_zero_and_all_gates_pass"
    ),
}
PRIMARY_ARCHITECTURE_SECONDARY_ESTIMANDS = {
    "c_obs_comp",
    "p50_p95_p99",
    "per_stream_slo_violation_rate",
    "per_stream_drop_rate",
    "cpu_gpu_nvdec_time",
    "native_h2d_d2h_transfer",
}
PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS = {
    "frames.csv",
    "frame_events.csv",
    "resource_events.csv",
    "policy_decisions.csv",
    "drop_counters.csv",
    "topology_events.csv",
    "ingress_ledger.csv",
    "branch_terminals.csv",
    "stage_contracts.csv",
    "reset_evidence.csv",
}
PUBLICATION_EVIDENCE_BUNDLE_SCOPE = "primary_architecture_raw_evidence_v1"
FULL_RESOURCE_PUBLICATION_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"
FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES = PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS | {
    "resource_intervals.csv",
    "hardware_resource_samples.csv",
    "fanout_work_counters.csv",
}
PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE = (
    "primary_policy_frozen_raw_evidence_v1"
)
PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE = (
    "primary_policy_online_raw_evidence_v1"
)
PRIMARY_POLICY_ARTIFACT_SHA256 = "0a961ae5e9e500dc3f07b386743b1a17c1991398018a44c5756d0f3a3b6045b5"
PRIMARY_POLICY_PASSPORT = {
    "artifact_schema_version": 2,
    "resource_scope": ["cpu", "gpu"],
    "initial_weights": {"cpu": 1.322315, "gpu": 0.677685},
    "weight_lower_bound": 0.5,
    "weight_upper_bound": 1.5,
    "projection_rule": "euclidean_box_mean_one_v1",
    "feedback_lag_limit": 8,
    "feedback_cooldown_events": 2,
    "variation_budget": 0.25,
    "feedback_update_rule": "simplified_gpu_queue_terminal_signal_v1",
    "feedback_penalty_step": 0.002,
    "feedback_reward_step": 0.0002,
    "heavy_object_threshold": 32,
    "heavy_gpu_bonus": 1.968103,
    "score_epsilon": 1.0e-9,
    "tie_break_rule": "score_then_queue_depth_then_stage_preference",
}
PRIMARY_POLICY_SECONDARY_ESTIMANDS = {
    "p95_max",
    "scheduler_call_time_ms",
    "applied_update_count",
    "cpu_gpu_nvdec_time",
    "native_h2d_d2h_transfer",
}
PRIMARY_POLICY_BOTH_ARM_GATES = {
    "architecture_scenario_accepted",
    "dataset_consuming_policy_path",
    "ingress_ledger_complete",
    "slo_drop_balance",
    "policy_trace_complete",
    "policy_causal_trace_complete",
}
PRIMARY_POLICY_ONLINE_ARM_GATES = {"policy_online_trace_complete"}
PRIMARY_POLICY_PAIR_GATES = {
    "policy_implementation_equivalence",
    "paired_ingress_terminal_identity",
    "reset_state_verified",
}
PRIMARY_ARCHITECTURE_PAIR_METADATA_CONTRACT_VERSION = 1
FORMAL_AW_HEFT_REQUIRED_RESOURCE_SCOPE = {"cpu", "gpu", "nvdec"}
FORMAL_AW_HEFT_REQUIRED_PASSPORT_FIELDS = {
    "rank_u_semantics",
    "ready_order_semantics",
    "transfer_cost_semantics",
    "memory_cost_semantics",
    "deadline_risk_semantics",
    "stability_window_semantics",
}
PRIMARY_POLICY_PAIR_METADATA_CONTRACT_VERSION = 1
PRIMARY_PROXY_V4_RUNTIME_IMPLEMENTATION = {
    "implementation_id": "custom_cpp_cuda_qt_internal_signal_proxy_v4",
    "system": "custom_cpp_cuda_qt",
    "source_path": "deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu",
    "supported_policies": ["ql_heft_frozen", "ql_heft_online"],
    "policy_version_prefix": "simplified-cpu-gpu-weighted-proxy-v4",
    "dataset_consuming": False,
    "benchmark_eligible": False,
    "workload_provenance": "internal_signal",
}
PRIMARY_POLICY_SYSTEM_SOURCE_PATHS = {
    "gstreamer_custom": "deploy/gstreamer_adaptivescheduler/gstadaptivescheduler.c",
    "custom_cpp_cuda_qt": "deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu",
}
PRIMARY_PROXY_V4_SOURCE_MARKERS = {
    "ql_heft_frozen",
    "ql_heft_online",
    "simplified-cpu-gpu-weighted-proxy-v4",
    "policy_decisions.csv",
    "policy_feedback.csv",
}
FORMAL_AW_HEFT_REFERENCE_SOURCE_MARKERS = {
    "REFERENCE_IMPLEMENTATION_ID",
    "compute_upward_ranks",
    "select_ready_task",
    "evaluate_decision",
    "project_box_mean_one",
    "evaluate_feedback",
    "formal_graph_profile_sha256",
    "replay_formal_aw_heft_trace",
    "updates_disabled_by_policy_mode",
}
RESOURCE_INTERVAL_EXTENSION_SOURCE_MARKERS = {
    "RESOURCE_INTERVAL_CONTRACT_VERSION",
    "RESOURCE_INTERVAL_COLUMNS",
    "validate_resource_intervals",
    "summarize_resource_interval_extension",
    "native_cuda_event_interval_v1",
    "native_decoder_submit_complete_interval_v1",
    "native_gstreamer_pad_probe_interval_v1",
    "RESOURCE_INTERVAL_DURATION_SEMANTICS",
    "RESOURCE_INTERVAL_ADDITIVE_COMPONENTS",
    "decoder_submit_to_output_elapsed_nonadditive_diagnostic",
    "queue_sink_to_src_elapsed_nonadditive_diagnostic",
    "publication_bundle_bound",
    "evidence_accepted",
}
RESOURCE_INTERVAL_FANOUT_EMITTER_MARKERS = {
    "CheckpointResourceIntervalEmitter",
    "resource_intervals.runtime.csv",
    "emit_fanout",
    "native_gstreamer_pad_probe_interval_v1",
    "gstreamer:tee-queue",
    "per_trace_interval",
    "telemetry_source",
}
RESOURCE_INTERVAL_FANOUT_BINDING_MARKERS = {
    "checkpoint-fanout-start",
    "checkpoint-fanout",
    "checkpoint_fanout_starts_by_branch",
    "FanoutIntervalStart",
    "checkpoint_resource_interval_emitter_",
    'branch,\n                "sink"',
}


def validate_primary_architecture_contrast(config: dict[str, Any]) -> dict[str, Any]:
    benchmark = config.get("benchmark") or {}
    primary = benchmark.get("primary_architecture_contrast")
    if not isinstance(primary, dict):
        raise ContractError("benchmark.primary_architecture_contrast must be declared")

    if int(primary.get("preregistration_version", 0) or 0) != 4:
        raise ContractError("primary architecture contrast requires preregistration_version: 4")
    if str(primary.get("status", "")) != "preregistered_blocked_execution":
        raise ContractError(
            "primary architecture contrast must remain preregistered_blocked_execution until accepted runs exist"
        )
    if str(primary.get("selection_basis", "")) != (
        "preexisting_defaults_and_contract_capabilities_before_results"
    ):
        raise ContractError("primary architecture contrast must record its result-independent selection basis")

    baseline_name = str(primary.get("baseline_scenario", ""))
    shared_name = str(primary.get("shared_scenario", ""))
    if (baseline_name, shared_name) != (PRIMARY_BASELINE_SCENARIO, PRIMARY_SHARED_SCENARIO):
        raise ContractError("primary architecture contrast must use the dissertation checkpoint scenario pair")
    scenarios = config.get("scenarios") or {}
    if baseline_name not in scenarios or shared_name not in scenarios:
        raise ContractError("primary architecture contrast references an unknown checkpoint scenario")

    system = str(primary.get("system", ""))
    if system != PRIMARY_ARCHITECTURE_SYSTEM:
        raise ContractError(
            f"primary architecture contrast must use system '{PRIMARY_ARCHITECTURE_SYSTEM}'"
        )
    system_config = (config.get("systems") or {}).get(system)
    if not isinstance(system_config, dict):
        raise ContractError("primary architecture contrast references an unknown system")
    if str(system_config.get("benchmark_status", "supported")) != "supported":
        raise ContractError("primary architecture contrast system must be benchmark-eligible")

    route = str(primary.get("routing_mode", ""))
    route_scope = str(primary.get("routing_scope", ""))
    if route != "all_branches_per_stream" or route_scope != "topology_only_stress":
        raise ContractError(
            "primary architecture contrast requires all_branches_per_stream as a topology_only_stress profile"
        )
    branches = [str(value) for value in primary.get("required_branches", [])]
    if not branches or len(branches) != len(set(branches)):
        raise ContractError("primary architecture contrast must declare unique required_branches")

    expected_streams = int(primary.get("streams", 0) or 0)
    for scenario_name in (baseline_name, shared_name):
        scenario = scenarios[scenario_name] or {}
        topology = scenario.get("topology") or {}
        workload = scenario.get("workload") or {}
        if str(topology.get("routing_mode", "")) != route or str(workload.get("routing_mode", "")) != route:
            raise ContractError(f"primary route does not match scenario '{scenario_name}'")
        if str(workload.get("routing_scope", "")) != route_scope:
            raise ContractError(f"primary routing scope does not match scenario '{scenario_name}'")
        if [str(value) for value in topology.get("required_branches", [])] != branches:
            raise ContractError(f"primary branches do not match scenario '{scenario_name}'")
        if int(workload.get("streams", 0) or 0) != expected_streams:
            raise ContractError(f"primary stream count does not match scenario '{scenario_name}'")

    policy = str(primary.get("policy", ""))
    if policy not in {str(value) for value in benchmark.get("scheduler_policies", [])}:
        raise ContractError(f"primary policy '{policy}' is not a configured scheduler policy")
    dataset = str(primary.get("dataset", ""))
    if dataset not in {str(value) for value in benchmark.get("benchmark_datasets", [])}:
        raise ContractError(f"primary dataset '{dataset}' is not a configured benchmark dataset")
    if dataset not in {str(value) for value in benchmark.get("report_datasets", [])}:
        raise ContractError(f"primary dataset '{dataset}' is not a configured report dataset")
    codec = str(primary.get("codec", ""))
    if codec != "h264" or dataset != "kpp_real_h264":
        raise ContractError("primary architecture contrast must bind codec h264 to dataset kpp_real_h264")

    deadline_ms = float(primary.get("deadline_ms", 0.0) or 0.0)
    if deadline_ms not in {float(value) for value in benchmark.get("report_deadline_ms", [])}:
        raise ContractError("primary deadline_ms is absent from benchmark.report_deadline_ms")
    target_deadline_ms = float((config.get("hardware_target") or {}).get("deadline_s", 0.0)) * 1000.0
    if abs(deadline_ms - target_deadline_ms) > 1e-9:
        raise ContractError("primary deadline_ms must match hardware_target.deadline_s")

    protocol = config.get("protocol") or {}
    protocol_fields = {
        "repeats": "repeats",
        "warmup_s": "warmup_s",
        "measurement_s": "measurement_s",
    }
    for primary_field, protocol_field in protocol_fields.items():
        if int(primary.get(primary_field, -1)) != int(protocol.get(protocol_field, -2)):
            raise ContractError(f"primary {primary_field} must match protocol.{protocol_field}")
    if int(primary.get("seed", -1)) != int(benchmark.get("default_seed", -2)):
        raise ContractError("primary seed must match benchmark.default_seed")
    if int(primary.get("effective_batch_size", 0) or 0) != 1:
        raise ContractError("primary effective_batch_size must remain 1 for event-factor interpretation")
    if primary.get("analytics_queue") != PRIMARY_ANALYTICS_QUEUE_CONTRACT:
        raise ContractError("primary analytics_queue contract has drifted")
    if primary.get("decoder_placement") != PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT:
        raise ContractError("primary decoder_placement contract has drifted")

    arm_order = primary.get("arm_order") or {}
    expected_first_arms = [
        baseline_name if index % 2 == 0 else shared_name for index in range(int(primary["repeats"]))
    ]
    if str(arm_order.get("strategy", "")) != "counterbalanced_alternating" or arm_order.get(
        "first_arm_by_pair"
    ) != expected_first_arms:
        raise ContractError("primary architecture contrast must use the frozen counterbalanced arm order")
    if primary.get("reset_contract") != PRIMARY_ARCHITECTURE_RESET_CONTRACT:
        raise ContractError("primary architecture contrast reset_contract has drifted")
    if primary.get("pairing_keys") != PRIMARY_ARCHITECTURE_PAIRING_KEYS:
        raise ContractError("primary architecture contrast pairing_keys have drifted")

    estimands = {str(value) for value in primary.get("primary_estimands", [])}
    if estimands != PRIMARY_ARCHITECTURE_ESTIMANDS:
        raise ContractError("primary architecture estimands do not match the preregistered pair")
    if primary.get("estimand_contract") != PRIMARY_ARCHITECTURE_ESTIMAND_CONTRACT:
        raise ContractError("primary architecture estimand_contract has drifted")
    if primary.get("quality_guardrail_estimands") != PRIMARY_ARCHITECTURE_QUALITY_GUARDRAIL_ESTIMANDS:
        raise ContractError("primary architecture quality_guardrail_estimands have drifted")
    if primary.get("guardrails") != PRIMARY_ARCHITECTURE_GUARDRAILS:
        raise ContractError("primary architecture guardrails have drifted")
    if primary.get("interval") != PRIMARY_ARCHITECTURE_INTERVAL:
        raise ContractError("primary architecture interval and claim rule have drifted")
    secondary = {str(value) for value in primary.get("secondary_estimands", [])}
    if secondary != PRIMARY_ARCHITECTURE_SECONDARY_ESTIMANDS:
        raise ContractError("primary architecture secondary_estimands have drifted")
    sidecars = {str(value) for value in primary.get("required_sidecars", [])}
    if sidecars != PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS:
        raise ContractError("primary architecture required_sidecars have drifted")
    gates = {str(value) for value in primary.get("acceptance_gates", [])}
    if gates != PRIMARY_ARCHITECTURE_GATES:
        raise ContractError("primary architecture acceptance_gates do not match the required set")
    return primary


def validate_primary_policy_ablation(config: dict[str, Any]) -> dict[str, Any]:
    benchmark = config.get("benchmark") or {}
    ablation = benchmark.get("primary_policy_ablation")
    if not isinstance(ablation, dict):
        raise ContractError("benchmark.primary_policy_ablation must be declared")

    architecture = validate_primary_architecture_contrast(config)
    if int(ablation.get("preregistration_version", 0) or 0) != 4:
        raise ContractError("primary policy ablation requires preregistration_version: 4")
    if str(ablation.get("status", "")) != "preregistered_blocked_execution":
        raise ContractError(
            "primary policy ablation must remain preregistered_blocked_execution until accepted paired runs exist"
        )
    if str(ablation.get("selection_basis", "")) != "reuse_preregistered_shared_cell_before_policy_results":
        raise ContractError("primary policy ablation must record its result-independent selection basis")
    if str(ablation.get("architecture_scenario", "")) != str(architecture["shared_scenario"]):
        raise ContractError("primary policy ablation must use the preregistered shared Video-DAG scenario")
    if str(ablation.get("architecture_prerequisite", "")) != "primary_architecture_contrast_accepted":
        raise ContractError("primary policy ablation must remain conditional on architecture acceptance")
    if str(ablation.get("interpretation_scope", "")) != (
        "formal_aw_heft_claim_blocked_until_implementation_equivalence"
    ):
        raise ContractError("primary policy ablation must preserve the formal-AW-HEFT equivalence blocker")

    frozen_policy = str(ablation.get("frozen_policy", ""))
    online_policy = str(ablation.get("online_policy", ""))
    if (frozen_policy, online_policy) != ("ql_heft_frozen", "ql_heft_online"):
        raise ContractError("primary policy ablation must compare the frozen and online technical policy IDs")
    active_policies = {str(value) for value in benchmark.get("scheduler_policies", [])}
    if frozen_policy in active_policies or online_policy in active_policies:
        raise ContractError("blocked policy-ablation arms must not enter the active benchmark matrix")
    if str(ablation.get("policy_version_prefix", "")) != "simplified-cpu-gpu-weighted-proxy-v4":
        raise ContractError("primary policy ablation must freeze the v4 technical policy version")
    if str(ablation.get("feedback_lag_semantics", "")) != (
        "max_staleness_from_oldest_applied_snapshot"
    ):
        raise ContractError("primary policy ablation must freeze conservative feedback lag semantics")

    artifact = str(ablation.get("policy_artifact", ""))
    if artifact != str(benchmark.get("ql_heft_policy_artifact", "")) or artifact != (
        "policies/ql_heft_frozen.policy"
    ):
        raise ContractError("primary policy ablation must bind the configured frozen policy artifact")
    digest = str(ablation.get("policy_artifact_sha256", ""))
    if digest != PRIMARY_POLICY_ARTIFACT_SHA256:
        raise ContractError("primary policy ablation policy artifact SHA-256 has drifted")
    artifact_path = Path(__file__).resolve().parents[1] / artifact
    if not artifact_path.is_file():
        raise ContractError(f"primary policy ablation artifact is missing: {artifact_path}")
    actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual_digest != digest:
        raise ContractError("primary policy ablation artifact bytes do not match the preregistered SHA-256")

    shared_coordinates = {
        "system": architecture["system"],
        "dataset": architecture["dataset"],
        "codec": architecture["codec"],
        "deadline_ms": architecture["deadline_ms"],
        "streams": architecture["streams"],
        "routing_mode": architecture["routing_mode"],
        "routing_scope": architecture["routing_scope"],
        "required_branches": architecture["required_branches"],
        "effective_batch_size": architecture["effective_batch_size"],
        "repeats": architecture["repeats"],
        "seed": architecture["seed"],
        "warmup_s": architecture["warmup_s"],
        "measurement_s": architecture["measurement_s"],
        "analytics_queue": architecture["analytics_queue"],
    }
    for field, expected in shared_coordinates.items():
        if ablation.get(field) != expected:
            raise ContractError(f"primary policy ablation {field} differs from the preregistered shared cell")

    passport = ablation.get("policy_passport")
    if passport != PRIMARY_POLICY_PASSPORT:
        raise ContractError("primary policy ablation policy_passport differs from the frozen schema-v2 artifact")
    weights = passport["initial_weights"]
    if not math.isclose(sum(float(value) for value in weights.values()), 2.0, abs_tol=1e-9):
        raise ContractError("primary policy ablation initial weights must have arithmetic mean one")

    arm_order = ablation.get("arm_order") or {}
    expected_first_arms = [frozen_policy if index % 2 == 0 else online_policy for index in range(10)]
    if str(arm_order.get("strategy", "")) != "counterbalanced_alternating" or arm_order.get(
        "first_arm_by_pair"
    ) != expected_first_arms:
        raise ContractError("primary policy ablation must use the frozen counterbalanced arm order")
    expected_reset = {
        "architecture_reset_evidence_contract_version": RESET_EVIDENCE_CONTRACT_VERSION,
        "warmup_feedback_updates": "disabled",
        "before_each_measurement": "reload_artifact_and_clear_feedback_state",
        "feedback_seq": 0,
        "update_seq": 0,
        "accumulated_variation": 0.0,
        "pending_feedback": "empty",
        "terminal_history": "empty",
    }
    if ablation.get("reset_contract") != expected_reset:
        raise ContractError("primary policy ablation reset_contract has drifted")
    if ablation.get("pairing_keys") != [
        "repeat",
        "seed",
        "run_seed",
        "input_schedule_sha256",
        "input_frame_key_sequence_sha256",
    ]:
        raise ContractError("primary policy ablation pairing keys have drifted")

    expected_estimand = {
        "name": "delta_vmax_policy_online_minus_frozen",
        "definition": "vmax_completed_slo_violation_rate_online_minus_frozen",
        "denominator": "completed_frames_per_stream",
        "favorable_direction": "negative",
    }
    if ablation.get("primary_estimand") != expected_estimand:
        raise ContractError("primary policy ablation primary_estimand has drifted")
    expected_guardrails = {
        "identical_ingress_input_frame_keys": True,
        "identical_terminal_status_by_input_frame_key": True,
        "censored_rate_percent_each_arm": 0.0,
        "max_online_minus_frozen_drop_rate_percent": 0.0,
        "require_positive_completed_frames_per_stream": True,
    }
    if ablation.get("guardrails") != expected_guardrails:
        raise ContractError("primary policy ablation guardrails must prevent cohort and terminal-status drift")
    expected_interval = {
        "method": "paired_percentile_bootstrap",
        "confidence_level": 0.95,
        "resamples": 10000,
        "seed": 20260323,
        "claim_rule": "upper_bound_below_zero_and_all_guardrails_pass",
    }
    if ablation.get("interval") != expected_interval:
        raise ContractError("primary policy ablation interval and claim rule have drifted")
    if {str(value) for value in ablation.get("secondary_estimands", [])} != PRIMARY_POLICY_SECONDARY_ESTIMANDS:
        raise ContractError("primary policy ablation secondary estimands have drifted")

    expected_sidecars = {
        "both_arms": {
            "frames.csv",
            "frame_events.csv",
            "ingress_ledger.csv",
            "policy_decisions.csv",
            "drop_counters.csv",
            "reset_evidence.csv",
        },
        "online_arm": {"policy_feedback.csv"},
    }
    sidecars = ablation.get("required_sidecars") or {}
    if not isinstance(sidecars, dict) or set(sidecars) != set(expected_sidecars):
        raise ContractError("primary policy ablation required sidecars have drifted")
    for key, expected in expected_sidecars.items():
        values = sidecars.get(key)
        if not isinstance(values, list) or {str(value) for value in values} != expected:
            raise ContractError("primary policy ablation required sidecars have drifted")
    expected_gates = {
        "both_arms": PRIMARY_POLICY_BOTH_ARM_GATES,
        "online_arm": PRIMARY_POLICY_ONLINE_ARM_GATES,
        "pair": PRIMARY_POLICY_PAIR_GATES,
    }
    gates = ablation.get("acceptance_gates") or {}
    if not isinstance(gates, dict) or set(gates) != set(expected_gates):
        raise ContractError("primary policy ablation acceptance gates have drifted")
    for key, expected in expected_gates.items():
        values = gates.get(key)
        if not isinstance(values, list) or {str(value) for value in values} != expected:
            raise ContractError("primary policy ablation acceptance gates have drifted")
    return ablation


def _policy_source_marker_assessment(source_path: str) -> dict[str, Any]:
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / source_path
    if not path.is_file():
        return {
            "path": source_path,
            "exists": False,
            "markers_verified": False,
            "missing_markers": sorted(PRIMARY_PROXY_V4_SOURCE_MARKERS),
        }
    source = path.read_text(encoding="utf-8")
    missing_markers = sorted(
        marker for marker in PRIMARY_PROXY_V4_SOURCE_MARKERS if marker not in source
    )
    return {
        "path": source_path,
        "exists": True,
        "markers_verified": not missing_markers,
        "missing_markers": missing_markers,
    }


def assess_primary_policy_runtime_compatibility(config: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when the frozen cell does not name the runtime that emits its trace."""

    ablation = validate_primary_policy_ablation(config)
    configured_system = str(ablation["system"])
    configured_source_path = PRIMARY_POLICY_SYSTEM_SOURCE_PATHS.get(configured_system, "")
    configured_source = _policy_source_marker_assessment(configured_source_path)
    implementation = dict(PRIMARY_PROXY_V4_RUNTIME_IMPLEMENTATION)
    registered_source = _policy_source_marker_assessment(
        str(implementation["source_path"])
    )
    systems = config.get("systems") or {}
    registered_system_config = systems.get(str(implementation["system"])) or {}
    registered_system_benchmark_eligible = (
        str(registered_system_config.get("benchmark_status", "supported")) == "supported"
    )

    blockers: list[str] = []
    if not configured_source["exists"]:
        blockers.append("configured_system_policy_source_missing")
    elif not configured_source["markers_verified"]:
        blockers.append("configured_system_missing_proxy_v4_emitter_contract")
    if configured_system != str(implementation["system"]):
        blockers.append("registered_proxy_v4_emitter_system_mismatch")
    if not registered_source["exists"] or not registered_source["markers_verified"]:
        blockers.append("registered_proxy_v4_emitter_source_contract_missing")
    if not bool(implementation["dataset_consuming"]):
        blockers.append("registered_proxy_v4_emitter_not_dataset_consuming")
    if (
        not bool(implementation["benchmark_eligible"])
        or not registered_system_benchmark_eligible
    ):
        blockers.append("registered_proxy_v4_emitter_not_benchmark_eligible")
    if [str(value) for value in implementation["supported_policies"]] != [
        str(ablation["frozen_policy"]),
        str(ablation["online_policy"]),
    ]:
        blockers.append("registered_proxy_v4_emitter_policy_ids_mismatch")
    if str(implementation["policy_version_prefix"]) != str(
        ablation["policy_version_prefix"]
    ):
        blockers.append("registered_proxy_v4_emitter_policy_version_mismatch")

    blockers = list(dict.fromkeys(blockers))
    compatible = not blockers
    return {
        "assessment_schema_version": 1,
        "status": (
            "ready_dataset_consuming_proxy_v4_runtime"
            if compatible
            else "blocked_runtime_policy_implementation_mismatch"
        ),
        "passed": compatible,
        "configured_cell": {
            "system": configured_system,
            "frozen_policy": str(ablation["frozen_policy"]),
            "online_policy": str(ablation["online_policy"]),
            "policy_version_prefix": str(ablation["policy_version_prefix"]),
            "source_assessment": configured_source,
        },
        "registered_proxy_v4_implementation": {
            **implementation,
            "source_assessment": registered_source,
            "system_benchmark_eligible_in_config": registered_system_benchmark_eligible,
        },
        "blockers": blockers,
        "interpretation": (
            "The frozen v4 cell names gstreamer_custom, but its registered source "
            "does not emit the ql_heft v4 decision/feedback contract. The only "
            "registered emitter is the diagnostic internal-signal "
            "custom_cpp_cuda_qt runtime. Pair execution must remain disabled until "
            "a dataset-consuming benchmark implementation is versioned and bound "
            "to the cell before results."
        ),
    }


def assess_formal_aw_heft_reference(config: dict[str, Any]) -> dict[str, Any]:
    """Verify the executable reference bytes without treating them as a runtime gate."""

    benchmark = config.get("benchmark") or {}
    reference = benchmark.get("formal_aw_heft_reference") or {}
    expected_declaration = {
        "reference_version": 1,
        "status": "reference_only_not_runtime_bound",
        "artifact": "policies/aw_heft_reference_v1.json",
        "implementation_module": "scripts/formal_aw_heft_reference.py",
        "trace_contract_version": 1,
        "replay_entrypoint": "formal_aw_heft_reference.replay_formal_aw_heft_trace",
        "replay_numeric_tolerance": 1.0e-9,
        "replay_status": "implemented_not_executed_on_accepted_trace",
        "runtime_binding": None,
        "benchmark_eligible": False,
    }
    blockers: list[str] = []
    for field, expected in expected_declaration.items():
        if reference.get(field) != expected:
            blockers.append(f"reference_declaration_drift:{field}")

    project_root = Path(__file__).resolve().parents[1]
    artifact_path = project_root / str(reference.get("artifact", ""))
    implementation_path = project_root / str(reference.get("implementation_module", ""))
    expected_artifact_sha = str(reference.get("artifact_sha256", ""))
    expected_implementation_sha = str(reference.get("implementation_sha256", ""))
    artifact_payload: dict[str, Any] | None = None

    if not artifact_path.is_file():
        blockers.append("reference_artifact_missing")
    else:
        actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_artifact_sha):
            blockers.append("reference_artifact_sha256_invalid")
        elif actual_sha != expected_artifact_sha:
            blockers.append("reference_artifact_sha256_mismatch")
        try:
            artifact_payload = validate_reference_artifact(artifact_path)
        except FormalAwHeftError:
            blockers.append("reference_artifact_contract_invalid")

    missing_source_markers = sorted(FORMAL_AW_HEFT_REFERENCE_SOURCE_MARKERS)
    if not implementation_path.is_file():
        blockers.append("reference_implementation_missing")
    else:
        actual_sha = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_implementation_sha):
            blockers.append("reference_implementation_sha256_invalid")
        elif actual_sha != expected_implementation_sha:
            blockers.append("reference_implementation_sha256_mismatch")
        source = implementation_path.read_text(encoding="utf-8")
        missing_source_markers = sorted(
            marker for marker in FORMAL_AW_HEFT_REFERENCE_SOURCE_MARKERS if marker not in source
        )
        if missing_source_markers:
            blockers.append("reference_implementation_contract_missing")

    blockers = list(dict.fromkeys(blockers))
    verified = not blockers
    return {
        "assessment_schema_version": 2,
        "status": (
            "ready_executable_reference_and_replay_not_runtime_bound"
            if verified
            else "blocked_formal_reference_contract_invalid"
        ),
        "passed": False,
        "reference_contract_verified": verified,
        "runtime_bound": False,
        "benchmark_eligible": False,
        "formal_reference_replay_implemented": verified,
        "formal_reference_replay_entrypoint": str(reference.get("replay_entrypoint", "")),
        "formal_trace_contract_version": reference.get("trace_contract_version"),
        "formal_replay_numeric_tolerance": reference.get("replay_numeric_tolerance"),
        "accepted_formal_trace_replay_performed": False,
        "runtime_reference_replay_performed": False,
        "artifact": {
            "path": str(reference.get("artifact", "")),
            "sha256": expected_artifact_sha,
            "implementation_id": str((artifact_payload or {}).get("implementation_id", "")),
        },
        "implementation": {
            "path": str(reference.get("implementation_module", "")),
            "sha256": expected_implementation_sha,
            "missing_markers": missing_source_markers,
        },
        "blockers": blockers,
        "remaining_gates": [
            "formal_h2_cell_not_preregistered",
            "dataset_consuming_runtime_not_bound",
            "target_runtime_not_executed",
            "accepted_formal_trace_not_available",
            "accepted_formal_reference_replay_not_performed",
        ],
        "interpretation": (
            "The separately versioned CPU/GPU/NVDEC reference implements the formal "
            "decision and bounded-feedback equations plus an input-only deterministic "
            "trace replay. No accepted trace has been replayed. The reference remains "
            "unbound to a dataset-consuming runtime, is not benchmark-eligible, and does "
            "not establish formal implementation equivalence or a policy effect."
        ),
    }


def assess_resource_interval_extension(config: dict[str, Any]) -> dict[str, Any]:
    """Verify the non-publication interval validator without extending frozen evidence."""

    benchmark = config.get("benchmark") or {}
    extension = benchmark.get("resource_interval_extension") or {}
    expected_declaration = {
        "contract_version": 2,
        "status": "validator_and_fanout_source_ready_not_emitted_not_publication_bound",
        "validator": "scripts/resource_interval_contract.py",
        "fanout_emitter": "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
        "fanout_binding": "deploy/native_gst_probe/vast_native_gst_probe.cpp",
        "fanout_runtime_sidecar": "resource_intervals.runtime.csv",
        "fanout_runtime_status": "source_implemented_not_target_executed_not_accepted",
        "sidecar": "resource_intervals.csv",
        "components": ["transfer", "nvdec_submit_complete", "fanout"],
        "duration_provenance": {
            "transfer": "native_cuda_event_interval_v1",
            "nvdec_submit_complete": "native_decoder_submit_complete_interval_v1",
            "fanout": "native_gstreamer_pad_probe_interval_v1",
        },
        "duration_semantics": {
            "transfer": "device_event_elapsed_additive_resource_work",
            "nvdec_submit_complete": (
                "decoder_submit_to_output_elapsed_nonadditive_diagnostic"
            ),
            "fanout": "queue_sink_to_src_elapsed_nonadditive_diagnostic",
        },
        "additive_duration_components": ["transfer"],
        "nonadditive_elapsed_components": ["fanout", "nvdec_submit_complete"],
        "true_nvdec_busy_status": "not_measured",
        "fanout_resource_work_status": "not_measured",
        "counter_scope": "per_trace_interval",
        "current_publication_bundle_scope": PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
        "future_publication_scope_required": (
            "primary_architecture_full_resource_raw_evidence_v2"
        ),
        "publication_bundle_bound": False,
        "evidence_accepted": False,
    }
    blockers: list[str] = []
    for field, expected in expected_declaration.items():
        if extension.get(field) != expected:
            blockers.append(f"resource_interval_declaration_drift:{field}")

    if str(extension.get("sidecar", "")) in PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS:
        blockers.append("resource_interval_sidecar_unexpectedly_added_to_frozen_bundle_v1")
    if str(extension.get("fanout_runtime_sidecar", "")) in PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS:
        blockers.append("fanout_runtime_sidecar_unexpectedly_added_to_frozen_bundle_v1")

    project_root = Path(__file__).resolve().parents[1]
    validator_path = project_root / str(extension.get("validator", ""))
    expected_sha = str(extension.get("validator_sha256", ""))
    missing_source_markers = sorted(RESOURCE_INTERVAL_EXTENSION_SOURCE_MARKERS)
    if not validator_path.is_file():
        blockers.append("resource_interval_validator_missing")
    else:
        actual_sha = hashlib.sha256(validator_path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
            blockers.append("resource_interval_validator_sha256_invalid")
        elif actual_sha != expected_sha:
            blockers.append("resource_interval_validator_sha256_mismatch")
        source = validator_path.read_text(encoding="utf-8")
        missing_source_markers = sorted(
            marker
            for marker in RESOURCE_INTERVAL_EXTENSION_SOURCE_MARKERS
            if marker not in source
        )
        if missing_source_markers:
            blockers.append("resource_interval_validator_contract_missing")

    fanout_emitter_path = project_root / str(extension.get("fanout_emitter", ""))
    expected_fanout_emitter_sha = str(extension.get("fanout_emitter_sha256", ""))
    missing_fanout_emitter_markers = sorted(RESOURCE_INTERVAL_FANOUT_EMITTER_MARKERS)
    if not fanout_emitter_path.is_file():
        blockers.append("resource_interval_fanout_emitter_missing")
    else:
        actual_sha = hashlib.sha256(fanout_emitter_path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_fanout_emitter_sha):
            blockers.append("resource_interval_fanout_emitter_sha256_invalid")
        elif actual_sha != expected_fanout_emitter_sha:
            blockers.append("resource_interval_fanout_emitter_sha256_mismatch")
        source = fanout_emitter_path.read_text(encoding="utf-8")
        missing_fanout_emitter_markers = sorted(
            marker
            for marker in RESOURCE_INTERVAL_FANOUT_EMITTER_MARKERS
            if marker not in source
        )
        if missing_fanout_emitter_markers:
            blockers.append("resource_interval_fanout_emitter_contract_missing")

    fanout_binding_path = project_root / str(extension.get("fanout_binding", ""))
    expected_fanout_binding_sha = str(extension.get("fanout_binding_sha256", ""))
    missing_fanout_binding_markers = sorted(RESOURCE_INTERVAL_FANOUT_BINDING_MARKERS)
    if not fanout_binding_path.is_file():
        blockers.append("resource_interval_fanout_binding_missing")
    else:
        actual_sha = hashlib.sha256(fanout_binding_path.read_bytes()).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_fanout_binding_sha):
            blockers.append("resource_interval_fanout_binding_sha256_invalid")
        elif actual_sha != expected_fanout_binding_sha:
            blockers.append("resource_interval_fanout_binding_sha256_mismatch")
        source = fanout_binding_path.read_text(encoding="utf-8")
        missing_fanout_binding_markers = sorted(
            marker
            for marker in RESOURCE_INTERVAL_FANOUT_BINDING_MARKERS
            if marker not in source
        )
        if missing_fanout_binding_markers:
            blockers.append("resource_interval_fanout_binding_contract_missing")

    blockers = list(dict.fromkeys(blockers))
    validator_verified = not blockers
    fanout_emitter_source_verified = not any(
        blocker.startswith("resource_interval_fanout_")
        or blocker.startswith("resource_interval_declaration_drift:fanout_")
        for blocker in blockers
    )
    return {
        "assessment_schema_version": 1,
        "status": (
            "ready_validator_and_fanout_source_not_target_verified_not_publication_bound"
            if validator_verified
            else "blocked_resource_interval_contract_invalid"
        ),
        "passed": False,
        "validator_verified": validator_verified,
        "fanout_emitter_source_verified": fanout_emitter_source_verified,
        "native_sidecar_emitted": False,
        "validated_interval_packet_available": False,
        "coverage_complete": False,
        "publication_bundle_bound": False,
        "evidence_accepted": False,
        "current_publication_bundle_scope": str(
            extension.get("current_publication_bundle_scope", "")
        ),
        "future_publication_scope_required": str(
            extension.get("future_publication_scope_required", "")
        ),
        "validator": {
            "path": str(extension.get("validator", "")),
            "sha256": expected_sha,
            "missing_markers": missing_source_markers,
        },
        "fanout_emitter": {
            "path": str(extension.get("fanout_emitter", "")),
            "sha256": expected_fanout_emitter_sha,
            "missing_markers": missing_fanout_emitter_markers,
        },
        "fanout_binding": {
            "path": str(extension.get("fanout_binding", "")),
            "sha256": expected_fanout_binding_sha,
            "missing_markers": missing_fanout_binding_markers,
        },
        "blockers": blockers,
        "remaining_gates": [
            "native_cuda_transfer_interval_emitter_missing",
            "native_nvdec_submit_complete_interval_emitter_missing",
            "native_nvdec_busy_resource_counter_missing",
            "native_fanout_interval_emitter_not_target_executed_or_accepted",
            "native_fanout_resource_work_counter_missing",
            "full_resource_publication_scope_not_preregistered",
            "accepted_interval_sidecars_not_available",
        ],
        "interpretation": (
            "The standalone validator can reject malformed or proxy interval rows "
            "and summarize native transfer, decoder submit-to-output, and fanout linkage. "
            "Only CUDA-event transfer duration is declared additive resource work. Decoder "
            "submit-to-output and queue sink-to-src spans are non-additive diagnostics, not "
            "NVDEC busy time or fanout resource work. The source-bound fanout emitter pairs "
            "native GStreamer queue sink/src probes, but it has not "
            "run on the target stand and its runtime-only fragment is not accepted. It is not "
            "bound to measurement passport v4 or publication evidence bundle v1, "
            "so it cannot upgrade the primary claim from partial resource coverage."
        ),
    }


def primary_architecture_pair_metadata(
    config: dict[str, Any],
    *,
    repeat: int,
    scenario: str,
) -> dict[str, Any]:
    primary = validate_primary_architecture_contrast(config)
    repeats = int(primary["repeats"])
    if repeat < 1 or repeat > repeats:
        raise ContractError(
            f"primary architecture pair repeat must be between 1 and {repeats}"
        )
    baseline = str(primary["baseline_scenario"])
    shared = str(primary["shared_scenario"])
    if scenario not in {baseline, shared}:
        raise ContractError(
            "primary architecture pair metadata requires a baseline or shared arm"
        )
    first_arm = str(primary["arm_order"]["first_arm_by_pair"][repeat - 1])
    second_arm = shared if first_arm == baseline else baseline
    return {
        "contract_version": PRIMARY_ARCHITECTURE_PAIR_METADATA_CONTRACT_VERSION,
        "strategy": str(primary["arm_order"]["strategy"]),
        "repeat": repeat,
        "first_arm": first_arm,
        "arm_position": 1 if scenario == first_arm else 2,
        "second_arm": second_arm,
    }


def validate_primary_architecture_pair_metadata(
    config: dict[str, Any],
    *,
    repeat: int,
    scenario: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ContractError("primary architecture pair metadata must be a mapping")
    expected = primary_architecture_pair_metadata(
        config,
        repeat=repeat,
        scenario=scenario,
    )
    if metadata != expected:
        raise ContractError(
            "primary architecture pair metadata differs from the frozen arm order"
        )
    return dict(expected)


def validate_primary_architecture_pair_run_contract(
    config: dict[str, Any],
    *,
    system: str,
    scenario: str,
    policy: str,
    dataset: str,
    deadline_ms: float,
    streams: int,
    repeat: int,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    primary = validate_primary_architecture_contrast(config)
    coordinate_mismatches = []
    if system != str(primary["system"]):
        coordinate_mismatches.append("system")
    if scenario not in {
        str(primary["baseline_scenario"]),
        str(primary["shared_scenario"]),
    }:
        coordinate_mismatches.append("scenario")
    if policy != str(primary["policy"]):
        coordinate_mismatches.append("policy")
    if dataset != str(primary["dataset"]):
        coordinate_mismatches.append("dataset")
    if not math.isclose(
        float(deadline_ms),
        float(primary["deadline_ms"]),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        coordinate_mismatches.append("deadline_ms")
    if int(streams) != int(primary["streams"]):
        coordinate_mismatches.append("streams")
    if coordinate_mismatches:
        raise ContractError(
            "primary architecture run differs from the frozen cell: "
            + ", ".join(coordinate_mismatches)
        )
    return validate_primary_architecture_pair_metadata(
        config,
        repeat=repeat,
        scenario=scenario,
        metadata=metadata,
    )


def build_primary_architecture_runtime_plan(config: dict[str, Any]) -> dict[str, Any]:
    primary = validate_primary_architecture_contrast(config)
    scenarios = config.get("scenarios") or {}
    baseline = str(primary["baseline_scenario"])
    shared = str(primary["shared_scenario"])
    blockers = []
    for scenario_name in (baseline, shared):
        status = str((scenarios.get(scenario_name) or {}).get("benchmark_status", "supported"))
        if status != "supported":
            blockers.append(f"scenario:{scenario_name}:benchmark_status:{status}")

    runs: list[dict[str, Any]] = []
    for repeat in range(1, int(primary["repeats"]) + 1):
        first_arm = str(primary["arm_order"]["first_arm_by_pair"][repeat - 1])
        second_arm = shared if first_arm == baseline else baseline
        for scenario in (first_arm, second_arm):
            runs.append(
                {
                    "scenario": scenario,
                    "system": str(primary["system"]),
                    "policy": str(primary["policy"]),
                    "dataset": str(primary["dataset"]),
                    "deadline_ms": float(primary["deadline_ms"]),
                    "streams": int(primary["streams"]),
                    "warmup_s": int(primary["warmup_s"]),
                    "measurement_s": int(primary["measurement_s"]),
                    "seed": int(primary["seed"]),
                    "primary_architecture_pair": primary_architecture_pair_metadata(
                        config,
                        repeat=repeat,
                        scenario=scenario,
                    ),
                }
            )
    return {
        "plan_schema_version": 1,
        "status": (
            "ready_primary_architecture_pair_runtime_plan"
            if not blockers
            else "blocked_primary_architecture_topology_implementation"
        ),
        "runtime_execution_allowed": not blockers,
        "expected_pairs": int(primary["repeats"]),
        "expected_runs": int(primary["repeats"]) * 2,
        "blockers": blockers,
        "runs": runs,
        "interpretation": (
            "This is a non-measurement schedule and metadata contract. It does not "
            "bypass topology, hardware, native-telemetry, or report acceptance gates "
            "and does not establish an architecture effect."
        ),
    }


def primary_policy_pair_metadata(
    config: dict[str, Any],
    *,
    repeat: int,
    policy: str,
) -> dict[str, Any]:
    ablation = validate_primary_policy_ablation(config)
    repeats = int(ablation["repeats"])
    if repeat < 1 or repeat > repeats:
        raise ContractError(f"primary policy pair repeat must be between 1 and {repeats}")
    frozen_policy = str(ablation["frozen_policy"])
    online_policy = str(ablation["online_policy"])
    if policy not in {frozen_policy, online_policy}:
        raise ContractError("primary policy pair metadata requires a frozen or online arm")
    first_arm = str(ablation["arm_order"]["first_arm_by_pair"][repeat - 1])
    second_arm = online_policy if first_arm == frozen_policy else frozen_policy
    return {
        "contract_version": PRIMARY_POLICY_PAIR_METADATA_CONTRACT_VERSION,
        "strategy": str(ablation["arm_order"]["strategy"]),
        "repeat": repeat,
        "first_arm": first_arm,
        "arm_position": 1 if policy == first_arm else 2,
        "second_arm": second_arm,
    }


def validate_primary_policy_pair_metadata(
    config: dict[str, Any],
    *,
    repeat: int,
    policy: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ContractError("primary policy pair metadata must be a mapping")
    expected = primary_policy_pair_metadata(config, repeat=repeat, policy=policy)
    if metadata != expected:
        raise ContractError("primary policy pair metadata differs from the frozen arm order")
    return dict(expected)


def validate_primary_policy_pair_run_contract(
    config: dict[str, Any],
    *,
    system: str,
    scenario: str,
    policy: str,
    dataset: str,
    deadline_ms: float,
    streams: int,
    repeat: int,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    ablation = validate_primary_policy_ablation(config)
    coordinate_mismatches = []
    if system != str(ablation["system"]):
        coordinate_mismatches.append("system")
    if scenario != str(ablation["architecture_scenario"]):
        coordinate_mismatches.append("scenario")
    if policy not in {
        str(ablation["frozen_policy"]),
        str(ablation["online_policy"]),
    }:
        coordinate_mismatches.append("policy")
    if dataset != str(ablation["dataset"]):
        coordinate_mismatches.append("dataset")
    if not math.isclose(
        float(deadline_ms),
        float(ablation["deadline_ms"]),
        rel_tol=0.0,
        abs_tol=1.0e-9,
    ):
        coordinate_mismatches.append("deadline_ms")
    if int(streams) != int(ablation["streams"]):
        coordinate_mismatches.append("streams")
    if coordinate_mismatches:
        raise ContractError(
            "primary policy run differs from the frozen cell: "
            + ", ".join(coordinate_mismatches)
        )
    return validate_primary_policy_pair_metadata(
        config,
        repeat=repeat,
        policy=policy,
        metadata=metadata,
    )


def build_primary_policy_runtime_plan(config: dict[str, Any]) -> dict[str, Any]:
    ablation = validate_primary_policy_ablation(config)
    readiness = assess_primary_policy_runtime_compatibility(config)
    runs: list[dict[str, Any]] = []
    frozen_policy = str(ablation["frozen_policy"])
    online_policy = str(ablation["online_policy"])
    for repeat in range(1, int(ablation["repeats"]) + 1):
        first_arm = str(ablation["arm_order"]["first_arm_by_pair"][repeat - 1])
        second_arm = online_policy if first_arm == frozen_policy else frozen_policy
        for policy in (first_arm, second_arm):
            runs.append(
                {
                    "scenario": str(ablation["architecture_scenario"]),
                    "system": str(ablation["system"]),
                    "policy": policy,
                    "dataset": str(ablation["dataset"]),
                    "deadline_ms": float(ablation["deadline_ms"]),
                    "streams": int(ablation["streams"]),
                    "warmup_s": int(ablation["warmup_s"]),
                    "measurement_s": int(ablation["measurement_s"]),
                    "seed": int(ablation["seed"]),
                    "primary_policy_pair": primary_policy_pair_metadata(
                        config,
                        repeat=repeat,
                        policy=policy,
                    ),
                }
            )
    return {
        "plan_schema_version": 1,
        "status": str(readiness["status"]),
        "runtime_execution_allowed": bool(readiness["passed"]),
        "architecture_prerequisite": str(ablation["architecture_prerequisite"]),
        "architecture_acceptance_evidence_checked": False,
        "expected_pairs": int(ablation["repeats"]),
        "expected_runs": int(ablation["repeats"]) * 2,
        "runtime_compatibility": readiness,
        "runs": runs,
        "interpretation": (
            "This is a non-measurement schedule and metadata contract. It does not "
            "authorize benchmark execution or establish a policy effect."
        ),
    }


def assess_primary_policy_equivalence_scope(config: dict[str, Any]) -> dict[str, Any]:
    """Classify what the frozen v4 policy cell can establish before any run."""

    ablation = validate_primary_policy_ablation(config)
    runtime_compatibility = assess_primary_policy_runtime_compatibility(config)
    formal_reference = assess_formal_aw_heft_reference(config)
    passport = ablation["policy_passport"]
    resource_scope = {str(value) for value in passport.get("resource_scope", [])}
    missing_requirements = [
        f"resource_scope:{resource}"
        for resource in sorted(FORMAL_AW_HEFT_REQUIRED_RESOURCE_SCOPE - resource_scope)
    ]
    missing_requirements.extend(
        f"policy_passport:{field}"
        for field in sorted(FORMAL_AW_HEFT_REQUIRED_PASSPORT_FIELDS - set(passport))
    )

    return {
        "assessment_schema_version": 3,
        "policy_cell_preregistration_version": int(ablation["preregistration_version"]),
        "policy_cell_status": str(ablation["status"]),
        "policy_version_prefix": str(ablation["policy_version_prefix"]),
        "runtime_execution_compatibility": runtime_compatibility,
        "proxy_passport_equivalence": {
            "gate": "policy_implementation_equivalence",
            "scope": "frozen_v4_proxy_passport_replay",
            "status": "ready_runtime_reference_replay_not_executed",
            "passed": False,
            "assessment_level": "configuration_declaration_only",
            "runtime_reference_replay_performed": False,
            "runtime_reference_replay_implemented": True,
            "runtime_reference_replay_entrypoint": (
                "benchmark_contract.evaluate_primary_policy_proxy_replay"
            ),
            "interpretation": (
                "The declared pair gate can qualify only the technical v4 proxy "
                "estimand after the implemented reference replay is executed on an "
                "accepted frozen/online pair; it cannot establish formal AW-HEFT "
                "equivalence."
            ),
        },
        "formal_aw_heft_equivalence": {
            "gate": "formal_aw_heft_implementation_equivalence",
            "scope": "formal_cpu_gpu_nvdec_aw_heft_contract",
            "status": (
                "blocked_reference_not_runtime_bound_or_preregistered"
                if formal_reference["reference_contract_verified"]
                else "blocked_formal_reference_contract_invalid"
            ),
            "passed": False,
            "assessment_level": (
                "executable_reference_and_input_only_replay_without_runtime_binding"
            ),
            "formal_reference_replay_implemented": bool(
                formal_reference["formal_reference_replay_implemented"]
            ),
            "accepted_formal_trace_replay_performed": False,
            "runtime_reference_replay_performed": False,
            "reference_implementation": formal_reference,
            "missing_requirements": [
                *missing_requirements,
                "formal_h2_cell:not_preregistered",
                "formal_runtime:dataset_consuming_binding_missing",
                "formal_trace:accepted_trace_missing",
                "formal_replay:accepted_trace_not_performed",
            ],
            "interpretation": (
                "The frozen v4 proxy passport is compositionally narrower than "
                "formal AW-HEFT. A separately versioned executable reference is now "
                "available with input-only rank/decision/feedback replay for contract "
                "tests, but it has no dataset-consuming runtime binding, preregistered "
                "H2 cell, accepted trace, or replay of accepted evidence."
            ),
        },
        "policy_analysis": {
            "claim_state": "blocked_missing_accepted_policy_pairs_or_gates",
            "pair_analysis_implemented": True,
            "pair_analysis_entrypoint": (
                "generate_vast_report_artifacts.write_primary_policy_analysis"
            ),
            "formal_h2_cell_preregistered": False,
            "formal_reference_replay_implemented": bool(
                formal_reference["formal_reference_replay_implemented"]
            ),
            "accepted_formal_trace_replay_performed": False,
            "interpretation": (
                "The executable pair state machine remains blocked until accepted "
                "frozen/online runs pass replay and every preregistered guardrail. "
                "The technical proxy analysis does not evaluate formal AW-HEFT."
            ),
        },
    }


_NULL_STRINGS = {"", "none", "nan", "null"}
_UNLABELED_LEGACY = "unlabeled_legacy"
_RESOURCE_TIME_PROVENANCE = {
    "native_hardware_counter",
    "derived_from_native_stage_timestamps",
    _UNLABELED_LEGACY,
}
_TRANSFER_PROVENANCE = {
    "native_hardware_counter",
    "estimated_from_frame_dimensions",
    "unavailable",
    _UNLABELED_LEGACY,
}
_NVDEC_PROVENANCE = {
    "native_hardware_counter",
    "stage_presence_proxy",
    "unavailable",
    _UNLABELED_LEGACY,
}
_VRAM_PROVENANCE = {
    "native_hardware_counter",
    "estimated_from_frame_dimensions",
    "unavailable",
    _UNLABELED_LEGACY,
}
_DECISION_PROVENANCE = {
    "native_scheduler_trace",
    "derived_from_native_frame_event",
    _UNLABELED_LEGACY,
}
_TRACE_COMPLETENESS = {"full", "selected_action_only", _UNLABELED_LEGACY}
_CAUSAL_TRACE_COMPLETENESS = {"full", "partial", "not_available"}
_FEEDBACK_TRACE_COMPLETENESS = {"full", "partial"}
_FEEDBACK_PROVENANCE = {"native_terminal_feedback"}
_TERMINAL_STATUSES = {"completed", "drop", "censored", "not_applicable", "unavailable"}
_DROP_PROVENANCE = {"native_drop_event", "inferred_from_frame_id_gaps", _UNLABELED_LEGACY}
_LATE_PROVENANCE = {
    "native_deadline_event",
    "derived_from_native_frame_latency",
    _UNLABELED_LEGACY,
}
_INGRESS_TERMINAL_STATUSES = {"completed", "drop", "censored"}
_INGRESS_PROVENANCE = {"native_ingress_event"}
_INGRESS_TERMINAL_PROVENANCE = {
    "native_completion_event",
    "native_drop_event",
    "explicit_censoring_at_drain_end",
}
INGRESS_WALL_CLOCK_START_TOLERANCE_MS = 5.0
_BRANCH_TERMINAL_STATUSES = {"completed", "drop"}
_BRANCH_TERMINAL_PROVENANCE = {
    "completed": "native_completion_event",
    "drop": "native_drop_event",
}
_VERIFIED_ANALYTICS_BACKENDS = {
    "openvino-dlstreamer:gvadetect",
    "openvino-dlstreamer:object_detect",
}
_STAGE_CONTRACT_PROVENANCE = {"runtime_loaded_configuration"}
_STAGE_ARTIFACT_PROVENANCE = {"runtime_loaded_artifacts_v1"}
_STAGE_ARTIFACT_KINDS = {
    "container_image",
    "executable",
    "model",
    "plugin",
    "policy",
    "shared_library",
}
_RESET_EVIDENCE_PROVENANCE = {"native_process_lifecycle_queue_and_sink_snapshot_v1"}
_COMMON_PREFIX_STAGES = {"decode", "preprocess"}
_STAGE_BRANCH_SUFFIXES = {"a", "b", "primary", "secondary", "left", "right"}
_STAGE_BASE_NAMES = {
    "decode",
    "preprocess",
    "detect",
    "track",
    "classify",
    "aggregate",
    "record",
    "visualize",
}


def stage_base_name(stage: str) -> str:
    """Return the logical stage taxonomy name while preserving strict unique stage IDs elsewhere."""
    value = str(stage).strip()
    prefix = value.split("_", 1)[0]
    if prefix in _STAGE_BASE_NAMES:
        return prefix
    if "_" not in value:
        return value
    base, suffix = value.rsplit("_", 1)
    if suffix in _STAGE_BRANCH_SUFFIXES and base in _STAGE_BASE_NAMES:
        return base
    return value


def _missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in _NULL_STRINGS


def _parse_finite_number(value: Any, *, path: Path, row_number: int, column: str) -> float:
    if _missing_value(value):
        raise ContractError(f"{path}:{row_number}: missing or empty value for {column}")
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{path}:{row_number}: invalid numeric value for {column}: {value!r}") from exc
    if not math.isfinite(number):
        raise ContractError(f"{path}:{row_number}: invalid numeric value for {column}: {value!r}")
    return number


def validate_csv_row_fields(
    row: dict[str, Any],
    fieldnames: list[str],
    *,
    path: Path,
    row_number: int,
    numeric_columns: set[str] | None = None,
) -> dict[str, Any]:
    if None in row:
        raise ContractError(f"{path}:{row_number}: unexpected extra CSV fields: {row[None]!r}")
    normalized: dict[str, Any] = {}
    for field in fieldnames:
        value = row.get(field)
        if _missing_value(value):
            raise ContractError(f"{path}:{row_number}: missing or empty value for {field}")
        normalized[field] = value
    if "trace_id" in fieldnames and not str(normalized.get("trace_id", "")).strip():
        raise ContractError(f"{path}:{row_number}: missing or empty trace_id")
    for field in numeric_columns or set():
        _parse_finite_number(normalized[field], path=path, row_number=row_number, column=field)
    return normalized


def _validate_csv_file_rows(path: Path, fieldnames: list[str], numeric_columns: set[str]) -> None:
    with path.open("r", newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        for row_number, row in enumerate(reader, start=2):
            validate_csv_row_fields(
                row,
                fieldnames,
                path=path,
                row_number=row_number,
                numeric_columns=numeric_columns,
            )


def _validate_dataframe_fields(
    df: pd.DataFrame,
    path: Path,
    fieldnames: list[str],
    numeric_columns: set[str],
) -> None:
    missing = [column for column in fieldnames if column not in df.columns]
    if missing:
        raise ContractError(f"{path} is missing required columns: {', '.join(missing)}")
    for row_index, row in df[fieldnames].iterrows():
        row_number = int(row_index) + 2
        for field in fieldnames:
            if _missing_value(row[field]):
                raise ContractError(f"{path}:{row_number}: missing or empty value for {field}")
        if "trace_id" in fieldnames and not str(row["trace_id"]).strip():
            raise ContractError(f"{path}:{row_number}: missing or empty trace_id")
        for field in numeric_columns:
            _parse_finite_number(row[field], path=path, row_number=row_number, column=field)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ffprobe_metadata(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        raise ContractError("ffprobe is required to validate video metadata but was not found")
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=index,codec_name,codec_type,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        raise ContractError(f"ffprobe failed for {path}: {exc.output}") from exc
    payload = json.loads(output)
    streams = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"]
    if not streams:
        raise ContractError(f"ffprobe found no video stream in {path}")
    stream = streams[0]
    fmt = payload.get("format", {})
    return {
        "container": str(fmt.get("format_name", "")),
        "codec_name": str(stream.get("codec_name", "")),
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "r_frame_rate": str(stream.get("r_frame_rate", "")),
        "avg_frame_rate": str(stream.get("avg_frame_rate", "")),
        "duration_s": float(stream.get("duration") or fmt.get("duration") or 0.0),
        "frame_count": int(stream.get("nb_frames") or 0),
    }


def _validate_video_metadata(stream: dict[str, Any], abs_path: Path) -> None:
    metadata_keys = {
        "container",
        "codec_name",
        "width",
        "height",
        "r_frame_rate",
        "avg_frame_rate",
        "duration_s",
        "frame_count",
        "fps_policy",
        "camera_role",
    }
    if not metadata_keys.intersection(stream):
        return
    missing = sorted(metadata_keys - set(stream))
    if missing:
        raise ContractError(f"dataset stream {stream.get('path', abs_path)} is missing video metadata: {', '.join(missing)}")
    fps_policy = str(stream.get("fps_policy", "")).strip()
    if fps_policy not in {"constant", "pts_frame_count", "pts", "cfr_600_from_source_pts"}:
        raise ContractError(f"dataset stream {stream.get('path', abs_path)} has unsupported fps_policy={fps_policy!r}")
    if str(stream["r_frame_rate"]) != str(stream["avg_frame_rate"]) and fps_policy == "constant":
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} has ambiguous FPS but fps_policy is constant"
        )
    probed = _ffprobe_metadata(abs_path)
    container = str(stream["container"])
    if container not in str(probed["container"]).split(","):
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} container mismatch: expected {container}, got {probed['container']}"
        )
    for key in ("codec_name", "r_frame_rate", "avg_frame_rate"):
        expected = str(stream[key])
        actual = str(probed[key])
        if expected != actual:
            raise ContractError(
                f"dataset stream {stream.get('path', abs_path)} metadata mismatch for {key}: expected {expected}, got {actual}"
            )
    for key in ("width", "height", "frame_count"):
        expected = int(stream[key])
        actual = int(probed[key])
        if expected != actual:
            raise ContractError(
                f"dataset stream {stream.get('path', abs_path)} metadata mismatch for {key}: expected {expected}, got {actual}"
            )
    expected_duration = float(stream["duration_s"])
    if abs(expected_duration - float(probed["duration_s"])) > 0.01:
        raise ContractError(
            f"dataset stream {stream.get('path', abs_path)} duration mismatch: "
            f"expected {expected_duration}, got {probed['duration_s']}"
        )


def _validate_dataset_annotations(dataset_name: str, dataset: dict[str, Any], project_root: Path, require_files: bool) -> None:
    annotations = dataset.get("annotations") or {}
    if not annotations:
        return
    rel_path = Path(str(annotations.get("path", "")))
    if not str(rel_path):
        raise ContractError(f"dataset '{dataset_name}' annotation path is empty")
    abs_path = project_root / rel_path
    if require_files and not abs_path.exists():
        raise ContractError(f"dataset annotation file is missing: {abs_path}")
    expected = str(annotations.get("sha256", "")).strip()
    if require_files and expected:
        actual = sha256_file(abs_path)
        if actual != expected:
            raise ContractError(f"dataset annotation checksum mismatch for {rel_path}: expected {expected}, got {actual}")


_DATASET_RUNTIME_DERIVED_KEYS = {
    "absolute_path",
    "resolved_sha256",
    "aggregate_sha256",
    "manifest_identity_schema_version",
    "manifest_identity_sha256",
}


def _canonical_contract_identity_value(
    value: Any,
    *,
    excluded_keys: set[str],
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_contract_identity_value(
                item,
                excluded_keys=excluded_keys,
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in excluded_keys
        }
    if isinstance(value, list):
        return [
            _canonical_contract_identity_value(
                item,
                excluded_keys=excluded_keys,
            )
            for item in value
        ]
    return value


def _versioned_contract_identity(
    value: dict[str, Any],
    *,
    schema_version: int,
    excluded_keys: set[str],
) -> dict[str, Any]:
    payload = _canonical_contract_identity_value(
        value,
        excluded_keys=excluded_keys,
    )
    payload_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return {
        "schema_version": schema_version,
        "sha256": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        "payload_json": payload_json,
    }


def dataset_manifest_identity(dataset: dict[str, Any]) -> dict[str, Any]:
    """Hash the frozen logical dataset manifest without host-specific paths."""

    return _versioned_contract_identity(
        dataset,
        schema_version=DATASET_MANIFEST_IDENTITY_VERSION,
        excluded_keys=_DATASET_RUNTIME_DERIVED_KEYS,
    )


def normalize_scenario_contract(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Resolve defaults that affect scenario execution before hashing or launch."""

    if "workload" not in raw:
        raise ValueError(
            f"scenario '{name}' must use the new schema and include a 'workload' section"
        )
    workload = dict(raw.get("workload") or {})
    pipeline = list(raw.get("pipeline") or [])
    placement = dict(raw.get("placement") or {})
    network = dict(raw.get("network") or {})
    distributed = dict(raw.get("distributed") or {})

    if not pipeline:
        raise ValueError(f"scenario '{name}' must define a non-empty pipeline")
    if "stages" not in placement:
        placement["stages"] = {stage: "local" for stage in pipeline}
    for stage in pipeline:
        if stage not in placement["stages"]:
            raise ValueError(f"scenario '{name}' placement is missing stage '{stage}'")

    object_profile = workload.get("object_density") or {}
    min_objects = int(object_profile.get("min", 0))
    max_objects = int(object_profile.get("max", 20))
    if min_objects > max_objects:
        raise ValueError(f"scenario '{name}' object_density min cannot exceed max")
    if "stream_range" not in workload and "streams" not in workload:
        raise ValueError(
            f"scenario '{name}' workload must define streams or stream_range"
        )

    return {
        "name": name,
        "description": raw.get("description", ""),
        "benchmark_status": raw.get("benchmark_status", "supported"),
        "benchmark_reason": raw.get("benchmark_reason", ""),
        "topology": dict(raw.get("topology") or {}),
        "workload": workload,
        "pipeline": pipeline,
        "placement": placement,
        "network": network,
        "distributed": distributed,
    }


def resolve_scenario_contract(
    name: str,
    raw: dict[str, Any],
    *,
    variant_name: str = "",
) -> dict[str, Any]:
    scenario = normalize_scenario_contract(name, raw)
    if not variant_name:
        return scenario
    variants = list(scenario["workload"].get("variants") or [])
    matches = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and str(variant.get("name", "variant")) == variant_name
    ]
    if len(matches) != 1:
        raise ContractError(
            f"scenario '{name}' has no unique workload variant '{variant_name}'"
        )
    resolved = json.loads(json.dumps(scenario))
    resolved["workload"].update(matches[0])
    resolved["workload"]["variant"] = variant_name
    if "placement_policy" in matches[0]:
        resolved["placement"]["policy"] = str(matches[0]["placement_policy"])
    return resolved


def scenario_contract_identity(scenario: dict[str, Any]) -> dict[str, Any]:
    """Hash the complete resolved scenario, preserving ordered execution fields."""

    return _versioned_contract_identity(
        scenario,
        schema_version=SCENARIO_CONTRACT_IDENTITY_VERSION,
        excluded_keys=set(),
    )


_PUBLICATION_RUN_COORDINATE_FIELDS = (
    "run_mode",
    "system",
    "scenario",
    "scenario_variant",
    "repeat",
    "streams",
    "duration_s",
    "deployment_mode",
    "host_topology",
    "distributed",
    "placement_policy",
    "detector",
    "backend",
    "policy",
    "dataset",
    "deadline_ms",
    "seed",
    "run_seed",
)


def resolve_publication_run_contract(
    config: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the configuration and frozen-analysis contract for one run."""

    system_name = str(result.get("system", "")).strip()
    systems = config.get("systems") or {}
    if not system_name or not isinstance(systems, dict) or system_name not in systems:
        raise ContractError(
            f"publication run contract references unknown system: {system_name or '<missing>'}"
        )
    system_config = systems[system_name]
    if not isinstance(system_config, dict):
        raise ContractError(
            f"publication run contract system configuration must be a mapping: {system_name}"
        )

    benchmark = config.get("benchmark") or {}
    if not isinstance(benchmark, dict):
        raise ContractError("publication run contract requires benchmark configuration")
    coordinates = {
        field: ("" if field == "scenario_variant" and result.get(field) is None else result.get(field))
        for field in _PUBLICATION_RUN_COORDINATE_FIELDS
    }
    contract: dict[str, Any] = {
        "run_coordinates": coordinates,
        "telemetry_contract": {
            "schema_version": benchmark.get("telemetry_schema_version"),
            "publishable_sources": list(
                benchmark.get("publishable_telemetry_sources") or []
            ),
        },
        "protocol": dict(config.get("protocol") or {}),
        "transport": dict(config.get("transport") or {}),
        "hardware_target": dict(config.get("hardware_target") or {}),
        "system": {
            "name": system_name,
            "configuration": dict(system_config),
        },
    }

    scenario_name = str(result.get("scenario", ""))
    policy_name = str(result.get("policy", ""))
    primary = benchmark.get("primary_architecture_contrast")
    if isinstance(primary, dict):
        primary_scenarios = {
            str(primary.get("baseline_scenario", "")),
            str(primary.get("shared_scenario", "")),
        }
        if system_name == str(primary.get("system", "")) and scenario_name in primary_scenarios:
            contract["primary_architecture_contrast"] = dict(primary)

    policy_ablation = benchmark.get("primary_policy_ablation")
    if isinstance(policy_ablation, dict):
        policy_arms = {
            str(policy_ablation.get("frozen_policy", "")),
            str(policy_ablation.get("online_policy", "")),
        }
        if (
            system_name == str(policy_ablation.get("system", ""))
            and scenario_name == str(policy_ablation.get("architecture_scenario", ""))
            and policy_name in policy_arms
        ):
            contract["primary_policy_ablation"] = dict(policy_ablation)

    return contract


def publication_run_contract_identity(contract: dict[str, Any]) -> dict[str, Any]:
    """Hash the resolved per-run execution and preregistration contract."""

    return _versioned_contract_identity(
        contract,
        schema_version=PUBLICATION_RUN_CONTRACT_IDENTITY_VERSION,
        excluded_keys=set(),
    )


def resolve_publication_evidence_bundle_scope(
    config: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """Select the frozen byte-manifest scope from run coordinates."""

    benchmark = config.get("benchmark") or {}
    extension = benchmark.get("resource_interval_extension")
    matrix_policies = {str(value) for value in benchmark.get("scheduler_policies") or ()}
    matrix_scenarios = {str(value) for value in benchmark.get("active_scenarios") or ()}
    if (
        isinstance(extension, dict)
        and str(result.get("policy", "")) in matrix_policies
        and str(result.get("scenario", "")) in matrix_scenarios
        and str(extension.get("status", "")) == "accepted_full_resource_publication_v2"
        and str(extension.get("current_publication_bundle_scope", ""))
        == FULL_RESOURCE_PUBLICATION_SCOPE
        and bool(extension.get("publication_bundle_bound"))
        and bool(extension.get("evidence_accepted"))
    ):
        return FULL_RESOURCE_PUBLICATION_SCOPE
    ablation = benchmark.get("primary_policy_ablation")
    if isinstance(ablation, dict):
        matches_policy_cell = (
            str(result.get("system", "")) == str(ablation.get("system", ""))
            and str(result.get("scenario", ""))
            == str(ablation.get("architecture_scenario", ""))
        )
        if matches_policy_cell:
            policy = str(result.get("policy", ""))
            if policy == str(ablation.get("frozen_policy", "")):
                return PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE
            if policy == str(ablation.get("online_policy", "")):
                return PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE
    return PUBLICATION_EVIDENCE_BUNDLE_SCOPE


def publication_evidence_bundle_files(scope: str) -> tuple[str, ...]:
    """Return the exact, ordered raw-file set for one publication scope."""

    files_by_scope = {
        PUBLICATION_EVIDENCE_BUNDLE_SCOPE: PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS,
        FULL_RESOURCE_PUBLICATION_SCOPE: FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
        PUBLICATION_EVIDENCE_BUNDLE_POLICY_FROZEN_SCOPE: (
            PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS
        ),
        PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE: (
            PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS | {"policy_feedback.csv"}
        ),
    }
    try:
        return tuple(sorted(files_by_scope[scope]))
    except KeyError as exc:
        raise ContractError(
            f"publication evidence bundle uses an unsupported scope: {scope}"
        ) from exc


def build_publication_evidence_bundle(
    run_dir: Path,
    *,
    scope: str,
) -> dict[str, Any]:
    """Hash the exact claim-critical raw files after accepted-sidecar validation."""

    records: list[dict[str, Any]] = []
    for relative_name in publication_evidence_bundle_files(scope):
        path = run_dir / relative_name
        if path.is_symlink():
            raise ContractError(
                f"publication evidence file must not be a symbolic link: {path}"
            )
        if not path.is_file():
            raise ContractError(f"publication evidence file is missing: {path}")
        records.append(
            {
                "relative_path": relative_name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": PUBLICATION_EVIDENCE_BUNDLE_IDENTITY_VERSION,
        "scope": scope,
        "files": records,
    }


def publication_evidence_bundle_identity(bundle: dict[str, Any]) -> dict[str, Any]:
    """Hash one complete primary-architecture raw evidence bundle."""

    return _versioned_contract_identity(
        bundle,
        schema_version=PUBLICATION_EVIDENCE_BUNDLE_IDENTITY_VERSION,
        excluded_keys=set(),
    )


def validate_publication_evidence_bundle(
    run_dir: Path,
    bundle: Any,
    declared_identity: Any,
    *,
    expected_scope: str,
) -> dict[str, Any]:
    """Recompute bundle bytes and reject absent, replaced, or re-ordered evidence."""

    if not isinstance(bundle, dict):
        raise ContractError("publication evidence bundle must be a mapping")
    if bundle.get("schema_version") != PUBLICATION_EVIDENCE_BUNDLE_IDENTITY_VERSION:
        raise ContractError(
            "publication evidence bundle uses an unsupported schema version"
        )
    publication_evidence_bundle_files(expected_scope)
    if bundle.get("scope") != expected_scope:
        raise ContractError(
            "publication evidence bundle scope does not match the expected run scope"
        )
    expected = build_publication_evidence_bundle(run_dir, scope=expected_scope)
    if bundle != expected:
        raise ContractError(
            "publication evidence bundle does not match current claim-critical raw files"
        )
    if not isinstance(declared_identity, dict):
        raise ContractError("publication evidence bundle identity must be a mapping")
    computed_identity = publication_evidence_bundle_identity(bundle)
    if (
        declared_identity.get("schema_version")
        != computed_identity["schema_version"]
    ):
        raise ContractError(
            "publication evidence bundle identity schema version does not match"
        )
    if declared_identity.get("sha256") != computed_identity["sha256"]:
        raise ContractError("publication evidence bundle identity SHA-256 does not match")
    return expected


def load_dataset(
    manifest_path: Path,
    dataset_name: str,
    *,
    mode: str,
    project_root: Path,
    require_files: bool,
    allow_placeholder_checksums: bool = False,
) -> dict[str, Any]:
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}
    datasets = manifest.get("datasets", {})
    if dataset_name not in datasets:
        raise ContractError(f"unknown dataset '{dataset_name}' in {manifest_path}")

    dataset = dict(datasets[dataset_name] or {})
    dataset["name"] = dataset_name
    streams = list(dataset.get("streams") or [])
    if not streams:
        raise ContractError(f"dataset '{dataset_name}' has no streams")
    if mode == "benchmark" and not bool(dataset.get("publishable")):
        raise ContractError(f"dataset '{dataset_name}' is not publishable and cannot be used in benchmark mode")

    resolved_streams: list[dict[str, Any]] = []
    checksums: list[str] = []
    checksum_cache: dict[Path, str] = {}
    for raw_stream in streams:
        stream = dict(raw_stream or {})
        rel_path = Path(str(stream.get("path", "")))
        if not str(rel_path):
            raise ContractError(f"dataset '{dataset_name}' contains a stream without path")
        abs_path = project_root / rel_path
        expected = str(stream.get("sha256", "")).strip()
        if mode == "benchmark" and not allow_placeholder_checksums and (not expected or expected.startswith("SET_")):
            raise ContractError(f"dataset '{dataset_name}' requires a real sha256 for {rel_path}")
        if require_files and not abs_path.exists():
            raise ContractError(f"dataset stream is missing: {abs_path}")
        actual = ""
        if abs_path.exists():
            actual = checksum_cache.setdefault(abs_path, sha256_file(abs_path))
        if expected and actual and expected != actual:
            raise ContractError(f"dataset checksum mismatch for {rel_path}: expected {expected}, got {actual}")
        if require_files:
            _validate_video_metadata(stream, abs_path)
        checksums.append(actual or expected or "missing")
        stream["absolute_path"] = str(abs_path)
        stream["resolved_sha256"] = actual or expected
        resolved_streams.append(stream)

    _validate_dataset_annotations(dataset_name, dataset, project_root, require_files)
    dataset["streams"] = resolved_streams
    dataset["aggregate_sha256"] = hashlib.sha256("\n".join(checksums).encode("utf-8")).hexdigest()
    identity = dataset_manifest_identity(dataset)
    dataset["manifest_identity_schema_version"] = identity["schema_version"]
    dataset["manifest_identity_sha256"] = identity["sha256"]
    return dataset


def _first_existing(df: pd.DataFrame, *names: str) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name]
    raise ContractError(f"frames.csv is missing required columns: one of {names}")


def canonicalize_frames_csv(
    path: Path,
    *,
    mode: str,
    run_id: str,
    detector: str,
    backend: str,
) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"frames.csv was not produced: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frames.csv is empty: {path}")

    missing = [column for column in FRAME_COLUMNS if column not in df.columns]
    if missing:
        if mode == "benchmark":
            raise ContractError(
                "benchmark mode requires native telemetry schema v2; "
                f"{path} is missing: {', '.join(missing)}"
            )
        egress = pd.to_numeric(_first_existing(df, "egress_timestamp_ms", "timestamp_ms"), errors="raise")
        latency = pd.to_numeric(_first_existing(df, "e2e_latency_ms", "latency_ms"), errors="raise")
        stream_ids = pd.to_numeric(_first_existing(df, "stream_id"), errors="raise").astype(int)
        frame_ids = pd.to_numeric(_first_existing(df, "frame_id"), errors="raise").astype(int)
        objects = (
            pd.to_numeric(df["objects"], errors="coerce").fillna(0).astype(int)
            if "objects" in df.columns
            else pd.Series([0] * len(df))
        )
        df = pd.DataFrame(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "trace_id": [
                    f"{run_id}:{stream_id}:{frame_id}"
                    for stream_id, frame_id in zip(stream_ids, frame_ids, strict=True)
                ],
                "stream_id": stream_ids,
                "frame_id": frame_ids,
                "ingress_timestamp_ms": egress - latency,
                "egress_timestamp_ms": egress,
                "e2e_latency_ms": latency,
                "objects": objects,
                "detector": detector,
                "backend": backend,
                "telemetry_source": "synthetic",
            }
        )
        df.to_csv(path, index=False)

    _validate_dataframe_fields(df, path, FRAME_COLUMNS, FRAME_NUMERIC_COLUMNS)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported telemetry schema version in {path}")
    if mode == "benchmark" and set(df["telemetry_source"].astype(str)) != {"native"}:
        raise ContractError("benchmark mode only accepts telemetry_source=native")
    if df["trace_id"].astype(str).duplicated().any():
        raise ContractError(f"duplicate trace_id values in {path}")
    if (pd.to_numeric(df["e2e_latency_ms"], errors="raise") < 0).any():
        raise ContractError(f"negative e2e latency in {path}")
    return df[FRAME_COLUMNS]


def summarize_frames(
    path: Path,
    *,
    deadline_ms: float | None = None,
    deadline_s: float | None = None,
    measurement_s: float,
) -> dict[str, Any]:
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frames.csv is empty: {path}")
    if deadline_ms is None:
        if deadline_s is None:
            raise ContractError("summarize_frames requires deadline_ms")
        deadline_ms = float(deadline_s) * 1000.0
    latency = pd.to_numeric(df["e2e_latency_ms"], errors="raise")
    frames = int(df.shape[0])
    duration_s = max(float(measurement_s), 0.001)
    return {
        "deadline_ms": float(deadline_ms),
        "throughput_fps": round(frames / duration_s, 3),
        "latency_p50_ms": round(float(latency.quantile(0.50)), 3),
        "latency_p95_ms": round(float(latency.quantile(0.95)), 3),
        "latency_p99_ms": round(float(latency.quantile(0.99)), 3),
        "latency_p999_ms": round(float(latency.quantile(0.999)), 3),
        "latency_max_ms": round(float(latency.max()), 3),
        "slo_violation_rate_percent": round(float((latency > float(deadline_ms)).mean() * 100.0), 3),
        "frames": frames,
        "telemetry_source": ",".join(sorted(set(df["telemetry_source"].astype(str)))),
    }


def validate_frame_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"frame_events.csv was not produced: {path}")
    _validate_csv_file_rows(path, FRAME_EVENT_COLUMNS, FRAME_EVENT_NUMERIC_COLUMNS)
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"frame_events.csv is empty: {path}")
    missing = [column for column in FRAME_EVENT_COLUMNS if column not in df.columns]
    if missing:
        raise ContractError(f"{path} is missing frame event columns: {', '.join(missing)}")
    _validate_dataframe_fields(df, path, FRAME_EVENT_COLUMNS, FRAME_EVENT_NUMERIC_COLUMNS)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported frame event schema version in {path}")
    return df[FRAME_EVENT_COLUMNS]


def validate_stage_trace_coverage(
    frames_path: Path,
    frame_events_path: Path,
    *,
    required_stages: list[str],
) -> None:
    frames = canonicalize_frames_csv(
        frames_path,
        mode="benchmark",
        run_id="",
        detector="",
        backend="",
    )
    events = validate_frame_events(frame_events_path)
    frame_traces = set(frames["trace_id"].astype(str))
    if not frame_traces:
        raise ContractError(f"frames.csv has no trace_id values: {frames_path}")
    for stage in required_stages:
        stage_traces = set(events.loc[events["stage"].astype(str) == str(stage), "trace_id"].astype(str))
        missing = frame_traces - stage_traces
        if missing:
            sample = ", ".join(sorted(missing)[:5])
            raise ContractError(
                f"missing native frame_events for stage '{stage}' "
                f"on {len(missing)} completed frames; sample trace_id values: {sample}"
            )


def _validate_native_sidecar(path: Path, columns: list[str], numeric_columns: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"{path.name} was not produced: {path}")
    _validate_csv_file_rows(path, columns, numeric_columns)
    df = pd.read_csv(path)
    if df.empty:
        raise ContractError(f"{path.name} is empty: {path}")
    _validate_dataframe_fields(df, path, columns, numeric_columns)
    schema_versions = pd.to_numeric(df["schema_version"], errors="raise")
    if (schema_versions != TELEMETRY_SCHEMA_VERSION).any():
        raise ContractError(f"unsupported telemetry schema version in {path}")
    if set(df["telemetry_source"].astype(str)) != {"native"}:
        raise ContractError(f"benchmark mode only accepts telemetry_source=native in {path.name}")
    return df[columns]


def _select_sidecar_columns(
    path: Path,
    current_columns: list[str],
    legacy_columns: list[str],
    provenance_columns: list[str],
) -> list[str]:
    if not path.exists():
        return current_columns
    with path.open("r", newline="", encoding="utf-8") as src:
        header = set(csv.DictReader(src).fieldnames or [])
    present = [column in header for column in provenance_columns]
    if any(present) and not all(present):
        missing = [column for column, exists in zip(provenance_columns, present) if not exists]
        raise ContractError(f"{path} has incomplete provenance columns: {', '.join(missing)}")
    return current_columns if all(present) else legacy_columns


def _select_policy_decision_columns(path: Path) -> list[str]:
    if not path.exists():
        return POLICY_DECISION_COLUMNS
    with path.open("r", newline="", encoding="utf-8") as src:
        header = set(csv.DictReader(src).fieldnames or [])
    trace_present = [column in header for column in POLICY_TRACE_COLUMNS]
    if any(trace_present) and not all(trace_present):
        missing = [column for column, exists in zip(POLICY_TRACE_COLUMNS, trace_present) if not exists]
        raise ContractError(f"{path} has incomplete policy trace columns: {', '.join(missing)}")
    causal_present = [column in header for column in POLICY_CAUSAL_TRACE_COLUMNS]
    if any(causal_present) and not all(causal_present):
        missing = [column for column, exists in zip(POLICY_CAUSAL_TRACE_COLUMNS, causal_present) if not exists]
        raise ContractError(f"{path} has incomplete causal policy trace columns: {', '.join(missing)}")
    if all(causal_present) and not all(trace_present):
        raise ContractError(f"{path} has causal policy trace columns without the engineering policy trace")
    if all(causal_present):
        return POLICY_DECISION_COLUMNS
    if all(trace_present):
        return ENGINEERING_POLICY_DECISION_COLUMNS
    return _select_sidecar_columns(
        path,
        PROVENANCE_POLICY_DECISION_COLUMNS,
        LEGACY_POLICY_DECISION_COLUMNS,
        POLICY_DECISION_PROVENANCE_COLUMNS,
    )


def _validate_provenance_values(df: pd.DataFrame, path: Path, column: str, allowed: set[str]) -> None:
    values = set(df[column].astype(str))
    invalid = sorted(values - allowed)
    if invalid:
        raise ContractError(f"{path}:{column} has unsupported provenance values: {', '.join(invalid)}")


def _require_labeled_provenance(
    df: pd.DataFrame,
    path: Path,
    provenance_columns: list[str],
    required: bool,
) -> None:
    if not required:
        return
    unlabeled = [column for column in provenance_columns if (df[column].astype(str) == _UNLABELED_LEGACY).any()]
    if unlabeled:
        raise ContractError(f"{path} lacks explicit metric provenance: {', '.join(unlabeled)}")


def _parse_json_field(value: Any, *, path: Path, row_number: int, column: str, expected_type: type) -> Any:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}:{row_number}: invalid JSON value for {column}") from exc
    if not isinstance(parsed, expected_type):
        raise ContractError(f"{path}:{row_number}: {column} must contain {expected_type.__name__} JSON")
    return parsed


def _finite_json_number(value: Any, *, path: Path, row_number: int, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ContractError(f"{path}:{row_number}: {field} must be a finite JSON number")
    return float(value)


def _positive_weight_map(value: Any, *, path: Path, row_number: int, field: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ContractError(f"{path}:{row_number}: {field} must be a non-empty JSON object")
    normalized: dict[str, float] = {}
    for raw_resource, raw_weight in value.items():
        resource = str(raw_resource).strip().lower()
        if not resource or resource in normalized:
            raise ContractError(f"{path}:{row_number}: {field} must use unique non-empty resource names")
        weight = _finite_json_number(
            raw_weight,
            path=path,
            row_number=row_number,
            field=f"{field}.{resource}",
        )
        if weight <= 0:
            raise ContractError(f"{path}:{row_number}: {field}.{resource} must be positive")
        normalized[resource] = weight
    return normalized


def _finite_weight_map(value: Any, *, path: Path, row_number: int, field: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ContractError(f"{path}:{row_number}: {field} must be a non-empty JSON object")
    normalized: dict[str, float] = {}
    for raw_resource, raw_weight in value.items():
        resource = str(raw_resource).strip().lower()
        if not resource or resource in normalized:
            raise ContractError(f"{path}:{row_number}: {field} must use unique non-empty resource names")
        normalized[resource] = _finite_json_number(
            raw_weight,
            path=path,
            row_number=row_number,
            field=f"{field}.{resource}",
        )
    return normalized


def _nonnegative_integer(value: Any, *, path: Path, row_number: int, field: str) -> int:
    number = _finite_json_number(value, path=path, row_number=row_number, field=field)
    integer = int(number)
    if number != integer or integer < 0:
        raise ContractError(f"{path}:{row_number}: {field} must be a non-negative integer")
    return integer


def _weight_maps_close(left: dict[str, float], right: dict[str, float], *, tolerance: float = 1e-9) -> bool:
    return set(left) == set(right) and all(
        math.isclose(left[resource], right[resource], rel_tol=1e-9, abs_tol=tolerance)
        for resource in left
    )


def _project_weights_to_box_mean_one(
    raw: dict[str, float],
    lower: dict[str, float],
    upper: dict[str, float],
) -> dict[str, float]:
    resources = sorted(raw)
    if set(lower) != set(resources) or set(upper) != set(resources):
        raise ValueError("projection maps must cover the same resources")
    target = float(len(resources))
    if sum(lower.values()) > target + 1e-12 or sum(upper.values()) < target - 1e-12:
        raise ValueError("box bounds do not intersect the mean-one hyperplane")
    lo = min(raw[resource] - upper[resource] for resource in resources)
    hi = max(raw[resource] - lower[resource] for resource in resources)
    for _ in range(200):
        shift = (lo + hi) / 2.0
        total = sum(
            max(lower[resource], min(upper[resource], raw[resource] - shift))
            for resource in resources
        )
        if total > target:
            lo = shift
        else:
            hi = shift
    shift = (lo + hi) / 2.0
    return {
        resource: max(lower[resource], min(upper[resource], raw[resource] - shift))
        for resource in resources
    }


def _policy_feedback_parameters(
    decisions: pd.DataFrame,
    *,
    path: Path,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str, int], dict[str, float]]]:
    configs: dict[tuple[str, str], dict[str, Any]] = {}
    version_weights: dict[tuple[str, str, int], dict[str, float]] = {}
    for row_index, row in decisions.iterrows():
        row_number = int(row_index) + 2
        key = (str(row["run_id"]), str(row["policy"]).strip())
        parameters = _parse_json_field(
            row["parameters_json"],
            path=path,
            row_number=row_number,
            column="parameters_json",
            expected_type=dict,
        )
        required = {
            "weights",
            "weight_lower_bounds",
            "weight_upper_bounds",
            "projection_rule",
            "feedback_lag_limit",
            "feedback_cooldown_events",
            "variation_budget",
            "feedback_update_rule",
            "feedback_update_parameters",
        }
        if not required.issubset(parameters):
            missing = ", ".join(sorted(required - set(parameters)))
            raise ContractError(f"{path}:{row_number}: online feedback parameters missing: {missing}")
        weights = _positive_weight_map(
            parameters["weights"], path=path, row_number=row_number, field="parameters_json.weights"
        )
        lower = _positive_weight_map(
            parameters["weight_lower_bounds"],
            path=path,
            row_number=row_number,
            field="parameters_json.weight_lower_bounds",
        )
        upper = _positive_weight_map(
            parameters["weight_upper_bounds"],
            path=path,
            row_number=row_number,
            field="parameters_json.weight_upper_bounds",
        )
        if set(weights) != set(lower) or set(weights) != set(upper):
            raise ContractError(f"{path}:{row_number}: weight bounds must cover every policy resource")
        if any(lower[resource] > upper[resource] for resource in weights):
            raise ContractError(f"{path}:{row_number}: weight lower bound exceeds upper bound")
        if not math.isclose(sum(weights.values()), float(len(weights)), rel_tol=1e-9, abs_tol=1e-9):
            raise ContractError(f"{path}:{row_number}: online policy weights must have arithmetic mean one")
        if any(weights[resource] < lower[resource] - 1e-9 or weights[resource] > upper[resource] + 1e-9 for resource in weights):
            raise ContractError(f"{path}:{row_number}: online policy weights violate configured box bounds")
        projection_rule = str(parameters["projection_rule"]).strip()
        if projection_rule != "euclidean_box_mean_one_v1":
            raise ContractError(f"{path}:{row_number}: unsupported online weight projection_rule")
        lag_limit = _nonnegative_integer(
            parameters["feedback_lag_limit"],
            path=path,
            row_number=row_number,
            field="parameters_json.feedback_lag_limit",
        )
        cooldown = _nonnegative_integer(
            parameters["feedback_cooldown_events"],
            path=path,
            row_number=row_number,
            field="parameters_json.feedback_cooldown_events",
        )
        variation_budget = _finite_json_number(
            parameters["variation_budget"],
            path=path,
            row_number=row_number,
            field="parameters_json.variation_budget",
        )
        if variation_budget < 0:
            raise ContractError(f"{path}:{row_number}: variation_budget must be non-negative")
        feedback_update_rule = str(parameters["feedback_update_rule"]).strip()
        feedback_update_parameters = parameters["feedback_update_parameters"]
        if feedback_update_rule in {"", "unavailable"}:
            raise ContractError(f"{path}:{row_number}: feedback_update_rule must be versioned")
        if not isinstance(feedback_update_parameters, dict) or not feedback_update_parameters:
            raise ContractError(f"{path}:{row_number}: feedback_update_parameters must be a non-empty object")
        config = {
            "lower": lower,
            "upper": upper,
            "projection_rule": projection_rule,
            "lag_limit": lag_limit,
            "cooldown": cooldown,
            "variation_budget": variation_budget,
            "feedback_update_rule": feedback_update_rule,
            "feedback_update_parameters": feedback_update_parameters,
        }
        previous = configs.get(key)
        if previous is not None and previous != config:
            raise ContractError(f"{path}:{row_number}: online feedback passport changes within one run")
        configs[key] = config
        update_seq = int(float(row["update_seq"]))
        version_key = (*key, update_seq)
        prior_weights = version_weights.get(version_key)
        if prior_weights is not None and not _weight_maps_close(prior_weights, weights):
            raise ContractError(f"{path}:{row_number}: one parameter snapshot version has conflicting weights")
        version_weights[version_key] = weights
    return configs, version_weights


def _validate_policy_trace_fields(
    df: pd.DataFrame,
    path: Path,
    *,
    require_full_trace: bool,
) -> pd.DataFrame:
    previous_update_seq: dict[tuple[str, str], int] = {}
    eligible: list[bool] = []
    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        run_id = str(row["run_id"])
        policy_name = str(row["policy"]).strip()
        sequence_key = (run_id, policy_name)
        previous_seq = previous_update_seq.get(sequence_key, 0)
        update_seq_number = _parse_finite_number(
            row["update_seq"],
            path=path,
            row_number=row_number,
            column="update_seq",
        )
        update_seq = int(update_seq_number)
        if update_seq < 0 or update_seq_number != update_seq:
            raise ContractError(f"{path}:{row_number}: update_seq must be a non-negative integer")
        if update_seq < previous_seq:
            raise ContractError(
                f"{path}:{row_number}: update_seq must be monotonic within "
                f"run_id={run_id}, policy={policy_name}"
            )
        sequence_advanced = update_seq > previous_seq

        allowed = _parse_json_field(
            row["allowed_resources_json"],
            path=path,
            row_number=row_number,
            column="allowed_resources_json",
            expected_type=list,
        )
        scores = _parse_json_field(
            row["alternative_scores_json"],
            path=path,
            row_number=row_number,
            column="alternative_scores_json",
            expected_type=dict,
        )
        components = _parse_json_field(
            row["cost_components_json"],
            path=path,
            row_number=row_number,
            column="cost_components_json",
            expected_type=dict,
        )
        parameters = _parse_json_field(
            row["parameters_json"],
            path=path,
            row_number=row_number,
            column="parameters_json",
            expected_type=dict,
        )
        update = _parse_json_field(
            row["update_json"],
            path=path,
            row_number=row_number,
            column="update_json",
            expected_type=dict,
        )

        is_full = str(row["trace_completeness"]) == "full"
        row_eligible = is_full and str(row["decision_provenance"]) == "native_scheduler_trace"
        eligible.append(row_eligible)
        if not is_full:
            previous_update_seq[sequence_key] = update_seq
            continue

        resources = [str(resource).strip().lower() for resource in allowed]
        if not resources or any(not resource for resource in resources) or len(set(resources)) != len(resources):
            raise ContractError(f"{path}:{row_number}: allowed_resources_json must list unique resources")
        selected = str(row["resource"]).strip().lower()
        if selected not in resources:
            raise ContractError(f"{path}:{row_number}: selected resource is not in allowed_resources_json")
        missing_scores = sorted(set(resources) - set(scores))
        if missing_scores:
            raise ContractError(f"{path}:{row_number}: missing alternative scores: {', '.join(missing_scores)}")
        numeric_scores = {
            resource: _finite_json_number(
                scores[resource],
                path=path,
                row_number=row_number,
                field=f"alternative_scores_json.{resource}",
            )
            for resource in resources
        }
        missing_components = sorted(set(resources) - set(components))
        if missing_components:
            raise ContractError(f"{path}:{row_number}: missing cost components: {', '.join(missing_components)}")
        if any(not isinstance(components[resource], dict) for resource in resources):
            raise ContractError(f"{path}:{row_number}: each cost_components_json entry must be an object")
        if "score_epsilon" not in parameters:
            raise ContractError(f"{path}:{row_number}: parameters_json must include score_epsilon")
        epsilon = _finite_json_number(
            parameters["score_epsilon"],
            path=path,
            row_number=row_number,
            field="parameters_json.score_epsilon",
        )
        if epsilon < 0:
            raise ContractError(f"{path}:{row_number}: score_epsilon must be non-negative")
        parameter_weights: dict[str, float] | None = None
        if policy_name.lower().startswith("ql_heft") or policy_name.lower().replace("-", "_").startswith("aw_heft"):
            parameter_weights = _positive_weight_map(
                parameters.get("weights"),
                path=path,
                row_number=row_number,
                field="parameters_json.weights",
            )
            if set(parameter_weights) != set(resources):
                raise ContractError(
                    f"{path}:{row_number}: parameters_json.weights must cover every allowed resource"
                )
        if numeric_scores[selected] > min(numeric_scores.values()) + epsilon:
            raise ContractError(f"{path}:{row_number}: selected resource does not minimize alternative scores")
        recorded_selected_score = _parse_finite_number(
            row["estimated_cost_ms"],
            path=path,
            row_number=row_number,
            column="estimated_cost_ms",
        )
        if not math.isclose(
            recorded_selected_score,
            numeric_scores[selected],
            rel_tol=1e-9,
            abs_tol=max(epsilon, 1e-9),
        ):
            raise ContractError(
                f"{path}:{row_number}: estimated_cost_ms does not match the selected alternative score"
            )
        if str(row["decision_mode"]) not in {"applied", "shadow"}:
            raise ContractError(f"{path}:{row_number}: decision_mode must be applied or shadow")
        if str(row["policy_version"]) in {"", "unavailable"}:
            raise ContractError(f"{path}:{row_number}: full trace requires policy_version")
        if str(row["tie_break_rule"]) in {"", "unavailable"}:
            raise ContractError(f"{path}:{row_number}: full trace requires tie_break_rule")
        if str(row["reason"]) in {"", "unavailable"}:
            raise ContractError(f"{path}:{row_number}: full trace requires reason")
        if str(row["decision_provenance"]) != "native_scheduler_trace":
            raise ContractError(f"{path}:{row_number}: full trace requires native_scheduler_trace provenance")

        if policy_name.lower().endswith("_frozen") and (update_seq != 0 or update):
            raise ContractError(f"{path}:{row_number}: frozen policy must keep update_seq=0 and update_json empty")
        if sequence_advanced and update_seq != previous_seq + 1:
            raise ContractError(f"{path}:{row_number}: update_seq must advance by one so no update is omitted")
        if sequence_advanced and not update:
            raise ContractError(f"{path}:{row_number}: update_seq advances without a replayable update_json payload")
        if update and not sequence_advanced:
            raise ContractError(f"{path}:{row_number}: update_json is present without an update_seq increment")
        if update:
            required_update_fields = {"reason", "features", "old_weights", "new_weights"}
            if not required_update_fields.issubset(update):
                raise ContractError(f"{path}:{row_number}: update_json lacks features, old/new weights, or reason")
            if not str(update["reason"]).strip():
                raise ContractError(f"{path}:{row_number}: update_json.reason must be non-empty")
            if not isinstance(update["features"], dict) or not update["features"]:
                raise ContractError(f"{path}:{row_number}: update_json.features must be a non-empty object")
            old_weights = _positive_weight_map(
                update["old_weights"],
                path=path,
                row_number=row_number,
                field="update_json.old_weights",
            )
            new_weights = _positive_weight_map(
                update["new_weights"],
                path=path,
                row_number=row_number,
                field="update_json.new_weights",
            )
            if set(old_weights) != set(new_weights):
                raise ContractError(f"{path}:{row_number}: update_json old/new weights must cover the same resources")
            if all(math.isclose(old_weights[resource], new_weights[resource]) for resource in old_weights):
                raise ContractError(f"{path}:{row_number}: update_json must record at least one changed weight")
            if parameter_weights is None:
                parameter_weights = _positive_weight_map(
                    parameters.get("weights"),
                    path=path,
                    row_number=row_number,
                    field="parameters_json.weights",
                )
            if not set(new_weights).issubset(parameter_weights) or any(
                not math.isclose(parameter_weights[resource], new_weights[resource]) for resource in new_weights
            ):
                raise ContractError(f"{path}:{row_number}: parameters_json.weights must match update_json.new_weights")

        previous_update_seq[sequence_key] = update_seq

    result = df.copy()
    result["policy_claim_eligible"] = eligible
    if require_full_trace and not bool(result["policy_claim_eligible"].all()):
        count = int((~result["policy_claim_eligible"]).sum())
        raise ContractError(f"{path} contains {count} decision rows without a replayable full policy trace")
    return result


def _validate_policy_causal_trace_fields(
    df: pd.DataFrame,
    path: Path,
    *,
    require_causal_trace: bool,
) -> pd.DataFrame:
    previous_decision_seq: dict[tuple[str, str], int] = {}
    previous_decision_timestamp: dict[tuple[str, str], float] = {}
    decisions_by_id: dict[str, dict[str, Any]] = {}
    eligible: list[bool] = []

    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        causal_full = str(row["causal_trace_completeness"]) == "full"
        row_eligible = causal_full and bool(row["policy_claim_eligible"])
        eligible.append(row_eligible)
        if not causal_full:
            continue
        if not bool(row["policy_claim_eligible"]):
            raise ContractError(
                f"{path}:{row_number}: causal full trace requires a replayable native engineering trace"
            )

        run_id = str(row["run_id"])
        policy_name = str(row["policy"]).strip()
        sequence_key = (run_id, policy_name)
        decision_id = str(row["decision_id"]).strip()
        if decision_id in {"", "unavailable"}:
            raise ContractError(f"{path}:{row_number}: causal full trace requires decision_id")
        if decision_id in decisions_by_id:
            raise ContractError(f"{path}:{row_number}: duplicate decision_id {decision_id}")

        decision_seq_number = _parse_finite_number(
            row["decision_seq"],
            path=path,
            row_number=row_number,
            column="decision_seq",
        )
        decision_seq = int(decision_seq_number)
        if decision_seq <= 0 or decision_seq_number != decision_seq:
            raise ContractError(f"{path}:{row_number}: decision_seq must be a positive integer")
        previous_seq = previous_decision_seq.get(sequence_key, 0)
        if decision_seq <= previous_seq:
            raise ContractError(
                f"{path}:{row_number}: decision_seq must strictly increase within "
                f"run_id={run_id}, policy={policy_name}"
            )

        decision_timestamp = _parse_finite_number(
            row["decision_timestamp_ms"],
            path=path,
            row_number=row_number,
            column="decision_timestamp_ms",
        )
        if decision_timestamp <= 0:
            raise ContractError(f"{path}:{row_number}: decision_timestamp_ms must be positive")
        if decision_timestamp < previous_decision_timestamp.get(sequence_key, 0.0):
            raise ContractError(
                f"{path}:{row_number}: decision_timestamp_ms must be monotonic within "
                f"run_id={run_id}, policy={policy_name}"
            )

        for column in ("graph_version", "profile_version"):
            if str(row[column]).strip() in {"", "unavailable"}:
                raise ContractError(f"{path}:{row_number}: causal full trace requires {column}")

        feature_provenance = _parse_json_field(
            row["feature_provenance_json"],
            path=path,
            row_number=row_number,
            column="feature_provenance_json",
            expected_type=dict,
        )
        if not feature_provenance:
            raise ContractError(f"{path}:{row_number}: feature_provenance_json must be a non-empty object")
        required_feature_fields = {
            "source",
            "source_trace_id",
            "observed_timestamp_ms",
            "age_ms",
            "estimator_version",
        }
        for feature_name, provenance in feature_provenance.items():
            if not isinstance(provenance, dict) or not required_feature_fields.issubset(provenance):
                raise ContractError(
                    f"{path}:{row_number}: feature_provenance_json.{feature_name} lacks "
                    "source, source_trace_id, observation time, age, or estimator version"
                )
            for field in ("source", "source_trace_id", "estimator_version"):
                if str(provenance[field]).strip() in {"", "unavailable"}:
                    raise ContractError(
                        f"{path}:{row_number}: feature_provenance_json.{feature_name}.{field} must be labeled"
                    )
            observed_timestamp = _finite_json_number(
                provenance["observed_timestamp_ms"],
                path=path,
                row_number=row_number,
                field=f"feature_provenance_json.{feature_name}.observed_timestamp_ms",
            )
            age_ms = _finite_json_number(
                provenance["age_ms"],
                path=path,
                row_number=row_number,
                field=f"feature_provenance_json.{feature_name}.age_ms",
            )
            if observed_timestamp <= 0 or observed_timestamp > decision_timestamp:
                raise ContractError(
                    f"{path}:{row_number}: feature {feature_name} must be observed no later than the decision"
                )
            expected_age = decision_timestamp - observed_timestamp
            if age_ms < 0 or not math.isclose(age_ms, expected_age, rel_tol=1e-9, abs_tol=1e-3):
                raise ContractError(
                    f"{path}:{row_number}: feature {feature_name} age_ms does not match decision time"
                )

        allowed_resources = _parse_json_field(
            row["allowed_resources_json"],
            path=path,
            row_number=row_number,
            column="allowed_resources_json",
            expected_type=list,
        )
        causal_components = _parse_json_field(
            row["cost_components_json"],
            path=path,
            row_number=row_number,
            column="cost_components_json",
            expected_type=dict,
        )
        queue_depth_snapshots: dict[str, float] = {}
        for resource_name in (str(resource).strip().lower() for resource in allowed_resources):
            resource_components = causal_components.get(resource_name)
            if not isinstance(resource_components, dict) or "queue_depth" not in resource_components:
                raise ContractError(
                    f"{path}:{row_number}: causal trace requires decision-time queue_depth "
                    f"for resource {resource_name}"
                )
            queue_depth_snapshots[resource_name] = _finite_json_number(
                resource_components["queue_depth"],
                path=path,
                row_number=row_number,
                field=f"cost_components_json.{resource_name}.queue_depth",
            )
            if queue_depth_snapshots[resource_name] < 0:
                raise ContractError(
                    f"{path}:{row_number}: decision-time queue_depth must be non-negative"
                )

        decision_mode = str(row["decision_mode"])
        terminal_status = str(row["terminal_status"])
        terminal_timestamp = _parse_finite_number(
            row["terminal_timestamp_ms"],
            path=path,
            row_number=row_number,
            column="terminal_timestamp_ms",
        )
        if decision_mode == "applied":
            if terminal_status not in {"completed", "drop", "censored"}:
                raise ContractError(
                    f"{path}:{row_number}: applied causal decision requires completed, drop, or censored status"
                )
            if terminal_timestamp < decision_timestamp:
                raise ContractError(
                    f"{path}:{row_number}: terminal_timestamp_ms precedes the applied decision"
                )
        elif terminal_status != "not_applicable" or terminal_timestamp != 0:
            raise ContractError(
                f"{path}:{row_number}: shadow causal decision must use terminal_status=not_applicable and time 0"
            )

        update = _parse_json_field(
            row["update_json"],
            path=path,
            row_number=row_number,
            column="update_json",
            expected_type=dict,
        )
        update_timestamp = _parse_finite_number(
            row["update_timestamp_ms"],
            path=path,
            row_number=row_number,
            column="update_timestamp_ms",
        )
        source_decision_ids = _parse_json_field(
            row["source_decision_ids_json"],
            path=path,
            row_number=row_number,
            column="source_decision_ids_json",
            expected_type=list,
        )
        first_consumer_id = str(row["first_consumer_decision_id"]).strip()
        first_consumer_seq_number = _parse_finite_number(
            row["first_consumer_decision_seq"],
            path=path,
            row_number=row_number,
            column="first_consumer_decision_seq",
        )
        first_consumer_seq = int(first_consumer_seq_number)
        if first_consumer_seq_number != first_consumer_seq or first_consumer_seq < 0:
            raise ContractError(
                f"{path}:{row_number}: first_consumer_decision_seq must be a non-negative integer"
            )

        if update:
            sources = [str(source_id).strip() for source_id in source_decision_ids]
            if not sources or any(not source_id for source_id in sources) or len(set(sources)) != len(sources):
                raise ContractError(
                    f"{path}:{row_number}: an online update requires unique source_decision_ids_json values"
                )
            if update_timestamp <= 0 or update_timestamp > decision_timestamp:
                raise ContractError(
                    f"{path}:{row_number}: update_timestamp_ms must precede its first consuming decision"
                )
            if first_consumer_id != decision_id or first_consumer_seq != decision_seq:
                raise ContractError(
                    f"{path}:{row_number}: update must identify the current row as its first consuming decision"
                )

            source_traces: set[str] = set()
            source_terminal_statuses: set[str] = set()
            source_terminal_timestamps: set[float] = set()
            source_gpu_queue_depths: list[float] = []
            for source_id in sources:
                source = decisions_by_id.get(source_id)
                if source is None:
                    raise ContractError(
                        f"{path}:{row_number}: update references unknown or non-prior decision_id {source_id}"
                    )
                if source["sequence_key"] != sequence_key or source["decision_mode"] != "applied":
                    raise ContractError(
                        f"{path}:{row_number}: update source {source_id} is not a prior applied decision "
                        "from the same run and policy"
                    )
                if source["terminal_status"] not in {"completed", "drop"}:
                    raise ContractError(
                        f"{path}:{row_number}: censored or unresolved decision {source_id} cannot update policy state"
                    )
                if source["decision_seq"] >= decision_seq or source["terminal_timestamp"] > update_timestamp:
                    raise ContractError(
                        f"{path}:{row_number}: update source {source_id} is not terminal before the update"
                    )
                source_traces.add(source["trace_id"])
                source_terminal_statuses.add(source["terminal_status"])
                source_terminal_timestamps.add(source["terminal_timestamp"])
                if "gpu" in source["queue_depth_snapshots"]:
                    source_gpu_queue_depths.append(source["queue_depth_snapshots"]["gpu"])
            if len(source_traces) != 1:
                raise ContractError(f"{path}:{row_number}: one update must attribute one terminal frame")
            source_trace = next(iter(source_traces))
            full_applied_set = {
                prior_id
                for prior_id, prior in decisions_by_id.items()
                if prior["sequence_key"] == sequence_key
                and prior["trace_id"] == source_trace
                and prior["decision_mode"] == "applied"
            }
            if set(sources) != full_applied_set:
                raise ContractError(
                    f"{path}:{row_number}: update source IDs must cover the full applied decision set "
                    f"for trace_id={source_trace}"
                )
            update_features = update["features"]
            if str(update_features.get("trace_id", "")) != source_trace:
                raise ContractError(
                    f"{path}:{row_number}: update feature trace_id does not match source decisions"
                )
            if len(source_terminal_statuses) != 1 or str(update_features.get("terminal_status", "")) not in source_terminal_statuses:
                raise ContractError(
                    f"{path}:{row_number}: update terminal_status does not match source decisions"
                )
            if len(source_terminal_timestamps) != 1:
                raise ContractError(
                    f"{path}:{row_number}: source decisions disagree on terminal_timestamp_ms"
                )
            feature_terminal_timestamp = _finite_json_number(
                update_features.get("terminal_timestamp_ms"),
                path=path,
                row_number=row_number,
                field="update_json.features.terminal_timestamp_ms",
            )
            if not math.isclose(feature_terminal_timestamp, next(iter(source_terminal_timestamps)), abs_tol=1e-3):
                raise ContractError(
                    f"{path}:{row_number}: update terminal timestamp does not match source decisions"
                )
            if source_gpu_queue_depths:
                feature_gpu_queue_depth = _finite_json_number(
                    update_features.get("gpu_queue_depth"),
                    path=path,
                    row_number=row_number,
                    field="update_json.features.gpu_queue_depth",
                )
                if not math.isclose(feature_gpu_queue_depth, max(source_gpu_queue_depths), abs_tol=1e-9):
                    raise ContractError(
                        f"{path}:{row_number}: update gpu_queue_depth does not match source decision snapshots"
                    )
        elif (
            update_timestamp != 0
            or source_decision_ids
            or first_consumer_id != "unavailable"
            or first_consumer_seq != 0
        ):
            raise ContractError(
                f"{path}:{row_number}: causal update linkage fields are present without update_json"
            )

        decisions_by_id[decision_id] = {
            "sequence_key": sequence_key,
            "trace_id": str(row["trace_id"]),
            "decision_mode": decision_mode,
            "decision_seq": decision_seq,
            "terminal_status": terminal_status,
            "terminal_timestamp": terminal_timestamp,
            "queue_depth_snapshots": queue_depth_snapshots,
        }
        previous_decision_seq[sequence_key] = decision_seq
        previous_decision_timestamp[sequence_key] = decision_timestamp

    result = df.copy()
    result["causal_policy_claim_eligible"] = eligible
    if require_causal_trace and not bool(result["causal_policy_claim_eligible"].all()):
        count = int((~result["causal_policy_claim_eligible"]).sum())
        raise ContractError(f"{path} contains {count} decision rows without a complete causal policy trace")
    return result


def validate_resource_events(path: Path, *, require_labeled_provenance: bool = False) -> pd.DataFrame:
    columns = _select_sidecar_columns(
        path,
        RESOURCE_EVENT_COLUMNS,
        LEGACY_RESOURCE_EVENT_COLUMNS,
        RESOURCE_EVENT_PROVENANCE_COLUMNS,
    )
    df = _validate_native_sidecar(path, columns, RESOURCE_EVENT_NUMERIC_COLUMNS).copy()
    if columns == LEGACY_RESOURCE_EVENT_COLUMNS:
        for column in RESOURCE_EVENT_PROVENANCE_COLUMNS:
            df[column] = _UNLABELED_LEGACY
    _validate_provenance_values(df, path, "time_provenance", _RESOURCE_TIME_PROVENANCE)
    _validate_provenance_values(df, path, "transfer_provenance", _TRANSFER_PROVENANCE)
    _validate_provenance_values(df, path, "nvdec_provenance", _NVDEC_PROVENANCE)
    _validate_provenance_values(df, path, "vram_provenance", _VRAM_PROVENANCE)
    _require_labeled_provenance(
        df,
        path,
        RESOURCE_EVENT_PROVENANCE_COLUMNS,
        require_labeled_provenance,
    )
    return df[RESOURCE_EVENT_COLUMNS]


def validate_policy_decisions(
    path: Path,
    *,
    require_labeled_provenance: bool = False,
    require_full_trace: bool = False,
    require_causal_trace: bool = False,
) -> pd.DataFrame:
    columns = _select_policy_decision_columns(path)
    numeric_columns = POLICY_DECISION_NUMERIC_COLUMNS.intersection(columns)
    df = _validate_native_sidecar(path, columns, numeric_columns).copy()
    if columns == LEGACY_POLICY_DECISION_COLUMNS:
        for column in POLICY_DECISION_PROVENANCE_COLUMNS:
            df[column] = _UNLABELED_LEGACY
    if columns not in (ENGINEERING_POLICY_DECISION_COLUMNS, POLICY_DECISION_COLUMNS):
        trace_defaults: dict[str, Any] = {
            "policy_version": "unavailable",
            "allowed_resources_json": "[]",
            "alternative_scores_json": "{}",
            "cost_components_json": "{}",
            "parameters_json": "{}",
            "tie_break_rule": "unavailable",
            "decision_mode": "applied",
            "update_seq": 0,
            "update_json": "{}",
            "reason": "unavailable",
        }
        for column, value in trace_defaults.items():
            df[column] = value
    if columns != POLICY_DECISION_COLUMNS:
        causal_defaults: dict[str, Any] = {
            "decision_id": "unavailable",
            "decision_seq": 0,
            "decision_timestamp_ms": 0.0,
            "graph_version": "unavailable",
            "profile_version": "unavailable",
            "feature_provenance_json": "{}",
            "terminal_status": "unavailable",
            "terminal_timestamp_ms": 0.0,
            "update_timestamp_ms": 0.0,
            "source_decision_ids_json": "[]",
            "first_consumer_decision_id": "unavailable",
            "first_consumer_decision_seq": 0,
            "causal_trace_completeness": "not_available",
        }
        for column, value in causal_defaults.items():
            df[column] = value
    _validate_provenance_values(df, path, "decision_provenance", _DECISION_PROVENANCE)
    _validate_provenance_values(df, path, "trace_completeness", _TRACE_COMPLETENESS)
    _validate_provenance_values(
        df,
        path,
        "causal_trace_completeness",
        _CAUSAL_TRACE_COMPLETENESS,
    )
    _validate_provenance_values(df, path, "terminal_status", _TERMINAL_STATUSES)
    _require_labeled_provenance(
        df,
        path,
        POLICY_DECISION_PROVENANCE_COLUMNS,
        require_labeled_provenance,
    )
    replay_validated = _validate_policy_trace_fields(
        df[POLICY_DECISION_COLUMNS],
        path,
        require_full_trace=require_full_trace,
    )
    return _validate_policy_causal_trace_fields(
        replay_validated,
        path,
        require_causal_trace=require_causal_trace,
    )


def validate_policy_feedback(
    path: Path,
    *,
    decisions: pd.DataFrame,
    require_complete: bool = False,
) -> pd.DataFrame:
    df = _validate_native_sidecar(path, POLICY_FEEDBACK_COLUMNS, POLICY_FEEDBACK_NUMERIC_COLUMNS).copy()
    _validate_provenance_values(df, path, "feedback_provenance", _FEEDBACK_PROVENANCE)
    _validate_provenance_values(
        df,
        path,
        "feedback_trace_completeness",
        _FEEDBACK_TRACE_COMPLETENESS,
    )
    initial_eligible = df["feedback_trace_completeness"].astype(str) == "full"
    if not bool(initial_eligible.any()):
        result = df.copy()
        result["policy_feedback_claim_eligible"] = False
        if require_complete:
            raise ContractError(f"{path} contains no complete online policy feedback rows")
        return result

    decision_path = path.parent / "policy_decisions.csv"
    online_decisions = decisions[
        decisions["policy"].astype(str).str.lower().str.endswith("_online")
    ].copy()
    if online_decisions.empty:
        raise ContractError(f"{path}: policy feedback requires online policy decisions")
    if not bool(online_decisions["causal_policy_claim_eligible"].all()):
        raise ContractError(f"{path}: full feedback validation requires complete causal policy decisions")

    configs, version_weights = _policy_feedback_parameters(online_decisions, path=decision_path)
    decisions_by_id: dict[str, dict[str, Any]] = {}
    applied_by_trace: dict[tuple[str, str, str], set[str]] = {}
    for row_index, row in online_decisions.iterrows():
        row_number = int(row_index) + 2
        decision_id = str(row["decision_id"]).strip()
        key = (str(row["run_id"]), str(row["policy"]).strip())
        trace_id = str(row["trace_id"])
        parameters = _parse_json_field(
            row["parameters_json"],
            path=decision_path,
            row_number=row_number,
            column="parameters_json",
            expected_type=dict,
        )
        decisions_by_id[decision_id] = {
            "key": key,
            "trace_id": trace_id,
            "decision_seq": int(float(row["decision_seq"])),
            "decision_timestamp": float(row["decision_timestamp_ms"]),
            "terminal_status": str(row["terminal_status"]),
            "terminal_timestamp": float(row["terminal_timestamp_ms"]),
            "snapshot_seq": int(float(row["update_seq"])),
            "decision_mode": str(row["decision_mode"]),
            "weights": _positive_weight_map(
                parameters["weights"],
                path=decision_path,
                row_number=row_number,
                field="parameters_json.weights",
            ),
            "update": _parse_json_field(
                row["update_json"],
                path=decision_path,
                row_number=row_number,
                column="update_json",
                expected_type=dict,
            ),
            "source_ids": _parse_json_field(
                row["source_decision_ids_json"],
                path=decision_path,
                row_number=row_number,
                column="source_decision_ids_json",
                expected_type=list,
            ),
        }
        if str(row["decision_mode"]) == "applied":
            applied_by_trace.setdefault((*key, trace_id), set()).add(decision_id)

    expected_feedback_seq: dict[tuple[str, str], int] = {}
    previous_feedback_timestamp: dict[tuple[str, str], float] = {}
    current_update_seq: dict[tuple[str, str], int] = {}
    last_update_feedback_seq: dict[tuple[str, str], int] = {}
    current_variation: dict[tuple[str, str], float] = {}
    current_weights: dict[tuple[str, str], dict[str, float]] = {}
    seen_traces: set[tuple[str, str, str]] = set()
    feedback_consumers: set[str] = set()
    eligible: list[bool] = []

    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        full = str(row["feedback_trace_completeness"]) == "full"
        row_eligible = full and str(row["feedback_provenance"]) == "native_terminal_feedback"
        eligible.append(row_eligible)
        if not full:
            continue

        key = (str(row["run_id"]), str(row["policy"]).strip())
        if key not in configs or not key[1].lower().endswith("_online"):
            raise ContractError(f"{path}:{row_number}: feedback row has no matching online policy trace")
        config = configs[key]
        expected_seq = expected_feedback_seq.get(key, 1)
        feedback_seq = int(float(row["feedback_seq"]))
        if float(row["feedback_seq"]) != feedback_seq or feedback_seq != expected_seq:
            raise ContractError(f"{path}:{row_number}: feedback_seq must be gap-free and start at one")
        expected_feedback_seq[key] = expected_seq + 1

        source_trace_id = str(row["source_trace_id"]).strip()
        trace_key = (*key, source_trace_id)
        if trace_key in seen_traces:
            raise ContractError(f"{path}:{row_number}: terminal trace has more than one feedback event")
        source_ids_raw = _parse_json_field(
            row["source_decision_ids_json"],
            path=path,
            row_number=row_number,
            column="source_decision_ids_json",
            expected_type=list,
        )
        source_ids = [str(value).strip() for value in source_ids_raw]
        if not source_ids or any(not value for value in source_ids) or len(set(source_ids)) != len(source_ids):
            raise ContractError(f"{path}:{row_number}: feedback requires unique source decision IDs")
        if set(source_ids) != applied_by_trace.get(trace_key, set()):
            raise ContractError(f"{path}:{row_number}: feedback source IDs must cover the full applied trace")
        unknown_sources = [source_id for source_id in source_ids if source_id not in decisions_by_id]
        if unknown_sources:
            raise ContractError(f"{path}:{row_number}: feedback references unknown decision IDs")
        sources = [decisions_by_id[source_id] for source_id in source_ids]
        if any(source["key"] != key or source["trace_id"] != source_trace_id for source in sources):
            raise ContractError(f"{path}:{row_number}: feedback sources cross a run, policy, or trace boundary")
        source_statuses = {source["terminal_status"] for source in sources}
        source_terminal_times = {source["terminal_timestamp"] for source in sources}
        terminal_status = str(row["terminal_status"])
        terminal_timestamp = float(row["terminal_timestamp_ms"])
        if source_statuses != {terminal_status} or len(source_terminal_times) != 1:
            raise ContractError(f"{path}:{row_number}: feedback terminal state disagrees with source decisions")
        if not math.isclose(terminal_timestamp, next(iter(source_terminal_times)), abs_tol=1e-3):
            raise ContractError(f"{path}:{row_number}: feedback terminal timestamp disagrees with source decisions")
        feedback_timestamp = float(row["feedback_timestamp_ms"])
        if feedback_timestamp < terminal_timestamp:
            raise ContractError(f"{path}:{row_number}: feedback_timestamp_ms precedes terminal completion")
        if feedback_timestamp < previous_feedback_timestamp.get(key, 0.0):
            raise ContractError(f"{path}:{row_number}: feedback timestamps must follow feedback_seq order")
        previous_feedback_timestamp[key] = feedback_timestamp

        source_snapshot = min(source["snapshot_seq"] for source in sources)
        recorded_source_snapshot = int(float(row["source_parameter_snapshot_seq"]))
        if float(row["source_parameter_snapshot_seq"]) != recorded_source_snapshot or recorded_source_snapshot != source_snapshot:
            raise ContractError(
                f"{path}:{row_number}: oldest source parameter snapshot does not match source decisions"
            )
        pre_update_seq = current_update_seq.get(key, 0)
        lag = pre_update_seq - source_snapshot
        if lag < 0 or float(row["parameter_lag"]) != lag:
            raise ContractError(f"{path}:{row_number}: parameter_lag does not match feedback ordering")
        since_update = feedback_seq - last_update_feedback_seq.get(key, 0)
        if float(row["events_since_update"]) != since_update:
            raise ContractError(f"{path}:{row_number}: events_since_update does not match feedback_seq")

        initial_weights = version_weights.get((*key, 0))
        if initial_weights is None:
            raise ContractError(f"{path}:{row_number}: online trace has no parameter snapshot version zero")
        state_weights = current_weights.setdefault(key, initial_weights)
        old_weights = _positive_weight_map(
            _parse_json_field(
                row["old_weights_json"], path=path, row_number=row_number,
                column="old_weights_json", expected_type=dict,
            ),
            path=path, row_number=row_number, field="old_weights_json",
        )
        raw_weights = _finite_weight_map(
            _parse_json_field(
                row["raw_weights_json"], path=path, row_number=row_number,
                column="raw_weights_json", expected_type=dict,
            ),
            path=path, row_number=row_number, field="raw_weights_json",
        )
        projected_weights = _positive_weight_map(
            _parse_json_field(
                row["projected_weights_json"], path=path, row_number=row_number,
                column="projected_weights_json", expected_type=dict,
            ),
            path=path, row_number=row_number, field="projected_weights_json",
        )
        lower = _positive_weight_map(
            _parse_json_field(
                row["weight_lower_bounds_json"], path=path, row_number=row_number,
                column="weight_lower_bounds_json", expected_type=dict,
            ),
            path=path, row_number=row_number, field="weight_lower_bounds_json",
        )
        upper = _positive_weight_map(
            _parse_json_field(
                row["weight_upper_bounds_json"], path=path, row_number=row_number,
                column="weight_upper_bounds_json", expected_type=dict,
            ),
            path=path, row_number=row_number, field="weight_upper_bounds_json",
        )
        if not _weight_maps_close(old_weights, state_weights):
            raise ContractError(f"{path}:{row_number}: old weights do not match the current policy state")
        if not _weight_maps_close(lower, config["lower"]) or not _weight_maps_close(upper, config["upper"]):
            raise ContractError(f"{path}:{row_number}: feedback bounds differ from the frozen policy passport")
        if str(row["projection_rule"]) != config["projection_rule"]:
            raise ContractError(f"{path}:{row_number}: feedback projection rule differs from the policy passport")
        if set(raw_weights) != set(old_weights) or set(projected_weights) != set(old_weights):
            raise ContractError(f"{path}:{row_number}: feedback weight maps cover different resources")
        expected_projection = _project_weights_to_box_mean_one(raw_weights, lower, upper)
        if not _weight_maps_close(projected_weights, expected_projection, tolerance=1e-8):
            raise ContractError(f"{path}:{row_number}: projected weights do not match deterministic projection")
        if not math.isclose(sum(projected_weights.values()), float(len(projected_weights)), abs_tol=1e-8):
            raise ContractError(f"{path}:{row_number}: projected weights must have arithmetic mean one")

        features = _parse_json_field(
            row["feedback_features_json"],
            path=path,
            row_number=row_number,
            column="feedback_features_json",
            expected_type=dict,
        )
        if not features:
            raise ContractError(f"{path}:{row_number}: feedback_features_json must be non-empty")
        required_feedback_features = {"trace_id", "terminal_status", "terminal_timestamp_ms"}
        if not required_feedback_features.issubset(features):
            raise ContractError(f"{path}:{row_number}: feedback features lack terminal trace attribution")
        if str(features["trace_id"]) != source_trace_id or str(features["terminal_status"]) != terminal_status:
            raise ContractError(f"{path}:{row_number}: feedback features disagree with terminal source")
        feature_terminal_timestamp = _finite_json_number(
            features["terminal_timestamp_ms"],
            path=path,
            row_number=row_number,
            field="feedback_features_json.terminal_timestamp_ms",
        )
        if not math.isclose(feature_terminal_timestamp, terminal_timestamp, abs_tol=1e-3):
            raise ContractError(f"{path}:{row_number}: feedback feature timestamp disagrees with terminal source")
        action = str(row["feedback_action"])
        reason = str(row["reason"]).strip()
        if action not in {"update", "no_op"} or not reason:
            raise ContractError(f"{path}:{row_number}: feedback action or reason is invalid")
        variation_before = float(row["variation_before"])
        variation_after = float(row["variation_after"])
        variation_budget = float(row["variation_budget"])
        expected_before = current_variation.get(key, 0.0)
        if not math.isclose(variation_before, expected_before, abs_tol=1e-9):
            raise ContractError(f"{path}:{row_number}: variation_before does not match prior feedback")
        if not math.isclose(variation_budget, config["variation_budget"], abs_tol=1e-9):
            raise ContractError(f"{path}:{row_number}: variation budget differs from the policy passport")
        candidate_variation = sum(abs(projected_weights[r] - old_weights[r]) for r in old_weights)
        expected_after = variation_before + (candidate_variation if action == "update" else 0.0)
        if not math.isclose(variation_after, expected_after, abs_tol=1e-8) or variation_after > variation_budget + 1e-9:
            raise ContractError(f"{path}:{row_number}: variation accounting violates the configured budget")

        update_seq = int(float(row["update_seq"]))
        consumer_id = str(row["first_consumer_decision_id"]).strip()
        consumer_seq = int(float(row["first_consumer_decision_seq"]))
        if action == "update":
            if terminal_status == "censored" or lag > config["lag_limit"] or since_update < config["cooldown"]:
                raise ContractError(f"{path}:{row_number}: feedback update violates status, lag, or cooldown gate")
            if candidate_variation <= 1e-12 or variation_after > variation_budget + 1e-9:
                raise ContractError(f"{path}:{row_number}: feedback update has no admissible bounded change")
            if update_seq != pre_update_seq + 1:
                raise ContractError(f"{path}:{row_number}: update_seq must advance exactly once for an update")
            consumer = decisions_by_id.get(consumer_id)
            if consumer is None or consumer["key"] != key or consumer["decision_seq"] != consumer_seq:
                raise ContractError(f"{path}:{row_number}: update has no matching first consumer decision")
            if consumer["snapshot_seq"] != update_seq or consumer["decision_timestamp"] < feedback_timestamp:
                raise ContractError(f"{path}:{row_number}: first consumer does not use the updated snapshot")
            if consumer_id in feedback_consumers:
                raise ContractError(f"{path}:{row_number}: first consumer is linked to multiple feedback updates")
            consumer_update = consumer["update"]
            if not consumer_update or set(consumer["source_ids"]) != set(source_ids):
                raise ContractError(f"{path}:{row_number}: decision update linkage disagrees with feedback sidecar")
            consumer_old = _positive_weight_map(
                consumer_update.get("old_weights"),
                path=decision_path,
                row_number=consumer_seq + 1,
                field="update_json.old_weights",
            )
            consumer_new = _positive_weight_map(
                consumer_update.get("new_weights"),
                path=decision_path,
                row_number=consumer_seq + 1,
                field="update_json.new_weights",
            )
            if not _weight_maps_close(consumer_old, old_weights) or not _weight_maps_close(consumer_new, projected_weights):
                raise ContractError(f"{path}:{row_number}: decision update weights disagree with feedback sidecar")
            snapshot_weights = version_weights.get((*key, update_seq))
            if snapshot_weights is None or not _weight_maps_close(snapshot_weights, projected_weights):
                raise ContractError(f"{path}:{row_number}: updated parameter snapshot is missing or inconsistent")
            feedback_consumers.add(consumer_id)
            current_update_seq[key] = update_seq
            last_update_feedback_seq[key] = feedback_seq
            current_variation[key] = variation_after
            current_weights[key] = projected_weights
        else:
            if update_seq != pre_update_seq or consumer_id != "unavailable" or consumer_seq != 0:
                raise ContractError(f"{path}:{row_number}: no-op feedback must not change state or name a consumer")
            expected_reason = None
            if terminal_status == "censored":
                expected_reason = "censored_feedback"
            elif lag > config["lag_limit"]:
                expected_reason = "stale_feedback"
            elif since_update < config["cooldown"]:
                expected_reason = "cooldown_active"
            elif candidate_variation <= 1e-12:
                expected_reason = "no_weight_update"
            elif variation_before + candidate_variation > variation_budget + 1e-9:
                expected_reason = "variation_budget_exhausted"
            elif reason != "no_subsequent_decision_before_end":
                raise ContractError(f"{path}:{row_number}: eligible bounded update was recorded as an unexplained no-op")
            if expected_reason is not None and reason != expected_reason:
                raise ContractError(f"{path}:{row_number}: no-op reason does not match the first failed feedback gate")
            current_variation[key] = variation_after
        seen_traces.add(trace_key)

    result = df.copy()
    result["policy_feedback_claim_eligible"] = eligible
    complete = bool(result["policy_feedback_claim_eligible"].all())
    if complete:
        expected_traces = {
            trace_key
            for trace_key in applied_by_trace
            if trace_key[:2] in configs
        }
        if seen_traces != expected_traces:
            raise ContractError(f"{path}: full feedback trace must cover every terminal applied trace exactly once")
        decision_update_consumers = {
            decision_id
            for decision_id, decision in decisions_by_id.items()
            if decision["update"]
        }
        if feedback_consumers != decision_update_consumers:
            raise ContractError(f"{path}: feedback updates and decision update consumers are not one-to-one")
    if require_complete and not complete:
        count = int((~result["policy_feedback_claim_eligible"]).sum())
        raise ContractError(f"{path} contains {count} feedback rows without a complete online policy trace")
    return result


def _proxy_replay_number(
    value: Any,
    *,
    field: str,
    blockers: list[str],
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        blockers.append(f"{field}:not_numeric")
        return None
    if not math.isfinite(number):
        blockers.append(f"{field}:not_finite")
        return None
    return number


def _proxy_replay_json(
    value: Any,
    *,
    field: str,
    expected_type: type,
    blockers: list[str],
) -> Any | None:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        blockers.append(f"{field}:invalid_json")
        return None
    if not isinstance(parsed, expected_type):
        blockers.append(f"{field}:wrong_json_type")
        return None
    return parsed


def _proxy_replay_close(left: float, right: float, *, tolerance: float = 1e-9) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=tolerance)


def _primary_proxy_runtime_artifact_blockers(
    metadata: dict[str, Any] | None,
    *,
    arm: str,
    expected_path: str,
    expected_sha256: str,
) -> list[str]:
    prefix = f"{arm}:runtime_metadata"
    if not isinstance(metadata, dict):
        return [f"{prefix}:missing"]
    blockers: list[str] = []
    if str(metadata.get("mode", "")) != "benchmark":
        blockers.append(f"{prefix}:mode_not_benchmark")
    artifact = metadata.get("ql_heft_policy_artifact")
    if not isinstance(artifact, dict):
        blockers.append(f"{prefix}:policy_artifact_identity_missing")
        return blockers
    if str(artifact.get("path", "")) != expected_path:
        blockers.append(f"{prefix}:policy_artifact_path_mismatch")
    if str(artifact.get("sha256", "")).lower() != expected_sha256:
        blockers.append(f"{prefix}:policy_artifact_sha256_mismatch")
    return blockers


def _primary_proxy_decision_replay(
    decisions: pd.DataFrame,
    *,
    arm: str,
    policy: str,
    version: str,
    passport: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    required_columns = set(POLICY_DECISION_COLUMNS) | {
        "policy_claim_eligible",
        "causal_policy_claim_eligible",
    }
    missing_columns = sorted(required_columns - set(decisions.columns))
    if missing_columns:
        return {
            "passed": False,
            "decision_count": int(decisions.shape[0]),
            "replayed_decision_count": 0,
            "blockers": [f"{arm}:missing_columns:{','.join(missing_columns)}"],
        }
    if decisions.empty:
        return {
            "passed": False,
            "decision_count": 0,
            "replayed_decision_count": 0,
            "blockers": [f"{arm}:no_policy_decisions"],
        }
    if not bool(decisions["policy_claim_eligible"].all()):
        blockers.append(f"{arm}:policy_trace_incomplete")
    if not bool(decisions["causal_policy_claim_eligible"].all()):
        blockers.append(f"{arm}:causal_policy_trace_incomplete")
    if set(decisions["policy"].astype(str)) != {policy}:
        blockers.append(f"{arm}:policy_id_mismatch")
    if set(decisions["policy_version"].astype(str)) != {version}:
        blockers.append(f"{arm}:policy_version_mismatch")
    if set(decisions["decision_mode"].astype(str)) != {"applied"}:
        blockers.append(f"{arm}:decision_mode_not_applied")

    resources = [str(value) for value in passport["resource_scope"]]
    expected_resource_set = set(resources)
    expected_initial_weights = {
        resource: float(passport["initial_weights"][resource]) for resource in resources
    }
    expected_lower = {resource: float(passport["weight_lower_bound"]) for resource in resources}
    expected_upper = {resource: float(passport["weight_upper_bound"]) for resource in resources}
    replayed = 0
    saw_initial_snapshot = False

    for position, (_, row) in enumerate(decisions.iterrows(), start=2):
        row_prefix = f"{arm}:decision_row_{position}"
        row_blocker_count = len(blockers)
        allowed = _proxy_replay_json(
            row["allowed_resources_json"],
            field=f"{row_prefix}:allowed_resources_json",
            expected_type=list,
            blockers=blockers,
        )
        scores = _proxy_replay_json(
            row["alternative_scores_json"],
            field=f"{row_prefix}:alternative_scores_json",
            expected_type=dict,
            blockers=blockers,
        )
        components = _proxy_replay_json(
            row["cost_components_json"],
            field=f"{row_prefix}:cost_components_json",
            expected_type=dict,
            blockers=blockers,
        )
        parameters = _proxy_replay_json(
            row["parameters_json"],
            field=f"{row_prefix}:parameters_json",
            expected_type=dict,
            blockers=blockers,
        )
        if any(value is None for value in (allowed, scores, components, parameters)):
            continue

        normalized_allowed = [str(value).strip().lower() for value in allowed]
        if normalized_allowed != resources:
            blockers.append(f"{row_prefix}:resource_scope_mismatch")
        if set(scores) != expected_resource_set:
            blockers.append(f"{row_prefix}:alternative_score_scope_mismatch")
        if set(components) != expected_resource_set:
            blockers.append(f"{row_prefix}:cost_component_scope_mismatch")
        if str(row["tie_break_rule"]) != str(passport["tie_break_rule"]):
            blockers.append(f"{row_prefix}:tie_break_rule_mismatch")

        required_parameters = {
            "score_epsilon",
            "weights",
            "weight_lower_bounds",
            "weight_upper_bounds",
            "projection_rule",
            "feedback_lag_limit",
            "feedback_cooldown_events",
            "variation_budget",
            "feedback_update_rule",
            "feedback_update_parameters",
            "heavy_gpu_bonus",
            "heavy_object_threshold",
            "heavy_scene",
            "stage_preference",
            "policy_scope",
        }
        missing_parameters = sorted(required_parameters - set(parameters))
        if missing_parameters:
            blockers.append(f"{row_prefix}:passport_fields_missing:{','.join(missing_parameters)}")
            continue
        weights_raw = parameters.get("weights")
        lower_raw = parameters.get("weight_lower_bounds")
        upper_raw = parameters.get("weight_upper_bounds")
        if not all(isinstance(value, dict) for value in (weights_raw, lower_raw, upper_raw)):
            blockers.append(f"{row_prefix}:weight_maps_invalid")
            continue
        if set(weights_raw) != expected_resource_set:
            blockers.append(f"{row_prefix}:weight_scope_mismatch")
            continue
        weights: dict[str, float] = {}
        for resource in resources:
            weight = _proxy_replay_number(
                weights_raw.get(resource),
                field=f"{row_prefix}:weights.{resource}",
                blockers=blockers,
            )
            if weight is not None:
                weights[resource] = weight
        if len(weights) != len(resources):
            continue
        try:
            update_seq = int(float(row["update_seq"]))
        except (TypeError, ValueError):
            blockers.append(f"{row_prefix}:update_seq_invalid")
            continue
        if float(row["update_seq"]) != update_seq or update_seq < 0:
            blockers.append(f"{row_prefix}:update_seq_invalid")
            continue
        if update_seq == 0:
            saw_initial_snapshot = True
            if not _weight_maps_close(weights, expected_initial_weights):
                blockers.append(f"{row_prefix}:initial_weights_mismatch")
        if arm == "frozen" and not _weight_maps_close(weights, expected_initial_weights):
            blockers.append(f"{row_prefix}:frozen_weights_changed")
        observed_lower: dict[str, float] = {}
        observed_upper: dict[str, float] = {}
        for resource in resources:
            lower_value = _proxy_replay_number(
                lower_raw.get(resource),
                field=f"{row_prefix}:weight_lower_bounds.{resource}",
                blockers=blockers,
            )
            upper_value = _proxy_replay_number(
                upper_raw.get(resource),
                field=f"{row_prefix}:weight_upper_bounds.{resource}",
                blockers=blockers,
            )
            if lower_value is not None:
                observed_lower[resource] = lower_value
            if upper_value is not None:
                observed_upper[resource] = upper_value
        if not _weight_maps_close(observed_lower, expected_lower):
            blockers.append(f"{row_prefix}:weight_lower_bounds_mismatch")
        if not _weight_maps_close(observed_upper, expected_upper):
            blockers.append(f"{row_prefix}:weight_upper_bounds_mismatch")

        scalar_expectations = {
            "projection_rule": passport["projection_rule"],
            "feedback_lag_limit": passport["feedback_lag_limit"],
            "feedback_cooldown_events": passport["feedback_cooldown_events"],
            "feedback_update_rule": passport["feedback_update_rule"],
            "heavy_object_threshold": passport["heavy_object_threshold"],
            "policy_scope": "simplified_cpu_gpu_queue_weighted_proxy",
        }
        for field, expected in scalar_expectations.items():
            if parameters.get(field) != expected:
                blockers.append(f"{row_prefix}:{field}_mismatch")
        numeric_expectations = {
            "score_epsilon": passport["score_epsilon"],
            "variation_budget": passport["variation_budget"],
            "heavy_gpu_bonus": passport["heavy_gpu_bonus"],
        }
        for field, expected in numeric_expectations.items():
            observed = _proxy_replay_number(
                parameters.get(field),
                field=f"{row_prefix}:{field}",
                blockers=blockers,
            )
            if observed is not None and not _proxy_replay_close(observed, float(expected)):
                blockers.append(f"{row_prefix}:{field}_mismatch")
        expected_update_parameters = {
            "penalty_step": float(passport["feedback_penalty_step"]),
            "reward_step": float(passport["feedback_reward_step"]),
        }
        update_parameters = parameters.get("feedback_update_parameters")
        if not isinstance(update_parameters, dict) or set(update_parameters) != set(expected_update_parameters):
            blockers.append(f"{row_prefix}:feedback_update_parameters_mismatch")
        else:
            for field, expected in expected_update_parameters.items():
                observed = _proxy_replay_number(
                    update_parameters[field],
                    field=f"{row_prefix}:feedback_update_parameters.{field}",
                    blockers=blockers,
                )
                if observed is not None and not _proxy_replay_close(observed, expected):
                    blockers.append(f"{row_prefix}:feedback_update_parameters.{field}_mismatch")

        heavy_scene = parameters.get("heavy_scene")
        if not isinstance(heavy_scene, bool):
            blockers.append(f"{row_prefix}:heavy_scene_not_boolean")
            continue
        stage_preference = str(parameters.get("stage_preference", "")).strip().lower()
        if stage_preference not in expected_resource_set:
            blockers.append(f"{row_prefix}:stage_preference_invalid")
            continue
        heavy_bonus = float(passport["heavy_gpu_bonus"])
        expected_component_keys = {
            "profile_exec_proxy_ms",
            "object_multiplier",
            "queue_depth",
            "active_tasks",
            "queue_wait_proxy_ms",
            "weight",
            "heavy_multiplier",
        }
        numeric_scores: dict[str, float] = {}
        queue_depths: dict[str, int] = {}
        for resource in resources:
            component = components.get(resource)
            if not isinstance(component, dict) or set(component) != expected_component_keys:
                blockers.append(f"{row_prefix}:{resource}_component_contract_mismatch")
                continue
            values: dict[str, float] = {}
            for field in expected_component_keys:
                value = _proxy_replay_number(
                    component.get(field),
                    field=f"{row_prefix}:{resource}.{field}",
                    blockers=blockers,
                )
                if value is not None:
                    values[field] = value
            if len(values) != len(expected_component_keys):
                continue
            queue_depth = int(values["queue_depth"])
            active_tasks = int(values["active_tasks"])
            if values["queue_depth"] != queue_depth or queue_depth < 0:
                blockers.append(f"{row_prefix}:{resource}_queue_depth_invalid")
                continue
            if values["active_tasks"] != active_tasks or active_tasks < 0:
                blockers.append(f"{row_prefix}:{resource}_active_tasks_invalid")
                continue
            queue_depths[resource] = queue_depth
            if not _proxy_replay_close(values["weight"], weights[resource]):
                blockers.append(f"{row_prefix}:{resource}_component_weight_mismatch")
            expected_heavy_multiplier = (
                1.0 / heavy_bonus if resource == "gpu" and heavy_scene else 1.0
            )
            if not _proxy_replay_close(values["heavy_multiplier"], expected_heavy_multiplier):
                blockers.append(f"{row_prefix}:{resource}_heavy_multiplier_mismatch")
            expected_wait = (
                (queue_depth + active_tasks)
                * values["profile_exec_proxy_ms"]
                * values["object_multiplier"]
            )
            if not _proxy_replay_close(
                values["queue_wait_proxy_ms"],
                expected_wait,
                tolerance=1e-8,
            ):
                blockers.append(f"{row_prefix}:{resource}_queue_wait_proxy_mismatch")
            expected_score = (
                (queue_depth + active_tasks + 1.0)
                * values["profile_exec_proxy_ms"]
                * values["object_multiplier"]
                * weights[resource]
                * expected_heavy_multiplier
            )
            score = _proxy_replay_number(
                scores.get(resource),
                field=f"{row_prefix}:score.{resource}",
                blockers=blockers,
            )
            if score is not None:
                numeric_scores[resource] = score
                epsilon = max(float(passport["score_epsilon"]), 1e-9)
                if not _proxy_replay_close(score, expected_score, tolerance=epsilon):
                    blockers.append(f"{row_prefix}:{resource}_score_replay_mismatch")

        if set(numeric_scores) != expected_resource_set or set(queue_depths) != expected_resource_set:
            continue
        epsilon = float(passport["score_epsilon"])
        cpu_score = numeric_scores["cpu"]
        gpu_score = numeric_scores["gpu"]
        if cpu_score + epsilon < gpu_score:
            expected_resource = "cpu"
            expected_reason = "minimum_weighted_proxy_score"
        elif gpu_score + epsilon < cpu_score:
            expected_resource = "gpu"
            expected_reason = "minimum_weighted_proxy_score"
        elif queue_depths["cpu"] < queue_depths["gpu"]:
            expected_resource = "cpu"
            expected_reason = "score_tie_lower_queue_depth"
        elif queue_depths["gpu"] < queue_depths["cpu"]:
            expected_resource = "gpu"
            expected_reason = "score_tie_lower_queue_depth"
        else:
            expected_resource = stage_preference
            expected_reason = "score_tie_stage_preference"
        selected = str(row["resource"]).strip().lower()
        if selected != expected_resource:
            blockers.append(f"{row_prefix}:selected_resource_replay_mismatch")
        if str(row["reason"]) != expected_reason:
            blockers.append(f"{row_prefix}:decision_reason_replay_mismatch")
        if str(row["decision"]) != f"{policy}:{selected}":
            blockers.append(f"{row_prefix}:decision_label_mismatch")
        selected_score = _proxy_replay_number(
            row["estimated_cost_ms"],
            field=f"{row_prefix}:estimated_cost_ms",
            blockers=blockers,
        )
        if selected_score is not None and not _proxy_replay_close(
            selected_score,
            numeric_scores[selected],
            tolerance=max(epsilon, 1e-9),
        ):
            blockers.append(f"{row_prefix}:selected_score_replay_mismatch")
        selected_queue_depth = _proxy_replay_number(
            row["queue_depth"],
            field=f"{row_prefix}:queue_depth",
            blockers=blockers,
        )
        if selected_queue_depth is not None and selected_queue_depth != queue_depths[selected]:
            blockers.append(f"{row_prefix}:selected_queue_depth_mismatch")
        if len(blockers) == row_blocker_count:
            replayed += 1

    if not saw_initial_snapshot:
        blockers.append(f"{arm}:initial_parameter_snapshot_missing")
    blockers = list(dict.fromkeys(blockers))
    return {
        "passed": not blockers and replayed == int(decisions.shape[0]),
        "decision_count": int(decisions.shape[0]),
        "replayed_decision_count": replayed,
        "blockers": blockers,
    }


def _primary_proxy_feedback_replay(
    feedback: pd.DataFrame,
    *,
    passport: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    required_columns = set(POLICY_FEEDBACK_COLUMNS) | {"policy_feedback_claim_eligible"}
    missing_columns = sorted(required_columns - set(feedback.columns))
    if missing_columns:
        return {
            "passed": False,
            "feedback_count": int(feedback.shape[0]),
            "replayed_feedback_count": 0,
            "blockers": [f"online_feedback:missing_columns:{','.join(missing_columns)}"],
        }
    if feedback.empty:
        return {
            "passed": False,
            "feedback_count": 0,
            "replayed_feedback_count": 0,
            "blockers": ["online_feedback:no_feedback_rows"],
        }
    if not bool(feedback["policy_feedback_claim_eligible"].all()):
        blockers.append("online_feedback:trace_incomplete")
    if set(feedback["policy"].astype(str)) != {"ql_heft_online"}:
        blockers.append("online_feedback:policy_id_mismatch")

    replayed = 0
    penalty = float(passport["feedback_penalty_step"])
    reward = float(passport["feedback_reward_step"])
    for position, (_, row) in enumerate(feedback.iterrows(), start=2):
        prefix = f"online_feedback:row_{position}"
        row_blocker_count = len(blockers)
        features = _proxy_replay_json(
            row["feedback_features_json"],
            field=f"{prefix}:feedback_features_json",
            expected_type=dict,
            blockers=blockers,
        )
        old_weights_raw = _proxy_replay_json(
            row["old_weights_json"],
            field=f"{prefix}:old_weights_json",
            expected_type=dict,
            blockers=blockers,
        )
        raw_weights_raw = _proxy_replay_json(
            row["raw_weights_json"],
            field=f"{prefix}:raw_weights_json",
            expected_type=dict,
            blockers=blockers,
        )
        projected_weights_raw = _proxy_replay_json(
            row["projected_weights_json"],
            field=f"{prefix}:projected_weights_json",
            expected_type=dict,
            blockers=blockers,
        )
        if any(
            value is None
            for value in (features, old_weights_raw, raw_weights_raw, projected_weights_raw)
        ):
            continue
        required_features = {"latency_ms", "deadline_ms", "gpu_queue_depth"}
        if not required_features.issubset(features):
            blockers.append(f"{prefix}:update_signal_features_missing")
            continue
        latency = _proxy_replay_number(
            features["latency_ms"],
            field=f"{prefix}:latency_ms",
            blockers=blockers,
        )
        deadline = _proxy_replay_number(
            features["deadline_ms"],
            field=f"{prefix}:deadline_ms",
            blockers=blockers,
        )
        queue_depth_number = _proxy_replay_number(
            features["gpu_queue_depth"],
            field=f"{prefix}:gpu_queue_depth",
            blockers=blockers,
        )
        if latency is None or deadline is None or queue_depth_number is None:
            continue
        gpu_queue_depth = int(queue_depth_number)
        if queue_depth_number != gpu_queue_depth or gpu_queue_depth < 0 or latency < 0 or deadline <= 0:
            blockers.append(f"{prefix}:update_signal_features_invalid")
            continue
        if latency > deadline and gpu_queue_depth > 0:
            delta = penalty
            signal_reason = "prototype_deadline_miss_with_gpu_backlog"
        elif latency <= deadline and gpu_queue_depth == 0:
            delta = -reward
            signal_reason = "prototype_on_time_with_empty_gpu_queue"
        else:
            delta = 0.0
            signal_reason = "no_weight_update"
        try:
            old_weights = {resource: float(old_weights_raw[resource]) for resource in ("cpu", "gpu")}
            raw_weights = {resource: float(raw_weights_raw[resource]) for resource in ("cpu", "gpu")}
            projected_weights = {
                resource: float(projected_weights_raw[resource]) for resource in ("cpu", "gpu")
            }
        except (KeyError, TypeError, ValueError):
            blockers.append(f"{prefix}:feedback_weight_maps_invalid")
            continue
        expected_raw = {"cpu": old_weights["cpu"], "gpu": old_weights["gpu"] + delta}
        if not _weight_maps_close(raw_weights, expected_raw, tolerance=1e-9):
            blockers.append(f"{prefix}:raw_weight_update_replay_mismatch")
        lower = {resource: float(passport["weight_lower_bound"]) for resource in ("cpu", "gpu")}
        upper = {resource: float(passport["weight_upper_bound"]) for resource in ("cpu", "gpu")}
        expected_projected = _project_weights_to_box_mean_one(expected_raw, lower, upper)
        if not _weight_maps_close(projected_weights, expected_projected, tolerance=1e-8):
            blockers.append(f"{prefix}:projected_weight_replay_mismatch")

        terminal_status = str(row["terminal_status"])
        lag = int(float(row["parameter_lag"]))
        events_since_update = int(float(row["events_since_update"]))
        variation_before = float(row["variation_before"])
        candidate_variation = sum(
            abs(expected_projected[resource] - old_weights[resource])
            for resource in ("cpu", "gpu")
        )
        has_consumer = (
            str(row["first_consumer_decision_id"]) != "unavailable"
            and int(float(row["first_consumer_decision_seq"])) > 0
        )
        if terminal_status == "censored":
            expected_action = "no_op"
            expected_reason = "censored_feedback"
        elif lag > int(passport["feedback_lag_limit"]):
            expected_action = "no_op"
            expected_reason = "stale_feedback"
        elif events_since_update < int(passport["feedback_cooldown_events"]):
            expected_action = "no_op"
            expected_reason = "cooldown_active"
        elif signal_reason == "no_weight_update" or candidate_variation <= 1e-12:
            expected_action = "no_op"
            expected_reason = "no_weight_update"
        elif variation_before + candidate_variation > float(passport["variation_budget"]) + 1e-12:
            expected_action = "no_op"
            expected_reason = "variation_budget_exhausted"
        elif not has_consumer:
            expected_action = "no_op"
            expected_reason = "no_subsequent_decision_before_end"
        else:
            expected_action = "update"
            expected_reason = signal_reason
        if str(row["feedback_action"]) != expected_action:
            blockers.append(f"{prefix}:feedback_action_replay_mismatch")
        if str(row["reason"]) != expected_reason:
            blockers.append(f"{prefix}:feedback_reason_replay_mismatch")
        if len(blockers) == row_blocker_count:
            replayed += 1

    blockers = list(dict.fromkeys(blockers))
    return {
        "passed": not blockers and replayed == int(feedback.shape[0]),
        "feedback_count": int(feedback.shape[0]),
        "replayed_feedback_count": replayed,
        "blockers": blockers,
    }


def evaluate_primary_policy_proxy_replay(
    config: dict[str, Any],
    *,
    frozen_decisions: pd.DataFrame,
    online_decisions: pd.DataFrame,
    online_feedback: pd.DataFrame,
    frozen_metadata: dict[str, Any] | None,
    online_metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Replay the frozen v4 CPU/GPU proxy without implying formal AW-HEFT equivalence."""

    ablation = validate_primary_policy_ablation(config)
    passport = ablation["policy_passport"]
    frozen = _primary_proxy_decision_replay(
        frozen_decisions,
        arm="frozen",
        policy=str(ablation["frozen_policy"]),
        version=f"{ablation['policy_version_prefix']}-frozen",
        passport=passport,
    )
    online = _primary_proxy_decision_replay(
        online_decisions,
        arm="online",
        policy=str(ablation["online_policy"]),
        version=f"{ablation['policy_version_prefix']}-online",
        passport=passport,
    )
    feedback = _primary_proxy_feedback_replay(online_feedback, passport=passport)
    artifact_blockers = [
        *_primary_proxy_runtime_artifact_blockers(
            frozen_metadata,
            arm="frozen",
            expected_path=str(ablation["policy_artifact"]),
            expected_sha256=str(ablation["policy_artifact_sha256"]),
        ),
        *_primary_proxy_runtime_artifact_blockers(
            online_metadata,
            arm="online",
            expected_path=str(ablation["policy_artifact"]),
            expected_sha256=str(ablation["policy_artifact_sha256"]),
        ),
    ]
    pair_blockers: list[str] = []
    if set(frozen_decisions.get("graph_version", pd.Series(dtype=str)).astype(str)) != set(
        online_decisions.get("graph_version", pd.Series(dtype=str)).astype(str)
    ):
        pair_blockers.append("pair:graph_version_mismatch")
    if set(frozen_decisions.get("profile_version", pd.Series(dtype=str)).astype(str)) != set(
        online_decisions.get("profile_version", pd.Series(dtype=str)).astype(str)
    ):
        pair_blockers.append("pair:profile_version_mismatch")
    blockers = list(
        dict.fromkeys(
            [
                *artifact_blockers,
                *frozen["blockers"],
                *online["blockers"],
                *feedback["blockers"],
                *pair_blockers,
            ]
        )
    )
    passed = not blockers and frozen["passed"] and online["passed"] and feedback["passed"]
    return {
        "assessment_schema_version": 1,
        "gate": "policy_implementation_equivalence",
        "scope": "frozen_v4_proxy_passport_replay",
        "status": "passed_proxy_reference_replay" if passed else "blocked_proxy_reference_replay_failed",
        "passed": passed,
        "runtime_reference_replay_performed": True,
        "policy_cell_preregistration_version": int(ablation["preregistration_version"]),
        "policy_version_prefix": str(ablation["policy_version_prefix"]),
        "artifact_identity_verified": not artifact_blockers,
        "frozen_arm": frozen,
        "online_arm": online,
        "online_feedback": feedback,
        "pair_contract_blockers": pair_blockers,
        "blockers": blockers,
        "formal_aw_heft_equivalence_evaluated": False,
        "interpretation": (
            "Passing this gate establishes only executable equivalence of the frozen "
            "v4 CPU/GPU technical proxy traces to their preregistered passport. It "
            "does not evaluate formal AW-HEFT or a paired policy effect."
        ),
    }


def validate_drop_counters(path: Path, *, require_labeled_provenance: bool = False) -> pd.DataFrame:
    columns = _select_sidecar_columns(
        path,
        DROP_COUNTER_COLUMNS,
        LEGACY_DROP_COUNTER_COLUMNS,
        DROP_COUNTER_PROVENANCE_COLUMNS,
    )
    df = _validate_native_sidecar(path, columns, DROP_COUNTER_NUMERIC_COLUMNS).copy()
    if columns == LEGACY_DROP_COUNTER_COLUMNS:
        for column in DROP_COUNTER_PROVENANCE_COLUMNS:
            df[column] = _UNLABELED_LEGACY
    _validate_provenance_values(df, path, "drop_provenance", _DROP_PROVENANCE)
    _validate_provenance_values(df, path, "late_provenance", _LATE_PROVENANCE)
    _require_labeled_provenance(
        df,
        path,
        DROP_COUNTER_PROVENANCE_COLUMNS,
        require_labeled_provenance,
    )
    for column in ("drop_rate_percent", "late_rate_percent"):
        values = pd.to_numeric(df[column], errors="raise")
        if ((values < 0) | (values > 100)).any():
            raise ContractError(f"{path}:{column} must be between 0 and 100")
    return df[DROP_COUNTER_COLUMNS]


def validate_ingress_ledger(
    path: Path,
    *,
    frames: pd.DataFrame,
    drop_counters: pd.DataFrame | None = None,
    topology_events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Validate an independently emitted ingress cohort and its terminal closure."""
    df = _validate_native_sidecar(path, INGRESS_LEDGER_COLUMNS, INGRESS_LEDGER_NUMERIC_COLUMNS).copy()
    if set(df["ingress_provenance"].astype(str)) - _INGRESS_PROVENANCE:
        raise ContractError(f"{path}: ingress_provenance must be native_ingress_event")
    if set(df["terminal_provenance"].astype(str)) - _INGRESS_TERMINAL_PROVENANCE:
        raise ContractError(f"{path}: unsupported terminal_provenance")
    if set(df["terminal_status"].astype(str)) - _INGRESS_TERMINAL_STATUSES:
        raise ContractError(f"{path}: terminal_status must be completed, drop, or censored")
    if df["trace_id"].astype(str).duplicated().any():
        raise ContractError(f"{path}: trace_id must be unique in the ingress cohort")
    if df["input_frame_key"].astype(str).duplicated().any():
        raise ContractError(f"{path}: input_frame_key must be unique in the ingress cohort")
    for column in ("source_sha256", "payload_sha256"):
        values = df[column].astype(str).str.strip().str.lower()
        if not values.str.fullmatch(r"[0-9a-f]{64}", na=False).all():
            raise ContractError(f"{path}: {column} must contain lowercase SHA-256 values")
        df[column] = values
    for column in (
        "admission_seq",
        "source_cycle",
        "access_unit_pts_ns",
        "payload_size_bytes",
        "schedule_offset_ns",
    ):
        values = pd.to_numeric(df[column], errors="raise")
        if (values % 1 != 0).any():
            raise ContractError(f"{path}: {column} must contain integers")
        df[column] = values.astype(int)
    if (df["admission_seq"] <= 0).any():
        raise ContractError(f"{path}: admission_seq must be positive")
    if (df["source_cycle"] < 0).any() or (df["access_unit_pts_ns"] < 0).any():
        raise ContractError(f"{path}: source_cycle and access_unit_pts_ns must be non-negative")
    if (df["payload_size_bytes"] <= 0).any() or (df["schedule_offset_ns"] < 0).any():
        raise ContractError(f"{path}: payload_size_bytes must be positive and schedule_offset_ns non-negative")
    for stream_id, group in df.groupby("stream_id", dropna=False):
        ordered = group.sort_values("admission_seq")
        sequences = ordered["admission_seq"].astype(int).tolist()
        if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
            raise ContractError(f"{path}: admission_seq must be gap-free within stream {stream_id}")
        offsets = ordered["schedule_offset_ns"].astype(int)
        if len(offsets) > 1 and not (offsets.diff().iloc[1:] > 0).all():
            raise ContractError(f"{path}: schedule_offset_ns must increase within stream {stream_id}")
    ledger_keys = list(
        zip(
            df["run_id"].astype(str),
            df["trace_id"].astype(str),
            pd.to_numeric(df["stream_id"], errors="raise").astype(int),
            pd.to_numeric(df["frame_id"], errors="raise").astype(int),
            strict=True,
        )
    )
    if len(ledger_keys) != len(set(ledger_keys)):
        raise ContractError(f"{path}: duplicate run/trace/stream/frame ingress key")

    run_ids = set(df["run_id"].astype(str))
    cohort_ids = set(df["cohort_id"].astype(str))
    if len(run_ids) != 1 or len(cohort_ids) != 1:
        raise ContractError(f"{path}: one run directory must contain exactly one ingress cohort")
    for column in (
        "window_start_timestamp_ms",
        "window_end_timestamp_ms",
        "drain_end_timestamp_ms",
        "censoring_rule",
    ):
        if df[column].nunique(dropna=False) != 1:
            raise ContractError(f"{path}: {column} must be constant within the ingress cohort")

    window_start = float(df["window_start_timestamp_ms"].iloc[0])
    window_end = float(df["window_end_timestamp_ms"].iloc[0])
    drain_end = float(df["drain_end_timestamp_ms"].iloc[0])
    if not window_start < window_end:
        raise ContractError(f"{path}: ingress window must satisfy t0 < t1")
    if drain_end < window_end:
        raise ContractError(f"{path}: drain_end_timestamp_ms must not precede the ingress window end")
    censoring_rule = str(df["censoring_rule"].iloc[0]).strip()
    if (
        (df["terminal_status"].astype(str) == "censored").any()
        and censoring_rule.lower() == "drain_to_empty"
    ):
        raise ContractError(f"{path}: drain_to_empty cannot leave censored ingress rows")

    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        ingress = float(row["ingress_timestamp_ms"])
        terminal = float(row["terminal_timestamp_ms"])
        status = str(row["terminal_status"])
        provenance = str(row["terminal_provenance"])
        # Cohort membership is selected by the native half-open schedule offsets.
        # Mapping the common monotonic start to integer wall-clock milliseconds can
        # place the first scheduled AU a few milliseconds before the declared t0.
        # Keep that conversion jitter bounded by the frozen 5 ms clock-offset gate;
        # the right boundary remains strict.
        if ingress < window_start - INGRESS_WALL_CLOCK_START_TOLERANCE_MS or ingress >= window_end:
            raise ContractError(f"{path}:{row_number}: ingress timestamp is outside [t0, t1)")
        if terminal < ingress or terminal > drain_end:
            raise ContractError(f"{path}:{row_number}: terminal timestamp is outside the frame/drain interval")
        expected_provenance = {
            "completed": "native_completion_event",
            "drop": "native_drop_event",
            "censored": "explicit_censoring_at_drain_end",
        }[status]
        if provenance != expected_provenance:
            raise ContractError(
                f"{path}:{row_number}: terminal_provenance does not match terminal_status={status}"
            )
        if status == "censored" and not math.isclose(terminal, drain_end, abs_tol=1e-3):
            raise ContractError(f"{path}:{row_number}: censored terminal time must equal drain end")

    missing_frame_columns = [column for column in FRAME_COLUMNS if column not in frames.columns]
    if missing_frame_columns:
        raise ContractError(
            f"frames dataframe is missing ingress linkage columns: {', '.join(missing_frame_columns)}"
        )
    if set(frames["telemetry_source"].astype(str)) != {"native"}:
        raise ContractError("ingress ledger linkage requires native frames.csv rows")
    frame_records = frames[FRAME_COLUMNS].to_dict(orient="records")
    frame_by_key: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for frame in frame_records:
        key = (
            str(frame["run_id"]),
            str(frame["trace_id"]),
            int(frame["stream_id"]),
            int(frame["frame_id"]),
        )
        if key in frame_by_key:
            raise ContractError("frames.csv contains duplicate ingress linkage keys")
        frame_by_key[key] = frame

    completed_rows = df[df["terminal_status"].astype(str) == "completed"]
    completed_by_key: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for row in completed_rows.to_dict(orient="records"):
        key = (str(row["run_id"]), str(row["trace_id"]), int(row["stream_id"]), int(row["frame_id"]))
        completed_by_key[key] = row
        frame = frame_by_key.get(key)
        if frame is None:
            raise ContractError(f"{path}: completed ingress row has no matching frames.csv row: {key}")
        if not math.isclose(
            float(row["ingress_timestamp_ms"]), float(frame["ingress_timestamp_ms"]), abs_tol=1e-3
        ):
            raise ContractError(f"{path}: completed ingress timestamp does not match frames.csv for {key}")
        if not math.isclose(
            float(row["terminal_timestamp_ms"]), float(frame["egress_timestamp_ms"]), abs_tol=1e-3
        ):
            raise ContractError(f"{path}: completed terminal timestamp does not match frames.csv for {key}")
    if set(frame_by_key) != set(completed_by_key):
        missing = set(frame_by_key) - set(completed_by_key)
        raise ContractError(f"{path}: ingress ledger is missing {len(missing)} completed frames.csv rows")

    if drop_counters is not None and "drop_provenance" in drop_counters.columns:
        native_drops = drop_counters[
            drop_counters["drop_provenance"].astype(str) == "native_drop_event"
        ].copy()
        if not native_drops.empty:
            counter_by_stream = (
                native_drops.assign(
                    stream_id=pd.to_numeric(native_drops["stream_id"], errors="raise").astype(int),
                    dropped_frames=pd.to_numeric(native_drops["dropped_frames"], errors="raise").astype(int),
                )
                .groupby("stream_id", dropna=False)["dropped_frames"]
                .sum()
                .to_dict()
            )
            ledger_by_stream = (
                df[df["terminal_status"].astype(str) == "drop"]
                .assign(stream_id=lambda value: pd.to_numeric(value["stream_id"], errors="raise").astype(int))
                .groupby("stream_id", dropna=False)
                .size()
                .to_dict()
            )
            all_streams = set(counter_by_stream) | set(ledger_by_stream)
            for stream_id in all_streams:
                if int(counter_by_stream.get(stream_id, 0)) != int(ledger_by_stream.get(stream_id, 0)):
                    raise ContractError(
                        f"{path}: native drop counter does not match ingress ledger for stream {stream_id}"
                    )

    if topology_events is not None:
        required = {"run_id", "trace_id", "stream_id", "frame_id", "input_frame_key"}
        missing_topology_columns = sorted(required - set(topology_events.columns))
        if missing_topology_columns:
            raise ContractError(
                f"topology events are missing ingress linkage columns: {', '.join(missing_topology_columns)}"
            )
        topology_keys: dict[tuple[str, str, int, int], set[str]] = {}
        for row in topology_events.to_dict(orient="records"):
            key = (str(row["run_id"]), str(row["trace_id"]), int(row["stream_id"]), int(row["frame_id"]))
            topology_keys.setdefault(key, set()).add(str(row["input_frame_key"]))
        if set(topology_keys) != set(completed_by_key):
            raise ContractError(f"{path}: topology trace and completed ingress cohort cover different frames")
        for key, input_keys in topology_keys.items():
            expected = str(completed_by_key[key]["input_frame_key"])
            if input_keys != {expected}:
                raise ContractError(f"{path}: topology input_frame_key does not match ingress ledger for {key}")

    result = df[INGRESS_LEDGER_COLUMNS].copy()
    result["ingress_claim_eligible"] = True
    return result


def validate_reset_evidence(
    path: Path,
    *,
    ingress_ledger: pd.DataFrame,
    topology_kind: str,
    expected_streams: int,
    required_branches: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    """Validate direct reset evidence for one independently launched benchmark arm."""
    df = _validate_native_sidecar(
        path,
        RESET_EVIDENCE_COLUMNS,
        RESET_EVIDENCE_NUMERIC_COLUMNS,
    ).copy()
    versions = pd.to_numeric(df["reset_contract_version"], errors="raise")
    if (versions != RESET_EVIDENCE_CONTRACT_VERSION).any():
        raise ContractError(f"{path}: unsupported reset evidence contract version")
    for column in RESET_EVIDENCE_NUMERIC_COLUMNS:
        values = pd.to_numeric(df[column], errors="raise")
        if (values % 1 != 0).any():
            raise ContractError(f"{path}: {column} must contain integers")
        df[column] = values.astype(int)
    if set(df["reset_provenance"].astype(str)) - _RESET_EVIDENCE_PROVENANCE:
        raise ContractError(f"{path}: reset evidence must come from a native lifecycle/queue/sink snapshot")

    ledger_required = set(INGRESS_LEDGER_COLUMNS)
    missing_ledger_columns = sorted(ledger_required - set(ingress_ledger.columns))
    if missing_ledger_columns:
        raise ContractError(
            f"{path}: reset evidence requires ingress ledger columns: {', '.join(missing_ledger_columns)}"
        )
    ledger_run_ids = set(ingress_ledger["run_id"].astype(str))
    ledger_cohort_ids = set(ingress_ledger["cohort_id"].astype(str))
    if len(ledger_run_ids) != 1 or len(ledger_cohort_ids) != 1:
        raise ContractError(f"{path}: reset evidence requires one accepted ingress cohort")
    if set(df["run_id"].astype(str)) != ledger_run_ids or set(df["cohort_id"].astype(str)) != ledger_cohort_ids:
        raise ContractError(f"{path}: reset evidence run/cohort does not match ingress_ledger.csv")
    if (ingress_ledger["terminal_status"].astype(str) == "censored").any():
        raise ContractError(f"{path}: reset evidence cannot pass while the ingress cohort contains censored rows")

    stream_count = int(expected_streams)
    if stream_count <= 0:
        raise ContractError(f"{path}: expected_streams must be positive")
    stream_ids = set(pd.to_numeric(ingress_ledger["stream_id"], errors="raise").astype(int))
    if stream_ids != set(range(stream_count)):
        raise ContractError(f"{path}: reset evidence requires ingress for streams 0..{stream_count - 1}")
    branches = tuple(str(value).strip() for value in required_branches if str(value).strip())
    if not branches or len(branches) != len(set(branches)):
        raise ContractError(f"{path}: reset evidence requires a non-empty unique branch set")
    if topology_kind not in {"independent_processes", "shared_video_dag"}:
        raise ContractError(f"{path}: unsupported reset evidence topology kind: {topology_kind}")

    if df["process_instance_id"].astype(str).duplicated().any():
        raise ContractError(f"{path}: process_instance_id must be unique")
    pids = df["observed_pid"].astype(int)
    if (pids <= 0).any() or pids.duplicated().any():
        raise ContractError(f"{path}: observed_pid must be positive and unique within an arm")
    tokens = df["process_start_token"].astype(str).str.strip().str.lower()
    if not tokens.str.fullmatch(r"[0-9a-f]{64}", na=False).all() or tokens.duplicated().any():
        raise ContractError(f"{path}: process_start_token must be a unique lowercase SHA-256")
    df["process_start_token"] = tokens
    ready = df["ready_timestamp_ns"].astype(int)
    if (ready <= 0).any():
        raise ContractError(f"{path}: ready_timestamp_ns must be positive")

    sink_ids = df["telemetry_sink_id"].astype(str).str.strip().str.lower()
    if sink_ids.nunique(dropna=False) != 1 or not sink_ids.str.fullmatch(r"[0-9a-f]{64}", na=False).all():
        raise ContractError(f"{path}: telemetry_sink_id must be one lowercase SHA-256 per arm")
    if (df["telemetry_sink_preexisting_entry_count"].astype(int) != 0).any():
        raise ContractError(f"{path}: telemetry sink must be empty before the arm starts")
    if set(df["warmup_included_in_measurement"].astype(str).str.lower()) != {"false"}:
        raise ContractError(f"{path}: warmup must be excluded from measurement")
    if set(df["admission_stopped_before_drain"].astype(str).str.lower()) != {"true"}:
        raise ContractError(f"{path}: admission must stop before drain")
    if set(df["terminal_state"].astype(str)) != {"DRAINED"}:
        raise ContractError(f"{path}: every reset process must terminate in DRAINED state")

    expected_processes: set[tuple[str, int, str]] = {
        ("source_coordinator", stream_id, "not_applicable") for stream_id in range(stream_count)
    }
    if topology_kind == "independent_processes":
        expected_processes.update(
            ("independent_branch_worker", stream_id, branch)
            for stream_id in range(stream_count)
            for branch in branches
        )
    else:
        expected_processes.update(
            ("shared_graph_worker", stream_id, "not_applicable")
            for stream_id in range(stream_count)
        )

    observed_processes: set[tuple[str, int, str]] = set()
    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        role = str(row["process_role"])
        stream_id = int(float(row["stream_id"]))
        branch_id = str(row["branch_id"])
        key = (role, stream_id, branch_id)
        if key in observed_processes:
            raise ContractError(f"{path}:{row_number}: duplicate reset process coordinate {key}")
        observed_processes.add(key)
        queue_depths = _parse_json_field(
            row["analytics_queue_depths_json"],
            path=path,
            row_number=row_number,
            column="analytics_queue_depths_json",
            expected_type=dict,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value != 0 for value in queue_depths.values()):
            raise ContractError(f"{path}:{row_number}: every analytics queue depth must be integer zero")
        source_cycle = int(float(row["source_cycle_first"]))
        admission_seq = int(float(row["admission_seq_first"]))
        if role == "source_coordinator":
            if queue_depths:
                raise ContractError(f"{path}:{row_number}: source coordinator must not claim analytics queues")
            if source_cycle != 0 or admission_seq != 1:
                raise ContractError(f"{path}:{row_number}: source replay must begin at cycle 0/admission 1")
        else:
            if source_cycle != -1 or admission_seq != -1:
                raise ContractError(f"{path}:{row_number}: worker source-origin fields must be -1")
            expected_queue_keys = {branch_id} if role == "independent_branch_worker" else set(branches)
            if set(queue_depths) != expected_queue_keys:
                raise ContractError(f"{path}:{row_number}: analytics queue reset coverage is incomplete")

    if observed_processes != expected_processes:
        missing = sorted(expected_processes - observed_processes)
        extra = sorted(observed_processes - expected_processes)
        raise ContractError(f"{path}: reset process coverage differs; missing={missing}, extra={extra}")

    result = df[RESET_EVIDENCE_COLUMNS].copy()
    result["reset_claim_eligible"] = True
    return result


def _branch_analytics_contract_entries(
    branch_terminals: pd.DataFrame,
    *,
    source: str,
) -> list[dict[str, str]]:
    required = {"branch_id", "detector", "backend"}
    missing = sorted(required - set(branch_terminals.columns))
    if missing:
        raise ContractError(
            f"{source}: branch analytics contract requires columns: {', '.join(missing)}"
        )

    identities: dict[str, dict[str, str]] = {}
    for row_index, row in branch_terminals.iterrows():
        row_number = int(row_index) + 2
        branch_id = str(row["branch_id"])
        detector = str(row["detector"])
        backend = str(row["backend"])
        detector_parts = detector.split(";")
        if len(detector_parts) not in {2, 3}:
            raise ContractError(
                f"{source}:{row_number}: detector must be a verified model identity"
            )
        detector_id = detector_parts[0]
        if (
            not 1 <= len(detector_id) <= 80
            or detector_id in {"identity", "topology_only"}
            or any(ord(character) < 0x20 or ord(character) > 0x7E for character in detector_id)
        ):
            raise ContractError(
                f"{source}:{row_number}: detector_id is not a valid verified analytics identifier"
            )
        if re.fullmatch(r"model_sha256=[0-9a-f]{64}", detector_parts[1]) is None:
            raise ContractError(
                f"{source}:{row_number}: detector must contain a lowercase model_sha256"
            )
        if len(detector_parts) == 3 and re.fullmatch(
            r"weights_sha256=[0-9a-f]{64}", detector_parts[2]
        ) is None:
            raise ContractError(
                f"{source}:{row_number}: detector weights identity is invalid"
            )
        if backend not in _VERIFIED_ANALYTICS_BACKENDS:
            raise ContractError(
                f"{source}:{row_number}: backend is not a verified OpenVINO/DL Streamer detector factory"
            )

        entry = {
            "branch_id": branch_id,
            "detector_id": detector_id,
            "model_sha256": detector_parts[1].split("=", 1)[1],
            "weights_sha256": (
                detector_parts[2].split("=", 1)[1] if len(detector_parts) == 3 else ""
            ),
            "backend": backend,
        }
        previous = identities.get(branch_id)
        if previous is not None and previous != entry:
            raise ContractError(
                f"{source}:{row_number}: analytics identity changed within branch {branch_id}"
            )
        identities[branch_id] = entry
    if not identities:
        raise ContractError(f"{source}: branch analytics contract is empty")
    return [identities[branch_id] for branch_id in sorted(identities)]


def validate_branch_terminals(
    path: Path,
    *,
    ingress_ledger: pd.DataFrame,
    frames: pd.DataFrame,
    required_branches: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Validate native per-branch outcomes before a checkpoint frame is aggregated."""
    df = _validate_native_sidecar(path, BRANCH_TERMINAL_COLUMNS, BRANCH_TERMINAL_NUMERIC_COLUMNS).copy()
    declared_branches = tuple(str(value).strip() for value in (required_branches or ()) if str(value).strip())
    if declared_branches:
        if len(declared_branches) != len(set(declared_branches)):
            raise ContractError(f"{path}: required checkpoint branches must be unique")
        branch_set = set(declared_branches)
    else:
        branch_set = set(df["branch_id"].astype(str))
    if not branch_set:
        raise ContractError(f"{path}: checkpoint branch set is empty")
    unknown_branches = set(df["branch_id"].astype(str)) - branch_set
    if unknown_branches:
        raise ContractError(f"{path}: branch terminals contain undeclared branches: {', '.join(sorted(unknown_branches))}")
    _branch_analytics_contract_entries(df, source=str(path))

    terminal_statuses = set(df["terminal_status"].astype(str))
    if terminal_statuses - _BRANCH_TERMINAL_STATUSES:
        raise ContractError(f"{path}: branch terminal_status must be completed or drop")
    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        status = str(row["terminal_status"])
        expected_provenance = _BRANCH_TERMINAL_PROVENANCE[status]
        if str(row["terminal_provenance"]) != expected_provenance:
            raise ContractError(
                f"{path}:{row_number}: terminal_provenance does not match branch terminal_status={status}"
            )
        objects = float(row["objects"])
        if not objects.is_integer() or objects < 0:
            raise ContractError(f"{path}:{row_number}: objects must be a non-negative integer")
        if status == "drop" and int(objects) != 0:
            raise ContractError(f"{path}:{row_number}: a dropped branch must not report accepted objects")

    ledger_required = set(INGRESS_LEDGER_COLUMNS)
    missing_ledger_columns = sorted(ledger_required - set(ingress_ledger.columns))
    if missing_ledger_columns:
        raise ContractError(
            f"branch terminal linkage requires ingress ledger columns: {', '.join(missing_ledger_columns)}"
        )
    frame_required = set(FRAME_COLUMNS)
    missing_frame_columns = sorted(frame_required - set(frames.columns))
    if missing_frame_columns:
        raise ContractError(
            f"branch terminal linkage requires frames columns: {', '.join(missing_frame_columns)}"
        )
    if set(frames["telemetry_source"].astype(str)) - {"native"}:
        raise ContractError("branch terminal linkage requires native frames.csv rows")

    def linkage_key(row: dict[str, Any]) -> tuple[str, str, int, int]:
        return (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )

    ledger_records = ingress_ledger[INGRESS_LEDGER_COLUMNS].to_dict(orient="records")
    ledger_by_key = {linkage_key(row): row for row in ledger_records}
    if len(ledger_by_key) != len(ledger_records):
        raise ContractError(f"{path}: ingress ledger contains duplicate branch linkage keys")
    frame_records = frames[FRAME_COLUMNS].to_dict(orient="records")
    frame_by_key = {linkage_key(row): row for row in frame_records}
    if len(frame_by_key) != len(frame_records):
        raise ContractError(f"{path}: frames.csv contains duplicate branch linkage keys")

    grouped: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}
    seen_branch_keys: set[tuple[str, str, int, int, str]] = set()
    for row in df[BRANCH_TERMINAL_COLUMNS].to_dict(orient="records"):
        key = linkage_key(row)
        ledger = ledger_by_key.get(key)
        if ledger is None:
            raise ContractError(f"{path}: branch terminal has no matching ingress row: {key}")
        if str(row["cohort_id"]) != str(ledger["cohort_id"]):
            raise ContractError(f"{path}: branch terminal cohort_id does not match ingress ledger for {key}")
        if str(row["input_frame_key"]) != str(ledger["input_frame_key"]):
            raise ContractError(f"{path}: branch terminal input_frame_key does not match ingress ledger for {key}")
        timestamp = float(row["terminal_timestamp_ms"])
        if timestamp < float(ledger["ingress_timestamp_ms"]) or timestamp > float(ledger["drain_end_timestamp_ms"]):
            raise ContractError(f"{path}: branch terminal timestamp is outside the frame/drain interval for {key}")
        branch_key = (*key, str(row["branch_id"]))
        if branch_key in seen_branch_keys:
            raise ContractError(f"{path}: duplicate branch terminal for {branch_key}")
        seen_branch_keys.add(branch_key)
        grouped.setdefault(key, []).append(row)

    for key, ledger in ledger_by_key.items():
        rows = grouped.get(key, [])
        observed = {str(row["branch_id"]) for row in rows}
        status = str(ledger["terminal_status"])
        row_statuses = {str(row["terminal_status"]) for row in rows}
        if status in {"completed", "drop"} and observed != branch_set:
            raise ContractError(f"{path}: terminal ingress row does not cover every required branch for {key}")
        if status == "completed" and row_statuses != {"completed"}:
            raise ContractError(f"{path}: completed ingress row contains a non-completed branch for {key}")
        if status == "drop" and "drop" not in row_statuses:
            raise ContractError(f"{path}: drop ingress row has no native branch drop event for {key}")
        if status == "censored":
            if "drop" in row_statuses:
                raise ContractError(f"{path}: censored ingress row contains a native branch drop event for {key}")
            if observed == branch_set:
                raise ContractError(f"{path}: fully terminalized branches may not be labeled censored for {key}")
            continue

        terminal_timestamp = max(float(row["terminal_timestamp_ms"]) for row in rows)
        aggregate_timestamp = float(ledger["terminal_timestamp_ms"])
        if status == "completed":
            if aggregate_timestamp + 1e-3 < terminal_timestamp:
                raise ContractError(f"{path}: aggregate join precedes a branch terminal for {key}")
        elif not math.isclose(terminal_timestamp, aggregate_timestamp, abs_tol=1e-3):
            raise ContractError(f"{path}: aggregate drop time does not match branch terminals for {key}")
        if status == "completed":
            frame = frame_by_key.get(key)
            if frame is None:
                raise ContractError(f"{path}: completed branch set has no aggregate frames.csv row for {key}")
            if str(frame["detector"]) != CHECKPOINT_FRAME_AGGREGATE_DETECTOR:
                raise ContractError(
                    f"{path}: checkpoint frames.csv detector must be {CHECKPOINT_FRAME_AGGREGATE_DETECTOR}"
                )
            object_sum = sum(int(float(row["objects"])) for row in rows)
            if int(float(frame["objects"])) != object_sum:
                raise ContractError(f"{path}: aggregate frames.csv objects do not equal branch result sum for {key}")
        elif key in frame_by_key:
            raise ContractError(f"{path}: dropped ingress row must not have a completed frames.csv row for {key}")

    result = df[BRANCH_TERMINAL_COLUMNS].copy()
    result["branch_terminal_claim_eligible"] = True
    return result


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def branch_analytics_contract_sha256(branch_terminals: pd.DataFrame) -> str:
    """Hash the stable per-branch detector artifact and backend identities."""
    payload = {
        "contract_version": BRANCH_ANALYTICS_CONTRACT_VERSION,
        "branches": _branch_analytics_contract_entries(
            branch_terminals,
            source="branch terminals",
        ),
    }
    return _canonical_json_sha256(payload)


def _validate_transform_contract(value: Any, *, path: Path, row_number: int) -> dict[str, Any]:
    transform = _parse_json_field(
        value,
        path=path,
        row_number=row_number,
        column="transform_json",
        expected_type=dict,
    )
    if set(transform) != {"resize", "normalization"}:
        raise ContractError(
            f"{path}:{row_number}: transform_json must contain exactly resize and normalization"
        )
    for component_name in ("resize", "normalization"):
        component = transform[component_name]
        if not isinstance(component, dict) or not component:
            raise ContractError(f"{path}:{row_number}: transform_json.{component_name} must be an object")
        mode = str(component.get("mode", "")).strip()
        if not mode:
            raise ContractError(f"{path}:{row_number}: transform_json.{component_name}.mode is required")
        if component_name == "resize" and mode != "identity":
            for field in ("output_width", "output_height"):
                value = component.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ContractError(
                        f"{path}:{row_number}: transform_json.resize.{field} must be a positive integer"
                    )
            if not str(component.get("algorithm", "")).strip():
                raise ContractError(f"{path}:{row_number}: transform_json.resize.algorithm is required")
        if component_name == "normalization" and mode != "identity":
            parameters = component.get("parameters")
            if not isinstance(parameters, dict) or not parameters:
                raise ContractError(
                    f"{path}:{row_number}: transform_json.normalization.parameters must be a non-empty object"
                )
    return transform


def _validate_output_shape(value: Any, *, path: Path, row_number: int) -> list[int | str]:
    shape = _parse_json_field(
        value,
        path=path,
        row_number=row_number,
        column="output_shape_json",
        expected_type=list,
    )
    if not shape:
        raise ContractError(f"{path}:{row_number}: output_shape_json must not be empty")
    normalized: list[int | str] = []
    for dimension in shape:
        if isinstance(dimension, bool):
            raise ContractError(f"{path}:{row_number}: output_shape_json contains an invalid dimension")
        if isinstance(dimension, int):
            if dimension <= 0:
                raise ContractError(f"{path}:{row_number}: output_shape_json dimensions must be positive")
            normalized.append(dimension)
            continue
        text = str(dimension).strip()
        if not text:
            raise ContractError(f"{path}:{row_number}: output_shape_json contains an empty dimension")
        normalized.append(text)
    return normalized


def _validate_implementation_artifacts(
    value: Any,
    *,
    path: Path,
    row_number: int,
) -> list[dict[str, str]]:
    artifacts = _parse_json_field(
        value,
        path=path,
        row_number=row_number,
        column="implementation_artifacts_json",
        expected_type=list,
    )
    if not artifacts:
        raise ContractError(
            f"{path}:{row_number}: implementation_artifacts_json must not be empty"
        )

    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for artifact_index, artifact in enumerate(artifacts):
        field_prefix = f"implementation_artifacts_json[{artifact_index}]"
        if not isinstance(artifact, dict) or set(artifact) != {
            "role",
            "logical_name",
            "kind",
            "sha256",
        }:
            raise ContractError(
                f"{path}:{row_number}: {field_prefix} must contain exactly "
                "role, logical_name, kind, and sha256"
            )
        role = str(artifact["role"]).strip()
        logical_name = str(artifact["logical_name"]).strip()
        kind = str(artifact["kind"]).strip()
        raw_sha256 = str(artifact["sha256"]).strip()
        sha256 = raw_sha256.lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]*", role):
            raise ContractError(
                f"{path}:{row_number}: {field_prefix}.role must be a canonical identifier"
            )
        if (
            not logical_name
            or logical_name.lower() in {"unknown", "unavailable", "none", "nan"}
            or any(character in logical_name for character in "\r\n")
        ):
            raise ContractError(
                f"{path}:{row_number}: {field_prefix}.logical_name must be explicit"
            )
        if kind not in _STAGE_ARTIFACT_KINDS:
            raise ContractError(
                f"{path}:{row_number}: {field_prefix}.kind is not an allowed runtime artifact kind"
            )
        if raw_sha256 != sha256 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ContractError(
                f"{path}:{row_number}: {field_prefix}.sha256 must be a lowercase SHA-256 digest"
            )
        identity = (role, kind, logical_name)
        if identity in identities:
            raise ContractError(
                f"{path}:{row_number}: implementation artifact identities must be unique"
            )
        identities.add(identity)
        normalized.append(
            {
                "role": role,
                "logical_name": logical_name,
                "kind": kind,
                "sha256": sha256,
            }
        )

    canonical = sorted(
        normalized,
        key=lambda artifact: (
            artifact["role"],
            artifact["kind"],
            artifact["logical_name"],
            artifact["sha256"],
        ),
    )
    if normalized != canonical:
        raise ContractError(
            f"{path}:{row_number}: implementation_artifacts_json must use canonical artifact order"
        )
    return canonical


def validate_stage_contracts(path: Path, *, topology_events: pd.DataFrame) -> pd.DataFrame:
    """Validate semantic equivalence metadata for physical common-prefix stage instances."""
    df = _validate_native_sidecar(path, STAGE_CONTRACT_COLUMNS, STAGE_CONTRACT_NUMERIC_COLUMNS).copy()
    version_values = pd.to_numeric(df["semantic_contract_version"], errors="raise")
    versions = version_values.astype(int)
    if not (version_values == versions).all():
        raise ContractError(f"{path}: semantic_contract_version must be an integer")
    if set(versions) != {STAGE_SEMANTIC_CONTRACT_VERSION}:
        raise ContractError(
            f"{path}: semantic_contract_version must equal {STAGE_SEMANTIC_CONTRACT_VERSION}"
        )
    if set(df["contract_provenance"].astype(str)) - _STAGE_CONTRACT_PROVENANCE:
        raise ContractError(f"{path}: stage contracts must come from runtime_loaded_configuration")
    if set(df["implementation_artifact_provenance"].astype(str)) - _STAGE_ARTIFACT_PROVENANCE:
        raise ContractError(f"{path}: stage artifacts must come from runtime_loaded_artifacts_v1")
    if df["contract_id"].astype(str).duplicated().any():
        raise ContractError(f"{path}: contract_id must be unique")
    if len(set(df["run_id"].astype(str))) != 1:
        raise ContractError(f"{path}: one run directory must contain one stage-contract run_id")

    required_topology_columns = {
        "run_id",
        "event_kind",
        "execution_domain",
        "stage",
    }
    missing_topology_columns = sorted(required_topology_columns - set(topology_events.columns))
    if missing_topology_columns:
        raise ContractError(
            "topology events are missing stage-contract linkage columns: "
            + ", ".join(missing_topology_columns)
        )
    expected_keys: set[tuple[str, str, str]] = set()
    expected_base_stages: set[str] = set()
    for row in topology_events.to_dict(orient="records"):
        stage = str(row["stage"])
        base_stage = stage_base_name(stage)
        if str(row["event_kind"]) != "stage_complete" or base_stage not in _COMMON_PREFIX_STAGES:
            continue
        expected_keys.add((str(row["run_id"]), str(row["execution_domain"]), stage))
        expected_base_stages.add(base_stage)
    if expected_base_stages != _COMMON_PREFIX_STAGES:
        raise ContractError(f"{path}: topology trace must contain decode and preprocess stage executions")

    observed_keys: set[tuple[str, str, str]] = set()
    semantic_payloads: dict[str, list[dict[str, Any]]] = {stage: [] for stage in _COMMON_PREFIX_STAGES}
    row_stage_hashes: list[str] = []
    for row_index, row in df.iterrows():
        row_number = int(row_index) + 2
        required_text = {
            "run_id": row["run_id"],
            "contract_id": row["contract_id"],
            "execution_domain": row["execution_domain"],
            "stage": row["stage"],
            "base_stage": row["base_stage"],
            "implementation_name": row["implementation_name"],
            "implementation_version": row["implementation_version"],
            "output_media_type": row["output_media_type"],
            "output_format": row["output_format"],
            "output_dtype": row["output_dtype"],
            "ordering_contract": row["ordering_contract"],
        }
        invalid_text = [
            field
            for field, value in required_text.items()
            if not str(value).strip() or str(value).strip().lower() in {"unknown", "unavailable", "none", "nan"}
        ]
        if invalid_text:
            raise ContractError(
                f"{path}:{row_number}: stage contract fields must be explicit: {', '.join(invalid_text)}"
            )
        stage = str(row["stage"])
        base_stage = str(row["base_stage"])
        if base_stage not in _COMMON_PREFIX_STAGES or stage_base_name(stage) != base_stage:
            raise ContractError(f"{path}:{row_number}: base_stage does not match decode/preprocess stage")
        key = (str(row["run_id"]), str(row["execution_domain"]), stage)
        if key in observed_keys:
            raise ContractError(f"{path}:{row_number}: duplicate execution_domain/stage contract")
        observed_keys.add(key)

        implementation_config = _parse_json_field(
            row["implementation_config_json"],
            path=path,
            row_number=row_number,
            column="implementation_config_json",
            expected_type=dict,
        )
        if not implementation_config:
            raise ContractError(f"{path}:{row_number}: implementation_config_json must not be empty")
        expected_config_sha = _canonical_json_sha256(implementation_config)
        raw_config_sha = str(row["config_sha256"]).strip()
        config_sha = raw_config_sha.lower()
        if (
            raw_config_sha != config_sha
            or len(config_sha) != 64
            or any(character not in "0123456789abcdef" for character in config_sha)
        ):
            raise ContractError(f"{path}:{row_number}: config_sha256 must be a lowercase SHA-256 digest")
        if config_sha != expected_config_sha:
            raise ContractError(f"{path}:{row_number}: config_sha256 does not match implementation_config_json")

        implementation_artifacts = _validate_implementation_artifacts(
            row["implementation_artifacts_json"],
            path=path,
            row_number=row_number,
        )
        expected_artifacts_sha = _canonical_json_sha256(implementation_artifacts)
        raw_artifacts_sha = str(row["implementation_artifacts_sha256"]).strip()
        artifacts_sha = raw_artifacts_sha.lower()
        if raw_artifacts_sha != artifacts_sha or not re.fullmatch(r"[0-9a-f]{64}", artifacts_sha):
            raise ContractError(
                f"{path}:{row_number}: implementation_artifacts_sha256 must be a lowercase SHA-256 digest"
            )
        if artifacts_sha != expected_artifacts_sha:
            raise ContractError(
                f"{path}:{row_number}: implementation_artifacts_sha256 does not match "
                "implementation_artifacts_json"
            )

        transform = _validate_transform_contract(row["transform_json"], path=path, row_number=row_number)
        output_shape = _validate_output_shape(row["output_shape_json"], path=path, row_number=row_number)
        payload = {
            "base_stage": base_stage,
            "implementation_name": str(row["implementation_name"]),
            "implementation_version": str(row["implementation_version"]),
            "implementation_config": implementation_config,
            "implementation_artifacts": implementation_artifacts,
            "implementation_artifact_provenance": str(row["implementation_artifact_provenance"]),
            "transform": transform,
            "output_media_type": str(row["output_media_type"]),
            "output_format": str(row["output_format"]),
            "output_dtype": str(row["output_dtype"]),
            "output_shape": output_shape,
            "ordering_contract": str(row["ordering_contract"]),
        }
        semantic_payloads[base_stage].append(payload)
        row_stage_hashes.append(_canonical_json_sha256(payload))

    if observed_keys != expected_keys:
        missing = expected_keys - observed_keys
        extra = observed_keys - expected_keys
        raise ContractError(
            f"{path}: stage contracts do not exactly cover topology common-prefix instances "
            f"(missing={len(missing)}, extra={len(extra)})"
        )
    for base_stage, payloads in semantic_payloads.items():
        hashes = {_canonical_json_sha256(payload) for payload in payloads}
        if len(hashes) != 1:
            raise ContractError(
                f"{path}: {base_stage} contracts differ across execution domains; reuse is not semantically admissible"
            )

    result = df[STAGE_CONTRACT_COLUMNS].copy()
    result["semantic_stage_sha256"] = row_stage_hashes
    result["semantic_contract_claim_eligible"] = True
    return result


def semantic_prefix_contract_sha256(stage_contracts: pd.DataFrame) -> str:
    by_stage: dict[str, str] = {}
    for base_stage, group in stage_contracts.groupby("base_stage", dropna=False):
        hashes = set(group["semantic_stage_sha256"].astype(str))
        if len(hashes) != 1:
            raise ContractError(f"semantic stage hash is not unique for {base_stage}")
        by_stage[str(base_stage)] = next(iter(hashes))
    if set(by_stage) != _COMMON_PREFIX_STAGES:
        raise ContractError("semantic prefix hash requires decode and preprocess contracts")
    return _canonical_json_sha256(by_stage)


def assess_decoder_placement(
    stage_contracts: pd.DataFrame,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Assess selected decoder identity without treating it as NVDEC busy-time evidence."""
    decode_rows = stage_contracts[stage_contracts["base_stage"].astype(str) == "decode"]
    factory_values: list[str] = []
    raw_configs = (
        decode_rows["implementation_config_json"].astype(str)
        if "implementation_config_json" in decode_rows.columns
        else pd.Series(dtype=str)
    )
    for raw_config in raw_configs:
        try:
            config = json.loads(raw_config)
        except json.JSONDecodeError:
            config = {}
        factory = config.get("decoder_factory") if isinstance(config, dict) else None
        if isinstance(factory, str) and factory.strip():
            factory_values.append(factory.strip())

    factories = set(factory_values)
    identity_complete = bool(
        not decode_rows.empty
        and len(factory_values) == len(decode_rows)
        and len(factories) == 1
    )
    factory = next(iter(factories)) if identity_complete else "unavailable"
    allowed_factories = {str(value) for value in contract.get("allowed_factories", [])}
    factory_allowed = bool(identity_complete and factory in allowed_factories)
    verified = bool(
        identity_complete
        and factory_allowed
        and str(contract.get("required_resource", "")) == "nvdec"
        and str(contract.get("software_fallback", "")) == "prohibited"
    )
    return {
        "decoder_placement_verified": verified,
        "decoder_placement_contract_version": int(contract.get("contract_version", 0) or 0),
        "decoder_required_resource": str(contract.get("required_resource", "")),
        "decoder_factory_identity_complete": identity_complete,
        "decoder_factory": factory,
        "decoder_factory_allowed": factory_allowed,
        "decoder_factory_identity_source": str(contract.get("factory_identity_source", "")),
        "decoder_placement_evidence_limit": str(contract.get("evidence_limit", "")),
    }


def _validate_policy_event_linkage(
    decisions: pd.DataFrame,
    events: pd.DataFrame,
    *,
    path: Path,
) -> None:
    event_by_key: dict[tuple[str, str, int, int, str], tuple[str, int, float]] = {}
    for event in events.to_dict(orient="records"):
        key = (
            str(event["run_id"]),
            str(event["trace_id"]),
            int(event["stream_id"]),
            int(event["frame_id"]),
            str(event["stage"]),
        )
        value = (
            str(event["resource"]).strip().lower(),
            int(float(event["queue_depth"])),
            float(event["estimated_cost_ms"]),
        )
        if key in event_by_key:
            raise ContractError(f"{path}: frame_events.csv contains duplicate stage linkage key {key}")
        event_by_key[key] = value

    applied_keys: set[tuple[str, str, int, int, str]] = set()
    for row_index, row in decisions.iterrows():
        if str(row["decision_mode"]) != "applied":
            continue
        row_number = int(row_index) + 2
        key = (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
            str(row["stage"]),
        )
        if key in applied_keys:
            raise ContractError(f"{path}:{row_number}: duplicate applied policy decision for linkage key {key}")
        applied_keys.add(key)
        if key not in event_by_key:
            raise ContractError(f"{path}:{row_number}: applied policy decision has no matching frame event")
        event_resource, event_queue_depth, event_cost = event_by_key[key]
        decision_resource = str(row["resource"]).strip().lower()
        if decision_resource != event_resource:
            raise ContractError(f"{path}:{row_number}: policy decision resource does not match frame event")
        decision_queue_depth = int(float(row["queue_depth"]))
        if decision_queue_depth != event_queue_depth:
            raise ContractError(f"{path}:{row_number}: policy decision queue depth does not match frame event")
        decision_cost = float(row["estimated_cost_ms"])
        if not math.isclose(decision_cost, event_cost, rel_tol=1e-9, abs_tol=1e-9):
            raise ContractError(f"{path}:{row_number}: policy decision cost does not match frame event")


def validate_required_sidecars(
    run_dir: Path,
    *,
    require_labeled_provenance: bool = False,
    require_full_policy_trace: bool = False,
    require_causal_policy_trace: bool = False,
    require_online_policy_trace: bool = False,
    require_ingress_ledger: bool = False,
    require_branch_terminals: bool = False,
    require_stage_contracts: bool = False,
    require_reset_evidence: bool = False,
    required_branches: list[str] | tuple[str, ...] | None = None,
    topology_kind: str | None = None,
    expected_streams: int | None = None,
    require_full_resource_evidence: bool = False,
    expected_run_id: str = "",
    frames: pd.DataFrame | None = None,
    topology_events: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    sidecars = {
        "resource_events": validate_resource_events(
            run_dir / "resource_events.csv",
            require_labeled_provenance=require_labeled_provenance,
        ),
        "policy_decisions": validate_policy_decisions(
            run_dir / "policy_decisions.csv",
            require_labeled_provenance=require_labeled_provenance,
            require_full_trace=require_full_policy_trace,
            require_causal_trace=require_causal_policy_trace,
        ),
        "drop_counters": validate_drop_counters(
            run_dir / "drop_counters.csv",
            require_labeled_provenance=require_labeled_provenance,
        ),
    }
    events = validate_frame_events(run_dir / "frame_events.csv")
    sidecars["frame_events"] = events
    _validate_policy_event_linkage(
        sidecars["policy_decisions"],
        events,
        path=run_dir / "policy_decisions.csv",
    )
    feedback_path = run_dir / "policy_feedback.csv"
    if feedback_path.exists() or require_online_policy_trace:
        sidecars["policy_feedback"] = validate_policy_feedback(
            feedback_path,
            decisions=sidecars["policy_decisions"],
            require_complete=require_online_policy_trace,
        )
    ingress_path = run_dir / "ingress_ledger.csv"
    if ingress_path.exists() or require_ingress_ledger:
        if frames is None:
            frames = canonicalize_frames_csv(
                run_dir / "frames.csv",
                mode="benchmark",
                run_id="",
                detector="",
                backend="",
            )
        sidecars["ingress_ledger"] = validate_ingress_ledger(
            ingress_path,
            frames=frames,
            drop_counters=sidecars["drop_counters"],
            topology_events=topology_events,
        )
    reset_path = run_dir / "reset_evidence.csv"
    if reset_path.exists() or require_reset_evidence:
        ingress = sidecars.get("ingress_ledger")
        if ingress is None:
            raise ContractError(f"{reset_path}: reset validation requires accepted ingress_ledger.csv")
        if topology_kind is None or expected_streams is None or required_branches is None:
            raise ContractError(
                f"{reset_path}: reset validation requires topology kind, stream count, and branch set"
            )
        sidecars["reset_evidence"] = validate_reset_evidence(
            reset_path,
            ingress_ledger=ingress,
            topology_kind=topology_kind,
            expected_streams=expected_streams,
            required_branches=required_branches,
        )
    branch_terminal_path = run_dir / "branch_terminals.csv"
    if branch_terminal_path.exists() or require_branch_terminals:
        if frames is None:
            frames = canonicalize_frames_csv(
                run_dir / "frames.csv",
                mode="benchmark",
                run_id="",
                detector="",
                backend="",
            )
        ingress = sidecars.get("ingress_ledger")
        if ingress is None:
            raise ContractError(
                f"{branch_terminal_path}: branch terminal validation requires accepted ingress_ledger.csv"
            )
        sidecars["branch_terminals"] = validate_branch_terminals(
            branch_terminal_path,
            ingress_ledger=ingress,
            frames=frames,
            required_branches=required_branches,
        )
    stage_contract_path = run_dir / "stage_contracts.csv"
    if stage_contract_path.exists() or require_stage_contracts:
        if topology_events is None:
            raise ContractError(
                f"{stage_contract_path}: stage semantic validation requires accepted topology events"
            )
        sidecars["stage_contracts"] = validate_stage_contracts(
            stage_contract_path,
            topology_events=topology_events,
        )
    if require_full_resource_evidence:
        ingress = sidecars.get("ingress_ledger")
        if ingress is None or topology_events is None or topology_kind is None:
            raise ContractError(
                "full resource evidence requires accepted ingress and topology sidecars"
            )
        if not expected_run_id:
            raise ContractError("full resource evidence requires expected_run_id")
        try:
            from full_resource_contract import validate_full_resource_evidence

            full_resource = validate_full_resource_evidence(
                run_dir,
                expected_run_id=expected_run_id,
                ingress_ledger=ingress,
                topology_events=topology_events,
                frame_events=events,
                topology_kind=topology_kind,
            )
        except RuntimeError as exc:
            raise ContractError(f"full resource evidence rejected: {exc}") from exc
        for name in (
            "resource_intervals",
            "hardware_resource_samples",
            "fanout_work_counters",
        ):
            sidecars[name] = full_resource[name]
        sidecars["resource_intervals"].attrs["full_resource_summary"] = full_resource[
            "summary"
        ]
    return sidecars


def _camera_roles(dataset: dict[str, Any]) -> dict[int, str]:
    roles: dict[int, str] = {}
    for index, stream in enumerate(dataset.get("streams", [])):
        stream_id = int(stream.get("stream_id", index))
        roles[stream_id] = str(stream.get("camera_role", "unknown"))
    return roles


def _frame_transfer_bytes(dataset: dict[str, Any], stream_id: int) -> int:
    streams = list(dataset.get("streams", []))
    if not streams:
        return 0
    selected = None
    for index, stream in enumerate(streams):
        if int(stream.get("stream_id", index)) == int(stream_id):
            selected = stream
            break
    if selected is None:
        selected = streams[int(stream_id) % len(streams)]
    width = int(selected.get("width", 0) or 0)
    height = int(selected.get("height", 0) or 0)
    return max(0, width * height * 3)


def write_provenance_labeled_sidecars(
    run_dir: Path,
    *,
    frames: pd.DataFrame,
    events: pd.DataFrame,
    dataset: dict[str, Any],
    policy: str,
    deadline_ms: float,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    event_rows: list[dict[str, Any]] = []
    policy_rows: list[dict[str, Any]] = []
    for event in events.to_dict(orient="records"):
        start = float(event["stage_start_timestamp_ms"])
        end = float(event["stage_end_timestamp_ms"])
        duration = max(0.0, end - start)
        resource = str(event["resource"])
        bytes_per_frame = _frame_transfer_bytes(dataset, int(event["stream_id"]))
        is_gpu = resource.lower() == "gpu"
        event_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": event["run_id"],
                "trace_id": event["trace_id"],
                "stream_id": int(event["stream_id"]),
                "frame_id": int(event["frame_id"]),
                "stage": event["stage"],
                "resource": resource,
                "timestamp_ms": round(end, 6),
                "cpu_time_ms": round(0.0 if is_gpu else duration, 6),
                "gpu_time_ms": round(duration if is_gpu else 0.0, 6),
                "h2d_bytes": bytes_per_frame if is_gpu else 0,
                "d2h_bytes": max(0, bytes_per_frame // 12) if is_gpu else 0,
                "nvdec_util_percent": 1.0 if stage_base_name(str(event["stage"])) == "decode" else 0.0,
                "vram_mb": round(bytes_per_frame / (1024 * 1024), 6) if is_gpu else 0.0,
                "time_provenance": "derived_from_native_stage_timestamps",
                "transfer_provenance": "estimated_from_frame_dimensions",
                "nvdec_provenance": "stage_presence_proxy",
                "vram_provenance": "estimated_from_frame_dimensions",
                "telemetry_source": "native",
            }
        )
        action = str(event.get("policy_action", ""))
        policy_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": event["run_id"],
                "trace_id": event["trace_id"],
                "stream_id": int(event["stream_id"]),
                "frame_id": int(event["frame_id"]),
                "stage": event["stage"],
                "policy": policy,
                "decision": action or f"{policy}:{resource}",
                "resource": resource,
                "queue_depth": int(float(event["queue_depth"])),
                "estimated_cost_ms": float(event["estimated_cost_ms"]),
                "deadline_ms": float(deadline_ms),
                "policy_version": "unavailable",
                "allowed_resources_json": "[]",
                "alternative_scores_json": json.dumps(
                    {resource.lower(): float(event["estimated_cost_ms"])},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "cost_components_json": "{}",
                "parameters_json": "{}",
                "tie_break_rule": "unavailable",
                "decision_mode": "applied",
                "update_seq": 0,
                "update_json": "{}",
                "reason": "derived_selected_action_only",
                "decision_id": "unavailable",
                "decision_seq": 0,
                "decision_timestamp_ms": 0.0,
                "graph_version": "unavailable",
                "profile_version": "unavailable",
                "feature_provenance_json": "{}",
                "terminal_status": "unavailable",
                "terminal_timestamp_ms": 0.0,
                "update_timestamp_ms": 0.0,
                "source_decision_ids_json": "[]",
                "first_consumer_decision_id": "unavailable",
                "first_consumer_decision_seq": 0,
                "causal_trace_completeness": "not_available",
                "decision_provenance": "derived_from_native_frame_event",
                "trace_completeness": "selected_action_only",
                "telemetry_source": "native",
            }
        )

    resource_path = run_dir / "resource_events.csv"
    if resource_path.exists():
        validate_resource_events(resource_path, require_labeled_provenance=True)
    else:
        pd.DataFrame(event_rows, columns=RESOURCE_EVENT_COLUMNS).to_csv(resource_path, index=False)

    policy_path = run_dir / "policy_decisions.csv"
    if policy_path.exists():
        validate_policy_decisions(policy_path, require_labeled_provenance=True)
    else:
        pd.DataFrame(policy_rows, columns=POLICY_DECISION_COLUMNS).to_csv(policy_path, index=False)

    roles = _camera_roles(dataset)
    drop_rows: list[dict[str, Any]] = []
    frame_df = frames.copy()
    frame_df["stream_id"] = pd.to_numeric(frame_df["stream_id"], errors="raise").astype(int)
    frame_df["frame_id"] = pd.to_numeric(frame_df["frame_id"], errors="raise").astype(int)
    frame_df["e2e_latency_ms"] = pd.to_numeric(frame_df["e2e_latency_ms"], errors="raise")
    run_id = str(frame_df["run_id"].iloc[0])
    for stream_id, group in frame_df.groupby("stream_id", dropna=False):
        unique_frames = sorted(set(int(value) for value in group["frame_id"]))
        expected = unique_frames[-1] - unique_frames[0] + 1 if unique_frames else 0
        total = len(unique_frames)
        dropped = max(0, expected - total)
        late = int((group["e2e_latency_ms"] > float(deadline_ms)).sum())
        denom = max(1, expected)
        drop_rows.append(
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "run_id": run_id,
                "stream_id": int(stream_id),
                "camera_role": roles.get(int(stream_id), "unknown"),
                "dropped_frames": dropped,
                "late_frames": late,
                "total_frames": int(group.shape[0]),
                "deadline_ms": float(deadline_ms),
                "drop_rate_percent": round(dropped / denom * 100.0, 6),
                "late_rate_percent": round(late / max(1, int(group.shape[0])) * 100.0, 6),
                "reason": "frame_id_gap" if dropped else ("deadline_miss" if late else "no_drop_or_late"),
                "drop_provenance": "inferred_from_frame_id_gaps",
                "late_provenance": "derived_from_native_frame_latency",
                "telemetry_source": "native",
            }
        )
    drop_path = run_dir / "drop_counters.csv"
    if drop_path.exists():
        validate_drop_counters(drop_path, require_labeled_provenance=True)
    else:
        pd.DataFrame(drop_rows, columns=DROP_COUNTER_COLUMNS).to_csv(drop_path, index=False)


def write_derived_native_sidecars(
    run_dir: Path,
    *,
    frames: pd.DataFrame,
    events: pd.DataFrame,
    dataset: dict[str, Any],
    policy: str,
    deadline_ms: float,
) -> None:
    write_provenance_labeled_sidecars(
        run_dir,
        frames=frames,
        events=events,
        dataset=dataset,
        policy=policy,
        deadline_ms=deadline_ms,
    )


def _provenance_supports(
    df: pd.DataFrame,
    column: str,
    accepted: set[str],
    *,
    require_observed: str | None = None,
) -> bool:
    values = set(df[column].astype(str))
    return bool(values) and values.issubset(accepted) and (require_observed is None or require_observed in values)


MEASUREMENT_PASSPORT_CONTRACT_VERSION = 4
RESOURCE_ATTRIBUTION_RULE = "native_per_trace_bounded_stage_interval_ingress_cohort_v3"
MEASUREMENT_STAGE_REDUCTION_RULE = "decode_preprocess_suffix_reduction_v1"
MEASUREMENT_RESOURCE_TIME_PROVENANCE = {
    "native_hardware_counter",
    "derived_from_native_stage_timestamps",
}


def build_measurement_signature_payload(time_provenance: list[str]) -> dict[str, Any]:
    """Return the complete canonical semantics of measurement passport v4."""
    return {
        "contract_version": MEASUREMENT_PASSPORT_CONTRACT_VERSION,
        "resource_attribution": RESOURCE_ATTRIBUTION_RULE,
        "resource_time_components": ["cpu_time_ms", "gpu_time_ms"],
        "resource_time_aggregation": (
            "unweighted_sum_of_attributed_device_milliseconds_v1"
        ),
        "resource_time_non_equivalence": (
            "not_energy_flops_monetary_cost_or_cross_device_equivalent_work_v1"
        ),
        "resource_time_provenance": time_provenance,
        "resource_interval_linkage": "one_to_one_frame_event_stage_interval_v1",
        "resource_event_coverage": "all_frame_events_for_closed_ingress_cohort",
        "stage_interval_cohort_bounds": (
            "ingress_le_queue_enter_le_stage_start_le_stage_end_le_terminal_v1"
        ),
        "derived_time_semantics": "stage_end_minus_stage_start_excluding_queue_wait",
        "transfer_time_components": [],
        "nvdec_busy_time_included": False,
        "fanout_time_included": False,
        "stage_reduction_rule": MEASUREMENT_STAGE_REDUCTION_RULE,
        "cohort_terminal_rule": "completed_or_native_drop_no_censored",
    }


def measurement_signature_payload_is_valid(
    payload: Any,
    *,
    resource_attribution: str,
) -> bool:
    """Validate the full fail-closed payload, including provenance ordering."""
    if not isinstance(payload, dict):
        return False
    time_provenance = payload.get("resource_time_provenance")
    if (
        not isinstance(time_provenance, list)
        or not time_provenance
        or any(not isinstance(value, str) for value in time_provenance)
        or time_provenance != sorted(set(time_provenance))
        or not set(time_provenance).issubset(MEASUREMENT_RESOURCE_TIME_PROVENANCE)
        or resource_attribution != RESOURCE_ATTRIBUTION_RULE
    ):
        return False
    return payload == build_measurement_signature_payload(time_provenance)


def measurement_signature_identity_is_valid(
    payload_json: Any,
    signature: Any,
    *,
    resource_attribution: str,
) -> bool:
    """Require the exact canonical JSON bytes, complete semantics, and SHA-256."""
    if not isinstance(payload_json, str) or not isinstance(signature, str):
        return False
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    if payload_json != canonical:
        return False
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest == signature and measurement_signature_payload_is_valid(
        payload,
        resource_attribution=resource_attribution,
    )


def _ordered_ingress_rows(ingress: pd.DataFrame) -> pd.DataFrame:
    return ingress.sort_values(["stream_id", "admission_seq"], kind="stable").reset_index(drop=True)


def input_schedule_sha256(ingress: pd.DataFrame) -> str:
    ordered = _ordered_ingress_rows(ingress)
    rows = [
        {
            "stream_id": int(row.stream_id),
            "admission_seq": int(row.admission_seq),
            "source_sha256": str(row.source_sha256),
            "source_cycle": int(row.source_cycle),
            "access_unit_pts_ns": int(row.access_unit_pts_ns),
            "payload_sha256": str(row.payload_sha256),
            "payload_size_bytes": int(row.payload_size_bytes),
            "schedule_offset_ns": int(row.schedule_offset_ns),
        }
        for row in ordered.itertuples(index=False)
    ]
    return _canonical_json_sha256(rows)


def input_frame_key_sequence_sha256(ingress: pd.DataFrame) -> str:
    ordered = _ordered_ingress_rows(ingress)
    rows = [
        {
            "stream_id": int(row.stream_id),
            "admission_seq": int(row.admission_seq),
            "input_frame_key": str(row.input_frame_key),
        }
        for row in ordered.itertuples(index=False)
    ]
    return _canonical_json_sha256(rows)


def summarize_measurement_passport(
    resources: pd.DataFrame,
    ingress: pd.DataFrame,
    frame_events: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Derive a claim-gating passport from accepted native sidecars only."""
    unavailable = {
        "resource_attribution_complete": False,
        "resource_attribution": "unavailable",
        "resource_attributed_ingress_count": 0,
        "resource_unattributed_event_count": int(resources.shape[0]),
        "input_schedule_sha256": input_schedule_sha256(ingress),
        "input_frame_key_sequence_sha256": input_frame_key_sequence_sha256(ingress),
        "measurement_window_duration_ms": round(
            float(ingress["window_end_timestamp_ms"].iloc[0])
            - float(ingress["window_start_timestamp_ms"].iloc[0]),
            6,
        ),
        "measurement_signature": "unavailable",
        "measurement_signature_payload_json": "{}",
        "c_obs_total_ms": float("nan"),
        "c_obs_cpu_total_ms": float("nan"),
        "c_obs_gpu_total_ms": float("nan"),
        "c_obs_in_ms_per_ingress": float("nan"),
        "c_obs_cpu_in_ms_per_ingress": float("nan"),
        "c_obs_gpu_in_ms_per_ingress": float("nan"),
        "c_obs_comp_ms_per_completed": float("nan"),
        "c_obs_is_partial": True,
    }
    if resources.empty or ingress.empty or frame_events is None or frame_events.empty:
        return unavailable

    frame_key_columns = ["run_id", "trace_id", "stream_id", "frame_id"]
    interval_key_columns = [*frame_key_columns, "stage", "resource"]
    ledger = ingress.copy()
    resource_rows = resources.copy()
    stage_rows = frame_events.copy()
    for frame in (ledger, resource_rows, stage_rows):
        frame["stream_id"] = pd.to_numeric(frame["stream_id"], errors="raise").astype(int)
        frame["frame_id"] = pd.to_numeric(frame["frame_id"], errors="raise").astype(int)
    ledger_keys = {
        tuple(row)
        for row in ledger[frame_key_columns].itertuples(index=False, name=None)
    }
    resource_frame_keys = [
        tuple(row)
        for row in resource_rows[frame_key_columns].itertuples(index=False, name=None)
    ]
    resource_frame_key_set = set(resource_frame_keys)
    unattributed_count = sum(key not in ledger_keys for key in resource_frame_keys)
    covered_keys = ledger_keys.intersection(resource_frame_key_set)

    stage_rows["frame_key"] = list(
        stage_rows[frame_key_columns].itertuples(index=False, name=None)
    )
    cohort_stage_rows = stage_rows[stage_rows["frame_key"].isin(ledger_keys)].copy()
    resource_interval_keys = [
        tuple(row)
        for row in resource_rows[interval_key_columns].itertuples(index=False, name=None)
    ]
    stage_interval_keys = [
        tuple(row)
        for row in cohort_stage_rows[interval_key_columns].itertuples(index=False, name=None)
    ]

    def duplicate_count(keys: list[tuple[Any, ...]]) -> int:
        counts: dict[tuple[Any, ...], int] = {}
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        return sum(count - 1 for count in counts.values() if count > 1)

    interval_sets_match = bool(
        stage_interval_keys
        and set(resource_interval_keys) == set(stage_interval_keys)
        and duplicate_count(resource_interval_keys) == 0
        and duplicate_count(stage_interval_keys) == 0
    )

    ledger_bounds = {
        tuple(row[column] for column in frame_key_columns): (
            float(row["ingress_timestamp_ms"]),
            float(row["terminal_timestamp_ms"]),
        )
        for row in ledger.to_dict(orient="records")
    }
    timestamps_in_bounds = True
    stages_by_key: dict[tuple[Any, ...], set[str]] = {}
    for row, key in zip(
        resource_rows.to_dict(orient="records"),
        resource_frame_keys,
        strict=True,
    ):
        stages_by_key.setdefault(key, set()).add(stage_base_name(str(row["stage"])))
        bounds = ledger_bounds.get(key)
        if bounds is None:
            timestamps_in_bounds = False
            continue
        timestamp = float(row["timestamp_ms"])
        if timestamp < bounds[0] or timestamp > bounds[1]:
            timestamps_in_bounds = False

    prefix_covered = all(
        {"decode", "preprocess"}.issubset(stages_by_key.get(key, set()))
        for key in ledger_keys
    )
    cpu_time = pd.to_numeric(resource_rows["cpu_time_ms"], errors="coerce")
    gpu_time = pd.to_numeric(resource_rows["gpu_time_ms"], errors="coerce")
    finite_nonnegative_time = bool(
        cpu_time.notna().all()
        and gpu_time.notna().all()
        and (cpu_time >= 0).all()
        and (gpu_time >= 0).all()
    )
    time_provenance = sorted(set(resource_rows["time_provenance"].astype(str)))
    valid_time_provenance = set(time_provenance).issubset(
        MEASUREMENT_RESOURCE_TIME_PROVENANCE
    )
    interval_time_consistent = interval_sets_match
    if interval_sets_match:
        stage_by_interval = {
            tuple(row[column] for column in interval_key_columns): row
            for row in cohort_stage_rows.to_dict(orient="records")
        }
        for resource_row, interval_key in zip(
            resource_rows.to_dict(orient="records"),
            resource_interval_keys,
            strict=True,
        ):
            stage_row = stage_by_interval[interval_key]
            queue_enter = float(stage_row["queue_enter_timestamp_ms"])
            stage_start = float(stage_row["stage_start_timestamp_ms"])
            stage_end = float(stage_row["stage_end_timestamp_ms"])
            resource_timestamp = float(resource_row["timestamp_ms"])
            cpu_value = float(resource_row["cpu_time_ms"])
            gpu_value = float(resource_row["gpu_time_ms"])
            resource_name = str(resource_row["resource"]).strip().lower()
            provenance = str(resource_row["time_provenance"])
            ingress_timestamp, terminal_timestamp = ledger_bounds[
                interval_key[: len(frame_key_columns)]
            ]
            if not (
                math.isfinite(ingress_timestamp)
                and math.isfinite(terminal_timestamp)
                and math.isfinite(queue_enter)
                and math.isfinite(stage_start)
                and math.isfinite(stage_end)
                and math.isfinite(resource_timestamp)
                and ingress_timestamp
                <= queue_enter
                <= stage_start
                <= stage_end
                <= terminal_timestamp
                and stage_start <= resource_timestamp <= stage_end
            ):
                interval_time_consistent = False
                break
            if resource_name == "cpu":
                resource_component_consistent = math.isclose(
                    gpu_value,
                    0.0,
                    abs_tol=1e-9,
                )
            elif resource_name == "gpu":
                resource_component_consistent = math.isclose(
                    cpu_value,
                    0.0,
                    abs_tol=1e-9,
                )
            else:
                resource_component_consistent = False
            if not resource_component_consistent:
                interval_time_consistent = False
                break
            if provenance == "derived_from_native_stage_timestamps" and not math.isclose(
                cpu_value + gpu_value,
                stage_end - stage_start,
                rel_tol=1e-9,
                abs_tol=1e-6,
            ):
                interval_time_consistent = False
                break
    closed_cohort = not (ledger["terminal_status"].astype(str) == "censored").any()
    c_obs_cpu_total = float(cpu_time.sum()) if finite_nonnegative_time else float("nan")
    c_obs_gpu_total = float(gpu_time.sum()) if finite_nonnegative_time else float("nan")
    c_obs_total = c_obs_cpu_total + c_obs_gpu_total
    attribution_complete = bool(
        ledger_keys
        and covered_keys == ledger_keys
        and unattributed_count == 0
        and timestamps_in_bounds
        and prefix_covered
        and finite_nonnegative_time
        and valid_time_provenance
        and interval_time_consistent
        and closed_cohort
        and c_obs_total > 0
    )
    unavailable.update(
        {
            "resource_attribution_complete": attribution_complete,
            "resource_attributed_ingress_count": len(covered_keys),
            "resource_unattributed_event_count": unattributed_count,
        }
    )
    if not attribution_complete:
        return unavailable

    signature_payload = build_measurement_signature_payload(time_provenance)
    signature_json = json.dumps(
        signature_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    ingress_count = int(ledger.shape[0])
    completed_count = int((ledger["terminal_status"].astype(str) == "completed").sum())
    unavailable.update(
        {
            "resource_attribution": RESOURCE_ATTRIBUTION_RULE,
            "measurement_signature": hashlib.sha256(signature_json.encode("utf-8")).hexdigest(),
            "measurement_signature_payload_json": signature_json,
            "c_obs_total_ms": round(c_obs_total, 6),
            "c_obs_cpu_total_ms": round(c_obs_cpu_total, 6),
            "c_obs_gpu_total_ms": round(c_obs_gpu_total, 6),
            "c_obs_in_ms_per_ingress": round(c_obs_total / ingress_count, 9),
            "c_obs_cpu_in_ms_per_ingress": round(c_obs_cpu_total / ingress_count, 9),
            "c_obs_gpu_in_ms_per_ingress": round(c_obs_gpu_total / ingress_count, 9),
            "c_obs_comp_ms_per_completed": round(c_obs_total / completed_count, 9)
            if completed_count > 0
            else float("nan"),
        }
    )
    return unavailable


def summarize_sidecars(
    run_dir: Path,
    *,
    frames: pd.DataFrame | None = None,
    topology_events: pd.DataFrame | None = None,
    required_branches: list[str] | tuple[str, ...] | None = None,
    topology_kind: str | None = None,
    expected_streams: int | None = None,
    require_full_resource_evidence: bool = False,
    expected_run_id: str = "",
    require_reset_evidence: bool = False,
    decoder_placement_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sidecars = validate_required_sidecars(
        run_dir,
        frames=frames,
        topology_events=topology_events,
        required_branches=required_branches,
        topology_kind=topology_kind,
        require_full_resource_evidence=require_full_resource_evidence,
        expected_run_id=expected_run_id,
        expected_streams=expected_streams,
        require_reset_evidence=require_reset_evidence,
    )
    resources = sidecars["resource_events"]
    decisions = sidecars["policy_decisions"]
    drops = sidecars["drop_counters"]
    resource_time_publishable = _provenance_supports(
        resources,
        "time_provenance",
        {"native_hardware_counter", "derived_from_native_stage_timestamps"},
    )
    transfer_publishable = _provenance_supports(
        resources,
        "transfer_provenance",
        {"native_hardware_counter", "unavailable"},
        require_observed="native_hardware_counter",
    )
    nvdec_publishable = _provenance_supports(
        resources,
        "nvdec_provenance",
        {"native_hardware_counter", "unavailable"},
        require_observed="native_hardware_counter",
    )
    vram_publishable = _provenance_supports(
        resources,
        "vram_provenance",
        {"native_hardware_counter", "unavailable"},
        require_observed="native_hardware_counter",
    )
    drop_publishable = _provenance_supports(drops, "drop_provenance", {"native_drop_event"})
    late_publishable = _provenance_supports(
        drops,
        "late_provenance",
        {"native_deadline_event", "derived_from_native_frame_latency"},
    )
    result = {
        "decode_count": int((resources["stage"].astype(str).map(stage_base_name) == "decode").sum()),
        "preprocess_count": int((resources["stage"].astype(str).map(stage_base_name) == "preprocess").sum()),
        "cpu_time_ms": round(float(pd.to_numeric(resources["cpu_time_ms"], errors="coerce").sum()), 3)
        if resource_time_publishable
        else float("nan"),
        "gpu_time_ms": round(float(pd.to_numeric(resources["gpu_time_ms"], errors="coerce").sum()), 3)
        if resource_time_publishable
        else float("nan"),
        "h2d_bytes": int(pd.to_numeric(resources["h2d_bytes"], errors="coerce").fillna(0).sum())
        if transfer_publishable
        else float("nan"),
        "d2h_bytes": int(pd.to_numeric(resources["d2h_bytes"], errors="coerce").fillna(0).sum())
        if transfer_publishable
        else float("nan"),
        "nvdec_utilization_percent": round(
            float(pd.to_numeric(resources["nvdec_util_percent"], errors="coerce").mean()), 3
        )
        if nvdec_publishable
        else float("nan"),
        "vram_mb_max": round(float(pd.to_numeric(resources["vram_mb"], errors="coerce").max()), 3)
        if vram_publishable
        else float("nan"),
        "policy_decision_count": int(decisions.shape[0]),
        "policy_trace_complete": bool(decisions["policy_claim_eligible"].all()),
        "policy_causal_trace_complete": bool(decisions["causal_policy_claim_eligible"].all()),
        "policy_online_trace_complete": bool(
            "policy_feedback" in sidecars
            and sidecars["policy_feedback"]["policy_feedback_claim_eligible"].all()
        ),
        "dropped_frame_rate_percent": round(
            float(pd.to_numeric(drops["drop_rate_percent"], errors="coerce").mean()), 3
        )
        if drop_publishable
        else float("nan"),
        "late_frame_rate_percent": round(
            float(pd.to_numeric(drops["late_rate_percent"], errors="coerce").mean()), 3
        )
        if late_publishable
        else float("nan"),
    }
    full_resource_summary = (
        sidecars["resource_intervals"].attrs.get("full_resource_summary")
        if "resource_intervals" in sidecars
        else None
    )
    if full_resource_summary is None:
        result.update(
            {
                "full_resource_evidence_accepted": False,
                "full_resource_coverage_complete": False,
                "resource_contract_version": float("nan"),
                "nvdec_busy_equivalent_ns": float("nan"),
                "nvdec_counter_scope": "unavailable",
                "fanout_thread_cpu_time_ns": float("nan"),
                "fanout_work_units": float("nan"),
                "fanout_counter_scope": "unavailable",
            }
        )
    else:
        result.update(
            {
                "full_resource_evidence_accepted": bool(
                    full_resource_summary["evidence_accepted"]
                ),
                "full_resource_coverage_complete": bool(
                    full_resource_summary["full_resource_coverage_complete"]
                ),
                "resource_contract_version": int(
                    full_resource_summary["resource_contract_version"]
                ),
                "nvdec_busy_equivalent_ns": int(
                    full_resource_summary["nvdec_busy_equivalent_ns"]
                ),
                "nvdec_counter_scope": str(
                    full_resource_summary["nvdec_counter_scope"]
                ),
                "fanout_thread_cpu_time_ns": int(
                    full_resource_summary["fanout_thread_cpu_time_ns"]
                ),
                "fanout_work_units": int(full_resource_summary["fanout_work_units"]),
                "fanout_counter_scope": str(
                    full_resource_summary["fanout_counter_scope"]
                ),
            }
        )
    ingress = sidecars.get("ingress_ledger")
    if ingress is None:
        result.update(
            {
                "ingress_ledger_complete": False,
                "ingress_cohort_closed": False,
                "ingress_frame_count": float("nan"),
                "completed_frame_count": float("nan"),
                "dropped_frame_count": float("nan"),
                "censored_frame_count": float("nan"),
                "censored_frame_rate_percent": float("nan"),
                "ingress_cohort_id": "unavailable",
                "ingress_censoring_rule": "unavailable",
                "ingress_window_start_timestamp_ms": float("nan"),
                "ingress_window_end_timestamp_ms": float("nan"),
                "ingress_drain_end_timestamp_ms": float("nan"),
                "drain_duration_ms": float("nan"),
                "resource_attribution_complete": False,
                "resource_attribution": "unavailable",
                "resource_attributed_ingress_count": 0,
                "resource_unattributed_event_count": int(resources.shape[0]),
                "input_schedule_sha256": "unavailable",
                "input_frame_key_sequence_sha256": "unavailable",
                "measurement_window_duration_ms": float("nan"),
                "measurement_signature": "unavailable",
                "measurement_signature_payload_json": "{}",
                "c_obs_total_ms": float("nan"),
                "c_obs_cpu_total_ms": float("nan"),
                "c_obs_gpu_total_ms": float("nan"),
                "c_obs_in_ms_per_ingress": float("nan"),
                "c_obs_cpu_in_ms_per_ingress": float("nan"),
                "c_obs_gpu_in_ms_per_ingress": float("nan"),
                "c_obs_comp_ms_per_completed": float("nan"),
                "c_obs_is_partial": True,
            }
        )
    else:
        statuses = ingress["terminal_status"].astype(str)
        window_end = float(ingress["window_end_timestamp_ms"].iloc[0])
        drain_end = float(ingress["drain_end_timestamp_ms"].iloc[0])
        censored_count = int((statuses == "censored").sum())
        dropped_count = int((statuses == "drop").sum())
        ingress_count = int(ingress.shape[0])
        result.update(
            {
                "ingress_ledger_complete": bool(ingress["ingress_claim_eligible"].all()),
                "ingress_cohort_closed": censored_count == 0,
                "ingress_frame_count": ingress_count,
                "completed_frame_count": int((statuses == "completed").sum()),
                "dropped_frame_count": dropped_count,
                "censored_frame_count": censored_count,
                "censored_frame_rate_percent": round(censored_count / ingress_count * 100.0, 6),
                "ingress_cohort_id": str(ingress["cohort_id"].iloc[0]),
                "ingress_censoring_rule": str(ingress["censoring_rule"].iloc[0]),
                "ingress_window_start_timestamp_ms": float(ingress["window_start_timestamp_ms"].iloc[0]),
                "ingress_window_end_timestamp_ms": window_end,
                "ingress_drain_end_timestamp_ms": drain_end,
                "drain_duration_ms": round(drain_end - window_end, 6),
                "dropped_frame_rate_percent": round(dropped_count / ingress_count * 100.0, 6),
            }
        )
        result.update(
            summarize_measurement_passport(
                resources,
                ingress,
                sidecars["frame_events"],
            )
        )

    branch_terminals = sidecars.get("branch_terminals")
    if branch_terminals is None:
        result.update(
            {
                "branch_terminal_trace_complete": False,
                "branch_terminal_event_count": float("nan"),
                "native_branch_drop_event_count": float("nan"),
                "checkpoint_frame_aggregation_complete": False,
                "branch_analytics_contract_sha256": "unavailable",
            }
        )
    else:
        terminal_statuses = branch_terminals["terminal_status"].astype(str)
        result.update(
            {
                "branch_terminal_trace_complete": bool(
                    branch_terminals["branch_terminal_claim_eligible"].all()
                ),
                "branch_terminal_event_count": int(branch_terminals.shape[0]),
                "native_branch_drop_event_count": int((terminal_statuses == "drop").sum()),
                "checkpoint_frame_aggregation_complete": bool(
                    branch_terminals["branch_terminal_claim_eligible"].all()
                ),
                "branch_analytics_contract_sha256": branch_analytics_contract_sha256(
                    branch_terminals
                ),
            }
        )

    stage_contracts = sidecars.get("stage_contracts")
    if stage_contracts is None:
        result.update(
            {
                "stage_semantic_contract_complete": False,
                "semantic_contract_version": float("nan"),
                "semantic_prefix_contract_sha256": "unavailable",
                "decoder_placement_verified": False,
                "decoder_placement_contract_version": float("nan"),
                "decoder_required_resource": "unavailable",
                "decoder_factory_identity_complete": False,
                "decoder_factory": "unavailable",
                "decoder_factory_allowed": False,
                "decoder_factory_identity_source": "unavailable",
                "decoder_placement_evidence_limit": "unavailable",
            }
        )
    else:
        result.update(
            {
                "stage_semantic_contract_complete": bool(
                    stage_contracts["semantic_contract_claim_eligible"].all()
                ),
                "semantic_contract_version": int(
                    pd.to_numeric(stage_contracts["semantic_contract_version"], errors="raise").iloc[0]
                ),
                "semantic_prefix_contract_sha256": semantic_prefix_contract_sha256(stage_contracts),
            }
        )
        if decoder_placement_contract is None:
            result.update(
                {
                    "decoder_placement_verified": False,
                    "decoder_placement_contract_version": float("nan"),
                    "decoder_required_resource": "unavailable",
                    "decoder_factory_identity_complete": False,
                    "decoder_factory": "unavailable",
                    "decoder_factory_allowed": False,
                    "decoder_factory_identity_source": "unavailable",
                    "decoder_placement_evidence_limit": "unavailable",
                }
            )
        else:
            result.update(
                assess_decoder_placement(stage_contracts, decoder_placement_contract)
            )
    reset_evidence = sidecars.get("reset_evidence")
    if reset_evidence is None:
        result.update(
            {
                "reset_state_verified": False,
                "reset_contract_version": float("nan"),
                "reset_process_start_tokens_json": "[]",
                "reset_telemetry_sink_id": "unavailable",
            }
        )
    else:
        result.update(
            {
                "reset_state_verified": bool(reset_evidence["reset_claim_eligible"].all()),
                "reset_contract_version": int(
                    pd.to_numeric(reset_evidence["reset_contract_version"], errors="raise").iloc[0]
                ),
                "reset_process_start_tokens_json": json.dumps(
                    sorted(set(reset_evidence["process_start_token"].astype(str))),
                    separators=(",", ":"),
                ),
                "reset_telemetry_sink_id": str(reset_evidence["telemetry_sink_id"].iloc[0]),
            }
        )
    return result

def network_profile_matches(measured: dict[str, float], acceptance: dict[str, list[float]]) -> tuple[bool, str]:
    for key, limits in acceptance.items():
        if key not in measured:
            return False, f"missing measured network metric: {key}"
        if len(limits) != 2:
            return False, f"network acceptance range for {key} must contain [min, max]"
        lo, hi = float(limits[0]), float(limits[1])
        value = float(measured[key])
        if value < lo or value > hi:
            return False, f"{key}={value} is outside [{lo}, {hi}]"
    return True, ""


def git_manifest(project_root: Path) -> dict[str, str]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(["git", *args], cwd=project_root, text=True).strip()
        except Exception:
            return "unknown"

    status = run("status", "--porcelain")
    diff = run("diff", "--binary", "HEAD")
    return {
        "commit_sha": run("rev-parse", "HEAD"),
        "dirty": "true" if status else "false",
        "dirty_diff_sha256": hashlib.sha256((status + "\n" + diff).encode("utf-8")).hexdigest(),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
