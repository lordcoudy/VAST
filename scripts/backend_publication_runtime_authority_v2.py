#!/usr/bin/env python3
"""Closed v2 runtime authority with explicit upstream identity bindings.

This module validates and physically assesses immutable inputs only.  It does
not authorize execution, validate analytics provenance or static-map
semantics, issue grants, accept run evidence, write receipts, or change
readiness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import backend_publication_runtime_authority as runtime_authority_v1


SCHEMA_VERSION = 2
ARTIFACT_KIND = "vast_backend_publication_runtime_authority_v2"
ASSESSMENT_KIND = "vast_backend_publication_runtime_authority_assessment_v2"
UPSTREAM_IDENTITY_FIELDS = frozenset({
    "dataset_manifest_sha256",
    "policy_contract_sha256",
    "policy_qualification_receipt_sha256",
    "resource_contract_identity_sha256",
    "resource_qualification_receipt_sha256",
    "analytics_execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "model_parity_acceptance_binding_sha256",
})
POLICY_OUTPUT_FIELDS = frozenset({"capability", "calibration", "static_map"})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_SHARED_FIELDS = (
    "coordinate",
    "dataset",
    "source_runtime_artifacts",
    "backend_runtime_artifacts",
    "analytics_authority",
    "policy_authority",
    "cohort_topology_plan",
    "resource_contract",
    "system_specific_launcher_input",
)
TOP_FIELDS = frozenset({
    "schema_version",
    "artifact_kind",
    *_SHARED_FIELDS,
    "upstream_identities",
    "authority_sha256",
})
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class BackendPublicationRuntimeAuthorityV2Error(RuntimeError):
    """The v2 runtime authority or its expected context is inconsistent."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as error:
        raise BackendPublicationRuntimeAuthorityV2Error(
            "runtime authority v2 material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendPublicationRuntimeAuthorityV2Error(message)


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _validate_upstream_identities(
    value: Any, *, label: str,
) -> dict[str, str]:
    _require(
        type(value) is dict and set(value) == UPSTREAM_IDENTITY_FIELDS,
        f"{label} upstream identity fields drifted",
    )
    _require(
        all(_valid_sha(item) for item in value.values()),
        f"{label} upstream identity SHA-256 is invalid",
    )
    return copy.deepcopy(value)


def _project_to_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    material = {
        "schema_version": runtime_authority_v1.SCHEMA_VERSION,
        "artifact_kind": runtime_authority_v1.ARTIFACT_KIND,
        **{name: copy.deepcopy(value[name]) for name in _SHARED_FIELDS},
        "model_parity_acceptance_binding_sha256": value[
            "upstream_identities"
        ]["model_parity_acceptance_binding_sha256"],
    }
    material["authority_sha256"] = _canonical_sha(material)
    return material


def _reconstruct_from_v1(
    projected: Mapping[str, Any], upstream_identities: Mapping[str, str],
) -> dict[str, Any]:
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        **{name: copy.deepcopy(projected[name]) for name in _SHARED_FIELDS},
        "upstream_identities": copy.deepcopy(dict(upstream_identities)),
    }
    material["authority_sha256"] = _canonical_sha(material)
    return material


def _validate_policy_outputs(
    authority: Mapping[str, Any], expected_policy_outputs: Any,
) -> None:
    _require(
        type(expected_policy_outputs) is dict
        and set(expected_policy_outputs) == POLICY_OUTPUT_FIELDS,
        "expected policy output fields drifted",
    )
    policy_authority = authority["policy_authority"]
    for name, label in (
        ("capability", "policy capability"),
        ("calibration", "policy calibration"),
        ("static_map", "policy static map"),
    ):
        artifact = policy_authority[name]
        observed = None if artifact is None else artifact["descriptor"]
        expected = expected_policy_outputs[name]
        if expected is not None:
            _require(
                type(expected) is dict and set(expected) == _DESCRIPTOR_FIELDS
                and type(expected.get("path")) is str
                and bool(expected["path"])
                and type(expected.get("size_bytes")) is int
                and expected["size_bytes"] > 0
                and _valid_sha(expected.get("sha256")),
                f"expected {label} descriptor is invalid",
            )
        _require(
            observed == expected,
            f"{label} canonical descriptor does not match expected output",
        )


def validate_backend_publication_runtime_authority_v2(
    value: Any,
    *,
    expected_system: str,
    expected_policy: str,
    expected_topology_kind: str,
    expected_codec: str,
    expected_upstream_identities: Mapping[str, str],
    expected_policy_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Purely validate closed v2 content against explicit caller context."""
    for expected, label in (
        (expected_system, "system"),
        (expected_policy, "policy"),
        (expected_topology_kind, "topology"),
        (expected_codec, "codec"),
    ):
        _require(
            type(expected) is str and bool(expected),
            f"expected runtime authority {label} is required",
        )
    _require(
        type(value) is dict and set(value) == TOP_FIELDS,
        "backend publication runtime authority v2 fields drifted",
    )
    _require(
        value.get("schema_version") == SCHEMA_VERSION,
        "runtime authority v2 schema version is invalid",
    )
    _require(
        value.get("artifact_kind") == ARTIFACT_KIND,
        "runtime authority v2 artifact kind is invalid",
    )
    upstream = _validate_upstream_identities(value.get("upstream_identities"), label="authority")
    expected_upstream = _validate_upstream_identities(
        expected_upstream_identities, label="expected",
    )
    _require(
        upstream == expected_upstream,
        "runtime authority v2 upstream identities do not match caller context",
    )
    unsigned = {
        key: item for key, item in value.items()
        if key != "authority_sha256"
    }
    _require(
        value.get("authority_sha256") == _canonical_sha(unsigned),
        "runtime authority v2 self-hash drifted",
    )

    projected = _project_to_v1(value)
    try:
        validated_v1 = runtime_authority_v1.validate_backend_publication_runtime_authority(
            projected,
            expected_system=expected_system,
            expected_policy=expected_policy,
            expected_topology_kind=expected_topology_kind,
            expected_codec=expected_codec,
        )
    except runtime_authority_v1.BackendPublicationRuntimeAuthorityError as error:
        raise BackendPublicationRuntimeAuthorityV2Error(str(error)) from error

    reconstructed = _reconstruct_from_v1(validated_v1, upstream)
    _require(
        reconstructed == value,
        "runtime authority v2 to v1 projection is not closed and lossless",
    )
    _require(
        validated_v1["model_parity_acceptance_binding_sha256"]
        == upstream["model_parity_acceptance_binding_sha256"],
        "model parity acceptance binding drifted",
    )
    _require(
        validated_v1["dataset"]["manifest"]["sha256"]
        == upstream["dataset_manifest_sha256"],
        "dataset manifest identity drifted",
    )
    _require(
        validated_v1["resource_contract"]["content_identity_sha256"]
        == upstream["resource_contract_identity_sha256"],
        "resource contract identity drifted",
    )
    _validate_policy_outputs(validated_v1, expected_policy_outputs)
    return copy.deepcopy(value)


def assess_backend_publication_runtime_authority_v2(
    value: Any,
    *,
    project_root: Path,
    expected_system: str,
    expected_policy: str,
    expected_topology_kind: str,
    expected_codec: str,
    expected_upstream_identities: Mapping[str, str],
    expected_policy_outputs: Mapping[str, Any],
) -> dict[str, Any]:
    """Physically assess v2 leaves without making authorization claims."""
    authority_sha = value.get("authority_sha256") if type(value) is dict else None
    coordinate = value.get("coordinate", {}) if type(value) is dict else {}
    blockers: list[str] = []
    checked = 0
    try:
        authority = validate_backend_publication_runtime_authority_v2(
            value,
            expected_system=expected_system,
            expected_policy=expected_policy,
            expected_topology_kind=expected_topology_kind,
            expected_codec=expected_codec,
            expected_upstream_identities=expected_upstream_identities,
            expected_policy_outputs=expected_policy_outputs,
        )
        projected = _project_to_v1(authority)
        assessment_v1 = runtime_authority_v1.assess_backend_publication_runtime_authority(
            projected,
            project_root=project_root,
            expected_system=expected_system,
            expected_policy=expected_policy,
            expected_topology_kind=expected_topology_kind,
            expected_codec=expected_codec,
        )
        _require(
            type(assessment_v1) is dict
            and assessment_v1.get("schema_version") == 1
            and assessment_v1.get("artifact_kind")
            == runtime_authority_v1.ASSESSMENT_KIND
            and assessment_v1.get("authority_sha256")
            == projected["authority_sha256"]
            and assessment_v1.get("system") == expected_system
            and assessment_v1.get("policy") == expected_policy
            and assessment_v1.get("topology_kind") == expected_topology_kind
            and assessment_v1.get("codec") == expected_codec
            and type(assessment_v1.get("checked_artifact_count")) is int
            and assessment_v1["checked_artifact_count"] >= 0
            and type(assessment_v1.get("blockers")) is list
            and all(type(item) is str and bool(item) for item in assessment_v1["blockers"]),
            "public v1 physical assessment response is malformed",
        )
        checked = assessment_v1["checked_artifact_count"]
        blockers.extend(assessment_v1["blockers"])
        if assessment_v1.get("status") != "physically_valid" and not blockers:
            blockers.append("public v1 physical assessment did not report physically_valid")
    except (
        BackendPublicationRuntimeAuthorityV2Error,
        runtime_authority_v1.BackendPublicationRuntimeAuthorityError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        blockers.append(str(error))
    blockers = sorted(dict.fromkeys(blockers))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if not blockers else "blocked",
        "authority_sha256": authority_sha,
        "system": coordinate.get("system"),
        "policy": coordinate.get("policy"),
        "topology_kind": coordinate.get("topology_kind"),
        "codec": coordinate.get("codec"),
        "checked_artifact_count": checked,
        "blockers": blockers,
        "execution_authorized": False,
        "analytics_provenance_validated": False,
        "static_map_semantics_validated": False,
    }


def build_backend_publication_runtime_authority_v2(
    *,
    project_root: Path,
    system: str,
    policy: str,
    topology_kind: str,
    codec: str,
    dataset_manifest: Mapping[str, Any],
    dataset_files: Sequence[Mapping[str, Any]],
    source_runtime_artifacts: Sequence[Mapping[str, Any]],
    backend_runtime_artifacts: Sequence[Mapping[str, Any]],
    analytics_authority: Mapping[str, Any],
    upstream_identities: Mapping[str, str],
    expected_upstream_identities: Mapping[str, str],
    expected_policy_outputs: Mapping[str, Any],
    policy_authority: Mapping[str, Any],
    cohort_topology_plan: Mapping[str, Any],
    resource_contract: Mapping[str, Any],
    system_specific_launcher_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Build v2 only after the public v1 physical assessment succeeds."""
    upstream = _validate_upstream_identities(upstream_identities, label="authority")
    expected_upstream = _validate_upstream_identities(
        expected_upstream_identities, label="expected",
    )
    _require(
        upstream == expected_upstream,
        "runtime authority v2 upstream identities do not match caller context",
    )
    try:
        projected = runtime_authority_v1.build_backend_publication_runtime_authority(
            project_root=project_root,
            system=system,
            policy=policy,
            topology_kind=topology_kind,
            codec=codec,
            dataset_manifest=dataset_manifest,
            dataset_files=dataset_files,
            source_runtime_artifacts=source_runtime_artifacts,
            backend_runtime_artifacts=backend_runtime_artifacts,
            analytics_authority=analytics_authority,
            model_parity_acceptance_binding_sha256=upstream[
                "model_parity_acceptance_binding_sha256"
            ],
            policy_authority=policy_authority,
            cohort_topology_plan=cohort_topology_plan,
            resource_contract=resource_contract,
            system_specific_launcher_input=system_specific_launcher_input,
        )
    except runtime_authority_v1.BackendPublicationRuntimeAuthorityError as error:
        raise BackendPublicationRuntimeAuthorityV2Error(str(error)) from error
    authority = _reconstruct_from_v1(projected, upstream)
    authority = validate_backend_publication_runtime_authority_v2(
        authority,
        expected_system=system,
        expected_policy=policy,
        expected_topology_kind=topology_kind,
        expected_codec=codec,
        expected_upstream_identities=expected_upstream,
        expected_policy_outputs=expected_policy_outputs,
    )
    assessment = assess_backend_publication_runtime_authority_v2(
        authority,
        project_root=project_root,
        expected_system=system,
        expected_policy=policy,
        expected_topology_kind=topology_kind,
        expected_codec=codec,
        expected_upstream_identities=expected_upstream,
        expected_policy_outputs=expected_policy_outputs,
    )
    if assessment["status"] != "physically_valid":
        raise BackendPublicationRuntimeAuthorityV2Error(
            "runtime authority v2 physical assessment blocked: "
            + ";".join(assessment["blockers"])
        )
    return authority


__all__ = [
    "ARTIFACT_KIND",
    "ASSESSMENT_KIND",
    "POLICY_OUTPUT_FIELDS",
    "SCHEMA_VERSION",
    "TOP_FIELDS",
    "UPSTREAM_IDENTITY_FIELDS",
    "BackendPublicationRuntimeAuthorityV2Error",
    "assess_backend_publication_runtime_authority_v2",
    "build_backend_publication_runtime_authority_v2",
    "validate_backend_publication_runtime_authority_v2",
]
