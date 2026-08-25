#!/usr/bin/env python3
"""Evidence-driven pre-run FULL-RESOURCE v2 capability qualification.

The receipt produced here is not an acceptance for any target arm.  Each arm
must still emit and pass its own resource-v2 evidence after it runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Mapping

from checkpoint_qualification_pilot_acceptance_v1 import (
    QualificationPilotAcceptanceV1Error,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)


QUALIFICATION_INDEX_SCHEMA_VERSION = 1
QUALIFICATION_ASSESSMENT_SCHEMA_VERSION = 1
QUALIFICATION_RECEIPT_SCHEMA_VERSION = 1
CAPABILITY_MANIFEST_FILENAME = "checkpoint_full_resource_capability_manifest.json"
QUALIFICATION_RECEIPT_FILENAME = "checkpoint_full_resource_qualification_receipt.json"
PUBLICATION_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
KPP_DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
TOPOLOGIES = ("independent_processes", "shared_video_dag")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
MINIMUM_SAMPLES_PER_BRANCH_COORDINATE = 30
EMITTER_ROLES = (
    "resource_intervals", "hardware_resource_samples", "fanout_work_counters",
)
PILOT_EVIDENCE_ROLES = (
    "checkpoint_acceptance", "frames", "frame_events", "ingress_ledger",
    "topology_events", "resource_intervals", "hardware_resource_samples",
    "fanout_work_counters",
)
_RUNTIME_IDENTITY_FIELDS = {
    "runtime_backend", "analytics_device_api", "decoder_device_api",
    "worker_image_digest", "implementation_version", "hardware_binding_id",
}
_SHA256_CHARS = frozenset("0123456789abcdef")


class FullResourceQualificationError(RuntimeError):
    """A qualification input, evidence file, or immutable output is unsafe."""


PilotValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FullResourceQualificationError(
            "full-resource qualification artifact is not canonical JSON"
        ) from exc


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
    return (
        len(text) >= 8 and text == text.strip()
        and text.lower() not in {"unknown", "unavailable", "placeholder"}
        and not any(character in text for character in "\r\n\x00")
    )


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullResourceQualificationError(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise FullResourceQualificationError(f"{label} must be a JSON object")
    return value


def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise FullResourceQualificationError(f"artifact stat failed: {path}: {exc}") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _resolve_relative_regular_file(root: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise FullResourceQualificationError(
            f"{label} path must be a non-empty POSIX relative path"
        )
    relative = Path(value)
    if (
        relative.is_absolute() or value != relative.as_posix()
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise FullResourceQualificationError(
            f"{label} path escapes or is not normalized: {value!r}"
        )
    physical_root = root.resolve(strict=True)
    cursor = physical_root
    for part in relative.parts:
        cursor = cursor / part
        if _is_reparse_or_link(cursor):
            raise FullResourceQualificationError(
                f"{label} path contains a symlink/reparse point: {value}"
            )
    candidate = physical_root.joinpath(*relative.parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(physical_root)
    except ValueError as exc:
        raise FullResourceQualificationError(
            f"{label} path escapes project root: {value}"
        ) from exc
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise FullResourceQualificationError(f"{label} is not a regular file: {value}")
    return candidate


def _verify_descriptor(
    root: Path, descriptor: Any, label: str, *, forbid_hardlinks: bool,
) -> dict[str, Any]:
    if type(descriptor) is not dict or set(descriptor) != {
        "path", "size_bytes", "sha256",
    }:
        raise FullResourceQualificationError(f"{label} artifact descriptor fields drifted")
    size = descriptor.get("size_bytes")
    expected_sha = descriptor.get("sha256")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise FullResourceQualificationError(f"{label} artifact size is invalid")
    if not _valid_sha(expected_sha):
        raise FullResourceQualificationError(f"{label} artifact SHA-256 is invalid")
    path = _resolve_relative_regular_file(root, descriptor.get("path"), label)
    before = path.stat()
    if forbid_hardlinks and int(before.st_nlink) != 1:
        raise FullResourceQualificationError(f"{label} hardlink alias is prohibited")
    digest = _sha256_file(path)
    after = path.stat()
    before_id = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        int(getattr(before, "st_ctime_ns", 0)),
    )
    after_id = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
        int(getattr(after, "st_ctime_ns", 0)),
    )
    if before_id != after_id:
        raise FullResourceQualificationError(f"{label} artifact changed while hashing")
    if before.st_size != size or digest != expected_sha:
        raise FullResourceQualificationError(f"{label} artifact size/SHA drift")
    return {
        "path": descriptor["path"], "size_bytes": size, "sha256": digest,
        "filesystem_identity": (int(before.st_dev), int(before.st_ino)),
    }


class _ArtifactRegistry:
    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.identities: set[tuple[int, int]] = set()
        self.records: dict[str, dict[str, Any]] = {}
        self.identity_paths: dict[tuple[int, int], str] = {}

    def add(self, artifact: Mapping[str, Any], label: str) -> None:
        path = str(artifact["path"])
        identity = tuple(artifact["filesystem_identity"])
        if path in self.paths or identity in self.identities:
            raise FullResourceQualificationError(f"{label} artifact alias is prohibited")
        self.paths.add(path)
        self.identities.add(identity)
        self.records[path] = dict(artifact)
        self.identity_paths[identity] = path

    def add_shared(self, artifact: Mapping[str, Any], label: str) -> None:
        """Allow only the exact same physical source to implement many emitter roles."""

        path = str(artifact["path"])
        identity = tuple(artifact["filesystem_identity"])
        existing = self.records.get(path)
        if existing is not None:
            if existing != dict(artifact) or self.identity_paths.get(identity) != path:
                raise FullResourceQualificationError(
                    f"{label} shared artifact descriptor drifted"
                )
            return
        aliased_path = self.identity_paths.get(identity)
        if aliased_path is not None:
            raise FullResourceQualificationError(
                f"{label} artifact aliases {aliased_path} through another path"
            )
        self.paths.add(path)
        self.identities.add(identity)
        self.records[path] = dict(artifact)
        self.identity_paths[identity] = path


def _verify_resource_contract(
    root: Path, raw: Any, registry: _ArtifactRegistry,
) -> dict[str, Any]:
    expected_fields = {
        "contract_version", "publication_scope", "full_resource_validator",
        "interval_validator",
    }
    if type(raw) is not dict or set(raw) != expected_fields:
        raise FullResourceQualificationError("resource contract declaration fields drifted")
    if raw.get("contract_version") != 2 or raw.get("publication_scope") != PUBLICATION_SCOPE:
        raise FullResourceQualificationError("resource contract identity drifted")
    expected_paths = {
        "full_resource_validator": "scripts/full_resource_contract.py",
        "interval_validator": "scripts/resource_interval_contract.py",
    }
    verified: dict[str, dict[str, Any]] = {}
    for role, expected_path in expected_paths.items():
        if (raw.get(role) or {}).get("path") != expected_path:
            raise FullResourceQualificationError(f"resource contract {role} path drifted")
        artifact = _verify_descriptor(root, raw[role], role, forbid_hardlinks=True)
        registry.add(artifact, role)
        verified[role] = artifact
    identity = {
        "contract_version": 2,
        "publication_scope": PUBLICATION_SCOPE,
        "full_resource_validator_sha256": verified["full_resource_validator"]["sha256"],
        "interval_validator_sha256": verified["interval_validator"]["sha256"],
    }
    identity["sha256"] = _canonical_sha(identity)
    return identity


def _verify_bindings(
    root: Path, raw_bindings: Any, registry: _ArtifactRegistry,
) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    expected = {(system, resource) for system in SYSTEMS for resource in RESOURCES}
    if not isinstance(raw_bindings, list) or len(raw_bindings) != len(expected):
        raise FullResourceQualificationError(
            "binding set must contain exactly 8 system/resource rows"
        )
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    implementation_ids: set[str] = set()
    emitter_ids: set[str] = set()
    required_fields = {
        "system", "resource", "implementation_id", "implementation_artifact",
        "runtime_binding", "runtime_identity", "emitters",
    }
    for position, raw in enumerate(raw_bindings):
        if type(raw) is not dict or set(raw) != required_fields:
            raise FullResourceQualificationError(f"binding[{position}] fields drifted")
        key = (str(raw.get("system", "")), str(raw.get("resource", "")))
        if key not in expected or key in observed:
            raise FullResourceQualificationError(f"binding coverage duplicate/unknown: {key}")
        implementation_id = str(raw["implementation_id"])
        runtime_binding = str(raw["runtime_binding"])
        if not _stable_id(implementation_id) or implementation_id in implementation_ids:
            raise FullResourceQualificationError(
                f"binding {key} implementation identity is invalid"
            )
        if not _stable_id(runtime_binding):
            raise FullResourceQualificationError(f"binding {key} runtime binding is invalid")
        implementation_ids.add(implementation_id)
        implementation = _verify_descriptor(
            root, raw["implementation_artifact"], f"binding {key} implementation",
            forbid_hardlinks=True,
        )
        registry.add(implementation, f"binding {key} implementation")
        runtime_identity = raw["runtime_identity"]
        if type(runtime_identity) is not dict or set(runtime_identity) != _RUNTIME_IDENTITY_FIELDS:
            raise FullResourceQualificationError(
                f"binding {key} runtime_identity fields drifted"
            )
        if not all(_stable_id(runtime_identity[field]) for field in _RUNTIME_IDENTITY_FIELDS):
            raise FullResourceQualificationError(f"binding {key} runtime_identity is incomplete")
        image = str(runtime_identity["worker_image_digest"])
        if not image.startswith("sha256:") or not _valid_sha(image[7:]):
            raise FullResourceQualificationError(
                f"binding {key} worker image digest is invalid"
            )
        expected_api = "HOST_CPU" if key[1] == "cpu" else "NVIDIA_CUDA"
        if (
            runtime_identity["analytics_device_api"] != expected_api
            or runtime_identity["decoder_device_api"] != "NVIDIA_NVDEC"
        ):
            raise FullResourceQualificationError(f"binding {key} device API drifted")
        raw_emitters = raw["emitters"]
        if type(raw_emitters) is not dict or set(raw_emitters) != set(EMITTER_ROLES):
            raise FullResourceQualificationError(f"binding {key} emitter role set drifted")
        emitters: dict[str, Any] = {}
        for role in EMITTER_ROLES:
            emitter = raw_emitters[role]
            if type(emitter) is not dict or set(emitter) != {"emitter_id", "artifact"}:
                raise FullResourceQualificationError(f"binding {key}/{role} fields drifted")
            emitter_id = str(emitter["emitter_id"])
            if not _stable_id(emitter_id) or emitter_id in emitter_ids:
                raise FullResourceQualificationError(
                    f"binding {key}/{role} emitter identity is invalid"
                )
            emitter_ids.add(emitter_id)
            artifact = _verify_descriptor(
                root, emitter["artifact"], f"binding {key}/{role}",
                forbid_hardlinks=True,
            )
            registry.add_shared(artifact, f"binding {key}/{role}")
            emitters[role] = {
                "status": "native_emitter_implementation_bound",
                "emitter_id": emitter_id,
                "artifact_sha256": artifact["sha256"],
                "telemetry_source": "native",
            }
        observed[key] = {
            "status": "implemented_and_pre_run_pilot_required",
            "implementation_id": implementation_id,
            "implementation_sha256": implementation["sha256"],
            "runtime_binding": runtime_binding,
            "runtime_identity": dict(runtime_identity),
            "emitters": emitters,
        }
    if set(observed) != expected:
        raise FullResourceQualificationError("binding_cell_set_mismatch")
    systems = {
        system: {"resources": {
            resource: observed[(system, resource)] for resource in RESOURCES
        }} for system in SYSTEMS
    }
    return systems, observed


def _verify_pilot_evidence(
    root: Path, pilot: Mapping[str, Any], registry: _ArtifactRegistry,
) -> dict[str, dict[str, Any]]:
    evidence = pilot.get("evidence")
    if type(evidence) is not dict or set(evidence) != set(PILOT_EVIDENCE_ROLES):
        raise FullResourceQualificationError("pilot raw evidence descriptor set drifted")
    verified: dict[str, dict[str, Any]] = {}
    parents: set[Path] = set()
    for role in PILOT_EVIDENCE_ROLES:
        artifact = _verify_descriptor(
            root, evidence[role], f"pilot {role}", forbid_hardlinks=True,
        )
        registry.add(artifact, f"pilot {role}")
        verified[role] = artifact
        parents.add((root / artifact["path"]).parent.resolve(strict=True))
    if len(parents) != 1:
        raise FullResourceQualificationError(
            "pilot evidence files must share one accepted arm directory"
        )
    return verified


def _load_and_verify_kpp_datasets(
    project_root: Path, dataset_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        from benchmark_contract import load_dataset
    except Exception as exc:
        raise FullResourceQualificationError(f"KPP dataset validator unavailable: {exc}") from exc
    manifest_path = project_root / str(dataset_manifest["path"])
    datasets: dict[str, Any] = {}
    for codec in CODECS:
        name = KPP_DATASET_BY_CODEC[codec]
        try:
            dataset = load_dataset(
                manifest_path, name, mode="benchmark", project_root=project_root,
                require_files=True,
            )
        except Exception as exc:
            raise FullResourceQualificationError(
                f"real KPP {codec} dataset is unavailable or drifted: {exc}"
            ) from exc
        sources = sorted({
            str(row.get("resolved_sha256", "")) for row in dataset["streams"]
        })
        annotations = dataset.get("annotations") or {}
        annotation_sha = str(annotations.get("sha256", ""))
        if (
            dataset.get("publishable") is not True
            or str(dataset.get("codec_variant", "")) != codec
            or len(sources) != 2
            or any(not _valid_sha(value) for value in sources)
            or not _valid_sha(annotation_sha)
        ):
            raise FullResourceQualificationError(f"real KPP {codec} identity is incomplete")
        datasets[codec] = {
            "dataset_name": name,
            "manifest_identity_sha256": str(dataset["manifest_identity_sha256"]),
            "source_sha256": sources,
            "annotation_sha256": annotation_sha,
        }
    return datasets


def _load_resource_validators() -> dict[str, Any]:
    from benchmark_contract import (
        canonicalize_frames_csv, validate_frame_events,
        validate_frozen_policy_decisions, validate_required_sidecars,
    )
    from publication_acceptance_evidence import accepted_arm_evidence_files
    from topology_contract import validate_topology_events

    return {
        "canonicalize_frames_csv": canonicalize_frames_csv,
        "validate_frame_events": validate_frame_events,
        "validate_required_sidecars": validate_required_sidecars,
        "validate_topology_events": validate_topology_events,
        "accepted_arm_evidence_files": accepted_arm_evidence_files,
        "validate_frozen_policy_decisions": validate_frozen_policy_decisions,
    }


def _default_pilot_validator(
    pilot: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    root = Path(context["project_root"])
    paths = {
        role: root / descriptor["path"]
        for role, descriptor in context["pilot_evidence"].items()
    }
    expected_policy = "cpu_only" if pilot["resource"] == "cpu" else "gpu_only"
    try:
        acceptance = validate_checkpoint_qualification_pilot_acceptance_v1(
            project_root=root,
            acceptance_path=paths["checkpoint_acceptance"],
            expected_system=pilot["system"],
            expected_resource=pilot["resource"],
            expected_codec=pilot["codec"],
            expected_topology_kind=pilot["topology_kind"],
        )
    except QualificationPilotAcceptanceV1Error as exc:
        raise FullResourceQualificationError(
            f"checkpoint acceptance is not a qualification pilot: {exc}"
        ) from exc
    run_id = acceptance.get("run_id")
    if not _stable_id(run_id):
        raise FullResourceQualificationError("checkpoint acceptance run_id is invalid")
    expected_scenario = (
        "checkpoint_independent_processes_baseline"
        if pilot["topology_kind"] == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    if acceptance.get("scenario") != expected_scenario:
        raise FullResourceQualificationError(
            "checkpoint acceptance scenario/topology mismatch"
        )
    if acceptance.get("full_resource_finalization") != {
        "hardware_collector_stopped": True,
        "validation": "full_resource_evidence_v2_passed",
        "prepared_by": "prepare_checkpoint_publication_acceptance",
    }:
        raise FullResourceQualificationError(
            "checkpoint acceptance full-resource finalization is absent"
        )
    evidence_hashes = acceptance.get("evidence_sha256")
    validators = _load_resource_validators()
    expected_files = set(
        validators["accepted_arm_evidence_files"](
            expected_policy,
            full_resource=True,
        )
    )
    if type(evidence_hashes) is not dict or set(evidence_hashes) != expected_files:
        raise FullResourceQualificationError(
            "checkpoint acceptance evidence hash set drifted"
        )
    arm_root = paths["checkpoint_acceptance"].parent
    for filename, expected_sha in evidence_hashes.items():
        if (
            type(filename) is not str or Path(filename).name != filename
            or not _valid_sha(expected_sha)
        ):
            raise FullResourceQualificationError(
                "checkpoint acceptance evidence identity is unsafe"
            )
        evidence_path = arm_root / filename
        try:
            relative = evidence_path.relative_to(root).as_posix()
            size = evidence_path.stat().st_size
        except (OSError, ValueError) as exc:
            raise FullResourceQualificationError(
                f"checkpoint acceptance evidence is missing: {filename}"
            ) from exc
        _verify_descriptor(
            root,
            {"path": relative, "size_bytes": size, "sha256": expected_sha},
            f"checkpoint acceptance {filename}",
            forbid_hardlinks=True,
        )
    role_names = {
        "frames": "frames.csv",
        "frame_events": "frame_events.csv",
        "ingress_ledger": "ingress_ledger.csv",
        "topology_events": "topology_events.csv",
        "resource_intervals": "resource_intervals.csv",
        "hardware_resource_samples": "hardware_resource_samples.csv",
        "fanout_work_counters": "fanout_work_counters.csv",
    }
    for role, filename in role_names.items():
        if (
            paths[role].name != filename
            or evidence_hashes.get(filename) != _sha256_file(paths[role])
        ):
            raise FullResourceQualificationError(
                f"checkpoint acceptance does not bind current {filename}"
            )
    expected_full = {
        f"{role}.csv": evidence_hashes.get(f"{role}.csv")
        for role in EMITTER_ROLES
    }
    if acceptance.get("full_resource_evidence_sha256") != expected_full:
        raise FullResourceQualificationError(
            "checkpoint acceptance full-resource hash set drifted"
        )

    try:
        frames = validators["canonicalize_frames_csv"](
            paths["frames"], mode="benchmark", run_id="", detector="", backend="",
        )
        frame_events = validators["validate_frame_events"](paths["frame_events"])
        scenario = {
            "name": expected_scenario,
            "workload": {
                "routing_mode": "all_branches_per_stream",
                "analytics_function_types": len(BRANCHES),
            },
            "topology": {
                "contract_version": 1,
                "kind": pilot["topology_kind"],
                "routing_mode": "all_branches_per_stream",
                "required_branches": list(BRANCHES),
            },
        }
        topology_events = validators["validate_topology_events"](
            paths["topology_events"], frames=frames, frame_events=frame_events,
            scenario=scenario,
        )
        sidecars = validators["validate_required_sidecars"](
            arm_root,
            require_labeled_provenance=True,
            require_full_policy_trace=True,
            require_causal_policy_trace=True,
            require_online_policy_trace=(expected_policy == "adaptive_weights"),
            require_ingress_ledger=True,
            require_branch_terminals=True,
            require_stage_contracts=True,
            require_reset_evidence=True,
            required_branches=list(BRANCHES),
            topology_kind=pilot["topology_kind"],
            expected_streams=6,
            require_full_resource_evidence=True,
            expected_run_id=str(run_id),
            frames=frames,
            topology_events=topology_events,
        )
        validators["validate_frozen_policy_decisions"](
            arm_root / "publication_policy_decisions.jsonl",
            decisions=sidecars["policy_decisions"],
            expected_policy=expected_policy,
        )
    except FullResourceQualificationError:
        raise
    except Exception as exc:
        raise FullResourceQualificationError(
            f"pilot resource-v2 sidecar revalidation failed: {exc}"
        ) from exc
    ingress = sidecars["ingress_ledger"]
    summary = sidecars["resource_intervals"].attrs.get("full_resource_summary")
    if summary != acceptance.get("full_resource_summary"):
        raise FullResourceQualificationError(
            "checkpoint acceptance resource summary differs from revalidation"
        )
    dataset = context["datasets"][pilot["codec"]]
    observed_sources = sorted(set(ingress["source_sha256"].astype(str)))
    if observed_sources != dataset["source_sha256"]:
        raise FullResourceQualificationError(
            "pilot ingress is not bound to the frozen real KPP codec sources"
        )

    completed = {
        (
            str(row["run_id"]), str(row["trace_id"]), int(row["stream_id"]),
            int(row["frame_id"]),
        ): str(row["input_frame_key"])
        for row in ingress.to_dict(orient="records")
        if str(row["terminal_status"]) == "completed"
    }
    completed_branch_terminals = {
        (str(row["trace_id"]), str(row["branch_id"]))
        for row in sidecars["branch_terminals"].to_dict(orient="records")
        if str(row["terminal_status"]) == "completed"
    }
    samples: list[dict[str, Any]] = []
    for row in frame_events.to_dict(orient="records"):
        branch = str(row["stage"])
        if branch not in BRANCHES:
            continue
        key = (
            str(row["run_id"]), str(row["trace_id"]), int(row["stream_id"]),
            int(row["frame_id"]),
        )
        if key not in completed or (key[1], branch) not in completed_branch_terminals:
            continue
        if str(row["resource"]).lower() != pilot["resource"]:
            raise FullResourceQualificationError(
                "pilot analytics resource does not match its declared CPU/GPU coordinate"
            )
        samples.append({
            "system": pilot["system"], "resource": pilot["resource"],
            "codec": pilot["codec"], "topology_kind": pilot["topology_kind"],
            "branch": branch, "trace_id": key[1], "stream_id": key[2],
            "frame_id": key[3], "input_frame_key": completed[key],
        })
    return {
        "system": pilot["system"], "resource": pilot["resource"],
        "codec": pilot["codec"], "topology_kind": pilot["topology_kind"],
        "run_id": str(run_id), "dataset_name": dataset["dataset_name"],
        "source_sha256": dataset["source_sha256"],
        "evidence_sha256": {
            role: context["pilot_evidence"][role]["sha256"]
            for role in PILOT_EVIDENCE_ROLES
        },
        "resource_summary": summary, "samples": samples,
    }


def _validate_pilot_result(
    value: Any,
    *,
    key: tuple[str, str, str, str],
    evidence: Mapping[str, Mapping[str, Any]],
    datasets: Mapping[str, Mapping[str, Any]],
    seen_run_ids: set[str],
    trace_cells: dict[str, tuple[str, str, str, str]],
    global_samples: set[tuple[str, str]],
) -> tuple[dict[str, Any], int]:
    expected_fields = {
        "system", "resource", "codec", "topology_kind", "run_id",
        "dataset_name", "source_sha256", "evidence_sha256", "resource_summary",
        "samples",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise FullResourceQualificationError(
            f"pilot {key} validator result fields drifted"
        )
    if tuple(
        value[field] for field in ("system", "resource", "codec", "topology_kind")
    ) != key:
        raise FullResourceQualificationError(f"pilot {key} validator result escaped its cell")
    run_id = str(value["run_id"])
    if not _stable_id(run_id) or run_id in seen_run_ids:
        raise FullResourceQualificationError(f"pilot {key} run_id is invalid or duplicate")
    seen_run_ids.add(run_id)
    dataset = datasets[key[2]]
    if (
        value["dataset_name"] != dataset["dataset_name"]
        or value["source_sha256"] != dataset["source_sha256"]
    ):
        raise FullResourceQualificationError(f"pilot {key} KPP dataset identity drifted")
    expected_hashes = {
        role: evidence[role]["sha256"] for role in PILOT_EVIDENCE_ROLES
    }
    if value["evidence_sha256"] != expected_hashes:
        raise FullResourceQualificationError(f"pilot {key} evidence hash binding drifted")
    summary = value["resource_summary"]
    required_summary = {
        "resource_contract_version": 2,
        "evidence_accepted": True,
        "publication_bundle_bound": True,
        "full_resource_coverage_complete": True,
        "nvdec_counter_scope": "device_sample",
        "fanout_counter_scope": "per_trace_resource_work",
    }
    if type(summary) is not dict or any(
        summary.get(field) != expected for field, expected in required_summary.items()
    ):
        raise FullResourceQualificationError(
            f"pilot {key} resource-v2 summary is not accepted"
        )
    for field in (
        "nvdec_busy_equivalent_ns", "fanout_thread_cpu_time_ns", "fanout_work_units",
    ):
        number = summary.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise FullResourceQualificationError(f"pilot {key} summary {field} is invalid")
    if summary["nvdec_busy_equivalent_ns"] <= 0:
        raise FullResourceQualificationError(f"pilot {key} has no positive native NVDEC work")
    shared = key[3] == "shared_video_dag"
    if shared and (
        summary["fanout_thread_cpu_time_ns"] <= 0
        or summary["fanout_work_units"] <= 0
    ):
        raise FullResourceQualificationError(f"pilot {key} has no native shared fanout work")
    if not shared and (
        summary["fanout_thread_cpu_time_ns"] != 0
        or summary["fanout_work_units"] != 0
    ):
        raise FullResourceQualificationError(
            f"pilot {key} independent topology claims fanout work"
        )

    rows = value["samples"]
    sample_fields = {
        "system", "resource", "codec", "topology_kind", "branch", "trace_id",
        "stream_id", "frame_id", "input_frame_key",
    }
    if not isinstance(rows, list):
        raise FullResourceQualificationError(f"pilot {key} samples must be a list")
    counts: dict[str, int] = defaultdict(int)
    for position, row in enumerate(rows):
        if type(row) is not dict or set(row) != sample_fields:
            raise FullResourceQualificationError(
                f"pilot {key} sample[{position}] fields drifted"
            )
        if tuple(
            row[field] for field in ("system", "resource", "codec", "topology_kind")
        ) != key:
            raise FullResourceQualificationError(f"pilot {key} sample escaped its cell")
        branch = str(row["branch"])
        trace_id = str(row["trace_id"])
        input_key = str(row["input_frame_key"])
        stream_id = row["stream_id"]
        frame_id = row["frame_id"]
        if (
            branch not in BRANCHES or not _stable_id(trace_id) or not _stable_id(input_key)
            or isinstance(stream_id, bool) or not isinstance(stream_id, int) or stream_id < 0
            or isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0
        ):
            raise FullResourceQualificationError(f"pilot {key} sample identity is invalid")
        previous_cell = trace_cells.setdefault(trace_id, key)
        if previous_cell != key:
            raise FullResourceQualificationError(f"pilot {key} trace_id collides across cells")
        sample_identity = (trace_id, branch)
        if sample_identity in global_samples:
            raise FullResourceQualificationError(
                f"pilot {key} contains duplicate branch sample"
            )
        global_samples.add(sample_identity)
        counts[branch] += 1
    if set(counts) != set(BRANCHES):
        raise FullResourceQualificationError(f"pilot {key} branch coverage mismatch")
    for branch in BRANCHES:
        if counts[branch] < MINIMUM_SAMPLES_PER_BRANCH_COORDINATE:
            raise FullResourceQualificationError(
                f"pilot {key}/{branch} requires at least "
                f"{MINIMUM_SAMPLES_PER_BRANCH_COORDINATE} accepted samples"
            )
    summary_fields = (
        "resource_contract_version", "evidence_accepted", "publication_bundle_bound",
        "full_resource_coverage_complete", "nvdec_busy_equivalent_ns",
        "nvdec_counter_scope", "fanout_thread_cpu_time_ns", "fanout_work_units",
        "fanout_counter_scope",
    )
    pilot_manifest = {
        "system": key[0], "resource": key[1], "codec": key[2],
        "topology_kind": key[3], "run_id": run_id,
        "dataset_name": value["dataset_name"],
        "source_sha256": list(value["source_sha256"]),
        "evidence_sha256": dict(value["evidence_sha256"]),
        "resource_summary": {field: summary[field] for field in summary_fields},
        "accepted_samples_by_branch": {
            branch: counts[branch] for branch in BRANCHES
        },
        "accepted_branch_sample_count": len(rows),
    }
    return pilot_manifest, len(rows)


def _assessment_failure(
    blockers: list[str], *, index_sha: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
        "artifact_kind": "vast_pre_run_full_resource_qualification_assessment",
        "passed": False,
        "status": "blocked",
        "blockers": list(dict.fromkeys(blockers)),
        "index_sha256": index_sha,
        "coverage": {
            "binding_count": 0, "pilot_cell_count": 0,
            "accepted_branch_sample_count": 0,
        },
        "capability_manifest": None,
    }


def assess_full_resource_qualification(
    *,
    project_root: Path,
    index_path: Path,
    pilot_validator: PilotValidator | None = None,
) -> dict[str, Any]:
    """Purely assess pre-run capability; never write or accept a target arm."""
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir() or _is_reparse_or_link(root):
            raise FullResourceQualificationError(
                "project_root must be a physical non-reparse directory"
            )
        candidate = Path(index_path)
        if candidate.is_absolute():
            try:
                relative_index = candidate.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise FullResourceQualificationError(
                    "qualification index must remain under project_root"
                ) from exc
        else:
            relative_index = candidate.as_posix()
        index_file = _resolve_relative_regular_file(root, relative_index, "qualification index")
        index_sha = _sha256_file(index_file)
        index = _load_json_object(index_file, "qualification index")
        expected_fields = {
            "schema_version", "artifact_kind", "resource_contract",
            "dataset_manifest", "bindings", "pilots",
        }
        if (
            set(index) != expected_fields
            or index.get("schema_version") != QUALIFICATION_INDEX_SCHEMA_VERSION
            or index.get("artifact_kind")
            != "vast_pre_run_full_resource_qualification_index"
        ):
            raise FullResourceQualificationError(
                "qualification index schema/fields drifted"
            )

        registry = _ArtifactRegistry()
        resource_contract = _verify_resource_contract(
            root, index["resource_contract"], registry,
        )
        dataset_manifest = _verify_descriptor(
            root, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True,
        )
        registry.add(dataset_manifest, "dataset manifest")
        datasets = _load_and_verify_kpp_datasets(root, dataset_manifest)
        systems, bindings = _verify_bindings(root, index["bindings"], registry)

        expected_pilots = {
            (system, resource, codec, topology)
            for system in SYSTEMS for resource in RESOURCES for codec in CODECS
            for topology in TOPOLOGIES
        }
        pilots = index["pilots"]
        if not isinstance(pilots, list) or len(pilots) != len(expected_pilots):
            raise FullResourceQualificationError(
                "pilot_cell_set_mismatch: expected exactly 32 pilots"
            )
        by_key: dict[
            tuple[str, str, str, str], tuple[dict[str, Any], dict[str, Any]]
        ] = {}
        pilot_fields = {"system", "resource", "codec", "topology_kind", "evidence"}
        for position, raw in enumerate(pilots):
            if type(raw) is not dict or set(raw) != pilot_fields:
                raise FullResourceQualificationError(f"pilot[{position}] fields drifted")
            key = tuple(
                str(raw[field])
                for field in ("system", "resource", "codec", "topology_kind")
            )
            if key not in expected_pilots or key in by_key:
                raise FullResourceQualificationError(
                    f"pilot_cell_set_mismatch: duplicate/unknown {key}"
                )
            by_key[key] = (raw, _verify_pilot_evidence(root, raw, registry))
        if set(by_key) != expected_pilots:
            raise FullResourceQualificationError("pilot_cell_set_mismatch")

        validator = pilot_validator or _default_pilot_validator
        seen_run_ids: set[str] = set()
        trace_cells: dict[str, tuple[str, str, str, str]] = {}
        global_samples: set[tuple[str, str]] = set()
        pilot_manifest_rows: list[dict[str, Any]] = []
        accepted_sample_count = 0
        for key in sorted(expected_pilots):
            pilot, evidence = by_key[key]
            value = validator(
                pilot,
                {
                    "project_root": root,
                    "resource_contract": resource_contract,
                    "dataset_manifest": dataset_manifest,
                    "datasets": datasets,
                    "systems": systems,
                    "bindings": bindings,
                    "pilot_evidence": evidence,
                },
            )
            row, count = _validate_pilot_result(
                value, key=key, evidence=evidence, datasets=datasets,
                seen_run_ids=seen_run_ids, trace_cells=trace_cells,
                global_samples=global_samples,
            )
            pilot_manifest_rows.append(row)
            accepted_sample_count += count

        coverage = {
            "binding_count": len(bindings),
            "pilot_cell_count": len(pilot_manifest_rows),
            "accepted_branch_sample_count": accepted_sample_count,
            "minimum_samples_per_branch_coordinate": (
                MINIMUM_SAMPLES_PER_BRANCH_COORDINATE
            ),
            "systems": len(SYSTEMS),
            "resources": len(RESOURCES),
            "codecs": len(CODECS),
            "topology_kinds": len(TOPOLOGIES),
            "branches": len(BRANCHES),
        }
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_pre_run_full_resource_capability_manifest",
            "qualification_scope": "pre_run_hardware_and_emitter_capability_only",
            "publication_scope": PUBLICATION_SCOPE,
            "resource_contract": {
                field: resource_contract[field]
                for field in (
                    "contract_version", "publication_scope",
                    "full_resource_validator_sha256", "interval_validator_sha256",
                )
            },
            "resource_contract_identity_sha256": resource_contract["sha256"],
            "dataset_manifest_sha256": dataset_manifest["sha256"],
            "datasets": datasets,
            "systems": systems,
            "pilot_cells": pilot_manifest_rows,
            "coverage": coverage,
            "post_run_per_arm_evidence": {
                "required": True,
                "acceptance_artifact_kind": "checkpoint_publication_runtime_acceptance",
                "validator": "validate_full_resource_evidence",
                "configuration_evidence_accepted_mutated": False,
            },
        }
        manifest["content_sha256"] = _canonical_sha(manifest)
        return {
            "schema_version": QUALIFICATION_ASSESSMENT_SCHEMA_VERSION,
            "artifact_kind": "vast_pre_run_full_resource_qualification_assessment",
            "passed": True,
            "status": "ready_for_atomic_promotion",
            "blockers": [],
            "index_sha256": index_sha,
            "coverage": coverage,
            "capability_manifest": manifest,
        }
    except FullResourceQualificationError as exc:
        return _assessment_failure([str(exc)], index_sha=locals().get("index_sha"))
    except Exception as exc:
        return _assessment_failure(
            [f"full-resource qualification validation failed closed: {exc}"],
            index_sha=locals().get("index_sha"),
        )


def _write_immutable_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if (
            _is_reparse_or_link(path) or not path.is_file()
            or int(path.stat().st_nlink) != 1
            or path.read_bytes() != payload
        ):
            raise FullResourceQualificationError(
                f"immutable qualification output collision: {path.name}"
            )
        return {
            "path": path.name, "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
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
                directory_descriptor = os.open(
                    path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                os.fsync(directory_descriptor)
            except OSError:
                pass
            finally:
                if directory_descriptor is not None:
                    os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": path.name, "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def promote_full_resource_qualification(
    *,
    project_root: Path,
    index_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Write the derived capability manifest, then commit its receipt last."""
    assessment = assess_full_resource_qualification(
        project_root=project_root, index_path=index_path,
    )
    if not assessment["passed"]:
        raise FullResourceQualificationError(
            "full-resource qualification is blocked: "
            + ", ".join(assessment["blockers"][:8])
        )
    root = Path(project_root).resolve(strict=True)
    destination = Path(output_dir)
    if not destination.is_absolute():
        if any(part in ("", ".", "..") for part in destination.parts):
            raise FullResourceQualificationError(
                "qualification output_dir must be normalized"
            )
        destination = root / destination
    elif any(part in ("", ".", "..") for part in destination.parts[1:]):
        raise FullResourceQualificationError(
            "qualification output_dir must be normalized"
        )
    relative_parent_parts: list[str] = []
    try:
        cursor = destination.parent
        while not os.path.samefile(cursor, root):
            if cursor.parent == cursor:
                raise ValueError("output_dir is outside project_root")
            if _is_reparse_or_link(cursor):
                raise FullResourceQualificationError(
                    "qualification output_dir path contains a symlink/reparse point"
                )
            if not cursor.is_dir():
                raise FullResourceQualificationError(
                    "qualification output_dir parent is not a directory"
                )
            relative_parent_parts.append(cursor.name)
            cursor = cursor.parent
        relative_destination = Path(
            *reversed(relative_parent_parts), destination.name,
        )
    except FullResourceQualificationError:
        raise
    except (OSError, ValueError) as exc:
        raise FullResourceQualificationError(
            "qualification output_dir must remain under project_root"
        ) from exc
    if destination.exists() and (
        _is_reparse_or_link(destination) or not destination.is_dir()
    ):
        raise FullResourceQualificationError(
            "qualification output_dir must be a physical directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    manifest = assessment["capability_manifest"]
    manifest_descriptor = _write_immutable_json(
        destination / CAPABILITY_MANIFEST_FILENAME, manifest,
    )
    receipt = {
        "schema_version": QUALIFICATION_RECEIPT_SCHEMA_VERSION,
        "artifact_kind": (
            "vast_pre_run_full_resource_capability_qualification_receipt"
        ),
        "status": "accepted_pre_run_resource_capability_qualification",
        "qualification_index_sha256": assessment["index_sha256"],
        "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
        "resource_contract_identity_sha256": (
            manifest["resource_contract_identity_sha256"]
        ),
        "capability_manifest_content_sha256": manifest["content_sha256"],
        "coverage": assessment["coverage"],
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
        "outputs": {"capability_manifest": manifest_descriptor},
    }
    receipt["sha256"] = _canonical_sha(receipt)
    _write_immutable_json(destination / QUALIFICATION_RECEIPT_FILENAME, receipt)
    return {
        "passed": True, "status": "promoted", "receipt": receipt,
        "output_dir": str(destination),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--index-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = promote_full_resource_qualification(
        project_root=args.project_root,
        index_path=args.index_path,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAPABILITY_MANIFEST_FILENAME",
    "QUALIFICATION_RECEIPT_FILENAME",
    "FullResourceQualificationError",
    "KPP_DATASET_BY_CODEC",
    "assess_full_resource_qualification",
    "main",
    "promote_full_resource_qualification",
]
