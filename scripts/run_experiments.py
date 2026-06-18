#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psutil
import yaml
from benchmark_contract import (
    ContractError,
    canonicalize_frames_csv,
    git_manifest,
    load_dataset,
    sha256_file,
    summarize_frames,
    validate_frame_events,
    validate_stage_trace_coverage,
    write_json,
)
from benchmark_adapters import select_scenarios, validate_benchmark_adapter
from collect_metrics import MetricsCollector
from distributed_executor import (
    build_distributed_plan,
    load_hosts_config,
    print_distributed_plan,
    run_distributed,
)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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
    if "workload" not in raw:
        raise ValueError(
            f"scenario '{name}' must use the new schema and include a 'workload' section"
        )
    workload = dict(raw.get("workload") or {})
    pipeline = list(raw.get("pipeline") or [])
    placement = dict(raw.get("placement") or {})
    network = dict(raw.get("network") or {})
    distributed = dict(raw.get("distributed") or {})

    if not pipeline:
        raise ValueError(f"scenario '{name}' must define a non-empty pipeline")
    if "stages" not in placement:
        placement["stages"] = {stage: "local" for stage in pipeline}
    for stage in pipeline:
        if stage not in placement["stages"]:
            raise ValueError(f"scenario '{name}' placement is missing stage '{stage}'")

    obj = _object_profile(workload)
    if obj["min"] > obj["max"]:
        raise ValueError(f"scenario '{name}' object_density min cannot exceed max")

    if "stream_range" not in workload and "streams" not in workload:
        raise ValueError(f"scenario '{name}' workload must define streams or stream_range")

    return {
        "name": name,
        "description": raw.get("description", ""),
        "workload": workload,
        "pipeline": pipeline,
        "placement": placement,
        "network": network,
        "distributed": distributed,
    }


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


def validate_hardware(cfg: dict[str, Any]) -> None:
    def normalize_model_name(value: str) -> str:
        # Compare hardware names in a punctuation-insensitive way (e.g. Intel(R) vs Intel).
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        # Remove common trademark remnants that break substring checks.
        normalized = re.sub(r"\b(r|tm)\b", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    target = cfg.get("hardware_target", {})
    gpu_target = str(target.get("gpu_model", ""))
    cpu_target = str(target.get("cpu_model", ""))
    ram_target = int(target.get("ram_gb", 0))

    gpu_detected = detect_gpu_name()
    cpu_detected = detect_cpu_name()
    ram_detected = round(psutil.virtual_memory().total / (1024**3))

    print(f"[hardware] detected GPU: {gpu_detected}")
    print(f"[hardware] detected CPU: {cpu_detected}")
    print(f"[hardware] detected RAM: {ram_detected} GB")

    if gpu_target and gpu_target.lower() not in gpu_detected.lower():
        print(f"[warning] GPU mismatch: expected contains '{gpu_target}'")
    if cpu_target and normalize_model_name(cpu_target) not in normalize_model_name(cpu_detected):
        print(f"[warning] CPU mismatch: expected contains '{cpu_target}'")
    if ram_target and abs(ram_detected - ram_target) > 2:
        print(f"[warning] RAM mismatch: expected about {ram_target} GB")


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


def resolve_metric_interval_s(config: dict[str, Any], system_key: str) -> float:
    protocol = config.get("protocol", {})
    base_interval = float(protocol.get("metric_interval_s", 1.0))

    if system_key == "custom_cpp_cuda_qt":
        # Custom app is usually short and bursty; use denser sampling by default.
        return float(protocol.get("custom_cpp_cuda_qt_metric_interval_s", min(base_interval, 0.2)))

    return base_interval


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
    base_seed: int,
    dry_run_plan: bool,
) -> dict[str, Any]:
    protocol = config["protocol"]
    deadline_s = float(config["hardware_target"]["deadline_s"])
    scenario_key = scenario["name"]
    system_config = config["systems"][system_key]
    if execution_context.distributed_enabled and not bool(system_config.get("supports_distributed", False)):
        raise ContractError(f"system '{system_key}' does not support distributed execution")
    benchmark_adapter = validate_benchmark_adapter(
        system_key=system_key,
        scenario=scenario,
        distributed=execution_context.distributed_enabled,
        mode=mode,
    )
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
            system_key,
            f"rep{repeat_index:02d}",
        )
        if part
    )

    scenario_dir = run_root / scenario_key
    if variant_name:
        scenario_dir /= f"variant_{variant_name}"
    scenario_dir = scenario_dir / f"streams_{streams}" / system_key / f"rep_{repeat_index:02d}"
    if not dry_run_plan:
        scenario_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = scenario_dir / "system_metrics.csv"
    frames_path = scenario_dir / "frames.csv"
    frame_events_path = scenario_dir / "frame_events.csv"
    network_path = scenario_dir / "network_metrics.csv"
    metadata_path = scenario_dir / "run_metadata.json"

    metric_interval_s = resolve_metric_interval_s(config, system_key)
    collector = MetricsCollector(metrics_path, interval_s=metric_interval_s)

    command_template = system_config["command"]
    base_cmd = command_template.format(
        scenario=scenario_key,
        duration_s=duration_s,
        streams=streams,
        min_objects=min_objects,
        max_objects=max_objects,
        output_dir=scenario_dir,
    )
    video_layout_dir = str(Path(dataset["streams"][0]["absolute_path"]).parent)
    ql_heft_artifact = str(config.get("benchmark", {}).get("ql_heft_policy_artifact", ""))
    command_env = {
        "ADAPTER_BACKEND": backend,
        "ADAPTER_DETECTOR": detector,
        "BENCHMARK_MODE": mode,
        "DATASET_NAME": dataset["name"],
        "DATASET_STREAMS_JSON": dataset_streams_json(dataset),
        "EXPERIMENT_REPEAT_INDEX": str(repeat_index),
        "EXPERIMENT_RUN_ID": run_id,
        "EXPERIMENT_RUN_SEED": str(run_seed),
        "QL_HEFT_POLICY_ARTIFACT": ql_heft_artifact,
        "SCHEDULER_POLICY": policy,
        "VIDEO_LAYOUT_DIR": video_layout_dir,
    }
    cmd = (
        f"{scenario_env_prefix(scenario, distributed=execution_context.distributed_enabled, extra=command_env)} "
        f"{base_cmd}"
    )

    distributed_enabled = execution_context.distributed_enabled
    run_relpath = str(scenario_dir)
    distributed_steps: list[dict[str, Any]] = []
    if distributed_enabled:
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
                f"system={system_key} command={cmd}"
            )
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": system_key,
            "scenario": scenario_key,
            "repeat": repeat_index,
            "exit_code": 0,
            "status": "planned",
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
            "throughput_fps": float("nan"),
            "latency_p50_ms": float("nan"),
            "latency_p95_ms": float("nan"),
            "latency_p99_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
            "telemetry_source": "",
        }

    warmup_s = float(protocol.get("warmup_s", 0))
    if warmup_s > 0:
        time.sleep(warmup_s)

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

    child_env = os.environ.copy()
    child_env["EXPERIMENT_RUN_SEED"] = str(run_seed)
    child_env["EXPERIMENT_REPEAT_INDEX"] = str(repeat_index)

    distributed_result = None
    collector.start()
    try:
        if distributed_enabled:
            distributed_result = run_distributed(
                steps=distributed_steps,
                project_root=Path.cwd(),
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
            )
            completed = subprocess.CompletedProcess(cmd, distributed_result.exit_code)
        else:
            completed = subprocess.run(cmd, shell=True, check=False, timeout=cmd_timeout_s, env=child_env)
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(exc.cmd, returncode=124)
        raise RuntimeError(
            f"Command timed out after {cmd_timeout_s}s for system={system_key}, "
            f"scenario={scenario_key}, repeat={repeat_index}. "
            f"Inspect run directory: {scenario_dir}"
        ) from exc
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
            "throughput_fps": float("nan"),
            "latency_p50_ms": float("nan"),
            "latency_p95_ms": float("nan"),
            "latency_p99_ms": float("nan"),
            "slo_violation_rate_percent": float("nan"),
            "frames": 0,
            "telemetry_source": "",
        }
        write_json(
            metadata_path,
            {
                "schema_version": 2,
                "result": result,
                "resolved_scenario": scenario,
                "dataset": dataset,
                "git": git_manifest(Path.cwd()),
                "adapter": adapter_manifest(system_config),
                "benchmark_adapter": benchmark_adapter.metadata() if benchmark_adapter else {},
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
            deadline_s=deadline_s,
            elapsed_s=sampled_s,
            run_id=run_id,
            detector=detector,
            backend=backend,
        )
    canonicalize_frames_csv(
        frames_path,
        mode=mode,
        run_id=run_id,
        detector=detector,
        backend=backend,
    )
    if mode == "benchmark":
        validate_frame_events(frame_events_path)
        validate_stage_trace_coverage(
            frames_path,
            frame_events_path,
            required_stages=[str(stage) for stage in scenario.get("pipeline", [])],
        )
    summary = summarize_frames(frames_path, deadline_s=deadline_s, measurement_s=duration_s)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": system_key,
        "scenario": scenario_key,
        "repeat": repeat_index,
        "exit_code": int(completed.returncode),
        "status": "completed",
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
        **summary,
    }

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
        "git": git_manifest(Path.cwd()),
        "adapter": adapter_manifest(system_config),
        "benchmark_adapter": benchmark_adapter.metadata() if benchmark_adapter else {},
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
        "hosts_config": str(execution_context.hosts_config_path),
        "hardware_target": config.get("hardware_target", {}),
        "protocol": config.get("protocol", {}),
    }

    write_json(metadata_path, metadata)
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
        variant_scenario = json.loads(json.dumps(scenario))
        if isinstance(variant, dict):
            variant_scenario["workload"].update(variant)
            variant_scenario["workload"]["variant"] = str(variant.get("name", "variant"))
            if "placement_policy" in variant:
                variant_scenario["placement"]["policy"] = str(variant["placement_policy"])
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
    parser.add_argument("--policy", default="static_hybrid")
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
    hosts_cfg = load_hosts_config(args.hosts_config)
    policies = list(cfg.get("benchmark", {}).get("scheduler_policies") or [])
    if args.policy not in policies:
        raise ContractError(f"unknown scheduler policy '{args.policy}'; expected one of: {', '.join(policies)}")
    run_kind = normalize_run_kind(args.run_kind, local_only=args.local_only)
    if args.dry_run_plan and run_kind == "distributed" and not hosts_cfg.get("hosts"):
        hosts_example = args.hosts_config.with_name("hosts.example.yaml")
        if hosts_example.exists():
            print(f"[warning] {args.hosts_config} is empty or missing; using {hosts_example} for dry-run planning")
            hosts_cfg = load_hosts_config(hosts_example)
    base_seed = int(args.seed if args.seed is not None else cfg.get("benchmark", {}).get("default_seed", 20260323))
    default_datasets = cfg.get("benchmark", {}).get("default_dataset", {})
    dataset_name = args.dataset or str(default_datasets.get(args.mode, ""))
    dataset = load_dataset(
        Path(cfg["benchmark"]["dataset_manifest"]),
        dataset_name,
        mode=args.mode,
        project_root=Path.cwd(),
        require_files=args.mode == "benchmark" and not args.dry_run_plan,
        allow_placeholder_checksums=args.dry_run_plan,
    )

    if args.warmup >= 0:
        cfg["protocol"]["warmup_s"] = int(args.warmup)

    validate_hardware(cfg)

    systems = list(cfg["systems"].keys()) if args.systems == ["all"] else args.systems
    scenarios = select_scenarios(cfg, args.scenarios, mode=args.mode, run_kind=run_kind)

    repeats = int(cfg["protocol"]["repeats"] if args.repeats < 0 else args.repeats)
    measurement_s = int(cfg["protocol"]["measurement_s"] if args.measurement < 0 else args.measurement)

    run_root = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    if not args.dry_run_plan:
        run_root.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []

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
                    project_root=Path.cwd(),
                )
                for rep in range(1, repeats + 1):
                    row = run_one(
                        config=cfg,
                        dataset=dataset,
                        system_key=system,
                        scenario=variant["scenario"],
                        streams=variant["streams"],
                        min_objects=variant["min_objects"],
                        max_objects=variant["max_objects"],
                        duration_s=_scenario_duration_s(variant["scenario"], measurement_s),
                        repeat_index=rep,
                        run_root=run_root,
                        execution_context=execution_context,
                        mode=args.mode,
                        policy=args.policy,
                        base_seed=base_seed,
                        dry_run_plan=args.dry_run_plan,
                    )
                    all_rows.append(row)
                    if row["status"] == "skipped":
                        print(
                            f"[skipped] scenario={scenario} streams={variant['streams']} "
                            f"system={system} rep={rep} reason={row['skip_reason']}"
                        )
                    else:
                        print(
                            f"[done] scenario={scenario} streams={variant['streams']} system={system} rep={rep} "
                            f"fps={row['throughput_fps']} p95={row['latency_p95_ms']} "
                            f"slo={row['slo_violation_rate_percent']}%"
                        )

    if args.dry_run_plan:
        print("[result] dry run plan complete")
        return

    summary_csv = run_root / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "timestamp",
            "system",
            "scenario",
            "repeat",
            "exit_code",
            "status",
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
            "throughput_fps",
            "latency_p50_ms",
            "latency_p95_ms",
            "latency_p99_ms",
            "slo_violation_rate_percent",
            "frames",
            "telemetry_source",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    print(f"[result] summary saved to {summary_csv}")


if __name__ == "__main__":
    try:
        main()
    except ContractError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
