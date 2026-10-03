#!/usr/bin/env python3
"""Fail-closed DeepStream SDK callback adapter for protocol-v3 execution.

The module is the launcher-visible factory that was previously missing.  It
maps an SDK-owned system-memory RGB ``GstSample`` into the frozen preprocessing
contract, binds the resulting tensor to the native NvDs identity, and executes
the already-attested CPU/TensorRT endpoint selected by the inherited policy
socket.  It does not spawn workers or create accepted benchmark evidence.
"""
from __future__ import annotations

import json
import math
import os
import socket
import stat
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


CONFIG_ENV = "VAST_DEEPSTREAM_ADAPTER_CONFIG"
CONFIG_KIND = "vast_deepstream_protocol_adapter_config"
CONFIG_CLAIM_STATUS = "native_sdk_adapter_requires_external_acceptance"
RESOURCES = ("cpu", "gpu")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
ANALYTICS_EXECUTION_TRANSPORT_TIMEOUT_NS = 300_000_000_000
_CONFIG_FIELDS = {
    "schema_version",
    "artifact_kind",
    "claim_status",
    "preprocessing_manifest_path",
    "branches",
}
_ENDPOINT_FIELDS = {
    "implementation_id",
    "socket_path",
    "binding_path",
    "runtime_probe_path",
}


class DeepStreamProtocolAdapterError(RuntimeError):
    """Adapter configuration, sample ownership, or endpoint binding failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeepStreamProtocolAdapterError(message)


def _exact_mapping(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    result = dict(value)
    _require(set(result) == fields, f"{label} fields have drifted")
    return result


def _visible_text(value: Any, label: str) -> str:
    result = str(value or "")
    _require(
        bool(result)
        and "\x00" not in result
        and all(ord(character) >= 0x20 and ord(character) != 0x7F for character in result),
        f"{label} is invalid",
    )
    return result


def _absolute_path(value: Any, label: str) -> Path:
    raw = _visible_text(value, label)
    path = Path(raw)
    _require(path.is_absolute(), f"{label} must be absolute")
    lexical = Path(os.path.abspath(os.fspath(path)))
    resolved = path.resolve()
    _require(
        lexical == resolved and not path.is_symlink() and resolved.is_file(),
        f"{label} is missing, a symlink, or an alias",
    )
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeepStreamProtocolAdapterError(f"{label} is not valid JSON: {exc}") from exc
    _require(isinstance(value, Mapping), f"{label} must contain a JSON object")
    return dict(value)


def validate_adapter_config(value: Any) -> dict[str, Any]:
    config = _exact_mapping(value, _CONFIG_FIELDS, "DeepStream adapter config")
    _require(config["schema_version"] == 1, "DeepStream adapter config schema drifted")
    _require(config["artifact_kind"] == CONFIG_KIND, "DeepStream adapter config kind drifted")
    _require(
        config["claim_status"] == CONFIG_CLAIM_STATUS,
        "DeepStream adapter config claim status drifted",
    )
    _visible_text(config["preprocessing_manifest_path"], "preprocessing manifest path")
    raw_branches = config["branches"]
    _require(isinstance(raw_branches, Mapping), "DeepStream adapter branches are missing")
    _require(bool(raw_branches) and set(raw_branches) <= set(BRANCHES), "DeepStream adapter branch set is invalid")
    branches: dict[str, dict[str, dict[str, str]]] = {}
    for branch, raw_resources in raw_branches.items():
        _require(isinstance(raw_resources, Mapping), f"{branch}: endpoint resources are missing")
        _require(set(raw_resources) == set(RESOURCES), f"{branch}: exact CPU/GPU endpoints are required")
        resources: dict[str, dict[str, str]] = {}
        for resource in RESOURCES:
            endpoint = _exact_mapping(
                raw_resources[resource], _ENDPOINT_FIELDS, f"{branch}/{resource} endpoint"
            )
            resources[resource] = {
                field: _visible_text(endpoint[field], f"{branch}/{resource} {field}")
                for field in _ENDPOINT_FIELDS
            }
        branches[str(branch)] = resources
    return {
        **config,
        "preprocessing_manifest_path": str(config["preprocessing_manifest_path"]),
        "branches": branches,
    }


def _connect_seqpacket(path_value: str) -> socket.socket:
    _require(hasattr(socket, "SOCK_SEQPACKET"), "SOCK_SEQPACKET is unavailable")
    _require(path_value.startswith("/"), "analytics endpoint socket path must be absolute POSIX")
    _require("\x00" not in path_value and len(os.fsencode(path_value)) < 108, "analytics endpoint socket path is invalid")
    path = Path(path_value)
    _require(path.exists() and not path.is_symlink(), "analytics endpoint socket is missing or a symlink")
    mode = os.lstat(path).st_mode
    _require(stat.S_ISSOCK(mode), "analytics endpoint path is not a socket")
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        endpoint.connect(path_value)
        return endpoint
    except BaseException:
        endpoint.close()
        raise


def _structure_integer(structure: Any, name: str) -> int:
    value = structure.get_value(name)
    _require(type(value) is int and value > 0, f"DeepStream RGB caps {name} is invalid")
    return int(value)


def _gst_map_read_flag() -> Any:
    """Resolve the GI enum object required by Gst.Buffer.map()."""

    try:
        import gi  # type: ignore

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore
    except Exception as exc:
        raise DeepStreamProtocolAdapterError(
            "DeepStream GStreamer bindings are unavailable"
        ) from exc
    return Gst.MapFlags.READ


class DeepStreamProtocolCallbacks:
    """Direct SDK callback surface consumed by ``DeepStreamSdkPipeline``."""

    def __init__(
        self,
        *,
        bridge: Any,
        input_bindings: Mapping[str, Mapping[str, Any]],
        preprocessing_contract: Mapping[str, Any],
        preprocess: Callable[..., tuple[bytes, dict[str, Any]]],
        deadline_ms: float,
        sockets: tuple[socket.socket, ...] = (),
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        gst_map_read_flag: Any | None = None,
        rgb_sample_pts_field: str = "mux_gst_buffer_pts_ns",
    ) -> None:
        _require(callable(preprocess), "DeepStream preprocessing callback is missing")
        _require(math.isfinite(deadline_ms) and deadline_ms > 0, "DeepStream deadline is invalid")
        _require(bool(input_bindings), "DeepStream input binding set is empty")
        _require(
            rgb_sample_pts_field in {"mux_gst_buffer_pts_ns", "nvds_buf_pts_ns"},
            "native RGB sample PTS identity field is invalid",
        )
        # nvstreamdemux restores per-frame PTS; a non-demuxed DeepStream
        # sample still carries the batched mux PTS. Both observations remain
        # in the unmodified identity sent to the bridge.
        self._rgb_sample_pts_field = rgb_sample_pts_field
        self._bridge = bridge
        self._input_bindings = {str(key): dict(value) for key, value in input_bindings.items()}
        self._preprocessing_contract = dict(preprocessing_contract)
        self._preprocess = preprocess
        # The benchmark SLO remains bound in the policy/runtime evidence.  The
        # worker protocol deadline is an operational anti-hang bound and must
        # not turn an ordinary benchmark SLO miss into an unreportable RPC
        # rejection before a native terminal can be emitted.
        self._execution_transport_timeout_ns = ANALYTICS_EXECUTION_TRANSPORT_TIMEOUT_NS
        self._sockets = sockets
        self._monotonic_ns = monotonic_ns
        self._gst_map_read_flag = (
            _gst_map_read_flag() if gst_map_read_flag is None else gst_map_read_flag
        )

    def admit_transport_frame(self, frame: Any, *, observed_timestamp_ms: int) -> None:
        self._bridge.admit_transport_frame(frame, observed_timestamp_ms=observed_timestamp_ms)

    def observe_decoded_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None:
        self._bridge.observe_decoded_frame(identity, observed_timestamp_ms=observed_timestamp_ms)

    def observe_preprocessed_frame(self, identity: Mapping[str, Any], *, observed_timestamp_ms: int) -> None:
        self._bridge.observe_preprocessed_frame(identity, observed_timestamp_ms=observed_timestamp_ms)

    def observe_fanout(self, identity: Mapping[str, Any], *, branch: str, observed_timestamp_ms: int) -> int:
        return self._bridge.observe_fanout(
            identity,
            branch=branch,
            observed_timestamp_ms=observed_timestamp_ms,
        )

    def execute_branch_sample(self, identity: Mapping[str, Any], *, branch: str, sample: Any) -> None:
        binding = self._input_bindings.get(branch)
        _require(binding is not None, "DeepStream sample branch has no frozen input binding")
        caps = sample.get_caps()
        _require(caps is not None and caps.get_size() == 1, "DeepStream sample caps are missing or ambiguous")
        structure = caps.get_structure(0)
        _require(structure is not None and structure.get_name() == "video/x-raw", "DeepStream sample caps are not raw video")
        _require(structure.get_value("format") == "RGB", "DeepStream sample is not system-memory RGB")
        width = _structure_integer(structure, "width")
        height = _structure_integer(structure, "height")
        buffer = sample.get_buffer()
        _require(buffer is not None, "DeepStream sample has no GstBuffer")
        _require(
            int(buffer.pts) == int(identity[self._rgb_sample_pts_field]),
            f"DeepStream RGB GstBuffer PTS drifted from {self._rgb_sample_pts_field}",
        )
        mapped, map_info = buffer.map(self._gst_map_read_flag)
        _require(mapped, "DeepStream RGB GstBuffer read map failed")
        try:
            payload = bytes(map_info.data)
        finally:
            buffer.unmap(map_info)
        _require(len(payload) > 0 and len(payload) % height == 0, "DeepStream RGB GstBuffer stride is invalid")
        stride = len(payload) // height
        _require(stride >= width * 3, "DeepStream RGB GstBuffer row is truncated")
        tensor, descriptor = self._preprocess(
            payload,
            frame={"format": "RGB", "width": width, "height": height, "stride": stride},
            preprocessing_contract=self._preprocessing_contract,
            expected_contract_sha256=str(binding["preprocessing_contract_sha256"]),
            tensor_name=str(binding["input"]["name"]),
        )
        for field in ("name", "dtype", "layout", "shape"):
            _require(descriptor[field] == binding["input"][field], f"DeepStream tensor {field} differs from frozen binding")
        self._bridge.bind_branch_tensor(identity, branch=branch, tensor_spec=descriptor)
        self._bridge.execute_branch(
            str(identity["input_frame_key"]),
            branch,
            tensor_payload=tensor,
            queue_depths={"cpu": 0, "gpu": 0},
            deadline_monotonic_ns=(
                self._monotonic_ns() + self._execution_transport_timeout_ns
            ),
        )

    def drop_branch(
        self,
        input_frame_key: str,
        branch: str,
        *,
        reason: str,
        observed_timestamp_ms: int,
    ) -> None:
        self._bridge.drop_branch(
            input_frame_key,
            branch,
            reason=reason,
            observed_timestamp_ms=observed_timestamp_ms,
        )

    def close(self) -> None:
        for endpoint in self._sockets:
            try:
                endpoint.close()
            except OSError:
                pass


def create_callbacks(*, context: Mapping[str, Any], event_sink: Any, policy_exchange: Any) -> DeepStreamProtocolCallbacks:
    """Build real CPU/TensorRT endpoints from one launcher-owned exact config."""

    config_value = os.environ.get(CONFIG_ENV, "").strip()
    _require(bool(config_value), f"required DeepStream environment is missing: {CONFIG_ENV}")
    config_path = _absolute_path(config_value, "DeepStream adapter config")
    config = validate_adapter_config(_load_json(config_path, "DeepStream adapter config"))
    branches = tuple(str(value) for value in context.get("branches") or ())
    _require(tuple(value for value in BRANCHES if value in branches) == branches, "DeepStream context branch order drifted")
    _require(
        set(branches) <= set(config["branches"]),
        "DeepStream adapter config does not cover process branches",
    )

    # These imports are deliberately deferred so importing the SDK runtime does
    # not require Linux-only memfd/fcntl or GI bindings.
    from analytics_execution_worker import ExecutionClient
    from checkpoint_deepstream_protocol_bridge import (
        DeepStreamExecutionEndpoint,
        DeepStreamProtocolBridge,
    )
    from checkpoint_gstreamer_analytics_bridge import preprocess_gstreamer_frame
    from analytics_execution_endpoint import expected_capability_from_binding_and_probe

    manifest_path = _absolute_path(
        config["preprocessing_manifest_path"], "DeepStream preprocessing manifest"
    )
    sockets: list[socket.socket] = []
    endpoints: dict[str, dict[str, Any]] = {}
    input_bindings: dict[str, dict[str, Any]] = {}
    try:
        for branch in branches:
            endpoints[branch] = {}
            for resource in RESOURCES:
                record = config["branches"][branch][resource]
                binding = _load_json(
                    _absolute_path(record["binding_path"], f"{branch}/{resource} binding"),
                    f"{branch}/{resource} binding",
                )
                probe = _load_json(
                    _absolute_path(record["runtime_probe_path"], f"{branch}/{resource} runtime probe"),
                    f"{branch}/{resource} runtime probe",
                )
                capability = expected_capability_from_binding_and_probe(
                    binding=binding,
                    runtime_probe=probe,
                    resource=resource,
                )
                endpoint_socket = _connect_seqpacket(record["socket_path"])
                sockets.append(endpoint_socket)
                client = ExecutionClient(endpoint_socket, expected_capability=capability)
                observed = client.handshake()
                _require(observed == capability, f"{branch}/{resource} capability handshake drifted")
                endpoints[branch][resource] = DeepStreamExecutionEndpoint(
                    resource=resource,
                    implementation_id=record["implementation_id"],
                    capability=capability,
                    client=client,
                )
                if branch not in input_bindings:
                    input_bindings[branch] = {
                        "input": dict(binding["input"]),
                        "preprocessing_contract_sha256": binding[
                            "preprocessing_contract_sha256"
                        ],
                    }
                else:
                    _require(
                        input_bindings[branch]
                        == {
                            "input": dict(binding["input"]),
                            "preprocessing_contract_sha256": binding[
                                "preprocessing_contract_sha256"
                            ],
                        },
                        f"{branch}: CPU/GPU input contracts differ",
                    )
        preprocessing_hashes = {
            str(value["preprocessing_contract_sha256"])
            for value in input_bindings.values()
        }
        _require(
            len(preprocessing_hashes) == 1,
            "DeepStream branches do not share one preprocessing contract",
        )
        from checkpoint_model_parity import load_parity_preprocessing_contract

        preprocessing = load_parity_preprocessing_contract(
            manifest_path,
            expected_sha256=next(iter(preprocessing_hashes)),
        )
        bridge = DeepStreamProtocolBridge(
            run_id=str(context["run_id"]),
            arm_id=str(context["arm_id"]),
            worker_id=str(context["worker_id"]),
            topology_kind=str(context["topology_kind"]),
            stream_id=int(context["stream_id"]),
            branch_id=branches[0] if len(branches) == 1 else None,
            event_sink=event_sink,
            policy_exchange=policy_exchange,
            analytics_endpoints=endpoints,
            resource_recorder=context.get("resource_recorder"),
        )
        deadline_ms = float(os.environ.get("VAST_DEEPSTREAM_DEADLINE_MS", ""))
        return DeepStreamProtocolCallbacks(
            bridge=bridge,
            input_bindings=input_bindings,
            preprocessing_contract=preprocessing,
            preprocess=preprocess_gstreamer_frame,
            deadline_ms=deadline_ms,
            sockets=tuple(sockets),
        )
    except BaseException:
        for endpoint in sockets:
            endpoint.close()
        raise


__all__ = [
    "CONFIG_CLAIM_STATUS",
    "CONFIG_ENV",
    "CONFIG_KIND",
    "DeepStreamProtocolAdapterError",
    "DeepStreamProtocolCallbacks",
    "create_callbacks",
    "validate_adapter_config",
]
