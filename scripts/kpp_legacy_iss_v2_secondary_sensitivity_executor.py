#!/usr/bin/env python3
"""Execute the authorized KPP v2 TensorRT pilot without publication authority.

The module is intentionally separate from publication materializers.  Its
Docker lifecycle is local-daemon-only, pull-free, and bound to the planner's
immutable TensorRT image/GPU/model identities.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
import re
import selectors
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from kpp_legacy_iss_v2_secondary_sensitivity_pilot import (
    BRANCHES,
    CODECS,
    PLAN_ARTIFACT_KIND,
    TENSORRT_ENGINE_PINS,
    TENSORRT_ENTRYPOINT,
    TENSORRT_BASE_IMAGE_ID,
    TENSORRT_GPU_UUID,
    TENSORRT_IMAGE_ID,
    TENSOR_SEGMENT_BYTES,
    build_pilot_plan,
)


DOCKER_CLI = "/usr/bin/docker"
DOCKER_HOST_ARG = "--host=unix:///var/run/docker.sock"
CONTAINER_UID = 1000
CONTAINER_GID = 1000
CONTAINER_MEMORY_BYTES = 4 * 1024 * 1024 * 1024
CONTAINER_NANO_CPUS = 2_000_000_000
CONTAINER_PIDS_LIMIT = 128
OWNER_LABEL = "org.vast.kpp_nonpublication.owner"
OWNER_VALUE = "kpp_legacy_iss_v2_secondary_sensitivity_executor_v1"
RUN_LABEL = "org.vast.kpp_nonpublication.run_identity_sha256"
BRANCH_LABEL = "org.vast.kpp_nonpublication.branch"
_DOCKER_DESKTOP_WSL_DISTRO_LABEL = "desktop.docker.io/wsl-distro"
_DOCKER_DESKTOP_WSL_DISTRO_VALUE = "Ubuntu"
IPC_RUNTIME_PARENT = Path("/tmp")
_IPC_RUNTIME_NAME_PREFIX = "vk2i-"
_IPC_RUNTIME_PATH_DOMAIN = b"VAST:kpp-v2-nonpublication-ipc-runtime:v1\0"
_IPC_CAPABILITY_SOCKET_NAME = ".capability.sock"
_AF_UNIX_PATH_MAX_BYTES = 107
_LINUX_EXT_FILESYSTEM_MAGIC = 0xEF53
_LINUX_V9FS_MAGIC = 0x01021997
_IPC_WATCHDOG_CHILD_WAIT_SECONDS = 75.0
IMAGE_LABELS = {
    "org.vast.analytics_worker.base_image_id": TENSORRT_BASE_IMAGE_ID,
    "org.vast.analytics_worker.engine": "tensorrt_cuda",
}
ASSESSMENT_NAME = "nonpublication_pilot_assessment.json"
EXECUTION_FAILURE_DIAGNOSTIC_NAME = "execution_failure_diagnostic.json"
ENGINE_TENSORRT_CUDA = "tensorrt_cuda"
PROTOCOL_IDENTITY_SHA256 = (
    "cbd56bae6b8862165ad596a5ccbf5d043f82f91d010fcb4731aa40901ce08df8"
)
TENSORRT_WORKER_IMPLEMENTATION_SHA256 = (
    "7a09892dc72f86c825b3ec9055fdb25859f497caf86e9e32c4d35d79f96c5c46"
)
EXECUTION_CONFIG_RELATIVE_PATH = "configs/analytics_execution_layer.yaml"
EXECUTION_CONFIG_FILE_SHA256 = (
    "c245a3514b84bc531d066c85544da8cb3d9751897cea4c83c69b52c91f6a360c"
)
RESULT_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_secondary_sensitivity_nonpublication_pilot_execution_assessment"
)
RESULT_DOMAIN = b"VAST:kpp-legacy-iss-v2-nonpublication-pilot-executor:v1\0"
WATCHDOG_DOMAIN = b"VAST:kpp-v2-nonpublication-container-watchdog:v4\0"
IPC_WATCHDOG_DOMAIN = b"VAST:kpp-v2-nonpublication-ipc-watchdog:v3\0"
_WATCHDOG_LATE_COMMIT_REMOVED_RC = 79
CLEANUP_MUTEX_DOMAIN = b"VAST:kpp-v2-nonpublication-cleanup-mutex:v1\0"
CLEANUP_MUTEX_PATH_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-cleanup-mutex-path:v1\0"
)
CLEANUP_MUTEX_PARENT = Path("/tmp")
_CLEANUP_MUTEX_NAME_PREFIX = "vk2c-"
_CLEANUP_MUTEX_ACQUIRE_SECONDS = 75.0
RUN_LEASE_DOMAIN = b"VAST:kpp-v2-nonpublication-run-lease:v2\0"
RUN_LEASE_SCOPE_DOMAIN = b"VAST:kpp-v2-nonpublication-run-lease-scope:v1\0"
RUN_LEASE_PARENT = Path("/tmp")
_RUN_LEASE_IDENTITY_NAME_PREFIX = "vk2l-"
_RUN_LEASE_ADMISSION_NAME_PREFIX = "vk2a-"
_RUN_LEASE_RETENTION_NAME_PREFIX = "vk2r-"
_RUN_LEASE_ACQUIRE_SECONDS = 75.0
UNRESOLVED_OPERATION_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-unresolved-operation:v1\0"
)
UNRESOLVED_OPERATION_PATH_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-unresolved-operation-path:v1\0"
)
_UNRESOLVED_ROOT_NAME_PREFIX = "vk2u-"
_UNRESOLVED_MARKER_NAME_PREFIX = "op-"
_UNRESOLVED_RESOLUTION_GUARD_SUFFIX = ".resolving"
PEERCRED_DIAGNOSTIC_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-so-peercred-diagnostic:v1\0"
)
PEERCRED_DIAGNOSTIC_ARTIFACT_KIND = (
    "vast_kpp_v2_nonpublication_so_peercred_diagnostic"
)
PEER_IDENTITY_MODE_NATIVE_VISIBLE = "native-visible"
PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0 = (
    "namespace-hidden-wsl2-docker-desktop"
)
PEER_IDENTITY_MODES = (
    PEER_IDENTITY_MODE_NATIVE_VISIBLE,
    PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0,
)
PEER_IDENTITY_POLICY_VERSION = 2
PEERCRED_PLATFORM_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-peercred-platform:v1\0"
)
EXECUTION_PROGRESS_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-execution-progress:v1\0"
)
EXECUTION_FAILURE_DIAGNOSTIC_DOMAIN = (
    b"VAST:kpp-v2-nonpublication-execution-failure-diagnostic:v1\0"
)
_WSL_OSRELEASE_CANONICAL_PATH = "/proc/sys/kernel/osrelease"
_WSL_OSRELEASE_PATH = Path(_WSL_OSRELEASE_CANONICAL_PATH)
_WSL_OSRELEASE_MAX_BYTES = 255
_WSL2_OSRELEASE_MARKER = "-microsoft-standard-WSL2"
_WSL2_OSRELEASE_RE = re.compile(
    r"[1-9][0-9]{0,2}(?:\.[0-9]{1,3}){2,3}-microsoft-standard-WSL2\Z"
)
_DOCKER_DESKTOP_CONTAINERD_COMMIT_ID = (
    "e53c7c1516c3b2bff98eb76f1f4117477e6f4e66"
)
FALSE_CLAIM_FIELDS = (
    "publication_ready",
    "publication_capable",
    "publishable",
    "accepted_evidence",
    "accepted_evidence_written",
    "accepted_measurement_evidence_emitted",
    "evidence_accepted",
    "benchmark",
    "benchmark_accepted",
    "promotable",
    "publication_authorized",
    "canonical_publication_outputs_written",
    "publication_receipt_written",
    "result_accepted",
    "accuracy_accepted",
    "model_acceptance",
    "runtime_acceptance",
    "power_loss_attested",
    "executed_engine_attested",
    "dynamic_library_closure_attested",
    "controller_death_cleanup_attested",
)
_FALSE_CLAIMS = {field: False for field in FALSE_CLAIM_FIELDS}
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
_PEERCRED_DIAGNOSTIC_RUN_ID_RE = re.compile(
    r"kpp-v2-secondary-peercred-diagnostic-[0-9]{8}-v[1-9][0-9]*\Z"
)
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
_KNOWN_CONTAINER_STATES = {
    "created",
    "running",
    "paused",
    "restarting",
    "removing",
    "exited",
    "dead",
}
_RUNNING_CONTAINER_STATES = {"running", "paused", "restarting"}


@dataclass(frozen=True)
class FileIdentity:
    size_bytes: int
    sha256: str
    is_regular_file: bool = True
    is_symlink: bool = False


@dataclass(frozen=True)
class CommandCapture:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandCapture: ...


@dataclass(frozen=True)
class BindingInventory:
    bindings: Mapping[str, Mapping[str, object]]
    source_paths: Mapping[str, Path]
    engine_paths: Mapping[str, Path]
    source_identities: Mapping[str, FileIdentity]
    engine_identities: Mapping[str, FileIdentity]
    manifest_identity_sha256: str
    execution_config_identity_sha256: str


@dataclass(frozen=True)
class TensorInventory:
    payloads: Mapping[str, bytes]
    bundle_observations: Sequence[Mapping[str, object]]


@dataclass
class _IpcRuntimeNamespace:
    run_identity: str
    path: Path
    parent_path: Path
    name: str
    parent_fd: int
    root_fd: int
    parent_identity: tuple[int, int, int, int, int]
    root_identity: tuple[int, int, int, int, int]
    filesystem_magic: int
    watchdog_owned: bool = False
    unlinked: bool = False
    closed: bool = False
    unresolved_operation_contract: Mapping[str, object] | None = None


@dataclass
class _IpcRuntimeWatchdogProcess:
    process: subprocess.Popen[bytes]
    control_fd: int
    ack_fd: int
    namespace: _IpcRuntimeNamespace
    sequence: int = 1
    registered: dict[str, dict[str, int]] = field(default_factory=dict)
    pending: dict[str, dict[str, int]] = field(default_factory=dict)
    protocol_poisoned: bool = False
    closed: bool = False
    terminal_returncode: int | None = None
    cleanup_ownership_retained: bool = True

    def register(self, branch: str) -> None:
        _require(
            not self.closed
            and type(branch) is str
            and branch in BRANCHES
            and branch not in self.registered
            and branch not in self.pending
            and not self.protocol_poisoned,
            "IPC watchdog socket registration drifted",
        )
        value = _validate_owned_ipc_socket(self.namespace, f"{branch}.sock")
        record = _watchdog_stat_record(value)
        self.pending[branch] = record
        _ipc_watchdog_roundtrip(
            self,
            {
                "schema_version": 1,
                "artifact_kind": "vast_nonpublication_ipc_watchdog_control_v1",
                "sequence": self.sequence,
                "action": "register",
                "branch": branch,
                "socket_identity": record,
            },
        )
        self.sequence += 1
        del self.pending[branch]
        self.registered[branch] = record

    def release(self, branch: str) -> None:
        _require(
            not self.closed
            and not self.protocol_poisoned
            and type(branch) is str
            and branch in self.registered,
            "IPC watchdog socket release drifted",
        )
        _ipc_watchdog_roundtrip(
            self,
            {
                "schema_version": 1,
                "artifact_kind": "vast_nonpublication_ipc_watchdog_control_v1",
                "sequence": self.sequence,
                "action": "release",
                "branch": branch,
                "socket_identity": self.registered[branch],
            },
        )
        self.sequence += 1
        del self.registered[branch]

    def _finish(self, action: str) -> None:
        _require(
            not self.closed and action in {"complete", "abort"},
            "IPC watchdog terminal control drifted",
        )
        poisoned_before_terminal = self.protocol_poisoned
        if action == "complete" and not poisoned_before_terminal:
            _require(
                not self.registered and not self.pending,
                "IPC watchdog completion retained registered sockets",
            )
        primary: BaseException | None = None
        if not poisoned_before_terminal:
            try:
                _ipc_watchdog_roundtrip(
                    self,
                    {
                        "schema_version": 1,
                        "artifact_kind": "vast_nonpublication_ipc_watchdog_control_v1",
                        "sequence": self.sequence,
                        "action": action,
                        "branch": None,
                        "socket_identity": None,
                    },
                )
            except BaseException as error:
                primary = error
        self.closed = True
        cleanup_errors = list(_close_ipc_watchdog_transport(self))
        returncode: int | None = None
        wait_failed = False
        try:
            returncode = self.process.wait(timeout=_IPC_WATCHDOG_CHILD_WAIT_SECONDS)
        except BaseException as error:
            wait_failed = True
            if primary is None:
                primary = error
            else:
                cleanup_errors.append(error)
            try:
                polled = self.process.poll()
                if type(polled) is int:
                    returncode = polled
            except BaseException as poll_error:
                cleanup_errors.append(poll_error)
        self.terminal_returncode = returncode
        self.cleanup_ownership_retained = returncode is None
        if wait_failed and returncode is None:
            cleanup_errors.append(
                ExecutorContractError(
                    "IPC watchdog retains cleanup ownership after bounded wait failure"
                )
            )
        namespace_attested = False
        try:
            _attest_ipc_watchdog_namespace_unlinked(self.namespace)
            namespace_attested = True
        except BaseException as error:
            cleanup_errors.append(error)
        if namespace_attested:
            self.cleanup_ownership_retained = False
        if returncode is not None and (
            returncode != 0 or not namespace_attested
        ):
            # A proven-dead child cannot retain cleanup ownership.  Preserve
            # the held namespace handles and transfer them back to the
            # controller; `_remove_private_runtime` will perform the exact
            # allowlisted socket/root cleanup before it closes those handles.
            self.namespace.watchdog_owned = False
            self.cleanup_ownership_retained = False
        protocol_abort_cleanup_attested = (
            action == "abort"
            and poisoned_before_terminal
            and namespace_attested
        )
        if (
            returncode is not None
            and returncode != 0
            and not protocol_abort_cleanup_attested
        ):
            # A partial or post-commit controller write can make the child
            # exit nonzero after the controller has already reported the
            # commit ambiguity.  During abort, independently proving that the
            # exact namespace is empty and unlinked is the cleanup result;
            # the expected poisoned-protocol exit is not a second cleanup
            # failure.
            cleanup_errors.append(
                _WatchdogChildExitError(
                    watchdog_kind="ipc_runtime",
                    returncode=returncode,
                )
            )
        if action == "complete" and poisoned_before_terminal:
            if primary is None:
                primary = ExecutorContractError(
                    "IPC watchdog protocol was already commit-ambiguous"
                )
            else:
                cleanup_errors.append(
                    ExecutorContractError(
                        "IPC watchdog protocol was already commit-ambiguous"
                    )
                )
        if primary is not None or cleanup_errors:
            raise _DescriptorClosureError(
                operation="ipc_watchdog_finish",
                primary=primary,
                close_failures=cleanup_errors,
                message="IPC watchdog terminal cleanup failed",
            ) from (
                primary if primary is not None else cleanup_errors[0]
            )

    def complete(self) -> None:
        self._finish("complete")

    def abort(self) -> None:
        self._finish("abort")


@dataclass(frozen=True)
class _ExecutorDependencies:
    platform_name: str
    environment: Mapping[str, str]
    observe_docker_cli: Callable[[], FileIdentity]
    command_runner: CommandRunner
    planner_builder: Callable[..., dict[str, object]]
    gpu_probe: Callable[..., Mapping[str, Any]]
    local_runtime_guard: Callable[[], None] | None = None
    observe_file: Callable[[Path], FileIdentity] | None = None
    binding_loader: Callable[..., BindingInventory] | None = None
    tensor_reader: Callable[..., TensorInventory] | None = None
    worker_runner: Callable[..., list[dict[str, object]]] | None = None
    run_lock_factory: Callable[[str], Any] | None = None
    cleanup_mutex_factory: Callable[[str], Any] | None = None
    progress_factory: Callable[..., _ExecutionProgressLedger] | None = None
    failure_diagnostic_writer: (
        Callable[[_RunRootCustody, Mapping[str, object]], Mapping[str, object]]
        | None
    ) = None
    stale_reaper: Callable[..., tuple[list[str], bool]] | None = None
    peercred_platform_observer: (
        Callable[[Mapping[str, object]], Mapping[str, object]] | None
    ) = None


@dataclass
class _ExecutionProgressLedger:
    """Monotonic lower-bound evidence for handshakes and validated responses."""

    run_root: Path | None
    run_id: str
    run_identity: str
    role: str
    requests: Sequence[Mapping[str, object]]
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _records: list[dict[str, object]] = field(default_factory=list, init=False)
    _handshakes: dict[str, dict[str, str]] = field(default_factory=dict, init=False)
    _barrier_released: bool = field(default=False, init=False)
    _dispatched_request_ids: set[str] = field(default_factory=set, init=False)
    _returned_request_ids: set[str] = field(default_factory=set, init=False)
    _validated_request_ids: set[str] = field(default_factory=set, init=False)
    _root_fd: int | None = field(default=None, init=False)
    _progress_fd: int | None = field(default=None, init=False)
    _progress_root: Path | None = field(default=None, init=False)
    _filesystem_magic: int | None = field(default=None, init=False)
    _expected_directory_mode: int | None = field(default=None, init=False)
    _expected_file_mode: int | None = field(default=None, init=False)
    _persisted_files: list[dict[str, object]] = field(
        default_factory=list,
        init=False,
    )
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require(
            type(self.run_id) is str
            and _RUN_ID_RE.fullmatch(self.run_id) is not None
            and type(self.run_identity) is str
            and _SHA_RE.fullmatch(self.run_identity) is not None
            and self.role in {"secondary", "sensitivity"},
            "execution progress identity drifted",
        )
        coordinates = [
            (
                item.get("request_id"),
                item.get("branch"),
                item.get("codec"),
            )
            for item in self.requests
        ]
        _require(
            len(coordinates) == 8
            and len({item[0] for item in coordinates}) == 8
            and all(
                type(request_id) is str
                and bool(request_id)
                and branch in BRANCHES
                and codec in CODECS
                for request_id, branch, codec in coordinates
            )
            and {
                (branch, codec)
                for _request_id, branch, codec in coordinates
            }
            == {(branch, codec) for branch in BRANCHES for codec in CODECS},
            "execution progress request matrix drifted",
        )
        if self.run_root is not None:
            _require(
                isinstance(self.run_root, Path)
                and self.run_root.is_absolute()
                and self.run_root.is_dir()
                and not self.run_root.is_symlink(),
                "execution progress run root drifted",
            )
            if os.name == "posix" and sys.platform.startswith("linux"):
                self._open_persistent_namespace()

    def _open_persistent_namespace(self) -> None:
        _require(
            self.run_root is not None
            and self._root_fd is None
            and self._progress_fd is None,
            "execution progress namespace state drifted",
        )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        _require(
            nofollow != 0 and cloexec != 0 and directory != 0,
            "execution progress no-follow custody is unavailable",
        )
        root_fd: int | None = None
        progress_fd: int | None = None
        created = False
        try:
            root_fd = os.open(
                self.run_root,
                os.O_RDONLY | directory | nofollow | cloexec,
            )
            root_state = os.fstat(root_fd)
            root_named = os.stat(self.run_root, follow_symlinks=False)
            magic = _linux_fstatfs_magic(root_fd)
            root_mode = stat.S_IMODE(root_state.st_mode)
            if magic == _LINUX_EXT_FILESYSTEM_MAGIC:
                expected_directory_mode = 0o700
                expected_file_mode = 0o400
            elif magic == _LINUX_V9FS_MAGIC:
                expected_directory_mode = 0o777
                expected_file_mode = 0o555
            else:
                raise ExecutorContractError(
                    "execution progress filesystem type drifted"
                )
            _require(
                _directory_identity(root_state) == _directory_identity(root_named)
                and stat.S_ISDIR(root_state.st_mode)
                and root_state.st_uid == os.getuid()
                and root_state.st_gid == os.getgid()
                and root_mode == expected_directory_mode,
                "execution progress run-root custody drifted",
            )
            os.mkdir("runtime_progress", 0o700, dir_fd=root_fd)
            created = True
            progress_fd = os.open(
                "runtime_progress",
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=root_fd,
            )
            progress_state = os.fstat(progress_fd)
            progress_named = os.stat(
                "runtime_progress",
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            _require(
                _directory_identity(progress_state)
                == _directory_identity(progress_named)
                and stat.S_ISDIR(progress_state.st_mode)
                and stat.S_IMODE(progress_state.st_mode)
                == expected_directory_mode
                and progress_state.st_uid == os.getuid()
                and progress_state.st_gid == os.getgid()
                and _linux_fstatfs_magic(progress_fd) == magic
                and os.listdir(progress_fd) == [],
                "execution progress directory custody drifted",
            )
            os.fsync(progress_fd)
            os.fsync(root_fd)
            self._root_fd = root_fd
            self._progress_fd = progress_fd
            self._progress_root = self.run_root / "runtime_progress"
            self._filesystem_magic = magic
            self._expected_directory_mode = expected_directory_mode
            self._expected_file_mode = expected_file_mode
            root_fd = None
            progress_fd = None
        except FileExistsError as error:
            raise ExecutorContractError(
                "execution progress namespace already exists"
            ) from error
        except ExecutorContractError:
            raise
        except OSError as error:
            raise ExecutorContractError(
                "cannot create execution progress namespace"
            ) from error
        finally:
            active_error = sys.exception()
            close_failures: list[BaseException] = []
            if progress_fd is not None:
                try:
                    os.close(progress_fd)
                except BaseException as error:
                    close_failures.append(error)
            if created and root_fd is not None:
                try:
                    os.rmdir("runtime_progress", dir_fd=root_fd)
                except BaseException as error:
                    close_failures.append(error)
            if root_fd is not None:
                try:
                    os.close(root_fd)
                except BaseException as error:
                    close_failures.append(error)
            if close_failures:
                raise _DescriptorClosureError(
                    operation="execution_progress_namespace_creation",
                    primary=active_error,
                    close_failures=close_failures,
                ) from (
                    active_error
                    if active_error is not None
                    else close_failures[0]
                )

    def _persist_record(self, record: Mapping[str, object]) -> None:
        if self._progress_fd is None:
            _require(
                self.run_root is None
                or os.name != "posix"
                or not sys.platform.startswith("linux"),
                "Linux execution progress persistence is unavailable",
            )
            return
        _require(
            not self._closed
            and self._root_fd is not None
            and self._expected_file_mode is not None
            and self._filesystem_magic is not None,
            "execution progress persistence state drifted",
        )
        sequence = record.get("sequence")
        _require(
            type(sequence) is int and sequence == len(self._persisted_files) + 1,
            "execution progress persistence sequence drifted",
        )
        name = f"{sequence:04d}.json"
        payload = canonical_line(dict(record))
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(
                name,
                flags,
                0o400,
                dir_fd=self._progress_fd,
            )
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                _require(written > 0, "execution progress write stalled")
                view = view[written:]
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            state = os.fstat(descriptor)
            named = os.stat(
                name,
                dir_fd=self._progress_fd,
                follow_symlinks=False,
            )
            identity = (
                int(state.st_dev),
                int(state.st_ino),
                int(state.st_mode),
                int(state.st_uid),
                int(state.st_gid),
                int(state.st_nlink),
                int(state.st_size),
            )
            _require(
                identity
                == (
                    int(named.st_dev),
                    int(named.st_ino),
                    int(named.st_mode),
                    int(named.st_uid),
                    int(named.st_gid),
                    int(named.st_nlink),
                    int(named.st_size),
                )
                and stat.S_ISREG(state.st_mode)
                and stat.S_IMODE(state.st_mode) == self._expected_file_mode
                and state.st_uid == os.getuid()
                and state.st_gid == os.getgid()
                and state.st_nlink == 1
                and state.st_size == len(payload)
                and stat.S_IMODE(state.st_mode) & 0o222 == 0,
                "execution progress file custody drifted",
            )
            os.lseek(descriptor, 0, os.SEEK_SET)
            readback = bytearray()
            while len(readback) <= len(payload):
                chunk = os.read(
                    descriptor,
                    min(1024 * 1024, len(payload) + 1 - len(readback)),
                )
                if not chunk:
                    break
                readback.extend(chunk)
            _require(
                bytes(readback) == payload,
                "execution progress durable readback drifted",
            )
            os.fsync(self._progress_fd)
            self._persisted_files.append(
                {
                    "name": name,
                    "identity": identity,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        except FileExistsError as error:
            raise ExecutorContractError(
                "execution progress record already exists"
            ) from error
        except ExecutorContractError:
            raise
        except OSError as error:
            raise ExecutorContractError(
                "cannot persist execution progress record"
            ) from error
        finally:
            active_error = sys.exception()
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as close_error:
                    raise _DescriptorClosureError(
                        operation="execution_progress_record_persistence",
                        primary=active_error,
                        close_failures=[close_error],
                    ) from (
                        active_error if active_error is not None else close_error
                    )

    def _validate_persisted_records(self) -> None:
        if self._progress_fd is None:
            _require(
                not self._persisted_files,
                "in-memory execution progress has persisted file facts",
            )
            return
        _require(
            self._root_fd is not None
            and self._progress_root is not None
            and self._expected_directory_mode is not None
            and self._filesystem_magic is not None
            and len(self._persisted_files) == len(self._records),
            "execution progress closure state drifted",
        )
        expected_names = [str(item["name"]) for item in self._persisted_files]
        _require(
            sorted(os.listdir(self._progress_fd)) == sorted(expected_names),
            "execution progress file-set closure drifted",
        )
        validation_failures: list[BaseException] = []
        for expected, record in zip(self._persisted_files, self._records):
            descriptor: int | None = None
            primary: BaseException | None = None
            try:
                descriptor = os.open(
                    str(expected["name"]),
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=self._progress_fd,
                )
                state = os.fstat(descriptor)
                named = os.stat(
                    str(expected["name"]),
                    dir_fd=self._progress_fd,
                    follow_symlinks=False,
                )
                identity = (
                    int(state.st_dev),
                    int(state.st_ino),
                    int(state.st_mode),
                    int(state.st_uid),
                    int(state.st_gid),
                    int(state.st_nlink),
                    int(state.st_size),
                )
                _require(
                    identity == tuple(expected["identity"])
                    and identity
                    == (
                        int(named.st_dev),
                        int(named.st_ino),
                        int(named.st_mode),
                        int(named.st_uid),
                        int(named.st_gid),
                        int(named.st_nlink),
                        int(named.st_size),
                    ),
                    "execution progress record identity changed",
                )
                payload = bytearray()
                while len(payload) <= int(expected["size_bytes"]):
                    chunk = os.read(
                        descriptor,
                        min(
                            1024 * 1024,
                            int(expected["size_bytes"]) + 1 - len(payload),
                        ),
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)
                expected_payload = canonical_line(record)
                _require(
                    bytes(payload) == expected_payload
                    and hashlib.sha256(payload).hexdigest()
                    == expected["sha256"],
                    "execution progress record bytes changed",
                )
            except ExecutorContractError as error:
                primary = error
            except OSError as error:
                primary = ExecutorContractError(
                    "cannot validate execution progress record"
                )
                primary.__cause__ = error
            except BaseException as error:
                primary = error
            finally:
                close_error: BaseException | None = None
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except BaseException as error:
                        close_error = error
                if primary is not None or close_error is not None:
                    validation_failures.append(
                        _DescriptorClosureError(
                            operation="execution_progress_record_validation",
                            primary=primary,
                            close_failures=(
                                [close_error]
                                if close_error is not None
                                else []
                            ),
                        )
                    )
        try:
            progress_state = os.fstat(self._progress_fd)
            progress_named = os.stat(
                "runtime_progress",
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
            _require(
                _directory_identity(progress_state)
                == _directory_identity(progress_named)
                and stat.S_IMODE(progress_state.st_mode)
                == self._expected_directory_mode
                and _linux_fstatfs_magic(self._progress_fd)
                == self._filesystem_magic,
                "execution progress directory changed",
            )
        except BaseException as error:
            validation_failures.append(error)
        if validation_failures:
            first, *remaining = validation_failures
            raise _DescriptorClosureError(
                operation="execution_progress_records_validation",
                primary=first,
                close_failures=remaining,
            ) from first

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            operation_errors: list[BaseException] = []
            try:
                self._validate_persisted_records()
            except BaseException as error:
                operation_errors.append(error)
            if self._progress_fd is not None:
                try:
                    os.fsync(self._progress_fd)
                except BaseException as error:
                    operation_errors.append(error)
            if self._root_fd is not None:
                try:
                    os.fsync(self._root_fd)
                except BaseException as error:
                    operation_errors.append(error)
            close_failures: list[BaseException] = []
            for descriptor_name in ("_progress_fd", "_root_fd"):
                descriptor = getattr(self, descriptor_name)
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except BaseException as error:
                        close_failures.append(error)
                    finally:
                        setattr(self, descriptor_name, None)
            if operation_errors or close_failures:
                raise _DescriptorClosureError(
                    operation="execution_progress",
                    primary=operation_errors[0] if operation_errors else None,
                    close_failures=[*operation_errors[1:], *close_failures],
                ) from (
                    operation_errors[0]
                    if operation_errors
                    else close_failures[0]
                )

    def _append(self, event_kind: str, facts: Mapping[str, object]) -> dict[str, object]:
        _require(
            event_kind
            in {
                "handshake_accepted",
                "four_party_barrier_released",
                "infer_request_dispatched",
                "infer_client_returned",
                "infer_response_validated",
                "operation_stage",
            },
            "execution progress event kind drifted",
        )
        sequence = len(self._records) + 1
        prior = (
            self._records[-1]["record_self_sha256"]
            if self._records
            else None
        )
        core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_v2_nonpublication_execution_progress_v1",
            "sequence": sequence,
            "event_kind": event_kind,
            "run_id": self.run_id,
            "run_identity_sha256": self.run_identity,
            "role": self.role,
            "prior_record_sha256": prior,
            **dict(facts),
        }
        record = {
            **core,
            "record_self_sha256": hashlib.sha256(
                EXECUTION_PROGRESS_DOMAIN + canonical_line(core)
            ).hexdigest(),
        }
        self._persist_record(record)
        self._records.append(record)
        return dict(record)

    def record_handshake(
        self,
        *,
        branch: str,
        capability_sha256: str,
        peer_identity_sha256: str | None,
    ) -> dict[str, object]:
        with self._lock:
            _require(
                branch in BRANCHES
                and branch not in self._handshakes
                and not self._barrier_released
                and _SHA_RE.fullmatch(capability_sha256) is not None
                and (
                    peer_identity_sha256 is None
                    or _SHA_RE.fullmatch(peer_identity_sha256) is not None
                ),
                "execution progress handshake drifted",
            )
            record = self._append(
                "handshake_accepted",
                {
                    "branch": branch,
                    "request_id": None,
                    "request_ordinal": None,
                    "capability_sha256": capability_sha256,
                    "peer_identity_sha256": peer_identity_sha256,
                    "response_sha256": None,
                    "output_sha256": None,
                    "output_size_bytes": None,
                },
            )
            self._handshakes[branch] = {
                "capability_sha256": capability_sha256,
                "peer_identity_sha256": peer_identity_sha256 or "",
                "record_self_sha256": str(record["record_self_sha256"]),
            }
            return record

    def record_infer_dispatched(
        self,
        *,
        branch: str,
        request_id: str,
        request_ordinal: int,
        capability_sha256: str,
        peer_identity_sha256: str | None,
    ) -> dict[str, object]:
        with self._lock:
            expected = [
                item for item in self.requests if item.get("branch") == branch
            ]
            recorded_peer = self._handshakes.get(branch, {}).get(
                "peer_identity_sha256"
            )
            normalized_peer = peer_identity_sha256 or ""
            _require(
                self._barrier_released
                and branch in self._handshakes
                and type(request_ordinal) is int
                and 0 <= request_ordinal < len(CODECS)
                and len(expected) == len(CODECS)
                and expected[request_ordinal].get("request_id") == request_id
                and request_id not in self._dispatched_request_ids
                and capability_sha256
                == self._handshakes[branch]["capability_sha256"]
                and normalized_peer == recorded_peer,
                "execution progress inference dispatch drifted",
            )
            record = self._append(
                "infer_request_dispatched",
                {
                    "branch": branch,
                    "request_id": request_id,
                    "request_ordinal": request_ordinal,
                    "capability_sha256": capability_sha256,
                    "peer_identity_sha256": peer_identity_sha256,
                    "response_sha256": None,
                    "output_sha256": None,
                    "output_size_bytes": None,
                },
            )
            self._dispatched_request_ids.add(request_id)
            return record

    def record_client_returned(
        self,
        *,
        branch: str,
        request_id: str,
        request_ordinal: int,
        response_is_dict: bool,
        output_is_bytes: bool,
        output_size_bytes: int | None,
    ) -> dict[str, object]:
        with self._lock:
            _require(
                branch in BRANCHES
                and request_id in self._dispatched_request_ids
                and request_id not in self._returned_request_ids
                and type(request_ordinal) is int
                and 0 <= request_ordinal < len(CODECS)
                and type(response_is_dict) is bool
                and type(output_is_bytes) is bool
                and (
                    output_size_bytes is None
                    or (
                        type(output_size_bytes) is int
                        and 0 <= output_size_bytes <= 16 * 1024 * 1024
                    )
                ),
                "execution progress client return drifted",
            )
            record = self._append(
                "infer_client_returned",
                {
                    "branch": branch,
                    "request_id": request_id,
                    "request_ordinal": request_ordinal,
                    "capability_sha256": None,
                    "peer_identity_sha256": None,
                    "response_sha256": None,
                    "output_sha256": None,
                    "output_size_bytes": output_size_bytes,
                    "response_is_dict": response_is_dict,
                    "output_is_bytes": output_is_bytes,
                },
            )
            self._returned_request_ids.add(request_id)
            return record

    def record_barrier_released(self) -> dict[str, object]:
        with self._lock:
            _require(
                not self._barrier_released
                and set(self._handshakes) == set(BRANCHES),
                "execution progress four-party barrier drifted",
            )
            record = self._append(
                "four_party_barrier_released",
                {
                    "branch": None,
                    "request_id": None,
                    "request_ordinal": None,
                    "capability_sha256": None,
                    "peer_identity_sha256": None,
                    "response_sha256": None,
                    "output_sha256": None,
                    "output_size_bytes": None,
                    "handshake_record_sha256s": {
                        branch: self._handshakes[branch]["record_self_sha256"]
                        for branch in BRANCHES
                    },
                },
            )
            self._barrier_released = True
            return record

    def record_infer_response(
        self,
        *,
        branch: str,
        request_id: str,
        request_ordinal: int,
        response_sha256: str,
        output_sha256: str,
        output_size_bytes: int,
        capability_sha256: str,
        peer_identity_sha256: str | None,
    ) -> dict[str, object]:
        with self._lock:
            expected = [
                item
                for item in self.requests
                if item.get("branch") == branch
            ]
            _require(
                self._barrier_released
                and branch in self._handshakes
                and type(request_ordinal) is int
                and 0 <= request_ordinal < len(CODECS)
                and len(expected) == len(CODECS)
                and expected[request_ordinal].get("request_id") == request_id
                and request_id in self._dispatched_request_ids
                and request_id in self._returned_request_ids
                and request_id not in self._validated_request_ids
                and _SHA_RE.fullmatch(response_sha256) is not None
                and _SHA_RE.fullmatch(output_sha256) is not None
                and output_size_bytes == 4000
                and capability_sha256
                == self._handshakes[branch]["capability_sha256"]
                and (peer_identity_sha256 or "")
                == self._handshakes[branch]["peer_identity_sha256"],
                "execution progress inference response drifted",
            )
            record = self._append(
                "infer_response_validated",
                {
                    "branch": branch,
                    "request_id": request_id,
                    "request_ordinal": request_ordinal,
                    "capability_sha256": capability_sha256,
                    "peer_identity_sha256": peer_identity_sha256,
                    "response_sha256": response_sha256,
                    "output_sha256": output_sha256,
                    "output_size_bytes": output_size_bytes,
                },
            )
            self._validated_request_ids.add(request_id)
            return record

    def summary(self) -> dict[str, object]:
        with self._lock:
            _require(not self._closed, "execution progress ledger is closed")
            self._validate_persisted_records()
            validated = [
                item
                for item in self._records
                if item["event_kind"] == "infer_response_validated"
            ]
            count = len(validated)
            dispatched_count = len(self._dispatched_request_ids)
            returned_count = len(self._returned_request_ids)
            _require(
                count == len(self._validated_request_ids)
                and 0 <= count <= returned_count <= dispatched_count <= 8,
                "execution progress validated count drifted",
            )
            if count > 0:
                inference_performed: bool | None = True
                inference_attested = True
            elif dispatched_count == 0:
                inference_performed = False
                inference_attested = True
            else:
                inference_performed = None
                inference_attested = False
            return {
                "expected_response_count": 8,
                "dispatched_checkpoint_count": dispatched_count,
                "client_returned_checkpoint_count": returned_count,
                "validated_checkpoint_count": count,
                "dispatched_request_ids": sorted(self._dispatched_request_ids),
                "client_returned_request_ids": sorted(self._returned_request_ids),
                "validated_request_ids": [
                    str(item["request_id"]) for item in validated
                ],
                "checkpoint_sha256s": [
                    str(item["record_self_sha256"]) for item in self._records
                ],
                "checkpoint_records": [dict(item) for item in self._records],
                "persistence": {
                    "mode": (
                        "durable_o_excl_fsync"
                        if self._progress_root is not None
                        else "synthetic_in_memory"
                    ),
                    "relative_directory": (
                        "runtime_progress"
                        if self._progress_root is not None
                        else None
                    ),
                    "file_count": len(self._persisted_files),
                    "filesystem_magic": self._filesystem_magic,
                    "requested_file_mode": (
                        "0400" if self._progress_root is not None else None
                    ),
                    "effective_file_mode": (
                        f"{self._expected_file_mode:04o}"
                        if self._expected_file_mode is not None
                        else None
                    ),
                    "integrity_attested": True,
                    "closure_error_sha256": None,
                },
                "chain_head_sha256": (
                    str(self._records[-1]["record_self_sha256"])
                    if self._records
                    else None
                ),
                "handshake_checkpoint_count": len(self._handshakes),
                "four_party_barrier_released": self._barrier_released,
                "inference_performed": inference_performed,
                "inference_performed_attested": inference_attested,
                "all_inferences_completed": count == 8,
            }

    def failure_summary(self, closure_error: BaseException) -> dict[str, object]:
        """Return conservative in-memory lower bounds after persistence failure."""

        with self._lock:
            validated = [
                item
                for item in self._records
                if item.get("event_kind") == "infer_response_validated"
                and item.get("request_id") in self._validated_request_ids
            ]
            dispatched_count = len(self._dispatched_request_ids)
            returned_count = len(self._returned_request_ids)
            count = len(validated)
            coherent = (
                count == len(self._validated_request_ids)
                and 0 <= count <= returned_count <= dispatched_count <= 8
            )
            if not coherent:
                inference_performed: bool | None = None
                inference_attested = False
            elif count > 0:
                inference_performed = True
                inference_attested = True
            elif dispatched_count == 0:
                inference_performed = False
                inference_attested = True
            else:
                inference_performed = None
                inference_attested = False
            return {
                "expected_response_count": 8,
                "dispatched_checkpoint_count": dispatched_count,
                "client_returned_checkpoint_count": returned_count,
                "validated_checkpoint_count": count,
                "dispatched_request_ids": sorted(self._dispatched_request_ids),
                "client_returned_request_ids": sorted(self._returned_request_ids),
                "validated_request_ids": [
                    str(item["request_id"]) for item in validated
                ],
                "checkpoint_sha256s": [
                    str(item["record_self_sha256"])
                    for item in self._records
                ],
                "checkpoint_records": [dict(item) for item in self._records],
                "persistence": {
                    "mode": (
                        "durable_o_excl_fsync"
                        if self._progress_root is not None
                        else "synthetic_in_memory"
                    ),
                    "relative_directory": (
                        "runtime_progress"
                        if self._progress_root is not None
                        else None
                    ),
                    "file_count": len(self._persisted_files),
                    "filesystem_magic": self._filesystem_magic,
                    "requested_file_mode": (
                        "0400" if self._progress_root is not None else None
                    ),
                    "effective_file_mode": (
                        f"{self._expected_file_mode:04o}"
                        if self._expected_file_mode is not None
                        else None
                    ),
                    "integrity_attested": False,
                    "closure_error_sha256": hashlib.sha256(
                        str(closure_error).encode("utf-8")
                    ).hexdigest(),
                },
                "chain_head_sha256": (
                    str(self._records[-1]["record_self_sha256"])
                    if self._records
                    else None
                ),
                "handshake_checkpoint_count": len(self._handshakes),
                "four_party_barrier_released": self._barrier_released,
                "inference_performed": inference_performed,
                "inference_performed_attested": inference_attested,
                "all_inferences_completed": coherent and count == 8,
            }


def _build_execution_failure_diagnostic(
    *,
    progress: _ExecutionProgressLedger | None,
    error: BaseException,
    phase: str,
    stage: str,
    branch: str | None,
    diagnostic_path: str | None,
    diagnostic_persistence_state: str,
    progress_facts: Mapping[str, object] | None = None,
    run_id: str | None = None,
    run_identity: str | None = None,
    role: str | None = None,
    assessment_persistence: Mapping[str, object] | None = None,
    runtime_cleanup: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if isinstance(error, _ExecutionFailureBundle):
        primary_error = error.primary
        primary_phase = error.primary_phase
        primary_stage = error.primary_stage
        primary_branch = error.primary_branch
        supplemental_failures = error.supplemental_failures
    else:
        primary_error = error
        primary_phase = phase
        primary_stage = stage
        primary_branch = branch
        supplemental_failures = ()
    primary_projection = _execution_failure_projection(
        error=primary_error,
        phase=primary_phase,
        stage=primary_stage,
        branch=primary_branch,
    )
    if progress is not None:
        _require(
            progress_facts is None
            and run_id is None
            and run_identity is None
            and role is None,
            "execution failure progress inputs overlap",
        )
        actual_progress_facts = progress.summary()
        actual_run_id = progress.run_id
        actual_run_identity = progress.run_identity
        actual_role = progress.role
    else:
        actual_progress_facts = dict(
            _mapping(progress_facts, "execution failure progress facts")
        )
        actual_run_id = run_id
        actual_run_identity = run_identity
        actual_role = role
    _require(
        phase in _EXECUTION_FAILURE_PHASES
        and primary_projection["stage"] in _EXECUTION_FAILURE_STAGES
        and (primary_projection["branch"] is None or primary_projection["branch"] in BRANCHES)
        and type(actual_run_id) is str
        and _RUN_ID_RE.fullmatch(actual_run_id) is not None
        and type(actual_run_identity) is str
        and _SHA_RE.fullmatch(actual_run_identity) is not None
        and actual_role in {"secondary", "sensitivity"}
        and diagnostic_persistence_state
        in {"not_started", "self_commit_unattested", "ambiguous"}
        and (
            (
                diagnostic_persistence_state == "not_started"
                and diagnostic_path is None
            )
            or (
                diagnostic_persistence_state
                in {"self_commit_unattested", "ambiguous"}
                and type(diagnostic_path) is str
                and bool(diagnostic_path)
            )
        ),
        "execution failure diagnostic inputs drifted",
    )
    expected_progress_fields = {
        "expected_response_count",
        "dispatched_checkpoint_count",
        "client_returned_checkpoint_count",
        "validated_checkpoint_count",
        "dispatched_request_ids",
        "client_returned_request_ids",
        "validated_request_ids",
        "checkpoint_sha256s",
        "checkpoint_records",
        "persistence",
        "chain_head_sha256",
        "handshake_checkpoint_count",
        "four_party_barrier_released",
        "inference_performed",
        "inference_performed_attested",
        "all_inferences_completed",
    }
    _require(
        set(actual_progress_facts) == expected_progress_fields,
        "execution failure progress schema drifted",
    )
    inference = actual_progress_facts["inference_performed"]
    assessment_state = (
        dict(assessment_persistence)
        if assessment_persistence is not None
        else {
            "attempted": False,
            "write_returned": False,
            "commit_attested": False,
            "state": "not_started",
        }
    )
    _require(
        set(assessment_state)
        == {"attempted", "write_returned", "commit_attested", "state"}
        and type(assessment_state["attempted"]) is bool
        and type(assessment_state["write_returned"]) is bool
        and assessment_state["commit_attested"] is False
        and assessment_state["state"]
        in {"not_started", "ambiguous", "write_returned_commit_unattested"},
        "assessment persistence facts drifted",
    )
    runtime_cleanup_state = dict(
        _mapping(
            runtime_cleanup,
            "execution failure runtime cleanup",
        )
        if runtime_cleanup is not None
        else _runtime_cleanup_observation(
            attempted=False,
            docker=None,
            unresolved_operations=None,
        )
    )
    _require(
        set(runtime_cleanup_state)
        == {
            "schema_version",
            "policy_id",
            "attempted",
            "docker_observation_available",
            "unresolved_operation_observation_available",
            "complete_attestation",
            "docker",
            "unresolved_operations",
        }
        and runtime_cleanup_state.get("schema_version") == 1
        and runtime_cleanup_state.get("policy_id")
        == "failure_safe_owned_runtime_poststate_v1"
        and all(
            type(runtime_cleanup_state[key]) is bool
            for key in (
                "attempted",
                "docker_observation_available",
                "unresolved_operation_observation_available",
                "complete_attestation",
            )
        ),
        "execution failure runtime cleanup schema drifted",
    )
    canonical_line(runtime_cleanup_state)
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_v2_nonpublication_execution_failure_diagnostic_v1",
        "claim_status": "postexecution_diagnostic_nonpublication_not_acceptance",
        "status": "blocked_executor_contract_error",
        "role": actual_role,
        "run_id": actual_run_id,
        "run_identity_sha256": actual_run_identity,
        "failure": primary_projection,
        "supplemental_failures": [
            {
                "scope": item.scope,
                **_execution_failure_projection(
                    error=item.error,
                    phase=item.phase,
                    stage=item.stage,
                    branch=item.branch,
                ),
            }
            for item in supplemental_failures
        ],
        "progress": actual_progress_facts,
        "diagnostic_persistence": {
            "path": diagnostic_path,
            "attempted": diagnostic_path is not None,
            "write_returned": None,
            "write_returned_attested": False,
            "commit_attested": False,
            "state": diagnostic_persistence_state,
            "self_commit_attested": False,
            "success_authority": "outer_capture_and_process_returncode",
        },
        "assessment_persistence": assessment_state,
        "runtime_cleanup": runtime_cleanup_state,
        "threat_model_boundary": {
            "concurrent_project_tree_writer_excluded": True,
            "concurrent_same_uid_project_tree_writer_excluded": True,
            "concurrent_other_uid_wsl_project_tree_writer_excluded": True,
            "concurrent_windows_side_project_writer_excluded": True,
            "concurrent_same_uid_runtime_state_writer_excluded": True,
            "filesystem_acl_attested": False,
        },
        "operational_completion_observed": False,
        "inference_performed": inference,
        "inference_performed_attested": actual_progress_facts[
            "inference_performed_attested"
        ],
        "all_inferences_completed": actual_progress_facts[
            "all_inferences_completed"
        ],
        **_FALSE_CLAIMS,
    }
    return {
        **core,
        "diagnostic_sha256": hashlib.sha256(
            EXECUTION_FAILURE_DIAGNOSTIC_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }


class ExecutorContractError(RuntimeError):
    """The local execution boundary differs from the frozen pilot contract."""


def _bounded_command_stream_facts(payload: bytes) -> dict[str, object]:
    _require(
        type(payload) is bytes and len(payload) <= 16 * 1024 * 1024,
        "Docker command stream facts drifted",
    )
    safe_text: str | None = None
    if len(payload) <= 4096:
        try:
            decoded = payload.decode("utf-8")
        except UnicodeError:
            decoded = ""
        if decoded and all(
            character in "\r\n\t" or 0x20 <= ord(character) <= 0x7E
            for character in decoded
        ):
            safe_text = decoded
    return {
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "safe_bounded_text": safe_text,
    }


class _DockerOperationError(ExecutorContractError):
    def __init__(
        self,
        message: str,
        *,
        stage: str,
        command_class: str,
        capture: CommandCapture,
    ) -> None:
        _require(
            stage in _EXECUTION_FAILURE_STAGES
            and command_class
            in {
                "container_inventory",
                "container_remove",
                "container_inspect",
                "container_create",
            }
            and type(capture) is CommandCapture
            and type(capture.returncode) is int,
            "Docker operation failure facts drifted",
        )
        super().__init__(message)
        self.stage = stage
        self.command_facts = {
            "command_class": command_class,
            "returncode": capture.returncode,
            "stdout": _bounded_command_stream_facts(capture.stdout),
            "stderr": _bounded_command_stream_facts(capture.stderr),
        }


class _WatchdogChildExitError(ExecutorContractError):
    """Truthful bounded projection when a child exposes only its exit status."""

    def __init__(self, *, watchdog_kind: str, returncode: int) -> None:
        _require(
            watchdog_kind in {"ipc_runtime", "owned_container"}
            and type(returncode) is int
            and returncode != 0,
            "watchdog child exit facts drifted",
        )
        super().__init__(f"{watchdog_kind} watchdog exited nonzero")
        self.watchdog_kind = watchdog_kind
        self.returncode = returncode


@dataclass(frozen=True)
class _SupplementalExecutionFailure:
    scope: str
    phase: str
    stage: str
    branch: str | None
    error: BaseException

    def __post_init__(self) -> None:
        _require(
            self.scope in _EXECUTION_CLEANUP_FAILURE_SCOPES
            and self.phase in _EXECUTION_FAILURE_PHASES
            and self.stage in _EXECUTION_FAILURE_STAGES
            and (self.branch is None or self.branch in BRANCHES)
            and isinstance(self.error, BaseException),
            "supplemental execution failure drifted",
        )


class _ExecutionFailureBundle(ExecutorContractError):
    def __init__(
        self,
        *,
        primary: BaseException,
        primary_phase: str,
        primary_stage: str,
        primary_branch: str | None,
        supplemental_failures: Sequence[_SupplementalExecutionFailure],
    ) -> None:
        _require(
            isinstance(primary, BaseException)
            and primary_phase in _EXECUTION_FAILURE_PHASES
            and primary_stage in _EXECUTION_FAILURE_STAGES
            and (primary_branch is None or primary_branch in BRANCHES)
            and all(
                type(item) is _SupplementalExecutionFailure
                for item in supplemental_failures
            ),
            "execution failure bundle drifted",
        )
        super().__init__("execution failed with additional cleanup failures")
        self.primary = primary
        self.primary_phase = primary_phase
        self.primary_stage = primary_stage
        self.primary_branch = primary_branch
        self.supplemental_failures = tuple(supplemental_failures)


def _bundle_execution_failure_with_supplementals(
    primary: BaseException,
    *,
    primary_phase: str,
    primary_stage: str,
    primary_branch: str | None,
    supplemental_failures: Sequence[_SupplementalExecutionFailure],
) -> BaseException:
    _require(
        isinstance(primary, BaseException)
        and primary_phase in _EXECUTION_FAILURE_PHASES
        and primary_stage in _EXECUTION_FAILURE_STAGES
        and (primary_branch is None or primary_branch in BRANCHES)
        and all(
            type(item) is _SupplementalExecutionFailure
            for item in supplemental_failures
        ),
        "execution failure supplemental merge drifted",
    )
    if not supplemental_failures:
        return primary
    if isinstance(primary, _ExecutionFailureBundle):
        return _ExecutionFailureBundle(
            primary=primary.primary,
            primary_phase=primary.primary_phase,
            primary_stage=primary.primary_stage,
            primary_branch=primary.primary_branch,
            supplemental_failures=[
                *primary.supplemental_failures,
                *supplemental_failures,
            ],
        )
    return _ExecutionFailureBundle(
        primary=primary,
        primary_phase=primary_phase,
        primary_stage=primary_stage,
        primary_branch=primary_branch,
        supplemental_failures=supplemental_failures,
    )


def _exception_detail_projection(
    error: BaseException,
    *,
    ancestors: frozenset[int] = frozenset(),
) -> dict[str, object]:
    _require(
        isinstance(error, BaseException)
        and id(error) not in ancestors
        and len(ancestors) < 32,
        "execution exception projection graph drifted",
    )
    next_ancestors = ancestors | {id(error)}
    docker_failure = (
        dict(error.command_facts)
        if isinstance(error, _DockerOperationError)
        else None
    )
    watchdog_child = (
        {
            "watchdog_kind": error.watchdog_kind,
            "returncode": error.returncode,
            "exact_child_failure_cause_attested": False,
            "child_failure_detail_transport_available": False,
        }
        if isinstance(error, _WatchdogChildExitError)
        else None
    )
    closure_failure = None
    if isinstance(error, _DescriptorClosureError):
        closure_failure = {
            "operation": error.operation,
            "primary": (
                _exception_detail_projection(
                    error.primary,
                    ancestors=next_ancestors,
                )
                if error.primary is not None
                else None
            ),
            "close_failures": [
                _exception_detail_projection(
                    item,
                    ancestors=next_ancestors,
                )
                for item in error.close_failures
            ],
        }
        if isinstance(error, _FinalOwnedContainerCleanupError):
            closure_failure["poststate_observation"] = {
                "owned_container_ids_by_name_sha256": dict(
                    error.registry_id_sha256s
                ),
                "successful_absence_inspects": [
                    dict(item) for item in error.absence_inspects
                ],
                "final_catalog": (
                    dict(error.final_catalog)
                    if error.final_catalog is not None
                    else None
                ),
                "complete_attestation": False,
            }
        if isinstance(error, _StaleExecutionReaperError):
            closure_failure["stale_reaper_observation"] = {
                "reaped_container_id_sha256s": list(
                    error.reaped_container_id_sha256s
                ),
                "failed_branches": list(error.failed_branches),
                "complete_attestation": False,
            }
    return {
        "exception_type": type(error).__name__,
        "message_sha256": hashlib.sha256(
            str(error).encode("utf-8")
        ).hexdigest(),
        "docker_command": docker_failure,
        "watchdog_child": watchdog_child,
        "closure_failure": closure_failure,
    }


def _execution_failure_projection(
    *,
    error: BaseException,
    phase: str,
    stage: str,
    branch: str | None,
) -> dict[str, object]:
    _require(
        isinstance(error, BaseException)
        and phase in _EXECUTION_FAILURE_PHASES
        and stage in _EXECUTION_FAILURE_STAGES
        and (branch is None or branch in BRANCHES),
        "execution failure projection inputs drifted",
    )
    details = _exception_detail_projection(error)
    docker_failure = details["docker_command"]
    return {
        "phase": phase,
        "stage": error.stage if isinstance(error, _DockerOperationError) else stage,
        "code": (
            "docker_command_contract_error"
            if docker_failure is not None
            else "executor_contract_error"
        ),
        "branch": branch,
        "exception_type": details["exception_type"],
        "message_sha256": details["message_sha256"],
        "docker_command": docker_failure,
        "watchdog_child": details["watchdog_child"],
        "closure_failure": details["closure_failure"],
    }


_EXECUTION_FAILURE_PHASES = {
    "mutating_preworker",
    "worker_execution",
    "postexecution_validation",
    "final_cleanup",
    "assessment_persistence",
    "failure_reporting",
}
_EXECUTION_CLEANUP_FAILURE_SCOPES = {
    "controller_container_cleanup",
    "container_watchdog_cleanup",
    "container_watchdog_takeover_cleanup",
    "ipc_watchdog_cleanup",
    "ipc_listener_cleanup",
    "ipc_listener_close",
    "ipc_listener_watchdog_release",
    "runtime_namespace_cleanup",
    "model_staging_cleanup",
    "ipc_namespace_cleanup",
    "run_root_closure",
    "progress_closure",
    "cleanup_mutex_close",
    "run_lease_release",
    "runtime_poststate_observation",
    "failure_diagnostic_persistence",
    "concurrent_worker_branch_failure",
    "handshake_barrier_abort",
    "worker_future_collection",
    "worker_future_terminal_drain",
    "worker_pool_shutdown",
    "ipc_listener_cleanup",
    "ipc_listener_close",
    "ipc_listener_watchdog_release",
    "model_staging_cleanup",
    "ipc_namespace_cleanup",
    "run_root_closure",
}
_EXECUTION_FAILURE_STAGES = {
    "stale_reaper",
    "gpu_probe",
    "run_namespace",
    "binding_materialization",
    "worker_orchestration",
    "worker_pool_shutdown",
    "worker_observation_validation",
    "model_file_revalidation",
    "daemon_revalidation",
    "platform_revalidation",
    "docker_cli_revalidation",
    "final_owned_container_cleanup",
    "cleanup_inventory_after_remove",
    "cleanup_inventory_existing_absence",
    "cleanup_remove",
    "cleanup_postremove_inspect",
    "container_create",
    "container_recovery",
    "controller_container_cleanup",
    "container_watchdog_cleanup",
    "container_watchdog_takeover_cleanup",
    "ipc_watchdog_cleanup",
    "ipc_listener_cleanup",
    "ipc_listener_close",
    "ipc_listener_watchdog_release",
    "runtime_namespace_cleanup",
    "model_staging_cleanup",
    "ipc_namespace_cleanup",
    "run_root_closure",
    "progress_closure",
    "cleanup_mutex_close",
    "run_lease_release",
    "runtime_poststate_docker_observation",
    "runtime_poststate_unresolved_operation_observation",
    "runtime_poststate_recording",
    "failure_diagnostic_write",
    "initial_freshness_inventory",
    "recovery_inventory_absence",
    "progress_finalization",
    "assessment_write",
}


@dataclass
class _RunRootLeafCustody:
    name: str
    descriptor: int
    identity: tuple[int, int, int, int, int, int, int]
    expected_mode: int
    size_bytes: int
    sha256: str


class _DescriptorClosureError(ExecutorContractError):
    """Preserve an operation failure together with every descriptor-close fault."""

    def __init__(
        self,
        *,
        operation: str,
        primary: BaseException | None,
        close_failures: Sequence[BaseException],
        message: str | None = None,
    ) -> None:
        _require(
            type(operation) is str
            and bool(operation)
            and (primary is not None or bool(close_failures))
            and all(isinstance(item, BaseException) for item in close_failures),
            "descriptor failure aggregation drifted",
        )
        _require(
            message is None or (type(message) is str and bool(message)),
            "descriptor failure message drifted",
        )
        super().__init__(
            message
            if message is not None
            else f"{operation} persistence or closure failed"
        )
        self.operation = operation
        self.primary = primary
        self.close_failures = tuple(close_failures)


class _RunRootArtifactPersistenceError(_DescriptorClosureError):
    """Preserve a run-root writer failure and every descriptor-close fault."""

    def __init__(
        self,
        *,
        primary: BaseException | None,
        close_failures: Sequence[BaseException],
    ) -> None:
        super().__init__(
            operation="held_run_root_artifact",
            primary=primary,
            close_failures=close_failures,
        )


class _FinalOwnedContainerCleanupError(_DescriptorClosureError):
    """Retain partial read-only poststate facts with every deterministic fault."""

    def __init__(
        self,
        *,
        primary: BaseException,
        supplemental_failures: Sequence[BaseException],
        registry_id_sha256s: Mapping[str, str],
        absence_inspects: Sequence[Mapping[str, object]],
        final_catalog: Mapping[str, object] | None,
    ) -> None:
        super().__init__(
            operation="final_owned_container_cleanup_attestation",
            primary=primary,
            close_failures=supplemental_failures,
            message="final owned-container cleanup attestation failed",
        )
        self.registry_id_sha256s = dict(registry_id_sha256s)
        self.absence_inspects = tuple(dict(item) for item in absence_inspects)
        self.final_catalog = (
            dict(final_catalog) if final_catalog is not None else None
        )


class _StaleExecutionReaperError(_DescriptorClosureError):
    """Retain successful stale-container removals beside every failed target."""

    def __init__(
        self,
        *,
        failures: Sequence[tuple[str | None, BaseException]],
        reaped_container_id_sha256s: Sequence[str],
    ) -> None:
        _require(bool(failures), "stale reaper failure set is empty")
        primary = failures[0][1]
        super().__init__(
            operation="stale_execution_reaper",
            primary=primary,
            close_failures=[error for _branch, error in failures[1:]],
            message="stale execution recovery was only partially attested",
        )
        self.failed_branches = tuple(branch for branch, _error in failures)
        self.reaped_container_id_sha256s = tuple(
            sorted(reaped_container_id_sha256s)
        )


@dataclass
class _RunRootCustody:
    path: Path
    descriptor: int
    identity: tuple[int, int, int, int, int]
    filesystem_magic: int
    expected_directory_mode: int
    leaves: dict[str, _RunRootLeafCustody] = field(default_factory=dict)
    close_attempted: bool = False

    @classmethod
    def _from_open_descriptor(
        cls,
        *,
        path: Path,
        descriptor: int,
        named_state: os.stat_result | None = None,
    ) -> _RunRootCustody:
        state = os.fstat(descriptor)
        named = (
            named_state
            if named_state is not None
            else os.stat(path, follow_symlinks=False)
        )
        path_named = os.stat(path, follow_symlinks=False)
        filesystem_magic = _linux_fstatfs_magic(descriptor)
        if filesystem_magic == _LINUX_EXT_FILESYSTEM_MAGIC:
            expected_directory_mode = 0o700
        elif filesystem_magic == _LINUX_V9FS_MAGIC:
            expected_directory_mode = 0o777
        else:
            raise ExecutorContractError("run-root filesystem type drifted")
        identity = _directory_identity(state)
        _require(
            identity == _directory_identity(named)
            and identity == _directory_identity(path_named)
            and stat.S_ISDIR(state.st_mode)
            and stat.S_IMODE(state.st_mode) == expected_directory_mode
            and state.st_uid == os.getuid()
            and state.st_gid == os.getgid(),
            "run-root custody drifted",
        )
        return cls(
            path=path,
            descriptor=descriptor,
            identity=identity,
            filesystem_magic=filesystem_magic,
            expected_directory_mode=expected_directory_mode,
        )

    @classmethod
    def create(cls, parent: Path, run_id: str) -> _RunRootCustody:
        _require(
            os.name == "posix"
            and sys.platform.startswith("linux")
            and isinstance(parent, Path)
            and parent.is_absolute()
            and _RUN_ID_RE.fullmatch(run_id) is not None,
            "run-root custody creation inputs drifted",
        )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        _require(
            nofollow != 0 and cloexec != 0 and directory != 0,
            "run-root create-and-bind custody is unavailable",
        )
        parent_fd: int | None = None
        descriptor: int | None = None
        created_custody: _RunRootCustody | None = None
        try:
            parent_fd = os.open(
                parent,
                os.O_RDONLY | directory | nofollow | cloexec,
            )
            parent_state = os.fstat(parent_fd)
            parent_named = os.stat(parent, follow_symlinks=False)
            _require(
                _directory_identity(parent_state)
                == _directory_identity(parent_named)
                and stat.S_ISDIR(parent_state.st_mode)
                and parent_state.st_uid == os.getuid()
                and parent_state.st_gid == os.getgid(),
                "run-root parent custody drifted",
            )
            os.mkdir(run_id, 0o700, dir_fd=parent_fd)
            descriptor = os.open(
                run_id,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=parent_fd,
            )
            named = os.stat(
                run_id,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
            created_custody = cls._from_open_descriptor(
                path=parent / run_id,
                descriptor=descriptor,
                named_state=named,
            )
            os.fsync(parent_fd)
            descriptor = None
            return created_custody
        except ExecutorContractError:
            raise
        except OSError as error:
            raise ExecutorContractError(
                "cannot create and bind run-root custody"
            ) from error
        finally:
            active_error = sys.exception()
            close_errors: list[BaseException] = []
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as error:
                    close_errors.append(error)
            if parent_fd is not None:
                try:
                    os.close(parent_fd)
                except BaseException as error:
                    close_errors.append(error)
            if close_errors:
                if created_custody is not None and descriptor is None:
                    try:
                        os.close(created_custody.descriptor)
                    except BaseException as error:
                        close_errors.append(error)
                    created_custody.descriptor = -1
                    created_custody.close_attempted = True
                raise _RunRootArtifactPersistenceError(
                    primary=active_error,
                    close_failures=close_errors,
                ) from (
                    active_error if active_error is not None else close_errors[0]
                )

    @classmethod
    def bind(cls, path: Path) -> _RunRootCustody:
        _require(
            os.name == "posix"
            and sys.platform.startswith("linux")
            and isinstance(path, Path)
            and path.is_absolute(),
            "run-root custody requires an absolute Linux path",
        )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        _require(
            nofollow != 0 and cloexec != 0 and directory != 0,
            "run-root no-follow custody is unavailable",
        )
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY | directory | nofollow | cloexec,
            )
            result = cls._from_open_descriptor(
                path=path,
                descriptor=descriptor,
            )
            descriptor = None
            return result
        except ExecutorContractError:
            raise
        except OSError as error:
            raise ExecutorContractError("cannot bind run-root custody") from error
        finally:
            active_error = sys.exception()
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as close_error:
                    raise _RunRootArtifactPersistenceError(
                        primary=active_error,
                        close_failures=[close_error],
                    ) from (
                        active_error if active_error is not None else close_error
                    )

    def _validate_directory_identity(self) -> None:
        try:
            held = os.fstat(self.descriptor)
            named = os.stat(self.path, follow_symlinks=False)
        except OSError as error:
            raise ExecutorContractError("cannot validate run-root custody") from error
        _require(
            _directory_identity(held) == self.identity
            and _directory_identity(named) == self.identity
            and stat.S_ISDIR(held.st_mode)
            and stat.S_IMODE(held.st_mode) == self.expected_directory_mode
            and held.st_uid == os.getuid()
            and held.st_gid == os.getgid()
            and _linux_fstatfs_magic(self.descriptor) == self.filesystem_magic,
            "run-root identity changed",
        )

    def validate(self) -> None:
        _require(
            not self.close_attempted and self.descriptor >= 0,
            "run-root custody is closed",
        )
        self._validate_directory_identity()

    def _validate_leaf(
        self,
        leaf: _RunRootLeafCustody,
        *,
        verify_payload: bool,
    ) -> None:
        try:
            held = os.fstat(leaf.descriptor)
            named = os.stat(
                leaf.name,
                dir_fd=self.descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            raise ExecutorContractError(
                "cannot validate held run-root leaf"
            ) from error
        held_identity = (
            int(held.st_dev),
            int(held.st_ino),
            int(held.st_mode),
            int(held.st_uid),
            int(held.st_gid),
            int(held.st_nlink),
            int(held.st_size),
        )
        named_identity = (
            int(named.st_dev),
            int(named.st_ino),
            int(named.st_mode),
            int(named.st_uid),
            int(named.st_gid),
            int(named.st_nlink),
            int(named.st_size),
        )
        _require(
            held_identity == leaf.identity
            and named_identity == leaf.identity
            and stat.S_ISREG(held.st_mode)
            and stat.S_IMODE(held.st_mode) == leaf.expected_mode
            and held.st_uid == os.getuid()
            and held.st_gid == os.getgid()
            and held.st_nlink == 1
            and held.st_size == leaf.size_bytes,
            "held run-root leaf identity changed",
        )
        if verify_payload:
            try:
                os.lseek(leaf.descriptor, 0, os.SEEK_SET)
                payload = bytearray()
                while len(payload) <= leaf.size_bytes:
                    chunk = os.read(
                        leaf.descriptor,
                        min(
                            1024 * 1024,
                            leaf.size_bytes + 1 - len(payload),
                        ),
                    )
                    if not chunk:
                        break
                    payload.extend(chunk)
            except OSError as error:
                raise ExecutorContractError(
                    "cannot reread held run-root leaf"
                ) from error
            _require(
                len(payload) == leaf.size_bytes
                and hashlib.sha256(payload).hexdigest() == leaf.sha256,
                "held run-root leaf payload changed",
            )

    def register_leaf(
        self,
        *,
        name: str,
        descriptor: int,
        identity: tuple[int, int, int, int, int, int, int],
        expected_mode: int,
        size_bytes: int,
        sha256: str,
    ) -> None:
        _require(
            not self.close_attempted
            and name in {ASSESSMENT_NAME, EXECUTION_FAILURE_DIAGNOSTIC_NAME}
            and name not in self.leaves
            and type(descriptor) is int
            and descriptor >= 0
            and type(identity) is tuple
            and len(identity) == 7
            and type(expected_mode) is int
            and type(size_bytes) is int
            and size_bytes >= 0
            and _SHA_RE.fullmatch(sha256) is not None,
            "run-root leaf registration drifted",
        )
        self.validate()
        leaf = _RunRootLeafCustody(
            name=name,
            descriptor=descriptor,
            identity=identity,
            expected_mode=expected_mode,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        self._validate_leaf(leaf, verify_payload=True)
        self.leaves[name] = leaf

    def close(self) -> None:
        _require(not self.close_attempted, "run-root custody close was retried")
        self.close_attempted = True
        primary_errors: list[BaseException] = []
        try:
            self._validate_directory_identity()
        except BaseException as error:
            primary_errors.append(error)
        for name in sorted(self.leaves):
            leaf = self.leaves[name]
            try:
                self._validate_leaf(leaf, verify_payload=True)
            except BaseException as error:
                primary_errors.append(error)
            try:
                os.fsync(leaf.descriptor)
            except BaseException as error:
                primary_errors.append(error)
        try:
            os.fsync(self.descriptor)
        except BaseException as error:
            primary_errors.append(error)
        try:
            self._validate_directory_identity()
        except BaseException as error:
            primary_errors.append(error)
        for name in sorted(self.leaves):
            try:
                self._validate_leaf(self.leaves[name], verify_payload=True)
            except BaseException as error:
                primary_errors.append(error)
        close_errors: list[BaseException] = []
        for name in sorted(self.leaves):
            leaf = self.leaves[name]
            try:
                os.close(leaf.descriptor)
            except BaseException as error:
                close_errors.append(error)
            leaf.descriptor = -1
        try:
            os.close(self.descriptor)
        except BaseException as error:
            close_errors.append(error)
        self.descriptor = -1
        if primary_errors or close_errors:
            raise _RunRootArtifactPersistenceError(
                primary=primary_errors[0] if primary_errors else None,
                close_failures=[*primary_errors[1:], *close_errors],
            ) from (primary_errors[0] if primary_errors else close_errors[0])


@dataclass
class _ExecutionAttemptContext:
    run_id: str
    run_identity: str
    role: str
    requests: Sequence[Mapping[str, object]]
    phase: str = "mutating_preworker"
    stage: str = "stale_reaper"
    branch: str | None = None
    mutating_phase_entered: bool = False
    progress: _ExecutionProgressLedger | None = None
    progress_snapshot: Mapping[str, object] | None = None
    progress_close_attempted: bool = False
    run_root: Path | None = None
    run_root_custody: _RunRootCustody | None = None
    supplemental_failures: list[_SupplementalExecutionFailure] = field(
        default_factory=list
    )
    runtime_cleanup_observation: Mapping[str, object] | None = None
    assessment_persistence: dict[str, object] = field(
        default_factory=lambda: {
            "attempted": False,
            "write_returned": False,
            "commit_attested": False,
            "state": "not_started",
        }
    )

    def __post_init__(self) -> None:
        _require(
            _RUN_ID_RE.fullmatch(self.run_id) is not None
            and _SHA_RE.fullmatch(self.run_identity) is not None
            and self.role in {"secondary", "sensitivity"}
            and len(self.requests) == 8,
            "execution attempt context drifted",
        )

    def mark(
        self,
        phase: str,
        stage: str,
        *,
        branch: str | None = None,
    ) -> None:
        _require(
            phase in _EXECUTION_FAILURE_PHASES
            and stage in _EXECUTION_FAILURE_STAGES
            and (branch is None or branch in BRANCHES),
            "execution attempt stage drifted",
        )
        self.phase = phase
        self.stage = stage
        self.branch = branch
        self.mutating_phase_entered = True

    def bind_progress(self, progress: _ExecutionProgressLedger) -> None:
        _require(
            self.progress is None
            and type(progress) is _ExecutionProgressLedger
            and progress.run_id == self.run_id
            and progress.run_identity == self.run_identity
            and progress.role == self.role,
            "execution attempt progress binding drifted",
        )
        self.progress = progress

    def bind_run_root(
        self,
        run_root: Path,
        custody: _RunRootCustody | None = None,
    ) -> None:
        _require(
            self.run_root is None
            and isinstance(run_root, Path)
            and run_root.is_absolute(),
            "execution attempt run-root binding drifted",
        )
        self.run_root = run_root
        if os.name == "posix" and sys.platform.startswith("linux"):
            _require(
                type(custody) is _RunRootCustody
                and custody.path == run_root
                and not custody.close_attempted,
                "execution attempt created run-root custody drifted",
            )
            self.run_root_custody = custody
            custody.validate()
        else:
            _require(custody is None, "non-Linux run-root custody drifted")

    def close_run_root(self) -> None:
        if (
            self.run_root_custody is not None
            and not self.run_root_custody.close_attempted
        ):
            try:
                self.run_root_custody.close()
            except BaseException as error:
                try:
                    self.record_cleanup_failure(
                        scope="run_root_closure",
                        stage="run_root_closure",
                        error=error,
                    )
                except BaseException as recording_error:
                    self.supplemental_failures.append(
                        _SupplementalExecutionFailure(
                            scope="run_root_closure",
                            phase="final_cleanup",
                            stage="run_root_closure",
                            branch=None,
                            error=_DescriptorClosureError(
                                operation="run_root_closure_failure_recording",
                                primary=error,
                                close_failures=[recording_error],
                            ),
                        )
                    )

    def record_cleanup_failure(
        self,
        *,
        scope: str,
        stage: str,
        error: BaseException,
        branch: str | None = None,
        phase: str = "final_cleanup",
    ) -> None:
        item = _SupplementalExecutionFailure(
            scope=scope,
            phase=phase,
            stage=stage,
            branch=branch,
            error=error,
        )
        if not any(
            current.scope == item.scope
            and current.phase == item.phase
            and current.stage == item.stage
            and current.branch == item.branch
            and current.error is item.error
            for current in self.supplemental_failures
        ):
            self.supplemental_failures.append(item)

    def record_runtime_cleanup_observation(
        self,
        value: Mapping[str, object],
    ) -> None:
        facts = dict(_mapping(value, "runtime cleanup observation"))
        _require(
            self.runtime_cleanup_observation is None
            and set(facts)
            == {
                "schema_version",
                "policy_id",
                "attempted",
                "docker_observation_available",
                "unresolved_operation_observation_available",
                "complete_attestation",
                "docker",
                "unresolved_operations",
            }
            and facts.get("schema_version") == 1
            and facts.get("policy_id")
            == "failure_safe_owned_runtime_poststate_v1"
            and all(
                type(facts[key]) is bool
                for key in (
                    "attempted",
                    "docker_observation_available",
                    "unresolved_operation_observation_available",
                    "complete_attestation",
                )
            ),
            "runtime cleanup observation schema drifted",
        )
        canonical_line(facts)
        self.runtime_cleanup_observation = facts

    def runtime_cleanup_facts(self) -> dict[str, object]:
        return dict(
            self.runtime_cleanup_observation
            if self.runtime_cleanup_observation is not None
            else _runtime_cleanup_observation(
                attempted=False,
                docker=None,
                unresolved_operations=None,
            )
        )

    def _safe_progress_failure_summary(
        self,
        ledger: _ExecutionProgressLedger,
        error: BaseException,
    ) -> tuple[dict[str, object], tuple[BaseException, ...]]:
        projection_errors: list[BaseException] = []
        try:
            return ledger.failure_summary(error), ()
        except BaseException as projection_error:
            projection_errors.append(projection_error)
        combined = _DescriptorClosureError(
            operation="execution_progress_failure_projection",
            primary=error,
            close_failures=projection_errors,
            message="execution progress failure projection failed",
        )
        try:
            return _ExecutionProgressLedger.failure_summary(ledger, combined), tuple(
                projection_errors
            )
        except BaseException as fallback_error:
            projection_errors.append(fallback_error)
        durable = getattr(ledger, "_progress_root", None) is not None
        return (
            {
                "expected_response_count": 8,
                "dispatched_checkpoint_count": 0,
                "client_returned_checkpoint_count": 0,
                "validated_checkpoint_count": 0,
                "dispatched_request_ids": [],
                "client_returned_request_ids": [],
                "validated_request_ids": [],
                "checkpoint_sha256s": [],
                "checkpoint_records": [],
                "persistence": {
                    "mode": (
                        "durable_o_excl_fsync"
                        if durable
                        else "synthetic_in_memory"
                    ),
                    "relative_directory": "runtime_progress" if durable else None,
                    "file_count": 0,
                    "filesystem_magic": getattr(ledger, "_filesystem_magic", None),
                    "requested_file_mode": "0400" if durable else None,
                    "effective_file_mode": (
                        f"{getattr(ledger, '_expected_file_mode'):04o}"
                        if getattr(ledger, "_expected_file_mode", None) is not None
                        else None
                    ),
                    "integrity_attested": False,
                    "closure_error_sha256": hashlib.sha256(
                        str(combined).encode("utf-8")
                    ).hexdigest(),
                },
                "chain_head_sha256": None,
                "handshake_checkpoint_count": 0,
                "four_party_barrier_released": False,
                "inference_performed": None,
                "inference_performed_attested": False,
                "all_inferences_completed": False,
            },
            tuple(projection_errors),
        )

    def snapshot_progress(self) -> Mapping[str, object]:
        if self.progress_snapshot is None:
            if self.progress is None:
                synthetic = _ExecutionProgressLedger(
                    run_root=None,
                    run_id=self.run_id,
                    run_identity=self.run_identity,
                    role=self.role,
                    requests=self.requests,
                )
                summary_error: BaseException | None = None
                try:
                    self.progress_snapshot = synthetic.summary()
                except BaseException as error:
                    summary_error = error
                close_error: BaseException | None = None
                try:
                    synthetic.close()
                except BaseException as error:
                    close_error = error
                if summary_error is not None or close_error is not None:
                    failures = [
                        item
                        for item in (summary_error, close_error)
                        if item is not None
                    ]
                    combined = _DescriptorClosureError(
                        operation="synthetic_execution_progress",
                        primary=summary_error,
                        close_failures=(
                            [close_error] if close_error is not None else []
                        ),
                    )
                    facts, projection_errors = self._safe_progress_failure_summary(
                        synthetic,
                        combined,
                    )
                    self.progress_snapshot = facts
                    for error in (*failures, *projection_errors):
                        self.record_cleanup_failure(
                            scope="progress_closure",
                            stage="progress_closure",
                            error=error,
                        )
            else:
                try:
                    self.progress_snapshot = self.progress.summary()
                except BaseException as error:
                    facts, projection_errors = self._safe_progress_failure_summary(
                        self.progress,
                        error,
                    )
                    self.progress_snapshot = facts
                    self.record_cleanup_failure(
                        scope="progress_closure",
                        stage="progress_closure",
                        error=error,
                    )
                    for projection_error in projection_errors:
                        self.record_cleanup_failure(
                            scope="progress_closure",
                            stage="progress_closure",
                            error=projection_error,
                        )
        return dict(self.progress_snapshot)

    def close_progress(self) -> None:
        if self.progress is not None and not self.progress_close_attempted:
            self.progress_close_attempted = True
            try:
                self.progress.close()
            except BaseException as error:
                facts, projection_errors = self._safe_progress_failure_summary(
                    self.progress,
                    error,
                )
                self.progress_snapshot = facts
                self.record_cleanup_failure(
                    scope="progress_closure",
                    stage="progress_closure",
                    error=error,
                )
                for projection_error in projection_errors:
                    self.record_cleanup_failure(
                        scope="progress_closure",
                        stage="progress_closure",
                        error=projection_error,
                    )

    def finalize_progress(self) -> None:
        _require(
            self.progress is not None and not self.progress_close_attempted,
            "execution progress finalization state drifted",
        )
        self.progress_close_attempted = True
        try:
            self.progress.close()
        except BaseException as error:
            facts, projection_errors = self._safe_progress_failure_summary(
                self.progress,
                error,
            )
            self.progress_snapshot = facts
            if projection_errors:
                raise _DescriptorClosureError(
                    operation="execution_progress_finalization",
                    primary=error,
                    close_failures=projection_errors,
                ) from error
            raise

    def bundle_failure(self, error: BaseException) -> BaseException:
        if isinstance(error, _ExecutionFailureBundle):
            primary = error.primary
            primary_phase = error.primary_phase
            primary_stage = error.primary_stage
            primary_branch = error.primary_branch
            supplemental = [
                *error.supplemental_failures,
                *self.supplemental_failures,
            ]
        else:
            primary = error
            primary_phase = self.phase
            primary_stage = self.stage
            primary_branch = self.branch
            supplemental = list(self.supplemental_failures)
        if not supplemental:
            return error
        return _ExecutionFailureBundle(
            primary=primary,
            primary_phase=primary_phase,
            primary_stage=primary_stage,
            primary_branch=primary_branch,
            supplemental_failures=supplemental,
        )

    def assessment_write_started(self) -> None:
        _require(
            self.assessment_persistence["state"] == "not_started",
            "assessment persistence state drifted",
        )
        self.assessment_persistence = {
            "attempted": True,
            "write_returned": False,
            "commit_attested": False,
            "state": "ambiguous",
        }

    def assessment_write_returned(self) -> None:
        _require(
            self.assessment_persistence["state"] == "ambiguous",
            "assessment persistence completion drifted",
        )
        self.assessment_persistence = {
            "attempted": True,
            "write_returned": True,
            "commit_attested": False,
            "state": "write_returned_commit_unattested",
        }


class _BoundedCommandRunner:
    """POSIX-only shell-free runner with bounded concurrent raw captures."""

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandCapture:
        _require(
            os.name == "posix"
            and type(argv) is list
            and bool(argv)
            and all(type(item) is str and item and "\0" not in item for item in argv),
            "bounded command argv is invalid",
        )
        _require(
            type(timeout_seconds) in {int, float}
            and 0 < timeout_seconds <= 300
            and type(stdout_limit) is int
            and 0 <= stdout_limit <= 16 * 1024 * 1024
            and type(stderr_limit) is int
            and 0 <= stderr_limit <= 16 * 1024 * 1024,
            "bounded command limits are invalid",
        )
        process: subprocess.Popen[bytes] | None = None
        selector = selectors.DefaultSelector()
        captures = {"stdout": bytearray(), "stderr": bytearray()}
        limits = {"stdout": stdout_limit, "stderr": stderr_limit}
        primary: BaseException | None = None
        cleanup_errors: list[BaseException] = []
        result: CommandCapture | None = None
        try:
            process = subprocess.Popen(
                argv,
                shell=False,
                env={},
                cwd="/",
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
            )
            _require(process.stdout is not None and process.stderr is not None, "bounded command pipes are unavailable")
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            deadline = time.monotonic() + float(timeout_seconds)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExecutorContractError("bounded command timed out")
                for key, _mask in selector.select(min(remaining, 0.1)):
                    name = str(key.data)
                    try:
                        chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if len(captures[name]) + len(chunk) > limits[name]:
                        raise ExecutorContractError(f"bounded command {name} overflowed")
                    captures[name].extend(chunk)
                if process.poll() is not None and not selector.get_map():
                    break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExecutorContractError("bounded command timed out")
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise ExecutorContractError("bounded command timed out") from error
            result = CommandCapture(
                returncode=int(returncode),
                stdout=bytes(captures["stdout"]),
                stderr=bytes(captures["stderr"]),
            )
        except BaseException as error:
            primary = error
            process_running = False
            if process is not None:
                try:
                    process_running = process.poll() is None
                except BaseException as poll_error:
                    cleanup_errors.append(poll_error)
                    process_running = True
            if process is not None and process_running:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except BaseException as terminate_error:
                    cleanup_errors.append(terminate_error)
                try:
                    process.wait(timeout=1.0)
                except BaseException as terminate_wait_error:
                    cleanup_errors.append(terminate_wait_error)
                    still_running = True
                    try:
                        still_running = process.poll() is None
                    except BaseException as poll_error:
                        cleanup_errors.append(poll_error)
                    if still_running:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except BaseException as kill_error:
                            cleanup_errors.append(kill_error)
                        try:
                            process.wait(timeout=5.0)
                        except BaseException as kill_wait_error:
                            cleanup_errors.append(kill_wait_error)
            if process is not None:
                # Never return command custody while the separate-session
                # process can still mutate Docker state.  TERM/KILL and their
                # bounded waits are diagnostic attempts; only an exact poll
                # or wait return is terminal authority.  Persistent inability
                # to prove termination intentionally hard-walls under the
                # outer one-shot launcher instead of permitting a late create
                # to race watchdog/name-absence cleanup.
                process_terminal_attested = False
                while not process_terminal_attested:
                    try:
                        observed_returncode = process.poll()
                    except BaseException as poll_error:
                        cleanup_errors.append(poll_error)
                    else:
                        if type(observed_returncode) is int:
                            process_terminal_attested = True
                            break
                    try:
                        observed_returncode = process.wait()
                        _require(
                            type(observed_returncode) is int,
                            "bounded command terminal wait returned no status",
                        )
                        process_terminal_attested = True
                    except BaseException as terminal_wait_error:
                        cleanup_errors.append(terminal_wait_error)
                    if process_terminal_attested:
                        break
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except BaseException as kill_error:
                        cleanup_errors.append(kill_error)
                    try:
                        time.sleep(0.05)
                    except BaseException as sleep_error:
                        cleanup_errors.append(sleep_error)
        finally:
            try:
                selector.close()
            except BaseException as error:
                cleanup_errors.append(error)
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as error:
                            cleanup_errors.append(error)
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="bounded_command_runner",
                primary=primary,
                close_failures=cleanup_errors,
                message="bounded command execution or cleanup failed",
            ) from (primary if primary is not None else cleanup_errors[0])
        if primary is not None:
            raise primary
        _require(result is not None, "bounded command result is unavailable")
        return result


class _ContainerWatchdog(Protocol):
    def mark_create_dispatch(self) -> None: ...

    def mark_create_terminal(self) -> None: ...

    def complete(self) -> None: ...

    def abort(self) -> None: ...

    def detach_ambiguous_owner(self) -> None: ...


class _NullContainerWatchdog:
    """Test-only synchronous sentinel; default execution never uses it."""

    def mark_create_dispatch(self) -> None:
        return None

    def mark_create_terminal(self) -> None:
        return None

    def complete(self) -> None:
        return None

    def abort(self) -> None:
        return None

    def detach_ambiguous_owner(self) -> None:
        return None


class _NullCleanupMutex:
    """Explicit test-only mutex; no production callsite may construct it."""

    @contextmanager
    def hold(self) -> Any:
        yield

    def close(self) -> None:
        return None


class _NullRunLease:
    """Explicit synthetic-test lease; default execution never constructs it."""

    contract: Mapping[str, object] = {"synthetic_test_only": True}

    def release(self) -> None:
        return None


@dataclass
class _RunLease:
    contract: Mapping[str, object]
    parent_fd: int
    identity_fd: int
    admission_fd: int
    retention_fd: int
    unresolved_root_fd: int
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        primary: BaseException | None = None
        try:
            _validate_run_lease_held(
                self.contract,
                parent_fd=self.parent_fd,
                identity_fd=self.identity_fd,
                admission_fd=self.admission_fd,
                retention_fd=self.retention_fd,
                unresolved_root_fd=self.unresolved_root_fd,
            )
        except BaseException as error:
            primary = error
        close_failures: list[BaseException] = []
        try:
            import fcntl
        except BaseException as error:
            close_failures.append(error)
            fcntl = None  # type: ignore[assignment]
        for field_name in (
            "retention_fd",
            "admission_fd",
            "identity_fd",
        ):
            descriptor = getattr(self, field_name)
            setattr(self, field_name, -1)
            if fcntl is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except BaseException as error:
                    close_failures.append(error)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        parent_fd = self.parent_fd
        self.parent_fd = -1
        unresolved_root_fd = self.unresolved_root_fd
        self.unresolved_root_fd = -1
        try:
            os.close(unresolved_root_fd)
        except BaseException as error:
            close_failures.append(error)
        try:
            os.close(parent_fd)
        except BaseException as error:
            close_failures.append(error)
        if primary is not None or close_failures:
            raise _DescriptorClosureError(
                operation="run_lease_release",
                primary=primary,
                close_failures=close_failures,
            ) from (primary if primary is not None else close_failures[0])

    def create_unresolved_container_marker(
        self,
        *,
        container_name: str,
    ) -> _UnresolvedOperationMarkerReservation:
        _require(not self.released, "run lease is already released")
        return _create_unresolved_operation_marker(
            run_lease=self,
            operation_kind="container_create",
            operation_id=container_name,
        )

    def create_unresolved_ipc_marker(
        self,
        *,
        parent: Path,
    ) -> _UnresolvedOperationMarkerReservation:
        _require(not self.released, "run lease is already released")
        run_identity = str(
            _mapping(self.contract, "run lease contract").get(
                "run_identity_sha256"
            )
        )
        return _create_unresolved_operation_marker(
            run_lease=self,
            operation_kind="ipc_namespace",
            operation_id=_ipc_unresolved_operation_id(
                run_identity,
                parent=parent,
            ),
        )


@dataclass
class _RunRetentionHold:
    contract: Mapping[str, object]
    parent_fd: int
    retention_fd: int
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        primary: BaseException | None = None
        try:
            _validate_run_retention_hold(
                self.contract,
                parent_fd=self.parent_fd,
                retention_fd=self.retention_fd,
            )
        except BaseException as error:
            primary = error
        close_failures: list[BaseException] = []
        try:
            import fcntl

            fcntl.flock(self.retention_fd, fcntl.LOCK_UN)
        except BaseException as error:
            close_failures.append(error)
        for field_name in ("retention_fd", "parent_fd"):
            descriptor = getattr(self, field_name)
            setattr(self, field_name, -1)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if primary is not None or close_failures:
            raise _DescriptorClosureError(
                operation="run_retention_hold_release",
                primary=primary,
                close_failures=close_failures,
            ) from (primary if primary is not None else close_failures[0])


@dataclass
class _UnresolvedOperationMarkerReservation:
    contract: Mapping[str, object]
    root_fd: int
    marker_fd: int
    closed: bool = False
    resolved: bool = False

    def resolve(self) -> None:
        _require(
            not self.closed and not self.resolved,
            "unresolved operation marker reservation is already closed",
        )
        _durably_resolve_unresolved_operation_marker(
            self.contract,
            root_fd=self.root_fd,
            marker_fd=self.marker_fd,
        )
        self.resolved = True

    def close(self) -> None:
        """Close controller duplicates without resolving the durable marker."""

        if self.closed:
            return
        self.closed = True
        primary: BaseException | None = None
        if not self.resolved:
            try:
                _validate_unresolved_operation_marker(
                    self.contract,
                    root_fd=self.root_fd,
                    marker_fd=self.marker_fd,
                    require_named=True,
                )
            except BaseException as error:
                primary = error
        close_failures: list[BaseException] = []
        for field_name in ("marker_fd", "root_fd"):
            descriptor = getattr(self, field_name)
            setattr(self, field_name, -1)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if primary is not None or close_failures:
            raise _DescriptorClosureError(
                operation="unresolved_operation_marker_reservation_close",
                primary=primary,
                close_failures=close_failures,
            ) from (primary if primary is not None else close_failures[0])


@dataclass
class _UnresolvedOperationMarkerHold:
    contract: Mapping[str, object]
    root_fd: int
    marker_fd: int
    closed: bool = False
    resolved: bool = False

    def resolve(self) -> None:
        _require(
            not self.closed and not self.resolved,
            "unresolved operation marker is already closed",
        )
        _durably_resolve_unresolved_operation_marker(
            self.contract,
            root_fd=self.root_fd,
            marker_fd=self.marker_fd,
        )
        self.resolved = True

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        primary: BaseException | None = None
        if not self.resolved:
            try:
                _validate_unresolved_operation_marker(
                    self.contract,
                    root_fd=self.root_fd,
                    marker_fd=self.marker_fd,
                    require_named=True,
                )
            except BaseException as error:
                primary = error
        close_failures: list[BaseException] = []
        for field_name in ("marker_fd", "root_fd"):
            descriptor = getattr(self, field_name)
            setattr(self, field_name, -1)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if primary is not None or close_failures:
            raise _DescriptorClosureError(
                operation="unresolved_operation_marker_hold_close",
                primary=primary,
                close_failures=close_failures,
            ) from (primary if primary is not None else close_failures[0])


def _cleanup_mutex_path(
    run_identity: str,
    *,
    parent: Path = CLEANUP_MUTEX_PARENT,
) -> Path:
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and isinstance(parent, Path)
        and parent.is_absolute()
        and ".." not in PurePosixPath(str(parent)).parts,
        "cleanup mutex path identity drifted",
    )
    digest = hashlib.sha256(
        CLEANUP_MUTEX_PATH_DOMAIN + run_identity.encode("ascii")
    ).hexdigest()[:48]
    return parent / f"{_CLEANUP_MUTEX_NAME_PREFIX}{digest}"


def _cleanup_mutex_parent_record(value: os.stat_result) -> dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "uid": int(value.st_uid),
        "gid": int(value.st_gid),
    }


def _cleanup_mutex_file_record(value: os.stat_result) -> dict[str, int]:
    return {
        **_cleanup_mutex_parent_record(value),
        "nlink": int(value.st_nlink),
        "size_bytes": int(value.st_size),
    }


def _cleanup_mutex_contract(
    *,
    run_identity: str,
    path: Path,
    filesystem_magic: int,
    parent_state: os.stat_result,
    mutex_state: os.stat_result,
) -> dict[str, object]:
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_v2_nonpublication_cleanup_mutex_v1",
        "run_identity_sha256": run_identity,
        "parent_path": str(path.parent),
        "path": str(path),
        "name": path.name,
        "filesystem_magic": filesystem_magic,
        "parent_identity": _cleanup_mutex_parent_record(parent_state),
        "mutex_identity": _cleanup_mutex_file_record(mutex_state),
    }
    return {
        **core,
        "cleanup_mutex_contract_sha256": hashlib.sha256(
            CLEANUP_MUTEX_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }


def _validate_cleanup_mutex_contract(
    value: Mapping[str, object],
) -> dict[str, object]:
    contract = dict(_mapping(value, "cleanup mutex contract"))
    _require(
        set(contract)
        == {
            "schema_version",
            "artifact_kind",
            "run_identity_sha256",
            "parent_path",
            "path",
            "name",
            "filesystem_magic",
            "parent_identity",
            "mutex_identity",
            "cleanup_mutex_contract_sha256",
        }
        and contract.get("schema_version") == 1
        and contract.get("artifact_kind")
        == "vast_kpp_v2_nonpublication_cleanup_mutex_v1",
        "cleanup mutex contract fields drifted",
    )
    claimed = contract.pop("cleanup_mutex_contract_sha256")
    _require(
        type(claimed) is str
        and _SHA_RE.fullmatch(claimed) is not None
        and claimed
        == hashlib.sha256(
            CLEANUP_MUTEX_DOMAIN + canonical_line(contract)
        ).hexdigest(),
        "cleanup mutex contract identity drifted",
    )
    run_identity = contract.get("run_identity_sha256")
    parent_path = contract.get("parent_path")
    path = contract.get("path")
    name = contract.get("name")
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and type(parent_path) is str
        and PurePosixPath(parent_path).is_absolute()
        and ".." not in PurePosixPath(parent_path).parts
        and type(path) is str
        and type(name) is str
        and _cleanup_mutex_path(
            run_identity,
            parent=Path(parent_path),
        )
        == Path(path)
        and Path(path).name == name
        and contract.get("filesystem_magic") == _LINUX_EXT_FILESYSTEM_MAGIC,
        "cleanup mutex contract path or filesystem drifted",
    )
    parent_identity = dict(
        _mapping(contract.get("parent_identity"), "cleanup mutex parent identity")
    )
    mutex_identity = dict(
        _mapping(contract.get("mutex_identity"), "cleanup mutex file identity")
    )
    _require(
        set(parent_identity) == {"device", "inode", "mode", "uid", "gid"}
        and set(mutex_identity)
        == {"device", "inode", "mode", "uid", "gid", "nlink", "size_bytes"}
        and all(type(item) is int for item in parent_identity.values())
        and all(type(item) is int for item in mutex_identity.values())
        and stat.S_ISDIR(parent_identity["mode"])
        and stat.S_IMODE(parent_identity["mode"]) == 0o1777
        and parent_identity["uid"] == 0
        and parent_identity["gid"] == 0
        and stat.S_ISREG(mutex_identity["mode"])
        and stat.S_IMODE(mutex_identity["mode"]) == 0o600
        and mutex_identity["uid"] == os.getuid()
        and mutex_identity["gid"] == os.getgid()
        and mutex_identity["nlink"] == 1
        and mutex_identity["size_bytes"] == 0,
        "cleanup mutex object identity drifted",
    )
    return {
        **contract,
        "parent_identity": parent_identity,
        "mutex_identity": mutex_identity,
        "cleanup_mutex_contract_sha256": claimed,
    }


def _cleanup_mutex_state_matches(
    record: Mapping[str, object],
    value: os.stat_result,
) -> bool:
    return (
        dict(record) == _cleanup_mutex_file_record(value)
        and stat.S_ISREG(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_uid == os.getuid()
        and value.st_gid == os.getgid()
        and value.st_nlink == 1
        and value.st_size == 0
    )


@contextmanager
def _hold_cleanup_mutex_contract(
    raw_contract: Mapping[str, object],
) -> Any:
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "cleanup mutex requires Linux",
    )
    try:
        import fcntl
    except ImportError as error:
        raise ExecutorContractError("cleanup mutex flock is unavailable") from error
    contract = _validate_cleanup_mutex_contract(raw_contract)
    parent_path = Path(str(contract["parent_path"]))
    name = str(contract["name"])
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and directory != 0 and cloexec != 0,
        "cleanup mutex no-follow custody is unavailable",
    )
    parent_fd: int | None = None
    descriptor: int | None = None
    locked = False
    try:
        parent_fd = os.open(
            parent_path,
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        descriptor = os.open(
            name,
            os.O_RDWR | nofollow | cloexec,
            dir_fd=parent_fd,
        )

        def validate() -> None:
            try:
                parent_handle = os.fstat(parent_fd)
                parent_named = os.stat(parent_path, follow_symlinks=False)
                mutex_handle = os.fstat(descriptor)
                mutex_named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as error:
                raise ExecutorContractError(
                    "cannot validate cleanup mutex custody"
                ) from error
            _require(
                _cleanup_mutex_parent_record(parent_handle)
                == _cleanup_mutex_parent_record(parent_named)
                == contract["parent_identity"]
                and _cleanup_mutex_state_matches(
                    _mapping(contract["mutex_identity"], "cleanup mutex identity"),
                    mutex_handle,
                )
                and _cleanup_mutex_state_matches(
                    _mapping(contract["mutex_identity"], "cleanup mutex identity"),
                    mutex_named,
                )
                and _linux_fstatfs_magic(parent_fd)
                == contract["filesystem_magic"],
                "cleanup mutex custody drifted",
            )

        validate()
        deadline = time.monotonic() + _CLEANUP_MUTEX_ACQUIRE_SECONDS
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                _require(
                    time.monotonic() < deadline,
                    "cleanup mutex acquisition timed out",
                )
                time.sleep(0.01)
        validate()
        try:
            yield
        except BaseException as body_error:
            try:
                validate()
            except BaseException as validation_error:
                raise _DescriptorClosureError(
                    operation="cleanup_mutex_body_and_final_validation",
                    primary=body_error,
                    close_failures=[validation_error],
                ) from body_error
            raise
        else:
            validate()
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError("cleanup mutex operation failed") from error
    finally:
        active_error = sys.exception()
        close_failures: list[BaseException] = []
        if descriptor is not None:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except BaseException as error:
                    close_failures.append(error)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_failures.append(error)
        if close_failures:
            raise _DescriptorClosureError(
                operation="cleanup_mutex_hold",
                primary=active_error,
                close_failures=close_failures,
            ) from (
                active_error if active_error is not None else close_failures[0]
            )


@dataclass
class _CleanupMutexReservation:
    contract: Mapping[str, object]
    parent_fd: int
    descriptor: int
    closed: bool = False

    def hold(self) -> Any:
        _require(not self.closed, "cleanup mutex reservation is closed")
        return _hold_cleanup_mutex_contract(self.contract)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        primary: BaseException | None = None
        try:
            with _hold_cleanup_mutex_contract(self.contract):
                pass
        except BaseException as error:
            primary = error
        close_failures: list[BaseException] = []
        for field_name in ("descriptor", "parent_fd"):
            descriptor = getattr(self, field_name)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
            finally:
                setattr(self, field_name, -1)
        if primary is not None or close_failures:
            raise _DescriptorClosureError(
                operation="cleanup_mutex_final_closure",
                primary=primary,
                close_failures=close_failures,
            ) from (primary if primary is not None else close_failures[0])


@dataclass(frozen=True)
class _CleanupMutexReference:
    contract: Mapping[str, object]

    def hold(self) -> Any:
        return _hold_cleanup_mutex_contract(self.contract)


def _cleanup_mutex_contract_from_actor(value: Any) -> dict[str, object]:
    contract = getattr(value, "contract", None)
    _require(
        isinstance(contract, Mapping),
        "cleanup mutex actor contract is unavailable",
    )
    return _validate_cleanup_mutex_contract(contract)


def _create_cleanup_mutex(run_identity: str) -> _CleanupMutexReservation:
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "cleanup mutex creation requires Linux",
    )
    path = _cleanup_mutex_path(run_identity)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and directory != 0 and cloexec != 0,
        "cleanup mutex creation custody is unavailable",
    )
    parent_fd: int | None = None
    descriptor: int | None = None
    try:
        parent_fd = os.open(
            path.parent,
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        parent_state = os.fstat(parent_fd)
        parent_named = os.stat(path.parent, follow_symlinks=False)
        _require(
            _cleanup_mutex_parent_record(parent_state)
            == _cleanup_mutex_parent_record(parent_named)
            and stat.S_ISDIR(parent_state.st_mode)
            and stat.S_IMODE(parent_state.st_mode) == 0o1777
            and parent_state.st_uid == 0
            and parent_state.st_gid == 0
            and _linux_fstatfs_magic(parent_fd) == _LINUX_EXT_FILESYSTEM_MAGIC,
            "cleanup mutex parent custody drifted",
        )
        descriptor = os.open(
            path.name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow | cloexec,
            0o600,
            dir_fd=parent_fd,
        )
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.fsync(parent_fd)
        mutex_state = os.fstat(descriptor)
        mutex_named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            _cleanup_mutex_file_record(mutex_state)
            == _cleanup_mutex_file_record(mutex_named)
            and stat.S_ISREG(mutex_state.st_mode)
            and stat.S_IMODE(mutex_state.st_mode) == 0o600
            and mutex_state.st_uid == os.getuid()
            and mutex_state.st_gid == os.getgid()
            and mutex_state.st_nlink == 1
            and mutex_state.st_size == 0,
            "cleanup mutex file custody drifted",
        )
        contract = _cleanup_mutex_contract(
            run_identity=run_identity,
            path=path,
            filesystem_magic=_LINUX_EXT_FILESYSTEM_MAGIC,
            parent_state=parent_state,
            mutex_state=mutex_state,
        )
        with _hold_cleanup_mutex_contract(contract):
            pass
        reservation = _CleanupMutexReservation(
            contract=_validate_cleanup_mutex_contract(contract),
            parent_fd=parent_fd,
            descriptor=descriptor,
        )
        parent_fd = None
        descriptor = None
        return reservation
    except FileExistsError as error:
        raise ExecutorContractError(
            "cleanup mutex persistent one-shot path already exists"
        ) from error
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError("cannot create cleanup mutex") from error
    finally:
        active_error = sys.exception()
        close_failures: list[BaseException] = []
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_failures.append(error)
        if close_failures:
            raise _DescriptorClosureError(
                operation="cleanup_mutex_creation",
                primary=active_error,
                close_failures=close_failures,
            ) from (
                active_error if active_error is not None else close_failures[0]
            )


@dataclass
class _OwnedContainerRegistry:
    run_identity: str
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _by_name: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        _require(
            type(self.run_identity) is str
            and _SHA_RE.fullmatch(self.run_identity) is not None,
            "owned container registry identity drifted",
        )

    @property
    def expected_names(self) -> tuple[str, ...]:
        prefix = f"vast-kpp-v2-np-{self.run_identity[:16]}-"
        return (
            f"{prefix}probe",
            *(f"{prefix}{branch}" for branch in BRANCHES),
        )

    def record(self, container_name: str, container_id: str) -> None:
        with self._lock:
            _require(
                container_name in self.expected_names
                and type(container_id) is str
                and _CONTAINER_ID_RE.fullmatch(container_id) is not None
                and (
                    container_name not in self._by_name
                    or self._by_name[container_name] == container_id
                )
                and container_id
                not in {
                    item
                    for name, item in self._by_name.items()
                    if name != container_name
                },
                "owned container registry record drifted",
            )
            self._by_name[container_name] = container_id

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(sorted(self._by_name.items()))


def _finalize_owned_container_cleanup(
    *,
    runner: CommandRunner,
    cleanup_mutex: Any,
    container_registry: _OwnedContainerRegistry,
    require_complete_registry: bool = True,
) -> dict[str, object]:
    """Bind all five owned IDs to exact absence under the global mutex."""

    _require(
        type(container_registry) is _OwnedContainerRegistry,
        "owned-container final registry type drifted",
    )
    _require(
        type(require_complete_registry) is bool,
        "owned-container final registry policy drifted",
    )
    snapshot = container_registry.snapshot()
    failures: list[BaseException] = []
    coverage_exact = (
        tuple(snapshot) == tuple(sorted(container_registry.expected_names))
        and len(snapshot) == 5
        and len(set(snapshot.values())) == 5
        and all(
            type(item) is str and _CONTAINER_ID_RE.fullmatch(item) is not None
            for item in snapshot.values()
        )
    )
    if require_complete_registry and not coverage_exact:
        failures.append(
            ExecutorContractError(
                "owned-container final registry coverage drifted"
            )
        )
    hold = getattr(cleanup_mutex, "hold", None)
    _require(callable(hold), "cleanup mutex interface drifted")
    inspect_facts: list[dict[str, object]] = []
    listing: CommandCapture | None = None
    final_catalog_facts: dict[str, object] | None = None
    with hold():
        seen_ids: set[str] = set()

        def inspect_reference(
            *,
            container_name: str,
            container_id: str | None,
            reference_kind: str,
            reference: str,
        ) -> None:
            try:
                capture = _container_inspect_capture(runner, reference)
            except BaseException as error:
                failures.append(error)
                return
            if not _is_exact_container_not_found(capture, reference):
                failures.append(
                    _DockerOperationError(
                        "owned Docker final inspect did not prove exact absence",
                        stage="final_owned_container_cleanup",
                        command_class="container_inspect",
                        capture=capture,
                    )
                )
                return
            valid_container_id = (
                container_id
                if type(container_id) is str
                and _CONTAINER_ID_RE.fullmatch(container_id) is not None
                else None
            )
            inspect_facts.append(
                {
                    "container_name": container_name,
                    "container_id_sha256": (
                        hashlib.sha256(
                            valid_container_id.encode("ascii")
                        ).hexdigest()
                        if valid_container_id is not None
                        else None
                    ),
                    "reference_kind": reference_kind,
                    "returncode": capture.returncode,
                    "stdout_size_bytes": len(capture.stdout),
                    "stdout_sha256": hashlib.sha256(capture.stdout).hexdigest(),
                    "stderr_size_bytes": len(capture.stderr),
                    "stderr_sha256": hashlib.sha256(capture.stderr).hexdigest(),
                }
            )

        for name in container_registry.expected_names:
            container_id = snapshot.get(name)
            references: list[tuple[str, str]] = []
            if (
                type(container_id) is str
                and _CONTAINER_ID_RE.fullmatch(container_id) is not None
                and container_id not in seen_ids
            ):
                seen_ids.add(container_id)
                references.append(("container_id", container_id))
            references.append(("container_name", name))
            for reference_kind, reference in references:
                inspect_reference(
                    container_name=name,
                    container_id=(
                        container_id if type(container_id) is str else None
                    ),
                    reference_kind=reference_kind,
                    reference=reference,
                )
        for name, container_id in sorted(snapshot.items()):
            if (
                name not in container_registry.expected_names
                and type(container_id) is str
                and _CONTAINER_ID_RE.fullmatch(container_id) is not None
                and container_id not in seen_ids
            ):
                seen_ids.add(container_id)
                inspect_reference(
                    container_name=name,
                    container_id=container_id,
                    reference_kind="unexpected_registry_container_id",
                    reference=container_id,
                )
        try:
            listing = _run_read_only(
                runner,
                [
                    DOCKER_CLI,
                    DOCKER_HOST_ARG,
                    "container",
                    "ls",
                    "--all",
                    "--no-trunc",
                    "--format={{json .}}",
                ],
                label="final local Docker container inventory",
            )
            final_catalog_facts = {
                "returncode": listing.returncode,
                "stdout_size_bytes": len(listing.stdout),
                "stdout_sha256": hashlib.sha256(listing.stdout).hexdigest(),
                "stderr_size_bytes": len(listing.stderr),
                "stderr_sha256": hashlib.sha256(listing.stderr).hexdigest(),
                "exact_empty_observed": (
                    listing.returncode == 0
                    and listing.stdout == b""
                    and listing.stderr == b""
                ),
            }
            if final_catalog_facts["exact_empty_observed"] is not True:
                failures.append(
                    _DockerOperationError(
                        "final local Docker container inventory is not exact empty",
                        stage="final_owned_container_cleanup",
                        command_class="container_inventory",
                        capture=listing,
                    )
                )
        except BaseException as error:
            failures.append(error)
        if failures:
            primary, *supplemental = failures
            raise _FinalOwnedContainerCleanupError(
                primary=primary,
                supplemental_failures=supplemental,
                registry_id_sha256s={
                    name: hashlib.sha256(container_id.encode("ascii")).hexdigest()
                    for name, container_id in snapshot.items()
                    if type(container_id) is str
                    and _CONTAINER_ID_RE.fullmatch(container_id) is not None
                },
                absence_inspects=inspect_facts,
                final_catalog=final_catalog_facts,
            ) from primary
    raw_contract = getattr(cleanup_mutex, "contract", None)
    contract = (
        _validate_cleanup_mutex_contract(raw_contract)
        if isinstance(raw_contract, Mapping)
        else None
    )
    _require(
        contract is not None or type(cleanup_mutex) is _NullCleanupMutex,
        "production cleanup mutex contract is unavailable",
    )
    return {
        "schema_version": 1,
        "policy_id": "native_flock_global_owned_container_cleanup_v1",
        "cleanup_mutex_contract": contract,
        "independent_open_file_description_per_actor_attested": (
            contract is not None
        ),
        "registry_coverage_complete": coverage_exact,
        "recorded_container_count": len(snapshot),
        "owned_container_ids_by_name_sha256": {
            name: hashlib.sha256(container_id.encode("ascii")).hexdigest()
            for name, container_id in snapshot.items()
        },
        "absence_inspects": inspect_facts,
        "final_catalog": dict(final_catalog_facts or {}),
    }


def _observe_unresolved_operation_root(
    run_lease: Any,
) -> dict[str, object] | None:
    """Snapshot durable unresolved markers while the exact run lease is held."""

    if type(run_lease) is _NullRunLease:
        return None
    _require(
        type(run_lease) is _RunLease and not run_lease.released,
        "unresolved operation observation lease drifted",
    )
    held_markers: list[tuple[str, int, dict[str, int]]] = []
    facts: dict[str, object] | None = None
    primary: BaseException | None = None
    try:
        _validate_run_lease_held(
            run_lease.contract,
            parent_fd=run_lease.parent_fd,
            identity_fd=run_lease.identity_fd,
            admission_fd=run_lease.admission_fd,
            retention_fd=run_lease.retention_fd,
            unresolved_root_fd=run_lease.unresolved_root_fd,
        )
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        _require(
            nofollow != 0 and cloexec != 0,
            "unresolved operation observation no-follow custody is unavailable",
        )
        try:
            os.fsync(run_lease.unresolved_root_fd)
            first_names = sorted(os.listdir(run_lease.unresolved_root_fd))
        except OSError as error:
            raise ExecutorContractError(
                "cannot observe unresolved operation root"
            ) from error
        name_sha256s: list[str] = []
        for name in first_names:
            _require(
                type(name) is str
                and re.fullmatch(
                    r"op-[0-9a-f]{48}(?:\.resolving)?",
                    name,
                )
                is not None,
                "unresolved operation root entry drifted",
            )
            try:
                descriptor = os.open(
                    name,
                    os.O_RDONLY | nofollow | cloexec,
                    dir_fd=run_lease.unresolved_root_fd,
                )
            except OSError as error:
                raise ExecutorContractError(
                    "cannot hold unresolved operation marker"
                ) from error
            held_markers.append((name, descriptor, {}))
            try:
                handle = os.fstat(descriptor)
                named = os.stat(
                    name,
                    dir_fd=run_lease.unresolved_root_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise ExecutorContractError(
                    "cannot observe unresolved operation marker"
                ) from error
            identity = _cleanup_mutex_file_record(handle)
            _require(
                _run_lease_leaf_matches(identity, handle)
                and _run_lease_leaf_matches(identity, named),
                "unresolved operation marker state drifted",
            )
            held_markers[-1] = (name, descriptor, identity)
            name_sha256s.append(
                hashlib.sha256(name.encode("ascii")).hexdigest()
            )
        try:
            os.fsync(run_lease.unresolved_root_fd)
            second_names = sorted(os.listdir(run_lease.unresolved_root_fd))
        except OSError as error:
            raise ExecutorContractError(
                "cannot close unresolved operation observation"
            ) from error
        _require(
            first_names == second_names,
            "unresolved operation root changed during observation",
        )
        for name, descriptor, identity in held_markers:
            try:
                handle = os.fstat(descriptor)
                named = os.stat(
                    name,
                    dir_fd=run_lease.unresolved_root_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise ExecutorContractError(
                    "unresolved operation marker changed during observation"
                ) from error
            _require(
                bool(identity)
                and _run_lease_leaf_matches(identity, handle)
                and _run_lease_leaf_matches(identity, named),
                "unresolved operation marker changed during observation",
            )
        _validate_run_lease_held(
            run_lease.contract,
            parent_fd=run_lease.parent_fd,
            identity_fd=run_lease.identity_fd,
            admission_fd=run_lease.admission_fd,
            retention_fd=run_lease.retention_fd,
            unresolved_root_fd=run_lease.unresolved_root_fd,
        )
        facts = {
            "schema_version": 1,
            "policy_id": "held_run_lease_unresolved_root_snapshot_v1",
            "entry_count": len(first_names),
            "entry_name_sha256s": name_sha256s,
            "exact_empty_attested": not first_names,
        }
    except BaseException as error:
        primary = error
    close_failures: list[BaseException] = []
    for _name, descriptor, _identity in held_markers:
        try:
            os.close(descriptor)
        except BaseException as error:
            close_failures.append(error)
    if close_failures:
        raise _DescriptorClosureError(
            operation="unresolved_operation_observation",
            primary=primary,
            close_failures=close_failures,
        ) from (primary if primary is not None else close_failures[0])
    if primary is not None:
        raise primary
    _require(facts is not None, "unresolved operation observation is unavailable")
    return facts


def _runtime_cleanup_observation(
    *,
    attempted: bool,
    docker: Mapping[str, object] | None,
    unresolved_operations: Mapping[str, object] | None,
) -> dict[str, object]:
    _require(type(attempted) is bool, "runtime cleanup attempt state drifted")
    docker_facts = dict(docker) if docker is not None else None
    unresolved_facts = (
        dict(unresolved_operations)
        if unresolved_operations is not None
        else None
    )
    docker_available = docker_facts is not None
    unresolved_available = unresolved_facts is not None
    complete = bool(
        attempted
        and docker_available
        and unresolved_available
        and dict(_mapping(docker_facts, "runtime cleanup Docker facts"))
        .get("final_catalog", {})
        .get("exact_empty_observed")
        is True
        and unresolved_facts.get("exact_empty_attested") is True
    )
    facts = {
        "schema_version": 1,
        "policy_id": "failure_safe_owned_runtime_poststate_v1",
        "attempted": attempted,
        "docker_observation_available": docker_available,
        "unresolved_operation_observation_available": unresolved_available,
        "complete_attestation": complete,
        "docker": docker_facts,
        "unresolved_operations": unresolved_facts,
    }
    canonical_line(facts)
    return facts


def _partial_owned_container_cleanup_facts(
    *,
    cleanup_mutex: Any,
    error: _FinalOwnedContainerCleanupError,
) -> dict[str, object]:
    """Project a failed read-only final observation without overstating it."""

    raw_contract = getattr(cleanup_mutex, "contract", None)
    contract = (
        _validate_cleanup_mutex_contract(raw_contract)
        if isinstance(raw_contract, Mapping)
        else None
    )
    _require(
        contract is not None or type(cleanup_mutex) is _NullCleanupMutex,
        "production cleanup mutex contract is unavailable",
    )
    facts: dict[str, object] = {
        "schema_version": 1,
        "policy_id": "native_flock_global_owned_container_cleanup_v1",
        "cleanup_mutex_contract": contract,
        "independent_open_file_description_per_actor_attested": (
            contract is not None
        ),
        "registry_coverage_complete": False,
        "recorded_container_count": len(error.registry_id_sha256s),
        "owned_container_ids_by_name_sha256": dict(
            error.registry_id_sha256s
        ),
        "absence_inspects": [dict(item) for item in error.absence_inspects],
        "final_catalog": dict(error.final_catalog or {}),
    }
    canonical_line(facts)
    return facts


def _produce_failure_safe_runtime_poststate(
    *,
    runner: CommandRunner,
    cleanup_mutex: Any,
    run_lease: Any,
    run_identity: str,
    attempt_context: _ExecutionAttemptContext,
) -> list[tuple[str, str, BaseException]]:
    """Record independent read-only poststate before releasing runtime owners."""

    failures: list[tuple[str, str, BaseException]] = []
    docker_facts: Mapping[str, object] | None = None
    unresolved_facts: Mapping[str, object] | None = None
    try:
        try:
            docker_facts = _finalize_owned_container_cleanup(
                runner=runner,
                cleanup_mutex=cleanup_mutex,
                container_registry=_OwnedContainerRegistry(run_identity),
                require_complete_registry=False,
            )
        except _FinalOwnedContainerCleanupError as error:
            try:
                docker_facts = _partial_owned_container_cleanup_facts(
                    cleanup_mutex=cleanup_mutex,
                    error=error,
                )
            except BaseException as projection_error:
                failures.append(
                    (
                        "runtime_poststate_observation",
                        "runtime_poststate_docker_observation",
                        _DescriptorClosureError(
                            operation="runtime_poststate_docker_projection",
                            primary=error,
                            close_failures=[projection_error],
                        ),
                    )
                )
            else:
                failures.append(
                    (
                        "runtime_poststate_observation",
                        "runtime_poststate_docker_observation",
                        error,
                    )
                )
        except BaseException as error:
            failures.append(
                (
                    "runtime_poststate_observation",
                    "runtime_poststate_docker_observation",
                    error,
                )
            )

        try:
            unresolved_facts = (
                _observe_unresolved_operation_root(run_lease)
                if type(run_lease) in {_RunLease, _NullRunLease}
                else None
            )
        except BaseException as error:
            failures.append(
                (
                    "runtime_poststate_observation",
                    "runtime_poststate_unresolved_operation_observation",
                    error,
                )
            )

        try:
            attempt_context.record_runtime_cleanup_observation(
                _runtime_cleanup_observation(
                    attempted=True,
                    docker=docker_facts,
                    unresolved_operations=unresolved_facts,
                )
            )
        except BaseException as error:
            failures.append(
                (
                    "runtime_poststate_observation",
                    "runtime_poststate_recording",
                    error,
                )
            )
    finally:
        try:
            cleanup_mutex.close()
        except BaseException as error:
            failures.append(
                ("cleanup_mutex_close", "cleanup_mutex_close", error)
            )
    return failures


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
        "IPC filesystem attestation requires Linux",
    )
    value = _LinuxStatFs()
    libc = ctypes.CDLL(None, use_errno=True)
    fstatfs = libc.fstatfs
    fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_LinuxStatFs)]
    fstatfs.restype = ctypes.c_int
    if fstatfs(descriptor, ctypes.byref(value)) != 0:
        error_number = ctypes.get_errno()
        raise ExecutorContractError("cannot attest IPC filesystem type") from OSError(
            error_number,
            os.strerror(error_number),
        )
    return int(value.f_type) & ((1 << (ctypes.sizeof(ctypes.c_long) * 8)) - 1)


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_uid),
        int(value.st_gid),
    )


def _ipc_runtime_path(
    run_identity: str,
    *,
    parent: Path = IPC_RUNTIME_PARENT,
) -> Path:
    _require(
        type(run_identity) is str and _SHA_RE.fullmatch(run_identity) is not None,
        "IPC runtime requires an exact run identity",
    )
    _require(
        isinstance(parent, Path)
        and (parent == IPC_RUNTIME_PARENT or parent.is_absolute())
        and ".." not in parent.parts
        and "\0" not in str(parent),
        "IPC runtime parent is unsafe",
    )
    token = hashlib.sha256(
        _IPC_RUNTIME_PATH_DOMAIN + run_identity.encode("ascii")
    ).hexdigest()[:48]
    root = parent / f"{_IPC_RUNTIME_NAME_PREFIX}{token}"
    for name in (_IPC_CAPABILITY_SOCKET_NAME, *(f"{branch}.sock" for branch in BRANCHES)):
        try:
            encoded = os.fsencode(root / name)
        except UnicodeError as error:
            raise ExecutorContractError("IPC AF_UNIX path is not filesystem-encodable") from error
        _require(
            b"\0" not in encoded and len(encoded) <= _AF_UNIX_PATH_MAX_BYTES,
            "IPC AF_UNIX path exceeds the exact bounded length",
        )
    return root


def _attest_native_ipc_runtime_parent(*, parent: Path) -> None:
    """Reject an unsupported IPC parent before arming a cleanup owner."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and isinstance(parent, Path)
        and parent.is_absolute()
        and nofollow != 0
        and directory != 0
        and cloexec != 0,
        "native IPC parent attestation requires Linux no-follow custody",
    )
    parent_fd: int | None = None
    primary: BaseException | None = None
    close_failures: list[BaseException] = []
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        handle = os.fstat(parent_fd)
        named = parent.lstat()
        mode = stat.S_IMODE(handle.st_mode)
        _require(
            _directory_identity(handle) == _directory_identity(named)
            and stat.S_ISDIR(handle.st_mode)
            and handle.st_uid in {0, os.getuid()}
            and ((mode & 0o022) == 0 or bool(handle.st_mode & stat.S_ISVTX))
            and _linux_fstatfs_magic(parent_fd)
            == _LINUX_EXT_FILESYSTEM_MAGIC,
            "native IPC runtime parent identity drifted",
        )
    except BaseException as error:
        primary = error
    finally:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_failures.append(error)
    if primary is not None or close_failures:
        raise _DescriptorClosureError(
            operation="native_ipc_runtime_parent_attestation",
            primary=primary,
            close_failures=close_failures,
        ) from (primary if primary is not None else close_failures[0])


def _durably_attest_ipc_namespace_absent(
    run_identity: str,
    *,
    parent: Path = IPC_RUNTIME_PARENT,
) -> None:
    """Commit and re-attest exact IPC-root absence before marker resolution."""

    root = _ipc_runtime_path(run_identity, parent=parent)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and nofollow != 0
        and directory != 0
        and cloexec != 0,
        "durable IPC absence attestation requires Linux no-follow custody",
    )
    parent_fd: int | None = None
    primary: BaseException | None = None
    close_failures: list[BaseException] = []
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        before = os.fstat(parent_fd)
        named_before = parent.lstat()
        parent_mode = stat.S_IMODE(before.st_mode)
        _require(
            _directory_identity(before) == _directory_identity(named_before)
            and stat.S_ISDIR(before.st_mode)
            and before.st_uid in {0, os.getuid()}
            and (
                (parent_mode & 0o022) == 0
                or bool(before.st_mode & stat.S_ISVTX)
            )
            and _linux_fstatfs_magic(parent_fd)
            == _LINUX_EXT_FILESYSTEM_MAGIC,
            "durable IPC absence parent identity drifted",
        )
        os.fsync(parent_fd)
        try:
            os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ExecutorContractError(
                "cannot inspect durably removed IPC namespace"
            ) from error
        else:
            raise ExecutorContractError(
                "IPC namespace remained named after durable absence fsync"
            )
        after = os.fstat(parent_fd)
        named_after = parent.lstat()
        _require(
            _directory_identity(after)
            == _directory_identity(named_after)
            == _directory_identity(before),
            "durable IPC absence parent changed during attestation",
        )
    except BaseException as error:
        primary = error
    finally:
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_failures.append(error)
    if primary is not None or close_failures:
        raise _DescriptorClosureError(
            operation="durable_ipc_namespace_absence_attestation",
            primary=primary,
            close_failures=close_failures,
        ) from (primary if primary is not None else close_failures[0])


def _validate_ipc_runtime_namespace(namespace: _IpcRuntimeNamespace) -> None:
    _require(
        type(namespace) is _IpcRuntimeNamespace
        and type(namespace.watchdog_owned) is bool
        and not namespace.closed,
        "IPC runtime namespace handle is invalid",
    )
    _require(
        namespace.path
        == _ipc_runtime_path(
            namespace.run_identity,
            parent=namespace.parent_path,
        )
        and namespace.name == namespace.path.name,
        "IPC runtime namespace path drifted",
    )
    if namespace.unresolved_operation_contract is not None:
        unresolved = _validate_unresolved_operation_contract(
            namespace.unresolved_operation_contract
        )
        _require(
            unresolved.get("operation_kind") == "ipc_namespace"
            and unresolved.get("run_identity_sha256")
            == namespace.run_identity
            and unresolved.get("operation_id")
            == _ipc_unresolved_operation_id(
                namespace.run_identity,
                parent=namespace.parent_path,
            )
            and _mapping(
                unresolved.get("root"),
                "IPC unresolved operation root",
            ).get("path")
            == str(_unresolved_operation_root_path()),
            "IPC unresolved operation cross-bind drifted",
        )
    try:
        parent_handle = os.fstat(namespace.parent_fd)
        root_handle = os.fstat(namespace.root_fd)
        parent_path = namespace.parent_path.lstat()
    except OSError as error:
        raise ExecutorContractError("cannot validate held IPC runtime namespace") from error
    _require(
        _directory_identity(parent_handle) == namespace.parent_identity
        and _directory_identity(parent_path) == namespace.parent_identity
        and stat.S_ISDIR(parent_handle.st_mode),
        "IPC runtime parent identity drifted",
    )
    _require(
        _directory_identity(root_handle) == namespace.root_identity
        and stat.S_ISDIR(root_handle.st_mode)
        and stat.S_IMODE(root_handle.st_mode) == 0o700
        and root_handle.st_uid == os.getuid()
        and root_handle.st_gid == os.getgid()
        and root_handle.st_nlink == (0 if namespace.unlinked else 2)
        and namespace.filesystem_magic == _LINUX_EXT_FILESYSTEM_MAGIC
        and _linux_fstatfs_magic(namespace.root_fd) == namespace.filesystem_magic,
        "IPC runtime directory identity drifted",
    )
    if namespace.unlinked:
        try:
            os.stat(
                namespace.name,
                dir_fd=namespace.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ExecutorContractError("cannot verify removed IPC runtime namespace") from error
        else:
            raise ExecutorContractError("removed IPC runtime namespace name reappeared")
        _require(not os.listdir(namespace.root_fd), "removed IPC runtime directory is not empty")
        return
    try:
        root_path = namespace.path.lstat()
        root_named = os.stat(
            namespace.name,
            dir_fd=namespace.parent_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise ExecutorContractError("cannot validate named IPC runtime namespace") from error
    _require(
        _directory_identity(root_path) == namespace.root_identity
        and _directory_identity(root_named) == namespace.root_identity,
        "IPC runtime named directory identity drifted",
    )


def _validate_owned_ipc_socket(
    namespace: _IpcRuntimeNamespace,
    name: str,
) -> os.stat_result:
    _require(
        type(name) is str
        and name in {_IPC_CAPABILITY_SOCKET_NAME, *(f"{branch}.sock" for branch in BRANCHES)},
        "IPC socket name drifted",
    )
    _validate_ipc_runtime_namespace(namespace)
    try:
        value = os.stat(name, dir_fd=namespace.root_fd, follow_symlinks=False)
    except OSError as error:
        raise ExecutorContractError("cannot validate owned IPC socket") from error
    _require(
        stat.S_ISSOCK(value.st_mode)
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_uid == os.getuid()
        and value.st_gid == os.getgid()
        and value.st_nlink == 1,
        "owned IPC socket identity drifted",
    )
    return value


def _unlink_owned_ipc_socket(
    namespace: _IpcRuntimeNamespace,
    name: str,
    *,
    missing_ok: bool,
) -> None:
    _validate_ipc_runtime_namespace(namespace)
    try:
        os.stat(name, dir_fd=namespace.root_fd, follow_symlinks=False)
    except FileNotFoundError:
        _require(missing_ok, "owned IPC socket disappeared before cleanup")
        try:
            os.fsync(namespace.root_fd)
        except OSError as error:
            raise ExecutorContractError(
                "cannot attest prior owned IPC socket cleanup"
            ) from error
        return
    except OSError as error:
        raise ExecutorContractError("cannot inspect owned IPC socket for cleanup") from error
    _validate_owned_ipc_socket(namespace, name)
    try:
        os.unlink(name, dir_fd=namespace.root_fd)
        os.fsync(namespace.root_fd)
        try:
            os.stat(name, dir_fd=namespace.root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ExecutorContractError("owned IPC socket still exists after cleanup")
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError("cannot remove owned IPC socket") from error
    _validate_ipc_runtime_namespace(namespace)


def _open_named_ipc_listener(
    namespace: _IpcRuntimeNamespace,
    name: str,
    *,
    timeout_seconds: float,
    socket_factory: Callable[..., Any],
) -> Any:
    _require(
        type(name) is str
        and name in {_IPC_CAPABILITY_SOCKET_NAME, *(f"{branch}.sock" for branch in BRANCHES)},
        "IPC listener name drifted",
    )
    _require(
        type(timeout_seconds) in {int, float} and 0 < timeout_seconds <= 60,
        "IPC listener timeout drifted",
    )
    _validate_ipc_runtime_namespace(namespace)
    try:
        os.stat(name, dir_fd=namespace.root_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ExecutorContractError("cannot establish fresh IPC socket custody") from error
    else:
        raise ExecutorContractError("IPC socket path is not fresh")
    listener: Any = None
    primary: BaseException | None = None
    try:
        listener = socket_factory(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        listener.settimeout(timeout_seconds)
        listener.bind(str(namespace.path / name))
        os.chmod(namespace.path / name, 0o600)
        _validate_owned_ipc_socket(namespace, name)
        listener.listen(1)
        _validate_owned_ipc_socket(namespace, name)
        return listener
    except BaseException as error:
        primary = error
    cleanup_errors: list[BaseException] = []
    if listener is not None:
        try:
            listener.close()
        except BaseException as error:
            cleanup_errors.append(error)
    try:
        _unlink_owned_ipc_socket(namespace, name, missing_ok=True)
    except BaseException as error:
        cleanup_errors.append(error)
    if cleanup_errors:
        raise _DescriptorClosureError(
            operation="ipc_listener_setup",
            primary=primary,
            close_failures=cleanup_errors,
            message="IPC listener setup cleanup failed",
        ) from (primary if primary is not None else cleanup_errors[0])
    _require(primary is not None, "IPC listener setup failed without an exception")
    if isinstance(primary, OSError):
        raise _DescriptorClosureError(
            operation="ipc_listener_setup",
            primary=primary,
            close_failures=[],
            message="cannot create exact IPC listener",
        ) from primary
    raise primary


def _open_ipc_listener(
    namespace: _IpcRuntimeNamespace,
    branch: str,
    *,
    socket_factory: Callable[..., Any] = socket.socket,
) -> Any:
    _require(type(branch) is str and branch in BRANCHES, "IPC listener branch drifted")
    return _open_named_ipc_listener(
        namespace,
        f"{branch}.sock",
        timeout_seconds=60.0,
        socket_factory=socket_factory,
    )


def _close_ipc_listener(
    namespace: _IpcRuntimeNamespace,
    branch: str,
    listener: Any,
) -> None:
    _require(type(branch) is str and branch in BRANCHES, "IPC listener branch drifted")
    close_error: BaseException | None = None
    try:
        listener.close()
    except BaseException as error:
        close_error = error
    cleanup_error: BaseException | None = None
    try:
        _unlink_owned_ipc_socket(namespace, f"{branch}.sock", missing_ok=False)
    except BaseException as error:
        cleanup_error = error
    cleanup_errors = [
        error
        for error in (close_error, cleanup_error)
        if error is not None
    ]
    if cleanup_errors:
        raise _DescriptorClosureError(
            operation="ipc_listener_close",
            primary=None,
            close_failures=cleanup_errors,
            message="cannot close exact IPC listener",
        ) from cleanup_errors[0]


def _unlink_ipc_namespace_if_empty(namespace: _IpcRuntimeNamespace) -> bool:
    _validate_ipc_runtime_namespace(namespace)
    if os.listdir(namespace.root_fd):
        return False
    try:
        os.fsync(namespace.root_fd)
        os.rmdir(namespace.name, dir_fd=namespace.parent_fd)
        os.fsync(namespace.parent_fd)
    except FileNotFoundError as error:
        raise ExecutorContractError("IPC runtime directory disappeared before unlink") from error
    except OSError as error:
        raise ExecutorContractError("cannot unlink empty IPC runtime directory") from error
    namespace.unlinked = True
    _validate_ipc_runtime_namespace(namespace)
    return True


def _attest_ipc_watchdog_namespace_unlinked(
    namespace: _IpcRuntimeNamespace,
) -> None:
    _require(
        type(namespace) is _IpcRuntimeNamespace
        and namespace.watchdog_owned
        and not namespace.closed,
        "IPC watchdog cleanup custody is invalid",
    )
    try:
        os.fsync(namespace.root_fd)
        os.fsync(namespace.parent_fd)
        root_handle = os.fstat(namespace.root_fd)
        parent_handle = os.fstat(namespace.parent_fd)
        parent_path = namespace.parent_path.lstat()
        names = os.listdir(namespace.root_fd)
        try:
            os.stat(
                namespace.name,
                dir_fd=namespace.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            named_absent = True
        else:
            named_absent = False
    except OSError as error:
        raise ExecutorContractError("cannot attest IPC watchdog cleanup") from error
    _require(
        _directory_identity(parent_handle) == namespace.parent_identity
        and _directory_identity(parent_path) == namespace.parent_identity
        and _directory_identity(root_handle) == namespace.root_identity
        and stat.S_ISDIR(root_handle.st_mode)
        and root_handle.st_nlink == 0
        and not names
        and named_absent,
        "IPC watchdog namespace remained linked or changed identity",
    )
    namespace.unlinked = True
    _validate_ipc_runtime_namespace(namespace)


def _destroy_ipc_runtime_namespace(namespace: _IpcRuntimeNamespace) -> None:
    primary: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    namespace_validated = False
    try:
        _require(
            type(namespace) is _IpcRuntimeNamespace and not namespace.closed,
            "IPC runtime namespace handle is invalid",
        )
        if namespace.watchdog_owned and not namespace.unlinked:
            _attest_ipc_watchdog_namespace_unlinked(namespace)
        _validate_ipc_runtime_namespace(namespace)
        namespace_validated = True
    except BaseException as error:
        primary = error
    if namespace_validated and not namespace.unlinked:
        names: list[str] = []
        names_validated = False
        try:
            names = os.listdir(namespace.root_fd)
            allowed = {
                _IPC_CAPABILITY_SOCKET_NAME,
                *(f"{branch}.sock" for branch in BRANCHES),
            }
            _require(
                len(names) == len(set(names)) and set(names) <= allowed,
                "IPC runtime directory contains unknown entries",
            )
            names_validated = True
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                cleanup_errors.append(error)
        if names_validated:
            for name in sorted(names):
                try:
                    _unlink_owned_ipc_socket(namespace, name, missing_ok=True)
                except BaseException as error:
                    if primary is None:
                        primary = error
                    else:
                        cleanup_errors.append(error)
            try:
                _require(
                    _unlink_ipc_namespace_if_empty(namespace),
                    "IPC runtime directory remained nonempty after exact cleanup",
                )
            except BaseException as error:
                if primary is None:
                    primary = error
                else:
                    cleanup_errors.append(error)
    if namespace_validated:
        try:
            _validate_ipc_runtime_namespace(namespace)
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                cleanup_errors.append(error)
    if (
        namespace_validated
        and namespace.unlinked
        and primary is None
        and not cleanup_errors
        and namespace.unresolved_operation_contract is not None
    ):
        try:
            _resolve_or_attest_unresolved_operation_marker(
                namespace.unresolved_operation_contract
            )
        except BaseException as error:
            primary = error
    namespace.closed = True
    for descriptor in (namespace.root_fd, namespace.parent_fd):
        try:
            os.close(descriptor)
        except BaseException as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise _DescriptorClosureError(
            operation="ipc_runtime_namespace_destroy",
            primary=primary,
            close_failures=cleanup_errors,
            message="cannot remove exact IPC runtime namespace",
        ) from (primary if primary is not None else cleanup_errors[0])
    if primary is not None:
        if isinstance(primary, ExecutorContractError):
            raise primary
        raise _DescriptorClosureError(
            operation="ipc_runtime_namespace_destroy",
            primary=primary,
            close_failures=[],
            message="cannot remove exact IPC runtime namespace",
        ) from primary


def _create_ipc_runtime_namespace(
    run_identity: str,
    *,
    parent: Path = IPC_RUNTIME_PARENT,
) -> _IpcRuntimeNamespace:
    _require(
        os.name == "posix"
        and hasattr(os, "getuid")
        and hasattr(os, "getgid")
        and parent.is_absolute(),
        "native IPC runtime requires POSIX",
    )
    root = _ipc_runtime_path(run_identity, parent=parent)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(nofollow != 0 and directory != 0, "POSIX IPC no-follow custody is unavailable")
    parent_fd: int | None = None
    root_fd: int | None = None
    created = False
    try:
        try:
            parent_fd = os.open(parent, os.O_RDONLY | directory | nofollow | cloexec)
        except OSError as error:
            raise ExecutorContractError("IPC runtime parent cannot be held no-follow") from error
        parent_handle = os.fstat(parent_fd)
        parent_path = parent.lstat()
        parent_mode = stat.S_IMODE(parent_handle.st_mode)
        _require(
            stat.S_ISDIR(parent_handle.st_mode)
            and _directory_identity(parent_handle) == _directory_identity(parent_path)
            and parent_handle.st_uid in {0, os.getuid()}
            and ((parent_mode & 0o022) == 0 or bool(parent_handle.st_mode & stat.S_ISVTX)),
            "IPC runtime parent identity is unsafe",
        )
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent_fd)
            created = True
        except FileExistsError as error:
            raise ExecutorContractError("IPC runtime namespace already exists") from error
        root_fd = os.open(
            root.name,
            os.O_RDONLY | directory | nofollow | cloexec,
            dir_fd=parent_fd,
        )
        root_handle = os.fstat(root_fd)
        root_named = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        filesystem_magic = _linux_fstatfs_magic(root_fd)
        _require(
            _directory_identity(root_handle) == _directory_identity(root_named)
            and stat.S_ISDIR(root_handle.st_mode)
            and stat.S_IMODE(root_handle.st_mode) == 0o700
            and root_handle.st_uid == os.getuid()
            and root_handle.st_gid == os.getgid()
            and root_handle.st_nlink == 2
            and filesystem_magic == _LINUX_EXT_FILESYSTEM_MAGIC,
            "new IPC runtime directory identity drifted",
        )
        namespace = _IpcRuntimeNamespace(
            run_identity=run_identity,
            path=root,
            parent_path=parent,
            name=root.name,
            parent_fd=parent_fd,
            root_fd=root_fd,
            parent_identity=_directory_identity(parent_handle),
            root_identity=_directory_identity(root_handle),
            filesystem_magic=filesystem_magic,
        )
        parent_fd = None
        root_fd = None
        try:
            listener = _open_named_ipc_listener(
                namespace,
                _IPC_CAPABILITY_SOCKET_NAME,
                timeout_seconds=1.0,
                socket_factory=socket.socket,
            )
            capability_cleanup_errors: list[BaseException] = []
            try:
                listener.close()
            except BaseException as error:
                capability_cleanup_errors.append(error)
            try:
                _unlink_owned_ipc_socket(
                    namespace,
                    _IPC_CAPABILITY_SOCKET_NAME,
                    missing_ok=False,
                )
            except BaseException as error:
                capability_cleanup_errors.append(error)
            if capability_cleanup_errors:
                raise _DescriptorClosureError(
                    operation="ipc_namespace_capability_listener_close",
                    primary=None,
                    close_failures=capability_cleanup_errors,
                    message="IPC namespace capability listener cleanup failed",
                ) from capability_cleanup_errors[0]
            _validate_ipc_runtime_namespace(namespace)
        except BaseException as primary_error:
            try:
                _destroy_ipc_runtime_namespace(namespace)
            except BaseException as cleanup_error:
                raise _DescriptorClosureError(
                    operation="ipc_namespace_capability_probe",
                    primary=primary_error,
                    close_failures=[cleanup_error],
                    message="IPC namespace capability probe cleanup failed",
                ) from primary_error
            raise
        return namespace
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError("cannot create exact IPC runtime namespace") from error
    finally:
        active_error = sys.exception()
        cleanup_errors: list[BaseException] = []
        if root_fd is not None:
            try:
                os.close(root_fd)
            except BaseException as error:
                cleanup_errors.append(error)
        if created and parent_fd is not None:
            try:
                value = os.stat(
                    root.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                _require(
                    stat.S_ISDIR(value.st_mode)
                    and value.st_uid == os.getuid(),
                    "created IPC namespace cleanup identity drifted",
                )
                os.rmdir(root.name, dir_fd=parent_fd)
            except BaseException as error:
                cleanup_errors.append(error)
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="ipc_runtime_namespace_creation",
                primary=active_error,
                close_failures=cleanup_errors,
                message="cannot create exact IPC runtime namespace",
            ) from (
                active_error if active_error is not None else cleanup_errors[0]
            )


def _run_lease_scope_sha256() -> str:
    core = {
        "docker_host": DOCKER_HOST_ARG,
        "image_id": TENSORRT_IMAGE_ID,
        "owner_policy": OWNER_VALUE,
    }
    return hashlib.sha256(
        RUN_LEASE_SCOPE_DOMAIN + canonical_line(core)
    ).hexdigest()


def _run_lease_paths(
    run_identity: str,
    *,
    parent: Path = RUN_LEASE_PARENT,
) -> dict[str, Path]:
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and isinstance(parent, Path)
        and parent.is_absolute()
        and ".." not in PurePosixPath(str(parent)).parts,
        "run lease path identity drifted",
    )
    scope = _run_lease_scope_sha256()[:48]
    return {
        "identity": parent / f"{_RUN_LEASE_IDENTITY_NAME_PREFIX}{run_identity}",
        "admission": parent / f"{_RUN_LEASE_ADMISSION_NAME_PREFIX}{scope}",
        "retention": parent / f"{_RUN_LEASE_RETENTION_NAME_PREFIX}{scope}",
    }


def _unresolved_operation_root_path(
    *,
    parent: Path = RUN_LEASE_PARENT,
) -> Path:
    _require(
        isinstance(parent, Path)
        and parent.is_absolute()
        and ".." not in PurePosixPath(str(parent)).parts,
        "unresolved operation root path drifted",
    )
    return parent / (
        _UNRESOLVED_ROOT_NAME_PREFIX + _run_lease_scope_sha256()[:48]
    )


def _unresolved_directory_record(value: os.stat_result) -> dict[str, int]:
    return {
        **_cleanup_mutex_parent_record(value),
        "nlink": int(value.st_nlink),
    }


def _run_lease_leaf_contract(path: Path, state: os.stat_result) -> dict[str, object]:
    return {
        "path": str(path),
        "name": path.name,
        "identity": _cleanup_mutex_file_record(state),
    }


def _run_lease_contract(
    *,
    run_identity: str,
    parent_state: os.stat_result,
    filesystem_magic: int,
    leaf_states: Mapping[str, os.stat_result],
    unresolved_root_state: os.stat_result,
    parent: Path = RUN_LEASE_PARENT,
) -> dict[str, object]:
    paths = _run_lease_paths(run_identity, parent=parent)
    _require(
        set(leaf_states) == {"identity", "admission", "retention"},
        "run lease leaf coverage drifted",
    )
    core: dict[str, object] = {
        "schema_version": 2,
        "artifact_kind": "vast_kpp_v2_nonpublication_run_lease_v2",
        "policy_id": "exclusive_global_admission_shared_global_retention_v1",
        "run_identity_sha256": run_identity,
        "global_scope_sha256": _run_lease_scope_sha256(),
        "parent_path": str(parent),
        "filesystem_magic": filesystem_magic,
        "parent_identity": _cleanup_mutex_parent_record(parent_state),
        "identity": _run_lease_leaf_contract(paths["identity"], leaf_states["identity"]),
        "admission": _run_lease_leaf_contract(paths["admission"], leaf_states["admission"]),
        "retention": _run_lease_leaf_contract(paths["retention"], leaf_states["retention"]),
        "unresolved_root": {
            "path": str(_unresolved_operation_root_path(parent=parent)),
            "name": _unresolved_operation_root_path(parent=parent).name,
            "identity": _unresolved_directory_record(unresolved_root_state),
        },
    }
    return {
        **core,
        "run_lease_contract_sha256": hashlib.sha256(
            RUN_LEASE_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }


def _validate_run_lease_contract(
    value: Mapping[str, object],
) -> dict[str, object]:
    contract = dict(_mapping(value, "run lease contract"))
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "policy_id",
        "run_identity_sha256",
        "global_scope_sha256",
        "parent_path",
        "filesystem_magic",
        "parent_identity",
        "identity",
        "admission",
        "retention",
        "unresolved_root",
        "run_lease_contract_sha256",
    }
    _require(
        set(contract) == expected_fields
        and contract.get("schema_version") == 2
        and contract.get("artifact_kind")
        == "vast_kpp_v2_nonpublication_run_lease_v2"
        and contract.get("policy_id")
        == "exclusive_global_admission_shared_global_retention_v1",
        "run lease contract fields drifted",
    )
    claimed = contract.pop("run_lease_contract_sha256")
    _require(
        type(claimed) is str
        and _SHA_RE.fullmatch(claimed) is not None
        and claimed
        == hashlib.sha256(
            RUN_LEASE_DOMAIN + canonical_line(contract)
        ).hexdigest(),
        "run lease contract identity drifted",
    )
    run_identity = contract.get("run_identity_sha256")
    parent_path = contract.get("parent_path")
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and type(parent_path) is str
        and Path(parent_path) == RUN_LEASE_PARENT
        and contract.get("global_scope_sha256") == _run_lease_scope_sha256()
        and contract.get("filesystem_magic") == _LINUX_EXT_FILESYSTEM_MAGIC,
        "run lease scope drifted",
    )
    parent_identity = dict(
        _mapping(contract.get("parent_identity"), "run lease parent identity")
    )
    _require(
        set(parent_identity) == {"device", "inode", "mode", "uid", "gid"}
        and all(type(item) is int for item in parent_identity.values())
        and stat.S_ISDIR(parent_identity["mode"])
        and stat.S_IMODE(parent_identity["mode"]) == 0o1777
        and parent_identity["uid"] == 0
        and parent_identity["gid"] == 0,
        "run lease parent identity drifted",
    )
    expected_paths = _run_lease_paths(run_identity)
    validated_leaves: dict[str, dict[str, object]] = {}
    for kind in ("identity", "admission", "retention"):
        leaf = dict(_mapping(contract.get(kind), f"run lease {kind}"))
        identity = dict(
            _mapping(leaf.get("identity"), f"run lease {kind} identity")
        )
        _require(
            set(leaf) == {"path", "name", "identity"}
            and leaf.get("path") == str(expected_paths[kind])
            and leaf.get("name") == expected_paths[kind].name
            and set(identity)
            == {"device", "inode", "mode", "uid", "gid", "nlink", "size_bytes"}
            and all(type(item) is int for item in identity.values())
            and stat.S_ISREG(identity["mode"])
            and stat.S_IMODE(identity["mode"]) == 0o600
            and identity["uid"] == os.getuid()
            and identity["gid"] == os.getgid()
            and identity["nlink"] == 1
            and identity["size_bytes"] == 0,
            f"run lease {kind} identity drifted",
        )
        validated_leaves[kind] = {**leaf, "identity": identity}
    unresolved_root = dict(
        _mapping(contract.get("unresolved_root"), "unresolved operation root")
    )
    unresolved_identity = dict(
        _mapping(
            unresolved_root.get("identity"),
            "unresolved operation root identity",
        )
    )
    expected_unresolved_root = _unresolved_operation_root_path()
    _require(
        set(unresolved_root) == {"path", "name", "identity"}
        and unresolved_root.get("path") == str(expected_unresolved_root)
        and unresolved_root.get("name") == expected_unresolved_root.name
        and set(unresolved_identity)
        == {"device", "inode", "mode", "uid", "gid", "nlink"}
        and all(type(item) is int for item in unresolved_identity.values())
        and stat.S_ISDIR(unresolved_identity["mode"])
        and stat.S_IMODE(unresolved_identity["mode"]) == 0o700
        and unresolved_identity["uid"] == os.getuid()
        and unresolved_identity["gid"] == os.getgid()
        and unresolved_identity["nlink"] >= 2,
        "unresolved operation root identity drifted",
    )
    return {
        **contract,
        "parent_identity": parent_identity,
        **validated_leaves,
        "unresolved_root": {
            **unresolved_root,
            "identity": unresolved_identity,
        },
        "run_lease_contract_sha256": claimed,
    }


def _run_lease_leaf_matches(
    record: Mapping[str, object],
    state: os.stat_result,
) -> bool:
    return (
        dict(record) == _cleanup_mutex_file_record(state)
        and stat.S_ISREG(state.st_mode)
        and stat.S_IMODE(state.st_mode) == 0o600
        and state.st_uid == os.getuid()
        and state.st_gid == os.getgid()
        and state.st_nlink == 1
        and state.st_size == 0
    )


def _validate_run_lease_descriptors(
    raw_contract: Mapping[str, object],
    *,
    parent_fd: int,
    descriptors: Mapping[str, int],
    unresolved_root_fd: int | None = None,
) -> dict[str, object]:
    contract = _validate_run_lease_contract(raw_contract)
    parent_path = Path(str(contract["parent_path"]))
    try:
        parent_handle = os.fstat(parent_fd)
        parent_named = os.stat(parent_path, follow_symlinks=False)
    except OSError as error:
        raise ExecutorContractError("cannot validate run lease parent") from error
    _require(
        _cleanup_mutex_parent_record(parent_handle)
        == _cleanup_mutex_parent_record(parent_named)
        == contract["parent_identity"]
        and _linux_fstatfs_magic(parent_fd) == contract["filesystem_magic"],
        "run lease parent custody drifted",
    )
    for kind, descriptor in descriptors.items():
        leaf = _mapping(contract.get(kind), f"run lease {kind}")
        identity = _mapping(leaf.get("identity"), f"run lease {kind} identity")
        try:
            handle = os.fstat(descriptor)
            named = os.stat(
                str(leaf["name"]),
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise ExecutorContractError(
                f"cannot validate run lease {kind} custody"
            ) from error
        _require(
            _run_lease_leaf_matches(identity, handle)
            and _run_lease_leaf_matches(identity, named),
            f"run lease {kind} custody drifted",
        )
    if unresolved_root_fd is not None:
        unresolved_root = _mapping(
            contract["unresolved_root"], "unresolved operation root"
        )
        unresolved_identity = _mapping(
            unresolved_root["identity"],
            "unresolved operation root identity",
        )
        try:
            root_handle = os.fstat(unresolved_root_fd)
            root_named = os.stat(
                str(unresolved_root["name"]),
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise ExecutorContractError(
                "cannot validate unresolved operation root custody"
            ) from error
        _require(
            _unresolved_directory_record(root_handle)
            == _unresolved_directory_record(root_named)
            == dict(unresolved_identity)
            and _linux_fstatfs_magic(unresolved_root_fd)
            == contract["filesystem_magic"],
            "unresolved operation root custody drifted",
        )
    return contract


def _validate_run_lease_held(
    raw_contract: Mapping[str, object],
    *,
    parent_fd: int,
    identity_fd: int,
    admission_fd: int,
    retention_fd: int,
    unresolved_root_fd: int,
) -> dict[str, object]:
    return _validate_run_lease_descriptors(
        raw_contract,
        parent_fd=parent_fd,
        descriptors={
            "identity": identity_fd,
            "admission": admission_fd,
            "retention": retention_fd,
        },
        unresolved_root_fd=unresolved_root_fd,
    )


def _validate_run_retention_hold(
    raw_contract: Mapping[str, object],
    *,
    parent_fd: int,
    retention_fd: int,
) -> dict[str, object]:
    return _validate_run_lease_descriptors(
        raw_contract,
        parent_fd=parent_fd,
        descriptors={"retention": retention_fd},
    )


def _open_or_create_run_lease_leaf(
    *,
    parent_fd: int,
    name: str,
) -> tuple[int, os.stat_result]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    flags = os.O_RDWR | nofollow | cloexec
    created = False
    try:
        descriptor = os.open(
            name,
            flags | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        created = True
    except FileExistsError:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        if created:
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            os.fsync(parent_fd)
        state = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            _cleanup_mutex_file_record(state)
            == _cleanup_mutex_file_record(named)
            and _run_lease_leaf_matches(_cleanup_mutex_file_record(state), state),
            "run lease leaf custody drifted",
        )
        return descriptor, state
    except BaseException:
        try:
            os.close(descriptor)
        except BaseException:
            pass
        raise


def _open_or_create_unresolved_operation_root(
    *,
    parent_fd: int,
) -> tuple[int, os.stat_result]:
    path = _unresolved_operation_root_path()
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    created = False
    try:
        os.mkdir(path.name, 0o700, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    root_fd = os.open(
        path.name,
        os.O_RDONLY | directory | nofollow | cloexec,
        dir_fd=parent_fd,
    )
    try:
        if created:
            os.fsync(parent_fd)
        state = os.fstat(root_fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        _require(
            _unresolved_directory_record(state)
            == _unresolved_directory_record(named)
            and stat.S_ISDIR(state.st_mode)
            and stat.S_IMODE(state.st_mode) == 0o700
            and state.st_uid == os.getuid()
            and state.st_gid == os.getgid()
            and _linux_fstatfs_magic(root_fd) == _LINUX_EXT_FILESYSTEM_MAGIC,
            "unresolved operation root custody drifted",
        )
        return root_fd, state
    except BaseException:
        try:
            os.close(root_fd)
        except BaseException:
            pass
        raise


def _unresolved_marker_name(
    *,
    run_identity: str,
    operation_kind: str,
    operation_id: str,
) -> str:
    operation_identity_is_exact = (
        operation_kind == "container_create"
        and _RUN_ID_RE.fullmatch(operation_id) is not None
    ) or (
        operation_kind == "ipc_namespace"
        and _SHA_RE.fullmatch(operation_id) is not None
    )
    _require(
        _SHA_RE.fullmatch(run_identity) is not None
        and operation_identity_is_exact,
        "unresolved operation marker identity drifted",
    )
    key = {
        "run_identity_sha256": run_identity,
        "operation_kind": operation_kind,
        "operation_id": operation_id,
    }
    digest = hashlib.sha256(
        UNRESOLVED_OPERATION_PATH_DOMAIN + canonical_line(key)
    ).hexdigest()[:48]
    return _UNRESOLVED_MARKER_NAME_PREFIX + digest


def _ipc_unresolved_operation_id(
    run_identity: str,
    *,
    parent: Path,
) -> str:
    root = _ipc_runtime_path(run_identity, parent=parent)
    core = {
        "run_identity_sha256": run_identity,
        "parent_path": str(parent),
        "root_path": str(root),
        "root_name": root.name,
    }
    return hashlib.sha256(
        UNRESOLVED_OPERATION_PATH_DOMAIN + canonical_line(core)
    ).hexdigest()


def _unresolved_operation_marker_contract(
    *,
    run_lease_contract: Mapping[str, object],
    operation_kind: str,
    operation_id: str,
    marker_state: os.stat_result,
) -> dict[str, object]:
    run_lease = _validate_run_lease_contract(run_lease_contract)
    run_identity = str(run_lease["run_identity_sha256"])
    root = _mapping(run_lease["unresolved_root"], "unresolved operation root")
    marker_name = _unresolved_marker_name(
        run_identity=run_identity,
        operation_kind=operation_kind,
        operation_id=operation_id,
    )
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_v2_unresolved_operation_marker_v1",
        "policy_id": "durable_unresolved_until_exact_cleanup_v1",
        "run_identity_sha256": run_identity,
        "global_scope_sha256": run_lease["global_scope_sha256"],
        "operation_kind": operation_kind,
        "operation_id": operation_id,
        "root": dict(root),
        "marker": {
            "path": str(Path(str(root["path"])) / marker_name),
            "name": marker_name,
            "identity": _cleanup_mutex_file_record(marker_state),
        },
    }
    return {
        **core,
        "unresolved_operation_contract_sha256": hashlib.sha256(
            UNRESOLVED_OPERATION_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }


def _validate_unresolved_operation_contract(
    value: Mapping[str, object],
) -> dict[str, object]:
    contract = dict(_mapping(value, "unresolved operation marker contract"))
    _require(
        set(contract)
        == {
            "schema_version",
            "artifact_kind",
            "policy_id",
            "run_identity_sha256",
            "global_scope_sha256",
            "operation_kind",
            "operation_id",
            "root",
            "marker",
            "unresolved_operation_contract_sha256",
        }
        and contract.get("schema_version") == 1
        and contract.get("artifact_kind")
        == "vast_kpp_v2_unresolved_operation_marker_v1"
        and contract.get("policy_id")
        == "durable_unresolved_until_exact_cleanup_v1",
        "unresolved operation marker contract fields drifted",
    )
    claimed = contract.pop("unresolved_operation_contract_sha256")
    _require(
        type(claimed) is str
        and _SHA_RE.fullmatch(claimed) is not None
        and claimed
        == hashlib.sha256(
            UNRESOLVED_OPERATION_DOMAIN + canonical_line(contract)
        ).hexdigest(),
        "unresolved operation marker contract identity drifted",
    )
    run_identity = contract.get("run_identity_sha256")
    operation_kind = contract.get("operation_kind")
    operation_id = contract.get("operation_id")
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and contract.get("global_scope_sha256") == _run_lease_scope_sha256()
        and type(operation_id) is str
        and (
            (
                operation_kind == "container_create"
                and _RUN_ID_RE.fullmatch(operation_id) is not None
            )
            or (
                operation_kind == "ipc_namespace"
                and _SHA_RE.fullmatch(operation_id) is not None
            )
        ),
        "unresolved operation marker scope drifted",
    )
    root = dict(_mapping(contract.get("root"), "unresolved operation root"))
    root_identity = dict(
        _mapping(root.get("identity"), "unresolved operation root identity")
    )
    expected_root = _unresolved_operation_root_path()
    _require(
        set(root) == {"path", "name", "identity"}
        and root.get("path") == str(expected_root)
        and root.get("name") == expected_root.name
        and set(root_identity)
        == {"device", "inode", "mode", "uid", "gid", "nlink"}
        and stat.S_ISDIR(root_identity["mode"])
        and stat.S_IMODE(root_identity["mode"]) == 0o700
        and root_identity["uid"] == os.getuid()
        and root_identity["gid"] == os.getgid()
        and root_identity["nlink"] >= 2,
        "unresolved operation root contract drifted",
    )
    marker = dict(
        _mapping(contract.get("marker"), "unresolved operation marker")
    )
    marker_identity = dict(
        _mapping(marker.get("identity"), "unresolved operation marker identity")
    )
    expected_name = _unresolved_marker_name(
        run_identity=run_identity,
        operation_kind=str(operation_kind),
        operation_id=operation_id,
    )
    _require(
        set(marker) == {"path", "name", "identity"}
        and marker.get("name") == expected_name
        and marker.get("path") == str(expected_root / expected_name)
        and set(marker_identity)
        == {"device", "inode", "mode", "uid", "gid", "nlink", "size_bytes"}
        and all(type(item) is int for item in marker_identity.values())
        and stat.S_ISREG(marker_identity["mode"])
        and stat.S_IMODE(marker_identity["mode"]) == 0o600
        and marker_identity["uid"] == os.getuid()
        and marker_identity["gid"] == os.getgid()
        and marker_identity["nlink"] == 1
        and marker_identity["size_bytes"] == 0,
        "unresolved operation marker object drifted",
    )
    return {
        **contract,
        "root": {**root, "identity": root_identity},
        "marker": {**marker, "identity": marker_identity},
        "unresolved_operation_contract_sha256": claimed,
    }


def _unresolved_resolution_guard_name(
    raw_contract: Mapping[str, object],
) -> str:
    contract = _validate_unresolved_operation_contract(raw_contract)
    marker = _mapping(contract["marker"], "unresolved operation marker")
    name = str(marker["name"]) + _UNRESOLVED_RESOLUTION_GUARD_SUFFIX
    _require(
        PurePosixPath(name).name == name
        and "/" not in name
        and "\\" not in name
        and "\0" not in name,
        "unresolved operation resolution guard name drifted",
    )
    return name


def _validate_unresolved_operation_root(
    raw_contract: Mapping[str, object],
    *,
    root_fd: int,
) -> dict[str, object]:
    contract = _validate_unresolved_operation_contract(raw_contract)
    root = _mapping(contract["root"], "unresolved operation root")
    try:
        root_handle = os.fstat(root_fd)
        root_named = os.stat(str(root["path"]), follow_symlinks=False)
    except OSError as error:
        raise ExecutorContractError(
            "cannot validate unresolved operation root custody"
        ) from error
    _require(
        _unresolved_directory_record(root_handle)
        == _unresolved_directory_record(root_named)
        == dict(_mapping(root["identity"], "unresolved operation root identity"))
        and _linux_fstatfs_magic(root_fd) == _LINUX_EXT_FILESYSTEM_MAGIC,
        "unresolved operation root custody drifted",
    )
    return contract


def _validate_unresolved_operation_marker(
    raw_contract: Mapping[str, object],
    *,
    root_fd: int,
    marker_fd: int,
    require_named: bool,
    named_name: str | None = None,
) -> dict[str, object]:
    contract = _validate_unresolved_operation_root(
        raw_contract,
        root_fd=root_fd,
    )
    marker = _mapping(contract["marker"], "unresolved operation marker")
    expected_named_name = (
        str(marker["name"])
        if named_name is None
        else named_name
    )
    _require(
        expected_named_name
        in {
            str(marker["name"]),
            _unresolved_resolution_guard_name(contract),
        },
        "unresolved operation marker named identity drifted",
    )
    try:
        marker_handle = os.fstat(marker_fd)
        marker_named = (
            os.stat(
                expected_named_name,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
            if require_named
            else None
        )
    except OSError as error:
        raise ExecutorContractError(
            "cannot validate unresolved operation marker custody"
        ) from error
    _require(
        _run_lease_leaf_matches(
            _mapping(marker["identity"], "unresolved operation marker identity"),
            marker_handle,
        )
        and (
            marker_named is None
            or _run_lease_leaf_matches(
                _mapping(
                    marker["identity"],
                    "unresolved operation marker identity",
                ),
                marker_named,
            )
        ),
        "unresolved operation marker custody drifted",
    )
    return contract


def _unresolved_marker_inode_matches(
    record: Mapping[str, object],
    state: os.stat_result,
    *,
    nlink: int,
) -> bool:
    expected = dict(record)
    expected["nlink"] = nlink
    return (
        _cleanup_mutex_file_record(state) == expected
        and stat.S_ISREG(state.st_mode)
        and stat.S_IMODE(state.st_mode) == 0o600
        and state.st_uid == os.getuid()
        and state.st_gid == os.getgid()
        and state.st_nlink == nlink
        and state.st_size == 0
    )


def _durably_resolve_unresolved_operation_marker(
    raw_contract: Mapping[str, object],
    *,
    root_fd: int,
    marker_fd: int | None,
) -> None:
    """Resolve via a durable same-inode guard before removing the witness."""

    contract = _validate_unresolved_operation_root(
        raw_contract,
        root_fd=root_fd,
    )
    marker = _mapping(contract["marker"], "unresolved operation marker")
    marker_identity = _mapping(
        marker["identity"],
        "unresolved operation marker identity",
    )
    marker_name = str(marker["name"])
    guard_name = _unresolved_resolution_guard_name(contract)

    def named_state(name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as error:
            wrapped = ExecutorContractError(
                "cannot inspect unresolved operation resolution state"
            )
            wrapped.__cause__ = error
            raise wrapped

    primary_state = named_state(marker_name)
    guard_state = named_state(guard_name)
    _require(
        primary_state is None or guard_state is None,
        "unresolved operation marker and resolution guard coexist",
    )
    local_marker_fd: int | None = None
    primary: BaseException | None = None
    close_failures: list[BaseException] = []
    try:
        if primary_state is None and guard_state is None:
            os.fsync(root_fd)
            _require(
                named_state(marker_name) is None
                and named_state(guard_name) is None,
                "resolved operation marker name reappeared",
            )
            if marker_fd is not None:
                _require(
                    _unresolved_marker_inode_matches(
                        marker_identity,
                        os.fstat(marker_fd),
                        nlink=0,
                    ),
                    "resolved operation marker inode drifted",
                )
            return

        active_name = marker_name if primary_state is not None else guard_name
        active_fd = marker_fd
        if active_fd is None:
            nofollow = getattr(os, "O_NOFOLLOW", 0)
            cloexec = getattr(os, "O_CLOEXEC", 0)
            _require(
                nofollow != 0 and cloexec != 0,
                "unresolved operation resolution no-follow custody is unavailable",
            )
            local_marker_fd = os.open(
                active_name,
                os.O_RDWR | nofollow | cloexec,
                dir_fd=root_fd,
            )
            active_fd = local_marker_fd
        _require(
            active_fd is not None,
            "unresolved operation resolution descriptor is unavailable",
        )
        _validate_unresolved_operation_marker(
            contract,
            root_fd=root_fd,
            marker_fd=active_fd,
            require_named=True,
            named_name=active_name,
        )
        if active_name == marker_name:
            os.rename(
                marker_name,
                guard_name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
            _require(
                named_state(marker_name) is None,
                "unresolved operation marker remained named after guard rename",
            )
            _validate_unresolved_operation_marker(
                contract,
                root_fd=root_fd,
                marker_fd=active_fd,
                require_named=True,
                named_name=guard_name,
            )

        # This fsync is the safety boundary: after it returns, a crash can
        # reveal either the guard or the later durable absence, never an empty
        # namespace whose primary-marker deletion was not committed.
        os.fsync(root_fd)
        _validate_unresolved_operation_marker(
            contract,
            root_fd=root_fd,
            marker_fd=active_fd,
            require_named=True,
            named_name=guard_name,
        )
        os.unlink(guard_name, dir_fd=root_fd)
        _require(
            named_state(guard_name) is None,
            "unresolved operation resolution guard remained named",
        )
        os.fsync(root_fd)
        _require(
            named_state(marker_name) is None
            and named_state(guard_name) is None
            and _unresolved_marker_inode_matches(
                marker_identity,
                os.fstat(active_fd),
                nlink=0,
            ),
            "resolved operation marker final custody drifted",
        )
    except BaseException as error:
        primary = error
    finally:
        if local_marker_fd is not None:
            try:
                os.close(local_marker_fd)
            except BaseException as error:
                close_failures.append(error)
    if primary is not None or close_failures:
        raise _DescriptorClosureError(
            operation="unresolved_operation_durable_resolution",
            primary=primary,
            close_failures=close_failures,
        ) from (primary if primary is not None else close_failures[0])


def _create_unresolved_operation_marker(
    *,
    run_lease: _RunLease,
    operation_kind: str,
    operation_id: str,
) -> _UnresolvedOperationMarkerReservation:
    _require(
        type(run_lease) is _RunLease and not run_lease.released,
        "unresolved operation requires an exact held run lease",
    )
    run_contract = _validate_run_lease_held(
        run_lease.contract,
        parent_fd=run_lease.parent_fd,
        identity_fd=run_lease.identity_fd,
        admission_fd=run_lease.admission_fd,
        retention_fd=run_lease.retention_fd,
        unresolved_root_fd=run_lease.unresolved_root_fd,
    )
    root = _mapping(run_contract["unresolved_root"], "unresolved operation root")
    name = _unresolved_marker_name(
        run_identity=str(run_contract["run_identity_sha256"]),
        operation_kind=operation_kind,
        operation_id=operation_id,
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    root_fd: int | None = None
    marker_fd: int | None = None
    try:
        root_fd = os.open(
            str(root["path"]),
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        _validate_run_lease_descriptors(
            run_contract,
            parent_fd=run_lease.parent_fd,
            descriptors={},
            unresolved_root_fd=root_fd,
        )
        marker_fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow | cloexec,
            0o600,
            dir_fd=root_fd,
        )
        os.fchmod(marker_fd, 0o600)
        os.fsync(marker_fd)
        os.fsync(root_fd)
        state = os.fstat(marker_fd)
        named = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        _require(
            _cleanup_mutex_file_record(state)
            == _cleanup_mutex_file_record(named)
            and _run_lease_leaf_matches(_cleanup_mutex_file_record(state), state),
            "unresolved operation marker creation drifted",
        )
        contract = _unresolved_operation_marker_contract(
            run_lease_contract=run_contract,
            operation_kind=operation_kind,
            operation_id=operation_id,
            marker_state=state,
        )
        reservation = _UnresolvedOperationMarkerReservation(
            contract=_validate_unresolved_operation_contract(contract),
            root_fd=root_fd,
            marker_fd=marker_fd,
        )
        root_fd = None
        marker_fd = None
        return reservation
    except FileExistsError as error:
        raise ExecutorContractError(
            "unresolved operation marker already exists"
        ) from error
    finally:
        active_error = sys.exception()
        close_failures: list[BaseException] = []
        if (
            active_error is not None
            and marker_fd is not None
            and root_fd is not None
        ):
            try:
                marker_handle = os.fstat(marker_fd)
                marker_named = os.stat(
                    name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                _require(
                    _cleanup_mutex_file_record(marker_handle)
                    == _cleanup_mutex_file_record(marker_named)
                    and _run_lease_leaf_matches(
                        _cleanup_mutex_file_record(marker_handle),
                        marker_handle,
                    ),
                    "failed unresolved marker creation custody drifted",
                )
                os.unlink(name, dir_fd=root_fd)
                os.fsync(root_fd)
                try:
                    os.stat(
                        name,
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise ExecutorContractError(
                        "failed unresolved marker remained named"
                    )
                _require(
                    os.fstat(marker_fd).st_nlink == 0,
                    "failed unresolved marker inode remained linked",
                )
            except BaseException as error:
                close_failures.append(error)
        for descriptor in (marker_fd, root_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if close_failures:
            raise _DescriptorClosureError(
                operation="unresolved_operation_marker_creation",
                primary=active_error,
                close_failures=close_failures,
            ) from (
                active_error if active_error is not None else close_failures[0]
            )


def _acquire_unresolved_operation_marker_hold(
    raw_contract: Mapping[str, object],
) -> _UnresolvedOperationMarkerHold:
    contract = _validate_unresolved_operation_contract(raw_contract)
    root = _mapping(contract["root"], "unresolved operation root")
    marker = _mapping(contract["marker"], "unresolved operation marker")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    root_fd: int | None = None
    marker_fd: int | None = None
    try:
        root_fd = os.open(
            str(root["path"]),
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        marker_fd = os.open(
            str(marker["name"]),
            os.O_RDWR | nofollow | cloexec,
            dir_fd=root_fd,
        )
        _validate_unresolved_operation_marker(
            contract,
            root_fd=root_fd,
            marker_fd=marker_fd,
            require_named=True,
        )
        result = _UnresolvedOperationMarkerHold(
            contract=contract,
            root_fd=root_fd,
            marker_fd=marker_fd,
        )
        root_fd = None
        marker_fd = None
        return result
    finally:
        active_error = sys.exception()
        close_failures: list[BaseException] = []
        for descriptor in (marker_fd, root_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException as error:
                close_failures.append(error)
        if close_failures:
            raise _DescriptorClosureError(
                operation="unresolved_operation_marker_hold_acquisition",
                primary=active_error,
                close_failures=close_failures,
            ) from (
                active_error if active_error is not None else close_failures[0]
            )


def _resolve_or_attest_unresolved_operation_marker(
    raw_contract: Mapping[str, object],
) -> None:
    """Resolve an exact named marker or attest a prior exact resolution."""

    contract = _validate_unresolved_operation_contract(raw_contract)
    root = _mapping(contract["root"], "unresolved operation root")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and directory != 0 and cloexec != 0,
        "unresolved operation resolution no-follow custody is unavailable",
    )
    root_fd: int | None = None
    primary: BaseException | None = None
    close_failures: list[BaseException] = []
    try:
        root_fd = os.open(
            str(root["path"]),
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        _durably_resolve_unresolved_operation_marker(
            contract,
            root_fd=root_fd,
            marker_fd=None,
        )
    except BaseException as error:
        primary = error
    finally:
        if root_fd is not None:
            try:
                os.close(root_fd)
            except BaseException as error:
                close_failures.append(error)
    if primary is not None or close_failures:
        raise _DescriptorClosureError(
            operation="unresolved_operation_resolution",
            primary=primary,
            close_failures=close_failures,
        ) from (primary if primary is not None else close_failures[0])


def _acquire_run_retention_hold(
    raw_contract: Mapping[str, object],
) -> _RunRetentionHold:
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "run retention requires Linux",
    )
    try:
        import fcntl
    except ImportError as error:
        raise ExecutorContractError("run retention flock is unavailable") from error
    contract = _validate_run_lease_contract(raw_contract)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and directory != 0 and cloexec != 0,
        "run retention no-follow custody is unavailable",
    )
    parent_fd: int | None = None
    retention_fd: int | None = None
    locked = False
    try:
        parent_fd = os.open(
            str(contract["parent_path"]),
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        retention = _mapping(contract["retention"], "run lease retention")
        retention_fd = os.open(
            str(retention["name"]),
            os.O_RDWR | nofollow | cloexec,
            dir_fd=parent_fd,
        )
        _validate_run_retention_hold(
            contract,
            parent_fd=parent_fd,
            retention_fd=retention_fd,
        )
        deadline = time.monotonic() + _RUN_LEASE_ACQUIRE_SECONDS
        while True:
            try:
                fcntl.flock(retention_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                _require(
                    time.monotonic() < deadline,
                    "run retention acquisition timed out",
                )
                time.sleep(0.01)
        _validate_run_retention_hold(
            contract,
            parent_fd=parent_fd,
            retention_fd=retention_fd,
        )
        result = _RunRetentionHold(
            contract=contract,
            parent_fd=parent_fd,
            retention_fd=retention_fd,
        )
        parent_fd = None
        retention_fd = None
        return result
    except BaseException as primary:
        close_failures: list[BaseException] = []
        if retention_fd is not None:
            if locked:
                try:
                    fcntl.flock(retention_fd, fcntl.LOCK_UN)
                except BaseException as error:
                    close_failures.append(error)
            try:
                os.close(retention_fd)
            except BaseException as error:
                close_failures.append(error)
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_failures.append(error)
        if close_failures:
            raise _DescriptorClosureError(
                operation="run_retention_acquisition",
                primary=primary,
                close_failures=close_failures,
            ) from primary
        raise


def _run_lease_contract_from_actor(value: Any) -> dict[str, object]:
    contract = getattr(value, "contract", None)
    _require(isinstance(contract, Mapping), "run lease actor contract is unavailable")
    return _validate_run_lease_contract(contract)


def _acquire_run_lease(run_identity: str) -> _RunLease:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and _SHA_RE.fullmatch(run_identity) is not None,
        "run lease requires Linux and an exact identity",
    )
    try:
        import fcntl
    except ImportError as error:
        raise ExecutorContractError("POSIX run locking is unavailable") from error
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and directory != 0 and cloexec != 0,
        "run lease no-follow custody is unavailable",
    )
    parent_fd: int | None = None
    descriptors: dict[str, int] = {}
    states: dict[str, os.stat_result] = {}
    unresolved_root_fd: int | None = None
    locked: list[str] = []
    try:
        parent_fd = os.open(
            RUN_LEASE_PARENT,
            os.O_RDONLY | directory | nofollow | cloexec,
        )
        parent_state = os.fstat(parent_fd)
        parent_named = os.stat(RUN_LEASE_PARENT, follow_symlinks=False)
        _require(
            _cleanup_mutex_parent_record(parent_state)
            == _cleanup_mutex_parent_record(parent_named)
            and stat.S_ISDIR(parent_state.st_mode)
            and stat.S_IMODE(parent_state.st_mode) == 0o1777
            and parent_state.st_uid == 0
            and parent_state.st_gid == 0
            and _linux_fstatfs_magic(parent_fd) == _LINUX_EXT_FILESYSTEM_MAGIC,
            "run lease parent custody drifted",
        )
        paths = _run_lease_paths(run_identity)
        for kind in ("identity", "admission", "retention"):
            descriptor, state = _open_or_create_run_lease_leaf(
                parent_fd=parent_fd,
                name=paths[kind].name,
            )
            descriptors[kind] = descriptor
            states[kind] = state
        unresolved_root_fd, unresolved_root_state = (
            _open_or_create_unresolved_operation_root(parent_fd=parent_fd)
        )
        contract = _validate_run_lease_contract(
            _run_lease_contract(
                run_identity=run_identity,
                parent_state=parent_state,
                filesystem_magic=_LINUX_EXT_FILESYSTEM_MAGIC,
                leaf_states=states,
                unresolved_root_state=unresolved_root_state,
            )
        )
        _validate_run_lease_held(
            contract,
            parent_fd=parent_fd,
            identity_fd=descriptors["identity"],
            admission_fd=descriptors["admission"],
            retention_fd=descriptors["retention"],
            unresolved_root_fd=unresolved_root_fd,
        )
        try:
            fcntl.flock(
                descriptors["identity"], fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            locked.append("identity")
        except BlockingIOError as error:
            raise ExecutorContractError(
                "nonpublication run identity is already active"
            ) from error
        try:
            fcntl.flock(
                descriptors["admission"], fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            locked.append("admission")
        except BlockingIOError as error:
            raise ExecutorContractError(
                "nonpublication global admission is already active"
            ) from error
        try:
            fcntl.flock(
                descriptors["retention"], fcntl.LOCK_EX | fcntl.LOCK_NB
            )
            locked.append("retention")
        except BlockingIOError as error:
            raise ExecutorContractError(
                "retained cleanup ownership blocks global admission"
            ) from error
        _require(
            os.listdir(unresolved_root_fd) == [],
            "durable unresolved operation blocks global admission",
        )
        # A remains EX throughout the EX->SH conversion.  Every conforming
        # contender acquires A first, so the conversion's non-atomic kernel
        # implementation cannot open an admission gap.
        fcntl.flock(descriptors["retention"], fcntl.LOCK_SH | fcntl.LOCK_NB)
        _validate_run_lease_held(
            contract,
            parent_fd=parent_fd,
            identity_fd=descriptors["identity"],
            admission_fd=descriptors["admission"],
            retention_fd=descriptors["retention"],
            unresolved_root_fd=unresolved_root_fd,
        )
        result = _RunLease(
            contract=contract,
            parent_fd=parent_fd,
            identity_fd=descriptors["identity"],
            admission_fd=descriptors["admission"],
            retention_fd=descriptors["retention"],
            unresolved_root_fd=unresolved_root_fd,
        )
        parent_fd = None
        unresolved_root_fd = None
        descriptors = {}
        return result
    except BaseException as primary_error:
        close_errors: list[BaseException] = []
        for kind in reversed(("identity", "admission", "retention")):
            descriptor = descriptors.get(kind)
            if descriptor is None:
                continue
            if kind in locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except BaseException as error:
                    close_errors.append(error)
            try:
                os.close(descriptor)
            except BaseException as error:
                close_errors.append(error)
        if unresolved_root_fd is not None:
            try:
                os.close(unresolved_root_fd)
            except BaseException as error:
                close_errors.append(error)
        if parent_fd is not None:
            try:
                os.close(parent_fd)
            except BaseException as error:
                close_errors.append(error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="run_lease_acquisition",
                primary=primary_error,
                close_failures=close_errors,
                message="cannot acquire exact nonpublication run lease",
            ) from primary_error
        raise


@dataclass
class _ContainerWatchdogProcess:
    process: subprocess.Popen[bytes]
    control_fd: int
    closed: bool = False
    terminal_returncode: int | None = None
    cleanup_ownership_retained: bool = True
    create_dispatch_marked: bool = False
    create_terminal_marked: bool = False
    unresolved_operation_contract: Mapping[str, object] | None = None
    ambiguous_owner_detached: bool = False

    def _write_marker(self, marker: bytes) -> None:
        _require(
            not self.closed and marker in {b"D", b"T", b"N", b"C"},
            "container watchdog marker state drifted",
        )
        view = memoryview(marker)
        while view:
            written = os.write(self.control_fd, view)
            _require(written > 0, "container watchdog marker write stalled")
            view = view[written:]

    def mark_create_dispatch(self) -> None:
        _require(
            not self.create_dispatch_marked and not self.create_terminal_marked,
            "container watchdog create dispatch state drifted",
        )
        self._write_marker(b"D")
        self.create_dispatch_marked = True

    def mark_create_terminal(self) -> None:
        _require(
            self.create_dispatch_marked and not self.create_terminal_marked,
            "container watchdog create terminal state drifted",
        )
        self._write_marker(b"T")
        self.create_terminal_marked = True

    def _finish(self, marker: bytes) -> None:
        if self.closed:
            raise ExecutorContractError("container watchdog control is already closed")
        primary: BaseException | None = None
        cleanup_errors: list[BaseException] = []
        try:
            if marker:
                self._write_marker(marker)
        except BaseException as error:
            primary = error
        self.closed = True
        descriptor = self.control_fd
        self.control_fd = -1
        try:
            os.close(descriptor)
        except BaseException as error:
            cleanup_errors.append(error)
        returncode: int | None = None
        wait_failed = False
        try:
            returncode = self.process.wait(timeout=300.0)
        except BaseException as error:
            wait_failed = True
            if primary is None:
                primary = error
            else:
                cleanup_errors.append(error)
            try:
                polled = self.process.poll()
                if type(polled) is int:
                    returncode = polled
            except BaseException as poll_error:
                cleanup_errors.append(poll_error)
        self.terminal_returncode = returncode
        self.cleanup_ownership_retained = returncode is None
        completion_cleanup_attested = marker == b"C" and primary is None
        if wait_failed and returncode is None and completion_cleanup_attested:
            process_running = True
            try:
                process_running = self.process.poll() is None
            except BaseException as error:
                cleanup_errors.append(error)
            if process_running:
                try:
                    self.process.kill()
                except BaseException as error:
                    cleanup_errors.append(error)
                try:
                    returncode = self.process.wait(timeout=10.0)
                    self.terminal_returncode = returncode
                    self.cleanup_ownership_retained = False
                except BaseException as error:
                    cleanup_errors.append(error)
        elif wait_failed and returncode is None:
            cleanup_errors.append(
                ExecutorContractError(
                    "container watchdog retains cleanup ownership after bounded wait failure"
                )
            )
        if returncode is not None and returncode != 0:
            cleanup_errors.append(
                _WatchdogChildExitError(
                    watchdog_kind="owned_container",
                    returncode=returncode,
                )
            )
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="container_watchdog_finish",
                primary=primary,
                close_failures=cleanup_errors,
                message="container watchdog terminal cleanup failed",
            ) from (primary if primary is not None else cleanup_errors[0])
        if primary is not None:
            raise primary

    def complete(self) -> None:
        self._finish(b"C")

    def abort(self) -> None:
        self._finish(
            b""
            if self.create_dispatch_marked and not self.create_terminal_marked
            else b"N"
        )

    def detach_ambiguous_owner(self) -> None:
        _require(
            not self.closed
            and self.create_dispatch_marked
            and not self.create_terminal_marked
            and self.unresolved_operation_contract is not None,
            "container watchdog ambiguous detach state drifted",
        )
        self.closed = True
        descriptor = self.control_fd
        self.control_fd = -1
        primary: BaseException | None = None
        try:
            os.close(descriptor)
        except BaseException as error:
            primary = error
        returncode: int | None = None
        try:
            observed = self.process.poll()
            if type(observed) is int:
                returncode = observed
        except BaseException as error:
            if primary is None:
                primary = error
            else:
                primary = _DescriptorClosureError(
                    operation="container_watchdog_ambiguous_detach",
                    primary=primary,
                    close_failures=[error],
                )
        self.terminal_returncode = returncode
        self.cleanup_ownership_retained = returncode is None
        self.ambiguous_owner_detached = returncode is None
        if returncode is not None:
            child_error = _WatchdogChildExitError(
                watchdog_kind="owned_container_ambiguous_guardian",
                returncode=returncode,
            )
            if primary is None:
                primary = child_error
            else:
                primary = _DescriptorClosureError(
                    operation="container_watchdog_ambiguous_detach",
                    primary=primary,
                    close_failures=[child_error],
                )
        if primary is not None:
            raise primary


class _DockerPathRunner:
    def __init__(self, docker_cli: Path) -> None:
        self._docker_cli = str(docker_cli)
        self._delegate = _BoundedCommandRunner()

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: float,
        stdout_limit: int,
        stderr_limit: int,
    ) -> CommandCapture:
        _require(bool(argv) and argv[0] == DOCKER_CLI, "watchdog Docker argv drifted")
        return self._delegate.run(
            [self._docker_cli, *argv[1:]],
            timeout_seconds=timeout_seconds,
            stdout_limit=stdout_limit,
            stderr_limit=stderr_limit,
        )


def _write_watchdog_contract(descriptor: int, contract: Mapping[str, object]) -> None:
    payload = canonical_line(contract)
    _require(len(payload) <= 64 * 1024, "container watchdog contract overflowed")
    framed = len(payload).to_bytes(4, "big") + payload
    try:
        view = memoryview(framed)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "container watchdog contract write stalled")
            view = view[written:]
    except OSError as error:
        raise ExecutorContractError("cannot send container watchdog contract") from error


def _read_exact_fd(descriptor: int, count: int) -> bytes:
    value = bytearray()
    try:
        while len(value) < count:
            chunk = os.read(descriptor, count - len(value))
            if not chunk:
                raise ExecutorContractError("container watchdog contract is partial")
            value.extend(chunk)
    except OSError as error:
        raise ExecutorContractError("cannot read container watchdog control") from error
    return bytes(value)


def _watchdog_stat_record(value: os.stat_result) -> dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "uid": int(value.st_uid),
        "gid": int(value.st_gid),
        "nlink": int(value.st_nlink),
    }


def _validate_watchdog_stat_record(value: Any, label: str) -> dict[str, int]:
    record = dict(_mapping(value, label))
    _require(
        set(record) == {"device", "inode", "mode", "uid", "gid", "nlink"}
        and all(type(item) is int and item >= 0 for item in record.values())
        and record["device"] > 0
        and record["inode"] > 0,
        f"{label} fields drifted",
    )
    return {key: int(item) for key, item in record.items()}


def _watchdog_record_matches(
    record: Mapping[str, int],
    value: os.stat_result,
    *,
    check_nlink: bool,
) -> bool:
    observed = _watchdog_stat_record(value)
    if not check_nlink:
        observed["nlink"] = int(record["nlink"])
    return observed == dict(record)


def _write_ipc_watchdog_frame(descriptor: int, core: Mapping[str, object]) -> None:
    value = {
        **dict(core),
        "self_sha256": hashlib.sha256(
            IPC_WATCHDOG_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }
    payload = canonical_line(value)
    try:
        pipe_buf = int(os.fpathconf(descriptor, "PC_PIPE_BUF"))
    except (AttributeError, OSError, ValueError) as error:
        raise ExecutorContractError("cannot attest IPC watchdog pipe framing") from error
    _require(
        512 <= pipe_buf
        and 0 < len(payload) <= 64 * 1024
        and len(payload) + 4 <= pipe_buf,
        "IPC watchdog frame overflowed its atomic pipe bound",
    )
    try:
        view = memoryview(len(payload).to_bytes(4, "big") + payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "IPC watchdog frame write stalled")
            view = view[written:]
    except OSError as error:
        raise ExecutorContractError("cannot send IPC watchdog frame") from error


def _read_ipc_watchdog_frame_or_eof(descriptor: int) -> dict[str, object] | None:
    header = bytearray()
    try:
        while len(header) < 4:
            chunk = os.read(descriptor, 4 - len(header))
            if not chunk:
                _require(not header, "IPC watchdog frame header is partial")
                return None
            header.extend(chunk)
    except OSError as error:
        raise ExecutorContractError("cannot read IPC watchdog frame header") from error
    length = int.from_bytes(header, "big")
    _require(0 < length <= 64 * 1024, "IPC watchdog frame length drifted")
    value = dict(
        _mapping(
            _parse_json(_read_exact_fd(descriptor, length), "IPC watchdog frame"),
            "IPC watchdog frame",
        )
    )
    claimed = value.pop("self_sha256", None)
    _require(
        type(claimed) is str
        and claimed
        == hashlib.sha256(IPC_WATCHDOG_DOMAIN + canonical_line(value)).hexdigest(),
        "IPC watchdog frame identity drifted",
    )
    return value


def _wait_ipc_watchdog_byte(descriptor: int, expected: bytes) -> None:
    selector = selectors.DefaultSelector()
    primary: BaseException | None = None
    try:
        selector.register(descriptor, selectors.EVENT_READ)
        events = selector.select(30.0)
        _require(bool(events), "IPC watchdog acknowledgement timed out")
        value = os.read(descriptor, 2)
        _require(value == expected, "IPC watchdog acknowledgement drifted")
    except OSError as error:
        primary = ExecutorContractError(
            "cannot receive IPC watchdog acknowledgement"
        )
        primary.__cause__ = error
    except BaseException as error:
        primary = error
    finally:
        close_errors: list[BaseException] = []
        try:
            selector.close()
        except BaseException as error:
            close_errors.append(error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="ipc_watchdog_acknowledgement_wait",
                primary=primary,
                close_failures=close_errors,
            ) from (primary if primary is not None else close_errors[0])
    if primary is not None:
        raise primary


def _close_ipc_watchdog_transport(
    handle: _IpcRuntimeWatchdogProcess,
) -> tuple[BaseException, ...]:
    errors: list[BaseException] = []
    for attribute in ("control_fd", "ack_fd"):
        descriptor = getattr(handle, attribute)
        if descriptor < 0:
            continue
        setattr(handle, attribute, -1)
        try:
            os.close(descriptor)
        except BaseException as error:
            errors.append(error)
    return tuple(errors)


def _poison_ipc_watchdog_transport(
    handle: _IpcRuntimeWatchdogProcess,
) -> tuple[BaseException, ...]:
    handle.protocol_poisoned = True
    return _close_ipc_watchdog_transport(handle)


def _ipc_watchdog_roundtrip(
    handle: _IpcRuntimeWatchdogProcess,
    core: Mapping[str, object],
) -> None:
    _require(
        type(handle) is _IpcRuntimeWatchdogProcess
        and not handle.closed
        and not handle.protocol_poisoned
        and handle.process.poll() is None,
        "IPC watchdog process is unavailable",
    )
    try:
        _write_ipc_watchdog_frame(handle.control_fd, core)
        _wait_ipc_watchdog_byte(handle.ack_fd, b"K")
        observed = handle.process.poll()
        terminal = core.get("action") in {"complete", "abort"}
        _require(
            observed is None or (terminal and observed == 0),
            "IPC watchdog exited after acknowledgement",
        )
    except BaseException as error:
        close_errors = _poison_ipc_watchdog_transport(handle)
        raise _DescriptorClosureError(
            operation="ipc_watchdog_roundtrip",
            primary=error,
            close_failures=close_errors,
            message=(
                "IPC watchdog control became commit-ambiguous and could not close"
                if close_errors
                else "IPC watchdog control became commit-ambiguous"
            ),
        ) from error


def _ipc_watchdog_provision_request(
    run_identity: str,
    *,
    parent: Path,
    run_lease_contract: Mapping[str, object],
    unresolved_operation_contract: Mapping[str, object],
) -> dict[str, object]:
    root = _ipc_runtime_path(run_identity, parent=parent)
    validated_run_lease = _validate_run_lease_contract(run_lease_contract)
    validated_unresolved_operation = (
        _validate_unresolved_operation_contract(
            unresolved_operation_contract
        )
    )
    _require(
        validated_run_lease.get("run_identity_sha256") == run_identity
        and validated_unresolved_operation.get("run_identity_sha256")
        == run_identity
        and validated_unresolved_operation.get("operation_kind")
        == "ipc_namespace"
        and validated_unresolved_operation.get("operation_id")
        == _ipc_unresolved_operation_id(run_identity, parent=parent)
        and validated_unresolved_operation.get("root")
        == validated_run_lease.get("unresolved_root"),
        "IPC watchdog run lease or unresolved-operation identity drifted",
    )
    return {
        "schema_version": 3,
        "artifact_kind": "vast_nonpublication_ipc_watchdog_provision_v3",
        "action": "provision_create_new",
        "run_identity": run_identity,
        "parent_path": str(parent),
        "root_path": str(root),
        "root_name": root.name,
        "run_lease": validated_run_lease,
        "unresolved_operation": validated_unresolved_operation,
    }


def _validate_ipc_watchdog_provision_request(
    value: Mapping[str, object],
    *,
    run_identity: str,
    parent: Path,
    run_lease_contract: Mapping[str, object],
    unresolved_operation_contract: Mapping[str, object],
) -> dict[str, object]:
    expected = _ipc_watchdog_provision_request(
        run_identity,
        parent=parent,
        run_lease_contract=run_lease_contract,
        unresolved_operation_contract=unresolved_operation_contract,
    )
    _require(
        type(value) is dict and dict(value) == expected,
        "IPC watchdog provision request drifted",
    )
    return expected


def _ipc_watchdog_readiness(namespace: _IpcRuntimeNamespace) -> dict[str, object]:
    _validate_ipc_runtime_namespace(namespace)
    return {
        "schema_version": 1,
        "artifact_kind": "vast_nonpublication_ipc_watchdog_ready_v1",
        "run_identity": namespace.run_identity,
        "parent_path": str(namespace.parent_path),
        "root_path": str(namespace.path),
        "root_name": namespace.name,
        "filesystem_magic": namespace.filesystem_magic,
        "parent_identity": _watchdog_stat_record(os.fstat(namespace.parent_fd)),
        "root_identity": _watchdog_stat_record(os.fstat(namespace.root_fd)),
        "allowed_socket_names": [f"{branch}.sock" for branch in BRANCHES],
    }


def _validate_ipc_watchdog_readiness(
    value: Mapping[str, object],
    *,
    run_identity: str,
    parent: Path,
) -> dict[str, object]:
    ready = dict(value)
    _require(
        set(ready)
        == {
            "schema_version",
            "artifact_kind",
            "run_identity",
            "parent_path",
            "root_path",
            "root_name",
            "filesystem_magic",
            "parent_identity",
            "root_identity",
            "allowed_socket_names",
        }
        and ready.get("schema_version") == 1
        and ready.get("artifact_kind")
        == "vast_nonpublication_ipc_watchdog_ready_v1",
        "IPC watchdog readiness fields drifted",
    )
    expected_root = _ipc_runtime_path(run_identity, parent=parent)
    _require(
        ready.get("run_identity") == run_identity
        and ready.get("parent_path") == str(parent)
        and ready.get("root_path") == str(expected_root)
        and ready.get("root_name") == expected_root.name
        and ready.get("filesystem_magic") == _LINUX_EXT_FILESYSTEM_MAGIC
        and ready.get("allowed_socket_names")
        == [f"{branch}.sock" for branch in BRANCHES],
        "IPC watchdog readiness namespace drifted",
    )
    parent_identity = _validate_watchdog_stat_record(
        ready.get("parent_identity"),
        "IPC watchdog readiness parent identity",
    )
    root_identity = _validate_watchdog_stat_record(
        ready.get("root_identity"),
        "IPC watchdog readiness root identity",
    )
    _require(
        stat.S_ISDIR(parent_identity["mode"])
        and stat.S_ISDIR(root_identity["mode"])
        and stat.S_IMODE(root_identity["mode"]) == 0o700
        and root_identity["uid"] == os.getuid()
        and root_identity["gid"] == os.getgid()
        and root_identity["nlink"] == 2,
        "IPC watchdog readiness object type drifted",
    )
    return {
        **ready,
        "parent_identity": parent_identity,
        "root_identity": root_identity,
    }


def _open_ipc_runtime_namespace_from_readiness(
    value: Mapping[str, object],
    *,
    run_identity: str,
    parent: Path,
) -> _IpcRuntimeNamespace:
    ready = _validate_ipc_watchdog_readiness(
        value,
        run_identity=run_identity,
        parent=parent,
    )
    root = _ipc_runtime_path(run_identity, parent=parent)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        os.name == "posix" and nofollow != 0 and directory != 0,
        "POSIX IPC no-follow custody is unavailable",
    )
    parent_fd: int | None = None
    root_fd: int | None = None
    try:
        parent_fd = os.open(parent, os.O_RDONLY | directory | nofollow | cloexec)
        root_fd = os.open(
            root.name,
            os.O_RDONLY | directory | nofollow | cloexec,
            dir_fd=parent_fd,
        )
        parent_handle = os.fstat(parent_fd)
        root_handle = os.fstat(root_fd)
        parent_named = parent.lstat()
        root_named = os.stat(root.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_record = _mapping(
            ready["parent_identity"],
            "IPC watchdog readiness parent identity",
        )
        root_record = _mapping(
            ready["root_identity"],
            "IPC watchdog readiness root identity",
        )
        _require(
            _watchdog_record_matches(parent_record, parent_handle, check_nlink=False)
            and _watchdog_record_matches(parent_record, parent_named, check_nlink=False)
            and _watchdog_record_matches(root_record, root_handle, check_nlink=True)
            and _watchdog_record_matches(root_record, root_named, check_nlink=True)
            and _linux_fstatfs_magic(root_fd) == _LINUX_EXT_FILESYSTEM_MAGIC,
            "IPC watchdog readiness custody drifted",
        )
        namespace = _IpcRuntimeNamespace(
            run_identity=run_identity,
            path=root,
            parent_path=parent,
            name=root.name,
            parent_fd=parent_fd,
            root_fd=root_fd,
            parent_identity=_directory_identity(parent_handle),
            root_identity=_directory_identity(root_handle),
            filesystem_magic=_LINUX_EXT_FILESYSTEM_MAGIC,
            watchdog_owned=True,
        )
        _validate_ipc_runtime_namespace(namespace)
        parent_fd = None
        root_fd = None
        return namespace
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError("cannot hold watchdog-created IPC namespace") from error
    finally:
        active_error = sys.exception()
        close_errors: list[BaseException] = []
        for descriptor in (root_fd, parent_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException as error:
                    close_errors.append(error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="ipc_watchdog_readiness_namespace_open",
                primary=active_error,
                close_failures=close_errors,
                message="cannot hold watchdog-created IPC namespace",
            ) from (
                active_error if active_error is not None else close_errors[0]
            )


def _ipc_watchdog_contract(namespace: _IpcRuntimeNamespace) -> dict[str, object]:
    _validate_ipc_runtime_namespace(namespace)
    return {
        "schema_version": 1,
        "artifact_kind": "vast_nonpublication_ipc_runtime_watchdog_v1",
        "run_identity": namespace.run_identity,
        "parent_fd": namespace.parent_fd,
        "root_fd": namespace.root_fd,
        "parent_path": str(namespace.parent_path),
        "root_path": str(namespace.path),
        "root_name": namespace.name,
        "filesystem_magic": namespace.filesystem_magic,
        "parent_identity": _watchdog_stat_record(os.fstat(namespace.parent_fd)),
        "root_identity": _watchdog_stat_record(os.fstat(namespace.root_fd)),
        "allowed_socket_names": [f"{branch}.sock" for branch in BRANCHES],
    }


def _validate_ipc_watchdog_contract(
    value: Mapping[str, object],
    *,
    parent_fd: int,
    root_fd: int,
) -> dict[str, object]:
    contract = dict(value)
    _require(
        set(contract)
        == {
            "schema_version",
            "artifact_kind",
            "run_identity",
            "parent_fd",
            "root_fd",
            "parent_path",
            "root_path",
            "root_name",
            "filesystem_magic",
            "parent_identity",
            "root_identity",
            "allowed_socket_names",
        }
        and contract.get("schema_version") == 1
        and contract.get("artifact_kind")
        == "vast_nonpublication_ipc_runtime_watchdog_v1",
        "IPC watchdog contract fields drifted",
    )
    run_identity = contract.get("run_identity")
    parent_path = contract.get("parent_path")
    root_path = contract.get("root_path")
    root_name = contract.get("root_name")
    _require(
        type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and type(parent_path) is str
        and PurePosixPath(parent_path).is_absolute()
        and ".." not in PurePosixPath(parent_path).parts
        and type(root_path) is str
        and type(root_name) is str
        and type(contract.get("parent_fd")) is int
        and type(contract.get("root_fd")) is int
        and contract["parent_fd"] == parent_fd
        and contract["root_fd"] == root_fd
        and parent_fd > 2
        and root_fd > 2
        and parent_fd != root_fd,
        "IPC watchdog contract path or descriptor drifted",
    )
    expected_root = _ipc_runtime_path(run_identity, parent=Path(parent_path))
    _require(
        str(expected_root) == root_path
        and expected_root.name == root_name
        and contract.get("filesystem_magic") == _LINUX_EXT_FILESYSTEM_MAGIC
        and contract.get("allowed_socket_names")
        == [f"{branch}.sock" for branch in BRANCHES],
        "IPC watchdog contract namespace drifted",
    )
    parent_identity = _validate_watchdog_stat_record(
        contract.get("parent_identity"),
        "IPC watchdog parent identity",
    )
    root_identity = _validate_watchdog_stat_record(
        contract.get("root_identity"),
        "IPC watchdog root identity",
    )
    _require(
        stat.S_ISDIR(parent_identity["mode"])
        and stat.S_ISDIR(root_identity["mode"])
        and stat.S_IMODE(root_identity["mode"]) == 0o700
        and root_identity["uid"] == os.getuid()
        and root_identity["gid"] == os.getgid()
        and root_identity["nlink"] == 2,
        "IPC watchdog directory identity drifted",
    )
    return {
        **contract,
        "parent_identity": parent_identity,
        "root_identity": root_identity,
    }


def _validate_ipc_watchdog_root_handles(contract: Mapping[str, object]) -> None:
    parent_fd = int(contract["parent_fd"])
    root_fd = int(contract["root_fd"])
    parent_record = _mapping(contract["parent_identity"], "IPC watchdog parent identity")
    root_record = _mapping(contract["root_identity"], "IPC watchdog root identity")
    try:
        parent_handle = os.fstat(parent_fd)
        root_handle = os.fstat(root_fd)
        parent_path = Path(str(contract["parent_path"])).lstat()
        root_path = Path(str(contract["root_path"])).lstat()
        root_named = os.stat(
            str(contract["root_name"]),
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        raise ExecutorContractError("cannot validate IPC watchdog held root") from error
    _require(
        _watchdog_record_matches(parent_record, parent_handle, check_nlink=False)
        and _watchdog_record_matches(parent_record, parent_path, check_nlink=False)
        and _watchdog_record_matches(root_record, root_handle, check_nlink=True)
        and _watchdog_record_matches(root_record, root_path, check_nlink=True)
        and _watchdog_record_matches(root_record, root_named, check_nlink=True)
        and _linux_fstatfs_magic(root_fd) == contract["filesystem_magic"],
        "IPC watchdog held root identity drifted",
    )


def _validate_ipc_watchdog_control(
    value: Mapping[str, object],
    *,
    sequence: int,
) -> dict[str, object]:
    message = dict(value)
    _require(
        set(message)
        == {
            "schema_version",
            "artifact_kind",
            "sequence",
            "action",
            "branch",
            "socket_identity",
        }
        and message.get("schema_version") == 1
        and message.get("artifact_kind")
        == "vast_nonpublication_ipc_watchdog_control_v1"
        and type(message.get("sequence")) is int
        and message.get("sequence") == sequence,
        "IPC watchdog control fields drifted",
    )
    action = message.get("action")
    branch = message.get("branch")
    if type(action) is str and action in {"register", "release"}:
        _require(
            type(branch) is str and branch in BRANCHES,
            "IPC watchdog control branch drifted",
        )
        message["socket_identity"] = _validate_watchdog_stat_record(
            message.get("socket_identity"),
            "IPC watchdog control socket identity",
        )
    else:
        _require(
            type(action) is str
            and action in {"complete", "abort"}
            and branch is None
            and message.get("socket_identity") is None,
            "IPC watchdog terminal control drifted",
        )
    return message


def _ipc_watchdog_remove_owned_namespace(
    contract: Mapping[str, object],
    registered: Mapping[str, Mapping[str, int]],
    *,
    require_empty: bool,
) -> None:
    _validate_ipc_watchdog_root_handles(contract)
    root_fd = int(contract["root_fd"])
    parent_fd = int(contract["parent_fd"])
    names = os.listdir(root_fd)
    allowed = set(str(item) for item in contract["allowed_socket_names"])
    registered_names = {f"{branch}.sock" for branch in registered}
    failures: list[BaseException] = []
    try:
        _require(
            len(names) == len(set(names))
            and set(names) <= allowed
            and registered_names <= set(names)
            and (not require_empty or not names)
            and (not require_empty or not registered),
            "IPC watchdog namespace contains unowned entries",
        )
    except BaseException as error:
        failures.append(error)
    observations: dict[str, os.stat_result] = {}
    for name in sorted(set(names) & allowed):
        observed: os.stat_result | None = None
        try:
            observed = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        except OSError as error:
            wrapped = ExecutorContractError("cannot inspect IPC watchdog socket")
            wrapped.__cause__ = error
            failures.append(wrapped)
            continue
        branch = name.removesuffix(".sock")
        record = registered.get(branch)
        try:
            if record is None:
                _require(
                    stat.S_ISSOCK(observed.st_mode)
                    and stat.S_IMODE(observed.st_mode) == 0o600
                    and observed.st_uid == os.getuid()
                    and observed.st_gid == os.getgid()
                    and observed.st_nlink == 1,
                    "unregistered IPC watchdog socket identity drifted",
                )
            else:
                _require(
                    _watchdog_record_matches(record, observed, check_nlink=True),
                    "registered IPC watchdog socket identity drifted",
                )
        except BaseException as error:
            failures.append(error)
            continue
        observations[name] = observed
    for name in sorted(observations):
        try:
            os.unlink(name, dir_fd=root_fd)
        except OSError as error:
            wrapped = ExecutorContractError("cannot remove IPC watchdog socket")
            wrapped.__cause__ = error
            failures.append(wrapped)
    root_fsync_attested = False
    try:
        os.fsync(root_fd)
        root_fsync_attested = True
    except OSError as error:
        wrapped = ExecutorContractError(
            "cannot persist IPC watchdog socket cleanup"
        )
        wrapped.__cause__ = error
        failures.append(wrapped)
    root_empty = False
    try:
        root_empty = not os.listdir(root_fd)
        _require(root_empty, "IPC watchdog root remained nonempty")
    except BaseException as error:
        failures.append(error)
    root_unlinked = False
    if root_empty and root_fsync_attested:
        while True:
            try:
                _validate_ipc_watchdog_root_handles(contract)
                _require(
                    not os.listdir(root_fd),
                    "IPC watchdog root changed before removal",
                )
                os.rmdir(str(contract["root_name"]), dir_fd=parent_fd)
                os.fsync(parent_fd)
                root_unlinked = True
                break
            except OSError as error:
                if error.errno not in {errno.EBUSY, errno.ENOTEMPTY}:
                    wrapped = ExecutorContractError(
                        "cannot remove IPC watchdog root"
                    )
                    wrapped.__cause__ = error
                    failures.append(wrapped)
                    break
                try:
                    _require(
                        not os.listdir(root_fd),
                        "IPC watchdog root gained entries while awaiting mount release",
                    )
                except BaseException as retry_error:
                    failures.append(retry_error)
                    break
                # The independent guardian owns both the retention SH lock and
                # the unresolved marker.  A transient mount hold must not turn
                # into an ownerless marker after an arbitrary wall-clock bound.
                time.sleep(0.05)
            except BaseException as error:
                failures.append(error)
                break
    try:
        final = os.fstat(root_fd)
        root_record = _mapping(
            contract["root_identity"], "IPC watchdog root identity"
        )
        _require(
            root_unlinked
            and _watchdog_record_matches(root_record, final, check_nlink=False)
            and final.st_nlink == 0
            and not os.listdir(root_fd),
            "IPC watchdog root did not become empty and unlinked",
        )
    except BaseException as error:
        failures.append(error)
    if failures:
        first, *remaining = failures
        raise _DescriptorClosureError(
            operation="ipc_watchdog_namespace_cleanup",
            primary=first,
            close_failures=remaining,
            message="IPC watchdog namespace cleanup was incomplete",
        ) from first


def _wait_ipc_watchdog_frame(descriptor: int) -> dict[str, object]:
    selector = selectors.DefaultSelector()
    primary: BaseException | None = None
    result: dict[str, object] | None = None
    try:
        selector.register(descriptor, selectors.EVENT_READ)
        events = selector.select(30.0)
        _require(bool(events), "IPC watchdog readiness timed out")
        value = _read_ipc_watchdog_frame_or_eof(descriptor)
        _require(value is not None, "IPC watchdog readiness is absent")
        result = value
    except BaseException as error:
        primary = error
    finally:
        close_errors: list[BaseException] = []
        try:
            selector.close()
        except BaseException as error:
            close_errors.append(error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="ipc_watchdog_readiness_wait",
                primary=primary,
                close_failures=close_errors,
            ) from (primary if primary is not None else close_errors[0])
    if primary is not None:
        raise primary
    _require(result is not None, "IPC watchdog readiness is unavailable")
    return result


def _spawn_ipc_runtime_watchdog(
    run_identity: str,
    *,
    run_lease: Any,
    parent: Path = IPC_RUNTIME_PARENT,
    _after_arm_before_provision: Callable[[int], None] | None = None,
    _after_provision_before_ready: Callable[[int], None] | None = None,
) -> _IpcRuntimeWatchdogProcess:
    _ipc_runtime_path(run_identity, parent=parent)
    _require(
        type(run_lease) is _RunLease and not run_lease.released,
        "IPC watchdog requires exact run lease ownership",
    )
    run_lease_contract = _run_lease_contract_from_actor(run_lease)
    _require(
        run_lease_contract.get("run_identity_sha256") == run_identity,
        "IPC watchdog run lease identity drifted",
    )
    # Reject a statically unsupported parent before pipes, process creation,
    # provisioning, or the durable unresolved-operation marker.  Any drift
    # after this point is still guarded by the child and retained marker.
    _attest_native_ipc_runtime_parent(parent=parent)
    control_read_fd = -1
    control_write_fd = -1
    ack_read_fd = -1
    ack_write_fd = -1
    process: subprocess.Popen[bytes] | None = None
    namespace: _IpcRuntimeNamespace | None = None
    unresolved_reservation: _UnresolvedOperationMarkerReservation | None = None
    unresolved_reservation_closed = False
    provision_may_have_been_sent = False
    try:
        control_read_fd, control_write_fd = os.pipe()
        ack_read_fd, ack_write_fd = os.pipe()
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "__owned_ipc_watchdog_v3",
                str(control_read_fd),
                str(ack_write_fd),
                run_identity,
                str(parent),
            ],
            shell=False,
            env={},
            cwd="/",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(
                control_read_fd,
                ack_write_fd,
            ),
            start_new_session=True,
        )
        descriptor = control_read_fd
        control_read_fd = -1
        os.close(descriptor)
        descriptor = ack_write_fd
        ack_write_fd = -1
        os.close(descriptor)
        _wait_ipc_watchdog_byte(ack_read_fd, b"A")
        if _after_arm_before_provision is not None:
            _after_arm_before_provision(process.pid)
        unresolved_reservation = run_lease.create_unresolved_ipc_marker(
            parent=parent
        )
        provision_may_have_been_sent = True
        _write_ipc_watchdog_frame(
            control_write_fd,
            _ipc_watchdog_provision_request(
                run_identity,
                parent=parent,
                run_lease_contract=run_lease_contract,
                unresolved_operation_contract=(
                    unresolved_reservation.contract
                ),
            ),
        )
        unresolved_reservation.close()
        unresolved_reservation_closed = True
        if _after_provision_before_ready is not None:
            _after_provision_before_ready(process.pid)
        ready = _wait_ipc_watchdog_frame(ack_read_fd)
        namespace = _open_ipc_runtime_namespace_from_readiness(
            ready,
            run_identity=run_identity,
            parent=parent,
        )
        namespace.unresolved_operation_contract = dict(
            unresolved_reservation.contract
        )
        _require(process.poll() is None, "IPC watchdog exited after readiness")
        handle = _IpcRuntimeWatchdogProcess(
            process=process,
            control_fd=control_write_fd,
            ack_fd=ack_read_fd,
            namespace=namespace,
        )
        control_write_fd = -1
        ack_read_fd = -1
        namespace = None
        return handle
    except BaseException as primary_error:
        cleanup_errors: list[BaseException] = []
        for field_name in (
            "control_write_fd",
            "control_read_fd",
            "ack_read_fd",
            "ack_write_fd",
        ):
            descriptor = locals()[field_name]
            if descriptor >= 0:
                if field_name == "control_write_fd":
                    control_write_fd = -1
                elif field_name == "control_read_fd":
                    control_read_fd = -1
                elif field_name == "ack_read_fd":
                    ack_read_fd = -1
                else:
                    ack_write_fd = -1
                try:
                    os.close(descriptor)
                except BaseException as error:
                    cleanup_errors.append(error)
        child_returncode: int | None = None
        if process is not None:
            try:
                child_returncode = process.wait(
                    timeout=_IPC_WATCHDOG_CHILD_WAIT_SECONDS
                )
            except BaseException as error:
                cleanup_errors.append(error)
                process_running = True
                try:
                    polled = process.poll()
                    process_running = polled is None
                    if type(polled) is int:
                        child_returncode = polled
                except BaseException as poll_error:
                    cleanup_errors.append(poll_error)
                if process_running and not provision_may_have_been_sent:
                    try:
                        process.kill()
                    except BaseException as kill_error:
                        cleanup_errors.append(kill_error)
                    try:
                        child_returncode = process.wait(timeout=10.0)
                    except BaseException as reap_error:
                        cleanup_errors.append(reap_error)
                elif process_running:
                    cleanup_errors.append(
                        ExecutorContractError(
                            "IPC watchdog retains namespace cleanup ownership after provisioning"
                        )
                    )
        if namespace is not None:
            if child_returncode is not None:
                namespace_attested = False
                try:
                    _attest_ipc_watchdog_namespace_unlinked(namespace)
                    namespace_attested = True
                except BaseException as error:
                    cleanup_errors.append(error)
                if not namespace_attested:
                    namespace.watchdog_owned = False
                try:
                    _destroy_ipc_runtime_namespace(namespace)
                except BaseException as error:
                    cleanup_errors.append(error)
                if child_returncode != 0:
                    cleanup_errors.append(
                        _WatchdogChildExitError(
                            watchdog_kind="ipc_runtime",
                            returncode=child_returncode,
                        )
                    )
            else:
                # A live/unknown provisioned child retains sole cleanup
                # ownership.  Close only this controller's duplicate handles.
                namespace.closed = True
                for descriptor in (namespace.root_fd, namespace.parent_fd):
                    try:
                        os.close(descriptor)
                    except BaseException as error:
                        cleanup_errors.append(error)
        elif (
            unresolved_reservation is not None
            and child_returncode is not None
        ):
            try:
                _durably_attest_ipc_namespace_absent(
                    run_identity,
                    parent=parent,
                )
                _resolve_or_attest_unresolved_operation_marker(
                    unresolved_reservation.contract
                )
                unresolved_reservation.resolved = True
            except BaseException as error:
                cleanup_errors.append(error)
        if (
            unresolved_reservation is not None
            and not unresolved_reservation_closed
        ):
            if (
                not provision_may_have_been_sent
                and (process is None or child_returncode is not None)
            ):
                try:
                    _resolve_or_attest_unresolved_operation_marker(
                        unresolved_reservation.contract
                    )
                    unresolved_reservation.resolved = True
                except BaseException as error:
                    cleanup_errors.append(error)
            try:
                unresolved_reservation.close()
                unresolved_reservation_closed = True
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="ipc_watchdog_spawn",
                primary=primary_error,
                close_failures=cleanup_errors,
                message="IPC watchdog provisioning cleanup failed",
            ) from primary_error
        raise


def _owned_ipc_watchdog_main(
    control_fd: int,
    ack_fd: int,
    run_identity: str,
    parent: Path,
) -> int:
    namespace: _IpcRuntimeNamespace | None = None
    contract: dict[str, object] | None = None
    retention_hold: _RunRetentionHold | None = None
    unresolved_hold: _UnresolvedOperationMarkerHold | None = None
    cleanup_safe = False
    registered: dict[str, dict[str, int]] = {}
    try:
        _ipc_runtime_path(run_identity, parent=parent)
        _require(
            control_fd > 2 and ack_fd > 2 and control_fd != ack_fd,
            "IPC watchdog bootstrap descriptors drifted",
        )
        _require(os.write(ack_fd, b"A") == 1, "IPC watchdog arming write stalled")
        initial = _read_ipc_watchdog_frame_or_eof(control_fd)
        if initial is None:
            return 0
        provision = _validate_ipc_watchdog_provision_request(
            initial,
            run_identity=run_identity,
            parent=parent,
            run_lease_contract=_mapping(
                initial.get("run_lease"),
                "IPC watchdog run lease",
            ),
            unresolved_operation_contract=_mapping(
                initial.get("unresolved_operation"),
                "IPC watchdog unresolved operation",
            ),
        )
        run_lease_contract = _validate_run_lease_contract(
            _mapping(provision["run_lease"], "IPC watchdog run lease")
        )
        unresolved_operation_contract = (
            _validate_unresolved_operation_contract(
                _mapping(
                    provision["unresolved_operation"],
                    "IPC watchdog unresolved operation",
                )
            )
        )
        retention_hold = _acquire_run_retention_hold(run_lease_contract)
        unresolved_hold = _acquire_unresolved_operation_marker_hold(
            unresolved_operation_contract
        )
        namespace = _create_ipc_runtime_namespace(run_identity, parent=parent)
        namespace.unresolved_operation_contract = dict(
            unresolved_operation_contract
        )
        contract = _ipc_watchdog_contract(namespace)
        root_fd = namespace.root_fd
        _validate_ipc_watchdog_root_handles(contract)
        _write_ipc_watchdog_frame(ack_fd, _ipc_watchdog_readiness(namespace))
        sequence = 1
        while True:
            raw = _read_ipc_watchdog_frame_or_eof(control_fd)
            if raw is None:
                _ipc_watchdog_remove_owned_namespace(
                    contract,
                    registered,
                    require_empty=False,
                )
                namespace.unlinked = True
                cleanup_safe = True
                return 0
            message = _validate_ipc_watchdog_control(raw, sequence=sequence)
            sequence += 1
            action = str(message["action"])
            if action == "register":
                branch = str(message["branch"])
                _require(branch not in registered, "IPC watchdog branch was registered twice")
                record = _mapping(
                    message["socket_identity"],
                    "IPC watchdog socket identity",
                )
                observed = os.stat(
                    f"{branch}.sock",
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                _require(
                    _watchdog_record_matches(record, observed, check_nlink=True),
                    "IPC watchdog socket registration identity drifted",
                )
                registered[branch] = dict(record)
                _require(os.write(ack_fd, b"K") == 1, "IPC watchdog registration acknowledgement stalled")
                continue
            if action == "release":
                branch = str(message["branch"])
                record = _mapping(
                    message["socket_identity"],
                    "IPC watchdog socket identity",
                )
                _require(
                    branch in registered and dict(record) == registered[branch],
                    "IPC watchdog socket release identity drifted",
                )
                observed = os.stat(
                    f"{branch}.sock",
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
                _require(
                    _watchdog_record_matches(record, observed, check_nlink=True),
                    "IPC watchdog released socket was replaced",
                )
                os.unlink(f"{branch}.sock", dir_fd=root_fd)
                try:
                    os.stat(
                        f"{branch}.sock",
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise ExecutorContractError(
                        "IPC watchdog released socket remained named"
                    )
                del registered[branch]
                _require(os.write(ack_fd, b"K") == 1, "IPC watchdog release acknowledgement stalled")
                continue
            _ipc_watchdog_remove_owned_namespace(
                contract,
                registered,
                require_empty=action == "complete",
            )
            namespace.unlinked = True
            cleanup_safe = True
            _require(os.write(ack_fd, b"K") == 1, "IPC watchdog terminal acknowledgement stalled")
            return 0
    except Exception:
        if contract is not None:
            try:
                _ipc_watchdog_remove_owned_namespace(
                    contract,
                    registered,
                    require_empty=False,
                )
                if namespace is not None:
                    namespace.unlinked = True
                cleanup_safe = True
            except Exception:
                pass
        elif unresolved_hold is not None:
            try:
                _durably_attest_ipc_namespace_absent(
                    run_identity,
                    parent=parent,
                )
                cleanup_safe = True
            except BaseException:
                pass
        return 78
    finally:
        close_failed = False
        for descriptor in (control_fd, ack_fd):
            try:
                os.close(descriptor)
            except OSError:
                close_failed = True
        if namespace is not None:
            namespace.closed = True
            for descriptor in (namespace.parent_fd, namespace.root_fd):
                try:
                    os.close(descriptor)
                except OSError:
                    close_failed = True
        if unresolved_hold is not None:
            if cleanup_safe and not unresolved_hold.resolved:
                try:
                    unresolved_hold.resolve()
                except BaseException:
                    close_failed = True
            try:
                unresolved_hold.close()
            except BaseException:
                close_failed = True
        if retention_hold is not None:
            try:
                retention_hold.close()
            except BaseException:
                close_failed = True
        if close_failed:
            raise SystemExit(78)


def _validate_container_watchdog_mount_binding(
    value: Mapping[str, object],
    labels: Mapping[str, object],
) -> dict[str, str]:
    run_identity = labels.get(RUN_LABEL)
    branch = labels.get(BRANCH_LABEL)
    _require(
        set(labels) == {OWNER_LABEL, RUN_LABEL, BRANCH_LABEL}
        and labels.get(OWNER_LABEL) == OWNER_VALUE
        and type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and type(branch) is str
        and branch in {*BRANCHES, "runtime_probe"},
        "container watchdog mount binding labels drifted",
    )
    mounts = dict(_mapping(value, "container watchdog mounts"))

    def exact_path(raw: object, label: str) -> PurePosixPath:
        _require(
            type(raw) is str
            and bool(raw)
            and "\0" not in raw
            and "\\" not in raw
            and "//" not in raw,
            f"{label} lexical form drifted",
        )
        path = PurePosixPath(raw)
        _require(
            path.is_absolute()
            and path.as_posix() == raw
            and ".." not in path.parts,
            f"{label} path drifted",
        )
        return path

    normalized: dict[str, str] = {}
    for raw_destination, raw_source in mounts.items():
        destination = exact_path(
            raw_destination,
            "container watchdog mount destination",
        )
        source = exact_path(
            raw_source,
            "container watchdog mount source",
        )
        _require(
            destination.as_posix() != "/var/run/docker.sock"
            and "docker.sock" not in source.as_posix(),
            "container watchdog Docker socket mount drifted",
        )
        normalized[destination.as_posix()] = source.as_posix()
    _require(
        len(normalized) == len(mounts),
        "container watchdog mount destination collision",
    )
    if branch == "runtime_probe":
        _require(
            normalized == {},
            "container watchdog runtime probe mount coverage drifted",
        )
        return normalized

    binding_name = f"{branch}.tensorrt_cuda.json"
    analytics_destination = "/run/vast/analytics"
    binding_destination = f"/run/vast/bindings/{binding_name}"
    model_root = PurePosixPath("/run/vast/models")
    model_destinations = sorted(
        destination
        for destination in normalized
        if PurePosixPath(destination).parent == model_root
    )
    _require(
        len(normalized) == 4
        and analytics_destination in normalized
        and binding_destination in normalized
        and len(model_destinations) == 2
        and set(normalized)
        == {
            analytics_destination,
            binding_destination,
            *model_destinations,
        },
        "container watchdog worker mount coverage drifted",
    )
    expected_analytics = _ipc_runtime_path(run_identity).as_posix()
    _require(
        normalized[analytics_destination] == expected_analytics,
        "container watchdog analytics mount run identity drifted",
    )
    binding_source = PurePosixPath(normalized[binding_destination])
    run_root = binding_source.parent.parent
    _require(
        binding_source.name == binding_name
        and binding_source.parent == run_root / "bindings"
        and len(run_root.parts) >= 3
        and tuple(run_root.parts[-3:-1]) == ("runs", "nonpublication")
        and _RUN_ID_RE.fullmatch(run_root.name) is not None,
        "container watchdog binding source topology drifted",
    )
    model_sources: list[str] = []
    for destination in model_destinations:
        destination_path = PurePosixPath(destination)
        source_path = PurePosixPath(normalized[destination])
        _require(
            source_path.parent == run_root / "model_staging"
            and source_path.name == destination_path.name,
            "container watchdog model mount topology drifted",
        )
        model_sources.append(source_path.as_posix())
    _require(
        len(set(model_sources)) == 2
        and len(
            {
                normalized[analytics_destination],
                normalized[binding_destination],
                *model_sources,
            }
        )
        == 4,
        "container watchdog mount sources overlap",
    )
    return dict(sorted(normalized.items()))


def _validate_container_watchdog_name_binding(
    container_name: object,
    labels: Mapping[str, object],
) -> str:
    run_identity = labels.get(RUN_LABEL)
    branch = labels.get(BRANCH_LABEL)
    _require(
        type(container_name) is str
        and type(run_identity) is str
        and _SHA_RE.fullmatch(run_identity) is not None
        and type(branch) is str
        and branch in {*BRANCHES, "runtime_probe"},
        "container watchdog deterministic name inputs drifted",
    )
    suffix = "probe" if branch == "runtime_probe" else branch
    expected = f"vast-kpp-v2-np-{run_identity[:16]}-{suffix}"
    _require(
        container_name == expected,
        "container watchdog name and branch binding drifted",
    )
    return container_name


def _validate_watchdog_contract(value: Mapping[str, object]) -> dict[str, object]:
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "container_name",
        "labels",
        "expected_mounts",
        "image_labels",
        "docker_cli",
        "daemon",
        "cleanup_mutex",
        "run_lease",
        "unresolved_operation",
        "watchdog_contract_sha256",
    }
    _require(set(value) == expected_fields, "container watchdog contract fields drifted")
    claimed = value.get("watchdog_contract_sha256")
    core = {key: value[key] for key in value if key != "watchdog_contract_sha256"}
    expected = hashlib.sha256(WATCHDOG_DOMAIN + canonical_line(core)).hexdigest()
    _require(claimed == expected, "container watchdog contract identity drifted")
    _require(
        value.get("schema_version") == 4
        and value.get("artifact_kind") == "vast_nonpublication_owned_container_watchdog_v4",
        "container watchdog contract header drifted",
    )
    labels = dict(_mapping(value.get("labels"), "container watchdog labels"))
    _require(
        set(labels) == {OWNER_LABEL, RUN_LABEL, BRANCH_LABEL}
        and labels.get(OWNER_LABEL) == OWNER_VALUE
        and _SHA_RE.fullmatch(str(labels.get(RUN_LABEL))) is not None
        and labels.get(BRANCH_LABEL) in {*BRANCHES, "runtime_probe"},
        "container watchdog labels drifted",
    )
    name = _validate_container_watchdog_name_binding(
        value.get("container_name"),
        labels,
    )
    mounts = _validate_container_watchdog_mount_binding(
        _mapping(value.get("expected_mounts"), "container watchdog mounts"),
        labels,
    )
    image_labels = dict(_mapping(value.get("image_labels"), "container watchdog image labels"))
    _require(
        all(type(key) is str and type(item) is str for key, item in image_labels.items())
        and all(image_labels.get(key) == item for key, item in IMAGE_LABELS.items()),
        "container watchdog image labels drifted",
    )
    _require_no_docker_desktop_label_collision(image_labels, labels)
    cli = _mapping(value.get("docker_cli"), "container watchdog Docker CLI")
    _require(set(cli) == {"path", "size_bytes", "sha256"}, "container watchdog Docker CLI fields drifted")
    _require(type(cli.get("path")) is str and PurePosixPath(cli["path"]).is_absolute(), "container watchdog Docker CLI path drifted")
    _require(type(cli.get("size_bytes")) is int and cli["size_bytes"] > 0, "container watchdog Docker CLI size drifted")
    _sha(cli.get("sha256"), "container watchdog Docker CLI SHA-256")
    daemon = dict(_mapping(value.get("daemon"), "container watchdog daemon"))
    for key in ("daemon_id", "server_version", "api_version", "observation_sha256"):
        _require(type(daemon.get(key)) is str and bool(daemon[key]), "container watchdog daemon drifted")
    cleanup_mutex = _validate_cleanup_mutex_contract(
        _mapping(value.get("cleanup_mutex"), "container watchdog cleanup mutex")
    )
    run_lease = _validate_run_lease_contract(
        _mapping(value.get("run_lease"), "container watchdog run lease")
    )
    unresolved_operation = _validate_unresolved_operation_contract(
        _mapping(
            value.get("unresolved_operation"),
            "container watchdog unresolved operation",
        )
    )
    _require(
        cleanup_mutex.get("run_identity_sha256") == labels.get(RUN_LABEL),
        "container watchdog cleanup mutex run identity drifted",
    )
    _require(
        run_lease.get("run_identity_sha256") == labels.get(RUN_LABEL),
        "container watchdog run lease identity drifted",
    )
    _require(
        unresolved_operation.get("run_identity_sha256")
        == labels.get(RUN_LABEL)
        and unresolved_operation.get("operation_kind") == "container_create"
        and unresolved_operation.get("operation_id") == name
        and unresolved_operation.get("root") == run_lease.get("unresolved_root"),
        "container watchdog unresolved operation cross-bind drifted",
    )
    return {
        **dict(value),
        "labels": labels,
        "expected_mounts": mounts,
        "image_labels": image_labels,
        "docker_cli": dict(cli),
        "daemon": daemon,
        "cleanup_mutex": cleanup_mutex,
        "run_lease": run_lease,
        "unresolved_operation": unresolved_operation,
    }


def _spawn_container_watchdog(
    *,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    docker_cli_identity: FileIdentity,
    daemon: Mapping[str, object],
    cleanup_mutex: Any,
    run_lease: Any,
    docker_cli_path: Path = Path(DOCKER_CLI),
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> _ContainerWatchdogProcess:
    _require(os.name == "posix", "container watchdog requires POSIX")
    _require_no_docker_desktop_label_collision(expected_image_labels, labels)
    _require(
        type(run_lease) is _RunLease and not run_lease.released,
        "container watchdog requires exact run lease ownership",
    )
    validated_mounts = _validate_container_watchdog_mount_binding(
        {
            destination: str(source)
            for destination, source in expected_mounts.items()
        },
        labels,
    )
    unresolved_reservation: _UnresolvedOperationMarkerReservation | None = None
    read_fd = -1
    write_fd = -1
    ready_read_fd = -1
    ready_write_fd = -1
    process: subprocess.Popen[bytes] | None = None
    cleanup_ownership_transferred = False
    unresolved_reservation_closed = False
    try:
        unresolved_reservation = run_lease.create_unresolved_container_marker(
            container_name=container_name,
        )
        core: dict[str, object] = {
            "schema_version": 4,
            "artifact_kind": "vast_nonpublication_owned_container_watchdog_v4",
            "container_name": container_name,
            "labels": dict(labels),
            "expected_mounts": dict(sorted(validated_mounts.items())),
            "image_labels": dict(expected_image_labels),
            "docker_cli": {
                "path": str(docker_cli_path),
                "size_bytes": docker_cli_identity.size_bytes,
                "sha256": docker_cli_identity.sha256,
            },
            "daemon": dict(daemon),
            "cleanup_mutex": _cleanup_mutex_contract_from_actor(cleanup_mutex),
            "run_lease": _run_lease_contract_from_actor(run_lease),
            "unresolved_operation": dict(unresolved_reservation.contract),
        }
        contract = {
            **core,
            "watchdog_contract_sha256": hashlib.sha256(
                WATCHDOG_DOMAIN + canonical_line(core)
            ).hexdigest(),
        }
        read_fd, write_fd = os.pipe()
        ready_read_fd, ready_write_fd = os.pipe()
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "__owned_container_watchdog_v4",
                str(read_fd),
                str(ready_write_fd),
            ],
            shell=False,
            env={},
            cwd="/",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(read_fd, ready_write_fd),
            start_new_session=True,
        )
        descriptor = read_fd
        read_fd = -1
        os.close(descriptor)
        descriptor = ready_write_fd
        ready_write_fd = -1
        os.close(descriptor)
        cleanup_ownership_transferred = True
        _write_watchdog_contract(write_fd, contract)
        selector = selectors.DefaultSelector()
        readiness_primary: BaseException | None = None
        try:
            selector.register(ready_read_fd, selectors.EVENT_READ)
            events = selector.select(30.0)
            _require(bool(events), "container watchdog readiness timed out")
            ready = os.read(ready_read_fd, 2)
            _require(ready == b"R", "container watchdog failed before readiness")
            _require(process.poll() is None, "container watchdog exited after readiness")
        except BaseException as error:
            readiness_primary = error
        finally:
            readiness_cleanup_errors: list[BaseException] = []
            try:
                selector.close()
            except BaseException as error:
                readiness_cleanup_errors.append(error)
            descriptor = ready_read_fd
            ready_read_fd = -1
            try:
                os.close(descriptor)
            except BaseException as error:
                readiness_cleanup_errors.append(error)
            if readiness_cleanup_errors:
                raise _DescriptorClosureError(
                    operation="container_watchdog_readiness",
                    primary=readiness_primary,
                    close_failures=readiness_cleanup_errors,
                ) from (
                    readiness_primary
                    if readiness_primary is not None
                    else readiness_cleanup_errors[0]
                )
        if readiness_primary is not None:
            raise readiness_primary
        unresolved_reservation.close()
        unresolved_reservation_closed = True
        handle = _ContainerWatchdogProcess(
            process=process,
            control_fd=write_fd,
            unresolved_operation_contract=dict(
                unresolved_reservation.contract
            ),
        )
        write_fd = -1
        return handle
    except BaseException as primary_error:
        cleanup_errors: list[BaseException] = []
        for field_name in (
            "write_fd",
            "read_fd",
            "ready_read_fd",
            "ready_write_fd",
        ):
            descriptor = locals()[field_name]
            if descriptor >= 0:
                if field_name == "write_fd":
                    write_fd = -1
                elif field_name == "read_fd":
                    read_fd = -1
                elif field_name == "ready_read_fd":
                    ready_read_fd = -1
                else:
                    ready_write_fd = -1
                try:
                    os.close(descriptor)
                except BaseException as error:
                    cleanup_errors.append(error)
        child_returncode: int | None = None
        if process is not None:
            process_running = True
            try:
                observed_returncode = process.poll()
                process_running = observed_returncode is None
                if type(observed_returncode) is int:
                    child_returncode = observed_returncode
            except BaseException as error:
                cleanup_errors.append(error)
            if process_running and not cleanup_ownership_transferred:
                try:
                    process.kill()
                except BaseException as error:
                    cleanup_errors.append(error)
            try:
                observed_returncode = process.wait(timeout=10.0)
                if type(observed_returncode) is int:
                    child_returncode = observed_returncode
            except BaseException as error:
                cleanup_errors.append(error)
            if cleanup_ownership_transferred and child_returncode is None:
                cleanup_errors.append(
                    ExecutorContractError(
                        "container watchdog retains cleanup ownership after provisioning"
                    )
                )
        if (
            unresolved_reservation is not None
            and not unresolved_reservation_closed
        ):
            # Provisioning failed before the caller could dispatch Docker
            # create.  Only a proven-dead/no-process child permits the
            # controller to resolve the durable marker; a live or unknown
            # child keeps sole cleanup ownership and resolves it.  The child
            # may already have unlinked it before the parent observes exit.
            if process is None or child_returncode is not None:
                try:
                    _resolve_or_attest_unresolved_operation_marker(
                        unresolved_reservation.contract
                    )
                    unresolved_reservation.resolved = True
                except BaseException as error:
                    cleanup_errors.append(error)
            try:
                unresolved_reservation.close()
                unresolved_reservation_closed = True
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="container_watchdog_spawn",
                primary=primary_error,
                close_failures=cleanup_errors,
                message="container watchdog provisioning cleanup failed",
            ) from primary_error
        raise


def _owned_container_watchdog_main(descriptor: int, ready_descriptor: int) -> int:
    status = 78
    retention_hold: _RunRetentionHold | None = None
    unresolved_hold: _UnresolvedOperationMarkerHold | None = None
    try:
        length = int.from_bytes(_read_exact_fd(descriptor, 4), "big")
        _require(0 < length <= 64 * 1024, "container watchdog contract length drifted")
        contract = _validate_watchdog_contract(
            _parse_json(_read_exact_fd(descriptor, length), "container watchdog contract")
        )
        retention_hold = _acquire_run_retention_hold(
            _mapping(contract["run_lease"], "container watchdog run lease")
        )
        unresolved_hold = _acquire_unresolved_operation_marker_hold(
            _mapping(
                contract["unresolved_operation"],
                "container watchdog unresolved operation",
            )
        )
        cli = _mapping(contract["docker_cli"], "container watchdog Docker CLI")
        cli_path = Path(str(cli["path"]))
        _require(
            _observe_regular_file(cli_path)
            == FileIdentity(int(cli["size_bytes"]), str(cli["sha256"])),
            "container watchdog Docker CLI identity drifted",
        )
        runner = _DockerPathRunner(cli_path)
        daemon = _mapping(contract["daemon"], "container watchdog daemon")
        observed_daemon = _validate_daemon(
            runner,
            expected_id=str(daemon["daemon_id"]),
            expected_server_version=str(daemon["server_version"]),
            expected_api_version=str(daemon["api_version"]),
        )
        _require(observed_daemon == daemon, "container watchdog daemon observation drifted")
        cleanup_mutex = _CleanupMutexReference(
            _validate_cleanup_mutex_contract(
                _mapping(
                    contract["cleanup_mutex"],
                    "container watchdog cleanup mutex",
                )
            )
        )
        # Readiness is emitted only after this process independently opened and
        # acquired the same pinned inode.  No flock descriptor is inherited.
        with cleanup_mutex.hold():
            pass
        name = str(contract["container_name"])
        labels = {
            str(key): str(item)
            for key, item in _mapping(
                contract["labels"], "container watchdog labels"
            ).items()
        }
        mounts = {
            str(key): Path(str(item))
            for key, item in _mapping(
                contract["expected_mounts"], "container watchdog mounts"
            ).items()
        }
        image_labels = {
            str(key): str(item)
            for key, item in _mapping(
                contract["image_labels"], "container watchdog image labels"
            ).items()
        }
        try:
            _require(os.write(ready_descriptor, b"R") == 1, "container watchdog readiness write stalled")
        except OSError as error:
            raise ExecutorContractError("container watchdog readiness failed") from error
        post_readiness_errors: list[BaseException] = []
        ready_to_close = ready_descriptor
        ready_descriptor = -1
        try:
            os.close(ready_to_close)
        except BaseException as error:
            post_readiness_errors.append(error)
        create_dispatched = False
        create_terminal = False
        final_marker = b""
        control_ambiguous = False
        while True:
            try:
                marker = os.read(descriptor, 1)
            except BaseException as error:
                post_readiness_errors.append(error)
                control_ambiguous = True
                break
            if marker == b"D":
                try:
                    _require(
                        not create_dispatched and not create_terminal,
                        "container watchdog duplicate create dispatch marker",
                    )
                    create_dispatched = True
                except BaseException as error:
                    post_readiness_errors.append(error)
                    control_ambiguous = True
                    break
                continue
            if marker == b"T":
                try:
                    _require(
                        create_dispatched and not create_terminal,
                        "container watchdog create terminal marker drifted",
                    )
                    create_terminal = True
                except BaseException as error:
                    post_readiness_errors.append(error)
                    control_ambiguous = True
                    break
                continue
            if marker in {b"", b"N", b"C"}:
                final_marker = marker
                break
            post_readiness_errors.append(
                ExecutorContractError(
                    "container watchdog completion marker drifted"
                )
            )
            control_ambiguous = True
            break
        if final_marker == b"C" and not (
            create_dispatched and create_terminal
        ):
            post_readiness_errors.append(
                ExecutorContractError(
                    "normal completion lacks terminal create authority"
                )
            )
            control_ambiguous = True
        commit_ambiguous = control_ambiguous or (
            create_dispatched and not create_terminal and final_marker != b"C"
        )
        late_commit_removed = False
        cleanup_safe = False
        if commit_ambiguous:
            # A single name/list absence cannot discharge ownership after the
            # client may have sent POST /containers/create without receiving a
            # terminal daemon response.  Release the cross-process mutex
            # between observations, retain this independent-session cleanup
            # owner indefinitely, and exit only after an exact late object was
            # observed, removed, and re-attested absent.  If no object ever
            # appears the process deliberately remains visible/owned.
            while True:
                try:
                    recovered = _recover_and_cleanup_owned_container_by_name(
                        runner=runner,
                        container_name=name,
                        labels=labels,
                        expected_mounts=mounts,
                        cleanup_mutex=cleanup_mutex,
                        expected_image_labels=image_labels,
                    )
                    if recovered is not None:
                        late_commit_removed = True
                        cleanup_safe = True
                        break
                except BaseException:
                    # Child detail transport is intentionally rc-only; do not
                    # surrender sole cleanup ownership on a transient daemon
                    # or filesystem observation failure.
                    status = 78
                try:
                    time.sleep(1.0)
                except BaseException:
                    status = 78
        else:
            try:
                recovered = _recover_and_cleanup_owned_container_by_name(
                    runner=runner,
                    container_name=name,
                    labels=labels,
                    expected_mounts=mounts,
                    cleanup_mutex=cleanup_mutex,
                    expected_image_labels=image_labels,
                )
                if recovered is not None and final_marker == b"C":
                    post_readiness_errors.append(
                        ExecutorContractError(
                            "normal completion left an owned Docker container"
                        )
                    )
                cleanup_safe = True
            except BaseException as error:
                post_readiness_errors.append(error)
        if cleanup_safe:
            _require(
                unresolved_hold is not None,
                "container watchdog unresolved marker is unavailable",
            )
            unresolved_hold.resolve()
        status = (
            _WATCHDOG_LATE_COMMIT_REMOVED_RC
            if late_commit_removed
            else (0 if not post_readiness_errors else 78)
        )
    except (ExecutorContractError, OSError, ValueError, RecursionError):
        status = 78
    finally:
        close_failed = False
        try:
            os.close(descriptor)
        except OSError:
            close_failed = True
        if ready_descriptor >= 0:
            ready_to_close = ready_descriptor
            ready_descriptor = -1
            try:
                os.close(ready_to_close)
            except OSError:
                close_failed = True
        if unresolved_hold is not None:
            try:
                unresolved_hold.close()
            except BaseException:
                close_failed = True
        if retention_hold is not None:
            try:
                retention_hold.close()
            except BaseException:
                close_failed = True
        if close_failed:
            status = 78
    return status


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutorContractError(f"{label} must be an object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutorContractError(message)


def _require_no_docker_desktop_label_collision(
    expected_image_labels: Mapping[str, str],
    ownership_labels: Mapping[str, str],
) -> None:
    _require(
        _DOCKER_DESKTOP_WSL_DISTRO_LABEL not in expected_image_labels
        and _DOCKER_DESKTOP_WSL_DISTRO_LABEL not in ownership_labels,
        "Docker Desktop injected label collides with expected labels",
    )


def _validate_owned_container_labels(
    actual_labels: Mapping[str, Any],
    expected_image_labels: Mapping[str, str],
    ownership_labels: Mapping[str, str],
) -> None:
    _require_no_docker_desktop_label_collision(
        expected_image_labels,
        ownership_labels,
    )
    expected = {**dict(expected_image_labels), **dict(ownership_labels)}
    exact_docker_desktop = {
        **expected,
        _DOCKER_DESKTOP_WSL_DISTRO_LABEL: _DOCKER_DESKTOP_WSL_DISTRO_VALUE,
    }
    actual = dict(actual_labels)
    _require(
        actual == expected or actual == exact_docker_desktop,
        "Docker ownership labels drifted",
    )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise ExecutorContractError("executor artifact is not canonical JSON") from error


def canonical_line(value: object) -> bytes:
    return _canonical_json(value) + b"\n"


def _identity(core: Mapping[str, object]) -> str:
    return hashlib.sha256(RESULT_DOMAIN + _canonical_json(core) + b"\n").hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutorContractError(f"duplicate Docker JSON key: {key}")
        result[key] = value
    return result


def _parse_json(payload: bytes, label: str) -> dict[str, Any]:
    _require(0 < len(payload) <= 1024 * 1024, f"{label} byte length is invalid")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ExecutorContractError(f"invalid Docker JSON constant: {item}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ExecutorContractError(f"{label} is invalid JSON") from error
    return dict(_mapping(value, label))


def _run_read_only(
    runner: CommandRunner,
    argv: list[str],
    *,
    label: str,
) -> CommandCapture:
    result = runner.run(
        argv,
        timeout_seconds=30.0,
        stdout_limit=1024 * 1024,
        stderr_limit=64 * 1024,
    )
    _require(type(result.returncode) is int, f"{label} return code is invalid")
    _require(type(result.stdout) is bytes and type(result.stderr) is bytes, f"{label} capture is invalid")
    return result


def _validate_daemon(
    runner: CommandRunner,
    *,
    expected_id: str,
    expected_server_version: str,
    expected_api_version: str,
) -> dict[str, object]:
    info_capture = _run_read_only(
        runner,
        [DOCKER_CLI, DOCKER_HOST_ARG, "info", "--format={{json .}}"],
        label="local Docker daemon info",
    )
    _require(info_capture.returncode == 0, "local Docker daemon info failed")
    info = _parse_json(info_capture.stdout, "local Docker daemon info")
    version_capture = _run_read_only(
        runner,
        [DOCKER_CLI, DOCKER_HOST_ARG, "version", "--format={{json .Server}}"],
        label="local Docker daemon version",
    )
    _require(version_capture.returncode == 0, "local Docker daemon version failed")
    version = _parse_json(version_capture.stdout, "local Docker daemon version")
    _require(info.get("ID") == expected_id, "local Docker daemon identity drifted")
    _require(info.get("ServerVersion") == expected_server_version, "local Docker daemon version drifted")
    _require(info.get("OSType") == "linux", "local Docker daemon is not linux")
    _require(info.get("Architecture") in {"x86_64", "amd64"}, "local Docker daemon architecture drifted")
    _require(version.get("Version") == expected_server_version, "Docker Server.Version drifted")
    _require(version.get("ApiVersion") == expected_api_version, "Docker Server.ApiVersion drifted")
    _require(version.get("Os") == "linux" and version.get("Arch") in {"amd64", "x86_64"}, "Docker server platform drifted")
    driver_status = info.get("DriverStatus")
    _require(
        type(driver_status) is list
        and 0 < len(driver_status) <= 32
        and all(
            type(item) is list
            and len(item) == 2
            and all(
                type(part) is str and 0 < len(part) <= 256
                for part in item
            )
            for item in driver_status
        ),
        "local Docker daemon driver status drifted",
    )
    containerd_commit = info.get("ContainerdCommit")
    _require(
        isinstance(containerd_commit, Mapping)
        and set(containerd_commit) == {"ID"}
        and type(containerd_commit.get("ID")) is str
        and re.fullmatch(r"[0-9a-f]{40}", containerd_commit["ID"]) is not None,
        "local Docker daemon containerd commit drifted",
    )
    for key, label in (
        ("Name", "name"),
        ("OperatingSystem", "operating system"),
        ("KernelVersion", "kernel version"),
        ("Driver", "storage driver"),
        ("DefaultRuntime", "default runtime"),
    ):
        item = info.get(key)
        _require(
            type(item) is str and 0 < len(item) <= 256,
            f"local Docker daemon {label} drifted",
        )
    core = {
        "daemon_id": expected_id,
        "server_version": expected_server_version,
        "api_version": expected_api_version,
        "os": "linux",
        "architecture": "amd64",
        "name": info["Name"],
        "operating_system": info["OperatingSystem"],
        "kernel_version": info["KernelVersion"],
        "driver": info["Driver"],
        "driver_status": [list(item) for item in driver_status],
        "default_runtime": info["DefaultRuntime"],
        "containerd_commit": dict(containerd_commit),
    }
    return {**core, "observation_sha256": hashlib.sha256(_canonical_json(core)).hexdigest()}


def _validate_daemon_observation(value: Mapping[str, object]) -> dict[str, object]:
    daemon = dict(_mapping(value, "Docker daemon observation"))
    fields = {
        "daemon_id",
        "server_version",
        "api_version",
        "os",
        "architecture",
        "name",
        "operating_system",
        "kernel_version",
        "driver",
        "driver_status",
        "default_runtime",
        "containerd_commit",
        "observation_sha256",
    }
    _require(set(daemon) == fields, "Docker daemon observation fields drifted")
    for key in (
        "daemon_id",
        "server_version",
        "api_version",
        "name",
        "operating_system",
        "kernel_version",
        "driver",
        "default_runtime",
    ):
        _require(
            type(daemon.get(key)) is str and 0 < len(daemon[key]) <= 256,
            "Docker daemon observation string drifted",
        )
    _require(
        daemon.get("os") == "linux" and daemon.get("architecture") == "amd64",
        "Docker daemon observation platform drifted",
    )
    driver_status = daemon.get("driver_status")
    _require(
        type(driver_status) is list
        and 0 < len(driver_status) <= 32
        and all(
            type(item) is list
            and len(item) == 2
            and all(type(part) is str and 0 < len(part) <= 256 for part in item)
            for item in driver_status
        ),
        "Docker daemon observation driver status drifted",
    )
    containerd_commit = daemon.get("containerd_commit")
    _require(
        isinstance(containerd_commit, Mapping)
        and set(containerd_commit) == {"ID"}
        and type(containerd_commit.get("ID")) is str
        and re.fullmatch(r"[0-9a-f]{40}", containerd_commit["ID"]) is not None,
        "Docker daemon observation containerd commit drifted",
    )
    claimed = daemon.pop("observation_sha256")
    _require(
        type(claimed) is str
        and _SHA_RE.fullmatch(claimed) is not None
        and claimed == hashlib.sha256(_canonical_json(daemon)).hexdigest(),
        "Docker daemon observation identity drifted",
    )
    return {**daemon, "observation_sha256": claimed}


def _exact_image_absent(runner: CommandRunner, capture: CommandCapture) -> bool:
    expected_errors = {
        f"Error response from daemon: No such image: {TENSORRT_IMAGE_ID}\n".encode("ascii"),
        f"Error: No such image: {TENSORRT_IMAGE_ID}\n".encode("ascii"),
    }
    if not (
        capture.returncode == 1
        and capture.stdout == b""
        and capture.stderr in expected_errors
    ):
        return False
    inventory = _run_read_only(
        runner,
        [DOCKER_CLI, DOCKER_HOST_ARG, "image", "ls", "--no-trunc", "--quiet"],
        label="local Docker image inventory",
    )
    _require(inventory.returncode == 0, "local Docker image inventory failed")
    try:
        values = [line.decode("ascii") for line in inventory.stdout.splitlines() if line]
    except UnicodeError as error:
        raise ExecutorContractError("local Docker image inventory is non-ASCII") from error
    _require(
        all(re.fullmatch(r"sha256:[0-9a-f]{64}", item) is not None for item in values),
        "local Docker image inventory drifted",
    )
    return TENSORRT_IMAGE_ID not in values


def _blocked_artifact(
    *,
    role: str,
    status: str,
    blocker: str,
    runtime: Mapping[str, object] | None = None,
    claim_status: str = "blocked_nonpublication_preflight_not_execution",
) -> dict[str, object]:
    _require(
        claim_status
        in {
            "blocked_nonpublication_preflight_not_execution",
            "diagnostic_only_blocked_nonpublication_not_evidence",
        },
        "blocked artifact claim status drifted",
    )
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": RESULT_ARTIFACT_KIND,
        "claim_status": claim_status,
        "status": status,
        "role": role,
        "required_image_id": TENSORRT_IMAGE_ID,
        "blockers": [blocker],
        "runtime_preflight": dict(runtime or {}),
        "operational_completion_observed": False,
        "inference_performed": False,
        **_FALSE_CLAIMS,
    }
    return {**core, "assessment_sha256": _identity(core)}


def _sha(value: object, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None, f"{label} is not a lowercase SHA-256")
    return value


def _validate_execution_plan(
    plan: Mapping[str, object],
    *,
    role: str,
    expected_receipt_file_sha256: str,
    expected_receipt_self_sha256: str,
) -> list[dict[str, object]]:
    _require(plan.get("schema_version") == 1, "pilot plan schema drifted")
    _require(plan.get("artifact_kind") == PLAN_ARTIFACT_KIND, "pilot plan kind drifted")
    _require(plan.get("claim_status") == "planning_only_nonpublication_not_execution", "pilot plan claim status drifted")
    _require(plan.get("role") == role, "pilot plan role drifted")
    _sha(plan.get("matrix_identity_sha256"), "pilot matrix identity")
    _sha(plan.get("pilot_plan_sha256"), "pilot plan identity")
    runtime = _mapping(plan.get("runtime"), "pilot runtime")
    required_runtime = {
        "engine": ENGINE_TENSORRT_CUDA,
        "worker_image_id": TENSORRT_IMAGE_ID,
        "base_image_id": TENSORRT_BASE_IMAGE_ID,
        "entrypoint": TENSORRT_ENTRYPOINT,
        "gpu_uuid": TENSORRT_GPU_UUID,
        "gpu_device_index": 0,
        "pull_policy": "never",
        "network": "none",
        "max_requests_per_worker": 2,
    }
    _require(all(runtime.get(key) == value for key, value in required_runtime.items()), "pilot runtime pins drifted")
    candidate = _mapping(plan.get("candidate"), "pilot candidate")
    receipt = _mapping(candidate.get("receipt"), "pilot candidate receipt")
    _require(receipt.get("sha256") == expected_receipt_file_sha256, "pilot receipt file pin drifted")
    _require(receipt.get("candidate_receipt_sha256") == expected_receipt_self_sha256, "pilot receipt self pin drifted")
    corpora = candidate.get("corpora")
    _require(type(corpora) is list and len(corpora) == 8, "pilot exact corpus coverage drifted")
    expected_corpus_suffixes = {
        f"corpus_{branch}_{corpus_role}.json"
        for branch in BRANCHES
        for corpus_role in ("calibration", "evaluation")
    }
    observed_suffixes = {
        PurePosixPath(str(_mapping(item, "pilot corpus descriptor").get("path"))).name
        for item in corpora
    }
    _require(observed_suffixes == expected_corpus_suffixes, "pilot corpus descriptor coverage drifted")
    requests = plan.get("requests")
    _require(type(requests) is list and plan.get("request_count") == 8 and len(requests) == 8, "pilot exact request coverage drifted")
    checked: list[dict[str, object]] = []
    position = 0
    for branch in BRANCHES:
        for codec, ordinal in (("h264", 0), ("h265", 1)):
            request = dict(_mapping(requests[position], f"pilot request {position}"))
            position += 1
            expected_request_id = f"kpp-v2-nonpublication-{branch}-{codec}-calibration-smoke-v1"
            expected_sample_id = f"kpp-v2-candidate.{branch}.calibration.{codec}.{ordinal:02d}"
            _require(
                request.get("request_id") == expected_request_id
                and request.get("sample_id") == expected_sample_id
                and request.get("branch") == branch
                and request.get("codec") == codec
                and request.get("corpus_role") == "calibration",
                "pilot request identity/order drifted",
            )
            _require(request.get("model") == TENSORRT_ENGINE_PINS[branch], "pilot request model pin drifted")
            tensor = _mapping(request.get("tensor"), "pilot request tensor")
            _require(
                tensor.get("encoding") == "raw_f32_le_c_contiguous_v1"
                and tensor.get("dtype") == "float32"
                and tensor.get("shape") == [1, 3, 224, 224]
                and tensor.get("layout") == "NCHW"
                and tensor.get("segment_size_bytes") == TENSOR_SEGMENT_BYTES,
                "pilot request tensor contract drifted",
            )
            for field in ("sha256", "segment_sha256", "preprocessing_contract_sha256"):
                _sha(tensor.get(field), f"pilot tensor {field}")
            _require(type(tensor.get("offset_bytes")) is int and tensor["offset_bytes"] >= 0, "pilot tensor offset drifted")
            checked.append(request)
    return checked


def _validate_bindings(
    inventory: BindingInventory,
    requests: Sequence[Mapping[str, object]],
) -> None:
    _sha(inventory.manifest_identity_sha256, "model parity manifest identity")
    _sha(inventory.execution_config_identity_sha256, "execution config identity")
    _require(set(inventory.bindings) == set(BRANCHES), "TensorRT binding branch coverage drifted")
    _require(set(inventory.source_paths) == set(BRANCHES), "TensorRT source path coverage drifted")
    _require(set(inventory.engine_paths) == set(BRANCHES), "TensorRT engine path coverage drifted")
    _require(set(inventory.source_identities) == set(BRANCHES), "TensorRT source identity coverage drifted")
    _require(set(inventory.engine_identities) == set(BRANCHES), "TensorRT engine identity coverage drifted")
    by_branch = {str(request["branch"]): request for request in requests if request["codec"] == "h264"}
    for branch in BRANCHES:
        binding = _mapping(inventory.bindings[branch], f"{branch} TensorRT binding")
        request = by_branch[branch]
        model = _mapping(request["model"], f"{branch} request model")
        tensor = _mapping(request["tensor"], f"{branch} request tensor")
        _require(
            binding.get("artifact_kind") == "vast_tensorrt_execution_worker_binding"
            and binding.get("branch") == branch
            and binding.get("model_id") == model.get("model_id")
            and binding.get("model_artifact_sha256") == model.get("engine_sha256")
            and binding.get("worker_image_id") == TENSORRT_IMAGE_ID
            and binding.get("gpu_device_index") == 0
            and binding.get("gpu_uuid") == TENSORRT_GPU_UUID,
            f"{branch} TensorRT binding pins drifted",
        )
        input_contract = _mapping(binding.get("input"), f"{branch} TensorRT input")
        _require(
            input_contract
            == {"name": "data", "dtype": "float32", "layout": "NCHW", "shape": [1, 3, 224, 224]},
            f"{branch} TensorRT input contract drifted",
        )
        _require(
            binding.get("preprocessing_contract_sha256")
            == tensor.get("preprocessing_contract_sha256"),
            f"{branch} preprocessing binding drifted",
        )
        source_text = str(inventory.source_paths[branch]).replace("\\", "/")
        engine_text = str(inventory.engine_paths[branch]).replace("\\", "/")
        _require(
            PurePosixPath(source_text).is_absolute(),
            f"{branch} host source path is not absolute",
        )
        _require(
            PurePosixPath(engine_text).is_absolute(),
            f"{branch} host engine path is not absolute",
        )


def _validate_binding_file_identities(
    inventory: BindingInventory,
    observer: Callable[[Path], FileIdentity],
) -> dict[str, dict[str, object]]:
    observations: dict[str, dict[str, object]] = {}
    for branch in BRANCHES:
        binding = _mapping(inventory.bindings[branch], f"{branch} TensorRT binding")
        expected_source = inventory.source_identities[branch]
        expected_engine = inventory.engine_identities[branch]
        pin = TENSORRT_ENGINE_PINS[branch]
        _require(
            type(expected_source) is FileIdentity
            and expected_source.size_bytes > 0
            and expected_source.sha256 == binding.get("source_model_sha256")
            and expected_source.is_regular_file
            and not expected_source.is_symlink,
            f"{branch} source model identity drifted",
        )
        _require(
            expected_engine
            == FileIdentity(
                size_bytes=int(pin["size_bytes"]),
                sha256=str(pin["engine_sha256"]),
            ),
            f"{branch} TensorRT engine identity drifted",
        )
        for kind, path, expected in (
            ("source", Path(inventory.source_paths[branch]), expected_source),
            ("engine", Path(inventory.engine_paths[branch]), expected_engine),
        ):
            observed = observer(path)
            _require(type(observed) is FileIdentity, f"{branch} {kind} file observation type drifted")
            _require(
                observed == expected
                and observed.is_regular_file
                and not observed.is_symlink,
                f"{branch} {kind} file identity drifted",
            )
            observations[f"{branch}:{kind}"] = {
                "size_bytes": observed.size_bytes,
                "sha256": observed.sha256,
                "regular_file": True,
                "symlink": False,
            }
    return observations


def _open_absolute_nofollow(path: Path) -> tuple[int, list[int]]:
    _require(os.name == "posix", "handle-based file custody requires POSIX")
    text = str(path)
    candidate = PurePosixPath(text)
    _require(candidate.is_absolute() and ".." not in candidate.parts, "custodied file path is unsafe")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    _require(nofollow != 0 and directory != 0, "POSIX no-follow directory custody is unavailable")
    holds: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | directory | cloexec)
        holds.append(current)
        parts = [part for part in candidate.parts if part not in {"/", ""}]
        _require(bool(parts), "custodied file path has no basename")
        for component in parts[:-1]:
            current = os.open(
                component,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=current,
            )
            holds.append(current)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | nofollow | cloexec,
            dir_fd=current,
        )
        holds.append(descriptor)
        return descriptor, holds
    except BaseException as error:
        primary: BaseException = error
        if isinstance(error, OSError):
            primary = ExecutorContractError(
                "cannot acquire no-follow file custody"
            )
            primary.__cause__ = error
        close_errors: list[BaseException] = []
        for held in reversed(holds):
            try:
                os.close(held)
            except BaseException as close_error:
                close_errors.append(close_error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="absolute_nofollow_open",
                primary=primary,
                close_failures=close_errors,
                message="cannot acquire no-follow file custody",
            ) from primary
        raise primary


def _file_snapshot(descriptor: int) -> tuple[int, int, int, int, int, int, int]:
    try:
        value = os.fstat(descriptor)
    except OSError as error:
        raise ExecutorContractError("cannot stat custodied file handle") from error
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_size),
        int(value.st_mode),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_nlink),
    )


def _observe_regular_file(path: Path) -> FileIdentity:
    descriptor, holds = _open_absolute_nofollow(path)
    result: FileIdentity | None = None
    primary: BaseException | None = None
    try:
        before = _file_snapshot(descriptor)
        _require(stat.S_ISREG(before[3]), "custodied path is not a regular file")
        digest = hashlib.sha256()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        except OSError as error:
            raise ExecutorContractError("cannot hash custodied file handle") from error
        after = _file_snapshot(descriptor)
        _require(after == before, "custodied file changed while hashing")
        result = FileIdentity(
            size_bytes=before[2],
            sha256=digest.hexdigest(),
            is_regular_file=True,
            is_symlink=False,
        )
    except BaseException as error:
        primary = error
    close_errors: list[BaseException] = []
    for held in reversed(holds):
        try:
            os.close(held)
        except BaseException as error:
            close_errors.append(error)
    if close_errors:
        raise _DescriptorClosureError(
            operation="regular_file_observation",
            primary=primary,
            close_failures=close_errors,
        ) from (primary if primary is not None else close_errors[0])
    if primary is not None:
        raise primary
    _require(result is not None, "regular file observation is unavailable")
    return result


def _project_file(root: Path, relative: object, label: str) -> Path:
    _require(type(relative) is str and bool(relative), f"{label} path is invalid")
    pure = PurePosixPath(relative)
    _require(not pure.is_absolute() and ".." not in pure.parts, f"{label} path is unsafe")
    candidate = root.joinpath(*pure.parts)
    _require(candidate.parent != candidate, f"{label} path is unsafe")
    return candidate


def _load_binding_inventory(
    *,
    project_root: Path | str,
    plan: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
) -> BindingInventory:
    del plan, requests
    root = Path(project_root).resolve()
    config_path = root / EXECUTION_CONFIG_RELATIVE_PATH
    config_file = _observe_regular_file(config_path)
    _require(
        config_file.sha256 == EXECUTION_CONFIG_FILE_SHA256,
        "analytics execution config file identity drifted",
    )
    try:
        from analytics_execution_bindings import build_worker_bindings
        from checkpoint_gstreamer_analytics_sidecar import load_execution_config
        from checkpoint_model_parity import load_parity_manifest
    except (ImportError, OSError) as error:
        raise ExecutorContractError("analytics binding APIs are unavailable") from error
    config = load_execution_config(config_path)
    manifest_path = _project_file(
        root, config.get("model_parity_manifest"), "model parity manifest"
    )
    manifest = load_parity_manifest(manifest_path)
    runtime_registry = _mapping(
        manifest.get("worker_runtime_registry"), "model parity worker runtime registry"
    )
    execution_reference = _mapping(
        runtime_registry.get("execution_config"),
        "model parity execution config reference",
    )
    config_identity = _mapping(config.get("identity"), "analytics execution config identity")
    _require(
        execution_reference.get("path") == EXECUTION_CONFIG_RELATIVE_PATH
        and execution_reference.get("sha256") == config_file.sha256
        and execution_reference.get("content_identity_sha256")
        == config_identity.get("sha256"),
        "model parity execution config binding drifted",
    )
    built = build_worker_bindings(
        manifest,
        config,
        project_root=root,
        worker_project_root="/run/vast/project",
    )
    slots = _mapping(manifest.get("workload_slots"), "model parity workload slots")
    sources = _mapping(manifest.get("source_registry"), "model parity source registry")
    bindings: dict[str, dict[str, object]] = {}
    source_paths: dict[str, Path] = {}
    engine_paths: dict[str, Path] = {}
    source_identities: dict[str, FileIdentity] = {}
    engine_identities: dict[str, FileIdentity] = {}
    for branch in BRANCHES:
        slot = _mapping(slots.get(branch), f"{branch} workload slot")
        source_ref = slot.get("source_ref")
        source = _mapping(sources.get(source_ref), f"{branch} source model")
        tensorrt = _mapping(slot.get("tensorrt_engine"), f"{branch} TensorRT engine")
        engine = _mapping(tensorrt.get("artifact"), f"{branch} TensorRT artifact")
        source_path = _project_file(root, source.get("path"), f"{branch} source model")
        engine_path = _project_file(root, engine.get("path"), f"{branch} TensorRT engine")
        source_identity = FileIdentity(
            size_bytes=int(source.get("size_bytes")),
            sha256=_sha(source.get("sha256"), f"{branch} source model SHA-256"),
        )
        engine_identity = FileIdentity(
            size_bytes=int(engine.get("size_bytes")),
            sha256=_sha(engine.get("sha256"), f"{branch} TensorRT engine SHA-256"),
        )
        binding = dict(
            _mapping(
                _mapping(built.get(branch), f"{branch} built bindings").get(
                    ENGINE_TENSORRT_CUDA
                ),
                f"{branch} built TensorRT binding",
            )
        )
        binding["source_path"] = f"/run/vast/models/{source_path.name}"
        binding["engine_path"] = f"/run/vast/models/{engine_path.name}"
        bindings[branch] = binding
        source_paths[branch] = source_path
        engine_paths[branch] = engine_path
        source_identities[branch] = source_identity
        engine_identities[branch] = engine_identity
    manifest_identity = _mapping(manifest.get("identity"), "model parity manifest identity")
    _require(
        _observe_regular_file(config_path) == config_file,
        "analytics execution config changed while building bindings",
    )
    return BindingInventory(
        bindings=bindings,
        source_paths=source_paths,
        engine_paths=engine_paths,
        source_identities=source_identities,
        engine_identities=engine_identities,
        manifest_identity_sha256=_sha(
            manifest_identity.get("sha256"), "model parity manifest identity"
        ),
        execution_config_identity_sha256=_sha(
            config_identity.get("sha256"), "analytics execution config identity"
        ),
    )


def _read_bundle_segments(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    offsets: Sequence[int],
) -> dict[int, bytes]:
    descriptor, holds = _open_absolute_nofollow(path)
    result: dict[int, bytes] | None = None
    primary: BaseException | None = None
    try:
        before = _file_snapshot(descriptor)
        _require(stat.S_ISREG(before[3]) and before[2] == expected_size, "tensor bundle file size drifted")
        segments: dict[int, bytes] = {}
        for offset in sorted(set(offsets)):
            try:
                payload = os.pread(descriptor, TENSOR_SEGMENT_BYTES, offset)
            except OSError as error:
                raise ExecutorContractError("cannot read selected tensor segment") from error
            _require(len(payload) == TENSOR_SEGMENT_BYTES, "selected tensor segment is partial")
            segments[offset] = payload
        digest = hashlib.sha256()
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        except OSError as error:
            raise ExecutorContractError("cannot hash tensor bundle handle") from error
        _require(_file_snapshot(descriptor) == before, "tensor bundle changed while held")
        _require(digest.hexdigest() == expected_sha256, "tensor bundle SHA-256 drifted")
        result = segments
    except BaseException as error:
        primary = error
    close_errors: list[BaseException] = []
    for held in reversed(holds):
        try:
            os.close(held)
        except BaseException as error:
            close_errors.append(error)
    if close_errors:
        raise _DescriptorClosureError(
            operation="tensor_bundle_read",
            primary=primary,
            close_failures=close_errors,
        ) from (primary if primary is not None else close_errors[0])
    if primary is not None:
        raise primary
    _require(result is not None, "tensor bundle segments are unavailable")
    return result


def _read_selected_tensors(
    *,
    project_root: Path | str,
    candidate_root: Path | str,
    plan: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
) -> TensorInventory:
    root = Path(project_root).resolve()
    plan_candidate = _mapping(plan.get("candidate"), "pilot candidate")
    plan_candidate_root = PurePosixPath(str(plan_candidate.get("root")))
    supplied = PurePosixPath(str(candidate_root).replace("\\", "/"))
    if supplied.is_absolute():
        root_pure = PurePosixPath(str(root).replace("\\", "/"))
        try:
            supplied = supplied.relative_to(root_pure)
        except ValueError as error:
            raise ExecutorContractError("candidate root escaped the project root") from error
    _require(
        not plan_candidate_root.is_absolute()
        and ".." not in plan_candidate_root.parts
        and supplied == plan_candidate_root,
        "candidate root differs from the validated pilot plan",
    )
    grouped: dict[str, dict[str, object]] = {}
    for request in requests:
        tensor = _mapping(request.get("tensor"), "pilot tensor descriptor")
        path = str(tensor.get("path"))
        tensor_path = PurePosixPath(path)
        try:
            tensor_path.relative_to(plan_candidate_root)
        except ValueError as error:
            raise ExecutorContractError("tensor bundle escaped the candidate root") from error
        descriptor = {
            "path": path,
            "size_bytes": tensor.get("size_bytes"),
            "sha256": tensor.get("sha256"),
            "offsets": [],
        }
        existing = grouped.setdefault(path, descriptor)
        _require(
            existing["size_bytes"] == descriptor["size_bytes"]
            and existing["sha256"] == descriptor["sha256"],
            "shared tensor bundle descriptor drifted",
        )
        existing["offsets"].append(tensor.get("offset_bytes"))
    bundle_segments: dict[str, dict[int, bytes]] = {}
    observations: list[dict[str, object]] = []
    for path, raw in sorted(grouped.items()):
        size = raw["size_bytes"]
        digest = raw["sha256"]
        offsets = raw["offsets"]
        _require(type(size) is int and type(digest) is str, "tensor bundle descriptor drifted")
        _require(type(offsets) is list and all(type(item) is int for item in offsets), "tensor offsets drifted")
        bundle_segments[path] = _read_bundle_segments(
            _project_file(root, path, "candidate tensor bundle"),
            expected_size=size,
            expected_sha256=digest,
            offsets=offsets,
        )
        observations.append({"path": path, "size_bytes": size, "sha256": digest})
    payloads: dict[str, bytes] = {}
    for request in requests:
        tensor = _mapping(request.get("tensor"), "pilot tensor descriptor")
        payloads[str(request["request_id"])] = bundle_segments[str(tensor["path"])][
            int(tensor["offset_bytes"])
        ]
    return TensorInventory(payloads=payloads, bundle_observations=observations)


def _copy_exact_file(
    source: Path,
    destination: Path,
    expected: FileIdentity,
) -> None:
    source_fd, holds = _open_absolute_nofollow(source)
    destination_fd: int | None = None
    destination_identity: tuple[int, int, int, int, int, int, int] | None = None
    primary: BaseException | None = None
    try:
        before = _file_snapshot(source_fd)
        _require(
            stat.S_ISREG(before[3])
            and before[2] == expected.size_bytes,
            "model staging source identity drifted",
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        destination_fd = os.open(destination, flags, 0o400)
        destination_identity = _file_snapshot(destination_fd)
        digest = hashlib.sha256()
        os.lseek(source_fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                _require(written > 0, "model staging write made no progress")
                view = view[written:]
        os.fsync(destination_fd)
        _require(_file_snapshot(source_fd) == before, "model staging source changed during copy")
        _require(digest.hexdigest() == expected.sha256, "model staging source SHA-256 drifted")
        staged = os.fstat(destination_fd)
        _require(
            stat.S_ISREG(staged.st_mode)
            and staged.st_size == expected.size_bytes,
            "staged model file identity drifted",
        )
    except OSError as error:
        primary = ExecutorContractError("cannot stage exact model file")
        primary.__cause__ = error
    except BaseException as error:
        primary = error
    cleanup_errors: list[BaseException] = []
    if primary is not None and destination_fd is not None:
        try:
            held_now = _file_snapshot(destination_fd)
            named = os.stat(destination, follow_symlinks=False)
            _require(
                destination_identity is not None
                and held_now[:2] == destination_identity[:2]
                and (
                    int(named.st_dev),
                    int(named.st_ino),
                    int(named.st_size),
                    int(named.st_mode),
                    int(named.st_mtime_ns),
                    int(named.st_ctime_ns),
                    int(named.st_nlink),
                )
                == held_now,
                "partial staged model identity drifted before cleanup",
            )
            os.unlink(destination)
        except BaseException as error:
            cleanup_errors.append(error)
    if destination_fd is not None:
        try:
            os.close(destination_fd)
        except BaseException as error:
            cleanup_errors.append(error)
    for held in reversed(holds):
        try:
            os.close(held)
        except BaseException as error:
            cleanup_errors.append(error)
    if primary is None and cleanup_errors and destination_identity is not None:
        try:
            named = os.stat(destination, follow_symlinks=False)
            _require(
                int(named.st_dev) == destination_identity[0]
                and int(named.st_ino) == destination_identity[1],
                "staged model identity drifted before close-failure cleanup",
            )
            os.unlink(destination)
        except BaseException as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        raise _DescriptorClosureError(
            operation="exact_model_file_copy",
            primary=primary,
            close_failures=cleanup_errors,
            message="cannot stage and close exact model file",
        ) from (primary if primary is not None else cleanup_errors[0])
    if primary is not None:
        raise primary


def _stage_model_inventory(
    run_root: Path,
    inventory: BindingInventory,
) -> tuple[BindingInventory, tuple[Path, ...], Path]:
    models_root = run_root / "model_staging"
    source_paths: dict[str, Path] = {}
    engine_paths: dict[str, Path] = {}
    staged: list[Path] = []
    planned: list[Path] = []
    used_names: set[str] = set()
    root_created = False
    try:
        os.mkdir(models_root, 0o700)
        root_created = True
        for branch in BRANCHES:
            for kind, source, expected, target_map in (
                (
                    "source",
                    Path(inventory.source_paths[branch]),
                    inventory.source_identities[branch],
                    source_paths,
                ),
                (
                    "engine",
                    Path(inventory.engine_paths[branch]),
                    inventory.engine_identities[branch],
                    engine_paths,
                ),
            ):
                name = source.name
                _require(name not in used_names, "staged model basename collision")
                used_names.add(name)
                destination = models_root / name
                planned.append(destination)
                _copy_exact_file(source, destination, expected)
                _require(
                    _observe_regular_file(destination) == expected,
                    f"staged {branch} {kind} identity drifted",
                )
                target_map[branch] = destination
                staged.append(destination)
        return (
            BindingInventory(
                bindings=inventory.bindings,
                source_paths=source_paths,
                engine_paths=engine_paths,
                source_identities=inventory.source_identities,
                engine_identities=inventory.engine_identities,
                manifest_identity_sha256=inventory.manifest_identity_sha256,
                execution_config_identity_sha256=inventory.execution_config_identity_sha256,
            ),
            tuple(staged),
            models_root,
        )
    except BaseException as primary_error:
        cleanup_errors: list[BaseException] = []
        if root_created:
            for destination in reversed(planned):
                try:
                    value = os.stat(destination, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except BaseException as error:
                    cleanup_errors.append(error)
                    continue
                try:
                    _require(
                        stat.S_ISREG(value.st_mode)
                        and value.st_uid == os.getuid()
                        and value.st_gid == os.getgid()
                        and value.st_nlink == 1,
                        "staged model cleanup identity drifted",
                    )
                    os.unlink(destination)
                except BaseException as error:
                    cleanup_errors.append(error)
            try:
                _require(
                    not os.listdir(models_root),
                    "model staging root retained unknown entries",
                )
                os.rmdir(models_root)
            except BaseException as error:
                cleanup_errors.append(error)
        if cleanup_errors:
            raise _DescriptorClosureError(
                operation="model_inventory_staging",
                primary=primary_error,
                close_failures=cleanup_errors,
                message="model inventory staging cleanup failed",
            ) from primary_error
        raise


def _build_inference_request(
    *,
    request: Mapping[str, object],
    binding: Mapping[str, object],
    capability: Mapping[str, object],
    run_id: str,
) -> dict[str, object]:
    tensor = _mapping(request.get("tensor"), "pilot inference tensor")
    offset = tensor.get("offset_bytes")
    _require(type(offset) is int, "pilot inference tensor offset drifted")
    sample_id = request.get("sample_id")
    codec = request.get("codec")
    _require(type(sample_id) is str and bool(sample_id), "pilot inference sample ID drifted")
    _require(codec in CODECS, "pilot inference codec drifted")
    return {
        "schema_version": 1,
        "message_type": "infer_request",
        "request_id": request["request_id"],
        "run_id": run_id,
        "arm_id": f"nonpublication-tensorrt-{request['branch']}",
        "worker_id": capability["worker_id"],
        "frame": {
            "input_frame_key": sample_id,
            "stream_id": 0,
            # This is the coordinator-local request ordinal.  The planner's
            # tensor offset is byte custody, not decoded-frame provenance.
            "frame_id": list(CODECS).index(codec),
            "transport_pts_ns": 0,
            "branch": request["branch"],
        },
        "engine": ENGINE_TENSORRT_CUDA,
        "deadline_monotonic_ns": time.monotonic_ns() + 120_000_000_000,
        "model": {
            "model_id": capability["model_id"],
            "source_sha256": capability["source_model_sha256"],
            "runtime_artifact_sha256": capability["model_artifact_sha256"],
            "runtime_weights_sha256": None,
        },
        "tensor": {
            "name": _mapping(binding.get("input"), "TensorRT binding input")["name"],
            "dtype": tensor["dtype"],
            "layout": tensor["layout"],
            "shape": list(tensor["shape"]),
            "byte_length": TENSOR_SEGMENT_BYTES,
            "sha256": tensor["segment_sha256"],
            "preprocessing_contract_sha256": tensor[
                "preprocessing_contract_sha256"
            ],
        },
        "expected_output_contract_sha256": capability[
            "output_contract_sha256"
        ],
    }


def _execute_requests_with_client(
    *,
    client: Any,
    capability: Mapping[str, object],
    branch: str,
    run_id: str,
    binding: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    payloads: TensorInventory,
    peer_identity: Mapping[str, object] | None = None,
    handshake_barrier: threading.Barrier | None = None,
    progress: _ExecutionProgressLedger,
) -> list[dict[str, object]]:
    actual_capability = client.handshake()
    _require(actual_capability == capability, f"{branch} worker capability drifted")
    capability_sha = hashlib.sha256(_canonical_json(dict(capability))).hexdigest()
    peer_identity_sha = (
        hashlib.sha256(_canonical_json(dict(peer_identity))).hexdigest()
        if peer_identity is not None
        else None
    )
    progress.record_handshake(
        branch=branch,
        capability_sha256=capability_sha,
        peer_identity_sha256=peer_identity_sha,
    )
    if handshake_barrier is not None:
        _require(
            type(handshake_barrier) is threading.Barrier
            and handshake_barrier.parties == len(BRANCHES),
            "worker handshake barrier drifted",
        )
        try:
            handshake_barrier.wait(timeout=180.0)
        except threading.BrokenBarrierError as error:
            raise ExecutorContractError(
                "four-worker capability handshake barrier failed"
            ) from error
    completed_peer_identity = (
        _complete_peer_identity_after_handshake(peer_identity)
        if peer_identity is not None
        else None
    )
    observations: list[dict[str, object]] = []
    for request_ordinal, request in enumerate(requests):
        inference_request = _build_inference_request(
            request=request,
            binding=binding,
            capability=capability,
            run_id=run_id,
        )
        request_id = str(request["request_id"])
        progress.record_infer_dispatched(
            branch=branch,
            request_id=request_id,
            request_ordinal=request_ordinal,
            capability_sha256=capability_sha,
            peer_identity_sha256=peer_identity_sha,
        )
        response, output = client.infer(
            inference_request,
            payloads.payloads[request_id],
        )
        progress.record_client_returned(
            branch=branch,
            request_id=request_id,
            request_ordinal=request_ordinal,
            response_is_dict=type(response) is dict,
            output_is_bytes=type(output) is bytes,
            output_size_bytes=(len(output) if type(output) is bytes else None),
        )
        _require(type(response) is dict and type(output) is bytes, "TensorRT worker response type drifted")
        _require(len(output) == 4000, "TensorRT worker output byte count drifted")
        response_sha = hashlib.sha256(_canonical_json(response)).hexdigest()
        output_sha = hashlib.sha256(output).hexdigest()
        progress.record_infer_response(
            branch=branch,
            request_id=request_id,
            request_ordinal=request_ordinal,
            response_sha256=response_sha,
            output_sha256=output_sha,
            output_size_bytes=len(output),
            capability_sha256=capability_sha,
            peer_identity_sha256=peer_identity_sha,
        )
        observation: dict[str, object] = {
                "request_id": request["request_id"],
                "branch": branch,
                "codec": request["codec"],
                "response_sha256": response_sha,
                "output_sha256": output_sha,
                "output_size_bytes": len(output),
                "worker_capability_sha256": capability_sha,
                "terminal_status": "completed",
            }
        if completed_peer_identity is not None:
            observation["peer_identity"] = dict(completed_peer_identity)
        observations.append(observation)
    return observations


def _peer_credentials_are_exact(peer_pid: int, peer_uid: int, peer_gid: int) -> bool:
    return (
        peer_pid > 0
        and peer_uid == CONTAINER_UID
        and peer_gid == CONTAINER_GID
    )


def _build_peercred_pid0_platform_observation(
    osrelease_raw: bytes,
    daemon_value: Mapping[str, object],
) -> dict[str, object]:
    daemon = _validate_daemon_observation(daemon_value)
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
        raise ExecutorContractError("WSL osrelease is not ASCII") from error
    osrelease_value = osrelease_text[:-1]
    _require(
        0 < len(osrelease_value) <= _WSL_OSRELEASE_MAX_BYTES - 1
        and _WSL2_OSRELEASE_RE.fullmatch(osrelease_value) is not None,
        "WSL2 osrelease marker drifted",
    )
    _require(
        daemon["name"] == "docker-desktop"
        and daemon["operating_system"] == "Docker Desktop"
        and daemon["kernel_version"] == osrelease_value
        and daemon["driver"] == "overlayfs"
        and daemon["driver_status"]
        == [["driver-type", "io.containerd.snapshotter.v1"]]
        and daemon["default_runtime"] == "runc"
        and daemon["containerd_commit"]
        == {"ID": _DOCKER_DESKTOP_CONTAINERD_COMMIT_ID},
        "Docker Desktop WSL2 containerd backend drifted",
    )
    wsl_osrelease = {
        "path": _WSL_OSRELEASE_CANONICAL_PATH,
        "raw_ascii": osrelease_text,
        "size_bytes": len(osrelease_raw),
        "sha256": hashlib.sha256(osrelease_raw).hexdigest(),
        "marker": _WSL2_OSRELEASE_MARKER,
        "marker_present": True,
    }
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": "vast_kpp_v2_peercred_pid0_platform_observation",
        "daemon_observation_sha256": daemon["observation_sha256"],
        "daemon_name": daemon["name"],
        "daemon_operating_system": daemon["operating_system"],
        "daemon_kernel_version": daemon["kernel_version"],
        "daemon_driver": daemon["driver"],
        "daemon_driver_status": daemon["driver_status"],
        "daemon_default_runtime": daemon["default_runtime"],
        "daemon_containerd_commit": daemon["containerd_commit"],
        "wsl_osrelease": wsl_osrelease,
    }
    return {
        **core,
        "observation_sha256": hashlib.sha256(
            PEERCRED_PLATFORM_DOMAIN + canonical_line(core)
        ).hexdigest(),
    }


def _validate_peercred_pid0_platform_observation(
    value: Mapping[str, object],
) -> dict[str, object]:
    observed = dict(_mapping(value, "peercred pid0 platform observation"))
    fields = {
        "schema_version",
        "artifact_kind",
        "daemon_observation_sha256",
        "daemon_name",
        "daemon_operating_system",
        "daemon_kernel_version",
        "daemon_driver",
        "daemon_driver_status",
        "daemon_default_runtime",
        "daemon_containerd_commit",
        "wsl_osrelease",
        "observation_sha256",
    }
    _require(set(observed) == fields, "peercred pid0 platform fields drifted")
    _require(
        observed.get("schema_version") == 1
        and observed.get("artifact_kind")
        == "vast_kpp_v2_peercred_pid0_platform_observation",
        "peercred pid0 platform header drifted",
    )
    wsl = dict(_mapping(observed.get("wsl_osrelease"), "WSL osrelease observation"))
    _require(
        set(wsl)
        == {
            "path",
            "raw_ascii",
            "size_bytes",
            "sha256",
            "marker",
            "marker_present",
        }
        and wsl.get("path") == _WSL_OSRELEASE_CANONICAL_PATH
        and type(wsl.get("raw_ascii")) is str,
        "WSL osrelease observation fields drifted",
    )
    try:
        raw = wsl["raw_ascii"].encode("ascii")
    except UnicodeError as error:
        raise ExecutorContractError("WSL osrelease observation is not ASCII") from error
    _require(
        0 < len(raw) <= _WSL_OSRELEASE_MAX_BYTES
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
    release = wsl["raw_ascii"][:-1]
    _require(
        _WSL2_OSRELEASE_RE.fullmatch(release) is not None
        and observed.get("daemon_name") == "docker-desktop"
        and observed.get("daemon_operating_system") == "Docker Desktop"
        and observed.get("daemon_kernel_version") == release
        and observed.get("daemon_driver") == "overlayfs"
        and observed.get("daemon_driver_status")
        == [["driver-type", "io.containerd.snapshotter.v1"]]
        and observed.get("daemon_default_runtime") == "runc"
        and observed.get("daemon_containerd_commit")
        == {"ID": _DOCKER_DESKTOP_CONTAINERD_COMMIT_ID}
        and type(observed.get("daemon_observation_sha256")) is str
        and _SHA_RE.fullmatch(observed["daemon_observation_sha256"]) is not None,
        "peercred pid0 platform backend drifted",
    )
    claimed = observed.pop("observation_sha256")
    _require(
        type(claimed) is str
        and _SHA_RE.fullmatch(claimed) is not None
        and claimed
        == hashlib.sha256(
            PEERCRED_PLATFORM_DOMAIN + canonical_line(observed)
        ).hexdigest(),
        "peercred pid0 platform identity drifted",
    )
    return {**observed, "observation_sha256": claimed}


def _observe_peercred_pid0_platform(
    daemon: Mapping[str, object],
    *,
    path: Path = _WSL_OSRELEASE_PATH,
) -> dict[str, object]:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and path == _WSL_OSRELEASE_PATH,
        "peercred pid0 platform observation requires Linux",
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    _require(
        getattr(os, "O_NOFOLLOW", 0) != 0,
        "peercred pid0 platform no-follow custody is unavailable",
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        named_before = os.stat(path, follow_symlinks=False)
        _require(
            stat.S_ISREG(before.st_mode)
            and _directory_identity(before) == _directory_identity(named_before)
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
        after = os.fstat(descriptor)
        named_after = os.stat(path, follow_symlinks=False)
        _require(
            _directory_identity(before)
            == _directory_identity(after)
            == _directory_identity(named_after),
            "WSL osrelease file identity changed during observation",
        )
        return _build_peercred_pid0_platform_observation(bytes(payload), daemon)
    except OSError as error:
        raise ExecutorContractError("cannot observe WSL osrelease") from error
    finally:
        active_error = sys.exception()
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as close_error:
                raise _DescriptorClosureError(
                    operation="wsl_osrelease_observation",
                    primary=active_error,
                    close_failures=[close_error],
                ) from (
                    active_error if active_error is not None else close_error
                )


def _select_peer_identity(
    *,
    selected_mode: str,
    peer_raw: bytes,
    docker_state_pid: object,
    runtime_daemon: Mapping[str, object],
    runtime_platform: Mapping[str, object] | None,
    runtime_custody: Mapping[str, object],
) -> dict[str, object]:
    _require(
        type(selected_mode) is str and selected_mode in PEER_IDENTITY_MODES,
        "peer identity mode drifted",
    )
    _require(
        type(peer_raw) is bytes and len(peer_raw) == struct.calcsize("3i"),
        "peer credential raw bytes drifted",
    )
    peer_pid, peer_uid, peer_gid = struct.unpack("3i", peer_raw)
    _require(
        type(docker_state_pid) is int
        and 0 < docker_state_pid < 2**31,
        "Docker running state PID drifted",
    )
    custody = dict(_mapping(runtime_custody, "peer runtime custody"))
    _require(
        set(custody)
        == {
            "native_ipc_namespace_attested",
            "readonly_mounts_attested",
            "container_image_entrypoint_identity_attested",
            "docker_desktop_wsl_distro_label_attested",
            "container_runtime",
        }
        and custody.get("native_ipc_namespace_attested") is True
        and custody.get("readonly_mounts_attested") is True
        and custody.get("container_image_entrypoint_identity_attested") is True
        and type(custody.get("docker_desktop_wsl_distro_label_attested")) is bool
        and custody.get("container_runtime") == "runc",
        "peer runtime custody drifted",
    )
    daemon = _validate_daemon_observation(runtime_daemon)
    _require(
        peer_uid == CONTAINER_UID and peer_gid == CONTAINER_GID,
        "TensorRT peer UID/GID drifted",
    )
    if selected_mode == PEER_IDENTITY_MODE_NATIVE_VISIBLE:
        _require(peer_pid > 0, "native peer PID is not positive")
        _require(
            peer_pid == docker_state_pid,
            "peer PID differs from container init",
        )
        _require(
            runtime_platform is None,
            "native peer mode received a namespace-hidden platform observation",
        )
        platform_sha: str | None = None
        wsl_attested = False
        backend_attested = False
        pid_visible = True
        pid_equal = True
        pid_identity = True
        socket_pid_binding = True
    else:
        _require(
            peer_pid == 0,
            "namespace-hidden peer mode requires exact PID zero",
        )
        _require(
            runtime_platform is not None,
            "namespace-hidden peer platform observation is unavailable",
        )
        platform = _validate_peercred_pid0_platform_observation(runtime_platform)
        _require(
            daemon["name"] == platform["daemon_name"] == "docker-desktop"
            and daemon["operating_system"]
            == platform["daemon_operating_system"]
            == "Docker Desktop"
            and daemon["kernel_version"] == platform["daemon_kernel_version"]
            and daemon["driver"] == platform["daemon_driver"] == "overlayfs"
            and daemon["driver_status"] == platform["daemon_driver_status"]
            == [["driver-type", "io.containerd.snapshotter.v1"]]
            and daemon["default_runtime"]
            == platform["daemon_default_runtime"]
            == "runc"
            and daemon["containerd_commit"]
            == platform["daemon_containerd_commit"]
            == {"ID": _DOCKER_DESKTOP_CONTAINERD_COMMIT_ID}
            and daemon["observation_sha256"]
            == platform["daemon_observation_sha256"]
            and custody["docker_desktop_wsl_distro_label_attested"] is True,
            "namespace-hidden Docker Desktop WSL2 identity drifted",
        )
        platform_sha = str(platform["observation_sha256"])
        wsl_attested = True
        backend_attested = True
        pid_visible = False
        pid_equal = False
        pid_identity = False
        socket_pid_binding = False
    return {
        "schema_version": 2,
        "policy_version": PEER_IDENTITY_POLICY_VERSION,
        "peer_identity_mode": selected_mode,
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
        "peer_identity_by_pid_attested": pid_identity,
        "peer_socket_to_container_pid_binding_attested": socket_pid_binding,
        "docker_desktop_containerd_backend_attested": backend_attested,
        "wsl2_platform_attested": wsl_attested,
        "platform_observation_sha256": platform_sha,
        "native_ipc_namespace_attested": True,
        "readonly_mounts_attested": True,
        "container_image_entrypoint_identity_attested": True,
        "protocol_nonce_capability_handshake_required": True,
        "protocol_nonce_capability_handshake_performed": False,
        "global_four_worker_handshake_barrier_attested": False,
        "peer_identity_by_protocol_capability_attested": False,
        "concurrent_same_uid_socket_connector_excluded": True,
        "concurrent_windows_side_project_writer_excluded": True,
    }


def _validate_peer_identity_observation(
    value: Mapping[str, object],
    *,
    completed_handshake: bool,
) -> dict[str, object]:
    peer = dict(_mapping(value, "peer identity observation"))
    _require(
        type(completed_handshake) is bool
        and set(peer)
        == {
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
            "native_ipc_namespace_attested",
            "readonly_mounts_attested",
            "container_image_entrypoint_identity_attested",
            "protocol_nonce_capability_handshake_required",
            "protocol_nonce_capability_handshake_performed",
            "global_four_worker_handshake_barrier_attested",
            "peer_identity_by_protocol_capability_attested",
            "concurrent_same_uid_socket_connector_excluded",
            "concurrent_windows_side_project_writer_excluded",
        },
        "peer identity observation fields drifted",
    )
    _require(
        peer.get("schema_version") == 2
        and peer.get("policy_version") == PEER_IDENTITY_POLICY_VERSION
        and peer.get("peer_identity_mode") in PEER_IDENTITY_MODES,
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
        raise ExecutorContractError("peer identity raw encoding drifted") from error
    _require(
        type(peer.get("peer_raw_hex")) is str
        and len(raw) == struct.calcsize("3i")
        and struct.unpack("3i", raw)
        == (peer["peer_pid"], peer["peer_uid"], peer["peer_gid"])
        and peer.get("peer_raw_sha256") == hashlib.sha256(raw).hexdigest()
        and peer.get("peer_uid") == CONTAINER_UID
        and peer.get("peer_gid") == CONTAINER_GID
        and peer.get("peer_uid_gid_exact") is True
        and peer.get("container_state_pid_positive") is True
        and peer.get("pid_positive") is (peer["peer_pid"] > 0)
        and peer.get("pid_matches_container_state_pid")
        is (peer["peer_pid"] == peer["container_state_pid"])
        and 0 < peer["container_state_pid"] < 2**31,
        "peer identity credential facts drifted",
    )
    for field in (
        "peer_pid_visible_in_controller_namespace",
        "peer_pid_state_pid_equality_attested",
        "peer_identity_by_pid_attested",
        "peer_socket_to_container_pid_binding_attested",
        "docker_desktop_containerd_backend_attested",
        "wsl2_platform_attested",
        "native_ipc_namespace_attested",
        "readonly_mounts_attested",
        "container_image_entrypoint_identity_attested",
        "protocol_nonce_capability_handshake_required",
        "protocol_nonce_capability_handshake_performed",
        "global_four_worker_handshake_barrier_attested",
        "peer_identity_by_protocol_capability_attested",
        "concurrent_same_uid_socket_connector_excluded",
        "concurrent_windows_side_project_writer_excluded",
    ):
        _require(type(peer.get(field)) is bool, f"peer identity {field} drifted")
    _require(
        peer["native_ipc_namespace_attested"] is True
        and peer["readonly_mounts_attested"] is True
        and peer["container_image_entrypoint_identity_attested"] is True
        and peer["protocol_nonce_capability_handshake_required"] is True
        and peer["protocol_nonce_capability_handshake_performed"]
        is completed_handshake
        and peer["global_four_worker_handshake_barrier_attested"]
        is completed_handshake
        and peer["peer_identity_by_protocol_capability_attested"]
        is completed_handshake
        and peer["concurrent_same_uid_socket_connector_excluded"] is True
        and peer["concurrent_windows_side_project_writer_excluded"] is True,
        "peer identity custody or handshake facts drifted",
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
            and peer["platform_observation_sha256"] is None,
            "native peer identity facts drifted",
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
            and type(peer["platform_observation_sha256"]) is str
            and _SHA_RE.fullmatch(peer["platform_observation_sha256"]) is not None,
            "namespace-hidden peer identity facts drifted",
        )
    return peer


def _complete_peer_identity_after_handshake(
    value: Mapping[str, object],
) -> dict[str, object]:
    peer = _validate_peer_identity_observation(
        value,
        completed_handshake=False,
    )
    completed = {
        **peer,
        "protocol_nonce_capability_handshake_performed": True,
        "global_four_worker_handshake_barrier_attested": True,
        "peer_identity_by_protocol_capability_attested": True,
    }
    return _validate_peer_identity_observation(
        completed,
        completed_handshake=True,
    )


def _peercred_diagnostic_filesystem_custody(
    root_descriptor: int,
) -> dict[str, object]:
    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and type(root_descriptor) is int
        and root_descriptor >= 0,
        "SO_PEERCRED diagnostic filesystem custody requires Linux",
    )
    root_state = os.fstat(root_descriptor)
    _require(
        stat.S_ISDIR(root_state.st_mode)
        and root_state.st_nlink >= 1
        and root_state.st_uid == os.getuid()
        and root_state.st_gid == os.getgid(),
        "SO_PEERCRED diagnostic run root custody drifted",
    )
    filesystem_magic = _linux_fstatfs_magic(root_descriptor)
    root_mode = stat.S_IMODE(root_state.st_mode)
    if (
        filesystem_magic == _LINUX_EXT_FILESYSTEM_MAGIC
        and root_mode == 0o700
    ):
        filesystem_type = "linux_ext_native"
        mount_observation = "native_ext_mode_enforcement"
        file_mode = 0o400
    elif filesystem_magic == _LINUX_V9FS_MAGIC and root_mode == 0o777:
        filesystem_type = "drvfs_9p_without_metadata_observed"
        mount_observation = "drvfs_9p_effective_mode_projection"
        file_mode = 0o555
    else:
        raise ExecutorContractError(
            "SO_PEERCRED diagnostic filesystem type or root mode drifted"
        )
    return {
        "statfs_magic": filesystem_magic,
        "statfs_magic_hex": f"0x{filesystem_magic:08x}",
        "filesystem_type": filesystem_type,
        "mount_observation": mount_observation,
        "run_root_effective_mode": f"{root_mode:04o}",
        "requested_file_mode": "0400",
        "file_effective_mode": f"{file_mode:04o}",
    }


def _write_peercred_failure_diagnostic(
    *,
    project_root: Path,
    run_root: Path,
    logical_run_root: str,
    run_identity: str,
    plan: Mapping[str, object],
    bindings: BindingInventory,
    branch: str,
    container_id: str,
    container_name: str,
    peer_pid: int,
    peer_uid: int,
    peer_gid: int,
    peer_raw: bytes,
    docker_state_pid: int,
    container_user: str,
    executor_source_path: str,
    executor_source_identity: FileIdentity,
    diagnostic_only: bool = False,
) -> Path:
    _require(branch in BRANCHES, "SO_PEERCRED diagnostic branch drifted")
    _require(
        type(run_identity) is str and _SHA_RE.fullmatch(run_identity) is not None,
        "SO_PEERCRED diagnostic run identity drifted",
    )
    _require(
        type(logical_run_root) is str,
        "SO_PEERCRED diagnostic logical run root type drifted",
    )
    logical = PurePosixPath(logical_run_root)
    _require(
        len(logical.parts) == 3
        and logical.parts[:2] == ("runs", "nonpublication")
        and _RUN_ID_RE.fullmatch(logical.parts[2]) is not None,
        "SO_PEERCRED diagnostic logical run root drifted",
    )
    run_id = logical.parts[2]
    _require(
        isinstance(project_root, Path)
        and project_root.is_absolute()
        and project_root.is_dir()
        and not project_root.is_symlink()
        and project_root.resolve() == project_root,
        "SO_PEERCRED diagnostic project root drifted",
    )
    _require(
        run_root.is_absolute()
        and run_root == project_root.joinpath(*logical.parts)
        and run_root.resolve() == run_root
        and run_root.name == run_id
        and run_root.is_dir()
        and not run_root.is_symlink(),
        "SO_PEERCRED diagnostic run namespace drifted",
    )
    _require(
        type(container_id) is str
        and _CONTAINER_ID_RE.fullmatch(container_id) is not None
        and type(container_name) is str
        and container_name
        == f"vast-kpp-v2-np-{run_identity[:16]}-{branch}",
        "SO_PEERCRED diagnostic container identity drifted",
    )
    for value, label in (
        (peer_pid, "peer PID"),
        (peer_uid, "peer UID"),
        (peer_gid, "peer GID"),
    ):
        _require(
            type(value) is int and -(2**31) <= value < 2**31,
            f"SO_PEERCRED diagnostic {label} type or bounds drifted",
        )
    _require(
        type(peer_raw) is bytes
        and len(peer_raw) == struct.calcsize("3i")
        and struct.unpack("3i", peer_raw) == (peer_pid, peer_uid, peer_gid),
        "SO_PEERCRED diagnostic raw credential bytes drifted",
    )
    _require(
        type(docker_state_pid) is int and 0 < docker_state_pid < 2**31,
        "SO_PEERCRED diagnostic Docker state PID drifted",
    )
    _require(
        type(container_user) is str
        and container_user == f"{CONTAINER_UID}:{CONTAINER_GID}",
        "SO_PEERCRED diagnostic container user drifted",
    )
    _require(
        type(diagnostic_only) is bool,
        "SO_PEERCRED diagnostic-only selector drifted",
    )
    peer_credentials_exact = _peer_credentials_are_exact(
        peer_pid,
        peer_uid,
        peer_gid,
    )
    _require(
        diagnostic_only or not peer_credentials_exact,
        "SO_PEERCRED diagnostic cannot record accepted credentials",
    )
    _require(
        type(executor_source_path) is str
        and executor_source_path
        == "scripts/kpp_legacy_iss_v2_secondary_sensitivity_executor.py"
        and type(executor_source_identity) is FileIdentity
        and type(executor_source_identity.size_bytes) is int
        and executor_source_identity.size_bytes > 0
        and _SHA_RE.fullmatch(executor_source_identity.sha256) is not None
        and executor_source_identity.is_regular_file is True
        and executor_source_identity.is_symlink is False,
        "SO_PEERCRED diagnostic executor identity drifted",
    )
    _require(type(bindings) is BindingInventory, "SO_PEERCRED diagnostic binding inventory drifted")
    role = plan.get("role")
    _require(
        type(role) is str and role in {"secondary", "sensitivity"},
        "SO_PEERCRED diagnostic role drifted",
    )
    decision = _mapping(plan.get("decision"), "SO_PEERCRED diagnostic decision")
    candidate = _mapping(plan.get("candidate"), "SO_PEERCRED diagnostic candidate")
    receipt = _mapping(candidate.get("receipt"), "SO_PEERCRED diagnostic receipt")
    execution_pins = {
        "executor_source": {
            "path": executor_source_path,
            "size_bytes": executor_source_identity.size_bytes,
            "sha256": executor_source_identity.sha256,
        },
        "run_id": run_id,
        "run_identity_sha256": run_identity,
        "role": role,
        "pilot_plan_sha256": _sha(
            plan.get("pilot_plan_sha256"), "SO_PEERCRED diagnostic pilot plan"
        ),
        "matrix_identity_sha256": _sha(
            plan.get("matrix_identity_sha256"), "SO_PEERCRED diagnostic matrix identity"
        ),
        "decision_sha256": _sha(
            decision.get("decision_sha256"), "SO_PEERCRED diagnostic decision identity"
        ),
        "candidate_receipt_file_sha256": _sha(
            receipt.get("sha256"), "SO_PEERCRED diagnostic receipt file identity"
        ),
        "candidate_receipt_self_sha256": _sha(
            receipt.get("candidate_receipt_sha256"),
            "SO_PEERCRED diagnostic receipt self identity",
        ),
        "model_parity_manifest_identity_sha256": _sha(
            bindings.manifest_identity_sha256,
            "SO_PEERCRED diagnostic model parity manifest identity",
        ),
        "execution_config_identity_sha256": _sha(
            bindings.execution_config_identity_sha256,
            "SO_PEERCRED diagnostic execution config identity",
        ),
        "required_image_id": TENSORRT_IMAGE_ID,
        "gpu_uuid": TENSORRT_GPU_UUID,
        "diagnostic_only": diagnostic_only,
    }
    filename = (
        f"so_peercred_diagnostic.{branch}.json"
        if diagnostic_only
        else f"so_peercred_failure.{branch}.json"
    )
    destination = run_root / filename
    _require(
        os.name == "posix" and sys.platform.startswith("linux"),
        "SO_PEERCRED diagnostic persistence requires Linux",
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    root_descriptor: int | None = None
    descriptor: int | None = None
    read_descriptor: int | None = None
    try:
        root_descriptor = os.open(
            run_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        root_state = os.fstat(root_descriptor)
        path_state = os.stat(run_root, follow_symlinks=False)
        _require(
            _directory_identity(root_state) == _directory_identity(path_state),
            "SO_PEERCRED diagnostic run namespace identity drifted",
        )
        filesystem_custody = _peercred_diagnostic_filesystem_custody(
            root_descriptor
        )
        core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": PEERCRED_DIAGNOSTIC_ARTIFACT_KIND,
            "claim_status": "controller_runtime_diagnostic_nonpublication_not_evidence",
            "diagnostic_reason": (
                "diagnostic_only_stop_before_handshake"
                if diagnostic_only
                else "so_peercred_rejected"
            ),
            "branch": branch,
            "container": {
                "container_id": container_id,
                "container_name": container_name,
                "config_user": container_user,
                "state_pid": docker_state_pid,
                "required_image_id": TENSORRT_IMAGE_ID,
            },
            "peer_credentials": {
                "pid": peer_pid,
                "uid": peer_uid,
                "gid": peer_gid,
                "raw_hex": peer_raw.hex(),
                "raw_size_bytes": len(peer_raw),
                "native_struct_format": "3i",
                "native_byteorder": sys.byteorder,
                "expected_uid": CONTAINER_UID,
                "expected_gid": CONTAINER_GID,
                "pid_positive": peer_pid > 0,
                "uid_matches": peer_uid == CONTAINER_UID,
                "gid_matches": peer_gid == CONTAINER_GID,
                "state_pid_matches": peer_pid == docker_state_pid,
            },
            "stages": {
                "listener_accept_succeeded": True,
                "socket_timeout_set": True,
                "so_peercred_read_succeeded": True,
                "peercred_exact_uid_gid_match_observed": peer_credentials_exact,
                "peer_credentials_accepted_for_inference": False,
                "running_container_inspect_succeeded": True,
                "container_state_pid_compared": True,
                "capability_handshake_started": False,
                "inference_started": False,
            },
            "execution_pins": execution_pins,
            "filesystem_custody": filesystem_custody,
            "diagnostic_only": diagnostic_only,
            "confidentiality_attested": False,
            "filesystem_acl_attested": False,
            "windows_acl_attested": False,
            "peer_credentials_accepted_for_inference": False,
            "capability_handshake_performed": False,
            "operational_completion_observed": False,
            "inference_performed": False,
            **_FALSE_CLAIMS,
        }
        document = {
            **core,
            "diagnostic_sha256": hashlib.sha256(
                PEERCRED_DIAGNOSTIC_DOMAIN + canonical_line(core)
            ).hexdigest(),
        }
        payload = canonical_line(document)
        descriptor = os.open(
            filename,
            flags,
            0o400,
            dir_fd=root_descriptor,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, "cannot write SO_PEERCRED diagnostic")
            view = view[written:]
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        file_state = os.fstat(descriptor)
        _require(
            stat.S_ISREG(file_state.st_mode)
            and file_state.st_nlink == 1
            and file_state.st_size == len(payload),
            "SO_PEERCRED diagnostic file custody drifted",
        )
        file_mode = stat.S_IMODE(file_state.st_mode)
        _require(
            file_state.st_uid == os.getuid()
            and file_state.st_gid == os.getgid()
            and f"{file_mode:04o}"
            == filesystem_custody["file_effective_mode"]
            and file_mode & 0o222 == 0,
            "SO_PEERCRED diagnostic file owner or mode drifted",
        )
        _require(
            _peercred_diagnostic_filesystem_custody(root_descriptor)
            == filesystem_custody,
            "SO_PEERCRED diagnostic filesystem custody drifted during persistence",
        )
        os.fsync(root_descriptor)
        read_descriptor = os.open(
            filename,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_descriptor,
        )
        read_state = os.fstat(read_descriptor)
        _require(
            (
                int(read_state.st_dev),
                int(read_state.st_ino),
                int(read_state.st_mode),
                int(read_state.st_uid),
                int(read_state.st_gid),
                int(read_state.st_nlink),
                int(read_state.st_size),
            )
            == (
                int(file_state.st_dev),
                int(file_state.st_ino),
                int(file_state.st_mode),
                int(file_state.st_uid),
                int(file_state.st_gid),
                int(file_state.st_nlink),
                int(file_state.st_size),
            ),
            "SO_PEERCRED diagnostic durable readback drifted",
        )
        readback = bytearray()
        while len(readback) <= len(payload):
            chunk = os.read(
                read_descriptor,
                min(1024 * 1024, len(payload) + 1 - len(readback)),
            )
            if not chunk:
                break
            readback.extend(chunk)
        _require(
            bytes(readback) == payload,
            "SO_PEERCRED diagnostic durable readback drifted",
        )
        final_path_state = os.stat(run_root, follow_symlinks=False)
        _require(
            _directory_identity(root_state)
            == _directory_identity(final_path_state),
            "SO_PEERCRED diagnostic run namespace identity drifted",
        )
    except OSError as error:
        raise ExecutorContractError("cannot persist SO_PEERCRED failure diagnostic") from error
    finally:
        active_error = sys.exception()
        close_errors: list[BaseException] = []
        for held in (read_descriptor, descriptor, root_descriptor):
            if held is not None:
                try:
                    os.close(held)
                except BaseException as error:
                    close_errors.append(error)
        if close_errors:
            raise _DescriptorClosureError(
                operation="peercred_failure_diagnostic",
                primary=active_error,
                close_failures=close_errors,
                message="cannot persist or close SO_PEERCRED failure diagnostic",
            ) from (
                active_error if active_error is not None else close_errors[0]
            )
    return destination


def _close_watched_ipc_listener(
    *,
    listener: Any,
    ipc_watchdog: _IpcRuntimeWatchdogProcess,
    ipc_control_lock: threading.Lock,
    branch: str,
    registered: bool,
) -> None:
    _require(
        type(branch) is str
        and branch in BRANCHES
        and type(registered) is bool,
        "watched IPC listener cleanup state drifted",
    )
    close_error: BaseException | None = None
    try:
        listener.close()
    except BaseException as error:
        close_error = error
    release_error: BaseException | None = None
    if registered:
        try:
            with ipc_control_lock:
                ipc_watchdog.release(branch)
        except BaseException as error:
            release_error = error
    if close_error is not None or release_error is not None:
        failures: list[_SupplementalExecutionFailure] = []
        if close_error is not None:
            failures.append(
                _SupplementalExecutionFailure(
                    scope="ipc_listener_close",
                    phase="final_cleanup",
                    stage="ipc_listener_close",
                    branch=branch,
                    error=close_error,
                )
            )
        if release_error is not None:
            failures.append(
                _SupplementalExecutionFailure(
                    scope="ipc_listener_watchdog_release",
                    phase="final_cleanup",
                    stage="ipc_listener_watchdog_release",
                    branch=branch,
                    error=release_error,
                )
            )
        first, *remaining = failures
        raise _ExecutionFailureBundle(
            primary=first.error,
            primary_phase=first.phase,
            primary_stage=first.stage,
            primary_branch=first.branch,
            supplemental_failures=remaining,
        )


def _remove_private_runtime(
    *,
    staged_files: Sequence[Path],
    model_root: Path,
    ipc_namespace: Any,
    ipc_namespace_destroyer: Callable[[Any], None],
) -> None:
    model_errors: list[BaseException] = []
    for path in staged_files:
        try:
            _require(path.parent == model_root, "staged model cleanup target drifted")
            path.unlink()
        except BaseException as error:
            model_errors.append(error)
    try:
        _require(not any(model_root.iterdir()), "model staging directory contains unknown entries")
        model_root.rmdir()
    except BaseException as error:
        model_errors.append(error)
    ipc_error: BaseException | None = None
    try:
        ipc_namespace_destroyer(ipc_namespace)
    except BaseException as error:
        ipc_error = error
    if model_errors or ipc_error is not None:
        failures: list[_SupplementalExecutionFailure] = []
        for model_error in model_errors:
            failures.append(
                _SupplementalExecutionFailure(
                    scope="model_staging_cleanup",
                    phase="final_cleanup",
                    stage="model_staging_cleanup",
                    branch=None,
                    error=model_error,
                )
            )
        if ipc_error is not None:
            failures.append(
                _SupplementalExecutionFailure(
                    scope="ipc_namespace_cleanup",
                    phase="final_cleanup",
                    stage="ipc_namespace_cleanup",
                    branch=None,
                    error=ipc_error,
                )
            )
        first, *remaining = failures
        raise _ExecutionFailureBundle(
            primary=first.error,
            primary_phase=first.phase,
            primary_stage=first.stage,
            primary_branch=None,
            supplemental_failures=remaining,
        )


def _abort_ipc_runtime_setup(
    *,
    ipc_watchdog: _IpcRuntimeWatchdogProcess | None,
    ipc_namespace: Any,
    ipc_namespace_destroyer: Callable[[Any], None],
) -> tuple[_SupplementalExecutionFailure, ...]:
    watchdog_error: BaseException | None = None
    if ipc_watchdog is not None:
        try:
            ipc_watchdog.abort()
        except BaseException as error:
            watchdog_error = error
    destroy_error: BaseException | None = None
    try:
        ipc_namespace_destroyer(ipc_namespace)
    except BaseException as error:
        destroy_error = error
    failures: list[_SupplementalExecutionFailure] = []
    if watchdog_error is not None:
        failures.append(
            _SupplementalExecutionFailure(
                scope="ipc_watchdog_cleanup",
                phase="final_cleanup",
                stage="ipc_watchdog_cleanup",
                branch=None,
                error=watchdog_error,
            )
        )
    if destroy_error is not None:
        failures.append(
            _SupplementalExecutionFailure(
                scope="ipc_namespace_cleanup",
                phase="final_cleanup",
                stage="ipc_namespace_cleanup",
                branch=None,
                error=destroy_error,
            )
        )
    return tuple(failures)


def _run_tensor_workers(
    *,
    project_root: Path,
    run_root: Path,
    logical_run_root: str,
    run_identity: str,
    plan: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    bindings: BindingInventory,
    payloads: TensorInventory,
    binding_descriptors: Mapping[str, Mapping[str, object]],
    runtime_probe: Mapping[str, object],
    runtime_image: Mapping[str, object],
    runtime_daemon: Mapping[str, object],
    docker_cli_identity: FileIdentity,
    command_runner: CommandRunner,
    cleanup_mutex: Any,
    container_registry: _OwnedContainerRegistry,
    progress: _ExecutionProgressLedger,
    run_lease: Any | None = None,
    peer_identity_mode: str = PEER_IDENTITY_MODE_NATIVE_VISIBLE,
    peercred_platform_observation: Mapping[str, object] | None = None,
    peercred_platform_observer: (
        Callable[[Mapping[str, object]], Mapping[str, object]] | None
    ) = None,
    peercred_diagnostic_only: bool = False,
    _session_factory: Callable[..., tuple[Any, Mapping[str, object]]] | None = None,
    _transaction_runner: Callable[..., Mapping[str, Any]] | None = None,
    _stage_inventory: Callable[..., tuple[BindingInventory, tuple[Path, ...], Path]] = _stage_model_inventory,
    _watchdog_spawner: Callable[..., _ContainerWatchdog] = _spawn_container_watchdog,
    _ipc_namespace_factory: Callable[[str], Any] | None = None,
    _ipc_namespace_destroyer: Callable[[Any], None] | None = None,
    _ipc_watchdog_spawner: Callable[[str], _IpcRuntimeWatchdogProcess] = (
        _spawn_ipc_runtime_watchdog
    ),
    _peercred_diagnostic_writer: Callable[..., Path] = (
        _write_peercred_failure_diagnostic
    ),
    _executor_source_observer: Callable[[Path], FileIdentity] = (
        _observe_regular_file
    ),
) -> list[dict[str, object]]:
    _require(
        type(peercred_diagnostic_only) is bool,
        "SO_PEERCRED diagnostic-only selector drifted",
    )
    _require(
        not peercred_diagnostic_only or plan.get("role") == "secondary",
        "SO_PEERCRED diagnostic-only role drifted",
    )
    _require(
        type(peer_identity_mode) is str
        and peer_identity_mode in PEER_IDENTITY_MODES
        and (
            not peercred_diagnostic_only
            or peer_identity_mode == PEER_IDENTITY_MODE_NATIVE_VISIBLE
        ),
        "peer identity mode selector drifted",
    )
    _require(
        (
            peer_identity_mode
            == PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
        )
        is (peercred_platform_observation is not None)
        and (
            peercred_platform_observation is None
            or peercred_platform_observer is not None
        ),
        "peer identity platform selection drifted",
    )
    validated_runtime_daemon = (
        _validate_daemon_observation(runtime_daemon)
        if _session_factory is None
        else dict(_mapping(runtime_daemon, "synthetic runtime daemon"))
    )
    validated_runtime_platform = (
        _validate_peercred_pid0_platform_observation(
            peercred_platform_observation
        )
        if peercred_platform_observation is not None
        else None
    )
    _require(len(requests) == 8, "TensorRT worker request coverage drifted")
    transaction_runner = (
        _run_owned_container_transaction
        if _transaction_runner is None
        else _transaction_runner
    )
    full_probe = runtime_probe.get("validated_runtime_probe")
    _require(isinstance(full_probe, Mapping), "full TensorRT runtime probe is unavailable")
    expected_image_labels = {
        str(key): str(item)
        for key, item in _mapping(runtime_image.get("labels"), "TensorRT runtime image labels").items()
    }
    if _session_factory is None:
        _run_lease_contract_from_actor(run_lease)
        expected_socket_root = _ipc_runtime_path(run_identity)
        _require(
            expected_socket_root != run_root
            and run_root not in expected_socket_root.parents,
            "private IPC runtime overlaps the durable run namespace",
        )
        ipc_watchdog = _ipc_watchdog_spawner(
            run_identity,
            run_lease=run_lease,
        )
        _require(
            type(ipc_watchdog) is _IpcRuntimeWatchdogProcess,
            "default execution requires an exact IPC watchdog",
        )
        ipc_namespace = ipc_watchdog.namespace
        ipc_namespace_destroyer: Callable[[Any], None] = (
            _destroy_ipc_runtime_namespace
        )
    else:
        _require(
            _ipc_namespace_factory is not None
            and _ipc_namespace_destroyer is not None,
            "synthetic execution requires explicit synthetic IPC custody",
        )
        ipc_namespace = _ipc_namespace_factory(run_identity)
        ipc_watchdog = None
        ipc_namespace_destroyer = _ipc_namespace_destroyer
    try:
        socket_root = Path(ipc_namespace.path)
        _require(
            socket_root.is_absolute()
            and socket_root != run_root
            and run_root not in socket_root.parents,
            "private IPC runtime overlaps the durable run namespace",
        )
        if _session_factory is None:
            _require(
                socket_root == expected_socket_root,
                "IPC watchdog returned a different runtime namespace",
            )
            _validate_ipc_runtime_namespace(ipc_namespace)
        else:
            _require(
                type(ipc_namespace) is not _IpcRuntimeNamespace,
                "synthetic execution cannot allocate an unwatched native IPC namespace",
            )
    except BaseException as primary_error:
        cleanup_failures = _abort_ipc_runtime_setup(
            ipc_watchdog=ipc_watchdog,
            ipc_namespace=ipc_namespace,
            ipc_namespace_destroyer=ipc_namespace_destroyer,
        )
        if cleanup_failures:
            raise _bundle_execution_failure_with_supplementals(
                primary_error,
                primary_phase="worker_execution",
                primary_stage="worker_orchestration",
                primary_branch=None,
                supplemental_failures=cleanup_failures,
            ) from primary_error
        raise
    ipc_control_lock = threading.Lock()
    try:
        staged_inventory, staged_files, model_root = _stage_inventory(run_root, bindings)
    except BaseException as primary_error:
        cleanup_failures = _abort_ipc_runtime_setup(
            ipc_watchdog=ipc_watchdog,
            ipc_namespace=ipc_namespace,
            ipc_namespace_destroyer=ipc_namespace_destroyer,
        )
        if cleanup_failures:
            raise _bundle_execution_failure_with_supplementals(
                primary_error,
                primary_phase="worker_execution",
                primary_stage="worker_orchestration",
                primary_branch=None,
                supplemental_failures=cleanup_failures,
            ) from primary_error
        raise

    def watchdog_factory(**kwargs: Any) -> _ContainerWatchdog:
        return _watchdog_spawner(
            **kwargs,
            docker_cli_identity=docker_cli_identity,
            daemon=runtime_daemon,
            cleanup_mutex=cleanup_mutex,
            run_lease=run_lease,
        )

    def validate_all_handshakes_before_inference() -> None:
        if _session_factory is None:
            observed_daemon = _validate_daemon(
                command_runner,
                expected_id=str(validated_runtime_daemon["daemon_id"]),
                expected_server_version=str(
                    validated_runtime_daemon["server_version"]
                ),
                expected_api_version=str(validated_runtime_daemon["api_version"]),
            )
            _require(
                observed_daemon == validated_runtime_daemon,
                "Docker daemon changed at the four-worker handshake barrier",
            )
            if validated_runtime_platform is not None:
                _require(
                    peercred_platform_observer is not None
                    and dict(peercred_platform_observer(observed_daemon))
                    == validated_runtime_platform,
                    "WSL2 peer platform changed at the four-worker handshake barrier",
                )
        progress.record_barrier_released()

    handshake_barrier = threading.Barrier(
        len(BRANCHES),
        action=validate_all_handshakes_before_inference,
    )

    def run_branch(branch: str) -> list[dict[str, object]]:
        binding = _mapping(staged_inventory.bindings[branch], f"{branch} TensorRT binding")
        branch_requests = [
            request for request in requests if request.get("branch") == branch
        ]
        _require(
            [request.get("codec") for request in branch_requests] == list(CODECS),
            f"{branch} request codec order drifted",
        )
        binding_record = _mapping(binding_descriptors.get(branch), f"{branch} binding descriptor")
        binding_source = run_root / str(binding_record.get("path"))
        _require(binding_source.parent == run_root / "bindings", f"{branch} binding host path drifted")
        source_model = staged_inventory.source_paths[branch]
        engine = staged_inventory.engine_paths[branch]
        _require(
            binding.get("source_path") == f"/run/vast/models/{source_model.name}"
            and binding.get("engine_path") == f"/run/vast/models/{engine.name}",
            f"{branch} staged binding path drifted",
        )
        socket_name = f"{branch}.sock"
        name = f"vast-kpp-v2-np-{run_identity[:16]}-{branch}"
        labels = {
            OWNER_LABEL: OWNER_VALUE,
            RUN_LABEL: run_identity,
            BRANCH_LABEL: branch,
        }
        expected_mounts = {
            f"/run/vast/bindings/{binding_source.name}": binding_source,
            str(binding["source_path"]): source_model,
            str(binding["engine_path"]): engine,
            "/run/vast/analytics": socket_root,
        }
        listener: socket.socket | None = None
        ipc_registered = False
        transaction_primary: BaseException | None = None
        try:
            if _session_factory is None:
                try:
                    from analytics_execution_endpoint import (
                        expected_capability_from_binding_and_probe,
                    )
                    from analytics_execution_worker import ExecutionClient
                except (ImportError, OSError) as error:
                    raise ExecutorContractError(
                        "analytics ExecutionClient APIs are unavailable"
                    ) from error
                capability = expected_capability_from_binding_and_probe(
                    binding=binding,
                    runtime_probe=full_probe,
                    resource="gpu",
                )
                listener = _open_ipc_listener(ipc_namespace, branch)
                _require(ipc_watchdog is not None, "IPC watchdog is unavailable")
                with ipc_control_lock:
                    ipc_watchdog.register(branch)
                ipc_registered = True
                _validate_ipc_runtime_namespace(ipc_namespace)
            else:
                synthetic_client, synthetic_capability = _session_factory(
                    branch=branch,
                    binding=binding,
                    runtime_probe=full_probe,
                )
                capability = dict(synthetic_capability)

            def after_start(container_id: str) -> list[dict[str, object]]:
                if _session_factory is not None:
                    _require(
                        not peercred_diagnostic_only,
                        "SO_PEERCRED diagnostic-only mode forbids synthetic sessions",
                    )
                    _require(
                        peer_identity_mode == PEER_IDENTITY_MODE_NATIVE_VISIBLE
                        and peercred_platform_observation is None,
                        "synthetic execution cannot select namespace-hidden peer mode",
                    )
                    return _execute_requests_with_client(
                        client=synthetic_client,
                        capability=capability,
                        branch=branch,
                        run_id=run_identity,
                        binding=binding,
                        requests=branch_requests,
                        payloads=payloads,
                        handshake_barrier=handshake_barrier,
                        progress=progress,
                    )
                _require(listener is not None, "TensorRT listener is unavailable")
                connection, _address = listener.accept()
                try:
                    connection.settimeout(180.0)
                    peer = connection.getsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_PEERCRED,
                        struct.calcsize("3i"),
                    )
                    peer_pid, peer_uid, peer_gid = struct.unpack("3i", peer)
                    peer_credentials_exact = _peer_credentials_are_exact(
                        peer_pid,
                        peer_uid,
                        peer_gid,
                    )
                    running_capture = _container_inspect_capture(
                        command_runner,
                        container_id,
                    )
                    _require(
                        running_capture.returncode == 0,
                        f"{branch} running container cannot be inspected",
                    )
                    running_document = _parse_json(
                        running_capture.stdout,
                        f"{branch} running container inspect",
                    )
                    running_state = _mapping(
                        running_document.get("State"),
                        f"{branch} running state",
                    )
                    running_status = running_state.get("Status")
                    _require(
                        type(running_status) is str
                        and running_status in _RUNNING_CONTAINER_STATES,
                        f"{branch} container is not running",
                    )
                    running_facts = _validate_container_inspect(
                        running_document,
                        container_id=container_id,
                        container_name=name,
                        labels=labels,
                        expected_mounts=expected_mounts,
                        expected_state=running_status,
                        expected_image_labels=expected_image_labels,
                    )
                    running_config = _mapping(
                        running_document.get("Config"),
                        f"{branch} running container config",
                    )

                    def write_peercred_diagnostic() -> None:
                        _peercred_diagnostic_writer(
                            project_root=project_root,
                            run_root=run_root,
                            logical_run_root=logical_run_root,
                            run_identity=run_identity,
                            plan=plan,
                            bindings=bindings,
                            branch=branch,
                            container_id=container_id,
                            container_name=name,
                            peer_pid=peer_pid,
                            peer_uid=peer_uid,
                            peer_gid=peer_gid,
                            peer_raw=peer,
                            docker_state_pid=running_facts.get("state_pid"),
                            container_user=running_config.get("User"),
                            executor_source_path=(
                                "scripts/"
                                "kpp_legacy_iss_v2_secondary_sensitivity_executor.py"
                            ),
                            executor_source_identity=_executor_source_observer(
                                Path(__file__).resolve()
                            ),
                            diagnostic_only=peercred_diagnostic_only,
                        )
                    if peercred_diagnostic_only:
                        write_peercred_diagnostic()
                    _require(
                        not peercred_diagnostic_only,
                        f"{branch} SO_PEERCRED diagnostic-only stop before capability handshake",
                    )
                    runtime_custody = {
                        "native_ipc_namespace_attested": True,
                        "readonly_mounts_attested": running_facts.get(
                            "native_readonly_mounts_attested"
                        ),
                        "container_image_entrypoint_identity_attested": (
                            running_facts.get(
                                "container_image_entrypoint_identity_attested"
                            )
                        ),
                        "docker_desktop_wsl_distro_label_attested": (
                            running_facts.get(
                                "docker_desktop_wsl_distro_label_attested"
                            )
                        ),
                        "container_runtime": running_facts.get(
                            "container_runtime"
                        ),
                    }
                    try:
                        peer_identity = _select_peer_identity(
                            selected_mode=peer_identity_mode,
                            peer_raw=peer,
                            docker_state_pid=running_facts.get("state_pid"),
                            runtime_daemon=validated_runtime_daemon,
                            runtime_platform=validated_runtime_platform,
                            runtime_custody=runtime_custody,
                        )
                    except ExecutorContractError:
                        if not peer_credentials_exact:
                            write_peercred_diagnostic()
                        raise
                    client = ExecutionClient(connection, expected_capability=capability)
                    return _execute_requests_with_client(
                        client=client,
                        capability=capability,
                        branch=branch,
                        run_id=run_identity,
                        binding=binding,
                        requests=branch_requests,
                        payloads=payloads,
                        peer_identity=peer_identity,
                        handshake_barrier=handshake_barrier,
                        progress=progress,
                    )
                finally:
                    active_error = sys.exception()
                    try:
                        connection.close()
                    except BaseException as close_error:
                        raise _DescriptorClosureError(
                            operation="worker_execution_connection",
                            primary=active_error,
                            close_failures=[close_error],
                            message="worker execution connection cleanup failed",
                        ) from (
                            active_error
                            if active_error is not None
                            else close_error
                        )

            transaction = transaction_runner(
                runner=command_runner,
                create_command=_build_worker_create_command(
                    container_name=name,
                    labels=labels,
                    binding_source=binding_source,
                    source_model=source_model,
                    engine=engine,
                    socket_root=socket_root,
                    socket_name=socket_name,
                ),
                container_name=name,
                labels=labels,
                expected_mounts=expected_mounts,
                after_start=after_start,
                cleanup_mutex=cleanup_mutex,
                container_registry=container_registry,
                watchdog_factory=watchdog_factory,
                expected_image_labels=expected_image_labels,
            )
        except BaseException as error:
            transaction_primary = error
            raise
        finally:
            if listener is not None:
                listener_error: BaseException | None = None
                try:
                    _require(
                        ipc_watchdog is not None,
                        "IPC watchdog is unavailable",
                    )
                    _close_watched_ipc_listener(
                        listener=listener,
                        ipc_watchdog=ipc_watchdog,
                        ipc_control_lock=ipc_control_lock,
                        branch=branch,
                        registered=ipc_registered,
                    )
                except BaseException as error:
                    listener_error = error
                if listener_error is not None:
                    if isinstance(listener_error, _ExecutionFailureBundle):
                        listener_failures = [
                            _SupplementalExecutionFailure(
                                scope="ipc_listener_cleanup",
                                phase=listener_error.primary_phase,
                                stage=listener_error.primary_stage,
                                branch=listener_error.primary_branch or branch,
                                error=listener_error.primary,
                            ),
                            *listener_error.supplemental_failures,
                        ]
                    else:
                        listener_failures = [
                            _SupplementalExecutionFailure(
                                scope="ipc_listener_cleanup",
                                phase="final_cleanup",
                                stage="ipc_listener_cleanup",
                                branch=branch,
                                error=listener_error,
                            )
                        ]
                    if isinstance(transaction_primary, _ExecutionFailureBundle):
                        raise _ExecutionFailureBundle(
                            primary=transaction_primary.primary,
                            primary_phase=transaction_primary.primary_phase,
                            primary_stage=transaction_primary.primary_stage,
                            primary_branch=transaction_primary.primary_branch,
                            supplemental_failures=[
                                *transaction_primary.supplemental_failures,
                                *listener_failures,
                            ],
                        )
                    if transaction_primary is not None:
                        raise _ExecutionFailureBundle(
                            primary=transaction_primary,
                            primary_phase="worker_execution",
                            primary_stage="worker_orchestration",
                            primary_branch=branch,
                            supplemental_failures=listener_failures,
                        )
                    first, *remaining = listener_failures
                    raise _ExecutionFailureBundle(
                        primary=first.error,
                        primary_phase=first.phase,
                        primary_stage=first.stage,
                        primary_branch=first.branch,
                        supplemental_failures=remaining,
                    )
        raw = transaction.get("action")
        _require(type(raw) is list and len(raw) == 2, f"{branch} TensorRT action coverage drifted")
        lifecycle = {
            "container_id_sha256": hashlib.sha256(
                str(transaction["container_id"]).encode("ascii")
            ).hexdigest(),
            "container_preinspect_sha256": transaction["preinspect_sha256"],
            "container_running_inspect_sha256": transaction[
                "running_inspect_sha256"
            ],
            "container_postinspect_sha256": transaction["postinspect_sha256"],
            "container_stdout_sha256": hashlib.sha256(transaction["stdout"]).hexdigest(),
            "container_stdout_size_bytes": len(transaction["stdout"]),
            "container_stderr_sha256": hashlib.sha256(transaction["stderr"]).hexdigest(),
            "container_stderr_size_bytes": len(transaction["stderr"]),
        }
        return [{**dict(item), **lifecycle} for item in raw]

    observations: list[dict[str, object]] = []
    body_succeeded = False
    primary: BaseException | None = None
    try:
        # Pre-allocate terminal custody before any worker can start.  The
        # submitted callable itself signals only after ``run_branch`` has
        # completed (including all of its cleanup).  Consequently no
        # fallible Future/dict/callback registration after ``submit`` can
        # leave a live worker outside the terminal-drain gate below.
        submitted_terminal_events = tuple(threading.Event() for _ in BRANCHES)
        submitted_future_slots: list[Any | None] = [None] * len(BRANCHES)
        submitted_count = 0

        def run_branch_with_terminal_custody(
            branch: str,
            terminal_event: threading.Event,
        ) -> list[dict[str, object]]:
            branch_error: BaseException | None = None
            try:
                return run_branch(branch)
            except BaseException as error:
                branch_error = error
                raise
            finally:
                try:
                    terminal_event.set()
                except BaseException as signal_error:
                    if branch_error is not None:
                        raise _DescriptorClosureError(
                            operation="worker_callable_terminal_signal",
                            primary=branch_error,
                            close_failures=[signal_error],
                        ) from branch_error
                    raise

        def wait_callable_terminal(
            terminal_event: threading.Event,
            errors: list[BaseException],
        ) -> None:
            while True:
                try:
                    if terminal_event.wait() is True:
                        return
                    errors.append(
                        ExecutorContractError(
                            "worker callable terminal wait returned false"
                        )
                    )
                except BaseException as wait_error:
                    errors.append(wait_error)

        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="kpp-v2-trt")
        pool_error: BaseException | None = None
        terminal_gate_errors: list[BaseException] = []
        try:
            futures: dict[Any, str] = {}
            future_terminal_events: dict[Any, threading.Event] = {}
            submission_error: BaseException | None = None
            for index, branch in enumerate(BRANCHES):
                try:
                    terminal_event = submitted_terminal_events[index]
                    # Mark this slot ambiguous *before* entering submit().
                    # An asynchronous BaseException can arrive after the
                    # executor accepted the callable but before Python stores
                    # its returned Future.  In that case a failed shutdown
                    # must wait this pre-registered terminal signal rather
                    # than tear IPC/model custody down under a live worker.
                    submitted_count = index + 1
                    future = pool.submit(
                        run_branch_with_terminal_custody,
                        branch,
                        terminal_event,
                    )
                    # These two assignments are to pre-existing local slots;
                    # ownership is registered before any dict allocation or
                    # other fallible bookkeeping below.
                    submitted_future_slots[index] = future
                    futures[future] = branch
                    future_terminal_events[future] = terminal_event
                except BaseException as error:
                    submission_error = error
                    break
            branch_failures: dict[str, BaseException] = {}
            barrier_abort_error: BaseException | None = None
            barrier_abort_attempted = False
            collection_error: BaseException | None = None
            terminal_drain_errors: list[BaseException] = []
            harvested_futures: set[Any] = set()
            terminal_futures: set[Any] = set()

            def abort_barrier_once() -> None:
                nonlocal barrier_abort_attempted, barrier_abort_error
                if barrier_abort_attempted:
                    return
                barrier_abort_attempted = True
                try:
                    handshake_barrier.abort()
                except BaseException as error:
                    barrier_abort_error = error

            def harvest_terminal_future(future: Any) -> None:
                branch = futures[future]
                _require(
                    isinstance(future, Future),
                    "worker pool returned a non-Future handle",
                )
                if future in harvested_futures:
                    return
                result_error: BaseException | None = None
                result_value: object | None = None
                try:
                    result_value = future.result()
                except BaseException as error:
                    result_error = error
                terminal_event = future_terminal_events[future]
                # Do not trust an interrupted result()/shutdown edge as a
                # join.  The pre-registered callable-finally signal proves
                # that branch mutation and cleanup have ended.  The outer
                # one-shot launcher supplies the hard wall-clock bound while
                # this wait preserves runtime custody.
                wait_callable_terminal(terminal_event, terminal_drain_errors)
                try:
                    terminal = future.done() is True
                except BaseException as state_error:
                    terminal_drain_errors.append(state_error)
                    terminal = False
                if terminal:
                    terminal_futures.add(future)
                    try:
                        # Re-read after callable-finally custody.  If the first
                        # result() was asynchronously interrupted, this yields
                        # the actual branch result/failure exactly once here.
                        result_value = future.result()
                        observations.extend(result_value)
                    except BaseException as terminal_error:
                        branch_failures[branch] = terminal_error
                    if (
                        result_error is not None
                        and result_error is not branch_failures.get(branch)
                    ):
                        terminal_drain_errors.append(result_error)
                else:
                    terminal_drain_errors.append(
                        _DescriptorClosureError(
                            operation="worker_future_terminal_wait",
                            primary=(
                                result_error
                                if result_error is not None
                                else ExecutorContractError(
                                    "worker Future result returned before terminal state"
                                )
                            ),
                            close_failures=[],
                            message="worker Future terminal state is unavailable",
                        )
                    )
                harvested_futures.add(future)

            if submission_error is not None:
                abort_barrier_once()
            try:
                for future in as_completed(futures):
                    harvest_terminal_future(future)
                    if futures[future] in branch_failures:
                        abort_barrier_once()
            except BaseException as error:
                collection_error = error
                abort_barrier_once()
            # `as_completed()` and ThreadPoolExecutor shutdown are themselves
            # fallible.  Independently wait every submitted Future to a
            # terminal state before IPC/model teardown can begin.  The outer
            # one-shot launcher remains the hard wall-clock bound.
            for branch in BRANCHES:
                for future, future_branch in futures.items():
                    if future_branch == branch and future not in harvested_futures:
                        harvest_terminal_future(future)
            if terminal_futures != set(futures):
                terminal_drain_errors.append(
                    _DescriptorClosureError(
                        operation="worker_future_terminal_attestation",
                        primary=ExecutorContractError(
                            "worker Future was not terminal before runtime cleanup"
                        ),
                        close_failures=[],
                    )
                )
            if (
                submission_error is not None
                or collection_error is not None
                or branch_failures
                or terminal_drain_errors
            ):
                ordered = [
                    (branch, branch_failures[branch])
                    for branch in BRANCHES
                    if branch in branch_failures
                ]
                if submission_error is not None:
                    primary_branch = None
                    selected = submission_error
                    remaining_failures = ordered
                elif collection_error is not None:
                    primary_branch = None
                    selected = collection_error
                    remaining_failures = ordered
                elif ordered:
                    primary_branch, selected = ordered[0]
                    remaining_failures = ordered[1:]
                else:
                    primary_branch = None
                    selected = terminal_drain_errors[0]
                    remaining_failures = []
                if isinstance(selected, _ExecutionFailureBundle):
                    selected_primary = selected.primary
                    selected_phase = selected.primary_phase
                    selected_stage = selected.primary_stage
                    selected_branch = selected.primary_branch or primary_branch
                    supplemental: list[_SupplementalExecutionFailure] = list(
                        selected.supplemental_failures
                    )
                else:
                    selected_primary = selected
                    selected_phase = "worker_execution"
                    selected_stage = "worker_orchestration"
                    selected_branch = primary_branch
                    supplemental = []
                for branch, failure in remaining_failures:
                    if isinstance(failure, _ExecutionFailureBundle):
                        supplemental.append(
                            _SupplementalExecutionFailure(
                                scope="concurrent_worker_branch_failure",
                                phase=failure.primary_phase,
                                stage=failure.primary_stage,
                                branch=failure.primary_branch or branch,
                                error=failure.primary,
                            )
                        )
                        supplemental.extend(failure.supplemental_failures)
                    else:
                        supplemental.append(
                            _SupplementalExecutionFailure(
                                scope="concurrent_worker_branch_failure",
                                phase="worker_execution",
                                stage="worker_orchestration",
                                branch=branch,
                                error=failure,
                            )
                        )
                if submission_error is not None and collection_error is not None:
                    supplemental.append(
                        _SupplementalExecutionFailure(
                            scope="worker_future_collection",
                            phase="worker_execution",
                            stage="worker_orchestration",
                            branch=None,
                            error=collection_error,
                        )
                    )
                terminal_error_start = (
                    1
                    if terminal_drain_errors
                    and selected is terminal_drain_errors[0]
                    else 0
                )
                for error in terminal_drain_errors[terminal_error_start:]:
                    supplemental.append(
                        _SupplementalExecutionFailure(
                            scope="worker_future_terminal_drain",
                            phase="final_cleanup",
                            stage="worker_orchestration",
                            branch=None,
                            error=error,
                        )
                    )
                if barrier_abort_error is not None:
                    supplemental.append(
                        _SupplementalExecutionFailure(
                            scope="handshake_barrier_abort",
                            phase="worker_execution",
                            stage="worker_orchestration",
                            branch=None,
                            error=barrier_abort_error,
                        )
                    )
                raise _ExecutionFailureBundle(
                    primary=selected_primary,
                    primary_phase=selected_phase,
                    primary_stage=selected_stage,
                    primary_branch=selected_branch,
                    supplemental_failures=supplemental,
                )
        except BaseException as error:
            pool_error = error
        finally:
            # This gate is independent of the Future mapping and collection
            # machinery.  Even if bookkeeping, ``as_completed`` or result
            # projection raises, every callable whose ``submit`` returned is
            # known to have left ``run_branch`` before IPC/model teardown.
            for index in range(submitted_count):
                if submitted_future_slots[index] is None:
                    # Ambiguous submit ownership is resolved by the one-shot
                    # shutdown attempt below.  If that attempt does not
                    # return, its separate finally gate waits this event.
                    continue
                terminal_event = submitted_terminal_events[index]
                wait_callable_terminal(terminal_event, terminal_gate_errors)
        shutdown_error: BaseException | None = None
        shutdown_returned = False
        try:
            pool.shutdown(wait=True)
            shutdown_returned = True
        except BaseException as error:
            shutdown_error = error
        finally:
            if not shutdown_returned:
                # A missing Future slot can mean submit() itself failed before
                # enqueue, or that an asynchronous exception interrupted the
                # return-value store after enqueue.  Only a successful
                # shutdown distinguishes those worlds.  On shutdown failure
                # wait the callable-owned signal; the outer launcher is the
                # hard bound for the genuinely never-enqueued case.
                for index in range(submitted_count):
                    if submitted_future_slots[index] is not None:
                        continue
                    terminal_event = submitted_terminal_events[index]
                    wait_callable_terminal(terminal_event, terminal_gate_errors)
        if terminal_gate_errors:
            if pool_error is None:
                pool_error = _ExecutionFailureBundle(
                    primary=terminal_gate_errors[0],
                    primary_phase="final_cleanup",
                    primary_stage="worker_future_terminal_drain",
                    primary_branch=None,
                    supplemental_failures=[
                        _SupplementalExecutionFailure(
                            scope="worker_future_terminal_drain",
                            phase="final_cleanup",
                            stage="worker_future_terminal_drain",
                            branch=None,
                            error=error,
                        )
                        for error in terminal_gate_errors[1:]
                    ],
                )
            else:
                pool_error = _bundle_execution_failure_with_supplementals(
                    pool_error,
                    primary_phase="worker_execution",
                    primary_stage="worker_orchestration",
                    primary_branch=None,
                    supplemental_failures=[
                        _SupplementalExecutionFailure(
                            scope="worker_future_terminal_drain",
                            phase="final_cleanup",
                            stage="worker_future_terminal_drain",
                            branch=None,
                            error=error,
                        )
                        for error in terminal_gate_errors
                    ],
                )
        if shutdown_error is not None:
            if pool_error is None:
                merged: BaseException = _ExecutionFailureBundle(
                    primary=shutdown_error,
                    primary_phase="final_cleanup",
                    primary_stage="worker_pool_shutdown",
                    primary_branch=None,
                    supplemental_failures=[],
                )
            else:
                merged = _bundle_execution_failure_with_supplementals(
                    pool_error,
                    primary_phase="worker_execution",
                    primary_stage="worker_orchestration",
                    primary_branch=None,
                    supplemental_failures=[
                        _SupplementalExecutionFailure(
                            scope="worker_pool_shutdown",
                            phase="final_cleanup",
                            stage="worker_pool_shutdown",
                            branch=None,
                            error=shutdown_error,
                        )
                    ],
                )
            raise merged
        if pool_error is not None:
            raise pool_error
        body_succeeded = True
        return observations
    except BaseException as error:
        primary = error
        raise
    finally:
        ipc_watchdog_error: BaseException | None = None
        if ipc_watchdog is not None:
            try:
                if body_succeeded:
                    ipc_watchdog.complete()
                else:
                    ipc_watchdog.abort()
            except BaseException as error:
                ipc_watchdog_error = error
        runtime_cleanup_error: BaseException | None = None
        try:
            _remove_private_runtime(
                staged_files=staged_files,
                model_root=model_root,
                ipc_namespace=ipc_namespace,
                ipc_namespace_destroyer=ipc_namespace_destroyer,
            )
        except BaseException as error:
            runtime_cleanup_error = error
        if ipc_watchdog_error is not None or runtime_cleanup_error is not None:
            cleanup_items: list[_SupplementalExecutionFailure] = []
            if ipc_watchdog_error is not None:
                cleanup_items.append(
                    _SupplementalExecutionFailure(
                        scope="ipc_watchdog_cleanup",
                        phase="final_cleanup",
                        stage="ipc_watchdog_cleanup",
                        branch=None,
                        error=ipc_watchdog_error,
                    )
                )
            if runtime_cleanup_error is not None:
                if isinstance(runtime_cleanup_error, _ExecutionFailureBundle):
                    cleanup_items.append(
                        _SupplementalExecutionFailure(
                            scope="runtime_namespace_cleanup",
                            phase=runtime_cleanup_error.primary_phase,
                            stage=runtime_cleanup_error.primary_stage,
                            branch=runtime_cleanup_error.primary_branch,
                            error=runtime_cleanup_error.primary,
                        )
                    )
                    cleanup_items.extend(
                        runtime_cleanup_error.supplemental_failures
                    )
                else:
                    cleanup_items.append(
                        _SupplementalExecutionFailure(
                            scope="runtime_namespace_cleanup",
                            phase="final_cleanup",
                            stage="runtime_namespace_cleanup",
                            branch=None,
                            error=runtime_cleanup_error,
                        )
                    )
            if isinstance(primary, _ExecutionFailureBundle):
                raise _ExecutionFailureBundle(
                    primary=primary.primary,
                    primary_phase=primary.primary_phase,
                    primary_stage=primary.primary_stage,
                    primary_branch=primary.primary_branch,
                    supplemental_failures=[
                        *primary.supplemental_failures,
                        *cleanup_items,
                    ],
                )
            if primary is not None:
                raise _ExecutionFailureBundle(
                    primary=primary,
                    primary_phase="worker_execution",
                    primary_stage="worker_orchestration",
                    primary_branch=None,
                    supplemental_failures=cleanup_items,
                )
            first, *remaining = cleanup_items
            raise _ExecutionFailureBundle(
                primary=first.error,
                primary_phase="final_cleanup",
                primary_stage=first.stage,
                primary_branch=None,
                supplemental_failures=remaining,
            )


def _validate_tensor_inventory(
    inventory: TensorInventory,
    requests: Sequence[Mapping[str, object]],
) -> None:
    expected_ids = {str(request["request_id"]) for request in requests}
    _require(set(inventory.payloads) == expected_ids, "selected tensor payload coverage drifted")
    expected_bundles: dict[str, dict[str, object]] = {}
    for request in requests:
        request_id = str(request["request_id"])
        payload = inventory.payloads[request_id]
        tensor = _mapping(request["tensor"], f"{request_id} tensor")
        path = tensor.get("path")
        size_bytes = tensor.get("size_bytes")
        offset_bytes = tensor.get("offset_bytes")
        _require(type(path) is str and bool(path), f"{request_id} tensor path drifted")
        _require(type(size_bytes) is int and size_bytes > 0, f"{request_id} tensor bundle size drifted")
        _require(
            type(offset_bytes) is int
            and offset_bytes >= 0
            and offset_bytes % TENSOR_SEGMENT_BYTES == 0
            and offset_bytes + TENSOR_SEGMENT_BYTES <= size_bytes,
            f"{request_id} tensor segment bounds drifted",
        )
        whole_sha = _sha(tensor.get("sha256"), f"{request_id} tensor bundle SHA-256")
        descriptor = {
            "path": path,
            "size_bytes": size_bytes,
            "sha256": whole_sha,
        }
        prior = expected_bundles.setdefault(path, descriptor)
        _require(prior == descriptor, f"{request_id} tensor bundle descriptor drifted")
        _require(type(payload) is bytes and len(payload) == TENSOR_SEGMENT_BYTES, f"{request_id} tensor payload size drifted")
        _require(hashlib.sha256(payload).hexdigest() == tensor["segment_sha256"], f"{request_id} tensor payload SHA-256 drifted")
    observed_bundles: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(inventory.bundle_observations):
        value = dict(_mapping(raw, f"tensor bundle observation {index}"))
        _require(
            set(value) == {"path", "size_bytes", "sha256"},
            "tensor bundle observation fields drifted",
        )
        path = value.get("path")
        _require(type(path) is str and path not in observed_bundles, "tensor bundle observation path drifted")
        _require(type(value.get("size_bytes")) is int, "tensor bundle observation size drifted")
        _sha(value.get("sha256"), "tensor bundle observation SHA-256")
        observed_bundles[path] = value
    _require(observed_bundles == expected_bundles, "tensor whole-file identity coverage drifted")


def _write_new(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, mode)
    primary: BaseException | None = None
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(written > 0, f"cannot write new executor artifact: {path.name}")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException as error:
        primary = error
    close_errors: list[BaseException] = []
    try:
        os.close(descriptor)
    except BaseException as error:
        close_errors.append(error)
    if close_errors:
        raise _DescriptorClosureError(
            operation="write_new_artifact",
            primary=primary,
            close_failures=close_errors,
        ) from (primary if primary is not None else close_errors[0])
    if primary is not None:
        raise primary


def _persist_held_runroot_leaf(
    run_root_custody: _RunRootCustody,
    *,
    name: str,
    payload: bytes,
    requested_mode: int,
) -> dict[str, object]:
    """Create one run-root leaf relative to the held created directory."""

    _require(
        os.name == "posix"
        and sys.platform.startswith("linux")
        and type(run_root_custody) is _RunRootCustody
        and name
        in {ASSESSMENT_NAME, EXECUTION_FAILURE_DIAGNOSTIC_NAME}
        and requested_mode in {0o400, 0o600}
        and type(payload) is bytes,
        "held run-root artifact inputs drifted",
    )
    run_root_custody.validate()
    run_root = run_root_custody.path
    _require(
        len(payload) <= 16 * 1024 * 1024,
        "execution failure diagnostic payload overflowed",
    )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    _require(
        nofollow != 0 and cloexec != 0,
        "execution failure diagnostic no-follow custody is unavailable",
    )
    root_fd = run_root_custody.descriptor
    descriptor: int | None = None
    try:
        filesystem_magic = run_root_custody.filesystem_magic
        if filesystem_magic == _LINUX_EXT_FILESYSTEM_MAGIC:
            expected_file_mode = requested_mode
        elif filesystem_magic == _LINUX_V9FS_MAGIC:
            expected_file_mode = 0o555 if requested_mode == 0o400 else 0o777
        else:
            raise ExecutorContractError(
                "execution failure diagnostic filesystem type drifted"
            )
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow | cloexec
        descriptor = os.open(
            name,
            flags,
            requested_mode,
            dir_fd=root_fd,
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _require(
                type(written) is int and written > 0,
                "execution failure diagnostic write stalled",
            )
            view = view[written:]
        os.fchmod(descriptor, requested_mode)
        os.fsync(descriptor)
        state = os.fstat(descriptor)
        named = os.stat(
            name,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        identity = (
            int(state.st_dev),
            int(state.st_ino),
            int(state.st_mode),
            int(state.st_uid),
            int(state.st_gid),
            int(state.st_nlink),
            int(state.st_size),
        )
        _require(
            identity
            == (
                int(named.st_dev),
                int(named.st_ino),
                int(named.st_mode),
                int(named.st_uid),
                int(named.st_gid),
                int(named.st_nlink),
                int(named.st_size),
            )
            and stat.S_ISREG(state.st_mode)
            and stat.S_IMODE(state.st_mode) == expected_file_mode
            and (
                requested_mode != 0o400
                or stat.S_IMODE(state.st_mode) & 0o222 == 0
            )
            and state.st_uid == os.getuid()
            and state.st_gid == os.getgid()
            and state.st_nlink == 1
            and state.st_size == len(payload),
            "execution failure diagnostic leaf custody drifted",
        )
        os.lseek(descriptor, 0, os.SEEK_SET)
        readback = bytearray()
        while len(readback) <= len(payload):
            chunk = os.read(
                descriptor,
                min(1024 * 1024, len(payload) + 1 - len(readback)),
            )
            if not chunk:
                break
            readback.extend(chunk)
        _require(
            bytes(readback) == payload,
            "execution failure diagnostic durable readback drifted",
        )
        run_root_custody.validate()
        os.fsync(root_fd)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        run_root_custody.register_leaf(
            name=name,
            descriptor=descriptor,
            identity=identity,
            expected_mode=expected_file_mode,
            size_bytes=len(payload),
            sha256=payload_sha256,
        )
        descriptor = None
        return {
            "path": str(run_root / name),
            "size_bytes": len(payload),
            "sha256": payload_sha256,
            "filesystem_magic": filesystem_magic,
            "requested_mode": f"{requested_mode:04o}",
            "effective_mode": f"{expected_file_mode:04o}",
            "identity": identity,
        }
    except FileExistsError as error:
        raise ExecutorContractError(
            "execution failure diagnostic already exists"
        ) from error
    except ExecutorContractError:
        raise
    except OSError as error:
        raise ExecutorContractError(
            "cannot persist execution failure diagnostic"
        ) from error
    finally:
        active_error = sys.exception()
        close_errors: list[BaseException] = []
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as error:
                close_errors.append(error)
        if close_errors:
            raise _RunRootArtifactPersistenceError(
                primary=active_error,
                close_failures=close_errors,
            ) from (active_error if active_error is not None else close_errors[0])


def _persist_execution_failure_diagnostic(
    run_root_custody: _RunRootCustody,
    artifact: Mapping[str, object],
) -> dict[str, object]:
    """Persist one failure leaf without claiming that it commits itself."""

    return _persist_held_runroot_leaf(
        run_root_custody,
        name=EXECUTION_FAILURE_DIAGNOSTIC_NAME,
        payload=canonical_line(dict(artifact)),
        requested_mode=0o400,
    )


def _create_run_namespace(
    project_root: Path | str,
    run_id: str,
) -> tuple[Path, str, _RunRootCustody | None]:
    _require(_RUN_ID_RE.fullmatch(run_id) is not None, "nonpublication run_id is invalid")
    root = Path(project_root).resolve()
    _require(root.is_dir() and not root.is_symlink(), "project root is unsafe")
    runs = root / "runs"
    nonpublication = runs / "nonpublication"
    runs.mkdir(mode=0o700, exist_ok=True)
    _require(runs.is_dir() and not runs.is_symlink(), "runs root is unsafe")
    nonpublication.mkdir(mode=0o700, exist_ok=True)
    _require(nonpublication.is_dir() and not nonpublication.is_symlink(), "nonpublication root is unsafe")
    target = nonpublication / run_id
    if os.name == "posix" and sys.platform.startswith("linux"):
        custody: _RunRootCustody | None = _RunRootCustody.create(
            nonpublication,
            run_id,
        )
    else:
        os.mkdir(target, 0o700)
        custody = None
    return target, f"runs/nonpublication/{run_id}", custody


def _materialize_bindings(run_root: Path, inventory: BindingInventory) -> dict[str, dict[str, object]]:
    root = run_root / "bindings"
    os.mkdir(root, 0o700)
    result: dict[str, dict[str, object]] = {}
    for branch in BRANCHES:
        payload = canonical_line(dict(inventory.bindings[branch]))
        path = root / f"{branch}.tensorrt_cuda.json"
        _write_new(path, payload, mode=0o400)
        result[branch] = {
            "path": f"bindings/{path.name}",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return result


def _validate_worker_observations(
    values: Sequence[Mapping[str, object]],
    requests: Sequence[Mapping[str, object]],
    *,
    require_peer_identity: bool = True,
) -> list[dict[str, object]]:
    _require(
        type(require_peer_identity) is bool
        and type(values) is list
        and len(values) == 8,
        "worker observation coverage drifted",
    )
    by_id = {str(item["request_id"]): item for item in requests}
    checked: list[dict[str, object]] = []
    for index, raw in enumerate(values):
        value = dict(_mapping(raw, f"worker observation {index}"))
        expected_fields = {
                "request_id",
                "branch",
                "codec",
                "response_sha256",
                "output_sha256",
                "output_size_bytes",
                "worker_capability_sha256",
                "terminal_status",
                "container_id_sha256",
                "container_preinspect_sha256",
                "container_running_inspect_sha256",
                "container_postinspect_sha256",
                "container_stdout_sha256",
                "container_stdout_size_bytes",
                "container_stderr_sha256",
                "container_stderr_size_bytes",
            }
        if require_peer_identity:
            expected_fields.add("peer_identity")
        _require(
            set(value) == expected_fields,
            "worker observation fields drifted",
        )
        request_id = str(value["request_id"])
        request = by_id.get(request_id)
        _require(request is not None, "worker observation request is unknown")
        _require(value["branch"] == request["branch"] and value["codec"] == request["codec"], "worker observation coordinate drifted")
        _require(value["terminal_status"] == "completed", "worker observation is not completed")
        _require(type(value["output_size_bytes"]) is int and value["output_size_bytes"] > 0, "worker output byte count drifted")
        for field in (
            "response_sha256",
            "output_sha256",
            "worker_capability_sha256",
            "container_id_sha256",
            "container_preinspect_sha256",
            "container_running_inspect_sha256",
            "container_postinspect_sha256",
            "container_stdout_sha256",
            "container_stderr_sha256",
        ):
            _sha(value[field], f"worker {field}")
        for field in ("container_stdout_size_bytes", "container_stderr_size_bytes"):
            _require(type(value[field]) is int and value[field] >= 0, f"worker {field} drifted")
        if require_peer_identity:
            value["peer_identity"] = _validate_peer_identity_observation(
                _mapping(value.get("peer_identity"), "worker peer identity"),
                completed_handshake=True,
            )
        checked.append(value)
    _require({item["request_id"] for item in checked} == set(by_id), "worker observation IDs are not exact")
    if require_peer_identity:
        for branch in BRANCHES:
            branch_peers = [
                item["peer_identity"]
                for item in checked
                if item["branch"] == branch
            ]
            _require(
                len(branch_peers) == len(CODECS)
                and all(item == branch_peers[0] for item in branch_peers),
                f"{branch} peer identity differs across codecs",
            )
    checked.sort(key=lambda item: next(i for i, request in enumerate(requests) if request["request_id"] == item["request_id"]))
    return checked


def _validate_local_runtime_boundary() -> None:
    _require(os.name == "posix" and sys.platform.startswith("linux"), "local Docker execution requires Linux/WSL")
    _require(
        hasattr(os, "getuid")
        and os.getuid() == CONTAINER_UID
        and os.getgid() == CONTAINER_GID,
        "WSL non-root UID/GID differs from the frozen pilot pin",
    )
    socket_path = Path("/var/run/docker.sock")
    try:
        value = socket_path.lstat()
    except OSError as error:
        raise ExecutorContractError("local Docker Unix socket is unavailable") from error
    _require(
        not socket_path.is_symlink() and stat.S_ISSOCK(value.st_mode),
        "local Docker endpoint is not the exact Unix socket",
    )


def _default_gpu_probe(**kwargs: Any) -> Mapping[str, Any]:
    daemon = _mapping(kwargs.get("daemon"), "GPU probe daemon")
    cli = kwargs.get("docker_cli_identity")
    runner = kwargs.get("runner")
    run_identity = kwargs.get("run_identity")
    cleanup_mutex = kwargs.get("cleanup_mutex")
    run_lease = kwargs.get("run_lease")
    container_registry = kwargs.get("container_registry")
    image = _mapping(kwargs.get("image"), "GPU probe image")
    image_labels = _mapping(image.get("labels"), "GPU probe image labels")
    _require(type(cli) is FileIdentity, "GPU probe Docker CLI identity is unavailable")
    _require(hasattr(runner, "run"), "GPU probe command runner is unavailable")
    _require(
        cleanup_mutex is not None
        and run_lease is not None
        and type(container_registry) is _OwnedContainerRegistry,
        "GPU probe cleanup or retention custody is unavailable",
    )

    def watchdog_factory(**owned: Any) -> _ContainerWatchdog:
        return _spawn_container_watchdog(
            **owned,
            docker_cli_identity=cli,
            daemon=daemon,
            cleanup_mutex=cleanup_mutex,
            run_lease=run_lease,
        )

    return _probe_exact_gpu(
        runner=runner,
        run_identity=str(run_identity),
        cleanup_mutex=cleanup_mutex,
        container_registry=container_registry,
        watchdog_factory=watchdog_factory,
        expected_image_labels={str(key): str(item) for key, item in image_labels.items()},
    )


def _default_dependencies() -> _ExecutorDependencies:
    runner = _BoundedCommandRunner()
    return _ExecutorDependencies(
        platform_name=os.name,
        environment=dict(os.environ),
        observe_docker_cli=lambda: _observe_regular_file(Path(DOCKER_CLI)),
        command_runner=runner,
        planner_builder=build_pilot_plan,
        gpu_probe=_default_gpu_probe,
        local_runtime_guard=_validate_local_runtime_boundary,
        observe_file=_observe_regular_file,
        binding_loader=_load_binding_inventory,
        tensor_reader=_read_selected_tensors,
        worker_runner=_run_tensor_workers,
        run_lock_factory=_acquire_run_lease,
        cleanup_mutex_factory=_create_cleanup_mutex,
        progress_factory=_ExecutionProgressLedger,
        failure_diagnostic_writer=_persist_execution_failure_diagnostic,
        stale_reaper=_reap_stale_execution,
        peercred_platform_observer=_observe_peercred_pid0_platform,
    )


def _reap_stale_execution(
    *,
    runner: CommandRunner,
    project_root: Path | str,
    run_id: str,
    run_identity: str,
    bindings: BindingInventory,
    expected_image_labels: Mapping[str, str],
    cleanup_mutex: Any,
) -> tuple[list[str], bool]:
    root = Path(project_root).resolve()
    run_root = root / "runs" / "nonpublication" / run_id
    socket_root = _ipc_runtime_path(run_identity)
    run_root_exists = run_root.exists() or run_root.is_symlink()
    if run_root_exists:
        _require(run_root.is_dir() and not run_root.is_symlink(), "existing nonpublication run namespace is unsafe")
    specs: list[tuple[str, dict[str, str], dict[str, Path]]] = []
    probe_labels = {
        OWNER_LABEL: OWNER_VALUE,
        RUN_LABEL: run_identity,
        BRANCH_LABEL: "runtime_probe",
    }
    specs.append((f"vast-kpp-v2-np-{run_identity[:16]}-probe", probe_labels, {}))
    for branch in BRANCHES:
        binding = _mapping(bindings.bindings[branch], f"{branch} TensorRT binding")
        binding_source = run_root / "bindings" / f"{branch}.tensorrt_cuda.json"
        source = run_root / "model_staging" / Path(bindings.source_paths[branch]).name
        engine = run_root / "model_staging" / Path(bindings.engine_paths[branch]).name
        mounts = {
            f"/run/vast/bindings/{binding_source.name}": binding_source,
            str(binding["source_path"]): source,
            str(binding["engine_path"]): engine,
            "/run/vast/analytics": socket_root,
        }
        specs.append(
            (
                f"vast-kpp-v2-np-{run_identity[:16]}-{branch}",
                {
                    OWNER_LABEL: OWNER_VALUE,
                    RUN_LABEL: run_identity,
                    BRANCH_LABEL: branch,
                },
                mounts,
            )
        )
    reaped: list[str] = []
    failures: list[tuple[str | None, BaseException]] = []
    for name, labels, mounts in specs:
        try:
            recovered = _recover_and_cleanup_owned_container_by_name(
                runner=runner,
                container_name=name,
                labels=labels,
                expected_mounts=mounts,
                cleanup_mutex=cleanup_mutex,
                expected_image_labels=expected_image_labels,
            )
        except BaseException as error:
            raw_branch = labels.get(BRANCH_LABEL)
            failures.append(
                (raw_branch if raw_branch in BRANCHES else None, error)
            )
            continue
        if recovered is None:
            continue
        reaped.append(hashlib.sha256(recovered.encode("ascii")).hexdigest())
    if failures:
        primary_branch, _primary = failures[0]
        reaper_error = _StaleExecutionReaperError(
            failures=failures,
            reaped_container_id_sha256s=reaped,
        )
        raise _ExecutionFailureBundle(
            primary=reaper_error,
            primary_phase="mutating_preworker",
            primary_stage="stale_reaper",
            primary_branch=primary_branch,
            supplemental_failures=[],
        )
    return sorted(reaped), run_root_exists


def _execute_mutating_phase(
    *,
    dependencies: _ExecutorDependencies,
    image: Mapping[str, object],
    daemon: Mapping[str, object],
    cli: FileIdentity,
    run_identity: str,
    role: str,
    project_root: Path | str,
    run_id: str,
    plan: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    bindings: BindingInventory,
    payloads: TensorInventory,
    model_file_observations: Mapping[str, Mapping[str, object]],
    expected_daemon_id: str,
    expected_daemon_server_version: str,
    expected_daemon_api_version: str,
    cleanup_mutex: Any,
    run_lease: Any,
    container_registry: _OwnedContainerRegistry,
    attempt_context: _ExecutionAttemptContext,
    peercred_diagnostic_only: bool = False,
    peer_identity_mode: str = PEER_IDENTITY_MODE_NATIVE_VISIBLE,
    peercred_platform_observation: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], int]:
    _require(dependencies.worker_runner is not None, "TensorRT worker runner is unavailable")
    _require(dependencies.observe_file is not None, "model file observer is unavailable")
    _require(
        callable(getattr(cleanup_mutex, "hold", None))
        and isinstance(
            getattr(run_lease, "contract", None),
            Mapping,
        )
        and type(container_registry) is _OwnedContainerRegistry
        and container_registry.run_identity == run_identity,
        "cleanup mutex or owned-container registry drifted",
    )
    _require(
        type(attempt_context) is _ExecutionAttemptContext
        and attempt_context.run_id == run_id
        and attempt_context.run_identity == run_identity
        and attempt_context.role == role
        and list(attempt_context.requests) == list(requests),
        "execution attempt context binding drifted",
    )
    _require(
        type(peercred_diagnostic_only) is bool,
        "SO_PEERCRED diagnostic-only selector drifted",
    )
    _require(
        not peercred_diagnostic_only or role == "secondary",
        "SO_PEERCRED diagnostic-only role drifted",
    )
    _require(
        type(peer_identity_mode) is str
        and peer_identity_mode in PEER_IDENTITY_MODES
        and (
            not peercred_diagnostic_only
            or peer_identity_mode == PEER_IDENTITY_MODE_NATIVE_VISIBLE
        )
        and (
            peer_identity_mode
            == PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
        )
        is (peercred_platform_observation is not None),
        "peer identity execution selection drifted",
    )
    attempt_context.mark("mutating_preworker", "stale_reaper")
    if dependencies.stale_reaper is None:
        reaped_container_ids, existing_run_root = [], False
    else:
        reaped_container_ids, existing_run_root = dependencies.stale_reaper(
            runner=dependencies.command_runner,
            project_root=project_root,
            run_id=run_id,
            run_identity=run_identity,
            bindings=bindings,
            cleanup_mutex=cleanup_mutex,
            expected_image_labels=_mapping(image.get("labels"), "TensorRT image labels"),
        )
    if existing_run_root:
        return (
            _blocked_artifact(
                role=role,
                status="blocked_existing_nonpublication_run_namespace",
                blocker="existing run namespace was not overwritten; exact owned containers were reaped",
                runtime={
                    "run_identity_sha256": run_identity,
                    "reaped_container_id_sha256s": reaped_container_ids,
                    "controller_death_cleanup_attested": False,
                    **(
                        {
                            "diagnostic_so_peercred_only": True,
                            "capability_handshake_performed": False,
                            "peer_credentials_accepted_for_inference": False,
                            "inference_performed": False,
                        }
                        if peercred_diagnostic_only
                        else {}
                    ),
                },
            ),
            78,
        )
    attempt_context.mark("mutating_preworker", "gpu_probe")
    gpu = dict(
        dependencies.gpu_probe(
            image=image,
            daemon=daemon,
            runner=dependencies.command_runner,
            run_identity=run_identity,
            docker_cli_identity=cli,
            cleanup_mutex=cleanup_mutex,
            run_lease=run_lease,
            container_registry=container_registry,
        )
    )
    _require(gpu.get("device_id") == TENSORRT_GPU_UUID, "GPU probe UUID differs from the frozen pilot pin")
    _sha(gpu.get("worker_implementation_sha256"), "GPU worker implementation")
    _sha(gpu.get("observation_sha256"), "GPU probe observation")
    attempt_context.mark("mutating_preworker", "run_namespace")
    run_root, logical_run_root, run_root_custody = _create_run_namespace(
        project_root,
        run_id,
    )
    attempt_context.bind_run_root(run_root, run_root_custody)
    attempt_context.mark("mutating_preworker", "binding_materialization")
    binding_descriptors = _materialize_bindings(run_root, bindings)
    _require(
        dependencies.progress_factory is not None,
        "execution progress ledger is unavailable",
    )
    progress = dependencies.progress_factory(
        run_root=run_root,
        run_id=run_id,
        run_identity=run_identity,
        role=role,
        requests=requests,
    )
    _require(
        type(progress) is _ExecutionProgressLedger,
        "execution progress ledger type drifted",
    )
    attempt_context.bind_progress(progress)
    attempt_context.mark("worker_execution", "worker_orchestration")
    raw_worker_observations = dependencies.worker_runner(
        project_root=Path(project_root).resolve(),
        run_root=run_root,
        logical_run_root=logical_run_root,
        run_identity=run_identity,
        plan=plan,
        requests=requests,
        bindings=bindings,
        payloads=payloads,
        binding_descriptors=binding_descriptors,
        runtime_probe=gpu,
        runtime_image=image,
        runtime_daemon=daemon,
        peer_identity_mode=peer_identity_mode,
        peercred_platform_observation=peercred_platform_observation,
        peercred_platform_observer=dependencies.peercred_platform_observer,
        docker_cli_identity=cli,
        command_runner=dependencies.command_runner,
        cleanup_mutex=cleanup_mutex,
        run_lease=run_lease,
        container_registry=container_registry,
        progress=progress,
        peercred_diagnostic_only=peercred_diagnostic_only,
    )
    _require(
        not peercred_diagnostic_only,
        "SO_PEERCRED diagnostic-only worker unexpectedly returned observations",
    )
    attempt_context.mark(
        "postexecution_validation", "worker_observation_validation"
    )
    worker_observations = _validate_worker_observations(raw_worker_observations, requests)
    peer_identity_by_branch: dict[str, dict[str, object]] = {}
    for branch in BRANCHES:
        branch_values = [
            dict(_mapping(item["peer_identity"], f"{branch} peer identity"))
            for item in worker_observations
            if item["branch"] == branch
        ]
        _require(
            len(branch_values) == len(CODECS)
            and all(item == branch_values[0] for item in branch_values)
            and branch_values[0].get("peer_identity_mode") == peer_identity_mode,
            f"{branch} selected peer identity mode drifted",
        )
        peer_identity_by_branch[branch] = branch_values[0]
    attempt_context.mark(
        "postexecution_validation", "model_file_revalidation"
    )
    post_model_file_observations = _validate_binding_file_identities(
        bindings, dependencies.observe_file
    )
    _require(post_model_file_observations == model_file_observations, "model files changed during TensorRT execution")
    attempt_context.mark("postexecution_validation", "daemon_revalidation")
    final_daemon = _validate_daemon(
        dependencies.command_runner,
        expected_id=expected_daemon_id,
        expected_server_version=expected_daemon_server_version,
        expected_api_version=expected_daemon_api_version,
    )
    _require(final_daemon == daemon, "local Docker daemon changed during execution")
    if peercred_platform_observation is not None:
        attempt_context.mark(
            "postexecution_validation", "platform_revalidation"
        )
        _require(
            dependencies.peercred_platform_observer is not None
            and dict(dependencies.peercred_platform_observer(final_daemon))
            == dict(peercred_platform_observation),
            "WSL2 peer platform changed during execution",
        )
    attempt_context.mark(
        "postexecution_validation", "docker_cli_revalidation"
    )
    _require(dependencies.observe_docker_cli() == cli, "Docker CLI identity changed during execution")
    attempt_context.mark("final_cleanup", "final_owned_container_cleanup")
    cleanup_facts = _finalize_owned_container_cleanup(
        runner=dependencies.command_runner,
        cleanup_mutex=cleanup_mutex,
        container_registry=container_registry,
    )
    attempt_context.mark("postexecution_validation", "progress_finalization")
    progress_facts = attempt_context.snapshot_progress()
    _require(
        progress_facts["validated_checkpoint_count"] == 8
        and progress_facts["all_inferences_completed"] is True
        and progress_facts["inference_performed"] is True
        and progress_facts["inference_performed_attested"] is True,
        "execution progress ledger did not attest all inference responses",
    )
    attempt_context.finalize_progress()
    candidate = _mapping(plan.get("candidate"), "pilot candidate")
    decision = _mapping(plan.get("decision"), "pilot decision")
    receipt = _mapping(candidate.get("receipt"), "pilot candidate receipt")
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": RESULT_ARTIFACT_KIND,
        "claim_status": "engineering_complete_nonpublication_not_evidence",
        "status": "completed_nonpublication_pilot",
        "role": role,
        "run_id": run_id,
        "run_identity_sha256": run_identity,
        "run_root": logical_run_root,
        "pilot_plan_sha256": plan["pilot_plan_sha256"],
        "matrix_identity_sha256": plan["matrix_identity_sha256"],
        "decision_sha256": decision.get("decision_sha256"),
        "candidate_receipt": {
            "path": receipt.get("path"),
            "size_bytes": receipt.get("size_bytes"),
            "sha256": receipt.get("sha256"),
            "candidate_receipt_sha256": receipt.get("candidate_receipt_sha256"),
        },
        "candidate_dataset_aggregate_sha256": candidate.get("dataset_aggregate_sha256"),
        "candidate_sampling_rule_sha256": candidate.get("sampling_rule_sha256"),
        "corpus_descriptors": [
            dict(_mapping(item, "pilot corpus descriptor"))
            for item in candidate["corpora"]
        ],
        "runtime_preflight": {
            "docker_cli": {"path": DOCKER_CLI, "size_bytes": cli.size_bytes, "sha256": cli.sha256},
            "daemon": dict(daemon),
            "image": dict(image),
            "gpu": gpu,
            "network_or_pull_performed_during_executor_invocation": False,
            "docker_build_performed_during_executor_invocation": False,
            "offline_image_load_performed_during_executor_invocation": False,
            "resume_reaped_container_id_sha256s": reaped_container_ids,
            "peer_identity_mode": peer_identity_mode,
            "peer_identity_policy_version": PEER_IDENTITY_POLICY_VERSION,
            "peercred_pid0_platform_observation": (
                dict(peercred_platform_observation)
                if peercred_platform_observation is not None
                else None
            ),
            "owned_container_cleanup": cleanup_facts,
        },
        "model_pins": {branch: dict(TENSORRT_ENGINE_PINS[branch]) for branch in BRANCHES},
        "model_parity_manifest_identity_sha256": bindings.manifest_identity_sha256,
        "execution_config_identity_sha256": bindings.execution_config_identity_sha256,
        "model_file_observations": dict(model_file_observations),
        "binding_descriptors": binding_descriptors,
        "tensor_bundle_observations": [
            dict(_mapping(item, "tensor bundle observation"))
            for item in payloads.bundle_observations
        ],
        "request_count": 8,
        "worker_count": 4,
        "requests_per_worker": 2,
        "request_observations": worker_observations,
        "execution_progress": progress_facts,
        "peer_identity_by_branch": peer_identity_by_branch,
        "peer_identity_claims": {
            "peer_identity_mode": peer_identity_mode,
            "policy_version": PEER_IDENTITY_POLICY_VERSION,
            "peer_uid_gid_exact": all(
                item["peer_uid_gid_exact"] is True
                for item in peer_identity_by_branch.values()
            ),
            "container_state_pid_positive": all(
                item["container_state_pid_positive"] is True
                for item in peer_identity_by_branch.values()
            ),
            "platform_observation_sha256": (
                peercred_platform_observation["observation_sha256"]
                if peercred_platform_observation is not None
                else None
            ),
            "peer_pid_visible_in_controller_namespace": all(
                item["peer_pid_visible_in_controller_namespace"] is True
                for item in peer_identity_by_branch.values()
            ),
            "peer_pid_state_pid_equality_attested": all(
                item["peer_pid_state_pid_equality_attested"] is True
                for item in peer_identity_by_branch.values()
            ),
            "peer_identity_by_pid_attested": all(
                item["peer_identity_by_pid_attested"] is True
                for item in peer_identity_by_branch.values()
            ),
            "socket_to_container_pid_binding_attested": all(
                item["peer_socket_to_container_pid_binding_attested"] is True
                for item in peer_identity_by_branch.values()
            ),
            "protocol_nonce_capability_handshake_performed": True,
            "global_four_worker_handshake_before_inference_attested": True,
            "native_ipc_namespace_attested": True,
            "readonly_mounts_attested": True,
            "container_image_entrypoint_identity_attested": True,
        },
        "threat_model_boundary": {
            "concurrent_project_tree_writer_excluded": True,
            "concurrent_same_uid_socket_connector_excluded": True,
            "concurrent_same_uid_project_tree_writer_excluded": True,
            "concurrent_other_uid_wsl_project_tree_writer_excluded": True,
            "concurrent_windows_side_project_writer_excluded": True,
            "concurrent_same_uid_runtime_state_writer_excluded": True,
            "filesystem_acl_attested": False,
            "peer_identity_by_pid_unavailable_is_not_represented_as_attested": True,
        },
        "operational_completion_observed": True,
        "inference_performed": True,
        **_FALSE_CLAIMS,
    }
    artifact = {**core, "assessment_sha256": _identity(core)}
    attempt_context.mark("assessment_persistence", "assessment_write")
    attempt_context.assessment_write_started()
    assessment_payload = canonical_line(artifact)
    if attempt_context.run_root_custody is not None:
        _persist_held_runroot_leaf(
            attempt_context.run_root_custody,
            name=ASSESSMENT_NAME,
            payload=assessment_payload,
            requested_mode=0o600,
        )
    else:
        _write_new(run_root / ASSESSMENT_NAME, assessment_payload)
    attempt_context.assessment_write_returned()
    return artifact, 0


def _emergency_execution_failure_artifact(
    *,
    attempt_context: _ExecutionAttemptContext,
    primary_error: BaseException,
    reporting_error: BaseException,
) -> dict[str, object]:
    """Last-resort postexecution truth; never relabel an entered run as preflight."""

    progress: dict[str, object] | None = None
    if isinstance(attempt_context.progress_snapshot, Mapping):
        try:
            candidate_progress = dict(attempt_context.progress_snapshot)
            canonical_line(candidate_progress)
            progress = candidate_progress
        except BaseException:
            progress = None
    if progress is None:
        progress = {
            "expected_response_count": 8,
            "dispatched_checkpoint_count": 0,
            "client_returned_checkpoint_count": 0,
            "validated_checkpoint_count": 0,
            "dispatched_request_ids": [],
            "client_returned_request_ids": [],
            "validated_request_ids": [],
            "checkpoint_sha256s": [],
            "checkpoint_records": [],
            "persistence": {
                "mode": "unknown",
                "relative_directory": None,
                "file_count": 0,
                "filesystem_magic": None,
                "requested_file_mode": None,
                "effective_file_mode": None,
                "integrity_attested": False,
                "closure_error_sha256": None,
            },
            "chain_head_sha256": None,
            "handshake_checkpoint_count": 0,
            "four_party_barrier_released": False,
            "inference_performed": None,
            "inference_performed_attested": False,
            "all_inferences_completed": False,
        }

    def safe_error(value: BaseException) -> dict[str, object]:
        try:
            projection = _exception_detail_projection(value)
            return {
                **projection,
                "projection_attested": True,
            }
        except BaseException:
            return {
                "exception_type": type(value).__name__,
                "message_sha256": None,
                "docker_command": None,
                "closure_failure": None,
                "projection_attested": False,
            }

    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": (
            "vast_kpp_v2_nonpublication_execution_failure_emergency_v1"
        ),
        "claim_status": (
            "postexecution_failure_reporting_degraded_nonpublication_not_acceptance"
        ),
        "status": "blocked_postexecution_failure_reporting_error",
        "role": attempt_context.role,
        "run_id": attempt_context.run_id,
        "run_identity_sha256": attempt_context.run_identity,
        "failure_phase": "failure_reporting",
        "last_attested_phase": attempt_context.phase,
        "last_attested_stage": attempt_context.stage,
        "last_attested_branch": attempt_context.branch,
        "primary_failure": safe_error(primary_error),
        "failure_reporting_error": safe_error(reporting_error),
        "cleanup_failures": [
            {
                "scope": item.scope,
                "phase": item.phase,
                "stage": item.stage,
                "branch": item.branch,
                "failure": safe_error(item.error),
            }
            for item in attempt_context.supplemental_failures
        ],
        "progress": progress,
        "assessment_persistence": dict(attempt_context.assessment_persistence),
        "runtime_cleanup": attempt_context.runtime_cleanup_facts(),
        "diagnostic_persistence": {
            "state": "ambiguous",
            "commit_attested": False,
        },
        "inference_performed": progress.get("inference_performed"),
        "inference_performed_attested": progress.get(
            "inference_performed_attested"
        ),
        "all_inferences_completed": progress.get("all_inferences_completed"),
        "operational_completion_observed": False,
        **_FALSE_CLAIMS,
    }
    return {
        **core,
        "failure_diagnostic_sha256": hashlib.sha256(
            b"VAST-KPP-V2-EXECUTION-FAILURE-EMERGENCY-V1\0"
            + canonical_line(core)
        ).hexdigest(),
    }


def execute_nonpublication_pilot(
    *,
    project_root: Path | str,
    decision_path: Path | str,
    candidate_root: Path | str,
    role: str,
    expected_receipt_file_sha256: str,
    expected_receipt_self_sha256: str,
    run_id: str,
    expected_docker_cli_size_bytes: int,
    expected_docker_cli_sha256: str,
    expected_daemon_id: str,
    expected_daemon_server_version: str,
    expected_daemon_api_version: str,
    diagnostic_so_peercred_only: bool = False,
    peer_identity_mode: str = PEER_IDENTITY_MODE_NATIVE_VISIBLE,
    _dependencies: _ExecutorDependencies | None = None,
) -> tuple[dict[str, object], int]:
    """Run or fail closed; external pins are observations, never authorization."""

    _require(role in {"secondary", "sensitivity"}, "pilot role is invalid")
    _require(type(run_id) is str and _RUN_ID_RE.fullmatch(run_id) is not None, "nonpublication run_id is invalid")
    _require(type(expected_docker_cli_size_bytes) is int and expected_docker_cli_size_bytes > 0, "Docker CLI size pin is invalid")
    _require(_SHA_RE.fullmatch(expected_docker_cli_sha256) is not None, "Docker CLI SHA-256 pin is invalid")
    _require(type(expected_daemon_id) is str and bool(expected_daemon_id), "Docker daemon ID pin is invalid")
    _require(type(expected_daemon_server_version) is str and bool(expected_daemon_server_version), "Docker daemon version pin is invalid")
    _require(type(expected_daemon_api_version) is str and bool(expected_daemon_api_version), "Docker daemon API pin is invalid")
    _require(
        type(diagnostic_so_peercred_only) is bool,
        "SO_PEERCRED diagnostic-only selector drifted",
    )
    _require(
        type(peer_identity_mode) is str
        and peer_identity_mode in PEER_IDENTITY_MODES
        and (
            not diagnostic_so_peercred_only
            or peer_identity_mode == PEER_IDENTITY_MODE_NATIVE_VISIBLE
        ),
        "peer identity mode selector drifted",
    )
    _require(
        (
            _PEERCRED_DIAGNOSTIC_RUN_ID_RE.fullmatch(run_id) is not None
        )
        is diagnostic_so_peercred_only
        and (not diagnostic_so_peercred_only or role == "secondary"),
        "SO_PEERCRED diagnostic-only run identity selector drifted",
    )
    diagnostic_runtime: dict[str, object] = (
        {
            "diagnostic_so_peercred_only": True,
            "capability_handshake_performed": False,
            "peer_credentials_accepted_for_inference": False,
            "inference_performed": False,
        }
        if diagnostic_so_peercred_only
        else {}
    )
    if _dependencies is None:
        _dependencies = _default_dependencies()
    if _dependencies.platform_name != "posix":
        return (
            _blocked_artifact(
                role=role,
                status="blocked_unsupported_execution_platform",
                blocker="the nonpublication executor requires WSL/POSIX",
                runtime=diagnostic_runtime,
            ),
            78,
        )
    for variable in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        _require(not _dependencies.environment.get(variable), f"{variable} is forbidden")
    if _dependencies.local_runtime_guard is not None:
        _dependencies.local_runtime_guard()
    cli = _dependencies.observe_docker_cli()
    _require(
        cli
        == FileIdentity(
            size_bytes=expected_docker_cli_size_bytes,
            sha256=expected_docker_cli_sha256,
        ),
        "Docker CLI identity drifted",
    )
    daemon = _validate_daemon(
        _dependencies.command_runner,
        expected_id=expected_daemon_id,
        expected_server_version=expected_daemon_server_version,
        expected_api_version=expected_daemon_api_version,
    )
    peercred_platform_observation: dict[str, object] | None = None
    if (
        peer_identity_mode
        == PEER_IDENTITY_MODE_DOCKER_DESKTOP_WSL2_PID0
    ):
        _require(
            _dependencies.peercred_platform_observer is not None,
            "namespace-hidden peer platform observer is unavailable",
        )
        peercred_platform_observation = (
            _validate_peercred_pid0_platform_observation(
                _dependencies.peercred_platform_observer(daemon)
            )
        )
    peer_identity_runtime = (
        {}
        if diagnostic_so_peercred_only
        else {
            "peer_identity_mode": peer_identity_mode,
            "peer_identity_policy_version": PEER_IDENTITY_POLICY_VERSION,
            "peercred_pid0_platform_observation": (
                dict(peercred_platform_observation)
                if peercred_platform_observation is not None
                else None
            ),
        }
    )
    image_capture = _run_read_only(
        _dependencies.command_runner,
        [
            DOCKER_CLI,
            DOCKER_HOST_ARG,
            "image",
            "inspect",
            "--format={{json .}}",
            TENSORRT_IMAGE_ID,
        ],
        label="exact TensorRT worker image inspect",
    )
    if image_capture.returncode != 0:
        exact_absence = _exact_image_absent(
            _dependencies.command_runner, image_capture
        )
        return (
            _blocked_artifact(
                role=role,
                status=(
                    "blocked_missing_exact_pinned_docker_image"
                    if exact_absence
                    else "blocked_local_docker_image_inspect_failure"
                ),
                blocker=(
                    "exact pinned TensorRT worker image is absent from the local daemon"
                    if exact_absence
                    else "local Docker image inspection did not return a classified not-found result"
                ),
                runtime={
                    "docker_cli": {
                        "path": DOCKER_CLI,
                        "size_bytes": cli.size_bytes,
                        "sha256": cli.sha256,
                    },
                    "daemon": daemon,
                    "image_available": False if exact_absence else None,
                    "network_or_pull_performed_during_executor_invocation": False,
                    **peer_identity_runtime,
                    **diagnostic_runtime,
                },
            ),
            78,
        )
    try:
        image = _validate_image_inspect(
            _parse_json(image_capture.stdout, "exact TensorRT worker image inspect")
        )
    except ExecutorContractError:
        return (
            _blocked_artifact(
                role=role,
                status="blocked_exact_pinned_docker_image_mismatch",
                blocker="local image inspect does not match the frozen TensorRT image contract",
                runtime={
                    "docker_cli": {
                        "path": DOCKER_CLI,
                        "size_bytes": cli.size_bytes,
                        "sha256": cli.sha256,
                    },
                    "daemon": daemon,
                    "image_available": None,
                    "network_or_pull_performed_during_executor_invocation": False,
                    **peer_identity_runtime,
                    **diagnostic_runtime,
                },
            ),
            78,
        )
    run_identity_core: dict[str, object] = {
        "schema_version": 1,
        "role": role,
        "run_id": run_id,
        "receipt_file_sha256": _sha(
            expected_receipt_file_sha256, "candidate receipt file pin"
        ),
        "receipt_self_sha256": _sha(
            expected_receipt_self_sha256, "candidate receipt self pin"
        ),
        "docker_cli_sha256": cli.sha256,
        "daemon_observation_sha256": daemon["observation_sha256"],
        "worker_image_id": TENSORRT_IMAGE_ID,
        "gpu_uuid": TENSORRT_GPU_UUID,
    }
    if diagnostic_so_peercred_only:
        run_identity_core["diagnostic_so_peercred_only"] = True
    else:
        run_identity_core["peer_identity_mode"] = peer_identity_mode
        run_identity_core["peer_identity_policy_version"] = (
            PEER_IDENTITY_POLICY_VERSION
        )
        run_identity_core["peercred_pid0_platform_observation_sha256"] = (
            peercred_platform_observation["observation_sha256"]
            if peercred_platform_observation is not None
            else None
        )
    run_identity = hashlib.sha256(
        b"VAST:kpp-v2-nonpublication-executor-run:v1\0"
        + canonical_line(run_identity_core)
    ).hexdigest()
    # Candidate custody starts only after the exact local image has passed the
    # read-only preflight.  The GPU probe is daemon-mutating, so all candidate,
    # model, and tensor validation is deliberately completed before it.
    plan = _dependencies.planner_builder(
        project_root=project_root,
        decision_path=decision_path,
        candidate_root=candidate_root,
        role=role,
        expected_receipt_file_sha256=expected_receipt_file_sha256,
        expected_receipt_self_sha256=expected_receipt_self_sha256,
    )
    requests = _validate_execution_plan(
        _mapping(plan, "pilot plan"),
        role=role,
        expected_receipt_file_sha256=expected_receipt_file_sha256,
        expected_receipt_self_sha256=expected_receipt_self_sha256,
    )
    _require(_dependencies.binding_loader is not None, "TensorRT binding loader is unavailable")
    _require(_dependencies.tensor_reader is not None, "candidate tensor reader is unavailable")
    _require(_dependencies.worker_runner is not None, "TensorRT worker runner is unavailable")
    bindings = _dependencies.binding_loader(
        project_root=project_root,
        plan=plan,
        requests=requests,
    )
    _require(type(bindings) is BindingInventory, "TensorRT binding inventory type drifted")
    _validate_bindings(bindings, requests)
    payloads = _dependencies.tensor_reader(
        project_root=project_root,
        candidate_root=candidate_root,
        plan=plan,
        requests=requests,
    )
    _require(type(payloads) is TensorInventory, "candidate tensor inventory type drifted")
    _validate_tensor_inventory(payloads, requests)
    _require(_dependencies.observe_file is not None, "model file observer is unavailable")
    model_file_observations = _validate_binding_file_identities(
        bindings, _dependencies.observe_file
    )
    attempt_context = _ExecutionAttemptContext(
        run_id=run_id,
        run_identity=run_identity,
        role=role,
        requests=requests,
    )

    lease = (
        _dependencies.run_lock_factory(run_identity)
        if _dependencies.run_lock_factory is not None
        else None
    )
    cleanup_mutex: Any | None = None
    result: tuple[dict[str, object], int] | None = None
    primary_error: BaseException | None = None
    try:
        _require(
            lease is not None
            and isinstance(getattr(lease, "contract", None), Mapping)
            and callable(getattr(lease, "release", None)),
            "run lease owner interface drifted",
        )
        _require(
            _dependencies.cleanup_mutex_factory is not None,
            "cleanup mutex factory is unavailable",
        )
        cleanup_mutex = _dependencies.cleanup_mutex_factory(run_identity)
        _require(
            callable(getattr(cleanup_mutex, "hold", None))
            and callable(getattr(cleanup_mutex, "close", None)),
            "cleanup mutex owner interface drifted",
        )
        container_registry = _OwnedContainerRegistry(run_identity)
        result = _execute_mutating_phase(
            dependencies=_dependencies,
            image=image,
            daemon=daemon,
            cli=cli,
            run_identity=run_identity,
            role=role,
            project_root=project_root,
            run_id=run_id,
            plan=plan,
            requests=requests,
            bindings=bindings,
            payloads=payloads,
            model_file_observations=model_file_observations,
            expected_daemon_id=expected_daemon_id,
            expected_daemon_server_version=expected_daemon_server_version,
            expected_daemon_api_version=expected_daemon_api_version,
            cleanup_mutex=cleanup_mutex,
            run_lease=lease,
            container_registry=container_registry,
            attempt_context=attempt_context,
            peercred_diagnostic_only=diagnostic_so_peercred_only,
            peer_identity_mode=peer_identity_mode,
            peercred_platform_observation=peercred_platform_observation,
        )
    except BaseException as error:
        primary_error = error
    finally:
        outer_cleanup_failures: list[tuple[str, str, BaseException]] = []
        if (
            attempt_context.mutating_phase_entered
            and cleanup_mutex is not None
            and lease is not None
        ):
            try:
                outer_cleanup_failures.extend(
                    _produce_failure_safe_runtime_poststate(
                        runner=_dependencies.command_runner,
                        cleanup_mutex=cleanup_mutex,
                        run_lease=lease,
                        run_identity=run_identity,
                        attempt_context=attempt_context,
                    )
                )
            except BaseException as error:
                outer_cleanup_failures.append(
                    (
                        "runtime_poststate_observation",
                        "runtime_poststate_recording",
                        error,
                    )
                )
        if cleanup_mutex is not None:
            try:
                cleanup_mutex.close()
            except BaseException as error:
                outer_cleanup_failures.append(
                    ("cleanup_mutex_close", "cleanup_mutex_close", error)
                )
        if lease is not None:
            try:
                lease.release()
            except BaseException as error:
                outer_cleanup_failures.append(
                    ("run_lease_release", "run_lease_release", error)
                )
        for scope, stage, error in outer_cleanup_failures:
            try:
                attempt_context.record_cleanup_failure(
                    scope=scope,
                    stage=stage,
                    error=error,
                )
            except BaseException as recording_error:
                wrapped = _DescriptorClosureError(
                    operation="outer_cleanup_failure_recording",
                    primary=error,
                    close_failures=[recording_error],
                )
                if primary_error is None:
                    primary_error = wrapped
                else:
                    try:
                        attempt_context.supplemental_failures.append(
                            _SupplementalExecutionFailure(
                                scope=scope,
                                phase="final_cleanup",
                                stage=stage,
                                branch=None,
                                error=wrapped,
                            )
                        )
                    except BaseException:
                        primary_error = _DescriptorClosureError(
                            operation="outer_cleanup_failure_aggregation",
                            primary=primary_error,
                            close_failures=[wrapped],
                        )

    if primary_error is None and attempt_context.supplemental_failures:
        promoted = attempt_context.supplemental_failures.pop(0)
        primary_error = promoted.error
        attempt_context.phase = "final_cleanup"
        attempt_context.stage = promoted.stage
        attempt_context.branch = promoted.branch
    if primary_error is None:
        attempt_context.close_run_root()
    if primary_error is None and attempt_context.supplemental_failures:
        promoted = attempt_context.supplemental_failures.pop(0)
        primary_error = promoted.error
        attempt_context.phase = "final_cleanup"
        attempt_context.stage = promoted.stage
        attempt_context.branch = promoted.branch
    if primary_error is None:
        _require(result is not None, "executor result is unavailable")
        return result
    if diagnostic_so_peercred_only:
        attempt_context.close_run_root()
        raise attempt_context.bundle_failure(primary_error)

    def emergency_failure_return(
        reporting_error: BaseException,
    ) -> tuple[dict[str, object], int]:
        emergency_cleanup_errors: list[BaseException] = []
        try:
            attempt_context.record_cleanup_failure(
                scope="failure_diagnostic_persistence",
                stage="failure_diagnostic_write",
                error=reporting_error,
                phase="failure_reporting",
            )
        except BaseException as error:
            emergency_cleanup_errors.append(error)
        try:
            attempt_context.close_progress()
        except BaseException as error:
            emergency_cleanup_errors.append(error)
        try:
            attempt_context.close_run_root()
        except BaseException as error:
            emergency_cleanup_errors.append(error)
        effective_reporting_error = (
            _DescriptorClosureError(
                operation="emergency_failure_reporting_cleanup",
                primary=reporting_error,
                close_failures=emergency_cleanup_errors,
            )
            if emergency_cleanup_errors
            else reporting_error
        )
        return (
            _emergency_execution_failure_artifact(
                attempt_context=attempt_context,
                primary_error=primary_error,
                reporting_error=effective_reporting_error,
            ),
            78,
        )

    try:
        progress_facts = attempt_context.snapshot_progress()
        attempt_context.close_progress()
        progress_facts = attempt_context.snapshot_progress()
        effective_error = attempt_context.bundle_failure(primary_error)
    except BaseException as reporting_error:
        return emergency_failure_return(reporting_error)
    diagnostic_writer_target: Any | None = (
        attempt_context.run_root_custody
        if attempt_context.run_root_custody is not None
        else attempt_context.run_root
    )
    diagnostic_path = (
        f"runs/nonpublication/{run_id}/{EXECUTION_FAILURE_DIAGNOSTIC_NAME}"
        if diagnostic_writer_target is not None
        and _dependencies.failure_diagnostic_writer is not None
        else None
    )
    persistence_state = (
        "self_commit_unattested" if diagnostic_path is not None else "not_started"
    )
    try:
        artifact = _build_execution_failure_diagnostic(
            progress=None,
            progress_facts=progress_facts,
            run_id=run_id,
            run_identity=run_identity,
            role=role,
            error=effective_error,
            phase=attempt_context.phase,
            stage=attempt_context.stage,
            branch=attempt_context.branch,
            diagnostic_path=diagnostic_path,
            diagnostic_persistence_state=persistence_state,
            assessment_persistence=attempt_context.assessment_persistence,
            runtime_cleanup=attempt_context.runtime_cleanup_facts(),
        )
    except BaseException as reporting_error:
        return emergency_failure_return(reporting_error)
    diagnostic_write_error: BaseException | None = None
    if diagnostic_path is not None:
        _require(
            diagnostic_writer_target is not None
            and _dependencies.failure_diagnostic_writer is not None,
            "execution failure diagnostic writer binding drifted",
        )
        try:
            written = _mapping(
                _dependencies.failure_diagnostic_writer(
                    diagnostic_writer_target,
                    artifact,
                ),
                "execution failure diagnostic persistence facts",
            )
            payload = canonical_line(artifact)
            _require(
                written.get("size_bytes") == len(payload)
                and written.get("sha256")
                == hashlib.sha256(payload).hexdigest(),
                "execution failure diagnostic persistence result drifted",
            )
        except BaseException as error:
            diagnostic_write_error = error
            persistence_state = "ambiguous"
    supplemental_count_before_run_root_close = len(
        attempt_context.supplemental_failures
    )
    attempt_context.close_run_root()
    if (
        len(attempt_context.supplemental_failures)
        != supplemental_count_before_run_root_close
    ):
        persistence_state = (
            "ambiguous" if diagnostic_path is not None else "not_started"
        )
    if diagnostic_write_error is not None:
        try:
            attempt_context.record_cleanup_failure(
                scope="failure_diagnostic_persistence",
                stage="failure_diagnostic_write",
                error=diagnostic_write_error,
                phase="failure_reporting",
            )
        except BaseException as reporting_error:
            return emergency_failure_return(
                _DescriptorClosureError(
                    operation="failure_diagnostic_error_recording",
                    primary=diagnostic_write_error,
                    close_failures=[reporting_error],
                )
            )
    try:
        final_error = attempt_context.bundle_failure(primary_error)
    except BaseException as reporting_error:
        return emergency_failure_return(reporting_error)
    if final_error is not effective_error or persistence_state == "ambiguous":
        try:
            artifact = _build_execution_failure_diagnostic(
                progress=None,
                progress_facts=progress_facts,
                run_id=run_id,
                run_identity=run_identity,
                role=role,
                error=final_error,
                phase=attempt_context.phase,
                stage=attempt_context.stage,
                branch=attempt_context.branch,
                diagnostic_path=diagnostic_path,
                diagnostic_persistence_state=persistence_state,
                assessment_persistence=attempt_context.assessment_persistence,
                runtime_cleanup=attempt_context.runtime_cleanup_facts(),
            )
        except BaseException as reporting_error:
            return emergency_failure_return(reporting_error)
    return artifact, 78


def _validate_image_inspect(value: Any) -> dict[str, object]:
    image = _mapping(value, "Docker image inspect")
    config = _mapping(image.get("Config"), "Docker image config")
    labels = _mapping(config.get("Labels"), "Docker image labels")
    _require(image.get("Id") == TENSORRT_IMAGE_ID, "Docker image ID differs from the frozen TensorRT image")
    _require(image.get("Os") == "linux", "TensorRT worker image OS is not linux")
    _require(image.get("Architecture") == "amd64", "TensorRT worker image architecture is not amd64")
    _require(config.get("Entrypoint") == [TENSORRT_ENTRYPOINT], "TensorRT worker image entrypoint drifted")
    observed_labels = dict(labels)
    _require(
        all(type(key) is str and type(item) is str for key, item in observed_labels.items())
        and all(observed_labels.get(key) == item for key, item in IMAGE_LABELS.items()),
        "TensorRT worker image labels drifted",
    )
    return {
        "image_id": TENSORRT_IMAGE_ID,
        "os": "linux",
        "architecture": "amd64",
        "entrypoint": TENSORRT_ENTRYPOINT,
        "base_image_id": TENSORRT_BASE_IMAGE_ID,
        "labels": observed_labels,
        "labels_sha256": hashlib.sha256(_canonical_json(observed_labels)).hexdigest(),
    }


def _validate_container_inspect(
    value: Any,
    *,
    container_id: str,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    expected_state: str,
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> dict[str, object]:
    container = _mapping(value, "Docker container inspect")
    config = _mapping(container.get("Config"), "Docker container config")
    host = _mapping(container.get("HostConfig"), "Docker host config")
    state = _mapping(container.get("State"), "Docker container state")
    actual_labels = _mapping(config.get("Labels"), "Docker container labels")
    _require(container.get("Id") == container_id, "Docker container ID drifted")
    _require(container.get("Name") == f"/{container_name}", "Docker container name drifted")
    _require(container.get("Image") == TENSORRT_IMAGE_ID, "Docker container image ID drifted")
    _require(config.get("Image") == TENSORRT_IMAGE_ID, "Docker container configured image drifted")
    _require(config.get("User") == f"{CONTAINER_UID}:{CONTAINER_GID}", "Docker container user is not the frozen non-root identity")
    _require(config.get("Entrypoint") == [TENSORRT_ENTRYPOINT], "Docker container entrypoint drifted")
    _validate_owned_container_labels(actual_labels, expected_image_labels, labels)
    validated_expected_mounts = _validate_container_watchdog_mount_binding(
        {
            destination: str(source)
            for destination, source in expected_mounts.items()
        },
        labels,
    )
    branch = labels.get(BRANCH_LABEL)
    if branch == "runtime_probe":
        expected_command = ["--capability", "--gpu-device-index", "0"]
    else:
        _require(branch in BRANCHES, "Docker worker branch label drifted")
        binding_destinations = sorted(
            destination
            for destination in validated_expected_mounts
            if destination.startswith("/run/vast/bindings/")
        )
        _require(len(binding_destinations) == 1, "Docker binding mount coverage drifted")
        expected_command = [
            "--binding",
            binding_destinations[0],
            "--socket",
            f"/run/vast/analytics/{branch}.sock",
            "--max-requests",
            "2",
            "--gpu-device-index",
            "0",
        ]
    _require(config.get("Cmd") == expected_command, "Docker container command drifted")
    _require(host.get("NetworkMode") == "none", "Docker container network is not disabled")
    _require(host.get("ReadonlyRootfs") is True, "Docker container root filesystem is writable")
    _require(host.get("CapDrop") == ["ALL"], "Docker container capabilities are not fully dropped")
    _require(host.get("SecurityOpt") == ["no-new-privileges"], "Docker no-new-privileges setting drifted")
    _require(host.get("Privileged") is False, "Docker container is privileged")
    _require(host.get("PidMode") in ("", None), "Docker container uses a host/shared PID namespace")
    _require(host.get("IpcMode") == "private", "Docker container IPC namespace is not private")
    _require(host.get("Runtime") == "runc", "Docker container runtime drifted")
    _require(host.get("Memory") == CONTAINER_MEMORY_BYTES, "Docker container memory cap drifted")
    _require(host.get("MemorySwap") == CONTAINER_MEMORY_BYTES, "Docker container swap cap drifted")
    _require(host.get("NanoCpus") == CONTAINER_NANO_CPUS, "Docker container CPU cap drifted")
    _require(host.get("PidsLimit") == CONTAINER_PIDS_LIMIT, "Docker container PID cap drifted")
    _require(
        host.get("RestartPolicy") == {"Name": "no", "MaximumRetryCount": 0},
        "Docker container restart policy drifted",
    )
    _require(host.get("AutoRemove") is False, "Docker container auto-remove policy drifted")
    _require(
        host.get("Ulimits") == [{"Name": "nofile", "Hard": 1024, "Soft": 1024}],
        "Docker container file-descriptor cap drifted",
    )
    requests = host.get("DeviceRequests")
    _require(type(requests) is list and len(requests) == 1, "Docker container GPU request coverage drifted")
    gpu = _mapping(requests[0], "Docker GPU request")
    _require(
        dict(gpu)
        == {
            "Driver": "",
            "Count": 0,
            "DeviceIDs": [TENSORRT_GPU_UUID],
            "Capabilities": [["gpu"]],
            "Options": {},
        },
        "Docker container GPU request drifted",
    )
    _require(
        "Binds" in host and host.get("Binds") is None,
        "Docker legacy bind-mount configuration drifted",
    )
    if not validated_expected_mounts:
        if "Mounts" in host:
            host_mounts = host["Mounts"]
            _require(
                type(host_mounts) is list and host_mounts == [],
                "Docker zero-mount host projection drifted",
            )
        else:
            host_mounts = []
        _require(
            "Mounts" in container
            and type(container["Mounts"]) is list
            and container["Mounts"] == [],
            "Docker zero-mount runtime projection drifted",
        )
        mounts = container["Mounts"]
    else:
        _require(
            "Mounts" in host
            and type(host["Mounts"]) is list
            and len(host["Mounts"]) == len(validated_expected_mounts),
            "Docker host mount coverage drifted",
        )
        _require(
            "Mounts" in container
            and type(container["Mounts"]) is list
            and len(container["Mounts"]) == len(validated_expected_mounts),
            "Docker runtime mount coverage drifted",
        )
        host_mounts = host["Mounts"]
        mounts = container["Mounts"]
    host_observed: dict[str, Mapping[str, Any]] = {}
    for raw_mount in host_mounts:
        mount = _mapping(raw_mount, "Docker host mount")
        _require(
            set(mount) == {"Type", "Source", "Target", "ReadOnly"},
            "Docker host mount fields drifted",
        )
        destination = mount.get("Target")
        _require(
            type(destination) is str and destination not in host_observed,
            "Docker host mount target drifted",
        )
        _require(
            mount.get("Type") == "bind"
            and type(mount.get("Source")) is str
            and mount.get("ReadOnly") is True,
            f"Docker host readonly mount drifted: {destination}",
        )
        host_observed[destination] = mount
    runtime_observed: dict[str, Mapping[str, Any]] = {}
    mode_family: set[str] = set()
    for raw_mount in mounts:
        mount = _mapping(raw_mount, "Docker runtime mount")
        _require(
            set(mount)
            == {"Type", "Source", "Destination", "Mode", "RW", "Propagation"},
            "Docker runtime mount fields drifted",
        )
        destination = mount.get("Destination")
        _require(
            type(destination) is str and destination not in runtime_observed,
            "Docker runtime mount destination drifted",
        )
        mode = mount.get("Mode")
        _require(
            mount.get("Type") == "bind"
            and type(mount.get("Source")) is str
            and type(mode) is str
            and mode in {"", "ro"}
            and mount.get("RW") is False
            and mount.get("Propagation") == "rprivate",
            f"Docker runtime readonly mount drifted: {destination}",
        )
        mode_family.add(mode)
        runtime_observed[destination] = mount
    _require(
        len(mode_family) <= 1,
        "Docker runtime mount mode family is mixed",
    )
    _require(
        set(host_observed)
        == set(runtime_observed)
        == set(validated_expected_mounts),
        "Docker host/runtime mount destinations drifted",
    )
    for destination, expected_source in validated_expected_mounts.items():
        host_mount = host_observed[destination]
        runtime_mount = runtime_observed[destination]
        _require(
            host_mount.get("Source")
            == runtime_mount.get("Source")
            == expected_source,
            f"Docker host/runtime mount source drifted: {destination}",
        )
        _require(
            destination != "/var/run/docker.sock"
            and "docker.sock" not in expected_source,
            "Docker socket mounting is forbidden",
        )
    _require(expected_state in _KNOWN_CONTAINER_STATES, "expected Docker container state is invalid")
    _require(state.get("Status") == expected_state, "Docker container lifecycle state drifted")
    _require(
        state.get("Running") is (expected_state in _RUNNING_CONTAINER_STATES),
        "Docker container running state drifted",
    )
    if expected_state == "created":
        _require(
            type(state.get("Pid")) is int and state.get("Pid") == 0,
            "created Docker container unexpectedly has a PID",
        )
    elif expected_state in _RUNNING_CONTAINER_STATES:
        _require(
            type(state.get("Pid")) is int and 0 < state["Pid"] < 2**31,
            "running Docker container PID drifted",
        )
    return {
        "container_id": container_id,
        "container_name": container_name,
        "state": expected_state,
        "state_pid": state.get("Pid"),
        "native_readonly_mounts_attested": True,
        "container_image_entrypoint_identity_attested": True,
        "docker_desktop_wsl_distro_label_attested": (
            dict(actual_labels).get(_DOCKER_DESKTOP_WSL_DISTRO_LABEL)
            == _DOCKER_DESKTOP_WSL_DISTRO_VALUE
        ),
        "container_runtime": "runc",
    }


def _validate_successful_terminal_state(value: Any) -> dict[str, object]:
    state = _mapping(value, "successful Docker terminal state")
    _require(
        state.get("Status") == "exited"
        and state.get("Running") is False
        and state.get("Paused") is False
        and state.get("Restarting") is False
        and state.get("OOMKilled") is False
        and state.get("Dead") is False
        and type(state.get("Pid")) is int
        and state.get("Pid") == 0
        and type(state.get("ExitCode")) is int
        and state.get("ExitCode") == 0
        and type(state.get("Error")) is str
        and state.get("Error") == "",
        "Docker terminal state contradicts successful completion",
    )
    return dict(state)


def _mount(source: Path, destination: PurePosixPath, *, readonly: bool) -> str:
    mode = ",readonly" if readonly else ""
    return f"type=bind,src={source},dst={destination}{mode}"


def _build_worker_create_command(
    *,
    container_name: str,
    labels: Mapping[str, str],
    binding_source: Path,
    source_model: Path,
    engine: Path,
    socket_root: Path,
    socket_name: str,
) -> list[str]:
    """Build the closed Docker-create argv; it never executes Docker."""

    _require(
        _DOCKER_DESKTOP_WSL_DISTRO_LABEL not in labels,
        "Docker Desktop injected label is forbidden in create ownership input",
    )
    binding_destination = PurePosixPath("/run/vast/bindings") / binding_source.name
    source_destination = PurePosixPath("/run/vast/models") / source_model.name
    engine_destination = PurePosixPath("/run/vast/models") / engine.name
    command = [
        DOCKER_CLI,
        DOCKER_HOST_ARG,
        "container",
        "create",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--ipc=private",
        "--pids-limit=128",
        "--memory=4g",
        "--memory-swap=4g",
        "--cpus=2",
        "--ulimit=nofile=1024:1024",
        f"--user={CONTAINER_UID}:{CONTAINER_GID}",
        f"--name={container_name}",
    ]
    for key, value in sorted(labels.items()):
        command.append(f"--label={key}={value}")
    command.extend(
        [
            "--mount",
            _mount(binding_source, binding_destination, readonly=True),
            "--mount",
            _mount(source_model, source_destination, readonly=True),
            "--mount",
            _mount(engine, engine_destination, readonly=True),
            "--mount",
            _mount(socket_root, PurePosixPath("/run/vast/analytics"), readonly=True),
            "--gpus",
            f"device={TENSORRT_GPU_UUID}",
            f"--entrypoint={TENSORRT_ENTRYPOINT}",
            TENSORRT_IMAGE_ID,
            "--binding",
            str(binding_destination),
            "--socket",
            str(PurePosixPath("/run/vast/analytics") / socket_name),
            "--max-requests",
            "2",
            "--gpu-device-index",
            "0",
        ]
    )
    return command


def _build_probe_create_command(
    *,
    container_name: str,
    labels: Mapping[str, str],
) -> list[str]:
    _require(
        _DOCKER_DESKTOP_WSL_DISTRO_LABEL not in labels,
        "Docker Desktop injected label is forbidden in create ownership input",
    )
    command = [
        DOCKER_CLI,
        DOCKER_HOST_ARG,
        "container",
        "create",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--ipc=private",
        f"--pids-limit={CONTAINER_PIDS_LIMIT}",
        "--memory=4g",
        "--memory-swap=4g",
        "--cpus=2",
        "--ulimit=nofile=1024:1024",
        f"--user={CONTAINER_UID}:{CONTAINER_GID}",
        f"--name={container_name}",
    ]
    for key, value in sorted(labels.items()):
        command.append(f"--label={key}={value}")
    command.extend(
        [
            "--gpus",
            f"device={TENSORRT_GPU_UUID}",
            f"--entrypoint={TENSORRT_ENTRYPOINT}",
            TENSORRT_IMAGE_ID,
            "--capability",
            "--gpu-device-index",
            "0",
        ]
    )
    return command


def _container_inspect_capture(
    runner: CommandRunner,
    container_id: str,
) -> CommandCapture:
    return _run_read_only(
        runner,
        [
            DOCKER_CLI,
            DOCKER_HOST_ARG,
            "container",
            "inspect",
            "--format={{json .}}",
            container_id,
        ],
        label="owned Docker container inspect",
    )


def _is_exact_container_not_found(
    capture: CommandCapture,
    reference: str,
) -> bool:
    if (
        type(capture) is not CommandCapture
        or type(capture.returncode) is not int
        or type(capture.stdout) is not bytes
        or type(capture.stderr) is not bytes
        or type(reference) is not str
        or not reference
    ):
        return False
    try:
        legacy_container = (
            f"Error: No such container: {reference}\n".encode("ascii")
        )
        legacy_object = f"Error: No such object: {reference}\n".encode("ascii")
        docker29_container = (
            f"Error response from daemon: No such container: {reference}\n".encode(
                "ascii"
            )
        )
    except UnicodeEncodeError:
        return False
    return capture.returncode == 1 and (
        (capture.stdout, capture.stderr)
        in {
            (b"", legacy_container),
            (b"", legacy_object),
            (b"\n", docker29_container),
        }
    )


def _container_reference_absent(
    runner: CommandRunner,
    reference: str,
    *,
    stage: str,
) -> tuple[bool, CommandCapture]:
    listing = _run_read_only(
        runner,
        [
            DOCKER_CLI,
            DOCKER_HOST_ARG,
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--format={{json .}}",
        ],
        label="local Docker container inventory",
    )
    if listing.returncode != 0:
        raise _DockerOperationError(
            "local Docker container inventory failed",
            stage=stage,
            command_class="container_inventory",
            capture=listing,
        )
    if len(listing.stdout) > 1024 * 1024:
        raise _DockerOperationError(
            "local Docker container inventory overflowed",
            stage=stage,
            command_class="container_inventory",
            capture=listing,
        )
    for index, line in enumerate(listing.stdout.splitlines()):
        if not line:
            continue
        try:
            item = _parse_json(
                line, f"local Docker container inventory row {index}"
            )
            container_id = item.get("ID")
            names = item.get("Names")
            _require(
                type(container_id) is str and type(names) is str,
                "Docker container inventory row drifted",
            )
        except ExecutorContractError as error:
            raise _DockerOperationError(
                "local Docker container inventory response drifted",
                stage=stage,
                command_class="container_inventory",
                capture=listing,
            ) from error
        if container_id == reference or names == reference or names == f"/{reference}":
            return False, listing
    return True, listing


def _require_exact_absence_locked(
    runner: CommandRunner,
    capture: CommandCapture,
    reference: str,
    *,
    inventory_stage: str,
) -> None:
    if not _is_exact_container_not_found(capture, reference):
        raise _DockerOperationError(
            "owned Docker container inspect failed without an exact not-found result",
            stage=inventory_stage,
            command_class="container_inspect",
            capture=capture,
        )
    absent, listing = _container_reference_absent(
        runner,
        reference,
        stage=inventory_stage,
    )
    if not absent:
        raise _DockerOperationError(
            "owned Docker container remains in the daemon inventory",
            stage=inventory_stage,
            command_class="container_inventory",
            capture=listing,
        )


def _require_exact_absence(
    runner: CommandRunner,
    capture: CommandCapture,
    reference: str,
    *,
    cleanup_mutex: Any,
    inventory_stage: str,
) -> None:
    hold = getattr(cleanup_mutex, "hold", None)
    _require(callable(hold), "cleanup mutex interface drifted")
    with hold():
        _require_exact_absence_locked(
            runner,
            capture,
            reference,
            inventory_stage=inventory_stage,
        )


def _cleanup_owned_container(
    *,
    runner: CommandRunner,
    container_id: str,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
    cleanup_mutex: Any,
) -> None:
    hold = getattr(cleanup_mutex, "hold", None)
    _require(callable(hold), "cleanup mutex interface drifted")
    context = hold()
    _require(
        hasattr(context, "__enter__") and hasattr(context, "__exit__"),
        "cleanup mutex context drifted",
    )
    with context:
        _cleanup_owned_container_locked(
            runner=runner,
            container_id=container_id,
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_image_labels=expected_image_labels,
        )


def _cleanup_owned_container_locked(
    *,
    runner: CommandRunner,
    container_id: str,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> None:
    capture = _container_inspect_capture(runner, container_id)
    if capture.returncode != 0:
        _require_exact_absence_locked(
            runner,
            capture,
            container_id,
            inventory_stage="cleanup_inventory_existing_absence",
        )
        return
    document = _parse_json(capture.stdout, "owned Docker cleanup inspect")
    state_record = _mapping(document.get("State"), "owned Docker cleanup state")
    state = state_record.get("Status")
    _require(state in _KNOWN_CONTAINER_STATES, "owned Docker cleanup state is ambiguous")
    _validate_container_inspect(
        document,
        container_id=container_id,
        container_name=container_name,
        labels=labels,
        expected_mounts=expected_mounts,
        expected_state=str(state),
        expected_image_labels=expected_image_labels,
    )
    removed: CommandCapture | None = None
    remove_error: BaseException | None = None
    try:
        removed = runner.run(
            [
                DOCKER_CLI,
                DOCKER_HOST_ARG,
                "container",
                "rm",
                "--force",
                container_id,
            ],
            timeout_seconds=30.0,
            stdout_limit=64 * 1024,
            stderr_limit=64 * 1024,
        )
    except BaseException as error:
        remove_error = error
    postremove_error: BaseException | None = None
    absence_attested = False
    try:
        absent = _container_inspect_capture(runner, container_id)
        if absent.returncode != 0:
            _require_exact_absence_locked(
                runner,
                absent,
                container_id,
                inventory_stage="cleanup_inventory_after_remove",
            )
            absence_attested = True
        elif removed is not None and removed.returncode != 0:
            postremove_error = _DockerOperationError(
                "owned Docker container removal failed",
                stage="cleanup_remove",
                command_class="container_remove",
                capture=removed,
            )
        else:
            postremove_error = _DockerOperationError(
                "owned Docker container still exists after removal",
                stage="cleanup_postremove_inspect",
                command_class="container_inspect",
                capture=absent,
            )
    except BaseException as error:
        postremove_error = error
    if remove_error is not None and postremove_error is not None:
        raise _DescriptorClosureError(
            operation="owned_container_remove_and_poststate",
            primary=remove_error,
            close_failures=[postremove_error],
            message="owned-container removal and poststate attestation failed",
        ) from remove_error
    if remove_error is not None:
        raise remove_error
    if postremove_error is not None:
        raise postremove_error
    _require(absence_attested, "owned-container absence was not attested")


def _recover_owned_container_by_name_locked(
    *,
    runner: CommandRunner,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> str | None:
    capture = _container_inspect_capture(runner, container_name)
    if capture.returncode != 0:
        _require_exact_absence_locked(
            runner,
            capture,
            container_name,
            inventory_stage="recovery_inventory_absence",
        )
        return None
    document = _parse_json(capture.stdout, "owned Docker name recovery inspect")
    container_id = document.get("Id")
    _require(
        type(container_id) is str
        and _CONTAINER_ID_RE.fullmatch(container_id) is not None,
        "owned Docker name recovery returned an invalid container ID",
    )
    state = _mapping(document.get("State"), "owned Docker name recovery state").get("Status")
    _require(state in _KNOWN_CONTAINER_STATES, "owned Docker name recovery state is ambiguous")
    _validate_container_inspect(
        document,
        container_id=container_id,
        container_name=container_name,
        labels=labels,
        expected_mounts=expected_mounts,
        expected_state=str(state),
        expected_image_labels=expected_image_labels,
    )
    return container_id


def _recover_owned_container_by_name(
    *,
    runner: CommandRunner,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    cleanup_mutex: Any,
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> str | None:
    hold = getattr(cleanup_mutex, "hold", None)
    _require(callable(hold), "cleanup mutex interface drifted")
    with hold():
        return _recover_owned_container_by_name_locked(
            runner=runner,
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_image_labels=expected_image_labels,
        )


def _recover_and_cleanup_owned_container_by_name(
    *,
    runner: CommandRunner,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    cleanup_mutex: Any,
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> str | None:
    hold = getattr(cleanup_mutex, "hold", None)
    _require(callable(hold), "cleanup mutex interface drifted")
    with hold():
        recovered: str | None = None
        primary: BaseException | None = None
        try:
            recovered = _recover_owned_container_by_name_locked(
                runner=runner,
                container_name=container_name,
                labels=labels,
                expected_mounts=expected_mounts,
                expected_image_labels=expected_image_labels,
            )
            if recovered is not None:
                _cleanup_owned_container_locked(
                    runner=runner,
                    container_id=recovered,
                    container_name=container_name,
                    labels=labels,
                    expected_mounts=expected_mounts,
                    expected_image_labels=expected_image_labels,
                )
        except BaseException as error:
            primary = error
        final_error: BaseException | None = None
        try:
            final = _container_inspect_capture(runner, container_name)
            _require_exact_absence_locked(
                runner,
                final,
                container_name,
                inventory_stage="recovery_inventory_absence",
            )
        except BaseException as error:
            final_error = error
        if primary is not None and final_error is not None:
            raise _DescriptorClosureError(
                operation="owned_container_recovery_final_absence",
                primary=primary,
                close_failures=[final_error],
                message="owned-container recovery and final absence attestation failed",
            ) from primary
        if primary is not None:
            raise primary
        if final_error is not None:
            raise final_error
        return recovered


def _take_over_dead_container_watchdog_cleanup(
    *,
    runner: CommandRunner,
    watchdog: _ContainerWatchdogProcess,
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    cleanup_mutex: Any,
    expected_image_labels: Mapping[str, str],
) -> bool:
    """Resolve a dead child's marker only after exact controller cleanup."""

    _require(
        type(watchdog) is _ContainerWatchdogProcess,
        "container watchdog takeover type drifted",
    )
    if not (
        watchdog.closed
        and watchdog.create_dispatch_marked
        and watchdog.create_terminal_marked
        and not watchdog.ambiguous_owner_detached
        and type(watchdog.terminal_returncode) is int
        and watchdog.terminal_returncode != 0
        and watchdog.cleanup_ownership_retained is False
        and isinstance(watchdog.unresolved_operation_contract, Mapping)
    ):
        return False
    contract = _validate_unresolved_operation_contract(
        watchdog.unresolved_operation_contract
    )
    _require(
        contract.get("operation_kind") == "container_create"
        and contract.get("operation_id") == container_name
        and contract.get("run_identity_sha256") == labels.get(RUN_LABEL),
        "dead container watchdog takeover contract drifted",
    )
    _validate_container_watchdog_name_binding(container_name, labels)
    _recover_and_cleanup_owned_container_by_name(
        runner=runner,
        container_name=container_name,
        labels=labels,
        expected_mounts=expected_mounts,
        cleanup_mutex=cleanup_mutex,
        expected_image_labels=expected_image_labels,
    )
    _resolve_or_attest_unresolved_operation_marker(contract)
    return True


def _run_owned_container_transaction(
    *,
    runner: CommandRunner,
    create_command: list[str],
    container_name: str,
    labels: Mapping[str, str],
    expected_mounts: Mapping[str, Path],
    after_start: Callable[[str], Any],
    cleanup_mutex: Any,
    container_registry: _OwnedContainerRegistry | None = None,
    watchdog_factory: Callable[..., _ContainerWatchdog] | None = None,
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
    allowed_started_states: tuple[str, ...] = ("running",),
    failure_phase: str = "worker_execution",
    failure_stage: str = "worker_orchestration",
) -> dict[str, Any]:
    """Create one owned daemon object and remove it on every Python exit path."""

    _require(
        failure_phase in {"mutating_preworker", "worker_execution"}
        and failure_stage in {"gpu_probe", "worker_orchestration"}
        and (
            (failure_phase == "mutating_preworker")
            is (failure_stage == "gpu_probe")
        ),
        "owned container failure context drifted",
    )
    watchdog = (
        _NullContainerWatchdog()
        if watchdog_factory is None
        else watchdog_factory(
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_image_labels=expected_image_labels,
        )
    )
    container_id: str | None = None
    primary: BaseException | None = None
    body_succeeded = False
    create_terminal_attested = False
    try:
        hold = getattr(cleanup_mutex, "hold", None)
        _require(callable(hold), "cleanup mutex interface drifted")
        with hold():
            initial = _container_inspect_capture(runner, container_name)
            _require(
                initial.returncode != 0,
                "owned Docker container name is not fresh",
            )
            _require_exact_absence_locked(
                runner,
                initial,
                container_name,
                inventory_stage="initial_freshness_inventory",
            )
        watchdog.mark_create_dispatch()
        created = runner.run(
            list(create_command),
            timeout_seconds=60.0,
            stdout_limit=64 * 1024,
            stderr_limit=64 * 1024,
        )
        creation_error: ExecutorContractError | None = None
        if created.returncode != 0:
            creation_error = _DockerOperationError(
                "owned Docker container creation failed",
                stage="container_create",
                command_class="container_create",
                capture=created,
            )
        else:
            try:
                candidate_text = created.stdout.decode("ascii")
            except UnicodeError:
                candidate_text = ""
            candidate_id = (
                candidate_text[:-1]
                if candidate_text.endswith("\n")
                else ""
            )
            if (
                _CONTAINER_ID_RE.fullmatch(candidate_id) is None
                or created.stdout != (candidate_id + "\n").encode("ascii")
                or created.stderr != b""
            ):
                creation_error = _DockerOperationError(
                    "Docker create returned an invalid container ID",
                    stage="container_create",
                    command_class="container_create",
                    capture=created,
                )
            else:
                container_id = candidate_id
                # Strict rc0 + empty stderr + exact lowercase-hex ID/LF is the
                # only terminal daemon-response authority.  Any other capture
                # remains D&&!T; neither controller nor child may promote a
                # one-shot absence to commit completion.
                watchdog.mark_create_terminal()
                create_terminal_attested = True
                if container_registry is not None:
                    container_registry.record(container_name, container_id)
        if creation_error is not None:
            # D&&!T cleanup belongs exclusively to the retained watchdog.  A
            # controller recovery pass could remove an already-published
            # object before the watcher positively observes it, leaving the
            # watcher unable to distinguish completion from a future commit.
            raise creation_error
        _require(container_id is not None, "Docker create did not bind a container ID")
        pre_capture = _container_inspect_capture(runner, container_id)
        _require(pre_capture.returncode == 0, "created Docker container cannot be inspected")
        pre_document = _parse_json(pre_capture.stdout, "created Docker container inspect")
        _validate_container_inspect(
            pre_document,
            container_id=container_id,
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_state="created",
            expected_image_labels=expected_image_labels,
        )
        started = runner.run(
            [DOCKER_CLI, DOCKER_HOST_ARG, "container", "start", container_id],
            timeout_seconds=30.0,
            stdout_limit=64 * 1024,
            stderr_limit=64 * 1024,
        )
        _require(started.returncode == 0, "owned Docker container start failed")
        running_capture = _container_inspect_capture(runner, container_id)
        _require(running_capture.returncode == 0, "started Docker container cannot be inspected")
        running_document = _parse_json(
            running_capture.stdout, "started Docker container inspect"
        )
        started_state = _mapping(
            running_document.get("State"), "started Docker container state"
        ).get("Status")
        _require(
            type(started_state) is str and started_state in allowed_started_states,
            "started Docker container entered an unexpected state",
        )
        _validate_container_inspect(
            running_document,
            container_id=container_id,
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_state=started_state,
            expected_image_labels=expected_image_labels,
        )
        action = after_start(container_id)
        waited = runner.run(
            [DOCKER_CLI, DOCKER_HOST_ARG, "container", "wait", container_id],
            timeout_seconds=180.0,
            stdout_limit=64 * 1024,
            stderr_limit=64 * 1024,
        )
        _require(waited.returncode == 0, "owned Docker container wait failed")
        try:
            exit_code = int(waited.stdout.decode("ascii").strip())
        except (UnicodeError, ValueError) as error:
            raise ExecutorContractError("Docker wait returned an invalid exit code") from error
        logs = runner.run(
            [DOCKER_CLI, DOCKER_HOST_ARG, "container", "logs", container_id],
            timeout_seconds=30.0,
            stdout_limit=1024 * 1024,
            stderr_limit=1024 * 1024,
        )
        _require(logs.returncode == 0, "owned Docker container log capture failed")
        post_capture = _container_inspect_capture(runner, container_id)
        _require(post_capture.returncode == 0, "finished Docker container cannot be inspected")
        post_document = _parse_json(post_capture.stdout, "finished Docker container inspect")
        _validate_container_inspect(
            post_document,
            container_id=container_id,
            container_name=container_name,
            labels=labels,
            expected_mounts=expected_mounts,
            expected_state="exited",
            expected_image_labels=expected_image_labels,
        )
        post_state = _mapping(post_document.get("State"), "finished Docker state")
        _require(exit_code == 0, "owned Docker container exited nonzero")
        _validate_successful_terminal_state(post_state)
        result = {
            "container_id": container_id,
            "container_name": container_name,
            "action": action,
            "stdout": logs.stdout,
            "stderr": logs.stderr,
            "preinspect_sha256": hashlib.sha256(canonical_line(pre_document)).hexdigest(),
            "running_inspect_sha256": hashlib.sha256(
                canonical_line(running_document)
            ).hexdigest(),
            "postinspect_sha256": hashlib.sha256(canonical_line(post_document)).hexdigest(),
        }
        body_succeeded = True
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_error: BaseException | None = None
        if container_id is not None and create_terminal_attested:
            try:
                _cleanup_owned_container(
                    runner=runner,
                    container_id=container_id,
                    container_name=container_name,
                    labels=labels,
                    expected_mounts=expected_mounts,
                    cleanup_mutex=cleanup_mutex,
                    expected_image_labels=expected_image_labels,
                )
            except BaseException as error:
                cleanup_error = error
        watchdog_error: BaseException | None = None
        try:
            if (
                isinstance(watchdog, _ContainerWatchdogProcess)
                and not create_terminal_attested
                and watchdog.create_dispatch_marked
            ):
                # D&&!T custody must survive the controller/wrapper process
                # group hard wall.  Close only the control pipe, prove the
                # independent-session guardian is still alive, and return
                # without waiting or killing it.  The guardian keeps its own
                # global retention SH lock and durable unresolved marker.
                watchdog.detach_ambiguous_owner()
            elif body_succeeded and cleanup_error is None:
                watchdog.complete()
            else:
                watchdog.abort()
        except BaseException as error:
            watchdog_error = error
        watchdog_takeover_error: BaseException | None = None
        if isinstance(watchdog, _ContainerWatchdogProcess):
            try:
                _take_over_dead_container_watchdog_cleanup(
                    runner=runner,
                    watchdog=watchdog,
                    container_name=container_name,
                    labels=labels,
                    expected_mounts=expected_mounts,
                    cleanup_mutex=cleanup_mutex,
                    expected_image_labels=expected_image_labels,
                )
            except BaseException as error:
                watchdog_takeover_error = error
        if (
            cleanup_error is not None
            or watchdog_error is not None
            or watchdog_takeover_error is not None
        ):
            branch_value = labels.get(BRANCH_LABEL)
            failure_branch = (
                str(branch_value) if branch_value in BRANCHES else None
            )
            cleanup_items: list[_SupplementalExecutionFailure] = []
            if cleanup_error is not None:
                cleanup_items.append(
                    _SupplementalExecutionFailure(
                        scope="controller_container_cleanup",
                        phase="final_cleanup",
                        stage="controller_container_cleanup",
                        branch=failure_branch,
                        error=cleanup_error,
                    )
                )
            if watchdog_error is not None:
                cleanup_items.append(
                    _SupplementalExecutionFailure(
                        scope="container_watchdog_cleanup",
                        phase="final_cleanup",
                        stage="container_watchdog_cleanup",
                        branch=failure_branch,
                        error=watchdog_error,
                    )
                )
            if watchdog_takeover_error is not None:
                cleanup_items.append(
                    _SupplementalExecutionFailure(
                        scope="container_watchdog_takeover_cleanup",
                        phase="final_cleanup",
                        stage="container_watchdog_takeover_cleanup",
                        branch=failure_branch,
                        error=watchdog_takeover_error,
                    )
                )
            if isinstance(primary, _ExecutionFailureBundle):
                raise _ExecutionFailureBundle(
                    primary=primary.primary,
                    primary_phase=primary.primary_phase,
                    primary_stage=primary.primary_stage,
                    primary_branch=primary.primary_branch,
                    supplemental_failures=[
                        *primary.supplemental_failures,
                        *cleanup_items,
                    ],
                )
            if primary is not None:
                raise _ExecutionFailureBundle(
                    primary=primary,
                    primary_phase=failure_phase,
                    primary_stage=failure_stage,
                    primary_branch=failure_branch,
                    supplemental_failures=cleanup_items,
                )
            first, *remaining = cleanup_items
            raise _ExecutionFailureBundle(
                primary=first.error,
                primary_phase="final_cleanup",
                primary_stage=first.stage,
                primary_branch=first.branch,
                supplemental_failures=remaining,
            )


def _probe_exact_gpu(
    *,
    runner: CommandRunner,
    run_identity: str,
    cleanup_mutex: Any,
    container_registry: _OwnedContainerRegistry,
    watchdog_factory: Callable[..., _ContainerWatchdog] | None = None,
    expected_image_labels: Mapping[str, str] = IMAGE_LABELS,
) -> dict[str, object]:
    _require(_SHA_RE.fullmatch(run_identity) is not None, "GPU probe run identity is invalid")
    name = f"vast-kpp-v2-np-{run_identity[:16]}-probe"
    labels = {
        OWNER_LABEL: OWNER_VALUE,
        RUN_LABEL: run_identity,
        BRANCH_LABEL: "runtime_probe",
    }
    transaction = _run_owned_container_transaction(
        runner=runner,
        create_command=_build_probe_create_command(
            container_name=name,
            labels=labels,
        ),
        container_name=name,
        labels=labels,
        expected_mounts={},
        after_start=lambda _container_id: None,
        cleanup_mutex=cleanup_mutex,
        container_registry=container_registry,
        watchdog_factory=watchdog_factory,
        expected_image_labels=expected_image_labels,
        allowed_started_states=("running", "exited"),
        failure_phase="mutating_preworker",
        failure_stage="gpu_probe",
    )
    probe = _validate_gpu_probe_document(
        _parse_json(transaction["stdout"], "TensorRT GPU runtime probe")
    )
    _require(probe["device_id"] == TENSORRT_GPU_UUID, "TensorRT GPU UUID differs from the frozen pilot pin")
    _require(probe["runtime_version"] == "8.6.1.6", "TensorRT runtime version differs from the engine pin")
    _require(
        probe["worker_implementation_sha256"]
        == TENSORRT_WORKER_IMPLEMENTATION_SHA256,
        "TensorRT worker implementation differs from the frozen image pin",
    )
    core: dict[str, object] = {
        "engine": ENGINE_TENSORRT_CUDA,
        "runtime_name": probe["runtime_name"],
        "runtime_version": probe["runtime_version"],
        "device_api": probe["device_api"],
        "device_id": probe["device_id"],
        "worker_implementation_sha256": probe["worker_implementation_sha256"],
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "preinspect_sha256": transaction["preinspect_sha256"],
        "postinspect_sha256": transaction["postinspect_sha256"],
        "container_id_sha256": hashlib.sha256(
            str(transaction["container_id"]).encode("ascii")
        ).hexdigest(),
        "gpu_name_pin": "NVIDIA GeForce RTX 3060",
        "compute_capability_pin": "8.6",
        "driver_version_pin": "610.47",
        "gpu_name_observed_by_executor": False,
        "compute_capability_observed_by_executor": False,
        "driver_version_observed_by_executor": False,
    }
    return {
        **core,
        "validated_runtime_probe": probe,
        "observation_sha256": hashlib.sha256(canonical_line(core)).hexdigest(),
    }


def _validate_gpu_probe_document(value: Any) -> dict[str, Any]:
    probe = _mapping(value, "TensorRT GPU runtime probe")
    fields = {
        "schema_version",
        "artifact_kind",
        "protocol_identity_sha256",
        "engine",
        "runtime_name",
        "runtime_version",
        "device_api",
        "device_id",
        "native_inference_api",
        "execution_path",
        "worker_implementation_sha256",
        "socket_seqpacket",
        "scm_rights",
        "memfd_sealing",
        "model_loaded",
        "inference_performed",
    }
    _require(set(probe) == fields, "TensorRT GPU runtime probe fields drifted")
    _require(
        probe.get("schema_version") == 1
        and probe.get("artifact_kind")
        == "vast_analytics_execution_worker_runtime_probe",
        "TensorRT GPU runtime probe header drifted",
    )
    _require(
        probe.get("protocol_identity_sha256") == PROTOCOL_IDENTITY_SHA256,
        "TensorRT GPU runtime probe protocol drifted",
    )
    _require(
        probe.get("engine") == ENGINE_TENSORRT_CUDA
        and probe.get("runtime_name") == "TensorRT"
        and probe.get("device_api") == "NVIDIA_CUDA"
        and probe.get("native_inference_api")
        == "nvinfer1::IExecutionContext::enqueueV3"
        and probe.get("execution_path") == "tensorrt_cuda_native",
        "TensorRT GPU runtime probe execution path drifted",
    )
    _require(
        all(probe.get(field) is True for field in ("socket_seqpacket", "scm_rights", "memfd_sealing")),
        "TensorRT GPU runtime probe IPC primitives are incomplete",
    )
    _require(
        probe.get("model_loaded") is False
        and probe.get("inference_performed") is False,
        "TensorRT capability probe unexpectedly executed a model",
    )
    return dict(probe)


class _ExecutorArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ExecutorContractError("executor command line is invalid")


def _build_parser() -> argparse.ArgumentParser:
    parser = _ExecutorArgumentParser(
        description="Run the KPP v2 TensorRT secondary/sensitivity nonpublication pilot."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--decision-path", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--role", choices=("secondary", "sensitivity"), required=True)
    parser.add_argument("--expected-receipt-file-sha256", required=True)
    parser.add_argument("--expected-receipt-self-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-docker-cli-size-bytes", type=int, required=True)
    parser.add_argument("--expected-docker-cli-sha256", required=True)
    parser.add_argument("--expected-daemon-id", required=True)
    parser.add_argument("--expected-daemon-server-version", required=True)
    parser.add_argument("--expected-daemon-api-version", required=True)
    parser.add_argument(
        "--peer-identity-mode",
        choices=PEER_IDENTITY_MODES,
        default=PEER_IDENTITY_MODE_NATIVE_VISIBLE,
        help=(
            "select the closed normal-mode SO_PEERCRED identity policy; "
            "the namespace-hidden mode is Docker Desktop/WSL2-specific"
        ),
    )
    parser.add_argument(
        "--diagnostic-so-peercred-only",
        action="store_true",
        default=False,
        help=(
            "collect closed SO_PEERCRED diagnostics and always stop before "
            "the capability handshake or inference"
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    _dependencies: _ExecutorDependencies | None = None,
    _stdout: Any = None,
) -> int:
    role = "secondary"
    diagnostic_so_peercred_only = False
    peer_identity_mode = PEER_IDENTITY_MODE_NATIVE_VISIBLE
    try:
        args = _build_parser().parse_args(argv)
        role = args.role
        diagnostic_so_peercred_only = args.diagnostic_so_peercred_only
        peer_identity_mode = args.peer_identity_mode
        artifact, status = execute_nonpublication_pilot(
            project_root=args.project_root,
            decision_path=args.decision_path,
            candidate_root=args.candidate_root,
            role=args.role,
            expected_receipt_file_sha256=args.expected_receipt_file_sha256,
            expected_receipt_self_sha256=args.expected_receipt_self_sha256,
            run_id=args.run_id,
            expected_docker_cli_size_bytes=args.expected_docker_cli_size_bytes,
            expected_docker_cli_sha256=args.expected_docker_cli_sha256,
            expected_daemon_id=args.expected_daemon_id,
            expected_daemon_server_version=args.expected_daemon_server_version,
            expected_daemon_api_version=args.expected_daemon_api_version,
            diagnostic_so_peercred_only=diagnostic_so_peercred_only,
            peer_identity_mode=peer_identity_mode,
            _dependencies=_dependencies,
        )
    except Exception as error:
        postexecution_escape = isinstance(error, _ExecutionFailureBundle)
        artifact = _blocked_artifact(
            role=role,
            status=(
                "blocked_executor_postexecution_contract_error"
                if postexecution_escape
                else "blocked_executor_contract_error"
            ),
            blocker=(
                "postexecution validation, cleanup, or failure reporting failed"
                if postexecution_escape
                else "executor contract validation or cleanup failed"
            ),
            runtime=(
                {
                    "diagnostic_so_peercred_only": True,
                    "capability_handshake_performed": False,
                    "peer_credentials_accepted_for_inference": False,
                    "inference_performed": False,
                }
                if diagnostic_so_peercred_only
                else {
                    "inference_performed": None,
                    "inference_performed_attested": False,
                    "operational_completion_observed": False,
                    "execution_phase_attested": (
                        "postexecution" if postexecution_escape else None
                    ),
                }
            ),
            claim_status=(
                "diagnostic_only_blocked_nonpublication_not_evidence"
                if diagnostic_so_peercred_only
                else (
                    "postexecution_failure_reporting_degraded_nonpublication_not_acceptance"
                    if postexecution_escape
                    else "blocked_nonpublication_execution_phase_unknown_not_acceptance"
                )
            ),
        )
        status = 78
    output = sys.stdout.buffer if _stdout is None else _stdout
    try:
        payload = canonical_line(artifact)
        written = output.write(payload)
        if type(written) is not int or written != len(payload):
            return 78
        output.flush()
    except BaseException:
        return 78
    return status


__all__ = ["TENSORRT_GPU_UUID", "TENSORRT_IMAGE_ID"]


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "__owned_ipc_watchdog_v3":
        try:
            ipc_control_fd = int(sys.argv[2])
            ipc_ack_fd = int(sys.argv[3])
        except ValueError:
            raise SystemExit(78)
        raise SystemExit(
            _owned_ipc_watchdog_main(
                ipc_control_fd,
                ipc_ack_fd,
                sys.argv[4],
                Path(sys.argv[5]),
            )
        )
    if len(sys.argv) == 4 and sys.argv[1] == "__owned_container_watchdog_v4":
        try:
            watchdog_fd = int(sys.argv[2])
            watchdog_ready_fd = int(sys.argv[3])
        except ValueError:
            raise SystemExit(78)
        raise SystemExit(
            _owned_container_watchdog_main(watchdog_fd, watchdog_ready_fd)
        )
    raise SystemExit(main())
