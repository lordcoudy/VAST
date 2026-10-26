"""Artificial front observations recorded by the real bounded journal writer.

The caller supplies capture-plan headers with actual held startup bindings.
Native domains are independently read and replayed before their identities
are sent through the production recorder. Responses are protocol fixtures,
not physical inference or publication-campaign evidence.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from publication_guardian_operational_recorder_v1 import GuardianOperationalRecorder
from publication_operational_request_domain_v1 import (
    MAX_NATIVE_DOMAIN_BYTES_V1, MAX_NATIVE_HEADER_BYTES_V1,
    _identity as _native_file_identity, _physical_file as _native_physical_file,
    canonical_json_v1, iter_native_domain_v1, strict_json_object_v1, validate_descriptor_v1,
)
from publication_operational_request_reconciliation_v1 import _identity
from publication_physical_io_v1 import PhysicalRootCustodyV1
from publication_policy_contract import bind_native_decision_evidence, validate_decision_record
from publication_policy_projection_v1 import project_accepted_decision_v1, reconstruct_original_decision_v1


class _FixtureJournalIoErrorV1(ValueError):
    def __init__(self, primary, secondary):
        super().__init__("fixture journal I/O failed; distinct causes retained")
        self.primary, self.secondary = primary, tuple(secondary)


def _raise_fixture_journal_error_v1(primary, secondary):
    if primary is None:
        return
    if isinstance(primary, _FixtureJournalIoErrorV1):
        secondary = [*primary.secondary, *secondary]
        primary = primary.primary
    distinct = []
    for error in secondary:
        if error is not primary and not any(error is previous for previous in distinct):
            distinct.append(error)
    if distinct:
        raise _FixtureJournalIoErrorV1(primary, distinct) from primary
    raise primary


def _read_fixture_native_header_v1(path, descriptor):
    """Read only the bounded original header; the existing iterator owns replay."""
    validate_descriptor_v1(descriptor)
    if path.absolute() != Path(descriptor["path"]).absolute():
        raise ValueError("fixture native header descriptor path mismatch")
    custody, stream, fd = None, None, -1
    primary, secondary, header = None, [], None
    try:
        custody = PhysicalRootCustodyV1.open(path.parent, label="fixture native header")
        before = _native_physical_file(path)
        if not 0 < before.st_size <= MAX_NATIVE_DOMAIN_BYTES_V1 or before.st_size != descriptor["size_bytes"]:
            raise ValueError("fixture native header file size mismatch")
        _, physical_identity = custody.stat_regular_identity(path, label="fixture native header")
        if physical_identity != (before.st_dev, before.st_ino):
            raise ValueError("fixture native header custody identity changed")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
                     | getattr(os, "O_BINARY", 0))
        if _native_file_identity(before) != _native_file_identity(os.fstat(fd)):
            raise ValueError("fixture native header identity changed before read")
        # Keep raw ownership even if buffered-wrapper construction fails.
        stream = os.fdopen(fd, "rb", buffering=MAX_NATIVE_HEADER_BYTES_V1, closefd=False)
        line = stream.readline(MAX_NATIVE_HEADER_BYTES_V1 + 1)
        if not line or len(line) > MAX_NATIVE_HEADER_BYTES_V1 or not line.endswith(b"\n"):
            raise ValueError("fixture native header is oversized or truncated")
        header = strict_json_object_v1(line, max_bytes=MAX_NATIVE_HEADER_BYTES_V1)
        if canonical_json_v1(header) + b"\n" != line:
            raise ValueError("fixture native header is not canonical JSONL")
        if (_native_file_identity(before) != _native_file_identity(os.fstat(stream.fileno()))
                or _native_file_identity(before) != _native_file_identity(_native_physical_file(path))):
            raise ValueError("fixture native header identity changed during read")
        custody.verify()
    except BaseException as error:
        primary = error
    finally:
        closures = []
        if stream is not None:
            closures.append(stream.close)
        if fd >= 0:
            closures.append(lambda: os.close(fd))
        if custody is not None:
            closures.append(custody.close)
        for close in closures:
            try:
                close()
            except BaseException as error:
                if primary is None:
                    primary = error
                else:
                    secondary.append(error)
    _raise_fixture_journal_error_v1(primary, secondary)
    return header


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
    primary, secondary = None, []
    try:
        for domain in native_domains:
            descriptor = domain["descriptor"]
            path = Path(descriptor["path"])
            native_header = _read_fixture_native_header_v1(path, descriptor)
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
    except BaseException as error:
        primary = error
    finally:
        try:
            recorder.close()
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                secondary.append(error)
    _raise_fixture_journal_error_v1(primary, secondary)
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
