#!/usr/bin/env python3
"""Build a nonaccepted calibration for forced qualification pilots only.

Accepted model-parity physical service and CUDA-event observations are
converted to contract-valid per-system calibrations.  These artifacts are
explicitly fenced from policy acceptance and full-publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
from pathlib import Path
from statistics import median
from functools import wraps
from typing import Any, Callable, Mapping

import checkpoint_model_parity_acceptance as model_parity_acceptance
import publication_policy_contract as policy
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCOPE = "forced_resource_qualification_pilots_only"
STATUS = "qualification_bootstrap_not_accepted"
MAPPING_FILENAME = "checkpoint_policy_qualification_bootstrap_mapping.v2.json"
RECEIPT_FILENAME = "checkpoint_policy_qualification_bootstrap_receipt.v2.json"
CALIBRATION_FILENAME = (
    "checkpoint_policy_qualification_bootstrap_calibration.{system}.v2.json"
)
NATIVE_RESOURCES = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}
CALIBRATION_EVIDENCE_NAMES = {
    "cpu": "cpu_policy_calibration",
    "gpu": "cuda_policy_calibration",
}
_SHA_CHARS = frozenset("0123456789abcdef")


class BootstrapCalibrationV2Error(RuntimeError):
    """Bootstrap input or immutable atomic output is unsafe."""


# Public compatibility name follows the neighbouring qualification-index API.
PolicyQualificationBootstrapV2Error = BootstrapCalibrationV2Error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BootstrapCalibrationV2Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BootstrapCalibrationV2Error(
            "bootstrap material is not canonical JSON"
        ) from exc


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and set(value).issubset(_SHA_CHARS)
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BootstrapCalibrationV2Error(
            f"path stat failed: {path}: {exc}"
        ) from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _physical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise BootstrapCalibrationV2Error(
            f"project_root is unavailable: {project_root}"
        ) from exc
    _require(lexical == resolved, "project_root must be a canonical physical path")
    _require(resolved.is_dir(), "project_root is not a directory")
    _require(not _is_link(resolved), "project_root is a symlink/reparse point")
    _require(
        resolved != Path(resolved.anchor),
        "project_root cannot be a filesystem root",
    )
    return resolved


def _normalized_relative(value: Any, label: str) -> Path:
    _require(
        type(value) is str and value and "\\" not in value,
        f"{label} path is invalid",
    )
    relative = Path(value)
    _require(
        not relative.is_absolute()
        and relative.as_posix() == value
        and all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label} path is not normalized",
    )
    return relative


def _relative_input(root: Path, value: Path | str, label: str) -> str:
    raw = Path(value)
    candidate = Path(
        os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw))
    )
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise BootstrapCalibrationV2Error(f"{label} escaped project_root") from exc
    _resolve_file(root, relative, label)
    return relative


def _resolve_file(root: Path, relative_value: Any, label: str) -> Path:
    relative = _normalized_relative(relative_value, label)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        _require(cursor.exists() or os.path.lexists(cursor), f"{label} is missing")
        _require(
            not _is_link(cursor),
            f"{label} contains a symlink/reparse point",
        )
    try:
        resolved = cursor.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise BootstrapCalibrationV2Error(f"{label} escaped project_root") from exc
    _require(resolved == cursor, f"{label} is an alias")
    info = cursor.lstat()
    _require(stat.S_ISREG(info.st_mode), f"{label} is not a regular file")
    _require(int(info.st_nlink) == 1, f"{label} hardlink alias is prohibited")
    return cursor


def _stable_descriptor(
    root: Path, relative: str, label: str
) -> tuple[dict[str, Any], tuple[int, int]]:
    path = _resolve_file(root, relative, label)
    before = path.stat()
    first = sha256_file(path)
    middle = path.stat()
    second = sha256_file(path)
    after = path.stat()
    identities = [
        (
            int(item.st_dev),
            int(item.st_ino),
            int(item.st_size),
            int(item.st_mtime_ns),
            int(getattr(item, "st_ctime_ns", 0)),
            int(item.st_nlink),
        )
        for item in (before, middle, after)
    ]
    _require(
        identities[0] == identities[1] == identities[2] and first == second,
        f"{label} changed while hashing",
    )
    _require(int(after.st_size) > 0, f"{label} is empty")
    return (
        {"path": relative, "size_bytes": int(after.st_size), "sha256": first},
        (int(after.st_dev), int(after.st_ino)),
    )


class _Registry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, dict[str, Any]] = {}
        self.identities: dict[tuple[int, int], str] = {}

    def add(self, relative: str, label: str) -> dict[str, Any]:
        _require(
            relative not in self.records,
            f"{label} duplicates a physical path",
        )
        record, identity = _stable_descriptor(self.root, relative, label)
        _require(
            identity not in self.identities,
            f"{label} aliases {self.identities.get(identity, '')}",
        )
        self.records[relative] = record
        self.identities[identity] = relative
        return record


def _descriptor_fields(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict, f"{label} descriptor must be an object")
    _require(
        set(value) == {"path", "size_bytes", "sha256"},
        f"{label} descriptor fields drifted",
    )
    _normalized_relative(value.get("path"), label)
    _require(
        type(value.get("size_bytes")) is int and value["size_bytes"] > 0,
        f"{label} descriptor size is invalid",
    )
    _require(
        _valid_sha(value.get("sha256")),
        f"{label} descriptor SHA-256 is invalid",
    )
    return dict(value)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapCalibrationV2Error(f"invalid {label}: {exc}") from exc
    _require(type(value) is dict, f"{label} must be a JSON object")
    return value


def _load_model_parity_manifest(path: Path) -> Mapping[str, Any]:
    try:
        import yaml
        header = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise BootstrapCalibrationV2Error(
            f"invalid accepted model-parity manifest header: {exc}"
        ) from exc
    coordinate = (
        header.get("schema_version") if type(header) is dict else None,
        header.get("artifact_kind") if type(header) is dict else None,
    )
    if coordinate == (3, "checkpoint_analytics_model_parity_manifest"):
        from checkpoint_model_parity import load_parity_manifest
        return load_parity_manifest(path)
    if coordinate == (4, "checkpoint_analytics_model_parity_manifest_v4"):
        from checkpoint_model_parity_v4 import load_parity_manifest_v4
        return load_parity_manifest_v4(
            path, project_root=Path(__file__).resolve().parents[1]
        )
    raise BootstrapCalibrationV2Error(
        "accepted model-parity manifest schema/kind is unsupported"
    )


def _candidate_material(
    *,
    root: Path,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = _Registry(root)
    manifest_relative = _relative_input(
        root, candidate_manifest_path, "candidate capability manifest"
    )
    receipt_relative = _relative_input(
        root, candidate_receipt_path, "candidate qualification receipt"
    )
    manifest_record = registry.add(
        manifest_relative, "candidate capability manifest"
    )
    receipt_record = registry.add(
        receipt_relative, "candidate qualification receipt"
    )
    manifest = _read_json(
        root / manifest_relative, "candidate capability manifest"
    )
    receipt = _read_json(
        root / receipt_relative, "candidate qualification receipt"
    )
    _require(
        (root / manifest_relative).read_bytes()
        == _canonical_bytes(manifest) + b"\n",
        "candidate capability manifest bytes are not canonical",
    )
    _require(
        (root / receipt_relative).read_bytes()
        == _canonical_bytes(receipt) + b"\n",
        "candidate qualification receipt bytes are not canonical",
    )
    expected_receipt_fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "accepted",
        "publication_ready",
        "scope",
        "policy_contract_sha256",
        "qualification_index",
        "candidate_manifest",
        "blockers",
        "sha256",
    }
    _require(
        set(receipt) == expected_receipt_fields,
        "candidate receipt fields drifted",
    )
    _require(
        receipt.get("schema_version") == 1
        and receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_candidate_receipt"
        and receipt.get("status") == "qualification_candidate_not_accepted"
        and receipt.get("accepted") is False
        and receipt.get("publication_ready") is False
        and receipt.get("scope") == SCOPE,
        "candidate receipt is not an explicit nonaccepted candidate",
    )
    _require(
        _valid_sha(receipt.get("sha256"))
        and receipt["sha256"]
        == _canonical_sha(
            {key: value for key, value in receipt.items() if key != "sha256"}
        ),
        "candidate receipt self-hash drifted",
    )
    _require(
        _descriptor_fields(
            receipt.get("candidate_manifest"), "candidate manifest"
        )
        == manifest_record,
        "candidate manifest descriptor drifted",
    )
    index_expected = _descriptor_fields(
        receipt.get("qualification_index"), "candidate qualification index"
    )
    index_record = registry.add(
        str(index_expected["path"]), "candidate qualification index"
    )
    _require(
        index_record == index_expected,
        "candidate qualification index drifted",
    )
    _require(
        type(receipt.get("blockers")) is list
        and "candidate_is_not_a_full_publication_authority"
        in receipt["blockers"],
        "candidate receipt lost its nonauthority blocker",
    )
    assessment = policy.assess_capability_manifest(manifest)
    _require(
        assessment.get("passed") is True
        and assessment.get("status") == "ready"
        and assessment.get("blockers") == [],
        "candidate capability manifest violates the frozen policy contract",
    )
    contract_sha = policy.policy_contract_identity()["sha256"]
    _require(
        manifest.get("policy_contract_sha256")
        == receipt.get("policy_contract_sha256")
        == contract_sha,
        "candidate policy contract identity drifted",
    )
    material = {
        "candidate_manifest": manifest_record,
        "candidate_receipt": receipt_record,
        "candidate_receipt_identity_sha256": receipt["sha256"],
        "qualification_index": index_record,
    }
    return manifest, material


def _validate_acceptance_binding(
    *,
    root: Path,
    binding: Mapping[str, Any],
    manifest_relative: str,
    assessment_relative: str,
    receipt_relative: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    _require(
        type(binding) is dict,
        "production model-parity validator returned no binding",
    )
    coordinate = (
        binding.get("schema_version"), binding.get("artifact_kind")
    )
    if coordinate == (2, "vast_verified_model_parity_acceptance_binding"):
        expected_file_count = 36
    elif coordinate == (4, "vast_verified_model_parity_acceptance_binding_v4"):
        expected_file_count = 50
        try:
            from checkpoint_model_parity_acceptance_v4 import (
                validate_refresh_authority_v4,
            )
            refresh = validate_refresh_authority_v4(
                binding.get("refresh_authority")
            )
        except Exception as exc:
            raise BootstrapCalibrationV2Error(
                f"production model-parity v4 refresh authority failed: {exc}"
            ) from exc
        _require(
            refresh == binding.get("refresh_authority"),
            "production model-parity v4 refresh authority drifted",
        )
    else:
        raise BootstrapCalibrationV2Error(
            "production model-parity schema-v2 acceptance binding identity drifted"
        )
    _require(
        binding.get("evidence_count") == 32,
        "production model-parity acceptance evidence coverage drifted",
    )
    transaction_binding = binding.get("transaction_index")
    _require(
        type(transaction_binding) is dict
        and set(transaction_binding)
        == {
            "path",
            "size_bytes",
            "sha256",
            "transaction_sha256",
            "files_sha256",
            "output_segments_sha256",
            "execution_bundle_count",
            "execution_bundles_sha256",
        }
        and _valid_sha(transaction_binding.get("transaction_sha256"))
        and _valid_sha(transaction_binding.get("files_sha256"))
        and _valid_sha(transaction_binding.get("output_segments_sha256"))
        and transaction_binding.get("execution_bundle_count") == 480
        and _valid_sha(transaction_binding.get("execution_bundles_sha256")),
        "production acceptance binding lacks exact schema-v2 transaction authority",
    )
    _descriptor_fields(
        {
            key: transaction_binding[key]
            for key in ("path", "size_bytes", "sha256")
        },
        "accepted transaction index",
    )
    declared = binding.get("binding_sha256")
    _require(
        _valid_sha(declared)
        and declared
        == _canonical_sha(
            {
                key: value
                for key, value in binding.items()
                if key != "binding_sha256"
            }
        ),
        "production model-parity acceptance binding self-hash drifted",
    )
    registry = _Registry(root)
    actual = {
        "receipt": registry.add(
            receipt_relative, "accepted model-parity receipt"
        ),
        "accepted_manifest": registry.add(
            manifest_relative, "accepted model-parity manifest"
        ),
        "accepted_assessment": registry.add(
            assessment_relative, "accepted model-parity assessment"
        ),
    }
    for role, record in actual.items():
        _require(
            _descriptor_fields(
                binding.get(role), f"model-parity binding {role}"
            )
            == record,
            f"accepted model-parity {role} descriptor drifted",
        )
    raw_files = binding.get("files")
    _require(
        type(raw_files) is list
        and (
            bool(raw_files)
            if expected_file_count == 36
            else len(raw_files) == expected_file_count
        ),
        "model-parity binding file set is missing",
    )
    binding_files: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(raw_files):
        record = _descriptor_fields(
            raw, f"model-parity binding file[{position}]"
        )
        path = str(record["path"])
        _require(
            path not in binding_files,
            "model-parity binding contains duplicate file paths",
        )
        binding_files[path] = record
    _require(
        binding.get("files_sha256") == _canonical_sha(raw_files),
        "model-parity acceptance binding files hash drifted",
    )
    for record in actual.values():
        _require(
            binding_files.get(str(record["path"])) == record,
            "accepted model-parity primary input is absent from binding files",
        )
    transaction_descriptor = {
        key: transaction_binding[key]
        for key in ("path", "size_bytes", "sha256")
    }
    _require(
        binding_files.get(str(transaction_descriptor["path"]))
        == transaction_descriptor,
        "accepted transaction index is absent from binding files",
    )
    return dict(binding), binding_files


def _accepted_calibration_material(
    *,
    root: Path,
    accepted_manifest_path: Path | str,
    accepted_assessment_path: Path | str,
    accepted_receipt_path: Path | str,
) -> dict[str, Any]:
    manifest_relative = _relative_input(
        root, accepted_manifest_path, "accepted model-parity manifest"
    )
    assessment_relative = _relative_input(
        root, accepted_assessment_path, "accepted model-parity assessment"
    )
    receipt_relative = _relative_input(
        root, accepted_receipt_path, "accepted model-parity receipt"
    )
    try:
        import yaml
        manifest_header = yaml.safe_load(
            (root / manifest_relative).read_text(encoding="utf-8")
        )
        manifest_header_coordinate = (
            manifest_header.get("schema_version")
            if type(manifest_header) is dict else None,
            manifest_header.get("artifact_kind")
            if type(manifest_header) is dict else None,
        )
        if manifest_header_coordinate == (
            3, "checkpoint_analytics_model_parity_manifest"
        ):
            acceptance_loader = (
                model_parity_acceptance.load_verified_model_parity_acceptance
            )
        elif manifest_header_coordinate == (
            4, "checkpoint_analytics_model_parity_manifest_v4"
        ):
            from checkpoint_model_parity_acceptance_v4 import (
                load_verified_model_parity_acceptance_v4,
            )
            acceptance_loader = load_verified_model_parity_acceptance_v4
        else:
            raise BootstrapCalibrationV2Error(
                "accepted model-parity manifest schema/kind is unsupported"
            )
        raw_binding = acceptance_loader(
            project_root=root,
            receipt_path=root / receipt_relative,
        )
    except Exception as exc:
        raise BootstrapCalibrationV2Error(
            f"production model-parity acceptance validation failed: {exc}"
        ) from exc
    binding, binding_files = _validate_acceptance_binding(
        root=root,
        binding=raw_binding,
        manifest_relative=manifest_relative,
        assessment_relative=assessment_relative,
        receipt_relative=receipt_relative,
    )
    try:
        manifest = _load_model_parity_manifest(root / manifest_relative)
    except Exception as exc:
        raise BootstrapCalibrationV2Error(
            f"accepted model-parity manifest loader rejected input: {exc}"
        ) from exc
    _require(
        type(manifest) is dict,
        "accepted model-parity manifest is not an object",
    )
    manifest_coordinate = (
        manifest.get("schema_version"), manifest.get("artifact_kind")
    )
    _require(
        manifest_coordinate
        in {
            (3, "checkpoint_analytics_model_parity_manifest"),
            (4, "checkpoint_analytics_model_parity_manifest_v4"),
        },
        "accepted model-parity manifest schema/kind drifted",
    )
    slots = manifest.get("workload_slots")
    _require(
        type(slots) is dict
        and set(slots) == set(policy.ANALYTICS_BRANCHES),
        "accepted model-parity workload slot set drifted",
    )
    registry = _Registry(root)
    calibration_records: list[dict[str, Any]] = []
    services: dict[tuple[str, str], list[tuple[str, float]]] = {}
    evidence_roots: set[str] = set()
    for branch in policy.ANALYTICS_BRANCHES:
        slot = slots[branch]
        _require(
            type(slot) is dict,
            f"accepted model-parity slot {branch} is invalid",
        )
        evidence = slot.get("evidence")
        _require(
            type(evidence) is dict,
            f"accepted model-parity evidence {branch} is invalid",
        )
        for resource in policy.RESOURCES:
            evidence_name = CALIBRATION_EVIDENCE_NAMES[resource]
            reference = evidence.get(evidence_name)
            _require(
                type(reference) is dict
                and set(reference) == {"path", "sha256"},
                f"accepted calibration reference {branch}/{resource} drifted",
            )
            relative = _normalized_relative(
                reference.get("path"),
                f"accepted calibration {branch}/{resource}",
            )
            _require(
                _valid_sha(reference.get("sha256")),
                "accepted calibration SHA is invalid",
            )
            parts = relative.parts
            _require(
                len(parts) >= 4
                and parts[-3] == "documents"
                and parts[-2] == branch
                and parts[-1] == f"{evidence_name}.json",
                f"accepted calibration {branch}/{resource} is outside "
                "the transaction layout",
            )
            evidence_roots.add(Path(*parts[:-3]).as_posix())
            record = registry.add(
                relative.as_posix(),
                f"accepted calibration {branch}/{resource}",
            )
            _require(
                record["sha256"] == reference["sha256"],
                f"accepted calibration {branch}/{resource} manifest SHA drifted",
            )
            _require(
                binding_files.get(relative.as_posix()) == record,
                f"accepted calibration {branch}/{resource} is not "
                "acceptance-bound",
            )
            document = _read_json(
                root / relative,
                f"accepted calibration {branch}/{resource}",
            )
            _require(
                document.get("schema_version") == 2
                and document.get("artifact_kind")
                == "checkpoint_model_policy_calibration"
                and document.get("branch") == branch
                and document.get("resource") == NATIVE_RESOURCES[resource],
                f"accepted calibration {branch}/{resource} identity drifted",
            )
            samples = document.get("samples")
            sample_count = document.get("sample_count")
            minimum = int(policy.MIN_CALIBRATION_SAMPLES)
            _require(
                type(sample_count) is int
                and sample_count >= minimum
                and type(samples) is list
                and len(samples) == sample_count,
                f"accepted calibration {branch}/{resource} requires at "
                f"least {minimum} physical samples",
            )
            seen: set[str] = set()
            service_rows: list[tuple[str, float]] = []
            for position, raw in enumerate(samples):
                _require(
                    type(raw) is dict
                    and set(raw) == {"sample_id", "service_time_ms"},
                    f"accepted calibration {branch}/{resource} "
                    f"sample[{position}] drifted",
                )
                sample_id = raw.get("sample_id")
                service = raw.get("service_time_ms")
                _require(
                    type(sample_id) is str
                    and sample_id
                    and sample_id not in seen,
                    f"accepted calibration {branch}/{resource} "
                    "sample_id is invalid",
                )
                _require(
                    not isinstance(service, bool)
                    and isinstance(service, (int, float))
                    and math.isfinite(float(service))
                    and float(service) > 0.0,
                    f"accepted calibration {branch}/{resource} "
                    "service time is invalid",
                )
                seen.add(sample_id)
                service_rows.append((sample_id, float(service)))
            services[(branch, resource)] = service_rows
            calibration_records.append(
                {"branch": branch, "resource": resource, **record}
            )
    _require(
        len(evidence_roots) == 1,
        "accepted calibration documents do not share one transaction root",
    )
    evidence_root = next(iter(evidence_roots))
    transaction_relative = (
        f"{evidence_root}/transaction_index.json"
        if evidence_root
        else "transaction_index.json"
    )
    transaction_record, physical_responses, transfers = _transaction_material(
        root=root,
        transaction_relative=transaction_relative,
        services=services,
    )
    _require(
        binding.get("transaction_index") == transaction_record,
        "accepted transaction index drifted from production acceptance binding",
    )
    calibration_records.sort(
        key=lambda row: (row["branch"], row["resource"])
    )
    result = {
        "acceptance_binding": binding,
        "acceptance_binding_sha256": binding["binding_sha256"],
        "accepted_manifest": _descriptor_fields(
            binding["accepted_manifest"], "accepted model-parity manifest"
        ),
        "accepted_assessment": _descriptor_fields(
            binding["accepted_assessment"], "accepted model-parity assessment"
        ),
        "accepted_receipt": _descriptor_fields(
            binding["receipt"], "accepted model-parity receipt"
        ),
        "accepted_evidence_sha256": binding["evidence_sha256"],
        "calibration_evidence": calibration_records,
        "calibration_evidence_sha256": _canonical_sha(calibration_records),
        "transaction_index": transaction_record,
        "physical_response_evidence": physical_responses,
        "physical_response_evidence_sha256": _canonical_sha(
            physical_responses
        ),
        "services": services,
        "transfers": transfers,
    }
    if manifest_coordinate[0] == 4:
        result["model_parity_refresh_authority"] = json.loads(
            _canonical_bytes(binding["refresh_authority"]).decode("ascii")
        )
    return result


def _execution_bundle_material(
    *,
    root: Path,
    index: Mapping[str, Any],
    files: list[Any],
    services: Mapping[tuple[str, str], list[tuple[str, float]]],
    evidence_root: str,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = index.get("execution_bundles")
    count = index.get("execution_bundle_count")
    _require(
        type(rows) is list
        and type(count) is int
        and count == len(rows) == 480,
        "schema-v2 transaction requires exact 480 execution bundles",
    )
    _require(
        index.get("execution_bundles_sha256") == _canonical_sha(rows),
        "transaction execution bundle hash drifted",
    )
    file_map: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(files):
        record = _descriptor_fields(raw, f"transaction file[{position}]")
        relative = str(record["path"])
        _require(
            relative not in file_map,
            "transaction file index contains duplicate paths",
        )
        _require(
            relative.startswith(f"{evidence_root}/"),
            "transaction file escaped its materialization root",
        )
        file_map[relative] = record

    required_ids = {
        (branch, resource): {sample_id for sample_id, _ in values}
        for (branch, resource), values in services.items()
    }
    expected_row_fields = {
        "branch",
        "role",
        "codec",
        "sample_id",
        "resource",
        "request_id",
        "manifest",
        "manifest_identity_sha256",
        "request_sha256",
        "response_sha256",
        "input_tensor_sha256",
        "output_tensor_sha256",
    }
    manifest_fields = {
        "schema_version",
        "artifact_kind",
        "protocol_identity_sha256",
        "request_id",
        "run_id",
        "arm_id",
        "worker_id",
        "frame",
        "capability_sha256",
        "files",
        "identity",
    }
    file_roles = {
        "request": "request_sha256",
        "response": "response_sha256",
        "input_tensor": "input_tensor_sha256",
        "output_tensor": "output_tensor_sha256",
    }
    expected_names = {
        "request": "request.json",
        "response": "response.json",
        "input_tensor": "input.tensor.bin",
        "output_tensor": "output.tensor.bin",
    }
    registry = _Registry(root)
    coordinates: set[tuple[str, str, str, str, str]] = set()
    execution_coordinates: set[tuple[str, str, str]] = set()
    coverage: dict[tuple[str, str, str, str], int] = {}
    request_ids: set[str] = set()
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for position, raw in enumerate(rows):
        _require(
            type(raw) is dict and set(raw) == expected_row_fields,
            f"execution bundle row[{position}] fields drifted",
        )
        branch = raw.get("branch")
        role = raw.get("role")
        codec = raw.get("codec")
        sample_id = raw.get("sample_id")
        native_resource = raw.get("resource")
        request_id = raw.get("request_id")
        _require(
            branch in policy.ANALYTICS_BRANCHES
            and role in {"calibration", "evaluation"}
            and codec in {"h264", "h265"}
            and type(sample_id) is str
            and sample_id
            and native_resource in set(NATIVE_RESOURCES.values())
            and type(request_id) is str
            and request_id,
            f"execution bundle row[{position}] coordinate drifted",
        )
        coordinate = (
            str(branch),
            str(role),
            str(codec),
            str(sample_id),
            str(native_resource),
        )
        _require(
            coordinate not in coordinates and request_id not in request_ids,
            "execution bundle coordinate/request_id is duplicated",
        )
        coordinates.add(coordinate)
        request_ids.add(str(request_id))
        execution_coordinate = (
            str(branch), str(native_resource), str(sample_id)
        )
        _require(
            execution_coordinate not in execution_coordinates,
            "execution bundle output coordinate is duplicated",
        )
        execution_coordinates.add(execution_coordinate)
        coverage_key = (
            str(branch), str(native_resource), str(role), str(codec)
        )
        coverage[coverage_key] = coverage.get(coverage_key, 0) + 1
        expected_manifest = _descriptor_fields(
            raw.get("manifest"), f"execution bundle manifest[{position}]"
        )
        manifest_record = registry.add(
            str(expected_manifest["path"]),
            f"execution bundle manifest[{position}]",
        )
        _require(
            manifest_record == expected_manifest
            and manifest_record["path"]
            == f"{evidence_root}/execution_bundles/{request_id}/manifest.json"
            and file_map.get(str(manifest_record["path"])) == manifest_record,
            f"execution bundle manifest[{position}] is not transaction-bound",
        )
        manifest_path = root / str(manifest_record["path"])
        manifest = _read_json(
            manifest_path, f"execution bundle manifest[{position}]"
        )
        _require(
            manifest_path.read_bytes() == _canonical_bytes(manifest) + b"\n"
            and set(manifest) == manifest_fields
            and manifest.get("schema_version") == 1
            and manifest.get("artifact_kind")
            == "vast_analytics_execution_evidence_bundle"
            and manifest.get("request_id") == request_id,
            f"execution bundle manifest[{position}] schema/bytes drifted",
        )
        identity = manifest.get("identity")
        _require(
            type(identity) is dict
            and set(identity) == {"algorithm", "sha256"}
            and identity.get("algorithm") == "sha256"
            and identity.get("sha256")
            == _canonical_sha(
                {key: value for key, value in manifest.items() if key != "identity"}
            )
            == raw.get("manifest_identity_sha256"),
            f"execution bundle manifest[{position}] identity drifted",
        )
        inventory = manifest.get("files")
        _require(
            type(inventory) is dict and set(inventory) == set(file_roles),
            f"execution bundle manifest[{position}] inventory drifted",
        )
        physical: dict[str, dict[str, Any]] = {}
        for file_role, row_hash_field in file_roles.items():
            item = inventory[file_role]
            _require(
                type(item) is dict
                and set(item) == {"path", "bytes", "sha256"}
                and item.get("path") == expected_names[file_role]
                and type(item.get("bytes")) is int
                and item["bytes"] > 0
                and _valid_sha(item.get("sha256"))
                and item["sha256"] == raw.get(row_hash_field),
                f"execution bundle {file_role}[{position}] binding drifted",
            )
            physical_path = manifest_path.parent / str(item["path"])
            try:
                relative = physical_path.relative_to(root).as_posix()
            except ValueError as exc:
                raise BootstrapCalibrationV2Error(
                    "execution bundle file escaped project_root"
                ) from exc
            actual = registry.add(
                relative, f"execution bundle {file_role}[{position}]"
            )
            _require(
                actual
                == {
                    "path": relative,
                    "size_bytes": item["bytes"],
                    "sha256": item["sha256"],
                }
                and file_map.get(relative) == actual,
                f"execution bundle {file_role}[{position}] is not transaction-bound",
            )
            physical[file_role] = actual
        resource = next(
            key
            for key, value in NATIVE_RESOURCES.items()
            if value == native_resource
        )
        selected_key = (str(branch), resource, str(sample_id))
        if (
            role == "calibration"
            and sample_id in required_ids[(str(branch), resource)]
        ):
            _require(
                selected_key not in selected,
                "accepted calibration sample has multiple execution bundles",
            )
            selected[selected_key] = {
                "request_id": str(request_id),
                "input_tensor_sha256": raw["input_tensor_sha256"],
                "response": physical["response"],
            }
    expected_selected = {
        (branch, resource, sample_id)
        for (branch, resource), sample_ids in required_ids.items()
        for sample_id in sample_ids
    }
    _require(
        set(selected) == expected_selected,
        "execution bundles do not exactly cover accepted calibration samples",
    )
    output_coordinates: set[tuple[str, str, str]] = set()
    for raw in index["output_segments"]:
        _require(type(raw) is dict, "transaction output segment is invalid")
        coordinate = (
            str(raw.get("branch")),
            str(raw.get("resource")),
            str(raw.get("sample_id")),
        )
        _require(
            coordinate[0] in policy.ANALYTICS_BRANCHES
            and coordinate[1] in set(NATIVE_RESOURCES.values())
            and coordinate[2]
            and _valid_sha(raw.get("preprocessed_tensor_sha256"))
            and coordinate not in output_coordinates,
            "transaction output coordinate is invalid or duplicated",
        )
        output_coordinates.add(coordinate)
    _require(
        output_coordinates == execution_coordinates,
        "transaction execution/output coordinate coverage drifted",
    )
    expected_coverage = {
        (branch, native_resource, role, codec): 15
        for branch in policy.ANALYTICS_BRANCHES
        for native_resource in NATIVE_RESOURCES.values()
        for role in ("calibration", "evaluation")
        for codec in ("h264", "h265")
    }
    _require(
        coverage == expected_coverage,
        "transaction balanced execution coverage drifted",
    )
    return selected


def _transaction_material(
    *,
    root: Path,
    transaction_relative: str,
    services: Mapping[tuple[str, str], list[tuple[str, float]]],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[tuple[str, str], list[tuple[str, float]]],
]:
    transaction_record, _ = _stable_descriptor(
        root, transaction_relative, "model-parity transaction index"
    )
    index = _read_json(
        root / transaction_relative, "model-parity transaction index"
    )
    _require(
        (root / transaction_relative).read_bytes()
        == _canonical_bytes(index) + b"\n",
        "model-parity transaction index bytes are not canonical",
    )
    expected_index_fields = {
        "schema_version",
        "artifact_kind",
        "run_id",
        "final_materialization_path",
        "document_count",
        "files",
        "files_sha256",
        "source_inventory",
        "source_inventory_sha256",
        "output_segments",
        "output_segments_sha256",
        "execution_bundle_count",
        "execution_bundles",
        "execution_bundles_sha256",
        "claimed_aggregates_accepted",
        "synthetic_or_mock_evidence_accepted",
        "transaction_sha256",
    }
    _require(
        set(index) == expected_index_fields
        and index.get("schema_version") == 2
        and index.get("artifact_kind")
        == "checkpoint_model_parity_materialization_transaction"
        and index.get("claimed_aggregates_accepted") is False
        and index.get("synthetic_or_mock_evidence_accepted") is False,
        "model-parity schema-v2 transaction boundary drifted",
    )
    evidence_root = Path(transaction_relative).parent.as_posix()
    source_inventory = index.get("source_inventory")
    _require(
        index.get("run_id") == Path(evidence_root).name
        and index.get("final_materialization_path") == evidence_root
        and index.get("document_count") == 32
        and type(source_inventory) is list
        and index.get("source_inventory_sha256")
        == _canonical_sha(source_inventory),
        "model-parity transaction root/source provenance drifted",
    )
    _require(
        _valid_sha(index.get("transaction_sha256"))
        and index["transaction_sha256"]
        == _canonical_sha(
            {
                key: value
                for key, value in index.items()
                if key != "transaction_sha256"
            }
        ),
        "model-parity transaction self-hash drifted",
    )
    files = index.get("files")
    segments = index.get("output_segments")
    _require(
        type(files) is list and files,
        "transaction file index is missing",
    )
    _require(
        type(segments) is list and segments,
        "transaction output segments are missing",
    )
    _require(
        index.get("files_sha256") == _canonical_sha(files),
        "transaction files hash drifted",
    )
    _require(
        index.get("output_segments_sha256") == _canonical_sha(segments),
        "transaction output segments hash drifted",
    )
    _require(
        index.get("execution_bundle_count") == len(segments),
        "transaction execution/output cardinality drifted",
    )
    selected_bundles = _execution_bundle_material(
        root=root,
        index=index,
        files=files,
        services=services,
        evidence_root=evidence_root,
    )

    required_ids = {
        (branch, resource): {sample_id for sample_id, _ in rows}
        for (branch, resource), rows in services.items()
    }
    segment_by_input: dict[tuple[str, str, str], str] = {}
    segment_coordinates: set[tuple[str, str, str]] = set()
    native_to_resource = {
        value: key for key, value in NATIVE_RESOURCES.items()
    }
    for position, raw in enumerate(segments):
        _require(
            type(raw) is dict,
            f"transaction segment[{position}] is invalid",
        )
        branch = raw.get("branch")
        resource = native_to_resource.get(raw.get("resource"))
        sample_id = raw.get("sample_id")
        tensor_sha = raw.get("preprocessed_tensor_sha256")
        if branch not in policy.ANALYTICS_BRANCHES or resource is None:
            continue
        if (
            type(sample_id) is not str
            or sample_id not in required_ids[(branch, resource)]
        ):
            continue
        _require(
            _valid_sha(tensor_sha),
            "transaction calibration tensor SHA is invalid",
        )
        coordinate = (branch, resource, sample_id)
        _require(
            coordinate not in segment_coordinates,
            f"transaction segment duplicates {branch}/{resource}/{sample_id}",
        )
        input_key = (branch, resource, str(tensor_sha))
        _require(
            input_key not in segment_by_input,
            "transaction tensor aliases multiple calibration samples: "
            f"{branch}/{resource}",
        )
        segment_coordinates.add(coordinate)
        segment_by_input[input_key] = sample_id
        _require(
            selected_bundles[coordinate]["input_tensor_sha256"]
            == tensor_sha,
            "transaction output segment/execution input binding drifted",
        )
    expected_coordinates = {
        (branch, resource, sample_id)
        for (branch, resource), sample_ids in required_ids.items()
        for sample_id in sample_ids
    }
    _require(
        segment_coordinates == expected_coordinates,
        "transaction index does not bind every accepted calibration sample_id",
    )

    response_records: list[dict[str, Any]] = []
    transfers: dict[tuple[str, str], list[tuple[str, float]]] = {
        key: [] for key in services
    }
    response_coordinates: set[tuple[str, str, str]] = set()
    request_ids: set[str] = set()
    gpu_device_ids: set[str] = set()
    for coordinate in sorted(expected_coordinates):
        branch, resource, sample_id = coordinate
        bundle = selected_bundles[coordinate]
        actual = bundle["response"]
        relative = str(actual["path"])
        response = _read_json(
            root / relative,
            f"transaction response {branch}/{resource}/{sample_id}",
        )
        frame = response.get("frame")
        provenance = response.get("provenance")
        _require(
            response.get("schema_version") == 1
            and response.get("message_type") == "infer_response"
            and response.get("engine") == NATIVE_RESOURCES[resource]
            and type(frame) is dict
            and type(provenance) is dict,
            "native transaction response schema drifted",
        )
        input_sha = provenance.get("input_sha256")
        _require(
            frame.get("branch") == branch
            and input_sha == bundle["input_tensor_sha256"],
            "native transaction response coordinate drifted",
        )
        request_id = response.get("request_id")
        _require(
            request_id == bundle["request_id"]
            and request_id not in request_ids,
            "native transaction request_id is missing or duplicated",
        )
        request_ids.add(request_id)
        transfer_ms = _physical_transfer_ms(response, resource=resource)
        if resource == "gpu":
            gpu_device_ids.add(str(provenance["device_id"]))
        response_coordinates.add(coordinate)
        transfers[(branch, resource)].append((sample_id, transfer_ms))
        response_records.append(
            {
                "branch": branch,
                "resource": resource,
                "sample_id": sample_id,
                "request_id": request_id,
                "transfer_ms": transfer_ms,
                **actual,
            }
        )
    _require(
        response_coordinates == expected_coordinates,
        "physical response coverage is below 30 samples per branch/resource",
    )
    _require(
        len(gpu_device_ids) == 1,
        "physical GPU calibration responses do not use one exact GPU",
    )
    for key in transfers:
        transfers[key].sort(key=lambda item: item[0])
        _require(
            len(transfers[key]) >= int(policy.MIN_CALIBRATION_SAMPLES),
            "physical response coverage is below minimum for "
            f"{key[0]}/{key[1]}",
        )
    response_records.sort(
        key=lambda row: (row["branch"], row["resource"], row["sample_id"])
    )
    accepted_transaction = {
        **transaction_record,
        "transaction_sha256": index["transaction_sha256"],
        "files_sha256": index["files_sha256"],
        "output_segments_sha256": index["output_segments_sha256"],
        "execution_bundle_count": index["execution_bundle_count"],
        "execution_bundles_sha256": index["execution_bundles_sha256"],
    }
    return accepted_transaction, response_records, transfers


def _physical_transfer_ms(
    response: Mapping[str, Any], *, resource: str
) -> float:
    provenance = response.get("provenance")
    facts = response.get("resource")
    _require(
        type(provenance) is dict and type(facts) is dict,
        "native response resource facts are missing",
    )
    intervals = facts.get("cuda_transfer_intervals")
    if resource == "cpu":
        _require(
            provenance.get("device_api") == "CPU"
            and facts.get("accelerator_memory_bytes") == 0
            and facts.get("cuda_h2d_bytes") == 0
            and facts.get("cuda_d2h_bytes") == 0
            and intervals == [],
            "CPU response contains nonzero or CUDA transfer evidence",
        )
        return 0.0
    _require(
        provenance.get("device_api") == "NVIDIA_CUDA"
        and type(provenance.get("device_id")) is str
        and provenance["device_id"].startswith("GPU-")
        and type(facts.get("accelerator_memory_bytes")) is int
        and facts["accelerator_memory_bytes"] > 0
        and type(intervals) is list
        and len(intervals) == 2,
        "GPU response lacks exact physical CUDA transfer evidence",
    )
    expected_fields = {
        "bytes",
        "device_elapsed_ns",
        "device_id",
        "direction",
        "host_end_monotonic_ns",
        "host_start_monotonic_ns",
        "timing_source",
    }
    by_direction: dict[str, Mapping[str, Any]] = {}
    device_ids: set[str] = set()
    elapsed_ns = 0
    for interval in intervals:
        _require(
            type(interval) is dict and set(interval) == expected_fields,
            "CUDA transfer interval fields drifted",
        )
        direction = interval.get("direction")
        _require(
            direction in {"h2d", "d2h"} and direction not in by_direction,
            "CUDA transfer interval directions are not exact",
        )
        _require(
            type(interval.get("bytes")) is int
            and interval["bytes"] > 0
            and type(interval.get("device_elapsed_ns")) is int
            and interval["device_elapsed_ns"] > 0
            and type(interval.get("host_start_monotonic_ns")) is int
            and type(interval.get("host_end_monotonic_ns")) is int
            and interval["host_end_monotonic_ns"]
            >= interval["host_start_monotonic_ns"]
            and interval.get("timing_source") == "cudaEventElapsedTime"
            and type(interval.get("device_id")) is str
            and interval["device_id"].startswith("GPU-"),
            "CUDA transfer interval is not a physical cudaEvent observation",
        )
        by_direction[str(direction)] = interval
        device_ids.add(str(interval["device_id"]))
        elapsed_ns += int(interval["device_elapsed_ns"])
    _require(
        set(by_direction) == {"h2d", "d2h"},
        "CUDA transfer directions drifted",
    )
    _require(
        device_ids == {str(provenance["device_id"])},
        "CUDA transfer intervals drifted from the response GPU identity",
    )
    _require(
        facts.get("cuda_h2d_bytes") == by_direction["h2d"]["bytes"]
        and facts.get("cuda_d2h_bytes") == by_direction["d2h"]["bytes"],
        "CUDA transfer byte totals drifted",
    )
    return float(elapsed_ns) / 1_000_000.0


def _derive_snapshot(
    *,
    root: Path,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    candidate, candidate_material = _candidate_material(
        root=root,
        candidate_manifest_path=candidate_manifest_path,
        candidate_receipt_path=candidate_receipt_path,
    )
    parity = _accepted_calibration_material(
        root=root,
        accepted_manifest_path=accepted_model_parity_manifest_path,
        accepted_assessment_path=accepted_model_parity_assessment_path,
        accepted_receipt_path=accepted_model_parity_receipt_path,
    )
    costs_by_branch: dict[str, dict[str, dict[str, Any]]] = {}
    for branch in policy.ANALYTICS_BRANCHES:
        costs_by_branch[branch] = {}
        for resource in policy.RESOURCES:
            service_rows = parity["services"][(branch, resource)]
            transfer_rows = parity["transfers"][(branch, resource)]
            service_by_id = dict(service_rows)
            transfer_by_id = dict(transfer_rows)
            _require(
                set(service_by_id) == set(transfer_by_id),
                "service/transfer physical sample set drifted for "
                f"{branch}/{resource}",
            )
            costs_by_branch[branch][resource] = {
                "service_ms": float(median(service_by_id.values())),
                "transfer_ms": float(median(transfer_by_id.values())),
                "samples": len(service_by_id),
            }
    calibrations: dict[str, dict[str, Any]] = {}
    contract_sha = policy.policy_contract_identity()["sha256"]
    for system in policy.PUBLISHABLE_SYSTEMS:
        costs: dict[str, dict[str, dict[str, Any]]] = {}
        for branch in policy.ANALYTICS_BRANCHES:
            costs[branch] = {}
            for resource in policy.RESOURCES:
                row = costs_by_branch[branch][resource]
                costs[branch][resource] = {
                    "implementation_id": candidate["systems"][system]
                    ["branches"][branch][resource]["implementation_id"],
                    **row,
                }
        calibration = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration",
            "system": system,
            "policy_contract_sha256": contract_sha,
            "costs": costs,
            "status": STATUS,
            "accepted": False,
            "publication_ready": False,
            "scope": SCOPE,
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "source_candidate_manifest_sha256": candidate_material[
                "candidate_manifest"
            ]["sha256"],
            "source_model_parity_acceptance_binding_sha256": parity[
                "acceptance_binding_sha256"
            ],
            "source_physical_response_evidence_sha256": parity[
                "physical_response_evidence_sha256"
            ],
        }
        try:
            policy.select_static_hybrid_map(system, calibration, candidate)
        except Exception as exc:
            raise BootstrapCalibrationV2Error(
                "derived calibration violates frozen policy contract "
                f"for {system}: {exc}"
            ) from exc
        calibrations[system] = calibration
    snapshot = {
        **candidate_material,
        "policy_contract_sha256": contract_sha,
        "accepted_model_parity_manifest": parity["accepted_manifest"],
        "accepted_model_parity_assessment": parity["accepted_assessment"],
        "accepted_model_parity_receipt": parity["accepted_receipt"],
        "model_parity_acceptance_binding_sha256": parity[
            "acceptance_binding_sha256"
        ],
        "accepted_model_parity_evidence_sha256": parity[
            "accepted_evidence_sha256"
        ],
        "calibration_evidence": parity["calibration_evidence"],
        "calibration_evidence_sha256": parity[
            "calibration_evidence_sha256"
        ],
        "transaction_index": parity["transaction_index"],
        "physical_response_evidence": parity["physical_response_evidence"],
        "physical_response_evidence_sha256": parity[
            "physical_response_evidence_sha256"
        ],
    }
    if "model_parity_refresh_authority" in parity:
        snapshot["model_parity_refresh_authority"] = parity[
            "model_parity_refresh_authority"
        ]
    return candidate, snapshot, calibrations


def _output_destination(root: Path, output_dir: Path | str) -> Path:
    raw = Path(output_dir)
    candidate = Path(
        os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw))
    )
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise BootstrapCalibrationV2Error(
            "output_dir escaped project_root"
        ) from exc
    _require(candidate != root, "output_dir cannot be project_root")
    parent = candidate.parent
    _require(parent.is_dir(), "output_dir parent must already exist")
    relative_parent = parent.relative_to(root)
    cursor = root
    for part in relative_parent.parts:
        cursor = cursor / part
        _require(
            not _is_link(cursor),
            "output_dir parent contains a symlink/reparse point",
        )
    _require(
        parent.resolve(strict=True) == parent,
        "output_dir parent is an alias",
    )
    if os.path.lexists(candidate):
        _require(
            candidate.is_dir()
            and not _is_link(candidate)
            and candidate.resolve(strict=True) == candidate,
            "immutable bootstrap output is not one physical directory",
        )
    return candidate


def _payload_descriptor(
    root: Path, path: Path, payload: bytes
) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | int(getattr(os, "O_CLOEXEC", 0)),
        0o444,
    )
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(path),
        "bootstrap directory identity is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _bootstrap_result(destination: Path) -> dict[str, Any]:
    return {
        "mapping_path": destination / MAPPING_FILENAME,
        "calibration_paths": {
            system: destination / CALIBRATION_FILENAME.format(system=system)
            for system in policy.PUBLISHABLE_SYSTEMS
        },
        "receipt_path": destination / RECEIPT_FILENAME,
    }


def _require_exact_bootstrap_tree(
    destination: Path,
    payloads: Mapping[str, bytes],
) -> tuple[int, int]:
    identity = _directory_identity(destination)
    try:
        names = {entry.name for entry in destination.iterdir()}
    except OSError as error:
        raise BootstrapCalibrationV2Error(
            "bootstrap output cannot be enumerated for exact adoption"
        ) from error
    _require(names == set(payloads), "immutable bootstrap output namespace drifted")
    for name, payload in payloads.items():
        path = destination / name
        try:
            before = path.lstat()
            observed = path.read_bytes()
            after = path.lstat()
        except OSError as error:
            raise BootstrapCalibrationV2Error(
                f"bootstrap output {name} cannot be adopted"
            ) from error
        _require(
            stat.S_ISREG(before.st_mode)
            and not _is_link(path)
            and int(before.st_nlink) == 1
            and (int(before.st_dev), int(before.st_ino), int(before.st_size))
            == (int(after.st_dev), int(after.st_ino), int(after.st_size))
            and observed == payload,
            f"immutable bootstrap output collision: {name}",
        )
    _require(
        _directory_identity(destination) == identity,
        "bootstrap output directory changed during exact adoption",
    )
    return identity


def _durable_bootstrap_tree(
    destination: Path,
    *,
    parent: Path,
    expected_identity: tuple[int, int],
    expected_parent_identity: tuple[int, int],
) -> None:
    _require(
        destination.parent == parent
        and _directory_identity(destination) == expected_identity,
        "bootstrap output directory identity drifted before durability barrier",
    )
    _require(
        _directory_identity(parent) == expected_parent_identity,
        "bootstrap output parent identity drifted before durability barrier",
    )
    try:
        for path in sorted(destination.iterdir(), key=lambda item: item.name):
            before = path.lstat()
            _require(
                stat.S_ISREG(before.st_mode)
                and not _is_link(path)
                and int(before.st_nlink) == 1,
                f"bootstrap durability barrier found unsafe leaf: {path.name}",
            )
            descriptor = os.open(
                path,
                os.O_RDONLY
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            try:
                opened = os.fstat(descriptor)
                _require(
                    (int(opened.st_dev), int(opened.st_ino))
                    == (int(before.st_dev), int(before.st_ino)),
                    f"bootstrap durability leaf rebound: {path.name}",
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        for directory in (destination, parent):
            directory_identity = _directory_identity(directory)
            descriptor = os.open(
                directory,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            try:
                opened = os.fstat(descriptor)
                _require(
                    (int(opened.st_dev), int(opened.st_ino))
                    == directory_identity,
                    "bootstrap durability directory rebound",
                )
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError as error:
        raise BootstrapCalibrationV2Error(
            "bootstrap final tree durability barrier failed"
        ) from error
    _require(
        _directory_identity(destination) == expected_identity
        and _directory_identity(parent) == expected_parent_identity,
        "bootstrap output directory/parent changed across durability barrier",
    )


def _cleanup_staging(
    staging: Path,
    *,
    parent: Path,
    expected_staging_identity: tuple[int, int],
    expected_parent_identity: tuple[int, int],
) -> None:
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_staging = staging.resolve(strict=True)
    except OSError as exc:
        raise BootstrapCalibrationV2Error(
            "bootstrap staging cleanup target cannot be resolved"
        ) from exc
    _require(
        resolved_staging.parent == resolved_parent
        and resolved_staging.name.startswith(".policy-bootstrap-v2.")
        and resolved_staging != Path.cwd().resolve()
        and resolved_staging.is_dir()
        and not _is_link(resolved_staging),
        "refusing unsafe bootstrap staging cleanup target",
    )
    _require(
        _directory_identity(resolved_parent) == expected_parent_identity
        and _directory_identity(resolved_staging) == expected_staging_identity,
        "refusing bootstrap cleanup after parent/staging inode replacement",
    )
    for entry in resolved_staging.iterdir():
        info = entry.lstat()
        _require(
            stat.S_ISREG(info.st_mode)
            and not _is_link(entry)
            and int(info.st_nlink) == 1,
            "refusing bootstrap cleanup of an unowned staging inode",
        )
    shutil.rmtree(resolved_staging)


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Use the hardened shared directory publisher without an import cycle."""

    from publication_policy_qualification_pilot_executor_v2 import (
        _rename_directory_noreplace as publish,
    )

    publish(source, destination)


def _cold_validate_bootstrap_commit(
    *, root: Path, result: Mapping[str, Any], custody: PhysicalRootCustodyV1
) -> None:
    receipt_path = Path(result["receipt_path"])
    try:
        receipt_descriptor, receipt_payload = custody.read_descriptor(
            receipt_path,
            label="cold bootstrap receipt",
            maximum=64 * 1024 * 1024,
            capture=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise BootstrapCalibrationV2Error(
            f"cold bootstrap receipt custody failed: {error}"
        ) from error
    assert receipt_payload is not None
    try:
        receipt = json.loads(receipt_payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BootstrapCalibrationV2Error(
            "cold bootstrap receipt is not JSON"
        ) from error
    unsigned = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    _require(
        type(receipt) is dict
        and receipt_payload == _canonical_bytes(receipt) + b"\n"
        and receipt.get("receipt_sha256") == _canonical_sha(unsigned),
        "cold bootstrap receipt identity drifted",
    )
    expected: list[tuple[str, Path, Any]] = [
        ("mapping", Path(result["mapping_path"]), receipt.get("mapping")),
        *(
            (
                f"calibration {system}",
                Path(result["calibration_paths"][system]),
                receipt.get("calibrations", {}).get(system),
            )
            for system in policy.PUBLISHABLE_SYSTEMS
        ),
    ]
    for label, path, descriptor in expected:
        try:
            observed, _payload = custody.read_descriptor(
                path, label=f"cold bootstrap {label}", maximum=64 * 1024 * 1024
            )
        except PublicationPhysicalIoV1Error as error:
            raise BootstrapCalibrationV2Error(
                f"cold bootstrap {label} custody failed: {error}"
            ) from error
        _require(observed == descriptor, f"cold bootstrap {label} drifted")
    _require(
        receipt_descriptor["path"] == receipt_path.relative_to(root).as_posix(),
        "cold bootstrap receipt path drifted",
    )


def _commit(
    *,
    root: Path,
    destination: Path,
    mapping: dict[str, Any],
    calibrations: Mapping[str, dict[str, Any]],
    snapshot: dict[str, Any],
    revalidate: Callable[
        [], tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]
    ],
    after_directory_publish_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    parent = destination.parent
    parent_identity = _directory_identity(parent)
    staging: Path | None = None
    staging_identity: tuple[int, int] | None = None
    try:
        payloads: dict[str, bytes] = {}
        mapping_payload = _canonical_bytes(mapping) + b"\n"
        payloads[MAPPING_FILENAME] = mapping_payload
        calibration_descriptors: dict[str, dict[str, Any]] = {}
        for system in policy.PUBLISHABLE_SYSTEMS:
            filename = CALIBRATION_FILENAME.format(system=system)
            payload = _canonical_bytes(calibrations[system]) + b"\n"
            payloads[filename] = payload
            calibration_descriptors[system] = _payload_descriptor(
                root, destination / filename, payload
            )
        mapping_descriptor = _payload_descriptor(
            root, destination / MAPPING_FILENAME, mapping_payload
        )
        receipt = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_bootstrap_receipt"
            ),
            "status": STATUS,
            "accepted": False,
            "publication_ready": False,
            "scope": SCOPE,
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": snapshot["policy_contract_sha256"],
            "candidate_manifest": snapshot["candidate_manifest"],
            "candidate_receipt": snapshot["candidate_receipt"],
            "candidate_receipt_identity_sha256": snapshot[
                "candidate_receipt_identity_sha256"
            ],
            "qualification_index": snapshot["qualification_index"],
            "accepted_model_parity_manifest": snapshot[
                "accepted_model_parity_manifest"
            ],
            "accepted_model_parity_assessment": snapshot[
                "accepted_model_parity_assessment"
            ],
            "accepted_model_parity_receipt": snapshot[
                "accepted_model_parity_receipt"
            ],
            "model_parity_acceptance_binding_sha256": snapshot[
                "model_parity_acceptance_binding_sha256"
            ],
            "accepted_model_parity_evidence_sha256": snapshot[
                "accepted_model_parity_evidence_sha256"
            ],
            "calibration_evidence": snapshot["calibration_evidence"],
            "calibration_evidence_sha256": snapshot[
                "calibration_evidence_sha256"
            ],
            "transaction_index": snapshot["transaction_index"],
            "physical_response_evidence": snapshot[
                "physical_response_evidence"
            ],
            "physical_response_evidence_sha256": snapshot[
                "physical_response_evidence_sha256"
            ],
            "mapping": mapping_descriptor,
            "calibrations": calibration_descriptors,
            "blockers": [
                "bootstrap_is_not_policy_qualification_acceptance",
                "bootstrap_is_not_full_publication_authority",
                "bootstrap_is_valid_only_for_forced_cpu_only_gpu_only_pilots",
            ],
        }
        if "model_parity_refresh_authority" in snapshot:
            receipt["model_parity_refresh_authority"] = snapshot[
                "model_parity_refresh_authority"
            ]
        receipt["receipt_sha256"] = _canonical_sha(receipt)
        payloads[RECEIPT_FILENAME] = _canonical_bytes(receipt) + b"\n"
        _require(
            tuple(payloads)[-1] == RECEIPT_FILENAME,
            "bootstrap receipt is not the last staged payload",
        )
        if os.path.lexists(destination):
            existing_identity = _require_exact_bootstrap_tree(
                destination, payloads
            )
            _durable_bootstrap_tree(
                destination,
                parent=parent,
                expected_identity=existing_identity,
                expected_parent_identity=parent_identity,
            )
            return _bootstrap_result(destination)

        staging = Path(
            tempfile.mkdtemp(prefix=".policy-bootstrap-v2.", dir=parent)
        )
        staging_identity = _directory_identity(staging)
        for filename, payload in payloads.items():
            _write_new(staging / filename, payload)
            _require(
                (staging / filename).read_bytes() == payload,
                f"staged bootstrap output {filename} drifted",
            )
        _, second_snapshot, second_calibrations = revalidate()
        _require(
            second_snapshot == snapshot
            and second_calibrations == calibrations,
            "bootstrap inputs changed before atomic commit",
        )
        _require(
            _directory_identity(parent) == parent_identity,
            "bootstrap output parent changed before commit",
        )
        try:
            _durable_bootstrap_tree(
                staging,
                parent=parent,
                expected_identity=staging_identity,
                expected_parent_identity=parent_identity,
            )
            _rename_directory_noreplace(staging, destination)
        except Exception:
            if not os.path.lexists(destination):
                raise
            adopted_identity = _require_exact_bootstrap_tree(
                destination, payloads
            )
            _durable_bootstrap_tree(
                destination,
                parent=parent,
                expected_identity=adopted_identity,
                expected_parent_identity=parent_identity,
            )
            return _bootstrap_result(destination)
        published_identity = staging_identity
        staging = None
        staging_identity = None
        if after_directory_publish_step is not None:
            after_directory_publish_step(
                "post_publish_pre_parent_fsync", destination
            )
        _durable_bootstrap_tree(
            destination,
            parent=parent,
            expected_identity=published_identity,
            expected_parent_identity=parent_identity,
        )
        return _bootstrap_result(destination)
    except BootstrapCalibrationV2Error:
        raise
    except Exception as exc:
        raise BootstrapCalibrationV2Error(
            f"atomic bootstrap calibration commit failed: {exc}"
        ) from exc
    finally:
        if staging is not None and staging.exists():
            assert staging_identity is not None
            _cleanup_staging(
                staging,
                parent=parent,
                expected_staging_identity=staging_identity,
                expected_parent_identity=parent_identity,
            )


def _build_qualification_bootstrap_calibration_v2_held(
    *,
    project_root: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    output_dir: Path | str,
    after_directory_publish_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Revalidate all inputs and atomically write a nonaccepted bootstrap."""

    root = _physical_root(project_root)
    destination = _output_destination(root, output_dir)

    def derive() -> tuple[
        dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]
    ]:
        return _derive_snapshot(
            root=root,
            candidate_manifest_path=candidate_manifest_path,
            candidate_receipt_path=candidate_receipt_path,
            accepted_model_parity_manifest_path=(
                accepted_model_parity_manifest_path
            ),
            accepted_model_parity_assessment_path=(
                accepted_model_parity_assessment_path
            ),
            accepted_model_parity_receipt_path=(
                accepted_model_parity_receipt_path
            ),
        )

    candidate, snapshot, calibrations = derive()
    mapping = {
        "schema_version": 2,
        "artifact_kind": (
            "vast_publication_policy_qualification_bootstrap_calibration_mapping"
        ),
        "status": STATUS,
        "accepted": False,
        "publication_ready": False,
        "scope": SCOPE,
        "authority": "nonaccepted_qualification_bootstrap_v2",
        "policy_contract_sha256": snapshot["policy_contract_sha256"],
        "aggregation_rule": (
            "median_of_accepted_physical_model_parity_samples_v2"
        ),
        "minimum_samples_per_branch_resource": int(
            policy.MIN_CALIBRATION_SAMPLES
        ),
        "candidate_manifest_sha256": snapshot["candidate_manifest"]["sha256"],
        "candidate_receipt_sha256": snapshot["candidate_receipt"]["sha256"],
        "model_parity_acceptance_binding_sha256": snapshot[
            "model_parity_acceptance_binding_sha256"
        ],
        "calibration_evidence_sha256": snapshot[
            "calibration_evidence_sha256"
        ],
        "physical_response_evidence_sha256": snapshot[
            "physical_response_evidence_sha256"
        ],
        "calibrations": calibrations,
    }
    if "model_parity_refresh_authority" in snapshot:
        mapping["model_parity_refresh_authority"] = snapshot[
            "model_parity_refresh_authority"
        ]
    _require(
        candidate.get("artifact_kind")
        == "vast_publication_policy_capability_manifest",
        "candidate capability kind drifted before output",
    )
    return _commit(
        root=root,
        destination=destination,
        mapping=mapping,
        calibrations=calibrations,
        snapshot=snapshot,
        revalidate=derive,
        after_directory_publish_step=after_directory_publish_step,
    )


@wraps(_build_qualification_bootstrap_calibration_v2_held)
def build_qualification_bootstrap_calibration_v2(
    *args: Any, **kwargs: Any
) -> dict[str, Any]:
    """Build under held input/root custody and cold-load through a fresh root."""

    _require(not args, "bootstrap builder accepts keyword arguments only")
    root = _physical_root(kwargs.get("project_root"))
    input_paths = (
        kwargs.get("candidate_manifest_path"),
        kwargs.get("candidate_receipt_path"),
        kwargs.get("accepted_model_parity_manifest_path"),
        kwargs.get("accepted_model_parity_assessment_path"),
        kwargs.get("accepted_model_parity_receipt_path"),
    )
    resolved_inputs = tuple(
        _resolve_file(
            root,
            _relative_input(root, value, f"qualification bootstrap input[{position}]"),
            f"qualification bootstrap input[{position}]",
        )
        for position, value in enumerate(input_paths)
    )
    candidate_inputs = resolved_inputs[:2]
    acceptance_inputs = resolved_inputs[2:]
    candidate_parents = {path.parent for path in candidate_inputs}
    acceptance_parents = {path.parent for path in acceptance_inputs}
    _require(
        len(candidate_parents) == 1 and len(acceptance_parents) == 1,
        "qualification bootstrap input groups must each share one physical parent",
    )
    candidate_parent = next(iter(candidate_parents))
    acceptance_parent = next(iter(acceptance_parents))
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification bootstrap project_root"
        ) as custody, PhysicalRootCustodyV1.open(
            candidate_parent, label="qualification bootstrap candidate parent"
        ) as candidate_custody, PhysicalRootCustodyV1.open(
            acceptance_parent, label="qualification bootstrap acceptance parent"
        ) as acceptance_custody:
            candidate_namespace = candidate_custody.capture_read_namespace(
                candidate_inputs, label="qualification bootstrap candidate inputs"
            )
            acceptance_namespace = acceptance_custody.capture_read_namespace(
                acceptance_inputs, label="qualification bootstrap acceptance inputs"
            )
            candidate_watch = None
            acceptance_watch = None
            try:
                candidate_watch = candidate_custody.begin_read_namespace_mutation_watch(
                    candidate_inputs,
                    label="qualification bootstrap candidate inputs",
                )
                acceptance_watch = acceptance_custody.begin_read_namespace_mutation_watch(
                    acceptance_inputs,
                    label="qualification bootstrap acceptance inputs",
                )
                result = _build_qualification_bootstrap_calibration_v2_held(**kwargs)
                candidate_custody.verify_read_namespace(
                    candidate_namespace,
                    label="qualification bootstrap candidate inputs",
                )
                acceptance_custody.verify_read_namespace(
                    acceptance_namespace,
                    label="qualification bootstrap acceptance inputs",
                )
                candidate_custody.verify_pinned_directory_mutation_watch(
                    candidate_watch,
                    label="qualification bootstrap candidate inputs",
                )
                acceptance_custody.verify_pinned_directory_mutation_watch(
                    acceptance_watch,
                    label="qualification bootstrap acceptance inputs",
                )
                candidate_custody.verify()
                acceptance_custody.verify()
            finally:
                if candidate_watch is not None:
                    candidate_watch.close()
                if acceptance_watch is not None:
                    acceptance_watch.close()
            custody.verify()
        with PhysicalRootCustodyV1.open(
            root, label="qualification bootstrap cold project_root"
        ) as cold:
            _cold_validate_bootstrap_commit(root=root, result=result, custody=cold)
            cold.verify()
        return result
    except BootstrapCalibrationV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise BootstrapCalibrationV2Error(
            f"qualification bootstrap physical custody failed: {error}"
        ) from error


def build_policy_qualification_bootstrap_v2(**kwargs: Any) -> dict[str, Any]:
    """Compatibility entry point with the qualification-index naming scheme."""

    return build_qualification_bootstrap_calibration_v2(**kwargs)


build_policy_qualification_bootstrap_calibration_v2 = (
    build_policy_qualification_bootstrap_v2
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument(
        "--accepted-model-parity-manifest", type=Path, required=True
    )
    parser.add_argument(
        "--accepted-model-parity-assessment", type=Path, required=True
    )
    parser.add_argument(
        "--accepted-model-parity-receipt", type=Path, required=True
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = build_qualification_bootstrap_calibration_v2(
        project_root=args.project_root,
        candidate_manifest_path=args.candidate_manifest,
        candidate_receipt_path=args.candidate_receipt,
        accepted_model_parity_manifest_path=(
            args.accepted_model_parity_manifest
        ),
        accepted_model_parity_assessment_path=(
            args.accepted_model_parity_assessment
        ),
        accepted_model_parity_receipt_path=args.accepted_model_parity_receipt,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "mapping_path": str(result["mapping_path"]),
                "calibration_paths": {
                    system: str(path)
                    for system, path in result["calibration_paths"].items()
                },
                "receipt_path": str(result["receipt_path"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BootstrapCalibrationV2Error",
    "CALIBRATION_FILENAME",
    "MAPPING_FILENAME",
    "PolicyQualificationBootstrapV2Error",
    "RECEIPT_FILENAME",
    "SCOPE",
    "STATUS",
    "build_qualification_bootstrap_calibration_v2",
    "build_policy_qualification_bootstrap_calibration_v2",
    "build_policy_qualification_bootstrap_v2",
    "sha256_file",
]
