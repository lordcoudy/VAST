#!/usr/bin/env python3
"""Pinned candidate-byte authority for the native replay runner v3."""
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

import backend_runtime_replay_runner_invocation_protocol_v4 as protocol_v4
import backend_runtime_validator_authority_v4 as q4_validator

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


SCHEMA_VERSION = 3
ARTIFACT_KIND = "vast_backend_runtime_replay_runner_authority_v3"
ASSESSMENT_KIND = "vast_backend_runtime_replay_runner_authority_v3_assessment"
CLOSURE_SET_KIND = "vast_backend_runtime_replay_runner_closure_set_v3"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
FALSE_CLAIMS = (
    "runtime_closure_bundle_completeness_validated",
    "runtime_closure_bundle_immutability_validated",
    "native_image_selection_by_broker_validated",
    "native_broker_authority_bound",
    "handle_abi_external_pin_bound",
    "wfp_policy_bound",
    "filesystem_minifilter_policy_bound",
    "concrete_invocation_bound",
    "session_lease_bound",
    "atomic_runtime_closure_snapshot_validated",
    "inherited_handle_allowlist_validated",
    "standard_handle_mapping_validated",
    "handle_sealing_validated",
    "child_path_reopen_prevented",
    "native_broker_implemented",
    "broker_state_machine_enforced",
    "challenge_delivery_validated",
    "challenge_freshness_validated",
    "stdout_integrity_validated",
    "lease_enforcement_validated",
    "sandbox_enforcement_validated",
    "process_executed",
    "validation_records_authenticated",
    "execution_authorized",
    "expected_record_parent_isolation_validated",
    "native_image_handle_binding_validated",
    "filesystem_write_policy_enforced",
    "network_policy_enforced",
)

_CLOSURE_DOMAIN = b"VAST:backend-runtime-replay-runner-closure-set:v3\0"
_AUTHORITY_DOMAIN = b"VAST:backend-runtime-replay-runner-authority:v3\0"
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_FILE_REF_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind", "descriptor",
    "content_identity_sha256",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "status", "runner_id",
    "supported_host_os", "supported_host_architecture",
    "native_runner_image", "runner_entrypoint", "runtime_closure_bundle",
    "runtime_closure_set_sha256", "q4_validator_authority_ref",
    "replay_invocation_protocol_v4_ref",
    "replay_invocation_protocol_v4_content",
    "supported_concrete_invocation_schema_version",
    "supported_concrete_invocation_kind", "supported_request_schema_version",
    "supported_request_kind", "supported_record_schema_version",
    "supported_record_kind", *FALSE_CLAIMS,
    "replay_runner_authority_sha256",
})


class ReplayRunnerAuthorityV3Error(ValueError):
    """The replay runner v3 candidate or one of its pins is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayRunnerAuthorityV3Error(message)


def _strict_json(
    value: Any, *, active: set[int] | None = None, depth: int = 0,
) -> None:
    _require(depth <= 48, "replay runner v3 JSON nesting is excessive")
    value_type = type(value)
    if value_type not in (dict, list):
        _require(
            value_type in (str, int, bool),
            "replay runner v3 contains a non-contract JSON type",
        )
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities,
             "replay runner v3 contains a JSON cycle")
    identities.add(identity)
    try:
        items = value.items() if value_type is dict else enumerate(value)
        for key, item in items:
            if value_type is dict:
                _require(type(key) is str,
                         "replay runner v3 has a non-string JSON key")
            _strict_json(item, active=identities, depth=depth + 1)
    finally:
        identities.remove(identity)


def _canonical_bytes(value: object) -> bytes:
    _strict_json(value)
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ReplayRunnerAuthorityV3Error(
            "replay runner v3 is not canonical JSON"
        ) from error


def _domain_sha(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a lowercase SHA-256 identity")
    return value


def _pins(
    *, expected_authority_sha256: Any,
    expected_runtime_closure_set_sha256: Any,
    expected_q4_validator_authority_sha256: Any,
    expected_replay_invocation_protocol_v4_sha256: Any,
) -> tuple[str, str, str, str]:
    values = (
        _sha(expected_authority_sha256, "expected replay runner v3 authority"),
        _sha(expected_runtime_closure_set_sha256,
             "expected replay runner v3 closure set"),
        _sha(expected_q4_validator_authority_sha256,
             "expected Q4 validator authority"),
        _sha(expected_replay_invocation_protocol_v4_sha256,
             "expected replay protocol v4"),
    )
    _require(len(set(values)) == len(values),
             "replay runner v3 semantic pin domains alias")
    return values


def _relative_path(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is invalid")
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


def _file_ref(value: Any, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _FILE_REF_FIELDS,
             f"{label} file reference fields drifted")
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} content")
    _require(identity == descriptor["sha256"],
             f"{label} content identity drifted")
    return {"descriptor": descriptor, "content_identity_sha256": identity}


def _typed_ref(
    value: Any, label: str, *, schema_version: int, artifact_kind: str,
    expected_identity: str,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _TYPED_REF_FIELDS,
             f"{label} typed reference fields drifted")
    _require(type(value.get("artifact_schema_version")) is int
             and value.get("artifact_schema_version") == schema_version,
             f"{label} schema version drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == artifact_kind,
             f"{label} artifact kind drifted")
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} content")
    _require(identity == expected_identity, f"{label} semantic pin drifted")
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": descriptor,
        "content_identity_sha256": identity,
    }


def _closure_set(
    image: Mapping[str, Any], entrypoint: Mapping[str, Any],
    bundle: Mapping[str, Any], q4_ref: Mapping[str, Any],
    protocol_ref: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": CLOSURE_SET_KIND,
        "native_runner_image": copy.deepcopy(dict(image)),
        "runner_entrypoint": copy.deepcopy(dict(entrypoint)),
        "runtime_closure_bundle": copy.deepcopy(dict(bundle)),
        "q4_validator_authority_ref": copy.deepcopy(dict(q4_ref)),
        "replay_invocation_protocol_v4_ref": copy.deepcopy(dict(protocol_ref)),
    }


def _unique_references(references: Sequence[Mapping[str, Any]]) -> None:
    paths: set[str] = set()
    files: set[str] = set()
    contents: set[str] = set()
    encoded: set[bytes] = set()
    for reference in references:
        descriptor = reference["descriptor"]
        path = descriptor["path"].casefold()
        file_identity = descriptor["sha256"]
        content_identity = reference["content_identity_sha256"]
        serialized = _canonical_bytes(reference)
        _require(path not in paths,
                 "replay runner v3 artifact paths alias")
        _require(file_identity not in files,
                 "replay runner v3 file identities alias")
        _require(content_identity not in contents,
                 "replay runner v3 content identities alias")
        _require(serialized not in encoded,
                 "replay runner v3 references alias")
        paths.add(path)
        files.add(file_identity)
        contents.add(content_identity)
        encoded.add(serialized)


def _protocol_document_file_ref(
    reference: Mapping[str, Any], content: Mapping[str, Any],
) -> None:
    persisted = _canonical_bytes(content) + b"\n"
    descriptor = reference["descriptor"]
    _require(descriptor["size_bytes"] == len(persisted)
             and descriptor["sha256"] == hashlib.sha256(persisted).hexdigest(),
             "replay protocol v4 persisted descriptor drifted from content")


def validate_backend_runtime_replay_runner_authority_v3(
    value: Any, *, expected_authority_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
) -> dict[str, Any]:
    """Purely validate candidate bytes against all external trust pins."""
    authority_pin, set_pin, q4_pin, protocol_pin = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_runtime_closure_set_sha256=(
            expected_runtime_closure_set_sha256
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_replay_invocation_protocol_v4_sha256=(
            expected_replay_invocation_protocol_v4_sha256
        ),
    )
    _strict_json(value)
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "replay runner v3 authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "replay runner v3 authority header drifted")
    _require(type(value.get("status")) is str
             and value.get("status") == "listed_candidate_bytes_only",
             "replay runner v3 status overstates candidate scope")
    runner_id = value.get("runner_id")
    _require(type(runner_id) is str and _ID_RE.fullmatch(runner_id) is not None,
             "replay runner v3 runner_id is invalid")
    _require(type(value.get("supported_host_os")) is list
             and value.get("supported_host_os") == ["nt"]
             and type(value.get("supported_host_architecture")) is list
             and value.get("supported_host_architecture") == ["amd64"],
             "replay runner v3 host support drifted")
    image = _file_ref(value.get("native_runner_image"), "native runner image")
    entrypoint = _file_ref(value.get("runner_entrypoint"), "runner entrypoint")
    bundle = _file_ref(value.get("runtime_closure_bundle"),
                       "opaque runtime closure bundle")
    q4_ref = _typed_ref(
        value.get("q4_validator_authority_ref"), "Q4 validator authority",
        schema_version=q4_validator.SCHEMA_VERSION,
        artifact_kind=q4_validator.ARTIFACT_KIND,
        expected_identity=q4_pin,
    )
    protocol_ref = _typed_ref(
        value.get("replay_invocation_protocol_v4_ref"), "replay protocol v4",
        schema_version=protocol_v4.SCHEMA_VERSION,
        artifact_kind=protocol_v4.ARTIFACT_KIND,
        expected_identity=protocol_pin,
    )
    try:
        protocol_content = (
            protocol_v4.validate_replay_runner_invocation_protocol_v4_contract(
                value.get("replay_invocation_protocol_v4_content"),
                expected_protocol_sha256=protocol_pin,
            )
        )
    except protocol_v4.ReplayRunnerInvocationProtocolV4Error as error:
        raise ReplayRunnerAuthorityV3Error(
            f"replay runner v3 protocol dependency invalid: {error}"
        ) from error
    _protocol_document_file_ref(protocol_ref, protocol_content)
    closure_sha = _sha(value.get("runtime_closure_set_sha256"),
                       "replay runner v3 closure set")
    computed_closure_sha = _domain_sha(
        _CLOSURE_DOMAIN,
        _closure_set(image, entrypoint, bundle, q4_ref, protocol_ref),
    )
    _require(closure_sha == set_pin == computed_closure_sha,
             "replay runner v3 role-bound closure set drifted")
    exact = {
        "supported_concrete_invocation_schema_version":
            protocol_v4.CONCRETE_INVOCATION_SCHEMA_VERSION,
        "supported_concrete_invocation_kind":
            protocol_v4.CONCRETE_INVOCATION_KIND,
        "supported_request_schema_version": protocol_v4.REQUEST_SCHEMA_VERSION,
        "supported_request_kind": protocol_v4.REQUEST_KIND,
        "supported_record_schema_version": protocol_v4.RECORD_SCHEMA_VERSION,
        "supported_record_kind": protocol_v4.RECORD_KIND,
    }
    for field, expected in exact.items():
        _require(type(value.get(field)) is type(expected)
                 and value.get(field) == expected,
                 f"replay runner v3 {field} drifted")
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "listed_candidate_bytes_only",
        "runner_id": runner_id,
        "supported_host_os": ["nt"],
        "supported_host_architecture": ["amd64"],
        "native_runner_image": image,
        "runner_entrypoint": entrypoint,
        "runtime_closure_bundle": bundle,
        "runtime_closure_set_sha256": closure_sha,
        "q4_validator_authority_ref": q4_ref,
        "replay_invocation_protocol_v4_ref": protocol_ref,
        "replay_invocation_protocol_v4_content": protocol_content,
        **exact,
    }
    for field in FALSE_CLAIMS:
        _require(value.get(field) is False,
                 f"replay runner v3 {field} claim drifted")
        normalized[field] = False
    observed = _sha(value.get("replay_runner_authority_sha256"),
                    "replay runner v3 authority")
    _require(observed == authority_pin
             == _domain_sha(_AUTHORITY_DOMAIN, normalized),
             "replay runner v3 authority identity drifted")
    normalized["replay_runner_authority_sha256"] = observed
    _unique_references([image, entrypoint, bundle, q4_ref, protocol_ref])
    return copy.deepcopy(normalized)


# Secure physical readers and candidate assessment follow.


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise ReplayRunnerAuthorityV3Error(
            f"project root cannot be inspected: {error}"
        ) from error
    _require(resolved == supplied and stat.S_ISDIR(info.st_mode)
             and not bool(getattr(info, "st_file_attributes", 0)) & 0x400,
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
        raise OSError("replay runner v3 artifact handle is not a disk file")
    identity = _FileIdInfo()
    attributes = _FileAttributeTagInfo()
    standard = _FileStandardInfo()
    for info_class, item in (
        (_FILE_ID_INFO, identity),
        (_FILE_ATTRIBUTE_TAG_INFO, attributes),
        (_FILE_STANDARD_INFO, standard),
    ):
        if not _GET_FILE_INFORMATION(
            native, info_class, ctypes.byref(item), ctypes.sizeof(item),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    return {
        "volume": int(identity.VolumeSerialNumber),
        "id": bytes(identity.FileId.Identifier),
        "attributes": int(attributes.FileAttributes),
        "reparse_tag": int(attributes.ReparseTag),
        "size": int(standard.EndOfFile),
        "nlink": int(standard.NumberOfLinks),
        "delete_pending": bool(standard.DeletePending),
        "directory": bool(standard.Directory),
    }


def _win_fingerprint(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value[key] for key in (
        "volume", "id", "attributes", "reparse_tag", "size", "nlink",
        "delete_pending", "directory",
    ))


def _win_validate(
    value: Mapping[str, Any], *, directory: bool, volume: int,
) -> None:
    _require(bool(value["directory"]) == directory
             and not bool(value["delete_pending"]),
             "replay runner v3 artifact handle kind drifted")
    _require(not int(value["attributes"]) & _ATTR_REPARSE,
             "replay runner v3 artifact path contains a reparse point")
    _require(int(value["volume"]) == volume,
             "replay runner v3 artifact volume drifted")
    if not directory:
        _require(int(value["nlink"]) == 1,
                 "replay runner v3 artifact has multiple hard links")


def _read_windows(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
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
        _require(
            (volume, int.from_bytes(root_info["id"], "little"))
            == root_identity,
            "project root changed before replay runner v3 read",
        )
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
                     "replay runner v3 artifact path aliases a parent")
            seen.add(identity)
            held.append((cursor, True, _win_fingerprint(info)))
        path = cursor / relative.parts[-1]
        final_handle = _win_open(path, directory=False)
        info = _win_info(final_handle)
        _win_validate(info, directory=False, volume=volume)
        identity = (volume, bytes(info["id"]))
        _require(identity not in seen,
                 "replay runner v3 artifact aliases a parent")
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
                     "replay runner v3 artifact exceeds size limit")
            chunks.append(chunk)
        current = _win_info(int(msvcrt.get_osfhandle(descriptor_fd)))
        _require(_win_fingerprint(current) == fingerprint,
                 "replay runner v3 artifact changed while reading")
        for expected_path, is_directory, expected in held + [
            (path, False, fingerprint)
        ]:
            reopened: int | None = None
            reopen_primary = False
            try:
                reopened = _win_open(expected_path, directory=is_directory)
                observed = _win_info(reopened)
                _win_validate(
                    observed, directory=is_directory, volume=volume,
                )
                _require(_win_fingerprint(observed) == expected,
                         "replay runner v3 artifact path changed while reading")
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
    except ReplayRunnerAuthorityV3Error:
        raise
    except (OSError, ValueError) as error:
        raise ReplayRunnerAuthorityV3Error(
            f"replay runner v3 physical read failed: {error}"
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
            raise ReplayRunnerAuthorityV3Error(
                "replay runner v3 artifact handle cleanup failed"
            ) from close_error


def _read_posix(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    _require(os.open in os.supports_dir_fd
             and all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW")),
             "secure POSIX traversal is unavailable")
    held: list[int] = []
    verification: list[int] = []
    descriptor_fd: int | None = None
    try:
        directory_flags = (
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | int(getattr(os, "O_CLOEXEC", 0))
        )
        root_fd = os.open(root, directory_flags)
        held.append(root_fd)
        root_info = os.fstat(root_fd)
        _require(stat.S_ISDIR(root_info.st_mode)
                 and (int(root_info.st_dev), int(root_info.st_ino))
                 == root_identity,
                 "project root changed before replay runner v3 read")
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
                     "replay runner v3 artifact parent drifted")
            _require(identity not in seen,
                     "replay runner v3 artifact path aliases a parent")
            seen.add(identity)
            components.append((part, identity))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1,
                 "replay runner v3 artifact is not a unique regular file")
        _require(identity[0] == root_identity[0] and identity not in seen,
                 "replay runner v3 artifact identity/volume drifted")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_ARTIFACT_BYTES,
                     "replay runner v3 artifact exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor_fd)
        _require(opened == after,
                 "replay runner v3 artifact changed while reading")
        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require((int(verify_root.st_dev), int(verify_root.st_ino))
                 == root_identity,
                 "project root changed while replay runner v3 read")
        for part, expected in components:
            child_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require((int(child_info.st_dev), int(child_info.st_ino)) == expected,
                     "replay runner v3 path component changed while reading")
            verify_parent = child_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification.append(verify_fd)
        _require(os.fstat(verify_fd) == after,
                 "replay runner v3 artifact path changed while reading")
        payload = b"".join(chunks)
        return ({
            "path": relative.as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }, identity, payload)
    except ReplayRunnerAuthorityV3Error:
        raise
    except OSError as error:
        raise ReplayRunnerAuthorityV3Error(
            f"replay runner v3 physical read failed: {error}"
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
            raise ReplayRunnerAuthorityV3Error(
                "replay runner v3 descriptor cleanup failed"
            ) from close_error


def _physical_file(
    root: Path, root_identity: tuple[int, int], relative: str,
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    safe = PurePosixPath(_relative_path(relative, "replay runner v3 artifact"))
    return (_read_windows(root, safe, root_identity) if os.name == "nt"
            else _read_posix(root, safe, root_identity))


def _json_document(payload: bytes, label: str) -> dict[str, Any]:
    try:
        _require(payload.endswith(b"\n")
                 and payload[:-1] == payload.rstrip(b"\n"),
                 f"{label} must have exactly one trailing newline")
        value = json.loads(payload[:-1].decode("utf-8"))
        _require(type(value) is dict
                 and _canonical_bytes(value) == payload[:-1],
                 f"{label} is not canonical JSON")
        return value
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReplayRunnerAuthorityV3Error(f"{label} is invalid JSON") from error


def _physical_material(
    *, project_root: Path, native_runner_image_path: str,
    runner_entrypoint_path: str, runtime_closure_bundle_path: str,
    q4_validator_authority_path: str,
    replay_invocation_protocol_v4_path: str,
    q4_pin: str, protocol_pin: str,
) -> dict[str, Any]:
    root, root_identity = _root(project_root)
    paths = [
        native_runner_image_path, runner_entrypoint_path,
        runtime_closure_bundle_path, q4_validator_authority_path,
        replay_invocation_protocol_v4_path,
    ]
    safe = [_relative_path(item, "replay runner v3 artifact") for item in paths]
    _require(len({item.casefold() for item in safe}) == len(safe),
             "replay runner v3 artifact paths alias")
    physical_ids: set[tuple[Any, ...]] = set()
    observed: dict[str, tuple[dict[str, Any], bytes]] = {}
    total = 0
    for relative in safe:
        descriptor, identity, payload = _physical_file(
            root, root_identity, relative,
        )
        _require(identity not in physical_ids,
                 "replay runner v3 artifacts alias physically")
        physical_ids.add(identity)
        total += descriptor["size_bytes"]
        _require(total <= MAX_TOTAL_BYTES,
                 "replay runner v3 listed bytes exceed total size limit")
        observed[relative] = (descriptor, payload)
    q4_value = _json_document(
        observed[q4_validator_authority_path][1], "Q4 validator authority",
    )
    protocol_value = _json_document(
        observed[replay_invocation_protocol_v4_path][1],
        "replay invocation protocol v4",
    )
    try:
        q4_validator.validate_backend_runtime_validator_authority_v4(
            q4_value, expected_authority_sha256=q4_pin,
        )
        protocol_v4.validate_replay_runner_invocation_protocol_v4_contract(
            protocol_value, expected_protocol_sha256=protocol_pin,
        )
    except (
        q4_validator.BackendRuntimeValidatorAuthorityV4Error,
        protocol_v4.ReplayRunnerInvocationProtocolV4Error,
    ) as error:
        raise ReplayRunnerAuthorityV3Error(
            f"replay runner v3 dependency invalid: {error}"
        ) from error
    q4_implementation_descriptor = _descriptor(
        q4_value["implementation"]["descriptor"],
        "Q4 validator implementation",
    )
    q4_implementation_path = q4_implementation_descriptor["path"]
    _require(q4_implementation_path.casefold()
             not in {item.casefold() for item in safe},
             "Q4 validator implementation aliases a listed candidate path")
    implementation_descriptor, implementation_identity, _ = _physical_file(
        root, root_identity, q4_implementation_path,
    )
    _require(implementation_identity not in physical_ids,
             "Q4 validator implementation aliases a candidate role physically")
    _require(implementation_descriptor == q4_implementation_descriptor,
             "Q4 validator implementation descriptor drifted physically")
    physical_ids.add(implementation_identity)
    total += implementation_descriptor["size_bytes"]
    _require(total <= MAX_TOTAL_BYTES,
             "replay runner v3 listed bytes exceed total size limit")
    file_ref = lambda relative: {
        "descriptor": observed[relative][0],
        "content_identity_sha256": observed[relative][0]["sha256"],
    }
    typed_ref = lambda relative, schema, kind, identity: {
        "artifact_schema_version": schema,
        "artifact_kind": kind,
        "descriptor": observed[relative][0],
        "content_identity_sha256": identity,
    }
    return {
        "root": root,
        "native_runner_image": file_ref(native_runner_image_path),
        "runner_entrypoint": file_ref(runner_entrypoint_path),
        "runtime_closure_bundle": file_ref(runtime_closure_bundle_path),
        "q4_validator_authority_ref": typed_ref(
            q4_validator_authority_path, q4_validator.SCHEMA_VERSION,
            q4_validator.ARTIFACT_KIND, q4_pin,
        ),
        "replay_invocation_protocol_v4_ref": typed_ref(
            replay_invocation_protocol_v4_path, protocol_v4.SCHEMA_VERSION,
            protocol_v4.ARTIFACT_KIND, protocol_pin,
        ),
        "q4_value": q4_value,
        "q4_implementation_descriptor": implementation_descriptor,
        "protocol_value": protocol_value,
        "checked_artifact_count": len(safe) + 1,
    }


def assess_backend_runtime_replay_runner_authority_v3(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
) -> dict[str, Any]:
    """Observe only the six listed candidate roles through handles."""
    authority_sha = (value.get("replay_runner_authority_sha256")
                     if type(value) is dict else None)
    runner_id = value.get("runner_id") if type(value) is dict else None
    authority_valid = closure_valid = False
    image_valid = entrypoint_valid = bundle_valid = False
    q4_implementation_valid = q4_valid = protocol_valid = distinct = False
    checked = 0
    blockers: list[str] = []
    try:
        authority = validate_backend_runtime_replay_runner_authority_v3(
            value,
            expected_authority_sha256=expected_authority_sha256,
            expected_runtime_closure_set_sha256=(
                expected_runtime_closure_set_sha256
            ),
            expected_q4_validator_authority_sha256=(
                expected_q4_validator_authority_sha256
            ),
            expected_replay_invocation_protocol_v4_sha256=(
                expected_replay_invocation_protocol_v4_sha256
            ),
        )
        authority_valid = True
        closure_valid = True
        physical = _physical_material(
            project_root=project_root,
            native_runner_image_path=authority[
                "native_runner_image"
            ]["descriptor"]["path"],
            runner_entrypoint_path=authority[
                "runner_entrypoint"
            ]["descriptor"]["path"],
            runtime_closure_bundle_path=authority[
                "runtime_closure_bundle"
            ]["descriptor"]["path"],
            q4_validator_authority_path=authority[
                "q4_validator_authority_ref"
            ]["descriptor"]["path"],
            replay_invocation_protocol_v4_path=authority[
                "replay_invocation_protocol_v4_ref"
            ]["descriptor"]["path"],
            q4_pin=expected_q4_validator_authority_sha256,
            protocol_pin=expected_replay_invocation_protocol_v4_sha256,
        )
        _require(
            physical["native_runner_image"] == authority["native_runner_image"],
            "native runner image descriptor drifted physically",
        )
        image_valid = True
        _require(
            physical["runner_entrypoint"] == authority["runner_entrypoint"],
            "runner entrypoint descriptor drifted physically",
        )
        entrypoint_valid = True
        _require(
            physical["runtime_closure_bundle"]
            == authority["runtime_closure_bundle"],
            "opaque runtime closure bundle descriptor drifted physically",
        )
        bundle_valid = True
        _require(
            physical["q4_validator_authority_ref"]
            == authority["q4_validator_authority_ref"],
            "Q4 validator authority reference drifted physically",
        )
        _require(
            physical["q4_implementation_descriptor"]
            == physical["q4_value"]["implementation"]["descriptor"],
            "Q4 validator implementation descriptor binding drifted",
        )
        q4_implementation_valid = True
        q4_assessment = (
            q4_validator.assess_backend_runtime_validator_authority_v4(
                physical["q4_value"], project_root=physical["root"],
                expected_authority_sha256=(
                    expected_q4_validator_authority_sha256
                ),
            )
        )
        _require(q4_assessment.get("status") == "physically_valid",
                 "Q4 validator authority physical assessment blocked")
        q4_valid = True
        _require(
            physical["replay_invocation_protocol_v4_ref"]
            == authority["replay_invocation_protocol_v4_ref"],
            "replay protocol v4 reference drifted physically",
        )
        _require(
            physical["protocol_value"]
            == authority["replay_invocation_protocol_v4_content"],
            "replay protocol v4 content drifted physically",
        )
        protocol_valid = True
        distinct = True
        checked = physical["checked_artifact_count"]
    except (
        ReplayRunnerAuthorityV3Error,
        q4_validator.BackendRuntimeValidatorAuthorityV4Error,
        protocol_v4.ReplayRunnerInvocationProtocolV4Error,
        OSError, TypeError, ValueError,
    ) as error:
        blockers.append(str(error))
        checked = 0
    blockers = sorted(dict.fromkeys(item for item in blockers if item))
    success = (
        authority_valid and closure_valid and image_valid and entrypoint_valid
        and bundle_valid and q4_implementation_valid and q4_valid
        and protocol_valid and distinct and checked == 6 and not blockers
    )
    if not success:
        image_valid = entrypoint_valid = bundle_valid = False
        q4_implementation_valid = q4_valid = protocol_valid = distinct = False
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ASSESSMENT_KIND,
        "status": (
            "listed_candidate_bytes_physically_observed"
            if success else "blocked"
        ),
        "replay_runner_authority_sha256": authority_sha,
        "runner_id": runner_id,
        "checked_artifact_count": checked if success else 0,
        "blockers": blockers,
        "authority_pin_validated": authority_valid,
        "runtime_closure_set_pin_validated": closure_valid,
        "native_runner_image_handle_bound": image_valid,
        "runner_entrypoint_handle_bound": entrypoint_valid,
        "runtime_closure_bundle_handle_bound": bundle_valid,
        "q4_validator_implementation_handle_bound": q4_implementation_valid,
        "q4_validator_authority_physically_validated": q4_valid,
        "replay_invocation_protocol_v4_physically_validated": protocol_valid,
        "listed_candidate_roles_physically_distinct": distinct,
        "physical_validation_scope":
            "six_role_sequential_handle_bound_candidate_bytes_and_independent_q4_validation",
        "transitive_artifact_physical_identities_distinct": False,
    }
    result.update({field: False for field in FALSE_CLAIMS})
    return result


def build_backend_runtime_replay_runner_authority_v3(
    *, project_root: Path, runner_id: str,
    native_runner_image_path: str, runner_entrypoint_path: str,
    runtime_closure_bundle_path: str, q4_validator_authority_path: str,
    replay_invocation_protocol_v4_path: str,
    expected_authority_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
) -> dict[str, Any]:
    """Build a pinned listed-byte candidate without creating any artifact."""
    authority_pin, set_pin, q4_pin, protocol_pin = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_runtime_closure_set_sha256=(
            expected_runtime_closure_set_sha256
        ),
        expected_q4_validator_authority_sha256=(
            expected_q4_validator_authority_sha256
        ),
        expected_replay_invocation_protocol_v4_sha256=(
            expected_replay_invocation_protocol_v4_sha256
        ),
    )
    physical = _physical_material(
        project_root=project_root,
        native_runner_image_path=native_runner_image_path,
        runner_entrypoint_path=runner_entrypoint_path,
        runtime_closure_bundle_path=runtime_closure_bundle_path,
        q4_validator_authority_path=q4_validator_authority_path,
        replay_invocation_protocol_v4_path=(
            replay_invocation_protocol_v4_path
        ),
        q4_pin=q4_pin,
        protocol_pin=protocol_pin,
    )
    closure = _closure_set(
        physical["native_runner_image"], physical["runner_entrypoint"],
        physical["runtime_closure_bundle"],
        physical["q4_validator_authority_ref"],
        physical["replay_invocation_protocol_v4_ref"],
    )
    _require(_domain_sha(_CLOSURE_DOMAIN, closure) == set_pin,
             "replay runner v3 role-bound closure set pin drifted")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": "listed_candidate_bytes_only",
        "runner_id": runner_id,
        "supported_host_os": ["nt"],
        "supported_host_architecture": ["amd64"],
        "native_runner_image": physical["native_runner_image"],
        "runner_entrypoint": physical["runner_entrypoint"],
        "runtime_closure_bundle": physical["runtime_closure_bundle"],
        "runtime_closure_set_sha256": set_pin,
        "q4_validator_authority_ref": physical[
            "q4_validator_authority_ref"
        ],
        "replay_invocation_protocol_v4_ref": physical[
            "replay_invocation_protocol_v4_ref"
        ],
        "replay_invocation_protocol_v4_content": physical["protocol_value"],
        "supported_concrete_invocation_schema_version":
            protocol_v4.CONCRETE_INVOCATION_SCHEMA_VERSION,
        "supported_concrete_invocation_kind":
            protocol_v4.CONCRETE_INVOCATION_KIND,
        "supported_request_schema_version": protocol_v4.REQUEST_SCHEMA_VERSION,
        "supported_request_kind": protocol_v4.REQUEST_KIND,
        "supported_record_schema_version": protocol_v4.RECORD_SCHEMA_VERSION,
        "supported_record_kind": protocol_v4.RECORD_KIND,
        **{field: False for field in FALSE_CLAIMS},
    }
    value["replay_runner_authority_sha256"] = _domain_sha(
        _AUTHORITY_DOMAIN, value,
    )
    _require(value["replay_runner_authority_sha256"] == authority_pin,
             "replay runner v3 authority pin drifted")
    return validate_backend_runtime_replay_runner_authority_v3(
        value,
        expected_authority_sha256=authority_pin,
        expected_runtime_closure_set_sha256=set_pin,
        expected_q4_validator_authority_sha256=q4_pin,
        expected_replay_invocation_protocol_v4_sha256=protocol_pin,
    )


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "ASSESSMENT_KIND",
    "CLOSURE_SET_KIND", "FALSE_CLAIMS",
    "ReplayRunnerAuthorityV3Error",
    "validate_backend_runtime_replay_runner_authority_v3",
    "assess_backend_runtime_replay_runner_authority_v3",
    "build_backend_runtime_replay_runner_authority_v3",
]
