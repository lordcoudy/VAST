#!/usr/bin/env python3
"""Pure pre-run authorization derived from physically verified parity identity."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = 2
GRANT_KIND = "vast_verified_pre_run_model_parity_grant"
GRANT_STATUS = "accepted_physical_model_parity_v3"
IDENTITY_SCHEMA_VERSION = 2
PARITY_BINDING_KIND = "vast_verified_model_parity_acceptance_binding"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_TRANSACTION_FIELDS = _DESCRIPTOR_FIELDS | {
    "transaction_sha256", "files_sha256", "output_segments_sha256",
    "execution_bundle_count", "execution_bundles_sha256",
}
_GRANT_FIELDS = {
    "schema_version", "artifact_kind", "status",
    "identity_artifact_binding_sha256", "parity_acceptance_binding_sha256",
    "acceptance_receipt", "accepted_manifest", "accepted_assessment",
    "transaction_index",
    "acceptance_identity_sha256", "accepted_manifest_content_identity_sha256",
    "canonical_assessment_identity_sha256", "evidence_count", "evidence_sha256",
    "runtime_registries_sha256", "runtime_images_sha256",
    "authorization_material_sha256", "grant_sha256",
}
_PARITY_BINDING_FIELDS = {
    "schema_version", "artifact_kind", "receipt", "accepted_manifest",
    "accepted_assessment", "transaction_index", "acceptance_identity_sha256",
    "accepted_manifest_content_identity_sha256",
    "canonical_assessment_identity_sha256", "evidence_count", "evidence_sha256",
    "runtime_registries_sha256", "runtime_images_sha256", "files", "files_sha256",
    "binding_sha256",
}
_IDENTITY_FIELDS = {
    "schema_version", "artifact_kind", "manifest", "bindings", "files",
    "files_sha256", "binding_sha256",
}


class ModelParityGrantError(RuntimeError):
    """Parity authorization material is missing, legacy, or has drifted."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ModelParityGrantError("model-parity grant is not canonical JSON") from error


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        raise ModelParityGrantError(f"{label} descriptor fields drifted")
    path = value.get("path")
    if (
        type(path) is not str or not path or "\\" in path or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or type(value.get("size_bytes")) is not int or value["size_bytes"] <= 0
        or not _valid_sha(value.get("sha256"))
    ):
        raise ModelParityGrantError(f"{label} descriptor is invalid")
    return copy.deepcopy(value)


def _transaction_descriptor(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _TRANSACTION_FIELDS:
        raise ModelParityGrantError(f"{label} transaction descriptor fields drifted")
    result = _descriptor(
        {key: value[key] for key in _DESCRIPTOR_FIELDS},
        f"{label} transaction index",
    )
    if not result["path"].endswith("/transaction_index.json"):
        raise ModelParityGrantError(f"{label} transaction path is invalid")
    for field in (
        "transaction_sha256", "files_sha256", "output_segments_sha256",
        "execution_bundles_sha256",
    ):
        if not _valid_sha(value.get(field)):
            raise ModelParityGrantError(f"{label} transaction {field} is invalid")
        result[field] = value[field]
    if value.get("execution_bundle_count") != 480:
        raise ModelParityGrantError(
            f"{label} transaction execution bundle coverage is not exact 480"
        )
    result["execution_bundle_count"] = 480
    return result


def _normalized_grant(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _GRANT_FIELDS:
        raise ModelParityGrantError("model-parity grant fields drifted")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != GRANT_KIND
        or value.get("status") != GRANT_STATUS
    ):
        raise ModelParityGrantError("model-parity grant schema/kind/status drifted")
    for field in (
        "identity_artifact_binding_sha256", "parity_acceptance_binding_sha256",
        "acceptance_identity_sha256", "accepted_manifest_content_identity_sha256",
        "canonical_assessment_identity_sha256", "evidence_sha256",
        "runtime_registries_sha256", "runtime_images_sha256",
        "authorization_material_sha256",
    ):
        if not _valid_sha(value.get(field)):
            raise ModelParityGrantError(f"model-parity grant {field} is invalid")
    if value.get("evidence_count") != 32:
        raise ModelParityGrantError("model-parity grant evidence coverage is not exact 32")
    material = {
        key: copy.deepcopy(item)
        for key, item in value.items()
        if key != "grant_sha256"
    }
    for field in ("acceptance_receipt", "accepted_manifest", "accepted_assessment"):
        material[field] = _descriptor(value.get(field), f"model-parity {field}")
    material["transaction_index"] = _transaction_descriptor(
        value.get("transaction_index"), "model-parity grant"
    )
    authorization = {
        key: material[key]
        for key in (
            "identity_artifact_binding_sha256", "parity_acceptance_binding_sha256",
            "acceptance_receipt", "accepted_manifest", "accepted_assessment",
            "transaction_index",
            "acceptance_identity_sha256", "accepted_manifest_content_identity_sha256",
            "canonical_assessment_identity_sha256", "evidence_count", "evidence_sha256",
            "runtime_registries_sha256", "runtime_images_sha256",
        )
    }
    if material["authorization_material_sha256"] != _sha(authorization):
        raise ModelParityGrantError("model-parity authorization material cross-binding drifted")
    return material


def assess_pre_run_model_parity_grant(value: Any) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        material = _normalized_grant(value)
        if not _valid_sha(value.get("grant_sha256")) or value["grant_sha256"] != _sha(material):
            raise ModelParityGrantError("model-parity grant self-hash drifted")
    except ModelParityGrantError as error:
        blockers.append(str(error))
    except Exception as error:
        blockers.append(f"model-parity grant failed closed: {error}")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_pre_run_model_parity_grant_assessment",
        "passed": not blockers,
        "status": "accepted" if not blockers else "blocked",
        "blockers": blockers,
        "grant_sha256": value.get("grant_sha256") if type(value) is dict and not blockers else None,
    }


def validate_pre_run_model_parity_grant(value: Any) -> dict[str, Any]:
    assessment = assess_pre_run_model_parity_grant(value)
    if not assessment["passed"]:
        raise ModelParityGrantError(
            "pre-run model-parity grant is invalid: " + ", ".join(assessment["blockers"])
        )
    return copy.deepcopy(value)


def model_parity_grant_from_identity_artifacts(identity: dict[str, Any]) -> dict[str, Any]:
    """Derive the grant only from a canonical schema-2 publication identity."""

    if type(identity) is not dict or set(identity) != _IDENTITY_FIELDS:
        raise ModelParityGrantError("validated full publication identity fields drifted")
    if (
        identity.get("schema_version") != IDENTITY_SCHEMA_VERSION
        or identity.get("artifact_kind") != "vast_full_publication_identity_artifact_binding"
        or not _valid_sha(identity.get("binding_sha256"))
        or identity["binding_sha256"]
        != _sha({key: item for key, item in identity.items() if key != "binding_sha256"})
    ):
        raise ModelParityGrantError("schema-2 validated full publication identity is required")
    files = identity.get("files")
    if type(files) is not list or not files:
        raise ModelParityGrantError("validated identity file set is empty")
    normalized_files = [_descriptor(item, f"identity file[{index}]") for index, item in enumerate(files)]
    if (
        len({item["path"] for item in normalized_files}) != len(normalized_files)
        or identity.get("files_sha256") != _sha(normalized_files)
    ):
        raise ModelParityGrantError("validated identity file set drifted")
    known = {item["path"]: item for item in normalized_files}
    bindings = identity.get("bindings")
    parity = bindings.get("analytics_model_parity") if type(bindings) is dict else None
    if (
        type(parity) is not dict or set(parity) != _PARITY_BINDING_FIELDS
        or parity.get("schema_version") != SCHEMA_VERSION
        or parity.get("artifact_kind") != PARITY_BINDING_KIND
        or not _valid_sha(parity.get("binding_sha256"))
        or parity["binding_sha256"]
        != _sha({key: item for key, item in parity.items() if key != "binding_sha256"})
    ):
        raise ModelParityGrantError("validated physical model-parity acceptance binding is required")
    if parity.get("evidence_count") != 32:
        raise ModelParityGrantError("validated model-parity evidence coverage is not exact 32")
    parity_files = parity.get("files")
    if type(parity_files) is not list or len(parity_files) != 36:
        raise ModelParityGrantError("validated model-parity file coverage is not exact 36")
    normalized_parity_files = [
        _descriptor(item, f"parity file[{index}]")
        for index, item in enumerate(parity_files)
    ]
    if (
        normalized_parity_files
        != sorted(normalized_parity_files, key=lambda item: item["path"])
        or len({item["path"] for item in normalized_parity_files}) != 36
        or parity.get("files_sha256") != _sha(normalized_parity_files)
        or any(known.get(item["path"]) != item for item in normalized_parity_files)
    ):
        raise ModelParityGrantError("validated model-parity file set is unbound")
    descriptors = {
        "acceptance_receipt": _descriptor(parity.get("receipt"), "parity receipt"),
        "accepted_manifest": _descriptor(parity.get("accepted_manifest"), "accepted parity manifest"),
        "accepted_assessment": _descriptor(parity.get("accepted_assessment"), "accepted parity assessment"),
    }
    for label, descriptor in descriptors.items():
        if known.get(descriptor["path"]) != descriptor:
            raise ModelParityGrantError(f"{label} descriptor is unbound")
    transaction = _transaction_descriptor(
        parity.get("transaction_index"), "parity acceptance"
    )
    transaction_file = {
        key: transaction[key] for key in _DESCRIPTOR_FIELDS
    }
    if known.get(transaction["path"]) != transaction_file:
        raise ModelParityGrantError("parity acceptance transaction descriptor is unbound")
    for field in (
        "acceptance_identity_sha256", "accepted_manifest_content_identity_sha256",
        "canonical_assessment_identity_sha256", "evidence_sha256",
        "runtime_registries_sha256", "runtime_images_sha256",
    ):
        if not _valid_sha(parity.get(field)):
            raise ModelParityGrantError(f"parity acceptance {field} is invalid")
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": GRANT_KIND,
        "status": GRANT_STATUS,
        "identity_artifact_binding_sha256": identity["binding_sha256"],
        "parity_acceptance_binding_sha256": parity["binding_sha256"],
        **descriptors,
        "transaction_index": transaction,
        "acceptance_identity_sha256": parity["acceptance_identity_sha256"],
        "accepted_manifest_content_identity_sha256": parity["accepted_manifest_content_identity_sha256"],
        "canonical_assessment_identity_sha256": parity["canonical_assessment_identity_sha256"],
        "evidence_count": 32,
        "evidence_sha256": parity["evidence_sha256"],
        "runtime_registries_sha256": parity["runtime_registries_sha256"],
        "runtime_images_sha256": parity["runtime_images_sha256"],
    }
    material["authorization_material_sha256"] = _sha(
        {
            key: material[key]
            for key in (
                "identity_artifact_binding_sha256", "parity_acceptance_binding_sha256",
                "acceptance_receipt", "accepted_manifest", "accepted_assessment",
                "transaction_index",
                "acceptance_identity_sha256", "accepted_manifest_content_identity_sha256",
                "canonical_assessment_identity_sha256", "evidence_count", "evidence_sha256",
                "runtime_registries_sha256", "runtime_images_sha256",
            )
        }
    )
    material["grant_sha256"] = _sha(material)
    return validate_pre_run_model_parity_grant(material)


__all__ = [
    "GRANT_KIND", "GRANT_STATUS", "ModelParityGrantError", "SCHEMA_VERSION",
    "assess_pre_run_model_parity_grant", "model_parity_grant_from_identity_artifacts",
    "validate_pre_run_model_parity_grant",
]
