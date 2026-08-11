#!/usr/bin/env python3
from __future__ import annotations

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
        if system_key != "gstreamer_custom":
            raise ContractError(
                f"scenario '{scenario_name}' publication runtime is implemented only for gstreamer_custom"
            )
        expected_kind = (
            "independent_processes"
            if scenario_name == "checkpoint_independent_processes_baseline"
            else "shared_video_dag"
        )
        if int(topology.get("contract_version", 0) or 0) != 1:
            raise ContractError(f"scenario '{scenario_name}' must declare topology contract version 1")
        if str(topology.get("kind", "")) != expected_kind:
            raise ContractError(f"scenario '{scenario_name}' must declare topology kind '{expected_kind}'")
        routing_mode = str(topology.get("routing_mode", ""))
        if routing_mode != "all_branches_per_stream":
            raise ContractError(
                f"scenario '{scenario_name}' must resolve routing_mode=all_branches_per_stream "
                "before topology contract v1 can be enabled"
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
        runner="scripts/run_system_template.sh",
        contract=(
            "strict_native_schema_v2_topology_v1"
            if int(topology.get("contract_version", 0) or 0) == 1
            else "strict_native_schema_v2"
        ),
        scenario=scenario_name,
        distributed=distributed,
        topology_contract_version=int(topology.get("contract_version", 0) or 0),
        topology_kind=str(topology.get("kind", "")),
    )
