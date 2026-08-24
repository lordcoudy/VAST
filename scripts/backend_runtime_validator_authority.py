#!/usr/bin/env python3
"""Pinned, non-authorizing authority for a local qualification validator."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_runtime_cell_validator_authority"
ASSESSMENT_KIND = "vast_backend_runtime_cell_validator_authority_assessment"
SUPPORTED_QUALIFICATION_SCHEMA_VERSION = 3
MAX_IMPLEMENTATION_BYTES = 64 * 1024 * 1024
TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "validator_id", "implementation",
    "validation_protocol_identity_sha256", "input_schema_identity_sha256",
    "output_schema_identity_sha256", "supported_qualification_schema_version",
    "deterministic", "authority_sha256",
})
IMPLEMENTATION_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_REPARSE_ATTRIBUTE = 0x400

if os.name == "nt":
    _WIN_GENERIC_READ = 0x80000000
    _WIN_FILE_LIST_DIRECTORY = 0x0001
    _WIN_FILE_READ_ATTRIBUTES = 0x0080
    _WIN_FILE_SHARE_READ = 0x00000001
    _WIN_OPEN_EXISTING = 3
    _WIN_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _WIN_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _WIN_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _WIN_FILE_TYPE_DISK = 0x0001
    _WIN_FILE_STANDARD_INFO = 1
    _WIN_FILE_ATTRIBUTE_TAG_INFO = 9
    _WIN_FILE_ID_INFO = 18
    _WIN_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class _WinFileId128(ctypes.Structure):
        _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

    class _WinFileIdInfo(ctypes.Structure):
        _fields_ = [
            ("VolumeSerialNumber", ctypes.c_ulonglong),
            ("FileId", _WinFileId128),
        ]

    class _WinFileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    class _WinFileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("AllocationSize", ctypes.c_longlong),
            ("EndOfFile", ctypes.c_longlong),
            ("NumberOfLinks", wintypes.DWORD),
            ("DeletePending", wintypes.BOOLEAN),
            ("Directory", wintypes.BOOLEAN),
        ]

    _WIN_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WIN_CREATE_FILE = _WIN_KERNEL32.CreateFileW
    _WIN_CREATE_FILE.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _WIN_CREATE_FILE.restype = wintypes.HANDLE
    _WIN_GET_FILE_INFORMATION = _WIN_KERNEL32.GetFileInformationByHandleEx
    _WIN_GET_FILE_INFORMATION.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _WIN_GET_FILE_INFORMATION.restype = wintypes.BOOL
    _WIN_GET_FILE_TYPE = _WIN_KERNEL32.GetFileType
    _WIN_GET_FILE_TYPE.argtypes = [wintypes.HANDLE]
    _WIN_GET_FILE_TYPE.restype = wintypes.DWORD
    _WIN_CLOSE_HANDLE = _WIN_KERNEL32.CloseHandle
    _WIN_CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _WIN_CLOSE_HANDLE.restype = wintypes.BOOL


class BackendRuntimeValidatorAuthorityError(ValueError):
    """The validator authority is malformed or physically untrusted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeValidatorAuthorityError(message)


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _canonical_sha(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeValidatorAuthorityError(
            "validator authority is not canonical JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _relative_path(value: Any) -> str:
    _require(type(value) is str and bool(value),
             "validator implementation path is invalid")
    _require(
        not value.startswith(("/", "\\"))
        and not value.endswith("/")
        and "\\" not in value
        and ":" not in value
        and "\x00" not in value
        and "//" not in value,
        "validator implementation path is not a strict relative POSIX path",
    )
    parts = value.split("/")
    _require(all(part not in ("", ".", "..") for part in parts),
             "validator implementation path traverses outside the project")
    for part in parts:
        _require(not part.endswith((".", " ")),
                 "validator implementation path has a Windows-ambiguous segment")
        _require(part.split(".", 1)[0].upper() not in _RESERVED,
                 "validator implementation path uses a reserved Windows name")
    return value


def _descriptor(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == DESCRIPTOR_FIELDS,
             "validator implementation descriptor fields drifted")
    path = _relative_path(value.get("path"))
    size = value.get("size_bytes")
    _require(type(size) is int and 0 <= size <= MAX_IMPLEMENTATION_BYTES,
             "validator implementation size is invalid")
    _require(_valid_sha(value.get("sha256")),
             "validator implementation sha256 is invalid")
    return {"path": path, "size_bytes": size, "sha256": value["sha256"]}


def validate_backend_runtime_cell_validator_authority(
    value: Any, *, expected_authority_sha256: str,
) -> dict[str, Any]:
    """Purely validate a closed authority against an explicit trusted pin."""
    _require(_valid_sha(expected_authority_sha256),
             "expected validator authority pin is invalid")
    _require(type(value) is dict and set(value) == TOP_FIELDS,
             "backend runtime validator authority fields drifted")
    _require(value.get("schema_version") == SCHEMA_VERSION,
             "validator authority schema version drifted")
    _require(value.get("artifact_kind") == ARTIFACT_KIND,
             "validator authority artifact kind drifted")
    _require(
        type(value.get("validator_id")) is str
        and _ID_RE.fullmatch(value["validator_id"]) is not None,
        "validator_id is invalid",
    )
    implementation = value.get("implementation")
    _require(type(implementation) is dict
             and set(implementation) == IMPLEMENTATION_FIELDS,
             "validator implementation fields drifted")
    checked_descriptor = _descriptor(implementation.get("descriptor"))
    _require(
        implementation.get("content_identity_sha256")
        == checked_descriptor["sha256"],
        "validator implementation content identity drifted",
    )
    for field in (
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256",
    ):
        _require(_valid_sha(value.get(field)), f"{field} is invalid")
    _require(
        value.get("supported_qualification_schema_version")
        == SUPPORTED_QUALIFICATION_SCHEMA_VERSION,
        "supported qualification schema version drifted",
    )
    _require(value.get("deterministic") is True,
             "validator implementation is not deterministic")
    authority_sha = value.get("authority_sha256")
    _require(_valid_sha(authority_sha), "validator authority sha256 is invalid")
    material = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "authority_sha256"}
    _require(authority_sha == _canonical_sha(material),
             "validator authority self-hash drifted")
    _require(authority_sha == expected_authority_sha256,
             "validator authority does not match the trusted pin")
    return copy.deepcopy(value)


def _is_link_or_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0)) & _REPARSE_ATTRIBUTE
    )


def _fingerprint(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns),
        int(info.st_ctime_ns), int(getattr(info, "st_file_attributes", 0)),
        int(getattr(info, "st_reparse_tag", 0)),
    )


def _canonical_root(project_root: Path) -> tuple[Path, tuple[int, ...]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise BackendRuntimeValidatorAuthorityError(
            "project root is unavailable"
        ) from error
    _require(supplied == resolved, "project root is not canonical")
    _require(stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
             "project root is not a plain directory")
    return resolved, _fingerprint(info)


def _win_open_handle(
    path: Path, *, directory: bool, read_data: bool = False,
) -> int:
    if os.name != "nt":
        raise OSError("Windows handle traversal is unavailable")
    desired_access = (
        (_WIN_FILE_LIST_DIRECTORY | _WIN_FILE_READ_ATTRIBUTES)
        if directory else (_WIN_GENERIC_READ | _WIN_FILE_READ_ATTRIBUTES)
    )
    if read_data:
        desired_access |= _WIN_GENERIC_READ
    flags = _WIN_FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _WIN_FILE_FLAG_BACKUP_SEMANTICS
    ctypes.set_last_error(0)
    handle = _WIN_CREATE_FILE(
        str(path), desired_access, _WIN_FILE_SHARE_READ, None,
        _WIN_OPEN_EXISTING, flags, None,
    )
    numeric = int(handle or 0)
    if not numeric or numeric == _WIN_INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    return numeric


def _win_close_handle(handle: int) -> None:
    ctypes.set_last_error(0)
    if not _WIN_CLOSE_HANDLE(wintypes.HANDLE(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _win_query_handle(handle: int) -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("Windows handle traversal is unavailable")
    native = wintypes.HANDLE(handle)
    ctypes.set_last_error(0)
    if _WIN_GET_FILE_TYPE(native) != _WIN_FILE_TYPE_DISK:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error) if error else OSError(
            "handle is not a disk file"
        )
    identity = _WinFileIdInfo()
    attributes = _WinFileAttributeTagInfo()
    standard = _WinFileStandardInfo()
    for info_class, value in (
        (_WIN_FILE_ID_INFO, identity),
        (_WIN_FILE_ATTRIBUTE_TAG_INFO, attributes),
        (_WIN_FILE_STANDARD_INFO, standard),
    ):
        ctypes.set_last_error(0)
        if not _WIN_GET_FILE_INFORMATION(
            native, info_class, ctypes.byref(value), ctypes.sizeof(value),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    return {
        "volume_serial": int(identity.VolumeSerialNumber),
        "file_id": bytes(identity.FileId.Identifier),
        "file_attributes": int(attributes.FileAttributes),
        "reparse_tag": int(attributes.ReparseTag),
        "size": int(standard.EndOfFile),
        "nlink": int(standard.NumberOfLinks),
        "delete_pending": bool(standard.DeletePending),
        "is_directory": bool(standard.Directory),
    }


def _win_identity(info: Mapping[str, Any]) -> tuple[int, bytes]:
    return int(info["volume_serial"]), bytes(info["file_id"])


def _win_component_fingerprint(info: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        *_win_identity(info), int(info["file_attributes"]),
        int(info["reparse_tag"]), int(info["size"]), int(info["nlink"]),
        bool(info["delete_pending"]), bool(info["is_directory"]),
    )


def _win_validate_component(
    info: Mapping[str, Any], *, label: str, directory: bool,
    expected_volume: int | None,
) -> None:
    if int(info["file_attributes"]) & _WIN_FILE_ATTRIBUTE_REPARSE_POINT:
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} path contains a link/reparse point"
        )
    if bool(info["is_directory"]) != directory:
        kind = "directory" if directory else "regular file"
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} is not a {kind}"
        )
    if bool(info["delete_pending"]):
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} is delete-pending"
        )
    if (
        expected_volume is not None
        and int(info["volume_serial"]) != expected_volume
    ):
        raise BackendRuntimeValidatorAuthorityError(f"{label} volume drifted")


def _win_reopen_identity(
    path: Path, *, directory: bool, label: str, expected_volume: int,
) -> tuple[Any, ...]:
    handle: int | None = None
    primary_active = False
    try:
        handle = _win_open_handle(path, directory=directory, read_data=False)
        info = _win_query_handle(handle)
        _win_validate_component(
            info, label=label, directory=directory,
            expected_volume=expected_volume,
        )
        if not directory and int(info["nlink"]) != 1:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} hardlink alias appeared during fresh reopen"
            )
        return _win_component_fingerprint(info)
    except BaseException:
        primary_active = True
        raise
    finally:
        if handle is not None:
            try:
                _win_close_handle(handle)
            except OSError:
                if not primary_active:
                    raise


def _read_physical_descriptor_windows(
    root: Path, relative: PurePosixPath, *,
    expected_root_identity: tuple[int, int],
) -> dict[str, Any]:
    label = "validator implementation"
    held: list[tuple[int, Path, bool, tuple[Any, ...]]] = []
    owned_handles: list[int] = []
    descriptor_fd: int | None = None
    opened_final_handle: int | None = None
    final_identity: tuple[int, bytes] | None = None
    root_volume: int | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        cursor = root
        root_handle = _win_open_handle(cursor, directory=True)
        owned_handles.append(root_handle)
        root_native = _win_query_handle(root_handle)
        _win_validate_component(
            root_native, label="project root", directory=True,
            expected_volume=None,
        )
        root_volume = int(root_native["volume_serial"])
        root_identity = _win_identity(root_native)
        if (
            root_identity[0], int.from_bytes(root_identity[1], "little"),
        ) != expected_root_identity:
            raise BackendRuntimeValidatorAuthorityError(
                "project root changed before secure assessment"
            )
        held.append((
            root_handle, cursor, True,
            _win_component_fingerprint(root_native),
        ))
        seen = {root_identity}

        for part in relative.parts[:-1]:
            cursor = cursor / part
            parent_handle = _win_open_handle(cursor, directory=True)
            owned_handles.append(parent_handle)
            parent_native = _win_query_handle(parent_handle)
            _win_validate_component(
                parent_native, label=label, directory=True,
                expected_volume=root_volume,
            )
            identity = _win_identity(parent_native)
            if identity in seen:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} path contains a duplicate FileId"
                )
            seen.add(identity)
            held.append((
                parent_handle, cursor, True,
                _win_component_fingerprint(parent_native),
            ))

        path = cursor / relative.parts[-1]
        opened_final_handle = _win_open_handle(
            path, directory=False, read_data=True,
        )
        final_native = _win_query_handle(opened_final_handle)
        _win_validate_component(
            final_native, label=label, directory=False,
            expected_volume=root_volume,
        )
        final_identity = _win_identity(final_native)
        if final_identity in seen:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} path contains a duplicate FileId"
            )
        if int(final_native["nlink"]) != 1:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} has multiple hard links"
            )
        if not 0 <= int(final_native["size"]) <= MAX_IMPLEMENTATION_BYTES:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} size is invalid"
            )
        final_fingerprint = _win_component_fingerprint(final_native)

        descriptor_fd = msvcrt.open_osfhandle(
            opened_final_handle,
            os.O_RDONLY | int(getattr(os, "O_BINARY", 0)),
        )
        opened_final_handle = None
        opened = os.fstat(descriptor_fd)
        if (
            int(opened.st_dev) != final_identity[0]
            or int(opened.st_ino)
            != int.from_bytes(final_identity[1], "little")
            or not stat.S_ISREG(opened.st_mode)
        ):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} native/CRT handle identity drifted"
            )
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMPLEMENTATION_BYTES:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} exceeds the size limit"
                )
            digest.update(chunk)
        after = os.fstat(descriptor_fd)
        if _fingerprint(opened) != _fingerprint(after):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} changed while reading"
            )

        for handle, _, directory, expected in held:
            current = _win_query_handle(handle)
            _win_validate_component(
                current, label=label, directory=directory,
                expected_volume=root_volume,
            )
            if _win_component_fingerprint(current) != expected:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} held path component changed while reading"
                )
        current_final = _win_query_handle(int(msvcrt.get_osfhandle(descriptor_fd)))
        _win_validate_component(
            current_final, label=label, directory=False,
            expected_volume=root_volume,
        )
        if _win_component_fingerprint(current_final) != final_fingerprint:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} held file changed while reading"
            )

        expected_paths = [
            (path_value, directory, fingerprint)
            for _, path_value, directory, fingerprint in held
        ]
        expected_paths.append((path, False, final_fingerprint))
        for expected_path, directory, expected_fingerprint in expected_paths:
            if _win_reopen_identity(
                expected_path, directory=directory, label=label,
                expected_volume=root_volume,
            ) != expected_fingerprint:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} path component changed while reading"
                )
    except BackendRuntimeValidatorAuthorityError:
        raise
    except (OSError, ValueError) as error:
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} physical read failed: {error}"
        ) from error
    finally:
        primary_active = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = close_error or error
        elif opened_final_handle is not None:
            try:
                _win_close_handle(opened_final_handle)
            except OSError as error:
                close_error = close_error or error
        for handle in reversed(owned_handles):
            try:
                _win_close_handle(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary_active:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} native handle cleanup failed: {close_error}"
            ) from close_error
    return {
        "path": relative.as_posix(), "size_bytes": total,
        "sha256": digest.hexdigest(),
    }


def _read_physical_descriptor_posix(
    root: Path, relative: PurePosixPath, *,
    expected_root_identity: tuple[int, int],
) -> dict[str, Any]:
    label = "validator implementation"
    held: list[int] = []
    verification_handles: list[int] = []
    descriptor_fd: int | None = None
    opened: os.stat_result | None = None
    after: os.stat_result | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | int(getattr(os, "O_CLOEXEC", 0))
        )
        root_fd = os.open(root, directory_flags)
        held.append(root_fd)
        root_info = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or (int(root_info.st_dev), int(root_info.st_ino))
            != expected_root_identity
        ):
            raise BackendRuntimeValidatorAuthorityError(
                "project root changed before secure assessment"
            )
        parent_fd = root_fd
        component_identities: list[tuple[str, tuple[int, int]]] = []
        seen = {expected_root_identity}
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            held.append(child_fd)
            child_info = os.fstat(child_fd)
            identity = (int(child_info.st_dev), int(child_info.st_ino))
            if not stat.S_ISDIR(child_info.st_mode):
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} parent is not a directory"
                )
            if identity[0] != int(root_info.st_dev):
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} volume drifted"
                )
            if identity in seen:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} path contains a duplicate inode"
                )
            seen.add(identity)
            component_identities.append((part, identity))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        final_identity = (int(opened.st_dev), int(opened.st_ino))
        if not stat.S_ISREG(opened.st_mode):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} is not a regular file"
            )
        if int(opened.st_nlink) != 1:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} has multiple hard links"
            )
        if final_identity[0] != int(root_info.st_dev):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} volume drifted"
            )
        if final_identity in seen:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} path contains a duplicate inode"
            )
        if not 0 <= int(opened.st_size) <= MAX_IMPLEMENTATION_BYTES:
            raise BackendRuntimeValidatorAuthorityError(f"{label} size is invalid")
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMPLEMENTATION_BYTES:
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} exceeds the size limit"
                )
            digest.update(chunk)
        after = os.fstat(descriptor_fd)
        if _fingerprint(opened) != _fingerprint(after):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} changed while reading"
            )

        verify_parent = os.open(root, directory_flags)
        verification_handles.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        if (
            int(verify_root.st_dev), int(verify_root.st_ino)
        ) != expected_root_identity:
            raise BackendRuntimeValidatorAuthorityError(
                "project root changed while assessing validator authority"
            )
        for part, expected_identity in component_identities:
            next_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification_handles.append(next_fd)
            verify_info = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(verify_info.st_mode)
                or (int(verify_info.st_dev), int(verify_info.st_ino))
                != expected_identity
            ):
                raise BackendRuntimeValidatorAuthorityError(
                    f"{label} path component changed while reading"
                )
            verify_parent = next_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification_handles.append(verify_fd)
        verify_info = os.fstat(verify_fd)
        if (
            not stat.S_ISREG(verify_info.st_mode)
            or int(verify_info.st_nlink) != 1
            or _fingerprint(verify_info) != _fingerprint(after)
        ):
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} path component changed while reading"
            )
    except BackendRuntimeValidatorAuthorityError:
        raise
    except OSError as error:
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} physical read failed: {error}"
        ) from error
    finally:
        primary_active = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = close_error or error
        for handle in reversed(verification_handles):
            try:
                os.close(handle)
            except OSError as error:
                close_error = close_error or error
        for handle in reversed(held):
            try:
                os.close(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary_active:
            raise BackendRuntimeValidatorAuthorityError(
                f"{label} descriptor cleanup failed: {close_error}"
            ) from close_error
    if opened is None or after is None:
        raise BackendRuntimeValidatorAuthorityError(
            f"{label} secure traversal did not establish an identity"
        )
    return {
        "path": relative.as_posix(), "size_bytes": total,
        "sha256": digest.hexdigest(),
    }


def _physical_descriptor(project_root: Path, relative: str) -> dict[str, Any]:
    relative = _relative_path(relative)
    root, root_fingerprint = _canonical_root(project_root)
    expected_root_identity = (root_fingerprint[0], root_fingerprint[1])
    path = PurePosixPath(relative)
    if os.name == "nt":
        return _read_physical_descriptor_windows(
            root, path, expected_root_identity=expected_root_identity,
        )
    if (
        os.open not in os.supports_dir_fd
        or not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW"))
    ):
        raise BackendRuntimeValidatorAuthorityError(
            "validator implementation secure handle-bound traversal is unavailable"
        )
    return _read_physical_descriptor_posix(
        root, path, expected_root_identity=expected_root_identity,
    )


def assess_backend_runtime_cell_validator_authority(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
) -> dict[str, Any]:
    """Physically check the pinned leaf without authenticating its outputs."""
    authority_sha = value.get("authority_sha256") if type(value) is dict else None
    validator_id = value.get("validator_id") if type(value) is dict else None
    blockers: list[str] = []
    checked = 0
    try:
        authority = validate_backend_runtime_cell_validator_authority(
            value, expected_authority_sha256=expected_authority_sha256,
        )
        expected = authority["implementation"]["descriptor"]
        observed = _physical_descriptor(project_root, expected["path"])
        _require(observed == expected,
                 "validator implementation descriptor drifted physically")
        checked = 1
    except (BackendRuntimeValidatorAuthorityError, OSError, ValueError) as error:
        blockers.append(str(error))
    return {
        "schema_version": 1,
        "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if not blockers else "blocked",
        "authority_sha256": authority_sha,
        "validator_id": validator_id,
        "checked_artifact_count": checked,
        "blockers": sorted(dict.fromkeys(blockers)),
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }


def build_backend_runtime_cell_validator_authority(
    *, project_root: Path, validator_id: str, implementation_path: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str,
    output_schema_identity_sha256: str,
) -> dict[str, Any]:
    """Derive an authority from the physical local implementation file."""
    descriptor = _physical_descriptor(project_root, implementation_path)
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "validator_id": validator_id,
        "implementation": {
            "descriptor": descriptor,
            "content_identity_sha256": descriptor["sha256"],
        },
        "validation_protocol_identity_sha256": validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
        "supported_qualification_schema_version":
            SUPPORTED_QUALIFICATION_SCHEMA_VERSION,
        "deterministic": True,
    }
    material["authority_sha256"] = _canonical_sha(material)
    validate_backend_runtime_cell_validator_authority(
        material, expected_authority_sha256=material["authority_sha256"],
    )
    assessment = assess_backend_runtime_cell_validator_authority(
        material, project_root=project_root,
        expected_authority_sha256=material["authority_sha256"],
    )
    if assessment["status"] != "physically_valid":
        raise BackendRuntimeValidatorAuthorityError(
            "validator authority physical assessment blocked: "
            + ";".join(assessment["blockers"])
        )
    return material


__all__ = [
    "ARTIFACT_KIND", "ASSESSMENT_KIND", "SCHEMA_VERSION",
    "SUPPORTED_QUALIFICATION_SCHEMA_VERSION",
    "BackendRuntimeValidatorAuthorityError",
    "assess_backend_runtime_cell_validator_authority",
    "build_backend_runtime_cell_validator_authority",
    "validate_backend_runtime_cell_validator_authority",
]
