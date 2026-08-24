#!/usr/bin/env python3
"""Frozen, replayable scheduler contract for the full publication matrix.

This module deliberately separates a deterministic policy decision from proof that
the decision was executed by a real runtime implementation.  A decision is not
publication-eligible until :func:`bind_native_decision_evidence` has matched it to
an emitter declared by a complete capability manifest.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import re
from typing import Any, Mapping, Sequence

from benchmark_contract import ContractError


POLICY_CONTRACT_SCHEMA_VERSION = 1
POLICY_CONTRACT_IDENTITY_SCHEMA_VERSION = 1
CAPABILITY_MANIFEST_SCHEMA_VERSION = 1
DECISION_RECORD_SCHEMA_VERSION = 1
CALIBRATION_SCHEMA_VERSION = 1
STATIC_MAP_SCHEMA_VERSION = 1
POLICY_SCOPE = "analytics_only"
ENGINE_IMPLEMENTATION_ID = "vast-publication-policy-engine-v1"
MIN_CALIBRATION_SAMPLES = 30

PUBLISHABLE_SYSTEMS = (
    "deepstream",
    "savant",
    "openvino_gva",
    "gstreamer_custom",
)
ANALYTICS_BRANCHES = (
    "plate_number",
    "vehicle_type",
    "damage",
    "foreign_object",
)
RESOURCES = ("cpu", "gpu")
POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{7,}$")
_PLACEHOLDER_IDS = {
    "cpu",
    "gpu",
    "native",
    "unknown",
    "unavailable",
    "label_only",
    "derived",
    "placeholder",
}


class PolicyContractError(ContractError):
    """A frozen policy, capability, calibration, or replay invariant failed."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PolicyContractError("policy artifact is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _payload_with_sha256(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result["sha256"] = _sha256(result)
    return result


def _valid_sha256(value: Any) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value)))


def _real_id(value: Any) -> bool:
    text = str(value)
    return bool(_REAL_ID_RE.fullmatch(text)) and text.lower() not in _PLACEHOLDER_IDS


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PolicyContractError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PolicyContractError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise PolicyContractError(f"{name} must be finite")
    return number


def _nonnegative(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number < 0.0:
        raise PolicyContractError(f"{name} must be nonnegative")
    return number


def _positive(value: Any, name: str) -> float:
    number = _finite(value, name)
    if number <= 0.0:
        raise PolicyContractError(f"{name} must be positive")
    return number


def build_policy_contract() -> dict[str, Any]:
    """Return the immutable v1 scientific scheduler contract."""

    return {
        "schema_version": POLICY_CONTRACT_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_policy_contract",
        "policy_scope": POLICY_SCOPE,
        "fixed_stage_placement": {
            "decode": "nvdec",
            "ingest": "fixed_runtime_resource",
            "preprocess": "fixed_runtime_resource",
            "aggregate": "cpu",
            "record": "cpu",
        },
        "analytics_branches": list(ANALYTICS_BRANCHES),
        "resources": list(RESOURCES),
        "policies": list(POLICIES),
        "engine_implementation_id": ENGINE_IMPLEMENTATION_ID,
        "decision_record_schema_version": DECISION_RECORD_SCHEMA_VERSION,
        "resource_tie_break": [
            "policy_score",
            "transfer_ms",
            "queue_depth",
            "fixed_resource_order_cpu_gpu",
        ],
        "ready_task_order": {
            "queue_aware_edf": [
                "absolute_deadline_ascending",
                "upward_rank_descending",
                "arrival_ascending",
                "trace_id_ascending",
                "branch_ascending",
            ],
            "heft_family": [
                "upward_rank_descending",
                "absolute_deadline_ascending",
                "arrival_ascending",
                "trace_id_ascending",
                "branch_ascending",
            ],
            "fixed_family": [
                "arrival_ascending",
                "absolute_deadline_ascending",
                "trace_id_ascending",
                "branch_ascending",
            ],
        },
        "policy_definitions": {
            "cpu_only": {"algorithm": "force_resource", "resource": "cpu"},
            "gpu_only": {"algorithm": "force_resource", "resource": "gpu"},
            "static_hybrid": {
                "algorithm": "frozen_calibrated_mixed_map",
                "calibration_min_samples_per_cell": MIN_CALIBRATION_SAMPLES,
                "candidate_maps": 14,
                "objective": "minimize_max_per_resource_serial_load_ms",
                "pure_cpu_and_pure_gpu_maps": "prohibited",
            },
            "heft": {
                "algorithm": "canonical_heft_earliest_finish_time",
                "score": "max(decision_time_ms,available_ms)+service_ms+transfer_ms",
            },
            "deadline_aware_heft": {
                "algorithm": "deadline_feasible_heft_then_minimum_lateness",
                "feasible_first": True,
            },
            "queue_aware_edf": {
                "algorithm": "absolute_edf_then_queue_completion",
                "resource_score": (
                    "max(decision_time_ms,available_ms)"
                    "+(queue_depth+1)*service_ms+transfer_ms"
                ),
            },
            "adaptive_weights": {
                "algorithm": "bounded_queue_ewma_cost",
                "score": "(queue_depth+1)*service_ewma_ms*weight+transfer_ms",
                "ewma_alpha": 0.1,
                "initial_weight": 1.0,
                "late_penalty": 0.002,
                "on_time_reward": 0.0002,
                "weight_lower_bound": 0.5,
                "weight_upper_bound": 1.5,
                "reset_scope": "arm",
            },
        },
        "publication_acceptance": {
            "capability_manifest_required": True,
            "cpu_and_gpu_implementation_required_per_system_branch": True,
            "native_decision_event_required": True,
            "derived_policy_label_accepted": False,
            "runtime_fallback_accepted": False,
            "offline_replay_required": True,
        },
    }


def policy_contract_identity(contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    candidate = copy.deepcopy(
        dict(build_policy_contract() if contract is None else contract)
    )
    if candidate != build_policy_contract():
        raise PolicyContractError(
            "policy contract drift requires a schema/implementation version change"
        )
    return {
        "schema_version": POLICY_CONTRACT_IDENTITY_SCHEMA_VERSION,
        "sha256": _sha256(candidate),
    }


def assess_capability_manifest(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Assess a full system/branch/resource manifest without accepting labels."""

    blockers: list[str] = []
    expected_contract_sha = policy_contract_identity()["sha256"]
    if not isinstance(manifest, Mapping):
        blockers.append("publication_policy_capability_manifest_missing")
        return {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_capability_assessment",
            "passed": False,
            "status": "blocked",
            "blockers": blockers,
            "manifest_sha256": None,
        }

    if manifest.get("schema_version") != CAPABILITY_MANIFEST_SCHEMA_VERSION:
        blockers.append("capability_manifest_schema_version_mismatch")
    if manifest.get("artifact_kind") != "vast_publication_policy_capability_manifest":
        blockers.append("capability_manifest_artifact_kind_mismatch")
    if manifest.get("policy_scope") != POLICY_SCOPE:
        blockers.append("capability_manifest_policy_scope_mismatch")
    if manifest.get("policy_contract_sha256") != expected_contract_sha:
        blockers.append("capability_manifest_policy_contract_sha256_mismatch")

    systems = manifest.get("systems")
    if not isinstance(systems, Mapping):
        systems = {}
        blockers.append("capability_manifest_systems_missing")
    if set(systems) != set(PUBLISHABLE_SYSTEMS):
        blockers.append("capability_manifest_system_set_mismatch")

    implementation_ids: list[str] = []
    emitter_ids: list[str] = []
    for system in PUBLISHABLE_SYSTEMS:
        system_entry = systems.get(system)
        if not isinstance(system_entry, Mapping):
            blockers.append(f"capability:{system}:missing")
            continue
        branches = system_entry.get("branches")
        if not isinstance(branches, Mapping):
            blockers.append(f"capability:{system}:branches_missing")
            continue
        if set(branches) != set(ANALYTICS_BRANCHES):
            blockers.append(f"capability:{system}:branch_set_mismatch")
        for branch in ANALYTICS_BRANCHES:
            resources = branches.get(branch)
            if not isinstance(resources, Mapping):
                blockers.append(f"capability:{system}:{branch}:missing")
                continue
            if set(resources) != set(RESOURCES):
                blockers.append(f"capability:{system}:{branch}:resource_set_mismatch")
            for resource in RESOURCES:
                prefix = f"capability:{system}:{branch}:{resource}"
                binding = resources.get(resource)
                if not isinstance(binding, Mapping):
                    blockers.append(f"{prefix}:missing")
                    continue
                implementation_id = str(binding.get("implementation_id", ""))
                if not _real_id(implementation_id):
                    blockers.append(f"{prefix}:implementation_id_not_real")
                else:
                    implementation_ids.append(implementation_id)
                if binding.get("status") != "implemented_and_native_evidence_bound":
                    blockers.append(f"{prefix}:implementation_not_bound")
                if not _valid_sha256(binding.get("implementation_sha256")):
                    blockers.append(f"{prefix}:implementation_sha256_invalid")
                if not _real_id(binding.get("runtime_binding")):
                    blockers.append(f"{prefix}:runtime_binding_not_real")

                evidence = binding.get("native_evidence")
                native_bound = isinstance(evidence, Mapping) and all(
                    (
                        evidence.get("status") == "accepted_native_runtime_emitter",
                        evidence.get("telemetry_source") == "native",
                        _real_id(evidence.get("emitter_id")),
                        _valid_sha256(evidence.get("emitter_sha256")),
                        _real_id(evidence.get("implementation_id_field")),
                        _real_id(evidence.get("resource_field")),
                    )
                )
                if not native_bound:
                    blockers.append(f"{prefix}:native_evidence_not_bound")
                elif isinstance(evidence, Mapping):
                    emitter_ids.append(str(evidence["emitter_id"]))

    if len(set(implementation_ids)) != len(implementation_ids):
        blockers.append("capability_manifest_implementation_ids_not_unique")
    if len(set(emitter_ids)) != len(emitter_ids):
        blockers.append("capability_manifest_emitter_ids_not_unique")
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_capability_assessment",
        "passed": not blockers,
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "manifest_sha256": _sha256(dict(manifest)),
    }


def _require_capabilities(manifest: Mapping[str, Any]) -> None:
    assessment = assess_capability_manifest(manifest)
    if not assessment["passed"]:
        raise PolicyContractError(
            "capability manifest is not publication-ready: "
            + ", ".join(assessment["blockers"][:5])
        )


def _binding(
    manifest: Mapping[str, Any],
    system: str,
    branch: str,
    resource: str,
) -> Mapping[str, Any]:
    return manifest["systems"][system]["branches"][branch][resource]


def select_static_hybrid_map(
    system: str,
    calibration: Mapping[str, Any],
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Choose the best non-pure placement from all 14 mixed maps."""

    _require_capabilities(capability_manifest)
    if system not in PUBLISHABLE_SYSTEMS:
        raise PolicyContractError(f"unknown publication system: {system}")
    if calibration.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise PolicyContractError("calibration schema_version must be 1")
    if calibration.get("artifact_kind") != "vast_publication_policy_calibration":
        raise PolicyContractError("calibration artifact_kind has drifted")
    if calibration.get("system") != system:
        raise PolicyContractError("calibration system does not match requested system")
    contract_sha = policy_contract_identity()["sha256"]
    if calibration.get("policy_contract_sha256") != contract_sha:
        raise PolicyContractError("calibration policy_contract_sha256 has drifted")
    costs = calibration.get("costs")
    if not isinstance(costs, Mapping) or set(costs) != set(ANALYTICS_BRANCHES):
        raise PolicyContractError("calibration must cover every analytics branch exactly")

    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for branch in ANALYTICS_BRANCHES:
        resource_costs = costs.get(branch)
        if not isinstance(resource_costs, Mapping) or set(resource_costs) != set(RESOURCES):
            raise PolicyContractError(
                f"calibration {branch} must cover cpu and gpu exactly"
            )
        normalized[branch] = {}
        for resource in RESOURCES:
            row = resource_costs.get(resource)
            if not isinstance(row, Mapping):
                raise PolicyContractError(f"calibration {branch}/{resource} row is missing")
            expected_id = str(
                _binding(capability_manifest, system, branch, resource)["implementation_id"]
            )
            if row.get("implementation_id") != expected_id:
                raise PolicyContractError(
                    f"calibration {branch}/{resource} implementation_id does not match capability binding"
                )
            samples = row.get("samples")
            if isinstance(samples, bool) or not isinstance(samples, int) or samples < MIN_CALIBRATION_SAMPLES:
                raise PolicyContractError(
                    f"calibration {branch}/{resource} requires at least 30 samples"
                )
            normalized[branch][resource] = {
                "implementation_id": expected_id,
                "service_ms": _positive(
                    row.get("service_ms"), f"calibration {branch}/{resource}.service_ms"
                ),
                "transfer_ms": _nonnegative(
                    row.get("transfer_ms"), f"calibration {branch}/{resource}.transfer_ms"
                ),
                "samples": samples,
            }

    candidates: list[tuple[tuple[Any, ...], dict[str, str], dict[str, float]]] = []
    resource_index = {resource: index for index, resource in enumerate(RESOURCES)}
    for assignment in itertools.product(RESOURCES, repeat=len(ANALYTICS_BRANCHES)):
        if set(assignment) != set(RESOURCES):
            continue
        placement = dict(zip(ANALYTICS_BRANCHES, assignment, strict=True))
        loads = {resource: 0.0 for resource in RESOURCES}
        for branch, resource in placement.items():
            row = normalized[branch][resource]
            loads[resource] += row["service_ms"] + row["transfer_ms"]
        critical_path = max(loads.values())
        key = (
            critical_path,
            tuple(resource_index[placement[branch]] for branch in ANALYTICS_BRANCHES),
        )
        candidates.append((key, placement, loads))
    key, placement, loads = min(candidates, key=lambda item: item[0])
    payload = {
        "schema_version": STATIC_MAP_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_static_hybrid_map",
        "policy_contract_sha256": contract_sha,
        "system": system,
        "selection": "exhaustive_nonempty_mixed_placement_v1",
        "candidate_count": len(candidates),
        "calibration_sha256": _sha256(dict(calibration)),
        "placement": placement,
        "implementation_ids": {
            branch: normalized[branch][resource]["implementation_id"]
            for branch, resource in placement.items()
        },
        "predicted_resource_load_ms": loads,
        "predicted_critical_path_ms": key[0],
    }
    return _payload_with_sha256(payload)


def _validate_static_map(
    artifact: Mapping[str, Any] | None,
    system: str,
    capability_manifest: Mapping[str, Any],
) -> dict[str, str]:
    if not isinstance(artifact, Mapping):
        raise PolicyContractError("static_hybrid requires a frozen calibration map")
    payload = dict(artifact)
    digest = payload.pop("sha256", None)
    if not _valid_sha256(digest) or _sha256(payload) != digest:
        raise PolicyContractError("static_hybrid map sha256 mismatch")
    if payload.get("schema_version") != STATIC_MAP_SCHEMA_VERSION:
        raise PolicyContractError("static_hybrid map schema_version has drifted")
    if payload.get("artifact_kind") != "vast_publication_static_hybrid_map":
        raise PolicyContractError("static_hybrid map artifact_kind has drifted")
    if payload.get("policy_contract_sha256") != policy_contract_identity()["sha256"]:
        raise PolicyContractError("static_hybrid map policy contract has drifted")
    if payload.get("system") != system:
        raise PolicyContractError("static_hybrid map belongs to another system")
    if payload.get("candidate_count") != 14:
        raise PolicyContractError("static_hybrid map did not evaluate all 14 mixed maps")
    placement = payload.get("placement")
    if not isinstance(placement, Mapping) or set(placement) != set(ANALYTICS_BRANCHES):
        raise PolicyContractError("static_hybrid placement branch set has drifted")
    normalized = {branch: str(placement[branch]) for branch in ANALYTICS_BRANCHES}
    if set(normalized.values()) != set(RESOURCES):
        raise PolicyContractError("static_hybrid placement must contain cpu and gpu")
    implementation_ids = payload.get("implementation_ids")
    if not isinstance(implementation_ids, Mapping):
        raise PolicyContractError("static_hybrid implementation_ids are missing")
    for branch, resource in normalized.items():
        expected = _binding(capability_manifest, system, branch, resource)["implementation_id"]
        if implementation_ids.get(branch) != expected:
            raise PolicyContractError(
                f"static_hybrid {branch} implementation does not match capability binding"
            )
    return normalized


def _normalize_request(
    request: Mapping[str, Any],
    system: str,
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "decision_id",
        "decision_seq",
        "trace_id",
        "branch",
        "arrival_ms",
        "decision_time_ms",
        "deadline_ms",
        "rank_u_ms",
        "candidates",
    }
    if set(request) != expected:
        raise PolicyContractError("decision request fields have drifted")
    decision_id = str(request.get("decision_id", ""))
    trace_id = str(request.get("trace_id", ""))
    if not _real_id(decision_id) or not _real_id(trace_id):
        raise PolicyContractError("decision_id and trace_id must be real stable IDs")
    decision_seq = request.get("decision_seq")
    if isinstance(decision_seq, bool) or not isinstance(decision_seq, int) or decision_seq <= 0:
        raise PolicyContractError("decision_seq must be a positive integer")
    branch = str(request.get("branch", ""))
    if branch not in ANALYTICS_BRANCHES:
        raise PolicyContractError("decision branch is outside policy_scope=analytics_only")
    candidates = request.get("candidates")
    if not isinstance(candidates, Mapping) or set(candidates) != set(RESOURCES):
        raise PolicyContractError("decision candidates must contain exactly cpu and gpu")

    normalized_candidates: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        candidate = candidates.get(resource)
        fields = {
            "allowed",
            "implementation_id",
            "available_ms",
            "queue_depth",
            "estimated_service_ms",
            "transfer_ms",
        }
        if not isinstance(candidate, Mapping) or set(candidate) != fields:
            raise PolicyContractError(f"{resource} candidate fields have drifted")
        if not isinstance(candidate.get("allowed"), bool):
            raise PolicyContractError(f"{resource}.allowed must be boolean")
        expected_id = str(
            _binding(capability_manifest, system, branch, resource)["implementation_id"]
        )
        if candidate.get("implementation_id") != expected_id:
            raise PolicyContractError(
                f"{resource} candidate implementation_id does not match capability binding"
            )
        queue_depth = candidate.get("queue_depth")
        if isinstance(queue_depth, bool) or not isinstance(queue_depth, int) or queue_depth < 0:
            raise PolicyContractError(f"{resource}.queue_depth must be a nonnegative integer")
        normalized_candidates[resource] = {
            "allowed": candidate["allowed"],
            "implementation_id": expected_id,
            "available_ms": _nonnegative(candidate.get("available_ms"), f"{resource}.available_ms"),
            "queue_depth": queue_depth,
            "estimated_service_ms": _positive(
                candidate.get("estimated_service_ms"), f"{resource}.estimated_service_ms"
            ),
            "transfer_ms": _nonnegative(candidate.get("transfer_ms"), f"{resource}.transfer_ms"),
        }

    return {
        "decision_id": decision_id,
        "decision_seq": decision_seq,
        "trace_id": trace_id,
        "branch": branch,
        "arrival_ms": _nonnegative(request.get("arrival_ms"), "arrival_ms"),
        "decision_time_ms": _nonnegative(request.get("decision_time_ms"), "decision_time_ms"),
        "deadline_ms": _positive(request.get("deadline_ms"), "deadline_ms"),
        "rank_u_ms": _nonnegative(request.get("rank_u_ms"), "rank_u_ms"),
        "candidates": normalized_candidates,
    }


def _evaluate_policy(
    policy: str,
    request: Mapping[str, Any],
    *,
    static_placement: Mapping[str, str] | None,
    state_before: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = request["candidates"]
    decision_time = float(request["decision_time_ms"])
    deadline = float(request["deadline_ms"])
    branch = str(request["branch"])
    resource_index = {resource: index for index, resource in enumerate(RESOURCES)}
    evaluations: dict[str, dict[str, Any]] = {}
    for resource in RESOURCES:
        candidate = candidates[resource]
        start = max(decision_time, float(candidate["available_ms"]))
        service = float(candidate["estimated_service_ms"])
        transfer = float(candidate["transfer_ms"])
        finish = start + service + transfer
        evaluations[resource] = {
            "allowed": bool(candidate["allowed"]),
            "implementation_id": str(candidate["implementation_id"]),
            "available_ms": float(candidate["available_ms"]),
            "queue_depth": int(candidate["queue_depth"]),
            "estimated_service_ms": service,
            "transfer_ms": transfer,
            "predicted_start_ms": start,
            "predicted_finish_ms": finish,
            "predicted_lateness_ms": max(0.0, finish - deadline),
        }

    allowed = [resource for resource in RESOURCES if evaluations[resource]["allowed"]]
    if not allowed:
        raise PolicyContractError("decision has no allowed real execution resource")

    def tie_tail(resource: str) -> tuple[Any, ...]:
        value = evaluations[resource]
        return (value["transfer_ms"], value["queue_depth"], resource_index[resource])

    if policy in {"cpu_only", "gpu_only"}:
        selected = "cpu" if policy == "cpu_only" else "gpu"
        if selected not in allowed:
            raise PolicyContractError(f"{policy} required resource is not allowed")
        reason = "forced_policy_resource"
    elif policy == "static_hybrid":
        if static_placement is None:
            raise PolicyContractError("static_hybrid placement is missing")
        selected = str(static_placement[branch])
        if selected not in allowed:
            raise PolicyContractError("static_hybrid selected resource is not allowed")
        reason = "frozen_calibrated_mixed_map"
    elif policy == "heft":
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["predicted_finish_ms"],) + tie_tail(resource),
        )
        reason = "minimum_earliest_finish_time"
    elif policy == "deadline_aware_heft":
        selected = min(
            allowed,
            key=lambda resource: (
                evaluations[resource]["predicted_finish_ms"] > deadline,
                evaluations[resource]["predicted_lateness_ms"],
                evaluations[resource]["predicted_finish_ms"],
            )
            + tie_tail(resource),
        )
        reason = (
            "minimum_feasible_finish_time"
            if evaluations[selected]["predicted_finish_ms"] <= deadline
            else "minimum_predicted_lateness"
        )
    elif policy == "queue_aware_edf":
        for resource in RESOURCES:
            value = evaluations[resource]
            value["queue_completion_ms"] = max(
                decision_time, float(value["available_ms"])
            ) + (value["queue_depth"] + 1) * value["estimated_service_ms"] + value["transfer_ms"]
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["queue_completion_ms"],) + tie_tail(resource),
        )
        reason = "edf_task_minimum_queue_completion"
    elif policy == "adaptive_weights":
        weights = state_before.get("weights")
        ewma = state_before.get("service_ewma_ms")
        if not isinstance(weights, Mapping) or set(weights) != set(RESOURCES):
            raise PolicyContractError("adaptive state weights have drifted")
        if not isinstance(ewma, Mapping):
            raise PolicyContractError("adaptive EWMA state has drifted")
        branch_ewma = ewma.get(branch, {})
        if not isinstance(branch_ewma, Mapping):
            raise PolicyContractError("adaptive branch EWMA state has drifted")
        for resource in RESOURCES:
            value = evaluations[resource]
            service_basis = float(
                branch_ewma.get(resource, value["estimated_service_ms"])
            )
            weight = float(weights[resource])
            value["service_basis_ms"] = service_basis
            value["adaptive_weight"] = weight
            value["adaptive_score_ms"] = (
                (value["queue_depth"] + 1) * service_basis * weight
                + value["transfer_ms"]
            )
        selected = min(
            allowed,
            key=lambda resource: (evaluations[resource]["adaptive_score_ms"],) + tie_tail(resource),
        )
        reason = "minimum_bounded_queue_ewma_cost"
    else:
        raise PolicyContractError(f"unknown policy: {policy}")

    return {
        "evaluations": evaluations,
        "selected_resource": selected,
        "selected_implementation_id": evaluations[selected]["implementation_id"],
        "reason": reason,
    }


class PolicyEngine:
    """Deterministic per-arm policy state machine."""

    def __init__(
        self,
        *,
        policy: str,
        system: str,
        capability_manifest: Mapping[str, Any],
        static_hybrid_map: Mapping[str, Any] | None = None,
    ) -> None:
        _require_capabilities(capability_manifest)
        if policy not in POLICIES:
            raise PolicyContractError(f"unknown publication policy: {policy}")
        if system not in PUBLISHABLE_SYSTEMS:
            raise PolicyContractError(f"unknown publication system: {system}")
        if policy == "static_hybrid":
            self._static_placement = _validate_static_map(
                static_hybrid_map, system, capability_manifest
            )
            self._static_map_sha256 = str(static_hybrid_map["sha256"])
        elif static_hybrid_map is not None:
            raise PolicyContractError("static_hybrid_map is valid only for static_hybrid")
        else:
            self._static_placement = None
            self._static_map_sha256 = None
        self.policy = policy
        self.system = system
        self._capabilities = copy.deepcopy(dict(capability_manifest))
        self._contract_sha256 = policy_contract_identity()["sha256"]
        self._arm_id: str | None = None
        self._weights: dict[str, float] = {}
        self._service_ewma_ms: dict[str, dict[str, float]] = {}
        self._next_decision_seq = 1
        self._issued: dict[str, dict[str, Any]] = {}
        self._feedback_applied: set[str] = set()

    def reset(self, arm_id: str) -> None:
        if not _real_id(arm_id):
            raise PolicyContractError("arm_id must be a real stable ID")
        self._arm_id = arm_id
        self._weights = {resource: 1.0 for resource in RESOURCES}
        self._service_ewma_ms = {}
        self._next_decision_seq = 1
        self._issued = {}
        self._feedback_applied = set()

    def state_snapshot(self) -> dict[str, Any]:
        if self._arm_id is None:
            raise PolicyContractError("policy engine must be reset for an arm before use")
        return {
            "arm_id": self._arm_id,
            "weights": copy.deepcopy(self._weights),
            "service_ewma_ms": copy.deepcopy(self._service_ewma_ms),
        }

    def decide(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if self._arm_id is None:
            raise PolicyContractError("policy engine must be reset for an arm before use")
        normalized = _normalize_request(request, self.system, self._capabilities)
        if normalized["decision_seq"] != self._next_decision_seq:
            raise PolicyContractError("decision_seq is not contiguous within the arm")
        if normalized["decision_id"] in self._issued:
            raise PolicyContractError("decision_id was already emitted in this arm")
        state_before = self.state_snapshot()
        result = _evaluate_policy(
            self.policy,
            normalized,
            static_placement=self._static_placement,
            state_before=state_before,
        )
        payload = {
            "schema_version": DECISION_RECORD_SCHEMA_VERSION,
            "artifact_kind": "vast_publication_policy_decision",
            "policy_contract_sha256": self._contract_sha256,
            "engine_implementation_id": ENGINE_IMPLEMENTATION_ID,
            "policy_scope": POLICY_SCOPE,
            "policy": self.policy,
            "system": self.system,
            "arm_id": self._arm_id,
            "decision_id": normalized["decision_id"],
            "decision_seq": normalized["decision_seq"],
            "trace_id": normalized["trace_id"],
            "branch": normalized["branch"],
            "request": normalized,
            "state_before": state_before,
            "static_hybrid_map_sha256": self._static_map_sha256,
            "static_hybrid_placement": copy.deepcopy(self._static_placement),
            **result,
            "record_status": "replayable_not_runtime_accepted",
            "native_decision_evidence": None,
        }
        record = _payload_with_sha256(payload)
        self._issued[normalized["decision_id"]] = copy.deepcopy(record)
        self._next_decision_seq += 1
        return record

    def feedback(
        self,
        decision_record: Mapping[str, Any],
        *,
        actual_service_ms: float,
        completed_at_ms: float,
    ) -> dict[str, Any]:
        if self.policy != "adaptive_weights":
            raise PolicyContractError("feedback is defined only for adaptive_weights")
        if self._arm_id is None:
            raise PolicyContractError("policy engine must be reset for an arm before use")
        decision_id = str(decision_record.get("decision_id", ""))
        issued = self._issued.get(decision_id)
        if issued is None or issued.get("sha256") != decision_record.get("sha256"):
            raise PolicyContractError("feedback decision is not an issued arm decision")
        if decision_id in self._feedback_applied:
            raise PolicyContractError("feedback was already applied for this decision")
        actual = _positive(actual_service_ms, "actual_service_ms")
        completed = _nonnegative(completed_at_ms, "completed_at_ms")
        state_before = self.state_snapshot()
        branch = str(decision_record["branch"])
        resource = str(decision_record["selected_resource"])
        branch_state = self._service_ewma_ms.setdefault(branch, {})
        previous = branch_state.get(resource)
        branch_state[resource] = actual if previous is None else 0.1 * actual + 0.9 * previous
        deadline = float(decision_record["request"]["deadline_ms"])
        late = completed > deadline
        delta = 0.002 if late else -0.0002
        self._weights[resource] = min(1.5, max(0.5, self._weights[resource] + delta))
        state_after = self.state_snapshot()
        payload = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_feedback",
            "policy_contract_sha256": self._contract_sha256,
            "engine_implementation_id": ENGINE_IMPLEMENTATION_ID,
            "policy": self.policy,
            "system": self.system,
            "arm_id": self._arm_id,
            "decision_id": decision_id,
            "actual_service_ms": actual,
            "completed_at_ms": completed,
            "deadline_ms": deadline,
            "outcome": "late" if late else "on_time",
            "state_before": state_before,
            "state_after": state_after,
        }
        self._feedback_applied.add(decision_id)
        return _payload_with_sha256(payload)


def select_ready_task(policy: str, tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Select a ready task using the frozen policy-family ordering."""

    if policy not in POLICIES:
        raise PolicyContractError(f"unknown publication policy: {policy}")
    if not tasks:
        raise PolicyContractError("ready task set must not be empty")
    normalized: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    required = {"trace_id", "branch", "arrival_ms", "deadline_ms", "rank_u_ms"}
    for task in tasks:
        if not isinstance(task, Mapping) or not required.issubset(task):
            raise PolicyContractError("ready task fields are incomplete")
        trace_id = str(task.get("trace_id", ""))
        branch = str(task.get("branch", ""))
        if not _real_id(trace_id) or branch not in ANALYTICS_BRANCHES:
            raise PolicyContractError("ready task identity is invalid")
        normalized.append(
            (
                {
                    "trace_id": trace_id,
                    "branch": branch,
                    "arrival_ms": _nonnegative(task.get("arrival_ms"), "arrival_ms"),
                    "deadline_ms": _positive(task.get("deadline_ms"), "deadline_ms"),
                    "rank_u_ms": _nonnegative(task.get("rank_u_ms"), "rank_u_ms"),
                },
                task,
            )
        )
    if policy == "queue_aware_edf":
        key = lambda item: (
            item[0]["deadline_ms"],
            -item[0]["rank_u_ms"],
            item[0]["arrival_ms"],
            item[0]["trace_id"],
            item[0]["branch"],
        )
    elif policy in {"heft", "deadline_aware_heft", "adaptive_weights"}:
        key = lambda item: (
            -item[0]["rank_u_ms"],
            item[0]["deadline_ms"],
            item[0]["arrival_ms"],
            item[0]["trace_id"],
            item[0]["branch"],
        )
    else:
        key = lambda item: (
            item[0]["arrival_ms"],
            item[0]["deadline_ms"],
            item[0]["trace_id"],
            item[0]["branch"],
        )
    return copy.deepcopy(dict(min(normalized, key=key)[1]))


def _record_sha_blocker(record: Mapping[str, Any]) -> str | None:
    payload = dict(record)
    digest = payload.pop("sha256", None)
    if not _valid_sha256(digest) or _sha256(payload) != digest:
        return "decision_record_sha256_mismatch"
    return None


def replay_decision(
    record: Mapping[str, Any],
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Replay one decision solely from its frozen inputs and state snapshot."""

    blockers: list[str] = []
    if not isinstance(record, Mapping):
        blockers.append("decision_record_missing")
    else:
        sha_blocker = _record_sha_blocker(record)
        if sha_blocker:
            blockers.append(sha_blocker)
    capability_assessment = assess_capability_manifest(capability_manifest)
    if not capability_assessment["passed"]:
        blockers.extend(capability_assessment["blockers"])
    if blockers:
        return {"passed": False, "status": "blocked", "blockers": list(dict.fromkeys(blockers))}

    try:
        if record.get("schema_version") != DECISION_RECORD_SCHEMA_VERSION:
            raise PolicyContractError("decision record schema_version has drifted")
        if record.get("artifact_kind") != "vast_publication_policy_decision":
            raise PolicyContractError("decision record artifact_kind has drifted")
        if record.get("policy_contract_sha256") != policy_contract_identity()["sha256"]:
            raise PolicyContractError("decision record policy contract has drifted")
        if record.get("engine_implementation_id") != ENGINE_IMPLEMENTATION_ID:
            raise PolicyContractError("decision record engine implementation has drifted")
        if record.get("policy_scope") != POLICY_SCOPE:
            raise PolicyContractError("decision record policy_scope has drifted")
        policy = str(record.get("policy", ""))
        system = str(record.get("system", ""))
        if policy not in POLICIES or system not in PUBLISHABLE_SYSTEMS:
            raise PolicyContractError("decision policy/system is invalid")
        normalized = _normalize_request(record["request"], system, capability_manifest)
        if normalized["decision_id"] != record.get("decision_id"):
            raise PolicyContractError("decision_id does not match request")
        if normalized["trace_id"] != record.get("trace_id"):
            raise PolicyContractError("trace_id does not match request")
        if normalized["branch"] != record.get("branch"):
            raise PolicyContractError("branch does not match request")
        if normalized["decision_seq"] != record.get("decision_seq"):
            raise PolicyContractError("decision_seq does not match request")
        static_placement = record.get("static_hybrid_placement")
        if policy == "static_hybrid":
            if not isinstance(static_placement, Mapping):
                raise PolicyContractError("static_hybrid placement is missing from record")
            static_placement = {
                branch: str(static_placement[branch]) for branch in ANALYTICS_BRANCHES
            }
        elif static_placement is not None:
            raise PolicyContractError("non-static decision contains static placement")
        state_before = record.get("state_before")
        if not isinstance(state_before, Mapping):
            raise PolicyContractError("decision state_before is missing")
        expected = _evaluate_policy(
            policy,
            normalized,
            static_placement=static_placement,
            state_before=state_before,
        )
        actual = {
            "evaluations": record.get("evaluations"),
            "selected_resource": record.get("selected_resource"),
            "selected_implementation_id": record.get("selected_implementation_id"),
            "reason": record.get("reason"),
        }
        if _canonical_json(expected) != _canonical_json(actual):
            raise PolicyContractError("replayed decision does not match recorded output")
    except (KeyError, PolicyContractError) as exc:
        blockers.append(f"decision_replay_failed:{exc}")
    return {
        "passed": not blockers,
        "status": "replayed" if not blockers else "blocked",
        "blockers": blockers,
    }


def _native_evidence_blockers(
    record: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
    capability_manifest: Mapping[str, Any],
) -> list[str]:
    if not isinstance(evidence, Mapping):
        return ["native_decision_evidence_missing"]
    blockers: list[str] = []
    for field in (
        "event_id",
        "decision_id",
        "system",
        "branch",
        "selected_resource",
        "implementation_id",
        "emitter_id",
        "emitter_sha256",
        "telemetry_source",
    ):
        if field not in evidence:
            blockers.append(f"native_decision_evidence:{field}:missing")
    if blockers:
        return blockers
    if evidence.get("telemetry_source") != "native":
        blockers.append("native_decision_evidence:telemetry_source")
    if not _real_id(evidence.get("event_id")):
        blockers.append("native_decision_evidence:event_id")
    for field in ("decision_id", "system", "branch", "selected_resource"):
        if evidence.get(field) != record.get(field):
            blockers.append(f"native_decision_evidence:{field}")
    if evidence.get("implementation_id") != record.get("selected_implementation_id"):
        blockers.append("native_decision_evidence:implementation_id")
    resource = str(record.get("selected_resource", ""))
    system = str(record.get("system", ""))
    branch = str(record.get("branch", ""))
    if system in PUBLISHABLE_SYSTEMS and branch in ANALYTICS_BRANCHES and resource in RESOURCES:
        binding = _binding(capability_manifest, system, branch, resource)
        native = binding["native_evidence"]
        if evidence.get("emitter_id") != native["emitter_id"]:
            blockers.append("native_decision_evidence:emitter_id")
        if evidence.get("emitter_sha256") != native["emitter_sha256"]:
            blockers.append("native_decision_evidence:emitter_sha256")
    return blockers


def validate_decision_record(
    record: Mapping[str, Any],
    capability_manifest: Mapping[str, Any],
    *,
    require_native_evidence: bool = True,
) -> dict[str, Any]:
    replay = replay_decision(record, capability_manifest)
    blockers = list(replay["blockers"])
    if replay["passed"] and require_native_evidence:
        blockers.extend(
            _native_evidence_blockers(
                record,
                record.get("native_decision_evidence"),
                capability_manifest,
            )
        )
        if record.get("record_status") != "accepted_native_runtime_decision":
            blockers.append("decision_record_not_native_runtime_accepted")
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_decision_assessment",
        "passed": not blockers,
        "status": "accepted" if not blockers else "blocked",
        "blockers": blockers,
    }


def bind_native_decision_evidence(
    record: Mapping[str, Any],
    evidence: Mapping[str, Any],
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Return an accepted copy after exact native emitter/decision matching."""

    replay = replay_decision(record, capability_manifest)
    if not replay["passed"]:
        raise PolicyContractError("decision cannot bind native evidence: " + ", ".join(replay["blockers"]))
    blockers = _native_evidence_blockers(record, evidence, capability_manifest)
    if blockers:
        raise PolicyContractError("native evidence mismatch: " + ", ".join(blockers))
    payload = copy.deepcopy(dict(record))
    payload.pop("sha256", None)
    payload["record_status"] = "accepted_native_runtime_decision"
    payload["native_decision_evidence"] = copy.deepcopy(dict(evidence))
    accepted = _payload_with_sha256(payload)
    assessment = validate_decision_record(accepted, capability_manifest)
    if not assessment["passed"]:
        raise PolicyContractError(
            "bound native decision did not validate: " + ", ".join(assessment["blockers"])
        )
    return accepted
