#!/usr/bin/env python3
"""Externally pinned, non-authorizing validator authority for qualification Q4."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import backend_runtime_validator_authority as physical_reader


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_runtime_validator_authority_q4"
ASSESSMENT_KIND = "vast_backend_runtime_validator_authority_q4_assessment"
SUPPORTED_QUALIFICATION_SCHEMA_VERSION = 4
MAX_IMPLEMENTATION_BYTES = 64 * 1024 * 1024
IDENTITY_FIELDS = frozenset({
    "qualification_input_schema_identity_sha256",
    "validation_system_context_schema_identity_sha256",
    "validation_request_schema_identity_sha256",
    "validation_record_schema_identity_sha256",
    "validation_system_shard_schema_identity_sha256",
    "validation_record_set_index_schema_identity_sha256",
    "validation_protocol_identity_sha256",
    "validation_input_schema_identity_sha256",
    "validation_output_schema_identity_sha256",
})
TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "validator_id", "implementation",
    "supported_qualification_schema_version", *IDENTITY_FIELDS,
    "deterministic", "execution_authorized",
    "validation_records_authenticated", "authority_sha256",
})
IMPLEMENTATION_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_PHYSICAL_ASSESSMENT_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "authority_sha256",
    "validator_id", "checked_artifact_count", "blockers",
    "execution_authorized", "validation_records_authenticated",
})
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


class BackendRuntimeValidatorAuthorityV4Error(ValueError):
    """The Q4 validator authority or its physical assessment is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeValidatorAuthorityV4Error(message)


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _canonical_sha(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeValidatorAuthorityV4Error(
            "Q4 validator authority is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _relative_path(value: Any) -> str:
    _require(type(value) is str and bool(value),
             "Q4 validator implementation path is invalid")
    _require(
        not value.startswith(("/", "\\"))
        and not value.endswith("/")
        and "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and "//" not in value,
        "Q4 validator implementation path is not a strict relative POSIX path",
    )
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") for part in parts),
             "Q4 validator implementation path traverses outside the project")
    for part in parts:
        _require(not part.endswith((".", " ")),
                 "Q4 validator path has a Windows-ambiguous segment")
        _require(part.split(".", 1)[0].upper() not in _RESERVED,
                 "Q4 validator path uses a reserved Windows name")
    return value


def _descriptor(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == DESCRIPTOR_FIELDS,
             "Q4 validator implementation descriptor fields drifted")
    path = _relative_path(value.get("path"))
    size = value.get("size_bytes")
    _require(type(size) is int and 0 <= size <= MAX_IMPLEMENTATION_BYTES,
             "Q4 validator implementation size is invalid")
    digest = value.get("sha256")
    _require(_valid_sha(digest),
             "Q4 validator implementation sha256 is invalid")
    return {"path": path, "size_bytes": size, "sha256": digest}


def validate_backend_runtime_validator_authority_v4(
    value: Any, *, expected_authority_sha256: str,
) -> dict[str, Any]:
    """Validate a closed Q4 authority against a mandatory external pin."""
    _require(_valid_sha(expected_authority_sha256),
             "expected Q4 validator authority pin is invalid")
    _require(type(value) is dict and set(value) == TOP_FIELDS,
             "Q4 validator authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION,
             "Q4 validator authority schema version drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "Q4 validator authority artifact kind drifted")
    validator_id = value.get("validator_id")
    _require(type(validator_id) is str
             and _ID_RE.fullmatch(validator_id) is not None,
             "Q4 validator_id is invalid")
    implementation = value.get("implementation")
    _require(type(implementation) is dict
             and set(implementation) == IMPLEMENTATION_FIELDS,
             "Q4 validator implementation fields drifted")
    checked_descriptor = _descriptor(implementation.get("descriptor"))
    _require(implementation.get("content_identity_sha256")
             == checked_descriptor["sha256"],
             "Q4 validator implementation content identity drifted")
    _require(type(value.get("supported_qualification_schema_version")) is int
             and value.get("supported_qualification_schema_version")
             == SUPPORTED_QUALIFICATION_SCHEMA_VERSION,
             "Q4 supported qualification schema version drifted")
    for field in IDENTITY_FIELDS:
        _require(_valid_sha(value.get(field)), f"{field} is invalid")
    _require(value.get("deterministic") is True,
             "Q4 validator implementation is not deterministic")
    _require(value.get("execution_authorized") is False,
             "Q4 validator authority made an execution claim")
    _require(value.get("validation_records_authenticated") is False,
             "Q4 validator authority made an authentication claim")
    authority_sha = value.get("authority_sha256")
    _require(_valid_sha(authority_sha),
             "Q4 validator authority sha256 is invalid")
    unsigned = {
        key: copy.deepcopy(item) for key, item in value.items()
        if key != "authority_sha256"
    }
    _require(authority_sha == _canonical_sha(unsigned),
             "Q4 validator authority self-hash drifted")
    _require(authority_sha == expected_authority_sha256,
             "Q4 validator authority does not match the trusted pin")
    return copy.deepcopy(value)


def build_backend_runtime_validator_authority_v4(
    *, validator_id: str, implementation_descriptor: dict[str, Any],
    qualification_input_schema_identity_sha256: str,
    validation_system_context_schema_identity_sha256: str,
    validation_request_schema_identity_sha256: str,
    validation_record_schema_identity_sha256: str,
    validation_system_shard_schema_identity_sha256: str,
    validation_record_set_index_schema_identity_sha256: str,
    validation_protocol_identity_sha256: str,
    validation_input_schema_identity_sha256: str,
    validation_output_schema_identity_sha256: str,
    expected_authority_sha256: str,
) -> dict[str, Any]:
    """Build a Q4 authority only when it matches an external authority pin."""
    _require(_valid_sha(expected_authority_sha256),
             "expected Q4 validator authority pin is invalid")
    _require(type(implementation_descriptor) is dict,
             "Q4 validator implementation descriptor type drifted")
    descriptor = _descriptor(implementation_descriptor)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "validator_id": validator_id,
        "implementation": {
            "descriptor": descriptor,
            "content_identity_sha256": descriptor["sha256"],
        },
        "supported_qualification_schema_version":
            SUPPORTED_QUALIFICATION_SCHEMA_VERSION,
        "qualification_input_schema_identity_sha256":
            qualification_input_schema_identity_sha256,
        "validation_system_context_schema_identity_sha256":
            validation_system_context_schema_identity_sha256,
        "validation_request_schema_identity_sha256":
            validation_request_schema_identity_sha256,
        "validation_record_schema_identity_sha256":
            validation_record_schema_identity_sha256,
        "validation_system_shard_schema_identity_sha256":
            validation_system_shard_schema_identity_sha256,
        "validation_record_set_index_schema_identity_sha256":
            validation_record_set_index_schema_identity_sha256,
        "validation_protocol_identity_sha256":
            validation_protocol_identity_sha256,
        "validation_input_schema_identity_sha256":
            validation_input_schema_identity_sha256,
        "validation_output_schema_identity_sha256":
            validation_output_schema_identity_sha256,
        "deterministic": True,
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }
    value["authority_sha256"] = _canonical_sha(value)
    return validate_backend_runtime_validator_authority_v4(
        value, expected_authority_sha256=expected_authority_sha256,
    )


def _physical_reader_projection(authority: Mapping[str, Any]) -> dict[str, Any]:
    material: dict[str, Any] = {
        "schema_version": physical_reader.SCHEMA_VERSION,
        "artifact_kind": physical_reader.ARTIFACT_KIND,
        "validator_id": authority["validator_id"],
        "implementation": copy.deepcopy(authority["implementation"]),
        "validation_protocol_identity_sha256":
            authority["validation_protocol_identity_sha256"],
        "input_schema_identity_sha256":
            authority["validation_input_schema_identity_sha256"],
        "output_schema_identity_sha256":
            authority["validation_output_schema_identity_sha256"],
        "supported_qualification_schema_version":
            physical_reader.SUPPORTED_QUALIFICATION_SCHEMA_VERSION,
        "deterministic": True,
    }
    material["authority_sha256"] = _canonical_sha(material)
    return material


def _validate_physical_assessment(
    value: Any, *, projection_sha256: str, validator_id: str,
) -> tuple[str, int, list[str]]:
    _require(type(value) is dict
             and set(value) == _PHYSICAL_ASSESSMENT_FIELDS,
             "physical reader assessment fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == physical_reader.SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == physical_reader.ASSESSMENT_KIND,
             "physical reader assessment header drifted")
    _require(value.get("authority_sha256") == projection_sha256
             and value.get("validator_id") == validator_id,
             "physical reader assessment projection binding drifted")
    _require(value.get("execution_authorized") is False
             and value.get("validation_records_authenticated") is False,
             "physical reader adapter made a trust claim")
    status = value.get("status")
    checked = value.get("checked_artifact_count")
    blockers = value.get("blockers")
    _require(type(status) is str
             and status in ("physically_valid", "blocked"),
             "physical reader assessment status is invalid")
    _require(type(checked) is int and checked in (0, 1),
             "physical reader checked count is invalid")
    _require(type(blockers) is list
             and all(type(item) is str and item for item in blockers)
             and blockers == sorted(dict.fromkeys(blockers)),
             "physical reader blockers are invalid")
    if status == "physically_valid":
        _require(checked == 1 and blockers == [],
                 "physical reader success evidence is incomplete")
    else:
        _require(checked == 0 and bool(blockers),
                 "physical reader failure evidence is incomplete")
    return status, checked, copy.deepcopy(blockers)


def assess_backend_runtime_validator_authority_v4(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
) -> dict[str, Any]:
    """Assess one Q4 implementation leaf without authenticating any record."""
    authority_sha = value.get("authority_sha256") if type(value) is dict else None
    validator_id = value.get("validator_id") if type(value) is dict else None
    projection_sha: str | None = None
    q4_pin_validated = False
    checked = 0
    blockers: list[str] = []
    try:
        authority = validate_backend_runtime_validator_authority_v4(
            value, expected_authority_sha256=expected_authority_sha256,
        )
        q4_pin_validated = True
        projection = _physical_reader_projection(authority)
        projection_sha = projection["authority_sha256"]
        physical = physical_reader.assess_backend_runtime_cell_validator_authority(
            projection, project_root=project_root,
            expected_authority_sha256=projection_sha,
        )
        status, checked, blockers = _validate_physical_assessment(
            physical, projection_sha256=projection_sha,
            validator_id=authority["validator_id"],
        )
        if status != "physically_valid":
            checked = 0
    except (
        BackendRuntimeValidatorAuthorityV4Error,
        physical_reader.BackendRuntimeValidatorAuthorityError,
        OSError, TypeError, ValueError,
    ) as error:
        blockers.append(str(error))
        checked = 0
    blockers = sorted(dict.fromkeys(item for item in blockers if item))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if q4_pin_validated
        and checked == 1 and not blockers else "blocked",
        "authority_sha256": authority_sha,
        "validator_id": validator_id,
        "q4_authority_pin_validated": q4_pin_validated,
        "physical_assessment_scope":
            "single_validator_implementation_descriptor",
        "physical_reader_adapter_kind": physical_reader.ARTIFACT_KIND,
        "physical_reader_projection_sha256": projection_sha,
        "physical_reader_projection_is_trust_anchor": False,
        "checked_artifact_count": checked,
        "blockers": blockers,
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }


__all__ = [
    "ARTIFACT_KIND", "ASSESSMENT_KIND", "SCHEMA_VERSION",
    "SUPPORTED_QUALIFICATION_SCHEMA_VERSION", "IDENTITY_FIELDS",
    "BackendRuntimeValidatorAuthorityV4Error",
    "assess_backend_runtime_validator_authority_v4",
    "build_backend_runtime_validator_authority_v4",
    "validate_backend_runtime_validator_authority_v4",
]
