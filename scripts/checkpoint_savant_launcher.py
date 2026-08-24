#!/usr/bin/env python3
"""Topology-exact Savant checkpoint launcher (engineering-only).

Maps the immutable Savant plan onto the existing POSIX FD coordinator.  The
launcher neither invents module evidence nor promotes the unbuilt runtime:
generated module configs, SDK binding, resource-v2 evidence and KPP pilots
remain explicit readiness blockers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from checkpoint_savant_runtime import (
    ANALYTICS_BRANCHES,
    RUNTIME_EXECUTABLE,
    validate_savant_runtime_plan,
)


INDEPENDENT_PROCESSES = "independent_processes"
SHARED_VIDEO_DAG = "shared_video_dag"
BRIDGE_CLASS = "checkpoint_savant_protocol_bridge:SavantProtocolBridge"
DESCRIPTOR_CLAIM_STATUS = "engineering_savant_module_descriptor_nonpublication"
_FD_CONTRACT = {
    "admission": "VAST_CHECKPOINT_ADMISSION_DATA_FD",
    "control": "VAST_CHECKPOINT_CONTROL_FD",
    "event": "VAST_CHECKPOINT_EVENT_FD",
    "policy": "VAST_CHECKPOINT_POLICY_FD",
    "status": "VAST_CHECKPOINT_STATUS_FD",
}


class SavantLauncherError(RuntimeError):
    """A frozen Savant process could not be mapped without relabeling."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantLauncherError(message)


def _text(value: Any, label: str) -> str:
    result = str(value)
    _require(bool(result) and "\x00" not in result, f"{label} is empty or invalid")
    return result


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SavantLauncherError("Savant descriptor is not canonical JSON") from exc


@dataclass(frozen=True)
class SavantWorkerLaunchSpec:
    worker_id: str
    stream_id: int
    branch_id: str | None
    command: tuple[str, ...]
    environment: dict[str, str] = field(default_factory=dict)
    native_event_source: bool = True


def _process_rows(plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    validate_savant_runtime_plan(plan)
    rows = plan.get("processes")
    _require(isinstance(rows, list), "Savant process list is missing")
    _require(all(isinstance(row, Mapping) for row in rows), "invalid Savant process row")
    return tuple(rows)


def _source_by_stream(plan: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    sources = plan.get("sources")
    _require(isinstance(sources, list), "Savant sources are missing")
    result: dict[int, Mapping[str, Any]] = {}
    for source in sources:
        _require(isinstance(source, Mapping), "invalid Savant source")
        stream_id = int(source.get("stream_id", -1))
        _require(0 <= stream_id < 6 and stream_id not in result, "Savant source stream drifted")
        result[stream_id] = source
    _require(set(result) == set(range(6)), "Savant sources do not cover six streams")
    return result


def build_savant_module_descriptor(
    plan: Mapping[str, Any],
    process: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a hash-bound descriptor for one exact frozen process row."""

    rows = _process_rows(plan)
    process_id = _text(process.get("process_id", ""), "Savant process_id")
    matching = [row for row in rows if row.get("process_id") == process_id]
    _require(len(matching) == 1 and dict(matching[0]) == dict(process),
             "Savant process is not an exact frozen plan row")
    topology = _text(plan.get("topology_kind", ""), "Savant topology")
    stream_id = int(process.get("stream_id", -1))
    _require(0 <= stream_id < 6, "Savant stream_id is invalid")
    branches = tuple(str(value) for value in process.get("branches") or ())
    if topology == INDEPENDENT_PROCESSES:
        _require(
            len(branches) == 1
            and process.get("branch") == branches[0]
            and branches[0] in ANALYTICS_BRANCHES,
            "baseline Savant process is not branch-isolated",
        )
        physical = {"physical_pipeline": process.get("physical_pipeline")}
    elif topology == SHARED_VIDEO_DAG:
        _require(branches == ANALYTICS_BRANCHES, "shared Savant branch order drifted")
        physical = {
            "shared_prefix": process.get("shared_prefix"),
            "routes": process.get("routes"),
        }
    else:
        raise SavantLauncherError("unsupported Savant topology")
    module_config = _text(process.get("module_config_path", ""), "Savant module config")
    _require(
        module_config.startswith("/opt/vast/checkpoint/generated/")
        and process.get("module_config_status") == "missing_not_built",
        "generic or promoted Savant module config is prohibited",
    )
    source = _source_by_stream(plan)[stream_id]
    descriptor: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "savant_checkpoint_module_descriptor",
        "claim_status": DESCRIPTOR_CLAIM_STATUS,
        "system": "savant",
        "module_id": process_id,
        "topology_kind": topology,
        "stream_id": stream_id,
        "branches": list(branches),
        "source_process_id": _text(process.get("source_process_id", ""), "source process_id"),
        "source_sha256": _text(source.get("source_sha256", ""), "source SHA-256"),
        "codec": _text(plan.get("codec", ""), "Savant codec"),
        "dataset": _text(plan.get("dataset", ""), "Savant dataset"),
        "policy": _text(plan.get("policy", ""), "Savant policy"),
        "deadline_ms": float(plan.get("deadline_ms")),
        "module_config_path": module_config,
        "module_config_status": "missing_not_built",
        "bridge_class": BRIDGE_CLASS,
        "inherited_fd_contract": dict(_FD_CONTRACT),
        **physical,
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }
    descriptor["descriptor_sha256"] = hashlib.sha256(
        _canonical_json(descriptor).encode("utf-8")
    ).hexdigest()
    return descriptor


def build_savant_worker_specs(
    plan: Mapping[str, Any],
    *,
    run_id: str,
    arm_id: str,
    runtime_executable: str = RUNTIME_EXECUTABLE,
) -> tuple[SavantWorkerLaunchSpec, ...]:
    """Map an exact plan to 24 baseline or six shared OS processes."""

    normalized_run = _text(run_id, "Savant run_id")
    normalized_arm = _text(arm_id, "Savant arm_id")
    _require(runtime_executable == RUNTIME_EXECUTABLE, "Savant runtime executable drifted")
    rows = _process_rows(plan)
    specs: list[SavantWorkerLaunchSpec] = []
    for process in rows:
        descriptor = build_savant_module_descriptor(plan, process)
        worker_id = str(descriptor["module_id"])
        branches = tuple(str(value) for value in descriptor["branches"])
        branch_id = branches[0] if descriptor["topology_kind"] == INDEPENDENT_PROCESSES else None
        descriptor_json = _canonical_json(descriptor)
        command = (
            runtime_executable,
            "run",
            "--module-config",
            str(descriptor["module_config_path"]),
            "--module-descriptor-sha256",
            str(descriptor["descriptor_sha256"]),
            "--topology-kind",
            str(descriptor["topology_kind"]),
            "--stream-id",
            str(descriptor["stream_id"]),
            "--branches",
            ",".join(branches),
            "--arm-id",
            normalized_arm,
        )
        specs.append(SavantWorkerLaunchSpec(
            worker_id=worker_id,
            stream_id=int(descriptor["stream_id"]),
            branch_id=branch_id,
            command=command,
            environment={
                "VAST_SAVANT_ARM_ID": normalized_arm,
                "VAST_SAVANT_BRANCHES": ",".join(branches),
                "VAST_SAVANT_BRIDGE_CLASS": BRIDGE_CLASS,
                "VAST_SAVANT_CLAIM_STATUS": DESCRIPTOR_CLAIM_STATUS,
                "VAST_SAVANT_CODEC": str(descriptor["codec"]),
                "VAST_SAVANT_DATASET_ID": str(descriptor["dataset"]),
                "VAST_SAVANT_DEADLINE_MS": str(float(descriptor["deadline_ms"])),
                "VAST_SAVANT_MODULE_DESCRIPTOR_JSON": descriptor_json,
                "VAST_SAVANT_MODULE_DESCRIPTOR_SHA256": str(descriptor["descriptor_sha256"]),
                "VAST_SAVANT_MODULE_ID": worker_id,
                "VAST_SAVANT_POLICY": str(descriptor["policy"]),
                "VAST_SAVANT_RUN_ID": normalized_run,
                "VAST_SAVANT_SOURCE_SHA256": str(descriptor["source_sha256"]),
            },
            native_event_source=True,
        ))
    topology = str(plan.get("topology_kind"))
    expected = 24 if topology == INDEPENDENT_PROCESSES else 6
    _require(len(specs) == expected, f"Savant {topology} requires exactly {expected} processes")
    _require(len({spec.worker_id for spec in specs}) == expected, "Savant worker IDs are not unique")
    _require({spec.stream_id for spec in specs} == set(range(6)), "Savant streams drifted")
    return tuple(specs)


def launch_savant_worker_processes(
    *,
    plan: Mapping[str, Any],
    run_id: str,
    arm_id: str,
    source_specs: Iterable[Any],
    policy_socket_handler: Callable[[str, Any], None],
    warmup_s: float,
    measurement_s: float,
    timeout_s: float,
    drain_timeout_s: float = 10.0,
    ready_timeout_s: float = 300.0,
    runner: Callable[..., Any] | None = None,
) -> Any:
    """Delegate exact physical specs to the established POSIX coordinator."""

    _require(warmup_s >= 0 and measurement_s > 0, "Savant lifecycle window is invalid")
    _require(drain_timeout_s > 0 and ready_timeout_s > 0, "Savant lifecycle timeout is invalid")
    _require(timeout_s > warmup_s + measurement_s, "Savant timeout is too short")
    _require(callable(policy_socket_handler), "Savant native policy handler is missing")
    specs = build_savant_worker_specs(plan, run_id=run_id, arm_id=arm_id)
    if runner is None:
        from checkpoint_runtime import run_worker_processes as runner
    return runner(
        run_id=run_id,
        topology_kind=str(plan["topology_kind"]),
        branches=ANALYTICS_BRANCHES,
        specs=specs,
        source_specs=tuple(source_specs),
        timeout_s=timeout_s,
        ready_timeout_s=ready_timeout_s,
        synchronized_lifecycle=True,
        warmup_s=warmup_s,
        measurement_s=measurement_s,
        drain_timeout_s=drain_timeout_s,
        require_decoder_placement_verification=True,
        policy_socket_handler=policy_socket_handler,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Savant physical worker launcher")
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--arm-id", required=True)
    args = parser.parse_args(argv)
    _require(args.manifest in {None, "manifest"}, "only manifest is supported")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    specs = build_savant_worker_specs(plan, run_id=args.run_id, arm_id=args.arm_id)
    output = {
        "schema_version": 1,
        "artifact_kind": "savant_checkpoint_worker_launch_manifest",
        "claim_status": "launch_manifest_not_measurement",
        "physical_process_count": len(specs),
        "specs": [asdict(value) for value in specs],
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }
    print(_canonical_json(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

