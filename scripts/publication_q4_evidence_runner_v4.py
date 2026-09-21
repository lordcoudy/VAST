#!/usr/bin/env python3
"""Hermetic, read-only runner for one physically pinned Q4-v4 replay.

This file intentionally uses only the Python standard library.  It is meant to
be invoked with ``python -I -S -B -X utf8`` and the exact argv published by
``backend_runtime_validation_runner_authority.py``.  It never grants execution
or production authority; its sole success value is a qualified evidence replay.
"""
from __future__ import annotations

import builtins
import copy
import hashlib
import io
import json
import math
import os
import re
import socket
import stat
import subprocess
import sys
import types
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


EXIT_USAGE = 64
EXIT_REJECTED = 78
MAX_JSON_BYTES = 256 * 1024 * 1024
MAX_STDOUT_BYTES = 64 * 1024
MAX_DIAGNOSTIC_BYTES = 4096

RUNNER_AUTHORITY_KIND = "vast_backend_runtime_validation_runner_authority"
RUNNER_MANIFEST_KIND = "vast_backend_runtime_validation_bundle_manifest"
RUNNER_INVOCATION_KIND = (
    "vast_backend_runtime_validation_runner_invocation_contract"
)
VALIDATOR_AUTHORITY_KIND = "vast_backend_runtime_validator_authority_q4"
REQUEST_KIND = "vast_backend_runtime_validation_replay_request_v2"
RUNTIME_AUTHORITY_KIND = "vast_backend_publication_runtime_authority_v2"
RAW_MANIFEST_KIND = "vast_publication_q4_raw_evidence_manifest_v4"

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_ARTIFACT_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})

_OPTION_NAMES = (
    "--project-root",
    "--runner-authority",
    "--runner-authority-file-sha256",
    "--runner-authority-sha256",
    "--validator-authority",
    "--validator-authority-file-sha256",
    "--validator-authority-sha256",
    "--request",
    "--request-file-sha256",
    "--request-sha256",
)

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

_RUNNER_MANIFEST_FIELDS = frozenset({
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
_RUNNER_AUTHORITY_FIELDS = frozenset({
    "schema_version", "artifact_kind", "runner_id",
    "runtime_bundle_manifest", "runtime_bundle_manifest_content",
    "runtime_leaves", "runtime_leaf_set_sha256", "python_executable",
    "runner", "invocation_contract",
    "supported_validator_authority_schema_version",
    "validation_protocol_identity_sha256", "input_schema_identity_sha256",
    "output_schema_identity_sha256", "deterministic",
    "runner_authority_sha256",
})
_VALIDATOR_IDENTITY_FIELDS = frozenset({
    "qualification_input_schema_identity_sha256",
    "validation_system_context_schema_identity_sha256",
    "validation_request_schema_identity_sha256",
    "validation_record_schema_identity_sha256",
    "validation_system_shard_schema_identity_sha256",
    "validation_record_set_index_schema_identity_sha256",
    "validation_protocol_identity_sha256",
    "validation_input_schema_identity_sha256",
    "validation_output_schema_identity_sha256",
})
_VALIDATOR_AUTHORITY_FIELDS = frozenset({
    "schema_version", "artifact_kind", "validator_id", "implementation",
    "supported_qualification_schema_version", *_VALIDATOR_IDENTITY_FIELDS,
    "deterministic", "execution_authorized",
    "validation_records_authenticated", "authority_sha256",
})
_RUNTIME_AUTHORITY_FIELDS = frozenset({
    "schema_version", "artifact_kind", "coordinate", "dataset",
    "source_runtime_artifacts", "backend_runtime_artifacts",
    "analytics_authority", "policy_authority", "cohort_topology_plan",
    "resource_contract", "system_specific_launcher_input",
    "upstream_identities", "authority_sha256",
})


class PublicationQ4EvidenceRunnerV4Error(ValueError):
    """The isolated request or one of its physical trust pins drifted."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4EvidenceRunnerV4Error(message)


def _strict_json(value: Any, *, active: set[int] | None = None, depth: int = 0) -> None:
    _require(depth <= 128, "JSON nesting exceeds the runner bound")
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        _require(math.isfinite(value), "JSON contains a non-finite number")
        return
    _require(type(value) in {dict, list}, "JSON contains a non-canonical type")
    active = set() if active is None else active
    identity = id(value)
    _require(identity not in active, "JSON contains a cycle")
    active.add(identity)
    if type(value) is dict:
        _require(
            all(type(key) is str for key in value),
            "JSON object contains a non-string key",
        )
        for item in value.values():
            _strict_json(item, active=active, depth=depth + 1)
    else:
        for item in value:
            _strict_json(item, active=active, depth=depth + 1)
    active.remove(identity)


def _canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    _strict_json(value)
    try:
        text = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            "value is not canonical JSON"
        ) from error
    return (text + ("\n" if newline else "")).encode("ascii")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return value


def _relative(value: Any, label: str) -> str:
    _require(type(value) is str and bool(value), f"{label} path is empty")
    path = PurePosixPath(value)
    _require(
        path.as_posix() == value and not path.is_absolute()
        and path.anchor == "" and "\\" not in value and ":" not in value
        and "\x00" not in value and "//" not in value
        and all(
            part not in {"", ".", ".."}
            and not part.endswith((".", " "))
            and not any(ord(character) < 32 for character in part)
            and part.split(".", 1)[0].upper() not in _RESERVED
            for part in path.parts
        ),
        f"{label} path is unsafe",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    size = value.get("size_bytes")
    _require(
        type(size) is int and 0 < size <= MAX_JSON_BYTES,
        f"{label} size is invalid",
    )
    return {
        "path": _relative(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _artifact(value: Any, label: str, *, semantic_file_hash: bool = True) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _ARTIFACT_FIELDS,
        f"{label} artifact fields drifted",
    )
    descriptor = _descriptor(value.get("descriptor"), label)
    identity = _sha(value.get("content_identity_sha256"), f"{label} semantic")
    if semantic_file_hash:
        _require(identity == descriptor["sha256"], f"{label} semantic/file drifted")
    return {"descriptor": descriptor, "content_identity_sha256": identity}


def _project_root(value: str) -> Path:
    supplied = Path(value)
    _require(supplied.is_absolute(), "project_root is not absolute")
    try:
        resolved = supplied.resolve(strict=True)
        info = supplied.lstat()
    except OSError as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            "project_root is unavailable"
        ) from error
    _require(
        supplied == resolved and stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode),
        "project_root is not a canonical physical directory",
    )
    return resolved


def _path_under_root(root: Path, relative: str, label: str) -> Path:
    checked = _relative(relative, label)
    path = root.joinpath(*PurePosixPath(checked).parts)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            f"{label} is unavailable"
        ) from error
    _require(
        resolved == path and resolved.is_relative_to(root),
        f"{label} escaped project_root or crossed a link",
    )
    parent = root
    for part in PurePosixPath(checked).parts[:-1]:
        parent /= part
        info = parent.lstat()
        _require(
            stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
            f"{label} parent is unsafe",
        )
    return path


def _read_physical(root: Path, descriptor: Mapping[str, Any], label: str) -> bytes:
    expected = _descriptor(dict(descriptor), label)
    path = _path_under_root(root, expected["path"], label)
    fd = -1
    try:
        before = path.lstat()
        _require(
            stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode)
            and int(before.st_nlink) == 1,
            f"{label} is not a unique regular file",
        )
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(fd)
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, expected["size_bytes"] + 1))
            if not chunk:
                break
            size += len(chunk)
            _require(size <= expected["size_bytes"], f"{label} grew while reading")
            chunks.append(chunk)
            digest.update(chunk)
        after = path.lstat()
        identity = lambda item: (
            int(item.st_dev), int(item.st_ino), int(item.st_mode),
            int(item.st_nlink), int(item.st_size), int(item.st_mtime_ns),
        )
        _require(
            identity(before) == identity(opened) == identity(after),
            f"{label} changed while reading",
        )
        _require(
            size == expected["size_bytes"]
            and digest.hexdigest() == expected["sha256"],
            f"{label} physical descriptor drifted",
        )
        return b"".join(chunks)
    except OSError as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            f"{label} physical read failed"
        ) from error
    finally:
        if fd >= 0:
            os.close(fd)


def _descriptor_for_absolute(root: Path, value: str, digest: str, label: str) -> dict[str, Any]:
    path = Path(value)
    _require(path.is_absolute(), f"{label} argv path is not absolute")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PublicationQ4EvidenceRunnerV4Error(f"{label} is unavailable") from error
    _require(
        path == resolved and path.is_relative_to(root),
        f"{label} argv path escaped project_root or crossed a link",
    )
    relative = path.relative_to(root).as_posix()
    info = path.stat()
    return {
        "path": relative,
        "size_bytes": int(info.st_size),
        "sha256": _sha(digest, f"{label} external file"),
    }


def _load_canonical_json(payload: bytes, label: str) -> dict[str, Any]:
    _require(0 < len(payload) <= MAX_JSON_BYTES, f"{label} size is invalid")
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            f"{label} is not valid JSON"
        ) from error
    _require(type(value) is dict, f"{label} must be a JSON object")
    _require(
        payload in {_canonical_bytes(value), _canonical_bytes(value, newline=True)},
        f"{label} is not canonical JSON",
    )
    return dict(value)


def _invocation_contract() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": RUNNER_INVOCATION_KIND,
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


def _validate_manifest(value: Any) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _RUNNER_MANIFEST_FIELDS,
        "runner bundle manifest fields drifted",
    )
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == RUNNER_MANIFEST_KIND,
        "runner bundle manifest header drifted",
    )
    interpreter = _artifact(value.get("python_executable"), "bundle interpreter")
    runner = _artifact(value.get("runner"), "bundle runner")
    leaves_value = value.get("runtime_leaves")
    _require(type(leaves_value) is list and bool(leaves_value), "bundle leaves are empty")
    leaves = [_artifact(item, f"bundle leaf[{index}]") for index, item in enumerate(leaves_value)]
    paths = [item["descriptor"]["path"] for item in leaves]
    _require(
        paths == sorted(paths) and len(paths) == len({item.casefold() for item in paths}),
        "bundle leaves are not sorted and unique",
    )
    _require(
        value.get("runtime_leaf_set_sha256") == _canonical_sha(leaves),
        "runner bundle leaf-set identity drifted",
    )
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "bundle_manifest_sha256"}
    _require(
        value.get("bundle_manifest_sha256") == _canonical_sha(unsigned),
        "runner bundle manifest self-hash drifted",
    )
    return copy.deepcopy(value)


def _validate_runner_authority(
    value: Any, *, expected_sha256: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _RUNNER_AUTHORITY_FIELDS,
        "runner authority fields drifted",
    )
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == RUNNER_AUTHORITY_KIND
        and type(value.get("runner_id")) is str
        and _ID_RE.fullmatch(value["runner_id"]) is not None,
        "runner authority header/id drifted",
    )
    manifest_ref = _artifact(
        value.get("runtime_bundle_manifest"), "runner bundle manifest",
        semantic_file_hash=False,
    )
    manifest = _validate_manifest(value.get("runtime_bundle_manifest_content"))
    _require(
        manifest_ref["content_identity_sha256"] == manifest["bundle_manifest_sha256"],
        "runner bundle manifest semantic identity drifted",
    )
    interpreter = _artifact(value.get("python_executable"), "runner interpreter")
    runner = _artifact(value.get("runner"), "runner implementation")
    leaves_value = value.get("runtime_leaves")
    _require(type(leaves_value) is list and bool(leaves_value), "runner leaves are empty")
    leaves = [_artifact(item, f"runner leaf[{index}]") for index, item in enumerate(leaves_value)]
    _require(
        manifest["python_executable"] == interpreter
        and manifest["runner"] == runner
        and manifest["runtime_leaves"] == leaves
        and value.get("runtime_leaf_set_sha256") == _canonical_sha(leaves)
        == manifest["runtime_leaf_set_sha256"],
        "runner authority bundle closure drifted",
    )
    all_paths = [
        manifest_ref["descriptor"]["path"], interpreter["descriptor"]["path"],
        runner["descriptor"]["path"],
        *(item["descriptor"]["path"] for item in leaves),
    ]
    _require(
        len(all_paths) == len({item.casefold() for item in all_paths}),
        "runner authority artifact paths alias",
    )
    invocation = value.get("invocation_contract")
    _require(
        type(invocation) is dict and set(invocation) == _INVOCATION_FIELDS
        and type(invocation.get("process_contract")) is dict
        and set(invocation["process_contract"]) == _PROCESS_FIELDS
        and invocation == _invocation_contract(),
        "runner invocation contract drifted",
    )
    _require(
        value.get("supported_validator_authority_schema_version") == 1
        and value.get("deterministic") is True,
        "runner authority capability drifted",
    )
    for field in (
        "validation_protocol_identity_sha256", "input_schema_identity_sha256",
        "output_schema_identity_sha256",
    ):
        _sha(value.get(field), f"runner authority {field}")
    identity = _sha(value.get("runner_authority_sha256"), "runner authority")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "runner_authority_sha256"}
    _require(
        identity == _canonical_sha(unsigned)
        == _sha(expected_sha256, "expected runner authority"),
        "runner authority self/external pin drifted",
    )
    return copy.deepcopy(value)


def _validate_validator_authority(
    value: Any, *, expected_sha256: str,
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _VALIDATOR_AUTHORITY_FIELDS,
        "validator authority fields drifted",
    )
    _require(
        value.get("schema_version") == 1
        and value.get("artifact_kind") == VALIDATOR_AUTHORITY_KIND
        and type(value.get("validator_id")) is str
        and _ID_RE.fullmatch(value["validator_id"]) is not None,
        "validator authority header/id drifted",
    )
    implementation = _artifact(value.get("implementation"), "validator implementation")
    _require(
        value.get("supported_qualification_schema_version") == 4
        and value.get("deterministic") is True
        and value.get("execution_authorized") is False
        and value.get("validation_records_authenticated") is False,
        "validator authority capability/claims drifted",
    )
    for field in _VALIDATOR_IDENTITY_FIELDS:
        _sha(value.get(field), f"validator authority {field}")
    identity = _sha(value.get("authority_sha256"), "validator authority")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "authority_sha256"}
    _require(
        identity == _canonical_sha(unsigned)
        == _sha(expected_sha256, "expected validator authority"),
        "validator authority self/external pin drifted",
    )
    return {**copy.deepcopy(value), "_implementation": implementation}


def _verify_runner_closure(
    *, root: Path, authority: Mapping[str, Any], authority_file_descriptor: Mapping[str, Any],
) -> None:
    _read_physical(root, authority_file_descriptor, "runner authority")
    manifest_ref = authority["runtime_bundle_manifest"]
    manifest_payload = _read_physical(root, manifest_ref["descriptor"], "runner bundle manifest")
    manifest_value = _load_canonical_json(manifest_payload, "runner bundle manifest")
    _require(
        manifest_value == authority["runtime_bundle_manifest_content"],
        "physical runner bundle manifest content drifted",
    )
    artifacts = [
        authority["python_executable"], authority["runner"],
        *authority["runtime_leaves"],
    ]
    for index, artifact in enumerate(artifacts):
        _read_physical(root, artifact["descriptor"], f"runner closure[{index}]")
    runner_path = Path(__file__).resolve(strict=True)
    _require(
        runner_path == _path_under_root(
            root, authority["runner"]["descriptor"]["path"], "runner implementation"
        ),
        "executed runner is not the pinned implementation",
    )
    executable = Path(sys.executable).resolve(strict=True)
    _require(
        executable == _path_under_root(
            root, authority["python_executable"]["descriptor"]["path"],
            "runner interpreter",
        ),
        "executed interpreter is not the pinned project interpreter",
    )


def _typed_ref(value: Any, label: str, *, schema_version: int, kind: str) -> dict[str, Any]:
    _require(
        type(value) is dict
        and set(value) == {
            "artifact_schema_version", "artifact_kind", "descriptor",
            "content_identity_sha256",
        }
        and value.get("artifact_schema_version") == schema_version
        and value.get("artifact_kind") == kind,
        f"{label} typed reference drifted",
    )
    artifact = _artifact(
        {
            "descriptor": value.get("descriptor"),
            "content_identity_sha256": value.get("content_identity_sha256"),
        },
        label,
        semantic_file_hash=False,
    )
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": kind,
        **artifact,
    }


def _validate_runtime_authority(
    value: Any, *, expected_sha256: str, coordinate: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _RUNTIME_AUTHORITY_FIELDS,
        "runtime authority v2 fields drifted",
    )
    _require(
        value.get("schema_version") == 2
        and value.get("artifact_kind") == RUNTIME_AUTHORITY_KIND,
        "runtime authority v2 header drifted",
    )
    observed_coordinate = value.get("coordinate")
    expected_coordinate = {
        field: coordinate[field]
        for field in ("system", "policy", "topology_kind", "codec")
    }
    _require(
        type(observed_coordinate) is dict
        and observed_coordinate == expected_coordinate,
        "runtime authority v2 coordinate drifted",
    )
    identity = _sha(value.get("authority_sha256"), "runtime authority v2")
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "authority_sha256"}
    _require(
        identity == _canonical_sha(unsigned)
        == _sha(expected_sha256, "expected runtime authority v2"),
        "runtime authority v2 self/request pin drifted",
    )
    return copy.deepcopy(value)


def _load_validator_module(path: Path, source: bytes) -> types.ModuleType:
    try:
        text = source.decode("utf-8")
        code = compile(text, str(path), "exec", dont_inherit=True, optimize=2)
        module = types.ModuleType("_vast_publication_q4_evidence_validator_v4")
        module.__file__ = str(path)
        exec(code, module.__dict__)
    except Exception as error:
        raise PublicationQ4EvidenceRunnerV4Error(
            f"validator implementation could not be loaded: {error}"
        ) from error
    for name in (
        "validate_publication_q4_evidence_v4",
        "validate_publication_q4_evidence_validation_result_v4",
    ):
        _require(callable(getattr(module, name, None)), f"validator API {name} is missing")
    return module


class _ReadOnlyNetworkFence:
    def __enter__(self) -> "_ReadOnlyNetworkFence":
        class _DeniedTextOutput:
            encoding = "ascii"
            errors = "strict"

            @staticmethod
            def write(_value: Any) -> int:
                raise PublicationQ4EvidenceRunnerV4Error(
                    "validator stdout/stderr writes denied"
                )

            @staticmethod
            def flush() -> None:
                return None

        self._open = builtins.open
        self._io_open = io.open
        self._os_open = os.open
        self._socket = socket.socket
        self._create_connection = socket.create_connection
        self._popen = subprocess.Popen
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        self._os_mutations = {
            name: getattr(os, name)
            for name in (
                "write", "pwrite", "truncate", "ftruncate", "unlink",
                "remove", "rename", "replace", "renames", "mkdir",
                "makedirs", "rmdir", "removedirs", "link", "symlink",
                "chmod", "fchmod", "lchmod", "chown", "fchown", "lchown",
                "utime", "mknod", "mkfifo",
            )
            if hasattr(os, name)
        }
        self._socket_mutations = {
            name: getattr(socket, name)
            for name in (
                "socket", "socketpair", "fromfd", "fromshare",
                "create_connection", "create_server",
            )
            if hasattr(socket, name)
        }
        self._os_processes = {
            name: getattr(os, name)
            for name in (
                "system", "popen", "fork", "forkpty", "posix_spawn",
                "posix_spawnp", "execl", "execle", "execlp", "execlpe",
                "execv", "execve", "execvp", "execvpe", "spawnl",
                "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve",
                "spawnvp", "spawnvpe", "startfile", "kill",
            )
            if hasattr(os, name)
        }
        self._subprocess_processes = {
            name: getattr(subprocess, name)
            for name in (
                "Popen", "run", "call", "check_call", "check_output",
                "getoutput", "getstatusoutput",
            )
            if hasattr(subprocess, name)
        }

        def checked_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            _require(not any(flag in mode for flag in "wax+"), "filesystem write denied")
            return self._open(file, mode, *args, **kwargs)

        def checked_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            denied = (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
                | getattr(os, "O_APPEND", 0)
            )
            _require(flags & denied == 0, "filesystem write denied")
            return self._os_open(path, flags, *args, **kwargs)

        def denied(*_args: Any, **_kwargs: Any) -> Any:
            raise PublicationQ4EvidenceRunnerV4Error("network/process creation denied")

        builtins.open = checked_open
        io.open = checked_open
        os.open = checked_os_open
        for name in self._os_mutations:
            setattr(os, name, denied)
        for name in self._socket_mutations:
            setattr(socket, name, denied)
        for name in self._os_processes:
            setattr(os, name, denied)
        for name in self._subprocess_processes:
            setattr(subprocess, name, denied)
        sys.stdout = _DeniedTextOutput()
        sys.stderr = _DeniedTextOutput()
        return self

    def __exit__(self, *_exc: Any) -> None:
        builtins.open = self._open
        io.open = self._io_open
        os.open = self._os_open
        for name, function in self._os_mutations.items():
            setattr(os, name, function)
        for name, function in self._socket_mutations.items():
            setattr(socket, name, function)
        for name, function in self._os_processes.items():
            setattr(os, name, function)
        for name, function in self._subprocess_processes.items():
            setattr(subprocess, name, function)
        sys.stdout = self._stdout
        sys.stderr = self._stderr


def _parse_argv(argv: Sequence[str]) -> dict[str, str]:
    _require(
        type(argv) in {list, tuple} and len(argv) == len(_OPTION_NAMES) * 2,
        "runner argv arity drifted",
    )
    values: dict[str, str] = {}
    for position, option in enumerate(_OPTION_NAMES):
        observed = argv[position * 2]
        value = argv[position * 2 + 1]
        _require(observed == option, f"runner argv option[{position}] drifted")
        _require(type(value) is str and bool(value), f"runner argv value[{position}] is empty")
        values[option] = value
    return values


def run_publication_q4_evidence_validation_v4(argv: Sequence[str]) -> dict[str, Any]:
    """Execute one read-only validation from the exact authority argv payload."""
    arguments = _parse_argv(argv)
    root = _project_root(arguments["--project-root"])

    runner_file_descriptor = _descriptor_for_absolute(
        root, arguments["--runner-authority"],
        arguments["--runner-authority-file-sha256"], "runner authority",
    )
    runner_payload = _read_physical(root, runner_file_descriptor, "runner authority")
    runner_authority = _validate_runner_authority(
        _load_canonical_json(runner_payload, "runner authority"),
        expected_sha256=arguments["--runner-authority-sha256"],
    )
    _verify_runner_closure(
        root=root, authority=runner_authority,
        authority_file_descriptor=runner_file_descriptor,
    )

    validator_file_descriptor = _descriptor_for_absolute(
        root, arguments["--validator-authority"],
        arguments["--validator-authority-file-sha256"], "validator authority",
    )
    validator_payload = _read_physical(
        root, validator_file_descriptor, "validator authority"
    )
    validator_authority = _validate_validator_authority(
        _load_canonical_json(validator_payload, "validator authority"),
        expected_sha256=arguments["--validator-authority-sha256"],
    )
    _require(
        runner_authority["validation_protocol_identity_sha256"]
        == validator_authority["validation_protocol_identity_sha256"]
        and runner_authority["input_schema_identity_sha256"]
        == validator_authority["validation_input_schema_identity_sha256"]
        and runner_authority["output_schema_identity_sha256"]
        == validator_authority["validation_output_schema_identity_sha256"],
        "runner/validator protocol or wire-schema identity drifted",
    )
    implementation = validator_authority["_implementation"]
    _require(
        implementation in runner_authority["runtime_leaves"],
        "validator implementation is outside the pinned runner closure",
    )
    validator_source = _read_physical(
        root, implementation["descriptor"], "validator implementation"
    )
    validator_path = _path_under_root(
        root, implementation["descriptor"]["path"], "validator implementation"
    )
    request_file_descriptor = _descriptor_for_absolute(
        root, arguments["--request"], arguments["--request-file-sha256"],
        "validation request",
    )
    request_payload = _read_physical(root, request_file_descriptor, "validation request")
    request = _load_canonical_json(request_payload, "validation request")
    request_sha = _sha(arguments["--request-sha256"], "expected validation request")
    _require(
        request.get("schema_version") == 2
        and request.get("artifact_kind") == REQUEST_KIND
        and request.get("request_sha256") == request_sha,
        "validation request external identity drifted",
    )
    runner_ref = _typed_ref(
        request.get("runner_authority_ref"), "request runner authority",
        schema_version=1, kind=RUNNER_AUTHORITY_KIND,
    )
    validator_ref = _typed_ref(
        request.get("q4_validator_authority_ref"), "request validator authority",
        schema_version=1, kind=VALIDATOR_AUTHORITY_KIND,
    )
    _require(
        runner_ref["descriptor"] == runner_file_descriptor
        and runner_ref["content_identity_sha256"]
        == runner_authority["runner_authority_sha256"]
        and validator_ref["descriptor"] == validator_file_descriptor
        and validator_ref["content_identity_sha256"]
        == validator_authority["authority_sha256"],
        "request authority reference drifted",
    )

    raw_ref = _artifact(request.get("raw_evidence_ref"), "raw evidence", semantic_file_hash=False)
    raw_payload = _read_physical(root, raw_ref["descriptor"], "raw evidence manifest")
    raw_manifest = _load_canonical_json(raw_payload, "raw evidence manifest")
    _require(
        raw_manifest.get("schema_version") == 4
        and raw_manifest.get("artifact_kind") == RAW_MANIFEST_KIND
        and raw_manifest.get("raw_evidence_manifest_sha256")
        == raw_ref["content_identity_sha256"],
        "raw evidence manifest semantic reference drifted",
    )

    runtime_ref = _typed_ref(
        request.get("runtime_authority_ref"), "request runtime authority",
        schema_version=2, kind=RUNTIME_AUTHORITY_KIND,
    )
    runtime_payload = _read_physical(
        root, runtime_ref["descriptor"], "runtime authority v2"
    )
    coordinate = {
        field: request.get(field)
        for field in (
            "system", "codec", "topology_kind", "policy", "deadline_ms",
            "cell_index",
        )
    }
    _validate_runtime_authority(
        _load_canonical_json(runtime_payload, "runtime authority v2"),
        expected_sha256=runtime_ref["content_identity_sha256"],
        coordinate=coordinate,
    )

    # Every remaining formal parent is physically present and bound to the
    # semantic pin in the request.  Its detailed schema was validated before
    # the externally pinned request was committed; here we re-establish the
    # immutable physical closure and the node's own identity.
    for ref_field, pin_field, identity_field, label in (
        ("context_ref", "context_sha256", "context_sha256", "system context"),
        ("q4_input_ref", "q4_input_sha256", "input_index_sha256", "Q4 input"),
        (
            "publication_launcher_invocation_v3_ref",
            "publication_launcher_invocation_v3_sha256",
            "invocation_sha256", "publication launcher invocation v3",
        ),
        (
            "launcher_runtime_authority_ref", "launcher_runtime_authority_sha256",
            "authority_sha256", "launcher runtime authority",
        ),
    ):
        reference = request.get(ref_field)
        _require(type(reference) is dict, f"request {label} reference is missing")
        descriptor = _descriptor(reference.get("descriptor"), label)
        parent = _load_canonical_json(_read_physical(root, descriptor, label), label)
        pin = _sha(request.get(pin_field), f"request {label}")
        _require(
            parent.get("schema_version") == reference.get("artifact_schema_version")
            and parent.get("artifact_kind") == reference.get("artifact_kind")
            and reference.get("content_identity_sha256") == pin
            and parent.get(identity_field) == pin,
            f"request {label} physical semantic identity drifted",
        )

    context_ref = request["context_ref"]
    context = _load_canonical_json(
        _read_physical(root, context_ref["descriptor"], "system context"),
        "system context",
    )
    for field in (
        "q4_input_ref", "q4_input_sha256", "q4_validator_authority_ref",
        "q4_validator_authority_sha256", "runner_authority_ref",
        "runner_authority_sha256", "publication_launcher_invocation_v3_ref",
        "publication_launcher_invocation_v3_sha256",
        "runner_invocation_identity_sha256",
        "runtime_binding_identity_v4_sha256", "runtime_authority_set_sha256",
        "launcher_runtime_authority_ref", "launcher_runtime_authority_sha256",
    ):
        _require(context.get(field) == request.get(field), f"request/context {field} drifted")
    _require(context.get("system") == coordinate["system"], "request/context system drifted")

    with _ReadOnlyNetworkFence():
        validator_module = _load_validator_module(validator_path, validator_source)
        result = validator_module.validate_publication_q4_evidence_v4(
            project_root=root,
            validation_request=request,
            raw_evidence_manifest=raw_manifest,
            raw_evidence_manifest_descriptor=raw_ref["descriptor"],
            expected_request_sha256=request_sha,
            expected_runner_authority_sha256=runner_authority[
                "runner_authority_sha256"
            ],
            expected_validator_authority_sha256=validator_authority[
                "authority_sha256"
            ],
        )
        result = validator_module.validate_publication_q4_evidence_validation_result_v4(
            result,
            expected_coordinate=coordinate,
            expected_request_sha256=request_sha,
            expected_raw_evidence_manifest_sha256=raw_ref[
                "content_identity_sha256"
            ],
        )
    _require(
        len(_canonical_bytes(result, newline=True)) <= MAX_STDOUT_BYTES,
        "validation result exceeds stdout bound",
    )
    return copy.deepcopy(result)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run_publication_q4_evidence_validation_v4(
            list(sys.argv[1:] if argv is None else argv)
        )
        payload = _canonical_bytes(result, newline=True)
        _require(len(payload) <= MAX_STDOUT_BYTES, "stdout exceeds bound")
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
        return 0
    except PublicationQ4EvidenceRunnerV4Error as error:
        diagnostic = f"Q4 evidence validation rejected: {error}\n".encode(
            "ascii", errors="replace"
        )[:MAX_DIAGNOSTIC_BYTES]
        sys.stderr.buffer.write(diagnostic)
        sys.stderr.buffer.flush()
        return EXIT_USAGE if "argv" in str(error).lower() else EXIT_REJECTED
    except Exception as error:
        diagnostic = f"Q4 evidence validation rejected: {type(error).__name__}: {error}\n".encode(
            "ascii", errors="replace"
        )[:MAX_DIAGNOSTIC_BYTES]
        sys.stderr.buffer.write(diagnostic)
        sys.stderr.buffer.flush()
        return EXIT_REJECTED


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_REJECTED", "EXIT_USAGE", "PublicationQ4EvidenceRunnerV4Error",
    "main", "run_publication_q4_evidence_validation_v4",
]
