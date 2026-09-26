#!/usr/bin/env python3
"""Commit-last physical acceptance for patch-bound model parity schema 4."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import checkpoint_model_parity_acceptance as acceptance_v3
import checkpoint_model_parity_v4 as parity_v4
from checkpoint_gstreamer_analytics_sidecar import (
    load_execution_config,
    load_materialized_binding_set,
)
from analytics_execution_worker import validate_runtime_probe


SCHEMA_VERSION = 4
ASSESSMENT_KIND = "vast_checkpoint_model_parity_accepted_assessment_v4"
RECEIPT_KIND = "vast_checkpoint_model_parity_acceptance_receipt_v4"
BINDING_KIND = "vast_verified_model_parity_acceptance_binding_v4"
RECEIPT_STATUS = "accepted_physical_model_parity_v4"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_TRANSACTION_FIELDS = _DESCRIPTOR_FIELDS | {
    "transaction_sha256", "files_sha256", "output_segments_sha256",
    "execution_bundle_count", "execution_bundles_sha256",
}


class ModelParityAcceptanceV4Error(RuntimeError):
    """Schema-4 acceptance input is missing, stale, or cross-bound wrongly."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelParityAcceptanceV4Error(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ModelParityAcceptanceV4Error("model-parity v4 acceptance is not canonical JSON") from error


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _copy(value: Any) -> Any:
    return json.loads(_canonical(value).decode("ascii"))


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not a mapping")
    _require(set(value) == fields, f"{label} fields drifted")
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    try:
        return parity_v4._descriptor(value, label)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error


def _authority_descriptor(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    return _descriptor({key: value[key] for key in _DESCRIPTOR_FIELDS}, label)


def validate_transaction_binding_v4(
    value: Any,
    *,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = _exact(value, _TRANSACTION_FIELDS, "model-parity v4 transaction binding")
    result = _descriptor({key: item[key] for key in _DESCRIPTOR_FIELDS}, "model-parity v4 transaction index")
    _require(result["path"].endswith("/transaction_index.json"), "model-parity v4 transaction path is invalid")
    for field in (
        "transaction_sha256", "files_sha256", "output_segments_sha256",
        "execution_bundles_sha256",
    ):
        _require(_valid_sha(item.get(field)), f"model-parity v4 transaction {field} is invalid")
        result[field] = item[field]
    _require(item.get("execution_bundle_count") == 480, "model-parity v4 transaction execution bundle coverage is not exact 480")
    result["execution_bundle_count"] = 480
    if expected is not None:
        _require(result == dict(expected), "model-parity v4 transaction/output authority drifted")
    return result


def validate_refresh_authority_v4(value: Any) -> dict[str, Any]:
    authority = _exact(
        value,
        {"image_identity_patch", "workers", "execution_config", "binding_set", "runtime_probes"},
        "model-parity v4 refresh authority",
    )
    patch = _exact(
        authority.get("image_identity_patch"),
        {"path", "size_bytes", "sha256", "patch_sha256", "refresh_blockers", "resolved_blockers", "workers"},
        "model-parity v4 image patch authority",
    )
    _authority_descriptor(patch, "model-parity v4 image patch")
    _require(_valid_sha(patch.get("patch_sha256")), "model-parity v4 image patch identity is invalid")
    _require(
        patch.get("refresh_blockers") == list(parity_v4.REFRESH_BLOCKERS)
        and patch.get("resolved_blockers") == [],
        "model-parity v4 acceptance must resolve only the exact two refresh blockers",
    )
    patch_workers = _exact(patch.get("workers"), {"cpu", "gpu"}, "model-parity v4 image patch workers")
    workers = _exact(authority.get("workers"), {"cpu", "gpu"}, "model-parity v4 resolved workers")
    probes = _exact(authority.get("runtime_probes"), {"cpu", "gpu"}, "model-parity v4 runtime probes")
    for resource in ("cpu", "gpu"):
        patch_worker = _exact(
            patch_workers[resource],
            {"image", "image_id", "base_image", "base_image_id", "previous_accepted_image_id", "source_set_sha256", "receipt_sha256"},
            f"model-parity v4 {resource} patch worker",
        )
        worker = _exact(
            workers[resource],
            {"image", "image_id", "worker_implementation_sha256", "source_set_sha256", "receipt_sha256"},
            f"model-parity v4 {resource} resolved worker",
        )
        probe = _exact(
            probes[resource],
            {"path", "size_bytes", "sha256", "worker_implementation_sha256"},
            f"model-parity v4 {resource} runtime probe",
        )
        _authority_descriptor(probe, f"model-parity v4 {resource} runtime probe")
        _require(
            worker.get("image") == patch_worker.get("image")
            and worker.get("image_id") == patch_worker.get("image_id")
            and worker.get("source_set_sha256") == patch_worker.get("source_set_sha256")
            and worker.get("receipt_sha256") == patch_worker.get("receipt_sha256")
            and worker.get("worker_implementation_sha256") == probe.get("worker_implementation_sha256")
            and all(
                _valid_sha(item)
                for item in (
                    worker.get("source_set_sha256"), worker.get("receipt_sha256"),
                    worker.get("worker_implementation_sha256"),
                )
            ),
            f"model-parity v4 {resource} worker identity cross-binding drifted",
        )
    config = _exact(
        authority.get("execution_config"),
        {"path", "size_bytes", "sha256", "content_identity_sha256", "worker_projection_sha256"},
        "model-parity v4 execution config",
    )
    _authority_descriptor(config, "model-parity v4 execution config")
    _require(_valid_sha(config.get("content_identity_sha256")) and _valid_sha(config.get("worker_projection_sha256")), "model-parity v4 execution config identities are invalid")
    binding_set = _exact(
        authority.get("binding_set"),
        {"index", "identity_sha256", "bindings_identity_sha256", "bindings"},
        "model-parity v4 binding set authority",
    )
    _descriptor(binding_set.get("index"), "model-parity v4 binding-set index")
    _require(_valid_sha(binding_set.get("identity_sha256")) and _valid_sha(binding_set.get("bindings_identity_sha256")), "model-parity v4 binding-set identities are invalid")
    bindings = binding_set.get("bindings")
    expected_coordinates = {
        f"{branch}:{resource}"
        for branch in parity_v4.parity_v3.BRANCHES
        for resource in ("cpu", "gpu")
    }
    _require(type(bindings) is dict and set(bindings) == expected_coordinates, "model-parity v4 endpoint binding coverage is not exact 8")
    normalized_bindings = {
        coordinate: _descriptor(bindings[coordinate], f"model-parity v4 endpoint binding {coordinate}")
        for coordinate in sorted(expected_coordinates)
    }
    return _copy({
        "image_identity_patch": dict(patch),
        "workers": dict(workers),
        "execution_config": dict(config),
        "binding_set": {
            "index": dict(binding_set["index"]),
            "identity_sha256": binding_set["identity_sha256"],
            "bindings_identity_sha256": binding_set["bindings_identity_sha256"],
            "bindings": normalized_bindings,
        },
        "runtime_probes": dict(probes),
    })


def _manifest_material(
    root: Path,
    manifest_record: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    registry: Any,
) -> dict[str, Any]:
    _require(
        manifest.get("schema_version") == SCHEMA_VERSION
        and manifest.get("artifact_kind") == parity_v4.MANIFEST_KIND,
        "accepted model-parity manifest is not exact schema 4",
    )
    try:
        manifest_identity = acceptance_v3._validate_identity(manifest, "accepted model-parity v4 manifest")
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error
    slots = _exact(manifest.get("workload_slots"), set(parity_v4.parity_v3.BRANCHES), "accepted model-parity v4 workload slots")
    evidence: list[dict[str, Any]] = []
    for branch in parity_v4.parity_v3.BRANCHES:
        slot = slots[branch]
        references = _exact(slot.get("evidence"), set(parity_v4.parity_v3.EVIDENCE_NAMES), f"accepted model-parity v4 evidence {branch}")
        for name in parity_v4.parity_v3.EVIDENCE_NAMES:
            reference = _exact(references[name], {"path", "sha256"}, f"accepted model-parity v4 evidence {branch}/{name}")
            _require(_valid_sha(reference.get("sha256")), f"accepted model-parity v4 evidence {branch}/{name} SHA-256 is invalid")
            record = registry.add_path(str(reference.get("path")), f"accepted model-parity v4 evidence {branch}/{name}")
            _require(record["sha256"] == reference["sha256"], f"accepted model-parity v4 evidence {branch}/{name} drifted")
            evidence.append({"branch": branch, "evidence_name": name, **record})
    _require(len(evidence) == 32, "accepted model-parity v4 evidence coverage is not exact 32")
    registries = {
        "toolchain_registry": _copy(manifest["toolchain_registry"]),
        "worker_runtime_registry": _copy(manifest["worker_runtime_registry"]),
    }
    return {
        "accepted_manifest": _copy(manifest_record),
        "accepted_manifest_content_identity_sha256": manifest_identity,
        "evidence": evidence,
        "evidence_count": 32,
        "evidence_sha256": _sha(evidence),
        **registries,
        "runtime_registries_sha256": _sha(registries),
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelParityAcceptanceV4Error(f"invalid {label}: {error}") from error
    _require(type(value) is dict and _canonical(value) + b"\n" == raw, f"{label} is not canonical JSON")
    return value


def _probe_documents(root: Path, refresh: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    config_path = parity_v4.verify_descriptor(
        root,
        _authority_descriptor(refresh["execution_config"], "model-parity v4 execution config"),
        "model-parity v4 execution config",
    )
    config = load_execution_config(config_path)
    _require(
        config["identity"]["sha256"] == refresh["execution_config"]["content_identity_sha256"]
        and parity_v4.canonical_sha256(config["workers"]) == refresh["execution_config"]["worker_projection_sha256"],
        "model-parity v4 execution config identity drifted",
    )
    probes: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        probe_path = parity_v4.verify_descriptor(
            root,
            _authority_descriptor(refresh["runtime_probes"][resource], f"{resource} runtime probe"),
            f"model-parity v4 {resource} runtime probe",
        )
        probe = _read_json(probe_path, f"model-parity v4 {resource} runtime probe")
        checked = validate_runtime_probe(probe, engine=config["workers"][resource]["engine"])
        _require(
            checked["worker_implementation_sha256"] == refresh["runtime_probes"][resource]["worker_implementation_sha256"],
            f"model-parity v4 {resource} runtime probe implementation drifted",
        )
        probes[resource] = checked
    return {"config": config, "probes": probes}


def _physical_refresh_authority(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    binding_set_authority: Mapping[str, Any],
    registry: Any,
) -> dict[str, Any]:
    manifest_refresh = manifest["refresh_authority"]
    for label, descriptor in (
        ("source schema-3 parity manifest", manifest_refresh["source_manifest"]),
        ("qualification image patch", manifest_refresh["image_identity_patch"]),
        ("versioned execution config", manifest_refresh["execution_config"]),
        ("CPU live runtime probe", manifest_refresh["runtime_probes"]["cpu"]),
        ("GPU live runtime probe", manifest_refresh["runtime_probes"]["gpu"]),
    ):
        registry.add_descriptor(_authority_descriptor(descriptor, label), label)
    patch_workers = manifest_refresh["image_identity_patch"]["workers"]
    workers = {
        resource: {
            "image": patch_workers[resource]["image"],
            "image_id": patch_workers[resource]["image_id"],
            "worker_implementation_sha256": manifest_refresh["runtime_probes"][resource]["worker_implementation_sha256"],
            "source_set_sha256": patch_workers[resource]["source_set_sha256"],
            "receipt_sha256": patch_workers[resource]["receipt_sha256"],
        }
        for resource in ("cpu", "gpu")
    }
    refresh = validate_refresh_authority_v4({
        "image_identity_patch": manifest_refresh["image_identity_patch"],
        "workers": workers,
        "execution_config": manifest_refresh["execution_config"],
        "binding_set": binding_set_authority,
        "runtime_probes": manifest_refresh["runtime_probes"],
    })
    index_record = registry.add_descriptor(refresh["binding_set"]["index"], "model-parity v4 binding index")
    for coordinate, descriptor in refresh["binding_set"]["bindings"].items():
        registry.add_descriptor(descriptor, f"model-parity v4 endpoint binding {coordinate}")
    loaded = _probe_documents(root, refresh)
    binding_root = root.joinpath(*PurePosixPath(index_record["path"]).parts).parent
    try:
        materialized = load_materialized_binding_set(
            binding_root,
            execution_config=loaded["config"],
            runtime_probes=loaded["probes"],
        )
    except Exception as error:
        raise ModelParityAcceptanceV4Error(f"model-parity v4 binding set rejected: {error}") from error
    _require(
        materialized.index["identity"]["sha256"] == refresh["binding_set"]["identity_sha256"]
        and materialized.index["bindings_identity_sha256"] == refresh["binding_set"]["bindings_identity_sha256"],
        "model-parity v4 binding-set identity drifted",
    )
    observed = {
        f"{branch}:{resource}": parity_v4.file_descriptor(root, path, f"model-parity v4 endpoint binding {branch}:{resource}")
        for (branch, resource), path in materialized.binding_paths.items()
    }
    _require(observed == refresh["binding_set"]["bindings"], "model-parity v4 endpoint binding descriptors drifted")
    return refresh


def _assessment_binding(value: Mapping[str, Any], manifest_identity: str) -> dict[str, Any]:
    try:
        identity = acceptance_v3._validate_identity(value, "model-parity v4 canonical assessment")
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == parity_v4.ASSESSMENT_KIND
        and value.get("manifest_identity_sha256") == manifest_identity
        and value.get("publication_ready") is True
        and value.get("blockers") == []
        and value.get("refresh_blockers_resolved") == list(parity_v4.REFRESH_BLOCKERS)
        and value.get("openvino_gpu_counted_as_nvidia_cuda") is False
        and value.get("network_or_download_performed") is False
        and value.get("permitted_external_command") == "docker image inspect only"
        and value.get("claimed_aggregate_metrics_accepted") is False
        and value.get("raw_per_sample_outputs_recomputed") is True,
        "model-parity v4 canonical assessment is not publication-ready",
    )
    runtime = {
        "base": _copy(value.get("runtime_images")),
        "workers": _copy(value.get("worker_runtime_images")),
    }
    _require(
        all(
            type(runtime[group]) is dict
            and set(runtime[group]) == {"cpu", "gpu"}
            for group in ("base", "workers")
        ),
        "model-parity v4 runtime image coverage drifted",
    )
    return {
        "canonical_assessment_identity_sha256": identity,
        "runtime_images": runtime,
        "runtime_images_sha256": _sha(runtime),
    }


def _output_path(root: Path, value: Path | str, label: str) -> Path:
    try:
        return acceptance_v3._output_path(root, value, label)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error


def _write_json(root: Path, path: Path, value: Mapping[str, Any], label: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    try:
        acceptance_v3._write_new_json(path, value, label)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error
    return parity_v4.file_descriptor(root, path, label)


def _self_hash(value: Mapping[str, Any], field: str, label: str) -> str:
    declared = value.get(field)
    _require(_valid_sha(declared) and declared == _sha({key: item for key, item in value.items() if key != field}), f"{label} self-hash drifted")
    return str(declared)


def _rollback_owned(root: Path, records: list[dict[str, Any]]) -> None:
    for record in reversed(records):
        path = root.joinpath(*PurePosixPath(record["path"]).parts)
        if not path.exists():
            continue
        current = parity_v4.file_descriptor(root, path, "model-parity v4 rollback artifact")
        _require(current == record, "model-parity v4 acceptance artifact changed before rollback")
        path.chmod(0o600)
        path.unlink()


def _files(registry: Any) -> list[dict[str, Any]]:
    rows = [registry.records[path] for path in sorted(registry.records)]
    _require(len(rows) == 50 and len({row["path"] for row in rows}) == 50, "model-parity v4 acceptance file coverage is not exact 50")
    return rows


def _accepted_assessment_document(
    *, material: Mapping[str, Any], transaction: Mapping[str, Any], assessed: Mapping[str, Any], refresh: Mapping[str, Any],
) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": RECEIPT_STATUS,
        "accepted_manifest": material["accepted_manifest"],
        "accepted_manifest_content_identity_sha256": material["accepted_manifest_content_identity_sha256"],
        "canonical_assessment_identity_sha256": assessed["canonical_assessment_identity_sha256"],
        "publication_ready": True,
        "blockers": [],
        "evidence_count": 32,
        "evidence_sha256": material["evidence_sha256"],
        "transaction_index": transaction,
        "runtime_registries_sha256": material["runtime_registries_sha256"],
        "runtime_images_sha256": assessed["runtime_images_sha256"],
        "refresh_authority_sha256": _sha(refresh),
    }
    value["assessment_sha256"] = _sha(value)
    return value


def _receipt_document(
    *, material: Mapping[str, Any], transaction: Mapping[str, Any], assessed: Mapping[str, Any], refresh: Mapping[str, Any], assessment_record: Mapping[str, Any], binding_relative: str,
) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": RECEIPT_STATUS,
        "acceptance_binding_path": binding_relative,
        "accepted_manifest": material["accepted_manifest"],
        "accepted_manifest_content_identity_sha256": material["accepted_manifest_content_identity_sha256"],
        "accepted_assessment": dict(assessment_record),
        "accepted_assessment_identity_sha256": assessed["accepted_assessment_identity_sha256"],
        "canonical_assessment_identity_sha256": assessed["canonical_assessment_identity_sha256"],
        "publication_ready": True,
        "blockers": [],
        "evidence": material["evidence"],
        "evidence_count": 32,
        "evidence_sha256": material["evidence_sha256"],
        "transaction_index": transaction,
        "toolchain_registry": material["toolchain_registry"],
        "worker_runtime_registry": material["worker_runtime_registry"],
        "runtime_registries_sha256": material["runtime_registries_sha256"],
        "runtime_images": assessed["runtime_images"],
        "runtime_images_sha256": assessed["runtime_images_sha256"],
        "refresh_authority": refresh,
        "refresh_authority_sha256": _sha(refresh),
    }
    value["receipt_sha256"] = _sha(value)
    return value


def _binding_document(
    *, receipt_record: Mapping[str, Any], material: Mapping[str, Any], assessment_record: Mapping[str, Any], receipt: Mapping[str, Any], transaction: Mapping[str, Any], refresh: Mapping[str, Any], files: list[dict[str, Any]],
) -> dict[str, Any]:
    value = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "receipt": dict(receipt_record),
        "accepted_manifest": material["accepted_manifest"],
        "accepted_assessment": dict(assessment_record),
        "acceptance_identity_sha256": receipt["receipt_sha256"],
        "accepted_manifest_content_identity_sha256": material["accepted_manifest_content_identity_sha256"],
        "canonical_assessment_identity_sha256": receipt["canonical_assessment_identity_sha256"],
        "evidence_count": 32,
        "evidence_sha256": material["evidence_sha256"],
        "runtime_registries_sha256": material["runtime_registries_sha256"],
        "runtime_images_sha256": receipt["runtime_images_sha256"],
        "transaction_index": transaction,
        "refresh_authority": refresh,
        "files": files,
        "files_sha256": _sha(files),
    }
    value["binding_sha256"] = _sha(value)
    return value


def promote_model_parity_acceptance_v4(
    *,
    project_root: Path | str,
    accepted_manifest_path: Path | str,
    accepted_assessment_path: Path | str,
    acceptance_receipt_path: Path | str,
    acceptance_binding_path: Path | str,
    binding_set_authority: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        root = parity_v4._physical_root(project_root)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error
    manifest_descriptor = parity_v4.file_descriptor(root, accepted_manifest_path, "accepted model-parity v4 manifest")
    manifest_path = root.joinpath(*PurePosixPath(manifest_descriptor["path"]).parts)
    manifest = parity_v4.load_parity_manifest_v4(manifest_path, project_root=root)
    assessment_path = _output_path(root, accepted_assessment_path, "accepted model-parity v4 assessment")
    receipt_path = _output_path(root, acceptance_receipt_path, "model-parity v4 acceptance receipt")
    binding_path = _output_path(root, acceptance_binding_path, "model-parity v4 acceptance binding")
    _require(len({assessment_path, receipt_path, binding_path}) == 3, "model-parity v4 acceptance output paths collide")
    registry = acceptance_v3._FileRegistry(root)
    manifest_record = registry.add_descriptor(manifest_descriptor, "accepted model-parity v4 manifest")
    material = _manifest_material(root, manifest_record, manifest, registry=registry)
    try:
        transaction = acceptance_v3._transaction_index_material(root, material, registry=registry)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(f"model-parity v4 transaction rejected: {error}") from error
    transaction = validate_transaction_binding_v4(transaction)
    refresh = _physical_refresh_authority(root=root, manifest=manifest, binding_set_authority=binding_set_authority, registry=registry)
    assessment = parity_v4.assess_model_parity_v4(manifest_path, project_root=root)
    assessed = _assessment_binding(assessment, material["accepted_manifest_content_identity_sha256"])
    accepted_assessment = _accepted_assessment_document(material=material, transaction=transaction, assessed=assessed, refresh=refresh)
    assessed = {**assessed, "accepted_assessment_identity_sha256": accepted_assessment["assessment_sha256"]}
    assessment_record = _write_json(root, assessment_path, accepted_assessment, "accepted model-parity v4 assessment")
    registry.add_descriptor(assessment_record, "accepted model-parity v4 assessment")
    binding_relative = binding_path.relative_to(root).as_posix()
    receipt = _receipt_document(material=material, transaction=transaction, assessed=assessed, refresh=refresh, assessment_record=assessment_record, binding_relative=binding_relative)
    receipt_record = _write_json(root, receipt_path, receipt, "model-parity v4 acceptance receipt")
    registry.add_descriptor(receipt_record, "model-parity v4 acceptance receipt")
    files = _files(registry)
    binding = _binding_document(receipt_record=receipt_record, material=material, assessment_record=assessment_record, receipt=receipt, transaction=transaction, refresh=refresh, files=files)
    _write_json(root, binding_path, binding, "model-parity v4 acceptance binding")
    return load_verified_model_parity_acceptance_v4(project_root=root, receipt_path=receipt_path)


def load_verified_model_parity_acceptance_v4(
    *,
    project_root: Path | str,
    receipt_path: Path | str,
) -> dict[str, Any]:
    try:
        root = parity_v4._physical_root(project_root)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(str(error)) from error
    receipt_record = parity_v4.file_descriptor(root, receipt_path, "model-parity v4 acceptance receipt")
    receipt_file = root.joinpath(*PurePosixPath(receipt_record["path"]).parts)
    receipt = _read_json(receipt_file, "model-parity v4 acceptance receipt")
    _require(
        receipt.get("schema_version") == SCHEMA_VERSION
        and receipt.get("artifact_kind") == RECEIPT_KIND
        and receipt.get("status") == RECEIPT_STATUS
        and receipt.get("publication_ready") is True
        and receipt.get("blockers") == [],
        "model-parity v4 acceptance receipt is not accepted",
    )
    receipt_identity = _self_hash(receipt, "receipt_sha256", "model-parity v4 acceptance receipt")
    binding_relative = parity_v4._relative(receipt.get("acceptance_binding_path"), "model-parity v4 acceptance binding")
    binding_record = parity_v4.file_descriptor(root, binding_relative, "model-parity v4 acceptance binding")
    binding = _read_json(root.joinpath(*PurePosixPath(binding_relative).parts), "model-parity v4 acceptance binding")
    _require(binding.get("schema_version") == SCHEMA_VERSION and binding.get("artifact_kind") == BINDING_KIND, "model-parity v4 acceptance binding schema/kind drifted")
    _self_hash(binding, "binding_sha256", "model-parity v4 acceptance binding")
    _require(binding.get("receipt") == receipt_record and binding.get("acceptance_identity_sha256") == receipt_identity, "model-parity v4 receipt/binding cross-link drifted")

    manifest_record = _descriptor(binding.get("accepted_manifest"), "accepted model-parity v4 manifest")
    manifest_path = parity_v4.verify_descriptor(root, manifest_record, "accepted model-parity v4 manifest")
    manifest = parity_v4.load_parity_manifest_v4(manifest_path, project_root=root)
    registry = acceptance_v3._FileRegistry(root)
    manifest_record = registry.add_descriptor(manifest_record, "accepted model-parity v4 manifest")
    material = _manifest_material(root, manifest_record, manifest, registry=registry)
    try:
        transaction = acceptance_v3._transaction_index_material(root, material, registry=registry)
    except Exception as error:
        raise ModelParityAcceptanceV4Error(f"model-parity v4 transaction rejected: {error}") from error
    transaction = validate_transaction_binding_v4(transaction, expected=binding.get("transaction_index"))
    refresh = _physical_refresh_authority(root=root, manifest=manifest, binding_set_authority=binding.get("refresh_authority", {}).get("binding_set", {}), registry=registry)
    _require(refresh == binding.get("refresh_authority") == receipt.get("refresh_authority"), "model-parity v4 refresh authority drifted")
    assessment_record = registry.add_descriptor(binding.get("accepted_assessment"), "accepted model-parity v4 assessment")
    assessment_document = _read_json(root.joinpath(*PurePosixPath(assessment_record["path"]).parts), "accepted model-parity v4 assessment")
    assessment_identity = _self_hash(assessment_document, "assessment_sha256", "accepted model-parity v4 assessment")
    current_assessment = parity_v4.assess_model_parity_v4(manifest_path, project_root=root)
    assessed = _assessment_binding(current_assessment, material["accepted_manifest_content_identity_sha256"])
    expected_assessment = _accepted_assessment_document(material=material, transaction=transaction, assessed=assessed, refresh=refresh)
    _require(assessment_document == expected_assessment, "accepted model-parity v4 assessment drifted")
    assessed = {**assessed, "accepted_assessment_identity_sha256": assessment_identity}
    registry.add_descriptor(receipt_record, "model-parity v4 acceptance receipt")
    expected_receipt = _receipt_document(material=material, transaction=transaction, assessed=assessed, refresh=refresh, assessment_record=assessment_record, binding_relative=binding_relative)
    _require(receipt == expected_receipt, "model-parity v4 acceptance receipt drifted")
    files = _files(registry)
    expected_binding = _binding_document(receipt_record=receipt_record, material=material, assessment_record=assessment_record, receipt=receipt, transaction=transaction, refresh=refresh, files=files)
    _require(binding == expected_binding, "model-parity v4 acceptance binding drifted")
    _require(binding.get("files") == files and binding.get("files_sha256") == _sha(files), "model-parity v4 acceptance file set drifted")
    # Binding itself is the commit marker and is deliberately excluded from the
    # self-bound 50-file input set to avoid a recursive file-hash fixed point.
    _require(parity_v4.file_descriptor(root, binding_relative, "post-load model-parity v4 binding") == binding_record, "model-parity v4 binding drifted while loading")
    return _copy(binding)


__all__ = [
    "ASSESSMENT_KIND", "BINDING_KIND", "ModelParityAcceptanceV4Error",
    "RECEIPT_KIND", "RECEIPT_STATUS", "SCHEMA_VERSION",
    "load_verified_model_parity_acceptance_v4",
    "promote_model_parity_acceptance_v4", "validate_refresh_authority_v4",
    "validate_transaction_binding_v4",
]
