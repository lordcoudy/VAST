#!/usr/bin/env python3
"""Dependency-light binding of materialized analytics workers to sockets.

This module deliberately depends only on the frozen execution protocol/worker
stdlib surfaces.  SDK adapters can therefore validate CPU/TensorRT endpoints
without importing a topology coordinator or its pandas/YAML dependencies.
"""
from __future__ import annotations

import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from analytics_execution_protocol import (
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_TENSOR_BYTES,
    PROTOCOL_IDENTITY_SHA256,
    TRANSPORT_KIND,
    ProtocolError,
)
from analytics_execution_worker import (
    ExecutionClient,
    WORKER_CAPABILITY_KIND,
    validate_runtime_probe,
    validate_worker_capability,
)


RESOURCES = ("cpu", "gpu")
RESOURCE_ENGINE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_BINDING_COMMON_FIELDS = {
    "schema_version",
    "artifact_kind",
    "worker_id",
    "branch",
    "model_id",
    "source_path",
    "source_model_sha256",
    "input",
    "preprocessing_contract_sha256",
    "output_contract_sha256",
    "outputs",
    "worker_image_id",
    "model_artifact_sha256",
}
_OPENVINO_BINDING_FIELDS = _BINDING_COMMON_FIELDS | {
    "model_path",
    "weights_path",
    "runtime_weights_sha256",
}
_TENSORRT_BINDING_FIELDS = _BINDING_COMMON_FIELDS | {
    "engine_path",
    "gpu_device_index",
    "gpu_uuid",
}


class ExecutionClientLike(Protocol):
    def handshake(self) -> dict[str, Any]: ...

    def infer(
        self,
        request: Mapping[str, Any],
        tensor: bytes | bytearray | memoryview,
    ) -> tuple[dict[str, Any], bytes]: ...


@dataclass(frozen=True)
class ExecutionEndpoint:
    resource: str
    capability: Mapping[str, Any]
    client: ExecutionClientLike


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    _require(set(value) == fields, f"{label} fields have drifted")
    return value


def _stable(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_STABLE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    return int(value)


def execution_endpoint_from_socket(
    sock: socket.socket,
    *,
    resource: str,
    expected_capability: Mapping[str, Any],
) -> ExecutionEndpoint:
    return ExecutionEndpoint(
        resource=resource,
        capability=dict(expected_capability),
        client=ExecutionClient(sock, expected_capability=expected_capability),
    )


def expected_capability_from_binding_and_probe(
    *,
    binding: Mapping[str, Any],
    runtime_probe: Mapping[str, Any],
    resource: str,
) -> dict[str, Any]:
    normalized_resource = str(resource)
    _require(normalized_resource in RESOURCES, "analytics endpoint resource is invalid")
    engine = RESOURCE_ENGINE[normalized_resource]
    probe = validate_runtime_probe(runtime_probe, engine=engine)
    expected_fields = (
        _OPENVINO_BINDING_FIELDS
        if normalized_resource == "cpu"
        else _TENSORRT_BINDING_FIELDS
    )
    value = _exact(
        binding,
        expected_fields,
        f"{normalized_resource} materialized analytics binding",
    )
    expected_kind = (
        "vast_openvino_execution_worker_binding"
        if normalized_resource == "cpu"
        else "vast_tensorrt_execution_worker_binding"
    )
    _require(value["schema_version"] == 1, "analytics binding schema_version is invalid")
    _require(value["artifact_kind"] == expected_kind, "analytics binding kind is invalid")
    branch = str(value["branch"])
    _require(branch in BRANCHES, "analytics binding branch is invalid")
    if normalized_resource == "gpu":
        _integer(value["gpu_device_index"], "TensorRT binding GPU index")
        _require(
            value["gpu_uuid"] == probe["device_id"],
            "TensorRT binding GPU UUID differs from the runtime probe",
        )
    runtime_weights = (
        _sha(value["runtime_weights_sha256"], "runtime weights sha256")
        if normalized_resource == "cpu"
        else None
    )
    capability = {
        "schema_version": 1,
        "artifact_kind": WORKER_CAPABILITY_KIND,
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": _stable(value["worker_id"], "analytics binding worker_id"),
        "branch": branch,
        "engine": engine,
        "worker_image_id": str(value["worker_image_id"]),
        "worker_implementation_sha256": probe["worker_implementation_sha256"],
        "runtime_name": probe["runtime_name"],
        "runtime_version": probe["runtime_version"],
        "device_api": probe["device_api"],
        "device_id": probe["device_id"],
        "native_inference_api": probe["native_inference_api"],
        "execution_path": probe["execution_path"],
        "model_id": _stable(value["model_id"], "analytics binding model_id"),
        "source_model_sha256": _sha(value["source_model_sha256"], "source model sha256"),
        "model_artifact_sha256": _sha(value["model_artifact_sha256"], "model artifact sha256"),
        "runtime_weights_sha256": runtime_weights,
        "preprocessing_contract_sha256": _sha(
            value["preprocessing_contract_sha256"], "preprocessing contract sha256"
        ),
        "output_contract_sha256": _sha(
            value["output_contract_sha256"], "output contract sha256"
        ),
        "transport": TRANSPORT_KIND,
        "max_inflight_requests": 1,
        "max_tensor_bytes": MAX_TENSOR_BYTES,
    }
    return validate_worker_capability(capability)


def terminal_detector_identity(capability: Mapping[str, Any]) -> str:
    """Return the stable semantic model identity used by terminal evidence."""

    checked = validate_worker_capability(capability)
    return (
        f"{checked['model_id']};"
        f"model_sha256={checked['source_model_sha256']}"
    )


__all__ = [
    "ExecutionEndpoint",
    "expected_capability_from_binding_and_probe",
    "execution_endpoint_from_socket",
    "terminal_detector_identity",
]
