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
import hashlib
import json
import os
import re
import socket
import stat
import struct
import subprocess
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
    PROTOCOL_IDENTITY_SHA256,
    ProtocolError,
    TRANSPORT_KIND,
    canonical_json_bytes,
    canonical_sha256,
    close_fds,
    receive_packet,
    send_packet,
    valid_image_id,
    verify_sealed_memfd,
)
from analytics_execution_worker import validate_runtime_probe


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
    bind_path = path
    hidden_path: Path | None = None
    published_identity: tuple[int, int, int] | None = None
    if atomic_publish:
        _require(
            os.name == "posix",
            "atomic analytics sidecar socket publication requires POSIX",
        )
        hidden_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
        _require(
            len(os.fsencode(hidden_path)) < 108
            and not os.path.lexists(hidden_path),
            "hidden analytics sidecar socket path is invalid or occupied",
        )
        bind_path = hidden_path
    try:
        listener.bind(str(bind_path))
        listener.listen(backlog)
        metadata = bind_path.lstat()
        _require(
            stat.S_ISSOCK(metadata.st_mode),
            "analytics sidecar listener did not create a socket node",
        )
        if hidden_path is not None:
            hidden_identity = _stat_identity(hidden_path)
            try:
                os.link(hidden_path, path, follow_symlinks=False)
            except FileExistsError as error:
                raise SidecarError(
                    f"analytics sidecar socket already exists: {path}"
                ) from error
            published_identity = hidden_identity
            _require(
                _stat_identity(path) == published_identity,
                "atomically published analytics socket identity mismatch",
            )
            _require(
                _stat_identity(hidden_path) == published_identity
                and stat.S_ISSOCK(hidden_path.lstat().st_mode),
                "hidden analytics socket identity changed before cleanup",
            )
            hidden_path.unlink()
            hidden_path = None
        return _OwnedSocket(path, _stat_identity(path), listener)
    except BaseException:
        listener.close()
        if published_identity is not None and os.path.lexists(path):
            published_node_is_owned = (
                not _is_reparse(path)
                and stat.S_ISSOCK(path.lstat().st_mode)
                and _stat_identity(path) == published_identity
            )
            if published_node_is_owned:
                path.unlink()
        if hidden_path is not None and os.path.lexists(hidden_path):
            _require(
                not _is_reparse(hidden_path)
                and stat.S_ISSOCK(hidden_path.lstat().st_mode),
                "hidden analytics socket was replaced before cleanup",
            )
            hidden_path.unlink()
        raise


def _close_owned_socket(value: _OwnedSocket) -> None:
    if value.listener is not None:
        try:
            value.listener.close()
        except OSError:
            pass
        value.listener = None
    if not os.path.lexists(value.path):
        return
    _require(
        not _is_reparse(value.path),
        f"owned analytics socket was replaced by a reparse point: {value.path.name}",
    )
    _require(
        _stat_identity(value.path) == value.identity,
        f"owned analytics socket identity changed: {value.path.name}",
    )
    _require(
        stat.S_ISSOCK(value.path.lstat().st_mode),
        f"owned analytics socket was replaced by a non-socket: {value.path.name}",
    )
    value.path.unlink()


def _peer_pid(connection: socket.socket) -> int:
    _require(
        hasattr(socket, "SO_PEERCRED"),
        "analytics sidecar requires Linux SO_PEERCRED",
    )
    try:
        credentials = connection.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            struct.calcsize("3i"),
        )
        pid, uid, gid = struct.unpack("3i", credentials)
    except (OSError, struct.error) as error:
        raise SidecarError(f"cannot read analytics worker peer credentials: {error}") from error
    _require(
        pid > 0 and uid >= 0 and gid >= 0,
        "analytics worker peer credentials are invalid",
    )
    return int(pid)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(dict(value)) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(
        getattr(os, "O_CLOEXEC", 0)
    )
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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_CLOEXEC", 0)),
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


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
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


class DockerWorkerHandle:
    """Foreground `docker run` handle with host PID attestation via inspect."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        container_name: str,
        command_runner: Callable[..., subprocess.CompletedProcess[str]],
    ) -> None:
        self._process = process
        self.container_name = container_name
        self.pid = int(process.pid)
        self._command_runner = command_runner

    def expected_peer_pid(self, timeout_s: float) -> int:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.poll() is not None:
                raise SidecarError(
                    f"analytics worker container {self.container_name} exited during startup"
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
        try:
            process = self._popen_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise SidecarError(
                f"cannot start analytics Docker worker {spec.branch}/{spec.resource}: {error}"
            ) from error
        return DockerWorkerHandle(
            process,
            container_name=container_name,
            command_runner=self._command_runner,
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
        runtime_dir: Path | str,
        front_socket: Path | str,
        evidence_root: Path | str,
        process_factory: WorkerProcessFactory,
        bridge_factory: BridgeFactory = _default_bridge_factory,
        max_connections: int,
        max_requests_per_connection: int,
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
        self.runtime_dir = _canonical_directory(
            runtime_dir,
            label="analytics sidecar runtime directory",
            reject_cwd_or_parent=True,
        )
        self.front_socket = _absolute(front_socket)
        _require(
            self.front_socket.parent == self.runtime_dir,
            "analytics sidecar front socket escaped its runtime directory",
        )
        self.evidence = EngineeringEvidenceSink(evidence_root)
        self.process_factory = process_factory
        self.bridge_factory = bridge_factory
        _require(
            type(max_connections) is int and 1 <= max_connections <= 1_000_000,
            "analytics sidecar max_connections is invalid",
        )
        _require(
            type(max_requests_per_connection) is int
            and 1 <= max_requests_per_connection <= 1_000_000,
            "analytics sidecar max_requests_per_connection is invalid",
        )
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
        self.max_connections = max_connections
        self.max_requests_per_connection = max_requests_per_connection
        self.startup_timeout_s = float(startup_timeout_s)
        self.shutdown_timeout_s = float(shutdown_timeout_s)
        self.monitor_interval_s = float(monitor_interval_s)
        self.lifecycle_id = uuid.uuid4().hex
        self._owned_sockets: list[_OwnedSocket] = []
        self._handles: dict[tuple[str, str], WorkerHandle] = {}
        self._connections: dict[tuple[str, str], socket.socket] = {}
        self._bridge: BridgeLike | None = None
        self._call_manifests: list[Mapping[str, Any]] = []
        self._worker_records: list[dict[str, Any]] = []
        self._runtime_probes: dict[str, Mapping[str, Any]] = {}
        self._stop = threading.Event()
        self._front_connections: set[socket.socket] = set()
        self._front_connections_lock = threading.Lock()

    def _worker_socket_path(self, branch: str, resource: str) -> Path:
        return self.runtime_dir / f"worker-{branch}-{resource}.sock"

    def _assert_workers_live(self, *, phase: str) -> None:
        for key, handle in self._handles.items():
            status = handle.poll()
            if status is not None:
                raise SidecarError(
                    f"analytics worker {key[0]}/{key[1]} exited during {phase}: {status}"
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
        return load_materialized_binding_set(
            self.binding_set_dir,
            execution_config=self.execution_config,
            runtime_probes=probes,
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
            self.max_connections * self.max_requests_per_connection
        )
        try:
            for branch in BRANCHES:
                for resource in RESOURCES:
                    key = (branch, resource)
                    path = self._worker_socket_path(branch, resource)
                    owned = _open_owned_listener(path, backlog=1)
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
                    observed_peer_pid = _peer_pid(connection)
                    if observed_peer_pid != expected_peer_pid:
                        connection.close()
                        raise SidecarError(
                            f"analytics worker {branch}/{resource} peer PID mismatch: "
                            f"expected {expected_peer_pid}, observed {observed_peer_pid}"
                        )
                    self._connections[key] = connection
                    self._worker_records.append(
                        {
                            "branch": branch,
                            "resource": resource,
                            "engine": ENGINE_BY_RESOURCE[resource],
                            "supervisor_pid": handle.pid,
                            "peer_pid": observed_peer_pid,
                            "binding_path": materialized.binding_paths[key].name,
                            "binding_sha256": hashlib.sha256(
                                canonical_json_bytes(materialized.bindings[key])
                            ).hexdigest(),
                            "capability_sha256": canonical_sha256(
                                materialized.capabilities[key]
                            ),
                        }
                    )
                    _close_owned_socket(owned)
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
        self._assert_workers_live(phase="post-hello attestation")

    def _serve_connection(
        self,
        endpoint: socket.socket,
        errors: list[BaseException],
        errors_lock: threading.Lock,
    ) -> None:
        try:
            for _ in range(self.max_requests_per_connection):
                message, descriptors = receive_packet(endpoint, expected_fds=1)
                try:
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
                    _require(
                        self._bridge is not None,
                        "analytics sidecar bridge is unavailable",
                    )
                    try:
                        response = dict(self._bridge.execute(message, payload))
                    except BaseException as execution_error:
                        manifest = self.evidence.persist_call(
                            request=message,
                            response={},
                            payload=payload,
                            lifecycle_id=self.lifecycle_id,
                            failure=execution_error,
                        )
                        self._call_manifests.append(manifest)
                        raise
                    manifest = self.evidence.persist_call(
                        request=message,
                        response=response,
                        payload=payload,
                        lifecycle_id=self.lifecycle_id,
                    )
                    self._call_manifests.append(manifest)
                    send_packet(endpoint, response)
                finally:
                    close_fds(descriptors)
        except BaseException as error:
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
        self._stop.set()
        self._close_front_connections()
        for owned in tuple(reversed(self._owned_sockets)):
            try:
                _close_owned_socket(owned)
            except BaseException as error:
                errors.append(f"socket_cleanup:{owned.path.name}:{error}")
            finally:
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
        return errors

    def run(self) -> dict[str, Any]:
        started_ns = time.monotonic_ns()
        failure: BaseException | None = None
        front: _OwnedSocket | None = None
        materialized: MaterializedBindingSet | None = None
        try:
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
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Own the bounded engineering GStreamer analytics sidecar lifecycle."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=project_root / "configs" / "analytics_execution_layer.yaml",
    )
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument("--binding-set", type=Path, required=True)
    parser.add_argument(
        "--policy-capability-manifest", type=Path, required=True
    )
    parser.add_argument("--preprocessing-contract", type=Path)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--front-socket", type=Path)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--max-connections", type=int, required=True)
    parser.add_argument(
        "--max-requests-per-connection", type=int, required=True
    )
    parser.add_argument("--startup-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--shutdown-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_execution_config(args.config)
        runtime_dir = _absolute(args.runtime_dir)
        front_socket = _absolute(
            args.front_socket or runtime_dir / "analytics-execution.sock"
        )
        plan = build_sidecar_plan(
            execution_config=config,
            project_root=args.project_root,
            binding_set_dir=args.binding_set,
            runtime_dir=runtime_dir,
            front_socket=front_socket,
            evidence_root=args.evidence_root,
            max_connections=args.max_connections,
            max_requests_per_connection=args.max_requests_per_connection,
        )
        if args.plan_only:
            print(
                (canonical_json_bytes(plan) + b"\n").decode("ascii"),
                end="",
            )
            return 0
        runtime_dir.mkdir(parents=False, exist_ok=False)
        runtime_dir = _canonical_directory(
            runtime_dir,
            label="analytics sidecar CLI runtime directory",
            reject_cwd_or_parent=True,
        )
        factory = DockerWorkerProcessFactory(
            project_root=args.project_root,
            binding_set_root=args.binding_set,
            runtime_dir=runtime_dir,
        )
        owner = GStreamerAnalyticsSidecar(
            execution_config=config,
            binding_set_dir=args.binding_set,
            policy_capability_manifest=_load_yaml_or_json(
                args.policy_capability_manifest,
                label="analytics policy capability manifest",
            ),
            preprocessing_contract=(
                None
                if args.preprocessing_contract is None
                else _load_yaml_or_json(
                    args.preprocessing_contract,
                    label="analytics preprocessing contract",
                )
            ),
            runtime_dir=runtime_dir,
            front_socket=front_socket,
            evidence_root=args.evidence_root,
            process_factory=factory,
            max_connections=args.max_connections,
            max_requests_per_connection=args.max_requests_per_connection,
            startup_timeout_s=args.startup_timeout_seconds,
            shutdown_timeout_s=args.shutdown_timeout_seconds,
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
    "MaterializedBindingSet",
    "SidecarError",
    "WorkerLaunchSpec",
    "build_parser",
    "build_sidecar_plan",
    "load_materialized_binding_set",
    "load_execution_config",
    "main",
]
