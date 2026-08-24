#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import math
import os
import posixpath
import re
import shutil
import socket
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from analytics_model_contract import (
    load_analytics_model_bindings as load_v2_analytics_model_bindings,
)
from benchmark_contract import (
    BRANCH_TERMINAL_COLUMNS,
    ContractError,
    INGRESS_LEDGER_COLUMNS,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT,
    PRIMARY_ANALYTICS_QUEUE_CONTRACT,
    RESET_EVIDENCE_COLUMNS,
    STAGE_CONTRACT_COLUMNS,
    validate_stage_contracts,
)
from checkpoint_admission import schedule_fingerprint_for_records
from checkpoint_runtime import (
    SourceLaunchSpec,
    WorkerLaunchSpec,
    build_runtime_reset_evidence,
    run_worker_processes,
)
from full_resource_contract import (
    FANOUT_COUNTER_PROVENANCE,
    FANOUT_WORK_COUNTER_COLUMNS,
    FULL_RESOURCE_CONTRACT_VERSION,
    HARDWARE_RESOURCE_SAMPLE_COLUMNS,
    FullResourceContractError,
    validate_fanout_work_counters,
    validate_full_resource_evidence,
)
from checkpoint_runtime_plan import (
    CLAIM_STATUS,
    build_checkpoint_runtime_plan,
    build_primary_pair_plans,
)
from checkpoint_native_policy_runtime import (
    NativePolicyRuntimeCoordinator,
    assess_gstreamer_native_policy_execution_manifest,
    canonical_frames_from_events,
    require_exact_native_cpu_capability_bindings,
)
from checkpoint_publication_runtime import publish_checkpoint_runtime
from publication_policy_contract import POLICIES
from resource_interval_contract import (
    RESOURCE_INTERVAL_COLUMNS,
    RESOURCE_INTERVAL_CONTRACT_VERSION,
    ResourceIntervalContractError,
    TELEMETRY_SCHEMA_VERSION,
    summarize_resource_interval_extension,
    validate_resource_intervals,
)
from topology_contract import INDEPENDENT_PROCESSES, TOPOLOGY_EVENT_COLUMNS


ENGINEERING_STATUS = "engineering_runtime_incomplete_not_publishable"
TOPOLOGY_ONLY_ANALYTICS_MODE = "topology_only"
NATIVE_TERMINAL_ANALYTICS_MODE = "native_terminal_socket_v1"
ANALYTICS_TERMINAL_MODES = {
    TOPOLOGY_ONLY_ANALYTICS_MODE,
    NATIVE_TERMINAL_ANALYTICS_MODE,
}
REFERENCE_ANALYTICS_ELEMENT = "vastanalyticsterminal"
REFERENCE_ANALYTICS_QUEUE = "vastanalyticsqueue"
REFERENCE_ANALYTICS_PLACEHOLDERS = {
    "{branch}",
    "{factory}",
    "{model_path}",
    "{model_sha256}",
    "{weights_sha256}",
    "{detector_id}",
    "{device}",
    "{input_format}",
    "{batch_size}",
    "{nireq}",
    "{ie_config}",
    "{max_buffers}",
}
MODEL_BINDING_ENV_FIELDS = {
    "factory": "FACTORY",
    "device": "DEVICE",
    "input_format": "INPUT_FORMAT",
    "batch_size": "BATCH_SIZE",
    "nireq": "NIREQ",
    "ie_config": "IE_CONFIG",
    "model_path": "MODEL_PATH",
    "model_sha256": "MODEL_SHA256",
    "weights_sha256": "WEIGHTS_SHA256",
    "detector_id": "DETECTOR_ID",
}
CHECKPOINT_KEYS = {
    "checkpoint_independent_processes_baseline": "baseline",
    "checkpoint_video_dag_shared": "shared",
}

CHECKPOINT_DECODER_FACTORIES_BY_CODEC = {
    "h264": ("nvh264dec", "nvv4l2decoder"),
    "h265": ("nvh265dec", "nvv4l2decoder"),
}


def checkpoint_decoder_factories(codec: str) -> tuple[str, ...]:
    """Return the frozen hardware-decoder allowlist for one elementary stream codec."""

    normalized = str(codec).strip().lower()
    factories = CHECKPOINT_DECODER_FACTORIES_BY_CODEC.get(normalized)
    _require(factories is not None, f"unsupported checkpoint codec: {codec}")
    return factories


def _decoder_placement_contract(codec: str) -> dict[str, Any]:
    contract = dict(PRIMARY_ARCHITECTURE_DECODER_PLACEMENT_CONTRACT)
    contract["codec"] = str(codec).strip().lower()
    contract["allowed_factories"] = list(checkpoint_decoder_factories(codec))
    return contract


def _analytics_execution_socket_path(value: Path | str | None) -> str:
    _require(
        value is not None,
        "native policy runtime requires --analytics-execution-socket",
    )
    raw = os.fspath(value)
    _require(
        type(raw) is str
        and raw.startswith("/")
        and "\\" not in raw
        and "\x00" not in raw
        and len(os.fsencode(raw)) < 108,
        "analytics execution socket path must be an absolute bounded POSIX path",
    )
    _require(
        posixpath.normpath(raw) == raw,
        "analytics execution socket path must be canonical",
    )
    if os.name == "posix":
        parent = posixpath.dirname(raw)
        parent_path = Path(parent)
        _require(
            parent_path.is_dir()
            and not parent_path.is_symlink()
            and os.path.realpath(parent) == parent,
            "analytics execution socket parent must be an existing canonical directory",
        )
        if os.path.lexists(raw):
            _require(
                stat.S_ISSOCK(os.lstat(raw).st_mode),
                "analytics execution socket path exists but is not a socket",
            )
    return raw


def _analytics_preprocessing_contract_sha256(value: str | None) -> str:
    _require(
        value is not None,
        "native policy runtime requires --analytics-preprocessing-contract-sha256",
    )
    resolved = str(value)
    _require(
        re.fullmatch(r"[0-9a-f]{64}", resolved) is not None,
        "analytics preprocessing contract SHA-256 must be a lowercase SHA-256 digest",
    )
    return resolved


def build_publication_pair_plans(
    *,
    config: dict[str, Any],
    datasets: dict[str, Any],
    system: str,
    codec: str,
) -> dict[str, dict[str, Any]]:
    """Build the exact frozen full-matrix pair for one codec."""

    normalized_codec = str(codec).strip().lower().replace("hevc", "h265")
    _require(normalized_codec in {"h264", "h265"}, "unsupported publication codec")
    benchmark = dict(config.get("benchmark") or {})
    declared_datasets = [
        str(value) for value in benchmark.get("benchmark_datasets", [])
    ]
    matching = [
        dataset_name
        for dataset_name in declared_datasets
        if dataset_name in datasets
        and str(datasets[dataset_name].get("codec_variant", ""))
        .strip()
        .lower()
        .replace("hevc", "h265")
        == normalized_codec
    ]
    _require(
        len(matching) == 1,
        f"publication codec {normalized_codec} must bind exactly one frozen benchmark dataset",
    )
    protocol = dict(config.get("protocol") or {})
    cohort_protocol = {
        "warmup_s": int(protocol.get("warmup_s", 0) or 0),
        "measurement_s": int(protocol.get("measurement_s", 0) or 0),
    }
    _require(
        cohort_protocol == {"warmup_s": 30, "measurement_s": 180},
        "full publication cohort protocol drifted",
    )
    primary = dict(benchmark.get("primary_architecture_contrast") or {})
    analytics_queue = dict(primary.get("analytics_queue") or {})
    _require(
        analytics_queue == PRIMARY_ANALYTICS_QUEUE_CONTRACT,
        "full publication analytics queue differs from the frozen contract",
    )
    dataset_name = matching[0]
    dataset = dict(datasets[dataset_name])
    decoder_placement = _decoder_placement_contract(normalized_codec)
    plans = {
        key: build_checkpoint_runtime_plan(
            scenario_name=scenario_name,
            scenario=dict((config.get("scenarios") or {})[scenario_name]),
            dataset_name=dataset_name,
            dataset=dataset,
            system=system,
            cohort_protocol=cohort_protocol,
            analytics_queue=analytics_queue,
            decoder_placement=decoder_placement,
        )
        for scenario_name, key in CHECKPOINT_KEYS.items()
    }
    baseline = plans["baseline"]
    shared = plans["shared"]
    _require(
        baseline["required_branches"] == shared["required_branches"],
        "publication pair analytics branches differ",
    )
    _require(
        len(baseline["streams"]) == len(shared["streams"]) == 6,
        "publication pair must bind six streams per arm",
    )
    for left, right in zip(baseline["streams"], shared["streams"], strict=True):
        left_sources = {
            str(worker["source_sha256"]) for worker in left["workers"]
        }
        right_source = str(right["graph_process"]["source_sha256"])
        _require(
            left_sources == {right_source},
            "publication pair source identities differ",
        )
    return plans


def full_resource_publication_requested(
    config: dict[str, Any],
    *,
    explicit_defer: bool = False,
) -> bool:
    extension = dict((config.get("benchmark") or {}).get("resource_interval_extension") or {})
    return (
        explicit_defer
        or (
        extension.get("status") == "accepted_full_resource_publication_v2"
        and extension.get("current_publication_bundle_scope") == FULL_RESOURCE_PUBLICATION_SCOPE
        and extension.get("publication_bundle_bound") is True
        and extension.get("evidence_accepted") is True
        )
    )


def build_runtime_cohort_audit(
    *,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    topology_kind: str,
    branches: list[str] | tuple[str, ...],
    window_start_timestamp_ms: int,
    window_end_timestamp_ms: int,
    drain_end_timestamp_ms: int,
    admission_records: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    measurement_start_schedule_offset_ns: int | None = None,
    measurement_end_schedule_offset_ns: int | None = None,
) -> dict[str, Any]:
    """Audit runtime coverage; native runs use deterministic decode-order schedule membership."""
    _require(window_start_timestamp_ms < window_end_timestamp_ms, "runtime cohort window is invalid")
    _require(drain_end_timestamp_ms >= window_end_timestamp_ms, "runtime drain boundary is invalid")
    branch_values = tuple(str(value) for value in branches)
    source_rows = [row for row in events if str(row.get("event_kind")) == "source_read"]
    _require(bool(source_rows), "runtime cohort audit requires direct source_read events")
    admissions = list(admission_records)
    schedule_selected = bool(admissions) or any(
        value is not None
        for value in (
            measurement_start_schedule_offset_ns,
            measurement_end_schedule_offset_ns,
        )
    )
    measurement_schedule_fingerprint_sha256: str | None = None
    if schedule_selected:
        _require(bool(admissions), "schedule-selected cohort audit requires direct admission records")
        _require(
            measurement_start_schedule_offset_ns is not None
            and measurement_end_schedule_offset_ns is not None
            and 0 <= measurement_start_schedule_offset_ns < measurement_end_schedule_offset_ns,
            "runtime cohort schedule window is invalid",
        )
        measurement_admissions = [
            row
            for row in admissions
            if measurement_start_schedule_offset_ns
            <= int(row["schedule_offset_ns"])
            < measurement_end_schedule_offset_ns
        ]
        _require(bool(measurement_admissions), "runtime measurement schedule cohort is empty")
        measurement_input_keys = {
            (int(row["stream_id"]), str(row["input_frame_key"]))
            for row in measurement_admissions
        }
        post_window_input_keys = {
            (int(row["stream_id"]), str(row["input_frame_key"]))
            for row in admissions
            if int(row["schedule_offset_ns"]) >= measurement_end_schedule_offset_ns
        }
        measurement_sources = [
            row
            for row in source_rows
            if (int(row["stream_id"]), str(row["input_frame_key"])) in measurement_input_keys
        ]
        post_window_source_count = sum(
            (int(row["stream_id"]), str(row["input_frame_key"])) in post_window_input_keys
            for row in source_rows
        )
        measurement_schedule_fingerprint_sha256 = schedule_fingerprint_for_records(
            measurement_admissions
        )
        cohort_selection_basis = "decode_order_schedule_offset_half_open"
    else:
        measurement_admissions = []
        measurement_sources = [
            row
            for row in source_rows
            if window_start_timestamp_ms <= int(row["timestamp_ms"]) < window_end_timestamp_ms
        ]
        post_window_source_count = sum(
            int(row["timestamp_ms"]) >= window_end_timestamp_ms for row in source_rows
        )
        cohort_selection_basis = "wall_clock_timestamp_half_open_test_fallback"

    frame_sources: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in measurement_sources:
        frame_sources.setdefault((int(row["stream_id"]), str(row["input_frame_key"])), []).append(row)
    joins = {
        (int(row["stream_id"]), str(row["input_frame_key"])): row
        for row in events
        if str(row.get("event_kind")) == "join_complete"
    }
    expected_source_branches = set(branch_values) if topology_kind == INDEPENDENT_PROCESSES else {"shared"}
    complete_source_coverage = {
        key
        for key, rows in frame_sources.items()
        if {str(row["branch_id"]) for row in rows} == expected_source_branches
        and len(rows) == len(expected_source_branches)
    }
    completed = {
        key
        for key in complete_source_coverage
        if key in joins and int(joins[key]["timestamp_ms"]) <= drain_end_timestamp_ms
    }
    source_spreads = [
        max(int(row["timestamp_ms"]) for row in rows) - min(int(row["timestamp_ms"]) for row in rows)
        for key, rows in frame_sources.items()
        if key in complete_source_coverage
    ]

    branch_key_sets_identical: bool | None = None
    if topology_kind == INDEPENDENT_PROCESSES:
        by_stream_branch: dict[tuple[int, str], set[str]] = {}
        streams = {int(row["stream_id"]) for row in measurement_sources}
        for row in measurement_sources:
            by_stream_branch.setdefault(
                (int(row["stream_id"]), str(row["branch_id"])), set()
            ).add(str(row["input_frame_key"]))
        branch_key_sets_identical = bool(streams) and all(
            len(
                {
                    frozenset(by_stream_branch.get((stream_id, branch), set()))
                    for branch in branch_values
                }
            )
            == 1
            and bool(by_stream_branch.get((stream_id, branch_values[0]), set()))
            for stream_id in streams
        )

    external_ingress_schedule_proven = bool(schedule_selected) and all(
        bool(row.get("consumer_coverage_complete")) for row in measurement_admissions
    ) and len(complete_source_coverage) == len(measurement_admissions)
    return {
        "schema_version": 1,
        "artifact_kind": "checkpoint_runtime_cohort_audit",
        "claim_status": "engineering_diagnostic_not_native_ingress_ledger",
        "cohort_selection_basis": cohort_selection_basis,
        "measurement_start_schedule_offset_ns": measurement_start_schedule_offset_ns,
        "measurement_end_schedule_offset_ns": measurement_end_schedule_offset_ns,
        "measurement_schedule_fingerprint_sha256": measurement_schedule_fingerprint_sha256,
        "window_start_timestamp_ms": window_start_timestamp_ms,
        "window_end_timestamp_ms": window_end_timestamp_ms,
        "drain_end_timestamp_ms": drain_end_timestamp_ms,
        "measurement_source_event_count": len(measurement_sources),
        "measurement_input_key_count": len(frame_sources),
        "complete_source_coverage_count": len(complete_source_coverage),
        "completed_join_count": len(completed),
        "post_window_source_event_count": post_window_source_count,
        "max_branch_source_timestamp_spread_ms": max(source_spreads, default=0),
        "baseline_branch_input_key_sets_identical": branch_key_sets_identical,
        "external_ingress_schedule_proven": external_ingress_schedule_proven,
        "accepted_ingress_ledger_written": False,
        "publication_blockers": [
            "runtime cohort rows are not accepted frames.csv or ingress_ledger.csv",
            "runtime audit remains engineering evidence rather than an accepted sidecar",
            "target resource attribution remains unaccepted",
        ],
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    _require(isinstance(value, dict), f"{path}: expected a YAML mapping")
    return value


def _absolute_source(raw: str, project_root: Path) -> Path:
    path = Path(raw)
    return (path if path.is_absolute() else project_root / path).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gst_registry_path(run_id: str, process_id: str) -> str:
    identity = f"{run_id}\0{process_id}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()
    return f"/tmp/vast-gst-registry-{digest}.bin"


def seed_gstreamer_registry_copies(
    specs: list[WorkerLaunchSpec],
    source_specs: list[SourceLaunchSpec],
    *,
    template_path: Path | None = None,
    refresh_hardware_plugins: bool = True,
) -> dict[str, Any]:
    resolved_template = (
        template_path
        if template_path is not None
        else Path(os.environ.get("VAST_GST_REGISTRY_TEMPLATE", ""))
    )
    _require(
        bool(str(resolved_template)) and resolved_template.is_file(),
        "prebuilt GStreamer registry template is missing",
    )
    base_template_sha256 = _sha256_file(resolved_template)
    destinations = [
        Path(spec.environment["GST_REGISTRY"])
        for spec in (*specs, *source_specs)
    ]
    _require(
        len(destinations) == len(set(destinations)),
        "checkpoint processes require distinct GStreamer registry copies",
    )
    _require(
        all(path != resolved_template for path in destinations),
        "checkpoint registry copy must not overwrite its template",
    )
    seeded_template = resolved_template
    hardware_refresh: dict[str, Any] = {
        "performed": False,
        "factory": "",
        "factories_by_codec": {},
    }
    generated_seed = False
    if refresh_hardware_plugins:
        declared_codecs: set[str] = set()
        for spec in (*specs, *source_specs):
            command = list(spec.command)
            _require(
                "--checkpoint-codec" in command,
                "hardware registry refresh requires a codec-bound checkpoint command",
            )
            codec = command[command.index("--checkpoint-codec") + 1]
            checkpoint_decoder_factories(codec)
            declared_codecs.add(codec)
        _require(bool(declared_codecs), "hardware registry refresh requires checkpoint codecs")
        descriptor, seed_name = tempfile.mkstemp(
            prefix="vast-gst-registry-hardware-",
            suffix=".bin",
        )
        os.close(descriptor)
        seeded_template = Path(seed_name)
        seeded_template.unlink(missing_ok=True)
        generated_seed = True
        refresh_environment = os.environ.copy()
        refresh_environment["GST_REGISTRY"] = str(seeded_template)
        refresh_environment.pop("GST_REGISTRY_UPDATE", None)
        selected_factories: dict[str, str] = {}
        for codec in sorted(declared_codecs):
            failures: list[str] = []
            for factory in checkpoint_decoder_factories(codec):
                completed = subprocess.run(
                    ("gst-inspect-1.0", factory),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=refresh_environment,
                )
                if completed.returncode == 0:
                    selected_factories[codec] = factory
                    break
                failures.append(f"{factory}: {completed.stderr.strip()}")
            _require(
                codec in selected_factories,
                f"GPU-aware GStreamer registry exposes no decoder for {codec}: "
                + "; ".join(failures),
            )
        _require(
            seeded_template.is_file() and seeded_template.stat().st_size > 0,
            "GPU-aware GStreamer registry refresh did not create its seed",
        )
        seeded_template.chmod(0o600)
        hardware_refresh = {
            "performed": True,
            "factory": ",".join(selected_factories[codec] for codec in sorted(selected_factories)),
            "factories_by_codec": selected_factories,
        }
    seeded_template_sha256 = _sha256_file(seeded_template)
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seeded_template, destination)
        destination.chmod(0o600)
        _require(
            _sha256_file(destination) == seeded_template_sha256,
            f"GStreamer registry copy digest mismatch: {destination}",
        )
    if generated_seed:
        seeded_template.unlink(missing_ok=True)
    return {
        "schema_version": 1,
        "base_template_path": str(resolved_template),
        "base_template_sha256": base_template_sha256,
        "seeded_template_sha256": seeded_template_sha256,
        "hardware_refresh": hardware_refresh,
        "copy_count": len(destinations),
        "registry_update_disabled": all(
            spec.environment.get("GST_REGISTRY_UPDATE") == "no"
            for spec in (*specs, *source_specs)
        ),
    }


def _binding_environment_name(field: str, branch: str) -> str:
    return f"VAST_CHECKPOINT_ANALYTICS_{field}_{branch}"


def _binding_environment(
    bindings: dict[str, dict[str, str]],
    branches: list[str] | tuple[str, ...],
) -> dict[str, str]:
    environment: dict[str, str] = {}
    for branch in branches:
        binding = bindings[branch]
        for key, field in MODEL_BINDING_ENV_FIELDS.items():
            environment[_binding_environment_name(field, branch)] = binding[key]
    return environment


def _queue_environment(max_buffers: int, branches: list[str] | tuple[str, ...]) -> dict[str, str]:
    return {
        _binding_environment_name("MAX_BUFFERS", branch): str(max_buffers)
        for branch in branches
    }


def _resolve_analytics_queue_max_buffers(
    *,
    plan: dict[str, Any],
    detect_bin: str,
    requested_max_buffers: int | None,
) -> int | None:
    uses_reference_element = REFERENCE_ANALYTICS_ELEMENT in detect_bin
    if not uses_reference_element:
        _require(
            requested_max_buffers is None,
            "--analytics-queue-max-buffers is only valid with vastanalyticsterminal",
        )
        return None

    contract = plan.get("analytics_queue")
    _require(
        contract == PRIMARY_ANALYTICS_QUEUE_CONTRACT,
        "checkpoint analytics queue contract differs from the primary preregistration",
    )
    expected = int(PRIMARY_ANALYTICS_QUEUE_CONTRACT["max_buffers"])
    if requested_max_buffers is not None:
        _require(
            int(requested_max_buffers) == expected,
            "--analytics-queue-max-buffers differs from the preregistered primary value",
        )
    return expected


def load_analytics_model_bindings(
    path: Path,
    *,
    required_branches: list[str] | tuple[str, ...],
) -> dict[str, dict[str, str]]:
    return load_v2_analytics_model_bindings(
        path,
        required_branches=required_branches,
    )
    """Validate branch model artifacts before constructing a native worker command."""
    resolved_manifest = path.resolve()
    raw = _load_yaml(resolved_manifest)
    _require(raw.get("schema_version") == 1, "analytics model manifest schema_version must be 1")
    _require(
        raw.get("artifact_kind") == "checkpoint_analytics_model_bindings",
        "analytics model manifest artifact_kind is invalid",
    )
    raw_branches = raw.get("branches")
    _require(isinstance(raw_branches, dict), "analytics model manifest requires a branches mapping")
    expected = set(required_branches)
    _require(
        set(str(value) for value in raw_branches) == expected,
        "analytics model manifest must exactly cover the required branches",
    )

    bindings: dict[str, dict[str, str]] = {}
    for branch in sorted(expected):
        raw_binding = raw_branches.get(branch)
        _require(isinstance(raw_binding, dict), f"analytics model binding {branch} must be a mapping")
        factory = str(raw_binding.get("factory") or "")
        detector_id = str(raw_binding.get("detector_id") or "")
        _require(factory in {"gvadetect", "object_detect"}, f"{branch}: unsupported detector factory")
        _require(
            re.fullmatch(r"[A-Za-z0-9._-]{1,80}", detector_id) is not None,
            f"{branch}: detector_id must be a stable 1-80 character identifier",
        )

        raw_model_path = str(raw_binding.get("model_path") or "")
        _require(bool(raw_model_path), f"{branch}: model_path is required")
        model_path = Path(raw_model_path)
        model_path = (
            model_path if model_path.is_absolute() else resolved_manifest.parent / model_path
        ).resolve()
        _require(model_path.is_file(), f"{branch}: model artifact was not found: {model_path}")
        _require(
            not any(value in str(model_path) for value in ('"', "\\", "\r", "\n")),
            f"{branch}: model path contains characters unsupported by the GStreamer template",
        )
        model_sha256 = str(raw_binding.get("model_sha256") or "")
        _require(
            re.fullmatch(r"[0-9a-f]{64}", model_sha256) is not None,
            f"{branch}: model_sha256 must be a lowercase SHA-256 digest",
        )
        _require(
            _sha256_file(model_path) == model_sha256,
            f"{branch}: model SHA-256 differs from the manifest",
        )

        weights_path_value = raw_binding.get("weights_path")
        weights_sha256 = str(raw_binding.get("weights_sha256") or "")
        if model_path.suffix == ".xml":
            _require(bool(weights_path_value), f"{branch}: OpenVINO IR requires weights_path")
            weights_path = Path(str(weights_path_value))
            weights_path = (
                weights_path if weights_path.is_absolute() else resolved_manifest.parent / weights_path
            ).resolve()
            _require(
                weights_path == model_path.with_suffix(".bin"),
                f"{branch}: OpenVINO weights must be the sibling .bin artifact",
            )
            _require(weights_path.is_file(), f"{branch}: weights artifact was not found: {weights_path}")
            _require(
                re.fullmatch(r"[0-9a-f]{64}", weights_sha256) is not None,
                f"{branch}: weights_sha256 must be a lowercase SHA-256 digest",
            )
            _require(
                _sha256_file(weights_path) == weights_sha256,
                f"{branch}: weights SHA-256 differs from the manifest",
            )
        else:
            _require(
                (weights_path_value is None or weights_path_value == "")
                and weights_sha256 == "",
                f"{branch}: weights fields are only valid for an OpenVINO .xml model",
            )

        bindings[branch] = {
            "factory": factory,
            "model_path": str(model_path),
            "model_sha256": model_sha256,
            "weights_sha256": weights_sha256,
            "detector_id": detector_id,
        }
    return bindings


def build_gstreamer_source_specs(
    *,
    plan: dict[str, Any],
    source_binary: Path,
    project_root: Path,
    run_id: str,
) -> list[SourceLaunchSpec]:
    _require(plan.get("claim_status") == CLAIM_STATUS, "checkpoint launch plan must remain planning-only")
    sources: list[SourceLaunchSpec] = []
    for source in plan["source_coordinators"]:
        source_id = str(source["process_id"])
        stream_id = int(source["stream_id"])
        command = (
            str(source_binary),
            "--source-path",
            str(_absolute_source(str(source["input_path"]), project_root)),
            "--dataset-id",
            str(plan["dataset"]),
            "--source-sha256",
            str(source["source_sha256"]),
            "--checkpoint-container",
            str(source["source_container"]),
            "--checkpoint-codec",
            str(source["source_codec"]),
            "--source-duration-ns",
            str(source["source_duration_ns"]),
            "--playback-timestamp-scale",
            str(source["playback_timestamp_scale"]),
            "--source-replay",
            "continuous",
            "--logical-stream-id",
            str(stream_id),
        )
        sources.append(
            SourceLaunchSpec(
                source_process_id=source_id,
                stream_id=stream_id,
                dataset_id=str(plan["dataset"]),
                source_sha256=str(source["source_sha256"]),
                command=command,
                environment={
                    "GST_REGISTRY": _gst_registry_path(run_id, source_id),
                    "GST_REGISTRY_UPDATE": "no",
                    "VAST_CHECKPOINT_SOURCE_CONTAINER": str(source["source_container"]),
                    "VAST_CHECKPOINT_SOURCE_CODEC": str(source["source_codec"]),
                    "VAST_CHECKPOINT_SOURCE_DURATION_NS": str(source["source_duration_ns"]),
                    "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE": str(source["playback_timestamp_scale"]),
                    "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                    "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
                },
                native_source=True,
            )
        )
    _require(
        len(sources) == len({source.stream_id for source in sources}),
        "GStreamer source specs must contain exactly one source per stream",
    )
    return sources


def build_gstreamer_worker_specs(
    *,
    plan: dict[str, Any],
    binary: Path,
    output_root: Path,
    project_root: Path,
    run_id: str,
    duration_s: int,
    detect_bin: str,
    analytics_terminal_mode: str = TOPOLOGY_ONLY_ANALYTICS_MODE,
    analytics_model_bindings: dict[str, dict[str, str]] | None = None,
    analytics_queue_max_buffers: int | None = None,
    native_policy: str | None = None,
    native_policy_deadline_ms: float | None = None,
    analytics_execution_socket: Path | str | None = None,
    analytics_preprocessing_contract_sha256: str | None = None,
) -> list[WorkerLaunchSpec]:
    _require(plan.get("claim_status") == CLAIM_STATUS, "checkpoint launch plan must remain planning-only")
    _require(duration_s > 0, "checkpoint engineering duration must be positive")
    _require(
        analytics_terminal_mode in ANALYTICS_TERMINAL_MODES,
        "unsupported checkpoint analytics terminal mode",
    )
    if analytics_terminal_mode == NATIVE_TERMINAL_ANALYTICS_MODE:
        _require(
            detect_bin.strip() != "identity",
            "native checkpoint analytics mode requires a non-identity detect bin",
        )
        _require(
            "{branch}" in detect_bin,
            "native checkpoint analytics detect bin must contain the {branch} placeholder",
        )
    policy_runtime_enabled = (
        native_policy is not None
        or native_policy_deadline_ms is not None
        or analytics_execution_socket is not None
        or analytics_preprocessing_contract_sha256 is not None
    )
    _require(
        not policy_runtime_enabled
        or (
            native_policy == "cpu_only"
            and native_policy_deadline_ms is not None
            and math.isfinite(float(native_policy_deadline_ms))
            and float(native_policy_deadline_ms) > 0
            and analytics_terminal_mode == NATIVE_TERMINAL_ANALYTICS_MODE
            and analytics_execution_socket is not None
            and analytics_preprocessing_contract_sha256 is not None
        ),
        "gstreamer_custom native policy runtime currently supports only exact cpu_only with a positive deadline, an analytics execution socket, and a preprocessing contract SHA-256",
    )
    resolved_execution_socket = (
        _analytics_execution_socket_path(analytics_execution_socket)
        if policy_runtime_enabled
        else None
    )
    resolved_preprocessing_sha256 = (
        _analytics_preprocessing_contract_sha256(
            analytics_preprocessing_contract_sha256
        )
        if policy_runtime_enabled
        else None
    )
    policy_args = (
        (
            "--policy",
            str(native_policy),
            "--deadline-ms",
            str(float(native_policy_deadline_ms)),
        )
        if policy_runtime_enabled
        else ()
    )
    branches = [str(value) for value in plan["required_branches"]]
    worker_codecs = {
        str(owner["source_codec"])
        for stream in plan["streams"]
        for owner in (
            stream["workers"]
            if plan["topology_kind"] == INDEPENDENT_PROCESSES
            else [stream["graph_process"]]
        )
    }
    _require(
        len(worker_codecs) == 1,
        "checkpoint worker specs require one codec across the arm",
    )
    source_codec = next(iter(worker_codecs))
    decoder_placement = dict(plan.get("decoder_placement") or {})
    _require(
        decoder_placement == _decoder_placement_contract(source_codec),
        "checkpoint worker specs require the codec-specific frozen decoder-placement contract",
    )
    allowed_decoder_factories = ",".join(
        str(value) for value in decoder_placement["allowed_factories"]
    )
    uses_reference_element = REFERENCE_ANALYTICS_ELEMENT in detect_bin
    resolved_queue_max_buffers = _resolve_analytics_queue_max_buffers(
        plan=plan,
        detect_bin=detect_bin,
        requested_max_buffers=analytics_queue_max_buffers,
    )
    if uses_reference_element:
        _require(
            analytics_terminal_mode == NATIVE_TERMINAL_ANALYTICS_MODE,
            "vastanalyticsterminal requires native_terminal_socket_v1 mode",
        )
        _require(
            REFERENCE_ANALYTICS_QUEUE in detect_bin,
            "vastanalyticsterminal requires vastanalyticsqueue immediately before each detector",
        )
        _require(
            REFERENCE_ANALYTICS_PLACEHOLDERS.issubset(set(re.findall(r"\{[a-z0-9_]+\}", detect_bin))),
            "vastanalyticsterminal detect bin lacks required branch/model/queue placeholders",
        )
        _require(
            detect_bin.count("name=checkpoint_detector_{branch}") == 1,
            "vastanalyticsterminal requires one unique branch-derived detector name",
        )
        _require(
            analytics_model_bindings is not None and set(analytics_model_bindings) == set(branches),
            "vastanalyticsterminal requires exact branch model bindings",
        )
    binding_values = analytics_model_bindings or {}
    specs: list[WorkerLaunchSpec] = []
    if plan["topology_kind"] == INDEPENDENT_PROCESSES:
        for stream in plan["streams"]:
            stream_id = int(stream["stream_id"])
            for worker in stream["workers"]:
                worker_id = str(worker["process_id"])
                branch = str(worker["branch_id"])
                worker_output = output_root / "workers" / worker_id
                command = (
                    str(binary),
                    "--system",
                    str(plan["system"]),
                    "--role",
                    "checkpoint_branch",
                    "--checkpoint-branch",
                    branch,
                    "--run-id",
                    run_id,
                    "--output-dir",
                    str(worker_output),
                    "--duration",
                    str(duration_s),
                    "--streams",
                    "1",
                    "--logical-stream-id",
                    str(stream_id),
                    "--dataset-id",
                    str(plan["dataset"]),
                    "--source-sha256",
                    str(worker["source_sha256"]),
                    "--checkpoint-container",
                    str(worker["source_container"]),
                    "--checkpoint-codec",
                    str(worker["source_codec"]),
                    "--checkpoint-allowed-decoder-factories",
                    allowed_decoder_factories,
                    "--source-duration-ns",
                    str(worker["source_duration_ns"]),
                    "--source-replay",
                    "continuous",
                    "--detect-bin",
                    detect_bin,
                    "--checkpoint-analytics-mode",
                    analytics_terminal_mode,
                ) + policy_args
                specs.append(
                    WorkerLaunchSpec(
                        worker_id=worker_id,
                        stream_id=stream_id,
                        branch_id=branch,
                        command=command,
                        environment={
                            "GST_REGISTRY": _gst_registry_path(run_id, worker_id),
                            "GST_REGISTRY_UPDATE": "no",
                            "VAST_CHECKPOINT_DATASET_ID": str(plan["dataset"]),
                            "VAST_CHECKPOINT_SOURCE_SHA256": str(worker["source_sha256"]),
                            "VAST_CHECKPOINT_SOURCE_CONTAINER": str(worker["source_container"]),
                            "VAST_CHECKPOINT_SOURCE_CODEC": str(worker["source_codec"]),
                            "VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES": allowed_decoder_factories,
                            "VAST_CHECKPOINT_SOURCE_DURATION_NS": str(worker["source_duration_ns"]),
                            "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                            "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
                            "VAST_CHECKPOINT_ANALYTICS_MODE": analytics_terminal_mode,
                            **(
                                {
                                    "SCHEDULER_POLICY": str(native_policy),
                                    "DEADLINE_MS": str(float(native_policy_deadline_ms)),
                                    "VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET": str(
                                        resolved_execution_socket
                                    ),
                                    **{
                                        _binding_environment_name(
                                            "PREPROCESSING_SHA256", required_branch
                                        ): str(resolved_preprocessing_sha256)
                                        for required_branch in branches
                                    },
                                }
                                if policy_runtime_enabled
                                else {}
                            ),
                            **(
                                _binding_environment(binding_values, [branch])
                                if uses_reference_element
                                else {}
                            ),
                            **(
                                _queue_environment(int(resolved_queue_max_buffers), [branch])
                                if uses_reference_element
                                else {}
                            ),
                        },
                        native_event_source=True,
                    )
                )
    else:
        for stream in plan["streams"]:
            stream_id = int(stream["stream_id"])
            graph = stream["graph_process"]
            worker_id = str(graph["process_id"])
            worker_output = output_root / "workers" / worker_id
            command = (
                str(binary),
                "--system",
                str(plan["system"]),
                "--role",
                "checkpoint_shared",
                "--checkpoint-branches",
                ",".join(branches),
                "--run-id",
                run_id,
                "--output-dir",
                str(worker_output),
                "--duration",
                str(duration_s),
                "--streams",
                "1",
                "--logical-stream-id",
                str(stream_id),
                "--dataset-id",
                str(plan["dataset"]),
                "--source-sha256",
                str(graph["source_sha256"]),
                "--checkpoint-container",
                str(graph["source_container"]),
                "--checkpoint-codec",
                str(graph["source_codec"]),
                "--checkpoint-allowed-decoder-factories",
                allowed_decoder_factories,
                "--source-duration-ns",
                str(graph["source_duration_ns"]),
                "--source-replay",
                "continuous",
                "--detect-bin",
                detect_bin,
                "--checkpoint-analytics-mode",
                analytics_terminal_mode,
            ) + policy_args
            specs.append(
                WorkerLaunchSpec(
                    worker_id=worker_id,
                    stream_id=stream_id,
                    branch_id=None,
                    command=command,
                    environment={
                        "GST_REGISTRY": _gst_registry_path(run_id, worker_id),
                        "GST_REGISTRY_UPDATE": "no",
                        "VAST_CHECKPOINT_BRANCHES": ",".join(branches),
                        "VAST_CHECKPOINT_DATASET_ID": str(plan["dataset"]),
                        "VAST_CHECKPOINT_SOURCE_SHA256": str(graph["source_sha256"]),
                        "VAST_CHECKPOINT_SOURCE_CONTAINER": str(graph["source_container"]),
                        "VAST_CHECKPOINT_SOURCE_CODEC": str(graph["source_codec"]),
                        "VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES": allowed_decoder_factories,
                        "VAST_CHECKPOINT_SOURCE_DURATION_NS": str(graph["source_duration_ns"]),
                        "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                        "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
                        "VAST_CHECKPOINT_ANALYTICS_MODE": analytics_terminal_mode,
                        **(
                            {
                                "SCHEDULER_POLICY": str(native_policy),
                                "DEADLINE_MS": str(float(native_policy_deadline_ms)),
                                "VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET": str(
                                    resolved_execution_socket
                                ),
                                **{
                                    _binding_environment_name(
                                        "PREPROCESSING_SHA256", required_branch
                                    ): str(resolved_preprocessing_sha256)
                                    for required_branch in branches
                                },
                            }
                            if policy_runtime_enabled
                            else {}
                        ),
                        **(
                            _binding_environment(binding_values, branches)
                            if uses_reference_element
                            else {}
                        ),
                        **(
                            _queue_environment(int(resolved_queue_max_buffers), branches)
                            if uses_reference_element
                            else {}
                        ),
                    },
                    native_event_source=True,
                )
            )
    return specs


def _assert_output_location(output_root: Path, project_root: Path) -> None:
    resolved = output_root.resolve()
    forbidden = [project_root / value for value in ("runs", "reports", "build", ".venv", ".pytest_cache")]
    _require(
        all(resolved != path.resolve() and path.resolve() not in resolved.parents for path in forbidden),
        "engineering checkpoint runtime output must not be written under generated VAST directories",
    )


def validate_worker_source_provenance(specs: list[WorkerLaunchSpec]) -> None:
    for spec in specs:
        command = list(spec.command)
        _require(
            "--dataset-streams-json" not in command,
            f"{spec.worker_id}: admission-linked worker must not receive a local source path",
        )
        dataset_id = command[command.index("--dataset-id") + 1]
        source_sha256 = command[command.index("--source-sha256") + 1]
        source_container = command[command.index("--checkpoint-container") + 1]
        source_codec = command[command.index("--checkpoint-codec") + 1]
        allowed_decoder_factories = command[
            command.index("--checkpoint-allowed-decoder-factories") + 1
        ]
        source_duration_ns = command[command.index("--source-duration-ns") + 1]
        source_replay = command[command.index("--source-replay") + 1]
        _require(source_container == "mp4", f"{spec.worker_id}: checkpoint container must be MP4")
        _require(source_codec in {"h264", "h265"}, f"{spec.worker_id}: checkpoint codec is unsupported")
        expected_decoder_factories = ",".join(checkpoint_decoder_factories(source_codec))
        _require(
            allowed_decoder_factories == expected_decoder_factories,
            f"{spec.worker_id}: decoder-factory allowlist differs from codec contract",
        )
        _require(int(source_duration_ns) > 0, f"{spec.worker_id}: source duration must be positive")
        _require(source_replay == "continuous", f"{spec.worker_id}: finite source replay must be continuous")
        _require(
            spec.environment.get("VAST_CHECKPOINT_DATASET_ID") == dataset_id,
            f"{spec.worker_id}: dataset ID differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_SOURCE_SHA256") == source_sha256,
            f"{spec.worker_id}: source SHA-256 differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_SOURCE_CODEC") == source_codec,
            f"{spec.worker_id}: source codec differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES")
            == allowed_decoder_factories,
            f"{spec.worker_id}: decoder-factory allowlist differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_SOURCE_CONTAINER") == source_container,
            f"{spec.worker_id}: source container differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_SOURCE_DURATION_NS") == source_duration_ns,
            f"{spec.worker_id}: source duration differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_SOURCE_REPLAY") == source_replay,
            f"{spec.worker_id}: source replay differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_ADMISSION_MODE") == "native_common_source_coordinator",
            f"{spec.worker_id}: worker is not bound to native common-source admission",
        )


def validate_source_provenance(specs: list[SourceLaunchSpec]) -> None:
    for spec in specs:
        command = list(spec.command)
        source = Path(command[command.index("--source-path") + 1])
        _require(source.is_absolute() and source.is_file(), f"{spec.source_process_id}: source file was not found: {source}")
        dataset_id = command[command.index("--dataset-id") + 1]
        source_sha256 = command[command.index("--source-sha256") + 1]
        source_container = command[command.index("--checkpoint-container") + 1]
        source_codec = command[command.index("--checkpoint-codec") + 1]
        source_duration_ns = command[command.index("--source-duration-ns") + 1]
        playback_timestamp_scale = command[command.index("--playback-timestamp-scale") + 1]
        source_replay = command[command.index("--source-replay") + 1]
        stream_id = int(command[command.index("--logical-stream-id") + 1])
        _require(dataset_id == spec.dataset_id, f"{spec.source_process_id}: source dataset binding drifted")
        _require(source_sha256 == spec.source_sha256, f"{spec.source_process_id}: source SHA-256 binding drifted")
        _require(stream_id == spec.stream_id, f"{spec.source_process_id}: source stream binding drifted")
        _require(source_container == "mp4", f"{spec.source_process_id}: checkpoint container must be MP4")
        _require(source_codec in {"h264", "h265"}, f"{spec.source_process_id}: checkpoint codec is unsupported")
        _require(int(source_duration_ns) > 0, f"{spec.source_process_id}: source duration must be positive")
        _require(int(playback_timestamp_scale) > 0, f"{spec.source_process_id}: playback timestamp scale must be positive")
        _require(source_replay == "continuous", f"{spec.source_process_id}: finite source replay must be continuous")
        _require(spec.native_source, f"{spec.source_process_id}: source process is not marked native")
        _require(
            spec.environment.get("VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE") == playback_timestamp_scale,
            f"{spec.source_process_id}: playback timestamp scale differs between command and runtime environment",
        )
        _require(
            spec.environment.get("VAST_CHECKPOINT_ADMISSION_MODE") == "native_common_source_coordinator",
            f"{spec.source_process_id}: source is not in native common-source admission mode",
        )
        digest = hashlib.sha256()
        with source.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        _require(digest.hexdigest() == source_sha256, f"{spec.source_process_id}: source SHA-256 differs from manifest")


def merge_runtime_stage_contracts(
    *,
    specs: list[WorkerLaunchSpec],
    process_ids: dict[str, int],
    output_root: Path,
    run_id: str,
    topology_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> Path:
    """Merge and validate worker-emitted engineering contracts without creating an accepted sidecar."""
    expected_worker_ids = {spec.worker_id for spec in specs}
    _require(set(process_ids) == expected_worker_ids, "checkpoint process IDs do not cover every worker")
    rows: list[dict[str, str]] = []
    contract_ids: set[str] = set()
    domain_stage_keys: set[tuple[str, str]] = set()
    hostname = socket.gethostname()

    for spec in specs:
        worker_output = Path(spec.command[spec.command.index("--output-dir") + 1])
        fragment = worker_output / "stage_contracts.runtime.csv"
        _require(fragment.is_file(), f"{spec.worker_id}: native stage-contract fragment was not produced")
        with fragment.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            _require(
                reader.fieldnames == STAGE_CONTRACT_COLUMNS,
                f"{spec.worker_id}: stage-contract fragment has an unexpected schema",
            )
            fragment_rows = list(reader)

        expected_domain = f"{hostname}:pid-{process_ids[spec.worker_id]}:worker-{spec.worker_id}"
        expected_stages = (
            {"decode", "preprocess"}
            if spec.branch_id is None
            else {f"decode_{spec.branch_id}", f"preprocess_{spec.branch_id}"}
        )
        _require(
            {str(row["stage"]) for row in fragment_rows} == expected_stages,
            f"{spec.worker_id}: stage-contract fragment must contain exactly decode and preprocess",
        )
        for row in fragment_rows:
            stage = str(row["stage"])
            contract_id = str(row["contract_id"])
            domain_stage = (expected_domain, stage)
            _require(str(row["run_id"]) == run_id, f"{spec.worker_id}: stage-contract run_id mismatch")
            _require(
                str(row["execution_domain"]) == expected_domain,
                f"{spec.worker_id}: stage-contract execution domain is not bound to the launched PID",
            )
            _require(
                contract_id == f"{run_id}:{expected_domain}:{stage}",
                f"{spec.worker_id}: stage-contract ID does not bind run, domain, and stage",
            )
            _require(str(row["telemetry_source"]) == "native", f"{spec.worker_id}: stage contract is not native")
            _require(
                str(row["contract_provenance"]) == "runtime_loaded_configuration",
                f"{spec.worker_id}: stage contract is not runtime-loaded",
            )
            _require(
                str(row["implementation_artifact_provenance"]) == "runtime_loaded_artifacts_v1",
                f"{spec.worker_id}: stage artifact manifest is not runtime-loaded",
            )
            _require(contract_id not in contract_ids, "duplicate runtime stage-contract ID")
            _require(domain_stage not in domain_stage_keys, "duplicate runtime execution-domain/stage contract")
            contract_ids.add(contract_id)
            domain_stage_keys.add(domain_stage)
            rows.append({column: str(row[column]) for column in STAGE_CONTRACT_COLUMNS})

    output_root.mkdir(parents=True, exist_ok=True)
    merged = output_root / "stage_contracts.runtime.csv"
    with merged.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=STAGE_CONTRACT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    topology = pd.DataFrame(topology_events)
    validated = validate_stage_contracts(merged, topology_events=topology)
    _require(len(validated) == len(rows), "runtime stage-contract validation changed row coverage")
    return merged


def merge_runtime_resource_intervals(
    *,
    specs: list[WorkerLaunchSpec],
    output_root: Path,
    run_id: str,
    topology_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> Path:
    """Merge exact native NVDEC/fanout fragments without accepting them for publication."""

    _require(bool(specs), "resource interval merge requires checkpoint workers")
    shared = all(spec.branch_id is None for spec in specs)
    independent = all(spec.branch_id is not None for spec in specs)
    _require(shared or independent, "resource interval merge cannot mix topology kinds")

    topology_by_execution: dict[tuple[str, str, int, int, str], dict[str, Any]] = {}
    expected_nvdec: set[tuple[str, str, int, int, str]] = set()
    expected_fanout: set[tuple[str, str, int, int, str]] = set()
    for raw in topology_events:
        key = (
            str(raw["run_id"]),
            str(raw["trace_id"]),
            int(raw["stream_id"]),
            int(raw["frame_id"]),
            str(raw["execution_id"]),
        )
        _require(key not in topology_by_execution, "runtime topology contains duplicate execution IDs")
        topology_by_execution[key] = raw
        event_kind = str(raw["event_kind"])
        stage = str(raw["stage"])
        if event_kind == "stage_complete" and (stage == "decode" or stage.startswith("decode_")):
            expected_nvdec.add(key)
        if event_kind == "fanout":
            expected_fanout.add(key)
    _require(bool(expected_nvdec), "runtime topology produced no decode executions for NVDEC coverage")
    _require(
        bool(expected_fanout) == shared,
        "runtime fanout topology does not match the worker topology kind",
    )

    rows: list[dict[str, str]] = []
    observed_nvdec: set[tuple[str, str, int, int, str]] = set()
    observed_fanout: set[tuple[str, str, int, int, str]] = set()
    native_event_ids: set[str] = set()
    for spec in specs:
        worker_output = Path(spec.command[spec.command.index("--output-dir") + 1])
        fragment = worker_output / "resource_intervals.runtime.csv"
        _require(
            fragment.is_file() and not fragment.is_symlink(),
            f"{spec.worker_id}: native resource interval fragment was not produced as a regular file",
        )
        with fragment.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            _require(
                reader.fieldnames == RESOURCE_INTERVAL_COLUMNS,
                f"{spec.worker_id}: resource interval fragment has an unexpected schema",
            )
            fragment_rows = list(reader)
        _require(bool(fragment_rows), f"{spec.worker_id}: resource interval fragment is empty")
        for row in fragment_rows:
            integer_columns = (
                "schema_version",
                "interval_contract_version",
                "stream_id",
                "frame_id",
                "host_start_timestamp_ns",
                "host_end_timestamp_ns",
                "duration_ns",
                "bytes",
            )
            _require(
                all(re.fullmatch(r"0|[1-9][0-9]*", str(row[column])) for column in integer_columns),
                f"{spec.worker_id}: resource interval integer is not canonical",
            )
            try:
                schema_version = int(row["schema_version"])
                contract_version = int(row["interval_contract_version"])
                stream_id = int(row["stream_id"])
                frame_id = int(row["frame_id"])
                start_ns = int(row["host_start_timestamp_ns"])
                end_ns = int(row["host_end_timestamp_ns"])
                duration_ns = int(row["duration_ns"])
                payload_bytes = int(row["bytes"])
            except (TypeError, ValueError) as exc:
                raise ContractError(f"{spec.worker_id}: resource interval integer is invalid") from exc
            _require(
                schema_version == TELEMETRY_SCHEMA_VERSION
                and contract_version == RESOURCE_INTERVAL_CONTRACT_VERSION,
                f"{spec.worker_id}: resource interval contract version drifted",
            )
            _require(str(row["run_id"]) == run_id, f"{spec.worker_id}: resource interval run_id mismatch")
            _require(stream_id == int(spec.stream_id), f"{spec.worker_id}: resource interval stream mismatch")
            _require(
                start_ns < end_ns and duration_ns == end_ns - start_ns and payload_bytes > 0,
                f"{spec.worker_id}: native diagnostic interval is invalid",
            )
            native_event_id = str(row["native_event_id"])
            _require(
                re.fullmatch(r"[0-9a-f]{64}", native_event_id) is not None
                and native_event_id not in native_event_ids,
                f"{spec.worker_id}: native event identity is invalid or duplicated",
            )
            native_event_ids.add(native_event_id)
            trace_id = str(row["trace_id"])
            execution_id = str(row["execution_id"])
            branch_id = str(row["branch_id"])
            key = (run_id, trace_id, stream_id, frame_id, execution_id)
            topology = topology_by_execution.get(key)
            _require(topology is not None, f"{spec.worker_id}: resource interval has no topology event")
            _require(
                str(topology["input_frame_key"]) == str(row["input_frame_key"])
                and str(topology["stage"]) == str(row["stage"])
                and str(topology["branch_id"]) == branch_id,
                f"{spec.worker_id}: resource interval topology linkage drifted",
            )
            topology_ns = int(topology["timestamp_ms"]) * 1_000_000
            _require(
                end_ns <= topology_ns + 1_000_000,
                f"{spec.worker_id}: resource interval ends after its topology event",
            )
            try:
                parents = json.loads(str(topology["parent_execution_ids_json"]))
            except json.JSONDecodeError as exc:
                raise ContractError(f"{spec.worker_id}: resource topology parents are invalid") from exc
            _require(isinstance(parents, list) and bool(parents), f"{spec.worker_id}: resource interval has no parent")
            parent_times = []
            for parent_id in parents:
                parent = topology_by_execution.get((run_id, trace_id, stream_id, frame_id, str(parent_id)))
                _require(parent is not None, f"{spec.worker_id}: resource interval parent is missing")
                parent_times.append(int(parent["timestamp_ms"]) * 1_000_000)
            _require(
                start_ns >= max(parent_times),
                f"{spec.worker_id}: resource interval starts before its topology parent",
            )

            component = str(row["component"])
            if component == "nvdec_submit_complete":
                _require(
                    (
                        str(row["direction"]),
                        str(row["counter_scope"]),
                        str(row["duration_provenance"]),
                        str(row["telemetry_source"]),
                    )
                    == (
                        "none",
                        "per_trace_interval",
                        "native_decoder_submit_complete_interval_v1",
                        "native",
                    ),
                    f"{spec.worker_id}: NVDEC interval provenance drifted",
                )
                _require(
                    str(row["device_id"]).startswith("nvdec:")
                    and re.fullmatch(r"[a-z][a-z0-9_.:-]*", str(row["device_id"])) is not None,
                    f"{spec.worker_id}: NVDEC interval device identity drifted",
                )
                _require(
                    str(topology["event_kind"]) == "stage_complete"
                    and (str(row["stage"]) == "decode" or str(row["stage"]).startswith("decode_"))
                    and execution_id == f"{trace_id}:{branch_id}:decode",
                    f"{spec.worker_id}: NVDEC interval execution identity drifted",
                )
                _require(key not in observed_nvdec, "NVDEC execution has more than one interval")
                observed_nvdec.add(key)
            elif component == "fanout":
                _require(shared, f"{spec.worker_id}: independent worker emitted fanout resource evidence")
                _require(
                    (
                        str(row["direction"]),
                        str(row["stage"]),
                        str(row["device_id"]),
                        str(row["counter_scope"]),
                        str(row["duration_provenance"]),
                        str(row["telemetry_source"]),
                    )
                    == (
                        "none",
                        "fanout",
                        "gstreamer:tee-queue",
                        "per_trace_interval",
                        "native_gstreamer_pad_probe_interval_v1",
                        "native",
                    )
                    and str(topology["event_kind"]) == "fanout"
                    and execution_id == f"{trace_id}:{branch_id}:fanout",
                    f"{spec.worker_id}: fanout interval provenance or identity drifted",
                )
                _require(key not in observed_fanout, "fanout execution has more than one interval")
                observed_fanout.add(key)
            else:
                raise ContractError(
                    f"{spec.worker_id}: runtime resource fragment contains unsupported component {component}"
                )
            rows.append({column: str(row[column]) for column in RESOURCE_INTERVAL_COLUMNS})

    _require(observed_nvdec == expected_nvdec, "runtime NVDEC interval coverage is not exact")
    _require(observed_fanout == expected_fanout, "runtime fanout interval coverage is not exact")
    output_root.mkdir(parents=True, exist_ok=True)
    merged = output_root / "resource_intervals.runtime.csv"
    with merged.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=RESOURCE_INTERVAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _require(
        not (output_root / "resource_intervals.csv").exists(),
        "runtime resource merge must not overwrite an accepted resource sidecar",
    )
    return merged


def merge_runtime_fanout_intervals(
    *,
    specs: list[WorkerLaunchSpec],
    output_root: Path,
    run_id: str,
    topology_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> Path | None:
    """Merge native fanout fragments without creating or accepting a publication sidecar."""

    shared_specs = [spec for spec in specs if spec.branch_id is None]
    fragments = [
        Path(spec.command[spec.command.index("--output-dir") + 1])
        / "resource_intervals.runtime.csv"
        for spec in specs
    ]
    if not shared_specs:
        _require(
            not any(path.exists() for path in fragments),
            "independent-process baseline must not emit fanout interval fragments",
        )
        return None
    _require(
        len(shared_specs) == len(specs),
        "fanout interval merge cannot mix shared and independent workers",
    )

    topology_by_execution: dict[tuple[str, str, int, int, str], dict[str, Any]] = {}
    expected_fanout: set[tuple[str, str, int, int, str]] = set()
    for raw in topology_events:
        key = (
            str(raw["run_id"]),
            str(raw["trace_id"]),
            int(raw["stream_id"]),
            int(raw["frame_id"]),
            str(raw["execution_id"]),
        )
        _require(key not in topology_by_execution, "runtime topology contains duplicate execution IDs")
        topology_by_execution[key] = raw
        if str(raw["event_kind"]) == "fanout":
            expected_fanout.add(key)
    _require(bool(expected_fanout), "shared runtime produced no fanout topology events")

    rows: list[dict[str, str]] = []
    observed_fanout: set[tuple[str, str, int, int, str]] = set()
    native_event_ids: set[str] = set()
    for spec, fragment in zip(specs, fragments, strict=True):
        _require(fragment.is_file(), f"{spec.worker_id}: native fanout interval fragment was not produced")
        with fragment.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            _require(
                reader.fieldnames == RESOURCE_INTERVAL_COLUMNS,
                f"{spec.worker_id}: fanout interval fragment has an unexpected schema",
            )
            fragment_rows = list(reader)
        _require(bool(fragment_rows), f"{spec.worker_id}: fanout interval fragment is empty")
        expected_stream_id = int(spec.stream_id)
        for row in fragment_rows:
            _require(
                str(row["schema_version"]) == str(TELEMETRY_SCHEMA_VERSION)
                and str(row["interval_contract_version"])
                == str(RESOURCE_INTERVAL_CONTRACT_VERSION),
                f"{spec.worker_id}: fanout interval contract version drifted",
            )
            _require(str(row["run_id"]) == run_id, f"{spec.worker_id}: fanout run_id mismatch")
            _require(
                str(row["stream_id"]) == str(expected_stream_id),
                f"{spec.worker_id}: fanout stream_id mismatch",
            )
            _require(
                (
                    str(row["component"]),
                    str(row["direction"]),
                    str(row["stage"]),
                    str(row["device_id"]),
                    str(row["counter_scope"]),
                    str(row["duration_provenance"]),
                    str(row["telemetry_source"]),
                )
                == (
                    "fanout",
                    "none",
                    "fanout",
                    "gstreamer:tee-queue",
                    "per_trace_interval",
                    "native_gstreamer_pad_probe_interval_v1",
                    "native",
                ),
                f"{spec.worker_id}: fanout interval provenance drifted",
            )
            try:
                frame_id = int(row["frame_id"])
                start_ns = int(row["host_start_timestamp_ns"])
                end_ns = int(row["host_end_timestamp_ns"])
                duration_ns = int(row["duration_ns"])
                payload_bytes = int(row["bytes"])
            except (TypeError, ValueError) as exc:
                raise ContractError(f"{spec.worker_id}: fanout interval integer is invalid") from exc
            _require(
                all(
                    re.fullmatch(r"0|[1-9][0-9]*", str(row[column]))
                    for column in (
                        "stream_id",
                        "frame_id",
                        "host_start_timestamp_ns",
                        "host_end_timestamp_ns",
                        "duration_ns",
                        "bytes",
                    )
                ),
                f"{spec.worker_id}: fanout interval integer is not canonical",
            )
            _require(
                start_ns < end_ns
                and duration_ns == end_ns - start_ns
                and payload_bytes > 0,
                f"{spec.worker_id}: fanout pad-probe interval is invalid",
            )
            native_event_id = str(row["native_event_id"])
            _require(
                re.fullmatch(r"[0-9a-f]{64}", native_event_id) is not None
                and native_event_id not in native_event_ids,
                f"{spec.worker_id}: fanout native_event_id is invalid or duplicated",
            )
            native_event_ids.add(native_event_id)
            trace_id = str(row["trace_id"])
            branch_id = str(row["branch_id"])
            execution_id = str(row["execution_id"])
            _require(
                execution_id == f"{trace_id}:{branch_id}:fanout",
                f"{spec.worker_id}: fanout execution identity drifted",
            )
            key = (run_id, trace_id, expected_stream_id, frame_id, execution_id)
            topology = topology_by_execution.get(key)
            _require(topology is not None, f"{spec.worker_id}: fanout interval has no topology event")
            _require(
                str(topology["event_kind"]) == "fanout"
                and str(topology["stage"]) == "fanout"
                and str(topology["branch_id"]) == branch_id
                and str(topology["input_frame_key"]) == str(row["input_frame_key"]),
                f"{spec.worker_id}: fanout interval topology linkage drifted",
            )
            topology_ns = int(topology["timestamp_ms"]) * 1_000_000
            _require(
                abs(end_ns - topology_ns) <= 1_000_000,
                f"{spec.worker_id}: fanout interval end differs from topology event",
            )
            parents = json.loads(str(topology["parent_execution_ids_json"]))
            _require(
                isinstance(parents, list) and len(parents) == 1,
                f"{spec.worker_id}: fanout topology must have one preprocess parent",
            )
            parent_key = (run_id, trace_id, expected_stream_id, frame_id, str(parents[0]))
            parent = topology_by_execution.get(parent_key)
            _require(
                parent is not None
                and str(parent["event_kind"]) == "stage_complete"
                and str(parent["stage"]) == "preprocess",
                f"{spec.worker_id}: fanout interval parent is not shared preprocess",
            )
            _require(
                start_ns >= int(parent["timestamp_ms"]) * 1_000_000,
                f"{spec.worker_id}: fanout interval starts before preprocess completes",
            )
            _require(key not in observed_fanout, "fanout execution has more than one interval")
            observed_fanout.add(key)
            rows.append({column: str(row[column]) for column in RESOURCE_INTERVAL_COLUMNS})

    _require(
        observed_fanout == expected_fanout,
        "runtime fanout intervals do not exactly cover shared topology fanout events",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    merged = output_root / "resource_intervals.runtime.csv"
    with merged.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=RESOURCE_INTERVAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _require(
        not (output_root / "resource_intervals.csv").exists(),
        "runtime fanout merge must not create an accepted resource sidecar",
    )
    return merged



def merge_runtime_fanout_work_counters(
    *,
    specs: list[WorkerLaunchSpec],
    output_root: Path,
    run_id: str,
    topology_events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> Path | None:
    """Merge native CPU-work fragments while keeping them runtime-only."""

    shared_specs = [spec for spec in specs if spec.branch_id is None]
    fragments = [
        Path(spec.command[spec.command.index("--output-dir") + 1])
        / "fanout_work_counters.runtime.csv"
        for spec in specs
    ]
    if not shared_specs:
        _require(
            not any(path.exists() for path in fragments),
            "independent-process baseline must not emit fanout work fragments",
        )
        return None
    _require(
        len(shared_specs) == len(specs),
        "fanout work merge cannot mix shared and independent workers",
    )

    expected: dict[tuple[str, int, int, str, str], dict[str, Any]] = {}
    for raw in topology_events:
        if str(raw["event_kind"]) != "fanout":
            continue
        key = (
            str(raw["trace_id"]),
            int(raw["stream_id"]),
            int(raw["frame_id"]),
            str(raw["branch_id"]),
            str(raw["execution_id"]),
        )
        _require(key not in expected, "runtime topology contains duplicate fanout work keys")
        expected[key] = raw
    _require(bool(expected), "shared runtime produced no fanout topology events")

    rows: list[dict[str, str]] = []
    observed: set[tuple[str, int, int, str, str]] = set()
    for spec, fragment in zip(specs, fragments, strict=True):
        _require(fragment.is_file(), f"{spec.worker_id}: native fanout work fragment was not produced")
        with fragment.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            _require(
                reader.fieldnames == FANOUT_WORK_COUNTER_COLUMNS,
                f"{spec.worker_id}: fanout work fragment has an unexpected schema",
            )
            fragment_rows = list(reader)
        _require(bool(fragment_rows), f"{spec.worker_id}: fanout work fragment is empty")
        expected_stream_id = int(spec.stream_id)
        for row in fragment_rows:
            integer_columns = (
                "schema_version",
                "resource_contract_version",
                "stream_id",
                "frame_id",
                "thread_cpu_time_ns",
                "work_units",
            )
            _require(
                all(
                    re.fullmatch(r"0|[1-9][0-9]*", str(row[column]))
                    for column in integer_columns
                ),
                f"{spec.worker_id}: fanout work integer is not canonical",
            )
            try:
                schema_version = int(row["schema_version"])
                contract_version = int(row["resource_contract_version"])
                stream_id = int(row["stream_id"])
                frame_id = int(row["frame_id"])
                thread_cpu_time_ns = int(row["thread_cpu_time_ns"])
                work_units = int(row["work_units"])
            except (TypeError, ValueError) as exc:
                raise ContractError(f"{spec.worker_id}: fanout work integer is invalid") from exc
            _require(
                schema_version == TELEMETRY_SCHEMA_VERSION
                and contract_version == FULL_RESOURCE_CONTRACT_VERSION,
                f"{spec.worker_id}: fanout work contract version drifted",
            )
            _require(str(row["run_id"]) == run_id, f"{spec.worker_id}: fanout work run_id mismatch")
            _require(stream_id == expected_stream_id, f"{spec.worker_id}: fanout work stream mismatch")
            _require(
                thread_cpu_time_ns > 0 and work_units > 0,
                f"{spec.worker_id}: fanout CPU work must be positive",
            )
            _require(
                (
                    str(row["device_id"]),
                    str(row["counter_scope"]),
                    str(row["counter_provenance"]),
                    str(row["telemetry_source"]),
                )
                == (
                    "host:fanout",
                    "per_trace_resource_work",
                    FANOUT_COUNTER_PROVENANCE,
                    "native",
                ),
                f"{spec.worker_id}: fanout work provenance drifted",
            )
            trace_id = str(row["trace_id"])
            branch_id = str(row["branch_id"])
            execution_id = str(row["execution_id"])
            _require(
                execution_id == f"{trace_id}:{branch_id}:fanout",
                f"{spec.worker_id}: fanout work execution identity drifted",
            )
            key = (trace_id, stream_id, frame_id, branch_id, execution_id)
            topology = expected.get(key)
            _require(topology is not None, f"{spec.worker_id}: fanout work has no topology event")
            _require(
                str(topology["input_frame_key"]) == str(row["input_frame_key"]),
                f"{spec.worker_id}: fanout work input-frame linkage drifted",
            )
            _require(key not in observed, "fanout execution has more than one work counter")
            observed.add(key)
            rows.append({column: str(row[column]) for column in FANOUT_WORK_COUNTER_COLUMNS})

    _require(
        observed == set(expected),
        "runtime fanout work counters do not exactly cover shared topology fanout events",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    merged = output_root / "fanout_work_counters.runtime.csv"
    with merged.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FANOUT_WORK_COUNTER_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    _require(
        not (output_root / "fanout_work_counters.csv").exists(),
        "runtime fanout work merge must not create an accepted resource sidecar",
    )
    return merged


def promote_runtime_interval_and_fanout_evidence(
    *,
    runtime_resource_intervals: Path,
    runtime_fanout_work_counters: Path | None,
    output_root: Path,
    expected_run_id: str,
    ingress_ledger: pd.DataFrame,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
    topology_kind: str,
) -> dict[str, Any]:
    """Promote native per-frame evidence; the external NVML collector closes v2 later."""

    accepted_names = ("resource_intervals.csv", "fanout_work_counters.csv")
    output_root.mkdir(parents=True, exist_ok=True)
    existing = [name for name in accepted_names if (output_root / name).exists()]
    if existing:
        raise FullResourceContractError(
            "runtime resource promotion refuses to overwrite accepted sidecars: "
            + ", ".join(existing)
        )
    required_identity = {"run_id", "trace_id", "stream_id", "frame_id"}
    if ingress_ledger.empty or not required_identity.issubset(ingress_ledger.columns):
        raise FullResourceContractError("runtime resource promotion requires accepted ingress rows")
    accepted_keys = {
        (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        for row in ingress_ledger.to_dict(orient="records")
    }
    if {key[0] for key in accepted_keys} != {expected_run_id}:
        raise FullResourceContractError("runtime resource promotion run identity drifted")

    def read_exact(path: Path, columns: list[str], label: str) -> list[dict[str, str]]:
        if path.is_symlink() or not path.is_file():
            raise FullResourceContractError(f"{label} must be a regular runtime file: {path}")
        with path.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != columns:
                raise FullResourceContractError(f"{label} runtime schema drifted")
            rows = list(reader)
        if any(str(row.get("run_id")) != expected_run_id for row in rows):
            raise FullResourceContractError(f"{label} contains another run identity")
        return rows

    interval_rows = read_exact(
        runtime_resource_intervals,
        RESOURCE_INTERVAL_COLUMNS,
        "resource intervals",
    )
    accepted_interval_rows = [
        row
        for row in interval_rows
        if (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        in accepted_keys
    ]
    if not accepted_interval_rows:
        raise FullResourceContractError("accepted cohort has no runtime resource intervals")
    counter_rows = (
        read_exact(
            runtime_fanout_work_counters,
            FANOUT_WORK_COUNTER_COLUMNS,
            "fanout work counters",
        )
        if runtime_fanout_work_counters is not None
        else []
    )
    accepted_counter_rows = [
        row
        for row in counter_rows
        if (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        in accepted_keys
    ]
    expected_fanout_keys = {
        (
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
            str(row["branch_id"]),
            str(row["execution_id"]),
        )
        for row in topology_events.to_dict(orient="records")
        if str(row["event_kind"]) == "fanout"
    }
    require_fanout = topology_kind == "shared_video_dag"
    if require_fanout and runtime_fanout_work_counters is None:
        raise FullResourceContractError("shared runtime lacks fanout work evidence")
    if require_fanout != bool(expected_fanout_keys):
        raise FullResourceContractError("accepted fanout topology coverage is inconsistent")

    try:
        with tempfile.TemporaryDirectory(prefix=".resource-frame-staging-", dir=output_root) as tmp:
            staging = Path(tmp)
            for name, columns, rows in (
                ("resource_intervals.csv", RESOURCE_INTERVAL_COLUMNS, accepted_interval_rows),
                ("fanout_work_counters.csv", FANOUT_WORK_COUNTER_COLUMNS, accepted_counter_rows),
            ):
                with (staging / name).open("w", newline="", encoding="utf-8") as output:
                    writer = csv.DictWriter(output, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(rows)
            intervals = validate_resource_intervals(
                staging / "resource_intervals.csv",
                ingress_ledger=ingress_ledger,
                topology_events=topology_events,
                frame_events=frame_events,
            )
            interval_summary = summarize_resource_interval_extension(
                intervals,
                topology_events=topology_events,
                frame_events=frame_events,
                topology_kind=topology_kind,
            )
            if not bool(interval_summary.get("coverage_complete")):
                raise FullResourceContractError("accepted runtime interval linkage is incomplete")
            validate_fanout_work_counters(
                staging / "fanout_work_counters.csv",
                expected_run_id=expected_run_id,
                expected_fanout_keys=expected_fanout_keys,
                require_rows=require_fanout,
            )
            for name in accepted_names:
                os.replace(staging / name, output_root / name)
    except (OSError, ValueError, KeyError, ResourceIntervalContractError) as exc:
        raise FullResourceContractError(f"runtime resource promotion failed validation: {exc}") from exc
    return {
        "interval_summary": interval_summary,
        "accepted_paths": {name: str(output_root / name) for name in accepted_names},
        "accepted_interval_count": len(accepted_interval_rows),
        "accepted_fanout_work_count": len(accepted_counter_rows),
        "hardware_samples_pending_external_collector": True,
    }


def promote_runtime_full_resource_evidence(
    *,
    runtime_resource_intervals: Path,
    runtime_hardware_samples: Path,
    runtime_fanout_work_counters: Path | None,
    output_root: Path,
    expected_run_id: str,
    ingress_ledger: pd.DataFrame,
    topology_events: pd.DataFrame,
    frame_events: pd.DataFrame,
    topology_kind: str,
) -> dict[str, Any]:
    """Validate a closed accepted cohort in staging before exposing v2 sidecars."""

    accepted_names = (
        "resource_intervals.csv",
        "hardware_resource_samples.csv",
        "fanout_work_counters.csv",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    existing = [name for name in accepted_names if (output_root / name).exists()]
    if existing:
        raise FullResourceContractError(
            "full-resource promotion refuses to overwrite accepted sidecars: "
            + ", ".join(existing)
        )
    required_identity = {"run_id", "trace_id", "stream_id", "frame_id"}
    if ingress_ledger.empty or not required_identity.issubset(ingress_ledger.columns):
        raise FullResourceContractError("full-resource promotion requires an accepted ingress cohort")
    accepted_keys = {
        (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        for row in ingress_ledger.to_dict(orient="records")
    }
    if not accepted_keys or {key[0] for key in accepted_keys} != {expected_run_id}:
        raise FullResourceContractError("accepted ingress cohort run identity drifted")

    def read_exact(path: Path, columns: list[str], label: str) -> list[dict[str, str]]:
        if path.is_symlink() or not path.is_file():
            raise FullResourceContractError(f"{label} must be a regular runtime file: {path}")
        with path.open("r", newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != columns:
                raise FullResourceContractError(f"{label} runtime schema drifted")
            rows = list(reader)
        if any(str(row.get("run_id")) != expected_run_id for row in rows):
            raise FullResourceContractError(f"{label} contains another run identity")
        return rows

    interval_rows = read_exact(
        runtime_resource_intervals,
        RESOURCE_INTERVAL_COLUMNS,
        "resource intervals",
    )
    accepted_interval_rows = [
        row
        for row in interval_rows
        if (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        in accepted_keys
    ]
    if not accepted_interval_rows:
        raise FullResourceContractError("accepted cohort has no native resource intervals")
    hardware_rows = read_exact(
        runtime_hardware_samples,
        HARDWARE_RESOURCE_SAMPLE_COLUMNS,
        "hardware resource samples",
    )
    counter_rows = (
        read_exact(
            runtime_fanout_work_counters,
            FANOUT_WORK_COUNTER_COLUMNS,
            "fanout work counters",
        )
        if runtime_fanout_work_counters is not None
        else []
    )
    accepted_counter_rows = [
        row
        for row in counter_rows
        if (
            str(row["run_id"]),
            str(row["trace_id"]),
            int(row["stream_id"]),
            int(row["frame_id"]),
        )
        in accepted_keys
    ]
    if topology_kind == "shared_video_dag" and runtime_fanout_work_counters is None:
        raise FullResourceContractError("shared topology lacks native fanout work counters")
    if topology_kind == "independent_processes" and accepted_counter_rows:
        raise FullResourceContractError("independent topology reported fanout work counters")

    try:
        with tempfile.TemporaryDirectory(prefix=".resource-v2-staging-", dir=output_root) as tmp:
            staging = Path(tmp)
            for name, columns, rows in (
                ("resource_intervals.csv", RESOURCE_INTERVAL_COLUMNS, accepted_interval_rows),
                ("hardware_resource_samples.csv", HARDWARE_RESOURCE_SAMPLE_COLUMNS, hardware_rows),
                ("fanout_work_counters.csv", FANOUT_WORK_COUNTER_COLUMNS, accepted_counter_rows),
            ):
                with (staging / name).open("w", newline="", encoding="utf-8") as output:
                    writer = csv.DictWriter(output, fieldnames=columns)
                    writer.writeheader()
                    writer.writerows(rows)
            evidence = validate_full_resource_evidence(
                staging,
                expected_run_id=expected_run_id,
                ingress_ledger=ingress_ledger,
                topology_events=topology_events,
                frame_events=frame_events,
                topology_kind=topology_kind,
            )
            for name in accepted_names:
                os.replace(staging / name, output_root / name)
    except (OSError, ValueError, KeyError, ResourceIntervalContractError) as exc:
        raise FullResourceContractError(f"full-resource promotion failed validation: {exc}") from exc
    return {
        "summary": evidence["summary"],
        "accepted_paths": {name: str(output_root / name) for name in accepted_names},
        "accepted_interval_count": len(accepted_interval_rows),
        "accepted_fanout_work_count": len(accepted_counter_rows),
    }


def write_runtime_branch_terminals(
    *,
    records: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ingress_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    required_branches: list[str] | tuple[str, ...],
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    """Persist direct protocol-v3 outcomes without creating an accepted sidecar."""
    branch_set = {str(branch) for branch in required_branches}
    _require(bool(branch_set), "runtime branch terminal audit requires branches")
    ledger_by_key = {
        (str(row["trace_id"]), int(row["stream_id"]), int(row["frame_id"])): row
        for row in ingress_rows
    }
    _require(
        len(ledger_by_key) == len(ingress_rows),
        "runtime branch terminal audit found duplicate ingress linkage",
    )
    grouped: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record["trace_id"]),
            int(record["stream_id"]),
            int(record["frame_id"]),
        )
        if key not in ledger_by_key:
            continue
        _require(
            int(record["runtime_protocol_version"]) == 3,
            "runtime branch terminal artifact accepts only direct protocol-v3 outcomes",
        )
        _require(
            str(record["telemetry_source"]) == "native",
            "runtime branch terminal outcome is not adapter-native",
        )
        _require(
            str(record["branch_id"]) in branch_set,
            "runtime branch terminal selected an undeclared branch",
        )
        ledger = ledger_by_key[key]
        _require(
            str(record["run_id"]) == str(ledger["run_id"])
            and str(record["input_frame_key"]) == str(ledger["input_frame_key"]),
            "runtime branch terminal identity does not match ingress linkage",
        )
        _require(
            str(record["terminal_status"]) in {"completed", "drop"},
            "runtime branch terminal status is unsupported",
        )
        _require(
            int(record["objects"]) >= 0
            and not (str(record["terminal_status"]) == "drop" and int(record["objects"]) != 0),
            "runtime branch terminal object count is invalid",
        )
        _require(
            all(str(record[field]).strip() for field in ("detector", "backend", "terminal_reason")),
            "runtime branch terminal provenance fields are empty",
        )
        grouped.setdefault(key, []).append(record)

    rows: list[dict[str, Any]] = []
    fully_terminalized_count = 0
    native_drop_event_count = 0
    for key, ledger in ledger_by_key.items():
        terminal_records = grouped.get(key, [])
        observed = {str(record["branch_id"]) for record in terminal_records}
        _require(
            len(observed) == len(terminal_records),
            "runtime branch terminal audit found duplicate branch outcomes",
        )
        ledger_status = str(ledger["terminal_status"])
        if ledger_status in {"completed", "drop"}:
            _require(
                observed == branch_set,
                "runtime terminal ingress row lacks a protocol-v3 outcome for every branch",
            )
            fully_terminalized_count += 1
            statuses = {str(record["terminal_status"]) for record in terminal_records}
            if ledger_status == "completed":
                _require(
                    statuses == {"completed"},
                    "runtime completed ingress row contains a non-completed branch",
                )
            else:
                _require(
                    "drop" in statuses,
                    "runtime drop ingress row has no native branch drop",
                )
        else:
            _require(ledger_status == "censored", "runtime ingress terminal status is unsupported")
            _require(
                all(str(record["terminal_status"]) != "drop" for record in terminal_records),
                "runtime censored ingress row contains a native branch drop",
            )
            _require(
                observed != branch_set,
                "runtime fully terminalized branch set may not remain censored",
            )
        if terminal_records:
            _require(
                all(
                    int(ledger["ingress_timestamp_ms"])
                    <= int(record["terminal_timestamp_ms"])
                    <= int(ledger["drain_end_timestamp_ms"])
                    for record in terminal_records
                ),
                "runtime branch terminal occurred outside the ingress/drain interval",
            )
        if ledger_status in {"completed", "drop"}:
            branch_terminal_max = max(
                int(record["terminal_timestamp_ms"]) for record in terminal_records
            )
            aggregate_terminal = int(ledger["terminal_timestamp_ms"])
            if ledger_status == "completed":
                _require(
                    aggregate_terminal >= branch_terminal_max,
                    "runtime join timestamp precedes a branch outcome",
                )
            else:
                _require(
                    aggregate_terminal == branch_terminal_max,
                    "runtime drop timestamp does not match branch outcomes",
                )
        for record in terminal_records:
            terminal_status = str(record["terminal_status"])
            if terminal_status == "drop":
                native_drop_event_count += 1
            rows.append(
                {
                    "schema_version": 2,
                    "run_id": str(record["run_id"]),
                    "cohort_id": str(ledger["cohort_id"]),
                    "trace_id": str(record["trace_id"]),
                    "input_frame_key": str(record["input_frame_key"]),
                    "stream_id": int(record["stream_id"]),
                    "frame_id": int(record["frame_id"]),
                    "branch_id": str(record["branch_id"]),
                    "terminal_status": terminal_status,
                    "terminal_timestamp_ms": int(record["terminal_timestamp_ms"]),
                    "objects": int(record["objects"]),
                    "detector": str(record["detector"]),
                    "backend": str(record["backend"]),
                    "terminal_reason": str(record["terminal_reason"]),
                    "terminal_provenance": (
                        "native_drop_event" if terminal_status == "drop" else "native_completion_event"
                    ),
                    "telemetry_source": "engineering_runtime",
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "branch_terminals.runtime.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=BRANCH_TERMINAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    audit = {
        "schema_version": 1,
        "artifact_kind": "checkpoint_runtime_branch_terminal_audit",
        "claim_status": "runtime_protocol_v3_not_accepted_branch_terminal_sidecar",
        "runtime_protocol_version": 3,
        "measurement_ingress_count": len(ledger_by_key),
        "branch_terminal_event_count": len(rows),
        "fully_terminalized_ingress_count": fully_terminalized_count,
        "native_drop_event_count": native_drop_event_count,
        "accepted_branch_terminals_written": False,
        "publication_blockers": [
            "branch_terminals.runtime.csv uses engineering_runtime telemetry_source",
            "accepted frames.csv and accepted ingress_ledger.csv linkage are absent",
            "target KPP execution and resource attribution are not accepted",
        ],
    }
    return path, audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or inspect the native GStreamer checkpoint runtime.")
    parser.add_argument("--config", type=Path, default=Path("configs/experiments.yaml"))
    parser.add_argument("--datasets", type=Path, default=Path("configs/datasets.yaml"))
    parser.add_argument("--scenario", choices=tuple(CHECKPOINT_KEYS), required=True)
    parser.add_argument("--system", default="gstreamer_custom")
    parser.add_argument("--codec", choices=("h264", "h265"))
    parser.add_argument("--policy")
    parser.add_argument("--deadline-ms", type=float)
    parser.add_argument(
        "--analytics-execution-socket",
        type=Path,
        help="Absolute canonical AF_UNIX pathname of the pre-started analytics bridge",
    )
    parser.add_argument(
        "--analytics-preprocessing-contract-sha256",
        help="Exact lowercase SHA-256 of the frozen GStreamer preprocessing contract",
    )
    parser.add_argument("--binary", type=Path, default=Path("build/bin/vast_native_gst_probe"))
    parser.add_argument("--source-binary", type=Path, default=Path("build/bin/vast_checkpoint_source"))
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/vast-checkpoint-engineering-runtime"))
    parser.add_argument("--run-id", default="checkpoint-engineering-runtime")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--warmup", type=float, default=0.0)
    parser.add_argument("--drain-timeout", type=float, default=10.0)
    parser.add_argument("--ready-timeout", type=float, default=300.0)
    parser.add_argument("--start-lead-ms", type=int, default=100)
    parser.add_argument("--use-preregistered-window", action="store_true")
    parser.add_argument("--detect-bin", default="identity")
    parser.add_argument(
        "--analytics-model-manifest",
        type=Path,
        help="Strict branch model/digest bindings required by vastanalyticsterminal",
    )
    parser.add_argument("--policy-capability-manifest", type=Path)
    parser.add_argument("--policy-calibration", type=Path)
    parser.add_argument("--static-hybrid-map", type=Path)
    parser.add_argument(
        "--analytics-queue-max-buffers",
        type=int,
        help="Optional assertion; must equal the primary preregistered waiting-buffer capacity",
    )
    parser.add_argument(
        "--checkpoint-analytics-mode",
        choices=tuple(sorted(ANALYTICS_TERMINAL_MODES)),
        default=TOPOLOGY_ONLY_ANALYTICS_MODE,
    )
    execution_mode = parser.add_mutually_exclusive_group()
    execution_mode.add_argument("--execute-engineering-runtime", action="store_true")
    execution_mode.add_argument("--execute-publication-runtime", action="store_true")
    parser.add_argument(
        "--defer-full-resource-acceptance",
        action="store_true",
        help="Emit only the candidate/resource evidence; the parent transaction commits acceptance last.",
    )
    args = parser.parse_args()

    project_root = args.config.resolve().parents[1]
    config = _load_yaml(args.config)
    datasets = dict(_load_yaml(args.datasets).get("datasets") or {})
    publication_mode = bool(args.execute_publication_runtime)
    if publication_mode:
        _require(args.codec is not None, "publication runtime requires exact --codec")
        _require(
            args.analytics_execution_socket is not None,
            "publication runtime requires exact --analytics-execution-socket",
        )
        _require(
            args.analytics_preprocessing_contract_sha256 is not None,
            "publication runtime requires exact --analytics-preprocessing-contract-sha256",
        )
        _require(
            args.system == "gstreamer_custom",
            "checkpoint publication runtime is topology-specific to gstreamer_custom",
        )
        pair = build_publication_pair_plans(
            config=config,
            datasets=datasets,
            system=args.system,
            codec=str(args.codec),
        )
    else:
        pair = build_primary_pair_plans(
            config=config,
            datasets=datasets,
            system=args.system,
        )
    plan = pair[CHECKPOINT_KEYS[args.scenario]]
    primary = dict((config.get("benchmark") or {}).get("primary_architecture_contrast") or {})
    dataset_identity = dict(datasets[str(plan["dataset"])])
    if publication_mode:
        _require(args.policy is not None, "publication runtime requires exact --policy")
        _require(args.deadline_ms is not None, "publication runtime requires exact --deadline-ms")
        _require(args.codec == str(dataset_identity.get("codec_variant")), "publication codec differs from dataset")
        configured_policies = tuple(
            str(value)
            for value in (config.get("benchmark") or {}).get("scheduler_policies", [])
        )
        _require(
            configured_policies == POLICIES and str(args.policy) in POLICIES,
            "publication policy differs from the frozen seven-policy matrix",
        )
        configured_deadlines = tuple(
            float(value)
            for value in (config.get("benchmark") or {}).get("deadline_ms", [])
        )
        _require(
            len(configured_deadlines) == 5
            and any(
                math.isclose(
                    float(args.deadline_ms),
                    expected,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                for expected in configured_deadlines
            ),
            "publication deadline differs from the frozen full matrix",
        )
    full_resource_requested = publication_mode and full_resource_publication_requested(
        config,
        explicit_defer=args.defer_full_resource_acceptance,
    )
    runtime_output_dir = (
        args.output_dir / "native_runtime"
        if publication_mode
        else args.output_dir
    )
    runtime_warmup_s = (
        float(plan["cohort_protocol"]["warmup_s"])
        if args.use_preregistered_window
        else float(args.warmup)
    )
    runtime_measurement_s = (
        float(plan["cohort_protocol"]["measurement_s"])
        if args.use_preregistered_window
        else float(args.duration)
    )
    _require(runtime_warmup_s > 0, "decoder placement verification requires a positive engineering warmup")
    _require(runtime_measurement_s > 0, "engineering checkpoint measurement must be positive")
    _require(args.drain_timeout > 0, "engineering checkpoint drain timeout must be positive")
    _require(args.ready_timeout > 0, "engineering checkpoint READY timeout must be positive")
    _require(args.start_lead_ms >= 0, "engineering checkpoint start lead must be non-negative")
    analytics_model_bindings = None
    if args.analytics_model_manifest is not None:
        _require(
            args.checkpoint_analytics_mode == NATIVE_TERMINAL_ANALYTICS_MODE,
            "analytics model manifest is only valid in native terminal mode",
        )
        analytics_model_bindings = load_analytics_model_bindings(
            args.analytics_model_manifest,
            required_branches=plan["required_branches"],
        )
    native_policy_runtime: NativePolicyRuntimeCoordinator | None = None
    native_policy_capability_assessment: dict[str, Any] | None = None
    if publication_mode:
        _require(
            args.analytics_model_manifest is not None and analytics_model_bindings is not None,
            "publication policy runtime requires an exact analytics execution manifest",
        )
        native_policy_capability_assessment = assess_gstreamer_native_policy_execution_manifest(
            _load_yaml(args.analytics_model_manifest)
        )
        _require(
            str(args.policy) in native_policy_capability_assessment["eligible_policies"],
            "native gstreamer policy is blocked by execution capabilities: "
            + ",".join(native_policy_capability_assessment["blockers"][:8]),
        )
        _require(
            args.policy == "cpu_only",
            "native gstreamer GPU/mixed policy paths require frozen TensorRT/CUDA parity bindings",
        )
        _require(
            args.policy_capability_manifest is not None,
            "publication policy capability manifest is required",
        )
        _require(args.policy_calibration is not None, "publication policy calibration is required")
        capability_manifest = _load_yaml(args.policy_capability_manifest)
        calibration = _load_yaml(args.policy_calibration)
        static_hybrid_map = (
            _load_yaml(args.static_hybrid_map)
            if args.static_hybrid_map is not None
            else None
        )
        require_exact_native_cpu_capability_bindings(
            binary=args.binary,
            analytics_bindings=analytics_model_bindings,
            capability_manifest=capability_manifest,
        )
        native_policy_runtime = NativePolicyRuntimeCoordinator(
            run_id=args.run_id,
            arm_id=(
                f"{args.run_id}:{args.scenario}:{args.codec}:{args.policy}:"
                f"{float(args.deadline_ms)}"
            ),
            system=args.system,
            scenario=args.scenario,
            codec=str(args.codec),
            policy=str(args.policy),
            deadline_ms=float(args.deadline_ms),
            branches=plan["required_branches"],
            capability_manifest=capability_manifest,
            calibration=calibration,
            static_hybrid_map=static_hybrid_map,
        )
    resolved_queue_max_buffers = _resolve_analytics_queue_max_buffers(
        plan=plan,
        detect_bin=args.detect_bin,
        requested_max_buffers=args.analytics_queue_max_buffers,
    )
    specs = build_gstreamer_worker_specs(
        plan=plan,
        binary=args.binary.resolve(),
        output_root=runtime_output_dir.resolve(),
        project_root=project_root,
        run_id=args.run_id,
        duration_s=args.duration,
        detect_bin=args.detect_bin,
        analytics_terminal_mode=args.checkpoint_analytics_mode,
        analytics_model_bindings=analytics_model_bindings,
        analytics_queue_max_buffers=resolved_queue_max_buffers,
        native_policy=(str(args.policy) if native_policy_runtime is not None else None),
        native_policy_deadline_ms=(
            float(args.deadline_ms) if native_policy_runtime is not None else None
        ),
        analytics_execution_socket=(
            args.analytics_execution_socket
            if native_policy_runtime is not None
            else None
        ),
        analytics_preprocessing_contract_sha256=(
            args.analytics_preprocessing_contract_sha256
            if native_policy_runtime is not None
            else None
        ),
    )
    source_specs = build_gstreamer_source_specs(
        plan=plan,
        source_binary=args.source_binary.resolve(),
        project_root=project_root,
        run_id=args.run_id,
    )
    preview = {
        "status": (
            "publication_runtime_ready_preview"
            if publication_mode
            else ENGINEERING_STATUS
        ),
        "scenario": args.scenario,
        "topology_kind": plan["topology_kind"],
        "cohort_protocol": plan["cohort_protocol"],
        "frame_identity": plan["frame_identity"],
        "source_playback": plan["source_playback"],
        "external_admission": plan["external_admission"],
        "source_coordinator_count": len(source_specs),
        "source_mode": (
            "native_framed_common_source_publication_v1"
            if publication_mode
            else "native_framed_common_source_engineering_unaccepted"
        ),
        "analytics_terminal_mode": args.checkpoint_analytics_mode,
        "native_branch_terminal_bridge_enabled": (
            args.checkpoint_analytics_mode == NATIVE_TERMINAL_ANALYTICS_MODE
        ),
        "analytics_model_manifest": (
            str(args.analytics_model_manifest.resolve())
            if args.analytics_model_manifest is not None
            else None
        ),
        "analytics_model_bindings": analytics_model_bindings,
        "native_policy_capability_assessment": native_policy_capability_assessment,
        "analytics_execution_socket": (
            str(args.analytics_execution_socket)
            if native_policy_runtime is not None
            else None
        ),
        "analytics_preprocessing_contract_sha256": (
            str(args.analytics_preprocessing_contract_sha256)
            if native_policy_runtime is not None
            else None
        ),
        "analytics_queue": plan["analytics_queue"],
        "decoder_placement": plan["decoder_placement"],
        "decoder_placement_runtime_gate": plan["decoder_placement_runtime_gate"],
        "analytics_queue_max_buffers": resolved_queue_max_buffers,
        "runtime_lifecycle": {
            "synchronized": True,
            "warmup_s": runtime_warmup_s,
            "measurement_s": runtime_measurement_s,
            "drain_timeout_s": float(args.drain_timeout),
            "ready_timeout_s": float(args.ready_timeout),
            "start_lead_ms": int(args.start_lead_ms),
            "preregistered_window_selected": bool(args.use_preregistered_window),
            "decoder_placement_verification_required": True,
        },
        "worker_count": len(specs),
        "worker_commands": [list(spec.command) for spec in specs],
        "source_commands": [list(spec.command) for spec in source_specs],
        "accepted_benchmark_sidecars_written": False,
        "full_resource_publication_requested": full_resource_requested,
    }
    if not args.execute_engineering_runtime and not args.execute_publication_runtime:
        print(json.dumps(preview, indent=2, sort_keys=True))
        return 0

    if publication_mode:
        _require(
            plan.get("benchmark_status") == "supported",
            "publication checkpoint runtime requires benchmark_status=supported",
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
    else:
        _require(
            plan.get("benchmark_status") == "blocked_topology",
            "engineering checkpoint runtime requires benchmark_status=blocked_topology",
        )
        _assert_output_location(args.output_dir, project_root)
    _require(args.binary.is_file(), f"native GStreamer probe binary was not found: {args.binary}")
    _require(args.source_binary.is_file(), f"native GStreamer source binary was not found: {args.source_binary}")
    validate_worker_source_provenance(specs)
    validate_source_provenance(source_specs)
    registry_seed = seed_gstreamer_registry_copies(specs, source_specs)
    telemetry_sink_preexisting_entry_count = (
        sum(1 for _ in runtime_output_dir.iterdir()) if runtime_output_dir.exists() else 0
    )
    _require(
        telemetry_sink_preexisting_entry_count == 0,
        "checkpoint reset contract requires a new empty output directory for every arm",
    )
    telemetry_sink_id = hashlib.sha256(
        f"{args.run_id}\0{runtime_output_dir.resolve()}".encode("utf-8")
    ).hexdigest()
    for spec in specs:
        Path(spec.command[spec.command.index("--output-dir") + 1]).mkdir(parents=True, exist_ok=True)
    runtime_output_dir.mkdir(parents=True, exist_ok=True)
    topology_path = runtime_output_dir / "topology_events.runtime.csv"
    with topology_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=TOPOLOGY_EVENT_COLUMNS)
        writer.writeheader()

        def write_event(row: dict[str, Any]) -> None:
            writer.writerow(row)
            output.flush()

        result = run_worker_processes(
            run_id=args.run_id,
            topology_kind=plan["topology_kind"],
            branches=plan["required_branches"],
            specs=specs,
            source_specs=source_specs,
            timeout_s=max(
                30.0,
                runtime_warmup_s + runtime_measurement_s + float(args.drain_timeout) + 20.0,
            ),
            ready_timeout_s=float(args.ready_timeout),
            on_event=write_event,
            synchronized_lifecycle=True,
            warmup_s=runtime_warmup_s,
            measurement_s=runtime_measurement_s,
            drain_timeout_s=float(args.drain_timeout),
            start_lead_s=float(args.start_lead_ms) / 1000.0,
            require_decoder_placement_verification=True,
            measurement_end_boundary_guard_ns=int(
                plan["source_playback"]["measurement_end_boundary_guard_ns"]
            ),
            policy_socket_handler=(
                native_policy_runtime.serve_worker_socket
                if native_policy_runtime is not None
                else None
            ),
        )
    native_policy_promotion: dict[str, Any] | None = None
    if native_policy_runtime is not None:
        native_policy_promotion = native_policy_runtime.promote(
            args.output_dir,
            canonical_frames=canonical_frames_from_events(result.events),
        )
        result = dataclasses.replace(
            result,
            events=native_policy_runtime.enrich_runtime_events(result.events),
        )
    cohort_audit = build_runtime_cohort_audit(
        events=result.events,
        topology_kind=plan["topology_kind"],
        branches=plan["required_branches"],
        window_start_timestamp_ms=result.window_start_timestamp_ms,
        window_end_timestamp_ms=result.window_end_timestamp_ms,
        drain_end_timestamp_ms=result.drain_end_timestamp_ms,
        admission_records=result.admission_records,
        measurement_start_schedule_offset_ns=result.measurement_start_schedule_offset_ns,
        measurement_end_schedule_offset_ns=result.measurement_end_schedule_offset_ns,
    )
    cohort_audit_path = runtime_output_dir / "cohort_audit.runtime.json"
    cohort_audit_path.write_text(
        json.dumps(cohort_audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    admission_audit_path: Path | None = None
    if result.admission_audit is not None:
        admission_audit_path = runtime_output_dir / "direct_admission_audit.runtime.json"
        admission_audit_path.write_text(
            json.dumps(result.admission_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    terminal_ingress_path: Path | None = None
    terminal_admission_audit_path: Path | None = None
    if result.terminal_admission_audit is not None:
        terminal_ingress_path = runtime_output_dir / "ingress_ledger.runtime.csv"
        with terminal_ingress_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=INGRESS_LEDGER_COLUMNS)
            writer.writeheader()
            writer.writerows(result.terminal_ingress_rows)
        terminal_admission_audit_path = runtime_output_dir / "terminal_admission_audit.runtime.json"
        terminal_admission_audit_path.write_text(
            json.dumps(result.terminal_admission_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    runtime_reset_evidence_path: Path | None = None
    runtime_reset_audit_path: Path | None = None
    runtime_reset_audit: dict[str, Any] | None = None
    runtime_reset_rows: list[dict[str, Any]] = []
    if result.terminal_ingress_rows:
        runtime_reset_rows, runtime_reset_audit = build_runtime_reset_evidence(
            run_id=args.run_id,
            topology_kind=plan["topology_kind"],
            branches=plan["required_branches"],
            specs=specs,
            source_specs=source_specs,
            result=result,
            telemetry_sink_id=telemetry_sink_id,
            telemetry_sink_preexisting_entry_count=telemetry_sink_preexisting_entry_count,
        )
        runtime_reset_evidence_path = runtime_output_dir / "reset_evidence.runtime.csv"
        with runtime_reset_evidence_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=RESET_EVIDENCE_COLUMNS)
            writer.writeheader()
            writer.writerows(runtime_reset_rows)
        runtime_reset_audit_path = runtime_output_dir / "reset_evidence_audit.runtime.json"
        runtime_reset_audit_path.write_text(
            json.dumps(runtime_reset_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    runtime_stage_contract_path: Path | None = None
    runtime_resource_interval_path: Path | None = None
    runtime_fanout_work_path: Path | None = None
    if not result.unresolved_frames:
        runtime_stage_contract_path = merge_runtime_stage_contracts(
            specs=specs,
            process_ids=result.process_ids,
            output_root=runtime_output_dir,
            run_id=args.run_id,
            topology_events=result.events,
        )
        runtime_resource_interval_path = merge_runtime_resource_intervals(
            specs=specs,
            output_root=runtime_output_dir,
            run_id=args.run_id,
            topology_events=result.events,
        )
        runtime_fanout_work_path = merge_runtime_fanout_work_counters(
            specs=specs,
            output_root=runtime_output_dir,
            run_id=args.run_id,
            topology_events=result.events,
        )
    runtime_branch_terminal_path: Path | None = None
    runtime_branch_terminal_audit_path: Path | None = None
    runtime_branch_terminal_audit: dict[str, Any] | None = None
    if args.checkpoint_analytics_mode == NATIVE_TERMINAL_ANALYTICS_MODE:
        runtime_branch_terminal_path, runtime_branch_terminal_audit = write_runtime_branch_terminals(
            records=result.branch_terminal_records,
            ingress_rows=result.terminal_ingress_rows,
            required_branches=plan["required_branches"],
            output_root=runtime_output_dir,
        )
        runtime_branch_terminal_audit_path = runtime_output_dir / "branch_terminal_audit.runtime.json"
        runtime_branch_terminal_audit_path.write_text(
            json.dumps(runtime_branch_terminal_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    publication_acceptance: dict[str, Any] | None = None
    resource_runtime_acceptance: dict[str, Any] | None = None
    if publication_mode:
        _require(runtime_reset_audit is not None, "publication runtime reset audit is absent")
        _require(runtime_stage_contract_path is not None, "publication runtime stage contract is absent")
        _require(str(primary.get("system")) == args.system, "publication runtime system differs from primary cell")
        _require(
            str(dataset_identity.get("codec_variant")) == str(args.codec),
            "publication runtime dataset/codec binding drifted",
        )
        scenario = dict((config.get("scenarios") or {}).get(args.scenario) or {})
        scenario["name"] = args.scenario
        dataset = dict(datasets[str(plan["dataset"])])
        publication_acceptance = publish_checkpoint_runtime(
            output_dir=args.output_dir,
            plan=plan,
            scenario=scenario,
            dataset=dataset,
            result=result,
            reset_rows=runtime_reset_rows,
            reset_audit=runtime_reset_audit,
            cohort_audit=cohort_audit,
            stage_contract_runtime_path=runtime_stage_contract_path,
            worker_specs=specs,
            source_specs=source_specs,
            run_id=args.run_id,
            policy=str(args.policy),
            deadline_ms=float(args.deadline_ms),
            defer_full_resource_acceptance=full_resource_requested,
        )
        if full_resource_requested:
            _require(
                runtime_resource_interval_path is not None,
                "full-resource publication lacks merged native intervals",
            )
            resource_runtime_acceptance = promote_runtime_interval_and_fanout_evidence(
                runtime_resource_intervals=runtime_resource_interval_path,
                runtime_fanout_work_counters=runtime_fanout_work_path,
                output_root=args.output_dir,
                expected_run_id=args.run_id,
                ingress_ledger=pd.read_csv(args.output_dir / "ingress_ledger.csv"),
                topology_events=pd.read_csv(args.output_dir / "topology_events.csv"),
                frame_events=pd.read_csv(args.output_dir / "frame_events.csv"),
                topology_kind=str(plan["topology_kind"]),
            )

    status = {
        **preview,
        "gstreamer_registry_seed": registry_seed,
        "native_policy_promotion": native_policy_promotion,
        "runtime_topology_path": str(topology_path),
        "runtime_stage_contract_path": (
            str(runtime_stage_contract_path) if runtime_stage_contract_path is not None else None
        ),
        "runtime_resource_interval_path": (
            str(runtime_resource_interval_path)
            if runtime_resource_interval_path is not None
            else None
        ),
        "runtime_fanout_work_path": (
            str(runtime_fanout_work_path)
            if runtime_fanout_work_path is not None
            else None
        ),
        "runtime_cohort_audit_path": str(cohort_audit_path),
        "runtime_cohort_audit": cohort_audit,
        "runtime_direct_admission_audit_path": (
            str(admission_audit_path) if admission_audit_path is not None else None
        ),
        "runtime_direct_admission_audit": result.admission_audit,
        "runtime_ingress_ledger_path": (
            str(terminal_ingress_path) if terminal_ingress_path is not None else None
        ),
        "runtime_terminal_admission_audit_path": (
            str(terminal_admission_audit_path) if terminal_admission_audit_path is not None else None
        ),
        "runtime_terminal_admission_audit": result.terminal_admission_audit,
        "runtime_branch_terminal_path": (
            str(runtime_branch_terminal_path) if runtime_branch_terminal_path is not None else None
        ),
        "runtime_branch_terminal_audit_path": (
            str(runtime_branch_terminal_audit_path)
            if runtime_branch_terminal_audit_path is not None
            else None
        ),
        "runtime_branch_terminal_audit": runtime_branch_terminal_audit,
        "runtime_reset_evidence_path": (
            str(runtime_reset_evidence_path) if runtime_reset_evidence_path is not None else None
        ),
        "runtime_reset_evidence_audit_path": (
            str(runtime_reset_audit_path) if runtime_reset_audit_path is not None else None
        ),
        "runtime_reset_evidence_audit": runtime_reset_audit,
        "event_count": len(result.events),
        "unresolved_frames": list(result.unresolved_frames),
        "lifecycle_statuses": {
            worker_id: list(states) for worker_id, states in result.lifecycle_statuses.items()
        },
        "common_start_clock": result.common_start_clock,
        "common_start_monotonic_ns": result.common_start_monotonic_ns,
        "measurement_start_schedule_offset_ns": result.measurement_start_schedule_offset_ns,
        "measurement_end_schedule_offset_ns": result.measurement_end_schedule_offset_ns,
        "window_start_timestamp_ms": result.window_start_timestamp_ms,
        "window_end_timestamp_ms": result.window_end_timestamp_ms,
        "drain_end_timestamp_ms": result.drain_end_timestamp_ms,
        "publication_acceptance": publication_acceptance,
        "resource_runtime_acceptance": resource_runtime_acceptance,
        "accepted_benchmark_sidecars_written": publication_acceptance is not None,
        "publication_blockers": [
            "accepted frames.csv is not emitted by the join coordinator",
            "accepted ingress_ledger.csv is not emitted; ingress_ledger.runtime.csv is engineering-only",
            "accepted stage_contracts.csv is not emitted; only validated engineering runtime fragments exist",
            "runtime terminal closure is not an accepted native ingress sidecar",
            "paired baseline/shared schedule fingerprints have not been observed on the target stand",
            "bounded asynchronous compressed-AU fanout has not been exercised on the target stand",
            "protocol-v3 runtime outcomes are not accepted branch_terminals.csv linkage",
            "native NVDEC submit-to-output and fanout intervals remain runtime-only until full-resource promotion",
            "accepted reset_evidence.csv is not emitted; reset_evidence.runtime.csv is engineering-only",
            "target-hardware execution has not been accepted",
        ] if publication_acceptance is None else [],
    }
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if not result.unresolved_frames else 2


if __name__ == "__main__":
    raise SystemExit(main())
