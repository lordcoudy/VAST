#!/usr/bin/env python3
"""Immutable leaf authority for backend publication runtime prerequisites.

This module validates and physically assesses inputs only.  It never starts a
backend, accepts benchmark evidence, writes a receipt, or changes readiness.
"""
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


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_backend_publication_runtime_authority"
ASSESSMENT_KIND = "vast_backend_publication_runtime_authority_assessment"
MAX_PHYSICAL_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
CODECS = ("h264", "h265")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
SOURCE_ROLES = frozenset({"source_binary", "source_protocol", "source_plan"})
BACKEND_ROLES = frozenset({
    "runtime_binary", "backend_plugin", "plugin_registry", "plugin_scanner",
    "runtime_module", "publication_launcher",
})
TOP_FIELDS = frozenset({
    "schema_version", "artifact_kind", "coordinate", "dataset",
    "source_runtime_artifacts", "backend_runtime_artifacts",
    "analytics_authority", "model_parity_acceptance_binding_sha256",
    "policy_authority", "cohort_topology_plan", "resource_contract",
    "system_specific_launcher_input", "authority_sha256",
})
COORDINATE_FIELDS = frozenset({"system", "policy", "topology_kind", "codec"})
DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
ARTIFACT_FIELDS = frozenset({"role", "descriptor", "content_identity_sha256"})
DATASET_FIELDS = frozenset({"manifest", "files", "content_identity_sha256"})
ANALYTICS_FIELDS = frozenset({
    "endpoint_authority", "capability", "bindings",
    "preprocessing_contract_sha256",
})
ENDPOINT_FIELDS = frozenset({
    "transport", "path_derivation_contract_sha256",
    "peer_capability_identity_sha256", "peer_binding_identity_sha256",
    "bind_before_backend_launch", "peer_credentials_required",
})
POLICY_FIELDS = frozenset({"capability", "calibration", "static_map"})
CONTENT_FIELDS = frozenset({"content", "content_identity_sha256"})
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_WINDOWS_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})

if os.name == "nt":
    _WIN_GENERIC_READ = 0x80000000
    _WIN_FILE_LIST_DIRECTORY = 0x0001
    _WIN_FILE_READ_ATTRIBUTES = 0x0080
    _WIN_FILE_SHARE_READ = 0x00000001
    _WIN_FILE_SHARE_WRITE = 0x00000002
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


class BackendPublicationRuntimeAuthorityError(RuntimeError):
    """Runtime authority material or its physical inputs are unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BackendPublicationRuntimeAuthorityError(
            "runtime authority material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BackendPublicationRuntimeAuthorityError(message)


def _descriptor(value: Any, *, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == DESCRIPTOR_FIELDS,
             f"{label} descriptor fields drifted")
    path = value.get("path")
    posix_relative = PurePosixPath(str(path))
    windows_relative = PureWindowsPath(str(path))
    parts = posix_relative.parts
    _require(
        type(path) is str and bool(path)
        and "\\" not in path and ":" not in path and "\x00" not in path
        and not posix_relative.is_absolute() and posix_relative.anchor == ""
        and windows_relative.drive == "" and windows_relative.root == ""
        and windows_relative.anchor == ""
        and posix_relative.as_posix() == path and bool(parts)
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((" ", "."))
            and not any(ord(character) < 32 for character in part)
            and part.split(".", 1)[0].upper() not in _WINDOWS_RESERVED_NAMES
            for part in parts
        ),
        f"{label} descriptor path is unsafe",
    )
    _require(type(value.get("size_bytes")) is int and value["size_bytes"] > 0,
             f"{label} descriptor size is invalid")
    _require(_valid_sha(value.get("sha256")),
             f"{label} descriptor SHA-256 is invalid")
    return copy.deepcopy(value)


def _artifact(value: Any, *, label: str, roles: frozenset[str]) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == ARTIFACT_FIELDS,
             f"{label} artifact fields drifted")
    _require(value.get("role") in roles, f"{label} artifact role is invalid")
    descriptor = _descriptor(value.get("descriptor"), label=label)
    _require(
        value.get("content_identity_sha256") == descriptor["sha256"],
        f"{label} content identity does not match physical SHA-256",
    )
    return copy.deepcopy(value)


def _artifact_list(
    value: Any, *, label: str, roles: frozenset[str], nonempty: bool = True,
) -> list[dict[str, Any]]:
    _require(type(value) is list and (bool(value) or not nonempty),
             f"{label} artifact list is invalid")
    observed = [
        _artifact(item, label=f"{label}[{index}]", roles=roles)
        for index, item in enumerate(value)
    ]
    keys = [
        (item["role"], item["descriptor"]["path"])
        for item in observed
    ]
    _require(keys == sorted(keys) and len(keys) == len(set(keys)),
             f"{label} artifacts are not sorted and unique")
    return observed


def _content_section(value: Any, *, label: str) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == CONTENT_FIELDS,
             f"{label} fields drifted")
    _require(type(value.get("content")) is dict,
             f"{label} content must be an object")
    _require(
        value.get("content_identity_sha256") == _canonical_sha(value["content"]),
        f"{label} content identity drifted",
    )
    return copy.deepcopy(value)


def _validate_coordinate(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == COORDINATE_FIELDS,
             "runtime authority coordinate fields drifted")
    _require(value.get("system") in SYSTEMS, "runtime authority system is invalid")
    _require(value.get("policy") in POLICIES, "runtime authority policy is invalid")
    _require(value.get("topology_kind") in TOPOLOGIES,
             "runtime authority topology is invalid")
    _require(value.get("codec") in CODECS, "runtime authority codec is invalid")
    return copy.deepcopy(value)


def validate_backend_publication_runtime_authority(
    value: Any, *, expected_system: str | None = None,
    expected_policy: str | None = None,
    expected_topology_kind: str | None = None,
    expected_codec: str | None = None,
) -> dict[str, Any]:
    """Validate closed canonical content without touching the filesystem."""
    _require(type(value) is dict and set(value) == TOP_FIELDS,
             "backend publication runtime authority fields drifted")
    coordinate = _validate_coordinate(value.get("coordinate"))
    for observed, expected, label in (
        (coordinate["system"], expected_system, "system"),
        (coordinate["policy"], expected_policy, "policy"),
        (coordinate["topology_kind"], expected_topology_kind, "topology"),
        (coordinate["codec"], expected_codec, "codec"),
    ):
        _require(expected is None or observed == expected,
                 f"runtime authority {label} cross-dispatch drifted")

    dataset = value.get("dataset")
    _require(type(dataset) is dict and set(dataset) == DATASET_FIELDS,
             "runtime authority dataset fields drifted")
    manifest = _descriptor(dataset.get("manifest"), label="dataset manifest")
    files = dataset.get("files")
    _require(type(files) is list and bool(files), "dataset file list is invalid")
    checked_files = [
        _descriptor(item, label=f"dataset file[{index}]")
        for index, item in enumerate(files)
    ]
    paths = [item["path"] for item in checked_files]
    _require(paths == sorted(paths) and len(paths) == len(set(paths)),
             "dataset file descriptors are not sorted and unique")
    _require(_valid_sha(dataset.get("content_identity_sha256")),
             "dataset content identity is invalid")
    _require(
        dataset["content_identity_sha256"]
        == _canonical_sha({"manifest": manifest, "files": checked_files}),
        "dataset descriptor-set identity drifted",
    )

    sources = _artifact_list(
        value.get("source_runtime_artifacts"),
        label="source runtime", roles=SOURCE_ROLES,
    )
    backends = _artifact_list(
        value.get("backend_runtime_artifacts"),
        label="backend runtime", roles=BACKEND_ROLES,
    )
    analytics = value.get("analytics_authority")
    _require(type(analytics) is dict and set(analytics) == ANALYTICS_FIELDS,
             "analytics authority fields drifted")
    endpoint = analytics.get("endpoint_authority")
    _require(type(endpoint) is dict and set(endpoint) == ENDPOINT_FIELDS,
             "analytics endpoint authority fields drifted")
    _require(
        endpoint.get("transport") == "AF_UNIX/SOCK_SEQPACKET"
        and _valid_sha(endpoint.get("path_derivation_contract_sha256"))
        and _valid_sha(endpoint.get("peer_capability_identity_sha256"))
        and _valid_sha(endpoint.get("peer_binding_identity_sha256"))
        and endpoint.get("bind_before_backend_launch") is True
        and endpoint.get("peer_credentials_required") is True,
        "analytics endpoint authority is invalid",
    )
    capability = _artifact(
        analytics.get("capability"), label="analytics capability",
        roles=frozenset({"analytics_endpoint_capability"}),
    )
    bindings = _artifact_list(
        analytics.get("bindings"), label="analytics binding",
        roles=frozenset({"analytics_worker_binding"}),
    )
    _require(_valid_sha(analytics.get("preprocessing_contract_sha256")),
             "analytics preprocessing identity is invalid")

    _require(_valid_sha(value.get("model_parity_acceptance_binding_sha256")),
             "model parity acceptance binding identity is invalid")
    policy = value.get("policy_authority")
    _require(type(policy) is dict and set(policy) == POLICY_FIELDS,
             "policy authority fields drifted")
    policy_capability = _artifact(
        policy.get("capability"), label="policy capability",
        roles=frozenset({"policy_capability"}),
    )
    calibration = _artifact(
        policy.get("calibration"), label="policy calibration",
        roles=frozenset({"policy_calibration"}),
    )
    static_map = policy.get("static_map")
    if coordinate["policy"] == "static_hybrid":
        static_map = _artifact(
            static_map, label="policy static map",
            roles=frozenset({"policy_static_map"}),
        )
    else:
        _require(static_map is None,
                 "policy static map is prohibited outside static_hybrid")

    _content_section(value.get("cohort_topology_plan"), label="cohort topology plan")
    _content_section(value.get("resource_contract"), label="resource contract")
    _content_section(
        value.get("system_specific_launcher_input"),
        label="system-specific launcher input",
    )
    _require(
        value["cohort_topology_plan"]["content"].get("topology_kind")
        == coordinate["topology_kind"],
        "cohort topology plan/coordinate drifted",
    )
    launcher_system = value["system_specific_launcher_input"]["content"].get("system")
    _require(launcher_system == coordinate["system"],
             "system-specific launcher input/coordinate drifted")

    descriptors = [manifest, *checked_files]
    descriptors.extend(item["descriptor"] for item in sources)
    descriptors.extend(item["descriptor"] for item in backends)
    descriptors.extend([capability["descriptor"]])
    descriptors.extend(item["descriptor"] for item in bindings)
    descriptors.extend([policy_capability["descriptor"], calibration["descriptor"]])
    if static_map is not None:
        descriptors.append(static_map["descriptor"])
    all_paths = [item["path"] for item in descriptors]
    _require(len(all_paths) == len(set(all_paths)),
             "runtime authority physical descriptor paths are aliased")

    _require(value.get("schema_version") == SCHEMA_VERSION,
             "runtime authority schema version is invalid")
    _require(value.get("artifact_kind") == ARTIFACT_KIND,
             "runtime authority artifact kind is invalid")
    unsigned = {key: item for key, item in value.items() if key != "authority_sha256"}
    _require(value.get("authority_sha256") == _canonical_sha(unsigned),
             "runtime authority self-hash drifted")
    return copy.deepcopy(value)


def _info_is_link_or_reparse(info: Any) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _stable_identity(info: Any) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode), int(info.st_size),
        int(info.st_mtime_ns), int(info.st_ctime_ns), int(info.st_nlink),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _win_open_handle(
    path: Path, *, directory: bool, read_data: bool = False,
) -> int:
    if os.name != "nt":
        raise OSError("Windows handle traversal is unavailable")
    desired_access = (
        (_WIN_FILE_LIST_DIRECTORY | _WIN_FILE_READ_ATTRIBUTES)
        if directory else
        (_WIN_GENERIC_READ | _WIN_FILE_READ_ATTRIBUTES)
    )
    if read_data:
        desired_access |= _WIN_GENERIC_READ
    flags = _WIN_FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= _WIN_FILE_FLAG_BACKUP_SEMANTICS
    ctypes.set_last_error(0)
    handle = _WIN_CREATE_FILE(
        str(path), desired_access,
        _WIN_FILE_SHARE_READ,
        None, _WIN_OPEN_EXISTING, flags, None,
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
        *_win_identity(info),
        int(info["file_attributes"]),
        int(info["reparse_tag"]),
        int(info["size"]),
        int(info["nlink"]),
        bool(info["delete_pending"]),
        bool(info["is_directory"]),
    )


def _win_identity_from_fingerprint(
    value: tuple[Any, ...],
) -> tuple[int, bytes]:
    return int(value[0]), bytes(value[1])


def _win_validate_component(
    info: Mapping[str, Any], *, label: str, directory: bool,
    expected_volume: int | None,
) -> None:
    if int(info["file_attributes"]) & _WIN_FILE_ATTRIBUTE_REPARSE_POINT:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} path contains a link/reparse point"
        )
    if bool(info["is_directory"]) != directory:
        kind = "directory" if directory else "regular file"
        raise BackendPublicationRuntimeAuthorityError(f"{label} is not a {kind}")
    if info["delete_pending"]:
        raise BackendPublicationRuntimeAuthorityError(f"{label} is delete-pending")
    if (
        expected_volume is not None
        and int(info["volume_serial"]) != expected_volume
    ):
        raise BackendPublicationRuntimeAuthorityError(f"{label} volume drifted")


def _win_reopen_identity(
    path: Path, *, directory: bool, label: str, expected_volume: int,
) -> tuple[int, bytes]:
    handle = _win_open_handle(path, directory=directory, read_data=False)
    primary_active = False
    try:
        info = _win_query_handle(handle)
        _win_validate_component(
            info, label=label, directory=directory,
            expected_volume=expected_volume,
        )
        return _win_identity(info)
    except BaseException:
        primary_active = True
        raise
    finally:
        try:
            _win_close_handle(handle)
        except OSError:
            if not primary_active:
                raise


def _all_descriptor_records(authority: Mapping[str, Any]) -> list[tuple[str, dict[str, Any], str | None]]:
    records: list[tuple[str, dict[str, Any], str | None]] = []
    dataset = authority["dataset"]
    records.append(("dataset manifest", dataset["manifest"], None))
    records.extend(
        (f"dataset file[{index}]", descriptor, None)
        for index, descriptor in enumerate(dataset["files"])
    )
    for section in ("source_runtime_artifacts", "backend_runtime_artifacts"):
        records.extend(
            (
                f"{section}:{item['role']}", item["descriptor"],
                item["content_identity_sha256"],
            )
            for item in authority[section]
        )
    analytics = authority["analytics_authority"]
    records.append((
        "analytics capability", analytics["capability"]["descriptor"],
        analytics["capability"]["content_identity_sha256"],
    ))
    records.extend(
        (
            f"analytics binding[{index}]", item["descriptor"],
            item["content_identity_sha256"],
        )
        for index, item in enumerate(analytics["bindings"])
    )
    policy = authority["policy_authority"]
    for key in ("capability", "calibration", "static_map"):
        item = policy[key]
        if item is not None:
            records.append((
                f"policy {key}", item["descriptor"],
                item["content_identity_sha256"],
            ))
    return records


def _read_physical_descriptor_windows(
    root: Path, relative: PurePosixPath, descriptor: Mapping[str, Any],
    *, label: str, expected_root_identity: tuple[int, int],
) -> tuple[int, int]:
    held: list[tuple[int, Path, bool, tuple[Any, ...]]] = []
    owned_handles: list[int] = []
    descriptor_fd: int | None = None
    opened_final_handle: int | None = None
    final_identity: tuple[int, bytes] | None = None
    root_volume: int | None = None
    digest = hashlib.sha256()
    observed = 0
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
            root_identity[0],
            int.from_bytes(root_identity[1], "little"),
        ) != expected_root_identity:
            raise BackendPublicationRuntimeAuthorityError(
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
                raise BackendPublicationRuntimeAuthorityError(
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
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} path contains a duplicate FileId"
            )
        if int(final_native["nlink"]) != 1:
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} hardlink alias is prohibited"
            )
        if (
            int(final_native["size"]) <= 0
            or int(final_native["size"]) > MAX_PHYSICAL_ARTIFACT_BYTES
        ):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} size is outside the bounded range"
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
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} native/CRT handle identity drifted"
            )
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_PHYSICAL_ARTIFACT_BYTES:
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} exceeded the bounded read size"
                )
            digest.update(chunk)
        after = os.fstat(descriptor_fd)
        if _stable_identity(opened) != _stable_identity(after):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} changed while reading"
            )

        for handle, _, is_directory, expected_fingerprint in held:
            current = _win_query_handle(handle)
            _win_validate_component(
                current, label=label, directory=is_directory,
                expected_volume=root_volume,
            )
            if _win_component_fingerprint(current) != expected_fingerprint:
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} held path component changed while reading"
                )
        current_final = _win_query_handle(
            int(msvcrt.get_osfhandle(descriptor_fd))
        )
        _win_validate_component(
            current_final, label=label, directory=False,
            expected_volume=root_volume,
        )
        if _win_component_fingerprint(current_final) != final_fingerprint:
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} held file changed while reading"
            )

        expected_paths = [
            (path_value, is_directory, _win_identity_from_fingerprint(fingerprint))
            for _, path_value, is_directory, fingerprint in held
        ]
        expected_paths.append((path, False, final_identity))
        for expected_path, is_directory, expected_identity in expected_paths:
            if _win_reopen_identity(
                expected_path, directory=is_directory, label=label,
                expected_volume=root_volume,
            ) != expected_identity:
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} path component changed while reading"
                )
    except BackendPublicationRuntimeAuthorityError:
        raise
    except (OSError, ValueError) as error:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} cannot be securely read: {error}"
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
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} native handle cleanup failed: {close_error}"
            ) from close_error
    if final_identity is None or root_volume is None:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} secure traversal did not establish an identity"
        )
    if observed != descriptor["size_bytes"]:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} physical size drifted"
        )
    if digest.hexdigest() != descriptor["sha256"]:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} physical SHA-256 drifted"
        )
    return final_identity[0], int.from_bytes(final_identity[1], "little")


def _read_physical_descriptor_posix(
    root: Path, relative: PurePosixPath, descriptor: Mapping[str, Any],
    *, label: str, expected_root_identity: tuple[int, int],
) -> tuple[int, int]:
    held: list[int] = []
    verification_handles: list[int] = []
    descriptor_fd: int | None = None
    opened: os.stat_result | None = None
    after: os.stat_result | None = None
    digest = hashlib.sha256()
    observed = 0
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
            raise BackendPublicationRuntimeAuthorityError(
                "project root changed before secure assessment"
            )
        parent_fd = root_fd
        component_identities: list[tuple[str, tuple[int, int]]] = []
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=parent_fd)
            held.append(child_fd)
            child_info = os.fstat(child_fd)
            if not stat.S_ISDIR(child_info.st_mode):
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} parent is not a directory"
                )
            if int(child_info.st_dev) != int(root_info.st_dev):
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} volume drifted"
                )
            component_identities.append((
                part, (int(child_info.st_dev), int(child_info.st_ino)),
            ))
            parent_fd = child_fd
        flags = (
            os.O_RDONLY | os.O_NOFOLLOW
            | int(getattr(os, "O_CLOEXEC", 0))
        )
        descriptor_fd = os.open(
            relative.parts[-1], flags, dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor_fd)
        if not stat.S_ISREG(opened.st_mode):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} is not a regular file"
            )
        if int(opened.st_nlink) != 1:
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} hardlink alias is prohibited"
            )
        if int(opened.st_dev) != int(root_info.st_dev):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} volume drifted"
            )
        if (
            int(opened.st_size) <= 0
            or int(opened.st_size) > MAX_PHYSICAL_ARTIFACT_BYTES
        ):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} size is outside the bounded range"
            )
        while True:
            chunk = os.read(descriptor_fd, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_PHYSICAL_ARTIFACT_BYTES:
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} exceeded the bounded read size"
                )
            digest.update(chunk)
        after = os.fstat(descriptor_fd)
        if _stable_identity(opened) != _stable_identity(after):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} changed while reading"
            )

        verify_parent = os.open(root, directory_flags)
        verification_handles.append(verify_parent)
        verify_root = os.fstat(verify_parent)
        if (
            int(verify_root.st_dev), int(verify_root.st_ino)
        ) != expected_root_identity:
            raise BackendPublicationRuntimeAuthorityError(
                "project root changed while assessing runtime authority"
            )
        for part, expected_identity in component_identities:
            next_fd = os.open(
                part, directory_flags, dir_fd=verify_parent,
            )
            verification_handles.append(next_fd)
            verify_info = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(verify_info.st_mode)
                or int(verify_info.st_dev) != int(root_info.st_dev)
                or (int(verify_info.st_dev), int(verify_info.st_ino))
                != expected_identity
            ):
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} path component changed while reading"
                )
            verify_parent = next_fd
        verify_fd = os.open(
            relative.parts[-1], flags, dir_fd=verify_parent,
        )
        verification_handles.append(verify_fd)
        verify_info = os.fstat(verify_fd)
        if (
            not stat.S_ISREG(verify_info.st_mode)
            or int(verify_info.st_dev) != int(root_info.st_dev)
            or (int(verify_info.st_dev), int(verify_info.st_ino))
            != (int(after.st_dev), int(after.st_ino))
        ):
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} path component changed while reading"
            )
    except BackendPublicationRuntimeAuthorityError:
        raise
    except OSError as error:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} cannot be securely read: {error}"
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
            raise BackendPublicationRuntimeAuthorityError(
                f"{label} descriptor cleanup failed: {close_error}"
            ) from close_error
    if opened is None or after is None:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} secure traversal did not establish an identity"
        )
    if observed != descriptor["size_bytes"]:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} physical size drifted"
        )
    if digest.hexdigest() != descriptor["sha256"]:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} physical SHA-256 drifted"
        )
    return int(after.st_dev), int(after.st_ino)


def _read_physical_descriptor(
    root: Path, descriptor: Mapping[str, Any], *, label: str,
    expected_root_identity: tuple[int, int],
) -> tuple[int, int]:
    relative = PurePosixPath(str(descriptor["path"]))
    path = root.joinpath(*relative.parts)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} escapes the project root"
        ) from error
    if os.name == "nt":
        return _read_physical_descriptor_windows(
            root, relative, descriptor, label=label,
            expected_root_identity=expected_root_identity,
        )
    if (
        os.open not in os.supports_dir_fd
        or not all(hasattr(os, name) for name in ("O_DIRECTORY", "O_NOFOLLOW"))
    ):
        raise BackendPublicationRuntimeAuthorityError(
            f"{label} secure handle-bound traversal is unavailable"
        )
    return _read_physical_descriptor_posix(
        root, relative, descriptor, label=label,
        expected_root_identity=expected_root_identity,
    )


def assess_backend_publication_runtime_authority(
    value: Any, *, project_root: Path,
    expected_system: str | None = None,
    expected_policy: str | None = None,
    expected_topology_kind: str | None = None,
    expected_codec: str | None = None,
) -> dict[str, Any]:
    """Physically rehash every leaf and report validity without acceptance."""
    authority_sha = value.get("authority_sha256") if type(value) is dict else None
    coordinate = value.get("coordinate", {}) if type(value) is dict else {}
    blockers: list[str] = []
    checked = 0
    try:
        authority = validate_backend_publication_runtime_authority(
            value,
            expected_system=expected_system,
            expected_policy=expected_policy,
            expected_topology_kind=expected_topology_kind,
            expected_codec=expected_codec,
        )
        supplied_root = Path(project_root)
        if not supplied_root.is_absolute():
            raise BackendPublicationRuntimeAuthorityError(
                "project root is not an absolute canonical path"
            )
        root = supplied_root.resolve(strict=True)
        root_info = root.lstat()
        if supplied_root != root or not stat.S_ISDIR(root_info.st_mode) or _info_is_link_or_reparse(root_info):
            raise BackendPublicationRuntimeAuthorityError(
                "project root is not a canonical plain directory"
            )
        identities: set[tuple[int, int]] = set()
        for label, descriptor, semantic_identity in _all_descriptor_records(authority):
            observed_root = root.lstat()
            if (
                _info_is_link_or_reparse(observed_root)
                or not stat.S_ISDIR(observed_root.st_mode)
                or (int(observed_root.st_dev), int(observed_root.st_ino))
                != (int(root_info.st_dev), int(root_info.st_ino))
            ):
                raise BackendPublicationRuntimeAuthorityError(
                    "project root changed while assessing runtime authority"
                )
            identity = _read_physical_descriptor(
                root, descriptor, label=label,
                expected_root_identity=(
                    int(root_info.st_dev), int(root_info.st_ino),
                ),
            )
            if identity in identities:
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} aliases another physical artifact"
                )
            identities.add(identity)
            if semantic_identity is not None and semantic_identity == descriptor["sha256"]:
                pass
            elif semantic_identity is not None and not _valid_sha(semantic_identity):
                raise BackendPublicationRuntimeAuthorityError(
                    f"{label} semantic content identity is invalid"
                )
            checked += 1
        final_root = root.lstat()
        if (
            _info_is_link_or_reparse(final_root)
            or not stat.S_ISDIR(final_root.st_mode)
            or (int(final_root.st_dev), int(final_root.st_ino))
            != (int(root_info.st_dev), int(root_info.st_ino))
        ):
            raise BackendPublicationRuntimeAuthorityError(
                "project root changed while assessing runtime authority"
            )
    except (BackendPublicationRuntimeAuthorityError, OSError, ValueError) as error:
        blockers.append(str(error))
    blockers = sorted(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": ASSESSMENT_KIND,
        "status": "physically_valid" if not blockers else "blocked",
        "authority_sha256": authority_sha,
        "system": coordinate.get("system"),
        "policy": coordinate.get("policy"),
        "topology_kind": coordinate.get("topology_kind"),
        "codec": coordinate.get("codec"),
        "checked_artifact_count": checked,
        "blockers": blockers,
    }


def build_backend_publication_runtime_authority(
    *, project_root: Path, system: str, policy: str, topology_kind: str,
    codec: str, dataset_manifest: Mapping[str, Any],
    dataset_files: Sequence[Mapping[str, Any]],
    source_runtime_artifacts: Sequence[Mapping[str, Any]],
    backend_runtime_artifacts: Sequence[Mapping[str, Any]],
    analytics_authority: Mapping[str, Any],
    model_parity_acceptance_binding_sha256: str,
    policy_authority: Mapping[str, Any],
    cohort_topology_plan: Mapping[str, Any],
    resource_contract: Mapping[str, Any],
    system_specific_launcher_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a leaf authority only after all physical artifacts validate."""
    dataset_files_list = [copy.deepcopy(dict(item)) for item in dataset_files]
    dataset = {
        "manifest": copy.deepcopy(dict(dataset_manifest)),
        "files": dataset_files_list,
        "content_identity_sha256": _canonical_sha({
            "manifest": copy.deepcopy(dict(dataset_manifest)),
            "files": dataset_files_list,
        }),
    }
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "coordinate": {
            "system": system, "policy": policy,
            "topology_kind": topology_kind, "codec": codec,
        },
        "dataset": dataset,
        "source_runtime_artifacts": [copy.deepcopy(dict(item)) for item in source_runtime_artifacts],
        "backend_runtime_artifacts": [copy.deepcopy(dict(item)) for item in backend_runtime_artifacts],
        "analytics_authority": copy.deepcopy(dict(analytics_authority)),
        "model_parity_acceptance_binding_sha256": model_parity_acceptance_binding_sha256,
        "policy_authority": copy.deepcopy(dict(policy_authority)),
        "cohort_topology_plan": copy.deepcopy(dict(cohort_topology_plan)),
        "resource_contract": copy.deepcopy(dict(resource_contract)),
        "system_specific_launcher_input": copy.deepcopy(dict(system_specific_launcher_input)),
    }
    material["authority_sha256"] = _canonical_sha(material)
    validate_backend_publication_runtime_authority(material)
    assessment = assess_backend_publication_runtime_authority(
        material, project_root=project_root,
        expected_system=system, expected_policy=policy,
        expected_topology_kind=topology_kind, expected_codec=codec,
    )
    if assessment["status"] != "physically_valid":
        raise BackendPublicationRuntimeAuthorityError(
            "runtime authority physical assessment blocked: "
            + ";".join(assessment["blockers"])
        )
    return material


__all__ = [
    "ARTIFACT_KIND", "ASSESSMENT_KIND", "SCHEMA_VERSION",
    "MAX_PHYSICAL_ARTIFACT_BYTES", "BackendPublicationRuntimeAuthorityError",
    "assess_backend_publication_runtime_authority",
    "build_backend_publication_runtime_authority",
    "validate_backend_publication_runtime_authority",
]
