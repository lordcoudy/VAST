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
    "custom_cpp_cuda_qt",
}
RTP_ROLES = {"edge", "gpu_worker", "aggregator"}


@dataclass(frozen=True)
class BenchmarkAdapterPlan:
    system: str
    runner: str
    contract: str
    scenario: str
    distributed: bool

    def metadata(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "contract": self.contract,
            "scenario": self.scenario,
            "distributed": self.distributed,
        }


def scenario_benchmark_status(name: str, raw: dict[str, Any]) -> str:
    explicit = raw.get("benchmark_status")
    if explicit is not None:
        return str(explicit)
    benchmark = raw.get("benchmark")
    if isinstance(benchmark, dict) and "status" in benchmark:
        return str(benchmark["status"])
    return "supported"


def select_scenarios(
    config: dict[str, Any],
    requested: list[str],
    *,
    mode: str,
    run_kind: str = "auto",
) -> list[str]:
    if requested != ["all"]:
        return requested
    scenarios = list(config["scenarios"].keys())
    if mode != "benchmark" or run_kind == "auto":
        return scenarios
    distributed = run_kind in {"single-server-distributed", "distributed"}
    return [
        name
        for name, raw in config["scenarios"].items()
        if bool((raw.get("distributed") or {}).get("enabled")) == distributed
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
    if system_key not in STRICT_BENCHMARK_SYSTEMS:
        raise ContractError(f"system '{system_key}' has no strict native benchmark adapter")

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
        contract="strict_native_schema_v2",
        scenario=scenario_name,
        distributed=distributed,
    )
