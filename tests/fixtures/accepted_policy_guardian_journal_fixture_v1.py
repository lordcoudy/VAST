"""Artificial front observations recorded by the real bounded journal writer.

The caller supplies capture-plan headers with actual held startup bindings.
Native domains are independently read and replayed before their identities
are sent through the production recorder. Responses are protocol fixtures,
not physical inference or publication-campaign evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from publication_guardian_operational_recorder_v1 import GuardianOperationalRecorder
from publication_operational_request_domain_v1 import canonical_json_v1, iter_native_domain_v1
from publication_operational_request_reconciliation_v1 import _identity
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_policy_contract import bind_native_decision_evidence, validate_decision_record
from publication_policy_projection_v1 import project_accepted_decision_v1, reconstruct_original_decision_v1


def write_fixture_guardian_operational_journals_v1(
    *,
    output_dir: Path,
    headers_by_route: Mapping[str, Mapping[str, Any]],
    native_domains: Sequence[Mapping[str, Any]],
    capability_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Record every complete original native occurrence, not only pilot rows."""
    headers = {tuple(route.split(":")): header for route, header in headers_by_route.items()}
    request_counts = {route: 0 for route in headers_by_route}
    connections = 0
    per_operation: list[dict[str, Any]] = []

    def original_authority(record: Mapping[str, Any]) -> None:
        accepted = record["accepted_record"]
        assessment = validate_decision_record(accepted, capability_manifest)
        if not assessment["passed"]:
            raise ValueError(f"fixture original authority refused: {assessment}")
        projected = project_accepted_decision_v1(
            accepted, canonical_trace_id=accepted["trace_id"],
            publication_decision_seq=accepted["decision_seq"],
            issued_record_sha256=record["issued_record_sha256"],
        )
        original, issued = reconstruct_original_decision_v1(projected)
        if canonical_json_v1(original) != canonical_json_v1(accepted):
            raise ValueError("fixture original inverse binding drifted")
        rebound = bind_native_decision_evidence(issued, accepted["native_decision_evidence"], capability_manifest)
        if rebound["sha256"] != record["accepted_record_sha256"]:
            raise ValueError("fixture original capability binding drifted")

    recorder = GuardianOperationalRecorder(output_dir, headers)
    try:
        for domain in native_domains:
            descriptor = domain["descriptor"]
            path = Path(descriptor["path"])
            with path.open("rb") as stream:
                native_header = json.loads(stream.readline())
            route_connections: dict[str, int] = {}
            local_sequences: dict[str, int] = {}
            count = measured = 0
            for record in iter_native_domain_v1(path, expected_descriptor=descriptor, original_authority_validator=original_authority):
                identity = _identity(record, native_header, headers_by_route)
                route = f"{identity['branch']}:{identity['resource']}"
                if route not in route_connections:
                    connections += 1
                    route_connections[route] = connections
                    local_sequences[route] = 0
                local_sequences[route] += 1
                frame = {
                    "input_frame_key": identity["input_frame_key"], "stream_id": identity["stream_id"],
                    "frame_id": identity["frame_id"], "transport_pts_ns": identity["transport_pts_ns"],
                    "branch": identity["branch"],
                }
                message = {
                    "schema_version": 1, "message_type": identity["protocol"],
                    "run_id": identity["run_id"], "arm_id": identity["arm_id"],
                    "request_id": identity["request_id"], "frame": frame,
                }
                native = identity["protocol"] == "analytics_execute"
                if native:
                    message["gstreamer_worker_id"] = identity["worker_id"]
                    message["decision"] = {"decision_id": identity["decision_id"], "selected_resource": identity["resource"]}
                else:
                    message["worker_id"] = identity["worker_id"]
                    message["engine"] = "openvino_cpu" if identity["resource"] == "cpu" else "tensorrt_cuda"
                token = recorder.begin(message, (identity["branch"], identity["resource"]),
                                       "gstreamer" if native else "worker",
                                       route_connections[route], local_sequences[route])
                recorder.terminal(token, {"fixture_response": True, "request_id": identity["request_id"]},
                                  outcome="completed", send="sent")
                request_counts[route] += 1
                count += 1
                measured += int(record["measurement"])
            per_operation.append({"operation_id": domain["operation_id"], "request_count": count, "measurement_count": measured})
        total = sum(request_counts.values())
        counters = {"requests_started": total, "requests_completed": total, "requests_failed": 0,
                    "connections_accepted": connections, "requests_by_worker": request_counts}
        descriptor = recorder.finish(counters)
    finally:
        recorder.close()
    companion = Path(descriptor["path"])
    with PhysicalRootCustodyV1.open(companion.parent, label="fixture guardian companion") as custody:
        observed, _ = custody.read_descriptor(companion, label="fixture guardian companion",
            maximum=1024**2, capture=False)
        custody.verify()
    if observed["size_bytes"] != descriptor["size_bytes"] or observed["sha256"] != descriptor["sha256"]:
        raise ValueError("fixture guardian group descriptor changed")
    return {
        "operational_group": descriptor, "lifecycle_counters": counters,
        "per_operation": per_operation,
        "limits": {"campaign_authority": False, "physical_inference_observed": False,
                   "response_scope": "artificial_front_protocol_observations"},
    }
