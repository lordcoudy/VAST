#!/usr/bin/env python3
"""Savant publication ABI-v3 coordinator executed inside the pinned image.

The host boundary materializes only SHA-bound files.  This coordinator proves
those bytes again, launches the exact six-source/24-or-six-worker SDK graph,
binds every analytics decision to the mounted CPU/TensorRT endpoints, and only
then invokes the common accepted-sidecar publication finalizer.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SYSTEM = "savant"
TERMINAL_STATUS_KIND = "vast_savant_publication_terminal_status_v3"
INPUT_ROOT = Path("/opt/vast/input")
OUTPUT_ROOT = Path("/opt/vast/output")
WORKER_EXECUTABLE = Path("/usr/local/bin/vast_savant_checkpoint_runtime")
SOURCE_EXECUTABLE = Path("/usr/local/bin/vast_checkpoint_source")
SCENARIO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
CHECKPOINT_KEYS = {
    "checkpoint_independent_processes_baseline": "baseline",
    "checkpoint_video_dag_shared": "shared",
}
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_GSTREAMER_REGISTRY_BYTES = 64 * 1024 * 1024
MAX_REGISTRY_SCANNER_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_NATIVE_STDIO_BYTES = 1024 * 1024
NVSTREAMMUX_EOS_LINE = "nvstreammux: Successfully handled EOS for source_id=0"


class SavantContainerRuntimeV3Error(RuntimeError):
    """A materialized input, SDK graph, or publication gate failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantContainerRuntimeV3Error(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SavantContainerRuntimeV3Error(
            f"runtime input cannot be hashed: {path}"
        ) from exc
    return digest.hexdigest()


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    # Windows exposes a slightly different ctime precision through stat() and
    # fstat() for the same held file handle.  Keep ctime in the path-before /
    # path-after mutation gate below, while comparing only cross-interface
    # identity fields against the opened descriptor.
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
    )


def _bounded_plain_payload(path: Path, *, limit: int, label: str) -> bytes:
    descriptor = -1
    try:
        before = path.lstat()
        _require(
            stat.S_ISREG(before.st_mode)
            and not path.is_symlink()
            and int(before.st_nlink) == 1
            and 0 <= int(before.st_size) <= limit,
            f"{label} custody is invalid",
        )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
        )
        opened = os.fstat(descriptor)
        payload = bytearray()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            _require(len(payload) <= limit, f"{label} exceeds its bounded capture")
        after = path.lstat()
    except OSError as exc:
        raise SavantContainerRuntimeV3Error(
            f"{label} custody is invalid"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _require(
        _stat_identity(before) == _stat_identity(opened) == _stat_identity(after)
        and int(before.st_ctime_ns) == int(after.st_ctime_ns)
        and len(payload) == int(after.st_size),
        f"{label} changed while being validated",
    )
    return bytes(payload)


def _registry_factories(codec: str) -> tuple[str, ...]:
    _require(codec in {"h264", "h265"}, "Savant registry codec is invalid")
    parser = "h264parse" if codec == "h264" else "h265parse"
    return (
        "appsrc",
        parser,
        "nvv4l2decoder",
        "nvstreammux",
        "nvvideoconvert",
        "capsfilter",
        "tee",
        "queue",
        "appsink",
    )


def seed_savant_gstreamer_registries(
    worker_specs: Sequence[Any],
    source_specs: Sequence[Any],
    *,
    codec: str,
    registry_root: Path = Path("/tmp"),
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Create one GPU-aware seed and exact private copies before READY."""

    root = Path(registry_root)
    try:
        root_info = root.lstat()
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SavantContainerRuntimeV3Error(
            "Savant registry root is invalid"
        ) from exc
    _require(
        resolved_root == root
        and stat.S_ISDIR(root_info.st_mode)
        and not root.is_symlink(),
        "Savant registry root is invalid",
    )
    specs = tuple(worker_specs) + tuple(source_specs)
    _require(bool(specs), "Savant registry process set is empty")
    destinations: list[Path] = []
    for spec in specs:
        environment = getattr(spec, "environment", None)
        _require(
            isinstance(environment, Mapping)
            and environment.get("GST_REGISTRY_UPDATE") == "no"
            and environment.get("GST_REGISTRY_FORK") == "no",
            "Savant registry environment is not fail-closed",
        )
        destination = Path(str(environment.get("GST_REGISTRY", "")))
        _require(
            destination.is_absolute()
            and destination.parent == root
            and not destination.exists(),
            "Savant registry destination is invalid",
        )
        destinations.append(destination)
    _require(
        len(destinations) == len(set(destinations)),
        "Savant registry destinations are not process-private",
    )

    descriptor, seed_name = tempfile.mkstemp(
        prefix="vast-savant-gpu-seed-",
        suffix=".bin",
        dir=str(root),
    )
    os.close(descriptor)
    seed = Path(seed_name)
    seed.unlink()
    scanner_stderr_bytes = 0
    scanner_stdout_bytes = 0
    try:
        environment = os.environ.copy()
        environment["GST_REGISTRY"] = str(seed)
        environment.pop("GST_REGISTRY_UPDATE", None)
        environment["GST_REGISTRY_FORK"] = "no"
        factories = _registry_factories(codec)
        for factory in factories:
            completed = runner(
                ("gst-inspect-1.0", factory),
                check=False,
                capture_output=True,
                timeout=60.0,
                env=environment,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            if isinstance(stdout, str):
                stdout = stdout.encode("utf-8")
            if isinstance(stderr, str):
                stderr = stderr.encode("utf-8")
            _require(
                isinstance(stdout, bytes)
                and isinstance(stderr, bytes)
                and completed.returncode == 0,
                f"Savant required GStreamer factory is unavailable: {factory}",
            )
            scanner_stdout_bytes += len(stdout)
            scanner_stderr_bytes += len(stderr)
            _require(
                scanner_stdout_bytes + scanner_stderr_bytes
                <= MAX_REGISTRY_SCANNER_CAPTURE_BYTES,
                "Savant registry scanner capture exceeded its bound",
            )
        seed_payload = _bounded_plain_payload(
            seed,
            limit=MAX_GSTREAMER_REGISTRY_BYTES,
            label="Savant GPU registry seed",
        )
        _require(seed_payload, "Savant GPU registry seed is empty")
        seed_sha256 = hashlib.sha256(seed_payload).hexdigest()
        for destination in destinations:
            with destination.open("xb") as output:
                output.write(seed_payload)
                output.flush()
                os.fsync(output.fileno())
            destination.chmod(0o600)
            _require(
                _sha256_file(destination) == seed_sha256,
                "Savant registry copy digest drifted",
            )
        return {
            "schema_version": 3,
            "artifact_kind": "vast_savant_gstreamer_registry_seed_audit_v3",
            "required_factories": list(factories),
            "seed_sha256": seed_sha256,
            "copy_sha256": seed_sha256,
            "copy_count": len(destinations),
            "scanner_stdout_bytes": scanner_stdout_bytes,
            "scanner_stderr_bytes": scanner_stderr_bytes,
            "registry_update_disabled": True,
            "registry_fork_disabled": True,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        raise SavantContainerRuntimeV3Error(
            "Savant GPU registry materialization failed"
        ) from exc
    finally:
        seed.unlink(missing_ok=True)


@contextmanager
def _capture_savant_native_stdio(output_dir: Path):
    stdout_path = output_dir / "native_children.stdout.log"
    stderr_path = output_dir / "native_children.stderr.log"
    stdout_fd = stderr_fd = saved_stdout = saved_stderr = -1
    try:
        stdout_fd = os.open(
            stdout_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        stderr_fd = os.open(
            stderr_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        sys.stdout.flush()
        sys.stderr.flush()
        saved_stdout = os.dup(1)
        saved_stderr = os.dup(2)
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        yield stdout_path, stderr_path
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        if saved_stdout >= 0:
            os.dup2(saved_stdout, 1)
        if saved_stderr >= 0:
            os.dup2(saved_stderr, 2)
        for descriptor in (stdout_fd, stderr_fd):
            if descriptor >= 0:
                try:
                    os.fsync(descriptor)
                except OSError:
                    pass
        for descriptor in (stdout_fd, stderr_fd, saved_stdout, saved_stderr):
            if descriptor >= 0:
                os.close(descriptor)


def validate_savant_native_stdio(
    stdout_path: Path,
    stderr_path: Path,
    *,
    expected_worker_count: int,
) -> dict[str, Any]:
    """Allow only exact native nvstreammux EOS notices; stderr stays empty."""

    _require(
        type(expected_worker_count) is int and expected_worker_count > 0,
        "Savant native stdio worker count is invalid",
    )
    stdout = _bounded_plain_payload(
        stdout_path,
        limit=MAX_NATIVE_STDIO_BYTES,
        label="Savant native stdout",
    )
    stderr = _bounded_plain_payload(
        stderr_path,
        limit=MAX_NATIVE_STDIO_BYTES,
        label="Savant native stderr",
    )
    try:
        lines = [line for line in stdout.decode("ascii").splitlines() if line]
    except UnicodeDecodeError as exc:
        raise SavantContainerRuntimeV3Error(
            "Savant native stdout contract is invalid"
        ) from exc
    _require(
        lines == [NVSTREAMMUX_EOS_LINE] * expected_worker_count,
        "Savant native stdout contract is invalid",
    )
    _require(not stderr, "Savant native stderr contract is not empty")
    return {
        "schema_version": 3,
        "artifact_kind": "vast_savant_native_stdio_audit_v3",
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "nvstreammux_eos_line_count": len(lines),
        "expected_worker_count": expected_worker_count,
    }


def _plain_regular_file(path: Path, *, root: Path = INPUT_ROOT) -> Path:
    _require(path.is_absolute(), f"runtime input is not absolute: {path}")
    try:
        lexical = Path(os.path.abspath(os.fspath(path)))
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
        before = path.lstat()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SavantContainerRuntimeV3Error(
            f"runtime input escapes the materialized root: {path}"
        ) from exc
    _require(
        lexical == path == resolved
        and stat.S_ISREG(before.st_mode)
        and not path.is_symlink()
        and int(before.st_nlink) == 1,
        f"runtime input is not a canonical single-link regular file: {path}",
    )
    return resolved


def parse_sha_path_bindings(
    values: Sequence[str],
    *,
    label: str,
    root: Path = INPUT_ROOT,
) -> dict[str, Path]:
    """Re-hash exact host-declared materialized bindings inside the image."""

    _require(bool(values), f"{label} binding set is empty")
    by_sha: dict[str, Path] = {}
    paths: set[Path] = set()
    for raw in values:
        digest, separator, path_text = str(raw).partition("=")
        _require(
            separator == "=" and SHA_RE.fullmatch(digest) is not None,
            f"{label} binding is not sha256=absolute-path",
        )
        path = _plain_regular_file(Path(path_text), root=root)
        _require(digest not in by_sha and path not in paths, f"{label} binding identity is duplicated")
        _require(_sha256_file(path) == digest, f"{label} binding SHA-256 drifted: {path}")
        by_sha[digest] = path
        paths.add(path)
    return by_sha


def _load_structured(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            value = json.loads(raw)
        else:
            import yaml

            value = yaml.safe_load(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ImportError) as exc:
        raise SavantContainerRuntimeV3Error(f"{label} is unreadable") from exc
    _require(isinstance(value, Mapping), f"{label} must contain one mapping")
    return dict(value)


def _validate_socket_path(value: Any, label: str) -> str:
    raw = str(value or "")
    _require(
        raw.startswith("/run/vast/")
        and "\\" not in raw
        and "\x00" not in raw
        and len(os.fsencode(raw)) < 108
        and os.path.normpath(raw) == raw,
        f"{label} socket path is invalid",
    )
    try:
        info = os.lstat(raw)
    except OSError as exc:
        raise SavantContainerRuntimeV3Error(f"{label} socket is missing") from exc
    _require(stat.S_ISSOCK(info.st_mode), f"{label} path is not a socket")
    return raw


def _verify_binding_artifacts(
    binding: Mapping[str, Any],
    *,
    resource: str,
    model_paths: set[Path],
) -> set[Path]:
    fields = ["source_path", "model_path", "weights_path"] if resource == "cpu" else ["source_path", "engine_path"]
    referenced: set[Path] = set()
    for field in fields:
        path = _plain_regular_file(Path(str(binding.get(field, ""))))
        _require(path in model_paths, f"{resource} binding references an undeclared model artifact")
        referenced.add(path)
    digest_fields = {
        "source_path": "source_model_sha256",
        "model_path": "model_artifact_sha256",
        "weights_path": "runtime_weights_sha256",
        "engine_path": "model_artifact_sha256",
    }
    for field in fields:
        expected = str(binding.get(digest_fields[field], ""))
        _require(SHA_RE.fullmatch(expected) is not None, f"{resource} binding digest is invalid")
        _require(_sha256_file(Path(str(binding[field]))) == expected, f"{resource} binding artifact digest drifted")
    return referenced


def validate_adapter_materialization(
    *,
    adapter_config_path: Path,
    analytics_model_manifest_path: Path,
    model_bindings: Mapping[str, Path],
    support_bindings: Mapping[str, Path],
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind adapter references and endpoint handshakes to declared input bytes."""

    from analytics_execution_endpoint import expected_capability_from_binding_and_probe
    from checkpoint_deepstream_protocol_adapter import validate_adapter_config
    from checkpoint_deepstream_protocol_bridge import analytics_backend_identity

    config = validate_adapter_config(_load_structured(adapter_config_path, "Savant adapter config"))
    _require(set(config["branches"]) == set(BRANCHES), "Savant adapter config lacks the frozen four branches")
    _require(
        Path(config["preprocessing_manifest_path"]) == analytics_model_manifest_path,
        "Savant preprocessing manifest path differs from the pinned manifest",
    )
    support_paths = set(support_bindings.values())
    model_paths = set(model_bindings.values())
    referenced_support: set[Path] = set()
    referenced_models: set[Path] = set()
    try:
        manifest_branches = capability_manifest["systems"][SYSTEM]["branches"]
    except (KeyError, TypeError) as exc:
        raise SavantContainerRuntimeV3Error(
            "Savant capability bindings are missing"
        ) from exc
    for branch in BRANCHES:
        for resource in RESOURCES:
            record = config["branches"][branch][resource]
            _validate_socket_path(record["socket_path"], f"{branch}/{resource}")
            binding_path = _plain_regular_file(Path(record["binding_path"]))
            probe_path = _plain_regular_file(Path(record["runtime_probe_path"]))
            _require(
                binding_path in support_paths and probe_path in support_paths,
                f"{branch}/{resource} references undeclared endpoint evidence",
            )
            referenced_support.update((binding_path, probe_path))
            binding = _load_structured(binding_path, f"{branch}/{resource} binding")
            probe = _load_structured(probe_path, f"{branch}/{resource} runtime probe")
            capability = expected_capability_from_binding_and_probe(
                binding=binding,
                runtime_probe=probe,
                resource=resource,
            )
            _require(capability["branch"] == branch, f"{branch}/{resource} capability branch drifted")
            policy_binding = manifest_branches[branch][resource]
            _require(
                record["implementation_id"] == policy_binding["implementation_id"],
                f"{branch}/{resource} adapter implementation differs from policy capability",
            )
            _require(
                str(policy_binding.get("terminal_detector")) == str(capability["model_id"])
                and str(policy_binding.get("terminal_backend", ""))
                == analytics_backend_identity(capability),
                f"{branch}/{resource} terminal identity differs from endpoint capability",
            )
            referenced_models.update(
                _verify_binding_artifacts(
                    binding,
                    resource=resource,
                    model_paths=model_paths,
                )
            )
    _require(referenced_support == support_paths, "Savant support binding set has unreferenced material")
    _require(referenced_models == model_paths, "Savant model binding set has unreferenced material")
    return config


def _frame_transfer_bytes(dataset: Mapping[str, Any], stream_id: int) -> int:
    streams = dataset.get("streams")
    _require(isinstance(streams, list), "Savant dataset streams are missing")
    selected = next(
        (
            value
            for value in streams
            if isinstance(value, Mapping) and int(value.get("stream_id", -1)) == stream_id
        ),
        None,
    )
    _require(isinstance(selected, Mapping), f"Savant dataset lacks stream {stream_id}")
    width = int(selected.get("width", 0) or 0)
    height = int(selected.get("height", 0) or 0)
    _require(width > 0 and height > 0, f"Savant stream {stream_id} dimensions are invalid")
    return width * height * 3


def write_native_stage_resource_events(
    output_dir: Path,
    *,
    frame_event_rows: Sequence[Mapping[str, Any]],
    dataset: Mapping[str, Any],
) -> Path:
    """Emit base resource evidence only from native per-stage interval timestamps."""

    from benchmark_contract import (
        RESOURCE_EVENT_COLUMNS,
        TELEMETRY_SCHEMA_VERSION,
        stage_base_name,
        validate_resource_events,
    )

    _require(bool(frame_event_rows), "Savant native frame-event set is empty")
    rows: list[dict[str, Any]] = []
    for event in frame_event_rows:
        start = float(event["stage_start_timestamp_ms"])
        end = float(event["stage_end_timestamp_ms"])
        _require(math.isfinite(start) and math.isfinite(end) and start <= end, "Savant native stage interval is invalid")
        duration = end - start
        resource = str(event["resource"]).lower()
        _require(resource in {"cpu", "gpu", "nvdec"}, "Savant native stage resource is invalid")
        stream_id = int(event["stream_id"])
        bytes_per_frame = _frame_transfer_bytes(dataset, stream_id)
        is_gpu = resource == "gpu"
        rows.append({
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "run_id": str(event["run_id"]),
            "trace_id": str(event["trace_id"]),
            "stream_id": stream_id,
            "frame_id": int(event["frame_id"]),
            "stage": str(event["stage"]),
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
        })
    path = output_dir / "resource_events.csv"
    try:
        with path.open("x", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=RESOURCE_EVENT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise SavantContainerRuntimeV3Error(
            "Savant resource_events.csv already exists"
        ) from exc
    validate_resource_events(path, require_labeled_provenance=True)
    return path


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as exc:
        raise SavantContainerRuntimeV3Error(
            f"Savant runtime evidence already exists: {path.name}"
        ) from exc


def _validated_cli_file(path: Path, label: str) -> Path:
    return _plain_regular_file(Path(path), root=INPUT_ROOT)


def execute_publication_arm(args: argparse.Namespace) -> dict[str, Any]:
    """Execute one genuine Savant SDK arm and return the terminal ABI object."""

    import yaml
    import pandas as pd

    from benchmark_contract import INGRESS_LEDGER_COLUMNS, RESET_EVIDENCE_COLUMNS
    from checkpoint_savant_publication_specs_v3 import (
        build_savant_publication_source_specs,
        build_savant_publication_worker_specs,
    )
    from checkpoint_savant_runtime import build_savant_runtime_plan
    from checkpoint_gstreamer_runtime import (
        build_publication_pair_plans,
        build_runtime_cohort_audit,
        merge_runtime_fanout_work_counters,
        merge_runtime_resource_intervals,
        merge_runtime_stage_contracts,
        promote_runtime_interval_and_fanout_evidence,
        write_runtime_branch_terminals,
    )
    from checkpoint_native_policy_runtime import (
        NativePolicyRuntimeCoordinator,
        canonical_frames_from_events,
    )
    from checkpoint_publication_runtime import (
        _accepted_frame_event_rows,
        _accepted_ingress_rows,
        publish_checkpoint_runtime,
    )
    from checkpoint_runtime import build_runtime_reset_evidence, run_worker_processes
    from topology_contract import TOPOLOGY_EVENT_COLUMNS

    _require(os.name == "posix", "Savant publication coordinator requires POSIX")
    _require(args.output_dir == OUTPUT_ROOT, "Savant output directory differs from ABI-v3")
    _require(args.topology_kind == SCENARIO_TOPOLOGY[args.scenario], "Savant scenario/topology binding drifted")
    _require(args.policy in POLICIES, "Savant policy is outside the frozen matrix")
    _require(math.isfinite(args.deadline_ms) and args.deadline_ms > 0, "Savant deadline is invalid")
    _require(args.duration == 180, "Savant publication measurement duration must equal 180 seconds")
    _require(args.ready_timeout > 0 and args.drain_timeout > 0, "Savant lifecycle timeout is invalid")
    _require(0 <= args.start_lead_ms <= 60_000, "Savant start lead is invalid")
    _require(args.output_dir.is_dir() and not args.output_dir.is_symlink(), "Savant output mount is invalid")
    _require(not any(args.output_dir.iterdir()), "Savant output mount must be empty for each arm")

    config_path = _validated_cli_file(args.config, "experiments config")
    datasets_path = _validated_cli_file(args.datasets, "datasets config")
    adapter_path = _validated_cli_file(args.adapter_config, "adapter config")
    analytics_manifest_path = _validated_cli_file(
        args.analytics_model_manifest, "analytics model manifest"
    )
    capability_path = _validated_cli_file(
        args.policy_capability_manifest, "policy capability manifest"
    )
    calibration_path = _validated_cli_file(args.policy_calibration, "policy calibration")
    source_bindings = parse_sha_path_bindings(args.source_binding, label="source")
    model_bindings = parse_sha_path_bindings(args.model_binding, label="model")
    support_bindings = parse_sha_path_bindings(args.support_binding, label="support")
    static_path = (
        _validated_cli_file(args.static_hybrid_map, "static hybrid map")
        if args.static_hybrid_map is not None
        else None
    )
    _require((args.policy == "static_hybrid") == (static_path is not None), "Savant static-hybrid map binding drifted")

    config = _load_structured(config_path, "experiments config")
    datasets_document = _load_structured(datasets_path, "datasets config")
    datasets = dict(datasets_document.get("datasets") or {})
    physical_plan = build_savant_runtime_plan(
        config=config,
        datasets=datasets,
        scenario=args.scenario,
        codec=args.codec,
        policy=args.policy,
        deadline_ms=args.deadline_ms,
    )
    publication_plan = build_publication_pair_plans(
        config=config,
        datasets=datasets,
        system=SYSTEM,
        codec=args.codec,
    )[CHECKPOINT_KEYS[args.scenario]]
    _require(
        physical_plan["topology_kind"] == publication_plan["topology_kind"] == args.topology_kind
        and physical_plan["dataset"] == publication_plan["dataset"],
        "Savant physical/publication plan identity drifted",
    )
    _require(
        float(physical_plan["measurement_s"]) == float(publication_plan["cohort_protocol"]["measurement_s"]) == float(args.duration)
        and float(physical_plan["warmup_s"]) == float(publication_plan["cohort_protocol"]["warmup_s"]) == 30.0,
        "Savant frozen cohort window drifted",
    )
    expected_source_hashes = {
        str(source["source_sha256"]) for source in physical_plan["sources"]
    }
    _require(set(source_bindings) == expected_source_hashes, "Savant KPP source binding set drifted")

    capability_manifest = _load_structured(capability_path, "policy capability manifest")
    calibration = _load_structured(calibration_path, "policy calibration")
    static_map = (
        _load_structured(static_path, "static hybrid map") if static_path is not None else None
    )
    validate_adapter_materialization(
        adapter_config_path=adapter_path,
        analytics_model_manifest_path=analytics_manifest_path,
        model_bindings=model_bindings,
        support_bindings=support_bindings,
        capability_manifest=capability_manifest,
    )
    policy_runtime = NativePolicyRuntimeCoordinator(
        run_id=args.run_id,
        arm_id=args.arm_id,
        system=SYSTEM,
        scenario=args.scenario,
        codec=args.codec,
        policy=args.policy,
        deadline_ms=args.deadline_ms,
        branches=BRANCHES,
        capability_manifest=capability_manifest,
        calibration=calibration,
        static_hybrid_map=static_map,
    )

    _require(WORKER_EXECUTABLE.is_file(), "Savant SDK worker executable is missing")
    _require(SOURCE_EXECUTABLE.is_file(), "Savant source coordinator executable is missing")
    runtime_output = args.output_dir / "native_runtime"
    runtime_output.mkdir(mode=0o700)
    worker_specs = build_savant_publication_worker_specs(
        physical_plan,
        run_id=args.run_id,
        arm_id=args.arm_id,
        adapter_config_path=str(adapter_path),
        output_root=runtime_output,
    )
    source_specs = build_savant_publication_source_specs(
        physical_plan,
        source_binary=SOURCE_EXECUTABLE,
        project_root=INPUT_ROOT,
        run_id=args.run_id,
        pinned_source_paths_by_sha256={key: str(value) for key, value in source_bindings.items()},
    )
    expected_workers = 24 if args.topology_kind == "independent_processes" else 6
    _require(len(worker_specs) == expected_workers and len(source_specs) == 6, "Savant physical process cardinality drifted")
    registry_audit = seed_savant_gstreamer_registries(
        worker_specs,
        source_specs,
        codec=args.codec,
    )
    _write_json(
        runtime_output / "gstreamer_registry_seed_audit.runtime.json",
        registry_audit,
    )
    for spec in worker_specs:
        Path(spec.command[spec.command.index("--output-dir") + 1]).mkdir(parents=True)

    telemetry_sink_id = hashlib.sha256(
        f"{args.run_id}\0{runtime_output.resolve()}".encode("utf-8")
    ).hexdigest()
    topology_path = runtime_output / "topology_events.runtime.csv"
    with topology_path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=TOPOLOGY_EVENT_COLUMNS)
        writer.writeheader()

        def write_event(row: dict[str, Any]) -> None:
            writer.writerow({column: row[column] for column in TOPOLOGY_EVENT_COLUMNS})
            output.flush()

        with _capture_savant_native_stdio(runtime_output) as native_stdio_paths:
            result = run_worker_processes(
                run_id=args.run_id,
                topology_contract_version=2,
                topology_kind=args.topology_kind,
                branches=BRANCHES,
                specs=worker_specs,
                source_specs=source_specs,
                timeout_s=30.0 + 180.0 + args.drain_timeout + 60.0,
                ready_timeout_s=args.ready_timeout,
                on_event=write_event,
                synchronized_lifecycle=True,
                warmup_s=30.0,
                measurement_s=180.0,
                drain_timeout_s=args.drain_timeout,
                start_lead_s=float(args.start_lead_ms) / 1000.0,
                require_decoder_placement_verification=True,
                measurement_end_boundary_guard_ns=int(
                    publication_plan["source_playback"]["measurement_end_boundary_guard_ns"]
                ),
                policy_socket_handler=policy_runtime.serve_worker_socket,
            )
    native_stdio_audit = validate_savant_native_stdio(
        native_stdio_paths[0],
        native_stdio_paths[1],
        expected_worker_count=expected_workers,
    )
    _write_json(
        runtime_output / "native_stdio_audit.runtime.json",
        native_stdio_audit,
    )
    for path in native_stdio_paths:
        path.unlink()
    _require(not result.unresolved_frames, "Savant arm has unresolved native frames")
    policy_promotion = policy_runtime.promote(
        args.output_dir,
        canonical_frames=canonical_frames_from_events(result.events),
    )
    result = dataclasses.replace(
        result,
        events=policy_runtime.enrich_runtime_events(result.events),
    )
    cohort_audit = build_runtime_cohort_audit(
        events=result.events,
        topology_kind=args.topology_kind,
        branches=BRANCHES,
        window_start_timestamp_ms=result.window_start_timestamp_ms,
        window_end_timestamp_ms=result.window_end_timestamp_ms,
        drain_end_timestamp_ms=result.drain_end_timestamp_ms,
        admission_records=result.admission_records,
        measurement_start_schedule_offset_ns=result.measurement_start_schedule_offset_ns,
        measurement_end_schedule_offset_ns=result.measurement_end_schedule_offset_ns,
    )
    _write_json(runtime_output / "cohort_audit.runtime.json", cohort_audit)

    ingress_runtime_path = runtime_output / "ingress_ledger.runtime.csv"
    with ingress_runtime_path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=INGRESS_LEDGER_COLUMNS)
        writer.writeheader()
        writer.writerows(result.terminal_ingress_rows)
    reset_rows, reset_audit = build_runtime_reset_evidence(
        run_id=args.run_id,
        topology_kind=args.topology_kind,
        branches=BRANCHES,
        specs=worker_specs,
        source_specs=source_specs,
        result=result,
        telemetry_sink_id=telemetry_sink_id,
        telemetry_sink_preexisting_entry_count=0,
    )
    with (runtime_output / "reset_evidence.runtime.csv").open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=RESET_EVIDENCE_COLUMNS)
        writer.writeheader()
        writer.writerows(reset_rows)
    _write_json(runtime_output / "reset_evidence_audit.runtime.json", reset_audit)
    stage_contract_path = merge_runtime_stage_contracts(
        specs=worker_specs,
        process_ids=result.process_ids,
        output_root=runtime_output,
        run_id=args.run_id,
        topology_events=result.events,
    )
    resource_interval_runtime_path = merge_runtime_resource_intervals(
        specs=worker_specs,
        output_root=runtime_output,
        run_id=args.run_id,
        topology_events=result.events,
    )
    fanout_work_runtime_path = merge_runtime_fanout_work_counters(
        specs=worker_specs,
        output_root=runtime_output,
        run_id=args.run_id,
        topology_events=result.events,
    )
    branch_terminal_path, branch_terminal_audit = write_runtime_branch_terminals(
        records=result.branch_terminal_records,
        ingress_rows=result.terminal_ingress_rows,
        required_branches=BRANCHES,
        output_root=runtime_output,
    )
    _write_json(runtime_output / "branch_terminal_audit.runtime.json", branch_terminal_audit)

    ledger_rows, _cohort_id = _accepted_ingress_rows(result, run_id=args.run_id)
    frame_event_rows = _accepted_frame_event_rows(
        result,
        ledger_rows=ledger_rows,
        policy=args.policy,
        system=SYSTEM,
        scenario=args.scenario,
        codec=args.codec,
        deadline_ms=args.deadline_ms,
    )
    dataset = dict(datasets[physical_plan["dataset"]])
    resource_path = write_native_stage_resource_events(
        args.output_dir,
        frame_event_rows=frame_event_rows,
        dataset=dataset,
    )
    scenario = dict((config.get("scenarios") or {}).get(args.scenario) or {})
    scenario["name"] = args.scenario
    acceptance = publish_checkpoint_runtime(
        output_dir=args.output_dir,
        plan=publication_plan,
        scenario=scenario,
        dataset=dataset,
        result=result,
        reset_rows=reset_rows,
        reset_audit=reset_audit,
        cohort_audit=cohort_audit,
        stage_contract_runtime_path=stage_contract_path,
        worker_specs=worker_specs,
        source_specs=source_specs,
        run_id=args.run_id,
        policy=args.policy,
        deadline_ms=args.deadline_ms,
        defer_full_resource_acceptance=args.defer_full_resource_acceptance,
    )
    resource_promotion = None
    if args.defer_full_resource_acceptance:
        resource_promotion = promote_runtime_interval_and_fanout_evidence(
            runtime_resource_intervals=resource_interval_runtime_path,
            runtime_fanout_work_counters=fanout_work_runtime_path,
            output_root=args.output_dir,
            expected_run_id=args.run_id,
            ingress_ledger=pd.read_csv(args.output_dir / "ingress_ledger.csv"),
            topology_events=pd.read_csv(args.output_dir / "topology_events.csv"),
            frame_events=pd.read_csv(args.output_dir / "frame_events.csv"),
            topology_kind=args.topology_kind,
        )
    _write_json(
        runtime_output / "savant_runtime_manifest.json",
        {
            "schema_version": 3,
            "artifact_kind": "vast_savant_runtime_manifest_v3",
            "run_id": args.run_id,
            "arm_id": args.arm_id,
            "physical_worker_count": len(worker_specs),
            "source_coordinator_count": len(source_specs),
            "stage_contract_runtime_path": str(stage_contract_path),
            "resource_interval_runtime_path": str(resource_interval_runtime_path),
            "fanout_work_runtime_path": (
                str(fanout_work_runtime_path)
                if fanout_work_runtime_path is not None
                else None
            ),
            "resource_promotion": resource_promotion,
            "branch_terminal_runtime_path": str(branch_terminal_path),
            "resource_event_path": str(resource_path),
            "gstreamer_registry_seed_audit": registry_audit,
            "native_stdio_audit": native_stdio_audit,
            "policy_promotion": policy_promotion,
            "publication_acceptance": acceptance,
        },
    )
    return terminal_status(args, publication_acceptance=acceptance)


def terminal_status(
    args: argparse.Namespace,
    *,
    publication_acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    acceptance = dict(publication_acceptance)
    expected_status = (
        "pending_full_resource_validation"
        if bool(args.defer_full_resource_acceptance)
        else "accepted_native_checkpoint_arm"
    )
    _require(
        acceptance.get("status") == expected_status
        and acceptance.get("run_id") == str(args.run_id)
        and acceptance.get("system") == SYSTEM
        and acceptance.get("scenario") == str(args.scenario)
        and acceptance.get("topology_kind") == str(args.topology_kind)
        and acceptance.get("codec") == str(args.codec)
        and acceptance.get("policy") == str(args.policy),
        "Savant terminal status cannot promote an incomplete arm",
    )
    try:
        deadline_matches = math.isclose(
            float(acceptance.get("deadline_ms")),
            float(args.deadline_ms),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    except (TypeError, ValueError):
        deadline_matches = False
    _require(
        deadline_matches,
        "Savant terminal status cannot promote an incomplete arm",
    )
    return {
        "schema_version": 3,
        "artifact_kind": TERMINAL_STATUS_KIND,
        "run_id": str(args.run_id),
        "arm_id": str(args.arm_id),
        "system": SYSTEM,
        "scenario": str(args.scenario),
        "topology_kind": str(args.topology_kind),
        "codec": str(args.codec),
        "policy": str(args.policy),
        "deadline_ms": float(args.deadline_ms),
        "accepted_benchmark_sidecars_written": True,
        "publication_blockers": [],
        "publication_acceptance": acceptance,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one exact-input Savant publication ABI-v3 arm"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--adapter-config", type=Path, required=True)
    parser.add_argument("--analytics-model-manifest", type=Path, required=True)
    parser.add_argument("--policy-capability-manifest", type=Path, required=True)
    parser.add_argument("--policy-calibration", type=Path, required=True)
    parser.add_argument("--scenario", choices=tuple(SCENARIO_TOPOLOGY), required=True)
    parser.add_argument(
        "--topology-kind",
        choices=("independent_processes", "shared_video_dag"),
        required=True,
    )
    parser.add_argument("--codec", choices=("h264", "h265"), required=True)
    parser.add_argument("--policy", choices=POLICIES, required=True)
    parser.add_argument("--deadline-ms", type=float, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm-id", required=True)
    parser.add_argument("--duration", type=int, required=True)
    parser.add_argument("--ready-timeout", type=float, required=True)
    parser.add_argument("--drain-timeout", type=float, required=True)
    parser.add_argument("--start-lead-ms", type=int, required=True)
    parser.add_argument("--source-binding", action="append", default=[])
    parser.add_argument("--model-binding", action="append", default=[])
    parser.add_argument("--support-binding", action="append", default=[])
    parser.add_argument("--static-hybrid-map", type=Path)
    parser.add_argument("--defer-full-resource-acceptance", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = execute_publication_arm(args)
    except Exception as exc:
        print(f"savant publication runtime blocked: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            status,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
