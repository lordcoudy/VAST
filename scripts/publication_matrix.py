#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from benchmark_contract import ContractError


FULL_RESOURCE_PUBLICATION_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"
FULL_MATRIX_SCHEMA_VERSION = 1
FULL_MATRIX_IDENTITY_SCHEMA_VERSION = 1
PUBLISHABLE_SYSTEMS = (
    "deepstream",
    "savant",
    "openvino_gva",
    "gstreamer_custom",
)
CHECKPOINT_SCENARIOS = (
    "checkpoint_independent_processes_baseline",
    "checkpoint_video_dag_shared",
)
DATASET_BY_CODEC = {
    "h264": "kpp_real_h264",
    "h265": "kpp_real_h265",
}
EXPECTED_RESOURCE_COMPONENTS = {
    "transfer",
    "nvdec_submit_complete",
    "fanout",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _slug(value: Any) -> str:
    text = format(float(value), "g") if isinstance(value, float) else str(value)
    return re.sub(r"[^A-Za-z0-9_-]+", "p", text).strip("p") or "value"


def publication_matrix_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": FULL_MATRIX_IDENTITY_SCHEMA_VERSION,
        "sha256": hashlib.sha256(_canonical_json(manifest)).hexdigest(),
    }


def _pair_id(
    *,
    system: str,
    codec: str,
    policy: str,
    deadline_ms: float,
    repeat: int,
) -> str:
    return "--".join(
        (
            system,
            codec,
            _slug(policy),
            f"d{_slug(deadline_ms)}",
            f"r{repeat:02d}",
        )
    )


def _ordered_scenarios(pair_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(pair_id.encode("utf-8")).digest()
    if digest[0] & 1:
        return CHECKPOINT_SCENARIOS[1], CHECKPOINT_SCENARIOS[0]
    return CHECKPOINT_SCENARIOS


def build_full_publication_matrix(config: dict[str, Any]) -> dict[str, Any]:
    benchmark = config.get("benchmark") or {}
    protocol = config.get("protocol") or {}
    policies = tuple(str(value) for value in benchmark.get("scheduler_policies") or ())
    deadlines = tuple(float(value) for value in benchmark.get("deadline_ms") or ())
    repeats = int(protocol.get("repeats", 0) or 0)
    warmup_s = int(protocol.get("warmup_s", 0) or 0)
    measurement_s = int(protocol.get("measurement_s", 0) or 0)
    seed = int(benchmark.get("default_seed", 0) or 0)

    if len(policies) != 7 or len(set(policies)) != 7:
        raise ContractError("full publication matrix requires exactly seven unique policies")
    if len(deadlines) != 5 or len(set(deadlines)) != 5:
        raise ContractError("full publication matrix requires exactly five unique deadlines")
    if repeats != 10:
        raise ContractError("full publication matrix requires exactly ten repeats")
    if (warmup_s, measurement_s) != (30, 180):
        raise ContractError("full publication matrix requires warmup_s=30 and measurement_s=180")
    if seed <= 0:
        raise ContractError("full publication matrix requires a positive frozen seed")

    pairs: list[dict[str, Any]] = []
    for system in PUBLISHABLE_SYSTEMS:
        for codec, dataset in DATASET_BY_CODEC.items():
            for policy in policies:
                for deadline_ms in deadlines:
                    for repeat in range(1, repeats + 1):
                        pair_id = _pair_id(
                            system=system,
                            codec=codec,
                            policy=policy,
                            deadline_ms=deadline_ms,
                            repeat=repeat,
                        )
                        arms = []
                        for position, scenario in enumerate(
                            _ordered_scenarios(pair_id),
                            start=1,
                        ):
                            arms.append(
                                {
                                    "arm_id": f"{pair_id}--a{position}",
                                    "arm_position": position,
                                    "scenario": scenario,
                                    "system": system,
                                    "codec": codec,
                                    "dataset": dataset,
                                    "policy": policy,
                                    "deadline_ms": deadline_ms,
                                    "repeat": repeat,
                                    "seed": seed,
                                    "streams": 6,
                                    "warmup_s": warmup_s,
                                    "measurement_s": measurement_s,
                                }
                            )
                        pairs.append(
                            {
                                "pair_id": pair_id,
                                "system": system,
                                "codec": codec,
                                "dataset": dataset,
                                "policy": policy,
                                "deadline_ms": deadline_ms,
                                "repeat": repeat,
                                "arms": arms,
                            }
                        )

    random.Random(seed).shuffle(pairs)
    expected_pairs = (
        len(PUBLISHABLE_SYSTEMS)
        * len(DATASET_BY_CODEC)
        * len(policies)
        * len(deadlines)
        * repeats
    )
    if len(pairs) != expected_pairs:
        raise ContractError("full publication matrix cardinality drifted")

    return {
        "schema_version": FULL_MATRIX_SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_matrix",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "selection_basis": "frozen_config_before_full_matrix_results",
        "order_strategy": "deterministic_seeded_pair_shuffle_hash_balanced_arm_order_v1",
        "seed": seed,
        "systems": list(PUBLISHABLE_SYSTEMS),
        "scenarios": list(CHECKPOINT_SCENARIOS),
        "codecs": list(DATASET_BY_CODEC),
        "policies": list(policies),
        "deadlines_ms": list(deadlines),
        "repeats": repeats,
        "warmup_s": warmup_s,
        "measurement_s": measurement_s,
        "expected_pairs": expected_pairs,
        "expected_arms": expected_pairs * 2,
        "pairs": pairs,
    }


def validate_full_publication_readiness(config: dict[str, Any]) -> dict[str, Any]:
    build_full_publication_matrix(config)
    blockers: list[str] = []
    scenarios = config.get("scenarios") or {}
    systems = config.get("systems") or {}

    for scenario_name in CHECKPOINT_SCENARIOS:
        scenario = scenarios.get(scenario_name)
        if not isinstance(scenario, dict):
            blockers.append(f"scenario:{scenario_name}:missing")
            continue
        status = str(scenario.get("benchmark_status", "supported"))
        if status != "supported":
            blockers.append(f"scenario:{scenario_name}:{status}")

    for system_name in PUBLISHABLE_SYSTEMS:
        system = systems.get(system_name)
        if not isinstance(system, dict):
            blockers.append(f"system:{system_name}:missing")
            continue
        status = str(system.get("benchmark_status", "supported"))
        if status != "supported":
            blockers.append(f"system:{system_name}:{status}")

    extension = (config.get("benchmark") or {}).get("resource_interval_extension")
    if not isinstance(extension, dict):
        raise ContractError("benchmark.resource_interval_extension must be declared")
    if int(extension.get("contract_version", 0) or 0) != 2:
        raise ContractError("resource interval extension contract_version must be 2")
    if set(str(value) for value in extension.get("components") or ()) != EXPECTED_RESOURCE_COMPONENTS:
        raise ContractError("resource interval extension components have drifted")
    if str(extension.get("counter_scope", "")) != "per_trace_interval":
        raise ContractError("resource interval extension counter_scope must be per_trace_interval")

    if str(extension.get("status", "")) != "accepted_full_resource_publication_v2":
        blockers.append("full_resource_extension_not_accepted")
    if str(extension.get("current_publication_bundle_scope", "")) != FULL_RESOURCE_PUBLICATION_SCOPE:
        blockers.append("full_resource_publication_scope_not_active")
    if not bool(extension.get("publication_bundle_bound")):
        blockers.append("full_resource_publication_bundle_not_bound")
    if not bool(extension.get("evidence_accepted")):
        blockers.append("full_resource_evidence_not_accepted")
    if str(extension.get("true_nvdec_busy_status", "")) != "device_level_nvml_sampled":
        blockers.append("nvdec_busy_sampling_not_accepted")
    if str(extension.get("fanout_resource_work_status", "")) != "native_cpu_thread_time_sampled":
        blockers.append("fanout_resource_work_not_accepted")

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_readiness",
        "passed": not blockers,
        "status": "ready" if not blockers else "blocked",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "blockers": blockers,
    }
