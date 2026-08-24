#!/usr/bin/env python3
"""Pure, permanently blocked execution plan for GStreamer publication arms."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any, Mapping

from backend_publication_output_receipt import (
    BackendPublicationOutputReceiptError,
    validate_backend_publication_arm_contract,
)
from backend_publication_runtime_authority import (
    BackendPublicationRuntimeAuthorityError,
    validate_backend_publication_runtime_authority,
)


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_checkpoint_gstreamer_publication_execution_plan"
SYSTEM = "gstreamer_custom"
_SCENARIO_TO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
_BASE_BLOCKERS = frozenset({
    "runtime_authority_not_integrated_into_arm_contract_or_backend_grant",
    "gstreamer_publication_launcher_still_fail_closed",
    "real_kpp_hardware_execution_not_performed",
    "physical_kpp_dataset_and_source_not_verified",
    "physical_policy_capability_and_calibration_not_verified",
    "live_analytics_socket_endpoint_not_bound_or_peer_verified",
})


class CheckpointGstreamerPublicationPlanError(RuntimeError):
    """Arm and runtime authority cannot form one closed GStreamer plan."""


def _canonical_sha(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CheckpointGstreamerPublicationPlanError(
            "GStreamer publication plan is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def build_checkpoint_gstreamer_publication_plan(
    arm_contract: Mapping[str, Any],
    runtime_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Crosscheck immutable inputs and return a non-executable closed plan.

    This function performs content validation only.  Physical runtime authority
    assessment belongs upstream; no backend, socket, KPP source, or filesystem
    operation is performed here.
    """
    try:
        arm = validate_backend_publication_arm_contract(
            copy.deepcopy(dict(arm_contract))
        )
    except (BackendPublicationOutputReceiptError, TypeError, ValueError) as error:
        raise CheckpointGstreamerPublicationPlanError(
            f"backend publication arm contract is invalid: {error}"
        ) from error
    runtime = arm["runtime_inputs"]
    dispatch = arm["dispatch_resolution"]
    try:
        authority = validate_backend_publication_runtime_authority(
            copy.deepcopy(dict(runtime_authority)),
            expected_system=SYSTEM,
            expected_policy=runtime["policy"],
            expected_topology_kind=runtime["topology_kind"],
            expected_codec=runtime["codec"],
        )
    except (BackendPublicationRuntimeAuthorityError, TypeError, ValueError) as error:
        raise CheckpointGstreamerPublicationPlanError(
            f"backend runtime authority cross-dispatch is invalid: {error}"
        ) from error
    if runtime["system"] != SYSTEM or dispatch["system"] != SYSTEM:
        raise CheckpointGstreamerPublicationPlanError(
            "GStreamer plan received another system coordinate"
        )
    expected_topology = _SCENARIO_TO_TOPOLOGY.get(runtime["scenario"])
    if expected_topology != runtime["topology_kind"]:
        raise CheckpointGstreamerPublicationPlanError(
            "GStreamer scenario/topology coordinate is replayed or mismatched"
        )
    if (
        authority["model_parity_acceptance_binding_sha256"]
        != arm["model_parity_acceptance_binding_sha256"]
    ):
        raise CheckpointGstreamerPublicationPlanError(
            "runtime authority/arm parity acceptance identity drifted"
        )
    deadline = runtime["deadline_ms"]
    if isinstance(deadline, bool) or not math.isfinite(float(deadline)):
        raise CheckpointGstreamerPublicationPlanError(
            "GStreamer deadline coordinate is invalid"
        )
    blockers = set(_BASE_BLOCKERS)
    if runtime["policy"] == "cpu_only":
        blockers.add("gstreamer_cpu_native_accepted_run_not_performed")
    else:
        blockers.add(
            "gstreamer_non_cpu_policy_requires_frozen_tensorrt_cuda_parity_bindings"
        )
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "executable": False,
        "arm_contract_sha256": arm["contract_sha256"],
        "runtime_authority_sha256": authority["authority_sha256"],
        "full_publication_execution_binding": copy.deepcopy(
            arm["full_publication_execution_binding"]
        ),
        "coordinate": {
            "system": runtime["system"],
            "scenario": runtime["scenario"],
            "topology_kind": runtime["topology_kind"],
            "codec": runtime["codec"],
            "policy": runtime["policy"],
            "deadline_ms": deadline,
        },
        "common_identities": {
            "backend_runtime_grant_sha256": arm[
                "backend_runtime_grant_sha256"
            ],
            "resource_capability_grant_sha256": arm[
                "resource_capability_grant_sha256"
            ],
            "model_parity_grant_sha256": arm["model_parity_grant_sha256"],
            "model_parity_acceptance_binding_sha256": arm[
                "model_parity_acceptance_binding_sha256"
            ],
            "identity_artifact_binding_sha256": arm[
                "identity_artifact_binding_sha256"
            ],
            "runtime_binding_identity_sha256": dispatch[
                "runtime_binding_identity_sha256"
            ],
            "cell_identity_sha256": dispatch["cell_identity_sha256"],
        },
        "inputs": {
            "dataset": copy.deepcopy(runtime["dataset"]),
            "streams": runtime["streams"],
            "duration_s": runtime["duration_s"],
            "run_id": runtime["run_id"],
            "output_dir": runtime["output_dir"],
        },
        "runtime_contract": {
            "cohort_topology_plan": copy.deepcopy(
                authority["cohort_topology_plan"]
            ),
            "system_specific_launcher_input": copy.deepcopy(
                authority["system_specific_launcher_input"]
            ),
        },
        "blockers": sorted(blockers),
    }
    material["plan_sha256"] = _canonical_sha(material)
    return material


__all__ = [
    "ARTIFACT_KIND", "SCHEMA_VERSION",
    "CheckpointGstreamerPublicationPlanError",
    "build_checkpoint_gstreamer_publication_plan",
]
