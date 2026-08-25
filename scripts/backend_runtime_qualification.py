#!/usr/bin/env python3
"""Fail-closed pre-run qualification of four native benchmark runtimes.

These receipts prove hardware/runtime reachability only.  They never accept a
target matrix arm; every arm still requires its own post-run acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
KPP_DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
TOPOLOGIES = ("independent_processes", "shared_video_dag")
RESOURCES = ("cpu", "gpu")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)
PILOT_EVIDENCE_ROLES = (
    "checkpoint_acceptance", "native_policy_decisions", "resource_intervals",
    "hardware_resource_samples", "fanout_work_counters", "runtime_probe",
)
RUNTIME_ARTIFACT_ROLES = (
    "image_descriptor", "runtime_source", "runtime_binary", "worker_binary",
)
RESOURCE_EMITTER_ROLES = (
    "resource_intervals", "hardware_resource_samples", "fanout_work_counters",
)
BINDING_INDEX_FILENAME = "checkpoint_backend_runtime_qualification_binding_index.json"
PUBLICATION_SCOPE = "backend_native_runtime_hardware_capability_only"
_SHA_CHARS = frozenset("0123456789abcdef")


class BackendRuntimeQualificationError(RuntimeError):
    """Qualification input, evidence, or output is unsafe or incomplete."""


PilotValidator = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
DatasetLoader = Callable[..., dict[str, Any]]
ExecutionIdentityLoader = Callable[..., tuple[str, str]]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BackendRuntimeQualificationError(
            "backend qualification artifact is not canonical JSON"
        ) from exc


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file_sha(path: Path, label: str) -> str:
    before = path.stat()
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
        raise BackendRuntimeQualificationError(f"{label} changed while hashing")
    return digest


def _valid_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and set(value) <= _SHA_CHARS


def _stable_id(value: Any) -> bool:
    text = str(value or "")
    return (
        len(text) >= 8 and text == text.strip()
        and text.lower() not in {
            "unknown", "unavailable", "placeholder", "generic", "synthetic",
            "nonpublication",
        }
        and not any(character in text for character in "\r\n\x00")
    )


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackendRuntimeQualificationError(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise BackendRuntimeQualificationError(f"{label} must be a JSON object")
    return value


def _resolve_file(root: Path, value: Any, label: str) -> Path:
    if type(value) is not str or not value or "\\" in value:
        raise BackendRuntimeQualificationError(f"{label} path is unsafe")
    relative = Path(value)
    if (
        relative.is_absolute() or relative.as_posix() != value
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise BackendRuntimeQualificationError(f"{label} path is not normalized")
    candidate = root / relative
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if _is_link_or_reparse(cursor):
                raise BackendRuntimeQualificationError(
                    f"{label} path contains a link/reparse point"
                )
        except FileNotFoundError as exc:
            raise BackendRuntimeQualificationError(f"{label} is missing") from exc
    try:
        candidate.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise BackendRuntimeQualificationError(f"{label} escapes project root") from exc
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise BackendRuntimeQualificationError(f"{label} is not a regular file")
    return candidate


def _verify_descriptor(
    root: Path, value: Any, label: str, *, forbid_hardlinks: bool = True,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"path", "size_bytes", "sha256"}:
        raise BackendRuntimeQualificationError(f"{label} descriptor fields drifted")
    size = value["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise BackendRuntimeQualificationError(f"{label} size is invalid")
    if not _valid_sha(value["sha256"]):
        raise BackendRuntimeQualificationError(f"{label} SHA-256 is invalid")
    path = _resolve_file(root, value["path"], label)
    before = path.stat()
    if forbid_hardlinks and int(before.st_nlink) != 1:
        raise BackendRuntimeQualificationError(f"{label} hardlink is prohibited")
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
        raise BackendRuntimeQualificationError(f"{label} changed while hashing")
    if before.st_size != size or digest != value["sha256"]:
        raise BackendRuntimeQualificationError(f"{label} size/SHA drift")
    return {
        "path": value["path"], "size_bytes": size, "sha256": digest,
        "filesystem_identity": (int(before.st_dev), int(before.st_ino)),
    }


class _ArtifactRegistry:
    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.identities: set[tuple[int, int]] = set()

    def add(self, value: Mapping[str, Any], label: str) -> None:
        path = str(value["path"])
        identity = tuple(value["filesystem_identity"])
        if path in self.paths or identity in self.identities:
            raise BackendRuntimeQualificationError(f"artifact alias is prohibited: {label}")
        self.paths.add(path)
        self.identities.add(identity)


def _policies_and_contract_sha() -> tuple[tuple[str, ...], str]:
    try:
        import publication_policy_contract as contract
    except Exception as exc:
        raise BackendRuntimeQualificationError(
            f"frozen policy contract is unavailable: {exc}"
        ) from exc
    policies = tuple(contract.POLICIES)
    expected = (
        "cpu_only", "gpu_only", "static_hybrid", "heft",
        "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
    )
    if policies != expected:
        raise BackendRuntimeQualificationError("frozen policy set drifted")
    identity = contract.policy_contract_identity().get("sha256")
    if not _valid_sha(identity):
        raise BackendRuntimeQualificationError("policy contract identity is invalid")
    return policies, identity


def _validate_self_hash(value: Mapping[str, Any], label: str) -> None:
    if not _valid_sha(value.get("sha256")):
        raise BackendRuntimeQualificationError(f"{label} self SHA-256 is invalid")
    core = {key: item for key, item in value.items() if key != "sha256"}
    if value["sha256"] != _canonical_sha(core):
        raise BackendRuntimeQualificationError(f"{label} self hash drifted")


def _verify_upstream(
    root: Path, index: Mapping[str, Any], registry: _ArtifactRegistry,
    *, policy_contract_sha: str,
) -> dict[str, Any]:
    dataset = _verify_descriptor(root, index["dataset_manifest"], "dataset manifest")
    registry.add(dataset, "dataset manifest")

    policy = index["policy_qualification"]
    if type(policy) is not dict or set(policy) != {"receipt", "capability_manifest"}:
        raise BackendRuntimeQualificationError("policy qualification fields drifted")
    policy_receipt_desc = _verify_descriptor(root, policy["receipt"], "policy receipt")
    policy_cap_desc = _verify_descriptor(root, policy["capability_manifest"], "policy capability")
    registry.add(policy_receipt_desc, "policy receipt")
    registry.add(policy_cap_desc, "policy capability")
    policy_receipt = _load_json(root / policy_receipt_desc["path"], "policy receipt")
    _validate_self_hash(policy_receipt, "policy receipt")
    if (
        policy_receipt.get("artifact_kind") != "vast_publication_policy_qualification_receipt"
        or policy_receipt.get("status") != "accepted_evidence_driven_policy_qualification"
        or policy_receipt.get("policy_contract_sha256") != policy_contract_sha
        or policy_receipt.get("dataset_manifest_sha256") != dataset["sha256"]
    ):
        raise BackendRuntimeQualificationError("policy receipt identity/status drifted")
    declared_policy_output = (policy_receipt.get("outputs") or {}).get("capability_manifest")
    if type(declared_policy_output) is not dict or (
        declared_policy_output.get("size_bytes") != policy_cap_desc["size_bytes"]
        or declared_policy_output.get("sha256") != policy_cap_desc["sha256"]
        or Path(str(declared_policy_output.get("path", ""))).name
        != Path(policy_cap_desc["path"]).name
    ):
        raise BackendRuntimeQualificationError("policy receipt/capability cross-binding drifted")
    policy_capability = _load_json(root / policy_cap_desc["path"], "policy capability")
    if (
        policy_capability.get("artifact_kind") != "vast_publication_policy_capability_manifest"
        or policy_capability.get("policy_scope") != "analytics_only"
        or policy_capability.get("policy_contract_sha256") != policy_contract_sha
        or set((policy_capability.get("systems") or {})) != set(SYSTEMS)
    ):
        raise BackendRuntimeQualificationError("policy capability identity drifted")

    resource = index["resource_qualification"]
    if type(resource) is not dict or set(resource) != {"receipt", "capability_manifest"}:
        raise BackendRuntimeQualificationError("resource qualification fields drifted")
    resource_receipt_desc = _verify_descriptor(root, resource["receipt"], "resource receipt")
    resource_cap_desc = _verify_descriptor(root, resource["capability_manifest"], "resource capability")
    registry.add(resource_receipt_desc, "resource receipt")
    registry.add(resource_cap_desc, "resource capability")
    resource_receipt = _load_json(root / resource_receipt_desc["path"], "resource receipt")
    _validate_self_hash(resource_receipt, "resource receipt")
    if (
        resource_receipt.get("artifact_kind")
        != "vast_pre_run_full_resource_capability_qualification_receipt"
        or resource_receipt.get("status")
        != "accepted_pre_run_resource_capability_qualification"
        or resource_receipt.get("dataset_manifest_sha256") != dataset["sha256"]
        or resource_receipt.get("post_run_per_arm_evidence_required") is not True
        or resource_receipt.get("configuration_evidence_accepted_mutated") is not False
    ):
        raise BackendRuntimeQualificationError("resource receipt identity/status drifted")
    declared_resource_output = (resource_receipt.get("outputs") or {}).get("capability_manifest")
    if type(declared_resource_output) is not dict or (
        declared_resource_output.get("size_bytes") != resource_cap_desc["size_bytes"]
        or declared_resource_output.get("sha256") != resource_cap_desc["sha256"]
        or Path(str(declared_resource_output.get("path", ""))).name
        != Path(resource_cap_desc["path"]).name
    ):
        raise BackendRuntimeQualificationError("resource receipt/capability cross-binding drifted")
    resource_capability = _load_json(root / resource_cap_desc["path"], "resource capability")
    if (
        resource_capability.get("artifact_kind")
        != "vast_pre_run_full_resource_capability_manifest"
        or resource_capability.get("qualification_scope")
        != "pre_run_hardware_and_emitter_capability_only"
        or resource_capability.get("dataset_manifest_sha256") != dataset["sha256"]
        or resource_capability.get("content_sha256")
        != _canonical_sha({key: item for key, item in resource_capability.items() if key != "content_sha256"})
        or resource_receipt.get("capability_manifest_content_sha256")
        != resource_capability.get("content_sha256")
        or set((resource_capability.get("systems") or {})) != set(SYSTEMS)
    ):
        raise BackendRuntimeQualificationError("resource capability identity drifted")
    resource_contract_sha = resource_capability.get("resource_contract_identity_sha256")
    if (
        not _valid_sha(resource_contract_sha)
        or resource_receipt.get("resource_contract_identity_sha256") != resource_contract_sha
    ):
        raise BackendRuntimeQualificationError("resource contract identity drifted")

    analytics = index["analytics_execution"]
    expected_analytics = {
        "config", "config_identity_sha256", "model_parity_manifest",
        "model_parity_manifest_identity_sha256",
    }
    if type(analytics) is not dict or set(analytics) != expected_analytics:
        raise BackendRuntimeQualificationError("analytics execution fields drifted")
    execution = _verify_descriptor(root, analytics["config"], "analytics execution config")
    parity = _verify_descriptor(root, analytics["model_parity_manifest"], "model parity manifest")
    registry.add(execution, "analytics execution config")
    registry.add(parity, "model parity manifest")
    if not _valid_sha(analytics["config_identity_sha256"]) or not _valid_sha(
        analytics["model_parity_manifest_identity_sha256"]
    ):
        raise BackendRuntimeQualificationError("analytics/parity identity is invalid")
    return {
        "dataset": dataset,
        "policy_receipt": policy_receipt_desc,
        "policy_capability": policy_capability,
        "resource_receipt": resource_receipt_desc,
        "resource_capability": resource_capability,
        "resource_contract_identity_sha256": resource_contract_sha,
        "execution": execution,
        "parity": parity,
        "execution_identity": analytics["config_identity_sha256"],
        "parity_identity": analytics["model_parity_manifest_identity_sha256"],
    }


def _verify_runtime_bindings(
    root: Path, values: Any, registry: _ArtifactRegistry,
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or len(values) != len(SYSTEMS):
        raise BackendRuntimeQualificationError("runtime binding set must contain exactly four systems")
    expected_fields = {
        "system", "runtime_id", "runtime_backend", "hardware_binding_id",
        "runtime_image_digest", "artifacts",
    }
    result: dict[str, dict[str, Any]] = {}
    for position, value in enumerate(values):
        if type(value) is not dict or set(value) != expected_fields:
            raise BackendRuntimeQualificationError(f"runtime_binding[{position}] fields drifted")
        system = str(value["system"])
        if system not in SYSTEMS or system in result:
            raise BackendRuntimeQualificationError("runtime binding system coverage drifted")
        if not all(
            _stable_id(value[field])
            for field in ("runtime_id", "runtime_backend", "hardware_binding_id")
        ):
            raise BackendRuntimeQualificationError(f"{system} runtime identity is unstable")
        image = str(value["runtime_image_digest"])
        if not image.startswith("sha256:") or not _valid_sha(image[7:]):
            raise BackendRuntimeQualificationError(f"{system} runtime image digest is invalid")
        artifacts = value["artifacts"]
        if type(artifacts) is not dict or set(artifacts) != set(RUNTIME_ARTIFACT_ROLES):
            raise BackendRuntimeQualificationError(f"{system} runtime artifact roles drifted")
        verified = {}
        for role in RUNTIME_ARTIFACT_ROLES:
            artifact = _verify_descriptor(root, artifacts[role], f"{system} {role}")
            registry.add(artifact, f"{system} {role}")
            verified[role] = {
                "path": artifact["path"], "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
            }
        image_text = (root / verified["image_descriptor"]["path"]).read_text(
            encoding="utf-8"
        ).strip()
        if image_text != image:
            raise BackendRuntimeQualificationError(f"{system} image descriptor drifted")
        normalized = {
            field: value[field]
            for field in (
                "system", "runtime_id", "runtime_backend", "hardware_binding_id",
                "runtime_image_digest",
            )
        }
        normalized["artifacts"] = verified
        normalized["runtime_binding_identity_sha256"] = _canonical_sha(normalized)
        result[system] = normalized
    if tuple(result) != SYSTEMS:
        raise BackendRuntimeQualificationError("runtime binding order/membership drifted")
    return result


def _verify_runtime_cells(
    values: Any, policies: tuple[str, ...], *, runtimes: Mapping[str, Mapping[str, Any]],
    policy_contract_sha: str, policy_capability_sha: str,
    resource_contract_sha: str, resource_capability_content_sha: str,
    execution_identity: str, parity_identity: str,
) -> dict[str, int]:
    expected = {
        (system, codec, topology, policy, deadline)
        for system in SYSTEMS for codec in CODECS for topology in TOPOLOGIES
        for policy in policies for deadline in DEADLINES_MS
    }
    if not isinstance(values, list) or len(values) != len(expected):
        raise BackendRuntimeQualificationError(
            "runtime cell set must contain exactly 560 policy/deadline cells"
        )
    fields = {
        "system", "codec", "topology_kind", "policy", "deadline_ms",
        "reachability_status", "runtime_binding_identity_sha256",
        "policy_contract_sha256", "policy_capability_artifact_sha256",
        "resource_contract_identity_sha256",
        "resource_capability_content_sha256",
        "analytics_execution_config_identity_sha256",
        "model_parity_manifest_identity_sha256",
    }
    observed: set[tuple[str, str, str, str, int | float]] = set()
    for position, value in enumerate(values):
        if type(value) is not dict or set(value) != fields:
            raise BackendRuntimeQualificationError(f"runtime_cell[{position}] fields drifted")
        deadline = value["deadline_ms"]
        if type(deadline) not in {int, float} or not math.isfinite(float(deadline)):
            raise BackendRuntimeQualificationError("runtime cell deadline type drifted")
        key = (
            str(value["system"]), str(value["codec"]),
            str(value["topology_kind"]), str(value["policy"]), deadline,
        )
        if (
            key not in expected or key in observed
            or value["reachability_status"] != "native_runtime_cell_reachable"
        ):
            raise BackendRuntimeQualificationError(
                "runtime cell is duplicate, generic, relabelled, or unknown"
            )
        expected_identities = {
            "runtime_binding_identity_sha256": runtimes[key[0]]["runtime_binding_identity_sha256"],
            "policy_contract_sha256": policy_contract_sha,
            "policy_capability_artifact_sha256": policy_capability_sha,
            "resource_contract_identity_sha256": resource_contract_sha,
            "resource_capability_content_sha256": resource_capability_content_sha,
            "analytics_execution_config_identity_sha256": execution_identity,
            "model_parity_manifest_identity_sha256": parity_identity,
        }
        if any(value[field] != expected_value for field, expected_value in expected_identities.items()):
            raise BackendRuntimeQualificationError(
                "runtime cell capability/runtime identity cross-binding drifted"
            )
        observed.add(key)
    if observed != expected:
        raise BackendRuntimeQualificationError("runtime cell coverage mismatch")
    return {system: sum(key[0] == system for key in observed) for system in SYSTEMS}


def _verify_pilots(
    root: Path, values: Any, registry: _ArtifactRegistry,
) -> dict[tuple[str, str, str], tuple[dict[str, Any], dict[str, Any]]]:
    expected = {
        (system, codec, topology)
        for system in SYSTEMS for codec in CODECS for topology in TOPOLOGIES
    }
    if not isinstance(values, list) or len(values) != len(expected):
        raise BackendRuntimeQualificationError("pilot set must contain exactly 16 hardware arm cells")
    fields = {"system", "codec", "topology_kind", "evidence"}
    result = {}
    for position, value in enumerate(values):
        if type(value) is not dict or set(value) != fields:
            raise BackendRuntimeQualificationError(f"pilot[{position}] fields drifted")
        key = (
            str(value["system"]), str(value["codec"]),
            str(value["topology_kind"]),
        )
        if key not in expected or key in result:
            raise BackendRuntimeQualificationError("pilot cell is duplicate/relabelled/unknown")
        evidence = value["evidence"]
        if type(evidence) is not dict or set(evidence) != set(PILOT_EVIDENCE_ROLES):
            raise BackendRuntimeQualificationError("pilot evidence role set drifted")
        verified = {}
        parents = set()
        for role in PILOT_EVIDENCE_ROLES:
            artifact = _verify_descriptor(root, evidence[role], f"pilot {key}/{role}")
            registry.add(artifact, f"pilot {key}/{role}")
            verified[role] = {
                "path": artifact["path"], "size_bytes": artifact["size_bytes"],
                "sha256": artifact["sha256"],
            }
            parents.add((root / artifact["path"]).parent.resolve(strict=True))
        if len(parents) != 1:
            raise BackendRuntimeQualificationError("pilot evidence files must share one arm directory")
        result[key] = (dict(value), verified)
    if set(result) != expected:
        raise BackendRuntimeQualificationError("pilot cell coverage mismatch")
    return result


def _default_dataset_loader(
    descriptor: Mapping[str, Any], *, project_root: Path,
) -> dict[str, Any]:
    try:
        from benchmark_contract import load_dataset
    except Exception as exc:
        raise BackendRuntimeQualificationError(f"KPP dataset loader unavailable: {exc}") from exc
    path = project_root / str(descriptor["path"])
    result = {}
    for codec in CODECS:
        try:
            dataset = load_dataset(
                path, KPP_DATASET_BY_CODEC[codec], mode="benchmark",
                project_root=project_root, require_files=True,
            )
        except Exception as exc:
            raise BackendRuntimeQualificationError(
                f"frozen real KPP {codec} dataset is not ready: {exc}"
            ) from exc
        sources = sorted({
            str(stream["resolved_sha256"]) for stream in dataset["streams"]
        })
        if len(sources) != 2 or not all(_valid_sha(value) for value in sources):
            raise BackendRuntimeQualificationError(f"KPP {codec} source coverage drifted")
        result[codec] = {
            "dataset_name": KPP_DATASET_BY_CODEC[codec],
            "source_sha256": sources,
        }
    return result


def _default_execution_identity_loader(
    config_descriptor: Mapping[str, Any], parity_descriptor: Mapping[str, Any],
    *, project_root: Path,
) -> tuple[str, str]:
    try:
        from analytics_execution_capability import load_execution_layer_config
        from checkpoint_model_parity import load_parity_manifest
        config = load_execution_layer_config(project_root / str(config_descriptor["path"]))
        parity = load_parity_manifest(project_root / str(parity_descriptor["path"]))
    except Exception as exc:
        raise BackendRuntimeQualificationError(
            f"analytics execution/parity identities cannot be derived: {exc}"
        ) from exc
    return str(config["identity"]["sha256"]), str(parity["identity"]["sha256"])


def _default_pilot_validator(
    pilot: dict[str, Any], context: dict[str, Any],
) -> dict[str, Any]:
    """Reject declarations; production promotion requires raw-evidence validation.

    A real implementation must parse and independently validate every referenced
    acceptance/decision/resource/runtime artifact.  Merely supplying files or
    self-declared flags can never qualify a backend.
    """
    raise BackendRuntimeQualificationError(
        "raw KPP backend hardware pilot validator is required; declarations are not proof"
    )


def _validate_pilot_result(
    value: Any, *, key: tuple[str, str, str],
    evidence: Mapping[str, Mapping[str, Any]], runtime: Mapping[str, Any],
    dataset: Mapping[str, Any], policy_capability: Mapping[str, Any],
    resource_capability: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "system", "codec", "topology_kind", "dataset_name", "source_sha256",
        "publication_scope", "accepted", "synthetic", "nonpublication",
        "runtime_id", "runtime_image_digest", "hardware_binding_id",
        "evidence_sha256", "resource_branch_executions",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise BackendRuntimeQualificationError(f"pilot {key} validator fields drifted")
    if tuple(value[field] for field in ("system", "codec", "topology_kind")) != key:
        raise BackendRuntimeQualificationError(f"pilot {key} result was relabelled")
    if (
        value["publication_scope"] != PUBLICATION_SCOPE
        or value["accepted"] is not True
        or value["synthetic"] is not False
        or value["nonpublication"] is not False
    ):
        raise BackendRuntimeQualificationError(
            f"pilot {key} is generic, synthetic, nonpublication, or unaccepted"
        )
    if (
        value["runtime_id"] != runtime["runtime_id"]
        or value["runtime_image_digest"] != runtime["runtime_image_digest"]
        or value["hardware_binding_id"] != runtime["hardware_binding_id"]
    ):
        raise BackendRuntimeQualificationError(f"pilot {key} runtime/hardware identity drifted")
    if (
        value["dataset_name"] != dataset["dataset_name"]
        or value["source_sha256"] != dataset["source_sha256"]
    ):
        raise BackendRuntimeQualificationError(f"pilot {key} is not exact frozen real KPP")
    hashes = {role: evidence[role]["sha256"] for role in PILOT_EVIDENCE_ROLES}
    if value["evidence_sha256"] != hashes:
        raise BackendRuntimeQualificationError(f"pilot {key} evidence hash binding drifted")
    rows = value["resource_branch_executions"]
    expected = {(resource, branch) for resource in RESOURCES for branch in BRANCHES}
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise BackendRuntimeQualificationError(f"pilot {key} resource/branch coverage drifted")
    fields = {
        "resource", "branch", "implementation_id", "policy_emitter_id",
        "resource_emitter_ids", "worker_image_digest", "native_execution",
    }
    observed = set()
    for position, row in enumerate(rows):
        if type(row) is not dict or set(row) != fields:
            raise BackendRuntimeQualificationError(
                f"pilot {key} execution[{position}] fields drifted"
            )
        coordinate = (str(row["resource"]), str(row["branch"]))
        if coordinate not in expected or coordinate in observed or row["native_execution"] is not True:
            raise BackendRuntimeQualificationError(f"pilot {key} execution coverage drifted")
        resource, branch = coordinate
        policy_binding = policy_capability["systems"][key[0]]["branches"][branch][resource]
        resource_binding = resource_capability["systems"][key[0]]["resources"][resource]
        expected_emitters = {
            role: resource_binding["emitters"][role]["emitter_id"]
            for role in RESOURCE_EMITTER_ROLES
        }
        if (
            policy_binding.get("status") != "implemented_and_native_evidence_bound"
            or policy_binding["native_evidence"].get("status")
            != "accepted_native_runtime_emitter"
            or policy_binding["native_evidence"].get("telemetry_source") != "native"
            or row["implementation_id"] != policy_binding["implementation_id"]
            or row["policy_emitter_id"] != policy_binding["native_evidence"]["emitter_id"]
            or resource_binding.get("status") != "implemented_and_pre_run_pilot_required"
            or row["resource_emitter_ids"] != expected_emitters
            or row["worker_image_digest"]
            != resource_binding["runtime_identity"]["worker_image_digest"]
        ):
            raise BackendRuntimeQualificationError(
                f"pilot {key}/{coordinate} native policy/resource binding drifted"
            )
        if any(
            resource_binding["emitters"][role].get("status")
            != "native_emitter_implementation_bound"
            or resource_binding["emitters"][role].get("telemetry_source") != "native"
            for role in RESOURCE_EMITTER_ROLES
        ):
            raise BackendRuntimeQualificationError(
                f"pilot {key}/{coordinate} resource emitter is not native"
            )
        observed.add(coordinate)
    if observed != expected:
        raise BackendRuntimeQualificationError(f"pilot {key} execution coverage mismatch")
    return {
        "system": key[0], "codec": key[1], "topology_kind": key[2],
        "runtime_binding_identity_sha256": runtime["runtime_binding_identity_sha256"],
        "evidence_sha256": hashes,
        "resource_branch_execution_count": len(observed),
    }


def _coverage(*, system_count: int, pilot_count: int, runtime_count: int, execution_count: int, policies: tuple[str, ...]) -> dict[str, Any]:
    return {
        **({"system_count": system_count} if system_count > 1 else {}),
        "hardware_pilot_cell_count": pilot_count,
        "benchmark_arm_pilot_count": pilot_count,
        "runtime_cell_count": runtime_count,
        "resource_branch_execution_count": execution_count,
        "codecs": list(CODECS), "topology_kinds": list(TOPOLOGIES),
        "resources": list(RESOURCES), "policies": list(policies),
        "deadlines_ms": list(DEADLINES_MS), "analytics_branches": list(BRANCHES),
    }


def _failure(blocker: str, *, index_sha: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_qualification_assessment",
        "passed": False, "status": "blocked", "blockers": [blocker],
        "qualification_index_sha256": index_sha,
        "coverage": {
            "system_count": 0, "hardware_pilot_cell_count": 0,
            "benchmark_arm_pilot_count": 0, "runtime_cell_count": 0,
            "resource_branch_execution_count": 0,
        },
        "system_qualifications": None,
    }


def assess_backend_runtime_qualification(
    *, project_root: Path, index_path: Path,
    pilot_validator: PilotValidator | None = None,
    dataset_loader: DatasetLoader = _default_dataset_loader,
    execution_identity_loader: ExecutionIdentityLoader = _default_execution_identity_loader,
) -> dict[str, Any]:
    """Pure assessment; no output or configuration mutation is permitted."""
    try:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir() or _is_link_or_reparse(root):
            raise BackendRuntimeQualificationError(
                "project_root must be a physical non-reparse directory"
            )
        candidate = Path(index_path)
        if candidate.is_absolute():
            try:
                relative_index = candidate.resolve(strict=True).relative_to(root).as_posix()
            except (OSError, ValueError) as exc:
                raise BackendRuntimeQualificationError(
                    "qualification index must remain under project_root"
                ) from exc
        else:
            relative_index = candidate.as_posix()
        index_file = _resolve_file(root, relative_index, "qualification index")
        if int(index_file.stat().st_nlink) != 1:
            raise BackendRuntimeQualificationError("qualification index hardlink is prohibited")
        index_sha = _stable_file_sha(index_file, "qualification index")
        index = _load_json(index_file, "qualification index")
        fields = {
            "schema_version", "artifact_kind", "dataset_manifest",
            "policy_qualification", "resource_qualification",
            "analytics_execution", "runtime_bindings", "runtime_cells", "pilots",
        }
        if (
            set(index) != fields or index.get("schema_version") != 1
            or index.get("artifact_kind") != "vast_backend_runtime_qualification_index"
        ):
            raise BackendRuntimeQualificationError("qualification index schema/fields drifted")
        policies, policy_contract_sha = _policies_and_contract_sha()
        registry = _ArtifactRegistry()
        upstream = _verify_upstream(
            root, index, registry, policy_contract_sha=policy_contract_sha,
        )
        runtime_bindings = _verify_runtime_bindings(
            root, index["runtime_bindings"], registry,
        )
        runtime_counts = _verify_runtime_cells(
            index["runtime_cells"], policies, runtimes=runtime_bindings,
            policy_contract_sha=policy_contract_sha,
            policy_capability_sha=index["policy_qualification"]["capability_manifest"]["sha256"],
            resource_contract_sha=upstream["resource_contract_identity_sha256"],
            resource_capability_content_sha=upstream["resource_capability"]["content_sha256"],
            execution_identity=upstream["execution_identity"],
            parity_identity=upstream["parity_identity"],
        )
        pilots = _verify_pilots(root, index["pilots"], registry)

        datasets = dataset_loader(upstream["dataset"], project_root=root)
        if type(datasets) is not dict or set(datasets) != set(CODECS):
            raise BackendRuntimeQualificationError("dataset loader codec coverage drifted")
        normalized_datasets = {}
        for codec in CODECS:
            value = datasets[codec]
            if type(value) is not dict or set(value) != {"dataset_name", "source_sha256"}:
                raise BackendRuntimeQualificationError(f"dataset {codec} fields drifted")
            sources = value["source_sha256"]
            if (
                value["dataset_name"] != KPP_DATASET_BY_CODEC[codec]
                or not isinstance(sources, list) or len(sources) != 2
                or len(set(sources)) != 2 or not all(_valid_sha(item) for item in sources)
            ):
                raise BackendRuntimeQualificationError(
                    f"dataset {codec} is not exact frozen real KPP"
                )
            normalized_datasets[codec] = {
                "dataset_name": value["dataset_name"],
                "source_sha256": sorted(sources),
            }
        capability_datasets = upstream["resource_capability"].get("datasets")
        if type(capability_datasets) is not dict or set(capability_datasets) != set(CODECS):
            raise BackendRuntimeQualificationError("resource capability dataset coverage drifted")
        for codec in CODECS:
            declared = capability_datasets[codec]
            if (
                type(declared) is not dict
                or declared.get("dataset_name") != normalized_datasets[codec]["dataset_name"]
                or sorted(declared.get("source_sha256", []))
                != normalized_datasets[codec]["source_sha256"]
            ):
                raise BackendRuntimeQualificationError(
                    f"resource capability/KPP {codec} cross-binding drifted"
                )
        execution_identity, parity_identity = execution_identity_loader(
            upstream["execution"], upstream["parity"], project_root=root,
        )
        if (
            execution_identity != upstream["execution_identity"]
            or parity_identity != upstream["parity_identity"]
        ):
            raise BackendRuntimeQualificationError(
                "analytics execution/model parity recomputed identity drifted"
            )

        validator = pilot_validator or _default_pilot_validator
        system_rows: dict[str, list[dict[str, Any]]] = {system: [] for system in SYSTEMS}
        for key in sorted(pilots):
            pilot, evidence = pilots[key]
            value = validator(
                pilot,
                {
                    "project_root": root, "pilot_evidence": evidence,
                    "dataset_sources": {
                        codec: normalized_datasets[codec]["source_sha256"]
                        for codec in CODECS
                    },
                    "runtime_binding": runtime_bindings[key[0]],
                    "policy_capability": upstream["policy_capability"],
                    "resource_capability": upstream["resource_capability"],
                    "analytics_execution_config_identity_sha256": execution_identity,
                    "model_parity_manifest_identity_sha256": parity_identity,
                },
            )
            row = _validate_pilot_result(
                value, key=key, evidence=evidence,
                runtime=runtime_bindings[key[0]],
                dataset=normalized_datasets[key[1]],
                policy_capability=upstream["policy_capability"],
                resource_capability=upstream["resource_capability"],
            )
            system_rows[key[0]].append(row)

        qualifications = {}
        for system in SYSTEMS:
            rows = system_rows[system]
            if len(rows) != 4 or runtime_counts[system] != 140:
                raise BackendRuntimeQualificationError(
                    f"{system} qualification coverage is incomplete"
                )
            runtime_sha = runtime_bindings[system]["runtime_binding_identity_sha256"]
            if {row["runtime_binding_identity_sha256"] for row in rows} != {runtime_sha}:
                raise BackendRuntimeQualificationError(
                    f"{system} pilot/runtime identity cross-binding drifted"
                )
            qualifications[system] = {
                "system": system,
                "runtime_binding_identity_sha256": runtime_sha,
                "coverage": _coverage(
                    system_count=1, pilot_count=4, runtime_count=140,
                    execution_count=sum(row["resource_branch_execution_count"] for row in rows),
                    policies=policies,
                ),
                "pilot_cells": rows,
            }
        coverage = _coverage(
            system_count=4, pilot_count=16, runtime_count=560,
            execution_count=128, policies=policies,
        )
        return {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_qualification_assessment",
            "passed": True, "status": "ready_for_atomic_promotion",
            "blockers": [], "qualification_index_sha256": index_sha,
            "dataset_manifest_sha256": upstream["dataset"]["sha256"],
            "policy_contract_sha256": policy_contract_sha,
            "policy_qualification_receipt_sha256": upstream["policy_receipt"]["sha256"],
            "resource_contract_identity_sha256": upstream["resource_contract_identity_sha256"],
            "resource_qualification_receipt_sha256": upstream["resource_receipt"]["sha256"],
            "analytics_execution_config_identity_sha256": execution_identity,
            "model_parity_manifest_identity_sha256": parity_identity,
            "coverage": coverage, "system_qualifications": qualifications,
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
    except BackendRuntimeQualificationError as exc:
        return _failure(str(exc), index_sha=locals().get("index_sha"))
    except Exception as exc:
        return _failure(
            f"backend runtime qualification failed closed: {exc}",
            index_sha=locals().get("index_sha"),
        )


def _write_immutable_json(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(value) + b"\n"
    if path.exists():
        if (
            _is_link_or_reparse(path) or not path.is_file()
            or int(path.stat().st_nlink) != 1 or path.read_bytes() != payload
        ):
            raise BackendRuntimeQualificationError(
                f"immutable backend qualification output collision: {path.name}"
            )
        return {
            "path": path.name, "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
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
                    path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
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


def _preflight_immutable_outputs(outputs: Mapping[Path, dict[str, Any]]) -> None:
    for path, value in outputs.items():
        if not path.exists():
            continue
        payload = _canonical_bytes(value) + b"\n"
        if (
            _is_link_or_reparse(path) or not path.is_file()
            or int(path.stat().st_nlink) != 1 or path.read_bytes() != payload
        ):
            raise BackendRuntimeQualificationError(
                f"immutable backend qualification output collision: {path.name}"
            )


def _safe_output_directory(root: Path, output_dir: Path) -> Path:
    destination = Path(output_dir)
    if not destination.is_absolute():
        if any(part in ("", ".", "..") for part in destination.parts):
            raise BackendRuntimeQualificationError("output_dir must be normalized")
        destination = root / destination
    # On Windows tempfile may expose the same physical parent through an 8.3
    # spelling.  Resolve the longest existing prefix before containment checks.
    lexical = destination.resolve(strict=False)
    try:
        relative = lexical.relative_to(root)
    except ValueError as exc:
        raise BackendRuntimeQualificationError("output_dir must remain under project_root") from exc
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise BackendRuntimeQualificationError("output_dir must be a normalized child")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if not cursor.exists():
            break
        if _is_link_or_reparse(cursor):
            raise BackendRuntimeQualificationError("output_dir contains a link/reparse point")
        if cursor != lexical and not cursor.is_dir():
            raise BackendRuntimeQualificationError("output_dir parent is not a directory")
    if lexical.exists() and (not lexical.is_dir() or _is_link_or_reparse(lexical)):
        raise BackendRuntimeQualificationError("output_dir must be a physical directory")
    lexical.mkdir(parents=True, exist_ok=True)
    return lexical


def promote_backend_runtime_qualification(
    *, project_root: Path, index_path: Path, output_dir: Path,
    pilot_validator: PilotValidator | None = None,
    dataset_loader: DatasetLoader = _default_dataset_loader,
    execution_identity_loader: ExecutionIdentityLoader = _default_execution_identity_loader,
) -> dict[str, Any]:
    """Write four immutable system receipts and commit their binding index last."""
    assessment = assess_backend_runtime_qualification(
        project_root=project_root, index_path=index_path,
        pilot_validator=pilot_validator, dataset_loader=dataset_loader,
        execution_identity_loader=execution_identity_loader,
    )
    if not assessment["passed"]:
        raise BackendRuntimeQualificationError(
            "backend runtime qualification is blocked: "
            + ", ".join(assessment["blockers"][:8])
        )
    root = Path(project_root).resolve(strict=True)
    destination = _safe_output_directory(root, output_dir)
    receipts: dict[str, dict[str, Any]] = {}
    receipt_common = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_qualification_receipt",
        "status": "accepted_pre_run_backend_runtime_qualification",
        "qualification_scope": PUBLICATION_SCOPE,
        "qualification_index_sha256": assessment["qualification_index_sha256"],
        "dataset_manifest_sha256": assessment["dataset_manifest_sha256"],
        "policy_contract_sha256": assessment["policy_contract_sha256"],
        "policy_qualification_receipt_sha256": assessment["policy_qualification_receipt_sha256"],
        "resource_contract_identity_sha256": assessment["resource_contract_identity_sha256"],
        "resource_qualification_receipt_sha256": assessment["resource_qualification_receipt_sha256"],
        "analytics_execution_config_identity_sha256": assessment["analytics_execution_config_identity_sha256"],
        "model_parity_manifest_identity_sha256": assessment["model_parity_manifest_identity_sha256"],
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    for system in SYSTEMS:
        qualification = assessment["system_qualifications"][system]
        receipt = {
            **receipt_common, "system": system,
            "runtime_binding_identity_sha256": qualification["runtime_binding_identity_sha256"],
            "coverage": qualification["coverage"],
        }
        receipt["sha256"] = _canonical_sha(receipt)
        receipts[system] = receipt
    receipt_descriptors = {
        system: {
            "path": f"checkpoint_{system}_backend_runtime_qualification_receipt.json",
            "size_bytes": len(_canonical_bytes(receipts[system]) + b"\n"),
            "sha256": hashlib.sha256(_canonical_bytes(receipts[system]) + b"\n").hexdigest(),
        }
        for system in SYSTEMS
    }
    binding_index = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_qualification_binding_index",
        "status": "accepted_pre_run_backend_runtime_qualification_set",
        "qualification_index_sha256": assessment["qualification_index_sha256"],
        "systems": list(SYSTEMS), "receipts": receipt_descriptors,
        "coverage": assessment["coverage"],
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    binding_index["sha256"] = _canonical_sha(binding_index)
    planned_outputs = {
        destination / f"checkpoint_{system}_backend_runtime_qualification_receipt.json": receipts[system]
        for system in SYSTEMS
    }
    planned_outputs[destination / BINDING_INDEX_FILENAME] = binding_index
    _preflight_immutable_outputs(planned_outputs)
    for system in SYSTEMS:
        filename = f"checkpoint_{system}_backend_runtime_qualification_receipt.json"
        current = _write_immutable_json(destination / filename, receipts[system])
        if current != receipt_descriptors[system]:
            raise BackendRuntimeQualificationError(
                f"backend receipt {system} descriptor drifted while committing"
            )
    binding_descriptor = _write_immutable_json(
        destination / BINDING_INDEX_FILENAME, binding_index,
    )
    return {
        "passed": True, "status": "promoted",
        "binding_index": binding_index,
        "binding_index_descriptor": binding_descriptor,
        "receipt_descriptors": receipt_descriptors,
        "output_dir": str(destination),
    }


__all__ = [
    "BINDING_INDEX_FILENAME", "BackendRuntimeQualificationError",
    "KPP_DATASET_BY_CODEC",
    "assess_backend_runtime_qualification",
    "promote_backend_runtime_qualification",
]
