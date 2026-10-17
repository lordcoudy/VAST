#!/usr/bin/env python3
"""Reviewed authority-v2 pilot validation shared by host and runtime consumers."""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from checkpoint_qualification_pilot_acceptance_v1 import (
    QualificationPilotAcceptanceV1Error,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)
from publication_policy_qualification import (
    KPP_DATASET_BY_CODEC,
    QualificationError,
    _read_jsonl,
    _sha256_file,
    _stable_id,
    _valid_sha,
    _validate_evidence_descriptors,
    _verify_descriptor,
)


# Amendment 9 (F5): textual copy of publication_policy_qualification._default_pilot_validator
# (closure-pinned, unchanged) with two reviewed changes, diff-locked by
# tests/test_publication_qualification_policy_pilot_validator_v2.py: sidecars are revalidated with
# reset evidence and six streams, as in the resource validator; a GPU decision of a frame dropped
# at ingress has no resource intervals and is fully checked but is not a calibration sample.
def policy_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    project_root = Path(context["project_root"])
    manifest = context["capability_manifest"]
    policy = context["policy"]
    paths = _validate_evidence_descriptors(project_root, pilot)
    expected_identity = {
        "policy": "cpu_only" if pilot["resource"] == "cpu" else "gpu_only",
    }
    try:
        acceptance = validate_checkpoint_qualification_pilot_acceptance_v1(
            project_root=project_root,
            acceptance_path=paths["checkpoint_acceptance"],
            expected_system=pilot["system"],
            expected_resource=pilot["resource"],
            expected_codec=pilot["codec"],
            expected_topology_kind=pilot["topology_kind"],
        )
    except QualificationPilotAcceptanceV1Error as exc:
        raise QualificationError(
            f"checkpoint acceptance is not a qualification pilot: {exc}"
        ) from exc
    run_id = acceptance.get("run_id")
    if not _stable_id(run_id):
        raise QualificationError("checkpoint acceptance run_id is invalid")
    expected_scenario = (
        "checkpoint_independent_processes_baseline"
        if pilot["topology_kind"] == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    if acceptance.get("scenario") != expected_scenario:
        raise QualificationError("checkpoint acceptance scenario/topology mismatch")
    evidence_hashes = acceptance.get("evidence_sha256")
    if type(evidence_hashes) is not dict:
        raise QualificationError("checkpoint acceptance evidence hashes are missing")
    from publication_acceptance_evidence import accepted_arm_evidence_files

    required_acceptance_files = set(
        accepted_arm_evidence_files(
            expected_identity["policy"],
            full_resource=True,
            runtime_history="publication_policy_runtime_history.jsonl" in evidence_hashes,
        )
    )
    if set(evidence_hashes) != required_acceptance_files:
        raise QualificationError("checkpoint acceptance evidence hash set drifted")
    arm_root = paths["checkpoint_acceptance"].parent
    for filename, expected_sha in evidence_hashes.items():
        if type(filename) is not str or Path(filename).name != filename or not _valid_sha(expected_sha):
            raise QualificationError("checkpoint acceptance contains an unsafe evidence identity")
        current = arm_root / filename
        try:
            relative = current.relative_to(project_root).as_posix()
            size = current.stat().st_size
        except (OSError, ValueError) as exc:
            raise QualificationError(f"checkpoint acceptance evidence is missing: {filename}") from exc
        _verify_descriptor(
            project_root,
            {"path": relative, "size_bytes": size, "sha256": expected_sha},
            f"checkpoint acceptance {filename}",
            forbid_hardlinks=True,
        )
    acceptance_roles = {
        "resource_intervals": "resource_intervals.csv",
        "ingress_ledger": "ingress_ledger.csv",
        "topology_events": "topology_events.csv",
        "frames": "frames.csv",
        "frame_events": "frame_events.csv",
        "branch_terminals": "branch_terminals.csv",
    }
    for role, filename in acceptance_roles.items():
        if paths[role].name != filename or evidence_hashes.get(filename) != _sha256_file(paths[role]):
            raise QualificationError(f"checkpoint acceptance does not bind current {filename}")
    summary = acceptance.get("full_resource_summary")
    if type(summary) is not dict or not all(
        summary.get(field) is True
        for field in ("evidence_accepted", "publication_bundle_bound", "full_resource_coverage_complete")
    ):
        raise QualificationError("checkpoint acceptance full-resource proof is not accepted")
    finalization = acceptance.get("full_resource_finalization")
    if finalization != {
        "hardware_collector_stopped": True,
        "validation": "full_resource_evidence_v2_passed",
        "prepared_by": "prepare_checkpoint_publication_acceptance",
    }:
        raise QualificationError("checkpoint acceptance finalization proof drifted")

    # Re-run complete sidecar validators; receipt hashes alone are not proof.
    try:
        from benchmark_contract import (
            canonicalize_frames_csv, load_dataset, validate_frame_events,
            validate_required_sidecars,
        )
        from topology_contract import validate_topology_events

        frames = canonicalize_frames_csv(paths["frames"], mode="benchmark", run_id="", detector="", backend="")
        frame_events = validate_frame_events(paths["frame_events"])
        scenario = {
            "name": expected_scenario,
            "workload": {
                "routing_mode": "all_branches_per_stream",
                "analytics_function_types": len(policy.ANALYTICS_BRANCHES),
            },
            "topology": {
                "contract_version": 2,
                "kind": pilot["topology_kind"],
                "routing_mode": "all_branches_per_stream",
                "required_branches": list(policy.ANALYTICS_BRANCHES),
            },
        }
        topology_events = validate_topology_events(
            paths["topology_events"], frames=frames, frame_events=frame_events, scenario=scenario,
        )
        sidecars = validate_required_sidecars(
            paths["frames"].parent,
            require_labeled_provenance=True,
            require_full_policy_trace=True,
            require_causal_policy_trace=True,
            require_ingress_ledger=True,
            require_branch_terminals=True,
            required_branches=list(policy.ANALYTICS_BRANCHES),
            topology_kind=pilot["topology_kind"],
            require_reset_evidence=True,
            expected_streams=6,
            require_full_resource_evidence=True,
            expected_run_id=str(run_id),
            frames=frames,
            topology_events=topology_events,
        )
        dataset_manifest = project_root / context["dataset_manifest"]["path"]
        dataset = load_dataset(
            dataset_manifest,
            KPP_DATASET_BY_CODEC[pilot["codec"]],
            mode="benchmark",
            project_root=project_root,
            require_files=True,
        )
        expected_sources = {str(stream["resolved_sha256"]) for stream in dataset["streams"]}
        observed_sources = set(sidecars["ingress_ledger"]["source_sha256"].astype(str))
        if observed_sources != expected_sources:
            raise QualificationError("pilot ingress is not bound to the frozen KPP codec dataset")
    except QualificationError:
        raise
    except Exception as exc:
        raise QualificationError(f"pilot sidecar revalidation failed: {exc}") from exc

    decisions = _read_jsonl(paths["policy_decisions_jsonl"])
    policy_rows = sidecars["policy_decisions"]
    intervals = sidecars["resource_intervals"]
    terminals = sidecars["branch_terminals"]
    policy_by_decision = {str(row["decision_id"]): row for row in policy_rows.to_dict(orient="records")}
    if len(policy_by_decision) != len(policy_rows):
        raise QualificationError("policy_decisions.csv contains duplicate decision_id")
    terminal_keys = {
        (str(row["trace_id"]), str(row["branch_id"]))
        for row in terminals.to_dict(orient="records")
        if str(row["terminal_status"]) == "completed"
    }
    transfer_by_key: dict[tuple[str, str], float] = defaultdict(float)
    for row in intervals.to_dict(orient="records"):
        if str(row["component"]) == "transfer":
            transfer_by_key[(str(row["trace_id"]), str(row["branch_id"]))] += float(row["duration_ns"]) / 1_000_000.0
    ingress_status = {
        str(row["trace_id"]): str(row["terminal_status"])
        for row in sidecars["ingress_ledger"].to_dict(orient="records")
    }

    samples = []
    seen_decisions: set[str] = set()
    seen_events: set[str] = set()
    for record in decisions:
        decision_id = str(record.get("decision_id", ""))
        trace_id = str(record.get("trace_id", ""))
        branch = str(record.get("branch", ""))
        resource = str(record.get("selected_resource", ""))
        if "publication_projection" in record:
            from publication_policy_projection_v1 import reconstruct_original_decision_v1
            try:
                original_accepted, _original_issued = reconstruct_original_decision_v1(record)
            except (ValueError, TypeError, KeyError) as exc:
                raise QualificationError(f"native decision original reconstruction failed: {exc}") from exc
            assessment = policy.validate_decision_record(original_accepted, manifest)
        else:
            assessment = policy.validate_decision_record(record, manifest)
        if not assessment.get("passed"):
            raise QualificationError("accepted native decision replay failed: " + ", ".join(assessment.get("blockers", [])[:6]))
        if record.get("system") != pilot["system"] or resource != pilot["resource"] or branch not in policy.ANALYTICS_BRANCHES:
            raise QualificationError("native decision does not belong to the declared pilot cell")
        evidence = record.get("native_decision_evidence")
        if type(evidence) is not dict:
            raise QualificationError("native decision evidence is missing")
        event_id = str(evidence.get("event_id", ""))
        if decision_id in seen_decisions or event_id in seen_events:
            raise QualificationError("duplicate native decision/event sample")
        seen_decisions.add(decision_id)
        seen_events.add(event_id)
        row = policy_by_decision.get(decision_id)
        if row is None or str(row["trace_id"]) != trace_id or str(row["stage"]) != branch or str(row["resource"]) != resource:
            raise QualificationError("native decision JSONL/CSV linkage mismatch")
        if (trace_id, branch) not in terminal_keys:
            raise QualificationError("native decision lacks accepted branch terminal linkage")
        service_ms = evidence.get("actual_service_ms")
        if isinstance(service_ms, bool) or not isinstance(service_ms, (int, float)) or not math.isfinite(float(service_ms)) or float(service_ms) <= 0:
            raise QualificationError("native decision actual_service_ms is invalid")
        transfer_ms = transfer_by_key.get((trace_id, branch), 0.0)
        if resource == "gpu" and transfer_ms <= 0:
            if ingress_status.get(trace_id) == "drop":
                continue
            raise QualificationError("GPU qualification sample lacks native transfer interval")
        samples.append({
            "system": pilot["system"], "resource": resource, "codec": pilot["codec"],
            "topology_kind": pilot["topology_kind"], "branch": branch,
            "decision_id": decision_id, "trace_id": trace_id,
            "service_ms": float(service_ms), "transfer_ms": float(transfer_ms),
        })
    return samples


__all__ = ["policy_pilot_validator"]
