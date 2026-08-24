#!/usr/bin/env python3
"""Fail-closed Savant checkpoint topology plan and capability preflight.

The plan freezes the physical Savant layout required by the two checkpoint
scenarios.  The executable probe checks only the pinned framework, plugins,
GPU and one decoded H264/H265 buffer.  Neither artifact is measurement
evidence and neither can claim publication readiness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
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


PLAN_SCHEMA_VERSION = 1
PROBE_SCHEMA_VERSION = 1
ASSESSMENT_SCHEMA_VERSION = 1
SAVANT_IMAGE = "ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0"
SAVANT_IMAGE_ID = (
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
SAVANT_IMAGE_REPO_DIGEST = (
    "ghcr.io/insight-platform/savant-deepstream@"
    "sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6"
)
SAVANT_VERSION = "0.5.17"
SAVANT_ENTRYPOINT = ("python", "-m", "savant.entrypoint")
PLAN_CLAIM_STATUS = "executable_plan_only_not_measurement"
PROBE_CLAIM_STATUS = "engineering_capability_probe_not_measurement"
RUNTIME_EXECUTABLE = "/usr/local/bin/vast_savant_checkpoint_runtime"
GENERIC_PROBE_EXECUTABLE = "/usr/local/bin/vast_native_gst_probe"
POLICY_TRANSPORT = "posix_sock_seqpacket_inherited_fd"

SCENARIO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
DATASET_BY_CODEC = {"h264": "kpp_real_h264", "h265": "kpp_real_h265"}
PARSER_BY_CODEC = {"h264": "h264parse", "h265": "h265parse"}
FROZEN_DEADLINES_MS = (16.7, 33.3, 50.0, 100.0, 500.0)
FROZEN_CPU_MANIFEST_SHA256 = (
    "db011831a08136683985ef529b28c11e2e4aa91b73a036945ffc31e768d2eb8b"
)
REQUIRED_ELEMENTS = (
    "appsrc", "h264parse", "h265parse", "nvv4l2decoder", "nvstreammux",
    "nvvideoconvert", "nvinfer", "tee", "queue", "appsink",
    "fakesink",
)

POLICY_REQUEST_FIELDS = (
    "schema_version", "message_type", "run_id", "worker_id", "input_frame_key",
    "trace_id", "stream_id", "frame_id", "transport_pts_ns", "branch",
    "arrival_ms", "decision_time_ms", "feature_observed_timestamp_ms",
    "queue_depths",
)
POLICY_RESPONSE_FIELDS = (
    "schema_version", "message_type", "decision_id", "decision_seq",
    "selected_resource", "selected_implementation_id", "emitter_id",
    "emitter_sha256",
)
POLICY_PATH_ENTER_FIELDS = (
    "schema_version", "message_type", "run_id", "worker_id", "decision_id",
    "input_frame_key", "branch", "transport_pts_ns", "selected_resource",
    "implementation_id", "emitter_id", "emitter_sha256", "event_id",
    "timestamp_ms",
)
POLICY_TERMINAL_FIELDS = (
    "schema_version", "message_type", "run_id", "worker_id", "decision_id",
    "input_frame_key", "branch", "transport_pts_ns", "selected_resource",
    "terminal_status", "terminal_timestamp_ms", "actual_service_ms",
    "detector", "backend",
)

BASE_BLOCKERS = (
    "savant_dedicated_checkpoint_runtime_missing",
    "savant_frozen_topology_module_configs_missing",
    "savant_common_admission_protocol_v3_binding_missing",
    "savant_protocol_v3_bridge_not_sdk_bound_or_hardware_piloted",
    "savant_native_policy_seqpacket_binding_missing",
    "savant_equivalent_cpu_cuda_branch_models_missing",
    "savant_accepted_resource_v2_emitter_missing",
    "savant_hardware_pilot_pair_missing",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_PLAN_FIELDS = {
    "schema_version", "artifact_kind", "claim_status", "system", "image",
    "image_id", "image_repo_digest", "savant_version", "savant_entrypoint",
    "scenario", "topology_kind", "codec", "parser_factory", "dataset",
    "policy", "deadline_ms", "stream_count", "queued_branches_per_stream",
    "required_branches", "warmup_s", "measurement_s", "runtime_executable",
    "runtime_implementation_status", "topology_runtime_implemented",
    "publication_ready", "savant_module_binding", "source_protocol",
    "runtime_event_protocol", "policy_binding", "model_binding",
    "admission_binding", "terminal_binding", "resource_binding",
    "pair_schedule_gate", "sources", "source_coordinators", "processes",
    "required_outputs", "accepted_measurement_evidence_emitted", "blockers",
    "topology_plan_sha256",
}
_PROBE_FIELDS = {
    "schema_version", "artifact_kind", "claim_status", "system", "image",
    "image_id", "image_repo_digest", "savant_version", "savant_import_path",
    "savant_entrypoint", "deepstream_sdk_version", "gpu",
    "required_elements", "decoder_probes",
    "dedicated_checkpoint_runtime_present",
    "protocol_v3_policy_adapter_present", "resource_v2_emitter_present",
    "generic_probe_executed", "accepted_measurement_evidence_emitted",
    "publication_ready",
}


class SavantRuntimeError(ContractError):
    """A Savant topology, probe, or readiness invariant failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantRuntimeError(message)


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if extra:
            detail.append(f"extra={','.join(extra)}")
        raise SavantRuntimeError(
            f"{label} fields have drifted ({'; '.join(detail)})"
        )


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise SavantRuntimeError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SavantRuntimeError(f"{label} must be numeric") from exc
    _require(math.isfinite(result), f"{label} must be finite")
    return result


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SavantRuntimeError("Savant artifact is not canonical JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_identity(plan: Mapping[str, Any]) -> str:
    payload = {
        key: value for key, value in plan.items()
        if key != "topology_plan_sha256"
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _frozen_scenario(
    config: Mapping[str, Any], scenario_name: str,
) -> str:
    systems = config.get("systems")
    _require(isinstance(systems, Mapping), "config.systems is missing")
    savant_system = systems.get("savant")
    _require(isinstance(savant_system, Mapping), "Savant system config is missing")
    _require(
        savant_system.get("container_image") == SAVANT_IMAGE,
        "Savant pinned image tag drifted",
    )
    _require(
        savant_system.get("backend") == "deepstream_tensorrt",
        "Savant configured backend drifted",
    )
    topology_kind = SCENARIO_TOPOLOGY.get(scenario_name)
    _require(
        topology_kind is not None,
        f"unsupported Savant checkpoint scenario: {scenario_name}",
    )
    scenarios = config.get("scenarios")
    _require(isinstance(scenarios, Mapping), "config.scenarios is missing")
    scenario = scenarios.get(scenario_name)
    _require(isinstance(scenario, Mapping), f"scenario is missing: {scenario_name}")
    _require(
        scenario.get("benchmark_status") == "supported",
        f"{scenario_name}: benchmark is not supported",
    )
    topology = scenario.get("topology")
    _require(isinstance(topology, Mapping), f"{scenario_name}: topology missing")
    _require(
        topology.get("contract_version") == 1
        and topology.get("kind") == topology_kind
        and topology.get("routing_mode") == "all_branches_per_stream",
        f"{scenario_name}: topology contract drifted",
    )
    _require(
        tuple(topology.get("required_branches") or ()) == ANALYTICS_BRANCHES,
        f"{scenario_name}: frozen branch order drifted",
    )
    workload = scenario.get("workload")
    _require(isinstance(workload, Mapping), f"{scenario_name}: workload missing")
    _require(
        int(workload.get("streams", 0) or 0) == 6,
        f"{scenario_name}: requires six logical streams",
    )
    _require(
        int(workload.get("logical_stream_instances", 0) or 0) == 6,
        f"{scenario_name}: requires six logical stream instances",
    )
    _require(
        int(workload.get("analytics_function_types", 0) or 0) == 4
        and workload.get("routing_mode") == "all_branches_per_stream",
        f"{scenario_name}: four-branch workload drifted",
    )
    distributed = scenario.get("distributed")
    _require(
        isinstance(distributed, Mapping) and distributed.get("enabled") is False,
        f"{scenario_name}: Savant checkpoint plan is local-only",
    )
    return str(topology_kind)


def _frozen_coordinates(
    config: Mapping[str, Any], *, codec: str, policy: str, deadline_ms: Any,
) -> tuple[str, str, float, int, int]:
    _require(codec in DATASET_BY_CODEC, f"unsupported frozen checkpoint codec: {codec}")
    benchmark, protocol = config.get("benchmark"), config.get("protocol")
    _require(isinstance(benchmark, Mapping), "config.benchmark is missing")
    _require(isinstance(protocol, Mapping), "config.protocol is missing")
    _require(
        tuple(benchmark.get("scheduler_policies") or ()) == POLICIES,
        "frozen scheduler policy order drifted",
    )
    _require(policy in POLICIES, f"unsupported frozen scheduler policy: {policy}")
    deadlines = tuple(
        _finite_number(value, "configured deadline_ms")
        for value in benchmark.get("deadline_ms") or ()
    )
    _require(deadlines == FROZEN_DEADLINES_MS, "frozen deadline matrix drifted")
    deadline = _finite_number(deadline_ms, "deadline_ms")
    _require(
        deadline in FROZEN_DEADLINES_MS,
        f"deadline_ms is outside the frozen matrix: {deadline:g}",
    )
    warmup_s = int(protocol.get("warmup_s", 0) or 0)
    measurement_s = int(protocol.get("measurement_s", 0) or 0)
    _require((warmup_s, measurement_s) == (30, 180), "cohort duration drifted")
    _require(int(protocol.get("repeats", 0) or 0) == 10, "repeat count drifted")
    return codec, policy, deadline, warmup_s, measurement_s


def _frozen_sources(
    datasets: Mapping[str, Any], *, codec: str,
) -> tuple[str, list[dict[str, Any]]]:
    dataset_name = DATASET_BY_CODEC[codec]
    dataset = datasets.get(dataset_name)
    _require(isinstance(dataset, Mapping), f"dataset missing: {dataset_name}")
    _require(dataset.get("publishable") is True, f"{dataset_name}: not publishable")
    _require(dataset.get("codec_variant") == codec, f"{dataset_name}: codec drifted")
    streams = dataset.get("streams")
    _require(
        isinstance(streams, list) and len(streams) == 6,
        f"{dataset_name}: requires six streams",
    )
    result = []
    for expected_id, raw in enumerate(streams):
        _require(isinstance(raw, Mapping), f"{dataset_name}: invalid stream")
        stream = dict(raw)
        _require(
            int(stream.get("stream_id", -1)) == expected_id,
            f"{dataset_name}: stream IDs must be contiguous",
        )
        stream_codec = str(stream.get("codec_name", "")).lower()
        if stream_codec == "hevc":
            stream_codec = "h265"
        _require(stream_codec == codec, f"{dataset_name}: stream codec drifted")
        _require(
            str(stream.get("container", "")).lower() == "mp4",
            f"{dataset_name}: MP4 required",
        )
        source_hash = str(stream.get("sha256", "")).lower()
        _require(
            bool(_SHA256_RE.fullmatch(source_hash)),
            f"{dataset_name}: invalid source SHA-256",
        )
        width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
        frame_count = int(stream.get("frame_count", 0))
        _require(width > 0 and height > 0 and frame_count > 0, "source metadata invalid")
        _require(bool(str(stream.get("path", "")).strip()), "source path missing")
        result.append({
            "stream_id": expected_id,
            "path": str(stream.get("path", "")),
            "source_sha256": source_hash,
            "source_codec": codec,
            "container": "mp4",
            "width": width,
            "height": height,
            "frame_count": frame_count,
            "source_id": str(stream.get("source_id", "")),
        })
    return dataset_name, result


def _validate_frozen_cpu_manifest() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "checkpoint_analytics_models_openvino.yaml"
    )
    _require(path.is_file(), "frozen CPU model manifest missing")
    _require(
        _sha256_file(path) == FROZEN_CPU_MANIFEST_SHA256,
        "frozen CPU model manifest SHA-256 drifted",
    )
    with path.open("r", encoding="utf-8") as source:
        document = yaml.safe_load(source)
    _require(isinstance(document, Mapping), "frozen CPU manifest invalid")
    _require(
        document.get("schema_version") == 2
        and document.get("runtime_family") == "openvino_dlstreamer",
        "frozen CPU manifest runtime contract drifted",
    )
    branches = document.get("branches")
    _require(
        isinstance(branches, Mapping)
        and tuple(branches) == ANALYTICS_BRANCHES,
        "frozen CPU manifest branch order drifted",
    )
    for branch, binding in branches.items():
        _require(isinstance(binding, Mapping), f"{branch}: CPU binding invalid")
        _require(
            binding.get("factory") == "gvadetect"
            and binding.get("device") == "CPU"
            and bool(_SHA256_RE.fullmatch(str(binding.get("model_sha256", ""))))
            and bool(_SHA256_RE.fullmatch(str(binding.get("weights_sha256", "")))),
            f"{branch}: frozen manifest must remain verified CPU-only OpenVINO",
        )


def _source_prefix(source: Mapping[str, Any], *, codec: str) -> list[dict[str, Any]]:
    return [
        {
            "factory": "appsrc",
            "role": "protocol_v3_common_admission_access_unit_source",
            "format": "time",
            "default_savant_uri_source_accepted": False,
        },
        {"factory": PARSER_BY_CODEC[codec], "role": "codec_parser", "codec": codec},
        {
            "factory": "nvv4l2decoder",
            "role": "explicit_hardware_decode",
            "execution_resource": "nvdec",
            "gpu_id": 0,
            "cudadec_memtype": "device",
            "software_fallback": "prohibited",
        },
        {
            "factory": "nvstreammux",
            "role": "single_stream_savant_deepstream_batch_meta",
            "batch_size": 1,
            "width": int(source["width"]),
            "height": int(source["height"]),
            "live_source": False,
        },
        {
            "factory": "nvvideoconvert",
            "role": "shared_preprocess",
            "execution_resource": "gpu",
            "device_api": "NVIDIA_CUDA",
            "gpu_id": 0,
        },
    ]


def _analytics_queue(branch: str) -> dict[str, Any]:
    return {
        "factory": "queue",
        "role": "bounded_branch_waiting_queue",
        "branch": branch,
        "max_size_buffers": 1,
        "leaky": "upstream",
        "drop_policy": "drop_newest",
    }


def _policy_dispatch(
    branch: str, *, policy: str, deadline_ms: float,
) -> dict[str, Any]:
    return {
        "factory": "vastsavantpolicydispatch",
        "role": "native_per_frame_policy_dispatch",
        "implementation_status": "missing_not_built",
        "branch": branch,
        "policy": policy,
        "deadline_ms": deadline_ms,
        "transport": POLICY_TRANSPORT,
        "fd_environment": POLICY_RPC_FD_ENV,
        "selected_execution_paths": {
            "cpu": {
                "factory": "vastsavantcpuinfer",
                "implementation_status": "missing_not_built",
                "backend": "openvino_cpu",
                "device": "CPU",
                "model_binding": "frozen_equivalent_model_required",
            },
            "gpu": {
                "factory": "nvinfer",
                "implementation_status": "plugin_present_frozen_model_binding_missing",
                "backend": "deepstream_tensorrt",
                "device": "GPU",
                "device_api": "NVIDIA_CUDA",
                "model_binding": "frozen_equivalent_tensorrt_model_required",
            },
        },
    }


def _terminal(branch: str) -> dict[str, Any]:
    return {
        "factory": "vastsavantbranchterminal",
        "role": "protocol_v3_native_branch_terminal",
        "branch": branch,
        "implementation_status": "missing_not_built",
        "event_provenance_required": "native_runtime_event",
    }


def _config_path(topology: str, stream_id: int, branch: str | None = None) -> str:
    suffix = f"stream-{stream_id}"
    if branch is not None:
        suffix += f"-branch-{branch}"
    return f"/opt/vast/checkpoint/generated/{topology}-{suffix}.yml"


def _baseline_processes(
    sources: Sequence[Mapping[str, Any]], *, codec: str, policy: str,
    deadline_ms: float,
) -> list[dict[str, Any]]:
    processes = []
    for source in sources:
        stream_id = int(source["stream_id"])
        for branch in ANALYTICS_BRANCHES:
            processes.append({
                "process_id": f"savant-stream-{stream_id}-branch-{branch}",
                "process_isolation": "os_process",
                "module_entrypoint": list(SAVANT_ENTRYPOINT),
                "module_config_path": _config_path("baseline", stream_id, branch),
                "module_config_status": "missing_not_built",
                "stream_id": stream_id,
                "branch": branch,
                "branches": [branch],
                "source_process_id": (
                    f"savant-stream-{stream_id}-source-coordinator"
                ),
                "physical_pipeline": _source_prefix(source, codec=codec) + [
                    _analytics_queue(branch),
                    _policy_dispatch(
                        branch, policy=policy, deadline_ms=deadline_ms,
                    ),
                    _terminal(branch),
                    {"factory": "fakesink", "role": "terminal_sink", "sync": False},
                ],
            })
    return processes


def _shared_processes(
    sources: Sequence[Mapping[str, Any]], *, codec: str, policy: str,
    deadline_ms: float,
) -> list[dict[str, Any]]:
    processes = []
    for source in sources:
        stream_id = int(source["stream_id"])
        processes.append({
            "process_id": f"savant-stream-{stream_id}-shared-video-dag",
            "process_isolation": "os_process",
            "module_entrypoint": list(SAVANT_ENTRYPOINT),
            "module_config_path": _config_path("shared", stream_id),
            "module_config_status": "missing_not_built",
            "stream_id": stream_id,
            "branches": list(ANALYTICS_BRANCHES),
            "source_process_id": f"savant-stream-{stream_id}-source-coordinator",
            "shared_prefix": _source_prefix(source, codec=codec) + [
                {"factory": "tee", "role": "physical_shared_fanout"},
            ],
            "routes": [
                {
                    "branch": branch,
                    "elements": [
                        _analytics_queue(branch),
                        _policy_dispatch(
                            branch, policy=policy, deadline_ms=deadline_ms,
                        ),
                        _terminal(branch),
                        {
                            "factory": "fakesink",
                            "role": "terminal_sink",
                            "sync": False,
                        },
                    ],
                }
                for branch in ANALYTICS_BRANCHES
            ],
        })
    return processes


def build_savant_runtime_plan(
    *, config: Mapping[str, Any], datasets: Mapping[str, Any], scenario: str,
    codec: str, policy: str, deadline_ms: Any,
) -> dict[str, Any]:
    """Build one immutable, non-measurement Savant checkpoint plan."""

    topology_kind = _frozen_scenario(config, scenario)
    codec, policy, deadline, warmup_s, measurement_s = _frozen_coordinates(
        config, codec=str(codec), policy=str(policy), deadline_ms=deadline_ms,
    )
    _validate_frozen_cpu_manifest()
    dataset_name, sources = _frozen_sources(datasets, codec=codec)
    if topology_kind == "independent_processes":
        processes = _baseline_processes(
            sources, codec=codec, policy=policy, deadline_ms=deadline,
        )
    else:
        processes = _shared_processes(
            sources, codec=codec, policy=policy, deadline_ms=deadline,
        )
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "artifact_kind": "savant_checkpoint_runtime_plan",
        "claim_status": PLAN_CLAIM_STATUS,
        "system": "savant",
        "image": SAVANT_IMAGE,
        "image_id": SAVANT_IMAGE_ID,
        "image_repo_digest": SAVANT_IMAGE_REPO_DIGEST,
        "savant_version": SAVANT_VERSION,
        "savant_entrypoint": list(SAVANT_ENTRYPOINT),
        "scenario": scenario,
        "topology_kind": topology_kind,
        "codec": codec,
        "parser_factory": PARSER_BY_CODEC[codec],
        "dataset": dataset_name,
        "policy": policy,
        "deadline_ms": deadline,
        "stream_count": 6,
        "queued_branches_per_stream": 4,
        "required_branches": list(ANALYTICS_BRANCHES),
        "warmup_s": warmup_s,
        "measurement_s": measurement_s,
        "runtime_executable": RUNTIME_EXECUTABLE,
        "runtime_implementation_status": (
            "dedicated_runtime_and_module_configs_missing_not_built"
        ),
        "topology_runtime_implemented": False,
        "publication_ready": False,
        "savant_module_binding": {
            "framework_version": SAVANT_VERSION,
            "base_image_entrypoint": list(SAVANT_ENTRYPOINT),
            "dedicated_runtime_wrapper": RUNTIME_EXECUTABLE,
            "generated_module_config_root": "/opt/vast/checkpoint/generated",
            "generated_module_config_status": "missing_not_built",
            "existing_generic_configs_accepted": False,
            "rejected_generic_configs": [
                "deploy/savant/module.yml",
                "deploy/savant/canonical_heterogeneous_module.yml",
                "deploy/savant/canonical_distributed_module.yml",
            ],
            "rejected_generic_reason": (
                "uri_or_jpeg_peoplenet_pyfunc_is_not_frozen_checkpoint_runtime"
            ),
        },
        "source_protocol": (
            "direct_admission_json_v1_with_framed_compressed_access_units"
        ),
        "runtime_event_protocol": (
            "direct_runtime_json_v3_with_native_path_and_terminals_required"
        ),
        "policy_binding": {
            "contract_status": (
                "coordinator_v1_available_savant_native_binding_missing"
            ),
            "rpc_schema_version": POLICY_RPC_SCHEMA_VERSION,
            "transport": POLICY_TRANSPORT,
            "fd_environment": POLICY_RPC_FD_ENV,
            "max_message_bytes": POLICY_RPC_MAX_MESSAGE_BYTES,
            "request_fields": list(POLICY_REQUEST_FIELDS),
            "response_fields": list(POLICY_RESPONSE_FIELDS),
            "path_enter_fields": list(POLICY_PATH_ENTER_FIELDS),
            "terminal_fields": list(POLICY_TERMINAL_FIELDS),
            "request_response_path_terminal_required": True,
            "derived_policy_or_resource_labels_prohibited": True,
            "nvidia_gpu_path_requirements": {
                "factory": "nvinfer",
                "backend": "deepstream_tensorrt",
                "device_api": "NVIDIA_CUDA",
                "native_terminal_verified": True,
                "gvadetect_gpu_label_accepted": False,
            },
        },
        "model_binding": {
            "frozen_cpu_manifest": (
                "configs/checkpoint_analytics_models_openvino.yaml"
            ),
            "frozen_cpu_manifest_sha256": FROZEN_CPU_MANIFEST_SHA256,
            "frozen_cpu_runtime_family": "openvino_dlstreamer",
            "frozen_cpu_device": "CPU",
            "savant_gpu_factory": "nvinfer",
            "savant_gpu_backend": "deepstream_tensorrt",
            "savant_gpu_device_api": "NVIDIA_CUDA",
            "cpu_cuda_parity_status": (
                "missing_equivalent_models_for_all_four_branches"
            ),
            "same_model_semantics_per_cpu_gpu_resource_required": True,
            "peoplenet_sample_model_accepted": False,
            "openvino_gvadetect_gpu_label_accepted": False,
        },
        "admission_binding": {
            "source_event_protocol": "direct_admission_json_v1",
            "source_event_protocol_version": 1,
            "worker_event_protocol": (
                "direct_runtime_json_v3_with_native_terminals"
            ),
            "worker_event_protocol_version": 3,
            "common_source_processes": 6,
            "admission_before_worker_source_read_required": True,
            "default_savant_uri_decode_source_accepted": False,
            "selection_basis": "decode_order_schedule_offset_half_open",
        },
        "terminal_binding": {
            "runtime_protocol_version": 3,
            "required_branches": list(ANALYTICS_BRANCHES),
            "native_branch_outcomes_per_frame": 4,
            "accepted_statuses": ["completed", "dropped", "censored"],
            "telemetry_source": "native",
            "event_provenance": "native_runtime_event",
            "posthoc_or_derived_terminal_events_accepted": False,
        },
        "resource_binding": {
            "resource_contract_version": 2,
            "status": "accepted_native_resource_v2_emitter_missing",
            "selected_resource_source": "native_policy_path_enter_and_terminal",
            "nvdec_factory": "nvv4l2decoder",
            "nvidia_gpu_analytics_factory": "nvinfer",
            "nvidia_gpu_analytics_backend": "deepstream_tensorrt",
            "nvidia_gpu_device_api": "NVIDIA_CUDA",
            "derived_stage_name_resource_labels_accepted": False,
            "generic_probe_resource_labels_accepted": False,
        },
        "pair_schedule_gate": {
            "artifact_kind": "checkpoint_terminal_admission_audit",
            "selection_basis": "decode_order_schedule_offset_half_open",
            "required_rule": (
                "equal_measurement_schedule_fingerprint_sha256"
            ),
            "evaluation_phase": "after_both_arms_before_pair_acceptance",
            "empty_or_incomplete_schedule_accepted": False,
        },
        "sources": sources,
        "source_coordinators": [
            {
                "process_id": (
                    f"savant-stream-{int(source['stream_id'])}-source-coordinator"
                ),
                "stream_id": int(source["stream_id"]),
                "executable": (
                    "/usr/local/bin/vast_savant_checkpoint_source_coordinator"
                ),
                "implementation_status": "missing_not_built",
                "native_source": True,
                "admission_before_worker_read_required": True,
                "source_sha256": str(source["source_sha256"]),
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
    plan["topology_plan_sha256"] = _plan_identity(plan)
    validate_savant_runtime_plan(plan)
    return plan


def _validate_prefix(
    prefix: Any, *, codec: str, label: str, tee_required: bool,
) -> None:
    _require(isinstance(prefix, list), f"{label}: physical prefix must be a list")
    factories = [
        str(value.get("factory", ""))
        for value in prefix if isinstance(value, Mapping)
    ]
    expected = [
        "appsrc", PARSER_BY_CODEC[codec], "nvv4l2decoder",
        "nvstreammux", "nvvideoconvert",
    ]
    if factories[:5] != expected:
        raise SavantRuntimeError(
            f"{label}: prefix must use appsrc/{PARSER_BY_CODEC[codec]}/"
            "nvv4l2decoder/nvstreammux/nvvideoconvert"
        )
    decoder = prefix[2]
    _require(
        decoder.get("execution_resource") == "nvdec"
        and decoder.get("gpu_id") == 0
        and decoder.get("software_fallback") == "prohibited",
        f"{label}: explicit NVDEC placement drifted",
    )
    _require(prefix[3].get("batch_size") == 1, f"{label}: batch size drifted")
    _require(
        prefix[4].get("device_api") == "NVIDIA_CUDA",
        f"{label}: preprocess is not NVIDIA CUDA",
    )
    if tee_required:
        _require(
            factories == expected + ["tee"],
            f"{label}: shared prefix must end in one physical tee",
        )


def _validate_queue(value: Any, *, branch: str, label: str) -> None:
    _require(isinstance(value, Mapping), f"{label}: queue missing")
    _require(
        value.get("factory") == "queue"
        and value.get("branch") == branch
        and value.get("max_size_buffers") == 1
        and value.get("leaky") == "upstream"
        and value.get("drop_policy") == "drop_newest",
        f"{label}: queue contract drifted",
    )


def _validate_dispatch(
    value: Any, *, branch: str, policy: str, deadline_ms: float, label: str,
) -> None:
    _require(isinstance(value, Mapping), f"{label}: policy dispatch missing")
    _require(
        value.get("factory") == "vastsavantpolicydispatch"
        and value.get("branch") == branch
        and value.get("policy") == policy
        and value.get("deadline_ms") == deadline_ms
        and value.get("transport") == POLICY_TRANSPORT
        and value.get("fd_environment") == POLICY_RPC_FD_ENV,
        f"{label}: native policy dispatch drifted",
    )
    paths = value.get("selected_execution_paths")
    _require(
        isinstance(paths, Mapping) and set(paths) == {"cpu", "gpu"},
        f"{label}: CPU/GPU paths incomplete",
    )
    _require(
        paths["cpu"].get("factory") == "vastsavantcpuinfer"
        and paths["cpu"].get("device") == "CPU",
        f"{label}: CPU path drifted",
    )
    _require(
        paths["gpu"].get("factory") == "nvinfer"
        and paths["gpu"].get("backend") == "deepstream_tensorrt"
        and paths["gpu"].get("device") == "GPU"
        and paths["gpu"].get("device_api") == "NVIDIA_CUDA",
        f"{label}: GPU path is not explicit NVIDIA CUDA/TensorRT",
    )


def _validate_module_process(value: Mapping[str, Any], label: str) -> None:
    _require(
        value.get("process_isolation") == "os_process",
        f"{label}: process isolation drifted",
    )
    _require(
        value.get("module_entrypoint") == list(SAVANT_ENTRYPOINT),
        f"{label}: Savant module entrypoint drifted",
    )
    _require(
        str(value.get("module_config_path", "")).startswith(
            "/opt/vast/checkpoint/generated/"
        )
        and value.get("module_config_status") == "missing_not_built",
        f"{label}: dedicated module config contract drifted",
    )


def validate_savant_runtime_plan(plan: Mapping[str, Any]) -> None:
    """Reject topology relabeling, frozen-coordinate drift, or readiness claims."""

    _require(isinstance(plan, Mapping), "Savant runtime plan must be a mapping")
    _exact_fields(plan, _PLAN_FIELDS, "Savant runtime plan")
    _require(plan.get("schema_version") == 1, "Savant plan schema drifted")
    _require(
        plan.get("artifact_kind") == "savant_checkpoint_runtime_plan"
        and plan.get("claim_status") == PLAN_CLAIM_STATUS
        and plan.get("system") == "savant",
        "Savant plan identity drifted",
    )
    _require(
        plan.get("image") == SAVANT_IMAGE
        and plan.get("image_id") == SAVANT_IMAGE_ID
        and plan.get("image_repo_digest") == SAVANT_IMAGE_REPO_DIGEST,
        "Savant immutable image identity drifted",
    )
    _require(
        plan.get("savant_version") == SAVANT_VERSION
        and plan.get("savant_entrypoint") == list(SAVANT_ENTRYPOINT),
        "Savant framework identity drifted",
    )
    scenario = str(plan.get("scenario", ""))
    topology_kind = SCENARIO_TOPOLOGY.get(scenario)
    _require(topology_kind is not None, "Savant scenario drifted")
    _require(
        plan.get("topology_kind") == topology_kind,
        "Savant topology kind drifted",
    )
    codec = str(plan.get("codec", ""))
    _require(codec in DATASET_BY_CODEC, "Savant codec drifted")
    _require(
        plan.get("parser_factory") == PARSER_BY_CODEC[codec]
        and plan.get("dataset") == DATASET_BY_CODEC[codec],
        "Savant dataset/codec binding drifted",
    )
    policy = str(plan.get("policy", ""))
    deadline = _finite_number(plan.get("deadline_ms"), "Savant deadline_ms")
    _require(policy in POLICIES, "Savant policy drifted")
    _require(deadline in FROZEN_DEADLINES_MS, "Savant deadline drifted")
    _require(
        plan.get("stream_count") == 6
        and plan.get("queued_branches_per_stream") == 4
        and tuple(plan.get("required_branches") or ()) == ANALYTICS_BRANCHES,
        "Savant requires six streams and four queued analytics branches",
    )
    _require(
        (plan.get("warmup_s"), plan.get("measurement_s")) == (30, 180),
        "Savant cohort duration drifted",
    )
    executable = str(plan.get("runtime_executable", ""))
    if executable == GENERIC_PROBE_EXECUTABLE:
        raise SavantRuntimeError(
            "generic probe cannot be relabelled as Savant checkpoint runtime"
        )
    _require(executable == RUNTIME_EXECUTABLE, "Savant runtime executable drifted")
    _require(
        plan.get("runtime_implementation_status")
        == "dedicated_runtime_and_module_configs_missing_not_built"
        and plan.get("topology_runtime_implemented") is False
        and plan.get("publication_ready") is False
        and plan.get("accepted_measurement_evidence_emitted") is False,
        "unpiloted Savant runtime must remain blocked",
    )
    _require(tuple(plan.get("blockers") or ()) == BASE_BLOCKERS, "blockers drifted")

    module = plan.get("savant_module_binding")
    _require(isinstance(module, Mapping), "Savant module binding missing")
    _require(
        module.get("framework_version") == SAVANT_VERSION
        and module.get("base_image_entrypoint") == list(SAVANT_ENTRYPOINT)
        and module.get("generated_module_config_status") == "missing_not_built"
        and module.get("existing_generic_configs_accepted") is False,
        "generic Savant module config was promoted",
    )
    binding = plan.get("policy_binding")
    _require(isinstance(binding, Mapping), "Savant policy binding missing")
    _require(
        binding.get("rpc_schema_version") == POLICY_RPC_SCHEMA_VERSION
        and binding.get("transport") == POLICY_TRANSPORT
        and binding.get("fd_environment") == POLICY_RPC_FD_ENV
        and binding.get("max_message_bytes") == POLICY_RPC_MAX_MESSAGE_BYTES,
        "Savant policy transport contract drifted",
    )
    for name, expected in (
        ("request_fields", POLICY_REQUEST_FIELDS),
        ("response_fields", POLICY_RESPONSE_FIELDS),
        ("path_enter_fields", POLICY_PATH_ENTER_FIELDS),
        ("terminal_fields", POLICY_TERMINAL_FIELDS),
    ):
        _require(binding.get(name) == list(expected), f"Savant {name} drifted")
    _require(
        binding.get("request_response_path_terminal_required") is True
        and binding.get("derived_policy_or_resource_labels_prohibited") is True,
        "Savant native policy evidence chain drifted",
    )
    gpu = binding.get("nvidia_gpu_path_requirements")
    _require(isinstance(gpu, Mapping), "Savant NVIDIA GPU requirements missing")
    _require(
        gpu.get("factory") == "nvinfer"
        and gpu.get("backend") == "deepstream_tensorrt"
        and gpu.get("device_api") == "NVIDIA_CUDA"
        and gpu.get("native_terminal_verified") is True
        and gpu.get("gvadetect_gpu_label_accepted") is False,
        "Savant NVIDIA CUDA/TensorRT requirements drifted",
    )
    model = plan.get("model_binding")
    _require(isinstance(model, Mapping), "Savant model binding missing")
    _require(
        model.get("frozen_cpu_device") == "CPU"
        and model.get("frozen_cpu_manifest_sha256")
        == FROZEN_CPU_MANIFEST_SHA256
        and model.get("savant_gpu_factory") == "nvinfer"
        and model.get("savant_gpu_backend") == "deepstream_tensorrt"
        and model.get("savant_gpu_device_api") == "NVIDIA_CUDA"
        and model.get("cpu_cuda_parity_status")
        == "missing_equivalent_models_for_all_four_branches"
        and model.get("peoplenet_sample_model_accepted") is False
        and model.get("openvino_gvadetect_gpu_label_accepted") is False,
        "Savant CPU/CUDA parity contract drifted",
    )
    admission = plan.get("admission_binding")
    _require(isinstance(admission, Mapping), "Savant admission binding missing")
    _require(
        admission.get("source_event_protocol") == "direct_admission_json_v1"
        and admission.get("source_event_protocol_version") == 1
        and admission.get("worker_event_protocol")
        == "direct_runtime_json_v3_with_native_terminals"
        and admission.get("worker_event_protocol_version") == 3
        and admission.get("common_source_processes") == 6
        and admission.get("admission_before_worker_source_read_required") is True
        and admission.get("default_savant_uri_decode_source_accepted") is False
        and admission.get("selection_basis")
        == "decode_order_schedule_offset_half_open",
        "Savant protocol-v3 common admission contract drifted",
    )
    terminal = plan.get("terminal_binding")
    _require(isinstance(terminal, Mapping), "Savant terminal binding missing")
    _require(
        terminal.get("runtime_protocol_version") == 3
        and terminal.get("required_branches") == list(ANALYTICS_BRANCHES)
        and terminal.get("native_branch_outcomes_per_frame") == 4
        and terminal.get("telemetry_source") == "native"
        and terminal.get("event_provenance") == "native_runtime_event"
        and terminal.get("posthoc_or_derived_terminal_events_accepted") is False,
        "Savant protocol-v3 terminal contract drifted",
    )
    resource = plan.get("resource_binding")
    _require(isinstance(resource, Mapping), "Savant resource binding missing")
    _require(
        resource.get("resource_contract_version") == 2
        and resource.get("status") == "accepted_native_resource_v2_emitter_missing"
        and resource.get("selected_resource_source")
        == "native_policy_path_enter_and_terminal"
        and resource.get("nvdec_factory") == "nvv4l2decoder"
        and resource.get("nvidia_gpu_analytics_factory") == "nvinfer"
        and resource.get("nvidia_gpu_analytics_backend")
        == "deepstream_tensorrt"
        and resource.get("nvidia_gpu_device_api") == "NVIDIA_CUDA"
        and resource.get("derived_stage_name_resource_labels_accepted") is False
        and resource.get("generic_probe_resource_labels_accepted") is False,
        "Savant resource-v2 evidence contract drifted",
    )
    _require(
        plan.get("pair_schedule_gate") == {
            "artifact_kind": "checkpoint_terminal_admission_audit",
            "selection_basis": "decode_order_schedule_offset_half_open",
            "required_rule": "equal_measurement_schedule_fingerprint_sha256",
            "evaluation_phase": "after_both_arms_before_pair_acceptance",
            "empty_or_incomplete_schedule_accepted": False,
        },
        "Savant pair schedule gate drifted",
    )

    sources = plan.get("sources")
    _require(
        isinstance(sources, list) and len(sources) == 6,
        "Savant plan requires six sources",
    )
    _require(
        [source.get("stream_id") for source in sources] == list(range(6))
        and all(source.get("source_codec") == codec for source in sources)
        and all(
            bool(_SHA256_RE.fullmatch(str(source.get("source_sha256", ""))))
            for source in sources
        ),
        "Savant source identity/codec drifted",
    )
    coordinators = plan.get("source_coordinators")
    _require(
        isinstance(coordinators, list)
        and len(coordinators) == 6
        and [value.get("stream_id") for value in coordinators] == list(range(6)),
        "Savant source coordinator coverage drifted",
    )
    processes = plan.get("processes")
    _require(isinstance(processes, list), "Savant processes must be a list")
    process_ids = [
        str(value.get("process_id", ""))
        for value in processes if isinstance(value, Mapping)
    ]
    _require(len(process_ids) == len(set(process_ids)), "process IDs duplicated")
    if topology_kind == "independent_processes":
        _require(
            len(processes) == 24,
            "Savant baseline requires twenty-four independent processes",
        )
        expected = {
            (stream_id, branch)
            for stream_id in range(6) for branch in ANALYTICS_BRANCHES
        }
        actual = {
            (value.get("stream_id"), value.get("branch"))
            for value in processes if isinstance(value, Mapping)
        }
        _require(actual == expected, "Savant baseline process coverage drifted")
        for process in processes:
            _require(isinstance(process, Mapping), "invalid baseline process")
            label, branch = str(process.get("process_id")), str(process.get("branch"))
            _validate_module_process(process, label)
            _require(
                process.get("branches") == [branch],
                f"{label}: branch isolation drifted",
            )
            pipeline = process.get("physical_pipeline")
            _validate_prefix(
                pipeline, codec=codec, label=label, tee_required=False,
            )
            _require(
                isinstance(pipeline, list) and len(pipeline) == 9,
                f"{label}: physical pipeline drifted",
            )
            _validate_queue(pipeline[5], branch=branch, label=label)
            _validate_dispatch(
                pipeline[6], branch=branch, policy=policy,
                deadline_ms=deadline, label=label,
            )
            _require(
                pipeline[7].get("factory") == "vastsavantbranchterminal"
                and pipeline[7].get("branch") == branch,
                f"{label}: native branch terminal missing",
            )
    else:
        _require(
            len(processes) == 6,
            "Savant shared topology requires six shared processes",
        )
        _require(
            {
                value.get("stream_id")
                for value in processes if isinstance(value, Mapping)
            } == set(range(6)),
            "Savant shared process coverage drifted",
        )
        for process in processes:
            _require(isinstance(process, Mapping), "invalid shared process")
            label = str(process.get("process_id"))
            _validate_module_process(process, label)
            _require(
                tuple(process.get("branches") or ()) == ANALYTICS_BRANCHES,
                f"{label}: branch set drifted",
            )
            _validate_prefix(
                process.get("shared_prefix"), codec=codec, label=label,
                tee_required=True,
            )
            routes = process.get("routes")
            _require(
                isinstance(routes, list) and len(routes) == 4,
                f"{label}: four routes required",
            )
            _require(
                {
                    route.get("branch")
                    for route in routes if isinstance(route, Mapping)
                } == set(ANALYTICS_BRANCHES),
                f"{label}: route coverage drifted",
            )
            for route in routes:
                _require(isinstance(route, Mapping), f"{label}: invalid route")
                branch = str(route.get("branch"))
                elements = route.get("elements")
                _require(
                    isinstance(elements, list) and len(elements) == 4,
                    f"{label}/{branch}: route elements or queue drifted",
                )
                _validate_queue(
                    elements[0], branch=branch, label=f"{label}/{branch}",
                )
                _validate_dispatch(
                    elements[1], branch=branch, policy=policy,
                    deadline_ms=deadline, label=f"{label}/{branch}",
                )
                _require(
                    elements[2].get("factory") == "vastsavantbranchterminal"
                    and elements[2].get("branch") == branch,
                    f"{label}/{branch}: native branch terminal missing",
                )
    identity = str(plan.get("topology_plan_sha256", ""))
    _require(
        bool(_SHA256_RE.fullmatch(identity))
        and identity == _plan_identity(plan),
        "Savant topology plan identity mismatch",
    )


def parse_probe_payload(text: str) -> dict[str, Any]:
    """Parse capability JSON without allowing accepted-evidence claims."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SavantRuntimeError("Savant capability probe returned non-JSON") from exc
    _require(isinstance(raw, Mapping), "Savant probe must be a JSON object")
    payload = copy.deepcopy(dict(raw))
    _exact_fields(payload, _PROBE_FIELDS, "Savant capability probe")
    _require(
        payload.get("schema_version") == PROBE_SCHEMA_VERSION
        and payload.get("artifact_kind") == "savant_checkpoint_capability_probe"
        and payload.get("claim_status") == PROBE_CLAIM_STATUS
        and payload.get("system") == "savant",
        "Savant probe identity drifted",
    )
    _require(
        payload.get("image") == SAVANT_IMAGE
        and payload.get("image_id") == SAVANT_IMAGE_ID
        and payload.get("image_repo_digest") == SAVANT_IMAGE_REPO_DIGEST,
        "Savant probe immutable image identity drifted",
    )
    _require(
        payload.get("savant_version") == SAVANT_VERSION,
        "Savant version probe drifted",
    )
    _require(
        str(payload.get("savant_import_path", "")).endswith(
            "/savant/__init__.py"
        )
        and payload.get("savant_entrypoint") == list(SAVANT_ENTRYPOINT),
        "Savant import/entrypoint probe drifted",
    )
    _require(
        str(payload.get("deepstream_sdk_version", "")).startswith("7.0."),
        "Savant probe requires DeepStream SDK 7.0",
    )
    gpu = payload.get("gpu")
    _require(isinstance(gpu, Mapping), "Savant GPU record missing")
    _exact_fields(
        gpu, {"name", "uuid", "driver_version", "visible"}, "Savant GPU",
    )
    _require(type(gpu.get("visible")) is bool, "GPU visibility must be boolean")
    _require(
        all(type(gpu.get(name)) is str for name in ("name", "uuid", "driver_version")),
        "Savant GPU identity fields invalid",
    )
    elements = payload.get("required_elements")
    _require(isinstance(elements, Mapping), "Savant element records missing")
    _require(set(elements) == set(REQUIRED_ELEMENTS), "element set drifted")
    for name, value in elements.items():
        _require(isinstance(value, Mapping), f"invalid element record: {name}")
        _exact_fields(
            value, {"available", "plugin_filename", "plugin_version"},
            f"Savant element {name}",
        )
        _require(
            type(value.get("available")) is bool
            and type(value.get("plugin_filename")) is str
            and type(value.get("plugin_version")) is str,
            f"Savant element {name} field types drifted",
        )
    decoders = payload.get("decoder_probes")
    _require(
        isinstance(decoders, Mapping) and set(decoders) == {"h264", "h265"},
        "Savant decoder probe set drifted",
    )
    decoder_fields = {
        "passed", "decoder_factory", "parser_factory", "gpu_id",
        "decoded_buffers", "source_sha256", "pipeline_status", "output_caps",
        "buffer_evidence",
    }
    for codec, value in decoders.items():
        _require(isinstance(value, Mapping), f"invalid {codec} decoder probe")
        _exact_fields(value, decoder_fields, f"Savant {codec} decoder probe")
        _require(type(value.get("passed")) is bool, f"{codec} passed invalid")
        _require(
            value.get("decoder_factory") == "nvv4l2decoder",
            f"Savant {codec} probe relabelled the hardware decoder",
        )
        _require(
            value.get("parser_factory") == PARSER_BY_CODEC[codec]
            and type(value.get("gpu_id")) is int
            and value.get("gpu_id") == 0,
            f"Savant {codec} parser/GPU placement drifted",
        )
        _require(
            type(value.get("decoded_buffers")) is int
            and value.get("decoded_buffers") in {0, 1}
            and bool(_SHA256_RE.fullmatch(str(value.get("source_sha256", "")))),
            f"Savant {codec} decoder evidence invalid",
        )
        _require(
            type(value.get("pipeline_status")) is str
            and type(value.get("output_caps")) is str
            and type(value.get("buffer_evidence")) is str,
            f"Savant {codec} buffer evidence field types drifted",
        )
        if value["passed"]:
            _require(
                value["decoded_buffers"] == 1
                and value["pipeline_status"] == "sample_observed"
                and value["buffer_evidence"] == "appsink_sample"
                and "video/x-raw(memory:NVMM)" in value["output_caps"]
                and "gpu-id=(int)0" in value["output_caps"],
                f"Savant {codec} passing probe lacks an explicit appsink "
                "NVIDIA NVMM buffer",
            )
        elif value["decoded_buffers"] == 0:
            _require(
                value["pipeline_status"] in {
                    "eos_without_buffer", "timeout_without_buffer", "error",
                }
                and value["output_caps"] == ""
                and value["buffer_evidence"] == "no_decoded_sample",
                f"Savant {codec} failed probe evidence drifted",
            )
        else:
            _require(
                value["pipeline_status"] == "sample_wrong_caps"
                and value["buffer_evidence"] == "appsink_sample"
                and bool(value["output_caps"]),
                f"Savant {codec} non-NVMM sample evidence drifted",
            )
    for name in (
        "dedicated_checkpoint_runtime_present",
        "protocol_v3_policy_adapter_present",
        "resource_v2_emitter_present",
    ):
        _require(type(payload.get(name)) is bool, f"{name} must be boolean")
        _require(
            payload[name] is False,
            f"unreviewed {name} cannot be promoted by capability schema v1",
        )
    _require(
        payload.get("generic_probe_executed") is False,
        "generic probe must not be executed or relabelled",
    )
    _require(
        payload.get("accepted_measurement_evidence_emitted") is False,
        "Savant capability probe must not emit measurement evidence",
    )
    _require(
        payload.get("publication_ready") is False,
        "Savant capability probe publication_ready must remain false",
    )
    return payload


def assess_savant_runtime_readiness(
    plan: Mapping[str, Any], probe: Mapping[str, Any],
) -> dict[str, Any]:
    """Report blockers; a capability probe can never accept a benchmark arm."""

    validate_savant_runtime_plan(plan)
    validated = parse_probe_payload(_canonical_json(probe).decode("utf-8"))
    blockers = list(BASE_BLOCKERS)
    if validated["gpu"]["visible"] is not True:
        blockers.append("savant_nvidia_gpu_not_visible")
    for name, value in validated["required_elements"].items():
        if value["available"] is not True:
            blockers.append(f"savant_gstreamer_element_missing:{name}")
    decoder_support = {}
    for codec in ("h264", "h265"):
        passed = validated["decoder_probes"][codec]["passed"] is True
        decoder_support[codec] = passed
        if not passed:
            blockers.append(f"savant_{codec}_nvdec_probe_failed")
    blockers = list(dict.fromkeys(blockers))
    dynamic = {
        "savant_nvidia_gpu_not_visible",
        "savant_h264_nvdec_probe_failed",
        "savant_h265_nvdec_probe_failed",
    }
    sdk_passed = not any(
        blocker in dynamic
        or blocker.startswith("savant_gstreamer_element_missing:")
        for blocker in blockers
    )
    cuda_capability = (
        validated["gpu"]["visible"] is True
        and validated["required_elements"]["nvinfer"]["available"] is True
    )
    return {
        "schema_version": ASSESSMENT_SCHEMA_VERSION,
        "artifact_kind": "savant_checkpoint_runtime_readiness",
        "passed": False,
        "status": "blocked",
        "topology_runtime_implemented": False,
        "publication_ready": False,
        "scenario": plan["scenario"],
        "codec": plan["codec"],
        "policy": plan["policy"],
        "deadline_ms": plan["deadline_ms"],
        "savant_version": validated["savant_version"],
        "savant_sdk_probe_passed": sdk_passed,
        "cuda_tensorrt_capability_detected": cuda_capability,
        "frozen_cpu_cuda_parity_ready": False,
        "hardware_decoder_support": decoder_support,
        "probe_sha256": hashlib.sha256(_canonical_json(validated)).hexdigest(),
        "topology_plan_sha256": plan["topology_plan_sha256"],
        "blockers": blockers,
    }


def build_probe_command(
    project_root: Path, *, image: str = SAVANT_IMAGE,
    image_id: str = SAVANT_IMAGE_ID, docker_binary: str = "docker",
) -> list[str]:
    """Return an argument-safe command with only two read-only input mounts."""

    _require(image == SAVANT_IMAGE, "Savant probe image is not frozen")
    _require(image_id == SAVANT_IMAGE_ID, "immutable image ID drifted")
    root = Path(project_root).resolve()
    probe_dir = root / "deploy" / "savant" / "checkpoint"
    data_dir = root / "data" / "videos" / "kpp"
    probe_script = probe_dir / "savant_checkpoint_capability_probe.py"
    _require(probe_script.is_file(), f"probe script missing: {probe_script}")
    for codec in ("h264", "h265"):
        _require(
            (data_dir / codec / "1.mp4").is_file(),
            f"Savant {codec} probe source missing",
        )
    return [
        docker_binary, "run", "--rm", "--gpus", "all",
        "--entrypoint", "python3",
        "--mount",
        f"type=bind,source={probe_dir},target=/opt/vast/checkpoint,readonly",
        "--mount",
        f"type=bind,source={data_dir},target=/opt/vast/kpp,readonly",
        "-e", f"VAST_SAVANT_IMAGE={image}",
        "-e", f"VAST_SAVANT_IMAGE_ID={image_id}",
        "-e", f"VAST_SAVANT_IMAGE_REPO_DIGEST={SAVANT_IMAGE_REPO_DIGEST}",
        "-e",
        f"VAST_H264_SOURCE_SHA256={_sha256_file(data_dir / 'h264' / '1.mp4')}",
        "-e",
        f"VAST_H265_SOURCE_SHA256={_sha256_file(data_dir / 'h265' / '1.mp4')}",
        image,
        "/opt/vast/checkpoint/savant_checkpoint_capability_probe.py",
    ]


def run_capability_probe(
    project_root: Path, *, image: str = SAVANT_IMAGE,
    docker_binary: str = "docker", timeout_s: float = 90.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Run only image/import/plugin/one-buffer checks, never a benchmark arm."""

    _require(image == SAVANT_IMAGE, "Savant probe image is not frozen")
    inspected = runner(
        [docker_binary, "image", "inspect", image],
        check=False, capture_output=True, text=True, timeout=timeout_s,
    )
    if inspected.returncode != 0:
        raise SavantRuntimeError("Savant Docker image inspection failed")
    try:
        document = json.loads(inspected.stdout)
    except json.JSONDecodeError as exc:
        raise SavantRuntimeError("Docker image inspect returned non-JSON") from exc
    _require(
        isinstance(document, list) and len(document) == 1
        and isinstance(document[0], Mapping),
        "Docker image inspection shape drifted",
    )
    record = document[0]
    _require(record.get("Id") == SAVANT_IMAGE_ID, "immutable image ID mismatch")
    _require(
        isinstance(record.get("RepoDigests"), list)
        and SAVANT_IMAGE_REPO_DIGEST in record["RepoDigests"],
        "immutable repo digest mismatch",
    )
    config = record.get("Config")
    _require(
        isinstance(config, Mapping)
        and config.get("Entrypoint") == list(SAVANT_ENTRYPOINT),
        "Savant image entrypoint mismatch",
    )
    completed = runner(
        build_probe_command(
            project_root, image=image, docker_binary=docker_binary,
        ),
        check=False, capture_output=True, text=True, timeout=timeout_s,
    )
    if completed.returncode != 0:
        raise SavantRuntimeError(
            f"Savant capability probe failed: exit {completed.returncode}"
        )
    return parse_probe_payload(completed.stdout)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    _require(isinstance(value, Mapping), f"{path}: expected YAML mapping")
    return dict(value)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build/probe fail-closed Savant checkpoint topology."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument(
        "--config", type=Path, default=Path("configs/experiments.yaml"),
    )
    plan_parser.add_argument(
        "--datasets", type=Path, default=Path("configs/datasets.yaml"),
    )
    plan_parser.add_argument(
        "--scenario", choices=tuple(SCENARIO_TOPOLOGY), required=True,
    )
    plan_parser.add_argument(
        "--codec", choices=tuple(DATASET_BY_CODEC), required=True,
    )
    plan_parser.add_argument("--policy", choices=POLICIES, required=True)
    plan_parser.add_argument("--deadline-ms", type=float, required=True)

    probe_parser = commands.add_parser("probe")
    probe_parser.add_argument(
        "--project-root", type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    probe_parser.add_argument("--image", default=SAVANT_IMAGE)

    assess_parser = commands.add_parser("assess")
    assess_parser.add_argument(
        "--config", type=Path, default=Path("configs/experiments.yaml"),
    )
    assess_parser.add_argument(
        "--datasets", type=Path, default=Path("configs/datasets.yaml"),
    )
    assess_parser.add_argument("--probe", type=Path, required=True)
    assess_parser.add_argument(
        "--scenario", choices=tuple(SCENARIO_TOPOLOGY), required=True,
    )
    assess_parser.add_argument(
        "--codec", choices=tuple(DATASET_BY_CODEC), required=True,
    )
    assess_parser.add_argument("--policy", choices=POLICIES, required=True)
    assess_parser.add_argument("--deadline-ms", type=float, required=True)
    args = parser.parse_args()
    if args.command == "probe":
        _print_json(run_capability_probe(args.project_root, image=args.image))
        return 0
    config = _load_yaml(args.config)
    datasets_document = _load_yaml(args.datasets)
    datasets = datasets_document.get("datasets")
    _require(isinstance(datasets, Mapping), "datasets document missing datasets")
    plan = build_savant_runtime_plan(
        config=config, datasets=datasets, scenario=args.scenario,
        codec=args.codec, policy=args.policy, deadline_ms=args.deadline_ms,
    )
    if args.command == "plan":
        _print_json(plan)
        return 0
    probe = parse_probe_payload(args.probe.read_text(encoding="utf-8"))
    _print_json(assess_savant_runtime_readiness(plan, probe))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
