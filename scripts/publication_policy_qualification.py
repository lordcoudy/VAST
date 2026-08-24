#!/usr/bin/env python3
"""Evidence-driven promotion of native policy capabilities and calibration.

The qualification index is only an inventory.  Proof is obtained by re-hashing
physical artifacts, re-validating accepted pilot bundles, and deriving the
capability/calibration outputs from native observations.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping, Sequence

from checkpoint_acceptance_metadata_binding import (
    AcceptanceMetadataBindingError,
    validate_checkpoint_acceptance_metadata_binding_envelope,
)


QUALIFICATION_INDEX_SCHEMA_VERSION = 1
QUALIFICATION_ASSESSMENT_SCHEMA_VERSION = 1
QUALIFICATION_RECEIPT_SCHEMA_VERSION = 1
CAPABILITY_MANIFEST_FILENAME = "checkpoint_policy_capability_manifest.json"
CALIBRATION_MAPPING_FILENAME = "checkpoint_policy_calibration_mapping.json"
QUALIFICATION_RECEIPT_FILENAME = "checkpoint_policy_qualification_receipt.json"
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
PILOT_EVIDENCE_ROLES = (
    "checkpoint_acceptance", "policy_decisions_jsonl", "resource_intervals",
    "ingress_ledger", "topology_events", "frames", "frame_events", "branch_terminals",
)
_SHA256_CHARS = frozenset("0123456789abcdef")
_RUNTIME_IDENTITY_FIELDS = {
    "runtime_backend", "device_api", "worker_image_digest", "implementation_version",
}


class QualificationError(RuntimeError):
    """A qualification input, evidence bundle, or immutable output is unsafe."""


PilotValidator = Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


def _load_policy_contract() -> Any:
    # Keep heavy benchmark dependencies lazy.  Fail-early evidence checks and
    # pure orchestration tests do not require pandas/PyYAML at import time.
    import publication_policy_contract as policy_contract

    return policy_contract


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError("qualification artifact is not canonical JSON") from exc


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value: Any) -> bool:
    text = str(value)
    return len(text) == 64 and set(text) <= _SHA256_CHARS


def _stable_id(value: Any) -> bool:
    text = str(value)
    return len(text) >= 8 and text == text.strip() and not any(ch in "\r\n\x00" for ch in text)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise QualificationError(f"{label} must be a JSON object")
    return value


def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise QualificationError(f"artifact stat failed: {path}: {exc}") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _resolve_relative_regular_file(project_root: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise QualificationError(f"{label} path must be a non-empty POSIX relative path")
    relative = Path(value)
    if relative.is_absolute() or value != relative.as_posix() or any(part in ("", ".", "..") for part in relative.parts):
        raise QualificationError(f"{label} path escapes or is not normalized: {value!r}")
    root = project_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_reparse_or_link(cursor):
            raise QualificationError(f"{label} path contains a symlink/reparse point: {value}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QualificationError(f"{label} path escapes project root: {value}") from exc
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise QualificationError(f"{label} is not a regular file: {value}")
    return candidate


def _verify_descriptor(project_root: Path, descriptor: Any, label: str, *, forbid_hardlinks: bool) -> dict[str, Any]:
    if type(descriptor) is not dict or set(descriptor) != {"path", "size_bytes", "sha256"}:
        raise QualificationError(f"{label} artifact descriptor fields drifted")
    expected_size = descriptor.get("size_bytes")
    expected_sha = descriptor.get("sha256")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
        raise QualificationError(f"{label} artifact size is invalid")
    if not _valid_sha(expected_sha):
        raise QualificationError(f"{label} artifact SHA-256 is invalid")
    path = _resolve_relative_regular_file(project_root, descriptor.get("path"), label)
    before = path.stat()
    if forbid_hardlinks and int(before.st_nlink) != 1:
        raise QualificationError(f"{label} hardlink alias is prohibited")
    digest = _sha256_file(path)
    after = path.stat()
    before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, int(getattr(before, "st_ctime_ns", 0)))
    after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, int(getattr(after, "st_ctime_ns", 0)))
    if before_id != after_id:
        raise QualificationError(f"{label} artifact changed while hashing")
    if before.st_size != expected_size or digest != expected_sha:
        raise QualificationError(f"{label} artifact size/SHA drift")
    return {
        "path": descriptor["path"], "size_bytes": expected_size, "sha256": digest,
        "filesystem_identity": (int(before.st_dev), int(before.st_ino)),
    }


def _binding_key(value: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(value.get("system", "")), str(value.get("branch", "")), str(value.get("resource", "")))


def _pilot_key(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (str(value.get("system", "")), str(value.get("resource", "")), str(value.get("codec", "")), str(value.get("topology_kind", "")))


def _derive_manifest(bindings: Sequence[Any], *, project_root: Path, policy: Any) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
    branches = tuple(policy.ANALYTICS_BRANCHES)
    resources = tuple(policy.RESOURCES)
    expected = {(system, branch, resource) for system in systems for branch in branches for resource in resources}
    if not isinstance(bindings, list) or len(bindings) != len(expected):
        raise QualificationError("binding set must contain exactly 32 system/branch/resource rows")
    observed: dict[tuple[str, str, str], dict[str, Any]] = {}
    path_aliases: set[str] = set()
    inode_aliases: set[tuple[int, int]] = set()
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()
    for position, raw in enumerate(bindings):
        if type(raw) is not dict:
            raise QualificationError(f"binding[{position}] must be an object")
        required = {
            "system", "branch", "resource", "implementation_id", "implementation_artifact",
            "emitter_id", "emitter_artifact", "runtime_binding", "runtime_identity",
        }
        if set(raw) != required:
            raise QualificationError(f"binding[{position}] fields drifted")
        key = _binding_key(raw)
        if key not in expected or key in observed:
            raise QualificationError(f"binding coverage duplicate/unknown: {key}")
        implementation_id = str(raw["implementation_id"])
        emitter_id = str(raw["emitter_id"])
        runtime_binding = str(raw["runtime_binding"])
        if not all(_stable_id(value) for value in (implementation_id, emitter_id, runtime_binding)):
            raise QualificationError(f"binding {key} contains a placeholder/unstable runtime identity")
        if implementation_id in implementation_ids or emitter_id in emitter_ids:
            raise QualificationError(f"binding {key} implementation/emitter identity is not unique")
        implementation_ids.add(implementation_id)
        emitter_ids.add(emitter_id)
        runtime_identity = raw["runtime_identity"]
        if type(runtime_identity) is not dict or set(runtime_identity) != _RUNTIME_IDENTITY_FIELDS:
            raise QualificationError(f"binding {key} runtime_identity fields drifted")
        if not all(_stable_id(runtime_identity[field]) for field in _RUNTIME_IDENTITY_FIELDS):
            raise QualificationError(f"binding {key} runtime_identity is incomplete")
        image = str(runtime_identity["worker_image_digest"])
        if not image.startswith("sha256:") or not _valid_sha(image[7:]):
            raise QualificationError(f"binding {key} worker image digest is invalid")
        artifacts = []
        for role in ("implementation_artifact", "emitter_artifact"):
            verified = _verify_descriptor(project_root, raw[role], f"binding {key} {role}", forbid_hardlinks=True)
            if verified["path"] in path_aliases or verified["filesystem_identity"] in inode_aliases:
                raise QualificationError(f"binding {key} artifact alias is prohibited")
            path_aliases.add(verified["path"])
            inode_aliases.add(verified["filesystem_identity"])
            artifacts.append(verified)
        implementation, emitter = artifacts
        observed[key] = {
            "status": "implemented_and_native_evidence_bound",
            "implementation_id": implementation_id,
            "implementation_sha256": implementation["sha256"],
            "runtime_binding": runtime_binding,
            "runtime_identity": dict(runtime_identity),
            "native_evidence": {
                "status": "accepted_native_runtime_emitter",
                "telemetry_source": "native",
                "emitter_id": emitter_id,
                "emitter_sha256": emitter["sha256"],
                "implementation_id_field": "implementation_id",
                "resource_field": "selected_resource",
            },
        }
    if set(observed) != expected:
        raise QualificationError("binding_cell_set_mismatch")
    manifest = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_capability_manifest",
        "policy_scope": policy.POLICY_SCOPE,
        "policy_contract_sha256": policy.policy_contract_identity()["sha256"],
        "systems": {
            system: {"branches": {
                branch: {resource: observed[(system, branch, resource)] for resource in resources}
                for branch in branches
            }} for system in systems
        },
    }
    assessment = policy.assess_capability_manifest(manifest)
    if not assessment.get("passed"):
        raise QualificationError("derived capability manifest rejected: " + ", ".join(assessment.get("blockers", [])[:8]))
    return manifest, observed


def _validate_evidence_descriptors(project_root: Path, pilot: Mapping[str, Any]) -> dict[str, Path]:
    evidence = pilot.get("evidence")
    if type(evidence) is not dict or set(evidence) != set(PILOT_EVIDENCE_ROLES):
        raise QualificationError("pilot raw evidence descriptor set drifted")
    verified: dict[str, Path] = {}
    paths: set[str] = set()
    inodes: set[tuple[int, int]] = set()
    for role in PILOT_EVIDENCE_ROLES:
        descriptor = _verify_descriptor(project_root, evidence[role], f"pilot {role}", forbid_hardlinks=True)
        if descriptor["path"] in paths or descriptor["filesystem_identity"] in inodes:
            raise QualificationError(f"pilot evidence alias is prohibited: {role}")
        paths.add(descriptor["path"])
        inodes.add(descriptor["filesystem_identity"])
        verified[role] = project_root / descriptor["path"]
    parents = {path.parent.resolve(strict=True) for path in verified.values()}
    if len(parents) != 1:
        raise QualificationError("pilot evidence files must share one accepted arm directory")
    return verified


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as source:
            for number, line in enumerate(source, start=1):
                if not line.strip():
                    raise QualificationError(f"{path}:{number}: blank JSONL records are prohibited")
                value = json.loads(line)
                if type(value) is not dict:
                    raise QualificationError(f"{path}:{number}: decision record must be an object")
                records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid native decision JSONL: {exc}") from exc
    if not records:
        raise QualificationError("native decision JSONL is empty")
    return records


def _default_pilot_validator(pilot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    project_root = Path(context["project_root"])
    manifest = context["capability_manifest"]
    policy = context["policy"]
    paths = _validate_evidence_descriptors(project_root, pilot)
    acceptance = _load_json_object(paths["checkpoint_acceptance"], "checkpoint acceptance")
    expected_identity = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_acceptance",
        "status": "accepted_native_checkpoint_arm",
        "system": pilot["system"],
        "codec": pilot["codec"],
        "topology_kind": pilot["topology_kind"],
        "policy": "cpu_only" if pilot["resource"] == "cpu" else "gpu_only",
        "execution_binding_provenance": "native_scheduler_execution_binding_v1",
    }
    for field, expected in expected_identity.items():
        if acceptance.get(field) != expected:
            raise QualificationError(f"checkpoint acceptance identity drift: {field}")
    try:
        validate_checkpoint_acceptance_metadata_binding_envelope(acceptance)
    except AcceptanceMetadataBindingError as exc:
        raise QualificationError(
            f"checkpoint acceptance metadata binding is invalid: {exc}"
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
    finalization = acceptance.get("acceptance_finalization")
    if finalization != {
        "hardware_collector_stopped": True,
        "validation": "full_resource_evidence_v2_passed",
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
                "contract_version": 1,
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
            require_full_resource_evidence=True,
            expected_run_id=str(run_id),
            frames=frames,
            topology_events=topology_events,
        )
        dataset_manifest = project_root / context["dataset_manifest"]["path"]
        dataset = load_dataset(
            dataset_manifest,
            f"kpp_real_{pilot['codec']}",
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

    samples = []
    seen_decisions: set[str] = set()
    seen_events: set[str] = set()
    for record in decisions:
        decision_id = str(record.get("decision_id", ""))
        trace_id = str(record.get("trace_id", ""))
        branch = str(record.get("branch", ""))
        resource = str(record.get("selected_resource", ""))
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
            raise QualificationError("GPU qualification sample lacks native transfer interval")
        samples.append({
            "system": pilot["system"], "resource": resource, "codec": pilot["codec"],
            "topology_kind": pilot["topology_kind"], "branch": branch,
            "decision_id": decision_id, "trace_id": trace_id,
            "service_ms": float(service_ms), "transfer_ms": float(transfer_ms),
        })
    return samples


def _validate_samples(
    rows: Any,
    *,
    pilot_key: tuple[str, str, str, str],
    branches: Sequence[str],
    minimum_samples: int,
    global_decisions: set[str],
    global_traces: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise QualificationError(f"pilot {pilot_key} validator did not return a sample list")
    expected_fields = {
        "system", "resource", "codec", "topology_kind", "branch",
        "decision_id", "trace_id", "service_ms", "transfer_ms",
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position, row in enumerate(rows):
        if type(row) is not dict or set(row) != expected_fields:
            raise QualificationError(f"pilot {pilot_key} sample[{position}] fields drifted")
        if (row["system"], row["resource"], row["codec"], row["topology_kind"]) != pilot_key:
            raise QualificationError(f"pilot {pilot_key} sample escaped its cell")
        branch = str(row["branch"])
        decision_id = str(row["decision_id"])
        trace_id = str(row["trace_id"])
        if branch not in branches or not _stable_id(decision_id) or not _stable_id(trace_id):
            raise QualificationError(f"pilot {pilot_key} sample identity is invalid")
        trace_key = (pilot_key[0], trace_id, branch)
        if decision_id in global_decisions or trace_key in global_traces:
            raise QualificationError(f"pilot {pilot_key} contains duplicate decision/trace sample")
        global_decisions.add(decision_id)
        global_traces.add(trace_key)
        for field, positive in (("service_ms", True), ("transfer_ms", False)):
            value = row[field]
            invalid = (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                or (positive and float(value) <= 0)
            )
            if invalid:
                raise QualificationError(f"pilot {pilot_key} sample {field} is invalid")
        grouped[branch].append(dict(row))
    if set(grouped) != set(branches):
        raise QualificationError(f"pilot {pilot_key} branch coverage mismatch")
    for branch in branches:
        if len(grouped[branch]) < minimum_samples:
            raise QualificationError(f"pilot {pilot_key}/{branch} requires at least {minimum_samples} accepted samples")
    return [row for branch in branches for row in grouped[branch]]


def _assessment_failure(blockers: list[str], *, index_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_policy_qualification_assessment",
        "passed": False,
        "status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "index_sha256": index_sha,
        "coverage": {"binding_count": 0, "pilot_cell_count": 0, "accepted_sample_count": 0},
        "capability_manifest": None,
        "calibration_mapping": None,
    }


def assess_policy_qualification(
    *,
    project_root: Path,
    index_path: Path,
    pilot_validator: PilotValidator | None = None,
) -> dict[str, Any]:
    """Purely assess and derive qualification artifacts; never write output."""
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir() or _is_reparse_or_link(root):
            raise QualificationError("project_root must be a physical non-reparse directory")
        index_candidate = Path(index_path)
        if index_candidate.is_absolute():
            try:
                relative_index = index_candidate.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise QualificationError("qualification index must remain under project_root") from exc
        else:
            relative_index = index_candidate.as_posix()
        index_file = _resolve_relative_regular_file(root, relative_index, "qualification index")
        index_sha = _sha256_file(index_file)
        index = _load_json_object(index_file, "qualification index")
        expected_fields = {
            "schema_version", "artifact_kind", "policy_contract_sha256",
            "dataset_manifest", "bindings", "pilots",
        }
        schema_ok = (
            set(index) == expected_fields
            and index.get("schema_version") == QUALIFICATION_INDEX_SCHEMA_VERSION
            and index.get("artifact_kind") == "vast_publication_policy_qualification_index"
        )
        if not schema_ok:
            raise QualificationError("qualification index schema/fields drifted")
        policy = _load_policy_contract()
        contract_sha = policy.policy_contract_identity()["sha256"]
        if index.get("policy_contract_sha256") != contract_sha:
            raise QualificationError("qualification index policy contract SHA-256 drifted")
        dataset = _verify_descriptor(root, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
        manifest, bindings = _derive_manifest(index["bindings"], project_root=root, policy=policy)
        expected_pilots = {
            (system, resource, codec, topology)
            for system in policy.PUBLISHABLE_SYSTEMS
            for resource in policy.RESOURCES
            for codec in CODECS
            for topology in TOPOLOGIES
        }
        pilots = index["pilots"]
        if not isinstance(pilots, list) or len(pilots) != len(expected_pilots):
            raise QualificationError("pilot_cell_set_mismatch: expected exactly 32 pilots")
        by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for position, raw in enumerate(pilots):
            if type(raw) is not dict or set(raw) != {"system", "resource", "codec", "topology_kind", "evidence"}:
                raise QualificationError(f"pilot[{position}] fields drifted")
            key = _pilot_key(raw)
            if key not in expected_pilots or key in by_key:
                raise QualificationError(f"pilot_cell_set_mismatch: duplicate/unknown {key}")
            by_key[key] = raw
        if set(by_key) != expected_pilots:
            raise QualificationError("pilot_cell_set_mismatch")
        validator = pilot_validator or _default_pilot_validator
        samples: list[dict[str, Any]] = []
        global_decisions: set[str] = set()
        global_traces: set[tuple[str, str, str]] = set()
        for key in sorted(expected_pilots):
            raw_rows = validator(by_key[key], {
                "project_root": root,
                "policy": policy,
                "capability_manifest": manifest,
                "bindings": bindings,
                "dataset_manifest": dataset,
            })
            samples.extend(_validate_samples(
                raw_rows,
                pilot_key=key,
                branches=tuple(policy.ANALYTICS_BRANCHES),
                minimum_samples=int(policy.MIN_CALIBRATION_SAMPLES),
                global_decisions=global_decisions,
                global_traces=global_traces,
            ))
        calibrations: dict[str, Any] = {}
        for system in policy.PUBLISHABLE_SYSTEMS:
            costs = {}
            for branch in policy.ANALYTICS_BRANCHES:
                costs[branch] = {}
                for resource in policy.RESOURCES:
                    selected = [
                        row for row in samples
                        if row["system"] == system and row["branch"] == branch and row["resource"] == resource
                    ]
                    balanced_minimum = len(CODECS) * len(TOPOLOGIES) * int(policy.MIN_CALIBRATION_SAMPLES)
                    if len(selected) < balanced_minimum:
                        raise QualificationError(f"calibration coverage below balanced minimum: {system}/{branch}/{resource}")
                    costs[branch][resource] = {
                        "implementation_id": bindings[(system, branch, resource)]["implementation_id"],
                        "service_ms": float(median(row["service_ms"] for row in selected)),
                        "transfer_ms": float(median(row["transfer_ms"] for row in selected)),
                        "samples": len(selected),
                    }
            calibrations[system] = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": contract_sha,
                "costs": costs,
            }
        calibration_mapping = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration_mapping",
            "policy_contract_sha256": contract_sha,
            "aggregation_rule": "median_of_balanced_native_codec_topology_cells_v1",
            "minimum_samples_per_branch_cell": int(policy.MIN_CALIBRATION_SAMPLES),
            "calibrations": calibrations,
        }
        return {
            "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
            "artifact_kind": "vast_publication_policy_qualification_assessment",
            "passed": True,
            "status": "ready_for_atomic_promotion",
            "blockers": [],
            "index_sha256": index_sha,
            "dataset_manifest_sha256": dataset["sha256"],
            "coverage": {
                "binding_count": len(bindings),
                "pilot_cell_count": len(by_key),
                "accepted_sample_count": len(samples),
                "minimum_samples_per_branch_cell": int(policy.MIN_CALIBRATION_SAMPLES),
            },
            "capability_manifest": manifest,
            "calibration_mapping": calibration_mapping,
        }
    except QualificationError as exc:
        return _assessment_failure([str(exc)], index_sha=locals().get("index_sha"))
    except Exception as exc:
        return _assessment_failure([f"qualification validation failed closed: {exc}"], index_sha=locals().get("index_sha"))


def _write_immutable_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if _is_reparse_or_link(path) or not path.is_file() or path.read_bytes() != payload:
            raise QualificationError(f"immutable qualification output collision: {path.name}")
        return {"path": path.name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_descriptor = None
            try:
                directory_descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                os.fsync(directory_descriptor)
            except OSError:
                pass
            finally:
                if directory_descriptor is not None:
                    os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": path.name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def promote_policy_qualification(
    *,
    project_root: Path,
    index_path: Path,
    output_dir: Path,
    pilot_validator: PilotValidator | None = None,
) -> dict[str, Any]:
    """Emit two derived artifacts and commit an immutable receipt last."""
    assessment = assess_policy_qualification(
        project_root=project_root, index_path=index_path, pilot_validator=pilot_validator,
    )
    if not assessment["passed"]:
        raise QualificationError("policy qualification is blocked: " + ", ".join(assessment["blockers"][:8]))
    root = Path(project_root).resolve(strict=True)
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = root / destination
    resolved_parent = destination.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise QualificationError("qualification output_dir must remain under project_root") from exc
    if destination.exists() and (_is_reparse_or_link(destination) or not destination.is_dir()):
        raise QualificationError("qualification output_dir must be a physical directory")
    destination.mkdir(parents=True, exist_ok=True)
    capability_descriptor = _write_immutable_json(
        destination / CAPABILITY_MANIFEST_FILENAME, assessment["capability_manifest"],
    )
    calibration_descriptor = _write_immutable_json(
        destination / CALIBRATION_MAPPING_FILENAME, assessment["calibration_mapping"],
    )
    receipt = {
        "schema_version": QUALIFICATION_RECEIPT_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_policy_qualification_receipt",
        "status": "accepted_evidence_driven_policy_qualification",
        "policy_contract_sha256": assessment["capability_manifest"]["policy_contract_sha256"],
        "qualification_index_sha256": assessment["index_sha256"],
        "dataset_manifest_sha256": assessment["dataset_manifest_sha256"],
        "coverage": assessment["coverage"],
        "outputs": {
            "capability_manifest": capability_descriptor,
            "calibration_mapping": calibration_descriptor,
        },
    }
    receipt["sha256"] = _canonical_sha(receipt)
    _write_immutable_json(destination / QUALIFICATION_RECEIPT_FILENAME, receipt)
    return {"passed": True, "status": "promoted", "receipt": receipt, "output_dir": str(destination)}


__all__ = [
    "CAPABILITY_MANIFEST_FILENAME",
    "CALIBRATION_MAPPING_FILENAME",
    "QUALIFICATION_RECEIPT_FILENAME",
    "QualificationError",
    "assess_policy_qualification",
    "promote_policy_qualification",
]
