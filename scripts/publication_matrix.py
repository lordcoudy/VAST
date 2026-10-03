#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from typing import Any

from backend_publication_dispatch import (
    BackendPublicationDispatchError,
    BackendPublicationDispatchResolver,
)
from backend_runtime_grant import (
    assess_pre_run_backend_runtime_grant,
    backend_launcher_output_receipt_protocol_ready,
)
from benchmark_contract import ContractError, assess_pre_run_resource_capability_grant
from benchmark_contract import (
    primary_architecture_pair_metadata,
    validate_primary_architecture_contrast,
)
from publication_policy_contract import (
    POLICIES as PUBLICATION_POLICIES,
    assess_capability_manifest,
    policy_contract_identity,
)
from model_parity_grant import assess_pre_run_model_parity_grant


FULL_RESOURCE_PUBLICATION_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"
FULL_MATRIX_SCHEMA_VERSION = 4
FULL_MATRIX_IDENTITY_SCHEMA_VERSION = 4
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
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
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

    if policies != PUBLICATION_POLICIES:
        raise ContractError(
            "full publication matrix scheduler_policies must match the frozen policy contract"
        )
    if len(deadlines) != 5 or len(set(deadlines)) != 5:
        raise ContractError("full publication matrix requires exactly five unique deadlines")
    if repeats != 10:
        raise ContractError("full publication matrix requires exactly ten repeats")
    if (warmup_s, measurement_s) != (30, 180):
        raise ContractError("full publication matrix requires warmup_s=30 and measurement_s=180")
    if seed <= 0:
        raise ContractError("full publication matrix requires a positive frozen seed")

    primary = validate_primary_architecture_contrast(config)
    primary_coordinates = {
        "system": str(primary["system"]),
        "codec": str(primary["codec"]),
        "dataset": str(primary["dataset"]),
        "policy": str(primary["policy"]),
        "deadline_ms": float(primary["deadline_ms"]),
        "streams": int(primary["streams"]),
        "repeats": int(primary["repeats"]),
    }
    if (
        primary_coordinates["system"] not in PUBLISHABLE_SYSTEMS
        or DATASET_BY_CODEC.get(primary_coordinates["codec"])
        != primary_coordinates["dataset"]
        or primary_coordinates["policy"] not in policies
        or primary_coordinates["deadline_ms"] not in deadlines
        or primary_coordinates["streams"] != 6
        or primary_coordinates["repeats"] != repeats
    ):
        raise ContractError(
            "primary architecture contrast is not an exact subset of the full matrix"
        )

    pairs: list[dict[str, Any]] = []
    primary_pair_count = 0
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
                        is_primary_pair = (
                            system == primary_coordinates["system"]
                            and codec == primary_coordinates["codec"]
                            and dataset == primary_coordinates["dataset"]
                            and policy == primary_coordinates["policy"]
                            and deadline_ms == primary_coordinates["deadline_ms"]
                        )
                        if is_primary_pair:
                            first_scenario = str(
                                primary["arm_order"]["first_arm_by_pair"][repeat - 1]
                            )
                            second_scenario = (
                                str(primary["shared_scenario"])
                                if first_scenario == str(primary["baseline_scenario"])
                                else str(primary["baseline_scenario"])
                            )
                            ordered_scenarios = (first_scenario, second_scenario)
                            primary_pair_count += 1
                        else:
                            ordered_scenarios = _ordered_scenarios(pair_id)
                        arms = []
                        for position, scenario in enumerate(
                            ordered_scenarios,
                            start=1,
                        ):
                            arm = {
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
                            if is_primary_pair:
                                arm["primary_architecture_pair"] = (
                                    primary_architecture_pair_metadata(
                                        config,
                                        repeat=repeat,
                                        scenario=scenario,
                                    )
                                )
                            arms.append(arm)
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
    if primary_pair_count != repeats:
        raise ContractError(
            "full publication matrix must contain exactly ten primary architecture pairs"
        )

    primary_preregistration_sha256 = hashlib.sha256(
        _canonical_json(primary)
    ).hexdigest()

    return {
        "schema_version": FULL_MATRIX_SCHEMA_VERSION,
        "artifact_kind": "vast_full_publication_matrix",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "selection_basis": "frozen_config_before_full_matrix_results",
        "order_strategy": (
            "deterministic_seeded_pair_shuffle_"
            "preregistered_primary_counterbalance_else_hash_balanced_v2"
        ),
        "primary_architecture_pair_contract": {
            "preregistration_version": int(primary["preregistration_version"]),
            "preregistration_sha256": primary_preregistration_sha256,
            "selection_basis": str(primary["selection_basis"]),
            "coordinates": primary_coordinates,
            "strategy": str(primary["arm_order"]["strategy"]),
            "pair_metadata_contract_version": 1,
            "pair_count": primary_pair_count,
            "arm_count": primary_pair_count * 2,
        },
        "policy_contract_identity": policy_contract_identity(),
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


def validate_full_publication_readiness(
    config: dict[str, Any],
    *,
    resource_capability_grant: dict[str, Any] | None = None,
    backend_runtime_grant: dict[str, Any] | None = None,
    model_parity_grant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matrix = build_full_publication_matrix(config)
    blockers: list[str] = []
    benchmark = config.get("benchmark") or {}
    scenarios = config.get("scenarios") or {}
    systems = config.get("systems") or {}

    policy_capabilities = assess_capability_manifest(
        benchmark.get("publication_policy_capability_manifest")
    )
    blockers.extend(str(value) for value in policy_capabilities["blockers"])

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

    extension = benchmark.get("resource_interval_extension")
    if not isinstance(extension, dict):
        raise ContractError("benchmark.resource_interval_extension must be declared")
    if int(extension.get("contract_version", 0) or 0) != 2:
        raise ContractError("resource interval extension contract_version must be 2")
    if set(str(value) for value in extension.get("components") or ()) != EXPECTED_RESOURCE_COMPONENTS:
        raise ContractError("resource interval extension components have drifted")
    if str(extension.get("counter_scope", "")) != "per_trace_interval":
        raise ContractError("resource interval extension counter_scope must be per_trace_interval")

    resource_capability = assess_pre_run_resource_capability_grant(
        resource_capability_grant
    )
    blockers.extend(str(value) for value in resource_capability["blockers"])
    parity_capability = assess_pre_run_model_parity_grant(model_parity_grant)
    blockers.extend(
        f"pre_run_model_parity_grant:{value}"
        for value in parity_capability["blockers"]
    )
    backend_capability = assess_pre_run_backend_runtime_grant(
        backend_runtime_grant
    )
    blockers.extend(
        f"pre_run_backend_runtime_grant:{value}"
        for value in backend_capability["blockers"]
    )
    backend_resolver: BackendPublicationDispatchResolver | None = None
    try:
        backend_resolver = BackendPublicationDispatchResolver(
            backend_runtime_grant
        )
    except BackendPublicationDispatchError:
        pass
    # This is derived only from a fully validated schema-v3 grant whose four
    # launcher authorities and parent-owned production transaction/receipt
    # protocol files are identity-registered.  Schema-v2 grants remain blocked.
    launcher_output_receipt_protocol_ready = (
        backend_launcher_output_receipt_protocol_ready(backend_runtime_grant)
    )

    blocked_arms = 0
    blocked_by_system: Counter[str] = Counter()
    runtime_blocker_counts: Counter[str] = Counter()
    runtime_samples: list[dict[str, Any]] = []
    for pair in matrix["pairs"]:
        for arm in pair["arms"]:
            try:
                if not launcher_output_receipt_protocol_ready:
                    raise BackendPublicationDispatchError(
                        "backend_launcher_output_receipt_protocol_not_implemented"
                    )
                if backend_resolver is None:
                    raise BackendPublicationDispatchError(
                        "pre-run backend runtime grant is unavailable or invalid"
                    )
                backend_resolver.resolve(
                    system=str(arm["system"]),
                    scenario=str(arm["scenario"]),
                    codec=str(arm["codec"]),
                    policy=str(arm["policy"]),
                    deadline_ms=float(arm["deadline_ms"]),
                )
                cell_blockers = []
            except BackendPublicationDispatchError as error:
                cell_blockers = [str(error)]
            if not cell_blockers:
                continue
            blocked_arms += 1
            blocked_by_system[str(arm["system"])] += 1
            runtime_blocker_counts.update(str(value) for value in cell_blockers)
            if len(runtime_samples) < 12:
                runtime_samples.append(
                    {
                        "arm_id": str(arm["arm_id"]),
                        "system": str(arm["system"]),
                        "scenario": str(arm["scenario"]),
                        "codec": str(arm["codec"]),
                        "policy": str(arm["policy"]),
                        "deadline_ms": float(arm["deadline_ms"]),
                        "blockers": [str(value) for value in cell_blockers],
                    }
                )
    if blocked_arms:
        blockers.append(
            f"checkpoint_runtime_cells_blocked:{blocked_arms}/{matrix['expected_arms']}"
        )
        blockers.extend(
            f"checkpoint_backend:{system}:blocked_arms:{count}"
            for system, count in sorted(blocked_by_system.items())
        )

    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_readiness",
        "passed": not blockers,
        "status": "ready" if not blockers else "blocked",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "blockers": blockers,
        "pre_run_resource_capability_assessment": resource_capability,
        "pre_run_model_parity_grant_assessment": parity_capability,
        "pre_run_backend_runtime_grant_assessment": backend_capability,
        "backend_launcher_output_receipt_protocol_ready": (
            launcher_output_receipt_protocol_ready
        ),
        "runtime_cell_assessment": {
            "assessed_arms": int(matrix["expected_arms"]),
            "blocked_arms": blocked_arms,
            "ready_arms": int(matrix["expected_arms"]) - blocked_arms,
            "blocked_by_system": dict(sorted(blocked_by_system.items())),
            "blocker_counts": dict(sorted(runtime_blocker_counts.items())),
            "samples": runtime_samples,
        },
    }
