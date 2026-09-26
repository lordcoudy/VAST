#!/usr/bin/env python3
"""Parent-owned, nonpublication engineering transaction for launcher ABI v3.

This module proves the v3 process and durable-result protocol with an externally
pinned synthetic launcher.  It deliberately cannot authorize a production
publication run, accept measurement evidence, or elevate readiness.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from backend_publication_dispatch_v3 import (
    ARM_CONTRACT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    BackendPublicationDispatchV3Error,
    build_backend_publication_command_v3,
    canonical_backend_publication_arm_contract_bytes_v3,
    parse_backend_publication_arm_contract_v3_bytes,
    validate_backend_publication_arm_contract_v3,
)
from backend_publication_process_supervisor_v3 import (
    BackendPublicationProcessSupervisorV3Error,
    _run_backend_publication_process_durable_v3 as run_backend_publication_process_v3,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_immutable_directory_v1 import (
    JOURNAL_ROOT as IMMUTABLE_DIRECTORY_JOURNAL_ROOT,
    PublicationImmutableDirectoryV1Error,
    commit_or_adopt_immutable_directory_v1,
)


SCHEMA_VERSION = 3
DURABLE_OUTPUT_SCHEMA_VERSION = 4
NONPUBLICATION_ENGINEERING_SCOPE = (
    "externally_pinned_synthetic_nonpublication_only"
)
ARM_AUTHORITY_KIND = "vast_backend_publication_arm_contract_file_authority_v3"
FENCE_KIND = "vast_backend_publication_launch_fence_v4"
RESULT_KIND = "vast_backend_publication_launcher_result_v4"
RECEIPT_KIND = "vast_backend_publication_output_receipt_v4"
RECEIPT_AUTHORITY_KIND = (
    "vast_backend_publication_output_receipt_authority_v4"
)
MAX_CONTROL_JSON_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_AGGREGATE_BYTES = 256 * 1024 * 1024
MAX_EVIDENCE_FILES = 64
MAX_TRANSACTION_NAMESPACE_ENTRIES = MAX_EVIDENCE_FILES + 6
READ_CHUNK_BYTES = 1024 * 1024
PROCESS_OBSERVATION_KIND = "vast_backend_publication_process_observation_v3"
PROCESS_OBSERVATION_DOMAIN = b"VAST:backend-publication-process-observation:v3\0"
BOOTSTRAP_JOURNAL_ROOT = ".backend-publication-transaction-bootstrap-v1"
BOOTSTRAP_INTENT_KIND = "vast_backend_publication_transaction_bootstrap_intent_v1"
BOOTSTRAP_RECEIPT_KIND = "vast_backend_publication_transaction_bootstrap_receipt_v1"
PROCESS_OBSERVATION_FIELDS = frozenset(
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
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_FALSE_CLAIM_FIELDS = (
    "accepted_measurement_evidence",
    "publication_execution_authorized",
    "publication_authorized",
    "publication_ready",
    "readiness_elevated",
    "promotable",
    "executed_python_bytecode_attested",
    "python_startup_filesystem_writes_attested",
    "process_observation_origin_attested",
    "capture_origin_attested",
    "launcher_evidence_origin_attested",
    "private_output_acl_attested",
    "directory_namespace_immutability_attested",
    "executable_path_immutability_through_spawn_attested",
    "parent_directory_crash_durability_attested",
    "power_loss_at_most_once_attested",
    "postcommit_resource_release_attested",
)


class BackendPublicationOutputTransactionV3Error(RuntimeError):
    """The v3 engineering transaction is unsafe, ambiguous, or inconsistent."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication transaction material is not canonical JSON"
        ) from error


def _canonical_file_bytes(value: object) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} SHA-256 is invalid"
        )
    return value


def _direct_child_name(value: Any, *, label: str) -> str:
    if type(value) is not str or not value or "\0" in value:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} filename is invalid"
        )
    path = Path(value)
    if (
        path.is_absolute()
        or len(path.parts) != 1
        or path.name != value
        or value in {".", ".."}
        or os.path.normpath(value) != value
    ):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} filename is not a canonical direct child"
        )
    return value


def _descriptor(value: Any, *, label: str, allow_empty: bool = True) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} descriptor fields drifted"
        )
    name = _direct_child_name(value.get("path"), label=label)
    size = value.get("size_bytes")
    if (
        type(size) is not int
        or size < 0
        or (not allow_empty and size == 0)
    ):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} descriptor size is invalid"
        )
    sha = _valid_sha(value.get("sha256"), label=label)
    return {"path": name, "size_bytes": size, "sha256": sha}


def _false_claims() -> dict[str, bool]:
    return {field: False for field in _FALSE_CLAIM_FIELDS}


def _stable_stat(info: os.stat_result) -> tuple[int, ...]:
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


def _cross_view_stat(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(stat.S_IFMT(info.st_mode)),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _directory_identity_stat(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(stat.S_IFMT(info.st_mode)),
        int(info.st_nlink),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _directory_file_id_stat(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(stat.S_IFMT(info.st_mode)),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _physical_directory_identity_stat(info: os.stat_result) -> tuple[int, ...]:
    """Match the exact directory identity returned by PhysicalRootCustodyV1."""

    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(getattr(info, "st_uid", 0)),
        int(getattr(info, "st_gid", 0)),
    )


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication immutable file write made no progress"
            )
        view = view[written:]


def _read_all(descriptor: int, *, limit: int, label: str) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    observed = 0
    while True:
        chunk = os.read(descriptor, min(READ_CHUNK_BYTES, limit + 1 - observed))
        if not chunk:
            break
        chunks.append(chunk)
        observed += len(chunk)
        if observed > limit:
            raise BackendPublicationOutputTransactionV3Error(
                f"{label} exceeds its byte bound"
            )
    return b"".join(chunks)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication control JSON has duplicate keys"
            )
        value[key] = item
    return value


def _parse_canonical_object(payload: bytes, *, label: str) -> dict[str, Any]:
    if not payload or len(payload) > MAX_CONTROL_JSON_BYTES:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} byte size is invalid"
        )
    try:
        value = json.loads(payload.decode("ascii"), object_pairs_hook=_unique_object)
    except BackendPublicationOutputTransactionV3Error:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ) as error:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} is not valid unique ASCII JSON"
        ) from error
    if type(value) is not dict or payload != _canonical_file_bytes(value):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} bytes are not canonical"
        )
    return value


class _DirectoryHold:
    """Keep one directory identity alive and non-renamable where supported."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._descriptor: int | None = None
        self._handle: int | None = None
        self._native_identity: tuple[int, ...] | None = None
        try:
            supplied = self.path
            if not supplied.is_absolute() or os.path.normpath(str(supplied)) != str(supplied):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication transaction directory is not canonical"
                )
            resolved = supplied.resolve(strict=True)
            if os.path.normcase(str(resolved)) != os.path.normcase(str(supplied)):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication transaction directory is not plain"
                )
            before = supplied.lstat()
            if not stat.S_ISDIR(before.st_mode) or _is_link_or_reparse(before):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication transaction directory is unsafe"
                )
            self.before = before
            if os.name == "nt":
                self._open_windows()
            else:
                flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
                flags |= int(getattr(os, "O_NOFOLLOW", 0))
                self._descriptor = os.open(self.path, flags)
                opened = os.fstat(self._descriptor)
                if _stable_stat(opened) != _stable_stat(before):
                    raise BackendPublicationOutputTransactionV3Error(
                        "backend publication transaction directory changed while opening"
                    )
        except BaseException:
            self.close(suppress=True)
            raise

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise BackendPublicationOutputTransactionV3Error(
                "POSIX transaction directory descriptor is unavailable"
            )
        return self._descriptor

    def _open_windows(self) -> None:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        handle = create(
            str(self.path),
            0x0001 | 0x00020000,
            0x00000001 | 0x00000002,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        invalid = ctypes.c_void_p(-1).value
        if not handle or int(handle) == invalid:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication Windows transaction directory custody failed"
            )
        self._handle = int(handle)
        self._native_identity = self._windows_identity(self._handle)
        try:
            after = self.path.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication Windows transaction directory disappeared while opening"
            ) from error
        native_inode = (
            int(self._native_identity[1]) << 32
        ) | int(self._native_identity[2])
        native_attributes = int(self._native_identity[3])
        native_links = int(self._native_identity[4])
        directory_attribute = 0x00000010
        reparse_attribute = 0x00000400
        if (
            _directory_identity_stat(after) != _directory_identity_stat(self.before)
            or int(self.before.st_ino) != native_inode
            or int(after.st_ino) != native_inode
            or int(self.before.st_nlink) != native_links
            or int(after.st_nlink) != native_links
            or not native_attributes & directory_attribute
            or native_attributes & reparse_attribute
        ):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication Windows transaction directory changed while opening"
            )

    @staticmethod
    def _windows_identity(handle: int) -> tuple[int, ...]:
        from ctypes import wintypes

        class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("dwFileAttributes", wintypes.DWORD),
                ("ftCreationTimeLow", wintypes.DWORD),
                ("ftCreationTimeHigh", wintypes.DWORD),
                ("ftLastAccessTimeLow", wintypes.DWORD),
                ("ftLastAccessTimeHigh", wintypes.DWORD),
                ("ftLastWriteTimeLow", wintypes.DWORD),
                ("ftLastWriteTimeHigh", wintypes.DWORD),
                ("dwVolumeSerialNumber", wintypes.DWORD),
                ("nFileSizeHigh", wintypes.DWORD),
                ("nFileSizeLow", wintypes.DWORD),
                ("nNumberOfLinks", wintypes.DWORD),
                ("nFileIndexHigh", wintypes.DWORD),
                ("nFileIndexLow", wintypes.DWORD),
            ]

        info = BY_HANDLE_FILE_INFORMATION()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        query = kernel32.GetFileInformationByHandle
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]
        query.restype = wintypes.BOOL
        if not query(wintypes.HANDLE(handle), ctypes.byref(info)):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication Windows directory identity query failed"
            )
        return (
            int(info.dwVolumeSerialNumber),
            int(info.nFileIndexHigh),
            int(info.nFileIndexLow),
            int(info.dwFileAttributes),
            int(info.nNumberOfLinks),
        )

    def names(self) -> set[str]:
        try:
            location: int | Path = self.descriptor if os.name != "nt" else self.path
            values: list[str] = []
            with os.scandir(location) as entries:
                for entry in entries:
                    if len(values) >= MAX_TRANSACTION_NAMESPACE_ENTRIES:
                        raise BackendPublicationOutputTransactionV3Error(
                            "backend publication transaction namespace exceeds its entry bound"
                        )
                    values.append(entry.name)
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace cannot be enumerated"
            ) from error
        if any(type(name) is not str or not name for name in values):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace is invalid"
            )
        folded = [name.casefold() for name in values]
        if len(folded) != len(set(folded)):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace case-collides"
            )
        return set(values)

    def sync_created_entry(self) -> None:
        """Persist a POSIX directory entry before it is used as a fence.

        Windows leaf creation uses FILE_FLAG_WRITE_THROUGH, but this module
        deliberately keeps parent-directory/power-loss durability claims false
        because Windows does not provide a portable directory-fsync primitive.
        """

        if os.name == "nt":
            return
        try:
            os.fsync(self.descriptor)
            current_handle = os.fstat(self.descriptor)
            current_path = self.path.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction directory entry cannot be synchronized"
            ) from error
        if (
            _directory_file_id_stat(current_handle)
            != _directory_file_id_stat(self.before)
            or _directory_file_id_stat(current_path)
            != _directory_file_id_stat(self.before)
        ):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction directory changed while synchronizing"
            )
        # Creating a child directory legitimately changes the POSIX link count.
        # Rebaseline only after both the held descriptor and path prove the same
        # directory identity; subsequent verification again binds the full
        # directory identity tuple.
        self.before = current_path

    def verify(self) -> None:
        try:
            after = self.path.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction directory disappeared"
            ) from error
        if _directory_identity_stat(after) != _directory_identity_stat(self.before):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction directory identity drifted"
            )
        if os.name == "nt":
            if self._handle is None or self._native_identity != self._windows_identity(self._handle):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication Windows transaction directory custody drifted"
                )
        else:
            if self._descriptor is None or _directory_identity_stat(os.fstat(self._descriptor)) != _directory_identity_stat(self.before):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication POSIX transaction directory custody drifted"
                )

    def close(self, *, suppress: bool = False) -> None:
        failures: list[BaseException] = []
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except BaseException as error:
                failures.append(error)
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                close_handle = kernel32.CloseHandle
                close_handle.argtypes = [wintypes.HANDLE]
                close_handle.restype = wintypes.BOOL
                if not close_handle(wintypes.HANDLE(handle)):
                    raise OSError(ctypes.get_last_error(), "CloseHandle failed")
            except BaseException as error:
                failures.append(error)
        if failures and not suppress:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction directory custody close failed"
            ) from failures[0]

    def __enter__(self) -> _DirectoryHold:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        try:
            self.close(suppress=exc is not None)
        except BaseException:
            if exc is None:
                raise
        return False


class _HeldFile:
    """Hold one direct child and repeatedly bind its path, identity, and bytes."""

    def __init__(
        self,
        root: _DirectoryHold,
        name: str,
        *,
        label: str,
        limit: int,
        allow_empty: bool,
        existing_descriptor: int | None = None,
    ) -> None:
        self.root = root
        self.name = _direct_child_name(name, label=label)
        self.label = label
        self.limit = limit
        self.allow_empty = allow_empty
        self.path = root.path / self.name
        self._descriptor: int | None = existing_descriptor
        try:
            self.path_before = self.path.lstat()
            if (
                not stat.S_ISREG(self.path_before.st_mode)
                or _is_link_or_reparse(self.path_before)
                or int(self.path_before.st_nlink) != 1
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    f"{label} is not a unique plain regular file"
                )
            if self._descriptor is None:
                self._descriptor = self._open_read_custody()
            self.handle_before = os.fstat(self.descriptor)
            if (
                not stat.S_ISREG(self.handle_before.st_mode)
                or int(self.handle_before.st_nlink) != 1
                or _cross_view_stat(self.path_before)
                != _cross_view_stat(self.handle_before)
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    f"{label} path/handle identity drifted"
                )
            self.payload = _read_all(
                self.descriptor, limit=self.limit, label=self.label
            )
            if not self.allow_empty and not self.payload:
                raise BackendPublicationOutputTransactionV3Error(
                    f"{label} is unexpectedly empty"
                )
            self.digest = hashlib.sha256(self.payload).hexdigest()
            self.handle_after_read = os.fstat(self.descriptor)
            self.path_after_read = self.path.lstat()
            self._verify_metadata()
        except FileNotFoundError as error:
            self.close(suppress=True)
            raise BackendPublicationOutputTransactionV3Error(
                f"{label} is missing"
            ) from error
        except BaseException:
            self.close(suppress=True)
            raise

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise BackendPublicationOutputTransactionV3Error(
                f"{self.label} custody is closed"
            )
        return self._descriptor

    def _open_read_custody(self) -> int:
        if os.name != "nt":
            flags = os.O_RDONLY | int(getattr(os, "O_NOFOLLOW", 0))
            flags |= int(getattr(os, "O_CLOEXEC", 0))
            return os.open(self.name, flags, dir_fd=self.root.descriptor)

        from ctypes import wintypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        handle = create(
            str(self.path),
            0x80000000,
            0x00000001,
            None,
            3,
            0x00200000 | 0x08000000,
            None,
        )
        invalid = ctypes.c_void_p(-1).value
        if not handle or int(handle) == invalid:
            raise OSError(ctypes.get_last_error(), f"{self.label} custody open failed")
        try:
            return msvcrt.open_osfhandle(
                int(handle), os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
            )
        except BaseException:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
            raise

    def _verify_metadata(self) -> None:
        if (
            _stable_stat(self.handle_before) != _stable_stat(self.handle_after_read)
            or _stable_stat(self.path_before) != _stable_stat(self.path_after_read)
            or _cross_view_stat(self.handle_after_read)
            != _cross_view_stat(self.path_after_read)
            or len(self.payload) != int(self.handle_after_read.st_size)
        ):
            raise BackendPublicationOutputTransactionV3Error(
                f"{self.label} identity changed while reading"
            )

    def file_descriptor(self) -> dict[str, Any]:
        return {
            "path": self.name,
            "size_bytes": len(self.payload),
            "sha256": self.digest,
        }

    def verify(self) -> None:
        try:
            current_handle = os.fstat(self.descriptor)
            current_path = self.path.lstat()
            current_payload = _read_all(
                self.descriptor, limit=self.limit, label=self.label
            )
            final_handle = os.fstat(self.descriptor)
            final_path = self.path.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                f"{self.label} cannot be revalidated"
            ) from error
        if (
            _stable_stat(self.handle_after_read) != _stable_stat(current_handle)
            or _stable_stat(current_handle) != _stable_stat(final_handle)
            or _stable_stat(self.path_after_read) != _stable_stat(current_path)
            or _stable_stat(current_path) != _stable_stat(final_path)
            or _cross_view_stat(final_handle) != _cross_view_stat(final_path)
            or current_payload != self.payload
        ):
            raise BackendPublicationOutputTransactionV3Error(
                f"{self.label} changed under custody"
            )

    def close(self, *, suppress: bool = False) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            os.close(descriptor)
        except BaseException as error:
            if not suppress:
                raise BackendPublicationOutputTransactionV3Error(
                    f"{self.label} custody close failed"
                ) from error


def _create_new_held(
    root: _DirectoryHold,
    name: str,
    payload: bytes,
    *,
    label: str,
    limit: int,
    allow_empty: bool,
    after_publish_step: Callable[[str], None] | None = None,
) -> _HeldFile:
    child = _direct_child_name(name, label=label)
    if type(payload) is not bytes or len(payload) > limit:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} payload exceeds its byte bound"
        )
    if not allow_empty and not payload:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} payload is unexpectedly empty"
        )
    try:
        with PhysicalRootCustodyV1.open(
            root.path.parent, label=f"{label} atomic publication parent"
        ) as custody:
            atomic_relative = f"{root.path.name}/{child}"
            observed, _identity, _disposition = (
                custody.commit_or_adopt_exact_identity(
                    atomic_relative,
                    payload,
                    label=label,
                    mode=0o600,
                    create_parents=False,
                    after_publish_step=after_publish_step,
                    allow_empty=allow_empty,
                )
            )
            expected = {
                "path": atomic_relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            if observed != expected:
                raise BackendPublicationOutputTransactionV3Error(
                    f"{label} atomic descriptor drifted"
                )
        root.sync_created_entry()
        return _HeldFile(
            root,
            child,
            label=label,
            limit=limit,
            allow_empty=allow_empty,
        )
    except PublicationPhysicalIoV1Error as error:
        raise BackendPublicationOutputTransactionV3Error(
            f"immutable backend publication transaction file cannot be atomically committed: {child}"
        ) from error


def _close_holds(holds: Iterable[_HeldFile], *, primary: BaseException | None) -> None:
    failure: BaseException | None = None
    for held in reversed(list(holds)):
        try:
            held.close(suppress=primary is not None)
        except BaseException as error:
            if failure is None:
                failure = error
    if primary is None and failure is not None:
        raise failure


def _expected_sets(evidence: Sequence[str]) -> dict[str, set[str]]:
    evidence_set = set(evidence)
    contract = {ARM_CONTRACT_FILENAME}
    fenced = contract | {LAUNCH_FENCE_FILENAME}
    captured = fenced | {
        CAPTURE_STDOUT_FILENAME,
        CAPTURE_STDERR_FILENAME,
    } | evidence_set
    result = captured | {LAUNCHER_RESULT_FILENAME}
    committed = result | {OUTPUT_RECEIPT_FILENAME}
    return {
        "prepared": contract,
        "fenced": fenced,
        "captured": captured,
        "result": result,
        "committed": committed,
    }


def _assert_exact_namespace(
    root: _DirectoryHold,
    expected: set[str],
    *,
    label: str,
) -> None:
    observed = root.names()
    if observed != expected:
        raise BackendPublicationOutputTransactionV3Error(
            f"backend publication transaction namespace is not exact for {label}"
        )
    for name in sorted(observed):
        try:
            info = (root.path / name).lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace changed while scanning"
            ) from error
        if (
            not stat.S_ISREG(info.st_mode)
            or _is_link_or_reparse(info)
            or int(info.st_nlink) != 1
        ):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace contains an unsafe leaf"
            )
    root.verify()


def _external_file_hold(
    project_root: Path,
    descriptor: Mapping[str, Any],
    *,
    label: str,
) -> tuple[_DirectoryHold, _HeldFile]:
    value = dict(descriptor)
    if type(descriptor) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} external descriptor fields drifted"
        )
    raw_path = value.get("path")
    relative = Path(str(raw_path))
    if (
        type(raw_path) is not str
        or not raw_path
        or "\0" in raw_path
        or relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] <= 0
    ):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} external descriptor is invalid"
        )
    checked = {
        "path": raw_path,
        "size_bytes": value["size_bytes"],
        "sha256": _valid_sha(value.get("sha256"), label=label),
    }
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} relative path is unsafe"
        )
    cursor = project_root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                f"{label} ancestor is missing"
            ) from error
        if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
            raise BackendPublicationOutputTransactionV3Error(
                f"{label} ancestor is unsafe"
            )
    parent = _DirectoryHold(cursor)
    try:
        held = _HeldFile(
            parent,
            relative.name,
            label=label,
            limit=max(int(checked["size_bytes"]), 1),
            allow_empty=False,
        )
        physical = held.file_descriptor()
        if (
            physical["size_bytes"] != checked["size_bytes"]
            or physical["sha256"] != checked["sha256"]
        ):
            raise BackendPublicationOutputTransactionV3Error(
                f"{label} physical descriptor differs from its external pin"
            )
        return parent, held
    except BaseException:
        parent.close(suppress=True)
        raise


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    material = copy.deepcopy(dict(value))
    material.pop(field, None)
    material[field] = _canonical_sha(material)
    return material


def _validate_self_hash(value: Mapping[str, Any], field: str, *, label: str) -> None:
    observed = _valid_sha(value.get(field), label=label)
    unsigned = {key: item for key, item in value.items() if key != field}
    if observed != _canonical_sha(unsigned):
        raise BackendPublicationOutputTransactionV3Error(
            f"{label} semantic self-hash drifted"
        )


def _fence_material(
    arm: Mapping[str, Any], *, arm_descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    value: dict[str, Any] = {
        "schema_version": DURABLE_OUTPUT_SCHEMA_VERSION,
        "artifact_kind": FENCE_KIND,
        "status": "launch_fenced_nonpublication_engineering",
        "execution_scope": NONPUBLICATION_ENGINEERING_SCOPE,
        "arm_contract": _descriptor(
            dict(arm_descriptor), label="arm contract", allow_empty=False
        ),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "python_executable": copy.deepcopy(dispatch["python_executable"]),
        "publication_launcher": copy.deepcopy(dispatch["publication_launcher"]),
        **_false_claims(),
    }
    return _seal(value, "fence_sha256")


def _validate_fence(
    value: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _fence_material(arm, arm_descriptor=arm_descriptor)
    if type(value) is not dict or value != expected:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication launch fence is tampered, replayed, or crossbound"
        )
    _validate_self_hash(value, "fence_sha256", label="launch fence")
    return copy.deepcopy(expected)


def _evidence_descriptors(holds: Sequence[_HeldFile]) -> list[dict[str, Any]]:
    values = [held.file_descriptor() for held in holds]
    if [item["path"] for item in values] != sorted(item["path"] for item in values):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication evidence descriptors are not sorted"
        )
    if sum(int(item["size_bytes"]) for item in values) > MAX_EVIDENCE_AGGREGATE_BYTES:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication evidence aggregate exceeds its byte bound"
        )
    return values


def _evidence_aggregate_sha(descriptors: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        b"VAST:backend-publication-evidence-set:v3\0"
        + _canonical_bytes([dict(item) for item in descriptors])
    ).hexdigest()


def _validate_process_observation(
    observation: Any,
    *,
    stdout: bytes,
    stderr: bytes,
    command: Sequence[str],
    cwd: Path,
    process_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        type(observation) is not dict
        or set(observation) != set(PROCESS_OBSERVATION_FIELDS)
    ):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication process observation fields drifted"
        )
    unsigned = copy.deepcopy(observation)
    declared = _valid_sha(
        unsigned.pop("observation_sha256", None), label="process observation"
    )
    expected_sha = hashlib.sha256(
        PROCESS_OBSERVATION_DOMAIN + _canonical_bytes(unsigned)
    ).hexdigest()
    platform = observation.get("platform_family")
    if platform == "windows":
        platform_valid = (
            observation.get("create_suspended") is True
            and observation.get("job_kill_on_close") is True
            and observation.get("job_assigned_before_resume") is True
            and observation.get("start_new_session") is False
            and observation.get("posix_child_subreaper") is False
            and observation.get("posix_pidfd_descendant_cleanup") is False
            and observation.get("posix_isolated_broker") is False
            and observation.get("active_processes_after_cleanup") == 0
        )
    elif platform == "posix":
        platform_valid = (
            observation.get("create_suspended") is False
            and observation.get("job_kill_on_close") is False
            and observation.get("job_assigned_before_resume") is False
            and observation.get("start_new_session") is True
            and observation.get("posix_child_subreaper") is True
            and observation.get("posix_pidfd_descendant_cleanup") is True
            and observation.get("posix_isolated_broker") is True
            and observation.get("active_processes_after_cleanup") == 0
        )
    else:
        platform_valid = False
    numeric_types_valid = (
        type(observation.get("schema_version")) is int
        and type(observation.get("exit_code")) is int
        and type(observation.get("stdout_size_bytes")) is int
        and type(observation.get("stderr_size_bytes")) is int
        and type(observation.get("timeout_ms")) is int
        and type(observation.get("max_stdout_bytes")) is int
        and type(observation.get("max_stderr_bytes")) is int
        and type(observation.get("active_processes_after_cleanup")) is int
    )
    if (
        declared != expected_sha
        or not numeric_types_valid
        or observation.get("schema_version") != SCHEMA_VERSION
        or observation.get("artifact_kind") != PROCESS_OBSERVATION_KIND
        or observation.get("status") != "succeeded"
        or observation.get("exit_code") != 0
        or observation.get("argv_sha256")
        != hashlib.sha256(_canonical_bytes(list(command))).hexdigest()
        or observation.get("cwd") != str(cwd)
        or observation.get("timeout_ms") != process_contract.get("timeout_ms")
        or observation.get("max_stdout_bytes")
        != process_contract.get("max_stdout_bytes")
        or observation.get("max_stderr_bytes")
        != process_contract.get("max_stderr_bytes")
        or observation.get("shell") is not False
        or observation.get("environment") != {}
        or observation.get("stdin") != "DEVNULL"
        or observation.get("close_fds") is not True
        or observation.get("timed_out") is not False
        or observation.get("stdout_overflow") is not False
        or observation.get("stderr_overflow") is not False
        or observation.get("termination_attempted") is not False
        or observation.get("termination_escalated") is not False
        or observation.get("process_tree_quiescent") is not True
        or observation.get("unexpected_live_descendant_detected") is not False
        or observation.get("publication_execution_authorized") is not False
        or observation.get("stdout_size_bytes") != len(stdout)
        or observation.get("stderr_size_bytes") != len(stderr)
        or observation.get("stdout_sha256") != hashlib.sha256(stdout).hexdigest()
        or observation.get("stderr_sha256") != hashlib.sha256(stderr).hexdigest()
        or not platform_valid
    ):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication process observation is not an exact success"
        )
    return copy.deepcopy(observation)


def _result_material(
    arm: Mapping[str, Any],
    *,
    arm_descriptor: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    stdout_descriptor: Mapping[str, Any],
    stderr_descriptor: Mapping[str, Any],
    process_observation: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
    durable_journal_response: Mapping[str, Any],
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    evidence = [_descriptor(dict(item), label="launcher evidence", allow_empty=False)
                for item in evidence_descriptors]
    value: dict[str, Any] = {
        "schema_version": DURABLE_OUTPUT_SCHEMA_VERSION,
        "artifact_kind": RESULT_KIND,
        "status": "completed_nonpublication_engineering_process",
        "execution_scope": NONPUBLICATION_ENGINEERING_SCOPE,
        "arm_contract": _descriptor(dict(arm_descriptor), label="arm contract", allow_empty=False),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "launch_fence": _descriptor(dict(fence_descriptor), label="launch fence", allow_empty=False),
        "launch_fence_content_sha256": fence["fence_sha256"],
        "process_observation": copy.deepcopy(dict(process_observation)),
        "durable_process_journal_response": copy.deepcopy(
            dict(durable_journal_response)
        ),
        "stdout_capture": _descriptor(dict(stdout_descriptor), label="stdout capture"),
        "stderr_capture": _descriptor(dict(stderr_descriptor), label="stderr capture"),
        "evidence_files": evidence,
        "evidence_aggregate_sha256": _evidence_aggregate_sha(evidence),
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": arm["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": arm["resource_capability_grant_sha256"],
        "model_parity_grant_sha256": arm["model_parity_grant_sha256"],
        "model_parity_acceptance_binding_sha256": arm[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": arm[
            "identity_artifact_binding_sha256"
        ],
        **_false_claims(),
    }
    return _seal(value, "result_sha256")


def _receipt_material(
    arm: Mapping[str, Any],
    *,
    arm_descriptor: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    stdout_descriptor: Mapping[str, Any],
    stderr_descriptor: Mapping[str, Any],
    result_descriptor: Mapping[str, Any],
    result: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dispatch = arm["dispatch_resolution"]
    execution = arm["full_publication_execution_binding"]
    evidence = [_descriptor(dict(item), label="launcher evidence", allow_empty=False)
                for item in evidence_descriptors]
    value: dict[str, Any] = {
        "schema_version": DURABLE_OUTPUT_SCHEMA_VERSION,
        "artifact_kind": RECEIPT_KIND,
        "status": "committed_launcher_output_not_accepted",
        "execution_scope": NONPUBLICATION_ENGINEERING_SCOPE,
        "arm_contract": _descriptor(dict(arm_descriptor), label="arm contract", allow_empty=False),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "launch_fence": _descriptor(dict(fence_descriptor), label="launch fence", allow_empty=False),
        "launch_fence_content_sha256": fence["fence_sha256"],
        "durable_process_journal_response": copy.deepcopy(
            result["durable_process_journal_response"]
        ),
        "stdout_capture": _descriptor(dict(stdout_descriptor), label="stdout capture"),
        "stderr_capture": _descriptor(dict(stderr_descriptor), label="stderr capture"),
        "launcher_result": _descriptor(dict(result_descriptor), label="launcher result", allow_empty=False),
        "launcher_result_content_sha256": result["result_sha256"],
        "evidence_files": evidence,
        "evidence_aggregate_sha256": _evidence_aggregate_sha(evidence),
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": arm["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": arm["resource_capability_grant_sha256"],
        "model_parity_grant_sha256": arm["model_parity_grant_sha256"],
        "model_parity_acceptance_binding_sha256": arm[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": arm[
            "identity_artifact_binding_sha256"
        ],
        **_false_claims(),
    }
    return _seal(value, "receipt_sha256")


def _authority_material(
    arm: Mapping[str, Any],
    *,
    receipt_descriptor: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    execution = arm["full_publication_execution_binding"]
    value: dict[str, Any] = {
        "schema_version": DURABLE_OUTPUT_SCHEMA_VERSION,
        "artifact_kind": RECEIPT_AUTHORITY_KIND,
        "status": "committed_nonpublication_engineering_output",
        "execution_scope": NONPUBLICATION_ENGINEERING_SCOPE,
        **_descriptor(dict(receipt_descriptor), label="output receipt", allow_empty=False),
        "content_sha256": receipt["receipt_sha256"],
        "arm_contract": copy.deepcopy(receipt["arm_contract"]),
        "launcher_result": copy.deepcopy(receipt["launcher_result"]),
        "durable_process_journal_response": copy.deepcopy(
            receipt["durable_process_journal_response"]
        ),
        "evidence_files": copy.deepcopy(receipt["evidence_files"]),
        "evidence_aggregate_sha256": receipt["evidence_aggregate_sha256"],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "dispatch_resolution_sha256": arm["dispatch_resolution"]["resolution_sha256"],
        **_false_claims(),
    }
    return _seal(value, "authority_sha256")


def _assert_plain_output_chain(project_root: Path, output_dir: Path) -> None:
    try:
        root = project_root.resolve(strict=True)
        relative = output_dir.relative_to(root)
    except (OSError, ValueError) as error:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication transaction output escaped project root"
        ) from error
    if not relative.parts:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication transaction output is not a strict descendant"
        )
    root_info = root.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or _is_link_or_reparse(root_info):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication transaction project root is unsafe"
        )
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction output ancestor is missing"
            ) from error
        if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction output ancestor is unsafe"
            )


def _arm_file_authority(
    arm: Mapping[str, Any], descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARM_AUTHORITY_KIND,
        **_descriptor(dict(descriptor), label="arm contract", allow_empty=False),
        "content_sha256": arm["contract_sha256"],
        "dispatch_resolution_sha256": arm["dispatch_resolution"][
            "resolution_sha256"
        ],
        "run_identity_sha256": arm["full_publication_execution_binding"][
            "run_identity_sha256"
        ],
        **_false_claims(),
    }
    return _seal(value, "authority_sha256")


def _bootstrap_paths_v1(
    *, custody_root: Path, output_dir: Path
) -> dict[str, str]:
    try:
        target = output_dir.relative_to(custody_root).as_posix()
        parent = output_dir.parent.relative_to(custody_root).as_posix()
    except ValueError as error:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication bootstrap escaped project root"
        ) from error
    key = hashlib.sha256(target.encode("utf-8")).hexdigest()
    stage_name = f".backend-publication-bootstrap-stage-v1-{key}"
    stage = stage_name if parent == "." else f"{parent}/{stage_name}"
    return {
        "target": target,
        "arm": f"{target}/{ARM_CONTRACT_FILENAME}",
        "stage": stage,
        "stage_arm": f"{stage}/{ARM_CONTRACT_FILENAME}",
        "intent": f"{BOOTSTRAP_JOURNAL_ROOT}/{key}.intent.json",
        "receipt": f"{BOOTSTRAP_JOURNAL_ROOT}/{key}.receipt.json",
        "directory_intent": (
            f"{IMMUTABLE_DIRECTORY_JOURNAL_ROOT}/{key}.json"
        ),
    }


def _bootstrap_intent_v1(
    *, paths: Mapping[str, str], arm: Mapping[str, Any], payload: bytes
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": BOOTSTRAP_INTENT_KIND,
        "target_output_dir": paths["target"],
        "staging_dir": paths["stage"],
        "arm_contract_path": paths["arm"],
        "arm_contract_size_bytes": len(payload),
        "arm_contract_sha256": hashlib.sha256(payload).hexdigest(),
        "arm_contract_content_sha256": arm["contract_sha256"],
    }
    return _seal(value, "intent_sha256")


def _bootstrap_fault_callback_v1(
    callback: Callable[[str], None] | None, prefix: str
) -> Callable[[str], None] | None:
    if callback is None:
        return None

    def invoke(step: str) -> None:
        callback(f"{prefix}:{step}")

    return invoke


def _bootstrap_receipt_v1(
    *,
    paths: Mapping[str, str],
    arm: Mapping[str, Any],
    payload: bytes,
    bootstrap_intent: Mapping[str, Any],
    bootstrap_intent_descriptor: Mapping[str, Any],
    bootstrap_intent_identity: tuple[int, int],
    directory_intent_descriptor: Mapping[str, Any],
    directory_intent_identity: tuple[int, int],
    output_directory_identity: tuple[int, ...],
    arm_descriptor: Mapping[str, Any],
    arm_identity: tuple[int, int],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": BOOTSTRAP_RECEIPT_KIND,
        "target_output_dir": paths["target"],
        "arm_contract_path": paths["arm"],
        "arm_contract_size_bytes": len(payload),
        "arm_contract_sha256": hashlib.sha256(payload).hexdigest(),
        "arm_contract_content_sha256": arm["contract_sha256"],
        "bootstrap_intent_sha256": bootstrap_intent["intent_sha256"],
        "bootstrap_intent": copy.deepcopy(dict(bootstrap_intent_descriptor)),
        "bootstrap_intent_identity": list(bootstrap_intent_identity),
        "immutable_directory_intent": copy.deepcopy(
            dict(directory_intent_descriptor)
        ),
        "immutable_directory_intent_identity": list(
            directory_intent_identity
        ),
        "output_directory_identity": list(output_directory_identity),
        "arm_contract": copy.deepcopy(dict(arm_descriptor)),
        "arm_contract_identity": list(arm_identity),
    }
    return _seal(value, "receipt_sha256")


def _remove_exact_bootstrap_stage_v1(
    custody: PhysicalRootCustodyV1,
    *,
    paths: Mapping[str, str],
    stage_path: Path,
    expected_directory_identity: tuple[int, ...],
    expected_arm_identity: tuple[int, int],
) -> None:
    """Remove one exact adopted stage without partially deleting foreign state."""

    stage = Path(stage_path)
    stage_name = _direct_child_name(
        stage.name, label="backend publication bootstrap staging directory"
    )
    expected_stage_name = Path(paths["stage"]).name
    if stage_name != expected_stage_name:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication bootstrap staging path drifted"
        )

    # POSIX deletion stays anchored to held parent/stage descriptors.  Validate
    # the complete namespace and both exact identities before the first unlink;
    # a rebind, extra sibling, or hardlink therefore leaves the stage untouched.
    if os.name != "nt":
        parent_hold: _DirectoryHold | None = None
        stage_fd = -1
        arm_fd = -1
        try:
            parent_hold = _DirectoryHold(stage.parent)
            named_stage = os.stat(
                stage_name,
                dir_fd=parent_hold.descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(named_stage.st_mode)
                or _is_link_or_reparse(named_stage)
                or _physical_directory_identity_stat(named_stage)
                != expected_directory_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging directory was rebound"
                )
            stage_fd = os.open(
                stage_name,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_hold.descriptor,
            )
            opened_stage = os.fstat(stage_fd)
            if (
                not stat.S_ISDIR(opened_stage.st_mode)
                or _physical_directory_identity_stat(opened_stage)
                != expected_directory_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging directory changed while opening"
                )
            if set(os.listdir(stage_fd)) != {ARM_CONTRACT_FILENAME}:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging namespace is foreign"
                )
            named_arm = os.stat(
                ARM_CONTRACT_FILENAME,
                dir_fd=stage_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(named_arm.st_mode)
                or stat.S_ISLNK(named_arm.st_mode)
                or int(named_arm.st_nlink) != 1
                or (int(named_arm.st_dev), int(named_arm.st_ino))
                != expected_arm_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging arm is not uniquely owned"
                )
            arm_fd = os.open(
                ARM_CONTRACT_FILENAME,
                os.O_RDONLY
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=stage_fd,
            )
            opened_arm = os.fstat(arm_fd)
            if (
                not stat.S_ISREG(opened_arm.st_mode)
                or int(opened_arm.st_nlink) != 1
                or (int(opened_arm.st_dev), int(opened_arm.st_ino))
                != expected_arm_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging arm changed while opening"
                )

            # Repeat every name/identity check at the mutation boundary while
            # both directory descriptors and the exact arm inode remain held.
            current_stage = os.stat(
                stage_name,
                dir_fd=parent_hold.descriptor,
                follow_symlinks=False,
            )
            current_arm = os.stat(
                ARM_CONTRACT_FILENAME,
                dir_fd=stage_fd,
                follow_symlinks=False,
            )
            if (
                _physical_directory_identity_stat(current_stage)
                != expected_directory_identity
                or _physical_directory_identity_stat(os.fstat(stage_fd))
                != expected_directory_identity
                or set(os.listdir(stage_fd)) != {ARM_CONTRACT_FILENAME}
                or not stat.S_ISREG(current_arm.st_mode)
                or int(current_arm.st_nlink) != 1
                or (int(current_arm.st_dev), int(current_arm.st_ino))
                != expected_arm_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging custody drifted"
                )

            os.unlink(ARM_CONTRACT_FILENAME, dir_fd=stage_fd)
            os.fsync(stage_fd)
            if os.listdir(stage_fd) != [] or int(os.fstat(arm_fd).st_nlink) != 0:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging arm removal was ambiguous"
                )
            named_before_rmdir = os.stat(
                stage_name,
                dir_fd=parent_hold.descriptor,
                follow_symlinks=False,
            )
            if (
                _physical_directory_identity_stat(named_before_rmdir)
                != expected_directory_identity
                or _physical_directory_identity_stat(os.fstat(stage_fd))
                != expected_directory_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging directory rebound before removal"
                )
            os.rmdir(stage_name, dir_fd=parent_hold.descriptor)
            os.fsync(parent_hold.descriptor)
            current_parent_handle = os.fstat(parent_hold.descriptor)
            current_parent_path = stage.parent.lstat()
            if (
                _directory_file_id_stat(current_parent_handle)
                != _directory_file_id_stat(parent_hold.before)
                or _directory_file_id_stat(current_parent_path)
                != _directory_file_id_stat(parent_hold.before)
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging parent changed during removal"
                )
            return
        except BackendPublicationOutputTransactionV3Error:
            raise
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication bootstrap staging cleanup failed"
            ) from error
        finally:
            if arm_fd >= 0:
                try:
                    os.close(arm_fd)
                except OSError:
                    pass
            if stage_fd >= 0:
                try:
                    os.close(stage_fd)
                except OSError:
                    pass
            if parent_hold is not None:
                parent_hold.close(suppress=True)

    # Native Windows keeps the existing custody primitives, but now performs
    # the same complete prevalidation before either destructive operation.
    with _DirectoryHold(stage) as stage_hold:
        if _physical_directory_identity_stat(stage_hold.before) != expected_directory_identity:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication bootstrap staging directory was rebound"
            )
        _assert_exact_namespace(
            stage_hold,
            {ARM_CONTRACT_FILENAME},
            label="bootstrap staging cleanup",
        )
        arm = _HeldFile(
            stage_hold,
            ARM_CONTRACT_FILENAME,
            label="backend publication bootstrap staging arm",
            limit=MAX_CONTROL_JSON_BYTES,
            allow_empty=False,
        )
        try:
            if (
                int(arm.handle_after_read.st_nlink) != 1
                or (int(arm.handle_after_read.st_dev), int(arm.handle_after_read.st_ino))
                != expected_arm_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap staging arm is not uniquely owned"
                )
            arm.verify()
            stage_hold.verify()
        finally:
            arm.close(suppress=True)
    custody.unlink_owned_identity(
        paths["stage_arm"],
        expected_arm_identity,
        label="backend publication bootstrap staging arm",
    )
    custody.rmdir_owned_identity(
        paths["stage"],
        expected_directory_identity,
        label="backend publication bootstrap staging directory",
    )


def prepare_backend_publication_engineering_transaction_v3(
    *,
    output_dir: Path,
    arm_contract: Mapping[str, Any],
    after_bootstrap_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create a fresh private-ish namespace and its immutable v3 arm contract.

    The directory is created with mode 0700 where POSIX honors modes.  This
    routine does not claim a private Windows DACL; the returned authority keeps
    that and every publication/acceptance claim false.
    """

    try:
        arm = copy.deepcopy(dict(arm_contract))
    except (TypeError, ValueError) as error:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication arm contract mapping is invalid"
        ) from error
    try:
        payload = canonical_backend_publication_arm_contract_bytes_v3(arm)
    except BackendPublicationDispatchV3Error as error:
        raise BackendPublicationOutputTransactionV3Error(
            f"backend publication arm contract v3 is invalid: {error}"
        ) from error
    runtime = arm["runtime_inputs"]
    root = Path(runtime["project_root"])
    output = Path(output_dir)
    if (
        output != Path(runtime["output_dir"])
        or output / ARM_CONTRACT_FILENAME != Path(runtime["arm_contract_path"])
    ):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication transaction path differs from its arm contract"
        )
    _assert_plain_output_chain(root, output)
    root = root.resolve(strict=True)
    bootstrap_root = output.parent
    paths = _bootstrap_paths_v1(custody_root=bootstrap_root, output_dir=output)
    bootstrap_intent = _bootstrap_intent_v1(
        paths=paths, arm=arm, payload=payload
    )
    bootstrap_intent_payload = _canonical_file_bytes(bootstrap_intent)
    receipt_path = bootstrap_root.joinpath(*Path(paths["receipt"]).parts)
    intent_path = bootstrap_root.joinpath(*Path(paths["intent"]).parts)
    receipt_preexisting = os.path.lexists(receipt_path)
    intent_preexisting = os.path.lexists(intent_path)
    if receipt_preexisting and not intent_preexisting:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication bootstrap receipt exists without its parent intent"
        )

    try:
        with PhysicalRootCustodyV1.open(
            bootstrap_root, label="backend publication bootstrap parent root"
        ) as custody:
            (
                bootstrap_intent_descriptor,
                bootstrap_intent_identity,
                bootstrap_intent_disposition,
            ) = custody.commit_or_adopt_exact_identity(
                paths["intent"],
                bootstrap_intent_payload,
                label="backend publication bootstrap intent",
                mode=0o444,
                create_parents=True,
                after_publish_step=_bootstrap_fault_callback_v1(
                    after_bootstrap_step, "bootstrap_intent"
                ),
            )

            if not receipt_preexisting:
                stage_path, created_directories = custody.ensure_directory_owned(
                    paths["stage"],
                    label="backend publication bootstrap staging directory",
                )
                stage_mode, stage_identity = custody.stat_directory_identity(
                    paths["stage"],
                    label="backend publication bootstrap staging directory",
                )
                if os.name != "nt" and stage_mode != 0o700:
                    raise BackendPublicationOutputTransactionV3Error(
                        "backend publication bootstrap staging mode drifted"
                    )
                created = dict(created_directories)
                if bootstrap_intent_disposition == "published" and (
                    created.get(paths["stage"]) != stage_identity
                ):
                    raise BackendPublicationOutputTransactionV3Error(
                        "foreign backend publication bootstrap staging directory preexisted its intent"
                    )
                if after_bootstrap_step is not None:
                    after_bootstrap_step("bootstrap_directory:post_create_fsync")
                _stage_mode_after, stage_identity_after = (
                    custody.stat_directory_identity(
                        paths["stage"],
                        label="backend publication bootstrap staging directory",
                    )
                )
                if stage_identity_after != stage_identity:
                    raise BackendPublicationOutputTransactionV3Error(
                        "backend publication bootstrap staging directory was rebound"
                    )

                stage_hold = _DirectoryHold(stage_path)
                contract_hold: _HeldFile | None = None
                stage_arm_identity: tuple[int, int] | None = None
                try:
                    names = stage_hold.names()
                    if names not in (set(), {ARM_CONTRACT_FILENAME}):
                        raise BackendPublicationOutputTransactionV3Error(
                            "backend publication bootstrap staging namespace is foreign"
                        )
                    contract_hold = _create_new_held(
                        stage_hold,
                        ARM_CONTRACT_FILENAME,
                        payload,
                        label="bootstrap arm contract",
                        limit=MAX_CONTROL_JSON_BYTES,
                        allow_empty=False,
                        after_publish_step=_bootstrap_fault_callback_v1(
                            after_bootstrap_step, "arm_contract"
                        ),
                    )
                    parsed = parse_backend_publication_arm_contract_v3_bytes(
                        contract_hold.payload,
                        expected_file_sha256=contract_hold.digest,
                    )
                    if parsed != arm:
                        raise BackendPublicationOutputTransactionV3Error(
                            "persisted bootstrap arm contract differs"
                        )
                    contract_hold.verify()
                    _assert_exact_namespace(
                        stage_hold,
                        {ARM_CONTRACT_FILENAME},
                        label="bootstrap staging transaction",
                    )
                    _stage_arm_descriptor, stage_arm_identity = (
                        custody.adopt_exact_durable_identity(
                            paths["stage_arm"],
                            payload,
                            label="bootstrap staging arm contract",
                            mode=0o600,
                        )
                    )
                finally:
                    if contract_hold is not None:
                        contract_hold.close(suppress=True)
                    stage_hold.close(suppress=True)

                try:
                    publication = commit_or_adopt_immutable_directory_v1(
                        project_root=bootstrap_root,
                        staging=stage_path,
                        target=output,
                        after_publish_step=_bootstrap_fault_callback_v1(
                            after_bootstrap_step, "transaction_directory"
                        ),
                    )
                except PublicationImmutableDirectoryV1Error as error:
                    raise BackendPublicationOutputTransactionV3Error(
                        "backend publication bootstrap directory commit/adoption failed"
                    ) from error
                if publication.get("disposition") == "adopted":
                    if stage_arm_identity is None or not os.path.lexists(stage_path):
                        raise BackendPublicationOutputTransactionV3Error(
                            "adopted backend publication bootstrap lost its supplied staging"
                        )
                    # The final directory was adopted from the immutable
                    # journal's previously anchored staging tree.  This newly
                    # supplied, independently validated twin is not needed for
                    # authority.  Preserve it instead of performing any
                    # check-then-unlink cleanup against a same-UID mutable
                    # namespace; the deterministic path is reused and
                    # revalidated on every later retry.
                elif publication.get("disposition") == "published":
                    if os.path.lexists(stage_path):
                        raise BackendPublicationOutputTransactionV3Error(
                            "published backend publication bootstrap retained its staging name"
                        )
                else:
                    raise BackendPublicationOutputTransactionV3Error(
                        "backend publication bootstrap directory disposition drifted"
                    )

                with _DirectoryHold(output) as prepared_directory:
                    _assert_exact_namespace(
                        prepared_directory,
                        {ARM_CONTRACT_FILENAME},
                        label="newly prepared transaction",
                    )

            output_mode, output_identity = custody.stat_directory_identity(
                paths["target"], label="prepared backend publication transaction"
            )
            if os.name != "nt" and output_mode != 0o700:
                raise BackendPublicationOutputTransactionV3Error(
                    "prepared backend publication transaction mode drifted"
                )
            arm_descriptor, arm_identity = custody.adopt_exact_durable_identity(
                paths["arm"],
                payload,
                label="prepared backend publication arm contract",
                mode=0o600,
            )
            (
                directory_intent_descriptor,
                directory_intent_payload,
                directory_intent_identity,
            ) = (
                custody.read_descriptor_identity(
                    paths["directory_intent"],
                    label="backend publication immutable directory intent",
                    maximum=MAX_CONTROL_JSON_BYTES,
                    capture=True,
                )
            )
            if directory_intent_payload is None:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication immutable directory intent was not captured"
                )
            with _DirectoryHold(output.parent) as parent:
                parent.sync_created_entry()

            bootstrap_receipt = _bootstrap_receipt_v1(
                paths=paths,
                arm=arm,
                payload=payload,
                bootstrap_intent=bootstrap_intent,
                bootstrap_intent_descriptor=bootstrap_intent_descriptor,
                bootstrap_intent_identity=bootstrap_intent_identity,
                directory_intent_descriptor=directory_intent_descriptor,
                directory_intent_identity=directory_intent_identity,
                output_directory_identity=output_identity,
                arm_descriptor=arm_descriptor,
                arm_identity=arm_identity,
            )
            bootstrap_receipt_payload = _canonical_file_bytes(bootstrap_receipt)
            custody.commit_or_adopt_exact_identity(
                paths["receipt"],
                bootstrap_receipt_payload,
                label="backend publication bootstrap receipt",
                mode=0o444,
                create_parents=False,
                after_publish_step=_bootstrap_fault_callback_v1(
                    after_bootstrap_step, "bootstrap_receipt"
                ),
            )
            _receipt_descriptor, observed_receipt_payload = custody.read_descriptor(
                paths["receipt"],
                label="backend publication bootstrap receipt",
                maximum=MAX_CONTROL_JSON_BYTES,
                capture=True,
            )
            if observed_receipt_payload != bootstrap_receipt_payload:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap receipt changed after commit"
                )
            output_mode_after, output_identity_after = custody.stat_directory_identity(
                paths["target"], label="prepared backend publication transaction"
            )
            _arm_after, arm_identity_after = custody.adopt_exact_durable_identity(
                paths["arm"],
                payload,
                label="prepared backend publication arm contract",
                mode=0o600,
                expected_identity=arm_identity,
            )
            if (
                output_mode_after != output_mode
                or output_identity_after != output_identity
                or arm_identity_after != arm_identity
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication bootstrap changed across its receipt commit"
                )
    except PublicationPhysicalIoV1Error as error:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication bootstrap physical custody failed"
        ) from error

    directory: _DirectoryHold | None = None
    contract_hold: _HeldFile | None = None
    primary: BaseException | None = None
    try:
        directory = _DirectoryHold(output)
        contract_hold = _HeldFile(
            directory,
            ARM_CONTRACT_FILENAME,
            label="arm contract",
            limit=MAX_CONTROL_JSON_BYTES,
            allow_empty=False,
        )
        parsed = parse_backend_publication_arm_contract_v3_bytes(
            contract_hold.payload,
            expected_file_sha256=contract_hold.digest,
        )
        if parsed != arm:
            raise BackendPublicationOutputTransactionV3Error(
                "persisted backend publication arm contract differs"
            )
        contract_hold.verify()
        journal_name = (
            ".backend-publication-process-journal-v1-"
            + str(arm["contract_sha256"])
        )
        try:
            with PhysicalRootCustodyV1.open(
                output.parent,
                label="prepared backend process journal parent",
            ) as journal_parent:
                journal_parent.ensure_directory_owned(
                    journal_name,
                    label="prepared backend process journal",
                )
        except PublicationPhysicalIoV1Error as error:
            raise BackendPublicationOutputTransactionV3Error(
                "prepared backend process journal cannot be created"
            ) from error
        return _arm_file_authority(arm, contract_hold.file_descriptor())
    except BaseException as error:
        primary = error
        raise
    finally:
        if contract_hold is not None:
            contract_hold.close(suppress=primary is not None)
        if directory is not None:
            directory.close(suppress=primary is not None)


def _load_control(held: _HeldFile, *, label: str) -> dict[str, Any]:
    return _parse_canonical_object(held.payload, label=label)


def _open_evidence(
    root: _DirectoryHold, names: Sequence[str]
) -> list[_HeldFile]:
    holds: list[_HeldFile] = []
    remaining = MAX_EVIDENCE_AGGREGATE_BYTES
    try:
        for name in sorted(names):
            if remaining <= 0:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication evidence aggregate exceeds its byte bound"
                )
            held = _HeldFile(
                root,
                name,
                label=f"launcher evidence {name}",
                limit=min(MAX_EVIDENCE_FILE_BYTES, remaining),
                allow_empty=False,
            )
            holds.append(held)
            remaining -= len(held.payload)
        _evidence_descriptors(holds)
        return holds
    except BaseException as error:
        _close_holds(holds, primary=error)
        raise


def _validate_durable_journal_response(
    value: Any,
    *,
    arm: Mapping[str, Any],
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "path",
        "size_bytes",
        "sha256",
        "session_sha256",
        "terminal_intent",
    }:
        raise BackendPublicationOutputTransactionV3Error(
            "durable process journal response descriptor drifted"
        )
    output = Path(str(arm["runtime_inputs"]["output_dir"]))
    journal = output.parent / (
        ".backend-publication-process-journal-v1-"
        + str(arm["contract_sha256"])
    )
    expected_path = journal / "terminal-response.frame"
    terminal_path = journal / "terminal-intent.json"
    terminal = value.get("terminal_intent")
    if (
        value.get("path") != str(expected_path)
        or type(value.get("size_bytes")) is not int
        or type(value.get("sha256")) is not str
        or _SHA256_RE.fullmatch(value["sha256"]) is None
        or type(value.get("session_sha256")) is not str
        or _SHA256_RE.fullmatch(value["session_sha256"]) is None
        or type(terminal) is not dict
        or set(terminal) != {"path", "size_bytes", "sha256"}
        or terminal.get("path") != str(terminal_path)
        or type(terminal.get("size_bytes")) is not int
        or type(terminal.get("sha256")) is not str
        or _SHA256_RE.fullmatch(terminal["sha256"]) is None
    ):
        raise BackendPublicationOutputTransactionV3Error(
            "durable process journal response crossbinding drifted"
        )
    for descriptor, path in ((value, expected_path), (terminal, terminal_path)):
        try:
            before = path.lstat()
            payload = path.read_bytes()
            after = path.lstat()
        except OSError as error:
            raise BackendPublicationOutputTransactionV3Error(
                "durable process journal response cannot be cold-validated"
            ) from error
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or int(before.st_nlink) != 1
            or _stable_stat(before) != _stable_stat(after)
            or descriptor["size_bytes"] != len(payload)
            or descriptor["sha256"] != hashlib.sha256(payload).hexdigest()
        ):
            raise BackendPublicationOutputTransactionV3Error(
                "durable process journal response changed under cold validation"
            )
    return copy.deepcopy(value)


def _validate_result_material(
    observed: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    stdout: _HeldFile,
    stderr: _HeldFile,
    evidence: Sequence[_HeldFile],
    command: Sequence[str],
    cwd: Path,
    process_contract: Mapping[str, Any],
) -> dict[str, Any]:
    if type(observed) is not dict:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication launcher result is not an object"
        )
    process = _validate_process_observation(
        observed.get("process_observation"),
        stdout=stdout.payload,
        stderr=stderr.payload,
        command=command,
        cwd=cwd,
        process_contract=process_contract,
    )
    journal_response = _validate_durable_journal_response(
        observed.get("durable_process_journal_response"), arm=arm
    )
    expected = _result_material(
        arm,
        arm_descriptor=arm_descriptor,
        fence_descriptor=fence_descriptor,
        fence=fence,
        stdout_descriptor=stdout.file_descriptor(),
        stderr_descriptor=stderr.file_descriptor(),
        process_observation=process,
        evidence_descriptors=_evidence_descriptors(evidence),
        durable_journal_response=journal_response,
    )
    if observed != expected:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication launcher result is tampered, replayed, or crossbound"
        )
    _validate_self_hash(observed, "result_sha256", label="launcher result")
    return copy.deepcopy(expected)


def _validate_receipt_material(
    observed: Any,
    *,
    arm: Mapping[str, Any],
    arm_descriptor: Mapping[str, Any],
    fence: Mapping[str, Any],
    fence_descriptor: Mapping[str, Any],
    stdout: _HeldFile,
    stderr: _HeldFile,
    result: Mapping[str, Any],
    result_descriptor: Mapping[str, Any],
    evidence: Sequence[_HeldFile],
) -> dict[str, Any]:
    expected = _receipt_material(
        arm,
        arm_descriptor=arm_descriptor,
        fence_descriptor=fence_descriptor,
        fence=fence,
        stdout_descriptor=stdout.file_descriptor(),
        stderr_descriptor=stderr.file_descriptor(),
        result_descriptor=result_descriptor,
        result=result,
        evidence_descriptors=_evidence_descriptors(evidence),
    )
    if type(observed) is not dict or observed != expected:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication output receipt is tampered, replayed, or crossbound"
        )
    _validate_self_hash(observed, "receipt_sha256", label="output receipt")
    return copy.deepcopy(expected)


def run_or_resume_backend_publication_engineering_transaction_v3(
    *,
    project_root: Path,
    output_dir: Path,
    expected_arm_contract_file_sha256: str,
    execution_scope: str,
    expected_coordinate: Mapping[str, Any],
    expected_python_executable: Mapping[str, Any],
    expected_publication_launcher: Mapping[str, Any],
    expected_launcher_invocation_sha256: str,
    expected_backend_runtime_grant_sha256: str,
    expected_identity_artifact_binding_sha256: str,
    expected_cell_identity_sha256: str,
    expected_validation_record_sha256: str,
    expected_runtime_binding_identity_sha256: str,
    expected_dispatch_resolution_sha256: str,
    expected_full_publication_execution_binding: Mapping[str, Any],
    expected_resource_capability_grant_sha256: str,
    expected_model_parity_grant_sha256: str,
    expected_model_parity_acceptance_binding_sha256: str,
    expected_runtime_inputs: Mapping[str, Any],
    expected_launcher_evidence_files: Iterable[str],
    _fault_hook: Callable[[str], None] | None = None,
    _allow_spawn: bool = True,
    _allow_finalize: bool = True,
) -> dict[str, Any]:
    """Run or conservatively resume one externally pinned synthetic v3 arm.

    Once the launch fence is observably committed, a missing exact result is
    deliberately ambiguous and is never relaunched.  An exact result without a
    receipt is finalized without a child process.  A committed transaction is
    validated read-only.  Power-loss at-most-once semantics remain explicitly
    unattested, including on Windows where portable parent-directory fsync is
    unavailable.
    """

    if execution_scope != NONPUBLICATION_ENGINEERING_SCOPE:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication v3 execution is restricted to synthetic nonpublication scope"
        )
    root_path = Path(project_root)
    output_path = Path(output_dir)
    expected_file_sha = _valid_sha(
        expected_arm_contract_file_sha256, label="arm contract raw file"
    )
    evidence_names = sorted(
        _direct_child_name(item, label="launcher evidence")
        for item in expected_launcher_evidence_files
    )
    if not evidence_names or len({name.casefold() for name in evidence_names}) != len(evidence_names):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication expected evidence set is invalid"
        )
    if len(evidence_names) > MAX_EVIDENCE_FILES:
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication expected evidence set exceeds its entry bound"
        )
    _assert_plain_output_chain(root_path, output_path)

    output_hold: _DirectoryHold | None = None
    project_hold: _DirectoryHold | None = None
    directory_holds: list[_DirectoryHold] = []
    file_holds: list[_HeldFile] = []
    primary: BaseException | None = None
    semantic_commit = False
    try:
        output_hold = _DirectoryHold(output_path)
        project_hold = _DirectoryHold(root_path)
        directory_holds.extend([output_hold, project_hold])
        arm_hold = _HeldFile(
            output_hold,
            ARM_CONTRACT_FILENAME,
            label="arm contract",
            limit=MAX_CONTROL_JSON_BYTES,
            allow_empty=False,
        )
        file_holds.append(arm_hold)
        if arm_hold.digest != expected_file_sha:
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication arm contract raw file SHA-256 drifted"
            )
        try:
            arm = parse_backend_publication_arm_contract_v3_bytes(
                arm_hold.payload,
                expected_file_sha256=expected_file_sha,
            )
            arm = validate_backend_publication_arm_contract_v3(
                arm,
                expected_dispatch_resolution_sha256=(
                    expected_dispatch_resolution_sha256
                ),
                expected_full_publication_execution_binding=(
                    expected_full_publication_execution_binding
                ),
                expected_resource_capability_grant_sha256=(
                    expected_resource_capability_grant_sha256
                ),
                expected_model_parity_grant_sha256=(
                    expected_model_parity_grant_sha256
                ),
                expected_model_parity_acceptance_binding_sha256=(
                    expected_model_parity_acceptance_binding_sha256
                ),
                expected_runtime_inputs=expected_runtime_inputs,
                expected_launcher_evidence_files=evidence_names,
            )
        except BackendPublicationDispatchV3Error as error:
            raise BackendPublicationOutputTransactionV3Error(
                f"backend publication arm contract external binding failed: {error}"
            ) from error
        runtime = arm["runtime_inputs"]
        if (
            runtime["project_root"] != str(root_path)
            or runtime["output_dir"] != str(output_path)
            or runtime["arm_contract_path"]
            != str(output_path / ARM_CONTRACT_FILENAME)
        ):
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction paths differ from the pinned arm"
            )
        resolution = arm["dispatch_resolution"]
        try:
            command = build_backend_publication_command_v3(
                resolution,
                expected_coordinate=expected_coordinate,
                expected_python_executable=expected_python_executable,
                expected_publication_launcher=expected_publication_launcher,
                expected_launcher_invocation_sha256=(
                    expected_launcher_invocation_sha256
                ),
                expected_backend_runtime_grant_sha256=(
                    expected_backend_runtime_grant_sha256
                ),
                expected_identity_artifact_binding_sha256=(
                    expected_identity_artifact_binding_sha256
                ),
                expected_cell_identity_sha256=expected_cell_identity_sha256,
                expected_validation_record_sha256=(
                    expected_validation_record_sha256
                ),
                expected_runtime_binding_identity_sha256=(
                    expected_runtime_binding_identity_sha256
                ),
                project_root=root_path,
                arm_contract_path=output_path / ARM_CONTRACT_FILENAME,
                arm_contract_file_sha256=expected_file_sha,
                output_dir=output_path,
            )
        except BackendPublicationDispatchV3Error as error:
            raise BackendPublicationOutputTransactionV3Error(
                f"backend publication v3 command binding failed: {error}"
            ) from error

        python_parent, python_hold = _external_file_hold(
            root_path,
            expected_python_executable,
            label="Python executable",
        )
        launcher_parent, launcher_hold = _external_file_hold(
            root_path,
            expected_publication_launcher,
            label="publication launcher",
        )
        directory_holds.extend([python_parent, launcher_parent])
        file_holds.extend([python_hold, launcher_hold])
        arm_descriptor = arm_hold.file_descriptor()
        states = _expected_sets(evidence_names)
        observed_names = output_hold.names()

        def leaf_fault(label: str) -> Callable[[str], None] | None:
            if _fault_hook is None:
                return None
            return lambda step: _fault_hook(f"{label}:{step}")

        resumable_partial = (
            LAUNCH_FENCE_FILENAME in observed_names
            and observed_names < states["result"]
            and observed_names <= states["result"]
        )
        if observed_names == states["prepared"] or resumable_partial:
            if _allow_spawn is not True:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication read-only validation cannot spawn or attach a pending arm"
                )
            fence = _fence_material(arm, arm_descriptor=arm_descriptor)
            fence_payload = _canonical_file_bytes(fence)
            fence_hold: _HeldFile | None = None

            def commit_launch_barrier() -> None:
                nonlocal fence_hold
                if fence_hold is not None:
                    fence_hold.verify()
                    return
                fence_hold = _create_new_held(
                    output_hold,
                    LAUNCH_FENCE_FILENAME,
                    fence_payload,
                    label="launch fence",
                    limit=MAX_CONTROL_JSON_BYTES,
                    allow_empty=False,
                    after_publish_step=leaf_fault("launch_fence"),
                )
                file_holds.append(fence_hold)
                if _fault_hook is not None:
                    _fault_hook("after_fence_commit")

            journal_name = (
                ".backend-publication-process-journal-v1-"
                + str(arm["contract_sha256"])
            )
            try:
                with PhysicalRootCustodyV1.open(
                    output_path.parent,
                    label="backend process journal parent",
                ) as journal_parent:
                    journal_path, _created = journal_parent.ensure_directory_owned(
                        journal_name,
                        label="backend process journal",
                    )
            except PublicationPhysicalIoV1Error as error:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend process journal cannot be held"
                ) from error
            try:
                process_run = run_backend_publication_process_v3(
                    command,
                    cwd=root_path,
                    durable_journal_directory=journal_path,
                    launch_authorization_path=(
                        output_path / LAUNCH_FENCE_FILENAME
                    ),
                    launch_authorization_sha256=hashlib.sha256(
                        fence_payload
                    ).hexdigest(),
                    launch_barrier=commit_launch_barrier,
                )
            except BackendPublicationProcessSupervisorV3Error as error:
                raise BackendPublicationOutputTransactionV3Error(
                    f"backend publication synthetic v3 process failed: {error}"
                ) from error
            if fence_hold is None:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend process journal returned without launch fence custody"
                )
            process_observation = _validate_process_observation(
                process_run.observation,
                stdout=process_run.stdout,
                stderr=process_run.stderr,
                command=command,
                cwd=root_path,
                process_contract=resolution["launcher_invocation"][
                    "process_contract"
                ],
            )
            if _fault_hook is not None:
                _fault_hook("after_process_success")
            arm_hold.verify()
            python_hold.verify()
            launcher_hold.verify()
            python_parent.verify()
            launcher_parent.verify()
            expected_after_child = states["fenced"] | set(evidence_names)
            current_after_child = output_hold.names()
            if not (
                expected_after_child <= current_after_child
                and current_after_child <= states["captured"]
            ):
                raise BackendPublicationOutputTransactionV3Error(
                    "launcher-completed transaction namespace drifted"
                )
            evidence_holds = _open_evidence(output_hold, evidence_names)
            file_holds.extend(evidence_holds)
            evidence_descriptors = _evidence_descriptors(evidence_holds)
            stdout_hold = _create_new_held(
                output_hold,
                CAPTURE_STDOUT_FILENAME,
                process_run.stdout,
                label="stdout capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
                after_publish_step=leaf_fault("stdout_capture"),
            )
            stderr_hold = _create_new_held(
                output_hold,
                CAPTURE_STDERR_FILENAME,
                process_run.stderr,
                label="stderr capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
                after_publish_step=leaf_fault("stderr_capture"),
            )
            file_holds.extend([stdout_hold, stderr_hold])
            _assert_exact_namespace(output_hold, states["captured"], label="captured transaction")
            if _fault_hook is not None:
                _fault_hook("after_captures_commit")
            result = _result_material(
                arm,
                arm_descriptor=arm_descriptor,
                fence_descriptor=fence_hold.file_descriptor(),
                fence=fence,
                stdout_descriptor=stdout_hold.file_descriptor(),
                stderr_descriptor=stderr_hold.file_descriptor(),
                process_observation=process_observation,
                evidence_descriptors=evidence_descriptors,
                durable_journal_response=_validate_durable_journal_response(
                    process_run.durable_journal_response,
                    arm=arm,
                ),
            )
            result_hold = _create_new_held(
                output_hold,
                LAUNCHER_RESULT_FILENAME,
                _canonical_file_bytes(result),
                label="launcher result",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
                after_publish_step=leaf_fault("launcher_result"),
            )
            file_holds.append(result_hold)
            _assert_exact_namespace(output_hold, states["result"], label="result transaction")
            if _fault_hook is not None:
                _fault_hook("after_result_commit")
        elif (
            observed_names == states["result"]
            or observed_names == states["committed"]
        ):
            fence_hold = _HeldFile(
                output_hold,
                LAUNCH_FENCE_FILENAME,
                label="launch fence",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            stdout_hold = _HeldFile(
                output_hold,
                CAPTURE_STDOUT_FILENAME,
                label="stdout capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            stderr_hold = _HeldFile(
                output_hold,
                CAPTURE_STDERR_FILENAME,
                label="stderr capture",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=True,
            )
            evidence_holds = _open_evidence(output_hold, evidence_names)
            result_hold = _HeldFile(
                output_hold,
                LAUNCHER_RESULT_FILENAME,
                label="launcher result",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.extend(
                [fence_hold, stdout_hold, stderr_hold, *evidence_holds, result_hold]
            )
            fence = _validate_fence(
                _load_control(fence_hold, label="launch fence"),
                arm=arm,
                arm_descriptor=arm_descriptor,
            )
            result = _validate_result_material(
                _load_control(result_hold, label="launcher result"),
                arm=arm,
                arm_descriptor=arm_descriptor,
                fence=fence,
                fence_descriptor=fence_hold.file_descriptor(),
                stdout=stdout_hold,
                stderr=stderr_hold,
                evidence=evidence_holds,
                command=command,
                cwd=root_path,
                process_contract=resolution["launcher_invocation"][
                    "process_contract"
                ],
            )
        else:
            allowed_partial = set().union(*states.values())
            if observed_names <= allowed_partial and LAUNCH_FENCE_FILENAME in observed_names:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication transaction is ambiguous after its launch fence"
                )
            raise BackendPublicationOutputTransactionV3Error(
                "backend publication transaction namespace is invalid or contains extras"
            )

        if output_hold.names() == states["result"]:
            if _allow_finalize is not True:
                raise BackendPublicationOutputTransactionV3Error(
                    "backend publication read-only validation cannot finalize a result-only transaction"
                )
            # Receipt creation is the semantic commit boundary.  Every fallible
            # tree, byte, identity, and ACL observation therefore happens while
            # the namespace is still resumable as result-only.
            _assert_exact_namespace(
                output_hold, states["result"], label="precommit result transaction"
            )
            for held in file_holds:
                held.verify()
            for held_directory in directory_holds:
                held_directory.verify()
            _assert_exact_namespace(
                output_hold,
                states["result"],
                label="terminal precommit result transaction",
            )
            receipt = _receipt_material(
                arm,
                arm_descriptor=arm_descriptor,
                fence_descriptor=fence_hold.file_descriptor(),
                fence=fence,
                stdout_descriptor=stdout_hold.file_descriptor(),
                stderr_descriptor=stderr_hold.file_descriptor(),
                result_descriptor=result_hold.file_descriptor(),
                result=result,
                evidence_descriptors=_evidence_descriptors(evidence_holds),
            )
            receipt_payload = _canonical_file_bytes(receipt)
            receipt_descriptor = {
                "path": OUTPUT_RECEIPT_FILENAME,
                "size_bytes": len(receipt_payload),
                "sha256": hashlib.sha256(receipt_payload).hexdigest(),
            }
            authority = _authority_material(
                arm,
                receipt_descriptor=receipt_descriptor,
                receipt=receipt,
            )
            receipt_hold = _create_new_held(
                output_hold,
                OUTPUT_RECEIPT_FILENAME,
                receipt_payload,
                label="output receipt",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
                after_publish_step=leaf_fault("output_receipt"),
            )
            file_holds.append(receipt_hold)
            semantic_commit = True
            if _fault_hook is not None:
                _fault_hook("after_receipt_commit")
            _assert_exact_namespace(
                output_hold, states["committed"], label="committed transaction"
            )
            for held in file_holds:
                held.verify()
            for held_directory in directory_holds:
                held_directory.verify()
            _assert_exact_namespace(
                output_hold,
                states["committed"],
                label="terminal committed transaction",
            )
            return authority
        else:
            receipt_hold = _HeldFile(
                output_hold,
                OUTPUT_RECEIPT_FILENAME,
                label="output receipt",
                limit=MAX_CONTROL_JSON_BYTES,
                allow_empty=False,
            )
            file_holds.append(receipt_hold)
            receipt = _validate_receipt_material(
                _load_control(receipt_hold, label="output receipt"),
                arm=arm,
                arm_descriptor=arm_descriptor,
                fence=fence,
                fence_descriptor=fence_hold.file_descriptor(),
                stdout=stdout_hold,
                stderr=stderr_hold,
                result=result,
                result_descriptor=result_hold.file_descriptor(),
                evidence=evidence_holds,
            )
            _assert_exact_namespace(
                output_hold, states["committed"], label="committed transaction"
            )
            for held in file_holds:
                held.verify()
            for held_directory in directory_holds:
                held_directory.verify()
            _assert_exact_namespace(
                output_hold,
                states["committed"],
                label="terminal committed transaction",
            )
            authority = _authority_material(
                arm,
                receipt_descriptor=receipt_hold.file_descriptor(),
                receipt=receipt,
            )
            semantic_commit = True
            return authority
    except BaseException as error:
        primary = error
        raise
    finally:
        cleanup_primary = primary
        if cleanup_primary is None and semantic_commit:
            cleanup_primary = BackendPublicationOutputTransactionV3Error(
                "postcommit resource release is not attested"
            )
        try:
            _close_holds(file_holds, primary=cleanup_primary)
        finally:
            for held_directory in reversed(directory_holds):
                try:
                    held_directory.close(suppress=cleanup_primary is not None)
                except BaseException as close_error:
                    if cleanup_primary is None:
                        raise close_error


def validate_backend_publication_engineering_transaction_v3(**kwargs: Any) -> dict[str, Any]:
    """Read-only validate a committed transaction through the resume engine."""
    if any(
        name in kwargs for name in ("_allow_spawn", "_allow_finalize", "_fault_hook")
    ):
        raise BackendPublicationOutputTransactionV3Error(
            "backend publication read-only validation received unsafe private controls"
        )
    return run_or_resume_backend_publication_engineering_transaction_v3(
        **kwargs,
        _allow_spawn=False,
        _allow_finalize=False,
    )


__all__ = [
    "ARM_AUTHORITY_KIND",
    "BackendPublicationOutputTransactionV3Error",
    "FENCE_KIND",
    "MAX_CONTROL_JSON_BYTES",
    "MAX_EVIDENCE_AGGREGATE_BYTES",
    "MAX_EVIDENCE_FILE_BYTES",
    "MAX_EVIDENCE_FILES",
    "MAX_TRANSACTION_NAMESPACE_ENTRIES",
    "NONPUBLICATION_ENGINEERING_SCOPE",
    "PROCESS_OBSERVATION_DOMAIN",
    "PROCESS_OBSERVATION_FIELDS",
    "PROCESS_OBSERVATION_KIND",
    "RECEIPT_AUTHORITY_KIND",
    "RECEIPT_KIND",
    "RESULT_KIND",
    "prepare_backend_publication_engineering_transaction_v3",
    "run_or_resume_backend_publication_engineering_transaction_v3",
    "validate_backend_publication_engineering_transaction_v3",
]
