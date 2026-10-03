#!/usr/bin/env python3
"""OpenVINO GVA SDK tensor-to-native-worker protocol-v3 bridge.

The bridge is deliberately smaller than a checkpoint launcher.  A topology-
specific GStreamer/DL Streamer adapter supplies one verified post-preprocess
``GstBuffer`` tensor and its direct-admission identity.  This module dispatches
that tensor through the frozen :class:`ExecutionClient` and returns the exact
topology-v2 ``analytics -> postprocess_<branch> -> branch_complete`` tail
consumed by ``DirectRuntimeJoinCoordinator``.

Nothing here writes an accepted benchmark sidecar or claims publication
readiness.  The engineering 24-worker/6-graph launcher is implemented, but KPP
pilots, native policy evidence, resource-v2 attribution, and accepted reset
evidence remain separate gates.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from analytics_execution_protocol import (
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_TENSOR_BYTES,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    TRANSPORT_KIND,
    validate_inference_request,
)
from analytics_execution_worker import (
    ExecutionClient,
    WORKER_CAPABILITY_KIND,
    validate_inference_response,
    validate_runtime_probe,
    validate_worker_capability,
)
from analytics_execution_endpoint import terminal_detector_identity
from checkpoint_runtime import RuntimeMessage
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG


GVA_SDK_BINDING = "intel_dl_streamer_gva_verified_preprocess_gst_buffer_v1"
GVA_TENSOR_ORIGIN = "verified_preprocess_src_pad"
GVA_PTS_ORIGIN = "GST_BUFFER_PTS"
RESOURCES = ("cpu", "gpu")
RESOURCE_ENGINE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
NATIVE_QUEUE_DROP_REASONS = {
    "native_pre_detector_queue_full_drop_newest",
    "native_postdecode_preprocess_queue_full_drop_newest",
}
BRIDGE_PUBLICATION_BLOCKERS = (
    "openvino_gva_topology_engineering_runtime_not_accepted",
    "openvino_gva_native_policy_decision_evidence_not_bound",
    "openvino_gva_resource_v2_not_accepted",
    "openvino_gva_kpp_pilots_not_accepted",
    "openvino_gva_accepted_sidecars_not_written",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_CONTEXT_FIELDS = {
    "sdk_binding",
    "tensor_origin",
    "pts_origin",
    "run_id",
    "arm_id",
    "request_id",
    "topology_kind",
    "topology_worker_id",
    "topology_worker_trace_id",
    "event_sequence",
    "stream_id",
    "frame_id",
    "input_frame_key",
    "transport_pts_ns",
    "branch",
    "selected_resource",
    "parent_execution_id",
    "postprocess_execution_id",
    "terminal_execution_id",
    "admission_id",
    "payload_sha256",
    "policy_decision_id",
    "policy_decision_sha256",
    "deadline_monotonic_ns",
}
_TENSOR_DESCRIPTOR_FIELDS = {
    "name",
    "dtype",
    "layout",
    "shape",
    "preprocessing_contract_sha256",
    "contiguous",
    "read_only",
}
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
    """The exact public surface used from the frozen ``ExecutionClient``."""

    def handshake(self) -> dict[str, Any]: ...

    def infer(
        self,
        request: Mapping[str, Any],
        tensor: bytes | bytearray | memoryview,
    ) -> tuple[dict[str, Any], bytes]: ...


@dataclass(frozen=True)
class ExecutionEndpoint:
    """One branch/resource endpoint bound to an immutable worker capability."""

    resource: str
    capability: Mapping[str, Any]
    client: ExecutionClientLike


@dataclass(frozen=True)
class _BoundEndpoint:
    resource: str
    capability: dict[str, Any]
    client: ExecutionClientLike


def execution_endpoint_from_socket(
    sock: socket.socket,
    *,
    resource: str,
    expected_capability: Mapping[str, Any],
) -> ExecutionEndpoint:
    """Bind a real frozen ``ExecutionClient`` without adding another transport."""

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
    """Assemble the exact pre-hello capability from frozen binding + probe.

    The materialized binding must already have passed its engine-specific file
    and digest validator.  The model-free runtime probe contributes only the
    immutable runtime/device/implementation fields.  Worker construction still
    loads and validates the model or TensorRT engine before hello, and the
    normal ``ExecutionClient`` handshake rejects any assembled mismatch.
    """

    normalized_resource = str(resource)
    _require(
        normalized_resource in RESOURCES,
        "OpenVINO GVA expected capability resource is invalid",
    )
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
        f"OpenVINO GVA {normalized_resource} materialized binding",
    )
    expected_kind = (
        "vast_openvino_execution_worker_binding"
        if normalized_resource == "cpu"
        else "vast_tensorrt_execution_worker_binding"
    )
    _require(value["schema_version"] == 1, "OpenVINO GVA binding schema_version is invalid")
    _require(value["artifact_kind"] == expected_kind, "OpenVINO GVA binding kind is invalid")
    branch = str(value["branch"])
    _require(branch in BRANCHES, "OpenVINO GVA binding branch is invalid")
    if normalized_resource == "gpu":
        _integer(value["gpu_device_index"], "OpenVINO GVA TensorRT GPU index")
        _require(
            value["gpu_uuid"] == probe["device_id"],
            "OpenVINO GVA TensorRT binding GPU UUID differs from the runtime probe",
        )
    runtime_weights = (
        _sha(value["runtime_weights_sha256"], "OpenVINO GVA runtime weights sha256")
        if normalized_resource == "cpu"
        else None
    )
    capability = {
        "schema_version": 1,
        "artifact_kind": WORKER_CAPABILITY_KIND,
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "worker_id": _stable(value["worker_id"], "OpenVINO GVA binding worker_id"),
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
        "model_id": _stable(value["model_id"], "OpenVINO GVA binding model_id"),
        "source_model_sha256": _sha(
            value["source_model_sha256"], "OpenVINO GVA source model sha256"
        ),
        "model_artifact_sha256": _sha(
            value["model_artifact_sha256"], "OpenVINO GVA model artifact sha256"
        ),
        "runtime_weights_sha256": runtime_weights,
        "preprocessing_contract_sha256": _sha(
            value["preprocessing_contract_sha256"],
            "OpenVINO GVA preprocessing contract sha256",
        ),
        "output_contract_sha256": _sha(
            value["output_contract_sha256"], "OpenVINO GVA output contract sha256"
        ),
        "transport": TRANSPORT_KIND,
        "max_inflight_requests": 1,
        "max_tensor_bytes": MAX_TENSOR_BYTES,
    }
    return validate_worker_capability(capability)


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


def _visible(value: Any, label: str, maximum: int = 512) -> str:
    result = str(value or "")
    _require(0 < len(result) <= maximum, f"{label} length is invalid")
    _require(
        all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result),
        f"{label} contains controls",
    )
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SHA256_RE.fullmatch(result) is not None, f"{label} must be a lowercase SHA-256")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    _require(type(value) is int and value >= minimum, f"{label} must be an integer >= {minimum}")
    return int(value)


def _validated_context(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = _exact(value, _CONTEXT_FIELDS, "OpenVINO GVA SDK dispatch context")
    _require(raw["sdk_binding"] == GVA_SDK_BINDING, "OpenVINO GVA SDK binding is invalid")
    _require(raw["tensor_origin"] == GVA_TENSOR_ORIGIN, "OpenVINO GVA tensor origin is not SDK-bound")
    _require(raw["pts_origin"] == GVA_PTS_ORIGIN, "OpenVINO GVA PTS origin is not GST_BUFFER_PTS")
    topology_kind = str(raw["topology_kind"])
    _require(
        topology_kind in {INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG},
        "OpenVINO GVA topology kind is invalid",
    )
    branch = str(raw["branch"])
    resource = str(raw["selected_resource"])
    _require(branch in BRANCHES, "OpenVINO GVA branch is invalid")
    _require(resource in RESOURCES, "OpenVINO GVA selected resource is invalid")
    parent_execution_id = _visible(
        raw["parent_execution_id"], "OpenVINO GVA parent execution_id"
    )
    postprocess_execution_id = _visible(
        raw["postprocess_execution_id"],
        "OpenVINO GVA postprocess execution_id",
    )
    terminal_execution_id = _visible(
        raw["terminal_execution_id"], "OpenVINO GVA terminal execution_id"
    )
    _require(
        len({parent_execution_id, postprocess_execution_id, terminal_execution_id}) == 3,
        "OpenVINO GVA topology execution IDs must be distinct",
    )
    return {
        "sdk_binding": GVA_SDK_BINDING,
        "tensor_origin": GVA_TENSOR_ORIGIN,
        "pts_origin": GVA_PTS_ORIGIN,
        "run_id": _stable(raw["run_id"], "OpenVINO GVA run_id"),
        "arm_id": _stable(raw["arm_id"], "OpenVINO GVA arm_id"),
        "request_id": _stable(raw["request_id"], "OpenVINO GVA request_id"),
        "topology_kind": topology_kind,
        "topology_worker_id": _stable(
            raw["topology_worker_id"], "OpenVINO GVA topology worker_id"
        ),
        "topology_worker_trace_id": _visible(
            raw["topology_worker_trace_id"], "OpenVINO GVA topology worker trace_id"
        ),
        "event_sequence": _integer(
            raw["event_sequence"], "OpenVINO GVA event sequence", minimum=1
        ),
        "stream_id": _integer(raw["stream_id"], "OpenVINO GVA stream_id"),
        "frame_id": _integer(raw["frame_id"], "OpenVINO GVA frame_id"),
        "input_frame_key": _visible(
            raw["input_frame_key"], "OpenVINO GVA input_frame_key"
        ),
        "transport_pts_ns": _integer(
            raw["transport_pts_ns"], "OpenVINO GVA transport PTS"
        ),
        "branch": branch,
        "selected_resource": resource,
        "parent_execution_id": parent_execution_id,
        "postprocess_execution_id": postprocess_execution_id,
        "terminal_execution_id": terminal_execution_id,
        "admission_id": _visible(raw["admission_id"], "OpenVINO GVA admission_id"),
        "payload_sha256": _sha(
            raw["payload_sha256"], "OpenVINO GVA admitted payload sha256"
        ),
        "policy_decision_id": _stable(
            raw["policy_decision_id"], "OpenVINO GVA policy decision_id"
        ),
        "policy_decision_sha256": _sha(
            raw["policy_decision_sha256"], "OpenVINO GVA policy decision sha256"
        ),
        "deadline_monotonic_ns": _integer(
            raw["deadline_monotonic_ns"],
            "OpenVINO GVA inference deadline",
            minimum=1,
        ),
    }


def _validated_tensor_descriptor(
    value: Mapping[str, Any],
    *,
    preprocessing_contract_sha256: str,
) -> dict[str, Any]:
    raw = _exact(value, _TENSOR_DESCRIPTOR_FIELDS, "OpenVINO GVA SDK tensor descriptor")
    _require(raw["contiguous"] is True, "OpenVINO GVA SDK tensor must be contiguous")
    _require(raw["read_only"] is True, "OpenVINO GVA SDK tensor map must be read-only")
    _require(
        raw["preprocessing_contract_sha256"] == preprocessing_contract_sha256,
        "OpenVINO GVA SDK preprocessing contract mismatch",
    )
    shape = raw["shape"]
    _require(type(shape) is list, "OpenVINO GVA SDK tensor shape must be a list")
    return {
        "name": _visible(raw["name"], "OpenVINO GVA SDK tensor name", 256),
        "dtype": str(raw["dtype"]),
        "layout": str(raw["layout"]),
        "shape": list(shape),
        "preprocessing_contract_sha256": preprocessing_contract_sha256,
    }


class OpenVINOGVAExecutionBridge:
    """Route exact SDK tensors to frozen CPU/TensorRT endpoints and emit v3 terminals."""

    def __init__(
        self,
        endpoints: Sequence[ExecutionEndpoint],
        *,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        expected_keys = {(branch, resource) for branch in BRANCHES for resource in RESOURCES}
        bound: dict[tuple[str, str], _BoundEndpoint] = {}
        for endpoint in endpoints:
            _require(isinstance(endpoint, ExecutionEndpoint), "OpenVINO GVA execution endpoint is invalid")
            resource = str(endpoint.resource)
            _require(resource in RESOURCES, "OpenVINO GVA endpoint resource is invalid")
            capability = validate_worker_capability(endpoint.capability)
            expected_engine = RESOURCE_ENGINE[resource]
            _require(
                capability["engine"] == expected_engine,
                f"OpenVINO GVA {resource} endpoint engine mismatch",
            )
            key = (str(capability["branch"]), resource)
            _require(key not in bound, "OpenVINO GVA endpoint inventory contains a duplicate")
            _require(
                callable(getattr(endpoint.client, "handshake", None))
                and callable(getattr(endpoint.client, "infer", None)),
                "OpenVINO GVA endpoint does not expose the frozen ExecutionClient API",
            )
            bound[key] = _BoundEndpoint(
                resource=resource,
                capability=capability,
                client=endpoint.client,
            )
        _require(
            set(bound) == expected_keys,
            "OpenVINO GVA endpoint inventory must cover four branches x cpu/gpu exactly",
        )
        self._endpoints = bound
        self._clock_ms = clock_ms or (lambda: int(time.monotonic_ns() // 1_000_000))
        self._handshaken = False

    def handshake_all(self) -> dict[str, Any]:
        _require(not self._handshaken, "OpenVINO GVA endpoint handshake already completed")
        inventory = []
        for branch in BRANCHES:
            for resource in RESOURCES:
                endpoint = self._endpoints[(branch, resource)]
                actual = validate_worker_capability(endpoint.client.handshake())
                _require(
                    actual == endpoint.capability,
                    f"OpenVINO GVA {branch}/{resource} worker capability mismatch",
                )
                inventory.append(
                    {
                        "branch": branch,
                        "resource": resource,
                        "engine": actual["engine"],
                        "worker_id": actual["worker_id"],
                        "worker_image_id": actual["worker_image_id"],
                        "worker_implementation_sha256": actual[
                            "worker_implementation_sha256"
                        ],
                    }
                )
        self._handshaken = True
        return {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_execution_bridge_handshake",
            "claim_status": "sdk_execution_bridge_handshake_nonpublication",
            "sdk_binding": GVA_SDK_BINDING,
            "endpoint_count": len(inventory),
            "branches": list(BRANCHES),
            "resources": list(RESOURCES),
            "endpoints": inventory,
            "publication_ready": False,
            "accepted_evidence_written": False,
            "publication_blockers": list(BRIDGE_PUBLICATION_BLOCKERS),
        }

    def _endpoint(self, dispatch: dict[str, Any]) -> _BoundEndpoint:
        _require(self._handshaken, "OpenVINO GVA endpoint handshake is required")
        return self._endpoints[(dispatch["branch"], dispatch["selected_resource"])]

    def _postprocess_event(
        self,
        *,
        dispatch: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp_ms = _integer(
            self._clock_ms(), "OpenVINO GVA postprocess monotonic timestamp"
        )
        event = {
            "protocol_version": 2,
            "worker_id": dispatch["topology_worker_id"],
            "sequence": dispatch["event_sequence"],
            "run_id": dispatch["run_id"],
            "trace_id": dispatch["topology_worker_trace_id"],
            "stream_id": dispatch["stream_id"],
            "frame_id": dispatch["frame_id"],
            "input_frame_key": dispatch["input_frame_key"],
            "topology_kind": dispatch["topology_kind"],
            "event_kind": "stage_complete",
            "stage": f"postprocess_{dispatch['branch']}",
            "branch_id": dispatch["branch"],
            "execution_id": dispatch["postprocess_execution_id"],
            "parent_execution_ids": [dispatch["parent_execution_id"]],
            "timestamp_ms": timestamp_ms,
            "admission_id": dispatch["admission_id"],
            "payload_sha256": dispatch["payload_sha256"],
        }
        RuntimeMessage.parse(json.dumps(event, sort_keys=True, separators=(",", ":")))
        return event

    def _terminal_event(
        self,
        *,
        dispatch: dict[str, Any],
        endpoint: _BoundEndpoint,
        event_kind: str,
        objects: int,
        reason: str,
        parent_execution_id: str,
        sequence: int,
    ) -> dict[str, Any]:
        timestamp_ms = _integer(
            self._clock_ms(), "OpenVINO GVA terminal monotonic timestamp"
        )
        event = {
            "protocol_version": 3,
            "worker_id": dispatch["topology_worker_id"],
            "sequence": sequence,
            "run_id": dispatch["run_id"],
            "trace_id": dispatch["topology_worker_trace_id"],
            "stream_id": dispatch["stream_id"],
            "frame_id": dispatch["frame_id"],
            "input_frame_key": dispatch["input_frame_key"],
            "topology_kind": dispatch["topology_kind"],
            "event_kind": event_kind,
            "stage": dispatch["branch"],
            "branch_id": dispatch["branch"],
            "execution_id": dispatch["terminal_execution_id"],
            "parent_execution_ids": [parent_execution_id],
            "timestamp_ms": timestamp_ms,
            "admission_id": dispatch["admission_id"],
            "payload_sha256": dispatch["payload_sha256"],
            "terminal_reason": reason,
            "objects": objects,
            "detector": endpoint.capability["model_id"],
            "backend": endpoint.capability["engine"],
        }
        RuntimeMessage.parse(json.dumps(event, sort_keys=True, separators=(",", ":")))
        return event

    @staticmethod
    def _result_common(dispatch: dict[str, Any], endpoint: _BoundEndpoint) -> dict[str, Any]:
        capability = endpoint.capability
        resource = dispatch["selected_resource"]
        device = "CPU" if resource == "cpu" else "NVIDIA_CUDA:0"
        return {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_execution_bridge_result",
            "claim_status": "engineering_runtime_terminal_nonpublication",
            "sdk_binding": GVA_SDK_BINDING,
            "topology_kind": dispatch["topology_kind"],
            "branch": dispatch["branch"],
            "selected_resource": dispatch["selected_resource"],
            "engine": endpoint.capability["engine"],
            "policy_decision_id": dispatch["policy_decision_id"],
            "policy_decision_sha256": dispatch["policy_decision_sha256"],
            "worker_image_id": endpoint.capability["worker_image_id"],
            "worker_implementation_sha256": endpoint.capability[
                "worker_implementation_sha256"
            ],
            "runtime_identity": {
                "runtime_backend": (
                    "openvino_gva_external_openvino_cpu_worker_v3"
                    if resource == "cpu"
                    else "openvino_gva_external_tensorrt_cuda_worker_v3"
                ),
                "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                "gpu_id": None if resource == "cpu" else 0,
                "worker_image_digest": capability["worker_image_id"],
                "implementation_version": (
                    "sha256:" + capability["worker_implementation_sha256"]
                ),
                "terminal_detector": terminal_detector_identity(capability),
                "terminal_backend": (
                    f"analytics-execution:{capability['engine']};"
                    f"runtime={capability['runtime_name']};"
                    f"native_api={capability['native_inference_api']};"
                    f"device={device}"
                ),
            },
            "publication_ready": False,
            "accepted_evidence_written": False,
            "publication_blockers": list(BRIDGE_PUBLICATION_BLOCKERS),
        }

    def execute(
        self,
        *,
        context: Mapping[str, Any],
        tensor: bytes | bytearray | memoryview,
        tensor_descriptor: Mapping[str, Any],
    ) -> dict[str, Any]:
        dispatch = _validated_context(context)
        endpoint = self._endpoint(dispatch)
        descriptor = _validated_tensor_descriptor(
            tensor_descriptor,
            preprocessing_contract_sha256=endpoint.capability[
                "preprocessing_contract_sha256"
            ],
        )
        _require(
            isinstance(tensor, (bytes, bytearray, memoryview)),
            "OpenVINO GVA SDK tensor payload must be bytes-like",
        )
        if isinstance(tensor, memoryview):
            _require(tensor.contiguous, "OpenVINO GVA SDK tensor memoryview is not contiguous")
        payload = bytes(tensor)
        request = validate_inference_request(
            {
                "schema_version": 1,
                "message_type": "infer_request",
                "request_id": dispatch["request_id"],
                "run_id": dispatch["run_id"],
                "arm_id": dispatch["arm_id"],
                "worker_id": endpoint.capability["worker_id"],
                "frame": {
                    "input_frame_key": dispatch["input_frame_key"],
                    "stream_id": dispatch["stream_id"],
                    "frame_id": dispatch["frame_id"],
                    "transport_pts_ns": dispatch["transport_pts_ns"],
                    "branch": dispatch["branch"],
                },
                "engine": endpoint.capability["engine"],
                "deadline_monotonic_ns": dispatch["deadline_monotonic_ns"],
                "model": {
                    "model_id": endpoint.capability["model_id"],
                    "source_sha256": endpoint.capability["source_model_sha256"],
                    "runtime_artifact_sha256": endpoint.capability[
                        "model_artifact_sha256"
                    ],
                    "runtime_weights_sha256": endpoint.capability[
                        "runtime_weights_sha256"
                    ],
                },
                "tensor": {
                    **descriptor,
                    "byte_length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
                "expected_output_contract_sha256": endpoint.capability[
                    "output_contract_sha256"
                ],
            }
        )
        response, output_payload = endpoint.client.infer(request, payload)
        checked_response = validate_inference_response(
            response,
            request=request,
            capability=endpoint.capability,
        )
        output = bytes(output_payload)
        _require(
            len(output) == checked_response["output"]["byte_length"],
            "OpenVINO GVA worker output byte length mismatch",
        )
        _require(
            hashlib.sha256(output).hexdigest() == checked_response["output"]["sha256"],
            "OpenVINO GVA worker output SHA-256 mismatch",
        )
        terminal = checked_response["terminal"]
        postprocess_event = self._postprocess_event(dispatch=dispatch)
        terminal_event = self._terminal_event(
            dispatch=dispatch,
            endpoint=endpoint,
            event_kind="branch_complete",
            objects=int(terminal["objects"]),
            reason=_visible(
                terminal["reason"], "OpenVINO GVA worker terminal reason", 256
            ),
            parent_execution_id=dispatch["postprocess_execution_id"],
            sequence=dispatch["event_sequence"] + 1,
        )
        worker_resource = checked_response["resource"]
        resource_receipt = {
            field: (
                [dict(interval) for interval in worker_resource[field]]
                if field == "cuda_transfer_intervals"
                else worker_resource[field]
            )
            for field in (
                "process_cpu_time_ns",
                "rss_before_bytes",
                "rss_after_bytes",
                "accelerator_memory_bytes",
                "cuda_h2d_bytes",
                "cuda_d2h_bytes",
                "cuda_transfer_intervals",
            )
        }
        cuda_interval_bindings = (
            []
            if dispatch["selected_resource"] == "cpu"
            else [
                {
                    "direction": "h2d",
                    "execution_id": dispatch["parent_execution_id"],
                    "stage": dispatch["branch"],
                },
                {
                    "direction": "d2h",
                    "execution_id": dispatch["postprocess_execution_id"],
                    "stage": f"postprocess_{dispatch['branch']}",
                },
            ]
        )
        result = self._result_common(dispatch, endpoint)
        result.update(
            {
                "inference_performed": True,
                "request": request,
                "response": checked_response,
                "output_byte_length": len(output),
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "resource": resource_receipt,
                "cuda_interval_bindings": cuda_interval_bindings,
                "runtime_events": [postprocess_event, terminal_event],
                "terminal_event": terminal_event,
            }
        )
        return result

    def emit_drop(
        self,
        *,
        context: Mapping[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        dispatch = _validated_context(context)
        endpoint = self._endpoint(dispatch)
        normalized_reason = _visible(reason, "OpenVINO GVA native drop reason", 256)
        _require(
            normalized_reason in NATIVE_QUEUE_DROP_REASONS,
            "OpenVINO GVA drop reason is not a verified native queue overflow",
        )
        terminal_event = self._terminal_event(
            dispatch=dispatch,
            endpoint=endpoint,
            event_kind="branch_drop",
            objects=0,
            reason=normalized_reason,
            parent_execution_id=dispatch["parent_execution_id"],
            sequence=dispatch["event_sequence"],
        )
        result = self._result_common(dispatch, endpoint)
        result.update(
            {
                "inference_performed": False,
                "request": None,
                "response": None,
                "output_byte_length": 0,
                "output_sha256": None,
                "terminal_event": terminal_event,
            }
        )
        return result


__all__ = [
    "BRIDGE_PUBLICATION_BLOCKERS",
    "ExecutionEndpoint",
    "GVA_PTS_ORIGIN",
    "GVA_SDK_BINDING",
    "GVA_TENSOR_ORIGIN",
    "NATIVE_QUEUE_DROP_REASONS",
    "OpenVINOGVAExecutionBridge",
    "expected_capability_from_binding_and_probe",
    "execution_endpoint_from_socket",
]
