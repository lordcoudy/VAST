#!/usr/bin/env python3
"""Exact-input Docker boundary for the custom GStreamer ABI-v3 launcher.

Every host input is held and hashed before Docker is contacted, copied from
that held descriptor into a private read-only input tree, and revalidated
before and after child execution.  Only the immutable image ID is executed.
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
from typing import Any, Callable

sys.dont_write_bytecode = True

from checkpoint_publication_launcher_adapter_v3 import (
    NativePublicationOutcomeV3,
    NativePublicationPermanentErrorV3,
    NativePublicationRequestV3,
    NativePublicationTransientErrorV3,
    deterministic_numeric_thread_environment_argv_v1,
)
from publication_child_evidence_materializer_v1 import (
    PublicationChildEvidenceMaterializerV1Error,
    materialize_publication_child_evidence_group_v1,
)
from publication_policy_contract import POLICIES as FROZEN_POLICIES

RUNTIME_INPUT_KEY = "gstreamer_custom_publication_runtime_v3"
RUNTIME_INPUT_KIND = "vast_gstreamer_custom_publication_runtime_inputs_v3"
EXPECTED_IMAGE_REFERENCE = 'vast/gstreamer-custom-publication-runtime-v3:materialized'
EXPECTED_IMAGE_ID = 'sha256:4d0355452b1a819ef56f442ebfeb9d0ab0c01ea393b03783d14145676c8e8b65'
EXPECTED_REPOSITORY_DIGEST = 'vast/gstreamer-custom-publication-runtime-v3@sha256:4d0355452b1a819ef56f442ebfeb9d0ab0c01ea393b03783d14145676c8e8b65'
EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256 = '6c9d555aea03d4baab561cb97ec6ae54238b364ad5d38c83981ace73a7c7a335'
EXPECTED_BASE_IMAGE_ID = 'sha256:f2579dc4c2977e2127c874273369c6c5ac7d99b4cb8e8c8a28e974a3a6195ca8'
EXPECTED_IMAGE_ENTRYPOINT = (
    "/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3"
)
EXPECTED_IMAGE_USER = "dlstreamer"
EXPECTED_IMAGE_LABELS = {'org.opencontainers.image.version': '24.04',
 'org.vast.base-image-id': 'sha256:f2579dc4c2977e2127c874273369c6c5ac7d99b4cb8e8c8a28e974a3a6195ca8',
 'org.vast.claim-status': 'deterministic-image-awaiting-exact-kpp-v3-gpu-pilots',
 'org.vast.component': 'gstreamer-custom-checkpoint-publication-runtime',
 'org.vast.native_probe.kind': 'openvino-dlstreamer',
 'org.vast.native_probe.source_sha': 'ae7ba6d2e74de0e5a84abe4cd187ff070606eeea7a9dcaf94e03e2958a984546',
 'org.vast.publication-runtime-abi': '3',
 'org.vast.runtime-dependency-set-sha256': '0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e',
 'org.vast.runtime-source-sha256': 'd85843a12b238f3d5e94f5060df343aa941100d8a6612ee6d29f48de17d0737e'}
EXPECTED_EMBEDDED_ARTIFACTS = {'/opt/vast/checkpoint/checkpoint_gstreamer_custom_container_coordinator_v3.py': '7f70138de1e87ab43dfab1e37674979c551dd24ee02fba205cd9905790b060c5',
 '/opt/vast/checkpoint/checkpoint_gstreamer_runtime.py': 'cd6800c43f9dff2214b5e54c7f7d8f7723f19fe9d751dc4c658a7e8ab6b3152a',
 '/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so': 'd36642c99d55fac7d834c75b500c7ffd086f022e671cb2b38aecaf38b8d0ad9f',
 '/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so': '9909f2b19adc3f7e82dcf8923a3e719f8546cd4e5126663deafdce04121d2258',
 '/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so': '04962e14523cc570ce1b24735e76334820ed730b5aee72beac0685a4704f9e45',
 '/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so': '797a9311f06cc60ce3768dfc2b3a191525a8577dd8ce2a4eca057aa4fcefdabf',
 '/opt/vast/runtime-source-allowlist.txt': 'dea819344804486529aeb32c0076690b42acfd8f5f861c2651d02b01c54608dc',
 '/opt/vast/share/gstreamer-registry.bin': '18b3fb289de3a7c101b12854beaabb38a8edb72c1ecaf6fc5deea39d307508bc',
 '/usr/local/bin/vast_checkpoint_source': '7501479ccb90dc1e322386126c372a7650f40e5c7b76bfb29f4495470bd185df',
 '/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3': '2f241d0fbf8e250d09f3dc8c6c97999910991c8649c44e56ee69d4f1cb38b8e7',
 '/usr/local/bin/vast_native_gst_probe': '2cd4c0f7b8c3ebb0449dae5d31144187bd0c5cf12acc8c73502cdee9d16c7ee8'}
DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
TOPOLOGY_BY_SCENARIO = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
REQUIRED_GSTREAMER_ELEMENTS = frozenset({
    "appsrc", "h264parse", "h265parse", "decodebin", "videoconvert",
    "tee", "vastanalyticsqueue", "gvadetect", "vastanalyticsterminal",
})
RUNTIME_FIELDS = {
    "schema_version", "artifact_kind", "files", "source_files", "model_files",
    "support_files", "static_hybrid_map", "container_image",
    "embedded_artifacts", "container_engine_socket", "endpoint_sockets",
    "device_binding", "preprocessing_contract_sha256", "detect_bin",
    "analytics_queue_max_buffers", "drain_timeout_s", "ready_timeout_s",
    "start_lead_ms", "container_timeout_s", "scratch_root",
    "defer_full_resource_acceptance", "evidence_mapping",
}
FILE_ROLES = {
    "container_engine", "device_probe", "experiments_config",
    "datasets_config", "analytics_model_manifest",
    "analytics_execution_manifest", "policy_capability_manifest",
    "policy_calibration",
}
EXECUTABLE_ROLES = {"container_engine"}
HOST_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
MOUNT_DESCRIPTOR_FIELDS = {
    "path", "container_path", "size_bytes", "sha256",
}
SOCKET_FIELDS = {"path", "device", "inode", "owner_uid", "owner_gid"}
ENDPOINT_FIELDS = SOCKET_FIELDS | {"container_path"}
IMAGE_FIELDS = {
    "image_id", "repository_digest", "inspect_projection_sha256",
    "base_image_id",
}
DEVICE_FIELDS = {
    "nvidia_decoder_gpu", "docker_gpus_request",
    "openvino_device_probe_sha256", "required_openvino_device_ids",
    "nvidia_gpu_counted_as_openvino_gpu", "analytics_resources",
}
NVIDIA_FIELDS = {"uuid", "name", "driver_version"}
ANALYTICS_RESOURCE_FIELDS = {"runtime", "device", "capability_sha256"}
POLICIES = frozenset(FROZEN_POLICIES)
CONTAINER_PROJECT_ROOT = PurePosixPath("/workspace/project")
# Six streams x four branches run 24 native workers plus their decoder and
# OpenVINO inference threads; the Sep25 CPU/H.264 cell peaked at 579 tasks.
# Match the Savant ceiling; this does not change CPU or memory allocation.
MAX_CONTAINER_PIDS = 4096
CONTAINER_OUTPUT_ROOT = "/opt/vast/output"
ANALYTICS_SOCKET_TARGET = "/run/vast/analytics-execution.sock"
MAX_FILES = 192
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GPU_UUID_RE = re.compile(r"^GPU-[0-9a-fA-F-]{36}$")
DRIVER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}$")
PARENT_FILES = {
    "backend_publication_arm_contract.json",
    "backend_publication_launch_fence.json",
    "backend_publication_launcher_stdout.log",
    "backend_publication_launcher_stderr.log",
    "backend_publication_launcher_result.json",
    "backend_publication_output_receipt.json",
}


class GstreamerPublicationRuntimeV3Error(NativePublicationPermanentErrorV3):
    """The arm-bound GStreamer runtime is invalid or changed."""


def _fail(blocker: str) -> None:
    raise GstreamerPublicationRuntimeV3Error(blocker)


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail("gstreamer_canonical_json_invalid")


def image_projection_sha256(value: Mapping[str, Any]) -> str:
    """Hash the exact refreeze-v1 projection encoding (without JSONL LF)."""
    try:
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail("gstreamer_container_image_projection_invalid")
    return hashlib.sha256(canonical).hexdigest()


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev), int(info.st_ino), int(info.st_mode),
        int(info.st_nlink), int(info.st_size), int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _is_link(info: os.stat_result) -> bool:
    attrs = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attrs & reparse)


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
        _fail("gstreamer_runtime_input_descriptor_unreadable")


@dataclass(frozen=True)
class _Pin:
    role: str
    path: Path
    fd: int
    snapshot: tuple[int, ...]
    size: int
    sha256: str
    container_path: str | None = None

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
        result = [*self.roles.values(), *self.sources, *self.models, *self.support]
        if self.static_map is not None:
            result.append(self.static_map)
        return tuple(result)

    @property
    def mounted(self) -> tuple[_Pin, ...]:
        return tuple(pin for pin in self.all if pin.container_path is not None)

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
    analytics_socket: dict[str, Any]
    device: dict[str, Any]
    evidence_mapping: dict[str, str]


@dataclass(frozen=True)
class _Completed:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class _MaterializedPin:
    origin: _Pin
    path: Path
    fd: int
    snapshot: tuple[int, ...]


@dataclass
class _MaterializedInputs:
    root: Path
    files: tuple[_MaterializedPin, ...]
    directories: tuple[tuple[Path, tuple[int, ...]], ...]

    def close(self) -> None:
        for value in reversed(self.files):
            try:
                os.close(value.fd)
            except OSError:
                pass
        for path, _ in reversed(self.directories):
            try:
                os.chmod(path, 0o700, follow_symlinks=False)
            except OSError:
                pass


def _project_path(root: Path, raw: Any) -> Path:
    if (
        type(raw) is not str or not raw or len(raw) > 4096
        or "\\" in raw or "\x00" in raw
        or any(ord(char) < 0x20 for char in raw)
    ):
        _fail("gstreamer_runtime_input_path_invalid")
    pure = PurePosixPath(raw)
    if (
        pure.is_absolute() or pure.as_posix() != raw
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail("gstreamer_runtime_input_path_invalid")
    path = root.joinpath(*pure.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        _fail("gstreamer_runtime_input_path_escaped_project_root")
    if resolved != path:
        _fail("gstreamer_runtime_input_path_alias_forbidden")
    return path


def _container_project_path(raw: Any, project_path: str) -> str:
    if (
        type(raw) is not str or not raw or len(raw.encode("utf-8")) > 4096
        or "\\" in raw or "\x00" in raw or "," in raw
        or any(ord(char) < 0x20 for char in raw)
    ):
        _fail("gstreamer_container_input_path_invalid")
    pure = PurePosixPath(raw)
    expected = CONTAINER_PROJECT_ROOT / PurePosixPath(project_path)
    if (
        not pure.is_absolute() or pure.as_posix() != raw
        or pure != expected
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail("gstreamer_container_input_path_invalid")
    return raw


def _absolute_host_file_path(raw: Any) -> Path:
    if (
        type(raw) is not str or not raw.startswith("/") or len(raw) > 4096
        or "\\" in raw or "\x00" in raw or "," in raw
        or any(ord(char) < 0x20 for char in raw)
        or os.path.normpath(raw) != raw
    ):
        _fail("gstreamer_host_executable_path_invalid")
    try:
        path = Path(raw)
        if path.resolve(strict=True) != path:
            raise OSError("alias")
    except (OSError, RuntimeError):
        _fail("gstreamer_host_executable_path_invalid")
    return path


def _open_pin(
    root: Path, role: str, value: Any, *,
    executable: bool = False, mounted: bool = True,
) -> _Pin:
    fields = MOUNT_DESCRIPTOR_FIELDS if mounted else HOST_DESCRIPTOR_FIELDS
    if type(value) is not dict or set(value) != fields:
        _fail("gstreamer_runtime_file_descriptor_fields_drifted")
    size, digest = value.get("size_bytes"), value.get("sha256")
    if (
        type(size) is not int or size <= 0
        or type(digest) is not str or SHA_RE.fullmatch(digest) is None
    ):
        _fail("gstreamer_runtime_file_descriptor_identity_invalid")
    project_path = value.get("path")
    path = (
        _project_path(root, project_path)
        if mounted else _absolute_host_file_path(project_path)
    )
    container_path = (
        _container_project_path(value.get("container_path"), project_path)
        if mounted else None
    )
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
        observed, observed_hash = _fd_hash(fd)
        if (
            _snapshot(before) != _snapshot(opened)
            or _snapshot(opened) != _snapshot(after)
            or observed != size or observed_hash != digest
        ):
            raise OSError("changed")
    except OSError:
        if fd >= 0:
            os.close(fd)
        _fail("gstreamer_runtime_file_descriptor_pin_failed")
    return _Pin(
        role, path, fd, _snapshot(after), size, digest, container_path,
    )


def _open_list(root: Path, role: str, value: Any) -> tuple[_Pin, ...]:
    if type(value) is not list or not value or len(value) > MAX_FILES:
        _fail(f"gstreamer_runtime_{role}_descriptor_set_invalid")
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


def _socket_binding(value: Any, *, endpoint: bool) -> dict[str, Any]:
    fields = ENDPOINT_FIELDS if endpoint else SOCKET_FIELDS
    blocker = (
        "gstreamer_endpoint_socket_binding_invalid"
        if endpoint else "gstreamer_container_engine_socket_binding_invalid"
    )
    if type(value) is not dict or set(value) != fields:
        _fail(blocker)
    path = _absolute_socket_path(value.get("path"), blocker)
    if any(
        type(value.get(field)) is not int or value[field] < 0
        for field in SOCKET_FIELDS - {"path"}
    ):
        _fail(blocker)
    result = {**value, "path": path}
    if endpoint and result.get("container_path") != ANALYTICS_SOCKET_TARGET:
        _fail(blocker)
    _require_socket(result, endpoint=endpoint)
    return result


def _require_socket(value: Mapping[str, Any], *, endpoint: bool) -> None:
    blocker = (
        "gstreamer_endpoint_socket_identity_changed"
        if endpoint else "gstreamer_container_engine_socket_identity_changed"
    )
    try:
        info = os.lstat(str(value["path"]))
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


def _validate_image(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != IMAGE_FIELDS:
        _fail("gstreamer_container_image_contract_fields_drifted")
    if (
        value.get("image_id") != EXPECTED_IMAGE_ID
        or value.get("repository_digest") != EXPECTED_REPOSITORY_DIGEST
        or value.get("inspect_projection_sha256")
        != EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256
        or value.get("base_image_id") != EXPECTED_BASE_IMAGE_ID
    ):
        _fail("gstreamer_container_image_contract_invalid")
    return dict(value)


def _validate_device(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != DEVICE_FIELDS:
        _fail("gstreamer_device_binding_fields_drifted")
    nvidia = value.get("nvidia_decoder_gpu")
    resources = value.get("analytics_resources")
    if (
        type(nvidia) is not dict or set(nvidia) != NVIDIA_FIELDS
        or type(nvidia.get("uuid")) is not str
        or GPU_UUID_RE.fullmatch(nvidia["uuid"]) is None
        or type(nvidia.get("name")) is not str
        or not 3 <= len(nvidia["name"]) <= 160
        or type(nvidia.get("driver_version")) is not str
        or DRIVER_RE.fullmatch(nvidia["driver_version"]) is None
        or value.get("docker_gpus_request") != f"device={nvidia['uuid']}"
        or type(value.get("openvino_device_probe_sha256")) is not str
        or SHA_RE.fullmatch(value["openvino_device_probe_sha256"]) is None
        or value.get("required_openvino_device_ids") != ["CPU"]
        or value.get("nvidia_gpu_counted_as_openvino_gpu") is not False
        or type(resources) is not dict or set(resources) != {"cpu", "gpu"}
    ):
        _fail("gstreamer_device_binding_invalid")
    cpu, gpu = resources.get("cpu"), resources.get("gpu")
    if (
        type(cpu) is not dict or type(gpu) is not dict
        or set(cpu) != ANALYTICS_RESOURCE_FIELDS
        or set(gpu) != ANALYTICS_RESOURCE_FIELDS
        or cpu.get("runtime") != "openvino_cpu" or cpu.get("device") != "CPU"
        or gpu.get("runtime") != "tensorrt_cuda"
        or gpu.get("device") != nvidia["uuid"]
        or any(
            type(item.get("capability_sha256")) is not str
            or SHA_RE.fullmatch(item["capability_sha256"]) is None
            for item in (cpu, gpu)
        )
    ):
        _fail("gstreamer_analytics_resource_binding_invalid")
    return json.loads(_canonical(value))


def _validate_dataset(request: NativePublicationRequestV3, sources: Any) -> None:
    runtime = request.runtime_inputs
    dataset, codec = runtime.get("dataset"), runtime.get("codec")
    if (
        type(dataset) is not dict or codec not in DATASET_BY_CODEC
        or dataset.get("name") != DATASET_BY_CODEC[codec]
        or dataset.get("codec_variant") != codec
        or dataset.get("logical_stream_instances") != 6
        or runtime.get("streams") != 6
        or TOPOLOGY_BY_SCENARIO.get(request.scenario) != request.topology_kind
    ):
        _fail("gstreamer_frozen_kpp_dataset_binding_invalid")
    streams = dataset.get("streams")
    if (
        type(streams) is not list or len(streams) != 6
        or {
            item.get("stream_id") for item in streams
            if type(item) is dict and type(item.get("stream_id")) is int
        } != set(range(6))
        or any(
            type(item) is not dict or type(item.get("stream_id")) is not int
            or str(item.get("codec_name", "")).strip().lower().replace(
                "hevc", "h265"
            ) != codec
            or type(item.get("sha256")) is not str
            or SHA_RE.fullmatch(item["sha256"]) is None
            for item in streams
        )
        or type(sources) is not list or len(sources) != 2
    ):
        _fail("gstreamer_frozen_kpp_dataset_binding_invalid")
    source_hashes = [item.get("sha256") for item in sources if type(item) is dict]
    if (
        len(source_hashes) != 2 or len(set(source_hashes)) != 2
        or {item["sha256"] for item in streams} != set(source_hashes)
        or any(streams[index]["sha256"] != source_hashes[0] for index in range(5))
        or streams[5]["sha256"] != source_hashes[1]
    ):
        _fail("gstreamer_frozen_kpp_stream_source_binding_invalid")


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


def _validate_contract(request: NativePublicationRequestV3) -> _Contract:
    if os.name != "posix" or not Path("/proc/self/fd").is_dir():
        _fail("gstreamer_publication_runtime_requires_linux_procfs")
    runtime = request.runtime_inputs
    dataset = runtime.get("dataset")
    value = dataset.get(RUNTIME_INPUT_KEY) if isinstance(dataset, Mapping) else None
    if type(value) is not dict:
        _fail("gstreamer_runtime_input_contract_missing")
    if set(value) != RUNTIME_FIELDS:
        _fail("gstreamer_runtime_input_contract_fields_drifted")
    if value.get("schema_version") != 3 or value.get("artifact_kind") != RUNTIME_INPUT_KIND:
        _fail("gstreamer_runtime_input_contract_identity_invalid")
    files = value.get("files")
    if type(files) is not dict or set(files) != FILE_ROLES:
        _fail("gstreamer_runtime_file_role_set_drifted")
    if runtime.get("system") != request.system or request.system != "gstreamer_custom":
        _fail("gstreamer_runtime_system_binding_invalid")
    if (
        runtime.get("scenario") != request.scenario
        or runtime.get("topology_kind") != request.topology_kind
    ):
        _fail("gstreamer_runtime_topology_binding_invalid")
    if runtime.get("policy") not in POLICIES:
        _fail("gstreamer_runtime_policy_binding_invalid")
    if runtime.get("codec") not in {"h264", "h265"}:
        _fail("gstreamer_runtime_codec_binding_invalid")
    _validate_dataset(request, value.get("source_files"))
    preprocessing, detect_bin = (
        value.get("preprocessing_contract_sha256"), value.get("detect_bin")
    )
    if type(preprocessing) is not str or SHA_RE.fullmatch(preprocessing) is None:
        _fail("gstreamer_preprocessing_contract_pin_invalid")
    required_detect_tokens = (
        "vastanalyticsqueue", "vastanalyticsterminal", "{branch}",
        "{model_path}", "{model_sha256}",
    )
    if (
        type(detect_bin) is not str or not detect_bin.strip()
        or len(detect_bin.encode("utf-8")) > 64 * 1024
        or "\x00" in detect_bin
        or any(token not in detect_bin for token in required_detect_tokens)
    ):
        _fail("gstreamer_detect_bin_contract_invalid")
    queue = value.get("analytics_queue_max_buffers")
    if type(queue) is not int or not 1 <= queue <= 4096:
        _fail("gstreamer_analytics_queue_contract_invalid")
    _positive(value.get("drain_timeout_s"), "gstreamer_drain_timeout_contract_invalid")
    _positive(value.get("ready_timeout_s"), "gstreamer_ready_timeout_contract_invalid")
    _positive(value.get("container_timeout_s"), "gstreamer_container_timeout_contract_invalid")
    if (
        type(value.get("start_lead_ms")) is not int
        or not 0 <= value["start_lead_ms"] <= 60_000
    ):
        _fail("gstreamer_start_lead_contract_invalid")
    if type(value.get("defer_full_resource_acceptance")) is not bool:
        _fail("gstreamer_resource_acceptance_mode_invalid")
    scratch = value.get("scratch_root")
    if (
        type(scratch) is not str or not scratch.startswith("/")
        or os.path.normpath(scratch) != scratch
    ):
        _fail("gstreamer_runtime_scratch_root_invalid")
    try:
        scratch_path = Path(scratch)
        info = scratch_path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode) or _is_link(info)
            or scratch_path.resolve(strict=True) != scratch_path
        ):
            raise OSError("invalid")
    except (OSError, RuntimeError):
        _fail("gstreamer_runtime_scratch_root_invalid")
    mapping = value.get("evidence_mapping")
    if (
        type(mapping) is not dict
        or set(mapping) != set(request.launcher_evidence_files)
        or len(set(mapping.values())) != len(mapping)
        or any(
            type(source) is not str or not source
            or Path(source).name != source or source in PARENT_FILES
            for source in mapping.values()
        )
    ):
        _fail("gstreamer_child_evidence_mapping_invalid")
    static_map = value.get("static_hybrid_map")
    if (runtime["policy"] == "static_hybrid") != (type(static_map) is dict):
        _fail("gstreamer_static_hybrid_map_binding_invalid")
    embedded = value.get("embedded_artifacts")
    if type(embedded) is not dict or embedded != EXPECTED_EMBEDDED_ARTIFACTS:
        _fail("gstreamer_embedded_artifact_contract_invalid")
    endpoints = value.get("endpoint_sockets")
    if type(endpoints) is not dict or set(endpoints) != {"analytics_execution"}:
        _fail("gstreamer_endpoint_socket_set_invalid")
    return _Contract(
        raw=dict(value),
        image=_validate_image(value["container_image"]),
        engine_socket=_socket_binding(
            value["container_engine_socket"], endpoint=False,
        ),
        analytics_socket=_socket_binding(
            endpoints["analytics_execution"], endpoint=True,
        ),
        device=_validate_device(value["device_binding"]),
        evidence_mapping=dict(mapping),
    )


def _open_pins(request: NativePublicationRequestV3, contract: _Contract) -> _Pins:
    root, raw = request.project_root, contract.raw
    descriptor_sets = (
        raw["source_files"], raw["model_files"], raw["support_files"],
    )
    if any(type(value) is not list for value in descriptor_sets):
        _fail("gstreamer_runtime_descriptor_set_invalid")
    declared_count = len(FILE_ROLES) + sum(len(value) for value in descriptor_sets)
    if raw["static_hybrid_map"] is not None:
        declared_count += 1
    if declared_count > MAX_FILES:
        _fail("gstreamer_runtime_descriptor_set_too_large")
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
                mounted=role != "container_engine",
            )
        sources = _open_list(root, "source_files", raw["source_files"])
        models = _open_list(root, "model_files", raw["model_files"])
        support = _open_list(root, "support_files", raw["support_files"])
        if raw["static_hybrid_map"] is not None:
            static_map = _open_pin(root, "static_hybrid_map", raw["static_hybrid_map"])
        pins = _Pins(roles, sources, models, support, static_map)
        paths = [pin.path for pin in pins.all]
        identities = [(pin.snapshot[0], pin.snapshot[1]) for pin in pins.all]
        targets = [str(pin.container_path) for pin in pins.mounted]
        if (
            len(paths) != len(set(paths))
            or len(identities) != len(set(identities))
            or len(targets) != len(set(targets))
            or len(paths) > MAX_FILES
        ):
            _fail("gstreamer_runtime_descriptor_path_set_invalid")
        expected_source_hashes = {
            stream["sha256"]
            for stream in request.runtime_inputs["dataset"]["streams"]
        }
        if {pin.sha256 for pin in sources} != expected_source_hashes:
            _fail("gstreamer_frozen_kpp_source_descriptor_binding_invalid")
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
            _fail("gstreamer_runtime_input_path_identity_changed")
        if (
            _snapshot(path_info) != pin.snapshot
            or _snapshot(fd_info) != pin.snapshot
            or _is_link(path_info) or not stat.S_ISREG(path_info.st_mode)
            or int(path_info.st_nlink) != 1
            or size != pin.size or digest != pin.sha256
        ):
            _fail("gstreamer_runtime_input_path_identity_changed")


def _require_sockets_unchanged(contract: _Contract) -> None:
    _require_socket(contract.engine_socket, endpoint=False)
    _require_socket(contract.analytics_socket, endpoint=True)


def _invoke_engine(
    engine: _Pin,
    engine_socket: Mapping[str, Any],
    argv: tuple[str, ...],
    timeout_s: float,
) -> _Completed:
    """Execute the held Docker CLI with bounded captures and pass_fds."""

    if (
        not argv or any(type(value) is not str or "\x00" in value for value in argv)
        or not math.isfinite(timeout_s) or timeout_s <= 0
    ):
        _fail("gstreamer_container_engine_argv_invalid")
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
            "gstreamer_container_engine_temporarily_unavailable"
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
            if len(captures[name]) < MAX_CAPTURE_BYTES:
                captures[name].extend(
                    chunk[: MAX_CAPTURE_BYTES - len(captures[name])]
                )

    threads = [
        threading.Thread(target=reader, args=(name, stream), daemon=True)
        for name, stream in (
            ("stdout", process.stdout), ("stderr", process.stderr),
        )
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
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass
    if any(thread.is_alive() for thread in threads):
        _fail("gstreamer_container_capture_drain_failed")
    if exceeded.is_set():
        _fail("gstreamer_container_capture_limit_exceeded")
    if timed_out:
        raise NativePublicationTransientErrorV3(
            "gstreamer_container_execution_timed_out"
        )
    return _Completed(
        int(process.returncode), bytes(captures["stdout"]),
        bytes(captures["stderr"]),
    )


def _image_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    config = value.get("Config")
    if type(config) is not dict or type(config.get("Labels")) is not dict:
        _fail("gstreamer_container_image_inspect_payload_invalid")
    return {
        "Architecture": value.get("Architecture"),
        "Config": {
            "Entrypoint": config.get("Entrypoint"),
            "Labels": {
                key: config["Labels"].get(key)
                for key in sorted(EXPECTED_IMAGE_LABELS)
            },
            "User": config.get("User"),
        },
        "Created": value.get("Created"),
        "Id": value.get("Id"),
        "Os": value.get("Os"),
        "RepoDigests": sorted(value.get("RepoDigests") or []),
    }


def _inspect_image(pins: _Pins, contract: _Contract) -> None:
    completed = _invoke_engine(
        pins.roles["container_engine"], contract.engine_socket,
        ("image", "inspect", EXPECTED_IMAGE_REFERENCE), 60.0,
    )
    if completed.returncode != 0 or completed.stderr:
        _fail("gstreamer_container_image_inspect_failed")
    try:
        decoded = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeError):
        _fail("gstreamer_container_image_inspect_payload_invalid")
    if type(decoded) is not list or len(decoded) != 1 or type(decoded[0]) is not dict:
        _fail("gstreamer_container_image_inspect_payload_invalid")
    projection = _image_projection(decoded[0])
    if (
        projection["Id"] != EXPECTED_IMAGE_ID
        or projection["Os"] != "linux"
        or projection["Architecture"] != "amd64"
        or projection["Created"] != "1970-01-01T00:00:00Z"
        or projection["RepoDigests"] != [EXPECTED_REPOSITORY_DIGEST]
        or projection["Config"]["Entrypoint"] != [EXPECTED_IMAGE_ENTRYPOINT]
        or projection["Config"]["User"] != EXPECTED_IMAGE_USER
        or projection["Config"]["Labels"] != EXPECTED_IMAGE_LABELS
        or image_projection_sha256(projection)
        != EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256
    ):
        _fail("gstreamer_container_image_identity_changed")


def _mount(source: str, target: str, *, readonly: bool) -> tuple[str, str]:
    if "," in source or "," in target or "\x00" in source or "\x00" in target:
        _fail("gstreamer_container_mount_path_invalid")
    return "--mount", (
        f"type=bind,src={source},dst={target}"
        + (",readonly" if readonly else "")
    )


def _materialized_relative(pin: _Pin) -> PurePosixPath:
    if pin.container_path is None:
        _fail("gstreamer_runtime_materialized_path_invalid")
    try:
        relative = PurePosixPath(pin.container_path).relative_to(
            CONTAINER_PROJECT_ROOT
        )
    except ValueError:
        _fail("gstreamer_runtime_materialized_path_invalid")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        _fail("gstreamer_runtime_materialized_path_invalid")
    return relative


def _copy_materialized_pin(pin: _Pin, root: Path) -> _MaterializedPin:
    target = root.joinpath(*_materialized_relative(pin).parts)
    write_fd = read_fd = -1
    successful = False
    try:
        write_fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.lseek(pin.fd, 0, os.SEEK_SET)
        observed = 0
        digest = hashlib.sha256()
        while True:
            chunk = os.read(pin.fd, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            digest.update(chunk)
            offset = 0
            while offset < len(chunk):
                written = os.write(write_fd, chunk[offset:])
                if written <= 0:
                    raise OSError("short write")
                offset += written
        os.lseek(pin.fd, 0, os.SEEK_SET)
        written = os.fstat(write_fd)
        if (
            observed != pin.size or digest.hexdigest() != pin.sha256
            or int(written.st_size) != pin.size
            or not stat.S_ISREG(written.st_mode) or int(written.st_nlink) != 1
        ):
            raise OSError("copy identity changed")
        os.fchmod(write_fd, 0o444)
        os.fsync(write_fd)
        os.close(write_fd)
        write_fd = -1
        before = target.lstat()
        read_fd = os.open(
            target, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened, after = os.fstat(read_fd), target.lstat()
        copied_size, copied_hash = _fd_hash(read_fd)
        if (
            _snapshot(before) != _snapshot(opened)
            or _snapshot(opened) != _snapshot(after) or _is_link(after)
            or not stat.S_ISREG(after.st_mode) or int(after.st_nlink) != 1
            or (int(after.st_mode) & 0o777) != 0o444
            or copied_size != pin.size or copied_hash != pin.sha256
        ):
            raise OSError("copy identity changed")
        result = _MaterializedPin(pin, target, read_fd, _snapshot(after))
        successful = True
        return result
    except OSError:
        _fail("gstreamer_runtime_input_materialization_failed")
    finally:
        for descriptor in (write_fd, -1 if successful else read_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


def _materialize_inputs(pins: _Pins, root: Path) -> _MaterializedInputs:
    directories: set[Path] = {root}
    for pin in pins.mounted:
        parent = _materialized_relative(pin).parent
        while parent != PurePosixPath("."):
            directories.add(root.joinpath(*parent.parts))
            parent = parent.parent
    ordered = tuple(sorted(
        directories,
        key=lambda path: (len(path.relative_to(root).parts), path.as_posix()),
    ))
    files: list[_MaterializedPin] = []
    try:
        for path in ordered:
            path.mkdir(mode=0o700)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or _is_link(info):
                raise OSError("directory identity invalid")
        for pin in sorted(pins.mounted, key=lambda item: str(item.container_path)):
            files.append(_copy_materialized_pin(pin, root))
        for path in reversed(ordered):
            os.chmod(path, 0o555, follow_symlinks=False)
        snapshots: list[tuple[Path, tuple[int, ...]]] = []
        for path in ordered:
            info = path.lstat()
            if (
                not stat.S_ISDIR(info.st_mode) or _is_link(info)
                or (int(info.st_mode) & 0o777) != 0o555
            ):
                raise OSError("directory identity invalid")
            snapshots.append((path, _snapshot(info)))
        return _MaterializedInputs(root, tuple(files), tuple(snapshots))
    except BaseException:
        for value in reversed(files):
            try:
                os.close(value.fd)
            except OSError:
                pass
        for path in reversed(ordered):
            try:
                os.chmod(path, 0o700, follow_symlinks=False)
            except OSError:
                pass
        raise


def _require_materialized_unchanged(value: _MaterializedInputs) -> None:
    for path, expected in value.directories:
        try:
            info = path.lstat()
        except OSError:
            _fail("gstreamer_runtime_materialized_input_changed")
        if (
            _snapshot(info) != expected or not stat.S_ISDIR(info.st_mode)
            or _is_link(info) or (int(info.st_mode) & 0o777) != 0o555
        ):
            _fail("gstreamer_runtime_materialized_input_changed")
    for item in value.files:
        try:
            path_info, fd_info = item.path.lstat(), os.fstat(item.fd)
            size, digest = _fd_hash(item.fd)
        except OSError:
            _fail("gstreamer_runtime_materialized_input_changed")
        if (
            _snapshot(path_info) != item.snapshot
            or _snapshot(fd_info) != item.snapshot or _is_link(path_info)
            or not stat.S_ISREG(path_info.st_mode) or int(path_info.st_nlink) != 1
            or (int(path_info.st_mode) & 0o777) != 0o444
            or size != item.origin.size or digest != item.origin.sha256
        ):
            _fail("gstreamer_runtime_materialized_input_changed")


def _input_mounts(materialized: _MaterializedInputs) -> list[str]:
    return [*_mount(
        str(materialized.root), str(CONTAINER_PROJECT_ROOT), readonly=True,
    )]


def _security_argv(contract: _Contract) -> list[str]:
    return [
        "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", str(MAX_CONTAINER_PIDS), "--ipc", "none", "--gpus",
        str(contract.device["docker_gpus_request"]),
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=1073741824",
        "--tmpfs", "/run/vast:rw,nosuid,nodev,noexec,size=16777216",
    ]


def _probe_embedded_artifacts(pins: _Pins, contract: _Contract) -> None:
    arguments = [
        *_security_argv(contract), "--entrypoint", "/usr/bin/sha256sum",
        EXPECTED_IMAGE_ID, *EXPECTED_EMBEDDED_ARTIFACTS,
    ]
    completed = _invoke_engine(
        pins.roles["container_engine"], contract.engine_socket,
        tuple(arguments), 120.0,
    )
    if completed.returncode != 0 or completed.stderr:
        _fail("gstreamer_embedded_artifact_probe_failed")
    try:
        lines = completed.stdout.decode("ascii").splitlines()
    except UnicodeError:
        _fail("gstreamer_embedded_artifact_probe_invalid")
    observed: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (/.+)", line)
        if match is None or match.group(2) in observed:
            _fail("gstreamer_embedded_artifact_probe_invalid")
        observed[match.group(2)] = match.group(1)
    if observed != EXPECTED_EMBEDDED_ARTIFACTS:
        _fail("gstreamer_embedded_artifact_identity_changed")


def _probe_openvino_devices(
    pins: _Pins, contract: _Contract, materialized: _MaterializedInputs,
) -> None:
    probe_path = str(pins.roles["device_probe"].container_path)
    arguments = [
        *_security_argv(contract), *_input_mounts(materialized),
        "--env", "HOME=/tmp", "--env", "XDG_CACHE_HOME=/tmp",
        "--env", "GST_REGISTRY=/opt/vast/share/gstreamer-registry.bin",
        "--env", "GST_REGISTRY_UPDATE=no",
        "--workdir", str(CONTAINER_PROJECT_ROOT),
        "--entrypoint", "/usr/bin/python3", EXPECTED_IMAGE_ID,
        "-B", probe_path,
    ]
    completed = _invoke_engine(
        pins.roles["container_engine"], contract.engine_socket,
        tuple(arguments), 180.0,
    )
    if completed.returncode != 0 or completed.stderr:
        _fail("gstreamer_device_probe_failed")
    try:
        probe = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeError):
        _fail("gstreamer_device_probe_invalid")
    if (
        type(probe) is not dict or probe.get("schema_version") != 1
        or probe.get("artifact_kind") != "vast_openvino_checkpoint_device_probe"
        or not str(probe.get("openvino_version", "")).strip()
        or hashlib.sha256(_canonical(probe)).hexdigest()
        != contract.device["openvino_device_probe_sha256"]
    ):
        _fail("gstreamer_device_probe_identity_changed")
    devices, elements = probe.get("available_devices"), probe.get("gstreamer_elements")
    if type(devices) is not list or type(elements) is not dict:
        _fail("gstreamer_device_probe_invalid")
    device_ids = {
        item.get("device_id") for item in devices if type(item) is dict
    }
    if not set(contract.device["required_openvino_device_ids"]) <= device_ids:
        _fail("gstreamer_required_openvino_device_missing")
    if any(
        type(elements.get(name)) is not dict
        or elements[name].get("available") is not True
        for name in REQUIRED_GSTREAMER_ELEMENTS
    ):
        _fail("gstreamer_required_element_missing")


def _probe_nvidia_device(pins: _Pins, contract: _Contract) -> None:
    arguments = [
        *_security_argv(contract), "--entrypoint", "/usr/bin/nvidia-smi",
        EXPECTED_IMAGE_ID, "--query-gpu=name,uuid,driver_version",
        "--format=csv,noheader,nounits",
    ]
    completed = _invoke_engine(
        pins.roles["container_engine"], contract.engine_socket,
        tuple(arguments), 120.0,
    )
    if completed.returncode != 0 or completed.stderr:
        _fail("gstreamer_nvidia_device_probe_failed")
    try:
        lines = [
            line.strip() for line in completed.stdout.decode("ascii").splitlines()
            if line.strip()
        ]
    except UnicodeError:
        _fail("gstreamer_nvidia_device_probe_invalid")
    expected = contract.device["nvidia_decoder_gpu"]
    if lines != [
        f"{expected['name']}, {expected['uuid']}, {expected['driver_version']}"
    ]:
        _fail("gstreamer_nvidia_device_identity_changed")


def _container_argv(
    request: NativePublicationRequestV3,
    contract: _Contract,
    pins: _Pins,
    materialized: _MaterializedInputs,
    runtime_output: Path,
) -> tuple[str, ...]:
    runtime, files = request.runtime_inputs, pins.roles
    arguments = [
        *_security_argv(contract),
        "--user", f"{os.getuid()}:{os.getgid()}",
        *_input_mounts(materialized),
        *_mount(runtime_output.as_posix(), CONTAINER_OUTPUT_ROOT, readonly=False),
        *_mount(
            str(contract.analytics_socket["path"]), ANALYTICS_SOCKET_TARGET,
            readonly=True,
        ),
        "--workdir", str(CONTAINER_PROJECT_ROOT),
        *deterministic_numeric_thread_environment_argv_v1(),
        "--env", "PYTHONDONTWRITEBYTECODE=1",
        "--env", "HOME=/tmp", "--env", "XDG_CACHE_HOME=/tmp",
        "--env", "GST_REGISTRY=/opt/vast/share/gstreamer-registry.bin",
        "--env", "GST_REGISTRY_UPDATE=no",
        "--env", "NVIDIA_DRIVER_CAPABILITIES=compute,utility,video",
        EXPECTED_IMAGE_ID,
        "--config", str(files["experiments_config"].container_path),
        "--datasets", str(files["datasets_config"].container_path),
        "--scenario", request.scenario,
        "--codec", str(runtime["codec"]), "--policy", str(runtime["policy"]),
        "--deadline-ms", str(float(runtime["deadline_ms"])),
        "--analytics-execution-socket", ANALYTICS_SOCKET_TARGET,
        "--analytics-preprocessing-contract-sha256",
        str(contract.raw["preprocessing_contract_sha256"]),
        "--binary", "/usr/local/bin/vast_native_gst_probe",
        "--source-binary", "/usr/local/bin/vast_checkpoint_source",
        "--output-dir", CONTAINER_OUTPUT_ROOT, "--run-id", request.run_id,
        "--duration", str(int(runtime["duration_s"])),
        "--drain-timeout", str(float(contract.raw["drain_timeout_s"])),
        "--ready-timeout", str(float(contract.raw["ready_timeout_s"])),
        "--start-lead-ms", str(int(contract.raw["start_lead_ms"])),
        "--use-preregistered-window", "--detect-bin", str(contract.raw["detect_bin"]),
        "--analytics-model-manifest",
        str(files["analytics_model_manifest"].container_path),
        "--analytics-execution-manifest",
        str(files["analytics_execution_manifest"].container_path),
        "--policy-capability-manifest",
        str(files["policy_capability_manifest"].container_path),
        "--policy-calibration", str(files["policy_calibration"].container_path),
        "--analytics-queue-max-buffers",
        str(int(contract.raw["analytics_queue_max_buffers"])),
        "--checkpoint-analytics-mode", "native_terminal_socket_v1",
        "--gst-registry-template", "/opt/vast/share/gstreamer-registry.bin",
        "--gst-plugin-path", "/opt/vast/lib/gstreamer-1.0",
        "--execute-publication-runtime",
    ]
    if pins.static_map is not None:
        arguments.extend((
            "--static-hybrid-map", str(pins.static_map.container_path),
        ))
    if contract.raw["defer_full_resource_acceptance"]:
        arguments.append("--defer-full-resource-acceptance")
    return tuple(arguments)


def _validate_status(
    payload: bytes, request: NativePublicationRequestV3, contract: _Contract,
) -> None:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, TypeError, UnicodeError):
        _fail("gstreamer_native_runtime_terminal_status_invalid")
    runtime = request.runtime_inputs
    acceptance = value.get("publication_acceptance") if type(value) is dict else None
    expected_status = (
        "pending_full_resource_validation"
        if contract.raw["defer_full_resource_acceptance"]
        else "accepted_native_checkpoint_arm"
    )
    if (
        type(value) is not dict or value.get("scenario") != request.scenario
        or value.get("topology_kind") != request.topology_kind
        or value.get("accepted_benchmark_sidecars_written") is not True
        or value.get("publication_blockers") != []
        or type(acceptance) is not dict or acceptance.get("status") != expected_status
        or acceptance.get("run_id") != request.run_id
        or acceptance.get("system") != request.system
        or acceptance.get("scenario") != request.scenario
        or acceptance.get("codec") != runtime["codec"]
        or acceptance.get("policy") != runtime["policy"]
        or acceptance.get("topology_kind") != request.topology_kind
    ):
        _fail("gstreamer_native_runtime_terminal_status_invalid")
    try:
        matches = math.isclose(
            float(acceptance.get("deadline_ms")),
            float(runtime["deadline_ms"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    except (TypeError, ValueError):
        matches = False
    if not matches:
        _fail("gstreamer_native_runtime_terminal_status_invalid")


def _copy_evidence(
    runtime_output: Path,
    request: NativePublicationRequestV3,
    mapping: Mapping[str, str],
    *,
    _fault_hook: Callable[[str], None] | None = None,
) -> None:
    try:
        materialize_publication_child_evidence_group_v1(
            project_root=request.project_root,
            source_dir=runtime_output,
            output_dir=request.output_dir,
            target_names=request.launcher_evidence_files,
            evidence_mapping=dict(mapping),
            allowed_preexisting_names=(
                (Path(os.path.abspath(request.arm_contract_path)).name,)
                if Path(os.path.abspath(request.arm_contract_path)).parent
                == Path(os.path.abspath(request.output_dir))
                else ()
            ),
            maximum_bytes=MAX_EVIDENCE_BYTES,
            label="GStreamer child evidence",
            after_physical_commit_step=_fault_hook,
        )
    except PublicationChildEvidenceMaterializerV1Error:
        _fail("gstreamer_child_evidence_materialization_failed")


def run_checkpoint_gstreamer_publication_runtime_v3(
    request: NativePublicationRequestV3,
) -> NativePublicationOutcomeV3:
    """Run one exact immutable-image arm and map declared child evidence."""

    contract = _validate_contract(request)
    pins = _open_pins(request, contract)
    try:
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        _inspect_image(pins, contract)
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        with tempfile.TemporaryDirectory(
            prefix=f"vast-gstreamer-v3-{request.arm_id}-",
            dir=str(contract.raw["scratch_root"]),
        ) as name:
            scratch = Path(name)
            if _is_link(scratch.lstat()):
                _fail("gstreamer_runtime_scratch_custody_invalid")
            materialized = _materialize_inputs(pins, scratch / "input")
            try:
                _require_materialized_unchanged(materialized)
                _require_pins_unchanged(pins)
                _require_sockets_unchanged(contract)
                _probe_embedded_artifacts(pins, contract)
                _require_materialized_unchanged(materialized)
                _require_pins_unchanged(pins)
                _require_sockets_unchanged(contract)
                _probe_openvino_devices(pins, contract, materialized)
                _require_materialized_unchanged(materialized)
                _require_pins_unchanged(pins)
                _require_sockets_unchanged(contract)
                _probe_nvidia_device(pins, contract)
                _require_materialized_unchanged(materialized)
                _require_pins_unchanged(pins)
                _require_sockets_unchanged(contract)
                runtime_output = scratch / "run"
                runtime_output.mkdir(mode=0o700)
                arguments = _container_argv(
                    request, contract, pins, materialized, runtime_output,
                )
                completed = _invoke_engine(
                    pins.roles["container_engine"], contract.engine_socket,
                    arguments, float(contract.raw["container_timeout_s"]),
                )
                _require_materialized_unchanged(materialized)
                _require_pins_unchanged(pins)
                _require_sockets_unchanged(contract)
                if completed.returncode == 2:
                    raise NativePublicationTransientErrorV3(
                        "gstreamer_native_runtime_incomplete_terminal_outcome"
                    )
                if completed.returncode != 0 or completed.stderr:
                    _fail("gstreamer_native_runtime_failed")
                _validate_status(completed.stdout, request, contract)
                _copy_evidence(
                    runtime_output, request, contract.evidence_mapping,
                )
            finally:
                materialized.close()
        _require_pins_unchanged(pins)
        _require_sockets_unchanged(contract)
        return NativePublicationOutcomeV3(exit_code=0)
    finally:
        pins.close()


__all__ = [
    "EXPECTED_IMAGE_ID", "EXPECTED_IMAGE_REFERENCE",
    "EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256",
    "EXPECTED_REPOSITORY_DIGEST",
    "GstreamerPublicationRuntimeV3Error",
    "image_projection_sha256",
    "RUNTIME_INPUT_KEY",
    "RUNTIME_INPUT_KIND",
    "run_checkpoint_gstreamer_publication_runtime_v3",
]
