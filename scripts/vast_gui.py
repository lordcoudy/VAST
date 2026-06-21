#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from benchmark_adapters import select_scenarios, validate_benchmark_adapter  # noqa: E402
from benchmark_contract import ContractError, load_dataset  # noqa: E402
from distributed_executor import load_hosts_config  # noqa: E402
from run_experiments import expand_scenario, load_config, normalize_scenario  # noqa: E402


REQUIRED_COMMAND_PLACEHOLDERS = [
    "{scenario}",
    "{duration_s}",
    "{streams}",
    "{min_objects}",
    "{max_objects}",
    "{output_dir}",
]
CONFIG_FILES = {
    "experiments": Path("configs/experiments.yaml"),
    "datasets": Path("configs/datasets.yaml"),
    "hosts": Path("configs/hosts.yaml"),
}
HOSTS_EXAMPLE = Path("configs/hosts.example.yaml")
ENV_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
MAX_TAIL_BYTES = 80_000
MAX_DETAIL_ROWS = 50_000


class GuiError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        return yaml.safe_load(source) or {}


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def parse_yaml_text(text: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise GuiError(f"invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GuiError("top-level YAML value must be a mapping")
    return parsed


def ensure_within_project(project_root: Path, path: Path) -> Path:
    resolved = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise GuiError(f"path escapes project root: {path}") from exc
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as target:
            target.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def positive_number(value: Any, name: str, *, allow_zero: bool = False) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GuiError(f"{name} must be numeric") from exc
    if allow_zero:
        if number < 0:
            raise GuiError(f"{name} must be >= 0")
    elif number <= 0:
        raise GuiError(f"{name} must be > 0")


def valid_percent(value: Any, name: str) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GuiError(f"{name} must be numeric") from exc
    if number < 0 or number > 100:
        raise GuiError(f"{name} must be between 0 and 100")


def validate_experiments_config(cfg: dict[str, Any]) -> None:
    if int(cfg.get("schema_version", 0)) != 2:
        raise GuiError("configs/experiments.yaml must use schema_version: 2")
    for section in ("benchmark", "hardware_target", "protocol", "scenarios", "systems"):
        if not isinstance(cfg.get(section), dict):
            raise GuiError(f"experiments config must define mapping section '{section}'")

    protocol = cfg["protocol"]
    for key in ("repeats", "warmup_s", "measurement_s", "metric_interval_s"):
        positive_number(protocol.get(key), f"protocol.{key}", allow_zero=key == "warmup_s")
    if "custom_cpp_cuda_qt_metric_interval_s" in protocol:
        positive_number(protocol["custom_cpp_cuda_qt_metric_interval_s"], "protocol.custom_cpp_cuda_qt_metric_interval_s")

    hardware = cfg["hardware_target"]
    positive_number(hardware.get("deadline_s"), "hardware_target.deadline_s")
    positive_number(hardware.get("ram_gb"), "hardware_target.ram_gb")

    transport = cfg.get("transport", {})
    if isinstance(transport, dict):
        positive_number(transport.get("max_clock_offset_ms", 0), "transport.max_clock_offset_ms", allow_zero=True)
        positive_number(transport.get("startup_grace_s", 0), "transport.startup_grace_s", allow_zero=True)
        positive_number(transport.get("stream_port_stride", 1), "transport.stream_port_stride")
        for key, value in (transport.get("role_ports") or {}).items():
            port = int(value)
            if port < 1 or port > 65535:
                raise GuiError(f"transport.role_ports.{key} must be a valid TCP/UDP port")

    policies = cfg.get("benchmark", {}).get("scheduler_policies") or []
    if not isinstance(policies, list) or not policies:
        raise GuiError("benchmark.scheduler_policies must be a non-empty list")

    for name, raw in cfg["scenarios"].items():
        scenario = normalize_scenario(name, raw)
        workload = scenario.get("workload", {})
        obj = workload.get("object_density") or {}
        if obj:
            positive_number(obj.get("min", 0), f"scenarios.{name}.workload.object_density.min", allow_zero=True)
            positive_number(obj.get("max", 0), f"scenarios.{name}.workload.object_density.max", allow_zero=True)
            if int(obj.get("min", 0)) > int(obj.get("max", 0)):
                raise GuiError(f"scenarios.{name}.workload.object_density.min cannot exceed max")
        if "streams" in workload:
            positive_number(workload["streams"], f"scenarios.{name}.workload.streams")
        if "stream_range" in workload:
            stream_range = workload["stream_range"]
            if not isinstance(stream_range, list) or len(stream_range) != 2:
                raise GuiError(f"scenarios.{name}.workload.stream_range must be [start, end]")
            start, end = int(stream_range[0]), int(stream_range[1])
            if start <= 0 or end < start:
                raise GuiError(f"scenarios.{name}.workload.stream_range must use positive ascending values")
        network = scenario.get("network") or {}
        for pct_key in ("packet_loss_percent",):
            if pct_key in network:
                valid_percent(network[pct_key], f"scenarios.{name}.network.{pct_key}")

    for name, system in cfg["systems"].items():
        command = str(system.get("command", ""))
        if not command:
            raise GuiError(f"systems.{name}.command is required")
        missing = [placeholder for placeholder in REQUIRED_COMMAND_PLACEHOLDERS if placeholder not in command]
        if missing:
            raise GuiError(f"systems.{name}.command is missing placeholders: {', '.join(missing)}")


def validate_datasets_config(cfg: dict[str, Any]) -> None:
    if int(cfg.get("schema_version", 0)) != 1:
        raise GuiError("configs/datasets.yaml must use schema_version: 1")
    datasets = cfg.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise GuiError("datasets config must define at least one dataset")
    for name, dataset in datasets.items():
        if not isinstance(dataset, dict):
            raise GuiError(f"datasets.{name} must be a mapping")
        if "fps" in dataset:
            positive_number(dataset["fps"], f"datasets.{name}.fps")
        streams = dataset.get("streams")
        if not isinstance(streams, list) or not streams:
            raise GuiError(f"datasets.{name}.streams must be a non-empty list")
        for index, stream in enumerate(streams):
            if not isinstance(stream, dict) or not str(stream.get("path", "")).strip():
                raise GuiError(f"datasets.{name}.streams[{index}].path is required")


def validate_hosts_config(cfg: dict[str, Any]) -> None:
    hosts = cfg.get("hosts")
    if hosts is None:
        cfg["hosts"] = []
        return
    if not isinstance(hosts, list):
        raise GuiError("hosts config must define hosts as a list")
    for index, host in enumerate(hosts):
        if not isinstance(host, dict):
            raise GuiError(f"hosts[{index}] must be a mapping")
        if not str(host.get("name", "")).strip():
            raise GuiError(f"hosts[{index}].name is required")
        if not str(host.get("address", "")).strip():
            raise GuiError(f"hosts[{index}].address is required")
        roles = host.get("roles") or []
        if not isinstance(roles, list) or not roles:
            raise GuiError(f"hosts[{index}].roles must be a non-empty list")
        port = int(host.get("port", 22))
        if port < 1 or port > 65535:
            raise GuiError(f"hosts[{index}].port must be a valid TCP port")


def validate_config(kind: str, cfg: dict[str, Any]) -> None:
    if kind == "experiments":
        validate_experiments_config(cfg)
    elif kind == "datasets":
        validate_datasets_config(cfg)
    elif kind == "hosts":
        validate_hosts_config(cfg)
    else:
        raise GuiError(f"unknown config kind: {kind}", status=404)


def normalize_list(value: Any, default: str = "all") -> list[str]:
    if value is None or value == "":
        return [default]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        return parts or [default]
    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts or [default]
    return [str(value)]


def parse_env_overrides(value: Any) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        overrides: dict[str, str] = {}
        for line in value.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                raise GuiError(f"environment override must be KEY=value: {line}")
            key, raw_value = stripped.split("=", 1)
            key = key.strip()
            if not ENV_KEY_RE.match(key):
                raise GuiError(f"invalid environment variable name: {key}")
            overrides[key] = raw_value.strip()
        return overrides
    if isinstance(value, dict):
        overrides = {}
        for key, raw_value in value.items():
            key = str(key).strip()
            if not ENV_KEY_RE.match(key):
                raise GuiError(f"invalid environment variable name: {key}")
            overrides[key] = str(raw_value)
        return overrides
    raise GuiError("env_overrides must be a mapping or KEY=value text")


def build_run_command(project_root: Path, request: dict[str, Any], *, dry_run: bool = False) -> tuple[list[str], dict[str, str]]:
    command = [
        sys.executable,
        "scripts/run_experiments.py",
        "--config",
        str(request.get("config", "configs/experiments.yaml")),
    ]
    mode = str(request.get("mode", "benchmark"))
    if mode not in {"smoke", "benchmark"}:
        raise GuiError("mode must be smoke or benchmark")
    command.extend(["--mode", mode])

    for flag, key, default in (
        ("--systems", "systems", "all"),
        ("--scenarios", "scenarios", "all"),
    ):
        command.append(flag)
        command.extend(normalize_list(request.get(key), default))

    scalar_flags = [
        ("--repeats", "repeats"),
        ("--measurement", "measurement"),
        ("--warmup", "warmup"),
        ("--output-root", "output_root"),
        ("--hosts-config", "hosts_config"),
        ("--dataset", "dataset"),
        ("--policy", "policy"),
        ("--run-kind", "run_kind"),
        ("--single-server-host", "single_server_host"),
        ("--single-server-port", "single_server_port"),
        ("--single-server-user", "single_server_user"),
        ("--seed", "seed"),
        ("--resume-run-root", "resume_run_root"),
    ]
    defaults = {
        "output_root": "runs",
        "hosts_config": "configs/hosts.yaml",
        "policy": "static_hybrid",
        "run_kind": "auto",
        "single_server_host": "127.0.0.1",
        "single_server_port": 22,
    }
    for flag, key in scalar_flags:
        value = request.get(key, defaults.get(key))
        if value in (None, ""):
            continue
        if key in {"repeats", "measurement", "warmup", "single_server_port", "seed"}:
            int(value)
        command.extend([flag, str(value)])

    if bool(request.get("local_only", False)):
        command.append("--local-only")
    if dry_run or bool(request.get("dry_run", False)):
        command.append("--dry-run-plan")

    env_overrides = parse_env_overrides(request.get("env_overrides"))
    return command, env_overrides


def normalize_summary(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "throughput_mean_fps": "throughput_fps",
        "mean_fps": "throughput_fps",
        "p95_latency_ms": "latency_p95_ms",
    }
    for old, new in aliases.items():
        if new not in df.columns and old in df.columns:
            df = df.rename(columns={old: new})
    defaults = {
        "timestamp": "",
        "system": "",
        "scenario": "",
        "repeat": 0,
        "status": "legacy",
        "skip_reason": "",
        "streams": 0,
        "duration_s": 0,
        "scenario_variant": "",
        "placement_policy": "",
        "distributed": False,
        "deployment_mode": "legacy",
        "host_topology": "legacy",
        "detector": "legacy",
        "backend": "legacy",
        "policy": "legacy",
        "dataset": "legacy",
        "throughput_fps": float("nan"),
        "latency_p50_ms": float("nan"),
        "latency_p95_ms": float("nan"),
        "latency_p99_ms": float("nan"),
        "slo_violation_rate_percent": float("nan"),
        "frames": 0,
        "telemetry_source": "legacy",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
    return df


def finite_or_none(value: Any) -> float | int | str | None:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def rows_for_json(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if limit is not None:
        df = df.head(limit)
    return [
        {column: finite_or_none(value) for column, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def tail_file(path: Path, max_bytes: int = MAX_TAIL_BYTES) -> str:
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as source:
        if size > max_bytes:
            source.seek(size - max_bytes)
        data = source.read(max_bytes)
    return data.decode("utf-8", errors="replace")


@dataclass
class JobRecord:
    id: str
    kind: str
    command: list[str]
    cwd: str
    stdout_path: Path
    stderr_path: Path
    started_at: float
    env_overrides: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen[str] | None = None
    status: str = "running"
    exit_code: int | None = None
    ended_at: float | None = None
    summary_path: str = ""

    def to_json(self, include_logs: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "cwd": self.cwd,
            "started_at": datetime.fromtimestamp(self.started_at, timezone.utc).isoformat(),
            "ended_at": (
                datetime.fromtimestamp(self.ended_at, timezone.utc).isoformat()
                if self.ended_at
                else None
            ),
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "summary_path": self.summary_path,
            "env_overrides": self.env_overrides,
        }
        if include_logs:
            payload["stdout_tail"] = tail_file(self.stdout_path)
            payload["stderr_tail"] = tail_file(self.stderr_path)
        return payload


class JobManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.root = project_root / "runs" / ".web" / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _persist(self, job: JobRecord) -> None:
        atomic_write_text(self._job_path(job.id), json.dumps(job.to_json(include_logs=False), indent=2))

    def _infer_summary_path(self, job: JobRecord) -> str:
        stdout = tail_file(job.stdout_path)
        match = re.search(r"\[result\]\s+summary saved to\s+(.+summary\.csv)", stdout)
        if match:
            return str((self.project_root / match.group(1).strip()).resolve())
        return job.summary_path

    def refresh(self, job: JobRecord) -> JobRecord:
        if job.process is not None and job.status == "running":
            exit_code = job.process.poll()
            if exit_code is not None:
                job.exit_code = int(exit_code)
                job.status = "completed" if exit_code == 0 else "failed"
                job.ended_at = time.time()
                job.summary_path = self._infer_summary_path(job)
                self._persist(job)
        return job

    def start(self, command: list[str], env_overrides: dict[str, str] | None = None, *, kind: str = "run") -> JobRecord:
        env = os.environ.copy()
        env.update(env_overrides or {})
        job_id = f"{utc_timestamp()}_{uuid.uuid4().hex[:8]}"
        stdout_path = self.root / f"{job_id}.stdout.log"
        stderr_path = self.root / f"{job_id}.stderr.log"
        stdout = stdout_path.open("w", encoding="utf-8")
        stderr = stderr_path.open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.project_root),
                env=env,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
        finally:
            stdout.close()
            stderr.close()
        job = JobRecord(
            id=job_id,
            kind=kind,
            command=command,
            cwd=str(self.project_root),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            started_at=time.time(),
            env_overrides=env_overrides or {},
            process=process,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._persist(job)
        return job

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return self.refresh(job)
        path = self._job_path(job_id)
        if not path.exists():
            raise GuiError(f"unknown job id: {job_id}", status=404)
        data = json.loads(path.read_text(encoding="utf-8"))
        return JobRecord(
            id=data["id"],
            kind=data.get("kind", "run"),
            command=list(data.get("command") or []),
            cwd=data.get("cwd", str(self.project_root)),
            stdout_path=Path(data["stdout_path"]),
            stderr_path=Path(data["stderr_path"]),
            started_at=datetime.fromisoformat(data["started_at"]).timestamp(),
            env_overrides=dict(data.get("env_overrides") or {}),
            process=None,
            status=data.get("status", "unknown"),
            exit_code=data.get("exit_code"),
            ended_at=(datetime.fromisoformat(data["ended_at"]).timestamp() if data.get("ended_at") else None),
            summary_path=data.get("summary_path", ""),
        )

    def list(self) -> list[JobRecord]:
        jobs: dict[str, JobRecord] = {}
        for path in sorted(self.root.glob("*.json")):
            try:
                job = self.get(path.stem)
                jobs[job.id] = job
            except Exception:
                continue
        with self._lock:
            for job_id, job in self._jobs.items():
                jobs[job_id] = self.refresh(job)
        return sorted(jobs.values(), key=lambda job: job.started_at, reverse=True)

    def stop(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if job.process is None or job.status != "running":
            return job
        job.process.terminate()
        try:
            job.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait(timeout=3)
        job.exit_code = int(job.process.returncode or 0)
        job.status = "stopped"
        job.ended_at = time.time()
        self._persist(job)
        return job


class VastGuiApp:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = project_root.resolve()
        self.web_root = self.project_root / "web"
        self.backup_root = self.project_root / "runs" / ".web" / "backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.jobs = JobManager(self.project_root)
        self._analytics_cache: dict[str, Any] = {}

    def config_path(self, kind: str) -> Path:
        if kind not in CONFIG_FILES:
            raise GuiError(f"unknown config kind: {kind}", status=404)
        return ensure_within_project(self.project_root, CONFIG_FILES[kind])

    def ensure_hosts_file(self) -> Path:
        hosts_path = self.config_path("hosts")
        if hosts_path.exists():
            return hosts_path
        example = ensure_within_project(self.project_root, HOSTS_EXAMPLE)
        if example.exists():
            hosts_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, hosts_path)
            return hosts_path
        atomic_write_text(hosts_path, "hosts: []\n")
        return hosts_path

    def load_config_kind(self, kind: str) -> tuple[dict[str, Any], str, Path]:
        path = self.ensure_hosts_file() if kind == "hosts" else self.config_path(kind)
        if not path.exists():
            raise GuiError(f"config file not found: {path}", status=404)
        raw = path.read_text(encoding="utf-8")
        parsed = parse_yaml_text(raw)
        return parsed, raw, path

    def load_all_configs(self) -> dict[str, Any]:
        experiments, exp_raw, exp_path = self.load_config_kind("experiments")
        datasets, ds_raw, ds_path = self.load_config_kind("datasets")
        hosts, hosts_raw, hosts_path = self.load_config_kind("hosts")
        benchmark = experiments.get("benchmark", {})
        systems = experiments.get("systems", {})
        scenarios = experiments.get("scenarios", {})
        datasets_map = datasets.get("datasets", {})
        return {
            "configs": {"experiments": experiments, "datasets": datasets, "hosts": hosts},
            "raw": {"experiments": exp_raw, "datasets": ds_raw, "hosts": hosts_raw},
            "paths": {
                "experiments": str(exp_path),
                "datasets": str(ds_path),
                "hosts": str(hosts_path),
            },
            "selectors": {
                "systems": [
                    {
                        "key": key,
                        "label": value.get("label", key),
                        "backend": value.get("backend", ""),
                        "detector": value.get("detector", ""),
                        "supports_distributed": bool(value.get("supports_distributed", False)),
                    }
                    for key, value in systems.items()
                ],
                "scenarios": [
                    {
                        "key": key,
                        "description": value.get("description", ""),
                        "distributed": bool((value.get("distributed") or {}).get("enabled")),
                        "benchmark_status": value.get("benchmark_status", ""),
                    }
                    for key, value in scenarios.items()
                ],
                "datasets": [
                    {
                        "key": key,
                        "description": value.get("description", ""),
                        "kind": value.get("kind", ""),
                        "publishable": bool(value.get("publishable", False)),
                        "fps": value.get("fps", ""),
                    }
                    for key, value in datasets_map.items()
                ],
                "policies": list(benchmark.get("scheduler_policies") or []),
                "modes": ["benchmark", "smoke"],
                "run_kinds": ["auto", "heterogeneous", "single-server-distributed", "distributed"],
            },
            "form_metadata": {
                "required_command_placeholders": REQUIRED_COMMAND_PLACEHOLDERS,
                "cmake_options": [
                    "VAST_BUILD_NATIVE_GST_PROBE",
                    "VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN",
                    "VAST_BUILD_CUSTOM_CUDA_QT",
                ],
                "setup_flags": [
                    "INSTALL_DOCKER",
                    "INSTALL_GPU_STACK",
                    "INSTALL_OPENVINO",
                    "INSTALL_DEEPSTREAM",
                    "INSTALL_SAVANT",
                    "PREPARE_ASSETS",
                ],
            },
        }

    def backup_config(self, kind: str, source_path: Path) -> str:
        self.backup_root.mkdir(parents=True, exist_ok=True)
        backup = self.backup_root / f"{kind}_{utc_timestamp()}.yaml"
        if source_path.exists():
            shutil.copyfile(source_path, backup)
        else:
            atomic_write_text(backup, "")
        return str(backup)

    def save_config(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if "yaml" in payload:
            data = parse_yaml_text(str(payload["yaml"]))
        elif "data" in payload:
            data = payload["data"]
            if not isinstance(data, dict):
                raise GuiError("data must be a mapping")
        else:
            raise GuiError("request must include 'data' or 'yaml'")
        validate_config(kind, data)
        path = self.ensure_hosts_file() if kind == "hosts" else self.config_path(kind)
        backup = self.backup_config(kind, path)
        raw = dump_yaml(data)
        atomic_write_text(path, raw)
        return {"kind": kind, "path": str(path), "backup": backup, "data": data, "yaml": raw}

    def validate_current(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        request = request or {}
        payload = self.load_all_configs()
        for kind, data in payload["configs"].items():
            validate_config(kind, data)
        experiments = payload["configs"]["experiments"]
        errors: list[str] = []
        for scenario_key, raw in experiments.get("scenarios", {}).items():
            scenario = normalize_scenario(scenario_key, raw)
            for system_key in experiments.get("systems", {}):
                try:
                    validate_benchmark_adapter(
                        system_key=system_key,
                        scenario=scenario,
                        distributed=bool(scenario.get("distributed", {}).get("enabled")),
                        mode=str(request.get("mode", "benchmark")),
                    )
                except ContractError as exc:
                    errors.append(f"{system_key}/{scenario_key}: {exc}")
        if errors:
            raise GuiError("; ".join(errors))
        if request.get("dataset"):
            try:
                load_dataset(
                    self.project_root / experiments["benchmark"]["dataset_manifest"],
                    str(request["dataset"]),
                    mode=str(request.get("mode", "benchmark")),
                    project_root=self.project_root,
                    require_files=False,
                    allow_placeholder_checksums=True,
                )
            except ContractError as exc:
                raise GuiError(str(exc)) from exc
        return {"ok": True, "message": "configuration is valid"}

    def dry_run(self, request: dict[str, Any]) -> dict[str, Any]:
        command, env_overrides = build_run_command(self.project_root, request, dry_run=True)
        env = os.environ.copy()
        env.update(env_overrides)
        timeout_s = int(request.get("timeout_s", 120))
        completed = subprocess.run(
            command,
            cwd=str(self.project_root),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "command": command,
            "env_overrides": env_overrides,
            "exit_code": int(completed.returncode),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "ok": completed.returncode == 0,
        }

    def start_run(self, request: dict[str, Any]) -> dict[str, Any]:
        command, env_overrides = build_run_command(self.project_root, request, dry_run=False)
        job = self.jobs.start(command, env_overrides, kind="run")
        return job.to_json(include_logs=True)

    def tool_command(self, request: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        tool = str(request.get("tool", ""))
        env_overrides = parse_env_overrides(request.get("env_overrides"))
        if tool == "check_system":
            return [sys.executable, "scripts/check_system.py"], env_overrides
        if tool == "analyze":
            command = [sys.executable, "scripts/analyze_results.py"]
            if request.get("run"):
                command.extend(["--run", str(request["run"])])
            if request.get("include_nonpublishable"):
                command.append("--include-nonpublishable")
            return command, env_overrides
        if tool == "prepare_assets":
            return ["bash", "scripts/prepare_assets.sh"], env_overrides
        if tool == "cmake_configure":
            command = ["cmake", "-S", ".", "-B", "build/cmake"]
            options = request.get("cmake_options") or {}
            if isinstance(options, dict):
                for key, value in options.items():
                    if key not in {
                        "VAST_BUILD_NATIVE_GST_PROBE",
                        "VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN",
                        "VAST_BUILD_CUSTOM_CUDA_QT",
                    }:
                        raise GuiError(f"unsupported CMake option: {key}")
                    command.append(f"-D{key}={'ON' if bool(value) else 'OFF'}")
            return command, env_overrides
        if tool == "cmake_build":
            target = str(request.get("target", "")).strip()
            command = ["cmake", "--build", "build/cmake"]
            if target:
                command.extend(["--target", target])
            return command, env_overrides
        raise GuiError(f"unknown tool: {tool}")

    def preview_tool(self, request: dict[str, Any]) -> dict[str, Any]:
        command, env_overrides = self.tool_command(request)
        return {"command": command, "env_overrides": env_overrides}

    def start_tool(self, request: dict[str, Any]) -> dict[str, Any]:
        command, env_overrides = self.tool_command(request)
        job = self.jobs.start(command, env_overrides, kind=str(request.get("tool", "tool")))
        return job.to_json(include_logs=True)

    def summary_files(self) -> list[Path]:
        runs_root = self.project_root / "runs"
        if not runs_root.exists():
            return []
        return sorted(
            path
            for path in runs_root.rglob("summary.csv")
            if ".web" not in path.parts
        )

    def analytics(self) -> dict[str, Any]:
        summaries = self.summary_files()
        signature = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in summaries)
        if self._analytics_cache.get("signature") == signature:
            return self._analytics_cache["payload"]

        frames: list[pd.DataFrame] = []
        runs: list[dict[str, Any]] = []
        for summary_path in summaries:
            try:
                df = normalize_summary(pd.read_csv(summary_path))
            except Exception:
                continue
            run_id = str(summary_path.parent.relative_to(self.project_root / "runs")).replace("\\", "/")
            df["run_id"] = run_id
            df["run_path"] = str(summary_path.parent)
            frames.append(df)
            runs.append(
                {
                    "run_id": run_id,
                    "run_path": str(summary_path.parent),
                    "summary_path": str(summary_path),
                    "rows": int(df.shape[0]),
                    "mtime": datetime.fromtimestamp(summary_path.stat().st_mtime, timezone.utc).isoformat(),
                }
            )
        if frames:
            all_rows = pd.concat(frames, ignore_index=True)
        else:
            all_rows = normalize_summary(pd.DataFrame())
            all_rows["run_id"] = ""
            all_rows["run_path"] = ""

        completed = all_rows[all_rows["status"].astype(str) == "completed"].copy()
        group_cols = ["scenario", "system", "policy", "dataset", "deployment_mode"]
        if completed.empty:
            aggregates = pd.DataFrame(columns=group_cols)
        else:
            aggregates = (
                completed.groupby(group_cols, as_index=False, dropna=False)
                .agg(
                    repeats=("repeat", "count"),
                    throughput_fps_mean=("throughput_fps", "mean"),
                    latency_p50_ms_mean=("latency_p50_ms", "mean"),
                    latency_p95_ms_mean=("latency_p95_ms", "mean"),
                    latency_p99_ms_mean=("latency_p99_ms", "mean"),
                    slo_violation_rate_percent_mean=("slo_violation_rate_percent", "mean"),
                    frames_sum=("frames", "sum"),
                )
                .sort_values(["scenario", "throughput_fps_mean"], ascending=[True, False])
            )

        latest_run = runs[-1] if runs else None
        kpis = {
            "run_count": len(runs),
            "summary_rows": int(all_rows.shape[0]),
            "completed_rows": int(completed.shape[0]),
            "avg_throughput_fps": finite_or_none(completed["throughput_fps"].mean()) if not completed.empty else None,
            "avg_latency_p95_ms": finite_or_none(completed["latency_p95_ms"].mean()) if not completed.empty else None,
            "avg_slo_violation_rate_percent": (
                finite_or_none(completed["slo_violation_rate_percent"].mean()) if not completed.empty else None
            ),
        }
        payload = {
            "runs": runs,
            "latest_run": latest_run,
            "kpis": kpis,
            "summary_rows": rows_for_json(all_rows.sort_values(["run_id", "scenario", "system"]).tail(2000)),
            "aggregates": rows_for_json(aggregates),
        }
        self._analytics_cache = {"signature": signature, "payload": payload}
        return payload

    def _resolve_run_dir(self, run_id: str) -> Path:
        run_dir = ensure_within_project(self.project_root, Path("runs") / run_id)
        if not run_dir.exists() or not run_dir.is_dir():
            raise GuiError(f"run not found: {run_id}", status=404)
        return run_dir

    def analytics_detail(self, run_id: str) -> dict[str, Any]:
        run_dir = self._resolve_run_dir(run_id)
        summary_path = run_dir / "summary.csv"
        summary_rows: list[dict[str, Any]] = []
        if summary_path.exists():
            summary_rows = rows_for_json(normalize_summary(pd.read_csv(summary_path)), limit=5000)

        frame_files = sorted(run_dir.rglob("frames.csv"))
        event_files = sorted(run_dir.rglob("frame_events.csv"))
        system_metric_files = sorted(run_dir.rglob("system_metrics.csv"))
        network_files = sorted(run_dir.rglob("network_metrics.csv"))
        metadata_files = sorted(run_dir.rglob("run_metadata.json"))

        frames_stats: list[dict[str, Any]] = []
        frame_samples: list[dict[str, Any]] = []
        for path in frame_files[:20]:
            df = pd.read_csv(path, nrows=MAX_DETAIL_ROWS)
            if df.empty:
                continue
            latency = pd.to_numeric(df.get("e2e_latency_ms", pd.Series(dtype=float)), errors="coerce")
            frames_stats.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "rows_sampled": int(df.shape[0]),
                    "latency_p50_ms": finite_or_none(latency.quantile(0.50)),
                    "latency_p95_ms": finite_or_none(latency.quantile(0.95)),
                    "latency_p99_ms": finite_or_none(latency.quantile(0.99)),
                    "objects_mean": finite_or_none(pd.to_numeric(df.get("objects", pd.Series(dtype=float)), errors="coerce").mean()),
                    "streams": int(pd.to_numeric(df.get("stream_id", pd.Series(dtype=float)), errors="coerce").nunique()),
                }
            )
            sample = df.head(120)[[column for column in ("stream_id", "frame_id", "egress_timestamp_ms", "e2e_latency_ms", "objects") if column in df.columns]]
            for row in rows_for_json(sample):
                row["path"] = str(path.relative_to(run_dir))
                frame_samples.append(row)

        stage_stats: list[dict[str, Any]] = []
        for path in event_files[:20]:
            df = pd.read_csv(path, nrows=MAX_DETAIL_ROWS)
            if df.empty or "stage" not in df:
                continue
            df["stage_duration_ms"] = (
                pd.to_numeric(df["stage_end_timestamp_ms"], errors="coerce")
                - pd.to_numeric(df["stage_start_timestamp_ms"], errors="coerce")
            )
            grouped = (
                df.groupby(["stage", "role", "resource"], as_index=False, dropna=False)
                .agg(
                    events=("trace_id", "count"),
                    duration_ms_mean=("stage_duration_ms", "mean"),
                    duration_ms_p95=("stage_duration_ms", lambda value: value.quantile(0.95)),
                    queue_depth_mean=("queue_depth", "mean"),
                )
            )
            for row in rows_for_json(grouped):
                row["path"] = str(path.relative_to(run_dir))
                stage_stats.append(row)

        metric_series: list[dict[str, Any]] = []
        metric_stats: list[dict[str, Any]] = []
        for path in system_metric_files[:20]:
            df = pd.read_csv(path, nrows=MAX_DETAIL_ROWS)
            if df.empty:
                continue
            stats = {"path": str(path.relative_to(run_dir)), "rows_sampled": int(df.shape[0])}
            for column in ("cpu_total_percent", "gpu_util_percent", "gpu_memory_mb", "gpu_power_w", "cpu_memory_mb", "cpu_power_w"):
                if column in df:
                    values = pd.to_numeric(df[column], errors="coerce")
                    stats[f"{column}_mean"] = finite_or_none(values.mean())
                    stats[f"{column}_max"] = finite_or_none(values.max())
            metric_stats.append(stats)
            step = max(1, int(len(df) / 300))
            sample = df.iloc[::step][[column for column in ("timestamp_ms", "cpu_total_percent", "gpu_util_percent", "gpu_memory_mb", "gpu_power_w", "cpu_memory_mb") if column in df.columns]]
            for row in rows_for_json(sample):
                row["path"] = str(path.relative_to(run_dir))
                metric_series.append(row)

        network_rows: list[dict[str, Any]] = []
        for path in network_files[:20]:
            df = pd.read_csv(path, nrows=MAX_DETAIL_ROWS)
            for row in rows_for_json(df):
                row["path"] = str(path.relative_to(run_dir))
                network_rows.append(row)

        metadata = []
        for path in metadata_files[:50]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            metadata.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "mode": raw.get("mode"),
                    "policy": raw.get("policy"),
                    "deployment_mode": raw.get("deployment_mode"),
                    "host_topology": raw.get("host_topology"),
                    "detected_hardware": raw.get("detected_hardware", {}),
                    "result": raw.get("result", {}),
                }
            )

        return {
            "run_id": run_id,
            "run_path": str(run_dir),
            "summary_rows": summary_rows,
            "files": {
                "frames": len(frame_files),
                "frame_events": len(event_files),
                "system_metrics": len(system_metric_files),
                "network_metrics": len(network_files),
                "metadata": len(metadata_files),
            },
            "frames": {"stats": frames_stats, "samples": frame_samples[:1000]},
            "stage_stats": stage_stats,
            "system_metrics": {"stats": metric_stats, "series": metric_series[:3000]},
            "network_metrics": network_rows[:3000],
            "metadata": metadata,
        }


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(app: VastGuiApp) -> type[BaseHTTPRequestHandler]:
    class VastRequestHandler(BaseHTTPRequestHandler):
        server_version = "VASTGUI/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("[vast-gui] " + fmt % args + "\n")

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise GuiError(f"invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise GuiError("request body must be a JSON object")
            return payload

        def send_json(self, status: int, payload: dict[str, Any]) -> None:
            json_response(self, status, payload)

        def handle_error(self, exc: Exception) -> None:
            if isinstance(exc, GuiError):
                self.send_json(exc.status, {"ok": False, "error": str(exc)})
            elif isinstance(exc, ContractError):
                self.send_json(400, {"ok": False, "error": str(exc)})
            else:
                self.send_json(500, {"ok": False, "error": str(exc)})

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/api/config":
                    self.send_json(200, app.load_all_configs())
                elif path == "/api/runs":
                    self.send_json(200, {"jobs": [job.to_json() for job in app.jobs.list()]})
                elif path.startswith("/api/runs/"):
                    job_id = unquote(path.removeprefix("/api/runs/"))
                    self.send_json(200, app.jobs.get(job_id).to_json(include_logs=True))
                elif path == "/api/analytics":
                    self.send_json(200, app.analytics())
                elif path.startswith("/api/analytics/"):
                    run_id = unquote(path.removeprefix("/api/analytics/"))
                    self.send_json(200, app.analytics_detail(run_id))
                elif path.startswith("/api/"):
                    raise GuiError(f"unknown endpoint: {path}", status=404)
                else:
                    self.serve_static(path)
            except Exception as exc:
                self.handle_error(exc)

        def do_POST(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                payload = self.read_json()
                if path == "/api/validate":
                    self.send_json(200, app.validate_current(payload))
                elif path == "/api/runs/dry-run":
                    self.send_json(200, app.dry_run(payload))
                elif path == "/api/runs":
                    self.send_json(201, app.start_run(payload))
                elif path.startswith("/api/runs/") and path.endswith("/stop"):
                    job_id = unquote(path.removeprefix("/api/runs/").removesuffix("/stop").strip("/"))
                    self.send_json(200, app.jobs.stop(job_id).to_json(include_logs=True))
                elif path == "/api/tools/preview":
                    self.send_json(200, app.preview_tool(payload))
                elif path == "/api/tools":
                    self.send_json(201, app.start_tool(payload))
                else:
                    raise GuiError(f"unknown endpoint: {path}", status=404)
            except Exception as exc:
                self.handle_error(exc)

        def do_PUT(self) -> None:
            try:
                path = urlparse(self.path).path
                if not path.startswith("/api/config/"):
                    raise GuiError(f"unknown endpoint: {path}", status=404)
                kind = unquote(path.removeprefix("/api/config/"))
                self.send_json(200, app.save_config(kind, self.read_json()))
            except Exception as exc:
                self.handle_error(exc)

        def serve_static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            static_path = (app.web_root / rel).resolve()
            try:
                static_path.relative_to(app.web_root.resolve())
            except ValueError as exc:
                raise GuiError("invalid static path", status=404) from exc
            if not static_path.exists() or not static_path.is_file():
                raise GuiError(f"static file not found: {rel}", status=404)
            content_type = mimetypes.guess_type(str(static_path))[0] or "application/octet-stream"
            data = static_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

    return VastRequestHandler


def serve(host: str, port: int, project_root: Path) -> None:
    app = VastGuiApp(project_root)
    handler = make_handler(app)
    server = ThreadingHTTPServer((host, port), handler)

    def shutdown(signum: int, _frame: Any) -> None:
        print(f"\n[vast-gui] received signal {signum}; stopping")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print(f"[vast-gui] serving {project_root} at http://{host}:{server.server_port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the local VAST web workbench")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    serve(args.host, args.port, args.project_root.resolve())


if __name__ == "__main__":
    main()
