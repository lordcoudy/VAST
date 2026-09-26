#!/usr/bin/env python3
"""Seal the completed qualification execution after authenticated guardian stop.

The closure is qualification evidence only.  It snapshots the stopped guardian
authority/lifecycle and writes its self-hashed receipt last.  It cannot grant a
full-publication run by itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from analytics_execution_protocol import BRANCHES, PROTOCOL_IDENTITY_SHA256
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


sys.dont_write_bytecode = True

SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_publication_policy_qualification_execution_closure_v1"
STATUS = "qualification_execution_closed_nonpublication"
SCOPE = "pre_run_policy_and_full_resource_qualification_only"
RECEIPT_FILENAME = "qualification_execution_closure.v1.receipt.json"
AUTHORITY_SNAPSHOT_FILENAME = "guardian_service_authority.v1.json"
LIFECYCLE_SNAPSHOT_FILENAME = "guardian_service_lifecycle.v1.json"
NONAUTHORITY_BLOCKER = "execution_closure_is_not_full_publication_authority"
TRANSACTION_KIND = "vast_publication_policy_qualification_input_transaction_v2"
PREPROCESSING_RECEIPT_KIND = (
    "vast_guardian_preprocessing_contract_materialization_v1"
)
MATERIALIZATION_RECEIPT_KIND = (
    "vast_qualification_native_runtime_input_materialization_v2"
)
RUNTIME_BUNDLE_SCOPE = "pre_run_policy_and_full_resource_qualification_only"
CHECKPOINT_SCHEMA_VERSION = 3
CHECKPOINT_KIND = "vast_publication_policy_qualification_pilot_execution_v3"
ACCEPTANCE_FILENAME = "checkpoint_qualification_pilot_acceptance.json"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICY_BY_RESOURCE = {"cpu": "cpu_only", "gpu": "gpu_only"}
SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
FINAL_NAMESPACE_FILES = frozenset(
    {
        "frames.csv",
        "frame_events.csv",
        "resource_events.csv",
        "policy_decisions.csv",
        "drop_counters.csv",
        "topology_events.csv",
        "ingress_ledger.csv",
        "branch_terminals.csv",
        "stage_contracts.csv",
        "reset_evidence.csv",
        "publication_policy_decisions.jsonl",
        "resource_intervals.csv",
        "fanout_work_counters.csv",
        "checkpoint_publication_candidate.json",
        "hardware_resource_samples.csv",
        ACCEPTANCE_FILENAME,
    }
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RUNTIME_EXPECTATION_FIELDS = {
    "execution_config_identity_sha256",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
    "preprocessing_contract_content_sha256",
}
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_SNAPSHOT_FIELDS_ORDER = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_file_attributes",
)
_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "qualification_execution_complete",
    "accepted_for_full_publication",
    "publication_ready",
    "authorization_eligible",
    "qualification_input_transaction",
    "guardian_preprocessing",
    "runtime_input_materialization",
    "guardian",
    "pilot_execution",
    "blockers",
    "receipt_sha256",
}
_SOCKET_FIELDS = {"path", "device", "inode", "owner_uid", "owner_gid"}
_RUNTIME_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "scope",
    "matrix_sha256",
    "inputs",
    "container_engine",
    "live_sockets",
    "container_images",
    "device_probes",
    "generated_assets",
    "bundles",
    "blockers",
    "receipt_sha256",
}
_RUNTIME_INPUT_FIELDS = {
    "candidate_index_sha256",
    "candidate_manifest_sha256",
    "candidate_receipt_sha256",
    "bootstrap_mapping_sha256",
    "bootstrap_receipt_sha256",
    "qualification_input_transaction_receipt_sha256",
    "hardware_resource_collector",
    "inventory_sha256",
}
_RUNTIME_BUNDLE_KIND = "vast_qualification_native_runtime_input_bundle_v2"
_GUARDIAN_AUTHORITY_KIND = (
    "vast_gstreamer_analytics_production_service_authority_v1"
)
_GUARDIAN_LIFECYCLE_KIND = (
    "vast_gstreamer_analytics_production_service_lifecycle_v1"
)
_GUARDIAN_STOP_KIND = (
    "vast_gstreamer_analytics_guardian_stop_attestation_v1"
)
_RETIRED_SOCKET_NODE_KIND = (
    "vast_gstreamer_analytics_retired_socket_node_v1"
)
_RETIRED_SOCKET_NODE_COUNT = len(BRANCHES) * len(RESOURCES) + 2
_GUARDIAN_SERVICE_MODE = "bounded_production_guardian_v1"
_GUARDIAN_AUTHORITY_FIELDS = {
    "schema_version",
    "artifact_kind",
    "service_mode",
    "status",
    "publication_ready",
    "accepted_evidence_written",
    "lifecycle_id",
    "owner_process",
    "front_socket",
    "control_socket",
    "protocol_identity_sha256",
    "execution_config_identity_sha256",
    "binding_set_identity_sha256",
    "preprocessing_contract_authority",
    "worker_image_ids",
    "capacity",
    "worker_count",
    "attested_worker_count",
    "peer_identities",
    "started_monotonic_ns",
    "readiness_artifact_path",
    "lifecycle_artifact_path",
    "service_identity_sha256",
    "service_authority_sha256",
}
_GUARDIAN_LIFECYCLE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "service_mode",
    "status",
    "publication_ready",
    "accepted_evidence_written",
    "lifecycle_id",
    "service_identity_sha256",
    "service_authority_sha256",
    "readiness_artifact",
    "front_socket",
    "control_socket",
    "capacity",
    "started_monotonic_ns",
    "finished_monotonic_ns",
    "duration_ns",
    "guardian_stop_attestation",
    "counters",
    "failure",
    "cleanup_errors",
    "retired_socket_nodes",
    "evidence_role",
    "identity",
}
_GUARDIAN_COUNTER_FIELDS = {
    "connections_accepted",
    "connections_active",
    "connections_clean_eof",
    "connections_failed",
    "connections_shutdown_closed",
    "requests_started",
    "requests_completed",
    "requests_failed",
    "requests_by_worker",
    "evidence_role",
    "aggregate_sha256",
}
_GUARDIAN_STOP_FIELDS = {
    "schema_version",
    "artifact_kind",
    "lifecycle_id",
    "service_authority_sha256",
    "nonce",
    "canonical_command_sha256",
    "peer_process",
    "accepted_monotonic_ns",
    "identity",
}
_PEER_IDENTITY_FIELDS = {
    "schema_version",
    "policy_version",
    "peer_identity_mode",
    "peer_pid",
    "peer_uid",
    "peer_gid",
    "peer_raw_hex",
    "peer_raw_sha256",
    "container_state_pid",
    "peer_uid_gid_exact",
    "container_state_pid_positive",
    "pid_positive",
    "pid_matches_container_state_pid",
    "peer_pid_visible_in_controller_namespace",
    "peer_pid_state_pid_equality_attested",
    "peer_identity_by_pid_attested",
    "peer_socket_to_container_pid_binding_attested",
    "docker_desktop_containerd_backend_attested",
    "wsl2_platform_attested",
    "platform_observation_sha256",
    "native_ext4_private_socket_attested",
    "native_ipc_custody_sha256",
    "protocol_nonce_capability_handshake_required",
    "protocol_nonce_capability_handshake_performed",
    "global_eight_worker_handshake_barrier_attested",
    "peer_identity_by_protocol_capability_attested",
    "identity_sha256",
}
_EXPECTED_WORKER_KEYS = {
    f"{branch}:{resource}" for branch in BRANCHES for resource in RESOURCES
}
_CLOSURE_NAMESPACE = frozenset(
    {AUTHORITY_SNAPSHOT_FILENAME, LIFECYCLE_SNAPSHOT_FILENAME, RECEIPT_FILENAME}
)


class QualificationExecutionClosureV1Error(RuntimeError):
    """The post-stop qualification custody chain is incomplete or unsafe."""


PreprocessingLoader = Callable[..., dict[str, Any]]
RuntimeExpectationsLoader = Callable[[Mapping[str, Any]], dict[str, Any]]
AuthorityValidator = Callable[..., dict[str, Any]]
LifecycleValidator = Callable[..., dict[str, Any]]
AcceptanceValidator = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class QualificationPilotCellV2:
    system: str
    resource: str
    codec: str
    topology_kind: str
    scenario: str
    policy: str
    deadline_ms: int | float
    duration_s: int
    run_id: str
    arm_id: str


@dataclass(frozen=True)
class ExecutionClosureDependenciesV1:
    load_preprocessing_contract: PreprocessingLoader
    runtime_expectations_from_preprocessing_receipt: RuntimeExpectationsLoader
    validate_service_authority: AuthorityValidator
    validate_service_lifecycle: LifecycleValidator
    validate_pilot_acceptance: AcceptanceValidator


def _default_load_preprocessing_contract(**kwargs: Any) -> dict[str, Any]:
    from publication_guardian_preprocessing_contract_v1 import (
        load_guardian_preprocessing_contract_v1,
    )

    return load_guardian_preprocessing_contract_v1(**kwargs)


def _default_validate_service_authority(
    value: Mapping[str, Any], **expected: Any
) -> dict[str, Any]:
    from checkpoint_gstreamer_analytics_sidecar import (
        assert_publication_sidecar_service_authority_identity_v1,
    )

    return assert_publication_sidecar_service_authority_identity_v1(
        value, **expected
    )


def _default_runtime_expectations_from_preprocessing_receipt(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    from publication_guardian_runtime_expectations_v1 import (
        runtime_expectations_from_preprocessing_receipt_v1,
    )

    return runtime_expectations_from_preprocessing_receipt_v1(receipt)


def _default_validate_service_lifecycle(
    value: Mapping[str, Any], *, expected_authority: Mapping[str, Any]
) -> dict[str, Any]:
    from checkpoint_gstreamer_analytics_sidecar import (
        validate_publication_sidecar_service_lifecycle_v1,
    )

    return validate_publication_sidecar_service_lifecycle_v1(
        value, expected_authority=expected_authority
    )


def _default_validate_pilot_acceptance(**kwargs: Any) -> dict[str, Any]:
    from checkpoint_qualification_pilot_acceptance_v1 import (
        validate_checkpoint_qualification_pilot_acceptance_v1,
    )

    return validate_checkpoint_qualification_pilot_acceptance_v1(**kwargs)


DEFAULT_DEPENDENCIES = ExecutionClosureDependenciesV1(
    load_preprocessing_contract=_default_load_preprocessing_contract,
    runtime_expectations_from_preprocessing_receipt=(
        _default_runtime_expectations_from_preprocessing_receipt
    ),
    validate_service_authority=_default_validate_service_authority,
    validate_service_lifecycle=_default_validate_service_lifecycle,
    validate_pilot_acceptance=_default_validate_pilot_acceptance,
)


def _fail(message: str) -> None:
    raise QualificationExecutionClosureV1Error(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationExecutionClosureV1Error(
            "qualification execution closure is not canonical JSON"
        ) from error


def _semantic_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def matrix_sha256(cells: Sequence[QualificationPilotCellV2]) -> str:
    """Return the canonical identity of the deterministic pilot matrix."""

    return _semantic_sha([asdict(cell) for cell in cells])


def qualification_pilot_cells_v2(
    *, deadline_ms: int | float = 100.0, duration_s: int = 180
) -> tuple[QualificationPilotCellV2, ...]:
    """Return the frozen deterministic 4x2x2x2 qualification matrix."""

    _require(
        not isinstance(deadline_ms, bool) and deadline_ms == 100,
        "qualification deadline_ms must be exactly 100",
    )
    _require(
        type(duration_s) is int and duration_s == 180,
        "qualification duration_s must be exactly 180",
    )
    cells: list[QualificationPilotCellV2] = []
    for system in SYSTEMS:
        for resource in RESOURCES:
            for codec in CODECS:
                for topology in TOPOLOGIES:
                    slug = f"{system}-{resource}-{codec}-{topology.replace('_', '-')}"
                    cells.append(
                        QualificationPilotCellV2(
                            system=system,
                            resource=resource,
                            codec=codec,
                            topology_kind=topology,
                            scenario=SCENARIO_BY_TOPOLOGY[topology],
                            policy=POLICY_BY_RESOURCE[resource],
                            deadline_ms=100.0,
                            duration_s=duration_s,
                            run_id=f"qualification-v2-{slug}",
                            arm_id=f"qualification-arm-v2-{slug}",
                        )
                    )
    return tuple(cells)


def _is_reparse(path: Path, info: os.stat_result | None = None) -> bool:
    observed = info if info is not None else path.lstat()
    attributes = int(getattr(observed, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    junction = getattr(os.path, "isjunction", lambda _path: False)
    return stat.S_ISLNK(observed.st_mode) or bool(attributes & reparse) or junction(path)


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _contains_reparse_component(path: Path) -> bool:
    absolute = Path(os.path.abspath(os.fspath(path)))
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except OSError:
            return True
        if _is_reparse(cursor, info):
            return True
    return False


def _physical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        info = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise QualificationExecutionClosureV1Error(
            "project_root is unavailable"
        ) from error
    _require(
        stat.S_ISDIR(info.st_mode)
        and not _is_reparse(lexical, info)
        and not _contains_reparse_component(lexical),
        "project_root must be one canonical physical directory",
    )
    return lexical


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    path = Path(os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw)))
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise QualificationExecutionClosureV1Error(
            f"{label} escaped project_root"
        ) from error
    _require(
        all(part not in {"", ".", ".."} for part in relative.parts),
        f"{label} path is not normalized",
    )
    return path


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationExecutionClosureV1Error(f"{label} is missing") from error
    _require(
        stat.S_ISDIR(info.st_mode)
        and not _is_reparse(path, info)
        and not _contains_reparse_component(path),
        f"{label} must be one canonical physical directory",
    )
    return path


def _physical_file(
    root: Path,
    value: Path | str,
    *,
    label: str,
    external: bool = False,
) -> Path:
    raw = Path(value)
    path = (
        Path(os.path.abspath(os.fspath(raw)))
        if external
        else _under_root(root, raw, label=label)
    )
    if external:
        _require(raw.is_absolute(), f"{label} must be absolute")
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationExecutionClosureV1Error(f"{label} is missing") from error
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_reparse(path, info)
        and not _contains_reparse_component(path)
        and int(info.st_nlink) == 1,
        f"{label} must be one canonical single-link physical file",
    )
    return path


def _stable_payload(path: Path, *, label: str) -> bytes:
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationExecutionClosureV1Error(f"cannot read {label}") from error
    _require(
        _snapshot(before) == _snapshot(after) and len(payload) == int(after.st_size),
        f"{label} changed while being read",
    )
    _require(bool(payload), f"{label} is empty")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        _require(key not in value, "canonical JSON contains a duplicate key")
        value[key] = item
    return value


def _decode_canonical_json_payload(
    payload: bytes, *, label: str
) -> dict[str, Any]:
    try:
        value = json.loads(
            payload.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                QualificationExecutionClosureV1Error(
                    f"{label} contains invalid JSON constant {token}"
                )
            ),
        )
    except QualificationExecutionClosureV1Error:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise QualificationExecutionClosureV1Error(f"{label} is invalid JSON") from error
    _require(
        type(value) is dict and payload == _canonical_bytes(value),
        f"{label} is not canonical JSON",
    )
    return value


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    payload = _stable_payload(path, label=label)
    value = _decode_canonical_json_payload(payload, label=label)
    return value, payload


def _project_descriptor(root: Path, value: Path | str, *, label: str) -> dict[str, Any]:
    path = _physical_file(root, value, label=label)
    payload = _stable_payload(path, label=label)
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _source_descriptor(root: Path, path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _future_descriptor(root: Path, path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _descriptor_shape(value: object, *, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict
        and set(value) == _DESCRIPTOR_FIELDS
        and type(value.get("path")) is str
        and bool(value["path"])
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] > 0
        and _valid_sha(value.get("sha256")),
        f"{label} descriptor fields drifted",
    )
    return dict(value)


def _verify_project_descriptor(
    root: Path, value: object, *, label: str
) -> tuple[dict[str, Any], Path]:
    expected = _descriptor_shape(value, label=label)
    path = _physical_file(root, expected["path"], label=label)
    observed = _project_descriptor(root, path, label=label)
    _require(observed == expected, f"{label} descriptor drifted")
    return expected, path


def _self_hash(value: Mapping[str, Any], field: str, *, label: str) -> str:
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    _require(
        _valid_sha(claimed) and claimed == _semantic_sha(unsigned),
        f"{label} self identity drifted",
    )
    return str(claimed)


def _socket_pin(value: object, *, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _SOCKET_FIELDS, f"{label} fields drifted")
    pin = dict(value)
    raw_path = str(pin.get("path") or "")
    path = Path(raw_path)
    posix_path = PurePosixPath(raw_path)
    canonical_absolute = (
        posix_path.is_absolute() and posix_path.as_posix() == raw_path
    ) or (
        path.is_absolute()
        and str(path) == str(Path(os.path.abspath(os.fspath(path))))
    )
    _require(
        canonical_absolute
        and all(
            type(pin.get(field)) is int and pin[field] >= 0
            for field in ("device", "inode", "owner_uid", "owner_gid")
        )
        and pin["inode"] > 0,
        f"{label} is invalid",
    )
    return pin


def _exact_mapping(value: object, fields: set[str], *, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == fields,
        f"{label} fields drifted",
    )
    return dict(value)


def _absolute_artifact_path(value: object, *, label: str) -> str:
    text = str(value or "")
    native = Path(text)
    posix = PurePosixPath(text)
    _require(
        (posix.is_absolute() and posix.as_posix() == text)
        or (
            native.is_absolute()
            and str(native) == str(Path(os.path.abspath(os.fspath(native))))
        ),
        f"{label} is not one canonical absolute path",
    )
    return text


def _validate_guardian_capacity(value: object) -> dict[str, Any]:
    fields = {
        "frozen_contract",
        "controlled_margin",
        "max_connections",
        "max_requests_per_connection",
        "max_total_requests",
        "worker_request_upper_bound",
        "connection_limit_semantics",
        "connection_eof_semantics",
        "request_evidence_semantics",
    }
    capacity = _exact_mapping(value, fields, label="guardian capacity")
    frozen = 600 * 6 * len(BRANCHES) * 240
    cells = 32 + 560 + 560 + 5600
    expected_frozen = {
        "frames_per_second": 600,
        "logical_streams": 6,
        "analytics_branches": len(BRANCHES),
        "cell_seconds_upper_bound": 240,
        "cell_count": cells,
        "connections_per_cell_upper_bound": 24,
        "unmargined_requests_per_connection": frozen,
        "unmargined_connections": cells * 24,
        "unmargined_total_requests": frozen * cells,
    }
    maximums = (
        capacity.get("max_connections"),
        capacity.get("max_requests_per_connection"),
        capacity.get("max_total_requests"),
    )
    _require(
        capacity.get("frozen_contract") == expected_frozen
        and capacity.get("controlled_margin")
        == {"numerator": 5, "denominator": 4}
        and all(type(item) is int for item in maximums)
        and 202560 <= maximums[0] <= 2**63 - 1
        and 4320000 <= maximums[1] <= 2**63 - 1
        and 29168640000 <= maximums[2] <= 2**63 - 1
        and capacity.get("worker_request_upper_bound") == maximums[2]
        and capacity.get("connection_limit_semantics")
        == "upper_bound_not_exact_drain"
        and capacity.get("connection_eof_semantics")
        == "clean_eof_below_upper_bound_allowed"
        and capacity.get("request_evidence_semantics")
        == "constant_memory_operational_counters_non_authorizing",
        "guardian capacity contract drifted",
    )
    return capacity


def _validate_guardian_peer_identity(
    value: object, *, owner: Mapping[str, Any]
) -> dict[str, Any]:
    peer = _exact_mapping(
        value, _PEER_IDENTITY_FIELDS, label="guardian peer identity"
    )
    try:
        raw = bytes.fromhex(str(peer.get("peer_raw_hex") or ""))
        unpacked = struct.unpack("3i", raw)
    except (ValueError, struct.error) as error:
        raise QualificationExecutionClosureV1Error(
            "guardian peer raw credentials drifted"
        ) from error
    bool_fields = {
        "peer_uid_gid_exact",
        "container_state_pid_positive",
        "pid_positive",
        "pid_matches_container_state_pid",
        "peer_pid_visible_in_controller_namespace",
        "peer_pid_state_pid_equality_attested",
        "peer_identity_by_pid_attested",
        "peer_socket_to_container_pid_binding_attested",
        "docker_desktop_containerd_backend_attested",
        "wsl2_platform_attested",
        "native_ext4_private_socket_attested",
        "protocol_nonce_capability_handshake_required",
        "protocol_nonce_capability_handshake_performed",
        "global_eight_worker_handshake_barrier_attested",
        "peer_identity_by_protocol_capability_attested",
    }
    _require(
        peer.get("schema_version") == 2
        and peer.get("policy_version") == 2
        and peer.get("peer_identity_mode")
        in {"native-visible", "namespace-hidden-wsl2-docker-desktop"}
        and all(type(peer.get(field)) is int for field in (
            "peer_pid", "peer_uid", "peer_gid", "container_state_pid"
        ))
        and len(raw) == struct.calcsize("3i")
        and unpacked
        == (peer["peer_pid"], peer["peer_uid"], peer["peer_gid"])
        and peer.get("peer_raw_sha256") == hashlib.sha256(raw).hexdigest()
        and peer.get("peer_uid") == owner["uid"]
        and peer.get("peer_gid") == owner["gid"]
        and peer.get("peer_uid_gid_exact") is True
        and peer.get("container_state_pid_positive") is True
        and 0 < peer["container_state_pid"] < 2**31
        and peer.get("pid_positive") is (peer["peer_pid"] > 0)
        and peer.get("pid_matches_container_state_pid")
        is (peer["peer_pid"] == peer["container_state_pid"])
        and all(type(peer.get(field)) is bool for field in bool_fields)
        and peer.get("protocol_nonce_capability_handshake_required") is True
        and peer.get("protocol_nonce_capability_handshake_performed") is True
        and peer.get("global_eight_worker_handshake_barrier_attested") is True
        and peer.get("peer_identity_by_protocol_capability_attested") is True,
        "guardian peer credential/handshake facts drifted",
    )
    if peer["peer_identity_mode"] == "native-visible":
        _require(
            peer["peer_pid"] == peer["container_state_pid"] > 0
            and peer["peer_pid_visible_in_controller_namespace"] is True
            and peer["peer_pid_state_pid_equality_attested"] is True
            and peer["peer_identity_by_pid_attested"] is True
            and peer["peer_socket_to_container_pid_binding_attested"] is True
            and peer["docker_desktop_containerd_backend_attested"] is False
            and peer["wsl2_platform_attested"] is False
            and peer["platform_observation_sha256"] is None
            and peer["native_ext4_private_socket_attested"] is False
            and peer["native_ipc_custody_sha256"] is None,
            "guardian native-visible peer facts drifted",
        )
    else:
        _require(
            peer["peer_pid"] == 0
            and peer["peer_pid_visible_in_controller_namespace"] is False
            and peer["peer_pid_state_pid_equality_attested"] is False
            and peer["peer_identity_by_pid_attested"] is False
            and peer["peer_socket_to_container_pid_binding_attested"] is False
            and peer["docker_desktop_containerd_backend_attested"] is True
            and peer["wsl2_platform_attested"] is True
            and peer["native_ext4_private_socket_attested"] is True
            and _valid_sha(peer.get("platform_observation_sha256"))
            and _valid_sha(peer.get("native_ipc_custody_sha256")),
            "guardian namespace-hidden peer facts drifted",
        )
    claimed = peer.get("identity_sha256")
    core = {key: item for key, item in peer.items() if key != "identity_sha256"}
    _require(
        _valid_sha(claimed) and claimed == _semantic_sha(core),
        "guardian peer identity self-hash drifted",
    )
    return peer


def _validate_guardian_stop_attestation(
    value: object,
    *,
    authority: Mapping[str, Any],
    finished_monotonic_ns: int,
) -> dict[str, Any]:
    attestation = _exact_mapping(
        value, _GUARDIAN_STOP_FIELDS, label="guardian stop attestation"
    )
    nonce = attestation.get("nonce")
    peer = _exact_mapping(
        attestation.get("peer_process"),
        {"pid", "uid", "gid", "proc_stat_starttime_ticks"},
        label="guardian stop peer process",
    )
    command = {
        "schema_version": 1,
        "message_type": "production_guardian_stop",
        "lifecycle_id": authority["lifecycle_id"],
        "service_authority_sha256": authority["service_authority_sha256"],
        "nonce": nonce,
    }
    accepted = attestation.get("accepted_monotonic_ns")
    _require(
        attestation.get("schema_version") == 1
        and attestation.get("artifact_kind") == _GUARDIAN_STOP_KIND
        and attestation.get("lifecycle_id") == authority["lifecycle_id"]
        and attestation.get("service_authority_sha256")
        == authority["service_authority_sha256"]
        and _valid_sha(nonce)
        and attestation.get("canonical_command_sha256") == _semantic_sha(command)
        and type(peer.get("pid")) is int
        and 0 < peer["pid"] < 2**31
        and peer.get("uid") == authority["owner_process"]["uid"]
        and peer.get("gid") == authority["owner_process"]["gid"]
        and type(peer.get("proc_stat_starttime_ticks")) is int
        and peer["proc_stat_starttime_ticks"] > 0
        and type(accepted) is int
        and authority["started_monotonic_ns"] <= accepted <= finished_monotonic_ns,
        "guardian authenticated-stop binding/timing drifted",
    )
    identity = _exact_mapping(
        attestation.get("identity"),
        {"algorithm", "sha256"},
        label="guardian stop identity",
    )
    core = {key: item for key, item in attestation.items() if key != "identity"}
    _require(
        identity.get("algorithm") == "sha256"
        and identity.get("sha256") == _semantic_sha(core),
        "guardian stop attestation self-hash drifted",
    )
    return attestation


def _validate_retired_socket_ledger(
    value: object,
    *,
    lifecycle_id: str,
    front_socket: Mapping[str, Any],
    control_socket: Mapping[str, Any],
) -> list[dict[str, Any]]:
    _require(type(value) is list, "guardian retired socket ledger is not a list")
    expected_active_name_sequence = (
        *(
            f"worker-{branch}-{resource}.sock"
            for branch in BRANCHES
            for resource in RESOURCES
        ),
        Path(front_socket["path"]).name,
        Path(control_socket["path"]).name,
    )
    _require(
        len(expected_active_name_sequence) == _RETIRED_SOCKET_NODE_COUNT
        and len(set(expected_active_name_sequence))
        == _RETIRED_SOCKET_NODE_COUNT,
        "guardian retired socket active-name cardinality drifted",
    )
    expected_active_names = set(expected_active_name_sequence)
    records: list[dict[str, Any]] = []
    for raw in value:
        record = _exact_mapping(
            raw,
            {
                "schema_version",
                "artifact_kind",
                "lifecycle_id",
                "active_name",
                "retired_name",
                "retirement_state",
                "socket_identity",
                "retirement_directory",
                "identity",
            },
            label="guardian retired socket record",
        )
        active_name = record.get("active_name")
        retired_name = record.get("retired_name")
        socket_identity = _exact_mapping(
            record.get("socket_identity"),
            {"st_dev", "st_ino", "st_mode_type", "st_nlink"},
            label="guardian retired socket identity",
        )
        retirement_directory = _exact_mapping(
            record.get("retirement_directory"),
            {"path", "st_dev", "st_ino"},
            label="guardian socket retirement directory",
        )
        identity = _exact_mapping(
            record.get("identity"),
            {"algorithm", "sha256"},
            label="guardian retired socket record identity",
        )
        core = {key: item for key, item in record.items() if key != "identity"}
        _require(
            record.get("schema_version") == 1
            and record.get("artifact_kind") == _RETIRED_SOCKET_NODE_KIND
            and record.get("lifecycle_id") == lifecycle_id
            and record.get("retirement_state") == "retired_verified"
            and type(active_name) is str
            and PurePosixPath(active_name).parts == (active_name,)
            and active_name not in {"", ".", ".."}
            and type(retired_name) is str
            and PurePosixPath(retired_name).parts == (retired_name,)
            and retired_name not in {"", ".", ".."}
            and type(socket_identity.get("st_dev")) is int
            and socket_identity["st_dev"] >= 0
            and type(socket_identity.get("st_ino")) is int
            and socket_identity["st_ino"] > 0
            and socket_identity.get("st_mode_type") == stat.S_IFSOCK
            and socket_identity.get("st_nlink") == 1
            and type(retirement_directory.get("path")) is str
            and Path(retirement_directory["path"]).is_absolute()
            and type(retirement_directory.get("st_dev")) is int
            and retirement_directory["st_dev"] == socket_identity["st_dev"]
            and type(retirement_directory.get("st_ino")) is int
            and retirement_directory["st_ino"] > 0
            and identity.get("algorithm") == "sha256"
            and identity.get("sha256") == _semantic_sha(core),
            "guardian retired socket record drifted",
        )
        records.append(dict(record))
    active_names = [item["active_name"] for item in records]
    retired_names = [item["retired_name"] for item in records]
    _require(
        len(records) == _RETIRED_SOCKET_NODE_COUNT
        and set(active_names) == expected_active_names
        and len(active_names) == len(set(active_names))
        and len(retired_names) == len(set(retired_names)),
        "guardian retired socket ledger coverage drifted",
    )
    directory_claims = {
        _semantic_sha(item["retirement_directory"]) for item in records
    }
    _require(
        len(directory_claims) == 1,
        "guardian retired socket ledger directory drifted",
    )
    retirement = records[0]["retirement_directory"]
    retirement_path = Path(retirement["path"])
    _require(
        retirement_path.parent == Path(front_socket["path"]).parent.parent
        and retirement_path.name
        == f".vast-gst-analytics-retired-{lifecycle_id}",
        "guardian socket retirement path binding drifted",
    )
    descriptor = -1
    try:
        descriptor = os.open(
            retirement_path,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        opened = os.fstat(descriptor)
        _require(
            stat.S_ISDIR(opened.st_mode)
            and int(opened.st_dev) == retirement["st_dev"]
            and int(opened.st_ino) == retirement["st_ino"]
            and set(os.listdir(descriptor)) == set(retired_names),
            "guardian socket retirement namespace drifted",
        )
        for record in records:
            metadata = os.stat(
                record["retired_name"],
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            claimed = record["socket_identity"]
            _require(
                stat.S_ISSOCK(metadata.st_mode)
                and int(metadata.st_nlink) == 1
                and {
                    "st_dev": int(metadata.st_dev),
                    "st_ino": int(metadata.st_ino),
                    "st_mode_type": int(stat.S_IFMT(metadata.st_mode)),
                    "st_nlink": int(metadata.st_nlink),
                }
                == claimed,
                "guardian retired socket physical identity drifted",
            )
    except OSError as error:
        raise ClosureError(
            f"guardian socket retirement custody failed: {error}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return records


def _independent_validate_guardian_documents(
    *,
    authority_value: Mapping[str, Any],
    lifecycle_value: Mapping[str, Any],
    expected_front_socket: Mapping[str, Any],
    expected_execution_config_identity_sha256: str,
    expected_binding_set_identity_sha256: str,
    expected_worker_image_ids: Mapping[str, Any],
    expected_preprocessing_authority: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = _exact_mapping(
        authority_value,
        _GUARDIAN_AUTHORITY_FIELDS,
        label="guardian service authority",
    )
    owner = _exact_mapping(
        authority.get("owner_process"),
        {"pid", "proc_stat_starttime_ticks", "uid", "gid"},
        label="guardian owner process",
    )
    front = _socket_pin(authority.get("front_socket"), label="guardian front socket")
    control = _socket_pin(
        authority.get("control_socket"), label="guardian control socket"
    )
    images = _exact_mapping(
        authority.get("worker_image_ids"), set(RESOURCES), label="guardian worker images"
    )
    capacity = _validate_guardian_capacity(authority.get("capacity"))
    _require(
        authority.get("schema_version") == 1
        and authority.get("artifact_kind") == _GUARDIAN_AUTHORITY_KIND
        and authority.get("service_mode") == _GUARDIAN_SERVICE_MODE
        and authority.get("status") == "live_operational_nonpublication"
        and authority.get("publication_ready") is False
        and authority.get("accepted_evidence_written") is False
        and type(authority.get("lifecycle_id")) is str
        and re.fullmatch(r"[A-Za-z0-9._-]{32}", authority["lifecycle_id"])
        is not None
        and type(owner.get("pid")) is int
        and 0 < owner["pid"] < 2**31
        and type(owner.get("proc_stat_starttime_ticks")) is int
        and owner["proc_stat_starttime_ticks"] > 0
        and type(owner.get("uid")) is int
        and owner["uid"] >= 0
        and type(owner.get("gid")) is int
        and owner["gid"] >= 0
        and front == dict(expected_front_socket)
        and front["path"] != control["path"]
        and authority.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256
        and authority.get("execution_config_identity_sha256")
        == expected_execution_config_identity_sha256
        and authority.get("binding_set_identity_sha256")
        == expected_binding_set_identity_sha256
        and authority.get("preprocessing_contract_authority")
        == dict(expected_preprocessing_authority)
        and images == dict(expected_worker_image_ids)
        and all(
            type(images[resource]) is str
            and _IMAGE_ID_RE.fullmatch(images[resource]) is not None
            for resource in RESOURCES
        )
        and type(authority.get("started_monotonic_ns")) is int
        and authority["started_monotonic_ns"] > 0,
        "guardian service authority header/input binding drifted",
    )
    _absolute_artifact_path(
        authority.get("readiness_artifact_path"), label="guardian readiness artifact"
    )
    _absolute_artifact_path(
        authority.get("lifecycle_artifact_path"), label="guardian lifecycle artifact"
    )
    _require(
        authority["readiness_artifact_path"] != authority["lifecycle_artifact_path"],
        "guardian evidence artifact paths alias",
    )
    peers = authority.get("peer_identities")
    _require(
        authority.get("worker_count") == len(_EXPECTED_WORKER_KEYS)
        and authority.get("attested_worker_count") == len(_EXPECTED_WORKER_KEYS)
        and type(peers) is list
        and len(peers) == len(_EXPECTED_WORKER_KEYS),
        "guardian worker/peer coverage drifted",
    )
    observed_keys: set[str] = set()
    for raw_row in peers:
        row = _exact_mapping(
            raw_row,
            {"branch", "resource", "worker_image_id", "peer_identity", "peer_identity_sha256"},
            label="guardian peer row",
        )
        key = f"{row.get('branch')}:{row.get('resource')}"
        _require(
            key in _EXPECTED_WORKER_KEYS
            and key not in observed_keys
            and row.get("worker_image_id") == images[row["resource"]],
            "guardian peer coordinate/image binding drifted",
        )
        peer = _validate_guardian_peer_identity(row.get("peer_identity"), owner=owner)
        _require(
            row.get("peer_identity_sha256") == peer["identity_sha256"],
            "guardian peer row identity drifted",
        )
        observed_keys.add(key)
    _require(
        observed_keys == _EXPECTED_WORKER_KEYS,
        "guardian peer coordinate set drifted",
    )
    service_material = {
        "lifecycle_id": authority["lifecycle_id"],
        "owner_process": owner,
        "front_socket": front,
        "control_socket": control,
        "protocol_identity_sha256": authority["protocol_identity_sha256"],
        "execution_config_identity_sha256": authority[
            "execution_config_identity_sha256"
        ],
        "binding_set_identity_sha256": authority["binding_set_identity_sha256"],
        "preprocessing_contract_authority": authority[
            "preprocessing_contract_authority"
        ],
        "worker_image_ids": images,
        "capacity": capacity,
    }
    _require(
        authority.get("service_identity_sha256") == _semantic_sha(service_material),
        "guardian service identity drifted",
    )
    authority_core = {
        key: item for key, item in authority.items() if key != "service_authority_sha256"
    }
    _require(
        authority.get("service_authority_sha256") == _semantic_sha(authority_core),
        "guardian service authority self-hash drifted",
    )

    lifecycle = _exact_mapping(
        lifecycle_value,
        _GUARDIAN_LIFECYCLE_FIELDS,
        label="guardian service lifecycle",
    )
    started = lifecycle.get("started_monotonic_ns")
    finished = lifecycle.get("finished_monotonic_ns")
    readiness = _exact_mapping(
        lifecycle.get("readiness_artifact"),
        _DESCRIPTOR_FIELDS,
        label="guardian readiness descriptor",
    )
    authority_payload = _canonical_bytes(authority)
    _require(
        lifecycle.get("schema_version") == 1
        and lifecycle.get("artifact_kind") == _GUARDIAN_LIFECYCLE_KIND
        and lifecycle.get("service_mode") == _GUARDIAN_SERVICE_MODE
        and lifecycle.get("status") == "clean_stop_nonpublication"
        and lifecycle.get("publication_ready") is False
        and lifecycle.get("accepted_evidence_written") is False
        and lifecycle.get("lifecycle_id") == authority["lifecycle_id"]
        and lifecycle.get("service_identity_sha256")
        == authority["service_identity_sha256"]
        and lifecycle.get("service_authority_sha256")
        == authority["service_authority_sha256"]
        and lifecycle.get("front_socket") == front
        and lifecycle.get("control_socket") == control
        and lifecycle.get("capacity") == capacity
        and lifecycle.get("evidence_role")
        == "operational_non_authorizing_lifecycle"
        and lifecycle.get("failure") is None
        and lifecycle.get("cleanup_errors") == []
        and started == authority["started_monotonic_ns"]
        and type(finished) is int
        and finished >= started
        and lifecycle.get("duration_ns") == finished - started
        and readiness.get("path") == authority["readiness_artifact_path"]
        and readiness.get("size_bytes") == len(authority_payload)
        and readiness.get("sha256") == hashlib.sha256(authority_payload).hexdigest(),
        "guardian lifecycle authority/status/timing binding drifted",
    )
    _validate_guardian_stop_attestation(
        lifecycle.get("guardian_stop_attestation"),
        authority=authority,
        finished_monotonic_ns=finished,
    )
    counters = _exact_mapping(
        lifecycle.get("counters"),
        _GUARDIAN_COUNTER_FIELDS,
        label="guardian lifecycle counters",
    )
    numeric = (
        "connections_accepted",
        "connections_active",
        "connections_clean_eof",
        "connections_failed",
        "connections_shutdown_closed",
        "requests_started",
        "requests_completed",
        "requests_failed",
    )
    by_worker = counters.get("requests_by_worker")
    counter_core = {
        key: item for key, item in counters.items() if key != "aggregate_sha256"
    }
    _require(
        all(type(counters.get(field)) is int and counters[field] >= 0 for field in numeric)
        and type(by_worker) is dict
        and set(by_worker) == _EXPECTED_WORKER_KEYS
        and all(type(count) is int and count >= 0 for count in by_worker.values())
        and counters["connections_active"] == 0
        and counters["connections_clean_eof"]
        + counters["connections_failed"]
        + counters["connections_shutdown_closed"]
        == counters["connections_accepted"]
        and counters["connections_failed"] == 0
        and counters["requests_completed"] == counters["requests_started"]
        and counters["requests_failed"] == 0
        and sum(by_worker.values()) == counters["requests_started"]
        and counters.get("evidence_role")
        == "operational_non_authorizing_aggregate"
        and counters.get("aggregate_sha256") == _semantic_sha(counter_core),
        "guardian lifecycle aggregate counters drifted",
    )
    lifecycle["retired_socket_nodes"] = _validate_retired_socket_ledger(
        lifecycle.get("retired_socket_nodes"),
        lifecycle_id=authority["lifecycle_id"],
        front_socket=front,
        control_socket=control,
    )
    identity = _exact_mapping(
        lifecycle.get("identity"),
        {"algorithm", "sha256"},
        label="guardian lifecycle identity",
    )
    lifecycle_core = {
        key: item for key, item in lifecycle.items() if key != "identity"
    }
    _require(
        identity.get("algorithm") == "sha256"
        and identity.get("sha256") == _semantic_sha(lifecycle_core),
        "guardian lifecycle self-hash drifted",
    )
    return authority, lifecycle, counters


def _validate_transaction(root: Path, path_value: Path | str) -> dict[str, Any]:
    descriptor = _project_descriptor(root, path_value, label="qualification transaction receipt")
    path = root / descriptor["path"]
    value, _payload = _read_canonical_json(path, label="qualification transaction receipt")
    required = {
        "schema_version",
        "artifact_kind",
        "status",
        "scope",
        "accepted",
        "publication_ready",
        "authorization_eligible",
        "systems",
        "cell_count",
        "hardware_resource_collector",
        "receipt_sha256",
    }
    _require(required <= set(value), "qualification transaction receipt fields drifted")
    _require(
        value.get("schema_version") == 2
        and value.get("artifact_kind") == TRANSACTION_KIND
        and value.get("status") == "qualification_inputs_materialized_nonaccepted"
        and value.get("scope") == "forced_resource_qualification_pilots_only"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("systems")
        == ["deepstream", "savant", "openvino_gva", "gstreamer_custom"]
        and value.get("cell_count") == 32,
        "qualification transaction receipt identity drifted",
    )
    fragments = value.get("fragments")
    collector_descriptor, _collector_path = _verify_project_descriptor(
        root,
        value.get("hardware_resource_collector"),
        label="qualification hardware resource collector",
    )
    _require(
        collector_descriptor["path"] == "scripts/collect_metrics.py",
        "qualification hardware resource collector path drifted",
    )
    _require(
        type(fragments) is dict and set(fragments) == set(SYSTEMS),
        "qualification transaction fragment set drifted",
    )
    verified_fragments: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        descriptor_value, _fragment_path = _verify_project_descriptor(
            root,
            fragments[system],
            label=f"qualification transaction {system} fragment",
        )
        verified_fragments[system] = descriptor_value
    return {
        "receipt": descriptor,
        "receipt_sha256": _self_hash(
            value, "receipt_sha256", label="qualification transaction receipt"
        ),
        "hardware_resource_collector": collector_descriptor,
        "fragments": verified_fragments,
    }


def _validate_preprocessing(
    *,
    root: Path,
    transaction: Mapping[str, Any],
    contract_path_value: Path | str,
    receipt_path_value: Path | str,
    dependencies: ExecutionClosureDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract_descriptor = _project_descriptor(
        root, contract_path_value, label="guardian preprocessing contract"
    )
    receipt_descriptor = _project_descriptor(
        root, receipt_path_value, label="guardian preprocessing receipt"
    )
    contract_path = root / contract_descriptor["path"]
    receipt_path = root / receipt_descriptor["path"]
    contract, _contract_payload = _read_canonical_json(
        contract_path, label="guardian preprocessing contract"
    )
    receipt, _receipt_payload = _read_canonical_json(
        receipt_path, label="guardian preprocessing receipt"
    )
    required = {
        "schema_version",
        "artifact_kind",
        "status",
        "preprocessing_contract",
        "preprocessing_contract_content_sha256",
        "qualification_transaction_receipt",
        "qualification_transaction_receipt_sha256",
        "candidate_manifest",
        "policy_contract_sha256",
        "receipt_sha256",
    }
    _require(required <= set(receipt), "guardian preprocessing receipt fields drifted")
    receipt_identity = _self_hash(
        receipt, "receipt_sha256", label="guardian preprocessing receipt"
    )
    _require(
        receipt.get("schema_version") == 1
        and receipt.get("artifact_kind") == PREPROCESSING_RECEIPT_KIND
        and receipt.get("status") == "materialized_from_verified_v4_acceptance"
        and receipt.get("preprocessing_contract") == contract_descriptor
        and receipt.get("qualification_transaction_receipt") == transaction["receipt"]
        and receipt.get("qualification_transaction_receipt_sha256")
        == transaction["receipt_sha256"]
        and receipt.get("preprocessing_contract_content_sha256")
        == _semantic_sha(contract)
        and _valid_sha(receipt.get("policy_contract_sha256")),
        "guardian preprocessing transaction/contract binding drifted",
    )
    candidate = _descriptor_shape(
        receipt.get("candidate_manifest"), label="preprocessing candidate manifest"
    )
    try:
        loaded = dependencies.load_preprocessing_contract(
            project_root=root,
            preprocessing_contract_path=contract_path,
            materialization_receipt_path=receipt_path,
            candidate_manifest_path=root / candidate["path"],
            expected_preprocessing_contract_sha256=receipt[
                "preprocessing_contract_content_sha256"
            ],
        )
    except QualificationExecutionClosureV1Error:
        raise
    except Exception as error:
        raise QualificationExecutionClosureV1Error(
            f"guardian preprocessing materialization validation failed: {error}"
        ) from error
    _require(
        type(loaded) is dict
        and loaded.get("preprocessing_contract") == contract
        and loaded.get("receipt") == receipt
        and type(loaded.get("authority")) is dict,
        "guardian preprocessing loader returned drifted material",
    )
    authority = dict(loaded["authority"])
    _require(
        authority.get("preprocessing_contract_content_sha256")
        == receipt["preprocessing_contract_content_sha256"]
        and authority.get("preprocessing_contract_file_sha256")
        == contract_descriptor["sha256"]
        and authority.get("materialization_receipt_identity_sha256")
        == receipt_identity
        and authority.get("materialization_receipt_file_sha256")
        == receipt_descriptor["sha256"]
        and authority.get("qualification_transaction_receipt_sha256")
        == transaction["receipt_sha256"]
        and authority.get("policy_contract_sha256")
        == receipt["policy_contract_sha256"],
        "guardian preprocessing authority drifted",
    )
    return (
        {
            "contract": contract_descriptor,
            "contract_content_sha256": receipt[
                "preprocessing_contract_content_sha256"
            ],
            "materialization_receipt": receipt_descriptor,
            "materialization_receipt_identity_sha256": receipt_identity,
            "policy_contract_sha256": receipt["policy_contract_sha256"],
            "authority": authority,
        },
        receipt,
    )


def _runtime_bundle_records(
    *,
    root: Path,
    receipt_path: Path,
    value: Mapping[str, Any],
    cells: Sequence[QualificationPilotCellV2],
    hardware_resource_collector: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    records = value.get("bundles")
    _require(type(records) is list and len(records) == 32, "runtime receipt requires exact 32 bundles")
    by_arm: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(records):
        _require(type(raw) is dict, f"runtime bundle record[{position}] is invalid")
        required = {"arm_id", "run_id", "path", "size_bytes", "sha256", "bundle_sha256"}
        _require(
            set(raw) == required,
            f"runtime bundle record[{position}] fields drifted",
        )
        arm_id = raw.get("arm_id")
        _require(type(arm_id) is str and arm_id not in by_arm, "runtime bundle arm set drifted")
        by_arm[arm_id] = dict(raw)
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[int, int]] = set()
    for cell in cells:
        record = by_arm.get(cell.arm_id)
        expected_relative = (
            Path(cell.system)
            / cell.resource
            / cell.codec
            / f"{cell.topology_kind}.json"
        ).as_posix()
        _require(
            type(record) is dict
            and record.get("run_id") == cell.run_id
            and record.get("path") == expected_relative
            and type(record.get("size_bytes")) is int
            and record["size_bytes"] > 0
            and _valid_sha(record.get("sha256"))
            and _valid_sha(record.get("bundle_sha256")),
            f"runtime bundle identity drifted for {cell.arm_id}",
        )
        relative = PurePosixPath(expected_relative)
        bundle_path = receipt_path.parent.joinpath(*relative.parts)
        try:
            bundle_path.relative_to(root)
        except ValueError as error:
            raise QualificationExecutionClosureV1Error(
                "runtime bundle escaped project_root"
            ) from error
        observed = _project_descriptor(root, bundle_path, label=f"runtime bundle {cell.arm_id}")
        _require(
            observed["size_bytes"] == record["size_bytes"]
            and observed["sha256"] == record["sha256"],
            f"runtime bundle descriptor drifted for {cell.arm_id}",
        )
        info = bundle_path.lstat()
        identity = (int(info.st_dev), int(info.st_ino))
        _require(identity not in identities, "runtime bundle physical alias is prohibited")
        identities.add(identity)
        bundle_value, _bundle_payload = _read_canonical_json(
            bundle_path, label=f"runtime bundle {cell.arm_id}"
        )
        _require(
            bundle_value.get("schema_version") == 2
            and bundle_value.get("artifact_kind") == _RUNTIME_BUNDLE_KIND
            and bundle_value.get("status")
            == "materialized_for_native_qualification_only"
            and bundle_value.get("accepted") is False
            and bundle_value.get("publication_ready") is False
            and bundle_value.get("authorization_eligible") is False
            and bundle_value.get("scope") == RUNTIME_BUNDLE_SCOPE
            and bundle_value.get("system") == cell.system
            and bundle_value.get("resource") == cell.resource
            and bundle_value.get("codec") == cell.codec
            and bundle_value.get("topology_kind") == cell.topology_kind
            and bundle_value.get("run_id") == cell.run_id
            and bundle_value.get("arm_id") == cell.arm_id
            and bundle_value.get("hardware_resource_collector")
            == hardware_resource_collector
            and _self_hash(
                bundle_value,
                "bundle_sha256",
                label=f"runtime bundle {cell.arm_id}",
            )
            == record["bundle_sha256"],
            f"runtime bundle semantic identity drifted for {cell.arm_id}",
        )
        normalized.append(dict(record))
    _require(set(by_arm) == {cell.arm_id for cell in cells}, "runtime bundle coordinate set drifted")
    return normalized, _semantic_sha(normalized)


def _validate_runtime_inputs(
    *,
    root: Path,
    path_value: Path | str,
    cells: Sequence[QualificationPilotCellV2],
    transaction: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    descriptor = _project_descriptor(
        root, path_value, label="runtime-input materialization receipt"
    )
    path = root / descriptor["path"]
    value, _payload = _read_canonical_json(path, label="runtime-input materialization receipt")
    _require(
        set(value) == _RUNTIME_RECEIPT_FIELDS,
        "runtime-input materialization receipt fields drifted",
    )
    expected_matrix = matrix_sha256(cells)
    _require(
        value.get("schema_version") == 2
        and value.get("artifact_kind") == MATERIALIZATION_RECEIPT_KIND
        and value.get("status") == "materialized_for_native_qualification_only"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("scope") == RUNTIME_BUNDLE_SCOPE
        and value.get("matrix_sha256") == expected_matrix,
        "runtime-input materialization receipt identity drifted",
    )
    source_inputs = value.get("inputs")
    _require(
        type(source_inputs) is dict
        and set(source_inputs) == _RUNTIME_INPUT_FIELDS
        and all(
            _valid_sha(source_inputs.get(field))
            for field in _RUNTIME_INPUT_FIELDS
            if field != "hardware_resource_collector"
        )
        and source_inputs.get("hardware_resource_collector")
        == transaction["hardware_resource_collector"]
        and source_inputs.get(
            "qualification_input_transaction_receipt_sha256"
        )
        == transaction["receipt"]["sha256"],
        "runtime-input materialization/transaction binding drifted",
    )
    receipt_identity = _self_hash(
        value, "receipt_sha256", label="runtime-input materialization receipt"
    )
    sockets = value.get("live_sockets")
    _require(
        type(sockets) is dict
        and set(sockets) == {"container_engine", "analytics_execution"},
        "runtime-input live socket set drifted",
    )
    analytics_socket = _socket_pin(
        sockets["analytics_execution"], label="runtime analytics socket"
    )
    records, bundle_set_sha = _runtime_bundle_records(
        root=root,
        receipt_path=path,
        value=value,
        cells=cells,
        hardware_resource_collector=transaction[
            "hardware_resource_collector"
        ],
    )
    return (
        {
            "receipt": descriptor,
            "receipt_sha256": receipt_identity,
            "matrix_sha256": expected_matrix,
            "bundle_count": 32,
            "bundle_set_sha256": bundle_set_sha,
            "analytics_socket": analytics_socket,
            "source_input_sha256": dict(source_inputs),
        },
        {record["arm_id"]: record for record in records},
    )


def _validate_guardian(
    *,
    root: Path,
    authority_path_value: Path | str,
    lifecycle_path_value: Path | str,
    runtime_socket: Mapping[str, Any],
    preprocessing: Mapping[str, Any],
    preprocessing_receipt: Mapping[str, Any],
    dependencies: ExecutionClosureDependenciesV1,
) -> tuple[dict[str, Any], bytes, bytes, Path, Path]:
    authority_path = _physical_file(
        root, authority_path_value, label="guardian service authority", external=True
    )
    lifecycle_path = _physical_file(
        root, lifecycle_path_value, label="guardian service lifecycle", external=True
    )
    authority_value, authority_payload = _read_canonical_json(
        authority_path, label="guardian service authority"
    )
    lifecycle_value, lifecycle_payload = _read_canonical_json(
        lifecycle_path, label="guardian service lifecycle"
    )
    preprocessing_authority = preprocessing.get("authority")
    _require(
        type(preprocessing_authority) is dict,
        "guardian preprocessing authority is missing",
    )
    try:
        runtime_expectations = (
            dependencies.runtime_expectations_from_preprocessing_receipt(
                preprocessing_receipt
            )
        )
    except QualificationExecutionClosureV1Error:
        raise
    except Exception as error:
        raise QualificationExecutionClosureV1Error(
            f"guardian runtime expectations validation failed: {error}"
        ) from error
    _require(
        type(runtime_expectations) is dict
        and set(runtime_expectations) == _RUNTIME_EXPECTATION_FIELDS,
        "guardian runtime expectations fields drifted",
    )
    worker_image_ids = runtime_expectations.get("worker_image_ids")
    _require(
        all(
            _valid_sha(runtime_expectations.get(field))
            for field in (
                "execution_config_identity_sha256",
                "binding_set_identity_sha256",
                "bindings_identity_sha256",
                "policy_contract_sha256",
                "preprocessing_contract_content_sha256",
            )
        )
        and type(worker_image_ids) is dict
        and set(worker_image_ids) == {"cpu", "gpu"}
        and all(
            type(worker_image_ids.get(resource)) is str
            and _IMAGE_ID_RE.fullmatch(worker_image_ids[resource]) is not None
            for resource in ("cpu", "gpu")
        ),
        "guardian runtime expectations identities are invalid",
    )
    _require(
        runtime_expectations["policy_contract_sha256"]
        == preprocessing_authority.get("policy_contract_sha256")
        and runtime_expectations["preprocessing_contract_content_sha256"]
        == preprocessing_authority.get(
            "preprocessing_contract_content_sha256"
        ),
        "guardian runtime expectations/preprocessing binding drifted",
    )
    authority, lifecycle, independent_counters = (
        _independent_validate_guardian_documents(
            authority_value=authority_value,
            lifecycle_value=lifecycle_value,
            expected_front_socket=runtime_socket,
            expected_execution_config_identity_sha256=runtime_expectations[
                "execution_config_identity_sha256"
            ],
            expected_binding_set_identity_sha256=runtime_expectations[
                "binding_set_identity_sha256"
            ],
            expected_worker_image_ids=worker_image_ids,
            expected_preprocessing_authority=preprocessing_authority,
        )
    )
    try:
        dependency_authority = dependencies.validate_service_authority(
            authority_value,
            expected_front_socket=runtime_socket["path"],
            expected_execution_config_identity_sha256=runtime_expectations[
                "execution_config_identity_sha256"
            ],
            expected_binding_set_identity_sha256=runtime_expectations[
                "binding_set_identity_sha256"
            ],
            expected_worker_image_ids=worker_image_ids,
            expected_preprocessing_contract_authority=(
                preprocessing_authority
            ),
            expected_service_identity_sha256=lifecycle_value.get(
                "service_identity_sha256"
            ),
            expected_policy_contract_sha256=runtime_expectations[
                "policy_contract_sha256"
            ],
        )
        dependency_lifecycle = dependencies.validate_service_lifecycle(
            lifecycle_value, expected_authority=dependency_authority
        )
    except QualificationExecutionClosureV1Error:
        raise
    except Exception as error:
        raise QualificationExecutionClosureV1Error(
            f"guardian authority/lifecycle validation failed: {error}"
        ) from error
    _require(
        type(dependency_authority) is dict
        and dependency_authority == authority == authority_value,
        "guardian authority validator drifted",
    )
    _require(
        type(dependency_lifecycle) is dict
        and dependency_lifecycle == lifecycle == lifecycle_value,
        "guardian lifecycle validator drifted",
    )
    _require(
        authority.get("preprocessing_contract_authority")
        == preprocessing_authority
        and authority.get("execution_config_identity_sha256")
        == runtime_expectations["execution_config_identity_sha256"]
        and authority.get("binding_set_identity_sha256")
        == runtime_expectations["binding_set_identity_sha256"]
        and authority.get("worker_image_ids") == worker_image_ids
        and authority.get("service_identity_sha256")
        == lifecycle.get("service_identity_sha256")
        and runtime_expectations["policy_contract_sha256"]
        == preprocessing.get("policy_contract_sha256"),
        "guardian authority preprocessing/service/policy binding drifted",
    )
    front = _socket_pin(authority.get("front_socket"), label="guardian front socket")
    control = _socket_pin(authority.get("control_socket"), label="guardian control socket")
    _require(front == dict(runtime_socket), "runtime/guardian analytics socket binding drifted")
    _require(front["path"] != control["path"], "guardian sockets alias")
    _require(
        lifecycle.get("status") == "clean_stop_nonpublication"
        and lifecycle.get("cleanup_errors") == []
        and lifecycle.get("failure") is None,
        "guardian lifecycle is not a clean authenticated stop",
    )
    _require(
        lifecycle.get("lifecycle_id") == authority.get("lifecycle_id")
        and lifecycle.get("service_identity_sha256")
        == authority.get("service_identity_sha256")
        and lifecycle.get("service_authority_sha256")
        == authority.get("service_authority_sha256")
        and lifecycle.get("front_socket") == front
        and lifecycle.get("control_socket") == control,
        "guardian lifecycle/authority binding drifted",
    )
    _require(
        _valid_sha(authority.get("service_authority_sha256"))
        and _valid_sha(authority.get("service_identity_sha256")),
        "guardian authority identities are invalid",
    )
    lifecycle_identity = lifecycle.get("identity")
    _require(
        type(lifecycle_identity) is dict
        and lifecycle_identity.get("algorithm") == "sha256"
        and _valid_sha(lifecycle_identity.get("sha256")),
        "guardian lifecycle identity is invalid",
    )
    for socket_path in (front["path"], control["path"]):
        _require(
            not os.path.lexists(socket_path),
            "guardian socket survived authenticated stop",
        )
    stop_attestation = lifecycle["guardian_stop_attestation"]
    return (
        {
            "service_authority_sha256": authority["service_authority_sha256"],
            "service_identity_sha256": authority["service_identity_sha256"],
            "lifecycle_id": authority["lifecycle_id"],
            "front_socket": front,
            "control_socket": control,
            "lifecycle_status": lifecycle["status"],
            "lifecycle_identity_sha256": lifecycle_identity["sha256"],
            "authenticated_stop_attestation_identity_sha256": (
                stop_attestation["identity"]["sha256"]
            ),
            "authenticated_stop_nonce": stop_attestation["nonce"],
            "request_counters_aggregate_sha256": independent_counters[
                "aggregate_sha256"
            ],
            "_request_counters": independent_counters,
            "preprocessing_contract_authority_sha256": _semantic_sha(
                preprocessing_authority
            ),
            "preprocessing_materialization_receipt_identity_sha256": (
                preprocessing["materialization_receipt_identity_sha256"]
            ),
            "policy_contract_sha256": preprocessing_authority[
                "policy_contract_sha256"
            ],
        },
        authority_payload,
        lifecycle_payload,
        authority_path,
        lifecycle_path,
    )


def _scan_accepted_guardian_workload(
    *,
    path: Path,
    cell: QualificationPilotCellV2,
    stream_digest: Any,
) -> dict[str, Any]:
    """Stream one accepted decision JSONL into exact guardian request counts."""

    flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = -1
    counts = {key: 0 for key in sorted(_EXPECTED_WORKER_KEYS)}
    per_cell_digest = hashlib.sha256(
        b"VAST:qualification-guardian-cell-workload:v1\0"
    )
    record_count = 0
    try:
        named_before = path.lstat()
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        _require(
            stat.S_ISREG(opened.st_mode)
            and int(opened.st_nlink) == 1
            and _snapshot(named_before) == _snapshot(opened),
            f"pilot decision workload file is unsafe for {cell.arm_id}",
        )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            for line_number, line in enumerate(source, start=1):
                _require(
                    1 < len(line) <= 4 * 1024 * 1024 and line.endswith(b"\n"),
                    f"pilot decision record framing drifted for {cell.arm_id}:{line_number}",
                )
                try:
                    record = json.loads(
                        line.decode("ascii"),
                        object_pairs_hook=_unique_object,
                        parse_constant=lambda token: (_ for _ in ()).throw(
                            QualificationExecutionClosureV1Error(
                                f"pilot decision contains invalid constant {token}"
                            )
                        ),
                    )
                except QualificationExecutionClosureV1Error:
                    raise
                except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
                    raise QualificationExecutionClosureV1Error(
                        f"pilot decision record is invalid for {cell.arm_id}:{line_number}"
                    ) from error
                _require(
                    type(record) is dict and _canonical_bytes(record) == line,
                    f"pilot decision record is not canonical for {cell.arm_id}:{line_number}",
                )
                claimed = record.get("sha256")
                unsigned = {
                    key: item for key, item in record.items() if key != "sha256"
                }
                native = record.get("native_decision_evidence")
                branch = record.get("branch")
                resource = record.get("selected_resource")
                decision_id = record.get("decision_id")
                _require(
                    _valid_sha(claimed)
                    and claimed == _semantic_sha(unsigned)
                    and record.get("record_status")
                    == "accepted_native_runtime_decision"
                    and record.get("system") == cell.system
                    and branch in BRANCHES
                    and resource == cell.resource
                    and type(decision_id) is str
                    and bool(decision_id)
                    and type(native) is dict
                    and native.get("decision_id") == decision_id
                    and native.get("system") == cell.system
                    and native.get("branch") == branch
                    and native.get("selected_resource") == resource
                    and native.get("telemetry_source") == "native"
                    and native.get("terminal_status") == "completed",
                    f"pilot decision is not accepted native guardian work for {cell.arm_id}:{line_number}",
                )
                key = f"{branch}:{resource}"
                projection = {
                    "arm_id": cell.arm_id,
                    "decision_id": decision_id,
                    "branch": branch,
                    "resource": resource,
                    "record_sha256": claimed,
                }
                projection_payload = _canonical_bytes(projection).rstrip(b"\n")
                framed = len(projection_payload).to_bytes(8, "big") + projection_payload
                stream_digest.update(framed)
                per_cell_digest.update(framed)
                counts[key] += 1
                record_count += 1
        after = os.fstat(descriptor)
        named_after = path.lstat()
        _require(
            _snapshot(opened) == _snapshot(after) == _snapshot(named_after),
            f"pilot decision workload changed while reading {cell.arm_id}",
        )
    except OSError as error:
        raise QualificationExecutionClosureV1Error(
            f"cannot read pilot decision workload for {cell.arm_id}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _require(
        record_count > 0
        and all(counts[f"{branch}:{cell.resource}"] > 0 for branch in BRANCHES)
        and all(
            count == 0
            for key, count in counts.items()
            if not key.endswith(f":{cell.resource}")
        ),
        f"pilot decision workload coverage drifted for {cell.arm_id}",
    )
    return {
        "arm_id": cell.arm_id,
        "request_count": record_count,
        "requests_by_worker": counts,
        "decision_stream_sha256": per_cell_digest.hexdigest(),
    }


def _validate_pilot_execution(
    *,
    root: Path,
    pilot_root_value: Path | str,
    checkpoint_path_value: Path | str,
    runtime: Mapping[str, Any],
    runtime_bundles: Mapping[str, Mapping[str, Any]],
    transaction: Mapping[str, Any],
    preprocessing: Mapping[str, Any],
    runtime_receipt_path: Path,
    guardian_authority_path: Path,
    guardian_authority_binding_descriptor: Mapping[str, Any] | None,
    guardian: Mapping[str, Any],
    cells: Sequence[QualificationPilotCellV2],
    dependencies: ExecutionClosureDependenciesV1,
) -> dict[str, Any]:
    pilots = _physical_directory(root, pilot_root_value, label="pilot_root")
    checkpoint_descriptor = _project_descriptor(
        root, checkpoint_path_value, label="qualification execution checkpoint"
    )
    checkpoint_path = root / checkpoint_descriptor["path"]
    _require(
        checkpoint_path != pilots and pilots not in checkpoint_path.parents,
        "qualification execution checkpoint must remain outside pilot_root",
    )
    checkpoint, _payload = _read_canonical_json(
        checkpoint_path, label="qualification execution checkpoint"
    )
    required = {
        "schema_version",
        "artifact_kind",
        "status",
        "matrix_sha256",
        "input_sha256",
        "input_identity",
        "completed",
        "publication_ready",
        "authorization_eligible",
        "blockers",
        "checkpoint_sha256",
    }
    _require(
        set(checkpoint) == required,
        "qualification execution checkpoint fields drifted",
    )
    checkpoint_identity = _self_hash(
        checkpoint, "checkpoint_sha256", label="qualification execution checkpoint"
    )
    completed = checkpoint.get("completed")
    expected_matrix = matrix_sha256(cells)
    _require(
        checkpoint.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
        and checkpoint.get("artifact_kind") == CHECKPOINT_KIND
        and checkpoint.get("status") == "completed"
        and checkpoint.get("matrix_sha256") == expected_matrix
        and runtime.get("matrix_sha256") == expected_matrix
        and type(completed) is list
        and len(completed) == 32
        and checkpoint.get("publication_ready") is False
        and checkpoint.get("authorization_eligible") is False
        and checkpoint.get("blockers")
        == ["qualification_pilots_are_not_full_publication_arms"],
        "qualification checkpoint does not contain the completed exact 32-cell matrix",
    )
    inputs = checkpoint.get("input_sha256")
    input_identity = checkpoint.get("input_identity")
    observed_guardian_descriptor = _project_descriptor(
        root, guardian_authority_path, label="pilot-bound guardian service authority"
    )
    if guardian_authority_binding_descriptor is None:
        guardian_descriptor = observed_guardian_descriptor
    else:
        guardian_descriptor = _descriptor_shape(
            guardian_authority_binding_descriptor,
            label="pilot-bound guardian authority source",
        )
        _require(
            guardian_descriptor["size_bytes"]
            == observed_guardian_descriptor["size_bytes"]
            and guardian_descriptor["sha256"]
            == observed_guardian_descriptor["sha256"],
            "pilot-bound guardian source/snapshot identity drifted",
        )
    expected_input_fields = {
        "candidate_index",
        "candidate_manifest",
        "candidate_receipt",
        "bootstrap_mapping",
        "bootstrap_receipt",
        "qualification_input_transaction_receipt",
        "hardware_resource_collector",
        "runtime_input_materialization_receipt",
        "guardian_service_authority",
        "guardian_preprocessing_contract",
        "guardian_preprocessing_contract_receipt",
        *(f"bootstrap_calibration_{system}" for system in SYSTEMS),
        *(f"native_runtime_bundle_{cell.arm_id}" for cell in cells),
    }
    _require(
        type(inputs) is dict
        and set(inputs) == expected_input_fields
        and all(_valid_sha(value) for value in inputs.values())
        and all(
            inputs.get(field)
            == runtime["source_input_sha256"].get(f"{field}_sha256")
            for field in (
                "candidate_index",
                "candidate_manifest",
                "candidate_receipt",
                "bootstrap_mapping",
                "bootstrap_receipt",
            )
        )
        and inputs.get("qualification_input_transaction_receipt")
        == transaction["receipt"]["sha256"]
        and inputs.get("hardware_resource_collector")
        == transaction["hardware_resource_collector"]["sha256"]
        and inputs.get("runtime_input_materialization_receipt")
        == runtime["receipt"]["sha256"]
        and inputs.get("guardian_service_authority")
        == guardian_descriptor["sha256"]
        and inputs.get("guardian_preprocessing_contract")
        == preprocessing["contract"]["sha256"]
        and inputs.get("guardian_preprocessing_contract_receipt")
        == preprocessing["materialization_receipt"]["sha256"],
        "qualification checkpoint input identities drifted",
    )
    identity_fields = {
        "schema_version",
        "named_sha256",
        "files",
        "execution_code_closure_receipt_path",
        "execution_code_closure_receipt_sha256",
        "execution_code_source_paths",
        "interpreter",
    }
    snapshot_fields = set(_SNAPSHOT_FIELDS_ORDER)
    _require(
        type(input_identity) is dict
        and set(input_identity) == identity_fields
        and input_identity.get("schema_version") == 1
        and input_identity.get("named_sha256") == inputs
        and _valid_sha(input_identity.get("execution_code_closure_receipt_sha256"))
        and type(input_identity.get("execution_code_closure_receipt_path")) is str
        and type(input_identity.get("execution_code_source_paths")) is list
        and type(input_identity.get("interpreter")) is dict,
        "qualification checkpoint physical input anchor drifted",
    )
    files = input_identity.get("files")
    _require(type(files) is list and bool(files), "qualification checkpoint physical input files are empty")
    anchored_by_path: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(files):
        _require(
            type(record) is dict
            and set(record) == {"path", "size_bytes", "sha256", "snapshot"}
            and type(record.get("snapshot")) is dict
            and set(record["snapshot"]) == snapshot_fields,
            f"qualification checkpoint physical input[{position}] shape drifted",
        )
        descriptor = _descriptor_shape(
            {key: record[key] for key in _DESCRIPTOR_FIELDS},
            label=f"qualification checkpoint physical input[{position}]",
        )
        _require(descriptor["path"] not in anchored_by_path, "qualification checkpoint physical input path is duplicated")
        anchored_path = _under_root(
            root,
            descriptor["path"],
            label=f"qualification checkpoint physical input[{position}]",
        )
        relocated_guardian = (
            not os.path.lexists(anchored_path)
            and guardian_authority_binding_descriptor is not None
            and descriptor["sha256"] == guardian_descriptor["sha256"]
            and descriptor["size_bytes"] == guardian_descriptor["size_bytes"]
            and descriptor["sha256"] == inputs["guardian_service_authority"]
        )
        if not relocated_guardian:
            observed = _project_descriptor(
                root,
                descriptor["path"],
                label=f"qualification checkpoint physical input[{position}]",
            )
            physical = _physical_file(
                root,
                descriptor["path"],
                label=f"qualification checkpoint physical input[{position}]",
            ).lstat()
            observed_snapshot = dict(
                zip(_SNAPSHOT_FIELDS_ORDER, _snapshot(physical), strict=True)
            )
            _require(
                observed == descriptor and observed_snapshot == record["snapshot"],
                f"qualification checkpoint physical input[{position}] drifted",
            )
        anchored_by_path[descriptor["path"]] = record
    _require(
        [record["path"] for record in files] == sorted(anchored_by_path)
        and all(value in {record["sha256"] for record in files} for value in inputs.values()),
        "qualification checkpoint physical input coverage drifted",
    )
    closure_receipt_path = input_identity["execution_code_closure_receipt_path"]
    _require(
        closure_receipt_path in anchored_by_path,
        "qualification checkpoint code closure receipt is not physically anchored",
    )
    closure_receipt, _closure_payload = _read_canonical_json(
        root / closure_receipt_path,
        label="qualification execution code closure receipt",
    )
    closure_unsigned = {
        key: value for key, value in closure_receipt.items() if key != "receipt_sha256"
    }
    _require(
        closure_receipt.get("kind")
        == "vast_publication_policy_qualification_execution_code_closure_v1"
        and closure_receipt.get("receipt_sha256") == _semantic_sha(closure_unsigned)
        == input_identity["execution_code_closure_receipt_sha256"]
        and input_identity["execution_code_source_paths"]
        == [record["path"] for record in closure_receipt.get("project_sources", [])]
        and all(path in anchored_by_path for path in input_identity["execution_code_source_paths"]),
        "qualification execution code closure binding drifted",
    )
    interpreter = input_identity["interpreter"]
    _require(
        set(interpreter) == {"path", "size_bytes", "sha256", "snapshot"}
        and type(interpreter.get("snapshot")) is dict
        and set(interpreter["snapshot"]) == snapshot_fields,
        "qualification checkpoint interpreter anchor shape drifted",
    )
    interpreter_path = _physical_file(
        root,
        interpreter["path"],
        label="qualification checkpoint interpreter",
        external=True,
    )
    interpreter_payload = _stable_payload(
        interpreter_path, label="qualification checkpoint interpreter"
    )
    interpreter_snapshot = dict(
        zip(
            _SNAPSHOT_FIELDS_ORDER,
            _snapshot(interpreter_path.lstat()),
            strict=True,
        )
    )
    _require(
        len(interpreter_payload) == interpreter["size_bytes"]
        and hashlib.sha256(interpreter_payload).hexdigest() == interpreter["sha256"]
        and interpreter_snapshot == interpreter["snapshot"],
        "qualification checkpoint interpreter anchor drifted",
    )
    cell_rows: list[dict[str, Any]] = []
    acceptance_inodes: set[tuple[int, int]] = set()
    workload_digest = hashlib.sha256(
        b"VAST:qualification-guardian-request-workload:v1\0"
    )
    workload_counts = {key: 0 for key in sorted(_EXPECTED_WORKER_KEYS)}
    workload_cells: list[dict[str, Any]] = []
    for position, cell in enumerate(cells):
        entry = completed[position]
        _require(
            type(entry) is dict
            and set(entry)
            == {
                "system",
                "resource",
                "codec",
                "topology_kind",
                "scenario",
                "policy",
                "deadline_ms",
                "duration_s",
                "run_id",
                "arm_id",
                "pilot_path",
                "acceptance",
                "evidence",
            },
            f"checkpoint completed[{position}] fields drifted",
        )
        coordinate = {
            "system": cell.system,
            "resource": cell.resource,
            "codec": cell.codec,
            "topology_kind": cell.topology_kind,
        }
        expected_pilot_path = (
            Path(cell.system) / cell.resource / cell.codec / cell.topology_kind
        ).as_posix()
        _require(
            all(entry.get(field) == value for field, value in coordinate.items())
            and entry.get("scenario") == cell.scenario
            and entry.get("policy") == cell.policy
            and entry.get("deadline_ms") == cell.deadline_ms
            and entry.get("duration_s") == cell.duration_s
            and entry.get("run_id") == cell.run_id
            and entry.get("arm_id") == cell.arm_id
            and entry.get("pilot_path") == expected_pilot_path,
            f"qualification checkpoint cell identity drifted at {position}",
        )
        bundle = runtime_bundles.get(cell.arm_id)
        _require(type(bundle) is dict, f"runtime bundle is absent for {cell.arm_id}")
        _require(
            inputs.get(f"native_runtime_bundle_{cell.arm_id}") == bundle["sha256"],
            f"checkpoint/runtime bundle binding drifted for {cell.arm_id}",
        )
        arm = pilots.joinpath(*PurePosixPath(expected_pilot_path).parts)
        arm = _physical_directory(root, arm, label=f"pilot arm {cell.arm_id}")
        try:
            names = {item.name for item in arm.iterdir()}
        except OSError as error:
            raise QualificationExecutionClosureV1Error(
                f"pilot arm is unreadable for {cell.arm_id}"
            ) from error
        _require(
            names == set(FINAL_NAMESPACE_FILES),
            f"pilot final namespace drifted for {cell.arm_id}",
        )
        evidence = entry.get("evidence")
        _require(
            type(evidence) is dict and set(evidence) == set(FINAL_NAMESPACE_FILES),
            f"checkpoint evidence set drifted for {cell.arm_id}",
        )
        for name in sorted(FINAL_NAMESPACE_FILES):
            observed = _project_descriptor(
                root, arm / name, label=f"pilot evidence {cell.arm_id}/{name}"
            )
            _require(
                evidence.get(name) == observed,
                f"checkpoint evidence descriptor drifted for {cell.arm_id}/{name}",
            )
        acceptance_descriptor = _project_descriptor(
            root, arm / ACCEPTANCE_FILENAME, label=f"pilot acceptance {cell.arm_id}"
        )
        _require(
            entry.get("acceptance") == acceptance_descriptor
            and evidence[ACCEPTANCE_FILENAME] == acceptance_descriptor,
            f"checkpoint acceptance descriptor drifted for {cell.arm_id}",
        )
        acceptance_info = (root / acceptance_descriptor["path"]).lstat()
        inode = (int(acceptance_info.st_dev), int(acceptance_info.st_ino))
        _require(inode not in acceptance_inodes, "pilot acceptance physical alias is prohibited")
        acceptance_inodes.add(inode)
        try:
            acceptance = dependencies.validate_pilot_acceptance(
                project_root=root,
                acceptance_path=root / acceptance_descriptor["path"],
                expected_system=cell.system,
                expected_resource=cell.resource,
                expected_codec=cell.codec,
                expected_topology_kind=cell.topology_kind,
                expected_run_id=cell.run_id,
                expected_arm_id=cell.arm_id,
            )
        except QualificationExecutionClosureV1Error:
            raise
        except Exception as error:
            raise QualificationExecutionClosureV1Error(
                f"pilot acceptance validation failed for {cell.arm_id}: {error}"
            ) from error
        _require(
            type(acceptance) is dict and _valid_sha(acceptance.get("sha256")),
            f"pilot acceptance identity is invalid for {cell.arm_id}",
        )
        runtime_bundle_path = runtime_receipt_path.parent.joinpath(
            *PurePosixPath(str(bundle["path"])).parts
        )
        runtime_bundle_descriptor = _project_descriptor(
            root,
            runtime_bundle_path,
            label=f"pilot-bound runtime bundle {cell.arm_id}",
        )
        expected_operational_binding = {
            "hardware_resource_collector": transaction[
                "hardware_resource_collector"
            ],
            "qualification_input_transaction_receipt": transaction["receipt"],
            "qualification_input_transaction_receipt_identity_sha256": (
                transaction["receipt_sha256"]
            ),
            "runtime_input_materialization_receipt": runtime["receipt"],
            "runtime_input_materialization_receipt_identity_sha256": (
                runtime["receipt_sha256"]
            ),
            "runtime_input_bundle": runtime_bundle_descriptor,
            "runtime_input_bundle_identity_sha256": bundle["bundle_sha256"],
            "guardian_service_authority": guardian_descriptor,
            "guardian_service_authority_identity_sha256": guardian[
                "service_authority_sha256"
            ],
            "guardian_preprocessing_contract_receipt": preprocessing[
                "materialization_receipt"
            ],
            "guardian_preprocessing_contract_receipt_identity_sha256": (
                preprocessing["materialization_receipt_identity_sha256"]
            ),
        }
        _require(
            acceptance.get("operational_binding") == expected_operational_binding,
            f"pilot operational binding drifted for {cell.arm_id}",
        )
        cell_workload = _scan_accepted_guardian_workload(
            path=arm / "publication_policy_decisions.jsonl",
            cell=cell,
            stream_digest=workload_digest,
        )
        workload_cells.append(cell_workload)
        for key, count in cell_workload["requests_by_worker"].items():
            workload_counts[key] += count
        cell_rows.append(
            {
                **coordinate,
                "scenario": cell.scenario,
                "policy": cell.policy,
                "deadline_ms": cell.deadline_ms,
                "duration_s": cell.duration_s,
                "run_id": cell.run_id,
                "arm_id": cell.arm_id,
                "pilot_path": expected_pilot_path,
                "acceptance": acceptance_descriptor,
                "acceptance_identity_sha256": acceptance["sha256"],
            }
        )
    cell_set_sha = _semantic_sha(cell_rows)
    pilot_root_record = {
        "path": pilots.relative_to(root).as_posix(),
        "cell_count": 32,
        "matrix_sha256": expected_matrix,
        "cell_set_sha256": cell_set_sha,
    }
    pilot_root_record["identity_sha256"] = _semantic_sha(pilot_root_record)
    workload_core = {
        "schema_version": 1,
        "artifact_kind": "vast_qualification_guardian_request_workload_v1",
        "derivation": "accepted_native_runtime_decisions_exact_v1",
        "cell_count": 32,
        "request_count": sum(workload_counts.values()),
        "requests_by_worker": workload_counts,
        "cells": workload_cells,
        "decision_stream_sha256": workload_digest.hexdigest(),
    }
    _require(
        workload_core["request_count"] > 0
        and all(workload_counts[key] > 0 for key in _EXPECTED_WORKER_KEYS),
        "accepted pilot workload does not cover all guardian workers",
    )
    workload = {
        **workload_core,
        "identity_sha256": _semantic_sha(workload_core),
    }
    return {
        "pilot_root": pilot_root_record,
        "checkpoint": checkpoint_descriptor,
        "checkpoint_sha256": checkpoint_identity,
        "cells": cell_rows,
        "cell_set_sha256": cell_set_sha,
        "guardian_request_workload": workload,
    }


def _validate_chain(
    *,
    root: Path,
    qualification_transaction_receipt_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_materialization_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    guardian_service_authority_path: Path | str,
    guardian_service_lifecycle_path: Path | str,
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    dependencies: ExecutionClosureDependenciesV1,
    guardian_authority_binding_descriptor: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], bytes, bytes, Path, Path]:
    cells = qualification_pilot_cells_v2()
    transaction = _validate_transaction(root, qualification_transaction_receipt_path)
    preprocessing, preprocessing_receipt = _validate_preprocessing(
        root=root,
        transaction=transaction,
        contract_path_value=preprocessing_contract_path,
        receipt_path_value=preprocessing_materialization_receipt_path,
        dependencies=dependencies,
    )
    runtime, runtime_bundles = _validate_runtime_inputs(
        root=root,
        path_value=runtime_input_materialization_receipt_path,
        cells=cells,
        transaction=transaction,
    )
    guardian, authority_payload, lifecycle_payload, authority_path, lifecycle_path = (
        _validate_guardian(
            root=root,
            authority_path_value=guardian_service_authority_path,
            lifecycle_path_value=guardian_service_lifecycle_path,
            runtime_socket=runtime["analytics_socket"],
            preprocessing=preprocessing,
            preprocessing_receipt=preprocessing_receipt,
            dependencies=dependencies,
        )
    )
    pilot_execution = _validate_pilot_execution(
        root=root,
        pilot_root_value=pilot_root,
        checkpoint_path_value=checkpoint_path,
        runtime=runtime,
        runtime_bundles=runtime_bundles,
        transaction=transaction,
        preprocessing=preprocessing,
        runtime_receipt_path=root / runtime["receipt"]["path"],
        guardian_authority_path=authority_path,
        guardian_authority_binding_descriptor=(
            guardian_authority_binding_descriptor
        ),
        guardian=guardian,
        cells=cells,
        dependencies=dependencies,
    )
    observed_counters = guardian.pop("_request_counters")
    expected_workload = pilot_execution["guardian_request_workload"]
    _require(
        observed_counters["requests_started"]
        == observed_counters["requests_completed"]
        == expected_workload["request_count"]
        and observed_counters["requests_failed"] == 0
        and observed_counters["requests_by_worker"]
        == expected_workload["requests_by_worker"],
        "guardian request counters do not exactly match accepted 32-cell workload",
    )
    guardian.update(
        {
            "accepted_workload_request_count": expected_workload[
                "request_count"
            ],
            "accepted_workload_requests_by_worker": expected_workload[
                "requests_by_worker"
            ],
            "accepted_workload_identity_sha256": expected_workload[
                "identity_sha256"
            ],
        }
    )
    return (
        {
            "qualification_input_transaction": transaction,
            "guardian_preprocessing": preprocessing,
            "runtime_input_materialization": runtime,
            "guardian": guardian,
            "pilot_execution": pilot_execution,
        },
        authority_payload,
        lifecycle_payload,
        authority_path,
        lifecycle_path,
    )


def _destination(root: Path, output_dir: Path | str) -> Path:
    destination = _under_root(root, output_dir, label="execution closure output_dir")
    _require(
        destination != root,
        "execution closure output_dir must be dedicated",
    )
    return destination


def _write_or_verify_immutable(
    custody: PhysicalRootCustodyV1,
    path: Path,
    payload: bytes,
    *,
    label: str,
    fault_hook: Any | None = None,
) -> dict[str, Any]:
    """Create one readonly leaf or accept only an identical readonly winner."""

    try:
        observed, _identity, _disposition = custody.commit_or_adopt_exact_identity(
            path,
            payload,
            label=label,
            mode=0o444,
            create_parents=False,
            after_publish_step=fault_hook,
        )
    except PublicationPhysicalIoV1Error as error:
        raise QualificationExecutionClosureV1Error(
            f"immutable execution closure collision: {path.name}"
        ) from error
    _require(
        observed.get("size_bytes") == len(payload)
        and observed.get("sha256") == hashlib.sha256(payload).hexdigest(),
        f"immutable execution closure identity drifted: {path.name}",
    )
    return observed


def materialize_publication_policy_qualification_execution_closure_v1(
    *,
    project_root: Path | str,
    qualification_transaction_receipt_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_materialization_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    guardian_service_authority_path: Path | str,
    guardian_service_lifecycle_path: Path | str,
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    output_dir: Path | str,
    dependencies: ExecutionClosureDependenciesV1 = DEFAULT_DEPENDENCIES,
) -> dict[str, Path | int | str]:
    """Validate the complete stopped execution and atomically publish its receipt."""

    root = _physical_root(project_root)
    destination = _destination(root, output_dir)
    chain, authority_payload, lifecycle_payload, authority_source, lifecycle_source = (
        _validate_chain(
            root=root,
            qualification_transaction_receipt_path=(
                qualification_transaction_receipt_path
            ),
            preprocessing_contract_path=preprocessing_contract_path,
            preprocessing_materialization_receipt_path=(
                preprocessing_materialization_receipt_path
            ),
            runtime_input_materialization_receipt_path=(
                runtime_input_materialization_receipt_path
            ),
            guardian_service_authority_path=guardian_service_authority_path,
            guardian_service_lifecycle_path=guardian_service_lifecycle_path,
            pilot_root=pilot_root,
            checkpoint_path=checkpoint_path,
            dependencies=dependencies,
        )
    )
    authority_final = destination / AUTHORITY_SNAPSHOT_FILENAME
    lifecycle_final = destination / LIFECYCLE_SNAPSHOT_FILENAME
    receipt_final = destination / RECEIPT_FILENAME
    guardian = {
        **chain["guardian"],
        "service_authority_source": _source_descriptor(
            root, authority_source, authority_payload
        ),
        "service_lifecycle_source": _source_descriptor(
            root, lifecycle_source, lifecycle_payload
        ),
        "service_authority_snapshot": _future_descriptor(
            root, authority_final, authority_payload
        ),
        "service_lifecycle_snapshot": _future_descriptor(
            root, lifecycle_final, lifecycle_payload
        ),
    }
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": STATUS,
        "scope": SCOPE,
        "qualification_execution_complete": True,
        "accepted_for_full_publication": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "qualification_input_transaction": chain[
            "qualification_input_transaction"
        ],
        "guardian_preprocessing": chain["guardian_preprocessing"],
        "runtime_input_materialization": chain[
            "runtime_input_materialization"
        ],
        "guardian": guardian,
        "pilot_execution": chain["pilot_execution"],
        "blockers": [NONAUTHORITY_BLOCKER],
    }
    receipt = {**unsigned, "receipt_sha256": _semantic_sha(unsigned)}
    receipt_payload = _canonical_bytes(receipt)

    try:
        with PhysicalRootCustodyV1.open(
            root, label="execution closure project_root"
        ) as custody:
            destination = custody.ensure_directory(
                destination, label="execution closure output_dir"
            )
            initial_names = set(
                custody.list_directory_names(
                    destination, label="execution closure output namespace"
                )
            )
            if RECEIPT_FILENAME in initial_names:
                _require(
                    initial_names == set(_CLOSURE_NAMESPACE),
                    "completed execution closure namespace drifted",
                )
            else:
                _require(
                    initial_names
                    <= {AUTHORITY_SNAPSHOT_FILENAME, LIFECYCLE_SNAPSHOT_FILENAME},
                    "incomplete execution closure namespace contains an extra entry",
                )
            _write_or_verify_immutable(
                custody,
                authority_final,
                authority_payload,
                label="guardian authority snapshot",
            )
            _write_or_verify_immutable(
                custody,
                lifecycle_final,
                lifecycle_payload,
                label="guardian lifecycle snapshot",
            )
            # The receipt is deliberately the last authority-bearing leaf.
            _write_or_verify_immutable(
                custody,
                receipt_final,
                receipt_payload,
                label="qualification execution closure receipt",
            )
            _require(
                set(
                    custody.list_directory_names(
                        destination, label="committed execution closure namespace"
                    )
                )
                == set(_CLOSURE_NAMESPACE),
                "committed execution closure namespace drifted",
            )
            custody.verify()
    except QualificationExecutionClosureV1Error:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise QualificationExecutionClosureV1Error(
            f"immutable execution closure commit failed: {error}"
        ) from error

    loaded = load_publication_policy_qualification_execution_closure_v1(
        project_root=root,
        receipt_path=receipt_final,
        dependencies=dependencies,
    )
    _require(loaded["receipt"] == receipt, "post-commit execution closure drifted")
    return {
        "receipt_path": receipt_final,
        "authority_snapshot_path": authority_final,
        "lifecycle_snapshot_path": lifecycle_final,
        "cell_count": 32,
        "receipt_sha256": receipt["receipt_sha256"],
    }


def load_publication_policy_qualification_execution_closure_v1(
    *,
    project_root: Path | str,
    receipt_path: Path | str,
    dependencies: ExecutionClosureDependenciesV1 = DEFAULT_DEPENDENCIES,
) -> dict[str, Any]:
    """Cold-load and revalidate one immutable execution-closure receipt."""

    root = _physical_root(project_root)
    receipt_file = _under_root(
        root, receipt_path, label="qualification execution closure receipt"
    )
    _require(
        receipt_file.name == RECEIPT_FILENAME,
        "execution closure receipt filename drifted",
    )
    authority_path = receipt_file.parent / AUTHORITY_SNAPSHOT_FILENAME
    lifecycle_path = receipt_file.parent / LIFECYCLE_SNAPSHOT_FILENAME
    try:
        with PhysicalRootCustodyV1.open(
            root, label="cold execution closure project_root"
        ) as custody:
            _require(
                set(
                    custody.list_directory_names(
                        receipt_file.parent,
                        label="cold execution closure namespace",
                    )
                )
                == set(_CLOSURE_NAMESPACE),
                "cold execution closure namespace drifted",
            )
            receipt_descriptor, receipt_payload = custody.read_descriptor(
                receipt_file,
                label="qualification execution closure receipt",
                maximum=64 * 1024 * 1024,
                capture=True,
            )
            authority_descriptor, authority_payload = custody.read_descriptor(
                authority_path,
                label="guardian authority snapshot",
                maximum=64 * 1024 * 1024,
                capture=True,
            )
            lifecycle_descriptor, lifecycle_payload = custody.read_descriptor(
                lifecycle_path,
                label="guardian lifecycle snapshot",
                maximum=64 * 1024 * 1024,
                capture=True,
            )
            for path, label in (
                (receipt_file, "qualification execution closure receipt"),
                (authority_path, "guardian authority snapshot"),
                (lifecycle_path, "guardian lifecycle snapshot"),
            ):
                mode, _identity = custody.stat_regular_identity(path, label=label)
                _require(mode == 0o444, f"{label} is not readonly")
            custody.verify()
    except QualificationExecutionClosureV1Error:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as error:
        raise QualificationExecutionClosureV1Error(
            f"cold execution closure custody failed: {error}"
        ) from error
    assert receipt_payload is not None
    assert authority_payload is not None
    assert lifecycle_payload is not None
    receipt = _decode_canonical_json_payload(
        receipt_payload, label="qualification execution closure receipt"
    )
    authority_snapshot = _decode_canonical_json_payload(
        authority_payload, label="guardian authority snapshot"
    )
    lifecycle_snapshot = _decode_canonical_json_payload(
        lifecycle_payload, label="guardian lifecycle snapshot"
    )
    _require(set(receipt) == _RECEIPT_FIELDS, "execution closure receipt fields drifted")
    _require(
        receipt.get("schema_version") == SCHEMA_VERSION
        and receipt.get("artifact_kind") == ARTIFACT_KIND
        and receipt.get("status") == STATUS
        and receipt.get("scope") == SCOPE
        and receipt.get("qualification_execution_complete") is True
        and receipt.get("accepted_for_full_publication") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and receipt.get("blockers") == [NONAUTHORITY_BLOCKER],
        "execution closure receipt identity drifted",
    )
    receipt_identity = _self_hash(
        receipt, "receipt_sha256", label="qualification execution closure receipt"
    )
    guardian_record = receipt.get("guardian")
    _require(type(guardian_record) is dict, "execution closure guardian binding is missing")
    _require(
        guardian_record.get("service_authority_snapshot") == authority_descriptor
        and guardian_record.get("service_lifecycle_snapshot")
        == lifecycle_descriptor,
        "guardian snapshot descriptors drifted",
    )
    authority_source = _descriptor_shape(
        guardian_record.get("service_authority_source"),
        label="guardian authority source",
    )
    lifecycle_source = _descriptor_shape(
        guardian_record.get("service_lifecycle_source"),
        label="guardian lifecycle source",
    )
    _require(
        authority_source["size_bytes"] == authority_descriptor["size_bytes"]
        and authority_source["sha256"] == authority_descriptor["sha256"]
        and lifecycle_source["size_bytes"] == lifecycle_descriptor["size_bytes"]
        and lifecycle_source["sha256"] == lifecycle_descriptor["sha256"],
        "guardian source/snapshot custody drifted",
    )
    chain, _authority_payload, _lifecycle_payload, _authority_path, _lifecycle_path = (
        _validate_chain(
            root=root,
            qualification_transaction_receipt_path=receipt[
                "qualification_input_transaction"
            ]["receipt"]["path"],
            preprocessing_contract_path=receipt["guardian_preprocessing"][
                "contract"
            ]["path"],
            preprocessing_materialization_receipt_path=receipt[
                "guardian_preprocessing"
            ]["materialization_receipt"]["path"],
            runtime_input_materialization_receipt_path=receipt[
                "runtime_input_materialization"
            ]["receipt"]["path"],
            guardian_service_authority_path=authority_path,
            guardian_service_lifecycle_path=lifecycle_path,
            pilot_root=receipt["pilot_execution"]["pilot_root"]["path"],
            checkpoint_path=receipt["pilot_execution"]["checkpoint"]["path"],
            dependencies=dependencies,
            guardian_authority_binding_descriptor=authority_source,
        )
    )
    _require(
        receipt["qualification_input_transaction"]
        == chain["qualification_input_transaction"]
        and receipt["guardian_preprocessing"] == chain["guardian_preprocessing"]
        and receipt["runtime_input_materialization"]
        == chain["runtime_input_materialization"]
        and receipt["pilot_execution"] == chain["pilot_execution"],
        "execution closure upstream chain drifted",
    )
    semantic_guardian = chain["guardian"]
    for field, value in semantic_guardian.items():
        _require(
            guardian_record.get(field) == value,
            f"execution closure guardian field drifted: {field}",
        )
    return {
        "receipt": receipt,
        "receipt_descriptor": receipt_descriptor,
        "receipt_sha256": receipt_identity,
        "authority": authority_snapshot,
        "lifecycle": lifecycle_snapshot,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--qualification-transaction-receipt", type=Path, required=True)
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument("--preprocessing-materialization-receipt", type=Path, required=True)
    parser.add_argument("--runtime-input-materialization-receipt", type=Path, required=True)
    parser.add_argument("--guardian-service-authority", type=Path, required=True)
    parser.add_argument("--guardian-service-lifecycle", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_publication_policy_qualification_execution_closure_v1(
            project_root=args.project_root,
            qualification_transaction_receipt_path=(
                args.qualification_transaction_receipt
            ),
            preprocessing_contract_path=args.preprocessing_contract,
            preprocessing_materialization_receipt_path=(
                args.preprocessing_materialization_receipt
            ),
            runtime_input_materialization_receipt_path=(
                args.runtime_input_materialization_receipt
            ),
            guardian_service_authority_path=args.guardian_service_authority,
            guardian_service_lifecycle_path=args.guardian_service_lifecycle,
            pilot_root=args.pilot_root,
            checkpoint_path=args.checkpoint,
            output_dir=args.output_dir,
        )
    except (OSError, QualificationExecutionClosureV1Error) as error:
        print(f"qualification execution closure blocked: {error}", file=sys.stderr)
        return 78
    print(
        json.dumps(
            {
                key: value.as_posix() if isinstance(value, Path) else value
                for key, value in result.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND",
    "AUTHORITY_SNAPSHOT_FILENAME",
    "DEFAULT_DEPENDENCIES",
    "ExecutionClosureDependenciesV1",
    "LIFECYCLE_SNAPSHOT_FILENAME",
    "QualificationExecutionClosureV1Error",
    "RECEIPT_FILENAME",
    "SCHEMA_VERSION",
    "load_publication_policy_qualification_execution_closure_v1",
    "materialize_publication_policy_qualification_execution_closure_v1",
    "matrix_sha256",
]
