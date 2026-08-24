#!/usr/bin/env python3
"""Immutable accepted-artifact binding for the full publication run identity."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 2
DEFAULT_MANIFEST = Path("configs/full_publication_identity_artifacts.yaml")
MANIFEST_KIND = "vast_full_publication_identity_artifact_manifest"
BINDING_KIND = "vast_full_publication_identity_artifact_binding"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
PUBLICATION_SCOPE = "primary_architecture_full_resource_raw_evidence_v2"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{7,160}$")
_PLACEHOLDERS = frozenset({"unknown", "placeholder", "unavailable", "engineering_canary"})
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})


class IdentityArtifactError(RuntimeError):
    """A required accepted identity artifact is missing, aliased, or invalid."""


Loader = Callable[[Path], Mapping[str, Any]]
PolicyAssessor = Callable[[Mapping[str, Any] | None], Mapping[str, Any]]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise IdentityArtifactError("identity artifact is not canonical JSON") from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _valid_id(value: Any) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None and value.lower() not in _PLACEHOLDERS


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IdentityArtifactError(message)


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields drifted")
    return value


def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise IdentityArtifactError(f"identity artifact stat failed: {path}: {error}") from error
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _root_path(project_root: Path | str) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as error:
        raise IdentityArtifactError(f"project_root is unavailable: {error}") from error
    _require(root.is_dir() and not _is_reparse_or_link(root), "project_root must be a physical directory")
    return root


def _resolve_file(root: Path, value: Any, label: str, *, base: Path | None = None) -> Path:
    _require(
        type(value) is str and bool(value) and "\\" not in value
        and ":" not in value and "\x00" not in value,
        f"{label} path must be POSIX relative",
    )
    relative_posix = PurePosixPath(value)
    relative_windows = PureWindowsPath(value)
    _require(
        not relative_posix.is_absolute()
        and relative_posix.anchor == ""
        and relative_windows.drive == ""
        and relative_windows.root == ""
        and relative_windows.anchor == ""
        and relative_posix.as_posix() == value
        and bool(relative_posix.parts)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((" ", "."))
            and not any(ord(character) < 32 for character in part)
            and part.split(".", 1)[0].upper() not in _WINDOWS_RESERVED_NAMES
            for part in relative_posix.parts
        ),
        f"{label} path is not normalized",
    )
    relative = Path(*relative_posix.parts)
    anchor = root if base is None else base
    try:
        anchor = anchor.resolve(strict=True)
        anchor.relative_to(root)
    except (OSError, ValueError) as error:
        raise IdentityArtifactError(f"{label} base escaped project_root") from error
    candidate = anchor.joinpath(*relative.parts)
    cursor = anchor
    for part in relative.parts:
        cursor = cursor / part
        _require(not _is_reparse_or_link(cursor), f"{label} path contains a symlink/reparse point")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise IdentityArtifactError(f"{label} path escaped project_root or is missing") from error
    _require(stat.S_ISREG(candidate.lstat().st_mode), f"{label} is not a regular file")
    return candidate


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_record(root: Path, descriptor: Any, label: str, *, base: Path | None = None) -> tuple[dict[str, Any], tuple[int, int], Path]:
    item = _exact(descriptor, {"path", "size_bytes", "sha256"}, f"{label} descriptor")
    size = item.get("size_bytes")
    _require(type(size) is int and size > 0, f"{label} artifact size is invalid")
    _require(_valid_sha(item.get("sha256")), f"{label} artifact SHA-256 is invalid")
    path = _resolve_file(root, item["path"], label, base=base)
    before = path.stat()
    _require(int(before.st_nlink) == 1, f"{label} hardlink alias is prohibited")
    first = _hash_file(path)
    middle = path.stat()
    second = _hash_file(path)
    after = path.stat()
    identities = [(value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, int(getattr(value, "st_ctime_ns", 0))) for value in (before, middle, after)]
    _require(identities[0] == identities[1] == identities[2] and first == second, f"{label} changed while hashing")
    _require(int(after.st_size) == size and first == item["sha256"], f"{label} artifact size/SHA drift")
    return ({"path": path.relative_to(root).as_posix(), "size_bytes": size, "sha256": first}, (int(after.st_dev), int(after.st_ino)), path)


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            import yaml
            value = yaml.safe_load(payload)
        else:
            value = json.loads(payload)
    except Exception as error:
        raise IdentityArtifactError(f"invalid {label}: {error}") from error
    _require(type(value) is dict, f"{label} must be an object")
    return value


def _self_hash(value: Mapping[str, Any], field: str, label: str) -> None:
    _require(_valid_sha(value.get(field)), f"{label} {field} is invalid")
    _require(value[field] == _canonical_sha({key: item for key, item in value.items() if key != field}), f"{label} self-hash drift")


class _Registry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, dict[str, Any]] = {}
        self.inodes: dict[tuple[int, int], str] = {}
        self.path_inodes: dict[str, tuple[int, int]] = {}

    def add(self, descriptor: Any, label: str, *, base: Path | None = None) -> tuple[dict[str, Any], Path]:
        record, inode, path = _stable_record(self.root, descriptor, label, base=base)
        _require(record["path"] not in self.files, f"{label} duplicates another artifact path")
        _require(inode not in self.inodes, f"{label} aliases artifact {self.inodes.get(inode, '')}")
        self.files[record["path"]] = record
        self.inodes[inode] = record["path"]
        self.path_inodes[record["path"]] = inode
        return record, path

    def add_shared(
        self, descriptor: Any, label: str, *, base: Path | None = None,
    ) -> tuple[dict[str, Any], Path]:
        """Register an exact recurring physical input once, never an alias."""
        record, inode, path = _stable_record(
            self.root, descriptor, label, base=base,
        )
        existing = self.files.get(record["path"])
        if existing is not None:
            _require(
                existing == record and self.inodes.get(inode) == record["path"],
                f"{label} recurring descriptor/inode drift",
            )
            return dict(existing), path
        _require(
            inode not in self.inodes,
            f"{label} aliases artifact {self.inodes.get(inode, '')}",
        )
        self.files[record["path"]] = record
        self.inodes[inode] = record["path"]
        self.path_inodes[record["path"]] = inode
        return record, path

    def verify_embedded(self, descriptor: Any, expected: Mapping[str, Any], label: str, *, base: Path) -> None:
        record, _, path = _stable_record(self.root, descriptor, label, base=base)
        _require(record == dict(expected) and path == self.root / expected["path"], f"{label} descriptor binding drift")


def _read_registered_object(
    registry: _Registry, record: Mapping[str, Any], path: Path, label: str,
    *, maximum_bytes: int = 64 * 1024 * 1024,
) -> dict[str, Any]:
    """Read registered JSON/YAML bytes from the same stable physical inode."""
    _require(
        type(record.get("size_bytes")) is int
        and 0 < record["size_bytes"] <= maximum_bytes,
        f"{label} exceeds the bounded parse size",
    )
    expected_inode = registry.path_inodes.get(str(record.get("path")))
    _require(expected_inode is not None, f"{label} was not physically registered")
    descriptor_fd: int | None = None
    try:
        before = path.lstat()
        _require(
            stat.S_ISREG(before.st_mode)
            and int(before.st_nlink) == 1
            and not _is_reparse_or_link(path),
            f"{label} is not one physical regular file",
        )
        flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        descriptor_fd = os.open(path, flags)
        opened = os.fstat(descriptor_fd)
        path_opened = path.lstat()
        _require(
            (int(opened.st_dev), int(opened.st_ino)) == expected_inode
            and (int(path_opened.st_dev), int(path_opened.st_ino))
            == expected_inode,
            f"{label} inode changed before parsing",
        )
        payload = bytearray()
        while True:
            chunk = os.read(descriptor_fd, min(1024 * 1024, maximum_bytes + 1))
            if not chunk:
                break
            payload.extend(chunk)
            _require(len(payload) <= maximum_bytes, f"{label} exceeded bounded parse size")
        after = os.fstat(descriptor_fd)
        path_after = path.lstat()
    except IdentityArtifactError:
        raise
    except OSError as error:
        raise IdentityArtifactError(f"{label} cannot be parsed safely: {error}") from error
    finally:
        if descriptor_fd is not None:
            os.close(descriptor_fd)
    _require(
        (int(after.st_dev), int(after.st_ino)) == expected_inode
        and (int(path_after.st_dev), int(path_after.st_ino)) == expected_inode
        and int(after.st_nlink) == 1
        and int(path_after.st_nlink) == 1,
        f"{label} inode changed while parsing",
    )
    raw = bytes(payload)
    _require(
        len(raw) == record["size_bytes"]
        and hashlib.sha256(raw).hexdigest() == record["sha256"],
        f"{label} registered descriptor drifted while parsing",
    )
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            import yaml
            value = yaml.safe_load(raw.decode("utf-8"))
        else:
            value = json.loads(raw.decode("utf-8"))
    except Exception as error:
        raise IdentityArtifactError(f"invalid {label}: {error}") from error
    _require(type(value) is dict, f"{label} must be an object")
    return value


def _default_parity_loader(path: Path) -> Mapping[str, Any]:
    from checkpoint_model_parity import load_parity_manifest
    return load_parity_manifest(path)


def _default_parity_acceptance_loader(
    *, project_root: Path, receipt_path: Path,
) -> Mapping[str, Any]:
    from checkpoint_model_parity_acceptance import (
        load_verified_model_parity_acceptance,
    )
    return load_verified_model_parity_acceptance(
        project_root=project_root,
        receipt_path=receipt_path,
    )


def _default_execution_loader(path: Path) -> Mapping[str, Any]:
    from analytics_execution_capability import load_execution_layer_config
    return load_execution_layer_config(path)


def _default_policy_assessor(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    from publication_policy_contract import assess_capability_manifest
    return assess_capability_manifest(value)


def _validate_content_binding(
    binding: Any,
    label: str,
    *,
    registry: _Registry,
    loader: Loader,
    expected_kind: str,
) -> tuple[dict[str, Any], str]:
    item = _exact(binding, {"artifact", "content_identity_sha256"}, label)
    declared = item["content_identity_sha256"]
    _require(_valid_sha(declared), f"{label} content identity SHA-256 is invalid")
    record, path = registry.add(item["artifact"], label)
    try:
        loaded = loader(path)
    except Exception as error:
        raise IdentityArtifactError(f"{label} canonical loader rejected artifact: {error}") from error
    _require(isinstance(loaded, Mapping) and loaded.get("artifact_kind") == expected_kind, f"{label} artifact kind drift")
    identity = loaded.get("identity")
    _require(isinstance(identity, Mapping) and identity.get("sha256") == declared, f"{label} content identity drift")
    return record, str(declared)


def _validate_parity_acceptance_binding(
    binding: Any,
    *,
    registry: _Registry,
    root: Path,
    loader: Callable[..., Mapping[str, Any]],
) -> tuple[dict[str, Any], str]:
    item = _exact(
        binding,
        {"receipt", "accepted_manifest", "accepted_assessment"},
        "model parity acceptance binding",
    )
    receipt_record, receipt_path = registry.add(
        item["receipt"], "model parity acceptance receipt"
    )
    manifest_record, _ = registry.add(
        item["accepted_manifest"], "accepted model parity manifest"
    )
    assessment_record, _ = registry.add(
        item["accepted_assessment"], "accepted model parity assessment"
    )
    try:
        accepted = loader(project_root=root, receipt_path=receipt_path)
    except Exception as error:
        raise IdentityArtifactError(
            f"model parity physical acceptance rejected artifact: {error}"
        ) from error
    _require(
        isinstance(accepted, Mapping)
        and accepted.get("schema_version") == 1
        and accepted.get("artifact_kind")
        == "vast_verified_model_parity_acceptance_binding",
        "model parity physical acceptance binding is invalid",
    )
    for field, expected in (
        ("receipt", receipt_record),
        ("accepted_manifest", manifest_record),
        ("accepted_assessment", assessment_record),
    ):
        _require(
            accepted.get(field) == expected,
            f"model parity physical acceptance {field} descriptor drift",
        )
    files = accepted.get("files")
    _require(
        type(files) is list and len(files) == 35,
        "model parity acceptance must bind exact 35 files",
    )
    _require(
        accepted.get("evidence_count") == 32
        and _valid_sha(accepted.get("evidence_sha256"))
        and _valid_sha(accepted.get("binding_sha256")),
        "model parity physical acceptance coverage/identity drift",
    )
    _require(
        accepted.get("files_sha256") == _canonical_sha(files)
        and accepted.get("binding_sha256")
        == _canonical_sha(
            {key: value for key, value in accepted.items() if key != "binding_sha256"}
        ),
        "model parity physical acceptance self-hash drift",
    )
    expected_paths = {item["path"] for item in files}
    _require(
        len(expected_paths) == 35,
        "model parity acceptance file set contains aliases",
    )
    # The parity loader has already physically rehashed them. Add the same exact
    # descriptors to the global identity registry so all downstream grants bind them.
    already_added = {
        receipt_record["path"], manifest_record["path"], assessment_record["path"]
    }
    for position, descriptor in enumerate(files):
        if descriptor["path"] in already_added:
            expected = {
                receipt_record["path"]: receipt_record,
                manifest_record["path"]: manifest_record,
                assessment_record["path"]: assessment_record,
            }[descriptor["path"]]
            _require(descriptor == expected, "model parity accepted artifact descriptor drift")
            continue
        registry.add(descriptor, f"model parity accepted evidence[{position}]")
    return json.loads(_canonical_bytes(accepted).decode("utf-8")), str(
        accepted["accepted_manifest_content_identity_sha256"]
    )


def _validate_policy(
    binding: Any,
    *,
    registry: _Registry,
    assessor: PolicyAssessor,
) -> tuple[dict[str, Any], dict[str, Any]]:
    item = _exact(binding, {"receipt", "outputs"}, "policy qualification binding")
    outputs = _exact(item["outputs"], {"capability_manifest", "calibration_mapping"}, "policy qualification outputs")
    receipt_record, receipt_path = registry.add(item["receipt"], "policy qualification receipt")
    capability_record, capability_path = registry.add(outputs["capability_manifest"], "policy capability manifest")
    calibration_record, calibration_path = registry.add(outputs["calibration_mapping"], "policy calibration mapping")
    receipt = _read_object(receipt_path, "policy qualification receipt")
    _exact(receipt, {
        "schema_version", "artifact_kind", "status", "policy_contract_sha256",
        "qualification_index_sha256", "dataset_manifest_sha256", "coverage", "outputs", "sha256",
    }, "policy qualification receipt")
    _require(receipt.get("schema_version") == 1 and receipt.get("artifact_kind") == "vast_publication_policy_qualification_receipt", "policy qualification receipt schema/kind drift")
    _require(receipt.get("status") == "accepted_evidence_driven_policy_qualification", "policy qualification receipt status is not accepted")
    for field in ("policy_contract_sha256", "qualification_index_sha256", "dataset_manifest_sha256"):
        _require(_valid_sha(receipt.get(field)), f"policy qualification receipt {field} is invalid")
    coverage = _exact(receipt["coverage"], {"binding_count", "pilot_cell_count", "accepted_sample_count", "minimum_samples_per_branch_cell"}, "policy qualification coverage")
    _require(
        coverage == {
            "binding_count": 32,
            "pilot_cell_count": 32,
            "accepted_sample_count": 3840,
            "minimum_samples_per_branch_cell": 30,
        },
        "policy qualification coverage is incomplete",
    )
    embedded = _exact(receipt["outputs"], {"capability_manifest", "calibration_mapping"}, "policy receipt outputs")
    registry.verify_embedded(embedded["capability_manifest"], capability_record, "policy receipt capability output", base=receipt_path.parent)
    registry.verify_embedded(embedded["calibration_mapping"], calibration_record, "policy receipt calibration output", base=receipt_path.parent)
    _self_hash(receipt, "sha256", "policy qualification receipt")
    capability = _read_object(capability_path, "policy capability manifest")
    assessment = assessor(capability)
    _require(isinstance(assessment, Mapping) and assessment.get("passed") is True, "policy capability manifest is not accepted: " + ", ".join(str(value) for value in (assessment.get("blockers") or [])[:5]))
    _require(capability.get("policy_contract_sha256") == receipt["policy_contract_sha256"], "policy capability/receipt contract identity drift")
    calibration = _read_object(calibration_path, "policy calibration mapping")
    _require(calibration.get("schema_version") == 1 and calibration.get("artifact_kind") == "vast_publication_policy_calibration_mapping", "policy calibration mapping schema/kind drift")
    _require(calibration.get("policy_contract_sha256") == receipt["policy_contract_sha256"], "policy calibration/receipt contract identity drift")
    _require(calibration.get("aggregation_rule") == "median_of_balanced_native_codec_topology_cells_v1" and calibration.get("minimum_samples_per_branch_cell") == 30, "policy calibration acceptance rule drift")
    calibrations = calibration.get("calibrations")
    _require(isinstance(calibrations, Mapping) and set(calibrations) == set(SYSTEMS), "policy calibration system coverage drift")
    return (
        {"receipt": receipt_record, "outputs": {"capability_manifest": capability_record, "calibration_mapping": calibration_record}},
        receipt,
    )


def _validate_resource_binding(binding: Any, *, registry: _Registry) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    item = _exact(binding, {"receipt", "outputs"}, "resource qualification binding")
    outputs = _exact(item["outputs"], {"capability_manifest"}, "resource qualification outputs")
    receipt_record, receipt_path = registry.add(item["receipt"], "resource qualification receipt")
    capability_record, capability_path = registry.add(outputs["capability_manifest"], "resource capability manifest")
    receipt = _read_object(receipt_path, "resource qualification receipt")
    _exact(receipt, {
        "schema_version", "artifact_kind", "status", "qualification_index_sha256",
        "dataset_manifest_sha256", "resource_contract_identity_sha256",
        "capability_manifest_content_sha256", "coverage",
        "post_run_per_arm_evidence_required", "configuration_evidence_accepted_mutated",
        "outputs", "sha256",
    }, "resource qualification receipt")
    _require(receipt.get("schema_version") == 1 and receipt.get("artifact_kind") == "vast_pre_run_full_resource_capability_qualification_receipt", "resource qualification receipt schema/kind drift")
    _require(receipt.get("status") == "accepted_pre_run_resource_capability_qualification", "resource qualification receipt status is not accepted")
    for field in ("qualification_index_sha256", "dataset_manifest_sha256", "resource_contract_identity_sha256", "capability_manifest_content_sha256"):
        _require(_valid_sha(receipt.get(field)), f"resource qualification receipt {field} is invalid")
    _require(receipt.get("post_run_per_arm_evidence_required") is True and receipt.get("configuration_evidence_accepted_mutated") is False, "resource receipt confused pre-run capability with per-arm acceptance")
    embedded = _exact(receipt["outputs"], {"capability_manifest"}, "resource receipt outputs")
    registry.verify_embedded(embedded["capability_manifest"], capability_record, "resource receipt capability output", base=receipt_path.parent)
    _self_hash(receipt, "sha256", "resource qualification receipt")
    capability = _read_object(capability_path, "resource capability manifest")
    _validate_resource_capability(capability)
    _require(capability["content_sha256"] == receipt["capability_manifest_content_sha256"], "resource capability content identity drift")
    _require(capability["resource_contract_identity_sha256"] == receipt["resource_contract_identity_sha256"], "resource contract identity drift")
    _require(capability["dataset_manifest_sha256"] == receipt["dataset_manifest_sha256"], "resource dataset identity drift")
    _require(capability["coverage"] == receipt["coverage"], "resource capability/receipt coverage drift")
    return ({"receipt": receipt_record, "outputs": {"capability_manifest": capability_record}}, receipt, capability)


def _validate_resource_capability(value: Mapping[str, Any]) -> None:
    _exact(value, {
        "schema_version", "artifact_kind", "qualification_scope", "publication_scope",
        "resource_contract", "resource_contract_identity_sha256", "dataset_manifest_sha256",
        "datasets", "systems", "pilot_cells", "coverage", "post_run_per_arm_evidence", "content_sha256",
    }, "resource capability manifest")
    _require(value.get("schema_version") == 1 and value.get("artifact_kind") == "vast_pre_run_full_resource_capability_manifest", "resource capability manifest schema/kind drift")
    _require(value.get("qualification_scope") == "pre_run_hardware_and_emitter_capability_only" and value.get("publication_scope") == PUBLICATION_SCOPE, "resource capability scope drift")
    contract = _exact(value["resource_contract"], {"contract_version", "publication_scope", "full_resource_validator_sha256", "interval_validator_sha256"}, "resource contract")
    _require(contract["publication_scope"] == PUBLICATION_SCOPE, "resource contract publication scope drift")
    _require(contract["contract_version"] == 2 and all(_valid_sha(contract[field]) for field in ("full_resource_validator_sha256", "interval_validator_sha256")), "resource contract is invalid")
    _require(value.get("resource_contract_identity_sha256") == _canonical_sha(contract), "resource contract self-identity drift")
    _require(_valid_sha(value.get("dataset_manifest_sha256")), "resource dataset manifest identity is invalid")
    datasets = _exact(value["datasets"], set(CODECS), "resource datasets")
    for codec in CODECS:
        dataset = _exact(datasets[codec], {"dataset_name", "manifest_identity_sha256", "source_sha256", "annotation_sha256"}, f"resource dataset {codec}")
        _require(dataset["dataset_name"] == f"kpp_real_{codec}" and _valid_sha(dataset["manifest_identity_sha256"]) and _valid_sha(dataset["annotation_sha256"]), f"resource dataset {codec} identity drift")
        sources = dataset["source_sha256"]
        _require(type(sources) is list and len(sources) == 2 and sources == sorted(set(sources)) and all(_valid_sha(source) for source in sources), f"resource dataset {codec} source identity drift")
    _validate_resource_systems(value["systems"])
    _validate_resource_pilots(value["pilot_cells"], datasets)
    coverage = _exact(value["coverage"], {
        "binding_count", "pilot_cell_count", "accepted_branch_sample_count",
        "minimum_samples_per_branch_coordinate", "systems", "resources",
        "codecs", "topology_kinds", "branches",
    }, "resource capability coverage")
    _require(
        {
            key: coverage[key]
            for key in coverage if key != "accepted_branch_sample_count"
        }
        == {
            "binding_count": 8, "pilot_cell_count": 32,
            "minimum_samples_per_branch_coordinate": 30, "systems": 4,
            "resources": 2, "codecs": 2, "topology_kinds": 2,
            "branches": 4,
        },
        "resource capability coverage drift",
    )
    accepted_count = coverage["accepted_branch_sample_count"]
    _require(
        type(accepted_count) is int
        and accepted_count >= 3840
        and accepted_count
        == sum(cell["accepted_branch_sample_count"] for cell in value["pilot_cells"]),
        "resource capability accepted sample coverage drift",
    )
    _require(value["post_run_per_arm_evidence"] == {
        "required": True,
        "acceptance_artifact_kind": "checkpoint_publication_runtime_acceptance",
        "validator": "validate_full_resource_evidence",
        "configuration_evidence_accepted_mutated": False,
    }, "resource post-run evidence boundary drift")
    _self_hash(value, "content_sha256", "resource capability manifest")


def _validate_resource_systems(value: Any) -> None:
    systems = _exact(value, set(SYSTEMS), "resource capability systems")
    emitter_roles = ("resource_intervals", "hardware_resource_samples", "fanout_work_counters")
    for system in SYSTEMS:
        system_entry = _exact(systems[system], {"resources"}, f"resource system {system}")
        resources = _exact(system_entry["resources"], set(RESOURCES), f"resource system {system} resources")
        for resource in RESOURCES:
            label = f"resource binding {system}/{resource}"
            binding = _exact(resources[resource], {"status", "implementation_id", "implementation_sha256", "runtime_binding", "runtime_identity", "emitters"}, label)
            _require(binding["status"] == "implemented_and_pre_run_pilot_required" and _valid_id(binding["implementation_id"]) and _valid_sha(binding["implementation_sha256"]) and _valid_id(binding["runtime_binding"]), f"{label} identity is invalid")
            runtime = _exact(binding["runtime_identity"], {"runtime_backend", "analytics_device_api", "decoder_device_api", "worker_image_digest", "implementation_version", "hardware_binding_id"}, f"{label} runtime identity")
            _require(all(_valid_id(runtime[field]) for field in ("runtime_backend", "analytics_device_api", "decoder_device_api", "implementation_version", "hardware_binding_id")), f"{label} runtime identity is incomplete")
            _require(type(runtime["worker_image_digest"]) is str and runtime["worker_image_digest"].startswith("sha256:") and _valid_sha(runtime["worker_image_digest"][7:]), f"{label} image identity is invalid")
            emitters = _exact(binding["emitters"], set(emitter_roles), f"{label} emitters")
            for role in emitter_roles:
                emitter = _exact(emitters[role], {"status", "emitter_id", "artifact_sha256", "telemetry_source"}, f"{label} emitter {role}")
                _require(emitter["status"] == "native_emitter_implementation_bound" and emitter["telemetry_source"] == "native" and _valid_id(emitter["emitter_id"]) and _valid_sha(emitter["artifact_sha256"]), f"{label} emitter {role} is not bound")


def _validate_resource_pilots(value: Any, datasets: Mapping[str, Any]) -> None:
    _require(type(value) is list and len(value) == 32, "resource pilot cell set must contain exactly 32 cells")
    expected_coordinates = sorted((system, resource, codec, topology) for system in SYSTEMS for resource in RESOURCES for codec in CODECS for topology in TOPOLOGIES)
    observed: list[tuple[str, str, str, str]] = []
    evidence_roles = {"checkpoint_acceptance", "frames", "frame_events", "ingress_ledger", "topology_events", "resource_intervals", "hardware_resource_samples", "fanout_work_counters"}
    for position, raw in enumerate(value):
        cell = _exact(raw, {"system", "resource", "codec", "topology_kind", "run_id", "dataset_name", "source_sha256", "evidence_sha256", "resource_summary", "accepted_samples_by_branch", "accepted_branch_sample_count"}, f"resource pilot[{position}]")
        coordinate = (str(cell["system"]), str(cell["resource"]), str(cell["codec"]), str(cell["topology_kind"]))
        observed.append(coordinate)
        _require(_valid_id(cell["run_id"]), f"resource pilot {coordinate} run_id is invalid")
        codec = coordinate[2]
        _require(codec in CODECS and cell["dataset_name"] == f"kpp_real_{codec}" and cell["source_sha256"] == datasets[codec]["source_sha256"], f"resource pilot {coordinate} dataset binding drift")
        evidence = _exact(cell["evidence_sha256"], evidence_roles, f"resource pilot {coordinate} evidence")
        _require(all(_valid_sha(item) for item in evidence.values()), f"resource pilot {coordinate} evidence identity is invalid")
        samples = _exact(cell["accepted_samples_by_branch"], set(BRANCHES), f"resource pilot {coordinate} samples")
        _require(all(type(count) is int and count >= 30 for count in samples.values()) and cell["accepted_branch_sample_count"] == sum(samples.values()), f"resource pilot {coordinate} sample coverage drift")
        summary = _exact(cell["resource_summary"], {"resource_contract_version", "evidence_accepted", "publication_bundle_bound", "full_resource_coverage_complete", "nvdec_busy_equivalent_ns", "nvdec_counter_scope", "fanout_thread_cpu_time_ns", "fanout_work_units", "fanout_counter_scope"}, f"resource pilot {coordinate} summary")
        _require(summary["resource_contract_version"] == 2 and summary["evidence_accepted"] is True and summary["publication_bundle_bound"] is True and summary["full_resource_coverage_complete"] is True, f"resource pilot {coordinate} is not accepted")
        _require(type(summary["nvdec_busy_equivalent_ns"]) is int and summary["nvdec_busy_equivalent_ns"] > 0 and summary["nvdec_counter_scope"] == "device_sample" and summary["fanout_counter_scope"] == "per_trace_resource_work", f"resource pilot {coordinate} counter scope drift")
        expected_positive = coordinate[3] == "shared_video_dag"
        for field in ("fanout_thread_cpu_time_ns", "fanout_work_units"):
            count = summary[field]
            _require(type(count) is int and ((count > 0) if expected_positive else count == 0), f"resource pilot {coordinate} {field} drift")
    _require(observed == expected_coordinates, "resource pilot coordinates are not exact, unique, and sorted")


POLICIES = ("cpu_only", "gpu_only", "static_hybrid", "heft", "deadline_aware_heft", "queue_aware_edf", "adaptive_weights")
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)


def _backend_coverage(*, system_count: int | None = None) -> dict[str, Any]:
    scale = 1 if system_count is None else system_count
    result: dict[str, Any] = {
        "hardware_pilot_cell_count": 4 * scale,
        "benchmark_arm_pilot_count": 4 * scale,
        "runtime_cell_count": 140 * scale,
        "resource_branch_execution_count": 32 * scale,
        "codecs": list(CODECS),
        "topology_kinds": list(TOPOLOGIES),
        "resources": list(RESOURCES),
        "policies": list(POLICIES),
        "deadlines_ms": list(DEADLINES_MS),
        "analytics_branches": list(BRANCHES),
    }
    if system_count is not None:
        result = {"system_count": system_count, **result}
    return result


def _validate_backend_receipt(value: Mapping[str, Any], *, system: str) -> None:
    _exact(value, {
        "schema_version", "artifact_kind", "status", "qualification_scope", "system",
        "qualification_index_sha256", "dataset_manifest_sha256", "policy_contract_sha256",
        "policy_qualification_receipt_sha256", "resource_contract_identity_sha256",
        "resource_qualification_receipt_sha256", "analytics_execution_config_identity_sha256",
        "model_parity_manifest_identity_sha256", "runtime_binding_identity_sha256", "coverage",
        "post_run_per_arm_evidence_required", "configuration_evidence_accepted_mutated", "sha256",
    }, f"backend receipt {system}")
    _require(value.get("schema_version") == 1 and value.get("artifact_kind") == "vast_backend_runtime_qualification_receipt", f"backend receipt {system} schema/kind drift")
    _require(value.get("status") == "accepted_pre_run_backend_runtime_qualification" and value.get("qualification_scope") == "backend_native_runtime_hardware_capability_only" and value.get("system") == system, f"backend receipt {system} is not accepted")
    sha_fields = ("qualification_index_sha256", "dataset_manifest_sha256", "policy_contract_sha256", "policy_qualification_receipt_sha256", "resource_contract_identity_sha256", "resource_qualification_receipt_sha256", "analytics_execution_config_identity_sha256", "model_parity_manifest_identity_sha256", "runtime_binding_identity_sha256")
    _require(all(_valid_sha(value.get(field)) for field in sha_fields), f"backend receipt {system} identity is incomplete")
    _require(value.get("coverage") == _backend_coverage(), f"backend receipt {system} coverage drift")
    _require(value.get("post_run_per_arm_evidence_required") is True and value.get("configuration_evidence_accepted_mutated") is False, f"backend receipt {system} confused pre-run capability with per-arm acceptance")
    _self_hash(value, "sha256", f"backend receipt {system}")


def _backend_v2_coverage(*, system_count: int) -> dict[str, Any]:
    return {
        "system_count": system_count,
        "runtime_cell_count": 140 * system_count,
        "cells_per_system": 140,
    }


_BACKEND_V2_UPSTREAM_FIELDS = {
    "dataset_manifest_sha256",
    "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
}
_BACKEND_V2_CELL_FIELDS = {
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "cell_identity_sha256", "raw_evidence",
    "launcher_invocation_sha256", "validator_identity_sha256",
    "validation_record_sha256",
}


def _validate_backend_receipt_v2(
    value: Mapping[str, Any], *, system: str, registry: _Registry,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _exact(value, {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "system", "qualification_index_sha256", "upstream_identities",
        "runtime_binding_identity_sha256", "launcher", "launcher_invocation",
        "launcher_kind",
        "publication_capable", "qualified_cells", "qualified_cells_sha256",
        "raw_evidence_set_sha256", "coverage",
        "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated", "sha256",
    }, f"backend receipt v2 {system}")
    _require(
        value.get("schema_version") == 2
        and value.get("artifact_kind") == "vast_backend_runtime_qualification_receipt"
        and value.get("status") == "accepted_pre_run_backend_runtime_qualification_v2"
        and value.get("qualification_scope")
        == "backend_native_runtime_evidence_backed_cells_v2"
        and value.get("system") == system,
        f"backend receipt v2 {system} is not accepted",
    )
    _require(
        _valid_sha(value.get("qualification_index_sha256"))
        and _valid_sha(value.get("runtime_binding_identity_sha256")),
        f"backend receipt v2 {system} identity is incomplete",
    )
    upstream = _exact(
        value.get("upstream_identities"),
        _BACKEND_V2_UPSTREAM_FIELDS,
        f"backend receipt v2 {system} upstream identities",
    )
    _require(
        all(_valid_sha(item) for item in upstream.values()),
        f"backend receipt v2 {system} upstream identity is invalid",
    )
    _require(
        value.get("launcher_kind") == "dedicated_publication_runtime"
        and value.get("publication_capable") is True,
        f"backend receipt v2 {system} launcher is engineering-only or nonpublication",
    )
    launcher_record, _ = registry.add(
        value.get("launcher"), f"backend receipt v2 {system} launcher"
    )
    try:
        from backend_publication_dispatch import (
            runtime_binding_identity,
            validate_launcher_invocation,
        )

        launcher_invocation = validate_launcher_invocation(
            value.get("launcher_invocation")
        )
    except Exception as error:
        raise IdentityArtifactError(
            f"backend receipt v2 {system} launcher invocation is invalid: {error}"
        ) from error
    _require(
        value.get("runtime_binding_identity_sha256")
        == runtime_binding_identity(
            system=system,
            launcher=launcher_record,
            launcher_invocation=launcher_invocation,
            upstream_identities=upstream,
        ),
        f"backend receipt v2 {system} runtime binding identity drift",
    )
    cells = value.get("qualified_cells")
    _require(
        type(cells) is list and len(cells) == 140,
        f"backend receipt v2 {system} must contain exactly 140 cells",
    )
    expected = {
        (system, codec, topology, policy, deadline)
        for codec in CODECS for topology in TOPOLOGIES
        for policy in POLICIES for deadline in DEADLINES_MS
    }
    observed: set[tuple[str, str, str, str, int | float]] = set()
    normalized_cells: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    for position, raw in enumerate(cells):
        cell = _exact(
            raw, _BACKEND_V2_CELL_FIELDS,
            f"backend receipt v2 {system} cell[{position}]",
        )
        deadline = cell.get("deadline_ms")
        _require(
            type(deadline) in {int, float}
            and math.isfinite(float(deadline))
            and deadline in DEADLINES_MS,
            f"backend receipt v2 {system} cell deadline type drift",
        )
        coordinate = (
            str(cell.get("system")), str(cell.get("codec")),
            str(cell.get("topology_kind")), str(cell.get("policy")), deadline,
        )
        _require(
            coordinate in expected and coordinate not in observed,
            f"backend receipt v2 {system} cell is missing, duplicate, or relabelled",
        )
        coordinate_value = {
            "system": coordinate[0], "codec": coordinate[1],
            "topology_kind": coordinate[2], "policy": coordinate[3],
            "deadline_ms": coordinate[4],
        }
        _require(
            cell.get("cell_identity_sha256") == _canonical_sha(coordinate_value),
            f"backend receipt v2 {system} cell identity drift",
        )
        evidence_record, _ = registry.add(
            cell.get("raw_evidence"),
            f"backend receipt v2 {system} cell[{position}] raw evidence",
        )
        _require(
            _valid_sha(cell.get("validator_identity_sha256"))
            and _valid_sha(cell.get("validation_record_sha256")),
            f"backend receipt v2 {system} validator identity is invalid",
        )
        _require(
            cell.get("launcher_invocation_sha256")
            == launcher_invocation["invocation_sha256"],
            f"backend receipt v2 {system} cell launcher invocation binding drift",
        )
        normalized_cells.append({
            **coordinate_value,
            "cell_identity_sha256": cell["cell_identity_sha256"],
            "raw_evidence": evidence_record,
            "launcher_invocation_sha256": cell[
                "launcher_invocation_sha256"
            ],
            "validator_identity_sha256": cell["validator_identity_sha256"],
            "validation_record_sha256": cell["validation_record_sha256"],
        })
        evidence_records.append(evidence_record)
        observed.add(coordinate)
    _require(
        observed == expected
        and value.get("qualified_cells_sha256") == _canonical_sha(normalized_cells)
        and value.get("raw_evidence_set_sha256") == _canonical_sha(evidence_records),
        f"backend receipt v2 {system} cell/evidence set hash drift",
    )
    _require(
        value.get("coverage") == _backend_v2_coverage(system_count=1),
        f"backend receipt v2 {system} coverage drift",
    )
    _require(
        value.get("post_run_per_arm_evidence_required") is True
        and value.get("configuration_evidence_accepted_mutated") is False,
        f"backend receipt v2 {system} confused pre-run capability with arm acceptance",
    )
    _self_hash(value, "sha256", f"backend receipt v2 {system}")
    return ({
        "system": system,
        "runtime_binding_identity_sha256": value["runtime_binding_identity_sha256"],
        "launcher": launcher_record,
        "launcher_invocation": launcher_invocation,
        "launcher_kind": "dedicated_publication_runtime",
        "publication_capable": True,
        "qualified_cells": normalized_cells,
        "qualified_cells_sha256": value["qualified_cells_sha256"],
        "raw_evidence_set_sha256": value["raw_evidence_set_sha256"],
    }, dict(upstream))


def _validate_backends_v2(
    binding: Mapping[str, Any], *, registry: _Registry,
    index_record: Mapping[str, Any], index_path: Path,
    index: Mapping[str, Any],
    parity_identity: str, parity_acceptance_binding_sha256: str,
    execution_identity: str,
    policy_record: Mapping[str, Any], policy_receipt: Mapping[str, Any],
    resource_record: Mapping[str, Any], resource_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    receipts_map = _exact(binding["receipts"], set(SYSTEMS), "backend v2 receipt descriptors")
    receipt_records: dict[str, Any] = {}
    receipt_values: dict[str, Any] = {}
    systems: dict[str, Any] = {}
    receipt_upstreams: dict[str, Any] = {}
    for system in SYSTEMS:
        record, path = registry.add(receipts_map[system], f"backend v2 receipt {system}")
        _require(
            path.name == f"checkpoint_{system}_backend_runtime_qualification_receipt.json",
            f"backend v2 receipt {system} filename drift",
        )
        value = _read_object(path, f"backend v2 receipt {system}")
        system_value, upstream = _validate_backend_receipt_v2(
            value, system=system, registry=registry,
        )
        receipt_records[system] = record
        receipt_values[system] = value
        systems[system] = system_value
        receipt_upstreams[system] = upstream
    _exact(index, {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "qualification_index_sha256", "upstream_identities", "systems",
        "receipts", "coverage", "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated", "sha256",
    }, "backend runtime qualification v2 binding index")
    _require(
        index.get("schema_version") == 2
        and index.get("artifact_kind") == "vast_backend_runtime_qualification_binding_index"
        and index.get("status") == "accepted_pre_run_backend_runtime_qualification_set_v2"
        and index.get("qualification_scope")
        == "backend_native_runtime_evidence_backed_cells_v2",
        "backend runtime qualification v2 binding index is not accepted",
    )
    _require(
        index.get("systems") == list(SYSTEMS)
        and index.get("coverage") == _backend_v2_coverage(system_count=4),
        "backend runtime qualification v2 index coverage drift",
    )
    embedded = _exact(index["receipts"], set(SYSTEMS), "backend v2 embedded receipts")
    upstream = _exact(
        index.get("upstream_identities"), _BACKEND_V2_UPSTREAM_FIELDS,
        "backend v2 index upstream identities",
    )
    expected_upstream = {
        "dataset_manifest_sha256": policy_receipt["dataset_manifest_sha256"],
        "policy_contract_sha256": policy_receipt["policy_contract_sha256"],
        "policy_qualification_receipt_sha256": policy_record["sha256"],
        "resource_contract_identity_sha256": resource_receipt["resource_contract_identity_sha256"],
        "resource_qualification_receipt_sha256": resource_record["sha256"],
        "analytics_execution_config_identity_sha256": execution_identity,
        "model_parity_manifest_identity_sha256": parity_identity,
        "model_parity_acceptance_binding_sha256": parity_acceptance_binding_sha256,
    }
    _require(
        dict(upstream) == expected_upstream
        and all(receipt_upstreams[system] == expected_upstream for system in SYSTEMS),
        "backend runtime qualification v2 upstream cross-binding drift",
    )
    _require(
        _valid_sha(index.get("qualification_index_sha256"))
        and all(
            receipt_values[system]["qualification_index_sha256"]
            == index["qualification_index_sha256"]
            for system in SYSTEMS
        ),
        "backend runtime qualification v2 index identity drift",
    )
    for system in SYSTEMS:
        registry.verify_embedded(
            embedded[system], receipt_records[system],
            f"backend v2 index receipt {system}", base=index_path.parent,
        )
    _require(
        index.get("post_run_per_arm_evidence_required") is True
        and index.get("configuration_evidence_accepted_mutated") is False,
        "backend runtime qualification v2 index confused pre-run capability with arm acceptance",
    )
    _self_hash(index, "sha256", "backend runtime qualification v2 binding index")
    return {
        "schema_version": 2,
        "qualification_index_sha256": index["qualification_index_sha256"],
        "binding_index": index_record,
        "receipts": receipt_records,
        "upstream_identities": dict(upstream),
        "systems": systems,
        "coverage": _backend_v2_coverage(system_count=4),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }


_BACKEND_V3_CANDIDATE_STATUS = (
    "qualified_runtime_authority_catalog_v3_pre_identity_candidate"
)
_BACKEND_V3_CANDIDATE_SCOPE = (
    "backend_runtime_authority_catalog_v3_pre_identity_only"
)
_BACKEND_V3_INDEX_FIELDS = {
    "schema_version", "artifact_kind", "status", "qualification_scope",
    "qualification_index_sha256", "catalog_sha256", "upstream_identities",
    "systems", "receipts", "coverage",
    "post_run_per_arm_evidence_required",
    "configuration_evidence_accepted_mutated", "binding_sha256",
}
_BACKEND_V3_RECEIPT_FIELDS = {
    "schema_version", "artifact_kind", "status", "qualification_scope",
    "system", "qualification_index_sha256", "upstream_identities",
    "runtime_binding_identity_sha256", "runtime_authority_set_sha256",
    "runtime_authorities", "launcher", "launcher_invocation",
    "launcher_kind", "publication_capable", "qualified_cells",
    "qualified_cells_sha256", "raw_evidence_set_sha256", "coverage",
    "post_run_per_arm_evidence_required",
    "configuration_evidence_accepted_mutated", "receipt_sha256",
}
_BACKEND_V3_CATALOG_SYSTEM_FIELDS = {
    "system", "runtime_binding_identity_sha256",
    "runtime_authority_set_sha256", "runtime_authorities", "launcher",
    "launcher_invocation", "launcher_kind", "publication_capable",
    "qualified_cells", "qualified_cells_sha256", "raw_evidence_set_sha256",
}
_BACKEND_V3_AUTHORIZATION_BLOCKERS = sorted({
    "analytics_authority_provenance_not_independently_validated",
    "identity_registry_handle_bound_payload_reader_not_implemented",
    "launcher_invocation_abi_v2_requires_requalification_for_v3",
    "runtime_authority_schema_v1_upstream_crossbinding_incomplete",
    "trusted_validator_authority_not_bound",
    "validation_records_not_physically_registered_or_replayed",
})


def _backend_v3_coverage(*, system_count: int) -> dict[str, int]:
    return {
        "system_count": system_count,
        "runtime_authority_count": 28 * system_count,
        "runtime_authorities_per_system": 28,
        "runtime_cell_count": 140 * system_count,
        "cells_per_system": 140,
        "deadlines_per_runtime_authority": 5,
    }


def _runtime_authority_leaf_descriptors(
    authority: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Enumerate only physical leaf descriptors from a public normalized schema."""
    dataset = authority["dataset"]
    descriptors = [dataset["manifest"], *dataset["files"]]
    descriptors.extend(
        item["descriptor"]
        for section in ("source_runtime_artifacts", "backend_runtime_artifacts")
        for item in authority[section]
    )
    analytics = authority["analytics_authority"]
    descriptors.append(analytics["capability"]["descriptor"])
    descriptors.extend(item["descriptor"] for item in analytics["bindings"])
    policy = authority["policy_authority"]
    descriptors.extend(
        item["descriptor"]
        for item in (
            policy["capability"], policy["calibration"], policy["static_map"]
        )
        if item is not None
    )
    return [dict(item) for item in descriptors]


def _validate_runtime_authority_candidate_crossbinding(
    authority: Mapping[str, Any], *, upstream: Mapping[str, Any],
    policy_outputs: Mapping[str, Any], label: str,
) -> None:
    """Enforce the semantic bindings representable by authority schema v1."""
    _require(
        authority["dataset"]["manifest"]["sha256"]
        == upstream["dataset_manifest_sha256"],
        f"{label} dataset manifest upstream cross-binding drift",
    )
    _require(
        authority["resource_contract"]["content_identity_sha256"]
        == upstream["resource_contract_identity_sha256"],
        f"{label} resource contract upstream cross-binding drift",
    )
    _require(
        authority["model_parity_acceptance_binding_sha256"]
        == upstream["model_parity_acceptance_binding_sha256"],
        f"{label} parity acceptance upstream cross-binding drift",
    )
    _require(
        authority["policy_authority"]["capability"]["descriptor"]
        == policy_outputs["capability_manifest"]
        and authority["policy_authority"]["calibration"]["descriptor"]
        == policy_outputs["calibration_mapping"],
        f"{label} policy authority artifact cross-binding drift",
    )


def _validate_backend_receipt_v3_candidate(
    value: Mapping[str, Any], *, system: str,
) -> dict[str, Any]:
    _exact(value, _BACKEND_V3_RECEIPT_FIELDS, f"backend receipt v3 {system}")
    _require(
        value.get("schema_version") == 3
        and value.get("artifact_kind")
        == "vast_backend_runtime_qualification_v3_receipt"
        and value.get("status") == _BACKEND_V3_CANDIDATE_STATUS
        and value.get("qualification_scope") == _BACKEND_V3_CANDIDATE_SCOPE
        and value.get("system") == system,
        f"backend receipt v3 {system} is not the persisted pre-identity candidate",
    )
    _require(
        _valid_sha(value.get("qualification_index_sha256"))
        and value.get("coverage") == _backend_v3_coverage(system_count=1),
        f"backend receipt v3 {system} identity/coverage drift",
    )
    _require(
        value.get("post_run_per_arm_evidence_required") is True
        and value.get("configuration_evidence_accepted_mutated") is False,
        f"backend receipt v3 {system} crossed the pre-identity boundary",
    )
    _self_hash(value, "receipt_sha256", f"backend receipt v3 {system}")
    return {
        field: json.loads(_canonical_bytes(value[field]).decode("utf-8"))
        for field in _BACKEND_V3_CATALOG_SYSTEM_FIELDS
    }


def _validate_backends_v3(
    binding: Mapping[str, Any], *, registry: _Registry,
    index_record: Mapping[str, Any], index_path: Path,
    index: Mapping[str, Any],
    parity_identity: str, parity_acceptance_binding_sha256: str,
    execution_identity: str,
    policy_record: Mapping[str, Any], policy_receipt: Mapping[str, Any],
    policy_outputs: Mapping[str, Any],
    resource_record: Mapping[str, Any], resource_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind persisted v3 candidates physically without authorizing execution."""
    from backend_publication_runtime_authority import (
        assess_backend_publication_runtime_authority,
        validate_backend_publication_runtime_authority,
    )
    from backend_runtime_qualification_v3 import (
        validate_backend_runtime_qualification_v3_catalog,
    )

    receipts_map = _exact(
        binding["receipts"], set(SYSTEMS), "backend v3 receipt descriptors",
    )
    policy_artifacts = _exact(
        policy_outputs, {"capability_manifest", "calibration_mapping"},
        "backend v3 policy authority outputs",
    )
    _require(
        index_path.name
        == "checkpoint_backend_runtime_qualification_v3_binding_index.json",
        "backend runtime qualification v3 binding index filename drift",
    )
    _exact(index, _BACKEND_V3_INDEX_FIELDS, "backend v3 binding index")
    _require(
        index.get("schema_version") == 3
        and index.get("artifact_kind")
        == "vast_backend_runtime_qualification_v3_binding_index"
        and index.get("status") == _BACKEND_V3_CANDIDATE_STATUS
        and index.get("qualification_scope") == _BACKEND_V3_CANDIDATE_SCOPE,
        "backend v3 binding index is not the persisted pre-identity candidate",
    )
    _require(
        index.get("systems") == list(SYSTEMS)
        and index.get("coverage") == _backend_v3_coverage(system_count=4)
        and _valid_sha(index.get("qualification_index_sha256"))
        and _valid_sha(index.get("catalog_sha256")),
        "backend v3 binding index identity/coverage drift",
    )
    _require(
        index.get("post_run_per_arm_evidence_required") is True
        and index.get("configuration_evidence_accepted_mutated") is False,
        "backend v3 binding index crossed the pre-identity boundary",
    )
    _self_hash(index, "binding_sha256", "backend v3 binding index")

    receipt_records: dict[str, dict[str, Any]] = {}
    receipt_values: dict[str, dict[str, Any]] = {}
    catalog_systems: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        record, path = registry.add(
            receipts_map[system], f"backend receipt v3 {system}",
        )
        _require(
            path.name
            == f"checkpoint_{system}_backend_runtime_qualification_v3_receipt.json",
            f"backend receipt v3 {system} filename drift",
        )
        value = _read_registered_object(
            registry, record, path, f"backend receipt v3 {system}",
        )
        catalog_systems[system] = _validate_backend_receipt_v3_candidate(
            value, system=system,
        )
        receipt_records[system] = record
        receipt_values[system] = value

    embedded_receipts = _exact(
        index["receipts"], set(SYSTEMS), "backend v3 index receipts",
    )
    upstream = _exact(
        index["upstream_identities"],
        _BACKEND_V2_UPSTREAM_FIELDS,
        "backend v3 upstream identities",
    )
    expected_upstream = {
        "dataset_manifest_sha256": policy_receipt["dataset_manifest_sha256"],
        "policy_contract_sha256": policy_receipt["policy_contract_sha256"],
        "policy_qualification_receipt_sha256": policy_record["sha256"],
        "resource_contract_identity_sha256": resource_receipt[
            "resource_contract_identity_sha256"
        ],
        "resource_qualification_receipt_sha256": resource_record["sha256"],
        "analytics_execution_config_identity_sha256": execution_identity,
        "model_parity_manifest_identity_sha256": parity_identity,
        "model_parity_acceptance_binding_sha256": (
            parity_acceptance_binding_sha256
        ),
    }
    _require(
        dict(upstream) == expected_upstream
        and all(
            receipt_values[system]["upstream_identities"] == expected_upstream
            and receipt_values[system]["qualification_index_sha256"]
            == index["qualification_index_sha256"]
            for system in SYSTEMS
        ),
        "backend v3 upstream/candidate identity cross-binding drift",
    )
    for system in SYSTEMS:
        registry.verify_embedded(
            embedded_receipts[system], receipt_records[system],
            f"backend v3 index receipt {system}", base=index_path.parent,
        )

    candidate_catalog = {
        "schema_version": 3,
        "artifact_kind": "vast_backend_runtime_qualification_v3_catalog",
        "status": _BACKEND_V3_CANDIDATE_STATUS,
        "publication_scope": _BACKEND_V3_CANDIDATE_SCOPE,
        "qualification_index_sha256": index["qualification_index_sha256"],
        "upstream_identities": dict(upstream),
        "systems": catalog_systems,
        "coverage": _backend_v3_coverage(system_count=4),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
        "catalog_sha256": index["catalog_sha256"],
    }
    try:
        catalog = validate_backend_runtime_qualification_v3_catalog(
            candidate_catalog
        )
    except Exception as error:
        raise IdentityArtifactError(
            f"backend v3 persisted candidate catalog rejected: {error}"
        ) from error

    normalized_systems: dict[str, dict[str, Any]] = {}
    global_leaves: dict[str, dict[str, Any]] = {}
    observed_validator_identities: set[str] = set()
    for system in SYSTEMS:
        source_system = catalog["systems"][system]
        system_leaves: dict[str, dict[str, Any]] = {}
        normalized_authorities: list[dict[str, Any]] = []
        for position, authority_record in enumerate(
            source_system["runtime_authorities"]
        ):
            authority_artifact, authority_path = registry.add(
                authority_record["artifact"],
                f"backend v3 {system} runtime authority[{position}]",
            )
            authority_value = _read_registered_object(
                registry, authority_artifact, authority_path,
                f"backend v3 {system} runtime authority[{position}]",
            )
            try:
                authority = validate_backend_publication_runtime_authority(
                    authority_value,
                    expected_system=authority_record["system"],
                    expected_codec=authority_record["codec"],
                    expected_topology_kind=authority_record["topology_kind"],
                    expected_policy=authority_record["policy"],
                )
            except Exception as error:
                raise IdentityArtifactError(
                    f"backend v3 runtime authority[{position}] rejected: {error}"
                ) from error
            _require(
                authority["authority_sha256"]
                == authority_record["runtime_authority_sha256"],
                f"backend v3 {system} runtime authority semantic identity drift",
            )
            _validate_runtime_authority_candidate_crossbinding(
                authority, upstream=upstream, policy_outputs=policy_artifacts,
                label=f"backend v3 {system} runtime authority[{position}]",
            )
            physical = assess_backend_publication_runtime_authority(
                authority,
                project_root=registry.root,
                expected_system=authority_record["system"],
                expected_codec=authority_record["codec"],
                expected_topology_kind=authority_record["topology_kind"],
                expected_policy=authority_record["policy"],
            )
            _require(
                physical.get("status") == "physically_valid",
                "backend v3 runtime authority physical assessment blocked: "
                + ";".join(str(item) for item in physical.get("blockers", [])),
            )
            for leaf_position, leaf in enumerate(
                _runtime_authority_leaf_descriptors(authority)
            ):
                normalized_leaf, _ = registry.add_shared(
                    leaf,
                    f"backend v3 {system} authority[{position}] leaf[{leaf_position}]",
                )
                previous = system_leaves.get(normalized_leaf["path"])
                _require(
                    previous is None or previous == normalized_leaf,
                    "backend v3 recurring system leaf descriptor drift",
                )
                system_leaves[normalized_leaf["path"]] = normalized_leaf
                global_previous = global_leaves.get(normalized_leaf["path"])
                _require(
                    global_previous is None or global_previous == normalized_leaf,
                    "backend v3 recurring global leaf descriptor drift",
                )
                global_leaves[normalized_leaf["path"]] = normalized_leaf
            normalized_authorities.append({
                **{
                    field: authority_record[field]
                    for field in (
                        "system", "codec", "topology_kind", "policy",
                        "runtime_authority_sha256",
                    )
                },
                "artifact": authority_artifact,
            })

        launcher_record, _ = registry.add(
            source_system["launcher"], f"backend v3 {system} launcher",
        )
        normalized_cells: list[dict[str, Any]] = []
        for position, cell in enumerate(source_system["qualified_cells"]):
            evidence_record, _ = registry.add(
                cell["raw_evidence"],
                f"backend v3 {system} raw evidence[{position}]",
            )
            normalized_cell = dict(cell)
            normalized_cell["raw_evidence"] = evidence_record
            normalized_cells.append(normalized_cell)
            observed_validator_identities.add(cell["validator_identity_sha256"])
        sorted_system_leaves = [
            system_leaves[path] for path in sorted(system_leaves)
        ]
        normalized_systems[system] = {
            **{
                field: json.loads(
                    _canonical_bytes(source_system[field]).decode("utf-8")
                )
                for field in _BACKEND_V3_CATALOG_SYSTEM_FIELDS
                if field
                not in {"runtime_authorities", "launcher", "qualified_cells"}
            },
            "runtime_authorities": normalized_authorities,
            "launcher": launcher_record,
            "qualified_cells": normalized_cells,
            "runtime_authority_leaves": sorted_system_leaves,
            "runtime_authority_leaf_set_sha256": _canonical_sha(
                sorted_system_leaves
            ),
        }

    sorted_global_leaves = [global_leaves[path] for path in sorted(global_leaves)]
    _require(
        len(observed_validator_identities) == 1,
        "backend v3 candidate validator identity is not globally consistent",
    )
    observed_validator_identity = next(iter(observed_validator_identities))
    normalized: dict[str, Any] = {
        "schema_version": 3,
        "artifact_kind": (
            "vast_full_publication_backend_runtime_qualification_binding_v3"
        ),
        "source_status": _BACKEND_V3_CANDIDATE_STATUS,
        "source_qualification_scope": _BACKEND_V3_CANDIDATE_SCOPE,
        "authorization_eligible": False,
        "validation_trust_status": "untrusted_callback_evidence_only",
        "semantic_crossbinding_complete": False,
        "authorization_blockers": list(_BACKEND_V3_AUTHORIZATION_BLOCKERS),
        "observed_validator_identity_sha256": observed_validator_identity,
        "qualification_index_sha256": index["qualification_index_sha256"],
        "catalog_sha256": index["catalog_sha256"],
        "binding_index": index_record,
        "receipts": receipt_records,
        "upstream_identities": dict(upstream),
        "systems": normalized_systems,
        "coverage": _backend_v3_coverage(system_count=4),
        "runtime_authority_leaves": sorted_global_leaves,
        "runtime_authority_leaf_set_sha256": _canonical_sha(
            sorted_global_leaves
        ),
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    normalized["identity_binding_sha256"] = _canonical_sha(normalized)
    return normalized


def _validate_backends(binding: Any, *, registry: _Registry, parity_identity: str, parity_acceptance_binding_sha256: str, execution_identity: str, policy_record: Mapping[str, Any], policy_receipt: Mapping[str, Any], policy_outputs: Mapping[str, Any], resource_record: Mapping[str, Any], resource_receipt: Mapping[str, Any]) -> dict[str, Any]:
    item = _exact(binding, {"binding_index", "receipts"}, "backend runtime qualification binding")
    index_record, index_path = registry.add(
        item["binding_index"], "backend runtime qualification binding index",
    )
    index_probe = _read_registered_object(
        registry, index_record, index_path,
        "backend runtime qualification binding index",
    )
    if index_probe.get("schema_version") == 3:
        return _validate_backends_v3(
            item, registry=registry, index_record=index_record,
            index_path=index_path, index=index_probe,
            parity_identity=parity_identity,
            parity_acceptance_binding_sha256=parity_acceptance_binding_sha256,
            execution_identity=execution_identity, policy_record=policy_record,
            policy_receipt=policy_receipt, policy_outputs=policy_outputs,
            resource_record=resource_record,
            resource_receipt=resource_receipt,
        )
    if index_probe.get("schema_version") == 2:
        return _validate_backends_v2(
            item, registry=registry, index_record=index_record,
            index_path=index_path, index=index_probe,
            parity_identity=parity_identity,
            parity_acceptance_binding_sha256=parity_acceptance_binding_sha256,
            execution_identity=execution_identity, policy_record=policy_record,
            policy_receipt=policy_receipt, resource_record=resource_record,
            resource_receipt=resource_receipt,
        )
    receipts_map = _exact(item["receipts"], set(SYSTEMS), "backend receipt descriptors")
    receipt_records: dict[str, Any] = {}
    receipt_values: dict[str, Any] = {}
    receipt_paths: dict[str, Path] = {}
    for system in SYSTEMS:
        record, path = registry.add(receipts_map[system], f"backend receipt {system}")
        _require(path.name == f"checkpoint_{system}_backend_runtime_qualification_receipt.json", f"backend receipt {system} filename drift")
        value = _read_object(path, f"backend receipt {system}")
        _validate_backend_receipt(value, system=system)
        receipt_records[system], receipt_values[system], receipt_paths[system] = record, value, path
    index = index_probe
    _exact(index, {"schema_version", "artifact_kind", "status", "qualification_index_sha256", "systems", "receipts", "coverage", "post_run_per_arm_evidence_required", "configuration_evidence_accepted_mutated", "sha256"}, "backend runtime qualification binding index")
    _require(index.get("schema_version") == 1 and index.get("artifact_kind") == "vast_backend_runtime_qualification_binding_index" and index.get("status") == "accepted_pre_run_backend_runtime_qualification_set", "backend binding index is not accepted")
    _require(index.get("systems") == list(SYSTEMS) and index.get("coverage") == _backend_coverage(system_count=4), "backend binding index coverage drift")
    _require(index.get("post_run_per_arm_evidence_required") is True and index.get("configuration_evidence_accepted_mutated") is False, "backend binding index confused pre-run capability with per-arm acceptance")
    _require(_valid_sha(index.get("qualification_index_sha256")), "backend binding index qualification identity is invalid")
    embedded = _exact(index["receipts"], set(SYSTEMS), "backend binding index receipts")
    common = {
        "qualification_index_sha256": index["qualification_index_sha256"],
        "dataset_manifest_sha256": policy_receipt["dataset_manifest_sha256"],
        "policy_contract_sha256": policy_receipt["policy_contract_sha256"],
        "policy_qualification_receipt_sha256": policy_record["sha256"],
        "resource_contract_identity_sha256": resource_receipt["resource_contract_identity_sha256"],
        "resource_qualification_receipt_sha256": resource_record["sha256"],
        "analytics_execution_config_identity_sha256": execution_identity,
        "model_parity_manifest_identity_sha256": parity_identity,
    }
    for system in SYSTEMS:
        registry.verify_embedded(embedded[system], receipt_records[system], f"backend index receipt {system}", base=index_path.parent)
        for field, expected in common.items():
            _require(receipt_values[system][field] == expected, f"backend receipt {system} {field} cross-binding drift")
    _self_hash(index, "sha256", "backend runtime qualification binding index")
    return {"binding_index": index_record, "receipts": receipt_records}


def load_full_publication_identity_artifacts(
    *,
    project_root: Path | str,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    parity_loader: Loader = _default_parity_loader,
    parity_acceptance_loader: Callable[..., Mapping[str, Any]] = (
        _default_parity_acceptance_loader
    ),
    execution_loader: Loader = _default_execution_loader,
    policy_capability_assessor: PolicyAssessor = _default_policy_assessor,
) -> dict[str, Any]:
    """Load only accepted, physical qualification outputs into run identity."""

    root = _root_path(project_root)
    candidate = Path(manifest_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as error:
        raise IdentityArtifactError(
            "full publication identity artifact manifest is missing or outside project_root: "
            f"{candidate}"
        ) from error
    manifest_path_resolved = _resolve_file(root, relative, "identity artifact manifest")
    manifest_descriptor = {
        "path": relative,
        "size_bytes": manifest_path_resolved.stat().st_size,
        "sha256": _hash_file(manifest_path_resolved),
    }
    registry = _Registry(root)
    manifest_record, _ = registry.add(manifest_descriptor, "identity artifact manifest")
    manifest = _read_object(manifest_path_resolved, "identity artifact manifest")
    top = _exact(manifest, {"schema_version", "artifact_kind", "bindings"}, "identity artifact manifest")
    _require(top["schema_version"] == SCHEMA_VERSION and top["artifact_kind"] == MANIFEST_KIND, "identity artifact manifest schema/kind drift")
    bindings = _exact(top["bindings"], {
        "analytics_model_parity", "analytics_execution_layer", "policy_qualification",
        "resource_qualification", "backend_runtime_qualification",
    }, "identity artifact bindings")
    parity_binding, parity_identity = _validate_parity_acceptance_binding(
        bindings["analytics_model_parity"],
        registry=registry,
        root=root,
        loader=parity_acceptance_loader,
    )
    execution_record, execution_identity = _validate_content_binding(
        bindings["analytics_execution_layer"],
        "analytics execution layer",
        registry=registry,
        loader=execution_loader,
        expected_kind="vast_analytics_execution_layer_config",
    )
    policy_binding, policy_receipt = _validate_policy(
        bindings["policy_qualification"],
        registry=registry,
        assessor=policy_capability_assessor,
    )
    resource_binding, resource_receipt, _resource_capability = _validate_resource_binding(
        bindings["resource_qualification"],
        registry=registry,
    )
    policy_receipt_record = policy_binding["receipt"]
    resource_receipt_record = resource_binding["receipt"]
    _require(policy_receipt["dataset_manifest_sha256"] == resource_receipt["dataset_manifest_sha256"], "qualification dataset identity cross-binding drift")
    backend_binding = _validate_backends(
        bindings["backend_runtime_qualification"],
        registry=registry,
        parity_identity=parity_identity,
        parity_acceptance_binding_sha256=parity_binding["binding_sha256"],
        execution_identity=execution_identity,
        policy_record=policy_receipt_record,
        policy_receipt=policy_receipt,
        policy_outputs=policy_binding["outputs"],
        resource_record=resource_receipt_record,
        resource_receipt=resource_receipt,
    )
    canonical_bindings = {
        "analytics_model_parity": parity_binding,
        "analytics_execution_layer": {"artifact": execution_record, "content_identity_sha256": execution_identity},
        "policy_qualification": policy_binding,
        "resource_qualification": resource_binding,
        "backend_runtime_qualification": backend_binding,
    }
    files = [registry.files[path] for path in sorted(registry.files)]
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "manifest": manifest_record,
        "bindings": canonical_bindings,
        "files": files,
        "files_sha256": _canonical_sha(files),
    }
    material["binding_sha256"] = _canonical_sha(material)
    return json.loads(_canonical_bytes(material).decode("utf-8"))


__all__ = [
    "BINDING_KIND",
    "DEFAULT_MANIFEST",
    "IdentityArtifactError",
    "MANIFEST_KIND",
    "SCHEMA_VERSION",
    "load_full_publication_identity_artifacts",
]
