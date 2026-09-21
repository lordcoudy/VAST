#!/usr/bin/env python3
"""Own the bounded, engineering-only GStreamer analytics sidecar lifecycle.

This owner starts and attests exactly eight branch/resource workers, constructs
the already-fail-closed :class:`AnalyticsExecutionBridge`, and only then binds
the native GStreamer front socket.  Its evidence is deliberately labelled
engineering/non-publication; policy qualification and accepted benchmark
sidecars remain separate gates.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from analytics_execution_endpoint import (
    expected_capability_from_binding_and_probe,
)
from analytics_execution_protocol import (
    BRANCHES,
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    MAX_CONTROL_BYTES,
    MAX_TENSOR_BYTES,
    PeerClosed,
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    TRANSPORT_KIND,
    canonical_json_bytes,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
    valid_image_id,
    verify_sealed_memfd,
)
from analytics_execution_worker import validate_runtime_probe
from publication_guardian_preprocessing_contract_v1 import (
    DirectoryFdCustodyV1,
    GuardianPreprocessingContractV1Error,
    load_guardian_preprocessing_contract_v1,
    read_file_bytes_fd_custody_v1,
    validate_guardian_preprocessing_authority_v1,
)
from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
    AcceptedPolicyGuardianPreprocessingContractV1Error,
    RECEIPT_KIND as ACCEPTED_POLICY_PREPROCESSING_RECEIPT_KIND,
    load_accepted_policy_guardian_preprocessing_contract_v1,
    validate_accepted_policy_guardian_preprocessing_authority_v1,
)
from publication_guardian_runtime_expectations_v1 import (
    GuardianRuntimeExpectationsV1Error,
    runtime_expectations_from_preprocessing_receipt_v1,
)


RESOURCES = ("cpu", "gpu")
ENGINE_BY_RESOURCE = {
    "cpu": ENGINE_OPENVINO_CPU,
    "gpu": ENGINE_TENSORRT_CUDA,
}
RESOURCE_BY_ENGINE = {value: key for key, value in ENGINE_BY_RESOURCE.items()}
EXPECTED_KEYS = {
    (branch, resource) for branch in BRANCHES for resource in RESOURCES
}
SIDECAR_LIFECYCLE_KIND = "vast_gstreamer_analytics_sidecar_engineering_lifecycle"
SIDECAR_CALL_KIND = "vast_gstreamer_analytics_sidecar_engineering_call"
SIDECAR_CLAIM_STATUS = "engineering_complete_nonpublication"
PRODUCTION_SERVICE_AUTHORITY_KIND = (
    "vast_gstreamer_analytics_production_service_authority_v1"
)
PRODUCTION_SERVICE_LIFECYCLE_KIND = (
    "vast_gstreamer_analytics_production_service_lifecycle_v1"
)
PRODUCTION_GUARDIAN_STOP_ATTESTATION_KIND = (
    "vast_gstreamer_analytics_guardian_stop_attestation_v1"
)
RETIRED_SOCKET_NODE_KIND = (
    "vast_gstreamer_analytics_retired_socket_node_v1"
)
PRODUCTION_RETIRED_SOCKET_NODE_COUNT = len(BRANCHES) * len(RESOURCES) + 2
PRODUCTION_SERVICE_MODE = "bounded_production_guardian_v1"
PRODUCTION_FROZEN_FPS = 600
PRODUCTION_FROZEN_STREAMS = 6
PRODUCTION_FROZEN_BRANCHES = len(BRANCHES)
PRODUCTION_CELL_SECONDS_UPPER_BOUND = 240
PRODUCTION_CELL_COUNT = 32 + 560 + 560 + 5600
PRODUCTION_CONNECTIONS_PER_CELL_UPPER_BOUND = 24
PRODUCTION_CAPACITY_MARGIN_NUMERATOR = 5
PRODUCTION_CAPACITY_MARGIN_DENOMINATOR = 4
PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM = (
    PRODUCTION_FROZEN_FPS
    * PRODUCTION_FROZEN_STREAMS
    * PRODUCTION_FROZEN_BRANCHES
    * PRODUCTION_CELL_SECONDS_UPPER_BOUND
    * PRODUCTION_CAPACITY_MARGIN_NUMERATOR
    // PRODUCTION_CAPACITY_MARGIN_DENOMINATOR
)
PRODUCTION_MAX_CONNECTIONS_MINIMUM = (
    PRODUCTION_CELL_COUNT
    * PRODUCTION_CONNECTIONS_PER_CELL_UPPER_BOUND
    * PRODUCTION_CAPACITY_MARGIN_NUMERATOR
    // PRODUCTION_CAPACITY_MARGIN_DENOMINATOR
)
PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM = (
    PRODUCTION_FROZEN_FPS
    * PRODUCTION_FROZEN_STREAMS
    * PRODUCTION_FROZEN_BRANCHES
    * PRODUCTION_CELL_SECONDS_UPPER_BOUND
    * PRODUCTION_CELL_COUNT
    * PRODUCTION_CAPACITY_MARGIN_NUMERATOR
    // PRODUCTION_CAPACITY_MARGIN_DENOMINATOR
)
PRODUCTION_REQUEST_LIMIT = 2**63 - 1
PEER_IDENTITY_MODE_NATIVE_VISIBLE = "native-visible"
PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0 = (
    "namespace-hidden-wsl2-docker-desktop"
)
PEER_IDENTITY_POLICY_VERSION = 2
PEERCRED_PLATFORM_DOMAIN = b"VAST:analytics-peercred-pid0-platform:v1\0"
_PEERCRED_PLATFORM_KIND = "vast_analytics_peercred_pid0_platform_observation"
_NATIVE_SOCKET_CUSTODY_KIND = "vast_analytics_native_ext4_socket_custody"
_WSL_OSRELEASE_PATH = Path("/proc/sys/kernel/osrelease")
_WSL_OSRELEASE_MAX_BYTES = 255
_WSL2_OSRELEASE_MARKER = "-microsoft-standard-WSL2"
_WSL2_OSRELEASE_RE = re.compile(
    r"[1-9][0-9]{0,2}(?:\.[0-9]{1,3}){2,3}-microsoft-standard-WSL2\Z"
)
_DOCKER_DESKTOP_SERVER_VERSION = "29.7.2"
# Explicit observed builds for the exact server/platform checks below. Keep the
# actual commit in evidence so historical observations retain their identities.
_DOCKER_DESKTOP_CONTAINERD_COMMIT_IDS = (
    "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66",
    "aad11006b869517fcd3009450b6f82da282e1a9b",
)
_DOCKER_DESKTOP_REQUIRED_RUNTIMES = (
    "io.containerd.runc.v2",
    "nvidia",
    "runc",
)
_LINUX_EXT_FILESYSTEM_MAGIC = 0xEF53
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_INDEX_FIELDS = {
    "schema_version",
    "artifact_kind",
    "protocol_identity_sha256",
    "execution_config_identity_sha256",
    "model_parity_manifest_identity_sha256",
    "worker_project_root",
    "worker_implementation_sha256",
    "bindings_identity_sha256",
    "files",
    "identity",
}
_PRODUCTION_RUNTIME_EXPECTATION_FIELDS = {
    "execution_config_identity_sha256",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
    "preprocessing_contract_content_sha256",
}


class SidecarError(RuntimeError):
    """The sidecar lifecycle, evidence, or ownership contract was violated."""


class WorkerHandle(Protocol):
    pid: int

    def expected_peer_pid(self, timeout_s: float) -> int: ...

    def poll(self) -> int | None: ...

    def wait(self, timeout_s: float) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class WorkerProcessFactory(Protocol):
    def probe(
        self, resource: str, worker_config: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...

    def start(self, spec: "WorkerLaunchSpec") -> WorkerHandle: ...


class BridgeLike(Protocol):
    def worker_protocol_handshake(
        self, value: Mapping[str, Any]
    ) -> tuple[tuple[str, str], Mapping[str, Any]]: ...

    def execute_worker_protocol(
        self,
        value: Mapping[str, Any],
        payload: bytes | bytearray | memoryview,
        *,
        route: tuple[str, str],
    ) -> tuple[Mapping[str, Any], bytes]: ...

    def execute(
        self, value: Mapping[str, Any], payload: bytes | bytearray | memoryview
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


BridgeFactory = Callable[..., BridgeLike]


@dataclass(frozen=True)
class WorkerLaunchSpec:
    branch: str
    resource: str
    engine: str
    binding_path: Path
    socket_path: Path
    container_binding_path: str
    container_socket_path: str
    worker_config: Mapping[str, Any]
    max_requests: int
    lifecycle_id: str


@dataclass(frozen=True)
class MaterializedBindingSet:
    root: Path
    index: Mapping[str, Any]
    bindings: Mapping[tuple[str, str], Mapping[str, Any]]
    capabilities: Mapping[tuple[str, str], Mapping[str, Any]]
    binding_paths: Mapping[tuple[str, str], Path]


@dataclass
class _OwnedSocket:
    path: Path
    identity: tuple[int, int, int]
    listener: socket.socket | None
    retirement_state: str = "active"
    retired_name: str | None = None
    retirement_record: dict[str, Any] | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SidecarError(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be a mapping")
    return value


def _exact(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    result = _mapping(value, label)
    _require(set(result) == fields, f"{label} fields have drifted")
    return result


def _sha(value: Any, label: str) -> str:
    result = str(value or "")
    _require(
        _SHA256_RE.fullmatch(result) is not None,
        f"{label} must be a lowercase SHA-256",
    )
    return result


def _safe_id(value: Any, label: str) -> str:
    result = str(value or "")
    _require(_SAFE_ID_RE.fullmatch(result) is not None, f"{label} is invalid")
    return result


def _canonical_clone(value: Mapping[str, Any]) -> dict[str, Any]:
    cloned = json.loads(canonical_json_bytes(dict(value)))
    _require(type(cloned) is dict, "canonical mapping clone failed")
    return cloned


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except (FileNotFoundError, OSError):
        return False
    return bool(
        attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    )


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _canonical_directory(
    path: Path | str,
    *,
    label: str,
    reject_cwd_or_parent: bool = False,
) -> Path:
    lexical = _absolute(path)
    _require(lexical != Path(lexical.anchor), f"{label} must not be a filesystem root")
    _require(not _is_reparse(lexical), f"{label} is a symlink, alias, or reparse point")
    _require(lexical.is_dir(), f"{label} is missing or not a directory")
    _require(lexical.resolve() == lexical, f"{label} is a symlink or alias")
    if reject_cwd_or_parent:
        cwd = Path.cwd().resolve()
        _require(
            lexical != cwd and lexical not in cwd.parents,
            f"{label} must not be the current directory or its parent",
        )
    return lexical


def _canonical_file(path: Path, *, parent: Path, label: str) -> Path:
    lexical = _absolute(path)
    _require(lexical.parent == parent, f"{label} escaped its directory")
    _require(not _is_reparse(lexical), f"{label} is a symlink, alias, or reparse point")
    _require(lexical.is_file(), f"{label} is missing or not a regular file")
    _require(lexical.resolve() == lexical, f"{label} is a symlink or alias")
    return lexical


def _stat_identity(path: Path) -> tuple[int, int, int]:
    metadata = path.lstat()
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(stat.S_IFMT(metadata.st_mode)),
    )


def _sha256_file_stable(path: Path, *, label: str) -> tuple[str, int]:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    _require(before_identity == after_identity, f"{label} changed while it was hashed")
    return digest.hexdigest(), int(before.st_size)


def _read_canonical_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = path.read_bytes()
        _require(payload.endswith(b"\n"), f"{label} lacks its canonical newline")
        value = json.loads(payload.decode("utf-8"))
        _require(isinstance(value, dict), f"{label} must be a mapping")
        _require(
            canonical_json_bytes(value) + b"\n" == payload,
            f"{label} is not canonical JSON",
        )
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarError(f"cannot read {label}: {error}") from error


def _execution_config_identity(config: Mapping[str, Any]) -> str:
    identity = _mapping(config.get("identity"), "analytics execution config identity")
    _require(identity.get("algorithm") == "sha256", "analytics execution config identity algorithm drifted")
    return _sha(identity.get("sha256"), "analytics execution config identity")


def _validate_preprocessing_authority_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    kind = value.get("artifact_kind")
    try:
        if kind == "vast_guardian_preprocessing_contract_authority_v1":
            return validate_guardian_preprocessing_authority_v1(value)
        if kind == "vast_guardian_accepted_policy_preprocessing_contract_authority_v1":
            return validate_accepted_policy_guardian_preprocessing_authority_v1(value)
    except (
        GuardianPreprocessingContractV1Error,
        AcceptedPolicyGuardianPreprocessingContractV1Error,
    ) as error:
        raise SidecarError(
            f"analytics preprocessing contract authority is invalid: {error}"
        ) from error
    raise SidecarError("analytics preprocessing contract authority kind is unsupported")


def _validate_production_runtime_expectations_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    checked = _exact(
        value,
        _PRODUCTION_RUNTIME_EXPECTATION_FIELDS,
        "analytics external production runtime expectations",
    )
    images = _exact(
        checked.get("worker_image_ids"),
        set(RESOURCES),
        "analytics external production worker image IDs",
    )
    result = {
        field: _sha(
            checked.get(field),
            f"analytics external production {field}",
        )
        for field in _PRODUCTION_RUNTIME_EXPECTATION_FIELDS
        if field != "worker_image_ids"
    }
    result["worker_image_ids"] = {}
    for resource in RESOURCES:
        image_id = images.get(resource)
        _require(
            type(image_id) is str and valid_image_id(image_id),
            f"analytics external production {resource} worker image is invalid",
        )
        result["worker_image_ids"][resource] = image_id
    return result


def load_materialized_binding_set(
    binding_set_dir: Path | str,
    *,
    execution_config: Mapping[str, Any],
    runtime_probes: Mapping[str, Mapping[str, Any]],
) -> MaterializedBindingSet:
    """Rehash and assemble the exact eight binding/capability coordinates."""

    root = _canonical_directory(
        binding_set_dir, label="analytics materialized binding set"
    )
    index_path = _canonical_file(
        root / "index.json", parent=root, label="analytics binding index"
    )
    index = _exact(
        _read_canonical_json(index_path, label="analytics binding index"),
        _INDEX_FIELDS,
        "analytics binding index",
    )
    _require(index["schema_version"] == 1, "analytics binding index schema drifted")
    _require(
        index["artifact_kind"] == "vast_analytics_execution_worker_binding_set",
        "analytics binding index kind drifted",
    )
    _require(
        index["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256,
        "analytics binding index protocol identity drifted",
    )
    _require(
        index["execution_config_identity_sha256"]
        == _execution_config_identity(execution_config),
        "analytics binding index execution config identity mismatch",
    )
    core = {field: index[field] for field in _INDEX_FIELDS - {"identity"}}
    identity = _exact(
        index["identity"], {"algorithm", "sha256"}, "analytics binding index identity"
    )
    _require(
        identity["algorithm"] == "sha256"
        and identity["sha256"] == canonical_sha256(core),
        "analytics binding index identity mismatch",
    )
    workers = _exact(
        execution_config.get("workers"), {"cpu", "gpu"}, "analytics execution workers"
    )
    _require(
        set(runtime_probes) == set(RESOURCES),
        "analytics runtime probes must cover exact CPU/GPU resources",
    )
    checked_probes: dict[str, dict[str, Any]] = {}
    implementations: dict[str, str] = {}
    for resource in RESOURCES:
        engine = ENGINE_BY_RESOURCE[resource]
        try:
            probe = validate_runtime_probe(runtime_probes[resource], engine=engine)
        except ProtocolError as error:
            raise SidecarError(
                f"analytics {resource} runtime probe is invalid: {error}"
            ) from error
        worker = _mapping(workers[resource], f"analytics {resource} worker config")
        expected_implementation = _sha(
            worker.get("worker_implementation_sha256"),
            f"analytics {resource} configured implementation",
        )
        _require(
            probe["worker_implementation_sha256"] == expected_implementation,
            f"analytics {resource} runtime probe implementation mismatch",
        )
        checked_probes[resource] = probe
        implementations[engine] = expected_implementation
    _require(
        index["worker_implementation_sha256"] == implementations,
        "analytics binding index implementation inventory mismatch",
    )

    expected_names = {
        f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
        for branch, resource in EXPECTED_KEYS
    }
    raw_records = index["files"]
    _require(
        type(raw_records) is list and len(raw_records) == len(EXPECTED_KEYS),
        "analytics binding index must cover exact 8 files",
    )
    records: dict[str, Mapping[str, Any]] = {}
    for position, raw_record in enumerate(raw_records):
        record = _exact(
            raw_record,
            {"path", "bytes", "sha256"},
            f"analytics binding file record {position}",
        )
        name = str(record["path"])
        _require(
            Path(name).name == name
            and "/" not in name
            and "\\" not in name
            and name in expected_names
            and name not in records,
            "analytics binding index file coverage is invalid",
        )
        _require(
            type(record["bytes"]) is int and record["bytes"] > 0,
            "analytics binding file byte count is invalid",
        )
        _sha(record["sha256"], "analytics binding file SHA-256")
        records[name] = record
    _require(set(records) == expected_names, "analytics binding index coverage is not exact 8")
    actual_names = {path.name for path in root.iterdir()}
    _require(
        actual_names == expected_names | {"index.json"},
        "analytics materialized binding directory has unexpected entries",
    )

    bindings: dict[tuple[str, str], Mapping[str, Any]] = {}
    capabilities: dict[tuple[str, str], Mapping[str, Any]] = {}
    paths: dict[tuple[str, str], Path] = {}
    identities: dict[str, str] = {}
    for branch in BRANCHES:
        for resource in RESOURCES:
            engine = ENGINE_BY_RESOURCE[resource]
            name = f"{branch}.{engine}.json"
            path = _canonical_file(
                root / name, parent=root, label=f"analytics binding {branch}/{resource}"
            )
            digest, byte_count = _sha256_file_stable(
                path, label=f"analytics binding {branch}/{resource}"
            )
            record = records[name]
            _require(
                digest == record["sha256"],
                f"analytics binding {branch}/{resource} SHA-256 mismatch",
            )
            _require(
                byte_count == record["bytes"],
                f"analytics binding {branch}/{resource} bytes mismatch",
            )
            value = _read_canonical_json(
                path, label=f"analytics binding {branch}/{resource}"
            )
            try:
                capability = expected_capability_from_binding_and_probe(
                    binding=value,
                    runtime_probe=checked_probes[resource],
                    resource=resource,
                )
            except ProtocolError as error:
                raise SidecarError(
                    f"analytics binding {branch}/{resource} is invalid: {error}"
                ) from error
            _require(
                capability["branch"] == branch,
                f"analytics binding {branch}/{resource} branch mismatch",
            )
            _require(
                capability["worker_image_id"]
                == _mapping(
                    workers[resource], f"analytics {resource} worker config"
                ).get("image_id"),
                f"analytics binding {branch}/{resource} image identity mismatch",
            )
            key = (branch, resource)
            bindings[key] = value
            capabilities[key] = capability
            paths[key] = path
            identities[name] = canonical_sha256(value)
    _require(
        index["bindings_identity_sha256"] == canonical_sha256(identities),
        "analytics binding-set identity mismatch",
    )
    return MaterializedBindingSet(
        root=root,
        index=dict(index),
        bindings=bindings,
        capabilities=capabilities,
        binding_paths=paths,
    )


def _open_owned_listener(
    path: Path, *, backlog: int, atomic_publish: bool = False
) -> _OwnedSocket:
    _require(
        type(backlog) is int and 1 <= backlog <= 128,
        "analytics sidecar listener backlog is invalid",
    )
    _require(
        path.is_absolute()
        and path.parent.is_dir()
        and path.parent.resolve() == path.parent,
        "analytics sidecar socket parent is invalid",
    )
    _require(
        not os.path.lexists(path),
        f"analytics sidecar socket already exists: {path}",
    )
    _require(
        len(os.fsencode(path)) < 108 and "\x00" not in str(path),
        "analytics sidecar socket path is invalid",
    )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    if atomic_publish:
        _require(
            os.name == "posix",
            "atomic analytics sidecar socket publication requires POSIX",
        )
    try:
        try:
            listener.bind(str(path))
        except OSError as error:
            if os.path.lexists(path):
                raise SidecarError(
                    f"analytics sidecar socket already exists: {path}"
                ) from error
            raise SidecarError(
                f"cannot bind analytics sidecar socket: {path}"
            ) from error
        listener.listen(backlog)
        metadata = path.lstat()
        _require(
            stat.S_ISSOCK(metadata.st_mode),
            "analytics sidecar listener did not create a socket node",
        )
        return _OwnedSocket(path, _stat_identity(path), listener)
    except BaseException:
        listener.close()
        raise


def _renameat2_noreplace_socket_node(
    source_directory_fd: int,
    source_name: str,
    target_directory_fd: int,
    target_name: str,
) -> None:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and type(source_directory_fd) is int
        and source_directory_fd >= 0
        and type(target_directory_fd) is int
        and target_directory_fd >= 0,
        "analytics socket renameat2 custody is unavailable",
    )
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    _require(
        renameat2 is not None,
        "analytics socket renameat2 no-replace is unavailable",
    )
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_directory_fd,
        os.fsencode(source_name),
        target_directory_fd,
        os.fsencode(target_name),
        1,
    )
    if result == 0:
        return
    code = ctypes.get_errno()
    raise SidecarError(
        f"analytics socket no-replace retirement failed: errno {code}"
    )


def _retired_socket_record_v1(
    value: _OwnedSocket,
    *,
    lifecycle_id: str,
    retirement_custody: DirectoryFdCustodyV1,
    metadata: os.stat_result,
) -> dict[str, Any]:
    _require(
        value.retired_name is not None,
        "analytics socket retirement name is unavailable",
    )
    directory_metadata = os.fstat(retirement_custody.directory_fd)
    core = {
        "schema_version": 1,
        "artifact_kind": RETIRED_SOCKET_NODE_KIND,
        "lifecycle_id": lifecycle_id,
        "active_name": value.path.name,
        "retired_name": value.retired_name,
        "retirement_state": "retired_verified",
        "socket_identity": {
            "st_dev": int(metadata.st_dev),
            "st_ino": int(metadata.st_ino),
            "st_mode_type": int(stat.S_IFMT(metadata.st_mode)),
            "st_nlink": int(metadata.st_nlink),
        },
        "retirement_directory": {
            "path": str(retirement_custody.path),
            "st_dev": int(directory_metadata.st_dev),
            "st_ino": int(directory_metadata.st_ino),
        },
    }
    return {
        **core,
        "identity": {
            "algorithm": "sha256",
            "sha256": canonical_sha256(core),
        },
    }


def _validate_retired_socket_record_v1(
    value: Mapping[str, Any],
    *,
    expected_lifecycle_id: str,
) -> dict[str, Any]:
    record = dict(
        _exact(
            value,
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
            "analytics retired socket record",
        )
    )
    active_name = str(record.get("active_name") or "")
    retired_name = str(record.get("retired_name") or "")
    _require(
        record.get("schema_version") == 1
        and record.get("artifact_kind") == RETIRED_SOCKET_NODE_KIND
        and record.get("lifecycle_id") == expected_lifecycle_id
        and record.get("retirement_state") == "retired_verified"
        and re.fullmatch(r"[A-Za-z0-9._-]+", active_name) is not None
        and active_name not in {".", ".."}
        and re.fullmatch(r"[A-Za-z0-9._-]+", retired_name) is not None
        and retired_name not in {".", ".."},
        "analytics retired socket record binding drifted",
    )
    socket_identity = dict(
        _exact(
            record.get("socket_identity"),
            {"st_dev", "st_ino", "st_mode_type", "st_nlink"},
            "analytics retired socket identity",
        )
    )
    _require(
        type(socket_identity.get("st_dev")) is int
        and socket_identity["st_dev"] >= 0
        and type(socket_identity.get("st_ino")) is int
        and socket_identity["st_ino"] > 0
        and socket_identity.get("st_mode_type") == stat.S_IFSOCK
        and socket_identity.get("st_nlink") == 1,
        "analytics retired socket identity drifted",
    )
    retirement_directory = dict(
        _exact(
            record.get("retirement_directory"),
            {"path", "st_dev", "st_ino"},
            "analytics socket retirement directory",
        )
    )
    retirement_path = Path(str(retirement_directory.get("path") or ""))
    _require(
        retirement_path.is_absolute()
        and type(retirement_directory.get("st_dev")) is int
        and retirement_directory["st_dev"] == socket_identity["st_dev"]
        and type(retirement_directory.get("st_ino")) is int
        and retirement_directory["st_ino"] > 0,
        "analytics socket retirement directory binding drifted",
    )
    record["socket_identity"] = socket_identity
    record["retirement_directory"] = retirement_directory
    identity = _exact(
        record.get("identity"),
        {"algorithm", "sha256"},
        "analytics retired socket record identity",
    )
    core = {key: item for key, item in record.items() if key != "identity"}
    _require(
        identity.get("algorithm") == "sha256"
        and identity.get("sha256") == canonical_sha256(core),
        "analytics retired socket record self-hash drifted",
    )
    record["identity"] = dict(identity)
    return record


def _validate_retired_socket_records_v1(
    value: Any,
    *,
    expected_lifecycle_id: str,
    expected_active_names: set[str] | None = None,
    expected_record_count: int | None = None,
    expected_retirement_directory: Path | None = None,
    verify_physical: bool = True,
) -> list[dict[str, Any]]:
    _require(
        type(value) is list,
        "analytics retired socket ledger must be a list",
    )
    records = [
        _validate_retired_socket_record_v1(
            _mapping(item, "analytics retired socket ledger entry"),
            expected_lifecycle_id=expected_lifecycle_id,
        )
        for item in value
    ]
    active_names = [item["active_name"] for item in records]
    retired_names = [item["retired_name"] for item in records]
    if expected_record_count is not None:
        _require(
            type(expected_record_count) is int
            and expected_record_count > 0
            and len(records) == expected_record_count
            and (
                expected_active_names is None
                or len(expected_active_names) == expected_record_count
            ),
            "analytics retired socket ledger cardinality drifted",
        )
    if expected_retirement_directory is not None:
        _require(
            expected_retirement_directory.is_absolute()
            and all(
                Path(item["retirement_directory"]["path"])
                == expected_retirement_directory
                for item in records
            ),
            "analytics socket retirement directory path binding drifted",
        )
    _require(
        len(active_names) == len(set(active_names))
        and len(retired_names) == len(set(retired_names))
        and (
            expected_active_names is None
            or set(active_names) == expected_active_names
        ),
        "analytics retired socket ledger coverage drifted",
    )
    if not records:
        _require(
            expected_active_names is None or expected_active_names == set(),
            "analytics retired socket ledger is unexpectedly empty",
        )
        return records
    directory_claims = {
        canonical_sha256(item["retirement_directory"])
        for item in records
    }
    _require(
        len(directory_claims) == 1,
        "analytics retired socket ledger spans multiple directories",
    )
    if verify_physical:
        retirement = records[0]["retirement_directory"]
        directory = Path(retirement["path"])
        _require(
            os.name == "posix"
            and not _is_reparse(directory)
            and directory.is_dir(),
            "analytics socket retirement directory is unavailable",
        )
        custody = DirectoryFdCustodyV1.open_existing(
            directory,
            label="analytics retired socket ledger directory",
        )
        try:
            opened = os.fstat(custody.directory_fd)
            _require(
                int(opened.st_dev) == retirement["st_dev"]
                and int(opened.st_ino) == retirement["st_ino"]
                and set(os.listdir(custody.directory_fd))
                == set(retired_names),
                "analytics socket retirement directory descriptor drifted",
            )
            for item in records:
                metadata = os.stat(
                    item["retired_name"],
                    dir_fd=custody.directory_fd,
                    follow_symlinks=False,
                )
                identity = item["socket_identity"]
                _require(
                    stat.S_ISSOCK(metadata.st_mode)
                    and int(metadata.st_nlink) == 1
                    and {
                        "st_dev": int(metadata.st_dev),
                        "st_ino": int(metadata.st_ino),
                        "st_mode_type": int(stat.S_IFMT(metadata.st_mode)),
                        "st_nlink": int(metadata.st_nlink),
                    }
                    == identity,
                    "analytics retired socket physical identity drifted",
                )
            custody.verify()
        finally:
            custody.close()
    return records


def _retire_owned_socket_via_custody(
    value: _OwnedSocket,
    directory_custody: DirectoryFdCustodyV1,
    retirement_custody: DirectoryFdCustodyV1,
    *,
    lifecycle_id: str,
) -> dict[str, Any]:
    _require(
        value.path.parent == directory_custody.path,
        "owned analytics socket escaped its held directory",
    )
    _require(
        _SAFE_ID_RE.fullmatch(lifecycle_id) is not None
        and len(lifecycle_id) == 32,
        "analytics socket retirement lifecycle_id is invalid",
    )
    directory_custody.verify()
    retirement_custody.verify()
    source_fd = directory_custody.directory_fd
    retirement_fd = retirement_custody.directory_fd
    source_metadata = os.fstat(source_fd)
    retirement_directory_metadata = os.fstat(retirement_fd)
    _require(
        int(source_metadata.st_dev) == int(retirement_directory_metadata.st_dev),
        "analytics socket retirement crossed filesystems",
    )
    expected_name = (
        f"{lifecycle_id}.{value.path.name}."
        f"{value.identity[0]:x}.{value.identity[1]:x}.sock"
    )
    _require(
        value.retired_name in {None, expected_name},
        "analytics socket retirement name drifted",
    )
    value.retired_name = expected_name
    if value.retirement_state == "active":
        _renameat2_noreplace_socket_node(
            source_fd,
            value.path.name,
            retirement_fd,
            expected_name,
        )
        value.retirement_state = "rename_committed"
        os.fsync(source_fd)
        os.fsync(retirement_fd)
    _require(
        value.retirement_state in {"rename_committed", "retired_verified"},
        "analytics socket retirement state drifted",
    )
    try:
        metadata = os.stat(
            expected_name,
            dir_fd=retirement_fd,
            follow_symlinks=False,
        )
        observed_identity = (
            int(metadata.st_dev),
            int(metadata.st_ino),
            int(stat.S_IFMT(metadata.st_mode)),
        )
        if not (
            observed_identity == value.identity
            and stat.S_ISSOCK(metadata.st_mode)
            and int(metadata.st_nlink) == 1
        ):
            raise SidecarError(
                f"retired analytics socket identity changed: {value.path.name}"
            )
        try:
            os.stat(value.path.name, dir_fd=source_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SidecarError(
                f"analytics socket active name was recreated: {value.path.name}"
            )
        record = _retired_socket_record_v1(
            value,
            lifecycle_id=lifecycle_id,
            retirement_custody=retirement_custody,
            metadata=metadata,
        )
        if value.retirement_record is not None:
            _require(
                value.retirement_record == record,
                "analytics socket retirement record drifted",
            )
        value.retirement_state = "retired_verified"
        value.retirement_record = record
        directory_custody.verify()
        retirement_custody.verify()
        return _canonical_clone(record)
    except SidecarError:
        raise
    except OSError as error:
        raise SidecarError(
            f"owned analytics socket custody retirement failed: {value.path.name}"
        ) from error


def _close_owned_socket(
    value: _OwnedSocket,
    *,
    directory_custody: DirectoryFdCustodyV1 | None = None,
    retirement_custody: DirectoryFdCustodyV1 | None = None,
    lifecycle_id: str | None = None,
) -> dict[str, Any] | None:
    if value.listener is not None:
        try:
            value.listener.close()
        except OSError:
            pass
        value.listener = None
    if os.name == "posix":
        _require(
            directory_custody is not None
            and retirement_custody is not None
            and lifecycle_id is not None,
            "POSIX analytics socket retirement custody is unavailable",
        )
        return _retire_owned_socket_via_custody(
            value,
            directory_custody,
            retirement_custody,
            lifecycle_id=lifecycle_id,
        )
    if not os.path.lexists(value.path):
        return
    _require(
        not _is_reparse(value.path)
        and _stat_identity(value.path) == value.identity
        and stat.S_ISSOCK(value.path.lstat().st_mode),
        f"owned analytics socket identity changed: {value.path.name}",
    )
    value.path.unlink()
    return None


def _peer_credentials_raw(connection: socket.socket) -> bytes:
    _require(
        hasattr(socket, "SO_PEERCRED"),
        "analytics sidecar requires Linux SO_PEERCRED",
    )
    try:
        credentials = bytes(connection.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        ))
        pid, uid, gid = struct.unpack("3i", credentials)
    except (OSError, struct.error) as error:
        raise SidecarError(f"cannot read analytics worker peer credentials: {error}") from error
    _require(
        len(credentials) == struct.calcsize("3i")
        and pid >= 0
        and uid >= 0
        and gid >= 0,
        "analytics worker peer credentials are invalid",
    )
    return credentials


def _docker_desktop_platform_projection(
    value: Mapping[str, Any],
    *,
    osrelease: str,
) -> dict[str, Any]:
    info = _mapping(value, "Docker Desktop info")
    runtimes = _mapping(info.get("Runtimes"), "Docker Desktop runtimes")
    _require(
        set(_DOCKER_DESKTOP_REQUIRED_RUNTIMES).issubset(runtimes)
        and all(type(name) is str and name for name in runtimes),
        "Docker Desktop runtime inventory drifted",
    )
    driver_status = info.get("DriverStatus")
    required_driver_status = ["driver-type", "io.containerd.snapshotter.v1"]
    _require(
        type(driver_status) is list
        and 0 < len(driver_status) <= 32
        and all(
            type(item) is list
            and len(item) == 2
            and all(type(part) is str and 0 < len(part) <= 256 for part in item)
            for item in driver_status
        )
        and driver_status.count(required_driver_status) == 1,
        "Docker Desktop containerd snapshotter drifted",
    )
    containerd_commit = info.get("ContainerdCommit")
    _require(
        isinstance(containerd_commit, Mapping)
        and type(containerd_commit.get("ID")) is str
        and containerd_commit.get("ID")
        in _DOCKER_DESKTOP_CONTAINERD_COMMIT_IDS,
        "Docker Desktop containerd commit drifted",
    )
    projection = {
        "name": info.get("Name"),
        "operating_system": info.get("OperatingSystem"),
        "kernel_version": info.get("KernelVersion"),
        "server_version": info.get("ServerVersion"),
        "os_type": info.get("OSType"),
        "driver": info.get("Driver"),
        "driver_status": [required_driver_status],
        "default_runtime": info.get("DefaultRuntime"),
        "containerd_commit": {
            "ID": containerd_commit["ID"]
        },
        "required_runtimes": list(_DOCKER_DESKTOP_REQUIRED_RUNTIMES),
    }
    _require(
        projection
        == {
            "name": "docker-desktop",
            "operating_system": "Docker Desktop",
            "kernel_version": osrelease,
            "server_version": _DOCKER_DESKTOP_SERVER_VERSION,
            "os_type": "linux",
            "driver": "overlayfs",
            "driver_status": [["driver-type", "io.containerd.snapshotter.v1"]],
            "default_runtime": "runc",
            "containerd_commit": {
                "ID": containerd_commit["ID"]
            },
            "required_runtimes": list(_DOCKER_DESKTOP_REQUIRED_RUNTIMES),
        },
        "Docker Desktop WSL2 platform facts drifted",
    )
    return projection


def _build_peercred_pid0_platform_observation(
    osrelease_raw: bytes,
    docker_info: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        type(osrelease_raw) is bytes
        and 0 < len(osrelease_raw) <= _WSL_OSRELEASE_MAX_BYTES
        and b"\0" not in osrelease_raw
        and b"\r" not in osrelease_raw
        and osrelease_raw.endswith(b"\n")
        and osrelease_raw.count(b"\n") == 1,
        "WSL osrelease framing drifted",
    )
    try:
        osrelease_text = osrelease_raw.decode("ascii")
    except UnicodeError as error:
        raise SidecarError("WSL osrelease is not ASCII") from error
    osrelease = osrelease_text[:-1]
    _require(
        _WSL2_OSRELEASE_RE.fullmatch(osrelease) is not None,
        "WSL2 osrelease marker drifted",
    )
    docker_projection = _docker_desktop_platform_projection(
        docker_info,
        osrelease=osrelease,
    )
    core = {
        "schema_version": 1,
        "artifact_kind": _PEERCRED_PLATFORM_KIND,
        "docker_info": docker_projection,
        "docker_info_sha256": canonical_sha256(docker_projection),
        "wsl_osrelease": {
            "path": str(_WSL_OSRELEASE_PATH),
            "raw_ascii": osrelease_text,
            "size_bytes": len(osrelease_raw),
            "sha256": hashlib.sha256(osrelease_raw).hexdigest(),
            "marker": _WSL2_OSRELEASE_MARKER,
            "marker_present": True,
        },
    }
    observed = {
        **core,
        "observation_sha256": hashlib.sha256(
            PEERCRED_PLATFORM_DOMAIN + canonical_json_bytes(core) + b"\n"
        ).hexdigest(),
    }
    return _validate_peercred_pid0_platform_observation(observed)


def _validate_peercred_pid0_platform_observation(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    observed = dict(
        _exact(
            value,
            {
                "schema_version",
                "artifact_kind",
                "docker_info",
                "docker_info_sha256",
                "wsl_osrelease",
                "observation_sha256",
            },
            "peercred PID-zero platform observation",
        )
    )
    _require(
        observed.get("schema_version") == 1
        and observed.get("artifact_kind") == _PEERCRED_PLATFORM_KIND,
        "peercred PID-zero platform header drifted",
    )
    wsl = dict(
        _exact(
            observed.get("wsl_osrelease"),
            {
                "path",
                "raw_ascii",
                "size_bytes",
                "sha256",
                "marker",
                "marker_present",
            },
            "WSL osrelease observation",
        )
    )
    _require(type(wsl.get("raw_ascii")) is str, "WSL osrelease raw text drifted")
    try:
        raw = wsl["raw_ascii"].encode("ascii")
    except UnicodeError as error:
        raise SidecarError("WSL osrelease observation is not ASCII") from error
    _require(
        wsl.get("path") == str(_WSL_OSRELEASE_PATH)
        and 0 < len(raw) <= _WSL_OSRELEASE_MAX_BYTES
        and b"\0" not in raw
        and b"\r" not in raw
        and raw.endswith(b"\n")
        and raw.count(b"\n") == 1
        and wsl.get("size_bytes") == len(raw)
        and wsl.get("sha256") == hashlib.sha256(raw).hexdigest()
        and wsl.get("marker") == _WSL2_OSRELEASE_MARKER
        and wsl.get("marker_present") is True,
        "WSL osrelease observation identity drifted",
    )
    osrelease = wsl["raw_ascii"][:-1]
    _require(
        _WSL2_OSRELEASE_RE.fullmatch(osrelease) is not None,
        "WSL2 osrelease observation marker drifted",
    )
    docker = dict(
        _exact(
            observed.get("docker_info"),
            {
                "name",
                "operating_system",
                "kernel_version",
                "server_version",
                "os_type",
                "driver",
                "driver_status",
                "default_runtime",
                "containerd_commit",
                "required_runtimes",
            },
            "Docker Desktop platform projection",
        )
    )
    containerd_commit = _exact(
        docker.get("containerd_commit"), {"ID"}, "Docker Desktop containerd commit"
    )
    _require(
        type(containerd_commit.get("ID")) is str
        and containerd_commit["ID"] in _DOCKER_DESKTOP_CONTAINERD_COMMIT_IDS,
        "Docker Desktop containerd commit drifted",
    )
    _require(
        docker
        == {
            "name": "docker-desktop",
            "operating_system": "Docker Desktop",
            "kernel_version": osrelease,
            "server_version": _DOCKER_DESKTOP_SERVER_VERSION,
            "os_type": "linux",
            "driver": "overlayfs",
            "driver_status": [["driver-type", "io.containerd.snapshotter.v1"]],
            "default_runtime": "runc",
            "containerd_commit": {
                "ID": containerd_commit["ID"]
            },
            "required_runtimes": list(_DOCKER_DESKTOP_REQUIRED_RUNTIMES),
        }
        and observed.get("docker_info_sha256") == canonical_sha256(docker),
        "Docker Desktop platform projection identity drifted",
    )
    core = {
        key: observed[key]
        for key in (
            "schema_version",
            "artifact_kind",
            "docker_info",
            "docker_info_sha256",
            "wsl_osrelease",
        )
    }
    _require(
        type(observed.get("observation_sha256")) is str
        and _SHA256_RE.fullmatch(observed["observation_sha256"]) is not None
        and observed["observation_sha256"]
        == hashlib.sha256(
            PEERCRED_PLATFORM_DOMAIN + canonical_json_bytes(core) + b"\n"
        ).hexdigest(),
        "peercred PID-zero platform identity drifted",
    )
    return observed


def _observe_peercred_pid0_platform_observation(
    *,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    osrelease_path: Path = _WSL_OSRELEASE_PATH,
) -> dict[str, Any]:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and osrelease_path == _WSL_OSRELEASE_PATH
        and int(getattr(os, "O_NOFOLLOW", 0)) != 0,
        "peercred PID-zero platform observation requires exact Linux custody",
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            osrelease_path,
            os.O_RDONLY
            | int(os.O_NOFOLLOW)
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        before = os.fstat(descriptor)
        named_before = os.stat(osrelease_path, follow_symlinks=False)
        before_identity = (
            int(before.st_dev),
            int(before.st_ino),
            int(before.st_mode),
            int(before.st_uid),
            int(before.st_gid),
        )
        _require(
            stat.S_ISREG(before.st_mode)
            and before_identity
            == (
                int(named_before.st_dev),
                int(named_before.st_ino),
                int(named_before.st_mode),
                int(named_before.st_uid),
                int(named_before.st_gid),
            )
            and stat.S_IMODE(before.st_mode) == 0o444
            and before.st_uid == 0
            and before.st_gid == 0
            and before.st_nlink == 1,
            "WSL osrelease file custody drifted",
        )
        payload = bytearray()
        while len(payload) <= _WSL_OSRELEASE_MAX_BYTES:
            chunk = os.read(
                descriptor,
                _WSL_OSRELEASE_MAX_BYTES + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        _require(
            0 < len(payload) <= _WSL_OSRELEASE_MAX_BYTES,
            "WSL osrelease exceeded its bounded read",
        )
        completed = command_runner(
            ["docker", "info", "--format={{json .}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        _require(
            type(completed.stdout) is str
            and 0 < len(completed.stdout.encode("utf-8")) <= 1024 * 1024,
            "Docker Desktop info capture drifted",
        )
        def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                _require(key not in result, "Docker Desktop info has duplicate keys")
                result[key] = item
            return result

        try:
            docker_info = json.loads(
                completed.stdout,
                object_pairs_hook=unique_object,
                parse_constant=lambda item: (_ for _ in ()).throw(
                    SidecarError(f"invalid Docker Desktop JSON constant: {item}")
                ),
            )
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise SidecarError("Docker Desktop info is invalid JSON") from error
        _require(type(docker_info) is dict, "Docker Desktop info must be a mapping")
        after = os.fstat(descriptor)
        named_after = os.stat(osrelease_path, follow_symlinks=False)
        _require(
            before_identity
            == (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_mode),
                int(after.st_uid),
                int(after.st_gid),
            )
            == (
                int(named_after.st_dev),
                int(named_after.st_ino),
                int(named_after.st_mode),
                int(named_after.st_uid),
                int(named_after.st_gid),
            ),
            "WSL osrelease file identity changed during observation",
        )
        return _build_peercred_pid0_platform_observation(
            bytes(payload),
            docker_info,
        )
    except SidecarError:
        raise
    except (OSError, subprocess.SubprocessError) as error:
        raise SidecarError("cannot observe Docker Desktop WSL2 platform") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as error:
                raise SidecarError("cannot close WSL osrelease observation") from error


class _LinuxStatFs(ctypes.Structure):
    _fields_ = [
        ("f_type", ctypes.c_long),
        ("f_bsize", ctypes.c_long),
        ("f_blocks", ctypes.c_ulong),
        ("f_bfree", ctypes.c_ulong),
        ("f_bavail", ctypes.c_ulong),
        ("f_files", ctypes.c_ulong),
        ("f_ffree", ctypes.c_ulong),
        ("f_fsid", ctypes.c_int * 2),
        ("f_namelen", ctypes.c_long),
        ("f_frsize", ctypes.c_long),
        ("f_flags", ctypes.c_long),
        ("f_spare", ctypes.c_long * 4),
    ]


def _linux_fstatfs_magic(descriptor: int) -> int:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and type(descriptor) is int
        and descriptor >= 0,
        "analytics socket filesystem attestation requires Linux",
    )
    value = _LinuxStatFs()
    libc = ctypes.CDLL(None, use_errno=True)
    fstatfs = libc.fstatfs
    fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_LinuxStatFs)]
    fstatfs.restype = ctypes.c_int
    if fstatfs(descriptor, ctypes.byref(value)) != 0:
        error_number = ctypes.get_errno()
        raise SidecarError("cannot attest analytics socket filesystem") from OSError(
            error_number,
            os.strerror(error_number),
        )
    return int(value.f_type) & ((1 << (ctypes.sizeof(ctypes.c_long) * 8)) - 1)


def _native_ext4_private_socket_custody(
    socket_dir: Path | str,
    socket_path: Path | str,
) -> dict[str, Any]:
    directory = _canonical_directory(
        socket_dir,
        label="native analytics socket directory",
    )
    path = _absolute(socket_path)
    _require(
        path.parent == directory
        and not _is_reparse(path)
        and os.path.lexists(path),
        "native analytics socket escaped its directory or disappeared",
    )
    flags = (
        os.O_RDONLY
        | int(getattr(os, "O_CLOEXEC", 0))
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_NOFOLLOW", 0))
    )
    _require(
        int(getattr(os, "O_DIRECTORY", 0)) != 0
        and int(getattr(os, "O_NOFOLLOW", 0)) != 0,
        "native analytics socket directory custody is unavailable",
    )
    try:
        descriptor = os.open(directory, flags)
    except OSError as error:
        raise SidecarError("cannot open native analytics socket directory") from error
    try:
        root = os.fstat(descriptor)
        named_root = directory.lstat()
        root_identity = (int(root.st_dev), int(root.st_ino))
        _require(
            stat.S_ISDIR(root.st_mode)
            and root_identity
            == (int(named_root.st_dev), int(named_root.st_ino))
            and stat.S_IMODE(root.st_mode) == 0o700
            and root.st_uid == os.getuid()
            and root.st_gid == os.getgid()
            and root.st_nlink >= 2
            and _linux_fstatfs_magic(descriptor) == _LINUX_EXT_FILESYSTEM_MAGIC,
            "native analytics socket directory is not private ext4 custody",
        )
        socket_state = os.stat(
            path.name,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        named_socket = path.lstat()
        socket_identity = (int(socket_state.st_dev), int(socket_state.st_ino))
        _require(
            stat.S_ISSOCK(socket_state.st_mode)
            and socket_identity
            == (int(named_socket.st_dev), int(named_socket.st_ino))
            and socket_state.st_uid == os.getuid()
            and socket_state.st_gid == os.getgid()
            and socket_state.st_nlink == 1,
            "native analytics socket node custody drifted",
        )
        after = os.fstat(descriptor)
        _require(
            (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_mode),
                int(after.st_uid),
                int(after.st_gid),
            )
            == (
                int(root.st_dev),
                int(root.st_ino),
                int(root.st_mode),
                int(root.st_uid),
                int(root.st_gid),
            ),
            "native analytics socket directory changed during custody observation",
        )
        core = {
            "schema_version": 1,
            "artifact_kind": _NATIVE_SOCKET_CUSTODY_KIND,
            "socket_directory": str(directory),
            "socket_path": str(path),
            "filesystem_magic": f"0x{_LINUX_EXT_FILESYSTEM_MAGIC:08x}",
            "directory_identity": {
                "st_dev": root_identity[0],
                "st_ino": root_identity[1],
            },
            "directory_mode": f"{stat.S_IMODE(root.st_mode):04o}",
            "directory_uid": int(root.st_uid),
            "directory_gid": int(root.st_gid),
            "socket_identity": {
                "st_dev": socket_identity[0],
                "st_ino": socket_identity[1],
            },
            "socket_mode": f"{stat.S_IMODE(socket_state.st_mode):04o}",
            "socket_uid": int(socket_state.st_uid),
            "socket_gid": int(socket_state.st_gid),
            "native_ext4_private_socket_attested": True,
        }
        return {**core, "identity_sha256": canonical_sha256(core)}
    except OSError as error:
        raise SidecarError("cannot attest native analytics socket custody") from error
    finally:
        os.close(descriptor)


def _validate_native_ext4_private_socket_custody(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    custody = dict(
        _exact(
            value,
            {
                "schema_version",
                "artifact_kind",
                "socket_directory",
                "socket_path",
                "filesystem_magic",
                "directory_identity",
                "directory_mode",
                "directory_uid",
                "directory_gid",
                "socket_identity",
                "socket_mode",
                "socket_uid",
                "socket_gid",
                "native_ext4_private_socket_attested",
                "identity_sha256",
            },
            "native ext4 analytics socket custody",
        )
    )
    core = {key: value for key, value in custody.items() if key != "identity_sha256"}
    _require(
        custody.get("schema_version") == 1
        and custody.get("artifact_kind") == _NATIVE_SOCKET_CUSTODY_KIND
        and custody.get("filesystem_magic") == f"0x{_LINUX_EXT_FILESYSTEM_MAGIC:08x}"
        and custody.get("directory_mode") == "0700"
        and custody.get("directory_uid") == os.getuid()
        and custody.get("directory_gid") == os.getgid()
        and custody.get("socket_uid") == os.getuid()
        and custody.get("socket_gid") == os.getgid()
        and custody.get("native_ext4_private_socket_attested") is True
        and type(custody.get("socket_mode")) is str
        and re.fullmatch(r"[0-7]{4}", custody["socket_mode"]) is not None
        and type(custody.get("identity_sha256")) is str
        and custody["identity_sha256"] == canonical_sha256(core),
        "native ext4 analytics socket custody identity drifted",
    )
    for field in ("directory_identity", "socket_identity"):
        identity = _mapping(custody.get(field), f"analytics socket {field}")
        _require(
            set(identity) == {"st_dev", "st_ino"}
            and all(type(identity[key]) is int and identity[key] > 0 for key in identity),
            f"analytics socket {field} drifted",
        )
    return custody


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


def _select_peer_identity(
    *,
    peer_raw: bytes,
    docker_state_pid: object,
    runtime_platform: Mapping[str, Any] | None,
    runtime_custody: Mapping[str, Any] | None,
) -> dict[str, Any]:
    _require(
        type(peer_raw) is bytes and len(peer_raw) == struct.calcsize("3i"),
        "peer credential raw bytes drifted",
    )
    try:
        peer_pid, peer_uid, peer_gid = struct.unpack("3i", peer_raw)
    except struct.error as error:
        raise SidecarError("peer credential raw bytes drifted") from error
    _require(
        peer_uid == os.getuid() and peer_gid == os.getgid(),
        "analytics worker peer UID/GID drifted",
    )
    _require(
        type(docker_state_pid) is int and 0 < docker_state_pid < 2**31,
        "Docker running state PID drifted",
    )
    if peer_pid > 0:
        _require(
            peer_pid == docker_state_pid,
            "analytics worker peer PID differs from container init",
        )
        _require(
            runtime_platform is None and runtime_custody is None,
            "visible peer PID mode received namespace-hidden authority",
        )
        mode = PEER_IDENTITY_MODE_NATIVE_VISIBLE
        platform_sha = None
        custody_sha = None
        pid_visible = True
        pid_equal = True
        pid_attested = True
        socket_pid_binding = True
        backend_attested = False
        wsl_attested = False
        native_custody_attested = False
    else:
        _require(
            peer_pid == 0,
            "namespace-hidden peer mode requires exact PID zero",
        )
        _require(
            runtime_platform is not None and runtime_custody is not None,
            "namespace-hidden peer authority is unavailable",
        )
        platform = _validate_peercred_pid0_platform_observation(runtime_platform)
        custody = _validate_native_ext4_private_socket_custody(runtime_custody)
        mode = PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
        platform_sha = platform["observation_sha256"]
        custody_sha = custody["identity_sha256"]
        pid_visible = False
        pid_equal = False
        pid_attested = False
        socket_pid_binding = False
        backend_attested = True
        wsl_attested = True
        native_custody_attested = True
    core = {
        "schema_version": 2,
        "policy_version": PEER_IDENTITY_POLICY_VERSION,
        "peer_identity_mode": mode,
        "peer_pid": peer_pid,
        "peer_uid": peer_uid,
        "peer_gid": peer_gid,
        "peer_raw_hex": peer_raw.hex(),
        "peer_raw_sha256": hashlib.sha256(peer_raw).hexdigest(),
        "container_state_pid": docker_state_pid,
        "peer_uid_gid_exact": True,
        "container_state_pid_positive": True,
        "pid_positive": peer_pid > 0,
        "pid_matches_container_state_pid": peer_pid == docker_state_pid,
        "peer_pid_visible_in_controller_namespace": pid_visible,
        "peer_pid_state_pid_equality_attested": pid_equal,
        "peer_identity_by_pid_attested": pid_attested,
        "peer_socket_to_container_pid_binding_attested": socket_pid_binding,
        "docker_desktop_containerd_backend_attested": backend_attested,
        "wsl2_platform_attested": wsl_attested,
        "platform_observation_sha256": platform_sha,
        "native_ext4_private_socket_attested": native_custody_attested,
        "native_ipc_custody_sha256": custody_sha,
        "protocol_nonce_capability_handshake_required": True,
        "protocol_nonce_capability_handshake_performed": False,
        "global_eight_worker_handshake_barrier_attested": False,
        "peer_identity_by_protocol_capability_attested": False,
    }
    result = {**core, "identity_sha256": canonical_sha256(core)}
    return _validate_peer_identity_observation(result, completed_handshake=False)


def _validate_peer_identity_observation(
    value: Mapping[str, Any],
    *,
    completed_handshake: bool,
) -> dict[str, Any]:
    peer = dict(_exact(value, _PEER_IDENTITY_FIELDS, "peer identity observation"))
    _require(
        type(completed_handshake) is bool
        and peer.get("schema_version") == 2
        and peer.get("policy_version") == PEER_IDENTITY_POLICY_VERSION
        and peer.get("peer_identity_mode")
        in {
            PEER_IDENTITY_MODE_NATIVE_VISIBLE,
            PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
        },
        "peer identity observation header drifted",
    )
    for field in ("peer_pid", "peer_uid", "peer_gid", "container_state_pid"):
        _require(
            type(peer.get(field)) is int and -(2**31) <= peer[field] < 2**31,
            f"peer identity {field} drifted",
        )
    try:
        raw = bytes.fromhex(str(peer.get("peer_raw_hex")))
    except ValueError as error:
        raise SidecarError("peer identity raw encoding drifted") from error
    _require(
        type(peer.get("peer_raw_hex")) is str
        and peer["peer_raw_hex"] == raw.hex()
        and len(raw) == struct.calcsize("3i")
        and struct.unpack("3i", raw)
        == (peer["peer_pid"], peer["peer_uid"], peer["peer_gid"])
        and peer.get("peer_raw_sha256") == hashlib.sha256(raw).hexdigest()
        and peer.get("peer_uid") == os.getuid()
        and peer.get("peer_gid") == os.getgid()
        and peer.get("peer_uid_gid_exact") is True
        and peer.get("container_state_pid_positive") is True
        and peer.get("pid_positive") is (peer["peer_pid"] > 0)
        and peer.get("pid_matches_container_state_pid")
        is (peer["peer_pid"] == peer["container_state_pid"])
        and 0 < peer["container_state_pid"] < 2**31,
        "peer identity credential facts drifted",
    )
    boolean_fields = {
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
        all(type(peer.get(field)) is bool for field in boolean_fields)
        and peer["protocol_nonce_capability_handshake_required"] is True
        and peer["protocol_nonce_capability_handshake_performed"]
        is completed_handshake
        and peer["global_eight_worker_handshake_barrier_attested"]
        is completed_handshake
        and peer["peer_identity_by_protocol_capability_attested"]
        is completed_handshake,
        "peer identity handshake facts drifted",
    )
    if peer["peer_identity_mode"] == PEER_IDENTITY_MODE_NATIVE_VISIBLE:
        _require(
            peer["peer_pid"] > 0
            and peer["peer_pid"] == peer["container_state_pid"]
            and peer["peer_pid_visible_in_controller_namespace"] is True
            and peer["peer_pid_state_pid_equality_attested"] is True
            and peer["peer_identity_by_pid_attested"] is True
            and peer["peer_socket_to_container_pid_binding_attested"] is True
            and peer["docker_desktop_containerd_backend_attested"] is False
            and peer["wsl2_platform_attested"] is False
            and peer["platform_observation_sha256"] is None
            and peer["native_ext4_private_socket_attested"] is False
            and peer["native_ipc_custody_sha256"] is None,
            "visible peer identity facts drifted",
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
            and type(peer["platform_observation_sha256"]) is str
            and _SHA256_RE.fullmatch(peer["platform_observation_sha256"])
            is not None
            and type(peer["native_ipc_custody_sha256"]) is str
            and _SHA256_RE.fullmatch(peer["native_ipc_custody_sha256"])
            is not None,
            "namespace-hidden peer identity facts drifted",
        )
    core = {key: value for key, value in peer.items() if key != "identity_sha256"}
    _require(
        type(peer.get("identity_sha256")) is str
        and peer["identity_sha256"] == canonical_sha256(core),
        "peer identity observation hash drifted",
    )
    return peer


def _complete_peer_identity_after_handshake(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    peer = _validate_peer_identity_observation(
        value,
        completed_handshake=False,
    )
    core = {
        **{key: item for key, item in peer.items() if key != "identity_sha256"},
        "protocol_nonce_capability_handshake_performed": True,
        "global_eight_worker_handshake_barrier_attested": True,
        "peer_identity_by_protocol_capability_attested": True,
    }
    completed = {**core, "identity_sha256": canonical_sha256(core)}
    return _validate_peer_identity_observation(
        completed,
        completed_handshake=True,
    )


def _attest_worker_peer_identity(
    connection: socket.socket,
    *,
    docker_state_pid: int,
    worker_handle: "WorkerHandle",
    socket_dir: Path | str,
    socket_path: Path | str,
) -> dict[str, Any]:
    raw = _peer_credentials_raw(connection)
    peer_pid, _peer_uid, _peer_gid = struct.unpack("3i", raw)
    platform: Mapping[str, Any] | None = None
    custody: Mapping[str, Any] | None = None
    if peer_pid == 0:
        _require(
            type(worker_handle) is DockerWorkerHandle,
            "namespace-hidden peer requires the exact Docker worker handle",
        )
        platform = worker_handle.peercred_pid0_platform_observation()
        custody = _native_ext4_private_socket_custody(socket_dir, socket_path)
    return _select_peer_identity(
        peer_raw=raw,
        docker_state_pid=docker_state_pid,
        runtime_platform=platform,
        runtime_custody=custody,
    )


def _peer_pid(connection: socket.socket) -> int:
    credentials = _peer_credentials_raw(connection)
    pid, _uid, _gid = struct.unpack("3i", credentials)
    _require(pid > 0, "analytics worker peer PID is not visible")
    return int(pid)


def _atomic_write_json(
    path: Path,
    value: Mapping[str, Any],
    *,
    directory_custody: Any | None = None,
) -> tuple[int, int] | None:
    payload = canonical_json_bytes(dict(value)) + b"\n"
    if directory_custody is not None:
        _require(
            path.parent == directory_custody.path,
            f"{path.name} escaped held directory custody",
        )
        try:
            return directory_custody.write_exclusive(
                path.name, payload, mode=0o400
            )
        except Exception as error:
            raise SidecarError(
                f"dirfd custody write failed for {path.name}: {error}"
            ) from error
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(
        getattr(os, "O_CLOEXEC", 0)
    ) | int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(path, flags, 0o400)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            _require(written > 0, f"failed to write {path.name}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return None


def _atomic_write_bytes(
    path: Path, payload: bytes, *, directory_custody: Any | None = None
) -> tuple[int, int] | None:
    if directory_custody is not None:
        _require(
            path.parent == directory_custody.path,
            f"{path.name} escaped held directory custody",
        )
        try:
            return directory_custody.write_exclusive(
                path.name, payload, mode=0o400
            )
        except Exception as error:
            raise SidecarError(
                f"dirfd custody write failed for {path.name}: {error}"
            ) from error
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | int(getattr(os, "O_CLOEXEC", 0))
        | int(getattr(os, "O_NOFOLLOW", 0)),
        0o400,
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            _require(written > 0, f"failed to write {path.name}")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return None


def _fsync_directory(path: Path, *, directory_custody: Any | None = None) -> None:
    if directory_custody is not None:
        _require(
            path == directory_custody.path,
            "fsync target escaped held directory custody",
        )
        try:
            directory_custody.fsync()
            return
        except Exception as error:
            raise SidecarError(
                f"dirfd custody fsync failed for {path.name}: {error}"
            ) from error
    descriptor = os.open(
        path,
        os.O_RDONLY
        | int(getattr(os, "O_NOFOLLOW", 0))
        | int(getattr(os, "O_DIRECTORY", 0))
        | int(getattr(os, "O_CLOEXEC", 0)),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class EngineeringEvidenceSink:
    """Atomic raw evidence sink explicitly excluded from accepted evidence."""

    def __init__(self, root: Path | str) -> None:
        lexical = _absolute(root)
        if not lexical.exists():
            lexical.mkdir(parents=True, exist_ok=False)
        self.root = _canonical_directory(
            lexical,
            label="analytics sidecar engineering evidence root",
            reject_cwd_or_parent=True,
        )
        self.calls = self.root / "calls"
        if not self.calls.exists():
            self.calls.mkdir()
        self.calls = _canonical_directory(
            self.calls,
            label="analytics sidecar engineering calls root",
            reject_cwd_or_parent=True,
        )
        self._lock = threading.Lock()

    def persist_call(
        self,
        *,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        payload: bytes,
        lifecycle_id: str,
        failure: BaseException | None = None,
    ) -> Mapping[str, Any]:
        request_id = _safe_id(request.get("request_id"), "sidecar request_id")
        if failure is None:
            _require(
                response.get("request_id") == request_id,
                "sidecar response request_id mismatch",
            )
        else:
            _require(not response, "failed sidecar call cannot contain a response")
        target = self.calls / request_id
        _require(
            target.parent == self.calls
            and not target.exists()
            and not target.is_symlink()
            and not _is_reparse(target),
            "sidecar engineering request evidence already exists or is unsafe",
        )
        with self._lock:
            _require(
                not target.exists() and not target.is_symlink(),
                "sidecar engineering request evidence already exists",
            )
            staging: Path | None = Path(
                tempfile.mkdtemp(prefix=f".{request_id}.", dir=self.calls)
            )
            staging_identity = _stat_identity(staging)
            try:
                request_payload = canonical_json_bytes(dict(request)) + b"\n"
                response_payload = canonical_json_bytes(dict(response)) + b"\n"
                files = {
                    "request": {
                        "path": "request.json",
                        "bytes": len(request_payload),
                        "sha256": hashlib.sha256(request_payload).hexdigest(),
                    },
                    "response": {
                        "path": "response.json",
                        "bytes": len(response_payload),
                        "sha256": hashlib.sha256(response_payload).hexdigest(),
                    },
                    "input_frame": {
                        "path": "input.frame.bin",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    },
                }
                core = {
                    "schema_version": 1,
                    "artifact_kind": SIDECAR_CALL_KIND,
                    "claim_status": SIDECAR_CLAIM_STATUS,
                    "outcome": "completed" if failure is None else "failed",
                    "publication_ready": False,
                    "accepted_evidence_written": False,
                    "lifecycle_id": lifecycle_id,
                    "request_id": request_id,
                    "branch": _mapping(request.get("frame"), "sidecar frame").get("branch"),
                    "selected_resource": _mapping(
                        request.get("decision"), "sidecar decision"
                    ).get("selected_resource"),
                    "worker_id": response.get("worker_id"),
                    "worker_implementation_sha256": response.get(
                        "worker_implementation_sha256"
                    ),
                    "failure": (
                        None
                        if failure is None
                        else {
                            "type": type(failure).__name__,
                            "message": str(failure)[:4096],
                        }
                    ),
                    "files": files,
                }
                manifest = {
                    **core,
                    "identity": {
                        "algorithm": "sha256",
                        "sha256": canonical_sha256(core),
                    },
                }
                _atomic_write_bytes(staging / "request.json", request_payload)
                _atomic_write_bytes(staging / "response.json", response_payload)
                _atomic_write_bytes(staging / "input.frame.bin", payload)
                _atomic_write_json(staging / "manifest.json", manifest)
                _fsync_directory(staging)
                os.replace(staging, target)
                staging = None
                _fsync_directory(self.calls)
                return manifest
            finally:
                if staging is not None and staging.exists():
                    _require(
                        staging.parent == self.calls
                        and staging.name.startswith(f".{request_id}.")
                        and _stat_identity(staging) == staging_identity
                        and not _is_reparse(staging),
                        "sidecar evidence staging identity changed",
                    )
                    for entry in staging.iterdir():
                        _require(
                            entry.parent == staging
                            and entry.is_file()
                            and not _is_reparse(entry),
                            "sidecar evidence staging contains an unsafe entry",
                        )
                        entry.unlink()
                    staging.rmdir()

    def persist_lifecycle(self, value: Mapping[str, Any]) -> None:
        path = self.root / "lifecycle.json"
        _require(
            not path.exists() and not path.is_symlink(),
            "sidecar lifecycle evidence already exists",
        )
        _atomic_write_json(path, value)
        _fsync_directory(self.root)


class ProductionLifecycleEvidenceSink:
    """Commit only immutable readiness and aggregate operational lifecycle files."""

    def __init__(self, root: Path | str) -> None:
        lexical = _absolute(root)
        if not lexical.exists():
            lexical.mkdir(parents=True, exist_ok=False)
        self.root = _canonical_directory(
            lexical,
            label="analytics production lifecycle evidence root",
            reject_cwd_or_parent=True,
        )
        self.authority_path = self.root / "service_authority.v1.json"
        self.lifecycle_path = self.root / "service_lifecycle.v1.json"
        self._directory_custody: Any | None = None
        self._authority_identity: tuple[int, int] | None = None
        if os.name == "posix":
            try:
                from publication_guardian_preprocessing_contract_v1 import (
                    DirectoryFdCustodyV1,
                )

                self._directory_custody = DirectoryFdCustodyV1.open_existing(
                    self.root,
                    label="analytics production lifecycle evidence root",
                )
            except Exception as error:
                raise SidecarError(
                    "cannot establish analytics production evidence dirfd custody"
                ) from error

    def persist_authority(self, value: Mapping[str, Any]) -> None:
        _require(
            self._authority_identity is None,
            "analytics production service authority already exists",
        )
        if self._directory_custody is None:
            _require(
                not os.path.lexists(self.authority_path),
                "analytics production service authority already exists",
            )
        identity = _atomic_write_json(
            self.authority_path,
            value,
            directory_custody=self._directory_custody,
        )
        if self._directory_custody is None:
            _fsync_directory(self.root)
        else:
            _require(
                identity is not None,
                "analytics production authority ownership was not established",
            )
        self._authority_identity = identity

    def persist_lifecycle(self, value: Mapping[str, Any]) -> None:
        if self._directory_custody is not None:
            _require(
                self._authority_identity is not None,
                "analytics production lifecycle commit order or custody drifted",
            )
            try:
                self._directory_custody.assert_owned(
                    self.authority_path.name, self._authority_identity
                )
            except Exception as error:
                raise SidecarError(
                    "analytics production authority dirfd custody changed"
                ) from error
        else:
            _require(
                self.authority_path.is_file()
                and not _is_reparse(self.authority_path)
                and not os.path.lexists(self.lifecycle_path),
                "analytics production lifecycle commit order or custody drifted",
            )
        _atomic_write_json(
            self.lifecycle_path,
            value,
            directory_custody=self._directory_custody,
        )
        if self._directory_custody is None:
            _fsync_directory(self.root)

    def close(self) -> None:
        custody = self._directory_custody
        self._directory_custody = None
        if custody is not None:
            custody.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class _RollingProductionCounters:
    """Fixed-size integer aggregates; never per-call evidence or hashing."""

    def __init__(self, *, max_total_requests: int) -> None:
        _require(
            type(max_total_requests) is int
            and PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM
            <= max_total_requests
            <= PRODUCTION_REQUEST_LIMIT,
            "analytics production max_total_requests is invalid",
        )
        self._max_total_requests = max_total_requests
        self._lock = threading.Lock()
        self._connections_accepted = 0
        self._connections_active = 0
        self._connections_clean_eof = 0
        self._connections_failed = 0
        self._connections_shutdown_closed = 0
        self._requests_started = 0
        self._requests_completed = 0
        self._requests_failed = 0
        self._requests_by_worker = {
            f"{branch}:{resource}": 0
            for branch in BRANCHES
            for resource in RESOURCES
        }

    def connection_opened(self) -> None:
        with self._lock:
            self._connections_accepted += 1
            self._connections_active += 1

    def connection_closed(self, *, clean_eof: bool, failed: bool) -> None:
        _require(
            type(clean_eof) is bool
            and type(failed) is bool
            and not (clean_eof and failed),
            "analytics production connection outcome is invalid",
        )
        with self._lock:
            _require(
                self._connections_active > 0,
                "analytics production active connection counter underflow",
            )
            self._connections_active -= 1
            if clean_eof:
                self._connections_clean_eof += 1
            if failed:
                self._connections_failed += 1
            if not clean_eof and not failed:
                self._connections_shutdown_closed += 1

    def request_started(
        self, *, branch: str, resource: str, request_id: str
    ) -> None:
        key = f"{branch}:{resource}"
        _require(
            key in self._requests_by_worker,
            "analytics production request route is invalid",
        )
        _safe_id(request_id, "analytics production request_id")
        with self._lock:
            _require(
                self._requests_started < self._max_total_requests
                and self._requests_by_worker[key] < self._max_total_requests,
                "analytics production request capacity was exhausted",
            )
            self._requests_started += 1
            self._requests_by_worker[key] += 1

    def request_completed(self, *, branch: str, resource: str) -> None:
        _require(
            f"{branch}:{resource}" in self._requests_by_worker,
            "analytics production completed request route is invalid",
        )
        with self._lock:
            self._requests_completed += 1

    def request_failed(self, *, branch: str, resource: str) -> None:
        _require(
            f"{branch}:{resource}" in self._requests_by_worker,
            "analytics production failed request route is invalid",
        )
        with self._lock:
            self._requests_failed += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            _require(
                self._requests_completed + self._requests_failed
                <= self._requests_started,
                "analytics production request counters drifted",
            )
            core = {
                "connections_accepted": self._connections_accepted,
                "connections_active": self._connections_active,
                "connections_clean_eof": self._connections_clean_eof,
                "connections_failed": self._connections_failed,
                "connections_shutdown_closed": self._connections_shutdown_closed,
                "requests_started": self._requests_started,
                "requests_completed": self._requests_completed,
                "requests_failed": self._requests_failed,
                "requests_by_worker": dict(self._requests_by_worker),
                "evidence_role": "operational_non_authorizing_aggregate",
            }
            return {**core, "aggregate_sha256": canonical_sha256(core)}


def _production_capacity_contract(
    *,
    max_connections: int,
    max_requests_per_connection: int,
    max_total_requests: int,
) -> dict[str, Any]:
    _require(
        type(max_connections) is int
        and PRODUCTION_MAX_CONNECTIONS_MINIMUM
        <= max_connections
        <= PRODUCTION_REQUEST_LIMIT,
        "analytics production max_connections is below the frozen contract",
    )
    _require(
        type(max_requests_per_connection) is int
        and PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM
        <= max_requests_per_connection
        <= PRODUCTION_REQUEST_LIMIT,
        "analytics production per-connection request bound is below the frozen contract",
    )
    _require(
        type(max_total_requests) is int
        and PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM
        <= max_total_requests
        <= PRODUCTION_REQUEST_LIMIT,
        "analytics production total request bound is below the frozen contract",
    )
    frozen_per_connection = (
        PRODUCTION_FROZEN_FPS
        * PRODUCTION_FROZEN_STREAMS
        * PRODUCTION_FROZEN_BRANCHES
        * PRODUCTION_CELL_SECONDS_UPPER_BOUND
    )
    frozen_connections = (
        PRODUCTION_CELL_COUNT * PRODUCTION_CONNECTIONS_PER_CELL_UPPER_BOUND
    )
    frozen_total = frozen_per_connection * PRODUCTION_CELL_COUNT
    return {
        "frozen_contract": {
            "frames_per_second": PRODUCTION_FROZEN_FPS,
            "logical_streams": PRODUCTION_FROZEN_STREAMS,
            "analytics_branches": PRODUCTION_FROZEN_BRANCHES,
            "cell_seconds_upper_bound": PRODUCTION_CELL_SECONDS_UPPER_BOUND,
            "cell_count": PRODUCTION_CELL_COUNT,
            "connections_per_cell_upper_bound": (
                PRODUCTION_CONNECTIONS_PER_CELL_UPPER_BOUND
            ),
            "unmargined_requests_per_connection": frozen_per_connection,
            "unmargined_connections": frozen_connections,
            "unmargined_total_requests": frozen_total,
        },
        "controlled_margin": {
            "numerator": PRODUCTION_CAPACITY_MARGIN_NUMERATOR,
            "denominator": PRODUCTION_CAPACITY_MARGIN_DENOMINATOR,
        },
        "max_connections": max_connections,
        "max_requests_per_connection": max_requests_per_connection,
        "max_total_requests": max_total_requests,
        "worker_request_upper_bound": max_total_requests,
        "connection_limit_semantics": "upper_bound_not_exact_drain",
        "connection_eof_semantics": "clean_eof_below_upper_bound_allowed",
        "request_evidence_semantics": (
            "constant_memory_operational_counters_non_authorizing"
        ),
    }


def _process_starttime_ticks(pid: int) -> int:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and type(pid) is int
        and 0 < pid < 2**31,
        "analytics production owner process identity requires Linux",
    )
    path = Path("/proc") / str(pid) / "stat"
    flags = os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0)) | int(
        getattr(os, "O_CLOEXEC", 0)
    )
    _require(
        getattr(os, "O_NOFOLLOW", 0) != 0,
        "analytics production owner process no-follow custody is unavailable",
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        raw = os.read(descriptor, 4097)
        after = os.fstat(descriptor)
        _require(
            0 < len(raw) <= 4096
            and before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
            and before.st_uid == after.st_uid == os.getuid()
            and before.st_gid == after.st_gid == os.getgid(),
            "analytics production owner /proc custody drifted",
        )
    except OSError as error:
        raise SidecarError(
            f"cannot observe analytics production owner process: {error}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    close_paren = raw.rfind(b")")
    _require(
        raw.startswith(f"{pid} (".encode("ascii"))
        and close_paren > 0
        and close_paren + 2 < len(raw),
        "analytics production owner /proc stat framing drifted",
    )
    fields = raw[close_paren + 2 :].split()
    _require(
        len(fields) >= 20 and fields[19].isdigit(),
        "analytics production owner starttime is unavailable",
    )
    starttime = int(fields[19])
    _require(starttime > 0, "analytics production owner starttime is invalid")
    return starttime


def _production_owner_process_identity() -> dict[str, int]:
    pid = os.getpid()
    return {
        "pid": pid,
        "proc_stat_starttime_ticks": _process_starttime_ticks(pid),
        "uid": os.getuid(),
        "gid": os.getgid(),
    }


def _guardian_stop_command_v1(
    *,
    lifecycle_id: str,
    service_authority_sha256: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "message_type": "production_guardian_stop",
        "lifecycle_id": lifecycle_id,
        "service_authority_sha256": service_authority_sha256,
        "nonce": nonce,
    }


def _validate_guardian_stop_attestation_v1(
    value: Mapping[str, Any],
    *,
    expected_authority: Mapping[str, Any],
) -> dict[str, Any]:
    authority = validate_publication_sidecar_service_authority_v1(
        expected_authority
    )
    attestation = dict(
        _exact(
            value,
            {
                "schema_version",
                "artifact_kind",
                "lifecycle_id",
                "service_authority_sha256",
                "nonce",
                "canonical_command_sha256",
                "peer_process",
                "accepted_monotonic_ns",
                "identity",
            },
            "analytics guardian stop attestation",
        )
    )
    nonce = str(attestation.get("nonce") or "")
    _require(
        attestation.get("schema_version") == 1
        and attestation.get("artifact_kind")
        == PRODUCTION_GUARDIAN_STOP_ATTESTATION_KIND
        and attestation.get("lifecycle_id") == authority["lifecycle_id"]
        and attestation.get("service_authority_sha256")
        == authority["service_authority_sha256"]
        and _SHA256_RE.fullmatch(nonce) is not None,
        "analytics guardian stop attestation binding drifted",
    )
    peer = dict(
        _exact(
            attestation.get("peer_process"),
            {"pid", "uid", "gid", "proc_stat_starttime_ticks"},
            "analytics guardian stop peer process",
        )
    )
    owner = authority["owner_process"]
    _require(
        type(peer.get("pid")) is int
        and 0 < peer["pid"] < 2**31
        and type(peer.get("uid")) is int
        and peer["uid"] == owner["uid"]
        and type(peer.get("gid")) is int
        and peer["gid"] == owner["gid"]
        and type(peer.get("proc_stat_starttime_ticks")) is int
        and peer["proc_stat_starttime_ticks"] > 0,
        "analytics guardian stop peer identity drifted",
    )
    command = _guardian_stop_command_v1(
        lifecycle_id=authority["lifecycle_id"],
        service_authority_sha256=authority["service_authority_sha256"],
        nonce=nonce,
    )
    _require(
        attestation.get("canonical_command_sha256")
        == canonical_sha256(command),
        "analytics guardian stop canonical command identity drifted",
    )
    accepted = attestation.get("accepted_monotonic_ns")
    _require(
        type(accepted) is int
        and accepted >= authority["started_monotonic_ns"],
        "analytics guardian stop acceptance time drifted",
    )
    identity = _exact(
        attestation.get("identity"),
        {"algorithm", "sha256"},
        "analytics guardian stop attestation identity",
    )
    core = {
        key: item for key, item in attestation.items() if key != "identity"
    }
    _require(
        identity.get("algorithm") == "sha256"
        and identity.get("sha256") == canonical_sha256(core),
        "analytics guardian stop attestation identity drifted",
    )
    attestation["peer_process"] = peer
    return attestation


def _build_guardian_stop_attestation_v1(
    command_value: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    peer_pid: int,
    peer_uid: int,
    peer_gid: int,
) -> dict[str, Any]:
    checked_authority = validate_publication_sidecar_service_authority_v1(
        authority
    )
    command = dict(
        _exact(
            command_value,
            {
                "schema_version",
                "message_type",
                "lifecycle_id",
                "service_authority_sha256",
                "nonce",
                "canonical_command_sha256",
            },
            "analytics production guardian stop command",
        )
    )
    expected_command = _guardian_stop_command_v1(
        lifecycle_id=checked_authority["lifecycle_id"],
        service_authority_sha256=checked_authority[
            "service_authority_sha256"
        ],
        nonce=str(command.get("nonce") or ""),
    )
    _require(
        {
            key: item
            for key, item in command.items()
            if key != "canonical_command_sha256"
        }
        == expected_command
        and command.get("canonical_command_sha256")
        == canonical_sha256(expected_command)
        and peer_uid == checked_authority["owner_process"]["uid"]
        and peer_gid == checked_authority["owner_process"]["gid"],
        "analytics production guardian stop authentication drifted",
    )
    core: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": PRODUCTION_GUARDIAN_STOP_ATTESTATION_KIND,
        "lifecycle_id": checked_authority["lifecycle_id"],
        "service_authority_sha256": checked_authority[
            "service_authority_sha256"
        ],
        "nonce": expected_command["nonce"],
        "canonical_command_sha256": command["canonical_command_sha256"],
        "peer_process": {
            "pid": peer_pid,
            "uid": peer_uid,
            "gid": peer_gid,
            "proc_stat_starttime_ticks": _process_starttime_ticks(peer_pid),
        },
        "accepted_monotonic_ns": time.monotonic_ns(),
    }
    attestation = {
        **core,
        "identity": {
            "algorithm": "sha256",
            "sha256": canonical_sha256(core),
        },
    }
    return _validate_guardian_stop_attestation_v1(
        attestation,
        expected_authority=checked_authority,
    )


def _production_socket_pin(path: Path) -> dict[str, Any]:
    _require(
        path.is_absolute()
        and os.path.lexists(path)
        and not _is_reparse(path),
        "analytics production socket pin path is missing or unsafe",
    )
    metadata = path.lstat()
    _require(
        stat.S_ISSOCK(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_gid == os.getgid()
        and metadata.st_nlink == 1,
        "analytics production socket pin custody drifted",
    )
    return {
        "path": str(path),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "owner_uid": metadata.st_uid,
        "owner_gid": metadata.st_gid,
    }


def _validate_production_socket_pin(
    value: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    pin = dict(
        _exact(
            value,
            {"path", "device", "inode", "owner_uid", "owner_gid"},
            label,
        )
    )
    path = Path(str(pin.get("path") or ""))
    _require(
        path.is_absolute()
        and str(path) == str(_absolute(path))
        and all(
            type(pin.get(field)) is int and pin[field] >= 0
            for field in ("device", "inode", "owner_uid", "owner_gid")
        )
        and pin["inode"] > 0,
        f"{label} fields are invalid",
    )
    return pin


def _assert_live_production_socket_pin(value: Mapping[str, Any]) -> None:
    pin = _validate_production_socket_pin(value, label="production socket pin")
    path = Path(pin["path"])
    _require(
        os.path.lexists(path) and not _is_reparse(path),
        "analytics production socket disappeared or became unsafe",
    )
    metadata = path.lstat()
    _require(
        stat.S_ISSOCK(metadata.st_mode)
        and metadata.st_dev == pin["device"]
        and metadata.st_ino == pin["inode"]
        and metadata.st_uid == pin["owner_uid"] == os.getuid()
        and metadata.st_gid == pin["owner_gid"] == os.getgid()
        and metadata.st_nlink == 1,
        "analytics production socket identity drifted",
    )


def _production_service_identity_material(
    authority: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "lifecycle_id": authority["lifecycle_id"],
        "owner_process": authority["owner_process"],
        "front_socket": authority["front_socket"],
        "control_socket": authority["control_socket"],
        "protocol_identity_sha256": authority["protocol_identity_sha256"],
        "execution_config_identity_sha256": authority[
            "execution_config_identity_sha256"
        ],
        "binding_set_identity_sha256": authority[
            "binding_set_identity_sha256"
        ],
        "preprocessing_contract_authority": authority[
            "preprocessing_contract_authority"
        ],
        "worker_image_ids": authority["worker_image_ids"],
        "capacity": authority["capacity"],
    }


def validate_publication_sidecar_service_authority_v1(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    authority = dict(
        _exact(
            value,
            {
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
            },
            "analytics production service authority",
        )
    )
    _require(
        authority.get("schema_version") == 1
        and authority.get("artifact_kind") == PRODUCTION_SERVICE_AUTHORITY_KIND
        and authority.get("service_mode") == PRODUCTION_SERVICE_MODE
        and authority.get("status") == "live_operational_nonpublication"
        and authority.get("publication_ready") is False
        and authority.get("accepted_evidence_written") is False,
        "analytics production service authority header drifted",
    )
    lifecycle_id = _safe_id(
        authority.get("lifecycle_id"), "analytics production lifecycle_id"
    )
    _require(
        len(lifecycle_id) == 32,
        "analytics production lifecycle_id width drifted",
    )
    owner = dict(
        _exact(
            authority.get("owner_process"),
            {"pid", "proc_stat_starttime_ticks", "uid", "gid"},
            "analytics production owner process",
        )
    )
    _require(
        type(owner.get("pid")) is int
        and 0 < owner["pid"] < 2**31
        and type(owner.get("proc_stat_starttime_ticks")) is int
        and owner["proc_stat_starttime_ticks"] > 0
        and type(owner.get("uid")) is int
        and owner["uid"] >= 0
        and type(owner.get("gid")) is int
        and owner["gid"] >= 0,
        "analytics production owner process fields drifted",
    )
    authority["front_socket"] = _validate_production_socket_pin(
        _mapping(authority.get("front_socket"), "production front socket pin"),
        label="production front socket pin",
    )
    authority["control_socket"] = _validate_production_socket_pin(
        _mapping(authority.get("control_socket"), "production control socket pin"),
        label="production control socket pin",
    )
    _require(
        authority["front_socket"]["path"]
        != authority["control_socket"]["path"],
        "analytics production front and control sockets alias",
    )
    _sha(authority.get("protocol_identity_sha256"), "production protocol identity")
    _require(
        authority["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256,
        "analytics production protocol identity drifted",
    )
    for field in (
        "execution_config_identity_sha256",
        "binding_set_identity_sha256",
    ):
        _sha(authority.get(field), f"production {field}")
    authority["preprocessing_contract_authority"] = (
        _validate_preprocessing_authority_v1(
            _mapping(
                authority.get("preprocessing_contract_authority"),
                "production preprocessing contract authority",
            )
        )
    )
    worker_images = dict(
        _exact(
            authority.get("worker_image_ids"),
            set(RESOURCES),
            "analytics production worker image IDs",
        )
    )
    _require(
        all(valid_image_id(worker_images[resource]) for resource in RESOURCES),
        "analytics production worker image IDs are invalid",
    )
    capacity = dict(
        _exact(
            authority.get("capacity"),
            {
                "frozen_contract",
                "controlled_margin",
                "max_connections",
                "max_requests_per_connection",
                "max_total_requests",
                "worker_request_upper_bound",
                "connection_limit_semantics",
                "connection_eof_semantics",
                "request_evidence_semantics",
            },
            "analytics production capacity",
        )
    )
    expected_capacity = _production_capacity_contract(
        max_connections=capacity.get("max_connections"),
        max_requests_per_connection=capacity.get(
            "max_requests_per_connection"
        ),
        max_total_requests=capacity.get("max_total_requests"),
    )
    _require(
        capacity == expected_capacity,
        "analytics production capacity derivation drifted",
    )
    peers = authority.get("peer_identities")
    _require(
        authority.get("worker_count") == len(EXPECTED_KEYS)
        and authority.get("attested_worker_count") == len(EXPECTED_KEYS)
        and type(peers) is list
        and len(peers) == len(EXPECTED_KEYS),
        "analytics production peer identity coverage is not exact 8",
    )
    observed_keys: set[tuple[str, str]] = set()
    for row_value in peers:
        row = _exact(
            row_value,
            {
                "branch",
                "resource",
                "worker_image_id",
                "peer_identity",
                "peer_identity_sha256",
            },
            "analytics production peer identity row",
        )
        key = (row.get("branch"), row.get("resource"))
        _require(
            key in EXPECTED_KEYS
            and key not in observed_keys
            and row.get("worker_image_id") == worker_images[key[1]],
            "analytics production peer identity coordinate drifted",
        )
        peer = _validate_peer_identity_observation(
            _mapping(row.get("peer_identity"), "production peer identity"),
            completed_handshake=True,
        )
        _require(
            row.get("peer_identity_sha256") == peer["identity_sha256"],
            "analytics production peer identity hash drifted",
        )
        observed_keys.add(key)
    _require(
        observed_keys == EXPECTED_KEYS,
        "analytics production peer identity coordinate coverage drifted",
    )
    _require(
        type(authority.get("started_monotonic_ns")) is int
        and authority["started_monotonic_ns"] > 0,
        "analytics production start time is invalid",
    )
    for field in ("readiness_artifact_path", "lifecycle_artifact_path"):
        path = Path(str(authority.get(field) or ""))
        _require(
            path.is_absolute() and str(path) == str(_absolute(path)),
            f"analytics production {field} is invalid",
        )
    _require(
        authority["readiness_artifact_path"]
        != authority["lifecycle_artifact_path"],
        "analytics production evidence artifact paths alias",
    )
    expected_service_identity = canonical_sha256(
        _production_service_identity_material(authority)
    )
    _require(
        authority.get("service_identity_sha256") == expected_service_identity,
        "analytics production service identity drifted",
    )
    claimed = authority.pop("service_authority_sha256")
    _require(
        type(claimed) is str
        and _SHA256_RE.fullmatch(claimed) is not None
        and claimed == canonical_sha256(authority),
        "analytics production service authority identity drifted",
    )
    return {**authority, "service_authority_sha256": claimed}


def assert_publication_sidecar_service_authority_identity_v1(
    value: Mapping[str, Any],
    *,
    expected_front_socket: Path | str,
    expected_execution_config_identity_sha256: str,
    expected_binding_set_identity_sha256: str,
    expected_worker_image_ids: Mapping[str, str],
    expected_preprocessing_contract_authority: Mapping[str, Any],
    expected_service_identity_sha256: str,
    expected_policy_contract_sha256: str,
) -> dict[str, Any]:
    authority = validate_publication_sidecar_service_authority_v1(value)
    expected_front = _absolute(expected_front_socket)
    expected_images = dict(
        _exact(
            expected_worker_image_ids,
            set(RESOURCES),
            "expected analytics production worker image IDs",
        )
    )
    expected_preprocessing = _validate_preprocessing_authority_v1(
        expected_preprocessing_contract_authority
    )
    expected_service_identity = _sha(
        expected_service_identity_sha256,
        "expected analytics production service identity",
    )
    expected_policy_identity = _sha(
        expected_policy_contract_sha256,
        "expected analytics production policy contract identity",
    )
    _require(
        authority["front_socket"]["path"] == str(expected_front)
        and authority["execution_config_identity_sha256"]
        == _sha(
            expected_execution_config_identity_sha256,
            "expected analytics production execution config identity",
        )
        and authority["binding_set_identity_sha256"]
        == _sha(
            expected_binding_set_identity_sha256,
            "expected analytics production binding set identity",
        )
        and authority["worker_image_ids"] == expected_images
        and authority["preprocessing_contract_authority"]
        == expected_preprocessing
        and authority["service_identity_sha256"]
        == expected_service_identity
        and authority["preprocessing_contract_authority"][
            "policy_contract_sha256"
        ]
        == expected_policy_identity
        == expected_preprocessing["policy_contract_sha256"],
        "analytics production service authority differs from expected inputs",
    )
    return authority


def assert_publication_sidecar_service_authority_v1(
    value: Mapping[str, Any],
    *,
    expected_front_socket: Path | str,
    expected_execution_config_identity_sha256: str,
    expected_binding_set_identity_sha256: str,
    expected_worker_image_ids: Mapping[str, str],
    expected_preprocessing_contract_authority: Mapping[str, Any],
    expected_service_identity_sha256: str,
    expected_policy_contract_sha256: str,
) -> dict[str, Any]:
    authority = assert_publication_sidecar_service_authority_identity_v1(
        value,
        expected_front_socket=expected_front_socket,
        expected_execution_config_identity_sha256=(
            expected_execution_config_identity_sha256
        ),
        expected_binding_set_identity_sha256=(
            expected_binding_set_identity_sha256
        ),
        expected_worker_image_ids=expected_worker_image_ids,
        expected_preprocessing_contract_authority=(
            expected_preprocessing_contract_authority
        ),
        expected_service_identity_sha256=expected_service_identity_sha256,
        expected_policy_contract_sha256=expected_policy_contract_sha256,
    )
    _assert_publication_sidecar_authority_live_custody(authority)
    observed = query_publication_sidecar_guardian_v1(authority)
    _require(
        observed == authority,
        "analytics production guardian returned a different authority",
    )
    return authority


def _assert_publication_sidecar_authority_live_custody(
    authority: Mapping[str, Any],
) -> None:
    owner = authority["owner_process"]
    _require(
        owner["uid"] == os.getuid()
        and owner["gid"] == os.getgid()
        and _process_starttime_ticks(owner["pid"])
        == owner["proc_stat_starttime_ticks"],
        "analytics production owner process identity drifted",
    )
    _assert_live_production_socket_pin(authority["front_socket"])
    _assert_live_production_socket_pin(authority["control_socket"])


def _publication_guardian_control_request(
    authority_value: Mapping[str, Any],
    *,
    message_type: str,
    timeout_s: float,
) -> dict[str, Any]:
    authority = validate_publication_sidecar_service_authority_v1(
        authority_value
    )
    _require(
        message_type
        in {"production_guardian_status", "production_guardian_stop"}
        and type(timeout_s) in {int, float}
        and 0 < float(timeout_s) <= 60,
        "analytics production guardian control request is invalid",
    )
    _assert_publication_sidecar_authority_live_custody(authority)
    nonce = secrets.token_hex(32)
    request = {
        "schema_version": 1,
        "message_type": message_type,
        "lifecycle_id": authority["lifecycle_id"],
        "service_authority_sha256": authority[
            "service_authority_sha256"
        ],
        "nonce": nonce,
    }
    if message_type == "production_guardian_stop":
        request["canonical_command_sha256"] = canonical_sha256(request)
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    endpoint.settimeout(float(timeout_s))
    try:
        endpoint.connect(authority["control_socket"]["path"])
        send_packet(endpoint, request)
        response, descriptors = receive_packet(endpoint, expected_fds=0)
        close_fds(descriptors)
    except (OSError, ProtocolError) as error:
        raise SidecarError(
            f"analytics production guardian control request failed: {error}"
        ) from error
    finally:
        endpoint.close()
    _require(
        response.get("nonce") == nonce,
        "analytics production guardian control response nonce drifted",
    )
    return response


def query_publication_sidecar_guardian_v1(
    authority: Mapping[str, Any], *, timeout_s: float = 5.0
) -> dict[str, Any]:
    response = _publication_guardian_control_request(
        authority,
        message_type="production_guardian_status",
        timeout_s=timeout_s,
    )
    checked = _exact(
        response,
        {"schema_version", "message_type", "nonce", "authority"},
        "analytics production guardian status response",
    )
    _require(
        checked.get("schema_version") == 1
        and checked.get("message_type")
        == "production_guardian_status_response",
        "analytics production guardian status response drifted",
    )
    observed = validate_publication_sidecar_service_authority_v1(
        _mapping(checked.get("authority"), "guardian status authority")
    )
    expected = validate_publication_sidecar_service_authority_v1(authority)
    _require(
        observed == expected,
        "analytics production guardian status authority drifted",
    )
    return observed


def request_publication_sidecar_guardian_stop_v1(
    authority: Mapping[str, Any], *, timeout_s: float = 5.0
) -> dict[str, Any]:
    response = _publication_guardian_control_request(
        authority,
        message_type="production_guardian_stop",
        timeout_s=timeout_s,
    )
    checked = dict(
        _exact(
            response,
            {
                "schema_version",
                "message_type",
                "lifecycle_id",
                "service_authority_sha256",
                "nonce",
                "canonical_command_sha256",
            },
            "analytics production guardian stop response",
        )
    )
    validated = validate_publication_sidecar_service_authority_v1(authority)
    _require(
        checked.get("schema_version") == 1
        and checked.get("message_type")
        == "production_guardian_stop_accepted"
        and checked.get("lifecycle_id") == validated["lifecycle_id"]
        and checked.get("service_authority_sha256")
        == validated["service_authority_sha256"]
        and checked.get("canonical_command_sha256")
        == canonical_sha256(
            _guardian_stop_command_v1(
                lifecycle_id=validated["lifecycle_id"],
                service_authority_sha256=validated[
                    "service_authority_sha256"
                ],
                nonce=str(checked.get("nonce") or ""),
            )
        ),
        "analytics production guardian stop response binding drifted",
    )
    return checked


def validate_publication_sidecar_service_lifecycle_v1(
    value: Mapping[str, Any],
    *,
    expected_authority: Mapping[str, Any],
) -> dict[str, Any]:
    authority = validate_publication_sidecar_service_authority_v1(
        expected_authority
    )
    lifecycle = dict(
        _exact(
            value,
            {
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
            },
            "analytics production service lifecycle",
        )
    )
    _require(
        lifecycle.get("schema_version") == 1
        and lifecycle.get("artifact_kind") == PRODUCTION_SERVICE_LIFECYCLE_KIND
        and lifecycle.get("service_mode") == PRODUCTION_SERVICE_MODE
        and lifecycle.get("status")
        in {"clean_stop_nonpublication", "failed_stop_nonpublication"}
        and lifecycle.get("publication_ready") is False
        and lifecycle.get("accepted_evidence_written") is False
        and lifecycle.get("evidence_role")
        == "operational_non_authorizing_lifecycle"
        and lifecycle.get("lifecycle_id") == authority["lifecycle_id"]
        and lifecycle.get("service_identity_sha256")
        == authority["service_identity_sha256"]
        and lifecycle.get("service_authority_sha256")
        == authority["service_authority_sha256"]
        and lifecycle.get("front_socket") == authority["front_socket"]
        and lifecycle.get("control_socket") == authority["control_socket"]
        and lifecycle.get("capacity") == authority["capacity"],
        "analytics production service lifecycle binding drifted",
    )
    readiness = _exact(
        lifecycle.get("readiness_artifact"),
        {"path", "size_bytes", "sha256"},
        "analytics production readiness descriptor",
    )
    readiness_path = Path(str(readiness.get("path") or ""))
    _require(
        readiness_path == Path(authority["readiness_artifact_path"])
        and type(readiness.get("size_bytes")) is int
        and readiness["size_bytes"] > 0,
        "analytics production readiness descriptor fields drifted",
    )
    readiness_payload = canonical_json_bytes(authority) + b"\n"
    _require(
        readiness.get("size_bytes") == len(readiness_payload)
        and readiness.get("sha256")
        == hashlib.sha256(readiness_payload).hexdigest(),
        "analytics production readiness descriptor identity drifted",
    )
    started = lifecycle.get("started_monotonic_ns")
    finished = lifecycle.get("finished_monotonic_ns")
    _require(
        started == authority["started_monotonic_ns"]
        and type(finished) is int
        and finished >= started
        and lifecycle.get("duration_ns") == finished - started,
        "analytics production lifecycle timing drifted",
    )
    attestation_value = lifecycle.get("guardian_stop_attestation")
    guardian_stop_attestation: dict[str, Any] | None = None
    if attestation_value is not None:
        guardian_stop_attestation = _validate_guardian_stop_attestation_v1(
            _mapping(
                attestation_value,
                "analytics guardian stop lifecycle attestation",
            ),
            expected_authority=authority,
        )
        _require(
            guardian_stop_attestation["accepted_monotonic_ns"] <= finished,
            "analytics guardian stop acceptance exceeds lifecycle finish",
        )
    lifecycle["guardian_stop_attestation"] = guardian_stop_attestation
    counters = dict(
        _exact(
            lifecycle.get("counters"),
            {
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
            },
            "analytics production lifecycle counters",
        )
    )
    for field in (
        "connections_accepted",
        "connections_active",
        "connections_clean_eof",
        "connections_failed",
        "connections_shutdown_closed",
        "requests_started",
        "requests_completed",
        "requests_failed",
    ):
        _require(
            type(counters.get(field)) is int and counters[field] >= 0,
            f"analytics production lifecycle counter {field} drifted",
        )
    requests_by_worker = counters.get("requests_by_worker")
    _require(
        type(requests_by_worker) is dict
        and set(requests_by_worker)
        == {
            f"{branch}:{resource}"
            for branch in BRANCHES
            for resource in RESOURCES
        }
        and all(type(count) is int and count >= 0 for count in requests_by_worker.values())
        and counters["connections_active"] == 0
        and counters["connections_clean_eof"]
        + counters["connections_failed"]
        + counters["connections_shutdown_closed"]
        == counters["connections_accepted"]
        and counters["requests_completed"] + counters["requests_failed"]
        == counters["requests_started"]
        and sum(requests_by_worker.values()) == counters["requests_started"]
        and counters.get("evidence_role")
        == "operational_non_authorizing_aggregate",
        "analytics production lifecycle aggregate counters drifted",
    )
    claimed_aggregate = counters.pop("aggregate_sha256")
    _require(
        claimed_aggregate == canonical_sha256(counters),
        "analytics production lifecycle aggregate identity drifted",
    )
    counters["aggregate_sha256"] = claimed_aggregate
    cleanup_errors = lifecycle.get("cleanup_errors")
    _require(
        type(cleanup_errors) is list
        and all(type(item) is str and item for item in cleanup_errors),
        "analytics production cleanup errors drifted",
    )
    authority_front_path = Path(authority["front_socket"]["path"])
    expected_retired_active_name_sequence = (
        *(
            f"worker-{branch}-{resource}.sock"
            for branch in BRANCHES
            for resource in RESOURCES
        ),
        authority_front_path.name,
        Path(authority["control_socket"]["path"]).name,
    )
    _require(
        len(expected_retired_active_name_sequence)
        == PRODUCTION_RETIRED_SOCKET_NODE_COUNT
        and len(set(expected_retired_active_name_sequence))
        == PRODUCTION_RETIRED_SOCKET_NODE_COUNT,
        "analytics retired socket active-name cardinality drifted",
    )
    expected_retired_active_names = (
        set(expected_retired_active_name_sequence)
        if lifecycle["status"] == "clean_stop_nonpublication"
        else None
    )
    expected_retirement_directory = authority_front_path.parent.parent / (
        f".vast-gst-analytics-retired-{authority['lifecycle_id']}"
    )
    lifecycle["retired_socket_nodes"] = _validate_retired_socket_records_v1(
        lifecycle.get("retired_socket_nodes"),
        expected_lifecycle_id=authority["lifecycle_id"],
        expected_active_names=expected_retired_active_names,
        expected_record_count=(
            PRODUCTION_RETIRED_SOCKET_NODE_COUNT
            if lifecycle["status"] == "clean_stop_nonpublication"
            else None
        ),
        expected_retirement_directory=expected_retirement_directory,
        verify_physical=True,
    )
    if lifecycle["status"] == "clean_stop_nonpublication":
        _require(
            lifecycle.get("failure") is None
            and cleanup_errors == []
            and counters["connections_failed"] == 0
            and counters["requests_failed"] == 0
            and guardian_stop_attestation is not None,
            "clean analytics production lifecycle contains failure claims",
        )
    else:
        failure = lifecycle.get("failure")
        _require(
            (type(failure) is dict and set(failure) == {"type", "message"})
            or bool(cleanup_errors),
            "failed analytics production lifecycle lacks a failure",
        )
        if guardian_stop_attestation is None:
            _require(
                "guardian_stop_attestation_missing" in cleanup_errors,
                "unauthenticated analytics production stop lacks its failure marker",
            )
    identity = _exact(
        lifecycle.get("identity"),
        {"algorithm", "sha256"},
        "analytics production lifecycle identity",
    )
    core = {key: item for key, item in lifecycle.items() if key != "identity"}
    _require(
        identity.get("algorithm") == "sha256"
        and identity.get("sha256") == canonical_sha256(core),
        "analytics production lifecycle identity drifted",
    )
    return lifecycle


def _assert_guardian_stop_ack_matches_lifecycle_v1(
    acknowledgement_value: Mapping[str, Any],
    lifecycle_value: Mapping[str, Any],
    *,
    expected_authority: Mapping[str, Any],
) -> dict[str, Any]:
    acknowledgement = dict(
        _exact(
            acknowledgement_value,
            {
                "schema_version",
                "message_type",
                "lifecycle_id",
                "service_authority_sha256",
                "nonce",
                "canonical_command_sha256",
            },
            "analytics guardian stop acknowledgement",
        )
    )
    lifecycle = validate_publication_sidecar_service_lifecycle_v1(
        lifecycle_value,
        expected_authority=expected_authority,
    )
    attestation = lifecycle.get("guardian_stop_attestation")
    _require(
        acknowledgement.get("schema_version") == 1
        and acknowledgement.get("message_type")
        == "production_guardian_stop_accepted"
        and type(attestation) is dict
        and acknowledgement.get("lifecycle_id")
        == attestation.get("lifecycle_id")
        and acknowledgement.get("service_authority_sha256")
        == attestation.get("service_authority_sha256")
        and acknowledgement.get("nonce") == attestation.get("nonce")
        and acknowledgement.get("canonical_command_sha256")
        == attestation.get("canonical_command_sha256"),
        "analytics guardian stop acknowledgement differs from lifecycle attestation",
    )
    return lifecycle


def _load_canonical_json_mapping(path: Path | str, *, label: str) -> dict[str, Any]:
    target = _absolute(path)
    try:
        payload = read_file_bytes_fd_custody_v1(target, label=label)
    except GuardianPreprocessingContractV1Error as error:
        raise SidecarError(f"{label} descriptor custody failed: {error}") from error

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            _require(key not in result, f"{label} has duplicate JSON keys")
            result[key] = item
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SidecarError(f"cannot parse {label}: {error}") from error
    _require(
        type(value) is dict
        and payload == canonical_json_bytes(value) + b"\n",
        f"{label} is not canonical JSON",
    )
    return value


def wait_publication_sidecar_guardian_stop_v1(
    authority_value: Mapping[str, Any], *, timeout_s: float = 60.0
) -> dict[str, Any]:
    authority = validate_publication_sidecar_service_authority_v1(
        authority_value
    )
    _require(
        type(timeout_s) in {int, float} and 0 < float(timeout_s) <= 300,
        "analytics production guardian stop wait is invalid",
    )
    lifecycle_path = Path(authority["lifecycle_artifact_path"])
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        if lifecycle_path.is_file() and not _is_reparse(lifecycle_path):
            lifecycle = validate_publication_sidecar_service_lifecycle_v1(
                _load_canonical_json_mapping(
                    lifecycle_path,
                    label="analytics production service lifecycle",
                ),
                expected_authority=authority,
            )
            _require(
                not os.path.lexists(authority["front_socket"]["path"])
                and not os.path.lexists(authority["control_socket"]["path"]),
                "analytics production sockets survived sealed shutdown",
            )
            return lifecycle
        time.sleep(0.02)
    raise SidecarError("timed out waiting for analytics production guardian stop")


class DockerWorkerHandle:
    """Foreground `docker run` handle with host PID attestation via inspect."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        container_name: str,
        command_runner: Callable[..., subprocess.CompletedProcess[str]],
        platform_observer: Callable[[], Mapping[str, Any]],
        stdout_capture: Any,
        stderr_capture: Any,
    ) -> None:
        self._process = process
        self.container_name = container_name
        self.pid = int(process.pid)
        self._command_runner = command_runner
        self._platform_observer = platform_observer
        self._stdout_capture = stdout_capture
        self._stderr_capture = stderr_capture

    @staticmethod
    def _capture_tail(capture: Any, *, maximum_bytes: int = 2048) -> str:
        try:
            capture.flush()
            end = int(capture.seek(0, os.SEEK_END))
            capture.seek(max(0, end - maximum_bytes), os.SEEK_SET)
            payload = capture.read(maximum_bytes)
        except (OSError, ValueError, AttributeError):
            return "capture_unavailable"
        if not isinstance(payload, bytes):
            payload = bytes(payload or b"")
        return payload.decode("utf-8", errors="replace")

    def failure_diagnostic(self) -> str:
        return (
            "stdout_tail="
            + json.dumps(self._capture_tail(self._stdout_capture), ensure_ascii=True)
            + ";stderr_tail="
            + json.dumps(self._capture_tail(self._stderr_capture), ensure_ascii=True)
        )

    def close_diagnostics(self) -> None:
        for field in ("_stdout_capture", "_stderr_capture"):
            capture = getattr(self, field, None)
            setattr(self, field, None)
            if capture is not None:
                try:
                    capture.close()
                except OSError:
                    pass

    def __del__(self) -> None:
        self.close_diagnostics()

    def expected_peer_pid(self, timeout_s: float) -> int:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.poll() is not None:
                raise SidecarError(
                    f"analytics worker container {self.container_name} exited during startup: "
                    f"{self.failure_diagnostic()}"
                )
            try:
                completed = self._command_runner(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Pid}}",
                        self.container_name,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=min(5.0, max(0.1, deadline - time.monotonic())),
                )
                raw = completed.stdout.strip()
                if raw.isdigit() and int(raw) > 0:
                    return int(raw)
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(0.02)
        raise SidecarError(
            f"timed out inspecting analytics worker PID: {self.container_name}"
        )

    def peercred_pid0_platform_observation(self) -> Mapping[str, Any]:
        return _validate_peercred_pid0_platform_observation(
            self._platform_observer()
        )

    def poll(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout_s: float) -> int:
        return int(self._process.wait(timeout=timeout_s))

    def terminate(self) -> None:
        try:
            self._command_runner(
                ["docker", "stop", "--time", "1", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        finally:
            if self.poll() is None:
                self._process.terminate()

    def kill(self) -> None:
        try:
            self._command_runner(
                ["docker", "kill", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        finally:
            if self.poll() is None:
                self._process.kill()


class DockerWorkerProcessFactory:
    """Pinned no-network Docker implementation for the CLI production plan."""

    def __init__(
        self,
        *,
        project_root: Path | str,
        binding_set_root: Path | str,
        runtime_dir: Path | str,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> None:
        self.project_root = _canonical_directory(
            project_root, label="analytics sidecar project root"
        )
        self.binding_set_root = _canonical_directory(
            binding_set_root, label="analytics sidecar binding-set root"
        )
        self.runtime_dir = _canonical_directory(
            runtime_dir, label="analytics sidecar runtime root"
        )
        runtime_owner = self.runtime_dir.stat()
        _require(
            type(runtime_owner.st_uid) is int
            and runtime_owner.st_uid >= 0
            and type(runtime_owner.st_gid) is int
            and runtime_owner.st_gid >= 0,
            "analytics sidecar runtime owner is invalid",
        )
        self.container_user = f"{runtime_owner.st_uid}:{runtime_owner.st_gid}"
        self._command_runner = command_runner
        self._popen_factory = popen_factory
        self._peercred_platform_observation: dict[str, Any] | None = None

    def _observe_peercred_platform(self) -> Mapping[str, Any]:
        observed = _observe_peercred_pid0_platform_observation(
            command_runner=self._command_runner
        )
        if self._peercred_platform_observation is None:
            self._peercred_platform_observation = observed
        else:
            _require(
                observed == self._peercred_platform_observation,
                "Docker Desktop peercred platform changed across workers",
            )
        return dict(
            _validate_peercred_pid0_platform_observation(
                self._peercred_platform_observation
            )
        )

    @staticmethod
    def _worker(resource: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
        _require(resource in RESOURCES, "analytics Docker worker resource is invalid")
        worker = _mapping(value, f"analytics Docker {resource} worker config")
        _require(
            worker.get("engine") == ENGINE_BY_RESOURCE[resource],
            f"analytics Docker {resource} engine mismatch",
        )
        image = str(worker.get("image") or "")
        image_id = str(worker.get("image_id") or "")
        entrypoint = str(worker.get("entrypoint") or "")
        _require(
            image and image_id.startswith("sha256:") and len(image_id) == 71,
            f"analytics Docker {resource} image is not frozen",
        )
        _require(
            entrypoint.startswith("/") and "\n" not in entrypoint,
            f"analytics Docker {resource} entrypoint is invalid",
        )
        return worker

    def probe(
        self, resource: str, worker_config: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        worker = self._worker(resource, worker_config)
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            self.container_user,
            "--read-only",
            "--workdir",
            "/tmp",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
            "--env",
            "HOME=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp",
            "--env",
            "XDG_CONFIG_HOME=/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        ]
        if resource == "gpu":
            command.extend(["--gpus", "all"])
        command.extend(
            [
                "--entrypoint",
                str(worker["entrypoint"]),
                str(worker["image_id"]),
                "--capability",
            ]
        )
        try:
            completed = self._command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            value = json.loads(completed.stdout)
            return validate_runtime_probe(value, engine=ENGINE_BY_RESOURCE[resource])
        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ProtocolError,
        ) as error:
            raise SidecarError(
                f"analytics Docker {resource} runtime probe failed: {error}"
            ) from error

    def start(self, spec: WorkerLaunchSpec) -> WorkerHandle:
        worker = self._worker(spec.resource, spec.worker_config)
        _require(
            spec.binding_path.parent == self.binding_set_root,
            "analytics Docker binding path escaped its materialized set",
        )
        _require(
            spec.socket_path.parent == self.runtime_dir,
            "analytics Docker socket path escaped its runtime directory",
        )
        container_name = (
            f"vast-gst-analytics-{spec.lifecycle_id[:16]}-"
            f"{spec.branch.replace('_', '-')}-{spec.resource}"
        )
        _require(
            len(container_name) <= 128,
            "analytics Docker container name exceeds its bound",
        )
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--name",
            container_name,
            "--user",
            self.container_user,
            "--read-only",
            "--workdir",
            "/workspace",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
            "--env",
            "HOME=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp",
            "--env",
            "XDG_CONFIG_HOME=/tmp",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,src={self.project_root},dst=/workspace,readonly",
            "--mount",
            f"type=bind,src={self.binding_set_root},dst=/run/vast/bindings,readonly",
            "--mount",
            f"type=bind,src={self.runtime_dir},dst=/run/vast/analytics",
        ]
        if spec.resource == "gpu":
            command.extend(["--gpus", "all"])
        command.extend(
            [
                "--entrypoint",
                str(worker["entrypoint"]),
                str(worker["image_id"]),
                "--binding",
                spec.container_binding_path,
                "--socket",
                spec.container_socket_path,
                "--max-requests",
                str(spec.max_requests),
            ]
        )
        stdout_capture = tempfile.TemporaryFile(mode="w+b")
        stderr_capture = tempfile.TemporaryFile(mode="w+b")
        try:
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_capture,
                stderr=stderr_capture,
            )
        except OSError as error:
            stdout_capture.close()
            stderr_capture.close()
            raise SidecarError(
                f"cannot start analytics Docker worker {spec.branch}/{spec.resource}: {error}"
            ) from error
        return DockerWorkerHandle(
            process,
            container_name=container_name,
            command_runner=self._command_runner,
            platform_observer=self._observe_peercred_platform,
            stdout_capture=stdout_capture,
            stderr_capture=stderr_capture,
        )


def _default_bridge_factory(**values: Any) -> BridgeLike:
    from checkpoint_gstreamer_analytics_bridge import AnalyticsExecutionBridge

    return AnalyticsExecutionBridge(**values)


class GStreamerAnalyticsSidecar:
    """Own exactly eight workers, one front socket, and their bounded service."""

    def __init__(
        self,
        *,
        execution_config: Mapping[str, Any],
        binding_set_dir: Path | str,
        policy_capability_manifest: Mapping[str, Any],
        preprocessing_contract: Mapping[str, Any] | None,
        preprocessing_authority: Mapping[str, Any] | None = None,
        production_runtime_expectations: Mapping[str, Any] | None = None,
        runtime_dir: Path | str,
        front_socket: Path | str,
        evidence_root: Path | str,
        process_factory: WorkerProcessFactory,
        bridge_factory: BridgeFactory = _default_bridge_factory,
        max_connections: int,
        max_requests_per_connection: int,
        max_total_requests: int | None = None,
        service_mode: str = "engineering",
        startup_timeout_s: float = 120.0,
        shutdown_timeout_s: float = 10.0,
        monitor_interval_s: float = 0.1,
    ) -> None:
        self.execution_config = dict(
            _mapping(execution_config, "analytics execution config")
        )
        self.binding_set_dir = _absolute(binding_set_dir)
        self.policy_capability_manifest = dict(
            _mapping(
                policy_capability_manifest,
                "analytics policy capability manifest",
            )
        )
        self.preprocessing_contract = (
            None
            if preprocessing_contract is None
            else dict(
                _mapping(
                    preprocessing_contract,
                    "analytics preprocessing contract",
                )
            )
        )
        self.preprocessing_authority = (
            None
            if preprocessing_authority is None
            else _validate_preprocessing_authority_v1(
                _mapping(
                    preprocessing_authority,
                    "analytics preprocessing contract authority",
                )
            )
        )
        self.production_runtime_expectations = (
            None
            if production_runtime_expectations is None
            else _validate_production_runtime_expectations_v1(
                _mapping(
                    production_runtime_expectations,
                    "analytics external production runtime expectations",
                )
            )
        )
        self.lifecycle_id = uuid.uuid4().hex
        self.runtime_dir = _canonical_directory(
            runtime_dir,
            label="analytics sidecar runtime directory",
            reject_cwd_or_parent=True,
        )
        self._runtime_directory_identity = _stat_identity(self.runtime_dir)
        self._runtime_directory_custody: DirectoryFdCustodyV1 | None = None
        self._socket_retirement_directory = self.runtime_dir.parent / (
            f".vast-gst-analytics-retired-{self.lifecycle_id}"
        )
        self._socket_retirement_directory_identity: tuple[int, int, int] | None = None
        self._socket_retirement_directory_custody: DirectoryFdCustodyV1 | None = None
        if os.name == "posix":
            retirement_custody: DirectoryFdCustodyV1 | None = None
            try:
                self._runtime_directory_custody = (
                    DirectoryFdCustodyV1.open_existing(
                        self.runtime_dir,
                        label="analytics sidecar runtime directory",
                    )
                )
                retirement_custody = DirectoryFdCustodyV1.open_existing(
                    self.runtime_dir.parent,
                    label="analytics socket retirement parent",
                )
                retirement_custody.mkdir_child_exclusive(
                    self._socket_retirement_directory.name,
                    mode=0o700,
                )
                retirement_metadata = os.fstat(retirement_custody.directory_fd)
                runtime_metadata = os.fstat(
                    self._runtime_directory_custody.directory_fd
                )
                _require(
                    stat.S_ISDIR(retirement_metadata.st_mode)
                    and int(retirement_metadata.st_dev)
                    == int(runtime_metadata.st_dev)
                    and not os.listdir(retirement_custody.directory_fd),
                    "analytics socket retirement directory is invalid",
                )
                self._socket_retirement_directory_identity = (
                    int(retirement_metadata.st_dev),
                    int(retirement_metadata.st_ino),
                    int(stat.S_IFMT(retirement_metadata.st_mode)),
                )
                self._socket_retirement_directory_custody = retirement_custody
                retirement_custody = None
            except Exception as error:
                if retirement_custody is not None:
                    retirement_custody.close()
                if self._runtime_directory_custody is not None:
                    self._runtime_directory_custody.close()
                    self._runtime_directory_custody = None
                raise SidecarError(
                    "cannot establish analytics runtime/retirement dirfd custody"
                ) from error
        self.front_socket = _absolute(front_socket)
        _require(
            self.front_socket.parent == self.runtime_dir,
            "analytics sidecar front socket escaped its runtime directory",
        )
        _require(
            service_mode in {"engineering", PRODUCTION_SERVICE_MODE},
            "analytics sidecar service mode is invalid",
        )
        self.service_mode = service_mode
        self._production = service_mode == PRODUCTION_SERVICE_MODE
        if self._production:
            _require(
                self.preprocessing_contract is not None
                and self.preprocessing_authority is not None
                and self.production_runtime_expectations is not None
                and self.preprocessing_authority[
                    "preprocessing_contract_content_sha256"
                ]
                == canonical_sha256(self.preprocessing_contract),
                "analytics production receipt-bound preprocessing contract identity mismatch",
            )
            try:
                candidate_manifest_file_sha256 = hashlib.sha256(
                    canonical_json_bytes(self.policy_capability_manifest) + b"\n"
                ).hexdigest()
            except ProtocolError as error:
                raise SidecarError(
                    "analytics production preprocessing candidate manifest is not canonical JSON"
                ) from error
            authority_kind = self.preprocessing_authority["artifact_kind"]
            manifest_field = (
                "candidate_manifest_file_sha256"
                if authority_kind
                == "vast_guardian_preprocessing_contract_authority_v1"
                else "accepted_policy_capability_manifest_file_sha256"
            )
            _require(
                self.preprocessing_authority[manifest_field]
                == candidate_manifest_file_sha256,
                "analytics production preprocessing receipt candidate manifest/policy capability mismatch",
            )
            expectations = self.production_runtime_expectations
            _require(
                expectations["preprocessing_contract_content_sha256"]
                == self.preprocessing_authority[
                    "preprocessing_contract_content_sha256"
                ]
                and expectations["policy_contract_sha256"]
                == self.preprocessing_authority["policy_contract_sha256"],
                "analytics external production preprocessing/policy authority drifted",
            )
            configured_identity = _execution_config_identity(self.execution_config)
            configured_workers = _exact(
                self.execution_config.get("workers"),
                set(RESOURCES),
                "analytics production configured workers",
            )
            _require(
                configured_identity
                == expectations["execution_config_identity_sha256"]
                and {
                    resource: configured_workers[resource].get("image_id")
                    for resource in RESOURCES
                }
                == expectations["worker_image_ids"],
                "analytics external production execution config/worker image pins drifted",
            )
        else:
            _require(
                self.preprocessing_authority is None
                and self.production_runtime_expectations is None,
                "engineering sidecar cannot claim a production preprocessing authority",
            )
        self.process_factory = process_factory
        self.bridge_factory = bridge_factory
        if self._production:
            _require(
                type(max_total_requests) is int,
                "analytics production max_total_requests is required",
            )
            self._capacity = _production_capacity_contract(
                max_connections=max_connections,
                max_requests_per_connection=max_requests_per_connection,
                max_total_requests=max_total_requests,
            )
        else:
            _require(
                max_total_requests is None,
                "engineering sidecar cannot claim a production total request bound",
            )
            _require(
                type(max_connections) is int
                and 1 <= max_connections <= 1_000_000,
                "analytics sidecar max_connections is invalid",
            )
            _require(
                type(max_requests_per_connection) is int
                and 1 <= max_requests_per_connection <= 1_000_000,
                "analytics sidecar max_requests_per_connection is invalid",
            )
            self._capacity = None
        _require(
            type(startup_timeout_s) in {int, float}
            and 0 < startup_timeout_s <= 3600,
            "analytics sidecar startup timeout is invalid",
        )
        _require(
            type(shutdown_timeout_s) in {int, float}
            and 0 < shutdown_timeout_s <= 300,
            "analytics sidecar shutdown timeout is invalid",
        )
        _require(
            type(monitor_interval_s) in {int, float}
            and 0.001 <= monitor_interval_s <= 5,
            "analytics sidecar monitor interval is invalid",
        )
        self.evidence = (
            ProductionLifecycleEvidenceSink(evidence_root)
            if self._production
            else EngineeringEvidenceSink(evidence_root)
        )
        self.max_connections = max_connections
        self.max_requests_per_connection = max_requests_per_connection
        self.max_total_requests = max_total_requests
        self.startup_timeout_s = float(startup_timeout_s)
        self.shutdown_timeout_s = float(shutdown_timeout_s)
        self.monitor_interval_s = float(monitor_interval_s)
        self._owned_sockets: list[_OwnedSocket] = []
        self._retired_socket_nodes: list[dict[str, Any]] = []
        self._handles: dict[tuple[str, str], WorkerHandle] = {}
        self._connections: dict[tuple[str, str], socket.socket] = {}
        self._bridge: BridgeLike | None = None
        self._call_manifests: list[Mapping[str, Any]] = []
        self._worker_records: list[dict[str, Any]] = []
        self._pending_peer_identities: dict[
            tuple[str, str], dict[str, Any]
        ] = {}
        self._runtime_probes: dict[str, Mapping[str, Any]] = {}
        self._stop = threading.Event()
        self._front_connections: set[socket.socket] = set()
        self._front_connections_lock = threading.Lock()
        self._production_counters = (
            _RollingProductionCounters(max_total_requests=max_total_requests)
            if self._production and type(max_total_requests) is int
            else None
        )
        self._production_state = "new"
        self._production_started_ns: int | None = None
        self._production_materialized: MaterializedBindingSet | None = None
        self._production_authority: dict[str, Any] | None = None
        self._production_lifecycle: dict[str, Any] | None = None
        self._production_front: _OwnedSocket | None = None
        self._production_control: _OwnedSocket | None = None
        self._production_front_thread: threading.Thread | None = None
        self._production_control_thread: threading.Thread | None = None
        self._production_connection_threads: set[threading.Thread] = set()
        self._production_threads_lock = threading.Lock()
        self._production_failure: BaseException | None = None
        self._production_failure_lock = threading.Lock()
        self._guardian_stop_requested = threading.Event()
        self._guardian_stop_attestation: dict[str, Any] | None = None
        self._guardian_stop_attestation_lock = threading.Lock()

    def _verify_runtime_directory_custody(self) -> None:
        try:
            custody = self._runtime_directory_custody
            if os.name == "posix":
                _require(
                    custody is not None,
                    "analytics runtime dirfd custody is unavailable",
                )
                custody.verify()
                opened = os.fstat(custody.directory_fd)
                _require(
                    stat.S_ISDIR(opened.st_mode)
                    and (
                        int(opened.st_dev),
                        int(opened.st_ino),
                        int(stat.S_IFMT(opened.st_mode)),
                    )
                    == self._runtime_directory_identity
                    and _stat_identity(self.runtime_dir)
                    == self._runtime_directory_identity
                    and not _is_reparse(self.runtime_dir),
                    "analytics runtime directory identity drifted",
                )
            else:
                _require(
                    _stat_identity(self.runtime_dir)
                    == self._runtime_directory_identity
                    and not _is_reparse(self.runtime_dir),
                    "analytics runtime directory identity drifted",
                )
        except SidecarError:
            raise
        except Exception as error:
            raise SidecarError(
                "analytics runtime directory custody changed"
            ) from error

    def _verify_socket_retirement_namespace(self) -> None:
        if os.name != "posix":
            _require(
                self._socket_retirement_directory_custody is None
                and self._socket_retirement_directory_identity is None
                and self._retired_socket_nodes == [],
                "non-POSIX analytics socket retirement state drifted",
            )
            return
        try:
            custody = self._socket_retirement_directory_custody
            _require(
                custody is not None
                and self._socket_retirement_directory_identity is not None,
                "analytics socket retirement dirfd custody is unavailable",
            )
            custody.verify()
            opened = os.fstat(custody.directory_fd)
            _require(
                (
                    int(opened.st_dev),
                    int(opened.st_ino),
                    int(stat.S_IFMT(opened.st_mode)),
                )
                == self._socket_retirement_directory_identity
                and custody.path == self._socket_retirement_directory,
                "analytics socket retirement directory identity drifted",
            )
            records_by_name: dict[str, Mapping[str, Any]] = {}
            for raw_record in self._retired_socket_nodes:
                record = _validate_retired_socket_record_v1(
                    raw_record,
                    expected_lifecycle_id=self.lifecycle_id,
                )
                name = record["retired_name"]
                _require(
                    name not in records_by_name,
                    "analytics socket retirement ledger contains duplicates",
                )
                records_by_name[name] = record
                metadata = os.stat(
                    name,
                    dir_fd=custody.directory_fd,
                    follow_symlinks=False,
                )
                socket_identity = record["socket_identity"]
                _require(
                    stat.S_ISSOCK(metadata.st_mode)
                    and int(metadata.st_nlink) == 1
                    and {
                        "st_dev": int(metadata.st_dev),
                        "st_ino": int(metadata.st_ino),
                        "st_mode_type": int(stat.S_IFMT(metadata.st_mode)),
                        "st_nlink": int(metadata.st_nlink),
                    }
                    == socket_identity,
                    f"retired analytics socket node drifted: {name}",
                )
            _require(
                set(os.listdir(custody.directory_fd)) == set(records_by_name),
                "analytics socket retirement namespace drifted",
            )
            custody.verify()
        except SidecarError:
            raise
        except Exception as error:
            raise SidecarError(
                "analytics socket retirement namespace changed"
            ) from error

    def _record_retired_socket_node(self, record: Mapping[str, Any]) -> None:
        checked = _validate_retired_socket_record_v1(
            record,
            expected_lifecycle_id=self.lifecycle_id,
        )
        existing = {
            item["retired_name"]: item for item in self._retired_socket_nodes
        }.get(checked["retired_name"])
        if existing is None:
            self._retired_socket_nodes.append(checked)
        else:
            _require(
                existing == checked,
                "analytics socket retirement ledger entry drifted",
            )
        self._verify_socket_retirement_namespace()

    def _close_runtime_directory_custody(self) -> None:
        custody = self._runtime_directory_custody
        retirement_custody = self._socket_retirement_directory_custody
        failure: BaseException | None = None
        try:
            self._verify_runtime_directory_custody()
            self._verify_socket_retirement_namespace()
        except BaseException as error:
            failure = error
        finally:
            self._runtime_directory_custody = None
            self._socket_retirement_directory_custody = None
            if custody is not None:
                custody.close()
            if retirement_custody is not None:
                retirement_custody.close()
        if failure is not None:
            if isinstance(failure, SidecarError):
                raise failure
            raise SidecarError(
                "analytics runtime directory custody close failed"
            ) from failure

    def __del__(self) -> None:
        custody = getattr(self, "_runtime_directory_custody", None)
        self._runtime_directory_custody = None
        retirement_custody = getattr(
            self, "_socket_retirement_directory_custody", None
        )
        self._socket_retirement_directory_custody = None
        for item in (custody, retirement_custody):
            if item is not None:
                try:
                    item.close()
                except Exception:
                    pass

    def _worker_socket_path(self, branch: str, resource: str) -> Path:
        self._verify_runtime_directory_custody()
        return self.runtime_dir / f"worker-{branch}-{resource}.sock"

    def _assert_workers_live(self, *, phase: str) -> None:
        for key, handle in self._handles.items():
            status = handle.poll()
            if status is not None:
                diagnostic = ""
                reporter = getattr(handle, "failure_diagnostic", None)
                if callable(reporter):
                    try:
                        diagnostic = f"; {reporter()}"
                    except BaseException:
                        diagnostic = "; diagnostic_capture_failed"
                raise SidecarError(
                    f"analytics worker {key[0]}/{key[1]} exited during {phase}: "
                    f"{status}{diagnostic}"
                )

    def _probe_and_load(self) -> MaterializedBindingSet:
        workers = _exact(
            self.execution_config.get("workers"),
            {"cpu", "gpu"},
            "analytics sidecar workers config",
        )
        probes: dict[str, Mapping[str, Any]] = {}
        for resource in RESOURCES:
            try:
                observed = self.process_factory.probe(
                    resource, _mapping(workers[resource], f"{resource} worker config")
                )
                probes[resource] = validate_runtime_probe(
                    observed, engine=ENGINE_BY_RESOURCE[resource]
                )
            except (ProtocolError, SidecarError):
                raise
            except BaseException as error:
                raise SidecarError(
                    f"analytics {resource} runtime probe failed: {error}"
                ) from error
        self._runtime_probes = probes
        materialized = load_materialized_binding_set(
            self.binding_set_dir,
            execution_config=self.execution_config,
            runtime_probes=probes,
        )
        self._assert_preprocessing_binding_closure(materialized)
        self._assert_external_production_runtime_material(materialized)
        return materialized

    def _assert_external_production_runtime_material(
        self, materialized: MaterializedBindingSet
    ) -> None:
        if not self._production:
            return
        expectations = self.production_runtime_expectations
        _require(
            expectations is not None,
            "analytics external production runtime expectations are unavailable",
        )
        identity = _exact(
            materialized.index.get("identity"),
            {"algorithm", "sha256"},
            "analytics production materialized binding-set identity",
        )
        _require(
            identity.get("algorithm") == "sha256"
            and identity.get("sha256")
            == expectations["binding_set_identity_sha256"]
            and materialized.index.get("bindings_identity_sha256")
            == expectations["bindings_identity_sha256"],
            "analytics external production binding-set pins drifted",
        )

    def _assert_preprocessing_binding_closure(
        self, materialized: MaterializedBindingSet
    ) -> None:
        _require(
            set(materialized.bindings) == EXPECTED_KEYS
            and set(materialized.capabilities) == EXPECTED_KEYS,
            "analytics preprocessing binding coverage is not exact 8",
        )
        if self.preprocessing_contract is None:
            _require(
                not self._production,
                "analytics production preprocessing contract is unavailable",
            )
            return
        content_sha256 = canonical_sha256(self.preprocessing_contract)
        if self._production:
            _require(
                self.preprocessing_authority is not None
                and self.preprocessing_authority[
                    "preprocessing_contract_content_sha256"
                ]
                == content_sha256,
                "analytics production receipt-bound preprocessing contract identity mismatch",
            )
        for branch in BRANCHES:
            for resource in RESOURCES:
                key = (branch, resource)
                _require(
                    materialized.bindings[key].get(
                        "preprocessing_contract_sha256"
                    )
                    == content_sha256,
                    f"analytics preprocessing binding {branch}/{resource} identity mismatch",
                )
                _require(
                    materialized.capabilities[key].get(
                        "preprocessing_contract_sha256"
                    )
                    == content_sha256,
                    f"analytics preprocessing capability {branch}/{resource} identity mismatch",
                )

    def _launch_workers(
        self, materialized: MaterializedBindingSet
    ) -> dict[tuple[str, str], socket.socket]:
        workers = _exact(
            self.execution_config.get("workers"),
            {"cpu", "gpu"},
            "analytics sidecar workers config",
        )
        worker_listeners: dict[tuple[str, str], _OwnedSocket] = {}
        total_request_bound = (
            self.max_total_requests
            if self._production
            else self.max_connections * self.max_requests_per_connection
        )
        _require(
            type(total_request_bound) is int
            and 1 <= total_request_bound <= PRODUCTION_REQUEST_LIMIT,
            "analytics worker total request bound is invalid",
        )
        try:
            for branch in BRANCHES:
                for resource in RESOURCES:
                    key = (branch, resource)
                    path = self._worker_socket_path(branch, resource)
                    owned = _open_owned_listener(path, backlog=1)
                    self._verify_runtime_directory_custody()
                    self._owned_sockets.append(owned)
                    worker_listeners[key] = owned
                    spec = WorkerLaunchSpec(
                        branch=branch,
                        resource=resource,
                        engine=ENGINE_BY_RESOURCE[resource],
                        binding_path=materialized.binding_paths[key],
                        socket_path=path,
                        container_binding_path=(
                            f"/run/vast/bindings/"
                            f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
                        ),
                        container_socket_path=(
                            f"/run/vast/analytics/{path.name}"
                        ),
                        worker_config=dict(
                            _mapping(
                                workers[resource],
                                f"analytics {resource} worker config",
                            )
                        ),
                        max_requests=total_request_bound,
                        lifecycle_id=self.lifecycle_id,
                    )
                    try:
                        handle = self.process_factory.start(spec)
                    except SidecarError:
                        raise
                    except BaseException as error:
                        raise SidecarError(
                            f"cannot start analytics worker {branch}/{resource}: {error}"
                        ) from error
                    _require(
                        type(handle.pid) is int and handle.pid > 0,
                        f"analytics worker {branch}/{resource} supervisor PID is invalid",
                    )
                    self._handles[key] = handle
            _require(
                set(self._handles) == EXPECTED_KEYS,
                "analytics worker process coverage is not exact 8",
            )

            deadline = time.monotonic() + self.startup_timeout_s
            for branch in BRANCHES:
                for resource in RESOURCES:
                    key = (branch, resource)
                    handle = self._handles[key]
                    self._assert_workers_live(phase="startup")
                    remaining = deadline - time.monotonic()
                    _require(
                        remaining > 0,
                        f"timed out starting analytics worker {branch}/{resource}",
                    )
                    try:
                        expected_peer_pid = handle.expected_peer_pid(remaining)
                    except SidecarError:
                        raise
                    except BaseException as error:
                        raise SidecarError(
                            f"cannot attest analytics worker {branch}/{resource} PID: {error}"
                        ) from error
                    owned = worker_listeners[key]
                    listener = owned.listener
                    _require(
                        listener is not None,
                        f"analytics worker {branch}/{resource} listener disappeared",
                    )
                    connection: socket.socket | None = None
                    while connection is None:
                        self._assert_workers_live(phase="startup")
                        remaining = deadline - time.monotonic()
                        _require(
                            remaining > 0,
                            f"timed out accepting analytics worker {branch}/{resource}",
                        )
                        listener.settimeout(
                            min(self.monitor_interval_s, remaining)
                        )
                        try:
                            connection, _address = listener.accept()
                        except socket.timeout:
                            continue
                        except OSError as error:
                            raise SidecarError(
                                f"cannot accept analytics worker {branch}/{resource}: {error}"
                            ) from error
                    try:
                        peer_identity = _attest_worker_peer_identity(
                            connection,
                            docker_state_pid=expected_peer_pid,
                            worker_handle=handle,
                            socket_dir=self.runtime_dir,
                            socket_path=owned.path,
                        )
                    except BaseException:
                        connection.close()
                        raise
                    observed_peer_pid = int(peer_identity["peer_pid"])
                    self._connections[key] = connection
                    self._pending_peer_identities[key] = peer_identity
                    self._worker_records.append(
                        {
                            "branch": branch,
                            "resource": resource,
                            "engine": ENGINE_BY_RESOURCE[resource],
                            "supervisor_pid": handle.pid,
                            "peer_pid": observed_peer_pid,
                            "peer_identity": dict(peer_identity),
                            "peer_identity_sha256": peer_identity[
                                "identity_sha256"
                            ],
                            "binding_path": materialized.binding_paths[key].name,
                            "binding_sha256": hashlib.sha256(
                                canonical_json_bytes(materialized.bindings[key])
                            ).hexdigest(),
                            "capability_sha256": canonical_sha256(
                                materialized.capabilities[key]
                            ),
                        }
                    )
                    retired = _close_owned_socket(
                        owned,
                        directory_custody=self._runtime_directory_custody,
                        retirement_custody=(
                            self._socket_retirement_directory_custody
                        ),
                        lifecycle_id=self.lifecycle_id,
                    )
                    if retired is not None:
                        self._record_retired_socket_node(retired)
                    self._owned_sockets.remove(owned)
            _require(
                set(self._connections) == EXPECTED_KEYS,
                "analytics worker socket coverage is not exact 8",
            )
            self._assert_workers_live(phase="pre-bridge attestation")
            return dict(self._connections)
        except BaseException:
            raise

    def _construct_bridge(self, materialized: MaterializedBindingSet) -> None:
        self._assert_workers_live(phase="bridge construction")
        try:
            bridge = self.bridge_factory(
                policy_capability_manifest=self.policy_capability_manifest,
                worker_connections=dict(self._connections),
                worker_capabilities=dict(materialized.capabilities),
                worker_bindings=dict(materialized.bindings),
                preprocessing_contract=self.preprocessing_contract,
            )
        except SidecarError:
            raise
        except BaseException as error:
            raise SidecarError(
                f"analytics bridge startup/hello attestation failed: {error}"
            ) from error
        self._bridge = bridge
        _require(
            set(self._pending_peer_identities) == EXPECTED_KEYS,
            "analytics worker pending peer identity coverage is not exact 8",
        )
        completed = {
            key: _complete_peer_identity_after_handshake(peer)
            for key, peer in self._pending_peer_identities.items()
        }
        for record in self._worker_records:
            key = (str(record["branch"]), str(record["resource"]))
            peer = completed[key]
            record["peer_identity"] = dict(peer)
            record["peer_identity_sha256"] = peer["identity_sha256"]
        self._pending_peer_identities = completed
        self._assert_workers_live(phase="post-hello attestation")

    def _record_production_failure(self, error: BaseException) -> None:
        _require(
            self._production,
            "engineering sidecar cannot record a production service failure",
        )
        with self._production_failure_lock:
            if self._production_failure is None:
                self._production_failure = error
        self._stop.set()

    def _assert_production_internal_live(self) -> None:
        self._verify_runtime_directory_custody()
        _require(
            self._production
            and self._production_state in {"starting", "running"}
            and self._bridge is not None
            and self._production_front is not None
            and self._production_control is not None
            and self._production_front.listener is not None
            and self._production_control.listener is not None,
            "analytics production service is not live",
        )
        # A reset worker socket and the worker process exit are the same
        # causal event.  Prefer the captured container diagnostic over the
        # bridge's secondary ECONNRESET when both are observable.
        self._assert_workers_live(phase="production health attestation")
        with self._production_failure_lock:
            failure = self._production_failure
        _require(
            failure is None,
            f"analytics production service failed: {failure}",
        )
        _require(
            self._production_front_thread is not None
            and self._production_front_thread.is_alive()
            and self._production_control_thread is not None
            and self._production_control_thread.is_alive(),
            "analytics production guardian thread is not live",
        )
        _require(
            _stat_identity(self._production_front.path)
            == self._production_front.identity
            and _stat_identity(self._production_control.path)
            == self._production_control.identity,
            "analytics production owned socket identity drifted",
        )
        _require(
            set(self._connections) == EXPECTED_KEYS
            and all(
                connection.fileno() >= 0
                and connection.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0
                for connection in self._connections.values()
            ),
            "analytics production bridge worker connection health drifted",
        )
        _assert_live_production_socket_pin(
            _production_socket_pin(self._production_front.path)
        )
        _assert_live_production_socket_pin(
            _production_socket_pin(self._production_control.path)
        )

    def _production_front_loop(self, front: _OwnedSocket) -> None:
        listener = front.listener
        _require(listener is not None, "analytics production front listener vanished")
        accepted = 0
        errors: list[BaseException] = []
        errors_lock = threading.Lock()
        try:
            while not self._stop.is_set():
                self._assert_workers_live(phase="production front service")
                if accepted >= self.max_connections:
                    raise SidecarError(
                        "analytics production connection capacity was exhausted"
                    )
                listener.settimeout(self.monitor_interval_s)
                try:
                    endpoint, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError as error:
                    if self._stop.is_set():
                        return
                    raise SidecarError(
                        f"analytics production front listener failed: {error}"
                    ) from error
                accepted += 1
                _require(
                    self._production_counters is not None,
                    "analytics production counters are unavailable",
                )
                self._production_counters.connection_opened()
                thread = threading.Thread(
                    target=self._serve_connection,
                    args=(endpoint, errors, errors_lock),
                    name=f"vast-gst-production-front-{accepted}",
                    daemon=False,
                )
                with self._front_connections_lock:
                    self._front_connections.add(endpoint)
                with self._production_threads_lock:
                    self._production_connection_threads.add(thread)
                try:
                    thread.start()
                except BaseException:
                    with self._production_threads_lock:
                        self._production_connection_threads.discard(thread)
                    with self._front_connections_lock:
                        self._front_connections.discard(endpoint)
                    endpoint.close()
                    self._production_counters.connection_closed(
                        clean_eof=False,
                        failed=True,
                    )
                    raise
        except BaseException as error:
            if not self._stop.is_set():
                self._record_production_failure(error)

    def _production_control_loop(self, control: _OwnedSocket) -> None:
        listener = control.listener
        _require(
            listener is not None,
            "analytics production control listener vanished",
        )
        try:
            while not self._stop.is_set():
                listener.settimeout(self.monitor_interval_s)
                try:
                    endpoint, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError as error:
                    if self._stop.is_set():
                        return
                    raise SidecarError(
                        f"analytics production control listener failed: {error}"
                    ) from error
                try:
                    raw = _peer_credentials_raw(endpoint)
                    peer_pid, peer_uid, peer_gid = struct.unpack("3i", raw)
                    _require(
                        peer_pid > 0
                        and peer_uid == os.getuid()
                        and peer_gid == os.getgid(),
                        "analytics production control peer identity drifted",
                    )
                    message, descriptors = receive_packet(
                        endpoint, expected_fds=0
                    )
                    close_fds(descriptors)
                    message_type = message.get("message_type")
                    command_fields = {
                        "schema_version",
                        "message_type",
                        "lifecycle_id",
                        "service_authority_sha256",
                        "nonce",
                    }
                    if message_type == "production_guardian_stop":
                        command_fields.add("canonical_command_sha256")
                    command = _exact(
                        message,
                        command_fields,
                        "analytics production guardian control command",
                    )
                    authority = self._production_authority
                    _require(
                        authority is not None
                        and command.get("schema_version") == 1
                        and command.get("lifecycle_id") == self.lifecycle_id
                        and command.get("service_authority_sha256")
                        == authority["service_authority_sha256"],
                        "analytics production guardian control binding drifted",
                    )
                    nonce = str(command.get("nonce") or "")
                    _require(
                        re.fullmatch(r"[0-9a-f]{64}", nonce) is not None,
                        "analytics production guardian control nonce drifted",
                    )
                    if message_type == "production_guardian_status":
                        self._assert_production_internal_live()
                        send_packet(
                            endpoint,
                            {
                                "schema_version": 1,
                                "message_type": (
                                    "production_guardian_status_response"
                                ),
                                "nonce": nonce,
                                "authority": authority,
                            },
                        )
                    elif message_type == "production_guardian_stop":
                        attestation = _build_guardian_stop_attestation_v1(
                            command,
                            authority=authority,
                            peer_pid=peer_pid,
                            peer_uid=peer_uid,
                            peer_gid=peer_gid,
                        )
                        with self._guardian_stop_attestation_lock:
                            _require(
                                self._guardian_stop_attestation is None,
                                "analytics production guardian stop was already accepted",
                            )
                            self._guardian_stop_attestation = _canonical_clone(
                                attestation
                            )
                        send_packet(
                            endpoint,
                            {
                                "schema_version": 1,
                                "message_type": "production_guardian_stop_accepted",
                                "lifecycle_id": self.lifecycle_id,
                                "service_authority_sha256": authority[
                                    "service_authority_sha256"
                                ],
                                "nonce": nonce,
                                "canonical_command_sha256": attestation[
                                    "canonical_command_sha256"
                                ],
                            },
                        )
                        self._guardian_stop_requested.set()
                    else:
                        raise SidecarError(
                            "analytics production guardian control command drifted"
                        )
                finally:
                    try:
                        endpoint.close()
                    except OSError:
                        pass
        except BaseException as error:
            if not self._stop.is_set():
                self._record_production_failure(error)

    def _serve_connection(
        self,
        endpoint: socket.socket,
        errors: list[BaseException],
        errors_lock: threading.Lock,
    ) -> None:
        clean_eof = False
        failed = False
        protocol_mode: str | None = None
        worker_route: tuple[str, str] | None = None
        handled_requests = 0
        try:
            while handled_requests < self.max_requests_per_connection:
                try:
                    message, descriptors = receive_packet(endpoint)
                except PeerClosed:
                    if self._production:
                        clean_eof = True
                        return
                    raise
                request_route: tuple[str, str] | None = None
                request_reserved = False
                request_completed = False
                try:
                    message_type = str(message.get("message_type") or "")
                    _require(
                        self._bridge is not None,
                        "analytics sidecar bridge is unavailable",
                    )
                    if protocol_mode is None and message_type == "hello":
                        _require(
                            self._production,
                            "analytics worker proxy protocol requires production guardian",
                        )
                        _require(
                            len(descriptors) == 0,
                            "analytics execution proxy hello cannot contain file descriptors",
                        )
                        worker_route, acknowledgement = (
                            self._bridge.worker_protocol_handshake(message)
                        )
                        _require(
                            worker_route in EXPECTED_KEYS,
                            "analytics execution proxy handshake route drifted",
                        )
                        send_packet(endpoint, acknowledgement)
                        protocol_mode = "worker"
                        continue
                    if protocol_mode is None:
                        protocol_mode = "gstreamer"
                    if protocol_mode == "worker":
                        _require(
                            message_type == "infer_request"
                            and worker_route is not None,
                            "analytics execution proxy connection protocol changed",
                        )
                        _require(
                            len(descriptors) == 1,
                            "analytics execution proxy request must contain exactly one file descriptor",
                        )
                        payload_record = _mapping(
                            message.get("tensor"),
                            "analytics execution proxy tensor",
                        )
                    else:
                        _require(
                            message_type == "analytics_execute",
                            "analytics GStreamer connection protocol changed",
                        )
                        _require(
                            len(descriptors) == 1,
                            "analytics GStreamer request must contain exactly one file descriptor",
                        )
                        payload_record = _mapping(
                            message.get("payload"),
                            "analytics sidecar request payload",
                        )
                    byte_count = payload_record.get("byte_length")
                    _require(
                        type(byte_count) is int and byte_count > 0,
                        "analytics sidecar request byte_length is invalid",
                    )
                    digest = _sha(
                        payload_record.get("sha256"),
                        "analytics sidecar request payload SHA-256",
                    )
                    payload = verify_sealed_memfd(
                        descriptors[0],
                        expected_bytes=byte_count,
                        expected_sha256=digest,
                    )
                    if self._production:
                        if protocol_mode == "worker":
                            _require(
                                worker_route is not None,
                                "analytics execution proxy route is unavailable",
                            )
                            branch, resource = worker_route
                            frame_branch = str(
                                _mapping(
                                    message.get("frame"),
                                    "analytics execution proxy request frame",
                                ).get("branch")
                                or ""
                            )
                            _require(
                                frame_branch == branch
                                and message.get("engine")
                                == ENGINE_BY_RESOURCE[resource],
                                "analytics execution proxy request changed route",
                            )
                        else:
                            branch = str(
                                _mapping(
                                    message.get("frame"),
                                    "analytics production request frame",
                                ).get("branch")
                                or ""
                            )
                            resource = str(
                                _mapping(
                                    message.get("decision"),
                                    "analytics production request decision",
                                ).get("selected_resource")
                                or ""
                            )
                        _require(
                            (branch, resource) in EXPECTED_KEYS,
                            "analytics production request route drifted",
                        )
                        request_route = (branch, resource)
                        _require(
                            self._production_counters is not None,
                            "analytics production counters are unavailable",
                        )
                        self._production_counters.request_started(
                            branch=branch,
                            resource=resource,
                            request_id=str(message.get("request_id") or ""),
                        )
                        request_reserved = True
                    try:
                        output: bytes | None = None
                        if protocol_mode == "worker":
                            _require(
                                worker_route is not None,
                                "analytics execution proxy route is unavailable",
                            )
                            worker_response, output = (
                                self._bridge.execute_worker_protocol(
                                    message,
                                    payload,
                                    route=worker_route,
                                )
                            )
                            response = dict(worker_response)
                        else:
                            response = dict(self._bridge.execute(message, payload))
                    except BaseException as execution_error:
                        if not self._production:
                            manifest = self.evidence.persist_call(
                                request=message,
                                response={},
                                payload=payload,
                                lifecycle_id=self.lifecycle_id,
                                failure=execution_error,
                            )
                            self._call_manifests.append(manifest)
                        raise
                    if not self._production:
                        manifest = self.evidence.persist_call(
                            request=message,
                            response=response,
                            payload=payload,
                            lifecycle_id=self.lifecycle_id,
                        )
                        self._call_manifests.append(manifest)
                    if protocol_mode == "worker":
                        _require(
                            output is not None,
                            "analytics execution proxy output is unavailable",
                        )
                        output_descriptor = create_sealed_memfd(
                            "vast-proxy-output-" + str(message["request_id"]),
                            output,
                        )
                        try:
                            send_packet(
                                endpoint,
                                response,
                                fds=(output_descriptor,),
                            )
                        finally:
                            close_fds((output_descriptor,))
                    else:
                        send_packet(endpoint, response)
                    if self._production:
                        _require(
                            request_route is not None
                            and self._production_counters is not None,
                            "analytics production completed route is unavailable",
                        )
                        self._production_counters.request_completed(
                            branch=request_route[0],
                            resource=request_route[1],
                        )
                        request_completed = True
                    handled_requests += 1
                except BaseException:
                    if (
                        self._production
                        and request_reserved
                        and not request_completed
                        and request_route is not None
                        and self._production_counters is not None
                    ):
                        self._production_counters.request_failed(
                            branch=request_route[0],
                            resource=request_route[1],
                        )
                    raise
                finally:
                    close_fds(descriptors)
            if self._production:
                raise SidecarError(
                    "analytics production per-connection request capacity was exhausted"
                )
        except BaseException as error:
            if self._production:
                if not self._stop.is_set():
                    failed = True
                    self._record_production_failure(error)
            else:
                with errors_lock:
                    errors.append(error)
                self._stop.set()
        finally:
            with self._front_connections_lock:
                self._front_connections.discard(endpoint)
            try:
                endpoint.close()
            except OSError:
                pass
            if self._production and self._production_counters is not None:
                self._production_counters.connection_closed(
                    clean_eof=clean_eof,
                    failed=failed,
                )
            if self._production:
                current = threading.current_thread()
                with self._production_threads_lock:
                    self._production_connection_threads.discard(current)

    def _close_front_connections(self) -> None:
        with self._front_connections_lock:
            endpoints = tuple(self._front_connections)
        for endpoint in endpoints:
            try:
                endpoint.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                endpoint.close()
            except OSError:
                pass

    def _serve_front(self, front: _OwnedSocket) -> None:
        listener = front.listener
        _require(listener is not None, "analytics front listener is unavailable")
        errors: list[BaseException] = []
        errors_lock = threading.Lock()
        threads: list[threading.Thread] = []
        accepted = 0
        try:
            while accepted < self.max_connections and not self._stop.is_set():
                self._assert_workers_live(phase="front service")
                listener.settimeout(self.monitor_interval_s)
                try:
                    endpoint, _address = listener.accept()
                except socket.timeout:
                    continue
                except OSError as error:
                    if self._stop.is_set():
                        break
                    raise SidecarError(
                        f"analytics front listener failed: {error}"
                    ) from error
                thread = threading.Thread(
                    target=self._serve_connection,
                    args=(endpoint, errors, errors_lock),
                    name=f"vast-gst-analytics-front-{accepted}",
                )
                threads.append(thread)
                accepted += 1
                with self._front_connections_lock:
                    self._front_connections.add(endpoint)
                thread.start()
            while any(thread.is_alive() for thread in threads):
                self._assert_workers_live(phase="front request")
                if self._stop.wait(self.monitor_interval_s):
                    break
            if self._stop.is_set():
                for thread in threads:
                    thread.join(timeout=self.shutdown_timeout_s)
            else:
                for thread in threads:
                    thread.join()
            with errors_lock:
                if errors:
                    error = errors[0]
                    raise SidecarError(f"analytics bridge failure: {error}") from error
            _require(
                accepted == self.max_connections,
                "analytics front service drained before its bounded connection count",
            )
        finally:
            self._stop.set()
            self._close_front_connections()
            for thread in threads:
                thread.join(timeout=self.shutdown_timeout_s)
            _require(
                not any(thread.is_alive() for thread in threads),
                "analytics front service thread survived bounded shutdown",
            )

    def _shutdown(self) -> list[str]:
        errors: list[str] = []
        try:
            self._verify_runtime_directory_custody()
        except BaseException as error:
            errors.append(f"runtime_directory_custody:{error}")
        self._stop.set()
        self._close_front_connections()
        for owned in tuple(reversed(self._owned_sockets)):
            try:
                retired = _close_owned_socket(
                    owned,
                    directory_custody=self._runtime_directory_custody,
                    retirement_custody=(
                        self._socket_retirement_directory_custody
                    ),
                    lifecycle_id=self.lifecycle_id,
                )
                if retired is not None:
                    self._record_retired_socket_node(retired)
            except BaseException as error:
                errors.append(f"socket_cleanup:{owned.path.name}:{error}")
            else:
                if owned in self._owned_sockets:
                    self._owned_sockets.remove(owned)
        if self._bridge is not None:
            try:
                self._bridge.close()
            except BaseException as error:
                errors.append(f"bridge_close:{error}")
            self._bridge = None
        for connection in self._connections.values():
            try:
                connection.close()
            except OSError:
                pass
        self._connections.clear()

        graceful_deadline = time.monotonic() + self.shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, graceful_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired):
                    pass
                except BaseException as error:
                    errors.append(f"worker_wait:{key[0]}/{key[1]}:{error}")
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.terminate()
                except BaseException as error:
                    errors.append(f"worker_terminate:{key[0]}/{key[1]}:{error}")
        terminate_deadline = time.monotonic() + self.shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, terminate_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired):
                    pass
                except BaseException as error:
                    errors.append(
                        f"worker_terminate_wait:{key[0]}/{key[1]}:{error}"
                    )
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.kill()
                except BaseException as error:
                    errors.append(f"worker_kill:{key[0]}/{key[1]}:{error}")
        kill_deadline = time.monotonic() + self.shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, kill_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired) as error:
                    errors.append(
                        f"worker_survived_kill:{key[0]}/{key[1]}:{error}"
                    )
                except BaseException as error:
                    errors.append(
                        f"worker_kill_wait:{key[0]}/{key[1]}:{error}"
                    )
        for key, handle in self._handles.items():
            if handle.poll() is None:
                errors.append(f"worker_still_live:{key[0]}/{key[1]}")
        try:
            self._verify_runtime_directory_custody()
        except BaseException as error:
            marker = f"runtime_directory_custody:{error}"
            if marker not in errors:
                errors.append(marker)
        return errors

    def run(self) -> dict[str, Any]:
        started_ns = time.monotonic_ns()
        failure: BaseException | None = None
        front: _OwnedSocket | None = None
        materialized: MaterializedBindingSet | None = None
        try:
            self._verify_runtime_directory_custody()
            materialized = self._probe_and_load()
            self._launch_workers(materialized)
            self._construct_bridge(materialized)
            self._assert_workers_live(phase="front publication")
            front = _open_owned_listener(
                self.front_socket,
                backlog=min(128, self.max_connections),
                atomic_publish=True,
            )
            self._owned_sockets.append(front)
            self._serve_front(front)
            self._assert_workers_live(phase="bounded service completion")
        except BaseException as error:
            failure = error
        cleanup_errors = self._shutdown()
        finished_ns = time.monotonic_ns()
        try:
            _require(
                _stat_identity(self.runtime_dir)
                == self._runtime_directory_identity
                and not _is_reparse(self.runtime_dir)
                and not any(self.runtime_dir.iterdir()),
                "analytics production runtime directory was not restored empty",
            )
        except BaseException as error:
            cleanup_errors.append(f"runtime_directory_cleanup:{error}")
        try:
            self._close_runtime_directory_custody()
        except BaseException as error:
            cleanup_errors.append(f"runtime_directory_custody_close:{error}")
        succeeded = failure is None and not cleanup_errors
        lifecycle_core = {
            "schema_version": 1,
            "artifact_kind": SIDECAR_LIFECYCLE_KIND,
            "claim_status": (
                SIDECAR_CLAIM_STATUS
                if succeeded
                else "engineering_failed_nonpublication"
            ),
            "status": (
                SIDECAR_CLAIM_STATUS
                if succeeded
                else "engineering_failed_nonpublication"
            ),
            "publication_ready": False,
            "accepted_evidence_written": False,
            "lifecycle_id": self.lifecycle_id,
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "binding_set_identity_sha256": (
                None
                if materialized is None
                else materialized.index["identity"]["sha256"]
            ),
            "started_monotonic_ns": started_ns,
            "finished_monotonic_ns": finished_ns,
            "duration_ns": max(0, finished_ns - started_ns),
            "configured_worker_count": len(EXPECTED_KEYS),
            "attested_worker_count": len(self._worker_records),
            "workers": list(self._worker_records),
            "runtime_probes": {
                resource: dict(self._runtime_probes[resource])
                for resource in RESOURCES
                if resource in self._runtime_probes
            },
            "capabilities": (
                []
                if materialized is None
                else [
                    {
                        "branch": branch,
                        "resource": resource,
                        "capability": dict(materialized.capabilities[(branch, resource)]),
                        "capability_sha256": canonical_sha256(
                            materialized.capabilities[(branch, resource)]
                        ),
                    }
                    for branch in BRANCHES
                    for resource in RESOURCES
                ]
            ),
            "binding_index": (
                None if materialized is None else dict(materialized.index)
            ),
            "max_connections": self.max_connections,
            "max_requests_per_connection": self.max_requests_per_connection,
            "call_count": len(self._call_manifests),
            "call_identity_sha256": [
                manifest["identity"]["sha256"]
                for manifest in self._call_manifests
            ],
            "failure": (
                None
                if failure is None
                else {
                    "type": type(failure).__name__,
                    "message": str(failure)[:4096],
                }
            ),
            "cleanup_errors": cleanup_errors,
            "retired_socket_nodes": json.loads(
                canonical_json_bytes(self._retired_socket_nodes)
            ),
        }
        lifecycle = {
            **lifecycle_core,
            "identity": {
                "algorithm": "sha256",
                "sha256": canonical_sha256(lifecycle_core),
            },
        }
        evidence_failure: BaseException | None = None
        try:
            self.evidence.persist_lifecycle(lifecycle)
        except BaseException as error:
            evidence_failure = error
        if failure is not None:
            if cleanup_errors:
                raise SidecarError(
                    f"{failure}; sidecar cleanup failed: {cleanup_errors}"
                ) from failure
            if evidence_failure is not None:
                raise SidecarError(
                    f"{failure}; lifecycle evidence failed: {evidence_failure}"
                ) from failure
            if isinstance(failure, SidecarError):
                raise failure
            raise SidecarError(str(failure)) from failure
        if cleanup_errors:
            raise SidecarError(f"analytics sidecar cleanup failed: {cleanup_errors}")
        if evidence_failure is not None:
            raise SidecarError(
                f"analytics sidecar lifecycle evidence failed: {evidence_failure}"
            ) from evidence_failure
        return lifecycle


class GStreamerAnalyticsProductionService(GStreamerAnalyticsSidecar):
    """One-shot, long-lived guardian for the frozen publication benchmark run."""

    def __init__(
        self,
        *,
        execution_config: Mapping[str, Any],
        binding_set_dir: Path | str,
        policy_capability_manifest: Mapping[str, Any],
        preprocessing_contract: Mapping[str, Any],
        preprocessing_authority: Mapping[str, Any],
        production_runtime_expectations: Mapping[str, Any],
        runtime_dir: Path | str,
        front_socket: Path | str,
        evidence_root: Path | str,
        process_factory: WorkerProcessFactory,
        bridge_factory: BridgeFactory = _default_bridge_factory,
        max_connections: int,
        max_requests_per_connection: int,
        max_total_requests: int,
        startup_timeout_s: float = 120.0,
        shutdown_timeout_s: float = 10.0,
        monitor_interval_s: float = 0.1,
    ) -> None:
        _require(
            isinstance(preprocessing_contract, Mapping)
            and isinstance(preprocessing_authority, Mapping),
            "analytics production guardian requires a receipt-bound preprocessing contract",
        )
        super().__init__(
            execution_config=execution_config,
            binding_set_dir=binding_set_dir,
            policy_capability_manifest=policy_capability_manifest,
            preprocessing_contract=preprocessing_contract,
            preprocessing_authority=preprocessing_authority,
            production_runtime_expectations=production_runtime_expectations,
            runtime_dir=runtime_dir,
            front_socket=front_socket,
            evidence_root=evidence_root,
            process_factory=process_factory,
            bridge_factory=bridge_factory,
            max_connections=max_connections,
            max_requests_per_connection=max_requests_per_connection,
            max_total_requests=max_total_requests,
            service_mode=PRODUCTION_SERVICE_MODE,
            startup_timeout_s=startup_timeout_s,
            shutdown_timeout_s=shutdown_timeout_s,
            monitor_interval_s=monitor_interval_s,
        )

    def _execution_config_identity(self) -> str:
        identity = _exact(
            self.execution_config.get("identity"),
            {"algorithm", "sha256"},
            "analytics production execution config identity",
        )
        core = {
            key: value
            for key, value in self.execution_config.items()
            if key != "identity"
        }
        claimed = _sha(
            identity.get("sha256"),
            "analytics production execution config identity",
        )
        _require(
            identity.get("algorithm") == "sha256"
            and claimed == canonical_sha256(core),
            "analytics production execution config identity drifted",
        )
        return claimed

    def _build_authority(
        self, materialized: MaterializedBindingSet
    ) -> dict[str, Any]:
        _require(
            type(self.evidence) is ProductionLifecycleEvidenceSink
            and self._capacity is not None
            and self._production_front is not None
            and self._production_control is not None
            and self._production_started_ns is not None,
            "analytics production authority prerequisites are unavailable",
        )
        record_by_key = {
            (str(record["branch"]), str(record["resource"])): record
            for record in self._worker_records
        }
        _require(
            set(record_by_key) == EXPECTED_KEYS,
            "analytics production worker record coverage is not exact 8",
        )
        worker_images = {
            resource: str(
                _mapping(
                    self.execution_config["workers"][resource],
                    f"analytics production {resource} worker config",
                ).get("image_id")
            )
            for resource in RESOURCES
        }
        expectations = self.production_runtime_expectations
        _require(
            expectations is not None
            and self._execution_config_identity()
            == expectations["execution_config_identity_sha256"]
            and materialized.index["identity"]["sha256"]
            == expectations["binding_set_identity_sha256"]
            and materialized.index["bindings_identity_sha256"]
            == expectations["bindings_identity_sha256"]
            and worker_images == expectations["worker_image_ids"],
            "analytics production authority differs from external runtime pins",
        )
        peer_identities = [
            {
                "branch": branch,
                "resource": resource,
                "worker_image_id": worker_images[resource],
                "peer_identity": dict(
                    record_by_key[(branch, resource)]["peer_identity"]
                ),
                "peer_identity_sha256": record_by_key[(branch, resource)][
                    "peer_identity_sha256"
                ],
            }
            for branch in BRANCHES
            for resource in RESOURCES
        ]
        core: dict[str, Any] = {
            "schema_version": 1,
            "artifact_kind": PRODUCTION_SERVICE_AUTHORITY_KIND,
            "service_mode": PRODUCTION_SERVICE_MODE,
            "status": "live_operational_nonpublication",
            "publication_ready": False,
            "accepted_evidence_written": False,
            "lifecycle_id": self.lifecycle_id,
            "owner_process": _production_owner_process_identity(),
            "front_socket": _production_socket_pin(
                self._production_front.path
            ),
            "control_socket": _production_socket_pin(
                self._production_control.path
            ),
            "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
            "execution_config_identity_sha256": (
                self._execution_config_identity()
            ),
            "binding_set_identity_sha256": materialized.index["identity"][
                "sha256"
            ],
            "preprocessing_contract_authority": dict(
                self.preprocessing_authority or {}
            ),
            "worker_image_ids": worker_images,
            "capacity": dict(self._capacity),
            "worker_count": len(EXPECTED_KEYS),
            "attested_worker_count": len(peer_identities),
            "peer_identities": peer_identities,
            "started_monotonic_ns": self._production_started_ns,
            "readiness_artifact_path": str(self.evidence.authority_path),
            "lifecycle_artifact_path": str(self.evidence.lifecycle_path),
        }
        core["service_identity_sha256"] = canonical_sha256(
            _production_service_identity_material(core)
        )
        authority = {
            **core,
            "service_authority_sha256": canonical_sha256(core),
        }
        return validate_publication_sidecar_service_authority_v1(authority)

    def start(self) -> dict[str, Any]:
        _require(
            self._production_state == "new",
            "analytics production service is one-shot and was already started",
        )
        self._production_state = "starting"
        self._production_started_ns = time.monotonic_ns()
        try:
            self._verify_runtime_directory_custody()
            materialized = self._probe_and_load()
            self._production_materialized = materialized
            self._launch_workers(materialized)
            self._construct_bridge(materialized)
            self._assert_workers_live(phase="production front publication")
            front = _open_owned_listener(
                self.front_socket,
                backlog=min(128, self.max_connections),
                atomic_publish=True,
            )
            self._verify_runtime_directory_custody()
            self._production_front = front
            self._owned_sockets.append(front)
            control_path = self.runtime_dir / "production-guardian-control.sock"
            _require(
                control_path != self.front_socket,
                "analytics production control socket aliases the front socket",
            )
            control = _open_owned_listener(
                control_path,
                backlog=8,
                atomic_publish=True,
            )
            self._verify_runtime_directory_custody()
            self._production_control = control
            self._owned_sockets.append(control)
            authority = self._build_authority(materialized)
            self._production_authority = authority
            self._production_front_thread = threading.Thread(
                target=self._production_front_loop,
                args=(front,),
                name=f"vast-gst-production-front-{self.lifecycle_id[:12]}",
                daemon=False,
            )
            self._production_control_thread = threading.Thread(
                target=self._production_control_loop,
                args=(control,),
                name=f"vast-gst-production-control-{self.lifecycle_id[:12]}",
                daemon=False,
            )
            self._production_front_thread.start()
            self._production_control_thread.start()
            self._assert_production_internal_live()
            self.evidence.persist_authority(authority)
            self._production_state = "running"
            return _canonical_clone(authority)
        except BaseException as error:
            self._stop.set()
            self._close_front_connections()
            for thread in (
                self._production_front_thread,
                self._production_control_thread,
            ):
                if thread is not None:
                    thread.join(timeout=self.shutdown_timeout_s)
            cleanup_errors = self._shutdown()
            try:
                self._close_runtime_directory_custody()
            except BaseException as custody_error:
                cleanup_errors.append(
                    f"runtime_directory_custody_close:{custody_error}"
                )
            self._production_state = "failed"
            if cleanup_errors:
                raise SidecarError(
                    f"{error}; production startup cleanup failed: {cleanup_errors}"
                ) from error
            if isinstance(error, SidecarError):
                raise
            raise SidecarError(str(error)) from error

    @property
    def authority(self) -> dict[str, Any]:
        _require(
            self._production_authority is not None,
            "analytics production service authority is unavailable",
        )
        return _canonical_clone(self._production_authority)

    def assert_live(
        self, expected_authority: Mapping[str, Any]
    ) -> dict[str, Any]:
        _require(
            self._production_state == "running"
            and self._production_authority is not None,
            "analytics production service is not in the running state",
        )
        expected = validate_publication_sidecar_service_authority_v1(
            expected_authority
        )
        _require(
            expected == self._production_authority,
            "analytics production expected authority differs from the live service",
        )
        try:
            self._assert_production_internal_live()
        except BaseException as error:
            self._record_production_failure(error)
            raise
        checked = assert_publication_sidecar_service_authority_v1(
            expected,
            expected_front_socket=self.front_socket,
            expected_execution_config_identity_sha256=(
                self.production_runtime_expectations[
                    "execution_config_identity_sha256"
                ]
            ),
            expected_binding_set_identity_sha256=self.production_runtime_expectations[
                "binding_set_identity_sha256"
            ],
            expected_worker_image_ids=self.production_runtime_expectations[
                "worker_image_ids"
            ],
            expected_preprocessing_contract_authority=self.preprocessing_authority,
            expected_service_identity_sha256=expected[
                "service_identity_sha256"
            ],
            expected_policy_contract_sha256=self.production_runtime_expectations[
                "policy_contract_sha256"
            ],
        )
        return checked

    def wait_for_guardian_stop(self) -> None:
        _require(
            self._production_state == "running",
            "analytics production guardian is not running",
        )
        while not self._guardian_stop_requested.wait(self.monitor_interval_s):
            self._assert_production_internal_live()

    def _join_service_threads(self) -> list[str]:
        errors: list[str] = []
        deadline = time.monotonic() + self.shutdown_timeout_s
        for thread in (
            self._production_front_thread,
            self._production_control_thread,
        ):
            if thread is not None:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    errors.append(f"guardian_thread_survived:{thread.name}")
        with self._production_threads_lock:
            connection_threads = tuple(self._production_connection_threads)
        for thread in connection_threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        surviving = tuple(thread for thread in connection_threads if thread.is_alive())
        if surviving:
            self._close_front_connections()
            forced_deadline = time.monotonic() + self.shutdown_timeout_s
            for thread in surviving:
                thread.join(timeout=max(0.0, forced_deadline - time.monotonic()))
                if thread.is_alive():
                    errors.append(f"front_thread_survived:{thread.name}")
        return errors

    def stop(self) -> dict[str, Any]:
        if self._production_lifecycle is not None:
            _require(
                self._production_authority is not None
                and type(self.evidence) is ProductionLifecycleEvidenceSink,
                "analytics production cached lifecycle authority is unavailable",
            )
            persisted_lifecycle = _load_canonical_json_mapping(
                self.evidence.lifecycle_path,
                label="analytics production cached lifecycle cold reopen",
            )
            checked_lifecycle = validate_publication_sidecar_service_lifecycle_v1(
                persisted_lifecycle,
                expected_authority=self._production_authority,
            )
            _require(
                checked_lifecycle == self._production_lifecycle,
                "analytics production cached lifecycle cold reopen drifted",
            )
            return _canonical_clone(checked_lifecycle)
        _require(
            self._production_state == "running"
            and self._production_authority is not None
            and type(self.evidence) is ProductionLifecycleEvidenceSink,
            "analytics production service cannot be stopped before readiness",
        )
        self._production_state = "stopping"
        self._stop.set()
        thread_errors = self._join_service_threads()
        cleanup_errors = self._shutdown()
        try:
            self._verify_runtime_directory_custody()
            _require(
                not any(self.runtime_dir.iterdir()),
                "analytics production runtime directory was not restored empty",
            )
        except BaseException as error:
            cleanup_errors.append(f"runtime_directory_cleanup:{error}")
        try:
            self._close_runtime_directory_custody()
        except BaseException as error:
            cleanup_errors.append(f"runtime_directory_custody_close:{error}")
        finished_ns = time.monotonic_ns()
        with self._production_failure_lock:
            failure = self._production_failure
        all_cleanup_errors = [*thread_errors, *cleanup_errors]
        readiness_payload = self.evidence.authority_path.read_bytes()
        _require(
            readiness_payload
            == canonical_json_bytes(self._production_authority) + b"\n",
            "analytics production readiness artifact drifted before shutdown",
        )
        _require(
            self._production_counters is not None
            and self._production_started_ns is not None,
            "analytics production lifecycle counters are unavailable",
        )
        counter_snapshot = self._production_counters.snapshot()
        if counter_snapshot["connections_failed"]:
            all_cleanup_errors.append(
                "connection_failures:"
                f"{counter_snapshot['connections_failed']}"
            )
        if counter_snapshot["requests_failed"]:
            all_cleanup_errors.append(
                f"request_failures:{counter_snapshot['requests_failed']}"
            )
        with self._guardian_stop_attestation_lock:
            stop_attestation_value = (
                None
                if self._guardian_stop_attestation is None
                else _canonical_clone(self._guardian_stop_attestation)
            )
        guardian_stop_attestation: dict[str, Any] | None = None
        if stop_attestation_value is None:
            all_cleanup_errors.append("guardian_stop_attestation_missing")
        else:
            try:
                guardian_stop_attestation = (
                    _validate_guardian_stop_attestation_v1(
                        stop_attestation_value,
                        expected_authority=self._production_authority,
                    )
                )
                _require(
                    guardian_stop_attestation["accepted_monotonic_ns"]
                    <= finished_ns,
                    "analytics guardian stop acceptance exceeds shutdown",
                )
            except SidecarError:
                guardian_stop_attestation = None
                all_cleanup_errors.extend(
                    (
                        "guardian_stop_attestation_invalid",
                        "guardian_stop_attestation_missing",
                    )
                )
        succeeded = failure is None and not all_cleanup_errors
        lifecycle_core = {
            "schema_version": 1,
            "artifact_kind": PRODUCTION_SERVICE_LIFECYCLE_KIND,
            "service_mode": PRODUCTION_SERVICE_MODE,
            "status": (
                "clean_stop_nonpublication"
                if succeeded
                else "failed_stop_nonpublication"
            ),
            "publication_ready": False,
            "accepted_evidence_written": False,
            "lifecycle_id": self.lifecycle_id,
            "service_identity_sha256": self._production_authority[
                "service_identity_sha256"
            ],
            "service_authority_sha256": self._production_authority[
                "service_authority_sha256"
            ],
            "readiness_artifact": {
                "path": str(self.evidence.authority_path),
                "size_bytes": len(readiness_payload),
                "sha256": hashlib.sha256(readiness_payload).hexdigest(),
            },
            "front_socket": dict(self._production_authority["front_socket"]),
            "control_socket": dict(
                self._production_authority["control_socket"]
            ),
            "capacity": dict(self._production_authority["capacity"]),
            "started_monotonic_ns": self._production_started_ns,
            "finished_monotonic_ns": finished_ns,
            "duration_ns": max(0, finished_ns - self._production_started_ns),
            "guardian_stop_attestation": guardian_stop_attestation,
            "counters": counter_snapshot,
            "failure": (
                None
                if failure is None
                else {
                    "type": type(failure).__name__,
                    "message": str(failure)[:4096],
                }
            ),
            "cleanup_errors": all_cleanup_errors,
            "retired_socket_nodes": json.loads(
                canonical_json_bytes(self._retired_socket_nodes)
            ),
            "evidence_role": "operational_non_authorizing_lifecycle",
        }
        lifecycle = {
            **lifecycle_core,
            "identity": {
                "algorithm": "sha256",
                "sha256": canonical_sha256(lifecycle_core),
            },
        }
        self.evidence.persist_lifecycle(lifecycle)
        persisted_lifecycle = _load_canonical_json_mapping(
            self.evidence.lifecycle_path,
            label="analytics production service lifecycle cold reopen",
        )
        checked_lifecycle = validate_publication_sidecar_service_lifecycle_v1(
            persisted_lifecycle,
            expected_authority=self._production_authority,
        )
        _require(
            checked_lifecycle == lifecycle,
            "analytics production service lifecycle cold reopen drifted",
        )
        self._production_lifecycle = checked_lifecycle
        self._production_state = "stopped" if succeeded else "failed"
        return _canonical_clone(checked_lifecycle)

    def __enter__(self) -> "GStreamerAnalyticsProductionService":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_type, exc_value, traceback
        self.stop()


def build_sidecar_plan(
    *,
    execution_config: Mapping[str, Any],
    project_root: Path | str,
    binding_set_dir: Path | str,
    runtime_dir: Path | str,
    front_socket: Path | str,
    evidence_root: Path | str,
    max_connections: int,
    max_requests_per_connection: int,
) -> dict[str, Any]:
    workers = _exact(
        execution_config.get("workers"),
        {"cpu", "gpu"},
        "analytics sidecar plan workers",
    )
    root = _absolute(project_root)
    bindings = _absolute(binding_set_dir)
    runtime = _absolute(runtime_dir)
    front = _absolute(front_socket)
    evidence = _absolute(evidence_root)
    _require(
        front.parent == runtime,
        "analytics sidecar plan front socket escaped runtime directory",
    )
    _require(
        type(max_connections) is int and 1 <= max_connections <= 1_000_000,
        "analytics sidecar plan max_connections is invalid",
    )
    _require(
        type(max_requests_per_connection) is int
        and 1 <= max_requests_per_connection <= 1_000_000,
        "analytics sidecar plan max requests is invalid",
    )
    records: list[dict[str, Any]] = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            worker = _mapping(workers[resource], f"{resource} worker plan")
            records.append(
                {
                    "branch": branch,
                    "resource": resource,
                    "engine": ENGINE_BY_RESOURCE[resource],
                    "image": worker.get("image"),
                    "image_id": worker.get("image_id"),
                    "entrypoint": worker.get("entrypoint"),
                    "requires_nvidia_runtime": resource == "gpu",
                    "network": "none",
                    "binding": (
                        f"/run/vast/bindings/"
                        f"{branch}.{ENGINE_BY_RESOURCE[resource]}.json"
                    ),
                    "socket": f"/run/vast/analytics/worker-{branch}-{resource}.sock",
                }
            )
    core = {
        "schema_version": 1,
        "artifact_kind": "vast_gstreamer_analytics_sidecar_plan",
        "claim_status": "engineering_plan_nonpublication",
        "publication_ready": False,
        "accepted_evidence_written": False,
        "project_root": str(root),
        "binding_set_dir": str(bindings),
        "runtime_dir": str(runtime),
        "front_socket": str(front),
        "evidence_root": str(evidence),
        "worker_count": len(records),
        "workers": records,
        "max_connections": max_connections,
        "max_requests_per_connection": max_requests_per_connection,
    }
    return {
        **core,
        "identity": {"algorithm": "sha256", "sha256": canonical_sha256(core)},
    }


def _load_yaml_or_json(path: Path | str, *, label: str) -> dict[str, Any]:
    resolved = _absolute(path)
    _require(
        resolved.is_file() and not _is_reparse(resolved),
        f"{label} is missing or unsafe",
    )
    try:
        text = resolved.read_text(encoding="utf-8")
        if resolved.suffix.lower() == ".json":
            value = json.loads(text)
        else:
            import yaml

            value = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SidecarError(f"cannot read {label}: {error}") from error
    _require(isinstance(value, dict), f"{label} must be a mapping")
    return value


def load_execution_config(path: Path | str) -> dict[str, Any]:
    """Load the exact execution-layer subset without publication dependencies."""

    raw = _exact(
        _load_yaml_or_json(path, label="analytics execution layer config"),
        {
            "schema_version",
            "artifact_kind",
            "config_id",
            "protocol_identity_sha256",
            "model_parity_manifest",
            "transport",
            "workers",
        },
        "analytics execution layer config",
    )
    _require(
        raw["schema_version"] == 1
        and raw["artifact_kind"] == "vast_analytics_execution_layer_config",
        "analytics execution layer config header drifted",
    )
    config_id = _safe_id(raw["config_id"], "analytics execution config_id")
    _require(
        raw["protocol_identity_sha256"] == PROTOCOL_IDENTITY_SHA256,
        "analytics execution config protocol identity mismatch",
    )
    manifest = str(raw["model_parity_manifest"] or "")
    manifest_path = Path(manifest)
    _require(
        manifest
        and not manifest_path.is_absolute()
        and ".." not in manifest_path.parts
        and "\n" not in manifest
        and "\r" not in manifest,
        "analytics execution model-parity path is unsafe",
    )
    transport = _exact(
        raw["transport"],
        {
            "kind",
            "max_control_bytes",
            "max_tensor_bytes",
            "max_inflight_requests_per_worker",
        },
        "analytics execution transport",
    )
    _require(
        transport["kind"] == TRANSPORT_KIND
        and transport["max_control_bytes"] == MAX_CONTROL_BYTES
        and transport["max_tensor_bytes"] == MAX_TENSOR_BYTES
        and transport["max_inflight_requests_per_worker"] == 1,
        "analytics execution transport contract drifted",
    )
    workers = _exact(
        raw["workers"], {"cpu", "gpu"}, "analytics execution workers"
    )
    normalized_workers: dict[str, dict[str, Any]] = {}
    worker_fields = {
        "engine",
        "base_image",
        "base_image_id",
        "image",
        "image_id",
        "worker_implementation_sha256",
        "entrypoint",
        "requires_nvidia_runtime",
    }
    for resource in RESOURCES:
        worker = _exact(
            workers[resource],
            worker_fields,
            f"analytics execution {resource} worker",
        )
        _require(
            worker["engine"] == ENGINE_BY_RESOURCE[resource],
            f"analytics execution {resource} worker engine mismatch",
        )
        _require(
            worker["requires_nvidia_runtime"] is (resource == "gpu"),
            f"analytics execution {resource} NVIDIA runtime flag drifted",
        )
        _require(
            valid_image_id(worker["base_image_id"])
            and valid_image_id(worker["image_id"]),
            f"analytics execution {resource} image identities are not frozen",
        )
        image = str(worker["image"] or "")
        base_image = str(worker["base_image"] or "")
        entrypoint = str(worker["entrypoint"] or "")
        _require(
            image
            and base_image
            and all(
                "\n" not in value and "\r" not in value
                for value in (image, base_image)
            ),
            f"analytics execution {resource} image references are invalid",
        )
        _require(
            entrypoint.startswith("/")
            and "\n" not in entrypoint
            and "\r" not in entrypoint,
            f"analytics execution {resource} entrypoint is invalid",
        )
        normalized_workers[resource] = {
            **dict(worker),
            "worker_implementation_sha256": _sha(
                worker["worker_implementation_sha256"],
                f"analytics execution {resource} implementation SHA-256",
            ),
            "base_image": base_image,
            "image": image,
            "entrypoint": entrypoint,
        }
    normalized = {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_layer_config",
        "config_id": config_id,
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "model_parity_manifest": manifest,
        "transport": dict(transport),
        "workers": normalized_workers,
    }
    normalized["identity"] = {
        "algorithm": "sha256",
        "sha256": canonical_sha256(normalized),
    }
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Own the bounded engineering GStreamer analytics sidecar lifecycle."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
    )
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--binding-set", type=Path)
    parser.add_argument(
        "--policy-capability-manifest", type=Path
    )
    parser.add_argument("--preprocessing-contract", type=Path)
    parser.add_argument("--preprocessing-contract-receipt", type=Path)
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--front-socket", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--max-connections", type=int)
    parser.add_argument(
        "--max-requests-per-connection", type=int
    )
    parser.add_argument("--max-total-requests", type=int)
    parser.add_argument("--startup-timeout-seconds", type=float)
    parser.add_argument("--shutdown-timeout-seconds", type=float)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--production-guardian", action="store_true")
    mode.add_argument("--production-status-authority", type=Path)
    mode.add_argument("--production-stop-authority", type=Path)
    parser.add_argument("--control-timeout-seconds", type=float)
    return parser


def _validate_cli_mode_contract(args: argparse.Namespace) -> None:
    lifecycle_fields = (
        "config",
        "project_root",
        "binding_set",
        "policy_capability_manifest",
        "preprocessing_contract",
        "preprocessing_contract_receipt",
        "runtime_dir",
        "front_socket",
        "evidence_root",
        "max_connections",
        "max_requests_per_connection",
        "max_total_requests",
        "startup_timeout_seconds",
        "shutdown_timeout_seconds",
    )
    control_mode = (
        args.production_status_authority is not None
        or args.production_stop_authority is not None
    )
    if control_mode:
        mode_label = (
            "production status"
            if args.production_status_authority is not None
            else "production stop"
        )
        incompatible = [
            field for field in lifecycle_fields if getattr(args, field) is not None
        ]
        _require(
            not incompatible,
            f"{mode_label} mode has incompatible lifecycle arguments: {incompatible}",
        )
        return
    _require(
        args.control_timeout_seconds is None,
        "lifecycle mode has incompatible --control-timeout-seconds",
    )
    if args.plan_only:
        incompatible = [
            field
            for field in (
                "preprocessing_contract",
                "preprocessing_contract_receipt",
                "max_total_requests",
                "startup_timeout_seconds",
                "shutdown_timeout_seconds",
            )
            if getattr(args, field) is not None
        ]
        _require(
            not incompatible,
            f"plan mode has incompatible runtime arguments: {incompatible}",
        )
    elif args.production_guardian:
        _require(
            args.preprocessing_contract is not None
            and args.preprocessing_contract_receipt is not None,
            "production guardian requires --preprocessing-contract and --preprocessing-contract-receipt",
        )
    else:
        _require(
            args.preprocessing_contract_receipt is None
            and args.max_total_requests is None,
            "engineering sidecar has incompatible production-only arguments",
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _validate_cli_mode_contract(args)
        control_timeout_s = (
            60.0
            if args.control_timeout_seconds is None
            else args.control_timeout_seconds
        )
        if args.production_status_authority is not None:
            authority = _load_canonical_json_mapping(
                args.production_status_authority,
                label="analytics production service authority",
            )
            observed = query_publication_sidecar_guardian_v1(
                authority,
                timeout_s=control_timeout_s,
            )
            print(
                (canonical_json_bytes(observed) + b"\n").decode("ascii"),
                end="",
            )
            return 0
        if args.production_stop_authority is not None:
            authority = _load_canonical_json_mapping(
                args.production_stop_authority,
                label="analytics production service authority",
            )
            acknowledgement = request_publication_sidecar_guardian_stop_v1(
                authority,
                timeout_s=min(60.0, control_timeout_s),
            )
            lifecycle = wait_publication_sidecar_guardian_stop_v1(
                authority,
                timeout_s=control_timeout_s,
            )
            lifecycle = _assert_guardian_stop_ack_matches_lifecycle_v1(
                acknowledgement,
                lifecycle,
                expected_authority=authority,
            )
            print(
                (canonical_json_bytes(lifecycle) + b"\n").decode("ascii"),
                end="",
            )
            return (
                0
                if lifecycle["status"] == "clean_stop_nonpublication"
                else 78
            )
        _require(
            args.binding_set is not None
            and args.policy_capability_manifest is not None
            and args.runtime_dir is not None
            and args.evidence_root is not None
            and type(args.max_connections) is int
            and type(args.max_requests_per_connection) is int,
            "sidecar lifecycle inputs and bounded counts are required",
        )
        default_project_root = Path(__file__).resolve().parents[1]
        project_root = args.project_root or default_project_root
        config_path = args.config or (
            default_project_root / "configs" / "analytics_execution_layer.yaml"
        )
        startup_timeout_s = (
            120.0
            if args.startup_timeout_seconds is None
            else args.startup_timeout_seconds
        )
        shutdown_timeout_s = (
            10.0
            if args.shutdown_timeout_seconds is None
            else args.shutdown_timeout_seconds
        )
        config = load_execution_config(config_path)
        runtime_dir = _absolute(args.runtime_dir)
        front_socket = _absolute(
            args.front_socket or runtime_dir / "analytics-execution.sock"
        )
        if args.plan_only:
            _require(
                args.max_total_requests is None,
                "engineering plan cannot claim production total requests",
            )
            plan = build_sidecar_plan(
                execution_config=config,
                project_root=project_root,
                binding_set_dir=args.binding_set,
                runtime_dir=runtime_dir,
                front_socket=front_socket,
                evidence_root=args.evidence_root,
                max_connections=args.max_connections,
                max_requests_per_connection=args.max_requests_per_connection,
            )
            print(
                (canonical_json_bytes(plan) + b"\n").decode("ascii"),
                end="",
            )
            return 0
        policy_capability_manifest = _load_yaml_or_json(
            args.policy_capability_manifest,
            label="analytics policy capability manifest",
        )
        preprocessing_contract: Mapping[str, Any] | None
        preprocessing_authority: Mapping[str, Any] | None = None
        production_runtime_expectations: Mapping[str, Any] | None = None
        if args.production_guardian:
            try:
                preprocessing_receipt_document = _load_canonical_json_mapping(
                    args.preprocessing_contract_receipt,
                    label="analytics preprocessing materialization receipt",
                )
                if (
                    preprocessing_receipt_document.get("artifact_kind")
                    == ACCEPTED_POLICY_PREPROCESSING_RECEIPT_KIND
                ):
                    loaded_preprocessing = (
                        load_accepted_policy_guardian_preprocessing_contract_v1(
                            project_root=project_root,
                            preprocessing_contract_path=args.preprocessing_contract,
                            materialization_receipt_path=(
                                args.preprocessing_contract_receipt
                            ),
                            accepted_policy_capability_manifest_path=(
                                args.policy_capability_manifest
                            ),
                        )
                    )
                else:
                    loaded_preprocessing = load_guardian_preprocessing_contract_v1(
                        project_root=project_root,
                        preprocessing_contract_path=args.preprocessing_contract,
                        materialization_receipt_path=(
                            args.preprocessing_contract_receipt
                        ),
                        candidate_manifest_path=args.policy_capability_manifest,
                    )
                production_runtime_expectations = (
                    runtime_expectations_from_preprocessing_receipt_v1(
                        _mapping(
                            loaded_preprocessing.get("receipt"),
                            "verified guardian preprocessing receipt",
                        )
                    )
                )
            except (
                GuardianPreprocessingContractV1Error,
                AcceptedPolicyGuardianPreprocessingContractV1Error,
                GuardianRuntimeExpectationsV1Error,
            ) as error:
                raise SidecarError(
                    f"production guardian preprocessing receipt validation failed: {error}"
                ) from error
            preprocessing_contract = _mapping(
                loaded_preprocessing.get("preprocessing_contract"),
                "verified guardian preprocessing contract",
            )
            preprocessing_authority = _mapping(
                loaded_preprocessing.get("authority"),
                "verified guardian preprocessing authority",
            )
        else:
            preprocessing_contract = (
                None
                if args.preprocessing_contract is None
                else _load_yaml_or_json(
                    args.preprocessing_contract,
                    label="analytics preprocessing contract",
                )
            )
        if runtime_dir.exists():
            _require(
                runtime_dir.is_dir()
                and not _is_reparse(runtime_dir)
                and stat.S_IMODE(runtime_dir.stat().st_mode) == 0o700
                and runtime_dir.stat().st_uid == os.getuid()
                and runtime_dir.stat().st_gid == os.getgid()
                and not any(runtime_dir.iterdir()),
                "analytics sidecar existing runtime directory custody drifted",
            )
        else:
            runtime_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        runtime_dir = _canonical_directory(
            runtime_dir,
            label="analytics sidecar CLI runtime directory",
            reject_cwd_or_parent=True,
        )
        factory = DockerWorkerProcessFactory(
            project_root=project_root,
            binding_set_root=args.binding_set,
            runtime_dir=runtime_dir,
        )
        owner_values: dict[str, Any] = {
            "execution_config": config,
            "binding_set_dir": args.binding_set,
            "policy_capability_manifest": policy_capability_manifest,
            "preprocessing_contract": preprocessing_contract,
            "preprocessing_authority": preprocessing_authority,
            "production_runtime_expectations": production_runtime_expectations,
            "runtime_dir": runtime_dir,
            "front_socket": front_socket,
            "evidence_root": args.evidence_root,
            "process_factory": factory,
            "bridge_factory": _default_bridge_factory,
            "max_connections": args.max_connections,
            "max_requests_per_connection": args.max_requests_per_connection,
            "startup_timeout_s": startup_timeout_s,
            "shutdown_timeout_s": shutdown_timeout_s,
        }
        if args.production_guardian:
            _require(
                type(args.max_total_requests) is int,
                "production guardian max_total_requests is required",
            )
            owner_values["max_total_requests"] = args.max_total_requests
        else:
            _require(
                args.max_total_requests is None,
                "engineering sidecar cannot claim production total requests",
            )
        if args.production_guardian:
            owner = GStreamerAnalyticsProductionService(**owner_values)
            _require(
                type(owner) is GStreamerAnalyticsProductionService,
                "analytics production guardian owner type drifted",
            )
            authority = owner.start()
            print(
                (canonical_json_bytes(authority) + b"\n").decode("ascii"),
                end="",
                flush=True,
            )
            previous_handlers: dict[int, Any] = {}

            def request_guardian_stop(
                signum: int, frame: Any
            ) -> None:
                del signum, frame
                owner._guardian_stop_requested.set()

            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_guardian_stop)
            wait_failure: BaseException | None = None
            try:
                owner.wait_for_guardian_stop()
            except BaseException as error:
                wait_failure = error
            finally:
                for signum, handler in previous_handlers.items():
                    signal.signal(signum, handler)
            lifecycle = owner.stop()
            print(
                (canonical_json_bytes(lifecycle) + b"\n").decode("ascii"),
                end="",
                flush=True,
            )
            if wait_failure is not None:
                raise SidecarError(
                    f"analytics production guardian failed: {wait_failure}"
                ) from wait_failure
            return (
                0
                if lifecycle["status"] == "clean_stop_nonpublication"
                else 78
            )
        owner = GStreamerAnalyticsSidecar(
            execution_config=config,
            binding_set_dir=args.binding_set,
            policy_capability_manifest=policy_capability_manifest,
            preprocessing_contract=preprocessing_contract,
            preprocessing_authority=preprocessing_authority,
            runtime_dir=runtime_dir,
            front_socket=front_socket,
            evidence_root=args.evidence_root,
            process_factory=factory,
            max_connections=args.max_connections,
            max_requests_per_connection=args.max_requests_per_connection,
            startup_timeout_s=startup_timeout_s,
            shutdown_timeout_s=shutdown_timeout_s,
        )
        result = owner.run()
        print(
            (canonical_json_bytes(result) + b"\n").decode("ascii"),
            end="",
        )
        return 0
    except (SidecarError, ProtocolError) as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_kind": "vast_gstreamer_analytics_sidecar_error",
                    "status": "engineering_failed_nonpublication",
                    "publication_ready": False,
                    "accepted_evidence_written": False,
                    "message": str(error),
                },
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 78


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DockerWorkerProcessFactory",
    "GStreamerAnalyticsSidecar",
    "GStreamerAnalyticsProductionService",
    "MaterializedBindingSet",
    "PRODUCTION_MAX_CONNECTIONS_MINIMUM",
    "PRODUCTION_MAX_REQUESTS_PER_CONNECTION_MINIMUM",
    "PRODUCTION_MAX_TOTAL_REQUESTS_MINIMUM",
    "PRODUCTION_RETIRED_SOCKET_NODE_COUNT",
    "SidecarError",
    "WorkerLaunchSpec",
    "assert_publication_sidecar_service_authority_identity_v1",
    "assert_publication_sidecar_service_authority_v1",
    "build_parser",
    "build_sidecar_plan",
    "load_materialized_binding_set",
    "load_execution_config",
    "main",
    "query_publication_sidecar_guardian_v1",
    "request_publication_sidecar_guardian_stop_v1",
    "validate_publication_sidecar_service_authority_v1",
    "validate_publication_sidecar_service_lifecycle_v1",
    "wait_publication_sidecar_guardian_stop_v1",
]
