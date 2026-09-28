#!/usr/bin/env python3
"""Hermetic, read-only validation of one arbitrary-Q4 native evidence cell.

The module has no third-party dependencies and performs no execution, network
access, filesystem mutation, acceptance publication, or grant issuance.  It
validates one formally pinned replay request, its raw-evidence manifest, the
bound runtime-v4 contract, and the exact legacy or projected native evidence set.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 4
RAW_EVIDENCE_MANIFEST_KIND = "vast_publication_q4_raw_evidence_manifest_v4"
VALIDATION_RESULT_KIND = "vast_publication_q4_evidence_validation_result_v4"
VALIDATION_REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RUNTIME_CONTRACT_KIND = "vast_publication_runtime_contract_v4"
NATIVE_GRAPH_KIND = "vast_publication_native_runtime_graph_contract_v4"
RUNTIME_AUTHORITY_KIND = "vast_backend_publication_runtime_authority_v2"
RUNNER_AUTHORITY_KIND = "vast_backend_runtime_validation_runner_authority"
VALIDATOR_AUTHORITY_KIND = "vast_backend_runtime_validator_authority_q4"
CONTEXT_KIND = "vast_backend_runtime_validation_system_context_v2"
Q4_INPUT_KIND = "vast_backend_runtime_qualification_v4_input_index"
PUBLICATION_LAUNCHER_INVOCATION_KIND = (
    "vast_backend_publication_launcher_invocation_v3"
)
LAUNCHER_RUNTIME_AUTHORITY_KIND = (
    "vast_backend_publication_launcher_runtime_authority"
)

SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS: tuple[int | float, ...] = (16.7, 33.3, 50, 100, 500)
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
DURATION_S = 180
WARMUP_S = 30
STREAMS = 6
BASE_SEED = 20260323
SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}

BASE_EVIDENCE_FILES = (
    "frames.csv", "frame_events.csv", "resource_events.csv",
    "policy_decisions.csv", "drop_counters.csv", "topology_events.csv",
    "ingress_ledger.csv", "branch_terminals.csv", "stage_contracts.csv",
    "reset_evidence.csv",
)
POLICY_DECISIONS_JSONL = "publication_policy_decisions.jsonl"
POLICY_FEEDBACK_JSONL = "publication_policy_feedback.jsonl"
POLICY_RUNTIME_HISTORY_JSONL = "publication_policy_runtime_history.jsonl"
FULL_RESOURCE_FILES = (
    "resource_intervals.csv", "hardware_resource_samples.csv",
    "fanout_work_counters.csv",
)
CANDIDATE_FILENAME = "checkpoint_publication_candidate.json"

FRAME_COLUMNS = (
    "schema_version", "run_id", "trace_id", "stream_id", "frame_id",
    "ingress_timestamp_ms", "egress_timestamp_ms", "e2e_latency_ms",
    "objects", "detector", "backend", "telemetry_source",
)
FRAME_EVENT_COLUMNS = (
    "schema_version", "run_id", "trace_id", "stream_id", "frame_id",
    "stage", "role", "host", "resource", "queue_enter_timestamp_ms",
    "stage_start_timestamp_ms", "stage_end_timestamp_ms", "queue_depth",
    "estimated_cost_ms", "policy_action",
)
RESOURCE_EVENT_COLUMNS = (
    "schema_version", "run_id", "trace_id", "stream_id", "frame_id",
    "stage", "resource", "timestamp_ms", "cpu_time_ms", "gpu_time_ms",
    "h2d_bytes", "d2h_bytes", "nvdec_util_percent", "vram_mb",
    "time_provenance", "transfer_provenance", "nvdec_provenance",
    "vram_provenance", "telemetry_source",
)
POLICY_DECISION_COLUMNS = (
    "schema_version", "run_id", "trace_id", "stream_id", "frame_id",
    "stage", "policy", "decision", "resource", "queue_depth",
    "estimated_cost_ms", "deadline_ms", "policy_version",
    "allowed_resources_json", "alternative_scores_json",
    "cost_components_json", "parameters_json", "tie_break_rule",
    "decision_mode", "update_seq", "update_json", "reason", "decision_id",
    "decision_seq", "decision_timestamp_ms", "graph_version",
    "profile_version", "feature_provenance_json", "terminal_status",
    "terminal_timestamp_ms", "update_timestamp_ms",
    "source_decision_ids_json", "first_consumer_decision_id",
    "first_consumer_decision_seq", "causal_trace_completeness",
    "decision_provenance", "trace_completeness", "telemetry_source",
)
DROP_COUNTER_COLUMNS = (
    "schema_version", "run_id", "stream_id", "camera_role",
    "dropped_frames", "late_frames", "total_frames", "deadline_ms",
    "drop_rate_percent", "late_rate_percent", "reason", "drop_provenance",
    "late_provenance", "telemetry_source",
)
INGRESS_LEDGER_COLUMNS = (
    "schema_version", "run_id", "cohort_id", "trace_id", "input_frame_key",
    "admission_seq", "source_sha256", "source_cycle", "access_unit_pts_ns",
    "payload_sha256", "payload_size_bytes", "schedule_offset_ns",
    "stream_id", "frame_id", "ingress_timestamp_ms",
    "window_start_timestamp_ms", "window_end_timestamp_ms", "terminal_status",
    "terminal_timestamp_ms", "drain_end_timestamp_ms", "terminal_reason",
    "censoring_rule", "ingress_provenance", "terminal_provenance",
    "telemetry_source",
)
BRANCH_TERMINAL_COLUMNS = (
    "schema_version", "run_id", "cohort_id", "trace_id", "input_frame_key",
    "stream_id", "frame_id", "branch_id", "terminal_status",
    "terminal_timestamp_ms", "objects", "detector", "backend",
    "terminal_reason", "terminal_provenance", "telemetry_source",
)
STAGE_CONTRACT_COLUMNS = (
    "schema_version", "semantic_contract_version", "run_id", "contract_id",
    "execution_domain", "stage", "base_stage", "implementation_name",
    "implementation_version", "implementation_config_json", "config_sha256",
    "implementation_artifacts_json", "implementation_artifacts_sha256",
    "implementation_artifact_provenance", "transform_json",
    "output_media_type", "output_format", "output_dtype", "output_shape_json",
    "ordering_contract", "contract_provenance", "telemetry_source",
)
RESET_EVIDENCE_COLUMNS = (
    "schema_version", "reset_contract_version", "run_id", "cohort_id",
    "process_instance_id", "process_role", "stream_id", "branch_id",
    "observed_pid", "process_start_token", "ready_timestamp_ns",
    "analytics_queue_depths_json", "source_cycle_first", "admission_seq_first",
    "telemetry_sink_id", "telemetry_sink_preexisting_entry_count",
    "warmup_included_in_measurement", "admission_stopped_before_drain",
    "terminal_state", "reset_provenance", "telemetry_source",
)
TOPOLOGY_EVENT_COLUMNS = (
    "schema_version", "run_id", "trace_id", "stream_id", "frame_id",
    "input_frame_key", "topology_kind", "event_kind", "stage", "branch_id",
    "execution_id", "parent_execution_ids_json", "execution_domain",
    "timestamp_ms", "event_provenance", "telemetry_source",
)
RESOURCE_INTERVAL_COLUMNS = (
    "schema_version", "interval_contract_version", "run_id", "trace_id",
    "stream_id", "frame_id", "input_frame_key", "component", "direction",
    "stage", "branch_id", "execution_id", "host_start_timestamp_ns",
    "host_end_timestamp_ns", "duration_ns", "bytes", "device_id",
    "counter_scope", "native_event_id", "duration_provenance",
    "telemetry_source",
)
HARDWARE_RESOURCE_SAMPLE_COLUMNS = (
    "schema_version", "resource_contract_version", "run_id", "sample_seq",
    "timestamp_ns", "sample_period_us", "device_id", "nvdec_util_percent",
    "gpu_util_percent", "memory_util_percent", "vram_used_bytes",
    "counter_scope", "sample_provenance", "telemetry_source",
)
FANOUT_WORK_COUNTER_COLUMNS = (
    "schema_version", "resource_contract_version", "run_id", "trace_id",
    "stream_id", "frame_id", "input_frame_key", "branch_id", "execution_id",
    "thread_cpu_time_ns", "work_units", "device_id", "counter_scope",
    "counter_provenance", "telemetry_source",
)

QUALIFIED_REPLAY_RESULT = {
    "record_status": "qualified", "accepted": True, "synthetic": False,
    "nonpublication": False, "publication_capable": True,
    "deterministic_replay_completed": True, "blocker_codes": [],
}

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_DEVICE_RE = re.compile(r"[a-z][a-z0-9_.:-]*\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_COORDINATE_FIELDS = frozenset(
    {"system", "codec", "topology_kind", "policy", "deadline_ms", "cell_index"}
)
_MANIFEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "coordinate", "run_id", "duration_s",
    "runtime_contract", "runtime_contract_sha256",
    "native_graph_contract_sha256", "runtime_authority_sha256",
    "evidence_files", "evidence_file_set_sha256",
    "raw_evidence_manifest_sha256",
})
_UPSTREAM_IDENTITY_FIELDS = frozenset({
    "dataset_manifest_sha256", "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
})
_RUNTIME_INPUT_FIELDS = frozenset({
    "system", "scenario", "topology_kind", "codec", "policy",
    "deadline_ms", "duration_s", "warmup_s", "streams", "base_seed",
    "run_id", "dataset",
})
_RUNTIME_CONTRACT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "coordinate", "run_id", "duration_s",
    "authority_snapshot_sha256", "dataset_binding_sha256", "runtime_inputs",
    "native_graph_contract", "contract_sha256",
})
_NATIVE_GRAPH_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authorization_eligible",
    "execution_authorized", "coordinate", "run_id", "duration_s",
    "authority_snapshot_sha256", "dataset_binding_sha256",
    "upstream_identities", "runtime_authority_ref",
    "runtime_authority_sha256", "runtime_authority_set_sha256",
    "runtime_binding_identity_v4_sha256", "launcher_runtime_authority_ref",
    "launcher_runtime_authority_sha256",
    "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256",
    "q4_validator_authority_ref", "q4_validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "runner_invocation_identity_sha256", "runtime_inputs_sha256",
    "launcher_evidence_files", "graph_contract_sha256",
})
_RUNTIME_INPUT_KEY_BY_SYSTEM = {
    "deepstream": "deepstream_publication_runtime_v3",
    "savant": "savant_publication_runtime_v3",
    "openvino_gva": "openvino_gva_publication_runtime_v3",
    "gstreamer_custom": "gstreamer_custom_publication_runtime_v3",
}
_RUNTIME_INPUT_KIND_BY_SYSTEM = {
    "deepstream": "vast_deepstream_publication_runtime_inputs_v3",
    "savant": "vast_savant_publication_runtime_inputs_v3",
    "openvino_gva": "vast_openvino_gva_publication_runtime_inputs_v3",
    "gstreamer_custom": "vast_gstreamer_custom_publication_runtime_inputs_v3",
}
_BASE_CONTAINER_RUNTIME_FIELDS = frozenset({
    "schema_version", "artifact_kind", "files", "source_files",
    "model_files", "support_files", "static_hybrid_map", "container_image",
    "container_engine_socket", "endpoint_sockets", "scratch_root",
    "ready_timeout_s", "drain_timeout_s", "start_lead_ms",
    "container_timeout_s", "defer_full_resource_acceptance",
    "evidence_mapping",
})
_RUNTIME_TEMPLATE_FIELDS_BY_SYSTEM = {
    "deepstream": _BASE_CONTAINER_RUNTIME_FIELDS,
    "savant": _BASE_CONTAINER_RUNTIME_FIELDS,
    "openvino_gva": frozenset({
        "schema_version", "artifact_kind", "files", "runtime_files",
        "source_files", "model_files", "support_files", "static_hybrid_map",
        "container_image", "embedded_artifacts", "container_engine_socket",
        "endpoint_sockets", "device_binding", "detect_bin",
        "preprocessing_contract_sha256", "analytics_queue_max_buffers",
        "scratch_root", "ready_timeout_s", "drain_timeout_s",
        "start_lead_ms", "container_timeout_s",
        "defer_full_resource_acceptance", "evidence_mapping",
    }),
    "gstreamer_custom": frozenset({
        "schema_version", "artifact_kind", "files", "source_files",
        "model_files", "support_files", "static_hybrid_map", "container_image",
        "embedded_artifacts", "container_engine_socket", "endpoint_sockets",
        "device_binding", "preprocessing_contract_sha256", "detect_bin",
        "analytics_queue_max_buffers", "drain_timeout_s", "ready_timeout_s",
        "start_lead_ms", "container_timeout_s", "scratch_root",
        "defer_full_resource_acceptance", "evidence_mapping",
    }),
}
_RESULT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "coordinate",
    "request_sha256", "raw_evidence_manifest_sha256", "replay_result",
    "result_sha256",
})
_REQUEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", *_COORDINATE_FIELDS,
    "context_ref", "context_sha256", "runtime_authority_ref",
    "runtime_authority_sha256", "raw_evidence_ref",
    "q4_input_ref", "q4_input_sha256",
    "q4_validator_authority_ref", "q4_validator_authority_sha256",
    "runner_authority_ref", "runner_authority_sha256",
    "publication_launcher_invocation_v3_ref",
    "publication_launcher_invocation_v3_sha256",
    "runner_invocation_identity_sha256",
    "runtime_binding_identity_v4_sha256", "runtime_authority_set_sha256",
    "launcher_runtime_authority_ref", "launcher_runtime_authority_sha256",
    "request_sha256",
})
_CANDIDATE_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "run_id", "system",
    "scenario", "codec", "policy", "deadline_ms",
    "execution_binding_provenance", "topology_kind", "cohort_id",
    "measurement_schedule_fingerprint_sha256", "completed_frames_by_stream",
    "summary", "evidence_sha256", "pending_full_resource_evidence",
})
_CANDIDATE_SUMMARY_GATES = (
    "ingress_ledger_complete",
    "ingress_cohort_closed",
    "branch_terminal_trace_complete",
    "checkpoint_frame_aggregation_complete",
    "stage_semantic_contract_complete",
    "decoder_placement_verified",
    "resource_attribution_complete",
    "reset_state_verified",
)
_DECISION_RECORD_FIELDS = frozenset({
    "schema_version", "artifact_kind", "policy_contract_sha256",
    "engine_implementation_id", "policy_scope", "policy", "system",
    "arm_id", "decision_id", "decision_seq", "trace_id", "branch",
    "request", "state_before", "static_hybrid_map_sha256",
    "static_hybrid_placement", "evaluations", "selected_resource",
    "selected_implementation_id", "reason", "record_status",
    "native_decision_evidence", "sha256",
})
_DECISION_REQUEST_FIELDS = frozenset({
    "decision_id", "decision_seq", "trace_id", "branch", "arrival_ms",
    "decision_time_ms", "deadline_ms", "rank_u_ms", "candidates",
})
_DECISION_CANDIDATE_FIELDS = frozenset({
    "allowed", "implementation_id", "available_ms", "queue_depth",
    "estimated_service_ms", "transfer_ms",
})
_EVALUATION_BASE_FIELDS = frozenset({
    "allowed", "implementation_id", "available_ms", "queue_depth",
    "estimated_service_ms", "transfer_ms", "predicted_start_ms",
    "predicted_finish_ms", "predicted_lateness_ms",
})
_NATIVE_DECISION_EVIDENCE_FIELDS = frozenset({
    "event_id", "decision_id", "system", "branch", "selected_resource",
    "implementation_id", "emitter_id", "emitter_sha256",
    "telemetry_source", "path_entry_timestamp_ms", "terminal_status",
    "terminal_timestamp_ms", "actual_service_ms", "detector", "backend",
    "worker_id", "input_frame_key", "transport_pts_ns",
})
_FEEDBACK_RECORD_FIELDS = frozenset({
    "schema_version", "artifact_kind", "policy_contract_sha256",
    "engine_implementation_id", "policy", "system", "arm_id",
    "decision_id", "actual_service_ms", "completed_at_ms", "deadline_ms",
    "outcome", "state_before", "state_after", "sha256",
})
_PROJECTION_FIELDS = frozenset({
    "schema_version", "original_worker_trace_id", "original_runtime_decision_seq",
    "issued_record_sha256", "accepted_record_sha256",
})
_HISTORY_HEADER_FIELDS = frozenset({
    "schema_version", "artifact_kind", "record_kind", "run_id", "arm_id",
    "system", "policy", "policy_contract_sha256", "engine_implementation_id",
    "initial_state", "runtime_decision_count", "runtime_feedback_count",
    "measurement_decision_count", "measurement_feedback_count", "event_count", "sha256",
})
_HISTORY_DECISION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "event_seq", "event_type",
    "runtime_decision_seq", "decision_id", "measurement", "issued_record_sha256",
    "accepted_record_sha256", "accepted_record", "sha256",
})
_HISTORY_FEEDBACK_FIELDS = frozenset({
    "schema_version", "artifact_kind", "event_seq", "event_type",
    "runtime_feedback_seq", "decision_id", "measurement", "issued_record_sha256",
    "feedback_record_sha256", "feedback_record", "sha256",
})
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_MAX_JSON_BYTES = 32 * 1024 * 1024
_MAX_EVIDENCE_FILE_BYTES = 8 * 1024 * 1024 * 1024
_MAX_TOTAL_EVIDENCE_BYTES = 64 * 1024 * 1024 * 1024
_MAX_ROWS = 10_000_000
_MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024
_MAX_HISTORY_BYTES = 64 * 1024 * 1024
_MAX_HISTORY_LINE_BYTES = 256 * 1024
_MAX_HISTORY_EVENTS = 1_000_000


class PublicationQ4EvidenceV4Error(ValueError):
    """One Q4 evidence identity or native semantic linkage failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4EvidenceV4Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None, depth: int = 0) -> None:
    _require(depth <= 64, "Q4 evidence JSON nesting is excessive")
    if active is None:
        active = set()
    kind = type(value)
    if value is None or kind in {str, bool, int}:
        return
    if kind is float:
        _require(math.isfinite(value), "Q4 evidence JSON has a non-finite number")
        return
    _require(kind in {dict, list}, "Q4 evidence contains a non-JSON type")
    identity = id(value)
    _require(identity not in active, "Q4 evidence JSON contains a cycle")
    active.add(identity)
    try:
        values = value.values() if kind is dict else value
        if kind is dict:
            _require(all(type(key) is str for key in value), "Q4 evidence JSON key type drifted")
        for item in values:
            _strict_json(item, active=active, depth=depth + 1)
    finally:
        active.remove(identity)


def canonical_bytes(value: Any) -> bytes:
    _strict_json(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4EvidenceV4Error("Q4 evidence is not canonical JSON") from error


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None, f"{label} is not SHA-256")
    return value


def _relative(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    _require(
        "\\" not in value and ":" not in value and "\x00" not in value
        and not posix.is_absolute() and not windows.is_absolute()
        and posix.as_posix() == value and bool(posix.parts)
        and all(
            part not in {"", ".", ".."} and not part.endswith((".", " "))
            and part.split(".", 1)[0].upper() not in _RESERVED
            and all(ord(character) >= 32 for character in part)
            for part in posix.parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS, f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and 0 < size <= _MAX_EVIDENCE_FILE_BYTES, f"{label} descriptor size is invalid")
    return {"path": _relative(value.get("path"), label), "size_bytes": size, "sha256": _sha(value.get("sha256"), f"{label} file")}


def coordinate_for_q4_cell_index_v4(cell_index: int) -> dict[str, Any]:
    _require(type(cell_index) is int and 0 <= cell_index < 560, "Q4 cell_index is invalid")
    remaining, deadline_position = divmod(cell_index, len(DEADLINES_MS))
    remaining, policy_position = divmod(remaining, len(POLICIES))
    remaining, topology_position = divmod(remaining, len(TOPOLOGIES))
    system_codec_position, codec_position = divmod(remaining, len(CODECS))
    return {
        "system": SYSTEMS[system_codec_position], "codec": CODECS[codec_position],
        "topology_kind": TOPOLOGIES[topology_position],
        "policy": POLICIES[policy_position],
        "deadline_ms": DEADLINES_MS[deadline_position], "cell_index": cell_index,
    }


def _coordinate(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _COORDINATE_FIELDS, "Q4 evidence coordinate fields drifted")
    index = value.get("cell_index")
    _require(type(index) is int, "Q4 evidence cell_index type drifted")
    expected = coordinate_for_q4_cell_index_v4(index)
    _require(value == expected, "Q4 evidence coordinate does not match its ordinal")
    return copy.deepcopy(expected)


def pre_finalization_evidence_files_v4(policy: str, *, runtime_history: bool = False) -> tuple[str, ...]:
    _require(type(policy) is str and policy in POLICIES, "Q4 evidence policy is invalid")
    _require(type(runtime_history) is bool and (not runtime_history or policy == "adaptive_weights"), "Q4 runtime history is only valid for adaptive_weights")
    values = (*BASE_EVIDENCE_FILES, POLICY_DECISIONS_JSONL)
    if policy == "adaptive_weights":
        values = (*values, POLICY_FEEDBACK_JSONL)
    return (*values, POLICY_RUNTIME_HISTORY_JSONL) if runtime_history else values


def qualification_launcher_evidence_files_v4(policy: str, *, runtime_history: bool = False) -> tuple[str, ...]:
    return (*pre_finalization_evidence_files_v4(policy, runtime_history=runtime_history), "resource_intervals.csv", "fanout_work_counters.csv", CANDIDATE_FILENAME)


def raw_evidence_files_v4(policy: str, *, runtime_history: bool = False) -> tuple[str, ...]:
    return (*qualification_launcher_evidence_files_v4(policy, runtime_history=runtime_history), "hardware_resource_samples.csv")


def _history_namespace(names: Any, *, policy: str) -> bool:
    _require(type(names) in {list, tuple}, "Q4 evidence namespace type drifted")
    present = POLICY_RUNTIME_HISTORY_JSONL in names
    _require(not present or policy == "adaptive_weights", "non-adaptive policy exposed runtime history")
    return present


def _physical_root(value: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(value)))
    try:
        resolved = lexical.resolve(strict=True)
        info = lexical.lstat()
    except OSError as error:
        raise PublicationQ4EvidenceV4Error(f"project_root is unavailable: {error}") from error
    _require(lexical == resolved and stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), "project_root is not a canonical physical directory")
    return resolved


def _path_under_root(root: Path, relative: str, *, label: str) -> Path:
    checked = _relative(relative, label)
    path = root.joinpath(*PurePosixPath(checked).parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PublicationQ4EvidenceV4Error(f"{label} is unavailable: {error}") from error
    _require(resolved == path and resolved.is_relative_to(root), f"{label} escaped project_root or crossed a link")
    parent = root
    for part in PurePosixPath(checked).parts[:-1]:
        parent = parent / part
        info = parent.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), f"{label} parent is unsafe")
    return path


def _hash_fd(fd: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _physical_descriptor(root: Path, relative: str, *, label: str) -> dict[str, Any]:
    path = _path_under_root(root, relative, label=label)
    fd = -1
    try:
        before = path.lstat()
        _require(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode) and int(before.st_nlink) == 1, f"{label} is not a unique regular file")
        if path.name == POLICY_RUNTIME_HISTORY_JSONL:
            _require(0 < before.st_size <= _MAX_HISTORY_BYTES, "policy runtime history file exceeds the bound")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(fd)
        if path.name == POLICY_RUNTIME_HISTORY_JSONL:
            _require(0 < opened.st_size <= _MAX_HISTORY_BYTES, "policy runtime history file exceeds the bound")
        size, digest = _hash_fd(fd)
        after = path.lstat()
        # On Windows, opening a file can legitimately update the exposed creation/
        # change timestamp even when the file identity and contents did not move.
        # Device/inode/mode/link-count/size/mtime plus the open descriptor hash are
        # the stable cross-platform TOCTOU identity.  Linux still gets O_NOFOLLOW.
        identity = lambda item: (int(item.st_dev), int(item.st_ino), int(item.st_mode), int(item.st_nlink), int(item.st_size), int(item.st_mtime_ns))
        _require(identity(before) == identity(opened) == identity(after) and size == int(after.st_size), f"{label} changed while hashing")
    except OSError as error:
        raise PublicationQ4EvidenceV4Error(f"{label} physical read failed: {error}") from error
    finally:
        if fd >= 0:
            os.close(fd)
    return {"path": relative, "size_bytes": size, "sha256": digest}


def _verify_descriptor(root: Path, value: Any, *, label: str) -> Path:
    expected = _descriptor(value, label)
    observed = _physical_descriptor(root, expected["path"], label=label)
    _require(observed == expected, f"{label} physical descriptor drifted")
    return root.joinpath(*PurePosixPath(expected["path"]).parts)


def _load_json(path: Path, *, label: str, maximum: int = _MAX_JSON_BYTES) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        _require(0 < len(payload) <= maximum, f"{label} size is invalid")
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicationQ4EvidenceV4Error(f"{label} is not valid JSON: {error}") from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(payload in {canonical_bytes(value), canonical_bytes(value) + b"\n"}, f"{label} is not canonical JSON")
    return dict(value)


def _typed_contract_ref(
    value: Any, *, label: str, schema_version: int, artifact_kind: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict
        and set(value) == {
            "artifact_schema_version", "artifact_kind", "descriptor",
            "content_identity_sha256",
        }
        and type(value.get("artifact_schema_version")) is int
        and value.get("artifact_schema_version") == schema_version
        and type(value.get("artifact_kind")) is str
        and value.get("artifact_kind") == artifact_kind,
        f"{label} typed reference drifted",
    )
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} semantic"
        ),
    }


def _runtime_contract(value: Any, *, coordinate: Mapping[str, Any], run_id: str, duration_s: int) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _RUNTIME_CONTRACT_FIELDS,
        "runtime contract v4 fields drifted",
    )
    _require(
        value.get("schema_version") == 4
        and value.get("artifact_kind") == RUNTIME_CONTRACT_KIND
        and value.get("status") == "bound_non_authorizing_arbitrary_q4_runtime"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "runtime contract v4 header/claims drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "contract_sha256"}
    identity = _sha(value.get("contract_sha256"), "runtime contract v4")
    _require(identity == canonical_sha256(unsigned), "runtime contract v4 self-hash drifted")
    _require(value.get("coordinate") == dict(coordinate) and value.get("run_id") == run_id and value.get("duration_s") == duration_s, "runtime contract v4 run/coordinate drifted")
    graph = value.get("native_graph_contract")
    _require(
        type(graph) is dict and set(graph) == _NATIVE_GRAPH_FIELDS,
        "native graph contract v4 fields drifted",
    )
    _require(
        graph.get("schema_version") == 4
        and graph.get("artifact_kind") == NATIVE_GRAPH_KIND
        and graph.get("status") == "bound_non_authorizing_native_runtime_graph"
        and graph.get("authorization_eligible") is False
        and graph.get("execution_authorized") is False,
        "native graph contract header/claims drifted",
    )
    graph_unsigned = {key: item for key, item in graph.items() if key != "graph_contract_sha256"}
    _require(graph.get("graph_contract_sha256") == canonical_sha256(graph_unsigned), "native graph contract self-hash drifted")
    _require(graph.get("coordinate") == dict(coordinate) and graph.get("run_id") == run_id and graph.get("duration_s") == duration_s, "native graph contract run/coordinate drifted")
    runtime_history = _history_namespace(graph.get("launcher_evidence_files"), policy=str(coordinate["policy"]))
    _require(graph.get("launcher_evidence_files") == list(qualification_launcher_evidence_files_v4(str(coordinate["policy"]), runtime_history=runtime_history)), "native graph policy-aware evidence contract drifted")
    runtime_inputs = value.get("runtime_inputs")
    _require(
        type(runtime_inputs) is dict and set(runtime_inputs) == _RUNTIME_INPUT_FIELDS,
        "runtime contract v4 runtime input fields drifted",
    )
    _require(
        runtime_inputs.get("system") == coordinate["system"]
        and runtime_inputs.get("topology_kind") == coordinate["topology_kind"]
        and runtime_inputs.get("scenario")
        == SCENARIO_BY_TOPOLOGY[coordinate["topology_kind"]]
        and runtime_inputs.get("codec") == coordinate["codec"]
        and runtime_inputs.get("policy") == coordinate["policy"]
        and type(runtime_inputs.get("deadline_ms"))
        is type(coordinate["deadline_ms"])
        and runtime_inputs.get("deadline_ms") == coordinate["deadline_ms"]
        and runtime_inputs.get("duration_s") == duration_s == DURATION_S
        and runtime_inputs.get("warmup_s") == WARMUP_S
        and runtime_inputs.get("streams") == STREAMS
        and runtime_inputs.get("base_seed") == BASE_SEED
        and runtime_inputs.get("run_id") == run_id,
        "runtime contract v4 runtime input identity drifted",
    )
    _require(
        graph.get("runtime_inputs_sha256") == canonical_sha256(runtime_inputs),
        "native graph runtime-input identity drifted",
    )

    dataset = runtime_inputs.get("dataset")
    runtime_key = _RUNTIME_INPUT_KEY_BY_SYSTEM[str(coordinate["system"])]
    _require(
        type(dataset) is dict
        and set(dataset)
        == {
            "name", "codec_variant", "logical_stream_instances", "streams",
            runtime_key,
        }
        and dataset.get("name")
        == f"kpp_iss_publication_v3_{coordinate['codec']}"
        and dataset.get("codec_variant") == coordinate["codec"]
        and dataset.get("logical_stream_instances") == STREAMS,
        "runtime contract v4 dataset fields/identity drifted",
    )
    streams = dataset.get("streams")
    _require(type(streams) is list and len(streams) == STREAMS, "runtime contract v4 dataset stream coverage drifted")
    checked_streams: list[dict[str, Any]] = []
    for position, stream in enumerate(streams):
        _require(
            type(stream) is dict
            and set(stream) == {"stream_id", "codec_name", "sha256"}
            and stream.get("stream_id") == position
            and stream.get("codec_name") == coordinate["codec"],
            f"runtime contract v4 dataset stream[{position}] drifted",
        )
        checked_streams.append(
            {
                "stream_id": position,
                "codec_name": coordinate["codec"],
                "sha256": _sha(stream.get("sha256"), f"dataset stream[{position}]"),
            }
        )
    _require(
        len({item["sha256"] for item in checked_streams}) == 2
        and all(
            checked_streams[position]["sha256"] == checked_streams[0]["sha256"]
            for position in range(5)
        )
        and checked_streams[5]["sha256"] != checked_streams[0]["sha256"],
        "runtime contract v4 dataset source topology drifted",
    )
    template = dataset.get(runtime_key)
    system = str(coordinate["system"])
    _require(
        type(template) is dict
        and set(template) == _RUNTIME_TEMPLATE_FIELDS_BY_SYSTEM[system]
        and template.get("schema_version") == 3
        and template.get("artifact_kind") == _RUNTIME_INPUT_KIND_BY_SYSTEM[system]
        and template.get("defer_full_resource_acceptance") is True,
        "runtime contract v4 embedded v3 input identity drifted",
    )
    evidence_mapping = template.get("evidence_mapping")
    expected_evidence = qualification_launcher_evidence_files_v4(
        str(coordinate["policy"]), runtime_history=runtime_history,
    )
    _require(
        type(evidence_mapping) is dict
        and set(evidence_mapping) == set(expected_evidence)
        and len(set(evidence_mapping.values())) == len(evidence_mapping)
        and all(
            type(name) is str and PurePosixPath(name).name == name
            for name in evidence_mapping.values()
        ),
        "runtime contract v4 embedded v3 evidence mapping drifted",
    )
    _require(
        (coordinate["policy"] == "static_hybrid")
        == (type(template.get("static_hybrid_map")) is dict),
        "runtime contract v4 embedded static-hybrid binding drifted",
    )
    source_files = template.get("source_files")
    _require(
        type(source_files) is list and len(source_files) == 2
        and all(
            type(item) is dict
            and set(item) in (
                {"path", "size_bytes", "sha256"},
                {"path", "container_path", "size_bytes", "sha256"},
            )
            and type(item.get("size_bytes")) is int
            and item["size_bytes"] > 0
            and _SHA_RE.fullmatch(str(item.get("sha256", ""))) is not None
            for item in source_files
        )
        and {item["sha256"] for item in source_files}
        == {item["sha256"] for item in checked_streams},
        "runtime contract v4 embedded source/dataset binding drifted",
    )
    dataset_binding_unsigned = {
        "schema_version": 4,
        "artifact_kind": "vast_frozen_publication_dataset_binding_v4",
        "status": "frozen_publication_codec_corpus",
        "codec_variant": coordinate["codec"],
        "dataset": {
            "name": dataset["name"],
            "codec_variant": dataset["codec_variant"],
            "logical_stream_instances": STREAMS,
            "streams": checked_streams,
        },
    }
    dataset_binding_sha = canonical_sha256(dataset_binding_unsigned)
    _require(
        value.get("dataset_binding_sha256") == dataset_binding_sha
        == graph.get("dataset_binding_sha256"),
        "runtime contract v4 dataset binding identity drifted",
    )
    authority_snapshot_sha = _sha(
        value.get("authority_snapshot_sha256"), "authority snapshot"
    )
    _require(
        graph.get("authority_snapshot_sha256") == authority_snapshot_sha,
        "runtime contract v4 authority snapshot cross-binding drifted",
    )
    upstream = graph.get("upstream_identities")
    _require(
        type(upstream) is dict and set(upstream) == _UPSTREAM_IDENTITY_FIELDS,
        "native graph upstream identity fields drifted",
    )
    for field in _UPSTREAM_IDENTITY_FIELDS:
        _sha(upstream.get(field), f"native graph {field}")
    reference_specs = (
        ("runtime_authority_ref", "runtime_authority_sha256", 2, RUNTIME_AUTHORITY_KIND),
        (
            "launcher_runtime_authority_ref", "launcher_runtime_authority_sha256",
            1, LAUNCHER_RUNTIME_AUTHORITY_KIND,
        ),
        (
            "publication_launcher_invocation_v3_ref",
            "publication_launcher_invocation_v3_sha256", 3,
            PUBLICATION_LAUNCHER_INVOCATION_KIND,
        ),
        (
            "q4_validator_authority_ref", "q4_validator_authority_sha256", 1,
            VALIDATOR_AUTHORITY_KIND,
        ),
        (
            "runner_authority_ref", "runner_authority_sha256", 1,
            RUNNER_AUTHORITY_KIND,
        ),
    )
    reference_paths: list[str] = []
    for ref_field, pin_field, schema_version, kind in reference_specs:
        checked_ref = _typed_contract_ref(
            graph.get(ref_field), label=ref_field,
            schema_version=schema_version, artifact_kind=kind,
        )
        pin = _sha(graph.get(pin_field), f"native graph {pin_field}")
        _require(
            checked_ref["content_identity_sha256"] == pin,
            f"native graph {ref_field} semantic cross-binding drifted",
        )
        reference_paths.append(checked_ref["descriptor"]["path"])
    _require(
        len(reference_paths) == len({item.casefold() for item in reference_paths}),
        "native graph authority reference paths alias",
    )
    for field in (
        "runtime_authority_set_sha256", "runtime_binding_identity_v4_sha256",
        "runner_invocation_identity_sha256",
    ):
        _sha(graph.get(field), f"native graph {field}")
    return copy.deepcopy(value)


def build_publication_q4_raw_evidence_manifest_v4(
    *, project_root: Path | str, evidence_dir: Path | str,
    runtime_contract_path: Path | str, coordinate: Mapping[str, Any],
    run_id: str, duration_s: int = DURATION_S,
) -> dict[str, Any]:
    """Physically pin, but do not accept or write, one Q4 evidence namespace."""
    root = _physical_root(project_root)
    cell = _coordinate(copy.deepcopy(dict(coordinate)))
    _require(type(run_id) is str and _RUN_ID_RE.fullmatch(run_id) is not None, "Q4 evidence run_id is invalid")
    _require(type(duration_s) is int and duration_s == DURATION_S, "Q4 evidence duration must equal 180 seconds")
    evidence_root = Path(os.path.abspath(os.fspath(evidence_dir)))
    contract_path = Path(os.path.abspath(os.fspath(runtime_contract_path)))
    _require(evidence_root.resolve(strict=True) == evidence_root and evidence_root.is_dir() and evidence_root.is_relative_to(root), "Q4 evidence_dir is unsafe")
    _require(contract_path.resolve(strict=True) == contract_path and contract_path.is_file() and contract_path.is_relative_to(root), "runtime contract path is unsafe")
    contract_relative = contract_path.relative_to(root).as_posix()
    contract_descriptor = _physical_descriptor(root, contract_relative, label="runtime contract")
    contract = _runtime_contract(_load_json(contract_path, label="runtime contract"), coordinate=cell, run_id=run_id, duration_s=duration_s)
    graph = contract["native_graph_contract"]
    runtime_history = _history_namespace(graph["launcher_evidence_files"], policy=cell["policy"])
    names = raw_evidence_files_v4(cell["policy"], runtime_history=runtime_history)
    descriptors = [
        _physical_descriptor(
            root, (evidence_root / name).relative_to(root).as_posix(),
            label=f"Q4 evidence {name}",
        )
        for name in names
    ]
    _require(sum(item["size_bytes"] for item in descriptors) <= _MAX_TOTAL_EVIDENCE_BYTES, "Q4 evidence total size exceeds the bound")
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RAW_EVIDENCE_MANIFEST_KIND,
        "status": "captured_native_runtime_evidence",
        "authorization_eligible": False,
        "execution_authorized": False,
        "coordinate": cell,
        "run_id": run_id,
        "duration_s": duration_s,
        "runtime_contract": contract_descriptor,
        "runtime_contract_sha256": contract["contract_sha256"],
        "native_graph_contract_sha256": graph["graph_contract_sha256"],
        "runtime_authority_sha256": _sha(graph.get("runtime_authority_sha256"), "runtime authority"),
        "evidence_files": descriptors,
        "evidence_file_set_sha256": canonical_sha256(descriptors),
    }
    return {**unsigned, "raw_evidence_manifest_sha256": canonical_sha256(unsigned)}


def validate_publication_q4_raw_evidence_manifest_v4(
    value: Any, *, expected_coordinate: Mapping[str, Any], expected_run_id: str,
    expected_runtime_authority_sha256: str,
    expected_runtime_contract_sha256: str | None = None,
) -> dict[str, Any]:
    """Purely validate the exact raw-manifest ABI and external identities."""
    _require(type(value) is dict and set(value) == _MANIFEST_FIELDS, "Q4 raw evidence manifest fields drifted")
    coordinate = _coordinate(copy.deepcopy(dict(expected_coordinate)))
    _require(value.get("schema_version") == SCHEMA_VERSION and value.get("artifact_kind") == RAW_EVIDENCE_MANIFEST_KIND and value.get("status") == "captured_native_runtime_evidence" and value.get("authorization_eligible") is False and value.get("execution_authorized") is False, "Q4 raw evidence manifest header/claims drifted")
    _require(value.get("coordinate") == coordinate and value.get("run_id") == expected_run_id and value.get("duration_s") == DURATION_S, "Q4 raw evidence manifest run/coordinate drifted")
    _require(type(expected_run_id) is str and _RUN_ID_RE.fullmatch(expected_run_id) is not None, "expected Q4 run_id is invalid")
    contract = _descriptor(value.get("runtime_contract"), "runtime contract")
    contract_identity = _sha(value.get("runtime_contract_sha256"), "runtime contract semantic")
    if expected_runtime_contract_sha256 is not None:
        _require(contract_identity == _sha(expected_runtime_contract_sha256, "expected runtime contract"), "runtime contract expected pin drifted")
    runtime_authority = _sha(expected_runtime_authority_sha256, "expected runtime authority")
    _require(value.get("runtime_authority_sha256") == runtime_authority, "Q4 raw evidence runtime authority cross-binding drifted")
    _sha(value.get("native_graph_contract_sha256"), "native graph contract")
    files = value.get("evidence_files")
    _require(type(files) is list, "Q4 raw evidence file coverage drifted")
    checked = [_descriptor(item, f"Q4 evidence file {position}") for position, item in enumerate(files)]
    paths = [PurePosixPath(item["path"]) for item in checked]
    runtime_history = _history_namespace([path.name for path in paths], policy=coordinate["policy"])
    expected_names = raw_evidence_files_v4(coordinate["policy"], runtime_history=runtime_history)
    _require(len(files) == len(expected_names), "Q4 raw evidence file coverage drifted")
    _require(all(item["size_bytes"] <= _MAX_HISTORY_BYTES for item in checked if PurePosixPath(item["path"]).name == POLICY_RUNTIME_HISTORY_JSONL), "policy runtime history descriptor exceeds the bound")
    _require(tuple(path.name for path in paths) == expected_names and len({path.as_posix().casefold() for path in paths}) == len(paths), "Q4 raw evidence file order/name drifted")
    _require(len({path.parent.as_posix() for path in paths}) == 1, "Q4 raw evidence files are not direct siblings")
    _require(contract["path"].casefold() not in {path.as_posix().casefold() for path in paths}, "runtime contract aliases raw evidence")
    _require(value.get("evidence_file_set_sha256") == canonical_sha256(checked), "Q4 raw evidence file-set identity drifted")
    unsigned = {key: item for key, item in value.items() if key != "raw_evidence_manifest_sha256"}
    _require(value.get("raw_evidence_manifest_sha256") == canonical_sha256(unsigned), "Q4 raw evidence manifest self-hash drifted")
    return copy.deepcopy(value)


def _csv_rows(path: Path, columns: Sequence[str], *, label: str, allow_empty: bool = False) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            _require(tuple(reader.fieldnames or ()) == tuple(columns), f"{label} exact CSV header drifted")
            rows: list[dict[str, str]] = []
            for number, row in enumerate(reader, start=2):
                _require(number <= _MAX_ROWS + 1, f"{label} row count exceeds bound")
                _require(None not in row and all(value is not None for value in row.values()), f"{label}:{number} malformed CSV row")
                rows.append(dict(row))
    except (OSError, UnicodeError, csv.Error) as error:
        raise PublicationQ4EvidenceV4Error(f"{label} cannot be read: {error}") from error
    _require(allow_empty or bool(rows), f"{label} must not be empty")
    return rows


def _canonical_int(value: Any, label: str, *, positive: bool = False) -> int:
    text = str(value)
    _require(re.fullmatch(r"0|[1-9][0-9]*", text) is not None, f"{label} is not a canonical integer")
    number = int(text)
    _require(not positive or number > 0, f"{label} must be positive")
    return number


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise PublicationQ4EvidenceV4Error(f"{label} is not numeric") from error
    _require(math.isfinite(number), f"{label} is not finite")
    return number


def _frame_key(row: Mapping[str, Any]) -> tuple[str, str, int, int]:
    return (str(row.get("run_id")), str(row.get("trace_id")), _canonical_int(row.get("stream_id"), "stream_id"), _canonical_int(row.get("frame_id"), "frame_id"))


def _basic_native_rows(rows: Sequence[Mapping[str, str]], *, run_id: str, label: str) -> None:
    for number, row in enumerate(rows, start=2):
        _require(row.get("schema_version") == "2", f"{label}:{number} schema_version drifted")
        _require(row.get("run_id") == run_id, f"{label}:{number} run_id drifted")
        if "telemetry_source" in row:
            _require(row.get("telemetry_source") == "native", f"{label}:{number} telemetry_source is not native")


def _json_array(value: Any, label: str) -> list[Any]:
    try:
        result = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise PublicationQ4EvidenceV4Error(f"{label} is not JSON") from error
    _require(type(result) is list, f"{label} is not a JSON array")
    return result


def _policy_evaluation(
    record: Mapping[str, Any], *, policy: str, strict_original: bool = False,
) -> tuple[dict[str, dict[str, Any]], str, str]:
    request = record.get("request")
    _require(
        type(request) is dict and set(request) == _DECISION_REQUEST_FIELDS,
        "policy decision request fields drifted",
    )
    _require(
        request.get("decision_id") == record.get("decision_id")
        and request.get("decision_seq") == record.get("decision_seq")
        and request.get("trace_id") == record.get("trace_id")
        and request.get("branch") == record.get("branch"),
        "policy decision request/record identity drifted",
    )
    sequence = request.get("decision_seq")
    _require(type(sequence) is int and sequence > 0, "policy decision sequence is invalid")
    candidates = request.get("candidates")
    _require(
        type(candidates) is dict and set(candidates) == set(RESOURCES),
        "policy decision candidate resource set drifted",
    )
    decision_time = _finite(request.get("decision_time_ms"), "policy decision time")
    arrival = _finite(request.get("arrival_ms"), "policy arrival time")
    deadline = _finite(request.get("deadline_ms"), "policy deadline")
    rank = _finite(request.get("rank_u_ms"), "policy upward rank")
    _require(
        arrival >= 0 and decision_time >= 0 and deadline > 0 and rank >= 0
        and (strict_original or arrival <= decision_time < deadline),
        "policy decision request timing drifted",
    )
    evaluations: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        candidate = candidates.get(resource)
        _require(
            type(candidate) is dict and set(candidate) == _DECISION_CANDIDATE_FIELDS
            and type(candidate.get("allowed")) is bool
            and type(candidate.get("implementation_id")) is str
            and bool(candidate["implementation_id"])
            and type(candidate.get("queue_depth")) is int
            and candidate["queue_depth"] >= 0,
            f"policy decision {resource} candidate drifted",
        )
        available = _finite(candidate.get("available_ms"), f"{resource} availability")
        service = _finite(candidate.get("estimated_service_ms"), f"{resource} service")
        transfer = _finite(candidate.get("transfer_ms"), f"{resource} transfer")
        _require(
            available >= 0 and service > 0 and transfer >= 0,
            f"policy decision {resource} candidate timing drifted",
        )
        start = max(decision_time, available)
        finish = start + service + transfer
        evaluations[resource] = {
            "allowed": candidate["allowed"],
            "implementation_id": candidate["implementation_id"],
            "available_ms": float(available),
            "queue_depth": candidate["queue_depth"],
            "estimated_service_ms": float(service),
            "transfer_ms": float(transfer),
            "predicted_start_ms": float(start),
            "predicted_finish_ms": float(finish),
            "predicted_lateness_ms": float(max(0.0, finish - deadline)),
        }
    allowed = [resource for resource in RESOURCES if evaluations[resource]["allowed"]]
    _require(bool(allowed), "policy decision has no allowed real resource")
    resource_index = {resource: index for index, resource in enumerate(RESOURCES)}

    def tail(resource: str) -> tuple[Any, ...]:
        item = evaluations[resource]
        return (item["transfer_ms"], item["queue_depth"], resource_index[resource])

    if policy in {"cpu_only", "gpu_only"}:
        selected = "cpu" if policy == "cpu_only" else "gpu"
        _require(selected in allowed, f"{policy} required resource is not allowed")
        reason = "forced_policy_resource"
    elif policy == "static_hybrid":
        placement = record.get("static_hybrid_placement")
        _require(
            type(placement) is dict and set(placement) == set(BRANCHES)
            and set(placement.values()) == set(RESOURCES),
            "static_hybrid placement is not an exact mixed map",
        )
        selected = str(placement[str(record["branch"])])
        _require(selected in allowed, "static_hybrid selected resource is not allowed")
        reason = "frozen_calibrated_mixed_map"
    elif policy == "heft":
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["predicted_finish_ms"], *tail(resource)
            ),
        )
        reason = "minimum_earliest_finish_time"
    elif policy == "deadline_aware_heft":
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["predicted_finish_ms"] > deadline,
                evaluations[resource]["predicted_lateness_ms"],
                evaluations[resource]["predicted_finish_ms"],
                *tail(resource),
            ),
        )
        reason = (
            "minimum_feasible_finish_time"
            if evaluations[selected]["predicted_finish_ms"] <= deadline
            else "minimum_predicted_lateness"
        )
    elif policy == "queue_aware_edf":
        for resource in RESOURCES:
            item = evaluations[resource]
            item["queue_completion_ms"] = float(
                max(decision_time, item["available_ms"])
                + (item["queue_depth"] + 1) * item["estimated_service_ms"]
                + item["transfer_ms"]
            )
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["queue_completion_ms"], *tail(resource)
            ),
        )
        reason = "edf_task_minimum_queue_completion"
    else:
        _require(policy == "adaptive_weights", "policy evaluator received an unknown policy")
        state = record.get("state_before")
        _require(
            type(state) is dict
            and set(state) == {"arm_id", "weights", "service_ewma_ms"}
            and state.get("arm_id") == record.get("arm_id")
            and type(state.get("weights")) is dict
            and set(state["weights"]) == set(RESOURCES)
            and type(state.get("service_ewma_ms")) is dict,
            "adaptive policy state drifted",
        )
        branch_ewma = state["service_ewma_ms"].get(str(record["branch"]), {})
        _require(type(branch_ewma) is dict, "adaptive branch EWMA state drifted")
        for resource in RESOURCES:
            item = evaluations[resource]
            weight = _finite(state["weights"][resource], f"adaptive {resource} weight")
            service_basis = _finite(
                branch_ewma.get(resource, item["estimated_service_ms"]),
                f"adaptive {resource} service basis",
            )
            _require(0.5 <= weight <= 1.5 and service_basis > 0, "adaptive state bounds drifted")
            item["service_basis_ms"] = float(service_basis)
            item["adaptive_weight"] = float(weight)
            item["adaptive_score_ms"] = float(
                (item["queue_depth"] + 1) * service_basis * weight
                + item["transfer_ms"]
            )
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["adaptive_score_ms"], *tail(resource)
            ),
        )
        reason = "minimum_bounded_queue_ewma_cost"
    return evaluations, selected, reason


def _json_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "policy JSON contains duplicate keys")
        result[key] = value
    return result


def _policy_jsonl(path: Path, *, label: str, history: bool = False) -> Iterable[dict[str, Any]]:
    line_bound = _MAX_HISTORY_LINE_BYTES if history else _MAX_JSONL_LINE_BYTES
    byte_bound = _MAX_HISTORY_BYTES if history else _MAX_EVIDENCE_FILE_BYTES
    row_bound = _MAX_HISTORY_EVENTS + 1 if history else _MAX_ROWS
    total = 0
    try:
        with path.open("rb") as source:
            _require(0 < os.fstat(source.fileno()).st_size <= byte_bound, f"{label} file exceeds the bound")
            number = 0
            while raw := source.readline(line_bound + 1):
                number += 1
                total += len(raw)
                _require(number <= row_bound and total <= byte_bound, f"{label} count/byte bound exceeded")
                _require(0 < len(raw) <= line_bound and raw.endswith(b"\n"), f"{label} line {number} framing drifted")
                value = json.loads(raw, object_pairs_hook=_json_object_pairs)
                _require(type(value) is dict and raw == canonical_bytes(value) + b"\n", f"{label} line {number} is not canonical")
                yield value
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise PublicationQ4EvidenceV4Error(f"{label} cannot be read: {error}") from error


def _record_hash(value: Mapping[str, Any], *, label: str) -> None:
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    _require(value.get("sha256") == canonical_sha256(unsigned), f"{label} self-hash drifted")


def _same_json(left: Any, right: Any) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


def _reset_state(arm_id: str) -> dict[str, Any]:
    return {"arm_id": arm_id, "weights": {"cpu": 1.0, "gpu": 1.0}, "service_ewma_ms": {}}


def _validate_policy_state(value: Any, *, arm_id: str, label: str) -> None:
    _require(
        type(value) is dict and set(value) == {"arm_id", "weights", "service_ewma_ms"}
        and value.get("arm_id") == arm_id and type(value.get("weights")) is dict
        and set(value["weights"]) == set(RESOURCES) and type(value.get("service_ewma_ms")) is dict
        and set(value["service_ewma_ms"]).issubset(BRANCHES),
        f"{label} fields drifted",
    )
    for resource in RESOURCES:
        weight = value["weights"][resource]
        _require(type(weight) in {int, float} and 0.5 <= _finite(weight, label) <= 1.5, f"{label} weight drifted")
    for costs in value["service_ewma_ms"].values():
        _require(type(costs) is dict and set(costs).issubset(RESOURCES) and bool(costs), f"{label} EWMA resource set drifted")
        _require(all(type(cost) in {int, float} and _finite(cost, label) > 0 for cost in costs.values()), f"{label} EWMA cost drifted")


def _reconstruct_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DECISION_RECORD_FIELDS | {"publication_projection"}, "policy publication projection record fields drifted")
    _record_hash(value, label="policy projected decision")
    projection = value.get("publication_projection")
    _require(
        type(projection) is dict and set(projection) == _PROJECTION_FIELDS
        and type(projection.get("schema_version")) is int and projection["schema_version"] == 1,
        "policy publication projection fields/version drifted",
    )
    trace = projection.get("original_worker_trace_id")
    sequence = projection.get("original_runtime_decision_seq")
    _require(type(trace) is str and len(trace) <= 4096 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{7,}", trace) is not None, "policy publication projection original trace is invalid")
    _require(type(sequence) is int and sequence > 0, "policy publication projection runtime sequence is invalid")
    request = value.get("request")
    _require(
        type(request) is dict and set(request) == _DECISION_REQUEST_FIELDS
        and request.get("trace_id") == value.get("trace_id")
        and type(request.get("decision_seq")) is int
        and request.get("decision_seq") == value.get("decision_seq")
        and request.get("decision_id") == value.get("decision_id")
        and request.get("branch") == value.get("branch"),
        "policy publication projection request/record identity drifted",
    )
    original = copy.deepcopy(dict(value))
    original.pop("publication_projection")
    original["trace_id"] = original["request"]["trace_id"] = trace
    original["decision_seq"] = original["request"]["decision_seq"] = sequence
    accepted_sha = canonical_sha256({key: item for key, item in original.items() if key != "sha256"})
    _require(accepted_sha == _sha(projection.get("accepted_record_sha256"), "original accepted decision"), "policy publication projection original accepted hash drifted")
    original["sha256"] = accepted_sha
    issued = copy.deepcopy(original)
    issued["record_status"] = "replayable_not_runtime_accepted"
    issued["native_decision_evidence"] = None
    issued_sha = canonical_sha256({key: item for key, item in issued.items() if key != "sha256"})
    _require(issued_sha == _sha(projection.get("issued_record_sha256"), "original issued decision"), "policy publication projection original issued hash drifted")
    return original


def _validate_native_decision_record(
    value: Mapping[str, Any], *, policy: str, system: str, arm_id: str,
    contract_sha256: str, label: str, strict_original: bool = False,
) -> None:
    _require(type(value) is dict and set(value) == _DECISION_RECORD_FIELDS, f"{label} fields drifted")
    _record_hash(value, label=label)
    _require(value.get("schema_version") == 1 and value.get("artifact_kind") == "vast_publication_policy_decision" and value.get("policy_contract_sha256") == contract_sha256 and value.get("engine_implementation_id") == "vast-publication-policy-engine-v1" and value.get("policy_scope") == "analytics_only" and value.get("policy") == policy and value.get("system") == system and value.get("record_status") == "accepted_native_runtime_decision" and value.get("arm_id") == arm_id and value.get("branch") in BRANCHES, f"{label} native identity drifted")
    expected_evaluations, expected_selected, expected_reason = _policy_evaluation(
        value, policy=policy, strict_original=strict_original,
    )
    if strict_original:
        _require(type(value.get("schema_version")) is int, f"{label} schema version type drifted")
        request = value["request"]
        for field in ("decision_id", "trace_id", "arm_id"):
            text = value.get(field)
            _require(type(text) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+/-]{7,}", text) is not None and text.lower() not in {"cpu", "gpu", "native", "unknown", "unavailable", "label_only", "derived", "placeholder"}, f"{label} original {field} is not a real stable identity")
        _require(all(type(request.get(field)) is float for field in ("arrival_ms", "decision_time_ms", "deadline_ms", "rank_u_ms")), f"{label} original request is not normalized")
        for candidate in request["candidates"].values():
            _require(all(type(candidate.get(field)) is float for field in ("available_ms", "estimated_service_ms", "transfer_ms")), f"{label} original candidate is not normalized")
        _require(_same_json(value.get("evaluations"), expected_evaluations), f"{label} original frozen policy evaluation types drifted")
    _require(
        value.get("evaluations") == expected_evaluations
        and value.get("selected_resource") == expected_selected
        and value.get("selected_implementation_id") == expected_evaluations[expected_selected]["implementation_id"]
        and value.get("reason") == expected_reason,
        f"{label} frozen policy replay drifted",
    )
    if policy != "static_hybrid":
        _require(value.get("static_hybrid_map_sha256") is None and value.get("static_hybrid_placement") is None, f"{label} unexpected static map")
    else:
        _sha(value.get("static_hybrid_map_sha256"), f"{label} static map")
    evidence = value.get("native_decision_evidence")
    _require(
        type(evidence) is dict and set(evidence) == _NATIVE_DECISION_EVIDENCE_FIELDS
        and evidence.get("decision_id") == value.get("decision_id")
        and evidence.get("system") == system and evidence.get("branch") == value.get("branch")
        and evidence.get("selected_resource") == expected_selected
        and evidence.get("implementation_id") == value.get("selected_implementation_id")
        and evidence.get("telemetry_source") == "native" and evidence.get("terminal_status") == "completed"
        and _SHA_RE.fullmatch(str(evidence.get("emitter_sha256", ""))) is not None
        and all(type(evidence.get(field)) is str and bool(evidence[field]) for field in ("event_id", "emitter_id", "worker_id", "input_frame_key"))
        and _finite(evidence.get("path_entry_timestamp_ms"), "native path entry") <= _finite(evidence.get("terminal_timestamp_ms"), "native terminal")
        and _finite(evidence.get("actual_service_ms"), "native service") > 0
        and type(evidence.get("transport_pts_ns")) is int,
        f"{label} native evidence cross-binding drifted",
    )
    if strict_original:
        _require(evidence["transport_pts_ns"] >= 0 and all(type(evidence.get(field)) in {int, float} and _finite(evidence[field], field) > 0 for field in ("path_entry_timestamp_ms", "terminal_timestamp_ms", "actual_service_ms")), f"{label} original native coordinates/timing drifted")


def _validate_jsonl(
    path: Path, *, policy: str, system: str, run_id: str,
    expected_policy_contract_sha256: str,
    csv_decisions: Sequence[Mapping[str, str]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    expected_arm_id = (
        run_id.removeprefix("qualification-q4-v4-")
        if run_id.startswith("qualification-q4-v4-")
        else run_id
    )
    projected: bool | None = None
    originals: list[dict[str, Any]] = []
    native_event_ids: set[str] = set()
    for number, value in enumerate(_policy_jsonl(path, label="policy decision JSONL"), start=1):
        current_projected = "publication_projection" in value
        _require(projected is None or current_projected == projected, "policy decision arm mixes projected and legacy records")
        projected = current_projected
        original = _reconstruct_projection(value) if projected else value
        _validate_native_decision_record(
            original, policy=policy, system=system, arm_id=expected_arm_id,
            contract_sha256=expected_policy_contract_sha256,
            label=f"policy decision JSONL line {number}", strict_original=projected,
        )
        if projected:
            event_id = original["native_decision_evidence"]["event_id"]
            _require(event_id not in native_event_ids, "projected policy native decision event_id reused")
            native_event_ids.add(event_id)
            _validate_policy_state(original.get("state_before"), arm_id=expected_arm_id, label="original decision state")
            if policy != "adaptive_weights":
                _require(_same_json(original.get("state_before"), _reset_state(expected_arm_id)), "projected non-adaptive decision differs from actual reset state")
        records.append(dict(value))
        originals.append(dict(original))
    _require(bool(records), "policy decision JSONL must not be empty")
    decision_ids = [str(item.get("decision_id")) for item in records]
    csv_ids = [str(item.get("decision_id")) for item in csv_decisions]
    _require(len(set(decision_ids)) == len(decision_ids) and set(decision_ids) == set(csv_ids), "policy decision JSONL/CSV identity coverage drifted")
    sequences = [_canonical_int(item.get("decision_seq"), "policy decision sequence") for item in records]
    _require(sequences == list(range(1, len(sequences) + 1)), "policy decision sequence is not contiguous from one")
    if projected:
        runtime_sequences = [item["decision_seq"] for item in originals]
        _require(runtime_sequences == sorted(set(runtime_sequences)), "projected decision original runtime ordering drifted")
    by_id = {str(item["decision_id"]): item for item in records}
    for row in csv_decisions:
        record = by_id[str(row["decision_id"])]
        _require(row.get("policy") == policy and row.get("stage") == record.get("branch") and row.get("resource") == record.get("selected_resource") and row.get("decision") == record.get("selected_implementation_id") and row.get("policy_version") == record.get("engine_implementation_id") and row.get("trace_id") == record.get("trace_id") and _canonical_int(row.get("decision_seq"), "policy CSV decision_seq") == record.get("decision_seq") and row.get("decision_provenance") == "native_scheduler_trace" and row.get("trace_completeness") == "full" and row.get("causal_trace_completeness") == "full", "policy decision CSV/JSONL semantic cross-binding drifted")
        if projected:
            try:
                provenance = json.loads(str(row.get("feature_provenance_json", "")), object_pairs_hook=_json_object_pairs)
            except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
                raise PublicationQ4EvidenceV4Error("projected policy feature provenance cannot be read") from error
            _strict_json(provenance)
            queues = provenance.get("native_queue_depths") if type(provenance) is dict else None
            _require(type(queues) is dict and queues.get("source_trace_id") == record["publication_projection"]["original_worker_trace_id"] and queues.get("source") == f"native_worker_socket:{record['native_decision_evidence']['worker_id']}", "projected policy original worker/feature provenance drifted")
    selected = {str(item["selected_resource"]) for item in records}
    if policy == "cpu_only":
        _require(selected == {"cpu"}, "cpu_only evidence executed a non-CPU policy path")
    if policy == "gpu_only":
        _require(selected == {"gpu"}, "gpu_only evidence executed a non-GPU policy path")
    if policy == "static_hybrid":
        placements: dict[str, str] = {}
        for item in records:
            placement = item.get("static_hybrid_placement")
            _require(type(placement) is dict and set(placement) == set(BRANCHES), "static_hybrid placement is incomplete")
            current = str(placement[item["branch"]])
            _require(current == item["selected_resource"], "static_hybrid selected resource drifted")
            for branch in BRANCHES:
                observed = str(placement[branch])
                _require(observed in RESOURCES and (branch not in placements or placements[branch] == observed), "static_hybrid placement drifted within the arm")
                placements[branch] = observed
    return records


def _validate_runtime_feedback(record: Any, *, decision: Mapping[str, Any]) -> None:
    _require(type(record) is dict and set(record) == _FEEDBACK_RECORD_FIELDS, "runtime feedback fields drifted")
    _record_hash(record, label="runtime feedback")
    _require(
        type(record.get("schema_version")) is int and record["schema_version"] == 1
        and record.get("artifact_kind") == "vast_publication_policy_feedback"
        and record.get("policy") == "adaptive_weights"
        and all(record.get(field) == decision.get(field) for field in (
            "system", "arm_id", "decision_id", "policy_contract_sha256", "engine_implementation_id",
        )),
        "runtime feedback decision identity drifted",
    )
    native = decision["native_decision_evidence"]
    for field in ("actual_service_ms", "completed_at_ms", "deadline_ms"):
        _require(type(record.get(field)) is float, f"runtime feedback {field} is not normalized")
    service = _finite(record["actual_service_ms"], "runtime feedback service")
    completed = _finite(record["completed_at_ms"], "runtime feedback completion")
    deadline = _finite(record["deadline_ms"], "runtime feedback deadline")
    _require(
        service > 0 and completed >= 0 and deadline > 0
        and service == float(native["actual_service_ms"])
        and completed == float(native["terminal_timestamp_ms"])
        and deadline == float(decision["request"]["deadline_ms"])
        and record.get("outcome") == ("late" if completed > deadline else "on_time"),
        "runtime feedback native terminal linkage drifted",
    )
    for label in ("state_before", "state_after"):
        _validate_policy_state(record.get(label), arm_id=str(decision["arm_id"]), label=f"runtime feedback {label}")


def _validate_runtime_history(
    path: Path, *, run_id: str, decisions: Sequence[Mapping[str, Any]],
    feedback: Sequence[Mapping[str, Any]], accepted_ingress_input_keys: set[str],
) -> None:
    # Keep this replay independent: the isolated runner executes only these
    # pinned validator bytes and cannot import the producer's policy helpers.
    originals = {str(item["decision_id"]): _reconstruct_projection(item) for item in decisions}
    measured_feedback = {str(item["decision_id"]): item for item in feedback}
    first = next(iter(originals.values()))
    records = iter(_policy_jsonl(path, label="policy runtime history", history=True))
    header = next(records, None)
    _require(type(header) is dict and set(header) == _HISTORY_HEADER_FIELDS, "policy runtime history header fields drifted")
    _record_hash(header, label="policy runtime history header")
    _require(
        type(header.get("schema_version")) is int and header["schema_version"] == 1
        and header.get("artifact_kind") == "vast_publication_policy_runtime_history_v1"
        and header.get("record_kind") == "header" and header.get("run_id") == run_id
        and header.get("policy") == "adaptive_weights"
        and all(header.get(field) == first.get(field) for field in (
            "arm_id", "system", "policy_contract_sha256", "engine_implementation_id",
        )),
        "policy runtime history header identity/version drifted",
    )
    for field in (
        "runtime_decision_count", "runtime_feedback_count", "measurement_decision_count",
        "measurement_feedback_count", "event_count",
    ):
        _require(type(header.get(field)) is int and 0 < header[field] <= _MAX_HISTORY_EVENTS, "policy runtime history header count exceeds bound")
    _require(
        header["runtime_decision_count"] == header["runtime_feedback_count"]
        and header["event_count"] == header["runtime_decision_count"] + header["runtime_feedback_count"]
        and header["measurement_decision_count"] == len(originals)
        and header["measurement_feedback_count"] == len(measured_feedback)
        and header["runtime_decision_count"] >= len(originals),
        "policy runtime history header count/measurement coverage drifted",
    )
    arm_id = str(first["arm_id"])
    _validate_policy_state(header.get("initial_state"), arm_id=arm_id, label="policy runtime history initial state")
    _require(_same_json(header.get("initial_state"), _reset_state(arm_id)), "policy runtime history differs from actual initial reset")
    state = copy.deepcopy(header["initial_state"])
    issued: dict[str, dict[str, Any]] = {}
    issued_hashes: dict[str, str] = {}
    native_event_ids: set[str] = set()
    completed: set[str] = set()
    measurement_order: list[str] = []
    feedback_order: list[str] = []
    _require(type(accepted_ingress_input_keys) is set and bool(accepted_ingress_input_keys) and all(type(key) is str and bool(key) for key in accepted_ingress_input_keys), "policy runtime history requires full validated accepted-ingress input keys")
    event_count = 0
    for event_count, event in enumerate(records, start=1):
        _require(event_count <= header["event_count"], "policy runtime history has extra events")
        kind = event.get("event_type")
        expected_fields = _HISTORY_DECISION_FIELDS if kind == "decision_issued" else _HISTORY_FEEDBACK_FIELDS
        _require(kind in {"decision_issued", "feedback_applied"} and set(event) == expected_fields, "policy runtime history event fields/type drifted")
        _record_hash(event, label="policy runtime history event")
        _require(
            type(event.get("schema_version")) is int and event["schema_version"] == 1
            and event.get("artifact_kind") == "vast_publication_policy_runtime_history_event_v1"
            and type(event.get("event_seq")) is int and event["event_seq"] == event_count
            and type(event.get("measurement")) is bool
            and type(event.get("decision_id")) is str and bool(event["decision_id"]),
            "policy runtime history event identity/order drifted",
        )
        decision_id = event["decision_id"]
        measured = event["measurement"]
        _require(measured == (decision_id in originals), "policy runtime history measurement cohort drifted")
        _sha(event.get("issued_record_sha256"), "history issued decision")
        if kind == "decision_issued":
            _require(decision_id not in issued and type(event.get("runtime_decision_seq")) is int and event["runtime_decision_seq"] == len(issued) + 1, "policy runtime history issuance identity/ordinal drifted")
            if measured:
                _require(event.get("accepted_record") is None, "measured history issuance duplicates its original record")
                original = originals[decision_id]
                measurement_order.append(decision_id)
            else:
                original = event.get("accepted_record")
            _validate_native_decision_record(
                original, policy="adaptive_weights", system=str(first["system"]), arm_id=arm_id,
                contract_sha256=str(first["policy_contract_sha256"]), label="policy history original decision", strict_original=True,
            )
            event_id = original["native_decision_evidence"]["event_id"]
            _require(event_id not in native_event_ids, "policy runtime history original native decision event_id reused")
            native_event_ids.add(event_id)
            _validate_policy_state(original.get("state_before"), arm_id=arm_id, label="policy history decision state")
            _require(
                original.get("decision_id") == decision_id and original.get("decision_seq") == event["runtime_decision_seq"]
                and original.get("sha256") == _sha(event.get("accepted_record_sha256"), "history accepted decision")
                and _same_json(original.get("state_before"), state),
                "policy runtime history decision original/state linkage drifted",
            )
            _require(measured == (original["native_decision_evidence"]["input_frame_key"] in accepted_ingress_input_keys), "policy runtime history omits/substitutes accepted measurement input cohort")
            issued_record = copy.deepcopy(dict(original))
            issued_record["record_status"] = "replayable_not_runtime_accepted"
            issued_record["native_decision_evidence"] = None
            issued_sha = canonical_sha256({key: item for key, item in issued_record.items() if key != "sha256"})
            _require(issued_sha == event["issued_record_sha256"], "policy runtime history issued authority hash drifted")
            issued[decision_id] = dict(original)
            issued_hashes[decision_id] = issued_sha
        else:
            _require(decision_id in issued and decision_id not in completed and type(event.get("runtime_feedback_seq")) is int and event["runtime_feedback_seq"] == len(completed) + 1, "policy runtime history feedback orphan/duplicate/ordinal drifted")
            _require(event["issued_record_sha256"] == issued_hashes[decision_id], "policy runtime history feedback issued authority drifted")
            if measured:
                _require(event.get("feedback_record") is None and decision_id in measured_feedback, "policy runtime history measurement feedback is missing or duplicated")
                record = measured_feedback[decision_id]
                feedback_order.append(decision_id)
            else:
                record = event.get("feedback_record")
            decision = issued[decision_id]
            _validate_runtime_feedback(record, decision=decision)
            _require(record.get("sha256") == _sha(event.get("feedback_record_sha256"), "history original feedback") and _same_json(record.get("state_before"), state), "policy runtime history feedback hash/state_before drifted")
            expected_after = copy.deepcopy(state)
            branch, resource = str(decision["branch"]), str(decision["selected_resource"])
            branch_ewma = expected_after["service_ewma_ms"].setdefault(branch, {})
            previous = branch_ewma.get(resource)
            actual = float(record["actual_service_ms"])
            branch_ewma[resource] = actual if previous is None else 0.1 * actual + 0.9 * previous
            delta = 0.002 if record["outcome"] == "late" else -0.0002
            expected_after["weights"][resource] = min(1.5, max(0.5, expected_after["weights"][resource] + delta))
            _require(_same_json(record.get("state_after"), expected_after), "policy runtime history feedback state_after frozen transition drifted")
            state = expected_after
            completed.add(decision_id)
    _require(
        event_count == header["event_count"] and len(issued) == header["runtime_decision_count"]
        and len(completed) == header["runtime_feedback_count"] and completed == set(issued)
        and measurement_order == [str(item["decision_id"]) for item in decisions]
        and feedback_order == [str(item["decision_id"]) for item in feedback]
        and set(measurement_order) == set(originals) and set(feedback_order) == set(originals),
        "policy runtime history complete terminal/measurement ordering drifted",
    )


def _validate_feedback(
    path: Path | None, *, policy: str, decisions: Sequence[Mapping[str, Any]],
    runtime_history_path: Path | None = None, run_id: str | None = None,
    accepted_ingress_input_keys: set[str] | None = None,
) -> None:
    projected = bool(decisions) and "publication_projection" in decisions[0]
    _require(all(("publication_projection" in item) == projected for item in decisions), "policy feedback arm mixes projected and legacy decisions")
    _require((runtime_history_path is not None) == (projected and policy == "adaptive_weights"), "policy runtime history is required exactly for projected adaptive decisions")
    if policy != "adaptive_weights":
        _require(path is None, "non-adaptive policy exposed feedback evidence")
        return
    _require(path is not None, "adaptive_weights feedback evidence is missing")
    records: list[dict[str, Any]] = []
    for number, item in enumerate(_policy_jsonl(path, label="policy feedback JSONL"), start=1):
        _require(set(item) == _FEEDBACK_RECORD_FIELDS, f"policy feedback line {number} fields drifted")
        _record_hash(item, label=f"policy feedback line {number}")
        _require(item.get("schema_version") == 1 and item.get("artifact_kind") == "vast_publication_policy_feedback" and item.get("policy") == "adaptive_weights", f"policy feedback line {number} identity drifted")
        records.append(item)
    _require(len(records) == len(decisions) and {str(item.get("decision_id")) for item in records} == {str(item.get("decision_id")) for item in decisions}, "adaptive_weights feedback coverage drifted")
    decisions_by_id = {str(item["decision_id"]): item for item in decisions}
    arm_ids = {str(item["arm_id"]) for item in decisions}
    _require(len(arm_ids) == 1, "adaptive_weights decision arm identity drifted")
    if projected:
        _validate_runtime_history(
            runtime_history_path, run_id=run_id if run_id is not None else str(decisions[0]["arm_id"]),
            decisions=decisions, feedback=records, accepted_ingress_input_keys=accepted_ingress_input_keys,
        )
        return
    for number, feedback in enumerate(records, start=1):
        decision = decisions_by_id[str(feedback["decision_id"])]
        evidence = decision["native_decision_evidence"]
        service = _finite(feedback.get("actual_service_ms"), "adaptive feedback service")
        completed = _finite(feedback.get("completed_at_ms"), "adaptive feedback completion")
        deadline = _finite(feedback.get("deadline_ms"), "adaptive feedback deadline")
        _require(
            feedback.get("system") == decision.get("system")
            and feedback.get("arm_id") == decision.get("arm_id")
            and feedback.get("policy_contract_sha256")
            == decision.get("policy_contract_sha256")
            and feedback.get("engine_implementation_id")
            == decision.get("engine_implementation_id")
            and service > 0 and completed >= 0 and deadline > 0
            and service == float(evidence["actual_service_ms"])
            and completed == float(evidence["terminal_timestamp_ms"])
            and deadline == float(decision["request"]["deadline_ms"])
            and feedback.get("outcome")
            == ("late" if completed > deadline else "on_time"),
            f"adaptive feedback line {number} decision/terminal cross-binding drifted",
        )
        for state_label in ("state_before", "state_after"):
            state = feedback.get(state_label)
            _require(
                type(state) is dict
                and set(state) == {"arm_id", "weights", "service_ewma_ms"}
                and state.get("arm_id") == decision.get("arm_id")
                and type(state.get("weights")) is dict
                and set(state["weights"]) == set(RESOURCES)
                and all(
                    0.5 <= _finite(state["weights"][resource], "adaptive weight") <= 1.5
                    for resource in RESOURCES
                )
                and type(state.get("service_ewma_ms")) is dict,
                f"adaptive feedback line {number} {state_label} drifted",
            )


def _validate_full_resource(
    *, run_id: str, topology_kind: str,
    ingress: Sequence[Mapping[str, str]], topology: Sequence[Mapping[str, str]],
    frame_events: Sequence[Mapping[str, str]], intervals: Sequence[Mapping[str, str]],
    hardware: Sequence[Mapping[str, str]], fanout: Sequence[Mapping[str, str]],
) -> None:
    ingress_by_key = {_frame_key(row): row for row in ingress}
    _require(len(ingress_by_key) == len(ingress), "ingress ledger frame keys are duplicated")
    topology_by_execution: dict[tuple[tuple[str, str, int, int], str], Mapping[str, str]] = {}
    fanout_keys: set[tuple[str, int, int, str, str]] = set()
    for number, row in enumerate(topology, start=2):
        key = (_frame_key(row), str(row.get("execution_id")))
        _require(key not in topology_by_execution, f"topology events:{number} execution key is duplicated")
        _require(
            row.get("topology_kind") == topology_kind
            and row.get("event_kind") in {
                "source_read", "stage_complete", "fanout",
                "branch_complete", "join_complete",
            }
            and row.get("event_provenance") == "native_runtime_event"
            and row.get("telemetry_source") == "native",
            f"topology events:{number} topology/event identity drifted",
        )
        parents = _json_array(row.get("parent_execution_ids_json"), f"topology events:{number} parents")
        _require(all(type(item) is str and item for item in parents) and len(parents) == len(set(parents)), f"topology events:{number} parents drifted")
        _require(
            (row.get("event_kind") == "source_read" and not parents)
            or (row.get("event_kind") != "source_read" and bool(parents)),
            f"topology events:{number} source/parent relation drifted",
        )
        topology_by_execution[key] = row
        if row.get("event_kind") == "fanout":
            fanout_keys.add((str(row["trace_id"]), _canonical_int(row["stream_id"], "fanout stream"), _canonical_int(row["frame_id"], "fanout frame"), str(row["branch_id"]), str(row["execution_id"])))
    for (frame_key, _execution), row in topology_by_execution.items():
        for parent in _json_array(row.get("parent_execution_ids_json"), "topology parent set"):
            _require((frame_key, parent) in topology_by_execution, "topology event references a missing parent")
    _require((topology_kind == "shared_video_dag") == bool(fanout_keys), "topology fanout coverage contradicts topology_kind")
    event_by_stage = {(_frame_key(row), str(row.get("stage"))): row for row in frame_events}
    _require(len(event_by_stage) == len(frame_events), "frame event stage keys are duplicated")

    observed_nvdec: set[tuple[tuple[str, str, int, int], str]] = set()
    native_ids: set[str] = set()
    nvdec_devices: set[str] = set()
    for number, row in enumerate(intervals, start=2):
        _require(row.get("schema_version") == "2" and row.get("interval_contract_version") == "2" and row.get("run_id") == run_id and row.get("telemetry_source") == "native" and row.get("counter_scope") == "per_trace_interval", f"resource intervals:{number} contract/run provenance drifted")
        component = str(row.get("component")); direction = str(row.get("direction"))
        _require(component in {"transfer", "nvdec_submit_complete", "fanout"} and direction in {"h2d", "d2h", "none"} and ((component == "transfer") == (direction in {"h2d", "d2h"})), f"resource intervals:{number} component/direction drifted")
        expected_provenance = {"transfer": "native_cuda_event_interval_v1", "nvdec_submit_complete": "native_decoder_submit_complete_interval_v1", "fanout": "native_gstreamer_pad_probe_interval_v1"}[component]
        _require(row.get("duration_provenance") == expected_provenance and _DEVICE_RE.fullmatch(str(row.get("device_id", ""))) is not None and _SHA_RE.fullmatch(str(row.get("native_event_id", ""))) is not None, f"resource intervals:{number} native provenance drifted")
        _require(str(row["native_event_id"]) not in native_ids, f"resource intervals:{number} native_event_id reused")
        native_ids.add(str(row["native_event_id"]))
        start = _canonical_int(row.get("host_start_timestamp_ns"), "interval start")
        end = _canonical_int(row.get("host_end_timestamp_ns"), "interval end", positive=True)
        duration = _canonical_int(row.get("duration_ns"), "interval duration", positive=True)
        _canonical_int(row.get("bytes"), "interval bytes", positive=True)
        _require(start < end and duration <= end - start and (component == "transfer" or duration == end - start), f"resource intervals:{number} timing drifted")
        frame_key = _frame_key(row)
        ingress_row = ingress_by_key.get(frame_key)
        _require(ingress_row is not None and row.get("input_frame_key") == ingress_row.get("input_frame_key"), f"resource intervals:{number} ingress linkage drifted")
        ingress_ns = round(_finite(ingress_row["ingress_timestamp_ms"], "ingress timestamp") * 1_000_000)
        terminal_ns = round(_finite(ingress_row["terminal_timestamp_ms"], "terminal timestamp") * 1_000_000)
        _require(ingress_ns <= start < end <= terminal_ns, f"resource intervals:{number} outside frame lifetime")
        topology_row = topology_by_execution.get((frame_key, str(row.get("execution_id"))))
        _require(topology_row is not None and all(str(row.get(field)) == str(topology_row.get(field)) for field in ("input_frame_key", "stage", "branch_id")), f"resource intervals:{number} topology linkage drifted")
        if component == "nvdec_submit_complete":
            event = event_by_stage.get((frame_key, str(row.get("stage"))))
            _require(topology_row.get("event_kind") == "stage_complete" and event is not None and str(event.get("resource")).lower() == "nvdec" and str(row.get("stage")).startswith("decode") and re.fullmatch(r"nvdec:[0-9]+", str(row.get("device_id"))) is not None, f"resource intervals:{number} NVDEC linkage drifted")
            observed_nvdec.add((frame_key, str(row.get("execution_id"))))
            nvdec_devices.add(str(row["device_id"]))
        if component == "fanout":
            key = (str(row["trace_id"]), _canonical_int(row["stream_id"], "fanout stream"), _canonical_int(row["frame_id"], "fanout frame"), str(row["branch_id"]), str(row["execution_id"]))
            _require(key in fanout_keys and topology_row.get("event_kind") == "fanout", f"resource intervals:{number} fanout linkage drifted")
    expected_nvdec = {
        (frame_key, execution)
        for (frame_key, execution), row in topology_by_execution.items()
        if row.get("event_kind") == "stage_complete"
        and str(row.get("stage")).startswith("decode")
        and str(event_by_stage.get((frame_key, str(row.get("stage"))), {}).get("resource", "")).lower() == "nvdec"
    }
    _require(bool(expected_nvdec) and observed_nvdec == expected_nvdec, "resource interval NVDEC coverage is incomplete")

    starts = {_finite(row["window_start_timestamp_ms"], "measurement window start") for row in ingress}
    ends = {_finite(row["window_end_timestamp_ms"], "measurement window end") for row in ingress}
    _require(len(starts) == len(ends) == 1, "ingress measurement window is not unique")
    window_start_ns = round(next(iter(starts)) * 1_000_000)
    window_end_ns = round(next(iter(ends)) * 1_000_000)
    _require(window_end_ns - window_start_ns == DURATION_S * 1_000_000_000, "ingress measurement window is not frozen 180 seconds")
    hardware_by_device: dict[str, list[tuple[int, int, float]]] = {}
    expected_seq: dict[str, int] = {}
    previous_sample_end: dict[str, int] = {}
    for number, row in enumerate(hardware, start=2):
        _require(row.get("schema_version") == "2" and row.get("resource_contract_version") == "2" and row.get("run_id") == run_id, f"hardware resource samples:{number} run_id/contract drifted")
        device = str(row.get("device_id"))
        _require(re.fullmatch(r"gpu:[0-9]+", device) is not None and row.get("counter_scope") == "device_sample" and row.get("sample_provenance") == "nvml_device_decoder_utilization_v1" and row.get("telemetry_source") == "native", f"hardware resource samples:{number} native provenance drifted")
        sequence = _canonical_int(row.get("sample_seq"), "hardware sample_seq", positive=True)
        _require(sequence == expected_seq.get(device, 1), f"hardware resource samples:{number} sample_seq is not contiguous")
        expected_seq[device] = sequence + 1
        timestamp = _canonical_int(row.get("timestamp_ns"), "hardware timestamp", positive=True)
        period = _canonical_int(row.get("sample_period_us"), "hardware period", positive=True)
        interval_start = timestamp - period * 1000
        _require(interval_start >= 0, f"hardware resource samples:{number} starts before zero")
        previous_end = previous_sample_end.get(device)
        _require(
            previous_end is None
            or (timestamp > previous_end and interval_start <= previous_end),
            f"hardware resource samples:{number} is nonmonotonic or has a sampling gap",
        )
        previous_sample_end[device] = timestamp
        utilization = _finite(row.get("nvdec_util_percent"), "hardware NVDEC utilization")
        for field in ("gpu_util_percent", "memory_util_percent"):
            value = _finite(row.get(field), f"hardware {field}")
            _require(0 <= value <= 100, f"hardware resource samples:{number} {field} out of range")
        _require(0 <= utilization <= 100 and _canonical_int(row.get("vram_used_bytes"), "hardware VRAM") >= 0, f"hardware resource samples:{number} numeric drifted")
        hardware_by_device.setdefault(device, []).append((interval_start, timestamp, utilization))
    required_gpu = {"gpu:" + item.split(":", 1)[1] for item in nvdec_devices}
    _require(required_gpu.issubset(hardware_by_device), "NVDEC interval lacks a bound GPU hardware sample")
    for device in required_gpu:
        rows = hardware_by_device[device]
        _require(min(item[0] for item in rows) <= window_start_ns and max(item[1] for item in rows) >= window_end_ns and sum(item[2] * (item[1] - item[0]) for item in rows) > 0, f"hardware samples for {device} do not cover the window with positive NVDEC work")

    observed_fanout: set[tuple[str, int, int, str, str]] = set()
    for number, row in enumerate(fanout, start=2):
        _require(row.get("schema_version") == "2" and row.get("resource_contract_version") == "2" and row.get("run_id") == run_id and row.get("device_id") == "host:fanout" and row.get("counter_scope") == "per_trace_resource_work" and row.get("counter_provenance") == "native_thread_cpu_time_v1" and row.get("telemetry_source") == "native", f"fanout work counters:{number} native provenance drifted")
        _canonical_int(row.get("thread_cpu_time_ns"), "fanout CPU time", positive=True)
        _canonical_int(row.get("work_units"), "fanout work units", positive=True)
        key = (str(row["trace_id"]), _canonical_int(row["stream_id"], "fanout stream"), _canonical_int(row["frame_id"], "fanout frame"), str(row["branch_id"]), str(row["execution_id"]))
        _require(key not in observed_fanout, f"fanout work counters:{number} duplicate key")
        observed_fanout.add(key)
    _require(observed_fanout == fanout_keys, "fanout work counter coverage drifted")


def validate_publication_q4_evidence_files_v4(
    *, project_root: Path | str, raw_evidence_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Physically and semantically validate one already-structured manifest."""
    root = _physical_root(project_root)
    _require(type(raw_evidence_manifest) is dict, "Q4 raw evidence manifest type drifted")
    coordinate = _coordinate(raw_evidence_manifest.get("coordinate"))
    run_id = str(raw_evidence_manifest.get("run_id", ""))
    manifest = validate_publication_q4_raw_evidence_manifest_v4(
        raw_evidence_manifest, expected_coordinate=coordinate,
        expected_run_id=run_id,
        expected_runtime_authority_sha256=str(raw_evidence_manifest.get("runtime_authority_sha256", "")),
    )
    contract_path = _verify_descriptor(root, manifest["runtime_contract"], label="runtime contract")
    contract = _runtime_contract(_load_json(contract_path, label="runtime contract"), coordinate=coordinate, run_id=run_id, duration_s=DURATION_S)
    _require(contract["contract_sha256"] == manifest["runtime_contract_sha256"] and contract["native_graph_contract"]["graph_contract_sha256"] == manifest["native_graph_contract_sha256"] and contract["native_graph_contract"]["runtime_authority_sha256"] == manifest["runtime_authority_sha256"], "runtime contract/manifest semantic cross-binding drifted")
    paths: dict[str, Path] = {}
    descriptors: dict[str, dict[str, Any]] = {}
    for descriptor in manifest["evidence_files"]:
        checked = _descriptor(descriptor, "Q4 raw evidence")
        name = PurePosixPath(checked["path"]).name
        paths[name] = _verify_descriptor(root, checked, label=f"Q4 evidence {name}")
        descriptors[name] = checked
    runtime_history = POLICY_RUNTIME_HISTORY_JSONL in paths
    _require(
        contract["native_graph_contract"]["launcher_evidence_files"]
        == list(qualification_launcher_evidence_files_v4(coordinate["policy"], runtime_history=runtime_history)),
        "Q4 runtime contract/raw evidence history namespace drifted",
    )

    candidate = _load_json(paths[CANDIDATE_FILENAME], label="native checkpoint candidate", maximum=4 * 1024 * 1024)
    _require(set(candidate) == _CANDIDATE_FIELDS, "native checkpoint candidate fields drifted")
    expected_identity = {
        "schema_version": 2, "artifact_kind": "checkpoint_publication_runtime_candidate",
        "status": "pending_full_resource_validation", "run_id": run_id,
        "system": coordinate["system"], "scenario": SCENARIO_BY_TOPOLOGY[coordinate["topology_kind"]],
        "codec": coordinate["codec"], "policy": coordinate["policy"],
        "execution_binding_provenance": "native_scheduler_execution_binding_v1",
        "topology_kind": coordinate["topology_kind"],
    }
    _require(all(type(candidate.get(field)) is type(expected) and candidate.get(field) == expected for field, expected in expected_identity.items()), "native checkpoint candidate identity drifted")
    _require(
        type(candidate.get("deadline_ms")) is float
        and math.isfinite(candidate["deadline_ms"])
        and candidate["deadline_ms"] == float(coordinate["deadline_ms"]),
        "native checkpoint candidate identity drifted: deadline_ms",
    )
    _require(type(candidate.get("cohort_id")) is str and bool(candidate["cohort_id"]) and _SHA_RE.fullmatch(str(candidate.get("measurement_schedule_fingerprint_sha256", ""))) is not None and type(candidate.get("summary")) is dict, "native checkpoint candidate cohort/summary drifted")
    candidate_summary = candidate["summary"]
    _require(
        all(candidate_summary.get(gate) is True for gate in _CANDIDATE_SUMMARY_GATES),
        "native checkpoint candidate acceptance summary gate drifted",
    )
    _require(
        type(candidate_summary.get("c_obs_total_ms")) in {int, float}
        and type(candidate_summary.get("c_obs_total_ms")) is not bool
        and math.isfinite(float(candidate_summary["c_obs_total_ms"]))
        and float(candidate_summary["c_obs_total_ms"]) > 0,
        "native checkpoint candidate resource observation is empty",
    )
    expected_pre = pre_finalization_evidence_files_v4(coordinate["policy"], runtime_history=runtime_history)
    evidence_hashes = candidate.get("evidence_sha256")
    _require(
        type(evidence_hashes) is dict
        and len(evidence_hashes) == len(expected_pre)
        and set(evidence_hashes) == set(expected_pre),
        "native checkpoint candidate policy-aware evidence set drifted",
    )
    _require(all(evidence_hashes[name] == descriptors[name]["sha256"] for name in expected_pre), "native checkpoint candidate evidence hash drifted")
    _require(candidate.get("pending_full_resource_evidence") == list(FULL_RESOURCE_FILES), "native checkpoint candidate full-resource pending set drifted")

    csv_specs: dict[str, tuple[str, ...]] = {
        "frames.csv": FRAME_COLUMNS, "frame_events.csv": FRAME_EVENT_COLUMNS,
        "resource_events.csv": RESOURCE_EVENT_COLUMNS,
        "policy_decisions.csv": POLICY_DECISION_COLUMNS,
        "drop_counters.csv": DROP_COUNTER_COLUMNS,
        "topology_events.csv": TOPOLOGY_EVENT_COLUMNS,
        "ingress_ledger.csv": INGRESS_LEDGER_COLUMNS,
        "branch_terminals.csv": BRANCH_TERMINAL_COLUMNS,
        "stage_contracts.csv": STAGE_CONTRACT_COLUMNS,
        "reset_evidence.csv": RESET_EVIDENCE_COLUMNS,
        "resource_intervals.csv": RESOURCE_INTERVAL_COLUMNS,
        "hardware_resource_samples.csv": HARDWARE_RESOURCE_SAMPLE_COLUMNS,
        "fanout_work_counters.csv": FANOUT_WORK_COUNTER_COLUMNS,
    }
    rows = {
        name: _csv_rows(paths[name], columns, label=name, allow_empty=(name == "fanout_work_counters.csv" and coordinate["topology_kind"] == "independent_processes"))
        for name, columns in csv_specs.items()
    }
    for name, values in rows.items():
        _basic_native_rows(values, run_id=run_id, label=name)

    ingress = rows["ingress_ledger.csv"]
    ingress_keys = [_frame_key(row) for row in ingress]
    _require(len(set(ingress_keys)) == len(ingress_keys) and {key[2] for key in ingress_keys} == set(range(STREAMS)), "ingress ledger six-stream/frame identity drifted")
    _require(all(row.get("terminal_status") == "completed" and row.get("cohort_id") == candidate["cohort_id"] for row in ingress), "ingress ledger terminal/cohort drifted")
    completed = {str(stream): sum(1 for key in ingress_keys if key[2] == stream) for stream in range(STREAMS)}
    _require(candidate.get("completed_frames_by_stream") == completed, "native checkpoint candidate completed stream cohort drifted")
    frames = rows["frames.csv"]
    _require({_frame_key(row) for row in frames} == set(ingress_keys) and len(frames) == len(ingress) and all(row.get("detector") == "checkpoint_all_branches_per_stream_v1" for row in frames), "frames/ingress aggregate coverage drifted")
    terminals = rows["branch_terminals.csv"]
    terminals_by_frame: dict[tuple[str, str, int, int], set[str]] = {}
    for row in terminals:
        _require(row.get("cohort_id") == candidate["cohort_id"] and row.get("terminal_status") == "completed" and row.get("branch_id") in BRANCHES, "branch terminal native identity drifted")
        terminals_by_frame.setdefault(_frame_key(row), set()).add(str(row["branch_id"]))
    _require(set(terminals_by_frame) == set(ingress_keys) and all(value == set(BRANCHES) for value in terminals_by_frame.values()) and len(terminals) == len(ingress) * len(BRANCHES), "branch terminal coverage drifted")

    decisions = rows["policy_decisions.csv"]
    _require(len(decisions) == len(terminals) and all(row.get("policy") == coordinate["policy"] and row.get("stage") in BRANCHES and row.get("resource") in RESOURCES for row in decisions), "policy decision CSV coverage drifted")
    decision_records = _validate_jsonl(
        paths[POLICY_DECISIONS_JSONL], policy=coordinate["policy"],
        system=coordinate["system"], run_id=run_id,
        expected_policy_contract_sha256=contract["native_graph_contract"][
            "upstream_identities"
        ]["policy_contract_sha256"],
        csv_decisions=decisions,
    )
    terminal_by_stage = {
        (*_frame_key(row), str(row["branch_id"])): row for row in terminals
    }
    frame_event_by_stage = {
        (*_frame_key(row), str(row["stage"])): row
        for row in rows["frame_events.csv"]
    }
    records_by_id = {str(item["decision_id"]): item for item in decision_records}
    projected = "publication_projection" in decision_records[0]
    ingress_by_frame = {_frame_key(row): row for row in ingress}
    if projected:
        _require(len({str(row.get("input_frame_key")) for row in ingress}) == len(ingress), "projected policy accepted ingress input-frame mapping is ambiguous")
        decision_stage_keys = [(*_frame_key(row), str(row["stage"])) for row in decisions]
        _require(len(set(decision_stage_keys)) == len(decision_stage_keys) and set(decision_stage_keys) == set(terminal_by_stage), "projected policy measurement branch cohort has duplicate/missing executions")
    for number, row in enumerate(decisions, start=2):
        record = records_by_id[str(row["decision_id"])]
        key = (*_frame_key(row), str(row["stage"]))
        terminal = terminal_by_stage.get(key)
        frame_event = frame_event_by_stage.get(key)
        native = record["native_decision_evidence"]
        if projected:
            accepted_ingress = ingress_by_frame.get(_frame_key(row))
            _require(accepted_ingress is not None and accepted_ingress.get("input_frame_key") == native.get("input_frame_key"), "projected policy canonical accepted-ingress mapping drifted")
        _require(
            terminal is not None and frame_event is not None
            and terminal.get("input_frame_key") == native.get("input_frame_key")
            and terminal.get("detector") == native.get("detector")
            and terminal.get("backend") == native.get("backend")
            and terminal.get("terminal_status") == native.get("terminal_status")
            and float(terminal["terminal_timestamp_ms"])
            == float(native["terminal_timestamp_ms"])
            == float(row["terminal_timestamp_ms"])
            and frame_event.get("resource") == record.get("selected_resource"),
            f"policy decision CSV row {number} terminal/execution cross-binding drifted",
        )
    _validate_feedback(
        paths.get(POLICY_FEEDBACK_JSONL), policy=coordinate["policy"], decisions=decision_records,
        runtime_history_path=paths.get(POLICY_RUNTIME_HISTORY_JSONL), run_id=run_id,
        accepted_ingress_input_keys={str(row["input_frame_key"]) for row in ingress},
    )
    _validate_full_resource(
        run_id=run_id, topology_kind=coordinate["topology_kind"],
        ingress=ingress, topology=rows["topology_events.csv"],
        frame_events=rows["frame_events.csv"], intervals=rows["resource_intervals.csv"],
        hardware=rows["hardware_resource_samples.csv"], fanout=rows["fanout_work_counters.csv"],
    )
    return {
        "coordinate": copy.deepcopy(coordinate),
        "raw_evidence_manifest_sha256": manifest["raw_evidence_manifest_sha256"],
        "replay_result": copy.deepcopy(QUALIFIED_REPLAY_RESULT),
    }


def _request_coordinate(value: Mapping[str, Any]) -> dict[str, Any]:
    return _coordinate({field: value.get(field) for field in _COORDINATE_FIELDS})


def _request_ref(value: Any, *, label: str, schema_version: int | None = None, artifact_kind: str | None = None) -> dict[str, Any]:
    expected = {"descriptor", "content_identity_sha256"}
    if schema_version is not None or artifact_kind is not None:
        expected |= {"artifact_schema_version", "artifact_kind"}
    _require(type(value) is dict and set(value) == expected, f"{label} request reference fields drifted")
    if schema_version is not None:
        _require(
            type(value.get("artifact_schema_version")) is int
            and value.get("artifact_schema_version") == schema_version
            and type(value.get("artifact_kind")) is str
            and value.get("artifact_kind") == artifact_kind,
            f"{label} request typed identity drifted",
        )
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} semantic")
    return {
        **(
            {
                "artifact_schema_version": schema_version,
                "artifact_kind": artifact_kind,
            }
            if schema_version is not None
            else {}
        ),
        "descriptor": descriptor,
        "content_identity_sha256": identity,
    }


def _validate_request(
    value: Any, *, expected_request_sha256: str,
    raw_manifest_descriptor: Mapping[str, Any], raw_manifest_sha256: str,
    expected_runner_authority_sha256: str, expected_validator_authority_sha256: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _REQUEST_FIELDS,
        "formal validation request fields drifted",
    )
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == 2
        and type(value.get("artifact_kind")) is str
        and value.get("artifact_kind") == VALIDATION_REQUEST_KIND,
        "formal validation request header drifted",
    )
    coordinate = _request_coordinate(value)
    identity = _sha(value.get("request_sha256"), "formal validation request")
    unsigned = {key: item for key, item in value.items() if key != "request_sha256"}
    _require(identity == canonical_sha256(unsigned) == _sha(expected_request_sha256, "expected validation request"), "formal validation request self/external pin drifted")
    raw_ref = _request_ref(value.get("raw_evidence_ref"), label="raw evidence")
    _require(raw_ref["descriptor"] == dict(raw_manifest_descriptor) and raw_ref["content_identity_sha256"] == raw_manifest_sha256, "formal request raw evidence cross-binding drifted")
    runtime_ref = _request_ref(value.get("runtime_authority_ref"), label="runtime authority", schema_version=2, artifact_kind=RUNTIME_AUTHORITY_KIND)
    _require(runtime_ref["content_identity_sha256"] == value.get("runtime_authority_sha256"), "formal request runtime authority semantic pin drifted")
    runner_ref = _request_ref(value.get("runner_authority_ref"), label="runner authority", schema_version=1, artifact_kind=RUNNER_AUTHORITY_KIND)
    validator_ref = _request_ref(value.get("q4_validator_authority_ref"), label="validator authority", schema_version=1, artifact_kind=VALIDATOR_AUTHORITY_KIND)
    _require(runner_ref["content_identity_sha256"] == value.get("runner_authority_sha256") == expected_runner_authority_sha256, "formal request runner authority pin drifted")
    _require(validator_ref["content_identity_sha256"] == value.get("q4_validator_authority_sha256") == expected_validator_authority_sha256, "formal request validator authority pin drifted")
    reference_pairs = (
        (
            "context_ref", "context_sha256", 2, CONTEXT_KIND,
            "system context",
        ),
        (
            "q4_input_ref", "q4_input_sha256", 4, Q4_INPUT_KIND,
            "Q4 input",
        ),
        (
            "publication_launcher_invocation_v3_ref",
            "publication_launcher_invocation_v3_sha256", 3,
            PUBLICATION_LAUNCHER_INVOCATION_KIND,
            "publication launcher invocation v3",
        ),
        (
            "launcher_runtime_authority_ref",
            "launcher_runtime_authority_sha256", 1,
            LAUNCHER_RUNTIME_AUTHORITY_KIND,
            "launcher runtime authority",
        ),
    )
    checked_references = {
        ref_field: _request_ref(
            value.get(ref_field), label=label,
            schema_version=schema_version, artifact_kind=kind,
        )
        for ref_field, _pin_field, schema_version, kind, label
        in reference_pairs
    }
    for ref_field, pin_field, _schema_version, _kind, label in reference_pairs:
        pin = _sha(value.get(pin_field), f"formal request {pin_field}")
        _require(
            checked_references[ref_field]["content_identity_sha256"] == pin,
            f"formal request {label} semantic pin drifted",
        )
    for field in (
        "runner_invocation_identity_sha256",
        "runtime_binding_identity_v4_sha256",
        "runtime_authority_set_sha256",
    ):
        _sha(value.get(field), f"formal request {field}")
    return {**copy.deepcopy(value), "_coordinate": coordinate}


def validate_publication_q4_evidence_v4(
    *, project_root: Path | str, validation_request: Mapping[str, Any],
    raw_evidence_manifest: Mapping[str, Any],
    raw_evidence_manifest_descriptor: Mapping[str, Any],
    expected_request_sha256: str, expected_runner_authority_sha256: str,
    expected_validator_authority_sha256: str,
) -> dict[str, Any]:
    """Validate a formal request and return only the qualified replay ABI."""
    descriptor = _descriptor(raw_evidence_manifest_descriptor, "raw evidence manifest")
    manifest = validate_publication_q4_raw_evidence_manifest_v4(
        raw_evidence_manifest,
        expected_coordinate=_request_coordinate(validation_request),
        expected_run_id=str(raw_evidence_manifest.get("run_id", "")),
        expected_runtime_authority_sha256=str(validation_request.get("runtime_authority_sha256", "")),
    )
    request = _validate_request(
        validation_request, expected_request_sha256=expected_request_sha256,
        raw_manifest_descriptor=descriptor,
        raw_manifest_sha256=manifest["raw_evidence_manifest_sha256"],
        expected_runner_authority_sha256=expected_runner_authority_sha256,
        expected_validator_authority_sha256=expected_validator_authority_sha256,
    )
    _require(manifest["runtime_authority_sha256"] == request["runtime_authority_sha256"], "formal request/manifest runtime authority drifted")
    checked = validate_publication_q4_evidence_files_v4(
        project_root=project_root, raw_evidence_manifest=manifest,
    )
    root = _physical_root(project_root)
    contract_path = _verify_descriptor(
        root, manifest["runtime_contract"], label="runtime contract",
    )
    contract = _runtime_contract(
        _load_json(contract_path, label="runtime contract"),
        coordinate=request["_coordinate"], run_id=manifest["run_id"],
        duration_s=DURATION_S,
    )
    graph = contract["native_graph_contract"]
    graph_request_pairs = (
        ("runtime_authority_ref", "runtime_authority_sha256"),
        ("launcher_runtime_authority_ref", "launcher_runtime_authority_sha256"),
        (
            "publication_launcher_invocation_v3_ref",
            "publication_launcher_invocation_v3_sha256",
        ),
        ("q4_validator_authority_ref", "q4_validator_authority_sha256"),
        ("runner_authority_ref", "runner_authority_sha256"),
    )
    _require(
        all(
            graph[ref_field] == request[ref_field]
            and graph[pin_field] == request[pin_field]
            for ref_field, pin_field in graph_request_pairs
        )
        and graph["runner_invocation_identity_sha256"]
        == request["runner_invocation_identity_sha256"]
        and graph["runtime_binding_identity_v4_sha256"]
        == request["runtime_binding_identity_v4_sha256"]
        and graph["runtime_authority_set_sha256"]
        == request["runtime_authority_set_sha256"],
        "formal request/native graph authority cross-binding drifted",
    )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": VALIDATION_RESULT_KIND,
        "status": "qualified_physical_runtime_evidence",
        "coordinate": copy.deepcopy(request["_coordinate"]),
        "request_sha256": request["request_sha256"],
        "raw_evidence_manifest_sha256": manifest["raw_evidence_manifest_sha256"],
        "replay_result": copy.deepcopy(checked["replay_result"]),
    }
    result = {**unsigned, "result_sha256": canonical_sha256(unsigned)}
    return validate_publication_q4_evidence_validation_result_v4(
        result, expected_coordinate=request["_coordinate"],
        expected_request_sha256=request["request_sha256"],
        expected_raw_evidence_manifest_sha256=manifest["raw_evidence_manifest_sha256"],
    )


def validate_publication_q4_evidence_validation_result_v4(
    value: Any, *, expected_coordinate: Mapping[str, Any],
    expected_request_sha256: str, expected_raw_evidence_manifest_sha256: str,
) -> dict[str, Any]:
    """Purely validate the sole allowed success stdout for the graph adapter."""
    _require(type(value) is dict and set(value) == _RESULT_FIELDS, "Q4 evidence validation result fields drifted")
    coordinate = _coordinate(copy.deepcopy(dict(expected_coordinate)))
    _require(value.get("schema_version") == SCHEMA_VERSION and value.get("artifact_kind") == VALIDATION_RESULT_KIND and value.get("status") == "qualified_physical_runtime_evidence" and value.get("coordinate") == coordinate, "Q4 evidence validation result identity drifted")
    _require(value.get("request_sha256") == _sha(expected_request_sha256, "expected request result") and value.get("raw_evidence_manifest_sha256") == _sha(expected_raw_evidence_manifest_sha256, "expected raw manifest result"), "Q4 evidence validation result parent identity drifted")
    replay = value.get("replay_result")
    _require(type(replay) is dict and replay == QUALIFIED_REPLAY_RESULT and all(type(replay[field]) is bool for field in ("accepted", "synthetic", "nonpublication", "publication_capable", "deterministic_replay_completed")), "Q4 evidence validation result replay shape is not qualified")
    unsigned = {key: item for key, item in value.items() if key != "result_sha256"}
    _require(value.get("result_sha256") == canonical_sha256(unsigned), "Q4 evidence validation result self-hash drifted")
    return copy.deepcopy(value)


__all__ = [
    "QUALIFIED_REPLAY_RESULT", "RAW_EVIDENCE_MANIFEST_KIND", "SCHEMA_VERSION",
    "VALIDATION_RESULT_KIND", "PublicationQ4EvidenceV4Error",
    "build_publication_q4_raw_evidence_manifest_v4", "canonical_sha256",
    "coordinate_for_q4_cell_index_v4", "pre_finalization_evidence_files_v4",
    "qualification_launcher_evidence_files_v4", "raw_evidence_files_v4",
    "validate_publication_q4_evidence_files_v4",
    "validate_publication_q4_evidence_v4",
    "validate_publication_q4_evidence_validation_result_v4",
    "validate_publication_q4_raw_evidence_manifest_v4",
]
