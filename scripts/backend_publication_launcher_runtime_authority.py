#!/usr/bin/env python3
"""Pinned, non-authorizing authority for one publication launcher closure."""
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
        _fields_ = [
            ("VolumeSerialNumber", ctypes.c_ulonglong),
            ("FileId", _FileId128),
        ]

    class _FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    class _FileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("AllocationSize", ctypes.c_longlong),
            ("EndOfFile", ctypes.c_longlong),
            ("NumberOfLinks", wintypes.DWORD),
            ("DeletePending", wintypes.BOOLEAN),
            ("Directory", wintypes.BOOLEAN),
        ]

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
ARTIFACT_KIND = "vast_backend_publication_launcher_runtime_authority"
ASSESSMENT_KIND = "vast_backend_publication_launcher_runtime_authority_assessment"
CLOSURE_MANIFEST_KIND = (
    "vast_backend_publication_launcher_runtime_closure_manifest"
)
CLOSURE_SET_KIND = "vast_backend_publication_launcher_runtime_closure_set"
LAUNCHER_INVOCATION_V3_SCHEMA_VERSION = 3
LAUNCHER_INVOCATION_V3_KIND = "vast_backend_publication_launcher_invocation_v3"
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_LEAVES = 4096
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_REF_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_MANIFEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "python_executable",
    "publication_launcher", "runtime_leaves", "runtime_closure_set_sha256",
    "publication_launcher_invocation_v3_sha256", "closure_manifest_sha256",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "system", "runtime_closure_manifest",
    "runtime_closure_manifest_content", "python_executable",
    "publication_launcher", "runtime_leaves", "runtime_closure_set_sha256",
    "publication_launcher_invocation_v3_sha256",
    "launcher_runtime_authority_sha256",
})


class BackendPublicationLauncherRuntimeAuthorityError(ValueError):
    """The launcher runtime authority or its physical closure is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendPublicationLauncherRuntimeAuthorityError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise BackendPublicationLauncherRuntimeAuthorityError(
            "launcher runtime authority is not canonical JSON"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _relative_path(value: Any, label: str = "launcher runtime artifact") -> str:
    _require(type(value) is str and bool(value), f"{label} path is invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    parts = posix.parts
    _require(
        "\\" not in value and ":" not in value and "\x00" not in value
        and "//" not in value and not value.endswith("/")
        and not posix.is_absolute() and posix.anchor == ""
        and windows.drive == "" and windows.root == "" and windows.anchor == ""
        and posix.as_posix() == value and bool(parts)
        and all(
            part not in ("", ".", "..") and not part.endswith((".", " "))
            and not any(ord(character) < 32 for character in part)
            and part.split(".", 1)[0].upper() not in _RESERVED
            for part in parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and 0 <= size <= MAX_ARTIFACT_BYTES,
             f"{label} size is invalid")
    return {
        "path": _relative_path(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _artifact_ref(
    value: Any, label: str, *, semantic_file_hash: bool = True,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REF_FIELDS,
             f"{label} reference fields drifted")
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} content")
    if semantic_file_hash:
        _require(identity == descriptor["sha256"],
                 f"{label} content identity drifted")
    return {"descriptor": descriptor, "content_identity_sha256": identity}


def _casefold_path_key(reference: Mapping[str, Any]) -> tuple[str, str]:
    path = reference["descriptor"]["path"]
    return path.casefold(), path


def _runtime_leaves(value: Any) -> list[dict[str, Any]]:
    _require(type(value) is list and 0 < len(value) <= MAX_RUNTIME_LEAVES,
             "launcher runtime leaf list is invalid")
    leaves = [_artifact_ref(item, "launcher runtime leaf") for item in value]
    _require(leaves == sorted(leaves, key=_casefold_path_key),
             "launcher runtime leaves are not canonically ordered")
    return leaves


def _closure_set(
    interpreter: Mapping[str, Any], launcher: Mapping[str, Any],
    leaves: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": CLOSURE_SET_KIND,
        "python_executable": copy.deepcopy(dict(interpreter)),
        "publication_launcher": copy.deepcopy(dict(launcher)),
        "runtime_leaves": copy.deepcopy(list(leaves)),
    }


def _unique_references(
    references: Sequence[Mapping[str, Any]], *,
    reserved_content_identities: set[str],
    manifest_identity: str,
) -> None:
    paths: set[str] = set()
    file_ids: set[str] = set()
    content_ids: set[str] = set()
    serialized: set[bytes] = set()
    for position, reference in enumerate(references):
        descriptor = reference["descriptor"]
        path_key = descriptor["path"].casefold()
        file_sha = descriptor["sha256"]
        content_sha = reference["content_identity_sha256"]
        encoded = _canonical_bytes(reference)
        _require(path_key not in paths,
                 "launcher runtime authority artifact paths alias")
        _require(file_sha not in file_ids,
                 "launcher runtime authority file identities alias")
        _require(content_sha not in content_ids,
                 "launcher runtime authority content identities alias")
        _require(encoded not in serialized,
                 "launcher runtime authority references alias")
        if position == 0:
            _require(content_sha == manifest_identity,
                     "closure manifest reference identity drifted")
        else:
            _require(content_sha not in reserved_content_identities,
                     "launcher runtime authority contains an identity cycle")
        paths.add(path_key)
        file_ids.add(file_sha)
        content_ids.add(content_sha)
        serialized.add(encoded)


def _manifest(
    value: Any, *, expected_system: str, expected_abi_sha: str,
    expected_manifest_sha: str, expected_set_sha: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _MANIFEST_FIELDS,
             "launcher runtime closure manifest fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == CLOSURE_MANIFEST_KIND,
             "launcher runtime closure manifest header drifted")
    _require(type(value.get("system")) is str
             and value.get("system") == expected_system,
             "launcher runtime closure manifest system drifted")
    interpreter = _artifact_ref(value.get("python_executable"),
                                "manifest python executable")
    launcher = _artifact_ref(value.get("publication_launcher"),
                             "manifest publication launcher")
    leaves = _runtime_leaves(value.get("runtime_leaves"))
    set_sha = _sha(value.get("runtime_closure_set_sha256"),
                   "manifest runtime closure set")
    _require(set_sha == _canonical_sha(_closure_set(interpreter, launcher, leaves))
             == expected_set_sha,
             "launcher runtime closure set identity drifted")
    abi_sha = _sha(value.get("publication_launcher_invocation_v3_sha256"),
                   "manifest publication launcher invocation v3")
    _require(abi_sha == expected_abi_sha,
             "launcher invocation v3 manifest pin drifted")
    material = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": CLOSURE_MANIFEST_KIND,
        "system": expected_system,
        "python_executable": interpreter,
        "publication_launcher": launcher,
        "runtime_leaves": leaves,
        "runtime_closure_set_sha256": set_sha,
        "publication_launcher_invocation_v3_sha256": abi_sha,
    }
    manifest_sha = _sha(value.get("closure_manifest_sha256"),
                        "closure manifest")
    _require(manifest_sha == _canonical_sha(material) == expected_manifest_sha,
             "launcher runtime closure manifest identity drifted")
    material["closure_manifest_sha256"] = manifest_sha
    return material


def _validate_expected(
    *, expected_authority_sha256: Any, expected_system: Any,
    expected_publication_launcher_invocation_v3_sha256: Any,
    expected_closure_manifest_sha256: Any,
    expected_runtime_closure_set_sha256: Any,
) -> tuple[str, str, str, str, str]:
    authority_sha = _sha(expected_authority_sha256,
                         "expected launcher runtime authority")
    _require(type(expected_system) is str and expected_system in SYSTEMS,
             "expected launcher runtime system is invalid")
    abi_sha = _sha(expected_publication_launcher_invocation_v3_sha256,
                   "expected launcher invocation v3")
    manifest_sha = _sha(expected_closure_manifest_sha256,
                        "expected closure manifest")
    set_sha = _sha(expected_runtime_closure_set_sha256,
                   "expected runtime closure set")
    _require(len({authority_sha, abi_sha, manifest_sha, set_sha}) == 4,
             "launcher runtime semantic trust pins alias")
    return authority_sha, expected_system, abi_sha, manifest_sha, set_sha


def validate_backend_publication_launcher_runtime_authority(
    value: Any, *, expected_authority_sha256: str, expected_system: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_closure_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
) -> dict[str, Any]:
    """Validate closed launcher closure content against mandatory trust pins."""
    authority_pin, system, abi_pin, manifest_pin, set_pin = _validate_expected(
        expected_authority_sha256=expected_authority_sha256,
        expected_system=expected_system,
        expected_publication_launcher_invocation_v3_sha256=(
            expected_publication_launcher_invocation_v3_sha256
        ),
        expected_closure_manifest_sha256=expected_closure_manifest_sha256,
        expected_runtime_closure_set_sha256=(
            expected_runtime_closure_set_sha256
        ),
    )
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "launcher runtime authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "launcher runtime authority header drifted")
    _require(type(value.get("system")) is str and value.get("system") == system,
             "launcher runtime authority system drifted")
    manifest_ref = _artifact_ref(
        value.get("runtime_closure_manifest"), "runtime closure manifest",
        semantic_file_hash=False,
    )
    manifest = _manifest(
        value.get("runtime_closure_manifest_content"),
        expected_system=system, expected_abi_sha=abi_pin,
        expected_manifest_sha=manifest_pin, expected_set_sha=set_pin,
    )
    _require(manifest_ref["content_identity_sha256"] == manifest_pin,
             "runtime closure manifest reference semantic identity drifted")
    interpreter = _artifact_ref(value.get("python_executable"),
                                "python executable")
    launcher = _artifact_ref(value.get("publication_launcher"),
                             "publication launcher")
    leaves = _runtime_leaves(value.get("runtime_leaves"))
    _require(manifest["python_executable"] == interpreter
             and manifest["publication_launcher"] == launcher
             and manifest["runtime_leaves"] == leaves,
             "launcher runtime authority manifest closure drifted")
    set_sha = _sha(value.get("runtime_closure_set_sha256"),
                   "runtime closure set")
    _require(set_sha == _canonical_sha(_closure_set(interpreter, launcher, leaves))
             == manifest["runtime_closure_set_sha256"] == set_pin,
             "launcher runtime authority closure set drifted")
    abi_sha = _sha(value.get("publication_launcher_invocation_v3_sha256"),
                   "publication launcher invocation v3")
    _require(abi_sha == manifest["publication_launcher_invocation_v3_sha256"]
             == abi_pin,
             "launcher runtime authority invocation v3 pin drifted")
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "system": system, "runtime_closure_manifest": manifest_ref,
        "runtime_closure_manifest_content": manifest,
        "python_executable": interpreter, "publication_launcher": launcher,
        "runtime_leaves": leaves, "runtime_closure_set_sha256": set_sha,
        "publication_launcher_invocation_v3_sha256": abi_sha,
    }
    observed = _sha(value.get("launcher_runtime_authority_sha256"),
                    "launcher runtime authority")
    _require(observed == _canonical_sha(normalized) == authority_pin,
             "launcher runtime authority self-hash or external pin drifted")
    normalized["launcher_runtime_authority_sha256"] = observed
    _unique_references(
        [manifest_ref, interpreter, launcher, *leaves],
        reserved_content_identities={observed, abi_pin, manifest_pin, set_pin},
        manifest_identity=manifest_pin,
    )
    return copy.deepcopy(normalized)


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise BackendPublicationLauncherRuntimeAuthorityError(
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
    ctypes.set_last_error(0)
    if _GET_FILE_TYPE(native) != _FILE_TYPE_DISK:
        raise OSError("launcher runtime artifact handle is not a disk file")
    identity = _FileIdInfo()
    attributes = _FileAttributeTagInfo()
    standard = _FileStandardInfo()
    for info_class, structure in (
        (_FILE_ID_INFO, identity),
        (_FILE_ATTRIBUTE_TAG_INFO, attributes),
        (_FILE_STANDARD_INFO, standard),
    ):
        ctypes.set_last_error(0)
        if not _GET_FILE_INFORMATION(
            native, info_class, ctypes.byref(structure), ctypes.sizeof(structure),
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


def _win_validate(value: Mapping[str, Any], *, directory: bool,
                  volume: int) -> None:
    _require(bool(value["directory"]) == directory
             and not bool(value["delete_pending"]),
             "launcher runtime artifact handle kind drifted")
    _require(not int(value["attributes"]) & _ATTR_REPARSE,
             "launcher runtime artifact path contains a reparse point")
    _require(int(value["volume"]) == volume,
             "launcher runtime artifact volume drifted")
    if not directory:
        _require(int(value["nlink"]) == 1,
                 "launcher runtime artifact has multiple hard links")


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
            _require(identity not in seen,
                     "launcher runtime artifact path aliases a parent")
            seen.add(identity)
            held.append((cursor, True, _win_fingerprint(info)))
        path = cursor / relative.parts[-1]
        final_handle = _win_open(path, directory=False)
        info = _win_info(final_handle)
        _win_validate(info, directory=False, volume=volume)
        identity = (volume, bytes(info["id"]))
        _require(identity not in seen,
                 "launcher runtime artifact aliases a parent")
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
                     "launcher runtime artifact exceeds size limit")
            chunks.append(chunk)
        current = _win_info(int(msvcrt.get_osfhandle(descriptor_fd)))
        _require(_win_fingerprint(current) == fingerprint,
                 "launcher runtime artifact changed while reading")
        for expected_path, is_directory, expected in held + [
            (path, False, fingerprint)
        ]:
            reopened: int | None = None
            reopen_primary = False
            try:
                reopened = _win_open(expected_path, directory=is_directory)
                observed = _win_info(reopened)
                _win_validate(observed, directory=is_directory, volume=volume)
                _require(_win_fingerprint(observed) == expected,
                         "launcher runtime artifact path changed while reading")
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
        return ({
            "path": relative.as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }, identity, payload)
    except BackendPublicationLauncherRuntimeAuthorityError:
        raise
    except (OSError, ValueError) as error:
        raise BackendPublicationLauncherRuntimeAuthorityError(
            f"launcher runtime artifact physical read failed: {error}"
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
            raise BackendPublicationLauncherRuntimeAuthorityError(
                "launcher runtime artifact handle cleanup failed"
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
                 and (int(root_info.st_dev), int(root_info.st_ino))
                 == root_identity,
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
                     "launcher runtime artifact parent drifted")
            _require(identity not in seen,
                     "launcher runtime artifact path aliases a parent")
            seen.add(identity)
            components.append((part, identity))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1,
                 "launcher runtime artifact is not a unique regular file")
        _require(identity[0] == root_identity[0] and identity not in seen,
                 "launcher runtime artifact identity/volume drifted")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_ARTIFACT_BYTES,
                     "launcher runtime artifact exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor_fd)
        _require(opened == after,
                 "launcher runtime artifact changed while reading")
        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require((int(verify_root.st_dev), int(verify_root.st_ino))
                 == root_identity, "project root changed while reading")
        for part, expected in components:
            child_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require((int(child_info.st_dev), int(child_info.st_ino)) == expected,
                     "launcher runtime artifact path component changed")
            verify_parent = child_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification.append(verify_fd)
        verify_info = os.fstat(verify_fd)
        _require(stat.S_ISREG(verify_info.st_mode)
                 and int(verify_info.st_nlink) == 1
                 and verify_info == after,
                 "launcher runtime artifact path changed while reading")
        payload = b"".join(chunks)
        return ({
            "path": relative.as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }, identity, payload)
    except BackendPublicationLauncherRuntimeAuthorityError:
        raise
    except OSError as error:
        raise BackendPublicationLauncherRuntimeAuthorityError(
            f"launcher runtime artifact physical read failed: {error}"
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
            raise BackendPublicationLauncherRuntimeAuthorityError(
                "launcher runtime artifact descriptor cleanup failed"
            ) from close_error


def _physical_file(
    root: Path, root_identity: tuple[int, int], relative: str,
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    safe = PurePosixPath(_relative_path(relative))
    return (_read_windows(root, safe, root_identity) if os.name == "nt"
            else _read_posix(root, safe, root_identity))


def _physical_material(
    *, project_root: Path, manifest_path: str, interpreter_path: str,
    launcher_path: str, leaf_paths: Sequence[str], expected_system: str,
    expected_abi_sha: str, expected_manifest_sha: str,
    expected_set_sha: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any],
           dict[str, Any], list[dict[str, Any]], int]:
    root, root_identity = _root(project_root)
    paths = [manifest_path, interpreter_path, launcher_path, *leaf_paths]
    safe_paths = [_relative_path(item) for item in paths]
    _require(len(safe_paths) == len({item.casefold() for item in safe_paths}),
             "launcher runtime authority artifact paths alias")
    _require(0 < len(leaf_paths) <= MAX_RUNTIME_LEAVES,
             "launcher runtime leaf list is invalid")
    identities: set[tuple[Any, ...]] = set()
    total = 0
    observed: dict[str, tuple[dict[str, Any], bytes]] = {}
    for relative in safe_paths:
        descriptor, identity, payload = _physical_file(
            root, root_identity, relative,
        )
        _require(identity not in identities,
                 "launcher runtime authority artifacts alias physically")
        identities.add(identity)
        total += descriptor["size_bytes"]
        _require(total <= MAX_TOTAL_BYTES,
                 "launcher runtime closure exceeds total size limit")
        observed[relative] = (descriptor, payload)
    try:
        manifest_payload = observed[manifest_path][1]
        _require(manifest_payload.endswith(b"\n")
                 and manifest_payload[:-1] == manifest_payload.rstrip(b"\n"),
                 "launcher runtime manifest must have exactly one trailing LF")
        raw_manifest = json.loads(manifest_payload[:-1].decode("utf-8"))
        _require(_canonical_bytes(raw_manifest) == manifest_payload[:-1],
                 "launcher runtime manifest file is not canonical JSON")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendPublicationLauncherRuntimeAuthorityError(
            "launcher runtime manifest is invalid JSON"
        ) from error
    manifest = _manifest(
        raw_manifest, expected_system=expected_system,
        expected_abi_sha=expected_abi_sha,
        expected_manifest_sha=expected_manifest_sha,
        expected_set_sha=expected_set_sha,
    )
    manifest_ref = {
        "descriptor": observed[manifest_path][0],
        "content_identity_sha256": manifest["closure_manifest_sha256"],
    }
    interpreter = {
        "descriptor": observed[interpreter_path][0],
        "content_identity_sha256": observed[interpreter_path][0]["sha256"],
    }
    launcher = {
        "descriptor": observed[launcher_path][0],
        "content_identity_sha256": observed[launcher_path][0]["sha256"],
    }
    leaves = sorted(({
        "descriptor": observed[path][0],
        "content_identity_sha256": observed[path][0]["sha256"],
    } for path in leaf_paths), key=_casefold_path_key)
    _require(manifest["python_executable"] == interpreter
             and manifest["publication_launcher"] == launcher
             and manifest["runtime_leaves"] == leaves
             and manifest["runtime_closure_set_sha256"]
             == _canonical_sha(_closure_set(interpreter, launcher, leaves)),
             "physical launcher runtime manifest closure drifted")
    return manifest_ref, manifest, interpreter, launcher, leaves, len(paths)


def _assessment(
    *, authority_sha: str, system: str, status: str, checked_count: int,
    blockers: Sequence[str], semantic_valid: bool, physical_valid: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": status,
        "launcher_runtime_authority_sha256": authority_sha,
        "system": system,
        "checked_artifact_count": checked_count,
        "blockers": sorted(set(blockers)),
        "authority_pin_validated": semantic_valid,
        "exact_system_validated": semantic_valid,
        "publication_launcher_invocation_v3_pin_validated": semantic_valid,
        "closure_manifest_physically_reconstructed": physical_valid,
        "individual_artifact_reads_handle_bound": physical_valid,
        "all_artifact_physical_identities_distinct": physical_valid,
        "atomic_runtime_closure_snapshot_validated": False,
        "atomic_execution_lease_established": False,
        "interpreter_execution_validated": False,
        "launcher_execution_validated": False,
        "launcher_abi_v3_behavior_validated": False,
        "publication_capable_validated": False,
        "execution_authorized": False,
    }


def assess_backend_publication_launcher_runtime_authority(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
    expected_system: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_closure_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
) -> dict[str, Any]:
    """Assess pinned bytes without executing or authorizing the launcher."""
    authority_sha = (expected_authority_sha256
                     if type(expected_authority_sha256) is str else "")
    system = expected_system if type(expected_system) is str else ""
    semantic_valid = False
    checked_count = 0
    blockers: list[str] = []
    try:
        normalized = validate_backend_publication_launcher_runtime_authority(
            value,
            expected_authority_sha256=expected_authority_sha256,
            expected_system=expected_system,
            expected_publication_launcher_invocation_v3_sha256=(
                expected_publication_launcher_invocation_v3_sha256
            ),
            expected_closure_manifest_sha256=(
                expected_closure_manifest_sha256
            ),
            expected_runtime_closure_set_sha256=(
                expected_runtime_closure_set_sha256
            ),
        )
        semantic_valid = True
        manifest_ref, manifest, interpreter, launcher, leaves, checked_count = (
            _physical_material(
                project_root=Path(project_root),
                manifest_path=normalized[
                    "runtime_closure_manifest"
                ]["descriptor"]["path"],
                interpreter_path=normalized[
                    "python_executable"
                ]["descriptor"]["path"],
                launcher_path=normalized[
                    "publication_launcher"
                ]["descriptor"]["path"],
                leaf_paths=[
                    item["descriptor"]["path"]
                    for item in normalized["runtime_leaves"]
                ],
                expected_system=expected_system,
                expected_abi_sha=(
                    expected_publication_launcher_invocation_v3_sha256
                ),
                expected_manifest_sha=expected_closure_manifest_sha256,
                expected_set_sha=expected_runtime_closure_set_sha256,
            )
        )
        _require(
            manifest_ref == normalized["runtime_closure_manifest"]
            and manifest == normalized["runtime_closure_manifest_content"]
            and interpreter == normalized["python_executable"]
            and launcher == normalized["publication_launcher"]
            and leaves == normalized["runtime_leaves"],
            "physical launcher runtime authority bytes drifted",
        )
        return _assessment(
            authority_sha=authority_sha, system=system,
            status="physically_valid", checked_count=checked_count,
            blockers=(), semantic_valid=True, physical_valid=True,
        )
    except (BackendPublicationLauncherRuntimeAuthorityError, OSError,
            TypeError, ValueError) as error:
        blockers.append(str(error) or type(error).__name__)
    return _assessment(
        authority_sha=authority_sha, system=system, status="blocked",
        checked_count=checked_count, blockers=blockers,
        semantic_valid=semantic_valid, physical_valid=False,
    )


def build_backend_publication_launcher_runtime_authority(
    *, project_root: Path, system: str,
    runtime_closure_manifest_path: str, python_executable_path: str,
    publication_launcher_path: str, runtime_leaf_paths: Sequence[str],
    expected_authority_sha256: str, expected_system: str,
    expected_publication_launcher_invocation_v3_sha256: str,
    expected_closure_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
) -> dict[str, Any]:
    """Build from an existing manifest using only caller-supplied trust pins."""
    authority_pin, pinned_system, abi_pin, manifest_pin, set_pin = (
        _validate_expected(
            expected_authority_sha256=expected_authority_sha256,
            expected_system=expected_system,
            expected_publication_launcher_invocation_v3_sha256=(
                expected_publication_launcher_invocation_v3_sha256
            ),
            expected_closure_manifest_sha256=(
                expected_closure_manifest_sha256
            ),
            expected_runtime_closure_set_sha256=(
                expected_runtime_closure_set_sha256
            ),
        )
    )
    _require(type(system) is str and system == pinned_system,
             "launcher runtime builder system drifted")
    _require(not isinstance(runtime_leaf_paths, (str, bytes))
             and isinstance(runtime_leaf_paths, Sequence),
             "launcher runtime leaf paths are invalid")
    manifest_ref, manifest, interpreter, launcher, leaves, _ = (
        _physical_material(
            project_root=Path(project_root),
            manifest_path=_relative_path(runtime_closure_manifest_path),
            interpreter_path=_relative_path(python_executable_path),
            launcher_path=_relative_path(publication_launcher_path),
            leaf_paths=[_relative_path(item) for item in runtime_leaf_paths],
            expected_system=pinned_system, expected_abi_sha=abi_pin,
            expected_manifest_sha=manifest_pin, expected_set_sha=set_pin,
        )
    )
    authority: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "system": pinned_system,
        "runtime_closure_manifest": manifest_ref,
        "runtime_closure_manifest_content": manifest,
        "python_executable": interpreter,
        "publication_launcher": launcher,
        "runtime_leaves": leaves,
        "runtime_closure_set_sha256": set_pin,
        "publication_launcher_invocation_v3_sha256": abi_pin,
    }
    authority["launcher_runtime_authority_sha256"] = _canonical_sha(authority)
    normalized = validate_backend_publication_launcher_runtime_authority(
        authority, expected_authority_sha256=authority_pin,
        expected_system=pinned_system,
        expected_publication_launcher_invocation_v3_sha256=abi_pin,
        expected_closure_manifest_sha256=manifest_pin,
        expected_runtime_closure_set_sha256=set_pin,
    )
    assessment = assess_backend_publication_launcher_runtime_authority(
        normalized, project_root=Path(project_root),
        expected_authority_sha256=authority_pin,
        expected_system=pinned_system,
        expected_publication_launcher_invocation_v3_sha256=abi_pin,
        expected_closure_manifest_sha256=manifest_pin,
        expected_runtime_closure_set_sha256=set_pin,
    )
    _require(assessment["status"] == "physically_valid",
             "launcher runtime authority physical assessment blocked")
    return normalized


__all__ = [
    "ARTIFACT_KIND", "ASSESSMENT_KIND", "CLOSURE_MANIFEST_KIND",
    "CLOSURE_SET_KIND", "LAUNCHER_INVOCATION_V3_KIND",
    "LAUNCHER_INVOCATION_V3_SCHEMA_VERSION", "SCHEMA_VERSION", "SYSTEMS",
    "BackendPublicationLauncherRuntimeAuthorityError",
    "assess_backend_publication_launcher_runtime_authority",
    "build_backend_publication_launcher_runtime_authority",
    "validate_backend_publication_launcher_runtime_authority",
]
