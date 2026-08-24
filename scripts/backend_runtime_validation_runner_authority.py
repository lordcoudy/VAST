#!/usr/bin/env python3
"""Pinned, non-authorizing authority for a hermetic validation runner."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _GENERIC_READ = 0x80000000
    _LIST_DIRECTORY = 0x0001
    _READ_ATTRIBUTES = 0x0080
    _SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _ATTR_REPARSE = 0x00000400
    _BACKUP_SEMANTICS = 0x02000000
    _OPEN_REPARSE_POINT = 0x00200000
    _FILE_TYPE_DISK = 0x0001
    _FILE_STANDARD_INFO = 1
    _FILE_ATTRIBUTE_TAG_INFO = 9
    _FILE_ID_INFO = 18
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _FileId128(ctypes.Structure):
        _fields_ = [("Identifier", ctypes.c_ubyte * 16)]

    class _FileIdInfo(ctypes.Structure):
        _fields_ = [("VolumeSerialNumber", ctypes.c_ulonglong),
                    ("FileId", _FileId128)]

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", wintypes.DWORD),
                    ("ReparseTag", wintypes.DWORD)]

    class _FileStandardInfo(ctypes.Structure):
        _fields_ = [("AllocationSize", ctypes.c_longlong),
                    ("EndOfFile", ctypes.c_longlong),
                    ("NumberOfLinks", wintypes.DWORD),
                    ("DeletePending", wintypes.BOOLEAN),
                    ("Directory", wintypes.BOOLEAN)]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _CREATE_FILE.restype = wintypes.HANDLE
    _GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandleEx
    _GET_FILE_INFORMATION.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _GET_FILE_INFORMATION.restype = wintypes.BOOL
    _GET_FILE_TYPE = _KERNEL32.GetFileType
    _GET_FILE_TYPE.argtypes = [wintypes.HANDLE]
    _GET_FILE_TYPE.restype = wintypes.DWORD
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _CLOSE_HANDLE.restype = wintypes.BOOL


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_runtime_validation_runner_authority"
ASSESSMENT_KIND = "vast_backend_runtime_validation_runner_authority_assessment"
BUNDLE_MANIFEST_KIND = "vast_backend_runtime_validation_bundle_manifest"
INVOCATION_KIND = "vast_backend_runtime_validation_runner_invocation_contract"
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_ARTIFACT_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_MANIFEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", "python_executable", "runner",
    "runtime_leaves", "runtime_leaf_set_sha256", "bundle_manifest_sha256",
})
_PROCESS_FIELDS = frozenset({
    "shell", "check", "environment", "cwd_source", "stdin", "stdout",
    "stderr", "close_fds", "accepted_exit_codes", "timeout_ms",
    "filesystem_writes", "network",
})
_INVOCATION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "runtime_kind", "argv_template",
    "required_env_keys", "process_contract", "invocation_sha256",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "runner_id",
    "runtime_bundle_manifest", "runtime_bundle_manifest_content",
    "runtime_leaves", "runtime_leaf_set_sha256", "python_executable",
    "runner", "invocation_contract",
    "supported_validator_authority_schema_version",
    "validation_protocol_identity_sha256", "input_schema_identity_sha256",
    "output_schema_identity_sha256", "deterministic",
    "runner_authority_sha256",
})

_ARGV_TEMPLATE = [
    "{python_executable}", "-I", "-S", "-B", "-X", "utf8",
    "{runner_path}", "--project-root", "{project_root}",
    "--runner-authority", "{runner_authority_path}",
    "--runner-authority-file-sha256", "{runner_authority_file_sha256}",
    "--runner-authority-sha256", "{runner_authority_sha256}",
    "--validator-authority", "{validator_authority_path}",
    "--validator-authority-file-sha256", "{validator_authority_file_sha256}",
    "--validator-authority-sha256", "{validator_authority_sha256}",
    "--request", "{request_path}",
    "--request-file-sha256", "{request_file_sha256}",
    "--request-sha256", "{request_sha256}",
]


class BackendRuntimeValidationRunnerAuthorityError(ValueError):
    """The validation runner authority is malformed or physically unsafe."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendRuntimeValidationRunnerAuthorityError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendRuntimeValidationRunnerAuthorityError(
            "runner authority is not canonical JSON"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _relative_path(value: Any) -> str:
    _require(type(value) is str and bool(value), "runner artifact path is invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    parts = posix.parts
    _require(
        "\\" not in value and ":" not in value and "\x00" not in value
        and not posix.is_absolute() and posix.anchor == ""
        and windows.drive == "" and windows.root == "" and windows.anchor == ""
        and posix.as_posix() == value and bool(parts)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and not any(ord(character) < 32 for character in part)
            and part.split(".", 1)[0].upper() not in _RESERVED
            for part in parts
        ),
        "runner artifact path is unsafe",
    )
    return value


def _descriptor(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             "runner artifact descriptor fields drifted")
    path = _relative_path(value.get("path"))
    size = value.get("size_bytes")
    _require(type(size) is int and 0 <= size <= MAX_ARTIFACT_BYTES,
             "runner artifact size is invalid")
    _require(_valid_sha(value.get("sha256")), "runner artifact sha256 is invalid")
    return {"path": path, "size_bytes": size, "sha256": value["sha256"]}


def _artifact(value: Any, *, semantic_file_hash: bool = True) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _ARTIFACT_FIELDS,
             "runner artifact reference fields drifted")
    descriptor = _descriptor(value.get("descriptor"))
    identity = value.get("content_identity_sha256")
    _require(_valid_sha(identity), "runner artifact content identity is invalid")
    if semantic_file_hash:
        _require(identity == descriptor["sha256"],
                 "runner artifact content identity drifted")
    return {"descriptor": descriptor, "content_identity_sha256": identity}


def _artifact_list(value: Any) -> list[dict[str, Any]]:
    _require(type(value) is list and bool(value), "runtime leaf list is invalid")
    leaves = [_artifact(item) for item in value]
    paths = [item["descriptor"]["path"] for item in leaves]
    folded_paths = [path.casefold() for path in paths]
    _require(paths == sorted(paths) and len(folded_paths) == len(set(folded_paths)),
             "runtime leaves are not sorted and unique")
    return leaves


def _require_distinct_artifact_paths(
    artifacts: Sequence[Mapping[str, Any]],
) -> None:
    paths = [item["descriptor"]["path"] for item in artifacts]
    folded_paths = [path.casefold() for path in paths]
    _require(len(folded_paths) == len(set(folded_paths)),
             "runner authority artifact paths alias")


def _manifest(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _MANIFEST_FIELDS,
             "runtime bundle manifest fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == 1
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == BUNDLE_MANIFEST_KIND,
             "runtime bundle manifest header drifted")
    interpreter = _artifact(value.get("python_executable"))
    runner = _artifact(value.get("runner"))
    leaves = _artifact_list(value.get("runtime_leaves"))
    _require_distinct_artifact_paths([interpreter, runner, *leaves])
    leaf_set_sha = value.get("runtime_leaf_set_sha256")
    _require(_valid_sha(leaf_set_sha)
             and leaf_set_sha == _canonical_sha(leaves),
             "runtime bundle manifest leaf set drifted")
    material = {
        "schema_version": 1, "artifact_kind": BUNDLE_MANIFEST_KIND,
        "python_executable": interpreter, "runner": runner,
        "runtime_leaves": leaves,
        "runtime_leaf_set_sha256": leaf_set_sha,
    }
    manifest_sha = value.get("bundle_manifest_sha256")
    _require(_valid_sha(manifest_sha),
             "runtime bundle manifest sha256 is invalid")
    unsigned = {
        key: copy.deepcopy(item) for key, item in value.items()
        if key != "bundle_manifest_sha256"
    }
    _require(unsigned == material,
             "runtime bundle manifest canonical material drifted")
    _require(manifest_sha == _canonical_sha(unsigned),
             "runtime bundle manifest self-hash drifted")
    material["bundle_manifest_sha256"] = manifest_sha
    return material


def runner_invocation_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": INVOCATION_KIND,
        "runtime_kind": "python3_isolated_argv_v1",
        "argv_template": list(_ARGV_TEMPLATE),
        "required_env_keys": [],
        "process_contract": {
            "shell": False, "check": False,
            "environment": "exact_empty_mapping",
            "cwd_source": "caller_supplied_canonical_project_root",
            "stdin": "DEVNULL", "stdout": "bounded_canonical_json_pipe",
            "stderr": "bounded_diagnostic_pipe", "close_fds": True,
            "accepted_exit_codes": [0], "timeout_ms": 30000,
            "filesystem_writes": "denied", "network": "denied",
        },
    }
    value["invocation_sha256"] = _canonical_sha(value)
    return value


def _validate_invocation(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _INVOCATION_FIELDS,
             "runner invocation fields drifted")
    _require(type(value.get("schema_version")) is int,
             "runner invocation schema version type drifted")
    for field in ("artifact_kind", "runtime_kind"):
        _require(type(value.get(field)) is str,
                 f"runner invocation {field} type drifted")
    argv = value.get("argv_template")
    required_env = value.get("required_env_keys")
    _require(type(argv) is list
             and all(type(item) is str for item in argv),
             "runner invocation argv types drifted")
    _require(type(required_env) is list
             and all(type(item) is str for item in required_env),
             "runner invocation environment key types drifted")
    process = value.get("process_contract")
    _require(type(process) is dict and set(process) == _PROCESS_FIELDS,
             "runner process contract fields drifted")
    for field in ("shell", "check", "close_fds"):
        _require(type(process.get(field)) is bool,
                 f"runner process {field} type drifted")
    for field in (
        "environment", "cwd_source", "stdin", "stdout", "stderr",
        "filesystem_writes", "network",
    ):
        _require(type(process.get(field)) is str,
                 f"runner process {field} type drifted")
    exit_codes = process.get("accepted_exit_codes")
    _require(type(exit_codes) is list
             and all(type(item) is int for item in exit_codes),
             "runner process exit code types drifted")
    _require(type(process.get("timeout_ms")) is int,
             "runner process timeout type drifted")
    invocation_sha = value.get("invocation_sha256")
    _require(_valid_sha(invocation_sha),
             "runner invocation sha256 is invalid")
    unsigned = {
        key: copy.deepcopy(item) for key, item in value.items()
        if key != "invocation_sha256"
    }
    _require(invocation_sha == _canonical_sha(unsigned),
             "runner invocation self-hash drifted")
    expected = runner_invocation_contract()
    _require(value == expected, "runner invocation contract drifted")
    return expected


def validate_backend_runtime_validation_runner_authority(
    value: Any, *, expected_runner_authority_sha256: str,
) -> dict[str, Any]:
    """Purely validate a closed authority against an external trusted pin."""
    _require(_valid_sha(expected_runner_authority_sha256),
             "expected runner authority pin is invalid")
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "validation runner authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "validation runner authority header drifted")
    _require(type(value.get("runner_id")) is str
             and _ID_RE.fullmatch(value["runner_id"]) is not None,
             "runner_id is invalid")
    manifest_ref = _artifact(value.get("runtime_bundle_manifest"),
                             semantic_file_hash=False)
    manifest = _manifest(value.get("runtime_bundle_manifest_content"))
    _require(manifest_ref["content_identity_sha256"]
             == manifest["bundle_manifest_sha256"],
             "runtime bundle manifest semantic identity drifted")
    leaves = _artifact_list(value.get("runtime_leaves"))
    interpreter = _artifact(value.get("python_executable"))
    runner = _artifact(value.get("runner"))
    _require(value.get("runtime_leaf_set_sha256") == _canonical_sha(leaves),
             "runtime authority leaf set drifted")
    _require(manifest["runtime_leaves"] == leaves
             and manifest["runtime_leaf_set_sha256"]
             == value["runtime_leaf_set_sha256"]
             and manifest["python_executable"] == interpreter
             and manifest["runner"] == runner,
             "runtime bundle manifest closure drifted")
    _require_distinct_artifact_paths([
        manifest_ref, interpreter, runner, *leaves,
    ])
    _validate_invocation(value.get("invocation_contract"))
    _require(type(value.get("supported_validator_authority_schema_version")) is int
             and value.get("supported_validator_authority_schema_version") == 1,
             "supported validator authority schema version drifted")
    for field in (
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256",
    ):
        _require(_valid_sha(value.get(field)), f"{field} is invalid")
    _require(value.get("deterministic") is True,
             "validation runner is not deterministic")
    observed = value.get("runner_authority_sha256")
    _require(_valid_sha(observed), "runner authority sha256 is invalid")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items()
                if key != "runner_authority_sha256"}
    _require(observed == _canonical_sha(unsigned), "runner authority self-hash drifted")
    _require(observed == expected_runner_authority_sha256,
             "runner authority does not match the trusted pin")
    return copy.deepcopy(value)


def _file_ref(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "descriptor": copy.deepcopy(dict(descriptor)),
        "content_identity_sha256": descriptor["sha256"],
    }


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise BackendRuntimeValidationRunnerAuthorityError(
            "project root is unavailable"
        ) from error
    _require(supplied == resolved and stat.S_ISDIR(info.st_mode)
             and not stat.S_ISLNK(info.st_mode)
             and not int(getattr(info, "st_file_attributes", 0)) & 0x400,
             "project root is not a canonical plain directory")
    return resolved, (int(info.st_dev), int(info.st_ino))


def _win_open(path: Path, *, directory: bool) -> int:
    access = (_LIST_DIRECTORY | _READ_ATTRIBUTES) if directory else (
        _GENERIC_READ | _READ_ATTRIBUTES
    )
    flags = _OPEN_REPARSE_POINT | (_BACKUP_SEMANTICS if directory else 0)
    ctypes.set_last_error(0)
    handle = _CREATE_FILE(
        str(path), access, _SHARE_READ, None, _OPEN_EXISTING, flags, None,
    )
    numeric = int(handle or 0)
    if not numeric or numeric == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return numeric


def _win_close(handle: int) -> None:
    ctypes.set_last_error(0)
    if not _CLOSE_HANDLE(wintypes.HANDLE(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _win_info(handle: int) -> dict[str, Any]:
    native = wintypes.HANDLE(handle)
    if _GET_FILE_TYPE(native) != _FILE_TYPE_DISK:
        raise OSError("runner artifact handle is not a disk file")
    identity = _FileIdInfo()
    attributes = _FileAttributeTagInfo()
    standard = _FileStandardInfo()
    for info_class, value in (
        (_FILE_ID_INFO, identity), (_FILE_ATTRIBUTE_TAG_INFO, attributes),
        (_FILE_STANDARD_INFO, standard),
    ):
        if not _GET_FILE_INFORMATION(
            native, info_class, ctypes.byref(value), ctypes.sizeof(value),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    return {
        "volume": int(identity.VolumeSerialNumber),
        "id": bytes(identity.FileId.Identifier),
        "attributes": int(attributes.FileAttributes),
        "reparse_tag": int(attributes.ReparseTag),
        "size": int(standard.EndOfFile), "nlink": int(standard.NumberOfLinks),
        "delete_pending": bool(standard.DeletePending),
        "directory": bool(standard.Directory),
    }


def _win_fingerprint(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value[key] for key in (
        "volume", "id", "attributes", "reparse_tag", "size", "nlink",
        "delete_pending", "directory",
    ))


def _win_validate(value: Mapping[str, Any], *, directory: bool, volume: int) -> None:
    _require(bool(value["directory"]) == directory
             and not bool(value["delete_pending"]),
             "runner artifact handle kind drifted")
    _require(not int(value["attributes"]) & _ATTR_REPARSE,
             "runner artifact path contains a reparse point")
    _require(int(value["volume"]) == volume, "runner artifact volume drifted")
    if not directory:
        _require(int(value["nlink"]) == 1,
                 "runner artifact has multiple hard links")


def _read_windows(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[int, bytes], bytes]:
    owned: list[int] = []
    held: list[tuple[Path, bool, tuple[Any, ...]]] = []
    descriptor_fd: int | None = None
    final_handle: int | None = None
    try:
        cursor = root
        root_handle = _win_open(cursor, directory=True)
        owned.append(root_handle)
        root_info = _win_info(root_handle)
        volume = int(root_info["volume"])
        _win_validate(root_info, directory=True, volume=volume)
        _require((volume, int.from_bytes(root_info["id"], "little"))
                 == root_identity, "project root changed before reading")
        seen = {(volume, root_info["id"])}
        held.append((cursor, True, _win_fingerprint(root_info)))
        for part in relative.parts[:-1]:
            cursor = cursor / part
            handle = _win_open(cursor, directory=True)
            owned.append(handle)
            info = _win_info(handle)
            _win_validate(info, directory=True, volume=volume)
            identity = (volume, info["id"])
            _require(identity not in seen, "runner artifact path aliases a parent")
            seen.add(identity)
            held.append((cursor, True, _win_fingerprint(info)))
        path = cursor / relative.parts[-1]
        final_handle = _win_open(path, directory=False)
        info = _win_info(final_handle)
        _win_validate(info, directory=False, volume=volume)
        identity = (volume, bytes(info["id"]))
        _require(identity not in seen, "runner artifact aliases a parent")
        fingerprint = _win_fingerprint(info)
        descriptor_fd = msvcrt.open_osfhandle(
            final_handle, os.O_RDONLY | int(getattr(os, "O_BINARY", 0)),
        )
        final_handle = None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_ARTIFACT_BYTES,
                     "runner artifact exceeds size limit")
            chunks.append(chunk)
        current = _win_info(int(msvcrt.get_osfhandle(descriptor_fd)))
        _require(_win_fingerprint(current) == fingerprint,
                 "runner artifact changed while reading")
        for expected_path, directory, expected in held + [(path, False, fingerprint)]:
            reopened: int | None = None
            reopen_primary = False
            try:
                reopened = _win_open(expected_path, directory=directory)
                observed = _win_info(reopened)
                _win_validate(observed, directory=directory, volume=volume)
                _require(_win_fingerprint(observed) == expected,
                         "runner artifact path changed while reading")
            except BaseException:
                reopen_primary = True
                raise
            finally:
                if reopened is not None:
                    try:
                        _win_close(reopened)
                    except OSError:
                        if not reopen_primary:
                            raise
        payload = b"".join(chunks)
        return ({"path": relative.as_posix(), "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}, identity, payload)
    except BackendRuntimeValidationRunnerAuthorityError:
        raise
    except (OSError, ValueError) as error:
        raise BackendRuntimeValidationRunnerAuthorityError(
            f"runner artifact physical read failed: {error}"
        ) from error
    finally:
        primary = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = close_error or error
        elif final_handle is not None:
            try:
                _win_close(final_handle)
            except OSError as error:
                close_error = close_error or error
        for handle in reversed(owned):
            try:
                _win_close(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary:
            raise BackendRuntimeValidationRunnerAuthorityError(
                "runner artifact handle cleanup failed"
            ) from close_error


def _read_posix(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[int, int], bytes]:
    _require(os.open in os.supports_dir_fd
             and all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")),
             "secure POSIX traversal is unavailable")
    held: list[int] = []
    verification: list[int] = []
    descriptor_fd: int | None = None
    try:
        directory_flags = (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | int(getattr(os, "O_CLOEXEC", 0)))
        root_fd = os.open(root, directory_flags)
        held.append(root_fd)
        root_info = os.fstat(root_fd)
        _require(stat.S_ISDIR(root_info.st_mode)
                 and (int(root_info.st_dev), int(root_info.st_ino)) == root_identity,
                 "project root changed before reading")
        seen = {root_identity}
        components: list[tuple[str, tuple[int, int]]] = []
        parent_fd = root_fd
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            held.append(child_fd)
            child_info = os.fstat(child_fd)
            identity = (int(child_info.st_dev), int(child_info.st_ino))
            _require(stat.S_ISDIR(child_info.st_mode)
                     and identity[0] == root_identity[0],
                     "runner artifact parent drifted")
            _require(identity not in seen, "runner artifact path aliases a parent")
            seen.add(identity)
            components.append((part, identity))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1,
                 "runner artifact is not a unique regular file")
        _require(identity[0] == root_identity[0] and identity not in seen,
                 "runner artifact identity/volume drifted")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_ARTIFACT_BYTES,
                     "runner artifact exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor_fd)
        _require(opened == after, "runner artifact changed while reading")
        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require((int(verify_root.st_dev), int(verify_root.st_ino)) == root_identity,
                 "project root changed while reading")
        for part, expected in components:
            child_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require((int(child_info.st_dev), int(child_info.st_ino)) == expected,
                     "runner artifact path component changed")
            verify_parent = child_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification.append(verify_fd)
        _require(os.fstat(verify_fd) == after,
                 "runner artifact path changed while reading")
        payload = b"".join(chunks)
        return ({"path": relative.as_posix(), "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}, identity, payload)
    except BackendRuntimeValidationRunnerAuthorityError:
        raise
    except OSError as error:
        raise BackendRuntimeValidationRunnerAuthorityError(
            f"runner artifact physical read failed: {error}"
        ) from error
    finally:
        primary = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = close_error or error
        for handle in reversed(verification + held):
            try:
                os.close(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary:
            raise BackendRuntimeValidationRunnerAuthorityError(
                "runner artifact descriptor cleanup failed"
            ) from close_error


def _physical_file(
    root: Path, root_identity: tuple[int, int], relative: str,
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    safe = PurePosixPath(_relative_path(relative))
    return (_read_windows(root, safe, root_identity) if os.name == "nt"
            else _read_posix(root, safe, root_identity))


def _physical_authority_material(
    *, project_root: Path, manifest_path: str, leaf_paths: Sequence[str],
    interpreter_path: str, runner_path: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]],
           dict[str, Any], dict[str, Any]]:
    root, root_identity = _root(project_root)
    paths = [manifest_path, interpreter_path, runner_path, *leaf_paths]
    safe_paths = [_relative_path(item) for item in paths]
    folded_paths = [path.casefold() for path in safe_paths]
    _require(len(folded_paths) == len(set(folded_paths)),
             "runner authority artifact paths alias")
    identities: set[tuple[Any, ...]] = set()
    total = 0
    observed: dict[str, tuple[dict[str, Any], bytes]] = {}
    for relative in safe_paths:
        descriptor, identity, payload = _physical_file(root, root_identity, relative)
        _require(identity not in identities,
                 "runner authority artifacts alias physically")
        identities.add(identity)
        total += descriptor["size_bytes"]
        _require(total <= MAX_TOTAL_BYTES,
                 "runner authority runtime closure exceeds total size limit")
        observed[relative] = (descriptor, payload)
    try:
        manifest_payload = observed[manifest_path][1]
        _require(manifest_payload.endswith(b"\n")
                 and manifest_payload[:-1] == manifest_payload.rstrip(b"\n"),
                 "runtime bundle manifest must have one trailing newline")
        raw_manifest = json.loads(manifest_payload[:-1].decode("utf-8"))
        _require(_canonical_bytes(raw_manifest) == manifest_payload[:-1],
                 "runtime bundle manifest file is not canonical JSON")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendRuntimeValidationRunnerAuthorityError(
            "runtime bundle manifest is invalid JSON"
        ) from error
    manifest = _manifest(raw_manifest)
    manifest_ref = {
        "descriptor": observed[manifest_path][0],
        "content_identity_sha256": manifest["bundle_manifest_sha256"],
    }
    interpreter = _file_ref(observed[interpreter_path][0])
    runner = _file_ref(observed[runner_path][0])
    leaves = sorted(
        (_file_ref(observed[path][0]) for path in leaf_paths),
        key=lambda value: value["descriptor"]["path"],
    )
    _require(manifest["python_executable"] == interpreter
             and manifest["runner"] == runner
             and manifest["runtime_leaves"] == leaves
             and manifest["runtime_leaf_set_sha256"] == _canonical_sha(leaves),
             "physical runtime bundle manifest closure drifted")
    return manifest_ref, manifest, leaves, interpreter, runner


def assess_backend_runtime_validation_runner_authority(
    value: Any, *, project_root: Path, expected_runner_authority_sha256: str,
) -> dict[str, Any]:
    """Check closure bytes only; never claim execution or sandbox authority."""
    authority_sha = value.get("runner_authority_sha256") if type(value) is dict else None
    runner_id = value.get("runner_id") if type(value) is dict else None
    checked = 0
    blockers: list[str] = []
    try:
        authority = validate_backend_runtime_validation_runner_authority(
            value,
            expected_runner_authority_sha256=expected_runner_authority_sha256,
        )
        expected_paths = [
            item["descriptor"]["path"] for item in (
                authority["runtime_bundle_manifest"],
                authority["python_executable"], authority["runner"],
                *authority["runtime_leaves"],
            )
        ]
        material = _physical_authority_material(
            project_root=project_root,
            manifest_path=expected_paths[0],
            interpreter_path=expected_paths[1], runner_path=expected_paths[2],
            leaf_paths=expected_paths[3:],
        )
        observed = [material[0], material[3], material[4], *material[2]]
        expected = [
            authority["runtime_bundle_manifest"], authority["python_executable"],
            authority["runner"], *authority["runtime_leaves"],
        ]
        _require(observed == expected
                 and material[1] == authority["runtime_bundle_manifest_content"],
                 "validation runner authority closure drifted physically")
        checked = len(observed)
    except (BackendRuntimeValidationRunnerAuthorityError, OSError, ValueError) as error:
        blockers.append(str(error))
    return {
        "schema_version": 1, "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if not blockers else "blocked",
        "runner_authority_sha256": authority_sha, "runner_id": runner_id,
        "checked_artifact_count": checked,
        "blockers": sorted(dict.fromkeys(blockers)),
        "individual_artifact_reads_handle_bound": not blockers,
        "atomic_runtime_closure_snapshot_validated": False,
        "interpreter_execution_validated": False,
        "sandbox_enforcement_validated": False,
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }


def build_backend_runtime_validation_runner_authority(
    *, project_root: Path, runner_id: str,
    runtime_bundle_manifest_path: str, runtime_leaf_paths: Sequence[str],
    python_executable_path: str, runner_path: str,
    validation_protocol_identity_sha256: str,
    input_schema_identity_sha256: str,
    output_schema_identity_sha256: str,
) -> dict[str, Any]:
    """Derive authority from an existing exact physical runtime closure."""
    _require(type(runtime_leaf_paths) in {list, tuple} and bool(runtime_leaf_paths),
             "runtime leaf paths are invalid")
    manifest_ref, manifest, leaves, interpreter, runner = (
        _physical_authority_material(
            project_root=project_root,
            manifest_path=runtime_bundle_manifest_path,
            leaf_paths=list(runtime_leaf_paths),
            interpreter_path=python_executable_path, runner_path=runner_path,
        )
    )
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "runner_id": runner_id,
        "runtime_bundle_manifest": manifest_ref,
        "runtime_bundle_manifest_content": manifest,
        "runtime_leaves": leaves,
        "runtime_leaf_set_sha256": _canonical_sha(leaves),
        "python_executable": interpreter, "runner": runner,
        "invocation_contract": runner_invocation_contract(),
        "supported_validator_authority_schema_version": 1,
        "validation_protocol_identity_sha256":
            validation_protocol_identity_sha256,
        "input_schema_identity_sha256": input_schema_identity_sha256,
        "output_schema_identity_sha256": output_schema_identity_sha256,
        "deterministic": True,
    }
    material["runner_authority_sha256"] = _canonical_sha(material)
    validate_backend_runtime_validation_runner_authority(
        material,
        expected_runner_authority_sha256=material["runner_authority_sha256"],
    )
    assessment = assess_backend_runtime_validation_runner_authority(
        material, project_root=project_root,
        expected_runner_authority_sha256=material["runner_authority_sha256"],
    )
    if assessment["status"] != "physically_valid":
        raise BackendRuntimeValidationRunnerAuthorityError(
            "validation runner authority physical assessment blocked: "
            + ";".join(assessment["blockers"])
        )
    return material


__all__ = [
    "ARTIFACT_KIND", "ASSESSMENT_KIND", "BUNDLE_MANIFEST_KIND",
    "BackendRuntimeValidationRunnerAuthorityError",
    "assess_backend_runtime_validation_runner_authority",
    "build_backend_runtime_validation_runner_authority",
    "runner_invocation_contract",
    "validate_backend_runtime_validation_runner_authority",
]
