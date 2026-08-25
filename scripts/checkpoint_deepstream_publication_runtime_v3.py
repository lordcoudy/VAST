#!/usr/bin/env python3
"""Exact-input DeepStream container runtime for publication ABI v3.

The parent launcher owns the publication namespace. This module holds every
host input by file descriptor, proves one immutable local image by its Docker
image ID and complete inspect payload, materializes only those held bytes into
a private read-only container mount, and maps only caller-declared evidence
back to the parent namespace.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

sys.dont_write_bytecode = True

from checkpoint_publication_launcher_adapter_v3 import (
    NativePublicationOutcomeV3,
    NativePublicationPermanentErrorV3,
    NativePublicationRequestV3,
    NativePublicationTransientErrorV3,
)
RUNTIME_INPUT_KEY = "deepstream_publication_runtime_v3"
RUNTIME_INPUT_KIND = "vast_deepstream_publication_runtime_inputs_v3"
TERMINAL_STATUS_KIND = "vast_deepstream_publication_terminal_status_v3"
RUNTIME_FIELDS = {
    "schema_version", "artifact_kind", "files", "source_files",
    "model_files", "support_files", "static_hybrid_map", "container_image",
    "container_engine_socket", "endpoint_sockets", "scratch_root",
    "ready_timeout_s", "drain_timeout_s", "start_lead_ms",
    "container_timeout_s", "defer_full_resource_acceptance",
    "evidence_mapping",
}
FILE_ROLES = {
    "container_engine", "experiments_config", "datasets_config",
    "adapter_config", "analytics_model_manifest",
    "policy_capability_manifest", "policy_calibration",
}
EXECUTABLE_ROLES = {"container_engine"}
DESCRIPTOR_FIELDS = {"path", "container_path", "size_bytes", "sha256"}
SOCKET_FIELDS = {"path", "device", "inode", "owner_uid", "owner_gid"}
ENDPOINT_SOCKET_FIELDS = {
    "host_path", "container_path", "device", "inode", "owner_uid",
    "owner_gid",
}
IMAGE_FIELDS = {
    "image_id", "repository_digest", "inspect_sha256", "coordinator_path",
    "required_labels",
}
REQUIRED_IMAGE_LABELS = {
    "org.vast.component": "deepstream-checkpoint-native-sdk-runtime",
    "org.vast.publication-runtime-abi": "3",
}
EXPECTED_COORDINATOR_PATH = "/usr/local/bin/vast_deepstream_publication_runtime_v3"
DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
POLICIES = frozenset({
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
})
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REPOSITORY_DIGEST_RE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
)
CONTAINER_INPUT_ROOT = PurePosixPath("/opt/vast/input")
CONTAINER_OUTPUT_ROOT = "/opt/vast/output"
MAX_FILES = 128
MAX_ENDPOINT_SOCKETS = 32
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
PARENT_FILES = {
    "backend_publication_arm_contract.json",
    "backend_publication_launch_fence.json",
    "backend_publication_launcher_stdout.log",
    "backend_publication_launcher_stderr.log",
    "backend_publication_launcher_result.json",
    "backend_publication_output_receipt.json",
}


class DeepStreamPublicationRuntimeV3Error(NativePublicationPermanentErrorV3):
    """The exact DeepStream container boundary is invalid or changed."""


def _fail(blocker: str) -> None:
    raise DeepStreamPublicationRuntimeV3Error(blocker)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail("deepstream_container_image_inspect_payload_invalid")


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _is_link(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _fd_hash(fd: int) -> tuple[int, str]:
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        size = 0
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
        os.lseek(fd, 0, os.SEEK_SET)
        return size, digest.hexdigest()
    except OSError:
        _fail("deepstream_runtime_input_descriptor_unreadable")


@dataclass(frozen=True)
class _Pin:
    role: str
    path: Path
    container_path: str
    fd: int
    snapshot: tuple[int, ...]
    size: int
    sha256: str

    @property
    def proc_path(self) -> str:
        return f"/proc/self/fd/{self.fd}"


@dataclass
class _Pins:
    roles: dict[str, _Pin]
    sources: tuple[_Pin, ...]
    models: tuple[_Pin, ...]
    support: tuple[_Pin, ...]
    static_map: _Pin | None

    @property
    def all(self) -> tuple[_Pin, ...]:
        values = [*self.roles.values(), *self.sources, *self.models, *self.support]
        if self.static_map is not None:
            values.append(self.static_map)
        return tuple(values)

    @property
    def materialized(self) -> tuple[_Pin, ...]:
        return tuple(pin for pin in self.all if pin.role != "container_engine")

    def close(self) -> None:
        for pin in reversed(self.all):
            try:
                os.close(pin.fd)
            except OSError:
                pass


@dataclass(frozen=True)
class _Contract:
    raw: dict[str, Any]
    image: dict[str, Any]
    engine_socket: dict[str, Any]
    endpoint_sockets: tuple[dict[str, Any], ...]
    evidence_mapping: dict[str, str]


@dataclass(frozen=True)
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes


def _project_path(root: Path, raw: Any) -> Path:
    if (
        type(raw) is not str or not raw or len(raw) > 4096
        or "\\" in raw or "\x00" in raw
        or any(ord(char) < 0x20 for char in raw)
    ):
        _fail("deepstream_runtime_input_path_invalid")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute() or pure.as_posix() != raw
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail("deepstream_runtime_input_path_invalid")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        _fail("deepstream_runtime_input_path_escaped_project_root")
    if resolved != path:
        _fail("deepstream_runtime_input_path_alias_forbidden")
    return path


def _container_input_path(raw: Any) -> str:
    if (
        type(raw) is not str or not raw
        or len(raw.encode("utf-8")) > 4096
        or "\\" in raw or "\x00" in raw
        or any(ord(char) < 0x20 for char in raw)
    ):
        _fail("deepstream_container_input_path_invalid")
    pure = PurePosixPath(raw)
    try:
        relative = pure.relative_to(CONTAINER_INPUT_ROOT)
    except ValueError:
        _fail("deepstream_container_input_path_invalid")
    if (
        not pure.is_absolute() or pure.as_posix() != raw or not relative.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail("deepstream_container_input_path_invalid")
    return raw


def _open_pin(
    root: Path,
    role: str,
    value: Any,
    *,
    executable: bool = False,
) -> _Pin:
    if type(value) is not dict or set(value) != DESCRIPTOR_FIELDS:
        _fail("deepstream_runtime_file_descriptor_fields_drifted")
    size, digest = value.get("size_bytes"), value.get("sha256")
    if (
        type(size) is not int or size <= 0
        or type(digest) is not str or SHA_RE.fullmatch(digest) is None
    ):
        _fail("deepstream_runtime_file_descriptor_identity_invalid")
    path = _project_path(root, value.get("path"))
    container_path = _container_input_path(value.get("container_path"))
    fd = -1
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode) or _is_link(before)
            or int(before.st_nlink) != 1 or int(before.st_size) != size
            or (executable and not (int(before.st_mode) & 0o111))
        ):
            raise OSError("invalid")
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened, after = os.fstat(fd), path.lstat()
        observed_size, observed_hash = _fd_hash(fd)
        if (
            _snapshot(before) != _snapshot(opened)
            or _snapshot(opened) != _snapshot(after)
            or observed_size != size or observed_hash != digest
        ):
            raise OSError("changed")
    except OSError:
        if fd >= 0:
            os.close(fd)
        _fail("deepstream_runtime_file_descriptor_pin_failed")
    return _Pin(
        role, path, container_path, fd, _snapshot(after), size, digest,
    )


def _open_list(root: Path, role: str, value: Any) -> tuple[_Pin, ...]:
    if type(value) is not list or not value or len(value) > MAX_FILES:
        _fail(f"deepstream_runtime_{role}_descriptor_set_invalid")
    result: list[_Pin] = []
    try:
        for index, descriptor in enumerate(value):
            result.append(_open_pin(root, f"{role}:{index}", descriptor))
        return tuple(result)
    except BaseException:
        for pin in result:
            os.close(pin.fd)
        raise


def _absolute_socket_path(raw: Any, blocker: str) -> str:
    if (
        type(raw) is not str or not raw.startswith("/") or "\\" in raw
        or "\x00" in raw or "," in raw or len(os.fsencode(raw)) >= 108
        or os.path.normpath(raw) != raw
    ):
        _fail(blocker)
    try:
        resolved = str(Path(raw).resolve(strict=True))
    except (OSError, RuntimeError):
        _fail(blocker)
    if resolved != raw:
        _fail(blocker)
    return raw


def _socket_binding(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != SOCKET_FIELDS:
        _fail("deepstream_container_engine_socket_binding_invalid")
    path = _absolute_socket_path(
        value.get("path"), "deepstream_container_engine_socket_binding_invalid"
    )
    if any(
        type(value.get(field)) is not int or value[field] < 0
        for field in SOCKET_FIELDS - {"path"}
    ):
        _fail("deepstream_container_engine_socket_binding_invalid")
    result = {**value, "path": path}
    _require_socket(result, engine=True)
    return result


def _endpoint_binding(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != ENDPOINT_SOCKET_FIELDS:
        _fail("deepstream_endpoint_socket_binding_invalid")
    host = _absolute_socket_path(
        value.get("host_path"), "deepstream_endpoint_socket_binding_invalid"
    )
    target = value.get("container_path")
    if (
        type(target) is not str or not target.startswith("/run/vast/")
        or "\\" in target or "\x00" in target or "," in target
        or len(os.fsencode(target)) >= 108
        or PurePosixPath(target).as_posix() != target
        or any(part in {"", ".", ".."} for part in PurePosixPath(target).parts)
    ):
        _fail("deepstream_endpoint_socket_binding_invalid")
    if any(
        type(value.get(field)) is not int or value[field] < 0
        for field in ENDPOINT_SOCKET_FIELDS - {"host_path", "container_path"}
    ):
        _fail("deepstream_endpoint_socket_binding_invalid")
    result = {**value, "host_path": host}
    _require_socket(result, engine=False)
    return result


def _require_socket(value: Mapping[str, Any], *, engine: bool) -> None:
    path_key = "path" if engine else "host_path"
    blocker = (
        "deepstream_container_engine_socket_identity_changed"
        if engine else "deepstream_endpoint_socket_identity_changed"
    )
    try:
        info = os.lstat(str(value[path_key]))
    except OSError:
        _fail(blocker)
    if (
        not stat.S_ISSOCK(info.st_mode)
        or int(info.st_dev) != value["device"]
        or int(info.st_ino) != value["inode"]
        or int(info.st_uid) != value["owner_uid"]
        or int(info.st_gid) != value["owner_gid"]
    ):
        _fail(blocker)


def _positive(value: Any, blocker: str) -> float:
    if isinstance(value, bool):
        _fail(blocker)
    try:
        result = float(value)
    except (TypeError, ValueError):
        _fail(blocker)
    if not math.isfinite(result) or result <= 0:
        _fail(blocker)
    return result


def _validate_image(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != IMAGE_FIELDS:
        _fail("deepstream_container_image_contract_fields_drifted")
    image_id = value.get("image_id")
    repository_digest = value.get("repository_digest")
    labels = value.get("required_labels")
    if (
        type(image_id) is not str or IMAGE_ID_RE.fullmatch(image_id) is None
        or (
            repository_digest is not None
            and (
                type(repository_digest) is not str
                or REPOSITORY_DIGEST_RE.fullmatch(repository_digest) is None
            )
        )
        or type(value.get("inspect_sha256")) is not str
        or SHA_RE.fullmatch(value["inspect_sha256"]) is None
        or value.get("coordinator_path") != EXPECTED_COORDINATOR_PATH
        or labels != REQUIRED_IMAGE_LABELS
    ):
        _fail("deepstream_container_image_contract_invalid")
    return dict(value)


def _validate_dataset(request: NativePublicationRequestV3, source_values: Any) -> None:
    runtime = request.runtime_inputs
    dataset = runtime.get("dataset")
    codec = runtime.get("codec")
    if (
        type(dataset) is not dict or codec not in DATASET_BY_CODEC
        or dataset.get("name") != DATASET_BY_CODEC[codec]
        or dataset.get("codec_variant") != codec
        or dataset.get("logical_stream_instances") != 6
        or runtime.get("streams") != 6
    ):
        _fail("deepstream_frozen_kpp_dataset_binding_invalid")
    streams = dataset.get("streams")
    if (
        type(streams) is not list or len(streams) != 6
        or {value.get("stream_id") for value in streams if type(value) is dict}
        != set(range(6))
        or any(
            type(value) is not dict or value.get("codec_name") != codec
            or type(value.get("sha256")) is not str
            or SHA_RE.fullmatch(value["sha256"]) is None
            for value in streams
        )
    ):
        _fail("deepstream_frozen_kpp_stream_binding_invalid")
    if type(source_values) is not list:
        _fail("deepstream_runtime_source_files_descriptor_set_invalid")
    source_hashes = {
        value.get("sha256") for value in source_values if type(value) is dict
    }
    if (
        len(source_values) != len(source_hashes)
        or source_hashes != {value["sha256"] for value in streams}
    ):
        _fail("deepstream_frozen_kpp_source_descriptor_binding_invalid")


def _validate_contract(request: NativePublicationRequestV3) -> _Contract:
    if os.name != "posix" or not Path("/proc/self/fd").is_dir():
        _fail("deepstream_publication_runtime_requires_linux_procfs")
    runtime = request.runtime_inputs
    dataset = runtime.get("dataset")
    value = dataset.get(RUNTIME_INPUT_KEY) if isinstance(dataset, Mapping) else None
    if type(value) is not dict:
        _fail("deepstream_runtime_input_contract_missing")
    if set(value) != RUNTIME_FIELDS:
        _fail("deepstream_runtime_input_contract_fields_drifted")
    if value.get("schema_version") != 3 or value.get("artifact_kind") != RUNTIME_INPUT_KIND:
        _fail("deepstream_runtime_input_contract_identity_invalid")
    files = value.get("files")
    if type(files) is not dict or set(files) != FILE_ROLES:
        _fail("deepstream_runtime_file_role_set_drifted")
    if runtime.get("system") != request.system or request.system != "deepstream":
        _fail("deepstream_runtime_system_binding_invalid")
    if (
        runtime.get("scenario") != request.scenario
        or runtime.get("topology_kind") != request.topology_kind
    ):
        _fail("deepstream_runtime_topology_binding_invalid")
    if runtime.get("policy") not in POLICIES:
        _fail("deepstream_runtime_policy_binding_invalid")
    _validate_dataset(request, value.get("source_files"))
    if type(value.get("defer_full_resource_acceptance")) is not bool:
        _fail("deepstream_resource_acceptance_mode_invalid")
    if (
        type(value.get("start_lead_ms")) is not int
        or not 0 <= value["start_lead_ms"] <= 60_000
    ):
        _fail("deepstream_start_lead_contract_invalid")
    _positive(value.get("ready_timeout_s"), "deepstream_ready_timeout_contract_invalid")
    _positive(value.get("drain_timeout_s"), "deepstream_drain_timeout_contract_invalid")
    _positive(value.get("container_timeout_s"), "deepstream_container_timeout_contract_invalid")
    scratch = value.get("scratch_root")
    if (
        type(scratch) is not str or not scratch.startswith("/") or "," in scratch
        or os.path.normpath(scratch) != scratch
    ):
        _fail("deepstream_runtime_scratch_root_invalid")
    try:
        scratch_path = Path(scratch)
        info = scratch_path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode) or _is_link(info)
            or scratch_path.resolve(strict=True) != scratch_path
        ):
            raise OSError("invalid")
    except (OSError, RuntimeError):
        _fail("deepstream_runtime_scratch_root_invalid")
    mapping = value.get("evidence_mapping")
    if (
        type(mapping) is not dict
        or set(mapping) != set(request.launcher_evidence_files)
        or len(set(mapping.values())) != len(mapping)
        or any(
            type(source) is not str or not source or Path(source).name != source
            or source in PARENT_FILES
            for source in mapping.values()
        )
    ):
        _fail("deepstream_child_evidence_mapping_invalid")
    static_map = value.get("static_hybrid_map")
    if (runtime["policy"] == "static_hybrid") != (type(static_map) is dict):
        _fail("deepstream_static_hybrid_map_binding_invalid")
    endpoints = value.get("endpoint_sockets")
    if (
        type(endpoints) is not list or not endpoints
        or len(endpoints) > MAX_ENDPOINT_SOCKETS
    ):
        _fail("deepstream_endpoint_socket_set_invalid")
    checked_endpoints = tuple(_endpoint_binding(endpoint) for endpoint in endpoints)
    if (
        len({item["host_path"] for item in checked_endpoints}) != len(checked_endpoints)
        or len({item["container_path"] for item in checked_endpoints}) != len(checked_endpoints)
    ):
        _fail("deepstream_endpoint_socket_set_invalid")
    return _Contract(
        raw=dict(value),
        image=_validate_image(value["container_image"]),
        engine_socket=_socket_binding(value["container_engine_socket"]),
        endpoint_sockets=checked_endpoints,
        evidence_mapping=dict(mapping),
    )


def _open_pins(request: NativePublicationRequestV3, contract: _Contract) -> _Pins:
    root, raw = request.project_root, contract.raw
    roles: dict[str, _Pin] = {}
    sources: tuple[_Pin, ...] = ()
    models: tuple[_Pin, ...] = ()
    support: tuple[_Pin, ...] = ()
    static_map: _Pin | None = None
    try:
        for role in sorted(FILE_ROLES):
            roles[role] = _open_pin(
                root, role, raw["files"][role],
                executable=role in EXECUTABLE_ROLES,
            )
        sources = _open_list(root, "source_files", raw["source_files"])
        models = _open_list(root, "model_files", raw["model_files"])
        support = _open_list(root, "support_files", raw["support_files"])
        if raw["static_hybrid_map"] is not None:
            static_map = _open_pin(root, "static_hybrid_map", raw["static_hybrid_map"])
        pins = _Pins(roles, sources, models, support, static_map)
        paths = [pin.path for pin in pins.all]
        targets = [pin.container_path for pin in pins.materialized]
        if (
            len(paths) != len(set(paths)) or len(targets) != len(set(targets))
            or any(
                len(values) != len({pin.sha256 for pin in values})
                for values in (sources, models, support)
            )
            or len(paths) > MAX_FILES
        ):
            _fail("deepstream_runtime_descriptor_path_set_invalid")
        expected_source_hashes = {
            stream["sha256"] for stream in request.runtime_inputs["dataset"]["streams"]
        }
        if {pin.sha256 for pin in sources} != expected_source_hashes:
            _fail("deepstream_frozen_kpp_source_descriptor_binding_invalid")
        return pins
    except BaseException:
        values = [*roles.values(), *sources, *models, *support]
        if static_map is not None:
            values.append(static_map)
        for pin in values:
            try:
                os.close(pin.fd)
            except OSError:
                pass
        raise


def _require_pins_unchanged(pins: _Pins) -> None:
    for pin in pins.all:
        try:
            path_info, fd_info = pin.path.lstat(), os.fstat(pin.fd)
            size, digest = _fd_hash(pin.fd)
        except OSError:
            _fail("deepstream_runtime_input_path_identity_changed")
        if (
            _snapshot(path_info) != pin.snapshot or _snapshot(fd_info) != pin.snapshot
            or _is_link(path_info) or not stat.S_ISREG(path_info.st_mode)
            or int(path_info.st_nlink) != 1 or size != pin.size
            or digest != pin.sha256
        ):
            _fail("deepstream_runtime_input_path_identity_changed")


def _require_sockets_unchanged(contract: _Contract) -> None:
    _require_socket(contract.engine_socket, engine=True)
    for endpoint in contract.endpoint_sockets:
        _require_socket(endpoint, engine=False)


def _invoke_engine(
    engine: _Pin,
    engine_socket: Mapping[str, Any],
    argv: tuple[str, ...],
    timeout_s: float,
) -> _Completed:
    """Run the held Docker CLI with bounded binary captures and no shell."""

    if not argv or any(type(value) is not str or "\x00" in value for value in argv):
        _fail("deepstream_container_engine_argv_invalid")
    environment = {
        "DOCKER_HOST": f"unix://{engine_socket['path']}",
        "LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin",
    }
    try:
        process = subprocess.Popen(
            [engine.proc_path, *argv], executable=engine.proc_path, cwd="/",
            env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True, pass_fds=(engine.fd,),
            start_new_session=True,
        )
    except OSError as error:
        raise NativePublicationTransientErrorV3(
            "deepstream_container_engine_temporarily_unavailable"
        ) from error
    captures = {"stdout": bytearray(), "stderr": bytearray()}
    exceeded = threading.Event()

    def reader(name: str, stream: Any) -> None:
        observed = 0
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return
            observed += len(chunk)
            if observed > MAX_CAPTURE_BYTES:
                exceeded.set()
            target = captures[name]
            if len(target) < MAX_CAPTURE_BYTES:
                target.extend(chunk[: MAX_CAPTURE_BYTES - len(target)])

    threads = [
        threading.Thread(target=reader, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=reader, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout_s
    timed_out = False
    while process.poll() is None:
        if exceeded.is_set() or time.monotonic() >= deadline:
            timed_out = not exceeded.is_set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            break
        time.sleep(0.01)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    for thread in threads:
        thread.join(timeout=10)
    if any(thread.is_alive() for thread in threads):
        _fail("deepstream_container_capture_drain_failed")
    if exceeded.is_set():
        _fail("deepstream_container_capture_limit_exceeded")
    if timed_out:
        raise NativePublicationTransientErrorV3(
            "deepstream_container_execution_timed_out"
        )
    return _Completed(
        int(process.returncode), bytes(captures["stdout"]), bytes(captures["stderr"])
    )


def _inspect_image(pins: _Pins, contract: _Contract) -> dict[str, Any]:
    completed = _invoke_engine(
        pins.roles["container_engine"], contract.engine_socket,
        ("image", "inspect", str(contract.image["image_id"])), 60.0,
    )
    if completed.returncode != 0 or completed.stderr:
        _fail("deepstream_container_image_inspect_failed")
    try:
        decoded = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeError):
        _fail("deepstream_container_image_inspect_payload_invalid")
    if type(decoded) is not list or len(decoded) != 1 or type(decoded[0]) is not dict:
        _fail("deepstream_container_image_inspect_payload_invalid")
    value = decoded[0]
    config = value.get("Config")
    repository_digest = contract.image["repository_digest"]
    if (
        hashlib.sha256(_canonical(value)).hexdigest()
        != contract.image["inspect_sha256"]
        or value.get("Id") != contract.image["image_id"]
        or value.get("Os") != "linux" or value.get("Architecture") != "amd64"
        or type(config) is not dict
        or config.get("Entrypoint") != [contract.image["coordinator_path"]]
        or type(config.get("Labels")) is not dict
        or any(
            config["Labels"].get(key) != expected
            for key, expected in contract.image["required_labels"].items()
        )
        or (
            repository_digest is not None
            and repository_digest not in (value.get("RepoDigests") or [])
        )
    ):
        _fail("deepstream_container_image_identity_changed")
    return value


def _copy_pin(pin: _Pin, input_root: Path) -> None:
    relative = PurePosixPath(pin.container_path).relative_to(CONTAINER_INPUT_ROOT)
    target = input_root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = -1
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
        os.lseek(pin.fd, 0, os.SEEK_SET)
        while True:
            chunk = os.read(pin.fd, 1024 * 1024)
            if not chunk:
                break
            offset = 0
            while offset < len(chunk):
                written = os.write(fd, chunk[offset:])
                if written <= 0:
                    raise OSError("short write")
                offset += written
        os.fsync(fd)
        os.lseek(pin.fd, 0, os.SEEK_SET)
    except OSError:
        _fail("deepstream_runtime_input_materialization_failed")
    finally:
        if fd >= 0:
            os.close(fd)
    if (
        target.stat().st_size != pin.size
        or hashlib.sha256(target.read_bytes()).hexdigest() != pin.sha256
    ):
        _fail("deepstream_runtime_input_materialization_failed")
    target.chmod(0o400)


def _materialize_inputs(pins: _Pins, input_root: Path) -> None:
    input_root.mkdir(mode=0o700)
    for pin in pins.materialized:
        _copy_pin(pin, input_root)


def _mount(source: str, target: str, *, readonly: bool) -> tuple[str, str]:
    if "," in source or "," in target:
        _fail("deepstream_container_mount_path_invalid")
    suffix = ",readonly" if readonly else ""
    return "--mount", f"type=bind,src={source},dst={target}{suffix}"


def _container_argv(
    request: NativePublicationRequestV3,
    contract: _Contract,
    pins: _Pins,
    input_root: Path,
    runtime_output: Path,
) -> tuple[str, ...]:
    runtime = request.runtime_inputs
    files = pins.roles
    arguments: list[str] = [
        "run", "--rm", "--gpus", "all", "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt",
        "no-new-privileges:true", "--pids-limit", "512",
        *_mount(str(input_root), str(CONTAINER_INPUT_ROOT), readonly=True),
        *_mount(str(runtime_output), CONTAINER_OUTPUT_ROOT, readonly=False),
    ]
    for endpoint in contract.endpoint_sockets:
        arguments.extend(
            _mount(
                str(endpoint["host_path"]), str(endpoint["container_path"]),
                readonly=True,
            )
        )
    arguments.extend(
        [
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=1073741824",
            str(contract.image["image_id"]),
            "--config", files["experiments_config"].container_path,
            "--datasets", files["datasets_config"].container_path,
            "--adapter-config", files["adapter_config"].container_path,
            "--analytics-model-manifest",
            files["analytics_model_manifest"].container_path,
            "--policy-capability-manifest",
            files["policy_capability_manifest"].container_path,
            "--policy-calibration", files["policy_calibration"].container_path,
            "--scenario", request.scenario,
            "--topology-kind", request.topology_kind,
            "--codec", str(runtime["codec"]),
            "--policy", str(runtime["policy"]),
            "--deadline-ms", str(float(runtime["deadline_ms"])),
            "--output-dir", CONTAINER_OUTPUT_ROOT,
            "--run-id", request.run_id, "--arm-id", request.arm_id,
            "--duration", str(int(runtime["duration_s"])),
            "--ready-timeout", str(float(contract.raw["ready_timeout_s"])),
            "--drain-timeout", str(float(contract.raw["drain_timeout_s"])),
            "--start-lead-ms", str(int(contract.raw["start_lead_ms"])),
        ]
    )
    for source in pins.sources:
        arguments.extend(
            ("--source-binding", f"{source.sha256}={source.container_path}")
        )
    for model in pins.models:
        arguments.extend(
            ("--model-binding", f"{model.sha256}={model.container_path}")
        )
    for support in pins.support:
        arguments.extend(
            ("--support-binding", f"{support.sha256}={support.container_path}")
        )
    if pins.static_map is not None:
        arguments.extend(("--static-hybrid-map", pins.static_map.container_path))
    if contract.raw["defer_full_resource_acceptance"]:
        arguments.append("--defer-full-resource-acceptance")
    return tuple(arguments)


def _validate_status(
    payload: bytes,
    request: NativePublicationRequestV3,
    contract: _Contract,
) -> None:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError):
        _fail("deepstream_native_runtime_terminal_status_invalid")
    runtime = request.runtime_inputs
    acceptance = value.get("publication_acceptance") if type(value) is dict else None
    expected_status = (
        "pending_full_resource_validation"
        if contract.raw["defer_full_resource_acceptance"]
        else "accepted_native_checkpoint_arm"
    )
    if (
        type(value) is not dict
        or set(value) != {
            "schema_version", "artifact_kind", "run_id", "arm_id", "system",
            "scenario", "topology_kind", "codec", "policy", "deadline_ms",
            "accepted_benchmark_sidecars_written", "publication_blockers",
            "publication_acceptance",
        }
        or value.get("schema_version") != 3
        or value.get("artifact_kind") != TERMINAL_STATUS_KIND
        or value.get("run_id") != request.run_id
        or value.get("arm_id") != request.arm_id
        or value.get("system") != request.system
        or value.get("scenario") != request.scenario
        or value.get("topology_kind") != request.topology_kind
        or value.get("codec") != runtime["codec"]
        or value.get("policy") != runtime["policy"]
        or value.get("accepted_benchmark_sidecars_written") is not True
        or value.get("publication_blockers") != []
        or type(acceptance) is not dict
        or acceptance.get("status") != expected_status
        or acceptance.get("run_id") != request.run_id
        or acceptance.get("system") != request.system
        or acceptance.get("scenario") != request.scenario
        or acceptance.get("topology_kind") != request.topology_kind
        or acceptance.get("codec") != runtime["codec"]
        or acceptance.get("policy") != runtime["policy"]
    ):
        _fail("deepstream_native_runtime_terminal_status_invalid")
    try:
        matches = math.isclose(
            float(value.get("deadline_ms")), float(runtime["deadline_ms"]),
            rel_tol=0.0, abs_tol=1e-9,
        ) and math.isclose(
            float(acceptance.get("deadline_ms")),
            float(runtime["deadline_ms"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    except (TypeError, ValueError):
        matches = False
    if not matches:
        _fail("deepstream_native_runtime_terminal_status_invalid")


def _copy_evidence(
    runtime_output: Path,
    request: NativePublicationRequestV3,
    mapping: Mapping[str, str],
) -> None:
    for target_name in request.launcher_evidence_files:
        source = runtime_output / mapping[target_name]
        target = request.output_dir / target_name
        temporary = target.with_name(f".{target.name}.deepstream-v3.{os.getpid()}.tmp")
        source_fd = target_fd = -1
        try:
            before = source.lstat()
            if (
                not stat.S_ISREG(before.st_mode) or _is_link(before)
                or int(before.st_nlink) != 1
                or not 0 < int(before.st_size) <= MAX_EVIDENCE_BYTES
                or target.exists() or temporary.exists()
            ):
                raise OSError("invalid")
            source_fd = os.open(
                source, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            opened = os.fstat(source_fd)
            target_fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600,
            )
            observed = 0
            digest = hashlib.sha256()
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                observed += len(chunk)
                digest.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(target_fd, chunk[offset:])
                    if written <= 0:
                        raise OSError("short write")
                    offset += written
            os.fsync(target_fd)
            after = source.lstat()
            if (
                _snapshot(before) != _snapshot(opened)
                or _snapshot(opened) != _snapshot(after)
                or observed != int(after.st_size)
            ):
                raise OSError("changed")
            os.close(source_fd)
            os.close(target_fd)
            source_fd = target_fd = -1
            if target.exists():
                raise OSError("collision")
            os.replace(temporary, target)
        except OSError:
            _fail("deepstream_child_evidence_materialization_failed")
        finally:
            for fd in (source_fd, target_fd):
                if fd >= 0:
                    os.close(fd)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def run_checkpoint_deepstream_publication_runtime_v3(
    request: NativePublicationRequestV3,
) -> NativePublicationOutcomeV3:
    """Run one exact DeepStream image and map only declared evidence."""

    contract = _validate_contract(request)
    pins = _open_pins(request, contract)
    try:
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        _inspect_image(pins, contract)
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        with tempfile.TemporaryDirectory(
            prefix=f"vast-deepstream-v3-{request.arm_id}-",
            dir=str(contract.raw["scratch_root"]),
        ) as name:
            scratch = Path(name)
            if _is_link(scratch.lstat()):
                _fail("deepstream_runtime_scratch_custody_invalid")
            inputs = scratch / "inputs"
            runtime_output = scratch / "output"
            _materialize_inputs(pins, inputs)
            runtime_output.mkdir(mode=0o700)
            arguments = _container_argv(
                request, contract, pins, inputs, runtime_output
            )
            _require_pins_unchanged(pins)
            _require_sockets_unchanged(contract)
            completed = _invoke_engine(
                pins.roles["container_engine"], contract.engine_socket,
                arguments, float(contract.raw["container_timeout_s"]),
            )
            _require_pins_unchanged(pins)
            _require_sockets_unchanged(contract)
            _inspect_image(pins, contract)
            if completed.returncode == 75:
                raise NativePublicationTransientErrorV3(
                    "deepstream_native_runtime_incomplete_terminal_outcome"
                )
            if completed.returncode != 0 or completed.stderr:
                _fail("deepstream_native_runtime_failed")
            _validate_status(completed.stdout, request, contract)
            _copy_evidence(runtime_output, request, contract.evidence_mapping)
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        return NativePublicationOutcomeV3(exit_code=0)
    finally:
        pins.close()


__all__ = [
    "DeepStreamPublicationRuntimeV3Error",
    "RUNTIME_INPUT_KEY",
    "RUNTIME_INPUT_KIND",
    "TERMINAL_STATUS_KIND",
    "run_checkpoint_deepstream_publication_runtime_v3",
]
