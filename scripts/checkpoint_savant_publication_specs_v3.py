#!/usr/bin/env python3
"""Exact internal process specs for one Savant publication arm container."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from checkpoint_runtime import SourceLaunchSpec, WorkerLaunchSpec
from checkpoint_savant_launcher import build_savant_module_descriptor
from checkpoint_savant_runtime import ANALYTICS_BRANCHES, validate_savant_runtime_plan


SAVANT_SDK_RUNTIME = (
    "/opt/vast/checkpoint/checkpoint_savant_sdk_runtime_v3.py"
)
SOURCE_EXECUTABLE = "/usr/local/bin/vast_checkpoint_source"
ADAPTER_CONFIG_ENV = "VAST_SAVANT_ADAPTER_CONFIG"
SOURCE_BINDING_ENV = "VAST_SAVANT_SOURCE_BINDING_JSON"
DESCRIPTOR_ENV = "VAST_SAVANT_MODULE_DESCRIPTOR_JSON"


class SavantPublicationSpecsV3Error(RuntimeError):
    """The physical single-arm Savant process matrix drifted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantPublicationSpecsV3Error(message)


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SavantPublicationSpecsV3Error(
            "Savant spec is not canonical JSON"
        ) from exc


def _absolute_posix(value: Path | str, label: str) -> str:
    text = value.as_posix() if isinstance(value, Path) else str(value)
    parsed = PurePosixPath(text)
    _require(
        parsed.is_absolute()
        and parsed.as_posix() == text
        and "\\" not in text
        and ".." not in parsed.parts
        and not text.startswith("//")
        and all(ord(character) >= 0x20 for character in text),
        f"{label} must be a canonical absolute POSIX path",
    )
    return text


def _registry_path(run_id: str, process_id: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}\0{process_id}".encode("utf-8")
    ).hexdigest()
    return f"/tmp/vast-savant-gst-registry-{digest}.bin"


def _status_path(run_id: str, worker_id: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}\0{worker_id}\0status".encode("utf-8")
    ).hexdigest()
    return f"/tmp/vast-savant-status-{digest}.txt"


def _sources_by_stream(plan: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    raw = plan.get("sources")
    _require(isinstance(raw, list) and len(raw) == 6,
             "Savant plan must contain six sources")
    result: dict[int, dict[str, Any]] = {}
    for value in raw:
        _require(isinstance(value, Mapping), "Savant source row is invalid")
        source = dict(value)
        stream_id = int(source.get("stream_id", -1))
        _require(
            0 <= stream_id < 6 and stream_id not in result,
            "Savant source stream identity drifted",
        )
        source_id = (
            "kpp_underbody_avi-stream-5"
            if stream_id == 5
            else f"kpp_plate_avi-stream-{stream_id}"
        )
        frame_count = int(source.get("frame_count", 0))
        duration_numerator = frame_count * 1_000_000_000
        _require(
            frame_count > 0 and duration_numerator % 600 == 0,
            "Savant source duration is not exact at 600 fps",
        )
        result[stream_id] = {
            "stream_id": stream_id,
            "source_id": source_id,
            "source_sha256": str(source["source_sha256"]),
            "source_codec": str(source["source_codec"]),
            "source_duration_ns": duration_numerator // 600,
            "width": int(source["width"]),
            "height": int(source["height"]),
        }
    _require(set(result) == set(range(6)),
             "Savant source rows do not cover six streams")
    return result


def build_savant_publication_worker_specs(
    plan: Mapping[str, Any],
    *,
    run_id: str,
    arm_id: str,
    adapter_config_path: str,
    output_root: Path,
    inherited_fds: tuple[int, ...] = (),
) -> tuple[WorkerLaunchSpec, ...]:
    """Build 24 baseline or six shared workers inside one arm container."""

    validate_savant_runtime_plan(plan)
    _require(plan.get("system") == "savant", "Savant plan system drifted")
    _require(bool(str(run_id).strip()) and bool(str(arm_id).strip()),
             "Savant run/arm identity is empty")
    adapter = _absolute_posix(adapter_config_path, "Savant adapter config")
    output = _absolute_posix(output_root, "Savant runtime output")
    _require(
        type(inherited_fds) is tuple
        and len(inherited_fds) == len(set(inherited_fds))
        and all(type(fd) is int and fd > 2 for fd in inherited_fds),
        "Savant inherited FD set is invalid",
    )
    topology = str(plan["topology_kind"])
    codec = str(plan["codec"])
    sources = _sources_by_stream(plan)
    processes = plan.get("processes")
    _require(isinstance(processes, list), "Savant process matrix is missing")
    specs: list[WorkerLaunchSpec] = []
    for process in processes:
        _require(isinstance(process, Mapping), "Savant process row is invalid")
        descriptor = build_savant_module_descriptor(plan, process)
        worker_id = str(descriptor["module_id"])
        stream_id = int(descriptor["stream_id"])
        branches = tuple(str(value) for value in descriptor["branches"])
        if topology == "independent_processes":
            _require(
                len(branches) == 1 and branches[0] in ANALYTICS_BRANCHES,
                "Savant baseline worker is not branch-isolated",
            )
            branch_id: str | None = branches[0]
        else:
            _require(
                topology == "shared_video_dag"
                and branches == ANALYTICS_BRANCHES,
                "Savant shared worker route order drifted",
            )
            branch_id = None
        worker_output = (
            PurePosixPath(output) / "workers" / worker_id
        ).as_posix()
        command = (
            "python3",
            "-B",
            SAVANT_SDK_RUNTIME,
            "run",
            "--codec",
            codec,
            "--topology-kind",
            topology,
            "--stream-id",
            str(stream_id),
            "--branches",
            ",".join(branches),
            "--arm-id",
            str(arm_id),
            "--output-dir",
            worker_output,
        )
        specs.append(
            WorkerLaunchSpec(
                worker_id=worker_id,
                stream_id=stream_id,
                branch_id=branch_id,
                command=command,
                environment={
                    ADAPTER_CONFIG_ENV: adapter,
                    DESCRIPTOR_ENV: _canonical(descriptor),
                    SOURCE_BINDING_ENV: _canonical(sources[stream_id]),
                    "VAST_SAVANT_ARM_ID": str(arm_id),
                    "VAST_SAVANT_BRANCHES": ",".join(branches),
                    "VAST_SAVANT_CODEC": codec,
                    "VAST_SAVANT_DATASET_ID": str(plan["dataset"]),
                    "VAST_SAVANT_DEADLINE_MS": str(
                        float(plan["deadline_ms"])
                    ),
                    "VAST_SAVANT_POLICY": str(plan["policy"]),
                    "SAVANT_STATUS_FILEPATH": _status_path(
                        str(run_id), worker_id
                    ),
                    "GST_REGISTRY": _registry_path(str(run_id), worker_id),
                    "GST_REGISTRY_UPDATE": "no",
                    "GST_REGISTRY_FORK": "no",
                    "VAST_SAVANT_CLAIM_STATUS":
                        "native_sdk_runtime_requires_external_acceptance",
                },
                native_event_source=True,
                inherited_fds=inherited_fds,
            )
        )
    expected = 24 if topology == "independent_processes" else 6
    _require(len(specs) == expected,
             f"Savant {topology} requires exactly {expected} workers")
    _require(len({spec.worker_id for spec in specs}) == expected,
             "Savant worker IDs are duplicated")
    _require({spec.stream_id for spec in specs} == set(range(6)),
             "Savant workers do not cover six streams")
    return tuple(specs)


def build_savant_publication_source_specs(
    plan: Mapping[str, Any],
    *,
    source_binary: Path,
    project_root: Path,
    run_id: str,
    pinned_source_paths_by_sha256: Mapping[str, str],
    inherited_fds: tuple[int, ...] = (),
) -> tuple[SourceLaunchSpec, ...]:
    """Bind six frozen KPP inputs to six native common-source processes."""

    validate_savant_runtime_plan(plan)
    executable = _absolute_posix(source_binary, "Savant source executable")
    root = Path(project_root)
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
             "Savant input root is invalid")
    sources = _sources_by_stream(plan)
    coordinators = plan.get("source_coordinators")
    _require(isinstance(coordinators, list) and len(coordinators) == 6,
             "Savant source coordinator matrix drifted")
    specs: list[SourceLaunchSpec] = []
    for stream_id, coordinator in enumerate(coordinators):
        _require(
            isinstance(coordinator, Mapping)
            and int(coordinator.get("stream_id", -1)) == stream_id,
            "Savant source coordinator order drifted",
        )
        source = sources[stream_id]
        source_sha256 = str(source["source_sha256"])
        raw_path = pinned_source_paths_by_sha256.get(source_sha256)
        _require(raw_path is not None,
                 "Savant source lacks an exact SHA-bound input")
        source_path = Path(raw_path)
        _require(
            source_path.is_absolute()
            and source_path.is_file()
            and not source_path.is_symlink(),
            "Savant SHA-bound source path is unsafe",
        )
        digest = hashlib.sha256()
        with source_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        _require(digest.hexdigest() == source_sha256,
                 "Savant source digest drifted")
        raw_plan_source = dict(plan["sources"][stream_id])
        frame_count = int(raw_plan_source["frame_count"])
        duration_ns = frame_count * 1_000_000_000 // 600
        _require(duration_ns > 0 and duration_ns * 600
                 == frame_count * 1_000_000_000,
                 "Savant source duration is not exact at 600 fps")
        process_id = str(coordinator["process_id"])
        command = (
            executable,
            "--source-path", str(source_path),
            "--dataset-id", str(plan["dataset"]),
            "--source-sha256", source_sha256,
            "--checkpoint-container", "mp4",
            "--checkpoint-codec", str(plan["codec"]),
            "--source-duration-ns", str(duration_ns),
            "--playback-timestamp-scale", "600",
            "--source-replay", "continuous",
            "--logical-stream-id", str(stream_id),
        )
        specs.append(
            SourceLaunchSpec(
                source_process_id=process_id,
                stream_id=stream_id,
                dataset_id=str(plan["dataset"]),
                source_sha256=source_sha256,
                command=command,
                environment={
                    "GST_REGISTRY": _registry_path(str(run_id), process_id),
                    "GST_REGISTRY_UPDATE": "no",
                    "GST_REGISTRY_FORK": "no",
                    "VAST_CHECKPOINT_SOURCE_CONTAINER": "mp4",
                    "VAST_CHECKPOINT_SOURCE_CODEC": str(plan["codec"]),
                    "VAST_CHECKPOINT_SOURCE_DURATION_NS": str(duration_ns),
                    "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE": "600",
                    "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                    "VAST_CHECKPOINT_ADMISSION_MODE":
                        "native_common_source_coordinator",
                },
                native_source=True,
                inherited_fds=inherited_fds,
            )
        )
    _require(len({spec.source_process_id for spec in specs}) == 6,
             "Savant source process IDs are duplicated")
    return tuple(specs)


__all__ = [
    "ADAPTER_CONFIG_ENV",
    "DESCRIPTOR_ENV",
    "SAVANT_SDK_RUNTIME",
    "SOURCE_BINDING_ENV",
    "SOURCE_EXECUTABLE",
    "SavantPublicationSpecsV3Error",
    "build_savant_publication_source_specs",
    "build_savant_publication_worker_specs",
]
