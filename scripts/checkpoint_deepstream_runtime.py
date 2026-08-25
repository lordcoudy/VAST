#!/usr/bin/env python3
"""Fail-closed DeepStream checkpoint topology plan and hardware capability probe.

This module is deliberately not an accepted benchmark launcher. It describes the
physical DeepStream graphs required by the frozen matrix and can execute a small
SDK/NVDEC capability probe. It cannot promote probe output to measurement
evidence or publication readiness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from benchmark_contract import ContractError
from checkpoint_native_policy_runtime import (
    POLICY_RPC_FD_ENV,
    POLICY_RPC_MAX_MESSAGE_BYTES,
    POLICY_RPC_SCHEMA_VERSION,
)
from publication_policy_contract import ANALYTICS_BRANCHES, POLICIES
from checkpoint_runtime_plan import SOURCE_PLAYBACK_CONTRACT


PLAN_SCHEMA_VERSION = 1
PROBE_SCHEMA_VERSION = 1
ASSESSMENT_SCHEMA_VERSION = 1
DEEPSTREAM_IMAGE = "nvcr.io/nvidia/deepstream:7.0-triton-multiarch"
PLAN_CLAIM_STATUS = "executable_plan_only_not_measurement"
PROBE_CLAIM_STATUS = "engineering_capability_probe_not_measurement"
RUNTIME_EXECUTABLE = "/usr/local/bin/vast_deepstream_checkpoint_runtime"
GENERIC_PROBE_EXECUTABLE = "/usr/local/bin/vast_native_gst_probe"
POLICY_FD_ENV = POLICY_RPC_FD_ENV
POLICY_TRANSPORT = "posix_sock_seqpacket_inherited_fd"
PROTOCOL_BRIDGE_IMPLEMENTATION_STATUS = (
    "protocol_bridge_source_implemented_not_deepstream_sdk_bound_or_hardware_piloted"
)
ANALYTICS_EXECUTION_FACTORY = "vastdeepstreamanalyticsexecution"

SCENARIO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
PARSER_BY_CODEC = {"h264": "h264parse", "h265": "h265parse"}
FROZEN_DEADLINES_MS = (16.7, 33.3, 50.0, 100.0, 500.0)
REQUIRED_ELEMENTS = (
    "appsrc",
    "h264parse",
    "h265parse",
    "nvv4l2decoder",
    "nvstreammux",
    "nvvideoconvert",
    "capsfilter",
    "tee",
    "queue",
    "appsink",
)
BASE_BLOCKERS = (
    "deepstream_runtime_image_not_accepted_or_kpp_pair_piloted",
    "deepstream_protocol_v3_sdk_bridge_not_kpp_pair_piloted",
    "deepstream_native_policy_capability_manifest_or_hardware_binding_missing",
    "deepstream_cpu_gpu_branch_implementation_parity_missing",
    "deepstream_frozen_branch_model_parity_evidence_missing",
    "deepstream_accepted_resource_v2_emitter_missing",
    "deepstream_hardware_pilot_pair_missing",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_PLAN_FIELDS = {
    "schema_version", "artifact_kind", "claim_status", "system", "image",
    "scenario", "topology_kind", "topology_contract_version", "codec", "parser_factory", "dataset",
    "policy", "deadline_ms", "stream_count", "required_branches", "warmup_s",
    "measurement_s", "runtime_executable", "runtime_implementation_status",
    "topology_runtime_implemented", "publication_ready", "source_protocol",
    "runtime_event_protocol", "policy_binding", "model_binding", "sources",
    "admission_binding", "terminal_binding", "resource_binding",
    "pair_schedule_gate", "source_coordinators", "processes", "required_outputs",
    "accepted_measurement_evidence_emitted", "blockers",
}
_PROBE_FIELDS = {
    "schema_version", "artifact_kind", "claim_status", "system", "image",
    "image_id", "deepstream_sdk_version", "gpu", "sdk_headers_present",
    "python_gi_present", "pyds_present", "required_elements", "decoder_probes",
    "accepted_measurement_evidence_emitted", "publication_ready",
}


class DeepStreamRuntimeError(ContractError):
    """A DeepStream plan, probe, or readiness invariant failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamRuntimeError(message)


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise DeepStreamRuntimeError(f"{label} fields have drifted ({'; '.join(details)})")


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise DeepStreamRuntimeError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DeepStreamRuntimeError(f"{label} must be numeric") from exc
    _require(math.isfinite(result), f"{label} must be finite")
    return result


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeepStreamRuntimeError("DeepStream artifact is not canonical JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_scenario(config: Mapping[str, Any], scenario_name: str) -> tuple[dict[str, Any], str]:
    topology_kind = SCENARIO_TOPOLOGY.get(scenario_name)
    _require(topology_kind is not None, f"unsupported DeepStream checkpoint scenario: {scenario_name}")
    scenarios = config.get("scenarios")
    _require(isinstance(scenarios, Mapping), "config.scenarios is missing")
    raw = scenarios.get(scenario_name)
    _require(isinstance(raw, Mapping), f"scenario is missing: {scenario_name}")
    scenario = copy.deepcopy(dict(raw))
    _require(scenario.get("benchmark_status") == "supported", f"{scenario_name}: benchmark is not supported")
    topology = scenario.get("topology")
    _require(isinstance(topology, Mapping), f"{scenario_name}: topology is missing")
    _require(topology.get("contract_version") == 2, f"{scenario_name}: topology contract version drifted")
    _require(topology.get("kind") == topology_kind, f"{scenario_name}: topology kind drifted")
    _require(topology.get("routing_mode") == "all_branches_per_stream", f"{scenario_name}: routing mode drifted")
    branches = tuple(str(value) for value in topology.get("required_branches") or ())
    _require(branches == ANALYTICS_BRANCHES, f"{scenario_name}: frozen branch order drifted")
    workload = scenario.get("workload")
    _require(isinstance(workload, Mapping), f"{scenario_name}: workload is missing")
    _require(int(workload.get("streams", 0) or 0) == 6, f"{scenario_name}: requires six logical streams")
    _require(int(workload.get("logical_stream_instances", 0) or 0) == 6, f"{scenario_name}: requires six logical stream instances")
    _require(int(workload.get("analytics_function_types", 0) or 0) == len(ANALYTICS_BRANCHES), f"{scenario_name}: analytics branch count drifted")
    _require(workload.get("routing_mode") == "all_branches_per_stream", f"{scenario_name}: workload routing mode drifted")
    distributed = scenario.get("distributed")
    _require(isinstance(distributed, Mapping) and distributed.get("enabled") is False, f"{scenario_name}: DeepStream checkpoint plan is local-only")
    return scenario, topology_kind


def _frozen_coordinates(
    config: Mapping[str, Any], *, codec: str, policy: str, deadline_ms: Any,
) -> tuple[str, str, float, int, int]:
    _require(codec in DATASET_BY_CODEC, f"unsupported frozen checkpoint codec: {codec}")
    benchmark = config.get("benchmark")
    protocol = config.get("protocol")
    _require(isinstance(benchmark, Mapping), "config.benchmark is missing")
    _require(isinstance(protocol, Mapping), "config.protocol is missing")
    configured_policies = tuple(str(value) for value in benchmark.get("scheduler_policies") or ())
    _require(configured_policies == POLICIES, "frozen scheduler policy order drifted")
    _require(policy in POLICIES, f"unsupported frozen scheduler policy: {policy}")
    configured_deadlines = tuple(_finite_number(value, "configured deadline_ms") for value in benchmark.get("deadline_ms") or ())
    _require(configured_deadlines == FROZEN_DEADLINES_MS, "frozen deadline matrix drifted")
    deadline = _finite_number(deadline_ms, "deadline_ms")
    _require(deadline in FROZEN_DEADLINES_MS, f"deadline_ms is outside the frozen matrix: {deadline:g}")
    warmup_s = int(protocol.get("warmup_s", 0) or 0)
    measurement_s = int(protocol.get("measurement_s", 0) or 0)
    _require((warmup_s, measurement_s) == (30, 180), "frozen cohort duration drifted")
    _require(int(protocol.get("repeats", 0) or 0) == 10, "frozen repeat count drifted")
    return codec, policy, deadline, warmup_s, measurement_s


def _frozen_sources(
    datasets: Mapping[str, Any], *, codec: str,
) -> tuple[str, list[dict[str, Any]]]:
    dataset_name = DATASET_BY_CODEC[codec]
    raw = datasets.get(dataset_name)
    _require(isinstance(raw, Mapping), f"dataset is missing: {dataset_name}")
    dataset = dict(raw)
    _require(dataset.get("publishable") is True, f"{dataset_name}: dataset is not publishable")
    _require(dataset.get("codec_variant") == codec, f"{dataset_name}: codec variant drifted")
    _require(
        dict(dataset.get("benchmark_playback") or {})
        == {
            "contract_version": 1,
            "encoded_timeline_fps": SOURCE_PLAYBACK_CONTRACT["encoded_timeline_fps"],
            "offered_playback_fps": SOURCE_PLAYBACK_CONTRACT["offered_playback_fps"],
            "timestamp_scale": SOURCE_PLAYBACK_CONTRACT["timestamp_scale"],
            "selection_basis": SOURCE_PLAYBACK_CONTRACT["selection_basis"],
        },
        f"{dataset_name}: benchmark playback contract drifted",
    )
    streams = dataset.get("streams")
    _require(isinstance(streams, list) and len(streams) == 6, f"{dataset_name}: requires six streams")
    sources: list[dict[str, Any]] = []
    for expected_stream_id, raw_stream in enumerate(streams):
        _require(isinstance(raw_stream, Mapping), f"{dataset_name}: stream entry is invalid")
        stream = dict(raw_stream)
        _require(int(stream.get("stream_id", -1)) == expected_stream_id, f"{dataset_name}: stream IDs must be contiguous from zero")
        stream_codec = str(stream.get("codec_name", "")).lower()
        if stream_codec == "hevc":
            stream_codec = "h265"
        _require(stream_codec == codec, f"{dataset_name}: stream codec drifted")
        _require(str(stream.get("container", "")).lower() == "mp4", f"{dataset_name}: MP4 is required")
        sha256 = str(stream.get("sha256", "")).lower()
        _require(bool(_SHA256_RE.fullmatch(sha256)), f"{dataset_name}: source SHA-256 is invalid")
        path = str(stream.get("path", "")).strip()
        _require(bool(path), f"{dataset_name}: source path is missing")
        width = int(stream.get("width", 0) or 0)
        height = int(stream.get("height", 0) or 0)
        _require(width > 0 and height > 0, f"{dataset_name}: source dimensions are invalid")
        _require(int(stream.get("frame_count", 0) or 0) > 0, f"{dataset_name}: frame count is invalid")
        try:
            duration_seconds = Decimal(str(stream.get("duration_s")))
        except (InvalidOperation, ValueError) as exc:
            raise DeepStreamRuntimeError(f"{dataset_name}: source duration is invalid") from exc
        native_duration = duration_seconds * Decimal(1_000_000_000)
        _require(
            duration_seconds > 0 and native_duration == native_duration.to_integral_value(),
            f"{dataset_name}: source duration exceeds nanosecond precision",
        )
        native_duration_ns = int(native_duration)
        timestamp_scale = int(SOURCE_PLAYBACK_CONTRACT["timestamp_scale"])
        sources.append({
            "stream_id": expected_stream_id, "path": path, "source_sha256": sha256,
            "source_codec": codec, "container": "mp4", "width": width,
            "height": height, "frame_count": int(stream["frame_count"]),
            "source_id": str(stream.get("source_id", "")),
            "native_source_duration_ns": native_duration_ns,
            "source_duration_ns": native_duration_ns * timestamp_scale,
            "playback_timestamp_scale": timestamp_scale,
            "playback_fps": int(SOURCE_PLAYBACK_CONTRACT["offered_playback_fps"]),
        })
    return dataset_name, sources


def _source_prefix(source: Mapping[str, Any], *, codec: str) -> list[dict[str, Any]]:
    return [
        {"factory": "appsrc", "role": "admission_bound_compressed_access_unit_source", "format": "time", "timestamp_source": "native_common_source_coordinator"},
        {"factory": PARSER_BY_CODEC[codec], "role": "codec_parser", "codec": codec},
        {"factory": "nvv4l2decoder", "role": "hardware_decode", "execution_resource": "nvdec", "gpu_id": 0, "cudadec_memtype": "device", "software_fallback": "prohibited"},
        {"factory": "nvstreammux", "role": "single_stream_deepstream_batch_meta", "batch_size": 1, "width": int(source["width"]), "height": int(source["height"]), "live_source": False},
        {"factory": "nvvideoconvert", "role": "preprocess", "gpu_id": 0},
        {"factory": "capsfilter", "role": "system_memory_rgb_download", "caps": "video/x-raw,format=RGB"},
    ]


def _policy_dispatch(branch: str, *, policy: str, deadline_ms: float) -> dict[str, Any]:
    return {
        "factory": "vastdeepstreampolicydispatch",
        "role": "native_per_frame_policy_dispatch",
        "implementation_status": "python_native_sdk_callback_adapter_source_implemented",
        "branch": branch,
        "policy": policy,
        "deadline_ms": deadline_ms,
        "transport": POLICY_TRANSPORT,
        "fd_environment": POLICY_FD_ENV,
        "selected_execution_paths": {
            "cpu": {
                "factory": ANALYTICS_EXECUTION_FACTORY,
                "implementation_status": "seqpacket_endpoint_adapter_source_implemented_not_kpp_piloted",
                "engine": "openvino_cpu",
                "device_api": "CPU",
                "model_format": "frozen_openvino_ir_required",
            },
            "gpu": {
                "factory": ANALYTICS_EXECUTION_FACTORY,
                "implementation_status": "seqpacket_endpoint_adapter_source_implemented_not_kpp_piloted",
                "engine": "tensorrt_cuda",
                "device_api": "NVIDIA_CUDA",
                "model_format": "frozen_equivalent_tensorrt_engine_required",
            },
        },
    }


def _terminal(branch: str) -> dict[str, Any]:
    return {
        "factory": "vastdeepstreambranchterminal",
        "role": "protocol_v3_native_branch_terminal",
        "branch": branch,
        "implementation_status": PROTOCOL_BRIDGE_IMPLEMENTATION_STATUS,
        "event_provenance_required": "native_runtime_event",
    }


def _baseline_processes(
    sources: Sequence[Mapping[str, Any]],
    *,
    codec: str,
    policy: str,
    deadline_ms: float,
) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for source in sources:
        stream_id = int(source["stream_id"])
        for branch in ANALYTICS_BRANCHES:
            processes.append({
                "process_id": f"deepstream-stream-{stream_id}-branch-{branch}",
                "process_isolation": "os_process",
                "stream_id": stream_id,
                "branch": branch,
                "branches": [branch],
                "source_process_id": f"stream-{stream_id}-source-coordinator",
                "physical_pipeline": _source_prefix(source, codec=codec) + [
                    {
                        "factory": "appsink",
                        "role": "native_sdk_rgb_callback",
                        "branch": branch,
                        "sync": False,
                        "max_buffers": 1,
                    },
                ],
                "callback_dispatch": _policy_dispatch(
                    branch, policy=policy, deadline_ms=deadline_ms
                ),
                "callback_terminal": _terminal(branch),
            })
    return processes


def _shared_processes(
    sources: Sequence[Mapping[str, Any]],
    *,
    codec: str,
    policy: str,
    deadline_ms: float,
) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for source in sources:
        stream_id = int(source["stream_id"])
        processes.append({
            "process_id": f"deepstream-stream-{stream_id}-shared-video-dag",
            "process_isolation": "os_process",
            "stream_id": stream_id,
            "branches": list(ANALYTICS_BRANCHES),
            "source_process_id": f"stream-{stream_id}-source-coordinator",
            "shared_prefix": _source_prefix(source, codec=codec)
            + [{"factory": "tee", "role": "physical_shared_fanout"}],
            "routes": [
                {
                    "branch": branch,
                    "elements": [
                        {
                            "factory": "queue",
                            "role": "bounded_branch_waiting_queue",
                            "max_size_buffers": 1,
                            "leaky": "no",
                        },
                        {
                            "factory": "appsink",
                            "role": "native_sdk_rgb_callback",
                            "branch": branch,
                            "sync": False,
                            "max_buffers": 1,
                        },
                    ],
                    "callback_dispatch": _policy_dispatch(
                        branch, policy=policy, deadline_ms=deadline_ms
                    ),
                    "callback_terminal": _terminal(branch),
                }
                for branch in ANALYTICS_BRANCHES
            ],
        })
    return processes


def build_deepstream_runtime_plan(
    *,
    config: Mapping[str, Any],
    datasets: Mapping[str, Any],
    scenario: str,
    codec: str,
    policy: str,
    deadline_ms: Any,
) -> dict[str, Any]:
    """Build a DeepStream-specific, non-measurement plan for one frozen matrix cell."""

    _scenario, topology_kind = _frozen_scenario(config, scenario)
    codec, policy, deadline, warmup_s, measurement_s = _frozen_coordinates(
        config, codec=str(codec), policy=str(policy), deadline_ms=deadline_ms,
    )
    dataset_name, sources = _frozen_sources(datasets, codec=codec)
    processes = (
        _baseline_processes(sources, codec=codec, policy=policy, deadline_ms=deadline)
        if topology_kind == "independent_processes"
        else _shared_processes(sources, codec=codec, policy=policy, deadline_ms=deadline)
    )
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "artifact_kind": "deepstream_checkpoint_runtime_plan",
        "claim_status": PLAN_CLAIM_STATUS,
        "system": "deepstream",
        "image": DEEPSTREAM_IMAGE,
        "scenario": scenario,
        "topology_kind": topology_kind,
        "topology_contract_version": 2,
        "codec": codec,
        "parser_factory": PARSER_BY_CODEC[codec],
        "dataset": dataset_name,
        "policy": policy,
        "deadline_ms": deadline,
        "stream_count": 6,
        "required_branches": list(ANALYTICS_BRANCHES),
        "warmup_s": warmup_s,
        "measurement_s": measurement_s,
        "runtime_executable": RUNTIME_EXECUTABLE,
        "runtime_implementation_status": (
            "dedicated_native_sdk_runtime_source_and_offline_image_recipe_implemented_not_kpp_pair_piloted"
        ),
        "topology_runtime_implemented": False,
        "publication_ready": False,
        "source_protocol": "direct_admission_json_v1_with_framed_compressed_access_units",
        "runtime_event_protocol": "direct_runtime_json_v3_with_native_terminals_required",
        "policy_binding": {
            "contract_status": (
                "bridge_validates_decision_path_terminal_acks_server_manifest_missing"
            ),
            "rpc_schema_version": POLICY_RPC_SCHEMA_VERSION,
            "transport": POLICY_TRANSPORT,
            "fd_environment": POLICY_FD_ENV,
            "max_message_bytes": POLICY_RPC_MAX_MESSAGE_BYTES,
            "request_response_path_terminal_required": True,
            "derived_policy_or_resource_labels_prohibited": True,
            "nvidia_gpu_path_requirements": {
                "factories": [ANALYTICS_EXECUTION_FACTORY],
                "backends": ["analytics-execution:tensorrt_cuda"],
                "device_api": "NVIDIA_CUDA",
                "native_terminal_verified": True,
                "openvino_gpu_label_accepted": False,
            },
        },
        "model_binding": {
            "frozen_cpu_manifest": "configs/checkpoint_analytics_models_openvino.yaml",
            "frozen_cpu_format": "openvino_ir_fp16",
            "execution_protocol": "vast_analytics_execution_protocol_v1",
            "bridge_requires_cpu_gpu_source_model_and_contract_identity": True,
            "deepstream_gpu_binding_status": "frozen_tensorrt_engines_present_parity_evidence_not_accepted",
            "same_model_semantics_per_cpu_gpu_resource_required": True,
            "sample_deepstream_models_accepted": False,
        },
        "admission_binding": {
            "source_event_protocol": "direct_admission_json_v1",
            "source_event_protocol_version": 1,
            "worker_event_protocol": "direct_runtime_json_v3_with_native_terminals",
            "worker_event_protocol_version": 3,
            "common_source_processes": 6,
            "admission_before_worker_source_read_required": True,
            "selection_basis": "decode_order_schedule_offset_half_open",
        },
        "terminal_binding": {
            "runtime_protocol_version": 3,
            "required_branches": list(ANALYTICS_BRANCHES),
            "native_branch_outcomes_per_frame": len(ANALYTICS_BRANCHES),
            "telemetry_source": "native",
            "event_provenance": "native_runtime_event",
            "posthoc_or_derived_terminal_events_accepted": False,
            "bridge_source": "scripts/checkpoint_deepstream_protocol_bridge.py",
            "bridge_implementation_status": PROTOCOL_BRIDGE_IMPLEMENTATION_STATUS,
            "analytics_response_and_policy_terminal_ack_required": True,
            "synthetic_bridge_events_accepted_as_native": False,
        },
        "resource_binding": {
            "status": "native_per_frame_and_device_evidence_missing",
            "selected_resource_source": "native_policy_path_enter_and_terminal",
            "nvdec_factory": "nvv4l2decoder",
            "nvdec_busy_source_required": "device_level_nvml_sampled",
            "fanout_work_source_required": "native_cpu_thread_time_sampled",
            "derived_stage_name_resource_labels_accepted": False,
            "analytics_execution_resource_fields_validated": True,
            "uniform_per_branch_native_capability_receipt_emitted": False,
            "uniform_receipt_required_fields": [
                "implementation_id",
                "emitter_sha256",
                "decision_ack",
                "path_ack",
                "terminal_ack",
                "service_sample",
                "transfer_sample",
            ],
            "accepted_resource_v2_evidence_emitted": False,
        },
        "pair_schedule_gate": {
            "artifact_kind": "checkpoint_terminal_admission_audit",
            "selection_basis": "decode_order_schedule_offset_half_open",
            "required_rule": "equal_measurement_schedule_fingerprint_sha256",
            "evaluation_phase": "after_both_arms_before_pair_acceptance",
            "empty_or_incomplete_schedule_accepted": False,
        },
        "sources": sources,
        "source_coordinators": [
            {
                "process_id": f"stream-{int(source['stream_id'])}-source-coordinator",
                "stream_id": int(source["stream_id"]),
                "executable": "/usr/local/bin/vast_checkpoint_source",
                "native_source": True,
                "admission_before_worker_read_required": True,
                "source_sha256": str(source["source_sha256"]),
                "input_path": str(source["path"]),
                "source_container": str(source["container"]),
                "source_codec": str(source["source_codec"]),
                "native_source_duration_ns": int(source["native_source_duration_ns"]),
                "source_duration_ns": int(source["source_duration_ns"]),
                "playback_timestamp_scale": int(source["playback_timestamp_scale"]),
                "playback_fps": int(source["playback_fps"]),
            }
            for source in sources
        ],
        "processes": processes,
        "required_outputs": [
            "frames.csv", "frame_events.csv", "topology_events.csv",
            "ingress_ledger.csv", "branch_terminals.csv", "reset_evidence.csv",
            "stage_contracts.csv", "drop_counters.csv", "resource_events.csv",
            "policy_decisions.csv", "checkpoint_publication_acceptance.json",
        ],
        "accepted_measurement_evidence_emitted": False,
        "blockers": list(BASE_BLOCKERS),
    }
    validate_deepstream_runtime_plan(plan)
    return plan


def _validate_prefix(prefix: Any, *, codec: str, label: str, tee_required: bool) -> None:
    _require(isinstance(prefix, list), f"{label}: physical prefix must be a list")
    factories = [
        str(value.get("factory", ""))
        for value in prefix
        if isinstance(value, Mapping)
    ]
    expected = [
        "appsrc", PARSER_BY_CODEC[codec], "nvv4l2decoder",
        "nvstreammux", "nvvideoconvert", "capsfilter",
    ]
    if factories[:6] != expected:
        raise DeepStreamRuntimeError(
            f"{label}: physical prefix must use appsrc/{PARSER_BY_CODEC[codec]}/"
            "nvv4l2decoder/nvstreammux/nvvideoconvert/capsfilter"
        )
    decoder = prefix[2]
    _require(decoder.get("execution_resource") == "nvdec", f"{label}: decoder is not bound to NVDEC")
    _require(decoder.get("gpu_id") == 0, f"{label}: decoder gpu_id drifted")
    _require(decoder.get("software_fallback") == "prohibited", f"{label}: software decoder fallback is enabled")
    mux = prefix[3]
    _require(mux.get("batch_size") == 1, f"{label}: effective batch size must be one")
    if tee_required:
        _require(factories == expected + ["tee"], f"{label}: shared prefix must end in a physical tee")


def _validate_dispatch(
    value: Any, *, branch: str, policy: str, deadline_ms: float, label: str,
) -> None:
    _require(isinstance(value, Mapping), f"{label}: policy dispatch is missing")
    _require(value.get("factory") == "vastdeepstreampolicydispatch", f"{label}: policy dispatch factory drifted")
    _require(value.get("branch") == branch, f"{label}: policy dispatch branch drifted")
    _require(value.get("policy") == policy, f"{label}: policy was not propagated")
    _require(value.get("deadline_ms") == deadline_ms, f"{label}: deadline was not propagated")
    _require(value.get("transport") == POLICY_TRANSPORT, f"{label}: policy transport drifted")
    _require(value.get("fd_environment") == POLICY_FD_ENV, f"{label}: policy FD binding drifted")
    paths = value.get("selected_execution_paths")
    _require(isinstance(paths, Mapping) and set(paths) == {"cpu", "gpu"}, f"{label}: CPU/GPU paths are incomplete")
    _require(
        paths["cpu"].get("factory") == ANALYTICS_EXECUTION_FACTORY
        and paths["cpu"].get("engine") == "openvino_cpu"
        and paths["cpu"].get("device_api") == "CPU",
        f"{label}: CPU analytics execution endpoint drifted",
    )
    _require(
        paths["gpu"].get("factory") == ANALYTICS_EXECUTION_FACTORY
        and paths["gpu"].get("engine") == "tensorrt_cuda"
        and paths["gpu"].get("device_api") == "NVIDIA_CUDA",
        f"{label}: GPU analytics execution endpoint drifted",
    )


def validate_deepstream_runtime_plan(plan: Mapping[str, Any]) -> None:
    """Reject topology relabeling, matrix drift, or accidental readiness claims."""

    _require(isinstance(plan, Mapping), "DeepStream runtime plan must be a mapping")
    _exact_fields(plan, _PLAN_FIELDS, "DeepStream runtime plan")
    _require(plan.get("schema_version") == PLAN_SCHEMA_VERSION, "DeepStream plan schema drifted")
    _require(plan.get("artifact_kind") == "deepstream_checkpoint_runtime_plan", "DeepStream plan kind drifted")
    _require(plan.get("claim_status") == PLAN_CLAIM_STATUS, "DeepStream plan claim status drifted")
    _require(plan.get("system") == "deepstream", "DeepStream plan system drifted")
    _require(plan.get("image") == DEEPSTREAM_IMAGE, "DeepStream image drifted")
    scenario = str(plan.get("scenario", ""))
    expected_topology = SCENARIO_TOPOLOGY.get(scenario)
    _require(expected_topology is not None, "DeepStream plan scenario drifted")
    _require(plan.get("topology_kind") == expected_topology, "DeepStream plan topology kind drifted")
    _require(
        plan.get("topology_contract_version") == 2,
        "DeepStream plan topology contract version drifted",
    )
    codec = str(plan.get("codec", ""))
    _require(codec in DATASET_BY_CODEC, "DeepStream plan codec drifted")
    _require(plan.get("parser_factory") == PARSER_BY_CODEC[codec], "DeepStream parser factory drifted")
    _require(plan.get("dataset") == DATASET_BY_CODEC[codec], "DeepStream dataset/codec binding drifted")
    policy = str(plan.get("policy", ""))
    _require(policy in POLICIES, "DeepStream plan policy drifted")
    deadline_ms = _finite_number(plan.get("deadline_ms"), "DeepStream plan deadline_ms")
    _require(deadline_ms in FROZEN_DEADLINES_MS, "DeepStream plan deadline drifted")
    _require(plan.get("stream_count") == 6, "DeepStream plan requires six logical streams")
    _require(tuple(plan.get("required_branches") or ()) == ANALYTICS_BRANCHES, "DeepStream branch order drifted")
    _require((plan.get("warmup_s"), plan.get("measurement_s")) == (30, 180), "DeepStream cohort drifted")
    executable = str(plan.get("runtime_executable", ""))
    if executable == GENERIC_PROBE_EXECUTABLE:
        raise DeepStreamRuntimeError(
            "generic probe cannot be relabelled as the DeepStream checkpoint runtime"
        )
    _require(executable == RUNTIME_EXECUTABLE, "DeepStream runtime executable drifted")
    _require(
        plan.get("runtime_implementation_status")
        == "dedicated_native_sdk_runtime_source_and_offline_image_recipe_implemented_not_kpp_pair_piloted",
        "DeepStream runtime implementation status drifted",
    )
    _require(
        plan.get("topology_runtime_implemented") is False,
        "unpiloted DeepStream topology must remain unimplemented",
    )
    _require(plan.get("publication_ready") is False, "unpiloted DeepStream runtime must remain blocked")
    _require(
        plan.get("accepted_measurement_evidence_emitted") is False,
        "DeepStream plan must not claim accepted measurement evidence",
    )
    _require(tuple(plan.get("blockers") or ()) == BASE_BLOCKERS, "DeepStream blocker set drifted")
    policy_binding = plan.get("policy_binding")
    _require(isinstance(policy_binding, Mapping), "DeepStream policy binding is missing")
    _require(
        policy_binding.get("rpc_schema_version") == POLICY_RPC_SCHEMA_VERSION,
        "DeepStream policy RPC schema drifted",
    )
    _require(policy_binding.get("transport") == POLICY_TRANSPORT, "DeepStream policy transport drifted")
    _require(policy_binding.get("fd_environment") == POLICY_FD_ENV, "DeepStream policy FD env drifted")
    _require(
        policy_binding.get("max_message_bytes") == POLICY_RPC_MAX_MESSAGE_BYTES,
        "DeepStream policy message limit drifted",
    )
    _require(
        policy_binding.get("derived_policy_or_resource_labels_prohibited") is True,
        "DeepStream plan permits derived policy/resource labels",
    )
    model_binding = plan.get("model_binding")
    _require(isinstance(model_binding, Mapping), "DeepStream model binding is missing")
    _require(
        model_binding.get("deepstream_gpu_binding_status")
        == "frozen_tensorrt_engines_present_parity_evidence_not_accepted",
        "DeepStream plan incorrectly claims frozen GPU models",
    )
    gpu_requirements = policy_binding.get("nvidia_gpu_path_requirements")
    _require(isinstance(gpu_requirements, Mapping), "DeepStream NVIDIA GPU path requirements are missing")
    _require(
        gpu_requirements.get("factories") == [ANALYTICS_EXECUTION_FACTORY]
        and gpu_requirements.get("backends")
        == ["analytics-execution:tensorrt_cuda"]
        and gpu_requirements.get("device_api") == "NVIDIA_CUDA"
        and gpu_requirements.get("native_terminal_verified") is True
        and gpu_requirements.get("openvino_gpu_label_accepted") is False,
        "DeepStream NVIDIA CUDA/TensorRT path requirements drifted",
    )
    admission = plan.get("admission_binding")
    _require(isinstance(admission, Mapping), "DeepStream admission binding is missing")
    _require(
        admission.get("source_event_protocol") == "direct_admission_json_v1"
        and admission.get("source_event_protocol_version") == 1
        and admission.get("worker_event_protocol")
        == "direct_runtime_json_v3_with_native_terminals"
        and admission.get("worker_event_protocol_version") == 3,
        "DeepStream common admission protocol drifted",
    )
    _require(admission.get("common_source_processes") == 6, "DeepStream admission source count drifted")
    _require(
        admission.get("admission_before_worker_source_read_required") is True,
        "DeepStream admission is not ordered before worker source_read",
    )
    _require(
        admission.get("selection_basis") == "decode_order_schedule_offset_half_open",
        "DeepStream measurement admission selection drifted",
    )
    terminal = plan.get("terminal_binding")
    _require(isinstance(terminal, Mapping), "DeepStream terminal binding is missing")
    _require(
        terminal.get("runtime_protocol_version") == 3
        and terminal.get("required_branches") == list(ANALYTICS_BRANCHES)
        and terminal.get("native_branch_outcomes_per_frame") == len(ANALYTICS_BRANCHES)
        and terminal.get("telemetry_source") == "native"
        and terminal.get("event_provenance") == "native_runtime_event"
        and terminal.get("posthoc_or_derived_terminal_events_accepted") is False,
        "DeepStream protocol-v3 terminal contract drifted",
    )
    _require(
        terminal.get("bridge_source")
        == "scripts/checkpoint_deepstream_protocol_bridge.py"
        and terminal.get("bridge_implementation_status")
        == PROTOCOL_BRIDGE_IMPLEMENTATION_STATUS
        and terminal.get("analytics_response_and_policy_terminal_ack_required") is True
        and terminal.get("synthetic_bridge_events_accepted_as_native") is False,
        "DeepStream protocol bridge readiness was overstated",
    )
    resource = plan.get("resource_binding")
    _require(isinstance(resource, Mapping), "DeepStream resource binding is missing")
    _require(
        resource.get("status") == "native_per_frame_and_device_evidence_missing"
        and resource.get("selected_resource_source")
        == "native_policy_path_enter_and_terminal"
        and resource.get("nvdec_factory") == "nvv4l2decoder"
        and resource.get("nvdec_busy_source_required") == "device_level_nvml_sampled"
        and resource.get("fanout_work_source_required")
        == "native_cpu_thread_time_sampled"
        and resource.get("derived_stage_name_resource_labels_accepted") is False,
        "DeepStream resource evidence contract drifted",
    )
    _require(
        resource.get("analytics_execution_resource_fields_validated") is True
        and resource.get("uniform_per_branch_native_capability_receipt_emitted")
        is False
        and resource.get("uniform_receipt_required_fields")
        == [
            "implementation_id",
            "emitter_sha256",
            "decision_ack",
            "path_ack",
            "terminal_ack",
            "service_sample",
            "transfer_sample",
        ]
        and resource.get("accepted_resource_v2_evidence_emitted") is False,
        "DeepStream analytics resource binding readiness was overstated",
    )
    schedule_gate = plan.get("pair_schedule_gate")
    _require(isinstance(schedule_gate, Mapping), "DeepStream pair schedule gate is missing")
    _require(
        schedule_gate == {
            "artifact_kind": "checkpoint_terminal_admission_audit",
            "selection_basis": "decode_order_schedule_offset_half_open",
            "required_rule": "equal_measurement_schedule_fingerprint_sha256",
            "evaluation_phase": "after_both_arms_before_pair_acceptance",
            "empty_or_incomplete_schedule_accepted": False,
        },
        "DeepStream pair schedule gate drifted",
    )
    sources = plan.get("sources")
    _require(isinstance(sources, list) and len(sources) == 6, "DeepStream plan requires six sources")
    _require([value.get("stream_id") for value in sources] == list(range(6)), "DeepStream source IDs drifted")
    _require(all(value.get("source_codec") == codec for value in sources), "DeepStream source codec drifted")
    _require(
        all(bool(_SHA256_RE.fullmatch(str(value.get("source_sha256", "")))) for value in sources),
        "DeepStream source SHA-256 drifted",
    )
    coordinators = plan.get("source_coordinators")
    _require(
        isinstance(coordinators, list) and len(coordinators) == 6,
        "DeepStream plan requires six source coordinators",
    )
    _require(
        [value.get("stream_id") for value in coordinators] == list(range(6)),
        "DeepStream source coordinator coverage drifted",
    )
    for source, coordinator in zip(sources, coordinators, strict=True):
        _require(
            coordinator.get("input_path") == source.get("path")
            and coordinator.get("source_container") == source.get("container")
            and coordinator.get("source_codec") == source.get("source_codec")
            and coordinator.get("source_duration_ns") == source.get("source_duration_ns")
            and coordinator.get("playback_timestamp_scale")
            == SOURCE_PLAYBACK_CONTRACT["timestamp_scale"]
            and coordinator.get("playback_fps")
            == SOURCE_PLAYBACK_CONTRACT["offered_playback_fps"],
            "DeepStream source coordinator playback binding drifted",
        )
    processes = plan.get("processes")
    _require(isinstance(processes, list), "DeepStream processes must be a list")
    process_ids = [
        str(value.get("process_id", ""))
        for value in processes
        if isinstance(value, Mapping)
    ]
    _require(len(process_ids) == len(set(process_ids)), "DeepStream process IDs are duplicated")
    if expected_topology == "independent_processes":
        _require(len(processes) == 24, "DeepStream baseline requires twenty-four independent processes")
        expected_coordinates = {
            (stream_id, branch)
            for stream_id in range(6)
            for branch in ANALYTICS_BRANCHES
        }
        actual_coordinates = {
            (value.get("stream_id"), value.get("branch"))
            for value in processes
            if isinstance(value, Mapping)
        }
        _require(actual_coordinates == expected_coordinates, "DeepStream baseline process coverage drifted")
        for process in processes:
            label = str(process.get("process_id"))
            _require(process.get("process_isolation") == "os_process", f"{label}: baseline process isolation drifted")
            branch = str(process.get("branch", ""))
            _require(process.get("branches") == [branch], f"{label}: baseline process contains another branch")
            pipeline = process.get("physical_pipeline")
            _validate_prefix(pipeline, codec=codec, label=label, tee_required=False)
            _require(isinstance(pipeline, list) and len(pipeline) == 7, f"{label}: baseline physical pipeline drifted")
            _require(
                pipeline[6].get("factory") == "appsink"
                and pipeline[6].get("branch") == branch,
                f"{label}: SDK callback appsink is missing",
            )
            _validate_dispatch(
                process.get("callback_dispatch"), branch=branch, policy=policy,
                deadline_ms=deadline_ms, label=label,
            )
            _require(
                process.get("callback_terminal", {}).get("factory")
                == "vastdeepstreambranchterminal"
                and process.get("callback_terminal", {}).get("branch") == branch,
                f"{label}: protocol-v3 branch terminal is missing",
            )
    else:
        _require(len(processes) == 6, "DeepStream shared topology requires six shared processes")
        _require(
            {value.get("stream_id") for value in processes} == set(range(6)),
            "DeepStream shared process coverage drifted",
        )
        for process in processes:
            label = str(process.get("process_id"))
            _require(process.get("process_isolation") == "os_process", f"{label}: process isolation drifted")
            _require(tuple(process.get("branches") or ()) == ANALYTICS_BRANCHES, f"{label}: branch set drifted")
            _validate_prefix(process.get("shared_prefix"), codec=codec, label=label, tee_required=True)
            routes = process.get("routes")
            _require(isinstance(routes, list) and len(routes) == 4, f"{label}: four routes are required")
            _require(
                {value.get("branch") for value in routes} == set(ANALYTICS_BRANCHES),
                f"{label}: route branches drifted",
            )
            for route in routes:
                branch = str(route.get("branch"))
                elements = route.get("elements")
                _require(isinstance(elements, list), f"{label}/{branch}: route elements drifted")
                _require(
                    bool(elements)
                    and isinstance(elements[0], Mapping)
                    and elements[0].get("factory") == "queue",
                    f"{label}/{branch}: branch queue is missing",
                )
                _require(len(elements) == 2, f"{label}/{branch}: route elements drifted")
                queue = elements[0]
                _require(queue.get("max_size_buffers") == 1, f"{label}/{branch}: queue capacity drifted")
                _require(queue.get("leaky") == "no", f"{label}/{branch}: GStreamer queue must not infer native callback drops")
                _require(
                    elements[1].get("factory") == "appsink"
                    and elements[1].get("branch") == branch,
                    f"{label}/{branch}: SDK callback appsink is missing",
                )
                _validate_dispatch(
                    route.get("callback_dispatch"), branch=branch, policy=policy,
                    deadline_ms=deadline_ms, label=f"{label}/{branch}",
                )
                _require(
                    route.get("callback_terminal", {}).get("factory")
                    == "vastdeepstreambranchterminal"
                    and route.get("callback_terminal", {}).get("branch") == branch,
                    f"{label}/{branch}: protocol-v3 branch terminal is missing",
                )


def parse_probe_payload(text: str) -> dict[str, Any]:
    """Parse an engineering probe without allowing accepted-evidence claims."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeepStreamRuntimeError("DeepStream capability probe did not return JSON") from exc
    _require(isinstance(raw, Mapping), "DeepStream capability probe must be a JSON object")
    payload = copy.deepcopy(dict(raw))
    _exact_fields(payload, _PROBE_FIELDS, "DeepStream capability probe")
    _require(payload.get("schema_version") == PROBE_SCHEMA_VERSION, "DeepStream probe schema drifted")
    _require(payload.get("artifact_kind") == "deepstream_checkpoint_capability_probe", "DeepStream probe kind drifted")
    _require(payload.get("claim_status") == PROBE_CLAIM_STATUS, "DeepStream probe claim status drifted")
    _require(payload.get("system") == "deepstream", "DeepStream probe system drifted")
    _require(payload.get("image") == DEEPSTREAM_IMAGE, "DeepStream probe image drifted")
    _require(bool(_IMAGE_ID_RE.fullmatch(str(payload.get("image_id", "")))), "DeepStream probe image ID is invalid")
    _require(str(payload.get("deepstream_sdk_version", "")).startswith("7.0."), "DeepStream 7.0 SDK probe is required")
    gpu = payload.get("gpu")
    _require(isinstance(gpu, Mapping), "DeepStream probe GPU record is missing")
    _exact_fields(gpu, {"name", "driver_version", "visible"}, "DeepStream probe GPU")
    _require(type(gpu.get("visible")) is bool, "DeepStream probe GPU visibility must be boolean")
    for name in ("sdk_headers_present", "python_gi_present", "pyds_present"):
        _require(type(payload.get(name)) is bool, f"DeepStream probe {name} must be boolean")
    elements = payload.get("required_elements")
    _require(isinstance(elements, Mapping), "DeepStream probe element records are missing")
    _require(set(elements) == set(REQUIRED_ELEMENTS), "DeepStream probe element set drifted")
    for name, value in elements.items():
        _require(isinstance(value, Mapping), f"DeepStream probe element {name} is invalid")
        _exact_fields(
            value, {"available", "plugin_filename", "plugin_version"},
            f"DeepStream probe element {name}",
        )
        _require(type(value.get("available")) is bool, f"DeepStream probe element {name} availability is not boolean")
        _require(type(value.get("plugin_filename")) is str, f"DeepStream probe element {name} filename is invalid")
        _require(type(value.get("plugin_version")) is str, f"DeepStream probe element {name} version is invalid")
    decoders = payload.get("decoder_probes")
    _require(
        isinstance(decoders, Mapping) and set(decoders) == {"h264", "h265"},
        "DeepStream decoder probe set drifted",
    )
    decoder_fields = {
        "passed", "decoder_factory", "parser_factory", "gpu_id",
        "decoded_buffers", "source_sha256", "command_exit_code",
    }
    for codec, value in decoders.items():
        _require(isinstance(value, Mapping), f"DeepStream {codec} decoder probe is invalid")
        _exact_fields(value, decoder_fields, f"DeepStream {codec} decoder probe")
        _require(type(value.get("passed")) is bool, f"DeepStream {codec} decoder passed value is not boolean")
        _require(value.get("decoder_factory") == "nvv4l2decoder", f"DeepStream {codec} probe relabelled the decoder")
        _require(value.get("parser_factory") == PARSER_BY_CODEC[codec], f"DeepStream {codec} parser drifted")
        _require(type(value.get("gpu_id")) is int and value.get("gpu_id") == 0, f"DeepStream {codec} gpu_id drifted")
        _require(
            type(value.get("decoded_buffers")) is int
            and value.get("decoded_buffers") in {0, 1},
            f"DeepStream {codec} decoded buffer count is invalid",
        )
        _require(
            bool(_SHA256_RE.fullmatch(str(value.get("source_sha256", "")))),
            f"DeepStream {codec} source SHA-256 is invalid",
        )
        _require(type(value.get("command_exit_code")) is int, f"DeepStream {codec} exit code is invalid")
        if value["passed"]:
            _require(
                value["decoded_buffers"] == 1 and value["command_exit_code"] == 0,
                f"DeepStream {codec} passing probe lacks a decoded buffer",
            )
    _require(
        payload.get("accepted_measurement_evidence_emitted") is False,
        "DeepStream capability probe must not emit accepted measurement evidence",
    )
    _require(
        payload.get("publication_ready") is False,
        "DeepStream capability probe publication_ready must remain false",
    )
    return payload


def assess_deepstream_runtime_readiness(
    plan: Mapping[str, Any],
    probe: Mapping[str, Any],
) -> dict[str, Any]:
    """Return precise blockers; an SDK probe can never satisfy runtime acceptance."""

    validate_deepstream_runtime_plan(plan)
    validated_probe = parse_probe_payload(_canonical_json(probe).decode("utf-8"))
    blockers = list(BASE_BLOCKERS)
    if validated_probe["image"] != plan["image"]:
        blockers.append("deepstream_probe_image_mismatch")
    if validated_probe["gpu"]["visible"] is not True:
        blockers.append("deepstream_gpu_not_visible")
    if validated_probe["sdk_headers_present"] is not True:
        blockers.append("deepstream_sdk_headers_missing")
    for name, value in validated_probe["required_elements"].items():
        if value["available"] is not True:
            blockers.append(f"deepstream_gstreamer_element_missing:{name}")
    hardware_decoder_support: dict[str, bool] = {}
    for codec in ("h264", "h265"):
        passed = validated_probe["decoder_probes"][codec]["passed"] is True
        hardware_decoder_support[codec] = passed
        if not passed:
            blockers.append(f"deepstream_{codec}_nvdec_probe_failed")
    blockers = list(dict.fromkeys(blockers))
    probe_blockers = {
        "deepstream_gpu_not_visible",
        "deepstream_sdk_headers_missing",
        "deepstream_h264_nvdec_probe_failed",
        "deepstream_h265_nvdec_probe_failed",
    }
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "artifact_kind": "deepstream_checkpoint_runtime_readiness",
        "passed": False,
        "status": "blocked",
        "topology_runtime_implemented": False,
        "publication_ready": False,
        "scenario": plan["scenario"],
        "codec": plan["codec"],
        "policy": plan["policy"],
        "deadline_ms": plan["deadline_ms"],
        "sdk_probe_passed": not any(
            value in probe_blockers
            or value.startswith("deepstream_gstreamer_element_missing:")
            for value in blockers
        ),
        "hardware_decoder_support": hardware_decoder_support,
        "probe_sha256": hashlib.sha256(_canonical_json(validated_probe)).hexdigest(),
        "blockers": blockers,
    }


def build_probe_command(
    project_root: Path,
    *,
    image: str = DEEPSTREAM_IMAGE,
    image_id: str | None = None,
    docker_binary: str = "docker",
) -> list[str]:
    """Return an argument-safe Docker probe command with read-only mounts."""

    _require(image == DEEPSTREAM_IMAGE, "DeepStream probe image is not frozen")
    root = Path(project_root).resolve()
    probe_dir = root / "deploy" / "deepstream" / "checkpoint"
    data_dir = root / "data" / "videos" / "kpp"
    probe_script = probe_dir / "deepstream_checkpoint_capability_probe.py"
    _require(probe_script.is_file(), f"DeepStream capability probe script is missing: {probe_script}")
    for codec in ("h264", "h265"):
        _require((data_dir / codec / "1.mp4").is_file(), f"DeepStream {codec} probe source is missing")
    command = [
        docker_binary,
        "run",
        "--rm",
        "--gpus",
        "all",
        "--entrypoint",
        "python3",
        "--mount",
        f"type=bind,source={probe_dir},target=/opt/vast/checkpoint,readonly",
        "--mount",
        f"type=bind,source={data_dir},target=/opt/vast/kpp,readonly",
        "-e",
        f"VAST_DEEPSTREAM_IMAGE={image}",
        "-e",
        f"VAST_H264_SOURCE_SHA256={_sha256_file(data_dir / 'h264' / '1.mp4')}",
        "-e",
        f"VAST_H265_SOURCE_SHA256={_sha256_file(data_dir / 'h265' / '1.mp4')}",
    ]
    if image_id is not None:
        _require(bool(_IMAGE_ID_RE.fullmatch(image_id)), "DeepStream Docker image ID is invalid")
        command.extend(["-e", f"VAST_DEEPSTREAM_IMAGE_ID={image_id}"])
    command.extend([image, "/opt/vast/checkpoint/deepstream_checkpoint_capability_probe.py"])
    return command


def run_capability_probe(
    project_root: Path,
    *,
    image: str = DEEPSTREAM_IMAGE,
    docker_binary: str = "docker",
    timeout_s: float = 90.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Execute only the one-buffer SDK/NVDEC probe, never a benchmark arm."""

    inspect = runner(
        [docker_binary, "image", "inspect", "--format", "{{.Id}}", image],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if inspect.returncode != 0:
        raise DeepStreamRuntimeError("DeepStream Docker image inspection failed") from None
    image_id = inspect.stdout.strip()
    _require(
        bool(_IMAGE_ID_RE.fullmatch(image_id)),
        "DeepStream Docker image inspection returned an invalid ID",
    )
    command = build_probe_command(
        project_root, image=image, image_id=image_id, docker_binary=docker_binary,
    )
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if completed.returncode != 0:
        raise DeepStreamRuntimeError(
            f"DeepStream capability probe failed with exit code {completed.returncode}"
        ) from None
    payload = parse_probe_payload(completed.stdout)
    _require(
        payload["image_id"] == image_id,
        "DeepStream probe image ID differs from Docker inspection",
    )
    return payload


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    _require(isinstance(value, Mapping), f"{path}: expected a YAML mapping")
    return dict(value)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or probe the fail-closed DeepStream checkpoint runtime plan."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    plan_parser.add_argument("--datasets", type=Path, default=Path("configs/datasets.yaml"))
    plan_parser.add_argument("--scenario", choices=tuple(SCENARIO_TOPOLOGY), required=True)
    plan_parser.add_argument("--codec", choices=tuple(DATASET_BY_CODEC), required=True)
    plan_parser.add_argument("--policy", choices=POLICIES, required=True)
    plan_parser.add_argument("--deadline-ms", type=float, required=True)
    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    probe_parser.add_argument("--image", default=DEEPSTREAM_IMAGE)
    assess_parser = subparsers.add_parser("assess")
    assess_parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    assess_parser.add_argument("--datasets", type=Path, default=Path("configs/datasets.yaml"))
    assess_parser.add_argument("--probe", type=Path, required=True)
    assess_parser.add_argument("--scenario", choices=tuple(SCENARIO_TOPOLOGY), required=True)
    assess_parser.add_argument("--codec", choices=tuple(DATASET_BY_CODEC), required=True)
    assess_parser.add_argument("--policy", choices=POLICIES, required=True)
    assess_parser.add_argument("--deadline-ms", type=float, required=True)
    args = parser.parse_args()

    if args.command == "probe":
        _print_json(run_capability_probe(args.project_root, image=args.image))
        return 0

    config = _load_yaml(args.config)
    datasets_document = _load_yaml(args.datasets)
    datasets = datasets_document.get("datasets")
    _require(isinstance(datasets, Mapping), "datasets document is missing datasets")
    plan = build_deepstream_runtime_plan(
        config=config,
        datasets=datasets,
        scenario=args.scenario,
        codec=args.codec,
        policy=args.policy,
        deadline_ms=args.deadline_ms,
    )
    if args.command == "plan":
        _print_json(plan)
        return 0
    probe = parse_probe_payload(args.probe.read_text(encoding="utf-8"))
    assessment = assess_deepstream_runtime_readiness(plan, probe)
    _print_json(assessment)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
