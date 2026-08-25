#!/usr/bin/env python3
"""Bind genuine Savant callbacks to exact CPU/TensorRT execution endpoints."""
from __future__ import annotations

import math
import os
import socket
from collections.abc import Mapping
from typing import Any

from checkpoint_deepstream_protocol_adapter import (
    BRANCHES,
    RESOURCES,
    DeepStreamProtocolCallbacks,
    _absolute_path,
    _connect_seqpacket,
    _load_json,
    validate_adapter_config,
)


CONFIG_ENV = "VAST_SAVANT_ADAPTER_CONFIG"
DEADLINE_ENV = "VAST_SAVANT_DEADLINE_MS"
CONFIG_KIND = "vast_deepstream_protocol_adapter_config"
CLAIM_STATUS = "native_savant_sdk_adapter_requires_external_acceptance"


class SavantProtocolAdapterV3Error(RuntimeError):
    """The exact Savant-to-execution adapter binding failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SavantProtocolAdapterV3Error(message)


def create_savant_callbacks(
    *,
    context: Mapping[str, Any],
    event_sink: Any,
    policy_exchange: Any,
    resource_recorder: Any,
) -> DeepStreamProtocolCallbacks:
    """Create direct, handshaken CPU/TensorRT endpoints for one Savant module."""

    config_value = os.environ.get(CONFIG_ENV, "").strip()
    _require(bool(config_value), f"required Savant environment is missing: {CONFIG_ENV}")
    config_path = _absolute_path(config_value, "Savant adapter config")
    config = validate_adapter_config(_load_json(config_path, "Savant adapter config"))
    branches = tuple(str(value) for value in context.get("branches") or ())
    _require(
        tuple(value for value in BRANCHES if value in branches) == branches,
        "Savant context branch order drifted",
    )
    _require(
        set(branches) <= set(config["branches"]),
        "Savant adapter config does not cover process branches",
    )

    from analytics_execution_endpoint import (
        expected_capability_from_binding_and_probe,
    )
    from analytics_execution_worker import ExecutionClient
    from checkpoint_deepstream_protocol_bridge import (
        DeepStreamExecutionEndpoint,
        DeepStreamProtocolBridge,
    )
    from checkpoint_gstreamer_analytics_bridge import preprocess_gstreamer_frame
    from checkpoint_model_parity import load_parity_manifest
    from checkpoint_savant_protocol_bridge import SavantProtocolBridge

    manifest_path = _absolute_path(
        config["preprocessing_manifest_path"], "Savant preprocessing manifest"
    )
    manifest = load_parity_manifest(manifest_path)
    _require(
        manifest.get("schema_version") == 3
        and manifest.get("artifact_kind")
        == "checkpoint_analytics_model_parity_manifest",
        "Savant preprocessing manifest contract drifted",
    )
    preprocessing = dict(manifest["preprocessing_contract"])
    sockets: list[socket.socket] = []
    endpoints: dict[str, dict[str, Any]] = {}
    input_bindings: dict[str, dict[str, Any]] = {}
    try:
        for branch in branches:
            endpoints[branch] = {}
            for resource in RESOURCES:
                record = config["branches"][branch][resource]
                binding = _load_json(
                    _absolute_path(
                        record["binding_path"], f"{branch}/{resource} binding"
                    ),
                    f"{branch}/{resource} binding",
                )
                probe = _load_json(
                    _absolute_path(
                        record["runtime_probe_path"],
                        f"{branch}/{resource} runtime probe",
                    ),
                    f"{branch}/{resource} runtime probe",
                )
                capability = expected_capability_from_binding_and_probe(
                    binding=binding,
                    runtime_probe=probe,
                    resource=resource,
                )
                endpoint_socket = _connect_seqpacket(record["socket_path"])
                sockets.append(endpoint_socket)
                client = ExecutionClient(
                    endpoint_socket, expected_capability=capability
                )
                _require(
                    client.handshake() == capability,
                    f"{branch}/{resource} capability handshake drifted",
                )
                endpoints[branch][resource] = DeepStreamExecutionEndpoint(
                    resource=resource,
                    implementation_id=record["implementation_id"],
                    capability=capability,
                    client=client,
                )
                contract = {
                    "input": dict(binding["input"]),
                    "preprocessing_contract_sha256": binding[
                        "preprocessing_contract_sha256"
                    ],
                }
                if branch in input_bindings:
                    _require(
                        input_bindings[branch] == contract,
                        f"{branch}: CPU/GPU input contracts differ",
                    )
                else:
                    input_bindings[branch] = contract

        delegate = DeepStreamProtocolBridge(
            run_id=str(context["run_id"]),
            arm_id=str(context["arm_id"]),
            worker_id=str(context["worker_id"]),
            topology_kind=str(context["topology_kind"]),
            stream_id=int(context["stream_id"]),
            branch_id=branches[0] if len(branches) == 1 else None,
            event_sink=event_sink,
            policy_exchange=policy_exchange,
            analytics_endpoints=endpoints,
            resource_recorder=resource_recorder,
        )
        bridge = SavantProtocolBridge(
            module_id=str(context["worker_id"]),
            stream_id=int(context["stream_id"]),
            topology_kind=str(context["topology_kind"]),
            delegate=delegate,
        )
        deadline_ms = float(os.environ.get(DEADLINE_ENV, ""))
        _require(
            math.isfinite(deadline_ms) and deadline_ms > 0,
            "Savant deadline is invalid",
        )
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
            try:
                endpoint.close()
            except OSError:
                pass
        raise


__all__ = [
    "CLAIM_STATUS",
    "CONFIG_ENV",
    "DEADLINE_ENV",
    "SavantProtocolAdapterV3Error",
    "create_savant_callbacks",
]
