"""Actual guardian protocol/custody around explicitly artificial fixture peers.

No production reader is replaced. Input authority must be loaded by the caller
from its genuine upstream graph. Local protocol responders are not physical
workers, inference evidence, Docker custody, or campaign qualification authority.
"""

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time
import uuid
from typing import Any, Mapping

import checkpoint_gstreamer_analytics_sidecar as sidecar
from analytics_execution_protocol import canonical_json_bytes, canonical_sha256, close_fds, receive_packet, send_packet
from analytics_execution_worker import ExecutionClient, _hello_ack, _validate_hello, validate_worker_capability
from publication_policy_qualification_execution_closure_v1 import _independent_validate_guardian_documents


LIMITS = {"campaign_authority": False, "physical_inference_observed": False,
    "physical_worker_observed": False, "real_docker_qualification": False,
    "protocol_peer": "artificial_local_fixture_responder"}


def _fresh_artifact(root: Path, path: Path) -> Path:
    value = path.absolute()
    if value.resolve(strict=False) != value or not value.is_relative_to(root) or os.path.lexists(value):
        raise ValueError("fixture artifact must be fresh and canonical inside project root")
    return value


def _write_document(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as destination:
        destination.write(raw)
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _identity(core: Mapping[str, Any]) -> dict[str, Any]:
    return {**core, "identity": {"algorithm": "sha256", "sha256": canonical_sha256(core)}}


def _socket_path(endpoint: socket.socket) -> Path:
    if endpoint.family != socket.AF_UNIX or endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_SEQPACKET:
        raise ValueError("fixture guardian requires held AF_UNIX SOCK_SEQPACKET endpoints")
    path = Path(endpoint.getsockname())
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise ValueError("fixture socket path must be canonical and already bound")
    sidecar._assert_live_production_socket_pin(sidecar._production_socket_pin(path))
    return path


def _observed_fixture_peer(route: socket.socket, path: Path, capability: Mapping[str, Any]) -> dict[str, Any]:
    route.listen(1)
    route.settimeout(2.0)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    client.settimeout(2.0)
    errors = []
    connection = None
    thread = None
    try:
        client.connect(str(path))
        connection, _ = route.accept()
        connection.settimeout(2.0)
        raw = sidecar._peer_credentials_raw(connection)
        peer_pid, _, _ = struct.unpack("3i", raw)
        peer = sidecar._select_peer_identity(peer_raw=raw, docker_state_pid=peer_pid,
            runtime_platform=None, runtime_custody=None)

        def respond():
            try:
                hello, descriptors = receive_packet(connection, expected_fds=0)
                close_fds(descriptors)
                checked = _validate_hello(hello, capability)
                send_packet(connection, _hello_ack(capability, checked["nonce"]))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=respond, name="fixture-worker-handshake", daemon=True)
        thread.start()
        if ExecutionClient(client, expected_capability=capability).handshake() != dict(capability):
            raise ValueError("fixture capability handshake changed its real input")
        thread.join(3.0)
        if thread.is_alive() or errors:
            raise RuntimeError("fixture worker handshake did not terminate cleanly") from (errors[0] if errors else None)
        return peer
    finally:
        client.close()
        if connection is not None:
            connection.close()
        if thread is not None:
            thread.join(3.0)


@dataclass
class FixtureGuardianLifecycleV1:
    authority: dict[str, Any]
    authority_descriptor: dict[str, Any]
    lifecycle_path: Path
    runtime_expectations: dict[str, Any]
    preprocessing_authority: dict[str, Any]
    front_socket: socket.socket
    control_socket: socket.socket
    route_sockets: list[tuple[Path, socket.socket]]
    stop_event: threading.Event = field(default_factory=threading.Event)
    errors: list[Exception] = field(default_factory=list)
    stop_attestation: dict[str, Any] | None = None
    thread: threading.Thread | None = None
    finished: bool = False

    @property
    def owner_process(self):
        return self.authority["owner_process"]

    @property
    def started_monotonic_ns(self):
        return self.authority["started_monotonic_ns"]

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(3.0)
        self.front_socket.close()
        self.control_socket.close()
        for _, endpoint in self.route_sockets:
            endpoint.close()
        if self.thread is not None and self.thread.is_alive():
            raise RuntimeError("fixture guardian control thread did not terminate")


def _respond_guardian_control(session: FixtureGuardianLifecycleV1):
    try:
        requests = 0
        # Real validation may run for hours; the owning lifecycle stops this responder.
        while requests < 4096:
            if session.stop_event.is_set():
                return
            try:
                connection, _ = session.control_socket.accept()
            except socket.timeout:
                continue
            requests += 1
            with connection:
                connection.settimeout(2.0)
                request, descriptors = receive_packet(connection, expected_fds=0)
                close_fds(descriptors)
                kind = request.get("message_type")
                fields = {"schema_version", "message_type", "lifecycle_id", "service_authority_sha256", "nonce"}
                if kind == "production_guardian_stop":
                    fields.add("canonical_command_sha256")
                if (set(request) != fields or request.get("schema_version") != 1
                        or request.get("lifecycle_id") != session.authority["lifecycle_id"]
                        or request.get("service_authority_sha256") != session.authority["service_authority_sha256"]):
                    raise ValueError("fixture guardian control binding drifted")
                if kind == "production_guardian_status":
                    send_packet(connection, {"schema_version": 1, "message_type": "production_guardian_status_response",
                        "nonce": request["nonce"], "authority": session.authority})
                elif kind == "production_guardian_stop":
                    pid, uid, gid = struct.unpack("3i", sidecar._peer_credentials_raw(connection))
                    session.stop_attestation = sidecar._build_guardian_stop_attestation_v1(request,
                        authority=session.authority, peer_pid=pid, peer_uid=uid, peer_gid=gid)
                    send_packet(connection, {**request, "message_type": "production_guardian_stop_accepted"})
                    session.stop_event.set()
                    return
                else:
                    raise ValueError("fixture guardian control message is unsupported")
        if not session.stop_event.is_set():
            raise RuntimeError("fixture guardian control request bound exceeded")
    except Exception as error:
        session.errors.append(error)
        session.stop_event.set()


def _authority_expectations(session: FixtureGuardianLifecycleV1) -> dict[str, Any]:
    runtime = session.runtime_expectations
    return {"expected_front_socket": session.authority["front_socket"]["path"],
        "expected_execution_config_identity_sha256": runtime["execution_config_identity_sha256"],
        "expected_binding_set_identity_sha256": runtime["binding_set_identity_sha256"],
        "expected_worker_image_ids": runtime["worker_image_ids"],
        "expected_preprocessing_contract_authority": session.preprocessing_authority,
        "expected_service_identity_sha256": session.authority["service_identity_sha256"],
        "expected_policy_contract_sha256": session.preprocessing_authority["policy_contract_sha256"]}


def begin_fixture_guardian_lifecycle_v1(*, project_root: Path, authority_path: Path, lifecycle_path: Path,
    front_socket: socket.socket, control_socket: socket.socket, preprocessing_authority: Mapping[str, Any],
    runtime_expectations: Mapping[str, Any], route_capabilities: Mapping[str, Mapping[str, Any]]) -> FixtureGuardianLifecycleV1:
    root = project_root.resolve(strict=True)
    readiness = _fresh_artifact(root, authority_path)
    lifecycle = _fresh_artifact(root, lifecycle_path)
    if readiness == lifecycle:
        raise ValueError("fixture authority and lifecycle outputs alias")
    preprocessing = sidecar._validate_preprocessing_authority_v1(preprocessing_authority)
    runtime = sidecar._validate_production_runtime_expectations_v1(runtime_expectations)
    expected_routes = {f"{branch}:{resource}" for branch, resource in sidecar.EXPECTED_KEYS}
    if set(route_capabilities) != expected_routes:
        raise ValueError("fixture route capabilities must cover exact eight routes")
    capabilities = {}
    for branch, resource in sidecar.EXPECTED_KEYS:
        key = f"{branch}:{resource}"
        checked = validate_worker_capability(route_capabilities[key])
        if (checked["branch"] != branch or checked["engine"] != sidecar.ENGINE_BY_RESOURCE[resource]
                or checked["worker_image_id"] != runtime["worker_image_ids"][resource]):
            raise ValueError("fixture route capability binding drifted")
        capabilities[key] = checked
    front, control = _socket_path(front_socket), _socket_path(control_socket)
    if front == control or front.parent != control.parent:
        raise ValueError("fixture sockets must have distinct names in one private native directory")
    routes = [(front.parent / f"worker-{branch}-{resource}.sock", branch, resource)
        for branch in sidecar.BRANCHES for resource in sidecar.RESOURCES]
    if any(os.path.lexists(path) or len(os.fsencode(path)) >= 108 for path, _, _ in routes):
        raise ValueError("fixture worker socket reservation is occupied or too long")
    held_routes = []
    incomplete_peers = []
    session = None
    try:
        for path, branch, resource in routes:
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            held_routes.append((path, endpoint))
            endpoint.bind(str(path))
            peer = _observed_fixture_peer(endpoint, path, capabilities[f"{branch}:{resource}"])
            incomplete_peers.append((branch, resource, peer))
        peers = []
        for branch, resource, peer in incomplete_peers:
            complete = sidecar._complete_peer_identity_after_handshake(peer)
            peers.append({"branch": branch, "resource": resource,
                "worker_image_id": runtime["worker_image_ids"][resource], "peer_identity": complete,
                "peer_identity_sha256": complete["identity_sha256"]})
        authority = {"schema_version": 1, "artifact_kind": sidecar.PRODUCTION_SERVICE_AUTHORITY_KIND,
            "service_mode": sidecar.PRODUCTION_SERVICE_MODE, "status": "live_operational_nonpublication",
            "publication_ready": False, "accepted_evidence_written": False, "lifecycle_id": uuid.uuid4().hex,
            "owner_process": sidecar._production_owner_process_identity(),
            "front_socket": sidecar._production_socket_pin(front), "control_socket": sidecar._production_socket_pin(control),
            "protocol_identity_sha256": sidecar.PROTOCOL_IDENTITY_SHA256,
            "execution_config_identity_sha256": runtime["execution_config_identity_sha256"],
            "binding_set_identity_sha256": runtime["binding_set_identity_sha256"],
            "preprocessing_contract_authority": json.loads(canonical_json_bytes(preprocessing)),
            "worker_image_ids": runtime["worker_image_ids"],
            "capacity": sidecar._production_capacity_contract(
                max_connections=sidecar.PRODUCTION_MAX_CONNECTIONS_MINIMUM,
                max_requests_per_connection=sidecar.PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM,
                max_total_requests=sidecar.PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM),
            "worker_count": 8, "attested_worker_count": 8, "peer_identities": peers,
            "started_monotonic_ns": time.monotonic_ns(),
            "readiness_artifact_path": str(readiness), "lifecycle_artifact_path": str(lifecycle)}
        authority["service_identity_sha256"] = canonical_sha256(sidecar._production_service_identity_material(authority))
        authority["service_authority_sha256"] = canonical_sha256(authority)
        authority = sidecar.validate_publication_sidecar_service_authority_v1(authority)
        descriptor = _write_document(readiness, authority)
        session = FixtureGuardianLifecycleV1(authority, descriptor, lifecycle, runtime, preprocessing,
            front_socket, control_socket, held_routes)
        front_socket.listen(1)
        control_socket.listen(8)
        control_socket.settimeout(0.1)
        session.thread = threading.Thread(target=_respond_guardian_control, args=(session,),
            name="fixture-guardian-control", daemon=True)
        session.thread.start()
        sidecar.assert_publication_sidecar_service_authority_v1(authority, **_authority_expectations(session))
        return session
    except Exception:
        if session is not None:
            session.close()
        else:
            for _, endpoint in held_routes:
                endpoint.close()
        raise


def _clean_counters(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"connections_accepted", "requests_started", "requests_completed", "requests_failed", "requests_by_worker"}
    if set(value) == required:
        core = {**value, "connections_active": 0, "connections_clean_eof": value["connections_accepted"],
            "connections_failed": 0, "connections_shutdown_closed": 0,
            "evidence_role": "operational_non_authorizing_aggregate"}
        return {**core, "aggregate_sha256": canonical_sha256(core)}
    return dict(value)


def finish_fixture_guardian_lifecycle_v1(session: FixtureGuardianLifecycleV1, *, counters: Mapping[str, Any],
    operational_group: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if session.finished:
        raise ValueError("fixture guardian lifecycle already finished")
    acknowledgement = sidecar.request_publication_sidecar_guardian_stop_v1(session.authority)
    session.thread.join(3.0)
    if session.thread.is_alive() or session.errors or session.stop_attestation is None:
        raise RuntimeError("fixture guardian stop was not authenticated and completed") from (session.errors[0] if session.errors else None)
    authority = sidecar.assert_publication_sidecar_service_authority_identity_v1(
        session.authority, **_authority_expectations(session))
    front = Path(authority["front_socket"]["path"])
    retirement = front.parent.parent / (".vast-gst-analytics-retired-" + authority["lifecycle_id"])
    retirement.mkdir(mode=0o700, exist_ok=False)
    directory_stat = retirement.lstat()
    nodes = [*session.route_sockets, (front, session.front_socket),
        (Path(authority["control_socket"]["path"]), session.control_socket)]
    records = []
    for ordinal, (path, endpoint) in enumerate(nodes):
        before = path.lstat()
        if not stat.S_ISSOCK(before.st_mode) or before.st_nlink != 1:
            raise ValueError("fixture socket custody drifted before retirement")
        endpoint.close()
        retired_name = f"retired-{ordinal:02d}-{path.name}"
        destination = retirement / retired_name
        path.rename(destination)
        metadata = destination.lstat()
        if (metadata.st_dev, metadata.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("fixture retirement changed socket identity")
        records.append(_identity({"schema_version": 1, "artifact_kind": sidecar.RETIRED_SOCKET_NODE_KIND,
            "lifecycle_id": authority["lifecycle_id"], "active_name": path.name, "retired_name": retired_name,
            "retirement_state": "retired_verified", "socket_identity": {
                "st_dev": metadata.st_dev, "st_ino": metadata.st_ino,
                "st_mode_type": stat.S_IFMT(metadata.st_mode), "st_nlink": metadata.st_nlink},
            "retirement_directory": {"path": str(retirement), "st_dev": directory_stat.st_dev, "st_ino": directory_stat.st_ino}}))
    finished = time.monotonic_ns()
    lifecycle = _identity({"schema_version": 1, "artifact_kind": sidecar.PRODUCTION_SERVICE_LIFECYCLE_KIND,
        "service_mode": sidecar.PRODUCTION_SERVICE_MODE, "status": "clean_stop_nonpublication",
        "publication_ready": False, "accepted_evidence_written": False,
        "lifecycle_id": authority["lifecycle_id"], "service_identity_sha256": authority["service_identity_sha256"],
        "service_authority_sha256": authority["service_authority_sha256"], "readiness_artifact": session.authority_descriptor,
        "front_socket": authority["front_socket"], "control_socket": authority["control_socket"],
        "capacity": authority["capacity"], "started_monotonic_ns": authority["started_monotonic_ns"],
        "finished_monotonic_ns": finished, "duration_ns": finished - authority["started_monotonic_ns"],
        "guardian_stop_attestation": session.stop_attestation, "counters": _clean_counters(counters),
        "failure": None, "cleanup_errors": [], "retired_socket_nodes": records,
        "evidence_role": "operational_non_authorizing_lifecycle"})
    lifecycle = sidecar.validate_publication_sidecar_service_lifecycle_v1(lifecycle, expected_authority=authority)
    sidecar._assert_guardian_stop_ack_matches_lifecycle_v1(acknowledgement, lifecycle, expected_authority=authority)
    independent_authority, independent_lifecycle, independent_counters = _independent_validate_guardian_documents(
        authority_value=authority, lifecycle_value=lifecycle, expected_front_socket=authority["front_socket"],
        expected_execution_config_identity_sha256=session.runtime_expectations["execution_config_identity_sha256"],
        expected_binding_set_identity_sha256=session.runtime_expectations["binding_set_identity_sha256"],
        expected_worker_image_ids=session.runtime_expectations["worker_image_ids"],
        expected_preprocessing_authority=session.preprocessing_authority)
    if independent_authority != authority or independent_lifecycle != lifecycle:
        raise ValueError("independent guardian reader changed fixture documents")
    descriptor = _write_document(session.lifecycle_path, lifecycle)
    session.finished = True
    return {"authority": authority, "authority_descriptor": session.authority_descriptor,
        "lifecycle": lifecycle, "lifecycle_descriptor": descriptor, "stop_acknowledgement": acknowledgement,
        "independent_counters": independent_counters,
        "operational_group": dict(operational_group) if operational_group is not None else None,
        "limits": dict(LIMITS)}
