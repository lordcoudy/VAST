#!/usr/bin/env python3
"""Fail-closed Savant module callback adapter for the checkpoint bridge.

This module validates native Savant frame/module identity and delegates the
already verified execution, policy, and direct-runtime protocol to the
DeepStream protocol bridge. It is an engineering bridge, not a Savant
launcher, module implementation, hardware pilot, or publication evidence.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from checkpoint_deepstream_protocol_bridge import (
    BRIDGE_SCHEMA_VERSION,
    INDEPENDENT_PROCESSES,
    NVDS_IDENTITY_KIND,
    SHARED_VIDEO_DAG,
    DeepStreamBranchExecutionResult,
    DeepStreamProtocolBridge,
)


SAVANT_VERSION = "0.5.17"
SAVANT_FRAME_IDENTITY_KIND = "savant_native_frame_identity"
SAVANT_BRIDGE_IMPLEMENTATION_STATUS = (
    "module_callback_protocol_bridge_implemented_not_launcher_or_kpp_piloted"
)
SAVANT_EVENT_ORIGIN = "savant_native_frame_callback"
_MODULE_ID_RE = re.compile(
    r"^savant-stream-(?P<stream>[0-9]+)-"
    r"(?:(?:branch-(?P<branch>plate_number|vehicle_type|damage|foreign_object))"
    r"|(?P<shared>shared-video-dag))$"
)
_IDENTITY_FIELDS = {
    "schema_version",
    "artifact_kind",
    "savant_version",
    "module_id",
    "module_frame_id",
    "event_origin",
    "admission_id",
    "input_frame_key",
    "stream_id",
    "frame_id",
    "transport_pts_ns",
    "payload_sha256",
    "nvds_source_id",
    "nvds_frame_num",
    "nvds_buf_pts_ns",
    "mux_gst_buffer_pts_ns",
    "decoder_factory",
    "decoder_gpu_id",
}
_NVDS_FIELDS = {
    "admission_id",
    "input_frame_key",
    "stream_id",
    "frame_id",
    "transport_pts_ns",
    "payload_sha256",
    "nvds_source_id",
    "nvds_frame_num",
    "nvds_buf_pts_ns",
    "mux_gst_buffer_pts_ns",
    "decoder_factory",
    "decoder_gpu_id",
}


class SavantProtocolBridgeError(RuntimeError):
    """Savant module identity or delegate binding failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantProtocolBridgeError(message)


def _exact_mapping(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    result = dict(value)
    missing = sorted(fields - set(result))
    extra = sorted(set(result) - fields)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if extra:
        details.append("extra=" + ",".join(extra))
    _require(not details, f"{label} fields drifted ({'; '.join(details)})")
    return result


def _exact_integer(value: Any, label: str) -> int:
    _require(
        type(value) is int and value >= 0,
        f"{label} must be a non-negative integer",
    )
    return int(value)


class SavantProtocolBridge:
    """Validate Savant callback identity before invoking the native bridge."""

    publication_ready = False
    accepted_evidence_written = False
    implementation_status = SAVANT_BRIDGE_IMPLEMENTATION_STATUS

    def __init__(
        self,
        *,
        module_id: str,
        stream_id: int,
        topology_kind: str,
        delegate: DeepStreamProtocolBridge,
    ) -> None:
        _require(
            isinstance(delegate, DeepStreamProtocolBridge),
            "invalid Savant bridge delegate",
        )
        match = _MODULE_ID_RE.fullmatch(str(module_id))
        _require(match is not None, "Savant module_id is outside the frozen topology")
        checked_stream = _exact_integer(stream_id, "Savant stream_id")
        _require(
            int(match.group("stream")) == checked_stream,
            "Savant module_id stream drifted",
        )
        _require(
            delegate.stream_id == checked_stream,
            "Savant/delegate stream binding drifted",
        )
        _require(
            delegate.nvds_source_id == checked_stream,
            "Savant/delegate native source binding drifted",
        )
        _require(
            delegate.worker_id == module_id,
            "Savant/delegate module identity drifted",
        )
        _require(
            delegate.topology_kind == topology_kind,
            "Savant/delegate topology drifted",
        )
        if topology_kind == SHARED_VIDEO_DAG:
            _require(match.group("shared") is not None, "shared Savant module_id drifted")
            _require(delegate.branch_id is None, "shared Savant delegate binds one branch")
        elif topology_kind == INDEPENDENT_PROCESSES:
            _require(
                match.group("branch") is not None,
                "baseline Savant module_id lacks branch",
            )
            _require(
                delegate.branch_id == match.group("branch"),
                "baseline Savant module/delegate branch drifted",
            )
        else:
            raise SavantProtocolBridgeError("unsupported Savant topology")
        self.module_id = str(module_id)
        self.stream_id = checked_stream
        self.topology_kind = topology_kind
        self.delegate = delegate

    def _nvds_identity(self, value: Mapping[str, Any]) -> dict[str, Any]:
        identity = _exact_mapping(value, _IDENTITY_FIELDS, "Savant frame identity")
        _require(
            identity["schema_version"] == BRIDGE_SCHEMA_VERSION,
            "Savant frame identity schema drifted",
        )
        _require(
            identity["artifact_kind"] == SAVANT_FRAME_IDENTITY_KIND,
            "Savant frame identity kind drifted",
        )
        _require(identity["savant_version"] == SAVANT_VERSION, "Savant version drifted")
        _require(identity["module_id"] == self.module_id, "Savant module identity drifted")
        _require(
            identity["event_origin"] == SAVANT_EVENT_ORIGIN,
            "Savant event is not native",
        )
        frame_id = _exact_integer(identity["frame_id"], "Savant frame_id")
        _require(
            _exact_integer(identity["module_frame_id"], "Savant module_frame_id")
            == frame_id,
            "Savant module frame does not bind NvDs frame",
        )
        _require(
            _exact_integer(identity["stream_id"], "Savant identity stream_id")
            == self.stream_id,
            "Savant frame stream drifted",
        )
        _require(
            _exact_integer(identity["nvds_source_id"], "Savant native source_id")
            == self.stream_id,
            "Savant native source identity drifted",
        )
        _require(
            identity["decoder_factory"] == "nvv4l2decoder",
            "Savant frame is not native nvv4l2decoder output",
        )
        _require(
            _exact_integer(identity["decoder_gpu_id"], "Savant decoder_gpu_id") == 0,
            "Savant decoder GPU binding drifted",
        )
        return {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "artifact_kind": NVDS_IDENTITY_KIND,
            **{field: identity[field] for field in _NVDS_FIELDS},
        }

    def admit_access_unit(self, admission_json: str, **kwargs: Any) -> None:
        self.delegate.admit_access_unit(admission_json, **kwargs)

    def admit_transport_frame(self, frame: Any, **kwargs: Any) -> None:
        self.delegate.admit_transport_frame(frame, **kwargs)

    def observe_decoded_frame(
        self,
        identity: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        self.delegate.observe_decoded_frame(self._nvds_identity(identity), **kwargs)

    def observe_preprocessed_frame(
        self,
        identity: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        self.delegate.observe_preprocessed_frame(self._nvds_identity(identity), **kwargs)

    def observe_fanout(
        self,
        identity: Mapping[str, Any],
        **kwargs: Any,
    ) -> int:
        return self.delegate.observe_fanout(self._nvds_identity(identity), **kwargs)

    def bind_branch_tensor(
        self,
        identity: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        self.delegate.bind_branch_tensor(self._nvds_identity(identity), **kwargs)

    def execute_branch(
        self,
        input_frame_key: str,
        branch: str,
        **kwargs: Any,
    ) -> DeepStreamBranchExecutionResult:
        return self.delegate.execute_branch(input_frame_key, branch, **kwargs)

    def drop_branch(
        self,
        input_frame_key: str,
        branch: str,
        **kwargs: Any,
    ) -> None:
        self.delegate.drop_branch(input_frame_key, branch, **kwargs)


__all__ = [
    "SAVANT_BRIDGE_IMPLEMENTATION_STATUS",
    "SAVANT_EVENT_ORIGIN",
    "SAVANT_FRAME_IDENTITY_KIND",
    "SAVANT_VERSION",
    "SavantProtocolBridge",
    "SavantProtocolBridgeError",
]
