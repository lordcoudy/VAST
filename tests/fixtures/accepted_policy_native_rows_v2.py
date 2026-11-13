"""Data-only artificial rows, without importing test modules or changing paths."""
from __future__ import annotations

import hashlib
import json

from benchmark_contract import STAGE_SEMANTIC_CONTRACT_VERSION, stage_base_name
from resource_interval_contract import RESOURCE_INTERVAL_CONTRACT_VERSION


def _row(defaults, overrides):
    return {**defaults, **overrides}


_FRAME = {"schema_version": 2, "run_id": "r", "trace_id": "r:0:1", "stream_id": 0, "frame_id": 1}


def native_frame_row(**overrides):
    return _row({**_FRAME, "ingress_timestamp_ms": 100, "egress_timestamp_ms": 130, "e2e_latency_ms": 30,
                 "objects": 1, "detector": "d", "backend": "b", "telemetry_source": "native"}, overrides)


def native_event_row(**overrides):
    return _row({**_FRAME, "stage": "decode", "role": "local", "host": "localhost", "resource": "cpu",
                 "queue_enter_timestamp_ms": 100, "stage_start_timestamp_ms": 100, "stage_end_timestamp_ms": 110,
                 "queue_depth": 0, "estimated_cost_ms": 10, "policy_action": "native:test"}, overrides)


def ingress_ledger_row(**overrides):
    row = _row({**_FRAME, "cohort_id": "r:cohort:1", "input_frame_key": "source:0:1", "admission_seq": 1,
                "source_sha256": "1" * 64, "source_cycle": 0, "access_unit_pts_ns": 90_000,
                "payload_sha256": "2" * 64, "payload_size_bytes": 4096, "schedule_offset_ns": 1_000_000,
                "ingress_timestamp_ms": 100.0, "window_start_timestamp_ms": 90.0, "window_end_timestamp_ms": 200.0,
                "terminal_status": "completed", "terminal_timestamp_ms": 130.0, "drain_end_timestamp_ms": 250.0,
                "terminal_reason": "native_output_committed", "censoring_rule": "fixed_drain_cutoff_v1",
                "ingress_provenance": "native_ingress_event", "terminal_provenance": "native_completion_event",
                "telemetry_source": "native"}, overrides)
    for name, value in (("admission_seq", row["frame_id"]), ("access_unit_pts_ns", int(row["frame_id"]) * 90_000),
                        ("schedule_offset_ns", int(row["frame_id"]) * 1_000_000),
                        ("payload_sha256", hashlib.sha256(str(row["input_frame_key"]).encode()).hexdigest())):
        if name not in overrides:
            row[name] = value
    return row


def resource_event_row(**overrides):
    return _row({**_FRAME, "stage": "decode", "resource": "cpu", "timestamp_ms": 110.0,
                 "cpu_time_ms": 10.0, "gpu_time_ms": 0.0, "h2d_bytes": 0, "d2h_bytes": 0,
                 "nvdec_util_percent": 0.0, "vram_mb": 0.0, "time_provenance": "derived_from_native_stage_timestamps",
                 "transfer_provenance": "unavailable", "nvdec_provenance": "unavailable", "vram_provenance": "unavailable",
                 "telemetry_source": "native"}, overrides)


def branch_terminal_row(**overrides):
    return _row({**_FRAME, "cohort_id": "r:cohort:1", "input_frame_key": "source:0:1", "branch_id": "damage",
                 "terminal_status": "completed", "terminal_timestamp_ms": 130.0, "objects": 1,
                 "detector": "native-damage-v1;model_sha256=" + "a" * 64 + ";weights_sha256=" + "b" * 64,
                 "backend": "openvino-dlstreamer:gvadetect", "terminal_reason": "native_result_committed",
                 "terminal_provenance": "native_completion_event", "telemetry_source": "native"}, overrides)


def stage_contract_row(**overrides):
    stage = str(overrides.get("stage", "decode"))
    base = stage_base_name(stage)
    config = overrides.pop("implementation_config", {"backend": "ffmpeg", "stage": base, "settings": {"threads": 2}})
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))
    artifacts = overrides.pop("implementation_artifacts", [
        {"role": "stage_host", "logical_name": "vast-native-stage-runtime", "kind": "executable", "sha256": hashlib.sha256(b"stage-runtime").hexdigest()},
        {"role": "stage_plugin", "logical_name": f"native-{base}", "kind": "plugin", "sha256": hashlib.sha256(f"plugin-{base}".encode()).hexdigest()},
    ])
    artifacts_json = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
    return _row({"schema_version": 2, "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
                 "run_id": "r", "contract_id": f"r:domain-a:{stage}", "execution_domain": "domain-a", "stage": stage,
                 "base_stage": base, "implementation_name": f"native-{base}", "implementation_version": "1.0.0",
                 "implementation_config_json": config_json, "config_sha256": hashlib.sha256(config_json.encode()).hexdigest(),
                 "implementation_artifacts_json": artifacts_json, "implementation_artifacts_sha256": hashlib.sha256(artifacts_json.encode()).hexdigest(),
                 "implementation_artifact_provenance": "runtime_loaded_artifacts_v1",
                 "transform_json": json.dumps({"resize": {"mode": "identity"}, "normalization": {"mode": "identity"}}, sort_keys=True),
                 "output_media_type": "video/x-raw", "output_format": "rgb24", "output_dtype": "uint8",
                 "output_shape_json": json.dumps([1080, 1920, 3]), "ordering_contract": "stream_frame_monotonic_v1",
                 "contract_provenance": "runtime_loaded_configuration", "telemetry_source": "native"}, overrides)


def interval_row(**overrides):
    return _row({**_FRAME, "interval_contract_version": RESOURCE_INTERVAL_CONTRACT_VERSION,
                 "input_frame_key": "kpp-h264:stream0:pts90000", "component": "nvdec_submit_complete",
                 "direction": "none", "stage": "decode", "branch_id": "shared", "execution_id": "decode-1",
                 "host_start_timestamp_ns": 1_002_000_000, "host_end_timestamp_ns": 1_009_500_000, "duration_ns": 7_500_000,
                 "bytes": 4096, "device_id": "nvdec:0", "counter_scope": "per_trace_interval", "native_event_id": "1" * 64,
                 "duration_provenance": "native_decoder_submit_complete_interval_v1", "telemetry_source": "native"}, overrides)
