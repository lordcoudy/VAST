#!/usr/bin/env python3
"""Validate pre-staged checkpoint-source closure candidates without execution."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _WIN_GENERIC_READ = 0x80000000
    _WIN_LIST_DIRECTORY = 0x0001
    _WIN_READ_ATTRIBUTES = 0x0080
    _WIN_SYNCHRONIZE = 0x00100000
    _WIN_SHARE_READ = 0x00000001
    _WIN_OPEN_EXISTING = 3
    _WIN_ATTRIBUTE_REPARSE = 0x00000400
    _WIN_BACKUP_SEMANTICS = 0x02000000
    _WIN_OPEN_REPARSE_POINT = 0x00200000
    _WIN_FILE_TYPE_DISK = 0x0001
    _WIN_FILE_STANDARD_INFO = 1
    _WIN_FILE_ATTRIBUTE_TAG_INFO = 9
    _WIN_FILE_ID_INFO = 18
    _WIN_INVALID_HANDLE = ctypes.c_void_p(-1).value
    _NT_OBJ_CASE_INSENSITIVE = 0x00000040
    _NT_FILE_OPEN = 1
    _NT_DIRECTORY_FILE = 0x00000001
    _NT_SYNCHRONOUS_IO_NONALERT = 0x00000020
    _NT_NON_DIRECTORY_FILE = 0x00000040
    _NT_OPEN_REPARSE_POINT = 0x00200000

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

    class _NtUnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class _NtObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(_NtUnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class _NtIoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("Status", ctypes.c_void_p),
            ("Information", ctypes.c_size_t),
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
    _WIN_NTDLL = ctypes.WinDLL("ntdll")
    _WIN_NT_CREATE_FILE = _WIN_NTDLL.NtCreateFile
    _WIN_NT_CREATE_FILE.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
        ctypes.POINTER(_NtObjectAttributes), ctypes.POINTER(_NtIoStatusBlock),
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    _WIN_NT_CREATE_FILE.restype = ctypes.c_long
else:
    import ctypes
    import fcntl

    _POSIX_SYS_OPENAT2 = 437
    _POSIX_RESOLVE_NO_XDEV = 0x01
    _POSIX_RESOLVE_NO_MAGICLINKS = 0x02
    _POSIX_RESOLVE_NO_SYMLINKS = 0x04
    _POSIX_RESOLVE_BENEATH = 0x08

    class _PosixOpenHow(ctypes.Structure):
        _fields_ = [
            ("flags", ctypes.c_uint64),
            ("mode", ctypes.c_uint64),
            ("resolve", ctypes.c_uint64),
        ]

    _POSIX_LIBC = ctypes.CDLL(None, use_errno=True)
    _POSIX_SYSCALL = _POSIX_LIBC.syscall
    _POSIX_SYSCALL.restype = ctypes.c_long


SCHEMA_VERSION = 1
MANIFEST_KIND = "vast_checkpoint_source_runtime_closure_manifest_v1"
CLOSURE_SET_KIND = "vast_checkpoint_source_runtime_closure_set_v1"
ENVIRONMENT_POLICY_KIND = "vast_checkpoint_source_environment_policy_v1"
BUILD_PROVENANCE_KIND = "vast_checkpoint_source_build_provenance_v1"
INVOCATION_CONTRACT_KIND = "vast_checkpoint_source_invocation_contract_v1"
GST_REGISTRY_CATALOG_KIND = "vast_checkpoint_source_gst_registry_catalog_v1"
AUTHORITY_KIND = "vast_checkpoint_source_runtime_closure_authority_v1"
ASSESSMENT_KIND = "vast_checkpoint_source_runtime_closure_authority_assessment_v1"
STAGE_PREFIX = "runtime/checkpoint_source/v1/"
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_RUNTIME_ARTIFACTS = 4096
MAX_STAGE_COMPONENT_UTF16_BYTES = 510
MAX_STAGE_PATH_UTF16_BYTES = 32760

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_BUILD_ID_RE = re.compile(r"[0-9a-f]{40}\Z")
_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_~-]{0,127}\Z")
_RUNTIME_CLASS_ORDER = {
    "source_executable": 0,
    "elf_interpreter": 1,
    "gst_plugin_scanner": 2,
    "shared_object": 3,
    "gst_plugin_module": 4,
    "gst_registry_seed": 5,
    "gst_registry_catalog": 6,
}
_SOURCE_INPUT_CLASSES = (
    "cmake_project_file",
    "coordinator_translation_unit",
    "admission_transport_header",
)
_SOURCE_OBJECT_CLASS = "coordinator_object"
_TOOL_CLASSES = ("cmake", "cxx_compiler", "pkg_config", "build_tool")
_FACTORIES = ("appsink", "filesrc", "h264parse", "h265parse", "qtdemux")
_PKG_MODULES = (
    "gstreamer-1.0",
    "gstreamer-app-1.0",
    "gstreamer-rtp-1.0",
    "gstreamer-video-1.0",
)
_ARGV_FIELDS = (
    ("--source-path", "absolute_dataset_path"),
    ("--dataset-id", "lowercase_identifier"),
    ("--source-sha256", "lowercase_sha256"),
    ("--checkpoint-container", "literal_mp4"),
    ("--checkpoint-codec", "h264_or_h265"),
    ("--source-duration-ns", "positive_uint64"),
    ("--playback-timestamp-scale", "positive_uint64"),
    ("--source-replay", "literal_continuous"),
    ("--logical-stream-id", "nonnegative_int32"),
)
_STATIC_ENVIRONMENT = (
    ("GST_PLUGIN_SYSTEM_PATH_1_0", "${STAGE_ROOT}/plugins"),
    ("GST_PLUGIN_PATH_1_0", ""),
    ("GST_PLUGIN_SCANNER_1_0", "${STAGE_ROOT}/libexec/gstreamer-1.0/gst-plugin-scanner"),
    ("GST_REGISTRY_1_0", "${LEASE_ROOT}/gstreamer/registry.bin"),
    ("GST_REGISTRY_UPDATE", "no"),
    ("GST_REGISTRY_FORK", "no"),
    ("HOME", "${LEASE_ROOT}/home"),
    ("LANG", "C"),
    ("LC_ALL", "C"),
    ("TZ", "UTC"),
    ("XDG_CACHE_HOME", "${LEASE_ROOT}/xdg/cache"),
    ("XDG_CONFIG_HOME", "${LEASE_ROOT}/xdg/config"),
    ("XDG_DATA_HOME", "${LEASE_ROOT}/xdg/data"),
    ("XDG_RUNTIME_DIR", "${LEASE_ROOT}/xdg/runtime"),
)
_FORCED_UNSET = (
    "GIO_EXTRA_MODULES", "GST_DEBUG", "GST_PLUGIN_FEATURE_RANK",
    "GST_PLUGIN_PATH", "GST_PLUGIN_SCANNER", "GST_PLUGIN_SYSTEM_PATH",
    "GST_REGISTRY", "LD_AUDIT", "LD_DEBUG", "LD_LIBRARY_PATH", "LD_PRELOAD",
)
_DYNAMIC_ENVIRONMENT = (
    ("VAST_CHECKPOINT_WORKER_ID", "lowercase_identifier"),
    ("VAST_CHECKPOINT_RUN_ID", "nonempty_ascii"),
    ("VAST_CHECKPOINT_DATASET_ID", "lowercase_identifier"),
    ("VAST_CHECKPOINT_SOURCE_SHA256", "lowercase_sha256"),
    ("VAST_CHECKPOINT_STREAM_ID", "nonnegative_int32"),
    ("VAST_CHECKPOINT_SOURCE_CONTAINER", "literal_mp4"),
    ("VAST_CHECKPOINT_SOURCE_CODEC", "h264_or_h265"),
    ("VAST_CHECKPOINT_SOURCE_DURATION_NS", "positive_uint64"),
    ("VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE", "positive_uint64"),
    ("VAST_CHECKPOINT_SOURCE_REPLAY", "literal_continuous"),
    ("VAST_CHECKPOINT_ADMISSION_MODE", "literal_native_common_source_coordinator"),
    ("VAST_CHECKPOINT_ADMISSION_EVENT_FD", "decimal_fd"),
    ("VAST_CHECKPOINT_ADMISSION_ACK_FD", "decimal_fd"),
    ("VAST_CHECKPOINT_CONTROL_FD", "decimal_fd"),
    ("VAST_CHECKPOINT_STATUS_FD", "decimal_fd"),
    ("VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON", "canonical_consumer_fd_map"),
)
_FD_BINDINGS = (
    ("VAST_CHECKPOINT_ADMISSION_EVENT_FD", "admission_event_write", "write", "one"),
    ("VAST_CHECKPOINT_ADMISSION_ACK_FD", "admission_ack_read", "read", "one"),
    ("VAST_CHECKPOINT_CONTROL_FD", "lifecycle_control_read", "read", "one"),
    ("VAST_CHECKPOINT_STATUS_FD", "lifecycle_status_write", "write", "one"),
    ("VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON", "compressed_access_unit_write", "write", "one_or_more"),
)
_COMPILE_HARDENING = (
    "-O2", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=3",
    "-fPIE", "-fcf-protection=full",
)
_LINK_HARDENING = (
    "-Wl,-z,relro", "-Wl,-z,now", "-Wl,-z,noexecstack", "-pie",
)
_FALSE_CLAIMS = (
    "atomic_runtime_closure_snapshot_validated",
    "staged_bundle_immutability_validated",
    "actual_loader_resolution_enforced",
    "dynamic_loader_closure_completeness_validated",
    "plugin_dlopen_closure_completeness_validated",
    "gst_registry_semantics_validated",
    "gst_registry_currentness_validated",
    "gst_plugin_scanner_execution_validated",
    "gst_plugin_loading_validated",
    "environment_policy_enforced",
    "invocation_argv_enforced",
    "inherited_fd_set_enforced",
    "source_process_executed",
    "source_behavior_validated",
    "reproducible_build_independently_attested",
    "toolchain_closure_completeness_validated",
    "publication_capable_validated",
    "execution_authorized",
)


class CheckpointSourceRuntimeClosureAuthorityV1Error(ValueError):
    """Raised for malformed, unpinned, or physically drifting candidates."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            "value is not canonical-JSON encodable"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(type(value) is str and _SHA_RE.fullmatch(value) is not None,
             f"{label} must be an exact lowercase SHA-256")
    return value


def _build_id(value: Any, label: str) -> str:
    _require(type(value) is str and _BUILD_ID_RE.fullmatch(value) is not None,
             f"{label} must be an exact lowercase SHA-1 build ID")
    return value


def _size(value: Any, label: str) -> int:
    _require(type(value) is int and 0 < value <= MAX_ARTIFACT_BYTES,
             f"{label} must be a bounded positive integer")
    return value


def _mapping(value: Any, keys: Sequence[str], label: str) -> Mapping[str, Any]:
    _require(type(value) is dict and set(value) == set(keys),
             f"{label} schema is not exact")
    return value


def _exact_int(value: Any, expected: int, label: str) -> int:
    _require(type(value) is int and value == expected,
             f"{label} must be the exact integer {expected}")
    return value


def _expected_pins(
    *, expected_manifest_sha256: Any,
    expected_runtime_closure_set_sha256: Any,
    expected_environment_policy_sha256: Any,
    expected_build_provenance_sha256: Any,
    expected_invocation_contract_sha256: Any,
    expected_source_executable_sha256: Any,
    expected_source_executable_size_bytes: Any,
    expected_source_executable_build_id_sha1: Any,
    expected_cmake_file_sha256: Any,
    expected_coordinator_source_sha256: Any,
    expected_transport_header_sha256: Any,
    expected_source_object_sha256: Any,
    expected_authority_sha256: Any | None = None,
) -> dict[str, Any]:
    pins = {
        "manifest": _sha(expected_manifest_sha256, "expected manifest pin"),
        "set": _sha(expected_runtime_closure_set_sha256, "expected closure-set pin"),
        "environment": _sha(expected_environment_policy_sha256, "expected environment-policy pin"),
        "build": _sha(expected_build_provenance_sha256, "expected build-provenance pin"),
        "invocation": _sha(expected_invocation_contract_sha256, "expected invocation-contract pin"),
        "executable": _sha(expected_source_executable_sha256, "expected source-executable pin"),
        "executable_size": _size(expected_source_executable_size_bytes,
                                 "expected source-executable size"),
        "build_id": _build_id(expected_source_executable_build_id_sha1,
                              "expected source-executable build ID"),
        "cmake": _sha(expected_cmake_file_sha256, "expected CMake file pin"),
        "coordinator": _sha(expected_coordinator_source_sha256,
                            "expected coordinator source pin"),
        "transport": _sha(expected_transport_header_sha256,
                          "expected transport header pin"),
        "object": _sha(expected_source_object_sha256,
                       "expected coordinator object pin"),
    }
    if expected_authority_sha256 is not None:
        pins["authority"] = _sha(expected_authority_sha256, "expected authority pin")
    _require(len({pins[key] for key in (
        "manifest", "set", "environment", "build", "invocation", "executable",
        "cmake", "coordinator", "transport", "object",
    )}) == 10, "external SHA-256 pins must be trust-domain distinct")
    return pins


def _relative_path(value: Any, label: str) -> str:
    _require(type(value) is str and value.isascii() and value.startswith(STAGE_PREFIX),
             f"{label} must be inside the staged checkpoint-source namespace")
    _require("\\" not in value and not any(ord(char) < 0x20 for char in value),
             f"{label} contains forbidden characters")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.parts
             and all(part not in ("", ".", "..") for part in path.parts),
             f"{label} is not a canonical project-relative path")
    _require(path.as_posix() == value,
             f"{label} spelling is not canonical")
    _require(len(value.encode("utf-16-le")) <= MAX_STAGE_PATH_UTF16_BYTES,
             f"{label} exceeds the bounded staged-path length")
    reserved = {"con", "prn", "aux", "nul"}
    reserved.update(f"com{index}" for index in range(1, 10))
    reserved.update(f"lpt{index}" for index in range(1, 10))
    for part in path.parts:
        _require(len(part.encode("utf-16-le"))
                 <= MAX_STAGE_COMPONENT_UTF16_BYTES
                 and not part.endswith((" ", ".")) and ":" not in part
                 and part.split(".", 1)[0].casefold() not in reserved,
                 f"{label} contains a reserved path component")
    return path.as_posix()


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    source = _mapping(value, ("path", "size_bytes", "sha256"), label)
    return {
        "path": _relative_path(source["path"], f"{label} path"),
        "size_bytes": _size(source["size_bytes"], f"{label} size"),
        "sha256": _sha(source["sha256"], f"{label} byte identity"),
    }


def _artifact_ref(value: Any, label: str,
                  expected_class: str | None = None) -> dict[str, Any]:
    source = _mapping(
        value, ("artifact_id", "artifact_class", "descriptor",
                "content_identity_sha256"), label,
    )
    artifact_id = source["artifact_id"]
    artifact_class = source["artifact_class"]
    _require(type(artifact_id) is str and _ID_RE.fullmatch(artifact_id) is not None,
             f"{label} artifact ID is invalid")
    _require(type(artifact_class) is str
             and (expected_class is None or artifact_class == expected_class),
             f"{label} artifact class is invalid")
    descriptor = _descriptor(source["descriptor"], f"{label} descriptor")
    identity = _sha(source["content_identity_sha256"], f"{label} content identity")
    if artifact_class != "gst_registry_catalog":
        _require(identity == descriptor["sha256"],
                 f"{label} content identity differs from bytes")
    return {
        "artifact_id": artifact_id, "artifact_class": artifact_class,
        "descriptor": descriptor, "content_identity_sha256": identity,
    }


def _document_ref(value: Any, label: str) -> dict[str, Any]:
    source = _mapping(value, ("descriptor", "content_identity_sha256"), label)
    return {
        "descriptor": _descriptor(source["descriptor"], f"{label} descriptor"),
        "content_identity_sha256": _sha(
            source["content_identity_sha256"], f"{label} semantic identity"
        ),
    }


def _self_hashed_document(
    value: Any, *, kind: str, hash_field: str,
    keys: Sequence[str], label: str,
) -> dict[str, Any]:
    source = _mapping(value, keys, label)
    _exact_int(source["schema_version"], SCHEMA_VERSION,
               f"{label} schema version")
    _require(source["artifact_kind"] == kind,
             f"{label} kind/version differs")
    supplied = _sha(source[hash_field], f"{label} self hash")
    material = copy.deepcopy(dict(source))
    material.pop(hash_field)
    _require(supplied == _canonical_sha(material), f"{label} self hash differs")
    return copy.deepcopy(dict(source))


def _environment_policy(value: Any, expected_sha: str) -> dict[str, Any]:
    result = _self_hashed_document(
        value, kind=ENVIRONMENT_POLICY_KIND,
        hash_field="environment_policy_sha256",
        keys=("schema_version", "artifact_kind", "inherit_parent_environment",
              "static_environment", "forced_unset_environment",
              "dynamic_environment", "inherited_fd_bindings",
              "environment_policy_sha256"),
        label="environment policy",
    )
    _require(result["environment_policy_sha256"] == expected_sha,
             "environment-policy external pin differs")
    _require(result["inherit_parent_environment"] is False,
             "parent environment inheritance must remain disabled")
    _require(result["static_environment"] == [
        {"name": name, "value": setting} for name, setting in _STATIC_ENVIRONMENT
    ], "static environment policy differs")
    _require(result["forced_unset_environment"] == list(_FORCED_UNSET),
             "forced-unset environment policy differs")
    _require(result["dynamic_environment"] == [
        {"name": name, "value_kind": kind} for name, kind in _DYNAMIC_ENVIRONMENT
    ], "dynamic environment policy differs")
    _require(result["inherited_fd_bindings"] == [
        {"environment_name": name, "role": role, "direction": direction,
         "multiplicity": multiplicity}
        for name, role, direction, multiplicity in _FD_BINDINGS
    ], "inherited-FD policy differs")
    return result


def _classified_refs(value: Any, classes: Sequence[str],
                     label: str) -> list[dict[str, Any]]:
    _require(type(value) is list and len(value) == len(classes),
             f"{label} cardinality differs")
    return [_artifact_ref(item, f"{label}[{index}]", expected)
            for index, (item, expected) in enumerate(zip(value, classes))]


def _command(value: Any, expected_name: str) -> dict[str, Any]:
    source = _mapping(value, ("name", "argv", "argv_sha256"),
                      f"{expected_name} command")
    argv = source["argv"]
    _require(source["name"] == expected_name and type(argv) is list and argv
             and all(type(token) is str and token.isascii()
                     and token and "\x00" not in token for token in argv),
             f"{expected_name} command tokens are invalid")
    allowed = {
        "${CMAKE}", "${CXX}", "${PKG_CONFIG}", "${BUILD_TOOL}",
        "${SOURCE_ROOT}", "${BUILD_ROOT}", "${STAGE_ROOT}", "${SYSROOT}",
    }
    for token in argv:
        _require(not token.startswith(("/", "\\")) and "=/" not in token
                 and "=\\" not in token
                 and re.match(r"^[A-Za-z]:[\\/]", token) is None,
                 f"{expected_name} command contains an ambient absolute path")
        _require(all(marker in allowed for marker in re.findall(r"\$\{[^}]+\}", token)),
                 f"{expected_name} command contains an unknown root token")
    identity = _sha(source["argv_sha256"], f"{expected_name} command identity")
    _require(identity == _canonical_sha(argv),
             f"{expected_name} command identity differs")
    return {"name": expected_name, "argv": list(argv), "argv_sha256": identity}


def _build_provenance(value: Any, pins: Mapping[str, Any]) -> dict[str, Any]:
    result = _self_hashed_document(
        value, kind=BUILD_PROVENANCE_KIND,
        hash_field="build_provenance_sha256",
        keys=("schema_version", "artifact_kind", "target_name",
              "build_configuration", "source_inputs",
              "source_tree_identity_sha256", "source_object",
              "tool_artifacts", "tool_versions",
              "pkg_config_modules", "commands",
              "required_compile_hardening_flags",
              "required_link_hardening_flags", "reproducibility_observation",
              "toolchain_closure_complete", "build_provenance_sha256"),
        label="build provenance",
    )
    _require(result["build_provenance_sha256"] == pins["build"],
             "build-provenance external pin differs")
    _require(result["target_name"] == "vast_checkpoint_source"
             and result["build_configuration"] == "Release",
             "build target/configuration differs")
    source_inputs = _classified_refs(
        result["source_inputs"], _SOURCE_INPUT_CLASSES, "source inputs"
    )
    for item, pin in zip(source_inputs, (
        pins["cmake"], pins["coordinator"], pins["transport"],
    )):
        _require(item["descriptor"]["sha256"] == pin,
                 "source input differs from external pin")
    source_object = _artifact_ref(
        result["source_object"], "coordinator object", _SOURCE_OBJECT_CLASS
    )
    _require(source_object["descriptor"]["sha256"] == pins["object"],
             "coordinator object differs from external pin")
    tool_artifacts = _classified_refs(
        result["tool_artifacts"], _TOOL_CLASSES, "tool artifacts"
    )
    expected_tree = _canonical_sha({
        "schema_version": 1,
        "artifact_kind": "vast_checkpoint_source_tree_identity_v1",
        "source_inputs": source_inputs,
    })
    _require(_sha(result["source_tree_identity_sha256"], "source-tree identity")
             == expected_tree, "source-tree identity differs")
    versions = result["tool_versions"]
    _require(type(versions) is list and len(versions) == len(_TOOL_CLASSES),
             "tool-version cardinality differs")
    for index, (item, expected) in enumerate(zip(versions, _TOOL_CLASSES)):
        _mapping(item, ("tool_class", "version"), f"tool version[{index}]")
        _require(item["tool_class"] == expected
                 and type(item["version"]) is str
                 and _VERSION_RE.fullmatch(item["version"]) is not None,
                 "tool version differs")
    modules = result["pkg_config_modules"]
    _require(type(modules) is list and len(modules) == len(_PKG_MODULES),
             "pkg-config module cardinality differs")
    for index, (item, expected) in enumerate(zip(modules, _PKG_MODULES)):
        _mapping(item, ("name", "version"), f"pkg-config module[{index}]")
        _require(item["name"] == expected and type(item["version"]) is str
                 and _VERSION_RE.fullmatch(item["version"]) is not None,
                 "pkg-config module/version differs")
    commands = result["commands"]
    _require(type(commands) is list and len(commands) == 4,
             "build command cardinality differs")
    normalized_commands = [
        _command(item, name) for item, name in zip(
            commands, ("configure", "build", "compile", "link")
        )
    ]
    _require(result["required_compile_hardening_flags"]
             == list(_COMPILE_HARDENING)
             and all(flag in normalized_commands[2]["argv"]
                     for flag in _COMPILE_HARDENING),
             "compile hardening differs")
    _require(result["required_link_hardening_flags"] == list(_LINK_HARDENING)
             and all(flag in normalized_commands[3]["argv"]
                     for flag in _LINK_HARDENING),
             "link hardening differs")
    observation = _mapping(
        result["reproducibility_observation"],
        ("observation_kind", "build_count", "source_executable_sha256",
         "source_executable_size_bytes", "source_executable_build_id_sha1",
         "source_object_sha256", "independently_attested"),
        "reproducibility observation",
    )
    _exact_int(observation["build_count"], 2,
               "reproducibility build count")
    _size(observation["source_executable_size_bytes"],
          "reproducibility source-executable size")
    _require(observation["observation_kind"]
             == "two_clean_builds_byte_identical_candidate"
             and observation["source_executable_sha256"] == pins["executable"]
             and observation["source_executable_size_bytes"] == pins["executable_size"]
             and observation["source_executable_build_id_sha1"] == pins["build_id"]
             and observation["source_object_sha256"] == pins["object"]
             and observation["independently_attested"] is False,
             "reproducibility observation differs from external pins")
    _require(result["toolchain_closure_complete"] is False,
             "toolchain closure must remain incomplete")
    return result


def _invocation_contract(value: Any, expected_sha: str) -> dict[str, Any]:
    result = _self_hashed_document(
        value, kind=INVOCATION_CONTRACT_KIND,
        hash_field="invocation_contract_sha256",
        keys=("schema_version", "artifact_kind", "loader_mode",
              "interpreter_artifact_id", "source_executable_artifact_id",
              "fixed_loader_argv", "argv_fields", "control_lines",
              "status_states", "admission_event_fields", "ack_line",
              "transport_contract_version", "invocation_contract_sha256"),
        label="invocation contract",
    )
    _require(result["invocation_contract_sha256"] == expected_sha,
             "invocation-contract external pin differs")
    _require(result["loader_mode"] == "explicit_staged_interpreter"
             and type(result["interpreter_artifact_id"]) is str
             and type(result["source_executable_artifact_id"]) is str,
             "invocation loader mode differs")
    _require(result["fixed_loader_argv"] == [
        "${INTERPRETER}", "--library-path", "${STAGE_ROOT}/lib",
        "${SOURCE_EXECUTABLE}",
    ], "fixed loader argv differs")
    _require(result["argv_fields"] == [
        {"flag": flag, "value_kind": kind} for flag, kind in _ARGV_FIELDS
    ], "source argv field contract differs")
    _require(result["control_lines"] == [
        {"version": "1", "command": "START", "value_kinds": [
            "future_monotonic_ns", "window_start_ms", "window_end_ms",
            "drain_end_ms",
        ]},
        {"version": "1", "command": "STOP",
         "value_kinds": ["window_end_ms"]},
    ], "lifecycle control-line contract differs")
    _require(result["status_states"] == [
        "READY", "STARTED", "ADMISSION_STOPPED", "DRAINED", "CENSORED",
    ], "status-state contract differs")
    _require(result["admission_event_fields"] == [
        "protocol_version", "source_process_id", "sequence", "run_id",
        "dataset_id", "stream_id", "admission_id", "input_frame_key",
        "source_sha256", "source_cycle", "access_unit_pts_ns",
        "payload_sha256", "payload_size_bytes", "schedule_offset_ns",
        "admission_timestamp_ms", "event_provenance",
    ], "admission-event contract differs")
    _exact_int(result["transport_contract_version"], 1,
               "transport contract version")
    _require(result["ack_line"] == {
        "version": "1", "command": "ACK", "value_kinds": ["sequence"],
    },
             "admission ACK/transport contract differs")
    return result


def _elf_metadata(value: Any, label: str) -> dict[str, Any]:
    source = _mapping(
        value, ("elf_type", "machine", "pt_interp", "build_id_sha1",
                "soname", "needed", "rpath", "runpath"), label,
    )
    _require(source["elf_type"] == "ET_DYN" and source["machine"] == "x86_64",
             f"{label} ELF type/machine differs")
    _require(source["pt_interp"] is None
             or (type(source["pt_interp"]) is str
                 and source["pt_interp"].isascii()
                 and source["pt_interp"].startswith("/")),
             f"{label} PT_INTERP is invalid")
    _build_id(source["build_id_sha1"], f"{label} build ID")
    _require(source["soname"] is None
             or (type(source["soname"]) is str
                 and source["soname"].isascii() and "/" not in source["soname"]),
             f"{label} SONAME is invalid")
    _require(type(source["needed"]) is list
             and all(type(item) is str and item.isascii() and item
                     and "/" not in item for item in source["needed"]),
             f"{label} DT_NEEDED list is invalid")
    _require(source["rpath"] is None and source["runpath"] is None,
             f"{label} RPATH/RUNPATH must be absent")
    return copy.deepcopy(dict(source))


def _runtime_artifacts(value: Any) -> list[dict[str, Any]]:
    _require(type(value) is list and 7 <= len(value) <= MAX_RUNTIME_ARTIFACTS,
             "runtime artifact cardinality is invalid")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        _mapping(item, ("artifact_id", "artifact_class", "descriptor",
                        "content_identity_sha256", "elf"),
                 f"runtime artifact[{index}]")
        reference = _artifact_ref(
            {key: item[key] for key in (
                "artifact_id", "artifact_class", "descriptor",
                "content_identity_sha256",
            )}, f"runtime artifact[{index}]",
        )
        _require(reference["artifact_class"] in _RUNTIME_CLASS_ORDER,
                 "runtime artifact class is unknown")
        if reference["artifact_class"] in {
            "gst_registry_seed", "gst_registry_catalog",
        }:
            _require(item["elf"] is None,
                     "non-ELF runtime artifact has ELF metadata")
            elf = None
        else:
            elf = _elf_metadata(item["elf"], f"runtime artifact[{index}] ELF")
        reference["elf"] = elf
        result.append(reference)
    expected_order = sorted(result, key=lambda item: (
        _RUNTIME_CLASS_ORDER[item["artifact_class"]],
        item["descriptor"]["path"].casefold(), item["descriptor"]["path"],
    ))
    _require(result == expected_order,
             "runtime artifacts are not in exact canonical order")
    counts = {
        name: sum(item["artifact_class"] == name for item in result)
        for name in _RUNTIME_CLASS_ORDER
    }
    for singleton in (
        "source_executable", "elf_interpreter", "gst_plugin_scanner",
        "gst_registry_seed", "gst_registry_catalog",
    ):
        _require(counts[singleton] == 1,
                 f"runtime artifact {singleton} must be a singleton")
    _require(counts["shared_object"] >= 1 and counts["gst_plugin_module"] >= 1,
             "runtime closure requires shared libraries and plugin modules")
    return result


def _loader_graph(value: Any,
                  artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    source = _mapping(
        value, ("loader_mode", "built_pt_interp",
                "elf_interpreter_artifact_id", "root_artifact_ids", "edges"),
        "ELF loader graph",
    )
    by_id = {item["artifact_id"]: item for item in artifacts}
    _require(len(by_id) == len(artifacts), "runtime artifact IDs alias")
    interpreter = next(item for item in artifacts
                       if item["artifact_class"] == "elf_interpreter")
    executable = next(item for item in artifacts
                      if item["artifact_class"] == "source_executable")
    scanner = next(item for item in artifacts
                   if item["artifact_class"] == "gst_plugin_scanner")
    plugins = [item for item in artifacts
               if item["artifact_class"] == "gst_plugin_module"]
    expected_roots = [
        executable["artifact_id"], interpreter["artifact_id"],
        scanner["artifact_id"],
        *(item["artifact_id"] for item in plugins),
    ]
    _require(source["loader_mode"] == "explicit_staged_interpreter"
             and source["elf_interpreter_artifact_id"] == interpreter["artifact_id"]
             and source["root_artifact_ids"] == expected_roots,
             "ELF loader root/interpreter binding differs")
    built_interp = source["built_pt_interp"]
    _require(type(built_interp) is str and built_interp.isascii()
             and built_interp.startswith("/")
             and PurePosixPath(built_interp).name
             == PurePosixPath(interpreter["descriptor"]["path"]).name
             and executable["elf"]["pt_interp"] == built_interp
             and scanner["elf"]["pt_interp"] == built_interp,
             "built PT_INTERP binding differs")
    expected_edges: list[dict[str, Any]] = []
    for item in artifacts:
        if item["elf"] is None:
            continue
        for needed_index, soname in enumerate(item["elf"]["needed"]):
            targets = [candidate for candidate in artifacts
                       if candidate["elf"] is not None
                       and candidate["elf"]["soname"] == soname]
            _require(len(targets) == 1,
                     f"DT_NEEDED {soname} lacks one exact staged target")
            target = targets[0]
            target_path = PurePosixPath(target["descriptor"]["path"])
            _require(
                target["artifact_class"] == "shared_object"
                and target_path.parent.as_posix() == f"{STAGE_PREFIX}lib"
                and target_path.name == soname,
                f"DT_NEEDED {soname} target is not its exact staged lib leaf",
            )
            expected_edges.append({
                "from_artifact_id": item["artifact_id"],
                "needed_index": needed_index, "needed_soname": soname,
                "to_artifact_id": target["artifact_id"],
            })
    _require(source["edges"] == expected_edges,
             "ELF loader edges differ from ordered DT_NEEDED")
    for edge in source["edges"]:
        _require(type(edge["needed_index"]) is int,
                 "ELF loader edge needed index must be an exact integer")
    reachable = set(expected_roots)
    changed = True
    while changed:
        changed = False
        for edge in expected_edges:
            if (edge["from_artifact_id"] in reachable
                    and edge["to_artifact_id"] not in reachable):
                reachable.add(edge["to_artifact_id"])
                changed = True
    shared = {item["artifact_id"] for item in artifacts
              if item["artifact_class"] == "shared_object"}
    _require(shared <= reachable,
             "staged shared-object leaf is unreachable from loader roots")
    return copy.deepcopy(dict(source))


def _registry_catalog(value: Any,
                      artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = _self_hashed_document(
        value, kind=GST_REGISTRY_CATALOG_KIND,
        hash_field="gst_registry_catalog_sha256",
        keys=("schema_version", "artifact_kind", "gstreamer_api_version",
              "gstreamer_version", "registry_seed_artifact_id", "factories",
              "gst_registry_catalog_sha256"),
        label="GStreamer registry catalog",
    )
    _require(result["gstreamer_api_version"] == "1.0"
             and type(result["gstreamer_version"]) is str
             and _VERSION_RE.fullmatch(result["gstreamer_version"]) is not None,
             "GStreamer version differs")
    by_id = {item["artifact_id"]: item for item in artifacts}
    seed = by_id.get(result["registry_seed_artifact_id"])
    _require(seed is not None and seed["artifact_class"] == "gst_registry_seed",
             "registry catalog seed binding differs")
    factories = result["factories"]
    _require(type(factories) is list and len(factories) == len(_FACTORIES),
             "GStreamer factory cardinality differs")
    for item, expected in zip(factories, _FACTORIES):
        _mapping(item, ("factory_name", "feature_kind", "plugin_name",
                        "plugin_version", "plugin_artifact_id"),
                 f"GStreamer factory {expected}")
        plugin = by_id.get(item["plugin_artifact_id"])
        _require(item["factory_name"] == expected
                 and item["feature_kind"] == "element_factory"
                 and type(item["plugin_name"]) is str
                 and _ID_RE.fullmatch(item["plugin_name"]) is not None
                 and type(item["plugin_version"]) is str
                 and _VERSION_RE.fullmatch(item["plugin_version"]) is not None
                 and plugin is not None
                 and plugin["artifact_class"] == "gst_plugin_module",
                 f"GStreamer factory {expected} plugin binding differs")
    return result


def _gstreamer(value: Any,
               artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    source = _mapping(
        value, ("api_version", "scanner_artifact_id",
                "registry_seed_artifact_id", "registry_catalog_artifact_id",
                "registry_catalog_content", "required_factory_bindings"),
        "GStreamer closure",
    )
    by_id = {item["artifact_id"]: item for item in artifacts}
    scanner = by_id.get(source["scanner_artifact_id"])
    seed = by_id.get(source["registry_seed_artifact_id"])
    catalog_artifact = by_id.get(source["registry_catalog_artifact_id"])
    _require(source["api_version"] == "1.0"
             and scanner is not None
             and scanner["artifact_class"] == "gst_plugin_scanner"
             and seed is not None
             and seed["artifact_class"] == "gst_registry_seed"
             and catalog_artifact is not None
             and catalog_artifact["artifact_class"] == "gst_registry_catalog",
             "GStreamer scanner/registry binding differs")
    catalog = _registry_catalog(source["registry_catalog_content"], artifacts)
    bound_plugin_ids = {
        item["plugin_artifact_id"] for item in catalog["factories"]
    }
    declared_plugin_ids = {
        item["artifact_id"] for item in artifacts
        if item["artifact_class"] == "gst_plugin_module"
    }
    _require(catalog["registry_seed_artifact_id"] == seed["artifact_id"]
             and catalog_artifact["content_identity_sha256"]
             == catalog["gst_registry_catalog_sha256"]
             and source["required_factory_bindings"] == catalog["factories"]
             and bound_plugin_ids == declared_plugin_ids,
             "GStreamer catalog/factory cross-binding differs")
    return copy.deepcopy(dict(source))


def _all_references(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    references = [
        {"descriptor": item["descriptor"],
         "content_identity_sha256": item["content_identity_sha256"]}
        for item in manifest["runtime_artifacts"]
    ]
    references.extend((
        manifest["environment_policy"], manifest["build_provenance"],
        manifest["invocation_contract"],
    ))
    references.extend(
        {"descriptor": item["descriptor"],
         "content_identity_sha256": item["content_identity_sha256"]}
        for item in manifest["build_provenance_content"]["source_inputs"]
    )
    references.append({
        "descriptor": manifest["build_provenance_content"]["source_object"][
            "descriptor"
        ],
        "content_identity_sha256": manifest["build_provenance_content"][
            "source_object"
        ]["content_identity_sha256"],
    })
    references.extend(
        {"descriptor": item["descriptor"],
         "content_identity_sha256": item["content_identity_sha256"]}
        for item in manifest["build_provenance_content"]["tool_artifacts"]
    )
    return references


def _global_uniqueness(manifest: Mapping[str, Any]) -> None:
    references = _all_references(manifest)
    paths = [item["descriptor"]["path"] for item in references]
    byte_shas = [item["descriptor"]["sha256"] for item in references]
    _require(len(paths) == len(set(path.casefold() for path in paths)),
             "staged artifact paths alias case-insensitively")
    _require(len(byte_shas) == len(set(byte_shas)),
             "staged artifact byte identities alias")


def _authority_uniqueness(authority: Mapping[str, Any]) -> None:
    manifest = authority["runtime_closure_manifest_content"]
    references = [authority["runtime_closure_manifest"], *_all_references(manifest)]
    paths = [item["descriptor"]["path"].casefold() for item in references]
    byte_shas = [item["descriptor"]["sha256"] for item in references]
    content_shas = [item["content_identity_sha256"] for item in references]
    _require(len(paths) == len(set(paths)),
             "authority staged artifact paths alias")
    _require(len(byte_shas) == len(set(byte_shas)),
             "authority staged artifact byte identities alias")
    _require(len(content_shas) == len(set(content_shas)),
             "authority staged artifact content identities alias")
    reserved = {
        authority["checkpoint_source_runtime_closure_authority_sha256"],
        authority["runtime_closure_set_sha256"],
    }
    _require(not reserved.intersection(content_shas[1:]),
             "authority contains a reserved semantic identity cycle")


def _closure_set_material(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "artifact_kind": CLOSURE_SET_KIND,
        "target": manifest["target"],
        "runtime_artifacts": manifest["runtime_artifacts"],
        "elf_loader_graph": manifest["elf_loader_graph"],
        "gstreamer": manifest["gstreamer"],
        "environment_policy": manifest["environment_policy"],
        "environment_policy_content": manifest["environment_policy_content"],
        "invocation_contract": manifest["invocation_contract"],
        "invocation_contract_content": manifest["invocation_contract_content"],
    }


def validate_checkpoint_source_runtime_closure_manifest_v1(
    value: Any, *, expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_environment_policy_sha256: str,
    expected_build_provenance_sha256: str,
    expected_invocation_contract_sha256: str,
    expected_source_executable_sha256: str,
    expected_source_executable_size_bytes: int,
    expected_source_executable_build_id_sha1: str,
    expected_cmake_file_sha256: str,
    expected_coordinator_source_sha256: str,
    expected_transport_header_sha256: str,
    expected_source_object_sha256: str,
) -> dict[str, Any]:
    """Purely validate a new-generation staged closure manifest."""
    pins = _expected_pins(
        expected_manifest_sha256=expected_manifest_sha256,
        expected_runtime_closure_set_sha256=expected_runtime_closure_set_sha256,
        expected_environment_policy_sha256=expected_environment_policy_sha256,
        expected_build_provenance_sha256=expected_build_provenance_sha256,
        expected_invocation_contract_sha256=expected_invocation_contract_sha256,
        expected_source_executable_sha256=expected_source_executable_sha256,
        expected_source_executable_size_bytes=expected_source_executable_size_bytes,
        expected_source_executable_build_id_sha1=(
            expected_source_executable_build_id_sha1
        ),
        expected_cmake_file_sha256=expected_cmake_file_sha256,
        expected_coordinator_source_sha256=expected_coordinator_source_sha256,
        expected_transport_header_sha256=expected_transport_header_sha256,
        expected_source_object_sha256=expected_source_object_sha256,
    )
    source = _mapping(
        value, ("schema_version", "artifact_kind", "target",
                "runtime_artifacts", "elf_loader_graph", "gstreamer",
                "environment_policy", "environment_policy_content",
                "build_provenance", "build_provenance_content",
                "invocation_contract", "invocation_contract_content",
                "runtime_closure_set_sha256",
                "checkpoint_source_runtime_closure_manifest_sha256"),
        "checkpoint-source runtime closure manifest",
    )
    _exact_int(source["schema_version"], SCHEMA_VERSION,
               "checkpoint-source manifest schema version")
    _require(source["artifact_kind"] == MANIFEST_KIND,
             "checkpoint-source runtime closure manifest kind/version differs")
    _require(source["target"] == {
        "target_name": "vast_checkpoint_source",
        "operating_system": "linux", "architecture": "x86_64",
        "binary_format": "ELF64", "byte_order": "little_endian",
        "abi_family": "gnu", "build_configuration": "Release",
    }, "checkpoint-source target identity differs")
    artifacts = _runtime_artifacts(source["runtime_artifacts"])
    graph = _loader_graph(source["elf_loader_graph"], artifacts)
    gstreamer = _gstreamer(source["gstreamer"], artifacts)
    environment = _environment_policy(
        source["environment_policy_content"], pins["environment"]
    )
    build = _build_provenance(source["build_provenance_content"], pins)
    invocation = _invocation_contract(
        source["invocation_contract_content"], pins["invocation"]
    )
    environment_ref = _document_ref(
        source["environment_policy"], "environment-policy reference"
    )
    build_ref = _document_ref(
        source["build_provenance"], "build-provenance reference"
    )
    invocation_ref = _document_ref(
        source["invocation_contract"], "invocation-contract reference"
    )
    _require(environment_ref["content_identity_sha256"] == pins["environment"]
             and build_ref["content_identity_sha256"] == pins["build"]
             and invocation_ref["content_identity_sha256"] == pins["invocation"],
             "control-document reference identity differs")
    executable = next(item for item in artifacts
                      if item["artifact_class"] == "source_executable")
    interpreter = next(item for item in artifacts
                       if item["artifact_class"] == "elf_interpreter")
    _require(executable["descriptor"]["sha256"] == pins["executable"]
             and executable["descriptor"]["size_bytes"] == pins["executable_size"]
             and executable["elf"]["build_id_sha1"] == pins["build_id"],
             "source-executable observation differs from external pins")
    _require(invocation["source_executable_artifact_id"]
             == executable["artifact_id"]
             and invocation["interpreter_artifact_id"]
             == interpreter["artifact_id"],
             "invocation executable/interpreter binding differs")
    normalized = copy.deepcopy(dict(source))
    normalized.update({
        "runtime_artifacts": artifacts, "elf_loader_graph": graph,
        "gstreamer": gstreamer, "environment_policy": environment_ref,
        "environment_policy_content": environment,
        "build_provenance": build_ref, "build_provenance_content": build,
        "invocation_contract": invocation_ref,
        "invocation_contract_content": invocation,
    })
    set_sha = _sha(
        source["runtime_closure_set_sha256"], "runtime closure-set identity"
    )
    _require(set_sha == pins["set"]
             and set_sha == _canonical_sha(_closure_set_material(normalized)),
             "runtime closure-set identity differs")
    manifest_sha = _sha(
        source["checkpoint_source_runtime_closure_manifest_sha256"],
        "checkpoint-source manifest identity",
    )
    material = copy.deepcopy(normalized)
    material.pop("checkpoint_source_runtime_closure_manifest_sha256")
    _require(manifest_sha == pins["manifest"]
             and manifest_sha == _canonical_sha(material),
             "checkpoint-source manifest identity differs")
    _global_uniqueness(normalized)
    return normalized


def validate_checkpoint_source_runtime_closure_authority_v1(
    value: Any, *, expected_authority_sha256: str,
    expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_environment_policy_sha256: str,
    expected_build_provenance_sha256: str,
    expected_invocation_contract_sha256: str,
    expected_source_executable_sha256: str,
    expected_source_executable_size_bytes: int,
    expected_source_executable_build_id_sha1: str,
    expected_cmake_file_sha256: str,
    expected_coordinator_source_sha256: str,
    expected_transport_header_sha256: str,
    expected_source_object_sha256: str,
) -> dict[str, Any]:
    """Purely validate an authority wrapper; never authorize execution."""
    pin_arguments = {
        "expected_manifest_sha256": expected_manifest_sha256,
        "expected_runtime_closure_set_sha256": expected_runtime_closure_set_sha256,
        "expected_environment_policy_sha256": expected_environment_policy_sha256,
        "expected_build_provenance_sha256": expected_build_provenance_sha256,
        "expected_invocation_contract_sha256": expected_invocation_contract_sha256,
        "expected_source_executable_sha256": expected_source_executable_sha256,
        "expected_source_executable_size_bytes": expected_source_executable_size_bytes,
        "expected_source_executable_build_id_sha1": (
            expected_source_executable_build_id_sha1
        ),
        "expected_cmake_file_sha256": expected_cmake_file_sha256,
        "expected_coordinator_source_sha256": expected_coordinator_source_sha256,
        "expected_transport_header_sha256": expected_transport_header_sha256,
        "expected_source_object_sha256": expected_source_object_sha256,
    }
    pins = _expected_pins(
        expected_authority_sha256=expected_authority_sha256, **pin_arguments
    )
    source = _mapping(
        value, ("schema_version", "artifact_kind", "runtime_closure_manifest",
                "runtime_closure_manifest_content", "runtime_closure_set_sha256",
                "environment_policy_sha256", "build_provenance_sha256",
                "invocation_contract_sha256", "source_executable_sha256",
                "source_executable_size_bytes", "source_executable_build_id_sha1",
                "cmake_file_sha256", "coordinator_source_sha256",
                "transport_header_sha256", "source_object_sha256",
                "checkpoint_source_runtime_closure_authority_sha256"),
        "checkpoint-source runtime closure authority",
    )
    _exact_int(source["schema_version"], SCHEMA_VERSION,
               "checkpoint-source authority schema version")
    _require(source["artifact_kind"] == AUTHORITY_KIND,
             "checkpoint-source authority kind/version differs")
    manifest_ref = _document_ref(
        source["runtime_closure_manifest"], "runtime closure manifest reference"
    )
    manifest = validate_checkpoint_source_runtime_closure_manifest_v1(
        source["runtime_closure_manifest_content"], **pin_arguments
    )
    _size(source["source_executable_size_bytes"],
          "authority source-executable size")
    _require(manifest_ref["content_identity_sha256"] == pins["manifest"]
             and source["runtime_closure_set_sha256"] == pins["set"]
             and source["environment_policy_sha256"] == pins["environment"]
             and source["build_provenance_sha256"] == pins["build"]
             and source["invocation_contract_sha256"] == pins["invocation"]
             and source["source_executable_sha256"] == pins["executable"]
             and source["source_executable_size_bytes"] == pins["executable_size"]
             and source["source_executable_build_id_sha1"] == pins["build_id"],
             "authority external-pin projection differs")
    _require(source["cmake_file_sha256"] == pins["cmake"]
             and source["coordinator_source_sha256"] == pins["coordinator"]
             and source["transport_header_sha256"] == pins["transport"]
             and source["source_object_sha256"] == pins["object"],
             "authority external-pin projection differs")
    normalized = copy.deepcopy(dict(source))
    normalized["runtime_closure_manifest"] = manifest_ref
    normalized["runtime_closure_manifest_content"] = manifest
    supplied = _sha(
        source["checkpoint_source_runtime_closure_authority_sha256"],
        "checkpoint-source authority identity",
    )
    material = copy.deepcopy(normalized)
    material.pop("checkpoint_source_runtime_closure_authority_sha256")
    _require(supplied == pins["authority"]
             and supplied == _canonical_sha(material),
             "checkpoint-source authority identity differs")
    _authority_uniqueness(normalized)
    return normalized


def _root(project_root: Path) -> tuple[Path, tuple[int, int]]:
    _require(isinstance(project_root, Path),
             "project root must be a pathlib.Path")
    supplied = project_root
    root = supplied.resolve(strict=True)
    info = os.lstat(supplied)
    attributes = int(getattr(info, "st_file_attributes", 0))
    _require(supplied == root and stat.S_ISDIR(info.st_mode)
             and not stat.S_ISLNK(info.st_mode) and not (attributes & 0x400),
             "project root is not a stable directory")
    return root, (int(info.st_dev), int(info.st_ino))


def _fingerprint(info: os.stat_result) -> tuple[Any, ...]:
    stable = (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )
    # On Windows, opening a previously untouched file can normalize the
    # creation-time value exposed as st_ctime_ns without changing its bytes or
    # file identity. POSIX ctime remains a useful mutation signal.
    return stable if os.name == "nt" else (*stable, int(info.st_ctime_ns))


def _read_payload(descriptor_fd: int) -> tuple[os.stat_result, bytes]:
    opened = os.fstat(descriptor_fd)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor_fd, 1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        _require(total <= MAX_ARTIFACT_BYTES,
                 "physical artifact exceeds size limit")
        chunks.append(chunk)
    after = os.fstat(descriptor_fd)
    _require(_fingerprint(after) == _fingerprint(opened),
             "physical artifact changed while reading")
    return opened, b"".join(chunks)


def _posix_open_beneath(parent_fd: int, name: str, flags: int) -> int:
    _require(os.name == "posix" and sys.platform.startswith("linux"),
             "Linux openat2 traversal is unavailable")
    _require(type(parent_fd) is int and parent_fd >= 0
             and type(flags) is int and flags >= 0,
             "openat2 descriptor/flags are invalid")
    _require(type(name) is str and name.isascii()
             and name not in ("", ".", "..")
             and "/" not in name and "\\" not in name
             and not any(ord(char) < 0x20 for char in name)
             and len(name.encode("utf-16-le"))
             <= MAX_STAGE_COMPONENT_UTF16_BYTES,
             "openat2 path component is invalid")
    encoded = os.fsencode(name)
    how = _PosixOpenHow(
        flags=flags,
        mode=0,
        resolve=(
            _POSIX_RESOLVE_BENEATH | _POSIX_RESOLVE_NO_XDEV
            | _POSIX_RESOLVE_NO_MAGICLINKS | _POSIX_RESOLVE_NO_SYMLINKS
        ),
    )
    ctypes.set_errno(0)
    descriptor = int(_POSIX_SYSCALL(
        ctypes.c_long(_POSIX_SYS_OPENAT2), ctypes.c_int(parent_fd),
        ctypes.c_char_p(encoded), ctypes.byref(how),
        ctypes.c_size_t(ctypes.sizeof(how)),
    ))
    if descriptor < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), name)
    return descriptor


def _physical_read_posix(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[int, int], bytes]:
    _require(os.name == "posix" and sys.platform.startswith("linux")
             and all(hasattr(os, name) for name in (
                 "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK",
             )), "secure Linux openat2 traversal is unavailable")
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
                 "project root changed before reading")
        seen = {root_identity}
        components: list[tuple[str, tuple[int, int]]] = []
        parent_fd = root_fd
        for part in relative.parts[:-1]:
            child_fd = _posix_open_beneath(parent_fd, part, directory_flags)
            held.append(child_fd)
            child_info = os.fstat(child_fd)
            identity = (int(child_info.st_dev), int(child_info.st_ino))
            _require(stat.S_ISDIR(child_info.st_mode)
                     and identity[0] == root_identity[0]
                     and identity not in seen,
                     "physical artifact parent identity/volume drifted")
            seen.add(identity)
            components.append((part, identity))
            parent_fd = child_fd
        flags = (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                 | int(getattr(os, "O_CLOEXEC", 0)))
        descriptor_fd = _posix_open_beneath(
            parent_fd, relative.parts[-1], flags,
        )
        opened = os.fstat(descriptor_fd)
        identity = (int(opened.st_dev), int(opened.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and int(opened.st_nlink) == 1
                 and identity[0] == root_identity[0] and identity not in seen,
                 "physical artifact is not a unique staged regular file")
        status_flags = int(fcntl.fcntl(descriptor_fd, fcntl.F_GETFL))
        fcntl.fcntl(
            descriptor_fd, fcntl.F_SETFL, status_flags & ~os.O_NONBLOCK,
        )
        read_opened, payload = _read_payload(descriptor_fd)
        _require(_fingerprint(read_opened) == _fingerprint(opened),
                 "physical artifact changed before reading")

        verify_parent = os.open(root, directory_flags)
        verification.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        _require((int(verify_root.st_dev), int(verify_root.st_ino))
                 == root_identity, "project root changed while reading")
        for part, expected_identity in components:
            child_fd = _posix_open_beneath(
                verify_parent, part, directory_flags,
            )
            verification.append(child_fd)
            child_info = os.fstat(child_fd)
            _require(stat.S_ISDIR(child_info.st_mode)
                     and (int(child_info.st_dev), int(child_info.st_ino))
                     == expected_identity,
                     "physical artifact parent changed while reading")
            verify_parent = child_fd
        verify_fd = _posix_open_beneath(
            verify_parent, relative.parts[-1], flags,
        )
        verification.append(verify_fd)
        verify_info = os.fstat(verify_fd)
        _require(stat.S_ISREG(verify_info.st_mode)
                 and int(verify_info.st_nlink) == 1
                 and (int(verify_info.st_dev), int(verify_info.st_ino)) == identity
                 and _fingerprint(verify_info) == _fingerprint(opened),
                 "physical artifact path changed while reading")
        return ({
            "path": relative.as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }, identity, payload)
    except CheckpointSourceRuntimeClosureAuthorityV1Error:
        raise
    except OSError as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            f"physical artifact secure POSIX read failed: {error}"
        ) from error
    finally:
        primary = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = error
        for handle in reversed(verification + held):
            try:
                os.close(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary:
            raise CheckpointSourceRuntimeClosureAuthorityV1Error(
                f"physical artifact descriptor cleanup failed: {close_error}"
            ) from close_error


def _win_open_handle(
    path: Path, *, directory: bool, read_data: bool = False,
) -> int:
    if os.name != "nt":
        raise OSError("Windows native handle traversal is unavailable")
    access = ((_WIN_LIST_DIRECTORY | _WIN_READ_ATTRIBUTES)
              if directory else (_WIN_GENERIC_READ | _WIN_READ_ATTRIBUTES))
    if read_data:
        access |= _WIN_GENERIC_READ
    flags = _WIN_OPEN_REPARSE_POINT | (
        _WIN_BACKUP_SEMANTICS if directory else 0
    )
    ctypes.set_last_error(0)
    handle = _WIN_CREATE_FILE(
        str(path), access, _WIN_SHARE_READ, None,
        _WIN_OPEN_EXISTING, flags, None,
    )
    numeric = int(handle or 0)
    if not numeric or numeric == _WIN_INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return numeric


def _win_open_relative_handle(
    parent_handle: int, name: str, *, directory: bool,
    read_data: bool = False,
) -> int:
    if os.name != "nt":
        raise OSError("Windows relative handle traversal is unavailable")
    _require(type(name) is str and name.isascii()
             and "/" not in name and "\\" not in name
             and name not in ("", ".", "..")
             and not any(ord(char) < 0x20 for char in name),
             "Windows relative path component is invalid")
    encoded_bytes = len(name.encode("utf-16-le"))
    _require(encoded_bytes <= MAX_STAGE_COMPONENT_UTF16_BYTES
             and encoded_bytes <= 65532,
             "Windows relative path component exceeds UNICODE_STRING bounds")
    buffer = ctypes.create_unicode_buffer(name)
    unicode = _NtUnicodeString(
        encoded_bytes, encoded_bytes + 2,
        ctypes.cast(buffer, wintypes.LPWSTR),
    )
    attributes = _NtObjectAttributes(
        ctypes.sizeof(_NtObjectAttributes), wintypes.HANDLE(parent_handle),
        ctypes.pointer(unicode), _NT_OBJ_CASE_INSENSITIVE, None, None,
    )
    status_block = _NtIoStatusBlock()
    result = wintypes.HANDLE()
    access = (_WIN_SYNCHRONIZE | _WIN_READ_ATTRIBUTES
              | (_WIN_LIST_DIRECTORY if directory else _WIN_GENERIC_READ))
    if read_data:
        access |= _WIN_GENERIC_READ
    options = (_NT_SYNCHRONOUS_IO_NONALERT | _NT_OPEN_REPARSE_POINT
               | (_NT_DIRECTORY_FILE if directory else _NT_NON_DIRECTORY_FILE))
    status = int(_WIN_NT_CREATE_FILE(
        ctypes.byref(result), access, ctypes.byref(attributes),
        ctypes.byref(status_block), None, 0, _WIN_SHARE_READ,
        _NT_FILE_OPEN, options, None, 0,
    ))
    numeric = int(result.value or 0)
    if status < 0 or not numeric or numeric == _WIN_INVALID_HANDLE:
        if numeric and numeric != _WIN_INVALID_HANDLE:
            _WIN_CLOSE_HANDLE(result)
        raise OSError(f"NtCreateFile relative open failed with NTSTATUS 0x{status & 0xffffffff:08x}")
    return numeric


def _win_close_handle(handle: int) -> None:
    ctypes.set_last_error(0)
    if not _WIN_CLOSE_HANDLE(wintypes.HANDLE(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def _win_query_handle(handle: int) -> dict[str, Any]:
    native = wintypes.HANDLE(handle)
    ctypes.set_last_error(0)
    if _WIN_GET_FILE_TYPE(native) != _WIN_FILE_TYPE_DISK:
        raise OSError("physical artifact handle is not a disk file")
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


def _win_fingerprint(info: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(info[key] for key in (
        "volume_serial", "file_id", "file_attributes", "reparse_tag",
        "size", "nlink", "delete_pending", "is_directory",
    ))


def _win_validate(info: Mapping[str, Any], *, directory: bool,
                  volume: int) -> None:
    _require(bool(info["is_directory"]) == directory
             and not bool(info["delete_pending"]),
             "physical artifact handle kind/delete state drifted")
    _require(not int(info["file_attributes"]) & _WIN_ATTRIBUTE_REPARSE,
             "physical artifact path contains a link/reparse point")
    _require(int(info["volume_serial"]) == volume,
             "physical artifact volume drifted")
    if not directory:
        _require(int(info["nlink"]) == 1,
                 "physical artifact has multiple hard links")


def _physical_read_windows(
    root: Path, relative: PurePosixPath, root_identity: tuple[int, int],
) -> tuple[dict[str, Any], tuple[int, bytes], bytes]:
    held: list[tuple[int, bool, tuple[Any, ...], str]] = []
    owned_handles: list[int] = []
    descriptor_fd: int | None = None
    final_handle: int | None = None
    try:
        root_handle = _win_open_handle(root, directory=True)
        owned_handles.append(root_handle)
        root_info = _win_query_handle(root_handle)
        volume = int(root_info["volume_serial"])
        _win_validate(root_info, directory=True, volume=volume)
        _require((volume, int.from_bytes(root_info["file_id"], "little"))
                 == root_identity,
                 "project root changed before secure physical read")
        held.append((root_handle, True, _win_fingerprint(root_info), "root"))
        seen = {_win_identity(root_info)}
        parent_handle = root_handle
        for index, part in enumerate(relative.parts[:-1]):
            child_handle = _win_open_relative_handle(
                parent_handle, part, directory=True,
            )
            owned_handles.append(child_handle)
            child_info = _win_query_handle(child_handle)
            _win_validate(child_info, directory=True, volume=volume)
            identity = _win_identity(child_info)
            _require(identity not in seen,
                     "physical artifact path aliases an ancestor")
            seen.add(identity)
            held.append((child_handle, True, _win_fingerprint(child_info),
                         f"parent[{index}]"))
            parent_handle = child_handle
        final_handle = _win_open_relative_handle(
            parent_handle, relative.parts[-1], directory=False, read_data=True,
        )
        final_info = _win_query_handle(final_handle)
        _win_validate(final_info, directory=False, volume=volume)
        final_identity = _win_identity(final_info)
        _require(final_identity not in seen,
                 "physical artifact aliases an ancestor")
        final_fingerprint = _win_fingerprint(final_info)
        descriptor_fd = msvcrt.open_osfhandle(
            final_handle, os.O_RDONLY | int(getattr(os, "O_BINARY", 0)),
        )
        final_handle = None
        opened, payload = _read_payload(descriptor_fd)
        _require(int(opened.st_dev) == final_identity[0]
                 and int(opened.st_ino)
                 == int.from_bytes(final_identity[1], "little")
                 and stat.S_ISREG(opened.st_mode),
                 "native/CRT physical handle identity drifted")
        current = _win_query_handle(int(msvcrt.get_osfhandle(descriptor_fd)))
        _win_validate(current, directory=False, volume=volume)
        _require(_win_fingerprint(current) == final_fingerprint,
                 "held physical artifact changed while reading")
        for handle, directory, expected, label in held:
            observed = _win_query_handle(handle)
            _win_validate(observed, directory=directory, volume=volume)
            _require(_win_fingerprint(observed) == expected,
                     f"held physical {label} changed while reading")

        verify_root = _win_open_handle(root, directory=True)
        verify_owned = [verify_root]
        try:
            verify_info = _win_query_handle(verify_root)
            _win_validate(verify_info, directory=True, volume=volume)
            _require(_win_identity(verify_info) == _win_identity(root_info),
                     "project root path changed while reading")
            verify_parent = verify_root
            for index, part in enumerate(relative.parts[:-1]):
                child = _win_open_relative_handle(
                    verify_parent, part, directory=True,
                )
                verify_owned.append(child)
                child_info = _win_query_handle(child)
                _win_validate(child_info, directory=True, volume=volume)
                _require(_win_fingerprint(child_info) == held[index + 1][2],
                         "physical artifact parent path changed while reading")
                verify_parent = child
            verify_final = _win_open_relative_handle(
                verify_parent, relative.parts[-1], directory=False,
                read_data=False,
            )
            verify_owned.append(verify_final)
            verify_final_info = _win_query_handle(verify_final)
            _win_validate(verify_final_info, directory=False, volume=volume)
            _require(_win_fingerprint(verify_final_info) == final_fingerprint,
                     "physical artifact final path changed while reading")
        finally:
            verification_primary = sys.exc_info()[0] is not None
            verification_close_error: OSError | None = None
            for handle in reversed(verify_owned):
                try:
                    _win_close_handle(handle)
                except OSError as error:
                    verification_close_error = verification_close_error or error
            if (verification_close_error is not None
                    and not verification_primary):
                raise CheckpointSourceRuntimeClosureAuthorityV1Error(
                    "Windows verification handle cleanup failed: "
                    f"{verification_close_error}"
                ) from verification_close_error
        return ({
            "path": relative.as_posix(), "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }, final_identity, payload)
    except CheckpointSourceRuntimeClosureAuthorityV1Error:
        raise
    except (OSError, ValueError, KeyError) as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            f"physical artifact secure Windows read failed: {error}"
        ) from error
    finally:
        primary = sys.exc_info()[0] is not None
        close_error: OSError | None = None
        if descriptor_fd is not None:
            try:
                os.close(descriptor_fd)
            except OSError as error:
                close_error = error
        elif final_handle is not None:
            try:
                _win_close_handle(final_handle)
            except OSError as error:
                close_error = error
        for handle in reversed(owned_handles):
            try:
                _win_close_handle(handle)
            except OSError as error:
                close_error = close_error or error
        if close_error is not None and not primary:
            raise CheckpointSourceRuntimeClosureAuthorityV1Error(
                f"Windows native handle cleanup failed: {close_error}"
            ) from close_error


def _physical_read(
    root: Path, root_identity: tuple[int, int], relative: str,
) -> tuple[dict[str, Any], tuple[Any, ...], bytes]:
    safe = PurePosixPath(_relative_path(relative, "physical artifact path"))
    return (_physical_read_windows(root, safe, root_identity)
            if os.name == "nt" else
            _physical_read_posix(root, safe, root_identity))


def _canonical_document(payload: bytes, label: str) -> dict[str, Any]:
    _require(payload.endswith(b"\n") and not payload.endswith(b"\n\n"),
             f"{label} must have exactly one trailing LF")
    try:
        value = json.loads(payload[:-1].decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            f"{label} is not strict ASCII JSON"
        ) from error
    _require(_canonical_bytes(value) == payload[:-1],
             f"{label} is not canonical JSON")
    return value


def _c_string(data: bytes, offset: int, limit: int, label: str) -> str:
    _require(0 <= offset < limit <= len(data),
             f"{label} string offset is invalid")
    end = data.find(b"\0", offset, limit)
    _require(end >= 0, f"{label} string is unterminated")
    try:
        value = data[offset:end].decode("ascii")
    except UnicodeError as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            f"{label} string is not ASCII"
        ) from error
    _require(value != "", f"{label} string is empty")
    return value


def _parse_elf64_le(data: bytes, label: str) -> dict[str, Any]:
    _require(len(data) >= 64 and data[:4] == b"\x7fELF"
             and data[4] == 2 and data[5] == 1 and data[6] == 1,
             f"{label} is not ELF64 little-endian")
    try:
        (_, elf_type, machine, version, _entry, phoff, _shoff, _flags,
         ehsize, phentsize, phnum, _shentsize, _shnum, _shstrndx) = (
            struct.unpack_from("<16sHHIQQQIHHHHHH", data, 0)
        )
    except struct.error as error:
        raise CheckpointSourceRuntimeClosureAuthorityV1Error(
            f"{label} ELF header is truncated"
        ) from error
    _require(elf_type == 3 and machine == 62 and version == 1
             and ehsize == 64 and phentsize == 56 and 0 < phnum <= 4096
             and phoff + phnum * phentsize <= len(data),
             f"{label} ELF header differs from Linux x86_64 PIE/DSO")
    segments: list[tuple[int, int, int, int, int]] = []
    for index in range(phnum):
        try:
            (p_type, _p_flags, p_offset, p_vaddr, _p_paddr,
             p_filesz, p_memsz, _align) = struct.unpack_from(
                "<IIQQQQQQ", data, phoff + index * phentsize
            )
        except struct.error as error:
            raise CheckpointSourceRuntimeClosureAuthorityV1Error(
                f"{label} program header is truncated"
            ) from error
        _require(p_offset + p_filesz <= len(data) and p_filesz <= p_memsz,
                 f"{label} program segment exceeds file")
        segments.append((p_type, p_offset, p_vaddr, p_filesz, p_memsz))
    interp_values: list[str] = []
    dynamic: list[tuple[int, int]] = []
    build_ids: list[str] = []
    loads = [item for item in segments if item[0] == 1]
    dynamic_segments = [item for item in segments if item[0] == 2]
    _require(len(dynamic_segments) == 1,
             f"{label} PT_DYNAMIC cardinality differs")
    for p_type, offset, _vaddr, filesz, _memsz in segments:
        if p_type == 3:
            raw = data[offset:offset + filesz]
            _require(raw.endswith(b"\0") and raw.count(b"\0") == 1,
                     f"{label} PT_INTERP is malformed")
            try:
                interp_values.append(raw[:-1].decode("ascii"))
            except UnicodeError as error:
                raise CheckpointSourceRuntimeClosureAuthorityV1Error(
                    f"{label} PT_INTERP is not ASCII"
                ) from error
        elif p_type == 2:
            _require(filesz % 16 == 0, f"{label} PT_DYNAMIC is malformed")
            entries = [struct.unpack_from("<QQ", data, cursor)
                       for cursor in range(offset, offset + filesz, 16)]
            _require(entries and entries[-1][0] == 0
                     and sum(tag == 0 for tag, _entry in entries) == 1,
                     f"{label} PT_DYNAMIC must end in exactly one DT_NULL")
            dynamic.extend(entries)
        elif p_type == 4:
            cursor = offset
            limit = offset + filesz
            while cursor + 12 <= limit:
                namesz, descsz, note_type = struct.unpack_from(
                    "<III", data, cursor
                )
                cursor += 12
                name = data[cursor:cursor + namesz]
                cursor += (namesz + 3) & ~3
                desc = data[cursor:cursor + descsz]
                cursor += (descsz + 3) & ~3
                _require(cursor <= limit, f"{label} PT_NOTE is malformed")
                if (note_type == 3 and name.rstrip(b"\0") == b"GNU"
                        and descsz == 20):
                    build_ids.append(desc.hex())
    _require(len(interp_values) <= 1 and len(build_ids) == 1,
             f"{label} interpreter/build-ID cardinality differs")
    strtab_values = [entry for tag, entry in dynamic if tag == 5]
    strsz_values = [entry for tag, entry in dynamic if tag == 10]
    _require(len(strtab_values) == 1 and len(strsz_values) == 1
             and strsz_values[0] > 0,
             f"{label} dynamic string table is missing")
    strtab_address, string_size = strtab_values[0], strsz_values[0]
    matches = [offset + (strtab_address - virtual)
               for _ptype, offset, virtual, filesz, _memsz in loads
               if virtual <= strtab_address
               and strtab_address + string_size <= virtual + filesz]
    _require(len(matches) == 1,
             f"{label} dynamic string table is not file-backed once")
    base = matches[0]
    needed = [_c_string(data, base + entry, base + string_size,
                        f"{label} DT_NEEDED")
              for tag, entry in dynamic if tag == 1]

    def singleton_string(tag: int, name: str) -> str | None:
        offsets = [entry for candidate, entry in dynamic if candidate == tag]
        _require(len(offsets) <= 1, f"{label} {name} repeats")
        return (_c_string(data, base + offsets[0], base + string_size,
                          f"{label} {name}") if offsets else None)

    return {
        "elf_type": "ET_DYN", "machine": "x86_64",
        "pt_interp": interp_values[0] if interp_values else None,
        "build_id_sha1": build_ids[0],
        "soname": singleton_string(14, "SONAME"), "needed": needed,
        "rpath": singleton_string(15, "RPATH"),
        "runpath": singleton_string(29, "RUNPATH"),
    }


def _physical_validate(
    root: Path, root_identity: tuple[int, int], manifest_path: str,
    authority: Mapping[str, Any],
) -> int:
    manifest = authority["runtime_closure_manifest_content"]
    references = [{
        "descriptor": authority["runtime_closure_manifest"]["descriptor"],
        "content_identity_sha256": authority[
            "runtime_closure_manifest"
        ]["content_identity_sha256"],
    }, *_all_references(manifest)]
    identities: set[tuple[int, int]] = set()
    payloads: dict[str, bytes] = {}
    total = 0
    for reference in references:
        expected = reference["descriptor"]
        observed, identity, payload = _physical_read(
            root, root_identity, expected["path"]
        )
        _require(observed == expected,
                 "staged artifact bytes differ from manifest")
        _require(identity not in identities,
                 "staged artifacts alias physically")
        identities.add(identity)
        total += len(payload)
        _require(total <= MAX_TOTAL_BYTES,
                 "staged closure exceeds total size limit")
        payloads[expected["path"]] = payload
    manifest_value = _canonical_document(
        payloads[manifest_path], "runtime closure manifest"
    )
    _require(manifest_value == manifest,
             "physical manifest bytes differ from authority content")
    for reference, content, label in (
        (manifest["environment_policy"],
         manifest["environment_policy_content"], "environment policy"),
        (manifest["build_provenance"],
         manifest["build_provenance_content"], "build provenance"),
        (manifest["invocation_contract"],
         manifest["invocation_contract_content"], "invocation contract"),
    ):
        path = reference["descriptor"]["path"]
        _require(_canonical_document(payloads[path], label) == content,
                 f"physical {label} bytes differ from embedded content")
    catalog_artifact = next(
        item for item in manifest["runtime_artifacts"]
        if item["artifact_class"] == "gst_registry_catalog"
    )
    catalog_path = catalog_artifact["descriptor"]["path"]
    _require(_canonical_document(
        payloads[catalog_path], "GStreamer registry catalog"
    ) == manifest["gstreamer"]["registry_catalog_content"],
             "physical GStreamer registry catalog differs")
    for item in manifest["runtime_artifacts"]:
        if item["elf"] is not None:
            parsed = _parse_elf64_le(
                payloads[item["descriptor"]["path"]], item["artifact_id"]
            )
            _require(parsed == item["elf"],
                     f"physical ELF metadata differs for {item['artifact_id']}")
    return len(references)


def _assessment(
    *, pins: Mapping[str, Any], status: str, checked: int,
    blockers: Sequence[str], semantic: bool, physical: bool,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": ASSESSMENT_KIND,
        "status": status,
        "checkpoint_source_runtime_closure_authority_sha256": pins.get(
            "authority", ""
        ),
        "checked_artifact_count": checked,
        "blockers": sorted(set(blockers)),
        "authority_pin_validated": semantic,
        "manifest_and_external_pins_validated": semantic,
        "staged_artifact_bytes_reconstructed": physical,
        "individual_artifact_reads_handle_bound": physical,
        "all_artifact_physical_identities_distinct": physical,
        "elf_metadata_physically_reconstructed": physical,
        "ordered_dt_needed_graph_reconstructed": physical,
        "declared_gstreamer_factory_coverage_validated": semantic,
        "environment_build_invocation_bytes_crossbound": physical,
    }
    value.update({claim: False for claim in _FALSE_CLAIMS})
    return value


def assess_checkpoint_source_runtime_closure_authority_v1(
    value: Any, *, project_root: Path, expected_authority_sha256: str,
    expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_environment_policy_sha256: str,
    expected_build_provenance_sha256: str,
    expected_invocation_contract_sha256: str,
    expected_source_executable_sha256: str,
    expected_source_executable_size_bytes: int,
    expected_source_executable_build_id_sha1: str,
    expected_cmake_file_sha256: str,
    expected_coordinator_source_sha256: str,
    expected_transport_header_sha256: str,
    expected_source_object_sha256: str,
) -> dict[str, Any]:
    """Reconstruct listed staged bytes without discovery, loading or execution."""
    pin_arguments = {
        "expected_authority_sha256": expected_authority_sha256,
        "expected_manifest_sha256": expected_manifest_sha256,
        "expected_runtime_closure_set_sha256": expected_runtime_closure_set_sha256,
        "expected_environment_policy_sha256": expected_environment_policy_sha256,
        "expected_build_provenance_sha256": expected_build_provenance_sha256,
        "expected_invocation_contract_sha256": expected_invocation_contract_sha256,
        "expected_source_executable_sha256": expected_source_executable_sha256,
        "expected_source_executable_size_bytes": expected_source_executable_size_bytes,
        "expected_source_executable_build_id_sha1": (
            expected_source_executable_build_id_sha1
        ),
        "expected_cmake_file_sha256": expected_cmake_file_sha256,
        "expected_coordinator_source_sha256": expected_coordinator_source_sha256,
        "expected_transport_header_sha256": expected_transport_header_sha256,
        "expected_source_object_sha256": expected_source_object_sha256,
    }
    pins = _expected_pins(**pin_arguments)
    semantic = False
    checked = 0
    blockers: list[str] = []
    try:
        authority = validate_checkpoint_source_runtime_closure_authority_v1(
            value, **pin_arguments
        )
        semantic = True
        root, root_identity = _root(project_root)
        path = authority["runtime_closure_manifest"]["descriptor"]["path"]
        checked = _physical_validate(root, root_identity, path, authority)
        return _assessment(
            pins=pins, status="physically_valid_candidate", checked=checked,
            blockers=(), semantic=True, physical=True,
        )
    except (CheckpointSourceRuntimeClosureAuthorityV1Error, OSError,
            TypeError, ValueError, struct.error) as error:
        blockers.append(str(error) or type(error).__name__)
    return _assessment(
        pins=pins, status="blocked", checked=checked, blockers=blockers,
        semantic=semantic, physical=False,
    )


def build_checkpoint_source_runtime_closure_authority_v1(
    *, project_root: Path, runtime_closure_manifest_path: str,
    expected_authority_sha256: str, expected_manifest_sha256: str,
    expected_runtime_closure_set_sha256: str,
    expected_environment_policy_sha256: str,
    expected_build_provenance_sha256: str,
    expected_invocation_contract_sha256: str,
    expected_source_executable_sha256: str,
    expected_source_executable_size_bytes: int,
    expected_source_executable_build_id_sha1: str,
    expected_cmake_file_sha256: str,
    expected_coordinator_source_sha256: str,
    expected_transport_header_sha256: str,
    expected_source_object_sha256: str,
) -> dict[str, Any]:
    """Build only from an already staged, externally pinned manifest."""
    pin_arguments = {
        "expected_authority_sha256": expected_authority_sha256,
        "expected_manifest_sha256": expected_manifest_sha256,
        "expected_runtime_closure_set_sha256": expected_runtime_closure_set_sha256,
        "expected_environment_policy_sha256": expected_environment_policy_sha256,
        "expected_build_provenance_sha256": expected_build_provenance_sha256,
        "expected_invocation_contract_sha256": expected_invocation_contract_sha256,
        "expected_source_executable_sha256": expected_source_executable_sha256,
        "expected_source_executable_size_bytes": expected_source_executable_size_bytes,
        "expected_source_executable_build_id_sha1": (
            expected_source_executable_build_id_sha1
        ),
        "expected_cmake_file_sha256": expected_cmake_file_sha256,
        "expected_coordinator_source_sha256": expected_coordinator_source_sha256,
        "expected_transport_header_sha256": expected_transport_header_sha256,
        "expected_source_object_sha256": expected_source_object_sha256,
    }
    pins = _expected_pins(**pin_arguments)
    root, root_identity = _root(project_root)
    manifest_path = _relative_path(
        runtime_closure_manifest_path, "runtime closure manifest path"
    )
    descriptor, _identity, payload = _physical_read(
        root, root_identity, manifest_path
    )
    manifest_value = _canonical_document(payload, "runtime closure manifest")
    manifest = validate_checkpoint_source_runtime_closure_manifest_v1(
        manifest_value,
        **{key: value for key, value in pin_arguments.items()
           if key != "expected_authority_sha256"},
    )
    authority: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "artifact_kind": AUTHORITY_KIND,
        "runtime_closure_manifest": {
            "descriptor": descriptor,
            "content_identity_sha256": pins["manifest"],
        },
        "runtime_closure_manifest_content": manifest,
        "runtime_closure_set_sha256": pins["set"],
        "environment_policy_sha256": pins["environment"],
        "build_provenance_sha256": pins["build"],
        "invocation_contract_sha256": pins["invocation"],
        "source_executable_sha256": pins["executable"],
        "source_executable_size_bytes": pins["executable_size"],
        "source_executable_build_id_sha1": pins["build_id"],
        "cmake_file_sha256": pins["cmake"],
        "coordinator_source_sha256": pins["coordinator"],
        "transport_header_sha256": pins["transport"],
        "source_object_sha256": pins["object"],
    }
    authority["checkpoint_source_runtime_closure_authority_sha256"] = (
        _canonical_sha(authority)
    )
    normalized = validate_checkpoint_source_runtime_closure_authority_v1(
        authority, **pin_arguments
    )
    assessment = assess_checkpoint_source_runtime_closure_authority_v1(
        normalized, project_root=root, **pin_arguments
    )
    _require(assessment["status"] == "physically_valid_candidate",
             "checkpoint-source authority physical assessment is blocked")
    return normalized


__all__ = [
    "ASSESSMENT_KIND", "AUTHORITY_KIND", "BUILD_PROVENANCE_KIND",
    "CLOSURE_SET_KIND", "ENVIRONMENT_POLICY_KIND",
    "GST_REGISTRY_CATALOG_KIND", "INVOCATION_CONTRACT_KIND",
    "MANIFEST_KIND", "SCHEMA_VERSION", "STAGE_PREFIX",
    "CheckpointSourceRuntimeClosureAuthorityV1Error",
    "assess_checkpoint_source_runtime_closure_authority_v1",
    "build_checkpoint_source_runtime_closure_authority_v1",
    "validate_checkpoint_source_runtime_closure_authority_v1",
    "validate_checkpoint_source_runtime_closure_manifest_v1",
]
