#!/usr/bin/env python3
from __future__ import annotations

import copy
import csv
import hashlib
import json
import sys
import tempfile
import unittest
import os
import subprocess
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_adapters import select_scenarios, validate_benchmark_adapter
from benchmark_contract import (
    ContractError,
    assess_formal_aw_heft_reference,
    assess_hardware_target,
    assess_resource_interval_extension,
    assess_primary_policy_equivalence_scope,
    assess_primary_policy_runtime_compatibility,
    build_primary_architecture_runtime_plan,
    build_primary_policy_runtime_plan,
    primary_architecture_pair_metadata,
    primary_policy_pair_metadata,
    validate_primary_architecture_pair_metadata,
    validate_primary_architecture_contrast,
    validate_primary_policy_ablation,
    validate_primary_policy_pair_metadata,
)
from distributed_executor import build_distributed_plan, run_network_preflight
from generate_vast_report_artifacts import load_report_config
from run_experiments import (
    build_run_seed,
    build_primary_architecture_execution_cells,
    configured_system_names,
    default_command_timeout_s,
    expand_scenario,
    load_config,
    normalize_run_kind,
    normalize_scenario,
    resolve_execution_context,
    run_primary_architecture_execution,
    scenario_env_prefix,
    summary_fieldnames,
    validate_primary_architecture_resume_prefix,
    validate_summary_rows,
    validate_checkpoint_workload,
    validate_hardware,
    write_summary_csv,
)


SHARED_PROOF_PIPELINE = [
    "decode",
    "preprocess",
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
    "aggregate",
    "record",
]
INDEPENDENT_PROOF_PIPELINE = [
    "decode_plate_number",
    "preprocess_plate_number",
    "plate_number",
    "decode_vehicle_type",
    "preprocess_vehicle_type",
    "vehicle_type",
    "decode_damage",
    "preprocess_damage",
    "damage",
    "decode_foreign_object",
    "preprocess_foreign_object",
    "foreign_object",
    "aggregate",
    "record",
]
ACTIVE_SCENARIOS = ["checkpoint_independent_processes_baseline", "checkpoint_video_dag_shared"]


def distributed_fixture() -> dict:
    pipeline = ["decode", "preprocess", "detect", "track", "aggregate", "record"]
    return {
        "description": "Inline distributed fixture for planner tests.",
        "workload": {"streams": 6, "object_density": {"min": 1, "max": 12}},
        "pipeline": pipeline,
        "placement": {
            "policy": "fixture_edge_worker_aggregator",
            "stages": {
                "decode": "edge",
                "preprocess": "edge",
                "detect": "gpu_worker",
                "track": "gpu_worker",
                "aggregate": "aggregator",
                "record": "aggregator",
            },
        },
        "network": {"profile": "lan", "latency_ms": 5, "bandwidth_mbps": 1000, "packet_loss_percent": 0},
        "distributed": {"enabled": True, "sync_project": True},
    }


def local_fixture() -> dict:
    pipeline = ["decode", "detect", "aggregate"]
    return {
        "description": "Inline local fixture for strict adapter contract tests.",
        "benchmark_status": "supported",
        "workload": {"streams": 2, "object_density": {"min": 1, "max": 2}},
        "pipeline": pipeline,
        "placement": {
            "policy": "fixture_local_cpu_gpu",
            "stages": {stage: "local" for stage in pipeline},
        },
        "network": {"profile": "local", "latency_ms": 0, "bandwidth_mbps": 0, "packet_loss_percent": 0},
        "distributed": {"enabled": False},
    }


class ScenarioPlanningTests(unittest.TestCase):
    def test_summary_csv_serializes_pairing_passport_and_reset_fields(self) -> None:
        row = {field: "" for field in summary_fieldnames()}
        row.update({
            "timestamp": "2026-07-23T00:00:00+00:00",
            "system": "gstreamer_custom",
            "scenario": "checkpoint_video_dag_shared",
            "repeat": 1,
            "exit_code": 0,
            "status": "completed",
            "run_mode": "benchmark",
            "skip_reason": "",
            "streams": 6,
            "duration_s": 180,
            "scenario_variant": "",
            "placement_policy": "static_hybrid",
            "distributed": False,
            "deployment_mode": "heterogeneous",
            "host_topology": "single_host",
            "host_role": "local",
            "detector": "openvino",
            "backend": "gstreamer",
            "policy": "static_hybrid",
            "dataset": "kpp_real_h264",
            "deadline_ms": 100.0,
            "throughput_fps": 30.0,
            "latency_p50_ms": 25.0,
            "latency_p95_ms": 50.0,
            "latency_p99_ms": 70.0,
            "slo_violation_rate_percent": 0.0,
            "frames": 5400,
            "telemetry_source": "native",
            "seed": 20260323,
            "run_seed": 1001,
            "resource_attribution_complete": True,
            "resource_attribution": "native_per_trace_ingress_cohort_v1",
            "resource_attributed_ingress_count": 6,
            "resource_unattributed_event_count": 0,
            "input_schedule_sha256": "1" * 64,
            "input_frame_key_sequence_sha256": "2" * 64,
            "measurement_window_duration_ms": 180000.0,
            "measurement_signature": "3" * 64,
            "measurement_signature_payload_json": '{"contract_version":1}',
            "c_obs_total_ms": 108.0,
            "c_obs_cpu_total_ms": 60.0,
            "c_obs_gpu_total_ms": 48.0,
            "c_obs_in_ms_per_ingress": 18.0,
            "c_obs_cpu_in_ms_per_ingress": 10.0,
            "c_obs_gpu_in_ms_per_ingress": 8.0,
            "c_obs_comp_ms_per_completed": 18.0,
            "c_obs_is_partial": True,
            "reset_state_verified": True,
            "reset_contract_version": 1,
            "reset_process_start_tokens_json": '["' + "4" * 64 + '"]',
            "reset_telemetry_sink_id": "5" * 64,
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.csv"
            write_summary_csv(path, [row])
            with path.open("r", newline="", encoding="utf-8") as handle:
                parsed = next(csv.DictReader(handle))

        self.assertEqual(list(parsed), summary_fieldnames())
        self.assertEqual(parsed["seed"], "20260323")
        self.assertEqual(parsed["run_seed"], "1001")
        self.assertEqual(parsed["run_mode"], "benchmark")
        self.assertEqual(parsed["measurement_signature"], "3" * 64)
        self.assertEqual(parsed["reset_telemetry_sink_id"], "5" * 64)

    def test_summary_schema_accepts_incomplete_noncompleted_rows(self) -> None:
        row = {field: "" for field in summary_fieldnames() if field in {
            "timestamp", "system", "scenario", "repeat", "exit_code", "status", "run_mode", "skip_reason",
            "streams", "duration_s", "scenario_variant", "placement_policy", "distributed",
            "deployment_mode", "host_topology", "host_role", "detector", "backend", "policy",
            "dataset", "deadline_ms", "throughput_fps", "latency_p50_ms", "latency_p95_ms",
            "latency_p99_ms", "slo_violation_rate_percent", "frames", "telemetry_source",
        }}
        row["status"] = "failed"
        row["run_mode"] = "benchmark"

        validate_summary_rows([row])

    def test_summary_schema_rejects_unexpected_key_before_opening_file(self) -> None:
        row = {field: "" for field in summary_fieldnames()}
        row["status"] = "completed"
        row["run_mode"] = "benchmark"
        row["unregistered_proof_field"] = "drift"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.csv"

            with self.assertRaisesRegex(ContractError, "fields outside the stable schema.*unregistered_proof_field"):
                write_summary_csv(path, [row])

            self.assertFalse(path.exists())

    def test_summary_schema_requires_every_proof_field_for_native_completed_row(self) -> None:
        row = {field: "" for field in summary_fieldnames()}
        row["status"] = "completed"
        row["run_mode"] = "benchmark"
        row["telemetry_source"] = "native"
        del row["measurement_signature"]

        with self.assertRaisesRegex(
            ContractError,
            "benchmark completed row 1 is missing proof fields: measurement_signature",
        ):
            validate_summary_rows([row])

    def test_summary_schema_allows_smoke_completed_row_without_proof_fields(self) -> None:
        row = {field: "" for field in summary_fieldnames() if field in {
            "timestamp", "system", "scenario", "repeat", "exit_code", "status", "run_mode", "skip_reason",
            "streams", "duration_s", "scenario_variant", "placement_policy", "distributed",
            "deployment_mode", "host_topology", "host_role", "detector", "backend", "policy",
            "dataset", "deadline_ms", "throughput_fps", "latency_p50_ms", "latency_p95_ms",
            "latency_p99_ms", "slo_violation_rate_percent", "frames", "telemetry_source",
        }}
        row["status"] = "completed"
        row["run_mode"] = "smoke"
        row["telemetry_source"] = "native"

        validate_summary_rows([row])

    def test_summary_schema_rejects_non_native_benchmark_completed_row(self) -> None:
        row = {field: "" for field in summary_fieldnames()}
        row["status"] = "completed"
        row["run_mode"] = "benchmark"
        row["telemetry_source"] = "synthetic"

        with self.assertRaisesRegex(ContractError, "must use telemetry_source=native"):
            validate_summary_rows([row])

    def test_checkpoint_shared_scenario_uses_real_kpp_schema(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])

        self.assertEqual(scenario["workload"]["streams"], 6)
        self.assertEqual(scenario["workload"]["seed_group"], "kpp_real_codecs_v1")
        self.assertEqual(scenario["workload"]["logical_stream_instances"], 6)
        self.assertEqual(scenario["workload"]["recorded_source_count"], 2)
        self.assertEqual(scenario["workload"]["analytics_function_types"], 4)
        self.assertEqual(scenario["workload"]["routing_mode"], "all_branches_per_stream")
        self.assertEqual(scenario["workload"]["routing_scope"], "topology_only_stress")
        self.assertEqual(scenario["pipeline"], SHARED_PROOF_PIPELINE)
        self.assertFalse(scenario["distributed"]["enabled"])

    def test_kpp_codec_manifests_are_six_replicas_of_two_recordings(self) -> None:
        datasets = load_config(ROOT / "configs" / "datasets.yaml")["datasets"]

        for name in ("kpp_real_avi", "kpp_real_h264", "kpp_real_h265"):
            with self.subTest(dataset=name):
                dataset = datasets[name]
                self.assertEqual(len(dataset["streams"]), 6)
                self.assertEqual(len({stream["source_id"] for stream in dataset["streams"]}), 2)
                self.assertEqual(dataset["logical_stream_instances"], 6)
                self.assertEqual(dataset["unique_recorded_sources"], 2)
                self.assertEqual(dataset["analytics_routing"], "unresolved")

    def test_checkpoint_profiles_share_workload_and_deadlines(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        shared = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])
        baseline = normalize_scenario(
            "checkpoint_independent_processes_baseline",
            cfg["scenarios"]["checkpoint_independent_processes_baseline"],
        )

        self.assertEqual(shared["workload"], baseline["workload"])
        self.assertEqual(shared["workload"]["streams"], 6)
        self.assertEqual(shared["pipeline"], SHARED_PROOF_PIPELINE)
        self.assertEqual(baseline["pipeline"], INDEPENDENT_PROOF_PIPELINE)
        self.assertEqual(shared["benchmark_status"], "blocked_topology")
        self.assertEqual(baseline["benchmark_status"], "blocked_topology")
        self.assertEqual(cfg["benchmark"]["active_scenarios"], ACTIVE_SCENARIOS)
        self.assertEqual(cfg["benchmark"]["report_scenarios"], ACTIVE_SCENARIOS)
        self.assertEqual(cfg["benchmark"]["deadline_ms"], [16.7, 33.3, 50, 100, 500])
        self.assertEqual(cfg["benchmark"]["report_deadline_ms"], [16.7, 33.3, 50, 100, 500])
        self.assertNotIn(3000, cfg["benchmark"]["report_deadline_ms"])

    def test_primary_architecture_contrast_is_fully_preregistered(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        primary = validate_primary_architecture_contrast(cfg)

        self.assertEqual(primary["preregistration_version"], 4)
        self.assertEqual(
            primary["selection_basis"],
            "preexisting_defaults_and_contract_capabilities_before_results",
        )
        self.assertEqual(primary["system"], "gstreamer_custom")
        self.assertEqual(primary["policy"], "static_hybrid")
        self.assertEqual(primary["dataset"], "kpp_real_h264")
        self.assertEqual(primary["codec"], "h264")
        self.assertEqual(primary["deadline_ms"], 100)
        self.assertEqual(primary["streams"], 6)
        self.assertEqual(primary["routing_mode"], "all_branches_per_stream")
        self.assertEqual(primary["effective_batch_size"], 1)
        self.assertEqual(primary["repeats"], 10)
        self.assertEqual(primary["seed"], 20260323)
        self.assertEqual(primary["warmup_s"], 30)
        self.assertEqual(primary["measurement_s"], 180)
        self.assertEqual(primary["analytics_queue"]["max_buffers"], 1)
        self.assertEqual(primary["decoder_placement"]["required_resource"], "nvdec")
        self.assertEqual(
            primary["decoder_placement"]["allowed_factories"],
            ["nvh264dec", "nvv4l2decoder"],
        )
        self.assertEqual(
            primary["decoder_placement"]["evidence_limit"],
            "factory_selection_does_not_measure_nvdec_busy_time",
        )
        self.assertIn("decoder_placement_verified", primary["acceptance_gates"])
        self.assertEqual(
            primary["analytics_queue"]["selection_basis"],
            "minimal_positive_capacity_to_bound_backlog_before_results",
        )
        self.assertEqual(
            primary["analytics_queue"]["capacity_semantics"],
            "waiting_buffers_excluding_inflight_detector_buffer",
        )
        self.assertEqual(
            primary["arm_order"]["first_arm_by_pair"],
            [
                "checkpoint_independent_processes_baseline",
                "checkpoint_video_dag_shared",
            ]
            * 5,
        )
        self.assertEqual(primary["reset_contract"]["source_replay_origin"], "cycle_0_admission_seq_1")
        self.assertEqual(primary["reset_contract"]["evidence_contract_version"], 1)
        self.assertIn("reset_evidence.csv", primary["required_sidecars"])
        self.assertEqual(primary["pairing_keys"][0], "repeat")
        self.assertEqual(primary["pairing_keys"][-1], "measurement_signature")
        self.assertEqual(
            primary["estimand_contract"]["delta_reuse_obs_c_obs_in"]["primary_summary"],
            "median",
        )
        self.assertEqual(
            primary["estimand_contract"]["decode_preprocess_event_factor_difference"]["stages"],
            ["decode", "preprocess"],
        )
        self.assertTrue(primary["guardrails"]["identical_ingress_input_frame_keys"])
        self.assertTrue(primary["guardrails"]["positive_baseline_c_obs_in"])
        self.assertEqual(primary["guardrails"]["censored_rate_percent_each_arm"], 0.0)
        self.assertEqual(primary["interval"]["method"], "paired_percentile_bootstrap")
        self.assertEqual(primary["interval"]["statistic"], "median")
        self.assertEqual(primary["interval"]["resamples"], 10000)
        self.assertEqual(
            primary["interval"]["claim_rule"],
            "all_coprimary_lower_bounds_above_zero_and_quality_upper_bounds_at_or_below_zero_and_all_gates_pass",
        )

    def test_primary_architecture_contrast_rejects_coordinate_drift(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        mutations = [
            ("system", "deepstream", "must use system 'gstreamer_custom'"),
            ("policy", "not_configured", "not a configured scheduler policy"),
            ("dataset", "kpp_real_h265", "bind codec h264"),
            ("deadline_ms", 50, "must match hardware_target"),
            ("streams", 5, "stream count does not match"),
            ("effective_batch_size", 2, "must remain 1"),
            ("repeats", 9, "must match protocol"),
        ]
        for field, value, message in mutations:
            with self.subTest(field=field):
                changed = copy.deepcopy(cfg)
                changed["benchmark"]["primary_architecture_contrast"][field] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_primary_architecture_contrast(changed)

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["primary_architecture_contrast"]["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "analytics_queue contract has drifted"):
            validate_primary_architecture_contrast(changed)

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["primary_architecture_contrast"]["decoder_placement"][
            "allowed_factories"
        ].append("avdec_h264")
        with self.assertRaisesRegex(ContractError, "decoder_placement contract has drifted"):
            validate_primary_architecture_contrast(changed)

        design_mutations = [
            (("arm_order", "first_arm_by_pair"), ["checkpoint_video_dag_shared"] * 10, "arm order"),
            (("reset_contract", "source_replay_origin"), "cycle_1", "reset_contract"),
            (("pairing_keys",), ["repeat_index"], "pairing_keys"),
            (
                ("estimand_contract", "delta_reuse_obs_c_obs_in", "primary_summary"),
                "mean",
                "estimand_contract",
            ),
            (
                (
                    "quality_guardrail_estimands",
                    "shared_minus_baseline_drop_max_ingress_rate_percentage_points",
                    "favorable_direction",
                ),
                "negative",
                "quality_guardrail_estimands",
            ),
            (("guardrails", "censored_rate_percent_each_arm"), 1.0, "guardrails"),
            (("interval", "resamples"), 2000, "interval and claim rule"),
            (("secondary_estimands",), ["p95"], "secondary_estimands"),
            (("required_sidecars",), ["frames.csv"], "required_sidecars"),
        ]
        for path, value, message in design_mutations:
            with self.subTest(path=path):
                changed = copy.deepcopy(cfg)
                target = changed["benchmark"]["primary_architecture_contrast"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_primary_architecture_contrast(changed)

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["primary_architecture_contrast"]["acceptance_gates"].pop()
        with self.assertRaisesRegex(ContractError, "acceptance_gates"):
            validate_primary_architecture_contrast(changed)

    def test_primary_policy_ablation_is_fully_preregistered_but_not_active(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        ablation = validate_primary_policy_ablation(cfg)

        self.assertEqual(ablation["preregistration_version"], 4)
        self.assertEqual(ablation["status"], "preregistered_blocked_execution")
        self.assertEqual(ablation["architecture_scenario"], "checkpoint_video_dag_shared")
        self.assertEqual(ablation["system"], "gstreamer_custom")
        self.assertEqual(ablation["frozen_policy"], "ql_heft_frozen")
        self.assertEqual(ablation["online_policy"], "ql_heft_online")
        self.assertEqual(
            ablation["feedback_lag_semantics"],
            "max_staleness_from_oldest_applied_snapshot",
        )
        self.assertEqual(ablation["dataset"], "kpp_real_h264")
        self.assertEqual(ablation["deadline_ms"], 100)
        self.assertEqual(ablation["streams"], 6)
        self.assertEqual(ablation["repeats"], 10)
        self.assertEqual(ablation["warmup_s"], 30)
        self.assertEqual(ablation["measurement_s"], 180)
        self.assertEqual(ablation["analytics_queue"]["max_buffers"], 1)
        self.assertEqual(ablation["reset_contract"]["architecture_reset_evidence_contract_version"], 1)
        self.assertIn("reset_evidence.csv", ablation["required_sidecars"]["both_arms"])
        self.assertAlmostEqual(sum(ablation["policy_passport"]["initial_weights"].values()), 2.0)
        self.assertEqual(
            ablation["arm_order"]["first_arm_by_pair"],
            ["ql_heft_frozen", "ql_heft_online"] * 5,
        )
        self.assertTrue(ablation["guardrails"]["identical_ingress_input_frame_keys"])
        self.assertTrue(ablation["guardrails"]["identical_terminal_status_by_input_frame_key"])
        self.assertEqual(ablation["interval"]["claim_rule"], "upper_bound_below_zero_and_all_guardrails_pass")
        self.assertNotIn("ql_heft_frozen", cfg["benchmark"]["scheduler_policies"])
        self.assertNotIn("ql_heft_online", cfg["benchmark"]["scheduler_policies"])

        artifact = ROOT / ablation["policy_artifact"]
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), ablation["policy_artifact_sha256"])

    def test_primary_policy_ablation_rejects_preregistered_design_drift(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        mutations = [
            (("status",), "supported", "must remain preregistered_blocked_execution"),
            (("architecture_scenario",), "checkpoint_independent_processes_baseline", "shared Video-DAG"),
            (("deadline_ms",), 50, "deadline_ms differs"),
            (("online_policy",), "adaptive_weights", "frozen and online technical policy IDs"),
            (("feedback_lag_semantics",), "newest_source_snapshot", "feedback lag semantics"),
            (("policy_artifact_sha256",), "0" * 64, "SHA-256 has drifted"),
            (("policy_passport", "projection_rule"), "different", "policy_passport differs"),
            (("arm_order", "first_arm_by_pair"), ["ql_heft_frozen"] * 10, "counterbalanced arm order"),
            (("reset_contract", "update_seq"), 1, "reset_contract has drifted"),
            (("guardrails", "identical_terminal_status_by_input_frame_key"), False, "guardrails must prevent"),
            (("interval", "seed"), 1, "interval and claim rule have drifted"),
        ]
        for path, value, message in mutations:
            with self.subTest(path=path):
                changed = copy.deepcopy(cfg)
                target = changed["benchmark"]["primary_policy_ablation"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaisesRegex(ContractError, message):
                    validate_primary_policy_ablation(changed)

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["primary_policy_ablation"]["acceptance_gates"]["pair"].pop()
        with self.assertRaisesRegex(ContractError, "acceptance gates have drifted"):
            validate_primary_policy_ablation(changed)

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["primary_policy_ablation"]["analytics_queue"]["max_buffers"] = 2
        with self.assertRaisesRegex(ContractError, "analytics_queue differs"):
            validate_primary_policy_ablation(changed)

    def test_primary_policy_equivalence_scope_keeps_proxy_and_formal_gates_separate(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        assessment = assess_primary_policy_equivalence_scope(cfg)

        self.assertEqual(assessment["assessment_schema_version"], 3)
        runtime = assessment["runtime_execution_compatibility"]
        self.assertEqual(
            runtime["status"],
            "blocked_runtime_policy_implementation_mismatch",
        )
        self.assertFalse(runtime["passed"])
        self.assertEqual(runtime["configured_cell"]["system"], "gstreamer_custom")
        self.assertFalse(
            runtime["configured_cell"]["source_assessment"]["markers_verified"]
        )
        self.assertEqual(
            runtime["registered_proxy_v4_implementation"]["system"],
            "custom_cpp_cuda_qt",
        )
        self.assertTrue(
            runtime["registered_proxy_v4_implementation"]["source_assessment"][
                "markers_verified"
            ]
        )
        self.assertIn(
            "registered_proxy_v4_emitter_system_mismatch",
            runtime["blockers"],
        )
        self.assertIn(
            "registered_proxy_v4_emitter_not_dataset_consuming",
            runtime["blockers"],
        )
        self.assertIn(
            "registered_proxy_v4_emitter_not_benchmark_eligible",
            runtime["blockers"],
        )

        proxy = assessment["proxy_passport_equivalence"]
        self.assertEqual(proxy["gate"], "policy_implementation_equivalence")
        self.assertEqual(proxy["scope"], "frozen_v4_proxy_passport_replay")
        self.assertEqual(proxy["status"], "ready_runtime_reference_replay_not_executed")
        self.assertFalse(proxy["passed"])
        self.assertFalse(proxy["runtime_reference_replay_performed"])
        self.assertTrue(proxy["runtime_reference_replay_implemented"])

        formal = assessment["formal_aw_heft_equivalence"]
        self.assertEqual(formal["gate"], "formal_aw_heft_implementation_equivalence")
        self.assertEqual(
            formal["status"],
            "blocked_reference_not_runtime_bound_or_preregistered",
        )
        self.assertFalse(formal["passed"])
        self.assertTrue(formal["formal_reference_replay_implemented"])
        self.assertFalse(formal["accepted_formal_trace_replay_performed"])
        self.assertFalse(formal["runtime_reference_replay_performed"])
        self.assertIn("resource_scope:nvdec", formal["missing_requirements"])
        self.assertIn("policy_passport:rank_u_semantics", formal["missing_requirements"])
        self.assertIn("policy_passport:deadline_risk_semantics", formal["missing_requirements"])
        self.assertIn("formal_h2_cell:not_preregistered", formal["missing_requirements"])
        self.assertIn(
            "formal_replay:accepted_trace_not_performed",
            formal["missing_requirements"],
        )
        reference = formal["reference_implementation"]
        self.assertEqual(
            reference["status"],
            "ready_executable_reference_and_replay_not_runtime_bound",
        )
        self.assertEqual(reference["assessment_schema_version"], 2)
        self.assertTrue(reference["reference_contract_verified"])
        self.assertFalse(reference["passed"])
        self.assertFalse(reference["runtime_bound"])
        self.assertFalse(reference["benchmark_eligible"])
        self.assertTrue(reference["formal_reference_replay_implemented"])
        self.assertFalse(reference["accepted_formal_trace_replay_performed"])
        self.assertFalse(reference["runtime_reference_replay_performed"])
        self.assertEqual(reference["blockers"], [])
        self.assertIn("dataset_consuming_runtime_not_bound", reference["remaining_gates"])

        policy_analysis = assessment["policy_analysis"]
        self.assertEqual(
            policy_analysis["claim_state"],
            "blocked_missing_accepted_policy_pairs_or_gates",
        )
        self.assertTrue(policy_analysis["pair_analysis_implemented"])
        self.assertFalse(policy_analysis["formal_h2_cell_preregistered"])
        self.assertTrue(policy_analysis["formal_reference_replay_implemented"])
        self.assertFalse(policy_analysis["accepted_formal_trace_replay_performed"])

    def test_formal_aw_heft_reference_assessment_fails_closed_on_hash_or_binding_drift(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        reference = assess_formal_aw_heft_reference(cfg)
        self.assertTrue(reference["reference_contract_verified"])
        self.assertFalse(reference["passed"])

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["formal_aw_heft_reference"]["artifact_sha256"] = "0" * 64
        drifted = assess_formal_aw_heft_reference(changed)
        self.assertFalse(drifted["reference_contract_verified"])
        self.assertIn("reference_artifact_sha256_mismatch", drifted["blockers"])

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["formal_aw_heft_reference"]["runtime_binding"] = "gstreamer_custom"
        bound_without_contract = assess_formal_aw_heft_reference(changed)
        self.assertFalse(bound_without_contract["reference_contract_verified"])
        self.assertIn("reference_declaration_drift:runtime_binding", bound_without_contract["blockers"])

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["formal_aw_heft_reference"]["replay_numeric_tolerance"] = 1.0e-6
        drifted_replay = assess_formal_aw_heft_reference(changed)
        self.assertFalse(drifted_replay["reference_contract_verified"])
        self.assertIn(
            "reference_declaration_drift:replay_numeric_tolerance",
            drifted_replay["blockers"],
        )

    def test_resource_interval_extension_is_verified_but_not_publication_bound(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        assessment = assess_resource_interval_extension(cfg)

        self.assertEqual(assessment["assessment_schema_version"], 1)
        self.assertEqual(
            assessment["status"],
            "ready_validator_and_fanout_source_not_target_verified_not_publication_bound",
        )
        self.assertTrue(assessment["validator_verified"])
        self.assertTrue(assessment["fanout_emitter_source_verified"])
        self.assertFalse(assessment["passed"])
        self.assertFalse(assessment["native_sidecar_emitted"])
        self.assertFalse(assessment["publication_bundle_bound"])
        self.assertFalse(assessment["evidence_accepted"])
        self.assertEqual(assessment["blockers"], [])
        self.assertIn(
            "full_resource_publication_scope_not_preregistered",
            assessment["remaining_gates"],
        )
        self.assertIn(
            "native_fanout_interval_emitter_not_target_executed_or_accepted",
            assessment["remaining_gates"],
        )
        self.assertIn(
            "native_nvdec_busy_resource_counter_missing",
            assessment["remaining_gates"],
        )
        self.assertIn(
            "native_fanout_resource_work_counter_missing",
            assessment["remaining_gates"],
        )
        self.assertNotIn(
            "native_fanout_interval_emitter_missing",
            assessment["remaining_gates"],
        )

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["resource_interval_extension"]["validator_sha256"] = "0" * 64
        drifted = assess_resource_interval_extension(changed)
        self.assertFalse(drifted["validator_verified"])
        self.assertIn("resource_interval_validator_sha256_mismatch", drifted["blockers"])

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["resource_interval_extension"]["fanout_emitter_sha256"] = "0" * 64
        drifted = assess_resource_interval_extension(changed)
        self.assertFalse(drifted["fanout_emitter_source_verified"])
        self.assertIn(
            "resource_interval_fanout_emitter_sha256_mismatch",
            drifted["blockers"],
        )

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["resource_interval_extension"]["publication_bundle_bound"] = True
        rebound = assess_resource_interval_extension(changed)
        self.assertFalse(rebound["validator_verified"])
        self.assertIn(
            "resource_interval_declaration_drift:publication_bundle_bound",
            rebound["blockers"],
        )

        changed = copy.deepcopy(cfg)
        changed["benchmark"]["resource_interval_extension"][
            "current_publication_bundle_scope"
        ] = "primary_architecture_full_resource_raw_evidence_v2"
        scope_drift = assess_resource_interval_extension(changed)
        self.assertFalse(scope_drift["validator_verified"])
        self.assertIn(
            "resource_interval_declaration_drift:current_publication_bundle_scope",
            scope_drift["blockers"],
        )

    def test_primary_policy_runtime_plan_freezes_order_but_disables_execution(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        readiness = assess_primary_policy_runtime_compatibility(cfg)
        plan = build_primary_policy_runtime_plan(cfg)

        self.assertEqual(plan["status"], readiness["status"])
        self.assertFalse(plan["runtime_execution_allowed"])
        self.assertFalse(plan["architecture_acceptance_evidence_checked"])
        self.assertEqual(plan["expected_pairs"], 10)
        self.assertEqual(plan["expected_runs"], 20)
        self.assertEqual(len(plan["runs"]), 20)
        self.assertEqual(
            [run["policy"] for run in plan["runs"][:4]],
            [
                "ql_heft_frozen",
                "ql_heft_online",
                "ql_heft_online",
                "ql_heft_frozen",
            ],
        )
        for repeat in range(1, 11):
            pair_runs = plan["runs"][(repeat - 1) * 2 : repeat * 2]
            self.assertEqual(
                [run["primary_policy_pair"]["arm_position"] for run in pair_runs],
                [1, 2],
            )
            self.assertTrue(
                all(
                    run["primary_policy_pair"]["repeat"] == repeat
                    for run in pair_runs
                )
            )
            self.assertEqual(
                pair_runs[0]["primary_policy_pair"]["first_arm"],
                pair_runs[0]["policy"],
            )
            self.assertEqual(
                pair_runs[0]["primary_policy_pair"]["second_arm"],
                pair_runs[1]["policy"],
            )

    def test_hardware_target_assessment_requires_cpu_gpu_and_ram_match(self) -> None:
        target = {
            "gpu_model": "NVIDIA GeForce RTX 3060",
            "cpu_model": "Intel Core i7-14700K",
            "ram_gb": 22,
        }
        accepted = assess_hardware_target(
            target,
            {
                "gpu_model": "NVIDIA GeForce RTX 3060",
                "cpu_model": "Intel(R) Core(TM) i7-14700K",
                "ram_gb": 23.5,
            },
        )
        self.assertTrue(accepted["passed"])
        self.assertEqual(accepted["status"], "target_hardware_verified")

        blocked = assess_hardware_target(
            target,
            {
                "gpu_model": "unknown",
                "cpu_model": "Apple M4 Max",
                "ram_gb": 64,
            },
        )
        self.assertFalse(blocked["passed"])
        self.assertEqual(blocked["status"], "blocked_hardware_target_mismatch")
        self.assertEqual(
            set(blocked["blockers"]),
            {
                "detected_gpu_model_missing",
                "cpu_model_mismatch",
                "ram_gb_mismatch",
            },
        )

    def test_benchmark_runner_fails_closed_on_hardware_mismatch(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        detected = {
            "gpu_model": "unknown",
            "cpu_model": "Apple M4 Max",
            "ram_gb": 64.0,
        }
        with mock.patch(
            "run_experiments.detected_hardware_manifest",
            return_value=detected,
        ):
            planning = validate_hardware(cfg, require_match=False)
            self.assertFalse(planning["passed"])
            with self.assertRaisesRegex(
                ContractError,
                "benchmark hardware target mismatch",
            ):
                validate_hardware(cfg, require_match=True)

    def test_primary_policy_pair_metadata_rejects_order_drift(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        metadata = primary_policy_pair_metadata(
            cfg,
            repeat=2,
            policy="ql_heft_online",
        )

        self.assertEqual(metadata["contract_version"], 1)
        self.assertEqual(metadata["arm_position"], 1)
        self.assertEqual(
            validate_primary_policy_pair_metadata(
                cfg,
                repeat=2,
                policy="ql_heft_online",
                metadata=metadata,
            ),
            metadata,
        )

        changed = copy.deepcopy(metadata)
        changed["arm_position"] = 2
        with self.assertRaisesRegex(ContractError, "frozen arm order"):
            validate_primary_policy_pair_metadata(
                cfg,
                repeat=2,
                policy="ql_heft_online",
                metadata=changed,
            )
        with self.assertRaisesRegex(ContractError, "between 1 and 10"):
            primary_policy_pair_metadata(
                cfg,
                repeat=11,
                policy="ql_heft_online",
            )

    def test_primary_policy_plan_cli_reports_blocker_without_running_matrix(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_experiments.py",
                "--primary-policy-plan",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertFalse(payload["runtime_execution_allowed"])
        self.assertEqual(payload["expected_runs"], 20)
        self.assertEqual(
            payload["status"],
            "blocked_runtime_policy_implementation_mismatch",
        )

    def test_independent_baseline_repeats_common_stages_per_branch(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        baseline = normalize_scenario(
            "checkpoint_independent_processes_baseline",
            cfg["scenarios"]["checkpoint_independent_processes_baseline"],
        )

        self.assertEqual(baseline["pipeline"], INDEPENDENT_PROOF_PIPELINE)
        self.assertEqual(sum(1 for stage in baseline["pipeline"] if stage.startswith("decode_")), 4)
        self.assertEqual(sum(1 for stage in baseline["pipeline"] if stage.startswith("preprocess_")), 4)
        self.assertEqual(set(baseline["placement"]["stages"].values()), {"local"})
        self.assertFalse(baseline["distributed"]["enabled"])

    def test_benchmark_all_excludes_topology_blocked_checkpoint_scenarios(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark"), [])
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="auto"), [])
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="heterogeneous"), [])
        self.assertEqual(select_scenarios(cfg, ["all"], mode="benchmark", run_kind="distributed"), [])
        self.assertEqual(select_scenarios(cfg, ["all"], mode="smoke"), ["checkpoint_video_dag_shared"])

    def test_strict_adapter_rejects_topology_blocked_checkpoint_scenarios(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        for name, raw in cfg["scenarios"].items():
            with self.subTest(scenario=name):
                scenario = normalize_scenario(name, raw)
                with self.assertRaisesRegex(ContractError, "not publishable.*blocked_topology"):
                    validate_benchmark_adapter(
                        system_key="deepstream",
                        scenario=scenario,
                        distributed=bool(scenario["distributed"]["enabled"]),
                        mode="benchmark",
                    )

    def test_explicit_checkpoint_benchmark_request_fails_topology_contract(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        with self.assertRaisesRegex(ContractError, "non-publishable scenarios cannot run"):
            select_scenarios(cfg, ["checkpoint_video_dag_shared"], mode="benchmark")

    def test_checkpoint_adapter_requires_declared_topology_after_status_is_enabled(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        checkpoint = normalize_scenario(
            "checkpoint_video_dag_shared",
            cfg["scenarios"]["checkpoint_video_dag_shared"],
        )
        checkpoint["benchmark_status"] = "supported"
        checkpoint["topology"]["routing_mode"] = "unresolved"
        checkpoint["workload"]["routing_mode"] = "unresolved"

        with self.assertRaisesRegex(ContractError, "must resolve routing_mode"):
            validate_benchmark_adapter(
                system_key="deepstream",
                scenario=checkpoint,
                distributed=False,
                mode="benchmark",
            )

        checkpoint["topology"]["routing_mode"] = "all_branches_per_stream"
        checkpoint["workload"]["routing_mode"] = "all_branches_per_stream"
        plan = validate_benchmark_adapter(
            system_key="deepstream",
            scenario=checkpoint,
            distributed=False,
            mode="benchmark",
        )
        self.assertEqual(plan.contract, "strict_native_schema_v2_topology_v1")
        self.assertEqual(plan.topology_contract_version, 1)
        self.assertEqual(plan.topology_kind, "shared_video_dag")

        checkpoint["topology"]["required_branches"] = ["plate_number"]
        with self.assertRaisesRegex(ContractError, "branches must match analytics_function_types"):
            validate_benchmark_adapter(
                system_key="deepstream",
                scenario=checkpoint,
                distributed=False,
                mode="benchmark",
            )

    def test_checkpoint_dataset_requires_resolved_matching_routing(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        dataset = dict(load_config(ROOT / "configs" / "datasets.yaml")["datasets"]["kpp_real_h264"])
        dataset["name"] = "kpp_real_h264"
        checkpoint = normalize_scenario(
            "checkpoint_video_dag_shared",
            cfg["scenarios"]["checkpoint_video_dag_shared"],
        )

        validate_checkpoint_workload(dataset, checkpoint)

        missing_profile = copy.deepcopy(dataset)
        missing_profile["experimental_routing_profiles"] = []
        with self.assertRaisesRegex(ContractError, "no exact non-production experimental routing profile"):
            validate_checkpoint_workload(missing_profile, checkpoint)

        production_profile = copy.deepcopy(dataset)
        production_profile["experimental_routing_profiles"][0]["production_semantics"] = True
        with self.assertRaisesRegex(ContractError, "no exact non-production experimental routing profile"):
            validate_checkpoint_workload(production_profile, checkpoint)

        unresolved_checkpoint = copy.deepcopy(checkpoint)
        unresolved_checkpoint["workload"]["routing_mode"] = "unresolved"
        with self.assertRaisesRegex(ContractError, "analytics routing is unresolved"):
            validate_checkpoint_workload(dataset, unresolved_checkpoint)

    def test_publication_report_rejects_topology_blocked_scenarios(self) -> None:
        with self.assertRaisesRegex(ContractError, "report_scenarios contains non-publishable"):
            load_report_config(ROOT / "configs" / "experiments.yaml")

    def test_strict_adapter_rejects_unknown_distributed_role(self) -> None:
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
        scenario["placement"]["stages"]["track"] = "remote"

        with self.assertRaisesRegex(ContractError, "unsupported distributed roles: remote"):
            validate_benchmark_adapter(
                system_key="deepstream",
                scenario=scenario,
                distributed=True,
                mode="benchmark",
            )

    def test_custom_signal_adapter_is_rejected_as_publishable_benchmark(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario(
            "checkpoint_video_dag_shared",
            cfg["scenarios"]["checkpoint_video_dag_shared"],
        )

        with self.assertRaisesRegex(ContractError, "diagnostic-only.*does not consume"):
            validate_benchmark_adapter(
                system_key="custom_cpp_cuda_qt",
                scenario=scenario,
                distributed=False,
                mode="benchmark",
            )

    def test_default_benchmark_matrix_excludes_diagnostic_signal_adapter(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        benchmark_systems = configured_system_names(cfg, ["all"], mode="benchmark")
        smoke_systems = configured_system_names(cfg, ["all"], mode="smoke")

        self.assertNotIn("custom_cpp_cuda_qt", benchmark_systems)
        self.assertIn("custom_cpp_cuda_qt", smoke_systems)

    def test_explicit_diagnostic_signal_benchmark_request_fails(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")

        with self.assertRaisesRegex(ContractError, "diagnostic-only systems cannot run"):
            configured_system_names(cfg, ["custom_cpp_cuda_qt"], mode="benchmark")

    def test_strict_adapter_accepts_checkpoint_local_and_distributed_fixture(self) -> None:
        local = normalize_scenario("local_fixture", local_fixture())
        distributed = normalize_scenario("distributed_fixture", distributed_fixture())

        local_plan = validate_benchmark_adapter(
            system_key="deepstream",
            scenario=local,
            distributed=False,
            mode="benchmark",
        )
        distributed_plan = validate_benchmark_adapter(
            system_key="openvino_gva",
            scenario=distributed,
            distributed=True,
            mode="benchmark",
        )

        self.assertEqual(local_plan.contract, "strict_native_schema_v2")
        self.assertEqual(distributed_plan.runner, "scripts/run_system_template.sh")

    def test_heterogeneous_context_forces_distributed_env_off(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("checkpoint_video_dag_shared", cfg["scenarios"]["checkpoint_video_dag_shared"])
        context = resolve_execution_context(
            requested_run_kind=normalize_run_kind("local"),
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )

        env_prefix = scenario_env_prefix(scenario, distributed=context.distributed_enabled)
        self.assertEqual(context.deployment_mode, "heterogeneous")
        self.assertIn("EXPERIMENT_DISTRIBUTED=0", env_prefix)

    def test_single_server_distributed_uses_localhost_without_sync(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
        context = resolve_execution_context(
            requested_run_kind="single-server-distributed",
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )
        steps = build_distributed_plan(
            hosts_config=context.hosts_config,
            scenario=scenario,
            system_key="custom_cpp_cuda_qt",
            command_template=cfg["systems"]["custom_cpp_cuda_qt"]["command"],
            run_relpath="runs/test/distributed_fixture/streams_6/custom/rep_01",
            duration_s=5,
            streams=6,
            min_objects=1,
            max_objects=12,
        )

        self.assertFalse(context.sync_project)
        self.assertEqual(context.host_topology, "single_host_ssh")
        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertTrue(all(s["host_label"] == "127.0.0.1" for s in steps))

    def test_builtin_strict_systems_build_role_steps(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
        context = resolve_execution_context(
            requested_run_kind="single-server-distributed",
            scenario=scenario,
            hosts_config={"hosts": []},
            hosts_config_path=ROOT / "configs" / "hosts.yaml",
            single_server_host="127.0.0.1",
            single_server_user="",
            single_server_port=22,
            project_root=ROOT,
        )
        for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
            steps = build_distributed_plan(
                hosts_config=context.hosts_config,
                scenario=scenario,
                system_key=system,
                command_template=cfg["systems"][system]["command"],
                run_relpath=f"runs/test/distributed_fixture/streams_6/{system}/rep_01",
                duration_s=5,
                streams=6,
                min_objects=1,
                max_objects=12,
                transport=cfg["transport"],
                mode="benchmark",
            )
            self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
            self.assertTrue(all(f"--system {system}" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_DISTRIBUTED=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("EXPERIMENT_RTP_PORT_STRIDE=1" in s["remote_command"] for s in steps))
            self.assertTrue(all("DISTRIBUTED_NATIVE_CMD" not in s["remote_command"] for s in steps))
            self.assertTrue(all("setsid bash -lc" in s["remote_command"] for s in steps))
            self.assertTrue(all(">/dev/null 2>&1 &" in s["remote_command"] for s in steps))

    def test_builtin_strict_template_dry_run_commands(self) -> None:
        expectations = {
            "deepstream": ["vast/deepstream-native-probe:7.0", "nvinfer", "/usr/local/bin/vast_native_gst_probe"],
            "savant": ["vast/savant-native-probe:0.5.17-7.0", "/usr/local/bin/vast_native_gst_probe", "nvinfer"],
            "openvino_gva": ["vast_native_gst_probe", "gvadetect", "--input-port-base 5600"],
            "gstreamer_custom": ["GST_CUSTOM_STRICT=1", "--detect-bin identity", "--input-port-base 5600"],
        }
        for system, expected in expectations.items():
            env = os.environ.copy()
            env.update(
                {
                    "REAL_DRY_RUN": "1",
                    "BENCHMARK_MODE": "benchmark",
                    "EXPERIMENT_DISTRIBUTED": "1",
                    "EXPERIMENT_HOST_ROLE": "gpu_worker",
                    "EXPERIMENT_PIPELINE_STAGES": "detect,track",
                    "EXPERIMENT_RTP_INPUT_PORT": "5600",
                    "EXPERIMENT_RTP_OUTPUT_HOST": "127.0.0.1",
                    "EXPERIMENT_RTP_OUTPUT_PORT": "5700",
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    system,
                    "--scenario",
                    "distributed_fixture",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "1",
                    "--max-objects",
                    "12",
                    "--output",
                    str(ROOT / "runs" / "dry" / system / "frames.csv"),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 1)
            for fragment in expected:
                self.assertIn(fragment, output)
            if system == "deepstream":
                self.assertIn("--entrypoint /usr/local/bin/vast_native_gst_probe", output)
                self.assertNotIn("'vast/deepstream-native-probe:7.0'     /usr/local/bin/vast_native_gst_probe", output)

    def test_builtin_strict_local_template_dry_run_commands(self) -> None:
        expectations = {
            "deepstream": ["vast/deepstream-native-probe:7.0", "nvinfer", "/usr/local/bin/vast_native_gst_probe", "--role local"],
            "savant": ["ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0", "savant.entrypoint", "canonical_heterogeneous_module.yml"],
            "openvino_gva": ["vast_native_gst_probe", "gvadetect", "--role local"],
            "gstreamer_custom": ["GST_CUSTOM_STRICT=1", "adaptivescheduler", "--role local"],
        }
        for system, expected in expectations.items():
            env = os.environ.copy()
            env.update(
                {
                    "REAL_DRY_RUN": "1",
                    "BENCHMARK_MODE": "benchmark",
                    "EXPERIMENT_DISTRIBUTED": "0",
                    "EXPERIMENT_HOST_ROLE": "local",
                    "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                }
            )
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    system,
                    "--scenario",
                    "topology_contract_fixture",
                    "--duration",
                    "5",
                    "--streams",
                    "2",
                    "--min-objects",
                    "20",
                    "--max-objects",
                    "80",
                    "--output",
                    str(ROOT / "runs" / "dry" / "local" / system / "frames.csv"),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 1)
            for fragment in expected:
                self.assertIn(fragment, output)
            self.assertNotIn("deepstream-test3-app", output)
            self.assertNotIn("deploy/savant/module.yml", output)
            if system == "deepstream":
                self.assertIn("--entrypoint /usr/local/bin/vast_native_gst_probe", output)
                self.assertNotIn("'vast/deepstream-native-probe:7.0'     /usr/local/bin/vast_native_gst_probe", output)
            if system == "savant":
                self.assertIn("Prewarming Savant local model cache", output)
                self.assertIn("wait_for_telemetry", output)
                self.assertIn("measurement_start_ms", output)
                self.assertIn("measurement_end_ms", output)
                self.assertIn(".cache/savant", output)
                self.assertNotIn("; sleep 5; for pid in $pids", output)

    def test_builtin_templates_dispatch_multistage_local_and_distributed_profiles(self) -> None:
        cases = [
            ("savant", "high_density_multistage", "0", "local", "decode,detect,track,classify,record"),
            ("gstreamer_custom", "edge_worker_aggregator_distributed", "1", "gpu_worker", "detect,track"),
        ]
        for system, scenario, distributed, role, stages in cases:
            with self.subTest(system=system, scenario=scenario):
                env = os.environ.copy()
                env.update(
                    {
                        "REAL_DRY_RUN": "1",
                        "BENCHMARK_MODE": "benchmark",
                        "EXPERIMENT_DISTRIBUTED": distributed,
                        "EXPERIMENT_HOST_ROLE": role,
                        "EXPERIMENT_PIPELINE_STAGES": stages,
                    }
                )
                completed = subprocess.run(
                    [
                        "bash",
                        str(ROOT / "scripts" / "run_system_template.sh"),
                        "--system",
                        system,
                        "--scenario",
                        scenario,
                        "--duration",
                        "5",
                        "--streams",
                        "1",
                        "--min-objects",
                        "1",
                        "--max-objects",
                        "2",
                        "--output",
                        str(ROOT / "runs" / "dry" / scenario / system / "frames.csv"),
                    ],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                output = completed.stdout + completed.stderr
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn("currently support only canonical", output)
                self.assertIn(stages, output)
                if system == "savant":
                    self.assertIn("stage_files_ready", output)
                    self.assertIn("frame_events_$stage.csv", output)

    def test_custom_cpp_uses_per_stream_frame_ids_for_distributed_preroll(self) -> None:
        body = (ROOT / "deploy" / "custom_cpp_cuda_qt" / "adaptive_scheduler_app.cu").read_text(encoding="utf-8")

        self.assertIn("task.frame_id = frame_idx;", body)
        self.assertNotIn("task.frame_id = stream_id * frames_per_stream_ + frame_idx;", body)

    def test_distributed_edge_preroll_keeps_rtp_producer_alive_for_cold_workers(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "1",
                "EXPERIMENT_HOST_ROLE": "edge",
                "EXPERIMENT_PIPELINE_STAGES": "decode",
                "STARTUP_GRACE_S": "10",
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "gstreamer_custom",
                "--scenario",
                "edge_worker_aggregator_distributed",
                "--duration",
                "5",
                "--streams",
                "1",
                "--min-objects",
                "1",
                "--max-objects",
                "2",
                "--output",
                str(ROOT / "runs" / "dry" / "edge_preroll" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("--duration 15", output)

    def test_openvino_local_template_can_force_container_runtime(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "OPENVINO_GVA_FORCE_CONTAINER": "1",
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "openvino_gva",
                    "--scenario",
                    "topology_contract_fixture",
                "--duration",
                "5",
                "--streams",
                "1",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "openvino_container" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("intel/dlstreamer:latest", output)
        self.assertIn("--entrypoint /workspace/project/build/bin/vast_native_gst_probe", output)
        self.assertIn("object_detect", output)
        self.assertIn("/workspace/project/models/openvino", output)
        self.assertIn("data/benchmark/mot17_02.mp4", output)

    def test_openvino_container_fallback_uses_short_finite_input_chunks(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "OPENVINO_GVA_FORCE_CONTAINER": "1",
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "openvino_gva",
                    "--scenario",
                    "topology_contract_fixture",
                "--duration",
                "16",
                "--streams",
                "1",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "openvino_chunks" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("run_openvino_container_chunks.py", output)
        self.assertIn("--chunk-s 15", output)
        self.assertIn("--parallel-streams 1", output)

    def test_openvino_host_fallback_validates_runtime_model_load(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("openvino_host_runtime_usable", body)
        self.assertIn("videotestsrc num-buffers=1", body)
        self.assertIn("capsrelax ! object_detect", body)
        self.assertIn("OpenVINO host DL Streamer runtime failed model preflight", body)

    def test_savant_local_template_preserves_benchmark_dataset_paths(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "REAL_DRY_RUN": "1",
                "BENCHMARK_MODE": "benchmark",
                "EXPERIMENT_DISTRIBUTED": "0",
                "EXPERIMENT_HOST_ROLE": "local",
                "EXPERIMENT_PIPELINE_STAGES": ",".join(SHARED_PROOF_PIPELINE),
                "DATASET_STREAMS_JSON": '["data/benchmark/mot17_02.mp4","data/benchmark/mot17_04.mp4"]',
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts" / "run_system_template.sh"),
                "--system",
                "savant",
                    "--scenario",
                    "topology_contract_fixture",
                "--duration",
                "5",
                "--streams",
                "2",
                "--min-objects",
                "5",
                "--max-objects",
                "35",
                "--output",
                str(ROOT / "runs" / "dry" / "local" / "savant_dataset" / "frames.csv"),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        output = completed.stdout + completed.stderr

        self.assertEqual(completed.returncode, 1)
        self.assertIn("file:///workspace/project/data/benchmark/mot17_02.mp4", output)
        self.assertIn("file:///workspace/project/data/benchmark/mot17_04.mp4", output)
        self.assertNotIn("file:///workspace/project/data/videos/mot17_02.mp4", output)
        self.assertNotIn("file:///workspace/project/data/videos/mot17_04.mp4", output)

    def test_gstreamer_custom_plugin_is_bundled(self) -> None:
        source = ROOT / "deploy" / "gstreamer_adaptivescheduler" / "gstadaptivescheduler.c"
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        body = source.read_text(encoding="utf-8")

        self.assertIn("add_library(gstadaptivescheduler MODULE", cmake)
        self.assertIn("LIBRARY_OUTPUT_DIRECTORY", cmake)
        self.assertIn('gst_element_register(plugin, "adaptivescheduler"', body)
        self.assertIn("GST_PLUGIN_DEFINE", body)

    def test_native_probe_dockerfiles_disable_unneeded_custom_plugin_target(self) -> None:
        for name in ("Dockerfile.deepstream", "Dockerfile.savant"):
            body = (ROOT / "deploy" / "native_gst_probe" / name).read_text(encoding="utf-8")
            self.assertIn("COPY deploy/native_gst_probe", body)
            self.assertIn("VAST_NATIVE_PROBE_SOURCE_SHA", body)
            self.assertIn('org.vast.native_probe.source_sha="${VAST_NATIVE_PROBE_SOURCE_SHA}"', body)
            self.assertIn("for attempt in 1 2 3 4 5", body)
            self.assertIn("apt-get -o Acquire::Retries=5 update &&", body)
            self.assertIn("apt-get -o Acquire::Retries=5 install -y --fix-missing", body)
            self.assertIn('if [ "$attempt" -eq 5 ]; then exit 1; fi;', body)
            self.assertNotIn("$$attempt", body)
            self.assertIn("-DVAST_BUILD_NATIVE_GST_PROBE=ON", body)
            self.assertIn("-DVAST_BUILD_GSTREAMER_CUSTOM_PLUGIN=OFF", body)
            self.assertIn("-DVAST_BUILD_CUSTOM_CUDA_QT=OFF", body)

        build_script = (ROOT / "scripts" / "build_native_probe_images.sh").read_text(encoding="utf-8")
        self.assertIn("--build-arg VAST_NATIVE_PROBE_SOURCE_SHA", build_script)
        self.assertIn("--label \"$SOURCE_LABEL=", build_script)

    def test_native_probe_sets_string_properties_after_parse_launch(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")
        self.assertNotIn("filesrc location=", body)
        self.assertNotIn("udpsink host=", body)
        self.assertIn("filesrc name=file_src", body)
        self.assertIn("udpsink name=out_sink", body)
        self.assertIn('set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location"', body)
        self.assertIn('set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host"', body)

    def test_deepstream_native_probe_uses_nvstreammux_topology(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("deepstream_edge_pipeline", body)
        self.assertIn("deepstream_local_pipeline", body)
        self.assertIn("deepstream_worker_pipeline", body)
        self.assertIn("return args_.system == \"deepstream\" || args_.system == \"savant\";", body)
        self.assertIn("if (uses_deepstream_elements()) {\n      return deepstream_edge_pipeline(stream_id);", body)
        self.assertIn('set_string_property(pipeline, "uri_src" + std::to_string(stream_id), "uri", uri_for_stream(stream_id));', body)
        self.assertIn("uridecodebin name=uri_src", body)
        self.assertIn("nvurisrcbin name=uri_src", body)
        self.assertIn("file-loop=true", body)
        self.assertIn("! queue ! nvvideoconvert ! video/x-raw,format=I420", body)
        self.assertIn("! identity sync=true ! jpegenc", body)
        self.assertGreaterEqual(body.count("! identity sync=true ! jpegenc"), 2)
        self.assertIn("nvstreammux name=mux", body)
        self.assertIn("! mux\" << stream_id << \".sink_0", body)
        self.assertNotIn("video/x-raw(memory:NVMM),format=NV12 ! nvinfer", body)

    def test_native_probe_builds_dynamic_stage_probes(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("stage_names_", body)
        self.assertIn("add_local_stage_probes", body)
        self.assertIn("stage_probe_name", body)
        self.assertIn("stage_base_name", body)
        self.assertIn("generic_stage_operation", body)
        self.assertIn("deepstream_stage_operation", body)
        self.assertIn("write_stage_events", body)
        self.assertIn("ctx->stage", body)
        self.assertIn("videoconvert ! videoscale ! video/x-raw,format=RGB,width=640,height=360", body)
        self.assertIn("jpegenc ! jpegdec", body)
        self.assertIn("sleep-time=1000", body)

    def test_checkpoint_shell_paths_are_blocked_until_topology_is_implemented(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("checkpoint_independent_processes_baseline|checkpoint_video_dag_shared", body)
        self.assertIn("do not implement the required process-per-detector versus shared-fanout topology contract", body)

        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    "bash",
                    str(ROOT / "scripts" / "run_system_template.sh"),
                    "--system",
                    "deepstream",
                    "--scenario",
                    "checkpoint_video_dag_shared",
                    "--duration",
                    "5",
                    "--streams",
                    "1",
                    "--output",
                    str(Path(tmp) / "frames.csv"),
                ],
                cwd=ROOT,
                env={**os.environ, "BENCHMARK_MODE": "benchmark", "REAL_DRY_RUN": "1"},
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("blocked in benchmark mode", completed.stderr)

    def test_native_probe_receives_configured_dataset_streams(self) -> None:
        shell_body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")
        probe_body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn('--dataset-streams-json "$DATASET_STREAMS_JSON"', shell_body)
        self.assertIn('key == "--dataset-streams-json"', probe_body)

    def test_native_probe_handles_rtp_payload_buffer_lists(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("GST_PAD_PROBE_TYPE_BUFFER_LIST", body)
        self.assertIn("GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER_LIST", body)
        self.assertIn("gst_buffer_list_make_writable", body)
        self.assertIn("gst_buffer_list_get_writable", body)
        self.assertIn("&NativeProbeRuntime::input_rtp_probe", body)
        self.assertIn("gst_buffer_list_get(list, index)", body)
        self.assertNotIn("VAST_SKIP_RTP_TRACE_EXTENSION", body)

    def test_native_probe_measurement_timer_starts_on_first_frame_event(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("waiting for first frame event", body)
        self.assertIn("start_measurement_timer_if_needed();", body)
        self.assertIn("measurement_started_.compare_exchange_strong", body)
        self.assertGreaterEqual(body.count("events_.flush();"), 2)
        self.assertGreaterEqual(body.count("frames_.flush();"), 2)

    def test_native_probe_stops_before_flushing_telemetry(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")

        self.assertIn("stop_pipelines();", body)
        self.assertIn("flush_outputs();", body)
        self.assertIn("std::mutex output_mutex_;", body)

    def test_custom_gstreamer_template_prepends_project_plugin_path(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn('"$PROJECT_DIR/build/lib${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}"', body)
        self.assertIn('GST_PLUGIN_PATH=$(gstreamer_custom_plugin_path)', body)
        self.assertIn('video/x-raw,format=RGB ! %s', body)

    def test_custom_cuda_app_uses_monotonic_telemetry_timestamps(self) -> None:
        body = (ROOT / "deploy" / "custom_cpp_cuda_qt" / "adaptive_scheduler_app.cu").read_text(encoding="utf-8")

        self.assertIn("telemetry_timestamp_ms", body)
        self.assertIn("completed_at - task.created_at", body)
        self.assertNotIn("now - task.wall_created_at", body)

    def test_custom_signal_shell_adapter_rejects_benchmark_mode(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn('if [[ "$BENCHMARK_MODE" == "benchmark" ]]', body)
        self.assertIn("custom_cpp_cuda_qt is diagnostic-only", body)
        self.assertIn("does not consume the configured video source", body)

    def test_template_rejects_stale_native_probe_images(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("ensure_native_probe_image_current", body)
        self.assertIn("org.vast.native_probe.source_sha", body)
        self.assertIn("VAST_SKIP_NATIVE_IMAGE_SHA_CHECK", body)
        self.assertIn("Strict native $SYSTEM benchmark image is stale", body)

    def test_savant_local_template_waits_for_native_rows_before_measurement(self) -> None:
        body = (ROOT / "scripts" / "run_system_template.sh").read_text(encoding="utf-8")

        self.assertIn("SAVANT_LOCAL_PREWARM", body)
        self.assertIn("wait_for_csv_rows", body)
        self.assertIn("csv_ready", body)
        self.assertIn("required_stages='${PIPELINE_STAGES}'", body)
        self.assertIn("stage_files_ready()", body)
        self.assertIn("frame_events_\\$stage.csv", body)
        self.assertIn("EXPERIMENT_PIPELINE_STAGES='${PIPELINE_STAGES}'", body)
        self.assertNotIn("currently support only canonical", body)
        self.assertIn("wait_for_telemetry || { rc=\\$?; cleanup", body)
        self.assertIn("mark_measurement_start; sleep ${DURATION_S}; mark_measurement_end", body)
        self.assertIn("measurement_start_ms", body)
        self.assertIn("measurement_end_ms", body)
        self.assertIn("process_alive", body)
        self.assertIn("process exited before telemetry was ready", body)
        self.assertIn("wait_for_csv_rows \\\"\\$host_output/prewarm/frames.csv\\\" 2 'Savant local cache prewarm' \\\"\\$prewarm_pid\\\"", body)
        self.assertIn("pid_at \\\"\\$i\\\" \\$stream_pids", body)

    def test_savant_local_timeout_allows_prewarm_and_shutdown(self) -> None:
        base_env = {"STARTUP_GRACE_S": "180", "SAVANT_LOCAL_SHUTDOWN_GRACE_S": "15"}

        self.assertEqual(
            default_command_timeout_s(
                system_key="deepstream",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env=base_env,
            ),
            270,
        )
        self.assertEqual(
            default_command_timeout_s(
                system_key="savant",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env=base_env,
            ),
            540,
        )
        self.assertEqual(
            default_command_timeout_s(
                system_key="savant",
                duration_s=30,
                distributed_enabled=False,
                mode="benchmark",
                env={**base_env, "SAVANT_LOCAL_PREWARM": "0"},
            ),
            360,
        )

    def test_dlstreamer_installer_prefers_clean_docker_fallback(self) -> None:
        body = (ROOT / "scripts" / "install_openvino_dlstreamer.sh").read_text(encoding="utf-8")

        self.assertIn("docker create \"$image\" bash -lc 'sleep 600'", body)
        self.assertIn("DLSTREAMER_TRY_INTEL_APT", body)
        self.assertLess(
            body.index("if install_from_intel_dlstreamer_image; then"),
            body.index("Docker fallback failed; trying Intel OpenVINO APT repository"),
        )

    def test_single_server_preflight_records_loopback_metrics(self) -> None:
        hosts_config = {
            "hosts": [
                {
                    "address": "127.0.0.1",
                    "project_path": str(ROOT),
                    "roles": ["edge", "gpu_worker", "aggregator"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            network_csv = Path(tmp) / "network_metrics.csv"
            result = run_network_preflight(
                hosts_config=hosts_config,
                network_csv=network_csv,
                network_profile={},
                max_clock_offset_ms=5,
            )

            self.assertFalse(result.skipped)
            self.assertIn("same_host_loopback", network_csv.read_text(encoding="utf-8"))

    def test_workload_seed_is_independent_of_system(self) -> None:
        first = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 1)
        second = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 1)
        different_repeat = build_run_seed(20260323, "checkpoint_video_dag_shared", "", 6, 2)

        self.assertEqual(first, second)
        self.assertNotEqual(first, different_repeat)

    def test_distributed_plan_maps_roles_to_hosts(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = normalize_scenario("distributed_fixture", distributed_fixture())
        hosts_config = {
            "hosts": [
                {
                    "address": "edge.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["edge"],
                },
                {
                    "address": "gpu.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["gpu_worker"],
                },
                {
                    "address": "agg.example.net",
                    "user": "vast",
                    "project_path": "/opt/vast",
                    "roles": ["aggregator"],
                },
            ]
        }

        steps = build_distributed_plan(
            hosts_config=hosts_config,
            scenario=scenario,
            system_key="custom_cpp_cuda_qt",
            command_template=cfg["systems"]["custom_cpp_cuda_qt"]["command"],
            run_relpath="runs/test/scenario/streams_1/custom/rep_01",
            duration_s=5,
            streams=1,
            min_objects=0,
            max_objects=1,
        )

        self.assertEqual([s["role"] for s in steps], ["aggregator", "gpu_worker", "edge"])
        self.assertIn("EXPERIMENT_DISTRIBUTED=1", steps[0]["remote_command"])
        self.assertIn("EXPERIMENT_RTP_INPUT_PORT=5700", steps[0]["remote_command"])
        self.assertIn("--output /opt/vast/runs/test", steps[0]["remote_command"])
        self.assertIn(" && { setsid bash -lc", steps[0]["remote_command"])
        self.assertTrue(steps[0]["remote_command"].rstrip().endswith("; }"))


    def test_primary_architecture_runtime_plan_preserves_counterbalanced_pairs(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        plan = build_primary_architecture_runtime_plan(cfg)

        self.assertEqual(
            plan["status"],
            "blocked_primary_architecture_topology_implementation",
        )
        self.assertFalse(plan["runtime_execution_allowed"])
        self.assertEqual(plan["expected_pairs"], 10)
        self.assertEqual(plan["expected_runs"], 20)
        self.assertEqual(len(plan["runs"]), 20)
        self.assertEqual(
            [run["scenario"] for run in plan["runs"][:4]],
            [
                "checkpoint_independent_processes_baseline",
                "checkpoint_video_dag_shared",
                "checkpoint_video_dag_shared",
                "checkpoint_independent_processes_baseline",
            ],
        )
        for repeat in range(1, 11):
            pair_runs = plan["runs"][(repeat - 1) * 2 : repeat * 2]
            self.assertEqual(
                [
                    run["primary_architecture_pair"]["arm_position"]
                    for run in pair_runs
                ],
                [1, 2],
            )
            self.assertTrue(
                all(
                    run["primary_architecture_pair"]["repeat"] == repeat
                    for run in pair_runs
                )
            )

    def test_primary_architecture_pair_metadata_rejects_order_drift(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        scenario = "checkpoint_video_dag_shared"
        metadata = primary_architecture_pair_metadata(
            cfg,
            repeat=2,
            scenario=scenario,
        )

        self.assertEqual(metadata["contract_version"], 1)
        self.assertEqual(metadata["arm_position"], 1)
        self.assertEqual(
            validate_primary_architecture_pair_metadata(
                cfg,
                repeat=2,
                scenario=scenario,
                metadata=metadata,
            ),
            metadata,
        )
        changed = copy.deepcopy(metadata)
        changed["arm_position"] = 2
        with self.assertRaisesRegex(ContractError, "frozen arm order"):
            validate_primary_architecture_pair_metadata(
                cfg,
                repeat=2,
                scenario=scenario,
                metadata=changed,
            )
        with self.assertRaisesRegex(ContractError, "between 1 and 10"):
            primary_architecture_pair_metadata(
                cfg,
                repeat=11,
                scenario=scenario,
            )

    def test_primary_architecture_plan_cli_reports_topology_blocker(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_experiments.py",
                "--primary-architecture-plan",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertFalse(payload["runtime_execution_allowed"])
        self.assertEqual(payload["expected_runs"], 20)
        self.assertEqual(
            payload["status"],
            "blocked_primary_architecture_topology_implementation",
        )

    def test_primary_architecture_execution_cells_preserve_frozen_order(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        for scenario in (
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        ):
            cfg["scenarios"][scenario]["benchmark_status"] = "supported"

        plan, cells = build_primary_architecture_execution_cells(cfg)

        self.assertTrue(plan["runtime_execution_allowed"])
        self.assertEqual(len(cells), 20)
        self.assertEqual([cell["sequence"] for cell in cells], list(range(1, 21)))
        self.assertEqual(
            [cell["scenario_key"] for cell in cells[:4]],
            [
                "checkpoint_independent_processes_baseline",
                "checkpoint_video_dag_shared",
                "checkpoint_video_dag_shared",
                "checkpoint_independent_processes_baseline",
            ],
        )
        self.assertEqual(
            [
                cell["primary_architecture_pair"]["arm_position"]
                for cell in cells
            ],
            [1, 2] * 10,
        )
        self.assertTrue(all(cell["duration_s"] == 180 for cell in cells))
        self.assertTrue(all(cell["seed"] == 20260323 for cell in cells))

    def test_primary_architecture_resume_requires_contiguous_prefix(self) -> None:
        completed = {"status": "completed"}
        self.assertEqual(
            validate_primary_architecture_resume_prefix(
                [completed, completed, completed, None, None]
            ),
            3,
        )
        with self.assertRaisesRegex(ContractError, "contiguous prefix"):
            validate_primary_architecture_resume_prefix(
                [completed, None, completed]
            )

    def test_primary_architecture_executor_invokes_frozen_order(self) -> None:
        cfg = load_config(ROOT / "configs" / "experiments.yaml")
        for scenario in (
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        ):
            cfg["scenarios"][scenario]["benchmark_status"] = "supported"
        dataset = {
            "name": "kpp_real_h264",
            "streams": [{"absolute_path": "/tmp/unused-kpp-source.avi"}],
        }

        def completed_row(**kwargs: object) -> dict[str, object]:
            return {
                "status": "completed",
                "scenario": kwargs["scenario"]["name"],
                "repeat": kwargs["repeat_index"],
            }

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "run_experiments.load_dataset", return_value=dataset
            ), mock.patch(
                "run_experiments.load_hosts_config", return_value={}
            ), mock.patch(
                "run_experiments.validate_hardware"
            ), mock.patch(
                "run_experiments.run_one", side_effect=completed_row
            ) as run_mock, mock.patch(
                "run_experiments.write_summary_csv"
            ) as summary_mock:
                run_root, rows = run_primary_architecture_execution(
                    cfg,
                    output_root=Path(tmp),
                    resume_run_root=None,
                    hosts_config_path=ROOT / "configs" / "hosts.yaml",
                    single_server_host="127.0.0.1",
                    single_server_user="",
                    single_server_port=22,
                    requested_seed=None,
                )

        self.assertEqual(len(rows), 20)
        self.assertEqual(run_mock.call_count, 20)
        self.assertEqual(
            [call.kwargs["scenario"]["name"] for call in run_mock.call_args_list[:4]],
            [
                "checkpoint_independent_processes_baseline",
                "checkpoint_video_dag_shared",
                "checkpoint_video_dag_shared",
                "checkpoint_independent_processes_baseline",
            ],
        )
        self.assertEqual(
            [
                call.kwargs["primary_architecture_pair"]["arm_position"]
                for call in run_mock.call_args_list
            ],
            [1, 2] * 10,
        )
        self.assertTrue(all(call.kwargs["mode"] == "benchmark" for call in run_mock.call_args_list))
        self.assertTrue(all(call.kwargs["dry_run_plan"] is False for call in run_mock.call_args_list))
        self.assertEqual(summary_mock.call_args.args[0], run_root / "summary.csv")

    def test_primary_architecture_run_cli_fails_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "primary-runs"
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_experiments.py",
                    "--primary-architecture-run",
                    "--output-root",
                    str(output_root),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("primary architecture execution is blocked", completed.stderr)
            self.assertFalse(output_root.exists())

    def test_primary_architecture_run_cli_rejects_matrix_overrides(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/run_experiments.py",
                "--primary-architecture-run",
                "--dry-run-plan",
                "--continue-on-error",
                "--systems",
                "gstreamer_custom",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("uses only the frozen preregistered cell", completed.stderr)
        self.assertIn("--systems", completed.stderr)
        self.assertIn("--dry-run-plan", completed.stderr)
        self.assertIn("--continue-on-error", completed.stderr)


if __name__ == "__main__":
    unittest.main()
