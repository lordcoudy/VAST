#!/usr/bin/env python3
"""Derive immutable production runtime pins from a preprocessing receipt."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any


QUALIFICATION_RECEIPT_KIND = (
    "vast_guardian_preprocessing_contract_materialization_v1"
)
ACCEPTED_POLICY_RECEIPT_KIND = (
    "vast_guardian_accepted_policy_preprocessing_contract_materialization_v1"
)
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}


class GuardianRuntimeExpectationsV1Error(RuntimeError):
    """The preprocessing receipt cannot be an external runtime authority."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GuardianRuntimeExpectationsV1Error(message)


def _sha(value: object, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return str(value)


def _descriptor(value: object, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    path = value.get("path")
    size = value.get("size_bytes")
    _require(
        type(path) is str
        and bool(path)
        and not path.startswith(("/", "\\"))
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and type(size) is int
        and size > 0,
        f"{label} descriptor values drifted",
    )
    return {"path": path, "size_bytes": size, "sha256": _sha(value.get("sha256"), label)}


def runtime_expectations_from_preprocessing_receipt_v1(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Return only pins whose authority predates the production service."""

    _require(type(receipt) is dict, "preprocessing receipt must be one plain object")
    _require(
        receipt.get("artifact_kind")
        in {QUALIFICATION_RECEIPT_KIND, ACCEPTED_POLICY_RECEIPT_KIND},
        "preprocessing receipt kind is not an external runtime authority",
    )
    refresh = receipt.get("model_parity_refresh_authority")
    _require(
        type(refresh) is dict
        and set(refresh)
        == {
            "image_identity_patch",
            "workers",
            "execution_config",
            "binding_set",
            "runtime_probes",
        },
        "preprocessing receipt model-parity refresh authority fields drifted",
    )

    execution = refresh.get("execution_config")
    _require(
        type(execution) is dict
        and set(execution)
        == _DESCRIPTOR_FIELDS
        | {"content_identity_sha256", "worker_projection_sha256"},
        "preprocessing execution-config authority fields drifted",
    )
    _descriptor(
        {field: execution[field] for field in _DESCRIPTOR_FIELDS},
        "preprocessing execution config",
    )
    execution_identity = _sha(
        execution.get("content_identity_sha256"),
        "preprocessing execution config content",
    )
    _sha(
        execution.get("worker_projection_sha256"),
        "preprocessing execution worker projection",
    )

    binding_set = refresh.get("binding_set")
    _require(
        type(binding_set) is dict
        and set(binding_set)
        == {"index", "identity_sha256", "bindings_identity_sha256", "bindings"},
        "preprocessing binding-set authority fields drifted",
    )
    _descriptor(binding_set.get("index"), "preprocessing binding-set index")
    expected_coordinates = {
        f"{branch}:{resource}" for branch in BRANCHES for resource in RESOURCES
    }
    bindings = binding_set.get("bindings")
    _require(
        type(bindings) is dict and set(bindings) == expected_coordinates,
        "preprocessing binding-set coverage is not exact 8",
    )
    for coordinate in sorted(expected_coordinates):
        _descriptor(bindings[coordinate], f"preprocessing binding {coordinate}")

    workers = refresh.get("workers")
    _require(
        type(workers) is dict and set(workers) == set(RESOURCES),
        "preprocessing worker authority coverage is not exact CPU/GPU",
    )
    worker_images: dict[str, str] = {}
    worker_fields = {
        "image",
        "image_id",
        "worker_implementation_sha256",
        "source_set_sha256",
        "receipt_sha256",
    }
    for resource in RESOURCES:
        worker = workers[resource]
        _require(
            type(worker) is dict
            and set(worker) == worker_fields
            and type(worker.get("image")) is str
            and bool(worker["image"])
            and type(worker.get("image_id")) is str
            and _IMAGE_RE.fullmatch(worker["image_id"]) is not None,
            f"preprocessing {resource} worker authority drifted",
        )
        for field in (
            "worker_implementation_sha256",
            "source_set_sha256",
            "receipt_sha256",
        ):
            _sha(worker.get(field), f"preprocessing {resource} {field}")
        worker_images[resource] = worker["image_id"]

    return copy.deepcopy(
        {
            "execution_config_identity_sha256": execution_identity,
            "binding_set_identity_sha256": _sha(
                binding_set.get("identity_sha256"),
                "preprocessing binding-set identity",
            ),
            "bindings_identity_sha256": _sha(
                binding_set.get("bindings_identity_sha256"),
                "preprocessing bindings identity",
            ),
            "worker_image_ids": worker_images,
            "policy_contract_sha256": _sha(
                receipt.get("policy_contract_sha256"),
                "preprocessing policy contract",
            ),
            "preprocessing_contract_content_sha256": _sha(
                receipt.get("preprocessing_contract_content_sha256"),
                "preprocessing contract content",
            ),
        }
    )


__all__ = [
    "ACCEPTED_POLICY_RECEIPT_KIND",
    "GuardianRuntimeExpectationsV1Error",
    "QUALIFICATION_RECEIPT_KIND",
    "runtime_expectations_from_preprocessing_receipt_v1",
]
