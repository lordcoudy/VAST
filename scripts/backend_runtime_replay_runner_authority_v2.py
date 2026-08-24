#!/usr/bin/env python3
"""Pinned, non-authorizing authority for listed replay-runner v2 artifacts."""
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

import backend_runtime_replay_runner_invocation_protocol_v3 as protocol
import backend_runtime_validation_runner_authority as base_runner
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


SCHEMA_VERSION = 2
ARTIFACT_KIND = "vast_backend_runtime_replay_runner_authority_v2"
ASSESSMENT_KIND = "vast_backend_runtime_replay_runner_authority_v2_assessment"
MANIFEST_KIND = "vast_backend_runtime_replay_runner_manifest_v2"
CLOSURE_SET_KIND = "vast_backend_runtime_replay_runner_closure_set_v2"
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
FALSE_CLAIMS = (
    "atomic_runtime_closure_snapshot_validated",
    "runtime_closure_completeness_validated",
    "lease_enforcement_validated",
    "sandbox_enforcement_validated",
    "challenge_freshness_validated",
    "protocol_schema_identity_crossbinding_complete",
    "process_executed",
    "validation_records_authenticated",
    "execution_authorized",
)

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
_COMMON_FIELDS = frozenset({
    "runner_id", "python_executable", "replay_runner", "runtime_leaves",
    "runtime_closure_set_sha256", "base_runner_authority_ref",
    "q4_validator_authority_ref", "replay_invocation_protocol_ref",
    "supported_concrete_invocation_schema_version",
    "supported_concrete_invocation_kind", "supported_request_schema_version",
    "supported_request_kind", "supported_record_schema_version",
    "supported_record_kind", "session_lease_challenge_abi",
    "session_lease_challenge_abi_sha256",
})
_MANIFEST_FIELDS = frozenset({
    "schema_version", "artifact_kind", *_COMMON_FIELDS, "manifest_sha256",
})
_TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "runtime_bundle_manifest",
    "runtime_bundle_manifest_content", *_COMMON_FIELDS,
    "replay_invocation_protocol_content", *FALSE_CLAIMS,
    "replay_runner_authority_sha256",
})


class ReplayRunnerAuthorityV2Error(ValueError):
    """The replay runner authority, closure, or trust pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayRunnerAuthorityV2Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None,
                 depth: int = 0) -> None:
    _require(depth <= 48, "replay runner authority JSON nesting is excessive")
    value_type = type(value)
    if value_type not in (dict, list):
        _require(value_type in (str, int, bool),
                 "replay runner authority contains a non-contract JSON type")
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities,
             "replay runner authority contains a JSON cycle")
    identities.add(identity)
    try:
        items = value.items() if value_type is dict else enumerate(value)
        for key, item in items:
            if value_type is dict:
                _require(type(key) is str,
                         "replay runner authority has a non-string JSON key")
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
        raise ReplayRunnerAuthorityV2Error(
            "replay runner authority is not canonical JSON"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a SHA-256 identity")
    return value


def _pins(
    *, expected_authority_sha256: Any, expected_manifest_sha256: Any,
    expected_runtime_closure_set_sha256: Any,
    expected_base_runner_authority_sha256: Any,
    expected_q4_validator_authority_sha256: Any,
    expected_replay_invocation_protocol_sha256: Any,
    expected_session_lease_challenge_abi_sha256: Any,
) -> tuple[str, str, str, str, str, str, str]:
    values = (
        _sha(expected_authority_sha256, "expected replay runner authority"),
        _sha(expected_manifest_sha256, "expected replay runner manifest"),
        _sha(expected_runtime_closure_set_sha256,
             "expected replay runtime closure set"),
        _sha(expected_base_runner_authority_sha256,
             "expected base runner authority"),
        _sha(expected_q4_validator_authority_sha256,
             "expected Q4 validator authority"),
        _sha(expected_replay_invocation_protocol_sha256,
             "expected replay invocation protocol"),
        _sha(expected_session_lease_challenge_abi_sha256,
             "expected session/lease/challenge ABI"),
    )
    _require(len(set(values)) == len(values),
             "replay runner semantic trust pin domains alias")
    return values


def _relative_path(value: Any, label: str = "replay runner artifact") -> str:
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


def _file_ref(value: Any, label: str,
              *, semantic_file_hash: bool = True) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _FILE_REF_FIELDS,
             f"{label} file reference fields drifted")
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} content")
    if semantic_file_hash:
        _require(identity == descriptor["sha256"],
                 f"{label} content identity drifted")
    return {"descriptor": descriptor, "content_identity_sha256": identity}


def _typed_ref(value: Any, label: str, *, schema_version: int,
               artifact_kind: str, expected_identity: str) -> dict[str, Any]:
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
        "artifact_kind": artifact_kind, "descriptor": descriptor,
        "content_identity_sha256": identity,
    }


def _runtime_leaves(value: Any) -> list[dict[str, Any]]:
    _require(type(value) is list and bool(value),
             "replay runtime leaf list is invalid")
    leaves = [_file_ref(item, "replay runtime leaf") for item in value]
    keys = [(item["descriptor"]["path"].casefold(),
             item["descriptor"]["path"]) for item in leaves]
    _require(keys == sorted(keys) and len(keys) == len(set(keys)),
             "replay runtime leaves are not sorted and unique")
    return leaves


def _closure_set(
    interpreter: Mapping[str, Any], runner: Mapping[str, Any],
    leaves: Sequence[Mapping[str, Any]], base_ref: Mapping[str, Any],
    q4_ref: Mapping[str, Any], protocol_ref: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "artifact_kind": CLOSURE_SET_KIND,
        "python_executable": copy.deepcopy(dict(interpreter)),
        "replay_runner": copy.deepcopy(dict(runner)),
        "runtime_leaves": copy.deepcopy(list(leaves)),
        "base_runner_authority_ref": copy.deepcopy(dict(base_ref)),
        "q4_validator_authority_ref": copy.deepcopy(dict(q4_ref)),
        "replay_invocation_protocol_ref": copy.deepcopy(dict(protocol_ref)),
    }


def _abi_identity(abi: Mapping[str, Any]) -> str:
    return _canonical_sha({
        "schema_version": protocol.SCHEMA_VERSION,
        "artifact_kind": protocol.SESSION_LEASE_CHALLENGE_ABI_KIND,
        "content": copy.deepcopy(dict(abi)),
    })


def _unique_references(references: Sequence[Mapping[str, Any]]) -> None:
    paths: set[str] = set()
    file_ids: set[str] = set()
    content_ids: set[str] = set()
    encoded: set[bytes] = set()
    for reference in references:
        descriptor = reference["descriptor"]
        path = descriptor["path"].casefold()
        file_id = descriptor["sha256"]
        content_id = reference["content_identity_sha256"]
        serialized = _canonical_bytes(reference)
        _require(path not in paths,
                 "replay runner authority artifact paths alias")
        _require(file_id not in file_ids,
                 "replay runner authority file identities alias")
        _require(content_id not in content_ids,
                 "replay runner authority content identities alias")
        _require(serialized not in encoded,
                 "replay runner authority references alias")
        paths.add(path)
        file_ids.add(file_id)
        content_ids.add(content_id)
        encoded.add(serialized)


def _common(
    value: Mapping[str, Any], *, set_pin: str, base_pin: str, q4_pin: str,
    protocol_pin: str, abi_pin: str, protocol_content: Mapping[str, Any],
) -> dict[str, Any]:
    _require(type(value.get("runner_id")) is str
             and _ID_RE.fullmatch(value["runner_id"]) is not None,
             "replay runner_id is invalid")
    interpreter = _file_ref(value.get("python_executable"),
                            "replay python executable")
    runner = _file_ref(value.get("replay_runner"), "replay runner")
    leaves = _runtime_leaves(value.get("runtime_leaves"))
    base_ref = _typed_ref(
        value.get("base_runner_authority_ref"), "base runner authority",
        schema_version=base_runner.SCHEMA_VERSION,
        artifact_kind=base_runner.ARTIFACT_KIND, expected_identity=base_pin,
    )
    q4_ref = _typed_ref(
        value.get("q4_validator_authority_ref"), "Q4 validator authority",
        schema_version=q4_validator.SCHEMA_VERSION,
        artifact_kind=q4_validator.ARTIFACT_KIND, expected_identity=q4_pin,
    )
    protocol_ref = _typed_ref(
        value.get("replay_invocation_protocol_ref"), "replay protocol",
        schema_version=protocol.SCHEMA_VERSION,
        artifact_kind=protocol.ARTIFACT_KIND,
        expected_identity=protocol_pin,
    )
    set_sha = _sha(value.get("runtime_closure_set_sha256"),
                   "replay runtime closure set")
    _require(set_sha == set_pin == _canonical_sha(_closure_set(
        interpreter, runner, leaves, base_ref, q4_ref, protocol_ref,
    )), "replay runtime closure set drifted")
    exact = {
        "supported_concrete_invocation_schema_version":
            protocol.CONCRETE_INVOCATION_SCHEMA_VERSION,
        "supported_concrete_invocation_kind":
            protocol.CONCRETE_INVOCATION_KIND,
        "supported_request_schema_version": protocol.REQUEST_SCHEMA_VERSION,
        "supported_request_kind": protocol.REQUEST_KIND,
        "supported_record_schema_version": protocol.RECORD_SCHEMA_VERSION,
        "supported_record_kind": protocol.RECORD_KIND,
    }
    for field, expected in exact.items():
        _require(type(value.get(field)) is type(expected)
                 and value.get(field) == expected,
                 f"replay runner {field} drifted")
    abi = value.get("session_lease_challenge_abi")
    _require(type(abi) is dict
             and abi == protocol_content["session_lease_challenge_abi"],
             "session/lease/challenge ABI drifted from protocol")
    abi_sha = _sha(value.get("session_lease_challenge_abi_sha256"),
                   "session/lease/challenge ABI")
    _require(abi_sha == abi_pin == _abi_identity(abi),
             "session/lease/challenge ABI identity drifted")
    return {
        "runner_id": value["runner_id"], "python_executable": interpreter,
        "replay_runner": runner, "runtime_leaves": leaves,
        "runtime_closure_set_sha256": set_sha,
        "base_runner_authority_ref": base_ref,
        "q4_validator_authority_ref": q4_ref,
        "replay_invocation_protocol_ref": protocol_ref, **exact,
        "session_lease_challenge_abi": copy.deepcopy(abi),
        "session_lease_challenge_abi_sha256": abi_sha,
    }


def _manifest(
    value: Any, *, manifest_pin: str, set_pin: str, base_pin: str,
    q4_pin: str, protocol_pin: str, abi_pin: str,
    protocol_content: Mapping[str, Any],
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _MANIFEST_FIELDS,
             "replay runner manifest fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == MANIFEST_KIND,
             "replay runner manifest header drifted")
    common = _common(
        value, set_pin=set_pin, base_pin=base_pin, q4_pin=q4_pin,
        protocol_pin=protocol_pin, abi_pin=abi_pin,
        protocol_content=protocol_content,
    )
    normalized = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": MANIFEST_KIND,
        **common,
    }
    manifest_sha = _sha(value.get("manifest_sha256"),
                        "replay runner manifest")
    _require(manifest_sha == manifest_pin == _canonical_sha(normalized),
             "replay runner manifest identity drifted")
    normalized["manifest_sha256"] = manifest_sha
    return normalized


def validate_backend_runtime_replay_runner_authority_v2(
    value: Any, *, expected_authority_sha256: str,
    expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_base_runner_authority_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_sha256: str,
    expected_session_lease_challenge_abi_sha256: str,
) -> dict[str, Any]:
    """Purely validate the closed authority against all external pins."""
    authority_pin, manifest_pin, set_pin, base_pin, q4_pin, protocol_pin, abi_pin = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_runtime_closure_set_sha256=expected_runtime_closure_set_sha256,
        expected_base_runner_authority_sha256=expected_base_runner_authority_sha256,
        expected_q4_validator_authority_sha256=expected_q4_validator_authority_sha256,
        expected_replay_invocation_protocol_sha256=(
            expected_replay_invocation_protocol_sha256
        ),
        expected_session_lease_challenge_abi_sha256=(
            expected_session_lease_challenge_abi_sha256
        ),
    )
    _strict_json(value)
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "replay runner authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "replay runner authority header drifted")
    protocol_content = protocol.validate_replay_runner_invocation_protocol_v3_contract(
        value.get("replay_invocation_protocol_content"),
        expected_protocol_sha256=protocol_pin,
    )
    manifest_ref = _file_ref(
        value.get("runtime_bundle_manifest"), "replay runner manifest",
        semantic_file_hash=False,
    )
    _require(manifest_ref["content_identity_sha256"] == manifest_pin,
             "replay runner manifest reference semantic identity drifted")
    manifest = _manifest(
        value.get("runtime_bundle_manifest_content"), manifest_pin=manifest_pin,
        set_pin=set_pin, base_pin=base_pin, q4_pin=q4_pin,
        protocol_pin=protocol_pin, abi_pin=abi_pin,
        protocol_content=protocol_content,
    )
    common = _common(
        value, set_pin=set_pin, base_pin=base_pin, q4_pin=q4_pin,
        protocol_pin=protocol_pin, abi_pin=abi_pin,
        protocol_content=protocol_content,
    )
    _require({field: manifest[field] for field in _COMMON_FIELDS} == common,
             "replay runner authority manifest binding drifted")
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "runtime_bundle_manifest": manifest_ref,
        "runtime_bundle_manifest_content": manifest, **common,
        "replay_invocation_protocol_content": protocol_content,
    }
    for field in FALSE_CLAIMS:
        _require(value.get(field) is False,
                 f"replay runner authority {field} claim drifted")
        normalized[field] = False
    observed = _sha(value.get("replay_runner_authority_sha256"),
                    "replay runner authority")
    _require(observed == authority_pin == _canonical_sha(normalized),
             "replay runner authority self-hash or external pin drifted")
    normalized["replay_runner_authority_sha256"] = observed
    _unique_references([
        manifest_ref, common["python_executable"], common["replay_runner"],
        *common["runtime_leaves"], common["base_runner_authority_ref"],
        common["q4_validator_authority_ref"],
        common["replay_invocation_protocol_ref"],
    ])
    return copy.deepcopy(normalized)


# Physical handle-bound reader and build/assessment follow below.


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise ReplayRunnerAuthorityV2Error(
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
        raise OSError("replay runner artifact handle is not a disk file")
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


def _win_validate(value: Mapping[str, Any], *, directory: bool,
                  volume: int) -> None:
    _require(bool(value["directory"]) == directory
             and not bool(value["delete_pending"]),
             "replay runner artifact handle kind drifted")
    _require(not int(value["attributes"]) & _ATTR_REPARSE,
             "replay runner artifact path contains a reparse point")
    _require(int(value["volume"]) == volume,
             "replay runner artifact volume drifted")
    if not directory:
        _require(int(value["nlink"]) == 1,
                 "replay runner artifact has multiple hard links")


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
                     "replay runner artifact path aliases a parent")
            seen.add(identity)
            held.append((cursor, True, _win_fingerprint(info)))
        path = cursor / relative.parts[-1]
        final_handle = _win_open(path, directory=False)
        info = _win_info(final_handle)
        _win_validate(info, directory=False, volume=volume)
        identity = (volume, bytes(info["id"]))
        _require(identity not in seen,
                 "replay runner artifact aliases a parent")
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
                     "replay runner artifact exceeds size limit")
            chunks.append(chunk)
        current = _win_info(int(msvcrt.get_osfhandle(descriptor_fd)))
        _require(_win_fingerprint(current) == fingerprint,
                 "replay runner artifact changed while reading")
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
                         "replay runner artifact path changed while reading")
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
                 "sha256": hashlib.sha256(payload).hexdigest()},
                identity, payload)
    except ReplayRunnerAuthorityV2Error:
        raise
    except (OSError, ValueError) as error:
        raise ReplayRunnerAuthorityV2Error(
            f"replay runner physical read failed: {error}"
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
            raise ReplayRunnerAuthorityV2Error(
                "replay runner artifact handle cleanup failed"
            ) from close_error


def _posix_stable_stat(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_size), int(value.st_mtime_ns), int(value.st_ctime_ns),
        int(value.st_dev), int(value.st_ino), int(value.st_mode),
        int(value.st_nlink),
    )


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
        directory_flags = (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                           | int(getattr(os, "O_CLOEXEC", 0)))
        root_fd = os.open(root, directory_flags)
        held.append(root_fd)
        root_info = os.fstat(root_fd)
        _require(stat.S_ISDIR(root_info.st_mode)
                 and (int(root_info.st_dev), int(root_info.st_ino))
                 == root_identity, "project root changed before reading")
        root_stable = _posix_stable_stat(root_info)
        seen = {root_identity}
        components: list[tuple[str, int, tuple[int, ...]]] = []
        parent_fd = root_fd
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            held.append(child_fd)
            child_info = os.fstat(child_fd)
            identity = (int(child_info.st_dev), int(child_info.st_ino))
            _require(stat.S_ISDIR(child_info.st_mode)
                     and identity[0] == root_identity[0],
                     "replay runner artifact parent drifted")
            _require(identity not in seen,
                     "replay runner artifact path aliases a parent")
            seen.add(identity)
            components.append((part, child_fd, _posix_stable_stat(child_info)))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1,
                 "replay runner artifact is not a unique regular file")
        _require(identity[0] == root_identity[0] and identity not in seen,
                 "replay runner artifact identity/volume drifted")
        opened_stable = _posix_stable_stat(opened)
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_ARTIFACT_BYTES,
                     "replay runner artifact exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor_fd)
        after_stable = _posix_stable_stat(after)
        _require(opened_stable == after_stable,
                 "replay runner artifact changed while reading")
        _require(_posix_stable_stat(os.fstat(root_fd)) == root_stable,
                 "project root changed while reading")
        for _part, held_fd, expected_stable in components:
            _require(_posix_stable_stat(os.fstat(held_fd)) == expected_stable,
                     "replay runner artifact held path component changed "
                     "while reading")
        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require(_posix_stable_stat(verify_root) == root_stable,
                 "project root changed while reading")
        for part, _held_fd, expected_stable in components:
            child_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require(_posix_stable_stat(child_info) == expected_stable,
                     "replay runner artifact path component changed")
            verify_parent = child_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification.append(verify_fd)
        reopened = os.fstat(verify_fd)
        _require(_posix_stable_stat(reopened) == after_stable,
                 "replay runner artifact path changed while reading")
        payload = b"".join(chunks)
        return ({"path": relative.as_posix(), "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()},
                identity, payload)
    except ReplayRunnerAuthorityV2Error:
        raise
    except OSError as error:
        raise ReplayRunnerAuthorityV2Error(
            f"replay runner physical read failed: {error}"
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
            raise ReplayRunnerAuthorityV2Error(
                "replay runner artifact descriptor cleanup failed"
            ) from close_error


def _physical_file(
    root: Path, root_identity: tuple[int, int], relative: str,
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    safe = PurePosixPath(_relative_path(relative))
    return (_read_windows(root, safe, root_identity) if os.name == "nt"
            else _read_posix(root, safe, root_identity))


def _json_document(payload: bytes, label: str) -> dict[str, Any]:
    try:
        _require(payload.endswith(b"\n")
                 and payload[:-1] == payload.rstrip(b"\n"),
                 f"{label} must have exactly one trailing newline")
        value = json.loads(payload[:-1].decode("utf-8"))
        _require(type(value) is dict and _canonical_bytes(value) == payload[:-1],
                 f"{label} is not canonical JSON")
        return value
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReplayRunnerAuthorityV2Error(f"{label} is invalid JSON") from error


def _physical_material(
    *, project_root: Path, manifest_path: str,
    python_executable_path: str, replay_runner_path: str,
    runtime_leaf_paths: Sequence[str], base_runner_authority_path: str,
    q4_validator_authority_path: str, replay_invocation_protocol_path: str,
    base_pin: str, q4_pin: str, protocol_pin: str,
) -> dict[str, Any]:
    root, root_identity = _root(project_root)
    paths = [
        manifest_path, python_executable_path, replay_runner_path,
        *runtime_leaf_paths, base_runner_authority_path,
        q4_validator_authority_path, replay_invocation_protocol_path,
    ]
    safe = [_relative_path(item) for item in paths]
    _require(len({item.casefold() for item in safe}) == len(safe),
             "replay runner authority artifact paths alias")
    physical_ids: set[tuple[Any, ...]] = set()
    observed: dict[str, tuple[dict[str, Any], bytes]] = {}
    total = 0
    for relative in safe:
        descriptor, identity, payload = _physical_file(
            root, root_identity, relative,
        )
        _require(identity not in physical_ids,
                 "replay runner authority artifacts alias physically")
        physical_ids.add(identity)
        total += descriptor["size_bytes"]
        _require(total <= MAX_TOTAL_BYTES,
                 "replay runner authority closure exceeds total size limit")
        observed[relative] = (descriptor, payload)
    manifest = _json_document(observed[manifest_path][1],
                              "replay runner manifest")
    base_value = _json_document(observed[base_runner_authority_path][1],
                                "base runner authority")
    q4_value = _json_document(observed[q4_validator_authority_path][1],
                              "Q4 validator authority")
    protocol_value = _json_document(observed[replay_invocation_protocol_path][1],
                                    "replay invocation protocol")
    base_runner.validate_backend_runtime_validation_runner_authority(
        base_value, expected_runner_authority_sha256=base_pin,
    )
    q4_validator.validate_backend_runtime_validator_authority_v4(
        q4_value, expected_authority_sha256=q4_pin,
    )
    schema_identity_bindings = (
        ("validation_protocol_identity_sha256",
         "validation_protocol_identity_sha256"),
        ("input_schema_identity_sha256",
         "validation_input_schema_identity_sha256"),
        ("output_schema_identity_sha256",
         "validation_output_schema_identity_sha256"),
    )
    for base_field, q4_field in schema_identity_bindings:
        _require(
            base_value[base_field] == q4_value[q4_field],
            f"base runner and Q4 validator {q4_field} binding drifted",
        )
    protocol.validate_replay_runner_invocation_protocol_v3_contract(
        protocol_value, expected_protocol_sha256=protocol_pin,
    )
    file_ref = lambda relative: {
        "descriptor": observed[relative][0],
        "content_identity_sha256": observed[relative][0]["sha256"],
    }
    typed_ref = lambda relative, schema, kind, identity: {
        "artifact_schema_version": schema, "artifact_kind": kind,
        "descriptor": observed[relative][0],
        "content_identity_sha256": identity,
    }
    leaves = sorted(
        (file_ref(relative) for relative in runtime_leaf_paths),
        key=lambda item: (item["descriptor"]["path"].casefold(),
                          item["descriptor"]["path"]),
    )
    return {
        "root": root, "manifest": manifest,
        "manifest_ref": {
            "descriptor": observed[manifest_path][0],
            "content_identity_sha256": manifest.get("manifest_sha256"),
        },
        "python_executable": file_ref(python_executable_path),
        "replay_runner": file_ref(replay_runner_path),
        "runtime_leaves": leaves,
        "base_runner_authority_ref": typed_ref(
            base_runner_authority_path, base_runner.SCHEMA_VERSION,
            base_runner.ARTIFACT_KIND, base_pin,
        ),
        "q4_validator_authority_ref": typed_ref(
            q4_validator_authority_path, q4_validator.SCHEMA_VERSION,
            q4_validator.ARTIFACT_KIND, q4_pin,
        ),
        "replay_invocation_protocol_ref": typed_ref(
            replay_invocation_protocol_path, protocol.SCHEMA_VERSION,
            protocol.ARTIFACT_KIND, protocol_pin,
        ),
        "base_value": base_value, "q4_value": q4_value,
        "protocol_value": protocol_value,
        "checked_artifact_count": len(safe),
    }


def assess_backend_runtime_replay_runner_authority_v2(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
    expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_base_runner_authority_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_sha256: str,
    expected_session_lease_challenge_abi_sha256: str,
) -> dict[str, Any]:
    authority_sha = (value.get("replay_runner_authority_sha256")
                     if type(value) is dict else None)
    runner_id = value.get("runner_id") if type(value) is dict else None
    checked = 0
    authority_valid = manifest_valid = base_valid = False
    q4_valid = protocol_valid = top_level_distinct = False
    blockers: list[str] = []
    try:
        authority = validate_backend_runtime_replay_runner_authority_v2(
            value, expected_authority_sha256=expected_authority_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_runtime_closure_set_sha256=(
                expected_runtime_closure_set_sha256
            ),
            expected_base_runner_authority_sha256=(
                expected_base_runner_authority_sha256
            ),
            expected_q4_validator_authority_sha256=(
                expected_q4_validator_authority_sha256
            ),
            expected_replay_invocation_protocol_sha256=(
                expected_replay_invocation_protocol_sha256
            ),
            expected_session_lease_challenge_abi_sha256=(
                expected_session_lease_challenge_abi_sha256
            ),
        )
        authority_valid = True
        physical = _physical_material(
            project_root=project_root,
            manifest_path=authority["runtime_bundle_manifest"]["descriptor"]["path"],
            python_executable_path=authority["python_executable"]["descriptor"]["path"],
            replay_runner_path=authority["replay_runner"]["descriptor"]["path"],
            runtime_leaf_paths=[item["descriptor"]["path"]
                                for item in authority["runtime_leaves"]],
            base_runner_authority_path=authority[
                "base_runner_authority_ref"
            ]["descriptor"]["path"],
            q4_validator_authority_path=authority[
                "q4_validator_authority_ref"
            ]["descriptor"]["path"],
            replay_invocation_protocol_path=authority[
                "replay_invocation_protocol_ref"
            ]["descriptor"]["path"],
            base_pin=expected_base_runner_authority_sha256,
            q4_pin=expected_q4_validator_authority_sha256,
            protocol_pin=expected_replay_invocation_protocol_sha256,
        )
        expected_refs = [
            authority["runtime_bundle_manifest"],
            authority["python_executable"], authority["replay_runner"],
            *authority["runtime_leaves"], authority["base_runner_authority_ref"],
            authority["q4_validator_authority_ref"],
            authority["replay_invocation_protocol_ref"],
        ]
        observed_refs = [
            physical["manifest_ref"], physical["python_executable"],
            physical["replay_runner"], *physical["runtime_leaves"],
            physical["base_runner_authority_ref"],
            physical["q4_validator_authority_ref"],
            physical["replay_invocation_protocol_ref"],
        ]
        _require(observed_refs == expected_refs,
                 "replay runner closure drifted physically")
        _require(physical["manifest"]
                 == authority["runtime_bundle_manifest_content"],
                 "replay runner manifest drifted physically")
        _require(physical["protocol_value"]
                 == authority["replay_invocation_protocol_content"],
                 "replay protocol content drifted physically")
        manifest_valid = True
        base_assessment = base_runner.assess_backend_runtime_validation_runner_authority(
            physical["base_value"], project_root=physical["root"],
            expected_runner_authority_sha256=(
                expected_base_runner_authority_sha256
            ),
        )
        _require(base_assessment.get("status") == "physically_valid",
                 "base runner authority physical assessment blocked")
        base_valid = True
        q4_assessment = q4_validator.assess_backend_runtime_validator_authority_v4(
            physical["q4_value"], project_root=physical["root"],
            expected_authority_sha256=expected_q4_validator_authority_sha256,
        )
        _require(q4_assessment.get("status") == "physically_valid",
                 "Q4 validator authority physical assessment blocked")
        q4_valid = True
        protocol_valid = True
        top_level_distinct = True
        checked = physical["checked_artifact_count"]
    except (
        ReplayRunnerAuthorityV2Error,
        base_runner.BackendRuntimeValidationRunnerAuthorityError,
        q4_validator.BackendRuntimeValidatorAuthorityV4Error,
        protocol.ReplayRunnerInvocationProtocolV3Error,
        OSError, TypeError, ValueError,
    ) as error:
        blockers.append(str(error))
        checked = 0
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if authority_valid and manifest_valid
        and base_valid and q4_valid and protocol_valid and top_level_distinct
        and not blockers else "blocked",
        "replay_runner_authority_sha256": authority_sha,
        "runner_id": runner_id, "checked_artifact_count": checked,
        "blockers": sorted(dict.fromkeys(item for item in blockers if item)),
        "authority_pin_validated": authority_valid,
        "manifest_physically_validated": manifest_valid,
        "base_runner_authority_physically_validated": base_valid,
        "q4_validator_authority_physically_validated": q4_valid,
        "replay_protocol_physically_validated": protocol_valid,
        "individual_artifact_reads_handle_bound": manifest_valid,
        "physical_validation_scope":
            "top_level_sequential_listed_closure_and_independent_nested_authority_assessments",
        "top_level_authority_reference_physical_identities_distinct":
            top_level_distinct,
        "transitive_runtime_artifact_physical_identities_distinct": False,
    }
    result.update({field: False for field in FALSE_CLAIMS})
    return result


def build_backend_runtime_replay_runner_authority_v2(
    *, project_root: Path, runner_id: str,
    runtime_bundle_manifest_path: str, runtime_leaf_paths: Sequence[str],
    python_executable_path: str, replay_runner_path: str,
    base_runner_authority_path: str, q4_validator_authority_path: str,
    replay_invocation_protocol_path: str,
    expected_authority_sha256: str, expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_base_runner_authority_sha256: str,
    expected_q4_validator_authority_sha256: str,
    expected_replay_invocation_protocol_sha256: str,
    expected_session_lease_challenge_abi_sha256: str,
) -> dict[str, Any]:
    pins = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_runtime_closure_set_sha256=expected_runtime_closure_set_sha256,
        expected_base_runner_authority_sha256=expected_base_runner_authority_sha256,
        expected_q4_validator_authority_sha256=expected_q4_validator_authority_sha256,
        expected_replay_invocation_protocol_sha256=(
            expected_replay_invocation_protocol_sha256
        ),
        expected_session_lease_challenge_abi_sha256=(
            expected_session_lease_challenge_abi_sha256
        ),
    )
    _require(type(runtime_leaf_paths) in {list, tuple} and bool(runtime_leaf_paths),
             "replay runtime leaf paths are invalid")
    try:
        physical = _physical_material(
            project_root=project_root,
            manifest_path=runtime_bundle_manifest_path,
            python_executable_path=python_executable_path,
            replay_runner_path=replay_runner_path,
            runtime_leaf_paths=list(runtime_leaf_paths),
            base_runner_authority_path=base_runner_authority_path,
            q4_validator_authority_path=q4_validator_authority_path,
            replay_invocation_protocol_path=replay_invocation_protocol_path,
            base_pin=pins[3], q4_pin=pins[4], protocol_pin=pins[5],
        )
    except (
        base_runner.BackendRuntimeValidationRunnerAuthorityError,
        q4_validator.BackendRuntimeValidatorAuthorityV4Error,
        protocol.ReplayRunnerInvocationProtocolV3Error,
    ) as error:
        raise ReplayRunnerAuthorityV2Error(
            f"replay runner dependency validation failed: {error}"
        ) from error
    common = {
        "runner_id": runner_id,
        "python_executable": physical["python_executable"],
        "replay_runner": physical["replay_runner"],
        "runtime_leaves": physical["runtime_leaves"],
        "runtime_closure_set_sha256": pins[2],
        "base_runner_authority_ref": physical["base_runner_authority_ref"],
        "q4_validator_authority_ref": physical["q4_validator_authority_ref"],
        "replay_invocation_protocol_ref": physical[
            "replay_invocation_protocol_ref"
        ],
        "supported_concrete_invocation_schema_version":
            protocol.CONCRETE_INVOCATION_SCHEMA_VERSION,
        "supported_concrete_invocation_kind": protocol.CONCRETE_INVOCATION_KIND,
        "supported_request_schema_version": protocol.REQUEST_SCHEMA_VERSION,
        "supported_request_kind": protocol.REQUEST_KIND,
        "supported_record_schema_version": protocol.RECORD_SCHEMA_VERSION,
        "supported_record_kind": protocol.RECORD_KIND,
        "session_lease_challenge_abi": copy.deepcopy(
            physical["protocol_value"]["session_lease_challenge_abi"]
        ),
        "session_lease_challenge_abi_sha256": pins[6],
    }
    _require(physical["manifest"] == {
        "schema_version": SCHEMA_VERSION, "artifact_kind": MANIFEST_KIND,
        **common, "manifest_sha256": pins[1],
    }, "physical replay runner manifest content drifted")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "runtime_bundle_manifest": physical["manifest_ref"],
        "runtime_bundle_manifest_content": physical["manifest"], **common,
        "replay_invocation_protocol_content": physical["protocol_value"],
        **{field: False for field in FALSE_CLAIMS},
    }
    value["replay_runner_authority_sha256"] = _canonical_sha(value)
    return validate_backend_runtime_replay_runner_authority_v2(
        value, expected_authority_sha256=expected_authority_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_runtime_closure_set_sha256=expected_runtime_closure_set_sha256,
        expected_base_runner_authority_sha256=expected_base_runner_authority_sha256,
        expected_q4_validator_authority_sha256=expected_q4_validator_authority_sha256,
        expected_replay_invocation_protocol_sha256=(
            expected_replay_invocation_protocol_sha256
        ),
        expected_session_lease_challenge_abi_sha256=(
            expected_session_lease_challenge_abi_sha256
        ),
    )


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "ASSESSMENT_KIND", "MANIFEST_KIND",
    "CLOSURE_SET_KIND", "FALSE_CLAIMS", "ReplayRunnerAuthorityV2Error",
    "validate_backend_runtime_replay_runner_authority_v2",
    "assess_backend_runtime_replay_runner_authority_v2",
    "build_backend_runtime_replay_runner_authority_v2",
]
