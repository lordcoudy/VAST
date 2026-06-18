#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from benchmark_contract import FRAME_EVENT_COLUMNS, NETWORK_COLUMNS, network_profile_matches


ROLE_START_ORDER = {"aggregator": 0, "gpu_worker": 1, "edge": 2}


@dataclass
class DistributedResult:
    exit_code: int
    skipped: bool = False
    skip_reason: str = ""
    max_clock_offset_ms: float = 0.0


def load_hosts_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"hosts": []}
    import yaml

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"hosts": []}


def _host_label(host: dict[str, Any]) -> str:
    user = str(host.get("user", "")).strip()
    address = str(host.get("address", "")).strip()
    if not address:
        raise ValueError(f"host entry is missing address: {host}")
    return f"{user}@{address}" if user else address


def _ssh_base(host: dict[str, Any]) -> list[str]:
    cmd = ["ssh"]
    port = host.get("port")
    if port:
        cmd.extend(["-p", str(port)])
    cmd.append(_host_label(host))
    return cmd


def _scp_base(host: dict[str, Any]) -> list[str]:
    cmd = ["scp"]
    port = host.get("port")
    if port:
        cmd.extend(["-P", str(port)])
    return cmd


def _role_hosts(hosts_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    role_map: dict[str, dict[str, Any]] = {}
    for host in hosts_config.get("hosts", []):
        for role in host.get("roles", []):
            role_map.setdefault(str(role), host)
    return role_map


def _host_identity(host: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(host.get("user", "")).strip(),
        str(host.get("address", "")).strip(),
        str(host.get("port", "")).strip(),
    )


def _same_host_topology(role_map: dict[str, dict[str, Any]]) -> bool:
    rtp_roles = [role for role in ("edge", "gpu_worker", "aggregator") if role in role_map]
    if len(rtp_roles) < 2:
        return False
    identities = {_host_identity(role_map[role]) for role in rtp_roles}
    return len(identities) == 1


def _required_roles(scenario: dict[str, Any]) -> list[str]:
    roles = {str(role) for role in scenario.get("placement", {}).get("stages", {}).values()}
    return sorted(roles, key=lambda role: (ROLE_START_ORDER.get(role, 99), role))


def _role_pipeline_stages(scenario: dict[str, Any], role: str) -> list[str]:
    stages = scenario.get("placement", {}).get("stages", {})
    return [stage for stage, stage_role in stages.items() if str(stage_role) == role]


def _remote_output_dir(host: dict[str, Any], run_relpath: str, role: str) -> PurePosixPath:
    return PurePosixPath(str(host["project_path"])) / run_relpath / "roles" / role


def _advertise_address(host: dict[str, Any]) -> str:
    transport = host.get("transport", {}) or {}
    return str(transport.get("advertise_address") or host.get("address") or "")


def _transport_env(role_map: dict[str, dict[str, Any]], role: str, transport: dict[str, Any]) -> dict[str, str]:
    ports = transport.get("role_ports", {}) or {}
    edge_port = int(ports.get("edge_to_gpu_worker", 5600))
    agg_port = int(ports.get("gpu_worker_to_aggregator", 5700))
    env = {
        "EXPERIMENT_TRANSPORT": str(transport.get("kind", "gstreamer_rtp_udp")),
        "EXPERIMENT_TRACE_METADATA": str(transport.get("trace_metadata", "rtp_header_extension")),
        "EXPERIMENT_RTP_PORT_STRIDE": str(int(transport.get("stream_port_stride", 1))),
    }
    if role == "edge":
        env.update(
            {
                "EXPERIMENT_RTP_OUTPUT_HOST": _advertise_address(role_map["gpu_worker"]),
                "EXPERIMENT_RTP_OUTPUT_PORT": str(edge_port),
            }
        )
    elif role == "gpu_worker":
        env.update(
            {
                "EXPERIMENT_RTP_INPUT_PORT": str(edge_port),
                "EXPERIMENT_RTP_OUTPUT_HOST": _advertise_address(role_map["aggregator"]),
                "EXPERIMENT_RTP_OUTPUT_PORT": str(agg_port),
            }
        )
    elif role == "aggregator":
        env["EXPERIMENT_RTP_INPUT_PORT"] = str(agg_port)
    return env


def build_distributed_plan(
    *,
    hosts_config: dict[str, Any],
    scenario: dict[str, Any],
    system_key: str,
    command_template: str,
    run_relpath: str,
    duration_s: int,
    streams: int,
    min_objects: int,
    max_objects: int,
    transport: dict[str, Any] | None = None,
    mode: str = "smoke",
    policy: str = "static_hybrid",
    dataset_name: str = "smoke_testsrc",
    run_id: str = "plan",
    detector: str = "",
    backend: str = "",
    extra_env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    role_map = _role_hosts(hosts_config)
    required_roles = _required_roles(scenario)
    transport = transport or {}
    for required in required_roles:
        if required not in role_map:
            raise ValueError(f"no host with role '{required}' in hosts config")
    if any(role in required_roles for role in ("edge", "gpu_worker", "aggregator")):
        for required in ("edge", "gpu_worker", "aggregator"):
            if required not in role_map:
                raise ValueError(f"RTP distributed runs require host role '{required}'")

    steps: list[dict[str, Any]] = []
    for role in required_roles:
        host = role_map[role]
        if "project_path" not in host:
            raise ValueError(f"host for role '{role}' is missing project_path")
        remote_output = _remote_output_dir(host, run_relpath, role)
        remote_project = PurePosixPath(str(host["project_path"]))
        role_stages = ",".join(_role_pipeline_stages(scenario, role))
        role_command = command_template.format(
            scenario=scenario["name"],
            duration_s=duration_s,
            streams=streams,
            min_objects=min_objects,
            max_objects=max_objects,
            output_dir=str(remote_output),
        )
        env = {
            "BENCHMARK_MODE": mode,
            "DATASET_NAME": dataset_name,
            "SCHEDULER_POLICY": policy,
            "ADAPTER_DETECTOR": detector,
            "ADAPTER_BACKEND": backend,
            "EXPERIMENT_RUN_ID": run_id,
            "EXPERIMENT_DISTRIBUTED": "1",
            "EXPERIMENT_HOST_ROLE": role,
            "EXPERIMENT_PIPELINE_STAGES": role_stages,
            "EXPERIMENT_SCENARIO_JSON": json.dumps(scenario, separators=(",", ":")),
            "MIN_OBJECTS": str(min_objects),
            "MAX_OBJECTS": str(max_objects),
        }
        env.update({str(k): str(v) for k, v in (extra_env or {}).items()})
        env["EXPERIMENT_DISTRIBUTED"] = "1"
        env["EXPERIMENT_HOST_ROLE"] = role
        env["EXPERIMENT_PIPELINE_STAGES"] = role_stages
        env.update(_transport_env(role_map, role, transport))
        env.update({str(k): str(v) for k, v in (host.get("env", {}) or {}).items()})
        env_prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in env.items())
        exit_file = remote_output / "exit_code"
        pid_file = remote_output / "pid"
        metrics_pid_file = remote_output / "metrics_pid"
        ready_file = remote_output / "ready"
        stdout_file = remote_output / "stdout.log"
        stderr_file = remote_output / "stderr.log"
        remote_command = (
            f"mkdir -p {shlex.quote(str(remote_output))} && "
            f"cd {shlex.quote(str(remote_project))} && "
            f"rm -f {shlex.quote(str(exit_file))} {shlex.quote(str(ready_file))} && "
            "{ "
            f"(METRICS_PY=.venv/bin/python; test -x \"$METRICS_PY\" || METRICS_PY=python3; "
            f"$METRICS_PY scripts/collect_metrics.py --output {shlex.quote(str(remote_output / 'system_metrics.csv'))} "
            f"--interval 1 >/dev/null 2>&1 & echo $! > {shlex.quote(str(metrics_pid_file))}; "
            f"{env_prefix} {role_command} > {shlex.quote(str(stdout_file))} "
            f"2> {shlex.quote(str(stderr_file))}; rc=$?; "
            f"kill $(cat {shlex.quote(str(metrics_pid_file))}) >/dev/null 2>&1 || true; "
            f"echo $rc > {shlex.quote(str(exit_file))}) & "
            f"echo $! > {shlex.quote(str(pid_file))} && touch {shlex.quote(str(ready_file))}; "
            "}"
        )
        steps.append(
            {
                "role": role,
                "host": host,
                "host_label": _host_label(host),
                "pipeline_stages": role_stages,
                "remote_output_dir": str(remote_output),
                "remote_command": remote_command,
                "ssh_command": _ssh_base(host) + [remote_command],
                "exit_file": str(exit_file),
                "pid_file": str(pid_file),
                "metrics_pid_file": str(metrics_pid_file),
                "ready_file": str(ready_file),
            }
        )
    return sorted(steps, key=lambda step: (ROLE_START_ORDER.get(step["role"], 99), step["role"]))


def print_distributed_plan(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        print(f"[plan] role={step['role']} host={step['host_label']} stages={step['pipeline_stages'] or '<none>'}")
        print(f"[plan] command={step['remote_command']}")


def parse_ping_output(output: str) -> dict[str, float]:
    loss_match = re.search(r"([\d.]+)% packet loss", output)
    rtt_match = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", output)
    if not loss_match or not rtt_match:
        raise ValueError("unable to parse ping output")
    return {
        "latency_ms": float(rtt_match.group(2)),
        "jitter_ms": float(rtt_match.group(4)),
        "packet_loss_percent": float(loss_match.group(1)),
    }


def parse_iperf_output(output: str) -> float:
    payload = json.loads(output)
    end = payload.get("end", {})
    summary = end.get("sum_received") or end.get("sum") or end.get("sum_sent") or {}
    return float(summary.get("bits_per_second", 0.0)) / 1_000_000.0


def parse_chrony_tracking(output: str) -> float:
    match = re.search(r"Last offset\s*:\s*([+-]?[\d.eE+-]+)\s+seconds", output)
    if not match:
        raise ValueError("unable to parse chronyc tracking output")
    return abs(float(match.group(1))) * 1000.0


def _remote_capture(host: dict[str, Any], command: str, *, check: bool = True) -> str:
    completed = subprocess.run(_ssh_base(host) + [command], check=check, text=True, capture_output=True)
    return completed.stdout


def write_same_host_network_metrics(network_csv: Path) -> None:
    rows = []
    for source_role, target_role in (("edge", "gpu_worker"), ("gpu_worker", "aggregator")):
        rows.append(
            {
                "timestamp_ms": int(time.time() * 1000),
                "source_role": source_role,
                "target_role": target_role,
                "latency_ms": 0.0,
                "jitter_ms": 0.0,
                "packet_loss_percent": 0.0,
                "bandwidth_mbps": 0.0,
                "clock_offset_ms": 0.0,
                "status": "same_host_loopback",
            }
        )
    network_csv.parent.mkdir(parents=True, exist_ok=True)
    with network_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NETWORK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run_network_preflight(
    *,
    hosts_config: dict[str, Any],
    network_csv: Path,
    network_profile: dict[str, Any],
    max_clock_offset_ms: float,
) -> DistributedResult:
    role_map = _role_hosts(hosts_config)
    pairs = [("edge", "gpu_worker"), ("gpu_worker", "aggregator")]
    rows: list[dict[str, Any]] = []
    max_offset = 0.0
    if _same_host_topology(role_map):
        write_same_host_network_metrics(network_csv)
        return DistributedResult(0, max_clock_offset_ms=0.0)

    for role, host in role_map.items():
        try:
            offset = parse_chrony_tracking(_remote_capture(host, "chronyc tracking"))
        except Exception as exc:
            return DistributedResult(2, skipped=True, skip_reason=f"chrony preflight failed for {role}: {exc}")
        max_offset = max(max_offset, offset)
    if max_offset > float(max_clock_offset_ms):
        return DistributedResult(
            2,
            skipped=True,
            skip_reason=f"clock offset {max_offset:.3f}ms exceeds {max_clock_offset_ms:.3f}ms",
            max_clock_offset_ms=max_offset,
        )

    for source_role, target_role in pairs:
        source = role_map[source_role]
        target = role_map[target_role]
        target_address = _advertise_address(target)
        try:
            measured = parse_ping_output(_remote_capture(source, f"ping -c 4 -q {shlex.quote(target_address)}"))
        except Exception as exc:
            return DistributedResult(2, skipped=True, skip_reason=f"ping preflight failed for {source_role}->{target_role}: {exc}")
        try:
            _remote_capture(target, "iperf3 -s -1 -D", check=False)
            bandwidth = parse_iperf_output(
                _remote_capture(source, f"iperf3 -c {shlex.quote(target_address)} -J -t 2", check=False)
            )
        except Exception:
            bandwidth = 0.0
        measured["bandwidth_mbps"] = bandwidth
        rows.append(
            {
                "timestamp_ms": int(time.time() * 1000),
                "source_role": source_role,
                "target_role": target_role,
                **measured,
                "clock_offset_ms": max_offset,
                "status": "measured",
            }
        )

    network_csv.parent.mkdir(parents=True, exist_ok=True)
    with network_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=NETWORK_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    acceptance = network_profile.get("acceptance") or {}
    if acceptance:
        aggregate = {
            "latency_ms": max(float(row["latency_ms"]) for row in rows),
            "jitter_ms": max(float(row["jitter_ms"]) for row in rows),
            "packet_loss_percent": max(float(row["packet_loss_percent"]) for row in rows),
            "bandwidth_mbps": min(float(row["bandwidth_mbps"]) for row in rows),
        }
        accepted, reason = network_profile_matches(aggregate, acceptance)
        if not accepted:
            return DistributedResult(0, skipped=True, skip_reason=f"network acceptance gate: {reason}", max_clock_offset_ms=max_offset)
    return DistributedResult(0, max_clock_offset_ms=max_offset)


def _sync_project(host: dict[str, Any], project_root: Path) -> None:
    if shutil.which("rsync") is None:
        raise RuntimeError("rsync is required for distributed project sync")
    remote = f"{_host_label(host)}:{str(host['project_path']).rstrip('/')}/"
    subprocess.run(
        [
            "rsync",
            "-az",
            "--exclude",
            ".git",
            "--exclude",
            ".venv",
            "--exclude",
            "__pycache__",
            "--exclude",
            "build",
            "--exclude",
            "runs",
            "--exclude",
            "reports",
            f"{project_root}/",
            remote,
        ],
        check=True,
    )


def _collect_role_outputs(step: dict[str, Any], local_role_dir: Path) -> None:
    local_role_dir.mkdir(parents=True, exist_ok=True)
    remote = f"{_host_label(step['host'])}:{step['remote_output_dir'].rstrip('/')}/"
    subprocess.run(_scp_base(step["host"]) + ["-r", remote, str(local_role_dir)], check=False)


def _first_csv(role_dir: Path, name: str) -> Path | None:
    return next(role_dir.rglob(name), None)


def _csvs(role_dir: Path, pattern: str) -> list[Path]:
    return sorted(role_dir.rglob(pattern))


def _combine_csv(paths: list[Path], output_csv: Path, fieldnames: list[str]) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for path in paths:
            with path.open("r", newline="", encoding="utf-8") as in_f:
                for row in csv.DictReader(in_f):
                    writer.writerow(row)


def _stop_remote(step: dict[str, Any]) -> None:
    command = (
        f"test -f {shlex.quote(step['pid_file'])} && kill $(cat {shlex.quote(step['pid_file'])}) >/dev/null 2>&1 || true; "
        f"test -f {shlex.quote(step['metrics_pid_file'])} && kill $(cat {shlex.quote(step['metrics_pid_file'])}) >/dev/null 2>&1 || true"
    )
    subprocess.run(_ssh_base(step["host"]) + [command], check=False)


def run_distributed(
    *,
    steps: list[dict[str, Any]],
    project_root: Path,
    local_run_dir: Path,
    frames_csv: Path,
    frame_events_csv: Path,
    network_csv: Path,
    hosts_config: dict[str, Any],
    network_profile: dict[str, Any],
    max_clock_offset_ms: float,
    sync_project: bool,
    duration_s: int,
    startup_grace_s: int,
    mode: str,
) -> DistributedResult:
    role_map = _role_hosts(hosts_config)
    same_host = _same_host_topology(role_map)
    preflight = run_network_preflight(
        hosts_config=hosts_config,
        network_csv=network_csv,
        network_profile=network_profile,
        max_clock_offset_ms=max_clock_offset_ms,
    )
    if preflight.skipped:
        return preflight

    seen_hosts: set[str] = set()
    if sync_project:
        for step in steps:
            if step["host_label"] not in seen_hosts:
                _sync_project(step["host"], project_root)
                seen_hosts.add(step["host_label"])

    launched: list[dict[str, Any]] = []
    try:
        for step in steps:
            subprocess.run(step["ssh_command"], check=True)
            launched.append(step)
            time.sleep(max(0, startup_grace_s))
        deadline = time.monotonic() + duration_s + startup_grace_s + 60
        exit_code = 0
        for step in reversed(steps):
            while time.monotonic() < deadline:
                output = _remote_capture(step["host"], f"cat {shlex.quote(step['exit_file'])}", check=False).strip()
                if output:
                    exit_code = exit_code or int(output)
                    break
                time.sleep(1)
            else:
                raise RuntimeError(f"distributed role timed out: {step['role']}")
    finally:
        for step in launched:
            _stop_remote(step)

    role_dirs: dict[str, Path] = {}
    for step in steps:
        if same_host:
            role_dir = Path(step["remote_output_dir"])
        else:
            role_dir = local_run_dir / "roles" / step["role"]
            _collect_role_outputs(step, role_dir)
        role_dirs[step["role"]] = role_dir

    aggregator_frames = _first_csv(role_dirs["aggregator"], "frames.csv")
    if aggregator_frames is None:
        raise RuntimeError("aggregator did not produce E2E frames.csv")
    shutil.copyfile(aggregator_frames, frames_csv)
    event_paths = [path for role_dir in role_dirs.values() for path in _csvs(role_dir, "frame_events*.csv")]
    if mode == "benchmark":
        missing_events = [role for role, role_dir in role_dirs.items() if not _csvs(role_dir, "frame_events*.csv")]
        missing_metrics = [role for role, role_dir in role_dirs.items() if _first_csv(role_dir, "system_metrics.csv") is None]
        if missing_events:
            raise RuntimeError(f"distributed roles did not produce frame_events.csv: {', '.join(missing_events)}")
        if missing_metrics:
            raise RuntimeError(f"distributed roles did not produce system_metrics.csv: {', '.join(missing_metrics)}")
    if event_paths:
        _combine_csv(event_paths, frame_events_csv, FRAME_EVENT_COLUMNS)
    return DistributedResult(exit_code, max_clock_offset_ms=preflight.max_clock_offset_ms)
