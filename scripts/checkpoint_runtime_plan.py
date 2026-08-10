#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from benchmark_contract import (
    ContractError,
    PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
    PRIMARY_ANALYTICS_QUEUE_CONTRACT,
    validate_primary_architecture_contrast,
)


BLUEPRINT_CONTRACT_VERSION = 1
CHECKPOINT_SCENARIOS = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
CLAIM_STATUS = "planning_only_not_measurement"
FRAME_IDENTITY_CONTRACT = {
    "contract_version": 3,
    "source": "native_common_source_coordinator_compressed_access_unit_before_decode",
    "input_frame_key_template": (
        "{dataset}:{stream_id}:{source_sha256}:{source_cycle}:{buffer_pts_ns}"
    ),
    "admission_id_template": "{run_id}:{stream_id}:admission:{admission_sequence}",
    "payload_identity": "sha256_of_compressed_access_unit_bytes",
    "trace_id_template": "{run_id}:{stream_id}:{frame_ordinal}",
    "pairing_requirement": (
        "same_stream_source_sha256_source_cycle_buffer_pts_payload_sha256_and_schedule_offset"
    ),
    "source_cycle_origin": "zero_based_increment_after_native_eos_before_seek_zero",
}
SOURCE_PLAYBACK_CONTRACT = {
    "contract_version": 3,
    "mode": "common_source_coordinator_continuous_replay",
    "cycle_boundary": "native_pipeline_eos_then_flush_seek_zero",
    "delivery_order": "gap_free_admission_sequence",
    "compressed_timestamp_order": "native_pts_may_reorder_for_b_frames",
    "worker_timestamp_mapping": "native_pts_dts_preserved_with_source_cycle_offset",
    "predecode_ingress_required": True,
    "source_coordinator_per_logical_stream": 1,
    "independent_worker_file_readers_pair_eligible": False,
    "consumer_payload": "same_compressed_access_unit_bytes",
    "common_start_barrier_required": True,
    "stop_admission_at_measurement_end_required": True,
    "drain_required": True,
}
COMMON_ADMISSION_CONTRACT = {
    "contract_version": 2,
    "implementation_status": "locally_executed_synthetic_h264_h265_engineering_unaccepted",
    "producer_scope": "one_native_source_process_per_logical_stream",
    "source_event_protocol": "direct_admission_json_v1",
    "worker_event_protocol": "direct_runtime_json_v2_with_admission_link",
    "payload_transport": "native_framed_compressed_access_unit_broadcast_required",
    "pacing_origin": "common_start_monotonic",
    "schedule_coordinate": "gap_free_sequence_source_cycle_native_pts_and_decode_order_duration_offset_ns",
    "worker_file_read_fallback": "engineering_only_not_pair_eligible",
    "pair_gate": "equal_schedule_fingerprint_sha256",
    "terminal_gate": "native_completed_drop_or_censored_ledger_required_separately",
}
DECODER_PLACEMENT_RUNTIME_GATE = {
    "contract_version": 1,
    "required_state": "DECODER_PLACEMENT_VERIFIED",
    "verification_phase": "warmup_before_measurement_window",
    "failure_action": "terminate_run_before_measurement_acceptance",
    "worker_scope": "every_checkpoint_worker",
    "evidence_limit": "runtime_gate_does_not_replace_accepted_stage_contracts_or_nvdec_busy_time",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: expected a YAML mapping")
    return data


def _duration_ns(raw: Any, *, context: str) -> int:
    try:
        seconds = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"{context}: invalid duration_s") from exc
    _require(seconds > 0, f"{context}: duration_s must be positive")
    nanoseconds = seconds * Decimal(1_000_000_000)
    _require(nanoseconds == nanoseconds.to_integral_value(), f"{context}: duration_s exceeds ns precision")
    return int(nanoseconds)


def _canonical_codec(raw: Any, *, context: str) -> str:
    codec = str(raw).lower()
    if codec == "hevc":
        codec = "h265"
    _require(codec in {"h264", "h265"}, f"{context}: checkpoint runtime requires H.264 or H.265")
    return codec


def _scenario_contract(scenario_name: str, scenario: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    expected_kind = CHECKPOINT_SCENARIOS.get(scenario_name)
    _require(expected_kind is not None, f"unsupported checkpoint scenario: {scenario_name}")
    topology = dict(scenario.get("topology") or {})
    _require(
        int(topology.get("contract_version", 0) or 0) == 1,
        f"{scenario_name}: topology contract version 1 is required",
    )
    _require(
        str(topology.get("kind", "")) == expected_kind,
        f"{scenario_name}: expected topology kind {expected_kind}",
    )
    _require(
        str(topology.get("routing_mode", "")) == "all_branches_per_stream",
        f"{scenario_name}: routing_mode must be all_branches_per_stream",
    )
    branches = [str(value) for value in topology.get("required_branches", [])]
    _require(bool(branches) and len(branches) == len(set(branches)), f"{scenario_name}: branches must be unique")
    workload = dict(scenario.get("workload") or {})
    _require(
        str(workload.get("routing_mode", "")) == "all_branches_per_stream",
        f"{scenario_name}: workload routing does not match topology",
    )
    _require(
        int(workload.get("analytics_function_types", 0) or 0) == len(branches),
        f"{scenario_name}: analytics_function_types does not match branches",
    )
    blueprint = dict(topology.get("runtime_blueprint") or {})
    _require(
        int(blueprint.get("contract_version", 0) or 0) == BLUEPRINT_CONTRACT_VERSION,
        f"{scenario_name}: runtime blueprint contract version {BLUEPRINT_CONTRACT_VERSION} is required",
    )
    _require(
        str(blueprint.get("join_source", "")) == "direct_runtime_completion_events",
        f"{scenario_name}: join must use direct runtime completion events",
    )
    return expected_kind, branches, blueprint


def _dataset_streams(dataset_name: str, dataset: dict[str, Any], expected_streams: int) -> list[dict[str, Any]]:
    streams = [dict(value) for value in dataset.get("streams", [])]
    _require(len(streams) == expected_streams, f"{dataset_name}: expected {expected_streams} dataset streams")
    ids = [int(stream.get("stream_id", -1)) for stream in streams]
    _require(ids == list(range(expected_streams)), f"{dataset_name}: stream_id values must be contiguous from zero")
    for stream in streams:
        stream_id = int(stream["stream_id"])
        context = f"{dataset_name}: stream {stream_id}"
        _require(bool(str(stream.get("path", ""))), f"{dataset_name}: stream path is required")
        sha256 = str(stream.get("sha256", ""))
        _require(len(sha256) == 64, f"{dataset_name}: stream sha256 is required")
        _require(str(stream.get("container", "")).lower() == "mp4", f"{context}: MP4 container is required")
        _canonical_codec(stream.get("codec_name"), context=context)
        _duration_ns(stream.get("duration_s"), context=context)
        _require(int(stream.get("frame_count", 0) or 0) > 0, f"{context}: frame_count must be positive")
    return streams


def _source_contract(stream: dict[str, Any], *, total_window_ns: int) -> dict[str, Any]:
    duration_ns = _duration_ns(stream.get("duration_s"), context=f"stream {stream['stream_id']}")
    return {
        "input_path": str(stream["path"]),
        "source_sha256": str(stream["sha256"]),
        "source_container": str(stream["container"]).lower(),
        "source_codec": _canonical_codec(stream.get("codec_name"), context=f"stream {stream['stream_id']}"),
        "source_duration_ns": duration_ns,
        "source_frame_count": int(stream["frame_count"]),
        "continuous_replay_required": duration_ns < total_window_ns,
    }


def _baseline_stream_plan(
    *,
    stream: dict[str, Any],
    branches: list[str],
    system: str,
    total_window_ns: int,
    analytics_queue: dict[str, Any],
) -> dict[str, Any]:
    stream_id = int(stream["stream_id"])
    source = _source_contract(stream, total_window_ns=total_window_ns)
    workers = []
    for branch in branches:
        workers.append(
            {
                "process_id": f"stream-{stream_id}-branch-{branch}",
                "process_kind": "independent_branch_worker",
                "branch_id": branch,
                "execution_domain_template": (
                    f"{{host}}:pid={{pid}}:system={system}:stream={stream_id}:branch={branch}"
                ),
                **source,
                "stages": [f"decode_{branch}", f"preprocess_{branch}", branch],
                "analytics_queue": dict(analytics_queue),
                "completion_delivery": "direct_runtime_ipc",
            }
        )
    return {
        "stream_id": stream_id,
        "source_id": str(stream.get("source_id", "")),
        "workers": workers,
        "join": {
            "coordinator_scope": "run",
            "required_branch_ids": branches,
            "emission_trigger": "all_branch_completion_events_for_input_frame_key",
        },
    }


def _shared_stream_plan(
    *,
    stream: dict[str, Any],
    branches: list[str],
    system: str,
    blueprint: dict[str, Any],
    total_window_ns: int,
    analytics_queue: dict[str, Any],
) -> dict[str, Any]:
    stream_id = int(stream["stream_id"])
    return {
        "stream_id": stream_id,
        "source_id": str(stream.get("source_id", "")),
        "graph_process": {
            "process_id": f"stream-{stream_id}-shared-video-dag",
            "process_kind": "shared_video_dag_worker",
            "execution_domain_template": f"{{host}}:pid={{pid}}:system={system}:stream={stream_id}:shared",
            **_source_contract(stream, total_window_ns=total_window_ns),
            "shared_prefix_stages": ["decode", "preprocess"],
            "fanout_primitive": str(blueprint.get("fanout_primitive", "")),
            "branches": [
                {
                    "branch_id": branch,
                    "queue_required": bool(blueprint.get("branch_queue_per_route", False)),
                    "analytics_queue": dict(analytics_queue),
                    "stages": [branch],
                }
                for branch in branches
            ],
            "join": {
                "required_branch_ids": branches,
                "emission_trigger": "all_branch_completion_events_for_input_frame_key",
            },
        },
    }


def build_checkpoint_runtime_plan(
    *,
    scenario_name: str,
    scenario: dict[str, Any],
    dataset_name: str,
    dataset: dict[str, Any],
    system: str,
    cohort_protocol: dict[str, Any],
    analytics_queue: dict[str, Any],
    decoder_placement: dict[str, Any],
) -> dict[str, Any]:
    topology_kind, branches, blueprint = _scenario_contract(scenario_name, scenario)
    workload = dict(scenario.get("workload") or {})
    stream_count = int(workload.get("streams", 0) or 0)
    _require(stream_count > 0, f"{scenario_name}: workload streams must be positive")
    streams = _dataset_streams(dataset_name, dataset, stream_count)
    warmup_s = int(cohort_protocol.get("warmup_s", 0) or 0)
    measurement_s = int(cohort_protocol.get("measurement_s", 0) or 0)
    _require(warmup_s > 0 and measurement_s > 0, "checkpoint cohort requires positive warmup and measurement")
    total_window_ns = (warmup_s + measurement_s) * 1_000_000_000

    if topology_kind == "independent_processes":
        _require(
            str(blueprint.get("branch_isolation", "")) == "os_process",
            f"{scenario_name}: baseline branches must use os_process isolation",
        )
        stream_plans = [
            _baseline_stream_plan(
                stream=stream,
                branches=branches,
                system=system,
                total_window_ns=total_window_ns,
                analytics_queue=analytics_queue,
            )
            for stream in streams
        ]
    else:
        _require(
            str(blueprint.get("fanout_primitive", "")) == "gstreamer_tee",
            f"{scenario_name}: shared fanout must use gstreamer_tee",
        )
        _require(
            bool(blueprint.get("branch_queue_per_route", False)),
            f"{scenario_name}: every shared branch must have its own queue",
        )
        stream_plans = [
            _shared_stream_plan(
                stream=stream,
                branches=branches,
                system=system,
                blueprint=blueprint,
                total_window_ns=total_window_ns,
                analytics_queue=analytics_queue,
            )
            for stream in streams
        ]

    plan = {
        "schema_version": BLUEPRINT_CONTRACT_VERSION,
        "artifact_kind": "checkpoint_runtime_blueprint",
        "claim_status": CLAIM_STATUS,
        "scenario": scenario_name,
        "dataset": dataset_name,
        "system": system,
        "benchmark_status": str(scenario.get("benchmark_status", "")),
        "topology_contract_version": 1,
        "topology_kind": topology_kind,
        "routing_mode": "all_branches_per_stream",
        "required_branches": branches,
        "analytics_queue": dict(analytics_queue),
        "decoder_placement": dict(decoder_placement),
        "decoder_placement_runtime_gate": dict(DECODER_PLACEMENT_RUNTIME_GATE),
        "frame_identity": FRAME_IDENTITY_CONTRACT,
        "source_playback": SOURCE_PLAYBACK_CONTRACT,
        "external_admission": COMMON_ADMISSION_CONTRACT,
        "cohort_protocol": {
            "contract_version": 1,
            "warmup_s": warmup_s,
            "measurement_s": measurement_s,
            "total_runtime_s": warmup_s + measurement_s,
            "window_clock": "wall_clock_after_common_start_barrier",
            "ingress_stage": "compressed_access_unit_before_decode",
        },
        "runtime_join": {
            "source": "direct_runtime_completion_events",
            "transport": "local_ipc",
            "posthoc_csv_join_prohibited": True,
        },
        "source_coordinators": [
            {
                "process_id": f"stream-{int(stream['stream_id'])}-source-coordinator",
                "process_kind": "native_common_source_coordinator",
                "stream_id": int(stream["stream_id"]),
                **_source_contract(stream, total_window_ns=total_window_ns),
                "admission_delivery": "direct_runtime_ipc_before_worker_source_read",
                "consumer_payload_delivery": "native_framed_compressed_access_unit_broadcast_required",
            }
            for stream in streams
        ],
        "required_native_outputs": [
            "frames.csv",
            "frame_events.csv",
            "topology_events.csv",
            "ingress_ledger.csv",
            "stage_contracts.csv",
        ],
        "streams": stream_plans,
    }
    validate_checkpoint_runtime_plan(plan)
    return plan


def validate_checkpoint_runtime_plan(plan: dict[str, Any]) -> None:
    _require(int(plan.get("schema_version", 0) or 0) == BLUEPRINT_CONTRACT_VERSION, "invalid blueprint version")
    _require(plan.get("claim_status") == CLAIM_STATUS, "runtime blueprint must remain planning-only")
    _require(plan.get("benchmark_status") == "blocked_topology", "blueprint must not silently unblock benchmark")
    _require(
        (plan.get("runtime_join") or {}).get("source") == "direct_runtime_completion_events",
        "join source must be direct runtime completion events",
    )
    _require(
        bool((plan.get("runtime_join") or {}).get("posthoc_csv_join_prohibited")),
        "post-hoc CSV join must be prohibited",
    )
    _require(plan.get("frame_identity") == FRAME_IDENTITY_CONTRACT, "checkpoint frame identity contract drifted")
    _require(plan.get("source_playback") == SOURCE_PLAYBACK_CONTRACT, "checkpoint source playback contract drifted")
    _require(plan.get("external_admission") == COMMON_ADMISSION_CONTRACT, "checkpoint admission contract drifted")
    _require(
        plan.get("analytics_queue") == PRIMARY_ANALYTICS_QUEUE_CONTRACT,
        "checkpoint analytics queue contract drifted",
    )
    _require(
        plan.get("decoder_placement") == PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
        "checkpoint decoder placement contract drifted",
    )
    _require(
        plan.get("decoder_placement_runtime_gate") == DECODER_PLACEMENT_RUNTIME_GATE,
        "checkpoint decoder placement runtime gate drifted",
    )
    cohort = dict(plan.get("cohort_protocol") or {})
    _require(int(cohort.get("contract_version", 0) or 0) == 1, "checkpoint cohort contract version 1 is required")
    warmup_s = int(cohort.get("warmup_s", 0) or 0)
    measurement_s = int(cohort.get("measurement_s", 0) or 0)
    _require(warmup_s > 0 and measurement_s > 0, "checkpoint cohort durations must be positive")
    _require(
        int(cohort.get("total_runtime_s", 0) or 0) == warmup_s + measurement_s,
        "checkpoint cohort total runtime differs from warmup plus measurement",
    )

    def validate_source(owner: dict[str, Any]) -> None:
        _require(owner.get("source_container") == "mp4", "checkpoint source container must be MP4")
        _require(
            owner.get("source_codec") == PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT["codec"],
            "checkpoint source codec differs from the decoder placement contract",
        )
        duration_ns = int(owner.get("source_duration_ns", 0) or 0)
        _require(duration_ns > 0, "checkpoint source duration must be positive")
        _require(int(owner.get("source_frame_count", 0) or 0) > 0, "checkpoint source frame count must be positive")
        replay_required = duration_ns < (warmup_s + measurement_s) * 1_000_000_000
        _require(
            owner.get("continuous_replay_required") is replay_required,
            "checkpoint source replay requirement differs from finite source duration",
        )

    branches = [str(value) for value in plan.get("required_branches", [])]
    streams = list(plan.get("streams", []))
    _require(bool(streams), "blueprint must contain stream plans")
    source_coordinators = list(plan.get("source_coordinators", []))
    _require(
        len(source_coordinators) == len(streams),
        "blueprint must contain one source coordinator per logical stream",
    )
    _require(
        {int(value.get("stream_id", -1)) for value in source_coordinators}
        == {int(value.get("stream_id", -1)) for value in streams},
        "source coordinator streams do not cover the runtime plan",
    )
    _require(
        all(value.get("process_kind") == "native_common_source_coordinator" for value in source_coordinators),
        "checkpoint source coordinators must be native processes",
    )
    for source_coordinator in source_coordinators:
        validate_source(source_coordinator)
        _require(
            source_coordinator.get("admission_delivery") == "direct_runtime_ipc_before_worker_source_read",
            "source admission must precede worker source_read",
        )
    if plan.get("topology_kind") == "independent_processes":
        for stream in streams:
            workers = list(stream.get("workers", []))
            _require(len(workers) == len(branches), "baseline stream must have one worker per branch")
            _require({worker.get("branch_id") for worker in workers} == set(branches), "baseline branches mismatch")
            domains = [str(worker.get("execution_domain_template", "")) for worker in workers]
            _require(len(domains) == len(set(domains)), "baseline workers must have distinct execution domains")
            _require(
                all(worker.get("process_kind") == "independent_branch_worker" for worker in workers),
                "baseline workers must be independent processes",
            )
            for worker in workers:
                validate_source(worker)
                _require(
                    worker.get("analytics_queue") == PRIMARY_ANALYTICS_QUEUE_CONTRACT,
                    "baseline branch analytics queue contract drifted",
                )
    elif plan.get("topology_kind") == "shared_video_dag":
        for stream in streams:
            graph = dict(stream.get("graph_process") or {})
            _require(graph.get("fanout_primitive") == "gstreamer_tee", "shared graph requires gstreamer_tee")
            _require(graph.get("shared_prefix_stages") == ["decode", "preprocess"], "shared prefix mismatch")
            route_plans = list(graph.get("branches", []))
            _require({route.get("branch_id") for route in route_plans} == set(branches), "shared branches mismatch")
            _require(all(route.get("queue_required") is True for route in route_plans), "shared branch queue missing")
            _require(
                all(route.get("analytics_queue") == PRIMARY_ANALYTICS_QUEUE_CONTRACT for route in route_plans),
                "shared branch analytics queue contract drifted",
            )
            validate_source(graph)
    else:
        raise ContractError(f"unsupported topology kind in blueprint: {plan.get('topology_kind')!r}")


def build_primary_pair_plans(
    *, config: dict[str, Any], datasets: dict[str, Any], system: str
) -> dict[str, Any]:
    primary = validate_primary_architecture_contrast(config)
    dataset_name = str(primary.get("dataset", ""))
    _require(dataset_name in datasets, f"unknown primary dataset: {dataset_name}")
    dataset = dict(datasets[dataset_name])
    _require(
        str(dataset.get("codec_variant", "")) == str(primary.get("codec", "")),
        "primary dataset codec differs from preregistration",
    )
    plans: dict[str, Any] = {}
    cohort_protocol = {
        "warmup_s": int(primary.get("warmup_s", 0) or 0),
        "measurement_s": int(primary.get("measurement_s", 0) or 0),
    }
    analytics_queue = dict(primary["analytics_queue"])
    for key in ("baseline_scenario", "shared_scenario"):
        scenario_name = str(primary.get(key, ""))
        _require(scenario_name in config.get("scenarios", {}), f"unknown primary scenario: {scenario_name}")
        plans[key] = build_checkpoint_runtime_plan(
            scenario_name=scenario_name,
            scenario=dict(config["scenarios"][scenario_name]),
            dataset_name=dataset_name,
            dataset=dataset,
            system=system,
            cohort_protocol=cohort_protocol,
            analytics_queue=analytics_queue,
            decoder_placement=dict(primary["decoder_placement"]),
        )
    baseline = plans["baseline_scenario"]
    shared = plans["shared_scenario"]
    _require(baseline["required_branches"] == shared["required_branches"], "primary pair branches differ")
    _require(len(baseline["streams"]) == len(shared["streams"]), "primary pair stream counts differ")
    _require(
        baseline["required_branches"] == [str(value) for value in primary.get("required_branches", [])],
        "runtime blueprint branches differ from preregistration",
    )
    _require(
        len(baseline["streams"]) == int(primary.get("streams", 0) or 0),
        "runtime blueprint stream count differs from preregistration",
    )
    _require(primary.get("routing_mode") == "all_branches_per_stream", "primary routing mode drifted")
    _require(int(primary.get("effective_batch_size", 0) or 0) == 1, "runtime blueprint requires batch size 1")
    _require(
        baseline["decoder_placement"] == shared["decoder_placement"] == primary["decoder_placement"],
        "primary pair decoder placement contracts differ",
    )
    _require(
        baseline["decoder_placement_runtime_gate"]
        == shared["decoder_placement_runtime_gate"]
        == DECODER_PLACEMENT_RUNTIME_GATE,
        "primary pair decoder placement runtime gates differ",
    )
    for left, right in zip(baseline["streams"], shared["streams"], strict=True):
        left_workers = left["workers"]
        right_graph = right["graph_process"]
        _require(
            {worker["source_sha256"] for worker in left_workers} == {right_graph["source_sha256"]},
            "primary pair input sources differ",
        )
        for key in (
            "source_container",
            "source_codec",
            "source_duration_ns",
            "source_frame_count",
            "continuous_replay_required",
        ):
            _require(
                {worker[key] for worker in left_workers} == {right_graph[key]},
                f"primary pair source {key} differs",
            )
    return {
        "schema_version": BLUEPRINT_CONTRACT_VERSION,
        "artifact_kind": "primary_checkpoint_runtime_blueprint_pair",
        "claim_status": CLAIM_STATUS,
        "preregistration_version": 1,
        "selection_basis": str(primary.get("selection_basis", "")),
        "analytics_queue": analytics_queue,
        "decoder_placement": dict(primary["decoder_placement"]),
        "decoder_placement_runtime_gate": dict(DECODER_PLACEMENT_RUNTIME_GATE),
        "system": system,
        "baseline": baseline,
        "shared": shared,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a non-measurement runtime blueprint for the primary checkpoint pair.")
    parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    parser.add_argument("--datasets", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--system", default="gstreamer_custom")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    config = _load_yaml(args.config)
    datasets_config = _load_yaml(args.datasets)
    plans = build_primary_pair_plans(
        config=config,
        datasets=dict(datasets_config.get("datasets") or {}),
        system=str(args.system),
    )
    payload = json.dumps(plans, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
