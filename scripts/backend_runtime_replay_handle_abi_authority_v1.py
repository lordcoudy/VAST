#!/usr/bin/env python3
"""Immutable, non-authorizing projection of replay protocol-v4 handle ABI."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

import backend_runtime_replay_runner_invocation_protocol_v4 as protocol_v4


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
    _CREATE_FILE.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _CREATE_FILE.restype = wintypes.HANDLE
    _GET_FILE_INFORMATION = _KERNEL32.GetFileInformationByHandleEx
    _GET_FILE_INFORMATION.argtypes = [wintypes.HANDLE, ctypes.c_int,
        wintypes.LPVOID, wintypes.DWORD]
    _GET_FILE_INFORMATION.restype = wintypes.BOOL
    _GET_FILE_TYPE = _KERNEL32.GetFileType
    _GET_FILE_TYPE.argtypes = [wintypes.HANDLE]
    _GET_FILE_TYPE.restype = wintypes.DWORD
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [wintypes.HANDLE]
    _CLOSE_HANDLE.restype = wintypes.BOOL


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_runtime_replay_handle_abi_authority_v1"
ASSESSMENT_KIND = "vast_backend_runtime_replay_handle_abi_authority_v1_assessment"
ABI_PROJECTION_SCHEMA_VERSION = 1
ABI_PROJECTION_KIND = "vast_backend_runtime_replay_handle_abi_projection_v1"
MAX_PROTOCOL_BYTES = 4 * 1024 * 1024
FALSE_CLAIMS = (
    "handle_abi_implemented", "os_handle_object_types_validated",
    "inherited_handle_set_validated", "handle_sealing_validated",
    "standard_handle_mapping_validated", "process_created",
    "process_executed", "execution_authorized",
)
_PROJECTION_DOMAIN = b"VAST:backend-runtime-replay-handle-abi-projection:v1\0"
_AUTHORITY_DOMAIN = b"VAST:backend-runtime-replay-handle-abi-authority:v1\0"
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED = frozenset({"CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
_ROLE_NAMES = (
    "runner_entrypoint_read", "runner_authority_read",
    "validator_authority_read", "validation_request_read",
    "raw_evidence_read", "runtime_closure_bundle_read", "challenge_read",
    "stdin_eof_read", "record_stdout_write", "acknowledgement_stderr_write",
)
_GRAMMAR = (
    "hmap4;runner_entrypoint_read={u64};runner_authority_read={u64};"
    "validator_authority_read={u64};validation_request_read={u64};"
    "raw_evidence_read={u64};runtime_closure_bundle_read={u64};"
    "challenge_read={u64};stdin_eof_read={u64};record_stdout_write={u64};"
    "acknowledgement_stderr_write={u64}"
)
_COMPLEMENTARY = ("challenge_write", "stdin_eof_write", "record_stdout_read",
                  "acknowledgement_stderr_read")
_STD_MAPPING = {"STARTF_USESTDHANDLES": True,
                "hStdInput": "stdin_eof_read",
                "hStdOutput": "record_stdout_write",
                "hStdError": "acknowledgement_stderr_write"}
_TOP_FIELDS = frozenset({"schema_version", "artifact_kind", "status",
    "supported_host_os", "supported_host_architecture",
    "replay_invocation_protocol_v4_ref", "replay_invocation_protocol_v4_content",
    "handle_abi_projection", "handle_abi_projection_sha256", *FALSE_CLAIMS,
    "handle_abi_authority_sha256"})
_REF_FIELDS = frozenset({"artifact_schema_version", "artifact_kind",
                         "descriptor", "content_identity_sha256"})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})


class ReplayHandleAbiAuthorityV1Error(ValueError):
    """The handle-ABI authority, projection, dependency, or pin is invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayHandleAbiAuthorityV1Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None,
                 depth: int = 0) -> None:
    _require(depth <= 32, "handle ABI authority JSON nesting is excessive")
    typ = type(value)
    if typ not in (dict, list):
        _require(typ in (str, int, bool),
                 "handle ABI authority contains a non-contract JSON type")
        return
    identities = set() if active is None else active
    identity = id(value)
    _require(identity not in identities, "handle ABI authority contains a cycle")
    identities.add(identity)
    try:
        items = value.items() if typ is dict else enumerate(value)
        for key, item in items:
            if typ is dict:
                _require(type(key) is str,
                         "handle ABI authority has a non-string key")
            _strict_json(item, active=identities, depth=depth + 1)
    finally:
        identities.remove(identity)


def _canonical_bytes(value: object) -> bytes:
    _strict_json(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise ReplayHandleAbiAuthorityV1Error(
            "handle ABI authority is not canonical JSON") from error


def _domain_sha(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} is not a lowercase SHA-256 identity")
    return value


def _pins(*, expected_authority_sha256: Any,
          expected_replay_invocation_protocol_v4_sha256: Any,
          expected_handle_abi_projection_sha256: Any) -> tuple[str, str, str]:
    values = (_sha(expected_authority_sha256, "expected handle ABI authority"),
        _sha(expected_replay_invocation_protocol_v4_sha256,
             "expected replay protocol v4"),
        _sha(expected_handle_abi_projection_sha256,
             "expected handle ABI projection"))
    _require(len(set(values)) == 3, "handle ABI semantic pin domains alias")
    return values


def _relative_path(value: Any) -> str:
    _require(type(value) is str and bool(value),
             "replay protocol v4 path is invalid")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    parts = posix.parts
    _require("\\" not in value and ":" not in value and "\x00" not in value
        and not posix.is_absolute() and posix.anchor == ""
        and windows.drive == "" and windows.root == "" and windows.anchor == ""
        and posix.as_posix() == value and bool(parts)
        and all(part not in {"", ".", ".."} and not part.endswith((".", " "))
                and not any(ord(char) < 32 for char in part)
                and part.split(".", 1)[0].upper() not in _RESERVED
                for part in parts), "replay protocol v4 path is unsafe")
    return value


def _descriptor(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
             "replay protocol v4 descriptor fields drifted")
    size = value.get("size_bytes")
    _require(type(size) is int and 0 < size <= MAX_PROTOCOL_BYTES,
             "replay protocol v4 descriptor size is invalid")
    return {"path": _relative_path(value.get("path")), "size_bytes": size,
            "sha256": _sha(value.get("sha256"), "replay protocol v4 file")}


def _typed_protocol_ref(value: Any, protocol_pin: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _REF_FIELDS,
             "replay protocol v4 typed reference fields drifted")
    _require(type(value.get("artifact_schema_version")) is int
             and value.get("artifact_schema_version") == protocol_v4.SCHEMA_VERSION,
             "replay protocol v4 reference schema drifted")
    _require(type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == protocol_v4.ARTIFACT_KIND,
             "replay protocol v4 reference kind drifted")
    identity = _sha(value.get("content_identity_sha256"),
                    "replay protocol v4 semantic")
    _require(identity == protocol_pin,
             "replay protocol v4 reference semantic pin drifted")
    return {"artifact_schema_version": protocol_v4.SCHEMA_VERSION,
            "artifact_kind": protocol_v4.ARTIFACT_KIND,
            "descriptor": _descriptor(value.get("descriptor")),
            "content_identity_sha256": identity}


def _exact(value: Any, expected: Any, label: str) -> Any:
    _require(type(value) is type(expected) and value == expected,
             f"handle ABI {label} drifted")
    return copy.deepcopy(value)


def _exact_type_skeleton(value: Any, expected: Any, *, path: str) -> None:
    _require(type(value) is type(expected),
             f"handle ABI projection type drifted at {path}")
    if type(expected) is dict:
        _require(set(value) == set(expected),
                 f"handle ABI projection fields drifted at {path}")
        for key in expected:
            _exact_type_skeleton(value[key], expected[key], path=f"{path}.{key}")
    elif type(expected) is list:
        _require(len(value) == len(expected),
                 f"handle ABI projection list drifted at {path}")
        for position, (item, expected_item) in enumerate(zip(value, expected)):
            _exact_type_skeleton(item, expected_item,
                                 path=f"{path}[{position}]")


def _normalized_projection(protocol_content: Any, *,
                           protocol_pin: str) -> dict[str, Any]:
    """Derive one closed projection after redundant-surface agreement checks."""
    pin = _sha(protocol_pin, "replay protocol v4 projection source")
    try:
        protocol = protocol_v4.validate_replay_runner_invocation_protocol_v4_contract(
            protocol_content, expected_protocol_sha256=pin)
    except protocol_v4.ReplayRunnerInvocationProtocolV4Error as error:
        raise ReplayHandleAbiAuthorityV1Error(
            f"handle ABI protocol-v4 dependency invalid: {error}") from error
    child = protocol["child_handle_map_abi"]
    native = protocol["native_broker_abi"]["process_creation"]
    process = protocol["process_contract_template"]
    roles = child["ordered_roles"]
    _require(type(roles) is list and len(roles) == 10,
             "handle ABI requires exactly ten roles")
    _require(all(type(item) is dict and type(item.get("role")) is str
                 for item in roles)
             and tuple(item["role"] for item in roles) == _ROLE_NAMES
             and len({item["role"] for item in roles}) == 10,
             "handle ABI role order or uniqueness drifted")
    runtime = child["runtime_representation"]
    _exact(runtime, {"grammar_template": _GRAMMAR, "exact_role_count": 10,
        "number_encoding": "canonical_unsigned_decimal_u64", "minimum": 1,
        "maximum": 18446744073709551615, "pseudo_handles": "forbidden",
        "pairwise_distinct": True, "process_local_only": True,
        "persisted": False, "semantic_hash_input": False,
        "logging": "forbidden"}, "runtime representation")
    inheritance = child["inheritance"]
    _exact(inheritance, {
        "allowlist_api": "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        "input_handle_allowlist": "exactly_all_ten_ordered_roles",
        "ambient_handle_inheritance": "forbidden",
        "prepared_before_state": "SEALED", "child_path_reopen": "forbidden",
    }, "inheritance contract")
    _exact(native["api"], "CreateProcessW", "native process API")
    _exact(native["creation_flags"],
           ["CREATE_SUSPENDED", "EXTENDED_STARTUPINFO_PRESENT"],
           "native creation flags")
    _exact(native["bInheritHandles"], True, "native inheritance switch")
    _exact(native["attribute_handle_allowlist"],
           "exact_PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
           "native attribute allowlist")
    _exact(native["attribute_handle_allowlist_members"],
           "exactly_all_ten_ordered_handle_map_roles",
           "native attribute allowlist members")
    _exact(native["ambient_inheritable_handles"], "forbidden",
           "native ambient inheritance")
    standard = child["standard_handle_mapping"]
    _require(type(standard) is dict
             and {key: standard.get(key) for key in _STD_MAPPING} == _STD_MAPPING,
             "handle ABI standard mapping drifted")
    _exact(standard.get("stdin_eof_parent_action"),
           "close_parent_private_complementary_writer_before_resume",
           "stdin EOF parent action")
    _exact(standard.get("stdin_child_observation"), "immediate_eof",
           "stdin EOF observation")
    _exact(native["standard_handle_binding"], _STD_MAPPING,
           "native standard handle binding")
    _exact(process["stdin"], {
        "mode": "inherited_pipe_read_immediate_eof",
        "child_handle_role": "stdin_eof_read",
        "parent_action": "close_parent_private_complementary_writer_before_resume",
    }, "process stdin mapping")
    _exact(process["stdout"]["child_handle_role"], "record_stdout_write",
           "process stdout mapping")
    _exact(process["stdout"]["parent_private_complementary_handle"],
           "record_stdout_read", "process stdout complementary endpoint")
    _exact(process["acknowledgement"]["child_handle_role"],
           "acknowledgement_stderr_write", "process stderr mapping")
    _exact(process["acknowledgement"]["parent_private_complementary_handle"],
           "acknowledgement_stderr_read",
           "process stderr complementary endpoint")
    _exact(child["parent_private_complementary_handles"], list(_COMPLEMENTARY),
           "parent-private complementary endpoints")
    _exact(child["parent_private_complementary_handle_inheritance"],
           "forbidden", "complementary inheritance")
    _exact(child["parent_private_complementary_handle_map_membership"],
           "forbidden", "complementary map membership")
    persistence = child["protocol_persistence"]
    _exact(persistence, {"stores_role_order": True, "stores_grammar": True,
        "stores_constraints": True,
        "stores_process_local_handle_numbers": False}, "protocol persistence")
    return {
        "schema_version": ABI_PROJECTION_SCHEMA_VERSION,
        "artifact_kind": ABI_PROJECTION_KIND,
        "source_protocol_identity": {
            "artifact_schema_version": protocol_v4.SCHEMA_VERSION,
            "artifact_kind": protocol_v4.ARTIFACT_KIND,
            "content_identity_sha256": pin,
        },
        "ordered_roles": copy.deepcopy(roles),
        "handle_map_runtime_representation": copy.deepcopy(runtime),
        "handle_inheritance": copy.deepcopy(inheritance),
        "native_process_creation_handle_contract": {
            "api": native["api"],
            "creation_flags": copy.deepcopy(native["creation_flags"]),
            "bInheritHandles": native["bInheritHandles"],
            "attribute_handle_allowlist": native["attribute_handle_allowlist"],
            "attribute_handle_allowlist_members":
                native["attribute_handle_allowlist_members"],
            "standard_handle_binding":
                copy.deepcopy(native["standard_handle_binding"]),
            "ambient_inheritable_handles":
                native["ambient_inheritable_handles"],
        },
        "standard_handle_mapping": copy.deepcopy(standard),
        "parent_private_complementary_handles": list(_COMPLEMENTARY),
        "parent_private_complementary_handle_inheritance": "forbidden",
        "parent_private_complementary_handle_map_membership": "forbidden",
        "protocol_persistence": copy.deepcopy(persistence),
    }


def validate_backend_runtime_replay_handle_abi_authority_v1(
    value: Any, *, expected_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
    expected_handle_abi_projection_sha256: str,
) -> dict[str, Any]:
    """Purely validate the authority against all mandatory external pins."""
    authority_pin, protocol_pin, projection_pin = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_replay_invocation_protocol_v4_sha256=
            expected_replay_invocation_protocol_v4_sha256,
        expected_handle_abi_projection_sha256=
            expected_handle_abi_projection_sha256)
    _strict_json(value)
    _require(type(value) is dict and set(value) == _TOP_FIELDS,
             "handle ABI authority fields drifted")
    _require(type(value.get("schema_version")) is int
             and value.get("schema_version") == SCHEMA_VERSION
             and type(value.get("artifact_kind")) is str
             and value.get("artifact_kind") == ARTIFACT_KIND,
             "handle ABI authority header drifted")
    _require(type(value.get("status")) is str and value.get("status")
             == "immutable_non_authorizing_handle_abi_projection",
             "handle ABI authority status overstates scope")
    _exact(value.get("supported_host_os"), ["nt"], "authority host OS")
    _exact(value.get("supported_host_architecture"), ["amd64"],
           "authority host architecture")
    reference = _typed_protocol_ref(
        value.get("replay_invocation_protocol_v4_ref"), protocol_pin)
    protocol_content = value.get("replay_invocation_protocol_v4_content")
    persisted_protocol = _canonical_bytes(protocol_content) + b"\n"
    descriptor = reference["descriptor"]
    _require(descriptor["size_bytes"] == len(persisted_protocol)
             and descriptor["sha256"]
             == hashlib.sha256(persisted_protocol).hexdigest(),
             "replay protocol v4 descriptor contradicts embedded content")
    projection = _normalized_projection(protocol_content, protocol_pin=protocol_pin)
    supplied_projection = value.get("handle_abi_projection")
    _exact_type_skeleton(supplied_projection, projection,
                         path="$.handle_abi_projection")
    _require(supplied_projection == projection,
             "handle ABI projection drifted from exact protocol-v4 source")
    observed_projection = _sha(value.get("handle_abi_projection_sha256"),
                               "handle ABI projection")
    _require(observed_projection == projection_pin
             == _domain_sha(_PROJECTION_DOMAIN, projection),
             "handle ABI projection identity drifted")
    descriptor_sha = reference["descriptor"]["sha256"]
    _require(len({authority_pin, protocol_pin, projection_pin, descriptor_sha}) == 4,
             "handle ABI identity namespace aliases")
    normalized: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "status": "immutable_non_authorizing_handle_abi_projection",
        "supported_host_os": ["nt"], "supported_host_architecture": ["amd64"],
        "replay_invocation_protocol_v4_ref": reference,
        "replay_invocation_protocol_v4_content": copy.deepcopy(protocol_content),
        "handle_abi_projection": projection,
        "handle_abi_projection_sha256": observed_projection,
    }
    for field in FALSE_CLAIMS:
        _require(value.get(field) is False,
                 f"handle ABI authority {field} claim drifted")
        normalized[field] = False
    observed_authority = _sha(value.get("handle_abi_authority_sha256"),
                              "handle ABI authority")
    _require(observed_authority == authority_pin
             == _domain_sha(_AUTHORITY_DOMAIN, normalized),
             "handle ABI authority identity drifted")
    normalized["handle_abi_authority_sha256"] = observed_authority
    return copy.deepcopy(normalized)


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    supplied = Path(project_root)
    _require(supplied.is_absolute(), "project root is not absolute")
    try:
        resolved, info = supplied.resolve(strict=True), supplied.lstat()
    except OSError as error:
        raise ReplayHandleAbiAuthorityV1Error(
            f"project root cannot be inspected: {error}") from error
    _require(resolved == supplied and stat.S_ISDIR(info.st_mode)
             and not bool(getattr(info, "st_file_attributes", 0)) & 0x400,
             "project root is not a canonical plain directory")
    return resolved, (int(info.st_dev), int(info.st_ino))


def _win_open(path: Path, *, directory: bool) -> int:
    access = (_LIST_DIRECTORY | _READ_ATTRIBUTES) if directory else (
        _GENERIC_READ | _READ_ATTRIBUTES)
    flags = _OPEN_REPARSE_POINT | (_BACKUP_SEMANTICS if directory else 0)
    ctypes.set_last_error(0)
    handle = _CREATE_FILE(str(path), access, _SHARE_READ, None, _OPEN_EXISTING,
                          flags, None)
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
        raise OSError("handle ABI protocol artifact is not a disk file")
    identity, attributes, standard = (
        _FileIdInfo(), _FileAttributeTagInfo(), _FileStandardInfo())
    for info_class, item in ((_FILE_ID_INFO, identity),
                             (_FILE_ATTRIBUTE_TAG_INFO, attributes),
                             (_FILE_STANDARD_INFO, standard)):
        if not _GET_FILE_INFORMATION(native, info_class, ctypes.byref(item),
                                     ctypes.sizeof(item)):
            raise ctypes.WinError(ctypes.get_last_error())
    return {"volume": int(identity.VolumeSerialNumber),
            "id": bytes(identity.FileId.Identifier),
            "attributes": int(attributes.FileAttributes),
            "reparse_tag": int(attributes.ReparseTag),
            "size": int(standard.EndOfFile),
            "nlink": int(standard.NumberOfLinks),
            "delete_pending": bool(standard.DeletePending),
            "directory": bool(standard.Directory)}


def _win_fingerprint(value: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(value[key] for key in ("volume", "id", "attributes",
        "reparse_tag", "size", "nlink", "delete_pending", "directory"))


def _win_validate(value: Mapping[str, Any], *, directory: bool,
                  volume: int) -> None:
    _require(bool(value["directory"]) == directory
             and not bool(value["delete_pending"]),
             "handle ABI protocol artifact kind drifted")
    _require(not int(value["attributes"]) & _ATTR_REPARSE,
             "handle ABI protocol path contains a reparse point")
    _require(int(value["volume"]) == volume,
             "handle ABI protocol artifact volume drifted")
    if not directory:
        _require(int(value["nlink"]) == 1,
                 "handle ABI protocol artifact has multiple hard links")


def _read_windows(root: Path, relative: PurePosixPath,
                  root_identity: tuple[int, int]) -> tuple[dict[str, Any], bytes]:
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
                 == root_identity, "project root changed before handle ABI read")
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
                     "handle ABI protocol path aliases a parent")
            seen.add(identity)
            held.append((cursor, True, _win_fingerprint(info)))
        path = cursor / relative.parts[-1]
        final_handle = _win_open(path, directory=False)
        info = _win_info(final_handle)
        _win_validate(info, directory=False, volume=volume)
        identity = (volume, bytes(info["id"]))
        _require(identity not in seen,
                 "handle ABI protocol artifact aliases a parent")
        fingerprint = _win_fingerprint(info)
        descriptor_fd = msvcrt.open_osfhandle(
            final_handle, os.O_RDONLY | int(getattr(os, "O_BINARY", 0)))
        final_handle = None
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_PROTOCOL_BYTES,
                     "handle ABI protocol artifact exceeds size limit")
            chunks.append(chunk)
        current = _win_info(int(msvcrt.get_osfhandle(descriptor_fd)))
        _require(_win_fingerprint(current) == fingerprint,
                 "handle ABI protocol artifact changed while reading")
        for expected_path, is_directory, expected in held + [
                (path, False, fingerprint)]:
            reopened: int | None = None
            primary = False
            try:
                reopened = _win_open(expected_path, directory=is_directory)
                observed = _win_info(reopened)
                _win_validate(observed, directory=is_directory, volume=volume)
                _require(_win_fingerprint(observed) == expected,
                         "handle ABI protocol path changed while reading")
            except BaseException:
                primary = True
                raise
            finally:
                if reopened is not None:
                    try:
                        _win_close(reopened)
                    except OSError:
                        if not primary:
                            raise
        payload = b"".join(chunks)
        return ({"path": relative.as_posix(), "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}, payload)
    except ReplayHandleAbiAuthorityV1Error:
        raise
    except (OSError, ValueError) as error:
        raise ReplayHandleAbiAuthorityV1Error(
            f"handle ABI protocol physical read failed: {error}") from error
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
            raise ReplayHandleAbiAuthorityV1Error(
                "handle ABI protocol handle cleanup failed") from close_error


def _read_posix(root: Path, relative: PurePosixPath,
                root_identity: tuple[int, int]) -> tuple[dict[str, Any], bytes]:
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
                 "project root changed before handle ABI read")
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
                     "handle ABI protocol parent drifted")
            _require(identity not in seen,
                     "handle ABI protocol path aliases a parent")
            seen.add(identity)
            components.append((part, identity))
            parent_fd = child_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | int(getattr(os, "O_CLOEXEC", 0))
        descriptor_fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1,
                 "handle ABI protocol artifact is not a unique regular file")
        _require(identity[0] == root_identity[0] and identity not in seen,
                 "handle ABI protocol artifact identity/volume drifted")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= MAX_PROTOCOL_BYTES,
                     "handle ABI protocol artifact exceeds size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor_fd)
        _require(opened == after,
                 "handle ABI protocol artifact changed while reading")
        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require((int(verify_root.st_dev), int(verify_root.st_ino)) == root_identity,
                 "project root changed while handle ABI read")
        for part, expected in components:
            child_fd = os.open(part, directory_flags, dir_fd=verify_parent)
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require((int(child_info.st_dev), int(child_info.st_ino)) == expected,
                     "handle ABI protocol path component changed while reading")
            verify_parent = child_fd
        verify_fd = os.open(relative.parts[-1], flags, dir_fd=verify_parent)
        verification.append(verify_fd)
        _require(os.fstat(verify_fd) == after,
                 "handle ABI protocol path changed while reading")
        payload = b"".join(chunks)
        return ({"path": relative.as_posix(), "size_bytes": len(payload),
                 "sha256": hashlib.sha256(payload).hexdigest()}, payload)
    except ReplayHandleAbiAuthorityV1Error:
        raise
    except OSError as error:
        raise ReplayHandleAbiAuthorityV1Error(
            f"handle ABI protocol physical read failed: {error}") from error
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
            raise ReplayHandleAbiAuthorityV1Error(
                "handle ABI protocol descriptor cleanup failed") from close_error


def _physical_protocol(*, project_root: Path, relative_path: str,
                       protocol_pin: str) -> dict[str, Any]:
    root, root_identity = _root(project_root)
    relative = PurePosixPath(_relative_path(relative_path))
    descriptor, payload = (_read_windows(root, relative, root_identity)
        if os.name == "nt" else _read_posix(root, relative, root_identity))
    try:
        _require(payload.endswith(b"\n") and payload[:-1] == payload.rstrip(b"\n"),
                 "replay protocol v4 must have exactly one trailing LF")
        value = json.loads(payload[:-1].decode("utf-8"))
        _require(type(value) is dict and _canonical_bytes(value) == payload[:-1],
                 "replay protocol v4 is not exact canonical JSON")
        protocol_v4.validate_replay_runner_invocation_protocol_v4_contract(
            value, expected_protocol_sha256=protocol_pin)
    except (UnicodeError, json.JSONDecodeError,
            protocol_v4.ReplayRunnerInvocationProtocolV4Error) as error:
        raise ReplayHandleAbiAuthorityV1Error(
            f"replay protocol v4 physical artifact invalid: {error}") from error
    return {"root": root, "descriptor": descriptor, "content": value}


def assess_backend_runtime_replay_handle_abi_authority_v1(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
    expected_handle_abi_projection_sha256: str,
) -> dict[str, Any]:
    """Observe exactly one canonical protocol-v4 artifact; authorize nothing."""
    authority_sha = (value.get("handle_abi_authority_sha256")
                     if type(value) is dict else None)
    projection_sha = (value.get("handle_abi_projection_sha256")
                      if type(value) is dict else None)
    authority_valid = protocol_pin_valid = projection_valid = False
    handle_bound = content_matched = exact_projection = namespace = False
    checked = 0
    blockers: list[str] = []
    try:
        authority = validate_backend_runtime_replay_handle_abi_authority_v1(
            value, expected_authority_sha256=expected_authority_sha256,
            expected_replay_invocation_protocol_v4_sha256=
                expected_replay_invocation_protocol_v4_sha256,
            expected_handle_abi_projection_sha256=
                expected_handle_abi_projection_sha256)
        authority_valid = protocol_pin_valid = projection_valid = True
        exact_projection = namespace = True
        physical = _physical_protocol(project_root=project_root,
            relative_path=authority["replay_invocation_protocol_v4_ref"]
                                   ["descriptor"]["path"],
            protocol_pin=expected_replay_invocation_protocol_v4_sha256)
        observed_ref = {
            "artifact_schema_version": protocol_v4.SCHEMA_VERSION,
            "artifact_kind": protocol_v4.ARTIFACT_KIND,
            "descriptor": physical["descriptor"],
            "content_identity_sha256":
                expected_replay_invocation_protocol_v4_sha256,
        }
        _require(observed_ref == authority["replay_invocation_protocol_v4_ref"],
                 "replay protocol v4 typed reference drifted physically")
        handle_bound = True
        _require(physical["content"]
                 == authority["replay_invocation_protocol_v4_content"],
                 "replay protocol v4 canonical content drifted physically")
        content_matched, checked = True, 1
    except (ReplayHandleAbiAuthorityV1Error,
            protocol_v4.ReplayRunnerInvocationProtocolV4Error,
            OSError, TypeError, ValueError) as error:
        blockers.append(str(error))
        checked = 0
    blockers = sorted(dict.fromkeys(item for item in blockers if item))
    success = (authority_valid and protocol_pin_valid and projection_valid
        and handle_bound and content_matched and exact_projection and namespace
        and checked == 1 and not blockers)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ASSESSMENT_KIND,
        "status": ("protocol_v4_artifact_physically_observed"
                   if success else "blocked"),
        "handle_abi_authority_sha256": authority_sha,
        "handle_abi_projection_sha256": projection_sha,
        "checked_artifact_count": checked if success else 0,
        "blockers": blockers, "authority_pin_validated": authority_valid,
        "protocol_v4_semantic_pin_validated": protocol_pin_valid,
        "handle_abi_projection_pin_validated": projection_valid,
        "protocol_v4_artifact_handle_bound": handle_bound,
        "protocol_v4_exact_canonical_content_matched": content_matched,
        "protocol_projection_exactly_validated": exact_projection,
        "identity_namespace_separated": namespace,
        "physical_validation_scope": "single_protocol_v4_artifact_only",
    }
    result.update({field: False for field in FALSE_CLAIMS})
    return result


def build_backend_runtime_replay_handle_abi_authority_v1(
    *, project_root: Path, replay_invocation_protocol_v4_path: str,
    expected_authority_sha256: str,
    expected_replay_invocation_protocol_v4_sha256: str,
    expected_handle_abi_projection_sha256: str,
) -> dict[str, Any]:
    """Read protocol-v4 bytes and build an authority without persisting it."""
    authority_pin, protocol_pin, projection_pin = _pins(
        expected_authority_sha256=expected_authority_sha256,
        expected_replay_invocation_protocol_v4_sha256=
            expected_replay_invocation_protocol_v4_sha256,
        expected_handle_abi_projection_sha256=
            expected_handle_abi_projection_sha256)
    physical = _physical_protocol(
        project_root=project_root,
        relative_path=replay_invocation_protocol_v4_path,
        protocol_pin=protocol_pin)
    projection = _normalized_projection(
        physical["content"], protocol_pin=protocol_pin)
    _require(_domain_sha(_PROJECTION_DOMAIN, projection) == projection_pin,
             "handle ABI projection external pin drifted")
    _require(len({authority_pin, protocol_pin, projection_pin,
                  physical["descriptor"]["sha256"]}) == 4,
             "handle ABI identity namespace aliases")
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ARTIFACT_KIND,
        "status": "immutable_non_authorizing_handle_abi_projection",
        "supported_host_os": ["nt"], "supported_host_architecture": ["amd64"],
        "replay_invocation_protocol_v4_ref": {
            "artifact_schema_version": protocol_v4.SCHEMA_VERSION,
            "artifact_kind": protocol_v4.ARTIFACT_KIND,
            "descriptor": physical["descriptor"],
            "content_identity_sha256": protocol_pin,
        },
        "replay_invocation_protocol_v4_content": physical["content"],
        "handle_abi_projection": projection,
        "handle_abi_projection_sha256": projection_pin,
        **{field: False for field in FALSE_CLAIMS},
    }
    value["handle_abi_authority_sha256"] = _domain_sha(_AUTHORITY_DOMAIN, value)
    _require(value["handle_abi_authority_sha256"] == authority_pin,
             "handle ABI authority external pin drifted")
    validated = validate_backend_runtime_replay_handle_abi_authority_v1(
        value, expected_authority_sha256=authority_pin,
        expected_replay_invocation_protocol_v4_sha256=protocol_pin,
        expected_handle_abi_projection_sha256=projection_pin)
    assessment = assess_backend_runtime_replay_handle_abi_authority_v1(
        validated, project_root=physical["root"],
        expected_authority_sha256=authority_pin,
        expected_replay_invocation_protocol_v4_sha256=protocol_pin,
        expected_handle_abi_projection_sha256=projection_pin)
    _require(assessment.get("status")
             == "protocol_v4_artifact_physically_observed"
             and assessment.get("checked_artifact_count") == 1
             and assessment.get("protocol_projection_exactly_validated") is True,
             "handle ABI authority build physical assessment blocked")
    return validated


__all__ = [
    "SCHEMA_VERSION", "ARTIFACT_KIND", "ASSESSMENT_KIND",
    "ABI_PROJECTION_SCHEMA_VERSION", "ABI_PROJECTION_KIND", "FALSE_CLAIMS",
    "ReplayHandleAbiAuthorityV1Error",
    "validate_backend_runtime_replay_handle_abi_authority_v1",
    "assess_backend_runtime_replay_handle_abi_authority_v1",
    "build_backend_runtime_replay_handle_abi_authority_v1",
]
