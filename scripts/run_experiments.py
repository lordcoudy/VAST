#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import psutil
import yaml
from backend_runtime_grant import (
    BackendRuntimeGrantError,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant,
)
from model_parity_grant import (
    ModelParityGrantError,
    model_parity_grant_from_identity_artifacts,
    validate_pre_run_model_parity_grant,
)
from backend_publication_dispatch import (
    BackendPublicationDispatchError,
    BackendPublicationDispatchResolver,
    build_backend_publication_command,
)
from backend_publication_output_receipt import (
    ARM_CONTRACT_FILENAME,
    BackendPublicationOutputReceiptError,
    launcher_output_protocol,
    validate_backend_publication_output_receipt,
    write_immutable_backend_publication_arm_contract,
)
from benchmark_contract import (
    ContractError,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
    assess_hardware_target,
    assess_primary_policy_runtime_compatibility,
    build_primary_architecture_runtime_plan,
    build_publication_evidence_bundle,
    build_primary_policy_runtime_plan,
    canonicalize_frames_csv,
    dataset_manifest_identity,
    git_manifest,
    load_dataset,
    normalize_scenario_contract,
    publication_run_contract_identity,
    publication_evidence_bundle_identity,
    resolve_publication_evidence_bundle_scope,
    resolve_publication_run_contract,
    resolve_scenario_contract,
    scenario_contract_identity,
    sha256_file,
    summarize_frames,
    summarize_sidecars,
    validate_frame_events,
    validate_required_sidecars,
    validate_primary_architecture_contrast,
    validate_primary_architecture_pair_run_contract,
    validate_primary_policy_ablation,
    validate_primary_policy_pair_run_contract,
    validate_publication_evidence_bundle,
    validate_stage_trace_coverage,
    write_provenance_labeled_sidecars,
    write_json,
)
from benchmark_adapters import select_scenarios, validate_benchmark_adapter
from checkpoint_publication_runtime import (
    commit_checkpoint_publication_acceptance,
    prepare_checkpoint_publication_acceptance,
)
from checkpoint_acceptance_metadata_binding import (
    AcceptanceMetadataBindingError,
    validate_checkpoint_acceptance_metadata_binding,
    validate_full_publication_execution_binding,
)
from publication_acceptance_evidence import accepted_arm_evidence_files
from collect_metrics import HardwareResourceCollector, MetricsCollector
from distributed_executor import (
    build_distributed_plan,
    load_hosts_config,
    print_distributed_plan,
    run_distributed,
)
from topology_contract import validate_topology_events

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def summary_fieldnames() -> list[str]:
    """Return the stable summary.csv contract, including all native proof fields."""
    return [
        "timestamp",
        "system",
        "scenario",
        "repeat",
        "exit_code",
        "status",
        "run_mode",
        "skip_reason",
        "streams",
        "duration_s",
        "scenario_variant",
        "placement_policy",
        "distributed",
        "deployment_mode",
        "host_topology",
        "host_role",
        "detector",
        "backend",
        "policy",
        "dataset",
        "seed",
        "run_seed",
        "deadline_ms",
        "throughput_fps",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "latency_p999_ms",
        "latency_max_ms",
        "slo_violation_rate_percent",
        "frames",
        "telemetry_source",
        "decode_count",
        "preprocess_count",
        "cpu_time_ms",
        "gpu_time_ms",
        "h2d_bytes",
        "d2h_bytes",
        "nvdec_utilization_percent",
        "vram_mb_max",
        "full_resource_evidence_accepted",
        "full_resource_coverage_complete",
        "resource_contract_version",
        "nvdec_busy_equivalent_ns",
        "nvdec_counter_scope",
        "fanout_thread_cpu_time_ns",
        "fanout_work_units",
        "fanout_counter_scope",
        "policy_decision_count",
        "policy_trace_complete",
        "policy_causal_trace_complete",
        "policy_online_trace_complete",
        "topology_trace_complete",
        "stage_semantic_contract_complete",
        "semantic_contract_version",
        "semantic_prefix_contract_sha256",
        "decoder_placement_verified",
        "decoder_placement_contract_version",
        "decoder_required_resource",
        "decoder_factory_identity_complete",
        "decoder_factory",
        "decoder_factory_allowed",
        "decoder_factory_identity_source",
        "decoder_placement_evidence_limit",
        "ingress_ledger_complete",
        "branch_terminal_trace_complete",
        "branch_terminal_event_count",
        "branch_analytics_contract_sha256",
        "native_branch_drop_event_count",
        "checkpoint_frame_aggregation_complete",
        "ingress_cohort_closed",
        "ingress_frame_count",
        "completed_frame_count",
        "dropped_frame_count",
        "censored_frame_count",
        "censored_frame_rate_percent",
        "ingress_cohort_id",
        "ingress_censoring_rule",
        "ingress_window_start_timestamp_ms",
        "ingress_window_end_timestamp_ms",
        "ingress_drain_end_timestamp_ms",
        "drain_duration_ms",
        "resource_attribution_complete",
        "resource_attribution",
        "resource_attributed_ingress_count",
        "resource_unattributed_event_count",
        "input_schedule_sha256",
        "input_frame_key_sequence_sha256",
        "measurement_window_duration_ms",
        "measurement_signature",
        "measurement_signature_payload_json",
        "c_obs_total_ms",
        "c_obs_cpu_total_ms",
        "c_obs_gpu_total_ms",
        "c_obs_in_ms_per_ingress",
        "c_obs_cpu_in_ms_per_ingress",
        "c_obs_gpu_in_ms_per_ingress",
        "c_obs_comp_ms_per_completed",
        "c_obs_is_partial",
        "reset_state_verified",
        "reset_contract_version",
        "reset_process_start_tokens_json",
        "reset_telemetry_sink_id",
        "dropped_frame_rate_percent",
        "late_frame_rate_percent",
    ]


SUMMARY_CORE_FIELDS = {
    "timestamp",
    "system",
    "scenario",
    "repeat",
    "exit_code",
    "status",
    "run_mode",
    "skip_reason",
    "streams",
    "duration_s",
    "scenario_variant",
    "placement_policy",
    "distributed",
    "deployment_mode",
    "host_topology",
    "host_role",
    "detector",
    "backend",
    "policy",
    "dataset",
    "deadline_ms",
    "throughput_fps",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_p99_ms",
    "slo_violation_rate_percent",
    "frames",
    "telemetry_source",
}
SUMMARY_STATUSES = {"planned", "completed", "skipped", "failed"}
SUMMARY_RUN_MODES = {"benchmark", "smoke"}


def validate_summary_rows(rows: list[dict[str, Any]]) -> None:
    """Validate every row before opening summary.csv for writing."""
    fieldnames = summary_fieldnames()
    if len(fieldnames) != len(set(fieldnames)):
        raise ContractError("summary.csv field contract contains duplicate names")
    allowed = set(fieldnames)
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ContractError(f"summary.csv row {row_index} must be a mapping")
        unexpected = sorted(set(row) - allowed)
        if unexpected:
            raise ContractError(
                f"summary.csv row {row_index} contains fields outside the stable schema: "
                f"{', '.join(unexpected)}"
            )
        missing_core = sorted(SUMMARY_CORE_FIELDS - set(row))
        if missing_core:
            raise ContractError(
                f"summary.csv row {row_index} is missing core fields: {', '.join(missing_core)}"
            )
        status = str(row["status"])
        if status not in SUMMARY_STATUSES:
            raise ContractError(f"summary.csv row {row_index} has unsupported status '{status}'")
        run_mode = str(row["run_mode"])
        if run_mode not in SUMMARY_RUN_MODES:
            raise ContractError(f"summary.csv row {row_index} has unsupported run_mode '{run_mode}'")
        if status == "completed" and run_mode == "benchmark":
            if str(row.get("telemetry_source", "")) != "native":
                raise ContractError(
                    f"summary.csv benchmark completed row {row_index} must use telemetry_source=native"
                )
            missing_completed = sorted(allowed - set(row))
            if missing_completed:
                raise ContractError(
                    f"summary.csv benchmark completed row {row_index} is missing proof fields: "
                    f"{', '.join(missing_completed)}"
                )


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    validate_summary_rows(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fieldnames())
        writer.writeheader()
        writer.writerows(rows)


def default_command_timeout_s(
    *,
    system_key: str,
    duration_s: int,
    distributed_enabled: bool,
    mode: str,
    env: dict[str, str] | None = None,
) -> int:
    values = os.environ if env is None else env
    startup_grace_s = int(values.get("STARTUP_GRACE_S", "180"))
    if mode == "benchmark" and not distributed_enabled and system_key == "savant":
        savant_startup_s = int(values.get("SAVANT_LOCAL_STARTUP_WAIT_S", str(startup_grace_s)))
        shutdown_grace_s = int(values.get("SAVANT_LOCAL_SHUTDOWN_GRACE_S", "15"))
        startup_windows = 2 if values.get("SAVANT_LOCAL_PREWARM", "1") != "0" else 1
        return int(duration_s) + (startup_windows * savant_startup_s) + (2 * shutdown_grace_s) + 120
    if mode == "benchmark" and not distributed_enabled and system_key == "gstreamer_custom":
        checkpoint_ready_timeout_s = int(values.get("CHECKPOINT_READY_TIMEOUT_S", "300"))
        checkpoint_drain_timeout_s = int(values.get("CHECKPOINT_DRAIN_TIMEOUT_S", "10"))
        # The preregistered checkpoint runtime owns a 30 s warmup in addition to
        # measurement. The final 90 s covers container launch, export, and validation.
        return (
            int(duration_s)
            + checkpoint_ready_timeout_s
            + checkpoint_drain_timeout_s
            + 120
        )
    return int(duration_s) + startup_grace_s + 60


@dataclass(frozen=True)
class ExecutionContext:
    run_kind: str
    deployment_mode: str
    host_topology: str
    distributed_enabled: bool
    hosts_config: dict[str, Any]
    hosts_config_path: Path
    sync_project: bool


def normalize_run_kind(run_kind: str, *, local_only: bool = False) -> str:
    if local_only or run_kind == "local":
        return "heterogeneous"
    return run_kind


def build_single_server_hosts_config(
    *,
    host: str,
    user: str,
    port: int,
    project_path: Path,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": "single-server-localhost",
        "address": host,
        "project_path": str(project_path),
        "roles": ["edge", "gpu_worker", "aggregator"],
        "runtime": {"docker": True, "gpu": True},
        "env": {},
        "transport": {"advertise_address": host},
    }
    if user:
        entry["user"] = user
    if port > 0:
        entry["port"] = port
    return {"topology": "single_host_ssh", "hosts": [entry]}


def resolve_execution_context(
    *,
    requested_run_kind: str,
    scenario: dict[str, Any],
    hosts_config: dict[str, Any],
    hosts_config_path: Path,
    single_server_host: str,
    single_server_user: str,
    single_server_port: int,
    project_root: Path,
) -> ExecutionContext:
    scenario_key = scenario["name"]
    scenario_distributed = bool(scenario.get("distributed", {}).get("enabled"))
    actual = "distributed" if requested_run_kind == "auto" and scenario_distributed else requested_run_kind
    if requested_run_kind == "auto" and not scenario_distributed:
        actual = "heterogeneous"

    if actual == "heterogeneous":
        if scenario_distributed:
            raise ContractError(
                f"scenario '{scenario_key}' is configured for distributed execution; "
                "use --run-kind single-server-distributed or --run-kind distributed"
            )
        return ExecutionContext(
            run_kind=actual,
            deployment_mode="heterogeneous",
            host_topology="single_host",
            distributed_enabled=False,
            hosts_config=hosts_config,
            hosts_config_path=hosts_config_path,
            sync_project=False,
        )

    if actual == "single-server-distributed":
        if not scenario_distributed:
            raise ContractError(
                f"scenario '{scenario_key}' is not configured for distributed execution; "
                "use a distributed scenario such as canonical_distributed"
            )
        return ExecutionContext(
            run_kind=actual,
            deployment_mode="single-server-distributed",
            host_topology="single_host_ssh",
            distributed_enabled=True,
            hosts_config=build_single_server_hosts_config(
                host=single_server_host,
                user=single_server_user,
                port=single_server_port,
                project_path=project_root,
            ),
            hosts_config_path=Path("<single-server-ssh>"),
            sync_project=False,
        )

    if actual == "distributed":
        if not scenario_distributed:
            raise ContractError(f"scenario '{scenario_key}' is not configured for distributed execution")
        return ExecutionContext(
            run_kind=actual,
            deployment_mode="distributed",
            host_topology="multi_host_ssh",
            distributed_enabled=True,
            hosts_config=hosts_config,
            hosts_config_path=hosts_config_path,
            sync_project=bool(scenario.get("distributed", {}).get("sync_project", True)),
        )

    raise ContractError(f"unknown run kind '{requested_run_kind}'")


def _object_profile(workload: dict[str, Any]) -> dict[str, int]:
    profile = workload.get("object_density", {})
    if profile is None:
        profile = {}
    return {
        "min": int(profile.get("min", 0)),
        "max": int(profile.get("max", 20)),
    }


def _scenario_duration_s(scenario: dict[str, Any], default_duration_s: int) -> int:
    workload = scenario.get("workload", {})
    override = workload.get("duration_s")
    return int(default_duration_s if override in (None, "") else override)


def normalize_scenario(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    return normalize_scenario_contract(name, raw)


def validate_checkpoint_workload(dataset: dict[str, Any], scenario: dict[str, Any]) -> None:
    if scenario.get("name") not in {
        "checkpoint_independent_processes_baseline",
        "checkpoint_video_dag_shared",
    }:
        return
    workload = scenario.get("workload") or {}
    routing_mode = str(workload.get("routing_mode", ""))
    if routing_mode == "unresolved" or not routing_mode:
        raise ContractError(f"scenario '{scenario['name']}' analytics routing is unresolved")
    dataset_routing = str(dataset.get("analytics_routing", ""))
    if dataset_routing != routing_mode:
        profile_name = str(workload.get("routing_profile", ""))
        route_scope = str(workload.get("routing_scope", ""))
        profiles = list(dataset.get("experimental_routing_profiles") or [])
        matched_profiles = [
            profile
            for profile in profiles
            if str((profile or {}).get("name", "")) == profile_name
            and str((profile or {}).get("routing_mode", "")) == routing_mode
            and str((profile or {}).get("scope", "")) == route_scope
            and (profile or {}).get("production_semantics") is False
        ]
        if len(matched_profiles) != 1 or route_scope != "topology_only_stress":
            raise ContractError(
                f"dataset '{dataset.get('name', '')}' analytics_routing does not match scenario routing_mode "
                "and no exact non-production experimental routing profile is declared"
            )
    streams = list(dataset.get("streams") or [])
    logical_stream_instances = int(workload.get("logical_stream_instances", 0) or 0)
    if logical_stream_instances != len(streams):
        raise ContractError(
            f"scenario '{scenario['name']}' logical_stream_instances does not match dataset streams"
        )
    source_ids = {str(stream.get("source_id", "")).strip() for stream in streams}
    if "" in source_ids:
        raise ContractError(f"dataset '{dataset.get('name', '')}' has stream entries without source_id")
    recorded_source_count = int(workload.get("recorded_source_count", 0) or 0)
    if recorded_source_count != len(source_ids):
        raise ContractError(
            f"scenario '{scenario['name']}' recorded_source_count does not match dataset source_id values"
        )
    if int(dataset.get("logical_stream_instances", 0) or 0) != logical_stream_instances:
        raise ContractError(f"dataset '{dataset.get('name', '')}' logical_stream_instances metadata mismatch")
    if int(dataset.get("unique_recorded_sources", 0) or 0) != recorded_source_count:
        raise ContractError(f"dataset '{dataset.get('name', '')}' unique_recorded_sources metadata mismatch")


def resolve_checkpoint_codec(
    dataset: dict[str, Any], scenario: dict[str, Any]
) -> str | None:
    if scenario.get("name") not in {
        "checkpoint_independent_processes_baseline",
        "checkpoint_video_dag_shared",
    }:
        return None
    codec = str(dataset.get("codec_variant", "")).strip().lower()
    if codec == "hevc":
        codec = "h265"
    if codec not in {"h264", "h265"}:
        raise ContractError(
            "checkpoint dataset codec_variant must be explicitly h264 or h265"
        )
    return codec


def scenario_env_prefix(
    scenario: dict[str, Any],
    *,
    role: str = "local",
    distributed: bool | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    distributed_enabled = (
        bool(scenario.get("distributed", {}).get("enabled")) if distributed is None else bool(distributed)
    )
    env = {
        "EXPERIMENT_SCENARIO_JSON": json.dumps(scenario, separators=(",", ":")),
        "EXPERIMENT_DISTRIBUTED": "1" if distributed_enabled else "0",
        "EXPERIMENT_HOST_ROLE": role,
        "EXPERIMENT_PIPELINE_STAGES": ",".join(scenario.get("pipeline", [])),
    }
    env.update(extra or {})
    return " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())


def detect_gpu_name() -> str:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out.splitlines()[0] if out else "unknown"
    except Exception:
        return "unknown"


def detect_cpu_name() -> str:
    try:
        # macOS
        out = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return out
    except Exception:
        pass

    try:
        # Linux
        out = subprocess.check_output(["lscpu"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if line.lower().startswith("model name:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
    except Exception:
        pass

    try:
        # Linux fallback
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name"):
                    value = line.split(":", 1)[1].strip()
                    if value:
                        return value
    except Exception:
        pass

    try:
        # Windows fallback
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "Name", "/value"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if line.startswith("Name="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    except Exception:
        pass

    return "unknown"


def validate_hardware(
    cfg: dict[str, Any],
    *,
    require_match: bool,
) -> dict[str, Any]:
    detected = detected_hardware_manifest()
    assessment = assess_hardware_target(
        dict(cfg.get("hardware_target") or {}),
        detected,
    )
    print(f"[hardware] detected GPU: {detected['gpu_model']}")
    print(f"[hardware] detected CPU: {detected['cpu_model']}")
    print(f"[hardware] detected RAM: {detected['ram_gb']} GB")
    if not assessment["passed"]:
        message = ", ".join(str(value) for value in assessment["blockers"])
        if require_match:
            raise ContractError(
                "benchmark hardware target mismatch: " + message
            )
        print(f"[warning] hardware target mismatch: {message}")
    return assessment


def emit_runtime_frames_csv(
    frames_csv: Path,
    duration_s: int,
    streams: int,
    min_objects: int,
    max_objects: int,
    deadline_s: float,
    elapsed_s: float,
    run_id: str,
    detector: str,
    backend: str,
) -> None:
    script_path = Path(__file__).resolve().parent / "emit_runtime_frames_csv.py"
    if not script_path.exists():
        raise RuntimeError(f"Runtime frame exporter script is missing: {script_path}")

    source_video = Path(os.environ.get("VIDEO_LAYOUT_DIR", "data/videos")) / "stream01.mp4"
    elapsed_ms = max(float(elapsed_s) * 1000.0, float(duration_s) * 1000.0)

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--output",
            str(frames_csv),
            "--duration-s",
            str(duration_s),
            "--streams",
            str(streams),
            "--elapsed-ms",
            str(elapsed_ms),
            "--source-video",
            str(source_video),
            "--min-objects",
            str(min_objects),
            "--max-objects",
            str(max_objects),
            "--deadline-ms",
            str(deadline_s * 1000.0),
            "--run-id",
            run_id,
            "--detector",
            detector,
            "--backend",
            backend,
        ],
        check=True,
    )


def measured_metrics_duration_s(metrics_csv: Path) -> float:
    if not metrics_csv.exists():
        return 0.0

    try:
        df = pd.read_csv(metrics_csv, usecols=["timestamp_ms"])
        if df.empty:
            return 0.0
        start = int(df["timestamp_ms"].iloc[0])
        end = int(df["timestamp_ms"].iloc[-1])
        if end <= start:
            return 0.0
        return (end - start) / 1000.0
    except Exception:
        return 0.0


def validate_system_metrics(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ContractError(f"system_metrics.csv was not produced: {path}")
    df = pd.read_csv(path)
    required = {"timestamp_ms", "cpu_total_percent", "cpu_memory_mb"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ContractError(f"system_metrics.csv is missing columns at {path}: {', '.join(missing)}")
    if df.empty:
        raise ContractError(f"system_metrics.csv has no samples: {path}")
    return df


def resolve_metric_interval_s(config: dict[str, Any], system_key: str) -> float:
    protocol = config.get("protocol", {})
    base_interval = float(protocol.get("metric_interval_s", 1.0))

    if system_key == "custom_cpp_cuda_qt":
        # Custom app is usually short and bursty; use denser sampling by default.
        return float(protocol.get("custom_cpp_cuda_qt_metric_interval_s", min(base_interval, 0.2)))

    return base_interval


def make_hardware_resource_collector(
    config: dict[str, Any],
    *,
    mode: str,
    system: str,
    scenario: dict[str, Any],
    scenario_name: str,
    policy: str,
    run_dir: Path,
    run_id: str,
    interval_s: float,
    resource_capability_grant: dict[str, Any] | None = None,
) -> HardwareResourceCollector | None:
    if mode != "benchmark" or not bool(scenario.get("topology")):
        return None
    scope = resolve_publication_evidence_bundle_scope(
        config,
        {
            "system": system,
            "scenario": scenario_name,
            "policy": policy,
        },
        resource_capability_grant=resource_capability_grant,
    )
    if scope != FULL_RESOURCE_PUBLICATION_SCOPE:
        return None
    return HardwareResourceCollector(
        run_dir / "hardware_resource_samples.csv",
        run_id=run_id,
        interval_s=interval_s,
    )


def _authoritative_full_resource_summary(
    acceptance: Any,
) -> dict[str, Any]:
    if (
        type(acceptance) is not dict
        or acceptance.get("artifact_kind")
        != "checkpoint_publication_runtime_acceptance"
        or acceptance.get("status") != "accepted_native_checkpoint_arm"
        or type(acceptance.get("summary")) is not dict
        or acceptance.get("acceptance_finalization")
        != {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
        }
    ):
        raise ContractError("checkpoint full-resource finalizer returned invalid acceptance")
    resource = acceptance.get("full_resource_summary")
    if (
        type(resource) is not dict
        or type(resource.get("resource_contract_version")) is not int
        or resource["resource_contract_version"] != 2
        or resource.get("evidence_accepted") is not True
        or resource.get("publication_bundle_bound") is not True
        or resource.get("full_resource_coverage_complete") is not True
    ):
        raise ContractError("checkpoint finalized full-resource summary is not accepted")
    integer_fields = (
        "nvdec_busy_equivalent_ns",
        "fanout_thread_cpu_time_ns",
        "fanout_work_units",
    )
    if any(
        type(resource.get(field)) is not int or resource[field] < 0
        for field in integer_fields
    ):
        raise ContractError("checkpoint finalized full-resource counters are invalid")
    if (
        resource.get("nvdec_counter_scope") != "device_sample"
        or resource.get("fanout_counter_scope") != "per_trace_resource_work"
    ):
        raise ContractError("checkpoint finalized full-resource counter scope drifted")
    return {
        "resource_contract_version": resource["resource_contract_version"],
        "full_resource_evidence_accepted": resource["evidence_accepted"],
        "full_resource_coverage_complete": resource[
            "full_resource_coverage_complete"
        ],
        "nvdec_busy_equivalent_ns": resource["nvdec_busy_equivalent_ns"],
        "nvdec_counter_scope": resource["nvdec_counter_scope"],
        "fanout_thread_cpu_time_ns": resource["fanout_thread_cpu_time_ns"],
        "fanout_work_units": resource["fanout_work_units"],
        "fanout_counter_scope": resource["fanout_counter_scope"],
    }


def write_durable_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace JSON after flushing its bytes before acceptance commit."""

    serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        with path.open("rb+") as persisted:
            os.fsync(persisted.fileno())
        if os.name != "nt":
            directory_descriptor: int | None = None
            try:
                directory_descriptor = os.open(
                    path.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                os.fsync(directory_descriptor)
            except OSError:
                # Some mounted filesystems do not expose directory fsync. The
                # file itself is still flushed before and after atomic replace.
                pass
            finally:
                if directory_descriptor is not None:
                    os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def checkpoint_full_resource_acceptance_transaction(
    *,
    full_resource_required: bool,
    mode: str,
    scenario: dict[str, Any],
    checkpoint_codec: str | None,
    hardware_collector: HardwareResourceCollector | None,
    hardware_collector_started: bool,
    hardware_collector_closed: bool,
    output_dir: Path,
    expected_run_id: str,
    expected_system: str,
    expected_policy: str,
    expected_deadline_ms: float,
    run_metadata_path: Path,
    expected_execution_binding: dict[str, Any],
) -> Iterator[dict[str, Any] | None]:
    """Prepare one arm, then commit acceptance only after the body succeeds."""

    if not full_resource_required:
        yield None
        return
    scenario_name = str(scenario.get("name", ""))
    topology = scenario.get("topology") or {}
    if (
        mode != "benchmark"
        or scenario_name
        not in {
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        }
        or not bool(topology)
        or checkpoint_codec is None
    ):
        raise ContractError(
            "full-resource acceptance requires an exact checkpoint benchmark topology"
        )
    if hardware_collector is None:
        raise ContractError("full-resource acceptance requires a hardware collector")
    if not hardware_collector_started:
        raise ContractError(
            "hardware collector must have started before full-resource acceptance"
        )
    if not hardware_collector_closed:
        raise ContractError(
            "hardware collector must be closed and failure-checked before acceptance"
        )
    if hardware_collector.is_alive():
        raise ContractError("hardware collector is still alive before acceptance")

    acceptance_path = output_dir / "checkpoint_publication_acceptance.json"
    if acceptance_path.exists():
        raise ContractError("final checkpoint acceptance already exists")
    acceptance = prepare_checkpoint_publication_acceptance(
        output_dir=output_dir,
        expected_run_id=expected_run_id,
        expected_system=expected_system,
        expected_scenario=scenario_name,
        expected_codec=checkpoint_codec,
        expected_policy=expected_policy,
        expected_deadline_ms=float(expected_deadline_ms),
        topology_kind=str(topology.get("kind", "")),
        hardware_collector_stopped=True,
    )
    finalized_summary = _authoritative_full_resource_summary(acceptance)
    yield finalized_summary
    commit_checkpoint_publication_acceptance(
        output_dir=output_dir,
        acceptance=acceptance,
        run_metadata_path=run_metadata_path,
        expected_execution_binding=expected_execution_binding,
    )


_BENCHMARK_CHILD_SECRET_ENV = {
    "VAST_SEAFILE_UPLOAD_LINK",
    "VAST_SEAFILE_READ_LINK",
}


def benchmark_child_environment(*, run_seed: int, repeat_index: int) -> dict[str, str]:
    child_env = os.environ.copy()
    for name in _BENCHMARK_CHILD_SECRET_ENV:
        child_env.pop(name, None)
    child_env["EXPERIMENT_RUN_SEED"] = str(run_seed)
    child_env["EXPERIMENT_REPEAT_INDEX"] = str(repeat_index)
    return child_env


def configured_system_names(config: dict[str, Any], requested: list[str], *, mode: str) -> list[str]:
    configured = list(config.get("systems", {}))
    selected = configured if requested == ["all"] else list(requested)
    unknown = sorted(set(selected) - set(configured))
    if unknown:
        raise ContractError(f"unknown systems: {', '.join(unknown)}")
    if mode != "benchmark":
        return selected

    diagnostic = [
        name
        for name in selected
        if str(config["systems"][name].get("benchmark_status", "supported")) == "diagnostic_only"
    ]
    if requested != ["all"] and diagnostic:
        reasons = "; ".join(
            f"{name}: {config['systems'][name].get('benchmark_reason', 'diagnostic-only adapter')}"
            for name in diagnostic
        )
        raise ContractError(f"diagnostic-only systems cannot run in benchmark mode: {reasons}")
    return [name for name in selected if name not in diagnostic]


def adapter_manifest(system_config: dict[str, Any]) -> dict[str, Any]:
    image = str(system_config.get("container_image", "")).strip()
    digest = ""
    if image:
        try:
            digest = subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            digest = "unavailable"
    return {
        "detector": system_config.get("detector", ""),
        "backend": system_config.get("backend", ""),
        "container_image": image,
        "container_digest": digest,
    }


def detected_hardware_manifest() -> dict[str, Any]:
    return {
        "gpu_model": detect_gpu_name(),
        "cpu_model": detect_cpu_name(),
        "ram_gb": round(psutil.virtual_memory().total / (1024**3), 3),
    }


def build_run_seed(
    base_seed: int,
    scenario_key: str,
    variant_name: str,
    streams: int,
    repeat_index: int,
) -> int:
    payload = f"{base_seed}:{scenario_key}:{variant_name}:{streams}:{repeat_index}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % (2**31 - 1)


def dataset_streams_json(dataset: dict[str, Any]) -> str:
    streams = []
    for stream in dataset.get("streams", []):
        rel_path = str(stream.get("path", "")).strip()
        abs_path = str(stream.get("absolute_path", "")).strip()
        streams.append(rel_path or abs_path)
    return json.dumps(streams, separators=(",", ":"))


def configured_deadlines_ms(
    config: dict[str, Any],
    *,
    mode: str,
    requested: list[str] | None = None,
) -> list[float]:
    benchmark = config.get("benchmark", {})
    if requested and requested != ["all"]:
        values = requested
    elif mode == "benchmark":
        values = benchmark.get("deadline_ms") or benchmark.get("report_deadline_ms") or []
    else:
        values = benchmark.get("smoke_deadline_ms") or []
    if not values:
        values = [float(config.get("hardware_target", {}).get("deadline_s", 0.1)) * 1000.0]
    deadlines = [float(value) for value in values]
    if any(value <= 0 for value in deadlines):
        raise ContractError("benchmark deadlines must be positive milliseconds")
    return deadlines


def configured_policy_names(config: dict[str, Any], requested: list[str] | None) -> list[str]:
    benchmark = config.get("benchmark", {})
    configured = [str(policy) for policy in benchmark.get("scheduler_policies", [])]
    ablations = [str(policy) for policy in benchmark.get("scheduler_ablations", [])]
    all_policies = list(dict.fromkeys([*configured, *ablations]))
    if not all_policies:
        raise ContractError("benchmark.scheduler_policies must be a non-empty list")
    if not requested or requested == ["all"]:
        return all_policies
    unknown = [policy for policy in requested if policy not in all_policies]
    if unknown:
        raise ContractError(
            f"unknown scheduler policies: {', '.join(unknown)}; expected one of: {', '.join(all_policies)}"
        )
    return list(requested)


def configured_dataset_names(
    config: dict[str, Any],
    *,
    mode: str,
    dataset: str,
    datasets: list[str] | None,
) -> list[str]:
    benchmark = config.get("benchmark", {})
    defaults = benchmark.get("default_dataset", {})
    requested = [str(name) for name in (datasets or []) if str(name).strip()]
    if not requested and dataset:
        requested = [dataset]
    if requested == ["all"]:
        requested = [str(name) for name in benchmark.get("benchmark_datasets", [])]
    if not requested:
        if mode == "benchmark":
            requested = [str(name) for name in benchmark.get("benchmark_datasets", [])]
        if not requested:
            requested = [str(defaults.get(mode, ""))]
    requested = [name for name in requested if name]
    if not requested:
        raise ContractError(f"no dataset configured for mode={mode}")
    return list(dict.fromkeys(requested))


def deadline_slug(deadline_ms: float) -> str:
    text = f"{float(deadline_ms):g}".replace(".", "p")
    return f"deadline_{text}"


def run_directory(
    run_root: Path,
    scenario: dict[str, Any],
    streams: int,
    system_key: str,
    repeat_index: int,
    deadline_ms: float | None = None,
    dataset_name: str | None = None,
    policy: str | None = None,
) -> Path:
    root = run_root
    if dataset_name:
        root /= f"dataset_{dataset_name}"
    if policy:
        root /= f"policy_{policy}"
    scenario_dir = root / scenario["name"]
    variant_name = str(scenario.get("workload", {}).get("variant", "")).strip()
    if variant_name:
        scenario_dir /= f"variant_{variant_name}"
    streams_dir = scenario_dir / f"streams_{streams}"
    if deadline_ms is not None:
        streams_dir /= deadline_slug(deadline_ms)
    return streams_dir / system_key / f"rep_{repeat_index:02d}"


def load_resumable_result(
    metadata_path: Path,
    *,
    system_key: str,
    scenario_key: str,
    repeat_index: int,
    streams: int,
    duration_s: int,
    policy: str,
    dataset_name: str,
    mode: str,
    deadline_ms: float | None = None,
    scenario_contract: dict[str, Any] | None = None,
    dataset_contract: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    base_seed: int | None = None,
    run_seed: int | None = None,
    primary_architecture_pair: dict[str, Any] | None = None,
    primary_policy_pair: dict[str, Any] | None = None,
    resource_capability_grant: dict[str, Any] | None = None,
    backend_runtime_grant: dict[str, Any] | None = None,
    model_parity_grant: dict[str, Any] | None = None,
    expected_execution_binding: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not metadata_path.exists():
        return None
    try:
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read resumable metadata {metadata_path}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ContractError(f"resumable metadata must be a mapping at {metadata_path}")
    result = metadata.get("result")
    if not isinstance(result, dict) or result.get("status") != "completed":
        return None
    metadata_mode = metadata.get("mode")
    result_mode = result.get("run_mode")
    if metadata_mode != mode or result_mode != mode or metadata_mode != result_mode:
        raise ContractError(
            f"resumable metadata mode does not match requested run at {metadata_path}: "
            f"requested={mode}, metadata={metadata_mode}, result={result_mode}"
        )
    expected = {
        "system": system_key,
        "scenario": scenario_key,
        "repeat": repeat_index,
        "streams": streams,
        "duration_s": duration_s,
        "policy": policy,
        "dataset": dataset_name,
        "run_mode": mode,
    }
    if deadline_ms is not None:
        expected["deadline_ms"] = float(deadline_ms)
    if base_seed is not None:
        expected["seed"] = int(base_seed)
    if run_seed is not None:
        expected["run_seed"] = int(run_seed)
    mismatches = [key for key, value in expected.items() if result.get(key) != value]
    if mismatches:
        raise ContractError(
            f"resumable metadata does not match requested run at {metadata_path}: {', '.join(mismatches)}"
        )
    stored_architecture_pair = metadata.get("primary_architecture_pair")
    stored_policy_pair = metadata.get("primary_policy_pair")
    if primary_architecture_pair is not None and primary_policy_pair is not None:
        raise ContractError(
            "resumable primary architecture and policy pair contracts are mutually exclusive"
        )
    if stored_architecture_pair is not None and stored_policy_pair is not None:
        raise ContractError(
            f"resumable metadata contains mutually exclusive pair contracts at {metadata_path}"
        )
    if any(
        value is not None
        for value in (
            primary_architecture_pair,
            primary_policy_pair,
            stored_architecture_pair,
            stored_policy_pair,
        )
    ) and mode != "benchmark":
        raise ContractError(
            f"resumable primary pair metadata is valid only in benchmark mode at {metadata_path}"
        )

    if primary_architecture_pair is None:
        if stored_architecture_pair is not None:
            raise ContractError(
                f"resumable metadata has an unexpected primary architecture pair contract at {metadata_path}"
            )
    else:
        if config is None or deadline_ms is None:
            raise ContractError(
                "resumable primary architecture pair validation requires configuration and deadline_ms"
            )
        expected_architecture_pair = validate_primary_architecture_pair_run_contract(
            config,
            system=system_key,
            scenario=scenario_key,
            policy=policy,
            dataset=dataset_name,
            deadline_ms=float(deadline_ms),
            streams=int(streams),
            repeat=repeat_index,
            metadata=primary_architecture_pair,
        )
        if stored_architecture_pair != expected_architecture_pair:
            raise ContractError(
                f"resumable primary architecture pair metadata drift at {metadata_path}"
            )

    if primary_policy_pair is None:
        if stored_policy_pair is not None:
            raise ContractError(
                f"resumable metadata has an unexpected primary policy pair contract at {metadata_path}"
            )
    else:
        if config is None or deadline_ms is None:
            raise ContractError(
                "resumable primary policy pair validation requires configuration and deadline_ms"
            )
        expected_policy_pair = validate_primary_policy_pair_run_contract(
            config,
            system=system_key,
            scenario=scenario_key,
            policy=policy,
            dataset=dataset_name,
            deadline_ms=float(deadline_ms),
            streams=int(streams),
            repeat=repeat_index,
            metadata=primary_policy_pair,
        )
        if stored_policy_pair != expected_policy_pair:
            raise ContractError(
                f"resumable primary policy pair metadata drift at {metadata_path}"
            )
    if scenario_contract is not None:
        expected_scenario_identity = scenario_contract_identity(scenario_contract)
        metadata_scenario = metadata.get("resolved_scenario")
        declared_scenario_identity = metadata.get("scenario_contract_identity")
        scenario_mismatches = []
        if not isinstance(metadata_scenario, dict):
            scenario_mismatches.append("resolved_scenario")
        elif (
            scenario_contract_identity(metadata_scenario)["sha256"]
            != expected_scenario_identity["sha256"]
        ):
            scenario_mismatches.append("resolved_scenario_sha256")
        if not isinstance(declared_scenario_identity, dict):
            scenario_mismatches.append("scenario_contract_identity")
        else:
            if (
                declared_scenario_identity.get("schema_version")
                != expected_scenario_identity["schema_version"]
            ):
                scenario_mismatches.append("scenario_contract_identity_schema_version")
            if (
                declared_scenario_identity.get("sha256")
                != expected_scenario_identity["sha256"]
            ):
                scenario_mismatches.append("scenario_contract_identity_sha256")
        if scenario_mismatches:
            raise ContractError(
                f"resumable metadata scenario contract drift at {metadata_path}: "
                + ", ".join(scenario_mismatches)
            )
    if dataset_contract is not None:
        expected_dataset_identity = dataset_manifest_identity(dataset_contract)
        metadata_dataset = metadata.get("dataset")
        dataset_mismatches = []
        if not isinstance(metadata_dataset, dict):
            dataset_mismatches.append("dataset")
        else:
            if (
                metadata_dataset.get("manifest_identity_schema_version")
                != expected_dataset_identity["schema_version"]
            ):
                dataset_mismatches.append("manifest_identity_schema_version")
            if (
                metadata_dataset.get("manifest_identity_sha256")
                != expected_dataset_identity["sha256"]
            ):
                dataset_mismatches.append("manifest_identity_sha256")
            if (
                dataset_manifest_identity(metadata_dataset)["sha256"]
                != expected_dataset_identity["sha256"]
            ):
                dataset_mismatches.append("dataset_manifest_sha256")
            if metadata_dataset.get("aggregate_sha256") != dataset_contract.get(
                "aggregate_sha256"
            ):
                dataset_mismatches.append("aggregate_sha256")
        if dataset_mismatches:
            raise ContractError(
                f"resumable metadata dataset contract drift at {metadata_path}: "
                + ", ".join(dataset_mismatches)
            )
    if config is not None:
        stored_contract = metadata.get("publication_run_contract")
        stored_arm_authority = (
            stored_contract.get("backend_publication_arm_contract_authority")
            if type(stored_contract) is dict
            else None
        )
        stored_receipt_authority = (
            stored_contract.get("backend_publication_output_receipt_authority")
            if type(stored_contract) is dict
            else None
        )
        expected_publication_contract = resolve_publication_run_contract(
            config,
            result,
            resource_capability_grant=resource_capability_grant,
            backend_runtime_grant=backend_runtime_grant,
            model_parity_grant=model_parity_grant,
            full_publication_execution_binding=expected_execution_binding,
            backend_publication_arm_contract_authority=stored_arm_authority,
            backend_publication_output_receipt_authority=(
                stored_receipt_authority
            ),
        )
        expected_publication_identity = publication_run_contract_identity(
            expected_publication_contract
        )
        metadata_publication_contract = metadata.get("publication_run_contract")
        declared_publication_identity = metadata.get(
            "publication_run_contract_identity"
        )
        publication_mismatches = []
        if not isinstance(metadata_publication_contract, dict):
            publication_mismatches.append("publication_run_contract")
        elif (
            publication_run_contract_identity(metadata_publication_contract)["sha256"]
            != expected_publication_identity["sha256"]
        ):
            publication_mismatches.append("publication_run_contract_sha256")
        if not isinstance(declared_publication_identity, dict):
            publication_mismatches.append("publication_run_contract_identity")
        else:
            if (
                declared_publication_identity.get("schema_version")
                != expected_publication_identity["schema_version"]
            ):
                publication_mismatches.append(
                    "publication_run_contract_identity_schema_version"
                )
            if (
                declared_publication_identity.get("sha256")
                != expected_publication_identity["sha256"]
            ):
                publication_mismatches.append(
                    "publication_run_contract_identity_sha256"
                )
        if publication_mismatches:
            raise ContractError(
                f"resumable metadata publication run contract drift at {metadata_path}: "
                + ", ".join(publication_mismatches)
            )
    if (
        mode == "benchmark"
        and isinstance(scenario_contract, dict)
        and bool(scenario_contract.get("topology"))
    ):
        if config is None:
            raise ContractError(
                "resumable topology benchmark validation requires configuration"
            )
        expected_evidence_scope = resolve_publication_evidence_bundle_scope(
            config,
            result,
            resource_capability_grant=resource_capability_grant,
        )
        try:
            validate_publication_evidence_bundle(
                metadata_path.parent,
                metadata.get("publication_evidence_bundle"),
                metadata.get("publication_evidence_bundle_identity"),
                expected_scope=expected_evidence_scope,
                expected_policy=str(result.get("policy", "")),
            )
            if expected_evidence_scope == FULL_RESOURCE_PUBLICATION_SCOPE:
                if resource_capability_grant is None:
                    raise ContractError(
                        "full-resource resume requires the pre-run resource capability grant"
                    )
                if backend_runtime_grant is None:
                    raise ContractError(
                        "full-resource resume requires the pre-run backend runtime grant"
                    )
                if model_parity_grant is None:
                    raise ContractError(
                        "full-resource resume requires the pre-run model-parity grant"
                    )
                if expected_execution_binding is None:
                    raise ContractError(
                        "full-resource resume requires the immutable execution binding"
                    )
                acceptance_path = metadata_path.parent / "checkpoint_publication_acceptance.json"
                if acceptance_path.is_symlink() or not acceptance_path.is_file():
                    raise ContractError("final full-resource checkpoint acceptance is missing")
                try:
                    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ContractError(
                        f"final full-resource checkpoint acceptance is invalid: {exc}"
                    ) from exc
                expected_acceptance = {
                    "schema_version": 2,
                    "artifact_kind": "checkpoint_publication_runtime_acceptance",
                    "status": "accepted_native_checkpoint_arm",
                    "system": result.get("system"),
                    "scenario": result.get("scenario"),
                    "policy": result.get("policy"),
                }
                if type(acceptance) is not dict or any(
                    acceptance.get(field) != value
                    for field, value in expected_acceptance.items()
                ):
                    raise ContractError("final full-resource checkpoint acceptance identity drift")
                try:
                    validate_checkpoint_acceptance_metadata_binding(
                        acceptance,
                        run_metadata_path=metadata_path,
                        expected_execution_binding=expected_execution_binding,
                    )
                except AcceptanceMetadataBindingError as exc:
                    raise ContractError(
                        f"final full-resource checkpoint acceptance metadata binding drift: {exc}"
                    ) from exc
                evidence = acceptance.get("evidence_sha256")
                expected_files = set(
                    accepted_arm_evidence_files(policy, full_resource=True)
                )
                if type(evidence) is not dict or set(evidence) != expected_files:
                    raise ContractError("final full-resource checkpoint acceptance evidence set drift")
                for name, digest in evidence.items():
                    evidence_path = metadata_path.parent / name
                    if (
                        type(digest) is not str
                        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                        or evidence_path.is_symlink()
                        or not evidence_path.is_file()
                        or sha256_file(evidence_path) != digest
                    ):
                        raise ContractError(
                            f"final full-resource checkpoint acceptance evidence drift: {name}"
                        )
                if acceptance.get("acceptance_finalization") != {
                    "hardware_collector_stopped": True,
                    "validation": "full_resource_evidence_v2_passed",
                }:
                    raise ContractError("final full-resource checkpoint acceptance is not finalized")
        except ContractError as exc:
            raise ContractError(
                f"resumable metadata publication evidence bundle drift at {metadata_path}: {exc}"
            ) from exc
    try:
        validate_summary_rows([result])
    except ContractError as exc:
        raise ContractError(f"resumable metadata uses an incompatible summary schema at {metadata_path}: {exc}") from exc
    return result


def failed_result_row(
    *,
    config: dict[str, Any],
    dataset: dict[str, Any],
    system_key: str,
    scenario: dict[str, Any],
    streams: int,
    duration_s: int,
    repeat_index: int,
    execution_context: ExecutionContext,
    policy: str,
    deadline_ms: float,
    mode: str,
    error: BaseException,
) -> dict[str, Any]:
    system_config = config["systems"].get(system_key, {})
    adapter = system_config.get("adapter") or {}
    distributed_enabled = bool(scenario.get("distributed", {}).get("enabled", False))
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": system_key,
        "scenario": scenario["name"],
        "repeat": repeat_index,
        "exit_code": 2,
        "status": "failed",
        "run_mode": mode,
        "skip_reason": str(error).replace("\n", " ")[:500],
        "streams": streams,
        "duration_s": duration_s,
        "scenario_variant": str(scenario.get("workload", {}).get("variant", "")).strip(),
        "placement_policy": scenario.get("placement", {}).get("policy", ""),
        "distributed": distributed_enabled,
        "deployment_mode": execution_context.deployment_mode,
        "host_topology": execution_context.host_topology,
        "host_role": "distributed" if distributed_enabled else "local",
        "detector": str(adapter.get("detector", "")),
        "backend": str(adapter.get("backend", "")),
        "policy": policy,
        "dataset": dataset["name"],
        "deadline_ms": float(deadline_ms),
        "throughput_fps": 0.0,
        "latency_p50_ms": 0.0,
        "latency_p95_ms": 0.0,
        "latency_p99_ms": 0.0,
        "slo_violation_rate_percent": 0.0,
        "frames": 0,
        "telemetry_source": "",
    }
    validate_summary_rows([result])
    return result


def build_backend_publication_arm_contract(
    *,
    dispatch_resolution: dict[str, Any],
    execution_binding: dict[str, Any],
    resource_capability_grant: dict[str, Any],
    model_parity_grant: dict[str, Any],
    dataset: dict[str, Any],
    scenario: dict[str, Any],
    run_id: str,
    run_seed: int,
    streams: int,
    duration_s: int,
    repeat_index: int,
    base_seed: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Build the closed, self-hashed input consumed by a dedicated launcher."""

    resource_grant_sha = resource_capability_grant.get("grant_sha256")
    parity_grant_sha = model_parity_grant.get("grant_sha256")
    parity_acceptance_sha = model_parity_grant.get(
        "parity_acceptance_binding_sha256"
    )
    if (
        type(resource_grant_sha) is not str
        or len(resource_grant_sha) != 64
        or any(character not in "0123456789abcdef" for character in resource_grant_sha)
    ):
        raise ContractError(
            "backend publication dispatch requires an exact resource grant identity"
        )
    if (
        type(parity_grant_sha) is not str
        or len(parity_grant_sha) != 64
        or any(character not in "0123456789abcdef" for character in parity_grant_sha)
        or type(parity_acceptance_sha) is not str
        or len(parity_acceptance_sha) != 64
        or any(
            character not in "0123456789abcdef"
            for character in parity_acceptance_sha
        )
    ):
        raise ContractError(
            "backend publication dispatch requires an exact model-parity grant identity"
        )
    material = {
        "schema_version": 2,
        "artifact_kind": "vast_backend_publication_arm_dispatch_contract",
        "full_publication_execution_binding": json.loads(
            json.dumps(execution_binding, sort_keys=True)
        ),
        "resource_capability_grant_sha256": resource_grant_sha,
        "model_parity_grant_sha256": parity_grant_sha,
        "model_parity_acceptance_binding_sha256": parity_acceptance_sha,
        "backend_runtime_grant_sha256": dispatch_resolution[
            "backend_runtime_grant_sha256"
        ],
        "identity_artifact_binding_sha256": dispatch_resolution[
            "identity_artifact_binding_sha256"
        ],
        "dispatch_resolution": json.loads(
            json.dumps(dispatch_resolution, sort_keys=True)
        ),
        "runtime_inputs": {
            "system": dispatch_resolution["system"],
            "scenario": str(scenario["name"]),
            "topology_kind": dispatch_resolution["topology_kind"],
            "codec": dispatch_resolution["codec"],
            "policy": dispatch_resolution["policy"],
            "deadline_ms": dispatch_resolution["deadline_ms"],
            "dataset": json.loads(json.dumps(dataset, sort_keys=True)),
            "streams": int(streams),
            "duration_s": int(duration_s),
            "repeat_index": int(repeat_index),
            "base_seed": int(base_seed),
            "run_seed": int(run_seed),
            "run_id": str(run_id),
            "output_dir": str(Path(output_dir).resolve()),
        },
        "launcher_output_protocol": launcher_output_protocol(
            dispatch_resolution["policy"]
        ),
    }
    material["contract_sha256"] = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return material


def run_one(
    config: dict[str, Any],
    dataset: dict[str, Any],
    system_key: str,
    scenario: dict[str, Any],
    streams: int,
    min_objects: int,
    max_objects: int,
    duration_s: int,
    repeat_index: int,
    run_root: Path,
    execution_context: ExecutionContext,
    mode: str,
    policy: str,
    deadline_ms: float,
    base_seed: int,
    dry_run_plan: bool,
    directory_dataset_name: str | None = None,
    directory_policy: str | None = None,
    primary_architecture_pair: dict[str, Any] | None = None,
    primary_policy_pair: dict[str, Any] | None = None,
    *,
    resource_capability_grant: dict[str, Any] | None = None,
    backend_runtime_grant: dict[str, Any] | None = None,
    model_parity_grant: dict[str, Any] | None = None,
    full_publication_execution_binding: dict[str, Any] | None = None,
    full_publication_identity_artifacts: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    if backend_runtime_grant is not None and project_root is None:
        raise ContractError(
            "backend publication dispatch requires an explicit caller project_root"
        )
    caller_project_root = (
        PROJECT_ROOT if project_root is None else Path(project_root).resolve(strict=True)
    )
    if not caller_project_root.is_dir():
        raise ContractError("caller project_root is not a directory")
    protocol = config["protocol"]
    scenario_key = scenario["name"]
    resolved_scenario_identity = scenario_contract_identity(scenario)
    system_config = config["systems"][system_key]
    resolved_backend_runtime_grant: dict[str, Any] | None = None
    resolved_model_parity_grant: dict[str, Any] | None = None
    resolved_execution_binding: dict[str, Any] | None = None
    if backend_runtime_grant is not None:
        try:
            resolved_backend_runtime_grant = (
                validate_pre_run_backend_runtime_grant(backend_runtime_grant)
            )
        except BackendRuntimeGrantError as error:
            raise ContractError(f"invalid pre-run backend runtime grant: {error}") from error
    if model_parity_grant is not None:
        try:
            resolved_model_parity_grant = validate_pre_run_model_parity_grant(
                model_parity_grant
            )
        except ModelParityGrantError as error:
            raise ContractError(f"invalid pre-run model-parity grant: {error}") from error
    if full_publication_execution_binding is not None:
        try:
            resolved_execution_binding = validate_full_publication_execution_binding(
                full_publication_execution_binding
            )
        except AcceptanceMetadataBindingError as error:
            raise ContractError(
                f"invalid full-publication execution binding: {error}"
            ) from error
    backend_dispatch_resolution: dict[str, Any] | None = None
    if resolved_backend_runtime_grant is not None:
        if type(full_publication_identity_artifacts) is not dict:
            raise ContractError(
                "backend publication dispatch requires validated identity artifacts"
            )
        try:
            identity_grant = backend_runtime_grant_from_identity_artifacts(
                full_publication_identity_artifacts
            )
        except BackendRuntimeGrantError as error:
            raise ContractError(
                f"backend publication identity artifacts are invalid: {error}"
            ) from error
        if identity_grant != resolved_backend_runtime_grant:
            raise ContractError(
                "backend runtime grant differs from validated identity artifacts"
            )
        if resolved_model_parity_grant is None:
            raise ContractError(
                "backend publication dispatch requires a validated model-parity grant"
            )
        try:
            identity_parity_grant = model_parity_grant_from_identity_artifacts(
                full_publication_identity_artifacts
            )
        except ModelParityGrantError as error:
            raise ContractError(
                f"model-parity identity artifacts are invalid: {error}"
            ) from error
        if identity_parity_grant != resolved_model_parity_grant:
            raise ContractError(
                "model-parity grant differs from validated identity artifacts"
            )
        grant_identities = {
            resource_capability_grant.get("identity_artifact_binding_sha256")
            if type(resource_capability_grant) is dict else None,
            resolved_backend_runtime_grant["identity_artifact_binding_sha256"],
            resolved_model_parity_grant["identity_artifact_binding_sha256"],
            full_publication_identity_artifacts.get("binding_sha256"),
        }
        if len(grant_identities) != 1 or None in grant_identities:
            raise ContractError(
                "resource/backend/model-parity grants differ from validated identity artifacts"
            )
        if (
            resolved_backend_runtime_grant["upstream_identities"][
                "model_parity_acceptance_binding_sha256"
            ]
            != resolved_model_parity_grant[
                "parity_acceptance_binding_sha256"
            ]
        ):
            raise ContractError(
                "backend and model-parity grants bind different parity acceptances"
            )
        if resolved_execution_binding is None:
            raise ContractError(
                "backend publication dispatch requires an immutable execution binding"
            )
        checkpoint_codec_probe = resolve_checkpoint_codec(dataset, scenario)
        if checkpoint_codec_probe is None:
            raise ContractError(
                "backend publication dispatch requires an exact checkpoint codec"
            )
        try:
            backend_dispatch_resolution = BackendPublicationDispatchResolver(
                resolved_backend_runtime_grant
            ).resolve(
                system=system_key,
                scenario=str(scenario["name"]),
                codec=checkpoint_codec_probe,
                policy=policy,
                deadline_ms=deadline_ms,
            )
        except BackendPublicationDispatchError as error:
            raise ContractError(
                f"backend publication dispatch is blocked: {error}"
            ) from error
    if primary_architecture_pair is not None and primary_policy_pair is not None:
        raise ContractError(
            "primary architecture and policy pair metadata are mutually exclusive"
        )
    if (
        primary_architecture_pair is not None
        or primary_policy_pair is not None
    ) and mode != "benchmark":
        raise ContractError("primary pair metadata is valid only in benchmark mode")
    if execution_context.distributed_enabled and not bool(system_config.get("supports_distributed", False)):
        raise ContractError(f"system '{system_key}' does not support distributed execution")
    benchmark_adapter = validate_benchmark_adapter(
        system_key=system_key,
        scenario=scenario,
        distributed=execution_context.distributed_enabled,
        mode=mode,
        backend_dispatch=backend_dispatch_resolution,
    )
    resolved_primary_architecture_pair: dict[str, Any] | None = None
    if primary_architecture_pair is not None:
        resolved_primary_architecture_pair = validate_primary_architecture_pair_run_contract(
            config,
            system=system_key,
            scenario=str(scenario["name"]),
            policy=policy,
            dataset=str(dataset["name"]),
            deadline_ms=float(deadline_ms),
            streams=int(streams),
            repeat=repeat_index,
            metadata=primary_architecture_pair,
        )

    resolved_primary_policy_pair: dict[str, Any] | None = None
    if primary_policy_pair is not None:
        readiness = assess_primary_policy_runtime_compatibility(config)
        if not readiness["passed"]:
            raise ContractError(
                "primary policy execution is blocked by runtime compatibility: "
                + ", ".join(str(value) for value in readiness["blockers"])
            )
        resolved_primary_policy_pair = validate_primary_policy_pair_run_contract(
            config,
            system=system_key,
            scenario=str(scenario["name"]),
            policy=policy,
            dataset=str(dataset["name"]),
            deadline_ms=float(deadline_ms),
            streams=int(streams),
            repeat=repeat_index,
            metadata=primary_policy_pair,
        )
    if mode == "benchmark":
        validate_checkpoint_workload(dataset, scenario)
    detector = str(system_config.get("detector", system_key))
    backend = str(system_config.get("backend", system_key))
    variant_name = str(scenario.get("workload", {}).get("variant", "")).strip()
    seed_key = str(scenario.get("workload", {}).get("seed_group", scenario_key))
    run_seed = build_run_seed(base_seed, seed_key, variant_name, streams, repeat_index)
    run_id = "-".join(
        part
        for part in (
            run_root.name,
            scenario_key,
            variant_name,
            f"streams{streams}",
            dataset["name"],
            policy,
            deadline_slug(deadline_ms),
            system_key,
            f"rep{repeat_index:02d}",
        )
        if part
    )

    scenario_dir = run_directory(
        run_root,
        scenario,
        streams,
        system_key,
        repeat_index,
        deadline_ms,
        directory_dataset_name,
        directory_policy,
    )
    if not dry_run_plan:
        scenario_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = scenario_dir / "system_metrics.csv"
    frames_path = scenario_dir / "frames.csv"
    frame_events_path = scenario_dir / "frame_events.csv"
    topology_events_path = scenario_dir / "topology_events.csv"
    network_path = scenario_dir / "network_metrics.csv"
    metadata_path = scenario_dir / "run_metadata.json"

    metric_interval_s = resolve_metric_interval_s(config, system_key)
    collector = MetricsCollector(metrics_path, interval_s=metric_interval_s)
    hardware_collector = make_hardware_resource_collector(
        config,
        mode=mode,
        system=system_key,
        scenario=scenario,
        scenario_name=scenario_key,
        policy=policy,
        run_dir=scenario_dir,
        run_id=run_id,
        interval_s=metric_interval_s,
        resource_capability_grant=resource_capability_grant,
    )
    full_resource_required = hardware_collector is not None
    if full_resource_required and resolved_backend_runtime_grant is None:
        raise ContractError(
            "full-resource publication requires a validated pre-run backend runtime grant"
        )
    if full_resource_required and resolved_execution_binding is None:
        raise ContractError(
            "full-resource publication requires an immutable execution binding"
        )
    if backend_dispatch_resolution is not None and not full_resource_required:
        raise ContractError(
            "backend publication dispatch requires verified full-resource collection"
        )
    if full_resource_required and backend_dispatch_resolution is None:
        raise ContractError(
            "full-resource publication requires an exact backend dispatch resolution"
        )

    command_template: str | None = None
    base_cmd: str | None = None
    if backend_dispatch_resolution is None:
        command_template = str(system_config["command"])
        base_cmd = command_template.format(
            scenario=scenario_key,
            duration_s=duration_s,
            streams=streams,
            min_objects=min_objects,
            max_objects=max_objects,
            output_dir=scenario_dir,
            deadline_ms=deadline_ms,
        )
    video_layout_dir = str(Path(dataset["streams"][0]["absolute_path"]).parent)
    ql_heft_artifact = str(config.get("benchmark", {}).get("ql_heft_policy_artifact", ""))
    if ql_heft_artifact:
        ql_heft_path = Path(ql_heft_artifact)
        ql_heft_artifact = str(
            ql_heft_path
            if ql_heft_path.is_absolute()
            else caller_project_root / ql_heft_path
        )
    distributed_enabled = execution_context.distributed_enabled
    cmd_timeout_env = os.environ.get("EXPERIMENT_CMD_TIMEOUT_S", "").strip()
    if cmd_timeout_env:
        cmd_timeout_s = int(cmd_timeout_env)
    else:
        cmd_timeout_s = default_command_timeout_s(
            system_key=system_key,
            duration_s=int(duration_s),
            distributed_enabled=distributed_enabled,
            mode=mode,
        )
    command_env = {
        "ADAPTER_BACKEND": backend,
        "ADAPTER_DETECTOR": detector,
        "BENCHMARK_MODE": mode,
        "CMD_TIMEOUT_S": str(cmd_timeout_s),
        "DATASET_NAME": dataset["name"],
        "DATASET_STREAMS_JSON": dataset_streams_json(dataset),
        "EXPERIMENT_REPEAT_INDEX": str(repeat_index),
        "EXPERIMENT_RUN_ID": run_id,
        "EXPERIMENT_RUN_SEED": str(run_seed),
        "QL_HEFT_POLICY_ARTIFACT": ql_heft_artifact,
        "SCHEDULER_POLICY": policy,
        "VIDEO_LAYOUT_DIR": video_layout_dir,
        "DEADLINE_MS": str(float(deadline_ms)),
        "CHECKPOINT_DEFER_FULL_RESOURCE_ACCEPTANCE": (
            "1" if full_resource_required else "0"
        ),
    }
    checkpoint_codec = resolve_checkpoint_codec(dataset, scenario)
    if checkpoint_codec is not None:
        command_env["CHECKPOINT_CODEC"] = checkpoint_codec
    if resolved_primary_policy_pair is not None:
        command_env["PRIMARY_POLICY_PAIR_JSON"] = json.dumps(
            resolved_primary_policy_pair,
            sort_keys=True,
            separators=(",", ":"),
        )
    if resolved_primary_architecture_pair is not None:
        command_env["PRIMARY_ARCHITECTURE_PAIR_JSON"] = json.dumps(
            resolved_primary_architecture_pair,
            sort_keys=True,
            separators=(",", ":"),
        )
    cmd: str | list[str]
    if backend_dispatch_resolution is None:
        assert base_cmd is not None
        cmd = (
            f"{scenario_env_prefix(scenario, distributed=execution_context.distributed_enabled, extra=command_env)} "
            f"{base_cmd}"
        )
    else:
        cmd = []

    run_relpath = str(scenario_dir)
    distributed_steps: list[dict[str, Any]] = []
    if distributed_enabled:
        if backend_dispatch_resolution is not None or command_template is None:
            raise ContractError(
                "backend publication dispatch prohibits distributed generic execution"
            )
        distributed_steps = build_distributed_plan(
            hosts_config=execution_context.hosts_config,
            scenario=scenario,
            system_key=system_key,
            command_template=command_template,
            run_relpath=run_relpath,
            duration_s=duration_s,
            streams=streams,
            min_objects=min_objects,
            max_objects=max_objects,
            deadline_ms=deadline_ms,
            transport=config.get("transport", {}),
            mode=mode,
            policy=policy,
            dataset_name=dataset["name"],
            run_id=run_id,
            detector=detector,
            backend=backend,
            extra_env=command_env,
        )

    if dry_run_plan:
        if distributed_enabled:
            print_distributed_plan(distributed_steps)
        else:
            print(
                f"[plan] {execution_context.deployment_mode} scenario={scenario_key} streams={streams} "
                f"system={system_key} command="
                f"{backend_dispatch_resolution['launcher']['path'] if backend_dispatch_resolution else cmd}"
            )
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": system_key,
            "scenario": scenario_key,
            "repeat": repeat_index,
            "exit_code": 0,
            "status": "planned",
            "run_mode": mode,
            "skip_reason": "",
            "streams": streams,
            "duration_s": duration_s,
            "scenario_variant": scenario.get("workload", {}).get("variant", ""),
            "placement_policy": scenario.get("placement", {}).get("policy", ""),
            "distributed": distributed_enabled,
            "deployment_mode": execution_context.deployment_mode,
            "host_topology": execution_context.host_topology,
            "host_role": "plan",
            "detector": detector,
            "backend": backend,
            "policy": policy,
            "dataset": dataset["name"],
            "deadline_ms": float(deadline_ms),
            "throughput_fps": float("nan"),
            "latency_p50_ms": float("nan"),
            "latency_p95_ms": float("nan"),
            "latency_p99_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
            "telemetry_source": "",
        }
        validate_summary_rows([result])
        return result

    backend_arm_contract_path: Path | None = None
    backend_arm_contract_authority: dict[str, Any] | None = None
    backend_output_receipt_authority: dict[str, Any] | None = None
    if backend_dispatch_resolution is not None:
        assert resolved_execution_binding is not None
        assert type(resource_capability_grant) is dict
        backend_arm_contract_path = scenario_dir / ARM_CONTRACT_FILENAME
        if backend_arm_contract_path.exists():
            raise ContractError(
                "immutable backend publication arm contract already exists"
            )
        backend_arm_contract = build_backend_publication_arm_contract(
            dispatch_resolution=backend_dispatch_resolution,
            execution_binding=resolved_execution_binding,
            resource_capability_grant=resource_capability_grant,
            model_parity_grant=resolved_model_parity_grant,
            dataset=dataset,
            scenario=scenario,
            run_id=run_id,
            run_seed=run_seed,
            streams=streams,
            duration_s=duration_s,
            repeat_index=repeat_index,
            base_seed=base_seed,
            output_dir=scenario_dir,
        )
        try:
            backend_arm_contract_authority = (
                write_immutable_backend_publication_arm_contract(
                    backend_arm_contract_path,
                    backend_arm_contract,
                )
            )
        except BackendPublicationOutputReceiptError as error:
            raise ContractError(
                f"backend publication arm contract commit failed: {error}"
            ) from error

    warmup_s = float(protocol.get("warmup_s", 0))
    if warmup_s > 0 and not bool(scenario.get("topology")):
        time.sleep(warmup_s)

    child_env = benchmark_child_environment(
        run_seed=run_seed,
        repeat_index=repeat_index,
    )

    distributed_result = None
    hardware_collector_started = False
    hardware_collector_closed = False
    collector.start()
    try:
        if hardware_collector is not None:
            hardware_collector.start()
            hardware_collector_started = True
            hardware_collector.wait_until_ready(timeout_s=10)
        if backend_dispatch_resolution is not None:
            assert backend_arm_contract_path is not None
            assert type(full_publication_identity_artifacts) is dict
            try:
                cmd = build_backend_publication_command(
                    backend_dispatch_resolution,
                    project_root=caller_project_root,
                    identity_artifacts=full_publication_identity_artifacts,
                    python_executable=Path(sys.executable),
                    arm_contract_path=backend_arm_contract_path,
                    output_dir=scenario_dir,
                )
            except BackendPublicationDispatchError as error:
                raise ContractError(
                    f"backend publication launcher pre-spawn validation failed: {error}"
                ) from error
            completed = subprocess.run(
                cmd,
                shell=False,
                check=False,
                timeout=cmd_timeout_s,
                env={},
                cwd=caller_project_root,
            )
            if completed.returncode == 0:
                assert backend_arm_contract_authority is not None
                try:
                    backend_output_receipt_authority = (
                        validate_backend_publication_output_receipt(
                            output_dir=scenario_dir,
                            expected_arm_contract_authority=(
                                backend_arm_contract_authority
                            ),
                        )
                    )
                except BackendPublicationOutputReceiptError as error:
                    raise ContractError(
                        "backend publication launcher output receipt failed "
                        f"post-spawn validation: {error}"
                    ) from error
        elif distributed_enabled:
            distributed_result = run_distributed(
                steps=distributed_steps,
                project_root=caller_project_root,
                local_run_dir=scenario_dir,
                frames_csv=frames_path,
                frame_events_csv=frame_events_path,
                network_csv=network_path,
                hosts_config=execution_context.hosts_config,
                network_profile=scenario.get("network", {}),
                max_clock_offset_ms=float(config.get("transport", {}).get("max_clock_offset_ms", 5)),
                sync_project=execution_context.sync_project,
                duration_s=duration_s,
                startup_grace_s=int(config.get("transport", {}).get("startup_grace_s", 5)),
                mode=mode,
                role_timeout_s=cmd_timeout_s,
                topology_events_csv=topology_events_path if scenario.get("topology") else None,
                ingress_ledger_csv=(scenario_dir / "ingress_ledger.csv") if scenario.get("topology") else None,
                branch_terminals_csv=(scenario_dir / "branch_terminals.csv") if scenario.get("topology") else None,
                stage_contracts_csv=(scenario_dir / "stage_contracts.csv") if scenario.get("topology") else None,
            )
            completed = subprocess.CompletedProcess(cmd, distributed_result.exit_code)
        else:
            completed = subprocess.run(
                cmd,
                shell=True,
                check=False,
                timeout=cmd_timeout_s,
                env=child_env,
                cwd=caller_project_root,
            )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(exc.cmd, returncode=124)
        raise RuntimeError(
            f"Command timed out after {cmd_timeout_s}s for system={system_key}, "
            f"scenario={scenario_key}, repeat={repeat_index}. "
            f"Inspect run directory: {scenario_dir}"
        ) from exc
    finally:
        try:
            if hardware_collector is not None:
                hardware_collector.stop()
                hardware_collector.join(timeout=5)
                if hardware_collector.is_alive():
                    raise RuntimeError("hardware resource collector did not stop")
                hardware_collector.raise_if_failed()
                hardware_collector_closed = True
        finally:
            collector.stop()
            collector.join(timeout=2)

    sampled_s = measured_metrics_duration_s(metrics_path)
    accepted_timeout_stop = False

    if distributed_result is not None and distributed_result.skipped:
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": system_key,
            "scenario": scenario_key,
            "repeat": repeat_index,
            "exit_code": int(distributed_result.exit_code),
            "status": "skipped",
            "run_mode": mode,
            "skip_reason": distributed_result.skip_reason,
            "streams": streams,
            "duration_s": duration_s,
            "scenario_variant": variant_name,
            "placement_policy": scenario.get("placement", {}).get("policy", ""),
            "distributed": distributed_enabled,
            "deployment_mode": execution_context.deployment_mode,
            "host_topology": execution_context.host_topology,
            "host_role": "distributed" if distributed_enabled else "local",
            "detector": detector,
            "backend": backend,
            "policy": policy,
            "dataset": dataset["name"],
            "deadline_ms": float(deadline_ms),
            "throughput_fps": float("nan"),
            "latency_p50_ms": float("nan"),
            "latency_p95_ms": float("nan"),
            "latency_p99_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
            "telemetry_source": "",
        }
        validate_summary_rows([result])
        publication_run_contract = resolve_publication_run_contract(
            config,
            result,
            resource_capability_grant=resource_capability_grant,
            backend_runtime_grant=resolved_backend_runtime_grant,
            model_parity_grant=resolved_model_parity_grant,
            full_publication_execution_binding=resolved_execution_binding,
        )
        publication_run_identity = publication_run_contract_identity(
            publication_run_contract
        )
        write_json(
            metadata_path,
            {
                "schema_version": 2,
                "mode": mode,
                "result": result,
                "resolved_scenario": scenario,
                "scenario_contract_identity": {
                    "schema_version": resolved_scenario_identity["schema_version"],
                    "sha256": resolved_scenario_identity["sha256"],
                },
                "publication_run_contract": publication_run_contract,
                "publication_run_contract_identity": {
                    "schema_version": publication_run_identity["schema_version"],
                    "sha256": publication_run_identity["sha256"],
                },
                "dataset": dataset,
                "git": git_manifest(caller_project_root),
                "adapter": adapter_manifest(system_config),
                "benchmark_adapter": benchmark_adapter.metadata() if benchmark_adapter else {},
                "primary_architecture_pair": resolved_primary_architecture_pair,
                "primary_policy_pair": resolved_primary_policy_pair,
                "detected_hardware": detected_hardware_manifest(),
                "ql_heft_policy_artifact": {
                    "path": ql_heft_artifact,
                    "sha256": (
                        sha256_file(Path(ql_heft_artifact))
                        if ql_heft_artifact and Path(ql_heft_artifact).exists()
                        else ""
                    ),
                },
                "distributed_plan": distributed_steps,
                "deployment_mode": execution_context.deployment_mode,
                "host_topology": execution_context.host_topology,
            },
        )
        return result

    if completed.returncode in (124, 137, 143):
        # Some real pipelines run continuously and rely on timeout as a controlled stop.
        # Accept this if we still captured at least the target measurement window.
        if sampled_s >= float(duration_s):
            print(
                f"[warning] Real-mode command ended by timeout/signal (exit={completed.returncode}) "
                f"after collecting {sampled_s:.1f}s metrics (target {duration_s}s). "
                f"Treating this run as valid."
            )
            accepted_timeout_stop = True
        elif completed.returncode == 124:
            raise RuntimeError(
                f"Real-mode command timed out for system={system_key}, scenario={scenario_key}, "
                f"repeat={repeat_index}. Inspect run directory: {scenario_dir}. "
                f"Increase STARTUP_GRACE_S/CMD_TIMEOUT_S or EXPERIMENT_CMD_TIMEOUT_S if needed."
            )
        else:
            raise RuntimeError(
                f"Real-mode command was terminated by signal for system={system_key}, scenario={scenario_key}, "
                f"repeat={repeat_index} (exit code {completed.returncode}). "
                f"This can indicate timeout force-kill or host OOM. "
                f"Current timeout env: CMD_TIMEOUT_S={os.environ.get('CMD_TIMEOUT_S', '') or '<unset>'}, "
                f"EXPERIMENT_CMD_TIMEOUT_S={os.environ.get('EXPERIMENT_CMD_TIMEOUT_S', '') or '<unset>'}, "
                f"STARTUP_GRACE_S={os.environ.get('STARTUP_GRACE_S', '') or '<unset>'}. "
                f"Inspect run directory: {scenario_dir}"
            )

    if completed.returncode != 0 and not accepted_timeout_stop:
        raise RuntimeError(
            f"Real-mode execution failed for system={system_key}, scenario={scenario_key}, "
            f"repeat={repeat_index} with exit code {completed.returncode}. "
            f"Inspect run directory: {scenario_dir}"
        )
    if backend_dispatch_resolution is not None and (
        backend_arm_contract_authority is None
        or backend_output_receipt_authority is None
    ):
        raise ContractError(
            "backend publication launcher returned without a validated output receipt"
        )

    if not frames_path.exists() and mode == "smoke":
        print(
            f"[warning] frames.csv missing after system command for system={system_key}, "
            f"scenario={scenario_key}, repeat={repeat_index}. Exporting synthetic smoke-only frame metrics."
        )
        emit_runtime_frames_csv(
            frames_csv=frames_path,
            duration_s=duration_s,
            streams=streams,
            min_objects=min_objects,
            max_objects=max_objects,
            deadline_s=float(deadline_ms) / 1000.0,
            elapsed_s=sampled_s,
            run_id=run_id,
            detector=detector,
            backend=backend,
        )
    frames_df = canonicalize_frames_csv(
        frames_path,
        mode=mode,
        run_id=run_id,
        detector=detector,
        backend=backend,
    )
    sidecar_summary: dict[str, Any] = {}
    publication_evidence_bundle: dict[str, Any] | None = None
    publication_evidence_identity: dict[str, Any] | None = None
    if mode == "benchmark":
        validate_system_metrics(metrics_path)
        events_df = validate_frame_events(frame_events_path)
        validate_stage_trace_coverage(
            frames_path,
            frame_events_path,
            required_stages=[str(stage) for stage in scenario.get("pipeline", [])],
        )
        topology_trace_complete = False
        topology_df: pd.DataFrame | None = None
        if scenario.get("topology"):
            topology_df = validate_topology_events(
                topology_events_path,
                frames=frames_df,
                frame_events=events_df,
                scenario=scenario,
            )
            topology_trace_complete = True
        write_provenance_labeled_sidecars(
            scenario_dir,
            frames=frames_df,
            events=events_df,
            dataset=dataset,
            policy=policy,
            deadline_ms=deadline_ms,
        )
        topology_config = scenario.get("topology") or {}
        validate_required_sidecars(
            scenario_dir,
            require_labeled_provenance=True,
            require_ingress_ledger=bool(topology_config),
            require_branch_terminals=bool(topology_config),
            require_stage_contracts=bool(topology_config),
            require_reset_evidence=bool(topology_config),
            required_branches=topology_config.get("required_branches"),
            topology_kind=topology_config.get("kind"),
            expected_streams=streams if topology_config else None,
            require_full_resource_evidence=full_resource_required,
            expected_run_id=run_id,
            frames=frames_df,
            topology_events=topology_df,
        )
        sidecar_summary = summarize_sidecars(
            scenario_dir,
            frames=frames_df,
            topology_events=topology_df,
            required_branches=topology_config.get("required_branches"),
            topology_kind=topology_config.get("kind"),
            expected_streams=streams if topology_config else None,
            require_reset_evidence=bool(topology_config),
            require_full_resource_evidence=full_resource_required,
            expected_run_id=run_id,
            decoder_placement_contract=(
                PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT
                if topology_config
                else None
            ),
        )
        sidecar_summary["topology_trace_complete"] = topology_trace_complete
    summary = summarize_frames(frames_path, deadline_ms=deadline_ms, measurement_s=duration_s)
    summary.update(sidecar_summary)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": system_key,
        "scenario": scenario_key,
        "repeat": repeat_index,
        "exit_code": int(completed.returncode),
        "status": "completed",
        "run_mode": mode,
        "skip_reason": "",
        "streams": streams,
        "duration_s": duration_s,
        "scenario_variant": variant_name,
        "placement_policy": scenario.get("placement", {}).get("policy", ""),
        "distributed": distributed_enabled,
        "deployment_mode": execution_context.deployment_mode,
        "host_topology": execution_context.host_topology,
        "host_role": "distributed" if distributed_enabled else "local",
        "detector": detector,
        "backend": backend,
        "policy": policy,
        "dataset": dataset["name"],
        "seed": base_seed,
        "run_seed": run_seed,
        **summary,
    }
    validate_summary_rows([result])
    publication_run_contract = resolve_publication_run_contract(
        config,
        result,
        resource_capability_grant=resource_capability_grant,
        backend_runtime_grant=resolved_backend_runtime_grant,
        model_parity_grant=resolved_model_parity_grant,
        full_publication_execution_binding=resolved_execution_binding,
        backend_publication_arm_contract_authority=(
            backend_arm_contract_authority
        ),
        backend_publication_output_receipt_authority=(
            backend_output_receipt_authority
        ),
    )
    publication_run_identity = publication_run_contract_identity(
        publication_run_contract
    )
    if mode == "benchmark" and bool(scenario.get("topology")):
        publication_evidence_scope = resolve_publication_evidence_bundle_scope(
            config,
            result,
            resource_capability_grant=resource_capability_grant,
        )
        publication_evidence_bundle = build_publication_evidence_bundle(
            scenario_dir,
            scope=publication_evidence_scope,
            policy=policy,
        )
        publication_evidence_identity = publication_evidence_bundle_identity(
            publication_evidence_bundle
        )

    metadata = {
        "schema_version": 2,
        "command": cmd,
        "distributed_plan": [
            {
                "role": step["role"],
                "host": step["host_label"],
                "pipeline_stages": step["pipeline_stages"],
                "remote_output_dir": step["remote_output_dir"],
                "remote_command": step["remote_command"],
            }
            for step in distributed_steps
        ],
        "run_seed": run_seed,
        "mode": mode,
        "deployment_mode": execution_context.deployment_mode,
        "host_topology": execution_context.host_topology,
        "policy": policy,
        "dataset": dataset,
        "git": git_manifest(caller_project_root),
        "adapter": adapter_manifest(system_config),
        "benchmark_adapter": benchmark_adapter.metadata() if benchmark_adapter else {},
        "primary_architecture_pair": resolved_primary_architecture_pair,
        "primary_policy_pair": resolved_primary_policy_pair,
        "detected_hardware": detected_hardware_manifest(),
        "ql_heft_policy_artifact": {
            "path": ql_heft_artifact,
            "sha256": sha256_file(Path(ql_heft_artifact)) if ql_heft_artifact and Path(ql_heft_artifact).exists() else "",
        },
        "max_clock_offset_ms": (
            distributed_result.max_clock_offset_ms if distributed_result is not None else 0.0
        ),
        "metric_interval_s": metric_interval_s,
        "result": result,
        "resolved_scenario": scenario,
        "scenario_contract_identity": {
            "schema_version": resolved_scenario_identity["schema_version"],
            "sha256": resolved_scenario_identity["sha256"],
        },
        "publication_run_contract": publication_run_contract,
        "publication_run_contract_identity": {
            "schema_version": publication_run_identity["schema_version"],
            "sha256": publication_run_identity["sha256"],
        },
        "hosts_config": str(execution_context.hosts_config_path),
        "hardware_target": config.get("hardware_target", {}),
        "protocol": config.get("protocol", {}),
    }

    if publication_evidence_bundle is not None:
        assert publication_evidence_identity is not None
        metadata["publication_evidence_bundle"] = publication_evidence_bundle
        metadata["publication_evidence_bundle_identity"] = {
            "schema_version": publication_evidence_identity["schema_version"],
            "sha256": publication_evidence_identity["sha256"],
        }

    with checkpoint_full_resource_acceptance_transaction(
        full_resource_required=full_resource_required,
        mode=mode,
        scenario=scenario,
        checkpoint_codec=checkpoint_codec,
        hardware_collector=hardware_collector,
        hardware_collector_started=hardware_collector_started,
        hardware_collector_closed=hardware_collector_closed,
        output_dir=scenario_dir,
        expected_run_id=run_id,
        expected_system=system_key,
        expected_policy=policy,
        expected_deadline_ms=float(deadline_ms),
        run_metadata_path=metadata_path,
        expected_execution_binding=resolved_execution_binding,
    ) as finalized_resource_summary:
        if finalized_resource_summary is not None:
            result.update(finalized_resource_summary)
        validate_summary_rows([result])
        publication_run_contract = resolve_publication_run_contract(
            config,
            result,
            resource_capability_grant=resource_capability_grant,
            backend_runtime_grant=resolved_backend_runtime_grant,
            model_parity_grant=resolved_model_parity_grant,
            full_publication_execution_binding=resolved_execution_binding,
            backend_publication_arm_contract_authority=(
                backend_arm_contract_authority
            ),
            backend_publication_output_receipt_authority=(
                backend_output_receipt_authority
            ),
        )
        publication_run_identity = publication_run_contract_identity(
            publication_run_contract
        )
        metadata["publication_run_contract"] = publication_run_contract
        metadata["publication_run_contract_identity"] = {
            "schema_version": publication_run_identity["schema_version"],
            "sha256": publication_run_identity["sha256"],
        }
        write_durable_json(metadata_path, metadata)
    return result


def expand_scenario(config: dict[str, Any], scenario_key: str) -> list[dict[str, Any]]:
    scenario = normalize_scenario(scenario_key, config["scenarios"][scenario_key])
    workload = scenario["workload"]
    obj = _object_profile(workload)
    variants = workload.get("variants") or [None]
    stream_values: list[int]
    if "stream_range" in workload:
        start, end = workload["stream_range"]
        stream_values = list(range(int(start), int(end) + 1))
    else:
        stream_values = [int(workload.get("streams", 6))]

    expanded: list[dict[str, Any]] = []
    for variant in variants:
        if isinstance(variant, dict):
            variant_scenario = resolve_scenario_contract(
                scenario_key,
                config["scenarios"][scenario_key],
                variant_name=str(variant.get("name", "variant")),
            )
        else:
            variant_scenario = json.loads(json.dumps(scenario))
        for s in stream_values:
            variant_obj = _object_profile(variant_scenario["workload"])
            expanded.append(
                {
                    "scenario": variant_scenario,
                    "streams": s,
                    "min_objects": variant_obj["min"],
                    "max_objects": variant_obj["max"],
                }
            )
    return expanded


def build_primary_architecture_execution_cells(
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = build_primary_architecture_runtime_plan(config)
    if not bool(plan["runtime_execution_allowed"]):
        blockers = ", ".join(str(value) for value in plan["blockers"])
        raise ContractError(
            "primary architecture execution is blocked: " + blockers
        )

    primary = validate_primary_architecture_contrast(config)
    protocol = config.get("protocol") or {}
    if int(protocol.get("warmup_s", -1)) != int(primary["warmup_s"]):
        raise ContractError(
            "protocol warmup_s differs from the frozen primary architecture cell"
        )
    if int(protocol.get("measurement_s", -1)) != int(primary["measurement_s"]):
        raise ContractError(
            "protocol measurement_s differs from the frozen primary architecture cell"
        )

    cells: list[dict[str, Any]] = []
    for sequence, planned_run in enumerate(plan["runs"], start=1):
        scenario_key = str(planned_run["scenario"])
        if scenario_key not in config.get("scenarios", {}):
            raise ContractError(
                f"primary architecture scenario is not configured: {scenario_key}"
            )
        matching_variants = [
            variant
            for variant in expand_scenario(config, scenario_key)
            if int(variant["streams"]) == int(planned_run["streams"])
        ]
        if len(matching_variants) != 1:
            raise ContractError(
                "primary architecture execution requires exactly one resolved "
                f"scenario variant for {scenario_key} at streams={planned_run['streams']}"
            )
        variant = matching_variants[0]
        duration_s = _scenario_duration_s(
            variant["scenario"],
            int(planned_run["measurement_s"]),
        )
        if duration_s != int(planned_run["measurement_s"]):
            raise ContractError(
                "scenario duration differs from the frozen primary architecture cell"
            )
        pair_metadata = validate_primary_architecture_pair_run_contract(
            config,
            system=str(planned_run["system"]),
            scenario=scenario_key,
            policy=str(planned_run["policy"]),
            dataset=str(planned_run["dataset"]),
            deadline_ms=float(planned_run["deadline_ms"]),
            streams=int(planned_run["streams"]),
            repeat=int(planned_run["primary_architecture_pair"]["repeat"]),
            metadata=planned_run["primary_architecture_pair"],
        )
        cells.append(
            {
                "sequence": sequence,
                "scenario_key": scenario_key,
                "scenario": variant["scenario"],
                "streams": int(variant["streams"]),
                "min_objects": int(variant["min_objects"]),
                "max_objects": int(variant["max_objects"]),
                "duration_s": duration_s,
                "system": str(planned_run["system"]),
                "policy": str(planned_run["policy"]),
                "dataset": str(planned_run["dataset"]),
                "deadline_ms": float(planned_run["deadline_ms"]),
                "repeat": int(pair_metadata["repeat"]),
                "seed": int(planned_run["seed"]),
                "primary_architecture_pair": pair_metadata,
            }
        )
    if len(cells) != int(plan["expected_runs"]):
        raise ContractError("primary architecture execution plan length drifted")
    return plan, cells


def validate_primary_architecture_resume_prefix(
    resumable_rows: list[dict[str, Any] | None],
) -> int:
    completed_prefix = 0
    missing_seen = False
    for sequence, row in enumerate(resumable_rows, start=1):
        if row is None:
            missing_seen = True
            continue
        if row.get("status") != "completed":
            raise ContractError(
                f"primary architecture resume step {sequence} is not completed"
            )
        if missing_seen:
            raise ContractError(
                "primary architecture resume requires completed runs to form a "
                f"contiguous prefix; found completed step {sequence} after a gap"
            )
        completed_prefix += 1
    return completed_prefix


def run_primary_architecture_execution(
    config: dict[str, Any],
    *,
    output_root: Path,
    resume_run_root: Path | None,
    hosts_config_path: Path,
    single_server_host: str,
    single_server_user: str,
    single_server_port: int,
    requested_seed: int | None,
) -> tuple[Path, list[dict[str, Any]]]:
    output_root = output_root if output_root.is_absolute() else PROJECT_ROOT / output_root
    if resume_run_root is not None and not resume_run_root.is_absolute():
        resume_run_root = PROJECT_ROOT / resume_run_root
    primary = validate_primary_architecture_contrast(config)
    plan, cells = build_primary_architecture_execution_cells(config)
    frozen_seed = int(primary["seed"])
    if requested_seed is not None and int(requested_seed) != frozen_seed:
        raise ContractError(
            "--seed differs from the frozen primary architecture seed"
        )
    base_seed = frozen_seed

    system_key = str(primary["system"])
    if configured_system_names(config, [system_key], mode="benchmark") != [system_key]:
        raise ContractError(
            f"primary architecture system is not benchmark-eligible: {system_key}"
        )
    dataset = load_dataset(
        Path(config["benchmark"]["dataset_manifest"]),
        str(primary["dataset"]),
        mode="benchmark",
        project_root=PROJECT_ROOT,
        require_files=True,
        allow_placeholder_checksums=False,
    )
    hosts_config = load_hosts_config(hosts_config_path)
    validate_hardware(config, require_match=True)

    if resume_run_root is not None:
        run_root = resume_run_root
        if not run_root.is_dir():
            raise ContractError(f"--resume-run-root does not exist: {run_root}")
    else:
        run_root = output_root / datetime.now().strftime("%Y%m%d_%H%M%S")
        if run_root.exists():
            raise ContractError(
                f"primary architecture run root already exists; use --resume-run-root: {run_root}"
            )

    resumable_rows: list[dict[str, Any] | None] = []
    for cell in cells:
        if resume_run_root is None:
            resumable_rows.append(None)
            continue
        variant_name = str(
            cell["scenario"].get("workload", {}).get("variant", "")
        ).strip()
        seed_key = str(
            cell["scenario"].get("workload", {}).get(
                "seed_group", cell["scenario_key"]
            )
        )
        expected_run_seed = build_run_seed(
            base_seed,
            seed_key,
            variant_name,
            int(cell["streams"]),
            int(cell["repeat"]),
        )
        metadata_path = run_directory(
            run_root,
            cell["scenario"],
            int(cell["streams"]),
            str(cell["system"]),
            int(cell["repeat"]),
            float(cell["deadline_ms"]),
        ) / "run_metadata.json"
        resumable_rows.append(
            load_resumable_result(
                metadata_path,
                system_key=str(cell["system"]),
                scenario_key=str(cell["scenario_key"]),
                repeat_index=int(cell["repeat"]),
                streams=int(cell["streams"]),
                duration_s=int(cell["duration_s"]),
                policy=str(cell["policy"]),
                dataset_name=str(cell["dataset"]),
                mode="benchmark",
                deadline_ms=float(cell["deadline_ms"]),
                scenario_contract=cell["scenario"],
                dataset_contract=dataset,
                config=config,
                base_seed=base_seed,
                run_seed=expected_run_seed,
                primary_architecture_pair=cell["primary_architecture_pair"],
            )
        )

    completed_prefix = validate_primary_architecture_resume_prefix(resumable_rows)
    if resume_run_root is None:
        run_root.mkdir(parents=True, exist_ok=False)

    all_rows = [
        row for row in resumable_rows[:completed_prefix] if row is not None
    ]
    for cell in cells[:completed_prefix]:
        print(
            f"[resumed-primary-architecture] step={cell['sequence']}/{plan['expected_runs']} "
            f"scenario={cell['scenario_key']} rep={cell['repeat']}"
        )

    for cell in cells[completed_prefix:]:
        execution_context = resolve_execution_context(
            requested_run_kind="auto",
            scenario=cell["scenario"],
            hosts_config=hosts_config,
            hosts_config_path=hosts_config_path,
            single_server_host=single_server_host,
            single_server_user=single_server_user,
            single_server_port=single_server_port,
            project_root=PROJECT_ROOT,
        )
        row = run_one(
            config=config,
            dataset=dataset,
            system_key=str(cell["system"]),
            scenario=cell["scenario"],
            streams=int(cell["streams"]),
            min_objects=int(cell["min_objects"]),
            max_objects=int(cell["max_objects"]),
            duration_s=int(cell["duration_s"]),
            repeat_index=int(cell["repeat"]),
            run_root=run_root,
            execution_context=execution_context,
            mode="benchmark",
            policy=str(cell["policy"]),
            deadline_ms=float(cell["deadline_ms"]),
            base_seed=base_seed,
            dry_run_plan=False,
            primary_architecture_pair=cell["primary_architecture_pair"],
        )
        if row.get("status") != "completed":
            raise ContractError(
                "primary architecture execution stopped on a non-completed arm: "
                f"step={cell['sequence']}, status={row.get('status', '')}"
            )
        all_rows.append(row)
        print(
            f"[done-primary-architecture] step={cell['sequence']}/{plan['expected_runs']} "
            f"scenario={cell['scenario_key']} rep={cell['repeat']}"
        )

    if len(all_rows) != int(plan["expected_runs"]):
        raise ContractError("primary architecture execution did not complete every planned arm")
    summary_csv = run_root / "summary.csv"
    write_summary_csv(summary_csv, all_rows)
    print(f"[result] primary architecture summary saved to {summary_csv}")
    return run_root, all_rows


def validate_primary_architecture_run_arguments(
    args: argparse.Namespace,
    config: dict[str, Any],
) -> None:
    primary = validate_primary_architecture_contrast(config)
    conflicts = []
    if args.mode != "benchmark":
        conflicts.append("--mode")
    if args.systems != ["all"]:
        conflicts.append("--systems")
    if args.scenarios != ["all"]:
        conflicts.append("--scenarios")
    if args.repeats != -1:
        conflicts.append("--repeats")
    if args.measurement != -1:
        conflicts.append("--measurement")
    if args.warmup != -1:
        conflicts.append("--warmup")
    if args.dataset or args.datasets is not None:
        conflicts.append("--dataset/--datasets")
    if args.policy != str(primary["policy"]) or args.policies is not None:
        conflicts.append("--policy/--policies")
    if args.deadline_modes != ["all"]:
        conflicts.append("--deadline-modes")
    if args.run_kind != "auto" or args.local_only:
        conflicts.append("--run-kind/--local-only")
    if args.dry_run_plan:
        conflicts.append("--dry-run-plan")
    if args.continue_on_error:
        conflicts.append("--continue-on-error")
    if args.seed is not None and int(args.seed) != int(primary["seed"]):
        conflicts.append("--seed")
    if conflicts:
        raise ContractError(
            "--primary-architecture-run uses only the frozen preregistered cell; "
            "remove conflicting options: " + ", ".join(conflicts)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run experiment matrix and capture metrics")
    parser.add_argument("--config", default="configs/experiments.yaml")
    parser.add_argument("--systems", nargs="*", default=["all"])
    parser.add_argument("--scenarios", nargs="*", default=["all"])
    parser.add_argument("--repeats", type=int, default=-1)
    parser.add_argument("--measurement", type=int, default=-1, help="Override measurement seconds")
    parser.add_argument("--warmup", type=int, default=-1, help="Override warmup seconds")
    parser.add_argument("--output-root", default="runs")
    parser.add_argument("--hosts-config", type=Path, default=Path("configs/hosts.yaml"))
    parser.add_argument("--mode", choices=["smoke", "benchmark"], default="benchmark")
    parser.add_argument("--dataset", default="")
    parser.add_argument("--datasets", nargs="*", default=None)
    parser.add_argument("--policy", default="static_hybrid")
    parser.add_argument("--policies", nargs="*", default=None)
    parser.add_argument("--deadline-modes", nargs="*", default=["all"])
    parser.add_argument(
        "--run-kind",
        choices=["auto", "local", "heterogeneous", "single-server-distributed", "distributed"],
        default="auto",
    )
    parser.add_argument("--local-only", action="store_true", help="Deprecated alias for --run-kind local")
    parser.add_argument("--single-server-host", default="127.0.0.1")
    parser.add_argument("--single-server-port", type=int, default=22)
    parser.add_argument("--single-server-user", default="")
    parser.add_argument("--seed", type=int, default=None, help="Base seed shared across systems for a scenario/repeat")
    parser.add_argument("--dry-run-plan", action="store_true")
    primary_mode = parser.add_mutually_exclusive_group()
    primary_mode.add_argument(
        "--primary-architecture-plan",
        action="store_true",
        help=(
            "Print the frozen non-measurement architecture-pair schedule and "
            "topology readiness, then exit"
        ),
    )
    primary_mode.add_argument(
        "--primary-architecture-run",
        action="store_true",
        help=(
            "Execute the frozen 20-arm primary architecture schedule only when "
            "all topology, dataset, hardware, and native telemetry gates are ready"
        ),
    )
    primary_mode.add_argument(
        "--primary-policy-plan",
        action="store_true",
        help=(
            "Print the frozen non-measurement policy-pair schedule and runtime "
            "compatibility assessment, then exit"
        ),
    )
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--resume-run-root",
        type=Path,
        help="Reuse a failed run root, skipping only completed repetitions with matching metadata",
    )
    parser.add_argument(
        "--strict-real-mode",
        action="store_true",
        help="Deprecated: real mode is now always enabled",
    )
    args = parser.parse_args()

    os.environ["REAL_DRY_RUN"] = "0"

    cfg = load_config(Path(args.config))
    if int(cfg.get("schema_version", 0)) != 2:
        raise ContractError("configs/experiments.yaml must use schema_version: 2")
    validate_primary_architecture_contrast(cfg)
    validate_primary_policy_ablation(cfg)
    if args.primary_architecture_plan:
        print(
            json.dumps(
                build_primary_architecture_runtime_plan(cfg),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.primary_policy_plan:
        print(
            json.dumps(
                build_primary_policy_runtime_plan(cfg),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.primary_architecture_run:
        validate_primary_architecture_run_arguments(args, cfg)
        run_primary_architecture_execution(
            cfg,
            output_root=Path(args.output_root),
            resume_run_root=args.resume_run_root,
            hosts_config_path=args.hosts_config,
            single_server_host=args.single_server_host,
            single_server_user=args.single_server_user,
            single_server_port=args.single_server_port,
            requested_seed=args.seed,
        )
        return
    hosts_cfg = load_hosts_config(args.hosts_config)
    requested_policies = args.policies if args.policies is not None else [args.policy]
    policy_names = configured_policy_names(cfg, requested_policies)
    run_kind = normalize_run_kind(args.run_kind, local_only=args.local_only)
    if args.dry_run_plan and run_kind == "distributed" and not hosts_cfg.get("hosts"):
        hosts_example = args.hosts_config.with_name("hosts.example.yaml")
        if hosts_example.exists():
            print(f"[warning] {args.hosts_config} is empty or missing; using {hosts_example} for dry-run planning")
            hosts_cfg = load_hosts_config(hosts_example)
    base_seed = int(args.seed if args.seed is not None else cfg.get("benchmark", {}).get("default_seed", 20260323))
    dataset_names = configured_dataset_names(cfg, mode=args.mode, dataset=args.dataset, datasets=args.datasets)
    datasets = [
        load_dataset(
            Path(cfg["benchmark"]["dataset_manifest"]),
            dataset_name,
            mode=args.mode,
            project_root=PROJECT_ROOT,
            require_files=args.mode == "benchmark" and not args.dry_run_plan,
            allow_placeholder_checksums=args.dry_run_plan,
        )
        for dataset_name in dataset_names
    ]

    if args.warmup >= 0:
        cfg["protocol"]["warmup_s"] = int(args.warmup)

    validate_hardware(
        cfg,
        require_match=args.mode == "benchmark" and not args.dry_run_plan,
    )

    systems = configured_system_names(cfg, args.systems, mode=args.mode)
    if args.mode == "benchmark" and args.systems == ["all"]:
        excluded_systems = sorted(set(cfg["systems"]) - set(systems))
        for system in excluded_systems:
            reason = str(cfg["systems"][system].get("benchmark_reason", "diagnostic-only adapter"))
            print(f"[warning] excluding diagnostic-only benchmark system {system}: {reason}")
    scenarios = select_scenarios(cfg, args.scenarios, mode=args.mode, run_kind=run_kind)
    if args.mode == "benchmark" and args.scenarios == ["all"]:
        configured_scenarios = cfg.get("benchmark", {}).get("active_scenarios") or list(cfg["scenarios"])
        excluded_scenarios = [name for name in configured_scenarios if name not in scenarios]
        for scenario in excluded_scenarios:
            raw = cfg["scenarios"].get(scenario, {})
            reason = str(raw.get("benchmark_reason", "scenario is not publication-ready"))
            print(f"[warning] excluding non-publishable benchmark scenario {scenario}: {reason}")
    if not scenarios:
        raise ContractError(
            "no scenarios are eligible for this execution mode and topology; "
            "implement and verify the publication topology contract before benchmark execution"
        )

    repeats = int(cfg["protocol"]["repeats"] if args.repeats < 0 else args.repeats)
    measurement_s = int(cfg["protocol"]["measurement_s"] if args.measurement < 0 else args.measurement)
    deadlines_ms = configured_deadlines_ms(cfg, mode=args.mode, requested=args.deadline_modes)
    use_matrix_dirs = len(datasets) > 1 or len(policy_names) > 1

    run_root = args.resume_run_root or Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.resume_run_root and not args.dry_run_plan and not run_root.is_dir():
        raise ContractError(f"--resume-run-root does not exist: {run_root}")
    if not args.dry_run_plan:
        run_root.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []

    for dataset in datasets:
        for policy in policy_names:
            for scenario in scenarios:
                if scenario not in cfg["scenarios"]:
                    print(f"[error] unknown scenario: {scenario}")
                    sys.exit(2)
                scenario_variants = expand_scenario(cfg, scenario)

                for system in systems:
                    if system not in cfg["systems"]:
                        print(f"[error] unknown system: {system}")
                        sys.exit(2)

                    for variant in scenario_variants:
                        execution_context = resolve_execution_context(
                            requested_run_kind=run_kind,
                            scenario=variant["scenario"],
                            hosts_config=hosts_cfg,
                            hosts_config_path=args.hosts_config,
                            single_server_host=args.single_server_host,
                            single_server_user=args.single_server_user,
                            single_server_port=args.single_server_port,
                            project_root=PROJECT_ROOT,
                        )
                        for deadline_ms in deadlines_ms:
                            for rep in range(1, repeats + 1):
                                duration_s = _scenario_duration_s(variant["scenario"], measurement_s)
                                directory_dataset_name = dataset["name"] if use_matrix_dirs else None
                                directory_policy = policy if use_matrix_dirs else None
                                variant_name = str(
                                    variant["scenario"].get("workload", {}).get(
                                        "variant", ""
                                    )
                                ).strip()
                                seed_key = str(
                                    variant["scenario"].get("workload", {}).get(
                                        "seed_group", variant["scenario"]["name"]
                                    )
                                )
                                expected_run_seed = build_run_seed(
                                    base_seed,
                                    seed_key,
                                    variant_name,
                                    variant["streams"],
                                    rep,
                                )
                                if args.resume_run_root and not args.dry_run_plan:
                                    metadata_path = run_directory(
                                        run_root,
                                        variant["scenario"],
                                        variant["streams"],
                                        system,
                                        rep,
                                        deadline_ms,
                                        directory_dataset_name,
                                        directory_policy,
                                    ) / "run_metadata.json"
                                    existing = load_resumable_result(
                                        metadata_path,
                                        system_key=system,
                                        scenario_key=variant["scenario"]["name"],
                                        repeat_index=rep,
                                        streams=variant["streams"],
                                        duration_s=duration_s,
                                        policy=policy,
                                        dataset_name=dataset["name"],
                                        mode=args.mode,
                                        deadline_ms=deadline_ms,
                                        scenario_contract=variant["scenario"],
                                        dataset_contract=dataset,
                                        config=cfg,
                                        base_seed=base_seed,
                                        run_seed=expected_run_seed,
                                    )
                                    if existing is not None:
                                        all_rows.append(existing)
                                        print(
                                            f"[resumed] dataset={dataset['name']} policy={policy} scenario={scenario} "
                                            f"streams={variant['streams']} deadline_ms={deadline_ms:g} "
                                            f"system={system} rep={rep}"
                                        )
                                        continue
                                try:
                                    row = run_one(
                                        config=cfg,
                                        dataset=dataset,
                                        system_key=system,
                                        scenario=variant["scenario"],
                                        streams=variant["streams"],
                                        min_objects=variant["min_objects"],
                                        max_objects=variant["max_objects"],
                                        duration_s=duration_s,
                                        repeat_index=rep,
                                        run_root=run_root,
                                        execution_context=execution_context,
                                        mode=args.mode,
                                        policy=policy,
                                        deadline_ms=deadline_ms,
                                        base_seed=base_seed,
                                        dry_run_plan=args.dry_run_plan,
                                        directory_dataset_name=directory_dataset_name,
                                        directory_policy=directory_policy,
                                    )
                                except Exception as exc:
                                    if not args.continue_on_error:
                                        raise
                                    row = failed_result_row(
                                        config=cfg,
                                        dataset=dataset,
                                        system_key=system,
                                        scenario=variant["scenario"],
                                        streams=variant["streams"],
                                        duration_s=duration_s,
                                        repeat_index=rep,
                                        execution_context=execution_context,
                                        policy=policy,
                                        deadline_ms=deadline_ms,
                                        mode=args.mode,
                                        error=exc,
                                    )
                                    print(
                                        f"[failed] dataset={dataset['name']} policy={policy} scenario={scenario} "
                                        f"streams={variant['streams']} deadline_ms={deadline_ms:g} "
                                        f"system={system} rep={rep} reason={row['skip_reason']}"
                                    )
                                all_rows.append(row)
                                if row["status"] == "skipped":
                                    print(
                                        f"[skipped] dataset={dataset['name']} policy={policy} scenario={scenario} "
                                        f"streams={variant['streams']} deadline_ms={deadline_ms:g} "
                                        f"system={system} rep={rep} reason={row['skip_reason']}"
                                    )
                                else:
                                    print(
                                        f"[done] dataset={dataset['name']} policy={policy} scenario={scenario} "
                                        f"streams={variant['streams']} deadline_ms={deadline_ms:g} system={system} "
                                        f"rep={rep} fps={row['throughput_fps']} p95={row['latency_p95_ms']} "
                                        f"slo={row['slo_violation_rate_percent']}%"
                                    )

    if args.dry_run_plan:
        print("[result] dry run plan complete")
        return

    summary_csv = run_root / "summary.csv"
    write_summary_csv(summary_csv, all_rows)

    print(f"[result] summary saved to {summary_csv}")


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
