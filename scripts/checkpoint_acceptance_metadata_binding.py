#!/usr/bin/env python3
"""One-way cryptographic binding from final arm acceptance to durable metadata."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from backend_runtime_grant import (
    BackendRuntimeGrantError,
    validate_pre_run_backend_runtime_grant,
)
from backend_publication_output_receipt import (
    BackendPublicationOutputReceiptError,
    validate_backend_publication_artifacts,
    validate_backend_publication_arm_contract_authority,
    validate_backend_publication_output_receipt_authority,
)
from model_parity_grant import (
    ModelParityGrantError,
    validate_pre_run_model_parity_grant,
)


ACCEPTANCE_SCHEMA_VERSION = 2
BINDING_SCHEMA_VERSION = 2
ACCEPTANCE_KIND = "checkpoint_publication_runtime_acceptance"
ACCEPTANCE_STATUS = "accepted_native_checkpoint_arm"
BINDING_KIND = "checkpoint_publication_acceptance_metadata_binding"
EXECUTION_BINDING_KIND = "vast_full_publication_arm_execution_binding"
FULL_RESOURCE_PUBLICATION_SCOPE = (
    "primary_architecture_full_resource_raw_evidence_v2"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_EXECUTION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "run_identity_sha256",
        "sequence",
        "pair_id",
        "attempt",
        "arm_id",
    }
)
_RESOURCE_GRANT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "publication_scope",
        "identity_artifact_binding_sha256",
        "qualification_receipt",
        "capability_manifest",
        "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated",
        "grant_sha256",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "run_metadata_file",
        "run_metadata_size_bytes",
        "run_metadata_sha256",
        "publication_run_contract_identity",
        "publication_evidence_bundle_identity",
        "identity_artifact_binding_sha256",
        "resource_capability_grant_sha256",
        "backend_runtime_grant_sha256",
        "model_parity_grant_sha256",
        "model_parity_acceptance_binding_sha256",
        "backend_publication_arm_contract_authority",
        "backend_publication_output_receipt_authority",
        "execution_binding",
        "binding_sha256",
    }
)


class AcceptanceMetadataBindingError(RuntimeError):
    """Acceptance and its durable run metadata are not the same arm commit."""


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
        raise AcceptanceMetadataBindingError(
            "acceptance metadata binding is not canonical JSON"
        ) from error


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _read_metadata(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.name != "run_metadata.json":
        raise AcceptanceMetadataBindingError(
            "durable metadata filename must be run_metadata.json"
        )
    if path.is_symlink() or not path.is_file():
        raise AcceptanceMetadataBindingError(
            "durable run_metadata is missing or not a regular file"
        )
    before = path.stat()
    try:
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcceptanceMetadataBindingError(
            f"durable run_metadata is invalid: {error}"
        ) from error
    after = path.stat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise AcceptanceMetadataBindingError(
            "durable run_metadata changed while reading"
        )
    if type(value) is not dict:
        raise AcceptanceMetadataBindingError(
            "durable run_metadata must be a JSON object"
        )
    return value, payload


def _identity(value: Any, label: str) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "sha256"}
        or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or not _valid_sha(value.get("sha256"))
    ):
        raise AcceptanceMetadataBindingError(f"{label} is invalid")
    return copy.deepcopy(value)


def _execution(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _EXECUTION_FIELDS:
        raise AcceptanceMetadataBindingError(
            "full publication execution binding fields drifted"
        )
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind") != EXECUTION_BINDING_KIND
        or not _valid_sha(value.get("run_identity_sha256"))
        or type(value.get("sequence")) is not int
        or value["sequence"] < 0
        or type(value.get("attempt")) is not int
        or value["attempt"] < 1
        or type(value.get("pair_id")) is not str
        or not value["pair_id"]
        or type(value.get("arm_id")) is not str
        or not value["arm_id"]
    ):
        raise AcceptanceMetadataBindingError(
            "full publication execution binding is invalid"
        )
    return copy.deepcopy(value)


def validate_full_publication_execution_binding(value: Any) -> dict[str, Any]:
    """Validate and detach one immutable pair/attempt/arm execution identity."""

    return _execution(value)


def _resource_grant(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _RESOURCE_GRANT_FIELDS:
        raise AcceptanceMetadataBindingError(
            "resource capability grant fields drifted"
        )
    unsigned = {key: item for key, item in value.items() if key != "grant_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind")
        != "vast_verified_pre_run_resource_capability_grant"
        or value.get("status")
        != "accepted_pre_run_resource_capability_qualification"
        or value.get("publication_scope") != FULL_RESOURCE_PUBLICATION_SCOPE
        or not _valid_sha(value.get("identity_artifact_binding_sha256"))
        or not _valid_sha(value.get("grant_sha256"))
        or value["grant_sha256"] != _sha(unsigned)
        or value.get("post_run_per_arm_evidence_required") is not True
        or value.get("configuration_evidence_accepted_mutated") is not False
    ):
        raise AcceptanceMetadataBindingError(
            "resource capability grant is invalid"
        )
    return copy.deepcopy(value)


def _metadata_authorities(
    metadata: Mapping[str, Any],
    *,
    run_metadata_path: Path,
    expected_execution_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if metadata.get("schema_version") != 2 or metadata.get("mode") != "benchmark":
        raise AcceptanceMetadataBindingError(
            "durable run_metadata is not a benchmark metadata v2 artifact"
        )
    result = metadata.get("result")
    if type(result) is not dict or result.get("status") != "completed":
        raise AcceptanceMetadataBindingError(
            "durable run_metadata result is not completed"
        )
    contract = metadata.get("publication_run_contract")
    if type(contract) is not dict:
        raise AcceptanceMetadataBindingError(
            "publication run contract is missing"
        )
    contract_identity = _identity(
        metadata.get("publication_run_contract_identity"),
        "publication run contract identity",
    )
    if contract_identity["sha256"] != _sha(contract):
        raise AcceptanceMetadataBindingError(
            "publication run contract identity SHA-256 drifted"
        )
    evidence = metadata.get("publication_evidence_bundle")
    if type(evidence) is not dict:
        raise AcceptanceMetadataBindingError(
            "publication evidence bundle is missing"
        )
    evidence_identity = _identity(
        metadata.get("publication_evidence_bundle_identity"),
        "publication evidence bundle identity",
    )
    if evidence_identity["sha256"] != _sha(evidence):
        raise AcceptanceMetadataBindingError(
            "publication evidence bundle identity SHA-256 drifted"
        )
    resource = _resource_grant(
        contract.get("pre_run_resource_capability_grant")
    )
    backend_raw = contract.get("pre_run_backend_runtime_grant")
    if backend_raw is None:
        raise AcceptanceMetadataBindingError(
            "backend runtime grant is missing"
        )
    try:
        backend = validate_pre_run_backend_runtime_grant(backend_raw)
    except BackendRuntimeGrantError as error:
        raise AcceptanceMetadataBindingError(
            f"backend runtime grant is invalid: {error}"
        ) from error
    parity_raw = contract.get("pre_run_model_parity_grant")
    if parity_raw is None:
        raise AcceptanceMetadataBindingError("model-parity grant is missing")
    try:
        parity = validate_pre_run_model_parity_grant(parity_raw)
    except ModelParityGrantError as error:
        raise AcceptanceMetadataBindingError(
            f"model-parity grant is invalid: {error}"
        ) from error
    expected = _execution(dict(expected_execution_binding))
    actual = _execution(contract.get("full_publication_execution_binding"))
    if actual != expected:
        raise AcceptanceMetadataBindingError(
            "full publication execution binding drifted"
        )
    arm_authority_raw = contract.get(
        "backend_publication_arm_contract_authority"
    )
    receipt_authority_raw = contract.get(
        "backend_publication_output_receipt_authority"
    )
    try:
        arm_authority = validate_backend_publication_arm_contract_authority(
            arm_authority_raw
        )
        receipt_authority = (
            validate_backend_publication_output_receipt_authority(
                receipt_authority_raw
            )
        )
        physical = validate_backend_publication_artifacts(
            output_dir=run_metadata_path.parent,
            expected_arm_contract_authority=arm_authority,
            expected_output_receipt_authority=receipt_authority,
        )
    except BackendPublicationOutputReceiptError as error:
        raise AcceptanceMetadataBindingError(
            f"backend publication contract/receipt authority is invalid: {error}"
        ) from error
    arm_authority = physical["arm_contract_authority"]
    receipt_authority = physical["output_receipt_authority"]
    resource_identity = resource["identity_artifact_binding_sha256"]
    backend_identity = backend["identity_artifact_binding_sha256"]
    parity_identity = parity["identity_artifact_binding_sha256"]
    if len({resource_identity, backend_identity, parity_identity}) != 1:
        raise AcceptanceMetadataBindingError(
            "identity artifact binding differs between resource, backend, and model-parity grants"
        )
    if (
        backend["upstream_identities"][
            "model_parity_acceptance_binding_sha256"
        ]
        != parity["parity_acceptance_binding_sha256"]
    ):
        raise AcceptanceMetadataBindingError(
            "backend and model-parity grants bind different parity acceptances"
        )
    if (
        Path(arm_authority["output_dir"]).resolve(strict=True)
        != run_metadata_path.parent.resolve(strict=True)
        or arm_authority["full_publication_execution_binding"] != actual
        or arm_authority["backend_runtime_grant_sha256"]
        != backend["grant_sha256"]
        or arm_authority["resource_capability_grant_sha256"]
        != resource["grant_sha256"]
        or arm_authority["model_parity_grant_sha256"]
        != parity["grant_sha256"]
        or arm_authority[
            "model_parity_acceptance_binding_sha256"
        ]
        != parity["parity_acceptance_binding_sha256"]
        or arm_authority["identity_artifact_binding_sha256"]
        != parity_identity
    ):
        raise AcceptanceMetadataBindingError(
            "backend publication contract/receipt authority differs from arm metadata"
        )
    return {
        "publication_run_contract_identity": contract_identity,
        "publication_evidence_bundle_identity": evidence_identity,
        "identity_artifact_binding_sha256": resource_identity,
        "resource_capability_grant_sha256": resource["grant_sha256"],
        "backend_runtime_grant_sha256": backend["grant_sha256"],
        "model_parity_grant_sha256": parity["grant_sha256"],
        "model_parity_acceptance_binding_sha256": parity[
            "parity_acceptance_binding_sha256"
        ],
        "backend_publication_arm_contract_authority": arm_authority,
        "backend_publication_output_receipt_authority": receipt_authority,
        "execution_binding": actual,
    }


def bind_checkpoint_acceptance_to_durable_metadata(
    acceptance: Mapping[str, Any],
    *,
    run_metadata_path: Path,
    expected_execution_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a v2 acceptance bound to exact already-durable metadata bytes."""

    if (
        type(acceptance) is not dict
        or acceptance.get("schema_version") != ACCEPTANCE_SCHEMA_VERSION
        or acceptance.get("artifact_kind") != ACCEPTANCE_KIND
        or acceptance.get("status") != ACCEPTANCE_STATUS
        or "publication_metadata_binding" in acceptance
    ):
        raise AcceptanceMetadataBindingError(
            "prepared checkpoint acceptance schema/status is invalid"
        )
    metadata, payload = _read_metadata(run_metadata_path)
    authorities = _metadata_authorities(
        metadata,
        run_metadata_path=run_metadata_path,
        expected_execution_binding=expected_execution_binding,
    )
    binding = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "run_metadata_file": "run_metadata.json",
        "run_metadata_size_bytes": len(payload),
        "run_metadata_sha256": hashlib.sha256(payload).hexdigest(),
        **authorities,
    }
    binding["binding_sha256"] = _sha(binding)
    result = copy.deepcopy(dict(acceptance))
    result["publication_metadata_binding"] = binding
    return result


def validate_checkpoint_acceptance_metadata_binding(
    acceptance: Mapping[str, Any],
    *,
    run_metadata_path: Path,
    expected_execution_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Re-read metadata and reject absent, swapped, or tampered arm authority."""

    binding = validate_checkpoint_acceptance_metadata_binding_envelope(acceptance)
    metadata, payload = _read_metadata(run_metadata_path)
    if (
        len(payload) != binding["run_metadata_size_bytes"]
        or hashlib.sha256(payload).hexdigest()
        != binding["run_metadata_sha256"]
    ):
        raise AcceptanceMetadataBindingError(
            "durable run_metadata SHA-256/size differs from final acceptance"
        )
    authorities = _metadata_authorities(
        metadata,
        run_metadata_path=run_metadata_path,
        expected_execution_binding=expected_execution_binding,
    )
    for field, value in authorities.items():
        if binding.get(field) != value:
            raise AcceptanceMetadataBindingError(
                f"checkpoint acceptance {field} differs from durable metadata"
            )
    return copy.deepcopy(authorities)


def validate_checkpoint_acceptance_metadata_binding_envelope(
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the signed v2 binding envelope when metadata is not in scope."""

    if (
        type(acceptance) is not dict
        or acceptance.get("schema_version") != ACCEPTANCE_SCHEMA_VERSION
        or acceptance.get("artifact_kind") != ACCEPTANCE_KIND
        or acceptance.get("status") != ACCEPTANCE_STATUS
    ):
        raise AcceptanceMetadataBindingError(
            "checkpoint acceptance schema v2/status is required"
        )
    binding = acceptance.get("publication_metadata_binding")
    if type(binding) is not dict or set(binding) != _BINDING_FIELDS:
        raise AcceptanceMetadataBindingError(
            "checkpoint acceptance metadata binding fields drifted"
        )
    unsigned = {key: item for key, item in binding.items() if key != "binding_sha256"}
    if (
        binding.get("schema_version") != BINDING_SCHEMA_VERSION
        or binding.get("artifact_kind") != BINDING_KIND
        or binding.get("run_metadata_file") != "run_metadata.json"
        or type(binding.get("run_metadata_size_bytes")) is not int
        or binding["run_metadata_size_bytes"] <= 0
        or not _valid_sha(binding.get("run_metadata_sha256"))
        or not _valid_sha(binding.get("binding_sha256"))
        or binding["binding_sha256"] != _sha(unsigned)
    ):
        raise AcceptanceMetadataBindingError(
            "checkpoint acceptance metadata binding self-hash is invalid"
        )
    _identity(
        binding.get("publication_run_contract_identity"),
        "publication run contract identity",
    )
    _identity(
        binding.get("publication_evidence_bundle_identity"),
        "publication evidence bundle identity",
    )
    if any(
        not _valid_sha(binding.get(field))
        for field in (
            "identity_artifact_binding_sha256",
            "resource_capability_grant_sha256",
            "backend_runtime_grant_sha256",
            "model_parity_grant_sha256",
            "model_parity_acceptance_binding_sha256",
        )
    ):
        raise AcceptanceMetadataBindingError(
            "checkpoint acceptance authority SHA-256 fields are invalid"
        )
    _execution(binding.get("execution_binding"))
    try:
        arm_authority = validate_backend_publication_arm_contract_authority(
            binding.get("backend_publication_arm_contract_authority")
        )
        receipt_authority = (
            validate_backend_publication_output_receipt_authority(
                binding.get("backend_publication_output_receipt_authority")
            )
        )
    except BackendPublicationOutputReceiptError as error:
        raise AcceptanceMetadataBindingError(
            f"checkpoint acceptance backend receipt authority is invalid: {error}"
        ) from error
    authority_crossbind_fields = (
        "full_publication_execution_binding",
        "run_identity_sha256",
        "run_id",
        "output_dir",
        "dispatch_resolution_sha256",
        "cell_identity_sha256",
        "launcher_sha256",
        "launcher_invocation_sha256",
        "backend_runtime_grant_sha256",
        "resource_capability_grant_sha256",
        "model_parity_grant_sha256",
        "model_parity_acceptance_binding_sha256",
        "identity_artifact_binding_sha256",
    )
    if (
        any(
            arm_authority[field] != receipt_authority[field]
            for field in authority_crossbind_fields
        )
        or receipt_authority["arm_contract"] != {
            key: arm_authority[key] for key in ("path", "size_bytes", "sha256")
        }
        or binding["execution_binding"]
        != arm_authority["full_publication_execution_binding"]
        or binding["resource_capability_grant_sha256"]
        != arm_authority["resource_capability_grant_sha256"]
        or binding["backend_runtime_grant_sha256"]
        != arm_authority["backend_runtime_grant_sha256"]
        or binding["model_parity_grant_sha256"]
        != arm_authority["model_parity_grant_sha256"]
        or binding["model_parity_acceptance_binding_sha256"]
        != arm_authority["model_parity_acceptance_binding_sha256"]
        or binding["identity_artifact_binding_sha256"]
        != arm_authority["identity_artifact_binding_sha256"]
    ):
        raise AcceptanceMetadataBindingError(
            "checkpoint acceptance backend authorities are not crossbound"
        )
    return copy.deepcopy(binding)


__all__ = [
    "ACCEPTANCE_SCHEMA_VERSION",
    "AcceptanceMetadataBindingError",
    "bind_checkpoint_acceptance_to_durable_metadata",
    "validate_checkpoint_acceptance_metadata_binding",
    "validate_checkpoint_acceptance_metadata_binding_envelope",
    "validate_full_publication_execution_binding",
]
