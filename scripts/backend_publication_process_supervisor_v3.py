#!/usr/bin/env python3
"""Bounded, non-authorizing process supervisor for publication ABI v3."""

from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import json
import math
import os
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)


SCHEMA_VERSION = 3
OBSERVATION_KIND = "vast_backend_publication_process_observation_v3"
OBSERVATION_DOMAIN = b"VAST:backend-publication-process-observation:v3\0"
READER_THREAD_PREFIX = "backend-publication-v3-reader-"
OBSERVATION_STATUSES = (
    "succeeded",
    "exit_nonzero",
    "timed_out",
    "stdout_overflow",
    "stderr_overflow",
    "capture_overflow",
    "capture_failed",
    "process_tree_not_quiescent",
)
OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "platform_family",
        "argv_sha256",
        "cwd",
        "exit_code",
        "stdout_size_bytes",
        "stdout_sha256",
        "stderr_size_bytes",
        "stderr_sha256",
        "timeout_ms",
        "max_stdout_bytes",
        "max_stderr_bytes",
        "timed_out",
        "stdout_overflow",
        "stderr_overflow",
        "termination_attempted",
        "termination_escalated",
        "process_tree_quiescent",
        "unexpected_live_descendant_detected",
        "active_processes_after_cleanup",
        "create_suspended",
        "job_kill_on_close",
        "job_assigned_before_resume",
        "start_new_session",
        "posix_child_subreaper",
        "posix_pidfd_descendant_cleanup",
        "posix_isolated_broker",
        "shell",
        "environment",
        "stdin",
        "close_fds",
        "publication_execution_authorized",
        "observation_sha256",
    }
)

_ARGV_LABELS = {
    2: "--project-root",
    4: "--arm-contract",
    6: "--arm-contract-sha256",
    8: "--output-dir",
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CAPTURE_CHUNK_BYTES = 64 * 1024
_MONITOR_INTERVAL_SECONDS = 0.01
_PIPE_JOIN_GRACE_SECONDS = 2.0
_TERMINATION_GRACE_SECONDS = 1.0
_FINAL_QUIESCENCE_GRACE_SECONDS = 1.0
_CREATE_SUSPENDED = 0x00000004
_PR_SET_CHILD_SUBREAPER = 36
_PR_GET_CHILD_SUBREAPER = 37
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4
_PR_SET_PDEATHSIG = 1
_PR_GET_PDEATHSIG = 2
_PR_CAPBSET_DROP = 24
_PR_SET_SECUREBITS = 28
_PR_SET_NO_NEW_PRIVS = 38
_PR_CAP_AMBIENT = 47
_PR_CAP_AMBIENT_CLEAR_ALL = 4
_LINUX_SECUREBITS_LOCKED_NO_PRIVILEGE_GAIN = 0xEF
_LINUX_CAPABILITY_VERSION_3 = 0x20080522
_MS_PRIVATE = 1 << 18
_MS_REC = 1 << 14
_MS_NOSUID = 2
_MS_NODEV = 4
_MS_NOEXEC = 8
_POSIX_SCOPE_LOCK = threading.Lock()
_POSIX_BROKER_MODE = "--internal-posix-process-broker-v3"
_POSIX_BROKER_REQUEST_KIND = "vast_backend_publication_posix_broker_request_v3"
_POSIX_BROKER_RESPONSE_KIND = "vast_backend_publication_posix_broker_response_v3"
_POSIX_BROKER_REQUEST_DOMAIN = b"VAST:backend-publication-posix-broker-request:v3\0"
_POSIX_BROKER_RESPONSE_DOMAIN = b"VAST:backend-publication-posix-broker-response:v3\0"
_POSIX_BROKER_FRAME_MAGIC = b"VASTBPS3\0"
_POSIX_BROKER_REQUEST_MAGIC = b"VASTBPR3\0"
_POSIX_BROKER_MAX_REQUEST_BYTES = 64 * 1024
_POSIX_BROKER_MAX_HEADER_BYTES = 128 * 1024
_POSIX_BROKER_MAX_DIAGNOSTIC_BYTES = 64 * 1024
_POSIX_BROKER_CLEANUP_MARGIN_MS = 15_000
_POSIX_BROKER_TERMINATION_GRACE_SECONDS = 12.0

_FROZEN_INVOCATION = validate_publication_launcher_invocation_v3(
    publication_launcher_invocation_v3_contract()
)
_FROZEN_PROCESS = _FROZEN_INVOCATION["process_contract"]
_PROCESS_TIMEOUT_MS = int(_FROZEN_PROCESS["timeout_ms"])
_MAX_STDOUT_BYTES = int(_FROZEN_PROCESS["max_stdout_bytes"])
_MAX_STDERR_BYTES = int(_FROZEN_PROCESS["max_stderr_bytes"])


class BackendPublicationProcessSupervisorV3Error(RuntimeError):
    """The exact v3 process run failed or could not be contained."""

    def __init__(
        self,
        message: str,
        *,
        observation: dict[str, Any] | None = None,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        super().__init__(message)
        self._observation = (
            None if observation is None else copy.deepcopy(observation)
        )
        self._stdout = bytes(stdout)
        self._stderr = bytes(stderr)

    @property
    def observation(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._observation)

    @property
    def stdout(self) -> bytes:
        return self._stdout

    @property
    def stderr(self) -> bytes:
        return self._stderr


@dataclass(frozen=True, slots=True)
class BackendPublicationProcessRunV3:
    stdout: bytes
    stderr: bytes
    observation: dict[str, Any]

    def __getattribute__(self, name: str) -> Any:
        value = object.__getattribute__(self, name)
        if name == "observation":
            return copy.deepcopy(value)
        return value

    def __post_init__(self) -> None:
        object.__setattr__(self, "stdout", bytes(self.stdout))
        object.__setattr__(self, "stderr", bytes(self.stderr))
        object.__setattr__(self, "observation", copy.deepcopy(self.observation))


@dataclass(frozen=True, slots=True)
class _MonitorOutcome:
    exit_code: int | None
    timed_out: bool
    capture_failed: bool


@dataclass(frozen=True, slots=True)
class _CleanupOutcome:
    termination_attempted: bool
    termination_escalated: bool
    quiescent: bool
    active_processes: int | None


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process value is not canonical JSON"
        ) from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _raw_path_has_dot_segment(value: str) -> bool:
    return any(component in {".", ".."} for component in re.split(r"[\\/]", value))


def _canonical_existing_path(
    value: str, *, label: str, directory: bool
) -> Path:
    path = Path(value)
    if (
        not path.is_absolute()
        or value.startswith(("\\\\", "//"))
        or _raw_path_has_dot_segment(value)
        or os.path.normpath(value) != value
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            f"{label} must be an absolute canonical path"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            f"{label} cannot be resolved"
        ) from exc
    if _normalized_path(value) != _normalized_path(str(resolved)):
        raise BackendPublicationProcessSupervisorV3Error(
            f"{label} must be an absolute canonical path"
        )
    matches_kind = resolved.is_dir() if directory else resolved.is_file()
    if not matches_kind:
        kind = "directory" if directory else "file"
        raise BackendPublicationProcessSupervisorV3Error(
            f"{label} must be an existing {kind}"
        )
    return resolved


def _validate_invocation(
    argv: Sequence[str], cwd: Path
) -> tuple[tuple[str, ...], Path]:
    if type(argv) not in {list, tuple} or len(argv) != 10:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process argv must contain exactly 10 tokens"
        )
    command = tuple(argv)
    if any(
        type(item) is not str or not item or "\x00" in item
        for item in command
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process argv tokens are invalid"
        )
    for index, label in _ARGV_LABELS.items():
        if command[index] != label:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process argv labels drifted"
            )
    if _SHA256_RE.fullmatch(command[7]) is None:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process contract SHA-256 is invalid"
        )
    if not isinstance(cwd, Path):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process cwd must be a Path"
        )
    canonical_cwd = _canonical_existing_path(
        str(cwd), label="backend publication process cwd", directory=True
    )
    executable = _canonical_existing_path(
        command[0], label="Python executable", directory=False
    )
    launcher = _canonical_existing_path(
        command[1], label="publication launcher", directory=False
    )
    project_root = _canonical_existing_path(
        command[3], label="project root", directory=True
    )
    arm_contract = _canonical_existing_path(
        command[5], label="arm contract", directory=False
    )
    output_dir = _canonical_existing_path(
        command[9], label="output directory", directory=True
    )
    if canonical_cwd != project_root:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process cwd must equal argv project root"
        )
    canonical_command = (
        str(executable),
        str(launcher),
        command[2],
        str(project_root),
        command[4],
        str(arm_contract),
        command[6],
        command[7],
        command[8],
        str(output_dir),
    )
    if tuple(map(_normalized_path, canonical_command)) != tuple(
        map(_normalized_path, command)
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process argv paths are not canonical"
        )
    return command, canonical_cwd


class _BoundedPipeReader:
    def __init__(self, *, name: str, pipe: BinaryIO, limit: int) -> None:
        self.name = name
        self.pipe = pipe
        self.limit = limit
        self.buffer = bytearray()
        self.overflow = False
        self.eof = False
        self.error: BaseException | None = None
        self.stop_requested = False
        self.started = False
        self.event = threading.Event()
        self.thread = threading.Thread(
            target=self._drain,
            name=f"{READER_THREAD_PREFIX}{name}",
            daemon=False,
        )

    def start(self) -> None:
        try:
            self.thread.start()
        finally:
            self.started = self.thread.ident is not None

    def _drain(self) -> None:
        try:
            descriptor = self.pipe.fileno()
            while not self.stop_requested:
                remaining = self.limit - len(self.buffer)
                requested = min(_CAPTURE_CHUNK_BYTES, remaining + 1)
                block = os.read(descriptor, requested)
                if not block:
                    self.eof = True
                    break
                accepted = min(remaining, len(block))
                if accepted:
                    self.buffer.extend(block[:accepted])
                if accepted != len(block):
                    self.overflow = True
                    break
        except BaseException as exc:
            if not self.stop_requested:
                self.error = exc
        finally:
            self.event.set()

    def stop(self) -> None:
        self.stop_requested = True
        try:
            self.pipe.close()
        except BaseException:
            pass
        self.event.set()

    def join(self, timeout: float) -> None:
        if self.started:
            self.thread.join(max(0.0, timeout))

    def payload(self) -> bytes:
        return bytes(self.buffer)


def _readers_have_failure(readers: Sequence[_BoundedPipeReader]) -> bool:
    return any(
        reader.overflow or reader.error is not None for reader in readers
    )


def _wait_readers(
    readers: Sequence[_BoundedPipeReader], *, grace_seconds: float
) -> bool:
    deadline = time.monotonic() + grace_seconds
    for reader in readers:
        reader.join(deadline - time.monotonic())
    return all(not reader.thread.is_alive() for reader in readers)


def _stop_readers(readers: Sequence[_BoundedPipeReader]) -> None:
    for reader in readers:
        reader.stop()
    _wait_readers(readers, grace_seconds=_PIPE_JOIN_GRACE_SECONDS)


def _monitor_process_v3(
    process: subprocess.Popen[bytes],
    readers: Sequence[_BoundedPipeReader],
    *,
    timeout_ms: int,
) -> _MonitorOutcome:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while True:
        if _readers_have_failure(readers):
            return _MonitorOutcome(
                exit_code=process.poll(),
                timed_out=False,
                capture_failed=any(reader.error is not None for reader in readers),
            )
        exit_code = process.poll()
        if exit_code is not None:
            return _MonitorOutcome(
                exit_code=exit_code,
                timed_out=False,
                capture_failed=False,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _MonitorOutcome(
                exit_code=None,
                timed_out=True,
                capture_failed=False,
            )
        readers[0].event.wait(min(_MONITOR_INTERVAL_SECONDS, remaining))
        for reader in readers:
            reader.event.clear()


class _WindowsJob:
    def __init__(self) -> None:
        if os.name != "nt":
            raise BackendPublicationProcessSupervisorV3Error(
                "Windows Job Object requested on a non-Windows platform"
            )
        from ctypes import wintypes

        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle: int | None = None
        self.assigned_before_resume = False
        self.kill_on_close = False
        create_job = self._kernel32.CreateJobObjectW
        create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        create_job.restype = wintypes.HANDLE
        handle = create_job(None, None)
        if not handle:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Windows Job Object creation failed"
            )
        self._handle = int(handle)
        try:
            self._set_kill_on_close()
        except BaseException:
            self.close()
            raise

    def _set_kill_on_close(self) -> None:
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        information = EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        set_information = self._kernel32.SetInformationJobObject
        set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        set_information.restype = wintypes.BOOL
        if self._handle is None or not set_information(
            wintypes.HANDLE(self._handle),
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Windows Job Object policy failed"
            )
        self.kill_on_close = True

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        assign = self._kernel32.AssignProcessToJobObject
        assign.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        assign.restype = wintypes.BOOL
        process_handle = int(getattr(process, "_handle"))
        if self._handle is None or not assign(
            wintypes.HANDLE(self._handle), wintypes.HANDLE(process_handle)
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process Job Object assignment failed"
            )
        self.assigned_before_resume = True

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        from ctypes import wintypes

        if not self.assigned_before_resume:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process resume preceded Job Object assignment"
            )
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        resume = ntdll.NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = ctypes.c_long
        status = int(resume(wintypes.HANDLE(int(getattr(process, "_handle")))))
        if status != 0:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication suspended process resume failed"
            )

    def active_processes(self) -> int:
        from ctypes import wintypes

        class BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        information = BASIC_ACCOUNTING_INFORMATION()
        query = self._kernel32.QueryInformationJobObject
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        query.restype = wintypes.BOOL
        returned = wintypes.DWORD()
        if self._handle is None or not query(
            wintypes.HANDLE(self._handle),
            1,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object accounting failed"
            )
        return int(information.ActiveProcesses)

    def terminate(self) -> None:
        from ctypes import wintypes

        terminate = self._kernel32.TerminateJobObject
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        if self._handle is not None and not terminate(
            wintypes.HANDLE(self._handle), 1
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object termination failed"
            )

    def close(self) -> None:
        from ctypes import wintypes

        handle = self._handle
        self._handle = None
        if handle is None:
            return
        close_handle = self._kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(wintypes.HANDLE(handle)):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication Job Object close failed"
            )


class _LinuxSubreaperScope:
    """Own every child during one POSIX run, including setsid escapees."""

    def __init__(self) -> None:
        self._locked = False
        self._closed = False
        self._previous = 0
        self._libc: Any = None
        if os.name == "nt" or not sys.platform.startswith("linux"):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX containment is unsupported"
            )
        if (
            threading.current_thread() is not threading.main_thread()
            or len(threading.enumerate()) != 1
            or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX containment preconditions failed"
            )
        if not _POSIX_SCOPE_LOCK.acquire(blocking=False):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX containment is already active"
            )
        self._locked = True
        try:
            try:
                native_tasks = list(
                    Path(f"/proc/{os.getpid()}/task").iterdir()
                )
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX native task query failed"
                ) from exc
            if len(native_tasks) != 1:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX caller has native threads"
                )
            try:
                probe_descriptor = os.pidfd_open(os.getpid(), 0)
                try:
                    signal.pidfd_send_signal(probe_descriptor, 0, None, 0)
                finally:
                    os.close(probe_descriptor)
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX pidfd probe failed"
                ) from exc
            self._libc = ctypes.CDLL(None, use_errno=True)
            prctl = self._libc.prctl
            prctl.restype = ctypes.c_int
            previous = ctypes.c_int()
            if prctl(
                _PR_GET_CHILD_SUBREAPER,
                ctypes.c_ulong(ctypes.addressof(previous)),
                0,
                0,
                0,
            ) != 0:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX subreaper query failed"
                )
            self._previous = int(previous.value)
            if self._direct_children_raw():
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX caller already has children"
                )
            if prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX subreaper setup failed"
                )
            enabled = ctypes.c_int()
            if (
                prctl(
                    _PR_GET_CHILD_SUBREAPER,
                    ctypes.c_ulong(ctypes.addressof(enabled)),
                    0,
                    0,
                    0,
                ) != 0
                or enabled.value != 1
            ):
                prctl(_PR_SET_CHILD_SUBREAPER, self._previous, 0, 0, 0)
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX subreaper verification failed"
                )
        except BaseException:
            if self._locked:
                _POSIX_SCOPE_LOCK.release()
                self._locked = False
            raise

    @staticmethod
    def _direct_children_raw() -> set[int]:
        task_root = Path(f"/proc/{os.getpid()}/task")
        try:
            tasks = list(task_root.iterdir())
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX child inventory failed"
            ) from exc
        children: set[int] = set()
        for task in tasks:
            try:
                payload = (task / "children").read_text(encoding="ascii")
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX child inventory failed"
                ) from exc
            if len(payload) > 1_048_576:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX child inventory overflowed"
                )
            try:
                children.update(int(token) for token in payload.split())
            except ValueError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX child inventory is invalid"
                ) from exc
        children.discard(os.getpid())
        return children

    def _reap_children(self, *, exclude: set[int] | None = None) -> None:
        excluded = set() if exclude is None else exclude
        for pid in self._direct_children_raw() - excluded:
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, ProcessLookupError):
                pass
            except OSError as exc:
                if exc.errno != errno.EINTR:
                    raise BackendPublicationProcessSupervisorV3Error(
                        "backend publication POSIX descendant reap failed"
                    ) from exc

    def children(self, *, exclude: set[int] | None = None) -> set[int]:
        self._reap_children(exclude=exclude)
        excluded = set() if exclude is None else exclude
        return self._direct_children_raw() - excluded

    def signal_children(
        self, signo: int, *, exclude: set[int] | None = None
    ) -> bool:
        attempted = False
        for pid in self.children(exclude=exclude):
            try:
                descriptor = os.pidfd_open(pid, 0)
            except ProcessLookupError:
                continue
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX descendant pidfd failed"
                ) from exc
            try:
                try:
                    signal.pidfd_send_signal(descriptor, signo, None, 0)
                    attempted = True
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    raise BackendPublicationProcessSupervisorV3Error(
                        "backend publication POSIX descendant signal failed"
                    ) from exc
            finally:
                os.close(descriptor)
        return attempted

    def quiescent(self, *, process_group: int) -> bool:
        self._reap_children()
        return (
            not _posix_group_exists(process_group)
            and not self._direct_children_raw()
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            late_descendants_detected = bool(self.children())
            deadline = time.monotonic() + _FINAL_QUIESCENCE_GRACE_SECONDS
            while self.children() and time.monotonic() < deadline:
                self.signal_children(signal.SIGKILL)
                time.sleep(_MONITOR_INTERVAL_SECONDS)
            self._reap_children()
            if self._direct_children_raw():
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX descendants survived cleanup"
                )
            if self._libc.prctl(
                _PR_SET_CHILD_SUBREAPER, self._previous, 0, 0, 0
            ) != 0:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX subreaper restore failed"
                )
            restored = ctypes.c_int()
            if (
                self._libc.prctl(
                    _PR_GET_CHILD_SUBREAPER,
                    ctypes.c_ulong(ctypes.addressof(restored)),
                    0,
                    0,
                    0,
                ) != 0
                or restored.value != self._previous
            ):
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX subreaper restore verification failed"
                )
            if late_descendants_detected:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX late descendants were rejected"
                )
        finally:
            if self._locked:
                _POSIX_SCOPE_LOCK.release()
                self._locked = False


def _posix_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_until(predicate: Any, *, grace_seconds: float) -> bool:
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_MONITOR_INTERVAL_SECONDS)
    return bool(predicate())


def _reap_direct_process(
    process: subprocess.Popen[bytes], *, grace_seconds: float
) -> None:
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            pass


def _cleanup_posix_tree(
    process: subprocess.Popen[bytes],
    process_group: int,
    scope: _LinuxSubreaperScope,
) -> _CleanupOutcome:
    direct_pid = {process.pid}
    attempted = (
        _posix_group_exists(process_group)
        or bool(scope.children(exclude=direct_pid))
    )
    escalated = False
    if _posix_group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            pass
    attempted = scope.signal_children(
        signal.SIGTERM, exclude=direct_pid
    ) or attempted
    _reap_direct_process(process, grace_seconds=_TERMINATION_GRACE_SECONDS)
    attempted = scope.signal_children(signal.SIGTERM) or attempted
    quiescent = _wait_until(
        lambda: scope.quiescent(process_group=process_group),
        grace_seconds=_TERMINATION_GRACE_SECONDS,
    )
    if not quiescent:
        escalated = True
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        scope.signal_children(signal.SIGKILL, exclude=direct_pid)
        _reap_direct_process(process, grace_seconds=_TERMINATION_GRACE_SECONDS)
        scope.signal_children(signal.SIGKILL)
        quiescent = _wait_until(
            lambda: (
                not scope.signal_children(signal.SIGKILL)
                and scope.quiescent(process_group=process_group)
            ),
            grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS,
        )
    return _CleanupOutcome(
        attempted, escalated, quiescent, 0 if quiescent else None
    )


def _cleanup_windows_tree(
    process: subprocess.Popen[bytes], job: _WindowsJob
) -> _CleanupOutcome:
    active = job.active_processes()
    attempted = active > 0
    if attempted:
        job.terminate()
    _reap_direct_process(process, grace_seconds=_TERMINATION_GRACE_SECONDS)
    quiescent = _wait_until(
        lambda: job.active_processes() == 0,
        grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS,
    )
    active = job.active_processes()
    return _CleanupOutcome(attempted, attempted, quiescent and active == 0, active)


def _tree_is_quiescent(
    *,
    process_group: int | None,
    job: _WindowsJob | None,
    posix_scope: _LinuxSubreaperScope | None,
) -> tuple[bool, int | None]:
    if os.name == "nt":
        if job is None:
            return False, None
        active = job.active_processes()
        return active == 0, active
    if process_group is None or posix_scope is None:
        return False, None
    quiescent = posix_scope.quiescent(process_group=process_group)
    return quiescent, 0 if quiescent else None


def _emergency_cleanup(
    process: subprocess.Popen[bytes] | None,
    *,
    process_group: int | None,
    job: _WindowsJob | None,
    posix_scope: _LinuxSubreaperScope | None,
    readers: Sequence[_BoundedPipeReader],
) -> None:
    if process is not None:
        try:
            if os.name == "nt" and job is not None:
                _cleanup_windows_tree(process, job)
            elif process_group is not None and posix_scope is not None:
                _cleanup_posix_tree(process, process_group, posix_scope)
            else:
                process.kill()
                _reap_direct_process(
                    process, grace_seconds=_TERMINATION_GRACE_SECONDS
                )
        except BaseException:
            try:
                process.kill()
            except BaseException:
                pass
            try:
                process.wait(timeout=_TERMINATION_GRACE_SECONDS)
            except BaseException:
                pass
    try:
        _stop_readers(readers)
    except BaseException:
        pass
    finally:
        if job is not None:
            try:
                job.close()
            except BaseException:
                pass


def _select_status_v3(
    *,
    stdout_overflow: bool,
    stderr_overflow: bool,
    timed_out: bool,
    capture_failed: bool,
    exit_code: int | None,
    quiescent: bool,
) -> str:
    if stdout_overflow and stderr_overflow:
        return "capture_overflow"
    if stdout_overflow:
        return "stdout_overflow"
    if stderr_overflow:
        return "stderr_overflow"
    if timed_out:
        return "timed_out"
    if capture_failed or exit_code is None:
        return "capture_failed"
    if exit_code != 0:
        return "exit_nonzero"
    if not quiescent:
        return "process_tree_not_quiescent"
    return "succeeded"


def _build_observation(
    *,
    status: str,
    command: tuple[str, ...],
    cwd: Path,
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    timed_out: bool,
    stdout_overflow: bool,
    stderr_overflow: bool,
    cleanup: _CleanupOutcome,
    job_assigned_before_resume: bool,
    unexpected_live_descendant_detected: bool,
) -> dict[str, Any]:
    if status not in OBSERVATION_STATUSES:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process observation status is invalid"
        )
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": OBSERVATION_KIND,
        "status": status,
        "platform_family": "windows" if os.name == "nt" else "posix",
        "argv_sha256": _sha256(_canonical_json(list(command))),
        "cwd": str(cwd),
        "exit_code": exit_code,
        "stdout_size_bytes": len(stdout),
        "stdout_sha256": _sha256(stdout),
        "stderr_size_bytes": len(stderr),
        "stderr_sha256": _sha256(stderr),
        "timeout_ms": _PROCESS_TIMEOUT_MS,
        "max_stdout_bytes": _MAX_STDOUT_BYTES,
        "max_stderr_bytes": _MAX_STDERR_BYTES,
        "timed_out": timed_out,
        "stdout_overflow": stdout_overflow,
        "stderr_overflow": stderr_overflow,
        "termination_attempted": cleanup.termination_attempted,
        "termination_escalated": cleanup.termination_escalated,
        "process_tree_quiescent": cleanup.quiescent,
        "unexpected_live_descendant_detected": (
            unexpected_live_descendant_detected
        ),
        "active_processes_after_cleanup": cleanup.active_processes,
        "create_suspended": os.name == "nt",
        "job_kill_on_close": os.name == "nt",
        "job_assigned_before_resume": job_assigned_before_resume,
        "start_new_session": os.name != "nt",
        "posix_child_subreaper": os.name != "nt",
        "posix_pidfd_descendant_cleanup": os.name != "nt",
        "posix_isolated_broker": os.name != "nt",
        "shell": False,
        "environment": {},
        "stdin": "DEVNULL",
        "close_fds": True,
        "publication_execution_authorized": False,
    }
    observation = {
        **core,
        "observation_sha256": _sha256(
            OBSERVATION_DOMAIN + _canonical_json(core)
        ),
    }
    if set(observation) != set(OBSERVATION_FIELDS):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process observation fields drifted"
        )
    return observation


_STATUS_MESSAGES = {
    "exit_nonzero": "backend publication process exited nonzero",
    "timed_out": "backend publication process timed out",
    "stdout_overflow": "backend publication process stdout overflowed",
    "stderr_overflow": "backend publication process stderr overflowed",
    "capture_overflow": "backend publication process capture overflowed",
    "capture_failed": "backend publication process capture failed",
    "process_tree_not_quiescent": (
        "backend publication process tree did not reach quiescence"
    ),
}


def _parse_canonical_broker_object(payload: bytes, *, label: str) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate broker JSON key")
            value[key] = item
        return value

    try:
        value = json.loads(
            payload.decode("ascii"), object_pairs_hook=unique_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            f"backend publication POSIX broker {label} is invalid"
        ) from exc
    if type(value) is not dict or _canonical_json(value) != payload:
        raise BackendPublicationProcessSupervisorV3Error(
            f"backend publication POSIX broker {label} is noncanonical"
        )
    return value


def _broker_request_bytes(command: tuple[str, ...], cwd: Path) -> bytes:
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": _POSIX_BROKER_REQUEST_KIND,
        "argv": list(command),
        "cwd": str(cwd),
        "publication_execution_authorized": False,
    }
    value = {
        **core,
        "request_sha256": _sha256(
            _POSIX_BROKER_REQUEST_DOMAIN + _canonical_json(core)
        ),
    }
    payload = _canonical_json(value)
    if len(payload) > _POSIX_BROKER_MAX_REQUEST_BYTES:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker request overflowed"
        )
    return (
        _POSIX_BROKER_REQUEST_MAGIC
        + len(payload).to_bytes(8, "big")
        + payload
    )


def _read_descriptor_exact_v3(descriptor: int, size: int) -> bytes:
    payload = bytearray()
    while len(payload) < size:
        try:
            block = os.read(descriptor, size - len(payload))
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker request read failed"
            ) from exc
        if not block:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker request is truncated"
            )
        payload.extend(block)
    return bytes(payload)


def _read_broker_request_frame_v3(descriptor: int) -> bytes:
    prefix_size = len(_POSIX_BROKER_REQUEST_MAGIC) + 8
    prefix = _read_descriptor_exact_v3(descriptor, prefix_size)
    if not prefix.startswith(_POSIX_BROKER_REQUEST_MAGIC):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker request framing drifted"
        )
    payload_size = int.from_bytes(
        prefix[len(_POSIX_BROKER_REQUEST_MAGIC) :], "big"
    )
    if payload_size <= 0 or payload_size > _POSIX_BROKER_MAX_REQUEST_BYTES:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker request size is invalid"
        )
    return _read_descriptor_exact_v3(descriptor, payload_size)


def _validate_broker_request(payload: bytes) -> tuple[tuple[str, ...], Path]:
    value = _parse_canonical_broker_object(payload, label="request")
    fields = {
        "schema_version",
        "artifact_kind",
        "argv",
        "cwd",
        "publication_execution_authorized",
        "request_sha256",
    }
    unsigned = {key: item for key, item in value.items() if key != "request_sha256"}
    if (
        set(value) != fields
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != _POSIX_BROKER_REQUEST_KIND
        or value.get("publication_execution_authorized") is not False
        or type(value.get("request_sha256")) is not str
        or value["request_sha256"]
        != _sha256(_POSIX_BROKER_REQUEST_DOMAIN + _canonical_json(unsigned))
        or type(value.get("argv")) is not list
        or type(value.get("cwd")) is not str
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker request drifted"
        )
    return _validate_invocation(value["argv"], Path(value["cwd"]))


def _broker_response_frame(
    *,
    outcome: str,
    message: str,
    observation: dict[str, Any] | None,
    stdout: bytes,
    stderr: bytes,
) -> bytes:
    if outcome not in {"succeeded", "failed"}:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker outcome is invalid"
        )
    core: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": _POSIX_BROKER_RESPONSE_KIND,
        "outcome": outcome,
        "message": message,
        "observation": copy.deepcopy(observation),
        "stdout_size_bytes": len(stdout),
        "stdout_sha256": _sha256(stdout),
        "stderr_size_bytes": len(stderr),
        "stderr_sha256": _sha256(stderr),
        "publication_execution_authorized": False,
    }
    value = {
        **core,
        "response_sha256": _sha256(
            _POSIX_BROKER_RESPONSE_DOMAIN
            + _canonical_json(core)
            + stdout
            + stderr
        ),
    }
    header = _canonical_json(value)
    if len(header) > _POSIX_BROKER_MAX_HEADER_BYTES:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response header overflowed"
        )
    return (
        _POSIX_BROKER_FRAME_MAGIC
        + len(header).to_bytes(8, "big")
        + header
        + stdout
        + stderr
    )


def _validate_broker_observation(
    value: Any,
    *,
    command: tuple[str, ...],
    cwd: Path,
    stdout: bytes,
    stderr: bytes,
    succeeded: bool,
) -> dict[str, Any] | None:
    if value is None:
        if succeeded or stdout or stderr:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker omitted its observation"
            )
        return None
    if type(value) is not dict or set(value) != set(OBSERVATION_FIELDS):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker observation fields drifted"
        )
    observation = copy.deepcopy(value)
    unsigned = copy.deepcopy(observation)
    declared = unsigned.pop("observation_sha256", None)
    expected_status = observation.get("status")
    if (
        type(declared) is not str
        or declared
        != _sha256(OBSERVATION_DOMAIN + _canonical_json(unsigned))
        or expected_status not in OBSERVATION_STATUSES
        or observation.get("argv_sha256")
        != _sha256(_canonical_json(list(command)))
        or observation.get("cwd") != str(cwd)
        or observation.get("platform_family") != "posix"
        or observation.get("stdout_size_bytes") != len(stdout)
        or observation.get("stdout_sha256") != _sha256(stdout)
        or observation.get("stderr_size_bytes") != len(stderr)
        or observation.get("stderr_sha256") != _sha256(stderr)
        or observation.get("timeout_ms") != _PROCESS_TIMEOUT_MS
        or observation.get("max_stdout_bytes") != _MAX_STDOUT_BYTES
        or observation.get("max_stderr_bytes") != _MAX_STDERR_BYTES
        or observation.get("publication_execution_authorized") is not False
        or observation.get("shell") is not False
        or observation.get("environment") != {}
        or observation.get("stdin") != "DEVNULL"
        or observation.get("close_fds") is not True
        or observation.get("start_new_session") is not True
        or observation.get("posix_child_subreaper") is not True
        or observation.get("posix_pidfd_descendant_cleanup") is not True
        or observation.get("posix_isolated_broker") is not True
        or observation.get("create_suspended") is not False
        or observation.get("job_kill_on_close") is not False
        or observation.get("job_assigned_before_resume") is not False
        or (succeeded and expected_status != "succeeded")
        or (succeeded and observation.get("exit_code") != 0)
        or (succeeded and observation.get("process_tree_quiescent") is not True)
        or (succeeded and observation.get("active_processes_after_cleanup") != 0)
        or (succeeded and observation.get("unexpected_live_descendant_detected") is not False)
        or (not succeeded and expected_status == "succeeded")
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker observation is invalid"
        )
    return observation


def _parse_broker_response_frame(
    payload: bytes,
    *,
    command: tuple[str, ...],
    cwd: Path,
) -> BackendPublicationProcessRunV3:
    prefix_size = len(_POSIX_BROKER_FRAME_MAGIC) + 8
    if len(payload) < prefix_size or not payload.startswith(
        _POSIX_BROKER_FRAME_MAGIC
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response framing drifted"
        )
    header_size = int.from_bytes(
        payload[len(_POSIX_BROKER_FRAME_MAGIC) : prefix_size], "big"
    )
    if header_size <= 0 or header_size > _POSIX_BROKER_MAX_HEADER_BYTES:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response header is invalid"
        )
    header_end = prefix_size + header_size
    if header_end > len(payload):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response is truncated"
        )
    header = _parse_canonical_broker_object(
        payload[prefix_size:header_end], label="response"
    )
    fields = {
        "schema_version",
        "artifact_kind",
        "outcome",
        "message",
        "observation",
        "stdout_size_bytes",
        "stdout_sha256",
        "stderr_size_bytes",
        "stderr_sha256",
        "publication_execution_authorized",
        "response_sha256",
    }
    stdout_size = header.get("stdout_size_bytes")
    stderr_size = header.get("stderr_size_bytes")
    message = header.get("message")
    if (
        set(header) != fields
        or header.get("schema_version") != SCHEMA_VERSION
        or header.get("artifact_kind") != _POSIX_BROKER_RESPONSE_KIND
        or header.get("outcome") not in {"succeeded", "failed"}
        or type(message) is not str
        or not message
        or len(message) > 256
        or any(ord(character) < 0x20 or ord(character) > 0x7E for character in message)
        or type(stdout_size) is not int
        or stdout_size < 0
        or stdout_size > _MAX_STDOUT_BYTES
        or type(stderr_size) is not int
        or stderr_size < 0
        or stderr_size > _MAX_STDERR_BYTES
        or header.get("publication_execution_authorized") is not False
        or type(header.get("response_sha256")) is not str
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response fields drifted"
        )
    stdout_end = header_end + stdout_size
    stderr_end = stdout_end + stderr_size
    if stderr_end != len(payload):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response body drifted"
        )
    stdout = payload[header_end:stdout_end]
    stderr = payload[stdout_end:stderr_end]
    unsigned = {key: item for key, item in header.items() if key != "response_sha256"}
    if (
        header["stdout_sha256"] != _sha256(stdout)
        or header["stderr_sha256"] != _sha256(stderr)
        or header["response_sha256"]
        != _sha256(
            _POSIX_BROKER_RESPONSE_DOMAIN
            + _canonical_json(unsigned)
            + stdout
            + stderr
        )
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker response hash drifted"
        )
    succeeded = header["outcome"] == "succeeded"
    observation = _validate_broker_observation(
        header.get("observation"),
        command=command,
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        succeeded=succeeded,
    )
    if succeeded:
        if message != "backend publication process succeeded":
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker success message drifted"
            )
        assert observation is not None
        return BackendPublicationProcessRunV3(
            stdout=stdout, stderr=stderr, observation=observation
        )
    if observation is not None and message != _STATUS_MESSAGES[observation["status"]]:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker failure message drifted"
        )
    raise BackendPublicationProcessSupervisorV3Error(
        message,
        observation=observation,
        stdout=stdout,
        stderr=stderr,
    )


class _LinuxCapabilityHeader(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("pid", ctypes.c_int),
    ]


class _LinuxCapabilityData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def _linux_prctl_v3(
    option: int,
    argument2: int = 0,
    argument3: int = 0,
    argument4: int = 0,
    argument5: int = 0,
) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = int(
        prctl(option, argument2, argument3, argument4, argument5)
    )
    if result < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    return result


def _linux_cap_last_cap_v3() -> int:
    try:
        payload = Path("/proc/sys/kernel/cap_last_cap").read_bytes()
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux capability inventory failed"
        ) from exc
    if (
        not payload
        or len(payload) > 16
        or payload[-1:] != b"\n"
        or not payload[:-1].isdigit()
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux capability inventory is invalid"
        )
    value = int(payload[:-1])
    if value < 0 or value > 255:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux capability inventory is out of range"
        )
    return value


def _linux_security_status_v3() -> dict[str, str]:
    try:
        payload = Path("/proc/self/status").read_text(encoding="ascii")
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux security status failed"
        ) from exc
    if len(payload) > 1_048_576:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux security status overflowed"
        )
    fields: dict[str, str] = {}
    for line in payload.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    return fields


def _linux_backend_preexec_v3() -> None:
    last_capability = _linux_cap_last_cap_v3()
    _linux_prctl_v3(_PR_SET_NO_NEW_PRIVS, 1)
    for capability in range(last_capability + 1):
        _linux_prctl_v3(_PR_CAPBSET_DROP, capability)
    _linux_prctl_v3(
        _PR_SET_SECUREBITS, _LINUX_SECUREBITS_LOCKED_NO_PRIVILEGE_GAIN
    )
    _linux_prctl_v3(
        _PR_CAP_AMBIENT, _PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0
    )
    libc = ctypes.CDLL(None, use_errno=True)
    capset = libc.capset
    capset.restype = ctypes.c_int
    header = _LinuxCapabilityHeader(
        version=_LINUX_CAPABILITY_VERSION_3,
        pid=0,
    )
    data = (_LinuxCapabilityData * 2)()
    ctypes.set_errno(0)
    if capset(ctypes.byref(header), ctypes.byref(data)) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))
    status = _linux_security_status_v3()
    capability_fields = (
        "CapInh",
        "CapPrm",
        "CapEff",
        "CapBnd",
        "CapAmb",
    )
    if (
        status.get("NoNewPrivs") != "1"
        or any(
            key not in status or int(status[key], 16) != 0
            for key in capability_fields
        )
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux privilege drop verification failed"
        )


def _set_linux_broker_nondumpable_v3() -> None:
    try:
        _linux_prctl_v3(_PR_SET_DUMPABLE, 0)
        dumpable = _linux_prctl_v3(_PR_GET_DUMPABLE)
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux broker hardening failed"
        ) from exc
    if dumpable != 0:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux broker hardening verification failed"
        )


def _set_linux_parent_death_signal_v3(
    parent_liveness_descriptor: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.restype = ctypes.c_int
    ctypes.set_errno(0)
    if prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux parent-death setup failed"
        ) from OSError(error_number, os.strerror(error_number))
    configured = ctypes.c_int()
    ctypes.set_errno(0)
    if (
        prctl(
            _PR_GET_PDEATHSIG,
            ctypes.c_ulong(ctypes.addressof(configured)),
            0,
            0,
            0,
        ) != 0
        or configured.value != int(signal.SIGKILL)
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux parent-death verification failed"
        )
    poller = select.poll()
    poller.register(
        parent_liveness_descriptor,
        select.POLLIN | select.POLLHUP | select.POLLERR | select.POLLNVAL,
    )
    if poller.poll(0):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux parent died during containment setup"
        )


def _run_backend_publication_process_direct_v3(
    command: tuple[str, ...],
    canonical_cwd: Path,
    *,
    posix_scope: _LinuxSubreaperScope | None,
) -> BackendPublicationProcessRunV3:
    if not (
        type(_PROCESS_TIMEOUT_MS) is int
        and 0 < _PROCESS_TIMEOUT_MS <= 3_600_000
        and type(_MAX_STDOUT_BYTES) is int
        and 0 < _MAX_STDOUT_BYTES <= 64 * 1024 * 1024
        and type(_MAX_STDERR_BYTES) is int
        and 0 < _MAX_STDERR_BYTES <= 64 * 1024 * 1024
        and math.isfinite(_TERMINATION_GRACE_SECONDS)
        and _TERMINATION_GRACE_SECONDS > 0
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process frozen limits are invalid"
        )

    process: subprocess.Popen[bytes] | None = None
    process_group: int | None = None
    job: _WindowsJob | None = None
    readers: list[_BoundedPipeReader] = []
    cleanup = _CleanupOutcome(False, False, False, None)
    unexpected_live_tree = False
    job_closed = False
    try:
        if os.name == "nt":
            job = _WindowsJob()
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                cwd=str(canonical_cwd),
                env={},
                bufsize=0,
                close_fds=True,
                creationflags=_CREATE_SUSPENDED,
            )
            job.assign(process)
        else:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                cwd=str(canonical_cwd),
                env={},
                bufsize=0,
                close_fds=True,
                start_new_session=True,
                preexec_fn=_linux_backend_preexec_v3,
            )
            process_group = process.pid
    except BackendPublicationProcessSupervisorV3Error:
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise
    except OSError as exc:
        if job is not None:
            try:
                job.close()
            except BaseException:
                pass
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process spawn failed"
        ) from exc
    except Exception as exc:
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process setup failed"
        ) from exc
    except BaseException:
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise

    assert process is not None
    try:
        if process.stdout is None or process.stderr is None:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication process capture pipes are missing"
            )
        readers = [
            _BoundedPipeReader(
                name="stdout", pipe=process.stdout, limit=_MAX_STDOUT_BYTES
            ),
            _BoundedPipeReader(
                name="stderr", pipe=process.stderr, limit=_MAX_STDERR_BYTES
            ),
        ]
        for reader in readers:
            reader.start()
        if job is not None:
            job.resume(process)

        monitor = _monitor_process_v3(
            process, readers, timeout_ms=_PROCESS_TIMEOUT_MS
        )
        stdout_overflow = readers[0].overflow
        stderr_overflow = readers[1].overflow
        needs_forced_cleanup = (
            monitor.timed_out
            or monitor.capture_failed
            or stdout_overflow
            or stderr_overflow
        )
        if needs_forced_cleanup:
            cleanup = (
                _cleanup_windows_tree(process, job)
                if job is not None
                else _cleanup_posix_tree(
                    process, int(process_group), posix_scope
                )
            )
        else:
            _reap_direct_process(
                process, grace_seconds=_TERMINATION_GRACE_SECONDS
            )
            initially_quiescent, active = _tree_is_quiescent(
                process_group=process_group,
                job=job,
                posix_scope=posix_scope,
            )
            unexpected_live_tree = not initially_quiescent
            if unexpected_live_tree:
                cleanup = (
                    _cleanup_windows_tree(process, job)
                    if job is not None
                    else _cleanup_posix_tree(
                        process, int(process_group), posix_scope
                    )
                )
            else:
                cleanup = _CleanupOutcome(False, False, True, active)

        readers_finished = _wait_readers(
            readers, grace_seconds=_PIPE_JOIN_GRACE_SECONDS
        )
        if not readers_finished:
            monitor = _MonitorOutcome(
                exit_code=monitor.exit_code,
                timed_out=monitor.timed_out,
                capture_failed=True,
            )
        stdout_overflow = stdout_overflow or readers[0].overflow
        stderr_overflow = stderr_overflow or readers[1].overflow
        capture_failed = monitor.capture_failed or any(
            reader.error is not None or reader.thread.is_alive()
            for reader in readers
        )
        _stop_readers(readers)
        _reap_direct_process(process, grace_seconds=_TERMINATION_GRACE_SECONDS)
        final_quiescent, active = _tree_is_quiescent(
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
        )
        cleanup = _CleanupOutcome(
            cleanup.termination_attempted,
            cleanup.termination_escalated,
            cleanup.quiescent and final_quiescent,
            active,
        )
        if job is not None:
            job.close()
            job_closed = True

        stdout = readers[0].payload()
        stderr = readers[1].payload()
        observed_exit_code = (
            None
            if monitor.timed_out or stdout_overflow or stderr_overflow
            else process.returncode
        )
        status = _select_status_v3(
            stdout_overflow=stdout_overflow,
            stderr_overflow=stderr_overflow,
            timed_out=monitor.timed_out,
            capture_failed=capture_failed,
            exit_code=observed_exit_code,
            quiescent=cleanup.quiescent and not unexpected_live_tree,
        )
        observation = _build_observation(
            status=status,
            command=command,
            cwd=canonical_cwd,
            exit_code=observed_exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=monitor.timed_out,
            stdout_overflow=stdout_overflow,
            stderr_overflow=stderr_overflow,
            cleanup=cleanup,
            job_assigned_before_resume=(
                job.assigned_before_resume if job is not None else False
            ),
            unexpected_live_descendant_detected=unexpected_live_tree,
        )
        if status != "succeeded":
            raise BackendPublicationProcessSupervisorV3Error(
                _STATUS_MESSAGES[status],
                observation=observation,
                stdout=stdout,
                stderr=stderr,
            )
        return BackendPublicationProcessRunV3(
            stdout=stdout,
            stderr=stderr,
            observation=observation,
        )
    except BackendPublicationProcessSupervisorV3Error:
        if job_closed:
            raise
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise
    except Exception as exc:
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication process supervision failed"
        ) from exc
    except BaseException:
        _emergency_cleanup(
            process,
            process_group=process_group,
            job=job,
            posix_scope=posix_scope,
            readers=readers,
        )
        raise


def _run_backend_with_posix_scope_v3(
    command: tuple[str, ...], cwd: Path
) -> BackendPublicationProcessRunV3:
    scope = _LinuxSubreaperScope()
    try:
        result = _run_backend_publication_process_direct_v3(
            command, cwd, posix_scope=scope
        )
    except Exception as primary:
        try:
            scope.close()
        except BackendPublicationProcessSupervisorV3Error as cleanup_error:
            raise cleanup_error from primary
        raise
    except BaseException:
        try:
            scope.close()
        except BaseException:
            pass
        raise
    scope.close()
    return result


class _PosixBrokerCancelled(BaseException):
    pass


def _write_descriptor_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker IPC write failed"
            )
        view = view[written:]


def _write_linux_proc_control_v3(path: str, payload: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        _write_descriptor_all(descriptor, payload)
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux namespace mapping failed"
        ) from exc
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _linux_mount_v3(
    source: bytes | None,
    target: bytes,
    filesystem: bytes | None,
    flags: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_char_p,
    ]
    mount.restype = ctypes.c_int
    ctypes.set_errno(0)
    if mount(source, target, filesystem, flags, None) != 0:
        error_number = ctypes.get_errno()
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux namespace mount failed"
        ) from OSError(error_number, os.strerror(error_number))


def _enter_linux_pid_namespace_v3() -> tuple[int, int]:
    if (
        not sys.platform.startswith("linux")
        or threading.current_thread() is not threading.main_thread()
        or len(threading.enumerate()) != 1
        or not all(
            hasattr(os, name)
            for name in ("unshare", "fork", "CLONE_NEWUSER", "CLONE_NEWNS", "CLONE_NEWPID")
        )
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux PID namespace is unsupported"
        )
    original_uid = os.getuid()
    original_gid = os.getgid()
    parent_liveness_read = -1
    parent_liveness_write = -1
    try:
        os.unshare(os.CLONE_NEWUSER)
        try:
            _write_linux_proc_control_v3(
                "/proc/self/setgroups", b"deny\n"
            )
        except BackendPublicationProcessSupervisorV3Error as exc:
            if not isinstance(exc.__cause__, FileNotFoundError):
                raise
        _write_linux_proc_control_v3(
            "/proc/self/uid_map",
            f"0 {original_uid} 1\n".encode("ascii"),
        )
        _write_linux_proc_control_v3(
            "/proc/self/gid_map",
            f"0 {original_gid} 1\n".encode("ascii"),
        )
        os.unshare(os.CLONE_NEWNS | os.CLONE_NEWPID)
        _linux_mount_v3(None, b"/", None, _MS_REC | _MS_PRIVATE)
        parent_liveness_read, parent_liveness_write = os.pipe2(
            getattr(os, "O_CLOEXEC", 0)
        )
        namespace_init_pid = os.fork()
    except BackendPublicationProcessSupervisorV3Error:
        for descriptor in (parent_liveness_read, parent_liveness_write):
            if descriptor >= 0:
                os.close(descriptor)
        raise
    except OSError as exc:
        for descriptor in (parent_liveness_read, parent_liveness_write):
            if descriptor >= 0:
                os.close(descriptor)
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux PID namespace setup failed"
        ) from exc
    if namespace_init_pid != 0:
        os.close(parent_liveness_read)
        return namespace_init_pid, parent_liveness_write
    os.close(parent_liveness_write)
    try:
        _set_linux_parent_death_signal_v3(parent_liveness_read)
    finally:
        os.close(parent_liveness_read)
    _linux_mount_v3(
        b"proc",
        b"/proc",
        b"proc",
        _MS_NOSUID | _MS_NODEV | _MS_NOEXEC,
    )
    try:
        proc_self = Path("/proc/self").resolve(strict=True)
    except OSError as exc:
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux PID namespace procfs failed"
        ) from exc
    if os.getpid() != 1 or proc_self != Path("/proc/1"):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication Linux PID namespace identity failed"
        )
    _set_linux_broker_nondumpable_v3()
    return 0, -1


def _wait_linux_namespace_init_v3(
    namespace_init_pid: int, parent_liveness_descriptor: int
) -> int:
    try:
        namespace_init_pidfd = os.pidfd_open(namespace_init_pid, 0)
    except OSError:
        return 74
    parent_lost = False
    poller = select.poll()
    poller.register(
        0,
        select.POLLIN | select.POLLHUP | select.POLLERR | select.POLLNVAL,
    )
    status: int | None = None
    try:
        while status is None:
            try:
                waited_pid, candidate_status = os.waitpid(
                    namespace_init_pid, os.WNOHANG
                )
            except InterruptedError:
                continue
            except OSError:
                return 74
            if waited_pid == namespace_init_pid:
                status = candidate_status
                break
            if waited_pid != 0:
                return 74
            events = poller.poll(20)
            if events:
                try:
                    trailing = os.read(0, 1)
                except OSError:
                    trailing = b""
                parent_lost = True
                try:
                    signal.pidfd_send_signal(
                        namespace_init_pidfd, signal.SIGKILL, None, 0
                    )
                except ProcessLookupError:
                    pass
                except OSError:
                    return 74
        if status is None:
            return 74
        exit_code = os.waitstatus_to_exitcode(status)
        if parent_lost:
            return 75
        return exit_code if exit_code >= 0 else 128 + (-exit_code)
    finally:
        os.close(namespace_init_pidfd)
        os.close(parent_liveness_descriptor)


def _run_linux_namespace_init_broker_v3(
    command: tuple[str, ...], cwd: Path
) -> int:
    def cancel(_signo: int, _frame: Any) -> None:
        raise _PosixBrokerCancelled()

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        try:
            result = _run_backend_with_posix_scope_v3(command, cwd)
        except BackendPublicationProcessSupervisorV3Error as error:
            frame = _broker_response_frame(
                outcome="failed",
                message=str(error),
                observation=error.observation,
                stdout=error.stdout,
                stderr=error.stderr,
            )
        except Exception:
            frame = _broker_response_frame(
                outcome="failed",
                message="backend publication POSIX broker supervision failed",
                observation=None,
                stdout=b"",
                stderr=b"",
            )
        else:
            frame = _broker_response_frame(
                outcome="succeeded",
                message="backend publication process succeeded",
                observation=result.observation,
                stdout=result.stdout,
                stderr=result.stderr,
            )
    except _PosixBrokerCancelled:
        return 75
    except BaseException:
        try:
            frame = _broker_response_frame(
                outcome="failed",
                message="backend publication POSIX broker setup failed",
                observation=None,
                stdout=b"",
                stderr=b"",
            )
        except BaseException:
            return 74
    try:
        _write_descriptor_all(1, frame)
    except BaseException:
        return 74
    return 0


def _posix_broker_entry_v3() -> int:
    if os.name == "nt":
        return 78
    try:
        request = _read_broker_request_frame_v3(0)
        command, cwd = _validate_broker_request(request)
        namespace_init_pid, parent_liveness_descriptor = (
            _enter_linux_pid_namespace_v3()
        )
    except BaseException:
        try:
            frame = _broker_response_frame(
                outcome="failed",
                message="backend publication POSIX broker setup failed",
                observation=None,
                stdout=b"",
                stderr=b"",
            )
            _write_descriptor_all(1, frame)
        except BaseException:
            return 74
        return 0
    if namespace_init_pid != 0:
        return _wait_linux_namespace_init_v3(
            namespace_init_pid, parent_liveness_descriptor
        )
    return _run_linux_namespace_init_broker_v3(command, cwd)


class _PosixBrokerIdentity:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        if (
            process.stdout is None
            or not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
        ):
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker identity is unsupported"
            )
        leader_pidfd = -1
        try:
            pipe_info = os.fstat(process.stdout.fileno())
            if not stat.S_ISFIFO(pipe_info.st_mode):
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX broker response is not a pipe"
                )
            leader_pidfd = os.pidfd_open(process.pid, 0)
            signal.pidfd_send_signal(leader_pidfd, 0, None, 0)
        except BackendPublicationProcessSupervisorV3Error:
            if leader_pidfd >= 0:
                os.close(leader_pidfd)
            raise
        except OSError as exc:
            if leader_pidfd >= 0:
                os.close(leader_pidfd)
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker identity failed"
            ) from exc
        self._leader_pidfd = leader_pidfd
        self.leader_pid = process.pid
        self.pipe_device = int(pipe_info.st_dev)
        self.pipe_inode = int(pipe_info.st_ino)
        self._closed = False

    def _leader_alive(self) -> bool:
        try:
            signal.pidfd_send_signal(self._leader_pidfd, 0, None, 0)
        except ProcessLookupError:
            return False
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker leader probe failed"
            ) from exc
        return True

    def _pipe_holder_pids(self) -> set[int]:
        try:
            processes = list(Path("/proc").iterdir())
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker inventory failed"
            ) from exc
        if len(processes) > 1_048_576:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker inventory overflowed"
            )
        holders: set[int] = set()
        for process_path in processes:
            if not process_path.name.isdigit():
                continue
            pid = int(process_path.name)
            try:
                process_stat = (process_path / "stat").read_bytes()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX broker inventory failed"
                ) from exc
            if len(process_stat) > 16_384:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX broker stat overflowed"
                )
            if process_stat.rfind(b")") < 0 or pid == os.getpid():
                continue
            try:
                descriptors = list((process_path / "fd").iterdir())
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            except OSError as exc:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX broker descriptor inventory failed"
                ) from exc
            if len(descriptors) > 65_536:
                raise BackendPublicationProcessSupervisorV3Error(
                    "backend publication POSIX broker descriptor inventory overflowed"
                )
            for descriptor in descriptors:
                try:
                    descriptor_info = descriptor.stat()
                except (FileNotFoundError, ProcessLookupError, PermissionError):
                    continue
                except OSError as exc:
                    raise BackendPublicationProcessSupervisorV3Error(
                        "backend publication POSIX broker descriptor probe failed"
                    ) from exc
                if (
                    stat.S_ISFIFO(descriptor_info.st_mode)
                    and int(descriptor_info.st_dev) == self.pipe_device
                    and int(descriptor_info.st_ino) == self.pipe_inode
                ):
                    holders.add(pid)
                    break
        return holders

    def signal_active(self, signo: int) -> bool:
        try:
            signal.pidfd_send_signal(self._leader_pidfd, signo, None, 0)
        except ProcessLookupError:
            return False
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker leader signal failed"
            ) from exc
        return True

    def quiescent(self, process: subprocess.Popen[bytes]) -> bool:
        try:
            process.poll()
            leader_alive = self._leader_alive()
            holders = self._pipe_holder_pids()
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker quiescence probe failed"
            ) from exc
        return not leader_alive and not holders

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._leader_pidfd)
        except OSError:
            pass


def _terminate_posix_broker(
    process: subprocess.Popen[bytes], identity: _PosixBrokerIdentity
) -> None:
    if identity.quiescent(process):
        _reap_direct_process(
            process, grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS
        )
        if process.poll() is None:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker cleanup failed"
            )
        return
    if not identity._leader_alive():
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker leader custody was lost"
        )
    identity.signal_active(signal.SIGTERM)
    group_quiescent = _wait_until(
        lambda: identity.quiescent(process),
        grace_seconds=_POSIX_BROKER_TERMINATION_GRACE_SECONDS,
    )
    if not group_quiescent:
        if not identity._leader_alive():
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker leader custody was lost"
            )
        group_quiescent = _wait_until(
            lambda: (
                identity.signal_active(signal.SIGKILL) is False
                and identity.quiescent(process)
            ),
            grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS,
        )
    _reap_direct_process(
        process, grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS
    )
    group_quiescent = identity.quiescent(process)
    if (
        process.poll() is None
        or not group_quiescent
    ):
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker cleanup failed"
        )


def _run_backend_publication_posix_broker_v3(
    command: tuple[str, ...], cwd: Path
) -> BackendPublicationProcessRunV3:
    request = _broker_request_bytes(command, cwd)
    supervisor_path = Path(__file__).resolve(strict=True)
    process: subprocess.Popen[bytes] | None = None
    broker_identity: _PosixBrokerIdentity | None = None
    readers: list[_BoundedPipeReader] = []
    stdin_closed = False
    broker_termination_attempted = False

    def terminate_broker_once() -> None:
        nonlocal broker_termination_attempted
        if process is None or broker_termination_attempted:
            return
        broker_termination_attempted = True
        if broker_identity is not None:
            _terminate_posix_broker(process, broker_identity)
            return
        if process.poll() is not None:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker identity was lost"
            )
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError as exc:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker pre-identity cleanup failed"
            ) from exc
        _reap_direct_process(
            process, grace_seconds=_FINAL_QUIESCENCE_GRACE_SECONDS
        )
        if process.poll() is None:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker pre-identity cleanup failed"
            )

    def cleanup_parent_broker() -> None:
        cleanup_error: BaseException | None = None
        try:
            terminate_broker_once()
        except BaseException as exc:
            cleanup_error = exc
        try:
            _stop_readers(readers)
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is not None:
            if isinstance(
                cleanup_error, BackendPublicationProcessSupervisorV3Error
            ):
                raise cleanup_error
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker cleanup failed"
            ) from cleanup_error

    try:
        process = subprocess.Popen(
            [command[0], str(supervisor_path), _POSIX_BROKER_MODE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            cwd=str(cwd),
            env={},
            bufsize=0,
            close_fds=True,
            start_new_session=True,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker pipes are missing"
            )
        broker_identity = _PosixBrokerIdentity(process)
        response_limit = (
            len(_POSIX_BROKER_FRAME_MAGIC)
            + 8
            + _POSIX_BROKER_MAX_HEADER_BYTES
            + _MAX_STDOUT_BYTES
            + _MAX_STDERR_BYTES
        )
        readers = [
            _BoundedPipeReader(
                name="broker-stdout", pipe=process.stdout, limit=response_limit
            ),
            _BoundedPipeReader(
                name="broker-stderr",
                pipe=process.stderr,
                limit=_POSIX_BROKER_MAX_DIAGNOSTIC_BYTES,
            ),
        ]
        for reader in readers:
            reader.start()
        _write_descriptor_all(process.stdin.fileno(), request)
        monitor = _monitor_process_v3(
            process,
            readers,
            timeout_ms=_PROCESS_TIMEOUT_MS + _POSIX_BROKER_CLEANUP_MARGIN_MS,
        )
        if monitor.timed_out or _readers_have_failure(readers):
            terminate_broker_once()
        else:
            _reap_direct_process(
                process, grace_seconds=_TERMINATION_GRACE_SECONDS
            )
        readers_finished = _wait_readers(
            readers, grace_seconds=_PIPE_JOIN_GRACE_SECONDS
        )
        capture_failed = (
            not readers_finished
            or any(
                reader.error is not None
                or reader.overflow
                or reader.thread.is_alive()
                for reader in readers
            )
        )
        _stop_readers(readers)
        if monitor.timed_out:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker timed out"
            )
        if capture_failed:
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker capture failed"
            )
        if process.returncode != 0 or readers[1].payload():
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker process failed"
            )
        if not broker_identity.quiescent(process):
            terminate_broker_once()
            raise BackendPublicationProcessSupervisorV3Error(
                "backend publication POSIX broker did not reach quiescence"
            )
        return _parse_broker_response_frame(
            readers[0].payload(), command=command, cwd=cwd
        )
    except BackendPublicationProcessSupervisorV3Error as primary:
        try:
            cleanup_parent_broker()
        except BackendPublicationProcessSupervisorV3Error as cleanup_error:
            raise cleanup_error from primary
        raise
    except Exception as exc:
        try:
            cleanup_parent_broker()
        except BackendPublicationProcessSupervisorV3Error as cleanup_error:
            raise cleanup_error from exc
        raise BackendPublicationProcessSupervisorV3Error(
            "backend publication POSIX broker supervision failed"
        ) from exc
    except BaseException as primary:
        try:
            cleanup_parent_broker()
        except BackendPublicationProcessSupervisorV3Error as cleanup_error:
            raise cleanup_error from primary
        raise
    finally:
        if process is not None and process.stdin is not None and not stdin_closed:
            try:
                process.stdin.close()
            except BaseException:
                pass
        if broker_identity is not None:
            broker_identity.close()


def run_backend_publication_process_v3(
    argv: Sequence[str], *, cwd: Path
) -> BackendPublicationProcessRunV3:
    """Run exactly one frozen-ABI child and return only exit-0 quiescent output."""

    command, canonical_cwd = _validate_invocation(argv, cwd)
    if os.name == "nt":
        return _run_backend_publication_process_direct_v3(
            command, canonical_cwd, posix_scope=None
        )
    return _run_backend_publication_posix_broker_v3(command, canonical_cwd)


__all__ = [
    "BackendPublicationProcessRunV3",
    "BackendPublicationProcessSupervisorV3Error",
    "OBSERVATION_DOMAIN",
    "OBSERVATION_FIELDS",
    "OBSERVATION_KIND",
    "OBSERVATION_STATUSES",
    "READER_THREAD_PREFIX",
    "SCHEMA_VERSION",
    "run_backend_publication_process_v3",
]


if __name__ == "__main__":
    if sys.argv[1:] != [_POSIX_BROKER_MODE]:
        raise SystemExit(78)
    raise SystemExit(_posix_broker_entry_v3())
