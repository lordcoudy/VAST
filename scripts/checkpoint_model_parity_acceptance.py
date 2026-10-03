#!/usr/bin/env python3
"""Physical, fail-closed acceptance for the schema-3 model-parity manifest."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ASSESSMENT_KIND = "vast_checkpoint_model_parity_accepted_assessment"
RECEIPT_KIND = "vast_checkpoint_model_parity_acceptance_receipt"
RECEIPT_STATUS = "accepted_physical_model_parity_v3"
BINDING_KIND = "vast_verified_model_parity_acceptance_binding"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
EVIDENCE_NAMES = (
    "cpu_execution_probe",
    "cuda_execution_probe",
    "calibration_corpus",
    "evaluation_corpus",
    "cpu_policy_calibration",
    "cuda_policy_calibration",
    "cpu_raw_output_bundle",
    "cuda_raw_output_bundle",
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TRANSACTION_BUNDLE_COUNT = 480
_TRANSACTION_FIELDS = {
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
_EXECUTION_BUNDLE_FIELDS = {
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


class ModelParityAcceptanceError(RuntimeError):
    """Accepted parity material is incomplete, aliased, or has drifted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelParityAcceptanceError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ModelParityAcceptanceError(
            "model-parity acceptance value is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields drifted")
    return value


def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise ModelParityAcceptanceError(
            f"model-parity artifact stat failed: {path}: {error}"
        ) from error
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _physical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise ModelParityAcceptanceError(f"project_root is unavailable: {error}") from error
    _require(lexical == resolved, "project_root is an alias")
    _require(resolved.is_dir(), "project_root is not a directory")
    _require(not _is_reparse_or_link(resolved), "project_root is a symlink/reparse point")
    _require(resolved != Path(resolved.anchor), "project_root cannot be a filesystem root")
    return resolved


def _normalized_relative(value: Any, label: str) -> Path:
    _require(type(value) is str and value and "\\" not in value, f"{label} path is invalid")
    relative = Path(value)
    _require(
        not relative.is_absolute()
        and relative.as_posix() == value
        and all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label} path is not normalized",
    )
    return relative


def _resolve_existing_file(root: Path, value: Any, label: str) -> Path:
    relative = _normalized_relative(value, label)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        _require(cursor.exists() or os.path.lexists(cursor), f"{label} is missing")
        _require(not _is_reparse_or_link(cursor), f"{label} contains a symlink/reparse point")
    try:
        resolved = cursor.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ModelParityAcceptanceError(f"{label} escaped project_root") from error
    _require(resolved == cursor, f"{label} is an alias")
    info = cursor.lstat()
    _require(stat.S_ISREG(info.st_mode), f"{label} is not a regular file")
    _require(int(info.st_nlink) == 1, f"{label} hardlink alias is prohibited")
    return cursor


def _relative_input(root: Path, value: Path | str, label: str) -> str:
    raw = Path(value)
    candidate = Path(os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw)))
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as error:
        raise ModelParityAcceptanceError(f"{label} escaped project_root") from error
    _resolve_existing_file(root, relative, label)
    return relative


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_descriptor(root: Path, relative: str, label: str) -> tuple[dict[str, Any], tuple[int, int]]:
    path = _resolve_existing_file(root, relative, label)
    before = path.stat()
    first = _hash_file(path)
    middle = path.stat()
    second = _hash_file(path)
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
    return (
        {"path": relative, "size_bytes": int(after.st_size), "sha256": first},
        (int(after.st_dev), int(after.st_ino)),
    )


def _validate_descriptor(value: Any, label: str) -> dict[str, Any]:
    item = _exact(value, {"path", "size_bytes", "sha256"}, f"{label} descriptor")
    _normalized_relative(item.get("path"), label)
    _require(type(item.get("size_bytes")) is int and item["size_bytes"] > 0, f"{label} size is invalid")
    _require(_valid_sha(item.get("sha256")), f"{label} SHA-256 is invalid")
    return _json_copy(item)


class _FileRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, dict[str, Any]] = {}
        self.identities: dict[tuple[int, int], str] = {}

    def add_path(self, relative: str, label: str) -> dict[str, Any]:
        record, identity = _stable_descriptor(self.root, relative, label)
        _require(relative not in self.records, f"{label} duplicates artifact path")
        _require(identity not in self.identities, f"{label} aliases artifact {self.identities.get(identity, '')}")
        self.records[relative] = record
        self.identities[identity] = relative
        return record

    def add_descriptor(self, descriptor: Any, label: str) -> dict[str, Any]:
        expected = _validate_descriptor(descriptor, label)
        actual = self.add_path(expected["path"], label)
        _require(actual == expected, f"{label} descriptor drifted")
        return actual


def _load_parity_manifest(path: Path) -> Mapping[str, Any]:
    from checkpoint_model_parity import load_parity_manifest

    return load_parity_manifest(path)


def _assess_model_parity(path: Path, root: Path) -> Mapping[str, Any]:
    from checkpoint_model_parity import assess_model_parity

    return assess_model_parity(path, project_root=root)


def _validate_identity(value: Mapping[str, Any], label: str) -> str:
    identity = _exact(
        value.get("identity"),
        {"schema_version", "algorithm", "canonicalization", "sha256"},
        f"{label} identity",
    )
    unsigned = {key: item for key, item in value.items() if key != "identity"}
    expected = _canonical_sha(unsigned)
    _require(
        identity
        == {
            "schema_version": 2,
            "algorithm": "sha256",
            "canonicalization": "sorted_compact_json_utf8_v2",
            "sha256": expected,
        },
        f"{label} identity drifted",
    )
    return expected


def _manifest_material(
    root: Path,
    manifest_record: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    registry: _FileRegistry,
) -> dict[str, Any]:
    _require(
        manifest.get("schema_version") == 3
        and manifest.get("artifact_kind")
        == "checkpoint_analytics_model_parity_manifest",
        "accepted model-parity manifest is not schema 3",
    )
    manifest_identity = _validate_identity(manifest, "accepted model-parity manifest")
    slots = _exact(
        manifest.get("workload_slots"), set(BRANCHES), "accepted parity workload slots"
    )
    evidence_records: list[dict[str, Any]] = []
    for branch in BRANCHES:
        slot = slots[branch]
        _require(isinstance(slot, Mapping), f"accepted parity slot {branch} is invalid")
        evidence = _exact(
            slot.get("evidence"), set(EVIDENCE_NAMES), f"accepted parity evidence {branch}"
        )
        for name in EVIDENCE_NAMES:
            reference = _exact(
                evidence[name], {"path", "sha256"}, f"accepted parity reference {branch}/{name}"
            )
            _require(
                _valid_sha(reference.get("sha256")),
                f"accepted parity reference {branch}/{name} must have a non-null SHA-256",
            )
            path_value = reference.get("path")
            _normalized_relative(path_value, f"accepted parity reference {branch}/{name}")
            record = registry.add_path(
                str(path_value), f"accepted parity evidence {branch}/{name}"
            )
            _require(
                record["sha256"] == reference["sha256"],
                f"accepted parity evidence {branch}/{name} SHA-256 drifted",
            )
            evidence_records.append(
                {"branch": branch, "evidence_name": name, **record}
            )
    _require(len(evidence_records) == 32, "accepted parity evidence coverage is not exact 32")
    toolchains = manifest.get("toolchain_registry")
    workers = manifest.get("worker_runtime_registry")
    _require(type(toolchains) is dict and bool(toolchains), "toolchain registry is missing")
    _require(type(workers) is dict and bool(workers), "worker runtime registry is missing")
    registries = {
        "toolchain_registry": _json_copy(toolchains),
        "worker_runtime_registry": _json_copy(workers),
    }
    return {
        "accepted_manifest": _json_copy(manifest_record),
        "accepted_manifest_content_identity_sha256": manifest_identity,
        "evidence": evidence_records,
        "evidence_count": 32,
        "evidence_sha256": _canonical_sha(evidence_records),
        **registries,
        "runtime_registries_sha256": _canonical_sha(registries),
    }


def _transaction_index_material(
    root: Path,
    material: Mapping[str, Any],
    *,
    registry: _FileRegistry,
) -> dict[str, Any]:
    evidence_roots: set[str] = set()
    for evidence in material["evidence"]:
        relative = _normalized_relative(
            evidence["path"],
            f"accepted parity transaction evidence {evidence['branch']}/{evidence['evidence_name']}",
        )
        parts = relative.parts
        _require(
            len(parts) >= 4
            and parts[-3] == "documents"
            and parts[-2] == evidence["branch"]
            and parts[-1] == f"{evidence['evidence_name']}.json",
            "accepted parity evidence is outside the materialization transaction layout",
        )
        evidence_roots.add(Path(*parts[:-3]).as_posix())
    _require(
        len(evidence_roots) == 1,
        "accepted parity evidence does not share one transaction root",
    )
    evidence_root = next(iter(evidence_roots))
    transaction_relative = f"{evidence_root}/transaction_index.json"
    transaction_record = registry.add_path(
        transaction_relative, "model-parity transaction index"
    )
    index = _read_json_object(
        root / transaction_relative, "model-parity transaction index"
    )
    _exact(index, _TRANSACTION_FIELDS, "model-parity transaction index")
    _require(
        index.get("schema_version") == SCHEMA_VERSION
        and index.get("artifact_kind")
        == "checkpoint_model_parity_materialization_transaction"
        and index.get("run_id") == Path(evidence_root).name
        and index.get("final_materialization_path") == evidence_root
        and index.get("document_count") == 32
        and index.get("claimed_aggregates_accepted") is False
        and index.get("synthetic_or_mock_evidence_accepted") is False,
        "model-parity transaction provenance boundary drifted",
    )
    transaction_sha = index.get("transaction_sha256")
    _require(
        _valid_sha(transaction_sha)
        and transaction_sha
        == _canonical_sha(
            {key: value for key, value in index.items() if key != "transaction_sha256"}
        ),
        "model-parity transaction self-hash drifted",
    )
    files = index.get("files")
    source_inventory = index.get("source_inventory")
    output_segments = index.get("output_segments")
    execution_bundles = index.get("execution_bundles")
    _require(type(files) is list and bool(files), "transaction file inventory is missing")
    _require(type(source_inventory) is list, "transaction source inventory is invalid")
    _require(
        type(output_segments) is list
        and len(output_segments) == _TRANSACTION_BUNDLE_COUNT,
        "transaction output coverage is not exact 480",
    )
    _require(
        type(execution_bundles) is list
        and len(execution_bundles) == _TRANSACTION_BUNDLE_COUNT
        and index.get("execution_bundle_count") == _TRANSACTION_BUNDLE_COUNT,
        "transaction execution bundle coverage is not exact 480",
    )
    _require(
        index.get("files_sha256") == _canonical_sha(files)
        and index.get("source_inventory_sha256") == _canonical_sha(source_inventory)
        and index.get("output_segments_sha256") == _canonical_sha(output_segments)
        and index.get("execution_bundles_sha256")
        == _canonical_sha(execution_bundles),
        "model-parity transaction indexed material hash drifted",
    )

    transaction_files = _FileRegistry(root)
    files_by_path: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(files):
        expected = _validate_descriptor(raw, f"transaction file[{position}]")
        path = str(expected["path"])
        _require(path not in files_by_path, "transaction file path is duplicated")
        _require(
            path.startswith(f"{evidence_root}/")
            and path != transaction_relative,
            "transaction file escaped its materialization root",
        )
        actual = transaction_files.add_descriptor(
            expected, f"transaction file[{position}]"
        )
        files_by_path[path] = actual
    for identity, path in transaction_files.identities.items():
        primary = registry.identities.get(identity)
        _require(
            primary is None or primary == path,
            "transaction file aliases an acceptance artifact",
        )
    for evidence in material["evidence"]:
        expected = {
            key: evidence[key] for key in ("path", "size_bytes", "sha256")
        }
        _require(
            files_by_path.get(str(evidence["path"])) == expected,
            "acceptance-bound evidence is absent from transaction files",
        )

    output_coordinates: set[tuple[str, str, str]] = set()
    for segment in output_segments:
        _require(type(segment) is dict, "transaction output segment is invalid")
        coordinate = (
            str(segment.get("branch")),
            str(segment.get("resource")),
            str(segment.get("sample_id")),
        )
        _require(
            coordinate[0] in BRANCHES
            and coordinate[1] in {"openvino_cpu", "tensorrt_cuda"}
            and coordinate[2]
            and _valid_sha(segment.get("preprocessed_tensor_sha256")),
            "transaction output coordinate is invalid",
        )
        _require(
            coordinate not in output_coordinates,
            "transaction output coordinate is duplicated",
        )
        output_coordinates.add(coordinate)

    execution_coordinates: set[tuple[str, str, str]] = set()
    request_ids: set[str] = set()
    coverage: dict[tuple[str, str, str, str], int] = {}
    for row in execution_bundles:
        _exact(row, _EXECUTION_BUNDLE_FIELDS, "transaction execution bundle")
        branch = row.get("branch")
        resource = row.get("resource")
        role = row.get("role")
        codec = row.get("codec")
        sample_id = row.get("sample_id")
        request_id = row.get("request_id")
        coordinate = (str(branch), str(resource), str(sample_id))
        _require(
            branch in BRANCHES
            and resource in {"openvino_cpu", "tensorrt_cuda"}
            and role in {"calibration", "evaluation"}
            and codec in {"h264", "h265"}
            and type(sample_id) is str
            and bool(sample_id)
            and type(request_id) is str
            and bool(request_id)
            and request_id not in request_ids,
            "transaction execution bundle coordinate is invalid",
        )
        _require(
            coordinate not in execution_coordinates,
            "transaction execution coordinate is duplicated",
        )
        manifest = _validate_descriptor(
            row.get("manifest"), "transaction execution bundle manifest"
        )
        _require(
            manifest["path"]
            == f"{evidence_root}/execution_bundles/{request_id}/manifest.json"
            and files_by_path.get(str(manifest["path"])) == manifest,
            "transaction execution bundle manifest descriptor drifted",
        )
        for field in (
            "manifest_identity_sha256",
            "request_sha256",
            "response_sha256",
            "input_tensor_sha256",
            "output_tensor_sha256",
        ):
            _require(_valid_sha(row.get(field)), f"transaction {field} is invalid")
        request_ids.add(request_id)
        execution_coordinates.add(coordinate)
        key = (str(branch), str(resource), str(role), str(codec))
        coverage[key] = coverage.get(key, 0) + 1
    _require(
        execution_coordinates == output_coordinates,
        "transaction execution/output coordinate coverage drifted",
    )
    _require(
        coverage
        == {
            (branch, resource, role, codec): 15
            for branch in BRANCHES
            for resource in ("openvino_cpu", "tensorrt_cuda")
            for role in ("calibration", "evaluation")
            for codec in ("h264", "h265")
        },
        "transaction balanced execution coverage drifted",
    )
    return {
        **transaction_record,
        "transaction_sha256": transaction_sha,
        "files_sha256": index["files_sha256"],
        "output_segments_sha256": index["output_segments_sha256"],
        "execution_bundle_count": _TRANSACTION_BUNDLE_COUNT,
        "execution_bundles_sha256": index["execution_bundles_sha256"],
    }


def _validate_canonical_assessment(
    value: Mapping[str, Any], *, manifest_identity: str
) -> dict[str, Any]:
    _require(type(value) is dict, "model-parity assessor result must be a dictionary")
    assessment_identity = _validate_identity(value, "model-parity assessor result")
    _require(
        value.get("schema_version") == 3
        and value.get("artifact_kind") == "checkpoint_analytics_model_parity_assessment",
        "model-parity assessor schema/kind drifted",
    )
    _require(
        value.get("manifest_identity_sha256") == manifest_identity,
        "model-parity assessor manifest identity drifted",
    )
    _require(
        value.get("publication_ready") is True and value.get("blockers") == [],
        "model-parity assessor is not publication-ready",
    )
    _require(
        value.get("openvino_gpu_counted_as_nvidia_cuda") is False
        and value.get("network_or_download_performed") is False
        and value.get("permitted_external_command") == "docker image inspect only"
        and value.get("claimed_aggregate_metrics_accepted") is False
        and value.get("raw_per_sample_outputs_recomputed") is True,
        "model-parity assessor safety or raw per-sample boundary drifted",
    )
    runtime_images = _exact(
        value.get("runtime_images"), {"cpu", "gpu"}, "model-parity runtime images"
    )
    image_facts: dict[str, Any] = {}
    for resource in ("cpu", "gpu"):
        record = runtime_images[resource]
        _require(isinstance(record, Mapping), f"runtime image {resource} is invalid")
        _require(
            _valid_sha(str(record.get("image_id", "")).removeprefix("sha256:")),
            f"runtime image {resource} identity is invalid",
        )
        _require(
            type(record.get("reference")) is str
            and bool(record["reference"])
            and type(record.get("repo_digests")) is list
            and bool(record["repo_digests"])
            and type(record.get("architecture")) is str
            and bool(record["architecture"])
            and type(record.get("os")) is str
            and bool(record["os"]),
            f"runtime image {resource} inspect facts are incomplete",
        )
        image_facts[resource] = _json_copy(record)
    branches = _exact(value.get("branches"), set(BRANCHES), "model-parity assessment branches")
    for branch in BRANCHES:
        _require(
            isinstance(branches[branch], Mapping)
            and branches[branch].get("ready") is True
            and branches[branch].get("blockers") == [],
            f"model-parity branch {branch} is not ready",
        )
    return {
        "canonical_assessment_identity_sha256": assessment_identity,
        "runtime_images": image_facts,
        "runtime_images_sha256": _canonical_sha(image_facts),
    }


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelParityAcceptanceError(f"invalid {label}: {error}") from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    return value


def _write_new_json(
    path: Path,
    value: Mapping[str, Any],
    label: str,
    *,
    _fault_hook: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    _require(path.parent.is_dir(), f"{label} parent is missing")
    _require(not _is_reparse_or_link(path.parent), f"{label} parent is unsafe")
    payload = _canonical_bytes(value) + b"\n"
    custody: PhysicalRootCustodyV1 | None = None
    try:
        custody = PhysicalRootCustodyV1.open(
            path.parent, label=f"{label} output parent"
        )
        record, _identity, _disposition = custody.commit_or_adopt_exact_identity(
            path.name,
            payload,
            label=label,
            mode=0o444,
            create_parents=False,
            after_publish_step=_fault_hook,
        )
        custody.verify()
    except PublicationPhysicalIoV1Error as error:
        raise ModelParityAcceptanceError(
            f"{label} atomic commit/adoption failed"
        ) from error
    finally:
        if custody is not None:
            custody.close()
    return {
        "path": path.name,
        "size_bytes": record["size_bytes"],
        "sha256": record["sha256"],
    }


def _output_path(root: Path, value: Path | str, label: str) -> Path:
    raw = Path(value)
    candidate = Path(os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw)))
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ModelParityAcceptanceError(f"{label} escaped project_root") from error
    _require(candidate != root and candidate.parent.is_dir(), f"{label} parent is missing")
    cursor = root
    for part in candidate.parent.relative_to(root).parts:
        cursor = cursor / part
        _require(not _is_reparse_or_link(cursor), f"{label} parent contains reparse point")
    _require(candidate.parent.resolve() == candidate.parent, f"{label} parent is an alias")
    return candidate


def promote_model_parity_acceptance(
    *,
    project_root: Path | str,
    accepted_manifest_path: Path | str,
    accepted_assessment_path: Path | str,
    acceptance_receipt_path: Path | str,
) -> dict[str, Any]:
    """Assess final physical evidence, then atomically create assessment and receipt."""

    root = _physical_root(project_root)
    manifest_relative = _relative_input(
        root, accepted_manifest_path, "accepted model-parity manifest"
    )
    assessment_path = _output_path(root, accepted_assessment_path, "accepted assessment")
    receipt_path = _output_path(root, acceptance_receipt_path, "acceptance receipt")
    _require(assessment_path != receipt_path, "assessment and receipt paths must be distinct")
    registry = _FileRegistry(root)
    manifest_record = registry.add_path(manifest_relative, "accepted model-parity manifest")
    manifest_path = root / manifest_relative
    try:
        manifest = _load_parity_manifest(manifest_path)
    except Exception as error:
        raise ModelParityAcceptanceError(
            f"accepted model-parity manifest loader rejected artifact: {error}"
        ) from error
    material = _manifest_material(root, manifest_record, manifest, registry=registry)
    transaction = _transaction_index_material(
        root, material, registry=registry
    )
    # The production assessor performs only read-only local Docker image inspect.
    try:
        assessor_result = _assess_model_parity(manifest_path, root)
    except Exception as error:
        raise ModelParityAcceptanceError(f"model-parity assessment failed: {error}") from error
    assessment_binding = _validate_canonical_assessment(
        assessor_result,
        manifest_identity=material["accepted_manifest_content_identity_sha256"],
    )
    # Rehash manifest and all 32 evidence files after assessment; no time-of-check gap.
    post_registry = _FileRegistry(root)
    post_manifest = post_registry.add_path(manifest_relative, "post-assessment manifest")
    _require(post_manifest == manifest_record, "accepted manifest drifted during assessment")
    for evidence in material["evidence"]:
        post = post_registry.add_path(
            evidence["path"],
            f"post-assessment evidence {evidence['branch']}/{evidence['evidence_name']}",
        )
        _require(
            post == {key: evidence[key] for key in ("path", "size_bytes", "sha256")},
            f"parity evidence {evidence['branch']}/{evidence['evidence_name']} drifted during assessment",
        )
    post_transaction = _transaction_index_material(
        root, material, registry=post_registry
    )
    _require(
        post_transaction == transaction,
        "model-parity transaction drifted during assessment",
    )
    accepted_assessment = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": RECEIPT_STATUS,
        "accepted_manifest": material["accepted_manifest"],
        "accepted_manifest_content_identity_sha256": material[
            "accepted_manifest_content_identity_sha256"
        ],
        "canonical_assessment_identity_sha256": assessment_binding[
            "canonical_assessment_identity_sha256"
        ],
        "publication_ready": True,
        "blockers": [],
        "evidence_count": 32,
        "evidence_sha256": material["evidence_sha256"],
        "transaction_index": transaction,
        "runtime_images": assessment_binding["runtime_images"],
        "runtime_images_sha256": assessment_binding["runtime_images_sha256"],
        "runtime_registries_sha256": material["runtime_registries_sha256"],
    }
    accepted_assessment["assessment_sha256"] = _canonical_sha(accepted_assessment)
    assessment_relative = assessment_path.relative_to(root).as_posix()
    local_assessment_record = _write_new_json(
        assessment_path, accepted_assessment, "accepted assessment"
    )
    assessment_record = {
        "path": assessment_relative,
        "size_bytes": local_assessment_record["size_bytes"],
        "sha256": local_assessment_record["sha256"],
    }
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": RECEIPT_STATUS,
        "accepted_manifest": material["accepted_manifest"],
        "accepted_manifest_content_identity_sha256": material[
            "accepted_manifest_content_identity_sha256"
        ],
        "accepted_assessment": assessment_record,
        "accepted_assessment_identity_sha256": accepted_assessment[
            "assessment_sha256"
        ],
        "canonical_assessment_identity_sha256": assessment_binding[
            "canonical_assessment_identity_sha256"
        ],
        "publication_ready": True,
        "blockers": [],
        "evidence": material["evidence"],
        "evidence_count": 32,
        "evidence_sha256": material["evidence_sha256"],
        "transaction_index": transaction,
        "toolchain_registry": material["toolchain_registry"],
        "worker_runtime_registry": material["worker_runtime_registry"],
        "runtime_registries_sha256": material["runtime_registries_sha256"],
        "runtime_images": assessment_binding["runtime_images"],
        "runtime_images_sha256": assessment_binding["runtime_images_sha256"],
    }
    receipt["receipt_sha256"] = _canonical_sha(receipt)
    _write_new_json(receipt_path, receipt, "model-parity acceptance receipt")
    return load_verified_model_parity_acceptance(
        project_root=root,
        receipt_path=receipt_path,
        parity_loader=lambda _path: _json_copy(manifest),
        parity_assessor=lambda _path, _root: _json_copy(assessor_result),
    )


def _validate_self_hash(value: Mapping[str, Any], field: str, label: str) -> str:
    declared = value.get(field)
    _require(_valid_sha(declared), f"{label} {field} is invalid")
    expected = _canonical_sha({key: item for key, item in value.items() if key != field})
    _require(declared == expected, f"{label} self-hash drifted")
    return str(declared)


def load_verified_model_parity_acceptance(
    *,
    project_root: Path | str,
    receipt_path: Path | str,
    parity_loader: Any = None,
    parity_assessor: Any = None,
) -> dict[str, Any]:
    """Rehash and re-assess every authorization input on every load/resume."""

    root = _physical_root(project_root)
    receipt_relative = _relative_input(root, receipt_path, "model-parity acceptance receipt")
    registry = _FileRegistry(root)
    receipt_record = registry.add_path(receipt_relative, "model-parity acceptance receipt")
    receipt = _read_json_object(root / receipt_relative, "model-parity acceptance receipt")
    receipt_version = receipt.get("schema_version")
    _require(
        receipt_version in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION},
        "model-parity acceptance receipt schema is unsupported",
    )
    expected_receipt_fields = {
        "schema_version", "artifact_kind", "status", "accepted_manifest",
        "accepted_manifest_content_identity_sha256", "accepted_assessment",
        "accepted_assessment_identity_sha256", "canonical_assessment_identity_sha256",
        "publication_ready", "blockers", "evidence", "evidence_count",
        "evidence_sha256", "toolchain_registry", "worker_runtime_registry",
        "runtime_registries_sha256", "runtime_images", "runtime_images_sha256",
        "receipt_sha256",
    }
    if receipt_version == SCHEMA_VERSION:
        expected_receipt_fields.add("transaction_index")
    _exact(receipt, expected_receipt_fields, "model-parity acceptance receipt")
    _require(
        receipt.get("artifact_kind") == RECEIPT_KIND
        and receipt.get("status") == RECEIPT_STATUS
        and receipt.get("publication_ready") is True
        and receipt.get("blockers") == [],
        "model-parity acceptance receipt is not accepted",
    )
    receipt_identity = _validate_self_hash(
        receipt, "receipt_sha256", "model-parity acceptance receipt"
    )
    manifest_record = registry.add_descriptor(
        receipt["accepted_manifest"], "accepted model-parity manifest"
    )
    assessment_record = registry.add_descriptor(
        receipt["accepted_assessment"], "accepted model-parity assessment"
    )
    manifest_path = root / manifest_record["path"]
    loader = parity_loader or _load_parity_manifest
    assessor = parity_assessor or _assess_model_parity
    try:
        manifest = loader(manifest_path)
    except Exception as error:
        raise ModelParityAcceptanceError(f"accepted parity manifest rejected: {error}") from error
    manifest_material = _manifest_material(root, manifest_record, manifest, registry=registry)
    _require(
        manifest_material["accepted_manifest_content_identity_sha256"]
        == receipt["accepted_manifest_content_identity_sha256"],
        "accepted parity manifest content identity drifted",
    )
    assessment = _read_json_object(
        root / assessment_record["path"], "accepted model-parity assessment"
    )
    assessment_fields = {
        "schema_version", "artifact_kind", "status", "accepted_manifest",
        "accepted_manifest_content_identity_sha256", "canonical_assessment_identity_sha256",
        "publication_ready", "blockers", "evidence_count", "evidence_sha256",
        "runtime_images", "runtime_images_sha256", "runtime_registries_sha256",
        "assessment_sha256",
    }
    if receipt_version == SCHEMA_VERSION:
        assessment_fields.add("transaction_index")
    _exact(assessment, assessment_fields, "accepted model-parity assessment")
    _require(
        assessment.get("schema_version") == receipt_version
        and assessment.get("artifact_kind") == ASSESSMENT_KIND
        and assessment.get("status") == RECEIPT_STATUS
        and assessment.get("publication_ready") is True
        and assessment.get("blockers") == [],
        "accepted model-parity assessment is not ready",
    )
    assessment_identity = _validate_self_hash(
        assessment, "assessment_sha256", "accepted model-parity assessment"
    )
    _require(
        assessment_identity == receipt["accepted_assessment_identity_sha256"],
        "accepted model-parity assessment identity drifted",
    )
    expected_evidence = manifest_material["evidence"]
    _require(
        receipt.get("evidence_count") == 32
        and receipt.get("evidence") == expected_evidence
        and receipt.get("evidence_sha256") == _canonical_sha(expected_evidence)
        and assessment.get("evidence_count") == 32
        and assessment.get("evidence_sha256") == receipt["evidence_sha256"],
        "accepted model-parity evidence set drifted",
    )
    transaction: dict[str, Any] | None = None
    if receipt_version == SCHEMA_VERSION:
        transaction = _transaction_index_material(
            root, manifest_material, registry=registry
        )
        _require(
            receipt.get("transaction_index") == transaction
            and assessment.get("transaction_index") == transaction,
            "accepted model-parity transaction binding drifted",
        )
    registries = {
        "toolchain_registry": manifest_material["toolchain_registry"],
        "worker_runtime_registry": manifest_material["worker_runtime_registry"],
    }
    _require(
        receipt["toolchain_registry"] == registries["toolchain_registry"]
        and receipt["worker_runtime_registry"] == registries["worker_runtime_registry"]
        and receipt["runtime_registries_sha256"] == _canonical_sha(registries)
        and assessment["runtime_registries_sha256"] == receipt["runtime_registries_sha256"],
        "accepted model-parity runtime registry drifted",
    )
    try:
        current_assessment = assessor(manifest_path, root)
    except Exception as error:
        raise ModelParityAcceptanceError(f"model-parity re-assessment failed: {error}") from error
    assessed = _validate_canonical_assessment(
        current_assessment,
        manifest_identity=manifest_material["accepted_manifest_content_identity_sha256"],
    )
    _require(
        assessed["canonical_assessment_identity_sha256"]
        == receipt["canonical_assessment_identity_sha256"]
        == assessment["canonical_assessment_identity_sha256"]
        and assessed["runtime_images"] == receipt["runtime_images"] == assessment["runtime_images"]
        and assessed["runtime_images_sha256"]
        == receipt["runtime_images_sha256"]
        == assessment["runtime_images_sha256"],
        "model-parity accepted assessment has drifted",
    )
    if transaction is not None:
        post_registry = _FileRegistry(root)
        post_manifest = post_registry.add_path(
            manifest_record["path"], "post-reassessment model-parity manifest"
        )
        _require(
            post_manifest == manifest_record,
            "accepted model-parity manifest drifted during reassessment",
        )
        post_transaction = _transaction_index_material(
            root, manifest_material, registry=post_registry
        )
        _require(
            post_transaction == transaction,
            "accepted model-parity transaction drifted during reassessment",
        )
    files = [registry.records[path] for path in sorted(registry.records)]
    binding = {
        "schema_version": receipt_version,
        "artifact_kind": BINDING_KIND,
        "receipt": receipt_record,
        "accepted_manifest": manifest_record,
        "accepted_assessment": assessment_record,
        "acceptance_identity_sha256": receipt_identity,
        "accepted_manifest_content_identity_sha256": manifest_material[
            "accepted_manifest_content_identity_sha256"
        ],
        "canonical_assessment_identity_sha256": assessed[
            "canonical_assessment_identity_sha256"
        ],
        "evidence_count": 32,
        "evidence_sha256": receipt["evidence_sha256"],
        "runtime_registries_sha256": receipt["runtime_registries_sha256"],
        "runtime_images_sha256": receipt["runtime_images_sha256"],
        "files": files,
        "files_sha256": _canonical_sha(files),
    }
    if transaction is not None:
        binding["transaction_index"] = transaction
    binding["binding_sha256"] = _canonical_sha(binding)
    return _json_copy(binding)


__all__ = [
    "ASSESSMENT_KIND",
    "BINDING_KIND",
    "ModelParityAcceptanceError",
    "RECEIPT_KIND",
    "RECEIPT_STATUS",
    "SCHEMA_VERSION",
    "load_verified_model_parity_acceptance",
    "promote_model_parity_acceptance",
]
