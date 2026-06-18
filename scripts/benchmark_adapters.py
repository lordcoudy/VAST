#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from benchmark_contract import ContractError


CANONICAL_STAGES = ("decode", "detect", "aggregate")
STRICT_BENCHMARK_SYSTEMS = {
    "deepstream",
    "savant",
    "openvino_gva",
    "gstreamer_custom",
    "custom_cpp_cuda_qt",
}
LOCAL_BENCHMARK_SCENARIOS = {"canonical_heterogeneous"}
DISTRIBUTED_BENCHMARK_SCENARIOS = {"canonical_distributed"}
ROLE_STAGES = {
    "edge": ("decode",),
    "gpu_worker": ("detect",),
    "aggregator": ("aggregate",),
}


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
    if name in LOCAL_BENCHMARK_SCENARIOS | DISTRIBUTED_BENCHMARK_SCENARIOS:
        return "supported"
    return "experimental"


def select_scenarios(
    config: dict[str, Any],
    requested: list[str],
    *,
    mode: str,
    run_kind: str = "auto",
) -> list[str]:
    if requested != ["all"]:
        return requested
    all_scenarios = list(config["scenarios"].keys())
    if mode != "benchmark":
        return all_scenarios
    supported = [
        name
        for name, raw in config["scenarios"].items()
        if scenario_benchmark_status(name, raw) == "supported"
    ]
    if run_kind in {"local", "heterogeneous"}:
        return [name for name in supported if name in LOCAL_BENCHMARK_SCENARIOS]
    if run_kind in {"single-server-distributed", "distributed"}:
        return [name for name in supported if name in DISTRIBUTED_BENCHMARK_SCENARIOS]
    return supported


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

    pipeline = tuple(str(stage) for stage in scenario.get("pipeline", []))
    if pipeline != CANONICAL_STAGES:
        raise ContractError(
            f"scenario '{scenario_name}' has unsupported benchmark pipeline {list(pipeline)}; "
            f"strict native adapters currently support {list(CANONICAL_STAGES)}"
        )

    if distributed:
        if scenario_name not in DISTRIBUTED_BENCHMARK_SCENARIOS:
            raise ContractError(
                f"scenario '{scenario_name}' is not a supported distributed benchmark scenario; "
                f"supported: {', '.join(sorted(DISTRIBUTED_BENCHMARK_SCENARIOS))}"
            )
        stages_by_role: dict[str, list[str]] = {}
        for stage, role in scenario.get("placement", {}).get("stages", {}).items():
            stages_by_role.setdefault(str(role), []).append(str(stage))
        for role, expected in ROLE_STAGES.items():
            actual = tuple(stages_by_role.get(role, []))
            if actual != expected:
                raise ContractError(
                    f"scenario '{scenario_name}' maps role '{role}' to stages {list(actual)}; "
                    f"strict distributed adapters require {list(expected)}"
                )
    else:
        if scenario_name not in LOCAL_BENCHMARK_SCENARIOS:
            raise ContractError(
                f"scenario '{scenario_name}' is not a supported local benchmark scenario; "
                f"supported: {', '.join(sorted(LOCAL_BENCHMARK_SCENARIOS))}"
            )
        placements = {str(role) for role in scenario.get("placement", {}).get("stages", {}).values()}
        if placements != {"local"}:
            raise ContractError(
                f"scenario '{scenario_name}' is not a local benchmark placement: {sorted(placements)}"
            )

    return BenchmarkAdapterPlan(
        system=system_key,
        runner="scripts/run_system_template.sh",
        contract="strict_native_schema_v2",
        scenario=scenario_name,
        distributed=distributed,
    )
