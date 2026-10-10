#!/usr/bin/env python3
"""Q1 steps 14-15 on qualification transaction v2 outputs (Amendment 8).

Runs the stock policy/resource index builders, promotions and assessments with
the authority-v2 fragment validator that transaction v2 itself uses.  Before
any stock function runs, the exact transaction receipt, its fragments, the
index and the execution closure must bind to one another.  Host-only: not
imported by the execution code closure and not part of any image.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from checkpoint_qualification_pilot_acceptance_v1 import (
    QualificationPilotAcceptanceV1Error,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)
import full_resource_qualification as resource_qualification
import full_resource_qualification_index_v1 as resource_index
import publication_policy_qualification as policy_qualification
import publication_policy_qualification_fragments_from_authority_v2 as fragments_v2
import publication_policy_qualification_index_v2 as policy_index
import publication_policy_qualification_transaction_v2 as transaction_v2
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


SYSTEMS = transaction_v2.SYSTEMS
# Same exit code as other refused qualification gates (EX_CONFIG).
ASSESSMENT_BLOCKED_EXIT = 78


class PromotionV2Error(RuntimeError):
    """The transaction, fragments, index and closure do not bind exactly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionV2Error(message)


def _fragment_validator(system: str, fragment_path: Path, project_root: Path) -> dict[str, Any]:
    return fragments_v2.validate_publication_policy_qualification_fragment_from_authority_v2(
        system, fragment_path, project_root
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


def _descriptor(root: Path, value: Path | str, label: str) -> dict[str, Any]:
    try:
        return transaction_v2.file_descriptor(root, value)
    except (OSError, transaction_v2.QualificationTransactionV2Error) as error:
        raise PromotionV2Error(f"{label} is not one physical file under project_root: {error}") from error


def _read_json(root: Path, value: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor = _descriptor(root, value, label)
    try:
        parsed = json.loads((root / descriptor["path"]).read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromotionV2Error(f"{label} is not JSON") from error
    _require(type(parsed) is dict, f"{label} is not a JSON object")
    return descriptor, parsed


def _transaction(
    project_root: Path, receipt_path: Path, fragment_paths: Mapping[str, Path]
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Exact cold-validated transaction v2 whose fragments are the given files."""
    try:
        root = transaction_v2._root(project_root)
        path, receipt = transaction_v2._read_json(root, receipt_path, label="qualification transaction receipt")
        transaction_v2._require(
            receipt.get("schema_version") == transaction_v2.SCHEMA_VERSION
            and receipt.get("artifact_kind") == transaction_v2.TRANSACTION_KIND
            and receipt.get("receipt_sha256")
            == transaction_v2._self_sha(receipt, "receipt_sha256"),
            "qualification transaction receipt kind/self-hash drifted",
        )
        transaction_v2._cold_validate_committed_transaction(root=root, receipt_path=path)
    except (OSError, transaction_v2.QualificationTransactionV2Error) as error:
        raise PromotionV2Error(f"qualification transaction v2 refused: {error}") from error
    fragments = receipt.get("fragments")
    _require(
        type(fragments) is dict and set(fragments) == set(SYSTEMS) and set(fragment_paths) == set(SYSTEMS),
        "qualification transaction fragment coverage drifted",
    )
    for system in SYSTEMS:
        _require(
            _descriptor(root, fragment_paths[system], f"{system} fragment") == fragments[system],
            f"{system} fragment is not the transaction fragment",
        )
    return root, _descriptor(root, path, "qualification transaction receipt"), receipt


def _require_closure_transaction(
    root: Path,
    closure: Path | str,
    receipt_descriptor: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    expected_descriptor: Mapping[str, Any] | None = None,
) -> None:
    descriptor, value = _read_json(root, closure, "qualification execution closure receipt")
    if expected_descriptor is not None:
        _require(descriptor == dict(expected_descriptor), "index execution closure descriptor drifted")
    transaction = value.get("qualification_input_transaction")
    _require(
        type(transaction) is dict
        and transaction.get("receipt") == dict(receipt_descriptor)
        and transaction.get("receipt_sha256") == receipt["receipt_sha256"]
        and transaction.get("fragments") == receipt["fragments"],
        "execution closure does not bind this qualification transaction",
    )


def _index(root: Path, index_path: Path, label: str) -> dict[str, Any]:
    _descriptor_value, index = _read_json(root, index_path, label)
    closure = index.get("qualification_execution_closure")
    _require(type(closure) is dict and type(closure.get("path")) is str, f"{label} has no execution closure")
    _require(type(index.get("bindings")) is list and bool(index["bindings"]), f"{label} has no bindings")
    return index


def _require_policy_index(root: Path, index_path: Path, receipt_descriptor, receipt) -> None:
    index = _index(root, index_path, "policy qualification index")
    seen: set[str] = set()
    for row in index["bindings"]:
        system = row.get("system") if type(row) is dict else None
        _require(system in SYSTEMS, "policy index binding system drifted")
        _require(
            row.get("fragment_artifact") == receipt["fragments"][system],
            f"policy index {system} fragment_artifact is not the transaction fragment",
        )
        seen.add(system)
    _require(seen == set(SYSTEMS), "policy index fragment coverage drifted")
    _require_closure_transaction(
        root, index["qualification_execution_closure"]["path"], receipt_descriptor, receipt,
        expected_descriptor=index["qualification_execution_closure"],
    )


def _require_resource_index(
    root: Path, index_path: Path, fragment_paths: Mapping[str, Path], receipt_descriptor, receipt
) -> None:
    # Resource rows carry no fragment descriptor; each implementation artifact must be
    # exactly the binding file the (transaction-bound) fragment lists for it.
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for system in SYSTEMS:
        _descriptor_value, fragment = _read_json(root, fragment_paths[system], f"{system} fragment")
        for row in fragment.get("resource_bindings") or []:
            expected[(system, str(row.get("resource")))] = {
                "path": row.get("path"), "size_bytes": row.get("size"), "sha256": row.get("sha256"),
            }
    index = _index(root, index_path, "full-resource qualification index")
    seen: set[tuple[str, str]] = set()
    for row in index["bindings"]:
        key = (str(row.get("system")), str(row.get("resource"))) if type(row) is dict else ("", "")
        _require(
            key in expected and row.get("implementation_artifact") == expected[key],
            f"resource index binding {key} is not the transaction fragment binding",
        )
        seen.add(key)
    _require(seen == set(expected) and len(seen) == 8, "resource index fragment coverage drifted")
    _require_closure_transaction(
        root, index["qualification_execution_closure"]["path"], receipt_descriptor, receipt,
        expected_descriptor=index["qualification_execution_closure"],
    )


def _fragments(args: argparse.Namespace) -> dict[str, Path]:
    return {system: getattr(args, f"{system}_fragment") for system in SYSTEMS}


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _run(args: argparse.Namespace) -> int:
    fragment_paths = _fragments(args)
    root, receipt_descriptor, receipt = _transaction(
        args.project_root, args.qualification_transaction_receipt, fragment_paths
    )
    command = args.command
    if command in {"policy-index", "resource-index"}:
        _require_closure_transaction(root, args.execution_closure_receipt, receipt_descriptor, receipt)
        common = dict(
            project_root=root,
            fragment_paths=fragment_paths,
            pilot_root=args.pilot_root,
            fragment_validator=_fragment_validator,
            execution_closure_receipt_path=args.execution_closure_receipt,
        )
        if command == "policy-index":
            result = policy_index.build_policy_qualification_index_v2(output_dir=args.output_dir, **common)
            _print({key: str(value) for key, value in result.items()})
        else:
            _print(str(resource_index.build_full_resource_qualification_index_v1(output_path=args.output_path, **common)))
        return 0

    if command.startswith("policy-"):
        _require_policy_index(root, args.index_path, receipt_descriptor, receipt)
    else:
        _require_resource_index(root, args.index_path, fragment_paths, receipt_descriptor, receipt)
    if command == "policy-promote":
        _print(policy_qualification.promote_policy_qualification(
            project_root=root, index_path=args.index_path, output_dir=args.output_dir,
            pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator,
        ))
        return 0
    if command == "resource-promote":
        _print(resource_qualification.promote_full_resource_qualification(
            project_root=root, index_path=args.index_path, output_dir=args.output_dir,
        ))
        return 0
    if command == "policy-assess":
        assessment = policy_qualification.assess_policy_qualification(
            project_root=root, index_path=args.index_path,
            pilot_validator=policy_pilot_validator, fragment_validator=_fragment_validator,
        )
    else:
        assessment = resource_qualification.assess_full_resource_qualification(
            project_root=root, index_path=args.index_path,
        )
    _print(assessment)
    return 0 if type(assessment) is dict and assessment.get("passed") is True else ASSESSMENT_BLOCKED_EXIT


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name)
        sub.add_argument("--project-root", type=Path, required=True)
        sub.add_argument("--qualification-transaction-receipt", type=Path, required=True)
        for system in SYSTEMS:
            sub.add_argument(
                f"--{system.replace('_', '-')}-fragment", dest=f"{system}_fragment", type=Path, required=True
            )
        return sub

    for name, output in (("policy-index", "--output-dir"), ("resource-index", "--output-path")):
        sub = command(name)
        sub.add_argument("--pilot-root", type=Path, required=True)
        sub.add_argument("--execution-closure-receipt", type=Path, required=True)
        sub.add_argument(output, type=Path, required=True)
    for name in ("policy-promote", "resource-promote"):
        sub = command(name)
        sub.add_argument("--index-path", type=Path, required=True)
        sub.add_argument("--output-dir", type=Path, required=True)
    for name in ("policy-assess", "resource-assess"):
        command(name).add_argument("--index-path", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return _run(_parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ASSESSMENT_BLOCKED_EXIT", "PromotionV2Error", "main", "policy_pilot_validator"]
