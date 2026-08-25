#!/usr/bin/env python3
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from benchmark_contract import ContractError


STRICT_BENCHMARK_SYSTEMS = {
    "deepstream",
    "savant",
    "openvino_gva",
    "gstreamer_custom",
}
DIAGNOSTIC_ONLY_SYSTEMS = {
    "custom_cpp_cuda_qt": (
        "the current adapter generates an internal signal workload and does not consume the configured video dataset"
    ),
}
RTP_ROLES = {"edge", "gpu_worker", "aggregator"}
CHECKPOINT_SCENARIOS = frozenset(
    {
        "checkpoint_independent_processes_baseline",
        "checkpoint_video_dag_shared",
    }
)


@dataclass(frozen=True)
class CheckpointBackendCapability:
    system: str
    launcher: str
    topology_runtime_implemented: bool
    publication_ready: bool
    scenarios: tuple[str, ...]
    codecs: tuple[str, ...]
    policies: tuple[str, ...]
    deadlines_ms: tuple[float, ...]
    distributed: bool
    blockers: tuple[str, ...]

    def metadata(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "launcher": self.launcher,
            "topology_runtime_implemented": self.topology_runtime_implemented,
            "publication_ready": self.publication_ready,
            "scenarios": list(self.scenarios),
            "codecs": list(self.codecs),
            "policies": list(self.policies),
            "deadlines_ms": list(self.deadlines_ms),
            "distributed": self.distributed,
            "blockers": list(self.blockers),
        }


def checkpoint_backend_capability(system_key: str) -> CheckpointBackendCapability:
    """Describe only topology-specific checkpoint runtimes that actually exist."""
    if system_key == "gstreamer_custom":
        return CheckpointBackendCapability(
            system=system_key,
            launcher="scripts/checkpoint_gstreamer_runtime.py",
            topology_runtime_implemented=True,
            publication_ready=False,
            scenarios=tuple(sorted(CHECKPOINT_SCENARIOS)),
            codecs=("h264", "h265"),
            policies=("cpu_only",),
            deadlines_ms=(16.7, 33.3, 50.0, 100.0, 500.0),
            distributed=False,
            blockers=(
                "gstreamer_custom cpu_only native path requires exact frozen capability and "
                "calibration artifacts before measurement",
                "gstreamer_custom GPU/mixed policies require saved NVIDIA CUDA/TensorRT parity "
                "bindings with native terminal evidence",
            ),
        )
    if system_key in {"deepstream", "savant", "openvino_gva"}:
        return CheckpointBackendCapability(
            system=system_key,
            launcher="",
            topology_runtime_implemented=False,
            publication_ready=False,
            scenarios=(),
            codecs=(),
            policies=(),
            deadlines_ms=(),
            distributed=False,
            blockers=(
                f"{system_key} has a generic native probe but no topology-specific checkpoint runtime "
                "with protocol-v3 common admission, branch terminals, and native policy/resource binding",
            ),
        )
    return CheckpointBackendCapability(
        system=system_key,
        launcher="",
        topology_runtime_implemented=False,
        publication_ready=False,
        scenarios=(),
        codecs=(),
        policies=(),
        deadlines_ms=(),
        distributed=False,
        blockers=(f"{system_key} has no strict checkpoint runtime capability declaration",),
    )


def checkpoint_runtime_cell_blockers(
    *,
    system: str,
    scenario: str,
    codec: str | None,
    policy: str | None,
    deadline_ms: float | None,
    distributed: bool,
) -> list[str]:
    """Return deterministic blockers for one explicit checkpoint matrix cell."""
    blockers: list[str] = []
    if scenario not in CHECKPOINT_SCENARIOS:
        blockers.append(f"{scenario} is not a checkpoint topology scenario")
    capability = checkpoint_backend_capability(system)
    if system != "gstreamer_custom":
        blockers.extend(capability.blockers)
    if distributed:
        blockers.append(f"{system} checkpoint runtime is local-only; distributed execution is unavailable")

    normalized_codec = str(codec or "").strip().lower().replace("hevc", "h265")
    normalized_policy = str(policy or "").strip()
    if not normalized_codec:
        blockers.append("checkpoint codec is not explicit")
    if not normalized_policy:
        blockers.append("checkpoint policy is not explicit")
    resolved_deadline_ms: float | None = None
    if deadline_ms is None:
        blockers.append("checkpoint deadline_ms is not explicit")
    else:
        try:
            resolved_deadline_ms = float(deadline_ms)
        except (TypeError, ValueError):
            blockers.append("checkpoint deadline_ms must be a finite positive number")
        else:
            if not math.isfinite(resolved_deadline_ms) or resolved_deadline_ms <= 0:
                blockers.append("checkpoint deadline_ms must be a finite positive number")

    if system == "gstreamer_custom":
        if normalized_codec and normalized_codec not in capability.codecs:
            blockers.append(
                "GStreamer checkpoint codec is outside the exact H.264/H.265 publication plans; "
                f"requested {normalized_codec}"
            )
        if (
            resolved_deadline_ms is not None
            and not any(
                math.isclose(resolved_deadline_ms, value, rel_tol=0.0, abs_tol=1e-9)
                for value in capability.deadlines_ms
            )
        ):
            blockers.append(
                "GStreamer checkpoint deadline is outside the exact frozen five-deadline matrix; "
                f"requested {resolved_deadline_ms:g} ms"
            )
        if normalized_policy == "cpu_only":
            blockers.append(
                "gstreamer_custom cpu_only native path requires exact frozen capability and "
                "calibration artifacts before measurement"
            )
        elif normalized_policy:
            if normalized_policy not in {
                "gpu_only",
                "static_hybrid",
                "heft",
                "deadline_aware_heft",
                "queue_aware_edf",
                "adaptive_weights",
            }:
                blockers.append(
                    f"GStreamer checkpoint policy is outside the frozen seven-policy matrix: "
                    f"{normalized_policy}"
                )
            else:
                blockers.append(
                    "gstreamer_custom GPU/mixed policy is blocked until saved NVIDIA "
                    "CUDA/TensorRT parity bindings have native terminal evidence"
                )
    return blockers


@dataclass(frozen=True)
class BenchmarkAdapterPlan:
    system: str
    runner: str
    contract: str
    scenario: str
    distributed: bool
    topology_contract_version: int = 0
    topology_kind: str = ""

    def metadata(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "contract": self.contract,
            "scenario": self.scenario,
            "distributed": self.distributed,
            "topology_contract_version": self.topology_contract_version,
            "topology_kind": self.topology_kind,
        }


def scenario_benchmark_status(name: str, raw: dict[str, Any]) -> str:
    explicit = raw.get("benchmark_status")
    if explicit is not None:
        return str(explicit)
    benchmark = raw.get("benchmark")
    if isinstance(benchmark, dict) and "status" in benchmark:
        return str(benchmark["status"])
    return "supported"


def scenario_benchmark_reason(name: str, raw: dict[str, Any]) -> str:
    explicit = raw.get("benchmark_reason")
    if explicit is not None:
        return str(explicit)
    benchmark = raw.get("benchmark")
    if isinstance(benchmark, dict) and "reason" in benchmark:
        return str(benchmark["reason"])
    return f"scenario '{name}' has not passed the publication topology contract"


def select_scenarios(
    config: dict[str, Any],
    requested: list[str],
    *,
    mode: str,
    run_kind: str = "auto",
) -> list[str]:
    if requested != ["all"]:
        unknown = sorted(set(requested) - set(config["scenarios"]))
        if unknown:
            raise ContractError(f"unknown scenarios: {', '.join(unknown)}")
        if mode == "benchmark":
            blocked = [
                name
                for name in requested
                if scenario_benchmark_status(name, config["scenarios"][name]) != "supported"
            ]
            if blocked:
                reasons = "; ".join(
                    f"{name}: {scenario_benchmark_reason(name, config['scenarios'][name])}"
                    for name in blocked
                )
                raise ContractError(f"non-publishable scenarios cannot run in benchmark mode: {reasons}")
        return requested
    benchmark = config.get("benchmark", {})
    configured = list(config["scenarios"].keys())
    if mode == "benchmark":
        scenario_names = [str(name) for name in (benchmark.get("active_scenarios") or benchmark.get("report_scenarios") or configured)]
    else:
        scenario_names = [str(name) for name in (benchmark.get("smoke_scenarios") or benchmark.get("active_scenarios") or configured)]
    scenario_names = [name for name in scenario_names if name in config["scenarios"]]
    if mode == "benchmark":
        scenario_names = [
            name
            for name in scenario_names
            if scenario_benchmark_status(name, config["scenarios"][name]) == "supported"
        ]
    if mode != "benchmark" or run_kind == "auto":
        return scenario_names
    distributed = run_kind in {"single-server-distributed", "distributed"}
    return [
        name
        for name in scenario_names
        if bool((config["scenarios"][name].get("distributed") or {}).get("enabled")) == distributed
    ]


def validate_benchmark_adapter(
    *,
    system_key: str,
    scenario: dict[str, Any],
    distributed: bool,
    mode: str,
    backend_dispatch: dict[str, Any] | None = None,
) -> BenchmarkAdapterPlan | None:
    if mode != "benchmark":
        return None

    scenario_name = str(scenario.get("name", ""))
    if system_key in DIAGNOSTIC_ONLY_SYSTEMS:
        raise ContractError(
            f"system '{system_key}' is diagnostic-only in benchmark mode: {DIAGNOSTIC_ONLY_SYSTEMS[system_key]}"
        )
    if system_key not in STRICT_BENCHMARK_SYSTEMS:
        raise ContractError(f"system '{system_key}' has no strict native benchmark adapter")

    status = str(scenario.get("benchmark_status", "supported"))
    if status != "supported":
        reason = str(
            scenario.get(
                "benchmark_reason",
                f"scenario '{scenario_name}' has not passed the publication topology contract",
            )
        )
        raise ContractError(
            f"scenario '{scenario_name}' is not publishable in benchmark mode ({status}): {reason}"
        )

    topology = dict(scenario.get("topology") or {})
    if scenario_name in {
        "checkpoint_independent_processes_baseline",
        "checkpoint_video_dag_shared",
    }:
        if backend_dispatch is None:
            capability = checkpoint_backend_capability(system_key)
            if not capability.topology_runtime_implemented:
                raise ContractError(
                    f"scenario '{scenario_name}' publication runtime is not grant-authorized: "
                    f"{capability.blockers[0]}"
                )
        if distributed:
            raise ContractError(
                f"scenario '{scenario_name}' checkpoint runtime is local-only for system '{system_key}'"
            )
        expected_kind = (
            "independent_processes"
            if scenario_name == "checkpoint_independent_processes_baseline"
            else "shared_video_dag"
        )
        if int(topology.get("contract_version", 0) or 0) != 2:
            raise ContractError(f"scenario '{scenario_name}' must declare topology contract version 2")
        if str(topology.get("kind", "")) != expected_kind:
            raise ContractError(f"scenario '{scenario_name}' must declare topology kind '{expected_kind}'")
        routing_mode = str(topology.get("routing_mode", ""))
        if routing_mode != "all_branches_per_stream":
            raise ContractError(
                f"scenario '{scenario_name}' must resolve routing_mode=all_branches_per_stream "
                "before topology contract v2 can be enabled"
            )
        branches = [str(value) for value in topology.get("required_branches", [])]
        if not branches or len(branches) != len(set(branches)):
            raise ContractError(f"scenario '{scenario_name}' must declare unique required topology branches")
        workload = scenario.get("workload") or {}
        if str(workload.get("routing_mode", "")) != routing_mode:
            raise ContractError(f"scenario '{scenario_name}' workload/topology routing_mode values must match")
        if int(workload.get("analytics_function_types", 0) or 0) != len(branches):
            raise ContractError(f"scenario '{scenario_name}' topology branches must match analytics_function_types")
        if int(workload.get("logical_stream_instances", 0) or 0) != int(workload.get("streams", 0) or 0):
            raise ContractError(f"scenario '{scenario_name}' logical_stream_instances must match streams")

    pipeline = [str(stage) for stage in scenario.get("pipeline", [])]
    if not pipeline or len(set(pipeline)) != len(pipeline):
        raise ContractError(f"scenario '{scenario_name}' must define unique strict benchmark stages")
    placements = {str(stage): str(role) for stage, role in (scenario.get("placement", {}).get("stages") or {}).items()}
    missing = [stage for stage in pipeline if stage not in placements]
    if missing:
        raise ContractError(f"scenario '{scenario_name}' placement is missing stages: {', '.join(missing)}")

    if distributed:
        roles = {placements[stage] for stage in pipeline}
        unsupported_roles = sorted(roles - RTP_ROLES)
        if unsupported_roles:
            raise ContractError(
                f"scenario '{scenario_name}' has unsupported distributed roles: {', '.join(unsupported_roles)}"
            )
        missing_roles = sorted(RTP_ROLES - roles)
        if missing_roles:
            raise ContractError(
                f"scenario '{scenario_name}' must assign strict distributed stages to roles: {', '.join(missing_roles)}"
            )
    elif {placements[stage] for stage in pipeline} != {"local"}:
        raise ContractError(f"scenario '{scenario_name}' is not a strict local placement")

    return BenchmarkAdapterPlan(
        system=system_key,
        runner=(
            str((backend_dispatch or {}).get("launcher", {}).get("path", ""))
            if backend_dispatch is not None
            else "scripts/run_system_template.sh"
        ),
        contract=(
            "strict_native_schema_v2_topology_v2"
            if int(topology.get("contract_version", 0) or 0) == 2
            else "strict_native_schema_v2"
        ),
        scenario=scenario_name,
        distributed=distributed,
        topology_contract_version=int(topology.get("contract_version", 0) or 0),
        topology_kind=str(topology.get("kind", "")),
    )
